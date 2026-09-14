"""One-shot, capture-only KRA race-plan/entry-sheet pilot.

This module never opens the operating database and never produces an F_t admission.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from horse_racing.collectors.kra_api import ENTRY_SHEET_ENDPOINT, RACE_PLAN_ENDPOINT
from horse_racing.parsers.entry_sheet import parse_entry_sheet_page
from horse_racing.parsers.race_day import RacePlanItem, parse_items

ALLOWED = {ENTRY_SHEET_ENDPOINT: "entry_sheet", RACE_PLAN_ENDPOINT: "race_plan"}


class CaptureError(RuntimeError):
    pass


class BudgetTransport(httpx.BaseTransport):
    """Counts actual sends, including attempted redirects/retries (redirects are disabled)."""

    def __init__(self, inner: httpx.BaseTransport, limit: int = 12) -> None:
        self.inner = inner
        self.limit = limit
        self.count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.count >= self.limit:
            raise CaptureError("transport request budget exhausted")
        self.count += 1
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


class CaptureStore:
    def __init__(self, root: Path, clock: Callable[[], int] | None = None) -> None:
        self.root = root
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.root.mkdir(parents=True, exist_ok=False)
        self.raw = root / "raw_private"
        self.raw.mkdir(mode=0o700)
        self.raw.chmod(0o700)
        self.journal = root / "capture_journal.jsonl"
        self.last_ms = 0

    def now(self) -> int:
        value = self.clock()
        if value < self.last_ms:
            raise CaptureError("clock regressed between capture stages")
        self.last_ms = value
        return value

    def append(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        fd = os.open(self.journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())

    def save_raw(self, body: bytes) -> str:
        digest = hashlib.sha256(body).hexdigest()
        path = self.raw / digest
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        return digest


def _strict_meta(payload: dict[str, Any], *, expected_page: int, page_size: int) -> dict[str, int]:
    response = payload.get("response", payload)
    if not isinstance(response, dict):
        raise CaptureError("response root missing")
    header = response.get("header")
    if not isinstance(header, dict) or str(header.get("resultCode", "")) not in {"00", "0000"}:
        raise CaptureError("header success code missing or unsuccessful")
    body = response.get("body")
    if not isinstance(body, dict):
        raise CaptureError("response body missing")
    meta = {}
    for key in ("totalCount", "pageNo", "numOfRows"):
        if key not in body or isinstance(body[key], bool):
            raise CaptureError(f"explicit {key} missing")
        try:
            value = int(body[key])
        except (TypeError, ValueError) as exc:
            raise CaptureError(f"invalid {key}") from exc
        if str(body[key]).strip() != str(value):
            raise CaptureError(f"invalid {key}")
        meta[key] = value
    if meta["totalCount"] < 0 or meta["pageNo"] != expected_page:
        raise CaptureError("totalCount/pageNo invalid")
    if meta["numOfRows"] != page_size:
        raise CaptureError("numOfRows differs from request")
    container = body.get("items") or {}
    if not isinstance(container, dict):
        raise CaptureError("items container invalid")
    raw_items = container.get("item", [])
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if raw_items in (None, ""):
        raw_items = []
    if not isinstance(raw_items, list):
        raise CaptureError("items list invalid")
    meta["actualItems"] = len(raw_items)
    if len(raw_items) > page_size:
        raise CaptureError("actual item count exceeds numOfRows")
    return meta


class PilotCapture:
    def __init__(
        self,
        store: CaptureStore,
        *,
        service_key: str,
        base_url: str,
        transport: BudgetTransport,
        timeout_seconds: float = 10.0,
        attempts: int = 2,
    ) -> None:
        self.store = store
        self.service_key = service_key
        self.transport = transport
        self.attempts = attempts
        parser_dir = Path(__file__).resolve().parents[1] / "parsers"
        self.parser_hashes = {
            ENTRY_SHEET_ENDPOINT: hashlib.sha256(
                (parser_dir / "entry_sheet.py").read_bytes()
            ).hexdigest(),
            RACE_PLAN_ENDPOINT: hashlib.sha256(
                (parser_dir / "race_day.py").read_bytes()
            ).hexdigest(),
        }
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def page(self, endpoint: str, public: dict[str, str | int], *, batch: str) -> dict[str, Any]:
        if endpoint not in ALLOWED:
            raise CaptureError("endpoint not allowed")
        if "ServiceKey" in public:
            raise CaptureError("secret in public params")
        page_no = int(public["pageNo"])
        page_size = int(public["numOfRows"])
        last: dict[str, Any] = {}
        for attempt in range(1, self.attempts + 1):
            if self.transport.count >= self.transport.limit:
                raise CaptureError("transport request budget exhausted")
            requested = self.store.now()
            body: bytes | None = None
            status: int | None = None
            failure: str | None = None
            try:
                response = self.client.get(
                    endpoint.lstrip("/"), params={**public, "ServiceKey": self.service_key}
                )
                status = response.status_code
                body = response.content
            except (httpx.HTTPError, CaptureError) as exc:
                failure = type(exc).__name__
            received = self.store.now()
            digest = self.store.save_raw(body) if body is not None else None
            parsed: list[Any] = []
            meta: dict[str, int] | None = None
            if body is not None:
                try:
                    if status != 200:
                        raise CaptureError("HTTP status not 200 (redirects are not followed)")
                    payload = json.loads(body)
                    meta = _strict_meta(payload, expected_page=page_no, page_size=page_size)
                    parsed = (
                        parse_entry_sheet_page(payload).items
                        if endpoint == ENTRY_SHEET_ENDPOINT
                        else parse_items(payload, RacePlanItem)
                    )
                    if len(parsed) != meta["actualItems"]:
                        raise CaptureError("parsed item count mismatch")
                except (ValueError, TypeError, KeyError, CaptureError) as exc:
                    failure = type(exc).__name__
            parsed_at = self.store.now()
            event = {
                "batch_id": batch,
                "kind": ALLOWED[endpoint],
                "endpoint": endpoint,
                "public_params": public,
                "attempt": attempt,
                "requested_at_ms": requested,
                "received_at_ms": received,
                "parsed_at_ms": parsed_at,
                "status_code": status,
                "body_sha256": digest,
                "body_bytes": len(body) if body is not None else None,
                "parser_code_sha256": self.parser_hashes[endpoint],
                "credential_reflected": bool(body and self.service_key.encode() in body),
                "meta": meta,
                "failure": failure,
                "published_at_ms": None,
                "effective_at_ms": None,
            }
            self.store.append(event)
            ack = self.store.now()
            self.store.append(
                {
                    "kind": "capture_ack",
                    "batch_id": batch,
                    "body_sha256": digest,
                    "attempt": attempt,
                    "commit_completed_at_ms": ack,
                }
            )
            last = {**event, "commit_completed_at_ms": ack, "items": parsed}
            if failure is None:
                return last
            if status is not None and status < 500 and status not in {408, 429}:
                break
        return last

    def batch(
        self, endpoint: str, race_date: str, *, batch_id: str, page_size: int = 1000
    ) -> dict[str, Any]:
        if endpoint not in ALLOWED:
            raise CaptureError("endpoint not allowed")
        public = (
            {"meet": 1, "rc_date": race_date, "_type": "json"}
            if endpoint == ENTRY_SHEET_ENDPOINT
            else {"rccrs_cd": 1, "race_dt": race_date, "_type": "json"}
        )
        pages: list[dict[str, Any]] = []
        total: int | None = None
        expected_pages = 1
        if self.transport.count < self.transport.limit:
            page = self.page(
                endpoint, {**public, "pageNo": 1, "numOfRows": page_size}, batch=batch_id
            )
            pages.append(page)
            if page["failure"] is None and page["meta"] is not None:
                total = page["meta"]["totalCount"]
                expected_pages = max(1, math.ceil(total / page_size))
        if pages and pages[0]["failure"] is None and total is not None:
            for page_no in range(2, expected_pages + 1):
                if self.transport.count >= self.transport.limit:
                    break
                page = self.page(
                    endpoint, {**public, "pageNo": page_no, "numOfRows": page_size}, batch=batch_id
                )
                pages.append(page)
                if page["failure"] is not None:
                    break
        return audit_batch(
            pages,
            endpoint=endpoint,
            race_date=race_date,
            expected_pages=expected_pages,
            batch_id=batch_id,
        )


def audit_batch(
    pages: list[dict[str, Any]],
    *,
    endpoint: str,
    race_date: str,
    expected_pages: int,
    batch_id: str,
) -> dict[str, Any]:
    issues: list[str] = []
    numbers = [p["meta"]["pageNo"] for p in pages if p.get("meta")]
    if numbers != list(range(1, expected_pages + 1)):
        issues.append("missing_or_duplicate_pages")
    if any(p.get("failure") for p in pages):
        issues.append("page_failure")
    totals = {p["meta"]["totalCount"] for p in pages if p.get("meta")}
    if len(totals) != 1:
        issues.append("inconsistent_totalCount")
    items = [item for page in pages for item in page.get("items", [])]
    total = next(iter(totals)) if len(totals) == 1 else None
    if total is None or len(items) != total:
        issues.append("item_count_mismatch")
    if any(
        (page.get("meta") or {}).get("actualItems") == 0
        and total
        and (page.get("meta") or {}).get("pageNo", 0) < expected_pages
        for page in pages
    ):
        issues.append("middle_empty_page")
    if endpoint == ENTRY_SHEET_ENDPOINT:
        keys = [
            (x.meet_name, x.race_date.isoformat(), x.race_number, x.horse_number, x.horse_id)
            for x in items
        ]
        if any(
            x.race_date.strftime("%Y%m%d") != race_date
            or x.meet_name not in {"서울", "SEOUL", "Seoul"}
            for x in items
        ):
            issues.append("date_or_meet_mixed")
        if len(set(keys)) != len(keys):
            issues.append("duplicate_source_keys")
        slots = [(k[0], k[1], k[2], k[3]) for k in keys]
        if len(set(slots)) != len(slots):
            issues.append("horse_number_identity_conflict")
        horse_slots = [(k[0], k[1], k[2], k[4]) for k in keys]
        if len(set(horse_slots)) != len(horse_slots):
            issues.append("horse_id_identity_conflict")
        race_counts = {str(k): v for k, v in sorted(Counter(x.race_number for x in items).items())}
    else:
        keys = [(x.meet_name, x.race_date.isoformat(), x.race_number) for x in items]
        if any(
            x.race_date.strftime("%Y%m%d") != race_date
            or x.meet_name not in {"서울", "SEOUL", "Seoul"}
            for x in items
        ):
            issues.append("date_or_meet_mixed")
        if len(set(keys)) != len(keys):
            issues.append("duplicate_race_keys")
        race_counts = {}
    key_hash = hashlib.sha256(json.dumps(sorted(keys), ensure_ascii=False).encode()).hexdigest()
    values = [x.model_dump(mode="json", by_alias=True) for x in items]
    values.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    value_hash = hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return {
        "batch_id": batch_id,
        "endpoint": endpoint,
        "complete": not issues,
        "credential_reflected": any(p.get("credential_reflected") for p in pages),
        "issues": issues,
        "totalCount_day": total,
        "actual_items_day": len(items),
        "race_counts": race_counts,
        "page_numbers": numbers,
        "expected_pages": expected_pages,
        "raw_sha256": [p.get("body_sha256") for p in pages],
        "source_keys": [list(k) for k in sorted(keys)],
        "key_sha256": key_hash,
        "value_sha256": value_hash,
        "completed_at_ms": pages[-1]["commit_completed_at_ms"] if pages else None,
        "items": items,
    }


def schedule_cutoff(schedule: RacePlanItem, completed_at_ms: int) -> dict[str, Any]:
    raw = schedule.scheduled_time
    if not raw:
        return {"scheduled_time_raw": None, "cutoff_at_ms": None, "margin_minutes": None}
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) not in {3, 4}:
        return {"scheduled_time_raw": raw, "cutoff_at_ms": None, "margin_minutes": None}
    digits = digits.zfill(4)
    hour, minute = int(digits[:2]), int(digits[2:])
    if hour > 23 or minute > 59:
        return {"scheduled_time_raw": raw, "cutoff_at_ms": None, "margin_minutes": None}
    scheduled = datetime.combine(schedule.race_date, datetime.min.time(), tzinfo=UTC).replace(
        hour=hour, minute=minute
    )
    # Korea Standard Time is UTC+09:00, without daylight saving time.
    cutoff_ms = int(scheduled.timestamp() * 1000) - 9 * 3600_000 - 30 * 60_000
    return {
        "scheduled_time_raw": raw,
        "cutoff_at_ms": cutoff_ms,
        "margin_minutes": (cutoff_ms - completed_at_ms) / 60_000,
    }

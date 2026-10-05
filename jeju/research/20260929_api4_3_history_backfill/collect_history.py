"""Archive immutable annual KRA API4_3 race-result response bytes for Jeju.

The race-result API is mixed. Rows whose venue is 제주 and whose ``rank``
starts with ``제`` are counted as candidates only; the prefix is not proof of
an individual horse's breed. This collector never writes to a database or to
the existing raw result archives.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from horse_racing.collectors.kra_api import (
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]
OLD_ARCHIVE = PROJECT_ROOT / "data/raw/jeju_native_results"
PHASE2_DB = PROJECT_ROOT / "data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3"
START_YEAR = 2002
END_YEAR = 2025
PAGE_SIZE = 20_000


def items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    wrapped = response_body(payload).get("items") or {}
    rows = wrapped.get("item") if isinstance(wrapped, dict) else None
    if rows is None:
        return []
    if isinstance(rows, dict):
        return [rows]
    if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
        return rows
    raise ValueError("Unexpected result item structure")


def immutable_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create_run() -> tuple[str, Path]:
    base = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    attempt_id = base
    suffix = 1
    root = ROOT / "attempts"
    root.mkdir(parents=True, exist_ok=True)
    while True:
        attempt_dir = root / attempt_id
        try:
            attempt_dir.mkdir()
            return attempt_id, attempt_dir
        except FileExistsError:
            suffix += 1
            attempt_id = f"{base}-{suffix}"


def safe_exception(exc: BaseException, service_key: str | None) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current)
        if service_key:
            message = message.replace(service_key, "[REDACTED]")
        message = re.sub(
            r"(?i)(servicekey|service_key)=([^&\s]+)",
            r"\1=[REDACTED]",
            message,
        )
        chain.append({"type": type(current).__name__, "message": message})
        current = current.__cause__ or current.__context__
    return chain


def empty_year_result(year: int) -> dict[str, Any]:
    return {
        "year": year,
        "status": "running",
        "source_pages": [],
        "actual_response_rows": 0,
        "meet_value_counts": {},
        "rank_value_counts": {},
        "rows_with_meet_jeju": 0,
        "rows_with_rank_prefix_je": 0,
        "jeju_rank_prefix_candidate_rows": 0,
        "jeju_rank_prefix_candidate_races": 0,
        "out_of_year_rows": 0,
    }


def collect_year(
    year: int,
    attempt_dir: Path,
    client: KraApiClient,
    service_key: str | None,
) -> dict[str, Any]:
    result = empty_year_result(year)
    pages_dir = attempt_dir / str(year) / "source_pages"
    candidate_races: set[tuple[str, str]] = set()
    meet_values: Counter[str] = Counter()
    rank_values: Counter[str] = Counter()
    total_counts: set[int] = set()
    actual_page_sizes: set[int] = set()
    try:
        for page_no, page in enumerate(
            client.iter_pages(
                endpoint=RACE_RESULT_WITH_SECTIONS_ENDPOINT,
                operation=RACE_RESULT_WITH_SECTIONS_OPERATION,
                public_params={"meet": 2, "rc_year": str(year), "_type": "json"},
                page_size=PAGE_SIZE,
                service_key_parameter="ServiceKey",
            ),
            start=1,
        ):
            if service_key and service_key.encode("utf-8") in page.body:
                raise ValueError("Response body contained the configured credential; body was not archived")
            page_path = pages_dir / f"page_{page_no:04d}.json"
            immutable_write(page_path, page.body)
            batch = items(page.payload)
            api_body = response_body(page.payload)
            total_count = int(api_body.get("totalCount") or 0)
            actual_page_size = int(api_body.get("numOfRows") or PAGE_SIZE)
            total_counts.add(total_count)
            actual_page_sizes.add(actual_page_size)
            page_count = max(1, math.ceil(total_count / max(actual_page_size, 1)))

            meet_count = rank_count = candidate_count = 0
            for row in batch:
                result["actual_response_rows"] += 1
                meet = str(row.get("meet") or "")
                rank = str(row.get("rank") or "")
                meet_values[meet] += 1
                rank_values[rank] += 1
                is_jeju_meet = meet == "제주"
                is_je_prefix = rank.startswith("제")
                if is_jeju_meet:
                    result["rows_with_meet_jeju"] += 1
                    meet_count += 1
                if is_je_prefix:
                    result["rows_with_rank_prefix_je"] += 1
                    rank_count += 1
                if is_jeju_meet and is_je_prefix:
                    candidate_count += 1
                    result["jeju_rank_prefix_candidate_rows"] += 1
                    if str(row.get("rcDate") or "")[:4] != str(year):
                        result["out_of_year_rows"] += 1
                    race_no = str(row.get("rcNo") or "").strip()
                    race_date = str(row.get("rcDate") or "").strip()
                    if race_date and race_no:
                        candidate_races.add((race_date, race_no))

            result["source_pages"].append(
                {
                    "page_no": page_no,
                    "status_code": page.status_code,
                    "content_type": page.content_type,
                    "requested_at_ms": page.requested_at_ms,
                    "retrieved_at_ms": page.retrieved_at_ms,
                    "response_bytes": len(page.body),
                    "response_sha256": hashlib.sha256(page.body).hexdigest(),
                    "response_file": str(page_path.relative_to(attempt_dir)),
                    "source_url_without_key": page.source_url,
                    "api_total_count": total_count,
                    "api_page_no": int(api_body.get("pageNo") or page_no),
                    "api_page_size": actual_page_size,
                    "api_expected_page_count": page_count,
                    "actual_page_rows": len(batch),
                    "rows_with_meet_jeju": meet_count,
                    "rows_with_rank_prefix_je": rank_count,
                    "jeju_rank_prefix_candidate_rows": candidate_count,
                }
            )

        if len(total_counts) > 1:
            raise ValueError(f"Inconsistent totalCount across pages: {sorted(total_counts)}")
        if len(actual_page_sizes) > 1:
            raise ValueError(f"Inconsistent numOfRows across pages: {sorted(actual_page_sizes)}")
        result["api_total_count"] = next(iter(total_counts), 0)
        result["api_page_size"] = next(iter(actual_page_sizes), PAGE_SIZE)
        result["api_expected_page_count"] = max(
            1, math.ceil(result["api_total_count"] / max(result["api_page_size"], 1))
        )
        result["actual_page_count"] = len(result["source_pages"])
        result["meet_value_counts"] = dict(sorted(meet_values.items()))
        result["rank_value_counts"] = dict(sorted(rank_values.items()))
        result["jeju_rank_prefix_candidate_races"] = len(candidate_races)
        result["status"] = "completed" if (
            result["actual_page_count"] == result["api_expected_page_count"]
            and result["actual_response_rows"] == result["api_total_count"]
        ) else "completed_with_count_mismatch"
        if result["out_of_year_rows"]:
            result["status"] = "completed_with_scope_anomaly"
    except Exception as exc:
        result["status"] = "failed"
        result["exception_chain"] = safe_exception(exc, service_key)
        result["partial_actual_page_count"] = len(result["source_pages"])
        result["partial_response_files"] = [
            {
                "path": str(path.relative_to(attempt_dir)),
                "response_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(pages_dir.glob("*.json"))
        ] if pages_dir.exists() else []
    return result


def old_archive_counts(year: int) -> dict[str, Any] | None:
    path = OLD_ARCHIVE / f"native_results_{year}.jsonl"
    if not path.exists():
        return None
    rows = 0
    races: set[tuple[str, str]] = set()
    parse_errors = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if str(row.get("meet") or "") != "제주" or not str(row.get("rank") or "").startswith("제"):
            continue
        rows += 1
        race_date = str(row.get("rcDate") or "").strip()
        race_no = str(row.get("rcNo") or "").strip()
        if race_date and race_no:
            races.add((race_date, race_no))
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "candidate_rows": rows,
        "candidate_races": len(races),
        "parse_error_lines": parse_errors,
    }


def phase2_counts() -> dict[str, dict[str, int]]:
    if not PHASE2_DB.exists():
        return {}
    uri = f"file:{PHASE2_DB}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        rows = conn.execute(
            """
            SELECT substr(replace(e.event_date, '-', ''), 1, 4) AS year,
                   COUNT(DISTINCT e.id) AS race_count,
                   COUNT(ent.id) AS entry_count,
                   SUM(CASE WHEN ent.breed_evidence = 'official_result_rank_explicit_je'
                            THEN 1 ELSE 0 END) AS explicit_rank_entry_count,
                   COUNT(DISTINCT CASE WHEN ent.breed_evidence = 'official_result_rank_explicit_je'
                                       THEN e.id END) AS explicit_rank_race_count
            FROM event AS e
            LEFT JOIN entry AS ent ON ent.event_id = e.id
            WHERE e.event_type = 'race'
              AND substr(replace(e.event_date, '-', ''), 1, 4) BETWEEN '2015' AND '2025'
            GROUP BY year
            ORDER BY year
            """
        ).fetchall()
    return {
        str(year): {
            "race_count": int(race_count or 0),
            "entry_count": int(entry_count or 0),
            "explicit_rank_entry_count": int(explicit_rank_entry_count or 0),
            "explicit_rank_race_count": int(explicit_rank_race_count or 0),
        }
        for year, race_count, entry_count, explicit_rank_entry_count, explicit_rank_race_count in rows
    }


def compare_years(year_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    research = phase2_counts()
    comparisons: list[dict[str, Any]] = []
    for result in year_results:
        year = int(result["year"])
        comparison: dict[str, Any] = {
            "year": year,
            "api_status": result["status"],
            "api_total_count": result.get("api_total_count"),
            "api_actual_response_rows": result["actual_response_rows"],
            "api_jeju_rank_prefix_candidate_rows": result["jeju_rank_prefix_candidate_rows"],
            "api_jeju_rank_prefix_candidate_races": result["jeju_rank_prefix_candidate_races"],
        }
        if 2002 <= year <= 2014:
            old = old_archive_counts(year)
            comparison["comparison_source"] = "existing data/raw/jeju_native_results/native_results_YEAR.jsonl"
            comparison["existing_archive"] = old
            if old is not None:
                comparison["api_minus_existing_candidate_rows"] = (
                    result["jeju_rank_prefix_candidate_rows"] - old["candidate_rows"]
                )
                comparison["api_minus_existing_candidate_races"] = (
                    result["jeju_rank_prefix_candidate_races"] - old["candidate_races"]
                )
        elif 2015 <= year <= 2025:
            existing = research.get(str(year))
            comparison["comparison_source"] = str(PHASE2_DB.relative_to(PROJECT_ROOT))
            comparison["research_layer"] = existing
            if existing is not None:
                comparison["api_minus_phase2_explicit_rank_entry_count"] = (
                    result["jeju_rank_prefix_candidate_rows"] - existing["explicit_rank_entry_count"]
                )
                comparison["api_minus_phase2_explicit_rank_race_count"] = (
                    result["jeju_rank_prefix_candidate_races"] - existing["explicit_rank_race_count"]
                )
                comparison["api_minus_phase2_all_entry_count"] = (
                    result["jeju_rank_prefix_candidate_rows"] - existing["entry_count"]
                )
                comparison["api_minus_phase2_all_race_count"] = (
                    result["jeju_rank_prefix_candidate_races"] - existing["race_count"]
                )
        comparisons.append(comparison)
    return comparisons


def main() -> None:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    service_key = secret.get_secret_value() if secret is not None else None
    run_id, attempt_dir = create_run()
    base_manifest = {
        "attempt_id": run_id,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "requested_scope": {
            "years_inclusive": [START_YEAR, END_YEAR],
            "public_params_per_year": {"meet": 2, "rc_year": "YEAR", "_type": "json"},
            "page_size": PAGE_SIZE,
            "endpoint": RACE_RESULT_WITH_SECTIONS_ENDPOINT,
            "operation": RACE_RESULT_WITH_SECTIONS_OPERATION,
        },
        "source": "KRA API4_3 raceResult_3",
        "source_host": urlparse(settings.kra_api_base_url).hostname,
        "service_key_recorded": False,
        "response_body_storage": "source_pages/page_NNNN.json (response.content bytes, stored before parsing/filtering)",
        "artifacts_are_immutable": True,
        "year_failures_are_isolated": True,
        "candidate_predicate": "meet == 제주 and rank starts with 제",
        "breed_decision_note": "The rank prefix is only a candidate selector and does not confirm individual-horse breed.",
    }
    year_results: list[dict[str, Any]] = []
    if service_key is None:
        for year in range(START_YEAR, END_YEAR + 1):
            result = empty_year_result(year)
            result["status"] = "failed"
            result["exception_chain"] = [{"type": "RuntimeError", "message": "KRA service key unavailable"}]
            year_results.append(result)
    else:
        with KraApiClient(
            service_key,
            base_url=settings.kra_api_base_url,
            timeout_seconds=90,
        ) as client:
            for year in range(START_YEAR, END_YEAR + 1):
                result = collect_year(year, attempt_dir, client, service_key)
                year_results.append(result)
                print(json.dumps({
                    "year": year,
                    "status": result["status"],
                    "api_total_count": result.get("api_total_count"),
                    "actual_response_rows": result["actual_response_rows"],
                    "candidate_rows": result["jeju_rank_prefix_candidate_rows"],
                    "candidate_races": result["jeju_rank_prefix_candidate_races"],
                    "page_count": result.get("actual_page_count", result.get("partial_actual_page_count", 0)),
                }, ensure_ascii=False), flush=True)

    comparisons = compare_years(year_results)
    for result, comparison in zip(year_results, comparisons, strict=True):
        result["comparison"] = comparison
        immutable_write(
            attempt_dir / str(result["year"]) / "attempt_manifest.json",
            (json.dumps({**base_manifest, **result}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    failed_years = [result["year"] for result in year_results if result["status"].startswith("failed")]
    run_manifest = {
        **base_manifest,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "status": "completed" if not failed_years else "completed_with_year_failures",
        "successful_years": [result["year"] for result in year_results if result["status"].startswith("completed")],
        "failed_years": failed_years,
        "years": year_results,
        "annual_comparisons": comparisons,
        "comparison_notes": [
            "2002-2014 existing archive comparison uses meet=제주 and rank-prefix=제 candidate row/race counts.",
            "2015-2025 phase2 comparison reports all race/entry counts and counts with breed_evidence=official_result_rank_explicit_je separately.",
            "API candidate totals are mixed-result observations and are not validated native-breed counts.",
        ],
    }
    immutable_write(
        attempt_dir / "run_manifest.json",
        (json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(json.dumps({
        "attempt_id": run_id,
        "status": run_manifest["status"],
        "successful_years": len(run_manifest["successful_years"]),
        "failed_years": failed_years,
        "attempt_dir": str(attempt_dir.relative_to(PROJECT_ROOT)),
        "run_manifest": str((attempt_dir / "run_manifest.json").relative_to(PROJECT_ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

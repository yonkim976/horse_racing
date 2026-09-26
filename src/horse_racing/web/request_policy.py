"""Bound public read requests before they reach expensive route loaders.

This module deliberately has no database dependency.  The checks run in the
HTTP middleware, before FastAPI resolves route parameters or opens a session.
Limits complement the narrower limits already present in route loaders.
"""

from __future__ import annotations

import re
from collections import OrderedDict, deque
from datetime import date
from threading import Lock
from time import monotonic
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import PlainTextResponse, Response

_WINDOW = 60.0
_BURST_WINDOW = 10.0
_MAX_CLIENT_BUCKETS = 8192

# Shared expensive-read quota prevents rotating among expensive routes from
# bypassing the per-route ceilings.  CSV has a tighter independent ceiling.
_QUOTAS: dict[str, tuple[int, int]] = {
    "expensive": (24, 8),
    "analysis": (24, 8),
    "csv": (6, 2),
    "validation": (24, 8),
    "forecast": (30, 10),
    "detail": (60, 15),
    "entity-list": (60, 15),
    "ledger": (24, 8),
    "data-status": (24, 8),
    "dashboard": (60, 15),
    "distance": (60, 15),
}

_ANALYSIS_KEYS = frozenset(
    {"date", "history_limit", "race_id", "start", "end", "meet", "distance",
     "grade", "horse", "jockey_id", "q"}
)
_ANALYSIS_OUTPUT_KEYS = frozenset(
    {"date", "history_limit", "race_id", "start", "end", "meet", "distance", "grade"}
)
_FORECAST_KEYS = frozenset({"date", "meet", "distance", "grade", "race_id"})
_VALIDATION_KEYS = frozenset(
    {"start", "end", "meet", "distance", "grade", "model", "mode"}
)
_ENTITY_KEYS = frozenset({"q", "page", "sort", "status"})
_DISTANCE_KEYS = frozenset({"year", "distance", "grade", "page"})
_HOME_KEYS = frozenset({"date", "meet", "race_id", "trial_id"})


def _category(path: str) -> str | None:
    if path == "/":
        return "dashboard"
    if re.fullmatch(r"/racecourses/(seoul|jeju|busan)/distances", path):
        return "distance"
    if path == "/analysis":
        return "analysis"
    if path == "/api/analysis/export.csv":
        return "csv"
    if path == "/validation":
        return "validation"
    if path == "/forecast":
        return "forecast"
    if path in {"/predictions", "/api/predictions"}:
        return "ledger"
    if path == "/data-status":
        return "data-status"
    if re.fullmatch(r"/races/[^/]+", path) or re.fullmatch(r"/running-trials/[^/]+", path):
        return "detail"
    if path == "/m/analysis":
        return None  # compatibility redirect, not a database read
    if re.fullmatch(r"/(horses|jockeys|trainers|owners)/[^/]+", path):
        return "detail"
    if re.fullmatch(r"/(horses|jockeys|trainers|owners)", path):
        return "entity-list"
    return None


def _query_keys(path: str) -> frozenset[str] | None:
    if path in {"/analysis", "/api/analysis/export.csv"}:
        return _ANALYSIS_KEYS
    if path == "/forecast":
        return _FORECAST_KEYS
    if path == "/validation":
        return _VALIDATION_KEYS
    if re.fullmatch(r"/(horses|jockeys|trainers|owners)", path):
        return _ENTITY_KEYS
    if re.fullmatch(r"/racecourses/(seoul|jeju|busan)/distances", path):
        return _DISTANCE_KEYS
    if path == "/":
        return _HOME_KEYS
    if path == "/m/analysis":
        return None  # legacy redirect preserves its original query parameters
    return frozenset()


def _mark_policy_response(
    response: Response,
    *,
    category: str,
    reason: str,
    count: int | None = None,
    limit: int | None = None,
) -> Response:
    """Attach safe, non-wire diagnostics for the middleware to log."""
    response.policy_diagnostics = {  # type: ignore[attr-defined]
        "category": category,
        "reason": reason,
        "count": count,
        "limit": limit,
    }
    return response


def _bad_request(message: str) -> Response:
    return _mark_policy_response(
        PlainTextResponse(message, status_code=422, headers={"Cache-Control": "no-store"}),
        category="request_validation",
        reason="invalid_request",
    )


def _validate(request: Request) -> Response | None:
    path = request.url.path
    raw_path = request.scope.get("raw_path", path.encode())
    if len(raw_path) > 1024:
        return _bad_request("요청 경로가 너무 깁니다.")
    if re.fullmatch(r"/(races|running-trials)/[^/]+", path):
        raw_id = path.rsplit("/", 1)[-1]
        if not raw_id.isascii() or not raw_id.isdecimal() or not raw_id.strip("0"):
            return _bad_request("경주 식별자가 올바르지 않습니다.")
        canonical_id = raw_id.lstrip("0")
        if len(canonical_id) > 19 or (
            len(canonical_id) == 19 and canonical_id > "9223372036854775807"
        ):
            return _bad_request("경주 식별자가 올바르지 않습니다.")
    if re.fullmatch(r"/(horses|jockeys|trainers|owners)/[^/]+", path):
        entity_key = path.rsplit("/", 1)[-1]
        if entity_key.isdecimal():
            numeric_id = int(entity_key)
            if numeric_id > 9223372036854775807:
                return _bad_request("개체 식별자가 올바르지 않습니다.")
    raw = request.scope.get("query_string", b"")
    limit = 4096 if path in {"/analysis", "/api/analysis/export.csv", "/m/analysis"} else 2048
    if len(raw) > limit:
        return _bad_request("요청 조건이 너무 깁니다.")

    allowed = _query_keys(path)
    params = request.query_params
    values = {key: params.getlist(key) for key in params.keys()}
    relevant_keys = set() if allowed is None else set(values) & allowed
    repeated_scalars = relevant_keys - {"horse"}
    if any(len(values[key]) > 1 for key in repeated_scalars):
        return _bad_request("같은 조건을 여러 번 지정할 수 없습니다.")

    if path in {"/analysis", "/api/analysis/export.csv"}:
        if len(values.get("horse", [])) > 40:
            return _bad_request("말 필터는 최대 40개까지 지정할 수 있습니다.")
        if any(not value.isdecimal() or len(value) > 19 or int(value) > 9223372036854775807
               for value in values.get("horse", [])):
            return _bad_request("말 식별자가 올바르지 않습니다.")
        if len(params.get("q", "")) > 50:
            return _bad_request("검색어가 너무 깁니다.")
        raw_history = params.get("history_limit")
        if raw_history is not None and (
            not raw_history.isdecimal() or not 1 <= int(raw_history) <= 60
        ):
            return _bad_request("history_limit은 1부터 60까지 지정해 주세요.")
        for key in ("race_id", "jockey_id"):
            raw_id = params.get(key)
            if raw_id is not None and not _valid_positive_integer(raw_id):
                return _bad_request(f"{key} 값이 올바르지 않습니다.")
        start, end = _date_value(params.get("start")), _date_value(params.get("end"))
        if start is _INVALID or end is _INVALID:
            return _bad_request("날짜 조건 형식이 올바르지 않습니다.")
        if isinstance(start, date) != isinstance(end, date):
            return _bad_request("기간을 지정할 때 시작일과 종료일을 함께 입력해 주세요.")
        if isinstance(start, date) and isinstance(end, date):
            if start > end:
                return _bad_request("시작일은 종료일보다 늦을 수 없습니다.")
            if (end - start).days > 366:
                return _bad_request("분석 조회 기간은 최대 366일입니다.")
    elif path == "/validation":
        start, end = _date_value(params.get("start")), _date_value(params.get("end"))
        if start is _INVALID or end is _INVALID:
            return _bad_request("날짜 조건 형식이 올바르지 않습니다.")
        if isinstance(start, date) != isinstance(end, date):
            return _bad_request("기간을 지정할 때 시작일과 종료일을 함께 입력해 주세요.")
        if isinstance(start, date) and isinstance(end, date):
            if start > end:
                return _bad_request("시작일은 종료일보다 늦을 수 없습니다.")
            if (end - start).days > 366:
                return _bad_request("검증 조회 기간은 최대 366일입니다.")
    elif path == "/forecast":
        raw_id = params.get("race_id")
        if raw_id is not None and not _valid_positive_integer(raw_id):
            return _bad_request("race_id 값이 올바르지 않습니다.")
    elif path == "/":
        raw_meet = params.get("meet", "")
        if raw_meet and (not raw_meet.isascii() or raw_meet not in {"1", "2", "3", "4"}):
            return _bad_request("경마장 값은 1부터 4까지 지정해 주세요.")
        for key in ("race_id", "trial_id"):
            raw_id = params.get(key)
            if raw_id is not None and not _valid_positive_integer(raw_id):
                return _bad_request(f"{key} 값이 올바르지 않습니다.")
    elif re.fullmatch(r"/(horses|jockeys|trainers|owners)", path):
        if len(params.get("q", "")) > 100:
            return _bad_request("검색어가 너무 깁니다.")
        raw_page = params.get("page")
        if raw_page is not None and (not raw_page.isdecimal() or not 1 <= int(raw_page) <= 200):
            return _bad_request("페이지는 1부터 200까지 지정해 주세요.")
    elif path.startswith("/racecourses/"):
        raw_page = params.get("page")
        if raw_page is not None and (not raw_page.isdecimal() or not 1 <= int(raw_page) <= 200):
            return _bad_request("페이지는 1부터 200까지 지정해 주세요.")
    return None


_INVALID = object()


def _date_value(value: str | None) -> date | None | object:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return _INVALID


def _valid_positive_integer(value: str) -> bool:
    return (
        value.isascii()
        and value.isdecimal()
        and bool(value.strip("0"))
        and len(value.lstrip("0")) <= 19
        and (
            len(value.lstrip("0")) < 19
            or value.lstrip("0") <= "9223372036854775807"
        )
    )


class RequestPolicy:
    """Per-app, bounded quota state; active clients are never evicted."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._requests: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()

    def check_request(
        self, request: Request, *, client_key: str, now: float | None = None
    ) -> Response | None:
        """Return a 422/429 response when a public request exceeds its policy."""
        invalid = _validate(request)
        if invalid is not None:
            return invalid
        category = _category(request.url.path)
        if category is None:
            return None
        current = monotonic() if now is None else now
        categories = ["expensive", category]
        with self._lock:
            # Drop only fully idle state. Live quota records remain until their
            # full window expires; saturation fails closed for new clients.
            expired = [
                key for key, bucket in self._requests.items()
                if not bucket or bucket[-1] <= current - _WINDOW
            ]
            for key in expired:
                self._requests.pop(key, None)
            keys = [(client_key, group) for group in categories]
            missing = sum(key not in self._requests for key in keys)
            if len(self._requests) + missing > _MAX_CLIENT_BUCKETS:
                return _too_many_requests(
                    category="quota_state",
                    reason="state_capacity",
                    limit=_MAX_CLIENT_BUCKETS,
                )
            for group, key in zip(categories, keys, strict=True):
                limit, burst_limit = _QUOTAS[group]
                bucket = self._requests.get(key)
                if bucket is None:
                    continue
                while bucket and bucket[0] <= current - _WINDOW:
                    bucket.popleft()
                in_burst = sum(t >= current - _BURST_WINDOW for t in bucket)
                if len(bucket) >= limit or in_burst >= burst_limit:
                    active_count = len(bucket)
                    in_burst = sum(t >= current - _BURST_WINDOW for t in bucket)
                    exceeded = "window" if active_count >= limit else "burst"
                    return _too_many_requests(
                        category=group,
                        reason=f"{exceeded}_limit",
                        count=active_count if exceeded == "window" else in_burst,
                        limit=limit if exceeded == "window" else burst_limit,
                    )
            # Reserve both shared and route buckets atomically after all checks.
            for key in keys:
                self._requests.setdefault(key, deque()).append(current)
        return None


def _too_many_requests(
    *, category: str, reason: str, count: int | None = None, limit: int | None = None
) -> Response:
    return _mark_policy_response(
        PlainTextResponse(
            "비용이 큰 요청이 많습니다. 잠시 후 다시 시도해 주세요.",
            status_code=429,
            headers={"Retry-After": "60", "Cache-Control": "no-store"},
        ),
        category=category,
        reason=reason,
        count=count,
        limit=limit,
    )


def normalized_query_key(request: Request) -> str:
    """Return output-relevant query parameters in stable order for response caches."""
    allowed = _query_keys(request.url.path)
    if allowed is None:
        return ""
    if request.url.path in {"/analysis", "/api/analysis/export.csv"}:
        allowed = _ANALYSIS_OUTPUT_KEYS
    params = request.query_params
    items: list[tuple[str, str]] = []
    for key in sorted(allowed):
        if key == "horse":
            items.extend((key, value) for value in params.getlist(key))
        elif key in params:
            items.append((key, params.get(key, "")))
    normalized = urlencode(items)
    if request.scope.get("query_string", b"") and not normalized:
        # The base template marks any queried URL noindex, so query presence is
        # itself response-relevant even if the parameters are ignored.
        return "__has_query=1"
    return normalized

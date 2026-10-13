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

from horse_racing.web.distance_benchmarks import BENCHMARK_BANDS
from horse_racing.web.security import _DualRateBucket
from horse_racing.web.seo import is_presentation_parameter

_WINDOW = 60.0
_BURST_WINDOW = 10.0
_MAX_CLIENT_BUCKETS = 8192

# Shared expensive-read quota prevents rotating among expensive routes from
# bypassing the per-route ceilings.  CSV has a tighter independent ceiling.
_QUOTAS: dict[str, tuple[int, int]] = {
    # Quotas aggregate by verified client IP. The larger per-IP ceilings admit
    # a shared household/racecourse network while keeping query shape bounds,
    # active DB admission, and CSV's intentionally narrow budget in force.
    "expensive": (1800, 1200),
    "calendar": (600, 300),
    "analysis": (300, 150),
    "csv": (6, 2),
    "validation": (180, 60),
    "forecast": (300, 120),
    "detail": (900, 450),
    "entity-list": (300, 120),
    "ledger": (180, 60),
    "data-status": (180, 60),
    "dashboard": (600, 300),
    "distance": (300, 120),
}

_ANALYSIS_KEYS = frozenset(
    {"date", "history_limit", "race_id", "start", "end", "meet", "distance",
     "grade", "horse", "jockey_id", "q"}
)
_ANALYSIS_PAGE_KEYS = _ANALYSIS_KEYS | {"layout", "tab"}
_ANALYSIS_OUTPUT_KEYS = frozenset(
    {"date", "history_limit", "race_id", "start", "end", "meet", "distance", "grade"}
)
_FORECAST_KEYS = frozenset({"date", "meet", "distance", "grade", "race_id"})
_VALIDATION_KEYS = frozenset(
    {"start", "end", "meet", "distance", "grade", "model", "mode"}
)
_ENTITY_KEYS = frozenset({"q", "page", "sort", "status", "meet", "grade", "origin", "period"})
_DISTANCE_KEYS = frozenset({"year", "distance", "grade", "page", "view", "band"})
_HOME_KEYS = frozenset({"date", "meet", "race_id", "trial_id", "layout"})


def _category(path: str) -> str | None:
    if path == "/sitemap-index.xml" or path.startswith("/sitemaps/"):
        return "detail"
    if path == "/horses/list":
        return "entity-list"
    if path == "/":
        return "dashboard"
    if path == "/api/calendar":
        return "calendar"
    if re.fullmatch(r"/racecourses/(seoul|jeju|busan|yeongcheon)/distances(?:/[^/]+)?", path):
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
    if path == "/horses/list":
        return _ENTITY_KEYS
    if re.fullmatch(r"/(horses|jockeys|trainers|owners)/[^/]+", path):
        return frozenset({"tab", "period"})
    if path == "/api/calendar":
        return frozenset({"month"})
    if path in {"/guide", "/privacy"}:
        return frozenset({"layout"})
    if path == "/analysis":
        return _ANALYSIS_PAGE_KEYS
    if path == "/api/analysis/export.csv":
        return _ANALYSIS_KEYS
    if re.fullmatch(r"/races/[^/]+", path):
        return frozenset({"layout"})
    if path == "/forecast":
        return _FORECAST_KEYS
    if path == "/validation":
        return _VALIDATION_KEYS
    if re.fullmatch(r"/(horses|jockeys|trainers|owners)", path):
        return _ENTITY_KEYS
    if re.fullmatch(r"/racecourses/(seoul|jeju|busan|yeongcheon)/distances(?:/[^/]+)?", path):
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
    if "layout" in relevant_keys and params.get("layout") not in {"mobile", "desktop", "auto"}:
        return _bad_request("layout은 mobile, desktop, auto 중 하나로 지정해 주세요.")

    if path == "/api/calendar":
        if set(values) - {"month"}:
            return _bad_request("연월 이외의 조건은 지정할 수 없습니다.")
        month = params.get("month", "")
        if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month):
            return _bad_request("연월은 YYYY-MM 형식으로 지정해 주세요.")
        try:
            date.fromisoformat(f"{month}-01")
        except ValueError:
            return _bad_request("유효한 연월을 입력해 주세요.")

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
    elif path == "/horses/list" or re.fullmatch(r"/(horses|jockeys|trainers|owners)", path):
        if len(params.get("q", "")) > 100:
            return _bad_request("검색어가 너무 깁니다.")
        raw_page = params.get("page")
        if raw_page is not None and (not raw_page.isdecimal() or not 1 <= int(raw_page) <= 200):
            return _bad_request("페이지는 1부터 200까지 지정해 주세요.")
    elif path.startswith("/racecourses/"):
        raw_page = params.get("page")
        if raw_page is not None and (not raw_page.isdecimal() or not 1 <= int(raw_page) <= 200):
            return _bad_request("페이지는 1부터 200까지 지정해 주세요.")
        if re.fullmatch(r"/racecourses/(seoul|jeju|busan|yeongcheon)/distances(?:/[^/]+)?", path):
            raw_view = params.get("view")
            if raw_view is not None and raw_view != "trials":
                return _bad_request("view는 trials만 지정할 수 있습니다.")
            raw_band = params.get("band")
            if raw_band is not None and raw_band not in BENCHMARK_BANDS:
                return _bad_request("지원하지 않는 함수율 기준입니다.")
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
        # Fixed-size token state avoids keeping one Python timestamp per
        # accepted request when an aggregate quota is deliberately generous.
        self._requests: OrderedDict[
            tuple[str, str], _DualRateBucket | deque[float]
        ] = OrderedDict()

    @staticmethod
    def is_database_backed(path: str) -> bool:
        return _category(path) is not None

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
        categories = [category] if category == "calendar" else ["expensive", category]
        with self._lock:
            # Drop only quota state that has not been touched for a whole
            # window; saturation still fails closed for new clients.
            expired = [
                key for key, bucket in self._requests.items()
                if (
                    current - (bucket[-1] if isinstance(bucket, deque) else bucket.last_seen)
                    >= _WINDOW
                )
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
                if group == "csv":
                    assert isinstance(bucket, deque)
                    while bucket and bucket[0] <= current - _WINDOW:
                        bucket.popleft()
                    in_burst = sum(t >= current - _BURST_WINDOW for t in bucket)
                    if len(bucket) >= limit or in_burst >= burst_limit:
                        exceeded_window = len(bucket) >= limit
                        return _too_many_requests(
                            category=group,
                            reason="window_limit" if exceeded_window else "burst_limit",
                            count=len(bucket) if exceeded_window else in_burst,
                            limit=limit if exceeded_window else burst_limit,
                        )
                    continue
                assert isinstance(bucket, _DualRateBucket)
                bucket.update_policy(
                    current,
                    window_seconds=_WINDOW,
                    window_limit=limit,
                    burst_seconds=_BURST_WINDOW,
                    burst_limit=burst_limit,
                )
                exceeded = bucket.deny_diagnostics()
                if exceeded is not None:
                    return _too_many_requests(
                        category=group,
                        reason=str(exceeded["reason"]),
                        count=int(exceeded["count"]),
                        limit=int(exceeded["limit"]),
                    )
            # Reserve both shared and route buckets atomically after all checks.
            for group, key in zip(categories, keys, strict=True):
                limit, burst_limit = _QUOTAS[group]
                bucket = self._requests.get(key)
                if bucket is None:
                    bucket = (
                        deque()
                        if group == "csv"
                        else _DualRateBucket.create(
                            current,
                            window_seconds=_WINDOW,
                            window_limit=limit,
                            burst_seconds=_BURST_WINDOW,
                            burst_limit=burst_limit,
                        )
                    )
                    self._requests[key] = bucket
                if group == "csv":
                    assert isinstance(bucket, deque)
                    bucket.append(current)
                else:
                    assert isinstance(bucket, _DualRateBucket)
                    bucket.consume(current)
                self._requests.move_to_end(key)
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
        if request.url.path == "/analysis":
            allowed = allowed | {"tab"}
    params = request.query_params
    items: list[tuple[str, str]] = []
    for key in sorted(allowed):
        if key == "horse":
            items.extend((key, value) for value in params.getlist(key))
        elif key in params:
            items.append((key, params.get(key, "")))
    normalized = urlencode(items)
    filtered = any(not is_presentation_parameter(key) for key in params)
    normalized_filtered = any(not is_presentation_parameter(key) for key, _ in items)
    if filtered and not normalized_filtered:
        # Ignored unknown parameters still change robots metadata. Never serve
        # a cached noindex variant to a tracking-only or canonical request.
        return normalized + ("&" if normalized else "") + "__noindex=1"
    if request.scope.get("query_string", b"") and not normalized:
        return "__has_query=1"
    return normalized

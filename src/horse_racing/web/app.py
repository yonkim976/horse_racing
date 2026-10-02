from __future__ import annotations

import csv
import hmac
import ipaddress
import json
import os
import random
import re
from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from io import StringIO
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import Annotated, TypeVar
from urllib.parse import quote, urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.gzip import GZipMiddleware

from horse_racing.db.session import SessionLocal
from horse_racing.web.dashboard import load_dashboard
from horse_racing.web.distance_page import GRADE_LABELS, SEOUL_GRADE_LABELS, load_distance_page
from horse_racing.web.entities import (
    DEFAULT_PAGE_SIZE,
    ENTITY_KINDS,
    load_entity_detail,
    load_entity_list,
    load_entity_official_id,
)
from horse_racing.web.insights import load_forecast_page
from horse_racing.web.predictions import load_prediction_ledger
from horse_racing.web.race_analysis import load_race_analysis_page
from horse_racing.web.race_page import load_race_page
from horse_racing.web.racecourse import build_racecourse_map
from horse_racing.web.request_policy import RequestPolicy, normalized_query_key
from horse_racing.web.security import (
    ActiveRequestGate,
    AsyncLockRegistry,
    BoundedRequestLimiter,
    BoundedTTLCache,
    SyncLockRegistry,
    bounded_size,
    parse_trusted_proxy_cidrs,
    resolve_client_ip,
    trusted_forwarded_scheme,
)
from horse_racing.web.trial_page import load_running_trial_page

WEB_ROOT = Path(__file__).parent
T = TypeVar("T")
_PUBLIC_SITE_ORIGIN = "https://mapilog.xyz"
_SITEMAP_PATHS = (
    "/",
    "/analysis",
    "/racecourses/seoul/distances",
    "/racecourses/jeju/distances",
    "/racecourses/busan/distances",
    "/racecourses/seoul/course",
    "/racecourses/jeju/course",
    "/racecourses/busan/course",
    "/racecourses/yeongcheon/course",
    "/horses",
    "/jockeys",
    "/trainers",
    "/owners",
)
_MOBILE_UA = re.compile(
    r"Android.+Mobile|iPhone|iPod|webOS|BlackBerry|IEMobile|Opera Mini",
    re.I,
)
_BLOCKED_ANTHROPIC_UA = re.compile(
    r"ClaudeBot|Claude-SearchBot|Claude-User|Claude-Web|anthropic-ai",
    re.I,
)
_CRAWLER_UA = re.compile(r"bot|crawler|spider|slurp|archiver", re.I)
_RATE_LIMIT_WINDOW_SECONDS = 60.0
_RATE_LIMIT_BURST_SECONDS = 10.0
_HUMAN_REQUESTS_PER_WINDOW = 180
_HUMAN_REQUESTS_PER_BURST = 60
_CRAWLER_REQUESTS_PER_WINDOW = 30
_CRAWLER_REQUESTS_PER_BURST = 10
_TRUSTED_PROXY_CIDRS = parse_trusted_proxy_cidrs(os.getenv("TRUSTED_PROXY_CIDRS"))
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_CACHE_ENTRY_BYTES = 512 * 1024
_ORIGIN_TOKEN_HEADER = "x-mapilog-origin-token"


def _diagnostic_path(path: str) -> str:
    """Keep logs low-cardinality and omit user supplied identifiers."""
    if path in {"/", "/analysis", "/m/analysis", "/forecast", "/validation",
                "/api/analysis/export.csv", "/predictions", "/api/predictions",
                "/data-status", "/robots.txt", "/health", "/health/ready"}:
        return path
    match = re.fullmatch(r"/(races|running-trials)/[^/]+", path)
    if match:
        return f"/{match.group(1)}/{{id}}"
    match = re.fullmatch(r"/(horses|jockeys|trainers|owners)(?:/[^/]+)?", path)
    if match:
        base = f"/{match.group(1)}"
        return base if path == base else f"{base}/{{id}}"
    match = re.fullmatch(r"/racecourses/(seoul|jeju|busan)/distances", path)
    if match:
        return "/racecourses/{meet}/distances"
    match = re.fullmatch(r"/racecourses/(seoul|jeju|busan|yeongcheon)/course", path)
    if match:
        return "/racecourses/{meet}/course"
    if path.startswith("/static/"):
        return "/static/{asset}"
    return "/_other"


def _response_bytes(response: Response) -> int | None:
    body = getattr(response, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return len(body)
    length = response.headers.get("content-length")
    return int(length) if length and length.isdecimal() else None


def _client_rate_key(request: Request) -> str:
    verified_client_ip = getattr(request.state, "verified_client_ip", None)
    if verified_client_ip is not None:
        return verified_client_ip
    return resolve_client_ip(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        _TRUSTED_PROXY_CIDRS,
    )


def _is_mobile_request(request: Request) -> bool:
    layout = request.cookies.get("hr-layout")
    if layout == "mobile":
        return True
    if layout == "desktop":
        return False
    return bool(_MOBILE_UA.search(request.headers.get("user-agent", "")))


def _legacy_mobile_target(
    request: Request,
    path: str,
    *,
    exclude: frozenset[str] = frozenset(),
    fragment: str = "",
) -> str:
    query = urlencode(
        [
            (key, value)
            for key, value in request.query_params.multi_items()
            if key not in exclude
        ]
    )
    target = f"{path}?{query}" if query else path
    return f"{target}#{fragment}" if fragment else target


def _permanent_redirect(url: str) -> RedirectResponse:
    return RedirectResponse(
        url=url,
        status_code=301,
        headers={"Cache-Control": "public, max-age=3600"},
    )


def create_app(
    session_factory: Callable[[], Session] = SessionLocal,
) -> FastAPI:
    app = FastAPI(
        title="한국 경마 데이터 보드",
        description="한국마사회 일정과 결과를 조회하는 로컬 대시보드",
    )
    templates = Jinja2Templates(directory=WEB_ROOT / "templates")
    app.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")

    # Read-only public surface: bounded per-client protection and short-lived caches.
    request_limiter = BoundedRequestLimiter(max_clients=4096, idle_ttl=120.0)
    page_cache: BoundedTTLCache[tuple[object, ...], object] = BoundedTTLCache(
        max_entries=128,
        max_bytes=8 * 1024 * 1024,
        max_entry_bytes=1024 * 1024,
        size_of=lambda value: bounded_size(value, limit=1024 * 1024),
    )
    cache_key_locks: SyncLockRegistry[tuple[object, ...]] = SyncLockRegistry()
    response_cache: BoundedTTLCache[str, tuple[int, dict[str, str], bytes]] = BoundedTTLCache(
        max_entries=128,
        max_bytes=4 * 1024 * 1024,
        max_entry_bytes=_MAX_RESPONSE_CACHE_ENTRY_BYTES,
        size_of=lambda value: len(value[2]),
    )
    response_locks: AsyncLockRegistry[str] = AsyncLockRegistry()
    request_policy = RequestPolicy()
    active_request_gate = ActiveRequestGate(limit=16)
    origin_token = os.getenv("MAPILOG_ORIGIN_TOKEN", "")
    if origin_token and len(origin_token) < 32:
        raise ValueError("MAPILOG_ORIGIN_TOKEN must be at least 32 characters")

    def cached(key: tuple[object, ...], loader: Callable[[], T], ttl: float = 20.0) -> T:
        now = monotonic()
        cached_value = page_cache.get(key, now=now)
        if cached_value is not None:
            return cached_value  # type: ignore[return-value]
        with cache_key_locks.hold(key):
            cached_value = page_cache.get(key, now=monotonic())
            if cached_value is not None:
                return cached_value  # type: ignore[return-value]
            value = loader()
            page_cache.set(key, value, ttl=ttl)
            return value

    @app.middleware("http")
    async def public_safety(request: Request, call_next):  # type: ignore[no-untyped-def]
        started_at = monotonic()

        def finish(response: Response) -> Response:
            policy = getattr(response, "policy_diagnostics", None)
            status = response.status_code
            if policy is not None or status in {413, 429}:
                policy = policy or {
                    "category": "protection_policy",
                    "reason": "response_limit" if status == 413 else "unclassified_rate_limit",
                    "count": None,
                    "limit": None,
                }
                event = {
                    "event": "request_policy_denied",
                    "severity": "WARNING",
                    "status_code": status,
                    "category": policy.get("category"),
                    "reason": policy.get("reason"),
                    "path": _diagnostic_path(request.scope.get("path", "")),
                    "count": policy.get("count"),
                    "limit": policy.get("limit"),
                    "retry_after": response.headers.get("retry-after"),
                    "duration_ms": round((monotonic() - started_at) * 1000, 2),
                    "response_bytes": _response_bytes(response),
                }
                print(json.dumps(event, separators=(",", ":")), flush=True)
            elif status < 400 and random.random() < 0.01:
                event = {
                    "event": "request_sample",
                    "severity": "INFO",
                    "status_code": status,
                    "path": _diagnostic_path(request.scope.get("path", "")),
                    "duration_ms": round((monotonic() - started_at) * 1000, 2),
                    "response_bytes": _response_bytes(response),
                }
                print(json.dumps(event, separators=(",", ":")), flush=True)
            return response

        path = request.scope.get("path", "")
        token_matches = not origin_token or hmac.compare_digest(
            request.headers.get(_ORIGIN_TOKEN_HEADER, "").encode("utf-8"),
            origin_token.encode("utf-8"),
        )
        cloudflare_ip = request.headers.get("cf-connecting-ip", "")
        if origin_token and token_matches:
            try:
                request.state.verified_client_ip = str(ipaddress.ip_address(cloudflare_ip))
            except ValueError:
                token_matches = False
        if not token_matches:
            denied = Response(status_code=403, headers={"Cache-Control": "no-store"})
            denied.policy_diagnostics = {  # type: ignore[attr-defined]
                "category": "origin_guard",
                "reason": "missing_or_invalid_token",
                "count": None,
                "limit": None,
            }
            return finish(denied)
        user_agent = request.headers.get("user-agent", "")
        if path != "/robots.txt" and _BLOCKED_ANTHROPIC_UA.search(user_agent):
            denied = Response(
                status_code=403,
                headers={
                    "Cache-Control": "no-store",
                    "X-Robots-Tag": "noindex, nofollow",
                },
            )
            denied.policy_diagnostics = {  # type: ignore[attr-defined]
                "category": "user_agent_block",
                "reason": "anthropic_crawler",
                "count": None,
                "limit": None,
            }
            return finish(denied)

        peer = request.client.host if request.client else None
        trusted_scheme = trusted_forwarded_scheme(
            peer, request.headers.get("x-forwarded-proto"), _TRUSTED_PROXY_CIDRS
        )
        if trusted_scheme:
            request.scope["scheme"] = trusted_scheme
        elif request.headers.get("host", "").lower().split(":", 1)[0] in {
            "mapilog.xyz", "www.mapilog.xyz"
        }:
            # The production host is HTTPS-only. This keeps url_for output
            # correct behind TLS termination without trusting arbitrary XFP.
            request.scope["scheme"] = "https"

        # Import URL helpers only after applying a proxy scheme from a trusted peer.
        path = request.url.path

        if path != "/health":
            client = _client_rate_key(request)
            crawler_request = bool(_CRAWLER_UA.search(user_agent))
            window_limit = (
                _CRAWLER_REQUESTS_PER_WINDOW
                if crawler_request
                else _HUMAN_REQUESTS_PER_WINDOW
            )
            burst_limit = (
                _CRAWLER_REQUESTS_PER_BURST
                if crawler_request
                else _HUMAN_REQUESTS_PER_BURST
            )
            now = monotonic()
            allowed, rate_diagnostics = request_limiter.allow_with_diagnostics(
                client,
                now=now,
                window_seconds=_RATE_LIMIT_WINDOW_SECONDS,
                window_limit=window_limit,
                burst_seconds=_RATE_LIMIT_BURST_SECONDS,
                burst_limit=burst_limit,
            )
            if not allowed:
                denied = PlainTextResponse(
                    "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                    status_code=429,
                    headers={"Retry-After": "60", "Cache-Control": "no-store"},
                )
                denied.policy_diagnostics = rate_diagnostics  # type: ignore[attr-defined]
                return finish(denied)

        if request.method in {"GET", "HEAD"}:
            client = _client_rate_key(request)
            policy_response = request_policy.check_request(
                request, client_key=client, now=monotonic()
            )
            if policy_response is not None:
                return finish(policy_response)

        if request.url.hostname == "www.mapilog.xyz":
            canonical_url = request.url.replace(scheme="https", netloc="mapilog.xyz")
            return finish(RedirectResponse(
                url=str(canonical_url),
                status_code=301,
                headers={"Cache-Control": "public, max-age=3600"},
            ))

        cacheable = request.method == "GET" and (
            path in {"/", "/m", "/analysis", "/m/analysis"}
            or path.startswith("/races/")
        )
        view_bit = "m" if _is_mobile_request(request) or request.url.path.startswith("/m") else "d"
        # Template responses contain absolute URLs generated from the request
        # origin. Keep caches isolated per origin so the apex, www, and
        # run.app hosts never receive HTML rendered for another host, while
        # mobile and desktop variants remain separate within the same host.
        normalized_query = normalized_query_key(request)
        response_key = (
            f"{request.url.scheme}://{request.url.netloc}"
            f"|{view_bit}:{path}?{normalized_query}"
        )
        request_cache_safe = (
            not request.headers.get("authorization")
            and not request.headers.get("cookie")
        )
        cacheable = cacheable and request_cache_safe
        if cacheable:
            cached_response = response_cache.get(response_key)
            if cached_response is not None:
                return finish(Response(
                    content=cached_response[2],
                    status_code=cached_response[0],
                    headers=cached_response[1],
                ))

        async def build_response():  # type: ignore[no-untyped-def]
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            if path in {"/", "/analysis"} or path.startswith("/races/"):
                vary = [
                    value.strip()
                    for value in response.headers.get("Vary", "").split(",")
                    if value.strip()
                ]
                if not any(value.lower() == "user-agent" for value in vary):
                    vary.append("User-Agent")
                response.headers["Vary"] = ", ".join(vary)
            if response.status_code == 200 and path in {"/analysis", "/m/analysis"}:
                response.headers["Cache-Control"] = "private, max-age=20"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
                "https://fonts.googleapis.com; "
                "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
            )
            content_length = response.headers.get("content-length")
            if (
                content_length
                and content_length.isdecimal()
                and int(content_length) > _MAX_RESPONSE_BYTES
            ):
                iterator = response.body_iterator
                close = getattr(iterator, "aclose", None)
                if close is not None:
                    await close()
                denied = PlainTextResponse(
                    "응답이 허용된 크기를 초과했습니다.",
                    status_code=413,
                    headers={"Cache-Control": "no-store"},
                    background=response.background,
                )
                denied.policy_diagnostics = {  # type: ignore[attr-defined]
                    "category": "response_size",
                    "reason": "content_length_limit",
                    "count": int(content_length),
                    "limit": _MAX_RESPONSE_BYTES,
                }
                return denied
            body_buffer = bytearray()
            iterator = response.body_iterator
            async for chunk in iterator:
                if len(body_buffer) + len(chunk) > _MAX_RESPONSE_BYTES:
                    close = getattr(iterator, "aclose", None)
                    if close is not None:
                        await close()
                    denied = PlainTextResponse(
                        "응답이 허용된 크기를 초과했습니다.",
                        status_code=413,
                        headers={"Cache-Control": "no-store"},
                        background=response.background,
                    )
                    denied.policy_diagnostics = {  # type: ignore[attr-defined]
                        "category": "response_size",
                        "reason": "stream_body_limit",
                        "count": len(body_buffer) + len(chunk),
                        "limit": _MAX_RESPONSE_BYTES,
                    }
                    return denied
                body_buffer.extend(chunk)
            body = bytes(body_buffer)
            if (
                cacheable
                and response.status_code == 200
                and len(body) <= _MAX_RESPONSE_CACHE_ENTRY_BYTES
                and "set-cookie" not in response.headers
            ):
                headers = dict(response.headers)
                cache_value = (response.status_code, headers, body)
                response_cache.set(response_key, cache_value, ttl=20.0)
                response = Response(content=body, status_code=response.status_code, headers=headers)
            else:
                raw_headers = [
                    (name, value)
                    for name, value in response.raw_headers
                    if name.lower() != b"content-length"
                ]
                raw_headers.append((b"content-length", str(len(body)).encode("latin-1")))
                buffered_response = Response(
                    content=body,
                    status_code=response.status_code,
                    headers={},
                    background=response.background,
                )
                buffered_response.raw_headers = raw_headers
                response = buffered_response
            return response

        if not active_request_gate.try_enter():
            denied = PlainTextResponse(
                "서버가 바쁩니다. 잠시 후 다시 시도해 주세요.",
                status_code=503,
                headers={"Retry-After": "1", "Cache-Control": "no-store"},
            )
            denied.policy_diagnostics = {  # type: ignore[attr-defined]
                "category": "concurrency",
                "reason": "active_request_limit",
                "count": active_request_gate.active_count,
                "limit": active_request_gate.limit,
            }
            return finish(denied)
        try:
            if cacheable:
                async with response_locks.hold(response_key):
                    cached_response = response_cache.get(response_key)
                    if cached_response is not None:
                        return finish(Response(
                            content=cached_response[2],
                            status_code=cached_response[0],
                            headers=cached_response[1],
                        ))
                    return finish(await build_response())
            return finish(await build_response())
        finally:
            active_request_gate.leave()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness() -> dict[str, str]:
        try:
            with session_factory() as session:
                session.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return {"status": "ready"}

    @app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
    def robots_txt() -> PlainTextResponse:
        return PlainTextResponse(
            "User-agent: ClaudeBot\nDisallow: /\n\n"
            "User-agent: Claude-SearchBot\nDisallow: /\n\n"
            "User-agent: Claude-User\nDisallow: /\n\n"
            "User-agent: Claude-Web\nDisallow: /\n\n"
            "User-agent: anthropic-ai\nDisallow: /\n\n"
            "User-agent: *\nAllow: /\n\n"
            f"Sitemap: {_PUBLIC_SITE_ORIGIN}/sitemap.xml\n",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap_xml() -> Response:
        urls = "\n".join(
            f"  <url><loc>{_PUBLIC_SITE_ORIGIN}{path}</loc></url>"
            for path in _SITEMAP_PATHS
        )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}\n"
            "</urlset>\n"
        )
        return Response(
            content=body,
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon_ico() -> FileResponse:
        return FileResponse(
            WEB_ROOT / "static/images/brand/mapilog-favicon.ico",
            media_type="image/x-icon",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/", response_class=HTMLResponse, response_model=None)
    def dashboard(
        request: Request,
        race_date: Annotated[date | None, Query(alias="date")] = None,
        meet: Annotated[str | None, Query()] = None,
        race_id: Annotated[int | None, Query()] = None,
        trial_id: Annotated[int | None, Query()] = None,
    ) -> HTMLResponse:
        mobile_view = _is_mobile_request(request)
        selected_meet = int(meet) if meet and meet.isdigit() else None
        with session_factory() as session:
            data = load_dashboard(
                session,
                selected_date=race_date,
                selected_meet=selected_meet,
                selected_race_id=race_id,
                selected_trial_id=trial_id,
                mobile_view=mobile_view,
            )
        return templates.TemplateResponse(
            request=request,
            name="mobile/home.html" if mobile_view else "dashboard.html",
            context={"active_nav": "races", "dashboard": data},
        )

    @app.get("/m", response_class=HTMLResponse)
    def legacy_mobile_dashboard(request: Request) -> RedirectResponse:
        return _permanent_redirect(_legacy_mobile_target(request, "/"))

    @app.get("/races/{race_id}", response_class=HTMLResponse)
    def race_detail(request: Request, race_id: int) -> HTMLResponse:
        if _is_mobile_request(request):
            return _render_analysis(
                request,
                layout="mobile/base.html",
                template_name="mobile/analysis.html",
                race_date=None,
                history_limit=12,
                race_id=race_id,
                start=None,
                end=None,
                meet=None,
                distance=None,
                grade="",
                horse=[],
                jockey_id=None,
                q="",
            )
        with session_factory() as session:
            page = load_race_page(session, race_id=race_id)
        if page is None:
            raise HTTPException(status_code=404, detail="Not found")
        return templates.TemplateResponse(
            request=request,
            name="race_detail.html",
            context={"active_nav": "races", "page": page},
        )

    @app.get("/running-trials/{trial_id}", response_class=HTMLResponse)
    def running_trial_detail(request: Request, trial_id: int) -> HTMLResponse:
        with session_factory() as session:
            page = load_running_trial_page(session, trial_id=trial_id)
        if page is None:
            raise HTTPException(status_code=404, detail="Not found")
        return templates.TemplateResponse(
            request=request,
            name="running_trial_detail.html",
            context={"active_nav": "races", "page": page},
        )

    @app.get("/racecourses/{course}/distances", response_class=HTMLResponse)
    def course_distances(
        request: Request,
        course: str,
        year: Annotated[int | None, Query(ge=0, le=9999)] = None,
        distance: Annotated[int, Query(ge=0, le=10000)] = 0,
        grade: str = "",
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> HTMLResponse:
        if course not in ("jeju", "seoul", "busan"):
            raise HTTPException(status_code=404, detail="지원하지 않는 경마장입니다.")
        meet_code = {"seoul": 1, "jeju": 2, "busan": 3}[course]
        allowed_grades = GRADE_LABELS if meet_code == 2 else SEOUL_GRADE_LABELS
        if grade and grade not in allowed_grades:
            raise HTTPException(status_code=422, detail="지원하지 않는 등급입니다.")
        with session_factory() as session:
            data = load_distance_page(
                session, year=year, distance=distance, grade=grade, page=page, meet_code=meet_code,
            )
        return templates.TemplateResponse(
            request=request, name="distance_page.html",
            context={"active_nav": "distances", "data": data},
        )

    @app.get("/racecourses/{course}/course", response_class=HTMLResponse)
    def course_map(
        request: Request,
        course: str,
        distance: Annotated[int | None, Query(ge=800, le=4000)] = None,
    ) -> HTMLResponse:
        meet_codes = {"seoul": 1, "jeju": 2, "busan": 3, "yeongcheon": 4}
        meet_code = meet_codes.get(course)
        if meet_code is None:
            raise HTTPException(status_code=404, detail="지원하지 않는 경마장입니다.")

        default_distances = {1: 1400, 2: 1200, 3: 1600, 4: 1400}
        track = build_racecourse_map(
            meet_code=meet_code,
            distance_m=distance if distance is not None else default_distances[meet_code],
        )
        options = track.diagram["variants"] if track and track.diagram else []
        supported_distances = {variant["distance"] for variant in options}
        if distance is not None and distance not in supported_distances:
            raise HTTPException(status_code=404, detail="지원하지 않는 경주 거리입니다.")
        if track is None or not track.supported_distance:
            raise HTTPException(status_code=404, detail="지원하지 않는 경주 거리입니다.")

        page = SimpleNamespace(
            course_name=track.course_name,
            meet_code=meet_code,
            distance_m=track.distance_m,
            distance=f"{track.distance_m:,}m",
            racecourse_map=track,
            map_checkpoints=[],
        )
        return templates.TemplateResponse(
            request=request,
            name="course_map_page.html",
            context={
                "active_nav": "distances",
                "page": page,
                "is_course_explorer": True,
            },
        )

    def _analysis_data(
        *,
        race_id: int | None,
        start: date | None,
        end: date | None,
        meet: int | None,
        distance: int | None,
        grade: str,
        horse: list[int],
        jockey_id: int | None,
        q: str,
        race_date: date | None = None,
        history_limit: int = 12,
    ):
        if start and end and start > end:
            raise HTTPException(status_code=422, detail="시작일은 종료일보다 늦을 수 없습니다.")

        def load():
            with session_factory() as session:
                return load_race_analysis_page(
                    session,
                    race_id=race_id,
                    race_date=race_date,
                    history_limit=history_limit,
                    start=start,
                    end=end,
                    meet=meet,
                    distance=distance,
                    grade=grade,
                )

        return cached(
            (
                "analysis",
                race_id,
                race_date,
                history_limit,
                start,
                end,
                meet,
                distance,
                grade,
                tuple(horse),
                jockey_id,
                q,
            ),
            load,
        )

    def _render_analysis(
        request: Request,
        *,
        layout: str,
        template_name: str,
        race_date: date | None,
        history_limit: int,
        race_id: int | None,
        start: date | None,
        end: date | None,
        meet: int | None,
        distance: int | None,
        grade: str,
        horse: list[int],
        jockey_id: int | None,
        q: str,
    ) -> HTMLResponse:
        page = _analysis_data(
            race_id=race_id,
            race_date=race_date,
            history_limit=history_limit,
            start=start,
            end=end,
            meet=meet,
            distance=distance,
            grade=grade,
            horse=horse,
            jockey_id=jockey_id,
            q=q,
        )
        forecast = None
        if page.selected_race is not None:
            selected = page.selected_race

            def load_forecast():
                with session_factory() as session:
                    return load_forecast_page(
                        session,
                        selected_date=date.fromisoformat(selected.date),
                        meet=selected.meet_code,
                        race_id=selected.id,
                    )

            forecast = cached(("forecast-embed", selected.id), load_forecast)
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context={
                "layout": layout,
                "active_nav": "analysis",
                "page": page,
                "forecast": forecast,
                "analysis_payload": {
                    "race": asdict(page.selected_race) if page.selected_race else None,
                    "runners": [asdict(runner) for runner in page.runners],
                },
            },
        )

    @app.get("/analysis", response_class=HTMLResponse, response_model=None)
    def analysis_workspace(
        request: Request,
        race_date: Annotated[date | None, Query(alias="date")] = None,
        history_limit: Annotated[int, Query(ge=1, le=60)] = 12,
        race_id: Annotated[int | None, Query(ge=1)] = None,
        start: Annotated[date | None, Query()] = None,
        end: Annotated[date | None, Query()] = None,
        meet: Annotated[int | None, Query(ge=1, le=4)] = None,
        distance: Annotated[int | None, Query(ge=800, le=4000)] = None,
        grade: Annotated[str, Query(max_length=50)] = "",
        horse: Annotated[list[int] | None, Query()] = None,
        jockey_id: Annotated[int | None, Query(ge=1)] = None,
        q: Annotated[str, Query(max_length=50)] = "",
    ) -> HTMLResponse:
        if _is_mobile_request(request):
            return _render_analysis(
                request,
                layout="mobile/base.html",
                template_name="mobile/analysis.html",
                race_date=race_date,
                history_limit=history_limit,
                race_id=race_id,
                start=start,
                end=end,
                meet=meet,
                distance=distance,
                grade=grade,
                horse=horse or [],
                jockey_id=jockey_id,
                q=q,
            )
        return _render_analysis(
            request,
            layout="base.html",
            template_name="analysis.html",
            race_date=race_date,
            history_limit=history_limit,
            race_id=race_id,
            start=start,
            end=end,
            meet=meet,
            distance=distance,
            grade=grade,
            horse=horse or [],
            jockey_id=jockey_id,
            q=q,
        )

    @app.get("/m/analysis", response_class=HTMLResponse)
    def legacy_mobile_analysis(request: Request) -> RedirectResponse:
        race_id = request.query_params.get("race_id", "")
        entry_id = request.query_params.get("entry", "")
        fragment = f"entry-{entry_id}" if entry_id.isdecimal() else ""
        if race_id.isdecimal():
            return _permanent_redirect(f"/races/{race_id}{f'#{fragment}' if fragment else ''}")
        return _permanent_redirect(
            _legacy_mobile_target(
                request,
                "/analysis",
                exclude=frozenset({"entry"}),
                fragment=fragment,
            )
        )

    @app.get("/api/analysis/export.csv")
    def analysis_export(
        race_date: Annotated[date | None, Query(alias="date")] = None,
        history_limit: Annotated[int, Query(ge=1, le=60)] = 12,
        race_id: Annotated[int | None, Query(ge=1)] = None,
        start: Annotated[date | None, Query()] = None,
        end: Annotated[date | None, Query()] = None,
        meet: Annotated[int | None, Query(ge=1, le=4)] = None,
        distance: Annotated[int | None, Query(ge=800, le=4000)] = None,
        grade: Annotated[str, Query(max_length=50)] = "",
        horse: Annotated[list[int] | None, Query()] = None,
        jockey_id: Annotated[int | None, Query(ge=1)] = None,
        q: Annotated[str, Query(max_length=50)] = "",
    ) -> PlainTextResponse:
        page = _analysis_data(
            race_id=race_id,
            race_date=race_date,
            history_limit=history_limit,
            start=start,
            end=end,
            meet=meet,
            distance=distance,
            grade=grade,
            horse=horse or [],
            jockey_id=jockey_id,
            q=q,
        )
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "date",
                "meet",
                "race",
                "distance",
                "grade",
                "track_condition",
                "horse",
                "jockey",
                "finish",
                "time",
                *page.section_codes,
            ],
        )
        writer.writeheader()
        for row in page.rows:
            writer.writerow({key: row.get(key, "—") for key in writer.fieldnames})
        return PlainTextResponse(
            output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=horse-analysis.csv"},
        )

    @app.get("/api/predictions")
    def predictions_api() -> dict[str, object]:
        with session_factory() as session:
            page = load_prediction_ledger(session)
        return {
            "prospective": {
                "publications": page.live_publications,
                "settlements": page.live_settlements,
                "scored_races": page.aggregate_scored_races,
                "win_log_loss": page.aggregate_win_log_loss,
                "ece": page.aggregate_ece,
                "top1": page.aggregate_top1,
            },
            "historical_publications": page.historical_publications,
            "runs": [
                {
                    "public_id": row.public_id,
                    "mode": row.mode,
                    "race_date": row.race_date,
                    "published_at": row.published_at,
                    "races": row.race_count,
                    "entries": row.entry_count,
                    "status": row.status,
                    "win_log_loss": row.win_log_loss,
                    "top1": row.top1,
                    "prediction_hash": row.hash_short,
                }
                for row in page.rows
            ],
        }

    @app.get("/{kind_slug}", response_class=HTMLResponse)
    def entity_list(
        request: Request,
        kind_slug: str,
        q: Annotated[str, Query(max_length=100)] = "",
        page: Annotated[int, Query(ge=1)] = 1,
        sort: Annotated[str, Query()] = "starts",
        status: Annotated[str, Query()] = "all",
        meet: Annotated[int | None, Query(ge=1, le=3)] = None,
    ) -> HTMLResponse:
        if kind_slug not in ENTITY_KINDS:
            raise HTTPException(status_code=404, detail="Not found")

        def load():  # type: ignore[no-untyped-def]
            with session_factory() as session:
                return load_entity_list(
                    session,
                    kind_slug=kind_slug,
                    query=q,
                    page=page,
                    page_size=DEFAULT_PAGE_SIZE,
                    sort=sort,
                    status=status,
                    meet=meet,
                )

        data = cached(("entity-list", kind_slug, q, page, sort, status, meet), load, ttl=60.0)
        if data is None:
            raise HTTPException(status_code=404, detail="Not found")
        return templates.TemplateResponse(
            request=request,
            name="entity_list.html",
            context={"active_nav": kind_slug, "page_data": data},
        )

    @app.get("/{kind_slug}/{entity_key}", response_class=HTMLResponse)
    def entity_detail(
        request: Request,
        kind_slug: str,
        entity_key: str,
    ) -> Response:
        if kind_slug not in ENTITY_KINDS:
            raise HTTPException(status_code=404, detail="Not found")
        with session_factory() as session:
            data = load_entity_detail(
                session,
                kind_slug=kind_slug,
                official_id=entity_key,
            )
            if data is None and entity_key.isdecimal():
                official_id = load_entity_official_id(
                    session,
                    kind_slug=kind_slug,
                    internal_id=int(entity_key),
                )
                if official_id is not None:
                    return _permanent_redirect(
                        f"/{kind_slug}/{quote(official_id, safe='')}"
                    )
        if data is None:
            raise HTTPException(status_code=404, detail="Not found")
        return templates.TemplateResponse(
            request=request,
            name="entity_detail.html",
            context={"active_nav": kind_slug, "detail": data},
        )

    # Compress server-rendered HTML after application caching so large pages do
    # not generate avoidable internet egress charges.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    return app


app = create_app()

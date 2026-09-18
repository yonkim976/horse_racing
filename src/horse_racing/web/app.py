from __future__ import annotations

import asyncio
import csv
import re
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from io import StringIO
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Annotated, TypeVar

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from horse_racing.db.session import SessionLocal
from horse_racing.web.dashboard import load_dashboard
from horse_racing.web.data_status import load_data_status
from horse_racing.web.distance_page import GRADE_LABELS, SEOUL_GRADE_LABELS, load_distance_page
from horse_racing.web.entities import (
    DEFAULT_PAGE_SIZE,
    ENTITY_KINDS,
    load_entity_detail,
    load_entity_list,
)
from horse_racing.web.insights import (
    load_forecast_page,
    load_validation_page,
)
from horse_racing.web.predictions import load_prediction_ledger
from horse_racing.web.race_analysis import load_race_analysis_page
from horse_racing.web.race_page import load_race_page
from horse_racing.web.trial_page import load_running_trial_page

WEB_ROOT = Path(__file__).parent
T = TypeVar("T")
_MOBILE_UA = re.compile(
    r"Android.+Mobile|iPhone|iPod|iPad|webOS|BlackBerry|IEMobile|Opera Mini",
    re.I,
)


def _is_mobile_request(request: Request) -> bool:
    return bool(_MOBILE_UA.search(request.headers.get("user-agent", "")))


def _mobile_redirect(request: Request, mobile_path: str) -> RedirectResponse:
    query = request.url.query
    target = f"{mobile_path}?{query}" if query else mobile_path
    return RedirectResponse(url=target, status_code=302)


def create_app(
    session_factory: Callable[[], Session] = SessionLocal,
) -> FastAPI:
    app = FastAPI(
        title="한국 경마 데이터 보드",
        description="한국마사회 일정과 결과를 조회하는 로컬 대시보드",
    )
    templates = Jinja2Templates(directory=WEB_ROOT / "templates")
    app.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")

    # Read-only public surface: conservative per-client burst protection and headers.
    request_times: dict[str, deque[float]] = defaultdict(deque)
    limiter_lock = Lock()
    page_cache: dict[tuple[object, ...], tuple[float, object]] = {}
    cache_key_locks: dict[tuple[object, ...], Lock] = defaultdict(Lock)
    cache_lock = Lock()
    response_cache: dict[str, tuple[float, int, dict[str, str], bytes]] = {}
    response_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def cached(key: tuple[object, ...], loader: Callable[[], T], ttl: float = 20.0) -> T:
        now = monotonic()
        with cache_lock:
            cached_value = page_cache.get(key)
            if cached_value and cached_value[0] > now:
                return cached_value[1]  # type: ignore[return-value]
            key_lock = cache_key_locks[key]
        with key_lock:
            now = monotonic()
            with cache_lock:
                cached_value = page_cache.get(key)
                if cached_value and cached_value[0] > now:
                    return cached_value[1]  # type: ignore[return-value]
            value = loader()
            with cache_lock:
                page_cache[key] = (now + ttl, value)
                if len(page_cache) > 256:
                    expired = [item for item, (expires, _) in page_cache.items() if expires <= now]
                    for item in expired:
                        page_cache.pop(item, None)
                        cache_key_locks.pop(item, None)
            return value

    @app.middleware("http")
    async def public_safety(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path != "/health":
            client = request.client.host if request.client else "unknown"
            now = monotonic()
            with limiter_lock:
                bucket = request_times[client]
                while bucket and bucket[0] < now - 60:
                    bucket.popleft()
                if len(bucket) >= 2400:
                    return PlainTextResponse(
                        "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                        status_code=429,
                        headers={"Retry-After": "30"},
                    )
                bucket.append(now)

        cacheable = request.method == "GET" and (
            request.url.path in {"/", "/m", "/forecast", "/validation", "/analysis", "/m/analysis"}
            or request.url.path.startswith("/races/")
        )
        view_bit = "m" if _is_mobile_request(request) or request.url.path.startswith("/m") else "d"
        # Template responses contain absolute URLs generated from the request
        # origin. Keep caches isolated per origin so the apex, www, and
        # run.app hosts never receive HTML rendered for another host, while
        # mobile and desktop variants remain separate within the same host.
        response_key = (
            f"{request.url.scheme}://{request.url.netloc}"
            f"|{view_bit}:{request.url.path}?{request.url.query}"
        )
        if cacheable:
            cached_response = response_cache.get(response_key)
            if cached_response and cached_response[0] > monotonic():
                return Response(
                    content=cached_response[3],
                    status_code=cached_response[1],
                    headers=cached_response[2],
                )

        response_lock: asyncio.Lock | None = None
        if cacheable:
            response_lock = response_locks[response_key]
            await response_lock.acquire()
            cached_response = response_cache.get(response_key)
            if cached_response and cached_response[0] > monotonic():
                response_lock.release()
                return Response(
                    content=cached_response[3],
                    status_code=cached_response[1],
                    headers=cached_response[2],
                )
        try:
            response = await call_next(request)
        except Exception:
            if response_lock and response_lock.locked():
                response_lock.release()
            raise
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path in {"/forecast", "/validation", "/analysis", "/m/analysis"}:
            response.headers["Cache-Control"] = "private, max-age=20"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
            "https://fonts.googleapis.com; "
            "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        if cacheable and response.status_code == 200:
            body = b"".join([chunk async for chunk in response.body_iterator])
            headers = dict(response.headers)
            response_cache[response_key] = (monotonic() + 20, response.status_code, headers, body)
            if len(response_cache) > 128:
                expired = [
                    key
                    for key, (expires, _, _, _) in response_cache.items()
                    if expires <= monotonic()
                ]
                for key in expired:
                    response_cache.pop(key, None)
                    response_locks.pop(key, None)
            response = Response(content=body, status_code=response.status_code, headers=headers)
        if response_lock and response_lock.locked():
            response_lock.release()
        return response

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

    @app.get("/", response_class=HTMLResponse, response_model=None)
    def dashboard(
        request: Request,
        race_date: Annotated[date | None, Query(alias="date")] = None,
        meet: Annotated[str | None, Query()] = None,
        race_id: Annotated[int | None, Query()] = None,
        trial_id: Annotated[int | None, Query()] = None,
    ) -> HTMLResponse | RedirectResponse:
        if _is_mobile_request(request):
            return _mobile_redirect(request, "/m")
        selected_meet = int(meet) if meet and meet.isdigit() else None
        with session_factory() as session:
            data = load_dashboard(
                session,
                selected_date=race_date,
                selected_meet=selected_meet,
                selected_race_id=race_id,
                selected_trial_id=trial_id,
            )
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={"active_nav": "races", "dashboard": data},
        )

    @app.get("/m", response_class=HTMLResponse)
    def mobile_dashboard(
        request: Request,
        race_date: Annotated[date | None, Query(alias="date")] = None,
        meet: Annotated[str | None, Query()] = None,
        race_id: Annotated[int | None, Query()] = None,
        trial_id: Annotated[int | None, Query()] = None,
    ) -> HTMLResponse:
        selected_meet = int(meet) if meet and meet.isdigit() else None
        with session_factory() as session:
            data = load_dashboard(
                session,
                selected_date=race_date,
                selected_meet=selected_meet,
                selected_race_id=race_id,
                selected_trial_id=trial_id,
                home_path="/m",
            )
        return templates.TemplateResponse(
            request=request,
            name="mobile/home.html",
            context={"active_nav": "races", "dashboard": data},
        )

    @app.get("/races/{race_id}", response_class=HTMLResponse)
    def race_detail(request: Request, race_id: int) -> HTMLResponse:
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

    @app.get("/data-status", response_class=HTMLResponse)
    def data_status(request: Request) -> HTMLResponse:
        with session_factory() as session:
            page = load_data_status(session)
        return templates.TemplateResponse(
            request=request,
            name="data_status.html",
            context={"active_nav": "data-status", "page": page},
        )

    @app.get("/predictions", response_class=HTMLResponse)
    def predictions(request: Request) -> HTMLResponse:
        with session_factory() as session:
            page = load_prediction_ledger(session)
        return templates.TemplateResponse(
            request=request,
            name="predictions.html",
            context={"active_nav": "predictions", "page": page},
        )

    @app.get("/forecast", response_class=HTMLResponse)
    def forecast(
        request: Request,
        race_date: Annotated[date | None, Query(alias="date")] = None,
        meet: Annotated[int | None, Query(ge=1, le=4)] = None,
        distance: Annotated[int | None, Query(ge=800, le=4000)] = None,
        grade: Annotated[str, Query(max_length=50)] = "",
        race_id: Annotated[int | None, Query(ge=1)] = None,
    ) -> HTMLResponse:
        def load():
            with session_factory() as session:
                return load_forecast_page(
                    session,
                    selected_date=race_date,
                    meet=meet,
                    distance=distance,
                    grade=grade,
                    race_id=race_id,
                )

        page = cached(("forecast", race_date, meet, distance, grade, race_id), load)
        return templates.TemplateResponse(
            request=request,
            name="forecast.html",
            context={"active_nav": "forecast", "page": page},
        )

    @app.get("/validation", response_class=HTMLResponse)
    def validation(
        request: Request,
        start: Annotated[date | None, Query()] = None,
        end: Annotated[date | None, Query()] = None,
        meet: Annotated[int | None, Query(ge=1, le=4)] = None,
        distance: Annotated[int | None, Query(ge=800, le=4000)] = None,
        grade: Annotated[str, Query(max_length=50)] = "",
        model: Annotated[str, Query(max_length=100)] = "",
        mode: Annotated[str, Query(pattern="^(|live|historical)$")] = "",
    ) -> HTMLResponse:
        if start and end and start > end:
            raise HTTPException(status_code=422, detail="시작일은 종료일보다 늦을 수 없습니다.")

        def load():
            with session_factory() as session:
                return load_validation_page(
                    session,
                    start=start,
                    end=end,
                    meet=meet,
                    distance=distance,
                    grade=grade,
                    model=model,
                    mode=mode,
                )

        page = cached(("validation", start, end, meet, distance, grade, model, mode), load)
        return templates.TemplateResponse(
            request=request,
            name="validation.html",
            context={"active_nav": "validation", "page": page},
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
    ) -> HTMLResponse | RedirectResponse:
        if _is_mobile_request(request):
            return _mobile_redirect(request, "/m/analysis")
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
    def mobile_analysis_workspace(
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
                )

        data = cached(("entity-list", kind_slug, q, page, sort), load, ttl=60.0)
        if data is None:
            raise HTTPException(status_code=404, detail="Not found")
        return templates.TemplateResponse(
            request=request,
            name="entity_list.html",
            context={"active_nav": kind_slug, "page_data": data},
        )

    @app.get("/{kind_slug}/{entity_id}", response_class=HTMLResponse)
    def entity_detail(
        request: Request,
        kind_slug: str,
        entity_id: int,
    ) -> HTMLResponse:
        if kind_slug not in ENTITY_KINDS:
            raise HTTPException(status_code=404, detail="Not found")
        with session_factory() as session:
            data = load_entity_detail(session, kind_slug=kind_slug, entity_id=entity_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Not found")
        return templates.TemplateResponse(
            request=request,
            name="entity_detail.html",
            context={"active_nav": kind_slug, "detail": data},
        )

    return app


app = create_app()

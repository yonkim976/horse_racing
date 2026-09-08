from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from horse_racing.db.session import SessionLocal
from horse_racing.web.dashboard import load_dashboard
from horse_racing.web.data_status import load_data_status
from horse_racing.web.distance_page import GRADE_LABELS, load_distance_page
from horse_racing.web.entities import (
    DEFAULT_PAGE_SIZE,
    ENTITY_KINDS,
    load_entity_detail,
    load_entity_list,
)
from horse_racing.web.predictions import load_prediction_ledger
from horse_racing.web.race_page import load_race_page
from horse_racing.web.trial_page import load_running_trial_page

WEB_ROOT = Path(__file__).parent


def create_app(
    session_factory: Callable[[], Session] = SessionLocal,
) -> FastAPI:
    app = FastAPI(
        title="한국 경마 데이터 보드",
        description="한국마사회 일정과 결과를 조회하는 로컬 대시보드",
    )
    templates = Jinja2Templates(directory=WEB_ROOT / "templates")
    app.mount("/static", StaticFiles(directory=WEB_ROOT / "static"), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
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
            )
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
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

    @app.get("/racecourses/jeju/distances", response_class=HTMLResponse)
    def jeju_distances(
        request: Request,
        year: Annotated[int | None, Query(ge=0, le=9999)] = None,
        distance: Annotated[int, Query(ge=0, le=10000)] = 0,
        grade: str = "",
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> HTMLResponse:
        if grade and grade not in GRADE_LABELS:
            raise HTTPException(status_code=422, detail="지원하지 않는 등급입니다.")
        with session_factory() as session:
            data = load_distance_page(
                session, year=year, distance=distance, grade=grade, page=page,
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
        q: Annotated[str, Query()] = "",
        page: Annotated[int, Query(ge=1)] = 1,
        sort: Annotated[str, Query()] = "starts",
    ) -> HTMLResponse:
        if kind_slug not in ENTITY_KINDS:
            raise HTTPException(status_code=404, detail="Not found")
        with session_factory() as session:
            data = load_entity_list(
                session,
                kind_slug=kind_slug,
                query=q,
                page=page,
                page_size=DEFAULT_PAGE_SIZE,
                sort=sort,
            )
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

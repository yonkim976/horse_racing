from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from horse_racing.db.session import SessionLocal
from horse_racing.web.dashboard import load_dashboard

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

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        race_date: Annotated[date | None, Query(alias="date")] = None,
        meet: Annotated[int | None, Query()] = None,
        race_id: Annotated[int | None, Query()] = None,
    ) -> HTMLResponse:
        with session_factory() as session:
            data = load_dashboard(
                session,
                selected_date=race_date,
                selected_meet=meet,
                selected_race_id=race_id,
            )
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={"dashboard": data},
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

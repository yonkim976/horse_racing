"""No public-app integration, arbitrary SQL, command execution or write routes."""

from __future__ import annotations

import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.exc import SQLAlchemyError

from horse_racing.operations import read_model as read
from horse_racing.operations.database import ROOT, create_sessions

ASSETS = Path(__file__).with_name("assets")
KINDS = Literal[
    "entries",
    "sections",
    "groups",
    "stewards",
    "trials",
    "training",
    "medical",
    "start",
    "swim",
    "hill",
]


class Reads:
    def __init__(self, factory=None):
        self.factory = factory
        self.lock = threading.Lock()
        self.cache = {}
        self.retry_after = 0

    def query(self, fn, *args, cache_key=None, **kwargs):
        # Serialize this low-traffic local console; single DB connection, no stampede.
        with self.lock:
            if cache_key in self.cache:
                saved, value = self.cache[cache_key]
                if time.monotonic() - saved < 60:
                    return value
            if self.factory is None:
                if time.monotonic() < self.retry_after:
                    raise HTTPException(
                        503, "DB 연결 설정을 확인하세요. 잠시 후 다시 조회할 수 있습니다."
                    )
                try:
                    self.factory = create_sessions()
                except (ValueError, OSError, SQLAlchemyError, TimeoutError) as exc:
                    self.retry_after = time.monotonic() + 30
                    raise HTTPException(
                        503,
                        "DB 비밀값 또는 연결 설정을 읽지 못했습니다. 실행 터미널의 Google 인증과 조회 권한을 확인하세요.",
                    ) from exc
                except Exception as exc:
                    self.retry_after = time.monotonic() + 30
                    raise HTTPException(
                        503, "DB 설정을 읽지 못했습니다. 자격 증명은 화면에 표시하지 않습니다."
                    ) from exc
            try:
                with self.factory() as session:
                    result = fn(session, *args, **kwargs)
                    # Session closes with ROLLBACK. No commit, even for successful reads.
            except SQLAlchemyError as exc:
                raise HTTPException(
                    503,
                    "DB 조회에 실패했습니다. 연결·조회 권한·응답 시간을 확인하세요. 데이터는 수정하지 않았습니다.",
                ) from exc
            if cache_key:
                self.cache[cache_key] = (time.monotonic(), result)
            return result


def validate_dates(start, end):
    if start > end or (end - start).days > 30:
        raise HTTPException(422, "조회 기간은 시작일 ≤ 종료일, 최대 31일이어야 합니다.")


def create_app(*, port=8765, session_factory=None):
    reads = Reads(session_factory)
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if reads.factory is not None:
            reads.factory.kw["bind"].dispose()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.reads = reads
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{host}" for host in hosts}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "").lower()
        client = request.client.host if request.client else ""
        if client not in {"127.0.0.1", "::1"} or host not in hosts:
            return JSONResponse({"detail": "로컬 주소에서만 접근할 수 있습니다."}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            return JSONResponse({"detail": "읽기 전용입니다."}, status_code=405)
        if request.headers.get("origin") not in origins | {None} or (
            request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse(
                {"detail": "외부 페이지의 요청은 허용하지 않습니다."}, status_code=403
            )
        if request.url.path.startswith("/api/") and not secrets.compare_digest(
            request.headers.get("x-operations-token", "").encode("utf-8"), token.encode("ascii")
        ):
            return JSONResponse({"detail": "대시보드를 다시 열어 주세요."}, status_code=403)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                    "img-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; "
                    "form-action 'self'; frame-ancestors 'none'"
                )
                if request.url.path != "/manual"
                else (
                    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                    "connect-src 'none'; img-src 'none'; object-src 'none'; base-uri 'none'; "
                    "form-action 'none'; frame-ancestors 'none'"
                ),
            }
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (ASSETS / "index.html").read_text().replace("__OPS_TOKEN__", token)

    @app.get("/assets/{asset}")
    def asset(asset: str):
        names = {"dashboard.css": "text/css", "dashboard.js": "application/javascript"}
        if asset not in names:
            raise HTTPException(404)
        return Response((ASSETS / asset).read_text(), media_type=names[asset])

    @app.get("/manual", response_class=HTMLResponse)
    def manual():
        return (ROOT / "operations/index.html").read_text()

    @app.get("/api/overview")
    def overview():
        return reads.query(read.overview, cache_key="overview")

    @app.get("/api/runs")
    def runs(
        start: date,
        end: date,
        data_type: str | None = Query(None, max_length=100),
        status: Literal["completed", "failed", "partial", "running"] | None = None,
        before_id: int | None = Query(None, ge=1),
    ):
        validate_dates(start, end)
        return reads.query(
            read.history, start, end, data_type=data_type, status=status, before_id=before_id
        )

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: int):
        if run_id < 1:
            raise HTTPException(422)
        result = reads.query(read.run_detail, run_id)
        if result is None:
            raise HTTPException(404, "실행 이력이 없습니다.")
        return result

    @app.get("/api/horses")
    def horses(q: str = Query(min_length=2, max_length=60)):
        return reads.query(read.horse_search, q.strip()) if len(q.strip()) >= 2 else {"rows": []}

    @app.get("/api/data")
    def data(
        kind: KINDS,
        start: date,
        end: date,
        horse_id: int | None = Query(None, ge=1),
        meet: int | None = Query(None, ge=1, le=4),
        race_no: int | None = Query(None, ge=1, le=30),
    ):
        validate_dates(start, end)
        return reads.query(
            read.search_data, kind, start, end, horse_id=horse_id, meet=meet, race_no=race_no
        )

    @app.get("/api/issues")
    def issues():
        return reads.query(read.suspected_gaps, cache_key="issues")

    return app

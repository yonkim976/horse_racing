"""Private feedback writes isolated from the read-only racing database engine."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from threading import Lock
from time import monotonic, time
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import (
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
    func,
    insert,
    select,
    text,
)
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from horse_racing.config import get_settings
from horse_racing.web.security import BoundedRequestLimiter

_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
                    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
                    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+")
_PAGE = re.compile(
    r"/(?:|analysis|forecast|validation|predictions|data-status|guide|privacy|"
    r"horses(?:/list)?|jockeys|trainers|owners|"
    r"(?:races|running-trials|horses|jockeys|trainers|owners)/[A-Za-z0-9_-]{1,64}|"
    r"racecourses/(?:seoul|jeju|busan|yeongcheon)/(?:course|distances))"
)
_PAGE_KEYS = frozenset({"race_id", "date", "meet", "tab", "distance", "year", "period"})
_NO_STORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}
_COOKIE = "mapilog-feedback-id"


def sanitize_page_path(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or parts.fragment or not _PAGE.fullmatch(parts.path):
        raise ValueError("Invalid page context")
    params = [(key, item) for key, item in parse_qsl(parts.query, max_num_fields=20)
              if key in _PAGE_KEYS and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", item)]
    return parts.path + ("?" + urlencode(params) if params else "")


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=36, max_length=36)
    category: str = Field(pattern=r"^(오류 제보|개선 제안|기타 의견)$")
    message: str = Field(min_length=10, max_length=1000)
    email: str | None = Field(default=None, max_length=254)
    page_path: str | None = Field(default=None, max_length=500)
    website: str = Field(default="", max_length=200)

    @field_validator("request_id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("Expected UUID4")
        return value

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10 or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
            raise ValueError("Invalid feedback text")
        return value

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not _EMAIL.fullmatch(value):
            raise ValueError("Invalid email")
        return value

    @field_validator("page_path")
    @classmethod
    def clean_page(cls, value: str | None) -> str | None:
        return sanitize_page_path(value)


class FeedbackLimit(Exception):
    pass


class FeedbackConflict(Exception):
    pass


class FeedbackStore:
    def __init__(self, database_url: str, secret: str):
        self.secret = secret.encode()
        self._sqlite_lock = Lock()
        postgres = database_url.startswith("postgresql")
        options = ({"pool_size": 1, "max_overflow": 0, "pool_timeout": 5,
                    "pool_recycle": 300, "pool_pre_ping": True,
                    "connect_args": {"connect_timeout": 5}}
                   if postgres else {"connect_args": {"check_same_thread": False}})
        self.engine = create_engine(database_url, hide_parameters=True, **options)
        if self.engine.dialect.name not in {"sqlite", "postgresql"}:
            raise ValueError("Unsupported feedback database")
        metadata = MetaData(schema="mapilog_feedback" if postgres else None)
        self.entries = Table(
            "entries", metadata,
            Column("request_id", Uuid, primary_key=True),
            Column("category", String(20), nullable=False),
            Column("message", Text, nullable=False),
            Column("email", String(254)),
            Column("page_path", String(500)),
            Column("client_hash", String(64), nullable=False),
            Column("payload_hash", String(64), nullable=False),
            Column("created_at", DateTime(timezone=True), nullable=False),
        )
        Index("feedback_client_created_idx", self.entries.c.client_hash,
              self.entries.c.created_at)
        Index("feedback_created_idx", self.entries.c.created_at)
        if not postgres:
            metadata.create_all(self.engine)

    def client_hash(self, client: str) -> str:
        return hmac.new(self.secret, b"feedback-client:" + client.encode(), "sha256").hexdigest()

    def browser_identity(self, cookie: str | None) -> tuple[str, str, bool]:
        """Signed anonymous identity avoids coupling users behind a shared proxy/NAT."""
        if cookie and re.fullmatch(r"[0-9a-f]{32}\.[0-9a-f]{64}", cookie):
            identity, signature = cookie.split(".")
            expected = hmac.new(self.secret, f"browser:{identity}".encode(),
                                "sha256").hexdigest()
            if hmac.compare_digest(signature, expected):
                return identity, cookie, False
        identity = secrets.token_hex(16)
        signature = hmac.new(self.secret, f"browser:{identity}".encode(), "sha256").hexdigest()
        return identity, f"{identity}.{signature}", True

    def token(self, client: str) -> str:
        body = f"{int(time()) + 3600}.{secrets.token_hex(16)}"
        signature = hmac.new(self.secret, f"csrf:{body}:{self.client_hash(client)}".encode(),
                             "sha256").hexdigest()
        return f"{body}.{signature}"

    def verify_token(self, token: str, client: str) -> bool:
        if len(token) > 120:
            return False
        parts = token.split(".")
        if len(parts) != 3 or not re.fullmatch(r"[0-9]{10}", parts[0]):
            return False
        if not re.fullmatch(r"[0-9a-f]{32}", parts[1]):
            return False
        if not re.fullmatch(r"[0-9a-f]{64}", parts[2]):
            return False
        expiry = int(parts[0])
        if not time() <= expiry <= time() + 3601:
            return False
        signature = hmac.new(self.secret,
                             f"csrf:{parts[0]}.{parts[1]}:{self.client_hash(client)}".encode(),
                             "sha256").hexdigest()
        return hmac.compare_digest(signature, parts[2])

    def save(self, data: FeedbackInput, client: str) -> str:
        now = datetime.now(UTC)
        client_hash = self.client_hash(client)
        payload_hash = hmac.new(self.secret, json.dumps(
            data.model_dump(exclude={"request_id", "website"}), sort_keys=True,
            ensure_ascii=False,
        ).encode(), 'sha256').hexdigest()
        entries = self.entries
        # A transaction lock makes quotas and idempotency atomic across instances.
        # SQLite is used only for development; the lock is process-local there.
        with self._sqlite_lock, self.engine.begin() as connection:
            if self.engine.dialect.name == "postgresql":
                connection.execute(text("SET LOCAL statement_timeout = '5s'"))
                connection.execute(text("SET LOCAL lock_timeout = '2s'"))
                connection.execute(text("SELECT pg_advisory_xact_lock(710112026)"))
                now = connection.execute(select(func.now())).scalar_one()
            existing = connection.execute(select(
                entries.c.client_hash, entries.c.payload_hash,
            ).where(entries.c.request_id == UUID(data.request_id))).first()
            if existing:
                if existing.client_hash == client_hash and existing.payload_hash == payload_hash:
                    return data.request_id
                raise FeedbackConflict
            def count_since(start: datetime, *, client_only: bool = False) -> int:
                query = select(func.count(entries.c.request_id)).where(
                    entries.c.created_at >= start,
                )
                if client_only:
                    query = query.where(entries.c.client_hash == client_hash)
                return connection.execute(query).scalar_one()
            if (count_since(now - timedelta(hours=1), client_only=True) >= 5
                    or count_since(now - timedelta(days=1), client_only=True) >= 20
                    or count_since(now - timedelta(days=1)) >= 1000):
                raise FeedbackLimit
            connection.execute(insert(entries).values(
                request_id=UUID(data.request_id), category=data.category, message=data.message,
                email=data.email, page_path=data.page_path, client_hash=client_hash,
                payload_hash=payload_hash, created_at=now,
            ))
        return data.request_id


@lru_cache(maxsize=1)
def get_feedback_store() -> FeedbackStore:
    settings = get_settings()
    url = settings.feedback_database_url
    secret = settings.feedback_secret
    if os.getenv("K_SERVICE") and (url is None or secret is None):
        raise ValueError("Production feedback requires isolated database and signing secrets")
    if secret is not None and len(secret.get_secret_value()) < 32:
        raise ValueError("Feedback signing secret must have at least 32 characters")
    return FeedbackStore(
        url.get_secret_value() if url else "sqlite:///data/feedback.sqlite3",
        secret.get_secret_value() if secret else secrets.token_hex(32),
    )


def _same_origin(request: Request, *, required: bool) -> bool:
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return not required
    if request.url.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}:
        return origin == str(request.base_url).rstrip("/")
    return origin in {"https://mapilog.xyz", "https://www.mapilog.xyz"}


def create_feedback_router(*, client_key: Callable[[Request], str]) -> APIRouter:
    router = APIRouter()
    limiter = BoundedRequestLimiter(max_clients=4096, idle_ttl=120.0)

    def response(status: int, message: str, **extra: object) -> JSONResponse:
        headers = dict(_NO_STORE)
        if status == 429:
            headers["Retry-After"] = "3600"
        return JSONResponse({"ok": status < 400, "message": message, **extra},
                            status_code=status, headers=headers)

    def admitted(client: str, *, token: bool) -> bool:
        return limiter.allow(
            ("token:" if token else "submit:") + client,
            now=monotonic(),
            window_seconds=60, window_limit=120 if token else 60,
            burst_seconds=10, burst_limit=30 if token else 20,
        )

    @router.get("/api/feedback/token", include_in_schema=False)
    async def feedback_token(request: Request) -> JSONResponse:
        if not _same_origin(request, required=False):
            return response(403, "현재 화면에서 다시 시도해 주세요.")
        client = client_key(request)
        if not admitted(client, token=True):
            return response(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요.")
        try:
            store = await run_in_threadpool(get_feedback_store)
        except (ValueError, SQLAlchemyError, OSError):
            return response(503, "의견 접수를 잠시 사용할 수 없습니다.")
        identity, cookie, new_cookie = store.browser_identity(request.cookies.get(_COOKIE))
        result = response(200, "", token=store.token(identity))
        if new_cookie:
            result.set_cookie(_COOKIE, cookie, max_age=7 * 24 * 3600, path="/api/feedback",
                              httponly=True, secure=request.url.scheme == "https", samesite="lax")
        return result

    @router.post("/api/feedback", include_in_schema=False)
    async def submit_feedback(request: Request) -> JSONResponse:
        if not _same_origin(request, required=True):
            return response(403, "현재 화면에서 다시 시도해 주세요.")
        client = client_key(request)
        if not admitted(client, token=False):
            return response(429, "요청이 많습니다. 잠시 후 다시 시도해 주세요.")
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            return response(415, "요청 형식이 올바르지 않습니다.")
        body = bytearray()
        try:
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 8192:
                        return response(413, "의견 내용이 너무 깁니다.")
            data = FeedbackInput.model_validate(json.loads(body))
        except (ValueError, ValidationError, TimeoutError, ClientDisconnect, RecursionError):
            return response(422, "의견은 10~1,000자, 이메일은 올바른 형식으로 입력해 주세요.")
        try:
            store = await run_in_threadpool(get_feedback_store)
            identity, _cookie, new_cookie = store.browser_identity(request.cookies.get(_COOKIE))
            if new_cookie or not store.verify_token(
                request.headers.get("x-feedback-token", ""), identity,
            ):
                return response(403, "작성 시간이 만료되었습니다. 다시 보내 주세요.")
            if data.website:
                return response(202, "의견을 접수했습니다.", reference=str(uuid4()))
            reference = await run_in_threadpool(store.save, data, identity)
        except FeedbackLimit:
            return response(429, "접수 횟수를 초과했습니다. 1시간 뒤 다시 시도해 주세요.")
        except FeedbackConflict:
            return response(409, "접수 정보가 변경되었습니다. 창을 다시 열어 주세요.")
        except (ValueError, SQLAlchemyError, OSError):
            # Never log database exception strings: they may contain user content.
            return response(503, "접수하지 못했습니다. 내용은 유지되니 다시 시도해 주세요.")
        return response(201, "의견을 접수했습니다.", reference=reference)

    return router

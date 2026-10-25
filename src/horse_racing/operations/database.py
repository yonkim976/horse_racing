"""Private credentials and transaction-scoped read guards; no collector imports."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from horse_racing.config import Settings

ROOT = Path(__file__).resolve().parents[3]
PROJECT_REF = "xkykmhhkjtosptoibduo"


def resolve_url():
    settings = Settings(_env_file=ROOT / ".env")
    explicit = os.environ.get("HORSE_RACING_OPERATIONS_DATABASE_URL")
    candidate = explicit or settings.web_database_url or settings.database_url
    url = make_url(candidate)
    if url.get_backend_name() != "postgresql":
        if explicit or settings.web_database_url:
            raise ValueError("operations_requires_postgres")
        # Same existing secret as the collectors. Never print stdout/stderr.
        result = subprocess.run(
            [
                shutil.which("gcloud") or "/Users/kimyongjin/google-cloud-sdk/bin/gcloud",
                "secrets",
                "versions",
                "access",
                "3",
                "--secret=horse-racing-database-url",
                "--project=mapilog-509017",
            ],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        if result.returncode:
            raise ValueError("database_secret_unavailable")
        url = make_url(result.stdout.strip())
    direct = url.host == f"db.{PROJECT_REF}.supabase.co"
    pooled = (url.host or "").endswith(".pooler.supabase.com") and (url.username or "").endswith(
        f".{PROJECT_REF}"
    )
    if url.get_backend_name() != "postgresql" or not (direct or pooled):
        raise ValueError("unexpected_database_target")
    if url.database != "postgres":
        raise ValueError("unexpected_database_name")
    # Do not inherit arbitrary libpq options (e.g. a disabled TLS setting).
    return url.set(
        drivername="postgresql+psycopg",
        query={
            "sslmode": "require",
            "connect_timeout": "8",
            "application_name": "horse_racing_local_operations_readonly",
        },
    )


def guard_transaction(connection):
    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    connection.exec_driver_sql("SET LOCAL statement_timeout = '8s'")
    connection.exec_driver_sql("SET LOCAL lock_timeout = '1s'")
    connection.exec_driver_sql("SET LOCAL idle_in_transaction_session_timeout = '15s'")


def create_sessions():
    engine = create_engine(
        resolve_url(),
        pool_size=1,
        max_overflow=0,
        pool_timeout=10,
        pool_pre_ping=True,
        pool_recycle=180,
        hide_parameters=True,
    )
    event.listen(engine, "begin", guard_transaction)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

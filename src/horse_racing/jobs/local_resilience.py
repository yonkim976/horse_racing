"""Bounded local connection recovery and credential-free failure diagnostics."""

from __future__ import annotations

import re
import time
from contextlib import contextmanager

from sqlalchemy.exc import OperationalError


def safe_failure(exc):
    """Inspect locally, but emit only fixed categories, never exception text/URLs."""
    from horse_racing.collectors.kra_api import KraApiError

    if isinstance(exc, KraApiError):
        return {"error_type": type(exc).__name__, **exc.safe_details()}
    original = getattr(exc, "orig", exc)
    code = getattr(original, "sqlstate", None)
    code = code if isinstance(code, str) and re.fullmatch(r"[A-Z0-9]{5}", code) else None
    message = str(original).lower()
    reason = "unclassified"
    for fragments, category in (
        (("password authentication", "authentication failed"), "authentication"),
        (("could not translate", "name or service not known", "nodename nor servname"), "dns"),
        (("network is unreachable", "no route to host"), "network_unreachable"),
        (("connection refused",), "connection_refused"),
        (("timeout", "timed out"), "timeout"),
        (("too many connections", "remaining connection slots", "maxclients"), "connection_limit"),
        (
            ("server closed", "connection is closed", "ssl connection has been closed"),
            "connection_closed",
        ),
        (("certificate verify", "ssl error"), "tls"),
    ):
        if any(fragment in message for fragment in fragments):
            reason = category
            break
    details = {"error_type": type(exc).__name__, "error_reason": reason}
    if code:
        details["sqlstate"] = code
    return details


def transient_connect_failure(exc):
    if not isinstance(exc, OperationalError):
        return False
    details = safe_failure(exc)
    code = details.get("sqlstate")
    if details["error_reason"] in {"authentication", "tls"} or (code and code[:2] == "28"):
        return False
    return code is None or code.startswith("08") or code in {"53300", "57P03"}


@contextmanager
def connect_local_database(engine, emit, *, sleep=time.sleep):
    """Retry only opening a connection: never replay a transaction/ambiguous commit."""
    for attempt in range(1, 4):
        try:
            connection = engine.connect()
            break
        except OperationalError as exc:
            retry = attempt < 3 and transient_connect_failure(exc)
            emit("local_database_connect_failed", attempt=attempt, retry=retry, **safe_failure(exc))
            if not retry:
                raise
            sleep(2 if attempt == 1 else 5)
    with connection:
        yield connection


def release_database_locks(connection, keys, emit):
    """A lost idle lock connection must not overwrite an already committed summary."""
    from sqlalchemy import text

    try:
        for key in reversed(keys):
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        connection.commit()
    except Exception as exc:
        emit("local_database_lock_release_failed", **safe_failure(exc))

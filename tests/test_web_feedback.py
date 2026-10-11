"""Feedback writes must remain private, optional-email, bounded and idempotent."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from horse_racing.web import feedback
from horse_racing.web.app import create_app


@pytest.fixture
def store(tmp_path):
    value = feedback.FeedbackStore(f"sqlite:///{tmp_path}/feedback.sqlite3", "a" * 64)
    yield value
    value.engine.dispose()


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(feedback, "get_feedback_store", lambda: store)
    for name in ("MAPILOG_ORIGIN_TOKEN", "MAPILOG_REQUIRE_ORIGIN_TOKEN", "MAPILOG_ORIGIN_HTTPS"):
        monkeypatch.delenv(name, raising=False)

    def forbidden_racing_database():
        raise AssertionError("Feedback must never open the racing DB")

    with TestClient(create_app(session_factory=forbidden_racing_database)) as value:
        yield value


def payload(**changes):
    return {"request_id": str(uuid4()), "category": "개선 제안",
            "message": "이메일 없이도 의견이 잘 접수되는지 확인합니다.", **changes}


def headers(client):
    response = client.get("/api/feedback/token")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return {"Origin": "http://testserver", "X-Feedback-Token": response.json()["token"]}


@pytest.mark.parametrize("email", [None, "", "  ", "reply@example.com"])
def test_optional_email_persists_privately(client, store, email):
    body = payload(email=email, page_path="/analysis?meet=1&q=private-search")
    response = client.post("/api/feedback", json=body, headers=headers(client))
    assert response.status_code == 201
    assert response.json()["reference"] == body["request_id"]
    assert response.headers["cache-control"] == "no-store"
    with store.engine.connect() as connection:
        row = connection.execute(select(store.entries)).one()
    assert row.email == (email.strip() if email and email.strip() else None)
    assert row.page_path == "/analysis?meet=1"
    assert row.client_hash != "testclient" and len(row.client_hash) == 64
    assert body["message"] not in response.text
    assert client.get("/api/feedback").status_code in {404, 405}


def test_retry_is_idempotent_but_changed_payload_is_rejected(client, store):
    body = payload()
    auth = headers(client)
    first = client.post("/api/feedback", json=body, headers=auth)
    retry = client.post("/api/feedback", json=body, headers=auth)
    conflict = client.post("/api/feedback", json={**body, "email": "other@example.com"},
                           headers=auth)
    assert first.status_code == retry.status_code == 201
    assert first.json()["reference"] == retry.json()["reference"]
    assert conflict.status_code == 409
    with store.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(store.entries)) == 1


@pytest.mark.parametrize("origin", [None, "https://evil.example", "null"])
def test_cross_site_submit_rejected(client, origin):
    auth = headers(client)
    if origin is None:
        del auth["Origin"]
    else:
        auth["Origin"] = origin
    assert client.post("/api/feedback", json=payload(), headers=auth).status_code == 403


@pytest.mark.parametrize("token", ["", "0.bad.fake", "1" * 500, "not-a-token"])
def test_missing_or_tampered_token_rejected(client, token):
    assert client.post("/api/feedback", json=payload(), headers={
        "Origin": "http://testserver", "X-Feedback-Token": token,
    }).status_code == 403


def test_token_bound_to_client_and_expires(store, monkeypatch):
    monkeypatch.setattr(feedback, "time", lambda: 1_800_000_000)
    token = store.token("client-one")
    assert store.verify_token(token, "client-one")
    assert not store.verify_token(token, "client-two")
    monkeypatch.setattr(feedback, "time", lambda: 1_800_003_601)
    assert not store.verify_token(token, "client-one")


def test_signed_browser_identity_cannot_be_forged(store):
    identity, cookie, new = store.browser_identity(None)
    assert new
    assert store.browser_identity(cookie) == (identity, cookie, False)
    assert store.browser_identity(cookie[:-1] + ("0" if cookie[-1] != "0" else "1"))[2]


def test_feedback_cookie_scoped_http_only_and_required(client):
    auth = headers(client)
    cookie = next(item for item in client.cookies.jar if item.name == "mapilog-feedback-id")
    assert cookie.path == "/api/feedback"
    assert cookie.has_nonstandard_attr("HttpOnly")
    client.cookies.clear()
    assert client.post("/api/feedback", json=payload(), headers=auth).status_code == 403


@pytest.mark.parametrize("changes", [
    {"message": "short"}, {"message": " " * 20}, {"message": "a" * 1001},
    {"email": "private-invalid-email"}, {"category": "unknown"},
    {"page_path": "https://evil.example/private"}, {"page_path": "//evil.example/private"},
    {"page_path": "/analysis#private-data"}, {"email": "line\n@example.com"},
    {"unexpected": "private-input"}, {"request_id": str(uuid4()).upper()},
])
def test_invalid_data_not_reflected(client, changes):
    response = client.post("/api/feedback", json=payload(**changes), headers=headers(client))
    assert response.status_code == 422
    assert "private-" not in response.text


def test_oversized_and_non_json_requests_rejected(client):
    auth = headers(client)
    assert client.post("/api/feedback", content="x" * 9000,
                       headers={**auth, "Content-Type": "application/json"}).status_code == 413
    assert client.post("/api/feedback", data={"message": "test"},
                       headers=auth).status_code == 415


def test_honeypot_avoids_database_insert(client, store):
    response = client.post("/api/feedback", json=payload(website="spam.example"),
                           headers=headers(client))
    assert response.status_code == 202
    with store.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(store.entries)) == 0


def test_database_limit_atomic_and_idempotent_retry_still_allowed(store):
    bodies = [feedback.FeedbackInput.model_validate(payload()) for _ in range(8)]

    def save(data):
        try:
            store.save(data, "shared-client")
            return True
        except feedback.FeedbackLimit:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(save, bodies))
    assert sum(outcomes) == 5
    accepted = bodies[outcomes.index(True)]
    assert store.save(accepted, "shared-client") == accepted.request_id
    # Last-hour quota can expire while the daily quota remains effective.
    with store.engine.begin() as connection:
        connection.execute(update(store.entries).values(
            created_at=datetime.now(UTC) - timedelta(hours=2),
        ))
    store.save(feedback.FeedbackInput.model_validate(payload()), "shared-client")


def test_storage_failure_safe_and_no_false_success(client, store, monkeypatch, capsys):
    def failing(*args):
        raise OperationalError("private-sql", {"email": "secret@example.com"},
                               RuntimeError("private-detail"))

    monkeypatch.setattr(store, "save", failing)
    response = client.post("/api/feedback", json=payload(), headers=headers(client))
    assert response.status_code == 503
    assert response.json()["ok"] is False
    assert "private-" not in response.text + capsys.readouterr().out


def test_private_input_keeps_markup_as_text(client, store):
    body = payload(message="<script>alert('not executable')</script>")
    assert client.post("/api/feedback", json=body, headers=headers(client)).status_code == 201
    with store.engine.connect() as connection:
        assert connection.scalar(select(store.entries.c.message)) == body["message"]


def test_page_context_filters_sensitive_query():
    assert feedback.sanitize_page_path("/horses/list?q=secret&meet=1") == "/horses/list?meet=1"
    with pytest.raises(ValidationError):
        feedback.FeedbackInput.model_validate(payload(page_path="/unrelated/private"))

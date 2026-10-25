import importlib
from datetime import date

from fastapi.testclient import TestClient
from test_dashboard import seeded_session

from horse_racing.web.app import create_app


def test_schedule_poll_is_bounded_read_only_and_checks_date_and_meet(tmp_path, monkeypatch):
    module = importlib.import_module("horse_racing.web.app")
    monkeypatch.setattr(module, "today_seoul", lambda: date(2026, 8, 21))
    monkeypatch.setattr(module, "now_seoul_ms", lambda: 100_000)
    factory = seeded_session(tmp_path)
    with TestClient(create_app(factory)) as client:
        response = client.get("/api/race-follow?date=2026-08-21&meet=2")
        assert response.status_code == 200
        data = response.json()
        assert data["graceMs"] == 60_000
        assert data["serverNow"] == 100_000
        assert {r["id"] for r in data["races"]} == {1, 2}
        assert all(set(r) == {"id", "start", "status"} for r in data["races"])
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/race-follow?date=2026-08-21&meet=1").json()["races"] == []
        assert client.get("/api/race-follow?date=2026-08-20").json()["races"] == []
        assert client.get("/api/race-follow?date=2026-08-21&meet=9").status_code == 422
        assert client.get("/api/race-follow?date=bad").status_code == 422
        assert client.get("/api/race-follow?date=2026-08-21&date=2026-08-22").status_code == 422

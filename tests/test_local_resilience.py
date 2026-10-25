from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from horse_racing.jobs import local_recovery as recovery
from horse_racing.jobs import local_resilience as resilience
from horse_racing.services import discord_notifications as discord

NOW = datetime(2026, 10, 10, 23, 30, tzinfo=recovery.catalog.cards.KST)
TOKEN = "synthetic_token_never_a_real_secret"
WEBHOOK = SecretStr(f"https://discord.com/api/webhooks/123456/{TOKEN}")


def failure(**overrides):
    return dict(
        status="failed",
        error_type="OperationalError",
        error_reason="dns",
        failure_phase="connect",
        observed_at=NOW.isoformat(),
        **overrides,
    )


def test_connect_retry_before_any_transaction_and_safe_diagnostics():
    engine, connection, emit, sleep = Mock(), MagicMock(), Mock(), Mock()
    error = OperationalError("secret query", {}, RuntimeError("could not translate " + TOKEN))
    engine.connect.side_effect = [error, error, connection]
    with resilience.connect_local_database(engine, emit, sleep=sleep) as actual:
        assert actual is connection
    assert engine.connect.call_count == 3
    assert [c.args[0] for c in sleep.call_args_list] == [2, 5]
    assert TOKEN not in str(emit.call_args_list)
    assert emit.call_args.kwargs["error_reason"] == "dns"


def test_no_replay_of_transaction_or_fatal_auth():
    engine, sleep = Mock(), Mock()
    engine.connect.return_value = MagicMock()
    with pytest.raises(OperationalError):
        with resilience.connect_local_database(engine, Mock(), sleep=sleep):
            raise OperationalError("commit", {}, RuntimeError(TOKEN))
    assert engine.connect.call_count == 1
    engine.connect.side_effect = OperationalError(
        "", {}, RuntimeError("password authentication failed")
    )
    with pytest.raises(OperationalError):
        with resilience.connect_local_database(engine, Mock(), sleep=sleep):
            pytest.fail("auth failure must not connect")
    sleep.assert_not_called()


def test_unlock_failure_does_not_mask_committed_result():
    connection, emit = Mock(), Mock()
    connection.execute.side_effect = OperationalError(
        "", {}, RuntimeError("server closed " + TOKEN)
    )
    resilience.release_database_locks(connection, [1], emit)
    assert emit.call_args.kwargs["error_reason"] == "connection_closed"
    assert TOKEN not in str(emit.call_args_list)


def test_discord_connect_errors_are_safe_to_retry_but_read_timeout_is_not(monkeypatch):
    monkeypatch.setattr(discord.time, "sleep", Mock())
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) < 3:
            raise httpx.ConnectError(TOKEN, request=request)
        return httpx.Response(200, json={"id": "123"})

    assert discord.send_discord(WEBHOOK, "test", transport=httpx.MockTransport(handler)) == "123"
    assert len(requests) == 3
    requests.clear()

    def read_timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout(TOKEN, request=request)

    with pytest.raises(discord.DiscordNotificationError) as caught:
        discord.send_discord(WEBHOOK, "test", transport=httpx.MockTransport(read_timeout))
    assert len(requests) == 1 and not caught.value.retryable
    assert TOKEN not in str(caught.value)


def test_exhausted_discord_connect_failure_is_pending_not_unknown(monkeypatch):
    monkeypatch.setattr(discord.time, "sleep", Mock())

    def handler(request):
        raise httpx.ConnectTimeout(TOKEN, request=request)

    with pytest.raises(discord.DiscordNotificationError) as caught:
        discord.send_discord(WEBHOOK, "test", transport=httpx.MockTransport(handler))
    assert caught.value.retryable
    assert discord.notification_failure(caught.value)["error_reason"] == "connect_failed_not_sent"


def test_recovery_only_recent_startup_failures_and_never_publication_pending():
    state = failure()
    assert recovery.candidates("canonical", state, NOW)[0]["action"] == "collect"
    assert recovery.candidates("repair", {"last_failure": state}, NOW)
    for changed in (
        {"failure_phase": "work"},
        {"error_reason": "authentication"},
        {"sqlstate": "28P01"},
        {"status": "partial"},
        {"observed_at": (NOW - timedelta(hours=25)).isoformat()},
        {"observed_at": (NOW + timedelta(minutes=1)).isoformat()},
    ):
        assert not recovery.candidates("canonical", dict(state, **changed), NOW)
    assert not recovery.candidates("canonical", {"status": "partial", "pending": [{}]}, NOW)


def test_notification_recovery_is_separate_and_unknown_delivery_is_not_retried():
    state = {
        "status": "completed",
        "observed_at": NOW.isoformat(),
        "run_id": 7,
        "notification": {"status": "failed", "retryable": True},
    }
    assert recovery.candidates("canonical", state, NOW)[0]["action"] == "notify"
    for notification in (
        {"status": "sending"},
        {"status": "delivered"},
        {"status": "failed", "retryable": False},
    ):
        assert not recovery.candidates("canonical", dict(state, notification=notification), NOW)


def test_recovery_dry_run_and_healthy_tick_perform_no_collection(monkeypatch, tmp_path):
    monkeypatch.setattr(recovery.live, "load_settings", lambda: pytest.fail("secret read"))
    monkeypatch.setattr(recovery.catalog, "execute", lambda **_: pytest.fail("collector called"))
    monkeypatch.setattr(recovery.post, "execute", lambda **_: pytest.fail("collector called"))
    monkeypatch.setattr(recovery, "CACHE_PATH", tmp_path / "recovery.json")
    monkeypatch.setattr(recovery.live, "ROOT", tmp_path)
    monkeypatch.setattr(recovery.post, "REPAIR_STATUS_PATH", tmp_path / "repair.json")
    assert recovery.execute() == 0
    assert not list(tmp_path.iterdir())
    assert recovery.execute(apply=True, now=NOW) == 0


def test_recovery_backoff_and_three_attempt_limit(monkeypatch, tmp_path):
    path = tmp_path / "data/state/local-catalog-canonical.json"
    recovery.live.write_state(path, failure())
    monkeypatch.setattr(recovery.live, "ROOT", tmp_path)
    monkeypatch.setattr(recovery, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(recovery.post, "REPAIR_STATUS_PATH", tmp_path / "repair.json")
    monkeypatch.setattr(recovery, "network_ready", lambda _: True)
    worker = Mock(return_value=1)
    monkeypatch.setattr(recovery.catalog, "execute", worker)
    for minutes in (0, 1, 6, 7, 30, 120):
        recovery.execute(apply=True, now=NOW + timedelta(minutes=minutes))
    assert worker.call_count == 3


def test_offline_tick_preserves_recovery_attempts(monkeypatch, tmp_path):
    recovery.live.write_state(tmp_path / "data/state/local-catalog-canonical.json", failure())
    monkeypatch.setattr(recovery.live, "ROOT", tmp_path)
    monkeypatch.setattr(recovery, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(recovery.post, "REPAIR_STATUS_PATH", tmp_path / "repair.json")
    monkeypatch.setattr(recovery, "network_ready", lambda _: False)
    monkeypatch.setattr(recovery.catalog, "execute", lambda **_: pytest.fail("offline collector"))
    assert recovery.execute(apply=True, now=NOW) == 0
    assert not recovery.CACHE_PATH.exists()


def test_repair_status_survives_dividend_ticks(monkeypatch, tmp_path):
    repair_path = tmp_path / "repair.json"
    monkeypatch.setattr(recovery.post, "REPAIR_STATUS_PATH", repair_path)
    shared = tmp_path / "shared.json"
    state = {"last_failure": failure(), "notification": {"status": "failed"}}
    recovery.post.write_execution_state(shared, state, "repair")
    recovery.post.write_execution_state(
        shared, {"last_summary": {"mode": "dividends"}}, "dividends"
    )
    assert recovery.live.read_state(repair_path)["last_failure"]["error_type"] == "OperationalError"


@pytest.mark.parametrize("kind", ["canonical", "repair"])
def test_failed_startup_is_durable_and_notification_status_is_separate(monkeypatch, tmp_path, kind):
    monkeypatch.setattr(recovery.live, "ROOT", tmp_path)
    monkeypatch.setattr(recovery.live, "STATE_PATH", tmp_path / "data/state/live.json")
    monkeypatch.setattr(recovery.post, "ROOT", tmp_path)
    monkeypatch.setattr(recovery.post, "REPAIR_STATUS_PATH", tmp_path / "repair-status.json")
    monkeypatch.setattr(
        recovery.live,
        "load_settings",
        lambda: SimpleNamespace(database_url="postgresql+psycopg://unused", raw_data_dir=tmp_path),
    )
    engine = Mock()
    engine.connect.side_effect = OperationalError(
        "", {}, RuntimeError("password authentication failed " + TOKEN)
    )
    module = recovery.catalog if kind == "canonical" else recovery.post
    monkeypatch.setattr(module, "create_engine_for_url", lambda _: engine)
    monkeypatch.setattr(
        module, "notify", lambda *_a, **_k: {"status": "delivered", "message_id": "1"}
    )
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=5 * 1024**3))
    if kind == "canonical":
        assert module.execute(mode=kind, apply=True, now=NOW) == 1
        state = recovery.live.read_state(tmp_path / "data/state/local-catalog-canonical.json")
        error = state
    else:
        assert (
            module.execute(mode=kind, apply=True, now=NOW, state_path=tmp_path / "shared.json") == 1
        )
        state = recovery.live.read_state(recovery.post.REPAIR_STATUS_PATH)
        error = state["last_failure"]
    assert error["failure_phase"] == "connect" and error["error_reason"] == "authentication"
    assert state["notification"]["status"] == "delivered"
    assert TOKEN not in str(state)
    assert not recovery.candidates(kind, state, NOW)


def test_retry_only_notification_without_db_or_collector(monkeypatch, tmp_path):
    path = tmp_path / "canonical.json"
    recovery.live.write_state(
        path,
        {
            "status": "completed",
            "observed_at": NOW.isoformat(),
            "run_id": 7,
            "notification": {"status": "failed", "retryable": True},
        },
    )
    monkeypatch.setattr(recovery.live, "STATE_PATH", tmp_path / "live.json")
    monkeypatch.setattr(recovery.live, "load_settings", lambda: pytest.fail("DB secret read"))
    monkeypatch.setattr(recovery, "Settings", lambda **_: SimpleNamespace())
    notification = Mock(return_value={"status": "delivered", "message_id": "123"})
    monkeypatch.setattr(recovery.catalog, "notify", notification)
    monkeypatch.setattr(recovery.catalog, "execute", lambda **_: pytest.fail("collector called"))
    recovery.retry_notification("canonical", path, NOW)
    assert notification.call_count == 1
    assert recovery.live.read_state(path)["notification"]["message_id"] == "123"

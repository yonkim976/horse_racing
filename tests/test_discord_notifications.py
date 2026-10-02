import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from pydantic import SecretStr

from horse_racing.config import Settings
from horse_racing.jobs import daily_training as job
from horse_racing.services import discord_notifications as discord

TEST_TOKEN = "synthetic_token_never_a_real_secret"
WEBHOOK = SecretStr(f"https://discord.com/api/webhooks/123456/{TEST_TOKEN}")


def summary():
    return {
        "run_id": 7,
        "window_start": "2026-09-26",
        "window_end": "2026-10-02",
        "failures": 0,
        "elapsed_seconds": 12.3,
        "results": [{"status": "completed"}, {"status": "observed_empty"}],
        "changes": {
            kind: {"new": 2, "changed": 1, "unchanged": 30, "removed_from_latest_snapshot": 0}
            for kind in discord.KINDS
        },
        "latest_training_date_in_window": {kind: "2026-10-01" for kind in discord.KINDS},
    }


def test_send_confirmed_once_and_mentions_disabled():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.params["wait"] == "true"
        assert json.loads(request.content)["allowed_mentions"] == {"parse": []}
        return httpx.Response(200, json={"id": "987654321"})

    assert (
        discord.send_discord(
            WEBHOOK, "연결 테스트 @everyone", transport=httpx.MockTransport(handler)
        )
        == "987654321"
    )
    assert len(requests) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://discord.com/api/webhooks/123456/" + TEST_TOKEN,
        "https://discord.com.attacker.example/api/webhooks/123456/" + TEST_TOKEN,
        "https://127.0.0.1/api/webhooks/123456/" + TEST_TOKEN,
        "https://x@discord.com/api/webhooks/123456/" + TEST_TOKEN,
        "https://discord.com:8443/api/webhooks/123456/" + TEST_TOKEN,
        "https://discord.com/api/webhooks/123456/" + TEST_TOKEN + "?thread_id=123",
        "https://discord.com/api/webhooks/123456/" + TEST_TOKEN + "#fragment",
        "https://discord.com/api/webhooks/123456/" + TEST_TOKEN + "/slack",
    ],
)
def test_reject_untrusted_url_before_network(url):
    with pytest.raises(discord.DiscordNotificationError, match="invalid_webhook_configuration"):
        discord.send_discord(
            SecretStr(url),
            "test",
            transport=httpx.MockTransport(lambda _: pytest.fail("unsafe network request")),
        )


def test_redirect_not_followed_and_response_not_logged():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            302, headers={"Location": "https://attacker.example"}, text=TEST_TOKEN
        )

    with pytest.raises(discord.DiscordNotificationError) as caught:
        discord.send_discord(WEBHOOK, "test", transport=httpx.MockTransport(handler))
    assert len(requests) == 1
    assert str(caught.value) == "http_status_302"
    assert TEST_TOKEN not in str(caught.value)


def test_timeout_not_retried_and_secret_not_exposed():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout(str(request.url), request=request)

    with pytest.raises(discord.DiscordNotificationError) as caught:
        discord.send_discord(WEBHOOK, "test", transport=httpx.MockTransport(handler))
    assert len(requests) == 1
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert TEST_TOKEN not in str(caught.value)


@pytest.mark.parametrize("status", [204, 400, 401, 404, 429, 500])
def test_only_confirmed_success_accepted(status):
    with pytest.raises(discord.DiscordNotificationError, match=f"http_status_{status}"):
        discord.send_discord(
            WEBHOOK,
            "test",
            transport=httpx.MockTransport(lambda _: httpx.Response(status, text=TEST_TOKEN)),
        )


@pytest.mark.parametrize("body", [{}, {"id": None}, {"id": TEST_TOKEN}])
def test_missing_message_receipt_is_not_success(body):
    with pytest.raises(discord.DiscordNotificationError, match="invalid_confirmation"):
        discord.send_discord(
            WEBHOOK, "test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
        )


def test_summary_and_partial_failure_are_explicit():
    data = summary()
    content = discord.format_training_summary(data)
    assert "갱신 완료" in content
    assert "최근 7일" in content
    assert "신규 2 / 변경 1 / 유지 30" in content
    assert "2026-10-01" in content
    assert "빈 응답은 기존 기록을 삭제하지 않습니다" in content
    assert len(content) < 2000
    data["failures"] = 1
    data["results"] += [{"status": "failed"}, {"status": "not_attempted_quota"}]
    assert "일부 실패" in discord.format_training_summary(data)


def test_notification_failure_does_not_raise_or_log_token(monkeypatch):
    emit = Mock()
    monkeypatch.setattr(discord, "send_discord", Mock(side_effect=RuntimeError(TEST_TOKEN)))
    discord.notify_training(WEBHOOK, emit=emit, summary=summary())
    emit.assert_called_once_with("discord_failed", error_type="RuntimeError")
    assert TEST_TOKEN not in str(emit.call_args)


def test_missing_secret_skips_network(monkeypatch):
    monkeypatch.setattr(discord, "send_discord", lambda *_a: pytest.fail("missing opt-in"))
    emit = Mock()
    discord.notify_training(None, emit=emit, summary=summary())
    emit.assert_called_once_with("discord_skipped", reason="not_configured")


def test_secret_setting_and_environment_precedence(tmp_path, monkeypatch):
    secret_file = tmp_path / ".env.discord"
    secret_file.write_text(f"HORSE_RACING_DISCORD_WEBHOOK_URL={WEBHOOK.get_secret_value()}\n")
    settings = Settings(_env_file=secret_file)
    assert settings.discord_webhook_url.get_secret_value() == WEBHOOK.get_secret_value()
    assert TEST_TOKEN not in repr(settings.discord_webhook_url)
    monkeypatch.setenv("HORSE_RACING_DISCORD_WEBHOOK_URL", "environment-override")
    assert (
        Settings(_env_file=secret_file).discord_webhook_url.get_secret_value()
        == "environment-override"
    )


def test_worker_notifies_only_after_commit_and_dispose(monkeypatch, tmp_path):
    events = []
    settings = SimpleNamespace(
        database_url="unused",
        data_go_kr_service_key=SecretStr("test"),
        discord_webhook_url=WEBHOOK,
        raw_data_dir=tmp_path,
    )
    engine = Mock()
    lock = Mock()
    lock.scalar.return_value = True
    engine.connect.return_value.__enter__ = Mock(return_value=lock)
    engine.connect.return_value.__exit__ = Mock(return_value=False)
    engine.dispose.side_effect = lambda: events.append("disposed")
    session = Mock()
    session.commit.side_effect = lambda: events.append("committed")
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)

    def add(run):
        run.id = 7

    session.add.side_effect = add
    data = summary()
    monkeypatch.setattr(job, "get_settings", lambda: settings)
    monkeypatch.setattr(job, "require_target", lambda *_a: None)
    monkeypatch.setattr(job, "create_engine_for_url", lambda *_a: engine)
    monkeypatch.setattr(job, "Session", lambda *_a, **_k: context)
    monkeypatch.setattr(
        job,
        "collect_window",
        lambda *_a: (data["results"], data["changes"], data["latest_training_date_in_window"]),
    )
    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)

    def notify(_webhook, **kwargs):
        assert events == ["committed", "committed", "disposed"]
        assert kwargs["summary"]["run_id"] == 7
        assert kwargs["summary"]["failures"] == 0
        events.append("notified")

    monkeypatch.setattr(job, "notify_training", notify)
    assert job.execute(as_of=datetime.now(job.KST).date(), apply=True) == 0
    assert events[-1] == "notified"


def test_main_failure_notifies_once_without_exception_text(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "argv", ["daily_training", "--apply"])
    monkeypatch.setattr(job, "execute", Mock(side_effect=RuntimeError(TEST_TOKEN)))
    monkeypatch.setattr(job, "get_settings", lambda: SimpleNamespace(discord_webhook_url=WEBHOOK))
    notify = Mock()
    monkeypatch.setattr(job, "notify_training", notify)
    with pytest.raises(SystemExit) as caught:
        job.main()
    assert caught.value.code == 1
    notify.assert_called_once_with(WEBHOOK, emit=job.emit, failure_type="RuntimeError")


@pytest.mark.parametrize("status", ["completed", "unchanged", "no_published_plan", "failed"])
def test_weekly_notification_statuses_are_explicit(monkeypatch, status):
    sender = Mock(return_value="987654321")
    monkeypatch.setattr(discord, "send_discord", sender)
    discord.notify_weekly(
        WEBHOOK,
        emit=Mock(),
        summary={
            "status": status,
            "run_id": 7,
            "races": 67,
            "runners": 700,
            "api_pages": 40,
            "window_start": "2026-10-02",
            "window_end": "2026-10-06",
            "error_type": "RuntimeError",
        },
    )
    content = sender.call_args.args[1]
    assert "주간 출마표" in content
    assert len(content) <= 2000
    if status == "unchanged":
        assert "변경 없음" in content and "건너뛰었습니다" in content
    if status == "no_published_plan":
        assert "미공개와 비경마일은 단정하지 않습니다" in content


def test_weekly_notification_failure_is_nonfatal(monkeypatch):
    monkeypatch.setattr(discord, "send_discord", Mock(side_effect=RuntimeError(TEST_TOKEN)))
    emit = Mock()
    discord.notify_weekly(WEBHOOK, emit=emit, summary={"status": "failed"})
    emit.assert_called_once_with("discord_failed", error_type="RuntimeError")

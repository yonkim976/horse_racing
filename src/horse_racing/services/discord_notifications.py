"""Opt-in Discord notifications; no database writes or automatic retries.

Configure HORSE_RACING_DISCORD_WEBHOOK_URL through a secret environment variable.
Local development may use the ignored .env.discord file instead.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr

KINDS = {"daily": "일반조교", "starting": "출발조교", "swimming": "수영조교", "hill": "언덕조교"}


class DiscordNotificationError(RuntimeError):
    """Sanitized error: never includes a webhook URL or a response body."""


def _validate_webhook(url: str) -> None:
    try:
        parts = urlsplit(url)
        valid = (
            parts.scheme == "https"
            and parts.netloc in {"discord.com", "discord.com:443"}
            and parts.port in {None, 443}
            and not parts.query
            and not parts.fragment
            and re.fullmatch(r"/api/webhooks/[0-9]+/[A-Za-z0-9_-]{20,}", parts.path)
        )
    except ValueError:
        valid = False
    if not valid:
        raise DiscordNotificationError("invalid_webhook_configuration") from None


def send_discord(
    webhook: SecretStr,
    content: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Send once and require confirmation; reject redirects and sanitize errors.

    Do not retry ambiguous transport failures: Discord may already have saved the message.
    """
    url = webhook.get_secret_value()
    _validate_webhook(url)
    if not content or len(content) > 2000:
        raise DiscordNotificationError("invalid_message_length")
    try:
        with httpx.Client(timeout=15, follow_redirects=False, transport=transport) as client:
            response = client.post(
                url,
                params={"wait": "true"},
                json={"content": content, "allowed_mentions": {"parse": []}},
            )
    except httpx.HTTPError:
        raise DiscordNotificationError("transport_error_delivery_unknown") from None
    if response.status_code != 200:
        raise DiscordNotificationError(f"http_status_{response.status_code}")
    try:
        message_id = response.json()["id"]
    except (ValueError, KeyError, TypeError):
        raise DiscordNotificationError("invalid_confirmation_delivery_unknown") from None
    if not isinstance(message_id, str) or not message_id.isdigit():
        raise DiscordNotificationError("invalid_confirmation_delivery_unknown")
    return message_id


def format_training_summary(summary: dict) -> str:
    """Select safe aggregate fields only; never forward exception text or API payloads."""
    failures = int(summary["failures"])
    results = summary["results"]
    skipped = sum(row["status"] == "not_attempted_quota" for row in results)
    empty = sum(row["status"] == "observed_empty" for row in results)
    completed = sum(row["status"] in {"completed", "observed_empty"} for row in results)
    now = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")
    lines = [
        f"[경마 DB] 조교 갱신 {'일부 실패' if failures or skipped else '완료'}",
        f"실행 시각: {now}",
        f"조회 범위: {summary['window_start']} ~ {summary['window_end']} (최근 7일)",
        f"대상: Supabase / 실행 ID: {int(summary['run_id'])}",
        f"작업: 완료 {completed} · 실패 {failures} · 할당량 중단 {skipped} · 빈 응답 {empty}",
    ]
    for kind, label in KINDS.items():
        diff = summary["changes"][kind]
        latest = summary["latest_training_date_in_window"][kind] or "자료 없음"
        lines.append(
            f"{label}: 신규 {int(diff['new'])} / 변경 {int(diff['changed'])} / "
            f"유지 {int(diff['unchanged'])} / 최신 스냅샷 제외 "
            f"{int(diff['removed_from_latest_snapshot'])} · 범위 내 최신일 {latest}"
        )
    lines += [
        f"소요: {float(summary['elapsed_seconds']):.1f}초",
        "빈 응답은 기존 기록을 삭제하지 않습니다. "
        "신규·변경은 업무 기록 기준이며 원문 이력은 별도입니다.",
        "DB 저장 후 알림입니다. 예측 실행·배포는 포함하지 않습니다.",
    ]
    return "\n".join(lines)


def notify_training(
    webhook: SecretStr | None,
    *,
    emit: Callable,
    summary: dict | None = None,
    failure_type: str | None = None,
) -> None:
    """Best-effort notification independent of the ingestion result/exit status."""
    if webhook is None:
        emit("discord_skipped", reason="not_configured")
        return
    try:
        if summary is not None:
            content = format_training_summary(summary)
        else:
            # Do not send arbitrary exception messages; an exception class name is sufficient.
            safe_type = re.sub(r"[^A-Za-z0-9_]", "", failure_type or "UnknownError")[:80]
            content = (
                "[경마 DB] 조교 갱신 실패\n"
                f"오류 종류: {safe_type}\n"
                "성공 요약을 만들지 못했습니다. 일부 저장 여부는 실행 로그와 DB를 확인하세요.\n"
                "알림 전송으로 수집이나 DB 쓰기를 재실행하지 않습니다."
            )
        message_id = send_discord(webhook, content)
        emit("discord_sent", message_id=message_id)
    except Exception as exc:
        # Never log exc/request/response/URL: even transport exceptions contain the token.
        emit("discord_failed", error_type=type(exc).__name__)


def notify_weekly(webhook: SecretStr | None, *, emit: Callable, summary: dict) -> None:
    """Notify a committed weekly result, verified no-change result, or sanitized failure."""
    if webhook is None:
        emit("discord_skipped", reason="not_configured")
        return
    try:
        labels = {
            "completed": "갱신 완료",
            "unchanged": "검증 완료 · 변경 없음",
            "no_published_plan": "공개 계획 없음",
            "failed": "갱신 실패",
        }
        status = summary["status"]
        content = [
            f"[경마 DB] 주간 출마표 {labels[status]}",
            "실행 시각: " + datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST"),
        ]
        if "window_start" in summary:
            content.append(f"조회 범위: {summary['window_start']} ~ {summary['window_end']}")
        if status in {"completed", "unchanged"}:
            content.append(
                f"공식 자료 대조: {int(summary['races'])}경주 · {int(summary['runners'])}두 "
                f"· API 응답 {int(summary['api_pages'])}페이지"
            )
            content.append(f"실행 ID: {int(summary['run_id'])}")
            content.append(
                "같은 입력·저장값을 확인해 DB 적재를 건너뛰었습니다."
                if status == "unchanged"
                else "검증 후 Supabase에 저장했습니다."
            )
        elif status == "no_published_plan":
            content.append(
                "조회 API에 공개 계획이 없습니다. 미공개와 비경마일은 단정하지 않습니다."
            )
        else:
            safe_type = re.sub(r"[^A-Za-z0-9_]", "", summary.get("error_type", "UnknownError"))[:80]
            content += [
                f"오류 종류: {safe_type}",
                "일부 저장 여부는 로그·DB를 확인하세요. 알림 때문에 수집을 재실행하지 않습니다.",
            ]
        content.append("당일 변경·결과·예측 수집은 이 작업에 포함하지 않습니다.")
        message_id = send_discord(webhook, "\n".join(content))
        emit("discord_sent", message_id=message_id)
    except Exception as exc:
        emit("discord_failed", error_type=type(exc).__name__)

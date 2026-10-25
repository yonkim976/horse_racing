"""Retry only recent startup-connection failures / definitely unsent local alerts.

No work when healthy. Not a new general collector or a model scheduler.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import socket
from datetime import date, datetime, timedelta

from sqlalchemy.engine import make_url

from horse_racing.config import Settings
from horse_racing.jobs import local_catalog as catalog
from horse_racing.jobs import local_post_race as post
from horse_racing.jobs import local_race_day as live
from horse_racing.jobs.local_log_rotation import open_regular
from horse_racing.services.discord_notifications import notification_failure

LABEL = "com.horse-racing.local-recovery"
CACHE_PATH = live.ROOT / "data/state/local-recovery.json"


def candidates(kind, state, now):
    failure = state if kind == "canonical" else state.get("last_failure", {})
    if failure.get("status") == "failed" or (kind == "repair" and failure):
        try:
            observed = datetime.fromisoformat(failure["observed_at"])
            age = now - observed
        except (KeyError, ValueError, TypeError):
            return []
        if (
            timedelta(0) <= age <= timedelta(hours=24)
            and failure.get("failure_phase") == "connect"
            and failure.get("error_type") == "OperationalError"
            and failure.get("error_reason") not in {"authentication", "tls"}
            and not str(failure.get("sqlstate", "")).startswith("28")
            and (
                not failure.get("sqlstate")
                or str(failure["sqlstate"]).startswith("08")
                or failure["sqlstate"] in {"53300", "57P03"}
            )
        ):
            return [
                {
                    "action": "collect",
                    "key": f"{kind}:{observed.date()}",
                    "through": failure.get("through", str(observed.date())),
                }
            ]
    notification = state.get("notification", {})
    if notification.get("status") == "failed" and notification.get("retryable") is True:
        summary = (
            state
            if kind == "canonical"
            else (
                state.get("last_notification_summary")
                if state.get("last_failure")
                else state.get("last_summary")
            )
        )
        if summary:
            # Only these two local, recent summaries are eligible; never replay unknown delivery.
            day = summary.get("end") or str(summary.get("observed_at", ""))[:10]
            try:
                age = now.date() - date.fromisoformat(day)
            except (ValueError, TypeError):
                return []
            if timedelta(0) <= age <= timedelta(days=1):
                return [
                    {
                        "action": "notify",
                        "key": f"notify:{kind}:{day}:{summary.get('run_id')}",
                        "summary": summary,
                    }
                ]
    return []


def due(cache, candidate, now):
    item = cache.get(candidate["key"], {})
    if item.get("attempts", 0) >= 3:
        return False
    return now.timestamp() >= item.get("next_at", 0)


def network_ready(action):
    """Do not burn the catch-up attempts during offline/DarkWake ticks."""
    try:
        if action == "collect":
            url = make_url(live.load_settings().database_url)  # Validates the fixed project host.
            address = (url.host, url.port or 5432)
        else:
            address = ("discord.com", 443)
        with socket.create_connection(address, timeout=3):
            return True
    except Exception as exc:
        catalog.cards.emit("local_recovery_waiting_for_network", error_type=type(exc).__name__)
        return False


def retry_notification(kind, path, now):
    # Serialize with ordinary workers so an old alert cannot overwrite a newer result.
    with os.fdopen(
        open_regular(live.STATE_PATH.with_suffix(".lock"), os.O_CREAT | os.O_RDWR), "a"
    ) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        state = live.read_state(path)
        pending = candidates(kind, state, now)
        if not pending or pending[0]["action"] != "notify":
            return
        settings = Settings(_env_file=(live.ROOT / ".env", live.ROOT / ".env.discord"))
        state["notification"] = {"status": "sending"}
        live.write_state(path, state)
        try:
            state["notification"] = (
                catalog.notify(settings, "canonical", pending[0]["summary"])
                if kind == "canonical"
                else post.notify(settings, pending[0]["summary"], scheduled=False)
            )
        except Exception as exc:
            state["notification"] = {"status": "failed", **notification_failure(exc)}
        live.write_state(path, state)


def execute(*, apply=False, now=None):
    now = now or datetime.now(catalog.cards.KST)
    if not apply:
        return 0  # No state, secret, filesystem or network access.
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(
        open_regular(CACHE_PATH.with_suffix(".lock"), os.O_CREAT | os.O_RDWR), "a"
    ) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 75
        cache = live.read_state(CACHE_PATH)
        cache = {
            k: v for k, v in cache.items() if now.timestamp() - v.get("updated_at", 0) < 7 * 86400
        }
        for kind, path in (
            ("canonical", live.ROOT / "data/state/local-catalog-canonical.json"),
            ("repair", post.REPAIR_STATUS_PATH),
        ):
            state = live.read_state(path)
            for candidate in candidates(kind, state, now):
                if not due(cache, candidate, now):
                    continue
                if not network_ready(candidate["action"]):
                    continue
                count = cache.get(candidate["key"], {}).get("attempts", 0) + 1
                cache[candidate["key"]] = {
                    "attempts": count,
                    "updated_at": now.timestamp(),
                    "next_at": now.timestamp() + (300, 1200, 3600)[count - 1],
                }
                live.write_state(CACHE_PATH, cache)  # Count before action, including crashes.
                catalog.cards.emit(
                    "local_recovery_attempt", kind=kind, action=candidate["action"], attempt=count
                )
                if candidate["action"] == "notify":
                    retry_notification(kind, path, now)
                elif kind == "canonical":
                    catalog.execute(mode="canonical", apply=True)
                else:
                    post.execute(
                        mode="repair", apply=True, through=date.fromisoformat(candidate["through"])
                    )
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    raise SystemExit(execute(**vars(parser.parse_args())))


if __name__ == "__main__":
    main()

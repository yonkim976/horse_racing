from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class SyncWindow:
    as_of: date
    schedule_dates: list[date]
    result_start: date
    result_end: date


@dataclass(frozen=True, slots=True)
class LatestSyncWindow:
    """통합 최신화에서 원천 성격별로 사용하는 날짜 창."""

    as_of: date
    schedule_dates: list[date]
    recent_start: date
    recent_end: date
    history_start: date
    history_end: date
    trial_start: date
    trial_end: date


def compute_sync_window(
    as_of: date,
    *,
    schedule_days: int = 3,
    result_lookback_days: int = 1,
) -> SyncWindow:
    if schedule_days < 1:
        raise ValueError("schedule_days는 1 이상이어야 합니다.")
    if result_lookback_days < 0:
        raise ValueError("result_lookback_days는 0 이상이어야 합니다.")

    schedule_dates = [as_of + timedelta(days=offset) for offset in range(schedule_days)]
    return SyncWindow(
        as_of=as_of,
        schedule_dates=schedule_dates,
        result_start=as_of - timedelta(days=result_lookback_days),
        result_end=as_of,
    )


def compute_latest_sync_window(
    as_of: date,
    *,
    schedule_days: int = 7,
    recent_lookback_days: int = 7,
    history_lookback_days: int = 14,
    trial_lookback_days: int = 14,
) -> LatestSyncWindow:
    """일정·결과·말 상태·주행심사에 맞춘 통합 최신화 범위를 계산한다."""
    if schedule_days < 1:
        raise ValueError("schedule_days는 1 이상이어야 합니다.")
    for name, value in (
        ("recent_lookback_days", recent_lookback_days),
        ("history_lookback_days", history_lookback_days),
        ("trial_lookback_days", trial_lookback_days),
    ):
        if value < 0:
            raise ValueError(f"{name}는 0 이상이어야 합니다.")

    return LatestSyncWindow(
        as_of=as_of,
        schedule_dates=[as_of + timedelta(days=offset) for offset in range(schedule_days)],
        recent_start=as_of - timedelta(days=recent_lookback_days),
        recent_end=as_of,
        history_start=as_of - timedelta(days=history_lookback_days),
        history_end=as_of,
        trial_start=as_of - timedelta(days=trial_lookback_days),
        trial_end=as_of,
    )


def format_yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")

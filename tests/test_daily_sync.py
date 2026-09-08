from datetime import date

import pytest

from horse_racing.cli import sync_daily, sync_latest
from horse_racing.services.daily_sync import (
    compute_latest_sync_window,
    compute_sync_window,
    format_yyyymmdd,
)


def test_compute_sync_window_defaults() -> None:
    window = compute_sync_window(date(2026, 8, 23))

    assert window.as_of == date(2026, 8, 23)
    assert window.schedule_dates == [
        date(2026, 8, 23),
        date(2026, 8, 24),
        date(2026, 8, 25),
    ]
    assert window.result_start == date(2026, 8, 22)
    assert window.result_end == date(2026, 8, 23)
    assert format_yyyymmdd(window.result_start) == "20260822"


def test_compute_sync_window_rejects_invalid_ranges() -> None:
    with pytest.raises(ValueError):
        compute_sync_window(date(2026, 8, 23), schedule_days=0)
    with pytest.raises(ValueError):
        compute_sync_window(date(2026, 8, 23), result_lookback_days=-1)


def test_compute_latest_sync_window_uses_source_specific_ranges() -> None:
    window = compute_latest_sync_window(date(2026, 8, 27))

    assert window.schedule_dates[0] == date(2026, 8, 27)
    assert window.schedule_dates[-1] == date(2026, 9, 2)
    assert window.recent_start == date(2026, 8, 20)
    assert window.history_start == date(2026, 8, 13)
    assert window.trial_start == date(2026, 8, 13)


def test_sync_daily_dry_run_prints_plan(capsys: pytest.CaptureFixture[str]) -> None:
    code = sync_daily(
        "all",
        as_of="20260823",
        meets=[1, 2, 3],
        schedule_days=3,
        result_lookback_days=1,
        page_size=1000,
        include_dividends=True,
        dry_run=True,
    )

    captured = capsys.readouterr().out
    assert code == 0
    assert "mode=all, as_of=20260823" in captured
    assert "일정·출전표·출발번호 수집 대상: 20260823 20260824 20260825" in captured
    assert "결과 수집 기간: 20260822~20260823" in captured
    assert "dry-run" in captured


def test_sync_latest_dry_run_prints_every_refresh_window(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = sync_latest(
        as_of="20260827",
        meets=[1, 2, 3],
        schedule_days=7,
        recent_lookback_days=7,
        history_lookback_days=14,
        trial_lookback_days=14,
        page_size=1000,
        include_dividends=True,
        dry_run=True,
    )

    captured = capsys.readouterr().out
    assert code == 0
    assert "통합 최신화 계획: as_of=20260827" in captured
    assert "결과·구간: 20260820~20260827" in captured
    assert "말 상태: 20260813~20260827" in captured
    assert "주행심사: 20260813~20260827" in captured
    assert "레이팅·현역 말 프로필·등급변동" in captured

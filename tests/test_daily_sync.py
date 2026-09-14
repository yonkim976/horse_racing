from datetime import date

import pytest

from horse_racing import cli
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


@pytest.mark.parametrize("command", ["sync-daily", "sync-latest"])
def test_refresh_defaults_include_yeongcheon(monkeypatch, command) -> None:
    received = {}

    def capture(*args, **kwargs):
        received.update(kwargs)
        return 0

    monkeypatch.setattr("sys.argv", ["horse-racing", command, "--dry-run"])
    monkeypatch.setattr(cli, command.replace("-", "_"), capture)
    assert cli.main() == 0
    assert received["meets"] == [1, 2, 3, 4]


def test_yeongcheon_sections_use_verified_cumulative_fields() -> None:
    from horse_racing.parsers.race_section import RaceResultSectionItem, parse_section_values

    item = RaceResultSectionItem.model_validate({
        "rcDate": 20260913, "rcNo": 1, "rcDist": 1800,
        "chulNo": 7, "hrNo": "0053366", "hrName": "모멘텀", "meet": "영천",
        "buS1fAccTime": 14.1, "buS1fOrd": 4,
        "buG3fAccTime": 75.8, "buG3fOrd": 3,
        "buG1fAccTime": 101, "buG1fOrd": 2,
        "buG8fAccTime": 0, "buG8fOrd": 0,
    })
    values = {s.section_code: s for s in parse_section_values(item, 4)}
    assert values["G3F"].elapsed_time_ms == 75800
    assert values["G1F"].elapsed_time_ms == 101000
    assert values["S1F"].position == 4
    assert all(s.time_basis == "cumulative" for s in values.values())
    assert "G8F" not in values


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

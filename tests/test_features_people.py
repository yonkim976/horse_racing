from datetime import date, timedelta

import polars as pl

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.people import FEATURES, add_features

TARGET_DATE = date(2026, 8, 22)
FEATURE_NAMES = [spec.name for spec in FEATURES]


def _frame(**overrides: object) -> pl.DataFrame:
    row = {
        "race_id": 100,
        "race_entry_id": 1000,
        "horse_id": 1,
        "jockey_id": 10,
        "trainer_id": 20,
        "meet_code": 1,
        "race_date": TARGET_DATE,
        "race_number": 5,
        "starters": 8,
        "finish_position": 1,
        "win": 1,
    }
    row.update(overrides)
    return pl.DataFrame(
        row,
        schema_overrides={"jockey_id": pl.Int64, "trainer_id": pl.Int64},
    )


def _past(
    *,
    race_entry_id: int,
    race_id: int,
    race_date: date,
    horse_id: int = 99,
    jockey_id: int | None = 10,
    trainer_id: int | None = 20,
    finish_position: int = 5,
    starters: int = 10,
) -> dict[str, object]:
    return {
        "horse_id": horse_id,
        "jockey_id": jockey_id,
        "trainer_id": trainer_id,
        "race_entry_id": race_entry_id,
        "race_id": race_id,
        "meet_code": 1,
        "race_date": race_date,
        "finish_position": finish_position,
        "starters": starters,
    }


def _sources(
    past_rows: list[dict[str, object]] | None = None,
    change_rows: list[dict[str, object]] | None = None,
) -> SourceFrames:
    return SourceFrames(
        past_results=pl.DataFrame(past_rows) if past_rows else pl.DataFrame(),
        jockey_changes=pl.DataFrame(change_rows) if change_rows else pl.DataFrame(),
    )


def test_feature_specs_registered() -> None:
    assert FEATURE_NAMES == [
        "jockey_starts_90d",
        "jockey_starts_365d",
        "jockey_win_rate_90d",
        "jockey_win_rate_365d",
        "jockey_top3_rate_90d",
        "trainer_starts_90d",
        "trainer_starts_365d",
        "trainer_win_rate_90d",
        "trainer_win_rate_365d",
        "trainer_top3_rate_90d",
        "horse_jockey_starts",
        "horse_jockey_wins",
        "horse_jockey_first",
        "jockey_changed",
    ]
    changed = next(spec for spec in FEATURES if spec.name == "jockey_changed")
    assert "공지는 경주 전 공개" in changed.leakage_note
    assert "observed_at은 수집시각이라 사용 안 함(T3)" in changed.leakage_note


def test_same_day_and_future_races_excluded() -> None:
    past = [
        _past(race_entry_id=1, race_id=1, race_date=TARGET_DATE, finish_position=1),
        _past(
            race_entry_id=2,
            race_id=2,
            race_date=TARGET_DATE + timedelta(days=1),
            finish_position=1,
        ),
        _past(
            race_entry_id=3,
            race_id=3,
            race_date=TARGET_DATE - timedelta(days=10),
            finish_position=4,
        ),
    ]
    result = add_features(_frame(), _sources(past))
    row = result.row(0, named=True)
    assert row["jockey_starts_90d"] == 1
    assert row["jockey_starts_365d"] == 1
    assert row["jockey_win_rate_90d"] == 0.0
    assert row["jockey_top3_rate_90d"] == 0.0
    assert row["trainer_starts_90d"] == 1
    assert row["trainer_win_rate_90d"] == 0.0


def test_window_boundaries_90_and_365() -> None:
    past = [
        _past(
            race_entry_id=1,
            race_id=1,
            race_date=TARGET_DATE - timedelta(days=90),
            finish_position=1,
        ),
        _past(
            race_entry_id=2,
            race_id=2,
            race_date=TARGET_DATE - timedelta(days=91),
            finish_position=1,
        ),
        _past(
            race_entry_id=3,
            race_id=3,
            race_date=TARGET_DATE - timedelta(days=365),
            finish_position=1,
        ),
        _past(
            race_entry_id=4,
            race_id=4,
            race_date=TARGET_DATE - timedelta(days=366),
            finish_position=1,
        ),
    ]
    result = add_features(_frame(), _sources(past))
    row = result.row(0, named=True)
    assert row["jockey_starts_90d"] == 1
    assert row["jockey_starts_365d"] == 3
    assert row["jockey_win_rate_90d"] == 1.0
    assert row["jockey_win_rate_365d"] == 1.0
    assert row["trainer_starts_90d"] == 1
    assert row["trainer_starts_365d"] == 3


def test_win_rate_and_zero_starts_are_null() -> None:
    frame = pl.concat(
        [
            _frame(),
            _frame(race_id=101, race_entry_id=1001, horse_id=2, jockey_id=11, trainer_id=21),
        ]
    )
    past = [
        _past(
            race_entry_id=1,
            race_id=1,
            race_date=TARGET_DATE - timedelta(days=5),
            finish_position=1,
        ),
        _past(
            race_entry_id=2,
            race_id=2,
            race_date=TARGET_DATE - timedelta(days=15),
            finish_position=4,
        ),
        _past(
            race_entry_id=3,
            race_id=3,
            race_date=TARGET_DATE - timedelta(days=20),
            finish_position=2,
        ),
    ]
    result = add_features(frame, _sources(past)).sort("race_entry_id")
    with_history = result.row(0, named=True)
    without_history = result.row(1, named=True)

    assert with_history["jockey_starts_90d"] == 3
    assert with_history["jockey_win_rate_90d"] == 1 / 3
    assert with_history["jockey_top3_rate_90d"] == 2 / 3
    assert with_history["trainer_win_rate_90d"] == 1 / 3
    assert with_history["trainer_top3_rate_90d"] == 2 / 3

    assert without_history["jockey_starts_90d"] == 0
    assert without_history["jockey_starts_365d"] == 0
    assert without_history["jockey_win_rate_90d"] is None
    assert without_history["jockey_win_rate_365d"] is None
    assert without_history["jockey_top3_rate_90d"] is None
    assert without_history["trainer_starts_90d"] == 0
    assert without_history["trainer_win_rate_90d"] is None
    assert without_history["trainer_top3_rate_90d"] is None


def test_combo_cumcount_excludes_current_race() -> None:
    past = [
        _past(
            race_entry_id=50,
            race_id=50,
            race_date=TARGET_DATE - timedelta(days=200),
            horse_id=1,
            jockey_id=10,
            finish_position=1,
        ),
        _past(
            race_entry_id=51,
            race_id=51,
            race_date=TARGET_DATE - timedelta(days=40),
            horse_id=1,
            jockey_id=10,
            finish_position=2,
        ),
        _past(
            race_entry_id=1000,
            race_id=100,
            race_date=TARGET_DATE,
            horse_id=1,
            jockey_id=10,
            finish_position=1,
        ),
        _past(
            race_entry_id=1001,
            race_id=101,
            race_date=TARGET_DATE,
            horse_id=2,
            jockey_id=10,
            finish_position=3,
        ),
    ]
    frame = pl.concat(
        [
            _frame(),
            _frame(race_id=101, race_entry_id=1001, horse_id=2, win=0, finish_position=3),
        ]
    )
    result = add_features(frame, _sources(past)).sort("race_entry_id")
    known = result.row(0, named=True)
    first = result.row(1, named=True)

    assert known["horse_jockey_starts"] == 2
    assert known["horse_jockey_wins"] == 1
    assert known["horse_jockey_first"] == 0
    assert first["horse_jockey_starts"] == 0
    assert first["horse_jockey_wins"] == 0
    assert first["horse_jockey_first"] == 1


def test_null_jockey_and_trainer_ids_yield_null_features() -> None:
    frame = pl.concat(
        [
            _frame(jockey_id=None, trainer_id=20, race_entry_id=1000),
            _frame(jockey_id=10, trainer_id=None, race_entry_id=1001, horse_id=2),
            _frame(jockey_id=None, trainer_id=None, race_entry_id=1002, horse_id=3),
        ]
    )
    past = [
        _past(
            race_entry_id=1,
            race_id=1,
            race_date=TARGET_DATE - timedelta(days=7),
            finish_position=1,
        ),
        _past(
            race_entry_id=1000,
            race_id=100,
            race_date=TARGET_DATE,
            horse_id=1,
            jockey_id=10,
            trainer_id=20,
            finish_position=1,
        ),
    ]
    result = add_features(frame, _sources(past)).sort("race_entry_id")
    no_jockey = result.row(0, named=True)
    no_trainer = result.row(1, named=True)
    neither = result.row(2, named=True)

    assert no_jockey["jockey_starts_90d"] is None
    assert no_jockey["jockey_starts_365d"] is None
    assert no_jockey["jockey_win_rate_90d"] is None
    assert no_jockey["jockey_win_rate_365d"] is None
    assert no_jockey["jockey_top3_rate_90d"] is None
    assert no_jockey["horse_jockey_starts"] is None
    assert no_jockey["horse_jockey_wins"] is None
    assert no_jockey["horse_jockey_first"] is None
    assert no_jockey["trainer_starts_90d"] == 1
    assert no_jockey["trainer_win_rate_90d"] == 1.0

    assert no_trainer["jockey_starts_90d"] == 1
    assert no_trainer["jockey_win_rate_90d"] == 1.0
    assert no_trainer["trainer_starts_90d"] is None
    assert no_trainer["trainer_starts_365d"] is None
    assert no_trainer["trainer_win_rate_90d"] is None
    assert no_trainer["trainer_win_rate_365d"] is None
    assert no_trainer["trainer_top3_rate_90d"] is None

    assert neither["jockey_starts_90d"] is None
    assert neither["trainer_starts_90d"] is None
    assert neither["horse_jockey_first"] is None


def test_jockey_changed_matches_horse_date_number_without_observed_at() -> None:
    changes = [
        {
            "horse_id": 1,
            "race_date": TARGET_DATE,
            "race_number": 5,
            "observed_at_ms": 9_999_999_999_999,
        },
        {
            "horse_id": 2,
            "race_date": TARGET_DATE,
            "race_number": 99,
            "observed_at_ms": 1,
        },
    ]
    frame = pl.concat(
        [
            _frame(),
            _frame(race_id=101, race_entry_id=1001, horse_id=2, race_number=1),
        ]
    )
    result = add_features(frame, _sources(change_rows=changes)).sort("race_entry_id")
    assert result.get_column("jockey_changed").to_list() == [1, 0]
    for name in FEATURE_NAMES:
        assert name in result.columns

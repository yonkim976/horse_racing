import sqlite3
from datetime import date, datetime
from pathlib import Path

import polars as pl

from horse_racing.analysis.jeju_native_top3_states import build_states


def _entries(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows).with_columns(pl.col("event_date").cast(pl.Date))


def _history(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows).with_columns(pl.col("event_date").cast(pl.Date))


def _entry(entry_id: int, race_id: int, horse_id: str, day: date, distance: int = 1000) -> dict:
    return {
        "entry_id": entry_id,
        "race_id": race_id,
        "horse_id": horse_id,
        "event_date": day,
        "distance_m": distance,
        "field_size": 2,
        "cutoff_at": datetime.combine(day, datetime.min.time()),
    }


def _result(
    entry_id: int,
    race_id: int,
    horse_id: str,
    day: date,
    position: int,
    distance: int = 1000,
    quality: str = "usable",
) -> dict:
    return {
        "entry_id": entry_id,
        "race_id": race_id,
        "horse_id": horse_id,
        "event_date": day,
        "distance_m": distance,
        "finish_position": position,
        "finish_time_ms": 100_000,
        "segment_quality": quality,
    }


def test_same_day_and_previous_day_results_are_excluded() -> None:
    target = _entries([_entry(20, 20, "0000001", date(2024, 1, 10))])
    history = _history(
        [
            _result(1, 1, "0000001", date(2024, 1, 7), 1),
            _result(2, 2, "0000001", date(2024, 1, 9), 1),
            _result(3, 3, "0000001", date(2024, 1, 10), 1),
        ]
    )
    states, _ = build_states(Path("/tmp/missing-jeju-state-db.sqlite3"), target, history)
    row = states.row(0, named=True)
    assert row["normal_completed_pre"] == 1
    assert row["days_since_previous_start"] == 3


def test_future_history_edit_does_not_change_fixed_target_state() -> None:
    target = _entries([_entry(20, 20, "0000001", date(2024, 1, 10))])
    before = _history([_result(1, 1, "0000001", date(2024, 1, 7), 1)])
    after = before.vstack(_history([_result(2, 2, "0000001", date(2024, 1, 20), 1)]))
    one, _ = build_states(Path("/tmp/missing-jeju-state-db.sqlite3"), target, before)
    two, _ = build_states(Path("/tmp/missing-jeju-state-db.sqlite3"), target, after)
    assert one.select(
        "global_elo_pre", "normal_completed_pre", "speed_time_per_100m_mean_pre"
    ).equals(two.select("global_elo_pre", "normal_completed_pre", "speed_time_per_100m_mean_pre"))


def test_dq_dnf_count_as_starts_but_not_normal_ability() -> None:
    target = _entries([_entry(20, 20, "0000001", date(2024, 1, 10))])
    history = _history(
        [
            _result(1, 1, "0000001", date(2024, 1, 1), 91),
            _result(2, 2, "0000001", date(2024, 1, 2), 92),
            _result(3, 3, "0000001", date(2024, 1, 3), 1),
        ]
    )
    states, _ = build_states(Path("/tmp/missing-jeju-state-db.sqlite3"), target, history)
    row = states.row(0, named=True)
    assert row["starts_pre"] == 3
    assert row["normal_completed_pre"] == 1
    assert row["wins_pre"] == 1


def test_target_400m_is_excluded_but_history_400m_is_retained_separately() -> None:
    targets = _entries(
        [
            _entry(20, 20, "0000001", date(2024, 1, 10), 1000),
            _entry(21, 21, "0000001", date(2024, 1, 10), 400),
        ]
    )
    history = _history([_result(1, 1, "0000001", date(2024, 1, 1), 1, 400)])
    states, metadata = build_states(Path("/tmp/missing-jeju-state-db.sqlite3"), targets, history)
    row = states.row(0, named=True)
    assert states.height == 1
    assert metadata["target_400m_excluded"] == 1
    assert metadata["history_400m_retained_separate"] is True
    assert row["starts_pre"] == 0


def test_output_is_invariant_to_input_row_order() -> None:
    targets = _entries(
        [
            _entry(20, 20, "0000001", date(2024, 1, 10)),
            _entry(21, 21, "0000002", date(2024, 1, 10)),
        ]
    )
    history = _history(
        [
            _result(1, 1, "0000001", date(2024, 1, 1), 1),
            _result(2, 1, "0000002", date(2024, 1, 1), 2),
        ]
    )
    one, _ = build_states(Path("/tmp/missing-jeju-state-db.sqlite3"), targets, history)
    two, _ = build_states(
        Path("/tmp/missing-jeju-state-db.sqlite3"), targets.reverse(), history.reverse()
    )
    assert one.sort("entry_id").equals(two.sort("entry_id"))


def test_h2_source_index_and_coverage_flags(tmp_path: Path) -> None:
    database = tmp_path / "h2.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE daily_training_record (
            id INTEGER, source_row_id INTEGER, hr_no TEXT, event_date TEXT,
            training_duration_seconds INTEGER, canter_count INTEGER,
            gallop_count INTEGER, meet INTEGER
        );
        CREATE TABLE analysis_start_training_distinct (
            id INTEGER, source_row_id INTEGER, hr_no TEXT, event_date TEXT,
            meet INTEGER
        );
        CREATE TABLE analysis_medical_distinct (
            id INTEGER, source_row_id INTEGER, hr_no TEXT, event_date TEXT,
            meet INTEGER
        );
        CREATE TABLE analysis_measured_weight (
            id INTEGER, source_row_id INTEGER, hr_no TEXT, event_date TEXT,
            event_number INTEGER, body_weight_kg INTEGER, meet INTEGER
        );
        CREATE TABLE event (id INTEGER, event_type TEXT, event_date TEXT, event_number INTEGER);
        CREATE TABLE entry (
            id INTEGER, event_id INTEGER, hr_no TEXT, finish_position INTEGER,
            finish_time_ms INTEGER, segment_quality TEXT, identity_status TEXT
        );
        INSERT INTO daily_training_record VALUES (1,11,'0000001','20240130',60,2,1,2);
        INSERT INTO analysis_start_training_distinct VALUES (2,12,'0000001','20240130',2);
        INSERT INTO analysis_medical_distinct VALUES (3,13,'0000001','20240130',2);
        INSERT INTO analysis_measured_weight VALUES (4,14,'0000001','20240130',1,480,2);
        INSERT INTO event VALUES (5,'trial','20240130',1);
        INSERT INTO entry VALUES (6,5,'0000001',2,50000,'usable','official_trial_hr_tr_linked');
        """
    )
    connection.commit()
    connection.close()
    target = _entries([_entry(20, 20, "0000001", date(2024, 2, 1))])
    states, _ = build_states(
        database,
        target,
        pl.DataFrame(
            {
                "entry_id": [],
                "race_id": [],
                "horse_id": [],
                "event_date": [],
                "distance_m": [],
                "finish_position": [],
                "finish_time_ms": [],
                "segment_quality": [],
            }
        ).with_columns(pl.col("event_date").cast(pl.Date)),
    )
    row = states.row(0, named=True)
    assert row["training_28d_count"] == 1
    assert row["training_28d_observed_any"] == 1
    assert row["training_28d_coverage_unknown"] == 1
    assert row["trial_count_pre"] == 1
    assert row["trial_last_valid_time_ms_pre"] == 50_000


def test_210m_start_section_is_kept_separate_from_200m_measurement() -> None:
    target = _entries([_entry(20, 20, "0000001", date(2024, 1, 10), 1110)])
    row = _result(1, 1, "0000001", date(2024, 1, 1), 1, 1110)
    row["section_s1f210_ms"] = 17500
    history = _history([row])
    states, _ = build_states(Path("/tmp/missing-jeju-state-db.sqlite3"), target, history)
    assert states["section_s1f210_ms_mean_pre"].item() == 17500
    assert states["section_s1f_ms_mean_pre"].item() is None

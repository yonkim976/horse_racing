from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from horse_racing.web.analysis_archive import load_verified_archive


def _archive(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript("""
      CREATE TABLE event (
        id INTEGER PRIMARY KEY,event_type TEXT,meet INTEGER,event_date TEXT,
        event_number INTEGER,trial_round INTEGER,distance_m INTEGER,grade TEXT,
        weather TEXT,track_condition TEXT,track_moisture_percent REAL,population_status TEXT
      );
      CREATE TABLE entry (
        id INTEGER PRIMARY KEY,event_id INTEGER,hr_no TEXT,horse_number INTEGER,
        horse_name TEXT,finish_position INTEGER,finish_time_ms INTEGER,record_status TEXT,
        segment_quality TEXT,time_analysis_eligible INTEGER,identity_status TEXT,
        source_row_id INTEGER
      );
      CREATE TABLE source_row (id INTEGER PRIMARY KEY,normalized_json TEXT);
      CREATE TABLE section_checkpoint (
        entry_id INTEGER,section_code TEXT,source_value_ms INTEGER,
        elapsed_from_start_ms INTEGER,time_basis TEXT,distance_from_start_m INTEGER,
        distance_is_approximate INTEGER,source_kind TEXT
      );
    """)
    return connection


def _insert(
    connection: sqlite3.Connection,
    number: int,
    *,
    day: str = "20240101",
    kind: str = "race",
    horse_id: str = "3103607",
    identity: str | None = None,
    population: str | None = None,
    status: str = "normal_completed",
    payload: dict | None = None,
) -> None:
    identity = identity or (
        "official_race_ids_linked" if kind == "race" else "official_trial_hr_tr_linked"
    )
    population = population or (
        "confirmed_native_normal_race" if kind == "race" else "native_confirmed_trial"
    )
    connection.execute(
        "INSERT INTO event VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (number, kind, 2, day, number, None, 800, "제6", "맑음", "건조", 3, population),
    )
    connection.execute(
        "INSERT INTO entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (number, number, horse_id, 1, "영웅본색", 1, 66000, status, "usable", 1,
         identity, number),
    )
    connection.execute(
        "INSERT INTO source_row VALUES (?,?)", (number, json.dumps(payload or {}))
    )
    connection.execute(
        "INSERT INTO section_checkpoint VALUES (?,?,?,?,?,?,?,?)",
        (number, "G3F", 48000, 18000, "closing", 200, 0, "trial_archived_text"),
    )
    connection.commit()


def test_only_verified_events_before_cutoff_and_requested_horses(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    with _archive(path) as connection:
        _insert(connection, 1)
        _insert(connection, 2, kind="trial", status="non_positive_result_entry")
        _insert(connection, 3, day="20260919")
        _insert(connection, 4, day="20260920")
        _insert(connection, 5, identity="official_race_id_unresolved")
        _insert(connection, 6, kind="trial", identity="official_trial_identity_unresolved")
        _insert(connection, 7, horse_id="3109999")
        _insert(
            connection, 8, status="quarantined_no_positive_result_race",
            identity="official_source_ids_unvalidated_quarantine",
            population="explicit_je_no_positive_result",
        )
        _insert(connection, 9, population="explicit_je_no_positive_result")
    result = load_verified_archive(["3103607"], date(2026, 9, 19), db_path=path)
    assert list(result) == ["3103607"]
    horse = result["3103607"]
    assert [row["archive_entry_id"] for row in horse["races"]] == [1]
    assert [row["archive_entry_id"] for row in horse["trials"]] == [2]
    assert horse["trials"][0]["record_status"] == "non_positive_result_entry"
    assert horse["race_total"] == horse["trial_total"] == 1


def test_limit_is_per_horse_per_event_type_and_reports_total(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    with _archive(path) as connection:
        _insert(connection, 1, day="20240101")
        _insert(connection, 2, day="20240102")
        _insert(connection, 3, day="20240103")
        _insert(connection, 4, day="20240101", kind="trial")
        _insert(connection, 5, day="20240102", kind="trial")
        _insert(connection, 6, horse_id="3109999")
    result = load_verified_archive(
        ["3103607", "3109999"], date(2026, 9, 19), db_path=path, limit_per_horse=1
    )
    horse = result["3103607"]
    assert [row["archive_entry_id"] for row in horse["races"]] == [3]
    assert [row["archive_entry_id"] for row in horse["trials"]] == [5]
    assert horse["race_total"] == 3
    assert horse["trial_total"] == 2
    assert horse["races_truncated"] and horse["trials_truncated"]
    assert result["3109999"]["race_total"] == 1
    assert not result["3109999"]["races_truncated"]


def test_sections_keep_source_time_basis_and_context_has_no_raw_payload(tmp_path: Path) -> None:
    path = tmp_path / "history.sqlite3"
    with _archive(path) as connection:
        _insert(connection, 1, kind="trial", payload={
            "secret_url": "https://example.test/?serviceKey=private",
            "trial_result": {
                "jockey_name": "문현진", "trainer_name": "신경호", "body_weight_kg": 283,
                "carried_weight_base_kg": 55, "carried_weight_extra_kg": 1,
                "carried_weight_raw": "55+1", "judgement": "불",
                "failure_reason": "능력미달", "inspection_reason": "장기휴양",
                "passing_order_raw": "1-2-3", "finish_rank_raw": "04",
            },
        })
    before = path.read_bytes()
    row = load_verified_archive(["3103607"], date(2026, 9, 19), db_path=path)[
        "3103607"
    ]["trials"][0]
    assert row["date"] == "2024-01-01"
    assert row["sections"]["G3F"] == {
        "raw_ms": 48000, "elapsed_ms": 18000, "time_basis": "closing",
        "distance_from_start_m": 200, "approximate": False, "source_kind": "trial_archived_text",
    }
    assert row["jockey"] == "문현진"
    assert row["body_weight_kg"] == 283
    assert row["carried_weight_extra_kg"] == 1
    assert row["judgement"] == "불"
    assert row["passing_order"] == "1-2-3"
    assert "serviceKey" not in json.dumps(row)
    assert str(path) not in json.dumps(row)
    assert path.read_bytes() == before


def test_optional_archive_and_environment_override(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "absent.sqlite3"
    assert load_verified_archive(["3103607"], date(2026, 9, 19), db_path=path) == {}
    assert not path.exists()
    with _archive(path) as connection:
        _insert(connection, 1, payload={"wgHr": "279(+1)", "wgBudam": 60, "jkName": "박성광"})
    monkeypatch.setenv("HORSE_RACING_ANALYSIS_ARCHIVE_DB", str(path))
    horse = load_verified_archive(["3103607"], date(2026, 9, 19))["3103607"]
    assert horse["races"][0]["body_weight_kg"] == 279
    assert horse["races"][0]["carried_weight_kg"] == 60


def test_corrupt_database_warns_without_exposing_path(tmp_path: Path, caplog, monkeypatch) -> None:
    # Alembic's fileConfig disables existing loggers in earlier dashboard tests.
    # Restore this test's logger locally; leave application logging policy alone.
    logger = logging.getLogger("horse_racing.web.analysis_archive")
    monkeypatch.setattr(logger, "disabled", False)
    path = tmp_path / "private-source.sqlite3"
    path.write_text("not sqlite")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        assert load_verified_archive(["3103607"], date(2026, 9, 19), db_path=path) == {}
    assert "Verified analysis archive unavailable" in caplog.text
    assert "private-source" not in caplog.text


def test_parameter_bounds_and_non_numeric_ids(tmp_path: Path) -> None:
    path = tmp_path / "absent.sqlite3"
    assert load_verified_archive(["'; DROP TABLE entry;--"], date.today(), db_path=path) == {}
    for limit in (0, 501):
        with pytest.raises(ValueError, match="limit_per_horse"):
            load_verified_archive(["3103607"], date.today(), db_path=path, limit_per_horse=limit)
    with pytest.raises(ValueError, match="At most 64"):
        load_verified_archive([str(value) for value in range(65)], date.today(), db_path=path)

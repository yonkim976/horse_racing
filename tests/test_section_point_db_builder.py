from __future__ import annotations

import sqlite3

from scripts.build_section_point_db import (
    create,
    create_verified_support,
    create_views,
    ensure_columns,
    repair,
)


def test_verified_view_uses_independent_position_and_excludes_conflicts() -> None:
    con = sqlite3.connect(":memory:")
    try:
        create(con)
        ensure_columns(con)
        con.executemany(
            """
            INSERT INTO finish_time
              (race_entry_id, meet_code, race_date, race_number, distance_m,
               kra_horse_id, horse_number, finish_position, finish_time_ms,
               scratched, result_state)
            VALUES (?,3,'2026-09-18',1,1200,?,?,1,78000,0,'finished')
            """,
            [(1, "0000001", 1), (2, "0000002", 2), (3, "0000003", 3)],
        )

        def add(
            entry: int, code: str, kind: str, ms: int, source: str,
            *, position: int | None = None, field: str = "",
        ) -> None:
            con.execute(
                """
                INSERT INTO section_time
                  (meet_code, race_date, race_number, distance_m, kra_horse_id,
                   horse_number, race_entry_id, point_code, point_kind, time_kind,
                   meters_from_start, meters_before_finish, elapsed_time_ms,
                   position, source_name, source_field, classification)
                VALUES (3,'2026-09-18',1,1200,?,?,?,?,?, ?,?,?, ?,?,?,?,?)
                """,
                (
                    f"{entry:07d}", entry, entry, code,
                    "start" if code == "S1F" else "furlong", kind,
                    200 if code == "S1F" else 600,
                    1000 if code == "S1F" else 600,
                    ms, position, source, field,
                    "pace_vs_finish" if source == "operational" else "api_field",
                ),
            )

        add(1, "S1F", "cumulative", 14000, "operational", position=2)
        add(1, "S1F", "cumulative", 14000, "busan_research", field="buS1fAccTime")
        add(1, "G3F", "closing", 40000, "operational", position=1)
        add(1, "G3F", "cumulative", 40000, "busan_research", field="buG3fAccTime")
        add(1, "G3F", "closing", 38000, "busan_research", field="bu_3fGTime")
        add(2, "S1F", "cumulative", 15000, "operational", position=99)
        add(2, "S1F", "cumulative", 15000, "busan_research", field="buS1fAccTime")
        add(2, "G1F", "cumulative", 65000, "operational", position=5)
        add(2, "G1F", "cumulative", 65000, "busan_research", field="buG1fAccTime")
        add(2, "G3F", "cumulative", 40050, "operational", position=3)
        add(2, "G3F", "cumulative", 40000, "busan_research", field="buG3fAccTime")
        add(2, "G3F", "closing", 40100, "busan_research", field="bu_3fGTime")
        add(3, "S1F", "cumulative", 16000, "operational", position=3)
        add(3, "S1F", "cumulative", 20000, "busan_research", field="buS1fAccTime")

        repair(con)
        create_verified_support(con)
        create_views(con, verified=True)

        assert con.execute(
            "SELECT position, position_raw, position_quality_status, source_name "
            "FROM common_point WHERE race_entry_id=1 AND point_code='S1F'"
        ).fetchone() == (2, 2, "valid", "busan_research")
        assert con.execute(
            "SELECT time_kind, position FROM common_point "
            "WHERE race_entry_id=1 AND point_code='G3F' ORDER BY time_kind"
        ).fetchall() == [("closing", 1), ("cumulative", 1)]
        assert con.execute(
            "SELECT time_kind, classification FROM section_time "
            "WHERE race_entry_id=1 AND point_code='G3F' AND source_name='operational'"
        ).fetchone() == ("cumulative", "aligned_to_api_field")
        assert con.execute(
            "SELECT position, position_raw, position_quality_status FROM common_point "
            "WHERE race_entry_id=2 AND point_code='S1F'"
        ).fetchone() == (None, 99, "sentinel_or_invalid")
        assert con.execute(
            "SELECT position, position_raw, position_quality_status FROM common_point "
            "WHERE race_entry_id=2 AND point_code='G1F'"
        ).fetchone() == (None, 5, "above_loaded_field_size")
        assert con.execute(
            "SELECT count(*) FROM common_point WHERE race_entry_id=2 AND point_code='G3F'"
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT count(*) FROM quality_issue WHERE issue_code='pair_mismatch'"
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT count(*) FROM quality_issue WHERE issue_code='ambiguous_api_kind'"
        ).fetchone()[0] == 1
        assert con.execute(
            "SELECT count(*) FROM common_point WHERE race_entry_id=3"
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT count(*) FROM quality_issue WHERE issue_code='source_conflict'"
        ).fetchone()[0] == 1
    finally:
        con.close()

import sqlite3

from scripts.adjudicate_section_points import (
    flag_closing_subset_violations,
    page_rows,
    parse_time,
)


def test_parse_time() -> None:
    assert parse_time("0:13.4") == 13400
    assert parse_time("1:02.9") == 62900
    assert parse_time("not a time") is None


def test_page_rows_separates_split_and_cumulative() -> None:
    html = """
    <table><tr><th>구간별 통과순위</th><th>S-1F</th><th>3F-G</th></tr>
      <tr><td>1</td><td>7</td><td>1-1-1</td><td>0:14.0</td>
          <td>0:25.8</td><td>0:25.2</td><td>0:26.2</td>
          <td>0:38.9</td><td>0:13.6</td><td>1:17.2</td></tr></table>
    <table><tr><th>구간별 통과순위</th><th>통과 누적기록</th></tr>
      <tr><td>1</td><td>7</td><td>1-1-1</td><td>0:14.0</td>
          <td>0:25.8</td><td>0:38.3</td><td>0:51.0</td>
          <td>1:03.6</td><td>1:17.2</td></tr></table>
    """
    split, cumulative = page_rows(html.encode())
    assert split[7] == {"S1F": 14000, "G3F": 38900, "G1F": 13600, "FIN": 77200}
    assert cumulative[7] == {"S1F": 14000, "G3F": 38300, "G1F": 63600, "FIN": 77200}


def test_closing_subset_violation_flags_both_values() -> None:
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(
            """CREATE TABLE section_time (
                 id INTEGER PRIMARY KEY, meet_code INTEGER, race_entry_id INTEGER,
                 point_code TEXT, time_kind TEXT, representation TEXT,
                 elapsed_time_ms INTEGER);
               CREATE TABLE quality_issue (
                 section_id INTEGER, issue_code TEXT, detail TEXT,
                 PRIMARY KEY(section_id,issue_code));
               INSERT INTO section_time VALUES
                 (1,2,10,'G3F','closing','canonical',49900),
                 (2,2,10,'G1F','closing','canonical',77200);"""
        )
        assert flag_closing_subset_violations(con) == 2
        assert flag_closing_subset_violations(con) == 2
        assert con.execute(
            "SELECT section_id FROM quality_issue ORDER BY section_id"
        ).fetchall() == [(1,), (2,)]
    finally:
        con.close()

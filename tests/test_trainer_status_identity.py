import sqlite3

from scripts.apply_20260929_trainer_status_identity import DB, build_payload


def test_reviewed_trainer_status_payload_has_complete_official_id_evidence() -> None:
    statuses, aliases = build_payload()
    assert len(statuses) == 59
    assert len(aliases) == 65

    by_number = {row["official_tr_no"]: row for row in statuses}
    for tr_no in ("070103", "070157", "070168"):
        assert by_number[tr_no]["status_code"] == "active"
        assert by_number[tr_no]["region_code"] == "SEOUL"

    confirmed = [row for row in aliases if row["resolution_status"] == "confirmed"]
    assert len(confirmed) == 11
    assert sum(row["matched_race_rows"] for row in confirmed) == 3574
    assert {row["official_tr_no"] for row in confirmed} == {"070167", "070133"}
    assert {row["canonical_name_ko"] for row in confirmed} == {"이신우", "윤영훈"}

    ended = [row for row in statuses if row["status_code"] == "domestic_registration_ended"]
    assert len(ended) == 54
    assert all(row["source_end_date"] is not None for row in ended)
    assert all(row["status_label_ko"] == "국내 등록 종료(은퇴 미확인)" for row in ended)


def test_confirmed_trainer_names_are_canonical_with_originals_preserved() -> None:
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "select ir.official_tr_no, count(*), sum(ir.matched_race_rows), "
            "sum((select count(*) from race_entries e where e.trainer_id=t.id)), "
            "sum(t.name_ko=ir.canonical_name_ko), "
            "sum(ir.source_name_ko<>ir.canonical_name_ko) "
            "from trainer_identity_resolutions ir "
            "join trainers t on t.kra_trainer_id=ir.temporary_trainer_ref "
            "where ir.resolution_status='confirmed' group by ir.official_tr_no"
        ).fetchall()
    finally:
        connection.close()
    assert sorted(rows) == [
        ("070133", 6, 1335, 1335, 6, 6),
        ("070167", 5, 2239, 2239, 5, 5),
    ]

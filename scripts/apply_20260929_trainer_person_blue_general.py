"""Apply the reviewed visiting-trainer links and four Jeju horse corrections.

Default is a read-only preflight. Use --apply only after the 0023 migration and a
SQLite online backup. The original dacom11 report is deliberately untouched.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data/horse_racing.sqlite3"
TARGETS = (
    ("2019-05-03", 8, 10),
    ("2019-05-25", 9, 10),
    ("2019-06-08", 8, 3),
    ("2019-07-12", 9, 7),
)
PEOPLE = (
    ("guest-tan-hai-wang", "TAN HAI WANG", "1969-01-13", "birth_date_and_name"),
    ("guest-jane-chapple-hyam", "JANE CHAPPLE-HYAM", "1966-10-21", "mixed"),
    ("guest-yu-sak-tsui", "YU SAK TSUI", None, "english_name_and_visit"),
)
ARCHIVE = "docs/research_archive/source/seoul_text_id_linkage_20260915_v1/candidate_evidence.csv"
PROFILE = "https://race.kra.co.kr/trainer/profileTrainerPersonItem.do?Act=08&Sub=1&meet=1&trNo="
LINKS = (
    (
        "070187",
        "guest-tan-hai-wang",
        "official_tr_no",
        "알윈탄",
        "birth_date_match",
        PROFILE + "070187",
        "DOB 1969-01-13; 2014-2015 visit",
    ),
    (
        "070217",
        "guest-tan-hai-wang",
        "official_tr_no",
        "알윈탄",
        "birth_date_match",
        PROFILE + "070217",
        "DOB 1969-01-13; 2016-2018 visit",
    ),
    (
        "070220",
        "guest-jane-chapple-hyam",
        "official_tr_no",
        "채플하임",
        "birth_date_match",
        PROFILE + "070220",
        "DOB 1966-10-21; 2016 visit",
    ),
    (
        "070270",
        "guest-jane-chapple-hyam",
        "official_tr_no",
        "채플하임",
        "english_name_and_visit",
        PROFILE + "070270",
        "DOB 9999-01-01 is unknown, not evidence; JANE CHAPPLE-HYAM; 2019 visit",
    ),
    (
        "070278",
        "guest-jane-chapple-hyam",
        "official_tr_no",
        "제인 채플하임",
        "birth_date_match",
        PROFILE + "070278",
        "DOB 1966-10-21; 2022 visit",
    ),
    (
        "070260",
        "guest-yu-sak-tsui",
        "official_tr_no",
        "유 삭 추이",
        "english_name_and_visit",
        PROFILE + "070260",
        "DOB unknown; YU SAK TSUI; 2018 visit",
    ),
    (
        "070275",
        "guest-yu-sak-tsui",
        "official_tr_no",
        "유 삭 추이",
        "english_name_and_visit",
        PROFILE + "070275",
        "DOB unknown; Y S TSUI; 2019 visit; English initials and Korean name agree",
    ),
    (
        "text:trainer:01d4fcb4a06c7b0a6fba3b65",
        "guest-tan-hai-wang",
        "text_ingest_id",
        "알윈탄",
        "archived_race_candidate",
        ARCHIVE,
        "Text alias spans two official registrations; does not assign a trNo to each race",
    ),
    (
        "text:trainer:05cd1c6084d0321cd2894f00",
        "guest-jane-chapple-hyam",
        "text_ingest_id",
        "채플하임",
        "archived_race_candidate",
        ARCHIVE,
        "Text alias spans 2016 and 2019 registrations",
    ),
    (
        "text:trainer:8588855351a363f5ede54039",
        "guest-jane-chapple-hyam",
        "text_ingest_id",
        "제인 채플",
        "archived_race_candidate",
        ARCHIVE,
        "2022 archived candidate 070278 and KRA name Jane Chapple-hyam",
    ),
    (
        "text:trainer:4a6a65e5072e805ff1fff9f3",
        "guest-yu-sak-tsui",
        "text_ingest_id",
        "유 삭 추이",
        "archived_race_candidate",
        ARCHIVE,
        "Text alias spans 2018 and 2019 registrations",
    ),
)

ENTRY_SQL = """
select e.id, r.race_date_local, r.race_number, e.horse_number, h.kra_horse_id
from race_entries e
join races r on r.id = e.race_id
join racecourses c on c.id = r.racecourse_id
join horses h on h.id = e.horse_id
where c.kra_meet_code = 2
  and (r.race_date_local, r.race_number, e.horse_number) in (
    ('2019-05-03', 8, 10), ('2019-05-25', 9, 10),
    ('2019-06-08', 8, 3), ('2019-07-12', 9, 7)
  )
order by r.race_date_local
"""


def preflight(connection: sqlite3.Connection) -> tuple[list[tuple], int]:
    rows = connection.execute(ENTRY_SQL).fetchall()
    if len(rows) != 4 or tuple((r[1], r[2], r[3]) for r in rows) != TARGETS:
        raise RuntimeError(f"Expected exactly four Jeju race entries; found {rows!r}")
    ids = {r[4] for r in rows}
    if ids not in ({"3018834"}, {"3017931"}):
        raise RuntimeError(f"Horse identities are mixed or unexpected: {ids!r}")
    horse = connection.execute(
        "select id from horses where kra_horse_id = '3017931' and name_ko = '푸른장군'"
    ).fetchone()
    if horse is None:
        raise RuntimeError("Official horse 3017931/푸른장군 is absent")
    duplicates = connection.execute(
        "select count(*) from race_entries where horse_id = ? and race_id in "
        "(select race_id from race_entries where id in (?, ?, ?, ?))",
        (horse[0], *(row[0] for row in rows)),
    ).fetchone()[0]
    if ids == {"3018834"} and duplicates:
        raise RuntimeError("Target horse already has an entry in a target race")
    return rows, horse[0]


def apply(connection: sqlite3.Connection) -> None:
    connection.execute("begin immediate")
    try:
        rows, new_horse_id = preflight(connection)
        if not connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'trainer_people'"
        ).fetchone():
            raise RuntimeError("Run Alembic migration 20260929_0023 first")
        for person in PEOPLE:
            expected = (
                *person,
                "user-confirmed 2026-09-29; KRA trainer profiles and official trainer list",
                "2026-09-29",
            )
            connection.execute(
                "insert into trainer_people "
                "(person_key, canonical_name_en, birth_date, identity_basis, "
                "decision_source, decided_on) "
                "values (?, ?, ?, ?, ?, ?) on conflict(person_key) do nothing",
                expected,
            )
            actual = connection.execute(
                "select person_key, canonical_name_en, birth_date, identity_basis, "
                "decision_source, decided_on "
                "from trainer_people where person_key = ?",
                (person[0],),
            ).fetchone()
            if actual != expected:
                raise RuntimeError(f"Conflicting trainer person row: {person[0]}")
        for link in LINKS:
            connection.execute(
                "insert into trainer_person_links "
                "(trainer_ref, person_key, ref_kind, name_at_source, link_basis, "
                "source_reference, evidence_note) "
                "values (?, ?, ?, ?, ?, ?, ?) on conflict(trainer_ref) do nothing",
                link,
            )
            actual = connection.execute(
                "select trainer_ref, person_key, ref_kind, name_at_source, link_basis, "
                "source_reference, evidence_note "
                "from trainer_person_links where trainer_ref = ?",
                (link[0],),
            ).fetchone()
            if actual != link:
                raise RuntimeError(f"Conflicting trainer reference: {link[0]}")
        if rows[0][4] == "3018834":
            changed = connection.execute(
                "update race_entries set horse_id = ? where id in (?, ?, ?, ?) "
                "and horse_id = (select id from horses where kra_horse_id = '3018834')",
                (new_horse_id, *(row[0] for row in rows)),
            ).rowcount
            if changed != 4:
                raise RuntimeError(f"Expected four horse updates, changed {changed}")
        final_rows, _ = preflight(connection)
        if {r[4] for r in final_rows} != {"3017931"}:
            raise RuntimeError("Horse update verification failed")
        connection.commit()
        print("Verified: 4 Jeju entries, 3 trainer people, 11 identity links")
    except Exception:
        connection.rollback()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the reviewed correction")
    args = parser.parse_args()
    mode = "rw" if args.apply else "ro"
    connection = sqlite3.connect(f"file:{DB}?mode={mode}", uri=True, timeout=10)
    try:
        connection.execute("pragma foreign_keys = on")
        if args.apply:
            apply(connection)
        else:
            rows, _ = preflight(connection)
            print("Preflight:", rows)
            print("Use --apply after the Alembic migration and an online backup")
    finally:
        connection.close()


if __name__ == "__main__":
    main()

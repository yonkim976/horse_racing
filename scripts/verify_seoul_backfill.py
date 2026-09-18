"""Read-only validation, overlap audit, and hashes for the isolated Seoul dataset."""
# ruff: noqa: E501  # SQL source strings and manifest descriptions retain their full form.

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from horse_racing.parsers.dacom11 import parse_dacom11_report

ROOT = Path("data/research/seoul_backfill_20260915_v1")
OPERATING_DB = Path("data/horse_racing.sqlite3")
PRE_AUDIT = Path("data/logs/pre2015_race_result_availability_20260914.json")


def scalar(db: sqlite3.Connection, sql: str, params: tuple = ()) -> object:
    return db.execute(sql, params).fetchone()[0]


def write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    root = ROOT
    db = sqlite3.connect(f"file:{root / 'history.sqlite3'}?mode=ro", uri=True)
    old = sqlite3.connect(f"file:{OPERATING_DB}?mode=ro", uri=True)
    expected = json.loads(PRE_AUDIT.read_text())["meets"]["1"]["years"]
    years: list[tuple] = []
    deviations = []
    preaudit_hash_deviations = []
    for y in range(2000, 2027):
        year = str(y)
        rows = scalar(db, "SELECT count(*) FROM entry WHERE race_date LIKE ?", (year + "%",))
        races = scalar(db, "SELECT count(*) FROM race WHERE race_date LIKE ?", (year + "%",))
        pages = scalar(
            db,
            "SELECT count(*) FROM source_inventory WHERE source_type='result_api' AND source_path LIKE ?",
            (f"%/{year}/%",),
        )
        training = scalar(
            db,
            "SELECT count(*) FROM training_event WHERE source_type='horse_training' AND event_date LIKE ?",
            (year + "%",),
        )
        start = scalar(
            db,
            "SELECT count(*) FROM training_event WHERE source_type='start_training' AND event_date LIKE ?",
            (year + "%",),
        )
        medical = scalar(
            db, "SELECT count(*) FROM medical_event WHERE event_date LIKE ?", (year + "%",)
        )
        weight = scalar(
            db, "SELECT count(*) FROM race_day_weight WHERE race_date LIKE ?", (year + "%",)
        )
        equipment = scalar(
            db, "SELECT count(*) FROM entry_equipment WHERE race_date LIKE ?", (year + "%",)
        )
        confirmed_weight = scalar(
            db,
            "SELECT count(*) FROM race_day_weight WHERE race_date LIKE ? AND link_status='confirmed'",
            (year + "%",),
        )
        confirmed_medical = scalar(
            db,
            "SELECT count(*) FROM medical_event WHERE event_date LIKE ? AND link_status='confirmed'",
            (year + "%",),
        )
        missing_jk = scalar(
            db, "SELECT count(*) FROM entry WHERE race_date LIKE ? AND jockey_no=''", (year + "%",)
        )
        missing_tr = scalar(
            db, "SELECT count(*) FROM entry WHERE race_date LIKE ? AND trainer_no=''", (year + "%",)
        )
        missing_ow = scalar(
            db, "SELECT count(*) FROM entry WHERE race_date LIKE ? AND owner_no=''", (year + "%",)
        )
        prior_training = scalar(
            db,
            "SELECT count(*) FROM research_entry WHERE race_date LIKE ? AND prior_training_28d>0",
            (year + "%",),
        )
        prior_start = scalar(
            db,
            "SELECT count(*) FROM research_entry WHERE race_date LIKE ? AND prior_start_training_28d>0",
            (year + "%",),
        )
        prior_medical = scalar(
            db,
            "SELECT count(*) FROM research_entry WHERE race_date LIKE ? AND prior_confirmed_medical_28d>0",
            (year + "%",),
        )
        years.append(
            (
                year,
                races,
                rows,
                pages,
                training,
                start,
                medical,
                weight,
                equipment,
                confirmed_weight,
                confirmed_medical,
                missing_jk,
                missing_tr,
                missing_ow,
                prior_training,
                prior_start,
                prior_medical,
            )
        )
        if year in expected and (
            rows != expected[year]["api_rows"] or races != expected[year]["api_races"]
        ):
            deviations.append(
                (year, rows, races, expected[year]["api_rows"], expected[year]["api_races"])
            )
        if year in expected:
            prior_hashes = [p["sha256"] for p in expected[year]["api_pages"]]
            current_hashes = [
                hash_file(p) for p in sorted((root / "raw_results" / year).glob("page_*.json"))
            ]
            if prior_hashes != current_hashes:
                preaudit_hash_deviations.append((year, prior_hashes, current_hashes))
    write_csv(
        root / "coverage_year_source_verified.csv",
        [
            "year",
            "official_races",
            "official_entries",
            "result_pages",
            "training_events",
            "start_training_events",
            "medical_events",
            "weight_observations",
            "equipment_rows",
            "confirmed_weight_links",
            "confirmed_medical_links",
            "missing_jockey_id",
            "missing_trainer_id",
            "missing_owner_id",
            "entries_with_prior_training_28d",
            "entries_with_prior_start_training_28d",
            "entries_with_prior_confirmed_medical_28d",
        ],
        years,
    )

    api_all_races = set(db.execute("SELECT race_date,race_no FROM race"))
    text_gaps = []
    text_coverage = []
    for source in ("dacom01", "dacom11", "dacom12", "dacom71"):
        text_keys = set(
            db.execute(
                "SELECT DISTINCT race_date,race_no FROM text_race_heading WHERE source_type=?",
                (source,),
            )
        )
        for year in range(2000, 2027):
            y = str(year)
            a = {key for key in api_all_races if key[0].startswith(y)}
            t = {key for key in text_keys if key[0].startswith(y)}
            text_coverage.append((source, y, len(t), len(a & t), len(t - a), len(a - t)))
            text_gaps.extend((source, "text_only", *key) for key in sorted(t - a))
            text_gaps.extend((source, "api_only", *key) for key in sorted(a - t))
    write_csv(
        root / "text_race_key_coverage.csv",
        ["source", "year", "text_race_keys", "common_keys", "text_only", "api_only"],
        text_coverage,
    )
    write_csv(
        root / "text_race_key_gaps.csv", ["source", "side", "race_date", "race_no"], text_gaps
    )

    # Compare only completed operating races. Official API remains the source of truth.
    old_races = set(
        old.execute("""SELECT r.race_date_local,r.race_number FROM races r
        WHERE r.racecourse_id=1 AND r.status='completed'""")
    )
    api_races = set(db.execute("SELECT race_date,race_no FROM race WHERE race_date>='2015-01-01'"))
    old_entries = {}
    for day, no, hr, jk, tr, ow, pos, ms in old.execute("""SELECT
        r.race_date_local,r.race_number,h.kra_horse_id,j.kra_jockey_id,
        t.kra_trainer_id,o.kra_owner_id,x.finish_position,x.finish_time_ms
      FROM race_entries e JOIN races r ON r.id=e.race_id
      JOIN horses h ON h.id=e.horse_id
      LEFT JOIN jockeys j ON j.id=e.jockey_id
      LEFT JOIN trainers t ON t.id=e.trainer_id
      LEFT JOIN owners o ON o.id=e.owner_id
      LEFT JOIN race_results x ON x.race_entry_id=e.id
      WHERE r.racecourse_id=1 AND r.status='completed'"""):
        old_entries[(day, no, str(hr).zfill(7))] = (jk, tr, ow, pos, ms)
    api_entries = {}
    for day, no, hr, jk, tr, ow, pos, seconds in db.execute("""SELECT
        e.race_date,e.race_no,e.hr_no,e.jockey_no,e.trainer_no,e.owner_no,
        x.finish_raw,x.race_time_s FROM entry e
        JOIN result x USING(meet,race_date,race_no,hr_no)
        WHERE e.race_date>='2015-01-01'"""):
        api_entries[(day, no, hr)] = (jk, tr, ow, pos, round(seconds * 1000) if seconds else None)
    legacy_horse_keys = {key for key in old_entries if key[2].startswith("text:")}
    old_official_keys = old_entries.keys() - legacy_horse_keys
    disagreements = []
    legacy_ids = []
    for key in sorted(api_entries.keys() & old_entries.keys()):
        a, b = api_entries[key], old_entries[key]
        for idx, field in enumerate(("jkNo", "trNo", "owNo")):
            if isinstance(b[idx], str) and b[idx].startswith("text:"):
                legacy_ids.append((*key, field, a[idx], b[idx]))
                continue
            if a[idx] and b[idx] and a[idx].lstrip("0") != str(b[idx]).lstrip("0"):
                disagreements.append((*key, field, a[idx], b[idx]))
        if a[4] is not None and b[4] is not None and a[4] != b[4]:
            disagreements.append((*key, "finish_ms", a[4], b[4]))
    write_csv(
        root / "operating_db_disagreements.csv",
        ["race_date", "race_no", "hr_no", "field", "api_value", "operating_db_value"],
        disagreements,
    )
    write_csv(
        root / "operating_db_legacy_id_namespace.csv",
        ["race_date", "race_no", "hr_no", "field", "official_api_id", "legacy_text_id"],
        legacy_ids,
    )
    write_csv(
        root / "operating_db_key_gaps.csv",
        ["side", "race_date", "race_no", "hr_no"],
        [("api_only", *k) for k in sorted(api_entries.keys() - old_entries.keys())]
        + [("db_only", *k) for k in sorted(old_official_keys - api_entries.keys())],
    )
    write_csv(
        root / "operating_db_race_gaps.csv",
        ["side", "race_date", "race_no", "official_result_state"],
        [
            (
                "api_only",
                day,
                no,
                scalar(
                    db,
                    "SELECT official_result_state FROM race WHERE race_date=? AND race_no=?",
                    (day, no),
                ),
            )
            for day, no in sorted(api_races - old_races)
        ]
        + [("db_only", day, no, "") for day, no in sorted(old_races - api_races)],
    )
    write_csv(
        root / "operating_db_legacy_horse_ids.csv",
        ["race_date", "race_no", "legacy_horse_id"],
        sorted(legacy_horse_keys),
    )

    write_csv(
        root / "race_regime.csv",
        [
            "race_date",
            "race_no",
            "distance_m",
            "grade_raw",
            "burden_type_raw",
            "rating_condition_raw",
            "rating_system",
            "surface_regime",
            "mile_1600_era",
            "official_result_state",
            "track_raw",
            "weather_raw",
            "source_path",
        ],
        list(
            db.execute("""SELECT race_date,race_no,distance_m,race_class,
                burden_type,rating_condition_raw,rating_system,surface_regime,
                mile_1600_era,official_result_state,track_raw,weather_raw,source_path FROM race
                ORDER BY race_date,race_no""")
        ),
    )
    write_csv(
        root / "unresolved_result_status.csv",
        [
            "race_date",
            "race_no",
            "hr_no",
            "finish_raw",
            "result_status",
            "race_time_s",
            "source_path",
            "source_row",
        ],
        list(
            db.execute("""SELECT race_date,race_no,hr_no,finish_raw,result_status,
          race_time_s,source_path,source_row FROM result WHERE result_status IN
          ('void_or_unresulted','unmapped_special_98','ranked_time_missing_unconfirmed',
           'unmapped_special_code') ORDER BY race_date,race_no,hr_no""")
        ),
    )
    write_csv(
        root / "unresolved_official_ids.csv",
        [
            "race_date",
            "race_no",
            "hr_no",
            "horse_name",
            "jockey_no",
            "trainer_no",
            "owner_no",
            "source_path",
            "source_row",
        ],
        list(
            db.execute("""SELECT race_date,race_no,hr_no,horse_name,
                jockey_no,trainer_no,owner_no,source_path,source_row FROM entry
                WHERE jockey_no='' OR trainer_no='' OR owner_no='' ORDER BY race_date,race_no,hr_no""")
        ),
    )

    # One ID may have several historical names; report rather than name-linking.
    id_collisions = []
    for kind, col, name_col in (
        ("horse", "hr_no", "horse_name"),
        ("jockey", "jockey_no", "jockey_name"),
        ("trainer", "trainer_no", "trainer_name"),
        ("owner", "owner_no", "owner_name"),
    ):
        for ident, names, n in db.execute(f"""SELECT {col},group_concat(DISTINCT {name_col}),
          count(DISTINCT {name_col}) FROM entry WHERE {col} IS NOT NULL AND {col}!=''
          GROUP BY {col} HAVING count(DISTINCT {name_col})>1"""):
            id_collisions.append((kind, ident, n, names))
    write_csv(
        root / "id_name_variants.csv", ["kind", "official_id", "name_count", "names"], id_collisions
    )

    # The Text report uses closing G3F/G1F; API4_3 uses cumulative checkpoints.
    by_card = defaultdict(list)
    for day, no, chul, name, hr in db.execute(
        "SELECT race_date,race_no,chul_no,horse_name,hr_no FROM entry"
    ):
        by_card[(day, no, chul)].append((name, hr))
    api_sections = {}
    for day, no, hr, code, value, closing in db.execute(
        "SELECT race_date,race_no,hr_no,section_code,value_s,canonical_closing_s "
        "FROM section WHERE race_date>='2015-01-01'"
    ):
        api_sections[(day, no, hr, code)] = (value, closing)
    text_sections = []
    text_parse_errors = []
    text_mismatches = []
    for (source_path,) in db.execute(
        "SELECT source_path FROM source_inventory WHERE source_type='dacom11'"
    ):
        try:
            parsed = parse_dacom11_report(Path(source_path).read_bytes())
        except Exception as exc:
            text_parse_errors.append((source_path, type(exc).__name__, str(exc)))
            continue
        for race in parsed:
            day = race.race_date.isoformat()
            for entry in race.entries:
                candidates = by_card.get((day, race.race_number, entry.horse_number), [])
                exact = [hr for name, hr in candidates if name == entry.horse_name]
                hr = exact[0] if len(exact) == 1 else None
                link = "confirmed" if hr else "ambiguous" if candidates else "unmatched"
                fields = {
                    "S1F": entry.s1f_ms,
                    "G3F": entry.g3f_ms,
                    "G1F": entry.g1f_ms,
                    **entry.corner_times_ms,
                }
                for code, ms in fields.items():
                    if ms is None:
                        continue
                    basis = "closing" if code in {"G3F", "G1F"} else "cumulative"
                    api = api_sections.get((day, race.race_number, hr, code)) if hr else None
                    comparable = api[1] if api and basis == "closing" else api[0] if api else None
                    delta = round(ms / 1000 - comparable, 3) if comparable is not None else None
                    text_sections.append(
                        (
                            day,
                            race.race_number,
                            entry.horse_number,
                            entry.horse_name,
                            hr,
                            link,
                            code,
                            ms / 1000,
                            basis,
                            comparable,
                            delta,
                            source_path,
                        )
                    )
                    if delta is not None and abs(delta) > 0.11:
                        text_mismatches.append(text_sections[-1])
    write_csv(
        root / "text_sections.csv",
        [
            "race_date",
            "race_no",
            "chul_no",
            "horse_name",
            "hr_no",
            "link_status",
            "section_code",
            "text_seconds",
            "text_time_basis",
            "api_equivalent_seconds",
            "delta_seconds",
            "source_path",
        ],
        text_sections,
    )
    write_csv(
        root / "text_section_mismatches.csv",
        [
            "race_date",
            "race_no",
            "chul_no",
            "horse_name",
            "hr_no",
            "link_status",
            "section_code",
            "text_seconds",
            "text_time_basis",
            "api_equivalent_seconds",
            "delta_seconds",
            "source_path",
        ],
        text_mismatches,
    )
    write_csv(
        root / "text_parse_errors.csv", ["source_path", "error_type", "message"], text_parse_errors
    )

    source_errors = []
    for typ, path, digest, size in db.execute(
        "SELECT source_type,source_path,sha256,bytes FROM source_inventory"
    ):
        p = Path(path)
        if p.stat().st_size != size or hash_file(p) != digest:
            source_errors.append((typ, path))
    ledger_errors = []
    request_events = [
        json.loads(line) for line in (root / "request_ledger.jsonl").read_text().splitlines()
    ]
    for event in request_events:
        if event.get("status") not in {"downloaded", "reused"}:
            continue
        path = Path(event["path"])
        if not path.is_file() or hash_file(path) != event["sha256"]:
            ledger_errors.append((event.get("scope"), event.get("page"), "hash_or_file"))
        if event["response_rows"] > event["total_count"]:
            ledger_errors.append((event.get("scope"), event.get("page"), "page_total"))

    firsts = {}
    for typ, query in {
        "result_api": "SELECT min(race_date) FROM race",
        "horse_training_api": "SELECT min(event_date) FROM training_event WHERE source_type='horse_training'",
        "start_training_api": "SELECT min(event_date) FROM training_event WHERE source_type='start_training'",
        "weight_text_file": "SELECT min(file_date) FROM source_inventory WHERE source_type='dacom12' AND bytes>0",
        "weight_text_observation": "SELECT min(race_date) FROM race_day_weight",
        "medical_text_file": "SELECT min(file_date) FROM source_inventory WHERE source_type='dacom72' AND bytes>0",
        "medical_text_event": "SELECT min(event_date) FROM medical_event",
        "equipment_text_file": "SELECT min(file_date) FROM source_inventory WHERE source_type='dacom71' AND bytes>0",
    }.items():
        firsts[typ] = scalar(db, query)
    status = dict(db.execute("SELECT result_status,count(*) FROM result GROUP BY 1"))
    summary = {
        "scope": "Seoul meet=1; KRA API result through latest archived official result",
        "races": scalar(db, "SELECT count(*) FROM race"),
        "entries": scalar(db, "SELECT count(*) FROM entry"),
        "results": scalar(db, "SELECT count(*) FROM result"),
        "sections": scalar(db, "SELECT count(*) FROM section"),
        "research_rows": scalar(db, "SELECT count(*) FROM research_entry"),
        "first_last_result": db.execute(
            "SELECT min(race_date),max(race_date) FROM race"
        ).fetchone(),
        "first_last_confirmed_result": db.execute(
            "SELECT min(race_date),max(race_date) FROM race WHERE official_result_state='confirmed'"
        ).fetchone(),
        "first_1600m": db.execute(
            "SELECT race_date,race_no FROM race WHERE distance_m=1600 ORDER BY race_date,race_no LIMIT 1"
        ).fetchone(),
        "first_rating": db.execute(
            "SELECT race_date,race_no,race_class,rating_condition_raw,source_path FROM race WHERE rating_system='rating' ORDER BY race_date,race_no LIMIT 1"
        ).fetchone(),
        "last_pre_rating": db.execute(
            "SELECT race_date,race_no,race_class,rating_condition_raw,source_path FROM race WHERE rating_system='pre_rating' ORDER BY race_date DESC,race_no DESC LIMIT 1"
        ).fetchone(),
        "preaudit_deviations": deviations,
        "preaudit_hash_deviations": preaudit_hash_deviations,
        "text_only_race_keys": sum(row[4] for row in text_coverage),
        "source_hash_errors": source_errors,
        "request_ledger_errors": ledger_errors,
        "primary_key_checks": {
            "result_rows_equal_entry_rows": scalar(db, "SELECT count(*) FROM result")
            == scalar(db, "SELECT count(*) FROM entry"),
            "research_rows_equal_target_entries": scalar(db, "SELECT count(*) FROM research_entry")
            == scalar(
                db,
                "SELECT count(*) FROM entry e JOIN race r USING(meet,race_date,race_no) WHERE r.label_scope!='mock'",
            ),
            "raw_api_rows_equal_entry_rows": scalar(
                db, "SELECT sum(rows) FROM source_inventory WHERE source_type='result_api'"
            )
            == scalar(db, "SELECT count(*) FROM entry"),
            "no_special_as_finished": scalar(
                db,
                "SELECT count(*) FROM result WHERE result_status='finished' AND (finish_order<1 OR finish_order>89 OR race_time_s<=0)",
            )
            == 0,
        },
        "first_valid_dates": firsts,
        "result_status_counts": status,
        "race_result_state_counts": dict(
            db.execute("SELECT official_result_state,count(*) FROM race GROUP BY 1")
        ),
        "operating_overlap": {
            "api_races": len(api_races),
            "completed_db_races": len(old_races),
            "common_races": len(api_races & old_races),
            "api_only_races": len(api_races - old_races),
            "db_only_races": len(old_races - api_races),
            "api_entries": len(api_entries),
            "db_entries": len(old_entries),
            "common_entries": len(api_entries.keys() & old_entries.keys()),
            "legacy_text_horse_ids": len(legacy_horse_keys),
            "field_disagreements": len(disagreements),
            "legacy_text_person_ids": len(legacy_ids),
        },
        "id_name_variants": len(id_collisions),
        "text_sections": {
            "rows": len(text_sections),
            "confirmed_link_rows": sum(row[5] == "confirmed" for row in text_sections),
            "compared_rows": sum(row[10] is not None for row in text_sections),
            "mismatches_over_0_11s": len(text_mismatches),
            "parse_error_files": len(text_parse_errors),
        },
        "missing_official_ids": {
            field: scalar(db, f"SELECT count(*) FROM entry WHERE {col}='' OR {col} IS NULL")
            for field, col in (
                ("hrNo", "hr_no"),
                ("jkNo", "jockey_no"),
                ("trNo", "trainer_no"),
                ("owNo", "owner_no"),
            )
        },
        "medical_links": dict(
            db.execute("SELECT link_status,count(*) FROM medical_event GROUP BY 1")
        ),
        "weight_links": dict(
            db.execute("SELECT link_status,count(*) FROM race_day_weight GROUP BY 1")
        ),
        "source_file_counts": dict(
            db.execute("SELECT source_type,count(*) FROM source_inventory GROUP BY 1")
        ),
    }
    (root / "verification.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    manifest_rows = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name in {
            "sha256_manifest.csv",
            "history.sqlite3-shm",
            "history.sqlite3-wal",
            "verify_stdout.json",
        }:
            continue
        manifest_rows.append((str(p), p.stat().st_size, hash_file(p)))
    for p in (
        Path("scripts/collect_seoul_backfill_results.py"),
        Path("scripts/audit_seoul_result_status_codes.py"),
        Path("scripts/build_seoul_backfill.py"),
        Path("scripts/resume_seoul_backfill.py"),
        Path("scripts/finalize_seoul_backfill.py"),
        Path("scripts/correct_seoul_special_98.py"),
        Path("scripts/correct_seoul_zero_time_ranks.py"),
        Path("scripts/verify_seoul_backfill.py"),
        Path("tests/test_seoul_backfill_status.py"),
    ):
        manifest_rows.append((str(p), p.stat().st_size, hash_file(p)))
    write_csv(root / "sha256_manifest.csv", ["path", "bytes", "sha256"], manifest_rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

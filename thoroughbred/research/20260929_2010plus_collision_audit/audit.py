"""Read-only 2010+ race-key and selected result-field source comparison."""

import csv
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
START, END, MODEL_START = "2010-01-01", "2026-09-20", "2017-01-01"
OP = ROOT / "data/horse_racing.sqlite3"
U = ROOT / "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb"
V = ROOT / "thoroughbred/data/dataset_20260929_v1/thoroughbred.duckdb"
CLOSURES = ROOT / "thoroughbred/research/20260929_closure_inventory_v1/closures.csv"


def period(key):
    return "2010_2016" if key[1] < MODEL_START else "2017_plus"


def grouped(keys):
    return dict(sorted(Counter(period(key) for key in keys).items()))


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    op = sqlite3.connect(f"file:{OP}?mode=ro", uri=True)
    op.execute("PRAGMA query_only=ON")
    unified = duckdb.connect(str(U), read_only=True)
    v1 = duckdb.connect(str(V), read_only=True)
    try:
        op_rows = op.execute(
            "SELECT racecourse_id,race_date_local,race_number,distance_m,grade,status "
            "FROM races WHERE racecourse_id IN (1,3,4) AND race_date_local BETWEEN ? AND ?",
            (START, END),
        ).fetchall()
        u_rows = unified.execute(
            "SELECT canonical_meet,race_date,race_no,distance_m,race_class,official_result_state,source_dataset "
            "FROM race WHERE canonical_meet IN (1,3,4) AND race_date BETWEEN ? AND ?",
            [START, END],
        ).fetchall()
        v_rows = v1.execute(
            "SELECT canonical_meet,race_date,race_no FROM race "
            "WHERE canonical_meet IN (1,3,4) AND race_date BETWEEN ? AND ?",
            [START, END],
        ).fetchall()
        o = {(m, str(d), n): (dist, grade, state) for m, d, n, dist, grade, state in op_rows}
        u = {(m, str(d), n): (dist, grade, state, dataset) for m, d, n, dist, grade, state, dataset in u_rows}
        v = {(m, str(d), n) for m, d, n in v_rows}
        assert len(o) == len(op_rows) and len(u) == len(u_rows) and len(v) == len(v_rows)

        op_entry_rows = op.execute(
            "SELECT r.racecourse_id,r.race_date_local,r.race_number,e.horse_number,h.kra_horse_id,"
            "z.finish_position,z.finish_time_ms FROM race_entries e "
            "JOIN races r ON r.id=e.race_id LEFT JOIN horses h ON h.id=e.horse_id "
            "LEFT JOIN race_results z ON z.race_entry_id=e.id "
            "WHERE r.racecourse_id IN (1,3,4) AND r.race_date_local BETWEEN ? AND ?",
            (START, END),
        ).fetchall()
        u_entry_rows = unified.execute(
            "SELECT canonical_meet,race_date,race_no,chul_no,hr_no,finish_order,race_time_s "
            "FROM entry_result WHERE canonical_meet IN (1,3,4) AND race_date BETWEEN ? AND ?",
            [START, END],
        ).fetchall()
        oe = {(m, str(d), n, slot): (str(h).zfill(7) if h is not None else None, pos, ms)
              for m, d, n, slot, h, pos, ms in op_entry_rows}
        ue = {(m, str(d), n, slot): (str(h).zfill(7) if h is not None else None, pos,
                                      round(seconds * 1000) if seconds is not None else None)
              for m, d, n, slot, h, pos, seconds in u_entry_rows}
        assert len(oe) == len(op_entry_rows) and len(ue) == len(u_entry_rows)

        o_only, u_only = set(o) - set(u), set(u) - set(o)
        common = set(o) & set(u)
        grade_diffs = [[*key, o[key][1], u[key][1]] for key in sorted(common) if o[key][1] != u[key][1]]
        allowed_states = {("completed", "confirmed"), ("void", "void"),
                          ("special_only_unresolved", "special_only_unresolved")}
        state_conflicts = [[*key, o[key][2], u[key][2]] for key in sorted(common)
                           if (o[key][2], u[key][2]) not in allowed_states]

        shared_entries = set(oe) & set(ue)
        horse_id_conflicts = [[*key, oe[key][0], ue[key][0]] for key in sorted(shared_entries)
                              if oe[key][0] != ue[key][0]]
        finish_raw_diffs = [key for key in shared_entries if oe[key][1] != ue[key][1]]
        regular_finish_diffs = [[*key, oe[key][1], ue[key][1]] for key in sorted(shared_entries)
                                if oe[key][1] is not None and ue[key][1] is not None
                                and 1 <= oe[key][1] < 90 and 1 <= ue[key][1] < 90
                                and oe[key][1] != ue[key][1]]
        time_diffs = [[*key, oe[key][2], ue[key][2]] for key in sorted(shared_entries)
                      if (oe[key][2] or None) != (ue[key][2] or None)]

        op_horses = defaultdict(set)
        op_horse_slots = defaultdict(dict)
        for key, (horse_id, _, _) in oe.items():
            if horse_id is not None:
                op_horses[key[:3]].add(horse_id)
                op_horse_slots[key[:3]][horse_id] = key[3]
        u_horses = defaultdict(set)
        u_horse_slots = defaultdict(dict)
        for key, (horse_id, _, _) in ue.items():
            if key[:3] in u_only and horse_id is not None:
                u_horses[key[:3]].add(horse_id)
                u_horse_slots[key[:3]][horse_id] = key[3]
        fingerprint_index = defaultdict(list)
        for key, horses in op_horses.items():
            fingerprint_index[frozenset(horses)].append(key)
        exact_horse_set_matches = []
        for key in sorted(u_only):
            horses = u_horses[key]
            if horses:
                for counterpart in fingerprint_index[frozenset(horses)]:
                    exact_horse_set_matches.append({"unified_only_key": list(key),
                                                    "operational_key": list(counterpart),
                                                    "horse_count": len(horses),
                                                    "matching_horse_number_count": sum(
                                                        u_horse_slots[key][h] == op_horse_slots[counterpart][h]
                                                        for h in horses
                                                    ),
                                                    "venue_changed": key[0] != counterpart[0]})
        duplicate_keys = {tuple(item["unified_only_key"]) for item in exact_horse_set_matches}
        duplicate_target_rows = v1.execute(
            "SELECT canonical_meet,race_date,race_no,COUNT(*),"
            "SUM(CASE WHEN is_model_target THEN 1 ELSE 0 END) "
            "FROM entry_result WHERE canonical_meet IN (1,3,4) AND race_date BETWEEN ? AND ? "
            "GROUP BY canonical_meet,race_date,race_no",
            [START, END],
        ).fetchall()
        duplicate_target_counts = {
            (m, str(d), n): (total, targets)
            for m, d, n, total, targets in duplicate_target_rows
            if (m, str(d), n) in duplicate_keys
        }

        with CLOSURES.open(encoding="utf-8", newline="") as stream:
            closures = list(csv.DictReader(stream))
        closure_conflicts = []
        for key in sorted(u_only):
            for c in closures:
                if key[0] == int(c["meet_code"]) and c["start_date"] <= key[1] <= c["end_date"]:
                    closure_conflicts.append({"key": list(key), "source_url": c["source_url"]})

        report = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": {"start": START, "end": END, "model_start": MODEL_START, "meets": [1, 3, 4]},
            "basis": "distinct natural keys; field values compared only on shared keys; source truth not assigned by count",
            "race_keys": {
                "operational": len(o), "historical_unified": len(u), "research_v1": len(v),
                "shared_operational_unified": len(common),
                "unified_only": len(u_only), "operational_only": len(o_only),
                "unified_only_by_period": grouped(u_only), "operational_only_by_period": grouped(o_only),
                "v1_only_vs_operational": len(v - set(o)),
                "operational_only_vs_v1": len(set(o) - v),
                "v1_equals_operational_union_unified": v == set(o) | set(u),
                "unified_only_status_counts": dict(Counter(u[key][2] for key in u_only)),
                "unified_only_by_date_venue": [
                    {"meet": m, "date": date, "count": count}
                    for (m, date), count in sorted(Counter((k[0], k[1]) for k in u_only).items())
                ],
                "operational_only_keys": [list(key) for key in sorted(o_only)],
            },
            "shared_race_fields": {
                "distance_mismatch_count": sum(o[key][0] != u[key][0] for key in common),
                "grade_raw_differences": grade_diffs,
                "result_state_pairs": [{"operational": a, "unified": b, "count": count}
                                       for (a, b), count in Counter((o[key][2], u[key][2]) for key in common).items()],
                "result_state_conflicts_after_basic_mapping": state_conflicts,
            },
            "entry_keys_and_fields": {
                "operational": len(oe), "historical_unified": len(ue), "shared": len(shared_entries),
                "unified_only": len(set(ue) - set(oe)), "operational_only": len(set(oe) - set(ue)),
                "official_horse_id_conflicts": horse_id_conflicts,
                "finish_raw_mismatch_count": len(finish_raw_diffs),
                "finish_raw_mismatch_by_period": grouped(finish_raw_diffs),
                "regular_numeric_finish_conflicts": regular_finish_diffs,
                "finish_time_conflicts_after_zero_as_missing": time_diffs,
            },
            "unified_only_duplicate_candidates": {
                "exact_horse_set_match_count": len(exact_horse_set_matches),
                "distinct_unified_only_keys_matched": len(duplicate_keys),
                "entry_rows_in_research_v1": sum(total for total, _ in duplicate_target_counts.values()),
                "model_target_races_in_research_v1": sum(targets > 0 for _, targets in duplicate_target_counts.values()),
                "model_target_entry_rows_in_research_v1": sum(targets for _, targets in duplicate_target_counts.values()),
                "all_horse_numbers_match": all(
                    item["horse_count"] == item["matching_horse_number_count"]
                    for item in exact_horse_set_matches
                ),
                "matches": exact_horse_set_matches,
                "interpretation": "Exact official horse ID sets are strong duplicate candidates; result and source text still require adjudication.",
            },
            "official_closure_interval_conflicts": closure_conflicts,
            "local_kra_text_evidence": [
                {"case": "2017-12-17 Seoul R13 numeric finish positions",
                 "path": "data/raw/kra_text/dacom11/meet=1/year=2017/month=12/day=17/20171217dacom11.rpt",
                 "sha256": sha256(ROOT / "data/raw/kra_text/dacom11/meet=1/year=2017/month=12/day=17/20171217dacom11.rpt"),
                 "source_values_by_horse_number": {"11": 7, "4": 8, "6": 9}},
                {"case": "2023-03-04 Seoul R8 finish times",
                 "path": "data/raw/kra_text/dacom11/meet=1/year=2023/month=03/day=04/20230304dacom11.rpt",
                 "sha256": sha256(ROOT / "data/raw/kra_text/dacom11/meet=1/year=2023/month=03/day=04/20230304dacom11.rpt"),
                 "source_time_ms_by_horse_number": {"8": 75000, "6": 75100, "4": 76300, "3": 77300}},
            ],
            "manually_checked_official_result": {
                "key": [3, "2010-03-12", 3],
                "url": "https://race.kra.co.kr/globalEn/resultsRaceDetailBusan.do?rcDate=20100312&rcNo=3",
                "checked_date": "2026-09-29",
                "method": "Direct browser inspection of KRA result page; not automated by this script",
                "class": "Class 5", "distance_m": 1200, "finishers": 10,
                "winner": "BARAMKKEOT", "winning_time": "1:18.6",
                "withdrawn_horse_number": 9,
                "assessment": "Genuine completed race missing from operational race table; unified attributes are incomplete."
            },
            "limitations": ["Many unified source_path files are no longer present at those paths.",
                            "Raw code values such as 92/94/95 are not equivalent to a numeric placing.",
                            "A scheduled or void row is not proof that a race ran."]
        }
        (HERE / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"unified_only": len(u_only), "operational_only": len(o_only),
                          "exact_horse_set_matches": len(exact_horse_set_matches),
                          "regular_finish_conflicts": len(regular_finish_diffs),
                          "time_conflicts": len(time_diffs),
                          "closure_conflicts": len(closure_conflicts)}))
    finally:
        v1.close()
        unified.close()
        op.close()


if __name__ == "__main__":
    main()

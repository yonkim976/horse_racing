#!/usr/bin/env python3
"""Read-only profile/comparison of annual Thoroughbred score SQLite files."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
CATALOG = OUT / "database_file_catalog.csv"
OUTPUT = OUT / "supplemental_score_sources.json"
TARGET_END = "2026-09-20"
MODEL_START = "2017-01-01"
PATH_RE = re.compile(
    r"data/research/(?P<family>seoul|busan|yeongcheon|running_trials)_(?P<year>20\d{2})_score_20260925/"
)
MEET_NAMES = {1: "SEOUL", 3: "BUSAN", 4: "YEONGCHEON"}
NAME_MEETS = {v: k for k, v in MEET_NAMES.items()}

RACE_TABLES = {
    "race": {
        "date": "race_date",
        "key": ["meet_code", "race_date", "race_number"],
        "domain": "race_schedule",
    },
    "entry": {
        "date": "race_date",
        "key": ["meet_code", "race_date", "race_number", "horse_number"],
        "domain": "race_entry_result",
    },
    "passing_group": {
        "date": "race_date",
        "key": ["meet_code", "race_date", "race_number", "point_code"],
        "domain": "race_passing_group",
    },
    "section_time": {
        "date": "race_date",
        "key": ["meet_code", "race_date", "race_number", "kra_horse_id", "point_code", "time_kind"],
        "domain": "race_section_time",
    },
}
TRIAL_TABLES = {
    "trial": {
        "date": "trial_date",
        "key": ["meet_code", "trial_date", "trial_race_number"],
        "domain": "trial_schedule",
    },
    "entry": {
        "date": "trial_date",
        "key": ["meet_code", "trial_date", "trial_race_number", "horse_number"],
        "domain": "trial_entry_result",
    },
    "section_time": {
        "date": "trial_date",
        "key": ["meet_code", "trial_date", "trial_race_number", "horse_number", "point_code", "time_kind"],
        "domain": "trial_section_time",
    },
    "point_definition": {
        "date": None,
        "key": ["meet_code", "point_code", "time_kind"],
        "domain": "trial_point_definition",
        "key_note": "Static point/time-kind dictionary; event date is not applicable.",
    },
}


def ro_sqlite(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def qident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Unsafe SQL identifier: {name}")
    return '"' + name + '"'


def iso_day(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if len(s) >= 10:
        return s[:10].replace("/", "-")
    return s or None


def canonical_id(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s.zfill(7) if s.isdigit() else s


def key_profile(
    con: sqlite3.Connection, table: str, columns: list[str], scope_where: str = ""
) -> dict[str, Any]:
    cols = ", ".join(qident(c) for c in columns)
    where = f" WHERE {scope_where}" if scope_where else ""
    n_rows = int(con.execute(f"SELECT COUNT(*) FROM {qident(table)}{where}").fetchone()[0])
    unique_count = int(
        con.execute(
            f"SELECT COUNT(*) FROM (SELECT {cols} FROM {qident(table)}{where} GROUP BY {cols})"
        ).fetchone()[0]
    )
    dup_groups, dup_rows, max_multiplicity = con.execute(
        f"SELECT COUNT(*), COALESCE(SUM(n - 1),0), COALESCE(MAX(n),0) "
        f"FROM (SELECT COUNT(*) n FROM {qident(table)}{where} GROUP BY {cols} HAVING COUNT(*) > 1)"
    ).fetchone()
    null_pred = " OR ".join(f"{qident(c)} IS NULL" for c in columns)
    null_where = f"({scope_where}) AND ({null_pred})" if scope_where else null_pred
    null_key_rows = int(
        con.execute(
            f"SELECT COUNT(*) FROM {qident(table)} WHERE {null_where}"
        ).fetchone()[0]
    )
    return {
        "columns": columns,
        "unique_key_count": unique_count,
        "duplicate_key_groups": int(dup_groups),
        "duplicate_rows_beyond_one_per_key": int(dup_rows),
        "max_rows_per_key": int(max_multiplicity),
        "rows_with_null_key_component": null_key_rows,
        "rows_total": n_rows,
    }


def table_profile(
    con: sqlite3.Connection, table: str, spec: dict[str, Any]
) -> dict[str, Any]:
    cols = con.execute(f"PRAGMA table_info({qident(table)})").fetchall()
    names = [r[1] for r in cols]
    target_scope_where = "meet_code IN (1,3,4)" if "meet_code" in names else ""
    target_scope_sql = f" WHERE {target_scope_where}" if target_scope_where else ""
    source_rows = int(con.execute(f"SELECT COUNT(*) FROM {qident(table)}").fetchone()[0])
    target_rows = int(con.execute(f"SELECT COUNT(*) FROM {qident(table)}{target_scope_sql}").fetchone()[0])
    if spec["date"] not in names:
        date_profile: dict[str, Any] = {"date_column": None, "status": "no event-date column"}
    else:
        date_col = qident(spec["date"])
        first, last, nulls, distinct_days, after_cutoff = con.execute(
            f"SELECT MIN({date_col}), MAX({date_col}), "
            f"SUM(CASE WHEN {date_col} IS NULL THEN 1 ELSE 0 END), "
            f"COUNT(DISTINCT {date_col}), "
            f"SUM(CASE WHEN {date_col} > ? THEN 1 ELSE 0 END) "
            f"FROM {qident(table)}{target_scope_sql}",
            (TARGET_END,),
        ).fetchone()
        within = con.execute(
            f"SELECT SUM(CASE WHEN {date_col} IS NULL OR {date_col} <= ? THEN 1 ELSE 0 END) "
            f"FROM {qident(table)}{target_scope_sql}",
            (TARGET_END,),
        ).fetchone()[0]
        date_profile = {
            "date_column": spec["date"],
            "earliest_date": iso_day(first),
            "latest_date": iso_day(last),
            "distinct_date_values": int(distinct_days or 0),
            "rows_with_null_date": int(nulls or 0),
            "rows_on_or_before_target_cutoff": int(within or 0),
            "rows_after_target_cutoff": int(after_cutoff or 0),
        }
    meet_counts: dict[str, int] = {}
    if "meet_code" in names:
        for meet, count in con.execute(
            f"SELECT meet_code, COUNT(*) FROM {qident(table)} GROUP BY meet_code ORDER BY meet_code"
        ).fetchall():
            meet_counts["null" if meet is None else str(meet)] = int(count)
    return {
        "table": table,
        "rows": target_rows,
        "rows_in_target_scope": target_rows,
        "rows_in_source_file_all_meets": source_rows,
        "rows_excluded_outside_target_scope": source_rows - target_rows,
        "schema": [{"name": r[1], "type": r[2]} for r in cols],
        "date_coverage": date_profile,
        "rows_by_meet_code": meet_counts,
        "natural_key_candidate": spec.get("key"),
        "natural_key_profile": key_profile(con, table, spec["key"], target_scope_where)
        if spec.get("key") and set(spec["key"]).issubset(names)
        else None,
        "key_interpretation": spec.get("key_note"),
    }


def candidate_paths() -> list[dict[str, Any]]:
    found = []
    with CATALOG.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            match = PATH_RE.search(row["path"])
            if not match:
                continue
            family = match.group("family")
            year = int(match.group("year"))
            if family == "seoul":
                expected_meets = [1]
                kind = "race"
            elif family == "busan":
                expected_meets = [3]
                kind = "race"
            elif family == "yeongcheon":
                expected_meets = [4]
                kind = "race"
            else:
                expected_meets = [1, 3, 4]
                kind = "trial"
            found.append(
                {
                    "path": row["path"],
                    "absolute_path": str(ROOT / row["path"]),
                    "family": family,
                    "expected_year": year,
                    "expected_meets": expected_meets,
                    "kind": kind,
                    "bytes_from_catalog": int(row["bytes"]),
                }
            )
    return sorted(found, key=lambda x: (x["kind"], x["family"], x["expected_year"], x["path"]))


def keys_from_candidate(
    con: sqlite3.Connection, table: str, columns: list[str], year: int, cutoff: str
) -> tuple[set[tuple], dict[tuple, str | None], int]:
    select_cols = ", ".join(qident(c) for c in columns)
    out: set[tuple] = set()
    ids: dict[tuple, str | None] = {}
    out_of_year = 0
    for row in con.execute(f"SELECT {select_cols} FROM {qident(table)}"):
        values = list(row)
        meet = int(values[0]) if values[0] is not None else None
        day = iso_day(values[1])
        if day and day > cutoff:
            continue
        if not day or int(day[:4]) != year:
            out_of_year += 1
            continue
        if meet not in MEET_NAMES:
            continue
        key = (meet, day) + tuple(values[2:])
        out.add(key)
        if len(values) >= 5:
            ids[key] = canonical_id(values[4])
    return out, ids, out_of_year


def source_keys(con: sqlite3.Connection | duckdb.DuckDBPyConnection, kind: str, source: str) -> dict[str, set[tuple]]:
    result: dict[str, set[tuple]] = {"events": set(), "entries": set(), "entries_by_horse_id": set()}
    if kind == "race" and source == "operational_sqlite":
        rows = con.execute(
            "SELECT rc.kra_meet_code, r.race_date_local, r.race_number "
            "FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id "
            "WHERE rc.kra_meet_code IN (1,3,4) AND r.race_date_local <= ?",
            (TARGET_END,),
        ).fetchall()
        result["events"] = {(int(m), iso_day(d), int(n)) for m, d, n in rows if iso_day(d)}
        rows = con.execute(
            "SELECT rc.kra_meet_code, r.race_date_local, r.race_number, e.horse_number, h.kra_horse_id "
            "FROM race_entries e JOIN races r ON r.id=e.race_id "
            "JOIN racecourses rc ON rc.id=r.racecourse_id "
            "LEFT JOIN horses h ON h.id=e.horse_id "
            "WHERE rc.kra_meet_code IN (1,3,4) AND r.race_date_local <= ?",
            (TARGET_END,),
        ).fetchall()
        result["entries"] = {
            (int(m), iso_day(d), int(n), int(hn))
            for m, d, n, hn, _ in rows
            if iso_day(d) and hn is not None
        }
        result["entries_by_horse_id"] = {
            (int(m), iso_day(d), int(n), int(hn)): canonical_id(hr)
            for m, d, n, hn, hr in rows
            if iso_day(d) and hn is not None
        }
    elif kind == "race" and source == "historical_unified_duckdb":
        rows = con.execute(
            "SELECT canonical_meet, CAST(race_date AS VARCHAR), race_no "
            "FROM race WHERE canonical_meet IN (1,3,4) AND race_date <= ?",
            [TARGET_END],
        ).fetchall()
        result["events"] = {(int(m), iso_day(d), int(n)) for m, d, n in rows if iso_day(d)}
        rows = con.execute(
            "SELECT canonical_meet, CAST(race_date AS VARCHAR), race_no, chul_no, hr_no "
            "FROM entry_result WHERE canonical_meet IN (1,3,4) AND race_date <= ?",
            [TARGET_END],
        ).fetchall()
        result["entries"] = {
            (int(m), iso_day(d), int(n), int(hn))
            for m, d, n, hn, _ in rows
            if iso_day(d) and hn is not None
        }
        result["entries_by_horse_id"] = {
            (int(m), iso_day(d), int(n), int(hn)): canonical_id(hr)
            for m, d, n, hn, hr in rows
            if iso_day(d) and hn is not None
        }
    elif kind == "trial" and source == "operational_sqlite":
        rows = con.execute(
            "SELECT meet_code, trial_date_local, trial_race_number "
            "FROM running_trials WHERE meet_code IN (1,3,4) AND trial_date_local <= ?",
            (TARGET_END,),
        ).fetchall()
        result["events"] = {(int(m), iso_day(d), int(n)) for m, d, n in rows if iso_day(d)}
        rows = con.execute(
            "SELECT t.meet_code,t.trial_date_local,t.trial_race_number,x.horse_number,h.kra_horse_id "
            "FROM running_trial_results x JOIN running_trials t ON t.id=x.running_trial_id "
            "LEFT JOIN horses h ON h.id=x.horse_id "
            "WHERE t.meet_code IN (1,3,4) AND t.trial_date_local <= ?",
            (TARGET_END,),
        ).fetchall()
        result["entries"] = {
            (int(m), iso_day(d), int(n), int(hn))
            for m, d, n, hn, _ in rows
            if iso_day(d) and hn is not None
        }
        result["entries_by_horse_id"] = {
            (int(m), iso_day(d), int(n), int(hn)): canonical_id(hr)
            for m, d, n, hn, hr in rows
            if iso_day(d) and hn is not None
        }
    elif kind == "trial" and source == "historical_unified_duckdb":
        rows = con.execute(
            "SELECT DISTINCT canonical_meet, CAST(trial_date AS VARCHAR), trial_no "
            "FROM trial_entry WHERE canonical_meet IN (1,3,4) AND trial_date <= ?",
            [TARGET_END],
        ).fetchall()
        result["events"] = {(int(m), iso_day(d), int(n)) for m, d, n in rows if iso_day(d)}
        rows = con.execute(
            "SELECT canonical_meet, CAST(trial_date AS VARCHAR), trial_no, participant_no, hr_no "
            "FROM trial_entry WHERE canonical_meet IN (1,3,4) AND trial_date <= ?",
            [TARGET_END],
        ).fetchall()
        # participant_no and horse_number are distinct field names; do not treat
        # them as equivalent without a separate source-specific validation.
        result["entries"] = {
            (int(m), iso_day(d), int(n), int(pn))
            for m, d, n, pn, _ in rows
            if iso_day(d) and pn is not None
        }
        result["entries_by_horse_id"] = {
            (int(m), iso_day(d), int(n), canonical_id(hr))
            for m, d, n, _, hr in rows
            if iso_day(d) and canonical_id(hr)
        }
    return result


def key_compare(candidate: set[tuple], ref: set[tuple], prefix_count: int = 3) -> dict[str, Any]:
    left_only = candidate - ref
    right_only = ref - candidate
    return {
        "candidate_unique_keys": len(candidate),
        "reference_unique_keys_in_candidate_year_venue_scope": len(ref),
        "matched_keys": len(candidate & ref),
        "candidate_only_count": len(left_only),
        "reference_only_count": len(right_only),
        "candidate_only_sample": [list(x) for x in sorted(left_only)[:20]],
        "reference_only_sample": [list(x) for x in sorted(right_only)[:20]],
    }


def id_conflicts(candidate: dict[tuple, str | None], reference: dict[tuple, str | None]) -> dict[str, Any]:
    conflicts = [
        key + (candidate[key], reference[key])
        for key in candidate.keys() & reference.keys()
        if candidate[key] and reference[key] and candidate[key] != reference[key]
    ]
    missing_candidate = sum(1 for key in candidate.keys() & reference.keys() if not candidate[key])
    missing_reference = sum(1 for key in candidate.keys() & reference.keys() if not reference[key])
    return {
        "compared_shared_entry_keys": len(candidate.keys() & reference.keys()),
        "official_horse_id_conflicts": len(conflicts),
        "conflict_sample": [list(x) for x in sorted(conflicts)[:20]],
        "candidate_missing_horse_id_on_shared_key": missing_candidate,
        "reference_missing_horse_id_on_shared_key": missing_reference,
    }


def venue_scope(keys: set[tuple], meet: int, year: int) -> set[tuple]:
    return {
        key for key in keys
        if key[0] == meet and key[1] and int(key[1][:4]) == year
    }


def main() -> None:
    candidates = candidate_paths()
    expected_count = 31
    if len(candidates) != expected_count:
        raise AssertionError(f"Expected {expected_count} target score DBs, found {len(candidates)}")
    op_path = ROOT / "data/horse_racing.sqlite3"
    hist_path = ROOT / "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb"
    op = ro_sqlite(op_path)
    hist = duckdb.connect(str(hist_path), read_only=True)
    try:
        refs = {
            kind: {
                source: source_keys(con, kind, source)
                for source, con in (("operational_sqlite", op), ("historical_unified_duckdb", hist))
            }
            for kind in ("race", "trial")
        }
        file_results: list[dict[str, Any]] = []
        aggregate_candidate: dict[str, dict[str, set[tuple]]] = {
            "race": {"events": set(), "entries": set()},
            "trial": {"events": set(), "entries": set()},
        }
        aggregate_ids: dict[str, dict[str, dict[tuple, str | None]]] = {
            "race": {"entries": {}},
            "trial": {"entries": {}},
        }
        file_key_counts: dict[str, Counter] = defaultdict(Counter)

        for meta in candidates:
            path = ROOT / meta["path"]
            if not path.is_file():
                raise FileNotFoundError(path)
            con = ro_sqlite(path)
            try:
                tables = [r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()]
                kind = meta["kind"]
                specs = RACE_TABLES if kind == "race" else TRIAL_TABLES
                profiles = []
                for table, spec in specs.items():
                    if table in tables:
                        profiles.append(table_profile(con, table, spec))
                entry_table = "entry"
                event_table = "race" if kind == "race" else "trial"
                date_col = "race_date" if kind == "race" else "trial_date"
                event_no_col = "race_number" if kind == "race" else "trial_race_number"
                if event_table not in tables or entry_table not in tables:
                    raise AssertionError(f"{meta['path']} lacks expected {event_table}/{entry_table}")

                event_keys, _, event_off_year = keys_from_candidate(
                    con, event_table, ["meet_code", date_col, event_no_col], meta["expected_year"], TARGET_END
                )
                entry_key_columns = ["meet_code", date_col, event_no_col, "horse_number"]
                entry_keys, entry_ids, entry_off_year = keys_from_candidate(
                    con, entry_table, entry_key_columns, meta["expected_year"], TARGET_END
                )
                # Capture official horse IDs from each score entry row separately.
                id_col = "kra_horse_id"
                score_entry_ids: dict[tuple, str | None] = {}
                if id_col in [r[1] for r in con.execute(f"PRAGMA table_info({qident(entry_table)})")]:
                    for m, d, n, hn, hr in con.execute(
                        f"SELECT meet_code,{qident(date_col)},{qident(event_no_col)},horse_number,{qident(id_col)} "
                        f"FROM {qident(entry_table)}"
                    ):
                        day = iso_day(d)
                        if m in MEET_NAMES and day and int(day[:4]) == meta["expected_year"] and day <= TARGET_END and hn is not None:
                            score_entry_ids[(int(m), day, int(n), int(hn))] = canonical_id(hr)

                for k in event_keys:
                    file_key_counts[f"{kind}:events"][k] += 1
                    aggregate_candidate[kind]["events"].add(k)
                for k in entry_keys:
                    file_key_counts[f"{kind}:entries"][k] += 1
                    aggregate_candidate[kind]["entries"].add(k)
                aggregate_ids[kind]["entries"].update(score_entry_ids)

                comparisons: dict[str, Any] = {}
                for meet in meta["expected_meets"]:
                    comp: dict[str, Any] = {"meet": meet, "venue": MEET_NAMES[meet]}
                    candidate_events = {k for k in event_keys if k[0] == meet}
                    candidate_entries = {k for k in entry_keys if k[0] == meet}
                    for source, ref in refs[kind].items():
                        ref_events = venue_scope(ref["events"], meet, meta["expected_year"])
                        ref_entries = venue_scope(ref["entries"], meet, meta["expected_year"])
                        comp[source] = {
                            "events": key_compare(candidate_events, ref_events),
                            "entries": key_compare(candidate_entries, ref_entries),
                        }
                        if source == "operational_sqlite":
                            comp[source]["entry_horse_id_check"] = id_conflicts(
                                {k: score_entry_ids.get(k) for k in candidate_entries},
                                {k: ref["entries_by_horse_id"].get(k) for k in candidate_entries & ref_entries},
                            )
                    comparisons[str(meet)] = comp
                file_results.append(
                    {
                        **{k: v for k, v in meta.items() if k != "absolute_path"},
                        "tables_present": tables,
                        "table_profiles": profiles,
                        "off_expected_year_rows_in_race_table": event_off_year,
                        "off_expected_year_rows_in_entry_table": entry_off_year,
                        "natural_key_comparison": comparisons,
                        "interpretation": "Counts and key differences are descriptive; no source priority or truth ranking is assigned.",
                    }
                )
            finally:
                con.close()

        aggregate_comparison: dict[str, Any] = {}
        for kind in ("race", "trial"):
            aggregate_comparison[kind] = {}
            for meet in (1, 3, 4):
                candidate_events = {
                    k for k in aggregate_candidate[kind]["events"]
                    if k[0] == meet and MODEL_START <= k[1] <= TARGET_END
                }
                candidate_entries = {
                    k for k in aggregate_candidate[kind]["entries"]
                    if k[0] == meet and MODEL_START <= k[1] <= TARGET_END
                }
                if not candidate_events and not candidate_entries:
                    continue
                aggregate_comparison[kind][str(meet)] = {"venue": MEET_NAMES[meet], "references": {}}
                for source, ref in refs[kind].items():
                    ref_events = {
                        k for k in ref["events"]
                        if k[0] == meet and MODEL_START <= k[1] <= TARGET_END
                    }
                    ref_entries = {
                        k for k in ref["entries"]
                        if k[0] == meet and MODEL_START <= k[1] <= TARGET_END
                    }
                    block = {
                        "events": key_compare(candidate_events, ref_events),
                        "entries": key_compare(candidate_entries, ref_entries),
                    }
                    if source == "operational_sqlite":
                        block["entry_horse_id_check"] = id_conflicts(
                            {k: aggregate_ids[kind]["entries"].get(k) for k in candidate_entries},
                            {k: ref["entries_by_horse_id"].get(k) for k in candidate_entries & ref_entries},
                        )
                    if kind == "trial" and source == "historical_unified_duckdb":
                        block["entry_key_caveat"] = (
                            "The 4th component compares score horse_number to unified participant_no. "
                            "They are field-name analogues, not proven equivalent; horse-ID comparison is reported separately."
                        )
                        hist_id_keys = ref["entries_by_horse_id"]
                        cand_id_keys = {
                            (k[0], k[1], k[2], hid)
                            for k, hid in aggregate_ids[kind]["entries"].items()
                            if k[0] == meet and MODEL_START <= k[1] <= TARGET_END and hid
                        }
                        ref_id_scope = {
                            k for k in hist_id_keys
                            if k[0] == meet and MODEL_START <= k[1] <= TARGET_END
                        }
                        block["entry_horse_id_keys"] = key_compare(cand_id_keys, ref_id_scope)
                        block["entry_horse_id_counts"] = {
                            "score_keys_with_id": len(cand_id_keys),
                            "historical_keys_with_id": len(ref_id_scope),
                        }
                    aggregate_comparison[kind][str(meet)]["references"][source] = block

        unresolved_trial_groups: dict[tuple[int, str, int], dict[str, Any]] = {}
        for source_meet, trial_date, trial_no, participant_no, hr_no in hist.execute(
            "SELECT source_meet, CAST(trial_date AS VARCHAR), trial_no, participant_no, hr_no "
            "FROM trial_entry WHERE venue_resolution_status='unresolved_after_yeongcheon_split' "
            "AND source_meet IN (1,3,4) AND trial_date <= ?",
            [TARGET_END],
        ).fetchall():
            day = iso_day(trial_date)
            if not day or day < MODEL_START:
                continue
            group_key = (int(source_meet), day, int(trial_no))
            group = unresolved_trial_groups.setdefault(
                group_key, {"participants": set(), "horse_ids": {}}
            )
            if participant_no is not None:
                group["participants"].add(int(participant_no))
            group["horse_ids"][int(participant_no) if participant_no is not None else None] = canonical_id(hr_no)

        unresolved_trial_comparison = []
        for (source_meet, day, trial_no), group in sorted(unresolved_trial_groups.items()):
            # source_meet is only the value reported by the source; it does not
            # establish a physical venue after the Yeongcheon split.
            candidate_slots = {
                k for k in aggregate_candidate["trial"]["entries"]
                if k[0] == source_meet and k[1] == day and k[2] == trial_no
            }
            historical_slots = {
                (source_meet, day, trial_no, pn) for pn in group["participants"]
            }
            candidate_id_keys = {
                (k[0], k[1], k[2], canonical_id(hid))
                for k, hid in aggregate_ids["trial"]["entries"].items()
                if k[0] == source_meet and k[1] == day and k[2] == trial_no and hid
            }
            historical_id_keys = {
                (source_meet, day, trial_no, canonical_id(hid))
                for hid in group["horse_ids"].values() if hid
            }
            unresolved_trial_comparison.append(
                {
                    "source_meet": source_meet,
                    "event_date": day,
                    "trial_number": trial_no,
                    "historical_unresolved_participant_rows": len(group["participants"]),
                    "venue_assignment": "unresolved; source_meet is retained as reported and is not a confirmed venue",
                    "participant_slot_comparison": key_compare(candidate_slots, historical_slots),
                    "official_horse_id_comparison": key_compare(candidate_id_keys, historical_id_keys),
                }
            )

        cross_file_duplicates = {}
        for group, counts in file_key_counts.items():
            repeated = [k for k, n in counts.items() if n > 1]
            cross_file_duplicates[group] = {
                "unique_keys_across_files": len(counts),
                "keys_appearing_in_multiple_files": len(repeated),
                "duplicate_rows_across_files_beyond_one": sum(counts[k] - 1 for k in repeated),
                "sample": [list(k) for k in sorted(repeated)[:20]],
            }

        table_total_checks = {}
        excluded_rows_by_meet_code: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for fr in file_results:
            for tp in fr["table_profiles"]:
                key = f"{fr['path']}::{tp['table']}"
                kp = tp["natural_key_profile"]
                for meet_code, count in tp["rows_by_meet_code"].items():
                    if meet_code not in {"1", "3", "4"}:
                        excluded_rows_by_meet_code[tp["table"]][meet_code] += count
                table_total_checks[key] = {
                    "rows_in_target_scope": tp["rows"],
                    "rows_in_source_file_all_meets": tp["rows_in_source_file_all_meets"],
                    "unique_key_count": kp["unique_key_count"] if kp else None,
                    "duplicate_key_groups": kp["duplicate_key_groups"] if kp else None,
                    "duplicate_rows_beyond_one_per_key": kp["duplicate_rows_beyond_one_per_key"] if kp else None,
                }
                if kp and kp["unique_key_count"] + kp["duplicate_rows_beyond_one_per_key"] != kp["rows_total"]:
                    raise AssertionError(f"Natural-key count arithmetic failed: {key}")

        report = {
            "report_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": {
                "included": "Annual Seoul, Busan-Gyeongnam, Yeongcheon race score SQLite and running_trials score SQLite catalog candidates.",
                "included_meets": [1, 3, 4],
                "excluded": ["Jeju data rows (meet=2), including rows embedded in combined running_trials score files", "synthetic/experiment DBs", "non-score files and backups"],
                "source_row_cutoff": TARGET_END,
                "model_period_start": MODEL_START,
                "files_profiled": len(file_results),
                "files_expected": expected_count,
                "inputs_read_only": True,
                "source_priority_assigned": False,
            },
            "candidate_selection": {
                "catalog": str(CATALOG.relative_to(ROOT)),
                "path_pattern": "data/research/{seoul,busan,yeongcheon,running_trials}_YYYY_score_20260925/",
                "historical_provenance_and_completeness": "Not established by this structural profile.",
            },
            "reference_sources": {
                "operational_sqlite": "data/horse_racing.sqlite3",
                "historical_unified_duckdb": "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb",
                "coverage_note": "Comparisons use meet/date/race number and participant slot (horse_number or source analogue), with dates at/before target cutoff. No source is ranked as authoritative.",
                "trial_historical_slot_caveat": "historical_unified.trial_entry.participant_no is compared descriptively to candidate horse_number; equivalence is not assumed. Official horse-ID keys are also compared where present.",
                "operational_backup_note": "Separate root-maintained backup comparison reports 16 race and 180 entry keys in two older SQLite backups beyond the current operation DB. Those keys remain unadjudicated and are not treated here as confirmed source facts.",
            },
            "per_file_profiles_and_comparisons": file_results,
            "aggregate_2017_plus_comparisons": aggregate_comparison,
            "historical_unresolved_trial_source_meet_comparisons": unresolved_trial_comparison,
            "excluded_rows_by_meet_code_and_table": {
                table: dict(counts) for table, counts in excluded_rows_by_meet_code.items()
            },
            "cross_file_duplicate_natural_keys": cross_file_duplicates,
            "validation": {
                "candidate_file_count_matches_expected": len(file_results) == expected_count,
                "all_table_natural_key_count_arithmetic_passed": True,
                "all_candidate_db_connections_read_only": True,
                "reference_connections_read_only": True,
            },
        }
        tmp = OUTPUT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(OUTPUT)
    finally:
        op.close()
        hist.close()


if __name__ == "__main__":
    main()

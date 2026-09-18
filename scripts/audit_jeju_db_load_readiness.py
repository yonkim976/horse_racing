"""Read-only Jeju-native race/trial readiness audit for 200 m analysis.

The script reports recoverability; it does not write to the operational DB.
KRA describes Jeju 3C/4C positions as approximate, so differences using those
checkpoints are proxy sections and must never be labelled exact 200 m splits.
"""

from __future__ import annotations

import collections
import glob
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_200m_readiness_20260915"
RACE_IDS = ROOT / "data/research/jeju_confirmed_race_time_ids_20260914"
TRIALS = ROOT / "data/research/jeju_native_running_trial_links_20260915"


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ms(row: dict, key: str) -> int | None:
    try:
        value = float(row.get(key) or 0)
        return round(value * 1000) if value > 0 else None
    except (TypeError, ValueError):
        return None


def race_audit() -> tuple[dict, list[dict], list[dict], list[dict]]:
    race_keys = {
        (str(row["race_date"]), int(row["race_number"]))
        for path in (RACE_IDS / "linked_official_ids.jsonl", RACE_IDS / "unresolved_29.jsonl")
        for row in read(path)
    }
    all_rows = 0
    quarantined_keys = set()
    counts = collections.Counter()
    distances = collections.defaultdict(collections.Counter)
    annual = collections.defaultdict(collections.Counter)
    issues = []
    paths = sorted(glob.glob(str(ROOT / "data/raw/jeju_native_results/native_results_*.jsonl")) + glob.glob(str(ROOT / "data/research/jeju_race_time_official_ids_20260914/official_native_results_*.jsonl")))
    for path in paths:
        for row in read(Path(path)):
            all_rows += 1
            key = (str(row["rcDate"]), int(row["rcNo"]))
            if key not in race_keys:
                quarantined_keys.add(key)
                continue
            distance = int(row["rcDist"])
            year = key[0][:4]
            counters = (counts, distances[distance], annual[year])
            f, s, g3, g1, c3, c4 = (ms(row, field) for field in ("rcTime", "jeS1fTime", "jeG3fTime", "jeG1fTime", "je_3cTime", "je_4cTime"))
            for c in counters:
                c["rows"] += 1
                c["positive_finish"] += f is not None
                c["s1_g3_g1"] += all(x is not None for x in (s, g3, g1))
                c["all_s1_3c_4c_g3_g1_finish"] += all(x is not None for x in (f, s, c3, c4, g3, g1))
            status = None
            if distance == 400 and all(x is not None for x in (f, s, g1)):
                status = "full_exact_200m" if abs(f-s-g1) <= 200 else "inconsistent"
            elif all(x is not None for x in (f, s, g3, g1, c3, c4)):
                g3_cumulative, g1_cumulative = f-g3, f-g1
                early_order_ok = abs(c3-s) <= 100 if distance == 800 else c3 > s
                web_chain_ok = (
                    abs(c3-g3_cumulative) <= 200
                    and early_order_ok and c4 > c3 and g1_cumulative > c4
                    and f > g1_cumulative
                )
                status = "web_style_segment_usable" if web_chain_ok else "inconsistent"
            if status:
                for c in counters:
                    if status == "inconsistent":
                        c["segment_checkpoint_inconsistent"] += 1
                    else:
                        c[status] += 1
                        c["web_style_segment_usable"] += status == "full_exact_200m"
                        c["corner_proxy_200m"] += status == "web_style_segment_usable" and distance in (800,1000)
            if status == "inconsistent":
                issues.append({"race_date": key[0], "race_number": key[1], "horse_number": row["chulNo"], "hrNo": str(row["hrNo"]), "distance_m": distance, "issue": "segment_checkpoint_inconsistent", "source_path": str(Path(path).relative_to(ROOT))})
    assert counts["rows"] == 90892, counts["rows"]
    summary = {"confirmed_native_races": len(race_keys), "confirmed_native_rows": counts["rows"], "all_archived_explicit_je_rows": all_rows, "quarantined_no_positive_result_races": len(quarantined_keys), "quarantined_no_positive_result_rows": all_rows-counts["rows"], **dict(counts)}
    return summary, [{"distance_m": d, **dict(v)} for d,v in sorted(distances.items())], [{"year": y, **dict(v)} for y,v in sorted(annual.items())], issues


def trial_audit() -> tuple[dict, list[dict], list[dict], list[dict]]:
    linked = read(TRIALS / "linked_native_trials_final.jsonl")
    unresolved = read(TRIALS / "unresolved_trials_final.jsonl")
    supplement = {(r["trial_date"],r["trial_race_number"],r["horse_number"]):r for r in read(TRIALS / "older_trial_section_audit_native_only.jsonl")}
    counts = collections.Counter()
    annual = collections.defaultdict(collections.Counter)
    distances = collections.defaultdict(collections.Counter)
    issues = []
    for row in linked:
        year = row["trial_date"][:4]
        distance = int(row["distance_m"])
        counters = (counts, annual[year], distances[distance])
        v = row["trial_result"]
        f, s, g3, g1, c3, c4 = (v.get(k) for k in ("finish_time_ms", "s1f_ms", "g3f_ms", "g1f_ms", "corner_3_ms", "corner_4_ms"))
        for c in counters:
            c["linked_rows"] += 1
            c["positive_finish"] += bool(f and f > 0)
            c["text_all_section_fields"] += all(x and x > 0 for x in (f,s,g3,g1,c3,c4))
        key = (row["trial_date"],row["trial_race_number"],row["horse_number"])
        extra = supplement.get(key)
        if extra and extra["status"] == "four_corner_proxy_segments_consistent":
            for c in counters:
                c["official_web_corner_proxy_200m"] += 1
                c["web_style_segment_usable"] += 1
            continue
        if not all(x and x > 0 for x in (f,s,g3,g1,c3,c4)):
            continue
        g3_cumulative, g1_cumulative = f-g3, f-g1
        early_order_ok = abs(c3-s) <= 100 if distance == 800 else c3 > s
        if abs(c3-g3_cumulative) <= 200 and early_order_ok and c4 > c3 and g1_cumulative > c4 and f > g1_cumulative:
            for c in counters:
                c["text_web_style_segment_usable"] += 1
                c["web_style_segment_usable"] += 1
                c["text_corner_proxy_200m"] += distance == 800
        else:
            issues.append({"trial_date":row["trial_date"],"trial_race_number":row["trial_race_number"],"horse_number":row["horse_number"],"hrNo":row["hrNo"],"issue":"200m_checkpoint_inconsistent","source_path":row["text_source"]})
    summary = {"linked_native_rows":len(linked),"unresolved_rows":len(unresolved),"full_exact_200m":0,**dict(counts),"official_web_supplement_rows":len(supplement),"official_web_corner_proxy_valid":sum(r["status"]=="four_corner_proxy_segments_consistent" for r in supplement.values())}
    return summary, [{"distance_m":d,**dict(v)} for d,v in sorted(distances.items())], [{"year":y,**dict(v)} for y,v in sorted(annual.items())],issues


def db_markers() -> dict:
    conn=sqlite3.connect(f"file:{ROOT / 'data/horse_racing.sqlite3'}?mode=ro",uri=True)
    race_columns={r[1] for r in conn.execute("PRAGMA table_info(races)")}
    trial_columns={r[1] for r in conn.execute("PRAGMA table_info(running_trial_results)")}
    data={"races_has_explicit_breed_column": bool(race_columns & {"breed","horse_type","native_jeju_status"}),"trial_results_has_explicit_breed_column": bool(trial_columns & {"breed","horse_type","native_jeju_status"}),"meet2_trial_rows":conn.execute("SELECT COUNT(*) FROM running_trial_results r JOIN running_trials t ON t.id=r.running_trial_id WHERE t.meet_code=2").fetchone()[0],"meet2_trial_origin_null_rows":conn.execute("SELECT COUNT(*) FROM running_trial_results r JOIN running_trials t ON t.id=r.running_trial_id WHERE t.meet_code=2 AND r.origin_country IS NULL").fetchone()[0],"meet2_races":conn.execute("SELECT COUNT(*) FROM races WHERE racecourse_id=2").fetchone()[0]}
    conn.close()
    return data


def main() -> dict:
    OUT.mkdir(parents=True,exist_ok=True)
    race,race_dist,race_year,race_issues=race_audit()
    trial,trial_dist,trial_year,trial_issues=trial_audit()
    db=db_markers()
    summary={"race":race,"trial":trial,"db_marker_audit":db,"race_200m_quality_issues":len(race_issues),"trial_200m_quality_issues":len(trial_issues)}
    checks={
        "race_distance_rows_reconcile": sum(r["rows"] for r in race_dist)==race["rows"],
        "race_year_rows_reconcile": sum(r["rows"] for r in race_year)==race["rows"],
        "race_archive_rows_reconcile": race["rows"]+race["quarantined_no_positive_result_rows"]==race["all_archived_explicit_je_rows"],
        "race_exact_only_400m": all(r.get("full_exact_200m",0)==0 for r in race_dist if r["distance_m"]!=400),
        "race_proxy_only_800_1000m": all(r.get("corner_proxy_200m",0)==0 for r in race_dist if r["distance_m"] not in (800,1000)),
        "trial_distance_rows_reconcile": sum(r["linked_rows"] for r in trial_dist)==trial["linked_rows"],
        "trial_year_rows_reconcile": sum(r["linked_rows"] for r in trial_year)==trial["linked_rows"],
        "trial_candidate_rows_reconcile": trial["linked_rows"]+trial["unresolved_rows"]==15688,
        "trial_no_exact_200m": trial["full_exact_200m"]==0,
        "trial_web_supplement_reconcile": trial["official_web_supplement_rows"]==3544 and trial["official_web_corner_proxy_valid"]==trial["official_web_corner_proxy_200m"],
        "trial_web_style_reconcile": trial["web_style_segment_usable"]==trial["official_web_corner_proxy_200m"]+trial["text_web_style_segment_usable"],
        "race_issues_reconcile": race["segment_checkpoint_inconsistent"]==len(race_issues),
    }
    validation={"passed":all(checks.values()),"checks":checks}
    assert validation["passed"], validation
    for filename,obj in (("summary.json",summary),("validation.json",validation),("race_by_distance.json",race_dist),("race_by_year.json",race_year),("trial_by_distance.json",trial_dist),("trial_by_year.json",trial_year),("race_200m_quality_issues.json",race_issues),("trial_200m_quality_issues.json",trial_issues)):
        write(OUT/filename,obj)
    return summary


if __name__=="__main__":
    print(json.dumps(main(),ensure_ascii=False,indent=2))

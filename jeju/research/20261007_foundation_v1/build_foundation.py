"""Jeju foundation audit and interpretable historical scorecards. Read-only DB."""

import argparse
import copy
import hashlib
import json
import math
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUTPUT = HERE
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
ARCHIVE = ROOT / "jeju/research/20260929_api_detail_sources/raw/full_year_sections_passing/20260929T143902.196014Z"
TARGET_DATE = "2026-09-19"
TIME_FIELDS = ["s1f", "c1", "c2", "c3", "c4", "g3f", "g1f"]
ORDER_FIELDS = ["s1f", "c1", "c2", "c3", "c4", "g1f"]
BODY = re.compile(r"^(\d+)(?:\(([+-]?\d*)\))?$")
MOISTURE = re.compile(r"\((\d+(?:\.\d+)?)%\)")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def save(name, value):
    with (OUTPUT / name).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def body(value):
    match = BODY.fullmatch(str(value or "").strip())
    if not match or int(match[1]) <= 0:
        return None, None
    delta = int(match[2]) if match[2] not in (None, "") else None
    return int(match[1]), delta


def moisture(value):
    match = MOISTURE.search(str(value or ""))
    number = float(match[1]) if match else None
    return number if number is not None and 0 < number <= 100 else None


def key(row):
    return row["race_date"], row["meet_code"], row["race_number"]


def normal(row):
    pos = row["finish_position"]
    return pos is not None and 1 <= pos <= 89


def started(row):
    return normal(row) or row["finish_position"] in (91, 92)


def timed(row):
    return normal(row) and positive(row["finish_time_seconds"]) and positive(row["race_distance_m"])


def summarize_field(population, field, valid, level="runner"):
    present = [r for r in population if valid(r.get(field))]
    values = [r[field] for r in present]
    numeric = [float(v) for v in values if isinstance(v, (int, float))]
    return {
        "field": field, "denominator": len(population), "unit_of_observation": level,
        "usable_count": len(present), "unusable_or_missing_count": len(population) - len(present),
        "unusable_or_missing_rate": (len(population) - len(present)) / len(population) if population else None,
        "first_usable_date": min((r["race_date"] for r in present), default=None),
        "last_usable_date": max((r["race_date"] for r in present), default=None),
        "numeric_min": min(numeric, default=None), "numeric_median": statistics.median(numeric) if numeric else None,
        "numeric_max": max(numeric, default=None),
    }


def metric(value, source, unit, formula):
    return {"value": value, "n": len(source), "source_api_record_ids": [r["api_record_id"] for r in source],
            "unit": unit, "formula": formula}


def scorecard(target, history):
    """Only past rows affect horse metrics. Target supplies ID, date and distance."""
    cutoff = (date.fromisoformat(target["race_date"]) - timedelta(days=2)).isoformat()
    past = sorted((r for r in history if r["horse_id"] == target["horse_id"] and r["race_date"] <= cutoff),
                  key=lambda r: (r["race_date"], r["race_number"], r["api_record_id"]))
    starts = [r for r in past if started(r)]
    usable = [r for r in past if timed(r)]
    same = [r for r in usable if r["race_distance_m"] == target["race_distance_m"]]
    recent = same[-5:]
    prior = recent[:-1][-3:]
    best_window = [r for r in same if r["race_date"] >= (date.fromisoformat(cutoff) - timedelta(days=364)).isoformat()]
    ordered_best = sorted(best_window, key=lambda r: (r["finish_time_seconds"], r["race_date"], r["api_record_id"]))
    last = recent[-1:] or []
    last_start = starts[-1:] or []
    weights = [r for r in starts if positive(r.get("body_weight_kg_parsed"))]
    burden = [r for r in starts if positive(r.get("carried_weight_kg"))]
    ages = [r for r in starts if positive(r.get("age_at_race_raw"))]
    times = [r["finish_time_seconds"] for r in recent]
    m = {
        "observed_start_count": metric(len(starts), starts, "observed rows", "count(normal finish or source code 91/92); incomplete lifetime coverage"),
        "days_since_last_observed_start": metric((date.fromisoformat(target["race_date"]) - date.fromisoformat(last_start[0]["race_date"])).days if last_start else None, last_start, "days", "T - latest observed start date <= T-2"),
        "valid_time_count_all_distances": metric(len(usable), usable, "observed rows", "count(normal finish, positive total time and distance); no pooling of their times"),
        "same_distance_valid_time_count": metric(len(same), same, "observed rows", "count(usable total times at exact target distance)"),
        "same_distance_last_time_s": metric(last[0]["finish_time_seconds"] if last else None, last, "seconds", "last usable exact-distance total time"),
        "same_distance_recent5_mean_s": metric(statistics.mean(times) if times else None, recent, "seconds", "arithmetic mean of at most 5 latest usable exact-distance times"),
        "same_distance_recent5_std_s": metric(statistics.pstdev(times) if len(times) >= 2 else None, recent, "seconds", "population std, NULL if n<2"),
        "same_distance_latest_minus_prior3_mean_s": metric(last[0]["finish_time_seconds"] - statistics.mean(r["finish_time_seconds"] for r in prior) if last and prior else None, prior + last if prior else [], "seconds", "latest - mean(up to 3 immediately preceding usable same-distance records); negative=faster raw time"),
        "same_distance_best365_s": metric(ordered_best[0]["finish_time_seconds"] if ordered_best else None, best_window, "seconds", "minimum usable exact-distance time in [cutoff-364 days, cutoff]"),
        "same_distance_second_best_gap365_s": metric(ordered_best[1]["finish_time_seconds"] - ordered_best[0]["finish_time_seconds"] if len(ordered_best) >= 2 else None, ordered_best[:2], "seconds", "second-smallest time minus smallest; descriptive, no repeatability claim"),
        "last_historical_body_weight_kg": metric(weights[-1]["body_weight_kg_parsed"] if weights else None, weights[-1:], "kg", "last parsed positive body weight on a past started race; not target-day weight"),
        "last_minus_previous_body_weight_kg": metric(weights[-1]["body_weight_kg_parsed"] - weights[-2]["body_weight_kg_parsed"] if len(weights) >= 2 else None, weights[-2:], "kg", "difference of two latest valid historical body weights"),
        "last_historical_carried_weight_kg": metric(burden[-1]["carried_weight_kg"] if burden else None, burden[-1:], "kg", "latest positive carried weight on a past started race"),
        "last_observed_event_age": metric(ages[-1]["age_at_race_raw"] if ages else None, ages[-1:], "source age", "latest valid raw age on an observed past started race; not necessarily age at target"),
    }
    # Modern same-distance section observations only; do not reconstruct geometry.
    modern_same = [r for r in same if r["race_date"] >= "2017-01-01"]
    for point in ("s1f", "g3f", "g1f"):
        chosen = [r for r in modern_same if positive(r.get(point + "_time_seconds"))
                  and r.get(point + "_time_status") in ("api_positive_unreviewed", "website_corrected")
                  and not r.get("section_internal_conflict_order_count")
                  and not r.get("section_internal_conflict_group_count")][-5:]
        m[point + "_recent5_mean_s"] = metric(statistics.mean(r[point + "_time_seconds"] for r in chosen) if chosen else None,
                                                   chosen, "seconds", "up to 5 positive quality-selected exact-distance times since 2017; conflict rows conservatively excluded; no track adjustment")
    early = [r for r in modern_same if positive(r.get("s1f_order")) and r["s1f_order"] <= r["stored_started_field_size"] and r["stored_started_field_size"] > 1 and not r.get("partial_candidate_race")][-5:]
    gain = [r for r in early if positive(r.get("g1f_order")) and r["g1f_order"] <= r["stored_started_field_size"]]
    m["early_rank_fraction_recent5"] = metric(statistics.mean((r["s1f_order"] - 1) / (r["stored_started_field_size"] - 1) for r in early) if early else None, early, "fraction", "mean((S1F order-1)/(stored started field size-1)); 0=front, no style threshold")
    m["early_to_g1f_order_gain_recent5"] = metric(statistics.mean(r["s1f_order"] - r["g1f_order"] for r in gain) if gain else None, gain, "positions", "mean(S1F order - G1F order); descriptive position change, not acceleration")
    for value in m.values():
        assert all(r["race_date"] <= cutoff for r in past if r["api_record_id"] in value["source_api_record_ids"])
    witness = ordered_best[0] if ordered_best else None
    return {
        "horse_id": target["horse_id"], "target_date": target["race_date"], "target_race_number": target["race_number"],
        "target_distance_m": target["race_distance_m"], "history_cutoff_date_inclusive": cutoff,
        "availability_status": "event-date T-2 assumption; historical first publication/correction timestamps not established",
        "history_coverage_status": "observed archive only; absence does not prove debut or zero lifetime starts",
        "metrics": m,
        "best_record_context": {k: witness.get(k) for k in ("api_record_id", "race_date", "race_distance_m", "rank_class_raw", "carried_weight_kg", "body_weight_kg_parsed", "track_raw", "finish_time_seconds")} if witness else None,
        "last_usable_same_distance_date": last[0]["race_date"] if last else None,
        "history_lineage": [{k: r.get(k) for k in ("api_record_id", "race_date", "race_number", "horse_id", "race_distance_m", "finish_position", "finish_time_seconds", "carried_weight_kg", "body_weight_raw", "body_weight_kg_parsed", "track_raw", "age_at_race_raw", "s1f_time_seconds", "s1f_time_status", "g3f_time_seconds", "g3f_time_status", "g1f_time_seconds", "g1f_time_status", "s1f_order", "s1f_order_status", "g1f_order", "g1f_order_status", "api4_3_payload_sha256")} for r in past],
    }


def main():
    before = DB.stat()
    db_hash_before = sha(DB)
    connection = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    columns = ["api_record_id", "race_date", "meet_code", "race_number", "horse_number", "horse_id", "horse_name", "age_2026", "race_distance_m", "rank_class_raw", "finish_position", "finish_time_seconds", "carried_weight_kg", "body_weight_raw", "track_raw", "age_at_race_raw", "api303_tempo_raw", "api4_3_payload_sha256", "section_internal_conflict_order_count", "section_internal_conflict_group_count"]
    columns += [f"{point}_time_{suffix}" for point in TIME_FIELDS for suffix in ("seconds", "status")]
    columns += [f"{point}_{suffix}" for point in ORDER_FIELDS for suffix in ("order", "order_status", "group", "group_status")]
    # All dynamic identifiers are fixed constants in this script, not input text.
    sql = 'SELECT ' + ','.join('"' + name + '"' for name in columns) + ' FROM jeju_race_postrace_sections_quality_2026'
    print("Reading the quality-selected race history once", flush=True)
    history = [dict(row) for row in connection.execute(sql)]
    print(f"Read {len(history)} candidate rows", flush=True)
    full = defaultdict(list)
    for row in connection.execute("SELECT race_date,meet_code,race_number,finish_position,horse_id FROM race_result_rows"):
        full[(row[0], row[1], row[2])].append(dict(row))
    candidate_counts = Counter(key(row) for row in history)
    for row in history:
        row["body_weight_kg_parsed"], row["body_delta_raw_parsed"] = body(row["body_weight_raw"])
        row["moisture_percent_parsed"] = moisture(row["track_raw"])
        row["stored_started_field_size"] = sum(started(r) for r in full[key(row)])
        row["partial_candidate_race"] = candidate_counts[key(row)] < len(full[key(row)])
    definitions = [("race_distance_m", positive), ("finish_time_seconds", positive), ("rank_class_raw", lambda v: bool(v)),
                   ("carried_weight_kg", positive), ("body_weight_kg_parsed", positive), ("body_delta_raw_parsed", lambda v: v is not None),
                   ("horse_number", positive), ("track_raw", lambda v: bool(v)), ("moisture_percent_parsed", positive),
                   ("age_at_race_raw", positive), ("api303_tempo_raw", lambda v: v is not None and str(v).strip() not in ("", "0", "-"))]
    definitions += [(f"{point}_time_seconds", positive) for point in TIME_FIELDS]
    definitions += [(f"{point}_order", positive) for point in ORDER_FIELDS]
    definitions += [(f"{point}_group", lambda v: v is not None and str(v).strip() not in ("", "0", "-")) for point in ORDER_FIELDS]
    pools = {"all_candidate_rows": history, "2017_plus_candidate_rows": [r for r in history if r["race_date"] >= "2017-01-01"],
             "2017_plus_normal_positive_finish_rows": [r for r in history if r["race_date"] >= "2017-01-01" and timed(r)]}
    fields = {pool: [summarize_field(values, name, check) for name, check in definitions] for pool, values in pools.items()}
    save("field_inventory.json", fields)
    by_race = defaultdict(list)
    for row in pools["2017_plus_candidate_rows"]:
        by_race[key(row)].append(row)
    label_races = [race_key for race_key, rows in by_race.items()
                   if all(timed(r) for r in rows)
                   and all(sum(r["finish_position"] == rank for r in rows) == 1 for rank in (1, 2, 3))]
    save("provisional_label_scope.json", {
        "status": "screening_only_not_final_train_set",
        "rule": "All candidate rows have normal numeric finish 1..89 and positive total time; exactly one each rank 1,2,3. Completeness vs declarations and all boundary ties not adjudicated. Postrace scope, not deploy-time runner selection.",
        "races": len(label_races), "by_year": dict(sorted(Counter(k[0][:4] for k in label_races).items())),
    })
    distances = []
    for distance in sorted({r["race_distance_m"] for r in pools["2017_plus_candidate_rows"] if r["race_distance_m"] is not None}):
        sample = [r for r in pools["2017_plus_candidate_rows"] if r["race_distance_m"] == distance]
        distances.append({"distance_m": distance, "candidate_rows": len(sample), "races": len({key(r) for r in sample}),
                          "normal_positive_time_rows": sum(timed(r) for r in sample), "first_date": min(r["race_date"] for r in sample), "last_date": max(r["race_date"] for r in sample),
                          "section_availability": {point: {"positive_count": sum(positive(r[point + "_time_seconds"]) for r in sample),
                                                       "status_counts": dict(Counter(r[point + "_time_status"] for r in sample))} for point in TIME_FIELDS}})
    save("distance_inventory.json", distances)
    print("Field and distance inventories saved", flush=True)
    # API6 is a separate archived race-level source, not a horse-level DB table.
    manifest = json.loads((ARCHIVE / "run_manifest.json").read_text())
    section_rows = {}
    section_sources = []
    for part in manifest["datasets"]["detail_section"]["yearly"]:
        for page in part["pages"]:
            path = (ARCHIVE / page["response_file"]).resolve()
            assert path.is_relative_to(ARCHIVE.resolve())
            assert sha(path) == page["response_sha256"]
            payload = json.loads(path.read_text())
            raw_rows = payload["response"]["body"]["items"]["item"]
            raw_rows = raw_rows if isinstance(raw_rows, list) else [raw_rows]
            assert len(raw_rows) == page["actual_page_rows"]
            section_sources.append({"path":str(path.relative_to(ROOT)), "sha256":page["response_sha256"], "rows":len(raw_rows)})
            for raw in raw_rows:
                event = str(raw["rcDate"])
                section_rows[(f"{event[:4]}-{event[4:6]}-{event[6:]}", 2, int(raw["rcNo"]))] = raw
    grid = []
    for distance in sorted({x["distance_m"] for x in distances}):
        raw_sample = [(k, v) for k, v in section_rows.items() if k in candidate_counts and k[0] >= "2017-01-01" and v["rcDist"] == distance]
        layouts = Counter(tuple(v.get(f"dist_{n}f") for n in range(1, 10)) for _, v in raw_sample)
        grid.append({"distance_m":distance, "race_rows":len(raw_sample), "distance_grid_layouts":[{"dist_1f_through_9f":list(layout), "races":count} for layout,count in layouts.most_common()]})
    save("api6_distance_grids.json", grid)
    trials = [dict(r) for r in connection.execute("SELECT t.*,a.payload_json FROM api_explicit_jeju_trial_rows t JOIN api_records a USING(api_record_id)")]
    trial_fields = ("rcTime", "rcTimeS1f", "rcTime_1c", "rcTime_2c", "rcTime_3c", "rcTime_4c", "rcTimeG3f", "rcTimeG1f", "wgHr", "wgBudam")
    trial_inventory = {"rows":len(trials), "horses":len({r["horse_id"] for r in trials}),
                       "first_date":min(r["trial_date"] for r in trials), "last_date":max(r["trial_date"] for r in trials), "fields":[]}
    for name in trial_fields:
        present = [r for r in trials if positive(json.loads(r["payload_json"]).get(name))]
        trial_inventory["fields"].append({"api_field":name, "positive_rows":len(present), "unusable_or_missing_rate":1-len(present)/len(trials), "first_date":min((r["trial_date"] for r in present),default=None),"last_date":max((r["trial_date"] for r in present),default=None)})
    trial_inventory["explicit_distance_field_rows"] = sum("rcDist" in json.loads(r["payload_json"]) for r in trials)
    save("trial_inventory.json", trial_inventory)
    by_horse = defaultdict(list)
    for row in history:
        by_horse[row["horse_id"]].append(row)
    targets = [r for r in history if r["race_date"] == TARGET_DATE and r["race_number"] in (1, 2, 6)]
    target_counts = {}
    for row in targets:
        cutoff = (date.fromisoformat(TARGET_DATE)-timedelta(days=2)).isoformat()
        target_counts[row["horse_id"]] = sum(started(h) and h["race_date"] <= cutoff for h in by_horse[row["horse_id"]])
    chosen = []
    for race_number in (1, 2, 6):
        entrants = sorted((r for r in targets if r["race_number"] == race_number), key=lambda r:(target_counts[r["horse_id"]], r["horse_id"]))
        chosen.extend((entrants[0], entrants[-1]))
    cards = []
    for target in chosen:
        card = scorecard(target, by_horse[target["horse_id"]])
        card["display_horse_name_current"] = target["horse_name"]
        card["display_age_2026_current_profile"] = target["age_2026"]
        card["display_age_2026_policy"] = "display only: 2026 minus latest profile birth year; do not use to represent historical event age"
        card["target_context_reconstructed_not_verified_at_T_minus_2"] = {"distance_m":target["race_distance_m"], "grade_raw":target["rank_class_raw"], "carried_weight_kg":target["carried_weight_kg"], "horse_number":target["horse_number"], "stored_result_row_count":candidate_counts[key(target)]}
        observed_trials = [r for r in trials if r["horse_id"] == target["horse_id"] and r["trial_date"] <= card["history_cutoff_date_inclusive"]]
        observed_trials.sort(key=lambda r:(r["trial_date"],r["trial_number"]))
        card["trial_observation_only"] = {"observed_rows":len(observed_trials), "latest_date":observed_trials[-1]["trial_date"] if observed_trials else None,
                                          "latest_time_seconds":observed_trials[-1]["finish_time_seconds"] if observed_trials and positive(observed_trials[-1]["finish_time_seconds"]) else None,
                                          "same_distance_comparable":False, "reason":"API20 payload has no explicit distance; do not pool trial time with race times"}
        cards.append(card)
    save("example_scorecards.json", cards)
    print("Six scorecards and API6 source audit saved", flush=True)
    # Material temporal and missing-data checks, independent of target outcomes.
    probe = chosen[0]
    first = scorecard(probe, by_horse[probe["horse_id"]])
    altered_target = copy.deepcopy(probe)
    altered_target.update(finish_position=1, finish_time_seconds=1, body_weight_raw="999(+99)", track_raw="不明")
    assert scorecard(altered_target, by_horse[probe["horse_id"]]) == first
    future = dict(probe)
    future.update(api_record_id=-100, race_date="2026-09-18", finish_time_seconds=1, finish_position=1)
    assert scorecard(probe, by_horse[probe["horse_id"]] + [future]) == first
    boundary = dict(probe)
    boundary.update(api_record_id=-101, race_date="2026-09-17", finish_time_seconds=70, finish_position=2)
    assert scorecard(probe, [boundary])["metrics"]["same_distance_last_time_s"]["value"] == 70
    empty = scorecard(probe, [])
    assert empty["metrics"]["same_distance_last_time_s"]["value"] is None
    assert empty["metrics"]["observed_start_count"]["value"] == 0
    other = dict(boundary, race_distance_m=1610 if probe["race_distance_m"]!=1610 else 900)
    assert scorecard(probe,[other])["metrics"]["same_distance_last_time_s"]["value"] is None
    assert body("0()") == (None,None) and body("260(+8)") == (260,8) and body("260()") == (260,None)
    held_order = sum(r[p+"_order_status"] == "unresolved_official_internal_conflict" for r in history for p in ORDER_FIELDS)
    held_group_occurrences = sum(r[p+"_group_status"] == "unresolved_official_internal_conflict" for r in history for p in ORDER_FIELDS)
    assert held_order == 70 and held_group_occurrences == 194
    assert all(r[p+"_order"] is None for r in history for p in ORDER_FIELDS if r[p+"_order_status"] == "unresolved_official_internal_conflict")
    assert all(r[p+"_group"] is None for r in history for p in ORDER_FIELDS if r[p+"_group_status"] == "unresolved_official_internal_conflict")
    race_summary = []
    for pool_name, values in pools.items():
        race_summary.append({"pool":pool_name,"rows":len(values),"races":len({key(r) for r in values}),"first_date":min(r["race_date"] for r in values),"last_date":max(r["race_date"] for r in values)})
    connection.close()
    after = DB.stat()
    db_hash_after = sha(DB)
    assert db_hash_before == db_hash_after and (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    save("source_audit.json", {"database":str(DB.relative_to(ROOT)),"sha256":db_hash_before,"size_bytes":before.st_size,
                              "view":"jeju_race_postrace_sections_quality_2026","pools":race_summary,"api6_pages":section_sources,
                              "query_columns":columns,"example_selection":"For races 1,2,6 on 2026-09-19, minimum and maximum prior observed starts; ties broken by horse_id; target outcomes ignored",
                              "target_context_availability":"Reconstructed from results; historical declaration at T-2 unverified; not yet an executable live predictor",
                              "quality_order_hold_fields":held_order,"quality_group_hold_runner_points":held_group_occurrences,
                              "database_unchanged":True,"model_training_performed":False,"thoroughbred_assets_modified":False})
    save("verification.json", {"status":"passed","checks":["target outcome/body/track invariance","T-1 row excluded","T-2 row included","no history remains NULL for ability","exact-distance isolation","body zero and missing delta handling","70 held orders and 194 held runner/group points remain NULL","DB hash/size/mtime unchanged"],"example_count":len(cards)})
    print(json.dumps({"status":"passed","cards":len(cards),"database_unchanged":True},ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", help="New subdirectory inside this research folder; existing outputs are never overwritten")
    args = parser.parse_args()
    if args.output_dir:
        OUTPUT = (HERE / args.output_dir).resolve()
        if not OUTPUT.is_relative_to(HERE.resolve()) or OUTPUT == HERE.resolve():
            parser.error("output directory must be a new child directory of this research folder")
        OUTPUT.mkdir(parents=True, exist_ok=False)
    main()

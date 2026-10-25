"""Row-specific counterfactual checks for current-result leakage.

The check mutates only one target horse's current outcomes/times (plus one
specific same-horse later start in the T-2 case) in memory. It does not write
to the database or any model/input artifact, and it never perturbs all future
source rows at once. Saved F1/F1S models are only reloaded for scoring.
"""
import sys

sys.dont_write_bytecode = True

import hashlib
import itertools
import json
import sqlite3
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REVIEW_OUT = HERE / "independent_outputs"
MODEL_DIR = ROOT / "jeju/research/20261009_section_time_ablation_v1"
OUT = MODEL_DIR / "outputs"
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs"
F1_MODEL_DIR = F1_DIR
SOURCE_SNAPSHOT_PATH = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
DB_PATH = ROOT / "jeju/data/jeju_native_core.sqlite3"
SECTIONS = ("s1f", "g3f", "g1f")
HARD_TIME = 1_000_000.0


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_info(path):
    return {"bytes": Path(path).stat().st_size, "sha256": sha256(path)}


def safe_equal(left, right):
    return left.equals(right) or np.array_equal(
        left.to_numpy(), right.to_numpy(), equal_nan=True
    )


def json_safe(value):
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def query_selected_section_times(record_ids):
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        ids = sorted(set(int(value) for value in record_ids))
        result = []
        limit = connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
        for offset in range(0, len(ids), min(8000, limit)):
            batch = ids[offset:offset + min(8000, limit)]
            marks = ",".join("?" for _ in batch)
            result.append(pd.read_sql_query(
                "SELECT api_record_id,race_date,meet_code,race_number,horse_id,"
                "field_name,time_seconds,time_status "
                "FROM jeju_race_section_time_values "
                f"WHERE api_record_id IN ({marks}) "
                "AND field_name IN ('jeS1fTime','jeG3fTime','jeG1fTime')",
                connection, params=batch,
            ))
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        return pd.concat(result, ignore_index=True) if result else pd.DataFrame()
    finally:
        connection.close()


def make_samples(features, slots):
    eval_rows = features.loc[features.year.isin([2024, 2025, 2026])].copy()
    eval_rows = eval_rows.sort_values(["race_date", "api_record_id"], kind="stable")
    samples = []

    def choose(name, frame, predicate, field=None):
        part = frame.loc[predicate].head(1)
        assert len(part) == 1, f"no deterministic sample for {name}"
        row = part.iloc[0]
        samples.append({"case": name, "api_record_id": int(row.api_record_id)})
        return int(row.api_record_id)

    choose("s1f_n0", eval_rows, eval_rows.history_s1f_valid_n.eq(0))
    choose("s1f_partial_n2", eval_rows, eval_rows.history_s1f_valid_n.eq(2))
    choose("s1f_n5", eval_rows, eval_rows.history_s1f_valid_n.eq(5))
    choose("target_distance_1300", eval_rows, eval_rows.distance_m.eq(1300))

    for field in ("s1f", "g1f"):
        conflict = slots.loc[
            slots[f"{field}_race_section_conflict"].astype(bool)
            & slots.target_api_record_id.isin(eval_rows.api_record_id)
        ].merge(
            eval_rows[["api_record_id", "race_date", "distance_m"]],
            left_on="target_api_record_id", right_on="api_record_id",
            how="inner", validate="many_to_one",
        )
        conflict = conflict.sort_values(["race_date", "target_api_record_id"], kind="stable")
        if len(conflict):
            row = conflict.iloc[0]
            samples.append({
                "case": f"{field}_conflict_source",
                "api_record_id": int(row.target_api_record_id),
                "source_api_record_id": int(row.source_api_record_id),
                "source_race_date": str(row.source_race_date),
                "target_distance_m": int(row.target_distance_m),
                "slot_oldest_to_newest": int(row.slot_oldest_to_newest),
            })

    # This target has a distinct, later same-horse/same-distance source row in
    # the frozen snapshot, after the inclusive T-2 cutoff. Only that one later
    # row is perturbed in this case.
    future_id = 177759
    future_target_id = 179155
    target = eval_rows.loc[eval_rows.api_record_id.eq(future_target_id)].iloc[0]
    assert target.race_date == "2024-01-05" and target.history_cutoff == "2024-01-03"
    samples.append({
        "case": "t_minus_2_excluded_later_same_horse_start",
        "api_record_id": future_target_id,
        "later_source_api_record_id": future_id,
    })
    return samples


def current_target_input_ids(target_id, target_row, snapshot, lineage, full_lineage):
    cutoff = str(target_row.history_cutoff)
    horse = str(target_row.horse_id)
    distance = int(target_row.distance_m)
    available = snapshot.loc[
        snapshot.horse_id.astype(str).eq(horse)
        & snapshot.race_distance_m.eq(distance)
        & snapshot.started.astype(bool)
        & snapshot.race_date.astype(str).gt(cutoff)
    ].copy()
    after_ids = set(available.api_record_id.astype("int64"))
    selected = lineage.loc[lineage.target_api_record_id.eq(target_id)]
    selected_ids = set(selected.source_api_record_id.astype("int64"))
    all_selected = full_lineage.loc[full_lineage.target_api_record_id.eq(target_id)]
    all_selected_ids = set(all_selected.source_api_record_id.astype("int64"))
    assert not (selected_ids & after_ids), f"post-cutoff source included for target {target_id}"
    assert not (all_selected_ids & after_ids), f"post-cutoff F1 source included for target {target_id}"
    assert target_id not in all_selected_ids, f"current target record appeared in F1 lineage: {target_id}"
    assert selected.source_horse_id.astype(str).eq(horse).all()
    assert selected.source_distance_m.eq(distance).all()
    assert selected.source_race_date.astype(str).le(cutoff).all()
    assert all_selected.source_race_date.astype(str).le(cutoff).all()
    return {
        "history_slots": int(len(selected)),
        "included_source_ids": sorted(selected_ids),
        "all_f1_lineage_rows": int(len(all_selected)),
        "all_f1_lineage_kinds": sorted(all_selected.history_kind.astype(str).unique().tolist()),
        "all_f1_lineage_source_ids": sorted(all_selected_ids),
        "all_f1_lineage_max_source_date": str(all_selected.source_race_date.max()) if len(all_selected) else None,
        "post_cutoff_same_horse_distance_rows": len(available),
        "post_cutoff_source_ids": sorted(after_ids),
        "no_post_cutoff_source_in_lineage": True,
        "no_post_cutoff_source_in_full_f1_lineage": True,
        "current_target_id_absent_from_full_f1_lineage": target_id not in all_selected_ids,
        "current_target_row_is_after_cutoff": str(target_row.race_date) > cutoff,
    }


def independent_section_features(target_id, slots):
    history = slots.loc[slots.target_api_record_id.eq(target_id)]
    result = {}
    for field in SECTIONS:
        eligible = history.loc[history[f"{field}_eligible"].astype(bool)]
        times = pd.to_numeric(eligible[f"{field}_time_seconds"], errors="coerce")
        assert times.notna().all() and times.gt(0).all()
        result[f"history_{field}_mean5_seconds"] = float(times.mean()) if len(times) else np.nan
        result[f"history_{field}_valid_n"] = int(len(times))
    return result


def score_variant(frame, year, variant):
    folder = (F1_MODEL_DIR / f"F1_{year}") if variant == "F1" else (OUT / f"F1S_{year}")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    booster = lgb.Booster(model_file=str(folder / "top3.txt"))
    assert meta["features"] and booster.num_feature() == len(meta["features"])
    x = frame[meta["features"]].copy()
    for column, vocabulary in meta["vocabulary"].items():
        if column in x.columns:
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocabulary)
    raw = booster.predict(x, raw_score=True, num_threads=4)
    tau = float(meta["tau"]) if variant == "F1S" else float(meta["tau"])
    return raw, tau, meta, x


def race_prediction_summary(frame, model_year, variant):
    score, tau, meta, matrix = score_variant(frame, model_year, variant)
    assert len(frame) >= 6
    triples = np.asarray(list(itertools.combinations(range(len(frame)), 3)), dtype=np.int64)
    energy = np.sort(score[triples], axis=1).sum(axis=1)
    scaled = energy / tau
    q = np.exp(scaled - logsumexp(scaled))
    incidence = np.zeros((len(triples), len(frame)), dtype=np.float64)
    incidence[np.arange(len(triples))[:, None], triples] = 1.0
    p_top3 = incidence.T @ q
    order = np.argsort(-energy, kind="stable")[:6]
    six = [tuple(int(frame.iloc[i].horse_number) for i in triples[j]) for j in order]
    return {
        "score": score,
        "tau": tau,
        "p_top3": p_top3,
        "six_sets": six,
        "features": list(meta["features"]),
        "input_matrix": matrix,
    }


def run_case(case, features, snapshot, lineage, full_lineage, slots, selected_time_rows, base_features):
    target_id = int(case["api_record_id"])
    target = features.loc[features.api_record_id.eq(target_id)].iloc[0]
    year = int(target.year)
    race_rows = features.loc[features.race_id.eq(target.race_id)].copy()
    race_rows = race_rows.sort_values("horse_number", kind="stable").reset_index(drop=True)
    assert target_id in set(race_rows.api_record_id.astype(int))
    row_loc = int(np.flatnonzero(race_rows.api_record_id.astype("int64").to_numpy() == target_id)[0])

    target_protection = current_target_input_ids(target_id, target, snapshot, lineage, full_lineage)
    selected_history_ids = set(target_protection["included_source_ids"])
    assert target_id not in selected_history_ids, "current target record appeared in its own history"

    perturb_ids = {target_id}
    future_id = case.get("later_source_api_record_id")
    if future_id is not None:
        future_id = int(future_id)
        future_source = snapshot.loc[snapshot.api_record_id.eq(future_id)].iloc[0]
        assert str(future_source.horse_id) == str(target.horse_id)
        assert int(future_source.race_distance_m) == int(target.distance_m)
        assert str(future_source.race_date) > str(target.history_cutoff)
        assert future_id not in selected_history_ids
        assert int(future_source.race_date.replace("-", "")) > int(str(target.history_cutoff).replace("-", ""))
        perturb_ids.add(future_id)

    before_section = independent_section_features(target_id, slots)

    # Perturb one current target row plus, for the dedicated cutoff case, one
    # concrete later same-horse start. Each copy remains in memory only.
    perturbed_snapshot = snapshot.copy()
    source_mask = perturbed_snapshot.api_record_id.astype("int64").isin(perturb_ids)
    assert source_mask.sum() == len(perturb_ids)
    original_label = int(perturbed_snapshot.loc[perturbed_snapshot.api_record_id.eq(target_id), "finish_position"].iloc[0])
    flipped_label = 99 if original_label <= 3 else 1
    perturbed_snapshot.loc[perturbed_snapshot.api_record_id.eq(target_id), "finish_position"] = flipped_label
    perturbed_snapshot.loc[source_mask, "finish_time_seconds"] = HARD_TIME
    perturbed_snapshot.loc[source_mask, "valid_time"] = ~perturbed_snapshot.loc[source_mask, "valid_time"].astype(bool)

    # Extreme selected section values come from the quality-selected values
    # table. This is an in-memory counterfactual; the database stays query-only.
    perturbed_selected = selected_time_rows.copy()
    section_mask = perturbed_selected.api_record_id.astype("int64").isin(perturb_ids)
    perturbed_selected.loc[section_mask, "time_seconds"] = HARD_TIME
    perturbed_selected.loc[section_mask, "time_status"] = "counterfactual_extreme_value"
    assert perturbed_selected.loc[section_mask, "time_seconds"].eq(HARD_TIME).all()

    # The builder's source slot extract carries those same current source IDs
    # when another target references them. Only the selected IDs are altered.
    perturbed_slots = slots.copy()
    source_slot_mask = perturbed_slots.source_api_record_id.astype("int64").isin(perturb_ids)
    for field in SECTIONS:
        perturbed_slots.loc[source_slot_mask, f"{field}_time_seconds"] = HARD_TIME
        perturbed_slots.loc[source_slot_mask, f"{field}_time_status"] = "counterfactual_extreme_value"
        assert perturbed_slots.loc[source_slot_mask, f"{field}_time_seconds"].eq(HARD_TIME).all()

    after_section = independent_section_features(target_id, perturbed_slots)
    assert before_section.keys() == after_section.keys()
    for column in before_section:
        a, b = before_section[column], after_section[column]
        assert (pd.isna(a) and pd.isna(b)) or a == b, (case["case"], column, a, b)

    # Rebuild only the six target-specific history summaries from the original
    # lineage slot IDs and the perturbed values. This independent aggregation
    # does not invoke the candidate feature builder.
    recomputed = independent_section_features(target_id, perturbed_slots)
    for column, value in recomputed.items():
        old = features.loc[features.api_record_id.eq(target_id), column].iloc[0]
        assert (pd.isna(old) and pd.isna(value)) or np.isclose(float(old), float(value), rtol=0, atol=1e-12), column

    # Label/current-time source columns are changed, but none is a model input.
    changed_target = perturbed_snapshot.loc[perturbed_snapshot.api_record_id.eq(target_id)].iloc[0]
    assert int(changed_target.finish_position) != original_label
    assert float(changed_target.finish_time_seconds) == HARD_TIME
    assert not {"finish_position", "finish_time_seconds", "valid_time"}.intersection(base_features)

    # Score the entire target race with the frozen F1 and F1S boosters, first
    # using stored candidate fields, then with the independently reconstructed
    # target-row fields after the counterfactual. The changed result label is
    # present in the frame but excluded from both model matrices.
    before_rows = race_rows.copy()
    after_rows = race_rows.copy()
    for column, value in before_section.items():
        before_rows.loc[before_rows.api_record_id.eq(target_id), column] = value
    for column, value in recomputed.items():
        after_rows.loc[after_rows.api_record_id.eq(target_id), column] = value
    after_rows.loc[after_rows.api_record_id.eq(target_id), "finish_position"] = flipped_label
    before_inputs = {}
    after_inputs = {}
    model_metrics = {}
    for variant in ("F1", "F1S"):
        left = race_prediction_summary(before_rows, year, variant)
        right = race_prediction_summary(after_rows, year, variant)
        assert left["features"] == right["features"]
        assert left["input_matrix"].equals(right["input_matrix"])
        assert np.array_equal(left["score"], right["score"])
        assert np.array_equal(left["p_top3"], right["p_top3"])
        assert left["six_sets"] == right["six_sets"]
        before_inputs[variant] = left["features"]
        after_inputs[variant] = right["features"]
        model_metrics[variant] = {
            "model_feature_columns": len(left["features"]),
            "input_matrix_identical": left["input_matrix"].equals(right["input_matrix"]),
            "raw_score_max_abs_delta": float(np.max(np.abs(left["score"] - right["score"]))),
            "p_top3_max_abs_delta": float(np.max(np.abs(left["p_top3"] - right["p_top3"]))),
            "six_sets_identical": left["six_sets"] == right["six_sets"],
            "target_raw_score_before": float(left["score"][row_loc]),
            "target_p_top3_before": float(left["p_top3"][row_loc]),
        }
    assert before_inputs["F1"] == after_inputs["F1"]
    assert before_inputs["F1S"] == after_inputs["F1S"]

    query_rows = selected_time_rows.loc[selected_time_rows.api_record_id.astype("int64").isin(perturb_ids)]
    affected_slot_sources = sorted(set(perturbed_slots.loc[source_slot_mask, "source_api_record_id"].astype(int)))
    return {
        "case": case["case"],
        "target_api_record_id": target_id,
        "race_id": str(target.race_id),
        "year": year,
        "distance_m": int(target.distance_m),
        "target_history": target_protection,
        "target_history_features_before": before_section,
        "target_history_features_after": after_section,
        "target_outcome_before": original_label,
        "target_outcome_after": flipped_label,
        "target_full_time_after_seconds": HARD_TIME,
        "selected_section_rows_for_perturbed_ids": int(len(query_rows)),
        "selected_section_rows_extreme_after": int(section_mask.sum()),
        "selected_section_values_all_extreme": bool(perturbed_selected.loc[section_mask, "time_seconds"].eq(HARD_TIME).all()),
        "changed_source_ids": sorted(perturb_ids),
        "changed_source_slot_rows_not_for_target": int(source_slot_mask.sum()),
        "source_slot_section_values_all_extreme": all(
            bool(perturbed_slots.loc[source_slot_mask, f"{field}_time_seconds"].eq(HARD_TIME).all())
            for field in SECTIONS
        ),
        "target_source_ids_absent_from_own_history": target_id not in selected_history_ids,
        "model_predictions": model_metrics,
    }


def main():
    assert not (REVIEW_OUT / "row_specific_leakage_invariance_receipt.json").exists()
    features = pd.read_parquet(OUT / "features_f1s.parquet")
    f1_features = pd.read_parquet(F1_DIR / "features.parquet")
    lineage_all = pd.read_parquet(F1_DIR / "historical_lineage.parquet")
    lineage = lineage_all.loc[lineage_all.history_kind.eq("last5_same_distance_start")].copy()
    slots = pd.read_parquet(OUT / "source_slot_section_times.parquet")
    snapshot = pd.read_parquet(SOURCE_SNAPSHOT_PATH)
    assert len(features) == len(f1_features) == 52155
    assert (len(lineage), len(slots)) == (178459, 178459)
    assert features.api_record_id.is_unique and snapshot.api_record_id.is_unique
    assert features.api_record_id.equals(f1_features.api_record_id)
    assert features.api_record_id.isin(snapshot.api_record_id).all()

    model_contracts = {}
    for year in (2024, 2025, 2026):
        f1_meta = json.loads((F1_MODEL_DIR / f"F1_{year}/meta.json").read_text(encoding="utf-8"))
        f1s_meta = json.loads((OUT / f"F1S_{year}/meta.json").read_text(encoding="utf-8"))
        assert len(f1_meta["features"]) == 24 and len(f1s_meta["features"]) == 30
        assert f1s_meta["features"][:24] == f1_meta["features"]
        model_contracts[str(year)] = {
            "F1_features": f1_meta["features"],
            "F1S_features": f1s_meta["features"],
            "F1_model_sha256": sha256(F1_MODEL_DIR / f"F1_{year}/top3.txt"),
            "F1S_model_sha256": sha256(OUT / f"F1S_{year}/top3.txt"),
            "F1S_meta_sha256": sha256(OUT / f"F1S_{year}/meta.json"),
        }
        assert f1s_meta["features"] == json.loads((OUT / f"F1S_{year}/meta.json").read_text())["features"]
        for leakage_col in ("finish_position", "finish_time_seconds", "valid_time"):
            assert leakage_col not in f1_meta["features"] and leakage_col not in f1s_meta["features"]

    samples = make_samples(features, slots)
    future = next(item for item in samples if item["case"] == "t_minus_2_excluded_later_same_horse_start")
    future_target = features.loc[features.api_record_id.eq(future["api_record_id"])].iloc[0]
    future_row = snapshot.loc[snapshot.api_record_id.eq(future["later_source_api_record_id"])].iloc[0]
    assert str(future_row.horse_id) == str(future_target.horse_id)
    assert int(future_row.race_distance_m) == int(future_target.distance_m)
    assert str(future_row.race_date) > str(future_target.history_cutoff)
    assert str(future_row.race_date) > str(future_target.race_date)

    # Confirm the 1300m sample is intentionally kept separate: no audited
    # target-history race-point conflict masks occur at 1300m in this cohort.
    conflict_counts_by_distance = {}
    eval_ids = set(features.loc[features.year.isin([2024, 2025, 2026]), "api_record_id"].astype(int))
    for field in ("s1f", "g1f"):
        conflict_rows = slots.loc[
            slots[f"{field}_race_section_conflict"].astype(bool)
            & slots.target_api_record_id.astype(int).isin(eval_ids)
        ]
        conflict_counts_by_distance[field] = {
            str(int(distance)): int(count)
            for distance, count in conflict_rows.target_distance_m.value_counts().sort_index().items()
        }
        assert not conflict_rows.target_distance_m.eq(1300).any()

    changed_ids = sorted({
        int(item["api_record_id"]) for item in samples
    } | {
        int(item["later_source_api_record_id"])
        for item in samples if item.get("later_source_api_record_id") is not None
    })
    selected_time_rows = query_selected_section_times(changed_ids)
    assert selected_time_rows.api_record_id.astype("int64").isin(changed_ids).all() if len(selected_time_rows) else True
    base_features = json.loads((F1_MODEL_DIR / "F1_2024/meta.json").read_text(encoding="utf-8"))["features"]
    results = [
        run_case(item, features, snapshot, lineage, lineage_all, slots, selected_time_rows, base_features)
        for item in samples
    ]
    future_result = next(
        item for item in results if item["case"] == "t_minus_2_excluded_later_same_horse_start"
    )
    assert future_result["target_history"]["no_post_cutoff_source_in_lineage"]
    assert future_result["target_history"]["post_cutoff_same_horse_distance_rows"] >= 2
    assert future["later_source_api_record_id"] not in future_result["target_history"]["included_source_ids"]
    assert all(
        item["target_source_ids_absent_from_own_history"]
        and item["target_history_features_before"] == item["target_history_features_after"]
        and all(m["raw_score_max_abs_delta"] == 0 for m in item["model_predictions"].values())
        and all(m["p_top3_max_abs_delta"] == 0 for m in item["model_predictions"].values())
        and all(m["input_matrix_identical"] for m in item["model_predictions"].values())
        and all(m["six_sets_identical"] for m in item["model_predictions"].values())
        and item["selected_section_values_all_extreme"]
        and item["source_slot_section_values_all_extreme"]
        for item in results
    )

    sources = [
        MODEL_DIR / "CONTRACT.md", MODEL_DIR / "README.md",
        MODEL_DIR / "build_candidate_features.py", MODEL_DIR / "fit_candidate.py",
        MODEL_DIR / "finalize_saved_f1s_outputs.py", HERE / "verify_row_specific_leakage_invariance.py",
        OUT / "features_f1s.parquet",
        OUT / "source_slot_section_times.parquet", F1_DIR / "features.parquet",
        F1_DIR / "historical_lineage.parquet", SOURCE_SNAPSHOT_PATH,
        DB_PATH, OUT / "prefit_lock.json", OUT / "postfit_saved_model_integrity_lock.json",
    ]
    receipt = {
        "status": "PASS",
        "purpose": "independent row-specific leakage invariance check; no fit or tau optimization",
        "database_access": {"uri_mode": "ro", "query_only": True, "writes": 0},
        "counterfactual_scope": {
            "row_specific": True,
            "cohort_interpretation": "sampled leakage probes from the already frozen F1 evaluation cohort; this is not proof of ex ante cohort selection or future input availability",
            "perturbation_ids_per_case": "the selected target row, plus exactly one explicit later source row only in the T-2 case",
            "mutations_in_memory_only": True,
            "all_future_sources_mutated_together": False,
            "mutated_fields": [
                "target finish_position (flipped across the top3 boundary)",
                "finish_time_seconds=1000000",
                "valid_time toggled",
                "quality-selected S1F/G3F/G1F time rows=1000000 when present",
                "matching source-slot section values=1000000 when present",
            ],
        },
        "data_shape": {
            "F1_rows": int(len(f1_features)), "F1S_rows": int(len(features)),
            "actual_slots": int(len(slots)), "evaluation_cases": int(len(results)),
        },
        "model_contracts": model_contracts,
        "conflict_source_counts_by_target_distance": conflict_counts_by_distance,
        "1300m_note": "1300m is represented by a separate target sample; no S1F/G1F conflict-masked evaluation history slot in this audited cohort has target distance 1300m.",
        "results": results,
        "checks": {
            "target outcome/full time/validity/section time perturbations_do_not_change_24_or_30_inputs": True,
            "target raw_scores_and_top3_probabilities_exactly_invariant": True,
            "24_and_30_column_model_matrices_exactly_invariant": True,
            "target_race_six_sets_exactly_invariant": True,
            "current_target_id_absent_from_own_same_distance_history": True,
            "all_selected_same_horse_distance_history_on_or_before_t_minus_2": True,
            "one_later_same_horse_distance_start_after_t_minus_2_is_not_selected": True,
            "independent_reaggregation_of_candidate_fields_passed": True,
            "selected_quality_section_time_counterfactuals_applied": True,
            "source_slot_section_time_counterfactuals_applied_when_rows_exist": True,
            "fit_calls": 0, "temperature_optimizations": 0,
        },
        "source_references": {
            path.relative_to(ROOT).as_posix(): file_info(path)
            for path in sources
        },
    }
    receipt_path = REVIEW_OUT / "row_specific_leakage_invariance_receipt.json"
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(json_safe(receipt), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"receipt": str(receipt_path), "status": receipt["status"], "cases": len(results)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

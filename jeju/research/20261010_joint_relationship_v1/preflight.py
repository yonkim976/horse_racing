"""Outcome-free source, roster, time, symmetry, and degeneracy preflight."""
from __future__ import annotations

from itertools import combinations
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import joint_model as jm


def inspect_roster(group: pd.DataFrame) -> dict:
    n = len(group)
    pair_rank = int(np.linalg.matrix_rank(np.eye(n)[[i for i, _ in combinations(range(n), 2)]] +
                                          np.eye(n)[[j for _, j in combinations(range(n), 2)]]))
    pair_count = math.comb(n, 2)
    triple_count = math.comb(n, 3)
    if n < 5 or triple_count < 6 or pair_rank != n or pair_count - pair_rank <= 0:
        raise AssertionError(
            f"unsupported roster/projection rank at {group.race_id.iloc[0]}: "
            f"N={n}, C(N,3)={triple_count}, pair_rank={pair_rank}"
        )
    return {"race_id": str(group.race_id.iloc[0]), "field_n": n,
            "pair_count": pair_count, "pair_rank": pair_rank,
            "pair_residual_rank": pair_count - pair_rank,
            "triple_count": triple_count}


def assert_history_cutoff(frame: pd.DataFrame) -> None:
    cutoff = pd.to_datetime(frame.history_cutoff, errors="raise").dt.normalize()
    race_date = pd.to_datetime(frame.race_date, errors="raise").dt.normalize()
    expected = race_date - pd.Timedelta(days=2)
    if not cutoff.equals(expected):
        different = int((cutoff != expected).sum())
        raise AssertionError(f"feature history_cutoff differs from race_date-2d on {different} rows")
    latest = pd.to_datetime(frame.latest_history_date, errors="raise").dt.normalize()
    has_history = latest.notna()
    future = has_history & latest.gt(cutoff)
    if future.any():
        raise AssertionError(
            f"latest_history_date exceeds T-2 history_cutoff on {int(future.sum())} rows"
        )


def pair_rms_from_h1(h1_groups: list[pd.DataFrame], scaler: dict) -> tuple[np.ndarray, list[dict]]:
    race_means = []
    raw_records = []
    for group in h1_groups:
        values, valid = jm.transform_runner(group, scaler)
        pairs, phi = jm.pair_basis(values, valid)
        residual, _ = jm.project_pair_basis(pairs, phi, len(group))
        race_means.append(np.mean(np.square(residual), axis=0))
        raw_records.append({"group": group, "values": values, "valid": valid,
                            "pairs": pairs, "phi": phi, "residual": residual})
    rms = np.sqrt(np.mean(np.vstack(race_means), axis=0))
    return rms, raw_records


def check_residual_structure(groups: list[pd.DataFrame], scaler: dict,
                             pair_rms: np.ndarray) -> dict:
    max_row_sum = 0.0
    max_a_transpose_g = 0.0
    cleaned_race_columns = 0
    pair_symmetry_checks = 0
    for group in groups:
        values, valid = jm.transform_runner(group, scaler)
        pairs, phi = jm.pair_basis(values, valid)
        # Pair order invariance is checked directly on fixed source columns.
        if len(pairs):
            i, j = pairs[0]
            swapped = jm.pair_basis(values[[j, i]], valid[[j, i]])[1][0]
            forward = jm.pair_basis(values[[i, j]], valid[[i, j]])[1][0]
            if not np.array_equal(swapped, forward):
                raise AssertionError("pair feature changes when the two runners are swapped")
            pair_symmetry_checks += 1
        residual, _ = jm.project_pair_basis(pairs, phi, len(group))
        normalized = np.zeros_like(residual)
        active = pair_rms > jm.DEGENERATE_TOL
        normalized[:, active] = residual[:, active] / pair_rms[active]
        cleaned, preclean_max = jm.clean_degenerate_residual(normalized)
        cleaned_race_columns += int(np.sum(preclean_max <= jm.DEGENERATE_TOL))
        if not len(group):
            continue
        n = len(group)
        row_sum = np.zeros((n, cleaned.shape[1]), dtype=np.float64)
        for row, (i, j) in enumerate(pairs):
            row_sum[i] += cleaned[row]
            row_sum[j] += cleaned[row]
        max_row_sum = max(max_row_sum, float(np.max(np.abs(row_sum))))
        triples = jm.triple_indices(n)
        triple_relation = jm.triple_relation_features(pairs, cleaned, triples)
        incidence = np.zeros((len(triples), n), dtype=np.float64)
        incidence[np.arange(len(triples))[:, None], triples] = 1.0
        max_a_transpose_g = max(max_a_transpose_g,
                                float(np.max(np.abs(incidence.T @ triple_relation))))
    if max_row_sum > jm.PROJECTION_TOL or max_a_transpose_g > jm.PROJECTION_TOL:
        raise AssertionError("pair/triple unary projection identity failed")
    if pair_symmetry_checks != len(groups):
        raise AssertionError("not every race received a pair-order symmetry check")
    return {
        "race_groups": len(groups),
        "max_pair_residual_row_sum_abs": max_row_sum,
        "max_A_transpose_G_abs": max_a_transpose_g,
        "race_feature_columns_cleaned_to_zero": cleaned_race_columns,
        "pair_swap_checks": pair_symmetry_checks,
    }


def baseline_ticket_parity(eval_frames: list[pd.DataFrame]) -> dict:
    stored = pd.read_csv(jm.confined(jm.BASELINE_SIX_PATH), dtype={"race_id": "string"})
    stored = stored.loc[stored.variant.eq("F1_STYLE6"), ["race_id", "selection_rank", "numbers"]]
    stored["selection_rank"] = stored.selection_rank.astype(int)
    stored = stored.sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
    if len(stored) != jm.EXPECTED_COHORT["races"] * 6:
        raise AssertionError(f"saved baseline six has unexpected rows: {len(stored)}")

    recreated = []
    for frame in eval_frames:
        for group in jm.race_groups(frame):
            scores = group.score.to_numpy(float)
            triples = jm.triple_indices(len(group))
            energies = jm.baseline_energies(scores, triples)
            order = jm.stable_top_indices(energies, k=6)
            numbers = jm.top_ticket_numbers(group, triples, order)
            for rank, ticket in enumerate(numbers, start=1):
                recreated.append({"race_id": str(group.race_id.iloc[0]),
                                  "selection_rank": rank, "numbers": ticket})
    actual = pd.DataFrame(recreated).sort_values(
        ["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
    actual = actual.astype({"race_id": "string", "selection_rank": "int64", "numbers": "string"})
    if len(actual) != len(stored):
        raise AssertionError("recreated baseline six row count differs from saved reference")
    stored = stored.astype({"race_id": "string", "selection_rank": "int64", "numbers": "string"})
    if not actual.equals(stored):
        mismatch = int((actual != stored).any(axis=1).sum())
        raise AssertionError(f"baseline saved-ticket parity failed: {mismatch} rows differ")
    return {"passed": True, "saved_rows": int(len(stored)),
            "recreated_rows": int(len(actual)), "exact_fields": ["race_id", "selection_rank", "numbers"]}


def saved_runner_reference_contract(eval_frames: list[pd.DataFrame]) -> dict:
    saved = pd.read_parquet(jm.confined(jm.SAVED_STYLE_RUNNER_PATH))
    required = {"api_record_id", "race_id", "race_date", "year", "horse_number",
                "variant", "p_top3", "y"}
    if not required.issubset(saved.columns):
        raise AssertionError(f"saved runner reference misses fields: {sorted(required - set(saved.columns))}")
    style = saved.loc[saved.variant.eq("F1_STYLE6")].copy()
    ids = pd.concat([frame.api_record_id.astype("int64") for frame in eval_frames], ignore_index=True)
    if len(style) != jm.EXPECTED_COHORT["runner_rows"] or style.api_record_id.duplicated().any():
        raise AssertionError("saved F1_STYLE6 runner reference has unexpected row count/duplicate IDs")
    if set(style.api_record_id.astype("int64")) != set(ids):
        raise AssertionError("saved F1_STYLE6 runner reference does not cover evaluation runners")
    probabilities = pd.to_numeric(style.p_top3, errors="raise").to_numpy(float)
    labels = pd.to_numeric(style.y, errors="raise").to_numpy(float)
    if (not np.isfinite(probabilities).all() or (probabilities < 0).any() or
            (probabilities > 1).any() or not np.isin(labels, [0, 1]).all()):
        raise AssertionError("saved F1_STYLE6 runner reference has invalid schema values")
    if style.race_id.nunique() != jm.EXPECTED_COHORT["races"]:
        raise AssertionError("saved F1_STYLE6 runner reference race count differs")
    return {"passed": True, "schema_columns": list(saved.columns),
            "variants": {str(key): int(value) for key, value in saved.variant.value_counts().sort_index().items()},
            "f1_style6_rows": int(len(style)),
            "f1_style6_races": int(style.race_id.nunique()),
            "key_coverage_exact": True, "outcome_metrics_computed": False}


def main() -> None:
    if jm.sha256(jm.HERE / "PLAN.md") != jm.EXPECTED_PLAN_SHA256:
        raise AssertionError("PLAN.md does not match the approved frozen plan hash")
    if any((jm.OUT / name).exists() for name in ("source_lock.json", "preflight_receipt.json")):
        raise FileExistsError("preflight outputs already exist; refusing overwrite")
    before = jm.lock_sources()
    features = pd.read_parquet(jm.confined(jm.FEATURES_PATH))
    if len(features) != 52155 or features.api_record_id.duplicated().any():
        raise AssertionError("locked style feature table has unexpected size or duplicate API IDs")
    if not set(jm.STYLE_FEATURES).issubset(features.columns):
        raise AssertionError("locked feature table lacks fixed model inputs")

    fold_results = []
    roster_support = []
    eval_frames = []
    eval_races = 0
    eval_rows = 0
    eval_days = set()
    eval_race_ids = set()
    eval_triples = 0
    h1_triples = 0
    h2_triples = 0
    for year in jm.YEARS:
        folder = jm.STYLE_OUT / f"F1_STYLE6_{year}"
        meta = jm.load_json(folder / "meta.json")
        if int(meta["evaluation_year"]) != year:
            raise AssertionError(f"wrong evaluation year in metadata: {year}")
        calibration = jm.join_scores(
            features, folder / "calibration_scores.parquet", year - 1,
            int(meta["calibration_rows"]), role="calibration")
        evaluation = jm.join_scores(
            features, folder / "evaluation_scores.parquet", year,
            int(meta["evaluation_rows"]), role="evaluation")
        assert_runner_columns = jm.assert_runner_features
        assert_runner_columns(calibration)
        assert_runner_columns(evaluation)
        assert_history_cutoff(calibration)
        assert_history_cutoff(evaluation)
        if calibration.race_id.nunique() != int(meta["calibration_races"]):
            raise AssertionError(f"calibration race count differs from metadata for {year}")
        if evaluation.race_id.nunique() != int(meta["evaluation_races"]):
            raise AssertionError(f"evaluation race count differs from metadata for {year}")

        split = jm.split_calibration(calibration, evaluation, meta)
        h1_groups = jm.race_groups(split["h1"])
        h2_groups = jm.race_groups(split["h2"])
        evaluation_groups = jm.race_groups(evaluation)
        for stage, groups in (("H1", h1_groups), ("H2", h2_groups), ("evaluation", evaluation_groups)):
            for group in groups:
                support = inspect_roster(group)
                roster_support.append({"evaluation_year": year, "stage": stage, **support})
        h1_triple_count = sum(math.comb(len(group), 3) for group in h1_groups)
        h2_triple_count = sum(math.comb(len(group), 3) for group in h2_groups)
        eval_triple_count = sum(math.comb(len(group), 3) for group in evaluation_groups)
        h1_triples += h1_triple_count
        h2_triples += h2_triple_count
        eval_triples += eval_triple_count
        eval_races += len(evaluation_groups)
        eval_rows += len(evaluation)
        eval_days.update(pd.to_datetime(evaluation.race_date).dt.strftime("%Y-%m-%d").unique())
        eval_race_ids.update(str(group.race_id.iloc[0]) for group in evaluation_groups)
        eval_frames.append(evaluation)

        scaler = jm.fit_runner_scaler(split["h1"])
        pair_rms, _ = pair_rms_from_h1(h1_groups, scaler)
        active_columns = [int(i) for i, value in enumerate(pair_rms)
                          if value > jm.DEGENERATE_TOL]
        h1_structure = check_residual_structure(h1_groups, scaler, pair_rms)
        h2_structure = check_residual_structure(h2_groups, scaler, pair_rms)
        eval_structure = check_residual_structure(evaluation_groups, scaler, pair_rms)
        fold_results.append({
            "evaluation_year": year,
            "calibration_year": year - 1,
            "calibration_score_rows": len(calibration),
            "calibration_score_races": int(calibration.race_id.nunique()),
            "calibration_score_race_days": int(calibration.race_date.nunique()),
            "h1_first_half_races_before_purge": split["pre_purge_h1_races"],
            "h1_races_after_t2_purge": split["h1_races"],
            "h1_days_after_t2_purge": split["h1_days"],
            "h1_purged_races": split["purged_races"],
            "h1_min_date": str(pd.to_datetime(split["h1"].race_date).min().date()),
            "h1_max_date": str(split["h1_max"].date()),
            "h2_races": split["h2_races"],
            "h2_days": split["h2_days"],
            "h2_min_date": str(split["h2"].race_date.min().date()),
            "h2_max_date": str(split["h2_max"].date()),
            "base_refit_max": str(split["refit_max"].date()),
            "evaluation_min_date": str(split["evaluation_min"].date()),
            "calibration_min_date": str(split["calibration_min"].date()),
            "calibration_max_date": str(split["calibration_max"].date()),
            "evaluation_max_date": str(split["evaluation_max"].date()),
            "h1_triples": h1_triple_count,
            "h2_triples": h2_triple_count,
            "evaluation_races": len(evaluation_groups),
            "evaluation_runner_rows": len(evaluation),
            "evaluation_triples": eval_triple_count,
            "pair_features": list(jm.PAIR_FEATURES),
            "pair_rms": pair_rms.tolist(),
            "active_pair_columns": active_columns,
            "runner_scaler": scaler,
            "h1_projection": h1_structure,
            "h2_projection": h2_structure,
            "evaluation_projection": eval_structure,
        })

    if (eval_races != jm.EXPECTED_COHORT["races"] or
            eval_rows != jm.EXPECTED_COHORT["runner_rows"] or
            len(eval_days) != jm.EXPECTED_COHORT["race_days"] or
            len(eval_race_ids) != eval_races):
        raise AssertionError("evaluation cohort differs from frozen 1,779-race contract")
    if eval_triples != 201404:
        raise AssertionError(f"evaluation triple count differs from locked diagnostic: {eval_triples}")
    parity = baseline_ticket_parity(eval_frames)
    runner_reference = saved_runner_reference_contract(eval_frames)
    synthetic = jm.synthetic_projection_control()
    after = jm.lock_sources()
    before_hashes = {name: value["sha256"] for name, value in before.items()}
    after_hashes = {name: value["sha256"] for name, value in after.items()}
    if before_hashes != after_hashes:
        raise AssertionError("source hashes changed during preflight")

    jm.OUT.mkdir(parents=True, exist_ok=True)
    source_lock = {
        "study": "20261010_joint_relationship_v1",
        "status": "preflight locked; outcome fitting/evaluation not run",
        "plan_sha256": jm.EXPECTED_PLAN_SHA256,
        "sources": before,
        "expected_manifest_references": jm.expected_manifest_references(),
        "checks": {
            "score_schema": ["api_record_id:int64", "score:float64"],
            "calibration_scores_are_saved_oos_raw_scores": True,
            "base_fit_or_refit_performed": False,
            "database_query_or_connection": False,
            "protected_database_read_only_hash_only": True,
            "network_access": False,
            "database_registry_and_current_model_protected_hashes_verified": True,
            "F1_STYLE6_top3_model_hashes_verified_against_meta": True,
            "style_lineage_snapshot_hash_verified_without_database_query": True,
            "source_hashes_unchanged_during_preflight": True,
        },
    }
    jm.write_json_new(jm.OUT / "source_lock.json", source_lock)
    receipt = {
        "passed": True,
        "status": "outcome-free structural preflight only",
        "study": "20261010_joint_relationship_v1",
        "plan_sha256": jm.EXPECTED_PLAN_SHA256,
        "source_lock_sha256": jm.sha256(jm.OUT / "source_lock.json"),
        "input_hashes_unchanged": True,
        "outcome_metrics_computed": False,
        "relationship_coefficients_fitted": False,
        "temperature_optimized": False,
        "evaluation": {"races": eval_races, "runner_rows": eval_rows,
                       "race_days": len(eval_days), "all_triples": eval_triples,
                       "unique_race_ids": len(eval_race_ids), "six_tickets": eval_races * 6},
        "calibration_triple_rows": {"h1_total": h1_triples, "h2_total": h2_triples},
        "roster_support_record_count": len(roster_support),
        "roster_support": roster_support,
        "history_cutoff_check": {
            "formula": "history_cutoff == race_date - 2 calendar days",
            "latest_history_rule": "all non-null latest_history_date <= history_cutoff; null remains null",
            "checked_calibration_and_evaluation_rows": int(sum(
                item["calibration_score_rows"] + item["evaluation_runner_rows"] for item in fold_results
            )),
        },
        "folds": fold_results,
        "saved_baseline_six_parity": parity,
        "saved_f1_style6_runner_reference_contract": runner_reference,
        "synthetic_unary_only_negative_control": synthetic,
    }
    jm.write_json_new(jm.OUT / "preflight_receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

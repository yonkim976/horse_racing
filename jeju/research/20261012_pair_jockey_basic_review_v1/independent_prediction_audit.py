"""Independent all-pair/pair-selection reproduction for the approved rider arm."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from independent_fit_audit import (
    BASE_FIT_PATH,
    FEATURES_PATH,
    ROOT,
    STARTS_PATH,
    load_independent_rolling_function,
    load_old_pair_moments,
    load_runner_moments,
    read_json,
    require,
    sha256,
    verify_approved_artifacts,
)
from independent_jockey_reference import (
    load_frozen_date_bootstrap_schedule,
    pair_jockey_sums,
    predict_race_21d,
    ref,
)


STUDY = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
OUT = STUDY / "outputs"
REVIEW = Path(__file__).resolve().parent
PREDICTIONS_PATH = OUT / "evaluation_pair_predictions.parquet"
DIAGNOSTICS_PATH = OUT / "evaluation_race_probabilities.parquet"
PREDICTION_RECEIPT_PATH = OUT / "PREDICTION_RECEIPT.json"
BASE = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
BASE_OUT = BASE / "outputs"
BASE_PREDICTIONS_PATH = BASE_OUT / "evaluation_pair_predictions.parquet"
BASE_DIAGNOSTICS_PATH = BASE_OUT / "evaluation_race_probabilities.parquet"
BASE_H2_PATH = BASE_OUT / "expanded_h2_calibration.json"
BASE_FIT_RECEIPT_PATH = BASE_OUT / "PAIR_FIT_RECEIPT.json"
EVAL_YEARS = (2024, 2025, 2026)
EXPECTED_ROWS = 76848
EXPECTED_RACES = 1779
EXPECTED_DATES = 269
EXPECTED_BASE_PREDICTIONS_SHA256 = "f983d9c5dfa7c4d1129b407d5a3e367dc38e193c0c8fdbbaeff34d86b31af499"
EXPECTED_FEATURES_SHA256 = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
EXPECTED_STARTS_SHA256 = "78800c5c91219d58855ce046e39ead6a87729a49c8ba0d58ca9f78765921801a"
KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]
COMPARATORS = {
    "latest_expanded_direct_pair_427": "selected_latest_pair",
    "old_direct_pair_426": "selected_old_direct",
    "H2_calibrated_p0_baseline": "selected_baseline",
    "raw_F1_STYLE6_score_Top2_429": "selected_raw_top2",
    "saved_F1_STYLE6_PTop3_Top2_429": "selected_saved_f1_top2",
    "existing_joint_marginal_Top2_434": "selected_candidate_joint_marginal_top2",
    "existing_candidate_max_joint_pair_422": "selected_candidate_joint_maxpair",
    "existing_matched_max_joint_pair_429": "selected_matched_joint_maxpair",
}


def load_evaluation_rows(prediction_receipt: dict[str, Any]) -> tuple[dict[int, pd.DataFrame], pd.DataFrame, dict[str, str]]:
    require(sha256(FEATURES_PATH) == EXPECTED_FEATURES_SHA256, "frozen evaluation feature source changed")
    require(sha256(STARTS_PATH) == EXPECTED_STARTS_SHA256, "frozen event jockey source changed")
    feature_columns = [
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "field_n", "finish_position", "distance_m",
        *ref.RUNNER_COLUMNS[1:],
    ]
    features = pd.read_parquet(
        FEATURES_PATH, columns=feature_columns,
        filters=[("year", ">=", 2024), ("year", "<=", 2026)],
    )
    for column in ("api_record_id", "race_id", "horse_id"):
        features[column] = features[column].astype("string")
    features["race_date"] = pd.to_datetime(features["race_date"], errors="raise").dt.normalize()
    require(features["api_record_id"].is_unique and set(features["year"].astype(int).unique()) == set(EVAL_YEARS),
            "evaluation feature key/year inventory changed")

    starts = pd.read_csv(
        STARTS_PATH,
        usecols=["api_record_id", "race_id", "horse_id", "race_date", "jockey_id", "field_n", "finish_position"],
        dtype={"api_record_id": "string", "race_id": "string", "horse_id": "string", "jockey_id": "string"},
        low_memory=False,
    )
    starts["race_date"] = pd.to_datetime(starts["race_date"], errors="raise").dt.normalize()
    require(starts["api_record_id"].is_unique, "event source API key duplicated")
    score_meta = prediction_receipt["evaluation_score_sources"]
    event_rows_by_year: dict[int, pd.DataFrame] = {}
    score_hashes: dict[str, str] = {}
    for year in EVAL_YEARS:
        meta = score_meta[str(year)]
        score_path = ROOT / meta["score_path"]
        meta_path = ROOT / meta["meta_path"]
        require(score_path.is_file() and not score_path.is_symlink(), f"evaluation score file missing: {year}")
        require(meta_path.is_file() and not meta_path.is_symlink(), f"evaluation score metadata missing: {year}")
        score_sha = sha256(score_path)
        meta_sha = sha256(meta_path)
        require(score_sha == meta["score_sha256"], f"evaluation score hash changed: {year}")
        require(meta_sha == meta["meta_sha256"], f"evaluation score metadata hash changed: {year}")
        meta_doc = read_json(meta_path)
        require(meta_doc.get("refit_max") == meta["refit_max"], f"evaluation refit date changed: {year}")
        scores = pd.read_parquet(score_path)
        require(scores.columns.tolist() == ["api_record_id", "score"], f"evaluation score schema changed: {year}")
        scores["api_record_id"] = scores["api_record_id"].astype("string")
        require(scores["api_record_id"].is_unique and np.isfinite(scores["score"].to_numpy(dtype=float)).all(),
                f"invalid evaluation score rows: {year}")
        rows = features.loc[features["year"].eq(year)].copy()
        require(set(rows["api_record_id"]) == set(scores["api_record_id"]), f"evaluation score key set changed: {year}")
        rows = rows.merge(scores, on="api_record_id", how="left", validate="one_to_one")
        require(rows["score"].notna().all() and len(rows) == int(meta["rows"]), f"evaluation score join/row count changed: {year}")
        event = rows.merge(
            starts[["api_record_id", "race_id", "horse_id", "race_date", "jockey_id", "field_n", "finish_position"]],
            on="api_record_id", how="left", validate="one_to_one", suffixes=("_feature", "_event"), indicator=True,
        )
        require(event["_merge"].eq("both").all(), f"event API key join missing: {year}")
        for a, b in (("race_id_feature", "race_id_event"), ("horse_id_feature", "horse_id_event"),
                     ("race_date_feature", "race_date_event"), ("field_n_feature", "field_n_event"),
                     ("finish_position_feature", "finish_position_event")):
            require(event[a].eq(event[b]).all(), f"source event mismatch {year}: {a}")
        event["race_id"] = event["race_id_feature"]
        event["horse_id"] = event["horse_id_feature"]
        event["race_date"] = event["race_date_feature"]
        event["field_n"] = event["field_n_feature"]
        event["finish_position"] = event["finish_position_feature"]
        event = event.drop(columns=[
            "_merge", "race_id_feature", "race_id_event", "horse_id_feature", "horse_id_event",
            "race_date_feature", "race_date_event", "field_n_feature", "field_n_event",
            "finish_position_feature", "finish_position_event",
        ])
        require(event["jockey_id"].notna().all(), f"event jockey ID missing: {year}")
        require(event["race_id"].nunique() == int(meta["races"]), f"evaluation race coverage changed: {year}")
        refit_max = pd.Timestamp(meta["refit_max"]).normalize()
        require(((event["race_date"] - pd.Timedelta(days=2)) >= refit_max).all(), f"score provider T-2 failed: {year}")
        score_hashes[meta["score_path"]] = score_sha
        score_hashes[meta["meta_path"]] = meta_sha
        event_rows_by_year[year] = event

    all_event_rows = pd.concat([event_rows_by_year[year] for year in EVAL_YEARS], ignore_index=True)
    rolling = load_independent_rolling_function()(all_event_rows, starts)
    all_event_rows = all_event_rows.merge(
        rolling[["api_record_id", "n_independent", "s_independent", "e_independent", "d_independent", "latest_history_date"]],
        on="api_record_id", how="left", validate="one_to_one",
    )
    require(all_event_rows["d_independent"].notna().all(), "independent evaluation rolling d missing")
    cutoff = all_event_rows["race_date"] - pd.Timedelta(days=2)
    latest = pd.to_datetime(all_event_rows["latest_history_date"], errors="coerce")
    require((latest.isna() | (latest <= cutoff)).all(), "evaluation history date exceeds T-2")
    by_year = {year: all_event_rows.loc[all_event_rows["year"].eq(year)].copy() for year in EVAL_YEARS}
    require(len(all_event_rows) == 17412 and all_event_rows["race_id"].nunique() == EXPECTED_RACES
            and all_event_rows["race_date"].nunique() == EXPECTED_DATES,
            "fixed evaluation roster inventory changed")
    return by_year, all_event_rows, score_hashes


def evaluate_independent_predictions() -> dict[str, Any]:
    approval, preflight, fit, fit_receipt, baseline_fit = verify_approved_artifacts()
    prediction_receipt = read_json(PREDICTION_RECEIPT_PATH)
    require(prediction_receipt.get("status") == "PASS" and prediction_receipt.get("performance_metrics_computed") is False,
            "candidate prediction receipt is not a metrics-free PASS")
    require(prediction_receipt.get("fit_receipt_sha256") == sha256(OUT / "FIT_RECEIPT.json"),
            "prediction receipt points to another fit")
    require(prediction_receipt.get("fit_sha256") == sha256(OUT / "FIT.json"), "prediction receipt fit hash mismatch")
    require(prediction_receipt.get("approval_sha256") == sha256(OUT / "APPROVAL.json"), "prediction approval hash mismatch")
    require(prediction_receipt.get("pair_predictions_sha256") == sha256(PREDICTIONS_PATH), "candidate prediction hash mismatch")
    require(prediction_receipt.get("race_diagnostics_sha256") == sha256(DIAGNOSTICS_PATH), "candidate diagnostic hash mismatch")
    require(prediction_receipt.get("fixed_pair_reference_sha256") == EXPECTED_BASE_PREDICTIONS_SHA256
            and sha256(BASE_PREDICTIONS_PATH) == EXPECTED_BASE_PREDICTIONS_SHA256,
            "latest expanded pair reference changed")
    require(prediction_receipt.get("bootstrap_schedule_sha256") == "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
            "prediction receipt schedule hash changed")
    candidate_rows = pd.read_parquet(PREDICTIONS_PATH)
    base_rows = pd.read_parquet(BASE_PREDICTIONS_PATH)
    require(len(candidate_rows) == len(base_rows) == EXPECTED_ROWS, "all-pair output row count changed")
    require(candidate_rows["race_id"].nunique() == base_rows["race_id"].nunique() == EXPECTED_RACES,
            "all-pair output race count changed")
    require(not candidate_rows.duplicated(KEYS).any() and not base_rows.duplicated(KEYS).any(), "duplicate pair key")
    require(set(candidate_rows["race_date"].astype(str).unique()) == set(base_rows["race_date"].astype(str).unique()),
            "evaluation date inventory changed")
    require(candidate_rows.groupby("race_id")["selected_candidate"].sum().eq(1).all(), "candidate selection count != 1/race")

    yearly, all_event_rows, score_hashes = load_evaluation_rows(prediction_receipt)
    baseline_rows = {int(row["evaluation_year"]): row for row in baseline_fit["folds"]}
    candidate_folds = {int(row["evaluation_year"]): row for row in fit["folds"]}
    baseline_h2 = read_json(BASE_H2_PATH)
    base_fit_receipt = read_json(BASE_FIT_RECEIPT_PATH)
    require(base_fit_receipt.get("expanded_h2_calibration_sha256") == sha256(BASE_H2_PATH),
            "frozen baseline H2 calibration hash mismatch")
    baseline_maps = {
        int(row["evaluation_year"]): (float(row["A"]), float(row["B"]))
        for row in baseline_h2["fold_maps"] if row["map"] == "baseline"
    }
    candidate_maps = {
        year: (float(candidate_folds[year]["h2_candidate_platt"]["A"]),
               float(candidate_folds[year]["h2_candidate_platt"]["B"]))
        for year in EVAL_YEARS
    }
    expected_records: list[dict[str, Any]] = []
    expected_diagnostics: dict[str, dict[str, Any]] = {}
    for year in EVAL_YEARS:
        fold_rows = candidate_folds[year]
        runner_moments = load_runner_moments(baseline_rows[year])
        old_pair_moments = load_old_pair_moments(baseline_rows[year])
        jockey_moments = fold_rows["new_pair_moment"]
        race_count = 0
        for race_id, frame in yearly[year].groupby("race_id", sort=True):
            race = frame.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
            numbers = race["horse_number"].astype(int).tolist()
            finishes = race["finish_position"].astype(int).tolist()
            require(len(race) == int(race["field_n"].iloc[0]) and sorted(finishes) == list(range(1, len(race) + 1)),
                    f"evaluation roster/ranks mismatch: {race_id}")
            require(sum(position <= 3 for position in finishes) == 3, f"Top3 runner count differs: {race_id}")
            runner_values = {name: race[name].to_numpy() for name in ref.RUNNER_COLUMNS}
            d_by_horse = {int(row.horse_number): float(row.d_independent) for row in race.itertuples(index=False)}
            n_by_horse = {int(row.horse_number): int(row.n_independent) for row in race.itertuples(index=False)}
            prediction = predict_race_21d(
                numbers, runner_values["score"], runner_values, d_by_horse,
                runner_moments, old_pair_moments, jockey_moments,
                [fold_rows["beta_by_basis"][name] for name in ref.BASIS_NAMES]
                + [fold_rows["gamma_jockey365_pair_sum"]], candidate_maps[year],
            )
            pairs = prediction["pairs"]
            labels = ref.pair_label(dict(zip(numbers, finishes, strict=True)), pairs)
            eta0 = ref.logit(prediction["p0"])
            baseline_a, baseline_b = baseline_maps[year]
            baseline_probability = ref.sigmoid(baseline_a + baseline_b * eta0)
            raw_by_horse = {int(row.horse_number): float(row.score) for row in race.itertuples(index=False)}
            selected_baseline = ref.choose_pair(pairs, eta0)
            expected_diagnostics[str(race_id)] = {
                "race_id": str(race_id), "race_date": race["race_date"].iloc[0].date().isoformat(),
                "evaluation_year": year, "distance_m": int(race["distance_m"].iloc[0]),
                "jockey_basic_candidate_sum_probability_minus_3": float(np.sum(prediction["candidate_calibrated_probability"])
                                                                          - 3.0),
            }
            for index, (horse_i, horse_j) in enumerate(pairs):
                expected_records.append({
                    "race_id": str(race_id), "race_date": race["race_date"].iloc[0].date().isoformat(),
                    "evaluation_year": year, "distance_m": int(race["distance_m"].iloc[0]),
                    "horse_i": horse_i, "horse_j": horse_j,
                    "score_i": raw_by_horse[horse_i], "score_j": raw_by_horse[horse_j],
                    "p0": float(prediction["p0"][index]), "eta": float(prediction["eta"][index]),
                    "candidate_raw_probability": float(prediction["candidate_raw_probability"][index]),
                    "candidate_calibrated_probability": float(prediction["candidate_calibrated_probability"][index]),
                    "baseline_calibrated_probability": float(baseline_probability[index]),
                    "y_pair": int(labels[index]),
                    "selected_candidate": int(pairs[index] == prediction["selected_candidate"]),
                    "selected_baseline_expected": int(pairs[index] == selected_baseline),
                    "jockey365_n_i": n_by_horse[horse_i], "jockey365_n_j": n_by_horse[horse_j],
                    "jockey365_d_i": d_by_horse[horse_i], "jockey365_d_j": d_by_horse[horse_j],
                    "jockey365_pair_sum": d_by_horse[horse_i] + d_by_horse[horse_j],
                    "jockey365_pair_z": float(prediction["standardized_basis_21"][index, 20]),
                })
            race_count += 1
        require(race_count == {2024: 637, 2025: 654, 2026: 488}[year], f"race count differs in eval year {year}")

    expected = pd.DataFrame(expected_records)
    actual = candidate_rows.merge(expected, on=KEYS, how="outer", validate="one_to_one", suffixes=("_stored", "_independent"), indicator=True)
    require(actual["_merge"].eq("both").all(), "stored and independently reconstructed pair keys differ")
    max_errors: dict[str, float] = {}
    tolerances = {
        "score_i": 0.0, "score_j": 0.0, "p0": 1e-14, "eta": 1e-11,
        "candidate_raw_probability": 1e-11, "candidate_calibrated_probability": 1e-11,
        "baseline_calibrated_probability": 1e-11, "jockey365_d_i": 1e-11,
        "jockey365_d_j": 1e-11, "jockey365_pair_sum": 2e-11, "jockey365_pair_z": 1e-9,
    }
    for field, tolerance in tolerances.items():
        error = (actual[f"{field}_stored"].astype(float) - actual[f"{field}_independent"].astype(float)).abs()
        max_errors[field] = float(error.max())
        require(max_errors[field] <= tolerance, f"stored candidate {field} differs; max={max_errors[field]}")
    for field in ("y_pair", "selected_candidate", "jockey365_n_i", "jockey365_n_j"):
        require(actual[f"{field}_stored"].astype(int).equals(actual[f"{field}_independent"].astype(int)),
                f"stored candidate {field} differs")
    require(actual["selected_baseline"].astype(int).equals(actual["selected_baseline_expected"].astype(int)),
            "frozen baseline selector differs from independent p0 argmax")
    # Both candidate eta column names and the canonical selector must agree.
    for field in ("candidate_eta", "eta"):
        err = (candidate_rows[field].to_numpy(dtype=float) - expected["eta"].to_numpy(dtype=float)).__abs__()
        require(float(err.max()) <= 1e-11, f"candidate {field} alias differs")
        max_errors[field] = float(err.max())
    require(candidate_rows["selected_jockey_basic_candidate"].astype(int).equals(candidate_rows["selected_candidate"].astype(int)),
            "candidate selector alias differs")
    require(candidate_rows.groupby("race_id")["selected_jockey_basic_candidate"].sum().eq(1).all(),
            "jockey candidate selector not exactly one/race")

    # Check that every frozen comparator and probability is preserved from the
    # pinned latest-pair table, with explicit aliases for the overwritten names.
    base_join = base_rows.merge(candidate_rows, on=KEYS, how="outer", validate="one_to_one", suffixes=("_base", "_new"), indicator=True)
    require(base_join["_merge"].eq("both").all(), "candidate eval pair set differs from frozen latest-pair set")
    exact_base_fields = [
        "score_i", "score_j", "p0", "y_pair", "selected_baseline", "selected_raw_top2",
        "selected_saved_f1_top2", "selected_candidate_joint_marginal_top2", "selected_candidate_joint_maxpair",
        "selected_matched_joint_maxpair", "selected_expanded_candidate", "expanded_eta",
        "expanded_candidate_raw_probability", "expanded_candidate_calibrated_probability",
        "selected_old_direct", "old_direct_eta", "old_direct_candidate_raw_probability",
        "old_direct_candidate_calibrated_probability",
    ]
    frozen_exact_errors = {}
    for field in exact_base_fields:
        left, right = base_join[f"{field}_base"], base_join[f"{field}_new"]
        if pd.api.types.is_numeric_dtype(left.dtype):
            require(np.array_equal(left.to_numpy(), right.to_numpy()), f"frozen comparator field changed: {field}")
        else:
            require(left.astype(str).equals(right.astype(str)), f"frozen comparator field changed: {field}")
        frozen_exact_errors[field] = 0.0
    for new_field, base_field in (
        ("latest_pair_eta", "expanded_eta"),
        ("latest_pair_raw_probability", "expanded_candidate_raw_probability"),
        ("latest_pair_calibrated_probability", "expanded_candidate_calibrated_probability"),
        ("old_direct_calibrated_probability", "old_direct_candidate_calibrated_probability"),
    ):
        require(np.array_equal(base_join[new_field].to_numpy(), base_join[f"{base_field}_base"].to_numpy()),
                f"frozen comparator alias changed: {new_field}")
    require(np.array_equal(base_join["selected_latest_pair"].to_numpy(), base_join["selected_expanded_candidate_base"].to_numpy()),
            "latest pair selector alias changed")

    diag_rows = pd.read_parquet(DIAGNOSTICS_PATH)
    base_diag = pd.read_parquet(BASE_DIAGNOSTICS_PATH)
    require(diag_rows["race_id"].astype(str).is_unique and set(diag_rows["race_id"].astype(str)) == set(expected_diagnostics),
            "race diagnostic inventory changed")
    diag_join = base_diag.merge(diag_rows, on=["race_id", "race_date", "evaluation_year", "distance_m"],
                                how="outer", validate="one_to_one", suffixes=("_base", "_new"), indicator=True)
    require(diag_join["_merge"].eq("both").all(), "candidate and frozen diagnostic race keys differ")
    for old_field in (
        "old_direct_candidate_sum_calibrated_pair_probability_minus_3",
        "baseline_sum_calibrated_pair_probability_minus_3",
        "old_direct_candidate_abs_sum_deviation", "baseline_abs_sum_deviation",
    ):
        require(np.array_equal(diag_join[f"{old_field}_base"].to_numpy(), diag_join[f"{old_field}_new"].to_numpy()),
                f"frozen diagnostic changed: {old_field}")
    for old_field, new_field in (
        ("candidate_sum_calibrated_pair_probability_minus_3", "latest_pair_sum_probability_minus_3"),
        ("candidate_abs_sum_deviation", "latest_pair_abs_sum_deviation"),
    ):
        require(np.array_equal(diag_join[old_field].to_numpy(), diag_join[new_field].to_numpy()),
                f"frozen latest-pair diagnostic alias changed: {old_field}")
    diag_errors = {"jockey_basic_candidate_sum_probability_minus_3": 0.0}
    diag_map = diag_rows.set_index(diag_rows["race_id"].astype(str))
    for race_id, expected_diag in expected_diagnostics.items():
        for key in ("race_date", "evaluation_year", "distance_m"):
            require(str(diag_map.loc[race_id, key]) == str(expected_diag[key]), f"diagnostic metadata differs: {race_id}/{key}")
        error = abs(float(diag_map.loc[race_id, "jockey_basic_candidate_sum_probability_minus_3"])
                    - expected_diag["jockey_basic_candidate_sum_probability_minus_3"])
        diag_errors["jockey_basic_candidate_sum_probability_minus_3"] = max(
            diag_errors["jockey_basic_candidate_sum_probability_minus_3"], error,
        )
        require(error <= 1e-12, f"candidate probability-mass diagnostic differs: {race_id}")

    # Recompute all fixed-reference hit counts, probability-quality summaries,
    # and paired CIs with the exact saved int32 date schedule.
    comparator_pairs: dict[str, dict[str, tuple[int, int]]] = {name: {} for name in COMPARATORS}
    for race_id, group in candidate_rows.groupby("race_id", sort=True):
        for name, selector in COMPARATORS.items():
            selected = group.loc[group[selector].astype(int).eq(1)]
            require(len(selected) == 1, f"frozen selector {selector} not one/race: {race_id}")
            row = selected.iloc[0]
            comparator_pairs[name][str(race_id)] = (int(row["horse_i"]), int(row["horse_j"]))
    candidate_by_year = {int(row["evaluation_year"]): row for row in fit["folds"]}
    candidate_platt = {
        year: (float(candidate_by_year[year]["h2_candidate_platt"]["A"]),
               float(candidate_by_year[year]["h2_candidate_platt"]["B"]))
        for year in EVAL_YEARS
    }
    baseline_platt = {year: baseline_maps[year] for year in EVAL_YEARS}
    norm_rows = []
    for row in candidate_rows.to_dict(orient="records"):
        norm_rows.append({
            "race_id": str(row["race_id"]), "race_date": str(row["race_date"]),
            "evaluation_year": int(row["evaluation_year"]), "distance_m": int(row["distance_m"]),
            "horse_a": int(row["horse_i"]), "horse_b": int(row["horse_j"]),
            "score_a": float(row["score_i"]), "score_b": float(row["score_j"]),
            "p0": float(row["p0"]), "eta": float(row["candidate_eta"]),
            "candidate_calibrated_probability": float(row["candidate_calibrated_probability"]),
            "baseline_calibrated_probability": float(row["baseline_calibrated_probability"]),
            "y_pair": int(row["y_pair"]),
            "candidate_selected": bool(row["selected_jockey_basic_candidate"]),
        })
    schedule = load_frozen_date_bootstrap_schedule(candidate_rows["race_date"].astype(str).tolist())
    evaluation = ref.evaluate_prediction_records(
        norm_rows, comparator_pairs, candidate_platt, baseline_platt, schedule,
    )
    hit_counts = {name: int(value["hits"]) for name, value in evaluation["selected_pair_hit_rates"].items()}
    expected_fixed = {
        "latest_expanded_direct_pair_427": 427,
        "old_direct_pair_426": 426,
        "H2_calibrated_p0_baseline": 429,
        "raw_F1_STYLE6_score_Top2_429": 429,
        "saved_F1_STYLE6_PTop3_Top2_429": 429,
        "existing_joint_marginal_Top2_434": 434,
        "existing_candidate_max_joint_pair_422": 422,
        "existing_matched_max_joint_pair_429": 429,
    }
    for name, expected_hits in expected_fixed.items():
        require(hit_counts[name] == expected_hits, f"frozen comparator hit count changed for {name}: {hit_counts[name]}")
    primary_key = "direct_candidate_minus_latest_expanded_direct_pair_427"
    raw_gate_key = "direct_candidate_minus_raw_F1_STYLE6_score_Top2_429"
    primary_ci = evaluation["selected_pair_date_bootstrap"][primary_key]
    raw_ci = evaluation["selected_pair_date_bootstrap"][raw_gate_key]
    primary_pass = bool(primary_ci["estimate"] > 0 and primary_ci["lower_95"] > 0)
    raw_gate_pass = bool(raw_ci["estimate"] > 0 and raw_ci["lower_95"] > 0)
    return {
        "status": "PASS",
        "scope": "independent all-pair candidate reconstruction, frozen selector preservation, fixed-reference hits and report metrics/CI; no optimizer",
        "approval_sha256": sha256(OUT / "APPROVAL.json"),
        "fit_receipt_sha256": sha256(OUT / "FIT_RECEIPT.json"), "fit_sha256": sha256(OUT / "FIT.json"),
        "prediction_receipt_sha256": sha256(PREDICTION_RECEIPT_PATH),
        "prediction_sha256": sha256(PREDICTIONS_PATH), "diagnostics_sha256": sha256(DIAGNOSTICS_PATH),
        "baseline_pair_prediction_sha256": sha256(BASE_PREDICTIONS_PATH),
        "schedule_sha256": "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
        "evaluation_score_source_hashes": score_hashes,
        "candidate_pair_rows": len(candidate_rows), "evaluation_races": int(candidate_rows["race_id"].nunique()),
        "evaluation_dates": int(candidate_rows["race_date"].nunique()),
        "max_abs_error_vs_independent_candidate": max_errors,
        "frozen_base_column_exact": frozen_exact_errors,
        "diagnostics_max_abs_error": diag_errors,
        "comparator_hits": hit_counts,
        "candidate_hits": hit_counts["direct_candidate"],
        "primary_latest_pair_difference": primary_ci,
        "raw_top2_gate_difference": raw_ci,
        "primary_latest_pair_gate_pass": primary_pass,
        "raw_top2_gate_pass": raw_gate_pass,
        "independent_evaluation_report": {
            key: value for key, value in evaluation.items() if key != "selector_pairs"
        },
        "bootstrap_schedule_receipt": ref.date_bootstrap_schedule_receipt(schedule),
        "optimizer_calls": 0,
    }


def main() -> None:
    receipt = evaluate_independent_predictions()
    path = REVIEW / "independent_prediction_audit.json"
    require(not path.exists() and not path.is_symlink(), "refusing to overwrite prediction audit receipt")
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


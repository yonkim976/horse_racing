"""Independent exact-slot feature and frozen-F1 replay verification.

This code loads saved LightGBM models directly and independently computes the
Top3 marginal probabilities, race losses, and top-six three-horse sets. It does
not import either the candidate builder/replay or the original model evaluator.
"""
import sys

sys.dont_write_bytecode = True

import hashlib
import itertools
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
F1_OUT = F1_DIR / "outputs"
SECTION_DIR = ROOT / "jeju/research/20261009_section_time_ablation_v1"
SECTION_OUT = SECTION_DIR / "outputs"
INDEPENDENT = HERE / "independent_outputs"
OUTPUTS = {
    "features": SECTION_OUT / "features_f1s.parquet",
    "candidate_preflight": SECTION_OUT / "candidate_feature_preflight.json",
    "candidate_runner": SECTION_OUT / "f1_reproduced_runner_predictions.parquet",
    "candidate_race": SECTION_OUT / "f1_reproduced_race_metrics.csv",
    "candidate_sets": SECTION_OUT / "f1_reproduced_six_combinations.csv",
    "candidate_replay": SECTION_OUT / "f1_saved_model_replay.json",
    "f1_features": F1_OUT / "features.parquet",
    "f1_runner": F1_OUT / "runner_predictions_canonical.parquet",
    "f1_race": F1_OUT / "race_metrics.csv",
    "f1_sets": F1_OUT / "six_combinations.csv",
}
YEARS = (2024, 2025, 2026)
TIME_FIELDS = ("s1f", "g3f", "g1f")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compare_frame(left, right, keys, numeric, string=(), atol=1e-12):
    a = left.sort_values(keys, kind="stable").reset_index(drop=True)
    b = right.sort_values(keys, kind="stable").reset_index(drop=True)
    assert len(a) == len(b), (len(a), len(b))
    for col in keys:
        assert a[col].astype(str).equals(b[col].astype(str)), col
    for col in string:
        assert a[col].fillna("<NULL>").astype(str).equals(b[col].fillna("<NULL>").astype(str)), col
    for col in numeric:
        x = pd.to_numeric(a[col], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(b[col], errors="coerce").to_numpy(dtype=float)
        assert np.allclose(x, y, rtol=0, atol=atol, equal_nan=True), col


def compare_subset(left, right, keys, numeric, string=()):
    columns = list(dict.fromkeys([*keys, *string, *numeric]))
    compare_frame(left[columns], right[columns], keys, numeric, string)
    return {"rows": int(len(left)), "columns_compared": columns, "match": True}


def log_softmax(values):
    maximum = float(np.max(values))
    return values - (maximum + float(np.log(np.exp(values - maximum).sum())))


def independently_evaluate(test, scores, tau, year):
    runner_rows = []
    race_rows = []
    set_rows = []
    for race_id, positions in test.groupby("race_id", sort=False).indices.items():
        positions = np.asarray(positions, dtype=np.int64)
        one = test.iloc[positions]
        one_scores = np.asarray(scores[positions], dtype=np.float64)
        n = len(one)
        assert one.horse_number.is_monotonic_increasing
        assert len(one_scores) == n

        combinations = np.asarray(list(itertools.combinations(range(n), 3)), dtype=np.int64)
        true_indices = np.flatnonzero(one.finish_position.to_numpy() <= 3)
        assert len(true_indices) == 3, (race_id, len(true_indices))
        true_index = np.flatnonzero(np.all(combinations == true_indices[None, :], axis=1))
        assert len(true_index) == 1
        true_index = int(true_index[0])

        combination_energy = np.sort(one_scores[combinations], axis=1).sum(axis=1)
        log_probabilities = log_softmax(combination_energy / float(tau))
        probabilities = np.exp(log_probabilities)
        incidence = np.zeros((len(combinations), n), dtype=np.float64)
        incidence[np.arange(len(combinations))[:, None], combinations] = 1.0
        marginal = probabilities @ incidence
        assert np.isclose(probabilities.sum(), 1.0, rtol=0, atol=1e-12)
        assert np.isclose(marginal.sum(), 3.0, rtol=0, atol=1e-10)

        target = (one.finish_position.to_numpy() <= 3).astype(np.float64)
        clipped = np.clip(marginal, 1e-12, 1.0 - 1e-12)
        individual_logloss = -target * np.log(clipped) - (1.0 - target) * np.log1p(-clipped)
        individual_brier = np.square(marginal - target)
        score_order = np.argsort(-one_scores, kind="stable")
        combo_order = np.argsort(-combination_energy, kind="stable")
        truth_set = set(combinations[true_index].tolist())

        race = {
            "race_id": str(race_id),
            "race_date": str(one.race_date.iloc[0]),
            "year": int(one.year.iloc[0]),
            "variant": "F1",
            "distance_m": int(one.distance_m.iloc[0]),
            "grade_raw": one.grade_raw.iloc[0],
            "field_n": int(n),
            "any_no_history": bool(one.observed_starts.eq(0).any()),
            "any_low_history": bool(one.observed_starts.lt(5).any()),
            "any_no_same_time": bool(one.same_valid_times.eq(0).any()),
            "log_loss": float(individual_logloss.mean()),
            "brier": float(individual_brier.mean()),
            "trio_nll": float(-log_probabilities[true_index]),
            "six_combo_hit": int(true_index in combo_order[:6]),
            "six_combo_mass": float(probabilities[combo_order[:6]].sum()),
        }
        for k in (3, 4, 5, 6):
            chosen = set(score_order[:k].tolist())
            race[f"top{k}_capture"] = len(truth_set & chosen) / 3.0
            race[f"top{k}_all3"] = int(truth_set <= chosen)
        race_rows.append(race)

        metadata_columns = [
            "api_record_id", "race_id", "race_date", "year", "distance_m",
            "grade_raw", "horse_id", "horse_number", "observed_starts",
            "same_valid_times", "field_n",
        ]
        for local_idx, (_, row) in enumerate(one.iterrows()):
            runner_rows.append({
                **{column: row[column] for column in metadata_columns},
                "variant": "F1",
                "score": float(one_scores[local_idx]),
                "p_top3": float(marginal[local_idx]),
                "y": int(target[local_idx]),
                "log_loss": float(individual_logloss[local_idx]),
                "brier": float(individual_brier[local_idx]),
            })

        for rank, combination_index in enumerate(combo_order[:6], start=1):
            selected_numbers = one.horse_number.iloc[combinations[combination_index]].astype(int)
            set_rows.append({
                "race_id": str(race_id),
                "variant": "F1",
                "selection_rank": int(rank),
                "numbers": ",".join(map(str, selected_numbers)),
                "probability": float(probabilities[combination_index]),
                "hit": int(combination_index == true_index),
            })
    return pd.DataFrame(runner_rows), pd.DataFrame(race_rows), pd.DataFrame(set_rows)


def main():
    for path in OUTPUTS.values():
        assert path.is_file(), f"missing expected input: {path}"
    preflight = json.loads(OUTPUTS["candidate_preflight"].read_text(encoding="utf-8"))
    replay_receipt = json.loads(OUTPUTS["candidate_replay"].read_text(encoding="utf-8"))
    assert preflight["passed"] and preflight["fit_executed"] is False
    assert replay_receipt["passed"]
    assert replay_receipt["model_refit_count"] == 0
    assert replay_receipt["temperature_optimization_count"] == 0
    assert replay_receipt["candidate_columns_used_for_f1_replay"] == []

    base_features = pd.read_parquet(OUTPUTS["f1_features"])
    candidate_features = pd.read_parquet(OUTPUTS["features"])
    additions = [
        "history_s1f_mean5_seconds", "history_s1f_valid_n",
        "history_g3f_mean5_seconds", "history_g3f_valid_n",
        "history_g1f_mean5_seconds", "history_g1f_valid_n",
    ]
    assert len(candidate_features) == len(base_features) == 52155
    assert candidate_features.race_id.nunique() == base_features.race_id.nunique() == 5206
    assert [column for column in candidate_features.columns if column not in base_features.columns] == additions
    pd.testing.assert_frame_equal(
        candidate_features[base_features.columns], base_features,
        check_dtype=True, check_exact=True,
    )

    independent = pd.read_csv(INDEPENDENT / "independent_target_feature_reconstruction.csv")
    assert independent.api_record_id.is_unique
    assert candidate_features.api_record_id.astype("int64").equals(independent.api_record_id.astype("int64"))
    reconstruction_columns = {
        "s1f": "history_s1f_mean5_seconds",
        "g3f": "history_g3f_mean5_seconds",
        "g1f": "history_g1f_mean5_seconds",
    }
    feature_differences = {}
    for section, mean_col in reconstruction_columns.items():
        candidate_valid_col = f"history_{section}_valid_n"
        independent_valid_col = f"{section}_valid_n"
        candidate_n = candidate_features[candidate_valid_col].to_numpy(dtype=np.int64)
        independent_n = independent[independent_valid_col].to_numpy(dtype=np.int64)
        assert np.array_equal(candidate_n, independent_n), candidate_valid_col
        candidate_mean = candidate_features[mean_col].to_numpy(dtype=np.float64)
        independent_mean = independent[f"history_{section}_mean5_seconds"].to_numpy(dtype=np.float64)
        assert np.allclose(candidate_mean, independent_mean, rtol=0, atol=1e-12, equal_nan=True), mean_col
        assert candidate_features.loc[candidate_features[candidate_valid_col].eq(0), mean_col].isna().all()
        feature_differences[section] = {
            "valid_n_exact_match": True,
            "mean_atol_1e-12_match": True,
            "targets_with_valid_n_zero": int(candidate_features[candidate_valid_col].eq(0).sum()),
            "targets_with_any_valid_time": int(candidate_features[candidate_valid_col].gt(0).sum()),
            "absolute_mean_difference_max": float(np.nanmax(np.abs(candidate_mean - independent_mean)))
            if np.isfinite(candidate_mean - independent_mean).any() else 0.0,
        }

    frozen_runner = pd.read_parquet(OUTPUTS["f1_runner"])
    frozen_runner = frozen_runner.loc[frozen_runner.variant.eq("F1")].copy()
    frozen_races = pd.read_csv(OUTPUTS["f1_race"])
    frozen_races = frozen_races.loc[frozen_races.variant.eq("F1")].copy()
    frozen_sets = pd.read_csv(OUTPUTS["f1_sets"])
    frozen_sets = frozen_sets.loc[frozen_sets.variant.eq("F1")].copy()
    candidate_runner = pd.read_parquet(OUTPUTS["candidate_runner"])
    candidate_races = pd.read_csv(OUTPUTS["candidate_race"])
    candidate_sets = pd.read_csv(OUTPUTS["candidate_sets"])
    assert (len(frozen_runner), frozen_runner.race_id.nunique()) == (17412, 1779)
    assert len(frozen_races) == 1779 and len(frozen_sets) == 10674
    assert len(candidate_runner) == 17412 and len(candidate_races) == 1779 and len(candidate_sets) == 10674

    all_runners, all_races, all_sets = [], [], []
    replay_years = {}
    for year in YEARS:
        folder = F1_OUT / f"F1_{year}"
        meta_path = folder / "meta.json"
        model_path = folder / "top3.txt"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert int(meta["evaluation_year"]) == year and meta["variant"] == "F1"
        assert len(meta["features"]) == 24
        assert int(meta["seed"]) == 20261008
        assert sha256(model_path) == meta["model_sha256"] == replay_receipt["frozen_model_sha256"][str(year)]
        assert int(meta["trees"]) in (92, 200)
        model = lgb.Booster(model_file=str(model_path))

        test = base_features.loc[base_features.year.eq(year)].reset_index(drop=True)
        assert test.race_id.nunique() == int(meta["evaluation_races"])
        x = test[meta["features"]].copy()
        for column, vocabulary in meta["vocabulary"].items():
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocabulary)
        raw_score = model.predict(x, raw_score=True, num_threads=4)
        runner, races, sets = independently_evaluate(test, raw_score, float(meta["tau"]), year)

        frozen_year = frozen_runner.loc[frozen_runner.year.eq(year)]
        compare_summary = compare_subset(
            runner, frozen_year, ["api_record_id"],
            ["score", "p_top3", "y", "log_loss", "brier"],
            ["race_id", "race_date", "year", "distance_m", "grade_raw", "horse_id", "horse_number"],
        )
        candidate_year = candidate_runner.loc[candidate_runner.year.eq(year)]
        candidate_replay_compare = compare_subset(
            runner, candidate_year, ["api_record_id"],
            ["year", "distance_m", "horse_number", "observed_starts", "same_valid_times", "field_n",
             "score", "p_top3", "y", "log_loss", "brier"],
            ["race_id", "race_date", "grade_raw", "horse_id", "variant"],
        )

        metric_columns = [
            "field_n", "log_loss", "brier", "trio_nll", "six_combo_hit", "six_combo_mass",
            "top3_capture", "top3_all3", "top4_capture", "top4_all3",
            "top5_capture", "top5_all3", "top6_capture", "top6_all3",
        ]
        compare_subset(
            races, frozen_races.loc[frozen_races.year.eq(year)], ["race_id"], metric_columns,
            ["race_date", "year", "distance_m", "grade_raw", "variant", "any_no_history", "any_low_history", "any_no_same_time"],
        )
        candidate_race_compare = compare_subset(
            races, candidate_races.loc[candidate_races.year.eq(year)], ["race_id"],
            ["year", "distance_m", "field_n", *metric_columns],
            ["race_date", "variant", "grade_raw", "any_no_history", "any_low_history", "any_no_same_time"],
        )
        compare_subset(
            sets, frozen_sets.loc[frozen_sets.race_id.isin(sets.race_id)],
            ["race_id", "selection_rank"], ["probability", "hit"], ["variant", "numbers"],
        )
        compare_subset(
            sets, candidate_sets.loc[candidate_sets.race_id.isin(sets.race_id)],
            ["race_id", "selection_rank"], ["probability", "hit"], ["variant", "numbers"],
        )
        all_runners.append(runner)
        all_races.append(races)
        all_sets.append(sets)
        replay_years[str(year)] = {
            "saved_model_sha256": sha256(model_path),
            "saved_tree_count": int(meta["trees"]),
            "stored_temperature": float(meta["tau"]),
            "runner_rows": int(len(runner)),
            "races": int(len(races)),
            "six_set_rows": int(len(sets)),
            "frozen_f1_prediction_match": compare_summary,
            "candidate_replay_runner_match": candidate_replay_compare,
            "candidate_replay_race_match": candidate_race_compare,
        }

    replay_runner = pd.concat(all_runners, ignore_index=True)
    replay_races = pd.concat(all_races, ignore_index=True)
    replay_sets = pd.concat(all_sets, ignore_index=True)
    assert (len(replay_runner), replay_runner.race_id.nunique()) == (17412, 1779)
    assert (len(replay_races), len(replay_sets)) == (1779, 10674)

    runner_out = INDEPENDENT / "independent_f1_replayed_runner_predictions.parquet"
    race_out = INDEPENDENT / "independent_f1_replayed_race_metrics.csv"
    sets_out = INDEPENDENT / "independent_f1_replayed_six_combinations.csv"
    for path in (runner_out, race_out, sets_out):
        assert not path.exists(), f"refusing to overwrite: {path}"
    replay_runner.to_parquet(runner_out, index=False)
    replay_races.to_csv(race_out, index=False)
    replay_sets.to_csv(sets_out, index=False)

    receipt_path = INDEPENDENT / "independent_feature_and_f1_replay_receipt.json"
    assert not receipt_path.exists(), f"refusing to overwrite: {receipt_path}"
    receipt = {
        "review_status": "candidate_features_and_frozen_f1_replay_independently_verified",
        "candidate_generation_and_replay_helpers_reused": False,
        "model_refit_count": 0,
        "candidate_model_fit_count": 0,
        "temperature_optimization_count": 0,
        "feature_checks": {
            "base_49_input_columns_exactly_unchanged": True,
            "exactly_6_additive_columns_in_fixed_order": additions,
            "all_52155_target_ids_in_original_order": True,
            "all_3_feature_means_and_valid_counts_match_independent_slot_reconstruction": feature_differences,
            "row_count": int(len(candidate_features)),
            "race_count": int(candidate_features.race_id.nunique()),
        },
        "frozen_f1_replay": {
            "model_count": 3,
            "rows": int(len(replay_runner)),
            "races": int(len(replay_races)),
            "race_days": int(replay_races.race_date.nunique()),
            "six_set_rows": int(len(replay_sets)),
            "stored_trees_and_temperature_by_year": replay_years,
            "all_probabilities_losses_race_metrics_and_top6_sets_match_frozen_f1": True,
            "all_replayed_outputs_match_candidate_replay": True,
        },
        "outputs": {
            runner_out.name: sha256(runner_out),
            race_out.name: sha256(race_out),
            sets_out.name: sha256(sets_out),
        },
        "references": {
            str(path.relative_to(ROOT)): {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (
                OUTPUTS["features"], OUTPUTS["candidate_preflight"],
                OUTPUTS["candidate_runner"], OUTPUTS["candidate_race"],
                OUTPUTS["candidate_sets"], OUTPUTS["candidate_replay"],
                OUTPUTS["f1_features"], OUTPUTS["f1_runner"], OUTPUTS["f1_race"], OUTPUTS["f1_sets"],
            )
        },
        "review_code_sha256": sha256(Path(__file__)),
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

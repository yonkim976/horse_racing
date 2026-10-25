"""Independently review and lock the approved three-year F1S fit scope.

This audit reads frozen artifacts and source files only. It does not import the
candidate harness, score a model, optimize temperature, or train a model.
"""
import sys

sys.dont_write_bytecode = True

import ast
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODEL_DIR = ROOT / "jeju/research/20261009_section_time_ablation_v1"
OUT = MODEL_DIR / "outputs"
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
F1_OUT = F1_DIR / "outputs"
BASE_RUN = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/run.py"
FIT_CODE = MODEL_DIR / "fit_candidate.py"
LOCK = OUT / "prefit_lock.json"
BEFORE = OUT / "before_fit_integrity_check.json"
PREFLIGHT = OUT / "fit_runner_preflight.json"
FEATURES = OUT / "features_f1s.parquet"
F1_FEATURES = F1_OUT / "features.parquet"
INDEPENDENT_FEATURE_REPLAY = HERE / "independent_outputs/independent_feature_and_f1_replay_receipt.json"
INDEPENDENT_SOURCE_REVIEW = HERE / "independent_outputs/independent_source_availability_receipt.json"
RECEIPT = HERE / "independent_fit_harness_review.json"
BOOTSTRAP_REPS = 2000
SEED = 20261008
YEARS = (2024, 2025, 2026)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_info(path):
    return {"bytes": Path(path).stat().st_size, "sha256": sha256(path)}


def literal_assignments(tree):
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
    return values


def keyword_dict_assignment(tree, name, literals):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            assert isinstance(node.value, ast.Call) and call_name(node.value.func) == "dict"
            values = {}
            for keyword in node.value.keywords:
                if isinstance(keyword.value, ast.Name):
                    values[keyword.arg] = literals[keyword.value.id]
                else:
                    values[keyword.arg] = ast.literal_eval(keyword.value)
            return values
    raise AssertionError(f"missing assignment: {name}")


def call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def function_node(tree, name):
    found = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    assert len(found) == 1, name
    return found[0]


def hash_locked_references(lock):
    checked = []
    for relative, expected in lock["scoped_reference_sha256"].items():
        path = ROOT / relative
        observed = file_info(path) if path.is_file() else None
        assert observed == expected, {"path": relative, "expected": expected, "observed": observed}
        checked.append(relative)
    protected = {}
    for relative, expected in lock["protected_live_state_sha256"].items():
        path = ROOT / relative
        observed = file_info(path) if path.is_file() else None
        assert observed == expected, {"path": relative, "expected": expected, "observed": observed}
        protected[relative] = observed
    return checked, protected


def year_splits(features, frozen_meta, model_cats, model_features):
    result = {}
    for year in YEARS:
        train = features.year.between(2017, year - 3)
        valid = features.year.eq(year - 2)
        calibration = features.year.eq(year - 1)
        test = features.year.eq(year)
        masks = {"train": train, "valid": valid, "calibration": calibration, "test": test}
        assert all(mask.any() for mask in masks.values())
        assert not (train & valid).any() and not (valid & calibration).any()
        assert not (calibration & test).any()
        refit = train | valid

        vocab = {}
        for column in model_cats:
            if column in model_features:
                vocab[column] = sorted(features.loc[train, column].dropna().astype(str).unique().tolist())
        assert frozen_meta[str(year)]["vocabulary"] == vocab
        assert frozen_meta[str(year)]["parameters"] == frozen_meta["2024"]["parameters"]
        assert frozen_meta[str(year)]["seed"] == SEED

        race_weight_sums = {}
        for label, mask in (("initial_train", train), ("refit_train_valid", refit)):
            weighted = (1.0 / features.loc[mask, "field_n"]).groupby(features.loc[mask, "race_id"]).sum()
            assert np.allclose(weighted.to_numpy(dtype=float), 1.0, rtol=0, atol=1e-12)
            race_weight_sums[label] = {
                "races": int(len(weighted)),
                "max_abs_error_from_one": float((weighted - 1.0).abs().max()),
            }

        saved = frozen_meta[str(year)]
        assert int(saved["evaluation_year"]) == year
        assert saved["features"] == model_features[:-6]
        assert int(saved["trees"]) > 0
        result[str(year)] = {
            "initial_train_years": [2017, year - 3],
            "initial_train_rows": int(train.sum()),
            "initial_train_races": int(features.loc[train, "race_id"].nunique()),
            "early_stopping_year": year - 2,
            "early_stopping_rows": int(valid.sum()),
            "early_stopping_races": int(features.loc[valid, "race_id"].nunique()),
            "refit_through_year": year - 2,
            "refit_rows": int(refit.sum()),
            "refit_races": int(features.loc[refit, "race_id"].nunique()),
            "calibration_year": year - 1,
            "calibration_rows": int(calibration.sum()),
            "calibration_races": int(features.loc[calibration, "race_id"].nunique()),
            "evaluation_rows": int(test.sum()),
            "evaluation_races": int(features.loc[test, "race_id"].nunique()),
            "frozen_f1_tree_count": int(saved["trees"]),
            "race_weight_sums": race_weight_sums,
            "initial_train_vocabulary_exactly_matches_saved_f1": True,
            "same_params_and_seed_as_saved_f1": True,
        }
    assert [result[str(year)]["frozen_f1_tree_count"] for year in YEARS] == [92, 200, 200]
    return result


def main():
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    feature_replay = json.loads(INDEPENDENT_FEATURE_REPLAY.read_text(encoding="utf-8"))
    source_review = json.loads(INDEPENDENT_SOURCE_REVIEW.read_text(encoding="utf-8"))
    assert before["phase"] == "before_fit" and before["passed"]
    assert before["mismatches"] == []
    assert preflight["passed"] and preflight["fit_executed"] is False
    assert preflight["saved_model_scoring_executed"] is False
    assert preflight["temperature_optimization_executed"] is False
    assert preflight["prediction_metrics_calculated"] is False
    assert feature_replay["candidate_model_fit_count"] == 0
    assert feature_replay["temperature_optimization_count"] == 0
    assert source_review["audit_status"] == "independent_source_slot_availability_reconstruction"

    checked_refs, protected = hash_locked_references(lock)
    code_info = file_info(FIT_CODE)
    assert lock["scoped_reference_sha256"][str(FIT_CODE.relative_to(ROOT))] == code_info
    assert preflight["candidate_fit_code_sha256"] == code_info["sha256"]
    assert lock["fit_scope"]["candidate"] == "F1S"
    assert lock["fit_scope"]["evaluation_years"] == list(YEARS)
    assert lock["fit_scope"]["model_column_count"] == 30
    assert lock["fit_scope"]["lightgbm_train_calls"] == 6
    assert lock["fit_scope"]["temperature_optimizations"] == 3
    assert lock["fit_scope"]["additional_features_or_search"] is False
    assert lock["fit_scope"]["result_dependent_followup_fit"] is False
    assert lock["section_time_quality_evidence"]["unresolved_individual_order_fields"] == 70
    assert lock["section_time_quality_evidence"]["unresolved_group_points"] == 20
    assert lock["section_time_quality_evidence"]["unresolved_order_group_receipt_status"] == "rechecked_and_quality_hold_applied_and_verified"

    baseline_tree = ast.parse(BASE_RUN.read_text(encoding="utf-8"))
    baseline_assignments = literal_assignments(baseline_tree)
    assert baseline_assignments["SEED"] == SEED
    expected_params = keyword_dict_assignment(baseline_tree, "PARAMS", baseline_assignments)
    assert expected_params["seed"] == SEED

    fit_text = FIT_CODE.read_text(encoding="utf-8")
    fit_tree = ast.parse(fit_text)
    assignments = literal_assignments(fit_tree)
    assert tuple(assignments["YEARS"]) == YEARS
    assert assignments["BOOTSTRAP_REPS"] == BOOTSTRAP_REPS
    assert assignments["BOOTSTRAP_SEED"] == SEED
    fit_year_node = function_node(fit_tree, "fit_year")
    fit_year_calls = [node for node in ast.walk(fit_year_node) if isinstance(node, ast.Call)]
    all_calls = [node for node in ast.walk(fit_tree) if isinstance(node, ast.Call)]
    assert sum(call_name(node.func) == "lgb.train" for node in fit_year_calls) == 2
    assert sum(call_name(node.func) == "lgb.train" for node in all_calls) == 2
    assert sum(call_name(node.func) == "BASE.temperature" for node in fit_year_calls) == 1
    assert sum(call_name(node.func) == "BASE.temperature" for node in all_calls) == 1
    assert sum(call_name(node.func) == "BASE.evaluate" for node in fit_year_calls) == 1
    assert sum(call_name(node.func) == "BASE.evaluate" for node in all_calls) == 1
    preflight_node = function_node(fit_tree, "run_preflight")
    preflight_calls = [node for node in ast.walk(preflight_node) if isinstance(node, ast.Call)]
    assert not any(call_name(node.func) in {"lgb.train", "BASE.temperature", "model.predict", "BASE.evaluate"} for node in preflight_calls)
    assert "--root-approved" in fit_text and "training is gated" in fit_text

    original = pd.read_parquet(F1_FEATURES)
    candidate = pd.read_parquet(FEATURES)
    f1_2024_meta = json.loads((F1_OUT / "F1_2024/meta.json").read_text(encoding="utf-8"))
    base_features = f1_2024_meta["features"]
    expected_added = [
        "history_s1f_mean5_seconds", "history_s1f_valid_n",
        "history_g3f_mean5_seconds", "history_g3f_valid_n",
        "history_g1f_mean5_seconds", "history_g1f_valid_n",
    ]
    model_features = base_features + expected_added
    assert len(base_features) == 24 and len(model_features) == 30
    assert assignments["NEW_FEATURES"] == expected_added
    features_assignment = next(
        node for node in fit_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "FEATURES" for target in node.targets)
    )
    assert ast.dump(features_assignment.value, include_attributes=False) == ast.dump(
        ast.BinOp(left=ast.Name(id="BASE_FEATURES", ctx=ast.Load()), op=ast.Add(),
                  right=ast.Name(id="NEW_FEATURES", ctx=ast.Load())),
        include_attributes=False,
    )
    assert lock["fit_scope"]["model_columns"] == model_features
    assert list(candidate.columns) == list(original.columns) + expected_added
    assert candidate[original.columns].equals(original)
    assert len(candidate) == 52155 and candidate.race_id.nunique() == 5206
    assert len(original) == len(candidate)
    assert np.isfinite(candidate[expected_added].select_dtypes(include=[np.number]).to_numpy(dtype=float)[
        np.isfinite(candidate[expected_added].select_dtypes(include=[np.number]).to_numpy(dtype=float))
    ]).all()
    assert candidate["history_s1f_mean5_seconds"].isna().eq(candidate["history_s1f_valid_n"].eq(0)).all()
    assert candidate["history_g3f_mean5_seconds"].isna().eq(candidate["history_g3f_valid_n"].eq(0)).all()
    assert candidate["history_g1f_mean5_seconds"].isna().eq(candidate["history_g1f_valid_n"].eq(0)).all()

    model_cats = ["grade_raw", "previous_sex", "previous_result_status"]
    f1_meta = {
        str(year): json.loads((F1_OUT / f"F1_{year}/meta.json").read_text(encoding="utf-8"))
        for year in YEARS
    }
    assert f1_meta["2024"]["parameters"] == expected_params
    assert preflight["parameters"] == expected_params
    yearly = year_splits(candidate, f1_meta, model_cats, model_features)
    assert preflight["yearly_split_and_vocab_checks"] == {
        year: {
            "initial_train_years": data["initial_train_years"],
            "initial_train_rows": data["initial_train_rows"],
            "initial_train_races": data["initial_train_races"],
            "early_stop_year": data["early_stopping_year"],
            "early_stop_rows": data["early_stopping_rows"],
            "early_stop_races": data["early_stopping_races"],
            "refit_through_year": data["refit_through_year"],
            "refit_rows": data["refit_rows"],
            "refit_races": data["refit_races"],
            "calibration_year": int(year) - 1,
            "calibration_rows": data["calibration_rows"],
            "calibration_races": data["calibration_races"],
            "evaluation_rows": data["evaluation_rows"],
            "evaluation_races": data["evaluation_races"],
            "existing_f1_trees": data["frozen_f1_tree_count"],
            "category_vocabulary_matches_frozen_f1": True,
            "race_weight_sum_is_one": True,
        }
        for year, data in yearly.items()
    }

    # Confirm that the calibration and evaluation methods are the locked F1 functions.
    f1_run_text = (F1_DIR / "run.py").read_text(encoding="utf-8")
    assert "tau = OLD.temperature(calibration_data, cal_scores)" in f1_run_text
    assert "race_result, runner_result, ticket_result = OLD.evaluate(evaluation_data, test_scores, tau, variant)" in f1_run_text
    assert "tau = BASE.temperature(calibration, cal_scores)" in fit_text
    assert "race_result, runner_result, set_result = BASE.evaluate(" in fit_text

    assert lock["fit_executed"] is False
    assert lock["temperature_optimization_executed"] is False
    # The runner lock deliberately remains execution-pending until reviewer C
    # certifies these results and section_model records the final before-fit pass.
    pending_conditions = lock["approval_conditions"]
    assert pending_conditions["independent_fit_code_review_passed"] is False
    assert pending_conditions["before_fit_check_passed"] is False
    assert before["passed"] is True

    receipt = {
        "review_status": "independent_fit_code_review_pass",
        "reviewer": "section_review",
        "fit_or_scoring_executed": False,
        "new_model_fit_count": 0,
        "new_temperature_optimization_count": 0,
        "candidate_fit_code": {
            "path": str(FIT_CODE.relative_to(ROOT)),
            **code_info,
            "preflight_locked_code_sha256_matches": True,
            "prefit_lock_code_reference_matches": True,
        },
        "candidate_lock_and_before_fit": {
            "prefit_lock": {"path": str(LOCK.relative_to(ROOT)), **file_info(LOCK)},
            "before_fit_check": {"path": str(BEFORE.relative_to(ROOT)), **file_info(BEFORE)},
            "before_fit_passed": bool(before["passed"]),
            "scoped_reference_count": len(checked_refs),
            "protected_state_hashes_verified": protected,
            "fit_authorization_conditions_still_pending_until_candidate_lock_refresh": pending_conditions,
        },
        "independent_evidence": {
            "source_review_receipt": {"path": str(INDEPENDENT_SOURCE_REVIEW.relative_to(ROOT)), **file_info(INDEPENDENT_SOURCE_REVIEW)},
            "feature_and_saved_f1_replay_receipt": {"path": str(INDEPENDENT_FEATURE_REPLAY.relative_to(ROOT)), **file_info(INDEPENDENT_FEATURE_REPLAY)},
            "candidate_preflight": {"path": str(PREFLIGHT.relative_to(ROOT)), **file_info(PREFLIGHT)},
        },
        "reference_f1_procedure": {
            "parameter_match_to_original_baseline": True,
            "race_equal_weight_max_deviation": max(
                row["race_weight_sums"][name]["max_abs_error_from_one"]
                for row in yearly.values() for name in ("initial_train", "refit_train_valid")
            ),
            "training_call_count_in_reviewed_year_function": 2,
            "year_count": len(YEARS),
            "total_expected_lightgbm_train_calls": 6,
            "temperature_calls_per_year": 1,
            "total_expected_temperature_optimizations": 3,
            "calibration_and_evaluation_functions_match_frozen_f1": True,
            "saved_f1_tree_counts_by_year": {year: row["frozen_f1_tree_count"] for year, row in yearly.items()},
            "yearly_splits_and_vocab_and_weight_checks": yearly,
            "bootstrap_date_clusters_repetitions_seed": {
                "cluster": "race_date", "repetitions": BOOTSTRAP_REPS, "seed": SEED,
            },
            "feature_matrix_exactly_f1_24_plus_fixed_6": True,
            "f1_original_columns_and_values_unchanged": True,
            "candidate_feature_rows": int(len(candidate)),
            "candidate_feature_races": int(candidate.race_id.nunique()),
        },
        "static_fit_scope_checks": {
            "exactly_two_lgb_train_calls_in_one_year_fit_function": True,
            "no_other_lgb_train_calls_in_module": True,
            "one_temperature_call_and_one_f1_evaluator_call_per_year": True,
            "preflight_has_no_fit_score_temperature_or_metric_call": True,
            "explicit_root_approved_fit_gate_present": True,
            "only_three_fixed_evaluation_years": list(YEARS),
            "no_additional_feature_search_or_followup_fit_in_lock": True,
            "reviewed_inputs_and_protected_files_still_match_prefit_lock": True,
        },
        "review_code_sha256": sha256(Path(__file__)),
    }
    assert not RECEIPT.exists(), f"refusing to overwrite {RECEIPT}"
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

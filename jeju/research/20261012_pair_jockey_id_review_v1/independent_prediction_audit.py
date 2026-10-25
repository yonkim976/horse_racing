"""Independent reconstruction of the approved 60-column eval predictions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
REVIEW = Path(__file__).resolve().parent
STUDY = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
OUT = STUDY / "outputs"
BASE_STUDY = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
BASE_REVIEW = ROOT / "jeju/research/20261012_pair_jockey_basic_review_v1"
BASE_EXPANDED = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
PREDICTIONS_PATH = OUT / "evaluation_pair_predictions.parquet"
DIAGNOSTICS_PATH = OUT / "evaluation_race_probabilities.parquet"
PREDICTION_RECEIPT_PATH = OUT / "PREDICTION_RECEIPT.json"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT_PATH = OUT / "FIT_RECEIPT.json"
APPROVAL_PATH = OUT / "APPROVAL.json"
PREFLIGHT_PATH = OUT / "SOURCE_PREFLIGHT.json"
DRY_RUN_PATH = OUT / "DESIGN_DRY_RUN.json"
BASE_PREDICTIONS_PATH = BASE_STUDY / "outputs/evaluation_pair_predictions.parquet"
BASE_DIAGNOSTICS_PATH = BASE_STUDY / "outputs/evaluation_race_probabilities.parquet"
EVAL_YEARS = (2024, 2025, 2026)
KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]
EXPECTED_SCHEDULE_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_ROWS = 76848
EXPECTED_RACES = 1779
EXPECTED_DATES = 269
COMPARATORS = {
    "jockey_basic_candidate": "selected_jockey_basic_candidate",
    "latest_expanded_direct_pair_427": "selected_latest_pair",
    "old_direct_pair_426": "selected_old_direct",
    "H2_calibrated_p0_baseline": "selected_baseline",
    "raw_F1_STYLE6_score_Top2_429": "selected_raw_top2",
    "saved_F1_STYLE6_PTop3_Top2_429": "selected_saved_f1_top2",
    "existing_joint_marginal_Top2_434": "selected_candidate_joint_marginal_top2",
    "existing_candidate_max_joint_pair_422": "selected_candidate_joint_maxpair",
    "existing_matched_max_joint_pair_429": "selected_matched_joint_maxpair",
}
EXPECTED_HITS = {
    "jockey_basic_candidate": 429,
    "latest_expanded_direct_pair_427": 427,
    "old_direct_pair_426": 426,
    "H2_calibrated_p0_baseline": 429,
    "raw_F1_STYLE6_score_Top2_429": 429,
    "saved_F1_STYLE6_PTop3_Top2_429": 429,
    "existing_joint_marginal_Top2_434": 434,
    "existing_candidate_max_joint_pair_422": 422,
    "existing_matched_max_joint_pair_429": 429,
}


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def sha256(path: Path) -> str:
    require(not path.is_symlink(), f"input symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    require(not path.is_symlink(), f"input symlink is not allowed: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    require(not path.is_symlink(), f"reference symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"reference outside workspace: {path}")
    spec = importlib.util.spec_from_file_location(name, resolved)
    require(spec is not None and spec.loader is not None, f"cannot load reference: {resolved}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def import_frozen_auditors():
    sys.path.insert(0, str(BASE_REVIEW))
    basic_fit = load_module(
        "basic_independent_fit_audit_for_id_predictions",
        BASE_REVIEW / "independent_fit_audit.py",
    )
    basic_prediction = load_module(
        "basic_independent_prediction_audit_for_id_predictions",
        BASE_REVIEW / "independent_prediction_audit.py",
    )
    id_reference = load_module(
        "independent_pair_jockey_id_reference_for_prediction_audit",
        REVIEW / "independent_pair_jockey_id_reference.py",
    )
    id_fit_audit = load_module(
        "independent_pair_jockey_id_fit_audit_for_prediction_audit",
        REVIEW / "independent_fit_audit.py",
    )
    return basic_fit, basic_prediction, id_reference, id_fit_audit


def validate_lineage(basic_fit, id_fit_audit) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    approval = read_json(APPROVAL_PATH)
    preflight = read_json(PREFLIGHT_PATH)
    dry_run = read_json(DRY_RUN_PATH)
    fit = read_json(FIT_PATH)
    fit_receipt = read_json(FIT_RECEIPT_PATH)
    prediction_receipt = read_json(PREDICTION_RECEIPT_PATH)
    require(approval.get("approved") is True and approval.get("approved_by") == "root",
            "root approval is missing")
    require(approval.get("scope") == "pair_jockey_id_h1_h2_fit"
            and approval.get("h1_fit_count") == 3 and approval.get("h2_candidate_map_count") == 3
            and approval.get("horse_model_fits") == 0, "approval scope changed")
    for key, path in (
        ("plan_sha256", STUDY / "PLAN.md"),
        ("source_preflight_sha256", PREFLIGHT_PATH),
        ("source_preflight_code_sha256", STUDY / "source_preflight.py"),
        ("id_basis_sha256", STUDY / "pair_jockey_id_basis.py"),
        ("fit_code_sha256", STUDY / "pair_jockey_id_fit.py"),
        ("design_dry_run_sha256", DRY_RUN_PATH),
    ):
        require(approval.get(key) == sha256(path), f"approval hash changed: {key}")
    require(preflight.get("status") == "PASS"
            and preflight.get("finish_labels_read") is False
            and preflight.get("performance_metrics_computed") is False,
            "approved source preflight is not label-free PASS")
    require(dry_run.get("status") == "PASS" and dry_run.get("optimizer_runs") == 0
            and dry_run.get("calibration_fits") == 0
            and dry_run.get("performance_metrics_computed") is False,
            "pre-fit dry run scope changed")
    require(fit_receipt.get("status") == "PASS"
            and fit_receipt.get("approval_sha256") == sha256(APPROVAL_PATH)
            and fit_receipt.get("candidate_fit_sha256") == sha256(FIT_PATH),
            "fit receipt does not pin approved fit")
    require(prediction_receipt.get("status") == "PASS"
            and prediction_receipt.get("performance_metrics_computed") is False
            and prediction_receipt.get("fit_sha256") == sha256(FIT_PATH)
            and prediction_receipt.get("fit_receipt_sha256") == sha256(FIT_RECEIPT_PATH)
            and prediction_receipt.get("approval_sha256") == sha256(APPROVAL_PATH)
            and prediction_receipt.get("source_preflight_sha256") == sha256(PREFLIGHT_PATH),
            "prediction receipt lineage changed")
    require(prediction_receipt.get("pair_predictions_sha256") == sha256(PREDICTIONS_PATH)
            and prediction_receipt.get("race_diagnostics_sha256") == sha256(DIAGNOSTICS_PATH),
            "prediction output hash differs from receipt")
    require(prediction_receipt.get("fixed_basic_pair_reference_sha256") == sha256(BASE_PREDICTIONS_PATH),
            "prediction receipt fixed-basic reference hash changed")
    fit_audit_path = REVIEW / "independent_fit_audit.json"
    independent_fit = read_json(fit_audit_path)
    require(independent_fit.get("status") == "PASS"
            and independent_fit.get("candidate_fit_sha256") == sha256(FIT_PATH)
            and independent_fit.get("candidate_fit_receipt_sha256") == sha256(FIT_RECEIPT_PATH),
            "independent 60D fit audit is absent or stale")
    for relative, expected in preflight.get("source_hashes", {}).items():
        relative_path = Path(relative)
        require(not relative_path.is_absolute() and ".." not in relative_path.parts,
                "preflight source path is unsafe")
        require(sha256(ROOT / relative_path) == expected, f"pinned preflight source changed: {relative}")
    _, _, _, _, _ = basic_fit.verify_approved_artifacts()
    return fit, prediction_receipt, independent_fit


def _category_moments(fold: dict[str, Any]) -> dict[str, Any]:
    saved = fold["category_encoding"]
    vocab = tuple(map(str, saved["vocabulary_h1_only"]))
    require(len(vocab) == 39 and vocab == tuple(sorted(set(vocab))), "H1-only vocabulary changed")
    return {
        "vocabulary": vocab,
        "mu": np.asarray([saved["mu"][key] for key in vocab], dtype=float),
        "pi": np.asarray([saved["pi"][key] for key in vocab], dtype=float),
        "sigma": np.asarray([saved["sigma"][key] for key in vocab], dtype=float),
    }


def _get_candidate_beta(fold: dict[str, Any], basic_ref) -> np.ndarray:
    vocab = tuple(map(str, fold["category_encoding"]["vocabulary_h1_only"]))
    beta_by_basis = fold["beta_by_basis"]
    beta = np.asarray(
        [beta_by_basis[name] for name in basic_ref.ref.BASIS_NAMES]
        + [fold["gamma_jockey365_pair_sum"]]
        + [fold["theta_by_jockey_id"][key] for key in vocab], dtype=float,
    )
    require(beta.shape == (60,) and np.isfinite(beta).all(), "saved 60 coefficients invalid")
    return beta


def _comparator_pairs(frame: pd.DataFrame) -> dict[str, dict[str, tuple[int, int]]]:
    result: dict[str, dict[str, tuple[int, int]]] = {name: {} for name in COMPARATORS}
    for race_id, group in frame.groupby("race_id", sort=True):
        for name, selector in COMPARATORS.items():
            selected = group.loc[group[selector].astype(int).eq(1)]
            require(len(selected) == 1, f"legacy comparator selector {selector} not one/race: {race_id}")
            row = selected.iloc[0]
            result[name][str(race_id)] = (int(row["horse_i"]), int(row["horse_j"]))
    return result


def reconstruct_and_audit() -> dict[str, Any]:
    basic_fit, basic_prediction, id_ref, id_fit_audit = import_frozen_auditors()
    fit, prediction_receipt, independent_fit = validate_lineage(basic_fit, id_fit_audit)
    candidate = pd.read_parquet(PREDICTIONS_PATH)
    base = pd.read_parquet(BASE_PREDICTIONS_PATH)
    require(len(candidate) == len(base) == EXPECTED_ROWS, "pair prediction row count changed")
    require(not candidate.duplicated(KEYS).any() and not base.duplicated(KEYS).any(), "duplicate pair keys")
    require(candidate.groupby("race_id")["selected_jockey_id_candidate"].sum().eq(1).all(),
            "ID candidate selector is not exactly one/race")
    require(candidate.groupby("race_id")["selected_candidate"].sum().eq(1).all(),
            "legacy basic selector is not exactly one/race")
    require(candidate["race_id"].nunique() == EXPECTED_RACES
            and candidate["race_date"].nunique() == EXPECTED_DATES,
            "fixed evaluation inventory changed")

    base_join = base.merge(candidate, on=KEYS, how="outer", validate="one_to_one",
                           suffixes=("_basic", "_id"), indicator=True)
    require(base_join["_merge"].eq("both").all(), "candidate pair key set differs from approved basic reference")
    preserved = [
        "score_i", "score_j", "p0", "eta", "candidate_raw_probability", "candidate_calibrated_probability",
        "baseline_calibrated_probability", "y_pair", "selected_candidate", "selected_baseline",
        "selected_raw_top2", "selected_saved_f1_top2", "selected_candidate_joint_marginal_top2",
        "selected_candidate_joint_maxpair", "selected_matched_joint_maxpair", "expanded_eta",
        "expanded_candidate_raw_probability", "expanded_candidate_calibrated_probability",
        "selected_expanded_candidate", "old_direct_eta", "old_direct_candidate_raw_probability",
        "old_direct_candidate_calibrated_probability", "selected_old_direct", "candidate_eta",
        "jockey365_n_i", "jockey365_n_j", "jockey365_d_i", "jockey365_d_j", "jockey365_pair_sum",
        "jockey365_pair_z", "latest_pair_eta", "latest_pair_raw_probability",
        "latest_pair_calibrated_probability", "selected_latest_pair", "old_direct_calibrated_probability",
        "selected_jockey_basic_candidate",
    ]
    preserved_exact: dict[str, bool] = {}
    for field in preserved:
        left, right = base_join[f"{field}_basic"], base_join[f"{field}_id"]
        if pd.api.types.is_numeric_dtype(left.dtype):
            exact = np.array_equal(left.to_numpy(), right.to_numpy())
        else:
            exact = left.astype(str).equals(right.astype(str))
        require(exact, f"frozen basic output changed: {field}")
        preserved_exact[field] = exact

    receipt = read_json(PREDICTION_RECEIPT_PATH)
    yearly, all_event_rows, score_hashes = basic_prediction.load_evaluation_rows(receipt)
    fit_by_year = {int(row["evaluation_year"]): row for row in fit["folds"]}
    baseline_fit = basic_fit.verify_approved_artifacts()[4]
    baseline_by_year = {int(row["evaluation_year"]): row for row in baseline_fit["folds"]}
    baseline_h2 = read_json(BASE_EXPANDED / "outputs/expanded_h2_calibration.json")
    baseline_maps = {
        int(row["evaluation_year"]): (float(row["A"]), float(row["B"]))
        for row in baseline_h2["fold_maps"] if row["map"] == "baseline"
    }
    expected_rows: list[dict[str, Any]] = []
    expected_diag: dict[str, dict[str, Any]] = {}
    cat_contrib_max_abs = 0.0
    unknown_pair_count = 0
    for year in EVAL_YEARS:
        fold = fit_by_year[year]
        category_moments = _category_moments(fold)
        vocabulary = set(category_moments["vocabulary"])
        beta = _get_candidate_beta(fold, basic_fit)
        runner_moments = basic_fit.load_runner_moments(baseline_by_year[year])
        frozen20 = basic_fit.load_old_pair_moments(baseline_by_year[year])
        rolling = fold["frozen_21st_rolling_moment"]
        a_candidate = float(fold["h2_candidate_platt"]["A"])
        b_candidate = float(fold["h2_candidate_platt"]["B"])
        require(b_candidate > 0.0, f"candidate calibrator slope is not positive in {year}")
        year_rows = yearly[year]
        for race_id, frame in year_rows.groupby("race_id", sort=True):
            race = frame.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
            numbers = race["horse_number"].astype(int).tolist()
            finishes = race["finish_position"].astype(int).tolist()
            require(len(race) == int(race["field_n"].iloc[0])
                    and sorted(finishes) == list(range(1, len(race) + 1)),
                    f"evaluation roster/ranks invalid: {race_id}")
            require(sum(place <= 3 for place in finishes) == 3, f"Top3 label count changed: {race_id}")
            runner_values = {name: race[name].to_numpy() for name in basic_prediction.ref.RUNNER_COLUMNS}
            rolling_by_horse = {int(row.horse_number): float(row.d_independent)
                                for row in race.itertuples(index=False)}
            id_by_horse = {int(row.horse_number): str(row.jockey_id)
                           for row in race.itertuples(index=False)}
            unknown_runners = sum(jockey_id not in vocabulary for jockey_id in id_by_horse.values())
            unknown_pair_count += unknown_runners
            predict = id_ref.predict_race_60d(
                numbers, race["score"].to_numpy(dtype=float), runner_values, rolling_by_horse, id_by_horse,
                runner_moments, frozen20, rolling, category_moments, beta, (a_candidate, b_candidate),
            )
            p0_by_pair = predict["p0"]
            eta = predict["eta"]
            base_a, base_b = baseline_maps[year]
            base_probability = basic_prediction.ref.sigmoid(
                base_a + base_b * basic_prediction.ref.logit(p0_by_pair),
            )
            pair_labels = basic_prediction.ref.pair_label(dict(zip(numbers, finishes, strict=True)), predict["pairs"])
            score_by_horse = {int(row.horse_number): float(row.score)
                              for row in race.itertuples(index=False)}
            horse_index = {horse: idx for idx, horse in enumerate(numbers)}
            known_by_horse = {horse: int(jockey_id in vocabulary)
                              for horse, jockey_id in id_by_horse.items()}
            expected_diag[str(race_id)] = {
                "race_id": str(race_id), "race_date": race["race_date"].iloc[0].date().isoformat(),
                "evaluation_year": year, "distance_m": int(race["distance_m"].iloc[0]),
                "jockey_id_candidate_sum_probability_minus_3": float(np.sum(predict["candidate_calibrated_probability"]) - 3.0),
                "known_id_runner_count": int(sum(known_by_horse.values())),
                "unknown_id_runner_count": int(unknown_runners),
            }
            for idx, (horse_i, horse_j) in enumerate(predict["pairs"]):
                id_contribution = float(predict["standardized_basis_60"][idx, 21:] @ beta[21:])
                raw_eta = float(basic_prediction.ref.logit(p0_by_pair[idx])
                                 + predict["standardized_basis_60"][idx, :21] @ beta[:21])
                require(abs(float(eta[idx]) - (raw_eta + id_contribution)) <= 1e-12,
                        f"independent ID contribution fails additive check: {race_id}/{horse_i}/{horse_j}")
                cat_contrib_max_abs = max(cat_contrib_max_abs, abs(id_contribution))
                pair_known = known_by_horse[horse_i] + known_by_horse[horse_j]
                expected_rows.append({
                    "race_id": str(race_id), "race_date": race["race_date"].iloc[0].date().isoformat(),
                    "evaluation_year": year, "distance_m": int(race["distance_m"].iloc[0]),
                    "horse_i": horse_i, "horse_j": horse_j,
                    "score_i": score_by_horse[horse_i], "score_j": score_by_horse[horse_j],
                    "p0": float(p0_by_pair[idx]), "eta": float(eta[idx]),
                    "candidate_raw_probability": float(predict["candidate_raw_probability"][idx]),
                    "candidate_calibrated_probability": float(predict["candidate_calibrated_probability"][idx]),
                    "baseline_calibrated_probability": float(base_probability[idx]),
                    "y_pair": int(pair_labels[idx]),
                    "selected_candidate": int((horse_i, horse_j) == predict["selected_candidate"]),
                    "known_runner_count_pair": int(pair_known),
                    "category_logit_contribution": id_contribution,
                    "rolling_n_i": int(race.iloc[horse_index[horse_i]]["n_independent"]),
                    "rolling_n_j": int(race.iloc[horse_index[horse_j]]["n_independent"]),
                    "rolling_d_i": rolling_by_horse[horse_i], "rolling_d_j": rolling_by_horse[horse_j],
                    "rolling_pair_sum": rolling_by_horse[horse_i] + rolling_by_horse[horse_j],
                    "rolling_pair_z": float(predict["standardized_basis_60"][idx, 20]),
                })

    expected = pd.DataFrame(expected_rows)
    joined = candidate.merge(expected, on=KEYS, how="outer", validate="one_to_one",
                             suffixes=("_saved", "_independent"), indicator=True)
    require(joined["_merge"].eq("both").all(), "independently reconstructed evaluation pair keys differ")
    def joined_column(name: str, suffix: str) -> str:
        suffixed = f"{name}_{suffix}"
        return suffixed if suffixed in joined.columns else name

    continuous = {
        "score_i": 0.0, "score_j": 0.0, "p0": 1e-14,
        "baseline_calibrated_probability": 1e-11, "jockey_id_candidate_eta": 1e-10,
        "jockey_id_candidate_raw_probability": 2e-12,
        "jockey_id_candidate_calibrated_probability": 2e-12,
        "jockey_id_category_logit_contribution": 1e-10,
        "jockey365_d_i": 1e-11, "jockey365_d_j": 1e-11,
        "jockey365_pair_sum": 2e-11, "jockey365_pair_z": 1e-9,
    }
    max_errors: dict[str, float] = {}
    for field, tolerance in continuous.items():
        saved_field = field
        expected_field = field
        if field.startswith("jockey_id_candidate_"):
            expected_field = {
                "jockey_id_candidate_eta": "eta",
                "jockey_id_candidate_raw_probability": "candidate_raw_probability",
                "jockey_id_candidate_calibrated_probability": "candidate_calibrated_probability",
            }[field]
        elif field == "jockey_id_category_logit_contribution":
            expected_field = "category_logit_contribution"
        elif field.startswith("jockey365_"):
            expected_field = field.removeprefix("jockey365_")
            expected_field = {
                "n_i": "rolling_n_i", "n_j": "rolling_n_j", "d_i": "rolling_d_i",
                "d_j": "rolling_d_j", "pair_sum": "rolling_pair_sum", "pair_z": "rolling_pair_z",
            }.get(expected_field, expected_field)
        error = (joined[joined_column(saved_field, "saved")].astype(float)
                 - joined[joined_column(expected_field, "independent")].astype(float)).abs()
        max_errors[field] = float(error.max())
        require(max_errors[field] <= tolerance,
                f"saved ID candidate field differs from independent reconstruction: {field} max={max_errors[field]}")
    for saved_field, expected_field in (
        ("selected_jockey_id_candidate", "selected_candidate"),
        ("jockey_id_known_runner_count_pair", "known_runner_count_pair"),
        ("y_pair", "y_pair"),
    ):
        require(joined[joined_column(saved_field, "saved")].astype(int).equals(
            joined[joined_column(expected_field, "independent")].astype(int)),
                f"saved candidate field differs from independent reconstruction: {saved_field}")
    require(candidate["selected_candidate"].astype(int).equals(candidate["selected_jockey_basic_candidate"].astype(int)),
            "legacy selected-candidate alias changed")
    # A distinct categorical fit can select another pair; compare only its selector alias to raw ETA argmax.
    for race_id, group in candidate.groupby("race_id", sort=True):
        selected = group.loc[group["selected_jockey_id_candidate"].astype(int).eq(1)]
        require(len(selected) == 1, f"ID selector is not unique: {race_id}")
        max_eta = group["jockey_id_candidate_eta"].astype(float).max()
        tied = group.loc[group["jockey_id_candidate_eta"].astype(float).eq(max_eta)]
        tie_key = min((int(row.horse_i), int(row.horse_j)) for row in tied.itertuples(index=False))
        actual_key = (int(selected.iloc[0]["horse_i"]), int(selected.iloc[0]["horse_j"]))
        require(actual_key == tie_key, f"ID selector does not implement canonical ETA argmax: {race_id}")

    diag = pd.read_parquet(DIAGNOSTICS_PATH)
    basic_diag = pd.read_parquet(BASE_DIAGNOSTICS_PATH)
    diag_join = basic_diag.merge(diag, on=["race_id", "race_date", "evaluation_year", "distance_m"],
                                 how="outer", validate="one_to_one", suffixes=("_basic", "_id"), indicator=True)
    require(diag_join["_merge"].eq("both").all() and diag["race_id"].astype(str).nunique() == EXPECTED_RACES,
            "race diagnostic keys differ")
    for field in (
        "old_direct_candidate_sum_calibrated_pair_probability_minus_3",
        "baseline_sum_calibrated_pair_probability_minus_3", "old_direct_candidate_abs_sum_deviation",
        "baseline_abs_sum_deviation", "latest_pair_sum_probability_minus_3", "latest_pair_abs_sum_deviation",
        "jockey_basic_candidate_sum_probability_minus_3", "jockey_basic_candidate_abs_sum_deviation",
    ):
        require(np.array_equal(diag_join[f"{field}_basic"].to_numpy(), diag_join[f"{field}_id"].to_numpy()),
                f"frozen basic race diagnostic changed: {field}")
    diag_by_id = diag.set_index(diag["race_id"].astype(str))
    diag_max_error = 0.0
    for race_id, record in expected_diag.items():
        row = diag_by_id.loc[race_id]
        for key in ("race_date", "evaluation_year", "distance_m", "known_id_runner_count", "unknown_id_runner_count"):
            require(str(row[key]) == str(record[key]), f"race diagnostic metadata changed: {race_id}/{key}")
        error = abs(float(row["jockey_id_candidate_sum_probability_minus_3"])
                    - record["jockey_id_candidate_sum_probability_minus_3"])
        diag_max_error = max(diag_max_error, error)
        require(error <= 1e-12, f"ID probability-mass diagnostic differs: {race_id}")
    require(unknown_pair_count == 0 and int(receipt.get("unknown_jockey_runner_count", -1)) == 0,
            "evaluation has unknown jockey IDs; the receipt expected none")

    comparator_pairs = _comparator_pairs(candidate)
    id_candidate_pairs: dict[str, tuple[int, int]] = {}
    for race_id, group in candidate.groupby("race_id", sort=True):
        chosen = group.loc[group["selected_jockey_id_candidate"].astype(int).eq(1)].iloc[0]
        id_candidate_pairs[str(race_id)] = (int(chosen["horse_i"]), int(chosen["horse_j"]))
    comparator_pairs["pair_jockey_id_candidate"] = id_candidate_pairs
    norms = []
    for row in candidate.to_dict(orient="records"):
        norms.append({
            "race_id": str(row["race_id"]), "race_date": str(row["race_date"]),
            "evaluation_year": int(row["evaluation_year"]), "distance_m": int(row["distance_m"]),
            "horse_a": int(row["horse_i"]), "horse_b": int(row["horse_j"]),
            "score_a": float(row["score_i"]), "score_b": float(row["score_j"]),
            "p0": float(row["p0"]), "eta": float(row["jockey_id_candidate_eta"]),
            "candidate_calibrated_probability": float(row["jockey_id_candidate_calibrated_probability"]),
            "baseline_calibrated_probability": float(row["baseline_calibrated_probability"]),
            "y_pair": int(row["y_pair"]),
            "candidate_selected": bool(row["selected_jockey_id_candidate"]),
        })
    candidate_platt = {
        year: (float(fit_by_year[year]["h2_candidate_platt"]["A"]),
               float(fit_by_year[year]["h2_candidate_platt"]["B"]))
        for year in EVAL_YEARS
    }
    baseline_platt = baseline_maps
    schedule = id_ref.basic.load_frozen_date_bootstrap_schedule(candidate["race_date"].astype(str).tolist())
    require(sha256(id_ref.basic.SCHEDULE_PATH) == EXPECTED_SCHEDULE_SHA256,
            "saved bootstrap schedule is not the pinned file")
    evaluation = basic_prediction.ref.evaluate_prediction_records(
        norms, comparator_pairs, candidate_platt, baseline_platt, schedule,
    )
    hits = {name: int(value["hits"]) for name, value in evaluation["selected_pair_hit_rates"].items()}
    for name, expected_hits in EXPECTED_HITS.items():
        require(hits[name] == expected_hits, f"fixed comparator hits changed: {name}={hits[name]}")
    primary_key = "direct_candidate_minus_jockey_basic_candidate"
    raw_key = "direct_candidate_minus_raw_F1_STYLE6_score_Top2_429"
    primary_ci = evaluation["selected_pair_date_bootstrap"][primary_key]
    raw_ci = evaluation["selected_pair_date_bootstrap"][raw_key]
    report = read_json(OUT / "REPORT.json")
    report_primary = report["primary_incremental_gate_vs_saved_rolling_429"]
    report_raw = report["secondary_raw429_gate"]
    require(hits["pair_jockey_id_candidate"] == int(report_primary["candidate_hits"]),
            "independent candidate hit count differs from saved report")
    for independent, saved, label in (
        (primary_ci, report_primary["paired_date_bootstrap_95pct_ci"], "primary"),
        (raw_ci, report_raw["paired_date_bootstrap_95pct_ci"], "raw429"),
    ):
        for source_key, report_key in (("estimate", "estimate"), ("lower_95", "ci_low"), ("upper_95", "ci_high")):
            require(abs(float(independent[source_key]) - float(saved[report_key])) <= 1e-12,
                    f"independent {label} CI differs from saved report: {source_key}")
    def close(left: Any, right: Any, label: str, tolerance: float = 1e-12) -> None:
        require(abs(float(left) - float(right)) <= tolerance,
                f"independent {label} differs from saved report: {left} vs {right}")

    report_quality = report["probability_quality_separate_diagnostics"]
    for report_key, evaluation_key in (
        ("jockey_id_candidate", "candidate"),
        ("H2_calibrated_p0_baseline", "baseline"),
    ):
        saved_quality = report_quality[report_key]
        for report_metric, evaluation_metric in (
            ("all_pair", "all_pair_calibration"),
            ("selected_pair", "selected_pair_calibration"),
        ):
            saved = saved_quality[report_metric]
            computed = evaluation[evaluation_metric][evaluation_key]
            require(int(saved["races"]) == int(computed["races"]),
                    f"report {report_metric} race count differs for {report_key}")
            close(saved["brier"], computed["brier"], f"{report_key} {report_metric} Brier")
            close(saved["log_loss"], computed["log_loss"], f"{report_key} {report_metric} log loss")
        for report_field, evaluation_field in (
            ("all_pair_reliability", "all_pair_reliability"),
            ("selected_pair_reliability", "selected_pair_reliability"),
        ):
            saved_bins = saved_quality[report_field]
            computed_bins = evaluation[evaluation_field][evaluation_key]
            require(len(saved_bins) == len(computed_bins), f"report reliability bin count differs for {report_key}/{report_field}")
            for index, (saved, computed) in enumerate(zip(saved_bins, computed_bins, strict=True)):
                for saved_key, computed_key in (("pairs", "pairs"), ("races", "races")):
                    require(int(saved[saved_key]) == int(computed[computed_key]),
                            f"report reliability {saved_key} differs for {report_key}/{report_field}/{index}")
                for saved_key, computed_key in (("predicted", "mean_prediction"),
                                                ("observed", "observed_rate"),
                                                ("total_weight", "weight_sum")):
                    if saved[saved_key] is None:
                        require(computed[computed_key] is None,
                                f"report reliability null differs for {report_key}/{report_field}/{index}")
                    else:
                        close(saved[saved_key], computed[computed_key],
                              f"{report_key} {report_field} bin {index} {saved_key}")

    threshold_saved = report["selected_probability_at_least_0_20"]["jockey_id_candidate"]
    threshold_computed = evaluation["selected_probability_ge_0_20"]
    require(int(threshold_saved["coverage_count"]) == int(threshold_computed["eligible_races"])
            and int(threshold_saved["selected_races"]) == EXPECTED_RACES,
            "selected-probability threshold coverage differs from saved report")
    close(threshold_saved["coverage"], threshold_computed["coverage"], "selected probability coverage")
    close(threshold_saved["hit_rate"], threshold_computed["hit_rate"], "selected probability hit rate")
    for computed_key, report_key in (("estimate", "estimate"), ("lower_95", "ci_low"), ("upper_95", "ci_high")):
        close(threshold_computed["date_bootstrap"][computed_key],
              threshold_saved["date_cluster_ci"][report_key], f"selected probability CI {computed_key}")
    report_sum = report["sum_pair_probability_minus_three_diagnostics"]
    computed_sum = evaluation["sum_calibrated_pair_probability_minus_3"]
    for report_key, evaluation_key in (("jockey_id_candidate", "candidate"),
                                       ("H2_calibrated_p0_baseline", "baseline")):
        saved, computed = report_sum[report_key], computed_sum[evaluation_key]
        close(saved["signed_mean"], computed["mean_signed"], f"{report_key} sum signed mean")
        close(saved["absolute_mean"], computed["mean_absolute"], f"{report_key} sum absolute mean")
        close(saved["absolute_p95"], computed["p95_absolute"], f"{report_key} sum absolute p95")
    return {
        "status": "PASS",
        "scope": "independent all-pair 60D score reconstruction, frozen comparator preservation, saved-schedule metrics and CI",
        "approval_sha256": sha256(APPROVAL_PATH),
        "approved_source_preflight_sha256": sha256(PREFLIGHT_PATH),
        "candidate_fit_sha256": sha256(FIT_PATH),
        "candidate_fit_receipt_sha256": sha256(FIT_RECEIPT_PATH),
        "prediction_receipt_sha256": sha256(PREDICTION_RECEIPT_PATH),
        "prediction_sha256": sha256(PREDICTIONS_PATH),
        "diagnostics_sha256": sha256(DIAGNOSTICS_PATH),
        "frozen_basic_prediction_sha256": sha256(BASE_PREDICTIONS_PATH),
        "frozen_schedule_sha256": EXPECTED_SCHEDULE_SHA256,
        "saved_report_sha256": sha256(OUT / "REPORT.json"),
        "evaluation_score_source_hashes": score_hashes,
        "candidate_pair_rows": len(candidate), "evaluation_races": int(candidate["race_id"].nunique()),
        "evaluation_dates": int(candidate["race_date"].nunique()),
        "unknown_jockey_runner_count": unknown_pair_count,
        "max_abs_error_vs_independent_60d_prediction": max_errors,
        "maximum_abs_category_logit_contribution": cat_contrib_max_abs,
        "frozen_basic_prediction_columns_exact": preserved_exact,
        "race_diagnostic_max_abs_error": diag_max_error,
        "comparator_hits": hits,
        "candidate_hits": int(evaluation["selected_pair_hit_rates"]["direct_candidate"]["hits"]),
        "primary_saved_rolling_difference": primary_ci,
        "raw_top2_gate_difference": raw_ci,
        "primary_latest_pair_gate_pass": bool(primary_ci["estimate"] > 0 and primary_ci["lower_95"] > 0),
        "raw_top2_gate_pass": bool(raw_ci["estimate"] > 0 and raw_ci["lower_95"] > 0),
        "independent_evaluation_report": {key: value for key, value in evaluation.items() if key != "selector_pairs"},
        "saved_report_proper_loss_reliability_threshold_and_mass_checks": "PASS",
        "bootstrap_schedule_receipt": basic_prediction.ref.date_bootstrap_schedule_receipt(schedule),
        "optimizer_calls": 0,
    }


def main() -> None:
    result = reconstruct_and_audit()
    result["review_script_sha256"] = sha256(Path(__file__).resolve())
    output = REVIEW / "independent_prediction_audit.json"
    require(not output.exists() and not output.is_symlink(), "refusing to overwrite independent prediction audit")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "candidate_hits": result["candidate_hits"],
        "comparator_hits": result["comparator_hits"],
        "primary_saved_rolling_difference": result["primary_saved_rolling_difference"],
        "raw_top2_gate_difference": result["raw_top2_gate_difference"],
        "max_abs_error_vs_independent_60d_prediction": result["max_abs_error_vs_independent_60d_prediction"],
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

"""Approval-gated single-arm H1/H2 pair reliability experiment.

Default execution is inert. ``design-dry-run`` audits H1/H2 design construction
without an optimizer, calibrator, evaluation prediction, or performance metric.
``fit-approved`` is blocked unless root has pinned the current plan, source,
design, and implementation hashes in outputs/APPROVAL.json.
"""

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
from scipy.optimize import minimize
from scipy.special import expit, logit

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261014_pair_reliability_v1"
OUT = STUDY / "outputs"
PLAN = STUDY / "PLAN.md"
PREFLIGHT_SCRIPT = STUDY / "source_preflight.py"
PREFLIGHT = OUT / "SOURCE_PREFLIGHT.json"
DRY_RUN = OUT / "DESIGN_DRY_RUN.json"
APPROVAL = OUT / "APPROVAL.json"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BASE = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
BASIC = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
ID = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
BASIC_FIT_CODE = BASIC / "pair_jockey_fit.py"
ID_FIT_CODE = ID / "pair_jockey_id_fit.py"
ID_BASIS_CODE = ID / "pair_jockey_id_basis.py"
BASELINE_FIT = BASE / "outputs/expanded_h1_fit.json"
BASIC_FIT = BASIC / "outputs/FIT.json"
ID_FIT = ID / "outputs/FIT.json"
FIT_YEARS = (2024, 2025, 2026)
H1_RACES = {2024: 2147, 2025: 2818, 2026: 3458}
H2_RACES = {2024: 336, 2025: 311, 2026: 325}
ID_VOCABULARY_SIZE = 39
MODEL_SCOPE = "pair_reliability_h1_h2_fit"
OLD_ROLLING_BASIS_NAME = "jockey365_past_field_relative_top3_sum"


class ReliabilityFitError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ReliabilityFitError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"input symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    require(spec is not None and spec.loader is not None, f"cannot load pinned helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    encoded = json.dumps(_json_safe(value), ensure_ascii=False, indent=2, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.write("\n")


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def load_runtime():
    basic_fit = import_module("reliability_basic_fit_helper", BASIC_FIT_CODE)
    core, pair_fit, jockey_input, historical = basic_fit.load_helpers()
    id_fit = import_module("reliability_id_fit_helper", ID_FIT_CODE)
    id_basis = import_module("reliability_id_basis_helper", ID_BASIS_CODE)
    reliability_basis = import_module("reliability_pair_basis", STUDY / "pair_reliability_basis.py")
    return core, pair_fit, basic_fit, jockey_input, historical, id_fit, id_basis, reliability_basis


def _typed_feature_source() -> pd.DataFrame:
    columns = [
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
        "distance_m", "history_cutoff", "observed_starts", "same_starts", "same_valid_times",
        "days_since_same", "mean5_s", "valid_n5", "std5_s",
    ]
    frame = pd.read_parquet(
        checked(FEATURES), columns=columns,
        filters=[("year", ">=", 2019), ("year", "<=", 2025)],
    )
    for column in ("api_record_id", "race_id", "horse_id"):
        frame[column] = frame[column].astype("string")
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce").dt.normalize()
    frame["history_cutoff"] = pd.to_datetime(frame["history_cutoff"], errors="coerce").dt.normalize()
    require(frame["api_record_id"].notna().all() and frame["api_record_id"].is_unique,
            "frozen feature api_record_id is missing or duplicated")
    require(frame["race_id"].notna().all() and frame["horse_id"].notna().all()
            and frame["race_date"].notna().all(), "frozen feature join keys are missing")
    require((frame["history_cutoff"] == frame["race_date"] - pd.Timedelta(days=2)).all(),
            "frozen feature history cutoff differs from T-2")
    return frame


def _attach_reliability_features(yearly: dict[int, pd.DataFrame]) -> dict[int, pd.DataFrame]:
    features = _typed_feature_source()
    attached: dict[int, pd.DataFrame] = {}
    keys = ("race_id", "horse_id", "race_date", "horse_number")
    history_columns = (
        "observed_starts", "same_starts", "same_valid_times", "days_since_same",
        "mean5_s", "valid_n5", "std5_s",
    )
    for year, roster in yearly.items():
        left = roster.copy()
        for column in ("api_record_id", "race_id", "horse_id"):
            left[column] = left[column].astype("string")
        left["race_date"] = pd.to_datetime(left["race_date"], errors="coerce").dt.normalize()
        right = features.loc[features["year"].eq(year)].copy()
        require(left["api_record_id"].notna().all() and left["api_record_id"].is_unique,
                f"training roster api key missing or duplicated: {year}")
        require(right["api_record_id"].is_unique, f"source api key duplicated: {year}")
        require(set(left["api_record_id"]) == set(right["api_record_id"]),
                f"training/source api key coverage differs: {year}")
        merged = left.merge(
            right[["api_record_id", *keys, "distance_m", "history_cutoff", *history_columns]],
            on="api_record_id", how="left", validate="one_to_one", suffixes=("", "_source"),
        )
        for column in keys:
            # The source value is authoritative; compare the corresponding roster value
            # when it exists, otherwise use source keys only after the API-key join.
            if column in left.columns:
                left_values = merged[column]
                right_values = merged[f"{column}_source"]
                if column == "horse_number":
                    left_values = pd.to_numeric(left_values, errors="coerce")
                    right_values = pd.to_numeric(right_values, errors="coerce")
                    matches = left_values.eq(right_values).all()
                elif column == "race_date":
                    matches = left_values.eq(right_values).all()
                else:
                    matches = left_values.astype("string").eq(right_values.astype("string")).all()
                require(left_values.notna().all() and right_values.notna().all() and matches,
                        f"API-key source {column} mismatch: {year}")
            else:
                require(merged[column].notna().all(), f"source {column} is missing: {year}")
        require(merged["distance_m"].notna().all(), f"source distance is missing: {year}")
        require(merged["history_cutoff"].notna().all()
                and (merged["history_cutoff"] == merged["race_date_source"] - pd.Timedelta(days=2)).all(),
                f"joined source is not exactly T-2: {year}")
        require(len(merged) == len(left) and merged["api_record_id"].is_unique,
                f"source attach changed training roster coverage: {year}")
        # No outcomes or market fields are attached from the feature source.
        attached[year] = merged
    return attached


def _saved_model_documents():
    baseline = json.loads(checked(BASELINE_FIT).read_text(encoding="utf-8"))
    basic = json.loads(checked(BASIC_FIT).read_text(encoding="utf-8"))
    current_id = json.loads(checked(ID_FIT).read_text(encoding="utf-8"))
    require(isinstance(baseline.get("folds"), list) and len(baseline["folds"]) == 3
            and basic.get("status") == "PASS" and current_id.get("status") == "PASS",
            "frozen comparison fit is not complete and PASS")
    require(basic.get("h1_fit_count") == current_id.get("h1_fit_count") == 3
            and basic.get("h2_candidate_map_count") == current_id.get("h2_candidate_map_count") == 3,
            "frozen rolling or ID fit count changed")
    return baseline, basic, current_id


def _old_60_design(core, basic_fit, id_basis, pair_fit, h1_races, h2_races,
                   baseline_fold, basic_fold, id_fold):
    require(basic_fold["old_pair_moments"] == baseline_fold["pair_standardization"],
            "saved rolling model no longer uses frozen style moments")
    rolling_moment = basic_fold["new_pair_moment"]
    runner_stats, old_pair_stats = basic_fit.stats_from_baseline(core, baseline_fold)
    x21_h1, p0_h1, y_h1, race_h1 = basic_fit.transform_candidate_basis(
        core, h1_races, old_pair_stats, rolling_moment,
    )
    x21_h2, p0_h2, y_h2, race_h2 = basic_fit.transform_candidate_basis(
        core, h2_races, old_pair_stats, rolling_moment,
    )
    category = id_fold["category_encoding"]
    vocabulary = tuple(category["vocabulary_h1_only"])
    require(len(vocabulary) == ID_VOCABULARY_SIZE and len(set(vocabulary)) == len(vocabulary),
            "frozen ID H1 vocabulary changed")
    require(all(key in category["pi"] and key in category["sigma"] for key in vocabulary),
            "frozen ID category moments are incomplete")
    pi = np.asarray([category["pi"][key] for key in vocabulary], dtype=np.float64)
    sigma = np.asarray([category["sigma"][key] for key in vocabulary], dtype=np.float64)
    moments = {"pi": pi, "sigma": sigma}
    cat_h1 = id_basis.race_pair_basis
    x_id_h1 = np.vstack([cat_h1(race["rows"], race["pairs"], vocabulary, pi, sigma) for race in h1_races])
    x_id_h2 = np.vstack([cat_h1(race["rows"], race["pairs"], vocabulary, pi, sigma) for race in h2_races])
    x60_h1 = np.column_stack((x21_h1, x_id_h1))
    x60_h2 = np.column_stack((x21_h2, x_id_h2))
    require(x60_h1.shape == (len(y_h1), 60) and x60_h2.shape == (len(y_h2), 60),
            "frozen 60-column design shape changed")
    require(np.isfinite(x60_h1).all() and np.isfinite(x60_h2).all(),
            "frozen 60-column design contains non-finite values")
    require(np.array_equal(x60_h1[:, :21], x21_h1) and np.array_equal(x60_h2[:, :21], x21_h2),
            "frozen 21-column design changed")
    return {
        "runner_stats": runner_stats,
        "old_pair_stats": old_pair_stats,
        "rolling_moment": rolling_moment,
        "vocabulary": vocabulary,
        "category_moments": moments,
        "x_h1": x60_h1, "p0_h1": p0_h1, "y_h1": y_h1, "race_h1": race_h1,
        "x_h2": x60_h2, "p0_h2": p0_h2, "y_h2": y_h2, "race_h2": race_h2,
    }


def _race_raw_reliability(reliability_basis, races: list[dict[str, Any]]) -> list[np.ndarray]:
    result = [reliability_basis.race_pair_basis(race["rows"], race["pairs"]) for race in races]
    require(bool(result) and all(x.shape == (len(race["pairs"]), 7)
                                 for x, race in zip(result, races, strict=True)),
            "invalid seven-column reliability race design")
    return result


def run_design_dry_run() -> None:
    require(PREFLIGHT.is_file(), "source preflight must run before design dry-run")
    source_record = json.loads(checked(PREFLIGHT).read_text(encoding="utf-8"))
    require(source_record.get("status") == "PASS"
            and source_record.get("finish_labels_read") is False
            and source_record.get("evaluation_target_labels_read") is False,
            "source preflight is not a label-free PASS")
    preflight_module = import_module("reliability_source_preflight", PREFLIGHT_SCRIPT)
    require(preflight_module.collect() == source_record,
            "current source/preflight lineage differs from the saved preflight")
    _, evaluation_yearly, _, _ = preflight_module._score_lineage(preflight_module._read_features())
    core, pair_fit, basic_fit, jockey_input, historical, _, id_basis, reliability_basis = load_runtime()
    baseline, basic_doc, id_doc = _saved_model_documents()
    yearly, _ = basic_fit.prepare_training_rows(pair_fit, jockey_input, historical)
    yearly = _attach_reliability_features(yearly)
    fold_summary: dict[str, Any] = {}
    for year in FIT_YEARS:
        h1, h2 = basic_fit.split_h1_h2(yearly, year)
        require(h1["race_id"].nunique() == H1_RACES[year] and h2["race_id"].nunique() == H2_RACES[year],
                f"H1/H2 split changed: {year}")
        h1_dates = h1.groupby("race_id")["race_date"].first()
        h2_dates = h2.groupby("race_id")["race_date"].first()
        evaluation = evaluation_yearly[year]
        require(h1_dates.max() <= h2_dates.min() - pd.Timedelta(days=2), f"H1/H2 purge failed: {year}")
        require(h2_dates.max() <= evaluation.groupby("race_id")["race_date"].first().min()
                - pd.Timedelta(days=2), f"H2/evaluation purge failed: {year}")
        baseline_fold = next(row for row in baseline["folds"] if int(row["evaluation_year"]) == year)
        basic_fold = next(row for row in basic_doc["folds"] if int(row["evaluation_year"]) == year)
        id_fold = next(row for row in id_doc["folds"] if int(row["evaluation_year"]) == year)
        runner_stats, _ = basic_fit.stats_from_baseline(core, baseline_fold)
        h1_races = pair_fit.build_races(core, h1, runner_stats)
        h2_races = pair_fit.build_races(core, h2, runner_stats)
        require(len(h1_races) == H1_RACES[year] and len(h2_races) == H2_RACES[year],
                f"label/design race count changed: {year}")
        require(all(int(np.asarray(race["labels"]).sum()) == 3 for race in h1_races + h2_races),
                f"H1/H2 design label arithmetic changed: {year}")
        old = _old_60_design(core, basic_fit, id_basis, pair_fit, h1_races, h2_races,
                             baseline_fold, basic_fold, id_fold)
        raw_h1 = _race_raw_reliability(reliability_basis, h1_races)
        raw_h2 = _race_raw_reliability(reliability_basis, h2_races)
        moments = reliability_basis.fit_race_equal_moments(raw_h1)
        z_h1 = [reliability_basis.transform_race(block, moments) for block in raw_h1]
        z_h2 = [reliability_basis.transform_race(block, moments) for block in raw_h2]
        x67_h1 = np.column_stack((old["x_h1"], np.vstack(z_h1)))
        x67_h2 = np.column_stack((old["x_h2"], np.vstack(z_h2)))
        require(x67_h1.shape == (len(old["y_h1"]), 67)
                and x67_h2.shape == (len(old["y_h2"]), 67),
                f"67-column H1/H2 design shape changed: {year}")
        require(np.isfinite(x67_h1).all() and np.isfinite(x67_h2).all(),
                f"67-column H1/H2 design contains non-finite values: {year}")
        require(np.array_equal(x67_h1[:, :60], old["x_h1"])
                and np.array_equal(x67_h2[:, :60], old["x_h2"]),
                f"new feature transform changed the frozen 60 columns: {year}")
        fold_summary[str(year)] = {
            "h1_races": len(h1_races), "h1_rows": int(len(h1)),
            "h1_pair_rows": int(len(old["y_h1"])), "h1_design_shape": list(x67_h1.shape),
            "h2_races": len(h2_races), "h2_rows": int(len(h2)),
            "h2_pair_rows": int(len(old["y_h2"])), "h2_design_shape": list(x67_h2.shape),
            "h1_first_date": h1["race_date"].min().date().isoformat(),
            "h1_last_date": h1["race_date"].max().date().isoformat(),
            "h2_first_date": h2["race_date"].min().date().isoformat(),
            "h2_last_date": h2["race_date"].max().date().isoformat(),
            "h2_evaluation_purge_days": int((evaluation["race_date"].min() - h2["race_date"].max()).days),
            "h1_h2_design_labels_constructed": True,
            "h1_positive_pairs": int(np.sum(old["y_h1"])),
            "h2_positive_pairs": int(np.sum(old["y_h2"])),
            "frozen_60_columns_preserved": True,
            "new_basis_moments": moments,
            "h1_feature_diversity": {
                item["basis"]: {
                    "finite_pair_values": item["observed_pair_values"],
                    "imputed_pair_values": item["imputed_pair_values"],
                    "races_with_observed_values": item["races_with_observed_values"],
                    "degenerate": item["degenerate"],
                }
                for item in moments["support"]
            },
        }
    value = {
        "status": "PASS", "study": STUDY.name,
        "scope": "H1/H2 feature and pair-design dry-run; no optimizer, H2 calibration, evaluation prediction, or performance metric",
        "source_preflight_sha256": sha256(PREFLIGHT),
        "source_preflight_code_sha256": sha256(PREFLIGHT_SCRIPT),
        "plan_sha256": sha256(PLAN),
        "basis_sha256": sha256(STUDY / "pair_reliability_basis.py"),
        "fit_code_sha256": sha256(Path(__file__).resolve()),
        "optimizer_runs": 0, "h2_calibration_fits": 0,
        "evaluation_predictions_generated": False, "evaluation_metrics_computed": False,
        "evaluation_target_labels_read": False,
        "h1_h2_design_labels_constructed": True,
        "h1_h2_design_label_scope": "Existing pair builder constructs H1/H2 pair targets for row-count and positive-pair arithmetic only; labels are not passed to feature selection or H1 moments.",
        "historical_results_read_for_existing_rolling_feature": True,
        "reliability_features_and_moments_use_only_pre_event_history": True,
        "folds": fold_summary,
    }
    write_json_once(DRY_RUN, value)
    print(json.dumps(_json_safe({
        "status": value["status"], "optimizer_runs": 0, "h2_calibration_fits": 0,
        "evaluation_predictions_generated": False, "folds": fold_summary,
    }), ensure_ascii=False, indent=2), flush=True)


def _validate_approval():
    require(PREFLIGHT.is_file() and DRY_RUN.is_file(), "preflight and design dry-run are required")
    preflight = json.loads(checked(PREFLIGHT).read_text(encoding="utf-8"))
    dry_run = json.loads(checked(DRY_RUN).read_text(encoding="utf-8"))
    approval = json.loads(checked(APPROVAL).read_text(encoding="utf-8"))
    require(preflight.get("status") == dry_run.get("status") == "PASS",
            "preflight/design dry-run is not PASS")
    require(dry_run.get("optimizer_runs") == dry_run.get("h2_calibration_fits") == 0
            and dry_run.get("evaluation_predictions_generated") is False
            and dry_run.get("evaluation_metrics_computed") is False,
            "dry-run exceeded approved pre-fit scope")
    require(approval.get("approved") is True and approval.get("approved_by") == "root"
            and approval.get("scope") == MODEL_SCOPE, "root approval for this exact fit scope is required")
    expected = {
        "plan_sha256": sha256(checked(PLAN)),
        "source_preflight_sha256": sha256(checked(PREFLIGHT)),
        "source_preflight_code_sha256": sha256(checked(PREFLIGHT_SCRIPT)),
        "basis_sha256": sha256(checked(STUDY / "pair_reliability_basis.py")),
        "fit_code_sha256": sha256(checked(Path(__file__).resolve())),
        "design_dry_run_sha256": sha256(checked(DRY_RUN)),
    }
    for key, value in expected.items():
        require(approval.get(key) == value, f"root approval hash mismatch: {key}")
    require(approval.get("source_hashes") == preflight.get("source_hashes"),
            "root approval source hash set differs from saved preflight")
    for relative, expected_hash in preflight.get("source_hashes", {}).items():
        require(sha256(checked(ROOT / relative)) == expected_hash,
                f"source artifact changed after preflight: {relative}")
    return preflight, approval


def _candidate_objective(core, beta: np.ndarray, basis: np.ndarray, p0: np.ndarray,
                         labels: np.ndarray, race_ids: np.ndarray):
    x = np.asarray(basis, dtype=np.float64)
    b = np.asarray(beta, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    prior = np.asarray(p0, dtype=np.float64)
    require(x.ndim == 2 and x.shape[1] == len(b) == 67, "candidate design/coefficient dimensions differ")
    require(len(x) == len(y) == len(prior) == len(race_ids), "candidate objective input lengths differ")
    require(np.isfinite(x).all() and np.isfinite(b).all() and np.isfinite(y).all()
            and np.isfinite(prior).all(), "non-finite candidate objective input")
    weights = core._race_pair_weights(race_ids)
    eta = logit(prior) + x @ b
    losses = np.logaddexp(0.0, eta) - y * eta
    residual = weights * (expit(eta) - y)
    value = float(np.dot(weights, losses) + 0.5 * float(core.LAMBDA) * np.dot(b, b))
    gradient = x.T @ residual + float(core.LAMBDA) * b
    require(math.isfinite(value) and np.isfinite(gradient).all(), "non-finite candidate objective")
    return value, gradient


def _coefficient_order(core, vocabulary: tuple[str, ...], reliability_basis) -> list[str]:
    result = [*core.BASIS_NAMES, OLD_ROLLING_BASIS_NAME]
    result.extend(f"jockey_id_effect:{jockey_id}" for jockey_id in vocabulary)
    result.extend(reliability_basis.BASIS_NAMES)
    require(len(result) == 67 and len(set(result)) == 67, "67-column coefficient order is not unique")
    return result


def _fit_fold(core, pair_fit, basic_fit, id_basis, reliability_basis, year,
              h1, h2, baseline_fold, basic_fold, id_fold):
    runner_stats, _ = basic_fit.stats_from_baseline(core, baseline_fold)
    h1_races = pair_fit.build_races(core, h1, runner_stats)
    h2_races = pair_fit.build_races(core, h2, runner_stats)
    require(len(h1_races) == H1_RACES[year] and len(h2_races) == H2_RACES[year],
            f"H1/H2 race count mismatch: {year}")
    require(all(int(np.asarray(race["labels"]).sum()) == 3 for race in h1_races + h2_races),
            f"H1/H2 pair label arithmetic changed: {year}")
    old = _old_60_design(core, basic_fit, id_basis, pair_fit, h1_races, h2_races,
                         baseline_fold, basic_fold, id_fold)
    raw_h1 = _race_raw_reliability(reliability_basis, h1_races)
    raw_h2 = _race_raw_reliability(reliability_basis, h2_races)
    moments = reliability_basis.fit_race_equal_moments(raw_h1)
    z_h1 = np.vstack([reliability_basis.transform_race(block, moments) for block in raw_h1])
    z_h2 = np.vstack([reliability_basis.transform_race(block, moments) for block in raw_h2])
    x_h1 = np.column_stack((old["x_h1"], z_h1))
    x_h2 = np.column_stack((old["x_h2"], z_h2))
    result = minimize(
        fun=lambda beta: _candidate_objective(core, beta, x_h1, old["p0_h1"], old["y_h1"], old["race_h1"]),
        x0=np.zeros(67, dtype=np.float64), method="L-BFGS-B", jac=True,
        options={"maxiter": core.H1_MAXITER, "ftol": core.H1_FTOL, "gtol": core.H1_GTOL},
    )
    require(result.success and np.isfinite(result.x).all() and math.isfinite(float(result.fun))
            and np.isfinite(result.jac).all(), f"H1 candidate optimizer failed: {year}: {result.message}")
    grad_inf = float(np.max(np.abs(result.jac)))
    require(grad_inf <= core.ACCEPT_GRAD_INF, f"H1 candidate stationarity failed: {year}: {grad_inf}")
    eta_h2 = logit(old["p0_h2"]) + x_h2 @ result.x
    calibration = core.fit_platt(eta_h2, old["y_h2"], old["race_h2"])
    require(calibration.success and float(calibration.x[1]) > 0.0,
            f"H2 candidate calibrator failed or reverses pair order: {year}")
    require(int(np.sum(old["y_h1"])) == 3 * H1_RACES[year]
            and int(np.sum(old["y_h2"])) == 3 * H2_RACES[year],
            f"H1/H2 positive-pair totals changed: {year}")
    order = _coefficient_order(core, old["vocabulary"], reliability_basis)
    coeff = np.asarray(result.x, dtype=np.float64)
    require(len(order) == len(coeff) == 67, "candidate coefficient vector changed dimension")
    fold = {
        "evaluation_year": year,
        "h1_races": len(h1_races), "h1_rows": int(len(h1)), "h1_pairs": int(len(old["y_h1"])),
        "h1_positive_pairs": int(np.sum(old["y_h1"])),
        "h2_races": len(h2_races), "h2_rows": int(len(h2)), "h2_pairs": int(len(old["y_h2"])),
        "h2_positive_pairs": int(np.sum(old["y_h2"])),
        "h1_first_date": h1["race_date"].min().date().isoformat(),
        "h1_last_date": h1["race_date"].max().date().isoformat(),
        "h2_first_date": h2["race_date"].min().date().isoformat(),
        "h2_last_date": h2["race_date"].max().date().isoformat(),
        "coefficient_order": order,
        "coefficients": [float(value) for value in coeff],
        "coefficients_by_basis": {name: float(value) for name, value in zip(order, coeff, strict=True)},
        "frozen_60_column_contract": {
            "style_basis_names": list(core.BASIS_NAMES),
            "rolling_basis_name": OLD_ROLLING_BASIS_NAME,
            "jockey_id_basis_names": [f"jockey_id_effect:{value}" for value in old["vocabulary"]],
            "style_moments_reused": baseline_fold["pair_standardization"],
            "rolling_moment_reused": old["rolling_moment"],
            "id_vocabulary_reused": list(old["vocabulary"]),
            "id_pi_reused": {key: float(old["category_moments"]["pi"][index])
                             for index, key in enumerate(old["vocabulary"])},
            "id_sigma_reused": {key: float(old["category_moments"]["sigma"][index])
                                for index, key in enumerate(old["vocabulary"])},
        },
        "new_basis_moments": moments,
        "optimizer": {
            "success": bool(result.success), "status": int(result.status), "message": str(result.message),
            "iterations": int(result.nit), "function_evaluations": int(result.nfev),
            "objective": float(result.fun), "gradient": [float(value) for value in result.jac],
            "gradient_inf_norm": grad_inf, "coefficient_count": int(len(coeff)),
            "lambda": float(core.LAMBDA), "maxiter": int(core.H1_MAXITER),
            "ftol": float(core.H1_FTOL), "gtol": float(core.H1_GTOL),
        },
        "h2_candidate_platt": {
            "A": float(calibration.x[0]), "B": float(calibration.x[1]),
            "objective": float(calibration.fun), "iterations": int(calibration.nit),
            "success": bool(calibration.success),
            "projected_gradient_inf_norm": float(np.max(np.abs(calibration.projected_gradient))),
        },
    }
    return fold


def run_approved_fit() -> None:
    preflight, approval = _validate_approval()
    require(not FIT_PATH.exists() and not FIT_RECEIPT.exists(), "candidate fit output already exists")
    require(all(not (OUT / f"FOLD_FIT_{year}.json").exists()
                and not (OUT / f"FOLD_FIT_{year}.json").is_symlink() for year in FIT_YEARS),
            "candidate fold output already exists; no fit retry permitted")
    core, pair_fit, basic_fit, jockey_input, historical, _, id_basis, reliability_basis = load_runtime()
    baseline, basic_doc, id_doc = _saved_model_documents()
    yearly, score_sources = basic_fit.prepare_training_rows(pair_fit, jockey_input, historical)
    yearly = _attach_reliability_features(yearly)
    fold_docs = []
    for year in FIT_YEARS:
        h1, h2 = basic_fit.split_h1_h2(yearly, year)
        baseline_fold = next(row for row in baseline["folds"] if int(row["evaluation_year"]) == year)
        basic_fold = next(row for row in basic_doc["folds"] if int(row["evaluation_year"]) == year)
        id_fold = next(row for row in id_doc["folds"] if int(row["evaluation_year"]) == year)
        fold = _fit_fold(core, pair_fit, basic_fit, id_basis, reliability_basis,
                         year, h1, h2, baseline_fold, basic_fold, id_fold)
        fold["source_preflight_sha256"] = sha256(PREFLIGHT)
        fold["design_dry_run_sha256"] = sha256(DRY_RUN)
        fold["approval_sha256"] = sha256(APPROVAL)
        path = OUT / f"FOLD_FIT_{year}.json"
        write_json_once(path, fold)
        fold_docs.append(fold)
    document = {
        "status": "PASS", "study": STUDY.name,
        "scope": "single pair reliability arm H1/H2 fit only; no evaluation predictions or performance metrics",
        "candidate_input": {
            "horse_score": "saved F1_STYLE6 score, unchanged",
            "basis": "20 style + saved rolling scalar + saved 39 H1 jockey-ID columns + seven pre-event history support/variation pair features",
            "history_source": str(FEATURES.relative_to(ROOT)),
            "pair_feature_names": list(reliability_basis.BASIS_NAMES),
            "pair_features_are_symmetric": True,
            "no odds_or_evaluation_outcomes_in_features_or_moments": True,
        },
        "model": "67-column joint race-equal pair BCE; logit(p0) offset; lambda=1; no intercept; original L-BFGS-B settings",
        "fit_budget": {"h1_optimizer_runs": 3, "h2_positive_slope_platt_fits": 3},
        "baseline_preserved": {
            "current_id_pair_predictions_sha256": preflight["fixed_current_pair_reference"]["sha256"],
            "F1_STYLE6_score_changed": False,
            "existing_baseline_or_60_basis_refit_outside_candidate": False,
            "existing_60_h1_moments_and_id_vocabulary_reused": True,
        },
        "source_preflight_sha256": sha256(PREFLIGHT), "design_dry_run_sha256": sha256(DRY_RUN),
        "approval_sha256": sha256(APPROVAL), "source_hashes": preflight["source_hashes"],
        "score_sources_by_race_year": score_sources,
        "h1_fit_count": 3, "h2_candidate_map_count": 3, "folds": fold_docs,
        "evaluation_predictions_generated": False, "performance_metrics_computed": False,
    }
    write_json_once(FIT_PATH, document)
    receipt = {
        "status": "PASS", "study": STUDY.name, "scope": MODEL_SCOPE,
        "h1_fit_count": 3, "h2_candidate_map_count": 3,
        "evaluation_predictions_generated": False, "performance_metrics_computed": False,
        "plan_sha256": sha256(PLAN), "source_preflight_sha256": sha256(PREFLIGHT),
        "source_preflight_code_sha256": sha256(PREFLIGHT_SCRIPT),
        "basis_sha256": sha256(STUDY / "pair_reliability_basis.py"),
        "fit_code_sha256": sha256(Path(__file__).resolve()),
        "design_dry_run_sha256": sha256(DRY_RUN), "approval_sha256": sha256(APPROVAL),
        "candidate_fit_sha256": sha256(FIT_PATH),
    }
    write_json_once(FIT_RECEIPT, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"design-dry-run", "fit-approved"}:
        raise SystemExit("usage: pair_reliability_fit.py {design-dry-run|fit-approved}")
    if sys.argv[1] == "design-dry-run":
        run_design_dry_run()
    else:
        run_approved_fit()

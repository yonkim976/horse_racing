"""Predict and report the single approved jockey-basic pair arm."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit, logit

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
OUT = STUDY / "outputs"
BASE = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
BASE_OUT = BASE / "outputs"
BASE_PAIR_PREDICTIONS = BASE_OUT / "evaluation_pair_predictions.parquet"
BASE_RACE_DIAGNOSTICS = BASE_OUT / "evaluation_race_probabilities.parquet"
BASE_SOURCE_LOCK = BASE_OUT / "HISTORICAL_SOURCE_LOCK.json"
BASELINE_FIT = BASE_OUT / "expanded_h1_fit.json"
BASE_PAIR_FIT = BASE / "pair_fit.py"
BASE_PAIR_PREDICT = BASE / "pair_predict.py"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
DIRECT_CORE = DIRECT / "core.py"
DIRECT_REPORT = DIRECT / "report.py"
DIRECT_SCHEDULE = DIRECT / "outputs/date_bootstrap_schedule.npy"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT_PATH = OUT / "FIT_RECEIPT.json"
PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
DIAGNOSTICS = OUT / "evaluation_race_probabilities.parquet"
PREDICTION_RECEIPT = OUT / "PREDICTION_RECEIPT.json"
REPORT_PATH = OUT / "REPORT.json"
REPORT_RECEIPT = OUT / "REPORT_RECEIPT.json"
README_PATH = STUDY / "README.md"
MANIFEST_PATH = STUDY / "ARTIFACT_MANIFEST.json"
EVAL_YEARS = (2024, 2025, 2026)
EXPECTED_RACES = {2024: 637, 2025: 654, 2026: 488}
EXPECTED_BASE_PAIR_SHA256 = "f983d9c5dfa7c4d1129b407d5a3e367dc38e193c0c8fdbbaeff34d86b31af499"
EXPECTED_BASE_CORE_SHA256 = "0a51495c6c1d08f65e1400a6d47c7710d3b32806f678a6bbefe2fab3a8e2de1e"
EXPECTED_BASE_PAIR_FIT_SHA256 = "5187288115621e6affc5079d4c24a6a35a9563385d7b336e958f179484fa3e16"
EXPECTED_BASE_PAIR_PREDICT_SHA256 = "69b19509552f4c12db9191b30dd8c5f6fc623cbed3f3265ba466b805c0614f75"
EXPECTED_BOOTSTRAP_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]


class EvaluationError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise EvaluationError(message)


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


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_parquet_once(path: Path, frame: pd.DataFrame) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def import_module(name: str, path: Path):
    path = checked(path)
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_fit() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    receipt = json.loads(checked(FIT_RECEIPT_PATH).read_text(encoding="utf-8"))
    fit = json.loads(checked(FIT_PATH).read_text(encoding="utf-8"))
    approval = json.loads(checked(OUT / "APPROVAL.json").read_text(encoding="utf-8"))
    require(receipt.get("status") == "PASS" and receipt.get("h1_fit_count") == 3
            and receipt.get("h2_candidate_map_count") == 3, "approved candidate fits did not pass")
    require(receipt.get("performance_metrics_computed") is False
            and receipt.get("evaluation_predictions_generated") is False,
            "fit stage already contains evaluation work")
    require(receipt.get("candidate_fit_sha256") == sha256(FIT_PATH), "candidate fit artifact changed")
    require(receipt.get("fit_code_sha256") == sha256(STUDY / "pair_jockey_fit.py"), "fit code changed after approval")
    require(receipt.get("approval_sha256") == sha256(OUT / "APPROVAL.json"), "root approval changed after fit")
    require(approval.get("approved") is True and approval.get("approved_by") == "root",
            "root approval missing")
    require(sha256(BASE_PAIR_PREDICTIONS) == EXPECTED_BASE_PAIR_SHA256,
            "frozen latest-pair evaluation reference changed")
    require(not PREDICTIONS.exists() and not DIAGNOSTICS.exists() and not PREDICTION_RECEIPT.exists(),
            "evaluation prediction outputs already exist")
    return receipt, fit, approval


def candidate_race_predictions(core, race: pd.DataFrame, fit_fold: dict[str, Any], baseline_fold: dict[str, Any]):
    runner_stats, old_pair_stats = _stats_from_baseline(core, baseline_fold)
    race = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
    numbers = race["horse_number"].to_numpy(dtype=int)
    require(len(numbers) >= 4 and len(set(numbers.tolist())) == len(numbers), "invalid evaluation roster")
    z, missing = core.transform_runners(race, runner_stats)
    pairs = list(itertools.combinations(sorted(numbers.tolist()), 2))
    position = {int(number): index for index, number in enumerate(numbers.tolist())}
    basis20 = np.vstack([
        core.pair_basis(z[position[a]], z[position[b]], missing[position[a]], missing[position[b]])
        for a, b in pairs
    ])
    p0_by_pair, _ = core.q0_from_scores(numbers.tolist(), race["score"].astype(float).tolist())
    p0 = np.asarray([p0_by_pair[pair] for pair in pairs], dtype=float)
    d_by_number = {int(row.horse_number): float(row.jockey365_field_relative_top3)
                   for row in race.itertuples(index=False)}
    n_by_number = {int(row.horse_number): int(row.jockey365_n) for row in race.itertuples(index=False)}
    d_i = np.asarray([d_by_number[a] for a, _ in pairs], dtype=float)
    d_j = np.asarray([d_by_number[b] for _, b in pairs], dtype=float)
    pair_d = d_i + d_j
    moment = fit_fold["new_pair_moment"]
    pair_z = np.zeros(len(pair_d), dtype=float) if moment["degenerate"] else (
        pair_d - float(moment["mean"])
    ) / float(moment["scale"])
    x = np.column_stack((core.transform_pair_basis(basis20, old_pair_stats), pair_z))
    require(x.shape == (len(pairs), 21) and np.isfinite(x).all(), "invalid evaluation 21-basis")
    beta = np.asarray([fit_fold["beta_by_basis"][name] for name in core.BASIS_NAMES]
                      + [fit_fold["gamma_jockey365_pair_sum"]], dtype=float)
    eta = logit(p0) + x @ beta
    raw = expit(eta)
    h2 = fit_fold["h2_candidate_platt"]
    calibrated_logits = float(h2["A"]) + float(h2["B"]) * eta
    calibrated = expit(calibrated_logits)
    selected = core.pair_choice_from_logits(pairs, eta)
    require(float(h2["B"]) > 0.0 and selected == core.pair_choice_from_logits(pairs, calibrated_logits),
            "candidate H2 map changed pair ranking")
    score_by_number = {int(row.horse_number): float(row.score) for row in race.itertuples(index=False)}
    rows = []
    for k, (a, b) in enumerate(pairs):
        rows.append({
            "race_id": str(race["race_id"].iloc[0]),
            "race_date": race["race_date"].iloc[0].date().isoformat(),
            "evaluation_year": int(race["year"].iloc[0]),
            "distance_m": int(race["distance_m"].iloc[0]),
            "horse_i": int(a), "horse_j": int(b),
            "score_i": score_by_number[a], "score_j": score_by_number[b],
            "candidate_p0_check": float(p0[k]),
            "candidate_eta": float(eta[k]),
            "candidate_raw_probability": float(raw[k]),
            "candidate_calibrated_probability": float(calibrated[k]),
            "selected_candidate": int((a, b) == selected),
            "jockey365_n_i": n_by_number[a], "jockey365_n_j": n_by_number[b],
            "jockey365_d_i": float(d_i[k]), "jockey365_d_j": float(d_j[k]),
            "jockey365_pair_sum": float(pair_d[k]),
            "jockey365_pair_z": float(pair_z[k]),
        })
    diagnostics = {
        "race_id": str(race["race_id"].iloc[0]),
        "race_date": race["race_date"].iloc[0].date().isoformat(),
        "evaluation_year": int(race["year"].iloc[0]),
        "distance_m": int(race["distance_m"].iloc[0]),
        "jockey_basic_candidate_sum_probability_minus_3": math.fsum(map(float, calibrated)) - 3.0,
    }
    return rows, diagnostics


def _stats_from_baseline(core, fit_row):
    runner_doc = fit_row["runner_standardization"]
    pair_doc = fit_row["pair_standardization"]
    runner = core.Standardization(
        columns=core.RUNNER_COLUMNS,
        mean=np.asarray([runner_doc[name]["mean"] for name in core.RUNNER_COLUMNS], dtype=float),
        scale=np.asarray([runner_doc[name]["scale"] for name in core.RUNNER_COLUMNS], dtype=float),
        degenerate=tuple(bool(runner_doc[name]["degenerate"]) for name in core.RUNNER_COLUMNS),
        support_weight=tuple(float(runner_doc[name]["support_weight"]) for name in core.RUNNER_COLUMNS),
    )
    pair = core.PairStandardization(
        mean=np.asarray([pair_doc[name]["mean"] for name in core.BASIS_NAMES], dtype=float),
        scale=np.asarray([pair_doc[name]["scale"] for name in core.BASIS_NAMES], dtype=float),
        degenerate=tuple(bool(pair_doc[name]["degenerate"]) for name in core.BASIS_NAMES),
        support_weight=tuple(float(pair_doc[name]["support_weight"]) for name in core.BASIS_NAMES),
    )
    return runner, pair


def run_predictions() -> None:
    fit_receipt, fit, approval = validate_fit()
    core = import_module("frozen_direct_pair_core_jockey_eval", DIRECT_CORE)
    pair_fit = import_module("frozen_expanded_pair_fit_jockey_eval", BASE_PAIR_FIT)
    pair_predict = import_module("frozen_expanded_pair_predict_jockey_eval", BASE_PAIR_PREDICT)
    jockey_input = import_module("pair_jockey_input_for_eval", STUDY / "jockey_input.py")
    require(sha256(DIRECT_CORE) == EXPECTED_BASE_CORE_SHA256, "frozen direct core changed")
    require(sha256(BASE_PAIR_FIT) == EXPECTED_BASE_PAIR_FIT_SHA256, "frozen pair fit helper changed")
    require(sha256(BASE_PAIR_PREDICT) == EXPECTED_BASE_PAIR_PREDICT_SHA256, "frozen pair predictor changed")
    require(sha256(DIRECT_SCHEDULE) == EXPECTED_BOOTSTRAP_SHA256, "frozen date schedule changed")
    source_lock = json.loads(checked(BASE_SOURCE_LOCK).read_text(encoding="utf-8"))
    require(source_lock.get("status") == "PASS", "baseline source lock not PASS")
    baseline_fit_doc = json.loads(checked(BASELINE_FIT).read_text(encoding="utf-8"))
    require(sha256(BASELINE_FIT) == fit_receipt["frozen_baseline_h1_sha256"], "baseline moment source changed")

    features = pd.read_parquet(
        checked(pair_predict.FEATURES), columns=pair_predict.EVAL_FEATURE_COLUMNS,
        filters=[("year", ">=", 2024), ("year", "<=", 2026)],
    )
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce").dt.normalize()
    require(features["race_date"].notna().all() and features["year"].isin(EVAL_YEARS).all(),
            "evaluation feature schema/date changed")
    starts = jockey_input.load_starts(include_results=True)
    all_predictions: list[dict[str, Any]] = []
    all_diagnostics: list[dict[str, Any]] = []
    eval_sources: dict[str, Any] = {}
    for year in EVAL_YEARS:
        rows, eval_sources[str(year)] = pair_predict.evaluation_runner_scores(year, features, source_lock)
        for key in ("api_record_id", "race_id", "horse_id"):
            rows[key] = rows[key].astype("string")
        rows["race_date"] = pd.to_datetime(rows["race_date"], errors="coerce").dt.normalize()
        event = jockey_input.attach_event_jockey(rows, starts)
        rolling = jockey_input.rolling_features(event, starts)
        event = event.merge(
            rolling[["api_record_id", "jockey365_n", "jockey365_top3", "jockey365_expected_top3", "jockey365_field_relative_top3"]],
            on="api_record_id", how="left", validate="one_to_one",
        )
        require(event["jockey365_field_relative_top3"].notna().all(), f"evaluation rolling feature missing: {year}")
        expected_fit = next(row for row in fit["folds"] if int(row["evaluation_year"]) == year)
        baseline_fold = next(row for row in baseline_fit_doc["folds"] if int(row["evaluation_year"]) == year)
        year_count = 0
        for _, race in event.groupby("race_id", sort=True):
            race_predictions, diagnostic = candidate_race_predictions(core, race, expected_fit, baseline_fold)
            all_predictions.extend(race_predictions)
            all_diagnostics.append(diagnostic)
            year_count += 1
        require(year_count == EXPECTED_RACES[year], f"evaluation race count changed: {year}")

    candidate = pd.DataFrame(all_predictions)
    new_diag = pd.DataFrame(all_diagnostics)
    require(len(new_diag) == 1779 and new_diag["race_id"].is_unique, "candidate race prediction coverage changed")
    require(not candidate.duplicated(KEYS).any(), "candidate pair prediction key duplicated")
    require((candidate.groupby("race_id")["selected_candidate"].sum() == 1).all(),
            "candidate must select exactly one pair per race")
    require(np.isfinite(candidate.select_dtypes(include=[np.number]).to_numpy(dtype=float)).all(),
            "non-finite candidate evaluation prediction")

    # Append this candidate to the frozen pair table by exact pair key; all saved
    # labels, probabilities, selectors, and comparator columns remain read-only.
    old = pd.read_parquet(checked(BASE_PAIR_PREDICTIONS))
    require(len(old) == 76848 and old["race_id"].nunique() == 1779, "frozen evaluation pair table shape changed")
    merged = old.merge(candidate, on=KEYS, how="outer", validate="one_to_one", indicator=True, suffixes=("", "_new"))
    require(merged["_merge"].eq("both").all(), "new and frozen evaluation pair keys differ")
    require(np.allclose(merged["p0"], merged["candidate_p0_check"], rtol=0, atol=1e-15),
            "fixed pair prior changed")
    require(np.allclose(merged["score_i"], merged["score_i_new"], rtol=0, atol=0)
            and np.allclose(merged["score_j"], merged["score_j_new"], rtol=0, atol=0),
            "frozen F1_STYLE6 horse score changed")
    merged["latest_pair_eta"] = merged["expanded_eta"]
    merged["latest_pair_raw_probability"] = merged["expanded_candidate_raw_probability"]
    merged["latest_pair_calibrated_probability"] = merged["expanded_candidate_calibrated_probability"]
    merged["selected_latest_pair"] = merged["selected_expanded_candidate"]
    merged["old_direct_calibrated_probability"] = merged["old_direct_candidate_calibrated_probability"]
    merged["eta"] = merged["candidate_eta"]
    merged["candidate_raw_probability"] = merged["candidate_raw_probability_new"]
    merged["candidate_calibrated_probability"] = merged["candidate_calibrated_probability_new"]
    merged["selected_candidate"] = merged["selected_candidate_new"]
    merged["selected_jockey_basic_candidate"] = merged["selected_candidate_new"]
    merged = merged.drop(columns=[
        "_merge", "score_i_new", "score_j_new", "candidate_p0_check",
        "candidate_raw_probability_new", "candidate_calibrated_probability_new", "selected_candidate_new",
    ])
    require((merged.groupby("race_id")["selected_candidate"].sum() == 1).all(), "candidate selector count changed")
    merged = merged.sort_values(KEYS, kind="mergesort").reset_index(drop=True)

    old_diag = pd.read_parquet(checked(BASE_RACE_DIAGNOSTICS))
    require(len(old_diag) == 1779 and old_diag["race_id"].is_unique, "frozen race diagnostics changed")
    old_diag = old_diag.rename(columns={
        "candidate_sum_calibrated_pair_probability_minus_3": "latest_pair_sum_probability_minus_3",
        "candidate_abs_sum_deviation": "latest_pair_abs_sum_deviation",
    })
    new_diag = old_diag.merge(new_diag, on=["race_id", "race_date", "evaluation_year", "distance_m"],
                              how="outer", validate="one_to_one", indicator=True)
    require(new_diag["_merge"].eq("both").all(), "candidate and frozen race keys differ")
    new_diag = new_diag.drop(columns="_merge")
    new_diag["jockey_basic_candidate_abs_sum_deviation"] = new_diag[
        "jockey_basic_candidate_sum_probability_minus_3"
    ].abs()
    new_diag = new_diag.sort_values("race_id", kind="mergesort").reset_index(drop=True)
    write_parquet_once(PREDICTIONS, merged)
    write_parquet_once(DIAGNOSTICS, new_diag)
    receipt = {
        "status": "PASS", "study": STUDY.name,
        "scope": "fixed evaluation pair predictions only; no performance metrics",
        "fit_receipt_sha256": sha256(FIT_RECEIPT_PATH),
        "fit_sha256": sha256(FIT_PATH), "approval_sha256": sha256(OUT / "APPROVAL.json"),
        "fixed_pair_reference_sha256": sha256(BASE_PAIR_PREDICTIONS),
        "fixed_source_lock_sha256": sha256(BASE_SOURCE_LOCK),
        "frozen_core_sha256": sha256(DIRECT_CORE),
        "bootstrap_schedule_sha256": sha256(DIRECT_SCHEDULE),
        "evaluation_score_sources": eval_sources,
        "prediction_rows": int(len(merged)), "prediction_races": int(merged["race_id"].nunique()),
        "evaluation_dates": int(merged["race_date"].nunique()),
        "selected_candidate_per_race": int(merged.groupby("race_id")["selected_candidate"].sum().eq(1).sum()),
        "old_pair_columns_and_selectors_preserved": True,
        "performance_metrics_computed": False,
        "pair_predictions_sha256": sha256(PREDICTIONS),
        "race_diagnostics_sha256": sha256(DIAGNOSTICS),
    }
    write_json_once(PREDICTION_RECEIPT, receipt)


def _changed_pair_diagnostic(candidate, comparator, races):
    left = candidate.set_index("race_id")
    right = comparator.set_index("race_id")
    changed = left.index[left["horse_i"].ne(right.reindex(left.index)["horse_i"])
                         | left["horse_j"].ne(right.reindex(left.index)["horse_j"])]
    diff = races.set_index("race_id")["jockey_basic_candidate"].astype(int) - races.set_index("race_id")["comparator"].astype(int)
    changed_mask = diff.index.isin(changed)
    return {
        "races_with_pair_changed": int(len(changed)),
        "gains_on_changed_races": int((diff[changed_mask] == 1).sum()),
        "losses_on_changed_races": int((diff[changed_mask] == -1).sum()),
        "ties_on_changed_races": int((diff[changed_mask] == 0).sum()),
    }


def _comparison(candidate_hit: pd.Series, other_hit: pd.Series, races: pd.DataFrame, dates, schedule):
    frame = races.copy()
    frame["difference"] = candidate_hit.reindex(frame["race_id"]).to_numpy(dtype=float) - other_hit.reindex(frame["race_id"]).to_numpy(dtype=float)
    return {
        "candidate_hits": int(candidate_hit.sum()), "comparator_hits": int(other_hit.sum()),
        "point_difference": float(frame["difference"].mean()),
        "paired_date_bootstrap_95pct_ci": _REPORT.date_ci(frame, "difference", dates, schedule),
    }


def run_report() -> None:
    prediction_receipt = json.loads(checked(PREDICTION_RECEIPT).read_text(encoding="utf-8"))
    require(prediction_receipt.get("status") == "PASS" and prediction_receipt.get("performance_metrics_computed") is False,
            "prediction receipt is not a metrics-free PASS")
    require(prediction_receipt.get("pair_predictions_sha256") == sha256(PREDICTIONS), "pair predictions changed")
    require(prediction_receipt.get("race_diagnostics_sha256") == sha256(DIAGNOSTICS), "race diagnostics changed")
    require(not REPORT_PATH.exists() and not REPORT_RECEIPT.exists() and not README_PATH.exists(),
            "report output already exists")
    dates, schedule, schedule_receipt = _REPORT.load_bootstrap()
    pairs = pd.read_parquet(checked(PREDICTIONS))
    require(len(pairs) == 76848 and pairs["race_id"].nunique() == 1779 and pairs["race_date"].nunique() == 269,
            "fixed evaluation pair/date cohort changed")
    require((pairs.groupby("race_id")["y_pair"].sum() == 3).all(), "evaluation label arithmetic changed")
    pairs = _REPORT.add_date_index(pairs, dates)
    policy_selectors = {
        "jockey_basic_candidate": "selected_candidate",
        "latest_expanded_direct_pair_427": "selected_latest_pair",
        "old_direct_pair_426": "selected_old_direct",
        "H2_calibrated_p0_baseline": "selected_baseline",
        "raw_F1_STYLE6_score_Top2_429": "selected_raw_top2",
        "saved_F1_STYLE6_PTop3_Top2_429": "selected_saved_f1_top2",
        "existing_joint_marginal_Top2_434": "selected_candidate_joint_marginal_top2",
        "existing_candidate_max_joint_pair_422": "selected_candidate_joint_maxpair",
        "existing_matched_max_joint_pair_429": "selected_matched_joint_maxpair",
    }
    races = pairs[["race_id", "race_date", "evaluation_year", "distance_m"]].drop_duplicates().copy()
    require(len(races) == 1779 and races["race_id"].is_unique, "race-level cohort key changed")
    for policy, selector in policy_selectors.items():
        selected = _REPORT.one_selected_per_race(pairs, selector)
        hit = selected[["race_id", "y_pair"]].rename(columns={"y_pair": policy})
        races = races.merge(hit, on="race_id", how="inner", validate="one_to_one")
    races = _REPORT.add_date_index(races, dates)
    rates = {name: {"hits": int(races[name].sum()), "races": len(races), "hit_rate": float(races[name].mean())}
             for name in policy_selectors}
    candidate = races["jockey_basic_candidate"].astype(int)
    comparisons = {}
    for policy in policy_selectors:
        if policy == "jockey_basic_candidate":
            continue
        frame = races.copy()
        frame["difference"] = candidate - races[policy].astype(int)
        comparisons[policy] = {
            "point_difference": float(frame["difference"].mean()),
            "paired_date_bootstrap_95pct_ci": _REPORT.date_ci(frame, "difference", dates, schedule),
        }
    primary = comparisons["latest_expanded_direct_pair_427"]
    raw_gate = comparisons["raw_F1_STYLE6_score_Top2_429"]
    primary_pass = bool(primary["point_difference"] > 0 and primary["paired_date_bootstrap_95pct_ci"]["ci_low"] is not None
                        and primary["paired_date_bootstrap_95pct_ci"]["ci_low"] > 0)
    raw_pass = bool(raw_gate["point_difference"] > 0 and raw_gate["paired_date_bootstrap_95pct_ci"]["ci_low"] is not None
                    and raw_gate["paired_date_bootstrap_95pct_ci"]["ci_low"] > 0)
    selection_diagnostics = {}
    candidate_pairs = _REPORT.one_selected_per_race(pairs, "selected_candidate").set_index("race_id")
    for label, selector in (("latest_pair_427", "selected_latest_pair"), ("raw_score_top2_429", "selected_raw_top2")):
        comparator_pairs = _REPORT.one_selected_per_race(pairs, selector).set_index("race_id")
        changed = candidate_pairs.index[
            candidate_pairs["horse_i"].ne(comparator_pairs.reindex(candidate_pairs.index)["horse_i"])
            | candidate_pairs["horse_j"].ne(comparator_pairs.reindex(candidate_pairs.index)["horse_j"])
        ]
        diff = races.set_index("race_id")["jockey_basic_candidate"].astype(int) - races.set_index("race_id")[selector_to_policy[selector]].astype(int) if False else None
        other_policy = "latest_expanded_direct_pair_427" if label == "latest_pair_427" else "raw_F1_STYLE6_score_Top2_429"
        d = races.set_index("race_id")["jockey_basic_candidate"].astype(int) - races.set_index("race_id")[other_policy].astype(int)
        d = d.reindex(candidate_pairs.index)
        selection_diagnostics[label] = {
            "races_with_pair_changed": int(len(changed)),
            "gains_on_changed_races": int(((d == 1) & d.index.isin(changed)).sum()),
            "losses_on_changed_races": int(((d == -1) & d.index.isin(changed)).sum()),
            "ties_on_changed_races": int(((d == 0) & d.index.isin(changed)).sum()),
        }

    probability_models = {
        "jockey_basic_candidate": ("candidate_calibrated_probability", "selected_candidate"),
        "latest_expanded_direct_pair": ("latest_pair_calibrated_probability", "selected_latest_pair"),
        "old_direct_pair": ("old_direct_calibrated_probability", "selected_old_direct"),
        "H2_calibrated_p0_baseline": ("baseline_calibrated_probability", "selected_baseline"),
    }
    probability_quality = {}
    confidence = {}
    for model, (column, selector) in probability_models.items():
        selected = _REPORT.one_selected_per_race(pairs, selector)
        probability_quality[model] = {
            "all_pair": _REPORT.race_equal_scores(pairs, column),
            "selected_pair": _REPORT.race_equal_scores(selected, column),
            "all_pair_reliability": _REPORT.reliability(pairs, column, True),
            "selected_pair_reliability": _REPORT.reliability(selected, column, False),
        }
        confident = selected.loc[selected[column].ge(0.20)].copy()
        confidence[model] = {
            "threshold": 0.20, "selected_races": int(len(selected)),
            "coverage_count": int(len(confident)), "coverage": float(len(confident) / len(selected)),
            "hit_rate": float(confident["y_pair"].mean()) if len(confident) else None,
            "date_cluster_ci": _REPORT.date_ci(confident, "y_pair", dates, schedule),
        }

    pair_diag = pd.read_parquet(checked(DIAGNOSTICS))
    sum_columns = {
        "jockey_basic_candidate": "jockey_basic_candidate_sum_probability_minus_3",
        "latest_expanded_direct_pair": "latest_pair_sum_probability_minus_3",
        "old_direct_pair": "old_direct_candidate_sum_calibrated_pair_probability_minus_3",
        "H2_calibrated_p0_baseline": "baseline_sum_calibrated_pair_probability_minus_3",
    }
    sum_diagnostics = {}
    for model, column in sum_columns.items():
        values = pair_diag[column].to_numpy(dtype=float)
        absolute = np.abs(values)
        sum_diagnostics[model] = {
            "races": len(values), "signed_mean": float(np.mean(values)),
            "absolute_mean": float(np.mean(absolute)), "absolute_median": float(np.median(absolute)),
            "absolute_p95": float(np.quantile(absolute, .95)), "absolute_max": float(np.max(absolute)),
        }

    by_year = {}
    for year in EVAL_YEARS:
        subset = races.loc[races["evaluation_year"].eq(year)].copy()
        entry = {name: {"hits": int(subset[name].sum()), "races": len(subset), "hit_rate": float(subset[name].mean())}
                 for name in policy_selectors}
        entry["candidate_minus_latest_pair"] = {
            "point_difference": float((subset["jockey_basic_candidate"] - subset["latest_expanded_direct_pair_427"]).mean()),
            "date_ci": _REPORT.date_ci(subset.assign(difference=subset["jockey_basic_candidate"] - subset["latest_expanded_direct_pair_427"]), "difference", dates, schedule),
        }
        by_year[str(year)] = entry
    by_distance = {}
    for distance in sorted(races["distance_m"].unique().tolist()):
        subset = races.loc[races["distance_m"].eq(distance)].copy()
        if subset.empty:
            continue
        diff_frame = subset.assign(difference=subset["jockey_basic_candidate"] - subset["latest_expanded_direct_pair_427"])
        by_distance[str(int(distance))] = {
            "races": len(subset), "dates": int(subset["race_date"].nunique()),
            "candidate_hits": int(subset["jockey_basic_candidate"].sum()),
            "latest_pair_hits": int(subset["latest_expanded_direct_pair_427"].sum()),
            "candidate_hit_rate": float(subset["jockey_basic_candidate"].mean()),
            "latest_pair_hit_rate": float(subset["latest_expanded_direct_pair_427"].mean()),
            "candidate_minus_latest_pair_date_ci": _REPORT.date_ci(diff_frame, "difference", dates, schedule),
            "sparse_subgroup": bool(len(subset) < 100 or subset["race_date"].nunique() < 20),
        }

    report = {
        "study": STUDY.name,
        "study_description": "저장 F1_STYLE6 말 점수와 pair 평가를 고정하고, T−2 기준 최근 365일 기수의 관측 편성 대비 Top3 빈도 scalar 합 한 열을 pair 선택에 추가한 단일 비교",
        "evaluation_scope": "2019–2025 historical H1/H2와 2024–2026 반복 개발 평가 cohort; 새 미래 holdout 아님",
        "candidate_input": {
            "formula": "d=(S-sum(3/field_n))/(n+20), n=0이면 0; unordered pair input=d_i+d_j",
            "window": "C=T−2 calendar days; C−365d < past race_date <= C",
            "added_pair_columns": ["jockey365_past_field_relative_top3_sum"],
            "interpretation": "과거 관측 편성 대비 Top3 빈도 지표; 기수 능력이나 인과효과가 아님",
            "excluded_inputs": ["마방", "기수 교체", "거리·각질 전문성", "기수 ID 범주형 효과", "기수×말 상호작용"],
        },
        "races": int(len(races)), "race_dates": int(races["race_date"].nunique()),
        "pair_rows": int(len(pairs)), "positive_pair_labels": int(pairs["y_pair"].sum()),
        "pair_hit_rate_by_policy": rates,
        "candidate_minus_fixed_comparator_date_bootstrap": comparisons,
        "primary_feature_effect_gate_vs_latest_pair_427": {
            **primary, "point_estimate_above_zero": primary["point_difference"] > 0,
            "ci_lower_above_zero": primary["paired_date_bootstrap_95pct_ci"]["ci_low"] is not None
                and primary["paired_date_bootstrap_95pct_ci"]["ci_low"] > 0,
            "passed": primary_pass,
        },
        "secondary_raw429_gate": {
            **raw_gate, "point_estimate_above_zero": raw_gate["point_difference"] > 0,
            "ci_lower_above_zero": raw_gate["paired_date_bootstrap_95pct_ci"]["ci_low"] is not None
                and raw_gate["paired_date_bootstrap_95pct_ci"]["ci_low"] > 0,
            "passed": raw_pass,
        },
        "combined_pair_improvement_gate_passed": bool(primary_pass and raw_pass),
        "selection_change_diagnostics": selection_diagnostics,
        "probability_quality_separate_diagnostics": probability_quality,
        "selected_probability_at_least_0_20": confidence,
        "sum_pair_probability_minus_three_diagnostics": sum_diagnostics,
        "hit_rate_by_year": by_year, "hit_rate_by_distance_m": by_distance,
        "bootstrap": {
            "schedule_sha256": sha256(DIRECT_SCHEDULE), "draws": int(schedule.shape[0]),
            "dates": int(schedule.shape[1]), "seed": schedule_receipt["seed"],
            "numpy_version": schedule_receipt["numpy_version"],
            "date_min": dates[0], "date_max": dates[-1],
        },
        "fit_receipt_sha256": sha256(FIT_RECEIPT_PATH),
        "prediction_receipt_sha256": sha256(PREDICTION_RECEIPT),
        "pair_predictions_sha256": sha256(PREDICTIONS),
        "race_diagnostics_sha256": sha256(DIAGNOSTICS),
        "interpretation_limits": [
            "평가기간은 반복 개발 라벨이 재사용된 과거 표본이며 독립 미래 holdout이 아니다.",
            "source는 정상 완주 완전 편성 cohort이므로 n은 이 관측 cohort에서의 eligible starts만 센다.",
            "과거 결과 게시시각은 저장되지 않았고 현재 event rider는 후향 사건 snapshot을 사용한다.",
            "고정 date bootstrap은 적합된 모델을 조건으로 하며 H1을 재표집하거나 재학습하지 않는다.",
            "제외 말 3005648과 400m는 source cohort에서 제외 상태를 유지했다.",
        ],
    }
    write_json_once(REPORT_PATH, report)
    primary_ci = primary["paired_date_bootstrap_95pct_ci"]
    raw_ci = raw_gate["paired_date_bootstrap_95pct_ci"]
    readme = [
        "# 제주 F1_STYLE6 두 말 동시 Top3 pair 기수 기본정보 비교",
        "",
        "저장된 F1_STYLE6 말 점수·평가 roster·latest expanded pair 427/1,779를 고정하고, pair 선택에 최근 365일 기수 기본 기록 한 열을 추가했다. 공식 event jockey ID는 과거 출전 묶음에만 사용했다. 입력은 T−2까지의 관측 출전 중 `(C−365일,C]` 구간에서 `(Top3 횟수−Σ(3/편성수))/(출전수+20)`이며, 두 말의 값을 합한다. 20 pseudo-start는 사전 고정 값이고 조정하지 않았다. 이 값은 과거 관측 편성 대비 Top3 빈도 지표이며 기수 능력 추정치가 아니다.",
        "",
        f"평가 cohort는 {len(races):,}경주·{races['race_date'].nunique():,}경주일·{len(pairs):,} unordered pair다. 2026년은 9월까지의 부분연도이고, 이 기간은 반복 개발 자료다.",
        "",
        "## 사전 지정 gate",
        "",
        f"Primary feature-effect gate (candidate−latest pair 427): {rates['jockey_basic_candidate']['hits']}/{len(races)} 대 {rates['latest_expanded_direct_pair_427']['hits']}/{len(races)}, 차이 {100*primary['point_difference']:+.3f}%p, date-bootstrap 95% CI {100*primary_ci['ci_low']:+.3f}~{100*primary_ci['ci_high']:+.3f}%p; {'통과' if primary_pass else '미통과'}.",
        f"Secondary raw Top2 429 gate: candidate {rates['jockey_basic_candidate']['hits']}/{len(races)} 대 {rates['raw_F1_STYLE6_score_Top2_429']['hits']}/{len(races)}, 차이 {100*raw_gate['point_difference']:+.3f}%p, 95% CI {100*raw_ci['ci_low']:+.3f}~{100*raw_ci['ci_high']:+.3f}%p; {'통과' if raw_pass else '미통과'}.",
        f"두 gate 동시 통과: {'예' if primary_pass and raw_pass else '아니오'}. 기존 계수와 저장 말 점수는 수정하지 않았다. 새 candidate에서만 20개 pair 계수와 jockey scalar 계수를 H1에 공동 적합했다.",
        "",
        "| 방식 | 적중 | 경주 | 적중률 |",
        "|---|---:|---:|---:|",
    ]
    for policy, values in rates.items():
        readme.append(f"| {policy} | {values['hits']:,} | {values['races']:,} | {100*values['hit_rate']:.2f}% |")
    readme += [
        "",
        "## 확률과 세부 결과",
        "",
        "all-pair/selected-pair Brier 및 log loss, reliability bins, selected probability ≥0.20의 coverage·적중률, 연도·거리별 paired 결과, 변경 선택 pair의 새 적중/놓침/동률 및 확률합 진단은 `outputs/REPORT.json`에 있다. Bootstrap은 기존 2,000 draw·269-date schedule을 그대로 썼다.",
        "",
        "## 해석 범위",
        "",
        "과거 start source는 정상 완주 완전 편성 cohort를 반영하므로 분모 `n`은 전체 현실 기승수가 아니다. 결과 게시 timestamp는 보유하지 않아 T−2 cutoff는 경주일 기준 시점 가정이며, event rider 배정은 후향 snapshot이다. 자료는 반복 개발 기간이므로 새 시점 holdout에서 확인하기 전 운영 적용 근거로 쓰지 않는다.",
        "",
    ]
    README_PATH.write_text("\n".join(readme), encoding="utf-8")
    report_receipt = {
        "status": "PASS", "study": STUDY.name, "performance_metrics_computed": True,
        "report_sha256": sha256(REPORT_PATH), "readme_sha256": sha256(README_PATH),
        "report_runner_sha256": sha256(Path(__file__).resolve()),
        "pair_predictions_sha256": sha256(PREDICTIONS),
        "bootstrap_schedule_sha256": sha256(DIRECT_SCHEDULE),
        "primary_gate_passed": primary_pass, "raw429_gate_passed": raw_pass,
    }
    write_json_once(REPORT_RECEIPT, report_receipt)
    write_manifest()


def write_manifest() -> None:
    files = [
        STUDY / "PLAN.md", STUDY / "SOURCE_AUDIT.md", STUDY / "jockey_input.py",
        STUDY / "pair_jockey_fit.py", STUDY / "pair_jockey_evaluate.py", README_PATH,
        OUT / "SOURCE_PREFLIGHT.json", OUT / "APPROVAL.json", FIT_PATH, FIT_RECEIPT_PATH,
        PREDICTIONS, DIAGNOSTICS, PREDICTION_RECEIPT, REPORT_PATH, REPORT_RECEIPT,
    ]
    entries = []
    for path in files:
        checked_path = path.resolve(strict=True)
        require(checked_path.is_relative_to(STUDY) and checked_path.is_file(), f"manifest path escaped study: {path}")
        entries.append({"path": str(checked_path.relative_to(STUDY)), "sha256": sha256(checked_path), "bytes": checked_path.stat().st_size})
    write_json_once(MANIFEST_PATH, {
        "status": "PASS", "study": STUDY.name, "generated_at": "2026-10-12",
        "files": entries, "manifest_self_hash_excluded": True,
    })


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("predict", "report", "all"):
        raise SystemExit("usage: pair_jockey_evaluate.py {predict|report|all}")
    stage = sys.argv[1]
    if stage in ("predict", "all"):
        run_predictions()
    if stage in ("report", "all"):
        run_report()


if __name__ == "__main__":
    main()

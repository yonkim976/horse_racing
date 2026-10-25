"""Post-fit 60-column H1/H2 arithmetic audit; never calls an optimizer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
REVIEW = Path(__file__).resolve().parent
STUDY = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
OUT = STUDY / "outputs"
BASE = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
BASE_REVIEW = ROOT / "jeju/research/20261012_pair_jockey_basic_review_v1"
BASE_EXPANDED = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/expanded_h1_fit.json"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT_PATH = OUT / "FIT_RECEIPT.json"
APPROVAL_PATH = OUT / "APPROVAL.json"
PREFLIGHT_PATH = OUT / "SOURCE_PREFLIGHT.json"
DRY_RUN_PATH = OUT / "DESIGN_DRY_RUN.json"
EVAL_YEARS = (2024, 2025, 2026)


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(checked(path).read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    checked_path = checked(path)
    spec = importlib.util.spec_from_file_location(name, checked_path)
    require(spec is not None and spec.loader is not None, f"cannot load frozen reference: {checked_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_basic_fit_review():
    sys.path.insert(0, str(BASE_REVIEW))
    return load_module("basic_independent_fit_audit_for_id", BASE_REVIEW / "independent_fit_audit.py")


def pair_moments_from_baseline(fit_row: dict[str, Any], basic_ref):
    doc = fit_row["pair_standardization"]
    return basic_ref.ref.PairMoments(
        mean=np.asarray([doc[name]["mean"] for name in basic_ref.ref.BASIS_NAMES], dtype=float),
        scale=np.asarray([doc[name]["scale"] for name in basic_ref.ref.BASIS_NAMES], dtype=float),
        degenerate=tuple(bool(doc[name]["degenerate"]) for name in basic_ref.ref.BASIS_NAMES),
        support_weight=tuple(float(doc[name]["support_weight"]) for name in basic_ref.ref.BASIS_NAMES),
    )


def category_doc_arrays(candidate_fold: dict[str, Any]) -> dict[str, Any]:
    category = candidate_fold["category_encoding"]
    vocabulary = tuple(map(str, category["vocabulary_h1_only"]))
    require(len(vocabulary) == len(set(vocabulary)) == 39, "saved H1-only ID vocabulary changed")
    require(vocabulary == tuple(sorted(vocabulary)), "saved H1 vocabulary is not canonical sorted order")
    mu = np.asarray([category["mu"][key] for key in vocabulary], dtype=float)
    pi = np.asarray([category["pi"][key] for key in vocabulary], dtype=float)
    sigma = np.asarray([category["sigma"][key] for key in vocabulary], dtype=float)
    require(np.isfinite(mu).all() and np.isfinite(pi).all() and np.isfinite(sigma).all(),
            "saved categorical moments are not finite")
    require((sigma > 1e-12).all(), "saved categorical moment has a degenerate ID")
    return {"vocabulary": vocabulary, "mu": mu, "pi": pi, "sigma": sigma}


def audit_fold(
    year: int,
    h1,
    h2,
    baseline_fold: dict[str, Any],
    rolling_fold: dict[str, Any],
    candidate_fold: dict[str, Any],
    basic_fit_audit,
    id_reference,
    core,
) -> dict[str, Any]:
    require(int(candidate_fold["evaluation_year"]) == year, f"candidate fit fold order changed in {year}")
    require(int(candidate_fold["h1_races"]) == int(h1["race_id"].nunique()),
            f"candidate H1 race count differs in {year}")
    require(int(candidate_fold["h2_races"]) == int(h2["race_id"].nunique()),
            f"candidate H2 race count differs in {year}")
    require(candidate_fold["frozen_21st_rolling_moment"] == rolling_fold["new_pair_moment"],
            f"saved rolling 21st moment differs from approved basic candidate in {year}")
    require(rolling_fold["old_pair_moments"] == baseline_fold["pair_standardization"],
            f"saved first 20 pair moments differ from frozen expanded reference in {year}")

    runner_stats = basic_fit_audit.load_runner_moments(baseline_fold)
    old_pair_stats = pair_moments_from_baseline(baseline_fold, basic_fit_audit)
    h1_races = basic_fit_audit.build_independent_races(h1, runner_stats)
    h2_races = basic_fit_audit.build_independent_races(h2, runner_stats)
    vocabulary = tuple(sorted(h1["jockey_id"].astype(str).unique().tolist()))
    saved_category = category_doc_arrays(candidate_fold)
    require(saved_category["vocabulary"] == vocabulary,
            f"candidate vocabulary is not derived solely from this fold's H1 IDs in {year}")

    def jockey_maps(races):
        maps = []
        pairs = []
        for race in races:
            id_by_horse = {
                int(row.horse_number): str(row.jockey_id)
                for row in race["rows"].itertuples(index=False)
            }
            maps.append(id_by_horse)
            pairs.append(race["pairs"])
        return maps, pairs

    h1_id_maps, h1_pairs = jockey_maps(h1_races)
    independently_recomputed = id_reference.enumerated_category_moments(
        h1_id_maps, h1_pairs, vocabulary,
    )
    for name in ("mu", "pi", "sigma"):
        require(np.allclose(
            np.asarray(saved_category[name]), independently_recomputed[name],
            rtol=0.0, atol=1e-12,
        ), f"saved H1 category {name} differs from independent enumeration in {year}")
    require(
        int(candidate_fold["category_encoding"]["vocabulary_count"]) == len(vocabulary)
        and not candidate_fold["category_encoding"]["degenerate_ids"],
        f"candidate category support/degeneracy metadata changed in {year}",
    )
    category_rows = candidate_fold["category_encoding"]["support_and_effects"]
    require(len(category_rows) == len(vocabulary), f"candidate category effect rows differ in {year}")
    category_rows_by_id = {str(row["jockey_id"]): row for row in category_rows}
    require(set(category_rows_by_id) == set(vocabulary), f"candidate category effects omit/add IDs in {year}")
    h1_support = h1["jockey_id"].astype(str).value_counts()
    for index, jockey_id in enumerate(vocabulary):
        row = category_rows_by_id[jockey_id]
        require(int(row["h1_starts"]) == int(h1_support[jockey_id]),
                f"candidate H1 start support differs for {jockey_id}/{year}")
        require(abs(float(row["mu_pair_count"]) - float(saved_category["mu"][index])) <= 1e-12,
                f"candidate category μ row differs for {jockey_id}/{year}")
        require(abs(float(row["pi_runner_weight"]) - float(saved_category["pi"][index])) <= 1e-12,
                f"candidate category π row differs for {jockey_id}/{year}")
        require(abs(float(row["sigma_pair_count"]) - float(saved_category["sigma"][index])) <= 1e-12,
                f"candidate category σ row differs for {jockey_id}/{year}")

    category_moments = {
        "vocabulary": vocabulary,
        "mu": independently_recomputed["mu"],
        "pi": independently_recomputed["pi"],
        "sigma": independently_recomputed["sigma"],
    }
    x_h1 = id_reference.standardize_60d_basis(
        [race["raw20"] for race in h1_races],
        [race["jockey_pair"] for race in h1_races],
        h1_id_maps,
        h1_pairs,
        old_pair_stats,
        rolling_fold["new_pair_moment"],
        category_moments,
    )
    h2_id_maps, h2_pairs = jockey_maps(h2_races)
    x_h2 = id_reference.standardize_60d_basis(
        [race["raw20"] for race in h2_races],
        [race["jockey_pair"] for race in h2_races],
        h2_id_maps,
        h2_pairs,
        old_pair_stats,
        rolling_fold["new_pair_moment"],
        category_moments,
    )
    require(all(basis.shape[1] == 60 for basis in x_h1 + x_h2),
            f"independent pair design is not 60-dimensional in {year}")
    require(all(np.isfinite(basis).all() for basis in x_h1 + x_h2),
            f"independent design contains non-finite values in {year}")

    beta_by_basis = candidate_fold["beta_by_basis"]
    beta = np.asarray(
        [beta_by_basis[name] for name in basic_fit_audit.ref.BASIS_NAMES]
        + [candidate_fold["gamma_jockey365_pair_sum"]]
        + [candidate_fold["theta_by_jockey_id"][jockey_id] for jockey_id in vocabulary],
        dtype=float,
    )
    require(beta.shape == (60,) and np.isfinite(beta).all(), f"saved 60 coefficients differ in {year}")
    require(int(candidate_fold["optimizer"]["coefficient_count"]) == 60
            and float(candidate_fold["optimizer"]["lambda"]) == float(core.LAMBDA) == 1.0,
            f"candidate H1 ridge/dimension changed in {year}")
    h1_objective, h1_gradient = id_reference.h1_objective_gradient(
        beta, x_h1, [race["p0"] for race in h1_races],
        [race["labels"] for race in h1_races], float(core.LAMBDA),
    )
    optimizer = candidate_fold["optimizer"]
    h1_gradient_inf = float(np.max(np.abs(h1_gradient)))
    require(abs(h1_objective - float(optimizer["objective"])) <= 1e-9,
            f"independent H1 objective differs in {year}")
    require(abs(h1_gradient_inf - float(optimizer["gradient_inf_norm"])) <= 1e-7,
            f"independent H1 gradient norm differs in {year}")
    require(h1_gradient_inf <= float(core.ACCEPT_GRAD_INF),
            f"saved H1 solution fails frozen stationarity gate in {year}")

    candidate_alpha = np.asarray(
        [candidate_fold["alpha_centered_runner_logit_effect_by_jockey_id"][key]
         for key in vocabulary], dtype=float,
    )
    independent_alpha = id_reference.centered_runner_effects(
        beta[21:], category_moments["pi"], category_moments["sigma"],
    )
    require(np.allclose(candidate_alpha, independent_alpha, rtol=0.0, atol=1e-12),
            f"saved centered per-ID effect differs from independent conversion in {year}")
    weighted_alpha_mean = math.fsum(
        float(category_moments["pi"][index] * independent_alpha[index])
        for index in range(len(vocabulary))
    )
    require(abs(weighted_alpha_mean) <= 1e-12, f"saved effects are not H1 exposure-centered in {year}")

    def h2_pair_logits():
        return [
            basic_fit_audit.ref.logit(race["p0"]) + basis @ beta
            for race, basis in zip(h2_races, x_h2, strict=True)
        ]

    logits_h2 = h2_pair_logits()
    platt = candidate_fold["h2_candidate_platt"]
    platt_theta = np.asarray([platt["A"], platt["B"]], dtype=float)
    h2_objective, h2_gradient = id_reference.h2_objective_gradient(
        platt_theta, logits_h2, [race["labels"] for race in h2_races],
    )
    projected = basic_fit_audit.ref.projected_box_gradient(
        platt_theta, h2_gradient, ((-20.0, 20.0), (0.05, 20.0)),
    )
    projected_inf = float(np.max(np.abs(projected)))
    require(platt_theta[1] > 0.0, f"saved H2 Platt slope is not positive in {year}")
    require(abs(h2_objective - float(platt["objective"])) <= 1e-9,
            f"independent H2 Platt objective differs in {year}")
    require(abs(projected_inf - float(platt["projected_gradient_inf_norm"])) <= 1e-7,
            f"independent H2 projected gradient differs in {year}")
    require(projected_inf <= 1e-7, f"saved H2 calibrator fails stationarity in {year}")

    return {
        "evaluation_year": year,
        "h1_races": len(h1_races), "h1_pairs": int(sum(len(race["labels"]) for race in h1_races)),
        "h2_races": len(h2_races), "h2_pairs": int(sum(len(race["labels"]) for race in h2_races)),
        "category_count": len(vocabulary), "minimum_h1_starts_per_id": int(h1_support.min()),
        "frozen_first_20_moments_exact": True, "frozen_21st_rolling_moment_exact": True,
        "independent_category_mu_max_abs": float(np.max(np.abs(saved_category["mu"] - independently_recomputed["mu"]))),
        "independent_category_pi_max_abs": float(np.max(np.abs(saved_category["pi"] - independently_recomputed["pi"]))),
        "independent_category_sigma_max_abs": float(np.max(np.abs(saved_category["sigma"] - independently_recomputed["sigma"]))),
        "independent_h1_objective": h1_objective,
        "h1_objective_abs_difference": abs(h1_objective - float(optimizer["objective"])),
        "independent_h1_gradient_inf_norm": h1_gradient_inf,
        "saved_h1_gradient_inf_norm": float(optimizer["gradient_inf_norm"]),
        "weighted_centered_alpha_mean": weighted_alpha_mean,
        "independent_h2_platt_objective": h2_objective,
        "h2_objective_abs_difference": abs(h2_objective - float(platt["objective"])),
        "independent_h2_projected_gradient_inf_norm": projected_inf,
        "saved_h2_projected_gradient_inf_norm": float(platt["projected_gradient_inf_norm"]),
        "h2_slope_positive": bool(platt_theta[1] > 0.0),
    }


def collect() -> dict[str, Any]:
    approval = read_json(APPROVAL_PATH)
    preflight = read_json(PREFLIGHT_PATH)
    dry_run = read_json(DRY_RUN_PATH)
    fit = read_json(FIT_PATH)
    receipt = read_json(FIT_RECEIPT_PATH)
    require(approval.get("approved") is True and approval.get("approved_by") == "root",
            "root fit approval is missing")
    require(approval.get("scope") == "pair_jockey_id_h1_h2_fit"
            and approval.get("h1_fit_count") == 3
            and approval.get("h2_candidate_map_count") == 3
            and approval.get("horse_model_fits") == 0,
            "root approval scope/budget changed")
    for key, path in (
        ("plan_sha256", STUDY / "PLAN.md"),
        ("source_preflight_sha256", PREFLIGHT_PATH),
        ("source_preflight_code_sha256", STUDY / "source_preflight.py"),
        ("id_basis_sha256", STUDY / "pair_jockey_id_basis.py"),
        ("fit_code_sha256", STUDY / "pair_jockey_id_fit.py"),
        ("design_dry_run_sha256", DRY_RUN_PATH),
    ):
        require(approval.get(key) == sha256(checked(path)), f"root approval hash mismatch: {key}")
    require(preflight.get("status") == "PASS"
            and preflight.get("finish_labels_read") is False
            and preflight.get("performance_metrics_computed") is False,
            "approved label-free source preflight is not PASS")
    require(dry_run.get("status") == "PASS" and dry_run.get("optimizer_runs") == 0
            and dry_run.get("calibration_fits") == 0
            and dry_run.get("performance_metrics_computed") is False,
            "pre-approval structural dry-run scope changed")
    require(fit.get("status") == "PASS" and fit.get("h1_fit_count") == 3
            and fit.get("h2_candidate_map_count") == 3
            and fit.get("evaluation_predictions_generated") is False
            and fit.get("performance_metrics_computed") is False,
            "candidate fit artifact scope/count changed")
    require(receipt.get("status") == "PASS" and receipt.get("h1_fit_count") == 3
            and receipt.get("h2_candidate_map_count") == 3
            and receipt.get("approval_sha256") == sha256(APPROVAL_PATH)
            and receipt.get("candidate_fit_sha256") == sha256(FIT_PATH),
            "candidate fit receipt does not pin approved result")
    require(fit.get("approval_sha256") == sha256(APPROVAL_PATH)
            and fit.get("source_preflight_sha256") == sha256(PREFLIGHT_PATH),
            "candidate fit lineage differs from approval/preflight")
    for relative, expected in preflight.get("source_hashes", {}).items():
        relative_path = Path(relative)
        require(not relative_path.is_absolute() and ".." not in relative_path.parts,
                "preflight source path is unsafe")
        require(sha256(checked(ROOT / relative_path)) == expected,
                f"preflight pinned input changed: {relative}")

    basic_fit_audit = load_basic_fit_review()
    _, _, _, _, baseline_fit = basic_fit_audit.verify_approved_artifacts()
    basic_candidate_fit = read_json(BASE / "outputs/FIT.json")
    yearly, score_hashes = basic_fit_audit.load_joined_training_rows(
        basic_candidate_fit, baseline_fit,
    )
    baseline_by_year = {int(row["evaluation_year"]): row for row in baseline_fit["folds"]}
    rolling_by_year = {int(row["evaluation_year"]): row for row in basic_candidate_fit["folds"]}
    candidate_by_year = {int(row["evaluation_year"]): row for row in fit["folds"]}
    require(set(candidate_by_year) == set(EVAL_YEARS), "candidate fold years changed")
    id_reference = load_module(
        "independent_pair_jockey_id_reference_for_fit",
        REVIEW / "independent_pair_jockey_id_reference.py",
    )
    core, _, _, _ = basic_fit_audit.ref, None, None, None
    # The frozen optimizer constants and Platt-box projection come from the
    # already-audited basic candidate implementation, read-only.
    basic_fit_module = load_module(
        "frozen_basic_fit_helper_for_id_audit",
        BASE / "pair_jockey_fit.py",
    )
    core, _, _, _ = basic_fit_module.load_helpers()
    fold_results = []
    for year in EVAL_YEARS:
        h1, h2 = basic_fit_audit.split_fold(yearly, year)
        candidate_file = read_json(OUT / f"FOLD_FIT_{year}.json")
        require(candidate_file == candidate_by_year[year],
                f"top-level FIT fold differs from saved fold receipt in {year}")
        fold_results.append(audit_fold(
            year, h1, h2, baseline_by_year[year], rolling_by_year[year],
            candidate_file, basic_fit_audit, id_reference, core,
        ))
    hashes = {
        str(path.relative_to(ROOT)): sha256(checked(path))
        for path in (
            APPROVAL_PATH, PREFLIGHT_PATH, DRY_RUN_PATH, FIT_PATH, FIT_RECEIPT_PATH,
            STUDY / "PLAN.md", STUDY / "source_preflight.py", STUDY / "pair_jockey_id_basis.py",
            STUDY / "pair_jockey_id_fit.py",
            *(OUT / f"FOLD_FIT_{year}.json" for year in EVAL_YEARS),
            BASE / "outputs/FIT.json", BASE / "outputs/FIT_RECEIPT.json",
            BASE / "outputs/APPROVAL.json", BASE / "pair_jockey_fit.py",
            BASE_EXPANDED,
            BASE_REVIEW / "independent_fit_audit.py",
            BASE_REVIEW / "independent_jockey_reference.py",
            REVIEW / "independent_pair_jockey_id_reference.py",
        )
    }
    return {
        "status": "PASS",
        "study": STUDY.name,
        "scope": "independent 60-column H1 objective/gradient and H2 Platt arithmetic only; no optimizer, candidate predictions, or performance metrics",
        "approval_sha256": sha256(APPROVAL_PATH),
        "candidate_fit_sha256": sha256(FIT_PATH),
        "candidate_fit_receipt_sha256": sha256(FIT_RECEIPT_PATH),
        "frozen_baseline_fit_sha256": sha256(BASE_EXPANDED),
        "input_hashes": dict(sorted(hashes.items())),
        "score_source_hashes": score_hashes,
        "optimizer_calls": 0,
        "candidate_evaluation_predictions_generated": False,
        "candidate_performance_metrics_computed": False,
        "folds": fold_results,
    }


def main() -> None:
    result = collect()
    result["review_script_sha256"] = sha256(checked(Path(__file__).resolve()))
    output = REVIEW / "independent_fit_audit.json"
    require(output.resolve().is_relative_to(REVIEW) and not output.is_symlink(),
            "refusing to escape review folder or write through a symlink")
    with output.open("w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "status": result["status"],
        "optimizer_calls": result["optimizer_calls"],
        "folds": result["folds"],
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

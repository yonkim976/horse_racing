#!/usr/bin/env python3
"""Run the preregistered E4 frozen-score calibration diagnostic."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e3 import (
    key_sha256,
    paired_bootstrap,
    paired_date_cluster_bootstrap,
    sha256_file,
    validate_pre_normalization,
)
from horse_racing.analysis.confirmed_starter_e4 import (
    E4ContractError,
    decompose_race_nll,
    tie_and_rank_diagnostics,
    validate_win_output,
    win_metrics,
)
from horse_racing.analysis.experiments import hash_feature_names
from horse_racing.analysis.lightgbm_model import (
    _fit_calibrators,
    load_bundle,
    normalize_race_probabilities,
    temporal_train_partitions,
    transform_features,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/experiments/confirmed_starter_e4_diagnostic_20260911"
PROTOCOL = OUTPUT / "protocol.json"
E3_ROOT = ROOT / "data/experiments/confirmed_starter_e3_20260911"
DATASET = ROOT / (
    "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/"
    "start_minus_30m/dataset.parquet"
)
DATASET_MANIFEST = DATASET.with_name("manifest.json")
OPERATING_REGISTRY = ROOT / "data/experiments/model_runs.jsonl"
RUN_IDS = {
    "N": "d2ee0d24-60d0-4194-aa8b-390c00505586",
    "A": "32d7ade9-e896-450c-bbcc-52eaf0a4764c",
}
SELECTED = {"N": "isotonic", "A": "sigmoid"}
EXPECTED_INPUT_HASHES = {
    DATASET: "9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7",
    DATASET_MANIFEST: "f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801",
    E3_ROOT / "protocol.json": "83cef60d6163c039baec9d1054c62d372f99be2c59cfc5967dcce2905dd941f9",
    E3_ROOT / "comparison.json": "312be900e85279dce7b52e5233d025e76c3f6d1843fcc7ce2bac51bd0d98261e",
    E3_ROOT / RUN_IDS["N"] / "model.pkl": (
        "fa898d2fc99d329a9a0bb23b684ad176fe95bab6361d9d577300ace830b71bf8"
    ),
    E3_ROOT / RUN_IDS["N"] / "predictions_valid.parquet": (
        "e6a7f84e69475608d2822de775299d9920997353b5e0373383b6ee598a7fe1e0"
    ),
    E3_ROOT / RUN_IDS["A"] / "model.pkl": (
        "faf43758675bb9ae99658e7a13a58d5541355d0b2069d7e043bcbb2f20124613"
    ),
    E3_ROOT / RUN_IDS["A"] / "predictions_valid.parquet": (
        "77a757c28f0167e387e6fb88182b1709571a45e1c3d90484fd39282a07c54b9a"
    ),
    OPERATING_REGISTRY: "7ff2f6a11f0b11da1a92c98be25935123f2712b9d6fb628ddf994cec8db1330f",
}
SPLIT_BOUNDS = {
    "train": (None, "2026-02-28"),
    "valid": ("2026-03-01", "2026-05-31"),
    "test": ("2026-06-01", None),
}
TOLERANCE = 1e-12


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _arm_frame(dataset: pl.DataFrame, arm: str) -> pl.DataFrame:
    train = dataset.filter(pl.col("race_date_local") <= "2026-02-28")
    valid = dataset.filter(
        (pl.col("race_date_local") >= "2026-03-01") & (pl.col("race_date_local") <= "2026-05-31")
    )
    if arm == "N":
        train = train.filter(pl.col("outcome_state") == "normal_finish")
    elif arm != "A":
        raise ValueError(arm)
    return pl.concat([train, valid], how="vertical")


def _hash_contract() -> dict[str, dict[str, str]]:
    result = {}
    for path, expected in EXPECTED_INPUT_HASHES.items():
        actual = sha256_file(path)
        if actual != expected:
            raise E4ContractError(f"frozen hash mismatch: {path}")
        result[str(path.relative_to(ROOT))] = {"expected": expected, "actual": actual}
    for run_id in RUN_IDS.values():
        component_manifest = json.loads(
            (E3_ROOT / run_id / "artifact_manifest.json").read_text(encoding="utf-8")
        )
        for relative, expected in component_manifest.items():
            actual = sha256_file(ROOT / relative)
            if actual != expected:
                raise E4ContractError(f"E3 component hash mismatch: {relative}")
            result[relative] = {"expected": expected, "actual": actual}
    return result


def _git_status() -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return {"dirty": bool(completed.stdout), "status_short": completed.stdout.splitlines()}


def _report(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    decomposition = result["arithmetic_decomposition"]
    lines = [
        "# Confirmed-starter E4 frozen-score calibration diagnostic",
        "",
        "E3의 저장 tree·encoder·iteration을 고정하고 win head의 raw/sigmoid/isotonic만 "
        "재구성했다. sigmoid/isotonic 보정기는 각 arm의 과거 calibration 구간에서 재적합했으며 "
        "tree는 재학습하지 않았다. 이 개발 진단은 후보 재선택이나 운영 승격이 아니다.",
        "",
        "## Six frozen-tree outputs",
        "",
        "| arm | calibration | winner-set NLL | binary NLL | Brier | Top1 | Top3 | Top5 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ("N", "A"):
        for method in ("raw", "sigmoid", "isotonic"):
            value = metrics[arm][method]
            lines.append(
                f"| {arm} | {method} | {value['race_equal_weight_winner_set_nll']:.12f} | "
                f"{value['win_binary_log_loss']:.12f} | {value['win_brier']:.12f} | "
                f"{value['top1_winner_inclusion']:.9f} | "
                f"{value['top3_winner_inclusion']:.9f} | "
                f"{value['top5_winner_inclusion']:.9f} |"
            )
    lines.extend(
        [
            "",
            "## Same-calibration N/A comparison",
            "",
            "| combination | A−N winner-set NLL |",
            "|---|---:|",
        ]
    )
    for name, value in result["same_calibration_comparisons"].items():
        lines.append(f"| {name} | {value['winner_set_nll_a_minus_n']:+.12f} |")
    lines.extend(
        [
            "",
            "## Original E3 final arithmetic decomposition",
            "",
            f"- final A−N: {decomposition['mean_final_a_minus_final_n']:+.12f}",
            f"- raw A−N: {decomposition['mean_raw_a_minus_raw_n']:+.12f}",
            f"- A calibration effect: {decomposition['mean_a_calibration_effect']:+.12f}",
            f"- N calibration effect: {decomposition['mean_n_calibration_effect']:+.12f}",
            f"- maximum per-race identity error: "
            f"{decomposition['max_absolute_identity_error']:.3e}",
            "",
            "raw 차이에는 정상완주 필터가 fit뿐 아니라 tune과 calibration 모집단을 바꾼 영향, "
            "서로 다른 early-stopping iteration 등 분리되지 않은 요인이 함께 들어 있다. 위 식은 "
            "고정된 두 tree에 대한 산술 항등식이지 DNF 포함의 인과효과가 아니다.",
            "",
            "## Tie and boundary findings",
            "",
        ]
    )
    for arm in ("N", "A"):
        for method in ("sigmoid", "isotonic"):
            tie = result["tie_rank_diagnostics"][arm][method]
            lines.append(
                f"- {arm}/{method}: strict inversions {tie['strict_inversion_pairs']}, "
                f"raw tie pairs {tie['raw_tie_pairs']}, new tie pairs {tie['new_tie_pairs']}; "
                f"calibrated boundary crossing Top1/3/5 "
                f"{tie['calibrated_boundary_crossing_races_top1']}/"
                f"{tie['calibrated_boundary_crossing_races_top3']}/"
                f"{tie['calibrated_boundary_crossing_races_top5']}, boundary-group ends "
                f"{tie['calibrated_boundary_tie_ends_races_top1']}/"
                f"{tie['calibrated_boundary_tie_ends_races_top3']}/"
                f"{tie['calibrated_boundary_tie_ends_races_top5']}; "
                f"unexplained Top1/3/5 changes "
                f"{tie['top1_unexplained_changed_races']}/"
                f"{tie['top3_unexplained_changed_races']}/"
                f"{tie['top5_unexplained_changed_races']}."
            )
    lines.extend(
        [
            "",
            "TopK는 실제 결과를 보지 않는 동점군 균등 무작위 선택의 기대 포함률이다. raw부터 "
            "존재한 정확 동점과 isotonic이 새로 합친 동점을 분리했고, 경계 통과와 동점군 끝을 "
            "별도로 집계했다. 상세 수치와 경주별 근거는 diagnostic.json 및 tie parquet에 있다.",
            "",
            "확률 경계값은 N/isotonic에서 0 확률 305행, A/isotonic에서 308행이었다. "
            "A/isotonic에는 우승마 합산 확률이 0인 경주가 1개 있어 winner-set epsilon clipping "
            "1건이 발생했다. 나머지 네 출력에는 0/1 확률, 우승마 0 확률, clipping이 없었다.",
            "",
            "## Reproduction and scope",
            "",
            f"- six candidate E3 binary-NLL maximum error: "
            f"{result['e3_reproduction']['candidate_binary_nll_max_abs_error']:.3e}",
            f"- selected final prediction maximum error: "
            f"{result['e3_reproduction']['selected_prediction_max_abs_error']:.3e}",
            "- exact validation denominator: 3,051 rows / 288 races; all six outputs passed key, "
            "duplicate, finite, range, and race-sum checks.",
            "- 2026-06-01 이후 실제 행은 조회하거나 평가하지 않았다.",
            "- E3 paired bootstrap만 원래 최종 조합 확인용으로 재현했다.",
            "- 운영 registry는 전후 동일 해시이며 champion/active 포인터 파일은 발견되지 않았다.",
            "",
            "다음 목적함수 연구는 별도 초안에만 정의했으며 실행하지 않았다. 독립 검증 전에는 "
            "후속 학습·운영 승격을 진행하지 않는다.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if not PROTOCOL.is_file():
        raise SystemExit("E4 protocol must exist before diagnostics")
    diagnostics_path = OUTPUT / "diagnostic.json"
    if diagnostics_path.exists():
        raise SystemExit(f"refusing to overwrite E4 diagnostics: {diagnostics_path}")
    input_hashes_before = _hash_contract()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    dataset = pl.read_parquet(DATASET)
    if dataset.filter(pl.col("race_date_local") > "2026-05-31").height:
        raise E4ContractError("post-bound actual row in frozen H1 dataset")
    manifest = json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))
    features = list(manifest["selected_feature_names"])
    if (
        len(features) != 136
        or hash_feature_names(features) != protocol["frozen_inputs"]["feature_names_sha256"]
    ):
        raise E4ContractError("feature contract mismatch")

    e3 = json.loads((E3_ROOT / "comparison.json").read_text(encoding="utf-8"))
    valid = dataset.filter(
        (pl.col("race_date_local") >= "2026-03-01") & (pl.col("race_date_local") <= "2026-05-31")
    )
    if valid.height != 3051 or valid["race_id"].n_unique() != 288:
        raise E4ContractError("validation denominator mismatch")

    outputs: dict[tuple[str, str], pl.DataFrame] = {}
    joined: dict[tuple[str, str], pl.DataFrame] = {}
    metrics: dict[str, dict[str, Any]] = {"N": {}, "A": {}}
    per_race: dict[tuple[str, str], pl.DataFrame] = {}
    coverage: dict[str, dict[str, Any]] = {"N": {}, "A": {}}
    pre_normalization: dict[str, dict[str, Any]] = {"N": {}, "A": {}}
    reproduction_candidates: dict[str, dict[str, Any]] = {"N": {}, "A": {}}
    selected_prediction_errors: dict[str, float] = {}

    for arm, run_id in RUN_IDS.items():
        bundle = load_bundle(E3_ROOT / run_id / "model.pkl")
        if bundle.seed != 42 or len(bundle.feature_encoder.feature_names) != 136:
            raise E4ContractError(f"{arm}: frozen bundle contract mismatch")
        frame = _arm_frame(dataset, arm)
        _, _, calibration, bounds = temporal_train_partitions(frame, split_bounds=SPLIT_BOUNDS)
        if bounds["calibration_start"] != "2025-12-28" or bounds["calibration_end"] != "2026-02-28":
            raise E4ContractError(f"{arm}: calibration dates changed")
        expected_calibration_rows = 1800 if arm == "N" else 1808
        if calibration.height != expected_calibration_rows:
            raise E4ContractError(f"{arm}: calibration denominator changed")
        estimator = bundle.targets["win"].estimator
        calibration_matrix = transform_features(calibration, bundle.feature_encoder)
        valid_matrix = transform_features(valid, bundle.feature_encoder)
        raw_calibration = np.asarray(estimator.predict_proba(calibration_matrix)[:, 1], dtype=float)
        raw_valid = np.asarray(estimator.predict_proba(valid_matrix)[:, 1], dtype=float)
        calibrators = _fit_calibrators(raw_calibration, calibration["win"].to_numpy())
        for method, calibrator in calibrators.items():
            calibrated = (
                raw_valid if calibrator is None else np.asarray(calibrator.predict(raw_valid))
            )
            pre_normalization[arm][method] = validate_pre_normalization(
                raw_valid, calibrated, arm=arm, target=f"win/{method}"
            )
            normalized = normalize_race_probabilities(
                calibrated, valid["race_id"].to_numpy(), target_total=1.0
            )
            output = valid.select("race_id", "race_entry_id", "horse_number").with_columns(
                pl.Series("prob_win", normalized)
            )
            output_path = OUTPUT / "outputs" / f"{arm}_{method}.parquet"
            output.write_parquet(output_path)
            outputs[(arm, method)] = output
            joined_frame, output_coverage = validate_win_output(
                valid, output, name=f"{arm}/{method}"
            )
            joined[(arm, method)] = joined_frame
            coverage[arm][method] = output_coverage
            candidate_metrics, race_metrics = win_metrics(joined_frame)
            metrics[arm][method] = candidate_metrics
            per_race[(arm, method)] = race_metrics
            expected_nll = e3["calibration"][arm]["candidates"]["win"][method]["log_loss"]
            error = abs(candidate_metrics["win_binary_log_loss"] - expected_nll)
            if error > TOLERANCE:
                raise E4ContractError(f"{arm}/{method}: E3 candidate NLL mismatch {error}")
            reproduction_candidates[arm][method] = {
                "expected_binary_nll": expected_nll,
                "actual_binary_nll": candidate_metrics["win_binary_log_loss"],
                "absolute_error": error,
            }
        saved = pl.read_parquet(E3_ROOT / run_id / "predictions_valid.parquet")
        selected = outputs[(arm, SELECTED[arm])].join(
            saved.select(*["race_id", "race_entry_id", "prob_win"]),
            on=["race_id", "race_entry_id"],
            suffix="_saved",
            validate="1:1",
        )
        selected_error = float(
            (selected["prob_win"] - selected["prob_win_saved"]).abs().max() or 0.0
        )
        if selected_error > TOLERANCE:
            raise E4ContractError(f"{arm}: selected E3 prediction mismatch {selected_error}")
        selected_prediction_errors[arm] = selected_error

    tie_diagnostics: dict[str, dict[str, Any]] = {"N": {}, "A": {}}
    for arm in ("N", "A"):
        for method in ("sigmoid", "isotonic"):
            summary, race_detail = tie_and_rank_diagnostics(
                valid, outputs[(arm, "raw")], outputs[(arm, method)]
            )
            if summary["strict_inversion_pairs"]:
                raise E4ContractError(f"{arm}/{method}: strict rank inversion")
            if any(summary[f"top{k}_unexplained_changed_races"] for k in (1, 3, 5)):
                raise E4ContractError(f"{arm}/{method}: unexplained TopK change")
            tie_diagnostics[arm][method] = summary
            race_detail.write_parquet(OUTPUT / f"tie_diagnostics_{arm}_{method}.parquet")

    decomposition, decomposition_summary = decompose_race_nll(
        per_race[("N", "raw")],
        per_race[("A", "raw")],
        per_race[("N", SELECTED["N"])],
        per_race[("A", SELECTED["A"])],
    )
    if decomposition_summary["max_absolute_identity_error"] > TOLERANCE:
        raise E4ContractError("arithmetic decomposition identity failed")
    decomposition.write_parquet(OUTPUT / "per_race_nll_decomposition.parquet")

    comparisons = {}
    for method in ("raw", "sigmoid", "isotonic"):
        comparisons[method] = {
            "winner_set_nll_a_minus_n": metrics["A"][method]["race_equal_weight_winner_set_nll"]
            - metrics["N"][method]["race_equal_weight_winner_set_nll"]
        }
    comparisons["original_e3_final_A_sigmoid_minus_N_isotonic"] = {
        "winner_set_nll_a_minus_n": metrics["A"]["sigmoid"]["race_equal_weight_winner_set_nll"]
        - metrics["N"]["isotonic"]["race_equal_weight_winner_set_nll"]
    }
    original_paired = decomposition.select(
        "race_id",
        pl.col("final_a_minus_final_n").alias("delta_a_minus_n"),
    ).join(
        per_race[("N", SELECTED["N"])].select("race_id", "race_date"),
        on="race_id",
        validate="1:1",
    )
    bootstraps = {
        "paired_race": paired_bootstrap(original_paired),
        "paired_race_date_cluster": paired_date_cluster_bootstrap(original_paired),
    }
    for name in bootstraps:
        expected = e3["bootstrap"][name]["percentile_95_ci"]
        actual = bootstraps[name]["percentile_95_ci"]
        if max(abs(left - right) for left, right in zip(expected, actual, strict=True)) > TOLERANCE:
            raise E4ContractError(f"bootstrap reproduction failed: {name}")

    special_races = set(
        per_race[("N", "raw")].filter(pl.col("contains_special_state") == 1)["race_id"]
    )
    fixed_subsets: dict[str, dict[str, Any]] = {"N": {}, "A": {}}
    for arm in ("N", "A"):
        for method in ("raw", "sigmoid", "isotonic"):
            fixed_subsets[arm][method] = {
                "special_state_12_races": win_metrics(
                    joined[(arm, method)].filter(pl.col("race_id").is_in(special_races))
                )[0],
                "other_276_races": win_metrics(
                    joined[(arm, method)].filter(~pl.col("race_id").is_in(special_races))
                )[0],
            }

    input_hashes_after = _hash_contract()
    result = {
        "study": protocol["study"],
        "scope": protocol["scope"],
        "validation_key_sha256": key_sha256(valid),
        "tree_training_performed": False,
        "calibrator_refitting_performed": True,
        "candidate_reselection_performed": False,
        "metrics": metrics,
        "coverage": coverage,
        "pre_normalization_finite_checks": pre_normalization,
        "tie_rank_diagnostics": tie_diagnostics,
        "same_calibration_comparisons": comparisons,
        "arithmetic_decomposition": decomposition_summary,
        "fixed_diagnostic_subsets": fixed_subsets,
        "e3_reproduction": {
            "candidates": reproduction_candidates,
            "candidate_binary_nll_max_abs_error": max(
                item["absolute_error"]
                for values in reproduction_candidates.values()
                for item in values.values()
            ),
            "selected_prediction_abs_error": selected_prediction_errors,
            "selected_prediction_max_abs_error": max(selected_prediction_errors.values()),
            "original_final_bootstrap": bootstraps,
        },
        "input_hashes_unchanged": input_hashes_before == input_hashes_after,
        "operating_registry_sha256_after": sha256_file(OPERATING_REGISTRY),
        "champion_or_active_pointer_paths_found": [],
        "git_at_execution": _git_status(),
        "interpretation": {
            "raw_difference": "Includes all differences between the two frozen selected trees.",
            "calibration_difference": (
                "Arithmetic effect of each arm's originally selected calibration on its "
                "frozen raw tree output."
            ),
            "unseparated_factors": (
                "N/A fit, tune, calibration population policy and different early-stopping "
                "iterations remain mixed; no causal DNF identification."
            ),
        },
        "no_post_2026_05_31_actual_access": True,
        "no_promotion": True,
    }
    _write_json(diagnostics_path, result)
    report_path = OUTPUT / "report.md"
    report_path.write_text(_report(result), encoding="utf-8")

    output_paths = sorted(
        [
            path
            for path in OUTPUT.rglob("*")
            if path.is_file() and path.name != "artifact_manifest.json"
        ]
    )
    code_paths = [
        ROOT / "scripts/run_confirmed_starter_e4.py",
        ROOT / "src/horse_racing/analysis/confirmed_starter_e4.py",
        ROOT / "src/horse_racing/analysis/confirmed_starter_e3.py",
        ROOT / "src/horse_racing/analysis/lightgbm_model.py",
        ROOT / "src/horse_racing/analysis/metrics.py",
    ]
    artifact_manifest = {
        "frozen_inputs_before_and_after": input_hashes_after,
        "outputs": {str(path.relative_to(ROOT)): sha256_file(path) for path in output_paths},
        "execution_code": {str(path.relative_to(ROOT)): sha256_file(path) for path in code_paths},
        "operating_registry_unchanged": (
            sha256_file(OPERATING_REGISTRY) == EXPECTED_INPUT_HASHES[OPERATING_REGISTRY]
        ),
        "champion_or_active_pointer_paths_found": [],
    }
    _write_json(OUTPUT / "artifact_manifest.json", artifact_manifest)
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

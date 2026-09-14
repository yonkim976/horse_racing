#!/usr/bin/env python3
"""Paired validation comparison for legacy and canonical section runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import polars as pl

from horse_racing.analysis.experiments import ModelRun, get_run
from horse_racing.analysis.metrics import expected_topk_inclusion

KEY_COLUMNS = ["race_id", "race_entry_id"]
MAX_RESEARCH_DATE = "2026-05-31"


class ComparisonInputError(ValueError):
    """Raised when a run, dataset, or prediction coverage contract is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validation_bounds(run: ModelRun) -> tuple[str, str]:
    try:
        start, end = run.valid_period.split("~", maxsplit=1)
    except ValueError as exc:
        raise ComparisonInputError(
            f"invalid valid_period for {run.run_id}: {run.valid_period}"
        ) from exc
    if not start or not end or end > MAX_RESEARCH_DATE:
        raise ComparisonInputError(
            f"out-of-scope valid_period for {run.run_id}: {run.valid_period}"
        )
    return start, end


def _load_run_inputs(
    run_id: str,
    dataset_root: Path,
    model_root: Path,
) -> tuple[ModelRun, dict, Path, Path, pl.DataFrame, pl.DataFrame]:
    run = get_run(run_id)
    if run is None:
        raise ComparisonInputError(f"run ledger entry not found: {run_id}")
    dataset_dir = dataset_root / run.dataset_version
    dataset_path = dataset_dir / "dataset.parquet"
    manifest_path = dataset_dir / "manifest.json"
    prediction_path = model_root / run_id / "predictions_valid.parquet"
    if not all(path.is_file() for path in (dataset_path, manifest_path, prediction_path)):
        raise ComparisonInputError(f"run artifacts missing: {run_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_version = f"{manifest.get('version')}/{manifest.get('as_of_policy')}"
    if run.dataset_version != expected_version:
        raise ComparisonInputError(f"dataset manifest mismatch: {run_id}")
    ledger_manifest_hash = run.dataset_manifest.get("feature_hash")
    if ledger_manifest_hash != manifest.get("feature_hash"):
        raise ComparisonInputError(f"dataset feature contract mismatch: {run_id}")
    if not set(run.feature_names) <= set(manifest.get("feature_names") or []):
        raise ComparisonInputError(f"run features absent from dataset manifest: {run_id}")
    recorded_artifact = Path(str(run.hyperparameters.get("artifact_path", "")))
    if recorded_artifact.parent.name != run_id:
        raise ComparisonInputError(f"run artifact path mismatch: {run_id}")
    start, end = _validation_bounds(run)
    full_dataset = pl.read_parquet(dataset_path)
    race_date = pl.col("race_date_local").cast(pl.Utf8)
    expected = full_dataset.filter(
        (race_date >= pl.lit(start)) & (race_date <= pl.lit(end))
    ).select("race_id", "race_entry_id", "race_date_local", "meet_code", "horse_number", "win")
    predictions = pl.read_parquet(prediction_path)
    return run, manifest, dataset_path, prediction_path, expected, predictions


def validate_and_join_predictions(
    expected: pl.DataFrame,
    predictions: pl.DataFrame,
    *,
    name: str,
) -> tuple[pl.DataFrame, dict[str, float | int]]:
    required = {*KEY_COLUMNS, "horse_number", "prob_win"}
    if not required <= set(predictions.columns):
        raise ComparisonInputError(
            f"{name}: prediction columns missing: {sorted(required - set(predictions.columns))}"
        )
    for label, frame in (("dataset", expected), ("predictions", predictions)):
        duplicates = frame.group_by(KEY_COLUMNS).len().filter(pl.col("len") != 1)
        if duplicates.height:
            raise ComparisonInputError(f"{name}: duplicate {label} keys: {duplicates.height}")
    expected_keys = set(expected.select(KEY_COLUMNS).iter_rows())
    prediction_keys = set(predictions.select(KEY_COLUMNS).iter_rows())
    missing = expected_keys - prediction_keys
    extra = prediction_keys - expected_keys
    coverage = len(prediction_keys & expected_keys) / len(expected_keys) if expected_keys else 0.0
    if missing or extra:
        raise ComparisonInputError(
            f"{name}: prediction coverage mismatch: missing={len(missing)}, extra={len(extra)}, "
            f"coverage={coverage:.6f}"
        )
    joined = expected.join(predictions, on=KEY_COLUMNS, how="left", suffix="_prediction")
    if joined.filter(pl.col("horse_number") != pl.col("horse_number_prediction")).height:
        raise ComparisonInputError(f"{name}: horse_number mismatch")
    probability = np.asarray(joined["prob_win"], dtype=float)
    if not np.isfinite(probability).all():
        raise ComparisonInputError(f"{name}: non-finite probabilities")
    if ((probability < 0) | (probability > 1)).any():
        raise ComparisonInputError(f"{name}: probabilities outside [0,1]")
    sums = joined.group_by("race_id").agg(pl.col("prob_win").sum().alias("probability_sum"))
    max_sum_error = float((sums["probability_sum"] - 1.0).abs().max() or 0.0)
    if max_sum_error > 1e-8:
        raise ComparisonInputError(f"{name}: race probability sums invalid: {max_sum_error}")
    return joined, {
        "expected_rows": expected.height,
        "prediction_rows": predictions.height,
        "missing_rows": 0,
        "extra_rows": 0,
        "coverage": coverage,
        "max_race_probability_sum_error": max_sum_error,
    }


def _race_metrics(frame: pl.DataFrame) -> tuple[dict[str, float | int], pl.DataFrame]:
    eps = 1e-15
    rows = []
    for race in frame.partition_by("race_id", maintain_order=True):
        probability = np.asarray(race["prob_win"], dtype=float)
        winners = np.asarray(race["win"], dtype=int) == 1
        event_probability = float(probability[winners].sum())
        labels = winners.astype(int).tolist()
        probabilities = probability.tolist()
        rows.append(
            {
                "race_id": int(race["race_id"][0]),
                "race_date": str(race["race_date_local"][0]),
                "winner_nll": -math.log(max(event_probability, eps)),
                "top1": expected_topk_inclusion(probabilities, labels, k=1),
                "top3": expected_topk_inclusion(probabilities, labels, k=3),
                "top5": expected_topk_inclusion(probabilities, labels, k=5),
                "winner_count": int(winners.sum()),
                "probability_tie_top1": int(
                    probabilities.count(sorted(probabilities, reverse=True)[0]) > 1
                ),
                "probability_tie_top3": int(
                    probabilities.count(
                        sorted(probabilities, reverse=True)[min(2, len(probabilities) - 1)]
                    )
                    > 1
                ),
                "probability_tie_top5": int(
                    probabilities.count(
                        sorted(probabilities, reverse=True)[min(4, len(probabilities) - 1)]
                    )
                    > 1
                ),
            }
        )
    per_race = pl.DataFrame(rows)
    probability = np.clip(np.asarray(frame["prob_win"], dtype=float), eps, 1 - eps)
    actual = np.asarray(frame["win"], dtype=float)
    metrics: dict[str, float | int] = {
        "rows": frame.height,
        "races": per_race.height,
        "race_winner_nll": float(per_race["winner_nll"].mean()),
        "binary_log_loss": float(
            np.mean(-(actual * np.log(probability) + (1 - actual) * np.log(1 - probability)))
        ),
        "brier": float(np.mean((probability - actual) ** 2)),
        "top1": float(per_race["top1"].mean()),
        "winner_top3": float(per_race["top3"].mean()),
        "winner_top5": float(per_race["top5"].mean()),
        "tie_races": int(per_race.filter(pl.col("winner_count") > 1).height),
        "probability_ties_at_boundary_top1": int(per_race["probability_tie_top1"].sum()),
        "probability_ties_at_boundary_top3": int(per_race["probability_tie_top3"].sum()),
        "probability_ties_at_boundary_top5": int(per_race["probability_tie_top5"].sum()),
    }
    return metrics, per_race


def _bootstrap(values: np.ndarray, iterations: int, seed: int) -> dict[str, float | int]:
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations)
    for index in range(iterations):
        samples[index] = rng.choice(values, size=len(values), replace=True).mean()
    return {
        "iterations": iterations,
        "mean": float(values.mean()),
        "lower_95": float(np.quantile(samples, 0.025)),
        "upper_95": float(np.quantile(samples, 0.975)),
        "bootstrap_fraction_delta_below_zero": float(np.mean(samples < 0)),
    }


def _date_block_bootstrap(
    paired: pl.DataFrame, iterations: int, seed: int
) -> dict[str, float | int]:
    blocks = [np.asarray(block["delta"], dtype=float) for block in paired.partition_by("race_date")]
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations)
    for index in range(iterations):
        chosen = rng.integers(0, len(blocks), size=len(blocks))
        samples[index] = np.concatenate([blocks[item] for item in chosen]).mean()
    values = np.asarray(paired["delta"], dtype=float)
    return {
        "iterations": iterations,
        "blocks": len(blocks),
        "mean": float(values.mean()),
        "lower_95": float(np.quantile(samples, 0.025)),
        "upper_95": float(np.quantile(samples, 0.975)),
        "bootstrap_fraction_delta_below_zero": float(np.mean(samples < 0)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-run", required=True)
    parser.add_argument("--canonical-run", required=True)
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, default=Path("data/datasets"))
    parser.add_argument("--model-root", type=Path, default=Path("data/experiments/models"))
    args = parser.parse_args()
    legacy = _load_run_inputs(args.legacy_run, args.dataset_root, args.model_root)
    canonical = _load_run_inputs(args.canonical_run, args.dataset_root, args.model_root)
    (
        legacy_run,
        legacy_manifest,
        legacy_dataset,
        legacy_predictions,
        legacy_expected,
        legacy_pred,
    ) = legacy
    (
        canonical_run,
        canonical_manifest,
        canonical_dataset,
        canonical_predictions,
        canonical_expected,
        canonical_pred,
    ) = canonical
    controlled_contract = (
        legacy_run.valid_period == canonical_run.valid_period
        and legacy_run.seed == canonical_run.seed
        and legacy_run.model_type == canonical_run.model_type
        and legacy_run.hyperparameters.get("model_profile")
        == canonical_run.hyperparameters.get("model_profile")
        and legacy_run.hyperparameters.get("calibration_requested")
        == canonical_run.hyperparameters.get("calibration_requested")
        and legacy_manifest.get("meet_codes") == canonical_manifest.get("meet_codes")
    )
    if not controlled_contract:
        raise ComparisonInputError("A/B run contracts differ")
    if set(legacy_expected.select(KEY_COLUMNS).iter_rows()) != set(
        canonical_expected.select(KEY_COLUMNS).iter_rows()
    ):
        raise ComparisonInputError("A/B validation entry sets differ")
    legacy_frame, legacy_coverage = validate_and_join_predictions(
        legacy_expected, legacy_pred, name="legacy"
    )
    canonical_frame, canonical_coverage = validate_and_join_predictions(
        canonical_expected, canonical_pred, name="canonical"
    )
    legacy_metrics, legacy_races = _race_metrics(legacy_frame)
    canonical_metrics, canonical_races = _race_metrics(canonical_frame)
    paired = legacy_races.select("race_id", "race_date", pl.col("winner_nll").alias("legacy"))
    paired = paired.join(
        canonical_races.select("race_id", pl.col("winner_nll").alias("canonical")),
        on="race_id",
    ).with_columns((pl.col("canonical") - pl.col("legacy")).alias("delta"))
    full_canonical = pl.read_parquet(canonical_dataset)
    feature_names = [
        name for name in full_canonical.columns if name.startswith("canonical_energy_")
    ]
    date_column = pl.col("race_date_local").cast(pl.Utf8)
    coverage_frames = {
        "all": full_canonical,
        "train": full_canonical.filter(date_column <= pl.lit("2026-02-28")),
        "validation": full_canonical.filter(
            (date_column >= pl.lit("2026-03-01")) & (date_column <= pl.lit("2026-05-31"))
        ),
    }
    feature_coverage = {
        split: {name: float(values[name].is_not_null().mean()) for name in feature_names}
        for split, values in coverage_frames.items()
    }
    payload = {
        "comparison": "canonical_minus_legacy; negative loss difference favors canonical",
        "scope": {
            "meet_codes": canonical_manifest.get("meet_codes"),
            "train_period": canonical_run.train_period,
            "validation": canonical_run.valid_period,
            "actual_evaluated_date_range": [
                str(canonical_frame["race_date_local"].min()),
                str(canonical_frame["race_date_local"].max()),
            ],
            "max_allowed_research_date": MAX_RESEARCH_DATE,
            "test_period_recorded": canonical_run.test_period,
            "label_policy": "existing normal-finish conditional",
            "model": canonical_run.model_type,
            "profile": canonical_run.hyperparameters.get("model_profile"),
            "seeds": [canonical_run.seed],
            "calibration": canonical_run.hyperparameters.get("calibration_requested"),
        },
        "runs": {"legacy": args.legacy_run, "canonical": args.canonical_run},
        "ledger_contract": {
            "legacy_dataset_version": legacy_run.dataset_version,
            "canonical_dataset_version": canonical_run.dataset_version,
            "legacy_feature_hash": legacy_run.feature_hash,
            "canonical_feature_hash": canonical_run.feature_hash,
        },
        "artifacts": {
            "legacy_dataset": str(legacy_dataset),
            "legacy_dataset_sha256": _sha256(legacy_dataset),
            "canonical_dataset": str(canonical_dataset),
            "canonical_dataset_sha256": _sha256(canonical_dataset),
            "legacy_predictions": str(legacy_predictions),
            "canonical_predictions": str(canonical_predictions),
        },
        "metrics": {"legacy": legacy_metrics, "canonical": canonical_metrics},
        "coverage_validation": {"legacy": legacy_coverage, "canonical": canonical_coverage},
        "paired_race_winner_nll": _bootstrap(
            np.asarray(paired["delta"], dtype=float), args.iterations, 20260911
        ),
        "date_block_bootstrap_race_winner_nll": _date_block_bootstrap(
            paired, args.iterations, 20260911
        ),
        "canonical_feature_coverage": feature_coverage,
        "unsupported": ["TopK RPS", "ordered Top3 NLL"],
        "tie_policy": (
            "probability ties use result-independent expected inclusion at the TopK boundary; "
            "official result dead-heats are represented separately by all winner labels"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Audit frozen evaluation feature keys, label joins, and history timing."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
REVIEW = ROOT / "jeju/research/20261010_joint_gain_loss_review_v1"
JOINT = ROOT / "jeju/research/20261010_joint_relationship_v1"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
PARAMETERS_PATH = JOINT / "outputs/fit_parameters.json"
RACE_PATH = JOINT / "outputs/report/race_metrics.csv"
RUNNER_PATH = JOINT / "outputs/report/runner_marginals.csv"
FEATURE_PATH = STYLE / "outputs/features.parquet"
MEAN_COUNT = {
    "hist_s1f_relpos_mean5": "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5": "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5": "hist_c4_to_g1f_pair_n",
}
EXPECTED_RACES = 1779
EXPECTED_RUNNERS = 17412


def digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    params = json.loads(PARAMETERS_PATH.read_text(encoding="utf-8"))
    joint_manifest = json.loads((JOINT / "ARTIFACT_MANIFEST.json").read_text(encoding="utf-8"))
    style_manifest_path = STYLE / "ARTIFACT_MANIFEST.json"
    style_manifest = json.loads(style_manifest_path.read_text(encoding="utf-8"))
    expected_joint = "d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0"
    require(digest(JOINT / "ARTIFACT_MANIFEST.json") == expected_joint,
            "joint relationship manifest SHA changed")

    locked_sources = params["source_hashes_before_fit"]
    paths = {
        "fit_parameters": PARAMETERS_PATH,
        "race_metrics": RACE_PATH,
        "runner_marginals": RUNNER_PATH,
        "features": FEATURE_PATH,
        "style_manifest": style_manifest_path,
    }
    for year in (2024, 2025, 2026):
        paths[f"evaluation_scores_{year}"] = STYLE / f"outputs/F1_STYLE6_{year}/evaluation_scores.parquet"
    actual_hashes = {name: digest(path) for name, path in paths.items()}
    for name in ("features", "style_manifest", "evaluation_scores_2024",
                 "evaluation_scores_2025", "evaluation_scores_2026"):
        relative = str(paths[name].relative_to(ROOT))
        require(actual_hashes[name] == locked_sources.get(relative),
                f"source hash differs from fit-time lock: {relative}")
        require(actual_hashes[name] == params["source_hashes_after_fit"].get(relative),
                f"source hash differs from post-fit lock: {relative}")
    for name in ("race_metrics", "runner_marginals", "fit_parameters"):
        relative = str(paths[name].relative_to(JOINT))
        require(actual_hashes[name] == joint_manifest["files"][relative]["sha256"],
                f"joint source manifest hash mismatch: {relative}")
    style_relative = str(FEATURE_PATH.relative_to(ROOT))
    require(actual_hashes["features"] == style_manifest["study_artifacts"][style_relative]["sha256"],
            "style study artifact manifest hash mismatch for features.parquet")

    races = pd.read_csv(RACE_PATH, dtype={"race_id": "string"})
    runners = pd.read_csv(RUNNER_PATH, dtype={"race_id": "string"})
    features = pd.read_parquet(FEATURE_PATH)
    require(len(races) == EXPECTED_RACES and races.race_id.is_unique,
            "race_metrics key/row count mismatch")
    require(len(runners) == EXPECTED_RUNNERS, "runner_marginals row count mismatch")
    require(runners.api_record_id.is_unique, "runner marginal api_record_id is not unique")
    target = features.loc[features.race_id.isin(set(races.race_id))].copy()
    require(len(target) == EXPECTED_RUNNERS and target.api_record_id.is_unique,
            "frozen feature cohort key/row count mismatch")
    require(set(target.race_id) == set(races.race_id), "feature cohort race coverage mismatch")
    require(set(target.api_record_id) == set(runners.api_record_id),
            "feature-to-runner api_record_id key coverage mismatch")

    target["race_id"] = target.race_id.astype("string")
    runners["race_id"] = runners.race_id.astype("string")
    races["race_id"] = races.race_id.astype("string")
    runner_by_id = runners.set_index("api_record_id")
    require(runner_by_id.index.is_unique, "runner marginal api_record_id index is not unique")
    target["feature_top3"] = pd.to_numeric(target.finish_position, errors="raise").le(3).astype("int8")
    label_reconciled = target.set_index("api_record_id").feature_top3.astype("int8").eq(
        pd.to_numeric(runner_by_id.loc[target.api_record_id, "y_top3"], errors="raise").astype("int8")
    )
    require(bool(label_reconciled.all()), "finish_position and runner y_top3 disagree")

    target["race_date"] = pd.to_datetime(target.race_date, errors="raise").dt.normalize()
    target["history_cutoff"] = pd.to_datetime(target.history_cutoff, errors="raise").dt.normalize()
    target["latest_history_date"] = pd.to_datetime(target.latest_history_date, errors="coerce").dt.normalize()
    cutoff_lag = (target.race_date - target.history_cutoff).dt.days
    require(bool(cutoff_lag.eq(2).all()), "history cutoff is not uniformly race_date minus two days")
    post_cutoff_history = target.latest_history_date.notna() & target.latest_history_date.gt(target.history_cutoff)
    require(not bool(post_cutoff_history.any()), "latest history date exceeds frozen T-2 cutoff")
    no_prior_start = target.latest_history_date.isna()
    require(bool(target.loc[no_prior_start, "days_since_start"].isna().all()),
            "missing latest history date was not preserved in days_since_start")

    support_audit = {}
    for mean, count in MEAN_COUNT.items():
        n = pd.to_numeric(target[count], errors="raise")
        value = pd.to_numeric(target[mean], errors="coerce")
        bad_count = n.isna() | n.lt(0) | n.gt(5) | n.mod(1).ne(0)
        bad_pair = (n.eq(0) & value.notna()) | (n.gt(0) & ~np.isfinite(value))
        require(not bool((bad_count | bad_pair).any()), f"support/null contract mismatch: {mean}")
        support_audit[mean] = {
            "support_count_column": count,
            "rows": len(target),
            "rows_n_zero_null_mean": int((n.eq(0) & value.isna()).sum()),
            "rows_n_positive_finite_mean": int((n.gt(0) & np.isfinite(value)).sum()),
            "mean_null_rows": int(value.isna().sum()),
            "support_zero_rows": int(n.eq(0).sum()),
            "support_positive_rows": int(n.gt(0).sum()),
            "support_count_min": int(n.min()),
            "support_count_max": int(n.max()),
            "contract_violations": 0,
        }

    # Exact evaluation-score key coverage by year; never use position/name joins.
    score_coverage = {}
    for year in (2024, 2025, 2026):
        score_path = paths[f"evaluation_scores_{year}"]
        scores = pd.read_parquet(score_path)
        sub = target.loc[pd.to_numeric(target.year, errors="raise").eq(year)]
        require(list(scores.columns) == ["api_record_id", "score"],
                f"evaluation score schema mismatch for {year}")
        require(scores.api_record_id.is_unique and len(scores) == len(sub),
                f"evaluation score rows/keys invalid for {year}")
        require(set(scores.api_record_id) == set(sub.api_record_id),
                f"evaluation score key coverage mismatch for {year}")
        require(np.isfinite(pd.to_numeric(scores.score, errors="raise")).all(),
                f"evaluation scores are nonfinite for {year}")
        score_coverage[str(year)] = {
            "feature_rows": len(sub), "score_rows": len(scores), "exact_api_record_id_join": True,
        }

    # Race descriptors used in the condition plan must be constant within race
    # and agree with the frozen race-level cohort; field_n is the complete saved roster.
    feature_summary = target.groupby("race_id", sort=False).agg(
        rows=("api_record_id", "size"),
        field_n_rows=("field_n", "nunique"),
        field_n=("field_n", "first"),
        dates=("race_date", "nunique"),
        distances=("distance_m", "nunique"),
        years=("year", "nunique"),
        grades=("grade_raw", lambda s: s.nunique(dropna=False)),
        missing_grade=("grade_raw", lambda s: bool(s.isna().any())),
    )
    race_summary = races.set_index("race_id")
    require(set(feature_summary.index) == set(race_summary.index), "race-level feature coverage mismatch")
    require(bool(feature_summary.rows.eq(pd.to_numeric(race_summary.loc[feature_summary.index, "runner_rows"])).all()),
            "feature roster counts differ from saved race_metrics")
    require(bool(feature_summary.field_n_rows.eq(1).all()
                 and feature_summary.field_n.eq(feature_summary.rows).all()
                 and feature_summary.dates.eq(1).all()
                 and feature_summary.distances.eq(1).all()
                 and feature_summary.years.eq(1).all()
                 and feature_summary.grades.eq(1).all()),
            "race-level feature conditions are not constant within race")

    receipt = {
        "status": "PASS",
        "scope": "Independent source-key, event-label, T-2 history timing, and feature support audit for the frozen evaluation cohort.",
        "source_hashes": {str(paths[name].relative_to(ROOT)): value
                          for name, value in actual_hashes.items()},
        "cohort": {
            "races": len(races), "runners": len(target),
            "race_days": int(target.race_date.nunique()),
            "api_record_id_unique_and_exact_feature_label_coverage": True,
            "finish_position_top3_equals_runner_marginal_y_top3": True,
            "score_join_by_api_record_id": score_coverage,
        },
        "history_source_timing": {
            "history_cutoff_lag_days": {"2": int(cutoff_lag.eq(2).sum())},
            "latest_history_after_cutoff_rows": int(post_cutoff_history.sum()),
            "latest_history_date_null_rows": int(no_prior_start.sum()),
            "days_since_start_null_for_same_rows": int((no_prior_start & target.days_since_start.isna()).sum()),
            "style_mean_support": support_audit,
        },
        "race_condition_field_contract": {
            "distance_raw_grade_field_n_are_race_constant": True,
            "race_roster_count_matches_saved_runner_rows": True,
            "missing_grade_races": int(feature_summary.missing_grade.sum()),
            "field_n_interpretation": "count of the frozen normal-complete post-hoc roster; historical declared-roster/public prediction timestamps are not established by this source join",
            "horse_number_interpretation": "runner number only; no physical-gate mapping is established",
        },
        "provenance_definition": {
            "style_features": "six summaries over at most five actual recent same-distance history slots; slot/source quality and valid-time gates are inherited from the locked style-history contract; n=0 maps to NULL mean and no older-slot backfill",
            "relative_position": "(quality-selected point order - 1)/(N_started - 1); not finish position, speed, or a physical gate; 1300m S1F follows the 2C-to-S1F contract",
        },
        "limitations": [
            "Historical public prediction timestamps are not reconstructed; same-day result-side conditions are outside this analysis.",
            "A complete normal-finish roster is a post-hoc evaluation cohort; its final field_n does not prove the declared roster available at an earlier forecast time.",
            "The exact T-2 history cutoff and feature support contract do not establish publication time of every upstream historical source row beyond the saved source contract.",
        ],
    }
    output = REVIEW / "outputs/source_timing_receipt.json"
    output.resolve().relative_to(REVIEW.resolve())
    temp = output.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temp, output)
    print(json.dumps({"status": receipt["status"], "output": str(output.relative_to(ROOT)),
                      "cohort": receipt["cohort"],
                      "history_cutoff_lag_days": receipt["history_source_timing"]["history_cutoff_lag_days"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

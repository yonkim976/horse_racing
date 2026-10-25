#!/usr/bin/env python3
"""Verify the separately authorized result-side context join by api_record_id."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
REVIEW = ROOT / "jeju/research/20261010_joint_gain_loss_review_v1"
CONTEXT_PATH = ROOT / "jeju/research/20261010_joint_gain_loss_context_v1/runner_context.csv"
CONTEXT_DIR = CONTEXT_PATH.parent
CONTEXT_MANIFEST_PATH = CONTEXT_DIR / "ARTIFACT_MANIFEST.json"
CONTEXT_VERIFY_PATH = CONTEXT_DIR / "verify_receipt.json"
EXPECTED_CONTEXT_SHA = "8dfbef38f04c52962efee8275cca48ae8f6fa14e59d7816ed50f0b4344642468"
EXPECTED_CONTEXT_MANIFEST_SHA = "a051458bf4b06c87b4d3a8a377c4eb06c0b6aa6f0a0c231e90b208e8d14d697f"
EXPECTED_CONTEXT_VERIFY_SHA = "8ea6f99fdea646d42bcaa18022c03029159bca5665940126452ae6b206b35f89"
JOINT = ROOT / "jeju/research/20261010_joint_relationship_v1"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
RACE_PATH = JOINT / "outputs/report/race_metrics.csv"
RUNNER_PATH = JOINT / "outputs/report/runner_marginals.csv"
FEATURE_PATH = STYLE / "outputs/features.parquet"


def digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def distribution(series: pd.Series) -> dict:
    x = pd.to_numeric(series, errors="coerce")
    finite = x[np.isfinite(x)]
    return {
        "rows": int(len(x)),
        "nonmissing_finite": int(len(finite)),
        "missing_or_nonfinite": int(len(x) - len(finite)),
        "mean": float(finite.mean()) if len(finite) else None,
        "median": float(finite.median()) if len(finite) else None,
        "p25": float(finite.quantile(0.25)) if len(finite) else None,
        "p75": float(finite.quantile(0.75)) if len(finite) else None,
        "min": float(finite.min()) if len(finite) else None,
        "max": float(finite.max()) if len(finite) else None,
    }


def main() -> None:
    actual_hash = digest(CONTEXT_PATH)
    require(actual_hash == EXPECTED_CONTEXT_SHA, "supplemental runner_context.csv hash changed")
    manifest_hash = digest(CONTEXT_MANIFEST_PATH)
    require(manifest_hash == EXPECTED_CONTEXT_MANIFEST_SHA, "supplemental context manifest hash changed")
    verify_hash = digest(CONTEXT_VERIFY_PATH)
    require(verify_hash == EXPECTED_CONTEXT_VERIFY_SHA, "supplemental verify-only receipt hash changed")
    context_manifest = json.loads(CONTEXT_MANIFEST_PATH.read_text(encoding="utf-8"))
    artifact_hashes = {}
    for artifact in context_manifest["artifacts"]:
        artifact_path = CONTEXT_DIR / artifact["path"]
        actual_artifact_hash = digest(artifact_path)
        require(actual_artifact_hash == artifact["sha256"],
                f"supplemental context artifact hash mismatch: {artifact['path']}")
        artifact_hashes[artifact["path"]] = actual_artifact_hash
    verify_receipt = json.loads(CONTEXT_VERIFY_PATH.read_text(encoding="utf-8"))
    require(verify_receipt.get("mode") == "verify_only" and
            verify_receipt.get("byte_parity") is True and
            verify_receipt.get("semantic_parity") is True and
            verify_receipt.get("output_sha256") == actual_hash and
            verify_receipt.get("reconstructed_sha256") == actual_hash,
            "supplemental build verify-only receipt does not establish byte/semantic parity")
    context = pd.read_csv(CONTEXT_PATH, dtype={"race_id": "string", "jockey_id": "string"})
    races = pd.read_csv(RACE_PATH, dtype={"race_id": "string"})
    runners = pd.read_csv(RUNNER_PATH, dtype={"race_id": "string"})
    features = pd.read_parquet(FEATURE_PATH)
    require(len(context) == 17412 and context.api_record_id.is_unique,
            "context rows/api_record_id coverage invalid")
    require(len(races) == 1779 and races.race_id.is_unique, "race ledger key coverage invalid")
    require(len(runners) == 17412 and runners.api_record_id.is_unique,
            "runner labels key coverage invalid")
    require(context.api_record_id.notna().all(), "context api_record_id is missing")
    require(set(context.api_record_id) == set(runners.api_record_id),
            "context-to-runner API key coverage mismatch")

    eval_features = features.loc[features.race_id.isin(set(races.race_id))].copy()
    require(len(eval_features) == 17412 and eval_features.api_record_id.is_unique,
            "feature evaluation cohort coverage invalid")
    require(set(context.api_record_id) == set(eval_features.api_record_id),
            "context-to-feature API key coverage mismatch")
    context["race_id"] = context.race_id.astype("string")
    eval_features["race_id"] = eval_features.race_id.astype("string")
    runners["race_id"] = runners.race_id.astype("string")
    context_index = context.set_index("api_record_id")
    feature_index = eval_features.set_index("api_record_id")
    runner_index = runners.set_index("api_record_id")
    for column, context_column in (
        ("race_id", "race_id"),
        ("race_date", "race_date"),
        ("evaluation_year", "year"),
        ("horse_id", "horse_id"),
        ("horse_number", "horse_number"),
        ("race_distance_m", "distance_m"),
        ("rank_class_raw", "grade_raw"),
    ):
        left = context_index.loc[feature_index.index, column]
        right = feature_index[context_column]
        if column in {"race_date"}:
            left = pd.to_datetime(left, errors="raise").dt.normalize()
            right = pd.to_datetime(right, errors="raise").dt.normalize()
        elif column in {"race_distance_m", "evaluation_year", "horse_number", "horse_id"}:
            left = pd.to_numeric(left, errors="raise")
            right = pd.to_numeric(right, errors="raise")
        require(bool(left.reset_index(drop=True).equals(right.reset_index(drop=True))),
                f"context/feature exact-key parity mismatch: {column}")
    context_top3 = pd.to_numeric(runner_index.loc[context.api_record_id, "y_top3"], errors="raise")
    feature_top3 = pd.to_numeric(feature_index.loc[context.api_record_id, "finish_position"], errors="raise").le(3).astype(int)
    require(bool(context_top3.reset_index(drop=True).astype(int).equals(
        feature_top3.reset_index(drop=True))), "context keyed rows do not match actual label roster")

    race_constant_fields = ["race_date", "evaluation_year", "race_distance_m", "field_n",
                            "rank_class_raw", "month", "track_raw", "moisture", "band"]
    race_values = context.groupby("race_id", sort=True, observed=True)
    require(context.race_id.nunique() == 1779, "context race coverage differs from cohort")
    race_rows = race_values.size()
    require(int(race_rows.sum()) == 17412, "context runner rows changed during race grouping")
    for column in race_constant_fields:
        cardinality = race_values[column].nunique(dropna=False)
        require(bool(cardinality.eq(1).all()), f"race-constant context field varies within race: {column}")

    race = race_values.first().reset_index()
    race["moisture"] = pd.to_numeric(race.moisture, errors="coerce")
    moisture_counts = race.assign(
        moisture_class=race.moisture.map(lambda x: "__MISSING__" if pd.isna(x) else str(float(x)))
    ).groupby("moisture_class", dropna=False).size().to_dict()
    band_counts = race.band.fillna("__MISSING__").astype(str).value_counts(dropna=False).sort_index().to_dict()
    result = {
        "status": "PASS",
        "scope": "Read-only exact API-key join and race-unit support audit for separately authorized same-day result-side context.",
        "source_sha256": actual_hash,
        "context_manifest_sha256": manifest_hash,
        "context_verify_receipt_sha256": verify_hash,
        "context_artifact_hashes_verified": artifact_hashes,
        "cohort": {
            "context_runner_rows": len(context),
            "feature_runner_rows": len(eval_features),
            "label_runner_rows": len(runners),
            "unique_races": int(context.race_id.nunique()),
            "race_days": int(pd.to_datetime(context.race_date).nunique()),
            "exact_api_record_id_coverage": True,
            "race_id_date_horse_identity_distance_grade_parity": True,
            "actual_top3_roster_parity": True,
            "race_rows_are_not_expanded": True,
        },
        "field_units_and_support": {
            "race_constant_fields": race_constant_fields,
            "moisture_percent_race_count_full_1779": {str(k): int(v) for k, v in sorted(moisture_counts.items())},
            "band_race_count_full_1779": {str(k): int(v) for k, v in sorted(band_counts.items())},
            "moisture_band_missing_races": int(race["moisture"].isna().sum()),
            "body_kg_runner_distribution": distribution(context.body_kg),
            "carried_weight_kg_runner_distribution": distribution(context.carried_weight_kg),
            "body_kg_raw_source_field_retained": True,
            "reported_body_change_raw_retained_without_reinterpretation": True,
            "jockey_id_condition_summaries_created": False,
        },
        "interpretation": {
            "moisture_band_body_and_carried_weight": "same-day result-side post-race context; measurement/publication time is unverified and these fields are not admissible prediction-time inputs in this retrospective condition analysis",
            "horse_number": "runner number only; physical gate mapping is unverified",
            "body_weight_and_carried_weight_summary_unit": "source rows are runner-level; inferential comparison against race-level hit groups must aggregate to one race-level descriptor first or explicitly use a race-clustered runner summary",
        },
        "limitations": [
            "Exact api_record_id key coverage proves row linkage, not pre-race availability or a public timestamp.",
            "Moisture and band repeat at runner grain but are race-level conditions; analysis denominators must be unique race counts.",
            "No jockey-level rule, cutoff, or per-jockey hit table was computed.",
            "This receipt validates provenance keys and field support only, not condition associations or model effects.",
        ],
    }
    output = REVIEW / "outputs/supplemental_context_receipt.json"
    output.resolve().relative_to(REVIEW.resolve())
    temp = output.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    os.replace(temp, output)
    print(json.dumps({"status": result["status"], "output": str(output.relative_to(ROOT)),
                      "cohort": result["cohort"], "band": result["field_units_and_support"]["band_race_count_full_1779"],
                      "moisture": result["field_units_and_support"]["moisture_percent_race_count_full_1779"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

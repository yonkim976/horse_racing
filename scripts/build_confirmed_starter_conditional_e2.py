#!/usr/bin/env python3
"""Build the fixed-scope E2 confirmed-starter retrospective research dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import polars as pl
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from horse_racing.analysis.confirmed_starter_dataset import (
    END_DATE,
    START_DATE,
    build_confirmed_starter_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/horse_racing.sqlite3"
DEFAULT_EVIDENCE = ROOT / "data/logs/pre_race_field_dnf_evidence_e1_v2_20260911.parquet"
DEFAULT_REFERENCE = (
    ROOT / "data/datasets/section_canonical_seoul_v2_review/start_minus_30m/dataset.parquet"
)
DEFAULT_PREVIOUS_E2 = (
    ROOT / "data/datasets/confirmed_starter_conditional_e2_remediation_v2_retrospective/"
    "start_minus_30m/dataset.parquet"
)
DEFAULT_TARGET = (
    ROOT / "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m"
)
DEFAULT_LOG = ROOT / "data/logs/confirmed_starter_e2_h1_remediation_20260911.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--previous-e2", type=Path, default=DEFAULT_PREVIOUS_E2)
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--log-output", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()

    dataset_path = args.target_dir / "dataset.parquet"
    manifest_path = args.target_dir / "manifest.json"
    collisions = [path for path in (dataset_path, manifest_path, args.log_output) if path.exists()]
    if collisions:
        raise SystemExit(f"refusing to overwrite E2 artifacts: {collisions}")

    engine = create_engine(f"sqlite:///file:{args.db.resolve()}?mode=ro&uri=true")
    with Session(engine) as session:
        result = build_confirmed_starter_dataset(
            session,
            evidence_path=args.evidence,
            reference_dataset_path=args.reference,
            previous_e2_dataset_path=args.previous_e2,
        )
    engine.dispose()

    args.target_dir.mkdir(parents=True, exist_ok=False)
    result.frame.write_parquet(dataset_path)
    result.manifest["dataset"] = {
        "path": str(dataset_path.relative_to(ROOT)),
        "sha256": _sha256(dataset_path),
        "rows": result.frame.height,
        "columns": {name: str(dtype) for name, dtype in result.frame.schema.items()},
    }
    source_paths = [
        ROOT / "src/horse_racing/analysis/confirmed_starter_dataset.py",
        Path(__file__).resolve(),
        ROOT / "src/horse_racing/analysis/pre_race_field_contract.py",
        args.evidence,
        args.reference,
        args.previous_e2,
    ]
    result.manifest["source_sha256"] = {
        str(path.relative_to(ROOT)): _sha256(path) for path in source_paths
    }
    result.manifest["database"] = {
        "path": str(args.db.relative_to(ROOT)),
        "sha256": _sha256(args.db),
        "read_only": True,
        "actual_result_query_bound": {"start": START_DATE, "end": END_DATE},
    }
    manifest_path.write_text(
        json.dumps(result.manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    selected = result.manifest["selected_feature_names"]
    special = result.frame.filter(pl.col("outcome_state") != "normal_finish")
    traced = special.filter(pl.col("career_starts") > 0).row(0, named=True)
    actual_case = {
        "race_id": traced["race_id"],
        "race_entry_id": traced["race_entry_id"],
        "race_date_local": traced["race_date_local"],
        "outcome_state": traced["outcome_state"],
        "career_starts": traced["career_starts"],
        "selected_features_non_null": sum(traced[name] is not None for name in selected),
        "selected_features_total": len(selected),
        "auxiliary_rank_observed": traced["auxiliary_rank_observed"],
        "auxiliary_finish_time_observed": traced["auxiliary_finish_time_observed"],
    }
    split_states = {
        split: {state: count for state, count in subset.group_by("outcome_state").len().iter_rows()}
        for split, subset in {
            "train": result.frame.filter(pl.col("race_date_local") <= "2026-02-28"),
            "development_validation": result.frame.filter(
                pl.col("race_date_local") >= "2026-03-01"
            ),
        }.items()
    }
    audit = {
        "audit": "confirmed-starter conditional E2 retrospective dataset",
        "scope": result.manifest["scope"],
        "field_contract": {
            key: value
            for key, value in result.manifest["field_contract"].items()
            if key != "expected_keys"
        },
        "counts": result.manifest["counts"],
        "split_state_counts": split_states,
        "labels": {
            "dnf_and_disqualification_win_top2_top3": 0,
            "dnf_and_disqualification_rank_time_auxiliary": "masked",
            "missing_or_ambiguous": "never coerced to zero",
        },
        "feature_contract": {
            "feature_set": result.manifest["feature_set"],
            "model_profile": result.manifest["model_profile"],
            "selected_feature_count": len(selected),
            "selected_feature_hash": result.manifest["selected_feature_hash"],
            "selected_feature_null_rates": result.manifest["selected_feature_null_rates"],
            "history_policy": result.manifest["history_policy"],
            "field_feature_policy": result.manifest["field_feature_policy"],
        },
        "reference_normal_comparison": result.comparison,
        "independent_horse_jockey_validation": result.manifest[
            "independent_horse_jockey_validation"
        ],
        "previous_e2_comparison": result.manifest["previous_e2_comparison"],
        "actual_dnf_or_disqualification_case": actual_case,
        "artifacts": {
            "dataset": {
                "path": str(dataset_path.relative_to(ROOT)),
                "sha256": _sha256(dataset_path),
            },
            "manifest": {"path": str(manifest_path.relative_to(ROOT))},
        },
        "source_sha256": result.manifest["source_sha256"],
        "database": result.manifest["database"],
        "training_performed": False,
        "evaluation_performed": False,
        "production_paths_changed": False,
    }
    args.log_output.parent.mkdir(parents=True, exist_ok=True)
    args.log_output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(dataset_path)
    print(manifest_path)
    print(args.log_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

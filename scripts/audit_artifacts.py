#!/usr/bin/env python3
"""Audit links between experiment records, datasets, models, and reports."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

UUID_PATTERN = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


def _directory_count(path: Path) -> int:
    return sum(1 for item in path.iterdir() if item.is_dir()) if path.exists() else 0


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def audit(root: Path) -> dict[str, object]:
    registry_path = root / "data/experiments/model_runs.jsonl"
    models_dir = root / "data/experiments/models"
    reports_dir = root / "data/experiments/reports"
    datasets_dir = root / "data/datasets"

    parse_errors: list[dict[str, object]] = []
    runs: list[dict[str, object]] = []
    for line_number, line in enumerate(registry_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError as exc:
            parse_errors.append({"line": line_number, "error": str(exc)})

    run_ids = [str(run.get("run_id", "")) for run in runs]
    duplicate_run_ids = sorted(
        run_id for run_id, count in Counter(run_ids).items() if run_id and count > 1
    )
    registered_ids = set(run_ids)

    artifact_refs: dict[str, Path] = {}
    missing_artifacts: list[dict[str, str]] = []
    missing_dataset_manifests: list[dict[str, str]] = []
    for run in runs:
        run_id = str(run.get("run_id", ""))
        hyperparameters = run.get("hyperparameters") or {}
        artifact = hyperparameters.get("artifact_path")
        if artifact:
            path = root / str(artifact)
            artifact_refs[run_id] = path
            if not path.exists():
                missing_artifacts.append({"run_id": run_id, "path": str(artifact)})

        dataset_version = str(run.get("dataset_version", ""))
        if "/" in dataset_version:
            version, as_of_policy = dataset_version.split("/", 1)
            manifest = datasets_dir / version / as_of_policy / "manifest.json"
            if not manifest.exists():
                missing_dataset_manifests.append(
                    {"run_id": run_id, "dataset_version": dataset_version}
                )

    model_dirs = {path.name for path in models_dir.iterdir() if path.is_dir()}
    reports = [path for path in reports_dir.iterdir() if path.is_file()]
    report_ids = {
        match.group(1)
        for path in reports
        if (match := UUID_PATTERN.search(path.name)) is not None
    }
    zero_byte_files = [
        str(path.relative_to(root))
        for base in (root / "docs", root / "data/datasets", root / "data/experiments")
        if base.exists()
        for path in base.rglob("*")
        if path.is_file() and path.stat().st_size == 0
    ]

    critical = {
        "registry_parse_errors": parse_errors,
        "duplicate_run_ids": duplicate_run_ids,
        "missing_artifacts": missing_artifacts,
        "missing_dataset_manifests": missing_dataset_manifests,
        "unregistered_model_directories": sorted(model_dirs - registered_ids),
        "unregistered_report_run_ids": sorted(report_ids - registered_ids),
        "zero_byte_files": zero_byte_files,
    }
    return {
        "status": "PASS" if not any(critical.values()) else "FAIL",
        "counts": {
            "registered_runs": len(runs),
            "artifact_references": len(artifact_refs),
            "model_directories": len(model_dirs),
            "dataset_manifests": len(list(datasets_dir.glob("*/*/manifest.json"))),
            "report_files": len(reports),
            "report_run_ids": len(report_ids),
            "walk_forward_directories": _directory_count(root / "data/experiments/walk_forward"),
            "calibration_directories": _directory_count(root / "data/experiments/calibration"),
            "race_value_directories": _directory_count(root / "data/experiments/race_value_v1"),
            "race_portfolio_directories": _directory_count(
                root / "data/experiments/race_portfolio_v1"
            ),
            "archive_manifests": len(list((root / "data/archives").glob("*/manifest.json"))),
        },
        "sizes_bytes": {
            "database": _tree_size(root / "data/horse_racing.sqlite3"),
            "raw": _tree_size(root / "data/raw"),
            "datasets": _tree_size(datasets_dir),
            "experiments": _tree_size(root / "data/experiments"),
            "predictions": _tree_size(root / "data/predictions"),
            "archives": _tree_size(root / "data/archives"),
        },
        "model_types": dict(Counter(str(run.get("model_type", "")) for run in runs)),
        "critical_issues": critical,
        "warnings": {
            "registered_runs_without_uuid_named_report": sorted(registered_ids - report_ids),
            "note": (
                "기준선 4개와 ablation 2개는 UUID가 파일명에 없는 공용 보고서를 사용한다."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

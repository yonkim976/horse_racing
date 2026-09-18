"""Refresh validation and write a complete hash manifest for a built dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from build_unified_thoroughbred_dataset import (
    BUSAN_DB,
    OPERATING_DB,
    SEOUL_DB,
    SEOUL_TRIAL_DB,
    ROOT,
    validate,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict:
    return {"bytes": path.stat().st_size, "sha256": sha256(path)}


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    database = out / "thoroughbred_unified.duckdb"
    validation_path = out / "validation.json"

    previous = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else {}
    db = duckdb.connect(str(database), read_only=True)
    try:
        validation = validate(db)
    finally:
        db.close()
    validation.update({
        "built_at_utc": previous.get("built_at_utc"),
        "finalized_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_counts": previous.get("source_counts", {}),
        "database": relative(database),
        "database_sha256": sha256(database),
        "existing_databases_modified": False,
        "independent_validation": relative(out / "independent_validation.json"),
    })
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    supporting_sources = [
        SEOUL_DB,
        SEOUL_TRIAL_DB,
        BUSAN_DB,
        OPERATING_DB,
        SEOUL_DB.parent / "sha256_manifest.csv",
        SEOUL_DB.parent / "validation.json",
        SEOUL_TRIAL_DB.parent / "sha256_manifest.csv",
        SEOUL_TRIAL_DB.parent / "validation.json",
        BUSAN_DB.parent / "manifest.json",
    ]
    code_and_report = [
        ROOT / "scripts/build_unified_thoroughbred_dataset.py",
        ROOT / "scripts/verify_unified_thoroughbred_dataset.py",
        ROOT / "scripts/finalize_unified_thoroughbred_dataset.py",
        ROOT / "docs/THOROUGHBRED_UNIFIED_DATASET_2026-09-18.md",
    ]
    artifacts = [
        path for path in out.rglob("*")
        if path.is_file() and path.name != "manifest.json" and "tmp" not in path.parts
    ] + [path for path in code_and_report if path.exists()]
    sources = [path for path in supporting_sources if path.exists()]
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_version": "2026-09-18",
        "artifacts": {relative(path): record(path) for path in sorted(artifacts)},
        "read_only_sources": {relative(path): record(path) for path in sources},
        "notes": [
            "The manifest intentionally excludes itself because a file cannot contain its own stable hash.",
            "Source SQLite databases were opened read-only; source-specific manifests trace their raw inputs.",
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"artifacts": len(artifacts), "sources": len(sources),
                      "database_sha256": validation["database_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

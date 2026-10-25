"""Create a fresh, byte-identical pre-update snapshot of central conclusions.

Read/copy only. It does not update any central conclusion or manifest.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[3]
REVIEW = ROOT / "jeju/research/20261010_joint_gain_loss_review_v1"
CENTRAL = ROOT / "jeju/research/conclusions"
TARGET = REVIEW / "outputs/central_snapshot_prepublication_gain_loss_20261010"
FILES = (
    "README.md",
    "SOURCES.md",
    "research_register.json",
    "source_manifest.json",
    "19_JOINT_RELATIONSHIP.md",
)
PROTECTED_TOPIC18 = CENTRAL / "18_PROBABILITY_COMBO_GAP.md"


def confined(path: Path, *, exists: bool = True) -> Path:
    resolved = path.resolve(strict=exists)
    resolved.relative_to(ROOT)
    return resolved


def digest(path: Path) -> str:
    path = confined(path)
    value = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main() -> int:
    if TARGET.exists():
        raise FileExistsError(f"refusing to replace existing snapshot: {TARGET}")
    TARGET.mkdir(mode=0o700, parents=False, exist_ok=False)
    copied = []
    for name in FILES:
        source = confined(CENTRAL / name)
        before_hash, before_bytes = digest(source), source.stat().st_size
        destination = confined(TARGET / name, exists=False)
        shutil.copyfile(source, destination)
        copied_hash, copied_bytes = digest(destination), destination.stat().st_size
        after_hash = digest(source)
        if (before_hash != copied_hash or before_hash != after_hash or
                before_bytes != copied_bytes):
            raise AssertionError(f"snapshot copy changed or source moved during copy: {name}")
        copied.append({
            "central_path": source.relative_to(ROOT).as_posix(),
            "snapshot_path": destination.relative_to(ROOT).as_posix(),
            "sha256": copied_hash,
            "bytes": copied_bytes,
            "byte_identical": True,
            "source_unchanged_during_copy": True,
        })

    source_manifest = json.loads((TARGET / "source_manifest.json").read_text(encoding="utf-8"))
    register = json.loads((TARGET / "research_register.json").read_text(encoding="utf-8"))
    central_rows = {row["path"]: row for row in source_manifest.get("files", [])
                    if row.get("path") in {item["central_path"] for item in copied}}
    for item in copied:
        central_path = item["central_path"]
        if central_path == "jeju/research/conclusions/source_manifest.json":
            continue
        row = central_rows.get(central_path)
        if row is None or row.get("sha256") != item["sha256"] or row.get("bytes") != item["bytes"]:
            raise AssertionError(f"pre-update central row does not match source manifest: {central_path}")
    topic19 = next(row for row in register.get("topics", []) if row.get("id") == "joint_relationship")
    if (topic19.get("status") != "retrospective_joint_relationship_gate_failed_no_operational_change" or
            topic19.get("primary_gate", {}).get("gate_passed") is not False or
            topic19.get("operationally_applied") is not False):
        raise AssertionError("existing topic 19 no longer preserves the failed research gate")
    manifest_state = {
        "source_manifest_sha256": digest(TARGET / "source_manifest.json"),
        "source_manifest_entries": len(source_manifest.get("files", [])),
        "source_manifest_has_topic19": "jeju/research/conclusions/19_JOINT_RELATIONSHIP.md" in central_rows,
        "topic19_register_record_count": sum(
            1 for row in register.get("topics", []) if row.get("id") == "joint_relationship"),
        "register_topic_count": len(register.get("topics", [])),
        "topic19_baseline_status": next(
            row.get("status") for row in register.get("topics", [])
            if row.get("id") == "joint_relationship"),
        "central_rows_in_source_manifest": central_rows,
        "protected_topic18_current_sha256": digest(PROTECTED_TOPIC18),
        "topic19_primary_gate_passed": topic19.get("primary_gate", {}).get("gate_passed"),
        "topic19_operationally_applied": topic19.get("operationally_applied"),
    }
    receipt = {
        "status": "PASS",
        "mode": "fresh pre-update central snapshot; read/copy only",
        "snapshot_directory": TARGET.relative_to(ROOT).as_posix(),
        "central_files_modified": False,
        "file_count": len(copied),
        "files": copied,
        "source_manifest_state": manifest_state,
        "note": "No database query or publication write was performed.",
    }
    receipt_path = TARGET / "snapshot_receipt.json"
    with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

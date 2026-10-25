"""Copy the current central index files into this C review folder, read-only."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CENTRAL = ROOT / "jeju/research/conclusions"
TARGET = HERE / "outputs/central_snapshot_prepublication_20261010"
FILES = (
    "README.md",
    "SOURCES.md",
    "research_register.json",
    "source_manifest.json",
    "18_PROBABILITY_COMBO_GAP.md",
)


def confined(path: Path, *, strict: bool = True) -> Path:
    resolved = path.resolve(strict=strict)
    resolved.relative_to(ROOT)
    return resolved


def digest(path: Path) -> str:
    path = confined(path)
    value = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def save_json_new(path: Path, value: dict) -> None:
    path = confined(path, strict=False)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        import os
        os.fsync(stream.fileno())


def audit_manifest_rows(manifest: dict) -> dict:
    rows = []
    entries = manifest.get("files", [])
    for index, entry in enumerate(entries, start=1):
        relative = str(entry.get("path", ""))
        if not relative:
            rows.append({"path": relative, "status": "invalid_empty_path"})
            continue
        source = confined(ROOT / relative, strict=False)
        if not source.is_file():
            rows.append({"path": relative, "status": "missing", "expected_sha256": entry.get("sha256"),
                         "expected_bytes": entry.get("bytes")})
            continue
        actual_bytes = source.stat().st_size
        actual_sha = digest(source)
        matches_sha = actual_sha == entry.get("sha256")
        matches_bytes = actual_bytes == entry.get("bytes")
        rows.append({"path": relative,
                     "status": "match" if matches_sha and matches_bytes else "preexisting_mismatch",
                     "expected_sha256": entry.get("sha256"), "actual_sha256": actual_sha,
                     "expected_bytes": entry.get("bytes"), "actual_bytes": actual_bytes,
                     "sha256_match": matches_sha, "bytes_match": matches_bytes})
        if index % 100 == 0:
            print(f"read-only source manifest audit: {index}/{len(entries)} rows", flush=True)
    mismatches = [row for row in rows if row["status"] != "match"]
    return {"manifest_path": "jeju/research/conclusions/source_manifest.json",
            "manifest_entry_count": len(rows),
            "matched_count": len(rows) - len(mismatches),
            "preexisting_mismatch_count": len(mismatches),
            "preexisting_mismatches": mismatches,
            "all_rows": rows,
            "scope": "read-only audit of the current pre-update source manifest; does not repair old rows"}


def main() -> None:
    if TARGET.exists():
        raise FileExistsError(f"refusing to replace an existing prepublication snapshot: {TARGET}")
    TARGET.mkdir(parents=True, exist_ok=False)
    records = []
    for name in FILES:
        source = confined(CENTRAL / name)
        before_sha = digest(source)
        before_bytes = source.stat().st_size
        destination = confined(TARGET / name, strict=False)
        shutil.copyfile(source, destination)
        copied_sha = digest(destination)
        copied_bytes = destination.stat().st_size
        after_sha = digest(source)
        if before_sha != copied_sha or before_sha != after_sha or before_bytes != copied_bytes:
            raise AssertionError(f"prepublication copy mismatch or source changed during snapshot: {name}")
        records.append({"source_path": source.relative_to(ROOT).as_posix(),
                        "snapshot_path": destination.relative_to(ROOT).as_posix(),
                        "sha256": copied_sha, "bytes": copied_bytes,
                        "copy_byte_identical": True, "source_unchanged_during_copy": True})

    saved_manifest_path = TARGET / "source_manifest.json"
    saved_manifest = json.loads(saved_manifest_path.read_text(encoding="utf-8"))
    audit = audit_manifest_rows(saved_manifest)
    save_json_new(TARGET / "source_manifest_prepublication_audit.json", audit)
    receipt = {
        "passed": True,
        "mode": "fresh pre-update central snapshot; read/copy only",
        "snapshot_directory": TARGET.relative_to(ROOT).as_posix(),
        "central_files_modified": False,
        "file_count": len(records),
        "files": records,
        "source_manifest_prepublication_audit": {
            "manifest_snapshot_sha256": digest(saved_manifest_path),
            "entry_count": audit["manifest_entry_count"],
            "matched_count": audit["matched_count"],
            "preexisting_mismatch_count": audit["preexisting_mismatch_count"],
            "audit_path": (TARGET / "source_manifest_prepublication_audit.json").relative_to(ROOT).as_posix(),
        },
    }
    save_json_new(TARGET / "central_snapshot_receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

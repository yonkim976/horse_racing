"""Verify the currently imported joint-model helper against its source manifest."""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = ROOT / "jeju/research/20261010_joint_relationship_v1"
MANIFEST = STUDY / "ARTIFACT_MANIFEST.json"
OUT = HERE / "HELPER_INTEGRITY_AUDIT.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    manifest_hash = sha256(MANIFEST)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = manifest["files"]["joint_model.py"]
    sys.path.insert(0, str(STUDY))
    jm = importlib.import_module("joint_model")
    imported = Path(jm.__file__).resolve(strict=True)
    expected_path = (STUDY / "joint_model.py").resolve(strict=True)
    if imported != expected_path:
        raise AssertionError(f"unexpected imported helper: {imported}")
    actual_hash = sha256(imported)
    actual_bytes = imported.stat().st_size
    if actual_hash != expected["sha256"] or actual_bytes != expected["bytes"]:
        raise AssertionError("imported helper differs from the manifest entry")
    if OUT.exists():
        raise FileExistsError(OUT)
    payload = {
        "audit_status": "post-run current-state integrity check",
        "audit_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_manifest": str(MANIFEST.relative_to(ROOT)),
        "source_manifest_sha256": manifest_hash,
        "manifest_helper_entry": expected,
        "imported_module": "joint_model",
        "imported_file": str(imported.relative_to(ROOT)),
        "imported_file_sha256": actual_hash,
        "imported_file_bytes": actual_bytes,
        "matches_manifest": True,
        "scope_note": (
            "This verifies the helper file currently imported by this audit against the "
            "authoritative manifest. It does not establish that the same check was run "
            "at the original core-analysis timestamp. The core analysis separately "
            "reconstructed and matched all saved triple energies. No fitting routine ran."
        ),
    }
    with OUT.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

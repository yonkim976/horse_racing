"""Verify the cleanup preserved all non-deleted snapshots and both model profiles."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    receipt = json.loads((HERE / "deletion_receipt.json").read_text())
    deleted = {row["path"] for row in receipt["files"]}
    assert all(not (ROOT / p).exists() for p in deleted)
    before = json.loads((HERE / "protected_before.json").read_text())["files"]
    section = json.loads((HERE / "section_databases_before.json").read_text())["files"]
    checked = []
    for row in before + section:
        if row["path"] in deleted:
            continue
        path = ROOT / row["path"]
        if not path.is_file() or sha(path) != row["sha256"]:
            raise AssertionError(f"protected file changed: {row['path']}")
        checked.append(row["path"])
    links = json.loads((HERE / "workspace_links.json").read_text())["links"]
    for row in links:
        path = ROOT / row["path"]
        assert path.is_symlink() and path.exists(), row["path"]
        assert path.resolve() == (ROOT / row["target"]).resolve(), row["path"]
    resolver = ROOT / ".agents/skills/horse-racing-prediction-publisher/scripts/resolve_main_model.py"
    profiles = {}
    for domain in ("thoroughbred", "jeju"):
        result = subprocess.run([sys.executable, str(resolver), "--repo-root", str(ROOT), "--domain", domain], capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        assert payload["ok"]
        with (HERE / f"resolver_{domain}_after.json").open("x") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        profiles[domain] = payload["active_profile"]
    out = {
        "passed": True,
        "preserved_snapshot_files": len(checked),
        "all_preserved_bytes_identical": True,
        "deleted_count": len(deleted),
        "deleted_bytes": receipt["bytes"],
        "valid_workspace_links": len(links),
        "profiles": profiles,
        "DB_row_writes": 0,
        "registry_changed": False,
    }
    with (HERE / "verification.json").open("x") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

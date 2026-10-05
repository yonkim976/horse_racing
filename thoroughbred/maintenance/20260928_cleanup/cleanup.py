"""Execute only the reviewed, hash-pinned cleanup; never discover extra deletions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD_DATABASES = {
    "data/research/section_point_db_20260925/section_points_ext.sqlite3",
    "data/research/section_point_db_20260925/section_points_repaired.sqlite3",
}


def sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def dump(name: str, value: object) -> None:
    with (HERE / name).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def allowed(relative: str) -> bool:
    p = Path(relative)
    if relative in OLD_DATABASES:
        return True
    return (
        p.parts[:2] == ("data", "research")
        and len(p.parts) > 3
        and p.parts[2].startswith("thoroughbred_")
        and (p.name == ".DS_Store" or (p.suffix == ".pyc" and "__pycache__" in p.parts))
    )


def plan() -> None:
    # The original base DB remains protected: its raw-key equivalence is unproven.
    # DB candidates must have a separate, completed comparison/review before apply.
    section = json.loads((HERE / "section_databases_before.json").read_text())["files"]
    before = json.loads((HERE / "protected_before.json").read_text())["files"]
    candidates = [r for r in section if r["path"] in OLD_DATABASES]
    candidates += [r for r in before if allowed(r["path"])]
    for row in candidates:
        row["reason"] = (
            "superseded section DB; explicitly forbidden for use; reviewed against retained source DBs"
            if row["path"] in OLD_DATABASES
            else "regenerable Python bytecode or Finder metadata"
        )
    dump("deletion_plan.json", {"files": candidates, "count": len(candidates), "bytes": sum(r["bytes"] for r in candidates)})


def apply() -> None:
    if (HERE / "deletion_receipt.json").exists():
        raise FileExistsError("cleanup has already been executed")
    review = json.loads((HERE / "review_decision.json").read_text())
    if review.get("approved_paths") != sorted(OLD_DATABASES) or not review.get("passed"):
        raise ValueError("completed independent review is required")
    rows = json.loads((HERE / "deletion_plan.json").read_text())["files"]
    section = json.loads((HERE / "section_databases_before.json").read_text())["files"]
    for row in section:
        p = ROOT / row["path"]
        if sha(p) != row["sha256"]:
            raise ValueError(f"section database changed since review: {row['path']}")
    paths = []
    for row in rows:
        p = ROOT / row["path"]
        if not allowed(row["path"]) or p.is_symlink() or p.resolve() != p.absolute():
            raise ValueError(f"unsafe path: {p}")
        if p.stat().st_size != row["bytes"] or sha(p) != row["sha256"]:
            raise ValueError(f"candidate changed since review: {p}")
        paths.append(p)
    opened = subprocess.run(["lsof", "-nP", *map(str, paths)], capture_output=True, text=True)
    if opened.returncode != 1 or opened.stdout.strip() or opened.stderr.strip():
        raise RuntimeError("file handles exist or open-file check failed; no deletion performed")
    # All preconditions are checked before the first unlink. Append each deletion
    # immediately so an interrupted run retains an exact partial receipt.
    with (HERE / "deletion_events.jsonl").open("x") as handle:
        for row, p in zip(rows, paths):
            handle.write(json.dumps({"event": "intent", **row}, ensure_ascii=False) + "\n")
            handle.flush()
            p.unlink()
            handle.write(json.dumps({"event": "deleted", **row}, ensure_ascii=False) + "\n")
            handle.flush()
    dump("deletion_receipt.json", {"files": rows, "count": len(rows), "bytes": sum(r["bytes"] for r in rows), "database_rows_modified": 0})
    print(json.dumps({"deleted_files": len(rows), "deleted_bytes": sum(r["bytes"] for r in rows)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["plan", "apply"])
    arguments = parser.parse_args()
    {"plan": plan, "apply": apply}[arguments.mode]()

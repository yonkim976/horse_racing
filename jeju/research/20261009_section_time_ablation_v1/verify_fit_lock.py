"""Verify locked inputs and protected files immediately before/after a fit."""
import argparse
import sys

sys.dont_write_bytecode = True

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
LOCK = OUT / "prefit_lock.json"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("before_fit", "after_fit"))
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    mismatches = []
    for relative, info in lock["scoped_reference_sha256"].items():
        path = ROOT / relative
        observed = {"bytes": path.stat().st_size, "sha256": sha256(path)} if path.is_file() else None
        if observed != info:
            mismatches.append({"path": relative, "expected": info, "observed": observed})
    protected_ok = {}
    for relative, info in lock["protected_live_state_sha256"].items():
        path = ROOT / relative
        observed = {"bytes": path.stat().st_size, "sha256": sha256(path)} if path.is_file() else None
        protected_ok[relative] = observed == info
        if observed != info:
            mismatches.append({"path": relative, "expected": info, "observed": observed})
    receipt = {
        "phase": args.phase,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checked_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "passed": not mismatches,
        "scoped_reference_count": len(lock["scoped_reference_sha256"]),
        "protected_live_state_unchanged": protected_ok,
        "mismatches": mismatches,
    }
    output_path = OUT / f"{args.phase}_integrity_check.json"
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)
    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

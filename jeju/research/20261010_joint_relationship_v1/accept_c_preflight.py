"""Copy the fixed-path independent C preflight receipt without alteration."""
from __future__ import annotations

import hashlib
import json
import os

import joint_model as jm


SOURCE = jm.C_FINAL_RECEIPT_PATH
DESTINATION = jm.OUT / "independent_preflight_receipt.json"


def raw_sha256(path) -> str:
    digest = hashlib.sha256()
    with jm.confined(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if DESTINATION.exists():
        raise FileExistsError("C preflight receipt copy already exists; refusing overwrite")
    payload = jm.load_json(SOURCE)
    expected_source_lock_sha = jm.sha256(jm.OUT / "source_lock.json")
    expected_preflight_sha = jm.sha256(jm.OUT / "preflight_receipt.json")
    if (payload.get("passed") is not True or
            payload.get("plan_sha256") != jm.EXPECTED_PLAN_SHA256 or
            payload.get("source_lock_sha256") != expected_source_lock_sha or
            payload.get("preflight_receipt_sha256") != expected_preflight_sha):
        raise AssertionError("C final preflight receipt does not match this A preflight/source lock")
    source_hash = raw_sha256(SOURCE)
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(DESTINATION, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output, jm.confined(SOURCE).open("rb") as input_stream:
            for block in iter(lambda: input_stream.read(1024 * 1024), b""):
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        raise
    copied_hash = raw_sha256(DESTINATION)
    if source_hash != copied_hash:
        raise AssertionError("byte-for-byte C receipt copy hash mismatch")
    result = {
        "passed": True,
        "mode": "fixed-path byte-for-byte C receipt acceptance",
        "c_source_path": str(SOURCE.relative_to(jm.ROOT)),
        "c_sha256": source_hash,
        "a_copy_path": str(DESTINATION.relative_to(jm.ROOT)),
        "a_copy_sha256": copied_hash,
        "plan_sha256": jm.EXPECTED_PLAN_SHA256,
        "source_lock_sha256": expected_source_lock_sha,
        "preflight_receipt_sha256": expected_preflight_sha,
    }
    receipt_path = jm.OUT / "c_preflight_acceptance.json"
    jm.write_json_new(receipt_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

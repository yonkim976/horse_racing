"""Recheck archived KRA Text files against their append-only download manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from horse_racing.config import get_settings

FINAL_STATUSES = {
    "downloaded",
    "skipped_existing",
    "skipped_duplicate_sha256",
    "verified_empty_source",
}


def audit(file_type: str, expected: dict[int, int]) -> dict:
    root = get_settings().raw_data_dir / "kra_text"
    manifest_path = root / "_manifests" / file_type / "manifest.jsonl"
    discovered: dict[int, set[str]] = defaultdict(set)
    final: dict[int, dict[str, dict]] = defaultdict(dict)
    failed: dict[int, set[str]] = defaultdict(set)
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(raw_line)
        meet = int(event["meet"])
        remote_path = event["remote_path"]
        if event["status"] == "discovered":
            discovered[meet].add(remote_path)
        elif event["status"] in FINAL_STATUSES:
            final[meet][remote_path] = event
        elif event["status"] == "failed":
            failed[meet].add(remote_path)

    result: dict[str, dict] = {}
    for meet in (1, 2, 3):
        entries = final[meet]
        if discovered[meet] != entries.keys():
            raise ValueError(f"Unfinished files: {file_type} meet={meet}")
        if failed[meet] - entries.keys():
            raise ValueError(f"Unrecovered source failures: {file_type} meet={meet}")
        if meet in expected and len(entries) != expected[meet]:
            raise ValueError(
                f"Unexpected file count: {file_type} meet={meet} "
                f"actual={len(entries)} expected={expected[meet]}"
            )
        statuses: Counter[str] = Counter()
        dates: list[str] = []
        bytes_total = 0
        html_bodies = 0
        empty_bodies = 0
        for event in entries.values():
            path = Path(event["local_path"])
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != event["sha256"]:
                raise ValueError(f"Missing or changed file: {path}")
            if not body:
                if event["status"] != "verified_empty_source":
                    raise ValueError(f"Unexpected empty file: {path}")
                empty_bodies += 1
            if body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                html_bodies += 1
            statuses[event["status"]] += 1
            bytes_total += int(event["response_bytes"])
            if event["file_date"]:
                dates.append(event["file_date"])
        result[str(meet)] = {
            "source_entries": len(entries),
            "statuses": dict(statuses),
            "first_file_date": min(dates) if dates else None,
            "last_file_date": max(dates) if dates else None,
            "response_bytes_sum": bytes_total,
            "html_payloads": html_bodies,
            "empty_payloads": empty_bodies,
            "recovered_failures": len(failed[meet]),
        }
        if html_bodies:
            raise ValueError(f"HTML payloads in {file_type} meet={meet}: {html_bodies}")
    return {"file_type": file_type, "manifest": str(manifest_path), "meets": result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-type", required=True)
    parser.add_argument("--expected", nargs="*", default=[], help="MEET:COUNT")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = {int(meet): int(count) for meet, count in (x.split(":") for x in args.expected)}
    result = audit(args.file_type, expected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({meet: x["source_entries"] for meet, x in result["meets"].items()}))


if __name__ == "__main__":
    main()

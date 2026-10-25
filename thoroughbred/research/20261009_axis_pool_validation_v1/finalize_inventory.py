"""Resolve a one-byte self-inventory cycle; analytical outputs remain immutable."""

import json

import run as e


def main():
    inventory = e.OUT / "artifact_inventory.json"
    before = json.loads((e.OUT / "publication_before.json").read_text())
    target = e.R / "conclusions/30_AXIS_POOL_VALIDATION.md"
    size_log = e.R / "ARTIFACT_SIZE_LOG.md"
    marker = "<!-- axis_pool_validation_v1_20261009 -->"
    # Retain every unrelated size-log entry, including concurrent additions.
    log_before = (
        "".join(
            line for line in size_log.read_text().splitlines(keepends=True) if marker not in line
        ).rstrip()
        + "\n"
    )
    previous = None
    for _ in range(30):
        files = sorted(
            [p for p in e.HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
            + [target]
        )
        rows = [
            dict(
                path=str(p.relative_to(e.ROOT)),
                bytes=p.stat().st_size,
                sha256=None if p == inventory else e.sha(p),
            )
            for p in files
        ]
        total = sum(r["bytes"] for r in rows)
        size_log.write_text(
            log_before
            + f"\n| 2026-10-09 | 더러브랫 축 고정 후보 범위 추가 검증 | {len(rows)} "
            + f"| {total} | {total / 1048576:.6f} | {len(before)} | 명세 참조 "
            + f"| 명세 참조 | [명세]({e.HERE.name}/outputs/artifact_inventory.json) | {marker}\n"
        )
        modified = [
            dict(
                path=key,
                before_bytes=old["bytes"],
                bytes=(e.ROOT / key).stat().st_size,
                delta_bytes=(e.ROOT / key).stat().st_size - old["bytes"],
                sha256=e.sha(e.ROOT / key),
            )
            for key, old in before.items()
        ]
        data = dict(
            new_file_count=len(rows),
            new_bytes=total,
            new_mib=round(total / 1048576, 6),
            modified_file_count=len(modified),
            modified_delta_bytes=sum(r["delta_bytes"] for r in modified),
            new_files=rows,
            modified_files=modified,
            inventory_self_hash_omitted=True,
            inventory_precision="MiB rounded to6 decimals to avoid a float-format size cycle",
        )
        inventory.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        signature = (total, inventory.stat().st_size)
        if signature == previous:
            break
        previous = signature
    else:
        raise AssertionError("Inventory did not converge")
    done = json.loads(inventory.read_text())
    for r in done["new_files"] + done["modified_files"]:
        p = e.ROOT / r["path"]
        assert p.stat().st_size == r["bytes"]
        if r["sha256"] is not None:
            assert e.sha(p) == r["sha256"]
    assert sum(r["bytes"] for r in done["new_files"]) == done["new_bytes"]
    e.check()
    print("Inventory verified", done["new_file_count"], done["new_bytes"], done["new_mib"])


if __name__ == "__main__":
    main()

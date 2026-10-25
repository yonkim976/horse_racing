"""Account for retained files, including this manifest's fixed-point size."""

# ruff: noqa: E501

import json

import run as e


def main():
    inventory = e.OUT / "artifact_inventory.json"
    before = json.loads((e.OUT / "publication_before.json").read_text())
    target = e.R / "conclusions/35_FAILURE_CLUSTERS.md"
    size_log = e.R / "ARTIFACT_SIZE_LOG.md"
    marker = "<!-- failure_clusters_v1_20261009 -->"
    original = (
        "".join(
            line for line in size_log.read_text().splitlines(keepends=True) if marker not in line
        ).rstrip()
        + "\n"
    )
    previous = None
    inventory.touch(exist_ok=True)
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
            original
            + f"\n| 2026-10-09 | 더러브랫 실패 경주와 후순위 입상 조건 군집 | {len(rows)} | {total} | {total / 1048576:.6f} | {len(before)} | 명세 참조 | 명세 참조 | [명세]({e.HERE.name}/outputs/artifact_inventory.json) | {marker}\n"
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
        e.save(
            inventory,
            dict(
                new_file_count=len(rows),
                new_bytes=total,
                new_mib=round(total / 1048576, 6),
                modified_file_count=len(modified),
                modified_delta_bytes=sum(r["delta_bytes"] for r in modified),
                new_files=rows,
                modified_files=modified,
                inventory_self_hash_omitted=True,
            ),
        )
        signature = (total, inventory.stat().st_size)
        if signature == previous:
            break
        previous = signature
    else:
        raise AssertionError("inventory size did not converge")
    done = json.loads(inventory.read_text())
    for r in done["new_files"] + done["modified_files"]:
        assert (e.ROOT / r["path"]).stat().st_size == r["bytes"]
        assert r["sha256"] is None or e.sha(e.ROOT / r["path"]) == r["sha256"]
    assert sum(r["bytes"] for r in done["new_files"]) == done["new_bytes"]
    e.check()
    print("Inventory verified", done["new_file_count"], done["new_bytes"], done["new_mib"])


if __name__ == "__main__":
    main()

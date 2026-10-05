"""Record all deliverables from this task, including the inventory and size log themselves."""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASELINE = Path("/tmp/horse1400_benchmark_baseline_20261005.json")
MANIFEST = HERE / "outputs/artifact_inventory.json"
LOG = HERE.parent / "ARTIFACT_SIZE_LOG.md"
RUN = "20261005_1400_benchmarks"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def task_paths():
    paths = set(HERE.rglob("*")) | set((HERE.parent / "conclusions").glob("*"))
    paths |= {
        HERE.parent / "SESSION_ARTIFACT_POLICY.md",
        HERE.parent / "RESEARCH_PUBLICATION_POLICY.md",
        HERE.parent / "20261004_website_research_review/README.md",
        HERE.parent / "DISTANCE_RECORD_BENCHMARK_POLICY.md",
        LOG,
        MANIFEST,
        HERE.parent / "README.md",
        ROOT / "thoroughbred/README.md",
    }
    return sorted(p for p in paths if p.is_file() and not p.is_symlink())


def collect(baseline):
    files = []
    for path in task_paths():
        assert path.resolve().is_relative_to(ROOT)
        name = str(path.relative_to(ROOT))
        stat = path.stat()
        old = baseline.get(name)
        if old and old["size"] == stat.st_size and old["mtime_ns"] == stat.st_mtime_ns:
            continue
        status = "modified" if old else "new"
        files.append(
            dict(
                path=name,
                status=status,
                bytes=stat.st_size,
                prior_bytes=old["size"] if old else 0,
                delta_bytes=stat.st_size - (old["size"] if old else 0),
                sha256=None if path == MANIFEST else sha(path),
            )
        )
    new = [f for f in files if f["status"] == "new"]
    changed = [f for f in files if f["status"] == "modified"]
    totals = dict(
        new_file_count=len(new),
        new_bytes=sum(f["bytes"] for f in new),
        modified_file_count=len(changed),
        modified_final_bytes=sum(f["bytes"] for f in changed),
        modified_delta_bytes=sum(f["delta_bytes"] for f in changed),
        net_added_bytes=sum(f["delta_bytes"] for f in files),
    )
    totals["new_mib"] = f"{totals['new_bytes'] / 1048576:.6f}"
    totals["net_added_mib"] = f"{totals['net_added_bytes'] / 1048576:.6f}"
    return dict(
        completed_on="2026-10-05",
        task=RUN,
        measurement="logical file size in bytes; 1 MiB = 1048576 bytes",
        scope=(
            "New and modified retained deliverables from this task; unchanged DB/input files, "
            "temporary files and OS caches excluded"
        ),
        inventory_and_size_log_included=True,
        self_sha256_omitted=True,
        totals=totals,
        files=files,
    )


def log_row(t):
    values = [
        "2026-10-05",
        "1400m 등급·함수율 기록 기준",
        str(t["new_file_count"]),
        str(t["new_bytes"]),
        t["new_mib"],
        str(t["modified_file_count"]),
        f"{t['modified_delta_bytes']:+d}",
        f"{t['net_added_bytes']:+d}",
        f"[명세]({RUN}/outputs/artifact_inventory.json)",
    ]
    return "| " + " | ".join(values) + f" | <!-- {RUN} -->\n"


def main():
    baseline = json.loads(BASELINE.read_text())
    old_log = (
        LOG.read_text()
        if LOG.exists()
        else (
            "# 이 세션의 작업별 산출물 용량\n\n"
            "2026-10-05부터 적용. 논리적 파일 크기 기준, MiB=1,048,576바이트. "
            "기존 참조 DB·원장은 제외하고 새 보관 산출물·수정 파일·용량 명세 자체를 포함한다. "
            "각 행은 해당 작업 완료 시점의 크기다.\n\n"
            "| 완료일 | 작업 | 신규 파일 | 신규 바이트 | 신규 MiB | 수정 파일 | "
            "수정 순증감 바이트 | 전체 순증감 바이트 | 상세 |\n"
            "|---|---|---:|---:|---:|---:|---:|---:|---|\n"
        )
    )
    # Rerunning replaces this task's row; it does not duplicate completed entries.
    old_log = (
        "\n".join(line for line in old_log.splitlines() if f"<!-- {RUN} -->" not in line) + "\n"
    )
    if not MANIFEST.exists():
        MANIFEST.write_text("{}\n")
    if not LOG.exists():
        LOG.write_text(old_log)
    for _ in range(20):
        data = collect(baseline)
        t = data["totals"]
        row = log_row(t)
        LOG.write_text(old_log + row, encoding="utf-8")
        data = collect(baseline)
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if collect(baseline) == data:
            # The log's values must also match the manifest after the size fixed point.
            t = data["totals"]
            expected = log_row(t)
            if LOG.read_text() == old_log + expected:
                break
    else:
        raise RuntimeError("Inventory/log sizes did not stabilize")
    final = json.loads(MANIFEST.read_text())
    assert final == collect(baseline)
    for f in final["files"]:
        assert (ROOT / f["path"]).stat().st_size == f["bytes"]
    print(json.dumps(final["totals"], ensure_ascii=False, indent=2))
    print("Largest new files:")
    for f in sorted(
        [f for f in final["files"] if f["status"] == "new"], key=lambda x: x["bytes"], reverse=True
    )[:5]:
        print(f["path"], f["bytes"])


if __name__ == "__main__":
    main()

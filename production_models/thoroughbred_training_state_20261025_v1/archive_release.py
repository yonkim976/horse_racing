"""Append this release's evidence without replacing concurrent research records."""

from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "thoroughbred/research"
CONCLUSION = RESEARCH / "conclusions/58N_PERSONAL_T2_PROMOTION.md"
INVENTORY = HERE / "artifact_inventory.json"
MARKER = "personal_t2_promotion_20261025"
BEFORE = json.loads((HERE / "preexisting_files.json").read_text())
CENTRAL = {
    "thoroughbred/research/README.md",
    "thoroughbred/research/conclusions/README.md",
    "thoroughbred/research/conclusions/SOURCES.md",
    "thoroughbred/research/conclusions/source_manifest.json",
    "thoroughbred/research/ARTIFACT_SIZE_LOG.md",
}
ADDITIONAL = [
    ROOT / "scripts/predict_thoroughbred_main.py",
    ROOT / "tests/test_promoted_training_state.py",
    ROOT / "docs/THOROUGHBRED_MODEL_IMPROVEMENT_2026-10-25.md",
    CONCLUSION,
]
PREVIOUS_BYTES = 196_761_183


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def owned_paths():
    return sorted(
        [p for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts] + ADDITIONAL
    )


def upsert(path, body):
    before = sha(path)
    old = path.read_text()
    start, end = f"<!-- {MARKER}:start -->", f"<!-- {MARKER}:end -->"
    block = f"{start}\n{body.rstrip()}\n{end}"
    if start in old:
        a = old.index(start)
        b = old.index(end, a) + len(end)
        new = old[:a] + block + old[b:]
    else:
        new = old + "\n\n" + block + "\n"
    require(sha(path) == before, "Concurrent update: " + str(path))
    path.write_text(new)


def manifest():
    path = RESEARCH / "conclusions/source_manifest.json"
    before = sha(path)
    value = json.loads(path.read_text())
    for key, paths in [
        ("sources", [p for p in owned_paths() if p not in [CONCLUSION, INVENTORY]]),
        ("conclusions", [CONCLUSION]),
    ]:
        lookup = {x["path"]: i for i, x in enumerate(value[key])}
        for p in paths:
            item = {"path": str(p.relative_to(ROOT)), "sha256": sha(p)}
            if item["path"] in lookup:
                value[key][lookup[item["path"]]] = item
            else:
                value[key].append(item)
    value["data_end_by_study"][MARKER] = {
        "study": HERE.name,
        "profile": "thoroughbred-training-state-20261025-v1",
        "selected_variant": "personal_t2_2026",
        "supported_meets": [1, 3],
        "history_snapshot_end": "2026-09-20",
        "training_snapshot_end": "2026-09-28",
        "comparison_races": 1258,
        "technical_replay_races": 1288,
        "result_free_fixture_races": 40,
        "production_changed": True,
        "new_training_fits": 0,
        "independent_future_validation": False,
        "actual_live_publications": False,
        "weekly_improvement": "Monday 10:00 Asia/Seoul; current-thread heartbeat",
        "auto_promote_future_candidates": False,
    }
    value["updated_at"] = "2026-10-25"
    require(sha(path) == before, "Concurrent manifest update")
    dump(path, value)


def inventory():
    files = [{"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size} for p in owned_paths()]
    concurrent = json.loads((HERE / "concurrent_updates.json").read_text())
    changed = []
    for name, old in BEFORE.items():
        p = ROOT / name
        delta = p.stat().st_size - old["bytes"]
        external = concurrent[name]["external_delta_bytes"]
        changed.append(
            {
                "path": name,
                "bytes_before": old["bytes"],
                "bytes_after": p.stat().st_size,
                "delta_bytes": delta,
                "external_delta_bytes": external,
                "task_delta_bytes": delta - external,
                "sha256_before": old["sha256"],
                "sha256_after": sha(p),
            }
        )
    total = sum(x["bytes"] for x in files)
    require(total + PREVIOUS_BYTES < 300_000_000, "Session storage ceiling exceeded")
    summary = {
        "new_file_count": len(files),
        "new_bytes": total,
        "new_mib": total / 1048576,
        "largest_file": max(files, key=lambda x: x["bytes"]),
        "modified_file_count": len(changed),
        "modified_final_bytes": sum(x["bytes_after"] for x in changed),
        "modified_delta_bytes": sum(x["delta_bytes"] for x in changed),
        "modified_external_delta_bytes": sum(x["external_delta_bytes"] for x in changed),
        "modified_task_delta_bytes": sum(x["task_delta_bytes"] for x in changed),
        "previous_ten_studies_new_bytes": PREVIOUS_BYTES,
        "combined_new_bytes": total + PREVIOUS_BYTES,
    }
    return {
        "release": HERE.name,
        "status": "complete",
        "summary": summary,
        "new_files": files,
        "modified_existing_files": changed,
        "self_inclusive": True,
        "units": "logical bytes; 1MiB=1048576bytes",
        "excluded": "Referenced DB/full-history/full-feature assets, transient caches and app-owned automation configuration. Frozen production model copies are included.",
    }


def indexes(summary):
    title = "연구58N 서울·부산 조교 변화 모델 운영 승격"
    report = "../../production_models/thoroughbred_training_state_20261025_v1/README.md"
    note = "사용자 지시로 personal_t2_2026 승격. 축800→830/1,258경주. 1,288경주 재현·전환 후40경주/432두 실행·테스트10개 통과. 이전 프로필/제주 보존, 월요일10시 지속 개선. 독립 미래검증 아님."
    upsert(RESEARCH / "README.md", f"[{title}]({report}): {note}")
    upsert(RESEARCH / "conclusions/README.md", f"[{title}]({CONCLUSION.name}): {note}")
    upsert(
        RESEARCH / "conclusions/SOURCES.md",
        f"[{title}]({CONCLUSION.name}) · [운영 보고서](../{report}) · [전환 확인](../../../production_models/thoroughbred_training_state_20261025_v1/verification/activation_verification.json) · [주간 절차](../../../docs/THOROUGHBRED_MODEL_IMPROVEMENT_2026-10-25.md). {note}",
    )
    s = summary
    upsert(
        RESEARCH / "ARTIFACT_SIZE_LOG.md",
        "| 날짜 | 작업 | 신규 파일 | 신규 bytes | MiB | 수정 파일 | 수정 최종 bytes | 순증감 bytes | 명세 |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---|\n"
        f"| 2026-10-25 | 서울·부산 personal_t2 운영 승격 | {s['new_file_count']} | {s['new_bytes']} | {s['new_mib']:.6f} | {s['modified_file_count']} | {s['modified_final_bytes']} | {s['modified_delta_bytes']:+d} | [명세](../../production_models/thoroughbred_training_state_20261025_v1/artifact_inventory.json) |\n\n"
        f"최대 `{s['largest_file']['path']}` {s['largest_file']['bytes']:,} bytes. 운영 모델2개와 소형 fixture 포함, DB/전체 이력 복제 없음. 이전10연구와 합계 {s['combined_new_bytes']:,}/300,000,000 bytes. 다른 작업의 중앙 수정 순증 {s['modified_external_delta_bytes']:,} bytes 보존, 이번 작업 순증 {s['modified_task_delta_bytes']:,} bytes.",
    )


def main():
    require(
        json.loads((HERE / "verification/activation_verification.json").read_text())["status"]
        == "passed",
        "Activation not verified",
    )
    concurrent_path = HERE / "concurrent_updates.json"
    if not concurrent_path.exists():
        dump(
            concurrent_path,
            {
                name: {
                    "sha256_before_our_first_central_write": sha(ROOT / name),
                    "external_delta_bytes": (ROOT / name).stat().st_size - old["bytes"]
                    if name in CENTRAL
                    else 0,
                    "handling": "Append own marker block / merge own manifest entries; preserve other changes"
                    if name in CENTRAL
                    else "Own implementation change",
                }
                for name, old in BEFORE.items()
            },
        )
    if not INVENTORY.exists():
        dump(INVENTORY, {})
    summary = inventory()["summary"]
    for _ in range(32):
        indexes(summary)
        manifest()
        value = inventory()
        dump(INVENTORY, value)
        after = inventory()
        if value == after and summary == after["summary"]:
            break
        summary = after["summary"]
    else:
        raise RuntimeError("Self-inclusive inventory did not converge")
    require(json.loads(INVENTORY.read_text()) == inventory(), "Inventory mismatch")
    links = 0
    for path in [HERE / "README.md", HERE / "PUBLICATION.md", CONCLUSION]:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            require(
                (path.parent / target.split("#")[0]).exists(), f"Missing link: {path}: {target}"
            )
            links += 1
    value = json.loads((RESEARCH / "conclusions/source_manifest.json").read_text())
    paths = {str(p.relative_to(ROOT)) for p in owned_paths() if p != INVENTORY}
    registered = [x for key in ["sources", "conclusions"] for x in value[key] if x["path"] in paths]
    require(len(registered) == len(paths), "Missing source hashes")
    require(all(sha(ROOT / x["path"]) == x["sha256"] for x in registered), "Source hash mismatch")
    print(
        json.dumps(
            {
                "status": "passed",
                **summary,
                "local_links_checked": links,
                "source_hashes_checked": len(registered),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

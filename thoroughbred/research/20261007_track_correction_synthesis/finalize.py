# ruff: noqa: E501
"""Verify a literature synthesis and account for its retained local artifacts."""

import csv
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CENTRAL = HERE.parent / "conclusions"
TOPIC = CENTRAL / "04A_TRACK_TOTAL_CORRECTION.md"
OUT = HERE / "outputs"
RUN = HERE.name
BASELINE = Path("/tmp/horse_track_synthesis_baseline_20261007.json")
LOG = HERE.parent / "ARTIFACT_SIZE_LOG.md"
INVENTORY = OUT / "artifact_inventory.json"
VERIFICATION = OUT / "verification.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    OUT.mkdir(exist_ok=True)
    sources = [
        CENTRAL / name
        for name in [
            "01_TRACK_MOISTURE.md",
            "03_GATE_POSITION.md",
            "04_JOINT_CORRECTION.md",
            "23_MONTHLY_SAME_MOISTURE.md",
        ]
    ]
    reference = HERE.parent / "20261002_moisture_strength_selection/outputs/reference_seconds.csv"
    sources.append(reference)
    source_hashes = [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in sources]
    expected = {
        "1": {"건조": 0.0, "양호": -0.10, "다습": -0.01, "포화": 0.39, "불량": 1.03},
        "3": {"건조": 0.0, "양호": -0.11, "다습": -0.07, "포화": 0.58, "불량": 0.87},
    }
    checks = []
    with reference.open() as stream:
        for row in csv.DictReader(stream):
            if row["distance_m"] == "1200" and row["meet"] in expected:
                want = expected[row["meet"]][row["band"]]
                assert row["supported"] == "True"
                assert abs(round(float(row["add_seconds_conservative"]), 2) - want) < 1e-12
                checks.append({"meet": row["meet"], "band": row["band"], "seconds": want})
    assert len(checks) == 10
    assert round(72.00 + expected["1"]["불량"], 2) == 73.03
    claims = {
        "rates_80_90": (sources[0], ["80%", "90%"]),
        "gate_top3_percentage_points": (sources[1], ["+1.97", "−1.82", "%p"]),
        "relative_positions": (
            sources[1],
            ["2두 마군에는 중간이 없다", "절대 위치를 뜻하지 않는다"],
        ),
        "conditional_recent_gate_settings": (sources[2], ["14일", "56일", "40경주", "84일", "5%p"]),
        "dry_august_month_effect": (sources[3], ["-0.61", "-0.65", "채택하지 않았다"]),
    }
    for label, (path, terms) in claims.items():
        content = path.read_text()
        assert all(term in content for term in terms), label
    verification = json.loads(VERIFICATION.read_text()) if VERIFICATION.exists() else {}
    owned = verification.get("task_owned_shared_deltas", {})
    additions = {
        CENTRAL / "README.md": (
            "\n\n## 주로 관련 보정의 종합 적용안\n\n"
            "[함수율·월·게이트·내외측을 종합하는 방법](04A_TRACK_TOTAL_CORRECTION.md): "
            "함수율 보정을 유지하며 월·게이트는 전체시간 공동 추정으로 검증한다. "
            "입상률 %p를 초로 변환하거나 실제 위치의 효과를 자동 차감하지 않는다. "
            "기존 연구 33개의 종합이며 새 계수 채택은 아니다.\n"
        ),
        CENTRAL / "SOURCES.md": (
            "\n\n## 주로 보정 결과의 종합\n\n"
            f"[기존 연구의 종합 적용안](../{RUN}/README.md) · "
            "[중앙 요약](04A_TRACK_TOTAL_CORRECTION.md) · "
            f"[출처 대조](../{RUN}/outputs/verification.json) · "
            f"[용량](../{RUN}/outputs/artifact_inventory.json). "
            "01·03·04·23번 결론을 대조한 설계이며 새 독립 연구나 수치 채택이 아니다.\n"
        ),
    }
    for path, addition in additions.items():
        name = str(path.relative_to(ROOT))
        text = path.read_text()
        if "## 주로 관련 보정의 종합 적용안" not in text and path.name == "README.md":
            path.write_text(text + addition)
            owned[name] = len(addition.encode())
        elif "## 주로 보정 결과의 종합" not in text and path.name == "SOURCES.md":
            path.write_text(text + addition)
            owned[name] = len(addition.encode())
        assert name in owned
    path = CENTRAL / "source_manifest.json"
    before = path.stat().st_size
    manifest = json.loads(path.read_text())
    own_source = str((HERE / "README.md").relative_to(ROOT))
    if not any(x["path"] == own_source for x in manifest["sources"]):
        manifest["sources"].append({"path": own_source, "sha256": sha(HERE / "README.md")})
    for item in manifest["sources"]:
        assert sha(ROOT / item["path"]) == item["sha256"]
    manifest["conclusions"] = [
        {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["track_correction_synthesis_added"] = True
    manifest["track_correction_synthesis_note"] = (
        "기존 연구 종합. 새 계수 추정·채택·운영 변경 없음."
    )
    write_json(path, manifest)
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    links = 0
    for path in [HERE / "README.md", TOPIC]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
            resolved = (path.parent / target.split("#")[0]).resolve()
            assert resolved.is_relative_to(ROOT)
            assert resolved.exists() or resolved in [INVENTORY, VERIFICATION]
            links += 1
    for item in source_hashes:
        assert sha(ROOT / item["path"]) == item["sha256"]
    for item in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / item["path"]) == item["sha256"]
    write_json(
        VERIFICATION,
        {
            "passed": True,
            "kind": "source_reconciliation_and_design_not_new_empirical_analysis",
            "sources": source_hashes,
            "reference_cells_checked": checks,
            "claims_checked": list(claims),
            "local_links_checked": links,
            "existing_research_count_unchanged": 33,
            "new_correction_adopted": False,
            "production_changed": False,
            "task_owned_shared_deltas": owned,
        },
    )
    baseline = json.loads(BASELINE.read_text())
    paths = [*HERE.rglob("*"), TOPIC, *additions, CENTRAL / "source_manifest.json", LOG]
    paths = sorted({p for p in paths if p.is_file() and "__pycache__" not in p.parts})
    marker = f"<!-- {RUN} -->"
    old_log = "\n".join(x for x in LOG.read_text().splitlines() if marker not in x) + "\n"
    INVENTORY.write_text("{}\n")

    def collect():
        files = []
        for path in sorted(set(paths + [INVENTORY])):
            assert path.resolve().is_relative_to(ROOT) and not path.is_symlink()
            name = str(path.relative_to(ROOT))
            size = path.stat().st_size
            previous = baseline.get(name)
            delta = size - (previous["size"] if previous else 0)
            task_delta = owned.get(name, delta)
            if path == LOG:
                task_delta = sum(
                    len(x.encode())
                    for x in LOG.read_text().splitlines(keepends=True)
                    if marker in x
                )
            files.append(
                {
                    "path": name,
                    "status": "modified" if previous else "new",
                    "bytes": size,
                    "prior_bytes": previous["size"] if previous else 0,
                    "delta_bytes": task_delta,
                    "outside_task_delta_bytes": delta - task_delta,
                    "sha256": None if path == INVENTORY else sha(path),
                }
            )
        new = [x for x in files if x["status"] == "new"]
        modified = [x for x in files if x["status"] == "modified"]
        totals = {
            "new_file_count": len(new),
            "new_bytes": sum(x["bytes"] for x in new),
            "modified_file_count": len(modified),
            "modified_final_bytes": sum(x["bytes"] for x in modified),
            "modified_delta_bytes": sum(x["delta_bytes"] for x in modified),
            "net_added_bytes": sum(x["delta_bytes"] for x in files),
            "outside_task_shared_delta_bytes": sum(x["outside_task_delta_bytes"] for x in files),
        }
        totals["new_mib"] = f"{totals['new_bytes'] / 1048576:.6f}"
        return {
            "completed_on": "2026-10-07",
            "task": RUN,
            "measurement": "logical bytes, 1 MiB = 1048576 bytes; inventory and log included",
            "self_sha256_omitted": True,
            "totals": totals,
            "files": files,
        }

    for _ in range(20):
        data = collect()
        t = data["totals"]
        row = (
            f"| 2026-10-07 | 주로 보정 종합 적용안 | {t['new_file_count']} | {t['new_bytes']} | "
            f"{t['new_mib']} | {t['modified_file_count']} | {t['modified_delta_bytes']:+d} | "
            f"{t['net_added_bytes']:+d} | [명세]({RUN}/outputs/artifact_inventory.json) | {marker}\n"
        )
        LOG.write_text(old_log + row)
        write_json(INVENTORY, collect())
        if collect() == data and LOG.read_text() == old_log + row:
            break
    else:
        raise RuntimeError("Inventory fixed point failed")
    assert json.loads(INVENTORY.read_text()) == collect()
    print(json.dumps(collect()["totals"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

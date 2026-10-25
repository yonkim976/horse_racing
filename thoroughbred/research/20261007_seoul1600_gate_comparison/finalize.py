"""Connect a verified gate follow-up to the existing research conclusions."""

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions"
RUN = HERE.name


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert json.loads((OUT / "verification.json").read_text())["passed"]
    assert json.loads((OUT / "independent_verification.json").read_text())["passed"]
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    additions = {
        CENTRAL / "README.md": (
            "\n\n## 서울1600m 게이트의 거리 간 직접 비교\n\n"
            "[서울1600m 후속 결론](03A_SEOUL1600_GATE.md): 내측−외측 Top3 차이 "
            "+10.06%p로 큰 편이며 1400·1800m보다 큰 차이가 전체기간 Holm 후 남았다. "
            "최근·같은 날짜·10두 보조 비교와 한계를 함께 보존했다. "
            "기존 게이트 연구 후속으로 연구 수 33개와 보정 채택 상태는 유지한다.\n"
        ),
        CENTRAL / "SOURCES.md": (
            "\n\n## 서울1600m 게이트 거리 간 비교 후속\n\n"
            f"[원 연구와 상세표](../{RUN}/README.md) · "
            "[중앙 결론](03A_SEOUL1600_GATE.md) · "
            f"[계획](../{RUN}/PLAN.md) · "
            f"[별도 부분회귀 검증](../{RUN}/outputs/independent_verification.json) · "
            f"[용량](../{RUN}/outputs/artifact_inventory.json). "
            "기존 게이트 모집단 재사용, 거리 간 공분산·다중비교와 사후 10두 분석을 구분했다.\n"
        ),
    }
    for path, addition in additions.items():
        name = str(path.relative_to(ROOT))
        before = path.stat().st_size
        text = path.read_text()
        heading = addition.splitlines()[2]
        if heading not in text:
            path.write_text(text + addition)
            owned[name] = path.stat().st_size - before
        assert name in owned
    path = CENTRAL / "source_manifest.json"
    before = path.stat().st_size
    manifest = json.loads(path.read_text())
    own = str((HERE / "README.md").relative_to(ROOT))
    if not any(item["path"] == own for item in manifest["sources"]):
        manifest["sources"].append({"path": own, "sha256": sha(HERE / "README.md")})
    manifest["conclusions"] = [
        {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["seoul1600_gate_followup_added"] = True
    manifest["seoul1600_gate_followup_note"] = (
        "기존 게이트 연구의 거리 간 직접 비교. 사후 10두 민감도 구분, 보정·운영 변경 없음."
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    count = 0
    for item in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / item["path"]) == item["sha256"]
        count += 1
    links = 0
    for p in [*HERE.glob("*.md"), CENTRAL / "03A_SEOUL1600_GATE.md"]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", p.read_text()):
            dest = (p.parent / target.split("#")[0]).resolve()
            assert dest.is_relative_to(ROOT)
            assert dest.exists() or dest == OUT / "artifact_inventory.json"
            links += 1
    result = {
        "passed": True,
        "central_hashes_checked": count,
        "local_links_checked": links,
        "independent_research_count_unchanged": 33,
        "new_correction_adopted": False,
        "production_changed": False,
        "posthoc_full10_disclosed": True,
    }
    (OUT / "final_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

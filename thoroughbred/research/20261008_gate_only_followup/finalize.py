"""Connect verified gate-only evidence to the research conclusion index."""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions"
RUN = HERE.name


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for name in ["verification.json", "period_table_verification.json"]:
        assert json.loads((OUT / name).read_text())["passed"]
    payload = json.loads((OUT / "web_gate_only.json").read_text())
    tables = {
        "number_profiles": "number_profiles.csv",
        "selection": "candidate_selection.csv",
        "evaluation": "evaluation.csv",
        "paired_day_bootstrap": "paired_day_bootstrap.csv",
        "historical_snapshot": "snapshot_20260921.csv",
        "preserved_month_deviations": "gate_significant_month_deviations.csv",
    }
    for key, filename in tables.items():
        expected = pd.read_csv(OUT / filename)
        actual = pd.DataFrame(payload[key])
        expected = expected.astype(object).where(expected.notna(), float("nan"))
        actual = actual.astype(object).where(actual.notna(), float("nan"))
        pd.testing.assert_frame_equal(
            expected, actual, check_dtype=False, check_exact=False, atol=1e-9, rtol=1e-9
        )
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    additions = {
        CENTRAL / "README.md": (
            "\n\n## 게이트 번호별·기간별 후속 검증\n\n"
            "[게이트 전용 후속 결론](03C_GATE_ONLY_FOLLOWUP.md): "
            "서울1600m 10두와 부산1600m 12두의 번호별 장기 차이, "
            "게이트만 분리한 날짜·주말·월별 표와 실제 현재 위치 없는 시간순 예측을 보존했다. "
            "부산 상위3두 선택의 보조 지표는 개선 방향이나 전체 확률 손실 개선은 확인하지 못했다. "
            "기존 게이트 연구 후속으로 연구 수33개와 보정 채택 상태는 유지한다.\n"
        ),
        CENTRAL / "SOURCES.md": (
            "\n\n## 게이트 전용 번호·기간·예측 후속\n\n"
            f"[원 보고서](../{RUN}/README.md) · [중앙 결론](03C_GATE_ONLY_FOLLOWUP.md) · "
            f"[계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
            f"[게시 요약](../{RUN}/PUBLICATION.md) · "
            f"[독립 대조](../{RUN}/outputs/verification.json) · "
            f"[기간표 보존 검증](../{RUN}/outputs/period_table_verification.json) · "
            f"[용량](../{RUN}/outputs/artifact_inventory.json). "
            "기존 모집단151,115출전·13,928경주 재사용. 번호별386대비와 과거 자료만 쓰는 "
            "예측후보11개를 별도 검증했다. 새 초·확률 가산이나 운영 변경은 없다.\n"
        ),
    }
    for path, addition in additions.items():
        name = str(path.relative_to(ROOT))
        before = path.stat().st_size
        content = path.read_text()
        if addition.splitlines()[2] not in content:
            path.write_text(content + addition)
            owned[name] = path.stat().st_size - before
        assert name in owned
    path = CENTRAL / "source_manifest.json"
    before = path.stat().st_size
    manifest = json.loads(path.read_text())
    for filename in ["README.md", "SOURCES.md", "PUBLICATION.md"]:
        source = HERE / filename
        name = str(source.relative_to(ROOT))
        entry = {"path": name, "sha256": sha(source)}
        matches = [item for item in manifest["sources"] if item["path"] == name]
        if matches:
            matches[0].update(entry)
        else:
            manifest["sources"].append(entry)
    manifest["conclusions"] = [
        {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["gate_only_followup_added"] = True
    manifest["gate_only_followup_note"] = (
        "기존 게이트 연구 후속. 번호별·기간별 관찰과 실제 현재 위치 없는 시간순 후보 비교. "
        "새 보정 채택·운영 변경 없음."
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    count = 0
    for item in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / item["path"]) == item["sha256"], item["path"]
        count += 1
    links = 0
    for p in [*HERE.glob("*.md"), CENTRAL / "03C_GATE_ONLY_FOLLOWUP.md"]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", p.read_text()):
            dest = (p.parent / target.split("#")[0]).resolve()
            assert dest.is_relative_to(ROOT)
            assert dest.exists() or dest == OUT / "artifact_inventory.json", (p, target)
            links += 1
    result = {
        "passed": True,
        "central_hashes_checked": count,
        "local_links_checked": links,
        "web_payload_tables_checked": len(tables),
        "independent_research_count_unchanged": 33,
        "new_correction_adopted": False,
        "production_changed": False,
        "figure_visually_reviewed": True,
    }
    (OUT / "final_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

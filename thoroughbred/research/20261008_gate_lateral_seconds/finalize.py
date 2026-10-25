"""Connect the verified within-race/pack seconds follow-up to conclusions."""

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
    assert json.loads((OUT / "verification.json").read_text())["passed"]
    payload = json.loads((OUT / "web_gate_lateral_seconds.json").read_text())
    tables = {
        "gate_focus": "gate_focus_table.csv",
        "lateral_focus": "lateral_focus_table.csv",
        "profiles": "seconds_profiles.csv",
        "gate_candidates": "gate_correction_candidates.csv",
        "field_lookup": "field_gate_lookup.csv",
    }
    for key, name in tables.items():
        a = pd.read_csv(OUT / name)
        b = pd.DataFrame(payload[key])
        for column in a:
            if pd.api.types.is_numeric_dtype(a[column]):
                b[column] = pd.to_numeric(b[column])
        a = a.astype(object).where(a.notna(), float("nan"))
        b = b.astype(object).where(b.notna(), float("nan"))
        pd.testing.assert_frame_equal(a, b, check_dtype=False, atol=1e-9, rtol=1e-9)
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    readme = CENTRAL / "README.md"
    before = readme.stat().st_size
    text = readme.read_text()
    heading = "## 같은 경주와 마군 안의 게이트 내외측 시간 후속"
    if heading not in text:
        text = text.replace(
            "서울·부산·영천 연구 34개와 두 결정 문서", "서울·부산·영천 연구 35개와 두 결정 문서"
        )
        text = text.replace(
            "| [원 보고서 목록](SOURCES.md) | 34개 연구와 결정 문서, 이전 연구의 원 경로 |",
            "| [원 보고서 목록](SOURCES.md) | 35개 연구와 결정 문서, 이전 연구의 원 경로 |",
        )
        lines = text.splitlines(keepends=True)
        matches = [
            i
            for i, line in enumerate(lines)
            if line.startswith("| 34 | 함수율·월·게이트의 완주시간 보정량")
        ]
        assert len(matches) == 1
        lines.insert(
            matches[0] + 1,
            "| 35 | 같은 경주·마군과 같은 말의 게이트·내외측 시간 차이 | "
            "서울1600m10번 등의 느린 방향과 코너·막판 내외측 방향 차이를 확인. "
            "최근 다중비교와 위치 선택의 한계 | 후향 조건부 설명·새 자동 보정 미채택 |\n",
        )
        text = "".join(lines)
        text += (
            "\n\n" + heading + "\n\n"
            "[게이트와 실제 위치 시간 후속](04C_GATE_LATERAL_SECONDS.md): "
            "276모형·4,671프로필로 같은 경주/마군과 같은 말을 통제했다. "
            "서울1600m10번은 전체+0.491초·최근+0.579초의 느린 방향이나 최근q=0.0648이었다. "
            "서울3C 외측 느림과G1F 외측 빠름을 구분하며 실제 위치를 경로 손실로 바꾸지 않는다. "
            "게이트·내외측 추가 자동 보정은 보류하고 기존 함수율·월 후보 상태를 유지한다. "
            "35번째 독립 연구이며 다음 경주 예측은 평가하지 않았다.\n"
        )
        readme.write_text(text)
        owned[str(readme.relative_to(ROOT))] = readme.stat().st_size - before
    sources = CENTRAL / "SOURCES.md"
    before = sources.stat().st_size
    text = sources.read_text()
    heading = "## 게이트와 상대 주행위치의 시간 차이 후속"
    if heading not in text:
        text += (
            "\n\n" + heading + "\n\n"
            f"35번째 연구 [원 보고서](../{RUN}/README.md) · "
            "[중앙 결론](04C_GATE_LATERAL_SECONDS.md) · "
            f"[계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
            f"[게시 요약](../{RUN}/PUBLICATION.md) · "
            f"[독립 검증](../{RUN}/outputs/verification.json) · "
            f"[용량](../{RUN}/outputs/artifact_inventory.json). "
            "같은 경주·마군 및마필 고정효과의 초 단위 후속. 남은 시간과 최종시간을 구분했다. "
            "새 보정 채택·운영 변경·다음 경주 예측 검증은 없다.\n"
        )
        sources.write_text(text)
        owned[str(sources.relative_to(ROOT))] = sources.stat().st_size - before
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
    manifest["scope"] = manifest["scope"].replace("연구34개", "연구35개")
    manifest["gate_lateral_seconds_added"] = True
    manifest["gate_lateral_seconds_note"] = (
        "35번째 독립 연구. 같은 경주/마군과 마필을 통제한 게이트·실제 위치의 초 단위 차이. "
        "남은 시간의 계측 범위 유지, 새 보정 채택·운영 변경·다음 경주 예측 검증 없음."
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    count = 0
    for item in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / item["path"]) == item["sha256"], item["path"]
        count += 1
    links = 0
    for p in [*HERE.glob("*.md"), CENTRAL / "04C_GATE_LATERAL_SECONDS.md"]:
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
        "independent_research_count": 35,
        "new_correction_adopted": False,
        "production_changed": False,
        "figures_visually_reviewed": 2,
    }
    (OUT / "final_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

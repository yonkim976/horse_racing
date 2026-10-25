"""Verify publication tables and register the completed local study."""

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


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    assert json.loads((OUT / "verification.json").read_text())["passed"]
    payload = json.loads((OUT / "web_moisture_gate_seconds.json").read_text())
    tables = {
        "coverage_grid": "coverage_grid.csv",
        "focus": "seoul1200_11_focus.csv",
        "number_focus": "1600_number_focus.csv",
        "candidates": "correction_candidates.csv",
        "interactions": "seconds_profiles.csv",
    }
    for key, name in tables.items():
        a = pd.read_csv(OUT / name, dtype={"level": str})
        if key == "interactions":
            a = a[
                a.adjustment.eq("dual")
                & a.family.eq("interaction")
                & a.period.isin(["all_mad4", "recent_mad4"])
            ].reset_index(drop=True)
        b = pd.DataFrame(payload[key])
        for col in a:
            if pd.api.types.is_numeric_dtype(a[col]):
                b[col] = pd.to_numeric(b[col])
        a = a.astype(object).where(a.notna(), float("nan"))
        b = b.astype(object).where(b.notna(), float("nan"))
        pd.testing.assert_frame_equal(a, b, check_dtype=False, atol=1e-8, rtol=1e-8)
    summary = json.loads((OUT / "summary.json").read_text())
    assert all(sha(ROOT / name) == digest for name, digest in summary["input_sha256"].items())
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    path = CENTRAL / "README.md"
    before = path.stat().st_size
    text = path.read_text()
    heading = "## 함수율 상태와 게이트 시간 차이의 교차 연구"
    if heading not in text:
        text = text.replace(
            "서울·부산·영천 연구 35개와 두 결정 문서", "서울·부산·영천 연구 36개와 두 결정 문서"
        )
        text = text.replace(
            "35개 연구와 결정 문서, 이전 연구의 원 경로",
            "36개 연구와 결정 문서, 이전 연구의 원 경로",
        )
        lines = text.splitlines(keepends=True)
        index = [
            i for i, line in enumerate(lines) if line.startswith("| 35 | 같은 경주·마군과 같은 말")
        ]
        assert len(index) == 1
        lines.insert(
            index[0] + 1,
            "| 36 | 함수율 상태×거리×두수×게이트의 시간 차이 | "
            "서울1200m11두에서 포화 때 건조 대비 외측 불리함 감소 방향. "
            "4,750비교의 소표본·미관측 명시 | 후향 교차 연구·새 게이트 보정 보류 |\n",
        )
        text = "".join(lines)
        text += (
            "\n\n"
            + heading
            + "\n\n"
            + (
                "[함수율 상태와 게이트 교차 연구](04D_MOISTURE_GATE_SECONDS.md): "
                "19개 지역×거리의4,750비교 행·14개 지역×거리89모형을 정리했다. "
                "서울1200m11두의 포화−건조 외내차 변화는 전체−0.423초·최근−0.419초이나 "
                "모든 감도와 지원 기준을 통과한 새 보정은 없다. "
                "번호·환산 그룹은 중복 증거이며 실제 주행 내외측과 구분한다. "
                "36번째 독립 연구, 다음 경주 예측 검증과 운영 변경 없음.\n"
            )
        )
        path.write_text(text)
        owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    path = CENTRAL / "SOURCES.md"
    before = path.stat().st_size
    text = path.read_text()
    heading = "## 함수율 상태와 게이트의 시간 교차 연구"
    if heading not in text:
        text += (
            "\n\n"
            + heading
            + "\n\n"
            + (
                f"36번째 연구 [원 보고서](../{RUN}/README.md) · "
                "[중앙 결론](04D_MOISTURE_GATE_SECONDS.md) · "
                f"[고정 계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
                f"[게시 요약](../{RUN}/PUBLICATION.md) · "
                f"[검증](../{RUN}/outputs/verification.json) · "
                f"[용량](../{RUN}/outputs/artifact_inventory.json). "
                "같은 경주·마필 통제 후 상태×게이트 대비와 건조 대비 상호작용. "
                "희소 장거리 효과 미생성, 새 보정 채택·운영 변경·다음 경주 검증 없음.\n"
            )
        )
        path.write_text(text)
        owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    path = CENTRAL / "source_manifest.json"
    before = path.stat().st_size
    manifest = json.loads(path.read_text())
    for filename in ["README.md", "SOURCES.md", "PUBLICATION.md"]:
        source = HERE / filename
        name = str(source.relative_to(ROOT))
        entry = dict(path=name, sha256=sha(source))
        matches = [item for item in manifest["sources"] if item["path"] == name]
        if matches:
            matches[0].update(entry)
        else:
            manifest["sources"].append(entry)
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = manifest["scope"].replace("연구35개", "연구36개")
    manifest["moisture_gate_seconds_added"] = True
    manifest["moisture_gate_seconds_note"] = (
        "36번째 연구. 상태별 게이트 초 차이와 건조 대비 상호작용. "
        "새 보정·운영 변경·다음 경주 검증 없음."
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    count = 0
    for item in manifest["sources"] + manifest["conclusions"]:
        target = (ROOT / item["path"]).resolve()
        assert target.is_relative_to(ROOT)
        assert sha(target) == item["sha256"], item["path"]
        count += 1
    links = 0
    for p in [*HERE.glob("*.md"), CENTRAL / "04D_MOISTURE_GATE_SECONDS.md"]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", p.read_text()):
            dest = (p.parent / target.split("#")[0]).resolve()
            assert dest.is_relative_to(ROOT)
            assert dest.exists() or dest == OUT / "artifact_inventory.json", (p, target)
            links += 1
    result = dict(
        passed=True,
        central_hashes_checked=count,
        local_links_checked=links,
        web_tables_checked=len(tables),
        independent_research_count=36,
        figures_visually_reviewed=1,
        new_correction_adopted=False,
        production_changed=False,
    )
    (OUT / "final_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

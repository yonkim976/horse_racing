"""Check publication tables and link the verified sectional study into conclusions."""

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
    summary = json.loads((OUT / "summary.json").read_text())
    assert all(sha(ROOT / name) == digest for name, digest in summary["input_sha256"].items())
    payload = json.loads((OUT / "web_section_candidate_v1.json").read_text())
    tables = {
        "gate_lookup": "section_gate_lookup.csv",
        "month_lookup": "section_month_lookup.csv",
        "focus": "1600_section_gate_focus.csv",
        "examples": "section_application_examples.csv",
    }
    for key, name in tables.items():
        b = pd.DataFrame(payload[key])
        a = pd.read_csv(OUT / name, dtype={"level": str})[b.columns]
        for col in a:
            if pd.api.types.is_numeric_dtype(a[col]):
                b[col] = pd.to_numeric(b[col])
        a = a.astype(object).where(a.notna(), float("nan"))
        b = b.astype(object).where(b.notna(), float("nan"))
        pd.testing.assert_frame_equal(a, b, check_dtype=False, atol=1e-8, rtol=1e-8)
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    path = CENTRAL / "README.md"
    before = path.stat().st_size
    text = path.read_text()
    heading = "## 구간기록의 함수율·월·게이트 시험 보정"
    if heading not in text:
        text = text.replace(
            "서울·부산·영천 연구 36개와 두 결정 문서", "서울·부산·영천 연구 37개와 두 결정 문서"
        )
        text = text.replace(
            "36개 연구와 결정 문서, 이전 연구의 원 경로",
            "37개 연구와 결정 문서, 이전 연구의 원 경로",
        )
        lines = text.splitlines(keepends=True)
        indices = [
            i
            for i, line in enumerate(lines)
            if line.startswith("| 36 | 함수율 상태×거리×두수×게이트")
        ]
        assert len(indices) == 1
        lines.insert(
            indices[0] + 1,
            "| 37 | 구간기록의 함수율·월·게이트 시간 보정 후보 | "
            "출발200m·마지막600m·마지막200m 직접 추정과 전체 일치 중간 잔여값 구분 | "
            "모델 시험 입력·구간 공식 채택 및 예측 검증 별도 |\n",
        )
        text = "".join(lines)
        text += (
            "\n\n"
            + heading
            + "\n\n"
            + (
                "[구간기록 보정 후보 v1](02A_SECTION_NORMALIZATION_CANDIDATE_V1.md): "
                "37번째 연구로75개 공통 설계 모형에서3구간을 추정하고 "
                "기존 구간 함수율 후보를 연결했다. "
                "서울1600m10두10번 건조의 게이트 후보는 출발200m−0.034초·"
                "마지막600m−0.083초·마지막200m−0.044초다. "
                "겹치는 구간을 중복하지 않고 중간값은 전체와 일치하는 잔여 환산으로 구분한다. "
                "직접 구간142,206출전·전체와4구간 완결133,223출전 원장을 제공한다. "
                "정책적 시험값이며 기존 전체시간 v1·구간 공식 채택 보류를 유지한다. "
                "운영 변경·다음 경주 예측 검증 없음.\n"
            )
        )
        path.write_text(text)
        owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    path = CENTRAL / "SOURCES.md"
    before = path.stat().st_size
    text = path.read_text()
    heading = "## 구간별 함수율·월·게이트 시험값 연구"
    if heading not in text:
        text += (
            "\n\n"
            + heading
            + "\n\n"
            + (
                f"37번째 연구 [원 보고서](../{RUN}/README.md) · "
                "[중앙 결론](02A_SECTION_NORMALIZATION_CANDIDATE_V1.md) · "
                f"[계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
                f"[함수](../{RUN}/apply.py) · [게시 요약](../{RUN}/PUBLICATION.md) · "
                f"[검증](../{RUN}/outputs/verification.json) · "
                f"[용량](../{RUN}/outputs/artifact_inventory.json). "
                "직접3목표·중간 잔여값·겹치는 구간을 구분했다. 다음 경주 검증과운영 변경 없음.\n"
            )
        )
        path.write_text(text)
        owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    path = CENTRAL / "source_manifest.json"
    before = path.stat().st_size
    manifest = json.loads(path.read_text())
    for filename in ["README.md", "SOURCES.md", "PUBLICATION.md"]:
        p = HERE / filename
        name = str(p.relative_to(ROOT))
        entry = dict(path=name, sha256=sha(p))
        matches = [item for item in manifest["sources"] if item["path"] == name]
        if matches:
            matches[0].update(entry)
        else:
            manifest["sources"].append(entry)
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = manifest["scope"].replace("연구36개", "연구37개")
    manifest["section_candidate_v1_added"] = True
    manifest["section_candidate_v1_note"] = (
        "37번째 연구. 직접3구간과잔여값 구분, 기존 전체 v1 보존. "
        "모델 시험 후보·운영 및 예측 검증 별도."
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    count = 0
    for item in manifest["sources"] + manifest["conclusions"]:
        p = (ROOT / item["path"]).resolve()
        assert p.is_relative_to(ROOT)
        assert sha(p) == item["sha256"], item["path"]
        count += 1
    links = 0
    for p in [*HERE.glob("*.md"), CENTRAL / "02A_SECTION_NORMALIZATION_CANDIDATE_V1.md"]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", p.read_text()):
            dest = (p.parent / target.split("#")[0]).resolve()
            assert dest.is_relative_to(ROOT)
            assert dest.exists() or dest == OUT / "artifact_inventory.json", (p, target)
            links += 1
    result = dict(
        passed=True,
        web_tables_checked=len(tables),
        central_hashes_checked=count,
        local_links_checked=links,
        independent_research_count=37,
        production_changed=False,
        prediction_validation=False,
    )
    (OUT / "final_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

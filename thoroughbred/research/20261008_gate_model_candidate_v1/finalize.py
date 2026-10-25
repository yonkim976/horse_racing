"""Verify the publication bundle and register this application follow-up."""

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
    payload = json.loads((OUT / "web_gate_candidate_v1.json").read_text())
    tables = {
        "lookup": "gate_correction_lookup.csv",
        "focus": "1600_trial_gate_values.csv",
        "examples": "application_examples.csv",
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
    heading = "## 모델 시험용 작은 게이트 보정값"
    if heading not in text:
        text += (
            "\n\n"
            + heading
            + "\n\n"
            + (
                "[모델 시험용 게이트 시간 보정 v1](04E_GATE_MODEL_CANDIDATE_V1.md): "
                "36번 상태 교차 연구의 적용 후속으로 독립 연구 수36개는 유지한다. "
                "확증적 채택 보류와 구분해30% 기본 반영·15% 상태 차이 반영 및 "
                "표본 수축의 후보를 만들었다. "
                "서울1600m10두10번 건조−0.111초·포화−0.081초, 부산1600m12두1번 건조−0.103초다. "
                "초 단위 표·적용 함수·후향 원장을 보존하며 기존 함수율에 가산, "
                "월 후보는 별도 스위치다. "
                "최적량·예측 개선·운영 반영은 미확정이다.\n"
            )
        )
        path.write_text(text)
        owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    path = CENTRAL / "SOURCES.md"
    before = path.stat().st_size
    text = path.read_text()
    heading = "## 모델 입력을 위한 게이트 보정 v1 후속"
    if heading not in text:
        text += (
            "\n\n"
            + heading
            + "\n\n"
            + (
                f"36번 연구 적용 후속 [원 보고서](../{RUN}/README.md) · "
                "[중앙 결론](04E_GATE_MODEL_CANDIDATE_V1.md) · "
                f"[계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
                f"[적용 함수](../{RUN}/apply.py) · [게시 요약](../{RUN}/PUBLICATION.md) · "
                f"[검증](../{RUN}/outputs/verification.json) · "
                f"[용량](../{RUN}/outputs/artifact_inventory.json). "
                "규칙으로 수축한 시험 후보이며 실증 연구 수는 늘리지 않는다. "
                "운영 변경·다음 경주 검증 없음.\n"
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
    manifest["gate_model_candidate_v1_added"] = True
    manifest["gate_model_candidate_v1_note"] = (
        "36번 연구 적용 후속. 규칙으로 수축한 초 단위 시험 표·함수·후향 원장. "
        "최적량·예측 개선·운영 반영 미확정, 독립 연구 수 유지."
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
    for p in [*HERE.glob("*.md"), CENTRAL / "04E_GATE_MODEL_CANDIDATE_V1.md"]:
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
        followup_type="model_trial_application",
        production_changed=False,
        predictive_validation=False,
    )
    (OUT / "final_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

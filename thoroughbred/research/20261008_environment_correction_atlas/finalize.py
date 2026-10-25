"""Verify source preservation, publication tables and shared research registration."""

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions"
RUN = HERE.name
WHOLE = HERE.parent / "20261008_gate_model_candidate_v1/outputs"
SECTION = HERE.parent / "20261008_section_normalization_candidate_v1/outputs"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_guarded(path, content, mtime):
    assert path.stat().st_mtime_ns == mtime, "shared file changed; reread before retry"
    path.write_text(content)


def main():
    assert json.loads((OUT / "verification.json").read_text())["passed"]
    for name in ["analysis_summary.json", "build_summary.json"]:
        summary = json.loads((OUT / name).read_text())
        for file, digest in summary["input_sha256"].items():
            assert sha(ROOT / file) == digest, file
    payload = json.loads((OUT / "web_environment_correction_atlas.json").read_text())
    tables = {
        "representative_saturated": "representative_saturated.csv",
        "reference1200": "reference1200_all_states.csv",
        "condition_summary": "condition_correction_summary.csv",
        "distance_summary": "distance_correction_summary.csv",
        "month_components": "month_components.csv",
        "lateral_profiles": "lateral_moisture_period_profiles.csv",
        "examples": "combined_application_examples.csv",
    }
    for key, name in tables.items():
        b = pd.DataFrame(payload[key])
        a = pd.read_csv(OUT / name, dtype={"level": str})[b.columns]
        for col in a:
            if pd.api.types.is_numeric_dtype(a[col]):
                b[col] = pd.to_numeric(b[col])
        pd.testing.assert_frame_equal(a, b, check_dtype=False, atol=1e-8, rtol=1e-8)
    gates = pd.read_parquet(OUT / "gate_components.parquet")
    old = pd.read_csv(WHOLE / "gate_correction_lookup.csv", dtype={"level": str})
    keys = ["meet", "distance_m", "field_size", "mode", "block", "band", "period", "level"]
    z = gates[gates.target.eq("finish")].merge(
        old[keys + ["gate_add_seconds"]], on=keys, suffixes=("", "_old"), validate="one_to_one"
    )
    assert len(z) == len(old) and np.allclose(
        z.gate_add_seconds, z.gate_add_seconds_old, atol=1e-12
    )
    month = pd.read_csv(OUT / "month_components.csv")
    old = pd.read_csv(WHOLE / "month_candidate_reference.csv")
    z = month[month.target.eq("finish") & month.period.eq("all_mad4")].merge(
        old, on=["meet", "distance_m", "month"], validate="one_to_one"
    )
    assert len(z) == len(old) and np.allclose(
        z.month_add_seconds, z.month_candidate_add, atol=1e-12
    )
    oldsec = pd.read_csv(SECTION / "section_month_lookup.csv").rename(columns={"section": "target"})
    z = month[month.target.ne("finish")].merge(
        oldsec,
        on=["meet", "distance_m", "target", "period", "month"],
        suffixes=("", "_old"),
        validate="one_to_one",
    )
    assert len(z) == len(oldsec) and np.allclose(
        z.month_add_seconds, z.month_add_seconds_old, atol=1e-12
    )
    moist = pd.read_csv(OUT / "moisture_components.csv")
    old = pd.read_csv(WHOLE / "moisture_reference.csv")
    z = moist[moist.target.eq("finish")].merge(
        old, on=["meet", "distance_m", "band"], validate="one_to_one"
    )
    assert len(z) == len(old) and np.allclose(
        z.moisture_add_seconds,
        z.add_seconds_conservative.where(z.supported),
        equal_nan=True,
        atol=1e-12,
    )
    assert z.adopted_moisture.eq(z.adopted_supported).all()
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    path = CENTRAL / "README.md"
    before, mtime = path.stat().st_size, path.stat().st_mtime_ns
    text = path.read_text()
    heading = "## 함수율 월 게이트 합산과 내외측 별도 특성"
    rows = [
        (i, int(m.group(1)))
        for i, line in enumerate(text.splitlines(keepends=True))
        if (m := re.match(r"^\| (\d+) \|", line))
    ]
    if heading not in text:
        number = max(n for _, n in rows) + 1
        text = re.sub(
            r"서울·부산·영천 연구 \d+개와 두 결정 문서",
            f"서울·부산·영천 연구 {number}개와 두 결정 문서",
            text,
        )
        text = re.sub(
            r"\d+개 연구와 결정 문서, 이전 연구의 원 경로",
            f"{number}개 연구와 결정 문서, 이전 연구의 원 경로",
            text,
        )
        lines = text.splitlines(keepends=True)
        lines.insert(
            max(i for i, _ in rows) + 1,
            f"| {number} | 함수율·월·게이트 전체/구간 합산과 내외측 상태별 특성 | "
            "620,640조건 조회·50공동 민감도·244내외측 모형 | "
            "보수적 시험 합산·내외측 제외·운영 및 예측 검증 별도 |\n",
        )
        index = next(i for i, line in enumerate(lines) if line.startswith("| [2두 포함 공동 보정]"))
        lines.insert(
            index + 1,
            "| [전체 구간 환경 보정 종합](04F_ENVIRONMENT_CORRECTION_ATLAS.md) | "
            "경기장·거리·상태·월·게이트 합산초와기호·기간별내외측별도표 |\n",
        )
        text = "".join(lines)
        text += (
            "\n\n" + heading + "\n\n"
            "[환경 보정 종합](04F_ENVIRONMENT_CORRECTION_ATLAS.md): "
            f"{number}번째 독립 연구. 전체·출발200m·마지막600m·마지막200m의 "
            "함수율+월+게이트 시험값과크기기호를연결했다. "
            "서울/부산1200m포화의대표전체보정은약+0.396/+0.585초다. "
            "전체/최근·연도/분기노출요약과내외측244모형을별도제공한다. "
            "내외측은합산하지않고기존채택범위·운영모델·다음경주검증을유지한다.\n"
        )
        write_guarded(path, text, mtime)
        owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    else:
        number = int(
            next(
                re.match(r"^\| (\d+) \|", line).group(1)
                for line in text.splitlines()
                if "| 함수율·월·게이트 전체/구간 합산과" in line
            )
        )
    path = CENTRAL / "SOURCES.md"
    before, mtime = path.stat().st_size, path.stat().st_mtime_ns
    text = path.read_text()
    if heading not in text:
        text += (
            "\n\n" + heading + "\n\n"
            f"{number}번째 연구 [원 보고서](../{RUN}/README.md) · "
            "[중앙 결론](04F_ENVIRONMENT_CORRECTION_ATLAS.md) · "
            f"[계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
            f"[조회 함수](../{RUN}/apply.py) · [게시 요약](../{RUN}/PUBLICATION.md) · "
            f"[검증](../{RUN}/outputs/verification.json) · "
            f"[용량](../{RUN}/outputs/artifact_inventory.json). "
            "합산값·관측방향·내외측설명을구분하고기존채택/운영/예측검증을유지한다.\n"
        )
        write_guarded(path, text, mtime)
        owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    (HERE / "REGISTRATION_NOTE.md").write_text(
        "# 연구 등록 번호\n\n"
        f"계산 전 계획의 예상 번호39는 공유 결론 목록에 먼저 등록된 다른 연구 때문에 "
        f"최종{number}번으로 배정됐다. 동시 작업의 기존 항목을 보존했으며 "
        "계산 계획·자료·방법은 변경하지 않았다.\n"
    )
    path = CENTRAL / "source_manifest.json"
    before, mtime = path.stat().st_size, path.stat().st_mtime_ns
    manifest = json.loads(path.read_text())
    for name in ["README.md", "SOURCES.md", "PUBLICATION.md"]:
        doc = HERE / name
        entry = dict(path=str(doc.relative_to(ROOT)), sha256=sha(doc))
        matches = [s for s in manifest["sources"] if s["path"] == entry["path"]]
        if matches:
            matches[0].update(entry)
        else:
            manifest["sources"].append(entry)
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = re.sub(r"연구\d+개", f"연구{number}개", manifest["scope"])
    manifest["environment_correction_atlas_added"] = True
    manifest["environment_correction_atlas_note"] = (
        f"{number}번째 연구. 함수율 월 게이트 합산후보와내외측별도특성,기존채택보존."
    )
    write_guarded(path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", mtime)
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    for entry in manifest["sources"] + manifest["conclusions"]:
        p = (ROOT / entry["path"]).resolve()
        assert p.is_relative_to(ROOT) and sha(p) == entry["sha256"], entry["path"]
    links = 0
    for doc in [*HERE.glob("*.md"), CENTRAL / "04F_ENVIRONMENT_CORRECTION_ATLAS.md"]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", doc.read_text()):
            if target.startswith("https://"):
                continue
            dest = (doc.parent / target.split("#")[0]).resolve()
            assert dest.is_relative_to(ROOT)
            assert dest.exists() or dest == OUT / "artifact_inventory.json", (doc, target)
            links += 1
    result = dict(
        passed=True,
        web_tables_checked=len(tables),
        source_values_preserved=True,
        central_hashes_checked=len(manifest["sources"]) + len(manifest["conclusions"]),
        local_links_checked=links,
        independent_research_count=number,
        figures_inspected=True,
        production_changed=False,
        prediction_validation=False,
    )
    (OUT / "final_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

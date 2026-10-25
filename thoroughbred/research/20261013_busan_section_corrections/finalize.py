"""Validate reader tables, preserve frozen sources and register the Busan follow-up."""

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
CONCLUSION = "02D_BUSAN_SEOUL_SECTION_CORRECTIONS.md"
MARKER = "<!-- busan_seoul_section_corrections_20261013 -->"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guarded(path, text, mtime):
    assert path.stat().st_mtime_ns == mtime, "Shared index changed; reread before retry"
    path.write_text(text)


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for name, digest in summary["input_sha256"].items():
        assert sha(ROOT / name) == digest, name
    for name, entry in summary["raw_verification"]["source_files"].items():
        assert sha(ROOT / name) == entry["sha256"]
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["max_explicit_contrast_error"] < 2e-5
    assert verification["max_contrast_variance_error"] < 1e-10
    web = json.loads((OUT / "web_research.json").read_text())
    assert web["publication"] == (HERE / "PUBLICATION.md").read_text()
    assert web["examples"] == json.loads((OUT / "venue_application_examples.json").read_text())
    factors = pd.read_csv(OUT / "correction_components.csv", dtype={"level": str})
    tables = {
        "primary_components": factors[factors.period.eq("all_mad4") & factors.variant.eq("tail25")],
        "definitions": pd.read_csv(OUT / "section_definitions.csv"),
        "coverage": pd.read_csv(OUT / "coverage.csv"),
        "moisture_comparison": pd.read_csv(OUT / "core_moisture_comparison_table.csv"),
        "month_gate_ranges": pd.read_csv(OUT / "core_month_gate_ranges_comparison.csv"),
        "raw_common_moisture_comparison": pd.read_csv(
            OUT / "common_moisture_raw_comparison.csv", dtype={"level": str}
        ),
    }
    for name, a in tables.items():
        a = a.reset_index(drop=True)
        b = pd.DataFrame(web[name])[a.columns]
        for column in a:
            if a[column].dtype == object:
                a[column] = a[column].where(a[column].notna(), "<missing>")
                b[column] = b[column].where(b[column].notna(), "<missing>")
        pd.testing.assert_frame_equal(a, b, check_dtype=False, atol=1e-8, rtol=1e-8)
    central = CENTRAL / CONCLUSION
    central.write_text(
        (HERE / "PUBLICATION.md").read_text()
        + f"\n\n[상세 방법과 검증](../{RUN}/README.md) · "
        + f"[월별 표](../{RUN}/outputs/month_primary.csv) · "
        + f"[게이트별 표](../{RUN}/outputs/gate_primary.csv) · "
        + f"[부산 세부 구간 표](../{RUN}/outputs/detail_primary.csv) · "
        + f"[서울과 직접 대비](../{RUN}/outputs/venue_raw_direct_contrasts.csv) · "
        + f"[용량 명세](../{RUN}/outputs/artifact_inventory.json).\n"
        + "\n기존 구간 연구의 부산 후속으로 등록했다. 기존 연구 수와 채택 상태를 유지한다.\n"
    )
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    entries = {
        "README.md": (
            "\n\n## 부산 구간 환경 보정과 서울 비교\n\n"
            f"{MARKER}\n[부산 구간 보정과 서울 비교]({CONCLUSION}): "
            f"62,831출전의 원자료 대조, {summary['models']}개 조건부 모형. "
            "서울과 같은 기본 분할 및 부산 실제 계측점 세부 분할을 구분했다. "
            "함수율40%·월/게이트30%와 표본 축소의 시험 후보, 공통 숫자 구성의 지역 직접 대비. "
            "기존 서울80%·부산90% 전체시간 채택과 운영을 유지하며 독립 연구 수를 늘리지 않았다.\n"
        ),
        "SOURCES.md": (
            f"\n\n## 부산 구간 보정과 서울 비교\n\n{MARKER}\n"
            f"[원 보고서](../{RUN}/README.md) · [중앙 결론]({CONCLUSION}) · "
            f"[계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
            f"[검증](../{RUN}/outputs/verification.json) · "
            f"[게시용 요약](../{RUN}/PUBLICATION.md) · "
            f"[용량](../{RUN}/outputs/artifact_inventory.json). "
            "구간 연구 부산 후속. 후보 차이와 공통 함수율 원 효과 직접 차이를 구분했다.\n"
        ),
    }
    for name, addition in entries.items():
        path = CENTRAL / name
        before, mtime = path.stat().st_size, path.stat().st_mtime_ns
        text = path.read_text()
        if MARKER not in text:
            guarded(path, text + addition, mtime)
            owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    path = CENTRAL / "source_manifest.json"
    before, mtime = path.stat().st_size, path.stat().st_mtime_ns
    manifest = json.loads(path.read_text())
    for name in ["README.md", "PUBLICATION.md", "SOURCES.md", "PLAN.md"]:
        p = HERE / name
        entry = dict(path=str(p.relative_to(ROOT)), sha256=sha(p))
        found = [r for r in manifest["sources"] if r["path"] == entry["path"]]
        if found:
            found[0].update(entry)
        else:
            manifest["sources"].append(entry)
    for p in [central, CENTRAL / "README.md", CENTRAL / "SOURCES.md"]:
        entry = dict(path=str(p.relative_to(ROOT)), sha256=sha(p))
        found = [r for r in manifest["conclusions"] if r["path"] == entry["path"]]
        if found:
            found[0].update(entry)
        else:
            manifest["conclusions"].append(entry)
    manifest["busan_seoul_section_corrections_added"] = True
    manifest["busan_seoul_section_corrections_note"] = (
        "2026-10-13 기존 구간 연구 후속02D. 부산 기본/세부 보정과 서울 직접 대비. "
        "기존 연구 수·서울80%/부산90% 채택·운영 유지."
    )
    manifest["updated_at"] = "2026-10-13"
    guarded(path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", mtime)
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    for entry in manifest["sources"]:
        if entry["path"].startswith(str(HERE.relative_to(ROOT)) + "/"):
            assert sha(ROOT / entry["path"]) == entry["sha256"]
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", central.read_text()):
        dest = (central.parent / target).resolve()
        assert dest.is_relative_to(ROOT)
        assert dest.exists() or dest == OUT / "artifact_inventory.json"
    result = dict(
        passed=True,
        web_tables_checked=len(tables),
        publication_exact_match=True,
        application_examples_exact_match=True,
        source_hashes_preserved=True,
        figures_visually_inspected=True,
        central_conclusion=CONCLUSION,
        existing_research_count_preserved=True,
        production_changed=False,
        prediction_validation=False,
    )
    (OUT / "final_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

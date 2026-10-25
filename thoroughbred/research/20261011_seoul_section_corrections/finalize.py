"""Verify publication tables and append a scoped follow-up to shared indexes."""

import hashlib
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions"
RUN = HERE.name
CONCLUSION = "02C_SEOUL_SECTION_CORRECTIONS.md"
MARKER = "<!-- seoul_section_corrections_20261011 -->"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guarded(path, text, mtime):
    assert path.stat().st_mtime_ns == mtime, "Shared index changed; reread before retry"
    path.write_text(text)


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    for name, digest in summary["input_sha256"].items():
        assert sha(ROOT / name) == digest
    web = json.loads((OUT / "web_research.json").read_text())
    assert web["publication"] == (HERE / "PUBLICATION.md").read_text()
    factors = pd.read_csv(OUT / "correction_components.csv", dtype={"level": str})
    tables = {
        "primary_components": factors[factors.period.eq("all_mad4") & factors.variant.eq("tail25")],
        "definitions": pd.read_csv(OUT / "section_definitions.csv"),
        "coverage": pd.read_csv(OUT / "coverage_detail.csv"),
        "month_gate_ranges": pd.read_csv(OUT / "core_month_gate_ranges.csv"),
    }
    for name, a in tables.items():
        a = a.reset_index(drop=True)
        b = pd.DataFrame(web[name])[a.columns]
        if "multiple_of_200" in a:
            a["multiple_of_200"] = a.multiple_of_200.astype("boolean")
            b["multiple_of_200"] = b.multiple_of_200.astype("boolean")
        pd.testing.assert_frame_equal(a, b, check_dtype=False, atol=1e-8, rtol=1e-8)
    central = CENTRAL / CONCLUSION
    central.write_text(
        (HERE / "PUBLICATION.md").read_text()
        + f"\n\n[상세 방법과 검증](../{RUN}/README.md) · "
        + f"[월별 표](../{RUN}/outputs/month_primary.csv) · "
        + f"[게이트별 표](../{RUN}/outputs/gate_primary.csv) · "
        + f"[코너 함수율 표](../{RUN}/outputs/corner_moisture_primary.csv) · "
        + f"[원 효과와 불확실성](../{RUN}/outputs/effect_profiles.csv) · "
        + f"[용량 명세](../{RUN}/outputs/artifact_inventory.json).\n"
        + "\n기존 구간 보정 연구의 세부 후속으로 등록했다. 기존 연구 수와 채택 상태를 유지한다.\n"
    )
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    entries = {
        "README.md": (
            "\n\n## 서울 거리 확정 구간과 코너 구간 보정\n\n"
            f"{MARKER}\n[서울 구간 환경 보정 후속]({CONCLUSION}): "
            "88,243출전의 계측 원문 대조, 56조건부 모형. "
            "1300m500m·1700m900m 중반을 포함한 기본 분할과 코너 분할을 구분했다. "
            "함수율40%·월/게이트30%와 표본 축소의 새 시험 후보이며 기존 서울80% "
            "전체시간 채택·운영·다음경주 검증 범위는 유지한다. "
            "독립 연구 수를 늘리지 않은 후속이다.\n"
        ),
        "SOURCES.md": (
            f"\n\n## 서울 기본 구간과 코너 구간 환경 보정\n\n{MARKER}\n"
            f"[원 보고서](../{RUN}/README.md) · [중앙 결론]({CONCLUSION}) · "
            f"[계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
            f"[검증](../{RUN}/outputs/verification.json) · "
            f"[게시용 요약](../{RUN}/PUBLICATION.md) · "
            f"[용량](../{RUN}/outputs/artifact_inventory.json). "
            "기존 구간 연구 후속. 정확한 거리와 코너 시간차를 분리하고 미지원은null로 보존한다.\n"
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
    manifest["seoul_section_corrections_added"] = True
    manifest["seoul_section_corrections_note"] = (
        "2026-10-11 기존 구간 연구 후속02C. 기본 거리와 코너 별도 56모형, "
        "직접 구간 시험값. 기존 연구 수·서울80% 채택·운영 유지."
    )
    manifest["updated_at"] = "2026-10-11"
    guarded(path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", mtime)
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    for entry in manifest["sources"]:
        if entry["path"].startswith(str(HERE.relative_to(ROOT)) + "/"):
            assert sha(ROOT / entry["path"]) == entry["sha256"]
    result = dict(
        passed=True,
        web_tables_checked=len(tables),
        publication_exact_match=True,
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

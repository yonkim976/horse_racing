"""Validate historical application publication and register a scoped follow-up."""

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
CONCLUSION = "02E_HISTORICAL_SECTION_APPLICATION.md"
MARKER = "<!-- historical_section_application_20261015 -->"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guarded(path, text, mtime):
    assert path.stat().st_mtime_ns == mtime, "Shared index changed; reread before retry"
    path.write_text(text)


def main():
    application = json.loads((OUT / "application_summary.json").read_text())
    for name, digest in application["input_sha256"].items():
        assert sha(ROOT / name) == digest, name
    assert json.loads((OUT / "verification.json").read_text())["passed"]
    web = json.loads((OUT / "web_research.json").read_text())
    assert web["publication"] == (HERE / "PUBLICATION.md").read_text()
    checks = {
        "coverage": "coverage.csv",
        "horse_best_summary": "horse_best_summary.csv",
        "within_race_summary": "within_race_time_order_summary.csv",
        "alternate_summary": "alternate_before_after_summary.csv",
    }
    for key, file in checks.items():
        a = pd.read_csv(OUT / file)
        b = pd.DataFrame(web[key])[a.columns]
        pd.testing.assert_frame_equal(a, b, check_dtype=False, atol=1e-8, rtol=1e-8)
    central = CENTRAL / CONCLUSION
    central.write_text(
        (HERE / "PUBLICATION.md").read_text() + f"\n\n[상세 방법](../{RUN}/README.md) · "
        f"[기본 원장](../{RUN}/outputs/core_historical_records.parquet) · "
        f"[코너 및 세부 원장](../{RUN}/outputs/alternate_historical_records.parquet) · "
        f"[개별 사례](../{RUN}/outputs/record_examples.csv) · "
        f"[말별 최고기록 변경](../{RUN}/outputs/changed_horse_examples.csv) · "
        f"[검증](../{RUN}/outputs/verification.json) · "
        f"[용량](../{RUN}/outputs/artifact_inventory.json).\n\n"
        "기존 구간 보정 연구의 적용 후속이며 새로운 계수 채택이나 예측 검증은 아니다.\n"
    )
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    additions = {
        "README.md": (
            f"\n\n## 과거 출전기록 구간 보정 적용\n\n{MARKER}\n"
            f"[보정 전후 적용 결과]({CONCLUSION}):151,074출전 조회,138,934출전 완전 적용. "
            "전체기록 평균 절대변화 서울0.072초·부산0.055초,말×거리 최고기록 선택 변경 "
            "서울2.12%·부산1.37%. 기본/세부 원장과 부분/완전 보정을 구분했다. "
            "기존 후보의 후향 적용이며 새 추정·운영 변경·예측 검증은 없다. 독립 연구 수 유지.\n"
        ),
        "SOURCES.md": (
            f"\n\n## 과거 출전기록 구간 보정 적용\n\n{MARKER}\n"
            f"[원 보고서](../{RUN}/README.md) · [중앙 결론]({CONCLUSION}) · "
            f"[계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
            f"[게시 요약](../{RUN}/PUBLICATION.md) · [검증](../{RUN}/outputs/verification.json) · "
            f"[용량](../{RUN}/outputs/artifact_inventory.json). "
            "원기록 유지·후향 적용·예측 검증 별도.\n"
        ),
    }
    for name, addition in additions.items():
        path = CENTRAL / name
        before, mtime = path.stat().st_size, path.stat().st_mtime_ns
        text = path.read_text()
        if MARKER not in text:
            guarded(path, text + addition, mtime)
            owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    path = CENTRAL / "source_manifest.json"
    before, mtime = path.stat().st_size, path.stat().st_mtime_ns
    manifest = json.loads(path.read_text())
    for group, paths in [
        ("sources", [HERE / n for n in ["README.md", "PUBLICATION.md", "SOURCES.md", "PLAN.md"]]),
        ("conclusions", [central, CENTRAL / "README.md", CENTRAL / "SOURCES.md"]),
    ]:
        for p in paths:
            entry = dict(path=str(p.relative_to(ROOT)), sha256=sha(p))
            found = [r for r in manifest[group] if r["path"] == entry["path"]]
            if found:
                found[0].update(entry)
            else:
                manifest[group].append(entry)
    manifest["historical_section_application_added"] = True
    manifest["historical_section_application_note"] = (
        "2026-10-15 기존 구간 연구 적용 후속02E.151,074출전 조회,138,934완전 적용. "
        "원기록/운영/기존 채택/연구 수 유지,예측 검증 아님."
    )
    manifest["updated_at"] = "2026-10-15"
    guarded(path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", mtime)
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", central.read_text()):
        dest = (central.parent / target).resolve()
        assert dest.is_relative_to(ROOT)
        assert dest.exists() or dest == OUT / "artifact_inventory.json"
    (OUT / "final_verification.json").write_text(
        json.dumps(
            dict(
                passed=True,
                source_values_and_hashes_preserved=True,
                publication_matches=True,
                web_tables_checked=len(checks),
                figures_visually_inspected=True,
                existing_research_count_preserved=True,
                production_changed=False,
                prediction_validation=False,
            ),
            indent=2,
        )
        + "\n"
    )
    print("Historical application publication verified and registered")


if __name__ == "__main__":
    main()

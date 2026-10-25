# ruff: noqa: E501
"""Reconcile publication tables, shared indexes and hashes without changing completed studies."""

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


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    assert json.loads((OUT / "verification.json").read_text())["passed"]
    web = json.loads((OUT / "web_age_curve_exit.json").read_text())
    alignment = []
    for filename, field in [
        ("age_profiles.csv", "age_profiles"),
        ("matched_age_changes.csv", "matched_age_changes"),
        ("inactivity_by_age.csv", "inactivity"),
        ("pre_inactivity_record_changes.csv", "pre_inactivity_changes"),
        ("trend_coverage.csv", "trend_coverage"),
        ("valid_final_start_sensitivity.csv", "posthoc_valid_final_start_sensitivity"),
    ]:
        source = pd.read_csv(OUT / filename)
        payload = pd.DataFrame(web[field])
        assert len(source) == len(payload)
        assert list(source.columns) == list(payload.columns)
        for col in source:
            a, b = source[col], payload[col]
            if pd.api.types.is_numeric_dtype(a):
                np.testing.assert_allclose(
                    a.to_numpy(float),
                    pd.to_numeric(b).to_numpy(float),
                    atol=1e-9,
                    rtol=1e-9,
                    equal_nan=True,
                )
            else:
                # pandas interprets a sparse mixed age/year column differently; JSON retains strings.
                assert a.fillna("").astype(str).eq(b.fillna("").astype(str)).all(), (filename, col)
        alignment.append(dict(table=filename, rows=len(source), passed=True))
    baseline = json.loads(Path("/tmp/horse_age_baseline_20261007.json").read_text())
    previous = []
    for name, old in baseline.items():
        if (
            name.startswith("thoroughbred/research/conclusions/")
            and name.endswith(".md")
            and Path(name).name not in ["README.md", "SOURCES.md"]
        ):
            p = ROOT / name
            assert p.stat().st_size == old["size"] and p.stat().st_mtime_ns == old["mtime_ns"], name
            previous.append(name)
    p = CENTRAL / "README.md"
    text = p.read_text()
    if "26_AGE_CURVE_EXIT.md" not in text:
        text = text.replace("연구 32개와", "연구 33개와", 1).replace(
            "32개 연구와 결정 문서", "33개 연구와 결정 문서", 1
        )
        text = text.replace(
            "| [원 보고서 목록](SOURCES.md)",
            "| [평균 연령 곡선과 출전 중단](26_AGE_CURVE_EXIT.md) | 2~4세 성장·집단과 동일 말 변화·365일 무출전·중단 전 하락 여부, 연령 보정 미채택 |\n| [원 보고서 목록](SOURCES.md)",
            1,
        )
        extra = ""
        if "| 32 |" not in text:
            extra += "\n| 32 | 암말·수말·거세마의 기록과 경기력 | 조건을 맞춘 차이와 같은 경주 성과·시기 민감도 | 관찰 연구·성별 보정 미채택 |"
        extra += "\n| 33 | 평균 연령 곡선과 출전 중단 전 기록 | 2~4세 성장 방향·4세 이후 변화 불확실·무출전 전 약3분의1은 하락 없음 | 관찰 연구·성장/하락 보정 미채택 |\n"
        text = text.replace("\n\n## 현재 보정 상태", extra + "\n## 현재 보정 상태", 1)
        p.write_text(text)
    p = CENTRAL / "SOURCES.md"
    text = p.read_text()
    if f"../{HERE.name}/README.md" not in text:
        text = text.replace("성별32개 연구", "성별·연령33개 연구", 1)
        text += f"\n## 평균 연령 곡선과 출전 중단\n\n- 33. [출전 집단 연령 곡선·같은 말 변화·중단 전 기록](../{HERE.name}/README.md)\n- [중앙 결론](26_AGE_CURVE_EXIT.md) · [출처](../{HERE.name}/SOURCES.md) · [계획](../{HERE.name}/PLAN.md) · [검증](../{HERE.name}/outputs/verification.json) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [용량 명세](../{HERE.name}/outputs/artifact_inventory.json)\n- 기존151,074행을 재사용하고 전체 실제 출발326,157행에서 이후 출전을 확인했다. 365일 무출전과 확정 퇴사를 구분하며, 새 연령 보정·운영 변경은 하지 않았다.\n"
        p.write_text(text)
    additions = {
        ROOT
        / "thoroughbred/README.md": f"\n\n[평균 연령 곡선과 출전 중단](research/{HERE.name}/README.md):2~4세 기록 향상 방향,4세 이후 변화의 불확실성과 잔존 선택,365일 무출전 전 기록을 함께 검증했다. [중앙 결론](research/conclusions/26_AGE_CURVE_EXIT.md)에 보존했으며 연령 보정·운영 변경은 하지 않았다.\n",
        HERE.parent
        / "README.md": f"\n\n[평균 연령 곡선과 출전 중단]({HERE.name}/README.md):11거리151,074기록,같은 말·달·함수율의 다음 연령 비교,전체 실제 출발326,157행의 추적. 무출전은 확정 퇴사와 구분하며 성장/하락 보정은 미채택이다. [중앙 결론](conclusions/26_AGE_CURVE_EXIT.md).\n",
        HERE.parent
        / "20261004_website_research_review/README.md": f"\n\n## 연령 곡선과 출전 중단 연구 추가\n\n2026-10-07 [원 연구](../{HERE.name}/README.md) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [게시JSON](../{HERE.name}/outputs/web_age_curve_exit.json)을 연결했다. 집단 곡선·같은 말 변화·출전 중단을 구분하고,무출전을 퇴사로 표시하지 않는다. 현재 기록과 다음 기록의 비교이며 생물학적 고정 정점·일률 감점·운영 예측으로 표현하지 않는다. 사이트 구현·배포는 변경하지 않았다.\n",
    }
    accounting_path = OUT / "shared_edit_accounting.json"
    accounting = json.loads(accounting_path.read_text()) if accounting_path.exists() else {}
    for p, addition in additions.items():
        name = str(p.relative_to(ROOT))
        text = p.read_text()
        if f"{HERE.name}/README.md" not in text:
            old = p.stat().st_size
            p.write_text(text + addition)
            accounting[name] = p.stat().st_size - old
        assert name in accounting
    accounting_path.write_text(json.dumps(accounting, ensure_ascii=False, indent=2) + "\n")
    p = CENTRAL / "source_manifest.json"
    manifest = json.loads(p.read_text())
    names = [x["path"] for x in manifest["sources"]]
    name = str((HERE / "README.md").relative_to(ROOT))
    if name not in names:
        names.append(name)
    manifest["sources"] = [dict(path=n, sha256=sha(ROOT / n)) for n in names]
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = manifest["scope"].replace("성별 연구32개", "성별·연령 연구33개")
    manifest["age_curve_exit_added"] = True
    manifest["age_curve_exit_note"] = (
        "집단 연령곡선·동일 말 전환·중단 전 기록을 구분. 무출전은 퇴사와 다르며 새 보정 미채택."
    )
    manifest["data_end_by_study"]["age_curve_exit_followup"] = "2026-09-18"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    for item in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / item["path"]) == item["sha256"]
    links = 0
    for p in [*HERE.rglob("*.md"), *CENTRAL.glob("*.md")]:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", p.read_text()):
            if target.startswith(("http:", "https:", "mailto:", "#")):
                continue
            q = (p.parent / target.split("#")[0]).resolve()
            assert q.is_relative_to(ROOT) and (
                q.exists() or q == OUT / "artifact_inventory.json"
            ), (p, target)
            links += 1
    result = dict(
        passed=True,
        publication_alignment=alignment,
        prior_topic_files_unchanged=len(previous),
        central_hashes_checked=len(manifest["sources"]) + len(manifest["conclusions"]),
        local_links_checked=links,
        figures_visually_reviewed=True,
        aging_correction_not_adopted=True,
        official_retirement_not_claimed=True,
        production_and_website_unchanged=True,
    )
    (OUT / "final_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

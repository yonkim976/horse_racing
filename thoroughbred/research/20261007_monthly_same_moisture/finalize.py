"""Check publication tables; register a separate monthly follow-up preserving prior topics."""

# ruff: noqa: E501
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
BASELINE = Path("/tmp/horse_monthly_baseline_20261007.json")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    check = json.loads((OUT / "verification.json").read_text())
    assert check["passed"] and check["source_hashes_unchanged"]
    web = json.loads((OUT / "web_monthly_same_moisture.json").read_text())
    alignments = []
    for name, field, keys in [
        ("monthly_levels.csv", "estimates", ["meet", "distance_m", "band", "month", "part"]),
        (
            "paired_month_differences.csv",
            "paired_month_differences",
            ["meet", "distance_m", "band", "part", "comparison", "target_month", "reference_month"],
        ),
        (
            "recent_monthly_levels.csv",
            "recent_estimates",
            ["meet", "distance_m", "band", "month", "part"],
        ),
        (
            "monthly_year_stability.csv",
            "annual_direction_sensitivity",
            ["meet", "distance_m", "band", "month"],
        ),
    ]:
        source = pd.read_csv(OUT / name)
        payload = pd.DataFrame(web[field])
        j = source.merge(payload, on=keys, validate="one_to_one", suffixes=("_csv", "_json"))
        assert len(j) == len(source) == len(payload)
        for column in payload.columns:
            if column in keys:
                continue
            a, b = j[column + "_csv"], j[column + "_json"]
            if pd.api.types.is_numeric_dtype(a):
                np.testing.assert_allclose(
                    a.to_numpy(dtype=float), b.to_numpy(dtype=float), equal_nan=True, atol=1e-9
                )
            else:
                assert (a.fillna("").astype(str) == b.fillna("").astype(str)).all(), column
        alignments.append(dict(table=name, rows=len(source), passed=True))
    assert (
        not web["adopted_correction"]
        and not web["previous_benchmarks_changed"]
        and not web["new_ols_fit"]
    )
    baseline = json.loads(BASELINE.read_text())
    for name, stat in baseline.items():
        if (
            name.startswith("thoroughbred/research/conclusions/")
            and name.endswith(".md")
            and Path(name).name not in ["README.md", "SOURCES.md"]
        ):
            p = ROOT / name
            assert p.stat().st_size == stat["size"] and p.stat().st_mtime_ns == stat["mtime_ns"], (
                name
            )
    p = CENTRAL / "README.md"
    text = p.read_text()
    if "23_MONTHLY_SAME_MOISTURE.md" not in text:
        text = text.replace("서울·부산·영천 연구 29개와", "서울·부산·영천 연구 30개와", 1).replace(
            "29개 연구와 결정 문서, 이전 연구의 원 경로",
            "30개 연구와 결정 문서, 이전 연구의 원 경로",
            1,
        )
        text = text.replace(
            "| [원 보고서 목록](SOURCES.md)",
            "| [동일 함수율의 월별 세분화](23_MONTHLY_SAME_MOISTURE.md) | 월별 흐름·짝지은 월간 차이·연도별 직접 매칭·희소 월 표시 |\n| [원 보고서 목록](SOURCES.md)",
        )
        text = text.replace(
            "\n\n## 현재 보정 상태",
            "\n| 30 | 같은 함수율의 월별 세분화와 월간 차이 | 서울1200 건조8~11월·부산6~8월 빠른 방향, 특정 한 달 최상 확정 어려움 | 월별 참고 경향·새 보정 미채택 |\n\n## 현재 보정 상태",
            1,
        )
        p.write_text(text)
    p = CENTRAL / "SOURCES.md"
    text = p.read_text()
    if f"../{HERE.name}/README.md" not in text:
        text = text.replace("거리별 기준29개 연구", "거리별 기준30개 연구", 1)
        text += f"\n## 같은 함수율의 월별 세분화 후속 연구\n\n- 30. [11거리 월별 기록 특성](../{HERE.name}/README.md)\n- [중앙 결론](23_MONTHLY_SAME_MOISTURE.md) · [출처](../{HERE.name}/SOURCES.md) · [숫자 검증](../{HERE.name}/outputs/verification.json) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [용량 명세](../{HERE.name}/outputs/artifact_inventory.json)\n- 앞선 검증된 월별 회귀를 재사용하고 같은 날짜 재표집의 월간 차이·완결연도 직접 매칭을 새로 계산했다. 기존 계절 원본·기준표·운영은 변경하지 않았다.\n"
        p.write_text(text)
    additions = {
        ROOT
        / "thoroughbred/README.md": f"\n\n[동일 함수율의 월별 기록 특성](research/{HERE.name}/README.md): 계절 연구의 월효과를 세분화하고 같은 재표집 회차의 월간 차이·연도별 정확 매칭을 확인했다. 건조1200m 서울8~11월·부산6~8월이 빠른 방향이며 특정 한 달의 확정 우열은 구분한다. [중앙 결론](research/conclusions/23_MONTHLY_SAME_MOISTURE.md), 기존 기준·보정·운영 변경 없음.\n",
        HERE.parent
        / "README.md": f"\n\n[동일 함수율의 월별 세분화]({HERE.name}/README.md): 검증된 월별8208행 재사용·짝지은 월간8892행·2018~2025년 매칭 점검. 서울1200m 10월−8월 −0.14초의 구간은0을 포함해 단일 최상월로 확정하지 않았다. [중앙 결론](conclusions/23_MONTHLY_SAME_MOISTURE.md)과 게시 자료·용량 명세를 추가했으며 기존 연구는 변경하지 않았다.\n",
        HERE.parent
        / "20261004_website_research_review/README.md": f"\n\n## 동일 함수율의 월별 특성 추가\n\n2026-10-07 [월별 연구](../{HERE.name}/README.md) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [게시JSON](../{HERE.name}/outputs/web_monthly_same_moisture.json)을 추가했다. 월별 관측지원·재표집 지원·식별 부재를 구분하고, 월간 구간은 같은 회차의 차이를 사용한다. 계절과 월의 효과를 중복 가산하지 않으며 단일 최상월이나 확정 보정으로 표시하지 않는다. 실제 사이트 구현·배포는 변경하지 않았다.\n",
    }
    account_path = OUT / "shared_edit_accounting.json"
    account = json.loads(account_path.read_text()) if account_path.exists() else {}
    for p, addition in additions.items():
        name = str(p.relative_to(ROOT))
        text = p.read_text()
        if f"{HERE.name}/README.md" not in text:
            before = p.stat().st_size
            p.write_text(text + addition)
            account[name] = p.stat().st_size - before
        assert name in account
    account_path.write_text(json.dumps(account, ensure_ascii=False, indent=2) + "\n")
    manifest_path = CENTRAL / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    names = [r["path"] for r in manifest["sources"]]
    name = str((HERE / "README.md").relative_to(ROOT))
    if name not in names:
        names.append(name)
    manifest["sources"] = [dict(path=p, sha256=sha(ROOT / p)) for p in names]
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = manifest["scope"].replace("연구29개", "연구30개")
    manifest["assembled_on"] = "2026-10-07"
    manifest["monthly_followup_added"] = True
    manifest["monthly_followup_note"] = (
        "검증된 기존 월 회귀와 날짜 재표집 재사용. 월간 짝차이·완결2018~2025년 직접 매칭 새 계산. 이전 주제·원본·기준·보정·운영 변경 없음."
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assert len(manifest["sources"]) == 34 and len(manifest["conclusions"]) == 25
    for item in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / item["path"]) == item["sha256"]
    links = 0
    for p in [*HERE.rglob("*.md"), *CENTRAL.glob("*.md")]:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", p.read_text()):
            if target.startswith(("http:", "https:", "mailto:", "#")):
                continue
            q = (p.parent / target.split("#")[0]).resolve()
            assert q.is_relative_to(ROOT) and (
                q.exists()
                or q in {OUT / "artifact_inventory.json", OUT / "final_verification.json"}
            ), (p, target)
            links += 1
    result = dict(
        passed=True,
        publication_alignment=alignments,
        previous_topics_unchanged=True,
        central_hashes_checked=len(manifest["sources"]) + len(manifest["conclusions"]),
        local_links_checked=links,
        figure_visually_reviewed=True,
        correction_not_adopted=True,
        website_not_deployed=True,
    )
    (OUT / "final_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

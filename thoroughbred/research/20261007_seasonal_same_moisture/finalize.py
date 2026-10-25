"""Verify seasonal publication data, preserve prior topics and update shared study indexes."""

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
BASELINE = Path("/tmp/horse_seasonal_baseline_20261007.json")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    check = json.loads((OUT / "verification.json").read_text())
    assert check["passed"] and check["inputs_unchanged"]
    web = json.loads((OUT / "web_seasonal_same_moisture.json").read_text())
    estimates = pd.read_csv(OUT / "controlled_month_season_contrasts.csv", dtype={"label": str})
    payload = pd.DataFrame(web["estimates"])
    keys = ["period", "mode", "controls", "meet", "distance_m", "band", "kind", "label", "part"]
    joined = estimates.merge(payload, on=keys, validate="one_to_one", suffixes=("_csv", "_web"))
    assert len(joined) == len(estimates) == 10260
    for field in ["difference", "ci_low", "ci_high", "informative_races", "bootstrap_valid_n"]:
        assert np.allclose(
            joined[field + "_csv"],
            joined[field + "_web"].to_numpy(dtype=float),
            equal_nan=True,
            atol=1e-8,
            rtol=1e-10,
        ), field
    assert not web["adopted_correction"] and not web["previous_benchmarks_changed"]
    # Treat observational support and uncertainty support as different fields.
    unsupported = estimates.status.isin(["not_identifiable", "no_within_stratum_month_overlap"])
    assert estimates.loc[unsupported, "difference"].isna().all()
    assert (
        estimates.loc[estimates.bootstrap_valid_n.lt(180), ["ci_low", "ci_high"]].isna().all().all()
    )
    before = json.loads(BASELINE.read_text())
    for name, stat in before.items():
        if (
            name.startswith("thoroughbred/research/conclusions/")
            and name.endswith(".md")
            and Path(name).name not in ["README.md", "SOURCES.md"]
        ):
            p = ROOT / name
            assert p.stat().st_size == stat["size"] and p.stat().st_mtime_ns == stat["mtime_ns"], (
                name
            )
    # Idempotent, topic-specific insertions; keep independently appended project links.
    p = CENTRAL / "README.md"
    text = (
        p.read_text()
        .replace("2026년 10월 6일 기준.", "2026년 10월 7일 기준.", 1)
        .replace("서울·부산·영천 연구 28개와", "서울·부산·영천 연구 29개와", 1)
        .replace(
            "28개 연구와 결정 문서, 이전 연구의 원 경로",
            "29개 연구와 결정 문서, 이전 연구의 원 경로",
        )
    )
    if "22_SEASONAL_SAME_MOISTURE.md" not in text:
        text = text.replace(
            "| [원 보고서 목록](SOURCES.md)",
            "| [동일 함수율의 월별·계절별 경향](22_SEASONAL_SAME_MOISTURE.md) | 같은 연도·등급·함수율 숫자의 비교, 건조1200/1400 여름 경향·희소 상태 |\n| [원 보고서 목록](SOURCES.md)",
        )
        text = text.replace(
            "\n\n## 현재 보정 상태",
            "\n| 29 | 같은 함수율의 월별·계절별 기록 경향 | 11거리151,074출전기록·13,928경주, 건조1200/1400 여름 빠른 방향·기간별 크기 변화 | 계절 연관 보존·새 보정 미채택 |\n\n## 현재 보정 상태",
        )
        text += f"\n\n## 동일 주로상태의 계절 연구\n\n2026-10-07 [같은 연도·등급·함수율 숫자의 월별·계절별 비교](../{HERE.name}/README.md)를 추가했다. 겨울 대비 여름의 건조1200m 차이는 서울 약−0.46초·부산−0.60초다. 포화·불량과 희소 장거리는 같은 결론을 적용할 근거가 부족하다. 날짜 재표집·완결된 최근2년·연도별 매칭을 보존했고, 기존 월 통제와 중복될 수 있어 새 계절 보정을 가산하지 않았다.\n"
    p.write_text(text)
    p = CENTRAL / "SOURCES.md"
    text = (
        p.read_text()
        .replace("2026년 10월 6일 갱신.", "2026년 10월 7일 갱신.", 1)
        .replace("거리별 기준28개 연구", "거리별 기준29개 연구", 1)
    )
    if f"../{HERE.name}/README.md" not in text:
        text += f"\n## 같은 함수율 숫자의 월별·계절별 기록 경향\n\n- 29. [11거리의 같은 연도·등급·함수율 숫자 비교](../{HERE.name}/README.md)\n- 이 폴더의 결론: [계절 경향과 새 보정 미채택](22_SEASONAL_SAME_MOISTURE.md)\n- [원천·방법](../{HERE.name}/SOURCES.md), [독립 검증](../{HERE.name}/outputs/verification.json), [게시 요약](../{HERE.name}/PUBLICATION.md), [산출물 용량](../{HERE.name}/outputs/artifact_inventory.json)\n"
    p.write_text(text)
    additions = {
        ROOT
        / "thoroughbred/README.md": f"\n\n[동일 함수율의 월별·계절별 기록 경향](research/{HERE.name}/README.md):11거리151,074출전기록·13,928경주에서 같은 연도·등급·함수율 숫자를 비교했다. 건조1200/1400에서 여름이 빠른 방향이 남지만 희소 상태·장거리·기간별 크기 변화를 구분한다. [중앙 결론](research/conclusions/22_SEASONAL_SAME_MOISTURE.md)을 추가했으며 새 계절 보정은 채택하지 않았다.\n",
        HERE.parent
        / "README.md": f"\n\n[같은 주로의 월별·계절별 기록 경향]({HERE.name}/README.md):기존11거리151,074행을 경주별 평균13,928경주로 집계해 같은 연도·등급·함수율 숫자의 계절 차이를 계산했다. 출전마 구성 통제·날짜 재표집200회·완결된2024/2025년·연도별 매칭을 보존했다. 건조1200/1400에서 여름이 빠른 방향이 남고 희소 상태/장거리는 비교 부재 또는 잠정이다. 기존 월 통제와 중복돼 새 보정 가산은 미채택이다. [중앙 결론](conclusions/22_SEASONAL_SAME_MOISTURE.md)과 게시 준비 자료를 보존했다.\n",
        HERE.parent
        / "20261004_website_research_review/README.md": f"\n\n## 동일 함수율의 계절별 경향 추가\n\n2026-10-07 [계절 연구](../{HERE.name}/README.md)·[게시 요약](../{HERE.name}/PUBLICATION.md)·[게시JSON](../{HERE.name}/outputs/web_seasonal_same_moisture.json)을 연결했다. 계절 차이는 동일 연도·등급·함수율 숫자를 통제한 경주평균 차이다. 표본 조건과 재표집 지원을 구분하고, 식별 부재는0으로 채우지 않으며95% 구간은 점별 구간이다. 기존 기준에 계절 보정을 자동 가산하거나 우승 예측 개선으로 표현하지 않는다. 실제 웹 구현·배포·운영 적용은 변경하지 않았다.\n",
    }
    account_path = OUT / "shared_edit_accounting.json"
    account = json.loads(account_path.read_text()) if account_path.exists() else {}
    for p, addition in additions.items():
        text = p.read_text()
        name = str(p.relative_to(ROOT))
        if f"{HERE.name}/README.md" not in text:
            old = p.stat().st_size
            p.write_text(text + addition)
            account[name] = p.stat().st_size - old
        assert name in account
    account_path.write_text(json.dumps(account, ensure_ascii=False, indent=2) + "\n")
    path = CENTRAL / "source_manifest.json"
    manifest = json.loads(path.read_text())
    names = [x["path"] for x in manifest["sources"]]
    name = str((HERE / "README.md").relative_to(ROOT))
    if name not in names:
        names.append(name)
    manifest["sources"] = [dict(path=p, sha256=sha(ROOT / p)) for p in names]
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = manifest["scope"].replace("연구28개", "연구29개")
    manifest["assembled_on"] = "2026-10-07"
    manifest["new_same_moisture_seasonal_analysis_added"] = True
    manifest["analysis_rerun_note"] = (
        "이전 완료 연구 재실행 없음. 기존11거리 최종 품질 모집단을 새 계절 연구에서 합쳐 같은 연도/등급/함수율 숫자의 월별·계절별 차이를 독립 계산·검증. 기존 기준표·보정 결정·운영은 변경하지 않음."
    )
    manifest["data_end_by_study"].update(seasonal_seoul="2026-09-20", seasonal_busan="2026-09-18")
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assert len(manifest["sources"]) == 33 and len(manifest["conclusions"]) == 24
    for record in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / record["path"]) == record["sha256"]
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
        created_on="2026-10-07",
        publication_rows=len(estimates),
        csv_json_alignment=True,
        prior_topic_conclusions_unchanged=True,
        central_hashes_checked=57,
        local_links_checked=links,
        correction_not_adopted=True,
        website_unchanged=True,
    )
    (OUT / "final_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

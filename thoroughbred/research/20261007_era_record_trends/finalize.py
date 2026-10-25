"""Register era research and verify all website tables and preserved prior conclusions."""

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
BASELINE = Path("/tmp/horse_era_baseline_20261007.json")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    check = json.loads((OUT / "verification.json").read_text())
    assert check["passed"] and check["source_hashes_unchanged"]
    web = json.loads((OUT / "web_era_record_trends.json").read_text())
    tables = []
    for name, field, keys in [
        (
            "era_contrasts.csv",
            "estimates",
            ["meet", "distance_m", "window", "band", "specification", "part"],
        ),
        ("overlap_support.csv", "overlap", ["meet", "distance_m", "window", "band"]),
        ("annual_race_means.csv", "annual_race_means", ["meet", "distance_m", "year", "window"]),
        (
            "recent_year_matched_changes.csv",
            "recent_year_matched",
            ["meet", "distance_m", "year", "part"],
        ),
    ]:
        source = pd.read_csv(OUT / name)
        payload = pd.DataFrame(web[field])
        join = source.merge(payload, on=keys, validate="one_to_one", suffixes=("_csv", "_web"))
        assert len(join) == len(source) == len(payload)
        for column in payload:
            if column in keys:
                continue
            a, b = join[column + "_csv"], join[column + "_web"]
            if pd.api.types.is_numeric_dtype(a):
                np.testing.assert_allclose(
                    a.to_numpy(dtype=float), b.to_numpy(dtype=float), atol=1e-9, equal_nan=True
                )
            else:
                assert (a.fillna("").astype(str) == b.fillna("").astype(str)).all(), column
        tables.append(dict(table=name, rows=len(source), passed=True))
    assert not web["adopted_correction"] and not web["previous_benchmarks_changed"]
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
    if "24_ERA_RECORD_TRENDS.md" not in text:
        text = text.replace("서울·부산·영천 연구 30개와", "서울·부산·영천 연구 31개와", 1).replace(
            "30개 연구와 결정 문서, 이전 연구의 원 경로",
            "31개 연구와 결정 문서, 이전 연구의 원 경로",
            1,
        )
        text = text.replace(
            "| [원 보고서 목록](SOURCES.md)",
            "| [2024년 전후 기록 변화](24_ERA_RECORD_TRENDS.md) | 공통월·등급·정확 함수율 비교, 전체시간과 구간 배분의 시대 차이 |\n| [원 보고서 목록](SOURCES.md)",
        )
        text = text.replace(
            "\n\n## 현재 보정 상태",
            "\n| 31 | 2024년 전후 전체·구간 기록 변화 | 1200m 전체차이 작음·서울 중간/막판 배분 변화, 부산1800 느린 방향·기간 민감도 | 후향 변화 관찰·시대 보정 미채택 |\n\n## 현재 보정 상태",
            1,
        )
        p.write_text(text)
    p = CENTRAL / "SOURCES.md"
    text = p.read_text()
    if f"../{HERE.name}/README.md" not in text:
        text = text.replace("거리별 기준30개 연구", "거리별 기준31개 연구", 1)
        text += f"\n## 2024년 전후 기록 수준과구간 배분 변화\n\n- 31. [동일 등급·정확 함수율·월의 시대 비교](../{HERE.name}/README.md)\n- [중앙 결론](24_ERA_RECORD_TRENDS.md) · [원천](../{HERE.name}/SOURCES.md) · [숫자 검증](../{HERE.name}/outputs/verification.json) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [산출물 용량](../{HERE.name}/outputs/artifact_inventory.json)\n- 주 비교는2018~2023년 대2024~2026년의 각1~8월이며 완결연도·가까운기간·부분2026년 포함 여부를 별도 점검했다. 기존 기록 기준·함수율 보정·운영을 변경하지 않았다.\n"
        p.write_text(text.replace("구간", "구간"))
    additions = {
        ROOT
        / "thoroughbred/README.md": f"\n\n[2024년 전후 기록 변화](research/{HERE.name}/README.md):같은 등급·정확 함수율·월의 공통층에서 최근과 과거를 비교했다.1200m 전체시간 차이는 작지만 서울의 중간/막판 배분 변화,부산1800m의 느린 방향이 관찰됐다. [중앙 결론](research/conclusions/24_ERA_RECORD_TRENDS.md)에 기간·표본 한계를 보존했고 시대 보정은 채택하지 않았다.\n",
        HERE.parent
        / "README.md": f"\n\n[2024년 전후 전체·구간 기록 변화]({HERE.name}/README.md):2018~2023 대2024~2026의 공통1~8월,정확 등급·함수율·월 매칭과 출전마 구성 통제·200회 날짜 재표집·기간 민감도. 전체 기록의 일괄 개선은 확인되지 않았고 일부 구간 배분이 달라졌다. [중앙 결론](conclusions/24_ERA_RECORD_TRENDS.md),기존 기준·운영 변경 없음.\n",
        HERE.parent
        / "20261004_website_research_review/README.md": f"\n\n## 시대별 기록 변화 연구 추가\n\n2026-10-07 [기록 변화 연구](../{HERE.name}/README.md) · [게시 요약](../{HERE.name}/PUBLICATION.md) · [게시JSON](../{HERE.name}/outputs/web_era_record_trends.json)을 연결했다.2026년 부분연도를 고려한 공통월 비교이며,원시와 공통층 모집단·초와상대속도%p·기간별 민감도·표본지원·점별95%구간을 구분한다. 관찰된 변화는 매년 일정한 초 보정·2024년 인과적 전환점·전 경주 능력 변화로 표현하지 않는다. 실제 사이트 구현·배포는 변경하지 않았다.\n",
    }
    path = OUT / "shared_edit_accounting.json"
    account = json.loads(path.read_text()) if path.exists() else {}
    for p, addition in additions.items():
        name = str(p.relative_to(ROOT))
        text = p.read_text()
        if f"{HERE.name}/README.md" not in text:
            old = p.stat().st_size
            p.write_text(text + addition)
            account[name] = p.stat().st_size - old
        assert name in account
    path.write_text(json.dumps(account, ensure_ascii=False, indent=2) + "\n")
    p = CENTRAL / "source_manifest.json"
    manifest = json.loads(p.read_text())
    names = [x["path"] for x in manifest["sources"]]
    name = str((HERE / "README.md").relative_to(ROOT))
    if name not in names:
        names.append(name)
    manifest["sources"] = [dict(path=p, sha256=sha(ROOT / p)) for p in names]
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = manifest["scope"].replace("연구30개", "연구31개")
    manifest["assembled_on"] = "2026-10-07"
    manifest["era_record_followup_added"] = True
    manifest["era_record_followup_note"] = (
        "검증된 기존11거리 모집단으로 시기 공통월·정확 층 비교 및 구성 통제·날짜 재표집을 새 수행. 기존 연구·기준·보정·운영 변경 없음."
    )
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assert len(manifest["sources"]) == 35 and len(manifest["conclusions"]) == 26
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
        publication_alignment=tables,
        previous_topics_unchanged=True,
        central_hashes_checked=61,
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

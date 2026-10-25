"""Verify prepared publication tables and register this independent local study."""

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


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert json.loads((OUT / "verification.json").read_text())["passed"]
    summary = json.loads((OUT / "summary.json").read_text())
    for path, digest in summary["input_sha256"].items():
        assert sha(ROOT / path) == digest, path
    payload = json.loads((OUT / "web_detached_tail_sensitivity.json").read_text())
    tables = {
        "distance_overview": "distance_overview.csv",
        "paired_changes": "paired_race_changes.csv",
        "moisture1200": "moisture1200_sensitivity.csv",
        "month_curve": "month_curve_sensitivity.csv",
        "gate1600": "gate1600_sensitivity.csv",
    }
    for key, name in tables.items():
        b = pd.DataFrame(payload[key])
        a = pd.read_csv(OUT / name, dtype={"level": str})
        for col in a:
            if pd.api.types.is_numeric_dtype(a[col]):
                b[col] = pd.to_numeric(b[col])
        pd.testing.assert_frame_equal(a, b, check_dtype=False, atol=1e-8, rtol=1e-8)
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    path = CENTRAL / "README.md"
    before = path.stat().st_size
    content = path.read_text()
    heading = "## 결승 이탈 후미를 제외한 기록 기준"
    if heading not in content:
        content = content.replace(
            "서울·부산·영천 연구 37개와 두 결정 문서", "서울·부산·영천 연구 38개와 두 결정 문서"
        )
        content = content.replace(
            "37개 연구와 결정 문서, 이전 연구의 원 경로",
            "38개 연구와 결정 문서, 이전 연구의 원 경로",
        )
        old_line = "| [구간기록 보정](02_SECTION_TIME.md)"
        lines = content.splitlines(keepends=True)
        index = next(i for i, line in enumerate(lines) if line.startswith(old_line))
        lines.insert(
            index + 1,
            "| [결승 이탈 후미 제외 기준](02B_DETACHED_TAIL_BASELINE.md) | "
            "중위권과 떨어진 말의 표식·평균 및 환경 효과 민감도·전체/정제 기준 병기 |\n",
        )
        index = next(
            i for i, line in enumerate(lines) if line.startswith("| 37 | 구간기록의 함수율")
        )
        lines.insert(
            index + 1,
            "| 38 | 결승 이탈 후미와 기록 기준 민감도 | "
            "기존4MAD 이후2.70% 추가 제외, 막판 평균 변화가 출발보다 큼 | "
            "전체 기준 보존·정제 기준 보조·보정표 변경 및 예측 검증 별도 |\n",
        )
        content = "".join(lines)
        content += (
            "\n\n" + heading + "\n\n"
            "[이탈 후미 민감도](02B_DETACHED_TAIL_BASELINE.md): "
            "38번째 연구. 완전한 명단151,115출전에서 선두·중위·경주 MAD 기준을 계산했다. "
            "기존4MAD 표본148,338출전 중4,012출전(2.70%)이 추가 표시됐다. "
            "서울/부산1200m 마지막200m 평균은 약0.041/0.046초 빨라졌고 출발 변화는 작았다. "
            "84모형으로 동일 조건 재추정 후 포화1200m의 초반 차이와 월별 막판 차이는 유지됐다. "
            "전체와 조건부 정제 기준을 함께 제공하고, "
            "실제 느린 경기 기록과 기존 보정표는 보존한다.\n"
        )
        path.write_text(content)
        owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    path = CENTRAL / "SOURCES.md"
    before = path.stat().st_size
    content = path.read_text()
    if heading not in content:
        content += (
            "\n\n" + heading + "\n\n"
            f"38번째 연구 [원 보고서](../{RUN}/README.md) · "
            "[중앙 결론](02B_DETACHED_TAIL_BASELINE.md) · "
            f"[계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
            f"[게시 요약](../{RUN}/PUBLICATION.md) · "
            f"[검증](../{RUN}/outputs/verification.json) · "
            f"[용량](../{RUN}/outputs/artifact_inventory.json). "
            "결승 이탈 표식의 회고적 민감도이며 "
            "원본 기록·운영 보정·다음 경주 검증은 변경하지 않았다.\n"
        )
        path.write_text(content)
        owned[str(path.relative_to(ROOT))] = path.stat().st_size - before
    path = CENTRAL / "source_manifest.json"
    before = path.stat().st_size
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
    manifest["scope"] = manifest["scope"].replace("연구37개", "연구38개")
    manifest["detached_tail_sensitivity_added"] = True
    manifest["detached_tail_sensitivity_note"] = (
        "38번째 연구. 전체/정제 조건부 기준 병기, 기존 보정표와 실제 기록 보존."
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    for entry in manifest["sources"] + manifest["conclusions"]:
        path = (ROOT / entry["path"]).resolve()
        assert path.is_relative_to(ROOT) and sha(path) == entry["sha256"], entry["path"]
    links = 0
    for doc in [*HERE.glob("*.md"), CENTRAL / "02B_DETACHED_TAIL_BASELINE.md"]:
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
        central_hashes_checked=len(manifest["sources"]) + len(manifest["conclusions"]),
        local_links_checked=links,
        independent_research_count=38,
        production_changed=False,
        prediction_validation=False,
    )
    (OUT / "final_verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

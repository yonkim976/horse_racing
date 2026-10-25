"""Link the new seconds-normalization study and check publication tables."""

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
    payload = json.loads((OUT / "web_record_normalization.json").read_text())
    tables = {
        "monthly_candidates": "monthly_candidate_table.csv",
        "all_candidates": "conservative_candidates.csv",
        "moisture_reference": "moisture_reference_preserved.csv",
    }
    for key, name in tables.items():
        a = pd.read_csv(OUT / name)
        b = pd.DataFrame(payload[key])
        # JSON object names are strings and mixed level labels remain strings.
        a.columns = a.columns.astype(str)
        b.columns = b.columns.astype(str)
        a = a.astype(object).where(a.notna(), float("nan"))
        b = b.astype(object).where(b.notna(), float("nan"))
        pd.testing.assert_frame_equal(a, b, check_dtype=False, atol=1e-9, rtol=1e-9)
    accounting = OUT / "shared_edit_accounting.json"
    owned = json.loads(accounting.read_text()) if accounting.exists() else {}
    readme = CENTRAL / "README.md"
    before = readme.stat().st_size
    text = readme.read_text()
    heading = "## 함수율 월 게이트의 초 단위 보정량 연구"
    if heading not in text:
        text = text.replace(
            "2026년 10월 7일 기준. 이번 대화에서 기존 주로환경 검증을 이어 진행한 "
            "서울·부산·영천 연구 33개와 두 결정 문서",
            "2026년 10월 8일 기준. 이번 대화에서 기존 주로환경 검증을 이어 진행한 "
            "서울·부산·영천 연구 34개와 두 결정 문서",
        )
        text = text.replace(
            "| [원 보고서 목록](SOURCES.md) | 33개 연구와 결정 문서, 이전 연구의 원 경로 |",
            "| [원 보고서 목록](SOURCES.md) | 34개 연구와 결정 문서, 이전 연구의 원 경로 |",
        )
        anchor = "| 33 | 평균 연령 곡선과 출전 중단 전 기록"
        lines = text.splitlines(keepends=True)
        matches = [i for i, line in enumerate(lines) if line.startswith(anchor)]
        assert len(matches) == 1
        lines.insert(
            matches[0] + 1,
            "| 34 | 함수율·월·게이트의 완주시간 보정량 | 같은 말·조건 통제와 "
            "이상치·기간 민감도 후 월 추가−0.11~+0.09초 후보. 게이트·실제 내외측 "
            "기본 적용 보류 | 후향 기록 비교용 후보·예측 검증 유보·미채택 |\n",
        )
        text = "".join(lines)
        text += (
            "\n\n" + heading + "\n\n"
            "[기록 보정량 후속 결론](04B_RECORD_NORMALIZATION_SECONDS.md): "
            "151,074출전을 연결해14지역×거리149,624출전·13,792경주에서64모형을 적합했다. "
            "기존 함수율 보정에 월별−0.11~+0.09초를 추가하는 보수적 후보를 만들었다. "
            "게이트 번호·그룹과 실제 내외측의 기본 추가 적용은 보류한다. "
            "34번째 독립 연구이며 예측 성능 검증은 사용자 요청에 따라 뒤로 두었다. "
            "기존 보정 채택 상태와 운영 모델은 유지한다.\n"
        )
        readme.write_text(text)
        owned[str(readme.relative_to(ROOT))] = readme.stat().st_size - before
    sources = CENTRAL / "SOURCES.md"
    before = sources.stat().st_size
    text = sources.read_text()
    heading = "## 완주시간의 함수율 월 게이트 보정량 연구"
    if heading not in text:
        text += (
            "\n\n" + heading + "\n\n"
            f"34번째 연구 [원 보고서](../{RUN}/README.md) · "
            "[중앙 결론](04B_RECORD_NORMALIZATION_SECONDS.md) · "
            f"[계획](../{RUN}/PLAN.md) · [출처](../{RUN}/SOURCES.md) · "
            f"[게시 요약](../{RUN}/PUBLICATION.md) · "
            f"[독립 검증](../{RUN}/outputs/verification.json) · "
            f"[용량](../{RUN}/outputs/artifact_inventory.json). "
            "기록 보정량 탐구이며 다음 경주 예측 검증과 새 보정 채택은 수행하지 않았다.\n"
        )
        sources.write_text(text)
        owned[str(sources.relative_to(ROOT))] = sources.stat().st_size - before
    path = CENTRAL / "source_manifest.json"
    before = path.stat().st_size
    manifest = json.loads(path.read_text())
    for filename in ["README.md", "SOURCES.md", "PUBLICATION.md"]:
        source = HERE / filename
        name = str(source.relative_to(ROOT))
        entry = {"path": name, "sha256": sha(source)}
        matches = [item for item in manifest["sources"] if item["path"] == name]
        if matches:
            matches[0].update(entry)
        else:
            manifest["sources"].append(entry)
    manifest["conclusions"] = [
        {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = manifest["scope"].replace("연구33개", "연구34개")
    manifest["assembled_on"] = "2026-10-08"
    manifest["record_normalization_seconds_added"] = True
    manifest["record_normalization_seconds_note"] = (
        "34번째 독립 연구. 완주시간의 함수율·월·게이트 추가량 후보 탐구. "
        "실제 내외측 추가 적용·다음 경주 예측 검증·새 보정 채택·운영 변경 없음."
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    owned.setdefault(str(path.relative_to(ROOT)), path.stat().st_size - before)
    accounting.write_text(json.dumps(owned, ensure_ascii=False, indent=2) + "\n")
    count = 0
    for item in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / item["path"]) == item["sha256"], item["path"]
        count += 1
    links = 0
    for p in [*HERE.glob("*.md"), CENTRAL / "04B_RECORD_NORMALIZATION_SECONDS.md"]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", p.read_text()):
            dest = (p.parent / target.split("#")[0]).resolve()
            assert dest.is_relative_to(ROOT)
            assert dest.exists() or dest == OUT / "artifact_inventory.json", (p, target)
            links += 1
    result = {
        "passed": True,
        "central_hashes_checked": count,
        "local_links_checked": links,
        "web_payload_tables_checked": len(tables),
        "independent_research_count": 34,
        "new_correction_adopted": False,
        "production_changed": False,
        "figures_visually_reviewed": 2,
    }
    (OUT / "final_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

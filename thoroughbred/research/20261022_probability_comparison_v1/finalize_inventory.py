"""Finalize local research indexes and a self-inclusive byte inventory.

Writes only this study, its new conclusion, and the five pre-recorded research
indexes. No training, database connection, network, commit, or publishing.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import report

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
ROOT = HERE.parents[2]
RESEARCH = HERE.parent
STUDY = HERE.name
MARKER = "probability_comparison_20261022"
INVENTORY = OUT / "artifact_inventory.json"
BEFORE = json.loads((OUT / "preexisting_files.json").read_text())


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def upsert(path, body):
    start = f"<!-- {MARKER}:start -->"
    end = f"<!-- {MARKER}:end -->"
    original = path.read_text(encoding="utf-8")
    block = f"{start}\n{body.rstrip()}\n{end}"
    if start in original:
        a = original.index(start)
        b = original.index(end, a) + len(end)
        updated = original[:a] + block + original[b:]
    else:
        expected = BEFORE[str(path.relative_to(ROOT))]["sha256"]
        assert sha(path) == expected, f"Unaccounted concurrent index edit: {path}"
        updated = original + "\n\n" + block + "\n"
    path.write_text(updated, encoding="utf-8")


def index_updates(summary):
    blurb = ("연구 full103 대비89개 후보 축60.47→61.28%(+39/4,799,95%+0.10~+1.58%p), "
             "복승3 −16경주로 전체 승식 개선은 미확인. 같은103의 전체쌍 복승3 정책은+58경주. "
             "새18모형·기존12재사용·시간순 검증·운영 미반영.")
    conclusion = report.CONCLUSION.name
    upsert(RESEARCH / "README.md", f"[연구58 더러브렛 축·복승·복연 확률 비교]({STUDY}/README.md): {blurb}")
    upsert(RESEARCH / "conclusions/README.md", f"[연구58 더러브렛 축·복승·복연 확률 비교]({conclusion}): {blurb}")
    upsert(RESEARCH / "conclusions/SOURCES.md",
        f"[연구58]({conclusion}) · [원 보고서](../{STUDY}/README.md) · "
        f"[사전계획](../{STUDY}/PLAN.md) · [승식 계약](../{STUDY}/TARGETS.md) · "
        f"[데이터 감사](../{STUDY}/audit_data.md) · [paired 구간](../{STUDY}/outputs/paired_differences.csv) · "
        f"[독립 검증](../{STUDY}/outputs/verification.json) · [정책 검증](../{STUDY}/outputs/policy_verification.json). "
        "기간2024-01-05~2026-09-20, 서울·부산4,799경주50,754출발행, 사전제한18개 신규모형. "
        "2024~2026 반복 개발자료·시점 미확정 카드·상위동착28경주 제외. " + blurb)
    upsert(RESEARCH / "ARTIFACT_SIZE_LOG.md",
        f"| 2026-10-22 | 더러브렛 축·복승·복연 공동확률 비교 | {summary['new_file_count']} | "
        f"{summary['new_bytes']} | {summary['new_bytes']/1048576:.6f} | {summary['modified_file_count']} | "
        f"{summary['modified_final_bytes']} | {summary['modified_delta_bytes']:+d} | "
        f"[명세]({STUDY}/outputs/artifact_inventory.json) |\n\n"
        f"최대 파일 `{summary['largest_file']['path']}` {summary['largest_file']['bytes']:,} bytes. "
        "용량 명세·검증·코드·신규 모델·최소 예측·보고서를 모두 포함한다. 원천DB/기존 모델 복사 없음, "
        "300,000,000 bytes 이하. 운영 예측 발행·DB 변경·웹 게시 없음.")


def manifest_update():
    path = RESEARCH / "conclusions/source_manifest.json"
    manifest = json.loads(path.read_text())
    sources = list(HERE.glob("*.md")) + list(HERE.glob("*.py")) + list(HERE.glob("*.json"))
    sources += [p for p in OUT.iterdir() if p.suffix in {".json", ".csv"} and p != INVENTORY]
    # Hash own model metadata too; binary/model files are verified by the frozen
    # input and per-fold manifests and are all counted in the byte inventory.
    sources += list((OUT / "models").glob("*/metadata.json"))
    for key, paths in [("sources", sources), ("conclusions", [report.CONCLUSION])]:
        indexes = {x["path"]: i for i, x in enumerate(manifest[key])}
        for item in sorted(paths):
            value = {"path": str(item.relative_to(ROOT)), "sha256": sha(item)}
            if value["path"] in indexes:
                manifest[key][indexes[value["path"]]] = value
            else:
                indexes[value["path"]] = len(manifest[key])
                manifest[key].append(value)
    manifest["data_end_by_study"][MARKER] = {
        "study": STUDY, "evaluation_start": "2024-01-05", "evaluation_end": "2026-09-20",
        "venues": ["Seoul", "Busan"], "races": 4799, "runner_rows": 50754,
        "new_final_models": 18, "reused_models": 12, "production_changed": False,
        "new_test_data": False, "general_improvement_confirmed": False,
    }
    manifest["probability_comparison_20261022_note"] = (
        "89 vs103 축+39경주/복승3−16: 축 후보 보존, 전체 개선 미확인. "
        "103 고정 전체쌍 복승3 정책+58. 연구58·사전제한실험·운영/DB/게시 변경 없음.")
    manifest["updated_at"] = "2026-10-22"
    save(path, manifest)


def completion_checks():
    inputs = json.loads((OUT / "input_manifest.json").read_text())
    for name, expected in inputs.items():
        path = ROOT / name
        assert path.stat().st_size == expected["bytes"] and sha(path) == expected["sha256"], name
    evaluation = json.loads((OUT / "evaluation_complete.json").read_text())
    assert sha(HERE / "evaluate.py") == evaluation["evaluation_code_sha256"]
    assert sha(HERE / "probability.py") == evaluation["probability_code_sha256"]
    verification = json.loads((OUT / "verification.json").read_text())
    policy = json.loads((OUT / "policy_verification.json").read_text())
    assert verification["status"] == policy["status"] == "passed"
    training = json.loads((OUT / "training_complete.json").read_text())
    assert training["new_final_models"] == 18 and training["reused_models"] == 12
    assert len(list((OUT / "models").glob("*/model.txt"))) == 18
    assert len(list((OUT / "models").glob("*/scores.parquet"))) == 30
    assert len(list((OUT / "calibration").glob("*.json"))) == 36
    flags_sha = sha(OUT / "population_flags.parquet")
    assert flags_sha == "008fb4b0447c38880cf490c7f6c88be8fc5435149fd41b1baa390cd75a7af26a"
    for name in ["audit_model.md", "audit_recent.md", "audit_data.md", "audit_data.json",
                 "audit_results.md", "policy_audit.md", "TARGETS.md"]:
        assert (HERE / name).stat().st_size > 0
    decisions = json.loads((OUT / "decision.json").read_text())
    assert not decisions["general_improvement_confirmed"]
    assert decisions["no_more_search"] and not decisions["production_comparison"]
    checks = {
        "status": "passed", "frozen_input_files_rehashed": len(inputs),
        "existing_production_registry_hash_unchanged": True,
        "evaluator_and_probability_code_match_verified_evaluation": True,
        "model_folds": 30, "new_final_models": 18, "reused_models": 12,
        "calibration_folds": 36, "population_flags_sha256": flags_sha,
        "independent_model_evaluation_verification": "passed",
        "independent_policy_verification": "passed",
        "all_six_completion_requirements_documented": True,
        "model_comparison": "Retrospective research full103; not operational A/B/C",
        "further_search_stopped": True,
        "scope_actions": {"database_writes": 0, "external_data_collection": 0,
                          "operational_prediction_publication": 0, "deployment": 0},
        "verification_sha256": sha(OUT / "verification.json"),
        "policy_verification_sha256": sha(OUT / "policy_verification.json"),
        "evaluation_sha256": sha(OUT / "evaluation_complete.json"),
        "metric_tables_sha256": {n: sha(OUT / n) for n in [
            "metrics.csv", "paired_differences.csv", "policy_comparison.csv",
            "unambiguous_metrics.csv", "calibration_summary.csv"]},
        "storage_check": "Exact final files and limits checked by artifact_inventory.json",
    }
    save(OUT / "completion_checks.json", checks)


def completion_doc(summary):
    text = f"""# 완수 조건 감사

2026-10-22. 사전 제한 실험과 해석을 완료했고 더 좋은 결과를 찾기 위한 추가 탐색을 중단했다. 축 연구 후보의 개선 신호는 남았으나 전체 승식 개선은 미확인이다.

| 사용자 완수 조건 | 결과 | 실제 근거 |
|---|---|---|
| 1. 목표·승식별 정답/확률/평가 문서화 | 완료 | [TARGETS](TARGETS.md): 공동 순서3두 분포, 복연 union/적중수 구분, 연승 규칙 미확정 시 보류 |
| 2. 현행 연구 모델 기준 재현 비교 | 완료 | [모델 감사](audit_model.md), 저장 F모형6개·A모형6개 재사용, [독립 재추론](outputs/verification.json) 점수차0 |
| 3. 사전 제한 가설 검증 | 완료 | [동결계획](PLAN.md), E/L/EL 신규18개·FP교정6회, [입력 해시](outputs/input_manifest.json), 추가 탐색 없음 |
| 4. 연도별 결과·불확실성 판단 | 완료 | 4,799경주 같은 키, 날짜paired2,000회95%구간, [결과표](outputs/metrics.csv), [paired 차이](outputs/paired_differences.csv) |
| 5. 유지·제외·미검증 정리 | 완료 | [보고서](README.md): EL89/종반·선택정책 후보 유지, FP채택 제외, 전향/운영비교/연승·동착/수익성 미검증 |
| 6. 코드·설정·최소 결과 보존 | 완료 | [환경](outputs/environment.json), 코드·모델·교정·압축 결과, [파일명세](outputs/artifact_inventory.json) |

전체 출발자/완주 조건부를 분리하고 취소·실격·DNF·상위동착28경주·미해결3행을 [데이터 감사](audit_data.md)에 기록했다. 연도·지역·거리·등급 및 회복/상실 원표를 제공했다. 과거 공개시각 미확정과 반복 사용 평가기간 한계를 명시했다.

독립 감사는 데이터, 기존 모델/재추론, 최근 연구/결과 해석으로 나누어 GPT-6-luna xhigh 최대3명 설정을 유지했다. [정책 검증](outputs/policy_verification.json)은 복승3의+58경주와bootstrap구간을 별도로 재현했다. 학습을 다시 수행하는 검증은 하지 않았으므로 조기종료 반복수 선택은 코드·메타데이터 기반 확인이라는 한계가 남는다.

동률 비교 오류는 학습·교정을 바꾸지 않고 수치정렬만 수정했으며 [수정 기록](outputs/implementation_repairs.json)을 보존했다. 해당 수정 후 확률8개·평가3개 테스트와 독립평가가 통과했다.

운영 registry와 원 모델의 해시는 동결 입력과 일치한다. 운영 교체·예측 게시·운영 DB 변경·외부 신규 수집·웹 배포는 수행하지 않았다. 기존 연구와 사용자 파일은 삭제하지 않았다. 결과용 연구문서5개에 이번 연구의 새 항목만 추가하고 중앙 출처해시를 갱신했다.

신규 {summary['new_file_count']:,}파일, {summary['new_bytes']:,} bytes ({summary['new_bytes']/1048576:.6f} MiB). 기존 수정 {summary['modified_file_count']}파일, 순증감 {summary['modified_delta_bytes']:+,} bytes. 최대 파일 {summary['largest_file']['bytes']:,} bytes. 전체300,000,000·단일100,000,000 bytes 상한을 모두 충족한다. [최종 기계 검증](outputs/completion_checks.json)과 용량명세가 실제 보존파일을 기준으로 한다.
"""
    (HERE / "COMPLETION_AUDIT.md").write_text(text, encoding="utf-8")


def inventory():
    paths = [p for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    paths.append(report.CONCLUSION)
    assert all(not p.is_symlink() for p in paths)
    files = [{"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size} for p in sorted(paths)]
    modified = []
    for name, before in BEFORE.items():
        p = ROOT / name
        modified.append({"path": name, "bytes_before": before["bytes"], "bytes_after": p.stat().st_size,
            "delta_bytes": p.stat().st_size - before["bytes"],
            "sha256_before": before["sha256"], "sha256_after": sha(p)})
    summary = {"new_file_count": len(files), "new_bytes": sum(x["bytes"] for x in files),
        "largest_file": max(files, key=lambda x: x["bytes"]), "modified_file_count": len(modified),
        "modified_final_bytes": sum(x["bytes_after"] for x in modified),
        "modified_delta_bytes": sum(x["delta_bytes"] for x in modified)}
    assert summary["new_bytes"] <= 300_000_000
    assert summary["largest_file"]["bytes"] < 100_000_000
    return {"study": STUDY, "date_kst": "2026-10-22", "status": "complete",
        "unit": "logical bytes; MiB = bytes / 1048576", "summary": summary,
        "new_files": files, "modified_existing_files": modified,
        "limits": {"all_new_retained_bytes": 300_000_000, "individual_new_file_bytes": 100_000_000},
        "exclusions": ["Existing databases, source features, and reused models; no copies created",
                       "Transient Python bytecode caches, removed from this study before final delivery"],
        "self_inclusive": True}


def links_check():
    checked = 0
    for p in [HERE / "README.md", HERE / "PUBLICATION.md", HERE / "COMPLETION_AUDIT.md",
              HERE / "TARGETS.md", report.CONCLUSION]:
        for link in re.findall(r"\]\(([^)]+)\)", p.read_text()):
            if "://" in link or link.startswith("#"):
                continue
            target = p.parent / link.split("#", 1)[0]
            assert target.exists(), (str(p), link)
            checked += 1
    return checked


def main():
    completion_checks()
    if not INVENTORY.exists():
        save(INVENTORY, {})
    # report and completion files must exist for the first complete enumeration.
    if not (HERE / "COMPLETION_AUDIT.md").exists():
        (HERE / "COMPLETION_AUDIT.md").write_text("Pending final inventory.\n")
    summary = inventory()["summary"]
    for attempt in range(20):
        report.render(summary)
        completion_doc(summary)
        index_updates(summary)
        manifest_update()
        before_save = inventory()
        save(INVENTORY, before_save)
        after_save = inventory()
        if before_save == after_save and summary == after_save["summary"]:
            break
        summary = after_save["summary"]
    else:
        raise RuntimeError("Self-inclusive inventory did not converge")
    assert json.loads(INVENTORY.read_text()) == inventory()
    count = links_check()
    manifest = json.loads((RESEARCH / "conclusions/source_manifest.json").read_text())
    own = [e for key in ["sources", "conclusions"] for e in manifest[key]
           if STUDY in e["path"] or e["path"] == str(report.CONCLUSION.relative_to(ROOT))]
    assert all(sha(ROOT / e["path"]) == e["sha256"] for e in own)
    print(json.dumps({"status": "passed", **summary, "checked_report_links": count,
                      "checked_central_hashes": len(own), "inventory_iterations": attempt + 1}, ensure_ascii=False))


if __name__ == "__main__":
    main()

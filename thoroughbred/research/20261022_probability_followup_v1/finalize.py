"""Local-only documentation, final checks, and self-inclusive artifact bytes."""
from __future__ import annotations
import json
import re

import common as c
import render_report as report

MARKER="probability_followup_20261022"
RESEARCH=c.HERE.parent
INVENTORY=c.OUT/"artifact_inventory.json"
BEFORE=json.loads((c.OUT/"preexisting_files.json").read_text())
OLD_INVENTORY=json.loads((c.BASE/"outputs/artifact_inventory.json").read_text())


def direct_save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def upsert(path,body):
    start=f"<!-- {MARKER}:start -->";end=f"<!-- {MARKER}:end -->"
    old=path.read_text(encoding="utf-8")
    block=f"{start}\n{body.rstrip()}\n{end}"
    if start in old:
        a=old.index(start);b=old.index(end,a)+len(end)
        new=old[:a]+block+old[b:]
    else:
        assert c.sha(path)==BEFORE[str(path.relative_to(c.ROOT))]["sha256"],f"Concurrent change: {path}"
        new=old+"\n\n"+block+"\n"
    path.write_text(new,encoding="utf-8")


def indexes(summary):
    study=c.HERE.name
    text=("EL89의 축·복연을 고정한 새 89열 Top2 head는 복승 1조합 +3경주·3조합 +7경주이나 95/99% 구간이 0을 포함. "
          "확률 혼합 2개·순서 교차·Top2 2계열의 5개 안 모두 개선 판정 실패. 새 모형 6개 중 5개가 학습 200회 상한에서 최적. "
          "학습 상한·조건부 3착 직접 학습·입력 봉인을 다음 우선순위로 기록. 운영 유지.")
    upsert(RESEARCH/"README.md",f"[연구58A 확률 혼합·복승 목표 분리]({study}/README.md): {text}")
    upsert(RESEARCH/"conclusions/README.md",f"[연구58A 확률 혼합·복승 목표 분리]({report.CONCLUSION.name}): {text}")
    upsert(RESEARCH/"conclusions/SOURCES.md",f"[연구58A]({report.CONCLUSION.name}) · "
        f"[원보고서](../{study}/README.md) · [사전계획](../{study}/PLAN.md) · [paired구간](../{study}/outputs/paired_differences.csv) · "
        f"[독립검증](../{study}/outputs/verification.json) · [새자료감사](../{study}/audit_fresh_data.md) · "
        f"[다음 실험](../{study}/NEXT_EXPERIMENT.md). {text} 기간 2024-01-05~2026-09-20, 4,799경주·50,754출발행, 반복 사용한 자료의 후향 탐색.")
    upsert(RESEARCH/"ARTIFACT_SIZE_LOG.md",f"| 2026-10-22 | 확률 혼합·복승 목표 분리 후속 | {summary['new_file_count']} | "
        f"{summary['new_bytes']} | {summary['new_bytes']/1048576:.6f} | {summary['modified_file_count']} | "
        f"{summary['modified_final_bytes']} | {summary['modified_delta_bytes']:+d} | "
        f"[명세]({study}/outputs/artifact_inventory.json) |\n\n"
        f"최대 `{summary['largest_file']['path']}` {summary['largest_file']['bytes']:,} bytes. "
        f"연구58과 신규 보관 파일 합계 {summary['combined_new_bytes']:,} bytes, 300MB 이내. "
        "신규 모형 6개·기존 18개 재사용. 원천 복사·DB 쓰기·운영 게시 없음.")


def update_sources():
    path=RESEARCH/"conclusions/source_manifest.json"
    manifest=json.loads(path.read_text())
    if MARKER not in manifest["data_end_by_study"]:
        assert c.sha(path)==BEFORE[str(path.relative_to(c.ROOT))]["sha256"],f"Concurrent change: {path}"
    files=list(c.HERE.glob("*.md"))+list(c.HERE.glob("*.py"))+list(c.HERE.glob("*.json"))
    files += [p for p in c.OUT.iterdir() if p.suffix in {".json",".csv"} and p!=INVENTORY]
    files += list((c.OUT/"models").glob("*/metadata.json"))
    for key,paths in [("sources",files),("conclusions",[report.CONCLUSION])]:
        lookup={x["path"]:i for i,x in enumerate(manifest[key])}
        for p in sorted(paths):
            value={"path":str(p.relative_to(c.ROOT)),"sha256":c.sha(p)}
            if value["path"] in lookup:
                manifest[key][lookup[value["path"]]]=value
            else:
                lookup[value["path"]]=len(manifest[key]);manifest[key].append(value)
    manifest["data_end_by_study"][MARKER]={"study":c.HERE.name,"evaluation_start":"2024-01-05",
        "evaluation_end":"2026-09-20","venues":["Seoul","Busan"],"races":4799,"runner_rows":50754,
        "new_final_models":6,"reused_top2_models":6,"reused_top3_models":12,
        "new_variants":5,"improvement_confirmed":False,"production_changed":False,"new_independent_test":False}
    manifest["probability_followup_20261022_note"]="Top2 전문화 복승 1조합 +3경주·3조합 +7경주 개선 미확정. 5개 안 종료. 학습 상한·조건부 목표·시점 봉인을 후속으로 제안. 운영 미반영."
    manifest["updated_at"]="2026-10-22"
    direct_save(path,manifest)


def checks():
    c.check_inputs()
    verification=json.loads((c.OUT/"verification.json").read_text())
    assert verification["status"]=="passed"
    training=json.loads((c.OUT/"training_complete.json").read_text())
    assert training["new_final_models"]==6
    assert len(list((c.OUT/"models").glob("*/model.txt")))==6
    assert len(list((c.OUT/"models").glob("*/scores.parquet")))==12
    assert len(list((c.OUT/"calibration").glob("*.json")))==6
    evaluation=json.loads((c.OUT/"evaluation_complete.json").read_text())
    assert evaluation["study_sha256"]==c.sha(c.HERE/"study.py")
    assert evaluation["heads_sha256"]==c.sha(c.HERE/"heads.py")
    decision=json.loads((c.OUT/"decision.json").read_text())
    assert len(decision["candidates"])==5
    assert not any(x["general_improvement_vs_f"] or x["quinella_specialization_vs_el"] for x in decision["candidates"])
    for name in ["audit_prior.md","audit_results.md","audit_fresh_data.md","audit_fresh_data.json","NEXT_EXPERIMENT.md"]:
        assert (c.HERE/name).stat().st_size>0
    value={"status":"passed","frozen_files_rehashed":len(json.loads((c.OUT/"input_manifest.json").read_text())),
        "new_final_models":6,"new_variants":5,"independent_verification":"passed",
        "evaluator_code_matches_frozen_run":True,"original_operational_registry_hash_matches":True,
        "further_search_stopped":True,"new_independent_test_data":False,
        "scope_actions":{"db_writes":0,"external_race_data_collection":0,"production_model_replacement":0,
                         "prediction_publication":0,"deployment":0},
        "verification_sha256":c.sha(c.OUT/"verification.json"),
        "output_hashes":{name:c.sha(c.OUT/name) for name in ["metrics.csv","paired_differences.csv",
            "calibration_summary.csv","decision.json","training_diagnostics.csv","evaluation_complete.json"]},
        "unit_test_cases":5,"storage":"Exact logical bytes and self-inclusive file list in artifact_inventory.json"}
    c.save(c.OUT/"completion_checks.json",value)


def audit(summary):
    text=f"""# 후속 작업 완료 감사

2026-10-22. 사용자 요청 ‘모델을 더 개선시킬 방법을 찾아봐’에 따라 선행 연구·시점 자료를 감사하고, 다섯 방법을 고정해 제한 실험을 완료했다. 기존 과거 평가를 보고 만든 후속 탐색임을 표시했다.

| 확인 항목 | 실제 산출물·판정 |
|---|---|
| 기존 방법과 중복·차이 확인 | audit_prior.md: 기존 pair·Top2·관계 특성 추가의 한계와 새로운 조건부 확률 분해 구분 |
| 사전 가설·예산·중단 고정 | PLAN.md/config.json, 입력 100파일 동결, 신규 모형 6개·12회 학습·후속 출력 5개 |
| 같은 모집단·추천 예산 | 4,799경주·50,754출발행, 기존 F/EL 참조, 각 승식 1조합·3조합 |
| 일관된 확률·누수 검사 | heads.py, 경주 그룹·과거 교정, 축·복연 보존, 독립 verification.json, 단위 테스트 5개 통과 |
| 성능·불확실성·조건별 진단 | metrics/paired/gain_loss/calibration/민감도, 95% 구간과 5개 주 비교의 99% 구간 |
| 판단과 후속 방향 | 5개 안 모두 개선 판정 실패. Top2_89의 소폭 양의 차이는 불확실. 학습 상한·조건부 3착·ranking 우선순위 |
| 새 기간의 실제 가용성 | audit_fresh_data.md/json: 추가 사후 결과와 경기 전 16개 아카이브 구분, 후보 feature 계약 불일치 |
| 재현과 범위 | 신규 모형 6개·12개 head 점수 분할. 원천·기존 모형 복사 없음. 운영·DB·예측 게시 변경 없음 |

기존 연구58의 코드·모델·결과를 바꾸지 않았다. 중앙 연구문서 5개에 새 연구58A 항목과 출처를 추가했다. 학습 상한 확장·직접 조건부 3착·ranking은 다음 실험 제안이며 실행하지 않았다.

신규 {summary['new_file_count']:,}파일, {summary['new_bytes']:,} bytes ({summary['new_bytes']/1048576:.6f} MiB). 기존 수정 5파일, 최종 {summary['modified_final_bytes']:,} bytes, 순증감 {summary['modified_delta_bytes']:+,} bytes. 최대 파일 {summary['largest_file']['bytes']:,} bytes. 연구58과 신규 파일 합계 {summary['combined_new_bytes']:,} bytes로 300MB 이내이며 이번 신규 100MB 목표도 충족했다.

[보고서](README.md) · [다음 실험](NEXT_EXPERIMENT.md) · [기계적 완료점검](outputs/completion_checks.json) · [전체 명세](outputs/artifact_inventory.json).
"""
    (c.HERE/"COMPLETION_AUDIT.md").write_text(text,encoding="utf-8")


def inventory():
    paths=[p for p in c.HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts]+[report.CONCLUSION]
    assert all(not p.is_symlink() for p in paths)
    files=[{"path":str(p.relative_to(c.ROOT)),"bytes":p.stat().st_size} for p in sorted(paths)]
    changes=[]
    for name,old in BEFORE.items():
        path=c.ROOT/name
        changes.append({"path":name,"bytes_before":old["bytes"],"bytes_after":path.stat().st_size,
            "delta_bytes":path.stat().st_size-old["bytes"],"sha256_before":old["sha256"],"sha256_after":c.sha(path)})
    own=sum(x["bytes"] for x in files)
    summary={"new_file_count":len(files),"new_bytes":own,"largest_file":max(files,key=lambda x:x["bytes"]),
        "modified_file_count":len(changes),"modified_final_bytes":sum(x["bytes_after"] for x in changes),
        "modified_delta_bytes":sum(x["delta_bytes"] for x in changes),
        "previous_study_new_bytes":OLD_INVENTORY["summary"]["new_bytes"],
        "combined_new_bytes":own+OLD_INVENTORY["summary"]["new_bytes"]}
    assert own<100_000_000 and summary["combined_new_bytes"]<300_000_000
    assert summary["largest_file"]["bytes"]<100_000_000
    return {"study":c.HERE.name,"date_kst":"2026-10-22","status":"complete","summary":summary,
        "new_files":files,"modified_existing_files":changes,"self_inclusive":True,
        "units":"logical file bytes; MiB=bytes/1048576",
        "excluded":"Existing DB/source/model references and transient bytecode; no old source/model copies retained"}


def links_check():
    count=0
    for p in [c.HERE/"README.md",c.HERE/"PUBLICATION.md",c.HERE/"NEXT_EXPERIMENT.md",c.HERE/"COMPLETION_AUDIT.md",report.CONCLUSION]:
        for link in re.findall(r"\]\(([^)]+)\)",p.read_text()):
            if "://" in link or link.startswith("#"):
                continue
            target=p.parent/link.split("#",1)[0]
            assert target.exists(),(str(p),link)
            count+=1
    return count


def main():
    checks()
    if not INVENTORY.exists():
        c.save(INVENTORY,{})
    if not (c.HERE/"COMPLETION_AUDIT.md").exists():
        (c.HERE/"COMPLETION_AUDIT.md").write_text("Finalization pending.\n")
    summary=inventory()["summary"]
    for attempt in range(20):
        report.render(summary);audit(summary);indexes(summary);update_sources()
        current=inventory();c.save(INVENTORY,current);after=inventory()
        if current==after and summary==after["summary"]:
            break
        summary=after["summary"]
    else:
        raise RuntimeError("Inventory failed to stabilize")
    assert json.loads(INVENTORY.read_text())==inventory()
    links=links_check()
    manifest=json.loads((RESEARCH/"conclusions/source_manifest.json").read_text())
    own=[x for key in ["sources","conclusions"] for x in manifest[key]
        if c.HERE.name in x["path"] or x["path"]==str(report.CONCLUSION.relative_to(c.ROOT))]
    assert all(c.sha(c.ROOT/x["path"])==x["sha256"] for x in own)
    print(json.dumps({"status":"passed",**summary,"local_links_checked":links,"source_hashes_checked":len(own)},ensure_ascii=False))


if __name__=="__main__":
    main()

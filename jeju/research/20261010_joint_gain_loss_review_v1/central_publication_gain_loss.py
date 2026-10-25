#!/usr/bin/env python3
"""Fail-closed staging/publication for the approved topic-19 follow-up.

Preview is local to this review folder. Central writes require an explicit
root approval token and an unchanged prepublication snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "jeju/research/20261010_joint_gain_loss_review_v1"
STUDY = ROOT / "jeju/research/20261010_joint_gain_loss_v1"
CENTRAL = ROOT / "jeju/research/conclusions"
SNAP = HERE / "outputs/central_snapshot_prepublication_gain_loss_20261010"
STAGING = HERE / "outputs/central_publication_preview_gain_loss"
SNAP_RECEIPT = SNAP / "snapshot_receipt.json"
REVIEW_RECEIPT = HERE / "outputs/independent_supplemental_verification_receipt.json"
CORE_RECEIPT = HERE / "outputs/independent_analysis_output_receipt.json"
ROOT_SUPERVISORY = STUDY / "ROOT_SUPERVISORY_REVIEW.json"
APPROVAL_TOKEN = "ROOT_APPROVES_GAIN_LOSS_TOPIC19_APPEND"

FILES = {
    "README.md": "jeju/research/conclusions/README.md",
    "SOURCES.md": "jeju/research/conclusions/SOURCES.md",
    "research_register.json": "jeju/research/conclusions/research_register.json",
    "source_manifest.json": "jeju/research/conclusions/source_manifest.json",
    "19_JOINT_RELATIONSHIP.md": "jeju/research/conclusions/19_JOINT_RELATIONSHIP.md",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def jread(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def jbytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def require_final_inputs():
    assert REVIEW_RECEIPT.is_file() and CORE_RECEIPT.is_file()
    assert jread(REVIEW_RECEIPT)["status"] == "PASS"
    assert jread(CORE_RECEIPT)["status"] == "PASS"
    assert ROOT_SUPERVISORY.is_file()
    assert jread(ROOT_SUPERVISORY)["status"] == "PASS_supervisory_review_for_retrospective_publication_only"
    manifest = STUDY / "ARTIFACT_MANIFEST.json"
    assert manifest.is_file(), "wait for A's frozen ARTIFACT_MANIFEST.json"
    m = jread(manifest)
    # A's manifest must bind its final README and the corrected, feature-labeled table.
    local = m.get("artifacts", m.get("local_files", m.get("files", [])))
    paths = {x.get("path", "").removeprefix("jeju/research/20261010_joint_gain_loss_v1/") for x in local}
    assert "README.md" in paths
    assert "outputs_followup_addendum/actual_top3_context_summary_corrected_v2.csv" in paths
    assert sha(STUDY / "README.md") == next(x["sha256"] for x in local if x.get("path", "").endswith("/README.md") or x.get("path") == "README.md")
    return manifest


def snapshot_bytes():
    receipt = jread(SNAP_RECEIPT)
    assert receipt["status"] == "PASS" and receipt["central_files_modified"] is False
    expected = {Path(x["snapshot_path"]).name: x["sha256"] for x in receipt["files"]}
    assert set(expected) == set(FILES)
    data = {}
    for name in FILES:
        p = SNAP / name
        assert sha(p) == expected[name], f"snapshot bytes changed: {name}"
        data[name] = p.read_bytes()
    return receipt, data


def prepare() -> tuple[dict[str, bytes], dict]:
    manifest_path = require_final_inputs()
    snap_receipt, raw = snapshot_bytes()
    result = {k: v.decode("utf-8") for k, v in raw.items()}
    topic = result["19_JOINT_RELATIONSHIP.md"]
    assert "## gained/lost 후속 진단 (2026-10-10)" not in topic
    topic += """

## gained/lost 후속 진단 (2026-10-10)

동일한 1,779개 후향 경주에서 baseline hit 407건과 candidate hit 423건의 차이는 +16건(+0.90%p)이었지만, 날짜 단위 95% 구간 [−0.11, +1.90]%p가 0을 포함해 원 성능 gate는 계속 실패다. 50 gained·34 lost·373 both-hit·1,322 both-miss이며, 무순서 top-six 집합은 1,077경주에서 달랐다. 이는 별도 holdout 검증이 아니다.

조건별 원시 차이는 하나의 안정된 규칙을 보이지 않았다. 거리별 net은 1000m 508경주에서 −1, 1110m 482경주에서 +7, 1200m 262경주에서 +5, 1300m 63경주에서 +5였다. 연도별 전체 net도 2024년 −3, 2025년 +15, 2026년 9월 19일까지 +4로 달랐다. 연도×거리 및 연도×수분 교차표는 전체 분모를 나누는 기술표이며, 조건 선택이나 효과 확증에 쓰지 않는다. 84개 gained/lost는 결과를 확인한 뒤 선택한 사후 집합이다.

true-set과 경계 경쟁 조합의 항별 에너지 차이는 행별 대수 분해로 재현된다. gained/lost 그룹에서 baseline 점수 차와 관계항 차의 평균 방향은 반대였지만, 이는 결과로 나눈 표본의 상관된 11개 항 분해이며 인과 기여나 support-count 정보 품질을 증명하지 않는다. 다음 검증 가설은 미관측 기간에서 style-mean 3항과 support-count 3항을 고정 ablation/shrinkage로 비교하고, 거리별 규칙 대신 충분한 지원의 연도×거리 구성을 pooled/shrunken 방식으로 시험하는 것이다. 같은 이벤트 체중·수분 등은 예측 시점 가용성이 확인되지 않은 사후 context다. 운영 모델, 확률, DB, fitting은 변경하지 않았다.

세부 결과와 수정 표는 [후속 분석 README](../20261010_joint_gain_loss_v1/README.md), [feature/unit이 명시된 실제 Top3 표](../20261010_joint_gain_loss_v1/outputs_followup_addendum/actual_top3_context_summary_corrected_v2.csv), [A 고정 manifest](../20261010_joint_gain_loss_v1/ARTIFACT_MANIFEST.json), [독립 보충 검토](../20261010_joint_gain_loss_review_v1/outputs/independent_supplemental_verification_receipt.json)를 따른다. 최초 오류 `all_1779` 표와 feature 이름이 빠진 첫 정정표는 보존되었으나 superseded 상태이며 해석에 사용하지 않는다.
"""
    result["19_JOINT_RELATIONSHIP.md"] = topic

    readme = result["README.md"]
    oldrow = "| [F1_STYLE6 공동 입상관계와 최대 6조합 비교](19_JOINT_RELATIONSHIP.md) | 기존 말 점수는 고정하고 관계항을 더한 후향 비교. 6조합 적중 점추정은 상승했지만 날짜 구간이 0을 포함하고 집합 NLL gate도 실패 | 독립 재구성 PASS; 연구 신호 gate 실패, 운영 미반영 |"
    newrow = "| [F1_STYLE6 공동 입상관계와 최대 6조합 비교](19_JOINT_RELATIONSHIP.md) | 기존 말 점수 고정 관계항 후향 비교와 gained/lost 조건·경계 진단. 연도·거리별 방향은 불안정하고 사후집합/사후 context의 적용 규칙은 미확인 | 원 성능 gate 실패 유지; 독립 진단 PASS, 운영 미반영 |"
    assert readme.count(oldrow) == 1
    result["README.md"] = readme.replace(oldrow, newrow)

    sources = result["SOURCES.md"]
    marker = "- [20261010_joint_relationship_v1]"
    assert sources.count(marker) == 1 and "20261010_joint_gain_loss_v1" not in sources
    sources += "\n- 후속 진단 [20261010_joint_gain_loss_v1](../20261010_joint_gain_loss_v1/README.md): 동일 후향 코호트의 84 gained/lost 사후 분석, 11항 true-set 대 boundary 분해, 결과-side context exact join, 연도×거리/수분 교차표. 17,412 API key·1,779 race 직접 재집계 PASS. original gate는 실패로 유지, predictive availability·인과효과 미확인, 운영 변경 없음. [A manifest](../20261010_joint_gain_loss_v1/ARTIFACT_MANIFEST.json), [독립 보충 검토](../20261010_joint_gain_loss_review_v1/outputs/independent_supplemental_verification_receipt.json).\n"
    result["SOURCES.md"] = sources

    reg = json.loads(result["research_register.json"])
    assert len(reg["topics"]) == 22
    hits = [x for x in reg["topics"] if x.get("id") == "joint_relationship"]
    assert len(hits) == 1
    item = hits[0]
    assert item["status"] == "retrospective_joint_relationship_gate_failed_no_operational_change"
    assert item["primary_gate"]["gate_passed"] is False and item["operationally_applied"] is False
    item["follow_up_diagnostic"] = {
        "study": "../20261010_joint_gain_loss_v1/README.md",
        "manifest": "../20261010_joint_gain_loss_v1/ARTIFACT_MANIFEST.json",
        "independent_review": "../20261010_joint_gain_loss_review_v1/outputs/independent_supplemental_verification_receipt.json",
        "cohort_races": 1779,
        "gained": 50,
        "lost": 34,
        "status": "retrospective_descriptive_followup; original_performance_gate_still_failed; no_operational_change",
        "prospective_rule_supported": False,
        "causal_effect_identified": False
    }
    reg["updated_at"] = "2026-10-10"
    result["research_register.json"] = json.dumps(reg, ensure_ascii=False, indent=2) + "\n"

    # Refresh only the four changed central rows and add the scoped source files
    # that this follow-up explicitly cites. All other rows stay byte-equivalent.
    sm = json.loads(result["source_manifest.json"])
    rows = {x["path"]: x for x in sm["files"]}
    central_roles = {
      FILES[n]: "conclusion_or_management" for n in ["README.md", "SOURCES.md", "19_JOINT_RELATIONSHIP.md"]
    }
    central_roles[FILES["research_register.json"]] = "research_registry"
    for name, role in central_roles.items():
        payload = result[Path(name).name].encode("utf-8")
        rows[name] = {"path": name, "role": role, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    scoped = [
      ("jeju/research/20261010_joint_gain_loss_v1/README.md", "joint_relationship_followup"),
      ("jeju/research/20261010_joint_gain_loss_v1/ARTIFACT_MANIFEST.json", "research_artifact_manifest"),
      ("jeju/research/20261010_joint_gain_loss_v1/outputs/analysis_receipt.json", "research_receipt"),
      ("jeju/research/20261010_joint_gain_loss_v1/outputs_followup_addendum/followup_receipt.json", "research_receipt"),
      ("jeju/research/20261010_joint_gain_loss_v1/outputs_followup_addendum/actual_top3_context_summary_corrected_v2.csv", "research_output"),
      ("jeju/research/20261010_joint_gain_loss_v1/outputs_followup_addendum/top3_summary_feature_label_correction_receipt.json", "research_receipt"),
      ("jeju/research/20261010_joint_gain_loss_v1/outputs_followup_addendum/history_scope_correction_receipt.json", "research_receipt"),
      ("jeju/research/20261010_joint_gain_loss_review_v1/outputs/independent_supplemental_verification_receipt.json", "independent_review_receipt"),
    ]
    for rel, role in scoped:
        p = ROOT / rel
        assert p.is_file(), f"missing source referenced by central follow-up: {rel}"
        rows[rel] = {"path": rel, "role": role, "sha256": sha(p), "bytes": p.stat().st_size}
    sm["files"] = sorted(rows.values(), key=lambda x: x["path"])
    sm["updated_at"] = "2026-10-10"
    sm["managed_files_bytes_excluding_this_manifest"] = sum(x.get("bytes", 0) for x in sm["files"])
    sm["latest_study"] = "jeju/research/20261010_joint_gain_loss_v1"
    sm["latest_verification"] = "jeju/research/20261010_joint_gain_loss_review_v1/outputs/independent_supplemental_verification_receipt.json"
    sm["latest_status"] = "retrospective_diagnostic_completed_original_gate_failed_no_operational_change"
    result["source_manifest.json"] = json.dumps(sm, ensure_ascii=False, indent=2) + "\n"

    # Validate local markdown links from their eventual central paths.
    for name in ["README.md", "SOURCES.md", "19_JOINT_RELATIONSHIP.md"]:
        source_path = CENTRAL / name
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", result[name]):
            target = target.strip().split("#", 1)[0]
            if not target or re.match(r"^(?:https?:|mailto:|tel:|data:)", target, re.I):
                continue
            assert (source_path.parent / target).resolve().exists(), f"broken local link in staged {name}: {target}"

    payloads = {FILES[name]: result[name].encode("utf-8") for name in FILES}
    preview = {
      "status": "prepared; no central writes",
      "snapshot_receipt_sha256": sha(SNAP_RECEIPT),
      "study_manifest_sha256": sha(manifest_path),
      "independent_review_sha256": sha(REVIEW_RECEIPT),
      "core_independent_review_sha256": sha(CORE_RECEIPT),
      "root_supervisory_review_sha256": sha(ROOT_SUPERVISORY),
      "topic_count": len(reg["topics"]),
      "topic19_original_gate_failed": True,
      "topic18_untouched_expected_sha256": "23f1a0819b5198440d7678395555cf46a132e6be9e2a7d1f8eefad9d5c060f5f",
      "central_targets": sorted(payloads),
      "central_writes": False,
    }
    return payloads, preview


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the staged five central files; requires root approval token")
    ap.add_argument("--root-approval", default="", help="must equal ROOT_APPROVES_GAIN_LOSS_TOPIC19_APPEND")
    args = ap.parse_args()
    payloads, receipt = prepare()
    STAGING.mkdir(parents=True, exist_ok=True)
    for rel, payload in payloads.items():
        out = STAGING / Path(rel).name
        out.write_bytes(payload)
    receipt["preview_files"] = [{"path": rel, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)} for rel, payload in sorted(payloads.items())]
    (STAGING / "preview_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    if not args.apply:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return
    if args.root_approval != APPROVAL_TOKEN:
        raise SystemExit("central writes refused: explicit root approval token required")
    assert not (HERE / "central_publication_receipt.json").exists(), "refuse to overwrite an existing publication receipt"
    # Recheck each central preimage immediately before writing; topic 18 is protected.
    snap_receipt, _ = snapshot_bytes()
    for name, rel in FILES.items():
        assert sha(ROOT / rel) == next(x["sha256"] for x in snap_receipt["files"] if Path(x["central_path"]).name == name), f"central preimage changed: {rel}"
    topic18 = CENTRAL / "18_PROBABILITY_COMBO_GAP.md"
    assert sha(topic18) == receipt["topic18_untouched_expected_sha256"]
    # Pre-serialize all outputs first, then atomically replace scoped destinations.
    temp_paths=[]
    try:
        for rel,payload in payloads.items():
            target=ROOT/rel; tmp=target.with_name(target.name+".gainloss.tmp")
            with tmp.open("wb") as f: f.write(payload); f.flush(); os.fsync(f.fileno())
            temp_paths.append((tmp,target))
        for tmp,target in temp_paths: os.replace(tmp,target)
    finally:
        for tmp,_ in temp_paths:
            if tmp.exists(): tmp.unlink()
    receipt["status"]="applied"
    receipt["central_writes"]=True
    receipt["written_files"]=[{"path":rel,"sha256":sha(ROOT/rel),"bytes":(ROOT/rel).stat().st_size} for rel in sorted(FILES.values()) if not rel.endswith("source_manifest.json")]
    receipt["initial_source_manifest_sha256"]=sha(CENTRAL/"source_manifest.json")
    receipt["topic18_unchanged_after_write"]=sha(topic18)==receipt["topic18_untouched_expected_sha256"]
    assert receipt["topic18_unchanged_after_write"]
    (HERE/"central_publication_receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    manifest_path=HERE/"ARTIFACT_MANIFEST.json"
    assert not manifest_path.exists(), "refuse to overwrite existing review ARTIFACT_MANIFEST.json"
    local_files=[]
    for p in sorted(HERE.rglob("*")):
        if not p.is_file() or p==manifest_path or "__pycache__" in p.parts or "central_publication_preview_gain_loss" in p.parts:
            continue
        local_files.append({"path":p.relative_to(ROOT).as_posix(),"sha256":sha(p),"bytes":p.stat().st_size})
    cmanifest={"scope":"Independent review and authorized central follow-up publication for 20261010 joint gain/loss","status":"independent verification PASS; original relationship performance gate remains failed; no operational change","central_publication_receipt":{"path":"jeju/research/20261010_joint_gain_loss_review_v1/central_publication_receipt.json","sha256":sha(HERE/"central_publication_receipt.json")},"verified_A_manifest":{"path":"jeju/research/20261010_joint_gain_loss_v1/ARTIFACT_MANIFEST.json","sha256":sha(manifest_path.parent.parent/"20261010_joint_gain_loss_v1/ARTIFACT_MANIFEST.json")},"local_files":local_files,"published_central_files":receipt["written_files"],"central_source_manifest_hash_excluded":"final source_manifest.json is refreshed in the following scoped step to add all A/context/review artifacts; its self hash is not recorded here"}
    manifest_path.write_text(json.dumps(cmanifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__ == "__main__": main()

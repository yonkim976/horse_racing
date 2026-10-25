#!/usr/bin/env python3
"""Publish the authorized joint-relationship research summary and scoped indexes."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "jeju/research/20261010_joint_relationship_review_v1"
CENTRAL = ROOT / "jeju/research/conclusions"
SNAP = HERE / "outputs/central_snapshot_prepublication_20261010"
STUDY = ROOT / "jeju/research/20261010_joint_relationship_v1"
TOPIC_REL = "jeju/research/conclusions/19_JOINT_RELATIONSHIP.md"
RECEIPT_PATH = HERE / "central_publication_receipt.json"
CMANIFEST_PATH = HERE / "ARTIFACT_MANIFEST.json"
SOURCES = ["README.md", "SOURCES.md", "research_register.json", "source_manifest.json", "18_PROBABILITY_COMBO_GAP.md"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def info(path: Path, relative: str | None = None) -> dict:
    return {"path": relative or path.relative_to(ROOT).as_posix(), "sha256": sha(path), "bytes": path.stat().st_size}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def local_markdown_links(path: Path) -> list[tuple[str, bool]]:
    text = path.read_text(encoding="utf-8")
    found = []
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        target = target.strip().split("#", 1)[0]
        if not target or re.match(r"^(?:https?:|mailto:|tel:|data:)", target, re.I):
            continue
        ok = (path.parent / target).resolve().exists()
        found.append((target, ok))
    return found


def main() -> None:
    snap_receipt = read_json(SNAP / "central_snapshot_receipt.json")
    assert snap_receipt["passed"] and snap_receipt["central_files_modified"] is False
    assert snap_receipt["source_manifest_prepublication_audit"]["entry_count"] == 1183
    assert snap_receipt["source_manifest_prepublication_audit"]["matched_count"] == 1183
    assert snap_receipt["source_manifest_prepublication_audit"]["preexisting_mismatch_count"] == 0
    old_reg = read_json(SNAP / "research_register.json")
    topic_path = CENTRAL / "19_JOINT_RELATIONSHIP.md"
    publication_exists = topic_path.exists()
    reg_path = CENTRAL / "research_register.json"
    if publication_exists:
        reg_now = read_json(reg_path)
        assert len(reg_now["topics"]) == 22 and reg_now["topics"][:21] == old_reg["topics"]
        assert RECEIPT_PATH.is_file() and CMANIFEST_PATH.is_file()
    else:
        for name in SOURCES:
            assert sha(CENTRAL / name) == sha(SNAP / name), f"central file changed after snapshot: {name}"

    a_manifest_path = STUDY / "ARTIFACT_MANIFEST.json"
    a_manifest = read_json(a_manifest_path)
    a_validation = read_json(HERE / "outputs/a_manifest_independent_validation.json")
    assert sha(a_manifest_path) == "d0d1a749afb6a6f894de1bb4263c9d67dd1e3b2d1a35bf1b5fd38d8948c656b0"
    assert a_validation["passed"] and a_validation["local_file_count"] == 34
    assert len(a_validation["external_review_refs_verified"]) == 3
    assert a_validation["study_manifest_sha256"] == sha(a_manifest_path)
    c_postfit = read_json(HERE / "outputs/postfit_independent_validation/independent_postfit_validation.json")
    assert c_postfit["passed"]
    assert c_postfit["locked_source_count"] == 39 and c_postfit["locked_sources_unchanged_before_after_validation"] is True
    root_review = read_json(STUDY / "outputs/root_final_review.json")
    assert root_review["passed"] and root_review["primary_research_signal_gate_passed"] is False

    if not publication_exists:
        topic = """# F1_STYLE6 공동 입상관계와 최대 6조합 비교

    **판정:** 저장된 F1_STYLE6 말 점수와 말별 평가를 유지한 채 관계항을 더한 후향 연구다. 사전 성능 게이트는 실패했고 운영 승격은 없다.

    ## 질문과 자료

    기존 F1_STYLE6 점수는 그대로 두고, 말 쌍 관계항을 추가해 전체 무순서 정확 Top3 조합을 정규화하고 경주당 최대 6개 조합을 고르는 실험을 했다. 평가 코호트는 2024-01-05~2026-09-19의 1,779경주, 17,412출전, 269경주일이며 2026년은 부분연도다. 과거 개발 자료를 재사용했으므로 독립 미래 검증은 아니다.

    주 비교는 같은 원시점수와 같은 H2 보정 기간을 사용한 매칭 점수 전용 대조군과 관계 후보였다. 시간 분할과 T−2 경계는 고정 계획을 따랐다. 기존 저장된 F1_STYLE6 점수·확률은 변경하지 않았다.

    ## 주 결과

    | 결과 | 매칭 대조군 | 관계 후보 | 후보−대조군 | 날짜 paired 95% CI | 게이트 |
    |---|---:|---:|---:|---:|---|
    | 최대 6조합 정확 Top3 적중 | 407/1,779 (22.8780%) | 423/1,779 (23.7774%) | +0.8994%p | [−0.1137, +1.8997]%p | 실패: 하한이 0 이하 |
    | 정확 Top3 집합 NLL | 4.287786 | 4.288421 | +0.000635 | [−0.004728, +0.006277] | 실패: 상한이 0 초과 |

    날짜 단위 paired bootstrap은 2,000회, seed 20261008이다. 사전 규칙은 적중률 차이의 CI 하한이 0보다 크고 집합 NLL 차이의 CI 상한이 0 이하인 경우만 통과로 정했다. 두 조건 모두 충족되지 않아 연구 신호 게이트는 false다. 점추정의 적중 증가는 불확실하며 결합 NLL은 평균상 후보가 조금 나빴다.

    ## 검증과 해석 범위

    C는 A의 계산 helper를 가져오지 않고 잠금 원천에서 H1 표준화·계수 목적함수와 gradient, H2 온도 stationarity, 1,779경주의 전체 triple 분포와 주변확률, 지표·날짜 bootstrap, 정확한 stable top-six 선택을 다시 계산했다. 저장 결과와 전량 대조, 순서·라벨 교란 불변성 검사는 PASS했다. 39개 잠금 원천 해시는 검토 중 바뀌지 않았다. 검증 PASS는 계산 재현성 판정이며 성능 게이트 PASS를 뜻하지 않는다.

    이 연구는 사후 완전 roster와 과거 스타일 요약을 사용했으며 과거 공표 시각이나 당시 확정 출전 명단을 재구성하지 않았다. 관계 계수를 인과적 궁합으로 해석하거나 미래 성능으로 일반화할 수 없다. 말 점수·저장 확률·운영 모델·DB·운영 등록부는 바뀌지 않았다.

    ## 원본과 검증 기록

    - [설계·코드·전체 결과](../20261010_joint_relationship_v1/README.md)
    - [상세 결과와 제한](../20261010_joint_relationship_v1/RESULTS_AND_LIMITATIONS.md)
    - [고정 산출물 manifest](../20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json)
    - [독립 원천 재구성 receipt](../20261010_joint_relationship_review_v1/outputs/postfit_independent_validation/independent_postfit_validation.json)
    - [최종 검토 receipt](../20261010_joint_relationship_v1/outputs/root_final_review.json)
    - [중앙 발행 receipt](../20261010_joint_relationship_review_v1/central_publication_receipt.json)
    """
        assert not topic_path.exists(), "topic19 already exists; do not overwrite"
        topic_path.write_text(topic.replace("\n            ", "\n"), encoding="utf-8")

        readme_path = CENTRAL / "README.md"
        readme = readme_path.read_text(encoding="utf-8")
        readme = readme.replace("F1_STYLE6 확률 및 최대 6조합 차이 진단이다.", "F1_STYLE6 확률 및 최대 6조합 차이 진단, 공동 입상관계 비교다.")
        marker = "| [확률 개선과 최대 6조합 적중 간격](18_PROBABILITY_COMBO_GAP.md)"
        assert readme.count(marker) == 1
        readme = readme.replace(marker, marker)
        insert_after = "| [원 연구와 버전 목록](SOURCES.md)"
        row = "| [F1_STYLE6 공동 입상관계와 최대 6조합 비교](19_JOINT_RELATIONSHIP.md) | 기존 말 점수는 고정하고 관계항을 더한 후향 비교. 6조합 적중 점추정은 상승했지만 날짜 구간이 0을 포함하고 집합 NLL gate도 실패 | 독립 재구성 PASS; 연구 신호 gate 실패, 운영 미반영 |\n"
        assert insert_after in readme and "19_JOINT_RELATIONSHIP.md" not in readme
        readme = readme.replace(insert_after, row + insert_after)
        readme += "\n<!-- joint_relationship_v1_20261010 -->\n[F1_STYLE6 공동 입상관계 비교](19_JOINT_RELATIONSHIP.md): 1,779경주에서 매칭 대조군 대비 최대 6조합 적중은 407→423건이었지만 날짜 CI가 0을 포함하고 집합 NLL guardrail이 실패했다. 독립 재구성은 PASS, 성능 gate는 실패했으며 운영 모델은 바꾸지 않았다. [원 연구](../20261010_joint_relationship_v1/README.md), [상세 결과](../20261010_joint_relationship_v1/RESULTS_AND_LIMITATIONS.md), [독립 receipt](../20261010_joint_relationship_review_v1/outputs/postfit_independent_validation/independent_postfit_validation.json).\n"
        readme_path.write_text(readme, encoding="utf-8")

        sources_path = CENTRAL / "SOURCES.md"
        sources = sources_path.read_text(encoding="utf-8")
        assert "20261010_joint_relationship_v1" not in sources
        sources += "\n- [20261010_joint_relationship_v1](../20261010_joint_relationship_v1/README.md): 기존 F1_STYLE6 점수 고정 하에 pair 관계항으로 전체 무순서 Top3를 정규화하고 최대 6개를 선택한 후향 비교. 후보 423/1,779, 매칭 대조군 407/1,779; 날짜 paired CI가 0을 포함하고 exact-set NLL gate도 실패. [최종 결과](../20261010_joint_relationship_v1/RESULTS_AND_LIMITATIONS.md), [고정 manifest](../20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json), [독립 사후검증](../20261010_joint_relationship_review_v1/outputs/postfit_independent_validation/independent_postfit_validation.json), [최종 검토](../20261010_joint_relationship_v1/outputs/root_final_review.json). 운영 변경 없음.\n"
        sources_path.write_text(sources, encoding="utf-8")

        reg_path = CENTRAL / "research_register.json"
        reg = read_json(reg_path)
        old_reg = read_json(SNAP / "research_register.json")
        assert reg == old_reg and len(reg["topics"]) == 21
        item = {
            "id": "joint_relationship",
            "title": "F1_STYLE6 공동 입상관계와 최대 6조합 비교",
            "conclusion": "19_JOINT_RELATIONSHIP.md",
            "latest_source": "../20261010_joint_relationship_v1/RESULTS_AND_LIMITATIONS.md",
            "study_manifest": "../20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json",
            "independent_review": "../20261010_joint_relationship_review_v1/outputs/postfit_independent_validation/independent_postfit_validation.json",
            "root_final_review": "../20261010_joint_relationship_v1/outputs/root_final_review.json",
            "central_publication_receipt": "../20261010_joint_relationship_review_v1/central_publication_receipt.json",
            "period_start": "2024-01-05",
            "period_end": "2026-09-19",
            "evaluation_period_start": "2024-01-05",
            "evaluation_period_end": "2026-09-19",
            "partial_year_2026": True,
            "population": "posthoc_normal_complete_full_roster_current_distance_cohort",
            "evaluation_rows": 17412,
            "evaluation_races": 1779,
            "evaluation_days": 269,
            "all_unordered_triples_recomputed": 402808,
            "relationship_pair_features": 11,
            "coefficient_fit_folds": 3,
            "temperature_optimizations": 6,
            "base_model_fit_or_reload": False,
            "primary_gate": {
                "comparison": "candidate_minus_H2_matched_raw_score_baseline",
                "candidate_hit6": 423,
                "baseline_hit6": 407,
                "hit6_delta_percentage_points": 0.8993816750983699,
                "hit6_date_ci95_percentage_points": [-0.11365423098913664, 1.8997081162513325],
                "joint_true_set_nll_delta": 0.0006347333275187765,
                "joint_true_set_nll_date_ci95": [-0.0047283895282942984, 0.006277195351270995],
                "bootstrap_draws": 2000,
                "bootstrap_seed": 20261008,
                "gate_passed": False
            },
            "independent_reconstruction_passed": True,
            "locked_source_count": 39,
            "locked_sources_unchanged": True,
            "independent_future_validation": False,
            "causal_effect_identified": False,
            "operationally_applied": False,
            "previous_F1_STYLE6_preserved": True,
            "status": "retrospective_joint_relationship_gate_failed_no_operational_change"
        }
        reg["topics"].append(item)
        reg["updated_at"] = "2026-10-10"
        reg["scope"] += " F1_STYLE6 공동 입상관계 비교를 포함한다."
        reg["latest_study"] = "jeju/research/20261010_joint_relationship_v1"
        reg["latest_verification"] = "jeju/research/20261010_joint_relationship_review_v1/central_publication_receipt.json"
        reg["latest_status"] = item["status"]
        write_json(reg_path, reg)

    reg = read_json(reg_path)
    # Create the receipt before either manifest to keep the dependency graph acyclic.
    snap_files = snap_receipt["files"]
    changed_now = [info(CENTRAL / p) for p in ("README.md", "SOURCES.md", "research_register.json", "19_JOINT_RELATIONSHIP.md")]
    receipt = {
        "passed": True,
        "mode": "authorized central publication with fresh pre-update snapshot; scoped hash/link verification",
        "date": "2026-10-10",
        "authorization": {
            "reviewer": "root",
            "writer": "joint_relationship_review",
            "scope": ["new topic19", "README.md", "SOURCES.md", "research_register.json", "source_manifest.json"],
            "model_refit_or_operating_database_change": False
        },
        "prepublication_snapshot": {
            "receipt_path": "jeju/research/20261010_joint_relationship_review_v1/outputs/central_snapshot_prepublication_20261010/central_snapshot_receipt.json",
            "files": snap_files,
            "source_manifest_entry_count": 1183,
            "source_manifest_matched_count": 1183,
            "preexisting_stale_count": 0,
            "topic18_preserved_sha256": "23f1a0819b5198440d7678395555cf46a132e6be9e2a7d1f8eefad9d5c060f5f"
        },
        "study_manifest": info(a_manifest_path),
        "study_manifest_validation": {
            "receipt_path": "jeju/research/20261010_joint_relationship_review_v1/outputs/a_manifest_independent_validation.json",
            "receipt_sha256": sha(HERE / "outputs/a_manifest_independent_validation.json"),
            "local_files_verified": 34,
            "external_review_refs_verified": 3,
            "all_passed": True
        },
        "independent_postfit_review": {
            "path": "jeju/research/20261010_joint_relationship_review_v1/outputs/postfit_independent_validation/independent_postfit_validation.json",
            "sha256": sha(HERE / "outputs/postfit_independent_validation/independent_postfit_validation.json"),
            "passed": True,
            "locked_sources_verified": 39,
            "performance_gate_passed": False
        },
        "central_files_written": changed_now,
        "topic18_written": False,
        "topic18_current_sha256": sha(CENTRAL / "18_PROBABILITY_COMBO_GAP.md"),
        "previous_register_topics_preserved": len(reg["topics"]) == 22 and reg["topics"][:21] == old_reg["topics"],
        "performance_gate_passed": False,
        "candidate_hit6": 423,
        "matched_baseline_hit6": 407,
        "hit6_delta_ci95_percentage_points": [-0.11365423098913664, 1.8997081162513325],
        "exact_set_nll_delta_ci95": [-0.0047283895282942984, 0.006277195351270995],
        "operational_promotion": False,
        "central_source_manifest_final_hash_excluded_to_avoid_cycle": True
    }
    write_json(RECEIPT_PATH, receipt)

    # Freeze the C artifact manifest after the receipt exists; source_manifest is published last.
    c_local = []
    for p in sorted(HERE.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts or p == CMANIFEST_PATH:
            continue
        c_local.append(info(p))
    cm = {
        "scope": "Independent verification and central publication artifacts for 20261010 joint relationship study",
        "status": "publication completed; validation PASS; performance gate FAIL",
        "central_publication_receipt": info(RECEIPT_PATH),
        "verified_study_manifest": info(a_manifest_path),
        "local_files": c_local,
        "published_central_files": changed_now,
        "excluded_for_acyclic_provenance": ["central source_manifest.json final self-referential hash"]
    }
    write_json(CMANIFEST_PATH, cm)

    # Update the source manifest while preserving all old noncentral rows byte-for-byte as JSON objects.
    sm_path = CENTRAL / "source_manifest.json"
    old_sm = read_json(SNAP / "source_manifest.json")
    sm = json.loads(json.dumps(old_sm))
    old_rows = list(sm["files"])
    by_path = {x["path"]: x for x in old_rows}
    changed_central = {"jeju/research/conclusions/README.md", "jeju/research/conclusions/SOURCES.md", "jeju/research/conclusions/research_register.json"}
    for rel, role in [
        ("jeju/research/conclusions/README.md", "conclusion_or_management"),
        ("jeju/research/conclusions/SOURCES.md", "conclusion_or_management"),
        ("jeju/research/conclusions/research_register.json", "research_registry"),
        (TOPIC_REL, "conclusion_or_management"),
    ]:
        p = ROOT / rel
        by_path[rel] = {"path": rel, "role": role, "sha256": sha(p), "bytes": p.stat().st_size}

    additions = [by_path[TOPIC_REL]]
    for rel, role in [(f"jeju/research/20261010_joint_relationship_v1/{k}", "joint_relationship_study") for k in a_manifest["files"]]:
        p = ROOT / rel
        row = {"path": rel, "role": role, "sha256": sha(p), "bytes": p.stat().st_size}
        if rel in by_path and rel not in changed_central:
            assert by_path[rel]["sha256"] == row["sha256"] and by_path[rel]["bytes"] == row["bytes"], f"conflicting prior entry: {rel}"
        else:
            additions.append(row)
            by_path[rel] = row
    a_manifest_row = info(a_manifest_path)
    a_manifest_row["role"] = "joint_relationship_study_manifest"
    additions.append(a_manifest_row)

    # C review artifacts include the C manifest and receipt; all are now frozen.
    for p in sorted(HERE.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        rel = p.relative_to(ROOT).as_posix()
        row = {"path": rel, "role": "joint_relationship_independent_review", "sha256": sha(p), "bytes": p.stat().st_size}
        if rel in by_path and rel not in changed_central:
            assert by_path[rel]["sha256"] == row["sha256"] and by_path[rel]["bytes"] == row["bytes"], f"conflicting C entry: {rel}"
        else:
            additions.append(row)
            by_path[rel] = row

    # Preserve original row order; append newly introduced rows deterministically.
    seen = {x["path"] for x in old_rows}
    append_rows = [x for x in additions if x["path"] not in seen]
    append_rows.sort(key=lambda x: x["path"])
    sm["files"] = [by_path[x["path"]] if x["path"] in changed_central else x for x in old_rows] + append_rows
    sm["updated_at"] = "2026-10-10"
    sm["latest_study"] = "jeju/research/20261010_joint_relationship_v1"
    sm["latest_verification"] = "jeju/research/20261010_joint_relationship_review_v1/central_publication_receipt.json"
    sm["latest_status"] = "retrospective_joint_relationship_gate_failed_no_operational_change"
    sm["managed_files_bytes_excluding_this_manifest"] = sum(x["bytes"] for x in sm["files"])
    v = sm["verification"]
    v.update({
        "status": "passed_central_publication_for_joint_relationship_gate_failed",
        "all_previous_source_hashes_unchanged": False,
        "latest_study": sm["latest_study"],
        "latest_verification": sm["latest_verification"],
        "all_previous_noncentral_source_entries_unchanged": True,
        "prepublication_snapshot_manifest": "jeju/research/20261010_joint_relationship_review_v1/outputs/central_snapshot_prepublication_20261010/source_manifest.json",
        "prepublication_source_manifest_sha256": sha(SNAP / "source_manifest.json"),
        "prepublication_source_manifest_entries": 1183,
        "prepublication_source_manifest_matched": 1183,
        "prepublication_source_manifest_stale": 0,
        "previous_topics_preserved_before_current_append": 21,
        "topic_entries_after_current_append": 22,
        "topic18_preserved_sha256": sha(CENTRAL / "18_PROBABILITY_COMBO_GAP.md"),
        "central_publication_receipt": "passed; new topic 19 appended, prior 21 research-register topic objects preserved, topic 18 unchanged",
        "central_publication_receipt_path": "jeju/research/20261010_joint_relationship_review_v1/central_publication_receipt.json",
        "central_publication_receipt_sha256": sha(RECEIPT_PATH),
        "central_publication_receipt_hash_included_as_frozen_source_entry": True,
        "publication_receipt_hash_included_in_C_artifact_manifest": True,
        "central_source_manifest_postpublication_hash_excluded_from_receipt": True,
        "source_manifest_self_hash_excluded": True,
        "performance_gate_passed": False,
        "operational_promotion": False,
        "database_query_performed": False,
        "database_registry_current_model_fit_or_code_modified": False,
        "central_publication_write_scope": ["jeju/research/conclusions/19_JOINT_RELATIONSHIP.md", "jeju/research/conclusions/README.md", "jeju/research/conclusions/SOURCES.md", "jeju/research/conclusions/research_register.json", "jeju/research/conclusions/source_manifest.json", "jeju/research/20261010_joint_relationship_review_v1/central_publication_receipt.json", "jeju/research/20261010_joint_relationship_review_v1/ARTIFACT_MANIFEST.json"],
        "previous_central_snapshot_hashes_recorded": True,
    })
    write_json(sm_path, sm)

    # Scoped post-write validation; do not rehash unrelated legacy multi-gigabyte inputs.
    assert sha(CENTRAL / "18_PROBABILITY_COMBO_GAP.md") == "23f1a0819b5198440d7678395555cf46a132e6be9e2a7d1f8eefad9d5c060f5f"
    new_reg = read_json(reg_path)
    assert new_reg["topics"][:21] == old_reg["topics"] and len(new_reg["topics"]) == 22
    new_rows = {x["path"]: x for x in sm["files"]}
    assert len(new_rows) == len(sm["files"])
    for row in append_rows:
        p = ROOT / row["path"]
        assert p.is_file() and p.stat().st_size == row["bytes"] and sha(p) == row["sha256"], row["path"]
    for rel in ["jeju/research/conclusions/README.md", "jeju/research/conclusions/SOURCES.md", "jeju/research/conclusions/research_register.json", TOPIC_REL]:
        row = new_rows[rel]
        p = ROOT / rel
        assert p.stat().st_size == row["bytes"] and sha(p) == row["sha256"]
    links = []
    for p in [CENTRAL / "README.md", CENTRAL / "SOURCES.md", topic_path]:
        links.extend((p.relative_to(ROOT).as_posix(), t, ok) for t, ok in local_markdown_links(p))
    failures = [x for x in links if not x[2]]
    assert not failures, failures[:10]
    assert sm["managed_files_bytes_excluding_this_manifest"] == sum(x["bytes"] for x in sm["files"])
    assert read_json(RECEIPT_PATH)["performance_gate_passed"] is False
    assert sha(CENTRAL / "README.md") != sha(SNAP / "README.md")
    print(json.dumps({
        "passed": True,
        "receipt": info(RECEIPT_PATH),
        "c_manifest": info(CMANIFEST_PATH),
        "source_manifest": info(sm_path),
        "topic19": info(topic_path),
        "central_links_checked": len(links),
        "link_failures": len(failures),
        "prior_source_rows": len(old_rows),
        "source_rows_after": len(sm["files"]),
        "added_source_rows": len(sm["files"]) - len(old_rows),
        "preserved_register_topics": 21,
        "performance_gate_passed": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

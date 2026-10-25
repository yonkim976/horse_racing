#!/usr/bin/env python3
"""Prepare or apply the narrowly scoped topic 21 publication append.

Default mode is a read-only dry run. Applying requires both --apply and the
explicit --confirm-apply-topic21 flag, and the complete central snapshot must
still match byte-for-byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
STUDY = ROOT / "jeju/research/20261010_pair_axis_review_v1"
PREP = STUDY / "publication_preparation"
SNAPSHOT_DIR = STUDY / "central_snapshot_before_topic21"
CENTRAL = ROOT / "jeju/research/conclusions"
PAYLOAD = PREP / "payload/21_PAIR_AXIS_TICKET_BUDGET.md"
TOPIC_NAME = "21_PAIR_AXIS_TICKET_BUDGET.md"
PUBLICATION_DATE = "2026-10-11"

PINNED = {
    "jeju/research/20261010_pair_axis_design_v1/README.md": "7f0a70c172563364489737210d8fadf2b9e14c02749455dbb8a2746cef968937",
    "jeju/research/20261010_pair_axis_design_v1/source_manifest.json": "2c72e6f098fe18ec8b13e5118126bb25f7d8acbbde9295ce75934e2e74f24e68",
    "jeju/research/20261010_pair_axis_v1/ARTIFACT_MANIFEST.json": "6513e3080c736d0486aa787fc01341305f602fb98f40f1499d1512ea67b6b329",
    "jeju/research/20261010_pair_axis_review_v1/REVIEW_MEMO.md": "de72582d1a04b48ecfe6324f2118beb64273e0d2199438c6fe96e3de45d146e2",
    "jeju/research/20261010_pair_axis_review_v1/independent_validation.py": "089479447884fc557b2c964c284ad774ab44c28a6f285a915d3df987d7c89126",
    "jeju/research/20261010_pair_axis_review_v1/outputs/independent_validation_receipt.json": "9fce11f05e57cc75aa6c7be679ea706783cf3145fce2007e5f6c6ee4b780720e",
    "jeju/research/20261010_pair_axis_review_v1/supplemental_cutoff_validation.py": "8cbbe469499ecca7a7bab02abd9afa8cb431e9c8b939634476e5546323cd4d5c",
    "jeju/research/20261010_pair_axis_review_v1/outputs/supplemental_fixed_cutoff_receipt.json": "4697afc1294c46b29d5e29b5c5ae93c10228f4ae6354a20067109c27bc9a8b38",
    "jeju/research/20261010_pair_axis_review_v1/publication_preparation/payload/21_PAIR_AXIS_TICKET_BUDGET.md": "94d18b6ba3bfeb20c9bf75bcdf6ad6453a3b78b91fb85f8f6817b11ba8e3513b",
    "jeju/research/20261010_pair_axis_review_v1/central_snapshot_before_topic21/snapshot_manifest.json": "d3fc58eaae08f219cdbb8cf9236154b9ea51049dc81ac2b7f0cd3e9f0eeb53cf",
}

STUDY_PREFIXES = (
    "jeju/research/20261010_pair_axis_design_v1/",
    "jeju/research/20261010_pair_axis_v1/",
    "jeju/research/20261010_pair_axis_review_v1/",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def repo_file(relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError(f"unsafe repository-relative path: {relative_path}")
    resolved = (ROOT / candidate).resolve()
    if not resolved.is_relative_to(ROOT):
        raise RuntimeError(f"path escapes repository: {relative_path}")
    return resolved


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_hash(relative_path: str, expected: str) -> Path:
    path = repo_file(relative_path)
    actual = file_hash(path)
    if actual != expected:
        raise RuntimeError(f"frozen source changed: {relative_path} ({actual})")
    return path


def verify_central_snapshot(snapshot: dict) -> None:
    if snapshot.get("snapshot_of") != "jeju/research/conclusions":
        raise RuntimeError("snapshot target mismatch")
    expected = snapshot["files"]
    expected_names = set(expected)
    current_names = {p.name for p in CENTRAL.iterdir() if p.is_file()}
    topic_path = snapshot["new_topic_path"].split("/")[-1]
    if topic_path in current_names:
        raise RuntimeError(f"new topic already exists: {topic_path}")
    if current_names != expected_names:
        added = sorted(current_names - expected_names)
        missing = sorted(expected_names - current_names)
        raise RuntimeError(f"central file set differs from snapshot; added={added}, missing={missing}")
    for name, record in expected.items():
        path = CENTRAL / name
        actual = file_hash(path)
        if actual != record["sha256"]:
            raise RuntimeError(f"central CAS failed: {name} ({actual})")
    for name in ("12_AXIS_COMPANION_PAIRS.md", "19_JOINT_RELATIONSHIP.md", "20_TRAINER_PROFILE.md"):
        if file_hash(CENTRAL / name) != expected[name]["sha256"]:
            raise RuntimeError(f"protected topic changed: {name}")


def source_rows(payload_hash: str) -> list[dict]:
    rows: list[dict] = []

    def add(path: str, role: str, sha: str, size: int) -> None:
        if not path.startswith(STUDY_PREFIXES):
            raise RuntimeError(f"source row is outside the three study folders: {path}")
        rows.append({"path": path, "role": role, "sha256": sha, "bytes": int(size)})

    # The design folder is a small read-only source audit; its immutable source
    # manifest identifies the already-published input records.
    for relative, role in (
        ("jeju/research/20261010_pair_axis_design_v1/README.md", "study_design"),
        ("jeju/research/20261010_pair_axis_design_v1/source_manifest.json", "study_source_manifest"),
    ):
        path = assert_hash(relative, PINNED[relative])
        add(relative, role, PINNED[relative], path.stat().st_size)

    # A's frozen manifest pins every analysis artifact. Verify the manifest
    # itself, then verify its scoped files without revisiting the large inputs.
    a_manifest_path = assert_hash(
        "jeju/research/20261010_pair_axis_v1/ARTIFACT_MANIFEST.json",
        PINNED["jeju/research/20261010_pair_axis_v1/ARTIFACT_MANIFEST.json"],
    )
    a_manifest = load_json(a_manifest_path)
    add(
        "jeju/research/20261010_pair_axis_v1/ARTIFACT_MANIFEST.json",
        "study_artifact_manifest",
        PINNED["jeju/research/20261010_pair_axis_v1/ARTIFACT_MANIFEST.json"],
        a_manifest_path.stat().st_size,
    )
    for item in a_manifest["local_files"]:
        relative = item["path"]
        path = repo_file(relative)
        if file_hash(path) != item["sha256"] or path.stat().st_size != int(item["bytes"]):
            raise RuntimeError(f"A frozen artifact changed: {relative}")
        add(relative, "analysis_artifact", item["sha256"], item["bytes"])

    # C's two receipts pin the independent tables; its code and review memo
    # are separately frozen above.
    for relative, role in (
        ("jeju/research/20261010_pair_axis_review_v1/REVIEW_MEMO.md", "independent_review"),
        ("jeju/research/20261010_pair_axis_review_v1/independent_validation.py", "independent_validator"),
        ("jeju/research/20261010_pair_axis_review_v1/outputs/independent_validation_receipt.json", "independent_validation_receipt"),
        ("jeju/research/20261010_pair_axis_review_v1/supplemental_cutoff_validation.py", "supplemental_validator"),
        ("jeju/research/20261010_pair_axis_review_v1/outputs/supplemental_fixed_cutoff_receipt.json", "supplemental_validation_receipt"),
    ):
        path = assert_hash(relative, PINNED[relative])
        add(relative, role, PINNED[relative], path.stat().st_size)

    receipt_path = repo_file("jeju/research/20261010_pair_axis_review_v1/outputs/independent_validation_receipt.json")
    receipt = load_json(receipt_path)
    for name, record in receipt["artifact_hashes"].items():
        relative = f"jeju/research/20261010_pair_axis_review_v1/outputs/{name}"
        path = repo_file(relative)
        if file_hash(path) != record["sha256"] or path.stat().st_size != int(record["bytes"]):
            raise RuntimeError(f"C result artifact changed: {relative}")
        add(relative, "independent_result_table", record["sha256"], record["bytes"])

    payload_path = PAYLOAD.resolve()
    if not payload_path.is_relative_to(ROOT):
        raise RuntimeError("publication payload escapes repository")
    if file_hash(payload_path) != payload_hash:
        raise RuntimeError("publication payload changed after freeze")
    add(
        "jeju/research/20261010_pair_axis_review_v1/publication_preparation/payload/21_PAIR_AXIS_TICKET_BUDGET.md",
        "publication_payload",
        payload_hash,
        payload_path.stat().st_size,
    )

    snapshot_relative = "jeju/research/20261010_pair_axis_review_v1/central_snapshot_before_topic21/snapshot_manifest.json"
    snapshot_path = assert_hash(snapshot_relative, PINNED[snapshot_relative])
    add(snapshot_relative, "prepublication_snapshot_manifest", PINNED[snapshot_relative], snapshot_path.stat().st_size)

    script_path = Path(__file__).resolve()
    if not script_path.is_relative_to(ROOT):
        raise RuntimeError("publication append script escapes repository")
    script_relative = script_path.relative_to(ROOT).as_posix()
    add(script_relative, "guarded_publication_append_script", file_hash(script_path), script_path.stat().st_size)

    paths = [row["path"] for row in rows]
    if len(paths) != len(set(paths)):
        raise RuntimeError("duplicate scoped source rows")
    return rows


def build_changes(snapshot: dict, rows: list[dict], payload_hash: str) -> dict[str, bytes]:
    old_ids = snapshot["registered_topic_ids"]
    if len(old_ids) != snapshot["registered_topic_count"] or len(set(old_ids)) != len(old_ids):
        raise RuntimeError("snapshot register inventory is inconsistent")

    readme = (SNAPSHOT_DIR / "README.md").read_text(encoding="utf-8")
    old_row = next(
        line for line in readme.splitlines()
        if "19_JOINT_RELATIONSHIP.md" in line and line.startswith("|")
    )
    new_row = "| [저장 Top3 pair 축과 티켓 예산 비교](21_PAIR_AXIS_TICKET_BUDGET.md) | 무순서 Top3 저장분포의 no-fit 축·고정예산 비교; 최대 pair K3·4 결과와 날짜 구간은 일관된 개선을 확인하지 못함 | 독립 계산 검증 PASS; 개선 미확인·운영 미반영 |"
    readme = readme.replace(old_row, old_row + "\n" + new_row, 1)
    if "<!-- pair_axis_ticket_budget_v1_20261010 -->" in readme:
        raise RuntimeError("topic 21 README marker already exists in snapshot")
    readme += (
        "\n\n<!-- pair_axis_ticket_budget_v1_20261010 -->\n"
        "[저장 Top3 pair 축과 티켓 예산 비교](21_PAIR_AXIS_TICKET_BUDGET.md): "
        "1,779경주 저장분포에서 같은 K의 최대 pair와 unrestricted 티켓을 비교했다. "
        "네 primary 날짜 paired 구간은 모두 0을 포함해 성능 개선은 확인되지 않았고, "
        "독립 계산은 PASS했으며 모델 학습·운영 반영은 없다. "
        "[원 연구](../20261010_pair_axis_v1/README.md), "
        "[독립 검토](../20261010_pair_axis_review_v1/REVIEW_MEMO.md), "
        "[전체 검증 receipt](../20261010_pair_axis_review_v1/outputs/independent_validation_receipt.json), "
        "[cutoff 보충 receipt](../20261010_pair_axis_review_v1/outputs/supplemental_fixed_cutoff_receipt.json).\n"
    )

    sources = (SNAPSHOT_DIR / "SOURCES.md").read_text(encoding="utf-8")
    sources = sources.replace("2026년 10월 10일 기준.", "2026년 10월 11일 기준.", 1)
    sources += (
        "\n\n새 주제: [20261010_pair_axis_design_v1](../20261010_pair_axis_design_v1/README.md) "
        "— 사전 설계와 입력 감사; [20261010_pair_axis_v1](../20261010_pair_axis_v1/README.md) "
        "— 저장된 무순서 Top3로 no-fit 축·티켓 예산 비교; "
        "[20261010_pair_axis_review_v1](../20261010_pair_axis_review_v1/REVIEW_MEMO.md) "
        "— 독립 재계산과 고정 cutoff 보충 검증. 계산 검증은 통과했으나 성능 개선이나 운영 채택은 확인하지 않았다.\n"
    )

    register = load_json(SNAPSHOT_DIR / "research_register.json")
    register_ids = [item["id"] for item in register["topics"]]
    if register_ids != old_ids:
        raise RuntimeError("snapshot register IDs differ from frozen snapshot manifest")
    if "pair_axis_ticket_budget" in register_ids:
        raise RuntimeError("topic 21 already exists in register snapshot")
    register["updated_at"] = PUBLICATION_DATE
    register["scope"] += "· 저장된 무순서 exact Top3 분포의 pair 축·고정 티켓 예산 비교"
    register["topics"].append({
        "id": "pair_axis_ticket_budget",
        "title": "저장 Top3 pair 축과 티켓 예산 비교",
        "conclusion": TOPIC_NAME,
        "design_source": "../20261010_pair_axis_design_v1/README.md",
        "latest_source": "../20261010_pair_axis_v1/README.md",
        "study_manifest": "../20261010_pair_axis_v1/ARTIFACT_MANIFEST.json",
        "independent_review": "../20261010_pair_axis_review_v1/REVIEW_MEMO.md",
        "independent_validation": "../20261010_pair_axis_review_v1/outputs/independent_validation_receipt.json",
        "supplemental_validation": "../20261010_pair_axis_review_v1/outputs/supplemental_fixed_cutoff_receipt.json",
        "study_date": "2026-10-10",
        "publication_date": PUBLICATION_DATE,
        "period_start": "2024-01-05",
        "period_end": "2026-09-19",
        "partial_2026": True,
        "evaluation_races": 1779,
        "evaluation_runners": 17412,
        "evaluation_days": 269,
        "all_unordered_triples_recomputed": 402808,
        "population": "posthoc_normal_complete_full_roster_current_distance_cohort",
        "primary_comparison": "maximum_joint_pair_vs_unrestricted_top_k; K=3,4; both saved arms",
        "saved_unrestricted_k6_hit_counts": {"matched_baseline": 407, "candidate": 423},
        "independent_calculation_validation": "passed",
        "performance_improvement_confirmed": False,
        "independent_future_validation": False,
        "causal_effect_identified": False,
        "new_training_calls": 0,
        "database_query_performed": False,
        "operationally_applied": False,
        "status": "retrospective_no_fit_calculation_validation_passed_performance_improvement_unconfirmed_no_promotion",
    })
    register["latest_study"] = "jeju/research/20261010_pair_axis_v1"
    register["latest_verification"] = "jeju/research/20261010_pair_axis_review_v1/outputs/independent_validation_receipt.json"
    register["latest_status"] = "calculation_validation_passed_performance_improvement_unconfirmed_no_operational_promotion"

    source_manifest = load_json(SNAPSHOT_DIR / "source_manifest.json")
    old_files = source_manifest["files"]
    if any(item["path"].startswith(STUDY_PREFIXES) for item in old_files):
        raise RuntimeError("pair-axis source rows already exist in frozen central manifest")
    if TOPIC_NAME in {Path(item["path"]).name for item in old_files}:
        raise RuntimeError("topic 21 already exists in source manifest")

    topic_path = "jeju/research/conclusions/" + TOPIC_NAME
    payload_bytes = PAYLOAD.read_bytes()
    rows.append({
        "path": topic_path,
        "role": "conclusion_or_management",
        "sha256": payload_hash,
        "bytes": len(payload_bytes),
    })
    managed_replacements = {
        "jeju/research/conclusions/README.md": ("conclusion_or_management", readme.encode("utf-8")),
        "jeju/research/conclusions/SOURCES.md": ("conclusion_or_management", sources.encode("utf-8")),
        "jeju/research/conclusions/research_register.json": (
            "research_registry", (json.dumps(register, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ),
    }
    for path, (role, contents) in managed_replacements.items():
        matches = [item for item in old_files if item["path"] == path]
        if len(matches) != 1:
            raise RuntimeError(f"expected one existing source-manifest row for {path}")
        matches[0].update({"role": role, "sha256": digest(contents), "bytes": len(contents)})

    for row in rows:
        if any(item["path"] == row["path"] for item in old_files):
            raise RuntimeError(f"source path already exists: {row['path']}")
    source_manifest["files"].extend(rows)
    source_manifest["updated_at"] = PUBLICATION_DATE
    source_manifest["managed_files_bytes_excluding_this_manifest"] = sum(
        int(item["bytes"]) for item in source_manifest["files"]
    )
    source_manifest["latest_study"] = "jeju/research/20261010_pair_axis_v1"
    source_manifest["latest_verification"] = "jeju/research/20261010_pair_axis_review_v1/outputs/independent_validation_receipt.json"
    source_manifest["latest_status"] = "calculation_validation_passed_performance_improvement_unconfirmed_no_operational_promotion"
    verification = source_manifest.setdefault("verification", {})
    verification.update({
        "pair_axis_ticket_budget_calculation_validation": "passed_independent_full_cohort_reconstruction_and_frozen_output_parity",
        "pair_axis_ticket_budget_performance_improvement": "unconfirmed; all four primary date-paired intervals include zero",
        "pair_axis_ticket_budget_future_validation": False,
        "pair_axis_ticket_budget_operational_promotion": False,
        "pair_axis_ticket_budget_previous_topic_count": len(old_ids),
        "pair_axis_ticket_budget_topic_count_after_append": len(old_ids) + 1,
        "pair_axis_ticket_budget_previous_source_rows_preserved": True,
        "pair_axis_ticket_budget_legacy_full_rehash_performed": False,
        "pair_axis_ticket_budget_snapshot": "jeju/research/20261010_pair_axis_review_v1/central_snapshot_before_topic21/snapshot_manifest.json",
        "source_manifest_self_hash_excluded": True,
    })

    changes = {
        TOPIC_NAME: payload_bytes,
        "README.md": readme.encode("utf-8"),
        "SOURCES.md": sources.encode("utf-8"),
        "research_register.json": (json.dumps(register, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        "source_manifest.json": (json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    }
    return changes


def apply_changes(changes: dict[str, bytes]) -> None:
    originals = {name: (CENTRAL / name).read_bytes() if (CENTRAL / name).exists() else None for name in changes}
    with tempfile.TemporaryDirectory(prefix="topic21-", dir=CENTRAL) as staging_dir:
        staging = Path(staging_dir)
        for name, contents in changes.items():
            (staging / name).write_bytes(contents)
        try:
            for name in changes:
                os.replace(staging / name, CENTRAL / name)
        except OSError:
            for name, original in originals.items():
                destination = CENTRAL / name
                if original is None:
                    destination.unlink(missing_ok=True)
                else:
                    destination.write_bytes(original)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the guarded append to central conclusions")
    parser.add_argument("--confirm-apply-topic21", action="store_true", help="required with --apply")
    args = parser.parse_args()
    if args.apply != args.confirm_apply_topic21:
        parser.error("apply requires both --apply and --confirm-apply-topic21; neither is used for dry run")

    snapshot = load_json(SNAPSHOT_DIR / "snapshot_manifest.json")
    verify_central_snapshot(snapshot)
    for relative, expected in PINNED.items():
        assert_hash(relative, expected)
    payload_hash = file_hash(PAYLOAD)
    rows = source_rows(payload_hash)
    changes = build_changes(snapshot, rows, payload_hash)
    print(f"central CAS: PASS ({len(snapshot['files'])} frozen files; topic 21 absent)")
    print("protected topics 12, 19, 20: PASS")
    print(f"source rows to append: {len(rows)} (3 scoped study folders plus topic 21)")
    print(f"files to write: {', '.join(changes)}")
    for name, contents in changes.items():
        print(f"  {name}: {len(contents)} bytes sha256={digest(contents)}")
    if args.apply:
        verify_central_snapshot(snapshot)
        apply_changes(changes)
        print("apply: completed")
    else:
        print("apply: not run (read-only dry run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

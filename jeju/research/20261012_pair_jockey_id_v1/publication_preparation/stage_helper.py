"""Prepare a compare-and-swap receipt for the five central research files.

The helper deliberately has no apply operation. Run ``snapshot`` only after
the study and independent review are complete, build ``after/`` from their
official reports, then run ``seal`` for root to review and apply.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
REVIEW = ROOT / "jeju/research/20261012_pair_jockey_id_review_v1"
CENTRAL = ROOT / "jeju/research/conclusions"
HERE = STUDY / "publication_preparation"
A_MANIFEST = STUDY / "ARTIFACT_MANIFEST.json"
A_ARTIFACT_FIELD = "local_artifacts"
REVIEW_MANIFEST = REVIEW / "ARTIFACT_MANIFEST.json"
REVIEW_ARTIFACT_FIELD = "local_artifacts"
ALLOWED_EXTERNAL_ROOTS = (ROOT, Path("/Users/kimyongjin/.codex/skills/code-security").resolve())
NAMES = (
    "22_DIRECT_PAIR_TOP3_MODEL.md",
    "README.md",
    "SOURCES.md",
    "research_register.json",
    "source_manifest.json",
)
TARGET_TOPIC = "pair_top3_direct_20261011"
REFRESHED_CENTRAL_ROWS = {
    "jeju/research/conclusions/22_DIRECT_PAIR_TOP3_MODEL.md",
    "jeju/research/conclusions/README.md",
    "jeju/research/conclusions/SOURCES.md",
    "jeju/research/conclusions/research_register.json",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def inside(path: Path, parent: Path) -> Path:
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(parent.resolve()), f"path escaped expected directory: {path}")
    return resolved


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def snapshot() -> None:
    """Take the final fresh snapshot immediately before staging begins."""
    before = HERE / "before"
    after = HERE / "after"
    require(not before.exists() and not after.exists(), "snapshot already exists; use a fresh preparation directory")
    HERE.mkdir(parents=True, exist_ok=True)
    before.mkdir()
    after.mkdir()
    for name in NAMES:
        source = inside(CENTRAL / name, CENTRAL)
        with (before / name).open("xb") as stream:
            stream.write(source.read_bytes())
    print(dump_json({"status": "SNAPSHOTTED", "before_sha256": hashes(before)}), end="")


def hashes(folder: Path) -> dict[str, str]:
    inside(folder, HERE)
    return {name: sha256(inside(folder / name, HERE)) for name in NAMES}


def verify_register(before: Path, after: Path) -> None:
    prior = read_json(before / "research_register.json")
    staged = read_json(after / "research_register.json")
    prior_topics = {topic["id"]: topic for topic in prior["topics"]}
    staged_topics = {topic["id"]: topic for topic in staged["topics"]}
    require(len(prior_topics) == len(prior["topics"]) == 25, "prior register must have 25 unique topics")
    require(len(staged_topics) == len(staged["topics"]) == 25, "staged register must retain 25 unique topics")
    require(prior_topics.keys() == staged_topics.keys(), "topic IDs changed")
    require(TARGET_TOPIC in prior_topics, "target topic missing from prior register")
    for topic_id in prior_topics.keys() - {TARGET_TOPIC}:
        require(prior_topics[topic_id] == staged_topics[topic_id], f"unrelated topic changed: {topic_id}")
    old_target = prior_topics[TARGET_TOPIC]
    new_target = staged_topics[TARGET_TOPIC]
    require(new_target.get("previous_latest_source") == old_target.get("latest_source"),
            "prior topic-22 latest source was not preserved")
    require(new_target.get("operationally_applied") is False, "topic 22 must remain unapplied operationally")
    require(new_target.get("categorical_increment_confirmed") is True,
            "primary jockey-ID incremental gate must be recorded as confirmed")
    require(new_target.get("raw_top2_superiority_confirmed") is False,
            "secondary raw-Top2 superiority must remain unconfirmed")
    require(new_target.get("both_predeclared_gates_passed") is False,
            "overall two-gate result must remain unconfirmed")
    require(new_target.get("performance_improvement_confirmed") is False,
            "generic improvement field must reflect the overall two-gate decision")
    scope = str(new_target.get("performance_confirmation_scope", "")).lower()
    require("both predeclared gates" in scope and "raw top2" in scope,
            "register must define generic improvement as the joint two-gate scope")


def verify_source_manifest(before: Path, after: Path) -> list[str]:
    prior = read_json(before / "source_manifest.json")
    staged = read_json(after / "source_manifest.json")
    old_rows = {row["path"]: row for row in prior["files"]}
    new_rows = {row["path"]: row for row in staged["files"]}
    require(len(old_rows) == len(prior["files"]), "prior source manifest has duplicate paths")
    require(len(new_rows) == len(staged["files"]), "staged source manifest has duplicate paths")
    require("jeju/research/conclusions/source_manifest.json" not in new_rows,
            "source manifest must exclude itself")

    for path, row in old_rows.items():
        if path in REFRESHED_CENTRAL_ROWS:
            staged_row = new_rows.get(path)
            require(staged_row is not None, f"refreshed central row missing: {path}")
            file_name = Path(path).name
            staged_file = after / file_name
            require(staged_row.get("sha256") == sha256(staged_file), f"central hash mismatch: {path}")
            require(staged_row.get("bytes") == staged_file.stat().st_size, f"central size mismatch: {path}")
        else:
            require(new_rows.get(path) == row, f"existing source row changed: {path}")

    added = sorted(new_rows.keys() - old_rows.keys())
    require(set(added) == EXPECTED_ADDITIONS, "new source rows differ from the actual A/C artifact manifests")
    for path in added:
        require("publication_preparation/" not in path, f"staging artifacts must not self-reference: {path}")
        source = inside(ROOT / path, ROOT)
        row = new_rows[path]
        require(sha256(source) == row.get("sha256"), f"new source hash mismatch: {path}")
        require(source.stat().st_size == row.get("bytes"), f"new source size mismatch: {path}")
    expected_bytes = sum(row["bytes"] for row in staged["files"])
    require(staged.get("managed_files_bytes_excluding_this_manifest") == expected_bytes,
            "managed file byte total is incorrect")
    return added


def manifest_artifacts(folder: Path, manifest_path: Path, field: str) -> set[str]:
    """Read only explicitly listed local artifacts and verify their saved hashes."""
    manifest_path = inside(manifest_path, folder)
    manifest = read_json(manifest_path)
    entries = manifest.get(field)
    require(isinstance(entries, list) and entries, f"manifest field is missing or empty: {field}")
    expected: set[str] = set()
    for entry in entries:
        require(isinstance(entry, dict) and isinstance(entry.get("path"), str),
                f"invalid local artifact entry in {manifest_path}")
        relative = Path(entry["path"])
        require(not relative.is_absolute() and ".." not in relative.parts,
                f"unsafe artifact path in {manifest_path}: {relative}")
        artifact = inside(folder / relative, folder)
        require(sha256(artifact) == entry.get("sha256"), f"artifact hash mismatch: {artifact}")
        require(artifact.stat().st_size == entry.get("bytes"), f"artifact size mismatch: {artifact}")
        expected.add(str(artifact.relative_to(ROOT)))
    expected.add(str(manifest_path.relative_to(ROOT)))
    return expected


def verify_external_sources(manifest_specs: tuple[tuple[Path, Path], ...]) -> None:
    """Check pinned dependencies from both manifests without adding them as new rows."""
    pins: dict[str, dict[str, Any]] = {}
    for folder, manifest_path in manifest_specs:
        manifest = read_json(inside(manifest_path, folder))
        external_sources = manifest.get("external_sources")
        require(isinstance(external_sources, dict), f"external_sources must be a map: {manifest_path}")
        for relative, expected in external_sources.items():
            relpath = Path(relative)
            require(isinstance(expected, dict), f"invalid external source pin: {relative}")
            if relative in pins:
                require(pins[relative] == expected, f"A/C external source pins disagree: {relative}")
            pins[relative] = expected
    for relative, expected in pins.items():
        candidate = Path(relative)
        path = candidate.resolve(strict=True) if candidate.is_absolute() else (ROOT / candidate).resolve(strict=True)
        require(any(path.is_relative_to(root) for root in ALLOWED_EXTERNAL_ROOTS),
                f"external source outside approved read-only roots: {relative}")
        require(path.is_file(), f"external source is not a file: {relative}")
        require(sha256(path) == expected.get("sha256"), f"external source hash changed: {relative}")
        require(path.stat().st_size == expected.get("bytes"), f"external source size changed: {relative}")


EXPECTED_ADDITIONS: set[str] = set()


def expected_source_additions() -> set[str]:
    study_files = manifest_artifacts(STUDY, A_MANIFEST, A_ARTIFACT_FIELD)
    review_files = manifest_artifacts(REVIEW, REVIEW_MANIFEST, REVIEW_ARTIFACT_FIELD)
    verify_external_sources(((STUDY, A_MANIFEST), (REVIEW, REVIEW_MANIFEST)))
    return study_files | review_files


def seal() -> None:
    """Validate a complete staged set and write hashes for root's CAS apply."""
    before = HERE / "before"
    after = HERE / "after"
    require(before.is_dir() and after.is_dir(), "run snapshot first")
    require(set(path.name for path in before.iterdir()) == set(NAMES), "before snapshot file set changed")
    require(set(path.name for path in after.iterdir()) == set(NAMES), "after must contain exactly the five central files")
    before_hashes = hashes(before)
    after_hashes = hashes(after)
    verify_register(before, after)
    global EXPECTED_ADDITIONS
    EXPECTED_ADDITIONS = expected_source_additions()
    added = verify_source_manifest(before, after)

    receipt = {
        "status": "STAGED",
        "scope": "five central research files; apply is owned by root",
        "before_sha256": before_hashes,
        "after_sha256": after_hashes,
        "new_source_entries": added,
        "prior_source_entries": len(read_json(before / "source_manifest.json")["files"]),
        "new_source_entries_count": len(added),
        "other_topics_preserved": True,
        "operationally_applied": False,
    }
    receipt_path = HERE / "STAGING_RECEIPT.json"
    require(not receipt_path.exists(), "refusing to overwrite staging receipt")
    with receipt_path.open("x", encoding="utf-8") as stream:
        stream.write(dump_json(receipt))
    print(dump_json(receipt), end="")


if __name__ == "__main__":
    commands = {"snapshot": snapshot, "seal": seal}
    require(len(sys.argv) == 2 and sys.argv[1] in commands, "usage: stage_helper.py snapshot|seal")
    commands[sys.argv[1]]()

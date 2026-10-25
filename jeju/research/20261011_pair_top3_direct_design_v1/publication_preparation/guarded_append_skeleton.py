#!/usr/bin/env python3
"""Prepare, inspect, and (only after explicit approval) apply a narrow append.

All preparation outputs live in this review folder. Central writes are gated by
final A/B/C pins, a frozen result payload, a reviewed proposal hash, a separate
root approval record, and an explicit CLI confirmation. Do not use --apply
until root has approved that exact payload, source-pin set, snapshot, and diff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
PREP = Path(__file__).resolve().parent
STUDY = PREP.parent
CENTRAL = ROOT / "jeju/research/conclusions"
CONFIG_PATH = PREP / "publication_manifest.json"
PROPOSAL_DIR = PREP / "prepared_append"
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
TOPIC_FILE_RE = re.compile(r"^\d{2}_[A-Z0-9_]+\.md$")
TOPIC_ID_RE = re.compile(r"^[a-z0-9_]+$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PROTECTED_PREFIXES = {12, 19, 20, 21}
EXPECTED_SCOPES = {
    "A": "jeju/research/20261011_pair_top3_direct_v1",
    "B": "jeju/research/20261011_pair_top3_direct_design_v1",
    "C": "jeju/research/20261011_pair_top3_direct_review_v1",
}
MANAGED_CENTRAL_NAMES = {
    "README.md",
    "SOURCES.md",
    "research_register.json",
    "source_manifest.json",
}


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_repo_path(relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path or "\x00" in relative_path:
        raise RuntimeError(f"unsafe repository-relative path: {relative_path!r}")
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != relative_path:
        raise RuntimeError(f"unsafe repository-relative path: {relative_path!r}")
    unresolved = ROOT / candidate
    cursor = ROOT
    for part in candidate.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RuntimeError(f"source path traverses a symlink: {relative_path}")
    resolved = unresolved.resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise RuntimeError(f"path escapes repository root: {relative_path}")
    if resolved.is_symlink() or not resolved.is_file():
        raise RuntimeError(f"expected a regular source file: {relative_path}")
    return resolved


def checked_label(label: str) -> str:
    if not LABEL_RE.fullmatch(label):
        raise RuntimeError("snapshot label must use only letters, digits, '_' or '-' (max 48 chars)")
    return label


def checked_snapshot_dir(label: str) -> Path:
    label = checked_label(label)
    base = PREP.resolve()
    candidate = (PREP / label).resolve()
    if not candidate.is_relative_to(base) or candidate == base:
        raise RuntimeError("snapshot directory escapes publication_preparation")
    central = CENTRAL.resolve()
    if candidate == central or central.is_relative_to(candidate):
        raise RuntimeError("snapshot path overlaps the central conclusions directory")
    return candidate


def central_files() -> list[Path]:
    central = CENTRAL.resolve()
    if not central.is_relative_to(ROOT.resolve()):
        raise RuntimeError("central conclusions path escapes repository")
    entries = sorted(central.iterdir(), key=lambda path: path.name)
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise RuntimeError("central directory contains a symlink or non-file; stop for manual review")
    return entries


def numbered_topics(directory: Path) -> list[str]:
    return sorted(
        path.name
        for path in directory.iterdir()
        if re.fullmatch(r"\d{2}_.+\.md", path.name)
    )


def registry_inventory(directory: Path) -> dict:
    register = json.loads((directory / "research_register.json").read_text(encoding="utf-8"))
    topics = register.get("topics")
    if not isinstance(topics, list):
        raise RuntimeError("research_register topics is not a list")
    topic_ids = [item.get("id") for item in topics]
    if any(not isinstance(item, str) or not item for item in topic_ids):
        raise RuntimeError("research_register contains a topic without a valid id")
    if len(topic_ids) != len(set(topic_ids)):
        raise RuntimeError("research_register contains duplicate topic ids")
    topic_files = numbered_topics(directory)
    max_number = max((int(name[:2]) for name in topic_files), default=None)
    return {
        "current_registry_topic_count": len(topics),
        "current_registry_topic_ids": topic_ids,
        "current_registry_latest_study": register.get("latest_study"),
        "current_registry_last_topic_id": topic_ids[-1] if topic_ids else None,
        "numbered_topic_files": topic_files,
        "max_numbered_topic_prefix": max_number,
        "provisional_next_numbered_prefix": max_number + 1 if max_number is not None else 0,
    }


def capture_snapshot(label: str) -> Path:
    destination = checked_snapshot_dir(label)
    if destination.exists():
        raise RuntimeError(f"snapshot already exists; choose a new label: {destination.name}")
    destination.mkdir(parents=False)
    files: dict[str, dict] = {}
    try:
        for source in central_files():
            data = source.read_bytes()
            (destination / source.name).write_bytes(data)
            files[source.name] = {"sha256": sha256_bytes(data), "bytes": len(data)}
        inventory = registry_inventory(destination)
        explicitly_protected = {
            name: files[name]
            for name in inventory["numbered_topic_files"]
            if int(name[:2]) in PROTECTED_PREFIXES
        }
        manifest = {
            "snapshot_of": "jeju/research/conclusions",
            "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "purpose": "prepublication compare-and-swap baseline",
            "central_file_count": len(files),
            "files": files,
            **inventory,
            "provisional_number_warning": "re-enumerate central files and register at finalization; do not reserve this number",
            "explicitly_protected_existing_topics": explicitly_protected,
            "central_write_performed": False,
        }
        (destination / "snapshot_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return destination
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def load_snapshot(label: str) -> tuple[Path, dict, str]:
    directory = checked_snapshot_dir(label)
    manifest_path = directory / "snapshot_manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError(f"snapshot manifest missing: {manifest_path}")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("snapshot_of") != "jeju/research/conclusions":
        raise RuntimeError("snapshot target mismatch")
    expected = manifest.get("files")
    if not isinstance(expected, dict) or len(expected) != manifest.get("central_file_count"):
        raise RuntimeError("snapshot file inventory is malformed")
    if any(Path(name).name != name or name in {"", ".", ".."} for name in expected):
        raise RuntimeError("snapshot contains an unsafe filename")
    for name, record in expected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"snapshot copy missing or unsafe: {name}")
        if sha256_file(path) != record.get("sha256") or path.stat().st_size != int(record.get("bytes", -1)):
            raise RuntimeError(f"snapshot copy hash mismatch: {name}")
    inventory = registry_inventory(directory)
    for field, observed in inventory.items():
        if manifest.get(field) != observed:
            raise RuntimeError(f"snapshot registry/topic inventory mismatch: {field}")
    return directory, manifest, sha256_bytes(manifest_bytes)


def verify_snapshot(label: str) -> tuple[Path, dict, str]:
    directory, manifest, manifest_hash = load_snapshot(label)
    expected = manifest["files"]
    current = {path.name: path for path in central_files()}
    if set(current) != set(expected):
        added = sorted(set(current) - set(expected))
        missing = sorted(set(expected) - set(current))
        raise RuntimeError(f"central CAS failed; added={added}, missing={missing}")
    changed = []
    for name, record in expected.items():
        actual_hash = sha256_file(current[name])
        actual_bytes = current[name].stat().st_size
        if actual_hash != record.get("sha256") or actual_bytes != int(record.get("bytes", -1)):
            changed.append(name)
    if changed:
        raise RuntimeError(f"central CAS failed; changed files={sorted(changed)}")
    for name, record in manifest.get("explicitly_protected_existing_topics", {}).items():
        if name not in current or sha256_file(current[name]) != record["sha256"]:
            raise RuntimeError(f"protected old topic changed: {name}")
    for name in manifest.get("numbered_topic_files", []):
        if name not in current or sha256_file(current[name]) != expected[name]["sha256"]:
            raise RuntimeError(f"existing numbered topic changed: {name}")
    return directory, manifest, manifest_hash


def require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise RuntimeError(f"{label} must be a lowercase SHA-256")
    return value


def verify_pinned_file(path_value: object, expected_hash: object, expected_bytes: object, label: str) -> tuple[Path, dict]:
    if not isinstance(path_value, str):
        raise RuntimeError(f"{label}.path must be a repository-relative string")
    path = checked_repo_path(path_value)
    expected_hash = require_sha(expected_hash, f"{label}.sha256")
    if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0:
        raise RuntimeError(f"{label}.bytes must be a nonnegative integer")
    actual_hash = sha256_file(path)
    actual_bytes = path.stat().st_size
    if actual_hash != expected_hash or actual_bytes != expected_bytes:
        raise RuntimeError(f"pinned file mismatch: {path_value}")
    return path, {"path": path_value, "sha256": actual_hash, "bytes": actual_bytes}


def scope_root_for(key: str) -> str:
    if not isinstance(key, str) or key not in EXPECTED_SCOPES:
        raise RuntimeError(f"unknown study scope {key!r}")
    return EXPECTED_SCOPES[key]


def load_scope_rows(scope: dict) -> tuple[dict, list[dict]]:
    key = scope.get("key")
    expected_root = scope_root_for(key)
    if scope.get("root") != expected_root:
        raise RuntimeError(f"scope root mismatch for {key}")
    expected_manifest_path = f"{expected_root}/ARTIFACT_MANIFEST.json"
    if scope.get("manifest_path") != expected_manifest_path:
        raise RuntimeError(f"scope {key} must pin its canonical ARTIFACT_MANIFEST.json")
    manifest_path, manifest_record = verify_pinned_file(
        scope.get("manifest_path"), scope.get("manifest_sha256"), scope.get("manifest_bytes"), f"scope {key} manifest"
    )
    if not manifest_path.as_posix().startswith((ROOT / expected_root).as_posix() + "/"):
        raise RuntimeError(f"scope {key} manifest lies outside its approved folder")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError(f"scope {key} artifact manifest must be a JSON object")
    source_rows = [{**manifest_record, "role": f"{key.lower()}_artifact_manifest"}]
    manifest_format = scope.get("manifest_format")
    if manifest_format in {"local_files", "artifacts"}:
        if manifest_format == "local_files":
            entries = manifest.get("local_files")
            if not isinstance(entries, list) or not entries:
                raise RuntimeError(f"scope {key} manifest has no nonempty local_files list")
            normalized_entries = []
            for index, item in enumerate(entries):
                if not isinstance(item, dict):
                    raise RuntimeError(f"scope {key} local_files[{index}] is invalid")
                normalized_entries.append((item.get("path"), item, True))
        else:
            entries = manifest.get("artifacts")
            if not isinstance(entries, dict) or not entries:
                raise RuntimeError(f"scope {key} manifest has no nonempty artifacts map")
            normalized_entries = [(relative, item, False) for relative, item in entries.items()]
        for path_value, item, repository_relative in normalized_entries:
            if not isinstance(item, dict):
                raise RuntimeError(f"scope {key} artifact record is invalid: {path_value!r}")
            if (
                not isinstance(path_value, str)
                or not path_value
                or "\\" in path_value
                or "\x00" in path_value
                or Path(path_value).is_absolute()
                or ".." in Path(path_value).parts
                or Path(path_value).as_posix() != path_value
            ):
                raise RuntimeError(f"scope {key} file lies outside its approved folder: {path_value!r}")
            if repository_relative:
                if not path_value.startswith(expected_root + "/"):
                    raise RuntimeError(f"scope {key} file lies outside its approved folder: {path_value!r}")
                repository_path = path_value
                display_path = path_value
            else:
                repository_path = f"{expected_root}/{path_value}"
                display_path = repository_path
            _, record = verify_pinned_file(repository_path, item.get("sha256"), item.get("bytes"), f"scope {key} file")
            role = item.get("role") or f"{key.lower()}_artifact"
            if not isinstance(role, str) or not role.strip():
                raise RuntimeError(f"scope {key} artifact role must be a nonempty string: {display_path}")
            source_rows.append({**record, "role": role})
    elif manifest_format in {"review_artifacts", "independent_review_artifacts"}:
        entries = manifest.get(manifest_format)
        if not isinstance(entries, dict) or not entries:
            raise RuntimeError(f"C manifest has no nonempty {manifest_format} map")
        for relative, item in sorted(entries.items()):
            if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise RuntimeError(f"unsafe C review-artifact path: {relative!r}")
            if not isinstance(item, dict):
                raise RuntimeError(f"C review-artifact record is invalid: {relative}")
            path_value = f"{expected_root}/{relative}"
            _, record = verify_pinned_file(path_value, item.get("sha256"), item.get("bytes"), "C review artifact")
            role = item.get("role") or "independent_review_artifact"
            if not isinstance(role, str) or not role.strip():
                raise RuntimeError(f"C review-artifact role must be a nonempty string: {relative}")
            if isinstance(item.get("status"), str) and item["status"].strip():
                role = f"{role}: {item['status'].strip()}"
            source_rows.append({**record, "role": role})
    else:
        raise RuntimeError(f"unsupported final manifest format for {key}: {manifest_format!r}")
    return manifest, source_rows


def load_final_inputs(config: dict, require_ready: bool = True) -> tuple[dict, list[dict], str, str, str]:
    if not isinstance(config, dict):
        raise RuntimeError("publication manifest must be a JSON object")
    if config.get("schema_version") != 1:
        raise RuntimeError("unsupported publication manifest schema_version")
    if require_ready and config.get("status") not in {"ready_to_prepare", "ready_to_apply"}:
        raise RuntimeError("final pins and result payload are absent; publication manifest is not ready")
    study_id = config.get("study_id")
    if not isinstance(study_id, str) or not TOPIC_ID_RE.fullmatch(study_id):
        raise RuntimeError("publication manifest study_id is missing or invalid")
    scopes = config.get("study_scopes")
    if not isinstance(scopes, list) or len(scopes) != 3 or any(not isinstance(scope, dict) for scope in scopes):
        raise RuntimeError("publication manifest must pin exactly one A, B, and C scope")
    if [scope.get("key") for scope in scopes].count("A") != 1 or [scope.get("key") for scope in scopes].count("B") != 1 or [scope.get("key") for scope in scopes].count("C") != 1:
        raise RuntimeError("publication manifest must pin exactly one A, B, and C scope")
    rows: list[dict] = []
    manifests = {}
    for scope in sorted(scopes, key=lambda item: item["key"]):
        manifest, scope_rows = load_scope_rows(scope)
        manifests[scope["key"]] = manifest
        rows.extend(scope_rows)
    paths = [row["path"] for row in rows]
    if len(paths) != len(set(paths)):
        raise RuntimeError("duplicate A/B/C source paths")
    payload = config.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("publication payload pin is missing")
    payload_path_value = payload.get("path")
    if not isinstance(payload_path_value, str) or not payload_path_value.startswith(EXPECTED_SCOPES["B"] + "/publication_preparation/payload/"):
        raise RuntimeError("publication payload must be inside the B publication_preparation/payload folder")
    payload_path, payload_record = verify_pinned_file(
        payload_path_value, payload.get("sha256"), payload.get("bytes"), "publication payload"
    )
    if payload_path.suffix.lower() != ".md" or payload_record["bytes"] == 0:
        raise RuntimeError("publication payload must be a nonempty Markdown file")
    source_pin_set_sha = sha256_bytes(canonical_json(sorted(rows, key=lambda row: row["path"])))
    payload_sha = payload_record["sha256"]
    rows.append({**payload_record, "role": "publication_payload"})
    if len({row["path"] for row in rows}) != len(rows):
        raise RuntimeError("publication payload path duplicates an A/B/C source row")
    return manifests, rows, source_pin_set_sha, payload_sha, payload_record["path"]


def validate_publication_fields(config: dict, manifest: dict) -> tuple[dict, str, dict]:
    publication = config.get("publication")
    if not isinstance(publication, dict):
        raise RuntimeError("publication metadata is missing")
    topic_id = publication.get("topic_id")
    filename = publication.get("filename")
    title = publication.get("title")
    if not isinstance(topic_id, str) or not TOPIC_ID_RE.fullmatch(topic_id):
        raise RuntimeError("publication topic_id is missing or invalid")
    if not isinstance(filename, str) or not TOPIC_FILE_RE.fullmatch(filename):
        raise RuntimeError("publication filename must be a two-digit numbered Markdown name")
    if not isinstance(title, str) or not title.strip():
        raise RuntimeError("publication title is missing")
    try:
        datetime.strptime(config.get("publication_date", ""), "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise RuntimeError("publication_date must be YYYY-MM-DD") from exc
    current_max = manifest.get("max_numbered_topic_prefix")
    number = int(filename[:2])
    if current_max is None or number != int(current_max) + 1:
        raise RuntimeError(f"new topic number must be recomputed from the fresh snapshot (expected {int(current_max or -1) + 1})")
    if topic_id in manifest.get("current_registry_topic_ids", []):
        raise RuntimeError(f"topic id already exists: {topic_id}")
    for field in ("readme_table_row", "readme_summary_block", "sources_entry"):
        if not isinstance(publication.get(field), str) or not publication[field].strip():
            raise RuntimeError(f"publication.{field} is not finalized")
    marker = publication.get("summary_marker")
    if not isinstance(marker, str) or not re.fullmatch(r"<!--[ \t]*[A-Za-z0-9_.:-]+[ \t]*-->", marker):
        raise RuntimeError("summary_marker must be a unique HTML comment marker")
    if marker not in publication["readme_summary_block"]:
        raise RuntimeError("README summary block does not contain its declared marker")
    if filename not in publication["readme_table_row"] or filename not in publication["readme_summary_block"]:
        raise RuntimeError("README row and summary must link the new conclusion filename")
    if filename not in publication["sources_entry"]:
        raise RuntimeError("SOURCES entry must link the new conclusion filename")
    registry_record = publication.get("register_record")
    if not isinstance(registry_record, dict):
        raise RuntimeError("publication.register_record is missing")
    if registry_record.get("id") != topic_id or registry_record.get("title") != title or registry_record.get("conclusion") != filename:
        raise RuntimeError("register record id/title/conclusion must match the publication fields")
    if registry_record.get("operationally_applied") is not False or registry_record.get("independent_future_validation") is not False:
        raise RuntimeError("register record must state no operational promotion and no independent future validation")
    if publication.get("pair_probability_is_full_joint_distribution") is not False:
        raise RuntimeError("pair output must not be described as a full joint distribution")
    if publication.get("ticket_probability_claimed") is not False or publication.get("exact_top2_objective") is not False:
        raise RuntimeError("publication must exclude ticket-probability and exact-Top2 claims")
    for field in ("registry_scope_append", "latest_study", "latest_verification", "latest_status"):
        if not isinstance(publication.get(field), str) or not publication[field].strip():
            raise RuntimeError(f"publication.{field} is not finalized")
    verification_updates = publication.get("verification_updates", {})
    if not isinstance(verification_updates, dict):
        raise RuntimeError("publication.verification_updates must be an object")
    if any(not isinstance(key, str) or not key.startswith("direct_pair_top3_") for key in verification_updates):
        raise RuntimeError("verification updates must use the direct_pair_top3_ namespace")
    return publication, filename, registry_record


def build_changes(config: dict, snapshot_dir: Path, snapshot_manifest: dict) -> tuple[dict[str, bytes], dict, list[dict], str, str]:
    manifests, rows, source_pin_set_sha, payload_sha, payload_path_value = load_final_inputs(config)
    publication, filename, registry_record = validate_publication_fields(config, snapshot_manifest)
    snapshot_bytes = (snapshot_dir / "snapshot_manifest.json").read_bytes()
    snapshot_sha = sha256_bytes(snapshot_bytes)
    snapshot_config = config.get("snapshot")
    if not isinstance(snapshot_config, dict) or snapshot_config.get("manifest_sha256") != snapshot_sha:
        raise RuntimeError("publication manifest snapshot pin is stale")
    if snapshot_config.get("label") != snapshot_dir.name:
        raise RuntimeError("publication manifest snapshot label mismatch")
    payload_bytes = checked_repo_path(payload_path_value).read_bytes()
    if sha256_bytes(payload_bytes) != payload_sha:
        raise RuntimeError("publication payload changed after pinning")
    old_names = set(snapshot_manifest["files"])
    if filename in old_names or (snapshot_dir / filename).exists():
        raise RuntimeError(f"new topic already exists: {filename}")
    if filename in {Path(row["path"]).name for row in json.loads((snapshot_dir / "source_manifest.json").read_text(encoding="utf-8"))["files"]}:
        raise RuntimeError(f"topic file already exists in central source manifest: {filename}")

    # README gets exactly one row in the topic table and one append-only block.
    readme = (snapshot_dir / "README.md").read_text(encoding="utf-8")
    if filename in readme or publication["summary_marker"] in readme:
        raise RuntimeError("new topic link or marker already exists in central README")
    table_anchor = "| [원 연구와 버전 목록]"
    if readme.count(table_anchor) != 1:
        raise RuntimeError("central README topic-table anchor is missing or ambiguous")
    table_row = publication["readme_table_row"].strip()
    if not table_row.startswith("| [") or not table_row.endswith("|"):
        raise RuntimeError("README table row must be one Markdown table row")
    readme = readme.replace(table_anchor, table_row + "\n" + table_anchor, 1)
    readme = readme.rstrip() + "\n\n" + publication["readme_summary_block"].strip() + "\n"

    sources = (snapshot_dir / "SOURCES.md").read_text(encoding="utf-8")
    sources_entry = publication["sources_entry"].strip()
    if filename in sources or sources_entry in sources:
        raise RuntimeError("new topic or source entry already exists in central SOURCES")
    sources = sources.rstrip() + "\n\n" + sources_entry + "\n"

    register = json.loads((snapshot_dir / "research_register.json").read_text(encoding="utf-8"))
    original_topics = json.loads(json.dumps(register["topics"], ensure_ascii=False))
    old_ids = [item["id"] for item in register["topics"]]
    if len(old_ids) != register_inventory_count(snapshot_manifest):
        raise RuntimeError("snapshot register inventory count mismatch")
    if registry_record["id"] in old_ids:
        raise RuntimeError(f"topic id already exists in central register: {registry_record['id']}")
    register["topics"].append(registry_record)
    if register["topics"][:-1] != original_topics:
        raise RuntimeError("proposal changed an existing registry topic")
    register["updated_at"] = config["publication_date"]
    scope_append = publication["registry_scope_append"].strip()
    register["scope"] = register.get("scope", "").rstrip("· ") + "· " + scope_append
    register["latest_study"] = publication["latest_study"]
    register["latest_verification"] = publication["latest_verification"]
    register["latest_status"] = publication["latest_status"]

    source_manifest = json.loads((snapshot_dir / "source_manifest.json").read_text(encoding="utf-8"))
    old_files = source_manifest.get("files")
    if not isinstance(old_files, list):
        raise RuntimeError("central source_manifest files is not a list")
    old_paths = [item.get("path") for item in old_files]
    if len(old_paths) != len(set(old_paths)):
        raise RuntimeError("central source manifest has duplicate old paths")
    original_source_rows = json.loads(json.dumps(old_files, ensure_ascii=False))
    new_rows = [dict(row) for row in rows]
    new_rows.append({
        "path": f"jeju/research/conclusions/{filename}",
        "role": "conclusion_or_management",
        "sha256": sha256_bytes(payload_bytes),
        "bytes": len(payload_bytes),
    })
    for row in new_rows:
        if row["path"] in old_paths:
            raise RuntimeError(f"source path already exists in central manifest: {row['path']}")
    old_prefixes = tuple(f"{root}/" for root in EXPECTED_SCOPES.values())
    if any(path.startswith(old_prefixes) for path in old_paths if isinstance(path, str)):
        raise RuntimeError("A/B/C study source rows already exist in central manifest")

    updated_readme = readme.encode("utf-8")
    updated_sources = sources.encode("utf-8")
    updated_register = (json.dumps(register, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    managed_replacements = {
        "README.md": ("conclusion_or_management", updated_readme),
        "SOURCES.md": ("conclusion_or_management", updated_sources),
        "research_register.json": ("research_registry", updated_register),
    }
    for name, (role, contents) in managed_replacements.items():
        path = f"jeju/research/conclusions/{name}"
        matches = [item for item in old_files if item.get("path") == path]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one existing source-manifest row for {path}")
        matches[0].update({"role": role, "sha256": sha256_bytes(contents), "bytes": len(contents)})
    expected_old_rows = json.loads(json.dumps(original_source_rows, ensure_ascii=False))
    replacement_by_path = {
        f"jeju/research/conclusions/{name}": (role, contents)
        for name, (role, contents) in managed_replacements.items()
    }
    for item in expected_old_rows:
        replacement = replacement_by_path.get(item.get("path"))
        if replacement is not None:
            role, contents = replacement
            item.update({"role": role, "sha256": sha256_bytes(contents), "bytes": len(contents)})
    if source_manifest["files"][:len(expected_old_rows)] != expected_old_rows:
        raise RuntimeError("proposal altered or reordered a prior source-manifest row")
    source_manifest["files"].extend(new_rows)
    source_manifest["updated_at"] = config["publication_date"]
    source_manifest["managed_files_bytes_excluding_this_manifest"] = sum(int(item["bytes"]) for item in source_manifest["files"])
    source_manifest["latest_study"] = publication["latest_study"]
    source_manifest["latest_verification"] = publication["latest_verification"]
    source_manifest["latest_status"] = publication["latest_status"]
    verification = source_manifest.setdefault("verification", {})
    if not isinstance(verification, dict):
        raise RuntimeError("central source manifest verification field is not an object")
    verification.update(publication["verification_updates"])
    verification.update({
        "direct_pair_top3_previous_topic_count": len(old_ids),
        "direct_pair_top3_topic_count_after_append": len(old_ids) + 1,
        "direct_pair_top3_previous_source_rows_preserved": True,
        "direct_pair_top3_numbered_topic_documents_preserved": True,
        "direct_pair_top3_snapshot_manifest_sha256": snapshot_sha,
        "source_manifest_self_hash_excluded": True,
    })
    updated_source_manifest = (json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    changes = {
        filename: payload_bytes,
        "README.md": updated_readme,
        "SOURCES.md": updated_sources,
        "research_register.json": updated_register,
        "source_manifest.json": updated_source_manifest,
    }
    if set(changes) != MANAGED_CENTRAL_NAMES | {filename}:
        raise RuntimeError("proposed central write set is broader than the approved narrow append")
    for old_topic_name in snapshot_manifest.get("numbered_topic_files", []):
        if old_topic_name in changes:
            raise RuntimeError(f"proposal would replace an existing numbered topic: {old_topic_name}")
    source_rows_sha = sha256_bytes(canonical_json(sorted(new_rows, key=lambda row: row["path"])))
    proposal_manifest = {
        "study_id": config["study_id"],
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot_label": snapshot_dir.name,
        "snapshot_manifest_sha256": snapshot_sha,
        "source_pin_set_sha256": source_pin_set_sha,
        "appended_source_rows_sha256": source_rows_sha,
        "payload_path": payload_path_value,
        "payload_sha256": payload_sha,
        "topic_id": publication["topic_id"],
        "topic_filename": filename,
        "old_registered_topic_count": len(old_ids),
        "registered_topic_count_after_append": len(old_ids) + 1,
        "old_numbered_topic_files": snapshot_manifest.get("numbered_topic_files", []),
        "old_numbered_topic_files_preserved": True,
        "central_write_set": sorted(changes),
        "proposed_files": {
            name: {"sha256": sha256_bytes(data), "bytes": len(data)}
            for name, data in sorted(changes.items())
        },
        "change_set_sha256": sha256_bytes(canonical_json([
            {"name": name, "sha256": sha256_bytes(data), "bytes": len(data)}
            for name, data in sorted(changes.items())
        ])),
        "root_approval_required_before_apply": True,
        "central_write_performed": False,
    }
    # Keep loaded manifests in scope to make explicit that A/B/C manifest pins
    # and every manifest-declared local artifact were validated before proposal.
    if set(manifests) != {"A", "B", "C"}:
        raise RuntimeError("not all three study manifests were validated")
    return changes, proposal_manifest, new_rows, source_pin_set_sha, snapshot_sha


def register_inventory_count(snapshot_manifest: dict) -> int:
    count = snapshot_manifest.get("current_registry_topic_count")
    if not isinstance(count, int) or count < 0:
        raise RuntimeError("snapshot registry topic count missing")
    return count


def load_ready_config() -> dict:
    if CONFIG_PATH.is_symlink() or not CONFIG_PATH.is_file():
        raise RuntimeError("publication_manifest.json is absent; final pins and result payload are not ready")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise RuntimeError("publication_manifest.json must contain a JSON object")
    if config.get("schema_version") != 1:
        raise RuntimeError("unsupported publication manifest schema_version")
    return config


def save_proposal(changes: dict[str, bytes], proposal_manifest: dict) -> None:
    if PROPOSAL_DIR.exists():
        raise RuntimeError("prepared_append already exists; remove it only after reviewing and archiving its contents")
    PROPOSAL_DIR.mkdir()
    try:
        for name, contents in changes.items():
            if Path(name).name != name:
                raise RuntimeError(f"unsafe proposed central filename: {name}")
            (PROPOSAL_DIR / name).write_bytes(contents)
        (PROPOSAL_DIR / "proposal_manifest.json").write_text(
            json.dumps(proposal_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception:
        shutil.rmtree(PROPOSAL_DIR, ignore_errors=True)
        raise


def prepare() -> dict:
    config = load_ready_config()
    if config.get("status") != "ready_to_prepare":
        raise RuntimeError("publication manifest status must be ready_to_prepare")
    label = config.get("snapshot", {}).get("label") if isinstance(config.get("snapshot"), dict) else None
    if not isinstance(label, str):
        raise RuntimeError("fresh central snapshot label is missing")
    snapshot_dir, snapshot_manifest, _ = verify_snapshot(label)
    changes, proposal_manifest, _, _, _ = build_changes(config, snapshot_dir, snapshot_manifest)
    save_proposal(changes, proposal_manifest)
    return proposal_manifest


def verify_root_approval(config: dict, proposal_manifest: dict) -> None:
    approval = config.get("root_approval")
    if not isinstance(approval, dict) or approval.get("approved") is not True:
        raise RuntimeError("root approval is absent; central apply is forbidden")
    expected = {
        "approved_study_id": config["study_id"],
        "approved_payload_sha256": proposal_manifest["payload_sha256"],
        "approved_source_pin_set_sha256": proposal_manifest["source_pin_set_sha256"],
        "approved_snapshot_manifest_sha256": proposal_manifest["snapshot_manifest_sha256"],
        "approved_change_set_sha256": proposal_manifest["change_set_sha256"],
    }
    for field, value in expected.items():
        if approval.get(field) != value:
            raise RuntimeError(f"root approval {field} does not match the prepared append")
    if not isinstance(approval.get("approved_by"), str) or not approval["approved_by"].strip():
        raise RuntimeError("root approval record must name the approving authority")
    if not isinstance(approval.get("approved_at_utc"), str) or not approval["approved_at_utc"].strip():
        raise RuntimeError("root approval record must include an approval timestamp")


def verify_prepared_proposal(changes: dict[str, bytes], expected_manifest: dict) -> None:
    manifest_path = PROPOSAL_DIR / "proposal_manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError("prepared proposal manifest is missing")
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_names = set(changes) | {"proposal_manifest.json"}
    actual_names = {path.name for path in PROPOSAL_DIR.iterdir() if path.is_file() and not path.is_symlink()}
    if actual_names != expected_names:
        raise RuntimeError("prepared proposal directory has unexpected or missing files")
    for field in ("study_id", "snapshot_manifest_sha256", "source_pin_set_sha256", "payload_sha256", "topic_filename", "change_set_sha256", "central_write_set"):
        if saved.get(field) != expected_manifest.get(field):
            raise RuntimeError(f"prepared proposal differs from current final pins: {field}")
    for name, contents in changes.items():
        path = PROPOSAL_DIR / name
        if path.is_symlink() or not path.is_file() or path.read_bytes() != contents:
            raise RuntimeError(f"prepared central payload was changed after review: {name}")


def verify_after_apply(snapshot_manifest: dict, changes: dict[str, bytes], new_filename: str) -> None:
    expected_names = set(snapshot_manifest["files"]) | {new_filename}
    current = {path.name: path for path in central_files()}
    if set(current) != expected_names:
        raise RuntimeError("post-apply central file inventory mismatch")
    for name, record in snapshot_manifest["files"].items():
        if name in changes:
            expected_bytes = changes[name]
            if current[name].read_bytes() != expected_bytes:
                raise RuntimeError(f"post-apply changed central file mismatch: {name}")
        elif sha256_file(current[name]) != record["sha256"]:
            raise RuntimeError(f"post-apply old central object changed: {name}")
    if current[new_filename].read_bytes() != changes[new_filename]:
        raise RuntimeError("post-apply conclusion payload mismatch")
    for name in snapshot_manifest.get("numbered_topic_files", []):
        if sha256_file(current[name]) != snapshot_manifest["files"][name]["sha256"]:
            raise RuntimeError(f"post-apply old numbered topic changed: {name}")


def apply_changes(changes: dict[str, bytes], snapshot_manifest: dict, new_filename: str) -> None:
    expected_names = MANAGED_CENTRAL_NAMES | {new_filename}
    if set(changes) != expected_names:
        raise RuntimeError("apply write set is not exactly the narrow append allowlist")
    current_files = {path.name: path for path in central_files()}
    if new_filename in current_files:
        raise RuntimeError(f"new topic already exists in central directory: {new_filename}")
    originals = {name: (CENTRAL / name).read_bytes() for name in MANAGED_CENTRAL_NAMES}
    original_modes = {name: stat.S_IMODE((CENTRAL / name).stat().st_mode) for name in MANAGED_CENTRAL_NAMES}
    if set(current_files) != set(snapshot_manifest["files"]):
        raise RuntimeError("central file set changed before apply")
    with tempfile.TemporaryDirectory(prefix="direct-pair-append-", dir=PREP) as staging_name:
        staging = Path(staging_name)
        for name, contents in changes.items():
            target = staging / name
            target.write_bytes(contents)
            if name in original_modes:
                os.chmod(target, original_modes[name])
            else:
                os.chmod(target, 0o644)
        # The staging area is outside central, so this final snapshot check sees
        # only the user's central files immediately before the first replace.
        verify_snapshot_from_manifest(snapshot_manifest)
        replaced: list[str] = []
        try:
            for name in sorted(changes):
                os.replace(staging / name, CENTRAL / name)
                replaced.append(name)
        except OSError:
            rollback_errors = []
            for name in reversed(replaced):
                destination = CENTRAL / name
                if name in originals:
                    rollback_file = staging / f"rollback_{name}"
                    rollback_file.write_bytes(originals[name])
                    os.chmod(rollback_file, original_modes[name])
                    try:
                        os.replace(rollback_file, destination)
                    except OSError as rollback_error:
                        rollback_errors.append(f"{name}: {rollback_error}")
                else:
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError as rollback_error:
                        rollback_errors.append(f"{name}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError("apply failed and rollback was incomplete: " + "; ".join(rollback_errors))
            raise
    verify_after_apply(snapshot_manifest, changes, new_filename)


def verify_snapshot_from_manifest(manifest: dict) -> None:
    expected = manifest["files"]
    current = {path.name: path for path in central_files()}
    if set(current) != set(expected):
        raise RuntimeError("central CAS failed immediately before apply")
    for name, record in expected.items():
        if sha256_file(current[name]) != record["sha256"] or current[name].stat().st_size != int(record["bytes"]):
            raise RuntimeError(f"central CAS failed immediately before apply: {name}")


def run_apply(confirm_study_id: str) -> dict:
    config = load_ready_config()
    if config.get("status") != "ready_to_apply":
        raise RuntimeError("publication manifest status must be ready_to_apply")
    if confirm_study_id != config.get("study_id"):
        raise RuntimeError("--confirm-append must exactly match the approved study_id")
    label = config.get("snapshot", {}).get("label") if isinstance(config.get("snapshot"), dict) else None
    if not isinstance(label, str):
        raise RuntimeError("approved snapshot label is missing")
    snapshot_dir, snapshot_manifest, snapshot_sha = verify_snapshot(label)
    changes, proposal_manifest, _, _, _ = build_changes(config, snapshot_dir, snapshot_manifest)
    if proposal_manifest["snapshot_manifest_sha256"] != snapshot_sha:
        raise RuntimeError("snapshot changed after proposal preparation")
    verify_prepared_proposal(changes, proposal_manifest)
    verify_root_approval(config, proposal_manifest)
    apply_changes(changes, snapshot_manifest, proposal_manifest["topic_filename"])
    return proposal_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--capture-snapshot", metavar="LABEL", help="copy central files into this B review folder")
    action.add_argument("--verify-snapshot", metavar="LABEL", help="read-only CAS check against a saved snapshot")
    action.add_argument("--prepare", action="store_true", help="build only a proposed append under this B folder")
    action.add_argument("--apply", action="store_true", help="apply a separately root-approved prepared append")
    parser.add_argument("--confirm-append", metavar="STUDY_ID", help="required with --apply; must equal the approved study id")
    args = parser.parse_args()
    if args.confirm_append is not None and not args.apply:
        parser.error("--confirm-append is valid only with --apply")
    try:
        if args.capture_snapshot:
            destination = capture_snapshot(args.capture_snapshot)
            _, manifest, snapshot_hash = load_snapshot(args.capture_snapshot)
            print(f"snapshot captured under B review folder: {destination.relative_to(ROOT)}")
            print(f"central files={manifest['central_file_count']}; registered topics={manifest['current_registry_topic_count']}; max numbered prefix={manifest['max_numbered_topic_prefix']}")
            print(f"snapshot manifest sha256={snapshot_hash}")
            print("central write: none")
        elif args.verify_snapshot:
            _, manifest, snapshot_hash = verify_snapshot(args.verify_snapshot)
            print(f"central CAS: PASS ({manifest['central_file_count']} files; {manifest['current_registry_topic_count']} registered topics)")
            print("protected old topic files: PASS (all numbered documents byte-identical)")
            print(f"snapshot manifest sha256={snapshot_hash}")
            print("central write: none")
        elif args.prepare:
            proposal = prepare()
            print(f"prepared proposal only: {PROPOSAL_DIR.relative_to(ROOT)}")
            print(f"write set={proposal['central_write_set']}")
            print(f"change set sha256={proposal['change_set_sha256']}")
            print("central write: none")
        elif args.apply:
            if not args.confirm_append:
                parser.error("--apply requires --confirm-append STUDY_ID")
            proposal = run_apply(args.confirm_append)
            print(f"append applied for {proposal['study_id']}; change set {proposal['change_set_sha256']}")
            print("all prior numbered topic documents verified byte-identical")
        else:
            parser.error("choose exactly one action")
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

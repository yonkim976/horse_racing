#!/usr/bin/env python3
"""Resolve and verify the explicitly promoted prediction model profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nested_value(value: Any, dotted_key: str) -> Any:
    current = value
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted_key)
        current = current[part]
    return current


def fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))
    raise SystemExit(2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--domain", default="thoroughbred")
    parser.add_argument(
        "--registry", type=Path, default=Path("config/prediction_model_registry.json")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.repo_root.resolve()
    registry_path = args.registry
    if not registry_path.is_absolute():
        registry_path = root / registry_path
    if not registry_path.is_file():
        fail(f"registry not found: {registry_path}")

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if registry.get("schema_version") != 1:
        fail("unsupported registry schema_version")
    domain = registry.get("domains", {}).get(args.domain)
    if not domain:
        fail(f"domain is not registered: {args.domain}")
    active_name = domain.get("active_profile")
    profile = registry.get("profiles", {}).get(active_name)
    if not profile:
        fail(f"active profile is missing: {active_name}")
    if profile.get("domain") != args.domain or profile.get("status") != "production":
        fail(f"active profile is not a production {args.domain} profile")
    if profile.get("selection_policy") != "promoted_champion_only":
        fail("unsafe model selection policy")

    verified_files: list[dict[str, str]] = []
    for label, artifact in profile.get("artifacts", {}).items():
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not relative or not expected:
            fail(f"artifact path/hash missing: {label}")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            fail(f"artifact escapes repository: {label}")
        if not path.is_file():
            fail(f"artifact not found: {label}: {relative}")
        actual = sha256_file(path)
        if actual != expected:
            fail(f"artifact hash mismatch: {label}: expected={expected} actual={actual}")
        verified_files.append({"name": label, "path": relative, "sha256": actual})

    for gate in profile.get("verification_gates", []):
        relative = gate.get("path")
        path = root / relative
        if not path.is_file():
            fail(f"verification file not found: {relative}")
        document = json.loads(path.read_text(encoding="utf-8"))
        for key, expected in gate.get("requires", {}).items():
            try:
                actual = nested_value(document, key)
            except KeyError:
                fail(f"verification key missing: {relative}:{key}")
            if actual != expected:
                fail(
                    f"verification gate failed: {relative}:{key} "
                    f"expected={expected!r} actual={actual!r}"
                )

    result = {
        "ok": True,
        "domain": args.domain,
        "active_profile": active_name,
        "champion_id": profile.get("champion_id"),
        "probability_contract": profile.get("probability_contract"),
        "combination_algorithm_version": profile.get("combination_algorithm_version"),
        "registry_path": str(registry_path.relative_to(root)),
        "registry_sha256": sha256_file(registry_path),
        "verified_artifacts": verified_files,
        "components": profile.get("components", {}),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (OSError, json.JSONDecodeError) as exc:
        fail(str(exc))

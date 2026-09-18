#!/usr/bin/env python3
"""Append one validated canonical prediction bundle to the configured database."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

import polars as pl
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from horse_racing.config import get_settings  # noqa: E402
from horse_racing.db.engine import create_engine_for_url  # noqa: E402
from horse_racing.db.models import (  # noqa: E402
    ModelPrediction,
    ModelPredictionExplanation,
    PredictionModelComponent,
    PredictionRun,
)
from horse_racing.services.prediction_ledger import (  # noqa: E402
    PredictionComponentMetadata,
    PredictionLedgerError,
    PredictionModelMetadata,
    PredictionPublicationContext,
    publish_predictions,
    sha256_file,
    verify_prediction_hash,
)


def fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))
    raise SystemExit(2)


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def require_string(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"metadata.{key} must be a non-empty string")
    return value


def sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_registry(metadata: dict[str, object]) -> tuple[dict[str, object], str]:
    registry_path = REPO_ROOT / "config/prediction_model_registry.json"
    registry_hash = sha256_file(registry_path)
    if registry_hash != require_string(metadata, "registry_sha256"):
        raise ValueError("registry SHA-256 differs from publication metadata")
    registry = read_json(registry_path)
    if not isinstance(registry, dict):
        raise ValueError("model registry is not a JSON object")
    domain_name = require_string(metadata, "domain")
    domains = registry.get("domains")
    profiles = registry.get("profiles")
    if not isinstance(domains, dict) or not isinstance(profiles, dict):
        raise ValueError("model registry domains/profiles are missing")
    domain = domains.get(domain_name)
    if not isinstance(domain, dict):
        raise ValueError(f"domain is not registered: {domain_name}")
    profile_name = domain.get("active_profile")
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict) or profile.get("status") != "production":
        raise ValueError("active production profile is missing")
    if profile.get("selection_policy") != "promoted_champion_only":
        raise ValueError("unsafe registry selection policy")
    for artifact_name, artifact in profile.get("artifacts", {}).items():
        if not isinstance(artifact, dict):
            raise ValueError(f"invalid artifact entry: {artifact_name}")
        artifact_path = REPO_ROOT / str(artifact.get("path", ""))
        expected_hash = artifact.get("sha256")
        if not artifact_path.is_file() or sha256_file(artifact_path) != expected_hash:
            raise ValueError(f"active artifact verification failed: {artifact_name}")
    if require_string(metadata, "probability_contract") != profile.get(
        "probability_contract"
    ):
        raise ValueError("probability contract differs from active profile")
    if require_string(metadata, "combination_algorithm_version") != profile.get(
        "combination_algorithm_version"
    ):
        raise ValueError("combination algorithm differs from active profile")
    return profile, registry_hash


def verify_destination(database_url: str, expected_project_ref: str, allow_sqlite: bool) -> None:
    parsed = urlparse(database_url)
    if parsed.scheme.startswith("sqlite"):
        if not allow_sqlite:
            raise ValueError(
                "SQLite write is disabled; configure HORSE_RACING_DATABASE_URL for Supabase"
            )
        return
    if not parsed.scheme.startswith("postgresql") and parsed.scheme != "postgres":
        raise ValueError("only PostgreSQL/Supabase or explicitly allowed SQLite is supported")
    username = unquote(parsed.username or "")
    host = parsed.hostname or ""
    if expected_project_ref not in username and expected_project_ref not in host:
        raise ValueError("configured database does not match --expected-project-ref")


def load_database_url(gcp_secret: str | None, gcp_project: str | None) -> str:
    if gcp_secret is None:
        return get_settings().database_url
    if not gcp_project:
        raise ValueError("--gcp-project is required with --gcp-secret")
    result = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={gcp_secret}",
            f"--project={gcp_project}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("could not access the configured database secret")
    database_url = result.stdout.strip()
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix(
            "postgresql://"
        )
    elif database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    return database_url


def load_components(
    metadata: dict[str, object], profile: dict[str, object]
) -> tuple[PredictionComponentMetadata, ...]:
    raw_components = metadata.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise ValueError("metadata.components must be a non-empty array")
    profile_artifacts = profile.get("artifacts", {})
    if not isinstance(profile_artifacts, dict):
        raise ValueError("active profile artifacts are invalid")
    active_hashes = {
        value.get("sha256")
        for value in profile_artifacts.values()
        if isinstance(value, dict)
    }
    components = []
    for raw in raw_components:
        if not isinstance(raw, dict):
            raise ValueError("each component must be an object")
        artifact_hash = require_string(raw, "artifact_sha256")
        if artifact_hash not in active_hashes:
            raise ValueError(
                f"component artifact is not in active profile: {raw.get('component')}"
            )
        parameters = raw.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("component.parameters must be an object")
        components.append(
            PredictionComponentMetadata(
                component=require_string(raw, "component"),
                model_version=require_string(raw, "model_version"),
                candidate_name=require_string(raw, "candidate_name"),
                artifact_sha256=artifact_hash,
                metadata_sha256=(
                    str(raw["metadata_sha256"])
                    if raw.get("metadata_sha256") is not None
                    else None
                ),
                algorithm_version=(
                    str(raw["algorithm_version"])
                    if raw.get("algorithm_version") is not None
                    else None
                ),
                parameters=parameters,
            )
        )
    return tuple(components)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("--publication-mode", choices=("live", "historical"), required=True)
    parser.add_argument("--expected-project-ref", required=True)
    parser.add_argument("--gcp-secret")
    parser.add_argument("--gcp-project")
    parser.add_argument("--confirm-write", action="store_true")
    parser.add_argument("--allow-sqlite", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--published-at-ms", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.confirm_write:
        fail("database append requires --confirm-write")
    bundle_dir = args.bundle_dir.resolve()
    runner_path = bundle_dir / "runner_predictions.parquet"
    metadata_path = bundle_dir / "publication_metadata.json"
    explanations_path = bundle_dir / "runner_explanations.json"
    for path in (runner_path, metadata_path, explanations_path):
        if not path.is_file():
            fail(f"bundle file not found: {path}")

    try:
        metadata_raw = read_json(metadata_path)
        if not isinstance(metadata_raw, dict) or metadata_raw.get("schema_version") != 1:
            raise ValueError("unsupported publication metadata schema")
        metadata = metadata_raw
        expected_runner_hash = metadata.get("runner_predictions_sha256")
        if expected_runner_hash is not None and sha256_file(runner_path) != expected_runner_hash:
            raise ValueError("runner_predictions.parquet SHA-256 mismatch")
        expected_explanation_hash = metadata.get("runner_explanations_sha256")
        if expected_explanation_hash is not None and sha256_file(
            explanations_path
        ) != expected_explanation_hash:
            raise ValueError("runner_explanations.json SHA-256 mismatch")

        profile, registry_hash = verify_registry(metadata)
        components = load_components(metadata, profile)
        predictions = pl.read_parquet(runner_path)
        explanation_raw = read_json(explanations_path)
        if not isinstance(explanation_raw, list):
            raise ValueError("runner_explanations.json must be an array")
        explanations = pl.DataFrame(explanation_raw, strict=False)

        database_url = load_database_url(args.gcp_secret, args.gcp_project)
        verify_destination(database_url, args.expected_project_ref, args.allow_sqlite)
        engine = create_engine_for_url(database_url)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        publication_context = PredictionPublicationContext(
            domain=require_string(metadata, "domain"),
            prediction_stage=require_string(metadata, "prediction_stage"),
            registry_sha256=registry_hash,
            input_card_sha256=require_string(metadata, "input_card_sha256"),
            source_card_at_ms=int(metadata["source_card_at_ms"]),
            history_cutoff_date=date.fromisoformat(
                require_string(metadata, "history_cutoff_date")
            ),
            data_availability_status=require_string(
                metadata, "data_availability_status"
            ),
            probability_contract=require_string(metadata, "probability_contract"),
            combination_algorithm_version=require_string(
                metadata, "combination_algorithm_version"
            ),
            parent_public_id=(
                str(metadata["parent_public_id"])
                if metadata.get("parent_public_id") is not None
                else None
            ),
        )
        model_metadata = PredictionModelMetadata(
            experiment_run_id=require_string(metadata, "experiment_run_id"),
            model_type=require_string(metadata, "model_type"),
            dataset_version=require_string(metadata, "dataset_version"),
            as_of_policy=require_string(metadata, "as_of_policy"),
            feature_hash=require_string(metadata, "feature_hash"),
            model_artifact_sha256=require_string(metadata, "model_artifact_sha256"),
        )

        with factory() as session:
            summary = publish_predictions(
                session,
                predictions,
                metadata=model_metadata,
                feature_cutoff_at_ms=int(metadata["feature_cutoff_at_ms"]),
                publication_mode=args.publication_mode,
                published_at_ms=args.published_at_ms,
                notes=(str(metadata["notes"]) if metadata.get("notes") else None),
                publication_context=publication_context,
                model_components=components,
                runner_details=predictions,
                explanations=explanations,
            )
            stored_run = session.scalar(
                select(PredictionRun).where(PredictionRun.public_id == summary.public_id)
            )
            if stored_run is None or not verify_prediction_hash(session, summary.public_id):
                raise RuntimeError("stored prediction hash verification failed")
            expected_run_values = {
                "domain": publication_context.domain,
                "prediction_stage": publication_context.prediction_stage,
                "registry_sha256": publication_context.registry_sha256,
                "input_card_sha256": publication_context.input_card_sha256,
                "probability_contract": publication_context.probability_contract,
                "combination_algorithm_version": (
                    publication_context.combination_algorithm_version
                ),
                "publication_content_sha256": summary.publication_content_sha256,
            }
            for field_name, expected_value in expected_run_values.items():
                if getattr(stored_run, field_name) != expected_value:
                    raise RuntimeError(f"stored run field differs: {field_name}")
            prediction_count = session.scalar(
                select(func.count(ModelPrediction.id)).where(
                    ModelPrediction.prediction_run_id == stored_run.id
                )
            )
            component_count = session.scalar(
                select(func.count(PredictionModelComponent.id)).where(
                    PredictionModelComponent.prediction_run_id == stored_run.id
                )
            )
            explanation_count = session.scalar(
                select(func.count(ModelPredictionExplanation.id))
                .join(ModelPrediction)
                .where(ModelPrediction.prediction_run_id == stored_run.id)
            )
            if prediction_count != predictions.height:
                raise RuntimeError("stored runner row count differs from bundle")
            if component_count != len(components):
                raise RuntimeError("stored component count differs from bundle")
            if explanation_count != explanations.height:
                raise RuntimeError("stored explanation count differs from bundle")
            stored_component_hashes = set(
                session.scalars(
                    select(PredictionModelComponent.artifact_sha256).where(
                        PredictionModelComponent.prediction_run_id == stored_run.id
                    )
                )
            )
            if stored_component_hashes != {
                component.artifact_sha256 for component in components
            }:
                raise RuntimeError("stored model artifact hashes differ from bundle")

        print(
            json.dumps(
                {
                    "ok": True,
                    "public_id": summary.public_id,
                    "prediction_run_id": summary.prediction_run_id,
                    "publication_mode": summary.publication_mode,
                    "race_date_local": summary.race_date_local,
                    "races": summary.race_count,
                    "runner_rows": summary.entry_count,
                    "explanation_rows": explanations.height,
                    "predictions_sha256": summary.predictions_sha256,
                    "publication_content_sha256": summary.publication_content_sha256,
                    "bundle_metadata_sha256": sha256_json(metadata),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        PredictionLedgerError,
        SQLAlchemyError,
    ) as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()

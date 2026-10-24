"""Run the explicitly promoted Seoul/Busan training-state model; no network/DB writes."""

from pathlib import Path
from datetime import datetime, timedelta, timezone
import argparse, json, sys, uuid

try:
    import torch  # noqa: F401 -- selects the macOS OpenMP runtime before LightGBM
except ImportError:
    pass
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "production_models/thoroughbred_training_state_20261025_v1"
sys.path.insert(0, str(BUNDLE))
import features
import inference


def require(condition, message="Invalid model input"):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc)


def iso(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(t.tzinfo is not None, "Model validation failed")
    return t


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--card", type=Path)
    group.add_argument("--prepared-features", type=Path)
    parser.add_argument("--card-metadata", type=Path)
    parser.add_argument("--sources", type=Path, default=BUNDLE / "source_manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--entry-map",
        type=Path,
        help="Optional validated mapping to actual DB race/entry IDs; never guessed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Retrospective replay only; cannot produce a live publication envelope",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Pre-registration dry-run using the frozen candidate assets",
    )
    args = parser.parse_args()
    require(not args.output.exists(), "Immutable output directory already exists")
    require(not args.preview or args.dry_run, "Model validation failed")
    if args.preview:
        profile = None
        registry_hash = None
    else:
        profile, registry_hash = inference.active_profile()
    started = now()
    card_path = args.card or args.prepared_features
    card_hash = features.sha(card_path)
    card_metadata = {}
    card_observed = None
    if args.card_metadata:
        card_metadata = json.loads(args.card_metadata.read_text())
        require(card_metadata["card_sha256"] == card_hash, "Model validation failed")
        card_observed = iso(card_metadata["observed_at_utc"])
        require(card_observed <= started, "Model validation failed")
    if args.prepared_features:
        require(
            args.dry_run, "Live inference requires the full result-free card and source rebuild"
        )
        frame = pd.read_parquet(args.prepared_features)
        feature_meta = {"dry_run": True, "prepared_fixture": True}
    else:
        card = pd.read_parquet(args.card)
        if not args.dry_run:
            require(
                args.card_metadata and card_observed is not None,
                "A live run needs a timestamped card manifest",
            )
            require(
                card_metadata.get("complete_card") is True, "Card completeness attestation required"
            )
            counts = card.groupby(["meet", "race_date", "race_no"]).size()
            expected = card_metadata["runner_counts_by_race"]
            actual = {
                f"{int(m)}:{pd.Timestamp(d).strftime('%Y%m%d')}:{int(r)}": int(n)
                for (m, d, r), n in counts.items()
            }
            require(actual == expected, "Snapshot roster count mismatch")
            for key, date in card_metadata["scheduled_at_utc_by_race"].items():
                require(
                    key in actual and started <= iso(date) - timedelta(minutes=30),
                    "Prediction deadline passed",
                )
            require(
                set(actual) == set(card_metadata["scheduled_at_utc_by_race"]),
                "Model validation failed",
            )
        frame, feature_meta = features.build(
            card, args.sources, dry_run=args.dry_run, progress=True
        )
    predictions, explanations, tickets, checks = inference.predict(frame)
    require(features.sha(card_path) == card_hash, "Input card changed during inference")
    spec = inference.load_spec()
    spec_hash = features.sha(BUNDLE / "model_spec.json")
    if args.entry_map:
        require(
            not args.preview, "Do not prepare publication identities from an unregistered candidate"
        )
        mapping = pd.read_parquet(args.entry_map)
        keys = ["race_key", "horse_id"]
        needed = keys + ["race_id", "race_entry_id"]
        require(
            set(needed) <= set(mapping) and not mapping.duplicated(keys).any(),
            "Model validation failed",
        )
        require(
            mapping.race_id.gt(0).all() and mapping.race_entry_id.gt(0).all(),
            "Model validation failed",
        )
        require(
            (mapping.race_id % 1).eq(0).all() and (mapping.race_entry_id % 1).eq(0).all(),
            "Model validation failed",
        )
        require(
            set(map(tuple, mapping[keys].to_numpy()))
            == set(map(tuple, predictions[keys].to_numpy())),
            "DB card identities differ",
        )
        predictions = predictions.drop(columns="race_id").merge(
            mapping[needed], on=keys, validate="one_to_one"
        )
        lookup = mapping.set_index(keys).race_entry_id
        for row in explanations:
            row["race_entry_id"] = int(lookup.loc[(row["race_key"], row["horse_id"])])
    source_ms = int(card_observed.timestamp() * 1000) if card_observed else None
    for row in explanations:
        row["source_cutoff_at_ms"] = source_ms
    args.output.mkdir(parents=True)
    frame.to_parquet(args.output / "prepared_features.parquet", index=False, compression="zstd")
    predictions.to_parquet(
        args.output / "runner_predictions.parquet", index=False, compression="zstd"
    )
    (args.output / "runner_explanations.json").write_text(
        json.dumps(explanations, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    (args.output / "recommendations.json").write_text(
        json.dumps(tickets, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    meta = {
        "schema_version": 1,
        "model_profile": inference.PROFILE,
        "model_spec_sha256": spec_hash,
        "registry_sha256": registry_hash,
        "generated_at_utc": started.isoformat(),
        "completed_at_utc": now().isoformat(),
        "card_sha256": card_hash,
        "source_card_observed_at_utc": card_observed.isoformat() if card_observed else None,
        "prediction_stage": "retrospective_dry_run" if args.dry_run else "initial_card",
        "source_metadata": feature_meta,
        "checks": checks,
        "dry_run": args.dry_run,
        "preview": args.preview,
        "canonical_db_identity_map_supplied": args.entry_map is not None,
        "database_writes": 0,
        "network_calls": 0,
        "probability_contract": spec["probability_contract"],
        "combination_algorithm_version": inference.ALGORITHM,
        "files": {p.name: features.sha(p) for p in args.output.iterdir() if p.is_file()},
    }
    (args.output / "run_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    if args.entry_map and not args.dry_run:
        require(profile and registry_hash and source_ms, "Model validation failed")
        temps = {
            m: {
                "set_temperature": json.loads(inference.checked_path(v["metadata"]).read_text())[
                    "temperature"
                ],
                "order_temperature": json.loads(inference.checked_path(v["metadata"]).read_text())[
                    "order_temperature"
                ],
            }
            for m, v in spec["venue_models"].items()
        }
        components = [
            {
                "component": name,
                "model_version": "personal_t2_2026",
                "candidate_name": "personal_t2",
                "artifact_sha256": spec_hash,
                "metadata_sha256": spec_hash,
                "algorithm_version": inference.ALGORITHM,
                "parameters": {
                    "venue_models": spec["venue_models"],
                    "temperatures_by_meet": temps,
                    "shared_coherent_joint": True,
                    "role": role,
                },
            }
            for name, role in [
                ("A", "runner_marginals"),
                ("B", "unordered_trio"),
                ("C", "exact_order"),
            ]
        ]
        envelope = {
            "schema_version": 1,
            "domain": "thoroughbred",
            "prediction_stage": "initial_card",
            "experiment_run_id": str(uuid.uuid4()),
            "model_type": "registered_main_prediction",
            "dataset_version": str(args.output),
            "as_of_policy": "T-2_history_current_card_before_start_minus30m",
            "feature_hash": features.sha(args.output / "prepared_features.parquet"),
            "model_artifact_sha256": spec_hash,
            "registry_sha256": registry_hash,
            "input_card_sha256": card_hash,
            "source_card_at_ms": source_ms,
            "history_cutoff_date": feature_meta["history_latest_date"],
            "feature_cutoff_at_ms": source_ms,
            "data_availability_status": "partial",
            "probability_contract": spec["probability_contract"],
            "combination_algorithm_version": inference.ALGORITHM,
            "parent_public_id": None,
            "components": components,
            "runner_predictions_sha256": features.sha(args.output / "runner_predictions.parquet"),
            "runner_explanations_sha256": features.sha(args.output / "runner_explanations.json"),
            "notes": "Promoted training-state model; fixed T-2 history, actual current card. Missing/older data are explicitly partial. Prepared locally; not published.",
        }
        (args.output / "publication_metadata.json").write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
    print(
        json.dumps(
            {
                "status": "passed",
                "profile": inference.PROFILE,
                "races": checks["races"],
                "runners": checks["runners"],
                "output": str(args.output),
                "dry_run": args.dry_run,
                "database_writes": 0,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

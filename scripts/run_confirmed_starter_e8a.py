"""Generate only synthetic E8-A replay evidence in an isolated directory.

Run from project root: .venv/bin/python -m scripts.run_confirmed_starter_e8a
No network, operating DB, real model, or historical outcome access.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from horse_racing.analysis.confirmed_starter_e8a import ShadowEvidenceStore

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/experiments/confirmed_starter_e8a_20260913_attempt4"
BASE = 2_000_000_000_000
PRESERVED = (
    "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m/dataset.parquet",
    "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m/manifest.json",
    "data/experiments/confirmed_starter_e3_20260911/artifact_manifest.json",
    "data/experiments/confirmed_starter_e4_diagnostic_20260911/artifact_manifest.json",
    "data/experiments/confirmed_starter_e5a_20260912/artifact_manifest.json",
    "data/experiments/confirmed_starter_e5b_race_objective_20260912/artifact_manifest.json",
    "data/experiments/confirmed_starter_e6b_20260913/artifact_manifest.json",
    "data/experiments/confirmed_starter_e7a_20260913_attempt4/artifact_manifest.json",
    "data/experiments/confirmed_starter_e7b_20260913/artifact_manifest.json",
    "data/experiments/model_runs.jsonl",
    "src/horse_racing/services/prediction_ledger.py",
    "src/horse_racing/db/models.py",
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hashes() -> dict[str, str]:
    return {relative: sha(ROOT / relative) for relative in PRESERVED}


def save_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite existing E8-A evidence: {OUTPUT}")
    before = hashes()
    OUTPUT.mkdir(parents=True)
    instant = BASE - 10

    def clock() -> int:
        return instant

    ledger = ShadowEvidenceStore.for_testing(OUTPUT / "shadow", clock)
    raw = json.dumps(
        {
            "schema": "synthetic_entry_sheet_v1",
            "timezone": "Asia/Seoul",
            "race_id": 7,
            "scheduled_at_ms": BASE + 1_800_000,
            "declared_count": 2,
            "status": "complete",
            "entries": [
                {"entry_id": 11, "horse_number": 1, "horse_id": "H11"},
                {"entry_id": 12, "horse_number": 2, "horse_id": "H12"},
            ],
        },
        sort_keys=True,
    ).encode()
    observation = ledger.observe_synthetic(
        source_id="synthetic/API26_2", request_at_ms=BASE - 20, body=raw
    )
    instant = BASE
    field = ledger.seal_field(observation_hash=observation, cutoff_at_ms=BASE)
    snapshot = ledger.snapshot(
        field_hash=field,
        population="F_t",
        rows=[
            {"entry_id": 11, "horse_number": 1, "horse_id": "H11", "features": {"x": 0.1}},
            {"entry_id": 12, "horse_number": 2, "horse_id": "H12", "features": {"x": 0.2}},
        ],
        feature_contracts={
            "x": {
                "source_observation_hash": observation,
                "available_at_ms": BASE - 10,
                "calculation_version": "synthetic-v1",
            }
        },
    )
    prediction = ledger.publish_synthetic(
        field_hash=field,
        snapshot_hash=snapshot,
        experiment_version="e8a-synthetic",
        model_version="uniform-v1",
        model_hash="a" * 64,
        cutoff_policy="start_minus_30m",
        model_population="F_t_synthetic",
        probabilities=[
            {"entry_id": 11, "horse_number": 1, "horse_id": "H11", "prob_win": 0.5},
            {"entry_id": 12, "horse_number": 2, "horse_id": "H12", "prob_win": 0.5},
        ],
    )
    instant = BASE + 1
    corrected_source = json.loads(raw)
    corrected_source["scheduled_at_ms"] = BASE + 2_400_000
    corrected_source["effective_at_ms"] = BASE - 100
    correction = ledger.observe_synthetic(
        source_id="synthetic/correction",
        request_at_ms=BASE,
        body=json.dumps(corrected_source, sort_keys=True).encode(),
    )
    outcome = ledger.append_outcome_event(
        prediction_hash=prediction,
        source_id="synthetic/result",
        body=b"DNS then correction",
        event_type="correction",
    )
    ledger.verify_chain()
    events = ledger.events()
    save_json(
        OUTPUT / "synthetic_replay.json",
        {
            "status": "completed_synthetic_only",
            "prospective_status": "not_activated",
            "actual_fits": 0,
            "actual_probability_publications": 0,
            "actual_performance_evaluations": 0,
            "event_count": len(events),
            "observation_hash": observation,
            "field_hash": field,
            "snapshot_hash": snapshot,
            "prediction_hash": prediction,
            "later_correction_hash": correction,
            "outcome_event_hash": outcome,
            "evaluation_status": "held_dns_policy_unconfirmed",
            "chain_verified": True,
        },
    )
    after = hashes()
    if before != after:
        raise RuntimeError("sealed upstream/operating file changed during replay")
    output_hashes = {
        str(path.relative_to(OUTPUT)): sha(path)
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file()
    }
    save_json(
        OUTPUT / "artifact_manifest.json",
        {
            "status": "completed_synthetic_only",
            "prospective_status": "not_activated",
            "preserved_hashes_before": before,
            "preserved_hashes_after": after,
            "output_hashes": output_hashes,
        },
    )


if __name__ == "__main__":
    main()

"""Reproducible synthetic-only E8-A R1-R4 replay; no network or operating DB.

Run: .venv/bin/python -m scripts.run_confirmed_starter_e8a_v2
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from horse_racing.analysis.confirmed_starter_e8a import ShadowContractError
from horse_racing.analysis.confirmed_starter_e8a_v2 import (
    CALCULATOR,
    FEATURE,
    ShadowEvidenceStoreV2,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/experiments/confirmed_starter_e8a_v2_20260913_attempt2"
BASE = 2_000_000_000_000
PRESERVED = (
    "docs/CONFIRMED_STARTER_E8A_2026-09-13.md",
    "src/horse_racing/analysis/confirmed_starter_e8a.py",
    "scripts/run_confirmed_starter_e8a.py",
    "tests/test_confirmed_starter_e8a.py",
    "src/horse_racing/analysis/pre_race_field_contract.py",
    "src/horse_racing/services/prediction_ledger.py",
    "src/horse_racing/db/models.py",
    "data/experiments/confirmed_starter_e7b_20260913/artifact_manifest.json",
    "data/experiments/model_runs.jsonl",
    "data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m/manifest.json",
)
NEW_SOURCES = (
    "src/horse_racing/analysis/confirmed_starter_e8a_v2.py",
    "scripts/run_confirmed_starter_e8a_v2.py",
    "tests/test_confirmed_starter_e8a_v2.py",
    "docs/CONFIRMED_STARTER_E8A_V2_CONTRACT_2026-09-13.md",
    "data/logs/confirmed_starter_e8a_independent_review_20260913.json",
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def raw(*, entries=None, race_id=7, effective=None) -> bytes:
    entries = entries or [
        {"entry_id": 11, "horse_number": 1, "horse_id": "H11"},
        {"entry_id": 12, "horse_number": 2, "horse_id": "H12"},
    ]
    return json.dumps(
        {
            "schema": "synthetic_entry_sheet_v1",
            "timezone": "Asia/Seoul",
            "race_id": race_id,
            "scheduled_at_ms": BASE + 1_800_000,
            "declared_count": len(entries),
            "status": "complete",
            "entries": entries,
            "effective_at_ms": effective,
        },
        sort_keys=True,
    ).encode()


class Clock:
    def __init__(self, value=BASE - 10):
        self.value = value

    def __call__(self):
        return self.value


def store(name: str):
    clock = Clock()
    return ShadowEvidenceStoreV2.for_testing(OUTPUT / name, clock), clock


def observe(s, clock, *, body=None, at=BASE - 10):
    clock.value = at
    return s.observe_synthetic(
        source_id="synthetic/API26_2", request_at_ms=at - 1, body=body or raw()
    )


def seal(s, clock):
    obs = observe(s, clock)
    clock.value = BASE
    return obs, s.seal_field(observation_hash=obs, cutoff_at_ms=BASE)


def rows():
    return [
        {"entry_id": 11, "horse_number": 1, "horse_id": "H11", "features": {FEATURE: 0.5}},
        {"entry_id": 12, "horse_number": 2, "horse_id": "H12", "features": {FEATURE: 1.0}},
    ]


def row_hash(items):
    body = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()


def contract(s, obs, items=None):
    items = items or rows()
    return {
        FEATURE: {
            "calculation_version": CALCULATOR,
            "dependency_observations": [obs],
            "dependency_ready_hashes": [s._observation_ack_hash(obs)],
            "available_at_ms": BASE,
            "result_hash": row_hash(items),
        }
    }


def snapshot(s, obs, fld):
    return s.snapshot(
        field_hash=fld, rows=rows(), feature_contracts=contract(s, obs), population="F_t"
    )


def prediction(s, fld, snap):
    return s.publish_synthetic(
        field_hash=fld,
        snapshot_hash=snap,
        experiment_version="e8a-v2-synthetic",
        model_version="uniform-v1",
        model_hash="a" * 64,
        cutoff_policy="start_minus_30m",
        model_population="F_t_synthetic",
        probabilities=[
            {"entry_id": 11, "horse_number": 1, "horse_id": "H11", "prob_win": 0.5},
            {"entry_id": 12, "horse_number": 2, "horse_id": "H12", "prob_win": 0.5},
        ],
    )


def rejected(action) -> str:
    try:
        action()
    except ShadowContractError as exc:
        return str(exc)
    raise RuntimeError("independent counterexample unexpectedly accepted")


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite {OUTPUT}")
    preserved = list(PRESERVED) + [
        str(path.relative_to(ROOT))
        for path in sorted(
            (ROOT / "data/experiments/confirmed_starter_e8a_20260913_attempt4").rglob("*")
        )
        if path.is_file()
    ]
    before = {name: sha(ROOT / name) for name in preserved}
    source_hashes = {name: sha(ROOT / name) for name in NEW_SOURCES}
    OUTPUT.mkdir(parents=True)
    prior = json.loads((ROOT / NEW_SOURCES[-1]).read_text())
    cases = {}

    s, clock = store("R1_drift")
    obs = observe(s, clock)
    ticks = iter((BASE, BASE + 1, BASE + 2, BASE + 3))
    s._clock = lambda: next(ticks)
    cases["R1"] = {
        "before_accepted": prior["R1_seal_clock_drift"]["accepted"],
        "after": rejected(lambda: s.seal_field(observation_hash=obs, cutoff_at_ms=BASE)),
    }
    pending = next(e for e in s.events() if e["kind"] == "v2_field_pending")
    cases["R1"]["admission"] = s._admission(pending["event_hash"], "v2_field_admission")
    s.verify_chain()

    s, clock = store("R2_superseded")
    old = observe(s, clock)
    one = [{"entry_id": 11, "horse_number": 1, "horse_id": "H11"}]
    new = observe(s, clock, body=raw(entries=one, effective=BASE - 5), at=BASE - 5)
    clock.value = BASE
    cases["R2"] = {
        "before_accepted": prior["R2_superseded_source"]["accepted"],
        "after": rejected(lambda: s.seal_field(observation_hash=old, cutoff_at_ms=BASE)),
    }
    fld = s.seal_field(observation_hash=new, cutoff_at_ms=BASE)
    cases["R2"]["selected_keys"] = s._field(fld)["expected_keys"]
    s.verify_chain()

    s, clock = store("R3_late")
    obs, fld = seal(s, clock)
    clock.value = BASE + 1_800_001
    feature_contract = contract(s, obs)
    feature_contract[FEATURE]["available_at_ms"] = clock.value
    cases["R3"] = {
        "before_accepted": prior["R3_after_race_creation"]["accepted"],
        "after": rejected(
            lambda: s.snapshot(
                field_hash=fld, rows=rows(), feature_contracts=feature_contract, population="F_t"
            )
        ),
    }
    cases["R3"]["new_snapshot_count"] = len(
        [e for e in s.events() if e["kind"] == "v2_snapshot_pending"]
    )
    s.verify_chain()

    s, clock = store("R4_fabricated")
    obs, fld = seal(s, clock)
    unrelated = observe(s, clock, body=raw(race_id=999), at=BASE)
    clock.value = BASE
    bad = rows()
    bad[0]["features"][FEATURE] = 999.0
    bad[1]["features"][FEATURE] = -999.0
    feature_contract = contract(s, obs, bad)
    feature_contract[FEATURE]["calculation_version"] = "nonexistent-calculator-v1"
    feature_contract[FEATURE]["dependency_observations"] = [unrelated]
    feature_contract[FEATURE]["available_at_ms"] = BASE - 10_000
    cases["R4"] = {
        "before_accepted": prior["R4_unbound_feature_provenance"]["accepted"],
        "after": rejected(
            lambda: s.snapshot(
                field_hash=fld, rows=bad, feature_contracts=feature_contract, population="F_t"
            )
        ),
    }
    s.verify_chain()

    s, clock = store("accepted_synthetic")
    obs, fld = seal(s, clock)
    snap = snapshot(s, obs, fld)
    pred = prediction(s, fld, snap)
    outcome = s.append_outcome_event(
        prediction_hash=pred,
        source_id="synthetic/result",
        body=b"DNS correction",
        event_type="correction",
    )
    s.verify_chain()
    save(
        OUTPUT / "replay.json",
        {
            "status": "completed_synthetic_only",
            "prospective_status": "not_activated",
            "reproduction": {
                "command": ".venv/bin/python -m scripts.run_confirmed_starter_e8a_v2",
                "runner": "scripts/run_confirmed_starter_e8a_v2.py",
                "tests": "tests/test_confirmed_starter_e8a_v2.py",
                "contract": "docs/CONFIRMED_STARTER_E8A_V2_CONTRACT_2026-09-13.md",
                "prior_review": "data/logs/confirmed_starter_e8a_independent_review_20260913.json",
            },
            "actual_collection": 0,
            "actual_tree_fits": 0,
            "actual_probability_publications": 0,
            "actual_performance_evaluations": 0,
            "counterexamples": cases,
            "accepted_synthetic": {
                "observation_hash": obs,
                "field_hash": fld,
                "snapshot_hash": snap,
                "prediction_hash": pred,
                "outcome_hash": outcome,
            },
        },
    )
    after = {name: sha(ROOT / name) for name in preserved}
    if before != after:
        raise RuntimeError("preserved E8-A/upstream artifact changed")
    output_hashes = {
        str(path.relative_to(OUTPUT)): sha(path)
        for path in sorted(OUTPUT.rglob("*"))
        if path.is_file()
    }
    save(
        OUTPUT / "artifact_manifest.json",
        {
            "status": "completed_synthetic_only",
            "prospective_status": "not_activated",
            "preserved_before": before,
            "preserved_after": after,
            "new_source_hashes": source_hashes,
            "output_hashes": output_hashes,
        },
    )


if __name__ == "__main__":
    main()

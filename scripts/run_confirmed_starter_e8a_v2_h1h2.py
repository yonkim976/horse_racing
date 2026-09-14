"""Synthetic H1/H2 replay only. Run: python -m scripts.run_confirmed_starter_e8a_v2_h1h2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from horse_racing.analysis.confirmed_starter_e8a import ShadowContractError
from horse_racing.analysis.confirmed_starter_e8a_v2 import CALCULATOR, FEATURE
from horse_racing.analysis.confirmed_starter_e8a_v2_h1h2 import (
    ShadowEvidenceStoreV2TimeChecked,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/experiments/confirmed_starter_e8a_v2_h1h2_20260913"
BASE = 2_000_000_000_000
PRESERVED = (
    "src/horse_racing/analysis/confirmed_starter_e8a_v2.py",
    "scripts/run_confirmed_starter_e8a_v2.py",
    "tests/test_confirmed_starter_e8a_v2.py",
    "docs/CONFIRMED_STARTER_E8A_V2_CONTRACT_2026-09-13.md",
    "docs/CONFIRMED_STARTER_E8A_V2_REMEDIATION_2026-09-13.md",
    "src/horse_racing/analysis/confirmed_starter_e8a.py",
    "scripts/run_confirmed_starter_e8a.py",
    "tests/test_confirmed_starter_e8a.py",
    "docs/CONFIRMED_STARTER_E8A_2026-09-13.md",
    "src/horse_racing/analysis/pre_race_field_contract.py",
    "data/experiments/confirmed_starter_e7b_20260913/artifact_manifest.json",
    "data/experiments/model_runs.jsonl",
)
SOURCES = (
    "src/horse_racing/analysis/confirmed_starter_e8a_v2_h1h2.py",
    "scripts/run_confirmed_starter_e8a_v2_h1h2.py",
    "tests/test_confirmed_starter_e8a_v2_h1h2.py",
    "docs/CONFIRMED_STARTER_E8A_V2_H1_H2_CONTRACT_2026-09-13.md",
    "data/logs/confirmed_starter_e8a_v2_independent_review_20260913.json",
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


class Clock:
    def __init__(self, value=BASE - 10):
        self.value = value

    def __call__(self):
        return self.value


def store(name):
    clock = Clock()
    return ShadowEvidenceStoreV2TimeChecked.for_testing(OUTPUT / name, clock), clock


def raw(entries=None, *, effective=None):
    entries = entries or [
        {"entry_id": 11, "horse_number": 1, "horse_id": "H11"},
        {"entry_id": 12, "horse_number": 2, "horse_id": "H12"},
    ]
    return json.dumps(
        {
            "schema": "synthetic_entry_sheet_v1",
            "timezone": "Asia/Seoul",
            "race_id": 7,
            "scheduled_at_ms": BASE + 1_800_000,
            "declared_count": len(entries),
            "status": "complete",
            "entries": entries,
            "effective_at_ms": effective,
        },
        sort_keys=True,
    ).encode()


def observe(s, clock, *, body=None, at=BASE - 10):
    clock.value = at
    return s.observe_synthetic(
        source_id="synthetic/API26_2", request_at_ms=at - 1, body=body or raw()
    )


def field(s, clock):
    obs = observe(s, clock)
    clock.value = BASE
    return obs, s.seal_field(observation_hash=obs, cutoff_at_ms=BASE)


def rows():
    return [
        {"entry_id": 11, "horse_number": 1, "horse_id": "H11", "features": {FEATURE: 0.5}},
        {"entry_id": 12, "horse_number": 2, "horse_id": "H12", "features": {FEATURE: 1.0}},
    ]


def contract(s, obs, available=BASE, feature_rows=None):
    feature_rows = feature_rows or rows()
    body = json.dumps(
        feature_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return {
        FEATURE: {
            "calculation_version": CALCULATOR,
            "dependency_observations": [obs],
            "dependency_ready_hashes": [s._observation_ack_hash(obs)],
            "available_at_ms": available,
            "result_hash": hashlib.sha256(body).hexdigest(),
        }
    }


def snapshot(s, obs, fld, *, available=BASE, feature_rows=None):
    feature_rows = feature_rows or rows()
    return s.snapshot(
        field_hash=fld,
        rows=feature_rows,
        feature_contracts=contract(s, obs, available, feature_rows),
        population="F_t",
    )


def prediction(s, fld, snap, *, model="uniform-v1"):
    return s.publish_synthetic(
        field_hash=fld,
        snapshot_hash=snap,
        experiment_version="h1h2-synthetic",
        model_version=model,
        model_hash="a" * 64,
        cutoff_policy="start_minus_30m",
        model_population="F_t_synthetic",
        probabilities=[
            {"entry_id": 11, "horse_number": 1, "horse_id": "H11", "prob_win": 0.5},
            {"entry_id": 12, "horse_number": 2, "horse_id": "H12", "prob_win": 0.5},
        ],
    )


def sequence(s, values):
    ticks = iter(values)
    s._clock = lambda: next(ticks)


def rejected(action):
    try:
        action()
    except ShadowContractError as exc:
        return str(exc)
    raise RuntimeError("counterexample was unexpectedly admitted")


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite {OUTPUT}")
    old_attempt = ROOT / "data/experiments/confirmed_starter_e8a_v2_20260913_attempt2"
    preserved = list(PRESERVED) + [
        str(path.relative_to(ROOT)) for path in sorted(old_attempt.rglob("*")) if path.is_file()
    ]
    before = {name: sha(ROOT / name) for name in preserved}
    sources = {name: sha(ROOT / name) for name in SOURCES}
    prior = json.loads((ROOT / SOURCES[-1]).read_text())["probes"]
    OUTPUT.mkdir(parents=True)
    evidence = {}

    s, clock = store("H1_field_rollback")
    obs = observe(s, clock)
    sequence(s, (BASE, BASE + 1, BASE, BASE + 2))
    evidence["H1_field"] = {
        "before_status": prior["H1_clock_regression"]["status"],
        "after": rejected(lambda: s.seal_field(observation_hash=obs, cutoff_at_ms=BASE)),
    }
    pending = next(e for e in s.events() if e["kind"] == "v2_field_pending")
    evidence["H1_field"]["pending_created_ms"] = pending["created_ms"]
    evidence["H1_field"]["admission_count"] = len(
        [e for e in s.events() if e["kind"] == "v2_field_admission"]
    )
    s.verify_chain()

    s, clock = store("H1_observation_rollback")
    sequence(s, (BASE - 10, BASE - 9, BASE - 8, BASE - 10, BASE + 1))
    evidence["H1_observation"] = {
        "after": rejected(
            lambda: s.observe_synthetic(
                source_id="synthetic/API26_2", request_at_ms=BASE - 11, body=raw()
            )
        )
    }
    evidence["H1_observation"]["ack_count"] = len(
        [e for e in s.events() if e["kind"] == "v2_observation_ack"]
    )
    s.verify_chain()

    s, clock = store("H1_snapshot_rollback")
    obs, fld = field(s, clock)
    sequence(s, (BASE, BASE, BASE + 1, BASE, BASE + 2))
    evidence["H1_snapshot"] = {"after": rejected(lambda: snapshot(s, obs, fld))}
    s.verify_chain()

    s, clock = store("H1_prediction_rollback")
    obs, fld = field(s, clock)
    snap = snapshot(s, obs, fld)
    sequence(s, (BASE, BASE + 1, BASE, BASE + 2))
    evidence["H1_prediction"] = {"after": rejected(lambda: prediction(s, fld, snap))}
    s.verify_chain()

    s, clock = store("H2_future")
    obs, fld = field(s, clock)
    evidence["H2"] = {
        "before_snapshot_admission": prior["H2_future_available"]["snapshot_admission"],
        "before_prediction_admission": prior["H2_future_available"]["prediction_admission"],
        "cutoff_plus_1": rejected(lambda: snapshot(s, obs, fld, available=BASE + 1)),
        "start_plus_1": rejected(lambda: snapshot(s, obs, fld, available=BASE + 1_800_001)),
        "cutoff_minus_1": rejected(lambda: snapshot(s, obs, fld, available=BASE - 1)),
    }
    evidence["H2"]["future_snapshot_count"] = len(
        [e for e in s.events() if e["kind"] == "v2_snapshot_pending"]
    )
    s.verify_chain()

    s, clock = store("accepted_equal_boundary")
    obs, fld = field(s, clock)
    snap = snapshot(s, obs, fld, available=BASE)
    pred = prediction(s, fld, snap)
    clock.value = BASE + 1_800_001
    assert prediction(s, fld, snap) == pred
    evidence["normal"] = {
        "snapshot_admission": s._admission(snap, "v2_snapshot_admission")["status"],
        "prediction_admission": s._admission(pred, "v2_prediction_admission")["status"],
        "late_identical_retry_hash": pred,
    }
    s.verify_chain()

    save(
        OUTPUT / "replay.json",
        {
            "status": "completed_synthetic_only",
            "prospective_status": "not_activated",
            "actual_collection": 0,
            "actual_tree_fits": 0,
            "actual_probability_publications": 0,
            "actual_performance_evaluations": 0,
            "reproduction": {
                "command": ".venv/bin/python -m scripts.run_confirmed_starter_e8a_v2_h1h2",
                "runner": "scripts/run_confirmed_starter_e8a_v2_h1h2.py",
                "tests": "tests/test_confirmed_starter_e8a_v2_h1h2.py",
                "review": SOURCES[-1],
            },
            "cases": evidence,
        },
    )
    after = {name: sha(ROOT / name) for name in preserved}
    if before != after:
        raise RuntimeError("preserved v2/upstream hash changed")
    outputs = {
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
            "new_source_hashes": sources,
            "output_hashes": outputs,
        },
    )


if __name__ == "__main__":
    main()

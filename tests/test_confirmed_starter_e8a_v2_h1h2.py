"""H1/H2 probes, including transient clock rollback and cutoff boundaries."""

from __future__ import annotations

import hashlib
import json

import pytest

from horse_racing.analysis.confirmed_starter_e8a import ShadowContractError
from horse_racing.analysis.confirmed_starter_e8a_v2 import CALCULATOR, FEATURE
from horse_racing.analysis.confirmed_starter_e8a_v2_h1h2 import (
    ShadowEvidenceStoreV2TimeChecked,
)

BASE = 2_000_000_000_000


class Clock:
    def __init__(self, value=BASE - 10):
        self.value = value

    def __call__(self):
        return self.value


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


def setup(tmp_path):
    clock = Clock()
    return ShadowEvidenceStoreV2TimeChecked.for_testing(tmp_path / "isolated", clock), clock


def observe(store, clock, body=None, at=BASE - 10):
    clock.value = at
    return store.observe_synthetic(
        source_id="synthetic/API26_2", request_at_ms=at - 1, body=body or raw()
    )


def field(store, clock):
    obs = observe(store, clock)
    clock.value = BASE
    return obs, store.seal_field(observation_hash=obs, cutoff_at_ms=BASE)


def rows():
    return [
        {"entry_id": 11, "horse_number": 1, "horse_id": "H11", "features": {FEATURE: 0.5}},
        {"entry_id": 12, "horse_number": 2, "horse_id": "H12", "features": {FEATURE: 1.0}},
    ]


def contract(store, obs, *, available=BASE, feature_rows=None):
    feature_rows = feature_rows or rows()
    body = json.dumps(feature_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        FEATURE: {
            "calculation_version": CALCULATOR,
            "dependency_observations": [obs],
            "dependency_ready_hashes": [store._observation_ack_hash(obs)],
            "available_at_ms": available,
            "result_hash": hashlib.sha256(body.encode()).hexdigest(),
        }
    }


def snapshot(store, obs, fld, *, available=BASE, feature_rows=None):
    feature_rows = feature_rows or rows()
    return store.snapshot(
        field_hash=fld,
        rows=feature_rows,
        feature_contracts=contract(store, obs, available=available, feature_rows=feature_rows),
        population="F_t",
    )


def prediction(store, fld, snap, *, model="uniform-v1"):
    return store.publish_synthetic(
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


def sequence(store, values):
    ticks = iter(values)
    store._clock = lambda: next(ticks)


def test_h1_field_ack_rollback_then_recovery_never_accepts(tmp_path):
    store, clock = setup(tmp_path)
    obs = observe(store, clock)
    sequence(store, (BASE, BASE + 1, BASE, BASE + 2))
    with pytest.raises(ShadowContractError, match="clock regressed"):
        store.seal_field(observation_hash=obs, cutoff_at_ms=BASE)
    pending = next(e for e in store.events() if e["kind"] == "v2_field_pending")
    assert pending["created_ms"] == BASE + 1
    with pytest.raises(ShadowContractError, match="missing"):
        store._admission(pending["event_hash"], "v2_field_admission")
    restarted = ShadowEvidenceStoreV2TimeChecked.for_testing(store.root, lambda: BASE + 2)
    with pytest.raises(ShadowContractError, match="missing"):
        restarted._field(pending["event_hash"])


def test_h1_observation_ack_precedes_insert_is_not_ready(tmp_path):
    store, _ = setup(tmp_path)
    sequence(store, (BASE - 10, BASE - 9, BASE - 8, BASE - 10, BASE + 1))
    with pytest.raises(ShadowContractError, match="clock regressed"):
        store.observe_synthetic(source_id="synthetic/API26_2", request_at_ms=BASE - 11, body=raw())
    observation = next(e for e in store.events() if e["kind"] == "v2_observation")
    assert observation["created_ms"] == BASE - 8
    assert not [e for e in store.events() if e["kind"] == "v2_observation_ack"]
    restarted = ShadowEvidenceStoreV2TimeChecked.for_testing(store.root, lambda: BASE)
    with pytest.raises(ShadowContractError, match="unacknowledged"):
        restarted.seal_field(observation_hash=observation["event_hash"], cutoff_at_ms=BASE)


def test_h1_snapshot_and_prediction_ack_precede_insert(tmp_path):
    store, clock = setup(tmp_path)
    obs, fld = field(store, clock)
    sequence(store, (BASE, BASE, BASE + 1, BASE, BASE + 2))
    with pytest.raises(ShadowContractError, match="clock regressed"):
        snapshot(store, obs, fld)
    pending = next(e for e in store.events() if e["kind"] == "v2_snapshot_pending")
    with pytest.raises(ShadowContractError, match="missing"):
        store._admission(pending["event_hash"], "v2_snapshot_admission")

    store, clock = setup(tmp_path / "prediction")
    obs, fld = field(store, clock)
    snap = snapshot(store, obs, fld)
    sequence(store, (BASE, BASE + 1, BASE, BASE + 2))
    with pytest.raises(ShadowContractError, match="clock regressed"):
        prediction(store, fld, snap)
    pending = next(e for e in store.events() if e["kind"] == "v2_prediction_pending")
    with pytest.raises(ShadowContractError, match="missing"):
        store._admission(pending["event_hash"], "v2_prediction_admission")


def test_h1_late_completion_and_marker_failure_remain_ineligible(tmp_path):
    store, clock = setup(tmp_path)
    obs = observe(store, clock)
    sequence(store, (BASE, BASE, BASE + 1, BASE + 2))
    with pytest.raises(ShadowContractError, match="late/ineligible"):
        store.seal_field(observation_hash=obs, cutoff_at_ms=BASE)
    pending = next(e for e in store.events() if e["kind"] == "v2_field_pending")
    assert (
        store._admission(pending["event_hash"], "v2_field_admission")["status"] == "late_ineligible"
    )

    store, clock = setup(tmp_path / "marker")
    obs = observe(store, clock)
    sequence(store, (BASE, BASE, BASE, BASE - 1, BASE + 1))
    with pytest.raises(ShadowContractError, match="clock regressed"):
        store.seal_field(observation_hash=obs, cutoff_at_ms=BASE)
    pending = next(e for e in store.events() if e["kind"] == "v2_field_pending")
    with pytest.raises(ShadowContractError, match="missing"):
        store._admission(pending["event_hash"], "v2_field_admission")


def test_h2_equal_boundary_and_future_declarations(tmp_path):
    store, clock = setup(tmp_path)
    obs, fld = field(store, clock)
    snap = snapshot(store, obs, fld, available=BASE)
    assert store._admission(snap, "v2_snapshot_admission")["status"] == "accepted"
    assert prediction(store, fld, snap)

    for offset in (1, 1_800_001):
        other, other_clock = setup(tmp_path / f"future_{offset}")
        o, f = field(other, other_clock)
        with pytest.raises(ShadowContractError, match="exceeds cutoff"):
            snapshot(other, o, f, available=BASE + offset)
        assert not [e for e in other.events() if e["kind"] == "v2_snapshot_pending"]

    other, other_clock = setup(tmp_path / "too_early")
    o, f = field(other, other_clock)
    with pytest.raises(ShadowContractError, match="precedes calculation"):
        snapshot(other, o, f, available=BASE - 1)


def test_original_r1_r4_and_late_idempotent_retry(tmp_path):
    store, clock = setup(tmp_path / "r1")
    obs = observe(store, clock)
    sequence(store, (BASE, BASE + 1, BASE + 2, BASE + 3))
    with pytest.raises(ShadowContractError, match="late/ineligible"):
        store.seal_field(observation_hash=obs, cutoff_at_ms=BASE)

    store, clock = setup(tmp_path / "r2")
    old = observe(store, clock)
    one = [{"entry_id": 11, "horse_number": 1, "horse_id": "H11"}]
    new = observe(store, clock, body=raw(one, effective=BASE - 5), at=BASE - 5)
    clock.value = BASE
    with pytest.raises(ShadowContractError, match="superseded"):
        store.seal_field(observation_hash=old, cutoff_at_ms=BASE)
    assert store._field(store.seal_field(observation_hash=new, cutoff_at_ms=BASE))[
        "expected_keys"
    ] == [[7, 11]]

    store, clock = setup(tmp_path / "r3r4")
    obs, fld = field(store, clock)
    bad = rows()
    bad[0]["features"][FEATURE] = 999.0
    with pytest.raises(ShadowContractError, match="not reproduced"):
        snapshot(store, obs, fld, feature_rows=bad)
    snap = snapshot(store, obs, fld)
    accepted = prediction(store, fld, snap)
    clock.value = BASE + 1_800_001
    assert prediction(store, fld, snap) == accepted
    with pytest.raises(ShadowContractError, match="new prediction after cutoff"):
        prediction(store, fld, snap, model="new")
    with pytest.raises(ShadowContractError, match="exceeds cutoff"):
        snapshot(store, obs, fld, available=BASE + 1_800_001)

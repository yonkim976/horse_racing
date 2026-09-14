"""Independent E8-A R1-R4 counterexamples against the isolated v2 protocol."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

import pytest

from horse_racing.analysis.confirmed_starter_e8a import ShadowContractError
from horse_racing.analysis.confirmed_starter_e8a_v2 import (
    CALCULATOR,
    FEATURE,
    ShadowEvidenceStoreV2,
)

BASE = 2_000_000_000_000


class Clock:
    def __init__(self, value: int = BASE - 10) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def raw(*, race_id=7, entries=None, status="complete", effective=None, schedule=None) -> bytes:
    if entries is None:
        entries = [
            {"entry_id": 11, "horse_number": 1, "horse_id": "H11"},
            {"entry_id": 12, "horse_number": 2, "horse_id": "H12"},
        ]
    return json.dumps(
        {
            "schema": "synthetic_entry_sheet_v1",
            "timezone": "Asia/Seoul",
            "race_id": race_id,
            "scheduled_at_ms": schedule or BASE + 1_800_000,
            "declared_count": len(entries),
            "status": status,
            "entries": entries,
            "effective_at_ms": effective,
        },
        sort_keys=True,
    ).encode()


def setup(tmp_path):
    clock = Clock()
    store = ShadowEvidenceStoreV2.for_testing(tmp_path / "v2", clock)
    return store, clock


def observe(store, clock, *, body=None, source="synthetic/API26_2", at=BASE - 10):
    clock.value = at
    return store.observe_synthetic(source_id=source, request_at_ms=at - 1, body=body or raw())


def field(store, clock):
    obs = observe(store, clock)
    clock.value = BASE
    return obs, store.seal_field(observation_hash=obs, cutoff_at_ms=BASE)


def rows(entries=None):
    entries = entries or [
        {"entry_id": 11, "horse_number": 1, "horse_id": "H11"},
        {"entry_id": 12, "horse_number": 2, "horse_id": "H12"},
    ]
    return [
        {**item, "features": {FEATURE: item["horse_number"] / len(entries)}} for item in entries
    ]


def result_hash(feature_rows):
    text = json.dumps(feature_rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def contract(store, obs, feature_rows=None, *, available=BASE):
    feature_rows = feature_rows or rows()
    return {
        FEATURE: {
            "calculation_version": CALCULATOR,
            "dependency_observations": [obs],
            "dependency_ready_hashes": [store._observation_ack_hash(obs)],
            "available_at_ms": available,
            "result_hash": result_hash(feature_rows),
        }
    }


def snap(store, obs, fld, *, feature_rows=None, feature_contracts=None):
    feature_rows = feature_rows or rows()
    return store.snapshot(
        field_hash=fld,
        rows=feature_rows,
        feature_contracts=feature_contracts or contract(store, obs, feature_rows),
        population="F_t",
    )


def pred(store, fld, snapshot_hash, *, model="uniform-v1"):
    return store.publish_synthetic(
        field_hash=fld,
        snapshot_hash=snapshot_hash,
        experiment_version="e8a-v2-test",
        model_version=model,
        model_hash="a" * 64,
        cutoff_policy="start_minus_30m",
        model_population="F_t_synthetic",
        probabilities=[
            {"entry_id": 11, "horse_number": 1, "horse_id": "H11", "prob_win": 0.5},
            {"entry_id": 12, "horse_number": 2, "horse_id": "H12", "prob_win": 0.5},
        ],
    )


def test_r1_clock_advances_between_check_and_insert(tmp_path):
    store, clock = setup(tmp_path)
    obs = observe(store, clock)
    ticks = iter((BASE, BASE + 1, BASE + 2, BASE + 3))
    store._clock = lambda: next(ticks)
    with pytest.raises(ShadowContractError, match="late/ineligible"):
        store.seal_field(observation_hash=obs, cutoff_at_ms=BASE)
    pending = [e for e in store.events() if e["kind"] == "v2_field_pending"]
    assert len(pending) == 1 and pending[0]["created_ms"] == BASE + 1
    assert (
        store._admission(pending[0]["event_hash"], "v2_field_admission")["status"]
        == "late_ineligible"
    )
    with pytest.raises(ShadowContractError, match="not prospectively"):
        store._field(pending[0]["event_hash"])


def test_r1_commit_ack_after_cutoff_and_restart_failure(tmp_path, monkeypatch):
    store, clock = setup(tmp_path)
    obs = observe(store, clock)
    ticks = iter((BASE, BASE, BASE + 1, BASE + 2))
    store._clock = lambda: next(ticks)
    with pytest.raises(ShadowContractError, match="late/ineligible"):
        store.seal_field(observation_hash=obs, cutoff_at_ms=BASE)
    event = next(e for e in store.events() if e["kind"] == "v2_field_pending")
    assert event["created_ms"] == BASE
    assert (
        store._admission(event["event_hash"], "v2_field_admission")["field_commit_ack_ms"]
        == BASE + 1
    )

    other, other_clock = setup(tmp_path / "second")
    other_obs = observe(other, other_clock)
    original = other._insert_locked

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("before commit")

    monkeypatch.setattr(other, "_insert_locked", crash)
    other_clock.value = BASE
    with pytest.raises(OSError, match="before commit"):
        other.seal_field(observation_hash=other_obs, cutoff_at_ms=BASE)
    assert not [e for e in other.events() if e["kind"] == "v2_field_pending"]
    restarted = ShadowEvidenceStoreV2.for_testing(other.root, lambda: BASE)
    accepted = restarted.seal_field(observation_hash=other_obs, cutoff_at_ms=BASE)
    assert restarted._admission(accepted, "v2_field_admission")["status"] == "accepted"


def test_r2_latest_known_correction_supersedes_old_and_reduces_field(tmp_path):
    store, clock = setup(tmp_path)
    old = observe(store, clock)
    one = [{"entry_id": 11, "horse_number": 1, "horse_id": "H11"}]
    new = observe(store, clock, body=raw(entries=one, effective=BASE - 5), at=BASE - 5)
    clock.value = BASE
    with pytest.raises(ShadowContractError, match="superseded"):
        store.seal_field(observation_hash=old, cutoff_at_ms=BASE)
    fld = store.seal_field(observation_hash=new, cutoff_at_ms=BASE)
    assert store._field(fld)["expected_keys"] == [[7, 11]]
    assert store._field(fld)["selection_policy"].startswith("e8a_v2_")


def test_r2_latest_partial_conflict_future_effective_and_schedule(tmp_path):
    store, clock = setup(tmp_path)
    old = observe(store, clock)
    observe(store, clock, body=raw(status="partial"), at=BASE - 5)
    clock.value = BASE
    with pytest.raises(ShadowContractError, match="partial"):
        store.seal_field(observation_hash=old, cutoff_at_ms=BASE)

    store, clock = setup(tmp_path / "conflict")
    old = observe(store, clock)
    changed = [{"entry_id": 11, "horse_number": 1, "horse_id": "H11"}]
    observe(store, clock, body=raw(entries=changed), source="other-source", at=BASE - 5)
    clock.value = BASE
    with pytest.raises(ShadowContractError, match="conflicting source"):
        store.seal_field(observation_hash=old, cutoff_at_ms=BASE)

    store, clock = setup(tmp_path / "future")
    old = observe(store, clock)
    later = observe(store, clock, body=raw(entries=changed, effective=BASE + 1), at=BASE - 5)
    clock.value = BASE
    fld = store.seal_field(observation_hash=old, cutoff_at_ms=BASE)
    assert later in store._field(fld)["deferred_future_effective"]

    store, clock = setup(tmp_path / "schedule")
    old = observe(store, clock)
    updated = observe(store, clock, body=raw(schedule=BASE + 2_400_000), at=BASE - 5)
    clock.value = BASE
    with pytest.raises(ShadowContractError, match="superseded"):
        store.seal_field(observation_hash=old, cutoff_at_ms=BASE)
    with pytest.raises(ShadowContractError, match="schedule"):
        store.seal_field(observation_hash=updated, cutoff_at_ms=BASE)


def test_r2_same_timestamp_conflict_and_input_order(tmp_path):
    for reverse in (False, True):
        store, clock = setup(tmp_path / f"order_{reverse}")
        two = raw()
        one = raw(entries=[{"entry_id": 11, "horse_number": 1, "horse_id": "H11"}])
        bodies = (one, two) if reverse else (two, one)
        hashes = [observe(store, clock, body=body, at=BASE - 5) for body in bodies]
        clock.value = BASE
        with pytest.raises(ShadowContractError, match="same-time conflicting"):
            store.seal_field(observation_hash=hashes[0], cutoff_at_ms=BASE)


def test_r2_selection_and_insert_share_one_write_transaction(tmp_path, monkeypatch):
    store, clock = setup(tmp_path)
    old = observe(store, clock)
    clock.value = BASE
    started = Event()
    finished = Event()
    correction = raw(entries=[{"entry_id": 11, "horse_number": 1, "horse_id": "H11"}])

    def concurrent_observation():
        started.set()
        store.observe_synthetic(
            source_id="synthetic/API26_2", request_at_ms=BASE - 1, body=correction
        )
        finished.set()

    original_insert = store._insert_locked
    worker = None

    def insert_with_new_observation(*args, **kwargs):
        nonlocal worker
        worker = Thread(target=concurrent_observation)
        worker.start()
        assert started.wait(2)
        assert not finished.is_set()
        return original_insert(*args, **kwargs)

    monkeypatch.setattr(store, "_insert_locked", insert_with_new_observation)
    fld = store.seal_field(observation_hash=old, cutoff_at_ms=BASE)
    worker.join(5)
    assert finished.is_set()
    assert store._field(fld)["expected_keys"] == [[7, 11], [7, 12]]


def test_r3_late_snapshot_and_new_prediction_rejected_but_retry_idempotent(tmp_path):
    store, clock = setup(tmp_path)
    obs, fld = field(store, clock)
    clock.value = BASE + 1_800_001
    with pytest.raises(ShadowContractError, match="after cutoff"):
        snap(store, obs, fld, feature_contracts=contract(store, obs, available=BASE + 1_800_001))
    assert not [e for e in store.events() if e["kind"] == "v2_snapshot_pending"]

    store, clock = setup(tmp_path / "retry")
    obs, fld = field(store, clock)
    snapshot_hash = snap(store, obs, fld)
    prediction_hash = pred(store, fld, snapshot_hash)
    clock.value = BASE + 1_800_001
    assert pred(store, fld, snapshot_hash) == prediction_hash
    with pytest.raises(ShadowContractError, match="new prediction after cutoff"):
        pred(store, fld, snapshot_hash, model="new-model")


def test_r3_prediction_commit_ack_after_deadline_is_ineligible(tmp_path):
    store, clock = setup(tmp_path)
    obs, fld = field(store, clock)
    snapshot_hash = snap(store, obs, fld)
    ticks = iter((BASE, BASE, BASE + 1, BASE + 2))
    store._clock = lambda: next(ticks)
    with pytest.raises(ShadowContractError, match="late/ineligible"):
        pred(store, fld, snapshot_hash)
    pending = next(e for e in store.events() if e["kind"] == "v2_prediction_pending")
    assert (
        store._admission(pending["event_hash"], "v2_prediction_admission")["status"]
        == "late_ineligible"
    )


def test_r4_calculator_reproduces_raw_and_rejects_fabrication(tmp_path):
    store, clock = setup(tmp_path)
    obs, fld = field(store, clock)
    valid = rows()
    assert snap(store, obs, fld, feature_rows=valid)

    store, clock = setup(tmp_path / "bad")
    obs, fld = field(store, clock)
    fabricated = rows()
    fabricated[0]["features"][FEATURE] = 999.0
    with pytest.raises(ShadowContractError, match="not reproduced"):
        snap(store, obs, fld, feature_rows=fabricated)
    wrong = contract(store, obs)
    wrong[FEATURE]["calculation_version"] = "nonexistent-calculator-v1"
    with pytest.raises(ShadowContractError, match="unregistered"):
        snap(store, obs, fld, feature_contracts=wrong)
    wrong = contract(store, obs)
    wrong[FEATURE]["dependency_observations"] = []
    with pytest.raises(ShadowContractError, match="dependency"):
        snap(store, obs, fld, feature_contracts=wrong)
    wrong = contract(store, obs, available=BASE - 1000)
    with pytest.raises(ShadowContractError, match="precedes source"):
        snap(store, obs, fld, feature_contracts=wrong)


def test_r4_unrelated_race_and_unregistered_feature_never_eligible(tmp_path):
    store, clock = setup(tmp_path)
    obs = observe(store, clock)
    other = observe(
        store,
        clock,
        source="synthetic/unrelated",
        at=BASE - 5,
        body=raw(
            race_id=999,
            entries=[
                {"entry_id": 91, "horse_number": 1, "horse_id": "U1"},
                {"entry_id": 92, "horse_number": 2, "horse_id": "U2"},
            ],
        ),
    )
    clock.value = BASE
    fld = store.seal_field(observation_hash=obs, cutoff_at_ms=BASE)
    wrong = contract(store, obs)
    wrong[FEATURE]["dependency_observations"] = [other]
    with pytest.raises(ShadowContractError, match="dependency"):
        snap(store, obs, fld, feature_contracts=wrong)
    with pytest.raises(ShadowContractError, match="availability_unverified"):
        snap(store, obs, fld, feature_contracts={"arbitrary_feature": {}})


def test_concurrent_duplicate_prediction_is_idempotent(tmp_path):
    store, clock = setup(tmp_path)
    obs, fld = field(store, clock)
    snapshot_hash = snap(store, obs, fld)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: pred(store, fld, snapshot_hash), range(2)))
    assert results[0] == results[1]
    assert len([e for e in store.events() if e["kind"] == "v2_prediction_pending"]) == 1

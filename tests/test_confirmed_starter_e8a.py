"""Synthetic boundary and replay tests; never query historical outcomes."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from horse_racing.analysis.confirmed_starter_e8a import ShadowContractError, ShadowEvidenceStore
from horse_racing.analysis.pre_race_field_contract import FieldContractError

BASE = 2_000_000_000_000


class Clock:
    def __init__(self, value: int = BASE - 10) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def raw(**changes) -> bytes:
    data = {
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
    }
    data.update(changes)
    return json.dumps(data, sort_keys=True).encode()


def store(tmp_path):
    clock = Clock()
    return ShadowEvidenceStore.for_testing(tmp_path / "isolated", clock), clock


def observed(store, clock, body=None):
    clock.value = BASE - 10
    return store.observe_synthetic(
        source_id="synthetic/API26_2", request_at_ms=BASE - 20, body=body or raw()
    )


def field(store, clock, body=None):
    obs = observed(store, clock, body)
    clock.value = BASE
    return obs, store.seal_field(observation_hash=obs, cutoff_at_ms=BASE)


def snapshot(store, obs, fld):
    return store.snapshot(
        field_hash=fld,
        population="F_t",
        rows=[
            {"entry_id": 11, "horse_number": 1, "horse_id": "H11", "features": {"x": 0.1}},
            {"entry_id": 12, "horse_number": 2, "horse_id": "H12", "features": {"x": 0.2}},
        ],
        feature_contracts={
            "x": {
                "source_observation_hash": obs,
                "available_at_ms": BASE - 10,
                "calculation_version": "synthetic-v1",
            }
        },
    )


def prediction(store, fld, snap, **changes):
    args = {
        "field_hash": fld,
        "snapshot_hash": snap,
        "experiment_version": "e8a-test",
        "model_version": "synthetic-uniform-v1",
        "model_hash": "a" * 64,
        "cutoff_policy": "start_minus_30m",
        "model_population": "F_t_synthetic",
        "probabilities": [
            {"entry_id": 11, "horse_number": 1, "horse_id": "H11", "prob_win": 0.5},
            {"entry_id": 12, "horse_number": 2, "horse_id": "H12", "prob_win": 0.5},
        ],
    }
    args.update(changes)
    return store.publish_synthetic(**args)


def test_cutoff_before_equal_after_and_late_import(tmp_path):
    s, c = store(tmp_path)
    o = observed(s, c)
    c.value = BASE - 1
    with pytest.raises(ShadowContractError, match="cutoff"):
        s.seal_field(observation_hash=o, cutoff_at_ms=BASE)
    c.value = BASE
    fld = s.seal_field(observation_hash=o, cutoff_at_ms=BASE)
    assert s._event(fld, "field")["field"]["sealed_at_ms"] == BASE
    c.value = BASE + 1
    with pytest.raises(ShadowContractError, match="retrospectively"):
        s.seal_field(observation_hash=o, cutoff_at_ms=BASE)
    imported = s.observe_synthetic(
        source_id="old-file-import", request_at_ms=BASE - 1000, body=raw()
    )
    assert s._ready(imported)[1] == BASE + 1
    with pytest.raises(ShadowContractError, match="retrospectively"):
        s.seal_field(observation_hash=imported, cutoff_at_ms=BASE)


def test_delayed_parse_clock_regression_and_timezone(tmp_path):
    s, c = store(tmp_path)
    c.value = BASE + 1
    late = s.observe_synthetic(source_id="late", request_at_ms=BASE - 100, body=raw())
    assert s._ready(late)[1] > BASE
    c.value = BASE
    with pytest.raises(ShadowContractError):
        s.seal_field(observation_hash=late, cutoff_at_ms=BASE)
    c.value = BASE + 2
    with pytest.raises(ShadowContractError, match="request"):
        s.observe_synthetic(source_id="bad", request_at_ms=BASE + 3, body=raw())
    invalid = s.observe_synthetic(source_id="tz", request_at_ms=BASE, body=raw(timezone="UTC"))
    assert s._event(invalid, "observation")["parse_status"] == "rejected"
    c.value = BASE + 1
    with pytest.raises(ShadowContractError, match="clock"):
        s.observe_synthetic(source_id="regress", request_at_ms=BASE, body=raw())


def test_receipt_before_cutoff_but_parse_after_cutoff_is_not_eligible(tmp_path):
    ticks = iter((BASE - 1, BASE + 1, BASE + 2, BASE + 3, BASE + 4, BASE + 5))
    s = ShadowEvidenceStore.for_testing(tmp_path / "delayed", lambda: next(ticks))
    obs = s.observe_synthetic(source_id="delayed", request_at_ms=BASE - 2, body=raw())
    event = s._event(obs, "observation")
    assert event["received_at_ms"] < BASE < s._ready(obs)[1]
    s._clock = lambda: BASE
    with pytest.raises(ShadowContractError, match="not available"):
        s.seal_field(observation_hash=obs, cutoff_at_ms=BASE)


def test_same_bytes_new_observation_event_but_single_blob(tmp_path):
    s, c = store(tmp_path)
    first = observed(s, c)
    c.value = BASE - 5
    second = s.observe_synthetic(source_id="synthetic/API26_2", request_at_ms=BASE - 6, body=raw())
    assert first != second
    assert len([e for e in s.events() if e["kind"] == "observation"]) == 2
    assert len(list((s.root / "raw").iterdir())) == 1


def test_raw_blob_tampering_breaks_chain_verification(tmp_path):
    s, c = store(tmp_path)
    observed(s, c)
    blob = next((s.root / "raw").iterdir())
    blob.write_bytes(b"tampered")
    with pytest.raises(ShadowContractError, match="raw blob"):
        s.verify_chain()


@pytest.mark.parametrize(
    "changes",
    [
        {"declared_count": 3},
        {"status": "partial"},
        {"status": "ambiguous_cancel"},
        {"entries": [{"entry_id": 11, "horse_number": 1, "horse_id": "H11"}]},
        {
            "entries": [
                {"entry_id": 11, "horse_number": 1, "horse_id": "H11"},
                {"entry_id": 11, "horse_number": 2, "horse_id": "H12"},
            ]
        },
        {
            "entries": [
                {"entry_id": 11, "horse_number": 1, "horse_id": "H11"},
                {"entry_id": 12, "horse_number": 1, "horse_id": "H12"},
            ]
        },
    ],
)
def test_incomplete_or_duplicate_field_is_rejected(tmp_path, changes):
    s, c = store(tmp_path)
    o = observed(s, c, raw(**changes))
    assert s._event(o, "observation")["parse_status"] == "rejected"
    c.value = BASE
    with pytest.raises(ShadowContractError, match="rejected"):
        s.seal_field(observation_hash=o, cutoff_at_ms=BASE)


def test_schedule_version_and_late_correction_do_not_move_seal(tmp_path):
    s, c = store(tmp_path)
    obs, fld = field(s, c)
    old = s._event(fld, "field")
    later = s.observe_synthetic(
        source_id="correction",
        request_at_ms=BASE,
        body=raw(scheduled_at_ms=BASE + 2_400_000, effective_at_ms=BASE - 100),
    )
    c.value = BASE + 600_000
    with pytest.raises(ShadowContractError):
        s.seal_field(observation_hash=later, cutoff_at_ms=BASE + 600_000)
    assert s._event(fld, "field") == old
    assert s._event(obs, "observation")["parsed"]["scheduled_at_ms"] == BASE + 1_800_000


def test_snapshot_identity_feature_availability_and_a_rejection(tmp_path):
    s, c = store(tmp_path)
    obs, fld = field(s, c)
    snap = snapshot(s, obs, fld)
    args = s._event(snap, "snapshot")
    with pytest.raises(ShadowContractError, match="prospective"):
        s.snapshot(
            field_hash=fld,
            rows=args["rows"],
            feature_contracts=args["feature_contracts"],
            population="A",
        )
    bad = [dict(row) for row in args["rows"]]
    bad[0]["horse_id"] = "OTHER"
    with pytest.raises(ShadowContractError, match="identity"):
        s.snapshot(
            field_hash=fld, rows=bad, feature_contracts=args["feature_contracts"], population="F_t"
        )
    with pytest.raises(FieldContractError, match="key mismatch"):
        s.snapshot(
            field_hash=fld,
            rows=bad[:1],
            feature_contracts=args["feature_contracts"],
            population="F_t",
        )
    contract = {"x": dict(args["feature_contracts"]["x"])}
    contract["x"]["available_at_ms"] = BASE + 1
    with pytest.raises(ShadowContractError, match="after cutoff"):
        s.snapshot(field_hash=fld, rows=args["rows"], feature_contracts=contract, population="F_t")
    del contract["x"]["available_at_ms"]
    with pytest.raises(ShadowContractError, match="available_at_ms"):
        s.snapshot(field_hash=fld, rows=args["rows"], feature_contracts=contract, population="F_t")


def test_prediction_idempotency_conflict_and_concurrent_duplicate(tmp_path):
    s, c = store(tmp_path)
    obs, fld = field(s, c)
    snap = snapshot(s, obs, fld)
    first = prediction(s, fld, snap)
    assert prediction(s, fld, snap) == first
    rows = s._event(first, "prediction")["probabilities"]
    changed = [dict(row) for row in rows]
    changed[0]["prob_win"] = 0.4
    changed[1]["prob_win"] = 0.6
    with pytest.raises(ShadowContractError, match="conflicting"):
        prediction(s, fld, snap, probabilities=changed)
    with pytest.raises(ShadowContractError, match="retrospective A"):
        prediction(s, fld, snap, model_population="A")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: prediction(s, fld, snap), range(2)))
    assert results == [first, first]
    assert len([e for e in s.events() if e["kind"] == "prediction"]) == 1


def test_transaction_failure_recovery_and_raw_dedup(tmp_path):
    s, c = store(tmp_path)
    with pytest.raises(OSError, match="interrupted"):
        s.observe_synthetic(
            source_id="s", request_at_ms=BASE - 20, body=raw(), fail_before_commit=True
        )
    assert not s.events()
    assert len(list((s.root / "raw").iterdir())) == 1
    obs = observed(s, c)
    assert s._event(obs, "observation")["raw_sha256"] in {
        p.name for p in (s.root / "raw").iterdir()
    }
    s.verify_chain()


def test_ready_marker_failure_never_approves_partial_observation(tmp_path, monkeypatch):
    s, c = store(tmp_path)
    original_append = s._append

    def fail_ready(kind, payload, **kwargs):
        if kind == "observation_ready":
            raise OSError("ready marker failed")
        return original_append(kind, payload, **kwargs)

    monkeypatch.setattr(s, "_append", fail_ready)
    with pytest.raises(OSError, match="ready marker"):
        observed(s, c)
    incomplete = [event for event in s.events() if event["kind"] == "observation"]
    assert len(incomplete) == 1
    monkeypatch.setattr(s, "_append", original_append)
    c.value = BASE
    with pytest.raises(ShadowContractError, match="not complete"):
        s.seal_field(observation_hash=incomplete[0]["event_hash"], cutoff_at_ms=BASE)
    c.value = BASE + 1
    recovered = s.observe_synthetic(source_id="retry", request_at_ms=BASE, body=raw())
    assert s._ready(recovered)[1] == BASE + 1


def test_later_dns_result_correction_never_rewrites_input(tmp_path):
    s, c = store(tmp_path)
    obs, fld = field(s, c)
    snap = snapshot(s, obs, fld)
    pred = prediction(s, fld, snap)
    immutable = [
        s._event(h, kind) for h, kind in ((fld, "field"), (snap, "snapshot"), (pred, "prediction"))
    ]
    c.value = BASE + 2
    for event_type, payload in (
        ("cancellation", b"DNS"),
        ("result", b"DNF DSQ DEADHEAT VOID"),
        ("correction", b"corrected"),
    ):
        s.append_outcome_event(
            prediction_hash=pred, source_id="synthetic-result", body=payload, event_type=event_type
        )
    assert [
        s._event(h, kind) for h, kind in ((fld, "field"), (snap, "snapshot"), (pred, "prediction"))
    ] == immutable
    assert all(
        s._event(e["event_hash"], "outcome")["evaluation_status"] == "held_dns_policy_unconfirmed"
        for e in s.events()
        if e["kind"] == "outcome"
    )
    s.verify_chain()

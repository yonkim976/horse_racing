"""Synthetic-only E8-A v2: commit-ack admission and deterministic cutoff state.

No operating database, network, model fit, or actual probability publication.
The authoritative eligibility event is an admission record whose ``ack_ms``
was sampled *after* its pending transaction returned successfully. An absent
admission is never eligible after interruption or restart.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from horse_racing.analysis.confirmed_starter_e8a import (
    ShadowContractError,
    ShadowEvidenceStore,
    _canonical,
    _hash,
    _positive_ms,
    _source_row,
)
from horse_racing.analysis.pre_race_field_contract import (
    SealedFieldManifest,
    validate_exact_keyset,
    validate_sealed_field,
)

FEATURE = "synthetic_horse_number_pct"
CALCULATOR = "synthetic_horse_number_pct_v1"
SELECTION_POLICY = "e8a_v2_latest_known_per_source_v1"
CUTOFF_POLICY = "start_minus_30m"


def _raw_hint(body: bytes) -> tuple[int | None, int | None]:
    """Retain race/effective hints even when a partial page fails parsing."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    race = data.get("race_id")
    effective = data.get("effective_at_ms")
    return (
        race if type(race) is int and race > 0 else None,
        effective if type(effective) is int and effective > 0 else None,
    )


def _payload(row: sqlite3.Row) -> dict[str, Any]:
    return json.loads(row["payload_json"])


class ShadowEvidenceStoreV2(ShadowEvidenceStore):
    """V2 event protocol in a new, isolated root; never migrate v1 events."""

    @classmethod
    def for_testing(cls, root: Path, clock):
        store = cls(root)
        store._clock = clock
        return store

    def _insert_locked(
        self,
        db: sqlite3.Connection,
        kind: str,
        payload: dict[str, Any],
        *,
        identity: str | None = None,
        created_ms: int | None = None,
    ) -> str:
        now = self._now() if created_ms is None else created_ms
        previous = db.execute(
            "SELECT event_hash,created_ms FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if previous is not None and now < previous["created_ms"]:
            raise ShadowContractError("store clock moved backwards")
        prev_hash = previous["event_hash"] if previous is not None else None
        payload_hash = hashlib.sha256(_canonical(payload)).hexdigest()
        event_hash = _hash(
            {
                "kind": kind,
                "identity": identity,
                "payload_hash": payload_hash,
                "created_ms": now,
                "previous_hash": prev_hash,
            }
        )
        db.execute(
            "INSERT INTO events(kind,identity,payload_json,payload_hash,created_ms,"
            "previous_hash,event_hash) VALUES(?,?,?,?,?,?,?)",
            (
                kind,
                identity,
                _canonical(payload).decode(),
                payload_hash,
                now,
                prev_hash,
                event_hash,
            ),
        )
        return event_hash

    def _admission(self, pending_hash: str, kind: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM events WHERE kind=? AND identity=?",
                (kind, pending_hash),
            ).fetchone()
        if row is None:
            raise ShadowContractError(f"{kind} missing; pending event is ineligible")
        return _payload(row)

    def observe_synthetic(
        self,
        *,
        source_id: str,
        request_at_ms: int,
        body: bytes,
        fail_before_commit: bool = False,
    ) -> str:
        if not source_id or not isinstance(body, bytes):
            raise ShadowContractError("source_id and raw bytes required")
        requested = _positive_ms(request_at_ms, "request_at_ms")
        received = self._now()
        if requested > received:
            raise ShadowContractError("request later than receipt")
        raw_hash = self._store_raw(body)
        race_hint, effective_hint = _raw_hint(body)
        try:
            parsed = _source_row(body)
            status, error = "ok", None
        except ShadowContractError as exc:
            parsed, status, error = None, "rejected", str(exc)
        parsed_at = self._now()
        if parsed_at < received:
            raise ShadowContractError("parser clock moved backwards")
        observation_hash = self._append(
            "v2_observation",
            {
                "synthetic_only": True,
                "source_id": source_id,
                "raw_sha256": raw_hash,
                "parser_version": "synthetic_entry_sheet_v1",
                "parse_status": status,
                "parse_error": error,
                "requested_at_ms": requested,
                "received_at_ms": received,
                "parsed_at_ms": parsed_at,
                "race_hint": race_hint,
                "effective_hint_ms": effective_hint,
                "parsed": parsed,
            },
            fail_before_commit=fail_before_commit,
        )
        # Ack is sampled only after the observation COMMIT returned. A crash
        # before the ack marker leaves an ineligible, recoverable pending row.
        ack_ms = self._now()
        self._append(
            "v2_observation_ack",
            {"observation_hash": observation_hash, "ack_ms": ack_ms},
            identity=observation_hash,
        )
        return observation_hash

    def _observations_at_cutoff(
        self,
        db: sqlite3.Connection,
        race_id: int,
        cutoff: int,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        rows = db.execute(
            "SELECT event_hash,payload_json FROM events WHERE kind='v2_observation' ORDER BY id"
        ).fetchall()
        observations: list[dict[str, Any]] = []
        deferred: list[str] = []
        for row in rows:
            data = _payload(row)
            if data["race_hint"] != race_id:
                continue
            ack = db.execute(
                "SELECT payload_json FROM events WHERE kind='v2_observation_ack' AND identity=?",
                (row["event_hash"],),
            ).fetchone()
            if ack is None:
                raise ShadowContractError("race has unacknowledged observation")
            known_at = _payload(ack)["ack_ms"]
            if known_at > cutoff:
                continue
            effective = data["effective_hint_ms"]
            if effective is not None and effective > cutoff:
                deferred.append(row["event_hash"])
                continue
            observations.append({"hash": row["event_hash"], "data": data, "known_at": known_at})
        if not observations:
            raise ShadowContractError("no known effective observation at cutoff")
        by_source: dict[str, list[dict[str, Any]]] = {}
        for item in observations:
            by_source.setdefault(item["data"]["source_id"], []).append(item)
        selected: list[dict[str, Any]] = []
        for source_rows in by_source.values():
            latest_ms = max(item["known_at"] for item in source_rows)
            latest = [item for item in source_rows if item["known_at"] == latest_ms]
            states = {_hash(item["data"]["parsed"]) for item in latest}
            if len(states) != 1:
                raise ShadowContractError("same-time conflicting source observations")
            chosen = min(latest, key=lambda item: item["hash"])
            if chosen["data"]["parse_status"] != "ok":
                raise ShadowContractError("latest source is partial or ambiguous")
            selected.append(chosen)
        states = {_hash(item["data"]["parsed"]) for item in selected}
        if len(states) != 1:
            raise ShadowContractError("conflicting source lineages")
        chosen = min(selected, key=lambda item: (item["data"]["source_id"], item["hash"]))
        return chosen, sorted(item["hash"] for item in selected), sorted(deferred)

    def seal_field(self, *, observation_hash: str, cutoff_at_ms: int) -> str:
        cutoff = _positive_ms(cutoff_at_ms, "cutoff_at_ms")
        candidate = self._event(observation_hash, "v2_observation")
        race_id = candidate["race_hint"]
        if race_id is None:
            raise ShadowContractError("candidate has no race identity")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            entered = self._now()
            if entered != cutoff:
                raise ShadowContractError("field transaction did not enter at exact cutoff")
            chosen, selected, deferred = self._observations_at_cutoff(db, race_id, cutoff)
            if observation_hash not in selected:
                raise ShadowContractError("caller observation superseded at cutoff")
            parsed = chosen["data"]["parsed"]
            if parsed["scheduled_at_ms"] - 1_800_000 != cutoff:
                raise ShadowContractError("observed schedule does not match cutoff")
            existing = db.execute(
                "SELECT 1 FROM events WHERE kind='v2_field_pending' AND identity=?",
                (str(race_id),),
            ).fetchone()
            if existing is not None:
                raise ShadowContractError("race already has a field attempt")
            keys = tuple((race_id, row["entry_id"]) for row in parsed["entries"])
            field = SealedFieldManifest(
                snapshot_id=chosen["hash"],
                source_id=chosen["data"]["source_id"],
                race_id=race_id,
                cutoff_at_ms=cutoff,
                sealed_at_ms=cutoff,
                expected_keys=keys,
                complete=True,
                completeness_basis=f"raw:{chosen['data']['raw_sha256']}:declared_count={parsed['declared_count']}",
            )
            validate_sealed_field(field)
            pending = self._insert_locked(
                db,
                "v2_field_pending",
                {
                    "synthetic_only": True,
                    "status": "pending",
                    "policy_cutoff_at_ms": cutoff,
                    "selection_policy": SELECTION_POLICY,
                    "selected_observations": selected,
                    "deferred_future_effective": deferred,
                    "observation_hash": chosen["hash"],
                    "source_id": field.source_id,
                    "race_id": race_id,
                    "scheduled_at_ms": parsed["scheduled_at_ms"],
                    "expected_keys": keys,
                    "entries": parsed["entries"],
                    "completeness_basis": field.completeness_basis,
                },
                identity=str(race_id),
            )
            db.commit()
        ack_ms = self._now()  # field transaction completion, not policy cutoff
        accepted = ack_ms <= cutoff
        self._append(
            "v2_field_admission",
            {
                "pending_hash": pending,
                "status": "accepted" if accepted else "late_ineligible",
                "field_commit_ack_ms": ack_ms,
                "policy_cutoff_at_ms": cutoff,
                "reason": None if accepted else "field_commit_after_cutoff",
            },
            identity=pending,
        )
        if not accepted:
            raise ShadowContractError("field commit completed after cutoff; late/ineligible")
        return pending

    def _field(self, field_hash: str) -> dict[str, Any]:
        field = self._event(field_hash, "v2_field_pending")
        admission = self._admission(field_hash, "v2_field_admission")
        if admission["status"] != "accepted":
            raise ShadowContractError("field is not prospectively admitted")
        return field

    def snapshot(
        self,
        *,
        field_hash: str,
        rows: Sequence[Mapping[str, Any]],
        feature_contracts: Mapping[str, Mapping[str, Any]],
        population: str,
    ) -> str:
        field = self._field(field_hash)
        cutoff = field["policy_cutoff_at_ms"]
        if population != "F_t":
            raise ShadowContractError("retrospective A is not F_t")
        if set(feature_contracts) != {FEATURE}:
            raise ShadowContractError(
                "availability_unverified: only registered synthetic feature admitted"
            )
        contract = feature_contracts[FEATURE]
        if contract.get("calculation_version") != CALCULATOR:
            raise ShadowContractError("unregistered synthetic calculator")
        source_hash = field["observation_hash"]
        source_ack = self._admission(source_hash, "v2_observation_ack")
        source_event = self._event(source_hash, "v2_observation")
        source_body = (self.root / "raw" / source_event["raw_sha256"]).read_bytes()
        if hashlib.sha256(source_body).hexdigest() != source_event["raw_sha256"]:
            raise ShadowContractError("feature dependency raw hash mismatch")
        source_parsed = _source_row(source_body)
        if (
            source_parsed["race_id"] != field["race_id"]
            or source_parsed["entries"] != field["entries"]
        ):
            raise ShadowContractError("feature dependency raw field differs from seal")
        expected_dependencies = [source_hash]
        if contract.get("dependency_observations") != expected_dependencies:
            raise ShadowContractError("missing or unrelated feature dependency")
        if contract.get("dependency_ready_hashes") != [self._observation_ack_hash(source_hash)]:
            raise ShadowContractError("missing dependency readiness evidence")
        declared = _positive_ms(contract.get("available_at_ms"), "feature.available_at_ms")
        if declared < source_ack["ack_ms"]:
            raise ShadowContractError("declared feature availability precedes source completion")
        expected = [tuple(key) for key in field["expected_keys"]]
        validate_exact_keyset(expected, [(field["race_id"], row.get("entry_id")) for row in rows])
        identities = {row["entry_id"]: row for row in source_parsed["entries"]}
        cleaned = []
        for row in rows:
            ref = identities[row["entry_id"]]
            if (
                row.get("horse_number") != ref["horse_number"]
                or row.get("horse_id") != ref["horse_id"]
            ):
                raise ShadowContractError("feature target identity differs from source")
            expected_value = ref["horse_number"] / len(identities)
            if row.get("features") != {FEATURE: expected_value}:
                raise ShadowContractError("feature value not reproduced from raw field")
            cleaned.append(
                {
                    "entry_id": row["entry_id"],
                    "horse_number": ref["horse_number"],
                    "horse_id": ref["horse_id"],
                    "features": {FEATURE: expected_value},
                }
            )
        cleaned.sort(key=lambda row: row["entry_id"])
        result_hash = _hash(cleaned)
        if contract.get("result_hash") != result_hash:
            raise ShadowContractError("feature result hash mismatch")
        calculated_at = self._now()
        if declared < calculated_at:
            raise ShadowContractError("declared availability precedes calculation completion")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            entered = self._now()
            if entered > cutoff:
                raise ShadowContractError("new snapshot after cutoff is ineligible")
            pending = self._insert_locked(
                db,
                "v2_snapshot_pending",
                {
                    "status": "pending",
                    "synthetic_only": True,
                    "field_hash": field_hash,
                    "population": "F_t",
                    "feature_name": FEATURE,
                    "calculation_version": CALCULATOR,
                    "dependency_observations": expected_dependencies,
                    "dependency_ready_hashes": contract["dependency_ready_hashes"],
                    "source_ack_ms": source_ack["ack_ms"],
                    "calculation_completed_ms": calculated_at,
                    "declared_available_at_ms": declared,
                    "result_hash": result_hash,
                    "rows": cleaned,
                },
                identity=field_hash,
            )
            db.commit()
        ack_ms = self._now()
        accepted = ack_ms <= cutoff
        self._append(
            "v2_snapshot_admission",
            {
                "pending_hash": pending,
                "status": "accepted" if accepted else "late_ineligible",
                "snapshot_commit_ack_ms": ack_ms,
                "deadline_ms": cutoff,
                "reason": None if accepted else "snapshot_commit_after_cutoff",
            },
            identity=pending,
        )
        if not accepted:
            raise ShadowContractError("snapshot completed after cutoff; late/ineligible")
        return pending

    def _observation_ack_hash(self, observation_hash: str) -> str:
        with self._connect() as db:
            row = db.execute(
                "SELECT event_hash FROM events WHERE kind='v2_observation_ack' AND identity=?",
                (observation_hash,),
            ).fetchone()
        if row is None:
            raise ShadowContractError("observation completion missing")
        return str(row["event_hash"])

    def publish_synthetic(
        self,
        *,
        field_hash: str,
        snapshot_hash: str,
        experiment_version: str,
        model_version: str,
        model_hash: str,
        cutoff_policy: str,
        probabilities: Sequence[Mapping[str, Any]],
        model_population: str,
    ) -> str:
        field = self._field(field_hash)
        snapshot = self._event(snapshot_hash, "v2_snapshot_pending")
        snap_admission = self._admission(snapshot_hash, "v2_snapshot_admission")
        if snapshot["field_hash"] != field_hash or snap_admission["status"] != "accepted":
            raise ShadowContractError("snapshot not admitted for field")
        if model_population != "F_t_synthetic" or not model_hash:
            raise ShadowContractError("retrospective A model is ineligible")
        if cutoff_policy != CUTOFF_POLICY or not experiment_version or not model_version:
            raise ShadowContractError("shadow identity incomplete")
        race_id = field["race_id"]
        validate_exact_keyset(
            [tuple(key) for key in field["expected_keys"]],
            [(race_id, row.get("entry_id")) for row in probabilities],
        )
        identities = {row["entry_id"]: row for row in field["entries"]}
        clean = []
        for row in probabilities:
            ref = identities[row["entry_id"]]
            probability = row.get("prob_win")
            if (
                row.get("horse_number") != ref["horse_number"]
                or row.get("horse_id") != ref["horse_id"]
            ):
                raise ShadowContractError("prediction identity mismatch")
            if (
                type(probability) not in {int, float}
                or not math.isfinite(probability)
                or not 0 <= probability <= 1
            ):
                raise ShadowContractError("invalid synthetic probability")
            clean.append(
                {
                    "entry_id": row["entry_id"],
                    "horse_number": ref["horse_number"],
                    "horse_id": ref["horse_id"],
                    "prob_win": float(probability),
                }
            )
        if not math.isclose(sum(row["prob_win"] for row in clean), 1, rel_tol=0, abs_tol=1e-9):
            raise ShadowContractError("race probabilities do not sum to one")
        identity = _hash(
            {
                "experiment_version": experiment_version,
                "model_version": model_version,
                "race_key": race_id,
                "cutoff_policy": cutoff_policy,
                "sealed_field_hash": field_hash,
            }
        )
        payload = {
            "status": "pending",
            "synthetic_only": True,
            "experiment_version": experiment_version,
            "model_version": model_version,
            "model_hash": model_hash,
            "race_key": race_id,
            "cutoff_policy": cutoff_policy,
            "sealed_field_hash": field_hash,
            "snapshot_hash": snapshot_hash,
            "probabilities": sorted(clean, key=lambda row: row["entry_id"]),
            "prospective_status": "not_activated",
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT event_hash,payload_json FROM events "
                "WHERE kind='v2_prediction_pending' AND identity=?",
                (identity,),
            ).fetchone()
            if old is not None:
                if _payload(old) != payload:
                    raise ShadowContractError("same prediction identity has conflicting payload")
                admitted = db.execute(
                    "SELECT payload_json FROM events "
                    "WHERE kind='v2_prediction_admission' AND identity=?",
                    (old["event_hash"],),
                ).fetchone()
                if admitted is None or _payload(admitted)["status"] != "accepted":
                    raise ShadowContractError("existing prediction is not eligible")
                return str(old["event_hash"])
            cutoff = field["policy_cutoff_at_ms"]
            if self._now() > cutoff:
                raise ShadowContractError("new prediction after cutoff is ineligible")
            pending = self._insert_locked(db, "v2_prediction_pending", payload, identity=identity)
            db.commit()
        ack_ms = self._now()
        accepted = ack_ms <= cutoff
        self._append(
            "v2_prediction_admission",
            {
                "pending_hash": pending,
                "status": "accepted" if accepted else "late_ineligible",
                "prediction_commit_ack_ms": ack_ms,
                "deadline_ms": cutoff,
                "reason": None if accepted else "prediction_commit_after_cutoff",
            },
            identity=pending,
        )
        if not accepted:
            raise ShadowContractError("prediction completed after cutoff; late/ineligible")
        return pending

    def append_outcome_event(
        self,
        *,
        prediction_hash: str,
        source_id: str,
        body: bytes,
        event_type: str,
    ) -> str:
        self._event(prediction_hash, "v2_prediction_pending")
        admission = self._admission(prediction_hash, "v2_prediction_admission")
        if admission["status"] != "accepted":
            raise ShadowContractError("outcome cannot attach to unadmitted prediction")
        if event_type not in {"result", "correction", "cancellation"} or not source_id:
            raise ShadowContractError("unapproved outcome event")
        raw_hash = self._store_raw(body)
        return self._append(
            "v2_outcome",
            {
                "synthetic_only": True,
                "prediction_hash": prediction_hash,
                "source_id": source_id,
                "raw_sha256": raw_hash,
                "event_type": event_type,
                "evaluation_status": "held_dns_policy_unconfirmed",
            },
        )

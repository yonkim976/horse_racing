"""Offline, synthetic-only evidence and shadow ledger for prospective F_t design.

This module does not fetch data, read the operating DB, fit a model, or publish
probabilities.  SQLite is the commit authority; content-addressed raw files may
be orphaned by a failed transaction but an uncommitted event is never approved.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from horse_racing.analysis.pre_race_field_contract import (
    SealedFieldManifest,
    validate_exact_keyset,
    validate_sealed_field,
)


class ShadowContractError(ValueError):
    """An offline evidence or shadow-ledger contract failed."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000


def _positive_ms(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ShadowContractError(f"{name} must be a positive UTC epoch millisecond integer")
    return value


def _source_row(raw: bytes) -> dict[str, Any]:
    """Strict synthetic fixture parser; a KRA adapter is activation work."""
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ShadowContractError("synthetic source is not valid JSON") from exc
    if not isinstance(data, dict) or data.get("schema") != "synthetic_entry_sheet_v1":
        raise ShadowContractError("unapproved synthetic source schema")
    if data.get("timezone") != "Asia/Seoul":
        raise ShadowContractError("schedule timezone must explicitly be Asia/Seoul")
    race_id = data.get("race_id")
    scheduled = data.get("scheduled_at_ms")
    count = data.get("declared_count")
    entries = data.get("entries")
    status = data.get("status")
    if type(race_id) is not int or race_id <= 0:
        raise ShadowContractError("race_id missing")
    _positive_ms(scheduled, "scheduled_at_ms")
    if type(count) is not int or count <= 0 or not isinstance(entries, list):
        raise ShadowContractError("independent declared_count and entries required")
    if status != "complete":
        raise ShadowContractError("partial or ambiguous source cannot seal a field")
    if len(entries) != count:
        raise ShadowContractError("source list differs from independent declared_count")
    numbers: set[int] = set()
    ids: set[int] = set()
    horses: set[str] = set()
    clean = []
    for row in entries:
        if not isinstance(row, dict) or set(row) != {"entry_id", "horse_number", "horse_id"}:
            raise ShadowContractError("entry needs exact identity fields")
        entry_id, number, horse_id = row["entry_id"], row["horse_number"], row["horse_id"]
        if (
            type(entry_id) is not int
            or entry_id <= 0
            or type(number) is not int
            or number <= 0
            or not isinstance(horse_id, str)
            or not horse_id.strip()
        ):
            raise ShadowContractError("invalid entry identity")
        if entry_id in ids or number in numbers or horse_id in horses:
            raise ShadowContractError("duplicate entry, horse number, or horse identity")
        ids.add(entry_id)
        numbers.add(number)
        horses.add(horse_id)
        clean.append({"entry_id": entry_id, "horse_number": number, "horse_id": horse_id})
    for name in ("published_at_ms", "effective_at_ms"):
        if data.get(name) is not None:
            _positive_ms(data[name], name)
    return {
        "race_id": race_id,
        "scheduled_at_ms": scheduled,
        "declared_count": count,
        "entries": sorted(clean, key=lambda row: row["horse_number"]),
        "source_published_at_ms": data.get("published_at_ms"),
        "source_effective_at_ms": data.get("effective_at_ms"),
        "status": status,
    }


class ShadowEvidenceStore:
    """Isolated append-only SQLite event journal and content-addressed raw store.

    Normal construction uses the system clock. ``for_testing`` is the only
    injection route and is deliberately marked synthetic-only in every event.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._clock: Callable[[], int] = _clock_ms
        self._initialize()

    @classmethod
    def for_testing(cls, root: Path, clock: Callable[[], int]) -> ShadowEvidenceStore:
        store = cls(root)
        store._clock = clock
        return store

    def _initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "raw").mkdir(exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "id INTEGER PRIMARY KEY, kind TEXT NOT NULL, identity TEXT, "
                "payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, "
                "created_ms INTEGER NOT NULL, previous_hash TEXT, event_hash TEXT NOT NULL UNIQUE)"
            )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS event_identity "
                "ON events(kind, identity) WHERE identity IS NOT NULL"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.root / "events.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _now(self) -> int:
        return _positive_ms(self._clock(), "store clock")

    def _append(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        identity: str | None = None,
        fail_before_commit: bool = False,
    ) -> str:
        serialized = _canonical(payload).decode("utf-8")
        payload_hash = hashlib.sha256(serialized.encode()).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if identity is not None:
                old = db.execute(
                    "SELECT payload_hash, event_hash FROM events WHERE kind=? AND identity=?",
                    (kind, identity),
                ).fetchone()
                if old is not None:
                    if old["payload_hash"] != payload_hash:
                        raise ShadowContractError("same shadow identity has conflicting payload")
                    return str(old["event_hash"])
            previous = db.execute(
                "SELECT event_hash, created_ms FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            now = self._now()
            if previous is not None and now < previous["created_ms"]:
                raise ShadowContractError("store clock moved backwards")
            if kind == "observation" and now < payload["persisted_at_ms"]:
                raise ShadowContractError("journal clock precedes persistence clock")
            prev_hash = previous["event_hash"] if previous is not None else None
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
                "previous_hash,event_hash) "
                "VALUES(?,?,?,?,?,?,?)",
                (kind, identity, serialized, payload_hash, now, prev_hash, event_hash),
            )
            if fail_before_commit:
                raise OSError("synthetic interrupted transaction")
            db.commit()
            return event_hash

    def _event(self, event_hash: str, kind: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM events WHERE event_hash=? AND kind=?", (event_hash, kind)
            ).fetchone()
        if row is None:
            raise ShadowContractError(f"missing {kind} event")
        return json.loads(row["payload_json"])

    def _ready(self, observation_hash: str) -> tuple[str, int]:
        with self._connect() as db:
            row = db.execute(
                "SELECT event_hash, payload_json FROM events "
                "WHERE kind='observation_ready' AND identity=?",
                (observation_hash,),
            ).fetchone()
        if row is None:
            raise ShadowContractError("observation persistence is not complete")
        data = json.loads(row["payload_json"])
        return str(row["event_hash"]), int(data["available_at_ms"])

    def events(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM events ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def verify_chain(self) -> None:
        previous = None
        previous_ms = 0
        for event in self.events():
            data = json.loads(event["payload_json"])
            raw_hash = data.get("raw_sha256")
            if raw_hash is not None:
                raw_path = self.root / "raw" / raw_hash
                if (
                    not raw_path.is_file()
                    or hashlib.sha256(raw_path.read_bytes()).hexdigest() != raw_hash
                ):
                    raise ShadowContractError("linked raw blob missing or corrupted")
            if (
                event["previous_hash"] != previous
                or event["payload_hash"] != _hash(data)
                or event["created_ms"] < previous_ms
                or event["event_hash"]
                != _hash(
                    {
                        "kind": event["kind"],
                        "identity": event["identity"],
                        "payload_hash": event["payload_hash"],
                        "created_ms": event["created_ms"],
                        "previous_hash": previous,
                    }
                )
            ):
                raise ShadowContractError("journal hash chain invalid")
            previous, previous_ms = event["event_hash"], event["created_ms"]

    def _store_raw(self, body: bytes) -> str:
        digest = hashlib.sha256(body).hexdigest()
        path = self.root / "raw" / digest
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ShadowContractError("content-addressed raw blob corrupted")
            return digest
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
            tmp.write(body)
            tmp.flush()
            os.fsync(tmp.fileno())
            temporary = Path(tmp.name)
        try:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ShadowContractError("concurrent raw blob conflict") from None
        finally:
            temporary.unlink(missing_ok=True)
        return digest

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
            raise ShadowContractError("request is later than receipt")
        raw_hash = self._store_raw(body)
        try:
            parsed = _source_row(body)
            parse_status = "ok"
            parse_error = None
        except ShadowContractError as exc:
            parsed = None
            parse_status = "rejected"
            parse_error = str(exc)
        parsed_at = self._now()
        if parsed_at < received:
            raise ShadowContractError("parser clock moved backwards")
        persisted_at = self._now()
        if persisted_at < parsed_at:
            raise ShadowContractError("persistence clock moved backwards")
        observation_hash = self._append(
            "observation",
            {
                "synthetic_only": True,
                "source_id": source_id,
                "raw_sha256": raw_hash,
                "parser_version": "synthetic_entry_sheet_v1",
                "parse_status": parse_status,
                "parse_error": parse_error,
                "requested_at_ms": requested,
                "received_at_ms": received,
                "parsed_at_ms": parsed_at,
                "persisted_at_ms": persisted_at,
                "provisional_persisted_at_ms": persisted_at,
                "parsed": parsed,
            },
            fail_before_commit=fail_before_commit,
        )
        # Only after the observation transaction commits can its contents be
        # considered available. The completion marker itself is another commit.
        ready_at = self._now()
        self._append(
            "observation_ready",
            {"observation_hash": observation_hash, "available_at_ms": ready_at},
            identity=observation_hash,
        )
        return observation_hash

    def seal_field(self, *, observation_hash: str, cutoff_at_ms: int) -> str:
        observed = self._event(observation_hash, "observation")
        ready_hash, available_at = self._ready(observation_hash)
        parsed = observed["parsed"]
        cutoff = _positive_ms(cutoff_at_ms, "cutoff_at_ms")
        if parsed is None or observed["parse_status"] != "ok":
            raise ShadowContractError("rejected source cannot seal")
        if self._now() != cutoff:
            raise ShadowContractError(
                "offline seal must occur at recorded cutoff, never retrospectively"
            )
        if available_at > cutoff:
            raise ShadowContractError("observation not available at cutoff")
        if parsed["scheduled_at_ms"] - 30 * 60 * 1000 != cutoff:
            raise ShadowContractError("cutoff differs from observed schedule version")
        race_id = parsed["race_id"]
        for existing in self.events():
            if existing["kind"] != "field":
                continue
            prior = json.loads(existing["payload_json"])["field"]
            if prior["race_id"] == race_id and prior["cutoff_at_ms"] != cutoff:
                raise ShadowContractError("sealed race cutoff cannot move with a later schedule")
        keys = tuple((race_id, row["entry_id"]) for row in parsed["entries"])
        field = SealedFieldManifest(
            snapshot_id=observation_hash,
            source_id=observed["source_id"],
            race_id=race_id,
            cutoff_at_ms=cutoff,
            sealed_at_ms=cutoff,
            expected_keys=keys,
            complete=True,
            completeness_basis=f"raw:{observed['raw_sha256']}:declared_count={parsed['declared_count']}",
        )
        validate_sealed_field(field)
        return self._append(
            "field",
            {
                "synthetic_only": True,
                "observation_hash": observation_hash,
                "observation_ready_hash": ready_hash,
                "raw_sha256": observed["raw_sha256"],
                "field": {
                    "snapshot_id": field.snapshot_id,
                    "source_id": field.source_id,
                    "race_id": race_id,
                    "cutoff_at_ms": cutoff,
                    "sealed_at_ms": cutoff,
                    "expected_keys": keys,
                    "complete": True,
                    "completeness_basis": field.completeness_basis,
                },
                "schedule_version_ms": parsed["scheduled_at_ms"],
                "entries": parsed["entries"],
            },
            identity=str(race_id),
        )

    def snapshot(
        self,
        *,
        field_hash: str,
        rows: Sequence[Mapping[str, Any]],
        feature_contracts: Mapping[str, Mapping[str, Any]],
        population: str,
    ) -> str:
        field_event = self._event(field_hash, "field")
        field = field_event["field"]
        cutoff = field["cutoff_at_ms"]
        if population != "F_t":
            raise ShadowContractError("retrospective A is not prospective F_t")
        expected = [tuple(key) for key in field["expected_keys"]]
        observed_keys = [(field["race_id"], row.get("entry_id")) for row in rows]
        validate_exact_keyset(expected, observed_keys)
        expected_identity = {row["entry_id"]: row for row in field_event["entries"]}
        feature_names = set(feature_contracts)
        if not feature_names:
            raise ShadowContractError("feature observation contracts required")
        cleaned = []
        for row in rows:
            source = expected_identity[row["entry_id"]]
            if (
                row.get("horse_number") != source["horse_number"]
                or row.get("horse_id") != source["horse_id"]
            ):
                raise ShadowContractError("snapshot horse identity differs from sealed field")
            values = row.get("features")
            if not isinstance(values, dict) or set(values) != feature_names:
                raise ShadowContractError("feature key missing or extra")
            for value in values.values():
                if type(value) not in {int, float} or not math.isfinite(value):
                    raise ShadowContractError("synthetic feature value must be finite")
            cleaned.append(
                {
                    "entry_id": row["entry_id"],
                    "horse_number": row["horse_number"],
                    "horse_id": row["horse_id"],
                    "features": values,
                }
            )
        for name, contract in feature_contracts.items():
            available = contract.get("available_at_ms")
            if not contract.get("source_observation_hash") or not contract.get(
                "calculation_version"
            ):
                raise ShadowContractError(f"feature {name} availability or calculation unverified")
            _positive_ms(available, f"{name}.available_at_ms")
            if available > cutoff:
                raise ShadowContractError(f"feature {name} is after cutoff")
            source = self._event(contract["source_observation_hash"], "observation")
            _, source_available_at = self._ready(contract["source_observation_hash"])
            if source_available_at > cutoff or source["parse_status"] != "ok":
                raise ShadowContractError(f"feature {name} source unavailable")
        payload = {
            "synthetic_only": True,
            "field_hash": field_hash,
            "population": "F_t",
            "feature_contracts": dict(feature_contracts),
            "rows": sorted(cleaned, key=lambda row: row["entry_id"]),
        }
        return self._append("snapshot", payload, identity=field_hash)

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
        field = self._event(field_hash, "field")
        snapshot = self._event(snapshot_hash, "snapshot")
        if snapshot["field_hash"] != field_hash:
            raise ShadowContractError("snapshot is not linked to field")
        if model_population != "F_t_synthetic" or not model_hash:
            raise ShadowContractError(
                "retrospective A or uncertified model cannot publish prospectively"
            )
        if cutoff_policy != "start_minus_30m" or not experiment_version or not model_version:
            raise ShadowContractError("shadow identity incomplete")
        expected = [tuple(key) for key in field["field"]["expected_keys"]]
        race_id = field["field"]["race_id"]
        validate_exact_keyset(expected, [(race_id, row.get("entry_id")) for row in probabilities])
        identity_map = {row["entry_id"]: row for row in field["entries"]}
        clean = []
        for row in probabilities:
            ref = identity_map[row["entry_id"]]
            probability = row.get("prob_win")
            if (
                row.get("horse_number") != ref["horse_number"]
                or row.get("horse_id") != ref["horse_id"]
            ):
                raise ShadowContractError("prediction horse identity mismatch")
            if (
                type(probability) not in {int, float}
                or not math.isfinite(probability)
                or not 0 <= probability <= 1
            ):
                raise ShadowContractError("invalid probability")
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
        return self._append(
            "prediction",
            {
                "synthetic_only": True,
                "experiment_version": experiment_version,
                "model_version": model_version,
                "model_hash": model_hash,
                "race_key": race_id,
                "cutoff_policy": cutoff_policy,
                "sealed_field_hash": field_hash,
                "snapshot_hash": snapshot_hash,
                "probabilities": sorted(clean, key=lambda row: row["entry_id"]),
                "status": "not_activated",
            },
            identity=identity,
        )

    def append_outcome_event(
        self,
        *,
        prediction_hash: str,
        source_id: str,
        body: bytes,
        event_type: str,
    ) -> str:
        self._event(prediction_hash, "prediction")
        if event_type not in {"result", "correction", "cancellation"} or not source_id:
            raise ShadowContractError("unapproved outcome event")
        raw_hash = self._store_raw(body)
        return self._append(
            "outcome",
            {
                "synthetic_only": True,
                "prediction_hash": prediction_hash,
                "source_id": source_id,
                "raw_sha256": raw_hash,
                "event_type": event_type,
                "evaluation_status": "held_dns_policy_unconfirmed",
            },
        )

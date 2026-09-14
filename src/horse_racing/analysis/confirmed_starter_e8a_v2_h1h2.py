"""Isolated E8-A v2 H1/H2 time-contract correction, synthetic only.

No new feature or operating integration. Every sampled clock value is checked
against the preceding sample, and admission payload acknowledgements are
checked against their committed pending rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from horse_racing.analysis.confirmed_starter_e8a import ShadowContractError, _positive_ms
from horse_racing.analysis.confirmed_starter_e8a_v2 import FEATURE, ShadowEvidenceStoreV2


class ShadowEvidenceStoreV2TimeChecked(ShadowEvidenceStoreV2):
    """A new-store-only time gate; never opens or migrates a v2 attempt root."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        with self._connect() as db:
            row = db.execute("SELECT created_ms FROM events ORDER BY id DESC LIMIT 1").fetchone()
        self._last_sample_ms = int(row["created_ms"]) if row is not None else 0

    def _now(self) -> int:
        sampled = super()._now()
        if sampled < self._last_sample_ms:
            raise ShadowContractError(
                f"clock regressed between stages: {sampled} < {self._last_sample_ms}"
            )
        self._last_sample_ms = sampled
        return sampled

    def _event_row(self, event_hash: str) -> tuple[int, dict[str, Any]]:
        with self._connect() as db:
            row = db.execute(
                "SELECT created_ms,payload_json FROM events WHERE event_hash=?", (event_hash,)
            ).fetchone()
        if row is None:
            raise ShadowContractError("admission predecessor missing")
        return int(row["created_ms"]), json.loads(row["payload_json"])

    def _append(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        identity: str | None = None,
        fail_before_commit: bool = False,
    ) -> str:
        ack_field = {
            "v2_observation_ack": "ack_ms",
            "v2_field_admission": "field_commit_ack_ms",
            "v2_snapshot_admission": "snapshot_commit_ack_ms",
            "v2_prediction_admission": "prediction_commit_ack_ms",
        }.get(kind)
        if ack_field is not None:
            predecessor = (
                payload["observation_hash"]
                if kind == "v2_observation_ack"
                else payload["pending_hash"]
            )
            inserted_at, preceding = self._event_row(predecessor)
            ack = _positive_ms(payload[ack_field], ack_field)
            lower = inserted_at
            if kind == "v2_observation_ack":
                lower = max(lower, preceding["parsed_at_ms"])
            elif kind == "v2_field_admission":
                observation = preceding["observation_hash"]
                observed_ack = self._admission(observation, "v2_observation_ack")["ack_ms"]
                lower = max(lower, observed_ack)
            elif kind == "v2_snapshot_admission":
                lower = max(
                    lower, preceding["source_ack_ms"], preceding["calculation_completed_ms"]
                )
            else:
                snapshot_hash = preceding["snapshot_hash"]
                snapshot_ack = self._admission(snapshot_hash, "v2_snapshot_admission")[
                    "snapshot_commit_ack_ms"
                ]
                lower = max(lower, snapshot_ack)
            if ack < lower:
                raise ShadowContractError(f"{kind} ack precedes required completed stage")
            deadline = payload.get("deadline_ms", payload.get("policy_cutoff_at_ms"))
            if payload.get("status") == "accepted" and ack > deadline:
                raise ShadowContractError("accepted admission ack exceeds deadline")
        return super()._append(
            kind, payload, identity=identity, fail_before_commit=fail_before_commit
        )

    def snapshot(self, *, field_hash, rows, feature_contracts, population):
        field = self._field(field_hash)
        contract = feature_contracts.get(FEATURE)
        if contract is not None:
            declared = _positive_ms(contract.get("available_at_ms"), "feature.available_at_ms")
            if declared > field["policy_cutoff_at_ms"]:
                raise ShadowContractError("declared feature availability exceeds cutoff")
        return super().snapshot(
            field_hash=field_hash,
            rows=rows,
            feature_contracts=feature_contracts,
            population=population,
        )

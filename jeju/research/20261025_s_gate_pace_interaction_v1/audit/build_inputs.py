"""Build audit-only G47 inputs from frozen S40 roster and phase-history assets.

No fitting, prediction, result-label read, database access, or network access is
performed. All source paths and SHA-256 pins are fixed below.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
TABLE_REL = "jeju/research/20261025_s_gate_pace_interaction_v1/audit/gate_pace_features.parquet"
CONTRACT_REL = "jeju/research/20261025_s_gate_pace_interaction_v1/audit/source_contract.json"
SYNTH_REL = "jeju/research/20261025_s_gate_pace_interaction_v1/audit/synthetic_checks.json"
CONTRACT_PIN = "9d0b5517dd05fef2ea7090bfaf564d571642f5a2316f54e830885e3db9e0c5ee"
SESSION_PIN = "a4eb8a10e8df7952cd033a8e61afadd577e059d5f13c09329d44e7101eefb231"

# Small metadata-only key table from the frozen 10/10 F1_STYLE6 roster.
# Phase values are read from only the explicit key/history columns below.
INPUTS = [
    ("jeju/research/20261025_s_gate_pace_interaction_v1/supervisor/DESIGN_CONTRACT.md", 9596,
     "9d0b5517dd05fef2ea7090bfaf564d571642f5a2316f54e830885e3db9e0c5ee", "frozen study contract"),
    ("jeju/research/20261025_s_gate_pace_interaction_v1/supervisor/SESSION_START.json", 29012,
     "a4eb8a10e8df7952cd033a8e61afadd577e059d5f13c09329d44e7101eefb231", "frozen source-tree pins and study budget"),
    ("jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet", 5476534,
     "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f", "S40 base roster keys and metadata only"),
    ("jeju/research/20261022_tb_state_transfer_v1/inputs/state_features.parquet", 3698878,
     "ac956c959ce853aa129c738113c598d4ecc968d88dc1306c0f5fa5f4712a78e7", "S40 exact target row-key set only"),
    ("jeju/research/20261022_tb_state_transfer_v1/inputs/input_manifest.json", 8245,
     "7561d6f91d5a1a5059add0741d912e33896b04810a19dd1dab955b0ebd229f5e", "S40 source/cohort pins"),
    ("jeju/research/20261021_phase_pace_prediction_v1/outputs/features_and_targets.parquet", 25306264,
     "0dcf70c9cb4822fb3c5198e1a138648062f5d94d1ef9bf712929d40e2a0dca33", "phase metadata and historical h10 S1F mean/n/slots only"),
    ("jeju/research/20261021_phase_pace_prediction_v1/outputs/history_lineage.parquet", 2822738,
     "1ed5b9432aa8491db6308e06d7a275c6318dafe969e465208980c1aac25e4785", "h10 selected prior API IDs and T-2/730-day bounds"),
    ("jeju/research/20261021_phase_pace_prediction_v1/outputs/feature_contract.json", 12093,
     "6026a3d500528ce1598919df0fd97b291b2513784c63b71cc4dba4cdcd200b67", "phase feature and history-window definitions"),
    ("jeju/research/20261021_phase_pace_prediction_v1/outputs/build_verification.json", 407,
     "bda33b4de4f65d6732c0275c771f870eb1ba1d150a02c616dcb55dcfd8dbd682", "existing phase history verification receipt"),
    ("jeju/research/20261021_phase_pace_prediction_v1/outputs/source_manifest.json", 2788,
     "75d7b8ee982b7e85849a7241809a5f6c00e766d116bb1ac97bbf28a63bdd2bfe", "phase source provenance"),
    ("jeju/research/20261021_phase_pace_prediction_v1/build.py", 13426,
     "0f2e6833f3f78262e072ec76cb021daac2265460a49d899478fe1f9229318624", "existing phase history selection code"),
    ("jeju/research/20261021_phase_pace_prediction_v1/verify_build.py", 5496,
     "522a9328d5940a09153fca0fc558ff02a800c5dba0147336dbf97557bca59aa3", "existing phase history verification code"),
]

FEATURES = [
    "pace_own_early_tendency",
    "pace_own_label_support_fraction_max10",
    "pace_inner_interaction",
    "pace_outer_interaction",
    "pace_adjacent_inner_interaction",
    "pace_adjacent_outer_interaction",
    "pace_opponent_observed_fraction",
]
PEER_GROUPS = ("inner", "outer", "adjacent_inner", "adjacent_outer")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pinned_source_records() -> list[dict[str, Any]]:
    records = []
    root = ROOT.resolve(strict=True)
    for rel, expected_bytes, expected_sha, role in INPUTS:
        path = (ROOT / rel).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError(f"source path escaped repository: {rel}")
        actual_bytes = path.stat().st_size
        actual_sha = sha256_file(path)
        if actual_bytes != expected_bytes or actual_sha != expected_sha:
            raise ValueError(f"source pin mismatch: {rel}")
        records.append({"path": rel, "bytes": actual_bytes, "sha256": actual_sha, "role": role})
    return records


def assert_session_pins(session: dict[str, Any]) -> None:
    tree_pins = {item["path"]: item for item in session["phase_reuse_tree_pins"]}
    for rel, nbytes, digest, _role in INPUTS:
        if "/20261021_phase_pace_prediction_v1/" not in rel:
            continue
        pin = tree_pins.get(rel)
        if pin is None or pin.get("bytes") != nbytes or pin.get("sha256") != digest:
            raise ValueError(f"phase source is not covered by frozen session pin: {rel}")


def parse_id_list(value: Any) -> list[int]:
    if value is None or (isinstance(value, float) and math.isnan(value)) or value == "":
        return []
    if not isinstance(value, str):
        raise TypeError("phase h10_ids must be a pipe-delimited string")
    items = [int(token) for token in value.split("|") if token]
    if len(items) != len(set(items)):
        raise ValueError("duplicate API ID in h10 lineage")
    return items


def q_value(mean: float | None, n: int) -> float:
    if n < 0 or n > 10:
        raise ValueError("h10 label count outside 0..10")
    if n == 0:
        if mean is not None and not math.isnan(float(mean)):
            raise ValueError("h10 mean must be null when n is zero")
        return 1.0 / 3.0
    if mean is None or not math.isfinite(float(mean)) or not 0.0 <= float(mean) <= 1.0:
        raise ValueError("h10 mean must be finite in [0,1] when n is positive")
    return (float(mean) * n + 1.0) / (n + 3.0)


def make_peer_payload(rivals: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rivals, key=lambda item: item["horse_number"])
    return {
        "ids": [int(item["api_record_id"]) for item in ordered],
        "horse_ids": [str(item["horse_id"]) for item in ordered],
        "numbers": [int(item["horse_number"]) for item in ordered],
        "n": [int(item["h10_s1f_0_n"]) for item in ordered],
        "support": [int(item["h10_s1f_0_n"]) > 0 for item in ordered],
        "q": [float(item["early_tendency_q"]) for item in ordered],
        "q_sum": float(sum(item["early_tendency_q"] for item in ordered)),
    }


def calculate_race(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(records) < 2:
        raise ValueError("S40 races must contain at least two runners")
    ids = [int(row["api_record_id"]) for row in records]
    nums = [int(row["horse_number"]) for row in records]
    if len(ids) != len(set(ids)) or len(nums) != len(set(nums)):
        raise ValueError("target race contains duplicate API IDs or horse numbers")
    if any(int(row["field_n"]) != len(records) for row in records):
        raise ValueError("target race field_n does not match its S40 roster")
    rows = []
    for own in records:
        number = int(own["horse_number"])
        rivals = [row for row in records if int(row["api_record_id"]) != int(own["api_record_id"])]
        inner = [row for row in rivals if int(row["horse_number"]) < number]
        outer = [row for row in rivals if int(row["horse_number"]) > number]
        adj_inner = [row for row in rivals if int(row["horse_number"]) == number - 1]
        adj_outer = [row for row in rivals if int(row["horse_number"]) == number + 1]
        n = int(own["h10_s1f_0_n"])
        q = q_value(own["h10_s1f_0_mean"], n)
        payload = {
            "pace_own_early_tendency": q,
            "pace_own_label_support_fraction_max10": n / 10.0,
            "pace_inner_interaction": q * sum(float(r["early_tendency_q"]) for r in inner),
            "pace_outer_interaction": q * sum(float(r["early_tendency_q"]) for r in outer),
            "pace_adjacent_inner_interaction": q * sum(float(r["early_tendency_q"]) for r in adj_inner),
            "pace_adjacent_outer_interaction": q * sum(float(r["early_tendency_q"]) for r in adj_outer),
            "pace_opponent_observed_fraction": sum(int(r["h10_s1f_0_n"]) > 0 for r in rivals) / len(rivals),
        }
        if any(not math.isfinite(float(value)) for value in payload.values()):
            raise ValueError("non-finite G47 feature")
        own.update(payload)
        own.update({
            "inner_rival": make_peer_payload(inner),
            "outer_rival": make_peer_payload(outer),
            "adjacent_inner_rival": make_peer_payload(adj_inner),
            "adjacent_outer_rival": make_peer_payload(adj_outer),
        })
        rows.append(own)
    return rows


def synthetic_checks() -> dict[str, Any]:
    def runner(api: int, number: int, n: int, mean: float | None, field_n: int = 4) -> dict[str, Any]:
        return {"api_record_id": api, "horse_id": f"H{api}", "horse_number": number,
                "field_n": field_n, "h10_s1f_0_n": n, "h10_s1f_0_mean": mean,
                "early_tendency_q": q_value(mean, n)}

    # Number gaps are preserved: for horse 4, horse 2 is inner but not adjacent.
    test = [runner(11, 2, 3, 1.0), runner(12, 4, 2, 0.0),
            runner(13, 5, 1, 0.75), runner(14, 6, 0, None)]
    result = {r["api_record_id"]: r for r in calculate_race(test)}
    r5 = result[13]
    assert math.isclose(r5["pace_inner_interaction"], (7.0 / 16.0) * (2.0 / 3.0 + 1.0 / 5.0), rel_tol=0, abs_tol=1e-12)
    assert math.isclose(r5["pace_outer_interaction"], (7.0 / 16.0) * (1.0 / 3.0), rel_tol=0, abs_tol=1e-12)
    assert math.isclose(r5["pace_adjacent_inner_interaction"], (7.0 / 16.0) * (1.0 / 5.0), rel_tol=0, abs_tol=1e-12)
    assert math.isclose(r5["pace_adjacent_outer_interaction"], (7.0 / 16.0) * (1.0 / 3.0), rel_tol=0, abs_tol=1e-12)
    assert math.isclose(r5["pace_opponent_observed_fraction"], 2.0 / 3.0, rel_tol=0, abs_tol=1e-12)
    assert result[14]["early_tendency_q"] == 1.0 / 3.0
    assert result[14]["inner_rival"]["support"] == [True, True, True]
    assert result[14]["inner_rival"]["ids"] == [11, 12, 13]
    assert result[12]["adjacent_inner_rival"]["ids"] == []
    assert result[12]["inner_rival"]["ids"] == [11]
    assert all(r["api_record_id"] not in r["inner_rival"]["ids"] + r["outer_rival"]["ids"]
               for r in result.values())

    # Holding the target q fixed and swapping opponents across it swaps sides.
    base = [runner(21, 4, 1, 0.5, 3), runner(22, 2, 1, 0.8, 3), runner(23, 6, 1, 0.2, 3)]
    swapped = [runner(31, 4, 1, 0.5, 3), runner(32, 6, 1, 0.8, 3), runner(33, 2, 1, 0.2, 3)]
    a = {r["api_record_id"]: r for r in calculate_race(base)}[21]
    b = {r["api_record_id"]: r for r in calculate_race(swapped)}[31]
    assert a["pace_inner_interaction"] > a["pace_outer_interaction"]
    assert b["pace_inner_interaction"] < b["pace_outer_interaction"]
    return {
        "passed": True,
        "checks": [
            "q uses 1/3 prior for n=0 and preserves unknown-history support flag",
            "self is excluded from every peer set",
            "inner and outer sums respond to the same opponent tendencies on different sides",
            "adjacent means integer number gap 1; skipped numbers are not compressed",
            "peer arrays are ordered by horse number and remain aligned",
            "observed fraction counts n>0 rivals, not q-prior values",
        ],
        "test_rows": 10,
        "no_training_or_performance_calculation": True,
    }


def source_pin_map() -> dict[str, dict[str, Any]]:
    return {record["path"]: record for record in pinned_source_records()}


def read_inputs() -> tuple[pd.DataFrame, dict[int, dict[str, Any]], list[dict[str, Any]]]:
    f1_path = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
    s_path = ROOT / "jeju/research/20261022_tb_state_transfer_v1/inputs/state_features.parquet"
    phase_path = ROOT / "jeju/research/20261021_phase_pace_prediction_v1/outputs/features_and_targets.parquet"
    lineage_path = ROOT / "jeju/research/20261021_phase_pace_prediction_v1/outputs/history_lineage.parquet"

    # Only target metadata/keys are selected from the old S40/F1 roster table.
    f1 = pd.read_parquet(f1_path, columns=["api_record_id", "race_id", "race_date", "horse_id",
                                           "horse_number", "distance_m", "field_n"])
    s40 = pd.read_parquet(s_path, columns=["api_record_id", "race_id", "race_date"])
    phase_cols = ["api_record_id", "race_id", "race_date", "race_number", "horse_id",
                  "horse_number", "race_distance_m", "field_n", "h10_slots",
                  "h10_s1f_0_mean", "h10_s1f_0_n"]
    phase = pd.read_parquet(phase_path, columns=phase_cols)
    lineage = pd.read_parquet(lineage_path, columns=["api_record_id", "cutoff", "lower", "h10_ids"])

    if not f1.api_record_id.is_unique or not s40.api_record_id.is_unique or not phase.api_record_id.is_unique or not lineage.api_record_id.is_unique:
        raise ValueError("a source API record key is not unique")
    if set(s40.api_record_id) != set(f1.api_record_id):
        raise ValueError("S40 target API ID set differs from frozen F1 target set")
    target = s40.merge(f1, on="api_record_id", how="left", suffixes=("_s40", "_f1"), validate="one_to_one")
    if target[["race_id_f1", "race_date_f1", "horse_id", "horse_number", "distance_m", "field_n"]].isna().any().any():
        raise ValueError("missing frozen F1 target metadata")
    target["race_date"] = pd.to_datetime(target.race_date_f1, format="%Y-%m-%d", errors="raise").dt.date
    target["race_date_s40"] = pd.to_datetime(target.race_date_s40, errors="raise").dt.date
    if not (target.race_id_s40.astype(str) == target.race_id_f1.astype(str)).all():
        raise ValueError("S40 race_id does not match frozen F1 roster")
    if not (target.race_date_s40 == target.race_date).all():
        raise ValueError("S40 race_date does not match frozen F1 roster")
    target["race_id"] = target.race_id_f1.astype(str)
    target["horse_id"] = target.horse_id.astype(str)
    target["horse_number"] = pd.to_numeric(target.horse_number, errors="raise").astype("int64")
    target["field_n"] = pd.to_numeric(target.field_n, errors="raise").astype("int64")
    distance = pd.to_numeric(target.distance_m, errors="raise")
    if not (distance == distance.round()).all():
        raise ValueError("non-integer target distance in frozen S40/F1 metadata")
    target["race_distance_m"] = distance.astype("int64")
    target = target[["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "field_n", "race_distance_m"]]

    phase_by_id = phase.set_index("api_record_id", drop=False)
    if not set(target.api_record_id).issubset(set(phase.api_record_id)):
        raise ValueError("S40 target IDs missing from phase history table")
    ph = phase_by_id.loc[target.api_record_id.to_numpy()].reset_index(drop=True)
    if not (ph.api_record_id.to_numpy() == target.api_record_id.to_numpy()).all():
        raise ValueError("phase target join order/key mismatch")
    phase_date = pd.to_datetime(ph.race_date, format="%Y-%m-%d", errors="raise").dt.date
    for name, left, right in [
        ("race_id", target.race_id.astype(str), ph.race_id.astype(str)),
        ("race_date", target.race_date, phase_date),
        ("horse_id", target.horse_id.astype(str), ph.horse_id.astype(str)),
        ("horse_number", target.horse_number, ph.horse_number),
        ("field_n", target.field_n, ph.field_n),
        ("race_distance_m", target.race_distance_m, ph.race_distance_m),
    ]:
        if not (left.reset_index(drop=True) == right.reset_index(drop=True)).all():
            raise ValueError(f"S40/F1 target metadata differs from phase source: {name}")
    target["h10_slots"] = pd.to_numeric(ph.h10_slots, errors="raise").astype("int64")
    target["h10_s1f_0_mean"] = pd.to_numeric(ph.h10_s1f_0_mean, errors="coerce")
    target["h10_s1f_0_n"] = pd.to_numeric(ph.h10_s1f_0_n, errors="raise").astype("int64")

    lin = lineage.set_index("api_record_id", drop=False)
    lin_targets = lin.loc[target.api_record_id.to_numpy()].reset_index(drop=True)
    if not (lin_targets.api_record_id.to_numpy() == target.api_record_id.to_numpy()).all():
        raise ValueError("history lineage target join order/key mismatch")
    target["history_cutoff"] = [date.fromisoformat(str(x)) for x in lin_targets.cutoff]
    target["history_lower"] = [date.fromisoformat(str(x)) for x in lin_targets.lower]

    phase_meta = phase[["api_record_id", "race_id", "race_date", "race_number", "horse_id"]].copy()
    phase_meta["race_date_obj"] = pd.to_datetime(phase_meta.race_date, format="%Y-%m-%d", errors="raise").dt.date
    meta = phase_meta.set_index("api_record_id", drop=False)
    history_ids_col: list[list[int]] = []
    history_dates_col: list[list[date]] = []
    for row, line in zip(target.itertuples(index=False), lin_targets.itertuples(index=False)):
        target_date = row.race_date
        expected_cutoff = target_date - timedelta(days=2)
        expected_lower = target_date - timedelta(days=730)
        if line.cutoff != expected_cutoff.isoformat() or line.lower != expected_lower.isoformat():
            raise ValueError(f"incorrect T-2/730-day metadata for target {row.api_record_id}")
        history_ids = parse_id_list(line.h10_ids)
        if len(history_ids) != int(row.h10_slots) or len(history_ids) > 10:
            raise ValueError(f"h10 slot count does not equal selected ID count for {row.api_record_id}")
        try:
            selected = meta.loc[history_ids]
        except KeyError as exc:
            raise ValueError(f"historical slot ID absent from phase metadata for {row.api_record_id}") from exc
        if isinstance(selected, pd.Series):
            selected = selected.to_frame().T
        hdates = selected.race_date_obj.tolist()
        if not (selected.horse_id.astype(str) == str(row.horse_id)).all():
            raise ValueError(f"historical slot horse ID differs from target for {row.api_record_id}")
        if any(not (expected_lower <= d <= expected_cutoff and d < target_date) for d in hdates):
            raise ValueError(f"historical slot date outside the T-2/730-day window for {row.api_record_id}")
        order = list(zip(hdates, selected.race_number.astype(int).tolist(), selected.api_record_id.astype(int).tolist()))
        if order != sorted(order):
            raise ValueError(f"h10 slot IDs not oldest-to-newest in phase lineage for {row.api_record_id}")
        n = int(row.h10_s1f_0_n)
        m = row.h10_s1f_0_mean
        if n < 0 or n > len(history_ids) or n > 10:
            raise ValueError(f"h10 S1F observation count exceeds selected slots for {row.api_record_id}")
        if n == 0:
            if not pd.isna(m):
                raise ValueError(f"h10 S1F mean should be null for zero observations: {row.api_record_id}")
        elif pd.isna(m) or not math.isfinite(float(m)) or not 0.0 <= float(m) <= 1.0:
            raise ValueError(f"invalid h10 S1F mean/count for {row.api_record_id}")
        history_ids_col.append(history_ids)
        history_dates_col.append(hdates)
    target["h10_ids"] = history_ids_col
    target["h10_dates"] = history_dates_col
    target["early_tendency_q"] = [q_value(None if pd.isna(m) else float(m), int(n))
                                   for m, n in zip(target.h10_s1f_0_mean, target.h10_s1f_0_n)]

    # Full S40 field consistency: no row is removed; number gaps are retained.
    for race_id, group in target.groupby("race_id", sort=False):
        if len(group) != int(group.field_n.iloc[0]) or group.field_n.nunique() != 1:
            raise ValueError(f"S40 roster size/field_n mismatch for {race_id}")
        if group.horse_number.nunique() != len(group) or group.api_record_id.nunique() != len(group):
            raise ValueError(f"duplicate target runner key/number in {race_id}")
    return target


def build_rows(target: pd.DataFrame) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    base_columns = ["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "field_n",
                    "race_distance_m", "h10_slots", "h10_s1f_0_mean", "h10_s1f_0_n", "h10_ids", "h10_dates",
                    "history_cutoff", "history_lower", "early_tendency_q"]
    for _race_id, group in target.groupby("race_id", sort=False):
        records = []
        for row in group.itertuples(index=False):
            item = row._asdict()
            item["race_date"] = row.race_date
            records.append(item)
        calculated = calculate_race(records)
        for item in calculated:
            out = {k: item[k] for k in base_columns}
            out.update({name: float(item[name]) for name in FEATURES})
            for prefix in PEER_GROUPS:
                key = prefix + "_rival"
                peer = item[key]
                out[prefix + "_rival_api_record_ids"] = peer["ids"]
                out[prefix + "_rival_horse_ids"] = peer["horse_ids"]
                out[prefix + "_rival_horse_numbers"] = peer["numbers"]
                out[prefix + "_rival_h10_s1f_0_n"] = peer["n"]
                out[prefix + "_rival_support"] = peer["support"]
                out[prefix + "_rival_q"] = peer["q"]
                out[prefix + "_rival_q_sum"] = peer["q_sum"]
            output.append(out)
    return output


def make_schema() -> pa.Schema:
    fields: list[pa.Field] = [
        pa.field("api_record_id", pa.int64(), nullable=False),
        pa.field("race_id", pa.string(), nullable=False),
        pa.field("race_date", pa.date32(), nullable=False),
        pa.field("horse_id", pa.string(), nullable=False),
        pa.field("horse_number", pa.int64(), nullable=False),
        pa.field("field_n", pa.int64(), nullable=False),
        pa.field("race_distance_m", pa.int64(), nullable=False),
        pa.field("h10_slots", pa.int64(), nullable=False),
        pa.field("h10_s1f_0_mean", pa.float64(), nullable=True),
        pa.field("h10_s1f_0_n", pa.int64(), nullable=False),
        pa.field("h10_ids", pa.list_(pa.int64()), nullable=False),
        pa.field("h10_dates", pa.list_(pa.date32()), nullable=False),
        pa.field("history_cutoff", pa.date32(), nullable=False),
        pa.field("history_lower", pa.date32(), nullable=False),
        pa.field("early_tendency_q", pa.float64(), nullable=False),
    ]
    fields.extend(pa.field(name, pa.float64(), nullable=False) for name in FEATURES)
    for prefix in PEER_GROUPS:
        fields.extend([
            pa.field(prefix + "_rival_api_record_ids", pa.list_(pa.int64()), nullable=False),
            pa.field(prefix + "_rival_horse_ids", pa.list_(pa.string()), nullable=False),
            pa.field(prefix + "_rival_horse_numbers", pa.list_(pa.int64()), nullable=False),
            pa.field(prefix + "_rival_h10_s1f_0_n", pa.list_(pa.int64()), nullable=False),
            pa.field(prefix + "_rival_support", pa.list_(pa.bool_()), nullable=False),
            pa.field(prefix + "_rival_q", pa.list_(pa.float64()), nullable=False),
            pa.field(prefix + "_rival_q_sum", pa.float64(), nullable=False),
        ])
    return pa.schema(fields, metadata={
        b"study_spec": b"s_gate_pace_v1_7f",
        b"feature_columns": json.dumps(FEATURES, separators=(",", ":")).encode(),
        b"history_cutoff": b"target race date minus 2 calendar days, inclusive",
        b"history_window": b"target race date minus 730 calendar days through cutoff, inclusive",
        b"result_labels_used_for_input": b"false",
    })


def census(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_year: dict[str, dict[str, int]] = {}
    slots: dict[str, int] = {}
    support_n: dict[str, int] = {}
    peer_counts: dict[str, int] = {group: 0 for group in PEER_GROUPS}
    for row in rows:
        year = str(row["race_date"].year)
        by_year.setdefault(year, {"rows": 0, "races": 0})["rows"] += 1
        slots[str(row["h10_slots"])] = slots.get(str(row["h10_slots"]), 0) + 1
        support_n[str(row["h10_s1f_0_n"])] = support_n.get(str(row["h10_s1f_0_n"]), 0) + 1
        for group in PEER_GROUPS:
            peer_counts[group] += len(row[group + "_rival_api_record_ids"])
    race_year_seen: dict[str, set[str]] = {}
    for row in rows:
        race_year_seen.setdefault(str(row["race_date"].year), set()).add(row["race_id"])
    for year, races in race_year_seen.items():
        by_year[year]["races"] = len(races)
    return {
        "target_rows": len(rows),
        "target_races": len({row["race_id"] for row in rows}),
        "target_years": by_year,
        "h10_actual_start_slot_count": dict(sorted(slots.items(), key=lambda x: int(x[0]))),
        "h10_valid_s1f_label_count": dict(sorted(support_n.items(), key=lambda x: int(x[0]))),
        "rows_with_zero_valid_s1f_labels": support_n.get("0", 0),
        "rows_with_at_least_three_valid_s1f_labels": sum(v for k, v in support_n.items() if int(k) >= 3),
        "peer_lineage_item_counts": peer_counts,
        "all_seven_feature_values_finite": all(math.isfinite(float(row[name])) for row in rows for name in FEATURES),
        "all_target_rows_retained": True,
    }


def write_json_new(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        raise FileExistsError(f"refusing to overwrite temporary {tmp}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main() -> None:
    if (OUT / "gate_pace_features.parquet").exists() or (OUT / "source_contract.json").exists() or (OUT / "synthetic_checks.json").exists():
        raise FileExistsError("audit outputs already exist; refusing to overwrite frozen files")
    synth = synthetic_checks()
    before = pinned_source_records()
    session = json.loads((ROOT / INPUTS[1][0]).read_text(encoding="utf-8"))
    assert_session_pins(session)
    s40_input = json.loads((ROOT / INPUTS[4][0]).read_text(encoding="utf-8"))
    f1_pin = s40_input["source_files"]["f1_style6_target_keys_source"]
    state_pin = s40_input["files"]["state_features.parquet"]
    if (f1_pin["path"], f1_pin["bytes"], f1_pin["sha256"]) != (INPUTS[2][0], INPUTS[2][1], INPUTS[2][2]):
        raise ValueError("S40 input manifest F1 target-key source pin mismatch")
    if (state_pin["path"], state_pin["bytes"], state_pin["sha256"]) != (INPUTS[3][0], INPUTS[3][1], INPUTS[3][2]):
        raise ValueError("S40 state input pin mismatch")

    target = read_inputs()
    rows = build_rows(target)
    if len(rows) != 52155 or len({row["race_id"] for row in rows}) != 5206:
        raise ValueError("target cohort does not match frozen S40 52,155/5,206 scope")
    support = census(rows)
    if support["target_rows"] != 52155 or support["target_races"] != 5206 or not support["all_seven_feature_values_finite"]:
        raise ValueError("G47 census/finite-value check failed")

    # Confirm every source file is unchanged after the read/feature build and before writing outputs.
    after_build = pinned_source_records()
    if before != after_build:
        raise ValueError("one or more pinned source files changed during input construction")

    table_path = OUT / "gate_pace_features.parquet"
    tmp_table = OUT / "gate_pace_features.parquet.tmp"
    if tmp_table.exists():
        raise FileExistsError(f"refusing to overwrite temporary {tmp_table}")
    table = pa.Table.from_pylist(rows, schema=make_schema())
    pq.write_table(table, tmp_table, compression="zstd", compression_level=9,
                   use_dictionary=True, write_statistics=True, data_page_version="2.0")
    table_bytes = tmp_table.stat().st_size
    if table_bytes > 8_000_000:
        tmp_table.unlink()
        raise ValueError(f"thin audit Parquet exceeds 8 MB allowance: {table_bytes}")
    table_sha = sha256_file(tmp_table)
    os.replace(tmp_table, table_path)

    synth_path = OUT / "synthetic_checks.json"
    write_json_new(synth_path, synth)
    synth_record = {"path": SYNTH_REL, "bytes": synth_path.stat().st_size, "sha256": sha256_file(synth_path)}
    builder_rel = "jeju/research/20261025_s_gate_pace_interaction_v1/audit/build_inputs.py"
    builder_path = ROOT / builder_rel
    builder_record = {"path": builder_rel, "bytes": builder_path.stat().st_size, "sha256": sha256_file(builder_path)}
    after_write = pinned_source_records()
    if before != after_write:
        raise ValueError("one or more pinned source files changed during output writing")

    contract = {
        "spec_id": "s_gate_pace_v1_7f",
        "passed": True,
        "feature_columns": FEATURES,
        "input_artifact": {"path": TABLE_REL, "bytes": table_bytes, "sha256": table_sha,
                           "rows": len(rows), "races": support["target_races"], "compression": "zstd"},
        "source_references": before,
        "builder": builder_record,
        "synthetic_checks": synth_record,
        "numeric_rules": {
            "cutoff_lag_days": 2,
            "lookback_days": 730,
            "history_lower_and_cutoff_inclusive": True,
            "max_history_slots": 10,
            "history_same_official_horse_id": True,
            "h10_slots_source": "h10_slots",
            "history_slot_ids_source": "history_lineage.h10_ids",
            "history_slot_date_source": "features_and_targets.parquet keyed by h10 API record IDs",
            "history_slot_order": "oldest-to-newest, preserved from frozen h10 lineage",
            "h10_mean_column": "h10_s1f_0_mean",
            "h10_observation_count_column": "h10_s1f_0_n",
            "prior_positive": 1,
            "prior_strength": 3,
            "q_formula": "(h10_s1f_0_mean * h10_s1f_0_n + 1) / (h10_s1f_0_n + 3); n=0 -> 1/3",
            "adjacent_number_gap": 1,
            "peer_roster": "all other runners from the exact frozen S40 race roster; self excluded",
            "empty_peer_sum": 0,
            "peer_order": "ascending horse_number; all peer arrays share identical element order",
            "race_number_gaps": "preserved; no compression after scratches",
            "feature_formulas": {
                "pace_own_early_tendency": "q_i",
                "pace_own_label_support_fraction_max10": "n_i / 10",
                "pace_inner_interaction": "q_i * sum(q_j for same-race S40 rivals with horse_number_j < horse_number_i)",
                "pace_outer_interaction": "q_i * sum(q_j for same-race S40 rivals with horse_number_j > horse_number_i)",
                "pace_adjacent_inner_interaction": "q_i * sum(q_j for same-race S40 rivals with horse_number_j = horse_number_i - 1)",
                "pace_adjacent_outer_interaction": "q_i * sum(q_j for same-race S40 rivals with horse_number_j = horse_number_i + 1)",
                "pace_opponent_observed_fraction": "count(other same-race S40 rivals with h10_s1f_0_n > 0) / (field_n - 1)",
            },
        },
        "support": support,
        "limitations": [
            {"id": "event_time_only", "detail": "T-2 is an event-date cutoff; source publication/first-availability timestamps are unverified."},
            {"id": "first_pack_semantics", "detail": "Historical S1F first-pack indicator is not solo-leader, physical contest, or an individual tactical running-style label."},
            {"id": "no_history", "detail": "n=0 q=1/3 is prior shrinkage with zero observed-label support; it does not mean no prior starts or a late-running horse."},
            {"id": "left_truncation", "detail": "Historical source starts in 2017; early target windows may be left-truncated."},
            {"id": "gate_mapping", "detail": "Horse number is used as the contracted ordering axis; mapping to physical starting stalls/track position is unverified."},
            {"id": "not_joint_event_probability", "detail": "q and products are covariates for fitting, not calibrated current-race or simultaneous early-pack probabilities."},
            {"id": "cohort", "detail": "All 52,155 S40 runner rows/5,206 races are retained; no extra phase-only race/runner enters the peer roster."},
            {"id": "oos_predictions_excluded", "detail": "No learned phase-model OOS probability, target label, result, market input, fit, or performance calculation was read or used."},
        ],
        "validation": {
            "source_pins_checked_before_reads": True,
            "source_pins_checked_after_build": True,
            "source_pins_checked_after_output_write": True,
            "target_api_id_join_exact": True,
            "target_metadata_join_exact": True,
            "history_slot_id_date_horse_window_checked": True,
            "all_s40_race_rosters_and_unique_numbers_checked": True,
            "synthetic_formula_checks_passed": bool(synth["passed"]),
            "fit_or_evaluation_run": False,
        },
    }
    # Store all actual bytes/hashes for the input artifact after the atomic rename.
    if table_path.stat().st_size != table_bytes or sha256_file(table_path) != table_sha:
        raise ValueError("final Parquet differs from its pre-rename hash")
    write_json_new(OUT / "source_contract.json", contract)

    print(json.dumps({
        "passed": True,
        "rows": len(rows),
        "races": support["target_races"],
        "parquet_bytes": table_bytes,
        "parquet_sha256": table_sha,
        "source_contract_path": CONTRACT_REL,
        "source_contract_sha256": sha256_file(OUT / "source_contract.json"),
        "builder_sha256": builder_record["sha256"],
        "fit_or_evaluation_run": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

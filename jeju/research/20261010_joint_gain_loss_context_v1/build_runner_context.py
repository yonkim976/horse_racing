#!/usr/bin/env python3
"""Reconstruct and verify the frozen supplemental runner context from local caches.

Default mode is verify-only: it reconstructs rows in memory and compares them
with the existing runner_context.csv. It never overwrites that file. Optional
--write-new and --receipt paths must be new files in this supplement directory.
No database, network, model fitting, or external packages are used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = BASE / "runner_context.csv"
TARGET = ROOT / "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv"
LINEAGE = ROOT / "jeju/research/20261008_weight_speed_v2/source_lineage.csv"
RACE_SUPPORT = ROOT / "jeju/research/20261007_track_environment_v1/race_support_rows.json"
F1_REFERENCE = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/f1_reproduced_race_metrics.csv"
EXCLUDED_HORSE_ID = "3005648"

EXPECTED_INPUT_HASHES = {
    TARGET: "0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09",
    LINEAGE: "95c44c1571f1ca383b57c5b9e98a8d9c1f32ebb1b9d19763db82ff51d3ed6346",
    RACE_SUPPORT: "1a8b202da7024c9d42ac51d688dbbe473ad695bdc5c9011672d3a60b861720c5",
    F1_REFERENCE: "89e783d9c2022cf7a91f7effc39a359ebcf755541c8d33073c0ce795e3341c07",
}

OUTPUT_FIELDS = [
    "api_record_id",
    "race_id",
    "race_date",
    "evaluation_year",
    "horse_id",
    "race_distance_m",
    "field_n",
    "rank_class_raw",
    "month",
    "horse_number",
    "jockey_id",
    "body_kg",
    "body_weight_raw",
    "reported_body_change_raw",
    "carried_weight_kg",
    "track_raw",
    "moisture",
    "band",
    "history_cutoff",
    "api4_3_payload_sha256",
    "result_payload_sha256",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def number(value: str, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite: {value!r}")
    return result


def check_input_hashes() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_INPUT_HASHES.items():
        if not path.is_file():
            raise FileNotFoundError(f"Required frozen source is missing: {path}")
        got = sha256(path)
        actual[str(path.relative_to(ROOT))] = got
        if got != expected:
            raise ValueError(
                f"Frozen source hash mismatch for {path.relative_to(ROOT)}: "
                f"expected {expected}, got {got}"
            )
    return actual


def unique_index(rows: list[dict[str, str]], key: str, label: str) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(key, "")
        if not value:
            raise ValueError(f"{label} has an empty {key}")
        if value in index:
            raise ValueError(f"{label} has duplicate {key}={value}")
        index[value] = row
    return index


def source_band(moisture: float) -> str:
    # Match jeju/research/20261007_track_environment_v1/audit_support.py.
    if moisture <= 5:
        return "건조"
    if moisture <= 9:
        return "양호"
    if moisture <= 14:
        return "다습"
    if moisture <= 19:
        return "포화"
    return "불량"


def build_rows() -> tuple[list[dict[str, str]], dict[str, Any]]:
    target_rows = read_csv(TARGET)
    lineage_rows = read_csv(LINEAGE)
    target_by_id = unique_index(target_rows, "api_record_id", "target runner cohort")
    lineage_by_id = unique_index(lineage_rows, "api_record_id", "source lineage")
    if len(target_rows) != 17_412 or len({r["race_id"] for r in target_rows}) != 1_779:
        raise ValueError("Target cohort totals differ from the fixed 17,412 runner / 1,779 race cohort")
    dates = {r["race_date"] for r in target_rows}
    if len(dates) != 269 or min(dates) != "2024-01-05" or max(dates) != "2026-09-19":
        raise ValueError("Target date coverage differs from the fixed 269-date interval")
    missing = sorted(set(target_by_id) - set(lineage_by_id))
    if missing:
        raise ValueError(f"Target IDs missing from source lineage: {missing[:5]}")

    # Every event API ID must be represented once in the race support JSON.
    support_rows = read_json(RACE_SUPPORT)
    support_by_api_id: dict[str, dict[str, Any]] = {}
    support_by_race_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for race in support_rows:
        race_key = (str(race["race_date"]), str(race["meet_code"]), str(race["race_number"]))
        if race_key in support_by_race_key:
            raise ValueError(f"Duplicate race-support tuple: {race_key}")
        support_by_race_key[race_key] = race
        for api_id in race.get("source_api_record_ids", []):
            api_key = str(api_id)
            if api_key in support_by_api_id:
                raise ValueError(f"Duplicate API ID in race-support JSON: {api_key}")
            support_by_api_id[api_key] = race
    if not set(target_by_id).issubset(support_by_api_id):
        raise ValueError("Not all target API IDs are covered by race-support JSON")

    f1_rows = [r for r in read_csv(F1_REFERENCE) if r.get("variant") == "F1"]
    f1_by_race_id = unique_index(f1_rows, "race_id", "F1 race reference")
    if len(f1_by_race_id) != 1_779:
        raise ValueError(f"Expected 1,779 unique F1 race rows, got {len(f1_by_race_id)}")

    expected_rows: list[dict[str, str]] = []
    mismatch_counts = {name: 0 for name in ("race_id", "race_date", "evaluation_year", "horse_number")}
    race_context: dict[str, tuple[str, str, str]] = {}
    numeric_bounds: dict[str, list[float]] = {
        "body_kg": [math.inf, -math.inf],
        "carried_weight_kg": [math.inf, -math.inf],
        "moisture": [math.inf, -math.inf],
        "race_distance_m": [math.inf, -math.inf],
        "field_n": [math.inf, -math.inf],
        "horse_number": [math.inf, -math.inf],
    }
    band_counts: dict[str, int] = {}
    for target in target_rows:  # retain frozen target order
        api_id = target["api_record_id"]
        source = lineage_by_id[api_id]
        expected_equal = {
            "race_id": (target["race_id"], source["race_id"]),
            "race_date": (target["race_date"], source["race_date"]),
            "evaluation_year": (target["evaluation_year"], source["year"]),
            "horse_number": (target["horse_number"], source["horse_number"]),
        }
        for field, (left, right) in expected_equal.items():
            if left != right:
                mismatch_counts[field] += 1
        if any(mismatch_counts.values()):
            raise ValueError(f"Target/source key mismatch observed: {mismatch_counts}")

        month_from_date = str(date.fromisoformat(source["race_date"]).month)
        if source["month"] != month_from_date:
            raise ValueError(f"Calendar month mismatch for API ID {api_id}")
        body = number(source["body_kg"], f"body_kg[{api_id}]")
        burden = number(source["carried_weight_kg"], f"carried_weight_kg[{api_id}]")
        moisture = number(source["moisture"], f"moisture[{api_id}]")
        distance = number(source["race_distance_m"], f"race_distance_m[{api_id}]")
        field_n = number(source["field_n"], f"field_n[{api_id}]")
        horse_number = number(source["horse_number"], f"horse_number[{api_id}]")
        checks = {
            "body_kg": (body, 209, 347),
            "carried_weight_kg": (burden, 51, 65.5),
            "moisture": (moisture, 2, 20),
            "race_distance_m": (distance, 800, 1610),
            "field_n": (field_n, 7, 13),
            "horse_number": (horse_number, 1, 12),
        }
        for name, (value, low, high) in checks.items():
            if not low <= value <= high:
                raise ValueError(f"{name}[{api_id}]={value} outside audited source range [{low}, {high}]")
            numeric_bounds[name][0] = min(numeric_bounds[name][0], value)
            numeric_bounds[name][1] = max(numeric_bounds[name][1], value)
        if not horse_number.is_integer() or not field_n.is_integer():
            raise ValueError(f"Non-integer field size or horse number for API ID {api_id}")
        if not re.fullmatch(r"\d{6}", source["jockey_id"]):
            raise ValueError(f"jockey_id must remain a zero-padded six-digit identifier ({api_id})")
        if source["band"] != source_band(moisture):
            raise ValueError(f"Moisture/band rule disagreement for API ID {api_id}")
        band_counts[source["band"]] = band_counts.get(source["band"], 0) + 1

        # Confirm race-support tuple and same-race source annotations.
        parts = source["race_id"].split("_")
        if len(parts) != 3:
            raise ValueError(f"Unexpected race_id format: {source['race_id']}")
        race_key = (source["race_date"], parts[1], parts[2])
        support = support_by_api_id[api_id]
        if race_key != (str(support["race_date"]), str(support["meet_code"]), str(support["race_number"])):
            raise ValueError(f"Race tuple mismatch between target lineage and race support for {api_id}")
        for f, left, right in (
            ("race_id", source["race_id"], source["race_date"] + "_" + str(support["meet_code"]) + "_" + str(support["race_number"])),
            ("race_date", source["race_date"], str(support["race_date"])),
            ("rank_class_raw", source["rank_class_raw"], str(support["grade_raw"])),
        ):
            if left != right:
                raise ValueError(f"Race support {f} mismatch for API ID {api_id}")
        for f, left, right in (
            ("distance", distance, float(support["distance_m"])),
            ("field_n", field_n, float(support["field_n"])),
            ("moisture", moisture, float(support["moisture_percent"])),
        ):
            if left != right:
                raise ValueError(f"Race support {f} mismatch for API ID {api_id}")
        if source["band"] != str(support["band"]):
            raise ValueError(f"Race support band mismatch for API ID {api_id}")

        f1 = f1_by_race_id.get(source["race_id"])
        if f1 is None:
            raise ValueError(f"F1 race reference missing target race {source['race_id']}")
        for field, left, right in (
            ("race_date", source["race_date"], f1["race_date"]),
            ("evaluation_year", source["year"], f1["year"]),
            ("rank_class_raw", source["rank_class_raw"], f1["grade_raw"]),
        ):
            if left != right:
                raise ValueError(f"F1 race reference {field} mismatch for {source['race_id']}")
        for field, left, right in (
            ("race_distance_m", distance, number(f1["distance_m"], f"F1 distance[{source['race_id']}]") ),
            ("field_n", field_n, number(f1["field_n"], f"F1 field_n[{source['race_id']}]") ),
        ):
            if left != right:
                raise ValueError(f"F1 race reference {field} mismatch for {source['race_id']}")

        track_raw = str(support["track_raw"])
        current_race_context = (source["moisture"], source["band"], track_raw)
        previous = race_context.setdefault(source["race_id"], current_race_context)
        if previous != current_race_context:
            raise ValueError(f"Within-race moisture/band/track disagreement for {source['race_id']}")

        expected_rows.append({
            "api_record_id": api_id,
            "race_id": source["race_id"],
            "race_date": source["race_date"],
            "evaluation_year": target["evaluation_year"],
            "horse_id": source["horse_id"],
            "race_distance_m": source["race_distance_m"],
            "field_n": source["field_n"],
            "rank_class_raw": source["rank_class_raw"],
            "month": source["month"],
            "horse_number": source["horse_number"],
            "jockey_id": source["jockey_id"],
            "body_kg": source["body_kg"],
            "body_weight_raw": source["body_weight_raw"],
            "reported_body_change_raw": source["reported_body_change_raw"],
            "carried_weight_kg": source["carried_weight_kg"],
            "track_raw": track_raw,
            "moisture": source["moisture"],
            "band": source["band"],
            "history_cutoff": source["history_cutoff"],
            "api4_3_payload_sha256": source["api4_3_payload_sha256"],
            "result_payload_sha256": source["result_payload_sha256"],
        })

    if len(race_context) != 1_779:
        raise ValueError(f"Race context coverage expected 1,779; got {len(race_context)}")
    if any(row["horse_id"] == EXCLUDED_HORSE_ID for row in expected_rows):
        raise ValueError(f"Excluded horse ID {EXCLUDED_HORSE_ID} present in target cohort")
    if set(target_by_id) != {row["api_record_id"] for row in expected_rows}:
        raise ValueError("Reconstructed key set differs from target key set")

    metadata = {
        "target_rows": len(target_rows),
        "target_unique_api_record_ids": len(target_by_id),
        "target_races": len(race_context),
        "target_race_dates": len(dates),
        "lineage_rows": len(lineage_rows),
        "target_id_coverage": f"{len(expected_rows)}/{len(target_rows)}",
        "target_race_coverage": f"{len(race_context)}/1779",
        "target_source_mismatches": mismatch_counts,
        "moisture_band_counts": dict(sorted(band_counts.items())),
        "numeric_ranges_observed": {k: [v[0], v[1]] for k, v in numeric_bounds.items()},
        "race_level_moisture_band_track_consistency": "all 1,779 races constant",
        "excluded_horse_id": EXCLUDED_HORSE_ID,
        "excluded_horse_matches": 0,
        "labels_or_prediction_scores_in_extract": False,
        "database_or_network_accessed": False,
        "model_fitting_executed": False,
    }
    return expected_rows, metadata


def serialize(rows: list[dict[str, str]]) -> bytes:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_FIELDS, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def check_semantic_parity(path: Path, expected: list[dict[str, str]]) -> bool:
    actual = read_csv(path)
    if actual and list(actual[0]) != OUTPUT_FIELDS:
        raise ValueError(f"Existing CSV columns differ: {list(actual[0])}")
    if len(actual) != len(expected):
        raise ValueError(f"Existing CSV row count {len(actual)} differs from reconstructed {len(expected)}")
    for index, (got, want) in enumerate(zip(actual, expected), start=2):
        if got != want:
            mismatches = [key for key in OUTPUT_FIELDS if got.get(key) != want.get(key)]
            raise ValueError(f"Semantic row mismatch at CSV line {index}, fields={mismatches[:8]}")
    return True


def local_new_path(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    try:
        path.relative_to(BASE.resolve())
    except ValueError as exc:
        raise ValueError("New output and receipt paths must stay inside the supplement directory") from exc
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing path: {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-new", metavar="PATH", help="write reconstructed CSV to a new path inside this directory")
    parser.add_argument("--receipt", metavar="PATH", help="write verification JSON to a new path inside this directory")
    args = parser.parse_args()

    input_hashes = check_input_hashes()
    expected_rows, metadata = build_rows()
    generated_bytes = serialize(expected_rows)

    if args.write_new:
        output_path = local_new_path(args.write_new)
        output_path.parent.mkdir(parents=False, exist_ok=True)
        output_path.write_bytes(generated_bytes)
        output_mode = "write_new"
        byte_parity = None
        semantic_parity = None
    else:
        output_path = DEFAULT_OUTPUT
        if not output_path.is_file():
            raise FileNotFoundError(f"Verify-only mode needs existing CSV: {output_path}")
        existing_bytes = output_path.read_bytes()
        byte_parity = existing_bytes == generated_bytes
        semantic_parity = check_semantic_parity(output_path, expected_rows)
        output_mode = "verify_only"

    code_path = Path(__file__).resolve()
    receipt = {
        "artifact": "20261010_joint_gain_loss_context_v1 runner_context supplement",
        "script": str(code_path.relative_to(ROOT)),
        "script_sha256": sha256(code_path),
        "mode": output_mode,
        "output_path": str(output_path.relative_to(ROOT)),
        "output_sha256": sha256(output_path),
        "output_bytes": output_path.stat().st_size,
        "reconstructed_sha256": hashlib.sha256(generated_bytes).hexdigest(),
        "reconstructed_bytes": len(generated_bytes),
        "byte_parity": byte_parity,
        "semantic_parity": semantic_parity,
        "input_hashes": input_hashes,
        "checks": metadata,
    }
    rendered_receipt = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.receipt:
        receipt_path = local_new_path(args.receipt)
        receipt_path.parent.mkdir(parents=False, exist_ok=True)
        receipt_path.write_text(rendered_receipt, encoding="utf-8")
        receipt["receipt_path"] = str(receipt_path.relative_to(ROOT))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"VERIFY FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)

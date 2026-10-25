"""Independently compare candidate support tables with reconstructed F1 slot values."""
import sys

sys.dont_write_bytecode = True

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INDEPENDENT = HERE / "independent_outputs"
CANDIDATE = ROOT / "jeju/research/20261009_section_time_ablation_v1/outputs"
OUT = HERE / "independent_candidate_support_comparison.json"
SECTIONS = ("s1f", "g3f", "g1f")
VALID_N_COLUMNS = {section: f"{section}_valid_n" for section in SECTIONS}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def derive_group_table(frame):
    data = frame.copy()
    data["experience_group"] = pd.cut(
        data.observed_starts, [-1, 0, 4, np.inf], labels=["0", "1_4", "5_plus"]
    ).astype("string")
    rows = []
    groupings = (
        ("distance_m", ["distance_m"]),
        ("year", ["year"]),
        ("distance_year", ["distance_m", "year"]),
        ("experience_group", ["experience_group"]),
    )
    for group_kind, keys in groupings:
        for key, group in data.groupby(keys, dropna=False, sort=True):
            values = key if isinstance(key, tuple) else (key,)
            key_columns = dict(zip(keys, values))
            for section, valid_col in VALID_N_COLUMNS.items():
                n_dist = group[valid_col].value_counts().reindex(range(6), fill_value=0)
                rows.append({
                    "group_kind": group_kind,
                    **key_columns,
                    "section": section,
                    "target_rows": int(len(group)),
                    "targets_with_any_valid_slot": int(group[valid_col].gt(0).sum()),
                    "eligible_historical_slots": int(group[valid_col].sum()),
                    **{f"targets_n_{n}": int(n_dist.loc[n]) for n in range(6)},
                })
    return pd.DataFrame(rows)


def derive_n_distribution(frame):
    data = frame.copy()
    data["experience_group"] = pd.cut(
        data.observed_starts, [-1, 0, 4, np.inf], labels=["0", "1_4", "5_plus"]
    ).astype("string")
    rows = []
    keys = ["year", "distance_m", "experience_group"]
    for group_key, group in data.groupby(keys, dropna=False, sort=True):
        year, distance, experience = group_key
        for section, valid_col in VALID_N_COLUMNS.items():
            counts = group[valid_col].value_counts().reindex(range(6), fill_value=0)
            for valid_n, count in counts.items():
                rows.append({
                    "year": int(year),
                    "distance_m": int(distance),
                    "experience_group": str(experience),
                    "section": section,
                    "valid_n": int(valid_n),
                    "target_rows": int(count),
                })
    return pd.DataFrame(rows)


def canonical(frame, columns):
    out = frame[columns].copy()
    for col in columns:
        if col in {"year", "distance_m", "target_rows", "targets_with_any_valid_slot", "eligible_historical_slots", *[f"targets_n_{n}" for n in range(6)], "valid_n"}:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(-999).astype("int64")
        else:
            out[col] = out[col].fillna("").astype(str)
    return out.sort_values(columns).reset_index(drop=True)


def assert_equal(left, right, columns, label):
    a = canonical(left, columns)
    b = canonical(right, columns)
    if not a.equals(b):
        diff = a.merge(b, on=columns[:0], how="outer", indicator=True) if False else None
        raise AssertionError(f"{label} differs: independent={a.shape}, candidate={b.shape}")
    return {"rows": int(len(a)), "columns": columns, "exact_match": True}


def main():
    source_receipt_path = INDEPENDENT / "independent_source_availability_receipt.json"
    feature_path = INDEPENDENT / "independent_target_feature_reconstruction.csv"
    candidate_audit_path = CANDIDATE / "source_availability_audit.json"
    candidate_group_path = CANDIDATE / "source_availability_by_group.csv"
    candidate_n_path = CANDIDATE / "source_valid_n_distribution.csv"
    for path in (source_receipt_path, feature_path, candidate_audit_path, candidate_group_path, candidate_n_path):
        assert path.is_file(), f"missing expected audit input: {path}"
    source_receipt = json.loads(source_receipt_path.read_text(encoding="utf-8"))
    candidate_audit = json.loads(candidate_audit_path.read_text(encoding="utf-8"))
    features = pd.read_csv(feature_path)
    candidate_group = pd.read_csv(candidate_group_path)
    candidate_n = pd.read_csv(candidate_n_path)

    independent_group = derive_group_table(features)
    group_columns = [
        "group_kind", "distance_m", "year", "experience_group", "section",
        "target_rows", "targets_with_any_valid_slot", "eligible_historical_slots",
        *[f"targets_n_{n}" for n in range(6)],
    ]
    for frame in (independent_group, candidate_group):
        for col in group_columns:
            if col not in frame:
                frame[col] = np.nan
    group_match = assert_equal(independent_group, candidate_group, group_columns, "group support")

    independent_n = derive_n_distribution(features)
    n_columns = ["year", "distance_m", "experience_group", "section", "valid_n", "target_rows"]
    n_match = assert_equal(independent_n, candidate_n, n_columns, "year/distance/experience valid-n distribution")

    independent_receipt = source_receipt
    independent_mask = {
        (row["race_key"], row["point"])
        for row in independent_receipt["race_section_conflict_mask"]["masked_race_points"]
    }
    candidate_mask = set()
    for point in ("S1F", "G1F"):
        section_key = point.lower()
        candidate_mask.update(
            (race_key, point)
            for race_key in candidate_audit["race_section_conflict_masks"][section_key]["race_keys"]
        )
    assert independent_mask == candidate_mask

    independent_ddl_hashes = independent_receipt["quality_view_dependency_ddl_sha256"]
    candidate_ddl_hashes = candidate_audit["quality_source_access"]["quality_view_dependency_ddl_sha256"]
    assert independent_ddl_hashes == candidate_ddl_hashes, {
        "independent": independent_ddl_hashes,
        "candidate": candidate_ddl_hashes,
    }

    independent_fields = {
        item["section"]: item for item in independent_receipt["field_slot_audit"]
    }
    candidate_fields = {
        item["section"]: item for item in candidate_audit["field_slot_audit"]
    }
    field_matches = {}
    for section in SECTIONS:
        left = independent_fields[section]
        right = candidate_fields[section]
        values = {
            "actual_slots": (left["actual_slot_rows"], right["slot_rows"]),
            "eligible_slots": (left["eligible_slot_rows"], right["eligible_slot_rows"]),
            "selected_time_slots": (left["positive_quality_selected_time_rows"], right["selected_value_rows_before_valid_time_and_conflict_mask"]),
            "invalid_source_time_exclusions": (left["excluded_for_invalid_source_time"], right["rows_excluded_by_valid_time"]),
            "conflict_time_exclusions": (left["excluded_for_section_conflict"], right["rows_excluded_by_race_section_conflict"]),
        }
        assert all(a == b for a, b in values.values()), (section, values)
        field_matches[section] = {name: {"independent": int(a), "candidate": int(b), "match": a == b} for name, (a, b) in values.items()}

    checks = {
        "independently_reconstructed_support_by_group_exact_match": group_match["exact_match"],
        "independently_reconstructed_valid_n_distribution_exact_match": n_match["exact_match"],
        "race_section_conflict_keys_exact_match": independent_mask == candidate_mask,
        "quality_view_dependency_ddl_sha256_exact_match": independent_ddl_hashes == candidate_ddl_hashes,
        "all_field_slot_support_counts_match": all(
            item["eligible_slots"]["match"] and item["conflict_time_exclusions"]["match"]
            for item in field_matches.values()
        ),
        "no_model_scoring_or_fit_or_temperature_or_prediction_metrics": True,
    }
    assert all(checks.values()), checks

    payload = {
        "review_status": "candidate_source_audit_independently_reaggregated_and_matched",
        "fit_executed": False,
        "candidate_generation_functions_reused": False,
        "independent_quality_source_reconstruction_reused": True,
        "support_table_matches": {"by_group": group_match, "valid_n_distribution": n_match},
        "quality_view_dependency_ddl_sha256_match": independent_ddl_hashes,
        "field_slot_matches": field_matches,
        "conflict_mask_match": {
            "exact_race_point_keys": len(independent_mask),
            "keys": sorted([{"race_key": race, "point": point} for race, point in independent_mask], key=lambda x: (x["race_key"], x["point"])),
        },
        "checks": checks,
        "references": {
            str(path.relative_to(ROOT)): {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (source_receipt_path, feature_path, candidate_audit_path, candidate_group_path, candidate_n_path)
        },
        "review_code_sha256": sha256(Path(__file__)),
    }
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite: {OUT}")
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

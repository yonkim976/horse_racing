"""Read-only exact-duplicate check for the ten raw pair inputs in each frozen H1 fold."""

from __future__ import annotations

import hashlib
import itertools
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[2]
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
RUNNER_AUDIT = HERE / "independent_runner_features.parquet"
SOURCE_RECEIPT = HERE / "independent_prefit_receipt.json"
BASELINE_FIT = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/FIT.json"
OUTPUT = HERE / "independent_h1_duplicate_receipt.json"
FEATURE_COLUMNS = [
    "previous_rider_retained_count",
    "previous_rider_unknown_count",
    "rider365_delta_sum",
    "rider365_current_support_log1p_sum",
    "rider365_previous_support_log1p_sum",
    "rider365_delta_unavailable_count",
    "horse_current_rider_rides_log1p_sum",
    "horse_current_rider_recency_log1p_sum",
    "horse_current_rider_first_observed_pair_count",
    "horse_current_rider_history_unavailable_count",
]
RUNNER_COLUMNS = [
    "previous_rider_retained", "previous_rider_unknown", "rider365_delta_feature_value",
    "rider365_current_n", "rider365_previous_n", "rider365_delta_unavailable",
    "horse_current_rider_past_started_n", "horse_current_rider_recency_days_asof_t2",
    "horse_current_rider_first_observed", "horse_current_rider_history_unavailable",
]
EXPECTED_H1 = {2024: 2147, 2025: 2818, 2026: 3458}
EXPECTED_PAIRS = {2024: 101158, 2025: 130929, 2026: 159060}


class AuditError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AuditError(message)


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"symlink input is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with checked(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def h1_roster(rows: pd.DataFrame, evaluation_year: int) -> pd.DataFrame:
    source = rows.loc[rows["year"].eq(evaluation_year - 1)].copy()
    h2 = source.loc[source["race_date"].dt.month.ge(7)]
    require(not h2.empty, f"empty H2 source roster for {evaluation_year}")
    cutoff = h2["race_date"].min().date() - timedelta(days=2)
    earlier = rows.loc[rows["year"].between(2019, evaluation_year - 2)].copy()
    current = source.loc[
        source["race_date"].dt.month.le(6)
        & source["race_date"].dt.date.map(lambda value: value <= cutoff)
    ].copy()
    h1 = pd.concat([earlier, current], ignore_index=True)
    require(h1["api_record_id"].is_unique, f"duplicate H1 runner key for {evaluation_year}")
    require(h1["race_id"].nunique() == EXPECTED_H1[evaluation_year],
            f"H1 race count differs from frozen split for {evaluation_year}")
    return h1


def main() -> None:
    require(not OUTPUT.exists(), "refusing to overwrite H1 duplicate receipt")
    keys = pd.read_parquet(checked(FEATURES), columns=[
        "api_record_id", "race_id", "race_date", "year", "horse_number",
    ], filters=[("year", ">=", 2019), ("year", "<=", 2025)])
    keys["api_record_id"] = pd.to_numeric(keys["api_record_id"], errors="raise").astype("int64")
    keys["race_id"] = keys["race_id"].astype("string")
    keys["race_date"] = pd.to_datetime(keys["race_date"], errors="raise").dt.normalize()
    keys["horse_number"] = pd.to_numeric(keys["horse_number"], errors="raise").astype("int64")
    require(keys["api_record_id"].is_unique, "frozen target runner key is not unique")

    runner = pd.read_parquet(checked(RUNNER_AUDIT))
    runner["api_record_id"] = pd.to_numeric(runner["api_record_id"], errors="raise").astype("int64")
    require(runner["api_record_id"].is_unique, "independent runner feature key is not unique")
    runner_values = keys[["api_record_id", "race_id", "race_date", "year", "horse_number"]].merge(
        runner[["api_record_id", *RUNNER_COLUMNS]], on="api_record_id", how="left",
        validate="one_to_one", indicator=True,
    )
    require(runner_values["_merge"].eq("both").all(), "independent runner feature missing from frozen H1 key roster")
    runner_values = runner_values.drop(columns="_merge")
    runner_values["horse_current_rider_recency_days_asof_t2"] = pd.to_numeric(
        runner_values["horse_current_rider_recency_days_asof_t2"], errors="coerce",
    ).fillna(0)
    runner_numeric = np.column_stack((
        runner_values["previous_rider_retained"].astype(bool).to_numpy(dtype=float),
        runner_values["previous_rider_unknown"].astype(bool).to_numpy(dtype=float),
        pd.to_numeric(runner_values["rider365_delta_feature_value"], errors="raise").to_numpy(dtype=float),
        np.log1p(pd.to_numeric(runner_values["rider365_current_n"], errors="raise").to_numpy(dtype=float)),
        np.log1p(pd.to_numeric(runner_values["rider365_previous_n"], errors="raise").to_numpy(dtype=float)),
        runner_values["rider365_delta_unavailable"].astype(bool).to_numpy(dtype=float),
        np.log1p(pd.to_numeric(runner_values["horse_current_rider_past_started_n"], errors="raise").to_numpy(dtype=float)),
        np.log1p(runner_values["horse_current_rider_recency_days_asof_t2"].to_numpy(dtype=float)),
        runner_values["horse_current_rider_first_observed"].astype(bool).to_numpy(dtype=float),
        runner_values["horse_current_rider_history_unavailable"].astype(bool).to_numpy(dtype=float),
    ))
    require(runner_numeric.shape == (len(runner_values), 10) and np.isfinite(runner_numeric).all(),
            "non-finite runner-level inputs")
    runner_values["_runner_position"] = np.arange(len(runner_values), dtype=np.int64)
    keys = keys.merge(runner_values[["api_record_id", "_runner_position"]], on="api_record_id",
                      how="left", validate="one_to_one")
    require(keys["_runner_position"].notna().all(), "H1 feature position missing")
    keys["_runner_position"] = keys["_runner_position"].astype("int64")

    fold_receipts: dict[str, Any] = {}
    all_fold_arrays: dict[int, list[np.ndarray]] = {}
    for evaluation_year in (2024, 2025, 2026):
        h1 = h1_roster(keys, evaluation_year)
        race_arrays: list[np.ndarray] = []
        pair_rows = 0
        for race_id, race in h1.groupby("race_id", sort=True):
            race = race.sort_values("horse_number", kind="mergesort")
            numbers = race["horse_number"].to_numpy(dtype=np.int64)
            require(len(numbers) >= 4 and len(np.unique(numbers)) == len(numbers),
                    f"invalid H1 pair roster in {evaluation_year}/{race_id}")
            values = runner_numeric[race["_runner_position"].to_numpy(dtype=np.int64)]
            pair_index = np.asarray(list(itertools.combinations(range(len(numbers)), 2)), dtype=np.int64)
            pair_values = values[pair_index[:, 0]] + values[pair_index[:, 1]]
            require(pair_values.shape[1] == 10 and np.isfinite(pair_values).all(),
                    f"invalid pair feature block in {evaluation_year}/{race_id}")
            pair_rows += len(pair_values)
            race_arrays.append(pair_values)
        require(len(race_arrays) == EXPECTED_H1[evaluation_year],
                f"H1 race rows changed in {evaluation_year}")
        require(pair_rows == EXPECTED_PAIRS[evaluation_year],
                f"H1 unordered pair count differs from saved fit in {evaluation_year}")
        matrix = np.vstack(race_arrays)
        all_fold_arrays[evaluation_year] = race_arrays
        duplicates: list[dict[str, str]] = []
        for left in range(len(FEATURE_COLUMNS)):
            for right in range(left + 1, len(FEATURE_COLUMNS)):
                if np.array_equal(matrix[:, left], matrix[:, right]):
                    duplicates.append({"left": FEATURE_COLUMNS[left], "right": FEATURE_COLUMNS[right]})
        fold_receipts[str(evaluation_year)] = {
            "h1_races": len(race_arrays), "h1_pair_rows": pair_rows,
            "finite_values": bool(np.isfinite(matrix).all()),
            "exact_duplicate_column_pairs": duplicates,
        }

    across_fold_duplicate_pairs: list[dict[str, str]] = []
    for left in range(len(FEATURE_COLUMNS)):
        for right in range(left + 1, len(FEATURE_COLUMNS)):
            equal_in_all = True
            for fold_arrays in all_fold_arrays.values():
                left_values = np.concatenate([block[:, left] for block in fold_arrays])
                right_values = np.concatenate([block[:, right] for block in fold_arrays])
                if not np.array_equal(left_values, right_values):
                    equal_in_all = False
                    break
            if equal_in_all:
                across_fold_duplicate_pairs.append({"left": FEATURE_COLUMNS[left], "right": FEATURE_COLUMNS[right]})

    source_receipt = json.loads(checked(SOURCE_RECEIPT).read_text(encoding="utf-8"))
    baseline_fit = json.loads(checked(BASELINE_FIT).read_text(encoding="utf-8"))
    expected_pair_rows = {
        str(row["evaluation_year"]): int(row["h1_pairs"]) for row in baseline_fit["folds"]
    }
    require({year: value["h1_pair_rows"] for year, value in fold_receipts.items()} == expected_pair_rows,
            "independent H1 pair roster differs from saved H1 training pair counts")
    require(source_receipt["status"] == "PASS", "upstream independent source receipt is not PASS")

    output = {
        "status": "PASS",
        "scope": "read-only H1 feature exact-duplicate check; no optimization, target labels, predictions, or performance metrics generated",
        "target_finish_labels_read": False,
        "historical_finish_results_read_for_input_features": True,
        "pair_roster_rule": "all unordered horse-number pairs within the exact frozen H1 race roster; same calendar split and 2-day purge",
        "input_feature_columns": FEATURE_COLUMNS,
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (FEATURES, RUNNER_AUDIT, SOURCE_RECEIPT, BASELINE_FIT)
        },
        "folds": fold_receipts,
        "exact_duplicate_column_pairs_across_all_h1_folds": across_fold_duplicate_pairs,
        "exact_duplicate_removal_rule_recommendation": "retain all ten raw columns in the source audit; in each fold's H1 fit matrix keep the first feature in fixed column order among exact duplicate columns and record the dropped column; standardize and fit only retained columns",
        "artifact_paths": {"receipt": str(OUTPUT.relative_to(ROOT))},
    }
    with OUTPUT.open("x", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({
        "status": output["status"], "folds": fold_receipts,
        "exact_duplicate_column_pairs_across_all_h1_folds": across_fold_duplicate_pairs,
        "receipt": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

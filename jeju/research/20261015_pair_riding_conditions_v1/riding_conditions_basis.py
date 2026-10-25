"""Fixed symmetric 10-column pair basis for the riding-conditions study."""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


RUNNER_COLUMNS = (
    "previous_rider_retained",
    "previous_rider_unknown",
    "rider365_delta",
    "rider365_current_support_log1p",
    "rider365_previous_support_log1p",
    "rider365_delta_unavailable",
    "horse_current_rider_rides_log1p",
    "horse_current_rider_recency_log1p",
    "horse_current_rider_first_observed",
    "horse_current_rider_history_unavailable",
)

PAIR_COLUMNS = (
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
)

RUNNER_TO_PAIR = dict(zip(RUNNER_COLUMNS, PAIR_COLUMNS, strict=True))
PAIR_TO_RUNNER = dict(zip(PAIR_COLUMNS, RUNNER_COLUMNS, strict=True))


class BasisError(RuntimeError):
    """Raised when the fixed pair-feature contract is violated."""


def require(ok: bool, message: str) -> None:
    if not ok:
        raise BasisError(message)


def pair_features_for_race(race: pd.DataFrame) -> pd.DataFrame:
    """Build every unordered horse-number pair by summing the two runner rows."""
    required = {"race_id", "race_date", "year", "distance_m", "horse_number", *RUNNER_COLUMNS}
    require(required.issubset(race.columns), "runner rows lack fixed pair-feature inputs")
    require(race["race_id"].nunique(dropna=False) == 1, "pair builder received multiple races")
    require(race["horse_number"].notna().all(), "pair builder received missing horse number")
    ordered = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
    numbers = ordered["horse_number"].astype(int).to_numpy()
    require(len(numbers) >= 2 and len(set(numbers.tolist())) == len(numbers),
            "pair builder received too few or duplicate horse numbers")
    values = ordered.loc[:, RUNNER_COLUMNS].to_numpy(dtype=float)
    require(np.isfinite(values).all(), "pair builder received non-finite runner feature")
    meta = ordered.iloc[0]
    rows = []
    for left, right in combinations(range(len(numbers)), 2):
        row = {
            "race_id": str(meta["race_id"]),
            "race_date": pd.Timestamp(meta["race_date"]).date().isoformat(),
            "year": int(meta["year"]),
            "distance_m": int(meta["distance_m"]),
            "horse_i": int(numbers[left]),
            "horse_j": int(numbers[right]),
        }
        row.update({
            pair_name: float(values[left, index] + values[right, index])
            for index, (runner_name, pair_name) in enumerate(RUNNER_TO_PAIR.items())
        })
        rows.append(row)
    result = pd.DataFrame(rows)
    require(result[[*PAIR_COLUMNS]].to_numpy(dtype=float).shape == (len(numbers) * (len(numbers) - 1) // 2, 10),
            "pair feature shape changed")
    require(np.isfinite(result.loc[:, PAIR_COLUMNS].to_numpy(dtype=float)).all(),
            "pair builder produced non-finite feature")
    return result


def fit_race_equal_moments(h1_runner_rows: pd.DataFrame) -> dict:
    """Compute candidate pair means/scales with equal total weight per H1 race."""
    required = {"race_id", *RUNNER_COLUMNS}
    require(required.issubset(h1_runner_rows.columns), "H1 rows lack fixed runner basis")
    require(not h1_runner_rows.empty, "cannot fit moments on empty H1")
    race_means: list[np.ndarray] = []
    race_seconds: list[np.ndarray] = []
    race_blocks: list[np.ndarray] = []
    pair_count = 0
    for _, race in h1_runner_rows.groupby("race_id", sort=True):
        pairs = pair_features_for_race(race)
        x = pairs.loc[:, PAIR_COLUMNS].to_numpy(dtype=float)
        race_means.append(x.mean(axis=0))
        race_seconds.append(np.square(x).mean(axis=0))
        race_blocks.append(x)
        pair_count += len(x)
    means = np.asarray(race_means, dtype=float)
    seconds = np.asarray(race_seconds, dtype=float)
    mean = means.mean(axis=0)
    variance = np.maximum(seconds.mean(axis=0) - np.square(mean), 0.0)
    scale = np.sqrt(variance)
    require(np.isfinite(mean).all() and np.isfinite(scale).all(), "non-finite H1 pair moments")
    all_pairs = np.vstack(race_blocks)
    kept_columns: list[int] = []
    duplicate_columns: dict[str, str] = {}
    for index, name in enumerate(PAIR_COLUMNS):
        duplicate_of = next((prior for prior in kept_columns
                             if np.array_equal(all_pairs[:, index], all_pairs[:, prior])), None)
        if duplicate_of is None:
            kept_columns.append(index)
        else:
            duplicate_columns[name] = PAIR_COLUMNS[duplicate_of]
    return {
        "columns": list(PAIR_COLUMNS),
        "mean": {name: float(mean[i]) for i, name in enumerate(PAIR_COLUMNS)},
        "scale": {name: float(scale[i]) for i, name in enumerate(PAIR_COLUMNS)},
        "degenerate_columns": [name for i, name in enumerate(PAIR_COLUMNS) if scale[i] <= 1e-12],
        "exact_duplicate_columns": duplicate_columns,
        "fit_excluded_columns": sorted(set(duplicate_columns) | {
            name for i, name in enumerate(PAIR_COLUMNS) if scale[i] <= 1e-12
        }, key=PAIR_COLUMNS.index),
        "fit_retained_columns": [name for name in PAIR_COLUMNS if name not in set(duplicate_columns)
                                 and scale[PAIR_COLUMNS.index(name)] > 1e-12],
        "h1_races": int(len(race_means)),
        "h1_unordered_pairs": int(pair_count),
        "weighting": "equal total weight per race; equal unordered pairs within each race",
        "zero_placeholder_rows_included": True,
    }


def transform_pair_features(pair_rows: pd.DataFrame, moments: dict) -> np.ndarray:
    """Standardize with frozen H1 moments; omit only H1-degenerate columns."""
    require(list(moments.get("columns", [])) == list(PAIR_COLUMNS), "pair-moment column order changed")
    require(set(PAIR_COLUMNS).issubset(pair_rows.columns), "pair rows lack candidate columns")
    excluded = set(moments["fit_excluded_columns"])
    active = [name for name in PAIR_COLUMNS if name not in excluded]
    mean = np.asarray([float(moments["mean"][name]) for name in active])
    scale = np.asarray([float(moments["scale"][name]) for name in active])
    require(np.isfinite(scale).all() and (scale > 1e-12).all(), "active H1 pair scale is degenerate")
    x = pair_rows.loc[:, active].to_numpy(dtype=float)
    result = (x - mean) / scale
    require(np.isfinite(result).all(), "non-finite standardized riding-conditions pair features")
    return result

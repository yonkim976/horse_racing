"""Seven symmetric, H1-standardized pair features for the reliability study."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


BASIS_NAMES = (
    "log1p_min_observed_starts",
    "log1p_min_same_valid_times",
    "min_valid_n5",
    "max_cv5_ratio",
    "cv5_unavailable_runner_count",
    "max_log1p_days_since_same_start",
    "same_start_gap_unavailable_runner_count",
)
COUNT_COLUMNS = ("observed_starts", "same_starts", "same_valid_times", "valid_n5")
RUNNER_COLUMNS = (
    "horse_number", "observed_starts", "same_starts", "same_valid_times",
    "days_since_same", "mean5_s", "valid_n5", "std5_s",
)
MISSING_ALLOWED = frozenset((3, 5))


class PairReliabilityBasisError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise PairReliabilityBasisError(message)


def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PairReliabilityBasisError(f"invalid numeric runner value for {name}") from exc
    require(math.isfinite(result), f"non-finite runner value for {name}")
    return result


def _runner_values(rows: pd.DataFrame) -> dict[int, dict[str, Any]]:
    require(set(RUNNER_COLUMNS).issubset(rows.columns), "runner rows lack reliability-source columns")
    require(not rows["horse_number"].isna().any(), "runner horse number is missing")
    result: dict[int, dict[str, Any]] = {}
    for row in rows.loc[:, RUNNER_COLUMNS].itertuples(index=False, name=None):
        number = int(row[0])
        require(number > 0 and number not in result, "invalid or duplicate horse number")
        values = dict(zip(RUNNER_COLUMNS, row, strict=True))
        counts: dict[str, int] = {}
        for column in COUNT_COLUMNS:
            value = _number(values[column], column)
            require(value >= 0 and value.is_integer(), f"{column} must be a nonnegative integer")
            counts[column] = int(value)
        require(counts["valid_n5"] <= 5, "valid_n5 exceeds the five actual slots")
        require(counts["same_valid_times"] <= counts["same_starts"],
                "same_valid_times exceeds all same-distance started observations")

        mean = values["mean5_s"]
        std = values["std5_s"]
        mean_finite = pd.notna(mean) and math.isfinite(float(mean))
        std_finite = pd.notna(std) and math.isfinite(float(std))
        n5 = counts["valid_n5"]
        require(mean_finite == (n5 > 0), "mean5_s missingness conflicts with valid_n5")
        require((n5 >= 3) == std_finite,
                "std5_s availability must match the source contract valid_n5 >= 3")
        if mean_finite:
            require(float(mean) > 0.0, "mean5_s must be positive when observed")
        if std_finite:
            require(float(std) >= 0.0, "std5_s must be nonnegative")

        gap = values["days_since_same"]
        gap_finite = pd.notna(gap) and math.isfinite(float(gap))
        require(gap_finite == (counts["same_starts"] > 0),
                "days_since_same missingness conflicts with same_starts")
        if gap_finite:
            require(float(gap) >= 0.0, "days_since_same must be nonnegative")

        cv_ok = n5 >= 3 and mean_finite and float(mean) > 0.0 and std_finite and float(std) >= 0.0
        gap_ok = counts["same_starts"] > 0 and gap_finite and float(gap) >= 0.0
        result[number] = {
            "observed_starts": counts["observed_starts"],
            "same_starts": counts["same_starts"],
            "same_valid_times": counts["same_valid_times"],
            "valid_n5": n5,
            "cv5": float(std) / float(mean) if cv_ok else None,
            "cv5_available": bool(cv_ok),
            "days_since_same": float(gap) if gap_ok else None,
            "same_start_gap_available": bool(gap_ok),
        }
    return result


def race_pair_basis(rows: pd.DataFrame, pairs: list[tuple[int, int]]) -> np.ndarray:
    """Create the frozen seven-column unordered-pair matrix for one race."""
    by_number = _runner_values(rows)
    require(bool(pairs), "race has no unordered pairs")
    matrix = np.empty((len(pairs), len(BASIS_NAMES)), dtype=np.float64)
    for index, pair in enumerate(pairs):
        require(len(pair) == 2 and pair[0] < pair[1], "pair numbers must be ascending")
        require(pair[0] in by_number and pair[1] in by_number, "pair number absent from runner rows")
        left, right = by_number[pair[0]], by_number[pair[1]]
        matrix[index, 0] = math.log1p(min(left["observed_starts"], right["observed_starts"]))
        matrix[index, 1] = math.log1p(min(left["same_valid_times"], right["same_valid_times"]))
        matrix[index, 2] = min(left["valid_n5"], right["valid_n5"])
        cv_known = left["cv5_available"] and right["cv5_available"]
        matrix[index, 3] = max(left["cv5"], right["cv5"]) if cv_known else np.nan
        matrix[index, 4] = int(not left["cv5_available"]) + int(not right["cv5_available"])
        gap_known = left["same_start_gap_available"] and right["same_start_gap_available"]
        matrix[index, 5] = (
            max(math.log1p(left["days_since_same"]), math.log1p(right["days_since_same"]))
            if gap_known else np.nan
        )
        matrix[index, 6] = int(not left["same_start_gap_available"]) + int(not right["same_start_gap_available"])
    require(matrix.ndim == 2 and matrix.shape == (len(pairs), 7), "seven-column pair design shape changed")
    require(np.isfinite(matrix[:, [0, 1, 2, 4, 6]]).all(), "non-finite count/support pair basis")
    require(np.isnan(matrix[:, [3, 5]]).any() or np.isfinite(matrix[:, [3, 5]]).all(),
            "unexpected non-finite raw CV/recency basis")
    require(not np.isinf(matrix).any(), "infinite raw reliability feature")
    require(np.isin(matrix[:, [4, 6]], (0.0, 1.0, 2.0)).all(), "pair missing count outside 0..2")
    return matrix


def fit_race_equal_moments(race_matrices: list[np.ndarray]) -> dict[str, Any]:
    """Fit each column's H1 mean and population scale with equal race weight.

    Every pair has weight 1/(H1 race count * pair count in that race). A
    nullable column's mean divides its weighted observed sum by its weighted
    observed support. Missing pair values are then imputed to that H1 mean
    (z=0); variance uses all H1 pair weights after that imputation.
    """
    require(bool(race_matrices), "cannot fit new moments on an empty H1")
    arrays = [np.asarray(block, dtype=np.float64) for block in race_matrices]
    require(all(x.ndim == 2 and x.shape[1] == 7 and len(x) > 0 for x in arrays),
            "invalid H1 reliability pair matrix")
    require(all(not np.isinf(x).any() for x in arrays), "infinite H1 reliability feature")
    means: list[float] = []
    scales: list[float] = []
    degenerate: list[bool] = []
    column_support: list[dict[str, Any]] = []
    for column, name in enumerate(BASIS_NAMES):
        race_count = len(arrays)
        race_weights = [1.0 / (race_count * len(block)) for block in arrays]
        observed_count = int(sum(np.isfinite(block[:, column]).sum() for block in arrays))
        missing_count = int(sum(np.isnan(block[:, column]).sum() for block in arrays))
        races_with_support = int(sum(np.isfinite(block[:, column]).any() for block in arrays))
        weighted_support = float(sum(
            race_weights[race_index] * np.isfinite(block[:, column]).sum()
            for race_index, block in enumerate(arrays)
        ))
        if observed_count and weighted_support > 0.0:
            weighted_sum = float(sum(
                race_weights[race_index] * np.nansum(block[:, column])
                for race_index, block in enumerate(arrays)
            ))
            mean = weighted_sum / weighted_support
            weighted_variance = float(sum(
                race_weights[race_index] * np.sum(
                    (np.where(np.isfinite(block[:, column]), block[:, column], mean) - mean) ** 2
                )
                for race_index, block in enumerate(arrays)
            ))
            variance = weighted_variance
            require(math.isfinite(mean) and math.isfinite(variance) and variance >= 0.0,
                    f"invalid H1 reliability moments for {name}")
            scale = math.sqrt(variance)
            is_degenerate = scale <= 1e-12
            means.append(mean)
            scales.append(1.0 if is_degenerate else scale)
            degenerate.append(bool(is_degenerate))
        else:
            means.append(0.0)
            scales.append(1.0)
            degenerate.append(True)
        column_support.append({
            "basis": name,
            "observed_pair_values": observed_count,
            "imputed_pair_values": missing_count,
            "races_with_observed_values": races_with_support,
            "race_equal_mean": means[-1],
            "race_equal_scale": scales[-1],
            "degenerate": degenerate[-1],
            "weighted_finite_pair_support": weighted_support,
            "moment_scope": "H1 only; each race has total weight 1/H1 races and each pair equal within race; null raw values imputed to H1 mean",
        })
    return {
        "basis_names": list(BASIS_NAMES),
        "mean": np.asarray(means, dtype=np.float64),
        "scale": np.asarray(scales, dtype=np.float64),
        "degenerate": tuple(degenerate),
        "support": column_support,
        "h1_races": len(arrays),
        "h1_pairs": int(sum(len(block) for block in arrays)),
    }


def transform_race(matrix: np.ndarray, moments: dict[str, Any]) -> np.ndarray:
    """Apply only saved H1 moments, imputing null raw values to H1 mean."""
    x = np.asarray(matrix, dtype=np.float64)
    mean = np.asarray(moments["mean"], dtype=np.float64)
    scale = np.asarray(moments["scale"], dtype=np.float64)
    degenerate = np.asarray(moments["degenerate"], dtype=bool)
    require(x.ndim == 2 and x.shape[1] == 7, "raw pair matrix must have seven columns")
    require(mean.shape == scale.shape == degenerate.shape == (7,), "H1 moments must have seven columns")
    require(not np.isinf(x).any() and np.isfinite(mean).all() and np.isfinite(scale).all(),
            "non-finite reliability transform input")
    require((scale > 0).all(), "non-positive reliability scale")
    filled = np.where(np.isfinite(x), x, mean[None, :])
    z = (filled - mean[None, :]) / scale[None, :]
    z[:, degenerate] = 0.0
    require(z.shape == x.shape and np.isfinite(z).all(), "invalid standardized reliability matrix")
    return z

"""Plackett--Luce marginal probabilities for the Jeju place target.

The public marginal is the probability that each starter occupies any one of
the first three slots.  It is therefore a per-starter top-three probability,
and its race total is three.  The implementation enumerates the complete
ordered top-three PL distribution in log space so it agrees with the sealed
top-three evaluator even for large raw-score margins.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any

import numpy as np


class JejuPlaceProbabilityError(ValueError):
    """Raised when place-probability inputs violate the race contract."""


_TIE_REL_TOL = 1e-12
_TIE_ABS_TOL = 1e-15


def _id_key(value: Any) -> tuple[str, str]:
    if value is None or isinstance(value, bool):
        raise JejuPlaceProbabilityError("horse IDs must be non-null strings or numbers")
    if not isinstance(value, (str, int, float)):
        raise JejuPlaceProbabilityError("horse IDs must be JSON scalar strings or numbers")
    if isinstance(value, float) and not math.isfinite(value):
        raise JejuPlaceProbabilityError("horse IDs must be finite")
    return type(value).__name__, str(value)


def _ids(horse_ids: Sequence[Any]) -> list[Any]:
    if isinstance(horse_ids, (str, bytes)):
        raise JejuPlaceProbabilityError("horse_ids must be a sequence of IDs")
    try:
        values = list(horse_ids)
    except TypeError as exc:
        raise JejuPlaceProbabilityError("horse_ids must be a sequence of IDs") from exc
    if len(values) < 3:
        raise JejuPlaceProbabilityError("a race requires at least three horses")
    keys = [_id_key(value) for value in values]
    if len(set(keys)) != len(values):
        raise JejuPlaceProbabilityError("horse_ids must be unique")
    return values


def _scores(scores: Sequence[Any], size: int) -> np.ndarray:
    if isinstance(scores, (str, bytes)):
        raise JejuPlaceProbabilityError("scores must align with horse_ids")
    try:
        raw_values = list(scores)
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in raw_values):
            raise JejuPlaceProbabilityError("scores must be finite real numbers")
        values = np.asarray(raw_values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise JejuPlaceProbabilityError("scores must be finite real numbers") from exc
    if values.ndim != 1 or len(values) != size or not np.all(np.isfinite(values)):
        raise JejuPlaceProbabilityError("scores must be finite and match horse_ids")
    return values


def _beta(beta: Any) -> float:
    if isinstance(beta, bool) or not isinstance(beta, Real):
        raise JejuPlaceProbabilityError("beta must be a positive finite number")
    value = float(beta)
    if not math.isfinite(value) or value <= 0:
        raise JejuPlaceProbabilityError("beta must be a positive finite number")
    return value


def _logsumexp(values: Sequence[float]) -> float:
    maximum = max(values)
    return float(maximum + math.log(math.fsum(math.exp(value - maximum) for value in values)))


def _pl_slot_marginals(scores: Sequence[Any], beta: Real) -> np.ndarray:
    raw = np.asarray(scores, dtype=float)
    beta_value = _beta(beta)
    scaled = raw * beta_value
    if not np.all(np.isfinite(scaled)):
        raise JejuPlaceProbabilityError("beta times score must remain finite")
    log_worth = scaled - np.max(scaled)
    n_horses = len(raw)
    all_indices = tuple(range(n_horses))
    first_denominator = _logsumexp(log_worth.tolist())
    second_denominators = {
        first: _logsumexp([log_worth[index] for index in all_indices if index != first])
        for first in all_indices
    }
    third_denominators = {
        (first, second): _logsumexp(
            [log_worth[index] for index in all_indices if index not in (first, second)]
        )
        for first in all_indices
        for second in all_indices
        if first != second
    }
    marginals = np.zeros((3, n_horses), dtype=float)
    for first, second, third in itertools.permutations(all_indices, 3):
        log_probability = (
            log_worth[first]
            - first_denominator
            + log_worth[second]
            - second_denominators[first]
            + log_worth[third]
            - third_denominators[(first, second)]
        )
        probability = math.exp(log_probability) if log_probability >= -745.0 else 0.0
        marginals[0, first] += probability
        marginals[1, second] += probability
        marginals[2, third] += probability
    return marginals


def pl_top3_marginals(scores: Sequence[Real], beta: Real = 1.0) -> np.ndarray:
    """Return each horse's PL probability of occupying one of slots 1--3."""

    if isinstance(scores, (str, bytes)):
        raise JejuPlaceProbabilityError("scores must be a finite numeric sequence")
    try:
        values = list(scores)
    except TypeError as exc:
        raise JejuPlaceProbabilityError("scores must be a finite numeric sequence") from exc
    if len(values) < 3:
        raise JejuPlaceProbabilityError("a race requires at least three scores")
    raw = _scores(values, len(values))
    slot_marginals = _pl_slot_marginals(raw, beta)
    return slot_marginals.sum(axis=0)


def _native_values(native_probabilities: Any, horse_ids: Sequence[Any]) -> np.ndarray:
    if isinstance(native_probabilities, Mapping):
        try:
            values = [native_probabilities[horse] for horse in horse_ids]
        except (KeyError, TypeError) as exc:
            raise JejuPlaceProbabilityError(
                "native_probabilities mapping must contain every horse ID"
            ) from exc
    else:
        if isinstance(native_probabilities, (str, bytes)):
            raise JejuPlaceProbabilityError("native_probabilities must be a numeric sequence")
        try:
            values = list(native_probabilities)
        except TypeError as exc:
            raise JejuPlaceProbabilityError(
                "native_probabilities must be a numeric sequence"
            ) from exc
    try:
        if any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
            raise JejuPlaceProbabilityError("native_probabilities must be finite probabilities")
        result = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise JejuPlaceProbabilityError(
            "native_probabilities must be finite probabilities"
        ) from exc
    if result.ndim != 1 or len(result) != len(horse_ids):
        raise JejuPlaceProbabilityError("native_probabilities must align with horse_ids")
    if not np.all(np.isfinite(result)) or np.any((result < 0) | (result > 1)):
        raise JejuPlaceProbabilityError("native_probabilities must lie in [0, 1]")
    return result


def _binary_metrics(probabilities: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    clipped = np.clip(probabilities, np.finfo(float).eps, 1.0 - np.finfo(float).eps)
    brier = float(np.mean((clipped - labels) ** 2))
    logloss = float(np.mean(-(labels * np.log(clipped) + (1.0 - labels) * np.log1p(-clipped))))
    return brier, logloss


def evaluate_place_race(
    horse_ids: Sequence[Any],
    scores: Sequence[Real],
    official_top3_ids: Sequence[Any],
    *,
    beta: Real = 1.0,
    native_probabilities: Sequence[Real] | Mapping[Any, Real] | None = None,
) -> dict[str, Any]:
    """Evaluate winner selection and per-entry official-place probabilities.

    ``official_top3_ids`` may contain four IDs for a documented third-place
    boundary tie.  Such a label has four positive entries; the caller can
    exclude that race from a strict three-slot probability aggregate while
    retaining this row for the single-horse hit metric.
    """

    ids = _ids(horse_ids)
    raw = _scores(scores, len(ids))
    beta_value = _beta(beta)
    if isinstance(official_top3_ids, (str, bytes)):
        raise JejuPlaceProbabilityError("official_top3_ids must be a sequence of IDs")
    try:
        official = list(official_top3_ids)
    except TypeError as exc:
        raise JejuPlaceProbabilityError("official_top3_ids must be a sequence of IDs") from exc
    if len(official) < 3:
        raise JejuPlaceProbabilityError("official_top3_ids must contain at least three IDs")
    id_keys = {_id_key(value) for value in ids}
    official_keys = [_id_key(value) for value in official]
    if len(set(official_keys)) != len(official_keys):
        raise JejuPlaceProbabilityError("official_top3_ids must be unique")
    if not set(official_keys).issubset(id_keys):
        raise JejuPlaceProbabilityError("official_top3_ids contains an unknown horse")

    slot_marginals = _pl_slot_marginals(raw, beta_value)
    pl_marginals_array = slot_marginals.sum(axis=0)
    maximum = float(np.max(raw))
    # Positive-beta PL is monotone in the raw score.  Use exact raw-score
    # equality for tie detection so a numerically saturated PL marginal does
    # not turn a genuinely higher score into a horse-ID tie-break.
    max_indices = [index for index, score in enumerate(raw) if float(score) == maximum]
    max_indices.sort(key=lambda index: _id_key(ids[index]))
    pick_index = max_indices[0]
    pick_horse_id = ids[pick_index]
    official_key_set = set(official_keys)
    labels = np.asarray([int(_id_key(horse) in official_key_set) for horse in ids], dtype=float)
    place_brier, place_logloss = _binary_metrics(pl_marginals_array, labels)
    native_brier = native_logloss = native_pick_probability = None
    if native_probabilities is not None:
        native = _native_values(native_probabilities, ids)
        native_brier, native_logloss = _binary_metrics(native, labels)
        native_pick_probability = float(native[pick_index])

    return {
        "pick_horse_id": pick_horse_id,
        "pick_hit": bool(_id_key(pick_horse_id) in official_key_set),
        "pick_probability": float(pl_marginals_array[pick_index]),
        "native_pick_probability": native_pick_probability,
        "tie_expected_pick_hit": float(
            sum(_id_key(ids[index]) in official_key_set for index in max_indices) / len(max_indices)
        ),
        "pl_marginals": [float(value) for value in pl_marginals_array],
        "official_labels": [int(value) for value in labels],
        "place_brier": place_brier,
        "place_logloss": place_logloss,
        "native_brier": native_brier,
        "native_logloss": native_logloss,
    }


__all__ = [
    "JejuPlaceProbabilityError",
    "evaluate_place_race",
    "pl_top3_marginals",
]

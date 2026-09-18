"""Evaluation contract for 제주 native top-three ordered triples.

The evaluator consumes raw, per-horse scores and turns them into one coherent
Plackett--Luce distribution over every distinct ordered triple in a race.  A
set probability is the sum of the six order probabilities for that set.  The
accepted orders supplied by the labels are authoritative, which means that a
dead heat is scored by summing the probability of all compatible orders.

This module is deliberately independent of model fitting and dataset I/O.  All
public results contain JSON-compatible values (lists and scalar values rather
than tuple or frozenset keys).
"""

from __future__ import annotations

import itertools
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from numbers import Real
from typing import Any

import numpy as np

DEFAULT_BOOTSTRAP_ITERATIONS = 5_000
DEFAULT_BOOTSTRAP_SEED = 17
_TIE_REL_TOL = 1e-12
_TIE_ABS_TOL = 1e-15


class JejuTop3EvaluationError(ValueError):
    """Raised when race labels or scores violate the top-three contract."""


def _id_key(value: Any) -> tuple[str, str]:
    """Return a deterministic, JSON-safe ordering key for a horse ID."""

    if isinstance(value, bool) or value is None:
        raise JejuTop3EvaluationError("horse IDs must be non-null strings or numbers")
    if not isinstance(value, (str, int, float)):
        raise JejuTop3EvaluationError("horse IDs must be JSON scalar strings or numbers")
    if isinstance(value, float) and not math.isfinite(value):
        raise JejuTop3EvaluationError("horse IDs must be finite")
    return (type(value).__name__, str(value))


def _validate_ids(horse_ids: Sequence[Any]) -> list[Any]:
    if isinstance(horse_ids, (str, bytes)):
        raise JejuTop3EvaluationError("horse_ids must be a sequence of individual IDs")
    try:
        values = list(horse_ids)
    except TypeError as exc:
        raise JejuTop3EvaluationError("horse_ids must be a sequence") from exc
    if len(values) < 3:
        raise JejuTop3EvaluationError("a race requires at least three horses")
    keys = [_id_key(value) for value in values]
    if len(set(keys)) != len(values):
        raise JejuTop3EvaluationError("horse_ids must be unique")
    return values


def _validate_scores(scores: Sequence[Any], expected: int) -> list[float]:
    if isinstance(scores, (str, bytes)):
        raise JejuTop3EvaluationError("scores must be a sequence aligned to horse_ids")
    try:
        values = list(scores)
    except TypeError as exc:
        raise JejuTop3EvaluationError("scores must be a sequence") from exc
    if len(values) != expected:
        raise JejuTop3EvaluationError("scores must have the same length as horse_ids")
    checked: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise JejuTop3EvaluationError("scores must be finite real numbers")
        number = float(value)
        if not math.isfinite(number):
            raise JejuTop3EvaluationError("scores must be finite real numbers")
        checked.append(number)
    return checked


def _validate_beta(beta: Any) -> float:
    if isinstance(beta, bool) or not isinstance(beta, Real):
        raise JejuTop3EvaluationError("beta must be a positive finite number")
    value = float(beta)
    if not math.isfinite(value) or value <= 0:
        raise JejuTop3EvaluationError("beta must be a positive finite number")
    return value


def _same_id(left: Any, right: Any) -> bool:
    return _id_key(left) == _id_key(right)


def _validate_accepted_orders(
    accepted_orders: Iterable[Sequence[Any]], horse_ids: Sequence[Any]
) -> tuple[list[tuple[Any, Any, Any]], set[tuple[tuple[str, str], ...]]]:
    if isinstance(accepted_orders, (str, bytes)):
        raise JejuTop3EvaluationError("accepted_orders must be an iterable of triples")
    horse_keys = {_id_key(value) for value in horse_ids}
    try:
        supplied = list(accepted_orders)
    except TypeError as exc:
        raise JejuTop3EvaluationError("accepted_orders must be an iterable of triples") from exc
    if not supplied:
        raise JejuTop3EvaluationError("accepted_orders must contain at least one triple")
    orders: list[tuple[Any, Any, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for order in supplied:
        if isinstance(order, (str, bytes)):
            raise JejuTop3EvaluationError("each accepted order must contain exactly three IDs")
        try:
            values = tuple(order)
        except TypeError as exc:
            raise JejuTop3EvaluationError(
                "each accepted order must contain exactly three IDs"
            ) from exc
        if len(values) != 3:
            raise JejuTop3EvaluationError("each accepted order must contain exactly three IDs")
        keys = tuple(_id_key(value) for value in values)
        if len(set(keys)) != 3:
            raise JejuTop3EvaluationError("accepted orders must contain three distinct IDs")
        if not set(keys).issubset(horse_keys):
            raise JejuTop3EvaluationError("accepted order contains a horse outside horse_ids")
        if keys in seen:
            raise JejuTop3EvaluationError("accepted_orders must not contain duplicates")
        seen.add(keys)
        orders.append(values)  # type: ignore[arg-type]
    return orders, seen


def _logsumexp(values: Iterable[float]) -> float:
    values_list = list(values)
    if not values_list:
        raise JejuTop3EvaluationError("logsumexp requires at least one value")
    maximum = max(values_list)
    return float(maximum + math.log(math.fsum(math.exp(value - maximum) for value in values_list)))


def _is_tie(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=_TIE_REL_TOL, abs_tol=_TIE_ABS_TOL)


def _json_order(order: Sequence[Any]) -> list[Any]:
    return list(order)


def evaluate_race(
    horse_ids: Sequence[Any],
    scores: Sequence[Real],
    accepted_orders: Iterable[Sequence[Any]],
    *,
    beta: Real = 1.0,
) -> dict[str, Any]:
    """Evaluate one race under a coherent Plackett--Luce top-three model.

    ``scores`` are aligned with ``horse_ids``.  ``beta`` is the inverse
    temperature: worth is ``exp(beta * score)``.  The main prediction first
    maximizes the set probability and then maximizes the order probability
    within that set.  Every tie is resolved by the stable horse-ID key.
    """

    ids = _validate_ids(horse_ids)
    raw_scores = _validate_scores(scores, len(ids))
    beta_value = _validate_beta(beta)
    _, accepted_keys = _validate_accepted_orders(accepted_orders, ids)
    id_to_score = {_id_key(horse): score for horse, score in zip(ids, raw_scores, strict=True)}
    ordered_ids = sorted(ids, key=_id_key)

    # A common score shift cancels in every PL ratio.  Work in log-worth space
    # and use logsumexp over the remaining horses so high score margins never
    # create a zero denominator through floating-point cancellation.
    scaled_scores = {key: beta_value * score for key, score in id_to_score.items()}
    if not all(math.isfinite(value) for value in scaled_scores.values()):
        raise JejuTop3EvaluationError("beta times score must remain finite")
    shift = max(scaled_scores.values())
    log_worth = {key: value - shift for key, value in scaled_scores.items()}
    by_key = {_id_key(horse): horse for horse in ids}
    all_keys = list(log_worth)
    first_log_denominator = _logsumexp(log_worth[key] for key in all_keys)
    second_log_denominators = {
        first: _logsumexp(log_worth[key] for key in all_keys if key != first) for first in all_keys
    }
    third_log_denominators = {
        (first, second): _logsumexp(
            log_worth[key] for key in all_keys if key not in {first, second}
        )
        for first in all_keys
        for second in all_keys
        if second != first
    }
    order_probabilities: dict[tuple[tuple[str, str], ...], tuple[tuple[Any, Any, Any], float]] = {}
    order_log_probabilities: dict[tuple[tuple[str, str], ...], float] = {}
    set_log_terms: dict[tuple[tuple[str, str], ...], list[float]] = defaultdict(list)
    set_accumulators: dict[tuple[tuple[str, str], ...], tuple[tuple[Any, Any, Any], float]] = {}
    for order in itertools.permutations(ordered_ids, 3):
        keys = tuple(_id_key(value) for value in order)
        first, second, third = keys
        log_probability = (
            log_worth[first]
            - first_log_denominator
            + log_worth[second]
            - second_log_denominators[first]
            + log_worth[third]
            - third_log_denominators[(first, second)]
        )
        probability = float(math.exp(log_probability)) if log_probability >= -745.0 else 0.0
        probability = float(probability)
        order_probabilities[keys] = (tuple(order), probability)
        order_log_probabilities[keys] = float(log_probability)
        set_key = tuple(sorted(keys))
        set_log_terms[set_key].append(float(log_probability))
        set_ids = tuple(by_key[key] for key in set_key)
        previous = set_accumulators.get(set_key)
        set_accumulators[set_key] = (
            set_ids,
            probability if previous is None else previous[1] + probability,
        )

    set_log_probabilities = {
        set_key: _logsumexp(log_terms) for set_key, log_terms in set_log_terms.items()
    }

    # Keep each accepted order's supplied value only for hit tests; key sets
    # avoid any dependence on source row order or ID object identity.
    accepted_set_keys = {tuple(sorted(keys[:])) for keys in accepted_keys}
    set_items = list(set_accumulators.items())
    max_set_log_probability = max(set_log_probabilities.values())
    max_set_items = [
        item
        for item in set_items
        if _is_tie(set_log_probabilities[item[0]], max_set_log_probability)
    ]
    max_set_items.sort(key=lambda item: tuple(_id_key(value) for value in item[1][0]))
    predicted_set = max_set_items[0][1][0]
    predicted_set_key = max_set_items[0][0]

    set_order_items = [
        item for key, item in order_probabilities.items() if tuple(sorted(key)) == predicted_set_key
    ]
    max_set_order_log_probability = max(
        order_log_probabilities[key]
        for key in order_probabilities
        if tuple(sorted(key)) == predicted_set_key
    )
    max_set_orders = [
        item
        for item in set_order_items
        if _is_tie(
            order_log_probabilities[tuple(_id_key(value) for value in item[0])],
            max_set_order_log_probability,
        )
    ]
    max_set_orders.sort(key=lambda item: tuple(_id_key(value) for value in item[0]))
    predicted_order, predicted_order_probability = max_set_orders[0]

    all_order_items = list(order_probabilities.values())
    max_order_log_probability = max(order_log_probabilities.values())
    max_orders = [
        item
        for item in all_order_items
        if _is_tie(
            order_log_probabilities[tuple(_id_key(value) for value in item[0])],
            max_order_log_probability,
        )
    ]
    max_orders.sort(key=lambda item: tuple(_id_key(value) for value in item[0]))
    global_order = max_orders[0][0]
    global_order_key = tuple(_id_key(value) for value in global_order)

    accepted_set_log_probability = _logsumexp(
        set_log_probabilities[key] for key in accepted_set_keys if key in set_log_probabilities
    )
    accepted_order_log_probability = _logsumexp(
        order_log_probabilities[key] for key in accepted_keys if key in order_log_probabilities
    )
    predicted_set_key = tuple(_id_key(value) for value in predicted_set)
    predicted_order_key = tuple(_id_key(value) for value in predicted_order)
    winner_keys = {key[0] for key in accepted_keys}
    predicted_set_key_set = set(predicted_set_key)
    compatible_overlap = max(
        len(predicted_set_key_set.intersection(set(key))) for key in accepted_set_keys
    )
    set_hit = predicted_set_key in accepted_set_keys
    order_hit = predicted_order_key in accepted_keys
    global_order_hit = global_order_key in accepted_keys
    set_max_keys = {key for key, _ in max_set_items}
    max_order_keys = {tuple(_id_key(value) for value in item[0]) for item in max_orders}
    max_tie_expected_set_hit = sum(key in accepted_set_keys for key in set_max_keys) / len(
        set_max_keys
    )
    max_tie_expected_order_hit = sum(key in accepted_keys for key in max_order_keys) / len(
        max_order_keys
    )
    order_given_set = bool(order_hit) if set_hit else None
    return {
        "n_horses": len(ids),
        "beta": float(beta_value),
        "set_hit": bool(set_hit),
        "order_hit": bool(order_hit),
        "order_given_set": order_given_set,
        "order_given_set_hit": order_given_set,
        "set_nll": float(-accepted_set_log_probability),
        "order_nll": float(-accepted_order_log_probability),
        "predicted_order": _json_order(predicted_order),
        "predicted_set": _json_order(predicted_set),
        "global_predicted_order": _json_order(global_order),
        "set_confidence": float(math.exp(max_set_log_probability))
        if max_set_log_probability >= -745.0
        else 0.0,
        "order_confidence": float(predicted_order_probability),
        "global_order_confidence": float(math.exp(max_order_log_probability))
        if max_order_log_probability >= -745.0
        else 0.0,
        "global_order_hit": bool(global_order_hit),
        "compatible_max_overlap": int(compatible_overlap),
        "top1_hit": bool(predicted_order_key[0] in winner_keys),
        "winner_in3": bool(predicted_set_key_set.intersection(winner_keys)),
        "max_tie_expected_set_hit": float(max_tie_expected_set_hit),
        "max_tie_expected_order_hit": float(max_tie_expected_order_hit),
        "expected_set_hit": float(max_tie_expected_set_hit),
        "expected_order_hit": float(max_tie_expected_order_hit),
        "order_probability_sum": float(sum(item[1] for item in all_order_items)),
        "set_probability_sum": float(sum(item[1] for item in set_accumulators.values())),
    }


def aggregate_race_metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate JSON race rows with race-equal weighting."""

    values = list(rows)
    if not values:
        raise JejuTop3EvaluationError("at least one race metric row is required")
    for row in values:
        if not isinstance(row, Mapping):
            raise JejuTop3EvaluationError("race metric rows must be mappings")

    def mean(name: str) -> float:
        observed = [float(row[name]) for row in values if row.get(name) is not None]
        return float(sum(observed) / len(observed)) if observed else float("nan")

    set_hits = [bool(row["set_hit"]) for row in values]
    order_hits = [bool(row["order_hit"]) for row in values]
    set_success_order = [bool(row["order_hit"]) for row in values if row.get("set_hit")]
    result = {
        "races": len(values),
        "set_hit_rate": float(sum(set_hits) / len(values)),
        "order_hit_rate": float(sum(order_hits) / len(values)),
        "order_accuracy_given_set": (
            float(sum(set_success_order) / len(set_success_order)) if set_success_order else None
        ),
        "set_nll": mean("set_nll"),
        "order_nll": mean("order_nll"),
        "global_order_hit_rate": float(
            sum(bool(row["global_order_hit"]) for row in values) / len(values)
        ),
        "top1_hit_rate": float(sum(bool(row["top1_hit"]) for row in values) / len(values)),
        "winner_in3_rate": float(sum(bool(row["winner_in3"]) for row in values) / len(values)),
        "compatible_max_overlap": mean("compatible_max_overlap"),
        "max_tie_expected_set_hit": mean("max_tie_expected_set_hit"),
        "max_tie_expected_order_hit": mean("max_tie_expected_order_hit"),
    }
    # JSON has no NaN value in strict mode.  Missing NLL is only possible for
    # an explicitly malformed caller row, so expose it as null instead.
    for key, value in list(result.items()):
        if isinstance(value, float) and math.isnan(value):
            result[key] = None
    return result


def _extract_delta(
    row: Mapping[str, Any], metric: str | None, candidate_key: str, reference_key: str
) -> float:
    if "delta" in row:
        value = row["delta"]
    elif metric is not None and candidate_key in row and reference_key in row:
        candidate = row[candidate_key]
        reference = row[reference_key]
        if isinstance(candidate, Mapping):
            candidate = candidate.get(metric)
        if isinstance(reference, Mapping):
            reference = reference.get(metric)
        if candidate is None or reference is None:
            raise JejuTop3EvaluationError(f"metric {metric!r} missing in paired row")
        value = float(candidate) - float(reference)
    elif metric is not None and f"candidate_{metric}" in row and f"reference_{metric}" in row:
        value = float(row[f"candidate_{metric}"]) - float(row[f"reference_{metric}"])
    else:
        raise JejuTop3EvaluationError(
            "paired rows need delta, candidate/reference values, or "
            "candidate_<metric>/reference_<metric>"
        )
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise JejuTop3EvaluationError("paired deltas must be finite real numbers")
    return float(value)


def _bootstrap_summary(
    deltas: np.ndarray,
    samples: np.ndarray,
    *,
    unit: str,
    iterations: int,
    seed: int,
    blocks: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "unit": unit,
        "n": int(len(deltas)),
        "iterations": int(iterations),
        "seed": int(seed),
        "observed_mean": float(deltas.mean()),
        "percentile_95_ci": [
            float(np.quantile(samples, 0.025)),
            float(np.quantile(samples, 0.975)),
        ],
        "ci_lower": float(np.quantile(samples, 0.025)),
        "ci_upper": float(np.quantile(samples, 0.975)),
        "fraction_bootstrap_deltas_below_zero": float(np.mean(samples < 0.0)),
    }
    if blocks is not None:
        result["blocks"] = int(blocks)
    return result


def paired_race_bootstrap(
    metric_rows: Iterable[Mapping[str, Any]],
    *,
    metric: str | None = None,
    candidate_key: str = "candidate",
    reference_key: str = "reference",
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Paired race bootstrap over a list of metric rows."""

    rows = list(metric_rows)
    if not rows:
        raise JejuTop3EvaluationError("at least one paired race row is required")
    if iterations <= 0:
        raise JejuTop3EvaluationError("iterations must be positive")
    deltas = np.asarray(
        [_extract_delta(row, metric, candidate_key, reference_key) for row in rows],
        dtype=np.float64,
    )
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations, dtype=np.float64)
    for index in range(iterations):
        samples[index] = float(rng.choice(deltas, size=len(deltas), replace=True).mean())
    return _bootstrap_summary(deltas, samples, unit="race", iterations=iterations, seed=seed)


def paired_day_cluster_bootstrap(
    metric_rows: Iterable[Mapping[str, Any]],
    *,
    metric: str | None = None,
    candidate_key: str = "candidate",
    reference_key: str = "reference",
    day_key: str | None = None,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Paired bootstrap sampling whole race-day clusters together."""

    rows = list(metric_rows)
    if not rows:
        raise JejuTop3EvaluationError("at least one paired race row is required")
    if iterations <= 0:
        raise JejuTop3EvaluationError("iterations must be positive")
    possible_keys = (day_key,) if day_key else ("race_date", "event_date", "date", "day")
    chosen_key = next(
        (key for key in possible_keys if key and all(key in row for row in rows)), None
    )
    if chosen_key is None:
        raise JejuTop3EvaluationError("day-cluster rows need a common race_date or event_date key")
    grouped: dict[Any, list[float]] = defaultdict(list)
    for row in rows:
        grouped[row[chosen_key]].append(_extract_delta(row, metric, candidate_key, reference_key))
    blocks = list(grouped.values())
    deltas = np.asarray([value for block in blocks for value in block], dtype=np.float64)
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations, dtype=np.float64)
    for index in range(iterations):
        choices = rng.integers(0, len(blocks), size=len(blocks))
        samples[index] = float(np.concatenate([blocks[item] for item in choices]).mean())
    return _bootstrap_summary(
        deltas,
        samples,
        unit="race_date_cluster",
        iterations=iterations,
        seed=seed,
        blocks=len(blocks),
    )


def paired_bootstrap(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Alias for the race-level paired bootstrap."""

    return paired_race_bootstrap(*args, **kwargs)


def paired_date_cluster_bootstrap(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Alias for the race-day cluster paired bootstrap."""

    return paired_day_cluster_bootstrap(*args, **kwargs)


__all__ = [
    "DEFAULT_BOOTSTRAP_ITERATIONS",
    "DEFAULT_BOOTSTRAP_SEED",
    "JejuTop3EvaluationError",
    "aggregate_race_metrics",
    "evaluate_race",
    "paired_bootstrap",
    "paired_date_cluster_bootstrap",
    "paired_day_cluster_bootstrap",
    "paired_race_bootstrap",
]

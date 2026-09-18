"""Factorized set/order evaluation for Jeju native top-three predictions.

The model is a coherent distribution over top-three sets and their orders:

``P(order) = P(set) * P(order | set)``

``P(set)`` is a softmax over the sum of per-horse inclusion scores, while the
conditional order distribution is a three-slot Plackett--Luce model built from
separate order scores.  The implementation enumerates all three-subsets and
permutations in log space and returns JSON-compatible scalars/lists.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from numbers import Real
from typing import Any

_TIE_REL_TOL = 1e-12
_TIE_ABS_TOL = 1e-15


class JejuJointEvaluationError(ValueError):
    """Raised when joint evaluator inputs violate the race contract."""


def _id_key(value: Any) -> tuple[str, str]:
    if value is None or isinstance(value, bool):
        raise JejuJointEvaluationError("horse IDs must be non-null strings or numbers")
    if not isinstance(value, (str, int, float)):
        raise JejuJointEvaluationError("horse IDs must be JSON scalar strings or numbers")
    if isinstance(value, float) and not math.isfinite(value):
        raise JejuJointEvaluationError("horse IDs must be finite")
    return type(value).__name__, str(value)


def _validate_ids(horse_ids: Sequence[Any]) -> list[Any]:
    if isinstance(horse_ids, (str, bytes)):
        raise JejuJointEvaluationError("horse_ids must be a sequence of IDs")
    try:
        values = list(horse_ids)
    except TypeError as exc:
        raise JejuJointEvaluationError("horse_ids must be a sequence of IDs") from exc
    if len(values) < 3:
        raise JejuJointEvaluationError("a race requires at least three horses")
    keys = [_id_key(value) for value in values]
    if len(set(keys)) != len(keys):
        raise JejuJointEvaluationError("horse_ids must be unique")
    return values


def _validate_scores(scores: Sequence[Any], size: int, label: str) -> list[float]:
    if isinstance(scores, (str, bytes)):
        raise JejuJointEvaluationError(f"{label} must align with horse_ids")
    try:
        values = list(scores)
    except TypeError as exc:
        raise JejuJointEvaluationError(f"{label} must align with horse_ids") from exc
    if len(values) != size:
        raise JejuJointEvaluationError(f"{label} must have the same length as horse_ids")
    checked: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise JejuJointEvaluationError(f"{label} must be finite real numbers")
        number = float(value)
        if not math.isfinite(number):
            raise JejuJointEvaluationError(f"{label} must be finite real numbers")
        checked.append(number)
    return checked


def _validate_beta(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise JejuJointEvaluationError(f"{label} must be a positive finite number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise JejuJointEvaluationError(f"{label} must be a positive finite number")
    return number


def _logsumexp(values: Iterable[float]) -> float:
    values_list = list(values)
    if not values_list:
        raise JejuJointEvaluationError("logsumexp requires at least one value")
    maximum = max(values_list)
    return float(maximum + math.log(math.fsum(math.exp(value - maximum) for value in values_list)))


def _is_tie(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=_TIE_REL_TOL, abs_tol=_TIE_ABS_TOL)


def _validate_accepted_orders(
    accepted_orders: Iterable[Sequence[Any]], horse_ids: Sequence[Any]
) -> tuple[list[tuple[Any, Any, Any]], set[tuple[tuple[str, str], ...]]]:
    if isinstance(accepted_orders, (str, bytes)):
        raise JejuJointEvaluationError("accepted_orders must be an iterable of triples")
    try:
        supplied = list(accepted_orders)
    except TypeError as exc:
        raise JejuJointEvaluationError("accepted_orders must be an iterable of triples") from exc
    if not supplied:
        raise JejuJointEvaluationError("accepted_orders must contain at least one triple")
    horse_keys = {_id_key(value) for value in horse_ids}
    orders: list[tuple[Any, Any, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for order in supplied:
        if isinstance(order, (str, bytes)):
            raise JejuJointEvaluationError("each accepted order must contain exactly three IDs")
        try:
            values = tuple(order)
        except TypeError as exc:
            raise JejuJointEvaluationError(
                "each accepted order must contain exactly three IDs"
            ) from exc
        if len(values) != 3:
            raise JejuJointEvaluationError("each accepted order must contain exactly three IDs")
        keys = tuple(_id_key(value) for value in values)
        if len(set(keys)) != 3:
            raise JejuJointEvaluationError("accepted orders must contain three distinct IDs")
        if not set(keys).issubset(horse_keys):
            raise JejuJointEvaluationError("accepted order contains a horse outside horse_ids")
        if keys in seen:
            raise JejuJointEvaluationError("accepted_orders must not contain duplicates")
        seen.add(keys)
        orders.append(values)  # type: ignore[arg-type]
    return orders, seen


def _validate_official_top3(
    official_top3_ids: Sequence[Any], horse_ids: Sequence[Any]
) -> set[tuple[str, str]]:
    if isinstance(official_top3_ids, (str, bytes)):
        raise JejuJointEvaluationError("official_top3_ids must be a sequence of IDs")
    try:
        values = list(official_top3_ids)
    except TypeError as exc:
        raise JejuJointEvaluationError("official_top3_ids must be a sequence of IDs") from exc
    if len(values) < 3:
        raise JejuJointEvaluationError("official_top3_ids must contain at least three IDs")
    keys = [_id_key(value) for value in values]
    horse_keys = {_id_key(value) for value in horse_ids}
    if len(set(keys)) != len(keys):
        raise JejuJointEvaluationError("official_top3_ids must be unique")
    if not set(keys).issubset(horse_keys):
        raise JejuJointEvaluationError("official_top3_ids contains an unknown horse")
    return set(keys)


def _json_order(order: Sequence[Any]) -> list[Any]:
    return list(order)


def _binary_metrics(probabilities: Sequence[float], labels: Sequence[int]) -> tuple[float, float]:
    epsilon = 1e-15
    brier_terms = []
    logloss_terms = []
    for probability, label in zip(probabilities, labels, strict=True):
        clipped = min(max(float(probability), epsilon), 1.0 - epsilon)
        brier_terms.append((clipped - int(label)) ** 2)
        logloss_terms.append(
            -(int(label) * math.log(clipped) + (1 - int(label)) * math.log1p(-clipped))
        )
    return float(math.fsum(brier_terms) / len(brier_terms)), float(
        math.fsum(logloss_terms) / len(logloss_terms)
    )


def evaluate_joint_race(
    horse_ids: Sequence[Any],
    inclusion_scores: Sequence[Real],
    order_scores: Sequence[Real],
    accepted_orders: Iterable[Sequence[Any]],
    official_top3_ids: Sequence[Any],
    *,
    beta_set: Real = 1.0,
    beta_order: Real = 1.0,
) -> dict[str, Any]:
    """Evaluate a factorized set/order distribution for one race.

    ``pl_marginals`` is retained for compatibility with the PL evaluator, but
    it is the joint model's inclusion probability for each supplied horse.
    It is aligned to the caller's ``horse_ids`` order and sums to three.
    Prediction is MAP set first, MAP conditional order within that set, and a
    single pick is the highest joint inclusion marginal with stable ID tie-break.
    """

    ids = _validate_ids(horse_ids)
    n_horses = len(ids)
    inclusion = _validate_scores(inclusion_scores, n_horses, "inclusion_scores")
    ordering = _validate_scores(order_scores, n_horses, "order_scores")
    set_beta = _validate_beta(beta_set, "beta_set")
    order_beta = _validate_beta(beta_order, "beta_order")
    _, accepted_keys = _validate_accepted_orders(accepted_orders, ids)
    official_keys = _validate_official_top3(official_top3_ids, ids)

    by_key = {_id_key(horse): horse for horse in ids}
    inclusion_by_key = {
        _id_key(horse): set_beta * score for horse, score in zip(ids, inclusion, strict=True)
    }
    ordering_by_key = {
        _id_key(horse): order_beta * score for horse, score in zip(ids, ordering, strict=True)
    }
    if not all(math.isfinite(value) for value in inclusion_by_key.values()):
        raise JejuJointEvaluationError("beta_set times inclusion_scores must remain finite")
    if not all(math.isfinite(value) for value in ordering_by_key.values()):
        raise JejuJointEvaluationError("beta_order times order_scores must remain finite")

    ordered_keys = sorted(by_key, key=lambda key: key)
    set_keys = list(itertools.combinations(ordered_keys, 3))
    unnormalized_set_logs = {
        set_key: math.fsum(inclusion_by_key[key] for key in set_key) for set_key in set_keys
    }
    set_shift = max(unnormalized_set_logs.values())
    set_normalizer = _logsumexp(
        value - set_shift for value in unnormalized_set_logs.values()
    )
    set_log_probabilities = {
        set_key: value - set_shift - set_normalizer
        for set_key, value in unnormalized_set_logs.items()
    }

    set_order_log_probabilities: dict[tuple[tuple[str, str], ...], float] = {}
    set_order_probabilities: dict[tuple[tuple[str, str], ...], float] = {}
    order_conditional_logs: dict[tuple[tuple[str, str], ...], float] = {}
    marginals_by_key = {key: 0.0 for key in ordered_keys}
    for set_key in set_keys:
        set_log_probability = set_log_probabilities[set_key]
        for order in itertools.permutations(set_key):
            first, second, third = order
            first_denominator = _logsumexp(ordering_by_key[key] for key in set_key)
            second_denominator = _logsumexp(
                ordering_by_key[key] for key in set_key if key != first
            )
            conditional_log_probability = (
                ordering_by_key[first]
                - first_denominator
                + ordering_by_key[second]
                - second_denominator
            )
            order_key = tuple(order)
            joint_log_probability = set_log_probability + conditional_log_probability
            order_conditional_logs[order_key] = float(conditional_log_probability)
            set_order_log_probabilities[order_key] = float(joint_log_probability)
            probability = (
                math.exp(joint_log_probability) if joint_log_probability >= -745.0 else 0.0
            )
            set_order_probabilities[order_key] = float(probability)
            for key in set_key:
                marginals_by_key[key] += probability

    # MAP set, then MAP conditional order within that set.  Stable ID ordering
    # makes ties independent of source row order.
    max_set_log = max(set_log_probabilities.values())
    max_set_keys = [
        key for key in set_keys if _is_tie(set_log_probabilities[key], max_set_log)
    ]
    max_set_keys.sort()
    predicted_set_key = max_set_keys[0]
    predicted_set = tuple(by_key[key] for key in predicted_set_key)

    candidate_orders = [
        key for key in set_order_log_probabilities if tuple(sorted(key)) == predicted_set_key
    ]
    max_conditional_log = max(order_conditional_logs[key] for key in candidate_orders)
    max_conditional_orders = [
        key for key in candidate_orders if _is_tie(order_conditional_logs[key], max_conditional_log)
    ]
    max_conditional_orders.sort()
    predicted_order_key = max_conditional_orders[0]
    predicted_order = tuple(by_key[key] for key in predicted_order_key)

    max_global_log = max(set_order_log_probabilities.values())
    max_global_orders = [
        key for key, value in set_order_log_probabilities.items() if _is_tie(value, max_global_log)
    ]
    max_global_orders.sort()
    global_order_key = max_global_orders[0]
    global_order = tuple(by_key[key] for key in global_order_key)

    accepted_set_keys = {tuple(sorted(key)) for key in accepted_keys}
    accepted_set_log_probability = _logsumexp(
        set_log_probabilities[key] for key in accepted_set_keys
    )
    accepted_order_log_probability = _logsumexp(
        set_order_log_probabilities[key] for key in accepted_keys
    )
    predicted_set_as_keys = tuple(_id_key(value) for value in predicted_set)
    predicted_order_as_keys = tuple(_id_key(value) for value in predicted_order)
    global_order_as_keys = tuple(_id_key(value) for value in global_order)
    set_hit = predicted_set_as_keys in accepted_set_keys
    order_hit = predicted_order_as_keys in accepted_keys
    global_order_hit = global_order_as_keys in accepted_keys
    winner_keys = {key[0] for key in accepted_keys}
    max_tie_expected_set_hit = sum(key in accepted_set_keys for key in max_set_keys) / len(
        max_set_keys
    )
    max_tie_expected_order_hit = sum(key in accepted_keys for key in max_global_orders) / len(
        max_global_orders
    )

    max_marginal = max(marginals_by_key.values())
    max_marginal_keys = [
        key for key in ordered_keys if _is_tie(marginals_by_key[key], max_marginal)
    ]
    max_marginal_keys.sort()
    pick_key = max_marginal_keys[0]
    pick_horse_id = by_key[pick_key]
    labels = [int(key in official_keys) for key in map(_id_key, ids)]
    marginals = [float(marginals_by_key[_id_key(horse)]) for horse in ids]
    place_brier, place_logloss = _binary_metrics(marginals, labels)
    order_confidence = set_order_probabilities[predicted_order_key]
    set_confidence = math.exp(set_log_probabilities[predicted_set_key])
    global_order_confidence = math.exp(max_global_log)
    probability_sums = {
        "set": float(math.fsum(math.exp(value) for value in set_log_probabilities.values())),
        "order": float(math.fsum(set_order_probabilities.values())),
        "marginal": float(math.fsum(marginals)),
    }
    return {
        "n_horses": n_horses,
        "beta_set": float(set_beta),
        "beta_order": float(order_beta),
        "set_hit": bool(set_hit),
        "order_hit": bool(order_hit),
        "order_given_set": bool(order_hit) if set_hit else None,
        "order_given_set_hit": bool(order_hit) if set_hit else None,
        "set_nll": float(-accepted_set_log_probability),
        "order_nll": float(-accepted_order_log_probability),
        "predicted_order": _json_order(predicted_order),
        "predicted_set": _json_order(predicted_set),
        "global_predicted_order": _json_order(global_order),
        "set_confidence": float(set_confidence),
        "order_confidence": float(order_confidence),
        "global_order_confidence": float(global_order_confidence),
        "global_order_hit": bool(global_order_hit),
        "compatible_max_overlap": int(
            max(len(set(predicted_set_as_keys).intersection(set(key))) for key in accepted_set_keys)
        ),
        "top1_hit": bool(predicted_order_as_keys[0] in winner_keys),
        "winner_in3": bool(set(predicted_set_as_keys).intersection(winner_keys)),
        "max_tie_expected_set_hit": float(max_tie_expected_set_hit),
        "max_tie_expected_order_hit": float(max_tie_expected_order_hit),
        "expected_set_hit": float(max_tie_expected_set_hit),
        "expected_order_hit": float(max_tie_expected_order_hit),
        "order_probability_sum": probability_sums["order"],
        "set_probability_sum": probability_sums["set"],
        "probability_sums": probability_sums,
        "pick_horse_id": pick_horse_id,
        "pick_hit": bool(pick_key in official_keys),
        "pick_probability": float(marginals_by_key[pick_key]),
        "place_probability": float(marginals_by_key[pick_key]),
        "tie_expected_pick_hit": float(
            sum(key in official_keys for key in max_marginal_keys) / len(max_marginal_keys)
        ),
        "pl_marginals": marginals,
        "official_labels": labels,
        "place_brier": float(place_brier),
        "place_logloss": float(place_logloss),
    }


__all__ = ["JejuJointEvaluationError", "evaluate_joint_race"]

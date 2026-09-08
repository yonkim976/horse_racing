"""Full top-three Plackett--Luce probabilities and calibration.

The ranker supplies one latent ability score per runner.  This module turns those
scores into a coherent distribution over ordered top-three outcomes, including
official dead-heats at the calibration/evaluation boundary.
"""

from __future__ import annotations

from itertools import permutations
from typing import Any

import numpy as np

PROBABILITY_EPSILON = 1e-15


def _race_groups(race_ids: np.ndarray) -> list[np.ndarray]:
    groups: dict[Any, list[int]] = {}
    for index, race_id in enumerate(np.asarray(race_ids)):
        key = race_id.item() if hasattr(race_id, "item") else race_id
        groups.setdefault(key, []).append(index)
    return [np.asarray(indices, dtype=int) for indices in groups.values()]


def _worths(scores: np.ndarray, beta: float) -> np.ndarray:
    logits = np.clip(np.asarray(scores, dtype=float) * beta, -50.0, 50.0)
    return np.exp(logits - logits.max())


def ordered_top3_probabilities(
    scores: np.ndarray,
    *,
    beta: float,
) -> dict[tuple[int, int, int], float]:
    """Return probabilities for every ordered top-three tuple in one race."""
    scores = np.asarray(scores, dtype=float)
    if scores.ndim != 1:
        raise ValueError("scores는 1차원이어야 합니다.")
    if len(scores) < 3:
        return {}
    worth = _worths(scores, beta)
    total = float(worth.sum())
    output: dict[tuple[int, int, int], float] = {}
    for first in range(len(scores)):
        remaining_after_first = float(worth[np.arange(len(scores)) != first].sum())
        p_first = float(worth[first]) / total
        for second in range(len(scores)):
            if second == first:
                continue
            remaining_after_second = float(
                worth[(np.arange(len(scores)) != first) & (np.arange(len(scores)) != second)].sum()
            )
            p_first_second = p_first * float(worth[second]) / remaining_after_first
            for third in range(len(scores)):
                if third == first or third == second:
                    continue
                output[(first, second, third)] = (
                    p_first_second * float(worth[third]) / remaining_after_second
                )
    return output


def plackett_luce_marginals(
    scores: np.ndarray,
    race_ids: np.ndarray,
    *,
    beta: float,
) -> dict[str, np.ndarray]:
    """Compute coherent first/second/third and cumulative top-k probabilities."""
    return plackett_luce_rank_marginals(scores, race_ids, beta=beta, max_rank=3)


def _position_marginals(worth: np.ndarray, max_rank: int) -> np.ndarray:
    """Subset-DP PL position marginals for one race.

    Prefixes that contain the same selected set have the same remaining
    denominator, so they can be aggregated into one bit-mask state.  This is
    substantially cheaper than enumerating every ordered top-five tuple.
    """
    runners = len(worth)
    depth = min(max_rank, runners)
    exact = np.zeros((max_rank, runners), dtype=float)
    states: dict[int, float] = {0: 1.0}
    full_mask = (1 << runners) - 1
    for rank in range(depth):
        next_probability: dict[int, float] = {}
        for mask, prefix_probability in states.items():
            remaining = full_mask ^ mask
            remaining_indices = [
                runner for runner in range(runners) if remaining & (1 << runner)
            ]
            denominator = float(worth[remaining_indices].sum())
            while remaining:
                bit = remaining & -remaining
                runner = bit.bit_length() - 1
                probability = prefix_probability * float(worth[runner]) / denominator
                exact[rank, runner] += probability
                if rank + 1 < depth:
                    next_mask = mask | bit
                    next_probability[next_mask] = next_probability.get(next_mask, 0.0) + probability
                remaining ^= bit
        states = next_probability
    return exact


def plackett_luce_rank_marginals(
    scores: np.ndarray,
    race_ids: np.ndarray,
    *,
    beta: float,
    max_rank: int = 5,
) -> dict[str, np.ndarray]:
    """Return exact-rank and cumulative top-k marginals through ``max_rank``."""
    scores = np.asarray(scores, dtype=float)
    race_ids = np.asarray(race_ids)
    if len(scores) != len(race_ids):
        raise ValueError("rank score와 race_id 길이가 다릅니다.")
    if max_rank < 1:
        raise ValueError("max_rank는 1 이상이어야 합니다.")
    exact = np.zeros((max_rank, len(scores)), dtype=float)
    for locations in _race_groups(race_ids):
        exact[:, locations] = _position_marginals(_worths(scores[locations], beta), max_rank)
    output = {f"prob_rank{rank}": exact[rank - 1] for rank in range(1, max_rank + 1)}
    aliases = ("win", "second", "third", "fourth", "fifth")
    for rank, alias in enumerate(aliases[:max_rank], start=1):
        output[f"prob_{alias}"] = exact[rank - 1]
    cumulative = np.cumsum(exact, axis=0)
    for rank in range(2, max_rank + 1):
        output[f"prob_top{rank}"] = cumulative[rank - 1]
    return output


def valid_ordered_top3_indices(finish_positions: np.ndarray) -> set[tuple[int, int, int]]:
    """Enumerate official top-three orders, marginalizing dead-heats.

    A dead-heat group wholly inside the top three is freely permuted.  If it
    crosses the third-place boundary, every ordered selection that fills the
    remaining slots is accepted.
    """
    return {
        tuple(order)  # type: ignore[misc]
        for order in valid_ordered_topk_indices(finish_positions, max_rank=3)
    }


def valid_ordered_topk_indices(
    finish_positions: np.ndarray,
    *,
    max_rank: int,
) -> set[tuple[int, ...]]:
    """Enumerate official ordered top-k outcomes, marginalizing dead-heats."""
    if max_rank < 1:
        raise ValueError("max_rank는 1 이상이어야 합니다.")
    grouped: dict[int, list[int]] = {}
    for index, raw_position in enumerate(np.asarray(finish_positions)):
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        if position > 0:
            grouped.setdefault(position, []).append(index)

    prefixes: set[tuple[int, ...]] = {()}
    for position in sorted(grouped):
        if not prefixes:
            break
        prefix_length = len(next(iter(prefixes)))
        if prefix_length >= max_rank:
            break
        group = grouped[position]
        slots = max_rank - prefix_length
        take = min(slots, len(group))
        next_prefixes: set[tuple[int, ...]] = set()
        for prefix in prefixes:
            for ordered_group in permutations(group, take):
                next_prefixes.add((*prefix, *ordered_group))
        prefixes = next_prefixes
        if take < len(group):
            break
    return {tuple(prefix) for prefix in prefixes if len(prefix) == max_rank}


def plackett_luce_top3_nll(
    scores: np.ndarray,
    race_ids: np.ndarray,
    finish_positions: np.ndarray,
    *,
    beta: float,
) -> float:
    """Mean race-level negative log likelihood of the observed ordered top three."""
    return plackett_luce_topk_nll(
        scores,
        race_ids,
        finish_positions,
        beta=beta,
        max_rank=3,
    )


def plackett_luce_topk_nll(
    scores: np.ndarray,
    race_ids: np.ndarray,
    finish_positions: np.ndarray,
    *,
    beta: float,
    max_rank: int,
) -> float:
    """Mean race-level NLL of the observed ordered top-k finish."""
    scores = np.asarray(scores, dtype=float)
    race_ids = np.asarray(race_ids)
    finish_positions = np.asarray(finish_positions)
    if not (len(scores) == len(race_ids) == len(finish_positions)):
        raise ValueError("scores, race_ids, finish_positions 길이가 다릅니다.")
    losses: list[float] = []
    for locations in _race_groups(race_ids):
        depth = min(max_rank, len(locations))
        valid_orders = valid_ordered_topk_indices(
            finish_positions[locations], max_rank=depth
        )
        if not valid_orders:
            continue
        worth = _worths(scores[locations], beta)
        observed_probability = 0.0
        for order in valid_orders:
            probability = 1.0
            remaining = np.ones(len(worth), dtype=bool)
            for runner in order:
                denominator = float(worth[remaining].sum())
                probability *= float(worth[runner]) / denominator
                remaining[runner] = False
            observed_probability += probability
        losses.append(-float(np.log(max(observed_probability, PROBABILITY_EPSILON))))
    if not losses:
        raise ValueError(f"유효한 top{max_rank} 착순이 있는 경주가 없습니다.")
    return float(np.mean(losses))


def fit_plackett_luce_beta(
    scores: np.ndarray,
    race_ids: np.ndarray,
    finish_positions: np.ndarray,
) -> float:
    """Select score temperature using ordered top-three race likelihood."""
    return fit_plackett_luce_beta_topk(
        scores,
        race_ids,
        finish_positions,
        max_rank=3,
    )


def fit_plackett_luce_beta_topk(
    scores: np.ndarray,
    race_ids: np.ndarray,
    finish_positions: np.ndarray,
    *,
    max_rank: int,
) -> float:
    """Select score temperature using ordered top-k race likelihood."""
    candidates = np.geomspace(0.03, 30.0, 121)
    losses = np.asarray(
        [
            plackett_luce_topk_nll(
                scores,
                race_ids,
                finish_positions,
                beta=float(beta),
                max_rank=max_rank,
            )
            for beta in candidates
        ]
    )
    best_index = int(np.argmin(losses))
    if 0 < best_index < len(candidates) - 1:
        candidates = np.geomspace(candidates[best_index - 1], candidates[best_index + 1], 81)
        losses = np.asarray(
            [
                plackett_luce_topk_nll(
                    scores,
                    race_ids,
                    finish_positions,
                    beta=float(beta),
                    max_rank=max_rank,
                )
                for beta in candidates
            ]
        )
        best_index = int(np.argmin(losses))
    return float(candidates[best_index])

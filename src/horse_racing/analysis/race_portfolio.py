"""RacePortfolio V1: probability, dividend, and ticket-portfolio research.

Final dividends are targets and settlement values only.  They are never used as
pre-race model features.  The module is intentionally separate from RaceFit so
the ability model remains frozen while ticket selection is evaluated.
"""

from __future__ import annotations

import math
import pickle
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations, permutations
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression

SUPPORTED_POOLS = ("WIN", "PLC", "QPL", "EXA", "TLA")
ODDS_FEATURES = (
    "ticket_probability_calibrated",
    "log_ticket_probability",
    "selection_count",
    "model_rank_min",
    "model_rank_max",
    "model_rank_sum",
    "model_rank_gap",
    "selected_win_probability_min",
    "selected_win_probability_max",
    "selected_win_probability_mean",
    "field_size",
    "meet_code",
    "distance_m",
    "race_number",
    "race_top1_probability",
    "race_probability_gap12",
    "race_entropy",
)
FINAL_ODDS_SENTINEL = 9_999.9
PROBABILITY_EPSILON = 1e-6


class RacePortfolioInputError(ValueError):
    """Raised when ticket-model inputs violate the data contract."""


@dataclass
class PoolProbabilityModel:
    pool: str
    estimator: LogisticRegression

    def predict(self, values: np.ndarray) -> np.ndarray:
        matrix = _beta_features(values)
        return np.clip(
            self.estimator.predict_proba(matrix)[:, 1],
            PROBABILITY_EPSILON,
            1.0 - PROBABILITY_EPSILON,
        )


@dataclass
class PoolOddsModel:
    pool: str
    lower_quantile: float
    lower: lgb.LGBMRegressor
    median: lgb.LGBMRegressor


@dataclass
class RacePortfolioBundle:
    probability_models: dict[str, PoolProbabilityModel]
    odds_models: dict[str, PoolOddsModel]
    train_end: str
    feature_names: tuple[str, ...] = ODDS_FEATURES
    lower_quantile: float = 0.20
    model_name: str = "RacePortfolio V1"

    def predict(self, tickets: pl.DataFrame) -> pl.DataFrame:
        if tickets.height == 0:
            return tickets
        pieces: list[pl.DataFrame] = []
        for pool_key, group in tickets.partition_by("bet_type", as_dict=True).items():
            pool = str(pool_key[0])
            probability_model = self.probability_models.get(pool)
            odds_model = self.odds_models.get(pool)
            if probability_model is None or odds_model is None:
                continue
            calibrated = probability_model.predict(group["ticket_probability"].to_numpy())
            prepared = _with_odds_features(
                group.with_columns(
                    pl.Series("ticket_probability_calibrated", calibrated)
                )
            )
            matrix = prepared.select(self.feature_names).to_numpy()
            lower = np.exp(odds_model.lower.predict(matrix))
            median = np.exp(odds_model.median.predict(matrix))
            pieces.append(
                prepared.with_columns(
                    pl.Series("predicted_odds_lower", np.clip(lower, 1.0, 5_000.0)),
                    pl.Series("predicted_odds_median", np.clip(median, 1.0, 5_000.0)),
                ).with_columns(
                    (
                        pl.col("ticket_probability_calibrated")
                        * pl.col("predicted_odds_lower")
                    ).alias("conservative_return_multiplier"),
                    (
                        pl.col("ticket_probability_calibrated")
                        * pl.col("predicted_odds_median")
                    ).alias("median_return_multiplier"),
                )
            )
        if not pieces:
            return pl.DataFrame()
        return pl.concat(pieces, how="diagonal_relaxed").sort(
            "race_date_local", "race_id", "bet_type", "selection_key"
        )


@dataclass(frozen=True)
class PortfolioLine:
    bet_type: str
    selection_key: str
    stake_units: int
    ticket_probability: float
    predicted_odds_lower: float
    predicted_odds_median: float


@dataclass(frozen=True)
class PortfolioRecommendation:
    race_id: int
    lines: tuple[PortfolioLine, ...]
    stake_units: int
    probability_non_loss: float
    expected_return_lower: float
    expected_return_median: float
    reason: str


@dataclass(frozen=True)
class PortfolioBacktest:
    races_available: int
    races_bet: int
    tickets_bet: int
    profitable_races: int
    hit_races: int
    stake_units: float
    returned_units: float
    roi: float
    profit_race_rate: float
    hit_race_rate: float
    max_drawdown_units: float
    max_consecutive_losing_races: int
    top_one_profit_removed_roi: float
    top_three_profit_removed_roi: float
    monthly: tuple[dict[str, Any], ...]
    selections: pl.DataFrame = field(repr=False)


@dataclass(frozen=True)
class FixedRankBacktest:
    bet_type: str
    model_ranks: tuple[int, ...]
    races: int
    hits: int
    hit_rate: float
    returned_units: float
    roi: float
    max_drawdown_units: float
    max_consecutive_losses: int
    top_one_profit_removed_roi: float
    top_three_profit_removed_roi: float


def _require_columns(frame: pl.DataFrame, required: Iterable[str], *, label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise RacePortfolioInputError(f"{label} 컬럼 없음: {', '.join(missing)}")


def _selection_key(numbers: Iterable[int], *, ordered: bool) -> str:
    values = tuple(int(value) for value in numbers)
    if not ordered:
        values = tuple(sorted(values))
    return "-".join(str(value) for value in values)


def _race_scenarios(group: pl.DataFrame) -> list[tuple[tuple[int, int, int], float]]:
    ordered = group.sort("horse_number")
    numbers = [int(value) for value in ordered["horse_number"].to_list()]
    worth = np.asarray(ordered["prob_win"].to_list(), dtype=float)
    if not np.all(np.isfinite(worth)) or np.any(worth < 0):
        raise RacePortfolioInputError("prob_win은 유한한 0 이상 값이어야 합니다.")
    total = float(worth.sum())
    if total <= 0 or len(numbers) < 3:
        raise RacePortfolioInputError("경주별 확률 합은 양수이고 출전마는 3두 이상이어야 합니다.")
    worth /= total
    output: list[tuple[tuple[int, int, int], float]] = []
    for first, second, third in permutations(range(len(numbers)), 3):
        remaining_after_first = 1.0 - worth[first]
        remaining_after_second = remaining_after_first - worth[second]
        if remaining_after_second <= 0:
            continue
        probability = (
            worth[first]
            * worth[second]
            / remaining_after_first
            * worth[third]
            / remaining_after_second
        )
        output.append(
            ((numbers[first], numbers[second], numbers[third]), float(probability))
        )
    return output


def _actual_winner_sets(
    context: pl.DataFrame,
    *,
    place_slots: int,
) -> dict[str, set[str]]:
    if "finish_position" not in context.columns:
        return {pool: set() for pool in SUPPORTED_POOLS}
    clean = context.filter(
        pl.col("finish_position").is_not_null()
        & (pl.col("finish_position") > 0)
        & (pl.col("finish_position") < 90)
    )
    if clean.height < 3:
        return {pool: set() for pool in SUPPORTED_POOLS}
    by_position: dict[int, list[int]] = {}
    for row in clean.select("horse_number", "finish_position").iter_rows(named=True):
        by_position.setdefault(int(row["finish_position"]), []).append(
            int(row["horse_number"])
        )
    first = sorted(by_position.get(1, []))
    place = sorted(
        int(row["horse_number"])
        for row in clean.filter(pl.col("finish_position") <= place_slots).iter_rows(
            named=True
        )
    )
    ordered_finish = [
        int(row["horse_number"])
        for row in clean.sort("finish_position", "horse_number").iter_rows(named=True)
    ]
    winners = {
        "WIN": {_selection_key([number], ordered=True) for number in first},
        "PLC": {_selection_key([number], ordered=True) for number in place},
        "QPL": {
            _selection_key(pair, ordered=False) for pair in combinations(place, 2)
        },
        "EXA": set(),
        "TLA": set(),
    }
    if len(by_position.get(1, [])) == 1 and len(by_position.get(2, [])) == 1:
        winners["EXA"].add(
            _selection_key(
                [by_position[1][0], by_position[2][0]],
                ordered=True,
            )
        )
    if len(ordered_finish) >= 3:
        third_cutoff = int(clean.sort("finish_position")["finish_position"][2])
        top_at_cutoff = sorted(
            int(row["horse_number"])
            for row in clean.filter(pl.col("finish_position") <= third_cutoff).iter_rows(
                named=True
            )
        )
        for triple in combinations(top_at_cutoff, 3):
            winners["TLA"].add(_selection_key(triple, ordered=False))
    return winners


def _ticket_feature_row(
    *,
    race: dict[str, Any],
    bet_type: str,
    numbers: tuple[int, ...],
    probability: float,
    ranks: dict[int, int],
    win_probabilities: dict[int, float],
    winner_keys: dict[str, set[str]],
    has_labels: bool,
) -> dict[str, Any]:
    ordered = bet_type == "EXA"
    key = _selection_key(numbers, ordered=ordered)
    selected_ranks = [ranks[number] for number in numbers]
    selected_win = [win_probabilities[number] for number in numbers]
    return {
        **race,
        "bet_type": bet_type,
        "selection_key": key,
        "selection_count": len(numbers),
        "ticket_probability": float(probability),
        "model_rank_min": min(selected_ranks),
        "model_rank_max": max(selected_ranks),
        "model_rank_sum": sum(selected_ranks),
        "model_rank_gap": max(selected_ranks) - min(selected_ranks),
        "selected_win_probability_min": min(selected_win),
        "selected_win_probability_max": max(selected_win),
        "selected_win_probability_mean": float(np.mean(selected_win)),
        "won": int(key in winner_keys[bet_type]) if has_labels else None,
    }


def build_ticket_candidates(
    frame: pl.DataFrame,
    predictions: pl.DataFrame,
    *,
    pools: Iterable[str] = SUPPORTED_POOLS,
) -> pl.DataFrame:
    """Create one pre-race row per supported ticket with PL joint probabilities."""
    pools = tuple(dict.fromkeys(str(pool).upper() for pool in pools))
    unsupported = sorted(set(pools) - set(SUPPORTED_POOLS))
    if unsupported:
        raise RacePortfolioInputError(f"지원하지 않는 승식: {', '.join(unsupported)}")
    _require_columns(
        frame,
        {
            "race_id",
            "race_date_local",
            "race_number",
            "meet_code",
            "distance_m",
            "horse_number",
            "starters",
        },
        label="frame",
    )
    _require_columns(
        predictions,
        {"race_id", "horse_number", "prob_win"},
        label="predictions",
    )
    prediction_races = set(predictions["race_id"].unique().to_list())
    context = frame.filter(pl.col("race_id").is_in(prediction_races))
    rows: list[dict[str, Any]] = []
    for race_key, prediction_group in predictions.group_by("race_id", maintain_order=True):
        race_id = int(race_key[0])
        race_context = context.filter(pl.col("race_id") == race_id)
        if race_context.height < 3:
            continue
        numbers = set(int(value) for value in prediction_group["horse_number"].to_list())
        race_context = race_context.filter(pl.col("horse_number").is_in(numbers))
        ranked = prediction_group.sort(
            "prob_win", "horse_number", descending=[True, False]
        )
        ranks = {
            int(number): index + 1
            for index, number in enumerate(ranked["horse_number"].to_list())
        }
        win_probabilities = {
            int(row["horse_number"]): float(row["prob_win"])
            for row in prediction_group.select("horse_number", "prob_win").iter_rows(
                named=True
            )
        }
        scenarios = _race_scenarios(prediction_group)
        field_size = len(numbers)
        place_slots = 3 if field_size >= 8 else 2
        has_labels = (
            "finish_position" in race_context.columns
            and race_context["finish_position"].is_not_null().any()
        )
        winner_keys = _actual_winner_sets(race_context, place_slots=place_slots)
        metadata = race_context.row(0, named=True)
        probabilities: dict[str, dict[tuple[int, ...], float]] = {
            pool: {} for pool in pools
        }
        for order, scenario_probability in scenarios:
            if "WIN" in probabilities:
                probabilities["WIN"][(order[0],)] = probabilities["WIN"].get(
                    (order[0],), 0.0
                ) + scenario_probability
            if "PLC" in probabilities:
                for number in order[:place_slots]:
                    probabilities["PLC"][(number,)] = probabilities["PLC"].get(
                        (number,), 0.0
                    ) + scenario_probability
            if "QPL" in probabilities:
                for pair in combinations(sorted(order[:place_slots]), 2):
                    probabilities["QPL"][pair] = probabilities["QPL"].get(
                        pair, 0.0
                    ) + scenario_probability
            if "EXA" in probabilities:
                pair = (order[0], order[1])
                probabilities["EXA"][pair] = probabilities["EXA"].get(
                    pair, 0.0
                ) + scenario_probability
            if "TLA" in probabilities:
                triple = tuple(sorted(order))
                probabilities["TLA"][triple] = probabilities["TLA"].get(
                    triple, 0.0
                ) + scenario_probability
        race_probabilities = sorted(win_probabilities.values(), reverse=True)
        entropy = -sum(
            probability * math.log(max(probability, PROBABILITY_EPSILON))
            for probability in race_probabilities
        )
        race = {
            "race_id": race_id,
            "race_date_local": str(metadata["race_date_local"]),
            "race_number": int(metadata["race_number"]),
            "meet_code": int(metadata["meet_code"]),
            "distance_m": int(metadata["distance_m"]),
            "field_size": field_size,
            "place_slots": place_slots,
            "race_top1_probability": race_probabilities[0],
            "race_probability_gap12": race_probabilities[0] - race_probabilities[1],
            "race_entropy": entropy,
        }
        for pool, pool_probabilities in probabilities.items():
            for selected_numbers, probability in pool_probabilities.items():
                rows.append(
                    _ticket_feature_row(
                        race=race,
                        bet_type=pool,
                        numbers=selected_numbers,
                        probability=probability,
                        ranks=ranks,
                        win_probabilities=win_probabilities,
                        winner_keys=winner_keys,
                        has_labels=has_labels,
                    )
                )
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows, infer_schema_length=None).sort(
        "race_date_local", "race_id", "bet_type", "selection_key"
    )


def attach_final_odds(tickets: pl.DataFrame, odds: pl.DataFrame) -> pl.DataFrame:
    """Attach final dividends for training/settlement, never as prediction features."""
    _require_columns(
        odds,
        {"race_id", "bet_type", "selection_key", "odds"},
        label="odds",
    )
    latest = odds
    if "observed_at_ms" in odds.columns:
        latest = odds.sort("observed_at_ms").unique(
            subset=["race_id", "bet_type", "selection_key"], keep="last"
        )
    return tickets.join(
        latest.select(
            "race_id",
            "bet_type",
            "selection_key",
            pl.col("odds").alias("actual_odds"),
        ),
        on=["race_id", "bet_type", "selection_key"],
        how="left",
        validate="1:1",
    ).with_columns(
        (
            pl.col("actual_odds").is_not_null()
            & (pl.col("actual_odds") > 1.0)
            & (pl.col("actual_odds") < FINAL_ODDS_SENTINEL)
        ).alias("valid_odds")
    )


def _beta_features(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(values, dtype=float), PROBABILITY_EPSILON, 1 - PROBABILITY_EPSILON)
    return np.column_stack((np.log(clipped), -np.log1p(-clipped)))


def fit_probability_models(
    tickets: pl.DataFrame,
    *,
    pools: Iterable[str] = SUPPORTED_POOLS,
) -> dict[str, PoolProbabilityModel]:
    _require_columns(
        tickets,
        {"race_id", "bet_type", "ticket_probability", "won"},
        label="tickets",
    )
    models: dict[str, PoolProbabilityModel] = {}
    for pool in pools:
        group = tickets.filter(
            (pl.col("bet_type") == pool) & pl.col("won").is_not_null()
        )
        if group.height == 0 or group["won"].n_unique() < 2:
            continue
        counts = group.group_by("race_id").len().rename({"len": "_race_rows"})
        weighted = group.join(counts, on="race_id", how="left")
        sample_weight = 1.0 / weighted["_race_rows"].to_numpy()
        sample_weight *= len(sample_weight) / sample_weight.sum()
        estimator = LogisticRegression(C=10.0, max_iter=1_000, random_state=42)
        estimator.fit(
            _beta_features(weighted["ticket_probability"].to_numpy()),
            weighted["won"].to_numpy(),
            sample_weight=sample_weight,
        )
        models[pool] = PoolProbabilityModel(pool=pool, estimator=estimator)
    return models


def apply_probability_models(
    tickets: pl.DataFrame,
    models: dict[str, PoolProbabilityModel],
) -> pl.DataFrame:
    pieces: list[pl.DataFrame] = []
    for pool_key, group in tickets.partition_by("bet_type", as_dict=True).items():
        pool = str(pool_key[0])
        model = models.get(pool)
        if model is None:
            continue
        pieces.append(
            group.with_columns(
                pl.Series(
                    "ticket_probability_calibrated",
                    model.predict(group["ticket_probability"].to_numpy()),
                )
            )
        )
    return pl.concat(pieces, how="diagonal_relaxed") if pieces else pl.DataFrame()


def _with_odds_features(tickets: pl.DataFrame) -> pl.DataFrame:
    return tickets.with_columns(
        pl.col("ticket_probability_calibrated")
        .clip(PROBABILITY_EPSILON, 1.0)
        .log()
        .alias("log_ticket_probability")
    )


def fit_race_portfolio_bundle(
    tickets: pl.DataFrame,
    *,
    train_end: str,
    pools: Iterable[str] = SUPPORTED_POOLS,
    lower_quantile: float = 0.20,
    seed: int = 42,
) -> RacePortfolioBundle:
    """Fit pool probability calibration and conservative final-dividend models."""
    if not 0 < lower_quantile < 0.5:
        raise RacePortfolioInputError("lower_quantile은 0과 0.5 사이여야 합니다.")
    train = tickets.filter(pl.col("race_date_local") <= train_end)
    train = train.filter(pl.col("valid_odds") & pl.col("won").is_not_null())
    if train.height == 0:
        raise RacePortfolioInputError("배당과 결과가 있는 학습 ticket이 없습니다.")
    probability_models = fit_probability_models(train, pools=pools)
    prepared = _with_odds_features(apply_probability_models(train, probability_models))
    odds_models: dict[str, PoolOddsModel] = {}
    for pool in pools:
        group = prepared.filter(pl.col("bet_type") == pool)
        if group.height < 100:
            continue
        matrix = group.select(ODDS_FEATURES).to_numpy()
        target = np.log(group["actual_odds"].to_numpy())
        shared = {
            "n_estimators": 250,
            "learning_rate": 0.04,
            "num_leaves": 31,
            "min_child_samples": 100,
            "subsample": 0.9,
            "subsample_freq": 1,
            "colsample_bytree": 0.9,
            "reg_lambda": 1.0,
            "random_state": seed,
            "n_jobs": -1,
            "verbosity": -1,
        }
        lower = lgb.LGBMRegressor(
            objective="quantile", alpha=lower_quantile, **shared
        )
        median = lgb.LGBMRegressor(objective="quantile", alpha=0.5, **shared)
        lower.fit(matrix, target)
        median.fit(matrix, target)
        odds_models[pool] = PoolOddsModel(
            pool=pool,
            lower_quantile=lower_quantile,
            lower=lower,
            median=median,
        )
    if not odds_models:
        raise RacePortfolioInputError("학습된 승식별 배당 모델이 없습니다.")
    return RacePortfolioBundle(
        probability_models=probability_models,
        odds_models=odds_models,
        train_end=train_end,
        lower_quantile=lower_quantile,
    )


def save_race_portfolio_bundle(bundle: RacePortfolioBundle, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        pickle.dump(bundle, stream)
    return output


def load_race_portfolio_bundle(path: str | Path) -> RacePortfolioBundle:
    with Path(path).open("rb") as stream:
        bundle = pickle.load(stream)
    if not isinstance(bundle, RacePortfolioBundle):
        raise RacePortfolioInputError("RacePortfolioBundle artifact가 아닙니다.")
    return bundle


def _winning_ticket_keys(
    order: tuple[int, int, int],
    *,
    place_slots: int,
) -> set[tuple[str, str]]:
    keys = {
        ("WIN", _selection_key([order[0]], ordered=True)),
        ("EXA", _selection_key(order[:2], ordered=True)),
        ("TLA", _selection_key(order, ordered=False)),
    }
    for number in order[:place_slots]:
        keys.add(("PLC", _selection_key([number], ordered=True)))
    for pair in combinations(sorted(order[:place_slots]), 2):
        keys.add(("QPL", _selection_key(pair, ordered=False)))
    return keys


def _positive_compositions(total: int, parts: int) -> Iterable[tuple[int, ...]]:
    if parts == 1:
        yield (total,)
        return
    for first in range(1, total - parts + 2):
        for rest in _positive_compositions(total - first, parts - 1):
            yield (first, *rest)


def optimize_race_portfolio(
    prediction_group: pl.DataFrame,
    ticket_group: pl.DataFrame,
    *,
    budget_units: int = 10,
    max_tickets: int = 3,
    candidate_limit: int = 6,
    minimum_expected_return: float = 1.02,
    minimum_ticket_probability: float = 0.05,
    minimum_non_loss_probability: float = 0.10,
) -> PortfolioRecommendation:
    """Maximize modeled probability of return >= stake under a return constraint."""
    if budget_units < 1 or max_tickets < 1:
        raise RacePortfolioInputError("budget_units와 max_tickets는 1 이상이어야 합니다.")
    if not 0.0 <= minimum_ticket_probability <= 1.0:
        raise RacePortfolioInputError("minimum_ticket_probability는 0과 1 사이여야 합니다.")
    if not 0.0 <= minimum_non_loss_probability <= 1.0:
        raise RacePortfolioInputError(
            "minimum_non_loss_probability는 0과 1 사이여야 합니다."
        )
    required = {
        "race_id",
        "bet_type",
        "selection_key",
        "ticket_probability_calibrated",
        "predicted_odds_lower",
        "predicted_odds_median",
        "conservative_return_multiplier",
        "place_slots",
    }
    _require_columns(ticket_group, required, label="ticket_group")
    race_id = int(ticket_group["race_id"][0])
    candidates = (
        ticket_group.filter(
            (pl.col("conservative_return_multiplier") >= minimum_expected_return)
            & (
                pl.col("ticket_probability_calibrated")
                >= minimum_ticket_probability
            )
        )
        .sort(
            "conservative_return_multiplier",
            "ticket_probability_calibrated",
            descending=True,
        )
        .head(candidate_limit)
    )
    if candidates.height == 0:
        return PortfolioRecommendation(
            race_id=race_id,
            lines=(),
            stake_units=0,
            probability_non_loss=0.0,
            expected_return_lower=0.0,
            expected_return_median=0.0,
            reason="보수적 기대수익 조건을 만족한 조합이 없음",
        )
    scenarios = _race_scenarios(prediction_group)
    scenario_probability = np.asarray([probability for _, probability in scenarios])
    candidate_rows = candidates.to_dicts()
    win_matrix = np.zeros((len(scenarios), len(candidate_rows)), dtype=float)
    for scenario_index, (order, _) in enumerate(scenarios):
        winners = _winning_ticket_keys(
            order, place_slots=int(candidates["place_slots"][0])
        )
        for candidate_index, row in enumerate(candidate_rows):
            if (str(row["bet_type"]), str(row["selection_key"])) in winners:
                win_matrix[scenario_index, candidate_index] = 1.0
    best: tuple[tuple[float, float, float, int], tuple[int, ...], tuple[int, ...]] | None = None
    maximum_size = min(max_tickets, candidates.height, budget_units)
    for size in range(1, maximum_size + 1):
        for indices in combinations(range(candidates.height), size):
            for allocation in _positive_compositions(budget_units, size):
                allocation_array = np.asarray(allocation, dtype=float)
                lower_odds = np.asarray(
                    [candidate_rows[index]["predicted_odds_lower"] for index in indices]
                )
                median_odds = np.asarray(
                    [candidate_rows[index]["predicted_odds_median"] for index in indices]
                )
                calibrated_probability = np.asarray(
                    [
                        candidate_rows[index]["ticket_probability_calibrated"]
                        for index in indices
                    ]
                )
                selected_wins = win_matrix[:, indices]
                lower_returns = selected_wins @ (allocation_array * lower_odds)
                expected_lower = float(
                    np.sum(allocation_array * lower_odds * calibrated_probability)
                    / budget_units
                )
                if expected_lower < minimum_expected_return:
                    continue
                probability_non_loss = float(
                    scenario_probability[lower_returns >= budget_units].sum()
                )
                if probability_non_loss < minimum_non_loss_probability:
                    continue
                expected_median = float(
                    np.sum(allocation_array * median_odds * calibrated_probability)
                    / budget_units
                )
                objective = (
                    probability_non_loss,
                    expected_lower,
                    expected_median,
                    -size,
                )
                if best is None or objective > best[0]:
                    best = (objective, indices, allocation)
    if best is None:
        return PortfolioRecommendation(
            race_id=race_id,
            lines=(),
            stake_units=0,
            probability_non_loss=0.0,
            expected_return_lower=0.0,
            expected_return_median=0.0,
            reason="포트폴리오 기대수익 제약을 만족하지 못함",
        )
    objective, indices, allocation = best
    lines = tuple(
        PortfolioLine(
            bet_type=str(candidate_rows[index]["bet_type"]),
            selection_key=str(candidate_rows[index]["selection_key"]),
            stake_units=int(stake),
            ticket_probability=float(
                candidate_rows[index]["ticket_probability_calibrated"]
            ),
            predicted_odds_lower=float(candidate_rows[index]["predicted_odds_lower"]),
            predicted_odds_median=float(candidate_rows[index]["predicted_odds_median"]),
        )
        for index, stake in zip(indices, allocation, strict=True)
    )
    return PortfolioRecommendation(
        race_id=race_id,
        lines=lines,
        stake_units=budget_units,
        probability_non_loss=objective[0],
        expected_return_lower=objective[1],
        expected_return_median=objective[2],
        reason="보수적 배당에서 원금회수 확률 최대화",
    )


def _max_consecutive_losses(values: list[bool]) -> int:
    longest = current = 0
    for won in values:
        if won:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def backtest_fixed_rank_ticket(
    scored_tickets: pl.DataFrame,
    *,
    bet_type: str,
    model_ranks: tuple[int, ...],
    start_date: str,
    end_date: str,
) -> FixedRankBacktest:
    """Settle one fixed model-rank ticket per race as a transparent baseline."""
    pool = bet_type.upper()
    required_count = {"WIN": 1, "PLC": 1, "QPL": 2, "EXA": 2, "TLA": 3}
    if pool not in required_count:
        raise RacePortfolioInputError(f"지원하지 않는 승식: {pool}")
    if len(model_ranks) != required_count[pool] or len(set(model_ranks)) != len(
        model_ranks
    ):
        raise RacePortfolioInputError("승식에 맞는 서로 다른 model_ranks가 필요합니다.")
    _require_columns(
        scored_tickets,
        {
            "race_id",
            "race_date_local",
            "bet_type",
            "selection_key",
            "model_rank_min",
            "actual_odds",
            "valid_odds",
            "won",
        },
        label="scored_tickets",
    )
    period = scored_tickets.filter(
        (pl.col("race_date_local") >= start_date)
        & (pl.col("race_date_local") <= end_date)
    )
    returns: list[float] = []
    profits: list[float] = []
    for _race_key, group in period.group_by("race_id", maintain_order=True):
        win_rows = group.filter(pl.col("bet_type") == "WIN")
        selections: list[int] = []
        for rank in model_ranks:
            row = win_rows.filter(pl.col("model_rank_min") == rank)
            if row.height != 1:
                selections = []
                break
            selections.append(int(row["selection_key"][0]))
        if not selections:
            continue
        key = _selection_key(selections, ordered=pool == "EXA")
        settled = group.filter(
            (pl.col("bet_type") == pool)
            & (pl.col("selection_key") == key)
            & pl.col("valid_odds")
        )
        if settled.height != 1:
            continue
        returned = (
            float(settled["actual_odds"][0]) if bool(settled["won"][0]) else 0.0
        )
        returns.append(returned)
        profits.append(returned - 1.0)
    races = len(returns)
    if races == 0:
        return FixedRankBacktest(
            bet_type=pool,
            model_ranks=model_ranks,
            races=0,
            hits=0,
            hit_rate=0.0,
            returned_units=0.0,
            roi=0.0,
            max_drawdown_units=0.0,
            max_consecutive_losses=0,
            top_one_profit_removed_roi=0.0,
            top_three_profit_removed_roi=0.0,
        )
    cumulative = np.cumsum(profits)
    peak = np.maximum.accumulate(np.concatenate(([0.0], cumulative)))[1:]
    sorted_returns = sorted(returns, reverse=True)

    def removed_roi(count: int) -> float:
        remainder = sorted_returns[count:]
        return sum(remainder) / len(remainder) if remainder else 0.0

    hits = sum(value > 0 for value in returns)
    return FixedRankBacktest(
        bet_type=pool,
        model_ranks=model_ranks,
        races=races,
        hits=hits,
        hit_rate=hits / races,
        returned_units=sum(returns),
        roi=sum(returns) / races,
        max_drawdown_units=float((peak - cumulative).max(initial=0.0)),
        max_consecutive_losses=_max_consecutive_losses(
            [value > 0 for value in returns]
        ),
        top_one_profit_removed_roi=removed_roi(1),
        top_three_profit_removed_roi=removed_roi(3),
    )


def backtest_portfolios(
    predictions: pl.DataFrame,
    scored_tickets: pl.DataFrame,
    *,
    start_date: str,
    end_date: str,
    budget_units: int = 10,
    max_tickets: int = 3,
    candidate_limit: int = 6,
    minimum_expected_return: float = 1.02,
    minimum_ticket_probability: float = 0.05,
    minimum_non_loss_probability: float = 0.10,
) -> PortfolioBacktest:
    """Select using predicted dividends and settle only against actual dividends."""
    test = scored_tickets.filter(
        (pl.col("race_date_local") >= start_date)
        & (pl.col("race_date_local") <= end_date)
        & pl.col("valid_odds")
    )
    rows: list[dict[str, Any]] = []
    races_available = 0
    for race_key, ticket_group in test.group_by("race_id", maintain_order=True):
        race_id = int(race_key[0])
        prediction_group = predictions.filter(pl.col("race_id") == race_id)
        if prediction_group.height < 3:
            continue
        races_available += 1
        recommendation = optimize_race_portfolio(
            prediction_group,
            ticket_group,
            budget_units=budget_units,
            max_tickets=max_tickets,
            candidate_limit=candidate_limit,
            minimum_expected_return=minimum_expected_return,
            minimum_ticket_probability=minimum_ticket_probability,
            minimum_non_loss_probability=minimum_non_loss_probability,
        )
        if not recommendation.lines:
            continue
        returned = 0.0
        hit = False
        line_rows: list[dict[str, Any]] = []
        for line in recommendation.lines:
            settled = ticket_group.filter(
                (pl.col("bet_type") == line.bet_type)
                & (pl.col("selection_key") == line.selection_key)
            ).row(0, named=True)
            won = bool(settled["won"])
            actual_return = line.stake_units * float(settled["actual_odds"]) if won else 0.0
            returned += actual_return
            hit = hit or won
            line_rows.append(
                {
                    "bet_type": line.bet_type,
                    "selection_key": line.selection_key,
                    "stake_units": line.stake_units,
                    "actual_odds": float(settled["actual_odds"]),
                    "won": int(won),
                    "actual_return": actual_return,
                }
            )
        metadata = ticket_group.row(0, named=True)
        profit = returned - recommendation.stake_units
        for row in line_rows:
            rows.append(
                {
                    "race_id": race_id,
                    "race_date_local": str(metadata["race_date_local"]),
                    "race_number": int(metadata["race_number"]),
                    "meet_code": int(metadata["meet_code"]),
                    **row,
                    "portfolio_stake": recommendation.stake_units,
                    "portfolio_return": returned,
                    "portfolio_profit": profit,
                    "portfolio_hit": int(hit),
                    "portfolio_non_loss": int(returned >= recommendation.stake_units),
                    "modeled_non_loss_probability": recommendation.probability_non_loss,
                    "modeled_expected_return_lower": recommendation.expected_return_lower,
                }
            )
    if not rows:
        empty = pl.DataFrame()
        return PortfolioBacktest(
            races_available=races_available,
            races_bet=0,
            tickets_bet=0,
            profitable_races=0,
            hit_races=0,
            stake_units=0.0,
            returned_units=0.0,
            roi=0.0,
            profit_race_rate=0.0,
            hit_race_rate=0.0,
            max_drawdown_units=0.0,
            max_consecutive_losing_races=0,
            top_one_profit_removed_roi=0.0,
            top_three_profit_removed_roi=0.0,
            monthly=(),
            selections=empty,
        )
    selections = pl.DataFrame(rows, infer_schema_length=None)
    per_race = (
        selections.group_by("race_id", maintain_order=True)
        .agg(
            pl.first("race_date_local").alias("race_date_local"),
            pl.first("race_number").alias("race_number"),
            pl.first("meet_code").alias("meet_code"),
            pl.first("portfolio_stake").alias("stake"),
            pl.first("portfolio_return").alias("returned"),
            pl.first("portfolio_profit").alias("profit"),
            pl.first("portfolio_hit").alias("hit"),
            pl.first("portfolio_non_loss").alias("non_loss"),
        )
        .sort("race_date_local", "race_number", "meet_code")
    )
    cumulative = np.cumsum(per_race["profit"].to_numpy())
    peak = np.maximum.accumulate(np.concatenate(([0.0], cumulative)))[1:]
    drawdown = peak - cumulative
    total_stake = float(per_race["stake"].sum())
    total_return = float(per_race["returned"].sum())
    profit_sorted = per_race.sort("profit", descending=True)

    def removed_roi(count: int) -> float:
        remaining = profit_sorted.slice(count)
        stake = float(remaining["stake"].sum())
        return float(remaining["returned"].sum() / stake) if stake else 0.0

    monthly = tuple(
        per_race.with_columns(pl.col("race_date_local").str.slice(0, 7).alias("month"))
        .group_by("month")
        .agg(
            pl.len().alias("races"),
            pl.col("stake").sum().alias("stake"),
            pl.col("returned").sum().alias("returned"),
            pl.col("non_loss").sum().alias("non_loss_races"),
        )
        .with_columns((pl.col("returned") / pl.col("stake")).alias("roi"))
        .sort("month")
        .to_dicts()
    )
    return PortfolioBacktest(
        races_available=races_available,
        races_bet=per_race.height,
        tickets_bet=selections.height,
        profitable_races=int(per_race["non_loss"].sum()),
        hit_races=int(per_race["hit"].sum()),
        stake_units=total_stake,
        returned_units=total_return,
        roi=total_return / total_stake,
        profit_race_rate=float(per_race["non_loss"].mean()),
        hit_race_rate=float(per_race["hit"].mean()),
        max_drawdown_units=float(drawdown.max(initial=0.0)),
        max_consecutive_losing_races=_max_consecutive_losses(
            (per_race["profit"] >= 0).to_list()
        ),
        top_one_profit_removed_roi=removed_roi(1),
        top_three_profit_removed_roi=removed_roi(3),
        monthly=monthly,
        selections=selections,
    )

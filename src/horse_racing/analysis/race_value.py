"""RaceValue V1: detect plausible market-undervalued place candidates.

Historical final WIN odds are used only to create the research label and to
settle bets.  They are deliberately excluded from the model feature matrix.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression

from horse_racing.analysis.race_portfolio import RacePortfolioInputError

SLEEPER_FEATURES = (
    "prob_win",
    "prob_top2",
    "prob_top3",
    "rank_score",
    "model_rank",
    "horse_number_pct",
    "carried_weight_rel",
    "load_ratio_pct",
    "career_starts",
    "form_recent3_pct",
    "form_recent5_pct",
    "top3_rate_recent5",
    "win_rate_career",
    "top3_rate_career",
    "days_since_last_race",
    "speed_rel_avg5",
    "speed_rel_best5",
    "speed_figure_last",
    "speed_figure_avg3",
    "speed_figure_trend",
    "energy_early_rel_avg5",
    "energy_finish_rel_avg5",
    "energy_resilience_avg5",
    "ability_elo_global",
    "ability_elo_context",
    "ability_elo_vs_field",
    "ability_elo_uncertainty",
    "early_pos_pct_avg5",
    "late_gain_pct_avg5",
    "pace_fade_avg5",
    "front_runner_count",
    "front_rival_count",
    "gate_top3_index_context",
    "gate_early_speed_context",
    "gate_early_speed_front_fit",
    "sand_recovery_score",
    "sand_recovered_flag",
    "sand_exposure_risk",
    "sand_expected_penalty",
    "condition_speed_delta",
    "condition_form_delta",
    "condition_weight_z",
    "condition_evidence",
    "condition_uncertainty",
    "jockey_win_rate_90d",
    "jockey_top3_rate_90d",
    "trainer_win_rate_90d",
    "trainer_top3_rate_90d",
    "horse_jockey_starts",
    "jockey_changed",
    "rating_race_z",
    "speed_figure_median5_race_z",
    "ability_elo_context_race_z",
    "late_gain_pct_avg5_race_z",
    "exact_distance_top3_rate_race_z",
)

MARKET_FEATURES = (
    "meet_code",
    "distance_m",
    "race_number",
    "starters",
    "horse_number_pct",
    "gate_number",
    "carried_weight_kg",
    "carried_weight_rel",
    "body_weight_kg",
    "body_weight_change_kg",
    "rating",
    "horse_age_months",
    "career_starts",
    "finish_pos_last",
    "form_recent3_pct",
    "form_recent5_pct",
    "top3_rate_recent5",
    "win_rate_career",
    "top3_rate_career",
    "days_since_last_race",
    "long_layoff",
    "is_debut",
    "dist_band_starts",
    "dist_band_top3_rate",
    "exact_distance_starts",
    "exact_distance_top3_rate",
    "meet_starts",
    "meet_win_rate",
    "jockey_starts_90d",
    "jockey_win_rate_90d",
    "jockey_top3_rate_90d",
    "trainer_starts_90d",
    "trainer_win_rate_90d",
    "trainer_top3_rate_90d",
    "horse_jockey_starts",
    "horse_jockey_wins",
    "jockey_changed",
)

FORBIDDEN_MODEL_FEATURES = {
    "actual_win_odds",
    "actual_place_odds",
    "actual_market_rank",
    "finish_position",
    "win",
    "top2",
    "top3",
    "sleeper_top3",
    "place_won",
}


@dataclass
class RaceValueBundle:
    estimator: lgb.LGBMClassifier
    calibrator: LogisticRegression
    feature_names: tuple[str, ...]
    market_estimator: lgb.LGBMRegressor
    market_feature_names: tuple[str, ...]
    train_end: str
    calibration_end: str
    model_name: str = "RaceValue V1"

    def predict(self, frame: pl.DataFrame) -> pl.DataFrame:
        required = set(self.feature_names) | set(self.market_feature_names)
        missing = sorted(required - set(frame.columns))
        if missing:
            raise RacePortfolioInputError(
                f"RaceValue 입력 컬럼 없음: {', '.join(missing)}"
            )
        matrix = _feature_matrix(frame, self.feature_names)
        raw = np.clip(
            self.estimator.predict_proba(matrix)[:, 1], 1e-6, 1.0 - 1e-6
        )
        calibrated = self.calibrator.predict_proba(_logit_feature(raw))[:, 1]
        predicted_market_odds = np.exp(
            self.market_estimator.predict(
                _feature_matrix(frame, self.market_feature_names)
            )
        )
        return frame.with_columns(
            pl.Series("sleeper_probability", calibrated).clip(1e-6, 1.0 - 1e-6),
            pl.Series(
                "predicted_market_win_odds",
                np.clip(predicted_market_odds, 1.0, 5_000.0),
            ),
        ).with_columns(
            pl.col("predicted_market_win_odds")
            .rank("ordinal")
            .over("race_id")
            .alias("predicted_market_rank")
        )


@dataclass(frozen=True)
class SleeperStrategyBacktest:
    bet_type: str
    races: int
    hits: int
    hit_rate: float
    sleeper_hits: int
    sleeper_hit_rate: float
    average_winning_odds: float
    returned_units: float
    roi: float
    max_drawdown_units: float
    max_consecutive_losses: int
    top_one_profit_removed_roi: float
    top_three_profit_removed_roi: float
    selections: pl.DataFrame = field(repr=False)


def _feature_matrix(frame: pl.DataFrame, feature_names: tuple[str, ...]) -> np.ndarray:
    return frame.select(feature_names).cast(pl.Float64).to_numpy()


def _logit_feature(probability: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(probability, dtype=float), 1e-6, 1.0 - 1e-6)
    return np.log(clipped / (1.0 - clipped)).reshape(-1, 1)


def build_historical_sleeper_frame(
    dataset: pl.DataFrame,
    predictions: pl.DataFrame,
    scored_tickets: pl.DataFrame,
) -> pl.DataFrame:
    """Build a horse-level research frame with final-odds-only labels."""
    required_dataset = {
        "race_id",
        "race_entry_id",
        "race_date_local",
        "horse_number",
        "finish_position",
    }
    required_predictions = {
        "race_id",
        "race_entry_id",
        "horse_number",
        "prob_win",
        "prob_top2",
        "prob_top3",
        "rank_score",
    }
    required_tickets = {
        "race_id",
        "bet_type",
        "selection_key",
        "actual_odds",
        "valid_odds",
        "won",
        "predicted_odds_lower",
        "predicted_odds_median",
    }
    for label, frame, required in (
        ("dataset", dataset, required_dataset),
        ("predictions", predictions, required_predictions),
        ("scored_tickets", scored_tickets, required_tickets),
    ):
        missing = sorted(required - set(frame.columns))
        if missing:
            raise RacePortfolioInputError(f"{label} 컬럼 없음: {', '.join(missing)}")

    win = scored_tickets.filter(pl.col("bet_type") == "WIN").select(
        "race_id",
        pl.col("selection_key").cast(pl.Int64).alias("horse_number"),
        pl.col("actual_odds").alias("actual_win_odds"),
        pl.col("valid_odds").alias("valid_win_odds"),
        pl.col("predicted_odds_lower").alias("predicted_win_odds_lower"),
        pl.col("predicted_odds_median").alias("predicted_win_odds_median"),
    )
    place = scored_tickets.filter(pl.col("bet_type") == "PLC").select(
        "race_id",
        pl.col("selection_key").cast(pl.Int64).alias("horse_number"),
        pl.col("actual_odds").alias("actual_place_odds"),
        pl.col("valid_odds").alias("valid_place_odds"),
        pl.col("won").alias("place_won"),
        pl.col("predicted_odds_lower").alias("predicted_place_odds_lower"),
        pl.col("predicted_odds_median").alias("predicted_place_odds_median"),
    )
    frame = (
        dataset.join(
            predictions,
            on=["race_id", "race_entry_id", "horse_number"],
            how="inner",
            validate="1:1",
        )
        .join(win, on=["race_id", "horse_number"], how="inner", validate="1:1")
        .join(place, on=["race_id", "horse_number"], how="left", validate="1:1")
        .filter(pl.col("valid_win_odds"))
        .with_columns(
            pl.col("actual_win_odds")
            .rank("ordinal")
            .over("race_id")
            .alias("actual_market_rank"),
            pl.col("prob_win")
            .rank("ordinal", descending=True)
            .over("race_id")
            .alias("model_rank"),
        )
        .with_columns(
            (
                (pl.col("finish_position") <= 3)
                & (pl.col("actual_market_rank") >= 4)
            )
            .cast(pl.Int8)
            .alias("sleeper_top3")
        )
    )
    return frame.sort("race_date_local", "race_id", "model_rank")


def fit_race_value_bundle(
    frame: pl.DataFrame,
    *,
    train_end: str,
    calibration_start: str,
    calibration_end: str,
    seed: int = 42,
) -> RaceValueBundle:
    """Fit and calibrate the longshot-top3 event model chronologically."""
    available_features = tuple(
        name
        for name in SLEEPER_FEATURES
        if name in frame.columns and frame.schema[name].is_numeric()
    )
    market_features = tuple(
        name
        for name in MARKET_FEATURES
        if name in frame.columns and frame.schema[name].is_numeric()
    )
    if not available_features:
        raise RacePortfolioInputError("RaceValue에 사용할 수치형 feature가 없습니다.")
    if not market_features:
        raise RacePortfolioInputError("시장배당 모델 feature가 없습니다.")
    leaked = sorted(FORBIDDEN_MODEL_FEATURES & set(available_features))
    if leaked:
        raise RacePortfolioInputError(f"누수 feature 감지: {', '.join(leaked)}")
    train = frame.filter(pl.col("race_date_local") <= train_end)
    calibration = frame.filter(
        (pl.col("race_date_local") >= calibration_start)
        & (pl.col("race_date_local") <= calibration_end)
    )
    if train.height < 1_000 or calibration.height < 200:
        raise RacePortfolioInputError("학습 또는 확률보정 표본이 부족합니다.")
    estimator = lgb.LGBMClassifier(
        n_estimators=350,
        learning_rate=0.025,
        num_leaves=15,
        min_child_samples=100,
        subsample=0.85,
        subsample_freq=1,
        colsample_bytree=0.80,
        reg_lambda=3.0,
        random_state=seed,
        n_jobs=-1,
        verbosity=-1,
    )
    race_counts = train.group_by("race_id").len().rename({"len": "_race_rows"})
    weighted = train.join(race_counts, on="race_id", how="left")
    sample_weight = 1.0 / weighted["_race_rows"].to_numpy()
    sample_weight *= len(sample_weight) / sample_weight.sum()
    estimator.fit(
        _feature_matrix(weighted, available_features),
        weighted["sleeper_top3"].to_numpy(),
        sample_weight=sample_weight,
    )
    raw = np.clip(
        estimator.predict_proba(_feature_matrix(calibration, available_features))[:, 1],
        1e-6,
        1.0 - 1e-6,
    )
    calibrator = LogisticRegression(C=10.0, max_iter=1_000, random_state=seed)
    calibrator.fit(_logit_feature(raw), calibration["sleeper_top3"].to_numpy())
    market_estimator = lgb.LGBMRegressor(
        objective="regression_l1",
        n_estimators=400,
        learning_rate=0.025,
        num_leaves=15,
        min_child_samples=100,
        colsample_bytree=0.85,
        reg_lambda=3.0,
        random_state=seed,
        n_jobs=-1,
        verbosity=-1,
    )
    market_estimator.fit(
        _feature_matrix(train, market_features),
        np.log(train["actual_win_odds"].to_numpy()),
        sample_weight=sample_weight,
    )
    return RaceValueBundle(
        estimator=estimator,
        calibrator=calibrator,
        feature_names=available_features,
        market_estimator=market_estimator,
        market_feature_names=market_features,
        train_end=train_end,
        calibration_end=calibration_end,
    )


def select_sleeper_candidates(
    scored_horses: pl.DataFrame,
    *,
    minimum_model_rank: int = 3,
    maximum_model_rank: int = 8,
    payout_exponent: float = 0.0,
    minimum_score: float | None = None,
    minimum_predicted_market_rank: int = 4,
) -> pl.DataFrame:
    """Select at most one balanced sleeper candidate per race."""
    if minimum_model_rank < 1 or maximum_model_rank < minimum_model_rank:
        raise RacePortfolioInputError("복병 후보 순위 범위가 잘못되었습니다.")
    required = {
        "race_id",
        "model_rank",
        "prob_top3",
        "predicted_market_win_odds",
        "predicted_market_rank",
    }
    missing = sorted(required - set(scored_horses.columns))
    if missing:
        raise RacePortfolioInputError(f"복병 선택 컬럼 없음: {', '.join(missing)}")
    candidates = scored_horses.filter(
        (pl.col("model_rank") >= minimum_model_rank)
        & (pl.col("model_rank") <= maximum_model_rank)
        & (pl.col("predicted_market_rank") >= minimum_predicted_market_rank)
        & pl.col("predicted_market_win_odds").is_not_null()
    ).with_columns(
        (
            pl.col("prob_top3").clip(1e-6, 1.0).log()
            + payout_exponent
            * pl.col("predicted_market_win_odds").clip(1.0, 5_000.0).log()
        ).alias("sleeper_score")
    )
    if minimum_score is not None:
        candidates = candidates.filter(pl.col("sleeper_score") >= minimum_score)
    if candidates.height == 0:
        return candidates
    return (
        candidates.sort(
            "sleeper_score", "sleeper_probability", "model_rank",
            descending=[True, True, False],
        )
        .group_by("race_id", maintain_order=True)
        .first()
        .sort("race_date_local", "race_id")
    )


def settle_sleeper_candidates(
    candidates: pl.DataFrame,
    scored_tickets: pl.DataFrame,
) -> pl.DataFrame:
    """Settle sleeper PLC, rank1-sleeper QPL, and rank1-rank2-sleeper TLA."""
    rows: list[dict[str, Any]] = []
    for candidate in candidates.iter_rows(named=True):
        race_id = int(candidate["race_id"])
        horse_number = int(candidate["horse_number"])
        race = scored_tickets.filter(pl.col("race_id") == race_id)
        ranked = race.filter(pl.col("bet_type") == "WIN").sort("model_rank_min")
        if ranked.height < 2:
            continue
        anchor_one = int(ranked["selection_key"][0])
        anchor_two = int(ranked["selection_key"][1])
        keys = {
            "PLC": str(horse_number),
            "QPL": "-".join(str(value) for value in sorted((anchor_one, horse_number))),
            "TLA": "-".join(
                str(value) for value in sorted((anchor_one, anchor_two, horse_number))
            ),
        }
        settlement: dict[str, tuple[int, float]] = {}
        for pool, key in keys.items():
            ticket = race.filter(
                (pl.col("bet_type") == pool)
                & (pl.col("selection_key") == key)
                & pl.col("valid_odds")
            )
            if ticket.height != 1:
                break
            settlement[pool] = (
                int(ticket["won"][0]),
                float(ticket["actual_odds"][0]),
            )
        if len(settlement) != len(keys):
            continue
        rows.append(
            {
                "race_id": race_id,
                "race_date_local": str(candidate["race_date_local"]),
                "meet_code": int(candidate["meet_code"]),
                "race_number": int(candidate["race_number"]),
                "horse_number": horse_number,
                "model_rank": int(candidate["model_rank"]),
                "actual_market_rank": int(candidate["actual_market_rank"]),
                "sleeper_probability": float(candidate["sleeper_probability"]),
                "sleeper_score": float(candidate["sleeper_score"]),
                "sleeper_top3": int(candidate["sleeper_top3"]),
                **{
                    f"{pool.lower()}_won": settlement[pool][0]
                    for pool in settlement
                },
                **{
                    f"{pool.lower()}_odds": settlement[pool][1]
                    for pool in settlement
                },
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None) if rows else pl.DataFrame()


def _max_consecutive_losses(values: list[bool]) -> int:
    longest = current = 0
    for won in values:
        if won:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def backtest_sleeper_strategy(
    settled: pl.DataFrame,
    *,
    bet_type: str,
) -> SleeperStrategyBacktest:
    pool = bet_type.upper()
    if pool not in {"PLC", "QPL", "TLA"}:
        raise RacePortfolioInputError(f"지원하지 않는 복병 승식: {pool}")
    won_column = f"{pool.lower()}_won"
    odds_column = f"{pool.lower()}_odds"
    if settled.height == 0:
        return SleeperStrategyBacktest(
            bet_type=pool,
            races=0,
            hits=0,
            hit_rate=0.0,
            sleeper_hits=0,
            sleeper_hit_rate=0.0,
            average_winning_odds=0.0,
            returned_units=0.0,
            roi=0.0,
            max_drawdown_units=0.0,
            max_consecutive_losses=0,
            top_one_profit_removed_roi=0.0,
            top_three_profit_removed_roi=0.0,
            selections=settled,
        )
    ordered = settled.sort("race_date_local", "race_number", "meet_code")
    returns = (
        ordered[won_column].cast(pl.Float64) * ordered[odds_column]
    ).to_numpy()
    wins = ordered.filter(pl.col(won_column) == 1)[odds_column].to_list()
    profits = returns - 1.0
    cumulative = np.cumsum(profits)
    peak = np.maximum.accumulate(np.concatenate(([0.0], cumulative)))[1:]
    sorted_returns = sorted(returns, reverse=True)

    def removed_roi(count: int) -> float:
        remainder = sorted_returns[count:]
        return float(sum(remainder) / len(remainder)) if remainder else 0.0

    return SleeperStrategyBacktest(
        bet_type=pool,
        races=ordered.height,
        hits=len(wins),
        hit_rate=len(wins) / ordered.height,
        sleeper_hits=int(ordered["sleeper_top3"].sum()),
        sleeper_hit_rate=float(ordered["sleeper_top3"].mean()),
        average_winning_odds=float(np.mean(wins)) if wins else 0.0,
        returned_units=float(returns.sum()),
        roi=float(returns.mean()),
        max_drawdown_units=float((peak - cumulative).max(initial=0.0)),
        max_consecutive_losses=_max_consecutive_losses(
            ordered[won_column].cast(pl.Boolean).to_list()
        ),
        top_one_profit_removed_roi=removed_roi(1),
        top_three_profit_removed_roi=removed_roi(3),
        selections=ordered,
    )


def save_race_value_bundle(bundle: RaceValueBundle, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        pickle.dump(bundle, stream)
    return output


def load_race_value_bundle(path: str | Path) -> RaceValueBundle:
    with Path(path).open("rb") as stream:
        bundle = pickle.load(stream)
    if not isinstance(bundle, RaceValueBundle):
        raise RacePortfolioInputError("RaceValueBundle artifact가 아닙니다.")
    return bundle

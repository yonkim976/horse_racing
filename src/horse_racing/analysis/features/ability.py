"""C2 group. Point-in-time, internally estimated horse ability ratings.

The rating is a multiplayer Elo variant.  A horse's observed score is its
pairwise fraction of opponents beaten (ties count as one half), and its
expected score is the mean logistic win probability against the same field.
Every row receives the rating *before* that race; updates are applied only
after every race on the date has been scored.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "C2. 자체 잠재 능력"
_SOURCE = "past_results 직접 계산 (공식 레이팅 미사용)"
_INITIAL_RATING = 1500.0
_GLOBAL_K = 32.0
_CONTEXT_K = 28.0
_DECAY_HALF_LIFE_DAYS = 730.0

FEATURES = [
    FeatureSpec(
        name="ability_elo_global",
        group=GROUP,
        description="과거 상대 착순으로 계산한 경주 전 multiplayer Elo",
        source=_SOURCE,
        lookback="전 기간, 장기 휴양 시 1500으로 완만히 회귀",
        null_policy="과거가 없으면 1500",
        leakage_note="현재 날짜 결과는 rating 출력 뒤 일괄 갱신",
    ),
    FeatureSpec(
        name="ability_elo_global_starts",
        group=GROUP,
        description="자체 global Elo 갱신에 사용된 과거 경주 수",
        source=_SOURCE,
        lookback="전 기간",
        null_policy="신마는 0",
        leakage_note="현재 경주 미포함",
    ),
    FeatureSpec(
        name="ability_elo_context",
        group=GROUP,
        description="경마장×거리대가 같은 과거 경주로 계산한 경주 전 Elo",
        source=_SOURCE,
        lookback="동일 경마장×거리대 전 기간",
        null_policy="해당 조건 첫 출전이면 1500",
        leakage_note="현재 날짜 결과는 rating 출력 뒤 일괄 갱신",
    ),
    FeatureSpec(
        name="ability_elo_context_starts",
        group=GROUP,
        description="동일 경마장×거리대 Elo 갱신에 사용된 과거 경주 수",
        source=_SOURCE,
        lookback="동일 조건 전 기간",
        null_policy="첫 출전이면 0",
        leakage_note="현재 경주 미포함",
    ),
    FeatureSpec(
        name="ability_elo_vs_field",
        group=GROUP,
        description="global Elo와 같은 경주 상대마 평균 Elo의 차이",
        source=_SOURCE,
        lookback="현재 출전표 + 과거 Elo",
        null_policy="단독 출전이면 0",
        leakage_note="현재 경주의 착순은 사용하지 않음",
    ),
    FeatureSpec(
        name="ability_elo_uncertainty",
        group=GROUP,
        description="과거 경주 수 기반 자체 Elo 불확실성 1/sqrt(starts+1)",
        source="ability_elo_global_starts 파생",
        lookback="전 기간",
        null_policy="신마는 1",
        leakage_note="현재 경주 미포함",
    ),
]

RatingState = tuple[float, int, date]


def _distance_band(distance_m: int | None) -> str:
    if distance_m is None or distance_m <= 1200:
        return "short"
    if distance_m <= 1600:
        return "middle"
    return "long"


def _decayed(state: RatingState | None, current_date: date) -> tuple[float, int]:
    if state is None:
        return _INITIAL_RATING, 0
    rating, starts, last_date = state
    days = max(0, (current_date - last_date).days)
    retention = 0.5 ** (days / _DECAY_HALF_LIFE_DAYS)
    return _INITIAL_RATING + (rating - _INITIAL_RATING) * retention, starts


def _expected(rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opponent_rating - rating) / 400.0))


def _observed_scores(positions: list[int]) -> list[float]:
    if len(positions) <= 1:
        return [0.5] * len(positions)
    scores: list[float] = []
    for index, position in enumerate(positions):
        points = 0.0
        for opponent_index, other in enumerate(positions):
            if opponent_index == index:
                continue
            points += 1.0 if position < other else 0.5 if position == other else 0.0
        scores.append(points / (len(positions) - 1))
    return scores


def _pre_race_ratings(past: pl.DataFrame) -> pl.DataFrame:
    required = {
        "race_entry_id",
        "race_id",
        "horse_id",
        "race_date",
        "meet_code",
        "distance_m",
        "finish_position",
    }
    if past.height == 0 or not required <= set(past.columns):
        return pl.DataFrame()

    ordered = past.sort("race_date", "race_id", "race_entry_id")
    global_states: dict[int, RatingState] = {}
    context_states: dict[tuple[int, str], RatingState] = {}
    output: list[dict[str, int | float]] = []

    for day_frame in ordered.partition_by("race_date", maintain_order=True):
        current_date = day_frame["race_date"][0]
        pending_global: dict[int, list[float]] = {}
        pending_context: dict[tuple[int, str], list[float]] = {}

        for race in day_frame.partition_by("race_id", maintain_order=True):
            rows = list(race.iter_rows(named=True))
            global_pre: list[tuple[float, int]] = []
            context_pre: list[tuple[float, int]] = []
            context_keys: list[tuple[int, str]] = []
            for row in rows:
                horse_id = int(row["horse_id"])
                context = f"{row['meet_code']}:{_distance_band(row['distance_m'])}"
                context_key = (horse_id, context)
                global_pre.append(_decayed(global_states.get(horse_id), current_date))
                context_pre.append(_decayed(context_states.get(context_key), current_date))
                context_keys.append(context_key)

            global_ratings = [item[0] for item in global_pre]
            context_ratings = [item[0] for item in context_pre]
            for index, row in enumerate(rows):
                opponents = global_ratings[:index] + global_ratings[index + 1 :]
                field_mean = (
                    sum(opponents) / len(opponents) if opponents else global_ratings[index]
                )
                starts = global_pre[index][1]
                output.append(
                    {
                        "race_entry_id": int(row["race_entry_id"]),
                        "ability_elo_global": global_ratings[index],
                        "ability_elo_global_starts": starts,
                        "ability_elo_context": context_ratings[index],
                        "ability_elo_context_starts": context_pre[index][1],
                        "ability_elo_vs_field": global_ratings[index] - field_mean,
                        "ability_elo_uncertainty": 1.0 / math.sqrt(starts + 1.0),
                    }
                )

            if any(row["finish_position"] is None for row in rows):
                continue
            positions = [int(row["finish_position"]) for row in rows]
            observed = _observed_scores(positions)
            for index, row in enumerate(rows):
                horse_id = int(row["horse_id"])
                global_expected = sum(
                    _expected(global_ratings[index], other)
                    for opponent_index, other in enumerate(global_ratings)
                    if opponent_index != index
                ) / max(1, len(global_ratings) - 1)
                context_expected = sum(
                    _expected(context_ratings[index], other)
                    for opponent_index, other in enumerate(context_ratings)
                    if opponent_index != index
                ) / max(1, len(context_ratings) - 1)
                global_delta = _GLOBAL_K * (observed[index] - global_expected)
                context_delta = _CONTEXT_K * (observed[index] - context_expected)

                if horse_id not in pending_global:
                    pending_global[horse_id] = [global_ratings[index], 0.0, 0.0]
                pending_global[horse_id][1] += global_delta
                pending_global[horse_id][2] += 1.0
                context_key = context_keys[index]
                if context_key not in pending_context:
                    pending_context[context_key] = [context_ratings[index], 0.0, 0.0]
                pending_context[context_key][1] += context_delta
                pending_context[context_key][2] += 1.0

        for horse_id, (base_rating, delta, count) in pending_global.items():
            previous_starts = global_states.get(horse_id, (_INITIAL_RATING, 0, current_date))[1]
            global_states[horse_id] = (
                base_rating + delta,
                previous_starts + int(count),
                current_date,
            )
        for context_key, (base_rating, delta, count) in pending_context.items():
            previous_starts = context_states.get(
                context_key, (_INITIAL_RATING, 0, current_date)
            )[1]
            context_states[context_key] = (
                base_rating + delta,
                previous_starts + int(count),
                current_date,
            )

    return pl.DataFrame(output)


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    ratings = _pre_race_ratings(sources.past_results)
    if ratings.height == 0:
        return frame.with_columns(
            pl.lit(_INITIAL_RATING).alias("ability_elo_global"),
            pl.lit(0, dtype=pl.Int64).alias("ability_elo_global_starts"),
            pl.lit(_INITIAL_RATING).alias("ability_elo_context"),
            pl.lit(0, dtype=pl.Int64).alias("ability_elo_context_starts"),
            pl.lit(0.0).alias("ability_elo_vs_field"),
            pl.lit(1.0).alias("ability_elo_uncertainty"),
        )
    result = frame.join(ratings, on="race_entry_id", how="left")
    return result.with_columns(
        pl.col("ability_elo_global").fill_null(_INITIAL_RATING),
        pl.col("ability_elo_global_starts").fill_null(0),
        pl.col("ability_elo_context").fill_null(_INITIAL_RATING),
        pl.col("ability_elo_context_starts").fill_null(0),
        pl.col("ability_elo_vs_field").fill_null(0.0),
        pl.col("ability_elo_uncertainty").fill_null(1.0),
    )

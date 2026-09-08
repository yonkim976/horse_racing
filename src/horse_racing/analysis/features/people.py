"""H그룹. 기수·조교사·조합 feature.

원천: 과거 `race_entries`+`race_results`(직접 집계), `jockey_changes`.
외부 통계 API 스냅샷은 누수라 사용하지 않는다. 과거 경주는 race_date 엄격히
이전만 쓰고, 당일 다른 경주 결과도 제외한다.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames, rolling_event_counts

GROUP = "H. 사람·조합"

_PAST_SOURCE = "past_results (race_entries+race_results 직접 집계)"
_LOOKBACK_STRICT = "race_date 엄격히 이전만 집계, 당일·미래 제외"

FEATURES = [
    FeatureSpec(
        name="jockey_starts_90d",
        group=GROUP,
        description="기수 최근 90일 출주수",
        source=_PAST_SOURCE,
        lookback="90일",
        null_policy="jockey_id null이면 null. 과거 출주 없으면 0",
        leakage_note=_LOOKBACK_STRICT,
    ),
    FeatureSpec(
        name="jockey_starts_365d",
        group=GROUP,
        description="기수 최근 365일 출주수",
        source=_PAST_SOURCE,
        lookback="365일",
        null_policy="jockey_id null이면 null. 과거 출주 없으면 0",
        leakage_note=_LOOKBACK_STRICT,
    ),
    FeatureSpec(
        name="jockey_win_rate_90d",
        group=GROUP,
        description="기수 최근 90일 승률 (1착 / 출주)",
        source=_PAST_SOURCE,
        lookback="90일",
        null_policy="jockey_id null이거나 출주 0이면 null",
        leakage_note=_LOOKBACK_STRICT,
    ),
    FeatureSpec(
        name="jockey_win_rate_365d",
        group=GROUP,
        description="기수 최근 365일 승률 (1착 / 출주)",
        source=_PAST_SOURCE,
        lookback="365일",
        null_policy="jockey_id null이거나 출주 0이면 null",
        leakage_note=_LOOKBACK_STRICT,
    ),
    FeatureSpec(
        name="jockey_top3_rate_90d",
        group=GROUP,
        description="기수 최근 90일 복승률 (3착 이내 / 출주)",
        source=_PAST_SOURCE,
        lookback="90일",
        null_policy="jockey_id null이거나 출주 0이면 null",
        leakage_note=_LOOKBACK_STRICT,
    ),
    FeatureSpec(
        name="trainer_starts_90d",
        group=GROUP,
        description="조교사 최근 90일 출주수",
        source=_PAST_SOURCE,
        lookback="90일",
        null_policy="trainer_id null이면 null. 과거 출주 없으면 0",
        leakage_note=_LOOKBACK_STRICT,
    ),
    FeatureSpec(
        name="trainer_starts_365d",
        group=GROUP,
        description="조교사 최근 365일 출주수",
        source=_PAST_SOURCE,
        lookback="365일",
        null_policy="trainer_id null이면 null. 과거 출주 없으면 0",
        leakage_note=_LOOKBACK_STRICT,
    ),
    FeatureSpec(
        name="trainer_win_rate_90d",
        group=GROUP,
        description="조교사 최근 90일 승률 (1착 / 출주)",
        source=_PAST_SOURCE,
        lookback="90일",
        null_policy="trainer_id null이거나 출주 0이면 null",
        leakage_note=_LOOKBACK_STRICT,
    ),
    FeatureSpec(
        name="trainer_win_rate_365d",
        group=GROUP,
        description="조교사 최근 365일 승률 (1착 / 출주)",
        source=_PAST_SOURCE,
        lookback="365일",
        null_policy="trainer_id null이거나 출주 0이면 null",
        leakage_note=_LOOKBACK_STRICT,
    ),
    FeatureSpec(
        name="trainer_top3_rate_90d",
        group=GROUP,
        description="조교사 최근 90일 복승률 (3착 이내 / 출주)",
        source=_PAST_SOURCE,
        lookback="90일",
        null_policy="trainer_id null이거나 출주 0이면 null",
        leakage_note=_LOOKBACK_STRICT,
    ),
    FeatureSpec(
        name="horse_jockey_starts",
        group=GROUP,
        description="이 말×이 기수 과거 조합 출주수",
        source=_PAST_SOURCE,
        lookback="전 기간",
        null_policy="jockey_id null이면 null. 과거 조합 없으면 0",
        leakage_note="현재 경주는 그룹 내 shift(1) cum count로 제외",
    ),
    FeatureSpec(
        name="horse_jockey_wins",
        group=GROUP,
        description="이 말×이 기수 과거 조합 승수",
        source=_PAST_SOURCE,
        lookback="전 기간",
        null_policy="jockey_id null이면 null. 과거 조합 없으면 0",
        leakage_note="현재 경주는 그룹 내 shift(1) cum count로 제외",
    ),
    FeatureSpec(
        name="horse_jockey_first",
        group=GROUP,
        description="이 말×이 기수 첫 조합 여부 (0/1)",
        source=_PAST_SOURCE,
        lookback="전 기간",
        null_policy="jockey_id null이면 null. 과거 출주 0이면 1, 아니면 0",
        leakage_note="현재 경주는 그룹 내 shift(1) cum count로 제외",
    ),
    FeatureSpec(
        name="jockey_changed",
        group=GROUP,
        description="이 경주에 기수변경 공지 존재 (0/1)",
        source="jockey_changes (horse_id+race_date+race_number)",
        lookback="-",
        null_policy="공지 없으면 0",
        leakage_note="공지는 경주 전 공개, observed_at은 수집시각이라 사용 안 함(T3)",
    ),
]

_PERSON_WINDOWS = (90, 365)
_ROLLING_VALUE_COLUMNS = {"win": "win", "top3": "top3"}


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    past = sources.past_results
    frame = _add_person_rolling(frame, past, key="jockey_id", prefix="jockey")
    frame = _add_person_rolling(frame, past, key="trainer_id", prefix="trainer")
    frame = _add_combo_features(frame, past)
    return _add_jockey_changed(frame, sources.jockey_changes)


def _person_events(past: pl.DataFrame, key: str) -> pl.DataFrame:
    if past.height == 0 or key not in past.columns:
        return pl.DataFrame()
    return past.filter(pl.col(key).is_not_null()).select(
        pl.col(key),
        pl.col("race_date").alias("event_date"),
        (pl.col("finish_position") == 1).cast(pl.Int64).alias("win"),
        (pl.col("finish_position") <= 3).cast(pl.Int64).alias("top3"),
    )


def _add_person_rolling(
    frame: pl.DataFrame,
    past: pl.DataFrame,
    *,
    key: str,
    prefix: str,
) -> pl.DataFrame:
    frame = rolling_event_counts(
        frame,
        _person_events(past, key),
        key=key,
        base_date_col="race_date",
        windows_days=_PERSON_WINDOWS,
        prefix=prefix,
        value_columns=_ROLLING_VALUE_COLUMNS,
    )
    n90, n365 = f"{prefix}_n_90d", f"{prefix}_n_365d"
    win90, win365 = f"{prefix}_win_90d", f"{prefix}_win_365d"
    top3_90 = f"{prefix}_top3_90d"
    valid = pl.col(key).is_not_null()
    frame = frame.with_columns(
        pl.when(valid).then(pl.col(n90)).otherwise(None).alias(f"{prefix}_starts_90d"),
        pl.when(valid).then(pl.col(n365)).otherwise(None).alias(f"{prefix}_starts_365d"),
        pl.when(valid & (pl.col(n90) > 0))
        .then(pl.col(win90) / pl.col(n90))
        .otherwise(None)
        .alias(f"{prefix}_win_rate_90d"),
        pl.when(valid & (pl.col(n365) > 0))
        .then(pl.col(win365) / pl.col(n365))
        .otherwise(None)
        .alias(f"{prefix}_win_rate_365d"),
        pl.when(valid & (pl.col(n90) > 0))
        .then(pl.col(top3_90) / pl.col(n90))
        .otherwise(None)
        .alias(f"{prefix}_top3_rate_90d"),
    )
    return frame.drop(
        n90,
        n365,
        win90,
        win365,
        top3_90,
        f"{prefix}_top3_365d",
    )


def _add_combo_features(frame: pl.DataFrame, past: pl.DataFrame) -> pl.DataFrame:
    if past.height == 0 or "race_entry_id" not in past.columns:
        starts: pl.Expr = pl.lit(0, dtype=pl.Int64)
        wins: pl.Expr = pl.lit(0, dtype=pl.Int64)
    else:
        combo = (
            past.filter(pl.col("jockey_id").is_not_null())
            .sort(["horse_id", "jockey_id", "race_date", "race_entry_id"])
            .with_columns(
                (pl.col("finish_position") == 1).cast(pl.Int64).alias("_win"),
            )
            .with_columns(
                (pl.col("race_entry_id").cum_count().over(["horse_id", "jockey_id"]) - 1).alias(
                    "horse_jockey_starts"
                ),
                pl.col("_win")
                .cum_sum()
                .over(["horse_id", "jockey_id"])
                .shift(1)
                .over(["horse_id", "jockey_id"])
                .fill_null(0)
                .alias("horse_jockey_wins"),
            )
            .select("race_entry_id", "horse_jockey_starts", "horse_jockey_wins")
            .unique("race_entry_id")
        )
        frame = frame.join(combo, on="race_entry_id", how="left")
        starts = pl.col("horse_jockey_starts").fill_null(0)
        wins = pl.col("horse_jockey_wins").fill_null(0)

    has_jockey = pl.col("jockey_id").is_not_null()
    return frame.with_columns(
        pl.when(has_jockey).then(starts).otherwise(None).cast(pl.Int64).alias("horse_jockey_starts"),
        pl.when(has_jockey).then(wins).otherwise(None).cast(pl.Int64).alias("horse_jockey_wins"),
        pl.when(has_jockey)
        .then((starts == 0).cast(pl.Int64))
        .otherwise(None)
        .alias("horse_jockey_first"),
    )


def _add_jockey_changed(frame: pl.DataFrame, changes: pl.DataFrame) -> pl.DataFrame:
    if changes.height == 0:
        return frame.with_columns(pl.lit(0, dtype=pl.Int64).alias("jockey_changed"))
    flags = (
        changes.select("horse_id", "race_date", "race_number")
        .unique()
        .with_columns(pl.lit(1, dtype=pl.Int64).alias("jockey_changed"))
    )
    return frame.join(flags, on=["horse_id", "race_date", "race_number"], how="left").with_columns(
        pl.col("jockey_changed").fill_null(0)
    )

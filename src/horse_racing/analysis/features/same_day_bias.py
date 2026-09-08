"""Intraday track-bias priors using only races completed before prediction time."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames, as_date

GROUP = "D2. 당일 실시간 주로 편향"
_RESULT_BUFFER_MS = 20 * 60 * 1000
_PAR_LOOKBACK_DAYS = 730
_MIN_PAR_RACES = 12
_SHRINK_RACES = 3.0

FEATURES = [
    FeatureSpec(
        name="live_bias_races",
        group=GROUP,
        description="예측시각 20분 전까지 예정됐던 같은 날·경마장 완료 경주 수",
        source="과거 races.scheduled_at_ms + 완료 결과",
        lookback="같은 날 앞 경주",
        null_policy="앞 경주가 없으면 0",
        leakage_note="prior scheduled_at + 20분 <= prediction_at인 경주만 사용",
    ),
    FeatureSpec(
        name="live_bias_reliability",
        group=GROUP,
        description="당일 편향 표본 신뢰도 n/(n+3)",
        source="live_bias_races",
        lookback="같은 날 앞 경주",
        null_policy="앞 경주가 없으면 0",
        leakage_note="예측시각 이전 자격 경주만 사용",
    ),
    FeatureSpec(
        name="live_track_speed_variant",
        group=GROUP,
        description="앞 경주 top3 속도의 과거 동일 경마장·거리 par 대비 로그 편차",
        source="앞 경주 finish_time + 과거 2년 par",
        lookback="당일 앞 경주, par는 이전 날짜 2년",
        null_policy="par 표본 부족이면 0으로 수축",
        leakage_note="현재·이후 경주 결과 제외",
    ),
    FeatureSpec(
        name="live_front_bias",
        group=GROUP,
        description="앞 경주 top3의 S1F 위치로 추정한 당일 선행 유리 정도",
        source="앞 경주 S1F position",
        lookback="같은 날 앞 경주",
        null_policy="S1F가 없으면 해당 경주 제외",
        leakage_note="현재·이후 경주 구간결과 제외",
    ),
    FeatureSpec(
        name="live_inner_bias",
        group=GROUP,
        description="앞 경주 top3 게이트 위치로 추정한 당일 내측 유리 정도",
        source="앞 경주 gate_number / starters",
        lookback="같은 날 앞 경주",
        null_policy="게이트가 없으면 해당 경주 제외",
        leakage_note="현재·이후 경주 착순 제외",
    ),
    FeatureSpec(
        name="live_style_fit",
        group=GROUP,
        description="당일 선행 편향과 해당 말의 과거 선행 성향 적합도",
        source="live_front_bias × early_pos_pct_avg5",
        lookback="당일 앞 경주 + 말 최근 5경주",
        leakage_note="두 입력 모두 예측시각 이전",
    ),
    FeatureSpec(
        name="live_gate_fit",
        group=GROUP,
        description="당일 내측 편향과 해당 말의 상대 게이트 적합도",
        source="live_inner_bias × horse_number_pct",
        lookback="당일 앞 경주 + 현재 출전표",
        leakage_note="현재 경주 결과 미사용",
    ),
    FeatureSpec(
        name="live_finish_energy_fit",
        group=GROUP,
        description="당일 선행 편향과 해당 말의 초후반 에너지 균형 상호작용",
        source="live_front_bias × energy_early_late_balance_avg5",
        lookback="당일 앞 경주 + 최근 5경주",
        leakage_note="현재 경주 결과 미사용",
    ),
]


@dataclass(frozen=True)
class _RaceBias:
    race_id: int
    race_date: date
    meet_code: int
    distance_m: int
    available_at_ms: int
    top3_speed: float | None
    front_bias: float | None
    inner_bias: float | None
    speed_variant: float | None = None


def _effective_s1f(sections: pl.DataFrame) -> pl.DataFrame:
    if sections.height == 0:
        return pl.DataFrame()
    usable = sections.filter(pl.col("section_code") == "S1F")
    if usable.height == 0:
        return pl.DataFrame()
    position = pl.when(pl.col("position").is_null() & pl.col("elapsed_time_ms").is_not_null()).then(
        pl.col("elapsed_time_ms").rank("average").over("race_id")
    ).otherwise(pl.col("position"))
    return usable.select("race_id", "horse_id", position.cast(pl.Float64).alias("_s1f"))


def _race_biases(past: pl.DataFrame, sections: pl.DataFrame) -> list[_RaceBias]:
    required = {
        "race_id",
        "horse_id",
        "race_date",
        "meet_code",
        "distance_m",
        "scheduled_at_ms",
        "finish_position",
        "finish_time_ms",
        "gate_number",
        "starters",
    }
    if past.height == 0 or not required <= set(past.columns):
        return []
    s1f = _effective_s1f(sections)
    rows = past.join(s1f, on=["race_id", "horse_id"], how="left") if s1f.height else past
    output: list[_RaceBias] = []
    for race in rows.partition_by("race_id", maintain_order=False):
        first = race.row(0, named=True)
        scheduled = first.get("scheduled_at_ms")
        if scheduled is None:
            continue
        starters = max(2, int(first.get("starters") or race.height))
        top3 = race.filter(pl.col("finish_position") <= 3)
        speeds = []
        for row in top3.iter_rows(named=True):
            elapsed = row.get("finish_time_ms")
            if elapsed is not None and float(elapsed) > 0:
                speeds.append(float(row["distance_m"]) / (float(elapsed) / 1000.0))
        early = (
            [
                (float(value) - 1.0) / (starters - 1.0)
                for value in top3["_s1f"].drop_nulls().to_list()
            ]
            if "_s1f" in top3.columns
            else []
        )
        gates = [
            (float(value) - 1.0) / (starters - 1.0)
            for value in top3["gate_number"].drop_nulls().to_list()
            if float(value) > 0
        ]
        output.append(
            _RaceBias(
                race_id=int(first["race_id"]),
                race_date=first["race_date"],
                meet_code=int(first["meet_code"]),
                distance_m=int(first["distance_m"]),
                available_at_ms=int(scheduled) + _RESULT_BUFFER_MS,
                top3_speed=float(median(speeds)) if speeds else None,
                front_bias=0.5 - float(sum(early) / len(early)) if early else None,
                inner_bias=0.5 - float(sum(gates) / len(gates)) if gates else None,
            )
        )
    return output


def _attach_speed_variants(races: list[_RaceBias]) -> list[_RaceBias]:
    histories: dict[tuple[int, int], deque[tuple[date, float]]] = defaultdict(deque)
    by_day: dict[date, list[_RaceBias]] = defaultdict(list)
    for race in races:
        by_day[race.race_date].append(race)
    output: list[_RaceBias] = []
    for current_date in sorted(by_day):
        for race in by_day[current_date]:
            history = histories[(race.meet_code, race.distance_m)]
            cutoff = current_date - timedelta(days=_PAR_LOOKBACK_DAYS)
            while history and history[0][0] < cutoff:
                history.popleft()
            values = [value for _, value in history]
            variant = None
            if race.top3_speed is not None and len(values) >= _MIN_PAR_RACES:
                par = median(values)
                if par > 0:
                    variant = 100.0 * math.log(race.top3_speed / par)
            output.append(
                _RaceBias(
                    **{
                        **race.__dict__,
                        "speed_variant": variant,
                    }
                )
            )
        # A day's results never enter another race's historical par on that date.
        for race in by_day[current_date]:
            if race.top3_speed is not None:
                histories[(race.meet_code, race.distance_m)].append(
                    (current_date, race.top3_speed)
                )
    return output


def _zero_features(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(0, dtype=pl.Int64).alias("live_bias_races"),
        *(pl.lit(0.0).alias(spec.name) for spec in FEATURES if spec.name != "live_bias_races"),
    )


def _shrunk_mean(races: list[_RaceBias], attribute: str, reliability: float) -> float:
    values = [
        float(value)
        for race in races
        if (value := getattr(race, attribute)) is not None
    ]
    if not values:
        return 0.0
    return float(sum(values) / len(values) * reliability)


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    if "prediction_at_ms" not in frame.columns:
        return _zero_features(frame)
    past = as_date(sources.past_results, "race_date")
    sections = as_date(sources.sections, "race_date")
    races = _attach_speed_variants(_race_biases(past, sections))
    if not races:
        return _zero_features(frame)

    by_context: dict[tuple[date, int], list[_RaceBias]] = defaultdict(list)
    for race in races:
        by_context[(race.race_date, race.meet_code)].append(race)
    for values in by_context.values():
        values.sort(key=lambda item: (item.available_at_ms, item.race_id))

    output: list[dict[str, float | int]] = []
    targets = frame.select(
        "race_entry_id", "race_date", "meet_code", "prediction_at_ms"
    ).iter_rows(named=True)
    for target in targets:
        eligible = [
            race
            for race in by_context.get((target["race_date"], int(target["meet_code"])), [])
            if race.available_at_ms <= int(target["prediction_at_ms"])
        ]
        count = len(eligible)
        reliability = count / (count + _SHRINK_RACES) if count else 0.0
        output.append(
            {
                "race_entry_id": int(target["race_entry_id"]),
                "live_bias_races": count,
                "live_bias_reliability": reliability,
                "live_track_speed_variant": _shrunk_mean(
                    eligible, "speed_variant", reliability
                ),
                "live_front_bias": _shrunk_mean(eligible, "front_bias", reliability),
                "live_inner_bias": _shrunk_mean(eligible, "inner_bias", reliability),
            }
        )
    result = frame.join(pl.DataFrame(output), on="race_entry_id", how="left")
    frontness = 0.5 - pl.col("early_pos_pct_avg5").fill_null(0.5)
    innerness = 0.5 - pl.col("horse_number_pct").fill_null(0.5)
    energy = pl.col("energy_early_late_balance_avg5").fill_null(0.0)
    return result.with_columns(
        (pl.col("live_front_bias") * frontness).alias("live_style_fit"),
        (pl.col("live_inner_bias") * innerness).alias("live_gate_fit"),
        (pl.col("live_front_bias") * energy).alias("live_finish_energy_fit"),
    )

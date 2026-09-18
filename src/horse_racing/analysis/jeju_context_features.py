"""Strictly lagged race-context and form features for sealed Jeju starters.

The public builder accepts plain dictionaries so the leakage contract can be
tested without a database.  A target row is evaluated using only that horse's
history and the current race's entry declarations/prior states.  Historical
outcomes, section ranks, burden, body weight, jockey identity, and weather are
cut off at ``event_date - 2 days``.  The current race's result/weather/weight
are never read by this module.
"""

from __future__ import annotations

import bisect
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, timedelta

import numpy as np

CUTOFF_DAYS = 2

CONTEXT_FEATURES = [
    "rival_global_elo_mean",
    "rival_global_elo_std",
    "rival_global_elo_max",
    "rival_global_elo_gap",
    "rival_distance_elo_mean",
    "rival_distance_elo_max",
    "rival_distance_elo_gap",
    "declared_horse_number_fraction",
    "historical_early_front_rate",
    "rival_early_pressure_count",
    "rival_early_pressure_mean",
    "field_early_ability_percentile",
    "jockey_early_front_rate",
    "current_minus_previous_elo",
    "previous_rival_elo_mean_3",
    "current_vs_previous_rival_elo",
    "lower_number_early_pressure_count",
    "higher_number_early_pressure_count",
]

FORM_FEATURES = [
    "last_burden_kg",
    "current_minus_last_burden_kg",
    "last_body_weight_kg",
    "body_weight_delta_kg",
    "body_weight_trend_3",
    "last_early_rank",
    "last_late_rank",
    "last_early_late_gain",
    "closing_speed_quality_mean_3",
    "late_rank_mean_3",
    "early_late_gain_mean_3",
    "early_rank_percentile_3",
    "late_rank_percentile_3",
    "progression_last3_vs_prev3",
    "best_last5_performance",
    "poor_last_but_good_late",
    "wet_performance_mean",
    "wet_performance_count",
    "dry_performance_mean",
    "dry_performance_count",
    "history_time_minus_same_race_median",
    "jockey_changed",
]

FEATURES = CONTEXT_FEATURES + FORM_FEATURES
FEATURE_DEFINITIONS = {
    "rival_global_elo_mean": ("현재 출전 상대(자신 제외)의 T-2 사전 global Elo 평균, Elo 점수"),
    "rival_global_elo_std": ("현재 상대 사전 global Elo 모집단 표준편차, Elo 점수"),
    "rival_global_elo_max": ("현재 상대 사전 global Elo 최댓값, Elo 점수"),
    "rival_global_elo_gap": ("자신의 사전 global Elo - 상대 최댓값, Elo 점수"),
    "rival_distance_elo_mean": ("현재 거리에서 상대들의 사전 distance Elo 평균, Elo 점수"),
    "rival_distance_elo_max": ("현재 거리에서 상대들의 사전 distance Elo 최댓값, Elo 점수"),
    "rival_distance_elo_gap": ("자신의 distance Elo - 상대 distance Elo 최댓값"),
    "declared_horse_number_fraction": (
        "(선언 출주번호-1)/(현재 필드에서 확인된 "
        "최대 선언번호-1). 취소로 빈 번호 보존. "
        "물리 게이트 확정 아님. 번호 미확인/최대1이"
        "면 결측"
    ),
    "historical_early_front_rate": (
        "자신의 T-2까지 과거 유효 초반 통과순위 중 3위 이내 비율. 거리 혼합, 관측없으면 결측"
    ),
    "rival_early_pressure_count": (
        "초반 상위3 비율>=0.5인 현재 상대 수. 이력 알려진 상대만. 전부 미확인하면 결측"
    ),
    "rival_early_pressure_mean": ("현재 상대의 과거 초반 상위3 비율 평균. 알려진 상대만"),
    "field_early_ability_percentile": (
        "현재 필드의 초반 상위3 비율 중 자기 이하 비율. 동률 포함 ECDF, 0~1"
    ),
    "jockey_early_front_rate": (
        "선언 기수의 T-2까지 초반 상위3 비율. 당시까지 알려진 이름-ID만 연결, 다중ID 불명확 시 결측"
    ),
    "current_minus_previous_elo": (
        "현재 자기 global Elo - 최근 과거 출전 당시 자기 사전 Elo. 최근 변화 대용치"
    ),
    "previous_rival_elo_mean_3": (
        "최근 과거3회 출전의 상대 사전 global Elo 평균을 다시 평균. 없으면 결측"
    ),
    "current_vs_previous_rival_elo": (
        "현재 상대 평균 global Elo - 최근3회 상대 평균. 양수면 이전보다 강한 편성 추정"
    ),
    "lower_number_early_pressure_count": (
        "자신보다 낮은 선언 출주번호이고 과거 초반 상위3 비율>=0.5인 상대 수. 물리 안쪽 확정 아님"
    ),
    "higher_number_early_pressure_count": (
        "자신보다 높은 선언 출주번호이고 과거 초반 상위3 비율>=0.5인 상대 수. 물리 바깥쪽 확정 아님"
    ),
    "last_burden_kg": ("T-2까지 과거 출전 중 마지막 유효 실제 부담중량 kg"),
    "current_minus_last_burden_kg": ("현재 선언 부담중량 - 과거 마지막 유효 실제 부담중량 kg"),
    "last_body_weight_kg": ("T-2까지 과거 출전의 마지막 유효 마체중 kg. 당일 체중 아님"),
    "body_weight_delta_kg": ("과거 마지막 두 유효 마체중의 차이 kg. 현재 경주의 증감 아님"),
    "body_weight_trend_3": ("과거 최근 최대3개 유효 체중의 (마지막-첫값)/(관측수-1), kg/관측"),
    "last_early_rank": ("직전 출전의 유효 S1F 통과순위. 1..당시 출전수만 유효"),
    "last_late_rank": ("직전 출전의 결승200m 전 G1F 통과순위. 막판200m 구간 속도 순위와 다름"),
    "last_early_late_gain": ("직전 S1F 통과순위-G1F 통과순위. 양수는 두 지점 사이 순위 상승"),
    "closing_speed_quality_mean_3": (
        "최근3회 출전의 최종200m 구간시간 상대속도"
        " 평균. 같은 과거 경주의 정상/유효 구간시간"
        "에서 빠를수록1, 평균동률, 관측2개 이상"
    ),
    "late_rank_mean_3": ("최근3회 출전의 유효 G1F 통과순위 평균"),
    "early_late_gain_mean_3": ("최근3회 출전의 유효 S1F순위-G1F순위 평균"),
    "early_rank_percentile_3": ("최근3회 출전의 1-(S1F순위-1)/(당시출전수-1) 평균"),
    "late_rank_percentile_3": ("최근3회 출전의 1-(G1F순위-1)/(당시출전수-1) 평균"),
    "progression_last3_vs_prev3": (
        "최근3회 상대결승점수 평균 - 그전3회 평균."
        " 6회 출전 필요. 상대결승점수=1-(착순-1"
        ")/(출전수-1). DQ/DNF 점수 결측"
    ),
    "best_last5_performance": (
        "최근5회 출전 중 정상 상대결승점수 최댓값. 한 번 부진했다고 이전 좋은 수행을 삭제하지 않음"
    ),
    "poor_last_but_good_late": (
        "직전 정상 상대결승점수<=0.25 이면서 최종"
        "200m 상대속도>=0.75면1. 둘다알려진비"
        "해당0, 미확인 결측. 포기 의도 라벨 아님"
    ),
    "wet_performance_mean": (
        "과거 함수율10~100% 경주의 정상 상대결승"
        "점수 평균. 거리/등급 혼합 관측요약, 젖은주"
        "로 인과효과 아님"
    ),
    "wet_performance_count": ("wet_performance_mean에 사용한 유효 정상 관측 수"),
    "dry_performance_mean": (
        "과거 함수율1~9%(건조+양호)의 정상 상대결승점수 평균. 현재 날씨 입력 아님"
    ),
    "dry_performance_count": ("dry_performance_mean에 사용한 관측 수. 함수율0/미확인 제외"),
    "history_time_minus_same_race_median": (
        "최근3회 과거 정상 유효 결승시간 - 같은 과"
        "거 경주의 유효시간 중앙값 평균, ms. 유효"
        "2마리 이상. 주로뿐 아니라 편성/전개도 섞인"
        " 상대기록"
    ),
    "jockey_changed": (
        "현재 선언 기수 이름과 직전 실제 기수 이름이"
        " 다르면1. 어느 이름이든 미확인 시 결측. "
        "현재 실제 결과 기수 대입 없음"
    ),
}

_BODY_WEIGHT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:\(([+-]?\d+(?:\.\d+)?)\))?\s*$")
_WET_WORDS = ("비", "소나기", "폭우", "강우")


def parse_body_weight(value) -> float | None:
    """Parse ``wgHr`` values such as ``264(+2)`` into the base body weight."""

    if value is None or isinstance(value, bool):
        return None
    match = _BODY_WEIGHT.match(str(value))
    if not match:
        return None
    number = float(match.group(1))
    return number if math.isfinite(number) and 100.0 <= number <= 1000.0 else None


def parse_track_moisture(value) -> float | None:
    """Extract only an explicit percent from historical API track text."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", str(value or ""))
    if match is None:
        return None
    value = float(match.group(1))
    return value if 1 <= value <= 100 else None


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    text = str(value).replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"invalid event date: {value!r}")
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean(values: Iterable[float]) -> float:
    values = [x for x in values if x is not None and math.isfinite(x)]
    return float(np.mean(values)) if values else float("nan")


def _std(values: Iterable[float]) -> float:
    values = [x for x in values if x is not None and math.isfinite(x)]
    return float(np.std(values)) if values else float("nan")


def _weather_class(row: Mapping) -> str | None:
    moisture = _number(row.get("track_moisture_percent"))
    if moisture is None or not 1 <= moisture <= 100:
        return None
    return "wet" if moisture >= 10.0 else "dry"


def _performance(row: Mapping) -> float | None:
    """Return relative finish quality; DQ/DNF rows intentionally return None."""

    position = _number(row.get("finish_position"))
    field_size = _number(row.get("field_size"))
    if position is None or field_size is None or position < 1 or field_size < 2:
        return None
    if position > field_size:
        return None
    return float(1.0 - (position - 1.0) / max(field_size - 1.0, 1.0))


def _rank_value(row: Mapping, key: str) -> float | None:
    value = _number(row.get(key))
    field = _number(row.get("field_size"))
    return value if value is not None and field is not None and 1 <= value <= field else None


def _front_rate(rows: Iterable[Mapping]) -> float:
    ranks = [_rank_value(row, "early_rank") for row in rows]
    ranks = [x for x in ranks if x is not None]
    return float(sum(x <= 3 for x in ranks) / len(ranks)) if ranks else float("nan")


def _jockey_key(row: Mapping, prefix: str = ""):
    identity = row.get(prefix + "jockey_id")
    name = row.get(prefix + "jockey_name")
    if identity not in (None, ""):
        return ("id", str(identity))
    if name not in (None, ""):
        return ("name", str(name).strip())
    return None


def _last_rows(rows: list[Mapping], n: int) -> list[Mapping]:
    return rows[-n:] if rows else []


def _rank_quality(rows: Iterable[Mapping], key: str) -> float:
    values = []
    for row in rows:
        rank = _rank_value(row, key)
        field = _number(row.get("field_size"))
        if rank is not None and field is not None and field >= 2:
            values.append(1.0 - (rank - 1.0) / max(field - 1.0, 1.0))
    return _mean(values)


def _summarize(target: Mapping, prior: list[Mapping], jockey_prior: list[Mapping]) -> dict:
    current_burden = _number(target.get("declared_burden_kg"))
    early = [row for row in prior if _rank_value(row, "early_rank") is not None]
    early_rate = _front_rate(prior)
    latest = prior[-1] if prior else None
    valid_burden = [(_number(row.get("burden_kg")), row) for row in prior]
    valid_burden = [(value, row) for value, row in valid_burden if value is not None]
    valid_weights = [(_number(row.get("body_weight_kg")), row) for row in prior]
    valid_weights = [(value, row) for value, row in valid_weights if value is not None]
    last_burden = valid_burden[-1][0] if valid_burden else float("nan")
    last_weight = valid_weights[-1][0] if valid_weights else float("nan")
    weight_delta = (
        valid_weights[-1][0] - valid_weights[-2][0] if len(valid_weights) >= 2 else float("nan")
    )
    recent_weights = valid_weights[-3:]
    weight_trend = (
        (recent_weights[-1][0] - recent_weights[0][0]) / (len(recent_weights) - 1)
        if len(recent_weights) >= 2
        else float("nan")
    )
    recent3 = _last_rows(prior, 3)
    recent5 = _last_rows(prior, 5)
    recent_valid = [row for row in recent3 if _performance(row) is not None]
    prior3 = prior[-6:-3] if len(prior) >= 6 else []
    perf_recent = [_performance(row) for row in recent3]
    perf_recent = [x for x in perf_recent if x is not None]
    perf_prev = [_performance(row) for row in prior3]
    perf_prev = [x for x in perf_prev if x is not None]
    latest_perf = _performance(latest) if latest else None
    latest_late = _number(latest.get("closing_speed_quality")) if latest else None
    latest_field = _number(latest.get("field_size")) if latest else None
    poor_late = (
        1.0
        if latest_perf is not None
        and latest_perf <= 0.25
        and latest_late is not None
        and latest_field is not None
        and latest_late >= 0.75
        else 0.0
        if latest_perf is not None and latest_late is not None and latest_field is not None
        else float("nan")
    )
    gains = []
    for row in recent3:
        early_rank = _rank_value(row, "early_rank")
        late_rank = _rank_value(row, "late_rank")
        if early_rank is not None and late_rank is not None:
            gains.append(early_rank - late_rank)
    latest_gain = float("nan")
    if latest is not None:
        latest_early = _rank_value(latest, "early_rank")
        latest_late = _rank_value(latest, "late_rank")
        if latest_early is not None and latest_late is not None:
            latest_gain = latest_early - latest_late
    time_deltas = [
        _number(row.get("time_minus_race_median_ms"))
        for row in recent3
        if _number(row.get("time_minus_race_median_ms")) is not None
    ]
    wet = [_performance(row) for row in prior if _weather_class(row) == "wet"]
    wet = [x for x in wet if x is not None]
    dry = [_performance(row) for row in prior if _weather_class(row) == "dry"]
    dry = [x for x in dry if x is not None]
    previous_elo = _number(latest.get("global_elo_pre")) if latest else None
    current_elo = _number(target.get("global_elo_pre"))
    current_jockey = target.get("jockey_name")
    previous_jockey = latest.get("jockey_name") if latest else None
    jockey_changed = (
        float(current_jockey != previous_jockey)
        if current_jockey is not None and previous_jockey is not None
        else float("nan")
    )
    jockey_rate = _front_rate(jockey_prior)
    return {
        "historical_early_front_rate": early_rate,
        "jockey_early_front_rate": jockey_rate,
        "current_minus_previous_elo": current_elo - previous_elo
        if current_elo is not None and previous_elo is not None
        else float("nan"),
        "last_burden_kg": last_burden,
        "current_minus_last_burden_kg": current_burden - last_burden
        if current_burden is not None and math.isfinite(last_burden)
        else float("nan"),
        "last_body_weight_kg": last_weight,
        "body_weight_delta_kg": weight_delta,
        "body_weight_trend_3": weight_trend,
        "last_early_rank": _rank_value(latest, "early_rank") if latest else float("nan"),
        "last_late_rank": _rank_value(latest, "late_rank") if latest else float("nan"),
        "last_early_late_gain": latest_gain,
        "closing_speed_quality_mean_3": _mean(
            _number(row.get("closing_speed_quality")) for row in recent3
        ),
        "late_rank_mean_3": _mean(_rank_value(row, "late_rank") for row in recent3),
        "early_late_gain_mean_3": _mean(gains),
        "early_rank_percentile_3": _rank_quality(recent3, "early_rank"),
        "late_rank_percentile_3": _rank_quality(recent3, "late_rank"),
        "progression_last3_vs_prev3": _mean(perf_recent) - _mean(perf_prev)
        if perf_recent and perf_prev
        else float("nan"),
        "best_last5_performance": max(
            (_performance(row) for row in recent5 if _performance(row) is not None),
            default=float("nan"),
        ),
        "poor_last_but_good_late": poor_late,
        "wet_performance_mean": _mean(wet),
        "wet_performance_count": float(len(wet)),
        "dry_performance_mean": _mean(dry),
        "dry_performance_count": float(len(dry)),
        "history_time_minus_same_race_median": _mean(time_deltas),
        "jockey_changed": jockey_changed,
        "_early_count": float(len(early)),
        "_early_prior_rows": early,
        "_recent_valid": recent_valid,
    }


def build_features(targets: Iterable[Mapping], history: Iterable[Mapping]) -> list[dict]:
    """Build context/form features from target and strictly historical rows.

    Required target keys are ``entry_id``, ``race_id``, ``event_date``,
    ``horse_id``, ``horse_number``, ``field_size``, and prior-state fields
    ``global_elo_pre``/``distance_elo_pre``.  Historical rows use the same
    horse/race keys plus outcome and section fields.  ``targets`` may contain
    current declarations, but current outcome/weather/body weight fields are
    ignored by construction.
    """

    target_rows = [dict(row) for row in targets]
    history_rows = [dict(row) for row in history]
    for row in target_rows + history_rows:
        row["event_date"] = _as_date(row["event_date"])
    by_horse: defaultdict[str, list[dict]] = defaultdict(list)
    by_jockey: defaultdict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in history_rows:
        by_horse[str(row.get("horse_id"))].append(row)
        key = _jockey_key(row)
        if key is not None:
            by_jockey[key].append(row)
        name = row.get("jockey_name")
        if name not in (None, ""):
            if key != ("name", str(name).strip()):
                by_jockey[("name", str(name).strip())].append(row)
    for rows in [*by_horse.values(), *by_jockey.values()]:
        rows.sort(key=lambda item: (item["event_date"], int(item.get("entry_id", 0))))
    date_index = {
        id(rows): [item["event_date"] for item in rows]
        for rows in [*by_horse.values(), *by_jockey.values()]
    }
    target_rows.sort(key=lambda item: (item["event_date"], int(item.get("entry_id", 0))))
    race_rows: defaultdict[object, list[dict]] = defaultdict(list)
    summaries: dict[int, dict] = {}
    for target in target_rows:
        cutoff = target["event_date"] - timedelta(days=CUTOFF_DAYS)
        horse_rows = by_horse.get(str(target.get("horse_id")), [])
        horse_dates = date_index.get(id(horse_rows), [])
        prior = horse_rows[: bisect.bisect_right(horse_dates, cutoff)]
        target_jockey_name = target.get("jockey_name")
        target_jockey_name = (
            str(target_jockey_name).strip() if target_jockey_name not in (None, "") else None
        )
        named_rows = by_jockey.get(("name", target_jockey_name), [])
        named_prior = named_rows[: bisect.bisect_right(date_index.get(id(named_rows), []), cutoff)]
        known_ids = {
            str(row["jockey_id"]) for row in named_prior if row.get("jockey_id") not in (None, "")
        }
        target_for_summary = dict(target)
        target_for_summary.pop("jockey_id", None)
        if len(known_ids) == 1:
            target_for_summary["jockey_id"] = next(iter(known_ids))
            jockey_rows = by_jockey.get(_jockey_key(target_for_summary), [])
            jockey_prior = jockey_rows[
                : bisect.bisect_right(date_index.get(id(jockey_rows), []), cutoff)
            ]
        elif not known_ids:
            jockey_prior = named_prior
        else:
            jockey_prior = []  # Historical ambiguous identity stays unknown.
        summary = _summarize(target_for_summary, prior, jockey_prior)
        summary["_prior"] = prior
        summaries[int(target["entry_id"])] = summary
        enriched = dict(target)
        enriched.update(summary)
        race_rows[target.get("race_id")].append(enriched)
    outputs = []
    for target in target_rows:
        summary = summaries[int(target["entry_id"])]
        current_elo = _number(target.get("global_elo_pre"))
        current_distance_elo = _number(target.get("distance_elo_pre"))
        rivals = [
            row for row in race_rows[target.get("race_id")] if row["entry_id"] != target["entry_id"]
        ]
        rival_global = [_number(row.get("global_elo_pre")) for row in rivals]
        rival_global = [x for x in rival_global if x is not None]
        rival_distance = [_number(row.get("distance_elo_pre")) for row in rivals]
        rival_distance = [x for x in rival_distance if x is not None]
        rival_rates = [row["historical_early_front_rate"] for row in rivals]
        rival_rates = [x for x in rival_rates if math.isfinite(x)]
        own_rate = summary["historical_early_front_rate"]
        field_rates = [
            row["historical_early_front_rate"]
            for row in race_rows[target.get("race_id")]
            if math.isfinite(row["historical_early_front_rate"])
        ]
        own_percentile = float("nan")
        if math.isfinite(own_rate) and field_rates:
            own_percentile = float(
                sum(value <= own_rate for value in field_rates) / len(field_rates)
            )
        horse_number = _number(target.get("horse_number"))
        declared_numbers = [
            _number(row.get("horse_number")) for row in race_rows[target.get("race_id")]
        ]
        declared_numbers = [value for value in declared_numbers if value is not None]
        max_number = max(declared_numbers, default=float("nan"))
        previous_rivals = _mean(
            _number(row.get("rival_elo_mean")) for row in summary["_prior"][-3:]
        )

        def side_pressure(lower, horse_number=horse_number, rivals=rivals):
            if horse_number is None:
                return float("nan")
            known = [
                row
                for row in rivals
                if _number(row.get("horse_number")) is not None
                and math.isfinite(row["historical_early_front_rate"])
            ]
            return (
                float(
                    sum(
                        row["historical_early_front_rate"] >= 0.5
                        and (
                            (row["horse_number"] < horse_number)
                            if lower
                            else (row["horse_number"] > horse_number)
                        )
                        for row in known
                    )
                )
                if known
                else float("nan")
            )

        output = {name: float("nan") for name in FEATURES}
        output.update(
            {
                "entry_id": target["entry_id"],
                "rival_global_elo_mean": _mean(rival_global),
                "rival_global_elo_std": _std(rival_global),
                "rival_global_elo_max": max(rival_global, default=float("nan")),
                "rival_global_elo_gap": current_elo - max(rival_global)
                if current_elo is not None and rival_global
                else float("nan"),
                "rival_distance_elo_mean": _mean(rival_distance),
                "rival_distance_elo_max": max(rival_distance, default=float("nan")),
                "rival_distance_elo_gap": current_distance_elo - max(rival_distance)
                if current_distance_elo is not None and rival_distance
                else float("nan"),
                "declared_horse_number_fraction": (horse_number - 1.0) / (max_number - 1.0)
                if horse_number is not None and math.isfinite(max_number) and max_number > 1
                else float("nan"),
                "historical_early_front_rate": own_rate,
                "rival_early_pressure_count": float(sum(value >= 0.5 for value in rival_rates))
                if rival_rates
                else float("nan"),
                "rival_early_pressure_mean": _mean(rival_rates),
                "field_early_ability_percentile": own_percentile,
                "jockey_early_front_rate": summary["jockey_early_front_rate"],
                "current_minus_previous_elo": summary["current_minus_previous_elo"],
                "previous_rival_elo_mean_3": previous_rivals,
                "current_vs_previous_rival_elo": _mean(rival_global) - previous_rivals,
                "lower_number_early_pressure_count": side_pressure(True),
                "higher_number_early_pressure_count": side_pressure(False),
            }
        )
        output.update({name: summary[name] for name in FORM_FEATURES})
        outputs.append(output)
    return outputs


__all__ = [
    "CONTEXT_FEATURES",
    "FORM_FEATURES",
    "FEATURES",
    "FEATURE_DEFINITIONS",
    "CUTOFF_DAYS",
    "build_features",
    "parse_body_weight",
]

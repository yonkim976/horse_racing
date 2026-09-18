"""Render a self-contained detailed HTML report from a sealed Jeju forecast."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import html
import json
import pickle
import sqlite3
from datetime import date, datetime
from itertools import combinations
from pathlib import Path

import numpy as np
import polars as pl
from predict_jeju_live_hy_r_form import FEATURE_LABELS

from horse_racing.analysis.jeju_hybrid_evaluation import distribution

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DB = (
    ROOT / "data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3"
)

EXTRA_LABELS = {
    "previous_rival_elo_mean_3": "최근 3경주 경쟁마 평균 Elo",
    "horse_jockey_history_starts": "말·기수 조합 출전 수",
    "jockey_history_starts": "기수 과거 출전 수",
    "trainer_history_starts": "조교사 과거 출전 수",
    "dry_performance_count": "건조 주로 관측 수",
    "wet_performance_count": "습윤 주로 관측 수",
    "normal_usable_count_pre": "정상 기록 사용 가능 경주 수",
    "distance_normal_usable_count_pre": "같은 거리 기록 사용 가능 경주 수",
    "speed_observation_count_pre": "같은 거리 기록 관측 수",
    "last_body_weight_kg": "직전 마체중",
    "body_weight_delta_kg": "최근 마체중 변화",
    "body_weight_trend_3": "최근 3회 마체중 추세",
    "last_burden_kg": "직전 부담중량",
    "early_late_gain_mean_3": "최근 3경주 초반→막판 순위 변화",
    "late_rank_mean_3": "최근 3경주 막판 평균 순위",
    "early_rank_percentile_3": "최근 3경주 초반 상대위치",
    "late_rank_percentile_3": "최근 3경주 막판 상대위치",
    "rival_global_elo_mean": "현재 편성 경쟁마 평균 Elo",
    "rival_distance_elo_mean": "현재 편성 경쟁마 거리 Elo",
    "lower_number_early_pressure_count": "안쪽 선행 경쟁마 수",
    "higher_number_early_pressure_count": "바깥쪽 선행 경쟁마 수",
}
FEATURE_LABELS = FEATURE_LABELS | EXTRA_LABELS

KRA_BETTING_GUIDE_URL = (
    "https://board.kra.co.kr/down/KRAFile_per_BoardNo/1250/20210527132436227737.pdf"
)
KRA_ODDS_URL = "https://race.kra.co.kr/raceScore/RecordBaedang.do?Act=04&Sub=8&meet=1"
RECOMMENDED_RETURN_MULTIPLE = 1.15

KEY_GROUPS = [
    (
        "선언·기본 조건",
        [
            ("declared_grade_number", "등급", "grade"),
            ("declared_age", "나이", "age"),
            ("declared_burden_kg", "부담중량", "kg"),
            ("declared_rating", "레이팅", "number"),
            ("days_since_previous_start", "직전 출전 후", "days"),
            ("days_since_previous_normal_finish", "직전 정상완주 후", "days"),
            ("jockey_changed", "기수 교체", "bool"),
        ],
    ),
    (
        "능력·최근 성적",
        [
            ("global_elo_pre", "전체 Elo", "number1"),
            ("distance_elo_pre", "거리 Elo", "number1"),
            ("starts_pre", "과거 출전", "count"),
            ("top3_pre", "과거 입상", "count"),
            ("recent_top3_rate_5", "최근 5경주 입상률", "percent"),
            ("recent_finish_score_5_mean", "최근 5경주 상대착순", "percent"),
            ("distance_starts_pre", "같은 거리 출전", "count"),
            ("distance_top3_pre", "같은 거리 입상", "count"),
            ("speed_time_per_100m_mean_pre", "같은 거리 100m 평균", "ms"),
            ("closing_speed_quality_mean_3", "최근 막판 상대속도", "percent"),
        ],
    ),
    (
        "전개·편성",
        [
            ("historical_early_front_rate", "과거 선행 빈도", "percent"),
            ("field_early_ability_percentile", "편성 내 선행력", "percent"),
            ("rival_early_pressure_count", "선행 경쟁마", "count"),
            ("rival_global_elo_mean", "경쟁마 평균 Elo", "number1"),
            ("rival_global_elo_gap", "최강마 대비 Elo", "signed1"),
            ("current_vs_previous_rival_elo", "직전 대비 편성 강도", "signed1"),
            ("current_minus_last_burden_kg", "직전 대비 부담중량", "signedkg"),
            ("progression_last3_vs_prev3", "최근 성적 발전도", "signed3"),
        ],
    ),
    (
        "기수·조교사·말 조합",
        [
            ("jockey_history_starts", "기수 출전", "count"),
            ("jockey_history_win_rate", "기수 우승률", "percent"),
            ("jockey_history_top3_rate", "기수 입상률", "percent"),
            ("trainer_history_top3_rate", "조교사 입상률", "percent"),
            ("horse_jockey_history_starts", "말·기수 출전", "count"),
            ("horse_jockey_history_top3_rate", "말·기수 입상률", "percent"),
            ("jockey_early_front_rate", "기수 선행 빈도", "percent"),
        ],
    ),
    (
        "조교·심사·관측",
        [
            ("training_28d_count", "최근 28일 조교", "count"),
            ("training_28d_duration_seconds", "최근 28일 조교시간", "duration"),
            ("start_training_28d_count", "최근 출발조교", "count"),
            ("medical_90d_count", "최근 90일 진료기록", "count"),
            ("trial_count_pre", "과거 주행심사", "count"),
            ("trial_last_valid_time_ms_pre", "최근 주행심사 기록", "ms"),
            ("weight_last_kg_pre", "최근 관측 마체중", "kg"),
        ],
    ),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def finite(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and abs(number) != float("inf")


def format_value(value, kind: str) -> str:
    if not finite(value):
        return "미관측"
    number = float(value)
    if kind == "grade":
        return f"제{int(number)}등급"
    if kind == "age":
        return f"{int(number)}세"
    if kind == "kg":
        return f"{number:.1f}kg"
    if kind == "signedkg":
        return f"{number:+.1f}kg"
    if kind == "days":
        return f"{int(number)}일"
    if kind == "count":
        return f"{int(number)}회"
    if kind == "percent":
        return f"{number:.1%}"
    if kind == "ms":
        return f"{number / 1000:.2f}초"
    if kind == "duration":
        return f"{number / 60:.0f}분"
    if kind == "bool":
        return "교체" if number >= 0.5 else "동일"
    if kind == "number1":
        return f"{number:.1f}"
    if kind == "signed1":
        return f"{number:+.1f}"
    if kind == "signed3":
        return f"{number:+.3f}"
    return f"{number:.2f}"


def raw_value(feature: str, value) -> str:
    base = feature.removesuffix("__missing")
    if not finite(value):
        return "미관측"
    number = float(value)
    if any(token in base for token in ("rate", "quality", "percentile", "performance")):
        return f"{number:.1%}"
    if base.endswith("_ms_pre") or "time_ms" in base:
        return f"{number / 1000:.2f}초"
    if "weight" in base or "burden" in base:
        return f"{number:.1f}kg"
    if "elo" in base.lower():
        return f"{number:.1f}"
    if "count" in base or "starts" in base or "wins" in base or "top3_pre" in base:
        return f"{int(number)}"
    return f"{number:.3f}"


def factor_list(factors: list[dict], positive: bool) -> str:
    if not factors:
        return '<p class="muted">표시할 요인이 없습니다.</p>'
    maximum = max(abs(float(item["contribution"])) for item in factors) or 1.0
    tone = "positive" if positive else "negative"
    rows = []
    for item in factors:
        feature = str(item["feature"])
        base = feature.removesuffix("__missing")
        label = FEATURE_LABELS.get(base, item.get("label") or base)
        if feature.endswith("__missing"):
            label += " 결측"
        contribution = float(item["contribution"])
        width = max(5.0, min(100.0, abs(contribution) / maximum * 100))
        rows.append(
            f"""
            <li class="factor-row">
              <div class="factor-head"><span>{esc(label)}</span>
                <strong>{contribution:+.3f}</strong></div>
              <div class="factor-meta">관측값 {esc(raw_value(feature, item.get('raw_value')))}</div>
              <div class="factor-track"><span class="{tone}" style="width:{width:.1f}%"></span></div>
            </li>
            """
        )
    return '<ol class="factor-list">' + "".join(rows) + "</ol>"


def probability_class(probability: float) -> str:
    if probability >= 0.7:
        return "prob-high"
    if probability >= 0.4:
        return "prob-mid"
    return "prob-low"


def confidence_text(gap: float) -> tuple[str, str]:
    if gap >= 0.15:
        return "경계 비교적 분명", "good"
    if gap >= 0.06:
        return "경계 주의", "warn"
    return "경계 매우 근접", "danger"


def probability_text(probability: float) -> str:
    if probability >= 0.1:
        return f"{probability:.1%}"
    if probability >= 0.01:
        return f"{probability:.2%}"
    return f"{probability:.3%}"


def odds_text(odds: float) -> str:
    if odds < 100:
        return f"{odds:.1f}배"
    if odds < 1000:
        return f"{odds:.0f}배"
    return f"{odds:,.0f}배"


def wager_record(wager: str, ticket: str, probability: float, basis: str) -> dict:
    if not 0 < probability <= 1:
        raise ValueError(f"Invalid {wager} probability: {probability}")
    return {
        "wager": wager,
        "ticket": ticket,
        "probability": probability,
        "break_even_odds": 1.0 / probability,
        "recommended_odds": RECOMMENDED_RETURN_MULTIPLE / probability,
        "net_roi_100_odds": 2.0 / probability,
        "basis": basis,
    }


def _best_probability(items: list[tuple[tuple[int, ...], float]]) -> tuple[tuple[int, ...], float]:
    return sorted(items, key=lambda item: (-item[1], item[0]))[0]


def build_wager_thresholds(
    race: dict,
    race_horses: list[dict],
    beta_set: float,
    beta_order: float,
) -> list[dict]:
    """Derive seven wager-market probabilities from the sealed HY_R_FORM joint distribution."""
    ordered_horses = sorted(race_horses, key=lambda horse: str(horse["horse_id"]))
    horse_ids = [str(horse["horse_id"]) for horse in ordered_horses]
    numbers = [int(horse["horse_number"]) for horse in ordered_horses]
    names = [str(horse["horse_name"]) for horse in ordered_horses]
    index_by_id = {horse_id: index for index, horse_id in enumerate(horse_ids)}
    sets, orders, log_sets, log_orders, marginals = distribution(
        [float(horse["rank_score"]) for horse in ordered_horses],
        [float(horse["order_score"]) for horse in ordered_horses],
        beta_set,
        beta_order,
    )
    set_probabilities = np.exp(log_sets)
    order_probabilities = np.exp(log_orders)

    def runner(index: int) -> str:
        return f"{numbers[index]}번 {names[index]}"

    win_probabilities = np.zeros(len(ordered_horses))
    quinella: dict[tuple[int, int], float] = {}
    exacta: dict[tuple[int, int], float] = {}
    for order, probability in zip(orders, order_probabilities, strict=True):
        first, second = int(order[0]), int(order[1])
        win_probabilities[first] += float(probability)
        pair = tuple(sorted((first, second)))
        quinella[pair] = quinella.get(pair, 0.0) + float(probability)
        exacta[(first, second)] = exacta.get((first, second), 0.0) + float(probability)

    quinella_place: dict[tuple[int, int], float] = {
        pair: 0.0 for pair in combinations(range(len(ordered_horses)), 2)
    }
    for selected_set, probability in zip(sets, set_probabilities, strict=True):
        for pair in combinations((int(value) for value in selected_set), 2):
            sorted_pair = tuple(sorted(pair))
            quinella_place[sorted_pair] += float(probability)

    win_index = int(
        sorted(range(len(ordered_horses)), key=lambda i: (-win_probabilities[i], numbers[i]))[0]
    )
    place_index = index_by_id[str(race["pick_horse_id"])]
    quinella_pair, quinella_probability = _best_probability(list(quinella.items()))
    exacta_pair, exacta_probability = _best_probability(list(exacta.items()))
    quinella_place_pair, quinella_place_probability = _best_probability(
        list(quinella_place.items())
    )

    predicted_set_indices = tuple(
        sorted(index_by_id[str(horse_id)] for horse_id in race["predicted_set_horse_ids"])
    )
    set_lookup = {tuple(int(value) for value in selected_set): i for i, selected_set in enumerate(sets)}
    predicted_order_indices = tuple(
        index_by_id[str(horse_id)] for horse_id in race["predicted_order_horse_ids"]
    )
    order_lookup = {tuple(int(value) for value in order): i for i, order in enumerate(orders)}
    set_probability = float(set_probabilities[set_lookup[predicted_set_indices]])
    order_probability = float(order_probabilities[order_lookup[predicted_order_indices]])

    def unordered(pair: tuple[int, ...]) -> str:
        return " · ".join(runner(index) for index in sorted(pair, key=lambda i: numbers[i]))

    def ordered(pair: tuple[int, ...]) -> str:
        return " → ".join(runner(index) for index in pair)

    return [
        wager_record("단승", runner(win_index), float(win_probabilities[win_index]), "모델 우승확률 최대"),
        wager_record("연승", runner(place_index), float(marginals[place_index]), "기존 한 마리 입상 선택"),
        wager_record("복연승", unordered(quinella_place_pair), quinella_place_probability, "동시 입상확률 최대 조합"),
        wager_record("복승", unordered(quinella_pair), quinella_probability, "1·2위 동시 점유확률 최대 조합"),
        wager_record("쌍승", ordered(exacta_pair), exacta_probability, "정확한 1·2위 확률 최대 조합"),
        wager_record(
            "삼복승",
            unordered(predicted_set_indices),
            set_probability,
            "기존 입상 세 마리 선택",
        ),
        wager_record(
            "삼쌍승",
            ordered(predicted_order_indices),
            order_probability,
            "기존 정확 순서 선택",
        ),
    ]


def wager_threshold_table(records: list[dict]) -> str:
    rows = []
    for record in records:
        rows.append(
            f"""
            <tr><td><strong>{esc(record['wager'])}</strong><small>{esc(record['basis'])}</small></td>
              <td>{esc(record['ticket'])}</td><td>{probability_text(record['probability'])}</td>
              <td>{odds_text(record['break_even_odds'])}</td>
              <td class="recommended-odds">{odds_text(record['recommended_odds'])}</td>
              <td>{odds_text(record['net_roi_100_odds'])}</td></tr>
            """
        )
    return f"""
      <section class="roi-card"><div class="roi-card-head"><div><h3>승식별 배당 진입 기준</h3>
        <p>현재 표시 배당이 <strong>권장 최소배당</strong> 이상일 때만 후보로 보고, 그보다 낮으면 패스한다.</p></div>
        <span>시장 최종배당 미사용</span></div>
      <div class="table-wrap"><table class="odds-table"><thead><tr><th>승식·선정 근거</th><th>모델 선택</th>
        <th>모델 적중확률</th><th>회수율 100%<br>손익분기</th><th>권장 최소배당<br>회수율 115% 목표</th>
        <th>순이익 ROI +100%<br>기준</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
    """


def horse_interpretation(horse: dict, race: dict) -> str:
    probability = float(horse["top3_probability"])
    positive = horse["positive_reasons"][0]["label"] if horse["positive_reasons"] else "없음"
    negative = horse["negative_reasons"][0]["label"] if horse["negative_reasons"] else "없음"
    if horse["selected_pick"]:
        status = "이 경주의 한 마리 입상 대표 선택"
    elif horse["selected_set"]:
        status = "예측 입상 세 마리 집합에 포함"
    elif horse["model_rank"] == 4:
        status = "세 마리 선택 경계 바로 밖의 대안"
    else:
        status = f"모델 입상 순위 {horse['model_rank']}위"
    order_position = None
    if horse["horse_id"] in race["predicted_order_horse_ids"]:
        order_position = race["predicted_order_horse_ids"].index(horse["horse_id"]) + 1
    order = f" 정확 순서에서는 {order_position}위로 배치됐다." if order_position else ""
    return (
        f"{status}이며 입상 확률은 {probability:.1%}다.{order} "
        f"가장 큰 상승 요인은 ‘{positive}’, 가장 큰 하락 요인은 ‘{negative}’다. "
        "이는 모델 내부 점수 설명이며 실제 경기 결과의 원인을 확정하지 않는다."
    )


def metric_groups(feature: dict) -> str:
    groups = []
    for title, fields in KEY_GROUPS:
        metrics = []
        for key, label, kind in fields:
            metrics.append(
                f'<div class="metric"><span>{esc(label)}</span>'
                f'<strong>{esc(format_value(feature.get(key), kind))}</strong></div>'
            )
        groups.append(
            f'<section class="metric-group"><h5>{esc(title)}</h5>' + "".join(metrics) + "</section>"
        )
    return '<div class="metric-grid">' + "".join(groups) + "</div>"


def _history_date(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def load_past_records(
    horse_ids: list[str], cutoff_date: str
) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    placeholders = ",".join("?" for _ in horse_ids)
    query = f"""
    WITH event_sizes AS (
      SELECT event_id,COUNT(*) AS field_size FROM entry GROUP BY event_id
    ), sections AS (
      SELECT entry_id,
        MAX(CASE WHEN section_code='S1F' THEN source_value_ms END) AS s1f_ms,
        MAX(CASE WHEN section_code='3C' THEN source_value_ms END) AS c3_ms,
        MAX(CASE WHEN section_code='4C' THEN source_value_ms END) AS c4_ms,
        MAX(CASE WHEN section_code='G3F' THEN source_value_ms END) AS g3f_ms,
        MAX(CASE WHEN section_code='G1F' THEN source_value_ms END) AS g1f_ms,
        MAX(CASE WHEN section_code='FIN' THEN source_value_ms END) AS fin_ms
      FROM section_checkpoint GROUP BY entry_id
    )
    SELECT e.id AS entry_id,e.hr_no AS horse_id,v.event_type,v.event_date,
      v.event_number,v.trial_round,v.distance_m,v.grade,v.weather,v.track_condition,
      v.track_moisture_percent,e.horse_number,e.finish_position,e.finish_time_ms,
      e.segment_quality,e.record_status,sz.field_size,s.s1f_ms,s.c3_ms,s.c4_ms,
      s.g3f_ms,s.g1f_ms,s.fin_ms
    FROM entry e
    JOIN event v ON v.id=e.event_id
    JOIN event_sizes sz ON sz.event_id=v.id
    LEFT JOIN sections s ON s.entry_id=e.id
    WHERE v.meet=2 AND e.hr_no IN ({placeholders})
      AND v.event_type IN ('race','trial') AND v.event_date<=?
    ORDER BY e.hr_no,v.event_date,v.event_number,e.id
    """
    connection = sqlite3.connect(f"file:{RESEARCH_DB.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in connection.execute(query, [*horse_ids, cutoff_date])]
    finally:
        connection.close()
    races: dict[str, list[dict]] = {horse_id: [] for horse_id in horse_ids}
    trials: dict[str, list[dict]] = {horse_id: [] for horse_id in horse_ids}
    previous_race: dict[str, date] = {}
    for row in rows:
        horse_id = str(row["horse_id"]).zfill(7)
        event_day = _history_date(str(row["event_date"]))
        row["event_date_iso"] = event_day.isoformat()
        if row["event_type"] == "race":
            previous = previous_race.get(horse_id)
            row["interval_days"] = (event_day - previous).days if previous else None
            previous_race[horse_id] = event_day
            races.setdefault(horse_id, []).append(row)
        else:
            trials.setdefault(horse_id, []).append(row)
    for values in (*races.values(), *trials.values()):
        values.reverse()
    return races, trials


def record_time(value) -> str:
    return f"{float(value) / 1000:.1f}" if finite(value) and float(value) > 0 else "—"


def finish_text(position, field_size) -> str:
    if not finite(position):
        return "—"
    value = int(float(position))
    if value >= 90:
        return f"{value}(비정상)"
    return f"{value}/{int(field_size)}"


def race_history_table(records: list[dict]) -> str:
    if not records:
        return '<section class="history-empty">과거 공식 경주 기록 없음 · 첫 출전</section>'
    rows = []
    for row in records:
        condition = " · ".join(
            value
            for value in (
                str(row.get("weather") or "").strip(),
                str(row.get("track_condition") or "").strip(),
            )
            if value
        ) or "—"
        interval = f"{int(row['interval_days'])}일" if row.get("interval_days") is not None else "—"
        rows.append(
            f"""
            <tr><td>{esc(row['event_date_iso'])}</td><td>{row['event_number']}R</td>
              <td>{row['distance_m']}m</td><td>{finish_text(row.get('finish_position'), row['field_size'])}</td>
              <td>{interval}</td><td>{record_time(row.get('finish_time_ms') or row.get('fin_ms'))}</td>
              <td>{record_time(row.get('s1f_ms'))}</td><td>{record_time(row.get('c3_ms'))}</td>
              <td>{record_time(row.get('c4_ms'))}</td><td>{record_time(row.get('g3f_ms'))}</td>
              <td>{record_time(row.get('g1f_ms'))}</td><td>{esc(condition)}</td></tr>
            """
        )
    return f"""
      <details class="history-block" open><summary>과거 공식 경주 {len(records)}회 · 최신순 전체 기록</summary>
      <div class="history-help">단위 초 · S1F·3C·4C는 출발 후 누적 기록, G3F·G1F는 결승선 전 600m·200m 구간 기록이다.
      출전간격은 해당 경주와 그 직전 경주 사이의 일수다.</div>
      <div class="history-scroll"><table class="history-table"><thead><tr><th>일자</th><th>경주</th><th>거리</th>
      <th>착순/두수</th><th>출전간격</th><th>총기록</th><th>S1F</th><th>3C</th><th>4C</th><th>G3F</th>
      <th>G1F</th><th>날씨·주로</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></details>
    """


def trial_history_table(records: list[dict]) -> str:
    if not records:
        return '<section class="history-empty">과거 공식 주행심사 구간 기록 없음</section>'
    rows = []
    for row in records:
        rows.append(
            f"""
            <tr><td>{esc(row['event_date_iso'])}</td><td>{row.get('event_number') or '—'}</td>
              <td>{row.get('distance_m') or '—'}m</td>
              <td>{finish_text(row.get('finish_position'), row['field_size'])}</td>
              <td>{record_time(row.get('finish_time_ms') or row.get('fin_ms'))}</td>
              <td>{record_time(row.get('s1f_ms'))}</td><td>{record_time(row.get('c3_ms'))}</td>
              <td>{record_time(row.get('c4_ms'))}</td><td>{record_time(row.get('g3f_ms'))}</td>
              <td>{record_time(row.get('g1f_ms'))}</td>
              <td>{esc(row.get('segment_quality') or '—')}</td></tr>
            """
        )
    return f"""
      <details class="history-block"><summary>과거 공식 주행심사 {len(records)}회 · 구간 기록</summary>
      <div class="history-scroll"><table class="history-table"><thead><tr><th>일자</th><th>심사</th><th>거리</th>
      <th>착순/두수</th><th>총기록</th><th>S1F</th><th>3C</th><th>4C</th><th>G3F</th><th>G1F</th>
      <th>품질</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></details>
    """


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prediction_dir", type=Path)
    args = parser.parse_args()
    root = args.prediction_dir.resolve()
    races = json.loads((root / "race_predictions.json").read_text(encoding="utf-8"))
    horses = json.loads((root / "horse_explanations.json").read_text(encoding="utf-8"))
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    original_manifest_sha = sha256(root / "manifest.json")
    model_path = Path(metadata["model_path"])
    if sha256(model_path) != metadata["model_sha256"]:
        raise RuntimeError("Model SHA-256 does not match the sealed forecast metadata")
    with model_path.open("rb") as model_file:
        model = pickle.load(model_file)  # noqa: S301 - locally sealed, hash-verified model artifact
    beta_set = float(model["rank_bundle"]["beta"])
    beta_order = float(model["beta_order"])
    feature_rows = pl.read_parquet(root / "live_features.parquet").to_dicts()
    feature_by_entry = {int(row["entry_id"]): row for row in feature_rows}
    cutoff_date = (
        (metadata.get("h2_supplemental_metadata") or {}).get("cutoff_date")
        or metadata["history_last_date"]
    )
    history_races, history_trials = load_past_records(
        sorted({str(horse["horse_id"]).zfill(7) for horse in horses}),
        str(cutoff_date).replace("-", ""),
    )
    race_numbers = sorted(int(race["race_number"]) for race in races)
    horses_by_race = {
        race_number: sorted(
            [horse for horse in horses if horse["race_number"] == race_number],
            key=lambda item: item["model_rank"],
        )
        for race_number in race_numbers
    }
    race_by_number = {race["race_number"]: race for race in races}
    wagers_by_race = {
        race_number: build_wager_thresholds(
            race_by_number[race_number], horses_by_race[race_number], beta_set, beta_order
        )
        for race_number in race_numbers
    }

    strongest = max(horses, key=lambda item: item["top3_probability"])
    most_stable_set = max(races, key=lambda item: item["set_probability"])
    most_stable_order = max(races, key=lambda item: item["order_probability"])
    nav = "".join(f'<a href="#race-{number}">{number}R</a>' for number in race_numbers)
    sections = []
    for race_number in race_numbers:
        race = race_by_number[race_number]
        race_horses = horses_by_race[race_number]
        wager_records = wagers_by_race[race_number]
        label, tone = confidence_text(float(race["third_fourth_probability_gap"]))
        set_text = " · ".join(race["predicted_set"])
        order_text = " → ".join(race["predicted_order"])
        table_rows = []
        detail_rows = []
        for horse in race_horses:
            probability = float(horse["top3_probability"])
            badges = []
            if horse["selected_pick"]:
                badges.append('<span class="badge pick">대표 선택</span>')
            if horse["selected_set"]:
                badges.append('<span class="badge set">Top3 집합</span>')
            if horse["model_rank"] == 4:
                badges.append('<span class="badge boundary">경계 대안</span>')
            table_rows.append(
                f"""
                <tr>
                  <td class="rank">{horse['model_rank']}</td>
                  <td><a href="#horse-{horse['entry_id']}"><strong>{horse['horse_number']}번
                    {esc(horse['horse_name'])}</strong></a><div class="badges">{''.join(badges)}</div></td>
                  <td>{esc(horse.get('jockey_name') or '미상')}</td>
                  <td>{esc(format_value(horse.get('burden_kg'), 'kg'))}</td>
                  <td class="prob-cell"><strong>{probability:.1%}</strong>
                    <div class="prob-track"><span class="{probability_class(probability)}"
                    style="width:{probability * 100:.1f}%"></span></div></td>
                </tr>
                """
            )
            feature = feature_by_entry[int(horse["entry_id"])]
            open_attribute = " open" if horse["selected_set"] or horse["model_rank"] == 4 else ""
            detail_rows.append(
                f"""
                <details class="horse-detail" id="horse-{horse['entry_id']}"{open_attribute}>
                  <summary>
                    <span class="horse-rank">#{horse['model_rank']}</span>
                    <span class="horse-title">{horse['horse_number']}번 {esc(horse['horse_name'])}</span>
                    <span class="horse-jockey">{esc(horse.get('jockey_name') or '미상')} ·
                      {esc(format_value(horse.get('burden_kg'), 'kg'))}</span>
                    <strong class="horse-prob">입상 {probability:.1%}</strong>
                    <span class="badges">{''.join(badges)}</span>
                  </summary>
                  <div class="horse-body">
                    <p class="interpretation">{esc(horse_interpretation(horse, race))}</p>
                    <div class="factor-columns">
                      <section><h4>점수를 높인 요인</h4>
                        {factor_list(horse['positive_reasons'], True)}</section>
                      <section><h4>점수를 낮춘 요인</h4>
                        {factor_list(horse['negative_reasons'], False)}</section>
                    </div>
                    {metric_groups(feature)}
                    <section class="record-section"><h4>과거 경주·구간 기록</h4>
                      {race_history_table(history_races.get(str(horse['horse_id']).zfill(7), []))}
                      {trial_history_table(history_trials.get(str(horse['horse_id']).zfill(7), []))}
                    </section>
                    <div class="raw-score">원시 순위점수 {horse['rank_score']:+.4f} ·
                      원시 순서점수 {horse['order_score']:+.4f} · 공식 말 ID {esc(horse['horse_id'])}</div>
                  </div>
                </details>
                """
            )
        sections.append(
            f"""
            <section class="race-section" id="race-{race_number}">
              <header class="race-header"><div><span class="race-number">{race_number}R</span>
                <h2>{race['distance_m']}m · {race['field_size']}두</h2></div>
                <a class="top-link" href="#top">맨 위로 ↑</a></header>
              <div class="prediction-grid">
                <article><span>한 마리 입상</span><strong>{esc(race['pick'])}</strong>
                  <em>{race['pick_top3_probability']:.1%}</em></article>
                <article><span>입상 세 마리 집합</span><strong>{esc(set_text)}</strong>
                  <em>{race['set_probability']:.1%}</em></article>
                <article><span>정확한 1·2·3위</span><strong>{esc(order_text)}</strong>
                  <em>{race['order_probability']:.1%}</em></article>
              </div>
              <div class="boundary-note {tone}"><strong>{esc(label)}</strong> · 3위 후보
                {esc(race['third_by_probability'])}와 4위 후보
                {esc(race['fourth_by_probability'])}의 입상확률 차이
                {race['third_fourth_probability_gap']:.1%}p</div>
              {wager_threshold_table(wager_records)}
              <h3>전체 출전마 모델 순위</h3>
              <div class="table-wrap"><table><thead><tr><th>순위</th><th>말</th><th>기수</th>
                <th>부담중량</th><th>3위 이내 확률</th></tr></thead>
                <tbody>{''.join(table_rows)}</tbody></table></div>
              <h3>말별 상세 분석</h3>
              <div class="horse-list">{''.join(detail_rows)}</div>
            </section>
            """
        )

    css = """
    :root{--ink:#18212b;--muted:#657080;--paper:#f4f1eb;--card:#fff;--line:#dfe3e8;
      --navy:#16324f;--gold:#c18b22;--green:#16734a;--red:#b6423c;--blue:#2e66a5}
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);
      color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Pretendard","Noto Sans KR",sans-serif;
      line-height:1.55}a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
    .hero{background:linear-gradient(135deg,#102b44,#214e72);color:white;padding:52px 24px 44px}
    .hero-inner,.container{max-width:1240px;margin:auto}.eyebrow{letter-spacing:.12em;text-transform:uppercase;
      color:#d8bd7a;font-weight:700}.hero h1{font-size:clamp(30px,5vw,56px);line-height:1.1;margin:10px 0}
    .hero p{max-width:830px;color:#d7e0e8;font-size:17px}.lock{display:inline-flex;gap:8px;align-items:center;
      padding:8px 12px;border:1px solid #7190aa;border-radius:999px;font-size:13px}
    .race-nav{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.94);backdrop-filter:blur(8px);
      border-bottom:1px solid var(--line);display:flex;justify-content:center;gap:8px;padding:10px;overflow:auto}
    .race-nav a{min-width:48px;text-align:center;padding:7px 12px;border-radius:999px;background:#eef3f7;
      color:var(--navy);font-weight:800}.container{padding:26px 20px 70px}.overview{display:grid;
      grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:22px}.overview article,.method{
      background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 5px 18px #2030400a}
    .overview span{display:block;color:var(--muted);font-size:13px}.overview strong{display:block;font-size:20px;margin-top:5px}
    .method{font-size:14px;color:#3d4855}.method strong{color:var(--ink)}.race-section{margin:34px 0 54px;
      scroll-margin-top:78px}.race-header{display:flex;align-items:center;justify-content:space-between;border-bottom:3px solid var(--navy);
      padding-bottom:10px}.race-header>div{display:flex;align-items:baseline;gap:12px}.race-number{font-size:30px;font-weight:900;
      color:var(--navy)}.race-header h2{margin:0;font-size:21px}.top-link{font-size:13px}.prediction-grid{display:grid;
      grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0}.prediction-grid article{position:relative;background:white;
      border:1px solid var(--line);border-radius:13px;padding:16px;min-height:125px}.prediction-grid span{display:block;
      color:var(--muted);font-size:13px;font-weight:700}.prediction-grid strong{display:block;font-size:17px;margin:7px 50px 0 0}
    .prediction-grid em{position:absolute;right:14px;top:14px;background:#edf4fa;color:var(--navy);font-style:normal;
      padding:4px 8px;border-radius:8px;font-weight:800}.boundary-note{padding:11px 14px;border-radius:10px;font-size:14px}
    .boundary-note.good{background:#e7f5ee;color:#16583b}.boundary-note.warn{background:#fff4dc;color:#765110}
    .boundary-note.danger{background:#fbe9e7;color:#7e2f2a}h3{margin:24px 0 10px}.table-wrap{overflow:auto;
      border:1px solid var(--line);border-radius:12px;background:white}table{width:100%;border-collapse:collapse;min-width:700px}
    .roi-guide{margin-top:14px;border-left:5px solid var(--gold)}.roi-guide .formula{display:grid;
      grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}.roi-guide .formula div{background:#f7f3e8;
      border-radius:8px;padding:10px}.roi-guide code{font-size:13px}.roi-card{margin:15px 0 22px}.roi-card-head{display:flex;
      align-items:end;justify-content:space-between;gap:12px}.roi-card-head h3{margin-bottom:0}.roi-card-head p{margin:2px 0 8px;
      color:var(--muted);font-size:13px}.roi-card-head>span{font-size:12px;color:#7a322c;background:#f4e5e2;
      padding:4px 8px;border-radius:999px;white-space:nowrap;margin-bottom:8px}.odds-table{min-width:940px}.odds-table small{
      display:block;color:var(--muted);font-weight:400}.odds-table td:nth-child(n+3){white-space:nowrap}.recommended-odds{
      background:#fff8df;font-weight:900;color:#765110}
    th{background:#edf1f4;text-align:left;font-size:13px;color:#4b5865;padding:10px}td{padding:10px;border-top:1px solid #edf0f2;
      vertical-align:middle}.rank{text-align:center;font-weight:900;color:var(--navy)}.badges{display:inline-flex;gap:5px;flex-wrap:wrap;
      margin-left:8px}.badge{font-size:11px;padding:2px 6px;border-radius:999px;white-space:nowrap}.badge.pick{background:#f6e6b5;
      color:#684800}.badge.set{background:#dff1e8;color:#155a3b}.badge.boundary{background:#f4e5e2;color:#7a322c}
    .prob-cell{min-width:160px}.prob-track,.factor-track{height:6px;background:#edf0f2;border-radius:99px;overflow:hidden;
      margin-top:5px}.prob-track span,.factor-track span{height:100%;display:block;border-radius:99px}.prob-high{background:#17734a}
    .prob-mid{background:#c18b22}.prob-low{background:#8c98a5}.horse-list{display:grid;gap:9px}.horse-detail{background:white;
      border:1px solid var(--line);border-radius:12px;overflow:hidden;scroll-margin-top:82px}.horse-detail summary{cursor:pointer;
      display:flex;align-items:center;gap:10px;padding:13px 15px;list-style:none}.horse-detail summary::-webkit-details-marker{display:none}
    .horse-detail summary::before{content:"＋";color:var(--muted)}.horse-detail[open] summary::before{content:"−"}
    .horse-rank{font-weight:900;color:var(--navy);min-width:26px}.horse-title{font-weight:850;font-size:17px}.horse-jockey{color:var(--muted);
      font-size:13px}.horse-prob{margin-left:auto}.horse-body{border-top:1px solid var(--line);padding:17px;background:#fdfdfc}
    .interpretation{margin-top:0;background:#eef4f8;border-left:4px solid var(--blue);padding:12px 14px;border-radius:6px}
    .factor-columns{display:grid;grid-template-columns:1fr 1fr;gap:18px}.factor-columns h4{margin:5px 0}.factor-list{list-style:none;
      padding:0;margin:0}.factor-row{padding:7px 0;border-bottom:1px dashed #e1e4e6}.factor-head{display:flex;justify-content:space-between;
      gap:10px}.factor-meta{font-size:12px;color:var(--muted)}.factor-track .positive{background:var(--green)}
    .factor-track .negative{background:var(--red)}.metric-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:9px;margin-top:18px}
    .metric-group{border:1px solid var(--line);border-radius:9px;padding:10px;background:white}.metric-group h5{margin:0 0 7px;color:var(--navy)}
    .metric{display:flex;justify-content:space-between;gap:8px;font-size:12px;padding:3px 0}.metric span{color:var(--muted)}
    .raw-score{font:12px ui-monospace,SFMono-Regular,monospace;color:#6a7480;margin-top:12px}.footer{border-top:1px solid var(--line);
      color:var(--muted);font-size:13px;padding:22px 0}.muted{color:var(--muted)}
    .record-section{margin-top:18px}.record-section>h4{margin:0 0 10px;color:var(--navy)}
    .history-block,.history-empty{background:#fff;border:1px solid var(--line);border-radius:10px;margin:9px 0}
    .history-block summary{cursor:pointer;padding:10px 12px;font-weight:800;color:var(--navy)}
    .history-help{font-size:12px;color:var(--muted);padding:0 12px 8px}.history-empty{padding:11px 12px;color:var(--muted);font-size:13px}
    .history-scroll{overflow:auto;max-height:430px;border-top:1px solid var(--line)}.history-table{font-size:12px;min-width:900px}
    .history-table th{position:sticky;top:0;background:#edf3f7;z-index:1;white-space:nowrap}.history-table td{white-space:nowrap}
    @media(max-width:900px){.overview,.prediction-grid,.roi-guide .formula{grid-template-columns:1fr}.factor-columns{grid-template-columns:1fr}
      .metric-grid{grid-template-columns:repeat(2,1fr)}.horse-detail summary{flex-wrap:wrap}.horse-prob{margin-left:0}}
    @media print{.race-nav,.top-link{display:none}.hero{padding:20px;background:#fff;color:#000}.hero p{color:#333}
      body{background:#fff}.race-section{break-before:page}.horse-detail{break-inside:avoid}.horse-detail:not([open]) .horse-body{display:block}
      .container{max-width:none;padding:0}.prediction-grid article,.overview article,.method{box-shadow:none}}
    """
    generated_at = metadata["created_at"]
    changed_horses = int(metadata.get("h2_changed_horses") or 0)
    correction_note = (
        f'<section class="method"><strong>입력 교정.</strong> 공식 조교·출발조교·진료 '
        f'원자료를 T-2로 다시 절단해 출전마 {changed_horses}두의 입력을 갱신한 재예측이다. '
        "대상 경주 결과는 사용하지 않았다.</section>"
        if changed_horses
        else ""
    )
    target_date = str(metadata["target_date"])
    target_date_ko = target_date.replace("-", "년 ", 1).replace("-", "월 ", 1) + "일"
    race_count = len(race_numbers)
    html_text = f"""<!doctype html>
    <html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>제주 {esc(target_date)} 전 경주 상세 예측</title><style>{css}</style></head>
    <body><header class="hero" id="top"><div class="hero-inner"><div class="eyebrow">Jeju Live Forecast</div>
      <h1>{esc(target_date_ko)}<br>제주 {race_count}경주 상세 예측</h1>
      <p>동결된 HY_R_FORM 모델로 공식 출마표 {metadata['entries']}두를 분석했다. 한 마리 입상, 입상 세 마리 집합,
      정확한 1·2·3위와 모든 경주마의 점수 근거를 함께 표시한다.</p>
      <div class="lock">🔒 사전 예측 고정 · {esc(generated_at)}</div></div></header>
    <nav class="race-nav">{nav}</nav><main class="container">
      <section class="overview">
        <article><span>가장 높은 한 마리 입상확률</span><strong>{strongest['race_number']}R ·
          {strongest['horse_number']}번 {esc(strongest['horse_name'])} · {strongest['top3_probability']:.1%}</strong></article>
        <article><span>가장 높은 세 마리 집합확률</span><strong>{most_stable_set['race_number']}R ·
          {most_stable_set['set_probability']:.1%}</strong></article>
        <article><span>가장 높은 정확 순서확률</span><strong>{most_stable_order['race_number']}R ·
          {most_stable_order['order_probability']:.1%}</strong></article>
      </section>
      <section class="method"><strong>읽는 법.</strong> 입상확률은 각 말의 공식 3위 이내 확률이며 한 경주 합계는 300%다.
        집합확률은 표시된 세 말이 순서와 무관하게 모두 입상할 확률, 순서확률은 표시된 1·2·3위가 그대로 들어올 확률이다.
        변수 기여도는 모델 내부 점수를 설명하며 실제 경기 결과의 인과관계를 뜻하지 않는다. 대상 경주 결과·최종 배당·당일
        마체중·실제 주로는 사용하지 않았다.</section>
      <section class="method"><strong>출전 주기 반영.</strong> 공식 경주일로 계산한 ‘직전 출전 후 일수’와
        ‘직전 정상 완주 후 일수’를 순위 모델과 순서 모델이 모두 사용한다. API78 경주카드의 문자형 출전주기
        <code>ptinCycl</code> 자체는 직접 입력하지 않는다. 과거 기록표의 출전간격은 각 경주와 그 직전 경주 사이의 일수다.</section>
      {correction_note}
      <section class="method roi-guide"><strong>배당 진입 기준.</strong> 한국마사회 배당처럼 원금을 포함한 환급 배수를
        <code>d</code>, 모델 적중확률을 <code>p</code>로 두면 기대 회수율은 <code>p × d × 100%</code>다.
        흔히 말하는 ‘ROI 100%’를 원금 회수 기준으로 해석한 손익분기는 <code>d = 1/p</code>다. 이 보고서는 확률 오차와
        마감 전 배당 변동을 감안해 <strong>15% 여유를 둔 d ≥ 1.15/p</strong>를 실제 관찰 기준으로 표시한다.
        수학적 순이익 ROI +100%, 즉 원금의 두 배 회수 기준은 <code>d = 2/p</code>로 별도 표시했다.
        <div class="formula"><div><strong>손익분기</strong><br><code>1 ÷ 모델확률</code></div>
          <div><strong>권장 최소배당</strong><br><code>1.15 ÷ 모델확률</code></div>
          <div><strong>순이익 ROI +100%</strong><br><code>2 ÷ 모델확률</code></div></div>
        각 경주의 표는 HY_R_FORM 상위 조합 하나를 기준으로 한다. 단·복·쌍 계열 확률은 모델의 정확 1·2·3위 결합분포를
        합산한 값이며 승식별 시장수익에 맞춰 별도 보정한 확률은 아니다. 실제 표시 배당이 권장 기준보다 낮으면 패스하며,
        기준 이상이어도 수익을 보장하지 않는다. 승식 정의는
        <a href="{KRA_BETTING_GUIDE_URL}">한국마사회 공식 안내</a>, 배당 표기 예시는
        <a href="{KRA_ODDS_URL}">한국마사회 배당률 조회</a>를 따른다.</section>
      {''.join(sections)}
      <footer class="footer"><strong>재현 정보</strong><br>모델 SHA-256 {esc(metadata['model_sha256'])}<br>
        기존 예측 manifest SHA-256 {original_manifest_sha}<br>과거 이력 마지막 날짜 {esc(metadata['history_last_date'])} ·
        공식 출마표 {metadata['entries']}두 · 결과 endpoint 호출 0회</footer>
    </main></body></html>"""
    output = root / "detailed_report.html"
    output.write_text(html_text, encoding="utf-8")
    thresholds_output = root / "betting_thresholds.json"
    thresholds_payload = {
        "target_date": metadata["target_date"],
        "model": metadata["model"],
        "model_sha256": metadata["model_sha256"],
        "market_odds_used": False,
        "definitions": {
            "expected_return_rate": "probability * decimal_odds",
            "break_even_odds": "1 / probability",
            "recommended_odds": f"{RECOMMENDED_RETURN_MULTIPLE} / probability",
            "net_roi_100_odds": "2 / probability",
            "recommended_expected_return_rate": RECOMMENDED_RETURN_MULTIPLE,
        },
        "official_sources": {
            "betting_guide": KRA_BETTING_GUIDE_URL,
            "odds_examples": KRA_ODDS_URL,
        },
        "races": [
            {"race_number": race_number, "wagers": wagers_by_race[race_number]}
            for race_number in race_numbers
        ],
    }
    thresholds_output.write_text(
        json.dumps(thresholds_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "created_from_prediction_manifest_sha256": original_manifest_sha,
        "detailed_report": {"path": output.name, "sha256": sha256(output)},
        "betting_thresholds": {
            "path": thresholds_output.name,
            "sha256": sha256(thresholds_output),
        },
        "renderer": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))},
        "races": len(races),
        "horses": len(horses),
        "target_results_used": False,
    }
    manifest_path = root / "detailed_report_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"report": str(output), "sha256": sha256(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

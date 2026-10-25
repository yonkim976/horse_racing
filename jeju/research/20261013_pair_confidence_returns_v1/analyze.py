#!/usr/bin/env python3
"""Summarize frozen-pair QNL/QPL returns by pre-fixed confidence groups."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261013_pair_confidence_returns_v1"
PREDICTION = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
QPL_RETURNS = ROOT / "jeju/research/20261013_pair_qpl_roi_v1/race_returns.csv"
QPL_HASHES = ROOT / "jeju/research/20261013_pair_qpl_roi_v1/SOURCE_HASHES.json"
QPL_REVIEW = ROOT / "jeju/research/20261013_pair_qpl_roi_v1/ROOT_REVIEW.json"
QNL_RETURNS = ROOT / "jeju/research/20261013_qnl_tla_roi_v1/race_returns.csv"
QNL_HASHES = ROOT / "jeju/research/20261013_qnl_tla_roi_v1/SOURCE_HASHES.json"
QNL_REVIEW = ROOT / "jeju/research/20261013_qnl_tla_roi_v1/ROOT_REVIEW.json"
SCHEDULE = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
SCHEDULE_RECEIPT = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"

EXPECTED_HASHES = {
    PREDICTION: "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6",
    QPL_RETURNS: "8e1b1a2485d6c625445315bd856d7988fa9da54e3de0bd10b2dac02086179afa",
    QPL_HASHES: "5d8498fecb5d7c1521aa3b85494e020e3337027432bb85f46506dafba1b92df6",
    QPL_REVIEW: "e65a2c8476efe29241080a360bc4fc04e1a2733785cd9b03b98a4b39f27196b3",
    QNL_RETURNS: "2be5c07884e48eab6e7621b17b82a7c0179bb9c77ad143ff52c7ef6a42c4d910",
    QNL_HASHES: "d14ff9114de96f034000eb03afbbbf79679058c253016340a76b9ff1525af028",
    QNL_REVIEW: "55baa3343bfab8459981625283b5a7e228928ade65037860f24e56dce0d808e8",
    SCHEDULE: "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
    SCHEDULE_RECEIPT: "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e",
}

BIN_EDGES = (0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 1.0)
BIN_LABELS = (
    "[0.00,0.10)", "[0.10,0.15)", "[0.15,0.20)", "[0.20,0.25)",
    "[0.25,0.30)", "[0.30,0.40)", "[0.40,0.50)", "[0.50,1.00]",
)
THRESHOLDS = (0.00, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)
STAKE = 10_000
SOURCE_QNL_STAKE = 6_000
EXPECTED_RACES_BY_YEAR = {2025: 654, 2026: 488}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_id(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def canonical_horse(value: object) -> int:
    text = canonical_id(value)
    require(text.isdigit(), f"invalid horse number: {value!r}")
    return int(text)


def parse_money(value: object) -> int:
    text = str(value).strip()
    require(bool(text), f"missing integer KRW amount: {value!r}")
    number = Decimal(text)
    require(number == number.to_integral_value(), f"non-integer KRW amount: {value!r}")
    return int(number)


def parse_odds(value: object) -> Decimal:
    text = str(value).strip()
    return Decimal(text) if text else Decimal(0)


def multiply_to_won(odds: Decimal, stake: int) -> int:
    amount = odds * Decimal(stake)
    require(amount == amount.to_integral_value(), f"fractional KRW payout: {odds} × {stake}")
    return int(amount)


def pair_text(first: object, second: object) -> str:
    a, b = sorted((canonical_horse(first), canonical_horse(second)))
    require(a != b, f"pair repeats a horse: {a}")
    return f"{a}-{b}"


def parse_qnl_ticket(ticket: object) -> str:
    numbers = re.findall(r"\d+", str(ticket))
    require(len(numbers) == 2, f"expected two-horse QNL ticket, got {ticket!r}")
    return pair_text(numbers[0], numbers[1])


def normalize_dates(frame: pd.DataFrame, column: str) -> None:
    frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.strftime("%Y-%m-%d")
    require(frame[column].notna().all(), f"invalid date in {column}")


def assign_bin(value: float) -> str:
    require(np.isfinite(value) and 0.0 <= value <= 1.0, f"confidence outside [0,1]: {value}")
    for index, (lower, upper) in enumerate(zip(BIN_EDGES[:-1], BIN_EDGES[1:])):
        if lower <= value < upper or (index == len(BIN_LABELS) - 1 and value == 1.0):
            return BIN_LABELS[index]
    raise RuntimeError(f"confidence not covered by frozen intervals: {value}")


def load_inputs() -> tuple[pd.DataFrame, dict[str, str]]:
    for path, expected in EXPECTED_HASHES.items():
        require(path.is_file(), f"missing pinned input: {path}")
        actual = sha256_file(path)
        require(actual == expected, f"SHA-256 mismatch for {path}: {actual}")

    predictions = pd.read_parquet(
        PREDICTION,
        columns=[
            "race_id", "race_date", "evaluation_year", "horse_i", "horse_j",
            "jockey_id_candidate_calibrated_probability", "selected_jockey_id_candidate",
        ],
    )
    predictions["race_id"] = predictions["race_id"].map(canonical_id)
    normalize_dates(predictions, "race_date")
    predictions["evaluation_year"] = pd.to_numeric(predictions["evaluation_year"], errors="raise").astype(int)
    predictions["confidence"] = pd.to_numeric(
        predictions["jockey_id_candidate_calibrated_probability"], errors="raise"
    ).astype(float)
    predictions["selected"] = pd.to_numeric(predictions["selected_jockey_id_candidate"], errors="raise").astype(int)
    selected = predictions.loc[predictions["selected"] == 1].copy()
    require(len(selected) > 0, "no frozen selected-pair prediction rows")
    require(selected["race_id"].is_unique, "more than one selected pair per race")
    require((selected["race_date"].str[:4].astype(int) == selected["evaluation_year"]).all(), "prediction year/date mismatch")
    selected["selected_pair"] = [pair_text(a, b) for a, b in zip(selected["horse_i"], selected["horse_j"])]
    selected["bin"] = selected["confidence"].map(assign_bin)

    qpl_all = pd.read_csv(QPL_RETURNS, dtype=str, keep_default_na=False)
    qpl = qpl_all.loc[qpl_all["selector"] == "jockey_id_candidate"].copy()
    qpl["race_id"] = qpl["race_id"].map(canonical_id)
    normalize_dates(qpl, "race_date")
    qpl["year"] = pd.to_numeric(qpl["year"], errors="raise").astype(int)
    qpl["pair"] = [pair_text(a, b) for a, b in zip(qpl["horse_i"], qpl["horse_j"])]
    qpl["hit"] = pd.to_numeric(qpl["hit"], errors="raise").astype(int)
    qpl["source_stake"] = qpl["stake_krw"].map(parse_money)
    qpl["source_return"] = qpl["return_krw"].map(parse_money)
    qpl["odds"] = qpl["paid_qpl_odds"].map(parse_odds)
    require(qpl["race_id"].is_unique, "duplicate QPL race rows for frozen selector")

    qnl_all = pd.read_csv(QNL_RETURNS, dtype=str, keep_default_na=False)
    qnl = qnl_all.loc[(qnl_all["selector"] == "jockey_id_candidate") & (qnl_all["pool"] == "QNL")].copy()
    qnl["race_id"] = qnl["race_id"].map(canonical_id)
    normalize_dates(qnl, "race_date")
    qnl["year"] = pd.to_numeric(qnl["year"], errors="raise").astype(int)
    qnl["pair"] = qnl["ticket"].map(parse_qnl_ticket)
    qnl["hit"] = pd.to_numeric(qnl["exact_hit"], errors="raise").astype(int)
    qnl["source_stake"] = qnl["stake_krw"].map(parse_money)
    qnl["source_return"] = qnl["return_krw"].map(parse_money)
    qnl["odds"] = qnl["paid_dividend_odds"].map(parse_odds)
    require(qnl["race_id"].is_unique, "duplicate QNL race rows for frozen selector")

    require(len(qpl) == 1_142 and len(qnl) == 1_142, "verified payout cohort is not 1,142 races per pool")
    require(set(qpl["race_id"]) == set(qnl["race_id"]), "QPL and QNL race cohorts differ")
    require(set(qpl["year"]) == {2025, 2026} and set(qnl["year"]) == {2025, 2026}, "unexpected payout year")
    require(qpl.groupby("year").size().to_dict() == EXPECTED_RACES_BY_YEAR, "QPL year counts differ from frozen cohort")
    require(qnl.groupby("year").size().to_dict() == EXPECTED_RACES_BY_YEAR, "QNL year counts differ from frozen cohort")

    selected = selected.loc[selected["race_id"].isin(qpl["race_id"])].copy()
    require(len(selected) == 1_142, "selected-pair predictions do not cover all verified payout races")
    selected_pair_by_id = selected.set_index("race_id")["selected_pair"]
    qpl_pairs = qpl.set_index("race_id")["pair"]
    qnl_pairs = qnl.set_index("race_id")["pair"]
    require((selected_pair_by_id.reindex(qpl_pairs.index) == qpl_pairs).all(), "QPL selected-pair mismatch")
    require((selected_pair_by_id.reindex(qnl_pairs.index) == qnl_pairs).all(), "QNL selected-pair mismatch")

    prediction_dates = set(predictions["race_date"])
    qpl_date_by_id = qpl.set_index("race_id")["race_date"]
    qnl_date_by_id = qnl.set_index("race_id")["race_date"]
    selected_date_by_id = selected.set_index("race_id")["race_date"]
    require((selected_date_by_id.reindex(qpl_date_by_id.index) == qpl_date_by_id).all(), "QPL/prediction date mismatch")
    require((selected_date_by_id.reindex(qnl_date_by_id.index) == qnl_date_by_id).all(), "QNL/prediction date mismatch")

    pool_frames: list[pd.DataFrame] = []
    for name, source, stake in (("QPL", qpl, STAKE), ("QNL", qnl, SOURCE_QNL_STAKE)):
        joined = selected[["race_id", "race_date", "evaluation_year", "selected_pair", "confidence", "bin"]].merge(
            source[["race_id", "race_date", "year", "pair", "hit", "source_stake", "source_return", "odds"]],
            on="race_id", how="left", validate="one_to_one", suffixes=("_prediction", "_source"),
        )
        require(joined["pair"].notna().all(), f"missing {name} source rows")
        require((joined["race_date_prediction"] == joined["race_date_source"]).all(), f"{name} date mismatch")
        require((joined["evaluation_year"] == joined["year"]).all(), f"{name} year mismatch")
        require((joined["selected_pair"] == joined["pair"]).all(), f"{name} pair mismatch")
        require((joined["hit"].isin((0, 1))).all(), f"invalid {name} hit flag")
        require((joined["source_stake"] == stake).all(), f"unexpected {name} source stake")
        adjusted_returns: list[int] = []
        winning_odds: list[float | None] = []
        for row in joined.itertuples(index=False):
            if row.hit:
                require(row.odds > 0, f"winning {name} row has no paid dividend")
                source_payout = multiply_to_won(row.odds, row.source_stake)
                require(source_payout == row.source_return, f"{name} stored return disagrees with paid dividend")
                adjusted_returns.append(multiply_to_won(row.odds, STAKE))
                winning_odds.append(float(row.odds))
            else:
                require(row.source_return == 0, f"losing {name} row has nonzero return")
                adjusted_returns.append(0)
                winning_odds.append(None)
        joined["pool"] = name
        joined["stake_krw"] = STAKE
        joined["return_krw"] = adjusted_returns
        joined["net_krw"] = joined["return_krw"] - STAKE
        joined["paid_dividend_odds"] = winning_odds
        joined["year"] = joined["evaluation_year"].astype(int)
        joined["pair"] = joined["selected_pair"]
        joined["date"] = joined["race_date_prediction"]
        pool_frames.append(joined[[
            "pool", "race_id", "date", "year", "pair", "confidence", "bin", "hit",
            "paid_dividend_odds", "stake_krw", "return_krw", "net_krw", "source_stake", "source_return",
        ]])

    records = pd.concat(pool_frames, ignore_index=True)
    qpl_records = records.loc[records["pool"] == "QPL"]
    qnl_records = records.loc[records["pool"] == "QNL"]
    require(int(qpl_records["hit"].sum()) == 283 and int(qpl_records["return_krw"].sum()) == 7_764_000, "QPL baseline differs from verified study")
    require(int(qnl_records["hit"].sum()) == 145 and int(qnl_records["source_return"].sum()) == 5_236_800, "QNL baseline differs from verified study")
    require(int(qnl_records["return_krw"].sum()) == 8_728_000, "QNL exact 10,000 KRW scaling mismatch")
    require(prediction_dates and len(prediction_dates) >= 200, "prediction date inventory unexpectedly small")
    source_hashes = {str(path.relative_to(ROOT)): sha256_file(path) for path in EXPECTED_HASHES}
    source_hashes[str((STUDY / "PLAN.md").relative_to(ROOT))] = sha256_file(STUDY / "PLAN.md")
    source_hashes[str((STUDY / "analyze.py").relative_to(ROOT))] = sha256_file(STUDY / "analyze.py")
    return records, source_hashes


def safe_mean(values: pd.Series) -> float | None:
    return float(values.mean()) if len(values) else None


def make_stat_row(pool: str, scope: str, group_type: str, group: str, frame: pd.DataFrame, denominator: int) -> dict[str, object]:
    n = len(frame)
    hits = int(frame["hit"].sum()) if n else 0
    stake = int(frame["stake_krw"].sum()) if n else 0
    returned = int(frame["return_krw"].sum()) if n else 0
    hit_rate = hits / n if n else None
    recovery = returned / stake if stake else None
    roi = recovery - 1.0 if recovery is not None else None
    mean_odds = safe_mean(frame.loc[frame["hit"] == 1, "paid_dividend_odds"].astype(float)) if hits else None
    mean_p = safe_mean(frame["confidence"])
    return {
        "pool": pool,
        "scope": scope,
        "group_type": group_type,
        "group": group,
        "n_races": n,
        "scope_races": denominator,
        "coverage_pct": (100.0 * n / denominator) if denominator else None,
        "coverage_of_all_1142_pct": 100.0 * n / 1_142,
        "race_days": int(frame["date"].nunique()) if n else 0,
        "mean_saved_top3_probability": mean_p,
        "hits": hits,
        "hit_rate_pct": 100.0 * hit_rate if hit_rate is not None else None,
        "mean_paid_dividend_odds_on_hit": mean_odds,
        "stake_krw": stake,
        "return_krw": returned,
        "net_krw": returned - stake,
        "recovery_pct": 100.0 * recovery if recovery is not None else None,
        "net_roi_pct": 100.0 * roi if roi is not None else None,
        "qpl_hit_minus_mean_probability_pct": (100.0 * (hit_rate - mean_p)) if pool == "QPL" and n else None,
    }


def build_stats(records: pd.DataFrame, group_type: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for scope, scoped in (("all", records), ("2025", records.loc[records["year"] == 2025]), ("2026_partial", records.loc[records["year"] == 2026])):
        denominator = int(scoped["race_id"].nunique())
        for pool in ("QNL", "QPL"):
            pool_frame = scoped.loc[scoped["pool"] == pool]
            if group_type == "bin":
                groups = [(label, pool_frame.loc[pool_frame["bin"] == label]) for label in BIN_LABELS]
            else:
                groups = [("all_baseline" if threshold == 0 else f">={threshold:.2f}", pool_frame.loc[pool_frame["confidence"] >= threshold]) for threshold in THRESHOLDS]
            rows.extend(make_stat_row(pool, scope, group_type, group, frame, denominator) for group, frame in groups)
    return pd.DataFrame(rows)


def bootstrap_stats(records: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    receipt = json.loads(SCHEDULE_RECEIPT.read_text(encoding="utf-8"))
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "bootstrap receipt is not frozen")
    dates = sorted(pd.read_parquet(PREDICTION, columns=["race_date"])["race_date"].pipe(pd.to_datetime).dt.strftime("%Y-%m-%d").unique().tolist())
    require(len(dates) == 269, f"expected 269 original evaluation dates, found {len(dates)}")
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(date_hash == receipt.get("date_inventory_sha256"), "schedule date inventory does not match prediction cohort")
    schedule = np.load(SCHEDULE, allow_pickle=False)
    require(schedule.shape == (2000, 269) and schedule.dtype == np.int32, "saved bootstrap schedule shape/dtype mismatch")
    require(((schedule >= 0) & (schedule < len(dates))).all(), "bootstrap schedule has invalid date indices")
    date_index = {date: index for index, date in enumerate(dates)}
    rows: list[dict[str, object]] = []
    empty_counts: dict[str, int] = {}
    groups: list[tuple[str, str, str, pd.DataFrame]] = []
    for scope, scoped in (("all", records), ("2025", records.loc[records["year"] == 2025]), ("2026_partial", records.loc[records["year"] == 2026])):
        for pool in ("QNL", "QPL"):
            pool_frame = scoped.loc[scoped["pool"] == pool]
            for group in BIN_LABELS:
                groups.append((scope, pool, f"bin:{group}", pool_frame.loc[pool_frame["bin"] == group]))
            for threshold in THRESHOLDS:
                label = "all_baseline" if threshold == 0 else f">={threshold:.2f}"
                groups.append((scope, pool, f"threshold:{label}", pool_frame.loc[pool_frame["confidence"] >= threshold]))
    for scope, pool, group, frame in groups:
        day_n = np.zeros(269, dtype=np.int64)
        day_hit = np.zeros(269, dtype=np.int64)
        day_stake = np.zeros(269, dtype=np.int64)
        day_return = np.zeros(269, dtype=np.int64)
        for row in frame.itertuples(index=False):
            index = date_index[row.date]
            day_n[index] += 1
            day_hit[index] += int(row.hit)
            day_stake[index] += int(row.stake_krw)
            day_return[index] += int(row.return_krw)
        sampled_n = day_n[schedule].sum(axis=1)
        sampled_hits = day_hit[schedule].sum(axis=1)
        sampled_stake = day_stake[schedule].sum(axis=1)
        sampled_return = day_return[schedule].sum(axis=1)
        valid = sampled_n > 0
        key = f"{scope}|{pool}|{group}"
        empty_counts[key] = int((~valid).sum())
        if not valid.any():
            for metric in ("hit_rate_pct", "recovery_pct", "net_roi_pct"):
                rows.append({"scope": scope, "pool": pool, "group": group, "metric": metric, "ci_low_pct": None, "ci_high_pct": None, "valid_draws": 0, "empty_draws_dropped": 2000})
            continue
        draw_hit = 100.0 * sampled_hits[valid] / sampled_n[valid]
        draw_recovery = 100.0 * sampled_return[valid] / sampled_stake[valid]
        draw_roi = draw_recovery - 100.0
        for metric, values in (("hit_rate_pct", draw_hit), ("recovery_pct", draw_recovery), ("net_roi_pct", draw_roi)):
            low, high = np.percentile(values, [2.5, 97.5], method="linear")
            rows.append({"scope": scope, "pool": pool, "group": group, "metric": metric, "ci_low_pct": float(low), "ci_high_pct": float(high), "valid_draws": int(valid.sum()), "empty_draws_dropped": int((~valid).sum())})
    meta = {
        "schedule_path": str(SCHEDULE.relative_to(ROOT)),
        "schedule_sha256": sha256_file(SCHEDULE),
        "schedule_receipt_sha256": sha256_file(SCHEDULE_RECEIPT),
        "schedule_shape": list(schedule.shape),
        "date_count": len(dates),
        "date_inventory_sha256": date_hash,
        "percentiles": [2.5, 97.5],
        "method": "date-cluster percentile bootstrap; same 2,000 saved draws over 269 sorted 2024-2026 dates for every fixed mask; zero-selected draws dropped",
        "empty_draws_dropped_by_group": empty_counts,
    }
    return pd.DataFrame(rows), meta


def write_csv(frame: pd.DataFrame, name: str) -> str:
    path = STUDY / name
    frame.to_csv(path, index=False, encoding="utf-8")
    return sha256_file(path)


def fmt(value: object, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.{digits}f}"


def render_report(bin_stats: pd.DataFrame, threshold_stats: pd.DataFrame, bootstrap_ci: pd.DataFrame) -> tuple[str, str]:
    def find(frame: pd.DataFrame, **criteria: object) -> pd.Series:
        mask = pd.Series(True, index=frame.index)
        for key, value in criteria.items():
            mask &= frame[key] == value
        rows = frame.loc[mask]
        require(len(rows) == 1, f"expected one report row for {criteria}; got {len(rows)}")
        return rows.iloc[0]

    lines = [
        "# 확신 구간별 복승·복연 실현 수익 비교",
        "",
        "## 분석 범위와 해석",
        "",
        "고정 선택 방식은 `selected_jockey_id_candidate == 1`이며, 저장된 `jockey_id_candidate_calibrated_probability`로 확률 구간을 나눴다. 이 값은 선택된 두 말이 **함께 Top3에 들 확률**이다. QPL의 적중 사건과 뜻이 맞지만 QNL의 정확한 1·2착 확률은 아니다. 따라서 QNL은 같은 점수로 경주를 층화한 결과이며 QNL 확률 보정 성능으로 해석하지 않는다.",
        "",
        "배당이 기존 검증 자료에 있는 2025년 654경주와 2026-09-19까지 488경주, 총 1,142경주만 포함했다. 2024년은 배당 검증 범위 밖이다. 매 선택 경주에 복승 1장과 복연 1장을 각각 10,000원 샀다고 계산했다. QNL은 6,000원 원천 배당을 Decimal 곱셈으로 10,000원에 환산했고 원천 환급과 재대조했다. 미적중 환급은 0원이다.",
        "",
        "## 전체 기준선",
        "",
        "| 승식 | 경주 | 적중 | 적중률 | 투입 | 환급 | 손익 | ROI |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for pool in ("QNL", "QPL"):
        row = find(threshold_stats, pool=pool, scope="all", group="all_baseline")
        lines.append(f"| {pool} | {int(row.n_races):,} | {int(row.hits):,} | {fmt(row.hit_rate_pct)}% | ₩{int(row.stake_krw):,} | ₩{int(row.return_krw):,} | ₩{int(row.net_krw):,} | {fmt(row.net_roi_pct)}% |")
    lines += ["", "## 구간별 전체 기간 결과", ""]
    for pool in ("QNL", "QPL"):
        lines += [
            f"### {pool}",
            "",
            "| 확률 구간 | 경주 (coverage) | 적중 | 적중률 | 평균 저장 확률 | 적중 평균 배당 | 환급 | 손익 | ROI |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        subset = bin_stats.loc[(bin_stats["pool"] == pool) & (bin_stats["scope"] == "all")]
        for row in subset.itertuples(index=False):
            lines.append(
                f"| {row.group} | {int(row.n_races)} ({fmt(row.coverage_of_all_1142_pct)}%) | {int(row.hits)} | {fmt(row.hit_rate_pct)}% | {fmt(100.0 * row.mean_saved_top3_probability) if pd.notna(row.mean_saved_top3_probability) else '—'}% | {fmt(row.mean_paid_dividend_odds_on_hit)}배 | ₩{int(row.return_krw):,} | ₩{int(row.net_krw):,} | {fmt(row.net_roi_pct)}% |"
            )
        lines.append("")

    lines += [
        "## 누적 확신 기준",
        "",
        "| 선택 기준 | 경주 | QNL 적중률 | QNL ROI | QPL 적중률 | QPL ROI |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group in ("all_baseline", ">=0.10", ">=0.15", ">=0.20", ">=0.25", ">=0.30", ">=0.40", ">=0.50"):
        qnl = find(threshold_stats, pool="QNL", scope="all", group=group)
        qpl = find(threshold_stats, pool="QPL", scope="all", group=group)
        lines.append(f"| {group} | {int(qnl.n_races)} | {fmt(qnl.hit_rate_pct)}% | {fmt(qnl.net_roi_pct)}% | {fmt(qpl.hit_rate_pct)}% | {fmt(qpl.net_roi_pct)}% |")

    lines += ["", "## 연도별 누적 기준", ""]
    for pool in ("QNL", "QPL"):
        lines += [f"### {pool}", "", "| 기간 | 기준 | 경주 | 적중 | 적중률 | 적중 평균 배당 | ROI |", "|---|---|---:|---:|---:|---:|---:|"]
        for scope, label in (("2025", "2025"), ("2026_partial", "2026 부분연도")):
            for group in ("all_baseline", ">=0.20", ">=0.30", ">=0.40", ">=0.50"):
                row = find(threshold_stats, pool=pool, scope=scope, group=group)
                lines.append(f"| {label} | {group} | {int(row.n_races)} | {int(row.hits)} | {fmt(row.hit_rate_pct)}% | {fmt(row.mean_paid_dividend_odds_on_hit)}배 | {fmt(row.net_roi_pct)}% |")
        lines.append("")

    lines += [
        "## 날짜 군집 재표집 불확실성",
        "",
        "기존 고정 2,000×269 날짜 부트스트랩 배열을 그대로 사용했다. 원래 2024–2026 평가 날짜 전체에서 날짜를 복원추출한 뒤 2025/2026 연도와 사전 고정 구간 조건을 적용했다. 선택 경주가 0인 반복은 버렸고 0으로 대체하지 않았다. 아래 구간은 95% percentile CI이며, 과거 표본 내부 불확실성이지 미래 검증이 아니다.",
        "",
        "| 승식 | 기준 | 적중률 95% CI | ROI 95% CI | 유효 반복 / 제외 반복 |",
        "|---|---|---:|---:|---:|",
    ]
    for pool in ("QNL", "QPL"):
        for group in (">=0.20", ">=0.30", ">=0.40", ">=0.50"):
            hit = find(bootstrap_ci, pool=pool, scope="all", group=f"threshold:{group}", metric="hit_rate_pct")
            roi = find(bootstrap_ci, pool=pool, scope="all", group=f"threshold:{group}", metric="net_roi_pct")
            lines.append(f"| {pool} | {group} | {fmt(hit.ci_low_pct)}–{fmt(hit.ci_high_pct)}% | {fmt(roi.ci_low_pct)}–{fmt(roi.ci_high_pct)}% | {int(roi.valid_draws)} / {int(roi.empty_draws_dropped)} |")

    lines += [
        "",
        "## 관찰과 제한",
        "",
        "- 전체 구간에서 확신값이 커질수록 QPL 적중률은 대체로 상승했지만, 높은 구간의 배당 하락 때문에 ROI는 함께 계속 상승하지 않았다. QPL 평균 적중배당은 전체 2.74배에서 0.50 이상 1.40배로 낮아졌다. QPL 적중률은 선택 사건에 대한 평균 확률과 비교할 수 있으나, 표본이 13경주인 최상단 구간은 불확실성이 크다.",
        "- QNL의 전체 기준 ROI는 -23.57%다. `p ≥ 0.40`은 +5.90%였지만 61경주뿐이고 95% ROI 구간은 음수부터 큰 양수까지 넓다. 연도별로 2025년 18경주 +59.44%, 2026년 부분 기간 43경주 -16.51%로 방향도 달랐다. `p ≥ 0.50`은 13경주에서 -30.77%였다.",
        "- 누적 조건의 실현 ROI가 단조롭지 않으며, 관측 기간을 반복 사용한 후향 결과다. 경계는 결과를 보고 바꾸지 않았고 특정 컷오프를 추천하거나 미래 이익을 보장하지 않는다. 고정 배당 환급은 실제 매수로 시장 배당이 변하는 효과도 반영하지 않는다.",
        "",
        "재현: 저장소 루트에서 `.venv/bin/python -B jeju/research/20261013_pair_confidence_returns_v1/analyze.py`. `bin_stats.csv`, `threshold_stats.csv`, `race_returns.csv`, `bootstrap_ci.csv`에 전체 수치가 있다. `SOURCE_HASHES.json`은 입력 검증 해시를 기록한다. SQLite는 열지 않았고 네트워크·학습·DB 쓰기는 없었다.",
    ]
    report = "\n".join(lines) + "\n"
    readme = """# 제주 pair 확신 구간별 QNL/QPL 실현 수익

확신값 구간마다 고정 `jockey_id_candidate` 선택쌍의 복승(QNL) 및 복연(QPL) 적중·환급·ROI를 비교한다. 전체 해석과 결과표는 [publication/REPORT.md](publication/REPORT.md), 고정 경계는 [PLAN.md](PLAN.md)를 본다.

재현은 저장소 루트에서 `.venv/bin/python -B jeju/research/20261013_pair_confidence_returns_v1/analyze.py`를 실행한다. 결과 CSV와 입력 SHA-256은 같은 폴더에 저장한다. 저장된 2024–2026 날짜 bootstrap schedule만 읽고, SQLite·네트워크·학습은 사용하지 않았다.
"""
    return readme, report


def main() -> None:
    require(STUDY.resolve().is_relative_to(ROOT), "study path escaped repository")
    records, source_hashes = load_inputs()
    bin_stats = build_stats(records, "bin")
    threshold_stats = build_stats(records, "threshold")
    bootstrap_ci, bootstrap_meta = bootstrap_stats(records)

    race_returns = records.sort_values(["date", "race_id", "pool"]).rename(columns={
        "date": "race_date", "pair": "selected_pair", "confidence": "saved_top3_probability", "bin": "confidence_bin", "hit": "exact_hit",
    })[[
        "pool", "race_id", "race_date", "year", "selected_pair", "saved_top3_probability", "confidence_bin",
        "exact_hit", "paid_dividend_odds", "source_stake", "source_return", "stake_krw", "return_krw", "net_krw",
    ]]
    output_hashes = {
        "bin_stats.csv": write_csv(bin_stats, "bin_stats.csv"),
        "threshold_stats.csv": write_csv(threshold_stats, "threshold_stats.csv"),
        "race_returns.csv": write_csv(race_returns, "race_returns.csv"),
        "bootstrap_ci.csv": write_csv(bootstrap_ci, "bootstrap_ci.csv"),
    }
    readme, publication_report = render_report(bin_stats, threshold_stats, bootstrap_ci)
    (STUDY / "publication").mkdir(exist_ok=True)
    (STUDY / "README.md").write_text(readme, encoding="utf-8")
    (STUDY / "publication/REPORT.md").write_text(publication_report, encoding="utf-8")
    output_hashes["README.md"] = sha256_file(STUDY / "README.md")
    output_hashes["publication/REPORT.md"] = sha256_file(STUDY / "publication/REPORT.md")
    total = records.groupby("pool").agg(races=("race_id", "nunique"), hits=("hit", "sum"), stake_krw=("stake_krw", "sum"), return_krw=("return_krw", "sum"), net_krw=("net_krw", "sum")).reset_index()
    total["hit_rate_pct"] = 100.0 * total["hits"] / total["races"]
    total["net_roi_pct"] = 100.0 * total["net_krw"] / total["stake_krw"]
    year_counts = records.loc[records["pool"] == "QPL"].groupby("year")["race_id"].nunique().to_dict()
    report = {
        "status": "COMPUTED",
        "objective": "Compare exact Top2 QNL and pair Top3 QPL realized returns across fixed confidence bins and cumulative cutoffs.",
        "confidence_definition": "jockey_id_candidate_calibrated_probability: probability both selected horses finish Top3; not exact-Top2/QNL probability.",
        "selection": "selected_jockey_id_candidate == 1; frozen pair from prediction rows.",
        "cohort": {"races": 1142, "year_counts": {str(year): int(count) for year, count in year_counts.items()}, "years": "2025 plus 2026 through 2026-09-19", "coverage_by_year_matches_expected": True},
        "fixed_bins": list(BIN_LABELS),
        "fixed_cumulative_thresholds": ["all_baseline"] + [f">={t:.2f}" for t in THRESHOLDS if t > 0],
        "units": {"stake_per_race_krw": STAKE, "QNL_source_stake_krw": SOURCE_QNL_STAKE, "QNL_scaling": "paid dividend odds × 10,000 KRW using Decimal; source 6,000 KRW payout independently reconciled"},
        "baseline_reconciliation": total.to_dict(orient="records"),
        "qpl_calibration_interpretation": "Only QPL exact pair Top3 hits share the saved confidence event; qpl_hit_minus_mean_probability_pct is descriptive. QNL is stratified on this score, not calibrated to it.",
        "bootstrap": bootstrap_meta,
        "source_sha256": source_hashes,
        "output_sha256": output_hashes,
        "limitations": [
            "Retrospective repeatedly inspected development period; no independent future validation.",
            "Confidence intervals resample dates from the fixed 2024-2026 cohort and do not establish future profitability.",
            "High-confidence groups can be sparse; thresholds are descriptive and were not selected for profitability.",
            "Historical published payouts are applied at fixed stake and do not model market impact or execution changes.",
        ],
    }
    report_path = STUDY / "REPORT.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    source_manifest = {
        "source_sha256": source_hashes,
        "output_sha256": {**output_hashes, "REPORT.json": sha256_file(report_path)},
        "read_policy": {"sqlite": "not opened", "network": False, "model_fit": False, "database_write": False},
    }
    (STUDY / "SOURCE_HASHES.json").write_text(json.dumps(source_manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "COMPUTED", "races": 1142, "summary": total.to_dict(orient="records"), "outputs": output_hashes, "bootstrap": bootstrap_meta}, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

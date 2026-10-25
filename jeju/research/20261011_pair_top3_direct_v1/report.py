#!/usr/bin/env python3
"""Fixed date-cluster uncertainty and pair-probability reporting."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import xlogy


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
OUT = STUDY / "outputs"
FEATURE_PATH = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
PREDICTION_PATH = OUT / "evaluation_pair_predictions.parquet"
RACE_DIAGNOSTICS_PATH = OUT / "evaluation_race_probabilities.parquet"
PREDICTION_RECEIPT_PATH = OUT / "prediction_receipt.json"
FIT_RECEIPT_PATH = OUT / "fit_receipt.json"
SCHEDULE_PATH = OUT / "date_bootstrap_schedule.npy"
SCHEDULE_RECEIPT_PATH = OUT / "date_bootstrap_schedule.json"
REPORT_PATH = OUT / "REPORT.json"
REPORT_RECEIPT_PATH = OUT / "REPORT_RECEIPT.json"
README_PATH = STUDY / "README.md"
SEED = 20261011
DRAWS = 2000
EXPECTED_DATES = 269
POLICIES = {
    "direct_pair_model": "selected_candidate",
    "H2_calibrated_p0_baseline": "selected_baseline",
    "raw_F1_STYLE6_score_Top2": "selected_raw_top2",
    "saved_F1_STYLE6_PTop3_Top2": "selected_saved_f1_top2",
    "existing_candidate_joint_marginal_Top2": "selected_candidate_joint_marginal_top2",
    "existing_candidate_maximum_joint_pair": "selected_candidate_joint_maxpair",
    "existing_matched_maximum_joint_pair": "selected_matched_joint_maxpair",
}
RELIABILITY_BINS = ((0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 1.0))
RELIABILITY_NAMES = ("[0,.05)", "[.05,.10)", "[.10,.20)", "[.20,.30)", "[.30,1]")


class ReportError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReportError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.exists(), f"refusing to overwrite report artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    require(not temp.exists(), f"temporary report exists: {temp}")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def prepare_bootstrap() -> None:
    require(not SCHEDULE_PATH.exists() and not SCHEDULE_RECEIPT_PATH.exists(), "bootstrap schedule already exists")
    features = pd.read_parquet(FEATURE_PATH, columns=["race_id", "race_date", "year"])
    features = features.loc[features["year"].isin((2024, 2025, 2026))].copy()
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    require(features["race_date"].notna().all(), "invalid date while preparing bootstrap schedule")
    dates = sorted(features["race_date"].drop_duplicates().tolist())
    require(len(dates) == EXPECTED_DATES, f"evaluation date count mismatch: {len(dates)}")
    rng = np.random.default_rng(SEED)
    schedule = rng.integers(0, len(dates), size=(DRAWS, len(dates)), endpoint=False, dtype=np.int32)
    OUT.mkdir(parents=True, exist_ok=True)
    temp = SCHEDULE_PATH.with_suffix(".npy.tmp")
    require(not temp.exists(), f"temporary schedule exists: {temp}")
    with temp.open("wb") as handle:
        np.save(handle, schedule, allow_pickle=False)
    temp.replace(SCHEDULE_PATH)
    receipt = {
        "status": "FROZEN_BEFORE_EVALUATION_METRICS",
        "generator": "numpy.random.default_rng",
        "bit_generator": type(rng.bit_generator).__name__,
        "seed": SEED,
        "numpy_version": np.__version__,
        "draws": DRAWS,
        "dates_per_draw": len(dates),
        "schedule_shape": list(schedule.shape),
        "date_inventory_sha256": hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest(),
        "date_min": dates[0],
        "date_max": dates[-1],
        "schedule_sha256": sha256_file(SCHEDULE_PATH),
        "source_features_sha256": sha256_file(FEATURE_PATH),
    }
    write_json_once(SCHEDULE_RECEIPT_PATH, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def load_bootstrap() -> tuple[list[str], np.ndarray, dict[str, Any]]:
    require(SCHEDULE_PATH.is_file() and SCHEDULE_RECEIPT_PATH.is_file(), "frozen bootstrap schedule missing")
    receipt = json.loads(SCHEDULE_RECEIPT_PATH.read_text(encoding="utf-8"))
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "bootstrap was not frozen before metrics")
    require(receipt.get("seed") == SEED and receipt.get("draws") == DRAWS, "bootstrap recipe changed")
    require(receipt.get("numpy_version") == np.__version__, "NumPy version changed")
    require(sha256_file(SCHEDULE_PATH) == receipt.get("schedule_sha256"), "bootstrap schedule hash mismatch")
    features = pd.read_parquet(FEATURE_PATH, columns=["race_id", "race_date", "year"])
    features = features.loc[features["year"].isin((2024, 2025, 2026))].copy()
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    dates = sorted(features["race_date"].drop_duplicates().tolist())
    require(len(dates) == EXPECTED_DATES, "bootstrap date roster changed")
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(date_hash == receipt.get("date_inventory_sha256"), "bootstrap date hash mismatch")
    schedule = np.load(SCHEDULE_PATH, allow_pickle=False)
    require(schedule.shape == (DRAWS, len(dates)) and schedule.dtype == np.int32, "bootstrap shape/dtype mismatch")
    require(((schedule >= 0) & (schedule < len(dates))).all(), "invalid date index in schedule")
    rng = np.random.default_rng(SEED)
    expected = rng.integers(0, len(dates), size=(DRAWS, len(dates)), endpoint=False, dtype=np.int32)
    require(np.array_equal(schedule, expected), "schedule does not match the frozen RNG recipe")
    return dates, schedule, receipt


def add_date_index(frame: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    result = frame.copy()
    result["race_date"] = pd.to_datetime(result["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    require(result["race_date"].notna().all(), "invalid date in evaluation artifact")
    mapping = {value: index for index, value in enumerate(dates)}
    require(result["race_date"].isin(mapping).all(), "evaluation date outside bootstrap roster")
    result["_date_index"] = result["race_date"].map(mapping).astype(int)
    return result


def date_ci(frame: pd.DataFrame, value_col: str, dates: list[str], schedule: np.ndarray) -> dict[str, Any]:
    if frame.empty:
        return {"estimate": None, "ci_low": None, "ci_high": None, "valid_draws": 0, "undefined_draws": DRAWS}
    sums = np.zeros(len(dates), dtype=float)
    counts = np.zeros(len(dates), dtype=float)
    for idx, row in frame.groupby("_date_index")[value_col].agg(["sum", "count"]).iterrows():
        sums[int(idx)] = float(row["sum"])
        counts[int(idx)] = float(row["count"])
    denominator = counts[schedule].sum(axis=1)
    numerator = sums[schedule].sum(axis=1)
    valid = denominator > 0
    replicates = numerator[valid] / denominator[valid]
    return {
        "estimate": float(frame[value_col].mean()),
        "ci_low": float(np.quantile(replicates, 0.025)) if len(replicates) else None,
        "ci_high": float(np.quantile(replicates, 0.975)) if len(replicates) else None,
        "valid_draws": int(valid.sum()),
        "undefined_draws": int((~valid).sum()),
    }


def losses(probability: pd.Series, labels: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    p = np.clip(probability.to_numpy(dtype=float), 1e-15, 1 - 1e-15)
    y = labels.to_numpy(dtype=float)
    log_loss = -(y * np.log(p) + (1 - y) * np.log1p(-p))
    return (p - y) ** 2, log_loss


def race_equal_scores(frame: pd.DataFrame, probability_col: str) -> dict[str, float]:
    brier, log_loss = losses(frame[probability_col], frame["y_pair"])
    work = frame[["race_id"]].copy()
    work["brier"] = brier
    work["log_loss"] = log_loss
    race = work.groupby("race_id", sort=True)[["brier", "log_loss"]].mean()
    return {"brier": float(race["brier"].mean()), "log_loss": float(race["log_loss"].mean()), "races": int(len(race))}


def reliability(frame: pd.DataFrame, probability_col: str, all_pairs: bool) -> list[dict[str, Any]]:
    work = frame[["race_id", probability_col, "y_pair"]].copy()
    work["p"] = work[probability_col].astype(float)
    work["weight"] = 1.0 / work.groupby("race_id")["race_id"].transform("size") if all_pairs else 1.0
    rows: list[dict[str, Any]] = []
    for (lower, upper), name in zip(RELIABILITY_BINS, RELIABILITY_NAMES, strict=True):
        selected = work.loc[work["p"].ge(lower) & (work["p"].le(upper) if upper == 1.0 else work["p"].lt(upper))]
        if selected.empty:
            rows.append({"bin": name, "pairs": 0, "races": 0, "predicted": None, "observed": None, "total_weight": 0.0})
        else:
            weight = selected["weight"].to_numpy(dtype=float)
            total = float(weight.sum())
            rows.append({
                "bin": name, "pairs": int(len(selected)), "races": int(selected["race_id"].nunique()),
                "predicted": float(np.dot(weight, selected["p"].to_numpy(dtype=float)) / total),
                "observed": float(np.dot(weight, selected["y_pair"].to_numpy(dtype=float)) / total),
                "total_weight": total,
            })
    return rows


def one_selected_per_race(pairs: pd.DataFrame, selector: str) -> pd.DataFrame:
    selected = pairs.loc[pairs[selector].eq(1)].copy()
    require(len(selected) == pairs["race_id"].nunique() and not selected["race_id"].duplicated().any(), f"invalid selector: {selector}")
    return selected


def group_report(races: pd.DataFrame, mask: pd.Series, dates: list[str], schedule: np.ndarray) -> dict[str, Any]:
    frame = races.loc[mask].copy()
    require(not frame.empty, "empty year/distance group")
    result: dict[str, Any] = {"races": int(len(frame)), "dates": int(frame["race_date"].nunique()), "policies": {}}
    for policy in POLICIES:
        result["policies"][policy] = {"hits": int(frame[policy].sum()), "hit_rate": float(frame[policy].mean())}
    for policy in POLICIES:
        if policy == "direct_pair_model":
            continue
        col = f"direct_minus_{policy}"
        frame[col] = frame["direct_pair_model"].astype(float) - frame[policy].astype(float)
        result["policies"][policy]["paired_difference_direct_minus_comparator"] = date_ci(frame, col, dates, schedule)
    return result


def fmt_pct(value: float | None) -> str:
    return "정의되지 않음" if value is None else f"{100*value:.2f}%"


def fmt_pp(value: float | None) -> str:
    return "정의되지 않음" if value is None else f"{100*value:+.2f}%p"


def render_readme(report: dict[str, Any]) -> str:
    hit = report["pair_hit_rate_by_policy"]
    paired = report["paired_date_cluster_differences_direct_minus_comparator"]
    gate = report["primary_gate"]
    lines = [
        "# 제주 Top3 pair 직접모형 평가",
        "",
        "저장된 F1_STYLE6 점수와 여섯 style 입력으로 학습한 대칭 pair 전용모형을 동일한 역사 평가 경주에서 비교했다. 평가기간은 2024-01-05~2026-09-19이며, 2026년은 9월까지의 부분연도다. 이 평가는 반복 개발 표본이며 새 holdout은 아니다. 예측 pair 확률은 공동 Top3 분포가 아니므로 경주별 모든 pair 확률의 합이 3으로 보장되지 않는다.",
        "",
        f"평가 코호트는 {report['races']:,}경주, {report['race_dates']:,}경주일, {report['pair_rows']:,}개 무순서 pair다. 각 경주에서 각 방식은 pair 하나를 선택했다.",
        "",
        "## Pair 적중률",
        "",
        "| 방식 | 적중 | 경주 | 적중률 | 차이 95% CI (전용−해당 방식, %p) |",
        "|---|---:|---:|---:|---:|",
    ]
    for policy, values in hit.items():
        ci_text = "—"
        if policy != "direct_pair_model":
            ci = paired[policy]
            if ci["ci_low"] is not None:
                ci_text = f"{fmt_pp(ci['ci_low'])} ~ {fmt_pp(ci['ci_high'])}"
        lines.append(f"| {policy} | {values['hits']:,} | {values['races']:,} | {fmt_pct(values['hit_rate'])} | {ci_text} |")
    primary = paired["raw_F1_STYLE6_score_Top2"]
    diff = hit["direct_pair_model"]["hit_rate"] - hit["raw_F1_STYLE6_score_Top2"]["hit_rate"]
    change = report["selection_change_vs_raw_score_top2"]
    gate_conclusion = (
        "이 반복 개발 표본에서 사전 정의한 pair 선택 개선 신호를 확인했다. 새 시점의 holdout에서 추가 검증이 필요하다."
        if gate["passed"] else
        "이 반복 개발 표본에서 사전 정의한 pair 선택 개선 신호를 확인하지 못했다. 현재 결과만으로는 이 모형을 적용 방식으로 채택하지 않는다."
    )
    lines += [
        "",
        f"Primary gate: {'통과' if gate['passed'] else '미통과'}. Direct 모델의 전체 pair hit-rate가 raw-score Top2보다 높고 paired date-cluster 95% CI 하한도 0보다 커야 통과다. 차이는 {100*diff:+.2f}%p, CI {fmt_pp(primary['ci_low'])} ~ {fmt_pp(primary['ci_high'])}다 (유효 {primary['valid_draws']:,}, 분모 0 미정의 {primary['undefined_draws']:,}회). {gate_conclusion}",
        f"Direct 모델은 raw-score Top2와 {change['races_with_pair_changed_vs_raw_top2']}경주에서 다른 pair를 골랐고, 변경된 경주 안의 성적 차이는 +{change['gains_on_changed_races']}승 / -{change['losses_on_changed_races']}패 / {change['ties_on_changed_races']}동률이다.",
        "",
        "## 확률 품질 진단",
        "",
        "| 모델/선택 | Brier | Log loss |",
        "|---|---:|---:|",
    ]
    probs = report["probability_quality_separate_diagnostics"]
    for model in ("candidate", "baseline"):
        for kind in ("all_pair", "selected_pair"):
            metric = probs[model][kind]
            lines.append(f"| {model} / {kind} | {metric['brier']:.5f} | {metric['log_loss']:.5f} |")
    lines += ["", "선택확률 0.20 이상 구간은 사전 고정 임계값이며 적중률과 coverage를 함께 표시했다.", ""]
    for model, item in report["selected_probability_at_least_0_20"].items():
        ci = item["date_cluster_ci"]
        ci_text = "정의되지 않음" if ci["ci_low"] is None else f"{fmt_pct(ci['ci_low'])} ~ {fmt_pct(ci['ci_high'])}"
        lines.append(f"- {model}: coverage {item['coverage_count']:,}/{item['selected_races']:,} ({fmt_pct(item['coverage'])}), 적중률 {fmt_pct(item['hit_rate'])}, CI {ci_text}; 미정의 반복 {ci['undefined_draws']:,}회")
    lines += [
        "",
        "## 연도별 pair 적중률",
        "",
        "| 연도 | 경주 | 경주일 | Direct | Raw Top2 | 저장 F1 PTop3 Top2 | Joint 주변확률 Top2 | Candidate 최대 pair | Matched 최대 pair |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year, item in report["hit_rate_groups_with_global_date_bootstrap"]["by_year"].items():
        policies = item["policies"]
        cells = [
            policies["direct_pair_model"]["hit_rate"],
            policies["raw_F1_STYLE6_score_Top2"]["hit_rate"],
            policies["saved_F1_STYLE6_PTop3_Top2"]["hit_rate"],
            policies["existing_candidate_joint_marginal_Top2"]["hit_rate"],
            policies["existing_candidate_maximum_joint_pair"]["hit_rate"],
            policies["existing_matched_maximum_joint_pair"]["hit_rate"],
        ]
        lines.append(f"| {year} | {item['races']:,} | {item['dates']:,} | " + " | ".join(fmt_pct(value) for value in cells) + " |")
    distance_groups = report["hit_rate_groups_with_global_date_bootstrap"]["by_distance_m"]
    lines += [
        "",
        "거리별 세부표는 outputs/REPORT.json에 있다. 경주가 100회 미만이거나 경주일이 20일 미만인 거리는 희소 하위집단으로 해석하며 확정적 비교로 보지 않는다.",
        "",
    ]
    sparse = [f"{distance}m (N={item['races']}, 날짜={item['dates']})" for distance, item in distance_groups.items() if item["races"] < 100 or item["dates"] < 20]
    if sparse:
        lines.append("희소 거리 하위집단: " + "; ".join(sparse) + ".")
    lines += [
        "",
        "연도·거리별 적중률과 paired CI, all-pair 및 선택 pair reliability bins, pair 확률 합 편차는 outputs/REPORT.json에서 확인할 수 있다. 높은 확신 구간은 방식별 coverage가 다를 수 있다. 이 결과는 삼복승 조합 완성도, 정확 Top2 또는 수익을 학습 목표로 삼지 않았다.",
        "",
    ]
    return "\n".join(lines)


def run_report() -> None:
    require(not REPORT_PATH.exists() and not REPORT_RECEIPT_PATH.exists() and not README_PATH.exists(), "report outputs already exist")
    require(FIT_RECEIPT_PATH.is_file() and PREDICTION_RECEIPT_PATH.is_file(), "fit/prediction receipt missing")
    fit_receipt = json.loads(FIT_RECEIPT_PATH.read_text(encoding="utf-8"))
    prediction_receipt = json.loads(PREDICTION_RECEIPT_PATH.read_text(encoding="utf-8"))
    require(fit_receipt.get("status") == "PASS" and prediction_receipt.get("status") == "PASS", "fit or prediction did not pass")
    require(prediction_receipt.get("performance_metrics_computed") is False, "prediction stage already computed metrics")
    require(sha256_file(PREDICTION_PATH) == prediction_receipt.get("evaluation_pair_predictions_sha256"), "pair prediction hash changed")
    require(sha256_file(RACE_DIAGNOSTICS_PATH) == prediction_receipt.get("race_probability_diagnostics_sha256"), "race diagnostic hash changed")
    dates, schedule, schedule_receipt = load_bootstrap()

    # Outcome labels are opened only after fit/calibration receipts and the
    # seed/date resampling schedule have been fixed.
    pairs = pd.read_parquet(PREDICTION_PATH)
    require(len(pairs) == int(prediction_receipt["prediction_rows"]), "pair row count changed")
    require(set(POLICIES.values()).issubset(pairs.columns), "one or more fixed selector columns are missing")
    require(len(pairs["race_id"].unique()) == 1779 and pairs["race_date"].nunique() == EXPECTED_DATES, "evaluation race/date inventory changed")
    require(((pairs["y_pair"] == 0) | (pairs["y_pair"] == 1)).all(), "pair labels are not binary")
    require((pairs.groupby("race_id")["y_pair"].sum() == 3).all(), "pair labels lack exactly three positives per race")
    pairs = add_date_index(pairs, dates)

    races = pairs.groupby(["race_id", "race_date", "evaluation_year", "distance_m"], as_index=False, sort=True).size().drop(columns="size")
    for policy, selector in POLICIES.items():
        selected = one_selected_per_race(pairs, selector)
        race_hit = selected[["race_id", "y_pair"]].rename(columns={"y_pair": policy})
        races = races.merge(race_hit, on="race_id", how="inner", validate="one_to_one")
    races = add_date_index(races, dates)
    require(len(races) == 1779, "race-level selection coverage changed")

    overall = {
        policy: {"hits": int(races[policy].sum()), "races": int(len(races)), "hit_rate": float(races[policy].mean())}
        for policy in POLICIES
    }
    paired: dict[str, Any] = {}
    for policy in POLICIES:
        if policy == "direct_pair_model":
            continue
        diff_col = f"direct_minus_{policy}"
        races[diff_col] = races["direct_pair_model"].astype(float) - races[policy].astype(float)
        paired[policy] = date_ci(races, diff_col, dates, schedule)
    primary_ci = paired["raw_F1_STYLE6_score_Top2"]
    candidate_selected = one_selected_per_race(pairs, "selected_candidate").set_index("race_id")
    raw_selected = one_selected_per_race(pairs, "selected_raw_top2").set_index("race_id")
    changed_race_ids = candidate_selected.index[candidate_selected["horse_i"].ne(raw_selected["horse_i"]) | candidate_selected["horse_j"].ne(raw_selected["horse_j"])]
    raw_diff = races["direct_pair_model"].astype(int) - races["raw_F1_STYLE6_score_Top2"].astype(int)
    selection_change_diagnostic = {
        "races_with_pair_changed_vs_raw_top2": int(len(changed_race_ids)),
        "gains_on_changed_races": int(((raw_diff == 1) & races["race_id"].isin(changed_race_ids)).sum()),
        "losses_on_changed_races": int(((raw_diff == -1) & races["race_id"].isin(changed_race_ids)).sum()),
        "ties_on_changed_races": int(((raw_diff == 0) & races["race_id"].isin(changed_race_ids)).sum()),
    }
    gate_pass = bool(
        overall["direct_pair_model"]["hit_rate"] > overall["raw_F1_STYLE6_score_Top2"]["hit_rate"]
        and primary_ci["ci_low"] is not None and primary_ci["ci_low"] > 0.0
    )

    probabilities: dict[str, Any] = {}
    for label, probability_col, selector in (
        ("candidate", "candidate_calibrated_probability", "selected_candidate"),
        ("baseline", "baseline_calibrated_probability", "selected_baseline"),
    ):
        selected = one_selected_per_race(pairs, selector)
        probabilities[label] = {
            "all_pair": race_equal_scores(pairs, probability_col),
            "selected_pair": race_equal_scores(selected, probability_col),
            "all_pair_reliability": reliability(pairs, probability_col, True),
            "selected_pair_reliability": reliability(selected, probability_col, False),
        }

    diagnostics = pd.read_parquet(RACE_DIAGNOSTICS_PATH)
    require(len(diagnostics) == 1779 and diagnostics["race_id"].nunique() == 1779, "race probability diagnostic coverage changed")
    sum_diagnostics: dict[str, Any] = {}
    for label, column in (
        ("candidate", "candidate_sum_calibrated_pair_probability_minus_3"),
        ("baseline", "baseline_sum_calibrated_pair_probability_minus_3"),
    ):
        values = diagnostics[column].to_numpy(dtype=float)
        absolute = np.abs(values)
        sum_diagnostics[label] = {
            "races": int(len(values)),
            "signed_mean": float(np.mean(values)),
            "signed_median": float(np.median(values)),
            "absolute_mean": float(np.mean(absolute)),
            "absolute_median": float(np.median(absolute)),
            "absolute_p95": float(np.quantile(absolute, 0.95)),
            "absolute_max": float(np.max(absolute)),
        }

    groups: dict[str, Any] = {"by_year": {}, "by_distance_m": {}}
    for year in sorted(races["evaluation_year"].unique().tolist()):
        groups["by_year"][str(int(year))] = group_report(races, races["evaluation_year"].eq(year), dates, schedule)
    for distance in sorted(races["distance_m"].unique().tolist()):
        distance_group = group_report(races, races["distance_m"].eq(distance), dates, schedule)
        distance_group["sparse_subgroup"] = bool(distance_group["races"] < 100 or distance_group["dates"] < 20)
        distance_group["sparse_rule"] = "N<100 races or fewer than 20 dates"
        groups["by_distance_m"][str(int(distance))] = distance_group

    confidence: dict[str, Any] = {}
    for label, selector, probability_col in (
        ("candidate", "selected_candidate", "candidate_calibrated_probability"),
        ("baseline", "selected_baseline", "baseline_calibrated_probability"),
    ):
        selected = one_selected_per_race(pairs, selector)
        confident = selected.loc[selected[probability_col].ge(0.20)].copy()
        confidence[label] = {
            "threshold": 0.20,
            "selected_races": int(len(selected)),
            "coverage_count": int(len(confident)),
            "coverage": float(len(confident) / len(selected)),
            "dates": int(confident["race_date"].nunique()),
            "hit_rate": float(confident["y_pair"].mean()) if len(confident) else None,
            "date_cluster_ci": date_ci(confident, "y_pair", dates, schedule),
            "by_year": {},
            "by_distance_m": {},
        }
        for year in sorted(selected["evaluation_year"].unique().tolist()):
            subset = confident.loc[confident["evaluation_year"].eq(year)]
            confidence[label]["by_year"][str(int(year))] = {
                "selected_races": int(selected["evaluation_year"].eq(year).sum()),
                "coverage_count": int(len(subset)),
                "hit_rate": float(subset["y_pair"].mean()) if len(subset) else None,
                "date_cluster_ci": date_ci(subset, "y_pair", dates, schedule),
            }
        for distance in sorted(selected["distance_m"].unique().tolist()):
            subset = confident.loc[confident["distance_m"].eq(distance)]
            confidence[label]["by_distance_m"][str(int(distance))] = {
                "selected_races": int(selected["distance_m"].eq(distance).sum()),
                "coverage_count": int(len(subset)),
                "hit_rate": float(subset["y_pair"].mean()) if len(subset) else None,
                "date_cluster_ci": date_ci(subset, "y_pair", dates, schedule),
            }

    report = {
        "study": "20261011_pair_top3_direct_v1",
        "evaluation_scope": "historical repeated development cohort; not a new holdout",
        "races": int(len(races)),
        "race_dates": int(races["race_date"].nunique()),
        "pair_rows": int(len(pairs)),
        "positive_pair_labels": int(pairs["y_pair"].sum()),
        "pair_hit_rate_by_policy": overall,
        "paired_date_cluster_differences_direct_minus_comparator": paired,
        "selection_change_vs_raw_score_top2": selection_change_diagnostic,
        "primary_gate": {
            "candidate_hit_rate_exceeds_raw_score_top2": overall["direct_pair_model"]["hit_rate"] > overall["raw_F1_STYLE6_score_Top2"]["hit_rate"],
            "paired_95pct_ci_lower_above_zero": primary_ci["ci_low"] is not None and primary_ci["ci_low"] > 0.0,
            "passed": gate_pass,
            "difference_ci": primary_ci,
            "bootstrap_draws": DRAWS,
        },
        "probability_quality_separate_diagnostics": probabilities,
        "sum_pair_probability_minus_three_diagnostics": sum_diagnostics,
        "selected_probability_at_least_0_20": confidence,
        "hit_rate_groups_with_global_date_bootstrap": groups,
        "bootstrap": {**schedule_receipt, "date_order": dates},
        "fit_receipt_sha256": sha256_file(FIT_RECEIPT_PATH),
        "prediction_receipt_sha256": sha256_file(PREDICTION_RECEIPT_PATH),
        "prediction_sha256": sha256_file(PREDICTION_PATH),
        "race_diagnostics_sha256": sha256_file(RACE_DIAGNOSTICS_PATH),
    }
    write_json_once(REPORT_PATH, report)
    readme = render_readme(report)
    require(not README_PATH.exists(), f"refusing to overwrite study README: {README_PATH}")
    README_PATH.write_text(readme, encoding="utf-8")
    receipt = {
        "status": "PASS",
        "study": "20261011_pair_top3_direct_v1",
        "report_sha256": sha256_file(REPORT_PATH),
        "readme_sha256": sha256_file(README_PATH),
        "report_runner_sha256": sha256_file(Path(__file__).resolve()),
        "prediction_sha256": sha256_file(PREDICTION_PATH),
        "fit_receipt_sha256": sha256_file(FIT_RECEIPT_PATH),
        "bootstrap_schedule_sha256": sha256_file(SCHEDULE_PATH),
        "bootstrap_schedule_receipt_sha256": sha256_file(SCHEDULE_RECEIPT_PATH),
        "numpy_version": np.__version__,
        "performance_metrics_computed": True,
    }
    write_json_once(REPORT_RECEIPT_PATH, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(readme)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare-bootstrap", "report"))
    args = parser.parse_args()
    try:
        prepare_bootstrap() if args.stage == "prepare-bootstrap" else run_report()
        return 0
    except Exception as error:
        print(f"REPORT_RUN_FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

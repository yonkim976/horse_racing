"""Report the frozen jockey-ID candidate against all saved pair comparators."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
OUT = STUDY / "outputs"
BASE = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
DIAGNOSTICS = OUT / "evaluation_race_probabilities.parquet"
PREDICTION_RECEIPT = OUT / "PREDICTION_RECEIPT.json"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
APPROVAL = OUT / "APPROVAL.json"
PREFLIGHT = OUT / "SOURCE_PREFLIGHT.json"
DRY_RUN = OUT / "DESIGN_DRY_RUN.json"
REPORT_PATH = OUT / "REPORT.json"
REPORT_RECEIPT = OUT / "REPORT_RECEIPT.json"
README = STUDY / "README.md"
MANIFEST = STUDY / "ARTIFACT_MANIFEST.json"
BASE_REPORT = BASE / "outputs/REPORT.json"
DIRECT_REPORT = DIRECT / "report.py"
DIRECT_SCHEDULE = DIRECT / "outputs/date_bootstrap_schedule.npy"
DIRECT_SCHEDULE_RECEIPT = DIRECT / "outputs/date_bootstrap_schedule.json"
EXPECTED_SCHEDULE_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]
POLICIES = {
    "jockey_id_candidate": ("selected_jockey_id_candidate", "jockey_id_candidate_calibrated_probability"),
    "jockey_basic_candidate": ("selected_jockey_basic_candidate", "candidate_calibrated_probability"),
    "latest_expanded_direct_pair_427": ("selected_latest_pair", "latest_pair_calibrated_probability"),
    "old_direct_pair_426": ("selected_old_direct", "old_direct_calibrated_probability"),
    "H2_calibrated_p0_baseline": ("selected_baseline", "baseline_calibrated_probability"),
    "raw_F1_STYLE6_score_Top2_429": ("selected_raw_top2", None),
    "saved_F1_STYLE6_PTop3_Top2_429": ("selected_saved_f1_top2", None),
    "existing_joint_marginal_Top2_434": ("selected_candidate_joint_marginal_top2", None),
    "existing_candidate_max_joint_pair_422": ("selected_candidate_joint_maxpair", None),
    "existing_matched_max_joint_pair_429": ("selected_matched_joint_maxpair", None),
}
PROBABILITY_MODELS = {
    "jockey_id_candidate": ("jockey_id_candidate_calibrated_probability", "selected_jockey_id_candidate"),
    "jockey_basic_candidate": ("candidate_calibrated_probability", "selected_jockey_basic_candidate"),
    "latest_expanded_direct_pair": ("latest_pair_calibrated_probability", "selected_latest_pair"),
    "old_direct_pair": ("old_direct_calibrated_probability", "selected_old_direct"),
    "H2_calibrated_p0_baseline": ("baseline_calibrated_probability", "selected_baseline"),
}


class ReportError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ReportError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"input symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    require(spec is not None and spec.loader is not None, f"cannot load frozen report helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_sources() -> tuple[dict[str, Any], dict[str, Any], Any, list[str], np.ndarray, dict[str, Any]]:
    prediction_receipt = json.loads(checked(PREDICTION_RECEIPT).read_text(encoding="utf-8"))
    fit_receipt = json.loads(checked(FIT_RECEIPT).read_text(encoding="utf-8"))
    fit = json.loads(checked(FIT_PATH).read_text(encoding="utf-8"))
    approval = json.loads(checked(APPROVAL).read_text(encoding="utf-8"))
    preflight = json.loads(checked(PREFLIGHT).read_text(encoding="utf-8"))
    dry_run = json.loads(checked(DRY_RUN).read_text(encoding="utf-8"))
    require(prediction_receipt.get("status") == "PASS" and prediction_receipt.get("prediction_rows") == 76848
            and prediction_receipt.get("prediction_races") == 1779
            and prediction_receipt.get("evaluation_dates") == 269, "candidate prediction receipt is not PASS")
    require(sha256(PREDICTIONS) == prediction_receipt.get("pair_predictions_sha256")
            and sha256(DIAGNOSTICS) == prediction_receipt.get("race_diagnostics_sha256"),
            "candidate prediction artifact hash mismatch")
    require(fit.get("status") == "PASS" and fit_receipt.get("status") == "PASS"
            and fit_receipt.get("candidate_fit_sha256") == sha256(FIT_PATH), "candidate fit lineage changed")
    require(approval.get("approved") is True and approval.get("approved_by") == "root"
            and fit.get("approval_sha256") == sha256(APPROVAL), "root fit approval lineage changed")
    require(preflight.get("status") == "PASS" and dry_run.get("status") == "PASS"
            and dry_run.get("optimizer_runs") == 0, "pre-fit source/design gate changed")
    for relative, expected in preflight.get("source_hashes", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"pinned source changed: {relative}")
    require(sha256(DIRECT_SCHEDULE) == EXPECTED_SCHEDULE_SHA,
            "frozen paired date-bootstrap schedule changed")
    report_helper = import_module("frozen_direct_pair_report_for_jockey_id", DIRECT_REPORT)
    dates, schedule, schedule_receipt = report_helper.load_bootstrap()
    require(sha256(DIRECT_REPORT) == "ad07cf566020edbb6f9e924b3fc0211c4ad917391ab9ba434bf34cba786bdc1f",
            "frozen bootstrap/report helper changed")
    require(not REPORT_PATH.exists() and not REPORT_RECEIPT.exists() and not README.exists() and not MANIFEST.exists(),
            "report outputs already exist")
    return prediction_receipt, fit, report_helper, dates, schedule, schedule_receipt


def selected_races(report_helper, pairs: pd.DataFrame, selector: str, dates: list[str]) -> pd.DataFrame:
    selected = report_helper.one_selected_per_race(pairs, selector)
    require(selected["race_id"].is_unique, f"selector repeats race: {selector}")
    result = selected[["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j", "y_pair"]].copy()
    return report_helper.add_date_index(result, dates)


def compare_hits(report_helper, races: pd.DataFrame, candidate: pd.DataFrame, comparator: pd.DataFrame,
                 comparator_name: str, dates: list[str], schedule: np.ndarray) -> dict[str, Any]:
    pair_changed = candidate.merge(comparator, on="race_id", suffixes=("_candidate", "_comparator"),
                                   validate="one_to_one")
    changed = pair_changed["horse_i_candidate"].ne(pair_changed["horse_i_comparator"]) \
        | pair_changed["horse_j_candidate"].ne(pair_changed["horse_j_comparator"])
    difference = pair_changed["y_pair_candidate"].astype(float) - pair_changed["y_pair_comparator"].astype(float)
    pair_changes = pd.DataFrame({"race_id": pair_changed["race_id"], "difference": difference,
                                 "pair_changed": changed})
    frame = races[["race_id", "race_date", "evaluation_year", "distance_m", "_date_index"]].copy()
    frame = frame.merge(pair_changes, on="race_id", how="inner", validate="one_to_one")
    require(len(frame) == len(races), "paired hit changes do not cover every race")
    ci = report_helper.date_ci(frame, "difference", dates, schedule)
    return {
        "comparator": comparator_name,
        "candidate_hits": int(candidate["y_pair"].sum()),
        "comparator_hits": int(comparator["y_pair"].sum()),
        "races": int(len(races)), "point_difference": float(frame["difference"].mean()),
        "paired_date_bootstrap_95pct_ci": ci,
        "selection_changes": {
            "races_with_pair_changed": int(frame["pair_changed"].sum()),
            "gains_on_changed_races": int(((frame["difference"].eq(1.0)) & frame["pair_changed"]).sum()),
            "losses_on_changed_races": int(((frame["difference"].eq(-1.0)) & frame["pair_changed"]).sum()),
            "ties_on_changed_races": int(((frame["difference"].eq(0.0)) & frame["pair_changed"]).sum()),
        },
    }


def score_policy_hits(pairs: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, dict[str, pd.DataFrame]]:
    rates: dict[str, Any] = {}
    selected: dict[str, pd.DataFrame] = {}
    race_hits = pairs[["race_id", "race_date", "evaluation_year", "distance_m"]].drop_duplicates().copy()
    require(len(race_hits) == 1779 and race_hits["race_id"].is_unique, "race-level key changed")
    for name, (selector, _) in POLICIES.items():
        frame = pairs.loc[pairs[selector].eq(1)].copy()
        require(len(frame) == 1779 and frame["race_id"].is_unique, f"selection count changed: {name}")
        selected[name] = frame
        hit = frame[["race_id", "y_pair"]].rename(columns={"y_pair": name})
        race_hits = race_hits.merge(hit, on="race_id", how="inner", validate="one_to_one")
        rates[name] = {"hits": int(frame["y_pair"].sum()), "races": int(len(frame)), "hit_rate": float(frame["y_pair"].mean())}
    return rates, race_hits, selected


def run_report() -> None:
    prediction_receipt, fit, report_helper, dates, schedule, schedule_receipt = validate_sources()
    pairs = pd.read_parquet(checked(PREDICTIONS))
    require(len(pairs) == 76848 and pairs["race_id"].nunique() == 1779
            and pairs["race_date"].nunique() == 269, "evaluation pair cohort changed")
    require((pairs.groupby("race_id")["y_pair"].sum() == 3).all(), "pair label arithmetic changed")
    pairs = report_helper.add_date_index(pairs, dates)
    rates, race_hits, selected = score_policy_hits(pairs)
    race_hits = report_helper.add_date_index(race_hits, dates)
    require(rates["jockey_basic_candidate"]["hits"] == 429,
            "saved rolling comparator no longer reports the frozen 429 hits")

    saved_report = json.loads(checked(BASE_REPORT).read_text(encoding="utf-8"))
    old_rates = saved_report["pair_hit_rate_by_policy"]
    for name in POLICIES:
        if name == "jockey_id_candidate":
            continue
        previous = old_rates[name]
        require(rates[name]["hits"] == int(previous["hits"]) and rates[name]["races"] == int(previous["races"]),
                f"saved comparator changed: {name}")
        require(math.isclose(rates[name]["hit_rate"], float(previous["hit_rate"]), rel_tol=0.0, abs_tol=1e-15),
                f"saved comparator rate changed: {name}")

    candidate_selected = selected["jockey_id_candidate"]
    comparisons: dict[str, Any] = {}
    for name, comparator in selected.items():
        if name == "jockey_id_candidate":
            continue
        candidate_rows = selected_races(report_helper, pairs, POLICIES["jockey_id_candidate"][0], dates)
        comparator_rows = selected_races(report_helper, pairs, POLICIES[name][0], dates)
        comparisons[name] = compare_hits(report_helper, race_hits, candidate_rows, comparator_rows,
                                         name, dates, schedule)
    primary = comparisons["jockey_basic_candidate"]
    secondary = comparisons["raw_F1_STYLE6_score_Top2_429"]
    primary_ci = primary["paired_date_bootstrap_95pct_ci"]
    secondary_ci = secondary["paired_date_bootstrap_95pct_ci"]
    primary_pass = bool(primary["point_difference"] > 0 and primary_ci["ci_low"] is not None and primary_ci["ci_low"] > 0)
    secondary_pass = bool(secondary["point_difference"] > 0 and secondary_ci["ci_low"] is not None and secondary_ci["ci_low"] > 0)

    quality: dict[str, Any] = {}
    confidence: dict[str, Any] = {}
    for model, (probability, selector) in PROBABILITY_MODELS.items():
        selected_frame = report_helper.one_selected_per_race(pairs, selector)
        quality[model] = {
            "all_pair": report_helper.race_equal_scores(pairs, probability),
            "selected_pair": report_helper.race_equal_scores(selected_frame, probability),
            "all_pair_reliability": report_helper.reliability(pairs, probability, True),
            "selected_pair_reliability": report_helper.reliability(selected_frame, probability, False),
        }
        confident = selected_frame.loc[selected_frame[probability].ge(0.20)].copy()
        confident = report_helper.add_date_index(confident, dates)
        confidence[model] = {
            "threshold": 0.20, "selected_races": int(len(selected_frame)),
            "coverage_count": int(len(confident)), "coverage": float(len(confident) / len(selected_frame)),
            "hit_rate": float(confident["y_pair"].mean()) if len(confident) else None,
            "date_cluster_ci": report_helper.date_ci(confident, "y_pair", dates, schedule),
        }

    diagnostics = pd.read_parquet(checked(DIAGNOSTICS))
    require(len(diagnostics) == 1779 and diagnostics["race_id"].is_unique, "race diagnostics row count changed")
    probability_sums: dict[str, Any] = {}
    probability_sum_columns = {
        "jockey_id_candidate": "jockey_id_candidate_sum_probability_minus_3",
        "jockey_basic_candidate": "jockey_basic_candidate_sum_probability_minus_3",
        "latest_expanded_direct_pair": "latest_pair_sum_probability_minus_3",
        "old_direct_pair": "old_direct_candidate_sum_calibrated_pair_probability_minus_3",
        "H2_calibrated_p0_baseline": "baseline_sum_calibrated_pair_probability_minus_3",
    }
    for model, column in probability_sum_columns.items():
        values = diagnostics[column].to_numpy(dtype=float)
        absolute = np.abs(values)
        probability_sums[model] = {
            "races": int(len(values)), "signed_mean": float(values.mean()),
            "absolute_mean": float(absolute.mean()), "absolute_median": float(np.median(absolute)),
            "absolute_p95": float(np.quantile(absolute, 0.95)), "absolute_max": float(absolute.max()),
        }

    years: dict[str, Any] = {}
    for year in (2024, 2025, 2026):
        subset = race_hits.loc[race_hits["evaluation_year"].eq(year)].copy()
        entry = {name: {"hits": int(subset[name].sum()), "races": len(subset),
                        "hit_rate": float(subset[name].mean())} for name in POLICIES}
        entry["candidate_minus_saved_rolling"] = report_helper.date_ci(
            subset.assign(difference=subset["jockey_id_candidate"].astype(float)
                          - subset["jockey_basic_candidate"].astype(float)),
            "difference", dates, schedule,
        )
        entry["candidate_minus_raw429"] = report_helper.date_ci(
            subset.assign(difference=subset["jockey_id_candidate"].astype(float)
                          - subset["raw_F1_STYLE6_score_Top2_429"].astype(float)),
            "difference", dates, schedule,
        )
        years[str(year)] = entry

    distances: dict[str, Any] = {}
    for distance in sorted(race_hits["distance_m"].unique().tolist()):
        subset = race_hits.loc[race_hits["distance_m"].eq(distance)].copy()
        distances[str(int(distance))] = {
            "races": int(len(subset)), "dates": int(subset["race_date"].nunique()),
            "candidate_hits": int(subset["jockey_id_candidate"].sum()),
            "saved_rolling_hits": int(subset["jockey_basic_candidate"].sum()),
            "raw_top2_hits": int(subset["raw_F1_STYLE6_score_Top2_429"].sum()),
            "candidate_hit_rate": float(subset["jockey_id_candidate"].mean()),
            "saved_rolling_hit_rate": float(subset["jockey_basic_candidate"].mean()),
            "candidate_minus_saved_rolling_date_ci": report_helper.date_ci(
                subset.assign(difference=subset["jockey_id_candidate"].astype(float)
                              - subset["jockey_basic_candidate"].astype(float)),
                "difference", dates, schedule,
            ),
            "sparse_subgroup": bool(len(subset) < 100 or subset["race_date"].nunique() < 20),
        }

    report = {
        "study": STUDY.name,
        "study_description": "F1_STYLE6 말 평가와 저장 rolling365 기수 입력을 고정하고, H1-only official jockey ID effect-coded categorical pair main effect를 추가한 단일 공동 적합",
        "evaluation_scope": "반복 개발자료 2024-01-05~2026-09-19; independent future holdout 아님",
        "candidate_input": {
            "formula": "eta=logit(p0)+z_style20·beta+z_rolling·gamma+W_jockey·theta; W=(u−K*pi)/sigma",
            "vocabulary": "각 fold H1에서 관측된 공식 jockey ID 39개만; ID 이름/숫자 크기는 입력 아님",
            "rare_id_handling": "전체 H1 vocabulary 유지; 최소 support 52 starts; pooling 없음",
            "unknown_id_handling": "H1-vocabulary 밖 runner의 category contribution 정확히 0",
            "reported_effect": "alpha_r=theta_r/sigma_r−sum(pi_k*theta_k/sigma_k); H1 weighted-centered runner logit association",
            "rolling_input": "저장 365d rolling basic feature와 H1 moments 재사용; candidate β/γ/θ 공동 재적합",
            "model": "race-equal BCE + unit ridge on standardized coefficients; no explicit intercept",
        },
        "races": int(len(race_hits)), "race_dates": int(race_hits["race_date"].nunique()),
        "pair_rows": int(len(pairs)), "positive_pair_labels": int(pairs["y_pair"].sum()),
        "pair_hit_rate_by_policy": rates,
        "candidate_minus_fixed_comparator_date_bootstrap": comparisons,
        "primary_incremental_gate_vs_saved_rolling_429": {
            **primary, "point_estimate_above_zero": primary["point_difference"] > 0,
            "ci_lower_above_zero": primary_ci["ci_low"] is not None and primary_ci["ci_low"] > 0,
            "passed": primary_pass,
        },
        "secondary_raw429_gate": {
            **secondary, "point_estimate_above_zero": secondary["point_difference"] > 0,
            "ci_lower_above_zero": secondary_ci["ci_low"] is not None and secondary_ci["ci_low"] > 0,
            "passed": secondary_pass,
        },
        "both_predeclared_gates_passed": bool(primary_pass and secondary_pass),
        "probability_quality_separate_diagnostics": quality,
        "selected_probability_at_least_0_20": confidence,
        "sum_pair_probability_minus_three_diagnostics": probability_sums,
        "hit_rate_by_year": years, "hit_rate_by_distance_m": distances,
        "bootstrap": {
            "schedule_sha256": sha256(DIRECT_SCHEDULE), "draws": int(schedule.shape[0]),
            "dates": int(schedule.shape[1]), "seed": int(schedule_receipt["seed"]),
            "numpy_version": str(schedule_receipt["numpy_version"]),
            "date_min": dates[0], "date_max": dates[-1],
        },
        "frozen_basic_report_sha256": sha256(BASE_REPORT),
        "fit_receipt_sha256": sha256(FIT_RECEIPT), "prediction_receipt_sha256": sha256(PREDICTION_RECEIPT),
        "pair_predictions_sha256": sha256(PREDICTIONS), "race_diagnostics_sha256": sha256(DIAGNOSTICS),
        "source_preflight_sha256": sha256(PREFLIGHT), "approval_sha256": sha256(APPROVAL),
        "interpretation_limits": [
            "범주 효과는 전체기간 고정효과가 아니라 각 평가 fold의 H1-only event ID 연관성이다.",
            "표준화 계수 theta에 lambda=1이 적용되며 raw alpha 효과의 유효 penalty는 sigma와 support에 따라 달라진다.",
            "기수 배정/결과의 최초 공개 timestamp는 없고 현재 event snapshot을 사용했다.",
            "과거 평가는 반복 개발자료이며 독립 미래 holdout이 아니다.",
            "eligible starts는 정상완주 완전 편성 저장 cohort에 한정되고 사용자 제외 말 3005648·400m 제외를 유지한다.",
        ],
    }
    write_json_once(REPORT_PATH, report)

    primary_text = primary["point_difference"]
    primary_ci_low = primary_ci["ci_low"]
    primary_ci_high = primary_ci["ci_high"]
    secondary_ci_low = secondary_ci["ci_low"]
    secondary_ci_high = secondary_ci["ci_high"]
    lines = [
        "# 제주 F1_STYLE6 두 말 동시 Top3 pair 기수 ID categorical 비교", "",
        "저장 F1_STYLE6 말 점수와 기존 20 style pair basis, rolling365 jockey scalar·moments를 고정하고, 각 fold H1에서만 정의한 공식 기수 ID categorical main effect 39열을 추가해 기존 21열과 함께 joint fit했다. H1 pair moments는 경주 균등이며 `W_r=(u_r−K*pi_r)/sigma_r`; H1 밖 ID의 categorical runner effect는 0이다. 최소 H1 support는 52 eligible starts였고 rare pooling은 하지 않았다. 기수 ID 값의 크기와 이름은 입력으로 쓰지 않았다.", "",
        f"평가 코호트는 {len(race_hits):,}경주·{race_hits['race_date'].nunique():,}경주일·{len(pairs):,} unordered pair다. 반복 개발기간이며 2026년은 9월까지의 부분연도다.", "",
        "## 사전 지정 비교", "",
        f"Primary incremental: ID candidate {rates['jockey_id_candidate']['hits']}/{len(race_hits)} − 저장 rolling candidate 429/1,779 = {100*primary_text:+.3f}%p (date-bootstrap 95% CI {100*primary_ci_low:+.3f}~{100*primary_ci_high:+.3f}%p); {'통과' if primary_pass else '미통과'}.",
        f"Secondary raw Top2: ID candidate {rates['jockey_id_candidate']['hits']}/{len(race_hits)} − raw Top2 429/1,779 = {100*secondary['point_difference']:+.3f}%p (95% CI {100*secondary_ci_low:+.3f}~{100*secondary_ci_high:+.3f}%p); {'통과' if secondary_pass else '미통과'}.",
        f"두 사전 gate 모두 통과: {'예' if primary_pass and secondary_pass else '아니오'}. 저장 rolling 대비 pair 선택이 다른 경주 {primary['selection_changes']['races_with_pair_changed']}개 중 +{primary['selection_changes']['gains_on_changed_races']}승/−{primary['selection_changes']['losses_on_changed_races']}패/{primary['selection_changes']['ties_on_changed_races']}동률.", "",
        "| 저장 비교 방식 | 적중 | 경주 | 적중률 |", "|---|---:|---:|---:|",
    ]
    for name, value in rates.items():
        lines.append(f"| {name} | {value['hits']:,} | {value['races']:,} | {100*value['hit_rate']:.2f}% |")
    lines += [
        "", "## 확률과 하위집단 진단", "",
        "All-pair/selected-pair Brier·log loss, fixed reliability bins, 선택확률 0.20 이상 coverage·적중률, 연도·거리별 paired 차이, probability sum 진단은 `outputs/REPORT.json`에 보존했다. 날짜 bootstrap은 기존 seed·2,000회·269일 schedule을 그대로 썼다.", "",
        "## 범주 계수와 해석", "",
        "fold별 전체 `theta`와 weighted-centered runner `alpha`는 `outputs/FIT.json`에 ID별 H1 support와 함께 저장했다. Ridge는 standardized basis coefficient에 적용되어 원시 alpha의 유효 penalty가 ID support와 sigma에 따라 달라진다. 결과는 관측 기수-ID 연관성이며 기수 능력 또는 인과효과로 해석하지 않는다.", "",
        "## 제한", "",
        "기수 변경·마방·상호작용·희귀 ID pooling·추가 tuning은 포함하지 않았다. 결과 게시 timestamp가 없어 과거 기수 snapshot의 사전 가용성은 검증하지 못했다. 이 후향 평가와 반복 개발자료만으로 운영 반영을 정당화하지 않는다.", "",
    ]
    require(not README.exists() and not README.is_symlink(), "README output already exists")
    with README.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))

    receipt = {
        "status": "PASS", "study": STUDY.name, "performance_metrics_computed": True,
        "report_sha256": sha256(REPORT_PATH), "readme_sha256": sha256(README),
        "report_code_sha256": sha256(Path(__file__).resolve()),
        "pair_predictions_sha256": sha256(PREDICTIONS), "bootstrap_schedule_sha256": sha256(DIRECT_SCHEDULE),
        "primary_incremental_gate_passed": primary_pass, "secondary_raw429_gate_passed": secondary_pass,
    }
    write_json_once(REPORT_RECEIPT, receipt)
    write_manifest(prediction_receipt, schedule_receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


def write_manifest(prediction_receipt: dict[str, Any], schedule_receipt: dict[str, Any]) -> None:
    external: dict[str, dict[str, Any]] = {}

    def add(path: Path, expected: str | None = None) -> None:
        resolved = checked(path)
        digest = sha256(resolved)
        if expected is not None:
            require(digest == expected, f"external source hash changed: {resolved.relative_to(ROOT)}")
        external[str(resolved.relative_to(ROOT))] = {"sha256": digest, "bytes": resolved.stat().st_size}

    preflight = json.loads(checked(PREFLIGHT).read_text(encoding="utf-8"))
    for relative, expected in preflight["source_hashes"].items():
        add(ROOT / relative, expected)
    predecessor_manifest_path = BASE / "ARTIFACT_MANIFEST.json"
    predecessor_manifest = json.loads(checked(predecessor_manifest_path).read_text(encoding="utf-8"))
    predecessor_inputs = predecessor_manifest.get("source_inputs_sha256")
    require(isinstance(predecessor_inputs, dict) and len(predecessor_inputs) == 42,
            "predecessor source-input lock is missing or changed")
    for relative, expected in predecessor_inputs.items():
        add(ROOT / relative, expected)
    add(predecessor_manifest_path)
    for year in ("2024", "2025", "2026"):
        source = prediction_receipt["evaluation_score_sources"][year]
        add(ROOT / source["score_path"], source["score_sha256"])
        add(ROOT / source["meta_path"], source["meta_sha256"])
    for path, expected in (
        (DIRECT_REPORT, "ad07cf566020edbb6f9e924b3fc0211c4ad917391ab9ba434bf34cba786bdc1f"),
        (DIRECT_SCHEDULE, EXPECTED_SCHEDULE_SHA),
        (DIRECT_SCHEDULE_RECEIPT, schedule_receipt["schedule_receipt_sha256"] if "schedule_receipt_sha256" in schedule_receipt else None),
        (BASE / "pair_jockey_fit.py", None), (BASE / "pair_jockey_predict.py", None),
        (BASE / "pair_jockey_report.py", None), (BASE / "jockey_input.py", None),
        (ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1/pair_fit.py", None),
        (ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1/pair_predict.py", None),
        (ROOT / "jeju/research/20261011_pair_top3_direct_v1/core.py", None),
    ):
        add(path, expected)
    local_files = []
    for path in sorted(
        p for p in STUDY.rglob("*")
        if p.is_file() and p != MANIFEST and "__pycache__" not in p.parts
        and "publication_preparation" not in p.parts
    ):
        checked(path)
        local_files.append({"path": str(path.relative_to(STUDY)), "sha256": sha256(path), "bytes": path.stat().st_size})
    require(not MANIFEST.exists() and not MANIFEST.is_symlink(), "artifact manifest already exists")
    write_json_once(MANIFEST, {
        "status": "PASS", "study": STUDY.name, "generated_at": "2026-10-12",
        "local_artifacts": local_files, "external_sources": dict(sorted(external.items())),
        "runtime_dependencies": {
            "python": platform.python_version(), "numpy": np.__version__,
            "pandas": pd.__version__, "scipy": scipy.__version__,
        },
        "manifest_self_hash_excluded": True,
    })


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] != "report":
        raise SystemExit("usage: pair_jockey_id_report.py report")
    run_report()


if __name__ == "__main__":
    main()


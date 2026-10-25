"""Apply the frozen date bootstrap to saved jockey-pair predictions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
OUT = STUDY / "outputs"
BASE = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
BASE_OUT = BASE / "outputs"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
DIRECT_REPORT = DIRECT / "report.py"
DIRECT_SCHEDULE = DIRECT / "outputs/date_bootstrap_schedule.npy"
DIRECT_SCHEDULE_RECEIPT = DIRECT / "outputs/date_bootstrap_schedule.json"
PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
DIAGNOSTICS = OUT / "evaluation_race_probabilities.parquet"
PREDICTION_RECEIPT = OUT / "PREDICTION_RECEIPT.json"
FIT = OUT / "FIT.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
REPORT = OUT / "REPORT.json"
REPORT_RECEIPT = OUT / "REPORT_RECEIPT.json"
README = STUDY / "README.md"
MANIFEST = STUDY / "ARTIFACT_MANIFEST.json"
EXPECTED_REPORT_HELPER = "ad07cf566020edbb6f9e924b3fc0211c4ad917391ab9ba434bf34cba786bdc1f"
EXPECTED_SCHEDULE = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"

POLICIES = {
    "jockey_basic_candidate": "selected_jockey_basic_candidate",
    "latest_expanded_direct_pair_427": "selected_latest_pair",
    "old_direct_pair_426": "selected_old_direct",
    "H2_calibrated_p0_baseline": "selected_baseline",
    "raw_F1_STYLE6_score_Top2_429": "selected_raw_top2",
    "saved_F1_STYLE6_PTop3_Top2_429": "selected_saved_f1_top2",
    "existing_joint_marginal_Top2_434": "selected_candidate_joint_marginal_top2",
    "existing_candidate_max_joint_pair_422": "selected_candidate_joint_maxpair",
    "existing_matched_max_joint_pair_429": "selected_matched_joint_maxpair",
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
    require(path.resolve().is_relative_to(STUDY), f"output escaped study: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def import_module(name: str, path: Path):
    path = checked(path)
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load report helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_prediction_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    prediction = json.loads(checked(PREDICTION_RECEIPT).read_text(encoding="utf-8"))
    fit_receipt = json.loads(checked(FIT_RECEIPT).read_text(encoding="utf-8"))
    approval = json.loads(checked(OUT / "APPROVAL.json").read_text(encoding="utf-8"))
    source_preflight = json.loads(checked(OUT / "SOURCE_PREFLIGHT.json").read_text(encoding="utf-8"))
    require(prediction.get("status") == "PASS" and prediction.get("performance_metrics_computed") is False,
            "prediction receipt must be metrics-free PASS")
    require(prediction.get("prediction_code_sha256") == sha256(STUDY / "pair_jockey_predict.py"),
            "prediction code hash mismatch")
    require(prediction.get("input_helper_sha256") == sha256(STUDY / "jockey_input.py"),
            "approved rolling helper changed")
    require(prediction.get("source_preflight_sha256") == sha256(OUT / "SOURCE_PREFLIGHT.json"),
            "source preflight hash mismatch")
    require(source_preflight.get("status") == "PASS" and source_preflight.get("finish_labels_read") is False,
            "source preflight changed or is not metrics-free")
    require(approval.get("approved") is True and approval.get("approved_by") == "root"
            and approval.get("source_preflight_sha256") == sha256(OUT / "SOURCE_PREFLIGHT.json"),
            "root approval/source preflight lineage mismatch")
    require(fit_receipt.get("status") == "PASS"
            and fit_receipt.get("candidate_fit_sha256") == sha256(FIT)
            and fit_receipt.get("approval_sha256") == sha256(OUT / "APPROVAL.json"),
            "candidate fit receipt/hash mismatch")
    require(prediction.get("fit_receipt_sha256") == sha256(FIT_RECEIPT), "fit receipt changed after prediction")
    require(prediction.get("pair_predictions_sha256") == sha256(PREDICTIONS)
            and prediction.get("race_diagnostics_sha256") == sha256(DIAGNOSTICS),
            "evaluation prediction artifact hash mismatch")
    for relative, expected in source_preflight.get("source_hashes", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"preflight source changed: {relative}")
    return prediction, source_preflight


def external_source_hashes(prediction: dict[str, Any], source_preflight: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}

    def add(path: Path, expected: str | None = None) -> None:
        resolved = checked(path)
        digest = sha256(resolved)
        if expected is not None:
            require(digest == expected, f"source hash changed: {resolved.relative_to(ROOT)}")
        hashes[str(resolved.relative_to(ROOT))] = digest

    for relative, expected in source_preflight["source_hashes"].items():
        add(ROOT / relative, expected)
    for path in (
        BASE / "pair_fit.py", BASE / "pair_predict.py", BASE / "expanded_report.py",
        BASE_OUT / "expanded_h1_fit.json", BASE_OUT / "expanded_h2_calibration.json",
        BASE_OUT / "PAIR_FIT_RECEIPT.json", BASE_OUT / "HISTORICAL_REFIT_RECEIPT.json",
        BASE_OUT / "HISTORICAL_SOURCE_LOCK.json", BASE_OUT / "evaluation_race_probabilities.parquet",
        DIRECT / "core.py", DIRECT_REPORT, DIRECT_SCHEDULE, DIRECT_SCHEDULE_RECEIPT,
        ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/style_history_lineage.parquet",
    ):
        add(path)
    lock = json.loads(checked(BASE_OUT / "HISTORICAL_SOURCE_LOCK.json").read_text(encoding="utf-8"))
    require(lock.get("status") == "PASS", "frozen baseline source lock not PASS")
    for relative, expected in lock.get("sources", {}).items():
        add(ROOT / relative, expected)
    historical = json.loads(checked(BASE_OUT / "HISTORICAL_REFIT_RECEIPT.json").read_text(encoding="utf-8"))
    for row in historical.get("folds", []):
        fold = int(row["fold"])
        add(BASE_OUT / f"F1_STYLE6_{fold}/top3.txt", row["model_sha256"])
    fit = json.loads(checked(FIT).read_text(encoding="utf-8"))
    for row in fit["score_sources_by_race_year"].values():
        add(ROOT / row["source_path"], row["source_sha256"])
        add(ROOT / row["meta_path"], row["meta_sha256"])
    for row in prediction["evaluation_score_sources"].values():
        add(ROOT / row["score_path"], row["score_sha256"])
        add(ROOT / row["meta_path"], row["meta_sha256"])
    add(DIRECT_SCHEDULE, EXPECTED_SCHEDULE)
    return dict(sorted(hashes.items()))


def _selection_changes(candidate: pd.DataFrame, comparator: pd.DataFrame, race_hits: pd.DataFrame) -> dict[str, int]:
    right = comparator.set_index("race_id").reindex(candidate["race_id"])
    changed = candidate["race_id"].to_numpy()[(candidate["horse_i"].to_numpy() != right["horse_i"].to_numpy())
                                               | (candidate["horse_j"].to_numpy() != right["horse_j"].to_numpy())]
    diff = race_hits.set_index("race_id")["candidate"].astype(int) - race_hits.set_index("race_id")["comparator"].astype(int)
    is_changed = diff.index.isin(changed)
    return {
        "races_with_pair_changed": int(len(changed)),
        "gains_on_changed_races": int(((diff == 1) & is_changed).sum()),
        "losses_on_changed_races": int(((diff == -1) & is_changed).sum()),
        "ties_on_changed_races": int(((diff == 0) & is_changed).sum()),
    }


def run_report() -> None:
    global _REPORT
    prediction, source_preflight = validate_prediction_sources()
    require(sha256(DIRECT_REPORT) == EXPECTED_REPORT_HELPER, "frozen report helper changed")
    require(sha256(DIRECT_SCHEDULE) == EXPECTED_SCHEDULE, "frozen bootstrap schedule changed")
    require(not REPORT.exists() and not REPORT_RECEIPT.exists() and not README.exists() and not MANIFEST.exists(),
            "report artifact already exists")
    _REPORT = import_module("frozen_direct_pair_report_jockey_basic", DIRECT_REPORT)
    dates, schedule, schedule_receipt = _REPORT.load_bootstrap()
    pairs = pd.read_parquet(checked(PREDICTIONS))
    require(len(pairs) == 76848 and pairs["race_id"].nunique() == 1779 and pairs["race_date"].nunique() == 269,
            "fixed evaluation pair/date cohort changed")
    require((pairs.groupby("race_id")["y_pair"].sum() == 3).all(), "evaluation label arithmetic changed")
    pairs = _REPORT.add_date_index(pairs, dates)
    races = pairs[["race_id", "race_date", "evaluation_year", "distance_m"]].drop_duplicates().copy()
    require(len(races) == 1779 and races["race_id"].is_unique, "race-level key changed")
    for policy, selector in POLICIES.items():
        selected = _REPORT.one_selected_per_race(pairs, selector)
        hit = selected[["race_id", "y_pair"]].rename(columns={"y_pair": policy})
        races = races.merge(hit, on="race_id", how="inner", validate="one_to_one")
    races = _REPORT.add_date_index(races, dates)
    rates = {name: {"hits": int(races[name].sum()), "races": len(races), "hit_rate": float(races[name].mean())}
             for name in POLICIES}
    races["candidate"] = races["jockey_basic_candidate"].astype(float)
    comparisons = {}
    for policy in POLICIES:
        if policy == "jockey_basic_candidate":
            continue
        races["difference"] = races["candidate"] - races[policy].astype(float)
        comparisons[policy] = {
            "point_difference": float(races["difference"].mean()),
            "paired_date_bootstrap_95pct_ci": _REPORT.date_ci(races, "difference", dates, schedule),
        }
    primary = comparisons["latest_expanded_direct_pair_427"]
    raw = comparisons["raw_F1_STYLE6_score_Top2_429"]
    primary_ci = primary["paired_date_bootstrap_95pct_ci"]
    raw_ci = raw["paired_date_bootstrap_95pct_ci"]
    primary_pass = bool(primary["point_difference"] > 0 and primary_ci["ci_low"] is not None and primary_ci["ci_low"] > 0)
    raw_pass = bool(raw["point_difference"] > 0 and raw_ci["ci_low"] is not None and raw_ci["ci_low"] > 0)

    selected_candidate = _REPORT.one_selected_per_race(pairs, "selected_jockey_basic_candidate")
    changes = {}
    for name, selector in (("latest_pair_427", "selected_latest_pair"), ("raw_score_top2_429", "selected_raw_top2")):
        comparator = _REPORT.one_selected_per_race(pairs, selector)
        hit_frame = selected_candidate[["race_id", "y_pair"]].rename(columns={"y_pair": "candidate"}).merge(
            comparator[["race_id", "y_pair"]].rename(columns={"y_pair": "comparator"}),
            on="race_id", validate="one_to_one"
        )
        changes[name] = _selection_changes(selected_candidate, comparator, hit_frame)

    probability_models = {
        "jockey_basic_candidate": ("candidate_calibrated_probability", "selected_candidate"),
        "latest_expanded_direct_pair": ("latest_pair_calibrated_probability", "selected_latest_pair"),
        "old_direct_pair": ("old_direct_calibrated_probability", "selected_old_direct"),
        "H2_calibrated_p0_baseline": ("baseline_calibrated_probability", "selected_baseline"),
    }
    quality, confidence = {}, {}
    for model, (column, selector) in probability_models.items():
        selected = _REPORT.one_selected_per_race(pairs, selector)
        quality[model] = {
            "all_pair": _REPORT.race_equal_scores(pairs, column),
            "selected_pair": _REPORT.race_equal_scores(selected, column),
            "all_pair_reliability": _REPORT.reliability(pairs, column, True),
            "selected_pair_reliability": _REPORT.reliability(selected, column, False),
        }
        confident = selected.loc[selected[column].ge(0.20)].copy()
        confidence[model] = {
            "threshold": 0.20, "selected_races": int(len(selected)),
            "coverage_count": int(len(confident)), "coverage": float(len(confident) / len(selected)),
            "hit_rate": float(confident["y_pair"].mean()) if len(confident) else None,
            "date_cluster_ci": _REPORT.date_ci(confident, "y_pair", dates, schedule),
        }

    diagnostics = pd.read_parquet(checked(DIAGNOSTICS))
    sum_columns = {
        "jockey_basic_candidate": "jockey_basic_candidate_sum_probability_minus_3",
        "latest_expanded_direct_pair": "latest_pair_sum_probability_minus_3",
        "old_direct_pair": "old_direct_candidate_sum_calibrated_pair_probability_minus_3",
        "H2_calibrated_p0_baseline": "baseline_sum_calibrated_pair_probability_minus_3",
    }
    sums = {}
    for model, column in sum_columns.items():
        values = diagnostics[column].to_numpy(dtype=float)
        absolute = np.abs(values)
        sums[model] = {
            "races": len(values), "signed_mean": float(np.mean(values)),
            "absolute_mean": float(np.mean(absolute)), "absolute_median": float(np.median(absolute)),
            "absolute_p95": float(np.quantile(absolute, 0.95)), "absolute_max": float(np.max(absolute)),
        }

    years = {}
    for year in (2024, 2025, 2026):
        subset = races.loc[races["evaluation_year"].eq(year)].copy()
        entry = {name: {"hits": int(subset[name].sum()), "races": len(subset), "hit_rate": float(subset[name].mean())}
                 for name in POLICIES}
        frame = subset.assign(difference=subset["candidate"] - subset["latest_expanded_direct_pair_427"])
        entry["candidate_minus_latest_pair"] = {
            "point_difference": float(frame["difference"].mean()),
            "paired_date_bootstrap_95pct_ci": _REPORT.date_ci(frame, "difference", dates, schedule),
        }
        years[str(year)] = entry

    distances = {}
    for distance in sorted(races["distance_m"].unique().tolist()):
        subset = races.loc[races["distance_m"].eq(distance)].copy()
        frame = subset.assign(difference=subset["candidate"] - subset["latest_expanded_direct_pair_427"])
        distances[str(int(distance))] = {
            "races": len(subset), "dates": int(subset["race_date"].nunique()),
            "candidate_hits": int(subset["jockey_basic_candidate"].sum()),
            "latest_pair_hits": int(subset["latest_expanded_direct_pair_427"].sum()),
            "candidate_hit_rate": float(subset["jockey_basic_candidate"].mean()),
            "latest_pair_hit_rate": float(subset["latest_expanded_direct_pair_427"].mean()),
            "paired_date_bootstrap_95pct_ci": _REPORT.date_ci(frame, "difference", dates, schedule),
            "sparse_subgroup": bool(len(subset) < 100 or subset["race_date"].nunique() < 20),
        }

    source_hashes = external_source_hashes(prediction, source_preflight)
    report = {
        "study": STUDY.name,
        "study_description": "F1_STYLE6 말 평가를 고정하고 T−2 최근 365일 기수의 관측 편성 대비 Top3 빈도 scalar 합 한 열을 pair 선택에 더한 단일 비교",
        "evaluation_scope": "반복 개발 평가자료 2024-01-05~2026-09-19; independent future holdout 아님",
        "candidate_input": {
            "formula": "d=(S−Σ(3/field_n))/(n+20), n=0→0; pair=d_i+d_j",
            "window": "C=T−2 calendar days; C−365d < past race_date <= C",
            "added_pair_columns": ["jockey365_past_field_relative_top3_sum"],
            "interpretation": "과거 관측 편성 대비 Top3 빈도 지표, 기수 능력·인과효과가 아님",
            "rider_id_role": "공식 event ID는 과거 출전 집계 key 전용; category coefficient 없음",
        },
        "races": len(races), "race_dates": int(races["race_date"].nunique()),
        "pair_rows": len(pairs), "positive_pair_labels": int(pairs["y_pair"].sum()),
        "pair_hit_rate_by_policy": rates,
        "candidate_minus_fixed_comparator_date_bootstrap": comparisons,
        "primary_feature_effect_gate_vs_latest_pair_427": {
            **primary, "point_estimate_above_zero": primary["point_difference"] > 0,
            "ci_lower_above_zero": primary_ci["ci_low"] is not None and primary_ci["ci_low"] > 0,
            "passed": primary_pass,
        },
        "secondary_raw429_gate": {
            **raw, "point_estimate_above_zero": raw["point_difference"] > 0,
            "ci_lower_above_zero": raw_ci["ci_low"] is not None and raw_ci["ci_low"] > 0,
            "passed": raw_pass,
        },
        "combined_pair_improvement_gate_passed": bool(primary_pass and raw_pass),
        "selection_change_diagnostics": changes,
        "probability_quality_separate_diagnostics": quality,
        "selected_probability_at_least_0_20": confidence,
        "sum_pair_probability_minus_three_diagnostics": sums,
        "hit_rate_by_year": years, "hit_rate_by_distance_m": distances,
        "bootstrap": {
            "schedule_sha256": sha256(DIRECT_SCHEDULE), "draws": int(schedule.shape[0]),
            "dates": int(schedule.shape[1]), "seed": int(schedule_receipt["seed"]),
            "numpy_version": str(schedule_receipt["numpy_version"]),
            "date_min": dates[0], "date_max": dates[-1],
        },
        "source_inputs_sha256": source_hashes,
        "fit_receipt_sha256": sha256(FIT_RECEIPT),
        "prediction_receipt_sha256": sha256(PREDICTION_RECEIPT),
        "pair_predictions_sha256": sha256(PREDICTIONS),
        "race_diagnostics_sha256": sha256(DIAGNOSTICS),
        "interpretation_limits": [
            "평가기간은 반복 개발 라벨을 재사용하며 독립 미래 holdout이 아니다.",
            "기수 분모 n은 저장된 정상완주 완전 편성 cohort 안 eligible starts만 뜻한다.",
            "과거 결과 게시 timestamp는 없고 현재 event 기수는 후향 snapshot으로 연결했다.",
            "고정 날짜 bootstrap은 적합된 모델을 조건으로 하며 H1 재표집·재학습을 하지 않는다.",
            "기존 source 제외 말 3005648 및 400m 제외를 유지했다.",
        ],
    }
    write_json_once(REPORT, report)
    readme_lines = [
        "# 제주 F1_STYLE6 두 말 동시 Top3 pair 기수 기본정보 비교", "",
        "저장 F1_STYLE6 말 점수·평가 roster·latest expanded pair를 고정하고, pair 선택에 최근 365일 기수 기록 한 열을 더했다. 공식 event jockey ID는 과거 출전을 묶는 데만 썼다. `C=T−2일` 기준 `(C−365일,C]` 구간에서 `d=(Top3 횟수−Σ(3/편성수))/(관측 출전수+20)`를 계산하고 unordered pair 입력은 두 말 값의 합으로 정의했다. 20 pseudo-start는 사전 고정이며 조정하지 않았다. 지표는 과거 관측 편성 대비 Top3 빈도이지 기수 능력 추정치가 아니다.", "",
        f"평가는 {len(races):,}경주·{races['race_date'].nunique():,}경주일·{len(pairs):,} pair다. 2026년은 9월까지의 부분연도이며 이 기간은 반복 개발 자료다.", "",
        "## 사전 지정 비교", "",
        f"Primary feature-effect: candidate {rates['jockey_basic_candidate']['hits']}/{len(races)} − latest pair 427/1,779 = {100*primary['point_difference']:+.3f}%p (date-bootstrap 95% CI {100*primary_ci['ci_low']:+.3f}~{100*primary_ci['ci_high']:+.3f}%p); {'통과' if primary_pass else '미통과'}.",
        f"Raw 429 gate: candidate {rates['jockey_basic_candidate']['hits']}/{len(races)} − raw Top2 429/1,779 = {100*raw['point_difference']:+.3f}%p (95% CI {100*raw_ci['ci_low']:+.3f}~{100*raw_ci['ci_high']:+.3f}%p); {'통과' if raw_pass else '미통과'}.",
        f"두 gate 모두 통과: {'예' if primary_pass and raw_pass else '아니오'}. Latest pair 대비 선택이 다른 경주는 {changes['latest_pair_427']['races_with_pair_changed']}개로, 변경 경주에서 +{changes['latest_pair_427']['gains_on_changed_races']}승/−{changes['latest_pair_427']['losses_on_changed_races']}패/{changes['latest_pair_427']['ties_on_changed_races']}동률이었다.", "",
        "| 비교 방식 | 적중 | 경주 | 적중률 |", "|---|---:|---:|---:|",
    ]
    for name, result in rates.items():
        readme_lines.append(f"| {name} | {result['hits']:,} | {result['races']:,} | {100*result['hit_rate']:.2f}% |")
    readme_lines += [
        "", "## 확률·하위집단 진단", "",
        "All-pair/selected-pair Brier와 log loss, reliability, 선택확률 0.20 이상 coverage·적중률, 연도·거리별 paired 결과 및 확률합 진단은 `outputs/REPORT.json`에 기록했다. 기존 2,000 draw·269-date bootstrap schedule을 그대로 사용했다.", "",
        "## 제한", "",
        "원천은 정상 완주 완전 편성 cohort라 `n`은 전체 현실 기승수가 아니다. 결과 게시시각은 없고 현재 기수 배정도 후향 event snapshot을 가정한다. 반복 개발 기간 결과이므로 새 미래 holdout 전 운영 적용 근거가 되지 않는다. 이번 비교는 rolling-365 scalar 하나만 확인했으며 기수 범주형 효과, 마방, 교체, 전문성은 포함하지 않았다.", "",
    ]
    require(not README.is_symlink(), "README output symlink not allowed")
    with README.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(readme_lines))
    report_receipt = {
        "status": "PASS", "study": STUDY.name, "performance_metrics_computed": True,
        "report_sha256": sha256(REPORT), "readme_sha256": sha256(README),
        "report_runner_sha256": sha256(Path(__file__).resolve()),
        "pair_predictions_sha256": sha256(PREDICTIONS),
        "bootstrap_schedule_sha256": sha256(DIRECT_SCHEDULE),
        "primary_feature_effect_gate_passed": primary_pass, "raw429_gate_passed": raw_pass,
    }
    write_json_once(REPORT_RECEIPT, report_receipt)
    write_manifest(source_hashes)


def write_manifest(source_hashes: dict[str, str]) -> None:
    local_files = [
        STUDY / "PLAN.md", STUDY / "SOURCE_AUDIT.md", STUDY / "jockey_input.py",
        STUDY / "pair_jockey_fit.py", STUDY / "pair_jockey_predict.py", STUDY / "pair_jockey_report.py",
        README, OUT / "SOURCE_PREFLIGHT.json", OUT / "APPROVAL.json", FIT, FIT_RECEIPT,
        PREDICTIONS, DIAGNOSTICS, PREDICTION_RECEIPT, REPORT, REPORT_RECEIPT,
    ]
    local = []
    for path in local_files:
        resolved = checked(path)
        require(resolved.is_relative_to(STUDY), f"manifest file escaped study: {path}")
        local.append({"path": str(resolved.relative_to(STUDY)), "sha256": sha256(resolved), "bytes": resolved.stat().st_size})
    write_json_once(MANIFEST, {
        "status": "PASS", "study": STUDY.name, "generated_at": "2026-10-12",
        "local_artifacts": local, "source_inputs_sha256": source_hashes,
        "manifest_self_hash_excluded": True,
    })


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] != "report":
        raise SystemExit("usage: pair_jockey_report.py report")
    run_report()


if __name__ == "__main__":
    main()

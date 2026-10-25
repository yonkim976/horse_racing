"""Run the frozen direct-pair report on expanded predictions and old schedule."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pandas as pd

sys.dont_write_bytecode = True

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
OUT = STUDY / "outputs"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
OLD_REPORT = DIRECT / "report.py"
OLD_SCHEDULE = DIRECT / "outputs/date_bootstrap_schedule.npy"
OLD_SCHEDULE_RECEIPT = DIRECT / "outputs/date_bootstrap_schedule.json"
PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
PREDICTION_RECEIPT = OUT / "prediction_receipt.json"
REPORT_COMPAT_PREDICTION_RECEIPT = OUT / "REPORT_INPUT_PREDICTION_RECEIPT.json"
FIT_RECEIPT = OUT / "PAIR_FIT_RECEIPT.json"
H1_FIT = OUT / "expanded_h1_fit.json"
REPORT_PATH = OUT / "REPORT.json"
REPORT_RECEIPT_PATH = OUT / "REPORT_RECEIPT.json"
README_PATH = STUDY / "README.md"
EXPECTED_SCHEDULE_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def atomic_replace_text(path: Path, content: str) -> None:
    require(not path.is_symlink() and path.resolve().is_relative_to(STUDY), f"metadata repair escaped study: {path}")
    temporary = path.with_name(path.name + ".metadata-repair.tmp")
    require(not temporary.exists(), f"metadata repair temporary exists: {temporary}")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def metric_fingerprint(report: dict) -> str:
    allowed_metadata = {"study", "study_description", "evaluation_scope", "interpretation_limits"}
    numeric_content = {key: value for key, value in report.items() if key not in allowed_metadata}
    serialized = json.dumps(numeric_content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def repair_metadata_only() -> None:
    require(REPORT_PATH.is_file() and REPORT_RECEIPT_PATH.is_file() and README_PATH.is_file(),
            "completed report artifacts are required for metadata repair")
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    receipt = json.loads(REPORT_RECEIPT_PATH.read_text(encoding="utf-8"))
    readme = README_PATH.read_text(encoding="utf-8")
    require(sha256(REPORT_PATH) == receipt.get("report_sha256"), "report changed before metadata-only repair")
    require(sha256(README_PATH) == receipt.get("readme_sha256"), "README changed before metadata-only repair")
    require(receipt.get("report_runner_sha256") == "c50cecc19625e87b1ae7c97c3a46f21dffa529806a0f8d6e580216c46ae5623b",
            "unexpected report runner before metadata-only repair")
    before = metric_fingerprint(report)

    report["study"] = STUDY.name
    report["study_description"] = "F1_STYLE6 평가를 고정하고 recipe-valid 과거 OOS 원시 점수를 추가해 direct pair 모형 H1만 확장한 후속 비교"
    report["evaluation_scope"] = "확장 H1을 적용한 반복 개발 평가 코호트이며 새로운 holdout이 아님"
    report["interpretation_limits"] = [
        "H1 확장은 경주 수와 함께 과거 달력 구간 및 점수 모델 vintage도 바꾸므로 학습량만의 인과효과로 해석할 수 없다.",
        "2024~2026 평가 코호트는 반복 개발 라벨을 재사용하며 독립 holdout이 아니다.",
        "고정 날짜 bootstrap은 이미 적합된 rolling model을 조건으로 하며 H1 학습 라벨을 재표집하거나 재학습하지 않는다.",
    ]
    require(metric_fingerprint(report) == before, "numeric/model/report content changed during metadata repair")

    title = "# 제주 Top3 pair H1 확장 모델 평가"
    readme = readme.replace("# 제주 Top3 pair 직접모형 평가", title, 1)
    readme = readme.replace(
        "저장된 F1_STYLE6 점수와 여섯 style 입력으로 학습한 대칭 pair 전용모형을 동일한 역사 평가 경주에서 비교했다.",
        "F1_STYLE6 평가와 30개 말 입력은 고정하고, recipe-valid 과거 OOS 원시 점수를 H1에 추가해 direct pair 모형을 다시 비교했다. 기존 direct 모형과 원시 점수 Top2를 포함한 모든 비교는 같은 2024~2026 평가 경주에서 수행했다.",
        1,
    )
    old_limits = (
        "The H1 expansion changes historical calendar regime mix and score-model vintage along with race count; the contrast is not a causal effect of sample size alone. "
        "The 2024-2026 evaluation cohort reuses historical development labels; it is not an independent holdout. "
        "The unchanged date bootstrap conditions on fitted rolling models and does not resample or refit H1 training labels."
    )
    korean_limits = "H1 확장은 경주 수와 함께 과거 달력 구간 및 점수 모델 vintage도 바꾸므로 학습량만의 인과효과로 해석할 수 없다. 2024~2026 평가 코호트는 반복 개발 라벨을 재사용하며 독립 holdout이 아니다. 고정 날짜 bootstrap은 적합된 rolling model을 조건으로 하며 H1 학습 라벨을 재표집하거나 재학습하지 않는다."
    require(old_limits in readme, "expected English limitation paragraph not found")
    readme = readme.replace(old_limits, korean_limits, 1)
    readme = readme.replace(
        "확장 direct와 기존 direct의 차이는 +0.06%p이며, 동일한 날짜 bootstrap 95% CI는 -0.28%p ~ +0.39%p다. 이 비교는 학습창 효과의 별도 사전 지정 대비이며 primary 성공 gate를 대체하지 않는다.",
        "확장 direct는 427/1,779(24.00%), 기존 direct는 426/1,779(23.95%)였다. 변경 pair 24경주 중 +5승, -4패, 15동률이며, 차이는 +0.0562%p, 동일 날짜 bootstrap 95% CI는 -0.2804%p ~ +0.3909%p다. 이 비교는 학습창 확대와 역사 구간 구성이 함께 바뀌는 별도 사전 지정 대비이며 primary 성공 gate를 대체하지 않는다.",
        1,
    )
    readme = readme.replace(
        "2024: 312 → 2147 경주 / 2025: 326 → 2818 경주 / 2026: 329 → 3458 경주. H2와 평가 코호트는 그대로 유지했다.",
        "H1은 2024년 312→2,147경주, 2025년 326→2,818경주, 2026년 329→3,458경주로 늘었다. 연도별 확장 direct 적중은 153/150/124, 기존 direct는 154/148/124였다. H2와 평가 코호트는 그대로 유지했다. Primary gate는 raw Top2 대비 427/1,779 대 429/1,779, 차이 -0.1124%p와 95% CI -0.3407%p~+0.0569%p로 미통과다.",
        1,
    )
    readme += "\n다음 비교에서는 표본 부족을 단정하지 않고 구조 효과와 학습 제약을 분리해 검토한다. 학습량 비교와 동시에 λ 또는 loss를 튜닝하지 않는다.\n"

    receipt["study"] = STUDY.name
    # Keep the report serializer's exact on-disk newline representation for its receipt hash.
    report_text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    receipt["report_sha256"] = hashlib.sha256(report_text.encode("utf-8")).hexdigest()
    receipt["readme_sha256"] = hashlib.sha256(readme.encode("utf-8")).hexdigest()
    receipt["report_runner_sha256"] = sha256(Path(__file__).resolve())
    receipt["metadata_only_repair"] = True
    receipt["metric_fingerprint_sha256"] = before
    receipt["performance_metrics_computed"] = True
    receipt_text = json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    atomic_replace_text(REPORT_PATH, report_text)
    atomic_replace_text(README_PATH, readme)
    atomic_replace_text(REPORT_RECEIPT_PATH, receipt_text)
    print(json.dumps({
        "status": "PASS", "repair_scope": "study metadata and Korean explanatory prose only",
        "metric_content_preserved": metric_fingerprint(json.loads(REPORT_PATH.read_text(encoding="utf-8"))) == before,
        "report_sha256": sha256(REPORT_PATH), "readme_sha256": sha256(README_PATH),
        "report_receipt_sha256": sha256(REPORT_RECEIPT_PATH), "runner_sha256": sha256(Path(__file__).resolve()),
    }, ensure_ascii=False, indent=2))


def write_report_input_receipt() -> None:
    source = json.loads(PREDICTION_RECEIPT.read_text(encoding="utf-8"))
    source["evaluation_pair_predictions_sha256"] = source["pair_prediction_sha256"]
    source["race_probability_diagnostics_sha256"] = source["race_diagnostics_sha256"]
    require(not REPORT_COMPAT_PREDICTION_RECEIPT.exists(), "refusing to overwrite report input receipt")
    with REPORT_COMPAT_PREDICTION_RECEIPT.open("x", encoding="utf-8") as stream:
        json.dump(source, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def load_report_module():
    require(sha256(OLD_SCHEDULE) == EXPECTED_SCHEDULE_SHA256, "frozen original bootstrap schedule changed")
    spec = importlib.util.spec_from_file_location("frozen_direct_pair_report", OLD_REPORT)
    require(spec is not None and spec.loader is not None, "cannot load frozen direct report functions")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.__file__ = str(Path(__file__).resolve())
    module.STUDY = STUDY
    module.OUT = OUT
    module.PREDICTION_PATH = PREDICTIONS
    module.RACE_DIAGNOSTICS_PATH = OUT / "evaluation_race_probabilities.parquet"
    module.PREDICTION_RECEIPT_PATH = PREDICTION_RECEIPT
    module.FIT_RECEIPT_PATH = FIT_RECEIPT
    # Read the exact previous schedule and receipt; never generate a replacement.
    module.SCHEDULE_PATH = OLD_SCHEDULE
    module.SCHEDULE_RECEIPT_PATH = OLD_SCHEDULE_RECEIPT
    module.REPORT_PATH = REPORT_PATH
    module.REPORT_RECEIPT_PATH = REPORT_RECEIPT_PATH
    module.README_PATH = README_PATH
    module.POLICIES = {
        "direct_pair_model": "selected_candidate",
        "old_direct_pair_model": "selected_old_direct",
        "H2_calibrated_p0_baseline": "selected_baseline",
        "raw_F1_STYLE6_score_Top2": "selected_raw_top2",
        "saved_F1_STYLE6_PTop3_Top2": "selected_saved_f1_top2",
        "existing_candidate_joint_marginal_Top2": "selected_candidate_joint_marginal_top2",
        "existing_candidate_maximum_joint_pair": "selected_candidate_joint_maxpair",
        "existing_matched_maximum_joint_pair": "selected_matched_joint_maxpair",
    }

    base_write = module.write_json_once

    def write_json_once(path, value):
        if Path(path) == REPORT_PATH:
            fit = json.loads(FIT_RECEIPT.read_text(encoding="utf-8"))
            h1 = json.loads(H1_FIT.read_text(encoding="utf-8"))
            pairs = pd.read_parquet(PREDICTIONS)
            old_selected = module.one_selected_per_race(pairs, "selected_old_direct")
            value["probability_quality_separate_diagnostics"]["old_direct"] = {
                "all_pair": module.race_equal_scores(pairs, "old_direct_candidate_calibrated_probability"),
                "selected_pair": module.race_equal_scores(old_selected, "old_direct_candidate_calibrated_probability"),
                "all_pair_reliability": module.reliability(pairs, "old_direct_candidate_calibrated_probability", True),
                "selected_pair_reliability": module.reliability(old_selected, "old_direct_candidate_calibrated_probability", False),
            }
            fit_folds = {str(row["evaluation_year"]): row for row in h1["folds"]}
            value["training_window"] = {
                "old_h1_races": {"2024": 312, "2025": 326, "2026": 329},
                "expanded_h1_races": {year: fit_folds[str(year)]["h1_races"] for year in (2024, 2025, 2026)},
                "expanded_h1_dates": {year: fit_folds[str(year)]["h1_dates"] for year in (2024, 2025, 2026)},
                "historical_score_years": "2019 through evaluation_year-2, plus unchanged Jan-Jun of evaluation_year-1",
                "h2_races_unchanged": {"2024": 336, "2025": 311, "2026": 325},
                "evaluation_cohort_unchanged": True,
            }
            old_ci = value["paired_date_cluster_differences_direct_minus_comparator"]["old_direct_pair_model"]
            value["training_window_contrast"] = {
                "contrast": "expanded direct pair minus prior direct pair (426/1,779)",
                "point_difference": (
                    value["pair_hit_rate_by_policy"]["direct_pair_model"]["hit_rate"]
                    - value["pair_hit_rate_by_policy"]["old_direct_pair_model"]["hit_rate"]
                ),
                "paired_date_bootstrap_95pct_ci": old_ci,
                "primary_gate_unchanged": "expanded direct pair minus raw F1_STYLE6 score Top2",
                "bootstrap_schedule_reused_sha256": EXPECTED_SCHEDULE_SHA256,
            }
            value["interpretation_limits"] = [
                "The H1 expansion changes historical calendar regime mix and score-model vintage along with race count; the contrast is not a causal effect of sample size alone.",
                "The 2024-2026 evaluation cohort reuses historical development labels; it is not an independent holdout.",
                "The unchanged date bootstrap conditions on fitted rolling models and does not resample or refit H1 training labels.",
            ]
            value["fit_receipt_sha256"] = sha256(FIT_RECEIPT)
            value["prediction_receipt_sha256"] = sha256(PREDICTION_RECEIPT)
        return base_write(path, value)

    module.write_json_once = write_json_once
    base_readme = module.render_readme

    def render_readme(report):
        body = base_readme(report)
        contrast = report["training_window_contrast"]
        ci = contrast["paired_date_bootstrap_95pct_ci"]
        fmt_pp = module.fmt_pp
        comparison = (
            f"확장 direct와 기존 direct의 차이는 {100*contrast['point_difference']:+.2f}%p이며, "
            f"동일한 날짜 bootstrap 95% CI는 {fmt_pp(ci['ci_low'])} ~ {fmt_pp(ci['ci_high'])}다. "
            "이 비교는 학습창 효과의 별도 사전 지정 대비이며 primary 성공 gate를 대체하지 않는다."
        )
        counts = report["training_window"]
        volume = " / ".join(
            f"{year}: {counts['old_h1_races'][str(year)]} → {counts['expanded_h1_races'][year]} 경주"
            for year in (2024, 2025, 2026)
        )
        limits = " ".join(report["interpretation_limits"])
        return body + "\n## H1 학습창 확장 대비\n\n" + comparison + "\n\n" + volume + ". H2와 평가 코호트는 그대로 유지했다. " + limits + "\n"

    module.render_readme = render_readme
    return module


def main() -> None:
    if sys.argv[1:] == ["repair-metadata-only"]:
        repair_metadata_only()
        return
    require(not REPORT_PATH.exists() and not REPORT_RECEIPT_PATH.exists() and not README_PATH.exists(),
            "refusing to overwrite existing expanded report")
    pred_receipt = json.loads(PREDICTION_RECEIPT.read_text(encoding="utf-8"))
    fit_receipt = json.loads(FIT_RECEIPT.read_text(encoding="utf-8"))
    require(pred_receipt.get("status") == "PASS" and pred_receipt.get("performance_metrics_computed") is False,
            "prediction artifact is not a no-metric PASS")
    require(fit_receipt.get("status") == "PASS", "pair fit receipt missing/not PASS")
    write_report_input_receipt()
    module = load_report_module()
    module.PREDICTION_RECEIPT_PATH = REPORT_COMPAT_PREDICTION_RECEIPT
    module.run_report()


if __name__ == "__main__":
    main()

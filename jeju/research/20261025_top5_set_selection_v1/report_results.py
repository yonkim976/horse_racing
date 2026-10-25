"""Report the frozen Top5 comparison after explicit root code approval.

Selection and its receipt are verified before this stage opens the outcome-label
column. All outputs are created exclusively under this study's outputs folder.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import select_sets


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
SELECTION_PATH = OUT / "selections.jsonl"
SELECTION_RECEIPT_PATH = OUT / "selection_receipt.json"
PRESELECTION_LOCK_PATH = OUT / "PRESELECTION_LOCK.json"
BOOTSTRAP_RECEIPT_REL = Path(
    "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
)
ROOT_REPORT_REVIEW_REL = Path(
    "jeju/research/20261025_top5_set_rootreview_v1/ROOT_REPORT_CODE_REVIEW_v2.json"
)

EXPECTED_BOOTSTRAP_RECEIPT_SHA256 = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"
EXPECTED_DATE_INVENTORY_SHA256 = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
EXPECTED_DATES = 269
EXPECTED_DRAWS = 2000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def confined_source(relative: Path) -> Path:
    path = (ROOT / relative).resolve(strict=True)
    if not path.is_relative_to(ROOT):
        raise AssertionError(f"source escaped repository root: {relative}")
    return path


def verify_preoutcome_inputs() -> tuple[dict[str, Any], dict[str, Any], np.ndarray, list[str]]:
    """Verify code/source/selection/schedule contracts without reading labels."""
    output_names = (
        "race_results.jsonl",
        "metrics.json",
        "REPORT.md",
        "report_receipt.json",
    )
    if any((OUT / name).exists() for name in output_names):
        raise FileExistsError("report outputs already exist; refusing to overwrite")

    preselection_lock = json.loads(PRESELECTION_LOCK_PATH.read_text(encoding="utf-8"))
    if preselection_lock.get("status") != "APPROVED_FOR_SELECTION_ONLY":
        raise AssertionError("selection-only approval lock is not passing")
    if preselection_lock.get("outcome_report_approved") is not False:
        raise AssertionError("preselection lock must not claim outcome-report approval")

    selection_receipt = json.loads(SELECTION_RECEIPT_PATH.read_text(encoding="utf-8"))
    if selection_receipt.get("status") != "PASS_LABEL_FREE_SELECTION":
        raise AssertionError("selection receipt is not a passing label-free receipt")
    if selection_receipt.get("selection_stage_reads_outcome_labels") is not False:
        raise AssertionError("selection receipt does not certify a label-free selector")
    if selection_receipt.get("selector_code_sha256") != sha256_file(HERE / "select_sets.py"):
        raise AssertionError("selector code changed after selection")

    selection_record = selection_receipt.get("selection_artifact", {})
    if selection_record.get("path") != str(SELECTION_PATH.relative_to(ROOT)):
        raise AssertionError("selection receipt points at an unexpected artifact")
    selection_sha = sha256_file(SELECTION_PATH)
    if selection_record.get("sha256") != selection_sha:
        raise AssertionError("selection artifact hash does not match its receipt")
    if selection_record.get("bytes") != SELECTION_PATH.stat().st_size:
        raise AssertionError("selection artifact size does not match its receipt")
    if selection_record.get("races") != select_sets.EXPECTED_RACES:
        raise AssertionError("selection artifact has an unexpected race count")
    if selection_record.get("primary_distance_races") != 1503:
        raise AssertionError("selection artifact has an unexpected primary count")
    if preselection_lock.get("approval_evidence", {}).get("approved_selector_sha256") != selection_receipt.get("selector_code_sha256"):
        raise AssertionError("selection code differs from the preselection approval lock")
    if preselection_lock.get("executed_plan_sha256") != sha256_file(HERE / "PLAN.md"):
        raise AssertionError("plan changed after the selection-only approval lock")

    # Check immutable model inputs, including root's independent Q receipt, before labels.
    sources = select_sets.verify_fixed_sources()

    bootstrap_receipt_path = confined_source(BOOTSTRAP_RECEIPT_REL)
    if sha256_file(bootstrap_receipt_path) != EXPECTED_BOOTSTRAP_RECEIPT_SHA256:
        raise AssertionError("frozen bootstrap receipt hash changed")
    bootstrap_receipt = json.loads(bootstrap_receipt_path.read_text(encoding="utf-8"))
    if bootstrap_receipt.get("status") != "FROZEN_BEFORE_EVALUATION_METRICS":
        raise AssertionError("bootstrap schedule was not frozen before outcome metrics")
    if bootstrap_receipt.get("seed") != 20261011:
        raise AssertionError("bootstrap seed changed")
    if bootstrap_receipt.get("draws") != EXPECTED_DRAWS:
        raise AssertionError("bootstrap draw count changed")
    if bootstrap_receipt.get("dates_per_draw") != EXPECTED_DATES:
        raise AssertionError("bootstrap date count changed")
    if bootstrap_receipt.get("date_inventory_sha256") != EXPECTED_DATE_INVENTORY_SHA256:
        raise AssertionError("bootstrap date inventory hash changed")
    if bootstrap_receipt.get("schedule_sha256") != select_sets.EXPECTED_SHA256[str(select_sets.BOOTSTRAP_REL)]:
        raise AssertionError("bootstrap receipt does not match the frozen schedule hash")

    schedule_path = select_sets.confined_source(select_sets.BOOTSTRAP_REL)
    schedule = np.load(schedule_path, allow_pickle=False)
    if schedule.shape != (EXPECTED_DRAWS, EXPECTED_DATES) or schedule.dtype != np.int32:
        raise AssertionError("bootstrap schedule shape or dtype changed")
    if not bool(((schedule >= 0) & (schedule < EXPECTED_DATES)).all()):
        raise AssertionError("bootstrap schedule contains an invalid date index")
    rng = np.random.default_rng(20261011)
    expected_schedule = rng.integers(
        0, EXPECTED_DATES, size=(EXPECTED_DRAWS, EXPECTED_DATES),
        endpoint=False, dtype=np.int32,
    )
    if not np.array_equal(schedule, expected_schedule):
        raise AssertionError("bootstrap schedule differs from its frozen RNG recipe")

    # Root review is a separate immutable approval artifact; it must bind these exact files.
    review_path = confined_source(ROOT_REPORT_REVIEW_REL)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    required_review = {
        "approved": True,
        "approved_by": "root",
        "scope": "outcome_report_code",
        "report_code_sha256": sha256_file(HERE / "report_results.py"),
        "selector_code_sha256": selection_receipt["selector_code_sha256"],
        "selection_receipt_sha256": sha256_file(SELECTION_RECEIPT_PATH),
        "selection_artifact_sha256": selection_sha,
        "plan_sha256": sha256_file(HERE / "PLAN.md"),
        "execution_approved": True,
    }
    for key, expected in required_review.items():
        if review.get(key) != expected:
            raise AssertionError(f"root report review does not bind expected {key}")

    if sources[str(select_sets.BASELINE_REL)]["sha256"] != select_sets.EXPECTED_BASELINE_SHA256:
        raise AssertionError("baseline source hash changed")
    return selection_receipt, {
        "review": review,
        "review_sha256": sha256_file(review_path),
        "selection_sha256": selection_sha,
        "bootstrap_receipt": bootstrap_receipt,
        "bootstrap_receipt_sha256": sha256_file(bootstrap_receipt_path),
        "bootstrap_schedule_sha256": sha256_file(schedule_path),
    }, schedule, list(sources)


def load_selections() -> pd.DataFrame:
    rows = []
    with SELECTION_PATH.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(f"invalid selection JSON on line {line_number}") from exc
            rows.append(row)
    frame = pd.DataFrame(rows)
    if len(frame) != select_sets.EXPECTED_RACES or frame.race_id.astype(str).duplicated().any():
        raise AssertionError("selection ledger has duplicate/missing races")
    for row in frame.itertuples(index=False):
        if len(row.baseline_horse_ids) != 5 or len(set(row.baseline_horse_ids)) != 5:
            raise AssertionError(f"baseline selection is not exactly five in {row.race_id}")
        if len(row.candidate_horse_ids) != 5 or len(set(row.candidate_horse_ids)) != 5:
            raise AssertionError(f"candidate selection is not exactly five in {row.race_id}")
        if len(row.baseline_horse_numbers) != 5 or len(row.candidate_horse_numbers) != 5:
            raise AssertionError(f"selection horse-number count changed in {row.race_id}")
        if row.candidate_q_gap_from_max < 0.0 or row.candidate_q_gap_from_max > select_sets.TOP5_TIE_TOLERANCE:
            raise AssertionError(f"candidate q tie gap changed in {row.race_id}")
        for name in ("candidate_q_on_baseline_top5", "candidate_q_max", "candidate_q_selected"):
            if not math.isfinite(float(getattr(row, name))):
                raise AssertionError(f"non-finite q value in {row.race_id}")
    return frame


def load_outcomes_after_lock(selection_frame: pd.DataFrame) -> pd.DataFrame:
    """This is the first point at which the report opens the y outcome column."""
    baseline_path = select_sets.confined_source(select_sets.BASELINE_REL)
    labels = pd.read_parquet(
        baseline_path,
        columns=["race_id", "race_date", "year", "distance_m", "horse_id", "horse_number", "y"],
    )
    labels["y"] = pd.to_numeric(labels.y, errors="coerce")
    if labels.y.isna().any() or not set(labels.y.unique()).issubset({0, 1}):
        raise AssertionError("outcome y is missing or non-binary")
    if labels[["race_id", "horse_id"]].duplicated().any():
        raise AssertionError("duplicate runner outcome key")

    outcomes: list[dict[str, Any]] = []
    selection_by_race = selection_frame.set_index(selection_frame.race_id.astype(str), drop=False)
    seen: set[str] = set()
    for race_id, group in labels.groupby("race_id", sort=False, observed=True):
        race_id = str(race_id)
        if race_id in seen:
            raise AssertionError(f"duplicate outcome race key: {race_id}")
        seen.add(race_id)
        if race_id not in selection_by_race.index:
            raise AssertionError(f"outcome race missing selection: {race_id}")
        selection = selection_by_race.loc[race_id]
        if isinstance(selection, pd.DataFrame):
            raise AssertionError(f"multiple selection rows for {race_id}")
        ids = group.horse_id.astype(str).tolist()
        if len(ids) != int(selection.field_n) or len(set(ids)) != len(ids):
            raise AssertionError(f"outcome roster mismatch in {race_id}")
        if int(group.y.sum()) != 3:
            raise AssertionError(f"race does not have exactly three y=1 runners: {race_id}")
        for key in ("race_date", "year", "distance_m"):
            raw = group[key].drop_duplicates()
            if len(raw) != 1:
                raise AssertionError(f"inconsistent outcome {key} in {race_id}")
            expected = getattr(selection, key)
            value = raw.iloc[0]
            if key == "race_date":
                value = pd.to_datetime(value).strftime("%Y-%m-%d")
                expected = pd.to_datetime(expected).strftime("%Y-%m-%d")
            elif key == "distance_m":
                value, expected = int(value), int(expected)
            else:
                value, expected = int(value), int(expected)
            if value != expected:
                raise AssertionError(f"outcome {key} mismatch in {race_id}")
        actual_ids = set(group.loc[group.y.astype(int) == 1, "horse_id"].astype(str))
        if not actual_ids.issubset(set(ids)) or len(actual_ids) != 3:
            raise AssertionError(f"invalid actual Top3 IDs in {race_id}")
        baseline_ids = set(selection.baseline_horse_ids)
        candidate_ids = set(selection.candidate_horse_ids)
        if not baseline_ids.issubset(set(ids)) or not candidate_ids.issubset(set(ids)):
            raise AssertionError(f"selected horse ID is outside the outcome roster in {race_id}")
        base_capture = len(actual_ids & baseline_ids)
        candidate_capture = len(actual_ids & candidate_ids)
        overlap = len(baseline_ids & candidate_ids)
        outcomes.append({
            "race_id": race_id,
            "race_date": pd.to_datetime(group.race_date.iloc[0]).strftime("%Y-%m-%d"),
            "year": int(group.year.iloc[0]),
            "distance_m": int(group.distance_m.iloc[0]),
            "field_n": int(selection.field_n),
            "career_stratum": str(selection.career_stratum),
            "primary_distance": bool(selection.primary_distance),
            "baseline_horse_ids": list(selection.baseline_horse_ids),
            "candidate_horse_ids": list(selection.candidate_horse_ids),
            "baseline_captured": base_capture,
            "candidate_captured": candidate_capture,
            "baseline_misses": 3 - base_capture,
            "candidate_misses": 3 - candidate_capture,
            "baseline_all_three_hit": base_capture == 3,
            "candidate_all_three_hit": candidate_capture == 3,
            "selection_overlap": overlap,
            "selection_changed": overlap != 5,
            "candidate_q_on_baseline_top5": float(selection.candidate_q_on_baseline_top5),
            "candidate_q_selected": float(selection.candidate_q_selected),
            "candidate_q_max": float(selection.candidate_q_max),
            "candidate_q_gap_from_max": float(selection.candidate_q_gap_from_max),
        })
    if seen != set(selection_frame.race_id.astype(str)) or len(outcomes) != select_sets.EXPECTED_RACES:
        raise AssertionError("outcome and selection race cohorts differ")
    return pd.DataFrame(outcomes).sort_values("race_id", kind="stable").reset_index(drop=True)


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"races": 0}
    count = int(len(frame))
    base_hits = int(frame.baseline_all_three_hit.sum())
    candidate_hits = int(frame.candidate_all_three_hit.sum())
    base_hit = frame.baseline_all_three_hit.to_numpy(dtype=bool)
    candidate_hit = frame.candidate_all_three_hit.to_numpy(dtype=bool)
    overlap_hist = frame.selection_overlap.value_counts().to_dict()
    return {
        "races": count,
        "baseline_all_three_hits": base_hits,
        "candidate_all_three_hits": candidate_hits,
        "baseline_all_three_hit_rate": base_hits / count,
        "candidate_all_three_hit_rate": candidate_hits / count,
        "candidate_minus_baseline_hit_rate": (candidate_hits - base_hits) / count,
        "baseline_only_hits": int((base_hit & ~candidate_hit).sum()),
        "candidate_only_hits": int((candidate_hit & ~base_hit).sum()),
        "both_hit": int((base_hit & candidate_hit).sum()),
        "both_missed": int((~base_hit & ~candidate_hit).sum()),
        "selection_changed_races": int(frame.selection_changed.sum()),
        "selection_overlap_counts": {str(k): int(overlap_hist.get(k, 0)) for k in range(6)},
        "mean_selection_overlap": float(frame.selection_overlap.mean()),
        "baseline_miss_distribution": {
            str(k): int((frame.baseline_misses == k).sum()) for k in range(4)
        },
        "candidate_miss_distribution": {
            str(k): int((frame.candidate_misses == k).sum()) for k in range(4)
        },
        "baseline_mean_captured": float(frame.baseline_captured.mean()),
        "candidate_mean_captured": float(frame.candidate_captured.mean()),
        "baseline_mean_candidate_q_utility": float(frame.candidate_q_on_baseline_top5.mean()),
        "candidate_mean_candidate_q_utility": float(frame.candidate_q_selected.mean()),
    }


def group_summaries(frame: pd.DataFrame, primary: bool) -> dict[str, Any]:
    subset = frame.loc[frame.primary_distance] if primary else frame
    return {
        "by_year": {
            str(key): summarize(group)
            for key, group in subset.groupby("year", sort=True, observed=True)
        },
        "by_distance_m": {
            str(key): summarize(group)
            for key, group in subset.groupby("distance_m", sort=True, observed=True)
        },
        "by_career_stratum": {
            str(key): summarize(group)
            for key, group in subset.groupby("career_stratum", sort=True, observed=True)
        },
    }


def paired_date_bootstrap(primary: pd.DataFrame, schedule: np.ndarray, dates: list[str]) -> dict[str, Any]:
    by_date = primary.groupby("race_date", sort=True).agg(
        races=("race_id", "size"),
        delta_hits=("candidate_all_three_hit", "sum"),
    )
    if list(by_date.index.astype(str)) != dates:
        raise AssertionError("primary race-date inventory differs from frozen bootstrap dates")
    if (by_date.races <= 0).any():
        raise AssertionError("a bootstrap date has no primary race")
    date_counts = by_date.races.to_numpy(dtype=np.int64)
    date_delta = (
        by_date.delta_hits.to_numpy(dtype=np.int64)
        - primary.groupby("race_date", sort=True).baseline_all_three_hit.sum().to_numpy(dtype=np.int64)
    )
    if len(date_counts) != EXPECTED_DATES or int(date_counts.sum()) != len(primary):
        raise AssertionError("primary date bootstrap roster/count changed")
    # Every draw resamples days as clusters, then gives each race equal weight.
    numerators = date_delta[schedule].sum(axis=1, dtype=np.int64)
    denominators = date_counts[schedule].sum(axis=1, dtype=np.int64)
    if (denominators <= 0).any():
        raise AssertionError("bootstrap replicate has no primary races")
    samples = numerators / denominators
    low, high = np.quantile(samples, [0.025, 0.975], method="linear")
    return {
        "replicates": int(len(samples)),
        "cluster": "race_date",
        "date_count": len(dates),
        "primary_race_count": int(len(primary)),
        "ci_level": 0.95,
        "quantile_method": "numpy.quantile method='linear'",
        "lower": float(low),
        "upper": float(high),
        "replicate_mean": float(samples.mean()),
        "replicate_sd": float(samples.std(ddof=1)),
    }


def write_exclusive(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def markdown_report(metrics: dict[str, Any], receipt_sha: str | None = None) -> str:
    primary = metrics["primary"]
    ci = metrics["primary_date_bootstrap_95ci"]
    gate = metrics["success_gate"]
    return (
        "# 추천 5두 집합 선택: 후향 결과\n\n"
        "상태: **완료된 반복사용 역사자료 비교**. 동결 F1_STYLE6 점수와 기존 pair-interaction joint 분포를 사용했다. "
        "2024–2026 표본은 이미 여러 연구에서 사용되어 독립 미래 홀드아웃으로 해석하지 않는다.\n\n"
        "## Primary: 900/1000/1110/1200m\n\n"
        f"- 경주 수: {primary['races']}\n"
        f"- Score Top5 all-three hit: {primary['baseline_all_three_hits']}/{primary['races']} "
        f"({primary['baseline_all_three_hit_rate']:.6f})\n"
        f"- Joint q-max Top5 all-three hit: {primary['candidate_all_three_hits']}/{primary['races']} "
        f"({primary['candidate_all_three_hit_rate']:.6f})\n"
        f"- Paired rate difference: {primary['candidate_minus_baseline_hit_rate']:.6f}\n"
        f"- Paired date-bootstrap 95% CI: [{ci['lower']:.6f}, {ci['upper']:.6f}] "
        f"(2,000 frozen draws; linear quantile)\n"
        f"- Prespecified success gate: **{'PASS' if gate['passed'] else 'NOT PASSED'}**\n\n"
        "## Full cohort and decision details\n\n"
        f"- Full cohort: {metrics['full_cohort']['races']} races; paired hit-rate difference "
        f"{metrics['full_cohort']['candidate_minus_baseline_hit_rate']:.6f}.\n"
        f"- Changed sets: {primary['selection_changed_races']}/{primary['races']}; "
        f"candidate-only hits {primary['candidate_only_hits']}; baseline-only hits {primary['baseline_only_hits']}.\n"
        f"- Mean captured actual Top3: score Top5 {primary['baseline_mean_captured']:.6f}; "
        f"joint q-max Top5 {primary['candidate_mean_captured']:.6f}.\n"
        f"- Candidate expected coverage utility mean: score Top5 {primary['baseline_mean_candidate_q_utility']:.6f}; "
        f"joint q-max Top5 {primary['candidate_mean_candidate_q_utility']:.6f}.\n\n"
        "Year, distance, career strata, miss-count, overlap, and paired hit breakdowns are in `metrics.json`. "
        "This retrospective result does not promote a model or establish prospective performance.\n"
        + (f"\nReport receipt SHA-256: `{receipt_sha}`\n" if receipt_sha else "")
    )


def main() -> None:
    # This preflight also requires a root review file binding this report's exact code hash.
    selection_receipt, preflight, schedule, sources = verify_preoutcome_inputs()
    selections = load_selections()

    # Outcome labels are first opened here, after the frozen selection hash is verified.
    race_metrics = load_outcomes_after_lock(selections)
    primary = race_metrics.loc[race_metrics.primary_distance].copy()
    full = race_metrics
    if len(primary) != 1503 or len(full) != select_sets.EXPECTED_RACES:
        raise AssertionError("reported cohort size differs from the prespecified counts")
    date_frame = race_metrics.loc[:, ["race_date", "primary_distance"]]
    dates = sorted(date_frame.loc[date_frame.primary_distance, "race_date"].unique().tolist())
    if len(dates) != EXPECTED_DATES:
        raise AssertionError("primary outcome date inventory has changed")
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    if date_hash != EXPECTED_DATE_INVENTORY_SHA256:
        raise AssertionError("primary outcome dates do not match frozen bootstrap inventory")

    primary_summary = summarize(primary)
    ci = paired_date_bootstrap(primary, schedule, dates)
    gate_pass = (
        primary_summary["candidate_minus_baseline_hit_rate"] > 0.0
        and ci["lower"] > 0.0
    )
    metrics = {
        "status": "RETROSPECTIVE_DEVELOPMENT_COMPARISON",
        "study": "20261025_top5_set_selection_v1",
        "target_event": "all three actual Top3 horse IDs are contained in the exactly-five selected horse IDs",
        "candidate": "argmax exact-Top3 joint probability mass over all five-horse subsets",
        "comparison": "frozen F1_STYLE6 raw score descending, horse_number ascending",
        "primary_distances_m": sorted(select_sets.PRIMARY_DISTANCES),
        "primary": primary_summary,
        "full_cohort": summarize(full),
        "subgroups_primary": group_summaries(race_metrics, primary=True),
        "subgroups_full": group_summaries(race_metrics, primary=False),
        "primary_date_bootstrap_95ci": ci,
        "success_gate": {
            "criterion": "primary paired hit-rate delta > 0 and 95% date-bootstrap CI lower bound > 0",
            "passed": bool(gate_pass),
        },
        "disclosures": {
            "historical_development_data_reused": True,
            "independent_future_holdout": False,
            "new_model_fits": 0,
            "selection_stage_outcome_labels_read": False,
            "outcome_report_reads_labels_after_selection_hash_lock": True,
            "reviewer_label_access_disclosure": "Some y/logloss values were exposed during prior schema inspection but were not used for selector or rule decisions.",
        },
    }

    race_content = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        for row in race_metrics.to_dict(orient="records")
    )
    metrics_content = json.dumps(metrics, indent=2, sort_keys=True, allow_nan=False) + "\n"
    # Write the selection/outcome join only after all validations and summaries passed.
    race_path = OUT / "race_results.jsonl"
    metrics_path = OUT / "metrics.json"
    report_path = OUT / "REPORT.md"
    receipt_path = OUT / "report_receipt.json"
    write_exclusive(race_path, race_content)
    write_exclusive(metrics_path, metrics_content)
    write_exclusive(report_path, markdown_report(metrics))
    receipt = {
        "status": "PASS_OUTCOME_REPORT",
        "study": "20261025_top5_set_selection_v1",
        "report_code_sha256": sha256_file(Path(__file__).resolve()),
        "selector_code_sha256": selection_receipt["selector_code_sha256"],
        "selection_receipt_sha256": sha256_file(SELECTION_RECEIPT_PATH),
        "selection_artifact_sha256": preflight["selection_sha256"],
        "root_report_review_sha256": preflight["review_sha256"],
        "bootstrap_schedule_sha256": preflight["bootstrap_schedule_sha256"],
        "baseline_source_sha256": select_sets.EXPECTED_BASELINE_SHA256,
        "race_results": {
            "path": str(race_path.relative_to(ROOT)),
            "sha256": sha256_file(race_path),
            "bytes": race_path.stat().st_size,
            "races": len(race_metrics),
        },
        "metrics": {
            "path": str(metrics_path.relative_to(ROOT)),
            "sha256": sha256_file(metrics_path),
            "bytes": metrics_path.stat().st_size,
        },
        "report": {
            "path": str(report_path.relative_to(ROOT)),
            "sha256": sha256_file(report_path),
            "bytes": report_path.stat().st_size,
        },
        "primary_gate_passed": bool(gate_pass),
        "label_read_started_after_selection_hash_verified": True,
    }
    write_exclusive(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": receipt["status"],
        "primary_races": len(primary),
        "full_races": len(full),
        "primary_delta": primary_summary["candidate_minus_baseline_hit_rate"],
        "primary_ci95": [ci["lower"], ci["upper"]],
        "success_gate_passed": gate_pass,
        "report_receipt_sha256": sha256_file(receipt_path),
        "output_bytes": sum(path.stat().st_size for path in (race_path, metrics_path, report_path, receipt_path)),
    }, sort_keys=True))


if __name__ == "__main__":
    main()

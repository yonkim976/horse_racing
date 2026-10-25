"""Independent post-lock outcome summary and date-cluster bootstrap audit.

This implementation does not import either the selector or report code. The
choice receipt and root's outcome-stage approval are checked before opening y.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = ROOT / "jeju/research/20261025_top5_set_selection_v1"
ROOT_REVIEW = ROOT / "jeju/research/20261025_top5_set_rootreview_v1"
SELECTIONS = STUDY / "outputs/selections.jsonl"
SELECTION_RECEIPT = STUDY / "outputs/selection_receipt.json"
PRESELECTION_LOCK = STUDY / "outputs/PRESELECTION_LOCK.json"
PLAN = STUDY / "PLAN.md"
SELECTOR_CODE = STUDY / "select_sets.py"
REPORT_CODE = STUDY / "report_results.py"
CHOICE_AUDIT = HERE / "INDEPENDENT_CHOICE_AUDIT.json"
ROOT_REPORT_REVIEW = ROOT_REVIEW / "ROOT_REPORT_CODE_REVIEW_v2.json"
ROOT_Q_RECEIPT = ROOT_REVIEW / "ROOT_Q_RECONSTRUCTION.json"
BASELINE = ROOT / (
    "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/"
    "baseline_runner_predictions.parquet"
)
SCHEDULE = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
SCHEDULE_RECEIPT = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
OUT = HERE / "INDEPENDENT_OUTCOME_AUDIT.json"

EXPECTED_SELECTION_SHA = "1f3d40769939b82afe4f6278f92bf5f13af85329355a4a03ddc036391d55322d"
EXPECTED_SELECTION_RECEIPT_SHA = "28711efecfece9da8dbf79639f2dd55223335cc67453273aa46a7efe6a55f2e6"
EXPECTED_SELECTOR_SHA = "9bbd0556236dde13697f62dec70e7a81928bab1f57de0ab267008b429e94c4e2"
EXPECTED_ROOT_Q_SHA = "f50e75f1815793fd4874bc36f38f80d64c4fd0192da2e89fb144b9ae7bae627a"
EXPECTED_CHOICE_AUDIT_SHA = "fc995f8b687b74f08ae5c80f5b456aaa8f04fe33a2b71e23af2cb0be961b26e6"
EXPECTED_REPORT_CODE_SHA = "3d39be089cce838a3f7993cb494b69d76fed1524dbbdc52e159dbaed8c8088d9"
EXPECTED_REPORT_CODE_REVIEW_V2_SHA = "9f5d8865fd8f252557787263509f123aadf1e38819824839f70a16e029bf0de0"
EXPECTED_BASELINE_SHA = "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1"
EXPECTED_SCHEDULE_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_SCHEDULE_RECEIPT_SHA = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"
EXPECTED_DATE_INVENTORY_SHA = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
PRIMARY_DISTANCES = {900, 1000, 1110, 1200}
EXPECTED_FULL_RACES = 1779
EXPECTED_PRIMARY_RACES = 1503


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def preflight_without_labels() -> tuple[list[dict[str, Any]], np.ndarray, dict[str, Any]]:
    required = (SELECTIONS, SELECTION_RECEIPT, PRESELECTION_LOCK, PLAN, SELECTOR_CODE,
                REPORT_CODE, CHOICE_AUDIT, ROOT_REPORT_REVIEW, ROOT_Q_RECEIPT,
                BASELINE, SCHEDULE, SCHEDULE_RECEIPT)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing locked pre-outcome artifact(s): {missing}")
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite independent audit: {OUT}")

    lock = json.loads(PRESELECTION_LOCK.read_text(encoding="utf-8"))
    selection_receipt = json.loads(SELECTION_RECEIPT.read_text(encoding="utf-8"))
    root_q = json.loads(ROOT_Q_RECEIPT.read_text(encoding="utf-8"))
    root_review = json.loads(ROOT_REPORT_REVIEW.read_text(encoding="utf-8"))
    choice_audit = json.loads(CHOICE_AUDIT.read_text(encoding="utf-8"))
    schedule_receipt = json.loads(SCHEDULE_RECEIPT.read_text(encoding="utf-8"))

    if lock.get("status") != "APPROVED_FOR_SELECTION_ONLY":
        raise AssertionError("preselection lock does not pass")
    if selection_receipt.get("status") != "PASS_LABEL_FREE_SELECTION":
        raise AssertionError("selection receipt does not pass")
    if selection_receipt.get("selection_stage_reads_outcome_labels") is not False:
        raise AssertionError("selection stage is not certified label-free")
    if root_q.get("passed") is not True or root_q.get("outcome_labels_read") is not False:
        raise AssertionError("root Q reconstruction is not a passing label-free receipt")
    if root_q.get("new_fits") != 0 or root_q.get("races") != EXPECTED_FULL_RACES:
        raise AssertionError("root Q reconstruction fit/race scope changed")
    if root_review.get("approved") is not True or root_review.get("execution_approved") is not True:
        raise AssertionError("root did not approve outcome-stage execution")
    if sha256_file(ROOT_REPORT_REVIEW) != EXPECTED_REPORT_CODE_REVIEW_V2_SHA:
        raise AssertionError("root outcome-code approval v2 changed")
    if root_review.get("selection_artifact_sha256") != EXPECTED_SELECTION_SHA:
        raise AssertionError("root report approval is not bound to the locked selection artifact")
    if root_review.get("choice_independent_audit_sha256") != EXPECTED_CHOICE_AUDIT_SHA:
        raise AssertionError("root report approval is not bound to the independent choice audit")
    if choice_audit.get("status") != "PASS_INDEPENDENT_LABEL_FREE_CHOICE_REPLAY":
        raise AssertionError("independent choice audit does not pass")
    if choice_audit.get("outcome_labels_read") is not False:
        raise AssertionError("independent choice audit read labels")

    expected_hashes = (
        (SELECTIONS, EXPECTED_SELECTION_SHA),
        (SELECTION_RECEIPT, EXPECTED_SELECTION_RECEIPT_SHA),
        (ROOT_Q_RECEIPT, EXPECTED_ROOT_Q_SHA),
        (BASELINE, EXPECTED_BASELINE_SHA),
        (SCHEDULE, EXPECTED_SCHEDULE_SHA),
        (SCHEDULE_RECEIPT, EXPECTED_SCHEDULE_RECEIPT_SHA),
        (CHOICE_AUDIT, EXPECTED_CHOICE_AUDIT_SHA),
    )
    for path, expected in expected_hashes:
        if sha256_file(path) != expected:
            raise AssertionError(f"locked artifact hash mismatch: {path.relative_to(ROOT)}")
    if selection_receipt.get("selector_code_sha256") != EXPECTED_SELECTOR_SHA:
        raise AssertionError("selection receipt is not bound to the approved selector")
    if sha256_file(SELECTOR_CODE) != EXPECTED_SELECTOR_SHA:
        raise AssertionError("selector code changed after choice generation")
    if root_review.get("plan_sha256") != sha256_file(PLAN):
        raise AssertionError("plan changed after root outcome code review")
    if root_review.get("selection_receipt_sha256") != EXPECTED_SELECTION_RECEIPT_SHA:
        raise AssertionError("root report approval is not bound to selection receipt")

    if schedule_receipt.get("status") != "FROZEN_BEFORE_EVALUATION_METRICS":
        raise AssertionError("bootstrap schedule was not frozen before outcome metrics")
    if (schedule_receipt.get("seed") != 20261011 or schedule_receipt.get("draws") != 2000
            or schedule_receipt.get("dates_per_draw") != 269
            or schedule_receipt.get("date_inventory_sha256") != EXPECTED_DATE_INVENTORY_SHA
            or schedule_receipt.get("schedule_sha256") != EXPECTED_SCHEDULE_SHA):
        raise AssertionError("bootstrap schedule metadata changed")
    schedule = np.load(SCHEDULE, allow_pickle=False)
    if schedule.shape != (2000, 269) or schedule.dtype != np.int32:
        raise AssertionError("bootstrap schedule shape or dtype changed")
    if not bool(((schedule >= 0) & (schedule < 269)).all()):
        raise AssertionError("bootstrap schedule contains an out-of-range date index")
    expected_schedule = np.random.default_rng(20261011).integers(
        0, 269, size=(2000, 269), endpoint=False, dtype=np.int32
    )
    if not np.array_equal(schedule, expected_schedule):
        raise AssertionError("bootstrap schedule differs from its frozen RNG recipe")

    # The root-reviewed report hash is recorded. If the working report source
    # has changed since that review, this independent aggregation still uses
    # its own implementation and never executes the changed report code.
    report_hash_current = sha256_file(REPORT_CODE)
    report_hash_approved = root_review.get("report_code_sha256")
    approved_run_binding = (
        report_hash_current == report_hash_approved == EXPECTED_REPORT_CODE_SHA
        and root_review.get("supersedes") == "ROOT_REPORT_CODE_REVIEW.json"
        and root_review.get("reviewed_static_fixes_no_choice_rule_change") is True
    )
    selection_rows = read_jsonl(SELECTIONS)
    if len(selection_rows) != EXPECTED_FULL_RACES or len({r["race_id"] for r in selection_rows}) != EXPECTED_FULL_RACES:
        raise AssertionError("locked selection ledger is incomplete or duplicated")
    return selection_rows, schedule, {
        "root_report_review_sha256": sha256_file(ROOT_REPORT_REVIEW),
        "root_reviewed_report_code_sha256": report_hash_approved,
        "working_report_code_sha256_at_independent_audit": report_hash_current,
        "working_report_code_matches_root_approval": approved_run_binding,
        "selection_sha256": sha256_file(SELECTIONS),
        "selection_receipt_sha256": sha256_file(SELECTION_RECEIPT),
        "choice_audit_sha256": sha256_file(CHOICE_AUDIT),
        "root_q_receipt_sha256": sha256_file(ROOT_Q_RECEIPT),
        "baseline_sha256": sha256_file(BASELINE),
        "bootstrap_schedule_sha256": sha256_file(SCHEDULE),
        "bootstrap_receipt_sha256": sha256_file(SCHEDULE_RECEIPT),
        "report_execution_approval": True,
    }


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    n = int(len(frame))
    if n == 0:
        return {"races": 0}
    base = frame["baseline_captured"].to_numpy(dtype=np.int64)
    cand = frame["candidate_captured"].to_numpy(dtype=np.int64)
    base_hit = base == 3
    cand_hit = cand == 3
    overlaps = frame["selection_overlap"].to_numpy(dtype=np.int64)
    return {
        "races": n,
        "baseline_all_three_hits": int(base_hit.sum()),
        "candidate_all_three_hits": int(cand_hit.sum()),
        "baseline_all_three_hit_rate": float(base_hit.mean()),
        "candidate_all_three_hit_rate": float(cand_hit.mean()),
        "candidate_minus_baseline_hit_rate": float((cand_hit.astype(np.int8) - base_hit.astype(np.int8)).mean()),
        "baseline_only_hits": int((base_hit & ~cand_hit).sum()),
        "candidate_only_hits": int((cand_hit & ~base_hit).sum()),
        "both_hit": int((base_hit & cand_hit).sum()),
        "both_missed": int((~base_hit & ~cand_hit).sum()),
        "selection_changed_races": int((overlaps != 5).sum()),
        "selection_overlap_counts": {str(k): int((overlaps == k).sum()) for k in range(6)},
        "mean_selection_overlap": float(overlaps.mean()),
        "baseline_miss_distribution": {str(k): int((base == 3 - k).sum()) for k in range(4)},
        "candidate_miss_distribution": {str(k): int((cand == 3 - k).sum()) for k in range(4)},
        "baseline_mean_captured": float(base.mean()),
        "candidate_mean_captured": float(cand.mean()),
        "baseline_mean_candidate_q_utility": float(frame["candidate_q_on_baseline_top5"].mean()),
        "candidate_mean_candidate_q_utility": float(frame["candidate_q_selected"].mean()),
    }


def grouped(frame: pd.DataFrame, by: str) -> dict[str, Any]:
    return {str(key): summarize(group) for key, group in frame.groupby(by, sort=True, observed=True)}


def make_race_outcomes(selection_rows: list[dict[str, Any]]) -> pd.DataFrame:
    # This is the first operation in this audit that opens y; all hashes,
    # selection and approval checks have already passed in preflight.
    labels = pd.read_parquet(
        BASELINE,
        columns=["race_id", "race_date", "year", "distance_m", "horse_id", "horse_number", "y"],
    )
    labels["y"] = pd.to_numeric(labels["y"], errors="coerce")
    if labels["y"].isna().any() or not set(labels["y"].unique()).issubset({0, 1}):
        raise AssertionError("outcome labels are missing or nonbinary")
    if labels[["race_id", "horse_id"]].duplicated().any():
        raise AssertionError("duplicate outcome runner key")

    choices = {str(row["race_id"]): row for row in selection_rows}
    if len(choices) != EXPECTED_FULL_RACES:
        raise AssertionError("duplicate selection race id")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for race_id, frame in labels.groupby("race_id", sort=True, observed=True):
        rid = str(race_id)
        if rid not in choices or rid in seen:
            raise AssertionError(f"selection/outcome race mismatch: {rid}")
        seen.add(rid)
        choice = choices[rid]
        roster_ids = frame["horse_id"].astype(str).tolist()
        if len(roster_ids) != int(choice["field_n"]) or len(set(roster_ids)) != len(roster_ids):
            raise AssertionError(f"outcome roster differs from locked field in {rid}")
        if int(frame["y"].sum()) != 3:
            raise AssertionError(f"race does not contain exactly three actual Top3 labels: {rid}")
        year = frame["year"].drop_duplicates().tolist()
        distance = frame["distance_m"].drop_duplicates().tolist()
        dates = pd.to_datetime(frame["race_date"].drop_duplicates(), errors="raise").dt.strftime("%Y-%m-%d").tolist()
        if len(year) != 1 or int(year[0]) != int(choice["year"]):
            raise AssertionError(f"year mismatch: {rid}")
        if len(distance) != 1 or int(distance[0]) != int(choice["distance_m"]):
            raise AssertionError(f"distance mismatch: {rid}")
        expected_date = pd.to_datetime(choice["race_date"]).strftime("%Y-%m-%d")
        if len(dates) != 1 or dates[0] != expected_date:
            raise AssertionError(f"race date mismatch: {rid}")
        actual = set(frame.loc[frame["y"].astype(int) == 1, "horse_id"].astype(str))
        baseline = set(choice["baseline_horse_ids"])
        candidate = set(choice["candidate_horse_ids"])
        if len(actual) != 3 or not baseline.issubset(set(roster_ids)) or not candidate.issubset(set(roster_ids)):
            raise AssertionError(f"invalid actual or selected runner set: {rid}")
        base_captured = len(actual & baseline)
        candidate_captured = len(actual & candidate)
        overlap = len(baseline & candidate)
        if len(baseline) != 5 or len(candidate) != 5:
            raise AssertionError(f"selection is not exactly five horses: {rid}")
        out.append({
            "race_id": rid,
            "race_date": expected_date,
            "year": int(year[0]),
            "distance_m": int(distance[0]),
            "career_stratum": str(choice["career_stratum"]),
            "primary_distance": int(distance[0]) in PRIMARY_DISTANCES,
            "baseline_captured": base_captured,
            "candidate_captured": candidate_captured,
            "selection_overlap": overlap,
            "candidate_q_on_baseline_top5": float(choice["candidate_q_on_baseline_top5"]),
            "candidate_q_selected": float(choice["candidate_q_selected"]),
        })
    if seen != set(choices) or len(out) != EXPECTED_FULL_RACES:
        raise AssertionError("outcome cohort differs from locked choice cohort")
    frame = pd.DataFrame(out).sort_values("race_id", kind="stable").reset_index(drop=True)
    if int(frame["primary_distance"].sum()) != EXPECTED_PRIMARY_RACES:
        raise AssertionError("primary cohort size changed")
    return frame


def bootstrap_ci(primary: pd.DataFrame, schedule: np.ndarray) -> dict[str, Any]:
    by_date = primary.groupby("race_date", sort=True).agg(
        n=("race_id", "size"),
        candidate_hits=("candidate_captured", lambda x: int((x == 3).sum())),
        baseline_hits=("baseline_captured", lambda x: int((x == 3).sum())),
    )
    dates = list(by_date.index.astype(str))
    if len(dates) != 269:
        raise AssertionError("primary date inventory must contain 269 dates")
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    if date_hash != EXPECTED_DATE_INVENTORY_SHA:
        raise AssertionError("primary dates differ from the frozen inventory")
    n_by_date = by_date["n"].to_numpy(dtype=np.int64)
    delta_by_date = (by_date["candidate_hits"] - by_date["baseline_hits"]).to_numpy(dtype=np.int64)
    if len(n_by_date) != schedule.shape[1] or int(n_by_date.sum()) != len(primary):
        raise AssertionError("primary date race count does not match bootstrap schedule")
    numerator = delta_by_date[schedule].sum(axis=1, dtype=np.int64)
    denominator = n_by_date[schedule].sum(axis=1, dtype=np.int64)
    samples = numerator / denominator
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
        "replicate_sd_ddof1": float(samples.std(ddof=1)),
        "delta_replicate_min": float(samples.min()),
        "delta_replicate_max": float(samples.max()),
    }


def run() -> dict[str, Any]:
    rows, schedule, provenance = preflight_without_labels()
    races = make_race_outcomes(rows)
    primary = races.loc[races.primary_distance].copy()
    full = races
    primary_summary = summarize(primary)
    full_summary = summarize(full)
    ci = bootstrap_ci(primary, schedule)
    gate = primary_summary["candidate_minus_baseline_hit_rate"] > 0.0 and ci["lower"] > 0.0
    return {
        "status": "PASS_INDEPENDENT_OUTCOME_RECOMPUTATION",
        "study": "20261025_top5_set_selection_v1",
        "target": "all three actual Top3 horse IDs are contained in exactly five selected horse IDs",
        "outcome_labels_read_only_after_all_selection_and_approval_hash_checks": True,
        "races": len(full),
        "primary_distances_m": sorted(PRIMARY_DISTANCES),
        "primary": primary_summary,
        "full_cohort": full_summary,
        "subgroups_primary": {
            "by_year": grouped(primary, "year"),
            "by_distance_m": grouped(primary, "distance_m"),
            "by_career_stratum": grouped(primary, "career_stratum"),
        },
        "subgroups_full": {
            "by_year": grouped(full, "year"),
            "by_distance_m": grouped(full, "distance_m"),
            "by_career_stratum": grouped(full, "career_stratum"),
        },
        "primary_date_bootstrap_95ci": ci,
        "success_gate": {
            "criterion": "primary paired hit-rate delta > 0 and 95% date-bootstrap CI lower bound > 0",
            "passed": bool(gate),
        },
        "provenance": provenance,
        "disclosures": {
            "historical_data_is_repeatedly_inspected_development_period": True,
            "independent_future_holdout": False,
            "new_fits": 0,
            "selector_stage_label_free": True,
            "reviewer_label_access": "Three first-race y/log_loss/brier rows were exposed during prior schema inspection; those values were not aggregated or used to alter the rules.",
        },
    }


if __name__ == "__main__":
    result = run()
    with OUT.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "status": result["status"],
        "primary_races": result["primary"]["races"],
        "full_races": result["full_cohort"]["races"],
        "primary_delta": result["primary"]["candidate_minus_baseline_hit_rate"],
        "primary_ci95": [result["primary_date_bootstrap_95ci"]["lower"], result["primary_date_bootstrap_95ci"]["upper"]],
        "success_gate": result["success_gate"]["passed"],
        "report_code_matches_root_approved_hash": result["provenance"]["working_report_code_matches_root_approval"],
        "audit_sha256": sha256_file(OUT),
        "bytes": OUT.stat().st_size,
    }, sort_keys=True))

"""Reconcile independent outcomes with the locked main and root summaries."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = ROOT / "jeju/research/20261025_top5_set_selection_v1"
ROOT_REVIEW = ROOT / "jeju/research/20261025_top5_set_rootreview_v1"
SELECTIONS = STUDY / "outputs/selections.jsonl"
SELECTION_RECEIPT = STUDY / "outputs/selection_receipt.json"
MAIN_METRICS = STUDY / "outputs/metrics.json"
MAIN_RACES = STUDY / "outputs/race_results.jsonl"
MAIN_RECEIPT = STUDY / "outputs/report_receipt.json"
ROOT_OUTCOMES = ROOT_REVIEW / "ROOT_OUTCOME_RECOMPUTATION.json"
ROOT_REPORT_REVIEW_V2 = ROOT_REVIEW / "ROOT_REPORT_CODE_REVIEW_v2.json"
INDEPENDENT = HERE / "INDEPENDENT_OUTCOME_AUDIT.json"
BASELINE = ROOT / (
    "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/"
    "baseline_runner_predictions.parquet"
)
OUT = HERE / "OUTCOME_RECONCILIATION.json"

EXPECTED_SELECTION_SHA = "1f3d40769939b82afe4f6278f92bf5f13af85329355a4a03ddc036391d55322d"
EXPECTED_SELECTOR_SHA = "9bbd0556236dde13697f62dec70e7a81928bab1f57de0ab267008b429e94c4e2"
EXPECTED_REPORT_CODE_SHA = "3d39be089cce838a3f7993cb494b69d76fed1524dbbdc52e159dbaed8c8088d9"
EXPECTED_PRIMARY = 1503
EXPECTED_FULL = 1779


def sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def close(a: Any, b: Any, tol: float = 1e-15) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k], tol) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tol)
    return a == b


def assert_equivalent(label: str, actual: Any, expected: Any, tol: float = 1e-15) -> None:
    if not close(actual, expected, tol):
        raise AssertionError(f"{label} differs")


def compare_summary(main: dict[str, Any], independent: dict[str, Any], label: str) -> int:
    assert_equivalent(f"{label} summary", main, independent)
    return len(main)


def reconcile() -> dict[str, Any]:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUT}")
    for path in (SELECTIONS, SELECTION_RECEIPT, MAIN_METRICS, MAIN_RACES, MAIN_RECEIPT,
                 ROOT_OUTCOMES, ROOT_REPORT_REVIEW_V2, INDEPENDENT, BASELINE):
        if not path.is_file():
            raise FileNotFoundError(path)

    selection_hash = sha256_file(SELECTIONS)
    selection_receipt = load_json(SELECTION_RECEIPT)
    main_receipt = load_json(MAIN_RECEIPT)
    main_metrics = load_json(MAIN_METRICS)
    root_result = load_json(ROOT_OUTCOMES)
    report_review = load_json(ROOT_REPORT_REVIEW_V2)
    independent = load_json(INDEPENDENT)
    if selection_hash != EXPECTED_SELECTION_SHA or main_receipt.get("selection_artifact_sha256") != selection_hash:
        raise AssertionError("main report is not bound to the locked selection ledger")
    if selection_receipt.get("selector_code_sha256") != EXPECTED_SELECTOR_SHA:
        raise AssertionError("selection receipt is not bound to reviewed selector")
    if (main_receipt.get("status") != "PASS_OUTCOME_REPORT"
            or main_receipt.get("report_code_sha256") != EXPECTED_REPORT_CODE_SHA
            or main_receipt.get("root_report_review_sha256") != sha256_file(ROOT_REPORT_REVIEW_V2)):
        raise AssertionError("main report receipt/code review binding is incomplete")
    if (report_review.get("approved") is not True
            or report_review.get("execution_approved") is not True
            or report_review.get("report_code_sha256") != EXPECTED_REPORT_CODE_SHA):
        raise AssertionError("v2 root report review does not bind executed report code")
    if root_result.get("passed") is not True or root_result.get("new_fits") != 0:
        raise AssertionError("root independent outcome receipt does not pass")
    if root_result.get("selection_sha256") != selection_hash:
        raise AssertionError("root independent outcome receipt uses a different choice ledger")
    if independent.get("status") != "PASS_INDEPENDENT_OUTCOME_RECOMPUTATION":
        raise AssertionError("independent outcome aggregation does not pass")
    if independent.get("provenance", {}).get("working_report_code_matches_root_approval") is not True:
        raise AssertionError("approved report code hash did not match at independent aggregation")

    # Independent race-level recheck: compare every main ledger outcome field
    # directly against y and the hash-locked selected horse IDs.
    choices = {str(x["race_id"]): x for x in (json.loads(line) for line in SELECTIONS.read_text(encoding="utf-8").splitlines())}
    main_rows = [json.loads(line) for line in MAIN_RACES.read_text(encoding="utf-8").splitlines()]
    main_by_race = {str(x["race_id"]): x for x in main_rows}
    if len(choices) != EXPECTED_FULL or len(main_by_race) != EXPECTED_FULL or len(main_rows) != EXPECTED_FULL:
        raise AssertionError("choice or main race ledger count/uniqueness changed")
    if set(choices) != set(main_by_race):
        raise AssertionError("main race ledger race IDs differ from the locked selections")

    labels = pd.read_parquet(
        BASELINE,
        columns=["race_id", "race_date", "year", "distance_m", "horse_id", "y"],
    )
    labels["y"] = pd.to_numeric(labels["y"], errors="coerce")
    if labels["y"].isna().any() or not set(labels["y"].unique()).issubset({0, 1}):
        raise AssertionError("invalid y values in frozen source")
    for race_id, group in labels.groupby("race_id", sort=True, observed=True):
        rid = str(race_id)
        choice = choices[rid]
        output = main_by_race[rid]
        actual = set(group.loc[group.y.astype(int) == 1, "horse_id"].astype(str))
        if len(actual) != 3 or int(group.y.sum()) != 3:
            raise AssertionError(f"race does not have exactly three top runners: {rid}")
        baseline_ids = set(choice["baseline_horse_ids"])
        candidate_ids = set(choice["candidate_horse_ids"])
        base_n, candidate_n = len(actual & baseline_ids), len(actual & candidate_ids)
        overlap = len(baseline_ids & candidate_ids)
        expected = {
            "baseline_horse_ids": choice["baseline_horse_ids"],
            "candidate_horse_ids": choice["candidate_horse_ids"],
            "baseline_captured": base_n,
            "candidate_captured": candidate_n,
            "baseline_misses": 3 - base_n,
            "candidate_misses": 3 - candidate_n,
            "baseline_all_three_hit": base_n == 3,
            "candidate_all_three_hit": candidate_n == 3,
            "selection_overlap": overlap,
            "selection_changed": overlap != 5,
            "candidate_q_on_baseline_top5": choice["candidate_q_on_baseline_top5"],
            "candidate_q_selected": choice["candidate_q_selected"],
            "candidate_q_max": choice["candidate_q_max"],
            "candidate_q_gap_from_max": choice["candidate_q_gap_from_max"],
        }
        for key, value in expected.items():
            if key not in output or not close(output[key], value):
                raise AssertionError(f"main race result {key} does not match direct outcome recomputation: {rid}")
    if len(labels.race_id.unique()) != EXPECTED_FULL:
        raise AssertionError("baseline y outcome cohort count changed")

    subgroup_checks = 0
    for domain in ("primary", "full_cohort"):
        subgroup_checks += compare_summary(main_metrics[domain], independent[domain], domain)
    for scope in ("subgroups_primary", "subgroups_full"):
        for axis, groups in main_metrics[scope].items():
            for key, main_summary in groups.items():
                independent_summary = independent[scope][axis][key]
                subgroup_checks += compare_summary(main_summary, independent_summary, f"{scope}/{axis}/{key}")
    ci_main = main_metrics["primary_date_bootstrap_95ci"]
    ci_ind = independent["primary_date_bootstrap_95ci"]
    for key in ("replicates", "cluster", "date_count", "primary_race_count", "ci_level", "quantile_method", "lower", "upper", "replicate_mean"):
        if not close(ci_main[key], ci_ind[key]):
            raise AssertionError(f"main and independent primary bootstrap differ at {key}")
    if not math.isclose(ci_main["replicate_sd"], ci_ind["replicate_sd_ddof1"], rel_tol=0.0, abs_tol=1e-15):
        raise AssertionError("main and independent bootstrap sample SD differ")

    # Root receipts store percentages and confidence limits in percentage points.
    root_primary = root_result["primary"]
    independent_primary = independent["primary"]
    for count_key, root_key in (("races", "races"), ("baseline_all_three_hits", "baseline_hits"),
                                ("candidate_all_three_hits", "candidate_hits"), ("baseline_only_hits", "baseline_only"),
                                ("candidate_only_hits", "candidate_only"), ("both_hit", "both_hit"),
                                ("both_missed", "both_miss"), ("selection_changed_races", "changed_sets")):
        if independent_primary[count_key] != root_primary[root_key]:
            raise AssertionError(f"root independent primary mismatch: {root_key}")
    for metric, root_key in (("baseline_all_three_hit_rate", "baseline_percent"),
                             ("candidate_all_three_hit_rate", "candidate_percent"),
                             ("candidate_minus_baseline_hit_rate", "delta_pp")):
        if not math.isclose(independent_primary[metric] * 100.0, root_primary[root_key], rel_tol=0.0, abs_tol=1e-12):
            raise AssertionError(f"root independent primary rate mismatch: {root_key}")
    if not close([x * 100.0 for x in (independent["primary_date_bootstrap_95ci"]["lower"], independent["primary_date_bootstrap_95ci"]["upper"])], root_primary["ci95_pp"], 1e-12):
        raise AssertionError("root independent primary bootstrap interval differs")
    if root_primary["primary_gate_passed"] is not False or independent["success_gate"]["passed"] is not False:
        raise AssertionError("primary prespecified gate should fail for all three implementations")

    return {
        "status": "PASS_MAIN_ROOT_INDEPENDENT_OUTCOME_RECONCILIATION",
        "selection_sha256": selection_hash,
        "selector_sha256": EXPECTED_SELECTOR_SHA,
        "report_code_sha256": EXPECTED_REPORT_CODE_SHA,
        "root_report_review_v2_sha256": sha256_file(ROOT_REPORT_REVIEW_V2),
        "main_metrics_sha256": sha256_file(MAIN_METRICS),
        "main_race_results_sha256": sha256_file(MAIN_RACES),
        "main_report_receipt_sha256": sha256_file(MAIN_RECEIPT),
        "root_outcome_recomputation_sha256": sha256_file(ROOT_OUTCOMES),
        "independent_outcome_audit_sha256": sha256_file(INDEPENDENT),
        "per_race_main_ledger_matches_raw_y_and_locked_choices": True,
        "races_crosschecked": EXPECTED_FULL,
        "summary_and_subgroup_comparison_count": subgroup_checks,
        "primary_ci_matches_main_and_root": True,
        "root_primary_counts_rates_and_gate_match": True,
        "primary": {
            "baseline_all_three": f"{independent_primary['baseline_all_three_hits']}/{independent_primary['races']}",
            "candidate_all_three": f"{independent_primary['candidate_all_three_hits']}/{independent_primary['races']}",
            "delta": independent_primary["candidate_minus_baseline_hit_rate"],
            "ci95": [independent["primary_date_bootstrap_95ci"]["lower"], independent["primary_date_bootstrap_95ci"]["upper"]],
            "gate_passed": False,
        },
    }


if __name__ == "__main__":
    result = reconcile()
    with OUT.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "status": result["status"],
        "races_crosschecked": result["races_crosschecked"],
        "subgroup_comparisons": result["summary_and_subgroup_comparison_count"],
        "primary_delta": result["primary"]["delta"],
        "primary_ci95": result["primary"]["ci95"],
        "gate_passed": result["primary"]["gate_passed"],
        "reconciliation_sha256": sha256_file(OUT),
    }, sort_keys=True))

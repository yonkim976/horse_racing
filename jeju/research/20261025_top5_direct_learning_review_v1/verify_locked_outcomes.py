"""Independently recompute locked selector outcomes after root approval.

This file is deliberately dormant until ROOT_OUTCOME_APPROVAL.json binds the
choice artifacts, fit receipt, and report code. Only after those checks does
main() read the explicit outcome allowlist, including y. It imports no main
study Python module and writes only compact artifacts in this review folder.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
REVIEW = Path(__file__).resolve().parent
MAIN = ROOT / "jeju/research/20261025_top5_direct_learning_v1"
OUT = MAIN / "outputs"

PLAN_PATH = MAIN / "PLAN.md"
SOURCE_AUDIT_PATH = MAIN / "SOURCE_AUDIT.md"
FIT_RECEIPT_PATH = OUT / "FIT_RECEIPT.json"
CHOICES_PATH = OUT / "candidate_choices.jsonl"
CHOICES_RECEIPT_PATH = OUT / "CHOICES_RECEIPT.json"
OUTCOME_APPROVAL_PATH = OUT / "ROOT_OUTCOME_APPROVAL.json"
REPORT_CODE_PATH = MAIN / "report_outcomes.py"
OUTCOMES_PATH = OUT / "outcomes.json"
RACE_OUTCOMES_PATH = OUT / "race_outcomes.jsonl"
OUTCOME_RECEIPT_PATH = OUT / "OUTCOME_RECEIPT.json"

PLAN_SHA256 = "c5683a8716e62094a7856cadfd44119dfac3c6ac3edd9f08652a951e42297012"
SOURCE_AUDIT_SHA256 = "c70596688c22c97deb7fa48cba21ef6e5442ea29e1901f790277c1f03fbe3fbd"
ROOT_AUDIT_SHA256 = "b263703aae9e7d5eca2bda394d4c20de67144bcaf78e959f5add9efffc8310f8"
BASELINE_REL = "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
BASELINE_SHA256 = "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1"
BOOTSTRAP_REL = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
BOOTSTRAP_RECEIPT_REL = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
BOOTSTRAP_RECEIPT_SHA256 = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"
DATE_INVENTORY_SHA256 = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
BOOTSTRAP_SEED = 20261011
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_DATES = 269
EVAL_YEARS = (2024, 2025, 2026)
PRIMARY_DISTANCES = {900, 1000, 1110, 1200}
OBJECTIVE_ID = "partial_event_gibbs_nll_additive_selection_head_v1"

OUTCOME_COLUMNS = [
    "api_record_id",
    "race_id",
    "race_date",
    "year",
    "distance_m",
    "horse_id",
    "horse_number",
    "field_n",
    "variant",
    "score",
    "y",
]


class OutcomeReplayError(RuntimeError):
    """Raised when a frozen outcome source or report artifact fails replay."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OutcomeReplayError(message)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def source_path(relative: str, expected_hash: str) -> Path:
    path = ROOT / relative
    require(not path.is_symlink(), f"source symlink is not allowed: {relative}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"source escaped workspace: {relative}")
    require(digest(resolved) == expected_hash, f"source hash mismatch: {relative}")
    return resolved


def read_json(path: Path, name: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"required locked artifact missing or unsafe: {name}")
    result = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(result, dict), f"JSON root is not an object: {name}")
    return result


def load_jsonl(path: Path, name: str) -> list[dict[str, Any]]:
    require(path.is_file() and not path.is_symlink(), f"locked artifact missing or unsafe: {name}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OutcomeReplayError(f"invalid {name} JSONL row {line_number}") from exc
            require(isinstance(record, dict), f"{name} row is not an object: {line_number}")
            rows.append(record)
    return rows


def validate_preoutcome_locks() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str, str, str]:
    """Validate every approval and artifact hash before opening the y column."""
    require(digest(PLAN_PATH) == PLAN_SHA256, "plan changed since review")
    require(digest(SOURCE_AUDIT_PATH) == SOURCE_AUDIT_SHA256, "source audit changed since review")
    fit_receipt = read_json(FIT_RECEIPT_PATH, "FIT_RECEIPT.json")
    choices_receipt = read_json(CHOICES_RECEIPT_PATH, "CHOICES_RECEIPT.json")
    require(fit_receipt.get("status") == "PASS" and fit_receipt.get("fit_count") == 3, "fit receipt is not a three-fold PASS")
    require(fit_receipt.get("evaluation_outcomes_read") is False and fit_receipt.get("outcome_metrics_computed") is False, "fit receipt reports evaluation outcome access")
    require(fit_receipt.get("source_audit_root_sha256") == ROOT_AUDIT_SHA256, "fit receipt root audit hash mismatch")
    require(fit_receipt.get("plan_sha256") == PLAN_SHA256 and fit_receipt.get("source_audit_sha256") == SOURCE_AUDIT_SHA256, "fit receipt source lock mismatch")
    fit_sha = digest(FIT_RECEIPT_PATH)

    require(choices_receipt.get("status") == "PASS" and choices_receipt.get("outcome_labels_read") is False, "choice receipt is not label-free PASS")
    require(choices_receipt.get("fit_receipt_sha256") == fit_sha, "choice receipt references another fit receipt")
    require(choices_receipt.get("plan_sha256") == PLAN_SHA256 and choices_receipt.get("source_audit_sha256") == SOURCE_AUDIT_SHA256, "choice receipt source lock mismatch")
    choice_sha = digest(CHOICES_PATH)
    choice_receipt_sha = digest(CHOICES_RECEIPT_PATH)
    require(choice_sha == choices_receipt.get("choices_sha256"), "choice artifact hash differs from choice receipt")
    require(CHOICES_PATH.stat().st_size == int(choices_receipt.get("choices_bytes", -1)), "choice byte count differs from receipt")
    require(choices_receipt.get("candidate_choices_created") == 1779 and choices_receipt.get("primary_races") == 1503, "locked choice population changed")
    require(choices_receipt.get("full_races") == 1779 and choices_receipt.get("zero_beta_negative_control_matches_baseline_all_races") is True, "locked choice control/population changed")

    review_receipt_path = REVIEW / "REPLAYED_CHOICES_RECEIPT.json"
    review_receipt = read_json(review_receipt_path, "independent choice replay receipt")
    require(review_receipt.get("status") == "PASS" and review_receipt.get("outcome_labels_read") is False, "independent choice replay is not label-free PASS")
    require(review_receipt.get("main_choices_sha256") == choice_sha and review_receipt.get("main_choices_receipt_sha256") == choice_receipt_sha, "independent choice replay references other choices")
    require(review_receipt.get("checks", {}).get("locked_choice_rows_exact_match") == 1779, "independent choice replay did not match every locked race")
    require(review_receipt.get("checks", {}).get("replayed_primary_races") == 1503, "independent choice replay primary count mismatch")
    require(digest(REVIEW / "REPLAYED_LOCKED_CHOICES.jsonl") == review_receipt.get("choice_file_sha256"), "independent choice replay ledger hash mismatch")

    approval = read_json(OUTCOME_APPROVAL_PATH, "ROOT_OUTCOME_APPROVAL.json")
    require(approval.get("status") == "approved", "root outcome approval is absent or not approved")
    require(approval.get("plan_sha256") == PLAN_SHA256 and approval.get("source_audit_sha256") == SOURCE_AUDIT_SHA256, "outcome approval plan/source hash mismatch")
    require(approval.get("choices_sha256") == choice_sha, "outcome approval references another choice artifact")
    require(approval.get("choices_receipt_sha256") == choice_receipt_sha, "outcome approval references another choice receipt")
    require(approval.get("fit_receipt_sha256") == fit_sha, "outcome approval references another fit receipt")
    require(approval.get("outcome_code_sha256") == digest(REPORT_CODE_PATH), "outcome approval report-code hash is stale")
    approval_sha = digest(OUTCOME_APPROVAL_PATH)

    outcome_receipt = read_json(OUTCOME_RECEIPT_PATH, "OUTCOME_RECEIPT.json")
    require(outcome_receipt.get("status") == "PASS" and outcome_receipt.get("outcome_labels_read") is True, "main outcome receipt is not PASS")
    require(outcome_receipt.get("outcome_code_sha256") == digest(REPORT_CODE_PATH), "main outcome receipt report-code hash is stale")
    require(outcome_receipt.get("root_outcome_approval_sha256") == approval_sha, "outcome receipt references another approval")
    require(outcome_receipt.get("choices_sha256") == choice_sha and outcome_receipt.get("choices_receipt_sha256") == choice_receipt_sha, "outcome receipt references another choice lock")
    require(outcome_receipt.get("fit_receipt_sha256") == fit_sha, "outcome receipt references another fit receipt")
    require(outcome_receipt.get("plan_sha256") == PLAN_SHA256 and outcome_receipt.get("source_audit_sha256") == SOURCE_AUDIT_SHA256, "outcome receipt source lock mismatch")
    require(outcome_receipt.get("bootstrap_schedule_sha256") == BOOTSTRAP_SHA256 and outcome_receipt.get("date_inventory_sha256") == DATE_INVENTORY_SHA256, "outcome receipt bootstrap lock mismatch")
    require(outcome_receipt.get("outcome_file") == "outcomes.json" and outcome_receipt.get("race_outcome_file") == "race_outcomes.jsonl", "outcome receipt filenames changed")
    require(OUTCOMES_PATH.stat().st_size == int(outcome_receipt.get("outcome_bytes", -1)), "main outcome JSON byte count mismatch")
    require(digest(OUTCOMES_PATH) == outcome_receipt.get("outcome_sha256"), "main outcome JSON hash mismatch")
    require(RACE_OUTCOMES_PATH.stat().st_size == int(outcome_receipt.get("race_outcome_bytes", -1)), "main race outcome JSONL byte count mismatch")
    require(digest(RACE_OUTCOMES_PATH) == outcome_receipt.get("race_outcome_sha256"), "main race outcome JSONL hash mismatch")

    outcomes = read_json(OUTCOMES_PATH, "outcomes.json")
    require(outcomes.get("status") == "RETROSPECTIVE_DEVELOPMENT_COMPARISON", "main outcome status is unexpected")
    require(outcomes.get("fit_receipt_sha256") == fit_sha and outcomes.get("choices_sha256") == choice_sha, "main outcome payload references another fit/choice lock")
    require(outcomes.get("choices_receipt_sha256") == choice_receipt_sha, "main outcome payload references another choice receipt")
    return fit_receipt, choices_receipt, outcome_receipt, outcomes, fit_sha, choice_sha, choice_receipt_sha


def choices_date_hash(choices: list[dict[str, Any]]) -> tuple[list[str], str]:
    dates = sorted({
        str(row["race_date"])
        for row in choices
        if int(float(row["distance_m"])) in PRIMARY_DISTANCES
    })
    require(len(dates) == BOOTSTRAP_DATES, "choice-ledger primary date count differs from frozen schedule")
    fingerprint = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(fingerprint == DATE_INVENTORY_SHA256, "choice date inventory differs from frozen bootstrap inventory")
    return dates, fingerprint


def bootstrap_schedule() -> tuple[np.ndarray, Path]:
    schedule_path = source_path(BOOTSTRAP_REL, BOOTSTRAP_SHA256)
    receipt_path = source_path(BOOTSTRAP_RECEIPT_REL, BOOTSTRAP_RECEIPT_SHA256)
    receipt = read_json(receipt_path, "frozen date bootstrap receipt")
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "bootstrap was not frozen before evaluation metrics")
    require(receipt.get("seed") == BOOTSTRAP_SEED and receipt.get("draws") == BOOTSTRAP_DRAWS, "bootstrap seed/draw count changed")
    require(receipt.get("dates_per_draw") == BOOTSTRAP_DATES, "bootstrap dates per draw changed")
    require(receipt.get("date_inventory_sha256") == DATE_INVENTORY_SHA256, "bootstrap date inventory hash changed")
    require(receipt.get("schedule_sha256") == BOOTSTRAP_SHA256, "bootstrap schedule hash changed")
    schedule = np.load(schedule_path, allow_pickle=False)
    require(schedule.shape == (BOOTSTRAP_DRAWS, BOOTSTRAP_DATES) and schedule.dtype == np.int32, "bootstrap array shape or dtype changed")
    require(bool(((schedule >= 0) & (schedule < BOOTSTRAP_DATES)).all()), "bootstrap date index out of range")
    return schedule, schedule_path


def independently_build_race_metrics(labels: pd.DataFrame, choices: list[dict[str, Any]]) -> pd.DataFrame:
    require(labels.columns.tolist() == OUTCOME_COLUMNS, "outcome allowlist/schema changed")
    require(len(labels) == 17412 and labels["api_record_id"].is_unique, "evaluation label row/key count changed")
    require(set(labels["variant"].astype(str)) == {"F1_STYLE6"}, "outcome labels include a non-F1_STYLE6 variant")
    y = pd.to_numeric(labels["y"], errors="coerce")
    require(y.notna().all() and y.isin([0, 1]).all(), "outcome y is not exact binary 0/1")
    labels = labels.copy()
    labels["y"] = y.astype(np.int8)
    groups = {str(key): value for key, value in labels.groupby("race_id", sort=False)}
    choice_map = {str(row["race_id"]): row for row in choices}
    require(len(groups) == 1779 and len(choice_map) == 1779, "race inventory count changed")
    require(groups.keys() == choice_map.keys(), "label and choice race inventories differ")

    records: list[dict[str, Any]] = []
    for race_id in sorted(groups):
        group = groups[race_id].sort_values("horse_number", kind="stable")
        choice = choice_map[race_id]
        n = int(group["field_n"].iloc[0])
        require(len(group) == n and (group["field_n"].astype(int) == n).all(), f"incomplete outcome roster: {race_id}")
        require(group["horse_id"].is_unique and group["horse_number"].is_unique, f"duplicate outcome horse/key: {race_id}")
        require(int(group["y"].sum()) == 3, f"race does not have exactly three Top3 labels: {race_id}")
        require(str(group["race_date"].iloc[0]) == str(choice["race_date"]), f"race date mismatch: {race_id}")
        require(int(group["year"].iloc[0]) == int(choice["year"]), f"race year mismatch: {race_id}")
        require(float(group["distance_m"].iloc[0]) == float(choice["distance_m"]), f"race distance mismatch: {race_id}")
        require(n == int(choice["field_n"]), f"race field size mismatch: {race_id}")
        actual = set(group.loc[group["y"].eq(1), "horse_id"].astype(str))
        base_ids_ordered = list(map(str, choice["baseline_top5_horse_ids"]))
        selector_ids_ordered = list(map(str, choice["selector_top5_horse_ids"]))
        base_nums_ordered = list(map(int, choice["baseline_top5_horse_numbers"]))
        selector_nums_ordered = list(map(int, choice["selector_top5_horse_numbers"]))
        require(len(base_ids_ordered) == len(set(base_ids_ordered)) == 5, f"baseline set is not exactly five distinct horses: {race_id}")
        require(len(selector_ids_ordered) == len(set(selector_ids_ordered)) == 5, f"selector set is not exactly five distinct horses: {race_id}")
        require(len(base_nums_ordered) == len(set(base_nums_ordered)) == 5, f"baseline numbers are not unique: {race_id}")
        require(len(selector_nums_ordered) == len(set(selector_nums_ordered)) == 5, f"selector numbers are not unique: {race_id}")
        roster = set(group["horse_id"].astype(str))
        require(set(base_ids_ordered) <= roster and set(selector_ids_ordered) <= roster, f"selected nonstarter: {race_id}")
        number_by_id = dict(zip(group["horse_id"].astype(str), group["horse_number"].astype(int), strict=True))
        require([number_by_id[horse] for horse in base_ids_ordered] == base_nums_ordered, f"baseline ID/number mapping differs: {race_id}")
        require([number_by_id[horse] for horse in selector_ids_ordered] == selector_nums_ordered, f"selector ID/number mapping differs: {race_id}")

        by_score = sorted(group.to_dict("records"), key=lambda row: (-float(row["score"]), int(row["horse_number"])))[:5]
        require(set(str(row["horse_id"]) for row in by_score) == set(base_ids_ordered), f"raw-score baseline Top5 does not reproduce: {race_id}")
        base_count = len(actual & set(base_ids_ordered))
        selector_count = len(actual & set(selector_ids_ordered))
        records.append({
            "race_id": race_id,
            "race_date": str(group["race_date"].iloc[0]),
            "year": int(group["year"].iloc[0]),
            "distance_m": float(group["distance_m"].iloc[0]),
            "primary_distance": int(float(group["distance_m"].iloc[0])) in PRIMARY_DISTANCES,
            "baseline_all_three_hit": base_count == 3,
            "selector_all_three_hit": selector_count == 3,
            "baseline_captured_top3": base_count,
            "selector_captured_top3": selector_count,
        })
    metrics = pd.DataFrame(records)
    require(len(metrics) == 1779 and int(metrics["primary_distance"].sum()) == 1503, "fixed evaluation cohort counts changed")
    require(metrics["race_id"].is_unique, "independent race metrics contain duplicate race IDs")
    return metrics


def summary(frame: pd.DataFrame) -> dict[str, Any]:
    n = int(len(frame))
    require(n > 0, "cannot summarize an empty cohort")
    base_hits = int(frame["baseline_all_three_hit"].sum())
    selector_hits = int(frame["selector_all_three_hit"].sum())
    selector_counts = frame["selector_captured_top3"].value_counts().reindex([0, 1, 2, 3], fill_value=0)
    baseline_counts = frame["baseline_captured_top3"].value_counts()
    return {
        "races": n,
        "baseline_all_three_hits": base_hits,
        "selector_all_three_hits": selector_hits,
        "baseline_all_three_rate": base_hits / n,
        "selector_all_three_rate": selector_hits / n,
        "selector_minus_baseline_rate": (selector_hits - base_hits) / n,
        "selector_minus_baseline_percentage_points": 100.0 * (selector_hits - base_hits) / n,
        "both_hit": int((frame["baseline_all_three_hit"] & frame["selector_all_three_hit"]).sum()),
        "baseline_only_lost": int((frame["baseline_all_three_hit"] & ~frame["selector_all_three_hit"]).sum()),
        "selector_only_caught": int((~frame["baseline_all_three_hit"] & frame["selector_all_three_hit"]).sum()),
        "both_miss": int((~frame["baseline_all_three_hit"] & ~frame["selector_all_three_hit"]).sum()),
        "selector_captured_top3_count_0_1_2_3": {str(k): int(selector_counts.loc[k]) for k in (0, 1, 2, 3)},
        "baseline_captured_top3_count_0_1_2_3": {str(k): int(baseline_counts.get(k, 0)) for k in (0, 1, 2, 3)},
    }


def grouped_summary(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    return {str(key): summary(group) for key, group in frame.groupby(column, sort=True)}


def paired_date_bootstrap(primary: pd.DataFrame, schedule: np.ndarray, dates: list[str]) -> dict[str, Any]:
    daily = primary.groupby("race_date", sort=True).agg(
        races=("race_id", "size"),
        selector_hits=("selector_all_three_hit", "sum"),
        baseline_hits=("baseline_all_three_hit", "sum"),
    )
    require(list(daily.index.astype(str)) == dates, "primary date inventory differs from frozen schedule")
    require(len(dates) == BOOTSTRAP_DATES and (daily["races"] > 0).all(), "primary date coverage changed")
    date_races = daily["races"].to_numpy(dtype=np.int64)
    date_delta = (daily["selector_hits"] - daily["baseline_hits"]).to_numpy(dtype=np.int64)
    require(int(date_races.sum()) == len(primary), "date-cluster denominators do not sum to primary races")
    numerators = date_delta[schedule].sum(axis=1, dtype=np.int64)
    denominators = date_races[schedule].sum(axis=1, dtype=np.int64)
    require((denominators > 0).all(), "bootstrap replicate has no races")
    replicates = numerators / denominators
    lower, upper = np.quantile(replicates, [0.025, 0.975], method="linear")
    return {
        "seed": BOOTSTRAP_SEED,
        "draws": BOOTSTRAP_DRAWS,
        "date_count": BOOTSTRAP_DATES,
        "date_inventory_sha256": hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest(),
        "schedule_sha256": BOOTSTRAP_SHA256,
        "cluster": "race_date",
        "interval_level": 0.95,
        "quantile_method": "numpy.quantile(method='linear')",
        "lower": float(lower),
        "upper": float(upper),
        "valid_replicates": int(len(replicates)),
        "replicates_with_zero_primary_races": int((denominators == 0).sum()),
    }


def compare_json(expected: Any, actual: Any, location: str = "root") -> None:
    """Compare JSON structures, tolerating only floating-point roundoff."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(expected) == set(actual), f"JSON object keys differ at {location}")
        for key in expected:
            compare_json(expected[key], actual[key], f"{location}.{key}")
        return
    if isinstance(expected, list):
        require(isinstance(actual, list) and len(expected) == len(actual), f"JSON list differs at {location}")
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            compare_json(left, right, f"{location}[{index}]")
        return
    if isinstance(expected, bool) or isinstance(actual, bool):
        require(type(expected) is type(actual) and expected == actual, f"JSON boolean differs at {location}")
        return
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        require(math.isfinite(float(expected)) and math.isfinite(float(actual)), f"nonfinite JSON number at {location}")
        require(abs(float(expected) - float(actual)) <= 1e-14 + 1e-13 * abs(float(expected)), f"JSON numeric value differs at {location}: {expected} vs {actual}")
        return
    require(expected == actual, f"JSON value differs at {location}")


def race_outcome_rows(metrics: pd.DataFrame) -> list[dict[str, Any]]:
    output = []
    for row in metrics.sort_values(["race_date", "race_id"], kind="stable").to_dict("records"):
        output.append({
            "race_id": str(row["race_id"]),
            "race_date": str(row["race_date"]),
            "year": int(row["year"]),
            "distance_m": float(row["distance_m"]),
            "primary_distance": bool(row["primary_distance"]),
            "baseline_all_three_hit": bool(row["baseline_all_three_hit"]),
            "selector_all_three_hit": bool(row["selector_all_three_hit"]),
            "selector_only_caught": bool(row["selector_all_three_hit"] and not row["baseline_all_three_hit"]),
            "baseline_only_lost": bool(row["baseline_all_three_hit"] and not row["selector_all_three_hit"]),
            "baseline_captured_top3": int(row["baseline_captured_top3"]),
            "selector_captured_top3": int(row["selector_captured_top3"]),
            "baseline_missed_top3": 3 - int(row["baseline_captured_top3"]),
            "selector_missed_top3": 3 - int(row["selector_captured_top3"]),
        })
    return output


def build_expected_report(
    metrics: pd.DataFrame,
    choices: list[dict[str, Any]],
    dates: list[str],
    date_hash: str,
    schedule: np.ndarray,
    schedule_path: Path,
    baseline_path: Path,
    fit_receipt: dict[str, Any],
    fit_sha: str,
    choice_sha: str,
    choice_receipt_sha: str,
) -> dict[str, Any]:
    primary = metrics.loc[metrics["primary_distance"]].copy()
    primary_summary = summary(primary)
    full_summary = summary(metrics)
    bootstrap = paired_date_bootstrap(primary, schedule, dates)
    gate = primary_summary["selector_minus_baseline_rate"] > 0.0 and bootstrap["lower"] > 0.0
    changed = sum(set(row["baseline_top5_horse_ids"]) != set(row["selector_top5_horse_ids"]) for row in choices)
    payload = {
        "status": "RETROSPECTIVE_DEVELOPMENT_COMPARISON",
        "study": MAIN.name,
        "objective_id": OBJECTIVE_ID,
        "outcome": "all three actual Top3 horses are contained in the selected exact five-horse set",
        "probability_claim": "none; the Gibbs positive-set mass is a stochastic training surrogate and is not deterministic coverage probability or calibrated probability",
        "primary": primary_summary | {"distance_m": sorted(PRIMARY_DISTANCES)},
        "full": full_summary,
        "primary_date_bootstrap_95ci": bootstrap,
        "label_free_choice_date_inventory_sha256": date_hash,
        "primary_success_gate": {
            "rule": "primary selector-minus-baseline all-three rate > 0 and date-bootstrap 95% CI lower bound > 0",
            "passed": bool(gate),
        },
        "primary_by_year": grouped_summary(primary, "year"),
        "primary_by_distance": grouped_summary(primary, "distance_m"),
        "full_by_year": grouped_summary(metrics, "year"),
        "full_by_distance": grouped_summary(metrics, "distance_m"),
        "training_label_checks": {
            str(year): fit_receipt["folds"][str(year)]["training_label_validation"]
            for year in EVAL_YEARS
        },
        "selection_changed_races": int(changed),
        "fit_receipt_sha256": fit_sha,
        "choices_sha256": choice_sha,
        "choices_receipt_sha256": choice_receipt_sha,
        "bootstrap_source_sha256": digest(schedule_path),
        "baseline_source_sha256": digest(baseline_path),
    }
    return payload


def write_once(path: Path, text: str) -> None:
    require(path.parent.resolve(strict=True) == REVIEW.resolve(strict=True), "review output escaped owned review directory")
    require(not path.exists() and not path.is_symlink(), f"refusing to overwrite independent outcome artifact: {path.name}")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def main() -> None:
    # This gate is evaluated before any code below reads a parquet label column.
    fit_receipt, choice_receipt, outcome_receipt, published_report, fit_sha, choice_sha, choice_receipt_sha = validate_preoutcome_locks()
    choices = load_jsonl(CHOICES_PATH, "candidate_choices.jsonl")
    require(len(choices) == 1779 and len({str(row.get("race_id")) for row in choices}) == 1779, "choice race inventory changed")
    dates, date_hash = choices_date_hash(choices)
    schedule, schedule_path = bootstrap_schedule()
    baseline_path = source_path(BASELINE_REL, BASELINE_SHA256)

    # `y` is read only after root's approval has bound every upstream artifact.
    labels = pd.read_parquet(baseline_path, columns=OUTCOME_COLUMNS)
    metrics = independently_build_race_metrics(labels, choices)
    expected_report = build_expected_report(metrics, choices, dates, date_hash, schedule, schedule_path, baseline_path, fit_receipt, fit_sha, choice_sha, choice_receipt_sha)
    compare_json(expected_report, published_report, "outcomes")

    expected_race_rows = race_outcome_rows(metrics)
    published_race_rows = load_jsonl(RACE_OUTCOMES_PATH, "race_outcomes.jsonl")
    require(len(expected_race_rows) == len(published_race_rows) == 1779, "race outcome ledger row count changed")
    for index, (expected, published) in enumerate(zip(expected_race_rows, published_race_rows, strict=True), 1):
        compare_json(expected, published, f"race_outcomes[{index}]")

    outcome_hash_before = digest(OUTCOMES_PATH)
    race_hash_before = digest(RACE_OUTCOMES_PATH)
    require(outcome_hash_before == outcome_receipt.get("outcome_sha256"), "published aggregate outcome hash changed")
    require(race_hash_before == outcome_receipt.get("race_outcome_sha256"), "published race outcome hash changed")
    gate = expected_report["primary_success_gate"]["passed"]
    require(outcome_receipt.get("outcome_rows") == len(labels) == 17412, "outcome row count differs from receipt")
    require(outcome_receipt.get("outcome_races") == 1779 and outcome_receipt.get("primary_races") == 1503, "outcome cohort counts differ from receipt")
    require(outcome_receipt.get("primary_success_gate_passed") is bool(gate), "success gate differs from receipt")

    replay_race_path = REVIEW / "REPLAYED_LOCKED_RACE_OUTCOMES.jsonl"
    write_once(replay_race_path, "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n" for row in expected_race_rows))
    replay_report_path = REVIEW / "REPLAYED_OUTCOME_METRICS.json"
    write_once(replay_report_path, json.dumps(expected_report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    replay_receipt = {
        "status": "PASS",
        "review": "independent recomputation of the approved retrospective outcome report",
        "outcome_labels_read": True,
        "all_metrics_recomputed_independently": True,
        "plan_sha256": PLAN_SHA256,
        "source_audit_sha256": SOURCE_AUDIT_SHA256,
        "baseline_source_sha256": BASELINE_SHA256,
        "main_report_code_sha256": digest(REPORT_CODE_PATH),
        "fit_receipt_sha256": fit_sha,
        "choices_sha256": choice_sha,
        "choices_receipt_sha256": choice_receipt_sha,
        "outcome_approval_sha256": digest(OUTCOME_APPROVAL_PATH),
        "main_outcome_receipt_sha256": digest(OUTCOME_RECEIPT_PATH),
        "main_outcomes_sha256": outcome_hash_before,
        "main_race_outcomes_sha256": race_hash_before,
        "bootstrap_schedule_sha256": BOOTSTRAP_SHA256,
        "bootstrap_date_inventory_sha256": date_hash,
        "input_allowlist": OUTCOME_COLUMNS,
        "counts": {
            "outcome_runner_rows": len(labels),
            "full_races": len(metrics),
            "primary_races": int(metrics["primary_distance"].sum()),
            "primary_dates": len(dates),
            "race_rows_exactly_reproduced": len(expected_race_rows),
        },
        "recomputed_primary": expected_report["primary"],
        "recomputed_full": expected_report["full"],
        "recomputed_primary_date_bootstrap_95ci": expected_report["primary_date_bootstrap_95ci"],
        "primary_gate_passed": bool(gate),
        "independent_race_outcomes_sha256": digest(replay_race_path),
        "independent_metrics_sha256": digest(replay_report_path),
    }
    write_once(REVIEW / "REPLAYED_OUTCOME_RECEIPT.json", json.dumps(replay_receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": "PASS", "full_races": len(metrics), "primary_races": int(metrics["primary_distance"].sum()), "gate_passed": bool(gate)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

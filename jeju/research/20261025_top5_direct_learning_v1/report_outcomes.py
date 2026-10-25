"""Open evaluation outcomes only after a hash-bound root approval."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import fit_selector as fit
import select_sets as select


BOOTSTRAP_REL = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
BOOTSTRAP_RECEIPT_REL = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
BOOTSTRAP_RECEIPT_SHA256 = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"
DATE_INVENTORY_SHA256 = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
BOOTSTRAP_SEED = 20261011
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_DATES = 269
OUTCOME_APPROVAL = fit.OUT / "ROOT_OUTCOME_APPROVAL.json"
CHOICES_RECEIPT_PATH = fit.OUT / select.CHOICES_RECEIPT_NAME
CHOICES_PATH = fit.OUT / select.CHOICES_PATH_NAME
OUTCOME_FILE_NAME = "outcomes.json"
RACE_OUTCOME_FILE_NAME = "race_outcomes.jsonl"
OUTCOME_RECEIPT_NAME = "OUTCOME_RECEIPT.json"
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise fit.FitError(message)


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"required receipt missing or unsafe: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def choices_hash_and_receipt() -> tuple[dict[str, Any], str, str]:
    receipt = read_json(CHOICES_RECEIPT_PATH)
    require(receipt.get("status") == "PASS" and receipt.get("outcome_labels_read") is False, "choice receipt is not a label-free PASS")
    require(CHOICES_PATH.is_file() and not CHOICES_PATH.is_symlink(), "hash-locked choice artifact missing")
    actual_hash = fit.sha256(CHOICES_PATH)
    require(actual_hash == receipt.get("choices_sha256"), "choice file hash differs from receipt")
    return receipt, actual_hash, fit.sha256(CHOICES_RECEIPT_PATH)


def require_outcome_approval(choice_sha: str, choice_receipt_sha: str, fit_receipt_sha: str) -> tuple[dict[str, Any], str]:
    approval = read_json(OUTCOME_APPROVAL)
    require(approval.get("status") == "approved", "root outcome approval status is not approved")
    require(approval.get("plan_sha256") == fit.sha256(fit.PLAN_PATH), "outcome approval plan hash is stale")
    require(approval.get("source_audit_sha256") == fit.sha256(fit.SOURCE_AUDIT_PATH), "outcome approval source hash is stale")
    require(approval.get("choices_sha256") == choice_sha, "outcome approval references a different choice artifact")
    require(approval.get("choices_receipt_sha256") == choice_receipt_sha, "outcome approval references a different choice receipt")
    require(approval.get("fit_receipt_sha256") == fit_receipt_sha, "outcome approval references a different fit receipt")
    require(approval.get("outcome_code_sha256") == fit.sha256(Path(__file__).resolve()), "outcome approval code hash is stale")
    return approval, fit.sha256(OUTCOME_APPROVAL)


def load_choice_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with CHOICES_PATH.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise fit.FitError(f"invalid choice JSONL row {line_number}") from exc
            rows.append(item)
    require(len(rows) == 1779, f"unexpected choice row count: {len(rows)}")
    require(len({row.get("race_id") for row in rows}) == len(rows), "choice race IDs are not unique")
    return rows


def verify_choice_date_inventory(choices: list[dict[str, Any]]) -> str:
    dates = sorted({
        str(row["race_date"])
        for row in choices
        if int(float(row["distance_m"])) in select.PRIMARY_DISTANCES
    })
    require(len(dates) == BOOTSTRAP_DATES, "label-free choice date inventory does not match frozen schedule dimensions")
    digest = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(digest == DATE_INVENTORY_SHA256, "label-free choice date inventory differs from frozen bootstrap inventory")
    return digest


def load_bootstrap_schedule() -> np.ndarray:
    path = fit.source_path(BOOTSTRAP_REL, BOOTSTRAP_SHA256)
    receipt_path = fit.source_path(BOOTSTRAP_RECEIPT_REL, BOOTSTRAP_RECEIPT_SHA256)
    receipt = read_json(receipt_path)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "bootstrap schedule was not frozen before evaluation")
    require(receipt.get("seed") == BOOTSTRAP_SEED and receipt.get("draws") == BOOTSTRAP_DRAWS, "frozen bootstrap seed or draw count changed")
    require(receipt.get("dates_per_draw") == BOOTSTRAP_DATES, "frozen bootstrap date count changed")
    require(receipt.get("date_inventory_sha256") == DATE_INVENTORY_SHA256, "bootstrap receipt date inventory hash changed")
    require(receipt.get("schedule_sha256") == BOOTSTRAP_SHA256, "bootstrap receipt schedule hash changed")
    schedule = np.load(path, allow_pickle=False)
    require(schedule.shape == (BOOTSTRAP_DRAWS, BOOTSTRAP_DATES), "frozen bootstrap schedule shape changed")
    require(schedule.dtype == np.int32, "frozen bootstrap schedule dtype changed")
    require(bool(((schedule >= 0) & (schedule < BOOTSTRAP_DATES)).all()), "bootstrap schedule has invalid date indices")
    return schedule


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    n = int(len(frame))
    baseline_hits = int(frame["baseline_all_three_hit"].sum())
    selector_hits = int(frame["selector_all_three_hit"].sum())
    captured = frame["selector_captured_top3"].value_counts().reindex([0, 1, 2, 3], fill_value=0)
    return {
        "races": n,
        "baseline_all_three_hits": baseline_hits,
        "selector_all_three_hits": selector_hits,
        "baseline_all_three_rate": baseline_hits / n,
        "selector_all_three_rate": selector_hits / n,
        "selector_minus_baseline_rate": (selector_hits - baseline_hits) / n,
        "selector_minus_baseline_percentage_points": 100.0 * (selector_hits - baseline_hits) / n,
        "both_hit": int((frame["baseline_all_three_hit"] & frame["selector_all_three_hit"]).sum()),
        "baseline_only_lost": int((frame["baseline_all_three_hit"] & ~frame["selector_all_three_hit"]).sum()),
        "selector_only_caught": int((~frame["baseline_all_three_hit"] & frame["selector_all_three_hit"]).sum()),
        "both_miss": int((~frame["baseline_all_three_hit"] & ~frame["selector_all_three_hit"]).sum()),
        "selector_captured_top3_count_0_1_2_3": {str(k): int(captured.loc[k]) for k in [0, 1, 2, 3]},
        "baseline_captured_top3_count_0_1_2_3": {
            str(k): int(frame["baseline_captured_top3"].value_counts().get(k, 0)) for k in [0, 1, 2, 3]
        },
    }


def group_summary(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, group in frame.groupby(column, sort=True):
        summary = summarize(group)
        result[str(key)] = summary
    return result


def paired_date_bootstrap(primary: pd.DataFrame, schedule: np.ndarray, dates: list[str]) -> dict[str, Any]:
    by_date = primary.groupby("race_date", sort=True).agg(
        races=("race_id", "size"),
        selector_hits=("selector_all_three_hit", "sum"),
        baseline_hits=("baseline_all_three_hit", "sum"),
    )
    require(list(by_date.index.astype(str)) == dates, "primary date inventory differs from frozen bootstrap schedule")
    require(len(dates) == BOOTSTRAP_DATES and (by_date["races"] > 0).all(), "primary date count/coverage changed")
    date_counts = by_date["races"].to_numpy(dtype=np.int64)
    date_delta = (by_date["selector_hits"] - by_date["baseline_hits"]).to_numpy(dtype=np.int64)
    require(int(date_counts.sum()) == len(primary), "primary bootstrap race denominator mismatch")
    numerators = date_delta[schedule].sum(axis=1, dtype=np.int64)
    denominators = date_counts[schedule].sum(axis=1, dtype=np.int64)
    require((denominators > 0).all(), "bootstrap draw has no primary races")
    samples = numerators / denominators
    lower, upper = np.quantile(samples, [0.025, 0.975], method="linear")
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
        "valid_replicates": int(len(samples)),
        "replicates_with_zero_primary_races": int((denominators == 0).sum()),
    }


def construct_race_metrics(labels: pd.DataFrame, choices: list[dict[str, Any]]) -> pd.DataFrame:
    require(labels.columns.tolist() == OUTCOME_COLUMNS, "outcome-stage label allowlist/schema changed")
    require(len(labels) == 17412 and labels["api_record_id"].is_unique, "evaluation outcome rows or keys changed")
    require(set(labels["variant"].astype(str)) == {"F1_STYLE6"}, "outcome source includes another model variant")
    y = pd.to_numeric(labels["y"], errors="coerce")
    require(y.notna().all() and y.isin([0, 1]).all(), "outcome labels are not exact binary values")
    labels = labels.copy()
    labels["y"] = y.astype(int)
    by_race = {str(race_id): group for race_id, group in labels.groupby("race_id", sort=False)}
    choice_by_race = {str(row["race_id"]): row for row in choices}
    require(set(by_race) == set(choice_by_race), "choice and outcome race inventories differ")
    race_records: list[dict[str, Any]] = []
    for race_id in sorted(by_race):
        group = by_race[race_id].sort_values("horse_number", kind="stable")
        row = choice_by_race[race_id]
        require(len(group) == int(group["field_n"].iloc[0]), f"outcome roster incomplete: {race_id}")
        require(int(group["y"].sum()) == 3, f"race does not have exactly three Top3 labels: {race_id}")
        require(str(group["race_date"].iloc[0]) == str(row["race_date"]), f"choice/outcome race date mismatch: {race_id}")
        require(int(group["year"].iloc[0]) == int(row["year"]), f"choice/outcome year mismatch: {race_id}")
        require(float(group["distance_m"].iloc[0]) == float(row["distance_m"]), f"choice/outcome distance mismatch: {race_id}")
        require(int(group["field_n"].iloc[0]) == int(row["field_n"]), f"choice/outcome field size mismatch: {race_id}")
        actual = set(group.loc[group["y"].eq(1), "horse_id"].astype(str))
        baseline_ids = set(map(str, row["baseline_top5_horse_ids"]))
        selector_ids = set(map(str, row["selector_top5_horse_ids"]))
        require(len(baseline_ids) == len(selector_ids) == 5, f"selection is not exactly five unique horses: {race_id}")
        roster_ids = set(group["horse_id"].astype(str))
        require(baseline_ids <= roster_ids and selector_ids <= roster_ids, f"selection includes a non-starter: {race_id}")
        number_by_id = dict(zip(group["horse_id"].astype(str), group["horse_number"].astype(int), strict=True))
        require([number_by_id[horse_id] for horse_id in row["baseline_top5_horse_ids"]] == list(map(int, row["baseline_top5_horse_numbers"])), f"baseline selected ID/number mismatch: {race_id}")
        require([number_by_id[horse_id] for horse_id in row["selector_top5_horse_ids"]] == list(map(int, row["selector_top5_horse_numbers"])), f"selector selected ID/number mismatch: {race_id}")
        baseline_hit_count = len(actual & baseline_ids)
        selector_hit_count = len(actual & selector_ids)
        base_order = sorted(group.to_dict("records"), key=lambda item: (-float(item["score"]), int(item["horse_number"])))[:5]
        require(set(str(item["horse_id"]) for item in base_order) == baseline_ids, f"baseline Top5 does not reproduce frozen raw score rule: {race_id}")
        primary = int(float(group["distance_m"].iloc[0])) in select.PRIMARY_DISTANCES
        race_records.append({
            "race_id": race_id,
            "race_date": str(group["race_date"].iloc[0]),
            "year": int(group["year"].iloc[0]),
            "distance_m": float(group["distance_m"].iloc[0]),
            "primary_distance": primary,
            "baseline_all_three_hit": baseline_hit_count == 3,
            "selector_all_three_hit": selector_hit_count == 3,
            "baseline_captured_top3": baseline_hit_count,
            "selector_captured_top3": selector_hit_count,
        })
    result = pd.DataFrame(race_records)
    require(len(result) == 1779 and int(result["primary_distance"].sum()) == 1503, "fixed outcome cohort counts changed")
    return result


def main() -> None:
    choice_receipt, choices_sha, choice_receipt_sha = choices_hash_and_receipt()
    fit_receipt_path = fit.OUT / "FIT_RECEIPT.json"
    fit_receipt = read_json(fit_receipt_path)
    fit_receipt_sha = fit.sha256(fit_receipt_path)
    approval, approval_sha = require_outcome_approval(choices_sha, choice_receipt_sha, fit_receipt_sha)
    require(choice_receipt.get("selection_code_sha256") == fit.sha256(fit.CHOICE_CODE_PATH), "choice code differs from receipt")
    require(choice_receipt.get("fit_receipt_sha256") == fit_receipt_sha, "choices use a different fit receipt")
    require(choice_receipt.get("primary_races") == 1503 and choice_receipt.get("full_races") == 1779, "choice cohort counts changed")

    choices = load_choice_rows()
    choice_date_inventory_sha = verify_choice_date_inventory(choices)
    schedule_path = fit.source_path(BOOTSTRAP_REL, BOOTSTRAP_SHA256)
    schedule = load_bootstrap_schedule()
    baseline_path = fit.source_path(select.BASELINE_REL, select.BASELINE_SHA256)

    # Outcome labels are opened only after the choices, receipts, source hashes,
    # model hashes, code hashes, and root outcome approval have all been checked.
    labels = pd.read_parquet(baseline_path, columns=OUTCOME_COLUMNS)
    race_metrics = construct_race_metrics(labels, choices)
    primary = race_metrics.loc[race_metrics["primary_distance"]].copy()
    dates = sorted(primary["race_date"].unique().tolist())
    bootstrap = paired_date_bootstrap(primary, schedule, dates)
    primary_summary = summarize(primary)
    full_summary = summarize(race_metrics)
    gate_pass = primary_summary["selector_minus_baseline_rate"] > 0.0 and bootstrap["lower"] > 0.0

    outcome_payload = {
        "status": "RETROSPECTIVE_DEVELOPMENT_COMPARISON",
        "study": fit.STUDY.name,
        "objective_id": fit.OBJECTIVE_ID,
        "outcome": "all three actual Top3 horses are contained in the selected exact five-horse set",
        "probability_claim": "none; the Gibbs positive-set mass is a stochastic training surrogate and is not deterministic coverage probability or calibrated probability",
        "primary": primary_summary | {"distance_m": sorted(select.PRIMARY_DISTANCES)},
        "full": full_summary,
        "primary_date_bootstrap_95ci": bootstrap,
        "label_free_choice_date_inventory_sha256": choice_date_inventory_sha,
        "primary_success_gate": {
            "rule": "primary selector-minus-baseline all-three rate > 0 and date-bootstrap 95% CI lower bound > 0",
            "passed": bool(gate_pass),
        },
        "primary_by_year": group_summary(primary, "year"),
        "primary_by_distance": group_summary(primary, "distance_m"),
        "full_by_year": group_summary(race_metrics, "year"),
        "full_by_distance": group_summary(race_metrics, "distance_m"),
        "training_label_checks": {
            str(year): fit_receipt["folds"][str(year)]["training_label_validation"]
            for year in fit.EVAL_YEARS
        },
        "selection_changed_races": int(sum(
            set(row["baseline_top5_horse_ids"]) != set(row["selector_top5_horse_ids"])
            for row in choices
        )),
        "fit_receipt_sha256": fit_receipt_sha,
        "choices_sha256": choices_sha,
        "choices_receipt_sha256": choice_receipt_sha,
        "bootstrap_source_sha256": fit.sha256(schedule_path),
        "baseline_source_sha256": fit.sha256(baseline_path),
    }
    race_ledger_path = fit.output_path(RACE_OUTCOME_FILE_NAME)
    with race_ledger_path.open("x", encoding="utf-8") as stream:
        for row in race_metrics.sort_values(["race_date", "race_id"], kind="stable").to_dict("records"):
            record = {
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
            }
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    outcome_path = fit.output_path(OUTCOME_FILE_NAME)
    fit.write_json_once(outcome_path, outcome_payload)
    outcome_receipt = {
        "status": "PASS",
        "study": fit.STUDY.name,
        "outcome_labels_read": True,
        "outcome_rows": int(len(labels)),
        "outcome_races": int(len(race_metrics)),
        "primary_races": int(len(primary)),
        "primary_success_gate_passed": bool(gate_pass),
        "outcome_file": OUTCOME_FILE_NAME,
        "outcome_sha256": fit.sha256(outcome_path),
        "outcome_bytes": outcome_path.stat().st_size,
        "race_outcome_file": RACE_OUTCOME_FILE_NAME,
        "race_outcome_sha256": fit.sha256(race_ledger_path),
        "race_outcome_bytes": race_ledger_path.stat().st_size,
        "plan_sha256": fit.sha256(fit.PLAN_PATH),
        "source_audit_sha256": fit.sha256(fit.SOURCE_AUDIT_PATH),
        "fit_receipt_sha256": fit_receipt_sha,
        "choices_sha256": choices_sha,
        "choices_receipt_sha256": choice_receipt_sha,
        "outcome_code_sha256": fit.sha256(Path(__file__).resolve()),
        "root_outcome_approval_sha256": approval_sha,
        "bootstrap_schedule_sha256": BOOTSTRAP_SHA256,
        "date_inventory_sha256": DATE_INVENTORY_SHA256,
    }
    receipt_path = fit.output_path(OUTCOME_RECEIPT_NAME)
    fit.write_json_once(receipt_path, outcome_receipt)
    print(json.dumps({"status": "PASS", "primary": primary_summary, "gate_passed": bool(gate_pass)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

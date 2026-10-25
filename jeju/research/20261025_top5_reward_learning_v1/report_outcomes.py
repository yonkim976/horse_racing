"""Compare raw Top5, frozen partial-NLL Top5, and reward-head Top5 after approval."""

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

OLD_CHOICES_REL = "jeju/research/20261025_top5_direct_learning_v1/outputs/candidate_choices.jsonl"
OLD_CHOICES_SHA256 = "eacbea0404a41dd70872a9936a9547804579b3e41ca13386e84924ec06899545"
OLD_OUTCOMES_REL = "jeju/research/20261025_top5_direct_learning_v1/outputs/outcomes.json"
OLD_OUTCOMES_SHA256 = "669fcf5067c029ab1d0b3c4c00ce1dd1b8bbe9f0d03d43a4fc18c7aaf2c9888d"
REWARD_ROOT_AUDIT_REL = "jeju/research/20261025_top5_reward_learning_rootreview_v1/ROOT_SOURCE_AUDIT.json"
REWARD_ROOT_AUDIT_SHA256 = "f5b05298c758bd233917ba988f2e4e10660e49c0bfad4ee5dee932577d08e8e2"
BASELINE_REL = "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
BASELINE_SHA256 = "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1"

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
ARMS = ("raw", "partial_nll", "reward")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise fit.FitError(message)


def iso_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="raise")
    return parsed.strftime("%Y-%m-%d")


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"required receipt missing or unsafe: {path.name}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), f"JSON object expected: {path.name}")
    return payload


def load_choices(path: Path, expected_sha256: str, expected_n: int, description: str) -> tuple[list[dict[str, Any]], str]:
    safe = fit.source_path(str(path.relative_to(fit.ROOT)), expected_sha256) if path.is_relative_to(fit.ROOT) else path
    require(safe.is_file() and not safe.is_symlink(), f"{description} file missing or unsafe")
    actual_sha256 = fit.sha256(safe)
    require(actual_sha256 == expected_sha256, f"{description} hash changed")
    rows: list[dict[str, Any]] = []
    with safe.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise fit.FitError(f"invalid {description} JSONL row {line_number}") from exc
            require(isinstance(item, dict), f"invalid {description} row type: {line_number}")
            rows.append(item)
    require(len(rows) == expected_n, f"unexpected {description} row count: {len(rows)}")
    race_ids = [str(row.get("race_id")) for row in rows]
    require(len(set(race_ids)) == len(race_ids), f"{description} race IDs are not unique")
    return rows, actual_sha256


def choice_hashes_and_fit_receipt() -> tuple[dict[str, Any], str, str, dict[str, Any], str]:
    choices_receipt = read_json(CHOICES_RECEIPT_PATH)
    require(choices_receipt.get("status") == "PASS", "choice receipt is not PASS")
    require(choices_receipt.get("outcome_labels_read") is False, "choice stage reports evaluation labels read")
    reward_choices_sha = fit.sha256(CHOICES_PATH)
    require(reward_choices_sha == choices_receipt.get("choices_sha256"), "reward choice hash differs from receipt")
    fit_receipt_path = fit.OUT / "FIT_RECEIPT.json"
    fit_receipt = read_json(fit_receipt_path)
    fit_receipt_sha = fit.sha256(fit_receipt_path)
    require(fit_receipt.get("status") == "PASS" and fit_receipt.get("fit_count") == 3, "fit receipt is not a complete three-fold fit")
    require(fit_receipt.get("objective_id") == fit.OBJECTIVE_ID, "fit receipt objective changed")
    require(fit_receipt.get("plan_sha256") == fit.sha256(fit.PLAN_PATH), "fit receipt plan hash is stale")
    require(fit_receipt.get("source_audit_sha256") == fit.sha256(fit.SOURCE_AUDIT_PATH), "fit receipt source audit hash is stale")
    require(choices_receipt.get("fit_receipt_sha256") == fit_receipt_sha, "choices use a different fit receipt")
    return choices_receipt, reward_choices_sha, fit.sha256(CHOICES_RECEIPT_PATH), fit_receipt, fit_receipt_sha


def require_outcome_approval(
    choices_receipt: dict[str, Any],
    choices_sha: str,
    choices_receipt_sha: str,
    fit_receipt_sha: str,
) -> tuple[dict[str, Any], str]:
    approval = read_json(OUTCOME_APPROVAL)
    require(approval.get("status") == "approved", "root outcome approval status is not approved")
    require(approval.get("plan_sha256") == fit.sha256(fit.PLAN_PATH), "outcome approval plan hash is stale")
    require(approval.get("source_audit_sha256") == fit.sha256(fit.SOURCE_AUDIT_PATH), "outcome approval source hash is stale")
    require(approval.get("fit_receipt_sha256") == fit_receipt_sha, "outcome approval fit receipt hash is stale")
    require(approval.get("choices_sha256") == choices_sha, "outcome approval choices hash is stale")
    require(approval.get("choices_receipt_sha256") == choices_receipt_sha, "outcome approval choice receipt hash is stale")
    require(approval.get("selection_code_sha256") == choices_receipt.get("selection_code_sha256"), "outcome approval selection code hash is stale")
    require(approval.get("outcome_code_sha256") == fit.sha256(Path(__file__).resolve()), "outcome approval code hash is stale")
    require(approval.get("source_audit_root_sha256") == fit.ROOT_AUDIT_SHA256, "outcome approval references a different base source audit")
    return approval, fit.sha256(OUTCOME_APPROVAL)


def verify_prior_root_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    audit_path = fit.source_path(REWARD_ROOT_AUDIT_REL, REWARD_ROOT_AUDIT_SHA256)
    audit = read_json(audit_path)
    require(audit.get("passed") is True and audit.get("new_reward_eval_labels_read") is False, "reward root source audit failed")
    source_hashes = audit.get("source_hashes", {})
    require(source_hashes.get(OLD_CHOICES_REL) == OLD_CHOICES_SHA256, "old choice hash differs from root source audit")
    require(source_hashes.get(OLD_OUTCOMES_REL) == OLD_OUTCOMES_SHA256, "old outcomes hash differs from root source audit")
    old_outcomes_path = fit.source_path(OLD_OUTCOMES_REL, OLD_OUTCOMES_SHA256)
    old_outcomes = read_json(old_outcomes_path)
    require(old_outcomes.get("status") == "RETROSPECTIVE_DEVELOPMENT_COMPARISON", "old outcome summary status changed")
    require(old_outcomes.get("objective_id") == "partial_event_gibbs_nll_additive_selection_head_v1", "old outcome summary is from another objective")
    expected = {"primary": (439, 435), "full": (519, 520)}
    for cohort, (raw_hits, old_hits) in expected.items():
        row = old_outcomes.get(cohort, {})
        require(row.get("baseline_all_three_hits") == raw_hits, f"old raw hit count changed for {cohort}")
        require(row.get("selector_all_three_hits") == old_hits, f"old partial-NLL hit count changed for {cohort}")
    return audit, old_outcomes


def load_schedule() -> tuple[np.ndarray, str]:
    path = fit.source_path(BOOTSTRAP_REL, BOOTSTRAP_SHA256)
    receipt_path = fit.source_path(BOOTSTRAP_RECEIPT_REL, BOOTSTRAP_RECEIPT_SHA256)
    receipt = read_json(receipt_path)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "date bootstrap was not frozen before evaluation")
    require(receipt.get("seed") == BOOTSTRAP_SEED and receipt.get("draws") == BOOTSTRAP_DRAWS, "bootstrap seed/draw count changed")
    require(receipt.get("dates_per_draw") == BOOTSTRAP_DATES, "bootstrap date count changed")
    require(receipt.get("date_inventory_sha256") == DATE_INVENTORY_SHA256, "bootstrap date inventory changed")
    require(receipt.get("schedule_sha256") == BOOTSTRAP_SHA256, "bootstrap schedule hash changed")
    schedule = np.load(path, allow_pickle=False)
    require(schedule.shape == (BOOTSTRAP_DRAWS, BOOTSTRAP_DATES), "bootstrap schedule shape changed")
    require(schedule.dtype == np.int32, "bootstrap schedule dtype changed")
    require(bool(((schedule >= 0) & (schedule < BOOTSTRAP_DATES)).all()), "bootstrap schedule index is out of range")
    return schedule, fit.sha256(path)


def validate_choice_pair(current: list[dict[str, Any]], old: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    current_by_race = {str(row["race_id"]): row for row in current}
    old_by_race = {str(row["race_id"]): row for row in old}
    require(set(current_by_race) == set(old_by_race), "current and previous choice race inventories differ")
    return current_by_race, old_by_race


def make_race_ledger(
    labels: pd.DataFrame,
    current_choices: list[dict[str, Any]],
    old_choices: list[dict[str, Any]],
) -> pd.DataFrame:
    require(labels.columns.tolist() == OUTCOME_COLUMNS, "outcome label column allowlist/schema changed")
    require(len(labels) == 17412 and labels["api_record_id"].is_unique, "evaluation outcome runner count/key changed")
    require(set(labels["variant"].astype(str)) == {"F1_STYLE6"}, "evaluation cohort contains another model variant")
    require(labels["field_n"].notna().all() and labels["horse_id"].notna().all(), "evaluation roster metadata has NULL")
    y = pd.to_numeric(labels["y"], errors="coerce")
    require(y.notna().all() and y.isin([0, 1]).all(), "evaluation outcomes are not exact binary labels")
    data = labels.copy()
    data["y"] = y.astype(np.int8)
    current_by_race, old_by_race = validate_choice_pair(current_choices, old_choices)
    by_race = {str(key): group for key, group in data.groupby("race_id", sort=False)}
    require(set(by_race) == set(current_by_race), "choice and evaluation race inventories differ")
    records: list[dict[str, Any]] = []

    for race_id in sorted(by_race):
        group = by_race[race_id].sort_values("horse_number", kind="stable")
        reward_row = current_by_race[race_id]
        old_row = old_by_race[race_id]
        n = int(group["field_n"].iloc[0])
        require(len(group) == n and group["horse_id"].is_unique and group["horse_number"].is_unique, f"evaluation roster is incomplete or duplicated: {race_id}")
        require(group["race_date"].nunique() == group["year"].nunique() == group["distance_m"].nunique() == 1, f"race metadata varies within roster: {race_id}")
        require((group["field_n"].astype(int) == n).all(), f"field_n differs within race: {race_id}")
        require(int(group["y"].sum()) == 3, f"race does not have exactly three Top3 labels: {race_id}")
        for label, row in (("reward", reward_row), ("partial NLL", old_row)):
            require(iso_date(group["race_date"].iloc[0]) == iso_date(row["race_date"]), f"{label} race date mismatch: {race_id}")
            require(int(group["year"].iloc[0]) == int(row["year"]), f"{label} year mismatch: {race_id}")
            require(float(group["distance_m"].iloc[0]) == float(row["distance_m"]), f"{label} distance mismatch: {race_id}")
            require(n == int(row["field_n"]), f"{label} field size mismatch: {race_id}")

        actual = set(group.loc[group["y"].eq(1), "horse_id"].astype(str))
        roster_ids = set(group["horse_id"].astype(str))
        number_by_id = dict(zip(group["horse_id"].astype(str), group["horse_number"].astype(int), strict=True))
        selected = {
            "raw": (list(map(str, reward_row["baseline_top5_horse_ids"])), list(map(int, reward_row["baseline_top5_horse_numbers"]))),
            "partial_nll": (list(map(str, old_row["selector_top5_horse_ids"])), list(map(int, old_row["selector_top5_horse_numbers"]))),
            "reward": (list(map(str, reward_row["selector_top5_horse_ids"])), list(map(int, reward_row["selector_top5_horse_numbers"]))),
        }
        old_raw = (list(map(str, old_row["baseline_top5_horse_ids"])), list(map(int, old_row["baseline_top5_horse_numbers"])))
        require(set(old_raw[0]) == set(selected["raw"][0]) and set(old_raw[1]) == set(selected["raw"][1]), f"raw Top5 roster differs between frozen choice ledgers: {race_id}")
        for arm, (horse_ids, horse_numbers) in selected.items():
            require(len(horse_ids) == len(set(horse_ids)) == 5, f"{arm} choice is not exactly five unique horses: {race_id}")
            require(len(horse_numbers) == len(set(horse_numbers)) == 5, f"{arm} choice has duplicate horse numbers: {race_id}")
            require(set(horse_ids) <= roster_ids, f"{arm} choice contains a non-starter: {race_id}")
            require([number_by_id[horse_id] for horse_id in horse_ids] == horse_numbers, f"{arm} selected ID/number mismatch: {race_id}")

        scores = group["score"].to_numpy(dtype=np.float64)
        require(np.isfinite(scores).all(), f"evaluation raw score is nonfinite: {race_id}")
        raw_order = sorted(group.to_dict("records"), key=lambda item: (-float(item["score"]), int(item["horse_number"])))[:5]
        require(set(str(item["horse_id"]) for item in raw_order) == set(selected["raw"][0]), f"raw-score Top5 does not reproduce: {race_id}")
        captured = {arm: len(actual & set(ids)) for arm, (ids, _) in selected.items()}
        primary = int(float(group["distance_m"].iloc[0])) in select.PRIMARY_DISTANCES
        records.append({
            "race_id": race_id,
            "race_date": iso_date(group["race_date"].iloc[0]),
            "year": int(group["year"].iloc[0]),
            "distance_m": float(group["distance_m"].iloc[0]),
            "primary_distance": primary,
            "raw_all_three_hit": captured["raw"] == 3,
            "partial_nll_all_three_hit": captured["partial_nll"] == 3,
            "reward_all_three_hit": captured["reward"] == 3,
            "raw_captured_top3": captured["raw"],
            "partial_nll_captured_top3": captured["partial_nll"],
            "reward_captured_top3": captured["reward"],
            "reward_changed_vs_raw": set(selected["reward"][0]) != set(selected["raw"][0]),
            "reward_changed_vs_partial_nll": set(selected["reward"][0]) != set(selected["partial_nll"][0]),
        })

    result = pd.DataFrame(records)
    require(len(result) == 1779 and int(result["primary_distance"].sum()) == 1503, "fixed evaluation cohort counts changed")
    return result


def summarize_arm(frame: pd.DataFrame, arm: str) -> dict[str, Any]:
    hit = frame[f"{arm}_all_three_hit"].to_numpy(dtype=bool)
    captured = frame[f"{arm}_captured_top3"].to_numpy(dtype=np.int8)
    counts = {str(k): int(np.count_nonzero(captured == k)) for k in range(4)}
    return {
        "races": int(len(frame)),
        "all_three_hits": int(hit.sum()),
        "all_three_rate": float(hit.mean()),
        "captured_top3_count_0_1_2_3": counts,
        "mean_captured_top3": float(captured.mean()),
    }


def summarize_pair(frame: pd.DataFrame, reference: str, candidate: str) -> dict[str, Any]:
    ref_hit = frame[f"{reference}_all_three_hit"].to_numpy(dtype=bool)
    cand_hit = frame[f"{candidate}_all_three_hit"].to_numpy(dtype=bool)
    n = len(frame)
    ref_captured = frame[f"{reference}_captured_top3"].to_numpy(dtype=np.int8)
    cand_captured = frame[f"{candidate}_captured_top3"].to_numpy(dtype=np.int8)
    return {
        "reference": reference,
        "candidate": candidate,
        "races": n,
        "reference_all_three_hits": int(ref_hit.sum()),
        "candidate_all_three_hits": int(cand_hit.sum()),
        "reference_all_three_rate": float(ref_hit.mean()),
        "candidate_all_three_rate": float(cand_hit.mean()),
        "candidate_minus_reference_rate": float((cand_hit.sum() - ref_hit.sum()) / n),
        "candidate_minus_reference_percentage_points": float(100.0 * (cand_hit.sum() - ref_hit.sum()) / n),
        "both_hit": int((ref_hit & cand_hit).sum()),
        "reference_only_lost": int((ref_hit & ~cand_hit).sum()),
        "candidate_only_caught": int((~ref_hit & cand_hit).sum()),
        "both_miss": int((~ref_hit & ~cand_hit).sum()),
        "reference_captured_top3_count_0_1_2_3": {str(k): int(np.count_nonzero(ref_captured == k)) for k in range(4)},
        "candidate_captured_top3_count_0_1_2_3": {str(k): int(np.count_nonzero(cand_captured == k)) for k in range(4)},
    }


def verify_date_inventory(primary: pd.DataFrame) -> tuple[list[str], str]:
    dates = sorted(primary["race_date"].astype(str).unique().tolist())
    digest = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(len(dates) == BOOTSTRAP_DATES and digest == DATE_INVENTORY_SHA256, "primary date inventory differs from frozen schedule")
    return dates, digest


def paired_date_bootstrap(frame: pd.DataFrame, reference: str, candidate: str, schedule: np.ndarray, dates: list[str]) -> dict[str, Any]:
    per_date = frame.groupby("race_date", sort=True).agg(
        races=("race_id", "size"),
        candidate_hits=(f"{candidate}_all_three_hit", "sum"),
        reference_hits=(f"{reference}_all_three_hit", "sum"),
    )
    require(list(per_date.index.astype(str)) == dates, f"{reference}/{candidate} date coverage differs from frozen inventory")
    counts = per_date["races"].to_numpy(dtype=np.int64)
    deltas = (per_date["candidate_hits"] - per_date["reference_hits"]).to_numpy(dtype=np.int64)
    require(int(counts.sum()) == len(frame), "date bootstrap denominator mismatch")
    denominators = counts[schedule].sum(axis=1, dtype=np.int64)
    numerators = deltas[schedule].sum(axis=1, dtype=np.int64)
    require((denominators > 0).all(), "date bootstrap draw has zero races")
    samples = numerators / denominators
    lower, upper = np.quantile(samples, [0.025, 0.975], method="linear")
    return {
        "reference": reference,
        "candidate": candidate,
        "cluster": "race_date",
        "interval_level": 0.95,
        "seed": BOOTSTRAP_SEED,
        "draws": BOOTSTRAP_DRAWS,
        "date_count": BOOTSTRAP_DATES,
        "date_inventory_sha256": DATE_INVENTORY_SHA256,
        "schedule_sha256": BOOTSTRAP_SHA256,
        "quantile_method": "numpy.quantile(method='linear')",
        "lower": float(lower),
        "upper": float(upper),
        "replicates_with_zero_races": int(np.count_nonzero(denominators == 0)),
    }


def grouped_pair_summaries(frame: pd.DataFrame, column: str, pairs: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, group in frame.groupby(column, sort=True):
        output[str(key)] = {f"{candidate}_minus_{reference}": summarize_pair(group, reference, candidate) for reference, candidate in pairs}
    return output


def main() -> None:
    choices_receipt, reward_choices_sha, choices_receipt_sha, fit_receipt, fit_receipt_sha = choice_hashes_and_fit_receipt()
    require(choices_receipt.get("candidate_choices_created") == 1779, "reward choice count changed")
    require(choices_receipt.get("primary_races") == 1503 and choices_receipt.get("full_races") == 1779, "reward choice cohort changed")
    require(choices_receipt.get("objective_id") == fit.OBJECTIVE_ID, "reward choice receipt objective changed")
    outcome_approval, outcome_approval_sha = require_outcome_approval(
        choices_receipt, reward_choices_sha, choices_receipt_sha, fit_receipt_sha
    )

    # Evaluation labels and the earlier outcome summary are opened only after
    # the separate root approval has been checked against all locked artifacts.
    current_choices, _ = load_choices(CHOICES_PATH, reward_choices_sha, 1779, "reward choice")
    old_choices, old_choices_sha = load_choices(fit.ROOT / OLD_CHOICES_REL, OLD_CHOICES_SHA256, 1779, "partial-NLL choice")
    root_source_audit, old_outcomes = verify_prior_root_sources()
    old_primary = old_outcomes["primary"]
    old_full = old_outcomes["full"]
    schedule, schedule_sha = load_schedule()
    baseline_path = fit.source_path(BASELINE_REL, BASELINE_SHA256)
    labels = pd.read_parquet(baseline_path, columns=OUTCOME_COLUMNS)
    race_ledger = make_race_ledger(labels, current_choices, old_choices)

    primary = race_ledger.loc[race_ledger["primary_distance"]].copy()
    dates, date_inventory_sha = verify_date_inventory(primary)
    full_dates = sorted(race_ledger["race_date"].astype(str).unique().tolist())
    require(full_dates == dates, "full cohort and primary cohort date inventories differ")
    pairs = (("raw", "partial_nll"), ("raw", "reward"), ("partial_nll", "reward"))
    primary_pairs = {f"{candidate}_minus_{reference}": summarize_pair(primary, reference, candidate) for reference, candidate in pairs}
    full_pairs = {f"{candidate}_minus_{reference}": summarize_pair(race_ledger, reference, candidate) for reference, candidate in pairs}
    primary_bootstrap = {
        f"{candidate}_minus_{reference}": paired_date_bootstrap(primary, reference, candidate, schedule, dates)
        for reference, candidate in (("raw", "reward"), ("partial_nll", "reward"))
    }
    full_bootstrap = {
        f"{candidate}_minus_{reference}": paired_date_bootstrap(race_ledger, reference, candidate, schedule, dates)
        for reference, candidate in (("raw", "reward"), ("partial_nll", "reward"))
    }

    for cohort, summary, prior in (("primary", primary_pairs, old_primary), ("full", full_pairs, old_full)):
        require(summary["partial_nll_minus_raw"]["candidate_all_three_hits"] == prior["selector_all_three_hits"], f"recomputed old selector hit count changed: {cohort}")
        require(summary["partial_nll_minus_raw"]["reference_all_three_hits"] == prior["baseline_all_three_hits"], f"recomputed old raw hit count changed: {cohort}")

    reward_raw = primary_pairs["reward_minus_raw"]
    reward_old = primary_pairs["reward_minus_partial_nll"]
    success_gate = all(
        primary_pairs[key]["candidate_minus_reference_rate"] > 0.0 and primary_bootstrap[key]["lower"] > 0.0
        for key in ("reward_minus_raw", "reward_minus_partial_nll")
    )
    training_reward = {
        str(year): {
            "training_races": int(fit_receipt["folds"][str(year)]["training_races"]),
            "mean_stochastic_expected_reward": float(fit_receipt["folds"][str(year)]["model_payload"]["fit_diagnostics"]["mean_expected_stochastic_reward"]),
        }
        for year in fit.EVAL_YEARS
    }

    outcome_payload = {
        "status": "RETROSPECTIVE_DEVELOPMENT_THREE_ARM_COMPARISON",
        "study": fit.STUDY.name,
        "objective_id": fit.OBJECTIVE_ID,
        "outcome": "all three actual Top3 horses are contained in the selected exact five-horse set",
        "policy_interpretation": "pi(S|race) is a stochastic choice distribution using only pre-race features; Pgood and realized reward require the observed actual Top3 label. Neither is a calibrated probability, and neither equals deterministic argmax coverage.",
        "primary": {"distances_m": sorted(select.PRIMARY_DISTANCES), "arms": {arm: summarize_arm(primary, arm) for arm in ARMS}, "paired_comparisons": primary_pairs},
        "full_secondary": {"arms": {arm: summarize_arm(race_ledger, arm) for arm in ARMS}, "paired_comparisons": full_pairs},
        "primary_date_bootstrap_95ci": primary_bootstrap,
        "full_secondary_date_bootstrap_95ci": full_bootstrap,
        "primary_success_gate": {
            "rule": "reward minus raw and reward minus partial-NLL each have positive primary paired delta and date-bootstrap 95% lower bound > 0",
            "reward_minus_raw_passed": bool(reward_raw["candidate_minus_reference_rate"] > 0 and primary_bootstrap["reward_minus_raw"]["lower"] > 0),
            "reward_minus_partial_nll_passed": bool(reward_old["candidate_minus_reference_rate"] > 0 and primary_bootstrap["reward_minus_partial_nll"]["lower"] > 0),
            "passed": bool(success_gate),
        },
        "primary_by_year": grouped_pair_summaries(primary, "year", pairs),
        "primary_by_distance": grouped_pair_summaries(primary, "distance_m", pairs),
        "full_by_year": grouped_pair_summaries(race_ledger, "year", pairs),
        "full_by_distance": grouped_pair_summaries(race_ledger, "distance_m", pairs),
        "changed_set_counts": {
            "primary_reward_vs_raw": int(primary["reward_changed_vs_raw"].sum()),
            "full_reward_vs_raw": int(race_ledger["reward_changed_vs_raw"].sum()),
            "primary_reward_vs_partial_nll": int(primary["reward_changed_vs_partial_nll"].sum()),
            "full_reward_vs_partial_nll": int(race_ledger["reward_changed_vs_partial_nll"].sum()),
        },
        "fold_training_stochastic_reward_diagnostics": training_reward,
        "old_partial_nll_reference": {
            "choices_sha256": old_choices_sha,
            "outcomes_sha256": OLD_OUTCOMES_SHA256,
            "root_source_audit_sha256": REWARD_ROOT_AUDIT_SHA256,
            "recomputed_primary_hits": old_primary["selector_all_three_hits"],
            "recomputed_full_hits": old_full["selector_all_three_hits"],
        },
        "training_label_checks": {str(year): fit_receipt["folds"][str(year)]["training_label_validation"] for year in fit.EVAL_YEARS},
        "fit_receipt_sha256": fit_receipt_sha,
        "reward_choices_sha256": reward_choices_sha,
        "choices_receipt_sha256": choices_receipt_sha,
        "root_source_audit_sha256": fit.ROOT_AUDIT_SHA256,
        "baseline_source_sha256": BASELINE_SHA256,
        "bootstrap_schedule_sha256": schedule_sha,
        "date_inventory_sha256": date_inventory_sha,
    }

    ledger_path = fit.output_path(RACE_OUTCOME_FILE_NAME)
    with ledger_path.open("x", encoding="utf-8") as stream:
        for row in race_ledger.sort_values(["race_date", "race_id"], kind="stable").to_dict("records"):
            record = {
                "race_id": str(row["race_id"]),
                "race_date": str(row["race_date"]),
                "year": int(row["year"]),
                "distance_m": float(row["distance_m"]),
                "primary_distance": bool(row["primary_distance"]),
            }
            for arm in ARMS:
                record[f"{arm}_all_three_hit"] = bool(row[f"{arm}_all_three_hit"])
                record[f"{arm}_captured_top3"] = int(row[f"{arm}_captured_top3"])
            record["reward_only_caught_vs_raw"] = bool(row["reward_all_three_hit"] and not row["raw_all_three_hit"])
            record["raw_only_lost_vs_reward"] = bool(row["raw_all_three_hit"] and not row["reward_all_three_hit"])
            record["reward_only_caught_vs_partial_nll"] = bool(row["reward_all_three_hit"] and not row["partial_nll_all_three_hit"])
            record["partial_nll_only_lost_vs_reward"] = bool(row["partial_nll_all_three_hit"] and not row["reward_all_three_hit"])
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")

    outcome_path = fit.output_path(OUTCOME_FILE_NAME)
    fit.write_json_once(outcome_path, outcome_payload)
    outcome_receipt = {
        "status": "PASS",
        "study": fit.STUDY.name,
        "outcome_labels_read": True,
        "outcome_rows": int(len(labels)),
        "outcome_races": int(len(race_ledger)),
        "primary_races": int(len(primary)),
        "primary_success_gate_passed": bool(success_gate),
        "outcome_file": OUTCOME_FILE_NAME,
        "outcome_sha256": fit.sha256(outcome_path),
        "outcome_bytes": outcome_path.stat().st_size,
        "race_outcome_file": RACE_OUTCOME_FILE_NAME,
        "race_outcome_sha256": fit.sha256(ledger_path),
        "race_outcome_bytes": ledger_path.stat().st_size,
        "plan_sha256": fit.sha256(fit.PLAN_PATH),
        "source_audit_sha256": fit.sha256(fit.SOURCE_AUDIT_PATH),
        "fit_receipt_sha256": fit_receipt_sha,
        "reward_choices_sha256": reward_choices_sha,
        "choices_receipt_sha256": choices_receipt_sha,
        "selection_code_sha256": choices_receipt["selection_code_sha256"],
        "outcome_code_sha256": fit.sha256(Path(__file__).resolve()),
        "root_outcome_approval_sha256": outcome_approval_sha,
        "old_choices_sha256": old_choices_sha,
        "old_outcomes_sha256": OLD_OUTCOMES_SHA256,
        "old_root_source_audit_sha256": fit.sha256(fit.source_path(REWARD_ROOT_AUDIT_REL, REWARD_ROOT_AUDIT_SHA256)),
        "bootstrap_schedule_sha256": BOOTSTRAP_SHA256,
        "date_inventory_sha256": date_inventory_sha,
    }
    receipt_path = fit.output_path(OUTCOME_RECEIPT_NAME)
    fit.write_json_once(receipt_path, outcome_receipt)
    print(json.dumps({"status": "PASS", "primary_pairs": primary_pairs, "success_gate": bool(success_gate)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

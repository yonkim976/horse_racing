"""Independently replay approved three-arm Top5 outcomes and paired CIs.

The verifier checks the outcome approval before it reads the fixed `y`
allowlist. It does not import the main report code and writes only one compact
review receipt, not another runner/race outcome ledger.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261025_top5_reward_learning_v1"
OUT = STUDY / "outputs"
YEARS = (2024, 2025, 2026)
PRIMARY_DISTANCES = {900, 1000, 1110, 1200}
ARMS = ("raw", "partial_nll", "reward")
PAIRS = (("raw", "partial_nll"), ("raw", "reward"), ("partial_nll", "reward"))
PRIMARY_BOOT_PAIRS = (("raw", "reward"), ("partial_nll", "reward"))
BASELINE_REL = "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
BASELINE_SHA = "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1"
OLD_CHOICES_REL = "jeju/research/20261025_top5_direct_learning_v1/outputs/candidate_choices.jsonl"
OLD_CHOICES_SHA = "eacbea0404a41dd70872a9936a9547804579b3e41ca13386e84924ec06899545"
OLD_OUTCOMES_REL = "jeju/research/20261025_top5_direct_learning_v1/outputs/outcomes.json"
OLD_OUTCOMES_SHA = "669fcf5067c029ab1d0b3c4c00ce1dd1b8bbe9f0d03d43a4fc18c7aaf2c9888d"
ROOT_CHOICE_AUDIT_REL = "jeju/research/20261025_top5_reward_learning_rootreview_v1/ROOT_CHOICES_AUDIT.json"
ROOT_CHOICE_AUDIT_SHA = "661cc7af6a58f0816b840d15c82ed74a351c9da404b2a6c094c2c89302f89df9"
REWARD_ROOT_AUDIT_REL = "jeju/research/20261025_top5_reward_learning_rootreview_v1/ROOT_SOURCE_AUDIT.json"
REWARD_ROOT_AUDIT_SHA = "f5b05298c758bd233917ba988f2e4e10660e49c0bfad4ee5dee932577d08e8e2"
BOOTSTRAP_REL = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
BOOTSTRAP_RECEIPT_REL = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
BOOTSTRAP_RECEIPT_SHA = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"
DATE_INVENTORY_SHA = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
OUTCOME_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "distance_m", "horse_id",
    "horse_number", "field_n", "variant", "score", "y",
]
EXPECTED_PLAN_SHA = "97cb3059573fd8c8352139ab9921a541dec997cabdcef2e7dc02cc19cc39d0cf"
EXPECTED_SOURCE_AUDIT_SHA = "918f68b3d78b105e12e4e02502a024fb211ed19f75c7916203ff6db9b5459753"
EXPECTED_FIT_CODE_SHA = "043c669ad6f8d7a9d66bb5846002758385c3e0811e7e6720727b2e5c1e9b85dc"
EXPECTED_SELECTION_CODE_SHA = "332304c499615288b37d9bc485f45f926931dedaf35d8242a4823e14fc616d54"
EXPECTED_OUTCOME_CODE_SHA = "4c787aceb33afb8c926ad8c7a95d64d1f2a63011fa8d0a2072b992ef89c9311a"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fixed_source(rel: str, digest: str) -> Path:
    p = ROOT / rel
    if p.is_symlink() or not p.resolve(strict=True).is_relative_to(ROOT):
        raise ValueError(f"unsafe fixed source: {rel}")
    if sha(p) != digest:
        raise ValueError(f"source hash mismatch: {rel}")
    return p


def json_file(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"missing/unsafe JSON artifact: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path, expected_sha: str, expected_rows: int) -> list[dict[str, object]]:
    fixed_source(str(path.relative_to(ROOT)), expected_sha)
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, start=1):
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"invalid JSONL record: {line_no}")
            rows.append(row)
    if len(rows) != expected_rows or len({str(row.get("race_id")) for row in rows}) != expected_rows:
        raise ValueError("choice ledger row count or race key mismatch")
    return rows


def assert_approval_before_labels() -> tuple[dict[str, object], dict[str, object], dict[str, object], str]:
    # These are metadata and locked choice artifacts only. No outcome column is
    # materialized until every approval hash below is confirmed.
    approval_path = OUT / "ROOT_OUTCOME_APPROVAL.json"
    approval = json_file(approval_path)
    choice_receipt_path = OUT / "CHOICES_RECEIPT.json"
    choices_receipt = json_file(choice_receipt_path)
    fit_receipt_path = OUT / "FIT_RECEIPT.json"
    fit_receipt = json_file(fit_receipt_path)
    choice_path = OUT / "candidate_choices.jsonl"
    choices_sha = sha(choice_path)
    choices_receipt_sha = sha(choice_receipt_path)
    fit_receipt_sha = sha(fit_receipt_path)
    if approval.get("status") != "approved":
        raise ValueError("root outcome approval is not approved")
    if sha(STUDY / "PLAN.md") != EXPECTED_PLAN_SHA or approval.get("plan_sha256") != EXPECTED_PLAN_SHA:
        raise ValueError("outcome approval plan hash mismatch")
    if sha(STUDY / "SOURCE_AUDIT.md") != EXPECTED_SOURCE_AUDIT_SHA or approval.get("source_audit_sha256") != EXPECTED_SOURCE_AUDIT_SHA:
        raise ValueError("outcome approval source-audit hash mismatch")
    if approval.get("fit_receipt_sha256") != fit_receipt_sha or choices_receipt.get("fit_receipt_sha256") != fit_receipt_sha:
        raise ValueError("outcome approval fit receipt hash mismatch")
    if approval.get("choices_sha256") != choices_sha or choices_receipt.get("choices_sha256") != choices_sha:
        raise ValueError("outcome approval choices hash mismatch")
    if approval.get("choices_receipt_sha256") != choices_receipt_sha:
        raise ValueError("outcome approval choice receipt hash mismatch")
    if approval.get("selection_code_sha256") != EXPECTED_SELECTION_CODE_SHA or choices_receipt.get("selection_code_sha256") != EXPECTED_SELECTION_CODE_SHA or sha(STUDY / "select_sets.py") != EXPECTED_SELECTION_CODE_SHA:
        raise ValueError("outcome approval selection code hash mismatch")
    if approval.get("outcome_code_sha256") != EXPECTED_OUTCOME_CODE_SHA or sha(STUDY / "report_outcomes.py") != EXPECTED_OUTCOME_CODE_SHA:
        raise ValueError("outcome approval reporter code hash mismatch")
    if approval.get("source_audit_root_sha256") != "b263703aae9e7d5eca2bda394d4c20de67144bcaf78e959f5add9efffc8310f8":
        raise ValueError("outcome approval references another source audit")
    root_choice_audit = json_file(fixed_source(ROOT_CHOICE_AUDIT_REL, ROOT_CHOICE_AUDIT_SHA))
    if approval.get("root_choice_audit_sha256") != ROOT_CHOICE_AUDIT_SHA or root_choice_audit.get("choices_sha256") != choices_sha:
        raise ValueError("root choice audit is not bound to locked choice ledger")
    independent_choice_audit = ROOT / "jeju/research/20261025_top5_reward_learning_review_v1/INDEPENDENT_CHOICE_AUDIT.json"
    if approval.get("independent_choice_audit_sha256") != sha(independent_choice_audit):
        raise ValueError("outcome approval is not bound to independent choice audit")
    if approval.get("no_reselection_or_refitting_after_outcomes") is not True:
        raise ValueError("outcome approval lacks the no-reselection lock")
    if fit_receipt.get("fit_code_sha256") != EXPECTED_FIT_CODE_SHA or fit_receipt.get("evaluation_outcomes_read") is not False:
        raise ValueError("fit receipt objective/source/outcome boundary mismatch")
    if fit_receipt.get("status") != "PASS" or fit_receipt.get("objective_id") != "expected_top3_in_top5_reward_gibbs_additive_selection_head_v1":
        raise ValueError("fit receipt is not the expected completed reward model")
    if choices_receipt.get("outcome_labels_read") is not False:
        raise ValueError("choice receipt indicates evaluation labels were read")
    if choices_receipt.get("candidate_choices_created") != 1779 or choices_receipt.get("primary_races") != 1503 or choices_receipt.get("full_races") != 1779:
        raise ValueError("locked choice cohort mismatch")
    return approval, choices_receipt, fit_receipt, choices_sha


def choice_map(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(row["race_id"]): row for row in rows}


def build_ledger(labels: pd.DataFrame, current: list[dict[str, object]], old: list[dict[str, object]]) -> list[dict[str, object]]:
    if labels.columns.tolist() != OUTCOME_COLUMNS:
        raise ValueError("outcome allowlist changed")
    if len(labels) != 17412 or not labels.api_record_id.is_unique:
        raise ValueError("evaluation runner count/key mismatch")
    if set(labels.variant.astype(str)) != {"F1_STYLE6"}:
        raise ValueError("evaluation model variant changed")
    y = pd.to_numeric(labels.y, errors="coerce")
    if y.isna().any() or not y.isin([0, 1]).all():
        raise ValueError("outcomes are not exact binary labels")
    data = labels.copy()
    data["y"] = y.astype(np.int8)
    current_by_race, old_by_race = choice_map(current), choice_map(old)
    if set(current_by_race) != set(old_by_race):
        raise ValueError("new and prior head race sets differ")
    if len(current_by_race) != 1779:
        raise ValueError("new choice race count mismatch")
    record_by_race: dict[str, dict[str, object]] = {}
    for race_id, group in data.groupby("race_id", sort=False):
        race_id = str(race_id)
        if race_id not in current_by_race:
            raise ValueError(f"evaluation outcome race missing choice: {race_id}")
        group = group.sort_values("horse_number", kind="stable")
        row_new, row_old = current_by_race[race_id], old_by_race[race_id]
        n = int(group.field_n.iloc[0])
        if len(group) != n or group.horse_id.isna().any() or not group.horse_id.is_unique or not group.horse_number.is_unique:
            raise ValueError(f"incomplete/duplicate evaluation roster: {race_id}")
        if not (group.field_n.astype(int) == n).all() or int(group.y.sum()) != 3:
            raise ValueError(f"invalid field size or Top3 label count: {race_id}")
        if group.race_date.nunique() != 1 or group.year.nunique() != 1 or group.distance_m.nunique() != 1:
            raise ValueError(f"race metadata varies within race: {race_id}")
        race_date = pd.to_datetime(group.race_date.iloc[0], errors="raise").strftime("%Y-%m-%d")
        year = int(group.year.iloc[0])
        distance = float(group.distance_m.iloc[0])
        actual_ids = set(group.loc[group.y.eq(1), "horse_id"].astype(str))
        roster_ids = set(group.horse_id.astype(str))
        number_by_id = dict(zip(group.horse_id.astype(str), group.horse_number.astype(int), strict=True))
        raw_ids = list(map(str, row_new["baseline_top5_horse_ids"]))
        raw_numbers = list(map(int, row_new["baseline_top5_horse_numbers"]))
        partial_ids = list(map(str, row_old["selector_top5_horse_ids"]))
        partial_numbers = list(map(int, row_old["selector_top5_horse_numbers"]))
        reward_ids = list(map(str, row_new["selector_top5_horse_ids"]))
        reward_numbers = list(map(int, row_new["selector_top5_horse_numbers"]))
        old_raw_ids = list(map(str, row_old["baseline_top5_horse_ids"]))
        old_raw_numbers = list(map(int, row_old["baseline_top5_horse_numbers"]))
        if set(raw_ids) != set(old_raw_ids) or set(raw_numbers) != set(old_raw_numbers):
            raise ValueError(f"raw-score Top5 differs between frozen ledgers: {race_id}")
        raw_ranked = sorted(group.to_dict("records"), key=lambda item: (-float(item["score"]), int(item["horse_number"])))[:5]
        if set(str(row["horse_id"]) for row in raw_ranked) != set(raw_ids):
            raise ValueError(f"raw-score Top5 does not reproduce: {race_id}")
        chosen = {"raw": (raw_ids, raw_numbers), "partial_nll": (partial_ids, partial_numbers), "reward": (reward_ids, reward_numbers)}
        for arm, (ids, numbers) in chosen.items():
            if len(ids) != 5 or len(set(ids)) != 5 or len(numbers) != 5 or len(set(numbers)) != 5:
                raise ValueError(f"{arm} arm is not exactly five unique runners: {race_id}")
            if not set(ids) <= roster_ids:
                raise ValueError(f"{arm} arm contains a nonstarter: {race_id}")
            if [number_by_id[h] for h in ids] != numbers:
                raise ValueError(f"{arm} selected ID/number mismatch: {race_id}")
        for label, row in (("reward", row_new), ("partial_nll", row_old)):
            if pd.to_datetime(row["race_date"], errors="raise").strftime("%Y-%m-%d") != race_date or int(row["year"]) != year or float(row["distance_m"]) != distance or int(row["field_n"]) != n:
                raise ValueError(f"{label} choice metadata mismatch: {race_id}")
        captured = {arm: len(actual_ids & set(ids)) for arm, (ids, _) in chosen.items()}
        record_by_race[race_id] = {
            "race_id": race_id,
            "race_date": race_date,
            "year": year,
            "distance_m": distance,
            "primary_distance": int(distance) in PRIMARY_DISTANCES,
            "raw_all_three_hit": captured["raw"] == 3,
            "partial_nll_all_three_hit": captured["partial_nll"] == 3,
            "reward_all_three_hit": captured["reward"] == 3,
            "raw_captured_top3": captured["raw"],
            "partial_nll_captured_top3": captured["partial_nll"],
            "reward_captured_top3": captured["reward"],
            "reward_changed_vs_raw": set(raw_ids) != set(reward_ids),
            "reward_changed_vs_partial_nll": set(partial_ids) != set(reward_ids),
        }
    if set(record_by_race) != set(current_by_race):
        raise ValueError("choice and outcome race inventories differ")
    ledger = [record_by_race[r] for r in sorted(record_by_race)]
    if len(ledger) != 1779 or sum(bool(r["primary_distance"]) for r in ledger) != 1503:
        raise ValueError("fixed evaluation population changed")
    return ledger


def summarize_arm(frame: pd.DataFrame, arm: str) -> dict[str, object]:
    hits = frame[f"{arm}_all_three_hit"].to_numpy(dtype=bool)
    captured = frame[f"{arm}_captured_top3"].to_numpy(dtype=np.int8)
    return {
        "races": int(len(frame)),
        "all_three_hits": int(hits.sum()),
        "all_three_rate": float(hits.mean()),
        "captured_top3_count_0_1_2_3": {str(k): int(np.count_nonzero(captured == k)) for k in range(4)},
        "mean_captured_top3": float(captured.mean()),
    }


def summarize_pair(frame: pd.DataFrame, reference: str, candidate: str) -> dict[str, object]:
    ref_hit = frame[f"{reference}_all_three_hit"].to_numpy(dtype=bool)
    cand_hit = frame[f"{candidate}_all_three_hit"].to_numpy(dtype=bool)
    ref_captured = frame[f"{reference}_captured_top3"].to_numpy(dtype=np.int8)
    cand_captured = frame[f"{candidate}_captured_top3"].to_numpy(dtype=np.int8)
    n = len(frame)
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


def paired_bootstrap(frame: pd.DataFrame, reference: str, candidate: str, schedule: np.ndarray, dates: list[str]) -> dict[str, object]:
    per_date = frame.groupby("race_date", sort=True).agg(
        races=("race_id", "size"),
        candidate_hits=(f"{candidate}_all_three_hit", "sum"),
        reference_hits=(f"{reference}_all_three_hit", "sum"),
    )
    if list(per_date.index.astype(str)) != dates:
        raise ValueError("date bootstrap inventory/order mismatch")
    counts = per_date.races.to_numpy(dtype=np.int64)
    deltas = (per_date.candidate_hits - per_date.reference_hits).to_numpy(dtype=np.int64)
    if int(counts.sum()) != len(frame):
        raise ValueError("bootstrap race denominator mismatch")
    denominators = counts[schedule].sum(axis=1, dtype=np.int64)
    numerators = deltas[schedule].sum(axis=1, dtype=np.int64)
    if not (denominators > 0).all():
        raise ValueError("bootstrap draw has zero races")
    samples = numerators / denominators
    lower, upper = np.quantile(samples, [0.025, 0.975], method="linear")
    return {
        "reference": reference,
        "candidate": candidate,
        "cluster": "race_date",
        "interval_level": 0.95,
        "seed": 20261011,
        "draws": 2000,
        "date_count": 269,
        "date_inventory_sha256": DATE_INVENTORY_SHA,
        "schedule_sha256": BOOTSTRAP_SHA,
        "quantile_method": "numpy.quantile(method='linear')",
        "lower": float(lower),
        "upper": float(upper),
        "replicates_with_zero_races": int(np.count_nonzero(denominators == 0)),
    }


def subgroup_summaries(frame: pd.DataFrame, column: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, group in frame.groupby(column, sort=True):
        out[str(key)] = {
            f"{candidate}_minus_{reference}": summarize_pair(group, reference, candidate)
            for reference, candidate in PAIRS
        }
    return out


def close_equal(actual: object, expected: object, tolerance: float = 1e-12) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(actual) == set(expected) and all(close_equal(actual[k], v, tolerance) for k, v in expected.items())
    if isinstance(expected, (list, tuple)):
        return isinstance(actual, (list, tuple)) and len(actual) == len(expected) and all(close_equal(a, b, tolerance) for a, b in zip(actual, expected, strict=True))
    if isinstance(expected, (bool, np.bool_)):
        return isinstance(actual, (bool, np.bool_)) and bool(actual) == bool(expected)
    if isinstance(expected, (int, np.integer)):
        return isinstance(actual, (int, np.integer)) and int(actual) == int(expected)
    if isinstance(expected, (float, np.floating)):
        return isinstance(actual, (int, float, np.integer, np.floating)) and abs(float(actual) - float(expected)) <= tolerance
    return actual == expected


def run() -> dict[str, object]:
    approval, choices_receipt, fit_receipt, choices_sha = assert_approval_before_labels()

    # Approval is checked before either the old outcome summary or evaluation y
    # is opened. The choice ledgers are frozen and outcome-free.
    current = read_jsonl(OUT / "candidate_choices.jsonl", choices_sha, 1779)
    old = read_jsonl(ROOT / OLD_CHOICES_REL, OLD_CHOICES_SHA, 1779)
    old_outcomes_path = fixed_source(OLD_OUTCOMES_REL, OLD_OUTCOMES_SHA)
    old_outcomes = json_file(old_outcomes_path)
    expected_old = {"primary": (439, 435), "full": (519, 520)}
    for cohort, (raw_hits, old_hits) in expected_old.items():
        row = old_outcomes.get(cohort, {})
        if row.get("baseline_all_three_hits") != raw_hits or row.get("selector_all_three_hits") != old_hits:
            raise ValueError(f"frozen prior outcome summary changed: {cohort}")
    root_audit = json_file(fixed_source(REWARD_ROOT_AUDIT_REL, REWARD_ROOT_AUDIT_SHA))
    if root_audit.get("passed") is not True or root_audit.get("new_reward_eval_labels_read") is not False:
        raise ValueError("root outcome source audit status changed")
    if root_audit.get("source_hashes", {}).get(OLD_OUTCOMES_REL) != OLD_OUTCOMES_SHA:
        raise ValueError("old outcome source hash not represented in root audit")

    schedule_path = fixed_source(BOOTSTRAP_REL, BOOTSTRAP_SHA)
    schedule_receipt_path = fixed_source(BOOTSTRAP_RECEIPT_REL, BOOTSTRAP_RECEIPT_SHA)
    schedule_meta = json_file(schedule_receipt_path)
    if schedule_meta.get("status") != "FROZEN_BEFORE_EVALUATION_METRICS" or schedule_meta.get("seed") != 20261011 or schedule_meta.get("draws") != 2000 or schedule_meta.get("dates_per_draw") != 269 or schedule_meta.get("date_inventory_sha256") != DATE_INVENTORY_SHA or schedule_meta.get("schedule_sha256") != BOOTSTRAP_SHA:
        raise ValueError("frozen date bootstrap receipt mismatch")
    schedule = np.load(schedule_path, allow_pickle=False)
    if schedule.shape != (2000, 269) or schedule.dtype != np.int32 or not bool(((schedule >= 0) & (schedule < 269)).all()):
        raise ValueError("frozen date bootstrap schedule shape/dtype/range mismatch")

    # Evaluation labels are first materialized here, after approval validation.
    baseline_path = fixed_source(BASELINE_REL, BASELINE_SHA)
    labels = pd.read_parquet(baseline_path, columns=OUTCOME_COLUMNS)
    ledger_rows = build_ledger(labels, current, old)
    frame = pd.DataFrame(ledger_rows)
    primary = frame.loc[frame.primary_distance].copy()
    dates = sorted(primary.race_date.astype(str).unique().tolist())
    date_sha = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    if len(dates) != 269 or date_sha != DATE_INVENTORY_SHA:
        raise ValueError("primary race-date inventory differs from fixed bootstrap")
    full_dates = sorted(frame.race_date.astype(str).unique().tolist())
    if full_dates != dates:
        raise ValueError("full and primary date inventories differ")

    primary_arms = {arm: summarize_arm(primary, arm) for arm in ARMS}
    full_arms = {arm: summarize_arm(frame, arm) for arm in ARMS}
    primary_pairs = {f"{cand}_minus_{ref}": summarize_pair(primary, ref, cand) for ref, cand in PAIRS}
    full_pairs = {f"{cand}_minus_{ref}": summarize_pair(frame, ref, cand) for ref, cand in PAIRS}
    primary_ci = {f"{cand}_minus_{ref}": paired_bootstrap(primary, ref, cand, schedule, dates) for ref, cand in PRIMARY_BOOT_PAIRS}
    full_ci = {f"{cand}_minus_{ref}": paired_bootstrap(frame, ref, cand, schedule, dates) for ref, cand in PRIMARY_BOOT_PAIRS}
    primary_by_year = subgroup_summaries(primary, "year")
    primary_by_distance = subgroup_summaries(primary, "distance_m")
    full_by_year = subgroup_summaries(frame, "year")
    full_by_distance = subgroup_summaries(frame, "distance_m")
    changed_set_counts = {
        "primary_reward_vs_raw": int(primary.reward_changed_vs_raw.sum()),
        "full_reward_vs_raw": int(frame.reward_changed_vs_raw.sum()),
        "primary_reward_vs_partial_nll": int(primary.reward_changed_vs_partial_nll.sum()),
        "full_reward_vs_partial_nll": int(frame.reward_changed_vs_partial_nll.sum()),
    }

    main_outcomes_path = OUT / "outcomes.json"
    race_outcomes_path = OUT / "race_outcomes.jsonl"
    receipt_path = OUT / "OUTCOME_RECEIPT.json"
    main_summary = json_file(main_outcomes_path)
    main_race_rows = read_jsonl(race_outcomes_path, sha(race_outcomes_path), 1779)
    main_receipt = json_file(receipt_path)
    if main_receipt.get("outcome_sha256") != sha(main_outcomes_path) or main_receipt.get("race_outcome_sha256") != sha(race_outcomes_path):
        raise ValueError("main outcome artifact hashes differ from receipt")
    if main_receipt.get("outcome_code_sha256") != EXPECTED_OUTCOME_CODE_SHA or main_receipt.get("root_outcome_approval_sha256") != sha(OUT / "ROOT_OUTCOME_APPROVAL.json"):
        raise ValueError("main outcome receipt code/approval hash mismatch")
    if main_receipt.get("reward_choices_sha256") != choices_sha or main_receipt.get("choices_receipt_sha256") != sha(OUT / "CHOICES_RECEIPT.json"):
        raise ValueError("main outcome receipt choice hashes mismatch")
    if main_receipt.get("outcome_rows") != 17412 or main_receipt.get("outcome_races") != 1779 or main_receipt.get("primary_races") != 1503:
        raise ValueError("main outcome receipt population mismatch")

    checks: dict[str, bool] = {}
    checks["primary_arms"] = close_equal(main_summary["primary"]["arms"], primary_arms)
    checks["full_arms"] = close_equal(main_summary["full_secondary"]["arms"], full_arms)
    checks["primary_paired_comparisons"] = close_equal(main_summary["primary"]["paired_comparisons"], primary_pairs)
    checks["full_paired_comparisons"] = close_equal(main_summary["full_secondary"]["paired_comparisons"], full_pairs)
    checks["primary_date_bootstrap"] = close_equal(main_summary["primary_date_bootstrap_95ci"], primary_ci)
    checks["full_date_bootstrap"] = close_equal(main_summary["full_secondary_date_bootstrap_95ci"], full_ci)
    checks["primary_by_year"] = close_equal(main_summary["primary_by_year"], primary_by_year)
    checks["primary_by_distance"] = close_equal(main_summary["primary_by_distance"], primary_by_distance)
    checks["full_by_year"] = close_equal(main_summary["full_by_year"], full_by_year)
    checks["full_by_distance"] = close_equal(main_summary["full_by_distance"], full_by_distance)
    checks["changed_set_counts"] = close_equal(main_summary["changed_set_counts"], changed_set_counts)
    success_gate = all(
        primary_pairs[key]["candidate_minus_reference_rate"] > 0.0 and primary_ci[key]["lower"] > 0.0
        for key in ("reward_minus_raw", "reward_minus_partial_nll")
    )
    checks["primary_success_gate"] = (
        bool(main_summary["primary_success_gate"]["passed"]) == bool(success_gate)
        and bool(main_receipt["primary_success_gate_passed"]) == bool(success_gate)
        and bool(main_summary["primary_success_gate"]["reward_minus_raw_passed"]) == bool(primary_pairs["reward_minus_raw"]["candidate_minus_reference_rate"] > 0 and primary_ci["reward_minus_raw"]["lower"] > 0)
        and bool(main_summary["primary_success_gate"]["reward_minus_partial_nll_passed"]) == bool(primary_pairs["reward_minus_partial_nll"]["candidate_minus_reference_rate"] > 0 and primary_ci["reward_minus_partial_nll"]["lower"] > 0)
    )

    expected_race_rows: dict[str, dict[str, object]] = {}
    for row in ledger_rows:
        out = {
            "race_id": str(row["race_id"]),
            "race_date": str(row["race_date"]),
            "year": int(row["year"]),
            "distance_m": float(row["distance_m"]),
            "primary_distance": bool(row["primary_distance"]),
        }
        for arm in ARMS:
            out[f"{arm}_all_three_hit"] = bool(row[f"{arm}_all_three_hit"])
            out[f"{arm}_captured_top3"] = int(row[f"{arm}_captured_top3"])
        out["reward_only_caught_vs_raw"] = bool(row["reward_all_three_hit"] and not row["raw_all_three_hit"])
        out["raw_only_lost_vs_reward"] = bool(row["raw_all_three_hit"] and not row["reward_all_three_hit"])
        out["reward_only_caught_vs_partial_nll"] = bool(row["reward_all_three_hit"] and not row["partial_nll_all_three_hit"])
        out["partial_nll_only_lost_vs_reward"] = bool(row["partial_nll_all_three_hit"] and not row["reward_all_three_hit"])
        expected_race_rows[str(row["race_id"])] = out
    if set(expected_race_rows) != {str(row["race_id"]) for row in main_race_rows}:
        checks["race_outcome_inventory"] = False
    else:
        checks["race_outcome_ledger"] = all(close_equal(main_race_rows[i], expected_race_rows[str(main_race_rows[i]["race_id"])]) for i in range(len(main_race_rows)))
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise ValueError(f"main outcomes do not match independent recomputation: {failed}")

    return {
        "status": "PASS",
        "outcome_code_sha256": EXPECTED_OUTCOME_CODE_SHA,
        "selection_code_sha256": EXPECTED_SELECTION_CODE_SHA,
        "outcome_approval_sha256": sha(OUT / "ROOT_OUTCOME_APPROVAL.json"),
        "outcome_receipt_sha256": sha(receipt_path),
        "outcome_file_sha256": sha(main_outcomes_path),
        "race_outcome_file_sha256": sha(race_outcomes_path),
        "reward_choice_sha256": choices_sha,
        "choice_receipt_sha256": sha(OUT / "CHOICES_RECEIPT.json"),
        "baseline_source_sha256": BASELINE_SHA,
        "old_choices_sha256": OLD_CHOICES_SHA,
        "old_outcomes_sha256": OLD_OUTCOMES_SHA,
        "bootstrap_schedule_sha256": BOOTSTRAP_SHA,
        "date_inventory_sha256": date_sha,
        "outcome_rows": int(len(labels)),
        "races_recomputed": int(len(frame)),
        "primary_races": int(len(primary)),
        "primary_arms": primary_arms,
        "full_arms": full_arms,
        "primary_paired_comparisons": primary_pairs,
        "full_paired_comparisons": full_pairs,
        "primary_by_year": primary_by_year,
        "primary_by_distance_m": primary_by_distance,
        "full_by_year": full_by_year,
        "full_by_distance_m": full_by_distance,
        "primary_date_bootstrap_95ci": primary_ci,
        "full_secondary_date_bootstrap_95ci": full_ci,
        "primary_success_gate_passed": bool(success_gate),
        "changed_set_counts": changed_set_counts,
        "independent_checks": checks,
        "evaluation_labels_read_only_after_approval": True,
        "evaluation_labels_used_for_training_or_choice": False,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, indent=2))

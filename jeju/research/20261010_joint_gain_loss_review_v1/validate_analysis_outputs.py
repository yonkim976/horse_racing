"""Independent no-fit checks for the saved joint gain/loss analysis outputs.

This reviewer script reads fixed source artifacts and A's outputs. It imports
only deterministic reconstruction functions from the earlier independent C
validation module; it never imports analysis A or runs fitting/optimization.
All writes are confined to this review directory.
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from hashlib import sha256

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
REVIEW = ROOT / "jeju/research/20261010_joint_gain_loss_review_v1"
OUT = REVIEW / "outputs"
A = ROOT / "jeju/research/20261010_joint_gain_loss_v1"
A_OUT = A / "outputs"
SOURCE = ROOT / "jeju/research/20261010_joint_relationship_v1/outputs"
CONTRACT = A / "INPUT_CONTRACT.json"
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261008
TIE_TOL = 1e-12


def digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def need(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def close(left, right, label: str, atol: float = 1e-10, rtol: float = 1e-10) -> float:
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    need(a.shape == b.shape and np.allclose(a, b, atol=atol, rtol=rtol, equal_nan=True),
         f"{label}: shape={a.shape}/{b.shape}, maxdiff="
         f"{float(np.nanmax(np.abs(a-b))) if a.shape == b.shape and a.size else 'n/a'}")
    return float(np.nanmax(np.abs(a - b))) if a.size else 0.0


def load_independent_module():
    path = ROOT / "jeju/research/20261010_joint_relationship_review_v1/postfit_independent_validation.py"
    spec = importlib.util.spec_from_file_location("frozen_independent_postfit_validation", path)
    need(spec is not None and spec.loader is not None, "cannot load frozen independent math module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def independent_bootstrap(frame: pd.DataFrame) -> tuple[float, float]:
    by_date = [part.delta_hit6.to_numpy(float)
               for _, part in frame.groupby("race_date", sort=True, observed=True)]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    days = len(by_date)
    draws = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        chosen = rng.integers(0, days, size=days)
        total = 0.0
        rows = 0
        for index in chosen:
            values = by_date[int(index)]
            total += float(values.sum())
            rows += len(values)
        draws[draw] = total / rows
    low, high = np.quantile(draws, [0.025, 0.975], method="linear")
    return float(low), float(high)


def main() -> int:
    c = load_independent_module()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    receipt = json.loads((A_OUT / "analysis_receipt.json").read_text(encoding="utf-8"))
    source_hashes = {}
    for item in contract["input_files"]:
        path = ROOT / item["path"]
        actual = digest(path)
        need(actual == item["sha256"], f"frozen source hash mismatch: {item['path']}")
        source_hashes[item["path"]] = actual
    need(receipt["input_hashes_verified"] == source_hashes,
         "A receipt input hashes do not equal independently checked input hashes")

    outputs = receipt["output_files"]
    for name, record in outputs.items():
        path = A_OUT / name
        need(path.is_file() and digest(path) == record["sha256"], f"A output hash mismatch: {name}")

    metrics = pd.read_csv(SOURCE / "report/race_metrics.csv")
    runners = pd.read_csv(SOURCE / "report/runner_marginals.csv")
    triples = pd.read_parquet(SOURCE / "report/all_triples.parquet")
    ledger = pd.read_csv(A_OUT / "race_ledger_1779.csv")
    discordant = pd.read_csv(A_OUT / "gain_loss_84.csv")
    boundary = pd.read_csv(A_OUT / "true_set_boundary_competitor_1779.csv")
    beta_rows = pd.read_csv(A_OUT / "true_set_beta_contributions.csv")
    term_summary = pd.read_csv(A_OUT / "beta_decomposition_by_outcome.csv")
    group_summary = pd.read_csv(A_OUT / "beta_group_decomposition_by_outcome.csv")
    ticket_changes = pd.read_csv(A_OUT / "selected_ticket_changes.csv")
    mechanical = pd.read_csv(A_OUT / "mechanical_cases.csv")
    selection_boundary = pd.read_csv(A_OUT / "selection_boundary_detail_1779.csv")

    need(len(metrics) == 1779 and metrics.race_id.is_unique, "source race coverage invalid")
    need(len(runners) == 17412 and not runners.api_record_id.duplicated().any(),
         "source runner key coverage invalid")
    need(len(ledger) == 1779 and ledger.race_id.is_unique, "ledger is not one row per race")
    need(set(ledger.race_id) == set(metrics.race_id), "ledger race key coverage differs")
    need(len(discordant) == 84 and discordant.race_id.is_unique,
         "discordant ledger is not exactly 84 unique races")
    need(set(discordant.race_id) == set(ledger.loc[ledger.hit_class.isin(["gained", "lost"]), "race_id"]),
         "discordant case keys differ from full ledger")
    need(len(boundary) == 1779 and boundary.race_id.is_unique, "U ledger is not one row per race")
    need(len(selection_boundary) == 1779 and selection_boundary.race_id.is_unique,
         "rank-six/seven boundary ledger is not one row per race")

    labels = runners.assign(actual_top3=pd.to_numeric(runners.y_top3, errors="raise").eq(1))
    actual_top = (labels.loc[labels.actual_top3].groupby("race_id", sort=False)
                  .horse_number.apply(lambda s: ",".join(map(str, sorted(map(int, s)))))
                  .rename("actual_true_set_ticket"))
    need((labels.groupby("race_id").actual_top3.sum() == 3).all(),
         "source actual true set is not exactly three runners per race")
    src = metrics.set_index("race_id")
    led = ledger.set_index("race_id")
    need((led.baseline_hit6.astype(int) == src.baseline_hit6.astype(int)).all(),
         "baseline hit6 changed between source and A ledger")
    need((led.candidate_hit6.astype(int) == src.candidate_hit6.astype(int)).all(),
         "candidate hit6 changed between source and A ledger")
    need((led.delta_hit6.astype(int) ==
          (src.candidate_hit6.astype(int) - src.baseline_hit6.astype(int))).all(),
         "A delta_hit6 differs from paired source outcomes")
    need((led.actual_true_set_ticket == actual_top.reindex(led.index)).all(),
         "A true-set ticket differs from raw runner labels")
    expected_class = np.select(
        [led.baseline_hit6.eq(1) & led.candidate_hit6.eq(1),
         led.baseline_hit6.eq(0) & led.candidate_hit6.eq(1),
         led.baseline_hit6.eq(1) & led.candidate_hit6.eq(0)],
        ["both_hit", "gained", "lost"], default="both_miss")
    need(np.array_equal(led.hit_class.astype(str).to_numpy(), expected_class),
         "hit class is not the source-defined four-way partition")

    counts = ledger.hit_class.value_counts().to_dict()
    need(counts == {"both_miss": 1322, "both_hit": 373, "gained": 50, "lost": 34},
         f"outcome counts changed: {counts}")
    need(int(ledger.selected_ticket_set_changed.sum()) == 1077 and
         int((~ledger.selected_ticket_set_changed).sum()) == 702,
         "ticket-set change counts differ")
    need(len(ticket_changes) == 2830 and
         ticket_changes.groupby("side").size().to_dict() ==
         {"entered_candidate": 1415, "exited_baseline": 1415},
         "entered/exited ticket rows or arm counts differ")
    need(not ticket_changes.duplicated(["race_id", "side", "ticket"]).any(),
         "ticket-change table contains duplicate race/side/ticket rows")
    for race_id, frame in ticket_changes.groupby("race_id", sort=False):
        n_enter = int(frame.side.eq("entered_candidate").sum())
        n_exit = int(frame.side.eq("exited_baseline").sum())
        need(n_enter == n_exit, f"ticket entry/exit counts do not balance: {race_id}")
        need(bool(led.loc[str(race_id), "selected_ticket_set_changed"]) == (n_enter > 0),
             f"ticket-change rows disagree with set-change flag: {race_id}")

    # Verify the published single-factor table and its date-cluster intervals.
    conditions = pd.read_csv(A_OUT / "condition_summary.csv")
    need(not conditions.duplicated(["factor", "condition"]).any(),
         "condition table has duplicate rows")
    wanted: dict[tuple[str, str], pd.DataFrame] = {("all", "all_1779"): ledger.copy()}
    for factor, column in [("year", "evaluation_year"), ("month", "calendar_month"),
                           ("distance_m", "distance_m"), ("grade_raw", "grade_condition"),
                           ("field_size_bin", "field_size_bin")]:
        for value, frame in ledger.groupby(column, sort=True, dropna=False, observed=True):
            label = "__MISSING__" if pd.isna(value) else str(value)
            wanted[(factor, label)] = frame
    need(set(zip(conditions.factor.astype(str), conditions.condition.astype(str))) == set(wanted),
         "condition inventory differs from the complete single-factor subgroup sets")
    max_ci_diff = 0.0
    for row in conditions.itertuples(index=False):
        frame = wanted[(str(row.factor), str(row.condition))]
        n = len(frame)
        values = {
            "races": n,
            "race_dates": int(frame.race_date.nunique()),
            "gained": int(frame.hit_class.eq("gained").sum()),
            "lost": int(frame.hit_class.eq("lost").sum()),
            "net_gained_minus_lost": int(frame.hit_class.eq("gained").sum() - frame.hit_class.eq("lost").sum()),
            "both_hit": int(frame.hit_class.eq("both_hit").sum()),
            "both_miss": int(frame.hit_class.eq("both_miss").sum()),
            "baseline_hits": int(frame.baseline_hit6.sum()),
            "candidate_hits": int(frame.candidate_hit6.sum()),
        }
        for name, expected in values.items():
            need(int(getattr(row, name)) == expected,
                 f"condition count mismatch {row.factor}/{row.condition}/{name}")
        close(row.baseline_hit_rate, frame.baseline_hit6.mean(), f"baseline rate {row.factor}/{row.condition}")
        close(row.candidate_hit_rate, frame.candidate_hit6.mean(), f"candidate rate {row.factor}/{row.condition}")
        close(row.candidate_minus_baseline_hit_rate, frame.delta_hit6.mean(),
              f"paired effect {row.factor}/{row.condition}")
        low, high = independent_bootstrap(frame)
        max_ci_diff = max(max_ci_diff, abs(float(row.paired_date_ci95_low) - low),
                          abs(float(row.paired_date_ci95_high) - high))
        close(row.paired_date_ci95_low, low, f"bootstrap low {row.factor}/{row.condition}", atol=1e-12, rtol=1e-10)
        close(row.paired_date_ci95_high, high, f"bootstrap high {row.factor}/{row.condition}", atol=1e-12, rtol=1e-10)

    # Rebuild all 11 term contributions and the race-specific U contrast from
    # fixed scores, saved parameters, and the frozen independent math module.
    features = c.load_feature_table()
    year_sizes = {2024: 6329, 2025: 6410, 2026: 4673}
    evaluation = pd.concat([c.attach_scores(features, year, "evaluation", year_sizes[year])
                            for year in (2024, 2025, 2026)], ignore_index=True)
    need(len(evaluation) == 17412 and evaluation.api_record_id.is_unique,
         "saved-score runner join does not give exact target cohort")
    need(set(evaluation.race_id) == set(ledger.race_id), "score frame race coverage differs")
    params = json.loads((SOURCE / "fit_parameters.json").read_text(encoding="utf-8"))
    fold_by_year = {int(fold["evaluation_year"]): fold for fold in params["folds"]}
    triples_by_race = {str(rid): frame.copy() for rid, frame in triples.groupby("race_id", sort=False)}
    beta_map = {(str(row.race_id), str(row.term)): row
                for row in beta_rows.itertuples(index=False)}
    boundary_map = selection_boundary.set_index("race_id")
    beta_terms = c.PAIR_FEATURES
    need(len(beta_rows) == 1779 * 11 and not beta_rows.duplicated(["race_id", "term"]).any(),
         "true-set contribution table is not 1,779 by 11")
    expected_group_by_term = {
        "score_product": "score_related_2",
        "absdiff_score": "score_related_2",
        "absdiff_hist_s1f_relpos_mean5": "style_mean_difference_3",
        "absdiff_hist_s1f_to_c4_forward_mean5": "style_mean_difference_3",
        "absdiff_hist_c4_to_g1f_forward_mean5": "style_mean_difference_3",
        "absdiff_hist_s1f_relpos_n": "support_count_difference_3",
        "absdiff_hist_s1f_to_c4_pair_n": "support_count_difference_3",
        "absdiff_hist_c4_to_g1f_pair_n": "support_count_difference_3",
        "missing_either_hist_s1f_relpos_mean5": "missingness_indicator_3",
        "missing_either_hist_s1f_to_c4_forward_mean5": "missingness_indicator_3",
        "missing_either_hist_c4_to_g1f_forward_mean5": "missingness_indicator_3",
    }
    need(set(beta_rows.term.astype(str)) == set(beta_terms),
         "A term inventory differs from fixed 11-term model contract")
    need(beta_rows.apply(lambda row: expected_group_by_term[str(row.term)] == str(row.term_group), axis=1).all(),
         "term-to-group mapping differs from fixed model interpretation")
    need(not term_summary.duplicated(["hit_class", "term_group", "term"]).any(),
         "per-term summary key duplicated")
    need(not group_summary.duplicated(["hit_class", "term_group"]).any(),
         "per-group summary key duplicated")
    max_true_energy_error = 0.0
    max_true_term_error = 0.0
    max_u_identity_error = 0.0
    max_u_term_error = 0.0
    u_rows_checked = 0
    y_distance_rows = []

    need(len(mechanical) == 9 and not mechanical.duplicated(["evaluation_year", "selection_rule"]).any(),
         "mechanical-case table does not contain exactly one row per planned rule/year")
    def expected_case(year: int, rule: str) -> tuple[str | None, float | None]:
        year_rows = ledger.loc[pd.to_numeric(ledger.evaluation_year).eq(year)].copy()
        delta = pd.to_numeric(year_rows.true_set_rank_delta_candidate_minus_baseline)
        if rule == "gained_smallest_positive_rank_improvement":
            eligible = year_rows.loc[year_rows.hit_class.eq("gained") & delta.lt(0)].copy()
            eligible["magnitude"] = -pd.to_numeric(eligible.true_set_rank_delta_candidate_minus_baseline)
            key = ["magnitude", "race_id"]
        elif rule == "lost_smallest_positive_rank_deterioration":
            eligible = year_rows.loc[year_rows.hit_class.eq("lost") & delta.gt(0)].copy()
            eligible["magnitude"] = pd.to_numeric(eligible.true_set_rank_delta_candidate_minus_baseline)
            key = ["magnitude", "race_id"]
        else:
            eligible = year_rows.loc[year_rows.hit_class.eq("both_miss") & delta.lt(0)].copy()
            eligible["magnitude"] = pd.to_numeric(eligible.true_set_candidate_rank)
            key = ["magnitude", "race_id"]
        if eligible.empty:
            return None, None
        chosen = eligible.sort_values(key, kind="stable").iloc[0]
        return str(chosen.race_id), float(chosen.magnitude)

    for row in mechanical.itertuples(index=False):
        want_key, want_magnitude = expected_case(int(row.evaluation_year), str(row.selection_rule))
        if want_key is None:
            need(not bool(row.case_available) and pd.isna(row.race_id),
                 f"ineligible mechanical example unexpectedly present: {row.evaluation_year}/{row.selection_rule}")
        else:
            need(bool(row.case_available) and str(row.race_id) == want_key,
                 f"mechanical example selection differs from frozen rule: {row.evaluation_year}/{row.selection_rule}")
            close(row.selection_magnitude, want_magnitude,
                  f"mechanical example magnitude {row.evaluation_year}/{row.selection_rule}")

    for race_id, group in evaluation.groupby("race_id", sort=True, observed=True):
        group = group.sort_values("horse_number", kind="stable").reset_index(drop=True)
        year = int(group.year.iloc[0])
        fold = fold_by_year[year]
        state = c.prediction_state(group, fold["runner_scaler"],
                                   np.asarray(fold["pair_rms"], dtype=float),
                                   np.asarray(fold["beta"], dtype=float))
        cand = triples_by_race[str(race_id)].query("arm == 'candidate'").sort_values("canonical_rank", kind="stable")
        base = triples_by_race[str(race_id)].query("arm == 'matched_baseline'").sort_values("canonical_rank", kind="stable")
        need(len(cand) == len(state["triples"]) and len(base) == len(cand),
             f"saved triple count mismatch: {race_id}")
        numbers = group.horse_number.to_numpy(int)
        tickets = [",".join(map(str, sorted(numbers[tri].tolist()))) for tri in state["triples"]]
        by_index = triples_by_race[str(race_id)].sort_values(["arm", "triple_index"], kind="stable")
        for arm_frame, arm in ((base, "matched_baseline"), (cand, "candidate")):
            expected = by_index.loc[by_index.arm.eq(arm)].sort_values("triple_index", kind="stable")
            need(expected.triple_numbers.astype(str).tolist() == tickets,
                 f"ticket enumeration mismatch: {race_id}/{arm}")
        truth_rows = np.flatnonzero(group.finish_position.to_numpy(int) <= 3)
        truth_ticket = ",".join(map(str, sorted(numbers[truth_rows].tolist())))
        truth_idx = tickets.index(truth_ticket)
        cand_true_saved = cand.loc[cand.triple_numbers.astype(str).eq(truth_ticket)].iloc[0]
        base_true_saved = base.loc[base.triple_numbers.astype(str).eq(truth_ticket)].iloc[0]
        need(int(cand_true_saved.canonical_rank) == int(led.loc[str(race_id), "true_set_candidate_rank"]),
             f"candidate true rank mismatch: {race_id}")
        need(int(base_true_saved.canonical_rank) == int(led.loc[str(race_id), "true_set_baseline_rank"]),
             f"baseline true rank mismatch: {race_id}")
        for arm_name, arm_frame, saved_true, state_energy, state_probability in (
            ("baseline", base, base_true_saved, state["baseline_energy"],
             c.softmax_energy(state["baseline_energy"], fold["baseline_tau"]["tau"])),
            ("candidate", cand, cand_true_saved, state["candidate_energy"],
             c.softmax_energy(state["candidate_energy"], fold["candidate_tau"]["tau"])),
        ):
            close(saved_true.total_energy, state_energy[truth_idx],
                  f"{arm_name} true-set energy {race_id}")
            close(saved_true.probability, state_probability[truth_idx],
                  f"{arm_name} true-set probability {race_id}")
            close(led.loc[str(race_id), f"true_set_{arm_name}_energy"],
                  saved_true.total_energy, f"ledger {arm_name} true-set energy {race_id}")
            close(led.loc[str(race_id), f"true_set_{arm_name}_probability"],
                  saved_true.probability, f"ledger {arm_name} true-set probability {race_id}")
            need(bool(led.loc[str(race_id), f"true_set_selected_{arm_name}"]) ==
                 (int(saved_true.canonical_rank) <= 6),
                 f"ledger {arm_name} selected flag differs from rank {race_id}")

        boundary_row = boundary_map.loc[str(race_id)]
        # Both tables carry the same rank-six/rank-seven quantities under
        # different intended reporting uses; compare them to the saved triples.
        for arm_label, arm_frame in (("baseline", base), ("candidate", cand)):
            rank6 = arm_frame.loc[arm_frame.canonical_rank.eq(6)].iloc[0]
            rank7 = arm_frame.loc[arm_frame.canonical_rank.eq(7)].iloc[0]
            energy_margin = float(rank6.total_energy - rank7.total_energy)
            probability_margin = float(rank6.probability - rank7.probability)
            close(boundary_row[f"{arm_label}_energy_margin_6_7"], energy_margin,
                  f"{arm_label} margin {race_id}")
            close(boundary_row[f"{arm_label}_probability_margin_6_7"], probability_margin,
                  f"{arm_label} probability margin {race_id}")
            need(str(boundary_row[f"{arm_label}_rank6_ticket"]) == str(rank6.triple_numbers) and
                 str(boundary_row[f"{arm_label}_rank7_ticket"]) == str(rank7.triple_numbers),
                 f"{arm_label} boundary ticket mismatch {race_id}")
            need(bool(boundary_row[f"{arm_label}_boundary_exact_energy_tie"]) ==
                 (energy_margin == 0.0), f"{arm_label} exact tie flag mismatch {race_id}")
            need(bool(boundary_row[f"{arm_label}_boundary_tolerance_energy_tie"]) ==
                 (abs(energy_margin) <= TIE_TOL),
                 f"{arm_label} tolerance tie flag mismatch {race_id}")
        beta = np.asarray(fold["beta"], dtype=float)
        true_contrib = state["x"][truth_idx] * beta
        saved_terms = np.array([float(beta_map[(str(race_id), term)].beta_contribution)
                                for term in beta_terms], dtype=float)
        saved_beta = np.array([float(beta_map[(str(race_id), term)].beta)
                               for term in beta_terms], dtype=float)
        saved_features = np.array([float(beta_map[(str(race_id), term)].triple_feature)
                                   for term in beta_terms], dtype=float)
        close(saved_beta, beta, f"saved coefficient vector {race_id}")
        close(saved_features, state["x"][truth_idx], f"saved true-set feature vector {race_id}")
        max_true_term_error = max(max_true_term_error,
                                  close(saved_terms, true_contrib, f"true terms {race_id}", atol=1e-10, rtol=1e-10))
        rel = float(state["relation_energy"][truth_idx])
        saved_rel = float(cand_true_saved.relationship_energy)
        max_true_energy_error = max(max_true_energy_error,
                                    abs(float(true_contrib.sum()) - rel), abs(saved_rel - rel))
        need(abs(float(true_contrib.sum()) - rel) <= 1e-10 and abs(saved_rel - rel) <= 1e-10,
             f"true 11-term contribution total mismatch: {race_id}")

        true_rank = int(cand_true_saved.canonical_rank)
        u_rank = 7 if true_rank <= 6 else 6
        u_row = cand.loc[cand.canonical_rank.eq(u_rank)].iloc[0]
        u_ticket = str(u_row.triple_numbers)
        need(u_ticket == tickets[int(u_row.triple_index)], f"U ticket-index mismatch: {race_id}")
        u_idx = int(u_row.triple_index)
        delta_terms = (state["x"][truth_idx] - state["x"][u_idx]) * beta
        base_contrast = float(state["baseline_energy"][truth_idx] - state["baseline_energy"][u_idx])
        energy_contrast = float(state["candidate_energy"][truth_idx] - state["candidate_energy"][u_idx])
        identity_error = abs(energy_contrast - (base_contrast + float(delta_terms.sum())))
        max_u_identity_error = max(max_u_identity_error, identity_error)
        need(identity_error <= 1e-10, f"true-vs-U additive identity mismatch: {race_id}")
        b_row = boundary.loc[boundary.race_id.eq(str(race_id))].iloc[0]
        need(str(b_row.candidate_boundary_competitor_ticket) == u_ticket and
             int(b_row.candidate_boundary_competitor_rank) == u_rank,
             f"A U rule/ticket does not match independent selection: {race_id}")
        close(b_row.candidate_true_minus_competitor_energy, energy_contrast,
              f"U energy contrast {race_id}")
        close(b_row.candidate_true_minus_competitor_baseline_score_energy, base_contrast,
              f"U baseline score contrast {race_id}")
        close(b_row.candidate_true_minus_competitor_relationship_energy, float(delta_terms.sum()),
              f"U relation contrast {race_id}")
        close(b_row.candidate_true_minus_competitor_exact_energy_tie,
              energy_contrast == 0.0, f"U exact tie flag {race_id}")
        close(b_row.candidate_true_minus_competitor_tolerance_energy_tie,
              abs(energy_contrast) <= TIE_TOL, f"U tolerance tie flag {race_id}")
        close(b_row.candidate_true_stable_order_precedes_competitor,
              true_rank < u_rank, f"U stable order flag {race_id}")
        a_delta_terms = np.array([float(getattr(b_row, f"true_minus_competitor__{term}"))
                                  for term in beta_terms])
        max_u_term_error = max(max_u_term_error,
                               close(a_delta_terms, delta_terms,
                                     f"U beta-contribution contrasts {race_id}", atol=1e-10, rtol=1e-10))
        u_rows_checked += 1

    # Validate A's grouped summaries only after every underlying race-term row
    # has been checked against the saved fold math above.
    class_by_race = ledger.set_index("race_id").hit_class.astype(str)
    verified_terms = beta_rows.copy()
    expected_hit_class = verified_terms.race_id.astype(str).map(class_by_race)
    need(verified_terms.hit_class.astype(str).reset_index(drop=True).equals(
        expected_hit_class.astype(str).reset_index(drop=True)),
        "A true-set contribution outcome labels differ from independent ledger")
    verified_terms["hit_class"] = verified_terms.race_id.astype(str).map(class_by_race)
    need(verified_terms.hit_class.notna().all(), "verified term rows lack outcome group")
    expected_term_summary = verified_terms.groupby(
        ["hit_class", "term_group", "term"], as_index=False, sort=True, observed=True
    ).agg(races=("race_id", "nunique"),
          contribution_mean=("beta_contribution", "mean"),
          contribution_median=("beta_contribution", "median"),
          contribution_p25=("beta_contribution", lambda s: s.quantile(0.25)),
          contribution_p75=("beta_contribution", lambda s: s.quantile(0.75)))
    term_join = term_summary.merge(expected_term_summary,
                                   on=["hit_class", "term_group", "term"],
                                   suffixes=("_a", "_independent"), validate="one_to_one")
    need(len(term_join) == len(term_summary) == len(expected_term_summary),
         "per-term summary coverage differs from independent rows")
    for column in ("contribution_mean", "contribution_median", "contribution_p25", "contribution_p75"):
        close(term_join[f"{column}_a"], term_join[f"{column}_independent"],
              f"per-term {column}", atol=1e-10, rtol=1e-10)
    need((term_join.races_a.astype(int) == term_join.races_independent.astype(int)).all(),
         "per-term summary race counts differ")

    per_race_group = verified_terms.groupby(
        ["race_id", "hit_class", "term_group"], as_index=False, sort=True,
        observed=True).beta_contribution.sum()
    expected_group_summary = per_race_group.groupby(
        ["hit_class", "term_group"], as_index=False, sort=True, observed=True
    ).agg(races=("race_id", "nunique"),
          grouped_contribution_mean=("beta_contribution", "mean"),
          grouped_contribution_median=("beta_contribution", "median"),
          grouped_contribution_p25=("beta_contribution", lambda s: s.quantile(0.25)),
          grouped_contribution_p75=("beta_contribution", lambda s: s.quantile(0.75)))
    group_join = group_summary.merge(expected_group_summary,
                                     on=["hit_class", "term_group"],
                                     suffixes=("_a", "_independent"), validate="one_to_one")
    need(len(group_join) == len(group_summary) == len(expected_group_summary),
         "group summary coverage differs from independent row sums")
    for column in ("grouped_contribution_mean", "grouped_contribution_median",
                   "grouped_contribution_p25", "grouped_contribution_p75"):
        close(group_join[f"{column}_a"], group_join[f"{column}_independent"],
              f"group {column}", atol=1e-10, rtol=1e-10)
    need((group_join.races_a.astype(int) == group_join.races_independent.astype(int)).all(),
         "group summary race counts differ")

    pair_groups = {
        "score_related_2": ["score_product", "absdiff_score"],
        "style_mean_difference_3": ["absdiff_hist_s1f_relpos_mean5",
                                    "absdiff_hist_s1f_to_c4_forward_mean5",
                                    "absdiff_hist_c4_to_g1f_forward_mean5"],
        "support_count_difference_3": ["absdiff_hist_s1f_relpos_n",
                                       "absdiff_hist_s1f_to_c4_pair_n",
                                       "absdiff_hist_c4_to_g1f_pair_n"],
        "missingness_indicator_3": ["missing_either_hist_s1f_relpos_mean5",
                                     "missing_either_hist_s1f_to_c4_forward_mean5",
                                     "missing_either_hist_c4_to_g1f_forward_mean5"],
    }
    max_mean_additivity_error = 0.0
    for row in group_join.itertuples(index=False):
        term_values = term_join.loc[
            term_join.hit_class.eq(row.hit_class) & term_join.term_group.eq(row.term_group)
        ]
        expected_terms = pair_groups[str(row.term_group)]
        term_values = term_values.set_index("term")
        mean_sum = float(term_values.loc[expected_terms, "contribution_mean_a"].sum())
        mean_error = abs(float(row.grouped_contribution_mean_a) - mean_sum)
        max_mean_additivity_error = max(max_mean_additivity_error, mean_error)
        need(mean_error <= 1e-10,
             f"mean contribution additivity fails for {row.hit_class}/{row.term_group}")

    # Direct year-distance composition table; raw counts and net only.
    tmp = ledger.copy()
    tmp["evaluation_year"] = pd.to_numeric(tmp.evaluation_year, errors="raise").astype(int)
    tmp["distance_m"] = pd.to_numeric(tmp.distance_m, errors="raise").astype(int)
    for (year, dist), frame in tmp.groupby(["evaluation_year", "distance_m"], sort=True):
        y_distance_rows.append({"year": int(year), "distance_m": int(dist), "races": len(frame),
                                "gained": int(frame.hit_class.eq("gained").sum()),
                                "lost": int(frame.hit_class.eq("lost").sum()),
                                "net": int(frame.hit_class.eq("gained").sum() - frame.hit_class.eq("lost").sum()),
                                "net_per_100_races": float(100 * frame.delta_hit6.mean())})

    result = {
        "status": "PASS",
        "scope": "fixed-source, no-fit direct re-computation; no A helper import",
        "source_manifest_sha256": source_hashes[
            "jeju/research/20261010_joint_relationship_v1/ARTIFACT_MANIFEST.json"],
        "a_output_hashes_checked": len(outputs),
        "cohort": {"races": len(ledger), "runner_rows": len(runners),
                   "race_days": int(ledger.race_date.nunique()), "discordant": len(discordant),
                   "outcome_counts": {k: int(v) for k, v in counts.items()},
                   "changed_ticket_sets": int(ledger.selected_ticket_set_changed.sum()),
                   "unchanged_ticket_sets": int((~ledger.selected_ticket_set_changed).sum()),
                   "entered_and_exited_ticket_rows_each": 1415},
        "condition_rows_recomputed": len(conditions),
        "condition_bootstrap_max_abs_diff": max_ci_diff,
        "true_set_term_rows_recomputed": len(beta_rows),
        "per_term_outcome_summaries_recomputed": len(term_summary),
        "per_group_outcome_summaries_recomputed": len(group_summary),
        "group_mean_term_additivity_max_abs_error": max_mean_additivity_error,
        "true_set_term_max_abs_diff": max_true_term_error,
        "true_set_energy_max_abs_diff": max_true_energy_error,
        "true_vs_U_rows_recomputed": u_rows_checked,
        "true_vs_U_identity_max_abs_error": max_u_identity_error,
        "true_vs_U_term_contribution_max_abs_diff": max_u_term_error,
        "mechanical_cases_rechecked": len(mechanical),
        "year_distance_raw_composition": y_distance_rows,
        "limitations": [
            "Retrospective reused evaluation cohort; no independent holdout or prospective validation.",
            "Condition families are descriptive; hit-class subgrouping is outcome-defined.",
            "Single-factor intervals are pointwise and do not control family-wise multiplicity.",
            "Year-distance composition remains a confounding/Simpson-reversal concern.",
            "True-set and U decomposition use actual results and are post-outcome diagnostics, not predictors.",
            "No training, fitting, tuning, database access, or network access was performed by this reviewer."
        ]
    }
    output = OUT / "independent_analysis_output_receipt.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "status", "a_output_hashes_checked", "cohort", "condition_rows_recomputed",
        "condition_bootstrap_max_abs_diff", "true_set_term_max_abs_diff",
        "true_set_energy_max_abs_diff", "true_vs_U_identity_max_abs_error",
        "true_vs_U_term_contribution_max_abs_diff")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

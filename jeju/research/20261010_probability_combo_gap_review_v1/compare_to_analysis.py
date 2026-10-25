"""Compare this independent reconstruction with the approved A analysis outputs."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OWN = Path(__file__).resolve().parent
A = ROOT / "jeju/research/20261010_probability_combo_gap_v1/outputs"
C = OWN / "outputs"
ATOL = 1e-12


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def assert_numeric_parity(left: pd.DataFrame, right: pd.DataFrame,
                          keys: list[str], fields: list[str], label: str) -> dict:
    vector_columns = {"triple_horse_ids", "triple_numbers", "own_six_horse_union_ids",
                      "own_only_union_horse_ids", "other_only_union_horse_ids"}

    def normalized(values: pd.Series, column: str) -> pd.Series:
        if column in vector_columns:
            def vector_key(value: object) -> str:
                tokens = re.findall(r"\d+", str(value))
                if column != "triple_horse_ids" and column != "triple_numbers":
                    tokens.sort()
                return ",".join(tokens)
            return values.fillna("").astype(str).map(vector_key)
        return (values.fillna("<NA>").astype(str).str.strip()
                .str.replace("[", "", regex=False).str.replace("]", "", regex=False)
                .str.replace("'", "", regex=False)
                .str.replace('"', "", regex=False))

    l = left.sort_values(keys, kind="stable").reset_index(drop=True)
    r = right.sort_values(keys, kind="stable").reset_index(drop=True)
    assert len(l) == len(r), (label, len(l), len(r))
    for key in keys:
        if (pd.api.types.is_numeric_dtype(l[key].dtype)
                and pd.api.types.is_numeric_dtype(r[key].dtype)):
            assert np.allclose(pd.to_numeric(l[key]).to_numpy(dtype=np.float64),
                               pd.to_numeric(r[key]).to_numpy(dtype=np.float64),
                               rtol=0, atol=ATOL, equal_nan=True), (label, key)
        else:
            assert normalized(l[key], key).equals(normalized(r[key], key)), (label, key)
    maxima = {}
    for col in fields:
        if (pd.api.types.is_bool_dtype(l[col].dtype)
                or not pd.api.types.is_numeric_dtype(l[col].dtype)):
            assert normalized(l[col], col).equals(normalized(r[col], col)), (label, col)
            maxima[col] = 0.0
            continue
        a = pd.to_numeric(l[col], errors="coerce").to_numpy(dtype=np.float64)
        b = pd.to_numeric(r[col], errors="coerce").to_numpy(dtype=np.float64)
        delta = np.abs(a - b)
        maxima[col] = float(np.nanmax(delta)) if np.isfinite(delta).any() else 0.0
        assert np.allclose(a, b, rtol=0, atol=ATOL, equal_nan=True), (
            label, col, maxima[col])
    return {"rows": int(len(l)), "max_abs_difference": maxima,
            "tolerance": ATOL, "passed": True}


def load(name: str, base: Path) -> pd.DataFrame:
    path = base / name
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)


def main() -> None:
    checks = {}
    a_triples = load("all_triples.parquet", A)
    c_triples = load("all_triples.parquet", C)
    triple_fields = ["triple_horse_ids", "triple_numbers", "triple_energy",
                     "joint_probability_saved_tau", "joint_probability_tau1",
                     "rank_after_saved_tau", "rank_after_tau1",
                     "exact_energy_tie_size", "is_truth"]
    checks["all_triples"] = assert_numeric_parity(
        a_triples, c_triples, ["race_id", "variant", "stable_rank"],
        triple_fields, "all_triples")

    a_races = load("race_diagnostics.parquet", A)
    c_races = load("race_diagnostics.parquet", C)
    race_fields = [
        "race_date", "year", "distance_m", "field_n", "saved_tau",
        "true_triple_rank", "true_rank_after_saved_tau", "true_rank_after_tau1",
        "hit_at_1", "hit_at_3", "hit_at_6", "hit_at_10", "hit_at_20",
        "joint_true_nll_saved_tau", "full_joint_brier_saved_tau",
        "top3_marginal_log_loss_saved_tau", "top3_marginal_brier_saved_tau",
        "joint_true_nll_tau1", "full_joint_brier_tau1",
        "top3_marginal_log_loss_tau1", "top3_marginal_brier_tau1",
        "six_mass_saved_tau", "six_mass_tau1", "scaled_tau_rank_mismatch_n",
        "scaled_tau_top6_mismatch", "tau1_rank_mismatch_n", "tau1_top6_mismatch",
        "p_top3_saved_tau_score_order_violations", "p_top3_tau1_score_order_violations",
    ]
    a_races = a_races.rename(columns={
        "true_triple_exact_tie_size": "true_triple_tie_size",
        "exact_tie_groups_n": "exact_energy_tie_groups",
        "exact_tied_triples_n": "tied_triple_rows",
    })
    race_fields += ["true_triple_tie_size", "exact_energy_tie_groups", "tied_triple_rows"]
    checks["race_diagnostics"] = assert_numeric_parity(
        a_races, c_races, ["race_id", "variant"], race_fields, "race_diagnostics")
    def tie_counts(value: str) -> tuple[int, int, int]:
        counts = json.loads(value)
        parsed = [(int(size), int(n_groups)) for size, n_groups in counts.items()]
        return (sum(n_groups for _, n_groups in parsed),
                sum(size * n_groups for size, n_groups in parsed),
                sum(size * (size - 1) // 2 * n_groups for size, n_groups in parsed))
    tie_cols = c_races["exact_tie_counts"].map(tie_counts)
    c_tie_summary = c_races[["race_id", "variant"]].copy()
    c_tie_summary[["exact_tie_groups_n", "exact_tied_triples_n", "exact_tie_pairs_n"]] = pd.DataFrame(
        tie_cols.tolist(), index=c_tie_summary.index)
    a_tie_summary = a_races[["race_id", "variant", "exact_energy_tie_groups",
                             "tied_triple_rows", "exact_tie_pairs_n"]].rename(columns={
                                 "exact_energy_tie_groups": "exact_tie_groups_n",
                                 "tied_triple_rows": "exact_tied_triples_n"})
    checks["exact_tie_count_summary"] = assert_numeric_parity(
        a_tie_summary, c_tie_summary, ["race_id", "variant"],
        ["exact_tie_groups_n", "exact_tied_triples_n", "exact_tie_pairs_n"],
        "exact_tie_count_summary")

    a_boot = load("paired_date_bootstrap.csv", A)
    c_boot = load("paired_date_bootstrap.csv", C)
    checks["paired_date_bootstrap"] = assert_numeric_parity(
        a_boot, c_boot, ["temperature_basis", "metric", "group", "value"],
        ["delta_STYLE6_minus_F1", "ci95_low", "ci95_high", "races",
         "race_days", "resamples", "seed"], "paired_date_bootstrap")

    a_contrib = load("runner_loss_contributions.csv", A)
    c_contrib = load("runner_loss_contributions.csv", C)
    a_contrib["ticket_changed"] = a_contrib.ticket_changed.map({False: "unchanged", True: "changed"})
    a_contrib["outcome_group"] = a_contrib.outcome_group.replace({
        "actual_top3": "top3", "other_runners": "other"})
    checks["runner_loss_contributions"] = assert_numeric_parity(
        a_contrib, c_contrib, ["metric", "ticket_changed", "outcome_group", "variant"],
        ["race_equal_loss_contribution", "runner_rows", "races", "race_days"],
        "runner_loss_contributions")

    a_cross = load("ticket_change_loss_cross.csv", A)
    c_cross = load("ticket_change_loss_cross.csv", C)
    a_cross["ticket_changed"] = a_cross.ticket_changed.map({False: "unchanged", True: "changed"})
    checks["ticket_change_loss_cross"] = assert_numeric_parity(
        a_cross, c_cross, ["ticket_changed", "metric"],
        ["races", "improved_races", "worsened_races", "unchanged_races",
         "mean_delta_STYLE6_minus_F1"], "ticket_change_loss_cross")

    a_mass = load("six_mass_reliability.csv", A)
    c_mass = load("six_mass_reliability.csv", C)
    assert a_mass.right_endpoint_inclusive.astype(bool).equals(
        a_mass.bin_right.eq(1.0)), "A bin endpoint flag contract"
    checks["six_mass_reliability"] = assert_numeric_parity(
        a_mass, c_mass, ["variant", "bin_left", "bin_right"],
        ["races", "race_days", "mean_predicted_mass", "observed_hit_rate"],
        "six_mass_reliability")

    a_u6 = load("ticket_and_union_decomposition.csv", A)
    a_u6["changed"] = a_u6.changed.map({False: "unchanged", True: "changed"})
    a_u6["six_hit"] = a_u6.six_hit.astype(int)
    a_u6["all3in_own_union"] = a_u6.all3in_own_union.astype(int)
    c_u6 = load("ticket_and_union_decomposition.csv", C).rename(columns={
        "ticket_changed": "changed", "all3inU6_v": "all3in_own_union"})
    c_u6["six_hit"] = c_u6.union_state.eq("hit").astype(int)
    checks["ticket_u6_decomposition"] = assert_numeric_parity(
        a_u6, c_u6,
        ["race_id", "variant"],
        ["race_date", "year", "distance_m", "six_hit", "ticket_overlap_n",
         "ticket_symmetric_difference_n", "changed", "hit_both_or_only_or_neither",
         "own_six_horse_union_n", "own_six_horse_union_ids", "other_union_overlap_n",
         "own_only_union_horse_ids", "other_only_union_horse_ids",
         "all3in_own_union", "union_state"], "ticket_u6_decomposition")

    # Independently check the report's year-specific gained/lost hit counts.
    f1_pairs = c_u6.loc[c_u6.variant.eq("F1"),
                        ["race_id", "year", "hit_both_or_only_or_neither"]]
    status_counts = {}
    for year, frame in f1_pairs.groupby("year", sort=True):
        counts = frame.hit_both_or_only_or_neither.value_counts().to_dict()
        status_counts[str(int(year))] = {k: int(counts.get(k, 0)) for k in
                                         ("hit_both", "F1_only", "STYLE6_only", "neither")}
    expected_year_hits = {
        "2024": {"F1_only": 15, "STYLE6_only": 28},
        "2025": {"F1_only": 17, "STYLE6_only": 15},
        "2026": {"F1_only": 11, "STYLE6_only": 10},
    }
    for year, expected in expected_year_hits.items():
        for status, count in expected.items():
            assert status_counts[year][status] == count, (year, status, status_counts[year])
    checks["year_gained_lost_hits"] = {
        "counts_by_year": status_counts,
        "README_claims_verified": True,
    }

    comparison = {
        "passed": True,
        "independent_recomputation": "saved raw score + own full-triple implementation; no A helper imported",
        "comparison_tolerance": ATOL,
        "A_compared_artifact_sha256": {
            name: digest(A / name) for name in (
                "all_triples.parquet", "race_diagnostics.parquet",
                "paired_date_bootstrap.csv", "runner_loss_contributions.csv",
                "ticket_change_loss_cross.csv", "six_mass_reliability.csv",
                "ticket_and_union_decomposition.csv")
        },
        "checks": checks,
        "interpretation_boundary": "Parity validates output reproduction; U6 is variant-specific endogenous selected-ticket union and its decomposition is descriptive, not causal.",
    }
    path = OWN / "independent_A_comparison_final.json"
    assert not path.exists()
    path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "checks": checks,
                      "comparison_receipt_sha256": digest(path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

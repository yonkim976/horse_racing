#!/usr/bin/env python3
"""Reconstruct rank-6/7 ties and true-set-versus-rival energy identities."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
REVIEW = ROOT / "jeju/research/20261010_joint_gain_loss_review_v1"
JOINT = ROOT / "jeju/research/20261010_joint_relationship_v1"
TRIPLES_PATH = JOINT / "outputs/report/all_triples.parquet"
RACES_PATH = JOINT / "outputs/report/race_metrics.csv"
TOL = 1e-12
EXPECTED = {
    "triples_sha256": "13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c",
    "races_sha256": "89820acf0dfafc749f394cf9e74a3b58a5ec890e2c746f890ad257eaf32ff115",
}


def digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    hashes = {"triples_sha256": digest(TRIPLES_PATH), "races_sha256": digest(RACES_PATH)}
    require(hashes == EXPECTED, "frozen all-triples or race-metric hash changed")
    triples = pd.read_parquet(TRIPLES_PATH)
    races = pd.read_csv(RACES_PATH, dtype={"race_id": "string"})
    require(len(races) == 1779 and races.race_id.is_unique, "race metric cohort key mismatch")
    require(len(triples) == 402808, "unexpected all-triples row count")
    require(not triples.duplicated(["race_id", "arm", "triple_index"]).any(),
            "duplicate (race_id, arm, triple_index) key")
    require(set(triples.arm.astype(str)) == {"matched_baseline", "candidate"},
            "unexpected triple arms")
    require(set(triples.race_id.astype(str)) == set(races.race_id.astype(str)),
            "triple race key coverage mismatch")
    races["hit_class"] = np.select(
        [races.candidate_hit6.eq(1) & races.baseline_hit6.eq(0),
         races.baseline_hit6.eq(1) & races.candidate_hit6.eq(0),
         races.baseline_hit6.eq(1) & races.candidate_hit6.eq(1)],
        ["gained", "lost", "both_hit"], default="both_miss")

    triples_by_race_arm = triples.groupby(["race_id", "arm"], sort=False, observed=True)
    rank_rows: list[dict] = []
    candidate_rival_rows: list[dict] = []
    for (race_id, arm), frame in triples_by_race_arm:
        frame = frame.sort_values("canonical_rank", kind="stable").reset_index(drop=True)
        require(frame.canonical_rank.astype(int).tolist() == list(range(1, len(frame) + 1)),
                f"non-contiguous canonical ranks: {race_id}/{arm}")
        require(frame.triple_index.is_unique and len(frame) >= 7,
                f"triple enumeration insufficient: {race_id}/{arm}")
        require(int(frame.is_true_set.astype(bool).sum()) == 1,
                f"actual true-set marker not unique: {race_id}/{arm}")
        require(np.isfinite(frame.total_energy.to_numpy(float)).all(),
                f"nonfinite energies: {race_id}/{arm}")
        require(abs(float(frame.probability.sum()) - 1.0) <= 1e-12,
                f"triple probabilities do not sum to one: {race_id}/{arm}")

        rank6 = frame.iloc[5]
        rank7 = frame.iloc[6]
        energy_margin = float(rank6.total_energy - rank7.total_energy)
        prob_margin = float(rank6.probability - rank7.probability)
        truth = frame.loc[frame.is_true_set.astype(bool)].iloc[0]
        rank_rows.append({
            "race_id": str(race_id), "arm": str(arm),
            "energy_margin_6_7": energy_margin,
            "probability_margin_6_7": prob_margin,
            "exact_energy_tie": bool(energy_margin == 0.0),
            "tolerance_energy_tie": bool(abs(energy_margin) <= TOL),
            "rank6_ticket": str(rank6.triple_numbers),
            "rank7_ticket": str(rank7.triple_numbers),
            "true_rank": int(truth.canonical_rank),
            "true_ticket": str(truth.triple_numbers),
        })

        if str(arm) == "candidate":
            truth_rank = int(truth.canonical_rank)
            rival_rank = 7 if truth_rank <= 6 else 6
            rival = frame.loc[frame.canonical_rank.eq(rival_rank)]
            require(len(rival) == 1 and not bool(rival.iloc[0].is_true_set),
                    f"selected rival is absent/true-set: {race_id}")
            rival = rival.iloc[0]
            gap = float(truth.total_energy - rival.total_energy)
            score_delta = float(truth.baseline_score_energy - rival.baseline_score_energy)
            relationship_delta = float(truth.relationship_energy - rival.relationship_energy)
            reconstructed_gap = score_delta + relationship_delta
            difference = gap - reconstructed_gap
            require(abs(difference) <= TOL, f"true/rival energy identity failed: {race_id}")
            candidate_rival_rows.append({
                "race_id": str(race_id),
                "true_set_rank": truth_rank,
                "true_set_selected": truth_rank <= 6,
                "rival_rank": rival_rank,
                "true_set_ticket": str(truth.triple_numbers),
                "rival_ticket": str(rival.triple_numbers),
                "true_minus_rival_energy": gap,
                "baseline_score_energy_difference": score_delta,
                "relationship_energy_difference": relationship_delta,
                "identity_residual": difference,
            })

    rank = pd.DataFrame(rank_rows).merge(races[["race_id", "hit_class"]],
                                         on="race_id", validate="many_to_one")
    rival = pd.DataFrame(candidate_rival_rows).merge(races[["race_id", "hit_class"]],
                                                     on="race_id", validate="one_to_one")
    require(len(rank) == 3558, "rank-boundary cohort must contain 1,779 races per arm")
    require(len(rival) == 1779, "candidate true-rival table is incomplete")

    margin_summary = {}
    for arm in ("matched_baseline", "candidate"):
        arm_rows = rank.loc[rank.arm.eq(arm)]
        margin_summary[arm] = {}
        for label in ("all", "gained", "lost"):
            subset = arm_rows if label == "all" else arm_rows.loc[arm_rows.hit_class.eq(label)]
            margin_summary[arm][label] = {
                "races": int(len(subset)),
                "exact_energy_ties": int(subset.exact_energy_tie.sum()),
                "tolerance_energy_ties_abs_le_1e-12": int(subset.tolerance_energy_tie.sum()),
                "median_rank6_minus_rank7_energy_margin": float(subset.energy_margin_6_7.median()),
                "median_rank6_minus_rank7_probability_margin": float(subset.probability_margin_6_7.median()),
            }

    gap_summary = {}
    for label in ("all", "gained", "lost", "both_hit", "both_miss"):
        subset = rival if label == "all" else rival.loc[rival.hit_class.eq(label)]
        gap_summary[label] = {
            "races": int(len(subset)),
            "mean_true_minus_rival_energy": float(subset.true_minus_rival_energy.mean()),
            "mean_baseline_score_energy_difference": float(subset.baseline_score_energy_difference.mean()),
            "mean_relationship_energy_difference": float(subset.relationship_energy_difference.mean()),
            "max_abs_row_identity_residual": float(subset.identity_residual.abs().max()),
            # These medians are deliberately separate; medians are not additive.
            "median_true_minus_rival_energy": float(subset.true_minus_rival_energy.median()),
            "median_baseline_score_energy_difference": float(subset.baseline_score_energy_difference.median()),
            "median_relationship_energy_difference": float(subset.relationship_energy_difference.median()),
        }

    receipt = {
        "status": "PASS",
        "scope": "Direct read-only reconstruction from the frozen all-triples and race-metrics artifacts; no analysis helper imported.",
        "source_hashes": hashes,
        "rows": {"all_triples": len(triples), "race_arm_groups": len(rank),
                 "candidate_true_rival_contrasts": len(rival)},
        "checks": {
            "exact_two_arm_coverage": True,
            "unique_race_arm_triple_key": True,
            "canonical_rank_complete_per_race_arm": True,
            "one_true_set_marker_per_race_arm": True,
            "probability_sums_within_1e_12": True,
            "candidate_true_rival_rule": "true rank <=6: highest-ranked non-true rival is rank7; true rank >6: rival is rank6",
            "rowwise_energy_identity": "E_candidate(true)-E_candidate(rival) = [E0(true)-E0(rival)] + [G(true)-G(rival)]",
            "max_abs_row_identity_residual": float(rival.identity_residual.abs().max()),
            "group_means_are_additive": True,
            "group_medians_are_nonadditive_and_reported_separately": True,
        },
        "rank6_rank7_margin_summary": margin_summary,
        "candidate_true_vs_rival_summary": gap_summary,
        "limitations": [
            "The all-triples rows are saved evaluation artifacts; this check does not reconstruct the 11 separate relationship feature terms.",
            "The true-set and candidate-rival comparison uses the realized finish order and is post-outcome diagnostic only.",
            "An exact or near-zero rank-6/rank-7 margin is not evidence for a future rule that turns relationship terms off.",
            "Group median components are not additive; only the rowwise identity and arithmetic group means have additive interpretations.",
        ],
    }
    output = REVIEW / "outputs/saved_boundary_reference.json"
    output.resolve().relative_to(REVIEW.resolve())
    temp = output.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    os.replace(temp, output)
    print(json.dumps({"status": receipt["status"], "output": str(output.relative_to(ROOT)),
                      "boundary": margin_summary,
                      "row_identity_max_abs": receipt["checks"]["max_abs_row_identity_residual"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

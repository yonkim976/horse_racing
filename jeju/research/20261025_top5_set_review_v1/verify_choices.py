"""Independent label-free replay of the locked Top-5 choices.

This code deliberately does not import the study selector or model code. It
reads no outcome, odds, favorite, or stored true-set columns.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = ROOT / "jeju/research/20261025_top5_set_selection_v1"
ROOT_REVIEW = ROOT / "jeju/research/20261025_top5_set_rootreview_v1"
SELECTIONS = STUDY / "outputs/selections.jsonl"
SELECTION_RECEIPT = STUDY / "outputs/selection_receipt.json"
ROOT_Q_RECEIPT = ROOT_REVIEW / "ROOT_Q_RECONSTRUCTION.json"
ROOT_SELECTOR_REVIEW = ROOT_REVIEW / "ROOT_SELECTION_CODE_REVIEW.json"
BASELINE = ROOT / (
    "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/"
    "baseline_runner_predictions.parquet"
)
TRIPLES = ROOT / "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet"
BOOTSTRAP = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
ROOT_Q_SHA256 = "f50e75f1815793fd4874bc36f38f80d64c4fd0192da2e89fb144b9ae7bae627a"
SELECTOR_SHA256 = "9bbd0556236dde13697f62dec70e7a81928bab1f57de0ab267008b429e94c4e2"
BASELINE_SHA256 = "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1"
TRIPLES_SHA256 = "13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c"
BOOTSTRAP_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
TIE_TOL = 1e-12
PRIMARY_DISTANCES = {900, 1000, 1110, 1200}


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def read_locked_inputs() -> tuple[list[dict[str, Any]], pd.DataFrame, dict[str, pd.DataFrame]]:
    for path in (SELECTIONS, SELECTION_RECEIPT, ROOT_Q_RECEIPT, ROOT_SELECTOR_REVIEW,
                 BASELINE, TRIPLES, BOOTSTRAP):
        if not path.is_file():
            raise FileNotFoundError(f"required locked artifact is absent: {path.relative_to(ROOT)}")
    q_receipt = json.loads(ROOT_Q_RECEIPT.read_text(encoding="utf-8"))
    if digest(ROOT_Q_RECEIPT) != ROOT_Q_SHA256 or q_receipt.get("passed") is not True:
        raise AssertionError("root Q-reconstruction receipt is absent, changed, or failing")
    if q_receipt.get("outcome_labels_read") is not False or q_receipt.get("new_fits") != 0:
        raise AssertionError("root Q reconstruction is not label-free and zero-fit")

    code_review = json.loads(ROOT_SELECTOR_REVIEW.read_text(encoding="utf-8"))
    if code_review.get("approved") is not True or code_review.get("report_execution_approved") is not False:
        raise AssertionError("selector is not approved or report stage has already been authorized")
    if code_review.get("selector_sha256") != SELECTOR_SHA256:
        raise AssertionError("root selector code review is not bound to the expected code")

    receipt = json.loads(SELECTION_RECEIPT.read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS_LABEL_FREE_SELECTION":
        raise AssertionError("selection stage receipt is not passing")
    if receipt.get("selection_stage_reads_outcome_labels") is not False:
        raise AssertionError("selection receipt does not certify outcome-free choice generation")
    if receipt.get("selector_code_sha256") != SELECTOR_SHA256:
        raise AssertionError("selection receipt is not bound to the reviewed selector code")
    selection_lock = receipt.get("selection_artifact", {})
    if selection_lock.get("path") != "jeju/research/20261025_top5_set_selection_v1/outputs/selections.jsonl":
        raise AssertionError("unexpected selection artifact path")
    if digest(SELECTIONS) != selection_lock.get("sha256"):
        raise AssertionError("selection artifact hash differs from its receipt")
    source_locks = receipt.get("source_artifacts", {})
    expected_source_locks = {
        "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet": BASELINE_SHA256,
        "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet": TRIPLES_SHA256,
        "jeju/research/20261025_top5_set_rootreview_v1/ROOT_Q_RECONSTRUCTION.json": ROOT_Q_SHA256,
        "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy": BOOTSTRAP_SHA256,
    }
    for relpath, expected_sha in expected_source_locks.items():
        if source_locks.get(relpath, {}).get("sha256") != expected_sha:
            raise AssertionError(f"selection receipt did not bind source hash: {relpath}")
    for path, sha in ((BASELINE, BASELINE_SHA256), (TRIPLES, TRIPLES_SHA256), (BOOTSTRAP, BOOTSTRAP_SHA256)):
        if digest(path) != sha:
            raise AssertionError(f"locked source changed: {path.relative_to(ROOT)}")

    selection_rows = [json.loads(line) for line in SELECTIONS.read_text(encoding="utf-8").splitlines()]
    if len(selection_rows) != 1779 or len({row["race_id"] for row in selection_rows}) != 1779:
        raise AssertionError("selection artifact is incomplete or has duplicate races")
    baseline = pd.read_parquet(
        BASELINE,
        columns=["race_id", "race_date", "year", "distance_m", "horse_id",
                 "horse_number", "field_n", "score", "variant"],
    )
    if len(baseline) != 17412 or set(baseline.variant.dropna().astype(str)) != {"F1_STYLE6"}:
        raise AssertionError("baseline cohort or frozen variant changed")
    required = ["race_id", "evaluation_year", "distance_m", "arm", "triple_numbers", "probability"]
    arms: dict[str, pd.DataFrame] = {}
    for arm in ("candidate", "matched_baseline"):
        arms[arm] = pq.read_table(
            TRIPLES,
            columns=[column for column in required if column != "arm"],
            filters=[("arm", "=", arm)],
        ).to_pandas()
        if len(arms[arm]) != 201404:
            raise AssertionError(f"unexpected {arm} triple row count")
    return selection_rows, baseline, arms


def parse_triple(encoded: str) -> tuple[int, int, int]:
    triple = tuple(int(x) for x in encoded.split(","))
    if len(triple) != 3 or tuple(sorted(triple)) != triple or len(set(triple)) != 3:
        raise AssertionError(f"invalid triple key: {encoded!r}")
    return triple  # type: ignore[return-value]


def q_of(selection: tuple[int, ...], probs: dict[tuple[int, int, int], float]) -> float:
    # Combinations are emitted in sorted lexical order, fixing the summand order.
    return math.fsum(probs[t] for t in itertools.combinations(selection, 3))


def distribution(group: pd.DataFrame, roster: tuple[int, ...], label: str) -> dict[tuple[int, int, int], float]:
    probs: dict[tuple[int, int, int], float] = {}
    roster_set = set(roster)
    for encoded, raw_p in group[["triple_numbers", "probability"]].itertuples(index=False, name=None):
        triple = parse_triple(str(encoded))
        p = float(raw_p)
        if not set(triple).issubset(roster_set) or not math.isfinite(p) or p < 0.0:
            raise AssertionError(f"invalid {label} triple or probability")
        if triple in probs:
            raise AssertionError(f"duplicate {label} triple: {triple}")
        probs[triple] = p
    if len(probs) != math.comb(len(roster), 3):
        raise AssertionError(f"{label} triple roster is incomplete")
    if not math.isclose(math.fsum(probs.values()), 1.0, rel_tol=0.0, abs_tol=1e-10):
        raise AssertionError(f"{label} probability mass differs from one")
    return probs


def optimize(roster: tuple[int, ...], probs: dict[tuple[int, int, int], float], baseline: tuple[int, ...]):
    scored = [(q_of(s, probs), s) for s in itertools.combinations(roster, 5)]
    maximum = max(q for q, _ in scored)
    tied = [(q, s) for q, s in scored if maximum - q <= TIE_TOL]
    base = set(baseline)
    selected_q, selected = min(tied, key=lambda x: (-len(set(x[1]) & base), x[1]))
    return selected, maximum, selected_q, len(tied)


def verify() -> dict[str, Any]:
    locked_rows, baseline_frame, arms = read_locked_inputs()
    selection_by_race = {row["race_id"]: row for row in locked_rows}
    base_by_race = {str(k): g for k, g in baseline_frame.groupby("race_id", sort=False)}
    arm_by_race = {
        arm: {str(k): g for k, g in frame.groupby("race_id", sort=False)}
        for arm, frame in arms.items()
    }
    if set(selection_by_race) != set(base_by_race):
        raise AssertionError("selection race IDs do not equal frozen baseline race IDs")

    changed = 0
    maximum_q_gap = 0.0
    maximum_replay_delta = 0.0
    max_tie_count = 0
    candidate_choice_counts: dict[int, int] = {}
    for race_id in sorted(base_by_race):
        b = base_by_race[race_id]
        stored = selection_by_race[race_id]
        if int(stored["field_n"]) != len(b):
            raise AssertionError(f"field size differs from frozen baseline in {race_id}")
        if int(stored["year"]) != int(b.year.iloc[0]) or int(stored["distance_m"]) != int(b.distance_m.iloc[0]):
            raise AssertionError(f"year/distance differs from frozen baseline in {race_id}")
        if b.horse_id.astype(str).duplicated().any() or b.horse_number.duplicated().any():
            raise AssertionError(f"baseline runner identity duplicated in {race_id}")
        roster = tuple(sorted(int(x) for x in b.horse_number))
        score_sorted = b.sort_values(["score", "horse_number"], ascending=[False, True], kind="stable")
        baseline_top5 = tuple(sorted(int(x) for x in score_sorted.horse_number.iloc[:5]))
        if tuple(stored["baseline_horse_numbers"]) != baseline_top5:
            raise AssertionError(f"locked baseline choice mismatch in {race_id}")
        candidate_probs = distribution(arm_by_race["candidate"][race_id], roster, "candidate")
        unary_probs = distribution(arm_by_race["matched_baseline"][race_id], roster, "matched_baseline")
        unary_selected, _, _, _ = optimize(roster, unary_probs, baseline_top5)
        if unary_selected != baseline_top5:
            raise AssertionError(f"matched unary negative control differs in {race_id}")
        selected, q_max, q_selected, tie_count = optimize(roster, candidate_probs, baseline_top5)
        locked_candidate = tuple(stored["candidate_horse_numbers"])
        if len(locked_candidate) != 5 or len(set(locked_candidate)) != 5 or tuple(sorted(locked_candidate)) != locked_candidate:
            raise AssertionError(f"locked candidate set is malformed in {race_id}")
        if locked_candidate != selected:
            raise AssertionError(f"independent candidate choice differs in {race_id}")
        gap = q_max - q_selected
        if gap < 0 or gap > TIE_TOL:
            raise AssertionError(f"selected q is outside the frozen tie tolerance in {race_id}")
        replay_q = q_of(selected, candidate_probs)
        locked_q = float(stored["candidate_q_selected"])
        locked_q_max = float(stored["candidate_q_max"])
        locked_q_gap = float(stored["candidate_q_gap_from_max"])
        locked_baseline_q = float(stored["candidate_q_on_baseline_top5"])
        if max(abs(q_max - locked_q_max), abs(gap - locked_q_gap),
               abs(q_of(baseline_top5, candidate_probs) - locked_baseline_q)) > 1e-15:
            raise AssertionError(f"locked utility values differ from independent recomputation in {race_id}")
        maximum_replay_delta = max(maximum_replay_delta, abs(replay_q - locked_q))
        maximum_q_gap = max(maximum_q_gap, gap)
        max_tie_count = max(max_tie_count, tie_count)
        changed += selected != baseline_top5
        candidate_choice_counts[len(selected)] = candidate_choice_counts.get(len(selected), 0) + 1

        # Reverse insertion order to confirm that source row order cannot change q.
        reversed_probs = dict(reversed(list(candidate_probs.items())))
        if q_of(selected, reversed_probs) != replay_q:
            raise AssertionError(f"probability row-order permutation changed q in {race_id}")

    if maximum_replay_delta > 1e-15:
        raise AssertionError(f"selected q replay differs from locked ledger: {maximum_replay_delta}")
    return {
        "status": "PASS_INDEPENDENT_LABEL_FREE_CHOICE_REPLAY",
        "selection_sha256": digest(SELECTIONS),
        "selection_receipt_sha256": digest(SELECTION_RECEIPT),
        "root_q_receipt_sha256": digest(ROOT_Q_RECEIPT),
        "selector_sha256": SELECTOR_SHA256,
        "outcome_labels_read": False,
        "races": len(locked_rows),
        "primary_distance_races": sum(int(row["distance_m"]) in PRIMARY_DISTANCES for row in locked_rows),
        "independent_candidate_choices_changed_from_baseline": changed,
        "all_choices_match_exhaustive_independent_argmax": True,
        "matched_unary_choices_equal_score_top5": True,
        "all_selected_q_values_replay_within_1e-15": True,
        "max_selected_q_replay_abs_delta": maximum_replay_delta,
        "max_q_gap_from_exact_max": maximum_q_gap,
        "max_candidate_optimal_tie_count": max_tie_count,
        "candidate_selected_count_distribution": candidate_choice_counts,
        "probability_row_order_invariance_checked": True,
    }


if __name__ == "__main__":
    result = verify()
    output = HERE / "INDEPENDENT_CHOICE_AUDIT.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))

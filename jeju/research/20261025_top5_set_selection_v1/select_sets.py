"""Select exactly five runners from frozen F1_STYLE6 and joint probabilities.

This stage intentionally reads no finishing labels. Source paths are fixed in
this study and every persistent output is created exclusively under outputs/.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"

BASELINE_REL = Path(
    "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/"
    "baseline_runner_predictions.parquet"
)
TRIPLES_REL = Path(
    "jeju/research/20261010_joint_relationship_v1/outputs/report/all_triples.parquet"
)
PARAMETERS_REL = Path(
    "jeju/research/20261010_joint_relationship_v1/outputs/fit_parameters.json"
)
FIT_RECEIPT_REL = Path(
    "jeju/research/20261010_joint_relationship_v1/outputs/fit_receipt.json"
)
REPORT_RECEIPT_REL = Path(
    "jeju/research/20261010_joint_relationship_v1/outputs/report/report_receipt.json"
)
SOURCE_LOCK_REL = Path(
    "jeju/research/20261010_joint_relationship_v1/outputs/source_lock.json"
)
BOOTSTRAP_REL = Path(
    "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
)
ROOT_Q_RECEIPT_REL = Path(
    "jeju/research/20261025_top5_set_rootreview_v1/ROOT_Q_RECONSTRUCTION.json"
)
ROOT_Q_RECONSTRUCTION_CODE_REL = Path(
    "jeju/research/20261025_top5_set_rootreview_v1/reconstruct_q.py"
)

EXPECTED_SHA256 = {
    str(BASELINE_REL): "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1",
    str(TRIPLES_REL): "13409e65353c0cb6dab14df97317cce24de913056ae464ee3524520759de681c",
    str(PARAMETERS_REL): "ff96e32cc4e0c991ac1326ef111a785b0e4f11b49daedc9f584be00dfe72eaeb",
    str(FIT_RECEIPT_REL): "8470f4d5848e12824511e3a6b03b2f481f760dcb7c433b59624894a8482b61dc",
    str(REPORT_RECEIPT_REL): "5720519b0d8860f5652650b4d2ee3b6f8444a6c6f01421395cd51f4a0251fae4",
    str(SOURCE_LOCK_REL): "4e5acda8590e8ab415be45333a8bd26f8894a390f411b33ce669e439d565fb61",
    str(BOOTSTRAP_REL): "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
    str(ROOT_Q_RECEIPT_REL): "f50e75f1815793fd4874bc36f38f80d64c4fd0192da2e89fb144b9ae7bae627a",
    str(ROOT_Q_RECONSTRUCTION_CODE_REL): "1e6c0f2b6b479273907328b3d32a6ffd903217afd445678dd684f7bc50fa04ec",
}
EXPECTED_PARAMETERS_SHA256 = EXPECTED_SHA256[str(PARAMETERS_REL)]
EXPECTED_REPORT_RECEIPT_SHA256 = EXPECTED_SHA256[str(REPORT_RECEIPT_REL)]
EXPECTED_CANDIDATE_TRIPLES_SHA256 = EXPECTED_SHA256[str(TRIPLES_REL)]
EXPECTED_BASELINE_SHA256 = EXPECTED_SHA256[str(BASELINE_REL)]
TOP5_TIE_TOLERANCE = 1e-12
CAREER_Q33 = 13.5
CAREER_Q67 = 26.5
PRIMARY_DISTANCES = {900, 1000, 1110, 1200}
EXPECTED_RACES = 1779
EXPECTED_RUNNERS = 17412


def confined_source(relative: Path) -> Path:
    """Resolve a fixed source path and keep it inside the repository root."""
    path = (ROOT / relative).resolve(strict=True)
    if not path.is_relative_to(ROOT):
        raise AssertionError(f"source escaped repository root: {relative}")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_fixed_sources() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for relative_text, expected in EXPECTED_SHA256.items():
        path = confined_source(Path(relative_text))
        actual = sha256_file(path)
        if actual != expected:
            raise AssertionError(f"source hash changed: {relative_text}")
        records[relative_text] = {
            "sha256": actual,
            "bytes": path.stat().st_size,
        }

    params = json.loads(confined_source(PARAMETERS_REL).read_text(encoding="utf-8"))
    fit_receipt = json.loads(confined_source(FIT_RECEIPT_REL).read_text(encoding="utf-8"))
    report_receipt = json.loads(confined_source(REPORT_RECEIPT_REL).read_text(encoding="utf-8"))
    source_lock = json.loads(confined_source(SOURCE_LOCK_REL).read_text(encoding="utf-8"))
    root_q_receipt = json.loads(confined_source(ROOT_Q_RECEIPT_REL).read_text(encoding="utf-8"))

    if params.get("study") != "20261010_joint_relationship_v1":
        raise AssertionError("unexpected joint relationship fit parameters")
    if params.get("fit_scope") != "H1 relationship coefficients and H2 matched temperatures; no base refit":
        raise AssertionError("unexpected fit scope")
    if params.get("source_hashes_unchanged_after_fit") is not True:
        raise AssertionError("frozen fit did not preserve its source hashes")
    if fit_receipt.get("passed") is not True or fit_receipt.get("base_model_fit_or_reload") is not False:
        raise AssertionError("frozen fit receipt is not a passing no-refit receipt")
    if fit_receipt.get("evaluation_outcome_metrics_computed") is not False:
        raise AssertionError("fit-stage receipt unexpectedly computed evaluation outcomes")
    if report_receipt.get("passed") is not True:
        raise AssertionError("frozen joint report receipt is not passing")
    if report_receipt.get("fit_parameters_sha256") != EXPECTED_PARAMETERS_SHA256:
        raise AssertionError("joint report does not reference the frozen parameters")
    if report_receipt.get("all_triples_sha256") != EXPECTED_CANDIDATE_TRIPLES_SHA256:
        raise AssertionError("joint report does not reference the frozen all-triples table")
    if source_lock.get("study") != "20261010_joint_relationship_v1":
        raise AssertionError("unexpected joint source lock")
    if len(source_lock.get("sources", {})) != 39:
        raise AssertionError("joint source lock has unexpected source count")
    if root_q_receipt.get("passed") is not True:
        raise AssertionError("root's independent Q reconstruction did not pass")
    if root_q_receipt.get("outcome_labels_read") is not False:
        raise AssertionError("root's independent Q reconstruction read outcome labels")
    if root_q_receipt.get("new_fits") != 0 or root_q_receipt.get("races") != EXPECTED_RACES:
        raise AssertionError("root's Q reconstruction fit/race contract changed")
    q_errors = root_q_receipt.get("max_abs_q_error", {})
    if any(
        not isinstance(q_errors.get(arm), (int, float))
        or not math.isfinite(float(q_errors[arm]))
        or float(q_errors[arm]) > 1e-12
        for arm in ("candidate", "matched_baseline")
    ):
        raise AssertionError("root's independently reconstructed Q exceeds tolerance")
    expected_root_sources = {
        str(BASELINE_REL): EXPECTED_BASELINE_SHA256,
        "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet":
            "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
        str(PARAMETERS_REL): EXPECTED_PARAMETERS_SHA256,
        str(TRIPLES_REL): EXPECTED_CANDIDATE_TRIPLES_SHA256,
    }
    if root_q_receipt.get("sources") != expected_root_sources:
        raise AssertionError("root's Q reconstruction source chain differs from the locked inputs")
    return records


def parse_triple(value: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split(","))
    except (AttributeError, TypeError, ValueError) as exc:
        raise AssertionError(f"invalid triple encoding: {value!r}") from exc
    if len(parts) != 3 or tuple(sorted(parts)) != parts or len(set(parts)) != 3:
        raise AssertionError(f"triple is not a sorted unique 3-number tuple: {value!r}")
    return parts  # type: ignore[return-value]


def choose_score_top5(group: pd.DataFrame) -> tuple[int, ...]:
    ordered = group.sort_values(
        ["score", "horse_number"], ascending=[False, True], kind="stable"
    )
    return tuple(sorted(int(number) for number in ordered.horse_number.iloc[:5]))


def q_value(numbers: tuple[int, ...], probabilities: dict[tuple[int, int, int], float]) -> float:
    triples = itertools.combinations(numbers, 3)
    return math.fsum(probabilities[triple] for triple in triples)


def choose_q_top5(
    runner_numbers: tuple[int, ...],
    probabilities: dict[tuple[int, int, int], float],
    baseline_top5: tuple[int, ...],
) -> tuple[tuple[int, ...], float, float]:
    values = [
        (q_value(selection, probabilities), selection)
        for selection in itertools.combinations(runner_numbers, 5)
    ]
    if not values:
        raise AssertionError("race has no five-runner selection")
    q_max = max(value for value, _ in values)
    eligible = [
        (value, selection)
        for value, selection in values
        if q_max - value <= TOP5_TIE_TOLERANCE
    ]
    baseline_set = set(baseline_top5)
    selected_q, selected = min(
        eligible,
        key=lambda item: (-len(set(item[1]) & baseline_set), item[1]),
    )
    gap = q_max - selected_q
    if gap < 0.0 or gap > TOP5_TIE_TOLERANCE:
        raise AssertionError("candidate selection exceeds the frozen q tie tolerance")
    return selected, selected_q, q_max


def assert_probability_arm(
    group: pd.DataFrame, runner_numbers: tuple[int, ...], race_id: str, arm: str
) -> dict[tuple[int, int, int], float]:
    probabilities: dict[tuple[int, int, int], float] = {}
    roster = set(runner_numbers)
    for row in group.itertuples(index=False):
        triple = parse_triple(row.triple_numbers)
        if not set(triple).issubset(roster):
            raise AssertionError(f"{arm} triple outside roster: {race_id} {triple}")
        value = float(row.probability)
        if not math.isfinite(value) or value < 0.0:
            raise AssertionError(f"invalid probability in {arm}: {race_id} {triple}")
        if triple in probabilities:
            raise AssertionError(f"duplicate triple in {arm}: {race_id} {triple}")
        probabilities[triple] = value
    expected_count = math.comb(len(runner_numbers), 3)
    if len(probabilities) != expected_count:
        raise AssertionError(
            f"{arm} triple count mismatch in {race_id}: {len(probabilities)} != {expected_count}"
        )
    total = math.fsum(probabilities.values())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-10):
        raise AssertionError(f"{arm} distribution mass mismatch in {race_id}: {total}")
    return probabilities


def load_selection_inputs() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    baseline_path = confined_source(BASELINE_REL)
    baseline = pd.read_parquet(
        baseline_path,
        columns=[
            "race_id", "race_date", "year", "distance_m", "horse_id",
            "horse_number", "field_n", "score", "variant", "observed_starts",
        ],
    )
    if len(baseline) != EXPECTED_RUNNERS or baseline.race_id.nunique() != EXPECTED_RACES:
        raise AssertionError("baseline cohort size changed")
    if set(baseline.variant.dropna().astype(str).unique()) != {"F1_STYLE6"}:
        raise AssertionError("baseline artifact is not exclusively frozen F1_STYLE6")
    if baseline[["race_id", "race_date", "year", "distance_m", "horse_id", "horse_number",
                 "field_n", "score", "observed_starts"]].isna().any().any():
        raise AssertionError("baseline selection inputs contain missing values")
    if not np.isfinite(baseline.score.to_numpy(dtype="float64")).all():
        raise AssertionError("non-finite baseline score")
    if not np.isfinite(baseline.observed_starts.to_numpy(dtype="float64")).all():
        raise AssertionError("non-finite pre-race career count")

    triples_path = confined_source(TRIPLES_REL)
    required_columns = [
        "race_id", "evaluation_year", "distance_m", "arm", "triple_numbers", "probability"
    ]
    candidate = pq.read_table(
        triples_path,
        columns=[column for column in required_columns if column != "arm"],
        filters=[("arm", "=", "candidate")],
    ).to_pandas()
    matched = pq.read_table(
        triples_path,
        columns=[column for column in required_columns if column != "arm"],
        filters=[("arm", "=", "matched_baseline")],
    ).to_pandas()
    if set(candidate.race_id.astype(str)) != set(baseline.race_id.astype(str)):
        raise AssertionError("candidate probability race roster differs from F1_STYLE6 baseline")
    if set(matched.race_id.astype(str)) != set(baseline.race_id.astype(str)):
        raise AssertionError("matched-baseline probability race roster differs from F1_STYLE6 baseline")
    return baseline, {"candidate": candidate, "matched_baseline": matched}


def race_rows(baseline: pd.DataFrame, arms: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    by_arm_race = {
        arm: {str(race_id): group for race_id, group in frame.groupby("race_id", sort=False)}
        for arm, frame in arms.items()
    }
    output: list[dict[str, Any]] = []
    seen_races: set[str] = set()
    for race_id, raw_group in baseline.groupby("race_id", sort=True, observed=True):
        race_id = str(race_id)
        if race_id in seen_races:
            raise AssertionError(f"duplicate baseline race ID: {race_id}")
        seen_races.add(race_id)
        group = raw_group.copy()
        if group.horse_id.astype(str).duplicated().any() or group.horse_number.duplicated().any():
            raise AssertionError(f"duplicate runner identity in {race_id}")
        field_sizes = group.field_n.astype(int).unique()
        if len(field_sizes) != 1 or len(group) != int(field_sizes[0]) or len(group) < 5:
            raise AssertionError(f"invalid field size in {race_id}")
        runner_numbers = tuple(sorted(group.horse_number.astype(int).tolist()))
        baseline_top5 = choose_score_top5(group)
        id_by_number = {
            int(row.horse_number): str(row.horse_id)
            for row in group[["horse_number", "horse_id"]].itertuples(index=False)
        }
        date_values = group.race_date.astype(str).unique()
        year_values = group.year.astype(int).unique()
        distance_values = group.distance_m.astype(float).unique()
        if len(date_values) != 1 or len(year_values) != 1 or len(distance_values) != 1:
            raise AssertionError(f"inconsistent race metadata in {race_id}")
        year = int(year_values[0])
        distance = float(distance_values[0])
        if not distance.is_integer():
            raise AssertionError(f"non-integer race distance in {race_id}")
        distance = int(distance)
        career_median = float(group.observed_starts.astype(float).median())
        career_stratum = (
            "lower" if career_median <= CAREER_Q33
            else "middle" if career_median <= CAREER_Q67
            else "upper"
        )
        if year not in (2024, 2025, 2026):
            raise AssertionError(f"unexpected evaluation year in {race_id}: {year}")

        distribution_by_arm: dict[str, dict[tuple[int, int, int], float]] = {}
        for arm in ("candidate", "matched_baseline"):
            arm_group = by_arm_race[arm].get(race_id)
            if arm_group is None:
                raise AssertionError(f"missing {arm} distribution for {race_id}")
            if set(arm_group.evaluation_year.astype(int).unique()) != {year}:
                raise AssertionError(f"year mismatch between {arm} and baseline in {race_id}")
            if set(arm_group.distance_m.astype(int).unique()) != {distance}:
                raise AssertionError(f"distance mismatch between {arm} and baseline in {race_id}")
            distribution_by_arm[arm] = assert_probability_arm(
                arm_group, runner_numbers, race_id, arm
            )

        matched_selection, _, _ = choose_q_top5(
            runner_numbers, distribution_by_arm["matched_baseline"], baseline_top5
        )
        if matched_selection != baseline_top5:
            raise AssertionError(f"unary matched-baseline negative control differs in {race_id}")

        candidate_selection, q_selected, q_max = choose_q_top5(
            runner_numbers, distribution_by_arm["candidate"], baseline_top5
        )
        q_baseline = q_value(baseline_top5, distribution_by_arm["candidate"])
        output.append({
            "race_id": race_id,
            "race_date": str(date_values[0]),
            "year": year,
            "distance_m": distance,
            "field_n": len(group),
            "career_median_observed_starts": career_median,
            "career_stratum": career_stratum,
            "baseline_horse_numbers": list(baseline_top5),
            "baseline_horse_ids": [id_by_number[number] for number in baseline_top5],
            "candidate_horse_numbers": list(candidate_selection),
            "candidate_horse_ids": [id_by_number[number] for number in candidate_selection],
            "candidate_q_on_baseline_top5": q_baseline,
            "candidate_q_max": q_max,
            "candidate_q_selected": q_selected,
            "candidate_q_gap_from_max": q_max - q_selected,
            "primary_distance": distance in PRIMARY_DISTANCES,
        })
    if seen_races != set(baseline.race_id.astype(str).unique()):
        raise AssertionError("race iteration did not cover the baseline cohort exactly")
    if len(output) != EXPECTED_RACES:
        raise AssertionError("unexpected selection ledger race count")
    return output


def write_text_exclusive(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def main() -> None:
    selection_path = OUT / "selections.jsonl"
    receipt_path = OUT / "selection_receipt.json"
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if selection_path.exists() or receipt_path.exists():
        raise FileExistsError("selection outputs already exist; refusing to overwrite")

    sources = verify_fixed_sources()
    baseline, arms = load_selection_inputs()
    rows = race_rows(baseline, arms)
    content = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    write_text_exclusive(selection_path, content)
    receipt = {
        "status": "PASS_LABEL_FREE_SELECTION",
        "study": "20261025_top5_set_selection_v1",
        "selection_stage_reads_outcome_labels": False,
        "selector_code_sha256": sha256_file(Path(__file__).resolve()),
        "source_artifacts": sources,
        "selection_artifact": {
            "path": str(selection_path.relative_to(ROOT)),
            "sha256": sha256_file(selection_path),
            "bytes": selection_path.stat().st_size,
            "races": len(rows),
            "primary_distance_races": sum(bool(row["primary_distance"]) for row in rows),
        },
        "candidate_model": {
            "study": "20261010_joint_relationship_v1",
            "fit_parameters_sha256": EXPECTED_PARAMETERS_SHA256,
            "all_triples_sha256": EXPECTED_CANDIDATE_TRIPLES_SHA256,
            "candidate_arm_rows": int(len(arms["candidate"])),
            "matched_baseline_arm_rows": int(len(arms["matched_baseline"])),
            "matched_baseline_unary_negative_control": "PASS all races equal score top5",
        },
        "contract": {
            "selected_runner_count": 5,
            "primary_distances_m": sorted(PRIMARY_DISTANCES),
            "candidate_set_objective": "sum candidate probability over all unordered exact Top3 subsets",
            "q_tie_absolute_tolerance": TOP5_TIE_TOLERANCE,
            "q_tie_resolution": "maximum overlap with score top5, then ascending horse-number tuple",
            "baseline_order": "raw score descending, horse number ascending",
            "career_strata_from_field_median_observed_starts": {
                "lower_max_inclusive": CAREER_Q33,
                "middle_max_inclusive": CAREER_Q67,
            },
        },
    }
    write_text_exclusive(
        receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "status": receipt["status"],
        "races": len(rows),
        "primary_races": receipt["selection_artifact"]["primary_distance_races"],
        "selection_bytes": selection_path.stat().st_size,
        "receipt_sha256": sha256_file(receipt_path),
    }, sort_keys=True))


if __name__ == "__main__":
    main()

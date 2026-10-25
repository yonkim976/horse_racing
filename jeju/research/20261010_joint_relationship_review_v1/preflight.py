"""Read-only audit of frozen F1_STYLE6 sources and joint-plan preflight gates.

This file deliberately uses only fixed repository paths. It does not fit a model,
compute new outcome-based performance metrics, connect to a database, or write
outside this review folder. Roster/score columns are read only as needed for
source-key, time-boundary, and zero-residual parity checks.
"""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256 as new_sha256
from itertools import combinations
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
COMBO = ROOT / "jeju/research/20261010_probability_combo_gap_v1"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
BASE = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
IMPLEMENTATION = ROOT / "jeju/research/20261010_joint_relationship_v1"
OUTPUT = HERE / "outputs/initial_preflight.json"
YEARS = (2024, 2025, 2026)
APPROVED_PLAN_SHA256 = "e0a34c6962112d88bfec7e645efbd8e4ea69bf4aada088f580e1188bac1207f3"


def require_within_root(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    resolved.relative_to(ROOT)
    return resolved


def file_sha256(path: Path) -> str:
    path = require_within_root(path)
    digest = new_sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    path = require_within_root(path)
    return json.loads(path.read_text(encoding="utf-8"))


def record_hash(path: Path, expected: str | None, source: str, records: dict) -> None:
    rel = str(path.relative_to(ROOT))
    actual = file_sha256(path)
    if expected is not None:
        assert actual == expected, f"SHA-256 mismatch: {rel}"
    records[rel] = {
        "expected_sha256": expected,
        "actual_sha256": actual,
        "matched": expected is None or actual == expected,
        "expected_source": source,
        "bytes": path.stat().st_size,
    }


def source_hash_audit() -> dict:
    combo_lock_path = COMBO / "outputs/source_lock.json"
    combo_manifest_path = COMBO / "ARTIFACT_MANIFEST.json"
    style_manifest_path = STYLE / "ARTIFACT_MANIFEST.json"
    combo_lock = read_json(combo_lock_path)
    combo_manifest = read_json(combo_manifest_path)
    style_manifest = read_json(style_manifest_path)
    style_prepared_lock = read_json(STYLE / "outputs/prepared_lock.json")
    files: dict[str, dict] = {}

    fixed = {
        COMBO / "PLAN.md": combo_lock["plan_sha256"],
        COMBO / "data_contract.json": combo_lock["data_contract_sha256"],
        COMBO / "analyze.py": combo_lock["analysis_code_sha256"],
        combo_lock_path: combo_manifest["approved_locks"]["source_lock_sha256"],
        STYLE / "ARTIFACT_MANIFEST.json": combo_lock["artifact_manifest_sha256"],
        STYLE / "outputs/prepared_lock.json": combo_lock["prepared_lock_sha256"],
        BASE / "outputs/prepared_lock.json": combo_lock["baseline_lock_sha256"],
        STYLE / "outputs/f1_reproduced_runner_predictions.parquet": combo_lock[
            "source_files"
        ][str((STYLE / "outputs/f1_reproduced_runner_predictions.parquet").relative_to(ROOT))][
            "sha256"
        ],
        STYLE / "outputs/f1_reproduced_six_combinations.csv": combo_lock[
            "source_files"
        ][str((STYLE / "outputs/f1_reproduced_six_combinations.csv").relative_to(ROOT))][
            "sha256"
        ],
        STYLE / "outputs/report/canonical_six_combinations.csv": combo_lock[
            "source_files"
        ][str((STYLE / "outputs/report/canonical_six_combinations.csv").relative_to(ROOT))][
            "sha256"
        ],
        STYLE / "outputs/features.parquet": style_prepared_lock["artifacts"]["features.parquet"],
    }

    for path, expected in fixed.items():
        record_hash(path, expected, "probability_combo_gap locks/manifests", files)

    for year in YEARS:
        prefix = STYLE / f"outputs/F1_STYLE6_{year}"
        for name in ("top3.txt", "meta.json", "evaluation_scores.parquet", "calibration_scores.parquet"):
            path = prefix / name
            rel = str(path.relative_to(ROOT))
            expected = style_manifest["study_artifacts"][rel]["sha256"]
            record_hash(path, expected, "STYLE6 ARTIFACT_MANIFEST.json", files)

        baseline_prefix = BASE / f"outputs/F1_{year}"
        for name in ("top3.txt", "meta.json"):
            path = baseline_prefix / name
            rel = str(path.relative_to(ROOT))
            expected = combo_lock["source_files"][rel]["sha256"]
            record_hash(path, expected, "probability_combo_gap source_lock.json", files)

    plan_path = IMPLEMENTATION / "PLAN.md"
    record_hash(plan_path, APPROVED_PLAN_SHA256, "root-approved final plan hash", files)
    source_availability = IMPLEMENTATION / "SOURCE_AVAILABILITY.md"
    observed_source_availability = {
        "observed_sha256": file_sha256(source_availability),
        "bytes": source_availability.stat().st_size,
        "status": "observed_for_preflight_context",
    }

    return {
        "locked_files": files,
        "root_approved_implementation_plan": {
            "path": str(plan_path.relative_to(ROOT)),
            "expected_sha256": APPROVED_PLAN_SHA256,
            "actual_sha256": files[str(plan_path.relative_to(ROOT))]["actual_sha256"],
        },
        "source_availability_note": observed_source_availability,
    }


def pair_projection(phi: np.ndarray) -> np.ndarray:
    """Project a symmetric complete-graph pair vector off all a_i + a_j terms."""
    n = phi.shape[0]
    assert phi.shape == (n, n) and n >= 3
    assert np.allclose(phi, phi.T, rtol=0, atol=0)
    assert np.allclose(np.diag(phi), 0.0, rtol=0, atol=0)
    degrees = phi.sum(axis=1)
    total = float(np.triu(phi, 1).sum())
    unary = (degrees - total / (n - 1)) / (n - 2)
    projected = np.zeros_like(phi, dtype=np.float64)
    for i in range(n):
        for j in range(i + 1, n):
            projected[i, j] = projected[j, i] = phi[i, j] - unary[i] - unary[j]
    return projected


def projection_negative_controls() -> dict:
    n = 7
    unary = np.asarray([-0.4, 0.2, 1.1, -0.7, 0.5, 0.9, -0.1], dtype=np.float64)
    additive = unary[:, None] + unary[None, :]
    np.fill_diagonal(additive, 0.0)
    additive_residual = pair_projection(additive)

    genuinely_pair = additive.copy()
    genuinely_pair[0, 1] += 0.75
    genuinely_pair[1, 0] += 0.75
    pair_residual = pair_projection(genuinely_pair)
    additive_max = float(np.max(np.abs(np.triu(additive_residual, 1))))
    pair_norm = float(np.linalg.norm(np.triu(pair_residual, 1)))
    assert additive_max <= 1e-12
    assert pair_norm > 1e-6
    # Check the plan's triple-level orthogonality claim with an independent
    # incidence construction, not with implementation helpers.
    triples = list(combinations(range(n), 3))
    incidence = np.zeros((len(triples), n), dtype=np.float64)
    triple_pair_sum = np.zeros(len(triples), dtype=np.float64)
    for row, triple in enumerate(triples):
        incidence[row, list(triple)] = 1.0
        triple_pair_sum[row] = sum(pair_residual[i, j] for i, j in combinations(triple, 2))
    unary_incidence_max = float(np.max(np.abs(incidence.T @ triple_pair_sum)))
    assert unary_incidence_max <= 1e-12
    return {
        "scope": "synthetic math-only negative control; no new outcome performance metrics computed",
        "unary_additive_max_abs_projection_residual": additive_max,
        "single_pair_perturbation_projection_residual_l2": pair_norm,
        "projected_triple_pair_sum_max_abs_runner_incidence_inner_product": unary_incidence_max,
        "unary_term_projects_to_zero": True,
        "genuine_pair_perturbation_survives_projection": True,
        "projected_triple_term_is_unary_incidence_orthogonal": True,
    }


def parse_ticket_numbers(value: str) -> tuple[int, int, int]:
    result = tuple(int(part.strip()) for part in str(value).split(","))
    assert len(result) == 3 and tuple(sorted(result)) == result
    return result


def cohort_and_zero_residual_audit() -> dict:
    runner_path = STYLE / "outputs/f1_reproduced_runner_predictions.parquet"
    features_path = STYLE / "outputs/features.parquet"
    tickets_path = STYLE / "outputs/report/canonical_six_combinations.csv"

    # Intentionally omit y, finish_position, hit, probability, and all post-race columns.
    runner_columns = [
        "api_record_id", "race_id", "race_date", "year", "distance_m",
        "horse_id", "horse_number", "field_n",
    ]
    feature_columns = [
        "api_record_id", "race_id", "race_date", "year", "distance_m",
        "horse_id", "horse_number", "field_n",
    ]
    base = pd.read_parquet(require_within_root(runner_path), columns=runner_columns)
    features = pd.read_parquet(require_within_root(features_path), columns=feature_columns)
    tickets = pd.read_csv(
        require_within_root(tickets_path),
        usecols=["race_id", "variant", "selection_rank", "numbers"],
        dtype={"race_id": "string", "variant": "string", "numbers": "string"},
    )

    assert len(base) == 17_412 and base.api_record_id.is_unique
    assert base.race_id.nunique() == 1_779 and base.race_date.nunique() == 269
    assert set(base.year.astype(int).unique()) == set(YEARS)
    assert not base.duplicated(["race_id", "horse_id"]).any()
    assert not base.duplicated(["race_id", "horse_number"]).any()
    base["race_date"] = pd.to_datetime(base.race_date).dt.strftime("%Y-%m-%d")
    features["race_date"] = pd.to_datetime(features.race_date).dt.strftime("%Y-%m-%d")
    assert features.api_record_id.is_unique
    assert features.race_date.notna().all()

    # Verify the frozen evaluation roster against the prepared F1_STYLE6 feature keys.
    eval_features = features.loc[features.year.astype(int).isin(YEARS)].copy()
    assert len(eval_features) == 17_412 and eval_features.race_id.nunique() == 1_779
    base_by_id = base.set_index("api_record_id").sort_index()
    features_by_id = eval_features.set_index("api_record_id").sort_index()
    assert base_by_id.index.equals(features_by_id.index)
    alignment_columns = ["race_id", "race_date", "year", "distance_m", "horse_id", "horse_number", "field_n"]
    for column in alignment_columns:
        assert base_by_id[column].astype(str).equals(features_by_id[column].astype(str)), column

    per_race = base.groupby("race_id", sort=False)
    race_sizes = per_race.size()
    assert per_race.field_n.nunique().eq(1).all()
    assert race_sizes.eq(per_race.field_n.first()).all()
    min_field = int(race_sizes.min())
    max_field = int(race_sizes.max())
    assert min_field >= 5, "C(N,3) < 6 for at least one frozen evaluation race"

    style_tickets = tickets.loc[tickets.variant.eq("F1_STYLE6")].copy()
    assert len(style_tickets) == 10_674
    assert style_tickets.race_id.nunique() == 1_779
    assert style_tickets.groupby("race_id").size().eq(6).all()
    assert not style_tickets.duplicated(["race_id", "selection_rank"]).any()
    assert style_tickets.groupby("race_id").selection_rank.apply(
        lambda values: sorted(values.astype(int).tolist()) == [1, 2, 3, 4, 5, 6]
    ).all()

    ticket_index = {
        str(race_id): [
            parse_ticket_numbers(value)
            for value in group.sort_values("selection_rank", kind="stable").numbers.tolist()
        ]
        for race_id, group in style_tickets.groupby("race_id", sort=False)
    }

    direct_ticket_rows = 0
    races_exact = 0
    exact_energy_ties = 0
    tie_races = 0
    triple_count = 0
    chosen_count_by_field: dict[str, int] = {}
    eval_meta = {}

    for year in YEARS:
        folder = STYLE / f"outputs/F1_STYLE6_{year}"
        meta = read_json(folder / "meta.json")
        score_path = folder / "evaluation_scores.parquet"
        scores = pd.read_parquet(require_within_root(score_path), columns=["api_record_id", "score"])
        assert int(meta["evaluation_year"]) == year
        assert len(scores) == int(meta["evaluation_rows"])
        assert scores.api_record_id.is_unique and scores.score.map(np.isfinite).all()
        year_base = base.loc[base.year.astype(int).eq(year)].copy()
        score_ids = set(scores.api_record_id.astype("int64"))
        base_ids = set(year_base.api_record_id.astype("int64"))
        assert score_ids == base_ids
        score_map = scores.set_index("api_record_id").score
        assert year_base.race_id.nunique() == int(meta["evaluation_races"])
        assert year_base.race_date.min() == meta["evaluation_min"]
        assert year_base.race_date.max() == meta["evaluation_max"]

        for race_id, input_group in year_base.groupby("race_id", sort=False):
            group = input_group.sort_values("horse_number", kind="stable").reset_index(drop=True)
            n = len(group)
            assert n >= 5
            assert group.horse_number.is_monotonic_increasing
            keys = group.api_record_id.astype("int64").tolist()
            runner_scores = score_map.reindex(keys).to_numpy(dtype=np.float64)
            assert np.isfinite(runner_scores).all()
            combos = np.asarray(list(combinations(range(n), 3)), dtype=np.int64)
            assert len(combos) == n * (n - 1) * (n - 2) // 6
            assert len(combos) >= 6
            energies = np.sort(runner_scores[combos], axis=1).sum(axis=1)
            order = np.argsort(-energies, kind="stable")
            selected = [tuple(int(group.horse_number.iloc[i]) for i in combos[j]) for j in order[:6]]
            rid = str(race_id)
            assert selected == ticket_index[rid], f"zero-residual canonical-six parity failed: {rid}"
            direct_ticket_rows += len(selected)
            races_exact += 1
            triple_count += len(combos)
            counts = np.unique(energies, return_counts=True)[1]
            tied_groups = int(np.count_nonzero(counts > 1))
            exact_energy_ties += tied_groups
            tie_races += int(tied_groups > 0)
            chosen_count_by_field[str(n)] = chosen_count_by_field.get(str(n), 0) + len(selected)

        eval_meta[str(year)] = {
            "evaluation_rows": len(scores),
            "evaluation_races": year_base.race_id.nunique(),
            "evaluation_min": str(year_base.race_date.min()),
            "evaluation_max": str(year_base.race_date.max()),
            "score_keys_exact_match_frozen_runner_ids": True,
            "zero_residual_six_ticket_races_exact": int(year_base.race_id.nunique()),
        }

    assert direct_ticket_rows == 10_674 and races_exact == 1_779
    return {
        "frozen_cohort": {
            "rows": len(base),
            "races": base.race_id.nunique(),
            "race_days": base.race_date.nunique(),
            "date_min": str(base.race_date.min()),
            "date_max": str(base.race_date.max()),
            "field_n_min": min_field,
            "field_n_max": max_field,
            "races_with_C_N_3_less_than_six": int((race_sizes < 5).sum()),
            "field_size_matches_started_runner_rows": True,
            "feature_key_roster_alignment": True,
        },
        "evaluation_folds": eval_meta,
        "all_unordered_triples_in_evaluation_cohort": triple_count,
        "canonical_six": {
            "rows": direct_ticket_rows,
            "races_exactly_six": races_exact,
            "stable_order_and_tickets_match_frozen_F1_STYLE6": True,
            "races_with_exact_energy_ties": tie_races,
            "exact_tie_groups_across_races": exact_energy_ties,
            "selected_rows_by_field_size": chosen_count_by_field,
        },
        "columns_read_for_roster_and_selection": runner_columns,
        "outcome_columns_loaded": [],
        "new_outcome_performance_metrics_computed": False,
    }


def calibration_split_audit() -> dict:
    features_path = STYLE / "outputs/features.parquet"
    # Deliberately omit finish_position and all post-race labels.
    columns = ["api_record_id", "race_id", "race_date", "year", "field_n", "horse_id", "horse_number"]
    features = pd.read_parquet(require_within_root(features_path), columns=columns)
    features["race_date"] = pd.to_datetime(features.race_date).dt.strftime("%Y-%m-%d")
    assert features.api_record_id.is_unique
    race_dates_per_race = features.groupby("race_id", sort=False).race_date.nunique()
    assert race_dates_per_race.eq(1).all()
    feature_index = features.set_index("api_record_id", drop=False)

    fold_records = {}
    for eval_year in YEARS:
        folder = STYLE / f"outputs/F1_STYLE6_{eval_year}"
        meta = read_json(folder / "meta.json")
        cal_year = eval_year - 1
        cal_scores = pd.read_parquet(
            require_within_root(folder / "calibration_scores.parquet"),
            columns=["api_record_id", "score"],
        )
        assert cal_scores.api_record_id.is_unique
        assert cal_scores.score.map(np.isfinite).all()
        ids = cal_scores.api_record_id.astype("int64")
        assert ids.isin(feature_index.index).all()
        joined = feature_index.loc[ids].copy()
        assert joined.api_record_id.astype("int64").tolist() == ids.tolist()
        assert joined.year.astype(int).eq(cal_year).all()
        assert len(joined) == int(meta["calibration_rows"])
        assert joined.race_id.nunique() == int(meta["calibration_races"])
        joined["race_date"] = joined.race_date.astype(str)
        assert str(joined.race_date.min()) == meta["calibration_min"]
        assert str(joined.race_date.max()) == meta["calibration_max"]

        h1_initial = joined.loc[joined.race_date.str.slice(0, 10) <= f"{cal_year}-06-30"]
        h2 = joined.loc[joined.race_date.str.slice(0, 10) >= f"{cal_year}-07-01"]
        assert not h1_initial.empty and not h2.empty
        h2_min = date.fromisoformat(str(h2.race_date.min()))
        h1_cutoff = h2_min - timedelta(days=2)
        h1 = h1_initial.loc[h1_initial.race_date <= h1_cutoff.isoformat()]
        purged = h1_initial.loc[h1_initial.race_date > h1_cutoff.isoformat()]
        assert not h1.empty
        expected_split = {
            2024: {"H1_races": 312, "H2_races": 336, "purged_races": 9, "H1_max": "2023-06-24", "H2_min": "2023-07-01", "min_field": 8},
            2025: {"H1_races": 326, "H2_races": 311, "purged_races": 0, "H1_max": "2024-06-29", "H2_min": "2024-07-05", "min_field": 8},
            2026: {"H1_races": 329, "H2_races": 325, "purged_races": 0, "H1_max": "2025-06-28", "H2_min": "2025-07-04", "min_field": 7},
        }[eval_year]
        for block in (h1, purged, h2):
            block_sizes = block.groupby("race_id", sort=False).size()
            block_field_n = block.groupby("race_id", sort=False).field_n.first()
            assert block_sizes.index.equals(block_field_n.index)
            assert np.array_equal(block_sizes.to_numpy(), block_field_n.astype(int).to_numpy())
        h1_min_field = int(h1.groupby("race_id", sort=False).size().min())
        h2_min_field = int(h2.groupby("race_id", sort=False).size().min())

        refit_max = date.fromisoformat(str(meta["refit_max"]))
        h1_min = date.fromisoformat(str(h1.race_date.min()))
        h1_max = date.fromisoformat(str(h1.race_date.max()))
        h2_max = date.fromisoformat(str(h2.race_date.max()))
        eval_first = date.fromisoformat(str(meta["evaluation_min"]))
        assert h1.race_id.nunique() == expected_split["H1_races"]
        assert h2.race_id.nunique() == expected_split["H2_races"]
        assert purged.race_id.nunique() == expected_split["purged_races"]
        assert h1_max.isoformat() == expected_split["H1_max"]
        assert h2_min.isoformat() == expected_split["H2_min"]
        assert min(h1_min_field, h2_min_field) == expected_split["min_field"]
        refit_gap = (h1_min - refit_max).days
        h1_h2_gap = (h2_min - h1_max).days
        h2_eval_gap = (eval_first - h2_max).days
        assert refit_gap >= 2, f"refit-to-H1 T-2 gap failed: {eval_year}"
        assert h1_h2_gap >= 2, f"H1-to-H2 T-2 purge failed: {eval_year}"
        assert h2_eval_gap >= 2, f"H2-to-evaluation T-2 gap failed: {eval_year}"

        # Every race/day remains wholly in one calendar segment; the purge is race-wide.
        assert h1.race_id.isin(h1_initial.race_id).all()
        assert purged.race_id.isin(h1_initial.race_id).all()
        assert not set(h1.race_id.astype(str)) & set(purged.race_id.astype(str))
        assert not set(h1.race_date.astype(str)) & set(h2.race_date.astype(str))
        assert not set(purged.race_date.astype(str)) & set(h2.race_date.astype(str))

        fold_records[str(eval_year)] = {
            "model_evaluation_year": eval_year,
            "calibration_year": cal_year,
            "refit_max": refit_max.isoformat(),
            "calibration_min": str(joined.race_date.min()),
            "calibration_max": str(joined.race_date.max()),
            "H1_calendar_rule": f"{cal_year}-01-01 through {cal_year}-06-30",
            "H2_calendar_rule": f"{cal_year}-07-01 through {cal_year}-12-31",
            "H1_min_after_purge": h1_min.isoformat(),
            "H1_max_after_purge": h1_max.isoformat(),
            "H2_min": h2_min.isoformat(),
            "H2_max": h2_max.isoformat(),
            "H2_min_minus_2d_H1_cutoff": h1_cutoff.isoformat(),
            "H1_rows_after_purge": len(h1),
            "H1_races_after_purge": h1.race_id.nunique(),
            "H1_days_after_purge": h1.race_date.nunique(),
            "H1_field_n_min_after_purge": h1_min_field,
            "H1_rows_purged": len(purged),
            "H1_races_purged": purged.race_id.nunique(),
            "H1_days_purged": purged.race_date.nunique(),
            "H2_rows": len(h2),
            "H2_races": h2.race_id.nunique(),
            "H2_days": h2.race_date.nunique(),
            "H2_field_n_min": h2_min_field,
            "next_evaluation_first_date": eval_first.isoformat(),
            "refit_to_H1_calendar_days": refit_gap,
            "H1_to_H2_calendar_days": h1_h2_gap,
            "H2_to_evaluation_calendar_days": h2_eval_gap,
            "all_three_T_minus_2_gates_pass": True,
            "race_date_grouping_preserved": True,
            "outcome_columns_loaded": [],
            "new_outcome_performance_metrics_computed": False,
        }

    return {"folds": fold_records, "new_outcome_performance_metrics_computed": False}


def main() -> None:
    assert not OUTPUT.exists(), f"refusing to overwrite existing receipt: {OUTPUT}"
    source_hashes = source_hash_audit()
    cohort = cohort_and_zero_residual_audit()
    splits = calibration_split_audit()
    negative_controls = projection_negative_controls()

    # Verify locked inputs remained unchanged while this read-only preflight ran.
    source_hashes_after = source_hash_audit()
    for rel, before in source_hashes["locked_files"].items():
        after = source_hashes_after["locked_files"][rel]
        assert before["actual_sha256"] == after["actual_sha256"], f"input changed during preflight: {rel}"
        before["sha256_unchanged_through_preflight"] = True
    assert (
        source_hashes["source_availability_note"]
        == source_hashes_after["source_availability_note"]
    ), "source availability note changed during preflight"
    source_hashes["source_availability_note_after"] = source_hashes_after[
        "source_availability_note"
    ]

    payload = {
        "status": "PASS",
        "scope": "source/hash/key/time-window and synthetic-structure checks only; no model fit or new outcome-based performance metrics",
        "reviewer_script_sha256": file_sha256(Path(__file__)),
        "source_hash_audit": source_hashes,
        "cohort_and_zero_residual_canonical_parity": cohort,
        "calibration_time_split_and_purge": splits,
        "pair_projection_negative_controls": negative_controls,
        "candidate_pair_model_fit": False,
        "new_outcome_performance_metrics_computed": False,
        "database_or_network_access": False,
        "central_or_operational_writes": False,
    }
    output_parent = OUTPUT.parent.resolve()
    output_parent.relative_to(ROOT)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "status": payload["status"],
        "receipt": str(OUTPUT.relative_to(ROOT)),
        "reviewer_script_sha256": payload["reviewer_script_sha256"],
        "races": cohort["frozen_cohort"]["races"],
        "field_n_min": cohort["frozen_cohort"]["field_n_min"],
        "zero_residual_ticket_parity": cohort["canonical_six"]["stable_order_and_tickets_match_frozen_F1_STYLE6"],
        "T_minus_2_gates": {
            year: record["all_three_T_minus_2_gates_pass"]
            for year, record in splits["folds"].items()
        },
        "candidate_fit": payload["candidate_pair_model_fit"],
        "new_outcome_performance_metrics": payload["new_outcome_performance_metrics_computed"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

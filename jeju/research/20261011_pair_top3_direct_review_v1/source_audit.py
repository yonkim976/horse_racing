"""Independent read-only source and prefit structure audit for direct pair Top3."""
from __future__ import annotations

from datetime import date
from itertools import combinations
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
OUT = ROOT / "jeju/research/20261011_pair_top3_direct_review_v1/outputs"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
JOINT = ROOT / "jeju/research/20261010_joint_relationship_v1"
PAIR_AXIS = ROOT / "jeju/research/20261010_pair_axis_v1"
TOL = 1e-12

MEANS = {
    "hist_s1f_relpos_mean5": "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5": "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5": "hist_c4_to_g1f_pair_n",
}
EXPECTED_COHORT = {2024: (6329, 637), 2025: (6410, 654), 2026: (4673, 488)}
EXPECTED_SPLITS = {2024: (312, 336), 2025: (326, 311), 2026: (329, 325)}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inside_root(relative: str) -> Path:
    candidate = (ROOT / relative).resolve(strict=True)
    if not candidate.is_relative_to(ROOT):
        raise ValueError(f"source escapes repository root: {relative}")
    return candidate


def contract_hashes(path: Path) -> dict[str, str]:
    refs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = [part.strip().strip("`") for part in line.split("|") if part.strip()]
        if len(parts) < 3:
            continue
        rel = parts[1]
        digest_match = next((re.fullmatch(r"[0-9a-f]{64}", part) for part in parts[2:]
                             if re.fullmatch(r"[0-9a-f]{64}", part)), None)
        if digest_match and rel.startswith("jeju/"):
            refs[rel] = digest_match.group(0)
    return refs


def canonical_top2(numbers: list[int], scores: list[float]) -> tuple[int, int]:
    order = sorted(range(len(numbers)), key=lambda i: (-scores[i], numbers[i]))[:2]
    return tuple(sorted(numbers[i] for i in order))


def p0_max_pair(numbers: list[int], scores: list[float]) -> tuple[int, int]:
    triples = list(combinations(range(len(numbers)), 3))
    energies = [math.fsum(scores[i] for i in triple) for triple in triples]
    peak = max(energies)
    weights = [math.exp(value - peak) for value in energies]
    normalizer = math.fsum(weights)
    q = [weight / normalizer for weight in weights]
    terms: dict[tuple[int, int], list[float]] = {
        pair: [] for pair in combinations(range(len(numbers)), 2)
    }
    for triple, probability in zip(triples, q, strict=True):
        for i, j in combinations(triple, 2):
            terms[(i, j)].append(probability)
    masses = {
        pair: math.fsum(probabilities)
        for pair, probabilities in terms.items()
    }
    best = min(masses, key=lambda pair: (-masses[pair],
                                         tuple(sorted((numbers[pair[0]], numbers[pair[1]])))))
    return tuple(sorted((numbers[best[0]], numbers[best[1]])))


def group_record(group: pd.DataFrame) -> dict:
    return {
        "rows": int(len(group)),
        "races": int(group.race_id.nunique()),
        "race_dates": int(group.race_date.nunique()),
        "min_date": group.race_date.min().date().isoformat(),
        "max_date": group.race_date.max().date().isoformat(),
        "pairs": int(sum(math.comb(int(n), 2) for n in group.groupby("race_id").size())),
    }


def label_pair_record(group: pd.DataFrame) -> dict:
    """Audit pair-label arithmetic only; do not score a chosen pair."""
    race_counts = {}
    for race_id, race in group.groupby("race_id", sort=False):
        runners = race[["horse_number", "finish_position"]].to_dict("records")
        candidates = list(combinations(runners, 2))
        positive = sum(
            int(left["finish_position"] <= 3 and right["finish_position"] <= 3)
            for left, right in candidates
        )
        race_counts[str(race_id)] = {
            "candidate_pairs": len(candidates),
            "expected_candidate_pairs": math.comb(len(runners), 2),
            "positive_pairs": positive,
        }
    bad = [race for race, values in race_counts.items()
           if values["candidate_pairs"] != values["expected_candidate_pairs"] or
           values["positive_pairs"] != 3]
    if bad:
        raise AssertionError(f"pair-label arithmetic failed for {len(bad)} races")
    return {
        "races": len(race_counts),
        "races_with_exactly_three_positive_pairs": sum(
            values["positive_pairs"] == 3 for values in race_counts.values()),
        "candidate_pair_rows": sum(values["candidate_pairs"] for values in race_counts.values()),
        "positive_pair_rows": sum(values["positive_pairs"] for values in race_counts.values()),
    }


def main() -> None:
    plan_path = STUDY / "PLAN.md"
    contract_path = STUDY / "INPUT_CONTRACT.md"
    if not plan_path.is_file() or not contract_path.is_file():
        raise FileNotFoundError("direct-pair plan and input contract must exist")

    refs = contract_hashes(contract_path)
    hash_records = {}
    for relative, expected in sorted(refs.items()):
        source = inside_root(relative)
        actual = sha256(source)
        if actual != expected:
            raise AssertionError(f"input hash differs from contract: {relative}")
        hash_records[relative] = {"sha256": actual, "bytes": source.stat().st_size}

    # Check the style study's own lock and manifest, independently of A's contract.
    style_manifest_path = STYLE / "ARTIFACT_MANIFEST.json"
    prepared_lock_path = STYLE / "outputs/prepared_lock.json"
    style_manifest = json.loads(style_manifest_path.read_text(encoding="utf-8"))
    prepared_lock = json.loads(prepared_lock_path.read_text(encoding="utf-8"))
    manifest_artifacts = style_manifest["study_artifacts"]
    style_manifest_verified_paths = {}
    for relative, record in sorted(hash_records.items()):
        if relative.startswith("jeju/research/20261010_style_history_ablation_v1/") and relative != style_manifest_path.relative_to(ROOT).as_posix():
            manifest_record = manifest_artifacts.get(relative)
            if manifest_record is None or manifest_record.get("sha256") != record["sha256"] or manifest_record.get("bytes") != record["bytes"]:
                raise AssertionError(f"style-study manifest does not verify source artifact: {relative}")
            style_manifest_verified_paths[relative] = record
    run_source_path = STYLE / "run.py"
    run_source_rel = run_source_path.relative_to(ROOT).as_posix()
    run_source_sha = sha256(run_source_path)
    run_manifest_record = manifest_artifacts.get(run_source_rel)
    if run_manifest_record is None or run_manifest_record.get("sha256") != run_source_sha:
        raise AssertionError("style F1_STYLE6 run source differs from locked manifest")
    feature_rel = FEATURES.relative_to(ROOT).as_posix()
    feature_sha = sha256(FEATURES)
    if prepared_lock["artifacts"].get("features.parquet") != feature_sha:
        raise AssertionError("feature hash differs from style prepared lock")
    if style_manifest["study_artifacts"][feature_rel]["sha256"] != feature_sha:
        raise AssertionError("feature hash differs from style manifest")

    features = pd.read_parquet(FEATURES)
    features["race_date"] = pd.to_datetime(features["race_date"], errors="raise")
    features["history_cutoff"] = pd.to_datetime(features["history_cutoff"], errors="raise")
    features["latest_history_date"] = pd.to_datetime(features["latest_history_date"], errors="coerce")
    if features.api_record_id.isna().any() or features.api_record_id.duplicated().any():
        raise AssertionError("feature api_record_id is null or duplicated")
    if features.race_id.isna().any() or features.horse_id.isna().any() or features.horse_number.isna().any():
        raise AssertionError("feature race or runner identity is incomplete")

    roster_bad = []
    top3_bad = []
    permutation_bad = []
    for race_id, group in features.groupby("race_id", sort=False):
        n = len(group)
        if (group.horse_id.nunique() != n or group.horse_number.nunique() != n or
                group.field_n.nunique() != 1 or int(group.field_n.iloc[0]) != n):
            roster_bad.append(str(race_id))
        if int((group.finish_position <= 3).sum()) != 3:
            top3_bad.append(str(race_id))
        if sorted(group.finish_position.astype(int).tolist()) != list(range(1, n + 1)):
            permutation_bad.append(str(race_id))
    if roster_bad or top3_bad or permutation_bad:
        raise AssertionError("feature roster / top3 labels / finish permutation failed")

    cutoff_bad = int((features.history_cutoff != features.race_date - pd.Timedelta(days=2)).sum())
    latest_after_cutoff = int((features.latest_history_date > features.history_cutoff).sum())
    if cutoff_bad or latest_after_cutoff:
        raise AssertionError("T-2 feature history cutoff failed")

    missingness = {}
    for mean_col, count_col in MEANS.items():
        count = pd.to_numeric(features[count_col], errors="coerce")
        value = pd.to_numeric(features[mean_col], errors="coerce")
        valid_count = count.notna() & (count.between(0, 5)) & (count == np.floor(count))
        coherent = valid_count & (((count == 0) & value.isna()) |
                                  ((count > 0) & value.notna() & np.isfinite(value)))
        missingness[mean_col] = {
            "count_column": count_col,
            "valid_count_rows": int(valid_count.sum()),
            "coherent_rows": int(coherent.sum()),
            "invalid_rows": int((~coherent).sum()),
        }
        if not coherent.all():
            raise AssertionError(f"mean/count missingness contract failed: {mean_col}")

    fold_records = {}
    evaluation_groups = []
    evaluation_scores_by_year: dict[int, pd.DataFrame] = {}
    calibration_scores_by_year: dict[int, pd.DataFrame] = {}
    for year in (2024, 2025, 2026):
        folder = STYLE / "outputs" / f"F1_STYLE6_{year}"
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        model_path = folder / "top3.txt"
        model_relative = model_path.relative_to(ROOT).as_posix()
        model_manifest_record = manifest_artifacts.get(model_relative)
        if model_manifest_record is None or model_manifest_record.get("sha256") != sha256(model_path):
            raise AssertionError(f"saved F1_STYLE6 model differs from source manifest in fold {year}")
        calibration = pd.read_parquet(folder / "calibration_scores.parquet")
        evaluation = pd.read_parquet(folder / "evaluation_scores.parquet")
        expected_score_columns = {"api_record_id", "score"}
        if set(calibration.columns) != expected_score_columns or set(evaluation.columns) != expected_score_columns:
            raise AssertionError(f"score schema differs from the locked two-column contract in fold {year}")
        if (meta.get("variant") != "F1_STYLE6" or int(meta.get("evaluation_year", -1)) != year or
                meta.get("calibration_scores_sha256") != sha256(folder / "calibration_scores.parquet") or
                meta.get("evaluation_scores_sha256") != sha256(folder / "evaluation_scores.parquet") or
                meta.get("model_sha256") != sha256(model_path) or
                int(meta.get("calibration_rows", -1)) != len(calibration) or
                int(meta.get("evaluation_rows", -1)) != len(evaluation)):
            raise AssertionError(f"saved F1_STYLE6 meta does not verify fold source artifacts in fold {year}")
        if calibration.api_record_id.duplicated().any() or evaluation.api_record_id.duplicated().any():
            raise AssertionError(f"score API key duplicated in fold {year}")
        if not np.isfinite(calibration.score.to_numpy(float)).all() or not np.isfinite(evaluation.score.to_numpy(float)).all():
            raise AssertionError(f"non-finite saved score in fold {year}")

        def join_scores(score: pd.DataFrame, role: str, expected_year: int) -> pd.DataFrame:
            expected_ids = set(features.loc[features.year.eq(expected_year), "api_record_id"])
            score_ids = set(score.api_record_id)
            if score_ids != expected_ids:
                raise AssertionError(
                    f"score IDs are not an exact roster match: fold={year} role={role} "
                    f"missing={len(expected_ids - score_ids)} extra={len(score_ids - expected_ids)}"
                )
            joined = score.merge(
                features[["api_record_id", "race_id", "race_date", "year", "horse_id",
                          "horse_number", "field_n", "finish_position", "history_cutoff",
                          "latest_history_date", *MEANS.keys(), *MEANS.values()]],
                on="api_record_id", how="left", validate="one_to_one", indicator=True,
            )
            if not joined._merge.eq("both").all():
                raise AssertionError(f"score feature join missing rows: fold={year} role={role}")
            if not joined.year.eq(expected_year).all():
                raise AssertionError(f"score file contains wrong calendar year: fold={year} role={role}")
            joined["race_date"] = pd.to_datetime(joined["race_date"], errors="raise")
            return joined.drop(columns="_merge")

        cal = join_scores(calibration, "calibration", year - 1)
        ev = join_scores(evaluation, "evaluation", year)
        for role, score_frame, role_name in (("calibration", cal, "calibration"),
                                             ("evaluation", ev, "evaluation")):
            if (score_frame.race_date.min().date().isoformat() != meta[f"{role_name}_min"] or
                    score_frame.race_date.max().date().isoformat() != meta[f"{role_name}_max"] or
                    int(score_frame.race_id.nunique()) != int(meta[f"{role_name}_races"])):
                raise AssertionError(f"saved F1_STYLE6 meta date/race summary mismatch in fold {year} {role}")
        if len(ev) != EXPECTED_COHORT[year][0] or ev.race_id.nunique() != EXPECTED_COHORT[year][1]:
            raise AssertionError(f"evaluation cohort mismatch in fold {year}")
        if ev.race_date.nunique() == 0:
            raise AssertionError(f"no evaluation dates in fold {year}")

        h1_all = cal[cal.race_date.dt.month.le(6)].copy()
        h2 = cal[cal.race_date.dt.month.ge(7)].copy()
        if h1_all.empty or h2.empty:
            raise AssertionError(f"empty H1 or H2 in fold {year}")
        h2_first = h2.race_date.min()
        h1_limit = h2_first - pd.Timedelta(days=2)
        h1 = h1_all[h1_all.race_date.le(h1_limit)].copy()
        if h1.empty:
            raise AssertionError(f"empty purged H1 in fold {year}")
        refit_max = pd.Timestamp(meta["refit_max"])
        if refit_max > h1.race_date.min() - pd.Timedelta(days=2):
            raise AssertionError(f"F1 refit overlaps H1 in fold {year}")
        if h1.race_date.max() > h2_first - pd.Timedelta(days=2):
            raise AssertionError(f"H1/H2 T-2 purge failed in fold {year}")
        if h2.race_date.max() > ev.race_date.min() - pd.Timedelta(days=2):
            raise AssertionError(f"H2/evaluation T-2 gap failed in fold {year}")
        h1n, h2n = int(h1.race_id.nunique()), int(h2.race_id.nunique())
        if (h1n, h2n) != EXPECTED_SPLITS[year]:
            raise AssertionError(f"H1/H2 race count differs from locked expected split in fold {year}")
        for split_name, split in (("H1", h1), ("H2", h2), ("evaluation", ev)):
            if split.groupby("race_id").finish_position.apply(lambda s: int((s <= 3).sum()) == 3).eq(False).any():
                raise AssertionError(f"Top3 label count failed in fold {year} {split_name}")
        label_pair_records = {
            name: label_pair_record(split)
            for name, split in (("H1", h1), ("H2", h2), ("evaluation", ev))
        }
        fold_records[str(year)] = {
            "base_model_sha256": meta["model_sha256"],
            "refit_max": meta["refit_max"],
            "saved_full_year_tau_excluded": float(meta["tau"]),
            "calibration_score_rows": int(len(cal)),
            "evaluation_score_rows": int(len(ev)),
            "H1_after_purge": group_record(h1),
            "H2": group_record(h2),
            "evaluation": group_record(ev),
            "H1_latest_date_max": h1.race_date.max().date().isoformat(),
            "H2_first_date": h2_first.date().isoformat(),
            "H2_last_date": h2.race_date.max().date().isoformat(),
            "evaluation_first_date": ev.race_date.min().date().isoformat(),
            "refit_to_H1_gap_days": int((h1.race_date.min() - refit_max).days),
            "H1_to_H2_gap_days": int((h2_first - h1.race_date.max()).days),
            "H2_to_evaluation_gap_days": int((ev.race_date.min() - h2.race_date.max()).days),
            "pair_label_arithmetic": label_pair_records,
        }
        evaluation_groups.append(ev)
        evaluation_scores_by_year[year] = evaluation[["api_record_id", "score"]].copy()
        calibration_scores_by_year[year] = calibration[["api_record_id", "score"]].copy()

    evaluation = pd.concat(evaluation_groups, ignore_index=True)
    if (len(evaluation), evaluation.race_id.nunique(), evaluation.race_date.nunique()) != (17412, 1779, 269):
        raise AssertionError("combined evaluation cohort differs from frozen expected values")
    if (evaluation.race_date.min().date().isoformat(), evaluation.race_date.max().date().isoformat()) != ("2024-01-05", "2026-09-19"):
        raise AssertionError("combined evaluation date range differs")

    # The same 2024 IDs occur in two fold artifacts, but the score model path matters.
    fold_overlap = evaluation_scores_by_year[2024].merge(
        calibration_scores_by_year[2025], on="api_record_id", how="outer",
        suffixes=("_eval_2024", "_cal_2025"), indicator=True,
    )
    overlap_rows = fold_overlap[fold_overlap._merge.eq("both")]
    if len(overlap_rows) != 6329 or not np.all(overlap_rows.score_eval_2024.ne(overlap_rows.score_cal_2025)):
        raise AssertionError("fold-qualified score overlap audit did not match expected paths")

    # Reconstruct p0 from each evaluation fold with canonical math.fsum.
    p0_parity = {"races": 0, "raw_top2_mismatch": 0, "min_pair_probability": 1.0,
                 "max_pair_probability": 0.0, "pair_mass_sum_max_abs_error": 0.0}
    for year in (2024, 2025, 2026):
        score = evaluation_scores_by_year[year]
        fold = features[features.year.eq(year)].merge(score, on="api_record_id", validate="one_to_one")
        for _, group in fold.groupby("race_id", sort=False):
            ordered = group.sort_values("horse_number")
            numbers = ordered.horse_number.astype(int).tolist()
            values = ordered.score.astype(float).tolist()
            baseline_pair = p0_max_pair(numbers, values)
            raw_top2_pair = canonical_top2(numbers, values)
            p0_parity["races"] += 1
            p0_parity["raw_top2_mismatch"] += int(baseline_pair != raw_top2_pair)
            # Recompute p0 pair marginals for probability range and sum-to-three.
            triples = list(combinations(range(len(numbers)), 3))
            energies = [math.fsum(values[i] for i in triple) for triple in triples]
            peak = max(energies)
            weights = [math.exp(value - peak) for value in energies]
            normalizer = math.fsum(weights)
            q = [weight / normalizer for weight in weights]
            pair_terms = {pair: [] for pair in combinations(range(len(numbers)), 2)}
            for triple, prob in zip(triples, q, strict=True):
                for pair in combinations(triple, 2):
                    pair_terms[pair].append(prob)
            pair_masses = [math.fsum(items) for items in pair_terms.values()]
            if not all(math.isfinite(p) and 0.0 < p < 1.0 for p in pair_masses):
                raise AssertionError("p0 pair probability is not finite and strictly inside (0,1)")
            mass_error = abs(math.fsum(pair_masses) - 3.0)
            p0_parity["pair_mass_sum_max_abs_error"] = max(p0_parity["pair_mass_sum_max_abs_error"], mass_error)
            p0_parity["min_pair_probability"] = min(p0_parity["min_pair_probability"], min(pair_masses))
            p0_parity["max_pair_probability"] = max(p0_parity["max_pair_probability"], max(pair_masses))
    if p0_parity["races"] != 1779 or p0_parity["raw_top2_mismatch"] or p0_parity["pair_mass_sum_max_abs_error"] > TOL:
        raise AssertionError("p0 negative-control source structure failed")

    # Check saved joint q structure and pair-marginal mass without using outcome rows.
    triple_path = JOINT / "outputs/report/all_triples.parquet"
    triples = pd.read_parquet(triple_path, columns=["race_id", "race_date", "arm", "triple_numbers",
                                                    "canonical_rank", "probability"])
    if triples.probability.isna().any() or not np.isfinite(triples.probability.to_numpy(float)).all():
        raise AssertionError("saved joint probability has null/non-finite values")
    if not triples.probability.between(0.0, 1.0).all():
        raise AssertionError("saved joint probability outside [0,1]")
    eval_rosters = evaluation.groupby("race_id").size().to_dict()
    q_groups = {"races": 0, "wrong_C_n_3": 0, "q_mass_fail": 0, "pair_mass_fail": 0,
                "q_mass_max_abs_error": 0.0, "pair_mass_max_abs_error": 0.0}
    for (arm, race), group in triples.groupby(["arm", "race_id"], sort=False):
        n = int(eval_rosters[str(race)])
        count_expected = math.comb(n, 3)
        triple_keys = [tuple(map(int, value.split(","))) for value in group.triple_numbers]
        if len(group) != count_expected or len(set(triple_keys)) != count_expected:
            q_groups["wrong_C_n_3"] += 1
        if any(tuple(sorted(key)) != key or len(key) != 3 for key in triple_keys):
            raise AssertionError("saved joint triples are not canonical unordered 3-sets")
        ranks = group.canonical_rank.astype(int).tolist()
        if len(set(ranks)) != len(ranks) or sorted(ranks) != list(range(1, count_expected + 1)):
            raise AssertionError("saved canonical ranks are incomplete or duplicated")
        q_values = group.probability.astype(float).tolist()
        q_error = abs(math.fsum(q_values) - 1.0)
        q_groups["q_mass_max_abs_error"] = max(q_groups["q_mass_max_abs_error"], q_error)
        if q_error > TOL:
            q_groups["q_mass_fail"] += 1
        pair_terms: dict[tuple[int, int], list[float]] = {}
        for key, probability in zip(triple_keys, q_values, strict=True):
            for pair in combinations(key, 2):
                pair_terms.setdefault(pair, []).append(probability)
        pair_masses = [math.fsum(pair_terms[pair]) for pair in sorted(pair_terms)]
        pair_error = abs(math.fsum(pair_masses) - 3.0)
        q_groups["pair_mass_max_abs_error"] = max(q_groups["pair_mass_max_abs_error"], pair_error)
        if pair_error > TOL:
            q_groups["pair_mass_fail"] += 1
        q_groups["races"] += 1
    if q_groups["races"] != 3558 or any(q_groups[key] for key in ("wrong_C_n_3", "q_mass_fail", "pair_mass_fail")):
        raise AssertionError("saved q structural identity failed")

    receipt = {
        "scope": "read-only source/provenance and outcome-free structural audit; no fit or performance metric",
        "audit_date": date.today().isoformat(),
        "result": "PASS",
        "direct_plan_sha256": sha256(plan_path),
        "direct_input_contract_sha256": sha256(contract_path),
        "contract_sources_verified": hash_records,
        "style_feature_hash_verified_against": {
            "manifest_sha256": sha256(style_manifest_path),
            "prepared_lock_sha256": sha256(prepared_lock_path),
            "feature_sha256": feature_sha,
            "run_py_sha256": run_source_sha,
            "manifest_verified_contract_paths": style_manifest_verified_paths,
        },
        "full_feature_source": {
            "rows": int(len(features)), "races": int(features.race_id.nunique()),
            "race_dates": int(features.race_date.nunique()),
            "date_min": features.race_date.min().date().isoformat(),
            "date_max": features.race_date.max().date().isoformat(),
            "top3_runner_count_by_race": {str(k): int(v) for k, v in
                features.assign(is_top3=features.finish_position.le(3)).groupby("race_id").is_top3.sum().value_counts().items()},
            "normal_finish_permutation_bad_races": len(permutation_bad),
            "roster_bad_races": len(roster_bad),
            "T_minus_2_cutoff_rows": int(len(features) - cutoff_bad),
            "latest_history_after_cutoff_rows": latest_after_cutoff,
            "mean_count_missingness": missingness,
        },
        "folds": fold_records,
        "evaluation_cohort": {
            "rows": int(len(evaluation)), "races": int(evaluation.race_id.nunique()),
            "race_dates": int(evaluation.race_date.nunique()),
            "date_min": evaluation.race_date.min().date().isoformat(),
            "date_max": evaluation.race_date.max().date().isoformat(),
            "2026_partial_through": "2026-09-19",
        },
        "fold_qualified_overlap": {
            "paths": ["F1_STYLE6_2024/evaluation_scores.parquet", "F1_STYLE6_2025/calibration_scores.parquet"],
            "same_api_record_ids": int(len(overlap_rows)),
            "score_vectors_differ": bool(np.all(overlap_rows.score_eval_2024.ne(overlap_rows.score_cal_2025))),
            "max_absolute_score_difference": float((overlap_rows.score_eval_2024 - overlap_rows.score_cal_2025).abs().max()),
        },
        "p0_structure": p0_parity,
        "saved_joint_q_structure": q_groups,
        "saved_joint_source": {
            "sha256": sha256(triple_path), "rows": int(len(triples)),
            "arms": {str(k): int(v) for k, v in triples.arm.value_counts().items()},
            "races_per_arm": 1779,
        },
        "explicit_exclusions": [
            "No candidate pair model was fit.",
            "No predicted pair hit rate, calibration metric, or other evaluation outcome metric was calculated.",
            "No database, network, current model, or operating registry was accessed.",
        ],
    }
    output = OUT / "prefit_source_audit_v4.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"result": receipt["result"], "output": str(output),
                      "folds": receipt["folds"], "p0_structure": p0_parity,
                      "joint_q_structure": q_groups}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

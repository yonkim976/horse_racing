"""No-fit retrospective audit of saved joint-relationship gains and losses.

This script reads only the fixed, hash-locked study artifacts named in
INPUT_CONTRACT.json. It does not train, calibrate, access a database/network, or
write anywhere outside this analysis folder. Outputs are created exclusively.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = ROOT / "jeju/research/20261010_joint_relationship_v1"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
OUT = HERE / "outputs_pending"
FINAL_OUT = HERE / "outputs"
INPUT_CONTRACT_PATH = HERE / "INPUT_CONTRACT.json"
PLAN_PATH = HERE / "ANALYSIS_PLAN.md"

sys.path.insert(0, str(STUDY))
import joint_model as jm  # noqa: E402


BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261008
ENERGY_TIE_TOL = 1e-12
PAIR_FEATURE_GROUPS = {
    "score_related_2": ["score_product", "absdiff_score"],
    "style_mean_difference_3": [
        "absdiff_hist_s1f_relpos_mean5",
        "absdiff_hist_s1f_to_c4_forward_mean5",
        "absdiff_hist_c4_to_g1f_forward_mean5",
    ],
    "support_count_difference_3": [
        "absdiff_hist_s1f_relpos_n",
        "absdiff_hist_s1f_to_c4_pair_n",
        "absdiff_hist_c4_to_g1f_pair_n",
    ],
    "missingness_indicator_3": [
        "missing_either_hist_s1f_relpos_mean5",
        "missing_either_hist_s1f_to_c4_forward_mean5",
        "missing_either_hist_c4_to_g1f_forward_mean5",
    ],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def write_json_new(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2,
                  allow_nan=False, default=json_default)
        stream.write("\n")


def write_csv_new(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, encoding="utf-8", mode="x",
                 float_format="%.12g")


def verify_input_hashes(contract: dict) -> dict[str, str]:
    checked: dict[str, str] = {}
    for entry in contract["input_files"]:
        relative = Path(entry["path"])
        path = (ROOT / relative).resolve(strict=True)
        if not path.is_relative_to(ROOT.resolve()):
            raise AssertionError(f"source escaped the project root: {relative}")
        actual = sha256(path)
        expected = entry["sha256"]
        if actual != expected:
            raise AssertionError(f"source hash changed: {relative}")
        checked[relative.as_posix()] = actual
    return checked


def load_fixed_inputs(contract: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame,
                                                pd.DataFrame, dict]:
    metrics = pd.read_csv(STUDY / "outputs/report/race_metrics.csv")
    runners_saved = pd.read_csv(STUDY / "outputs/report/runner_marginals.csv")
    triples = pd.read_parquet(STUDY / "outputs/report/all_triples.parquet")
    features = pd.read_parquet(STYLE / "outputs/features.parquet")
    score_parts = []
    for year in (2024, 2025, 2026):
        score_path = STYLE / f"outputs/F1_STYLE6_{year}/evaluation_scores.parquet"
        score = pd.read_parquet(score_path)
        if list(score.columns) != ["api_record_id", "score"]:
            raise AssertionError(f"saved score columns changed for {year}")
        expected_rows = next(
            int(entry["rows"]) for entry in contract["input_files"]
            if entry["path"].endswith(f"F1_STYLE6_{year}/evaluation_scores.parquet")
        )
        if len(score) != expected_rows:
            raise AssertionError(f"saved score row count changed for {year}")
        score["evaluation_year"] = year
        score_parts.append(score)
    scores = pd.concat(score_parts, ignore_index=True)
    params = json.loads((STUDY / "outputs/fit_parameters.json").read_text(encoding="utf-8"))

    required_metric_cols = set(contract["csv_column_contracts"][
        "jeju/research/20261010_joint_relationship_v1/outputs/report/race_metrics.csv"])
    required_runner_cols = set(contract["csv_column_contracts"][
        "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv"])
    if not required_metric_cols.issubset(metrics.columns):
        raise AssertionError("race_metrics columns differ from the saved contract")
    if not required_runner_cols.issubset(runners_saved.columns):
        raise AssertionError("runner_marginals columns differ from the saved contract")
    triples_contract = next(e for e in contract["input_files"]
                            if e["path"].endswith("all_triples.parquet"))
    if list(triples.columns) != triples_contract["columns"]:
        raise AssertionError("all_triples columns differ from the saved contract")
    feature_contract = next(e for e in contract["input_files"]
                            if e["path"].endswith("features.parquet"))
    missing = set(feature_contract["required_columns"]).difference(features.columns)
    if missing:
        raise AssertionError(f"features missing contract columns: {sorted(missing)}")
    return metrics, runners_saved, triples, features, {"scores": scores, "params": params}


def derive_feature_state(group: pd.DataFrame, scaler: dict, pair_rms: np.ndarray) -> dict:
    """Rebuild only the saved model's deterministic feature map; no fitting."""
    runner_values, runner_valid = jm.transform_runner(group, scaler)
    pair_ids, phi = jm.pair_basis(runner_values, runner_valid)
    residual, _ = jm.project_pair_basis(pair_ids, phi, len(group))
    normalized = np.zeros_like(residual)
    active = pair_rms > jm.DEGENERATE_TOL
    normalized[:, active] = residual[:, active] / pair_rms[active]
    cleaned, _ = jm.clean_degenerate_residual(normalized)
    triples_idx = jm.triple_indices(len(group))
    triple_features = jm.triple_relation_features(pair_ids, cleaned, triples_idx)
    scores = group.score.to_numpy(float)
    baseline_energy = jm.baseline_energies(scores, triples_idx)
    numbers = group.horse_number.to_numpy(int)
    triple_tickets = [ticket(numbers[triple]) for triple in triples_idx]
    truth_rows = np.flatnonzero(group.finish_position.to_numpy(int) <= 3)
    if len(truth_rows) != 3:
        raise AssertionError(f"true set is not exactly three runners: {group.race_id.iloc[0]}")
    truth_ticket = ticket(numbers[truth_rows])
    return {
        "runner_values": runner_values,
        "runner_valid": runner_valid,
        "triples": triples_idx,
        "tickets": triple_tickets,
        "truth_ticket": truth_ticket,
        "triple_features": triple_features,
        "baseline_energy": baseline_energy,
    }


def ticket(numbers: np.ndarray) -> str:
    return ",".join(str(int(value)) for value in sorted(numbers.tolist()))


def probability_concentration(frame: pd.DataFrame, arm: str) -> dict:
    ordered = frame.sort_values("canonical_rank", kind="stable")
    p = ordered.probability.to_numpy(float)
    if not np.isfinite(p).all() or (p < 0).any() or abs(float(p.sum()) - 1.0) > 1e-12:
        raise AssertionError(f"invalid saved triple probabilities: {frame.race_id.iloc[0]} {arm}")
    positive = p > 0
    entropy = float(-np.sum(p[positive] * np.log(p[positive])))
    top6 = ordered.iloc[:6]
    top7 = ordered.iloc[6]
    e6 = float(top6.iloc[-1].total_energy)
    e7 = float(top7.total_energy)
    p6 = float(top6.iloc[-1].probability)
    p7 = float(top7.probability)
    gap = e6 - e7
    return {
        f"{arm}_top_triple_probability": float(ordered.probability.iloc[0]),
        f"{arm}_top6_probability_mass": float(top6.probability.sum()),
        f"{arm}_triple_entropy": entropy,
        f"{arm}_effective_triples_exp_entropy": float(math.exp(entropy)),
        f"{arm}_energy_margin_6_7": gap,
        f"{arm}_probability_margin_6_7": p6 - p7,
        f"{arm}_boundary_exact_energy_tie": bool(gap == 0.0),
        f"{arm}_boundary_tolerance_energy_tie": bool(abs(gap) <= ENERGY_TIE_TOL),
        f"{arm}_rank6_ticket": str(top6.iloc[-1].triple_numbers),
        f"{arm}_rank7_ticket": str(top7.triple_numbers),
        f"{arm}_rank6_energy": e6,
        f"{arm}_rank7_energy": e7,
        f"{arm}_rank6_probability": p6,
        f"{arm}_rank7_probability": p7,
    }


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def race_history_features(group: pd.DataFrame, model_state: dict) -> dict:
    n = len(group)
    starts = _num(group.observed_starts)
    days = _num(group.days_since_start)
    same_n = _num(group.same_distance_last5_actual_n)
    same_normal_n = _num(group.same_distance_last5_normal_n)
    same_rate = _num(group.same_distance_last5_top3_rate)
    style_mean_names = list(jm.MEAN_COLUMNS)
    style_count_names = [jm.COUNT_FOR_MEAN[name] for name in style_mean_names]
    style_counts = np.column_stack([_num(group[name]).to_numpy(float)
                                    for name in style_count_names])
    style_means = np.column_stack([_num(group[name]).to_numpy(float)
                                   for name in style_mean_names])
    if not np.isfinite(style_counts).all():
        raise AssertionError(f"missing style support count: {group.race_id.iloc[0]}")
    count_mean_consistent = np.array_equal(np.isfinite(style_means), style_counts > 0)
    if not count_mean_consistent:
        raise AssertionError(f"style mean/count missingness mismatch: {group.race_id.iloc[0]}")

    style_total = style_counts.sum(axis=1)
    has_any_style_mean = np.isfinite(style_means).any(axis=1)
    has_all_style_means = np.isfinite(style_means).all(axis=1)
    # The three means use the saved fold scaler; missing dimensions are omitted
    # only within that runner pair and supported-pair counts are explicit.
    values = model_state["runner_values"]
    valid = model_state["runner_valid"]
    style_cols = [jm.INPUT_COLUMNS.index(name) for name in style_mean_names]
    pair_distances: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            ok = valid[i, style_cols] & valid[j, style_cols]
            if ok.any():
                pair_distances.append(float(np.abs(values[i, style_cols][ok] -
                                                   values[j, style_cols][ok]).mean()))

    out = {
        "career_starts_0_n": int((starts == 0).sum()),
        "career_starts_1_4_n": int(starts.between(1, 4).sum()),
        "career_starts_5plus_n": int((starts >= 5).sum()),
        "career_starts_missing_n": int(starts.isna().sum()),
        "career_starts_0_share": float((starts == 0).mean()),
        "career_starts_1_4_share": float(starts.between(1, 4).mean()),
        "career_starts_5plus_share": float((starts >= 5).mean()),
        "career_starts_missing_share": float(starts.isna().mean()),
        "same_distance_history_mean_n": float(same_n.mean()),
        "same_distance_history_median_n": float(same_n.median()),
        "same_distance_history_zero_share": float((same_n == 0).mean()),
        "same_distance_history_missing_share": float(same_n.isna().mean()),
        "same_distance_normal_history_mean_n": float(same_normal_n.mean()),
        "same_distance_top3_rate_mean": float(same_rate.mean()),
        "same_distance_top3_rate_missing_share": float(same_rate.isna().mean()),
        "days_since_start_median": float(days.median()),
        "days_since_start_mean": float(days.mean()),
        "days_since_start_missing_share": float(days.isna().mean()),
        "style_support_total_mean": float(style_total.mean()),
        "style_support_total_median": float(np.median(style_total)),
        "style_support_no_observation_share": float((style_total == 0).mean()),
        "style_mean_any_available_share": float(has_any_style_mean.mean()),
        "style_mean_all3_available_share": float(has_all_style_means.mean()),
        "style_pair_heterogeneity_mean_absdiff_z": (
            float(np.mean(pair_distances)) if pair_distances else np.nan
        ),
        "style_pair_heterogeneity_eligible_pairs": int(len(pair_distances)),
        "style_pair_heterogeneity_possible_pairs": int(math.comb(n, 2)),
        "style_pair_heterogeneity_eligible_pair_share": (
            float(len(pair_distances) / math.comb(n, 2)) if math.comb(n, 2) else np.nan
        ),
        "s1f_to_c4_forward_mean": float(_num(group.hist_s1f_to_c4_forward_mean5).mean()),
        "s1f_to_c4_forward_coverage": float(
            _num(group.hist_s1f_to_c4_forward_mean5).notna().mean()
        ),
        "c4_to_g1f_forward_mean": float(_num(group.hist_c4_to_g1f_forward_mean5).mean()),
        "c4_to_g1f_forward_coverage": float(
            _num(group.hist_c4_to_g1f_forward_mean5).notna().mean()
        ),
        "s1f_relpos_mean": float(_num(group.hist_s1f_relpos_mean5).mean()),
        "s1f_relpos_coverage": float(_num(group.hist_s1f_relpos_mean5).notna().mean()),
    }
    return out


def race_score_gaps(group: pd.DataFrame) -> dict:
    score = group.score.to_numpy(float)
    order = np.argsort(-score, kind="stable")
    sd = float(np.std(score, ddof=0))
    gaps = {
        "score_gap_rank1_2_raw": float(score[order[0]] - score[order[1]]),
        "score_gap_rank1_3_raw": float(score[order[0]] - score[order[2]]),
        "score_gap_rank3_4_raw": float(score[order[2]] - score[order[3]]),
        "race_score_sd_population": sd,
        "score_gap_rank1_2_over_race_sd": float((score[order[0]] - score[order[1]]) / sd)
        if sd > 0 else np.nan,
        "score_gap_rank1_3_over_race_sd": float((score[order[0]] - score[order[2]]) / sd)
        if sd > 0 else np.nan,
        "score_gap_rank3_4_over_race_sd": float((score[order[2]] - score[order[3]]) / sd)
        if sd > 0 else np.nan,
    }
    return gaps


def cluster_bootstrap_delta(group: pd.DataFrame) -> dict:
    if group.empty:
        return {"paired_date_ci95_low": np.nan, "paired_date_ci95_high": np.nan,
                "paired_date_count": 0}
    by_date = [part.delta_hit6.to_numpy(float)
               for _, part in group.groupby("race_date", sort=True, observed=True)]
    if not by_date:
        raise AssertionError("nonempty subgroup has no race dates")
    point = float(group.delta_hit6.mean())
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    date_count = len(by_date)
    for draw in range(BOOTSTRAP_DRAWS):
        chosen = rng.integers(0, date_count, size=date_count)
        total = 0.0
        rows = 0
        for index in chosen:
            values = by_date[int(index)]
            total += float(values.sum())
            rows += len(values)
        draws[draw] = total / rows
    low, high = np.quantile(draws, [0.025, 0.975], method="linear")
    return {"paired_date_ci95_low": float(low), "paired_date_ci95_high": float(high),
            "paired_date_count": date_count, "paired_date_bootstrap_draws": BOOTSTRAP_DRAWS,
            "paired_date_bootstrap_seed": BOOTSTRAP_SEED, "point_estimate": point}


def summarize_condition(cohort: pd.DataFrame, column: str, factor: str,
                        value: Any) -> dict:
    group = cohort if factor == "all" else cohort.loc[cohort[column].eq(value)]
    dates = group.race_date.nunique()
    old_hits = int(group.baseline_hit6.sum())
    new_hits = int(group.candidate_hit6.sum())
    gained = int(group.hit_class.eq("gained").sum())
    lost = int(group.hit_class.eq("lost").sum())
    both_hit = int(group.hit_class.eq("both_hit").sum())
    both_miss = int(group.hit_class.eq("both_miss").sum())
    ci = cluster_bootstrap_delta(group)
    n = len(group)
    if gained + lost + both_hit + both_miss != n:
        raise AssertionError(f"outcome partition incomplete for {factor}={value}")
    return {
        "factor": factor,
        "condition": str(value),
        "races": n,
        "share_of_full_1779": n / len(cohort),
        "race_dates": dates,
        "gained": gained,
        "lost": lost,
        "net_gained_minus_lost": gained - lost,
        "both_hit": both_hit,
        "both_miss": both_miss,
        "baseline_hits": old_hits,
        "candidate_hits": new_hits,
        "baseline_hit_rate": old_hits / n if n else np.nan,
        "candidate_hit_rate": new_hits / n if n else np.nan,
        "candidate_minus_baseline_hit_rate": (new_hits - old_hits) / n if n else np.nan,
        "paired_date_ci95_low": ci["paired_date_ci95_low"],
        "paired_date_ci95_high": ci["paired_date_ci95_high"],
        "ci_dates": ci["paired_date_count"],
        "ci_draws": BOOTSTRAP_DRAWS,
        "ci_seed": BOOTSTRAP_SEED,
    }


def build_condition_table(cohort: pd.DataFrame) -> pd.DataFrame:
    rows = [summarize_condition(cohort, "", "all", "all_1779")]
    specs: list[tuple[str, str, list[Any]]] = []
    specs.append(("evaluation_year", "year", sorted(cohort.evaluation_year.unique().tolist())))
    specs.append(("calendar_month", "month", sorted(cohort.calendar_month.unique().tolist())))
    specs.append(("distance_m", "distance_m",
                  sorted(cohort.distance_m.dropna().unique().tolist())))
    grade_values = sorted(cohort.grade_condition.astype(str).unique().tolist())
    specs.append(("grade_condition", "grade_raw", grade_values))
    specs.append(("field_size_bin", "field_size_bin", ["<=8", "9-10", ">=11"]))
    for column, factor, values in specs:
        for value in values:
            rows.append(summarize_condition(cohort, column, factor, value))
    return pd.DataFrame(rows)


def continuous_summary(features: pd.DataFrame, cohort: pd.DataFrame) -> pd.DataFrame:
    measurement_columns = [
        "score_gap_rank1_2_raw", "score_gap_rank1_3_raw", "score_gap_rank3_4_raw",
        "score_gap_rank1_2_over_race_sd", "score_gap_rank1_3_over_race_sd",
        "score_gap_rank3_4_over_race_sd",
        "baseline_top_triple_probability", "baseline_top6_probability_mass",
        "baseline_triple_entropy", "baseline_effective_triples_exp_entropy",
        "baseline_energy_margin_6_7", "baseline_probability_margin_6_7",
        "candidate_top_triple_probability", "candidate_top6_probability_mass",
        "candidate_triple_entropy", "candidate_effective_triples_exp_entropy",
        "candidate_energy_margin_6_7", "candidate_probability_margin_6_7",
        "true_set_baseline_rank", "true_set_candidate_rank",
        "true_set_rank_delta_candidate_minus_baseline",
        "true_set_baseline_probability", "true_set_candidate_probability",
        "true_set_probability_delta_candidate_minus_baseline",
        "true_set_candidate_relationship_energy",
        "career_starts_0_share", "career_starts_1_4_share", "career_starts_5plus_share",
        "career_starts_missing_share", "same_distance_history_mean_n",
        "same_distance_history_zero_share", "same_distance_history_missing_share",
        "same_distance_top3_rate_mean", "same_distance_top3_rate_missing_share",
        "days_since_start_median", "days_since_start_missing_share",
        "style_support_total_mean", "style_support_no_observation_share",
        "style_mean_any_available_share", "style_mean_all3_available_share",
        "style_pair_heterogeneity_mean_absdiff_z",
        "style_pair_heterogeneity_eligible_pair_share",
        "s1f_to_c4_forward_mean", "s1f_to_c4_forward_coverage",
        "c4_to_g1f_forward_mean", "c4_to_g1f_forward_coverage",
        "s1f_relpos_mean", "s1f_relpos_coverage",
    ]
    joined = cohort[["race_id", "race_date", "hit_class"]].merge(
        features, on=["race_id", "race_date"], how="left", validate="one_to_one",
        suffixes=("", "_feature"))
    rows: list[dict] = []
    selections = [("all_1779", joined)]
    for label in ("gained", "lost", "both_hit", "both_miss"):
        selections.append((label, joined.loc[joined.hit_class.eq(label)]))
    for outcome, frame in selections:
        for column in measurement_columns:
            values = pd.to_numeric(frame[column], errors="coerce")
            finite = values[np.isfinite(values.to_numpy(float))]
            rows.append({
                "outcome_group": outcome,
                "feature": column,
                "races": int(len(frame)),
                "race_dates": int(frame.race_date.nunique()),
                "nonmissing_races": int(finite.shape[0]),
                "mean": float(finite.mean()) if len(finite) else np.nan,
                "median": float(finite.median()) if len(finite) else np.nan,
                "p25": float(finite.quantile(0.25)) if len(finite) else np.nan,
                "p75": float(finite.quantile(0.75)) if len(finite) else np.nan,
            })
    return pd.DataFrame(rows)


def missingness_summary(runners: pd.DataFrame, cohort: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "observed_starts", "days_since_start", "same_distance_last5_top3_rate",
        "same_distance_last5_actual_n", "same_distance_last5_normal_n",
        "hist_s1f_relpos_mean5", "hist_s1f_to_c4_forward_mean5",
        "hist_c4_to_g1f_forward_mean5",
    ]
    run = runners.copy()
    race_missing = (run.set_index("race_id")[cols].isna()
                    .groupby(level=0, sort=True, observed=True).mean().reset_index())
    joined = cohort[["race_id", "race_date", "hit_class"]].merge(
        race_missing, on="race_id", how="left", validate="one_to_one")
    rows = []
    for outcome, frame in [("all_1779", joined)] + [
            (label, joined.loc[joined.hit_class.eq(label)])
            for label in ("gained", "lost", "both_hit", "both_miss")]:
        for col in cols:
            values = frame[col].to_numpy(float)
            rows.append({
                "outcome_group": outcome,
                "feature": col,
                "races": int(len(frame)),
                "race_dates": int(frame.race_date.nunique()),
                "mean_per_race_runner_missing_fraction": float(np.nanmean(values))
                if np.isfinite(values).any() else np.nan,
                "median_per_race_runner_missing_fraction": float(np.nanmedian(values))
                if np.isfinite(values).any() else np.nan,
                "races_with_any_missing_runner": int(np.sum(values > 0)),
            })
    return pd.DataFrame(rows)


def verify_saved_predictions(metrics: pd.DataFrame, runners_saved: pd.DataFrame,
                             triples: pd.DataFrame, features: pd.DataFrame,
                             scores: pd.DataFrame, params: dict) -> tuple[pd.DataFrame,
                                                                          pd.DataFrame,
                                                                          pd.DataFrame,
                                                                          dict]:
    for name, expected in (("race_metrics", 1779), ("runners_saved", 17412),
                           ("features", len(features)), ("scores", 17412)):
        frame = {"race_metrics": metrics, "runners_saved": runners_saved,
                 "features": features, "scores": scores}[name]
        if name in {"race_metrics", "runners_saved", "scores"} and len(frame) != expected:
            raise AssertionError(f"unexpected {name} rows: {len(frame)} != {expected}")
    evaluation_features = features.loc[features.year.isin([2024, 2025, 2026])].copy()
    evaluation_features["api_record_id"] = evaluation_features.api_record_id.astype("int64")
    if evaluation_features.api_record_id.duplicated().any() or scores.api_record_id.duplicated().any():
        raise AssertionError("evaluation API record key is not unique")
    if set(evaluation_features.api_record_id) != set(scores.api_record_id.astype("int64")):
        raise AssertionError("saved evaluation scores do not exactly cover feature rows")
    eval_runner = evaluation_features.merge(
        scores[["api_record_id", "score"]], on="api_record_id", how="inner",
        validate="one_to_one")
    eval_runner["race_date"] = pd.to_datetime(eval_runner.race_date, errors="raise").dt.strftime("%Y-%m-%d")
    if not np.isfinite(eval_runner.score.to_numpy(float)).all():
        raise AssertionError("non-finite saved score")
    if len(eval_runner) != 17412 or eval_runner.race_id.nunique() != 1779 or eval_runner.race_date.nunique() != 269:
        raise AssertionError("saved evaluation runner cohort differs from fixed contract")
    if params.get("pair_features") != list(jm.PAIR_FEATURES):
        raise AssertionError("saved fit pair feature names differ from fixed model contract")
    folds = {int(fold["evaluation_year"]): fold for fold in params["folds"]}
    if set(folds) != {2024, 2025, 2026}:
        raise AssertionError("saved fit fold years differ from fixed contract")
    if triples.race_id.nunique() != 1779 or len(triples) != 402808:
        raise AssertionError("saved full-triple cohort shape differs from fixed contract")
    if set(triples.arm.unique()) != {"matched_baseline", "candidate"}:
        raise AssertionError("unexpected saved arms")
    if triples.duplicated(["race_id", "arm", "triple_numbers"]).any():
        raise AssertionError("duplicate saved race/arm/ticket rows")
    truth_counts = triples.loc[triples.is_true_set].groupby(
        ["race_id", "arm"], observed=True).size()
    if len(truth_counts) != 1779 * 2 or not truth_counts.eq(1).all():
        raise AssertionError("saved distribution does not contain one true set per race and arm")
    if set(metrics.race_id) != set(eval_runner.race_id) or set(triples.race_id) != set(metrics.race_id):
        raise AssertionError("saved race IDs differ among the evaluation inputs")
    if runners_saved.api_record_id.duplicated().any() or set(runners_saved.api_record_id) != set(eval_runner.api_record_id):
        raise AssertionError("runner marginal IDs differ from saved evaluation roster")
    runner_label = (eval_runner.finish_position <= 3).astype(int)
    saved_label = runners_saved.set_index("api_record_id").loc[
        eval_runner.api_record_id, "saved_y_top3"].to_numpy(int)
    if not np.array_equal(runner_label.to_numpy(int), saved_label):
        raise AssertionError("saved runner labels differ from fixed finish positions")
    return eval_runner, triples, metrics, folds


def make_race_ledgers(eval_runner: pd.DataFrame, triples: pd.DataFrame,
                      metrics: pd.DataFrame, folds: dict) -> tuple[pd.DataFrame,
                                                                   pd.DataFrame,
                                                                   pd.DataFrame,
                                                                   pd.DataFrame,
                                                                   pd.DataFrame,
                                                                   pd.DataFrame,
                                                                   dict]:
    metric_by_race = metrics.set_index("race_id", drop=False)
    triple_groups = {str(key): value.copy()
                     for key, value in triples.groupby("race_id", sort=True, observed=True)}
    runner_groups = {str(key): value.sort_values("horse_number", kind="stable").reset_index(drop=True)
                     for key, value in eval_runner.groupby("race_id", sort=True, observed=True)}
    race_rows: list[dict] = []
    beta_rows: list[dict] = []
    boundary_rows: list[dict] = []
    ticket_change_rows: list[dict] = []
    contrast_rows: list[dict] = []
    fold_checks: dict[str, Any] = {}
    for race_id in sorted(runner_groups):
        group = runner_groups[race_id]
        tgroup = triple_groups[race_id]
        source_metric = metric_by_race.loc[race_id]
        year = int(group.year.iloc[0])
        fold = folds[year]
        beta = np.asarray(fold["beta"], dtype=float)
        pair_rms = np.asarray(fold["pair_rms"], dtype=float)
        if len(beta) != len(jm.PAIR_FEATURES) or len(pair_rms) != len(jm.PAIR_FEATURES):
            raise AssertionError(f"unexpected beta or pair RMS shape for {year}")
        if group.race_id.nunique() != 1 or group.year.nunique() != 1:
            raise AssertionError(f"race runner group is not homogeneous: {race_id}")
        if int(group.field_n.nunique()) != 1 or int(group.field_n.iloc[0]) != len(group):
            raise AssertionError(f"saved field size disagrees with roster: {race_id}")
        if group.distance_m.nunique(dropna=False) != 1 or group.grade_raw.nunique(dropna=False) != 1:
            raise AssertionError(f"race descriptors disagree within roster: {race_id}")

        state = derive_feature_state(group, fold["runner_scaler"], pair_rms)
        triples_idx = state["triples"]
        triples_by_arm = {arm: part.sort_values("canonical_rank", kind="stable").copy()
                          for arm, part in tgroup.groupby("arm", sort=False, observed=True)}
        expected_n = math.comb(len(group), 3)
        if expected_n < 7:
            raise AssertionError(f"fewer than seven possible triples: {race_id}")
        if any(len(part) != expected_n for part in triples_by_arm.values()):
            raise AssertionError(f"incomplete saved triple distribution: {race_id}")
        own_tickets = state["tickets"]
        for arm in ("matched_baseline", "candidate"):
            observed = triples_by_arm[arm]
            # Pair saved result rows to the deterministic roster/triple enumeration.
            if observed.triple_index.duplicated().any() or set(observed.triple_index.astype(int)) != set(range(expected_n)):
                raise AssertionError(f"triple indices do not cover complete enumeration: {race_id}/{arm}")
            keyed = observed.set_index("triple_index").loc[range(expected_n)]
            if keyed.triple_numbers.astype(str).tolist() != own_tickets:
                raise AssertionError(f"saved ticket enumeration differs for {race_id}/{arm}")
        base = triples_by_arm["matched_baseline"].set_index("triple_index").loc[range(expected_n)]
        cand = triples_by_arm["candidate"].set_index("triple_index").loc[range(expected_n)]
        candidate_features = state["triple_features"]
        candidate_relation = candidate_features @ beta
        if not np.allclose(state["baseline_energy"], base.baseline_score_energy.to_numpy(float),
                           rtol=0, atol=1e-12):
            raise AssertionError(f"baseline energy reconstruction differs: {race_id}")
        if not np.allclose(candidate_relation, cand.relationship_energy.to_numpy(float),
                           rtol=0, atol=1e-10):
            raise AssertionError(f"candidate relationship energy reconstruction differs: {race_id}")
        if not np.allclose(state["baseline_energy"] + candidate_relation,
                           cand.total_energy.to_numpy(float), rtol=0, atol=1e-10):
            raise AssertionError(f"candidate total energy reconstruction differs: {race_id}")

        truth_ticket = state["truth_ticket"]
        truth_matches = np.flatnonzero(np.asarray(own_tickets, dtype=object) == truth_ticket)
        if len(truth_matches) != 1:
            raise AssertionError(f"true set ticket missing or duplicated: {race_id}")
        truth_idx = int(truth_matches[0])
        if not bool(base.iloc[truth_idx].is_true_set) or not bool(cand.iloc[truth_idx].is_true_set):
            raise AssertionError(f"saved true-set marker differs from finish order: {race_id}")

        arms = {
            "baseline": {
                "rows": base,
                "hit": int(int(base.iloc[truth_idx].canonical_rank) <= 6),
            },
            "candidate": {
                "rows": cand,
                "hit": int(int(cand.iloc[truth_idx].canonical_rank) <= 6),
            },
        }
        if arms["baseline"]["hit"] != int(source_metric.baseline_hit6) or arms["candidate"]["hit"] != int(source_metric.candidate_hit6):
            raise AssertionError(f"saved hit outcomes do not match true-set ranks: {race_id}")
        if int(base.iloc[truth_idx].canonical_rank) != int(cand.iloc[truth_idx].canonical_rank):
            pass

        base_top = base.loc[base.canonical_rank.le(6), "triple_numbers"].astype(str).tolist()
        cand_top = cand.loc[cand.canonical_rank.le(6), "triple_numbers"].astype(str).tolist()
        base_set, cand_set = set(base_top), set(cand_top)
        entered = sorted(cand_set - base_set)
        exited = sorted(base_set - cand_set)
        changed = base_set != cand_set
        if len(entered) != len(exited):
            raise AssertionError(f"selection size changed between arms: {race_id}")
        for side, values in (("entered_candidate", entered), ("exited_baseline", exited)):
            for rank, tri in enumerate(values, start=1):
                row = (cand if side == "entered_candidate" else base).loc[
                    (cand if side == "entered_candidate" else base).triple_numbers.eq(tri)
                ].iloc[0]
                ticket_change_rows.append({
                    "race_id": race_id,
                    "race_date": str(group.race_date.iloc[0]),
                    "evaluation_year": year,
                    "side": side,
                    "ticket": tri,
                    "arm_rank": int(row.canonical_rank),
                    "arm_probability": float(row.probability),
                    "arm_total_energy": float(row.total_energy),
                    "is_actual_true_set": bool(tri == truth_ticket),
                })

        base_truth = base.iloc[truth_idx]
        cand_truth = cand.iloc[truth_idx]
        base_rank = int(base_truth.canonical_rank)
        cand_rank = int(cand_truth.canonical_rank)
        hit_class = ("both_hit" if base_rank <= 6 and cand_rank <= 6 else
                     "gained" if base_rank > 6 and cand_rank <= 6 else
                     "lost" if base_rank <= 6 and cand_rank > 6 else "both_miss")
        base_conc = probability_concentration(base, "baseline")
        cand_conc = probability_concentration(cand, "candidate")
        score_gaps = race_score_gaps(group)
        history = race_history_features(group, state)
        ticket_contribution = candidate_features[truth_idx] * beta
        if not math.isclose(float(ticket_contribution.sum()), float(cand_truth.relationship_energy),
                            rel_tol=0, abs_tol=1e-10):
            raise AssertionError(f"true-set beta terms do not sum to relationship energy: {race_id}")
        term_contrib = {f"beta_contribution__{name}": float(value)
                        for name, value in zip(jm.PAIR_FEATURES, ticket_contribution)}
        grouped_contrib = {
            f"beta_group_contribution__{name}": float(sum(
                ticket_contribution[list(jm.PAIR_FEATURES).index(term)] for term in terms
            ))
            for name, terms in PAIR_FEATURE_GROUPS.items()
        }
        candidate_order = cand.sort_values("canonical_rank", kind="stable")
        competitor_rank = 7 if cand_rank <= 6 else 6
        competitor = candidate_order.loc[
            candidate_order.canonical_rank.eq(competitor_rank)
        ].iloc[0]
        competitor_idx = int(competitor.name)
        competitor_contribution = candidate_features[competitor_idx] * beta
        term_contrast = ticket_contribution - competitor_contribution
        baseline_score_contrast = float(
            base.iloc[truth_idx].baseline_score_energy -
            base.iloc[competitor_idx].baseline_score_energy
        )
        candidate_contrast = float(cand_truth.total_energy - competitor.total_energy)
        if not math.isclose(candidate_contrast,
                            baseline_score_contrast + float(term_contrast.sum()),
                            rel_tol=0, abs_tol=1e-10):
            raise AssertionError(f"true-set/competitor energy decomposition differs: {race_id}")
        true_comp_terms = {
            f"true_minus_competitor__{name}": float(value)
            for name, value in zip(jm.PAIR_FEATURES, term_contrast)
        }
        true_comp_groups = {
            f"true_minus_competitor_group__{name}": float(sum(
                term_contrast[list(jm.PAIR_FEATURES).index(term)] for term in terms
            ))
            for name, terms in PAIR_FEATURE_GROUPS.items()
        }
        for name, value in zip(jm.PAIR_FEATURES, ticket_contribution):
            beta_rows.append({
                "race_id": race_id,
                "race_date": str(group.race_date.iloc[0]),
                "evaluation_year": year,
                "hit_class": hit_class,
                "true_set_ticket": truth_ticket,
                "term": name,
                "term_group": next(group_name for group_name, terms in PAIR_FEATURE_GROUPS.items()
                                   if name in terms),
                "beta": float(beta[list(jm.PAIR_FEATURES).index(name)]),
                "triple_feature": float(candidate_features[truth_idx, list(jm.PAIR_FEATURES).index(name)]),
                "beta_contribution": float(value),
            })

        run_history = group.copy()
        run_history["history_cutoff_dt"] = pd.to_datetime(run_history.history_cutoff, errors="coerce")
        run_history["latest_history_dt"] = pd.to_datetime(run_history.latest_history_date, errors="coerce")
        race_date_dt = pd.Timestamp(str(group.race_date.iloc[0]))
        cutoff_known = run_history.history_cutoff_dt.notna()
        latest_known = run_history.latest_history_dt.notna()
        cutoff_after_race = (run_history.history_cutoff_dt > race_date_dt).fillna(False)
        latest_after_cutoff = (
            run_history.latest_history_dt > run_history.history_cutoff_dt
        ).fillna(False)
        cutoff_too_recent = (
            run_history.history_cutoff_dt > (race_date_dt - pd.Timedelta(days=2))
        ).fillna(False)

        base_ticket_true = bool(truth_ticket in base_set)
        cand_ticket_true = bool(truth_ticket in cand_set)
        base_to_cut = float(base_truth.total_energy - base.loc[base.canonical_rank.eq(6), "total_energy"].iloc[0])
        cand_to_cut = float(cand_truth.total_energy - cand.loc[cand.canonical_rank.eq(6), "total_energy"].iloc[0])
        meta = {
            "race_id": race_id,
            "race_date": str(group.race_date.iloc[0]),
            "evaluation_year": year,
            "calendar_month": int(pd.Timestamp(str(group.race_date.iloc[0])).month),
            "distance_m": int(round(float(group.distance_m.iloc[0]))),
            "grade_raw": group.grade_raw.iloc[0] if pd.notna(group.grade_raw.iloc[0]) else None,
            "grade_condition": str(group.grade_raw.iloc[0]) if pd.notna(group.grade_raw.iloc[0]) else "__MISSING__",
            "field_n": len(group),
            "field_size_bin": "<=8" if len(group) <= 8 else "9-10" if len(group) <= 10 else ">=11",
            "baseline_hit6": arms["baseline"]["hit"],
            "candidate_hit6": arms["candidate"]["hit"],
            "delta_hit6": arms["candidate"]["hit"] - arms["baseline"]["hit"],
            "hit_class": hit_class,
            "selected_ticket_set_changed": bool(changed),
            "baseline_top6_ticket_count": len(base_set),
            "candidate_top6_ticket_count": len(cand_set),
            "top6_ticket_entered_count": len(entered),
            "top6_ticket_exited_count": len(exited),
            "actual_true_set_ticket": truth_ticket,
            "true_set_selected_baseline": base_ticket_true,
            "true_set_selected_candidate": cand_ticket_true,
            "true_set_baseline_rank": base_rank,
            "true_set_candidate_rank": cand_rank,
            "true_set_rank_delta_candidate_minus_baseline": cand_rank - base_rank,
            "true_set_baseline_probability": float(base_truth.probability),
            "true_set_candidate_probability": float(cand_truth.probability),
            "true_set_probability_delta_candidate_minus_baseline": float(cand_truth.probability - base_truth.probability),
            "true_set_baseline_energy": float(base_truth.total_energy),
            "true_set_candidate_energy": float(cand_truth.total_energy),
            "true_set_candidate_relationship_energy": float(cand_truth.relationship_energy),
            "true_set_baseline_energy_to_rank6_cutoff": base_to_cut,
            "true_set_candidate_energy_to_rank6_cutoff": cand_to_cut,
            "candidate_true_set_boundary_competitor_ticket": str(competitor.triple_numbers),
            "candidate_true_set_boundary_competitor_rank": competitor_rank,
            "candidate_true_minus_competitor_energy": candidate_contrast,
            "candidate_true_minus_competitor_baseline_score_energy": baseline_score_contrast,
            "candidate_true_minus_competitor_relationship_energy": float(term_contrast.sum()),
            "candidate_true_minus_competitor_exact_energy_tie": bool(candidate_contrast == 0.0),
            "candidate_true_minus_competitor_tolerance_energy_tie": bool(abs(candidate_contrast) <= ENERGY_TIE_TOL),
            "candidate_true_stable_order_precedes_competitor": bool(cand_rank < competitor_rank),
            "history_cutoff_missing_runner_count": int((~cutoff_known).sum()),
            "latest_history_date_missing_runner_count": int((~latest_known).sum()),
            "history_cutoff_after_race_runner_count": int(cutoff_after_race.sum()),
            "latest_history_after_cutoff_runner_count": int(latest_after_cutoff.sum()),
            "history_cutoff_within_two_days_runner_count": int(cutoff_too_recent.sum()),
            **base_conc,
            **cand_conc,
            **score_gaps,
            **history,
            **term_contrib,
            **grouped_contrib,
            **true_comp_terms,
            **true_comp_groups,
        }
        race_rows.append(meta)

        contrast_rows.append({
            "race_id": race_id,
            "race_date": str(group.race_date.iloc[0]),
            "evaluation_year": year,
            "hit_class": hit_class,
            "actual_true_set_ticket": truth_ticket,
            "actual_true_set_candidate_rank": cand_rank,
            "candidate_boundary_competitor_rule": "rank7_if_true_in_top6_else_rank6",
            "candidate_boundary_competitor_ticket": str(competitor.triple_numbers),
            "candidate_boundary_competitor_rank": competitor_rank,
            "candidate_true_set_in_top6": bool(cand_rank <= 6),
            "candidate_true_minus_competitor_energy": candidate_contrast,
            "candidate_true_minus_competitor_baseline_score_energy": baseline_score_contrast,
            "candidate_true_minus_competitor_relationship_energy": float(term_contrast.sum()),
            "candidate_true_minus_competitor_exact_energy_tie": bool(candidate_contrast == 0.0),
            "candidate_true_minus_competitor_tolerance_energy_tie": bool(abs(candidate_contrast) <= ENERGY_TIE_TOL),
            "candidate_true_stable_order_precedes_competitor": bool(cand_rank < competitor_rank),
            **true_comp_terms,
            **true_comp_groups,
        })

        common_boundary = {
            "race_id": race_id,
            "race_date": str(group.race_date.iloc[0]),
            "evaluation_year": year,
            "hit_class": hit_class,
            "actual_true_set_ticket": truth_ticket,
            "true_set_baseline_rank": base_rank,
            "true_set_candidate_rank": cand_rank,
            "true_set_baseline_probability": float(base_truth.probability),
            "true_set_candidate_probability": float(cand_truth.probability),
            "true_set_candidate_relationship_energy": float(cand_truth.relationship_energy),
            "entered_candidate_count": len(entered),
            "exited_baseline_count": len(exited),
            "selected_ticket_set_changed": bool(changed),
        }
        boundary_rows.append({**common_boundary, **base_conc, **cand_conc})

        fold_checks.setdefault(str(year), {"races": 0, "runners": 0, "triples_per_arm": 0})
        fold_checks[str(year)]["races"] += 1
        fold_checks[str(year)]["runners"] += len(group)
        fold_checks[str(year)]["triples_per_arm"] += expected_n

    race_ledger = pd.DataFrame(race_rows).sort_values(["race_date", "race_id"], kind="stable").reset_index(drop=True)
    if len(race_ledger) != 1779:
        raise AssertionError("complete race ledger does not contain 1,779 races")
    if int(race_ledger.hit_class.eq("gained").sum()) != 50 or int(race_ledger.hit_class.eq("lost").sum()) != 34:
        raise AssertionError("saved gained/lost outcome counts differ from fixed task scope")
    if int(race_ledger.selected_ticket_set_changed.sum()) != 1077:
        raise AssertionError("saved changed selection set count differs from fixed task scope")
    if int((~race_ledger.selected_ticket_set_changed).sum()) != 702:
        raise AssertionError("saved unchanged selection set count differs from fixed task scope")
    if race_ledger.history_cutoff_after_race_runner_count.sum() > 0:
        raise AssertionError("history_cutoff occurs after a race date")
    return (race_ledger, pd.DataFrame(beta_rows), pd.DataFrame(boundary_rows),
            pd.DataFrame(ticket_change_rows), pd.DataFrame(contrast_rows), fold_checks)


def mechanical_cases(race_ledger: pd.DataFrame) -> pd.DataFrame:
    records = []
    for year in (2024, 2025, 2026):
        year_rows = race_ledger.loc[race_ledger.evaluation_year.eq(year)]
        candidates = [
            ("gained_smallest_positive_rank_improvement",
             year_rows.loc[year_rows.hit_class.eq("gained")].assign(
                 selection_magnitude=lambda x: -x.true_set_rank_delta_candidate_minus_baseline)),
            ("lost_smallest_positive_rank_deterioration",
             year_rows.loc[year_rows.hit_class.eq("lost")].assign(
                 selection_magnitude=lambda x: x.true_set_rank_delta_candidate_minus_baseline)),
            ("both_miss_improved_but_outside_six",
             year_rows.loc[year_rows.hit_class.eq("both_miss") &
                           year_rows.true_set_rank_delta_candidate_minus_baseline.lt(0)]
             .assign(selection_magnitude=lambda x: x.true_set_candidate_rank)),
        ]
        for rule, eligible in candidates:
            eligible = eligible.sort_values(["selection_magnitude", "race_id"], kind="stable")
            if eligible.empty:
                records.append({"evaluation_year": year, "selection_rule": rule,
                                "case_available": False})
                continue
            row = eligible.iloc[0]
            records.append({
                "evaluation_year": year,
                "selection_rule": rule,
                "case_available": True,
                "race_id": row.race_id,
                "race_date": row.race_date,
                "hit_class": row.hit_class,
                "true_set_ticket": row.actual_true_set_ticket,
                "baseline_true_set_rank": int(row.true_set_baseline_rank),
                "candidate_true_set_rank": int(row.true_set_candidate_rank),
                "rank_delta_candidate_minus_baseline": int(row.true_set_rank_delta_candidate_minus_baseline),
                "baseline_true_set_probability": float(row.true_set_baseline_probability),
                "candidate_true_set_probability": float(row.true_set_candidate_probability),
                "baseline_energy_margin_6_7": float(row.baseline_energy_margin_6_7),
                "candidate_energy_margin_6_7": float(row.candidate_energy_margin_6_7),
                "baseline_effective_triples_exp_entropy": float(row.baseline_effective_triples_exp_entropy),
                "candidate_effective_triples_exp_entropy": float(row.candidate_effective_triples_exp_entropy),
                "baseline_candidate_top6_sets_changed": bool(row.selected_ticket_set_changed),
                "selection_magnitude": float(row.selection_magnitude),
            })
    return pd.DataFrame(records)


def build_history_timing_audit(race_ledger: pd.DataFrame) -> dict:
    all_runners = int(race_ledger.history_cutoff_missing_runner_count.sum())
    cohort_runners = 17412
    if all_runners > cohort_runners:
        raise AssertionError("timing audit runner count exceeds fixed cohort")
    return {
        "race_rows": int(len(race_ledger)),
        "runner_rows": cohort_runners,
        "cutoff_missing_runner_rows": all_runners,
        "latest_history_date_missing_runner_rows": int(
            race_ledger.latest_history_date_missing_runner_count.sum()),
        "history_cutoff_after_race_runner_rows": int(
            race_ledger.history_cutoff_after_race_runner_count.sum()),
        "latest_history_after_cutoff_runner_rows": int(
            race_ledger.latest_history_after_cutoff_runner_count.sum()),
        "history_cutoff_within_two_days_runner_rows": int(
            race_ledger.history_cutoff_within_two_days_runner_count.sum()),
        "interpretation": (
            "This checks saved history date fields only. It does not establish the first public "
            "release time of source observations; the saved study input contract and publication "
            "time limits remain applicable."
        ),
    }


def main() -> None:
    if OUT.exists() or FINAL_OUT.exists():
        raise FileExistsError(f"refusing to overwrite analysis outputs: {FINAL_OUT}")
    contract = json.loads(INPUT_CONTRACT_PATH.read_text(encoding="utf-8"))
    source_hashes = verify_input_hashes(contract)
    metrics, runner_saved, triples, features, loaded = load_fixed_inputs(contract)
    eval_runner, triples, metrics, folds = verify_saved_predictions(
        metrics, runner_saved, triples, features, loaded["scores"], loaded["params"])
    (race_ledger, beta_long, boundary, ticket_changes, true_set_contrasts,
     fold_checks) = make_race_ledgers(
        eval_runner, triples, metrics, folds)

    race_ledger["month"] = race_ledger.calendar_month
    full = race_ledger.copy()
    gains_losses = race_ledger.loc[race_ledger.hit_class.isin(["gained", "lost"])].copy()
    if len(gains_losses) != 84:
        raise AssertionError("gained/lost ledger is not the complete 84-race set")
    condition = build_condition_table(race_ledger)
    continuous = continuous_summary(race_ledger, race_ledger)
    missing = missingness_summary(eval_runner, race_ledger)
    beta_summary = beta_long.groupby(["hit_class", "term_group", "term"], as_index=False,
                                     sort=True, observed=True).agg(
        races=("race_id", "nunique"),
        contribution_mean=("beta_contribution", "mean"),
        contribution_median=("beta_contribution", "median"),
        contribution_p25=("beta_contribution", lambda s: s.quantile(0.25)),
        contribution_p75=("beta_contribution", lambda s: s.quantile(0.75)),
    )
    # The row-wise group sums are already additive at race x term grain; summarize
    # those totals by outcome rather than summing all term rows into one scalar.
    group_totals = beta_long.groupby(["race_id", "hit_class", "term_group"], as_index=False,
                                     sort=True, observed=True).beta_contribution.sum()
    beta_group_summary = group_totals.groupby(["hit_class", "term_group"], as_index=False,
                                              sort=True, observed=True).agg(
        races=("race_id", "nunique"),
        grouped_contribution_mean=("beta_contribution", "mean"),
        grouped_contribution_median=("beta_contribution", "median"),
        grouped_contribution_p25=("beta_contribution", lambda s: s.quantile(0.25)),
        grouped_contribution_p75=("beta_contribution", lambda s: s.quantile(0.75)),
    )
    cases = mechanical_cases(race_ledger)

    OUT.mkdir(mode=0o700, parents=False, exist_ok=False)
    write_csv_new(OUT / "race_ledger_1779.csv", full)
    write_csv_new(OUT / "gain_loss_84.csv", gains_losses)
    write_csv_new(OUT / "condition_summary.csv", condition)
    write_csv_new(OUT / "continuous_features_by_outcome.csv", continuous)
    write_csv_new(OUT / "feature_missingness_by_outcome.csv", missing)
    write_csv_new(OUT / "true_set_beta_contributions.csv", beta_long)
    write_csv_new(OUT / "beta_decomposition_by_outcome.csv", beta_summary)
    write_csv_new(OUT / "beta_group_decomposition_by_outcome.csv", beta_group_summary)
    write_csv_new(OUT / "selection_boundary_detail_1779.csv", boundary)
    write_csv_new(OUT / "selected_ticket_changes.csv", ticket_changes)
    write_csv_new(OUT / "true_set_boundary_competitor_1779.csv", true_set_contrasts)
    write_csv_new(OUT / "mechanical_cases.csv", cases)
    timing_audit = build_history_timing_audit(race_ledger)
    write_json_new(OUT / "history_timing_audit.json", timing_audit)

    outcome_counts = race_ledger.hit_class.value_counts().sort_index().to_dict()
    source_metric_delta = int(metrics.delta_hit6.sum())
    ledger_delta = int(race_ledger.delta_hit6.sum())
    if source_metric_delta != ledger_delta:
        raise AssertionError("race ledger net hits differ from saved race_metrics")
    entry_counts = ticket_changes.side.value_counts().to_dict()
    if entry_counts.get("entered_candidate", 0) != entry_counts.get("exited_baseline", 0):
        raise AssertionError("selected ticket entry/exit counts do not balance")
    if int(race_ledger.top6_ticket_entered_count.sum()) != entry_counts.get("entered_candidate", 0):
        raise AssertionError("ticket change detail does not match per-race ledger")
    receipt = {
        "analysis": "20261010_joint_gain_loss_v1",
        "status": "completed_no_fit_retrospective_analysis",
        "analysis_plan_sha256": sha256(PLAN_PATH),
        "input_contract_sha256": sha256(INPUT_CONTRACT_PATH),
        "input_hashes_verified": source_hashes,
        "cohort": {
            "races": int(len(race_ledger)),
            "runner_rows": int(len(eval_runner)),
            "race_days": int(race_ledger.race_date.nunique()),
            "period_start": str(race_ledger.race_date.min()),
            "period_end": str(race_ledger.race_date.max()),
            "partial_2026": True,
        },
        "outcome_counts": outcome_counts,
        "selection_changed_races": int(race_ledger.selected_ticket_set_changed.sum()),
        "selection_unchanged_races": int((~race_ledger.selected_ticket_set_changed).sum()),
        "net_hit_delta": ledger_delta,
        "ticket_changes": entry_counts,
        "fold_reconstruction_checks": fold_checks,
        "relationship_decomposition": {
            "terms": list(jm.PAIR_FEATURES),
            "groups": PAIR_FEATURE_GROUPS,
            "all_race_candidate_energy_reconstruction_tolerance": 1e-10,
            "contribution_sum_tolerance": 1e-10,
            "decomposition_target": "actual unordered Top3 triple per race",
        },
        "paired_date_bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
            "interval": "pointwise percentile 95%",
        },
        "fit_or_training_executed": False,
        "database_or_network_accessed": False,
        "history_timing_audit": timing_audit,
        "output_files": {},
    }
    for path in sorted(OUT.iterdir()):
        if path.is_file():
            receipt["output_files"][path.name] = {
                "sha256": sha256(path),
                "bytes": int(path.stat().st_size),
            }
    write_json_new(OUT / "analysis_receipt.json", receipt)
    OUT.rename(FINAL_OUT)
    print(json.dumps({
        "status": receipt["status"],
        "cohort": receipt["cohort"],
        "outcome_counts": receipt["outcome_counts"],
        "selection_changed_races": receipt["selection_changed_races"],
        "net_hit_delta": receipt["net_hit_delta"],
        "output_dir": str(FINAL_OUT),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

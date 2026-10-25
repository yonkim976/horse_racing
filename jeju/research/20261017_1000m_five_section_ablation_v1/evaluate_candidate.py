"""One-pass frozen scoring, profile, and paired-metric report for the ablation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from feature_core import ADDED_FEATURES, SEGMENTS
from train_candidate import (
    BASELINE_REPLAY_PATH, BASE_COLUMNS, FEATURE_PATH, OUT, ROOT, STYLE, STYLE_OUT,
    VARIANT, YEARS, sha256, write_json_new, write_parquet_new,
)


HERE = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "jeju/research/20261017_1000m_five_section_source_audit_v1"
BOOTSTRAP_PATH = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT_PATH = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
LOCK_PATH = OUT / "evaluation_source_lock.json"
RECEIPT_PATH = OUT / "evaluation_report_receipt.json"
SCHEDULE_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
DATE_INVENTORY_SHA = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
PRIMARY_METRICS = ("log_loss", "brier")
SECONDARY_RACE_METRICS = (
    "trio_nll", "six_combo_hit", "six_combo_mass", "top3_capture", "top3_all3",
    "top4_capture", "top4_all3", "top5_capture", "top5_all3", "top6_capture", "top6_all3",
    "pick_hit",
)
PROFILE_COLUMNS = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_name",
                   "horse_number", "history_cutoff", *ADDED_FEATURES]


def _verify_frozen_eval_inputs() -> tuple[dict, dict]:
    assert LOCK_PATH.is_file(), "freeze_evaluation_source.py must run before metric evaluation"
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["lock_status"] == "FROZEN_BEFORE_METRIC_EVALUATION"
    assert lock["evaluator_sha256"] == sha256(Path(__file__))
    freezer_path = HERE / "freeze_evaluation_source.py"
    assert lock["freezer_sha256"] == sha256(freezer_path)
    for relative, entry in lock["input_files"].items():
        path = ROOT / relative
        assert path.is_file(), f"missing frozen report input: {relative}"
        assert path.stat().st_size == int(entry["bytes"]), f"frozen report size changed: {relative}"
        assert sha256(path) == entry["sha256"], f"frozen report input hash changed: {relative}"
    approval = json.loads((OUT / "root_fit_approval.json").read_text(encoding="utf-8"))
    completion = json.loads((OUT / "candidate_training_completion.json").read_text(encoding="utf-8"))
    assert approval.get("approved") is True and approval.get("approved_by") == "root"
    assert completion.get("passed") is True and completion.get("candidate_models") == 3
    assert completion.get("lightgbm_train_calls") == 6
    assert completion.get("temperature_optimizations") == 3
    assert completion.get("candidate_outcome_metrics_computed") is False
    return lock, completion


def _profile_table(features: pd.DataFrame, slot_ledger: pd.DataFrame) -> pd.DataFrame:
    target = features.loc[pd.to_numeric(features.distance_m, errors="raise").eq(1000), PROFILE_COLUMNS].copy()
    assert len(target) == 14457 and target.api_record_id.is_unique
    history = slot_ledger.sort_values(
        ["target_api_record_id", "slot_oldest_to_newest"], kind="stable"
    ).groupby("target_api_record_id", sort=False).agg(
        last5_source_ids=("source_api_record_id", lambda values: ";".join(map(str, values.astype("int64")))),
        last5_source_dates=("source_race_date", lambda values: ";".join(map(str, values.astype("string")))),
    ).reset_index().rename(columns={"target_api_record_id": "api_record_id"})
    target = target.merge(history, on="api_record_id", how="left", validate="one_to_one", sort=False)
    target["last5_source_ids"] = target.last5_source_ids.fillna("")
    target["last5_source_dates"] = target.last5_source_dates.fillna("")
    assert target.api_record_id.is_unique and len(target) == 14457
    target = target.sort_values(["race_date", "race_id", "horse_number", "api_record_id"], kind="stable")
    return target.reset_index(drop=True)


def _profile_examples(profiles: pd.DataFrame) -> pd.DataFrame:
    """Choose evaluation examples using only key order and history support."""
    target = profiles.loc[profiles.year.isin(YEARS)].sort_values(
        ["race_date", "race_id", "horse_number", "api_record_id"], kind="stable"
    )
    rows = []
    for spec in SEGMENTS:
        n_column = spec["n"]
        buckets = (
            ("n0", target[n_column].eq(0)),
            ("n1", target[n_column].eq(1)),
            ("n2_to_4", target[n_column].between(2, 4)),
            ("n5", target[n_column].eq(5)),
        )
        for label, mask in buckets:
            eligible = target.loc[mask]
            assert len(eligible) > 0, f"predeclared example support bucket missing: {spec['key']} {label}"
            row = eligible.iloc[0]
            rows.append({
                "segment": spec["key"],
                "support_bucket": label,
                "api_record_id": int(row.api_record_id),
                "race_id": row.race_id,
                "race_date": row.race_date,
                "horse_id": row.horse_id,
                "horse_name": row.horse_name,
                "horse_number": int(row.horse_number),
                "history_cutoff_t_minus_2": row.history_cutoff,
                "history_mean_seconds": row[spec["mean"]],
                "valid_history_n_0_to_5": int(row[n_column]),
                "last5_source_ids_oldest_to_newest": row.last5_source_ids,
                "last5_source_dates_oldest_to_newest": row.last5_source_dates,
            })
    result = pd.DataFrame(rows)
    assert len(result) == len(SEGMENTS) * 4
    return result


def _with_pick_hit(races: pd.DataFrame, runners: pd.DataFrame) -> pd.DataFrame:
    picks = []
    for race_id, group in runners.groupby("race_id", sort=False):
        best = group.sort_values("score", ascending=False, kind="stable").iloc[0]
        picks.append({"race_id": race_id, "pick_hit": int(best.y)})
    result = races.merge(pd.DataFrame(picks), on="race_id", how="left", validate="one_to_one")
    assert result.pick_hit.notna().all()
    return result


def _make_candidate_evaluation(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    race_frames, runner_frames, ticket_frames = [], [], []
    for year in YEARS:
        folder = OUT / f"{VARIANT}_{year}"
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        assert meta["variant"] == VARIANT and int(meta["evaluation_year"]) == year
        assert meta["features"] == BASE_COLUMNS + ADDED_FEATURES and int(meta["feature_count"]) == 40
        score = pd.read_parquet(folder / "evaluation_scores.parquet")
        test = features.loc[features.year.eq(year)].reset_index(drop=True)
        assert len(test) == int(meta["evaluation_rows"])
        assert score.api_record_id.astype("int64").tolist() == test.api_record_id.astype("int64").tolist()
        raw = score.score.to_numpy(dtype="float64")
        race, runner, ticket = STYLE.OLD.evaluate(test, raw, float(meta["tau"]), VARIANT)
        race_frames.append(race)
        runner_frames.append(runner)
        ticket_frames.append(ticket)
    races = _with_pick_hit(pd.concat(race_frames, ignore_index=True), pd.concat(runner_frames, ignore_index=True))
    runners = pd.concat(runner_frames, ignore_index=True)
    tickets = pd.concat(ticket_frames, ignore_index=True)
    assert len(runners) == 17412 and runners.api_record_id.is_unique
    assert races.race_id.nunique() == 1779 and races.race_id.is_unique
    assert len(tickets) == 10674
    return races, runners, tickets


def _paired_frames(candidate_races: pd.DataFrame, candidate_runners: pd.DataFrame,
                   baseline_races: pd.DataFrame, baseline_runners: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    runner_keys = ["api_record_id", "race_id", "race_date", "year", "distance_m", "horse_id", "horse_number"]
    left = candidate_runners.rename(columns={
        "variant": "variant_candidate", "score": "score_candidate", "p_top3": "p_top3_candidate",
        "log_loss": "log_loss_candidate", "brier": "brier_candidate", "y": "y_candidate",
    })
    right = baseline_runners.rename(columns={
        "variant": "variant_baseline", "score": "score_baseline", "p_top3": "p_top3_baseline",
        "log_loss": "log_loss_baseline", "brier": "brier_baseline", "y": "y_baseline",
    })
    paired_runners = left.merge(right, on=runner_keys, how="inner", validate="one_to_one")
    assert len(paired_runners) == 17412 and paired_runners.api_record_id.is_unique
    assert paired_runners.y_candidate.astype("int8").equals(paired_runners.y_baseline.astype("int8"))

    race_keys = ["race_id", "race_date", "year", "distance_m", "field_n"]
    candidate = candidate_races.rename(columns={
        "variant": "variant_candidate",
        **{metric: f"{metric}_candidate" for metric in (
            "log_loss", "brier", *SECONDARY_RACE_METRICS, "pick_hit"
        )},
    })
    baseline = baseline_races.rename(columns={
        "variant": "variant_baseline",
        **{metric: f"{metric}_baseline" for metric in (
            "log_loss", "brier", *SECONDARY_RACE_METRICS, "pick_hit"
        )},
    })
    paired_races = candidate.merge(baseline, on=race_keys, how="inner", validate="one_to_one")
    assert len(paired_races) == 1779 and paired_races.race_id.is_unique
    return paired_runners, paired_races


def _paired_tickets(candidate_tickets: pd.DataFrame, baseline_tickets: pd.DataFrame) -> pd.DataFrame:
    keys = ["race_id", "selection_rank"]
    left = candidate_tickets[keys + ["numbers", "probability", "hit"]].rename(columns={
        "numbers": "numbers_candidate", "probability": "probability_candidate", "hit": "hit_candidate",
    })
    right = baseline_tickets[keys + ["numbers", "probability", "hit"]].rename(columns={
        "numbers": "numbers_baseline", "probability": "probability_baseline", "hit": "hit_baseline",
    })
    paired = left.merge(right, on=keys, how="inner", validate="one_to_one")
    assert len(paired) == 10674 and paired.race_id.nunique() == 1779
    assert paired.groupby("race_id").selection_rank.nunique().eq(6).all()
    return paired


def _date_support(features: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    eval_rows = features.loc[features.year.isin(YEARS), ["race_id", "race_date", "distance_m"]].drop_duplicates()
    eval_rows["is_1000m"] = pd.to_numeric(eval_rows.distance_m, errors="raise").eq(1000)
    counts = eval_rows.groupby("race_date", sort=True).agg(
        all_evaluation_races=("race_id", "nunique"),
        primary_1000m_races=("is_1000m", "sum"),
    )
    full = pd.DataFrame({"race_date": dates}).set_index("race_date").join(counts, how="left").fillna(0).reset_index()
    full["all_evaluation_races"] = full.all_evaluation_races.astype("int64")
    full["primary_1000m_races"] = full.primary_1000m_races.astype("int64")
    assert len(full) == 269 and full.primary_1000m_races.sum() == 508
    return full


def _bootstrap_values(paired: pd.DataFrame, metric: str, dates: list[str], schedule: np.ndarray) -> tuple[float, float, float, np.ndarray, int]:
    delta = pd.to_numeric(paired[f"{metric}_candidate"], errors="raise").to_numpy(dtype="float64") - \
        pd.to_numeric(paired[f"{metric}_baseline"], errors="raise").to_numpy(dtype="float64")
    assert np.isfinite(delta).all()
    date_to_index = {date: index for index, date in enumerate(dates)}
    daily_sum = np.zeros(len(dates), dtype="float64")
    daily_count = np.zeros(len(dates), dtype="int64")
    for date, value in zip(paired.race_date.astype("string"), delta):
        idx = date_to_index[str(date)]
        daily_sum[idx] += value
        daily_count[idx] += 1
    point = float(delta.mean())
    numerator = daily_sum[schedule].sum(axis=1)
    denominator = daily_count[schedule].sum(axis=1)
    valid = denominator > 0
    draws = np.full(schedule.shape[0], np.nan, dtype="float64")
    draws[valid] = numerator[valid] / denominator[valid]
    valid_draws = draws[valid]
    if len(valid_draws):
        low, high = float(np.quantile(valid_draws, .025)), float(np.quantile(valid_draws, .975))
    else:
        low = high = float("nan")
    return point, low, high, draws, int(valid.sum())


def _scope_comparisons(paired_races: pd.DataFrame, dates: list[str], schedule: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    scopes: list[tuple[str, str, pd.DataFrame]] = [("all_eval", "all", paired_races)]
    primary = paired_races.loc[paired_races.distance_m.eq(1000)].copy()
    scopes.append(("1000m_primary", "2024_2026", primary))
    for year in YEARS:
        scopes.append(("all_distances_by_year", str(year), paired_races.loc[paired_races.year.eq(year)]))
        scopes.append(("1000m_by_year", str(year), paired_races.loc[
            paired_races.year.eq(year) & paired_races.distance_m.eq(1000)
        ]))
    for distance, group in paired_races.groupby("distance_m", sort=True):
        scopes.append(("distance_auxiliary", str(int(distance)), group))

    metric_names = ("log_loss", "brier", *SECONDARY_RACE_METRICS)
    summary_rows, draw_rows = [], []
    for kind, label, group in scopes:
        if group.empty:
            continue
        for metric in metric_names:
            c = group[f"{metric}_candidate"].to_numpy(dtype="float64")
            b = group[f"{metric}_baseline"].to_numpy(dtype="float64")
            point, low, high, draws, valid_draws = _bootstrap_values(group, metric, dates, schedule)
            if kind == "1000m_primary":
                assert valid_draws == schedule.shape[0], "primary 1000m CI requires all fixed draws to have races"
            summary_rows.append({
                "scope": kind, "scope_value": label, "metric": metric,
                "races": int(group.race_id.nunique()), "race_days_with_rows": int(group.race_date.nunique()),
                "candidate_mean": float(np.mean(c)), "baseline_mean": float(np.mean(b)),
                "candidate_total": float(np.sum(c)), "baseline_total": float(np.sum(b)),
                "candidate_minus_baseline": point, "paired_date_ci95_low": low,
                "paired_date_ci95_high": high, "bootstrap_dates_per_draw": int(schedule.shape[1]),
                "bootstrap_draws": int(schedule.shape[0]),
                "valid_bootstrap_draws": valid_draws,
                "zero_denominator_draws_excluded_from_ci": int(schedule.shape[0] - valid_draws),
            })
            if kind == "1000m_primary" and metric in PRIMARY_METRICS:
                draw_rows.extend({
                    "metric": metric, "draw": int(index), "candidate_minus_baseline": float(value)
                } for index, value in enumerate(draws) if np.isfinite(value))
    summary = pd.DataFrame(summary_rows)
    primary_summary = summary.loc[
        summary.scope.eq("1000m_primary") & summary.metric.isin(PRIMARY_METRICS)
    ].copy()
    assert len(primary_summary) == 2
    point = {row.metric: float(row.candidate_minus_baseline) for row in primary_summary.itertuples(index=False)}
    upper = {row.metric: float(row.paired_date_ci95_high) for row in primary_summary.itertuples(index=False)}
    gate = bool(all(point[metric] < 0 for metric in PRIMARY_METRICS)
                and any(upper[metric] < 0 for metric in PRIMARY_METRICS))
    gate_receipt = {
        "primary_gate_passed": gate,
        "required_both_runner_binary_logloss_and_brier_point_estimates_improve": True,
        "required_at_least_one_primary_date_paired_ci_upper_below_zero": True,
        "primary_candidate_minus_baseline": point,
        "primary_paired_date_ci95_upper": upper,
        "primary_races": int(primary.race_id.nunique()),
        "primary_runner_rows": int(paired_races.loc[paired_races.distance_m.eq(1000), "field_n"].sum()),
        "bootstrap_schedule_shape": [int(schedule.shape[0]), int(schedule.shape[1])],
        "bootstrap_date_inventory_count": len(dates),
        "bootstrap_dates_without_1000m_contribute_zero_sum_and_count": True,
    }
    return summary, pd.DataFrame(draw_rows), gate_receipt


def _runner_scope_summary(paired_runners: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    context = features[["api_record_id", "distance_m", "year"] + ADDED_FEATURES].copy()
    rows = paired_runners.merge(context, on=["api_record_id", "distance_m", "year"], how="left", validate="one_to_one")
    assert len(rows) == 17412
    rows["is_top3_candidate"] = rows.y_candidate.astype("int8")
    scopes = [("all_eval", "all", rows),
              ("1000m_primary", "2024_2026", rows.loc[rows.distance_m.eq(1000)])]
    for year in YEARS:
        scopes.append(("all_distances_by_year", str(year), rows.loc[rows.year.eq(year)]))
        scopes.append(("1000m_by_year", str(year), rows.loc[rows.year.eq(year) & rows.distance_m.eq(1000)]))
    for distance, group in rows.groupby("distance_m", sort=True):
        scopes.append(("distance_auxiliary", str(int(distance)), group))
    result = []
    for kind, label, group in scopes:
        for metric in ("log_loss", "brier"):
            result.append({
                "scope": kind,
                "scope_value": label,
                "metric": f"runner_{metric}_race_equal",
                "races": int(group.race_id.nunique()),
                "runner_rows": int(len(group)),
                "candidate_mean_within_race_then_race_equal": float(
                    group.groupby("race_id")[f"{metric}_candidate"].mean().mean()
                ) if len(group) else np.nan,
                "baseline_mean_within_race_then_race_equal": float(
                    group.groupby("race_id")[f"{metric}_baseline"].mean().mean()
                ) if len(group) else np.nan,
            })
    return pd.DataFrame(result)


def _write_output(path: Path, frame: pd.DataFrame, *, csv: bool = False) -> None:
    assert not path.exists(), f"refusing to overwrite report output: {path.name}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if csv:
        frame.to_csv(path, index=False)
    else:
        write_parquet_new(path, frame)


def evaluate() -> dict:
    assert not RECEIPT_PATH.exists(), "report already ran; post-hoc reruns are prohibited"
    lock, completion = _verify_frozen_eval_inputs()
    features = pd.read_parquet(FEATURE_PATH)
    assert len(features) == 52155 and features.api_record_id.is_unique
    assert list(features.loc[:, BASE_COLUMNS].columns) == BASE_COLUMNS
    assert list(features.columns[-len(ADDED_FEATURES):]) == ADDED_FEATURES
    source_slots = pd.read_parquet(OUT / "historical_section_slot_ledger.parquet")
    profiles = _profile_table(features, source_slots)
    examples = _profile_examples(profiles)

    candidate_races, candidate_runners, candidate_tickets = _make_candidate_evaluation(features)
    baseline_races = pd.read_parquet(OUT / "baseline_replayed_race_metrics.parquet")
    baseline_runners = pd.read_parquet(OUT / "baseline_replayed_runner_predictions.parquet")
    baseline_tickets = pd.read_parquet(OUT / "baseline_replayed_canonical_max6.parquet")
    baseline_races = _with_pick_hit(baseline_races, baseline_runners)
    paired_runners, paired_races = _paired_frames(
        candidate_races, candidate_runners, baseline_races, baseline_runners
    )
    paired_tickets = _paired_tickets(candidate_tickets, baseline_tickets)
    saved_labels = features[["api_record_id", "finish_position"]].copy()
    saved_labels["expected_y"] = saved_labels.finish_position.le(3).astype("int8")
    label_check = paired_runners[["api_record_id", "y_candidate"]].merge(
        saved_labels[["api_record_id", "expected_y"]], on="api_record_id", how="left", validate="one_to_one"
    )
    assert label_check.expected_y.notna().all()
    assert label_check.expected_y.astype("int8").equals(label_check.y_candidate.astype("int8"))
    assert len(paired_runners.loc[paired_runners.distance_m.eq(1000)]) == 5013
    assert paired_races.loc[paired_races.distance_m.eq(1000), "race_id"].nunique() == 508
    assert paired_races.loc[paired_races.distance_m.eq(1000)].groupby("year").race_id.nunique().to_dict() == {
        2024: 170, 2025: 196, 2026: 142,
    }

    schedule_receipt = json.loads(BOOTSTRAP_RECEIPT_PATH.read_text(encoding="utf-8"))
    dates = sorted(features.loc[features.year.isin(YEARS), "race_date"].astype("string").unique().tolist())
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    schedule = np.load(BOOTSTRAP_PATH, allow_pickle=False)
    assert len(dates) == 269 and schedule.shape == (2000, 269)
    assert date_hash == DATE_INVENTORY_SHA == schedule_receipt["date_inventory_sha256"]
    assert sha256(BOOTSTRAP_PATH) == SCHEDULE_SHA == schedule_receipt["schedule_sha256"]
    assert schedule.dtype.kind in "iu" and schedule.min() >= 0 and schedule.max() < 269

    date_support = _date_support(features, dates)
    race_comparison, primary_draws, gate = _scope_comparisons(paired_races, dates, schedule)
    runner_summary = _runner_scope_summary(paired_runners, features)
    primary_abs = race_comparison.loc[
        race_comparison.scope.eq("1000m_primary") & race_comparison.metric.isin(PRIMARY_METRICS)
    ].merge(
        runner_summary.loc[
            runner_summary.scope.eq("1000m_primary")
            & runner_summary.metric.str.startswith("runner_")
        ].assign(metric=lambda frame: frame.metric.str.removeprefix("runner_").str.removesuffix("_race_equal")),
        on=["scope", "scope_value", "metric"], suffixes=("_race", "_runner"), validate="one_to_one",
    )
    assert len(primary_abs) == 2
    assert np.allclose(primary_abs.candidate_mean, primary_abs.candidate_mean_within_race_then_race_equal,
                       rtol=0, atol=1e-12)
    assert np.allclose(primary_abs.baseline_mean, primary_abs.baseline_mean_within_race_then_race_equal,
                       rtol=0, atol=1e-12)
    candidate_profiles = profiles.loc[profiles.year.isin(YEARS)].copy()
    eval_context = candidate_profiles[["api_record_id", "horse_name", *ADDED_FEATURES]]
    human_runner = paired_runners.loc[paired_runners.distance_m.eq(1000)].merge(
        eval_context, on="api_record_id", how="left", validate="one_to_one"
    ).sort_values(["race_date", "race_id", "horse_number"], kind="stable")
    assert len(human_runner) == 5013 and human_runner.horse_name.notna().all()
    human_races = paired_races.loc[paired_races.distance_m.eq(1000)].sort_values(
        ["race_date", "race_id"], kind="stable"
    )

    # Fixed, outcome-independent artifacts are written only after the input and
    # model/source lock has been checked. All metric data derive from saved OOS scores.
    _write_output(OUT / "candidate_evaluation_runner_predictions.parquet", candidate_runners)
    _write_output(OUT / "candidate_evaluation_race_metrics.parquet", candidate_races)
    _write_output(OUT / "candidate_evaluation_canonical_max6.parquet", candidate_tickets)
    _write_output(OUT / "paired_runner_metrics.parquet", paired_runners)
    _write_output(OUT / "paired_race_metrics.parquet", paired_races)
    _write_output(OUT / "paired_canonical_max6.parquet", paired_tickets)
    _write_output(OUT / "evaluation_date_support.parquet", date_support)
    _write_output(OUT / "race_metric_comparisons.parquet", race_comparison)
    _write_output(OUT / "runner_metric_comparisons.parquet", runner_summary)
    _write_output(OUT / "primary_1000m_bootstrap_draws.parquet", primary_draws)
    _write_output(OUT / "all_1000m_profiles.parquet", profiles)
    _write_output(OUT / "profile_examples.csv", examples, csv=True)
    _write_output(OUT / "1000m_runner_comparison.parquet", human_runner)
    _write_output(OUT / "1000m_race_comparison.parquet", human_races)

    summary = {
        "report_status": "PASS_FROZEN_OOS_METRICS",
        "study": HERE.name,
        "candidate": VARIANT,
        "candidate_fit_completion_sha256": sha256(OUT / "candidate_training_completion.json"),
        "fit_approval_sha256": sha256(OUT / "root_fit_approval.json"),
        "evaluation_source_lock_sha256": sha256(LOCK_PATH),
        "candidate_oos_score_metrics_computed_once": True,
        "candidate_refit_after_evaluation": False,
        "baseline_refit": False,
        "candidate_model_count": int(completion["candidate_models"]),
        "lightgbm_train_calls": int(completion["lightgbm_train_calls"]),
        "temperature_optimizations": int(completion["temperature_optimizations"]),
        "baseline_full_eval_rows": 17412,
        "baseline_full_eval_races": 1779,
        "candidate_full_eval_rows": int(len(candidate_runners)),
        "candidate_full_eval_races": int(len(candidate_races)),
        "primary_1000m": gate,
        "all_1000m_profiles": int(len(profiles)),
        "human_profile_examples": int(len(examples)),
        "profile_example_selection": "For each interval and each n bucket (0,1,2-4,5), first 2024-2026 evaluation row sorted by race_date,race_id,horse_number,api_record_id; no outcomes used.",
        "target_race_endpoint_times_in_prediction_tables": False,
        "target_actual_top3_outcome_in_evaluation_runner_table": True,
        "source_section_point_notes": "S1F is the 200m mark; C3/C4 correspond approximately to 400m/600m elapsed boundaries in the split labels.",
        "production_changed": False,
        "database_changed": False,
        "operating_model_promoted": False,
        "bootstrap": {
            "schedule_path": str(BOOTSTRAP_PATH.relative_to(ROOT)),
            "schedule_sha256": sha256(BOOTSTRAP_PATH),
            "date_count": len(dates),
            "date_inventory_sha256": date_hash,
            "draws": int(schedule.shape[0]),
            "dates_per_draw": int(schedule.shape[1]),
        },
        "outputs": {},
    }
    output_names = [
        "candidate_evaluation_runner_predictions.parquet", "candidate_evaluation_race_metrics.parquet",
        "candidate_evaluation_canonical_max6.parquet", "paired_runner_metrics.parquet",
        "paired_race_metrics.parquet", "paired_canonical_max6.parquet", "evaluation_date_support.parquet",
        "race_metric_comparisons.parquet",
        "runner_metric_comparisons.parquet", "primary_1000m_bootstrap_draws.parquet",
        "all_1000m_profiles.parquet", "profile_examples.csv", "1000m_runner_comparison.parquet",
        "1000m_race_comparison.parquet",
    ]
    for name in output_names:
        path = OUT / name
        summary["outputs"][name] = {"bytes": int(path.stat().st_size), "sha256": sha256(path)}
    write_json_new(OUT / "evaluation_summary.json", summary)

    receipt = {
        "passed": True,
        "report_source_lock_sha256": sha256(LOCK_PATH),
        "evaluator_sha256": sha256(Path(__file__)),
        "candidate_training_completion_sha256": sha256(OUT / "candidate_training_completion.json"),
        "fit_approval_sha256": sha256(OUT / "root_fit_approval.json"),
        "candidate_oos_metrics_computed_once": True,
        "candidate_refit_after_metrics": False,
        "candidate_models": 3,
        "candidate_train_calls": 6,
        "candidate_temperature_optimizations": 3,
        "eval_rows": 17412,
        "eval_races": 1779,
        "primary_1000m_runner_rows": 5013,
        "primary_1000m_races": 508,
        "primary_gate_passed": gate["primary_gate_passed"],
        "production_changed": False,
        "database_changed": False,
        "outputs": summary["outputs"],
        "summary_sha256": sha256(OUT / "evaluation_summary.json"),
    }
    write_json_new(RECEIPT_PATH, receipt)
    return summary


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2, allow_nan=False, default=str))

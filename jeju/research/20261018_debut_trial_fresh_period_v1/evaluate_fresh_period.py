"""Score the two frozen 2026 models on the released fresh-period cohort.

This script loads saved model files and saved temperatures only. It never calls
training or calibration functions and writes only under this study's outputs/.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
SOURCE = ROOT / "jeju/research/20261018_debut_trial_fresh_source_v1/outputs"
ROOT_REVIEW = ROOT / "jeju/research/20261018_debut_trial_fresh_rootreview_v1"
STYLE_DIR = ROOT / "jeju/research/20261010_style_history_ablation_v1"

FEATURES_PATH = OUT / "fresh_features_34_root_dryrun.parquet"
FEATURE_RECEIPT = OUT / "fresh_trial4_build.json"
TARGET_PATH = SOURCE / "eligible_target_roster.parquet"
SOURCE_MANIFEST = SOURCE / "audit_manifest.json"
ROOT_RELEASE = ROOT_REVIEW / "ROOT_RELEASE.json"
PROTOCOL = ROOT_REVIEW / "ROOT_PROTOCOL_PRE_SCORE.json"
COLD_SCHEDULE = ROOT_REVIEW / "ROOT_COLD_DATE_BOOTSTRAP.npy"
ALL_SCHEDULE = ROOT_REVIEW / "ROOT_ALL_DATE_BOOTSTRAP.npy"

BASE_FEATURES = [
    "distance_m", "grade_raw", "field_n", "observed_starts", "days_since_start",
    "previous_age", "previous_sex", "same_starts", "same_valid_times", "days_since_same",
    "last_time_s", "mean5_s", "valid_n5", "opp_mean5_valid_n",
    "opp_mean5_valid_fraction", "opp_mean5_median_s", "mean5_minus_opp_mean_s",
    "mean5_minus_opp_median_s", "mean5_minus_opp_fast2mean_s", "opp_mean5_faster_n",
    "mean5_rank_fraction", "previous_finish_relative_rank", "previous_top3",
    "previous_result_status", "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
]
TRIAL_FEATURES = [
    "trial_peer_relative_time_mean3",
    "trial_peer_relative_time_n3",
    "trial_days_since_latest_event_pre",
    "trial_event_count_pre",
]
STRING_FEATURES = {"grade_raw", "previous_sex", "previous_result_status"}
MODELS = [
    (
        "baseline",
        "F1_STYLE6",
        ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026",
    ),
    (
        "candidate",
        "F1_STYLE6_DEBUT_TRIAL4",
        ROOT / "jeju/research/20261018_debut_trial_ablation_v1/outputs/F1_STYLE6_DEBUT_TRIAL4_2026",
    ),
]

OUTPUTS = {
    "fresh_model_predictions.parquet",
    "fresh_race_metrics.parquet",
    "fresh_canonical_max6.parquet",
    "fresh_paired_runner_losses.parquet",
    "fresh_paired_race_metrics.parquet",
    "fresh_scope_summary.json",
    "fresh_primary_date_bootstrap.parquet",
    "fresh_raw_score_concordance.parquet",
    "fresh_six_combination_summary.parquet",
    "fresh_evaluation_receipt.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_parquet_new(path: Path, frame: pd.DataFrame) -> None:
    if not path.resolve().is_relative_to(OUT.resolve()):
        raise AssertionError("refusing to write evaluation outputs outside this study")
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def write_json_new(path: Path, payload: dict) -> None:
    if not path.resolve().is_relative_to(OUT.resolve()):
        raise AssertionError("refusing to write evaluation receipt outside this study")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def load_style_runner():
    if str(STYLE_DIR) not in sys.path:
        sys.path.insert(0, str(STYLE_DIR))
    spec = importlib.util.spec_from_file_location(
        "fresh_period_locked_style_runner", STYLE_DIR / "run.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load saved-model categorical transform contract")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _check_release_and_features() -> tuple[dict, dict, pd.DataFrame]:
    release = json.loads(ROOT_RELEASE.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    feature_receipt = json.loads(FEATURE_RECEIPT.read_text(encoding="utf-8"))
    assert release.get("source_and_features_approved") is True
    assert release.get("allowed") == "frozen2026 model evaluation only, all34 values mustequalthisreference, no training or recalibration"
    assert protocol.get("status") == "LOCKED_BEFORE_FRESH_MODEL_PREDICTIONS"
    assert protocol.get("new_training_calls") == 0 and protocol.get("new_temperature_optimizations") == 0
    assert protocol.get("window_start") == "2026-09-20" and protocol.get("window_end") == "2026-10-17"
    assert feature_receipt.get("passed") is True
    checks = feature_receipt["checks"]
    assert checks["frozen_34_input_reference"]["rows"] == 426
    assert checks["frozen_34_input_reference"]["max_abs_error"] == 0.0
    assert checks["trial4_14_row_reference"]["rows"] == 14
    assert checks["trial4_14_row_reference"]["max_abs_error"] == 0.0
    assert checks["selected_trial_slots_reference"]["all_slots_exact_within_1e-12"] is True
    assert sha256(SOURCE_MANIFEST) == release["source_manifest_sha256"]
    assert sha256(PROTOCOL) == release["protocol_sha256"]
    assert sha256(FEATURES_PATH) == feature_receipt["output_sha256"][FEATURES_PATH.name]

    feature_cols = ["api_record_id", "race_id", "race_date", "horse_id", *BASE_FEATURES, *TRIAL_FEATURES]
    features = pd.read_parquet(FEATURES_PATH, columns=feature_cols)
    if len(features) != 426 or features.api_record_id.duplicated().any():
        raise AssertionError("frozen fresh model inputs must contain 426 unique target rows")
    return release, protocol, features


def _verify_models(release: dict, style) -> list[dict]:
    receipts = []
    for label, variant, folder in MODELS:
        model_file, meta_file = folder / "top3.txt", folder / "meta.json"
        relative_model = str(model_file.relative_to(ROOT))
        relative_meta = str(meta_file.relative_to(ROOT))
        assert release["models"][relative_model] == sha256(model_file), f"frozen model changed: {relative_model}"
        assert release["models"][relative_meta] == sha256(meta_file), f"frozen metadata changed: {relative_meta}"
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        expected_features = BASE_FEATURES if label == "baseline" else BASE_FEATURES + TRIAL_FEATURES
        assert meta["variant"] == variant and int(meta["evaluation_year"]) == 2026
        assert meta["features"] == expected_features and int(meta["feature_count"]) == len(expected_features)
        assert float(meta["tau"]) > 0 and float(meta["tau"]) == float(meta["tau"])
        assert meta["vocabulary"] and set(meta["vocabulary"]) == {
            column for column in style.MODEL_CATS if column in expected_features
        }
        model = lgb.Booster(model_file=str(model_file))
        assert model.num_trees() == int(meta["trees"])
        assert model.feature_name() == expected_features
        receipts.append({
            "label": label,
            "variant": variant,
            "model_path": relative_model,
            "meta_path": relative_meta,
            "model_sha256": sha256(model_file),
            "meta_sha256": sha256(meta_file),
            "saved_trees": int(meta["trees"]),
            "saved_tau": float(meta["tau"]),
            "feature_count": len(expected_features),
        })
    return receipts


def _score_and_evaluate(features: pd.DataFrame, labels: pd.DataFrame, style) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict]]:
    identity = ["api_record_id", "race_id", "race_date", "horse_id"]
    joined = features[identity].merge(
        labels[["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "finish_position"]],
        on="api_record_id", how="left", suffixes=("_feature", "_source"), validate="one_to_one",
    )
    if len(joined) != 426 or joined.finish_position.isna().any():
        raise AssertionError("audited outcome labels do not cover the exact frozen target roster")
    for field in ("race_id", "race_date", "horse_id"):
        if not joined[f"{field}_feature"].astype("string").equals(joined[f"{field}_source"].astype("string")):
            raise AssertionError(f"audited label identity differs from frozen features: {field}")
    labels_aligned = labels.set_index("api_record_id").loc[features.api_record_id.astype("int64")]
    model_frame = features.copy()
    model_frame["horse_number"] = pd.to_numeric(labels_aligned.horse_number, errors="raise").to_numpy(dtype="int64")
    model_frame["finish_position"] = pd.to_numeric(labels_aligned.finish_position, errors="raise").to_numpy(dtype="int64")
    model_frame["year"] = pd.to_datetime(model_frame.race_date, format="%Y-%m-%d", errors="raise").dt.year.astype("int64")
    model_frame = model_frame.sort_values(["race_date", "race_id", "horse_number"], kind="stable").reset_index(drop=True)
    if model_frame.groupby("race_id", sort=False).horse_number.apply(lambda x: x.is_monotonic_increasing).eq(False).any():
        raise AssertionError("horse numbers are not in increasing race order")
    if not model_frame.finish_position.between(1, model_frame.field_n).all():
        raise AssertionError("target finish positions fail the frozen complete-race range check")
    race_ranks = model_frame.groupby("race_id", sort=False).finish_position.agg(["size", "nunique", "min", "max"])
    if not (race_ranks["size"].eq(race_ranks["nunique"]) & race_ranks["min"].eq(1) & race_ranks["max"].eq(race_ranks["size"])).all():
        raise AssertionError("target outcome ranks fail exact 1..N permutation")

    all_races: list[pd.DataFrame] = []
    all_runners: list[pd.DataFrame] = []
    all_tickets: list[pd.DataFrame] = []
    score_receipts: list[dict] = []
    for label, variant, folder in MODELS:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        columns = meta["features"]
        data = model_frame.copy()
        x = style.transform(data, columns, meta["vocabulary"])
        model = lgb.Booster(model_file=str(folder / "top3.txt"))
        raw_scores = model.predict(x, raw_score=True, num_threads=4)
        if len(raw_scores) != len(model_frame) or not np.isfinite(raw_scores).all():
            raise AssertionError(f"non-finite or mis-sized raw scores for {variant}")
        # Frozen probability/combination calculation; saved tau only, no fit.
        race_metrics, runners, tickets = style.OLD.evaluate(data, raw_scores, float(meta["tau"]), variant)
        if len(runners) != 426 or race_metrics.race_id.nunique() != 45 or len(tickets) != 270:
            raise AssertionError(f"unexpected evaluation output counts for {variant}")
        runners["model"] = label
        race_metrics["model"] = label
        tickets["model"] = label
        all_races.append(race_metrics)
        all_runners.append(runners)
        all_tickets.append(tickets)
        score_receipts.append({
            "model": label,
            "variant": variant,
            "rows_scored": int(len(raw_scores)),
            "races_evaluated": int(race_metrics.race_id.nunique()),
            "tickets": int(len(tickets)),
            "raw_score_min": float(np.min(raw_scores)),
            "raw_score_max": float(np.max(raw_scores)),
            "saved_tau_used": float(meta["tau"]),
            "model_predict_calls": 1,
            "training_calls": 0,
            "calibration_calls": 0,
        })
    races = pd.concat(all_races, ignore_index=True)
    runners = pd.concat(all_runners, ignore_index=True)
    tickets = pd.concat(all_tickets, ignore_index=True)
    return races, runners, tickets, score_receipts


def _paired_tables(features: pd.DataFrame, races: pd.DataFrame, runners: pd.DataFrame, tickets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    runner_keys = ["api_record_id", "race_id", "race_date", "year", "distance_m", "horse_id", "horse_number"]
    runner_metrics = ["score", "p_top3", "y", "log_loss", "brier"]
    base = runners.loc[runners.model.eq("baseline"), runner_keys + runner_metrics].rename(
        columns={column: f"{column}_baseline" for column in runner_metrics}
    )
    candidate = runners.loc[runners.model.eq("candidate"), runner_keys + runner_metrics].rename(
        columns={column: f"{column}_candidate" for column in runner_metrics}
    )
    paired = candidate.merge(base, on=runner_keys, how="inner", validate="one_to_one")
    if len(paired) != 426 or paired.api_record_id.duplicated().any():
        raise AssertionError("paired runner output is incomplete or has duplicate IDs")
    if not paired.y_candidate.astype("int8").equals(paired.y_baseline.astype("int8")):
        raise AssertionError("candidate/baseline outcomes differ")
    context = features[["api_record_id", "observed_starts", *TRIAL_FEATURES]]
    paired = paired.merge(context, on="api_record_id", how="left", validate="one_to_one", sort=False)
    if paired.observed_starts.isna().any():
        raise AssertionError("paired runner rows lost frozen history context")

    race_metrics = [
        "trio_nll", "six_combo_hit", "six_combo_mass", "top3_capture", "top3_all3",
        "top4_capture", "top4_all3", "top5_capture", "top5_all3", "top6_capture", "top6_all3",
    ]
    race_keys = ["race_id", "race_date", "year", "distance_m", "field_n"]
    base_race = races.loc[races.model.eq("baseline"), race_keys + race_metrics].rename(
        columns={column: f"{column}_baseline" for column in race_metrics}
    )
    cand_race = races.loc[races.model.eq("candidate"), race_keys + race_metrics].rename(
        columns={column: f"{column}_candidate" for column in race_metrics}
    )
    paired_races = cand_race.merge(base_race, on=race_keys, how="inner", validate="one_to_one")
    if len(paired_races) != 45 or paired_races.race_id.duplicated().any():
        raise AssertionError("paired race output must contain the same 45 eligible races")
    # Add top-rank selection hit using exact raw-score order and stable row order.
    pick_rows = []
    for model in ("baseline", "candidate"):
        one = runners.loc[runners.model.eq(model)]
        for race_id, group in one.groupby("race_id", sort=False):
            top = group.sort_values("score", ascending=False, kind="stable").iloc[0]
            pick_rows.append({"race_id": race_id, "model": model, "pick_hit": int(top.y)})
    pick = pd.DataFrame(pick_rows).pivot(index="race_id", columns="model", values="pick_hit")
    paired_races = paired_races.merge(
        pick.rename(columns={"baseline": "pick_hit_baseline", "candidate": "pick_hit_candidate"}),
        left_on="race_id", right_index=True, how="left", validate="one_to_one",
    )
    return paired, paired_races


def _race_loss_scope(paired: pd.DataFrame, scope: str) -> pd.DataFrame:
    if scope == "all":
        subset = paired
    elif scope == "cold":
        subset = paired.loc[pd.to_numeric(paired.observed_starts, errors="raise").eq(0)]
    elif scope == "experienced":
        subset = paired.loc[pd.to_numeric(paired.observed_starts, errors="raise").gt(0)]
    else:
        raise ValueError(scope)
    if subset.empty:
        raise AssertionError(f"empty loss scope: {scope}")
    grouped = subset.groupby(["race_id", "race_date"], sort=True).agg(
        runner_rows=("api_record_id", "size"),
        log_loss_candidate=("log_loss_candidate", "mean"),
        log_loss_baseline=("log_loss_baseline", "mean"),
        brier_candidate=("brier_candidate", "mean"),
        brier_baseline=("brier_baseline", "mean"),
    ).reset_index()
    for metric in ("log_loss", "brier"):
        grouped[f"{metric}_delta"] = grouped[f"{metric}_candidate"] - grouped[f"{metric}_baseline"]
    grouped["scope"] = scope
    return grouped


def _summarize_loss_scopes(paired: pd.DataFrame, cold_schedule: np.ndarray, all_schedule: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame]:
    scope_tables = {
        scope: _race_loss_scope(paired, scope)
        for scope in ("cold", "all", "experienced")
    }
    rows = []
    draw_rows = []
    for scope, race_losses in scope_tables.items():
        dates = sorted(race_losses.race_date.astype("string").unique().tolist())
        if scope == "cold":
            schedule = cold_schedule
            expected_dates = [
                "2026-10-02", "2026-10-03", "2026-10-05",
                "2026-10-09", "2026-10-10", "2026-10-17",
            ]
        else:
            schedule = all_schedule
            expected_dates = [
                "2026-10-02", "2026-10-03", "2026-10-05", "2026-10-09",
                "2026-10-10", "2026-10-16", "2026-10-17",
            ]
        if dates != expected_dates or schedule.shape != (20000, len(dates)):
            raise AssertionError(f"{scope}: date schedule does not match preregistered dates")
        if schedule.min() < 0 or schedule.max() >= len(dates):
            raise AssertionError(f"{scope}: date bootstrap schedule index is outside scope")
        daily_count = race_losses.groupby("race_date", sort=True).size().reindex(dates).to_numpy(dtype="int64")
        if np.any(daily_count <= 0):
            raise AssertionError(f"{scope}: at least one schedule date has no eligible races")
        for metric in ("log_loss", "brier"):
            delta_col = f"{metric}_delta"
            daily_sum = race_losses.groupby("race_date", sort=True)[delta_col].sum().reindex(dates).to_numpy(dtype="float64")
            draws = daily_sum[schedule].sum(axis=1) / daily_count[schedule].sum(axis=1)
            point = float(race_losses[delta_col].mean())
            low, high = np.quantile(draws, [0.025, 0.975])
            rows.append({
                "scope": scope,
                "metric": metric,
                "rows": int(race_losses.runner_rows.sum()),
                "races": int(len(race_losses)),
                "dates": int(len(dates)),
                "candidate_race_equal": float(race_losses[f"{metric}_candidate"].mean()),
                "baseline_race_equal": float(race_losses[f"{metric}_baseline"].mean()),
                "delta_candidate_minus_baseline": point,
                "paired_date_bootstrap_ci95_low": float(low),
                "paired_date_bootstrap_ci95_high": float(high),
                "bootstrap_draws": 20000,
                "dates_per_draw": int(len(dates)),
                "few_date_exploratory": bool(scope == "cold" and len(dates) < 5),
            })
            draw_rows.extend(
                {"scope": scope, "metric": metric, "draw_id": int(i), "delta": float(value)}
                for i, value in enumerate(draws)
            )
    return pd.DataFrame(rows), pd.DataFrame(draw_rows)


def _concordance(paired: pd.DataFrame) -> pd.DataFrame:
    cold = paired.loc[pd.to_numeric(paired.observed_starts, errors="raise").eq(0)]
    rows = []
    for race_id, group in cold.groupby("race_id", sort=True):
        positive = group.loc[group.y_candidate.eq(1)]
        negative = group.loc[group.y_candidate.eq(0)]
        if positive.empty or negative.empty:
            continue
        row = {
            "race_id": race_id,
            "race_date": str(group.race_date.iloc[0]),
            "positive_cold_rows": int(len(positive)),
            "negative_cold_rows": int(len(negative)),
            "cross_label_pairs": int(len(positive) * len(negative)),
        }
        for model in ("baseline", "candidate"):
            p = positive[f"score_{model}"].to_numpy(dtype="float64")[:, None]
            n = negative[f"score_{model}"].to_numpy(dtype="float64")[None, :]
            diff = p - n
            row[f"{model}_concordance"] = float(np.where(diff > 0, 1.0, np.where(diff == 0, 0.5, 0.0)).mean())
        row["candidate_minus_baseline"] = row["candidate_concordance"] - row["baseline_concordance"]
        rows.append(row)
    return pd.DataFrame(rows)


def _six_combo_summary(paired_races: pd.DataFrame, cold_races: set[str]) -> pd.DataFrame:
    metrics = [
        "pick_hit", "top3_all3", "top4_all3", "top5_all3", "top6_all3",
        "trio_nll", "six_combo_hit", "six_combo_mass",
    ]
    rows = []
    for scope, subset in (
        ("all_eligible_races", paired_races),
        ("races_containing_cold_targets", paired_races.loc[paired_races.race_id.isin(cold_races)]),
    ):
        for metric in metrics:
            candidate = pd.to_numeric(subset[f"{metric}_candidate"], errors="raise").to_numpy(dtype="float64")
            baseline = pd.to_numeric(subset[f"{metric}_baseline"], errors="raise").to_numpy(dtype="float64")
            rows.append({
                "scope": scope, "metric": metric, "races": int(len(subset)),
                "candidate_mean": float(candidate.mean()), "baseline_mean": float(baseline.mean()),
                "candidate_minus_baseline": float((candidate - baseline).mean()),
                "candidate_sum_or_hit_count": float(candidate.sum()),
                "baseline_sum_or_hit_count": float(baseline.sum()),
            })
    return pd.DataFrame(rows)


def main() -> dict:
    if any((OUT / name).exists() for name in OUTPUTS):
        raise FileExistsError("refusing to overwrite existing fresh-period evaluation outputs")
    release, protocol, features = _check_release_and_features()
    style = load_style_runner()
    model_receipts = _verify_models(release, style)

    label_cols = ["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "finish_position"]
    labels = pd.read_parquet(TARGET_PATH, columns=label_cols)
    labels["api_record_id"] = pd.to_numeric(labels.api_record_id, errors="raise").astype("int64")
    labels["horse_number"] = pd.to_numeric(labels.horse_number, errors="raise").astype("int64")
    labels["finish_position"] = pd.to_numeric(labels.finish_position, errors="raise").astype("int64")
    if len(labels) != 426 or labels.api_record_id.duplicated().any():
        raise AssertionError("outcome source must match the exact audited 426-row eligible roster")

    # The model itself sees only the frozen feature columns. Outcome labels are
    # joined afterward for the released probability and performance evaluation.
    races, runners, tickets, score_receipts = _score_and_evaluate(features, labels, style)
    paired, paired_races = _paired_tables(features, races, runners, tickets)

    cold_rows = paired.loc[pd.to_numeric(paired.observed_starts, errors="raise").eq(0)]
    if len(cold_rows) != 14 or cold_rows.race_id.nunique() != 6:
        raise AssertionError("primary cold scope differs from the frozen protocol")
    if set(cold_rows.race_date.astype("string")) != set(protocol["primary_cold_dates"]):
        raise AssertionError("primary cold dates differ from the locked date list")
    if not cold_rows.distance_m.eq(900).all():
        raise AssertionError("primary fresh cold cohort distance scope differs from protocol")

    cold_schedule = np.load(COLD_SCHEDULE, allow_pickle=False)
    all_schedule = np.load(ALL_SCHEDULE, allow_pickle=False)
    if cold_schedule.shape != (20000, 6) or all_schedule.shape != (20000, 7):
        raise AssertionError("fixed paired bootstrap schedule dimensions changed")
    if cold_schedule.dtype.kind not in "iu" or all_schedule.dtype.kind not in "iu":
        raise AssertionError("fixed bootstrap schedules must be integer date indices")
    scope_summary, bootstrap = _summarize_loss_scopes(paired, cold_schedule, all_schedule)
    concordance = _concordance(paired)
    cold_races = set(cold_rows.race_id.astype("string"))
    six_combo = _six_combo_summary(paired_races, cold_races)

    receipt = {
        "status": "PASS_FROZEN_2026_FRESH_PERIOD_EVALUATION",
        "release_path": str(ROOT_RELEASE.relative_to(ROOT)),
        "release_sha256": sha256(ROOT_RELEASE),
        "protocol_path": str(PROTOCOL.relative_to(ROOT)),
        "protocol_sha256": sha256(PROTOCOL),
        "feature_path": str(FEATURES_PATH.relative_to(ROOT)),
        "feature_sha256": sha256(FEATURES_PATH),
        "reference_feature_path": release["feature_path"],
        "reference_feature_sha256": release["feature_sha256"],
        "source_manifest_sha256": sha256(SOURCE_MANIFEST),
        "audited_outcome_roster_path": str(TARGET_PATH.relative_to(ROOT)),
        "audited_outcome_roster_sha256": sha256(TARGET_PATH),
        "models": model_receipts,
        "scope": {
            "fresh_window_start": protocol["window_start"],
            "fresh_window_end": protocol["window_end"],
            "available_local_card_dates": protocol["available_dates"],
            "eligible_runner_rows": 426,
            "eligible_races": 45,
            "all_scope_dates": 7,
            "cold_runner_rows": 14,
            "cold_races": 6,
            "cold_dates": protocol["primary_cold_dates"],
            "cold_distance_m": [900],
            "prior_evaluation_end": protocol["prior_evaluation_end"],
        },
        "analysis": {
            "primary": "cold runner binary Top3 log loss/Brier; cold runner mean within each race, then equal race average",
            "difference": "candidate minus baseline",
            "uncertainty": "paired calendar-date cluster bootstrap using frozen ROOT_COLD_DATE_BOOTSTRAP.npy and ROOT_ALL_DATE_BOOTSTRAP.npy",
            "cold_date_bootstrap_draws": int(cold_schedule.shape[0]),
            "all_date_bootstrap_draws": int(all_schedule.shape[0]),
            "cold_few_date_exploratory_rule_below": int(protocol["uncertainty"]["few_date_exploratory_if_below"]),
            "concordance": "within-cold-race raw score comparisons; only races with both Top3-positive and negative cold horses; exact ties=.5",
            "six_combination_scopes": ["all 45 eligible races", "six races containing cold targets"],
        },
        "execution": {
            "model_predict_calls": 2,
            "training_calls": 0,
            "calibration_calls": 0,
            "feature_or_threshold_tuning": False,
            "automatic_promotion": False,
            "database_opened": False,
            "database_writes": 0,
            "registry_or_operating_model_writes": 0,
            "scores_fitted_or_calibrated_on_fresh_period": False,
        },
        "scoring_receipts": score_receipts,
        "summary_files": {
            "primary_and_secondary_losses": "fresh_scope_summary.json",
            "paired_date_bootstrap_draws": "fresh_primary_date_bootstrap.parquet",
            "cold_raw_score_concordance": "fresh_raw_score_concordance.parquet",
            "six_combination_diagnostics": "fresh_six_combination_summary.parquet",
        },
    }

    # Emit an accessible compact summary alongside the underlying row/race data.
    summary_payload = {
        "scope_metrics": scope_summary.to_dict(orient="records"),
        "cold_concordance": {
            "eligible_cold_races_with_both_labels": int(len(concordance)),
            "cross_label_pairs": int(concordance.cross_label_pairs.sum()) if len(concordance) else 0,
            "baseline_equal_race_mean": float(concordance.baseline_concordance.mean()) if len(concordance) else None,
            "candidate_equal_race_mean": float(concordance.candidate_concordance.mean()) if len(concordance) else None,
            "candidate_minus_baseline": float(concordance.candidate_minus_baseline.mean()) if len(concordance) else None,
        },
        "six_combination_metrics": six_combo.to_dict(orient="records"),
        "cold_sample_note": "14 fresh cold runners in six 900m races across six dates; earlier 661-row/252-race result is a separate disjoint period.",
        "date_coverage_note": "No local raw race rows were present for 2026-09-20 through 2026-10-01; this does not establish that no race events occurred then.",
        "availability_note": "Historical public availability at each target's T-2 cutoff remains unverified for some source records.",
        "no_promotion": True,
    }

    write_parquet_new(OUT / "fresh_model_predictions.parquet", runners)
    write_parquet_new(OUT / "fresh_race_metrics.parquet", races)
    write_parquet_new(OUT / "fresh_canonical_max6.parquet", tickets)
    write_parquet_new(OUT / "fresh_paired_runner_losses.parquet", paired)
    write_parquet_new(OUT / "fresh_paired_race_metrics.parquet", paired_races)
    write_parquet_new(OUT / "fresh_primary_date_bootstrap.parquet", bootstrap)
    write_parquet_new(OUT / "fresh_raw_score_concordance.parquet", concordance)
    write_parquet_new(OUT / "fresh_six_combination_summary.parquet", six_combo)
    write_json_new(OUT / "fresh_scope_summary.json", summary_payload)
    receipt["outputs_sha256"] = {name: sha256(OUT / name) for name in sorted(OUTPUTS - {"fresh_evaluation_receipt.json"})}
    write_json_new(OUT / "fresh_evaluation_receipt.json", receipt)
    return {"receipt": receipt, "summary": summary_payload}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2, allow_nan=False))

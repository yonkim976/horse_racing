"""One-pass evaluation of the frozen first-start trial candidate."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import numpy as np
import pandas as pd

from feature_core import ADDED_FEATURES
from train_candidate import BASE_COLUMNS, FEATURE_PATH, OUT, ROOT, VARIANT, YEARS, sha256, write_json_new, write_parquet_new

HERE = Path(__file__).resolve().parent
STYLE_DIR = ROOT / "jeju/research/20261010_style_history_ablation_v1"
ROOT_REVIEW = ROOT / "jeju/research/20261018_debut_trial_rootreview_v1"
BOOTSTRAP_PATH = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
LOCK_PATH = OUT / "evaluation_source_lock.json"
RECEIPT_PATH = OUT / "evaluation_report_receipt.json"
RACE_METRICS = [
    "pick_hit", "top3_capture", "top3_all3", "top4_capture", "top4_all3",
    "top5_capture", "top5_all3", "top6_capture", "top6_all3",
    "trio_nll", "six_combo_hit", "six_combo_mass",
]
REPORT_OUTPUT_NAMES = (
    "candidate_evaluation_runner_predictions.parquet",
    "candidate_evaluation_race_metrics.parquet",
    "candidate_evaluation_canonical_max6.parquet",
    "paired_runner_metrics.parquet",
    "paired_race_metrics.parquet",
    "cold_primary_metrics.parquet",
    "cold_primary_bootstrap_draws.parquet",
    "cold_raw_score_concordance_by_race.parquet",
    "race_diagnostic_comparisons.parquet",
    "runner_scope_comparisons.parquet",
    "cold_trial_signal_support.parquet",
    "frozen_2026_01_02_jeju1r_example.csv",
    "evaluation_summary.json",
    "evaluation_report_receipt.json",
)


def _load_style():
    if str(STYLE_DIR) not in sys.path:
        sys.path.insert(0, str(STYLE_DIR))
    spec = importlib.util.spec_from_file_location("debut_trial_eval_style6", STYLE_DIR / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STYLE = _load_style()


def _check_lock() -> tuple[dict, dict]:
    assert LOCK_PATH.is_file(), "freeze_evaluation_source.py must lock all report inputs first"
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["lock_status"] == "FROZEN_BEFORE_FINAL_REPORT_OUTPUT"
    assert lock["evaluator_sha256"] == sha256(Path(__file__))
    assert lock["freezer_sha256"] == sha256(HERE / "freeze_evaluation_source.py")
    assert lock["selftest_sha256"] == sha256(HERE / "selftest_evaluator.py")
    assert lock["successful_reports_before_lock"] == 0
    assert lock["failed_evaluation_attempts_before_lock"] == 1
    assert lock["failed_attempt_metrics_computed_in_memory"] is True
    assert lock["failed_attempt_outputs_written_or_values_emitted"] is False
    for relative, entry in lock["input_files"].items():
        path = ROOT / relative
        assert path.is_file() and path.stat().st_size == int(entry["bytes"])
        assert sha256(path) == entry["sha256"], f"locked report input changed: {relative}"
    completion = json.loads((OUT / "candidate_training_completion.json").read_text())
    assert completion["passed"] is True and completion["candidate_models"] == 3
    assert completion["lightgbm_train_calls"] == 6 and completion["temperature_optimizations"] == 3
    assert completion["candidate_outcome_metrics_computed"] is False
    return lock, completion


def _score_candidate(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    races, runners, tickets = [], [], []
    for year in YEARS:
        folder = OUT / f"{VARIANT}_{year}"
        meta = json.loads((folder / "meta.json").read_text())
        assert meta["variant"] == VARIANT and int(meta["evaluation_year"]) == year
        assert meta["features"] == BASE_COLUMNS + ADDED_FEATURES and int(meta["feature_count"]) == 34
        saved = pd.read_parquet(folder / "evaluation_scores.parquet")
        test = features.loc[features.year.eq(year)].reset_index(drop=True)
        assert len(saved) == len(test) == int(meta["evaluation_rows"])
        assert saved.api_record_id.astype("int64").tolist() == test.api_record_id.astype("int64").tolist()
        r, u, t = STYLE.OLD.evaluate(test, saved.score.to_numpy(float), float(meta["tau"]), VARIANT)
        races.append(r)
        runners.append(u)
        tickets.append(t)
    race = pd.concat(races, ignore_index=True)
    runner = pd.concat(runners, ignore_index=True)
    ticket = pd.concat(tickets, ignore_index=True)
    assert len(runner) == 17412 and runner.api_record_id.is_unique
    assert len(race) == race.race_id.nunique() == 1779
    assert len(ticket) == 10674 and ticket.race_id.nunique() == 1779
    return race, runner, ticket


def _add_pick_hit(race: pd.DataFrame, runner: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for race_id, group in runner.groupby("race_id", sort=False):
        top = group.sort_values("score", ascending=False, kind="stable").iloc[0]
        rows.append({"race_id": race_id, "pick_hit": int(top.y)})
    out = race.merge(pd.DataFrame(rows), on="race_id", how="left", validate="one_to_one")
    assert out.pick_hit.notna().all()
    return out


def _pair(features: pd.DataFrame, cand: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    keys = ["api_record_id", "race_id", "race_date", "year", "distance_m", "horse_id", "horse_number"]
    cols = ["score", "p_top3", "y", "log_loss", "brier"]
    c = cand[keys + cols].rename(columns={k: f"{k}_candidate" for k in cols})
    b = base[keys + cols].rename(columns={k: f"{k}_baseline" for k in cols})
    out = c.merge(b, on=keys, validate="one_to_one", how="inner")
    assert len(out) == 17412 and out.api_record_id.is_unique
    assert out.y_candidate.astype("int8").equals(out.y_baseline.astype("int8"))
    context = features[["api_record_id", "observed_starts", *ADDED_FEATURES]]
    out = out.merge(context, on="api_record_id", how="left", validate="one_to_one", sort=False)
    assert len(out) == 17412 and out.observed_starts.notna().all()
    return out


def _pair_races(cand: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    keys = ["race_id", "race_date", "year", "distance_m", "field_n"]
    c = cand[keys + RACE_METRICS].rename(columns={m: f"{m}_candidate" for m in RACE_METRICS})
    b = base[keys + RACE_METRICS].rename(columns={m: f"{m}_baseline" for m in RACE_METRICS})
    out = c.merge(b, on=keys, how="inner", validate="one_to_one")
    assert len(out) == 1779 and out.race_id.is_unique
    return out


def _write_csv_new(path: Path, frame: pd.DataFrame) -> None:
    path = Path(path)
    assert path.resolve().is_relative_to(OUT.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as stream:
        frame.to_csv(stream, index=False)


def _scope_summary(group: pd.DataFrame, scope: str, value: str) -> tuple[dict, pd.DataFrame]:
    assert len(group)
    race = group.groupby("race_id", sort=False).agg(
        race_date=("race_date", "first"),
        log_loss_candidate=("log_loss_candidate", "mean"),
        log_loss_baseline=("log_loss_baseline", "mean"),
        brier_candidate=("brier_candidate", "mean"),
        brier_baseline=("brier_baseline", "mean"),
        runner_rows=("api_record_id", "size"),
    )
    row = {
        "scope": scope, "scope_value": value, "rows": int(len(group)),
        "races": int(len(race)), "race_days": int(race.race_date.nunique()),
    }
    for metric in ("log_loss", "brier"):
        row[f"{metric}_candidate"] = float(race[f"{metric}_candidate"].mean())
        row[f"{metric}_baseline"] = float(race[f"{metric}_baseline"].mean())
        row[f"{metric}_delta"] = float(
            (race[f"{metric}_candidate"] - race[f"{metric}_baseline"]).mean()
        )
    return row, race.reset_index()


def _primary_bootstrap(cold: pd.DataFrame, dates: list[str], schedule: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame]:
    race = cold.groupby("race_id", sort=False).agg(
        race_date=("race_date", "first"),
        log_loss_candidate=("log_loss_candidate", "mean"),
        log_loss_baseline=("log_loss_baseline", "mean"),
        brier_candidate=("brier_candidate", "mean"),
        brier_baseline=("brier_baseline", "mean"),
    ).reset_index()
    index = {date: i for i, date in enumerate(dates)}
    summary, draw_rows = [], []
    for metric in ("log_loss", "brier"):
        delta = race[f"{metric}_candidate"] - race[f"{metric}_baseline"]
        daily_sum = np.zeros(len(dates), dtype=float)
        daily_count = np.zeros(len(dates), dtype=np.int64)
        for day, value in zip(race.race_date.astype("string"), delta.to_numpy(float)):
            daily_sum[index[str(day)]] += float(value)
            daily_count[index[str(day)]] += 1
        numerator = daily_sum[schedule].sum(axis=1)
        denominator = daily_count[schedule].sum(axis=1)
        valid = denominator > 0
        draws = np.full(schedule.shape[0], np.nan, dtype=float)
        draws[valid] = numerator[valid] / denominator[valid]
        assert valid.all(), f"primary {metric} bootstrap has a no-race draw"
        point = float(delta.mean())
        low, high = np.quantile(draws, [0.025, 0.975])
        summary.append({
            "metric": metric, "cold_runner_rows": int(len(cold)), "cold_races": int(len(race)),
            "race_days_with_cold_runners": int(race.race_date.nunique()),
            "candidate_race_equal": float(race[f"{metric}_candidate"].mean()),
            "baseline_race_equal": float(race[f"{metric}_baseline"].mean()),
            "delta_candidate_minus_baseline": point,
            "paired_date_bootstrap_ci95_low": float(low), "paired_date_bootstrap_ci95_high": float(high),
            "draws": int(schedule.shape[0]), "dates_per_draw": int(schedule.shape[1]),
            "valid_draws": int(valid.sum()),
        })
        draw_rows.extend({"metric": metric, "draw_id": int(i), "delta": float(v)} for i, v in enumerate(draws))
    return pd.DataFrame(summary), pd.DataFrame(draw_rows)


def _concordance(pair: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows = []
    for race_id, group in pair.loc[pair.observed_starts.eq(0)].groupby("race_id", sort=True):
        pos = group.loc[group.y_candidate.eq(1)]
        neg = group.loc[group.y_candidate.eq(0)]
        if pos.empty or neg.empty:
            continue
        row = {"race_id": race_id, "race_date": str(group.race_date.iloc[0]),
               "cross_label_pairs": int(len(pos) * len(neg))}
        for model in ("baseline", "candidate"):
            p = pos[f"score_{model}"].to_numpy(float)[:, None]
            n = neg[f"score_{model}"].to_numpy(float)[None, :]
            row[f"{model}_concordance"] = _pair_concordance_score(p.ravel(), n.ravel())
        rows.append(row)
    by_race = pd.DataFrame(rows)
    assert len(by_race) == 118 and int(by_race.cross_label_pairs.sum()) == 398
    result = {
        "eligible_races": int(len(by_race)), "cross_label_pairs": int(by_race.cross_label_pairs.sum()),
        "baseline_equal_race_mean": float(by_race.baseline_concordance.mean()),
        "candidate_equal_race_mean": float(by_race.candidate_concordance.mean()),
        "delta": float((by_race.candidate_concordance - by_race.baseline_concordance).mean()),
        "pairing": "all cold Top3-positive/negative score pairs within each race; average pair scores within race, then races equally",
        "score": "raw model score; exact raw-score ties earn 0.5",
        "role": "descriptive secondary, not a gate",
    }
    return by_race, result


def _pair_concordance_score(positive_scores: np.ndarray, negative_scores: np.ndarray) -> float:
    positive = np.asarray(positive_scores, dtype="float64").reshape(-1)
    negative = np.asarray(negative_scores, dtype="float64").reshape(-1)
    assert positive.size and negative.size
    assert np.isfinite(positive).all() and np.isfinite(negative).all()
    comparisons = positive[:, None] - negative[None, :]
    return float(np.where(comparisons > 0, 1., np.where(comparisons == 0, .5, 0.)).mean())


def _race_diagnostics(cand: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    keys = ["race_id", "race_date", "year", "distance_m"]
    pair = cand[keys + RACE_METRICS].merge(
        base[keys + RACE_METRICS], on=keys, how="inner", suffixes=("_candidate", "_baseline"), validate="one_to_one"
    )
    assert len(pair) == 1779
    scopes = [("all", "all", pair)]
    scopes.extend(("year", str(int(y)), g) for y, g in pair.groupby("year", sort=True))
    scopes.extend(("distance_m", str(int(d)), g) for d, g in pair.groupby("distance_m", sort=True))
    result = []
    for kind, value, group in scopes:
        for metric in RACE_METRICS:
            c = group[f"{metric}_candidate"].to_numpy(float)
            b = group[f"{metric}_baseline"].to_numpy(float)
            result.append({"scope": kind, "scope_value": value, "metric": metric,
                           "races": int(len(group)), "candidate_mean": float(c.mean()),
                           "baseline_mean": float(b.mean()), "delta": float((c-b).mean())})
    return pd.DataFrame(result)


def _fixed_example(features: pd.DataFrame, pair: pd.DataFrame, slots: pd.DataFrame) -> pd.DataFrame:
    spec = json.loads((ROOT_REVIEW / "ROOT_EXAMPLE_SELECTION.json").read_text())
    assert spec["status"] == "FROZEN_BEFORE_CANDIDATE_FIT"
    ids = list(map(int, spec["api_record_ids"]))
    assert len(ids) == 8 and len(set(ids)) == 8 and spec["race_id"] == "2026-01-02_2_1"
    selected = pair.loc[pair.api_record_id.isin(ids)].copy()
    assert set(selected.api_record_id.astype(int)) == set(ids) and selected.race_id.eq(spec["race_id"]).all()
    selected = selected.merge(features[["api_record_id", "horse_name", "finish_position"]],
                              on="api_record_id", how="left", validate="one_to_one")
    expected = pd.DataFrame(spec["horses"])[["horse_number", "horse_id", "horse_name"]].rename(
        columns={"horse_name": "frozen_name"})
    selected = selected.merge(expected, on=["horse_number", "horse_id"], how="left", validate="one_to_one")
    assert selected.frozen_name.notna().all()
    assert selected.horse_name.astype("string").equals(selected.frozen_name.astype("string"))
    by_target = {int(k): g.sort_values("slot_rank_desc", kind="stable")
                 for k, g in slots.groupby("target_api_record_id", sort=False)}
    result = []
    for row in selected.itertuples(index=False):
        group = by_target.get(int(row.api_record_id), slots.iloc[:0])
        result.append({
            "api_record_id": int(row.api_record_id), "race_id": row.race_id,
            "horse_number": int(row.horse_number), "horse_id": str(row.horse_id),
            "horse_name": row.horse_name, "top3_outcome": int(row.finish_position <= 3),
            "baseline_score": float(row.score_baseline), "baseline_p_top3": float(row.p_top3_baseline),
            "candidate_score": float(row.score_candidate), "candidate_p_top3": float(row.p_top3_candidate),
            "delta_p_top3": float(row.p_top3_candidate - row.p_top3_baseline),
            **{f: getattr(row, f) for f in ADDED_FEATURES},
            "trial_source_api_ids_latest_first": ",".join(map(str, group.source_api_record_id.astype(int))),
            "trial_dates_latest_first": ",".join(map(str, group.source_trial_date.astype("string"))),
        })
    result = pd.DataFrame(result).sort_values("horse_number", kind="stable").reset_index(drop=True)
    assert len(result) == 8
    return result


def evaluate() -> dict:
    assert not any((OUT / name).exists() for name in REPORT_OUTPUT_NAMES), "refusing to overwrite or repeat report outputs"
    lock, completion = _check_lock()
    features = pd.read_parquet(FEATURE_PATH)
    assert len(features) == 52155 and features.api_record_id.is_unique
    assert list(features[BASE_COLUMNS].columns) == BASE_COLUMNS
    assert list(features.columns[-4:]) == ADDED_FEATURES
    cand_race, cand_runner, cand_ticket = _score_candidate(features)
    base_race = pd.read_parquet(OUT / "baseline_replayed_race_metrics.parquet")
    base_runner = pd.read_parquet(OUT / "baseline_replayed_runner_predictions.parquet")
    base_ticket = pd.read_parquet(OUT / "baseline_replayed_canonical_max6.parquet")
    assert len(base_runner) == 17412 and len(base_race) == 1779 and len(base_ticket) == 10674
    cand_race = _add_pick_hit(cand_race, cand_runner)
    base_race = _add_pick_hit(base_race, base_runner)
    pair = _pair(features, cand_runner, base_runner)
    paired_races = _pair_races(cand_race, base_race)
    cold = pair.loc[pair.observed_starts.eq(0)].copy()
    experienced = pair.loc[pair.observed_starts.gt(0)].copy()
    assert len(cold) == 661 and cold.race_id.nunique() == 252
    assert len(experienced) == 16751 and experienced.race_id.nunique() == 1779

    dates = sorted(features.loc[features.year.isin(YEARS), "race_date"].astype("string").unique().tolist())
    assert len(dates) == 269
    schedule = np.load(BOOTSTRAP_PATH, allow_pickle=False)
    assert sha256(BOOTSTRAP_PATH) == BOOTSTRAP_SHA256
    assert schedule.shape == (2000, 269) and schedule.dtype.kind in "iu"
    assert schedule.min() >= 0 and schedule.max() < 269

    scope_rows = []
    for name, value, group in (("all_evaluation", "all", pair),
                               ("cold_primary", "observed_starts_0", cold),
                               ("experienced_guard", "observed_starts_positive", experienced)):
        scope_rows.append(_scope_summary(group, name, value)[0])
    for year in YEARS:
        scope_rows.append(_scope_summary(pair.loc[pair.year.eq(year)], "all_by_year", str(year))[0])
        scope_rows.append(_scope_summary(cold.loc[cold.year.eq(year)], "cold_by_year", str(year))[0])
    for distance, group in pair.groupby("distance_m", sort=True):
        scope_rows.append(_scope_summary(group, "all_by_distance", str(int(distance)))[0])
    for distance, group in cold.groupby("distance_m", sort=True):
        scope_rows.append(_scope_summary(group, "cold_by_distance", str(int(distance)))[0])
    scope_table = pd.DataFrame(scope_rows)
    primary, draws = _primary_bootstrap(cold, dates, schedule)
    primary_by_metric = {row.metric: row for row in primary.itertuples(index=False)}
    gate = bool(
        all(float(primary_by_metric[m].delta_candidate_minus_baseline) < 0 for m in ("log_loss", "brier"))
        and any(float(primary_by_metric[m].paired_date_bootstrap_ci95_high) < 0 for m in ("log_loss", "brier"))
    )
    concordance_by_race, concordance = _concordance(pair)
    race_diag = _race_diagnostics(cand_race, base_race)
    slots = pd.read_parquet(OUT / "cold_target_trial_feature_slots.parquet")
    example = _fixed_example(features, pair, slots)
    support = cold.groupby("trial_peer_relative_time_n3", sort=True).agg(
        runner_rows=("api_record_id", "size"), races=("race_id", "nunique"),
        mean3_nonnull=("trial_peer_relative_time_mean3", "count"),
    ).reset_index().rename(columns={"trial_peer_relative_time_n3": "valid_relative_trial_n_latest3"})

    exp_delta = (experienced.score_candidate - experienced.score_baseline).to_numpy(float)
    exp_diagnostic = {
        "experienced_rows": int(len(experienced)), "races": int(experienced.race_id.nunique()),
        "raw_score_changed_rows": int(np.count_nonzero(exp_delta != 0.0)),
        "raw_score_mean_absolute_change": float(np.mean(np.abs(exp_delta))),
        "raw_score_max_absolute_change": float(np.max(np.abs(exp_delta))),
        "added_features_all_null": bool(features.loc[features.observed_starts.gt(0), ADDED_FEATURES].isna().all().all()),
        "interpretation": "Pooled refit can change experienced-runner scores even though added inputs are NULL.",
    }
    assert cand_ticket.groupby("race_id").size().eq(6).all()
    assert cand_ticket.groupby("race_id").hit.max().sort_index().astype("int64").equals(
        cand_race.set_index("race_id").six_combo_hit.sort_index().astype("int64")
    )
    assert base_ticket.groupby("race_id").hit.max().sort_index().astype("int64").equals(
        base_race.set_index("race_id").six_combo_hit.sort_index().astype("int64")
    )

    frames = {
        "candidate_evaluation_runner_predictions.parquet": cand_runner,
        "candidate_evaluation_race_metrics.parquet": cand_race,
        "candidate_evaluation_canonical_max6.parquet": cand_ticket,
        "paired_runner_metrics.parquet": pair,
        "paired_race_metrics.parquet": paired_races,
        "cold_primary_metrics.parquet": primary,
        "cold_primary_bootstrap_draws.parquet": draws,
        "cold_raw_score_concordance_by_race.parquet": concordance_by_race,
        "race_diagnostic_comparisons.parquet": race_diag,
        "runner_scope_comparisons.parquet": scope_table,
        "cold_trial_signal_support.parquet": support,
        "frozen_2026_01_02_jeju1r_example.csv": example,
    }
    for name, frame in frames.items():
        if name.endswith(".parquet"):
            write_parquet_new(OUT / name, frame)
        else:
            _write_csv_new(OUT / name, frame)

    baseline_ref = json.loads((ROOT_REVIEW / "ROOT_EVALUATION_CONTRACT.json").read_text())["baseline_primary"]
    summary = {
        "status": "PASS_ONE_PASS_RETROSPECTIVE_OOS_EVALUATION",
        "candidate": VARIANT, "baseline": "saved F1_STYLE6 replay; not refit",
        "candidate_models": int(completion["candidate_models"]),
        "lightgbm_train_calls": int(completion["lightgbm_train_calls"]),
        "temperature_optimizations": int(completion["temperature_optimizations"]),
        "primary_definition": "Runner-binary Top3 LL/Brier: cold runners averaged within race, then races equally.",
        "primary_scope": {"cold_runner_rows": 661, "races": 252, "all_distances": True},
        "baseline_primary_reference": baseline_ref,
        "primary_gate_passed": gate,
        "primary_metrics": primary.to_dict(orient="records"),
        "fixed_date_bootstrap": {"path": str(BOOTSTRAP_PATH.relative_to(ROOT)),
                                  "sha256": sha256(BOOTSTRAP_PATH), "dates": len(dates),
                                  "draws": int(schedule.shape[0]), "dates_per_draw": int(schedule.shape[1]),
                                  "zero_cold_dates_contribute_zero_sum_and_count": True,
                                  "valid_primary_draws": 2000},
        "cold_raw_score_concordance": concordance,
        "race_diagnostic_definition": "Equal-race means for top pick/axis, top-3/4/5/6 capture, trio NLL, canonical six-combination hit and mass; all evaluation races, year and distance auxiliary groups.",
        "experienced_score_diagnostic": exp_diagnostic,
        "frozen_human_example": {"selection": "All eight cold runners in the prefit-frozen 2026-01-02 Jeju 1R.",
                                 "race_id": "2026-01-02_2_1", "rows": 8,
                                 "artifact": "frozen_2026_01_02_jeju1r_example.csv"},
        "trial_signal_support": support.to_dict(orient="records"),
        "limitations": [
            "observed_starts=0 means no start in the saved-baseline history, not verified lifetime debut.",
            "Trial event date is not a publication timestamp; historical availability at T−2 is unverified.",
            "API20 had no explicit trial distance field in the audited snapshot; only within-event relative times were used.",
            "This retrospective development-period comparison does not establish future performance or production readiness.",
        ],
        "candidate_refit_after_evaluation": False, "production_changed": False,
        "database_changed": False, "operating_model_promoted": False,
        "evaluation_source_lock_sha256": sha256(LOCK_PATH),
        "candidate_training_completion_sha256": sha256(OUT / "candidate_training_completion.json"),
        "outputs": {},
    }
    for name, frame in frames.items():
        path = OUT / name
        summary["outputs"][name] = {"rows": int(len(frame)), "bytes": int(path.stat().st_size), "sha256": sha256(path)}
    summary_path = OUT / "evaluation_summary.json"
    write_json_new(summary_path, summary)
    receipt = {
        "passed": True, "successful_oos_metric_reports": 1,
        "evaluation_attempts_reaching_in_memory_scoring": 2,
        "failed_evaluation_attempts_before_success": 1,
        "successful_report_runs": 1,
        "candidate_refit_after_metrics": False, "candidate_models": 3,
        "lightgbm_train_calls": 6, "temperature_optimizations": 3,
        "evaluation_rows": 17412, "evaluation_races": 1779,
        "cold_primary_rows": 661, "cold_primary_races": 252,
        "primary_gate_passed": gate, "metric_runs_before_lock": 0,
        "evaluation_source_lock_sha256": sha256(LOCK_PATH),
        "evaluator_sha256": sha256(Path(__file__)),
        "summary_sha256": sha256(summary_path), "outputs": summary["outputs"],
        "production_changed": False, "database_changed": False,
    }
    write_json_new(RECEIPT_PATH, receipt)
    print(json.dumps({"passed": True, "primary_gate_passed": gate,
                      "primary_metrics": primary.to_dict(orient="records"),
                      "cold_raw_score_concordance": concordance,
                      "evaluation_summary_sha256": sha256(summary_path),
                      "evaluation_report_receipt_sha256": sha256(RECEIPT_PATH)},
                     ensure_ascii=False, indent=2, allow_nan=False))
    return summary


if __name__ == "__main__":
    evaluate()

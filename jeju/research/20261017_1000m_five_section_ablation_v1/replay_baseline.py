"""Reproduce saved STYLE6 evaluation predictions without fitting or DB access."""
from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from train_candidate import BASE_COLUMNS, STYLE, STYLE_OUT, OUT, YEARS, sha256, write_json_new, write_parquet_new


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE_FEATURES_PATH = STYLE_OUT / "features.parquet"
SAVED_REPORT = STYLE_OUT / "report"


def _transform(frame: pd.DataFrame, vocabulary: dict) -> pd.DataFrame:
    x = frame[BASE_COLUMNS].copy()
    for column in STYLE.MODEL_CATS:
        if column in BASE_COLUMNS:
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocabulary[column])
    return x


def _compare_num(left: pd.DataFrame, right: pd.DataFrame, keys: list[str], columns: list[str], atol=1e-12):
    a = left.sort_values(keys, kind="stable").reset_index(drop=True)
    b = right.sort_values(keys, kind="stable").reset_index(drop=True)
    assert len(a) == len(b)
    for key in keys:
        assert a[key].astype("string").fillna("<NA>").equals(b[key].astype("string").fillna("<NA>")), key
    errors = {}
    for column in columns:
        av = pd.to_numeric(a[column], errors="raise").to_numpy(dtype="float64")
        bv = pd.to_numeric(b[column], errors="raise").to_numpy(dtype="float64")
        error = float(np.max(np.abs(av - bv))) if len(av) else 0.0
        assert np.allclose(av, bv, rtol=0, atol=atol, equal_nan=True), column
        errors[column] = error
    return errors


def replay() -> dict:
    receipt_path = OUT / "baseline_replay_verification.json"
    assert not receipt_path.exists(), "refusing to overwrite baseline replay receipt"
    features = pd.read_parquet(BASE_FEATURES_PATH)
    assert len(features) == 52155 and features.api_record_id.is_unique
    assert features.race_id.nunique() == 5206
    assert len(BASE_COLUMNS) == 30
    for year in YEARS:
        meta = json.loads((STYLE_OUT / f"F1_STYLE6_{year}/meta.json").read_text(encoding="utf-8"))
        assert meta["variant"] == "F1_STYLE6" and int(meta["evaluation_year"]) == year
        assert meta["features"] == BASE_COLUMNS and int(meta["feature_count"]) == 30
        assert meta["parameters"] == STYLE.OLD.PARAMS and int(meta["seed"]) == 20261008

    saved_runner = pd.read_parquet(SAVED_REPORT / "runner_predictions.parquet")
    saved_runner = saved_runner.loc[saved_runner.variant.eq("F1_STYLE6")].copy()
    saved_races = pd.read_parquet(SAVED_REPORT / "race_metrics.parquet")
    saved_races = saved_races.loc[saved_races.variant.eq("F1_STYLE6")].copy()
    saved_tickets = pd.read_csv(SAVED_REPORT / "canonical_six_combinations.csv")
    saved_tickets = saved_tickets.loc[saved_tickets.variant.eq("F1_STYLE6")].copy()

    runner_frames = []
    race_frames = []
    ticket_frames = []
    fold_rows = []
    max_score_error = 0.0
    max_probability_error = 0.0
    for year in YEARS:
        folder = STYLE_OUT / f"F1_STYLE6_{year}"
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        model_path = folder / "top3.txt"
        assert sha256(model_path) == meta["model_sha256"]
        model = lgb.Booster(model_file=str(model_path))
        test = features.loc[features.year.eq(year)].reset_index(drop=True)
        x = _transform(test, meta["vocabulary"])
        replay_scores = model.predict(x, raw_score=True, num_threads=4)
        locked_scores = pd.read_parquet(folder / "evaluation_scores.parquet")
        assert locked_scores.api_record_id.astype("int64").tolist() == test.api_record_id.astype("int64").tolist()
        score_error = float(np.max(np.abs(replay_scores - locked_scores.score.to_numpy(dtype="float64"))))
        assert np.array_equal(replay_scores, locked_scores.score.to_numpy(dtype="float64")), (
            f"saved raw score replay is not exact for {year}"
        )
        max_score_error = max(max_score_error, score_error)
        races, runners, tickets = STYLE.OLD.evaluate(test, replay_scores, float(meta["tau"]), "F1_STYLE6")

        old_runners = saved_runner.loc[saved_runner.year.eq(year)]
        runner_errors = _compare_num(
            old_runners, runners, ["api_record_id"], ["score", "p_top3", "log_loss", "brier"]
        )
        max_probability_error = max(max_probability_error, runner_errors["p_top3"])
        old_races = saved_races.loc[saved_races.year.eq(year)]
        _compare_num(old_races, races, ["race_id"], ["log_loss", "brier", "trio_nll", "six_combo_mass"])
        old_tickets = saved_tickets.loc[saved_tickets.race_id.isin(tickets.race_id)]
        a = old_tickets.sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
        b = tickets.sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
        assert a[["race_id", "selection_rank", "numbers", "hit"]].astype("string").equals(
            b[["race_id", "selection_rank", "numbers", "hit"]].astype("string")
        )
        _compare_num(a, b, ["race_id", "selection_rank"], ["probability"])
        runner_frames.append(runners)
        race_frames.append(races)
        ticket_frames.append(tickets)
        fold_rows.append({
            "year": year,
            "model_sha256": sha256(model_path),
            "saved_evaluation_scores_sha256": sha256(folder / "evaluation_scores.parquet"),
            "runners": int(len(runners)),
            "races": int(races.race_id.nunique()),
            "canonical_max6_rows": int(len(tickets)),
            "raw_score_max_abs_error": score_error,
            "saved_runner_metric_max_abs_error": max(runner_errors.values()),
        })

    all_runners = pd.concat(runner_frames, ignore_index=True)
    all_races = pd.concat(race_frames, ignore_index=True)
    all_tickets = pd.concat(ticket_frames, ignore_index=True)
    assert len(all_runners) == 17412 and all_runners.api_record_id.is_unique
    assert all_races.race_id.nunique() == 1779
    assert len(all_tickets) == 10674
    write_parquet_new(OUT / "baseline_replayed_runner_predictions.parquet", all_runners)
    write_parquet_new(OUT / "baseline_replayed_race_metrics.parquet", all_races)
    write_parquet_new(OUT / "baseline_replayed_canonical_max6.parquet", all_tickets)
    receipt = {
        "passed": True,
        "baseline": "saved F1_STYLE6",
        "baseline_models_reloaded": 3,
        "runner_rows_reproduced": int(len(all_runners)),
        "distinct_races_reproduced": int(all_races.race_id.nunique()),
        "canonical_max6_rows_reproduced": int(len(all_tickets)),
        "raw_score_replay_exact": max_score_error == 0.0,
        "raw_score_max_abs_error": max_score_error,
        "saved_top3_probability_max_abs_error": max_probability_error,
        "saved_race_metrics_and_max6_sets_reproduced": True,
        "baseline_candidate_fit_models": 0,
        "candidate_fit_models": 0,
        "candidate_outcome_metrics_computed": False,
        "source_files": {
            str(BASE_FEATURES_PATH.relative_to(ROOT)): sha256(BASE_FEATURES_PATH),
            str((STYLE_OUT / "report/runner_predictions.parquet").relative_to(ROOT)):
                sha256(SAVED_REPORT / "runner_predictions.parquet"),
        },
        "folds": fold_rows,
        "replay_outputs": {
            "baseline_replayed_runner_predictions.parquet": sha256(OUT / "baseline_replayed_runner_predictions.parquet"),
            "baseline_replayed_race_metrics.parquet": sha256(OUT / "baseline_replayed_race_metrics.parquet"),
            "baseline_replayed_canonical_max6.parquet": sha256(OUT / "baseline_replayed_canonical_max6.parquet"),
        },
    }
    write_json_new(receipt_path, receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(replay(), ensure_ascii=False, indent=2))

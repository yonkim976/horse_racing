"""Exact replay of the saved F1_STYLE6 models; does not fit or access a DB."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import lightgbm as lgb
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
STYLE_DIR = ROOT / "jeju/research/20261010_style_history_ablation_v1"
STYLE_OUT = STYLE_DIR / "outputs"
FEATURES_PATH = STYLE_OUT / "features.parquet"
SAVED_REPORT = STYLE_OUT / "report"
YEARS = (2024, 2025, 2026)
BASELINE_VARIANT = "F1_STYLE6"
BASE_COLUMNS = [
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_style_runner():
    # Import the established scoring contract only. Do not call its fit or
    # verify entrypoints; the latter includes an old whole-DB hash check.
    if str(STYLE_DIR) not in sys.path:
        sys.path.insert(0, str(STYLE_DIR))
    spec = importlib.util.spec_from_file_location(
        "debut_trial_saved_style6_runner", STYLE_DIR / "run.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the saved F1_STYLE6 scoring contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STYLE = _load_style_runner()


def _write_new(path: Path, frame: pd.DataFrame) -> None:
    path = Path(path)
    if not path.resolve().is_relative_to(OUT.resolve()):
        raise AssertionError("refusing to write baseline replay output outside this study")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def _write_json_new(path: Path, payload: dict) -> None:
    path = Path(path)
    if not path.resolve().is_relative_to(OUT.resolve()):
        raise AssertionError("refusing to write replay receipt outside this study")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _transform(frame: pd.DataFrame, vocabulary: dict) -> pd.DataFrame:
    x = frame[BASE_COLUMNS].copy()
    for column in STYLE.MODEL_CATS:
        if column in BASE_COLUMNS:
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocabulary[column])
    return x


def _compare(left: pd.DataFrame, right: pd.DataFrame, keys: list[str], columns: list[str]) -> dict:
    a = left.sort_values(keys, kind="stable").reset_index(drop=True)
    b = right.sort_values(keys, kind="stable").reset_index(drop=True)
    assert len(a) == len(b)
    for key in keys:
        assert a[key].astype("string").fillna("<NA>").equals(
            b[key].astype("string").fillna("<NA>")
        ), f"saved key mismatch: {key}"
    errors = {}
    for column in columns:
        av = pd.to_numeric(a[column], errors="raise").to_numpy(dtype="float64")
        bv = pd.to_numeric(b[column], errors="raise").to_numpy(dtype="float64")
        error = float(np.max(np.abs(av - bv))) if len(av) else 0.0
        assert np.allclose(av, bv, rtol=0, atol=1e-12, equal_nan=True), column
        errors[column] = error
    return errors


def replay() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    receipt_path = OUT / "baseline_replay_verification.json"
    assert not receipt_path.exists(), "refusing to overwrite baseline replay receipt"
    features = pd.read_parquet(FEATURES_PATH)
    assert len(features) == 52155 and features.api_record_id.is_unique
    assert features.race_id.nunique() == 5206
    assert len(BASE_COLUMNS) == 30

    for year in YEARS:
        meta = json.loads((STYLE_OUT / f"F1_STYLE6_{year}/meta.json").read_text(encoding="utf-8"))
        assert meta["variant"] == BASELINE_VARIANT and int(meta["evaluation_year"]) == year
        assert meta["features"] == BASE_COLUMNS and int(meta["feature_count"]) == 30
        assert meta["parameters"] == STYLE.OLD.PARAMS
        assert int(meta["seed"]) == int(STYLE.OLD.SEED) == 20261008

    saved_runner = pd.read_parquet(SAVED_REPORT / "runner_predictions.parquet")
    saved_runner = saved_runner.loc[saved_runner.variant.eq(BASELINE_VARIANT)].copy()
    saved_races = pd.read_parquet(SAVED_REPORT / "race_metrics.parquet")
    saved_races = saved_races.loc[saved_races.variant.eq(BASELINE_VARIANT)].copy()
    saved_tickets = pd.read_csv(SAVED_REPORT / "canonical_six_combinations.csv")
    saved_tickets = saved_tickets.loc[saved_tickets.variant.eq(BASELINE_VARIANT)].copy()

    runner_frames = []
    race_frames = []
    ticket_frames = []
    fold_receipts = []
    max_score_error = 0.0
    max_probability_error = 0.0
    max_runner_metric_error = 0.0
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
        saved_raw = locked_scores.score.to_numpy(dtype="float64")
        score_error = float(np.max(np.abs(replay_scores - saved_raw)))
        assert np.array_equal(replay_scores, saved_raw), f"saved raw score replay is not exact for {year}"
        max_score_error = max(max_score_error, score_error)
        races, runners, tickets = STYLE.OLD.evaluate(test, replay_scores, float(meta["tau"]), BASELINE_VARIANT)

        old_runners = saved_runner.loc[saved_runner.year.eq(year)]
        runner_errors = _compare(
            old_runners, runners, ["api_record_id"], ["score", "p_top3", "log_loss", "brier"]
        )
        max_probability_error = max(max_probability_error, runner_errors["p_top3"])
        max_runner_metric_error = max(max_runner_metric_error, max(runner_errors.values()))
        old_races = saved_races.loc[saved_races.year.eq(year)]
        race_errors = _compare(old_races, races, ["race_id"], ["log_loss", "brier", "trio_nll", "six_combo_mass"])
        old_tickets = saved_tickets.loc[saved_tickets.race_id.isin(tickets.race_id)]
        a = old_tickets.sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
        b = tickets.sort_values(["race_id", "selection_rank"], kind="stable").reset_index(drop=True)
        assert a[["race_id", "selection_rank", "numbers", "hit"]].astype("string").equals(
            b[["race_id", "selection_rank", "numbers", "hit"]].astype("string")
        )
        ticket_errors = _compare(a, b, ["race_id", "selection_rank"], ["probability"])
        runner_frames.append(runners)
        race_frames.append(races)
        ticket_frames.append(tickets)
        fold_receipts.append({
            "year": year,
            "model_sha256": sha256(model_path),
            "saved_evaluation_scores_sha256": sha256(folder / "evaluation_scores.parquet"),
            "runner_rows": int(len(runners)),
            "race_rows": int(races.race_id.nunique()),
            "canonical_max6_rows": int(len(tickets)),
            "raw_score_max_abs_error": score_error,
            "runner_metric_max_abs_error": max(runner_errors.values()),
            "race_metric_max_abs_error": max(race_errors.values()),
            "max6_probability_max_abs_error": max(ticket_errors.values()),
        })

    all_runners = pd.concat(runner_frames, ignore_index=True)
    all_races = pd.concat(race_frames, ignore_index=True)
    all_tickets = pd.concat(ticket_frames, ignore_index=True)
    assert len(all_runners) == 17412 and all_runners.api_record_id.is_unique
    assert all_races.race_id.nunique() == 1779
    assert len(all_tickets) == 10674
    outputs = {
        "baseline_replayed_runner_predictions.parquet": all_runners,
        "baseline_replayed_race_metrics.parquet": all_races,
        "baseline_replayed_canonical_max6.parquet": all_tickets,
    }
    for name, frame in outputs.items():
        _write_new(OUT / name, frame)
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
        "saved_runner_metric_max_abs_error": max_runner_metric_error,
        "saved_race_metrics_and_max6_sets_reproduced": True,
        "baseline_refit_models": 0,
        "candidate_fit_models": 0,
        "candidate_outcome_metrics_computed": False,
        "source_files": {
            "features.parquet": {"path": str(FEATURES_PATH.relative_to(ROOT)), "sha256": sha256(FEATURES_PATH)},
            "runner_predictions.parquet": {
                "path": str((SAVED_REPORT / "runner_predictions.parquet").relative_to(ROOT)),
                "sha256": sha256(SAVED_REPORT / "runner_predictions.parquet"),
            },
        },
        "folds": fold_receipts,
        "replay_outputs": {name: sha256(OUT / name) for name in outputs},
    }
    _write_json_new(receipt_path, receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(replay(), ensure_ascii=False, indent=2))

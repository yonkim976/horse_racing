"""Replay the three frozen F1 models against the fixed historical feature rows.

No model is trained and no temperature is optimized. Replayed predictions,
race summaries, and six-set outputs are checked against saved F1 artifacts.
"""
import sys

sys.dont_write_bytecode = True

import hashlib
import importlib.util
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
F1_OUT = F1_DIR / "outputs"
BASE_RUN = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/run.py"
ORIGINAL_FEATURES = F1_OUT / "features.parquet"
CANDIDATE_FEATURES = OUT / "features_f1s.parquet"
PREDICTIONS = F1_OUT / "runner_predictions_canonical.parquet"
RACE_METRICS = F1_OUT / "race_metrics.csv"
SIX_SETS = F1_OUT / "six_combinations.csv"
YEARS = (2024, 2025, 2026)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_new(path):
    if Path(path).exists():
        raise FileExistsError(f"refusing to overwrite replay output: {path}")


def compare_frames(saved, replayed, key, numeric_columns, string_columns=(), atol=1e-12):
    left = saved.sort_values(key, kind="stable").reset_index(drop=True)
    right = replayed.sort_values(key, kind="stable").reset_index(drop=True)
    assert len(left) == len(right)
    for column in key:
        assert left[column].astype(str).equals(right[column].astype(str)), column
    for column in string_columns:
        assert left[column].fillna("<NULL>").astype(str).equals(
            right[column].fillna("<NULL>").astype(str)
        ), column
    for column in numeric_columns:
        assert np.allclose(
            pd.to_numeric(left[column], errors="coerce").to_numpy(float),
            pd.to_numeric(right[column], errors="coerce").to_numpy(float),
            rtol=0, atol=atol, equal_nan=True,
        ), column


def main():
    preflight_path = OUT / "candidate_feature_preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    assert preflight["passed"]
    assert preflight["fit_executed"] is False
    assert preflight["output_sha256"] == sha256(CANDIDATE_FEATURES)
    for relative, info in preflight["references"].items():
        path = ROOT / relative
        assert path.stat().st_size == info["bytes"] and sha256(path) == info["sha256"], relative

    spec = importlib.util.spec_from_file_location("section_time_saved_f1_reference", BASE_RUN)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)

    original = pd.read_parquet(ORIGINAL_FEATURES)
    features = pd.read_parquet(CANDIDATE_FEATURES)
    additions = preflight["candidate_additional_columns"]
    pd.testing.assert_frame_equal(
        features[original.columns], original, check_dtype=True, check_exact=True,
    )
    assert len(features) == 52155 and features.race_id.nunique() == 5206

    frozen_predictions = pd.read_parquet(PREDICTIONS)
    frozen_predictions = frozen_predictions.loc[frozen_predictions.variant.eq("F1")].copy()
    frozen_races = pd.read_csv(RACE_METRICS)
    frozen_races = frozen_races.loc[frozen_races.variant.eq("F1")].copy()
    frozen_sets = pd.read_csv(SIX_SETS)
    frozen_sets = frozen_sets.loc[frozen_sets.variant.eq("F1")].copy()
    assert (len(frozen_predictions), frozen_predictions.race_id.nunique()) == (17412, 1779)
    assert len(frozen_races) == 1779
    assert len(frozen_sets) == 10674

    runners, races, six_sets = [], [], []
    model_hashes = {}
    for year in YEARS:
        folder = F1_OUT / f"F1_{year}"
        meta_path = folder / "meta.json"
        model_path = folder / "top3.txt"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["variant"] == "F1" and int(meta["evaluation_year"]) == year
        assert len(meta["features"]) == 24
        assert int(meta["seed"]) == 20261008
        assert sha256(model_path) == meta["model_sha256"]
        assert meta["parameters"] == base.PARAMS
        model = lgb.Booster(model_file=str(model_path))
        test = features.loc[features.year.eq(year)].reset_index(drop=True)
        x = test[meta["features"]].copy()
        for column, vocabulary in meta["vocabulary"].items():
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocabulary)
        scores = model.predict(x, raw_score=True, num_threads=4)
        race_result, runner_result, set_result = base.evaluate(
            test, scores, float(meta["tau"]), "F1"
        )

        year_predictions = frozen_predictions.loc[frozen_predictions.year.eq(year)].copy()
        compare_frames(
            year_predictions, runner_result, ["api_record_id"],
            ["score", "p_top3", "y", "log_loss", "brier"],
        )
        year_races = frozen_races.loc[frozen_races.year.eq(year)].copy()
        metric_columns = [
            "field_n", "log_loss", "brier", "trio_nll", "six_combo_hit", "six_combo_mass",
            "top3_capture", "top3_all3", "top4_capture", "top4_all3",
            "top5_capture", "top5_all3", "top6_capture", "top6_all3",
        ]
        metric_columns = [column for column in metric_columns if column in year_races.columns]
        compare_frames(year_races, race_result, ["race_id"], metric_columns)
        year_sets = frozen_sets.loc[frozen_sets.race_id.isin(set_result.race_id)].copy()
        compare_frames(
            year_sets, set_result, ["race_id", "selection_rank"], ["probability", "hit"],
            string_columns=["numbers"],
        )
        runners.append(runner_result)
        races.append(race_result)
        six_sets.append(set_result)
        model_hashes[str(year)] = sha256(model_path)
        print(
            f"F1 saved-model replay {year}: {len(runner_result):,} runners, "
            f"{len(race_result):,} races, {len(set_result):,} six-sets; exact saved-output match.",
            flush=True,
        )

    replay_runner = pd.concat(runners, ignore_index=True)
    replay_races = pd.concat(races, ignore_index=True)
    replay_sets = pd.concat(six_sets, ignore_index=True)
    assert (len(replay_runner), replay_runner.race_id.nunique()) == (17412, 1779)
    assert (len(replay_races), len(replay_sets)) == (1779, 10674)

    runner_path = OUT / "f1_reproduced_runner_predictions.parquet"
    race_path = OUT / "f1_reproduced_race_metrics.csv"
    sets_path = OUT / "f1_reproduced_six_combinations.csv"
    receipt_path = OUT / "f1_saved_model_replay.json"
    for path in (runner_path, race_path, sets_path, receipt_path):
        ensure_new(path)
    replay_runner.to_parquet(runner_path, index=False)
    replay_races.to_csv(race_path, index=False)
    replay_sets.to_csv(sets_path, index=False)
    receipt = {
        "passed": True,
        "saved_models_reloaded": 3,
        "model_refit_count": 0,
        "temperature_optimization_count": 0,
        "scored_runner_rows": int(len(replay_runner)),
        "scored_races": int(len(replay_races)),
        "replayed_six_set_rows": int(len(replay_sets)),
        "frozen_predictions_race_metrics_and_six_sets_match": True,
        "original_f1_feature_columns_unchanged_in_candidate_artifact": True,
        "candidate_columns_used_for_f1_replay": [],
        "candidate_columns_defined_but_not_scored": additions,
        "frozen_model_sha256": model_hashes,
        "replay_code_sha256": sha256(HERE / "replay_saved_f1.py"),
        "candidate_feature_sha256": sha256(CANDIDATE_FEATURES),
        "outputs": {
            runner_path.name: sha256(runner_path),
            race_path.name: sha256(race_path),
            sets_path.name: sha256(sets_path),
        },
        "production_changed": False,
        "database_changed": False,
    }
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

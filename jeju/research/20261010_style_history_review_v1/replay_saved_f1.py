"""Independent replay of the locked F1 models and stored predictions.

Reads existing artifacts only. It does not fit a model, optimize calibration,
query the database, or write outside this review directory.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
F1_OUT = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs"
OUT_DIR = HERE / "saved_f1_replay"
YEARS = (2024, 2025, 2026)
ATOL = 1e-12


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def numeric_equal(left: pd.Series, right: pd.Series, name: str) -> None:
    a = pd.to_numeric(left, errors="coerce").to_numpy(dtype=np.float64)
    b = pd.to_numeric(right, errors="coerce").to_numpy(dtype=np.float64)
    assert np.allclose(a, b, rtol=0, atol=ATOL, equal_nan=True), name


def key_equal(left: pd.Series, right: pd.Series, name: str) -> None:
    a = left.fillna("<NA>").astype(str).reset_index(drop=True)
    b = right.fillna("<NA>").astype(str).reset_index(drop=True)
    assert a.equals(b), name


def compare_frames(
    expected: pd.DataFrame,
    observed: pd.DataFrame,
    keys: list[str],
    numeric: list[str],
    strings: list[str] = (),
    booleans: list[str] = (),
) -> None:
    left = expected.sort_values(keys, kind="stable").reset_index(drop=True)
    right = observed.sort_values(keys, kind="stable").reset_index(drop=True)
    assert len(left) == len(right), (len(left), len(right))
    for column in keys + list(strings):
        key_equal(left[column], right[column], column)
    for column in numeric:
        numeric_equal(left[column], right[column], column)
    for column in booleans:
        assert left[column].astype(bool).equals(right[column].astype(bool)), column


def score_frame(features: pd.DataFrame, model_meta: dict, model: lgb.Booster) -> pd.DataFrame:
    columns = model_meta["features"]
    assert list(model.feature_name()) == columns
    x = features[columns].copy()
    for column, vocabulary in model_meta["vocabulary"].items():
        assert column in columns
        x[column] = pd.Categorical(x[column], categories=vocabulary)
    scores = model.predict(x, raw_score=True, num_threads=4)
    return pd.DataFrame({"api_record_id": features.api_record_id.to_numpy(), "score": scores})


def evaluate_race(frame: pd.DataFrame, scores: np.ndarray, tau: float) -> tuple[dict, list[dict], list[dict]]:
    n = len(frame)
    assert n >= 6
    assert frame.horse_number.is_monotonic_increasing
    triples = np.asarray(list(itertools.combinations(range(n), 3)), dtype=np.int64)
    energy = np.sort(scores[triples], axis=1).sum(axis=1)

    truth_positions = np.flatnonzero(frame.finish_position.to_numpy(dtype=float) <= 3)
    assert len(truth_positions) == 3
    truth_mask = (triples == truth_positions[None, :]).all(axis=1)
    assert int(truth_mask.sum()) == 1
    target_index = int(np.flatnonzero(truth_mask)[0])

    scaled_energy = energy / float(tau)
    log_q = scaled_energy - float(logsumexp(scaled_energy))
    q = np.exp(log_q)
    incidence = np.zeros((len(triples), n), dtype=np.float64)
    incidence[np.arange(len(triples))[:, None], triples] = 1.0
    p_top3 = q @ incidence
    assert np.isclose(float(q.sum()), 1.0, rtol=0, atol=1e-12)
    assert np.isclose(float(p_top3.sum()), 3.0, rtol=0, atol=1e-10)

    y = frame.finish_position.to_numpy(dtype=float) <= 3
    y_float = y.astype(np.float64)
    clipped = np.clip(p_top3, 1e-12, 1.0 - 1e-12)
    runner_ll = -y_float * np.log(clipped) - (~y) * np.log1p(-clipped)
    runner_brier = (p_top3 - y_float) ** 2
    raw_order = np.argsort(-scores, kind="stable")
    best_combos = np.argsort(-energy, kind="stable")[:6]
    true_triple = set(triples[target_index].tolist())

    race = {
        "race_id": frame.race_id.iloc[0],
        "race_date": frame.race_date.iloc[0],
        "year": int(frame.year.iloc[0]),
        "variant": "F1",
        "distance_m": int(frame.distance_m.iloc[0]),
        "grade_raw": frame.grade_raw.iloc[0],
        "field_n": int(n),
        "any_no_history": bool(frame.observed_starts.eq(0).any()),
        "any_low_history": bool(frame.observed_starts.lt(5).any()),
        "any_no_same_time": bool(frame.same_valid_times.eq(0).any()),
        "log_loss": float(runner_ll.mean()),
        "brier": float(runner_brier.mean()),
        "trio_nll": float(-log_q[target_index]),
        "six_combo_hit": int(target_index in set(best_combos.tolist())),
        "six_combo_mass": float(q[best_combos].sum()),
    }
    for k in (3, 4, 5, 6):
        selected = set(raw_order[:k].tolist())
        race[f"top{k}_capture"] = len(true_triple & selected) / 3.0
        race[f"top{k}_all3"] = int(true_triple.issubset(selected))

    runners = []
    for local, row in enumerate(frame.itertuples(index=False)):
        runners.append({
            "api_record_id": row.api_record_id,
            "race_id": row.race_id,
            "race_date": row.race_date,
            "year": int(row.year),
            "distance_m": int(row.distance_m),
            "grade_raw": row.grade_raw,
            "horse_id": row.horse_id,
            "horse_number": int(row.horse_number),
            "observed_starts": row.observed_starts,
            "same_valid_times": row.same_valid_times,
            "field_n": int(n),
            "variant": "F1",
            "score": float(scores[local]),
            "p_top3": float(p_top3[local]),
            "y": int(y[local]),
            "log_loss": float(runner_ll[local]),
            "brier": float(runner_brier[local]),
            "previous_result_status": row.previous_result_status,
            "previous_top3": row.previous_top3,
            "same_starts": row.same_starts,
            "same_distance_last5_actual_n": row.same_distance_last5_actual_n,
            "same_distance_last5_normal_n": row.same_distance_last5_normal_n,
            "same_distance_last5_top3_rate": row.same_distance_last5_top3_rate,
        })

    horse_numbers = frame.horse_number.to_numpy()
    tickets = []
    for rank, combo_index in enumerate(best_combos, start=1):
        combo = triples[combo_index]
        tickets.append({
            "race_id": frame.race_id.iloc[0],
            "variant": "F1",
            "selection_rank": rank,
            "numbers": ",".join(str(int(value)) for value in horse_numbers[combo]),
            "probability": float(q[combo_index]),
            "hit": int(int(combo_index) == target_index),
        })
    return race, runners, tickets


def main() -> None:
    assert not OUT_DIR.exists(), f"refusing to overwrite {OUT_DIR}"
    features_path = F1_OUT / "features.parquet"
    saved_runner_path = F1_OUT / "runner_predictions.parquet"
    saved_race_path = F1_OUT / "race_metrics.csv"
    saved_ticket_path = F1_OUT / "six_combinations.csv"
    saved_runner = pd.read_parquet(saved_runner_path)
    saved_runner = saved_runner.loc[saved_runner.variant.eq("F1")].copy()
    saved_races = pd.read_csv(saved_race_path)
    saved_races = saved_races.loc[saved_races.variant.eq("F1")].copy()
    saved_tickets = pd.read_csv(saved_ticket_path)
    saved_tickets = saved_tickets.loc[saved_tickets.variant.eq("F1")].copy()
    features = pd.read_parquet(features_path)
    assert len(features) == 52155 and features.api_record_id.is_unique
    assert features.race_id.nunique() == 5206
    assert len(saved_runner) == 17412 and saved_runner.api_record_id.is_unique
    assert saved_runner.race_id.nunique() == 1779
    assert len(saved_races) == 1779 and len(saved_tickets) == 1779 * 6

    replay_scores: dict[int, dict[str, pd.DataFrame]] = {}
    replay_races: list[dict] = []
    replay_runners: list[dict] = []
    replay_tickets: list[dict] = []
    model_info = {}
    calibration_info = {}

    for year in YEARS:
        folder = F1_OUT / f"F1_{year}"
        model_path = folder / "top3.txt"
        meta_path = folder / "meta.json"
        calibration_path = folder / "calibration_scores.parquet"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["variant"] == "F1" and int(meta["evaluation_year"]) == year
        assert meta["model_sha256"] == sha256(model_path)
        assert len(meta["features"]) == 24
        model = lgb.Booster(model_file=str(model_path))
        assert int(model.current_iteration()) == int(meta["trees"])
        assert model.feature_name() == meta["features"]

        calibration = features.loc[features.year.eq(year - 1)].reset_index(drop=True)
        calibration_scores = score_frame(calibration, meta, model)
        saved_calibration = pd.read_parquet(calibration_path)
        compare_frames(saved_calibration, calibration_scores, ["api_record_id"], ["score"])
        assert len(calibration_scores) == int(meta["calibration_rows"] if "calibration_rows" in meta else len(saved_calibration))
        calibration_info[str(year)] = {
            "rows": int(len(calibration_scores)),
            "saved_score_match_atol_1e-12": True,
            "tau_fixed_from_saved_meta": float(meta["tau"]),
        }

        evaluation = features.loc[features.year.eq(year)].reset_index(drop=True)
        scored = score_frame(evaluation, meta, model)
        scores = scored.score.to_numpy(dtype=np.float64)
        replay_scores[year] = {"scores": scored, "features": evaluation}
        for race_id, positions in evaluation.groupby("race_id", sort=False).indices.items():
            idx = np.asarray(positions, dtype=np.int64)
            one = evaluation.iloc[idx]
            race, runners, tickets = evaluate_race(one, scores[idx], float(meta["tau"]))
            assert race["race_id"] == race_id
            replay_races.append(race)
            replay_runners.extend(runners)
            replay_tickets.extend(tickets)

        model_info[str(year)] = {
            "model_sha256": meta["model_sha256"],
            "meta_sha256": sha256(meta_path),
            "trees": int(meta["trees"]),
            "model_loaded_iteration": int(model.current_iteration()),
            "input_feature_count": len(meta["features"]),
            "test_rows_scored": int(len(evaluation)),
            "test_races_scored": int(evaluation.race_id.nunique()),
            "tau_fixed_from_saved_meta": float(meta["tau"]),
        }

    replay_runner = pd.DataFrame.from_records(replay_runners)
    replay_race = pd.DataFrame.from_records(replay_races)
    replay_ticket = pd.DataFrame.from_records(replay_tickets)

    runner_numeric = [
        "score", "p_top3", "y", "log_loss", "brier", "field_n",
        "observed_starts", "same_valid_times", "previous_top3", "same_starts",
        "same_distance_last5_actual_n", "same_distance_last5_normal_n",
        "same_distance_last5_top3_rate",
    ]
    runner_strings = ["race_id", "race_date", "horse_id", "variant", "grade_raw", "previous_result_status"]
    compare_frames(saved_runner, replay_runner,
                   ["api_record_id"], runner_numeric,
                   strings=runner_strings)
    compare_frames(saved_races, replay_race,
                   ["race_id"],
                   ["year", "distance_m", "field_n", "log_loss", "brier", "trio_nll",
                    "six_combo_hit", "six_combo_mass", "top3_capture", "top3_all3",
                    "top4_capture", "top4_all3", "top5_capture", "top5_all3",
                    "top6_capture", "top6_all3"],
                   strings=["race_date", "variant", "grade_raw"],
                   booleans=["any_no_history", "any_low_history", "any_no_same_time"])
    compare_frames(saved_tickets, replay_ticket,
                   ["race_id", "selection_rank"],
                   ["probability", "hit"],
                   strings=["variant", "numbers"])

    assert len(replay_runner) == 17412
    assert len(replay_race) == 1779
    assert len(replay_ticket) == 10674
    db_lock = json.loads((F1_OUT / "prepared_lock.json").read_text(encoding="utf-8"))["protected"]
    current_protected = {}
    for relative, info in db_lock.items():
        path = ROOT / relative
        if relative == "jeju/data/jeju_native_core.sqlite3":
            assert path.stat().st_size == int(info["bytes"])
            current_protected[relative] = {
                "bytes": int(path.stat().st_size),
                "sha256": info["sha256"],
                "sha_reused_from_f1_lock_without_rehash": True,
            }
        else:
            current_hash = sha256(path)
            assert current_hash == info["sha256"] and path.stat().st_size == int(info["bytes"]), relative
            current_protected[relative] = {
                "bytes": int(path.stat().st_size),
                "sha256": current_hash,
                "matches_f1_lock": True,
            }

    receipt = {
        "status": "independent_saved_f1_replay_passed",
        "fit_or_refit_count": 0,
        "temperature_optimization_count": 0,
        "models_reloaded": 3,
        "evaluation_rows": len(replay_runner),
        "evaluation_races": len(replay_race),
        "evaluation_days": int(replay_race.race_date.nunique()),
        "six_combination_rows": len(replay_ticket),
        "all_saved_runner_scores_probabilities_losses_match_atol_1e-12": True,
        "all_saved_race_metrics_match_atol_1e-12": True,
        "all_saved_canonical_six_combinations_and_probabilities_match_atol_1e-12": True,
        "probability_sums": {
            "joint_distribution_equals_one": True,
            "runner_top3_marginals_equal_three": True,
        },
        "calibration_raw_scores_match_saved_atol_1e-12": calibration_info,
        "model_replay": model_info,
        "protected_current_vs_locked": current_protected,
        "source_hashes": {
            "features.parquet": {"bytes": features_path.stat().st_size, "sha256": sha256(features_path)},
            "runner_predictions.parquet": {"bytes": saved_runner_path.stat().st_size, "sha256": sha256(saved_runner_path)},
            "race_metrics.csv": {"bytes": saved_race_path.stat().st_size, "sha256": sha256(saved_race_path)},
            "six_combinations.csv": {"bytes": saved_ticket_path.stat().st_size, "sha256": sha256(saved_ticket_path)},
        },
        "metric_direction": "No candidate-versus-F1 difference is computed in this baseline replay.",
        "limitations": [
            "Replay checks existing fixed F1 outputs; it does not validate new style-history feature construction or candidate performance.",
            "The preserved SQLite SHA is reused from the existing F1 lock after checking file size; this replay did not query or rehash the full database.",
        ],
    }

    OUT_DIR.mkdir(exist_ok=False)
    replay_runner.to_parquet(OUT_DIR / "runner_predictions.parquet", index=False)
    replay_race.to_csv(OUT_DIR / "race_metrics.csv", index=False, encoding="utf-8")
    replay_ticket.to_csv(OUT_DIR / "six_combinations.csv", index=False, encoding="utf-8")
    receipt["replay_outputs"] = {
        name: {"bytes": (OUT_DIR / name).stat().st_size, "sha256": sha256(OUT_DIR / name)}
        for name in ("runner_predictions.parquet", "race_metrics.csv", "six_combinations.csv")
    }
    receipt_path = OUT_DIR / "receipt.json"
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "status": receipt["status"],
        "rows": receipt["evaluation_rows"],
        "races": receipt["evaluation_races"],
        "days": receipt["evaluation_days"],
        "six_combination_rows": receipt["six_combination_rows"],
        "output": str(OUT_DIR),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

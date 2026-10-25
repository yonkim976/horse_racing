"""Independent, read-only verification of frozen model inputs and saved scores.

This script checks research artifacts only. It never trains or writes predictions;
the only write is outputs/verification.json.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from itertools import combinations, permutations
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp
from scipy.stats import rankdata


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESEARCH = HERE.parent
OUT = HERE / "outputs"
SOURCE = RESEARCH / "20261009_gate_front_late_v1/outputs"
ABILITY = RESEARCH / "20261008_profile_carried_weight_v1/outputs"
KEY = ["race_key", "program_no", "horse_id"]
BASE_VARIANTS = ["ability22", "early47", "late66", "additive89", "full103"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def repo_path(relative: str) -> Path:
    """Resolve a manifest path and reject absolute paths or repo escapes."""
    candidate = Path(relative)
    if candidate.is_absolute():
        raise AssertionError(f"absolute path in manifest: {relative}")
    resolved = (ROOT / candidate).resolve()
    if not resolved.is_relative_to(ROOT):
        raise AssertionError(f"path escapes repository: {relative}")
    return resolved


def category_columns(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [name for name in columns if not pd.api.types.is_numeric_dtype(frame[name])]


def expected_contracts() -> dict[str, list[str]]:
    """Reconstruct feature sets from source contracts without importing run.py."""
    source_full = read_json(SOURCE / "feature_contract.json")["full103"]
    ability = read_json(ABILITY / "research_baseline_selection.json")["features"]
    shared = ["section_previous_distance", "section_same_distance_n5"]
    early_block = [
        name for name in source_full
        if name.startswith("section_early_") or name.startswith("dirgate_")
    ]
    early_block += [
        name for name in source_full
        if name.startswith("style_role")
        or name in {"style_solo_mean5", "style_group_mean_relative_mean5"}
    ]
    late_block = [
        name for name in source_full
        if name.startswith(("section_last600_", "section_late_", "rolelate_"))
    ]
    late_block += [
        name for name in source_full
        if name.startswith(("style_middle_", "style_gain", "style_recovery_", "style_fade_"))
    ]
    result = {
        "ability22": ability,
        "early47": ability + shared + early_block,
        "late66": ability + shared + late_block,
        "additive89": ability + shared + early_block + late_block,
        "full103": source_full,
    }
    expected_counts = {"ability22": 22, "early47": 47, "late66": 66,
                       "additive89": 89, "full103": 103}
    for name, columns in result.items():
        assert len(columns) == expected_counts[name], (name, len(columns))
        assert len(columns) == len(set(columns)), f"duplicate feature in {name}"
    return result


def verify_feature_contracts() -> dict:
    expected = expected_contracts()
    recorded = read_json(OUT / "feature_contract.json")
    assert recorded == expected, "saved feature contract differs from independently reconstructed sets"

    early = set(expected["early47"])
    late = set(expected["late66"])
    additive = set(expected["additive89"])
    full = set(expected["full103"])
    assert additive == early | late, "additive89 is not exactly early47 union late66"
    assert set(expected["ability22"]) <= early & late
    assert additive < full
    full_only = full - additive
    assert len(full_only) == 14, f"expected 14 full103-only features, got {len(full_only)}"
    assert {"front_gate_probability", "front_prediction_supported"} <= full_only
    assert not any(name.startswith("rolelate_") or name.startswith("section_late_")
                   or name.startswith("section_last600_")
                   or name.startswith(("style_middle_", "style_gain", "style_recovery_", "style_fade_"))
                   or name in {"front_gate_probability", "front_prediction_supported"}
                   for name in early), "early47 contains late/forecast-trained input"
    assert not any(name.startswith("section_early_") or name.startswith("dirgate_")
                   or name.startswith("style_role")
                   or name in {"style_solo_mean5", "style_group_mean_relative_mean5"}
                   for name in late), "late66 contains early block input"
    assert {"section_previous_distance", "section_same_distance_n5"} <= early & late
    return {
        "feature_counts": {name: len(columns) for name, columns in expected.items()},
        "full103_only_count": len(full_only),
        "full103_only_features": sorted(full_only),
        "early47_excludes_late_and_front_forecast": True,
        "late66_excludes_early_block": True,
        "additive89_is_early47_union_late66": True,
        "saved_contract_matches_independent_reconstruction": True,
    }


def verify_frozen_inputs() -> dict:
    manifest_path = OUT / "input_manifest.json"
    manifest = read_json(manifest_path)
    verified = []
    for relative, expected in manifest.items():
        path = repo_path(relative)
        assert path.is_file(), f"manifest input missing: {relative}"
        size = path.stat().st_size
        digest = sha256(path)
        assert size == expected["bytes"], f"byte count changed: {relative}"
        assert digest == expected["sha256"], f"SHA-256 changed: {relative}"
        verified.append(relative)

    protocol = read_json(OUT / "protocol_frozen.json")
    assert sha256(HERE / "PLAN.md") == protocol["plan_sha256"], "frozen PLAN changed"
    assert sha256(HERE / "config.json") == protocol["config_sha256"], "frozen config changed"
    assert protocol["new_evaluation_started"] is False, "freeze marker was changed"
    training = read_json(OUT / "training_complete.json")
    current_run_sha = sha256(HERE / "run.py")
    assert training["training_code_sha256"] == protocol["initial_run_code_sha256"], \
        "training code fingerprint differs from the frozen initial run.py"
    assert training["training_code_sha256"] == current_run_sha, \
        "current run.py differs from the code fingerprint used to train"
    expected_fingerprint = sha256(manifest_path)
    assert training["new_final_models"] == 18
    assert training["reused_models"] == 12
    assert training["folds"] == 30
    assert training["source_rows"] == 178497
    return {
        "manifest_entries": len(verified),
        "all_manifest_sha256_and_bytes_match": True,
        "plan_and_config_match_frozen_protocol": True,
        "freeze_timestamp": protocol["frozen_at_utc"],
        "new_evaluation_started_at_freeze": protocol["new_evaluation_started"],
        "training_code_sha256": training["training_code_sha256"],
        "current_run_sha256_matches_training": True,
        "input_fingerprint": expected_fingerprint,
        "training_complete_counts": training,
    }


def load_corpus(contract: dict[str, list[str]]) -> pd.DataFrame:
    columns = list(dict.fromkeys(KEY + [
        "meet", "race_date", "year", "grade_raw", "outcome", "cutoff_date",
        "history_source_date", "profile_source_date", "weight_source_date",
    ] + contract["full103"]))
    frame = pd.read_parquet(SOURCE / "features.parquet", columns=columns)
    assert len(frame) == 178497, f"unexpected source row count: {len(frame)}"
    assert not frame.duplicated(KEY).any(), "duplicate runner key"
    assert frame["meet"].isin([1, 3]).all(), "non-thoroughbred/Jeju venue in source"
    assert frame["year"].ge(2017).all(), "source includes rows before the frozen model range"
    frame = frame.sort_values(["meet", "race_date", "race_key", "program_no"]).reset_index(drop=True)
    frame["row_number"] = np.arange(len(frame), dtype=np.int64)

    race_date = pd.to_datetime(frame["race_date"], errors="raise")
    assert race_date.dt.year.eq(frame["year"]).all(), "race_date/year mismatch"
    assert frame["cutoff_date"].notna().all(), "missing feature cutoff date"
    cutoff = pd.to_datetime(frame["cutoff_date"], errors="raise")
    for name in ["history_source_date", "profile_source_date", "weight_source_date"]:
        source_date = pd.to_datetime(frame[name], errors="coerce")
        assert (source_date.isna() | source_date.le(cutoff)).all(), \
            f"future source date in {name}"

    grouped = frame.groupby("race_key", sort=False)
    assert grouped["year"].nunique().eq(1).all(), "race spans calendar-year partitions"
    assert grouped["meet"].nunique().eq(1).all(), "race_key collides across venues"
    assert grouped.size().eq(grouped["field_size"].first()).all(), \
        "race rows differ from recorded field_size"
    for position in (1, 2, 3):
        podium_counts = frame["outcome"].eq(position).groupby(frame["race_key"]).sum()
        assert podium_counts.eq(1).all(), f"race has non-unique outcome {position}"
    return frame


def split_masks(frame: pd.DataFrame, evaluation_year: int) -> dict[str, pd.Series]:
    year = frame["year"]
    return {
        "initial": year.between(2017, evaluation_year - 3),
        "validation": year.eq(evaluation_year - 2),
        "calibration": year.eq(evaluation_year - 1),
        "evaluation": year.eq(evaluation_year),
    }


def source_model(variant: str, venue: int, year: int) -> tuple[Path, str]:
    if variant == "ability22":
        return ABILITY / "models" / f"{venue}_{year}_month_gate_weight22", "top3.txt"
    return SOURCE / "models" / f"full103_{venue}_{year}", "model.txt"


def verify_models_and_scores(frame: pd.DataFrame, contract: dict[str, list[str]],
                             config: dict, input_fingerprint: str,
                             training_code_sha: str) -> dict:
    results = []
    total_eval_races = 0
    cohort_summary = {}
    for venue in config["venues"]:
        one = frame.loc[frame["meet"].eq(venue)].reset_index(drop=True)
        one_categories = {name: sorted(one[name].dropna().unique().tolist())
                          for name in set().union(*(set(contract[v]) for v in BASE_VARIANTS))
                          if not pd.api.types.is_numeric_dtype(one[name])}
        for evaluation_year in config["evaluation_years"]:
            masks = split_masks(one, evaluation_year)
            expected_rows = {phase: one.loc[mask, "row_number"].to_numpy(dtype=np.int64)
                             for phase, mask in masks.items()}
            expected_races = int(one.loc[masks["evaluation"], "race_key"].nunique())
            total_eval_races += expected_races
            cohort_summary[f"{venue}_{evaluation_year}"] = {
                "initial_rows": int(masks["initial"].sum()),
                "validation_rows": int(masks["validation"].sum()),
                "calibration_rows": int(masks["calibration"].sum()),
                "evaluation_rows": int(masks["evaluation"].sum()),
                "evaluation_races": expected_races,
            }

            refit_rows = one.loc[masks["initial"] | masks["validation"]]
            expected_train_end = pd.to_datetime(refit_rows["race_date"]).max().date().isoformat()
            expected_train_vocab = {}
            for variant in ("early47", "late66", "additive89"):
                for column in category_columns(one, contract[variant]):
                    expected_train_vocab.setdefault(column, sorted(
                        one.loc[masks["initial"], column].dropna().unique().tolist()
                    ))

            for variant in BASE_VARIANTS:
                folder = OUT / "models" / f"{variant}_{venue}_{evaluation_year}"
                metadata_path = folder / "metadata.json"
                score_path = folder / "scores.parquet"
                metadata = read_json(metadata_path)
                assert metadata["variant"] == variant
                assert metadata["venue"] == venue
                assert metadata["evaluation_year"] == evaluation_year
                assert metadata["validation_year"] == evaluation_year - 2
                assert metadata["calibration_year"] == evaluation_year - 1
                assert metadata["training_min"] == "2017-01-01"
                assert metadata["train_end"] == expected_train_end, \
                    f"{variant}/{venue}/{evaluation_year}: train_end mismatch"
                assert metadata["features"] == contract[variant], \
                    f"{variant}/{venue}/{evaluation_year}: feature list mismatch"
                assert metadata["input_fingerprint"] == input_fingerprint
                assert metadata["training_code_sha256"] == training_code_sha
                assert 1 <= int(metadata["trees"]) <= int(config["training"]["max_rounds"])
                assert config["temperature_bounds"][0] <= float(metadata["temperature"]) <= \
                    config["temperature_bounds"][1]

                cats = category_columns(one, contract[variant])
                vocabulary = metadata["category_vocabulary"]
                assert set(vocabulary) == set(cats), \
                    f"{variant}/{venue}/{evaluation_year}: category vocabulary columns mismatch"
                for column in cats:
                    assert vocabulary[column] == sorted(vocabulary[column]), \
                        f"{column} vocabulary is not deterministic/sorted"
                    assert set(vocabulary[column]) <= set(one_categories[column]), \
                        f"{column} vocabulary contains values outside the saved cohort"
                if variant in {"early47", "late66", "additive89"}:
                    assert vocabulary == expected_train_vocab, \
                        f"{variant}/{venue}/{evaluation_year}: vocab not derived from initial train years"

                expected_counts = {name: int(mask.sum()) for name, mask in masks.items()}
                assert metadata["rows"] == expected_counts, \
                    f"{variant}/{venue}/{evaluation_year}: split row counts mismatch"
                assert bool(metadata["reused"]) == (variant in {"ability22", "full103"})

                if metadata["reused"]:
                    source_folder, filename = source_model(variant, venue, evaluation_year)
                    source_model_path = source_folder / filename
                    source_metadata = read_json(source_folder / "metadata.json")
                    assert metadata["model_path"] == source_model_path.relative_to(ROOT).as_posix()
                    assert metadata["features"] == source_metadata["features"]
                    assert vocabulary == source_metadata["category_vocabulary"]
                    model_path = source_model_path
                    assert metadata["model_sha256"] == source_metadata["model_sha256"]
                else:
                    model_path = folder / "model.txt"
                    assert metadata["model_path"] == model_path.relative_to(ROOT).as_posix()
                assert model_path.is_file(), f"model file missing: {model_path}"
                model_hash = sha256(model_path)
                assert metadata["model_sha256"] == model_hash, \
                    f"{variant}/{venue}/{evaluation_year}: model hash mismatch"

                scores = pd.read_parquet(score_path)
                assert list(scores.columns) == ["row_number", "score", "phase"]
                assert scores["row_number"].notna().all() and scores["row_number"].is_unique
                assert scores["phase"].isin(["calibration", "evaluation"]).all()
                assert np.isfinite(scores["score"].to_numpy(dtype=float)).all()
                actual_rows = {
                    phase: scores.loc[scores["phase"].eq(phase), "row_number"].to_numpy(dtype=np.int64)
                    for phase in ("calibration", "evaluation")
                }
                for phase in ("calibration", "evaluation"):
                    assert np.array_equal(actual_rows[phase], expected_rows[phase]), \
                        f"{variant}/{venue}/{evaluation_year}: {phase} runner keys/cohort mismatch"

                # Predict in memory only; no new score or probability file is emitted.
                model = lgb.Booster(model_file=str(model_path))
                assert model.num_trees() == int(metadata["trees"]), \
                    f"{variant}/{venue}/{evaluation_year}: model tree count mismatch"
                assert model.feature_name() == contract[variant], \
                    f"{variant}/{venue}/{evaluation_year}: model feature names mismatch"
                x = one[contract[variant]].copy()
                for column in cats:
                    x[column] = pd.Categorical(x[column], categories=vocabulary[column])

                phase_errors = {}
                for phase in ("calibration", "evaluation"):
                    mask = masks[phase]
                    predicted = np.asarray(model.predict(
                        x.loc[mask], raw_score=True, num_threads=4
                    ), dtype=float)
                    stored = scores.loc[scores["phase"].eq(phase), "score"].to_numpy(dtype=float)
                    assert predicted.shape == stored.shape
                    max_abs = float(np.max(np.abs(predicted - stored))) if len(stored) else 0.0
                    assert np.allclose(predicted, stored, rtol=1e-7, atol=1e-7), \
                        f"{variant}/{venue}/{evaluation_year}: {phase} score reproduction error {max_abs}"
                    phase_errors[phase] = max_abs

                results.append({
                    "variant": variant,
                    "venue": venue,
                    "evaluation_year": evaluation_year,
                    "reused": bool(metadata["reused"]),
                    "model_sha256": model_hash,
                    "trees": model.num_trees(),
                    "rows": expected_counts,
                    "calibration_score_max_abs_error": phase_errors["calibration"],
                    "evaluation_score_max_abs_error": phase_errors["evaluation"],
                    "score_file_sha256": sha256(score_path),
                })

    assert len(results) == 30, f"expected 30 base-model folds, found {len(results)}"
    assert total_eval_races == 4799, f"evaluation race cohort changed: {total_eval_races}"
    return {
        "verified_model_folds": len(results),
        "verified_reused_models": sum(row["reused"] for row in results),
        "verified_new_models": sum(not row["reused"] for row in results),
        "all_variants_share_identical_per_fold_calibration_and_evaluation_keys": True,
        "predict_reproduces_saved_raw_scores": True,
        "max_absolute_score_error": max(max(row["calibration_score_max_abs_error"],
                                              row["evaluation_score_max_abs_error"])
                                         for row in results),
        "evaluation_races": total_eval_races,
        "fold_cohort": cohort_summary,
        "model_folds": results,
    }


def reference_pair_features(frame: pd.DataFrame) -> np.ndarray:
    """Small independent implementation of the frozen FP pair feature contract."""
    front = frame["front_gate_probability"].to_numpy(dtype=float, na_value=np.nan)
    last600 = frame["section_last600_mean3"].to_numpy(dtype=float, na_value=np.nan)
    late = frame["section_late_mean3"].to_numpy(dtype=float, na_value=np.nan)
    front = np.where(np.isfinite(front), front, 0.0)

    def rank(values: np.ndarray) -> np.ndarray:
        valid = np.isfinite(values)
        result = np.full(len(frame), np.nan)
        if valid.any():
            result[valid] = 2 * (rankdata(-values[valid], method="average") - 0.5) / valid.sum() - 1
        return result

    r600, r200 = rank(last600), rank(late)
    rows = []
    for triple in combinations(range(len(frame)), 3):
        features = []
        for i, j in combinations(triple, 2):
            feature600 = min(r600[i], r600[j]) if np.isfinite([r600[i], r600[j]]).all() else 0.0
            feature200 = min(r200[i], r200[j]) if np.isfinite([r200[i], r200[j]]).all() else 0.0
            features.append((front[i] * front[j], feature600, feature200))
        rows.append(np.mean(features, axis=0))
    return np.asarray(rows, dtype=float)


def reference_joint(scores: np.ndarray, set_temperature: float, order_temperature: float,
                    pair_x: np.ndarray | None = None, beta: np.ndarray | None = None):
    """Exhaustive reference distribution; deliberately does not call probability.py."""
    triples = list(combinations(range(len(scores)), 3))
    energies = []
    for index, triple in enumerate(triples):
        energy = float(np.sum(scores[list(triple)]) / set_temperature)
        if pair_x is not None and beta is not None:
            energy += float(np.dot(pair_x[index], beta))
        energies.append(energy)
    logits = np.asarray(energies, dtype=float)
    trio_probability = np.exp(logits - logsumexp(logits))
    utilities = scores / order_temperature
    orders, mass = [], []
    for triple, trio_p in zip(triples, trio_probability, strict=True):
        for order in permutations(triple):
            remaining = list(triple)
            conditional = 1.0
            for horse in order:
                conditional *= float(np.exp(utilities[horse] - logsumexp(utilities[remaining])))
                remaining.remove(horse)
            orders.append(order)
            mass.append(float(trio_p * conditional))
    return np.asarray(orders, dtype=np.int64), np.asarray(mass, dtype=float)


def reference_marginals(n: int, orders: np.ndarray, mass: np.ndarray) -> dict[str, np.ndarray]:
    win = np.zeros(n, dtype=float)
    top2 = np.zeros(n, dtype=float)
    top3 = np.zeros(n, dtype=float)
    quinella = np.zeros((n, n), dtype=float)
    qpl = np.zeros((n, n), dtype=float)
    for order, probability in zip(orders, mass, strict=True):
        first, second, third = map(int, order)
        win[first] += probability
        top2[first] += probability
        top2[second] += probability
        top3[[first, second, third]] += probability
        quinella[first, second] += probability
        quinella[second, first] += probability
        for i, j in ((first, second), (first, third), (second, third)):
            qpl[i, j] += probability
            qpl[j, i] += probability
    return {"win": win, "top2": top2, "top3": top3, "quinella": quinella, "qpl": qpl}


def reference_race(frame: pd.DataFrame, scores: np.ndarray, set_temperature: float,
                   order_temperature: float, pair_beta: np.ndarray,
                   active: np.ndarray | None = None):
    pair_x = reference_pair_features(frame) if len(pair_beta) and np.any(pair_beta) else None
    orders, mass = reference_joint(scores, set_temperature, order_temperature,
                                   pair_x, pair_beta if pair_x is not None else None)
    n = len(frame)
    if active is None:
        active = np.ones(n, dtype=bool)
    if not active.all():
        keep = active[orders].all(axis=1)
        mass = np.where(keep, mass, 0.0)
        mass = mass / mass.sum()
    m = reference_marginals(n, orders, mass)
    ii, jj = np.triu_indices(n, 1)
    eligible = active[ii] & active[jj]
    ii, jj = ii[eligible], jj[eligible]
    outcomes = frame["outcome"].to_numpy(dtype=int)
    podium = (outcomes >= 1) & (outcomes <= 3)
    top2_truth = (outcomes >= 1) & (outcomes <= 2)
    qnl = m["quinella"][ii, jj]
    qpl = m["qpl"][ii, jj]
    qnl_order = np.lexsort((frame.program_no.to_numpy()[jj],
                            frame.program_no.to_numpy()[ii], -np.round(qnl, 12)))[:3]
    qpl_order = np.lexsort((frame.program_no.to_numpy()[jj],
                            frame.program_no.to_numpy()[ii], -np.round(qpl, 12)))[:3]
    axis = int(np.argmax(np.round(m["top3"], 12)))
    qnl_union = float(qnl[qnl_order].sum())
    qpl_hits_order = np.zeros(len(orders), dtype=bool)
    for t in qpl_order:
        qpl_hits_order |= np.isin(orders, [ii[t]]).any(axis=1) & np.isin(orders, [jj[t]]).any(axis=1)
    qpl_union = float(mass[qpl_hits_order].sum())
    true_indices = np.asarray([np.flatnonzero(outcomes == rank)[0] for rank in (1, 2, 3)])
    set_mask = podium[orders].all(axis=1)
    order_mask = (orders == true_indices).all(axis=1)
    qnl_truth = (top2_truth[ii] & top2_truth[jj]).astype(int)
    qpl_truth = (podium[ii] & podium[jj]).astype(int)
    tickets = []
    for pool, selection, probabilities, truths in (
        ("quinella", qnl_order, qnl, qnl_truth),
        ("qpl", qpl_order, qpl, qpl_truth),
    ):
        for rank, t in enumerate(selection, start=1):
            tickets.append({
                "pool": pool, "rank": rank,
                "program_a": int(frame.program_no.iloc[ii[t]]),
                "program_b": int(frame.program_no.iloc[jj[t]]),
                "probability": float(probabilities[t]), "hit": int(truths[t]),
            })
    return {
        "orders": orders, "mass": mass, "marginals": m, "tickets": tickets,
        "axis": axis, "axis_hit": int(podium[axis]), "axis_probability": float(m["top3"][axis]),
        "qnl_one": int(qnl_truth[qnl_order[0]]), "qnl_three": int(qnl_truth[qnl_order].sum() > 0),
        "qpl_one": int(qpl_truth[qpl_order[0]]), "qpl_count": int(qpl_truth[qpl_order].sum()),
        "qpl_three": int(qpl_truth[qpl_order].sum() > 0),
        "qnl1_probability": float(qnl[qnl_order[0]]), "qnl3_probability": qnl_union,
        "qpl1_probability": float(qpl[qpl_order[0]]), "qpl3_probability": qpl_union,
        "qpl_expected_count": float(qpl[qpl_order].sum()),
        "runner_brier": float(np.mean((m["top3"][active] - podium[active]) ** 2)),
        "quinella_brier": float(np.mean((qnl - qnl_truth) ** 2)),
        "qpl_brier": float(np.mean((qpl - qpl_truth) ** 2)),
        "trio_logloss": float(-np.log(max(float(mass[set_mask].sum()), 1e-300))),
        "ordered_logloss": float(-np.log(max(float(mass[order_mask].sum()), 1e-300))),
    }


def assert_close(left, right, label: str, atol: float = 2e-9) -> float:
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    assert a.shape == b.shape, f"{label}: shape {a.shape} != {b.shape}"
    error = float(np.max(np.abs(a - b))) if a.size else 0.0
    assert np.allclose(a, b, rtol=1e-8, atol=atol), f"{label}: max absolute error {error}"
    return error


def verify_evaluation_outputs(frame: pd.DataFrame, contract: dict[str, list[str]], config: dict) -> dict:
    """Check all saved outcomes/tickets and exhaustively reconstruct selected races."""
    needed = [
        "evaluation_started.json", "evaluation_complete.json", "population_flags.parquet",
        "calibration_parameters.json", "race_metrics.parquet", "tickets.parquet",
        "runner_probabilities.parquet", "calibration_bins.csv", "metrics.csv",
        "paired_differences.csv", "implementation_repairs.json",
    ]
    missing = [name for name in needed if not (OUT / name).is_file()]
    assert not missing, f"evaluation outputs are not complete: {missing}"

    started = read_json(OUT / "evaluation_started.json")
    complete = read_json(OUT / "evaluation_complete.json")
    repair = read_json(OUT / "implementation_repairs.json")
    flags = pd.read_parquet(OUT / "population_flags.parquet")
    assert not flags.duplicated(KEY).any()
    assert flags[KEY + ["normal_finisher", "ambiguous_flag"]].notna().all().all()
    assert pd.api.types.is_bool_dtype(flags["normal_finisher"])
    assert pd.api.types.is_bool_dtype(flags["ambiguous_flag"])
    expected_frame = frame.loc[frame["year"].ge(2024)].copy()
    expected_keyset = set(map(tuple, expected_frame[KEY].to_numpy()))
    assert len(expected_keyset) == 50754
    assert expected_keyset == set(map(tuple, flags[KEY].to_numpy()))
    expected_frame = expected_frame.merge(flags[KEY + ["normal_finisher", "ambiguous_flag"]],
                                          on=KEY, how="left", validate="one_to_one")
    assert expected_frame["normal_finisher"].notna().all()
    assert expected_frame["ambiguous_flag"].notna().all()

    probability_hash = sha256(HERE / "probability.py")
    evaluation_hash = sha256(HERE / "evaluate.py")
    assert started["protocol_sha256"] == sha256(OUT / "protocol_frozen.json")
    assert started["evaluation_code_sha256"] == evaluation_hash
    assert started["probability_code_sha256"] == probability_hash
    assert started["population_flags_sha256"] == sha256(OUT / "population_flags.parquet")
    assert complete["evaluation_code_sha256"] == evaluation_hash
    assert complete["probability_code_sha256"] == probability_hash
    assert complete["evaluation_code_sha256"] == started["evaluation_code_sha256"]
    assert complete["probability_code_sha256"] == started["probability_code_sha256"]
    assert repair["no_model_or_calibration_changes"] is True
    assert repair["old_evaluate_sha256"] != evaluation_hash, \
        "documented tie repair was not used for the completed evaluation"
    assert repair["observed_no_pair_axis_mismatches"] == {
        "ability22": 8, "early47": 1, "late66": 7, "additive89": 0, "full103": 0,
    }
    assert float(repair["maximum_tie_numeric_difference"]) <= 1e-12

    # Each calibration parameter set must be unique and match one frozen fold.
    calibration_parameters = read_json(OUT / "calibration_parameters.json")
    expected_folds = {
        (variant, venue, year)
        for variant in config["variants"]
        for venue in config["venues"]
        for year in config["evaluation_years"]
    }
    assert len(calibration_parameters) == 36
    calibration_map = {}
    for parameters in calibration_parameters:
        key = (parameters["variant"], int(parameters["meet"]), int(parameters["evaluation_year"]))
        assert key not in calibration_map
        calibration_map[key] = parameters
        assert parameters["calibration_year"] == key[2] - 1
        assert parameters["config_sha256"] == sha256(HERE / "config.json")
        parent_variant = "full103" if key[0] == "full103_pair" else key[0]
        metadata_path = OUT / "models" / f"{parent_variant}_{key[1]}_{key[2]}" / "metadata.json"
        assert parameters["source_metadata_sha256"] == sha256(metadata_path)
        assert parameters["probability_code_sha256"] == probability_hash
        metadata = read_json(metadata_path)
        assert float(parameters["set_temperature"]) == float(metadata["temperature"])
        assert config["temperature_bounds"][0] <= parameters["order_temperature"] <= config["temperature_bounds"][1]
        beta = np.asarray(parameters["beta"], dtype=float)
        assert beta.shape == (3,) and np.isfinite(beta).all()
        assert np.max(np.abs(beta)) <= config["pair_bound"] + 1e-12
        assert parameters["optimizer"]["success"] is True
        if key[0] != "full103_pair":
            assert np.array_equal(beta, np.zeros(3))
        else:
            assert "iterations" in parameters["optimizer"]
            assert parameters["optimizer"]["iterations"] <= config["pair_maxiter"]
    assert set(calibration_map) == expected_folds

    metrics = pd.read_parquet(OUT / "race_metrics.parquet")
    tickets = pd.read_parquet(OUT / "tickets.parquet")
    runners = pd.read_parquet(OUT / "runner_probabilities.parquet")
    race_keys = sorted(expected_frame["race_key"].unique())
    assert len(race_keys) == 4799
    scopes = ["all_starters", "normal_finishers_conditioned"]
    variants = config["variants"]
    assert len(metrics) == len(scopes) * len(variants) * len(race_keys)
    assert not metrics.duplicated(["scope", "variant", "race_key"]).any()
    expected_metric_keys = {
        (scope, variant, race_key)
        for scope in scopes for variant in variants for race_key in race_keys
    }
    assert expected_metric_keys == set(map(tuple, metrics[["scope", "variant", "race_key"]].to_numpy()))
    assert len(runners) == len(variants) * len(expected_frame)
    assert not runners.duplicated(["variant", *KEY]).any()
    expected_runner_keys = {
        (variant, race_key, program_no, horse_id)
        for variant in variants
        for race_key, program_no, horse_id in expected_frame[KEY].itertuples(index=False, name=None)
    }
    assert expected_runner_keys == set(map(tuple, runners[["variant", *KEY]].to_numpy()))
    expected_outcomes = expected_frame.set_index(KEY).outcome.sort_index()
    saved_outcomes = runners.set_index(["variant", *KEY]).outcome
    for variant in variants:
        actual_outcomes = saved_outcomes.xs(variant, level="variant").sort_index()
        assert actual_outcomes.index.equals(expected_outcomes.index)
        assert np.array_equal(actual_outcomes.to_numpy(dtype=int), expected_outcomes.to_numpy(dtype=int)), \
            f"{variant}: runner outcomes differ from frozen source corpus"
    assert len(tickets) == len(variants) * len(race_keys) * 2 * 3
    assert not tickets.duplicated(["race_key", "variant", "pool", "rank"]).any()
    assert set(tickets["pool"].unique()) == {"quinella", "qpl"}
    ticket_counts = tickets.groupby(["race_key", "variant", "pool"], sort=False).size()
    assert ticket_counts.eq(3).all() and len(ticket_counts) == len(variants) * len(race_keys) * 2
    assert tickets["rank"].isin([1, 2, 3]).all()
    assert (tickets["program_a"] < tickets["program_b"]).all()
    assert tickets["probability"].between(0, 1).all()
    for _, group in tickets.sort_values(["race_key", "variant", "pool", "rank"]).groupby(
            ["race_key", "variant", "pool"], sort=False):
        actual_pairs = list(zip(group.program_a.astype(int), group.program_b.astype(int), strict=True))
        probability = group.probability.to_numpy(dtype=float)
        expected_order = sorted(range(len(group)), key=lambda i: (
            -float(np.round(probability[i], 12)), actual_pairs[i][0], actual_pairs[i][1]))
        assert expected_order == list(range(len(group))), \
            "ticket ranks do not follow rounded-probability descending/program-number tie policy"

    # Confirm outcome labels for every runner and independently recalculate ticket hits.
    outcome_lookup = runners[["race_key", "variant", "program_no", "outcome"]]
    left = tickets.merge(outcome_lookup, left_on=["race_key", "variant", "program_a"],
                         right_on=["race_key", "variant", "program_no"], validate="many_to_one")
    left = left.rename(columns={"outcome": "outcome_a"}).drop(columns="program_no")
    left = left.merge(outcome_lookup, left_on=["race_key", "variant", "program_b"],
                      right_on=["race_key", "variant", "program_no"], validate="many_to_one")
    left = left.rename(columns={"outcome": "outcome_b"}).drop(columns="program_no")
    expected_hit = np.where(left.pool.eq("quinella"),
                            left.outcome_a.isin([1, 2]) & left.outcome_b.isin([1, 2]),
                            left.outcome_a.isin([1, 2, 3]) & left.outcome_b.isin([1, 2, 3])).astype(int)
    assert np.array_equal(expected_hit, left.hit.to_numpy(dtype=int)), "ticket hit labels do not match raw outcomes"
    left["expected_hit"] = expected_hit
    hit_rows = left.pivot(index=["race_key", "variant"], columns=["pool", "rank"], values="expected_hit")
    all_metrics = metrics.loc[metrics.scope.eq("all_starters")].set_index(["race_key", "variant"]).sort_index()
    assert np.array_equal(hit_rows.loc[all_metrics.index, ("quinella", 1)].to_numpy(dtype=int),
                          all_metrics["quinella_one"].to_numpy(dtype=int))
    qnl_any = hit_rows.loc[all_metrics.index, [("quinella", 1), ("quinella", 2), ("quinella", 3)]].sum(axis=1)
    assert np.array_equal(qnl_any.gt(0).to_numpy(dtype=int), all_metrics["quinella_three"].to_numpy(dtype=int))
    assert np.array_equal(hit_rows.loc[all_metrics.index, ("qpl", 1)].to_numpy(dtype=int),
                          all_metrics["qpl_one"].to_numpy(dtype=int))
    qpl_count = hit_rows.loc[all_metrics.index, [("qpl", 1), ("qpl", 2), ("qpl", 3)]].sum(axis=1)
    assert np.array_equal(qpl_count.to_numpy(dtype=int), all_metrics["qpl_count"].to_numpy(dtype=int))
    assert np.array_equal(qpl_count.gt(0).to_numpy(dtype=int), all_metrics["qpl_three"].to_numpy(dtype=int))

    # Runner-level probability coherence and race metrics are checked on every saved row.
    runner_groups = runners.groupby(["race_key", "variant"], sort=False)
    runner_sums = runner_groups[["win", "top2", "top3"]].sum()
    assert np.allclose(runner_sums["win"], 1.0, atol=2e-9, rtol=0)
    assert np.allclose(runner_sums["top2"], 2.0, atol=2e-9, rtol=0)
    assert np.allclose(runner_sums["top3"], 3.0, atol=2e-9, rtol=0)
    assert np.isfinite(runners[["win", "top2", "top3"]].to_numpy(dtype=float)).all()
    assert runners[["win", "top2", "top3"]].ge(-1e-12).all().all()
    assert runners[["win", "top2", "top3"]].le(1 + 1e-12).all().all()
    assert (runners["win"] <= runners["top2"] + 1e-10).all()
    assert (runners["top2"] <= runners["top3"] + 1e-10).all()
    runner_check = runners.copy()
    runner_check["top3_truth"] = runner_check.outcome.isin([1, 2, 3]).astype(int)
    brier = runner_check.assign(sq=(runner_check.top3-runner_check.top3_truth)**2).groupby(
        ["race_key", "variant"], sort=False).sq.mean()
    saved_brier = all_metrics["runner_brier"].sort_index()
    assert_close(brier.reindex(saved_brier.index), saved_brier, "runner Brier from output marginals")
    runner_race = runners.sort_values(["race_key", "variant", "program_no"], kind="stable").groupby(
        ["race_key", "variant"], sort=False)
    axis_rows = []
    for (race_key, variant), group in runner_race:
        # The frozen implementation repair defines a 1e-12 probability tie,
        # with stable program-number ordering inside that tie.
        ix = int(np.argmax(np.round(group.top3.to_numpy(dtype=float), 12)))
        row = group.iloc[ix]
        axis_rows.append((race_key, variant, int(row.program_no), int(row.outcome in [1, 2, 3]), float(row.top3)))
    axes = pd.DataFrame(axis_rows, columns=["race_key", "variant", "axis_program_no", "axis_top3", "axis_probability"])
    axes = axes.set_index(["race_key", "variant"]).sort_index()
    assert np.array_equal(axes.loc[all_metrics.index, "axis_program_no"].to_numpy(dtype=int),
                          all_metrics.axis_program_no.to_numpy(dtype=int))
    assert np.array_equal(axes.loc[all_metrics.index, "axis_top3"].to_numpy(dtype=int),
                          all_metrics.axis_top3.to_numpy(dtype=int))
    assert_close(axes.loc[all_metrics.index, "axis_probability"], all_metrics.axis_probability,
                 "axis probability from runner output")

    # The archived full103 values are its original raw scores and set-softmax Top3 marginals.
    old = pd.read_parquet(SOURCE / "runner_predictions.parquet")
    old = old.loc[old.variant.eq("full103")].copy()
    assert len(old) == 50754 and not old.duplicated(KEY).any()
    old = old.merge(expected_frame[KEY + ["row_number", "meet", "race_date", "year"]],
                    on=KEY, how="left", validate="one_to_one", suffixes=("", "_features"))
    assert old["row_number"].notna().all()
    assert old.meet.eq(old.meet_features).all()
    assert old.race_date.eq(old.race_date_features.astype(str)).all()
    assert old.year.eq(old.year_features).all()
    full_scores = {}
    for venue in config["venues"]:
        for year in config["evaluation_years"]:
            path = OUT / "models" / f"full103_{venue}_{year}" / "scores.parquet"
            scores = pd.read_parquet(path)
            scores = scores.loc[scores.phase.eq("evaluation")].set_index("row_number").score
            full_scores.update(scores.to_dict())
    stored_raw = np.asarray([full_scores[int(row)] for row in old.row_number], dtype=float)
    assert_close(stored_raw, old.raw_score.to_numpy(dtype=float), "cached full103 raw scores", atol=1e-7)
    cached_top3 = np.zeros(len(old), dtype=float)
    for _, indices in old.groupby("race_key", sort=False).indices.items():
        group = old.iloc[indices]
        venue, year = int(group.meet.iloc[0]), int(group.year.iloc[0])
        source_meta_path, _ = source_model("full103", venue, year)
        temperature = float(read_json(source_meta_path / "metadata.json")["temperature"])
        scores = group.raw_score.to_numpy(dtype=float)
        triples = list(combinations(range(len(group)), 3))
        energies = np.asarray([sum(scores[list(t)]) / temperature for t in triples], dtype=float)
        q = np.exp(energies - logsumexp(energies))
        marginal = np.zeros(len(group), dtype=float)
        for trio, probability in zip(triples, q, strict=True):
            marginal[list(trio)] += probability
        cached_top3[indices] = marginal
    cached_error = assert_close(cached_top3, old.target_probability.to_numpy(dtype=float),
                                "original cached full103 Top3 probabilities", atol=2e-9)
    runner_full = runners.loc[runners.variant.eq("full103")].merge(
        expected_frame[KEY + ["row_number"]], on=KEY, how="left", validate="one_to_one")
    runner_full = runner_full.set_index("row_number").loc[old.row_number.to_numpy()]
    full_error = assert_close(runner_full.top3.to_numpy(dtype=float), cached_top3,
                              "joint full103 Top3 against original cache", atol=2e-9)

    # Rebuild the incumbent's axis + next-three raw-score quinella policy for all races.
    legacy_expected = []
    for race_key, group in old.groupby("race_key", sort=False):
        ranked = group.sort_values(["raw_score", "program_no"], ascending=[False, True], kind="stable")
        top2 = ranked.outcome.isin([1, 2]).to_numpy(dtype=bool)
        pair_hits = [bool(top2[0] and top2[k]) for k in (1, 2, 3) if len(top2) > k]
        legacy_expected.append((race_key, int(pair_hits[0]), int(any(pair_hits))))
    legacy = pd.DataFrame(legacy_expected, columns=["race_key", "legacy_quinella_one", "legacy_quinella_three"])
    full_legacy = all_metrics.loc[all_metrics.index.get_level_values("variant") == "full103"]
    legacy = legacy.set_index("race_key").loc[full_legacy.index.get_level_values("race_key")]
    assert np.array_equal(legacy.legacy_quinella_one.to_numpy(dtype=int),
                          full_legacy.legacy_quinella_one.to_numpy(dtype=int))
    assert np.array_equal(legacy.legacy_quinella_three.to_numpy(dtype=int),
                          full_legacy.legacy_quinella_three.to_numpy(dtype=int))

    # For beta=0, trio inclusion probability is monotone in raw score. Exact
    # raw-score ties therefore must follow the protocol's program-number tie
    # rule; summation roundoff must not pick another horse. Check both scopes.
    score_axis_diagnostics = {}
    for variant in [name for name in variants if name != "full103_pair"]:
        score_parts = []
        for venue in config["venues"]:
            for year in config["evaluation_years"]:
                path = OUT / "models" / f"{variant}_{venue}_{year}" / "scores.parquet"
                phase_scores = pd.read_parquet(path)
                score_parts.append(phase_scores.loc[phase_scores.phase.eq("evaluation"),
                                                    ["row_number", "score"]])
        raw = pd.concat(score_parts, ignore_index=True)
        raw = raw.merge(expected_frame[KEY + ["row_number", "normal_finisher"]],
                        on="row_number", how="left", validate="one_to_one")
        assert raw[KEY].notna().all().all() and raw["normal_finisher"].notna().all()
        for scope, eligible in (("all_starters", raw),
                                ("normal_finishers_conditioned", raw.loc[raw.normal_finisher])):
            expected_ties = {}
            exact_ties = 0
            for race_key, group in eligible.groupby("race_key", sort=False):
                highest = group.score.max()
                tied = group.loc[group.score.eq(highest)]
                exact_ties += int(len(tied) > 1)
                if len(tied) > 1:
                    expected_ties[race_key] = int(tied.program_no.min())
            saved_axis = metrics.loc[metrics.variant.eq(variant) & metrics.scope.eq(scope)] \
                .set_index("race_key").axis_program_no.sort_index().astype(int)
            mismatch = pd.Series({race_key: int(saved_axis.loc[race_key]) != expected_program
                                  for race_key, expected_program in expected_ties.items()}, dtype=bool)
            if mismatch.any():
                examples = mismatch[mismatch].index.astype(str).tolist()[:12]
                raise AssertionError(
                    f"{variant}/{scope}: exact raw-score tie does not choose lowest program number in "
                    f"{int(mismatch.sum())} races; examples={examples}"
                )
            score_axis_diagnostics[f"{variant}/{scope}"] = {
                "exact_raw_score_tie_races": exact_ties,
                "exact_tie_program_order_mismatches": 0,
            }

    # Independently enumerate all ordered triples for three deterministic races per fold.
    sample_frame = expected_frame.sort_values(["meet", "year", "race_date", "race_key", "program_no"])
    sample_races = sample_frame[["race_key", "meet", "year", "race_date"]].drop_duplicates()
    sample_keys = []
    for (_, _), group in sample_races.groupby(["meet", "year"], sort=True):
        for loc in sorted(set([0, len(group)//2, len(group)-1])):
            sample_keys.append(str(group.iloc[loc].race_key))
    max_reference_error = 0.0
    max_probability_sum_error = 0.0
    for race_key in sample_keys:
        race = expected_frame.loc[expected_frame.race_key.eq(race_key)].sort_values("program_no").reset_index(drop=True)
        flags_race = race[["normal_finisher", "ambiguous_flag"]]
        venue, year = int(race.meet.iloc[0]), int(race.year.iloc[0])
        for variant in variants:
            parameter = calibration_map[(variant, venue, year)]
            parent_variant = "full103" if variant == "full103_pair" else variant
            score_path = OUT / "models" / f"{parent_variant}_{venue}_{year}" / "scores.parquet"
            phase_scores = pd.read_parquet(score_path)
            row_numbers = race.row_number.to_numpy(dtype=int)
            score_map = phase_scores.loc[phase_scores.phase.eq("evaluation")].set_index("row_number").score
            scores = score_map.loc[row_numbers].to_numpy(dtype=float)
            beta = np.asarray(parameter["beta"], dtype=float)
            reference = reference_race(race, scores, float(parameter["set_temperature"]),
                                       float(parameter["order_temperature"]), beta)
            m = reference["marginals"]
            sums = [abs(reference["mass"].sum()-1), abs(m["win"].sum()-1),
                    abs(m["top2"].sum()-2), abs(m["top3"].sum()-3),
                    abs(m["quinella"].sum()/2-1), abs(m["qpl"].sum()/2-3)]
            max_probability_sum_error = max(max_probability_sum_error, max(sums))
            assert max(sums) < 2e-9
            saved_runners = runners.loc[(runners.race_key.eq(race_key)) & runners.variant.eq(variant)].sort_values("program_no")
            max_reference_error = max(max_reference_error,
                assert_close(saved_runners.win, m["win"], f"sample {race_key}/{variant} win"),
                assert_close(saved_runners.top2, m["top2"], f"sample {race_key}/{variant} top2"),
                assert_close(saved_runners.top3, m["top3"], f"sample {race_key}/{variant} top3"))
            for scope, active in (("all_starters", np.ones(len(race), dtype=bool)),
                                  ("normal_finishers_conditioned", race.normal_finisher.to_numpy(dtype=bool))):
                expected_scope = reference if active.all() else reference_race(
                    race, scores, float(parameter["set_temperature"]),
                    float(parameter["order_temperature"]), beta, active=active)
                metric = metrics.loc[(metrics.race_key.eq(race_key)) & metrics.variant.eq(variant)
                                     & metrics.scope.eq(scope)].iloc[0]
                for col, refkey in (("axis_top3", "axis_hit"), ("quinella_one", "qnl_one"),
                    ("quinella_three", "qnl_three"), ("qpl_one", "qpl_one"),
                    ("qpl_three", "qpl_three"), ("qpl_count", "qpl_count")):
                    assert int(metric[col]) == int(expected_scope[refkey]), f"sample {race_key}/{variant}/{scope}/{col}"
                for col, refkey in (("axis_probability", "axis_probability"),
                    ("qnl1_probability", "qnl1_probability"), ("qnl3_probability", "qnl3_probability"),
                    ("qpl1_probability", "qpl1_probability"), ("qpl3_probability", "qpl3_probability"),
                    ("qpl_expected_count", "qpl_expected_count"), ("runner_brier", "runner_brier"),
                    ("quinella_brier", "quinella_brier"), ("qpl_brier", "qpl_brier"),
                    ("trio_logloss", "trio_logloss"), ("ordered_logloss", "ordered_logloss")):
                    max_reference_error = max(max_reference_error,
                        assert_close([metric[col]], [expected_scope[refkey]], f"sample {race_key}/{variant}/{scope}/{col}"))
                if scope == "all_starters":
                    saved_tickets = tickets.loc[tickets.race_key.eq(race_key) & tickets.variant.eq(variant)]
                    expected_tickets = pd.DataFrame(expected_scope["tickets"])
                    actual_sorted = saved_tickets.sort_values(["pool", "rank"])
                    expected_sorted = expected_tickets.sort_values(["pool", "rank"])
                    assert actual_sorted[["pool", "rank", "program_a", "program_b"]].reset_index(drop=True).equals(
                        expected_sorted[["pool", "rank", "program_a", "program_b"]].reset_index(drop=True))
                    max_reference_error = max(max_reference_error,
                        assert_close(actual_sorted.probability, expected_sorted.probability, f"sample {race_key}/{variant} ticket probabilities"))
                    assert np.array_equal(actual_sorted.hit.to_numpy(dtype=int), expected_sorted.hit.to_numpy(dtype=int))

    # Validate race-weighted summaries and the direct zero/one/two/three ticket-count distribution.
    summary = pd.read_csv(OUT / "metrics.csv")
    assert not summary.duplicated(["scope", "variant", "dimension", "level"]).any()
    for (scope, variant), group in metrics.groupby(["scope", "variant"], sort=False):
        row = summary.loc[summary.scope.eq(scope) & summary.variant.eq(variant)
                          & summary.dimension.eq("overall") & summary.level.eq("all")]
        assert len(row) == 1
        row = row.iloc[0]
        assert int(row.races) == len(group)
        for column in ["axis_top3", "quinella_one", "quinella_three", "qpl_one", "qpl_three", "qpl_count",
                       "runner_brier", "quinella_brier", "qpl_brier", "trio_logloss", "axis_brier",
                       "qnl1_brier", "qnl3_brier", "qpl1_brier", "qpl3_brier",
                       "legacy_quinella_one", "legacy_quinella_three"]:
            assert_close([row[column]], [group[column].mean()], f"summary {scope}/{variant}/{column}")
        for count in range(4):
            assert int(row[f"qpl_count_{count}_races"]) == int(group.qpl_count.eq(count).sum())
        assert int(row.qpl_hits_total) == int(group.qpl_count.sum())
        for column, source_column in (
            ("axis_top3_hits", "axis_top3"), ("quinella_one_hits", "quinella_one"),
            ("quinella_three_hits", "quinella_three"), ("qpl_one_hits", "qpl_one"),
            ("qpl_three_hits", "qpl_three"),
        ):
            assert int(row[column]) == int(group[source_column].sum()), \
                f"summary hit count {scope}/{variant}/{column}"

    distribution = {}
    allstar_ticket_hits = left.loc[left.pool.eq("qpl")].groupby(["race_key", "variant"]).expected_hit.sum()
    for variant in variants:
        values = allstar_ticket_hits.xs(variant, level="variant").value_counts().to_dict()
        counts = {str(count): int(values.get(count, 0)) for count in range(4)}
        assert sum(counts.values()) == len(race_keys)
        distribution[variant] = counts

    # Point estimates in paired_differences must be the exact paired race-level differences.
    paired = pd.read_csv(OUT / "paired_differences.csv")
    assert len(paired) == 2 * 6 * 10 * 15
    assert not paired.duplicated(["scope", "period", "candidate", "baseline", "metric"]).any()
    metric_names = ["axis_top3", "quinella_one", "quinella_three", "qpl_one", "qpl_three", "qpl_count",
                    "runner_brier", "quinella_brier", "qpl_brier", "trio_logloss",
                    "axis_brier", "qnl1_brier", "qnl3_brier", "qpl1_brier", "qpl3_brier"]
    comparisons = [("early47", "ability22"), ("late66", "ability22"), ("additive89", "early47"),
                   ("additive89", "late66"), ("full103", "additive89"),
                   ("full103_pair", "full103"), ("ability22", "full103"),
                   ("early47", "full103"), ("late66", "full103"), ("additive89", "full103")]
    assert set(paired.metric.unique()) == set(metric_names)
    for _, row in paired.iterrows():
        subset = metrics.loc[metrics.scope.eq(row.scope)]
        if row.period != "all":
            if str(row.period).startswith("venue"):
                subset = subset.loc[subset.meet.eq(int(str(row.period)[5:]))]
            else:
                subset = subset.loc[subset.year.eq(int(row.period))]
        candidate, baseline = str(row.candidate), str(row.baseline)
        candidate_values = subset.loc[subset.variant.eq(candidate)].set_index("race_key")[row.metric].sort_index()
        baseline_values = subset.loc[subset.variant.eq(baseline)].set_index("race_key")[row.metric].sort_index()
        assert candidate_values.index.equals(baseline_values.index)
        candidate_mean, baseline_mean = float(candidate_values.mean()), float(baseline_values.mean())
        assert_close([row.candidate_mean, row.baseline_mean, row.difference],
                     [candidate_mean, baseline_mean, candidate_mean-baseline_mean],
                     f"paired point difference {row.scope}/{row.period}/{candidate}/{row.metric}")
        assert int(row.races) == len(candidate_values)
        assert (candidate, baseline) in comparisons

    assert complete["race_rows"] == len(metrics)
    assert complete["runner_rows"] == len(runners)
    assert complete["ticket_rows"] == len(tickets)
    assert abs(float(complete["max_coherence_error"]) - float(metrics.coherence_max_error.max())) < 2e-9
    return {
        "evaluation_hashes_match_started_marker": True,
        "documented_ranking_only_repair_used_without_model_or_calibration_changes": True,
        "population_flags_null_free_and_exact_eval_keyset": True,
        "calibration_parameter_folds": len(calibration_parameters),
        "race_metric_rows": len(metrics),
        "runner_probability_rows": len(runners),
        "ticket_rows": len(tickets),
        "same_race_and_runner_keysets_across_all_variants": True,
        "ticket_hits_recomputed_for_every_saved_ticket": True,
        "ticket_counts_per_race_pool": 3,
        "qpl_ticket_hit_count_distribution": distribution,
        "runner_probability_sums_checked_for_every_race": True,
        "axis_and_runner_brier_checked_for_every_race": True,
        "no_pair_axis_matches_stable_raw_score_max_for_both_scopes": score_axis_diagnostics,
        "legacy_full103_hits_reproduced_for_all_races": True,
        "full103_all_starters_axis_hits": int(full_legacy.axis_top3.sum()),
        "original_cached_full103_top3_max_abs_error": cached_error,
        "joint_full103_top3_vs_original_cache_max_abs_error": full_error,
        "exhaustive_sample_races": len(sample_keys),
        "exhaustive_variant_race_checks": len(sample_keys) * len(variants),
        "max_exhaustive_probability_or_metric_error": max_reference_error,
        "max_exhaustive_probability_sum_error": max_probability_sum_error,
        "summary_means_and_0_1_2_3_counts_recomputed": True,
        "paired_point_differences_recomputed": len(paired),
    }


def main() -> int:
    config = read_json(HERE / "config.json")
    contracts = expected_contracts()
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "frozen input, model-score, and saved evaluation-output verification",
        "prediction_storage": "none; Booster.predict results were compared in memory",
        "checks": {},
        "limitations": [
            "This verifier does not train, inspect training logs, or independently reproduce early-stopping iteration selection.",
            "Training logs are unavailable, so early-stopping iteration selection is metadata-only, not independently retrained.",
        ],
    }
    report["checks"]["frozen_inputs"] = verify_frozen_inputs()
    report["checks"]["feature_contracts"] = verify_feature_contracts()
    corpus = load_corpus(contracts)
    report["checks"]["corpus"] = {
        "source_rows": len(corpus),
        "unique_runner_keys": int(corpus[KEY].drop_duplicates().shape[0]),
        "venues": sorted(int(x) for x in corpus["meet"].unique()),
        "years": [int(corpus["year"].min()), int(corpus["year"].max())],
        "race_count": int(corpus["race_key"].nunique()),
        "future_source_dates": 0,
        "all_races_have_unique_first_second_third": True,
        "all_races_match_field_size": True,
    }
    report["checks"]["models_and_scores"] = verify_models_and_scores(
        corpus, contracts, config,
        report["checks"]["frozen_inputs"]["input_fingerprint"],
        report["checks"]["frozen_inputs"]["training_code_sha256"],
    )
    report["checks"]["evaluation_outputs"] = verify_evaluation_outputs(corpus, contracts, config)
    report["status"] = "passed"
    report_path = OUT / "verification.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(f"Verification passed: {len(report['checks']['models_and_scores']['model_folds'])} folds")
    print(f"Maximum absolute saved-score difference: {report['checks']['models_and_scores']['max_absolute_score_error']:.3g}")
    print(f"Evaluation outputs verified: {report['checks']['evaluation_outputs']['race_metric_rows']} race metric rows")
    print(f"Wrote {report_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

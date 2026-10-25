"""Independent, read-only checks for the finish-history ablation outputs.

This reviewer deliberately does not import the candidate implementation. It
rebuilds the six proposed fields from the frozen R1 features and source
snapshot, reloads stored LightGBM models, and recalculates probabilities,
rankings, tickets, losses, and date-cluster intervals. The script writes its
verification receipt only into this review folder.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import ast
from pathlib import Path, PurePosixPath

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp


ROOT = Path(__file__).resolve().parents[3]
REVIEW = Path(__file__).resolve().parent
STUDY = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
R1 = ROOT / "jeju/research/20261009_field_relative_ability_v1"
BASELINE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1"
OPS = ROOT / "jeju/research/20261009_operating_model_comparison_v1"
SOURCE = BASELINE / "outputs_v2/source_snapshot.parquet"
BASE_FEATURES = R1 / "outputs/features.parquet"

EVAL_YEARS = (2024, 2025, 2026)
VARIANTS = ("R1", "F1", "F2")
BOOTSTRAP_SEED = 20261008
BOOTSTRAP_REPS = 2000
ATOL = 2e-10
RACE_METRICS = ["log_loss", "brier", "trio_nll", "top3_capture", "top4_capture",
                "top5_capture", "top6_capture", "top5_all3", "six_combo_hit"]
RUNNER_METRICS = ["log_loss", "brier"]
COMPARISONS = [("F1", "R1"), ("F2", "F1"), ("F2", "R1")]
INTEGRATION_COMPLETE = True


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_root_path(raw: str) -> Path:
    """Resolve a lock path while refusing absolute and parent-traversal paths."""
    rel = PurePosixPath(raw)
    require(not rel.is_absolute() and ".." not in rel.parts, f"unsafe lock path: {raw}")
    resolved = (ROOT / Path(*rel.parts)).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise AssertionError(f"lock path escapes workspace: {raw}") from exc
    return resolved


def is_null(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        result = pd.isna(value)
        return bool(result) if np.ndim(result) == 0 else False
    except (TypeError, ValueError):
        return False


def ids_list(value: object) -> list[int]:
    if is_null(value):
        return []
    if isinstance(value, np.ndarray):
        value = value.tolist()
    require(isinstance(value, (list, tuple)), f"expected source ID list, got {type(value).__name__}")
    return [int(x) for x in value if not is_null(x)]


def close(actual: object, expected: object, label: str, atol: float = ATOL) -> None:
    a = np.asarray(actual, dtype=float)
    e = np.asarray(expected, dtype=float)
    require(a.shape == e.shape, f"{label}: shape {a.shape} != {e.shape}")
    require(np.allclose(a, e, rtol=0.0, atol=atol, equal_nan=True), f"{label}: mismatch")


def load_source_and_features() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    source = pd.read_parquet(SOURCE)
    base = pd.read_parquet(BASE_FEATURES)
    candidate = pd.read_parquet(STUDY / "outputs/features.parquet")
    required_source = {"api_record_id", "race_id", "race_date", "horse_id", "race_distance_m", "finish_position", "started"}
    require(required_source.issubset(source.columns), "source snapshot schema changed")
    require(source.api_record_id.is_unique, "source API record ID is not unique")
    require(not source.duplicated(["race_id", "horse_id"]).any(), "duplicate horse within source race")
    require(len(base) == len(candidate) == 52155, "feature row count differs from frozen R1 cohort")
    require(base.api_record_id.tolist() == candidate.api_record_id.tolist(), "candidate changed frozen row order")
    require(base.race_id.tolist() == candidate.race_id.tolist(), "candidate changed frozen race rows")
    require(base.horse_id.astype(str).tolist() == candidate.horse_id.astype(str).tolist(), "candidate changed horse IDs")
    for col in base.columns:
        require(col in candidate.columns, f"missing inherited R1 column {col}")
    pd.testing.assert_frame_equal(candidate[base.columns], base, check_exact=True, check_dtype=True)
    return source, base, candidate


def event_index(source: pd.DataFrame) -> tuple[dict[str, dict[str, object]], dict[int, dict[str, object]]]:
    """Build actual-starter counts, conservative whole-race status and row lookup."""
    row_by_id: dict[int, dict[str, object]] = {}
    stats: dict[str, dict[str, object]] = {}
    for row in source.to_dict("records"):
        row_by_id[int(row["api_record_id"])] = row
    for race_id, group in source.groupby("race_id", sort=False, dropna=False):
        starters = group[group.started.fillna(False).astype(bool)]
        n_started = len(starters)
        raw = pd.to_numeric(starters.finish_position, errors="coerce")
        ranks = [int(x) for x in raw.dropna() if float(x).is_integer() and 1 <= x <= 89]
        complete = (
            n_started >= 2
            and len(ranks) == n_started
            and sorted(ranks) == list(range(1, n_started + 1))
            and starters.horse_id.notna().all()
            and starters.horse_id.nunique() == n_started
        )
        stats[str(race_id)] = {
            "n_started": n_started,
            "complete": bool(complete),
            "starter_ids": set(starters.api_record_id.astype(int)),
        }
    return stats, row_by_id


def rank_value(row: dict[str, object], n_started: int) -> int | None:
    value = pd.to_numeric(pd.Series([row.get("finish_position")]), errors="coerce").iloc[0]
    if pd.isna(value) or not float(value).is_integer():
        return None
    rank = int(value)
    if not (1 <= rank <= 89 and rank <= n_started):
        return None
    return rank


def recompute_history_features(
    base: pd.DataFrame,
    candidate: pd.DataFrame,
    stats: dict[str, dict[str, object]],
    row_by_id: dict[int, dict[str, object]],
) -> dict[str, int]:
    """Rebuild F1/F2 fields without calling the candidate's feature builder."""
    required = {
        "previous_start_id", "last5_same_source_ids", "history_cutoff", "distance_m",
        "previous_finish_relative_rank", "previous_top3", "previous_result_status",
        "same_distance_last5_top3_rate", "same_distance_last5_actual_n", "same_distance_last5_normal_n",
    }
    require(required.issubset(candidate.columns), f"candidate feature columns missing: {sorted(required - set(candidate.columns))}")
    actual_n = candidate.same_distance_last5_actual_n.to_numpy(float)
    normal_n = candidate.same_distance_last5_normal_n.to_numpy(float)
    top3_rate = candidate.same_distance_last5_top3_rate.to_numpy(float)
    previous_top3 = candidate.previous_top3.to_numpy(float)
    previous_rank = candidate.previous_finish_relative_rank.to_numpy(float)
    status = candidate.previous_result_status.astype(object).tolist()
    source_index = row_by_id
    checked = {"rows": 0, "f1_unobserved": 0, "f1_incomplete": 0, "f2_slots": 0, "f2_normal": 0}

    for i, row in enumerate(candidate.to_dict("records")):
        pid = None if is_null(row["previous_start_id"]) else int(row["previous_start_id"])
        if pid is None:
            exp_rank = np.nan
            exp_top3 = np.nan
            exp_status = "unobserved"
            checked["f1_unobserved"] += 1
        else:
            require(pid in source_index, f"previous start missing from source snapshot: {pid}")
            prior = source_index[pid]
            require(str(prior["horse_id"]) == str(row["horse_id"]), f"previous start horse mismatch at row {i}")
            require(str(prior["race_date"]) <= str(row["history_cutoff"]), f"previous start violates T-2 at row {i}")
            require(bool(prior["started"]), f"previous start is not a started source row at row {i}")
            e = stats[str(prior["race_id"])]
            rank = rank_value(prior, int(e["n_started"]))
            exp_top3 = float(rank <= 3) if rank is not None else np.nan
            exp_status = "normal" if e["complete"] else "non_normal_or_incomplete"
            exp_rank = (rank - 1) / (int(e["n_started"]) - 1) if e["complete"] and rank is not None else np.nan
            checked["f1_incomplete"] += int(not e["complete"])
        close([previous_rank[i]], [exp_rank], f"previous relative rank row {i}")
        close([previous_top3[i]], [exp_top3], f"previous Top3 row {i}")
        require(str(status[i]) == exp_status, f"previous status row {i}: {status[i]} != {exp_status}")

        ids = ids_list(row["last5_same_source_ids"])
        require(len(ids) <= 5, f"more than five same-distance actual starts at row {i}")
        known_ranks: list[int] = []
        for sid in ids:
            checked["f2_slots"] += 1
            require(sid in source_index, f"same-distance history missing from source snapshot: {sid}")
            prior = source_index[sid]
            require(str(prior["horse_id"]) == str(row["horse_id"]), f"same-distance history horse mismatch at row {i}")
            require(bool(prior["started"]), f"same-distance history includes non-starter at row {i}")
            require(prior["race_distance_m"] == row["distance_m"], f"same-distance history distance mismatch at row {i}")
            require(str(prior["race_date"]) <= str(row["history_cutoff"]), f"same-distance history violates T-2 at row {i}")
            rank = rank_value(prior, int(stats[str(prior["race_id"])]["n_started"]))
            if rank is not None:
                known_ranks.append(rank)
                checked["f2_normal"] += 1
        exp_actual = len(ids)
        exp_normal = len(known_ranks)
        exp_rate = float(np.mean(np.asarray(known_ranks) <= 3)) if known_ranks else np.nan
        close([actual_n[i]], [exp_actual], f"same-distance actual_n row {i}")
        close([normal_n[i]], [exp_normal], f"same-distance normal_n row {i}")
        close([top3_rate[i]], [exp_rate], f"same-distance Top3 rate row {i}")
        checked["rows"] += 1
    return checked


def triple_rows(frame: pd.DataFrame, score: np.ndarray) -> list[tuple[str, np.ndarray, np.ndarray, int]]:
    result = []
    for race_id, positions in frame.groupby("race_id", sort=False).indices.items():
        idx = np.asarray(positions, dtype=int)
        truth = np.flatnonzero(frame.iloc[idx].finish_position.to_numpy(int) <= 3)
        require(len(truth) == 3, f"race {race_id} does not have exactly three Top3 labels")
        combos = np.asarray(list(itertools.combinations(range(len(idx)), 3)), dtype=int)
        target = np.flatnonzero((combos == truth).all(axis=1))
        require(len(target) == 1, f"race {race_id} actual Top3 combo is not unique")
        terms = np.sort(score[idx][combos], axis=1)
        energies = (terms[:, 0] + terms[:, 1]) + terms[:, 2]
        result.append((str(race_id), idx, energies, int(target[0])))
    return result


def temperature(frame: pd.DataFrame, scores: np.ndarray) -> float:
    rows = triple_rows(frame.reset_index(drop=True), scores)
    width = max(len(energies) for _, _, energies, _ in rows)
    energy = np.full((len(rows), width), -np.inf)
    truth = np.empty(len(rows), dtype=float)
    for i, (_, _, energies, target) in enumerate(rows):
        energy[i, :len(energies)] = energies
        truth[i] = energies[target]
    result = minimize_scalar(
        lambda tau: float(np.mean(logsumexp(energy / tau, axis=1) - truth / tau)),
        bounds=(0.35, 4.0), method="bounded",
    )
    require(result.success, "temperature optimization failed")
    return float(result.x)


def evaluate_races(frame: pd.DataFrame, scores: np.ndarray, tau: float, variant: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    race_rows = []
    runner_rows = []
    ticket_rows = []
    for race_id, idx, energies, target in triple_rows(frame.reset_index(drop=True), scores):
        one = frame.iloc[idx]
        combos = np.asarray(list(itertools.combinations(range(len(idx)), 3)), dtype=int)
        logq = energies / tau - logsumexp(energies / tau)
        q = np.exp(logq)
        marginal = np.zeros(len(idx), dtype=float)
        for j, triple in enumerate(combos):
            marginal[triple] += q[j]
        require(np.isclose(q.sum(), 1.0, atol=1e-12, rtol=0), f"{race_id} combo mass")
        require(np.isclose(marginal.sum(), 3.0, atol=1e-10, rtol=0), f"{race_id} Top3 marginal mass")
        y = (one.finish_position.to_numpy(int) <= 3).astype(float)
        clipped = np.clip(marginal, 1e-12, 1 - 1e-12)
        row_ll = -y * np.log(clipped) - (1 - y) * np.log1p(-clipped)
        row_brier = (marginal - y) ** 2
        order = np.argsort(-scores[idx], kind="stable")
        ticket_order = np.argsort(-energies, kind="stable")[:6]
        true_set = set(np.flatnonzero(y))
        race = {"race_id": race_id, "race_date": one.race_date.iloc[0], "year": int(one.year.iloc[0]), "variant": variant,
                "log_loss": float(row_ll.mean()), "brier": float(row_brier.mean()),
                "trio_nll": float(-logq[target]), "six_combo_hit": int(target in ticket_order),
                "six_combo_mass": float(q[ticket_order].sum())}
        for k in (3, 4, 5, 6):
            chosen = set(order[:k])
            race[f"top{k}_capture"] = len(true_set & chosen) / 3
            race[f"top{k}_all3"] = int(true_set <= chosen)
        race_rows.append(race)
        for j, row in enumerate(one.to_dict("records")):
            runner_rows.append({"api_record_id": int(row["api_record_id"]), "race_id": race_id,
                                "race_date": row["race_date"], "year": int(row["year"]),
                                "horse_id": str(row["horse_id"]), "horse_number": int(row["horse_number"]),
                                "variant": variant, "score": float(scores[idx[j]]),
                                "p_top3": float(marginal[j]), "y": int(y[j]),
                                "log_loss": float(row_ll[j]), "brier": float(row_brier[j])})
        for rank, j in enumerate(ticket_order, start=1):
            numbers = sorted(int(one.horse_number.iloc[k]) for k in combos[j])
            ticket_rows.append({"race_id": race_id, "variant": variant, "selection_rank": rank,
                                "numbers": ",".join(map(str, numbers)), "probability": float(q[j]),
                                "hit": int(j == target)})
    races = pd.DataFrame(race_rows)
    runners = pd.DataFrame(runner_rows)
    tickets = pd.DataFrame(ticket_rows)
    return races, runners, tickets, pd.DataFrame()


def date_bootstrap(a: pd.DataFrame, b: pd.DataFrame, metric: str) -> dict[str, float]:
    paired = a[["race_id", "race_date", metric]].merge(
        b[["race_id", metric]], on="race_id", suffixes=("", "_base"), validate="one_to_one"
    )
    require(len(paired) == len(a) == len(b), f"paired race coverage for {metric}")
    paired["delta"] = paired[metric] - paired[f"{metric}_base"]
    clusters = paired.groupby("race_date").delta.agg(["sum", "size"])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    index = rng.integers(0, len(clusters), size=(BOOTSTRAP_REPS, len(clusters)))
    values = clusters["sum"].to_numpy()[index].sum(axis=1) / clusters["size"].to_numpy()[index].sum(axis=1)
    return {"delta": float(paired.delta.mean()), "lo": float(np.quantile(values, 0.025)),
            "hi": float(np.quantile(values, 0.975)), "races": int(len(paired)), "days": int(len(clusters))}


def runner_bootstrap(a: pd.DataFrame, b: pd.DataFrame, metric: str) -> dict[str, float]:
    paired = a[["api_record_id", "race_date", metric]].merge(
        b[["api_record_id", metric]], on="api_record_id", suffixes=("", "_base"), validate="one_to_one"
    )
    require(len(paired) == len(a) == len(b), f"paired runner coverage for {metric}")
    paired["delta"] = paired[metric] - paired[f"{metric}_base"]
    clusters = paired.groupby("race_date").delta.agg(["sum", "size"])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    index = rng.integers(0, len(clusters), size=(BOOTSTRAP_REPS, len(clusters)))
    values = clusters["sum"].to_numpy()[index].sum(axis=1) / clusters["size"].to_numpy()[index].sum(axis=1)
    return {"delta": float(paired.delta.mean()), "lo": float(np.quantile(values, 0.025)),
            "hi": float(np.quantile(values, 0.975)), "rows": int(len(paired)), "days": int(len(clusters))}


def compare_keyed(actual: pd.DataFrame, expected: pd.DataFrame, keys: list[str],
                  numeric: list[str], label: str) -> None:
    require(set(keys + numeric).issubset(actual.columns), f"{label}: actual schema missing columns")
    require(set(keys + numeric).issubset(expected.columns), f"{label}: expected schema missing columns")
    left = actual.sort_values(keys, kind="stable").reset_index(drop=True)
    right = expected.sort_values(keys, kind="stable").reset_index(drop=True)
    require(len(left) == len(right), f"{label}: row count mismatch {len(left)} != {len(right)}")
    for key in keys:
        require(left[key].astype(str).equals(right[key].astype(str)), f"{label}: key mismatch {key}")
    for col in numeric:
        close(left[col].to_numpy(float), right[col].to_numpy(float), f"{label}: {col}")


def assert_frame_identity(actual: pd.DataFrame, expected: pd.DataFrame, keys: list[str], label: str) -> None:
    left = actual.sort_values(keys, kind="stable").reset_index(drop=True)
    right = expected.sort_values(keys, kind="stable").reset_index(drop=True)
    require(len(left) == len(right), f"{label}: row count mismatch")
    for col in keys:
        require(left[col].astype(str).equals(right[col].astype(str)), f"{label}: identity mismatch {col}")


def model_matrix(frame: pd.DataFrame, columns: list[str], vocabulary: dict[str, list[str]]) -> pd.DataFrame:
    x = frame[columns].copy()
    for column in ("grade_raw", "previous_sex", "previous_result_status"):
        if column in columns:
            require(column in vocabulary, f"model vocabulary missing {column}")
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocabulary[column])
    return x


def check_training_source_shape() -> dict[str, int]:
    """Confirm fit source has one initial fit, one refit and one calibration call per model."""
    path = STUDY / "run.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fit = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == "fit_candidate")
    train_calls = sum(1 for node in ast.walk(fit)
                      if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and isinstance(node.func.value, ast.Name) and node.func.value.id == "lgb"
                      and node.func.attr == "train")
    temperature_calls = sum(1 for node in ast.walk(fit)
                            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and isinstance(node.func.value, ast.Name) and node.func.value.id == "OLD"
                            and node.func.attr == "temperature")
    require(train_calls == 2 and temperature_calls == 1,
            f"fit_candidate call structure changed: lgb.train={train_calls}, temperature={temperature_calls}")
    return {"per_candidate_model_train_calls_in_source": train_calls,
            "per_candidate_model_temperature_calls_in_source": temperature_calls}


def frozen_model_parameters() -> dict[str, object]:
    source = BASELINE / "run.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "PARAMS"
                              for target in node.targets))
    require(isinstance(assignment.value, ast.Call) and isinstance(assignment.value.func, ast.Name)
            and assignment.value.func.id == "dict", "frozen baseline PARAMS is not a dict literal")
    result = {}
    for keyword in assignment.value.keywords:
        key = keyword.arg
        value_node = keyword.value
        if isinstance(value_node, ast.Name):
            require(value_node.id in constants, f"unknown frozen parameter constant: {value_node.id}")
            value = constants[value_node.id]
        else:
            value = ast.literal_eval(value_node)
        result[key] = value
    return result


def check_training_artifacts(lock: dict[str, object]) -> dict[str, object]:
    completion_path = STUDY / "outputs/training_completion.json"
    require(completion_path.exists(), "training_completion.json missing")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    require(completion.get("passed") is True, "candidate training completion did not pass")
    output_hashes = completion.get("outputs")
    require(isinstance(output_hashes, dict) and output_hashes, "training output hashes missing")
    for name, expected in output_hashes.items():
        path = STUDY / "outputs" / name
        require(path.is_file() and sha256(path) == expected, f"output changed after completion: {name}")
    completion_script = STUDY / "complete_outputs.py"
    require(completion_script.is_file() and
            sha256(completion_script) == completion.get("completion_script_sha256"),
            "completion script hash mismatch")

    candidate_models = []
    model_meta = []
    for variant in ("F1", "F2"):
        for year in EVAL_YEARS:
            folder = STUDY / f"outputs/{variant}_{year}"
            model_path = folder / "top3.txt"
            meta_path = folder / "meta.json"
            require(model_path.is_file() and meta_path.is_file(), f"missing {variant}_{year} final model/meta")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            require(sha256(model_path) == meta.get("model_sha256"), f"model hash mismatch: {variant}_{year}")
            require(meta.get("variant") == variant and int(meta.get("evaluation_year")) == year,
                    f"model metadata identity mismatch: {variant}_{year}")
            require(int(meta.get("lightgbm_train_calls", -1)) == 2 and
                    int(meta.get("temperature_optimizations", -1)) == 1,
                    f"model metadata call-count mismatch: {variant}_{year}")
            candidate_models.append(model_path)
            model_meta.append(meta)
    require(len(candidate_models) == 6 and len(model_meta) == 6, "expected six candidate final models")

    r1_models = []
    for year in EVAL_YEARS:
        folder = R1 / f"outputs/R1_{year}"
        model_path = folder / "top3.txt"
        meta_path = folder / "meta.json"
        require(model_path.is_file() and meta_path.is_file(), f"missing stored R1 model/meta {year}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        require(sha256(model_path) == meta.get("model_sha256"), f"R1 model hash mismatch: {year}")
        r1_models.append(model_path)
    require(len(r1_models) == 3, "expected three stored R1 models")
    source_shape = check_training_source_shape()
    require(sum(int(meta["lightgbm_train_calls"]) for meta in model_meta) == 12,
            "six model metadata do not sum to twelve training calls")
    require(sum(int(meta["temperature_optimizations"]) for meta in model_meta) == 6,
            "six model metadata do not sum to six temperature optimizations")
    require(completion.get("final_candidate_models") == 6 and
            completion.get("lightgbm_train_calls") == 12 and
            completion.get("temperature_optimizations") == 6,
            "candidate completion counts differ from model artifacts/metadata")
    return {"candidate_final_models": len(candidate_models), "stored_r1_models": len(r1_models),
            "candidate_train_calls_from_metadata": 12,
            "candidate_temperature_optimizations_from_metadata": 6,
            "completion_script_sha256_verified": True,
            **source_shape}


def verify_model_outputs(features: pd.DataFrame, predictions: pd.DataFrame,
                         races: pd.DataFrame, tickets: pd.DataFrame) -> dict[str, int]:
    r1_features = pd.read_parquet(R1 / "outputs/features.parquet")
    frozen_runners = pd.read_parquet(R1 / "outputs/runner_predictions.parquet")
    frozen_races = pd.read_csv(R1 / "outputs/race_metrics.csv")
    frozen_tickets = pd.read_csv(R1 / "outputs/six_combinations.csv")
    r1_reference_meta = json.loads((R1 / "outputs/R1_2024/meta.json").read_text(encoding="utf-8"))
    r1_columns = list(r1_reference_meta["features"])
    expected_parameters = frozen_model_parameters()
    require(len(r1_columns) == 21, "frozen R1 feature contract is not 21 columns")
    require(set(predictions.variant) == set(VARIANTS), "runner predictions variants differ")
    require(len(predictions) == 3 * 17412, "runner prediction row count differs")
    require(len(races) == 3 * 1779, "race metrics row count differs")
    require(not predictions.duplicated(["variant", "api_record_id"]).any(), "duplicate variant/API output")
    require(not races.duplicated(["variant", "race_id"]).any(), "duplicate variant/race metric")
    require(not tickets.duplicated(["variant", "race_id", "selection_rank"]).any(), "duplicate ticket rank")

    # The R1 replay must match both original saved values and direct reload predictions.
    r1_reproduced = pd.read_parquet(STUDY / "outputs/r1_reproduced_runner_predictions.parquet")
    replay_races = pd.read_csv(STUDY / "outputs/r1_reproduced_race_metrics.csv")
    replay_tickets = pd.read_csv(STUDY / "outputs/r1_reproduced_six_combinations.csv")
    replayed_models = 0
    calibration_rows = 0
    for year in EVAL_YEARS:
        eval_base = r1_features.loc[r1_features.year.eq(year)].reset_index(drop=True)
        eval_features = features.loc[features.year.eq(year)].reset_index(drop=True)
        pd.testing.assert_frame_equal(eval_features[r1_features.columns], eval_base, check_exact=True)
        cal_base = r1_features.loc[r1_features.year.eq(year - 1)].reset_index(drop=True)
        for variant in VARIANTS:
            if variant == "R1":
                folder = R1 / f"outputs/R1_{year}"
                meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
                columns = list(meta["features"])
            else:
                folder = STUDY / f"outputs/{variant}_{year}"
                meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
                columns = list(meta["features"])
                year_values = features.year
                train_mask = year_values.between(2017, year - 3)
                valid_mask = year_values.eq(year - 2)
                calibration_mask = year_values.eq(year - 1)
                evaluation_mask = year_values.eq(year)
                require(meta.get("parameters") == expected_parameters,
                        f"frozen LightGBM parameters changed: {variant}_{year}")
                require(int(meta.get("seed", -1)) == BOOTSTRAP_SEED,
                        f"model seed changed: {variant}_{year}")
                date_ranges = {
                    "training_min": features.loc[train_mask, "race_date"].min(),
                    "initial_training_max": features.loc[train_mask, "race_date"].max(),
                    "early_stopping_min": features.loc[valid_mask, "race_date"].min(),
                    "refit_max": features.loc[valid_mask, "race_date"].max(),
                    "calibration_min": features.loc[calibration_mask, "race_date"].min(),
                    "calibration_max": features.loc[calibration_mask, "race_date"].max(),
                    "evaluation_min": features.loc[evaluation_mask, "race_date"].min(),
                    "evaluation_max": features.loc[evaluation_mask, "race_date"].max(),
                }
                for key, expected_value in date_ranges.items():
                    require(str(meta.get(key)) == str(expected_value),
                            f"{variant}_{year} split date mismatch: {key}")
                require(int(meta.get("train_races")) == int(features.loc[train_mask | valid_mask, "race_id"].nunique()),
                        f"{variant}_{year} refit race count mismatch")
                require(int(meta.get("calibration_races")) == int(features.loc[calibration_mask, "race_id"].nunique()),
                        f"{variant}_{year} calibration race count mismatch")
                require(int(meta.get("evaluation_races")) == int(features.loc[evaluation_mask, "race_id"].nunique())
                        and int(meta.get("evaluation_rows")) == int(evaluation_mask.sum()),
                        f"{variant}_{year} evaluation cohort mismatch")
            require(columns == list(dict.fromkeys(columns)), f"duplicate model feature columns: {variant}_{year}")
            require(columns == r1_columns + ([
                "previous_finish_relative_rank", "previous_top3", "previous_result_status"
            ] if variant in ("F1", "F2") else []) + ([
                "same_distance_last5_top3_rate", "same_distance_last5_actual_n", "same_distance_last5_normal_n"
            ] if variant == "F2" else []), f"model feature contract mismatch: {variant}_{year}")
            model = lgb.Booster(model_file=str(folder / "top3.txt"))
            require(model.num_trees() == int(meta["trees"]), f"tree count mismatch: {variant}_{year}")
            require(list(model.feature_name()) == columns, f"model feature names mismatch: {variant}_{year}")
            eval_data = r1_features.loc[r1_features.year.eq(year)].reset_index(drop=True) if variant == "R1" else eval_features
            calibration = cal_base if variant == "R1" else features.loc[features.year.eq(year - 1)].reset_index(drop=True)
            x_eval = model_matrix(eval_data, columns, meta["vocabulary"])
            raw_score = model.predict(x_eval, raw_score=True, num_threads=4)
            stored = predictions.loc[predictions.variant.eq(variant) & predictions.year.eq(year)].copy()
            compare_keyed(stored, pd.DataFrame({"api_record_id": eval_data.api_record_id,
                                                "score": raw_score}), ["api_record_id"], ["score"],
                          f"{variant}_{year} reloaded scores")
            expected_rows, expected_runners, expected_tickets, _ = evaluate_races(
                eval_data, raw_score, float(meta["tau"]), variant)
            stored_rows = races.loc[races.variant.eq(variant) & races.year.eq(year)]
            compare_keyed(stored_rows, expected_rows, ["race_id"], RACE_METRICS,
                          f"{variant}_{year} race metrics")
            stored_runners = predictions.loc[predictions.variant.eq(variant) & predictions.year.eq(year)]
            compare_keyed(stored_runners, expected_runners, ["api_record_id"],
                          ["score", "p_top3", "y", "log_loss", "brier"],
                          f"{variant}_{year} runner metrics/probabilities")
            stored_tickets = tickets.loc[tickets.variant.eq(variant) & tickets.race_id.isin(expected_tickets.race_id)]
            compare_keyed(stored_tickets, expected_tickets, ["race_id", "selection_rank"],
                          ["probability", "hit"], f"{variant}_{year} six-combination probabilities")
            actual_numbers = stored_tickets.sort_values(["race_id", "selection_rank"], kind="stable").numbers.astype(str).tolist()
            expected_numbers = expected_tickets.sort_values(["race_id", "selection_rank"], kind="stable").numbers.astype(str).tolist()
            require(actual_numbers == expected_numbers, f"{variant}_{year} six-combination numbers mismatch")

            # Recompute calibration scores and the fitted temperature from saved calibration rows.
            x_cal = model_matrix(calibration, columns, meta["vocabulary"])
            cal_score = model.predict(x_cal, raw_score=True, num_threads=4)
            if variant == "R1":
                saved_cal = pd.read_parquet(folder / "calibration_scores.parquet")
            else:
                saved_cal = pd.read_parquet(folder / "calibration_scores.parquet")
            compare_keyed(saved_cal, pd.DataFrame({"api_record_id": calibration.api_record_id,
                                                  "score": cal_score}), ["api_record_id"], ["score"],
                          f"{variant}_{year} calibration scores")
            recalculated_tau = temperature(calibration, cal_score)
            close([float(meta["tau"])], [recalculated_tau], f"{variant}_{year} calibration temperature")
            calibration_rows += len(cal_score)
            replayed_models += 1

    compare_keyed(r1_reproduced, frozen_runners.loc[frozen_runners.variant.eq("R1")],
                  ["api_record_id"], ["score", "p_top3", "log_loss", "brier"], "R1 replay vs original")
    compare_keyed(replay_races, frozen_races.loc[frozen_races.variant.eq("R1")],
                  ["race_id"], RACE_METRICS, "R1 replay race metrics vs original")
    compare_keyed(replay_tickets, frozen_tickets.loc[frozen_tickets.variant.eq("R1")],
                  ["race_id", "selection_rank"], ["probability", "hit"], "R1 replay tickets vs original")
    require(replay_tickets.sort_values(["race_id", "selection_rank"], kind="stable").numbers.astype(str).tolist() ==
            frozen_tickets.loc[frozen_tickets.variant.eq("R1")].sort_values(
                ["race_id", "selection_rank"], kind="stable").numbers.astype(str).tolist(),
            "R1 replay combination numbers differ from original")
    return {"models_reloaded_and_scored": replayed_models, "calibration_score_rows_recomputed": calibration_rows,
            "runner_rows_checked": int(len(predictions)), "race_metric_rows_checked": int(len(races)),
            "six_combination_rows_checked": int(len(tickets)), "r1_replay_original_match": True}


def verify_group_tables(runners: pd.DataFrame, races: pd.DataFrame) -> dict[str, int]:
    race_groups = [("all", "all", races)]
    race_groups.extend(("year", str(year), group) for year, group in races.groupby("year"))
    race_groups.extend(("distance_m", str(int(distance)), group) for distance, group in races.groupby("distance_m"))
    expected_race_rows = []
    expected_race_diff = []
    for kind, value, group in race_groups:
        for variant, one in group.groupby("variant"):
            expected_race_rows.append({"group": kind, "value": value, "variant": variant,
                                       "races": len(one), "days": one.race_date.nunique(),
                                       **{m: float(one[m].mean()) for m in RACE_METRICS}})
        for left_variant, right_variant in COMPARISONS:
            left = group.loc[group.variant.eq(left_variant)]
            right = group.loc[group.variant.eq(right_variant)]
            for metric in RACE_METRICS:
                expected_race_diff.append({"group": kind, "value": value,
                    "comparison": f"{left_variant}-{right_variant}", "metric": metric,
                    **date_bootstrap(left, right, metric)})
    saved_race_rows = pd.read_csv(STUDY / "outputs/metrics_by_group.csv")
    saved_race_diff = pd.read_csv(STUDY / "outputs/paired_differences.csv")
    compare_keyed(saved_race_rows, pd.DataFrame(expected_race_rows), ["group", "value", "variant"],
                  ["races", "days"] + RACE_METRICS, "race grouped summaries")
    compare_keyed(saved_race_diff, pd.DataFrame(expected_race_diff),
                  ["group", "value", "comparison", "metric"], ["delta", "lo", "hi", "races", "days"],
                  "race paired bootstrap table")

    runner_groups = [("all", "all", runners)]
    runner_groups.extend(("year", str(year), group) for year, group in runners.groupby("year"))
    runner_groups.extend(("distance_m", str(int(distance)), group) for distance, group in runners.groupby("distance_m"))
    for column, labels in (("observed_starts", ["0", "1_4", "5_plus"]),
                           ("same_starts", ["0", "1_4", "5_plus"])):
        bins = pd.cut(runners[column], [-1, 0, 4, np.inf], labels=labels)
        runner_groups.extend((column, label, runners.loc[bins.astype("string").eq(label)]) for label in labels)
    for column, labels in (("previous_result_status", ["normal", "non_normal_or_incomplete", "unobserved"]),):
        runner_groups.extend((column, label, runners.loc[runners[column].eq(label)]) for label in labels)
    top3_state = runners.previous_top3.map({0.0: "not_top3", 1.0: "top3"}).fillna("unknown")
    runner_groups.extend(("previous_top3", label, runners.loc[top3_state.eq(label)])
                         for label in ["not_top3", "top3", "unknown"])
    expected_runner_rows = []
    expected_runner_diff = []
    for kind, value, group in runner_groups:
        if group.empty:
            continue
        for variant, one in group.groupby("variant"):
            weights = 1 / one.field_n
            expected_runner_rows.append({"group": kind, "value": value, "variant": variant,
                "rows": len(one), "races": one.race_id.nunique(), "days": one.race_date.nunique(),
                "log_loss": float(one.log_loss.mean()), "brier": float(one.brier.mean()),
                "weighted_log_loss": float(np.average(one.log_loss, weights=weights)),
                "weighted_brier": float(np.average(one.brier, weights=weights)),
                "predicted": float(np.average(one.p_top3, weights=weights)),
                "actual": float(np.average(one.y, weights=weights))})
        for left_variant, right_variant in COMPARISONS:
            left = group.loc[group.variant.eq(left_variant)]
            right = group.loc[group.variant.eq(right_variant)]
            if left.empty or right.empty:
                continue
            for metric in RUNNER_METRICS:
                expected_runner_diff.append({"group": kind, "value": value,
                    "comparison": f"{left_variant}-{right_variant}", "metric": metric,
                    **runner_bootstrap(left, right, metric)})
    saved_runner_rows = pd.read_csv(STUDY / "outputs/runner_metrics_by_group.csv")
    saved_runner_diff = pd.read_csv(STUDY / "outputs/runner_paired_differences.csv")
    compare_keyed(saved_runner_rows, pd.DataFrame(expected_runner_rows), ["group", "value", "variant"],
                  ["rows", "races", "days", "log_loss", "brier", "weighted_log_loss", "weighted_brier",
                   "predicted", "actual"], "runner grouped summaries")
    compare_keyed(saved_runner_diff, pd.DataFrame(expected_runner_diff),
                  ["group", "value", "comparison", "metric"], ["delta", "lo", "hi", "rows", "days"],
                  "runner paired bootstrap table")

    edges = np.linspace(0, 1, 11)
    expected_calibration = []
    for variant, group in runners.groupby("variant"):
        bins = pd.cut(group.p_top3, edges, include_lowest=True)
        for interval, one in group.groupby(bins, observed=True):
            weights = 1 / one.field_n
            expected_calibration.append({"variant": variant, "probability_bin": str(interval),
                "rows": len(one), "races": one.race_id.nunique(),
                "predicted": float(np.average(one.p_top3, weights=weights)),
                "observed": float(np.average(one.y, weights=weights))})
    saved_calibration = pd.read_csv(STUDY / "outputs/calibration_bins.csv")
    compare_keyed(saved_calibration, pd.DataFrame(expected_calibration), ["variant", "probability_bin"],
                  ["rows", "races", "predicted", "observed"], "calibration bins")
    return {"race_group_summaries": len(expected_race_rows), "race_paired_bootstrap_rows": len(expected_race_diff),
            "runner_group_summaries": len(expected_runner_rows),
            "runner_paired_bootstrap_rows": len(expected_runner_diff),
            "calibration_bins": len(expected_calibration)}


def verify_operating_common(runners: pd.DataFrame, races: pd.DataFrame,
                            tickets: pd.DataFrame) -> dict[str, int]:
    op_runners = pd.read_parquet(OPS / "outputs/runner_predictions.parquet")
    op_races = pd.read_csv(OPS / "outputs/race_metrics.csv")
    op_tickets = pd.read_csv(OPS / "outputs/six_combinations.csv")
    common_ids = set(op_races.loc[op_races.variant.eq("HY_R_FORM"), "race_id"])
    require(len(common_ids) == 467, f"operating common races {len(common_ids)} != 467")
    op_base_races = op_races.loc[op_races.variant.eq("HY_R_FORM")].copy()
    op_base_runners = op_runners.loc[op_runners.variant.eq("HY_R_FORM")].copy()
    op_base_tickets = op_tickets.loc[op_tickets.variant.eq("HY_R_FORM")].copy()
    require(len(op_base_races) == 467 and len(op_base_runners) == 4475 and len(op_base_tickets) == 467 * 6,
            "operating HY_R_FORM reference counts differ")
    compare_keyed(op_base_races, pd.read_csv(OPS / "outputs/race_metrics.csv").query("variant == 'HY_R_FORM'"),
                  ["race_id"], ["brier", "log_loss", "pick_hit", "top3_all3", "top5_all3", "top5_capture", "six_combo_hit"],
                  "operating saved base race table")
    saved_races = pd.read_csv(STUDY / "outputs/operating_common_467_race_metrics.csv")
    saved_runners = pd.read_parquet(STUDY / "outputs/operating_common_467_runner_predictions.parquet")
    saved_tickets = pd.read_csv(STUDY / "outputs/operating_common_467_six_combinations.csv")
    summaries = pd.read_csv(STUDY / "outputs/operating_common_467_summary.csv")
    differences = pd.read_csv(STUDY / "outputs/operating_common_467_paired_differences.csv")
    require(set(saved_races.variant) == {"HY_R_FORM", "R1", "F1", "F2"}, "operating race variants differ")
    require(saved_races.groupby("variant").race_id.nunique().eq(467).all(), "operating race count per variant differs")
    require(saved_runners.groupby("variant").size().eq(4475).all(), "operating runner count per variant differs")
    require(saved_tickets.groupby("variant").size().eq(467 * 6).all(), "operating ticket count per variant differs")

    candidate = runners.loc[runners.race_id.isin(common_ids) & runners.year.eq(2026)].copy()
    for variant in VARIANTS:
        one = candidate.loc[candidate.variant.eq(variant)]
        ref = op_base_runners
        assert_frame_identity(one, ref, ["race_id", "horse_id", "y"], f"{variant} vs operating common runners")
        extracted = saved_runners.loc[saved_runners.variant.eq(variant)]
        compare_keyed(extracted, one, ["race_id", "horse_id"],
                      ["p_top3", "brier", "log_loss", "y"],
                      f"{variant} persisted 467-runner slice")
        candidate_tickets = tickets.loc[tickets.variant.eq(variant) & tickets.race_id.isin(common_ids)]
        persisted_tickets = saved_tickets.loc[saved_tickets.variant.eq(variant)]
        compare_keyed(persisted_tickets, candidate_tickets, ["race_id", "selection_rank"],
                      ["probability", "hit"], f"{variant} persisted 467 tickets")
        require(persisted_tickets.sort_values(["race_id", "selection_rank"], kind="stable").numbers.astype(str).tolist() ==
                candidate_tickets.sort_values(["race_id", "selection_rank"], kind="stable").numbers.astype(str).tolist(),
                f"{variant} persisted 467 ticket numbers differ")
    # Recompute the 467 race statistics for candidates and confirm the saved operating baseline.
    recomputed = []
    for variant in VARIANTS:
        for race_id, group in candidate.loc[candidate.variant.eq(variant)].groupby("race_id", sort=False):
            group = group.sort_values("horse_number", kind="stable")
            order = np.argsort(-group.score.to_numpy(float), kind="stable")
            truth = set(np.flatnonzero(group.y.to_numpy(int)))
            ticket = tickets.loc[tickets.variant.eq(variant) & tickets.race_id.eq(race_id)]
            recomputed.append({"race_id": race_id, "variant": variant,
                "brier": float(group.brier.mean()), "log_loss": float(group.log_loss.mean()),
                "pick_hit": int(group.y.iloc[order[0]]),
                "top3_all3": int(truth.issubset(set(order[:3]))),
                "top5_all3": int(truth.issubset(set(order[:5]))),
                "top5_capture": len(truth.intersection(set(order[:5]))) / 3,
                "six_combo_hit": int(ticket.hit.max())})
    expected = pd.DataFrame(recomputed)
    candidate_saved = saved_races.loc[saved_races.variant.isin(VARIANTS)]
    compare_keyed(candidate_saved, expected, ["variant", "race_id"],
                  ["brier", "log_loss", "pick_hit", "top3_all3", "top5_all3", "top5_capture", "six_combo_hit"],
                  "operating candidate race metrics")
    # Check that the saved operating baseline's rows and tickets still match their source outputs.
    saved_base = saved_races.loc[saved_races.variant.eq("HY_R_FORM")]
    compare_keyed(saved_base, op_base_races, ["race_id"],
                  ["brier", "log_loss", "pick_hit", "top3_all3", "top5_all3", "top5_capture", "six_combo_hit"],
                  "operating baseline race metrics")
    saved_base_tickets = saved_tickets.loc[saved_tickets.variant.eq("HY_R_FORM")]
    compare_keyed(saved_base_tickets, op_base_tickets, ["race_id", "selection_rank"], ["probability", "hit"],
                  "operating baseline tickets")
    require(saved_base_tickets.sort_values(["race_id", "selection_rank"], kind="stable").numbers.astype(str).tolist() ==
            op_base_tickets.sort_values(["race_id", "selection_rank"], kind="stable").numbers.astype(str).tolist(),
            "operating baseline ticket numbers differ")
    persisted_base_runners = saved_runners.loc[saved_runners.variant.eq("HY_R_FORM")]
    compare_keyed(persisted_base_runners, op_base_runners, ["race_id", "horse_id"],
                  ["p_top3", "brier", "log_loss", "y"], "operating baseline runner rows")

    metric_names = ["brier", "log_loss", "pick_hit", "top3_all3", "top5_all3", "top5_capture", "six_combo_hit"]
    expected_summary = []
    expected_diffs = []
    for variant, group in saved_races.groupby("variant"):
        expected_summary.append({"variant": variant, "races": len(group), "days": group.race_date.nunique(),
                                 **{metric: float(group[metric].mean()) for metric in metric_names}})
    for variant in VARIANTS:
        for metric in metric_names:
            expected_diffs.append({"comparison": f"{variant}-HY_R_FORM", "metric": metric,
                **date_bootstrap(saved_races.loc[saved_races.variant.eq(variant)],
                                 saved_races.loc[saved_races.variant.eq("HY_R_FORM")], metric)})
    compare_keyed(summaries, pd.DataFrame(expected_summary), ["variant"],
                  ["races", "days"] + metric_names, "operating comparison summary")
    compare_keyed(differences, pd.DataFrame(expected_diffs), ["comparison", "metric"],
                  ["delta", "lo", "hi", "races", "days"], "operating paired bootstrap")
    return {"operating_common_races": len(common_ids), "operating_common_runner_rows_per_variant": 4475,
            "operating_common_ticket_rows_per_variant": 467 * 6,
            "operating_race_metric_rows": len(saved_races), "operating_runner_rows": len(saved_runners)}


def sequential_gate_report(races: pd.DataFrame) -> dict[str, object]:
    differences = pd.read_csv(STUDY / "outputs/paired_differences.csv")

    def gate(comparison: str) -> dict[str, object]:
        selected = differences.loc[differences.group.eq("all") &
                                   differences.comparison.eq(comparison) &
                                   differences.metric.isin(["log_loss", "brier"])].set_index("metric")
        require(set(selected.index) == {"log_loss", "brier"}, f"missing sequential metrics for {comparison}")
        values = {metric: {"delta": float(selected.loc[metric, "delta"]),
                           "lo": float(selected.loc[metric, "lo"]),
                           "hi": float(selected.loc[metric, "hi"])}
                  for metric in ("log_loss", "brier")}
        both_lower = all(item["delta"] < 0 for item in values.values())
        one_interval_below_zero = any(item["hi"] < 0 for item in values.values())
        return {"comparison": comparison, "metrics": values,
                "both_point_estimates_lower": both_lower,
                "at_least_one_95pct_interval_below_zero": one_interval_below_zero,
                "passed": bool(both_lower and one_interval_below_zero)}

    f1 = gate("F1-R1")
    f2 = gate("F2-F1")
    return {"F1_vs_R1": f1, "F2_vs_F1": f2,
            "F2_sequential_research_candidate": bool(f1["passed"] and f2["passed"]),
            "F2_vs_R1_is_auxiliary_only": True,
            "interpretation": "retrospective research-candidate gate; not independent future validation or operational promotion"}


def check_lock_hashes() -> dict[str, int]:
    path = STUDY / "outputs/prepared_lock.json"
    require(path.exists(), "prepared_lock.json missing")
    lock = json.loads(path.read_text(encoding="utf-8"))
    protected = lock.get("protected")
    require(isinstance(protected, dict) and protected, "protected hash manifest missing")
    checked = 0
    for raw, expected in protected.items():
        file_path = safe_root_path(raw)
        require(file_path.is_file(), f"protected file missing: {raw}")
        expected_sha = expected.get("sha256") if isinstance(expected, dict) else expected
        require(sha256(file_path) == expected_sha, f"protected hash changed: {raw}")
        if isinstance(expected, dict) and "bytes" in expected:
            require(file_path.stat().st_size == int(expected["bytes"]), f"protected size changed: {raw}")
        checked += 1
    references = lock.get("references", {})
    reference_checks = 0
    for raw, expected in references.items():
        file_path = safe_root_path(raw)
        require(file_path.is_file(), f"reference file missing: {raw}")
        expected_sha = expected.get("sha256") if isinstance(expected, dict) else expected
        require(sha256(file_path) == expected_sha, f"reference hash changed: {raw}")
        reference_checks += 1
    prepared = lock.get("artifacts", {})
    for name, expected in prepared.items():
        file_path = STUDY / "outputs" / name
        require(file_path.is_file() and sha256(file_path) == expected, f"prepared artifact hash changed: {name}")
    old_lock_path = STUDY / "outputs/prepared_lock_before_supervisor_addendum.json"
    require(old_lock_path.exists(), "pre-addendum prepared lock missing")
    old_lock = json.loads(old_lock_path.read_text(encoding="utf-8"))
    require(all(references.get(path) == value for path, value in old_lock["references"].items()),
            "pre-addendum references changed")
    require(lock.get("protected") == old_lock.get("protected") and
            lock.get("artifacts") == old_lock.get("artifacts"),
            "protected/prepared artifact lock changed while adding supervisor gate")
    contract_path = "jeju/research/20261009_finish_history_ablation_v1/CONTRACT.md"
    addendum_path = "jeju/research/20261009_finish_history_ablation_v1/SUPERVISOR_GATE_ADDENDUM.md"
    require(lock.get("contract_sha256_locked_before_addendum") == old_lock["references"].get(contract_path),
            "original contract SHA was not preserved in supplemental lock")
    require(lock.get("supervisor_gate_addendum_sha256") == references.get(addendum_path),
            "supervisor addendum SHA is not locked")
    return {"protected_files": checked, "reference_files": reference_checks,
            "prepared_artifacts": len(prepared), "pre_addendum_contract_locked": 1,
            "supervisor_addendum_locked": 1}


def verify() -> dict[str, object]:
    """Run after all candidate outputs and training_completion.json are written."""
    require(INTEGRATION_COMPLETE, "independent verifier integration is still in progress")
    candidate_final_path = STUDY / "outputs/final_verification.json"
    candidate_final = None
    if candidate_final_path.exists():
        candidate_final = json.loads(candidate_final_path.read_text(encoding="utf-8"))
        require(candidate_final.get("passed") is True, "candidate final verifier did not pass")
        require(candidate_final.get("probability_sum_checked_races") == 3 * 1779,
                "candidate probability check is incomplete")
    source, base, features = load_source_and_features()
    stats, source_by_id = event_index(source)
    feature_checks = recompute_history_features(base, features, stats, source_by_id)
    lock = json.loads((STUDY / "outputs/prepared_lock.json").read_text(encoding="utf-8"))
    training_checks = check_training_artifacts(lock)
    predictions = pd.read_parquet(STUDY / "outputs/runner_predictions.parquet")
    races = pd.read_csv(STUDY / "outputs/race_metrics.csv")
    tickets = pd.read_csv(STUDY / "outputs/six_combinations.csv")
    model_checks = verify_model_outputs(features, predictions, races, tickets)
    grouped_checks = verify_group_tables(predictions, races)
    operating_checks = verify_operating_common(predictions, races, tickets)
    sequential_gates = sequential_gate_report(races)
    hashes = check_lock_hashes()
    return {"passed": True, "feature_checks": feature_checks, "training_artifact_checks": training_checks,
            "model_probability_metric_checks": model_checks, "group_and_interval_checks": grouped_checks,
            "operating_467_checks": operating_checks, "sequential_gate_interpretation": sequential_gates,
            "hash_checks": hashes, "database_changed": False, "production_changed": False,
            "evaluation_is_independent_future_validation": False,
            "candidate_final_verification_present": candidate_final is not None}


if __name__ == "__main__":
    report = verify()
    receipt = REVIEW / "independent_verification.json"
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

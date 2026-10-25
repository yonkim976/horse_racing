"""Independent, read-only verification of the fixed axis-selector fit outputs.

Recomputes feature construction, saved-model utility scores, race selections,
cohort metrics, and the frozen date bootstrap. It does not optimize or refit.
It writes only outputs/FIT_REVIEW.json in this review folder.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[3]
REVIEW = ROOT / "jeju/research/20261020_axis_selector_review_v1"
OUT = REVIEW / "outputs"
STUDY = ROOT / "jeju/research/20261020_axis_selector_v1"
FIT_OUT = STUDY / "outputs"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BASELINE = ROOT / "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
SCHEDULE = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
YEARS = (2024, 2025, 2026)
DISTANCES = (900, 1000, 1110, 1200)
BASIS = (
    "score_rank", "score_z", "log_observed_starts", "log_days_since_start",
    "days_since_start_missing", "log_same_starts", "log_same_valid_times",
    "log_days_since_same", "days_since_same_missing", "mean5_rank_fraction",
    "mean5_rank_fraction_missing",
)
WINDOWS = {
    2024: (2019, 2023, 25278, 2492, 7476, 2106, 4212, "2023-12-30", 6329, 637),
    2025: (2019, 2024, 31607, 3129, 9387, 2645, 5290, "2024-12-28", 6410, 654),
    2026: (2019, 2025, 38017, 3783, 11349, 3205, 6410, "2025-12-27", 4673, 488),
}


class ReviewError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ReviewError(message)


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_file() and resolved.is_relative_to(ROOT), f"input outside workspace: {path}")
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with checked(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(checked(path).read_text(encoding="utf-8"))


def close(a, b, *, atol=1e-12) -> bool:
    return bool(np.allclose(np.asarray(a), np.asarray(b), rtol=0.0, atol=atol, equal_nan=True))


def derive(frame: pd.DataFrame, scores: np.ndarray, probabilities: np.ndarray | None = None,
           labels: np.ndarray | None = None) -> pd.DataFrame:
    data = frame.reset_index(drop=True).copy()
    data["base_score"] = np.asarray(scores, dtype=np.float64)
    require(len(data) == len(scores) and np.isfinite(data["base_score"]).all(), "invalid score vector")
    if probabilities is not None:
        data["base_p"] = np.asarray(probabilities, dtype=np.float64)
        require(np.isfinite(data["base_p"]).all(), "invalid p_top3 vector")
    if labels is None:
        data["y"] = data["finish_position"].le(3).to_numpy(dtype=np.int8)
    else:
        data["y"] = np.asarray(labels, dtype=np.int8)
    data = data.sort_values(["race_id", "base_score", "horse_number"],
                            ascending=[True, False, True], kind="mergesort").reset_index(drop=True)
    data["score_rank"] = data.groupby("race_id", sort=False).cumcount().add(1)
    scores_group = data.groupby("race_id", sort=False)["base_score"]
    means = scores_group.transform("mean").to_numpy(dtype=np.float64)
    sds = scores_group.transform(lambda x: x.std(ddof=0)).to_numpy(dtype=np.float64)
    data["score_z"] = np.divide(data["base_score"].to_numpy(dtype=np.float64) - means, sds,
                                out=np.zeros(len(data), dtype=np.float64), where=sds > 0.0)
    for source, dest in (("observed_starts", "log_observed_starts"),
                         ("same_starts", "log_same_starts"),
                         ("same_valid_times", "log_same_valid_times")):
        values = pd.to_numeric(data[source], errors="raise").to_numpy(dtype=np.float64)
        require(np.isfinite(values).all() and (values >= 0).all(), f"invalid {source}")
        data[dest] = np.log1p(values)
    for source, dest, flag in (("days_since_start", "log_days_since_start", "days_since_start_missing"),
                               ("days_since_same", "log_days_since_same", "days_since_same_missing")):
        values = pd.to_numeric(data[source], errors="raise").to_numpy(dtype=np.float64)
        missing = np.isnan(values)
        require(np.isfinite(values[~missing]).all() and (values[~missing] >= 0).all(), f"invalid {source}")
        data[flag] = missing.astype(np.float64)
        data[dest] = np.log1p(np.where(missing, 0.0, values))
    values = pd.to_numeric(data["mean5_rank_fraction"], errors="raise").to_numpy(dtype=np.float64)
    missing = np.isnan(values)
    require(np.isfinite(values[~missing]).all(), "invalid mean5_rank_fraction")
    data["mean5_rank_fraction_missing"] = missing.astype(np.float64)
    data["mean5_rank_fraction"] = np.where(missing, 0.0, values)
    require(np.isfinite(data.loc[:, BASIS].to_numpy(dtype=np.float64)).all(), "non-finite basis")
    return data


def summarize(frame: pd.DataFrame) -> dict:
    n = len(frame)
    require(n > 0, "empty metric cohort")
    base = int(frame["baseline_hit"].sum())
    selected = int(frame["selector_hit"].sum())
    both = int((frame["outcome"] == "both").sum())
    baseline_only = int((frame["outcome"] == "baseline_only").sum())
    selector_only = int((frame["outcome"] == "selector_only").sum())
    neither = int((frame["outcome"] == "neither").sum())
    return {
        "races": int(n), "baseline_top3_hits": base, "selector_top3_hits": selected,
        "baseline_top3_rate": base / n, "selector_top3_rate": selected / n,
        "selector_minus_baseline": (selected - base) / n,
        "axis_changed_races": int(frame["axis_changed"].sum()),
        "axis_changed_rate": float(frame["axis_changed"].mean()),
        "new_selector_hits": selector_only, "lost_baseline_hits": baseline_only,
        "both_hit": both, "neither_hit": neither,
        "outcome_counts": {"both": both, "baseline_only": baseline_only,
                           "selector_only": selector_only, "neither": neither},
    }


def compare_summary(actual: dict, expected: dict, label: str) -> None:
    for key in ("races", "baseline_top3_hits", "selector_top3_hits", "axis_changed_races",
                "new_selector_hits", "lost_baseline_hits", "both_hit", "neither_hit", "outcome_counts"):
        require(actual.get(key) == expected.get(key), f"{label}: {key} mismatch")
    for key in ("baseline_top3_rate", "selector_top3_rate", "selector_minus_baseline", "axis_changed_rate"):
        require(close(actual.get(key), expected.get(key)), f"{label}: {key} mismatch")


def run() -> dict:
    receipt_path = FIT_OUT / "FIT_RECEIPT.json"
    receipt = read_json(receipt_path)
    require(receipt.get("status") == "PASS" and receipt.get("fits_completed") == 3,
            "fit receipt does not report exactly three completed fits")
    require(receipt.get("database_or_network_access") is False and
            receipt.get("existing_model_or_registry_modified") is False,
            "fit receipt has unexpected side-effect claim")
    approval_path = FIT_OUT / "ROOT_FIT_APPROVAL.json"
    approval = read_json(approval_path)
    code_path = STUDY / "fit_selector.py"
    plan_path = STUDY / "PLAN.md"
    preflight_path = FIT_OUT / "PREFLIGHT.json"
    lock_path = FIT_OUT / "SOURCE_LOCK.json"
    require(approval.get("approved") is True and approval.get("approved_fits") == 3,
            "approval does not bind exactly three fits")
    require(receipt["fit_code_sha256"] == sha256(code_path) == approval.get("fit_code_sha256"),
            "fit code hash differs from receipt or approval")
    require(receipt["plan_sha256"] == sha256(plan_path) == approval.get("plan_sha256"),
            "plan hash mismatch")
    require(receipt["preflight_sha256"] == sha256(preflight_path) == approval.get("preflight_sha256"),
            "preflight hash mismatch")
    require(receipt["source_lock_sha256"] == sha256(lock_path) == approval.get("source_lock_sha256"),
            "source lock hash mismatch")
    require(receipt["root_approval_sha256"] == sha256(approval_path), "approval hash mismatch")
    lock = read_json(lock_path)
    require(receipt["source_hashes"] == lock["sources"], "receipt source map differs from source lock")
    for rel, digest in receipt["source_hashes"].items():
        path = checked(ROOT / rel)
        require(sha256(path) == digest, f"locked input hash changed: {rel}")
    for name, digest in receipt["output_sha256"].items():
        require(sha256(FIT_OUT / name) == digest, f"output hash differs from fit receipt: {name}")

    features = pd.read_parquet(checked(FEATURES))
    baseline = pd.read_parquet(checked(BASELINE))
    candidate_output = pd.read_parquet(checked(FIT_OUT / "candidate_predictions.parquet"))
    choice_output = pd.read_parquet(checked(FIT_OUT / "race_choices.parquet"))
    report = read_json(FIT_OUT / "REPORT.json")
    require(candidate_output["api_record_id"].is_unique and choice_output["race_id"].is_unique,
            "duplicate prediction or choice keys")
    checked_columns = (list(features.columns) + list(baseline.columns) + list(candidate_output.columns) +
                       list(choice_output.columns) + list(BASIS))
    forbidden_tokens = ("odds", "favorite", "fav_id", "배당", "인기")
    require(not any(any(token in str(column).casefold() for token in forbidden_tokens)
                    for column in checked_columns),
            "market/favorite field found in source, basis, or selector output")

    models: dict[int, dict] = {}
    model_hashes = {}
    verified_counts = {}
    all_full: dict[int, pd.DataFrame] = {}
    expected_candidate_rows = []
    expected_choices = []
    max_scaler_error = 0.0
    max_objective_error = 0.0
    max_gradient_error = 0.0
    max_utility_error = 0.0

    for year in YEARS:
        model_path = FIT_OUT / f"model_{year}.json"
        model = read_json(model_path)
        models[year] = model
        model_hashes[str(year)] = sha256(model_path)
        ymin, ymax, source_rows, source_races, candidate_rows, rmix_expected, pairs_expected, last_date, eval_rows, eval_races = WINDOWS[year]
        require(model.get("status") == "FIT_PASS" and model.get("evaluation_year") == year,
                f"model metadata status/year mismatch: {year}")
        require(model.get("basis_order") == list(BASIS), f"basis order mismatch: {year}")
        require(model.get("training_label_year_min") == ymin and model.get("training_label_year_max") == ymax and
                model.get("training_max_label_date") == last_date, f"training window mismatch: {year}")
        require(model.get("optimizer", {}).get("success") is True and
                model.get("optimizer", {}).get("gradient_max_abs", 1.0) <= 1e-6,
                f"saved convergence criteria fail: {year}")
        require(model.get("utility_is_probability") is False and
                model.get("baseline_p_top3_used_as_feature") is False,
                f"probability contract mismatch: {year}")
        tproviders = model.get("training_score_providers", [])
        require([p.get("race_year") for p in tproviders] == list(range(ymin, ymax + 1)),
                f"training provider year list mismatch: {year}")
        for provider in tproviders:
            target_year = provider["race_year"]
            require(provider.get("provider_role") == "calibration_raw_score_only" and
                    provider.get("provider_fold") == target_year + 1,
                    f"wrong training provider role/fold: eval {year}, label {target_year}")
            rel = provider["source_path"]
            require(receipt["source_hashes"].get(rel) == provider["source_sha256"],
                    f"training provider hash absent from lock: {target_year}")
            require(sha256(ROOT / rel) == provider["source_sha256"], f"training score changed: {target_year}")
            meta = read_json(ROOT / provider["meta_path"])
            require(meta["refit_max"] == provider["provider_refit_max"],
                    f"training refit receipt mismatch: {target_year}")
            require(sha256(ROOT / provider["meta_path"]) == provider["meta_sha256"],
                    f"training metadata hash mismatch: {target_year}")
            target_dates = pd.to_datetime(features.loc[features["year"].eq(target_year), "race_date"], errors="raise")
            require(pd.Timestamp(provider["provider_refit_max"]) <= target_dates.min() - pd.Timedelta(days=2),
                    f"training provider not OOF before T-2: {target_year}")
        eval_provider = model["evaluation_score_provider"]
        require(eval_provider.get("race_year") == year and eval_provider.get("provider_fold") == year and
                eval_provider.get("provider_role") == "evaluation_raw_score_only",
                f"wrong eval provider role/fold: {year}")
        require(receipt["source_hashes"].get(eval_provider["source_path"]) == eval_provider["source_sha256"],
                f"eval provider hash absent from lock: {year}")
        eval_meta = read_json(ROOT / eval_provider["meta_path"])
        require(eval_meta["refit_max"] == eval_provider["provider_refit_max"] and
                sha256(ROOT / eval_provider["meta_path"]) == eval_provider["meta_sha256"],
                f"eval provider metadata mismatch: {year}")

        train = features.loc[features["year"].between(ymin, ymax)].copy()
        train_score = np.full(len(train), np.nan, dtype=np.float64)
        for provider in tproviders:
            target_year = provider["race_year"]
            fold_path = checked(ROOT / provider["source_path"])
            fold_scores = pd.read_parquet(fold_path)
            require(fold_scores.columns.tolist() == ["api_record_id", "score"] and
                    fold_scores["api_record_id"].is_unique, f"invalid raw score schema: {target_year}")
            subset = train["year"].eq(target_year).to_numpy()
            target_keys = train.loc[subset, "api_record_id"]
            aligned = fold_scores.set_index("api_record_id")["score"].reindex(target_keys)
            require(aligned.notna().all(), f"training OOF scores do not cover label year {target_year}")
            train_score[subset] = aligned.to_numpy(dtype=np.float64)
        require(np.isfinite(train_score).all(), f"missing training score: {year}")
        train_full = derive(train, train_score)
        train_candidates = train_full.loc[train_full["score_rank"].le(3)].copy().reset_index(drop=True)
        counts = (len(train), train["race_id"].nunique(), len(train_candidates))
        require(counts == (source_rows, source_races, candidate_rows), f"training roster count mismatch: {year}")
        require(str(pd.to_datetime(train["race_date"], errors="raise").max().date()) == last_date,
                f"training max date mismatch: {year}")
        x = train_candidates.loc[:, BASIS].to_numpy(dtype=np.float64)
        mean, sd = x.mean(axis=0), x.std(axis=0, ddof=0)
        scale = np.where(sd == 0.0, 1.0, sd)
        z = (x - mean) / scale
        saved_mean = np.array([model["mean_by_feature"][k] for k in BASIS], dtype=np.float64)
        saved_scale = np.array([model["scale_by_feature"][k] for k in BASIS], dtype=np.float64)
        max_scaler_error = max(max_scaler_error, float(np.max(np.abs(mean - saved_mean))),
                               float(np.max(np.abs(scale - saved_scale))))
        require(close(mean, saved_mean, atol=1e-13) and close(scale, saved_scale, atol=1e-13),
                f"training scaler mismatch: {year}")

        pair_rows = []
        mixed = 0
        for _, group in train_candidates.groupby("race_id", sort=False):
            idx = group.index.to_numpy()
            labels = group["y"].to_numpy(dtype=np.int8)
            pos, neg = idx[labels == 1], idx[labels == 0]
            if len(pos) and len(neg):
                require(len(pos) * len(neg) == 2, f"unexpected mixed K3 pair count: {year}")
                mixed += 1
                pair_rows.extend(z[i] - z[j] for i in pos for j in neg)
        pair_matrix = np.vstack(pair_rows)
        require(mixed == rmix_expected and len(pair_matrix) == pairs_expected,
                f"R_mix/pair count mismatch: {year}")
        beta = np.array([model["coefficients"][k] for k in BASIS], dtype=np.float64)
        margin = pair_matrix @ beta
        objective = float(np.logaddexp(0.0, -margin).mean() + 0.5 * beta.dot(beta))
        gradient = beta - (expit(-margin)[:, None] * pair_matrix).mean(axis=0)
        saved_opt = model["optimizer"]
        saved_gradient = np.array([saved_opt["gradient"][k] for k in BASIS], dtype=np.float64)
        max_objective_error = max(max_objective_error, abs(objective - saved_opt["objective_value"]))
        max_gradient_error = max(max_gradient_error, float(np.max(np.abs(gradient - saved_gradient))))
        require(close(objective, saved_opt["objective_value"], atol=2e-12) and
                close(gradient, saved_gradient, atol=2e-12), f"saved objective/gradient mismatch: {year}")
        require(model["training_counts"] == {
            "source_runners": source_rows, "source_races": source_races, "candidate_rows": candidate_rows,
            "informative_races_R_mix": rmix_expected, "informative_pair_rows": pairs_expected,
        }, f"training count metadata mismatch: {year}")

        ev = features.loc[features["year"].eq(year)].copy()
        pred = baseline.loc[baseline["year"].eq(year)].set_index("api_record_id").reindex(ev["api_record_id"])
        require(len(ev) == eval_rows and pred["race_id"].notna().all(), f"eval roster/key mismatch: {year}")
        for col in ("race_id", "year", "horse_id", "horse_number", "distance_m", "field_n", "observed_starts"):
            require(np.array_equal(ev[col].to_numpy(), pred[col].to_numpy()),
                    f"baseline identity mismatch {year}: {col}")
        y = pred["y"].to_numpy(dtype=np.int8)
        require(np.array_equal(y, ev["finish_position"].le(3).to_numpy(dtype=np.int8)),
                f"frozen target mismatch: {year}")
        eval_full = derive(ev, pred["score"].to_numpy(dtype=np.float64),
                           pred["p_top3"].to_numpy(dtype=np.float64), y)
        eval_candidates = eval_full.loc[eval_full["score_rank"].le(3)].copy().reset_index(drop=True)
        eval_x = eval_candidates.loc[:, BASIS].to_numpy(dtype=np.float64)
        utility = ((eval_x - mean) / scale) @ beta
        eval_candidates["utility"] = utility
        eval_candidates["selector_chosen"] = False
        eval_candidates["baseline_chosen"] = eval_candidates["score_rank"].eq(1)
        expected_candidate_rows.append(eval_candidates)
        all_full[year] = eval_full
        choice_rows = []
        for race_id, group in eval_candidates.groupby("race_id", sort=False):
            order = np.lexsort((group["horse_number"].to_numpy(), -group["base_score"].to_numpy(),
                                -group["utility"].to_numpy()))
            selected = group.iloc[int(order[0])]
            base = group.loc[group["score_rank"].eq(1)].iloc[0]
            eval_candidates.loc[group.index[int(order[0])], "selector_chosen"] = True
            base_hit, selected_hit = bool(base["y"]), bool(selected["y"])
            outcome = ("both" if base_hit and selected_hit else "baseline_only" if base_hit else
                       "selector_only" if selected_hit else "neither")
            choice_rows.append({
                "race_id": race_id, "year": int(base["year"]),
                "race_date": str(base["race_date"]), "distance_m": int(base["distance_m"]),
                "field_n": int(base["field_n"]),
                "baseline_axis_api_record_id": int(base["api_record_id"]),
                "baseline_axis_horse_id": str(base["horse_id"]),
                "baseline_axis_horse_number": int(base["horse_number"]),
                "baseline_score": float(base["base_score"]), "baseline_p_top3": float(base["base_p"]),
                "baseline_observed_starts": int(base["observed_starts"]), "baseline_hit": base_hit,
                "selector_axis_api_record_id": int(selected["api_record_id"]),
                "selector_axis_horse_id": str(selected["horse_id"]),
                "selector_axis_horse_number": int(selected["horse_number"]),
                "selector_utility": float(selected["utility"]), "selector_hit": selected_hit,
                "axis_changed": bool(base["api_record_id"] != selected["api_record_id"]),
                "outcome": outcome,
            })
        expected_choices.extend(choice_rows)
        actual_candidates = candidate_output.loc[candidate_output["year"].eq(year)].copy()
        actual_candidates = actual_candidates.set_index("api_record_id").sort_index()
        check_candidates = eval_candidates.set_index("api_record_id").sort_index()
        require(actual_candidates.index.equals(check_candidates.index), f"candidate roster mismatch: {year}")
        for col in ("race_id", "year", "horse_id", "horse_number", "distance_m", "score_rank", "y",
                    "selector_chosen", "baseline_chosen"):
            require(np.array_equal(actual_candidates[col].to_numpy(), check_candidates[col].to_numpy()),
                    f"candidate {col} mismatch: {year}")
        for col in ("base_score", "base_p", "utility"):
            err = float(np.max(np.abs(actual_candidates[col].to_numpy(dtype=np.float64) -
                                      check_candidates[col].to_numpy(dtype=np.float64))))
            if col == "utility":
                max_utility_error = max(max_utility_error, err)
            require(err <= 2e-12, f"candidate {col} mismatch: {year}")
        require(actual_candidates["provider_role"].eq("evaluation_raw_score_only").all() and
                actual_candidates["provider_fold"].eq(year).all() and
                actual_candidates["provider_source_path"].eq(eval_provider["source_path"]).all() and
                actual_candidates["provider_sha256"].eq(eval_provider["source_sha256"]).all() and
                actual_candidates["provider_refit_max"].eq(eval_provider["provider_refit_max"]).all(),
                f"candidate provider metadata mismatch: {year}")
        verified_counts[str(year)] = {
            "training_source_runners": int(source_rows), "training_source_races": int(source_races),
            "training_candidate_rows": int(candidate_rows), "R_mix": int(mixed),
            "informative_pairs": int(len(pair_matrix)), "evaluation_runners": int(eval_rows),
            "evaluation_races": int(eval_races),
        }

    expected_candidates = pd.concat(expected_candidate_rows, ignore_index=True)
    actual_choice = choice_output.set_index("race_id").sort_index()
    calc_choice = pd.DataFrame(expected_choices).set_index("race_id").sort_index()
    require(actual_choice.index.equals(calc_choice.index), "race choice key set mismatch")
    for col in ("year", "race_date", "distance_m", "field_n", "baseline_axis_api_record_id",
                "baseline_axis_horse_id", "baseline_axis_horse_number", "baseline_hit",
                "selector_axis_api_record_id", "selector_axis_horse_id", "selector_axis_horse_number",
                "selector_hit", "axis_changed", "outcome"):
        require(np.array_equal(actual_choice[col].to_numpy(), calc_choice[col].to_numpy()),
                f"race choice {col} mismatch")
    for col in ("baseline_score", "baseline_p_top3", "selector_utility"):
        require(close(actual_choice[col].to_numpy(dtype=np.float64),
                      calc_choice[col].to_numpy(dtype=np.float64), atol=2e-12),
                f"race choice {col} mismatch")

    races = choice_output.copy()
    require(len(races) == 1779 and races["race_id"].nunique() == 1779, "full evaluation denominator mismatch")
    primary = races.loc[races["distance_m"].isin(DISTANCES)].copy()
    require(len(primary) == 1503 and primary["race_id"].nunique() == 1503, "primary denominator mismatch")
    primary_summary = summarize(primary)
    full_summary = summarize(races)
    compare_summary(report["primary_four_distance_cohort"], primary_summary, "primary metrics")
    compare_summary(report["all_distance_cohort"], full_summary, "all-distance metrics")
    low, high = report["primary_four_distance_cohort"]["paired_date_bootstrap_ci95"]

    schedule = np.load(checked(SCHEDULE), allow_pickle=False)
    require(schedule.shape == (2000, 269) and schedule.dtype == np.int32, "bootstrap schedule shape/type mismatch")
    require(sha256(SCHEDULE) == "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
            "bootstrap schedule hash mismatch")
    dates = sorted(pd.to_datetime(races["race_date"], errors="raise").dt.strftime("%Y-%m-%d").unique())
    date_hash = hashlib.sha256("\n".join(dates).encode()).hexdigest()
    require(date_hash == report["bootstrap"]["date_inventory_sha256"], "bootstrap date inventory mismatch")
    expected_schedule = np.random.default_rng(20261011).integers(0, len(dates), size=(2000, 269),
                                                                 endpoint=False, dtype=np.int32)
    require(np.array_equal(schedule, expected_schedule), "bootstrap schedule recipe mismatch")
    day = primary.groupby("race_date", sort=False).agg(
        n=("race_id", "size"), base=("baseline_hit", "sum"), selected=("selector_hit", "sum"))
    day = day.reindex(dates, fill_value=0)
    denominator = day["n"].to_numpy(dtype=np.int64)[schedule].sum(axis=1)
    base_hits = day["base"].to_numpy(dtype=np.int64)[schedule].sum(axis=1)
    selected_hits = day["selected"].to_numpy(dtype=np.int64)[schedule].sum(axis=1)
    defined = denominator > 0
    delta = np.full(len(schedule), np.nan, dtype=np.float64)
    delta[defined] = (selected_hits[defined] - base_hits[defined]) / denominator[defined]
    ci = np.quantile(delta[defined], [0.025, 0.975])
    require(np.all(defined), "unexpected zero-denominator bootstrap draw")
    draw_output = pd.read_parquet(checked(FIT_OUT / "bootstrap_draws.parquet"))
    require(len(draw_output) == 2000, "bootstrap output row count mismatch")
    for col, values in (("draw_id", np.arange(2000, dtype=np.int32)),
                        ("primary_races", denominator), ("baseline_hits", base_hits),
                        ("selector_hits", selected_hits), ("defined", defined)):
        require(np.array_equal(draw_output[col].to_numpy(), values), f"bootstrap draw {col} mismatch")
    require(close(draw_output["selector_minus_baseline"].to_numpy(), delta, atol=1e-15),
            "bootstrap draw deltas mismatch")
    require(close(ci, [low, high], atol=1e-15), "bootstrap confidence interval mismatch")
    gate = primary_summary["selector_minus_baseline"] > 0 and float(ci[0]) > 0
    require(report["primary_four_distance_cohort"]["primary_gate_pass"] is gate and
            receipt["primary_gate_pass"] is gate and not gate,
            "primary gate status mismatch")

    # Recompute K=5 actual-Top3 coverage from full-field raw-score ranks.
    k5_rows = []
    for year, frame in all_full.items():
        cover = frame.loc[frame["score_rank"].le(5)].groupby("race_id", sort=False)["y"].max().astype(bool)
        dist = frame.groupby("race_id", sort=False)["distance_m"].first()
        k5_rows.append(pd.DataFrame({"year": year, "distance_m": dist, "covered": cover}))
    k5 = pd.concat(k5_rows)
    k5_primary = k5.loc[k5["distance_m"].isin(DISTANCES)]
    k5_all = {"races": int(len(k5)), "covered_races": int(k5["covered"].sum()),
              "coverage_rate": float(k5["covered"].mean())}
    k5_prim = {"races": int(len(k5_primary)), "covered_races": int(k5_primary["covered"].sum()),
               "coverage_rate": float(k5_primary["covered"].mean())}
    require(report["k5_coverage_diagnostic"]["all_distances"]["races"] == k5_all["races"] and
            report["k5_coverage_diagnostic"]["all_distances"]["covered_races"] == k5_all["covered_races"] and
            close(report["k5_coverage_diagnostic"]["all_distances"]["coverage_rate"], k5_all["coverage_rate"]),
            "K5 all-distance coverage mismatch")
    require(report["k5_coverage_diagnostic"]["primary_four_distance"]["races"] == k5_prim["races"] and
            report["k5_coverage_diagnostic"]["primary_four_distance"]["covered_races"] == k5_prim["covered_races"] and
            close(report["k5_coverage_diagnostic"]["primary_four_distance"]["coverage_rate"], k5_prim["coverage_rate"]),
            "K5 primary coverage mismatch")

    fit_findings = {
        "status": "PASS",
        "scope": "independent stored-output replay; no fit or parameter optimization",
        "fit_code_sha256": receipt["fit_code_sha256"],
        "fit_receipt_sha256": sha256(receipt_path),
        "verified_output_hashes": receipt["output_sha256"],
        "verified_model_hashes": model_hashes,
        "models_checked": len(models),
        "training_windows_and_counts": verified_counts,
        "checks": {
            "approval_code_plan_preflight_and_source_hashes": "PASS",
            "train_oof_provider_roles_keys_and_refit_t2": "PASS",
            "eval_provider_role_and_frozen_score_probability_preservation": "PASS",
            "training_scalers_recomputed_ddof0": "PASS",
            "saved_objective_and_analytic_gradient_recomputed_without_refit": "PASS",
            "race_level_choice_and_tie_break_replay": "PASS",
            "all_distance_and_primary_denominators_and_metrics": "PASS",
            "frozen_date_schedule_draws_ci_and_gate": "PASS",
            "k5_coverage_diagnostic": "PASS",
            "market_favorite_inputs_excluded": "PASS",
        },
        "max_abs_differences": {
            "training_mean_or_scale": max_scaler_error,
            "saved_objective": max_objective_error,
            "saved_gradient": max_gradient_error,
            "recomputed_candidate_utility": max_utility_error,
            "bootstrap_ci": float(np.max(np.abs(ci - [low, high]))),
        },
        "primary_four_distance": {
            **primary_summary, "paired_date_bootstrap_ci95": [float(ci[0]), float(ci[1])],
            "defined_bootstrap_draws": int(defined.sum()), "primary_gate_pass": bool(gate),
        },
        "all_distance": full_summary,
        "k5_coverage": {"primary_four_distance": k5_prim, "all_distances": k5_all},
        "interpretation": "The fixed selector misses its preregistered primary gate; retain F1_STYLE6 and do not treat this retrospective comparison as promotion evidence.",
    }
    outpath = OUT / "FIT_REVIEW.json"
    require(not outpath.is_symlink() and outpath.resolve(strict=False).is_relative_to(REVIEW),
            "unsafe FIT_REVIEW.json path")
    outpath.write_text(json.dumps(fit_findings, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                       encoding="utf-8")
    return fit_findings


if __name__ == "__main__":
    try:
        result = run()
    except (ReviewError, KeyError, ValueError, OSError) as exc:
        raise SystemExit(f"FIT REVIEW FAILED: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))

"""Fit the pre-registered three-fold F1_STYLE6 axis selector after approval.

Reads only hash-locked local artifacts, runs exactly three selector fits, and
writes the fixed outputs in this study folder. It has no database or network
access. ROOT_FIT_APPROVAL.json must bind this exact code and frozen inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

import preflight as source_preflight


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
OUT = STUDY / "outputs"
CODE = STUDY / "fit_selector.py"
PLAN = STUDY / "PLAN.md"
PREFLIGHT = OUT / "PREFLIGHT.json"
APPROVAL = OUT / "ROOT_FIT_APPROVAL.json"

FEATURES_REL = "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BASELINE_REL = "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
HIST_OUT = "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs"
STYLE_OUT = "jeju/research/20261010_style_history_ablation_v1/outputs"
BOOTSTRAP_REL = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"

BASIS = (
    "score_rank", "score_z", "log_observed_starts", "log_days_since_start",
    "days_since_start_missing", "log_same_starts", "log_same_valid_times",
    "log_days_since_same", "days_since_same_missing", "mean5_rank_fraction",
    "mean5_rank_fraction_missing",
)
YEARS = (2024, 2025, 2026)
PRIMARY_DISTANCES = (900, 1000, 1110, 1200)
EXPECTED = {
    2024: (2019, 2023, 25278, 2492, 7476, 2106, 4212, "2023-12-30", 6329, 637),
    2025: (2019, 2024, 31607, 3129, 9387, 2645, 5290, "2024-12-28", 6410, 654),
    2026: (2019, 2025, 38017, 3783, 11349, 3205, 6410, "2025-12-27", 4673, 488),
}
OUTPUT_NAMES = (
    "model_2024.json", "model_2025.json", "model_2026.json",
    "candidate_predictions.parquet", "race_choices.parquet", "REPORT.json",
    "bootstrap_draws.parquet", "FIT_RECEIPT.json",
)


class FitError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise FitError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_gate() -> tuple[dict[str, str], str, str, dict[str, Any], str]:
    require(OUT.is_dir() and not OUT.is_symlink(), "outputs directory is missing or symlinked")
    require(not APPROVAL.is_symlink() and APPROVAL.is_file(), "root fit approval is missing or symlinked")
    for name in OUTPUT_NAMES:
        path = OUT / name
        require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {name}")

    # Reuse the source-only validator; run() is deliberately never called here.
    source_hashes, lock_hash = source_preflight.verify_source_lock()
    preflight_path = source_preflight.checked_study_file("outputs/PREFLIGHT.json")
    preflight_hash = sha256(preflight_path)
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    require(preflight.get("status") == "PASS", "source preflight did not pass")
    require(preflight.get("scope") == "source_contract_only_before_selector_fit", "preflight scope changed")
    require(preflight.get("source_lock_sha256") == lock_hash, "preflight source-lock hash mismatch")
    require(preflight.get("source_hashes") == source_hashes, "preflight source hashes mismatch")
    for key in ("model_fit_performed", "selector_predictions_generated", "axis_hit_metrics_computed",
                "outcome_performance_metrics_computed"):
        require(preflight.get(key) is False, f"preflight must remain source-only: {key}")

    code_hash = sha256(CODE)
    approval = json.loads(APPROVAL.read_text(encoding="utf-8"))
    require(approval.get("approved") is True and approval.get("approved_fits") == 3,
            "approval must authorize exactly three fits")
    require(approval.get("fit_code_sha256") == code_hash, "approval fit-code hash mismatch")
    require(approval.get("plan_sha256") == sha256(PLAN), "approval plan hash mismatch")
    require(approval.get("preflight_sha256") == preflight_hash, "approval preflight hash mismatch")
    require(approval.get("source_lock_sha256") == lock_hash, "approval source-lock hash mismatch")
    if "approved_by" in approval:
        require(approval["approved_by"] == "root", "approval identity mismatch")
    return source_hashes, lock_hash, preflight_hash, preflight, code_hash


def provider_record(year: int, role: str, source_hashes: dict[str, str]) -> dict[str, Any]:
    fold = year + 1 if role == "calibration_raw_score_only" else year
    base = HIST_OUT if role == "calibration_raw_score_only" and fold <= 2023 else STYLE_OUT
    filename = "calibration_scores.parquet" if role == "calibration_raw_score_only" else "evaluation_scores.parquet"
    score_rel = f"{base}/F1_STYLE6_{fold}/{filename}"
    meta_rel = f"{base}/F1_STYLE6_{fold}/meta.json"
    meta = json.loads(source_preflight.checked_source(meta_rel).read_text(encoding="utf-8"))
    return {
        "race_year": year,
        "provider_fold": fold,
        "provider_role": role,
        "source_path": score_rel,
        "source_sha256": source_hashes[score_rel],
        "meta_path": meta_rel,
        "meta_sha256": source_hashes[meta_rel],
        "provider_refit_max": meta["refit_max"],
    }


def verify_inputs(source_hashes: dict[str, str], preflight: dict[str, Any]):
    features = pd.read_parquet(source_preflight.checked_source(FEATURES_REL))
    baseline = pd.read_parquet(source_preflight.checked_source(BASELINE_REL))
    hist = source_preflight.validate_historical_receipt(source_hashes)
    historical_records, train_scores = source_preflight.verify_oos_sources(features, hist)
    eval_records = source_preflight.validate_eval_sources(features, baseline)
    schedule_record = source_preflight.validate_schedule(features)
    require(historical_records == preflight["historical_oos_providers"], "historical preflight receipt changed")
    require(eval_records == preflight["frozen_evaluation_providers"], "evaluation preflight receipt changed")
    require(schedule_record == preflight["date_bootstrap"], "bootstrap preflight receipt changed")
    records = {
        ("calibration_raw_score_only", year): provider_record(year, "calibration_raw_score_only", source_hashes)
        for year in range(2019, 2026)
    }
    records.update({
        ("evaluation_raw_score_only", year): provider_record(year, "evaluation_raw_score_only", source_hashes)
        for year in YEARS
    })
    return features, baseline, train_scores, records


def derive_roster(frame: pd.DataFrame, raw_score: np.ndarray, p_top3: np.ndarray | None = None,
                  y: np.ndarray | None = None) -> pd.DataFrame:
    data = frame.reset_index(drop=True).copy()
    data["base_score"] = np.asarray(raw_score, dtype=float)
    require(len(data) == len(raw_score) and np.isfinite(data["base_score"]).all(), "invalid raw scores")
    if p_top3 is not None:
        data["base_p"] = np.asarray(p_top3, dtype=float)
        require(np.isfinite(data["base_p"]).all(), "non-finite frozen p_top3")
    data["y"] = np.asarray(y, dtype=np.int8) if y is not None else data["finish_position"].le(3).astype(np.int8)
    data = data.sort_values(["race_id", "base_score", "horse_number"],
                            ascending=[True, False, True], kind="mergesort").reset_index(drop=True)
    data["score_rank"] = data.groupby("race_id", sort=False).cumcount().add(1)
    grouped = data.groupby("race_id", sort=False)["base_score"]
    mean = grouped.transform("mean").to_numpy(dtype=float)
    sd = grouped.transform(lambda values: values.std(ddof=0)).to_numpy(dtype=float)
    data["score_z"] = np.divide(data["base_score"].to_numpy(dtype=float) - mean, sd,
                                out=np.zeros(len(data), dtype=float), where=sd > 0.0)

    for col in ("observed_starts", "same_starts", "same_valid_times"):
        values = pd.to_numeric(data[col], errors="coerce").to_numpy(dtype=float)
        require(np.isfinite(values).all() and (values >= 0).all(), f"invalid support feature {col}")
        dest = {"observed_starts": "log_observed_starts", "same_starts": "log_same_starts",
                "same_valid_times": "log_same_valid_times"}[col]
        data[dest] = np.log1p(values)
    for col, dest, flag in (
        ("days_since_start", "log_days_since_start", "days_since_start_missing"),
        ("days_since_same", "log_days_since_same", "days_since_same_missing"),
    ):
        values = pd.to_numeric(data[col], errors="coerce").to_numpy(dtype=float)
        missing = np.isnan(values)
        require(np.isfinite(values[~missing]).all() and (values[~missing] >= 0).all(), f"invalid {col}")
        data[flag] = missing.astype(float)
        data[dest] = np.log1p(np.where(missing, 0.0, values))
    values = pd.to_numeric(data["mean5_rank_fraction"], errors="coerce").to_numpy(dtype=float)
    missing = np.isnan(values)
    require(np.isfinite(values[~missing]).all(), "non-finite mean5_rank_fraction")
    data["mean5_rank_fraction_missing"] = missing.astype(float)
    data["mean5_rank_fraction"] = np.where(missing, 0.0, values)
    require(np.isfinite(data.loc[:, BASIS].to_numpy(dtype=float)).all(), "non-finite derived basis")
    return data


def fit_fold(year: int, features: pd.DataFrame, baseline: pd.DataFrame,
             train_scores: dict[int, pd.Series], providers: dict[int, dict[str, Any]],
             source_hashes: dict[str, str], lock_hash: str, preflight: dict[str, Any]):
    ymin, ymax, nr, races, nc, rmix_expected, npair_expected, last_date, eval_n, eval_races = EXPECTED[year]
    train = features.loc[features["year"].between(ymin, ymax)].copy()
    scores = np.full(len(train), np.nan)
    for label_year in range(ymin, ymax + 1):
        mask = train["year"].eq(label_year).to_numpy()
        aligned = train_scores[label_year].reindex(train.loc[mask, "api_record_id"])
        require(aligned.notna().all(), f"training score coverage mismatch: {label_year}")
        scores[mask] = aligned.to_numpy(dtype=float)
    train_full = derive_roster(train, scores)
    candidates = train_full.loc[train_full["score_rank"].le(3)].copy().reset_index(drop=True)
    require((len(train), train["race_id"].nunique(), len(candidates)) == (nr, races, nc),
            f"training window count mismatch: {year}")
    require(str(pd.to_datetime(train["race_date"], errors="raise").max().date()) == last_date,
            f"training label end mismatch: {year}")
    receipt_window = next(item for item in preflight["selector_windows"] if item["evaluation_year"] == year)
    require(receipt_window["candidate_fit_rows"] == nc and
            receipt_window["informative_training_races_R_mix"] == rmix_expected and
            receipt_window["informative_pair_rows"] == npair_expected,
            f"preflight training counts changed: {year}")

    raw = candidates.loc[:, BASIS].to_numpy(dtype=float)
    mean, sd = raw.mean(axis=0), raw.std(axis=0, ddof=0)
    zero_sd = sd == 0.0
    scale = np.where(zero_sd, 1.0, sd)
    z = (raw - mean) / scale
    pairs = []
    mixed_count = 0
    for _, group in candidates.groupby("race_id", sort=False):
        idx = group.index.to_numpy()
        y = group["y"].to_numpy(dtype=np.int8)
        pos, neg = idx[y == 1], idx[y == 0]
        if len(pos) and len(neg):
            require(len(pos) * len(neg) == 2, "mixed K3 race did not produce two pairs")
            mixed_count += 1
            pairs.extend(z[i] - z[j] for i in pos for j in neg)
    pair_matrix = np.vstack(pairs)
    require(mixed_count == rmix_expected and len(pair_matrix) == npair_expected,
            f"informative pair counts changed: {year}")

    pair_weight = 1.0 / len(pair_matrix)
    def objective(beta: np.ndarray):
        margin = pair_matrix @ beta
        loss = pair_weight * np.logaddexp(0.0, -margin).sum() + 0.5 * beta.dot(beta)
        grad = beta - pair_weight * (expit(-margin) @ pair_matrix)
        return float(loss), grad

    result = minimize(objective, np.zeros(len(BASIS)), jac=True, method="L-BFGS-B",
                       options={"maxiter": 1000, "ftol": 1e-12, "gtol": 1e-8})
    beta = np.asarray(result.x, dtype=float)
    loss, grad = objective(beta)
    grad_max = float(np.max(np.abs(grad)))
    require(result.success and np.isfinite(beta).all() and math.isfinite(loss) and np.isfinite(grad).all()
            and grad_max <= 1e-6, f"optimizer acceptance failed for {year}: {result.message}; grad={grad_max}")

    ev = features.loc[features["year"].eq(year)].copy()
    base = baseline.loc[baseline["year"].eq(year)].set_index("api_record_id").reindex(ev["api_record_id"])
    require(len(ev) == eval_n and base["race_id"].notna().all(), f"evaluation roster changed: {year}")
    for col in ("race_id", "year", "horse_id", "horse_number", "distance_m", "field_n", "observed_starts"):
        require(np.array_equal(ev[col].to_numpy(), base[col].to_numpy()), f"baseline identity mismatch: {year} {col}")
    y = base["y"].to_numpy(dtype=np.int8)
    require(np.array_equal(y, ev["finish_position"].le(3).to_numpy(dtype=np.int8)), f"evaluation labels changed: {year}")
    ev_full = derive_roster(ev, base["score"].to_numpy(dtype=float), base["p_top3"].to_numpy(dtype=float), y)
    ev_candidates = ev_full.loc[ev_full["score_rank"].le(3)].copy().reset_index(drop=True)
    ev_candidates["utility"] = ((ev_candidates.loc[:, BASIS].to_numpy(dtype=float) - mean) / scale) @ beta
    ev_candidates["selector_chosen"] = False
    ev_candidates["baseline_chosen"] = ev_candidates["score_rank"].eq(1)
    provider = providers[("evaluation_raw_score_only", year)]
    for col, value in (("provider_fold", provider["provider_fold"]), ("provider_role", provider["provider_role"]),
                       ("provider_source_path", provider["source_path"]), ("provider_sha256", provider["source_sha256"]),
                       ("provider_refit_max", provider["provider_refit_max"])):
        ev_candidates[col] = value

    choices = []
    for race_id, group in ev_candidates.groupby("race_id", sort=False):
        chosen_idx = group["utility"].idxmax()  # ties keep baseline score rank, then horse number
        ev_candidates.loc[chosen_idx, "selector_chosen"] = True
        old, new = group.loc[group["score_rank"].eq(1)].iloc[0], ev_candidates.loc[chosen_idx]
        old_hit, new_hit = bool(old["y"]), bool(new["y"])
        outcome = ("both" if old_hit and new_hit else "baseline_only" if old_hit else
                   "selector_only" if new_hit else "neither")
        choices.append({
            "race_id": race_id, "year": int(old["year"]), "race_date": str(old["race_date"]),
            "distance_m": int(old["distance_m"]), "field_n": int(old["field_n"]),
            "baseline_axis_api_record_id": int(old["api_record_id"]),
            "baseline_axis_horse_id": str(old["horse_id"]),
            "baseline_axis_horse_number": int(old["horse_number"]),
            "baseline_score": float(old["base_score"]), "baseline_p_top3": float(old["base_p"]),
            "baseline_observed_starts": int(old["observed_starts"]), "baseline_hit": old_hit,
            "selector_axis_api_record_id": int(new["api_record_id"]),
            "selector_axis_horse_id": str(new["horse_id"]),
            "selector_axis_horse_number": int(new["horse_number"]),
            "selector_utility": float(new["utility"]), "selector_hit": new_hit,
            "axis_changed": bool(old["api_record_id"] != new["api_record_id"]), "outcome": outcome,
        })
    race_choices = pd.DataFrame(choices)
    require(len(race_choices) == eval_races and len(ev_candidates) == 3 * eval_races,
            f"evaluation race/candidate counts changed: {year}")

    model = {
        "status": "FIT_PASS", "model_name": "F1_STYLE6_K3_pairwise_logistic_axis_selector",
        "evaluation_year": year, "training_label_year_min": ymin, "training_label_year_max": ymax,
        "training_max_label_date": last_date, "candidate_count": 3, "basis_order": list(BASIS),
        "standardization_ddof": 0,
        "mean_by_feature": {k: float(mean[i]) for i, k in enumerate(BASIS)},
        "scale_by_feature": {k: float(scale[i]) for i, k in enumerate(BASIS)},
        "zero_variance_features": [k for i, k in enumerate(BASIS) if zero_sd[i]],
        "coefficients": {k: float(beta[i]) for i, k in enumerate(BASIS)},
        "objective": "race_mean_pairwise_logistic + 0.5*||beta||^2; lambda=1; no intercept",
        "optimizer": {"method": "L-BFGS-B", "initial": "zero", "maxiter": 1000,
                      "ftol": 1e-12, "gtol": 1e-8, "success": bool(result.success),
                      "status": int(result.status), "message": str(result.message),
                      "iterations": int(result.nit), "function_evaluations": int(result.nfev),
                      "objective_value": float(loss), "gradient": {k: float(grad[i]) for i, k in enumerate(BASIS)},
                      "gradient_max_abs": grad_max},
        "training_counts": {"source_runners": nr, "source_races": races, "candidate_rows": nc,
                            "informative_races_R_mix": mixed_count, "informative_pair_rows": len(pair_matrix)},
        "training_score_providers": [providers[("calibration_raw_score_only", yr)] for yr in range(ymin, ymax + 1)],
        "evaluation_score_provider": provider, "source_lock_sha256": lock_hash,
        "source_hashes": source_hashes, "utility_is_probability": False,
        "baseline_p_top3_used_as_feature": False,
    }
    columns = ["api_record_id", "race_id", "year", "horse_id", "horse_number", "distance_m",
               "base_score", "base_p", "score_rank", "utility", "y", "selector_chosen",
               "baseline_chosen", "provider_fold", "provider_role", "provider_source_path",
               "provider_sha256", "provider_refit_max"]
    return model, ev_candidates[columns].copy(), race_choices, ev_full


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    n = len(frame)
    require(n > 0, "empty metric cohort")
    base = int(frame["baseline_hit"].sum())
    selected = int(frame["selector_hit"].sum())
    counts = {key: int((frame["outcome"] == key).sum()) for key in
              ("both", "baseline_only", "selector_only", "neither")}
    return {
        "races": int(n), "baseline_top3_hits": base, "selector_top3_hits": selected,
        "baseline_top3_rate": base / n, "selector_top3_rate": selected / n,
        "selector_minus_baseline": (selected - base) / n,
        "axis_changed_races": int(frame["axis_changed"].sum()),
        "axis_changed_rate": float(frame["axis_changed"].mean()),
        "new_selector_hits": counts["selector_only"], "lost_baseline_hits": counts["baseline_only"],
        "both_hit": counts["both"], "neither_hit": counts["neither"], "outcome_counts": counts,
    }


def group_summaries(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    return {str(value): summarize(group) for value, group in frame.groupby(column, sort=True)}


def bootstrap(races: pd.DataFrame, source_hashes: dict[str, str], preflight: dict[str, Any]):
    schedule_path = source_preflight.checked_source(BOOTSTRAP_REL)
    schedule = np.load(schedule_path, allow_pickle=False)
    require(schedule.shape == (2000, 269) and schedule.dtype == np.int32, "frozen schedule shape/type changed")
    require(source_hashes[BOOTSTRAP_REL] == "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
            "frozen schedule hash changed")
    dates = sorted(pd.to_datetime(races["race_date"], errors="raise").dt.strftime("%Y-%m-%d").unique())
    inventory = hashlib.sha256("\n".join(dates).encode()).hexdigest()
    frozen = preflight["date_bootstrap"]
    require(len(dates) == 269 and inventory == frozen["date_inventory_sha256"], "evaluation date inventory changed")
    require(np.array_equal(schedule, np.random.default_rng(20261011).integers(
        0, len(dates), size=(2000, len(dates)), endpoint=False, dtype=np.int32)),
        "frozen schedule differs from recipe")

    primary = races.loc[races["distance_m"].isin(PRIMARY_DISTANCES)].copy()
    daily = primary.groupby("race_date", sort=False).agg(
        n=("race_id", "size"), base=("baseline_hit", "sum"), selected=("selector_hit", "sum"))
    daily = daily.reindex(dates, fill_value=0)
    den = daily["n"].to_numpy(dtype=np.int64)[schedule].sum(axis=1)
    base = daily["base"].to_numpy(dtype=np.int64)[schedule].sum(axis=1)
    selected = daily["selected"].to_numpy(dtype=np.int64)[schedule].sum(axis=1)
    defined = den > 0
    delta = np.full(len(schedule), np.nan)
    delta[defined] = (selected[defined] - base[defined]) / den[defined]
    require(defined.any(), "all paired bootstrap draws have zero denominator")
    low, high = np.quantile(delta[defined], [0.025, 0.975])
    draws = pd.DataFrame({"draw_id": np.arange(len(schedule), dtype=np.int32), "primary_races": den,
                          "baseline_hits": base, "selector_hits": selected, "defined": defined,
                          "selector_minus_baseline": delta})
    info = {"schedule_path": BOOTSTRAP_REL, "schedule_sha256": source_hashes[BOOTSTRAP_REL],
            "draws": len(schedule), "dates_per_draw": schedule.shape[1],
            "date_inventory_sha256": inventory, "defined_draws": int(defined.sum()),
            "undefined_draws": int((~defined).sum()), "paired_delta_ci95_percentile": [float(low), float(high)]}
    return draws, info


def make_report(races: pd.DataFrame, eval_full: dict[int, pd.DataFrame], bootstrap_info: dict[str, Any]):
    primary = races.loc[races["distance_m"].isin(PRIMARY_DISTANCES)].copy()
    require(len(primary) == 1503 and len(races) == 1779, "evaluation cohort count changed")
    primary_summary = summarize(primary)
    low, high = bootstrap_info["paired_delta_ci95_percentile"]
    primary_summary.update({"paired_date_bootstrap_ci95": [low, high],
                           "paired_date_bootstrap_defined_draws": bootstrap_info["defined_draws"],
                           "primary_gate_pass": bool(primary_summary["selector_minus_baseline"] > 0 and low > 0)})

    k5_frames = []
    for year, frame in eval_full.items():
        hits = frame.loc[frame["score_rank"].le(5)].groupby("race_id", sort=False)["y"].max().astype(bool)
        distances = frame.groupby("race_id", sort=False)["distance_m"].first()
        k5_frames.append(pd.DataFrame({"year": year, "distance_m": distances, "covered": hits}))
    k5 = pd.concat(k5_frames)
    k5_primary = k5.loc[k5["distance_m"].isin(PRIMARY_DISTANCES)]
    def coverage(frame: pd.DataFrame):
        return {"races": int(len(frame)), "covered_races": int(frame["covered"].sum()),
                "coverage_rate": float(frame["covered"].mean())}

    careers = {}
    starts = primary["baseline_observed_starts"]
    for name, mask in (("0", starts.eq(0)), ("1-4", starts.ge(1) & starts.le(4)), ("5+", starts.ge(5))):
        careers[name] = summarize(primary.loc[mask])
    return {
        "status": "EVALUATION_COMPLETE",
        "interpretation": "retrospective development-period comparison; not independent future validation, profitability, causal effect, or promotion evidence",
        "primary_four_distance_cohort": primary_summary,
        "all_distance_cohort": summarize(races),
        "primary_by_year": group_summaries(primary, "year"),
        "all_distance_by_year": group_summaries(races, "year"),
        "primary_by_distance_m": group_summaries(primary, "distance_m"),
        "all_distance_by_distance_m": group_summaries(races, "distance_m"),
        "primary_by_baseline_axis_career": careers,
        "k5_coverage_diagnostic": {"definition": "share of races with an actual Top3 horse in baseline raw-score top five; no K5 selector",
                                   "primary_four_distance": coverage(k5_primary), "all_distances": coverage(k5),
                                   "primary_by_year": {str(year): coverage(group) for year, group in
                                                       k5_primary.groupby("year", sort=True)}},
        "bootstrap": bootstrap_info,
        "limitations": [
            "The 2024-2026 dates are repeated development data, not a new holdout.",
            "Date bootstrap conditions on the three fitted selectors and excludes training uncertainty.",
            "Training and evaluation F1_STYLE6 scores use different model vintages.",
            "Subgroup results are exploratory and do not replace the primary gate.",
        ],
    }


def write_json(path: Path, value: dict[str, Any]):
    require(not path.is_symlink() and not path.exists() and path.resolve(strict=False).is_relative_to(STUDY),
            f"unsafe or existing output path: {path.name}")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_parquet(path: Path, frame: pd.DataFrame):
    require(not path.is_symlink() and not path.exists() and path.resolve(strict=False).is_relative_to(STUDY),
            f"unsafe or existing output path: {path.name}")
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def run():
    source_hashes, lock_hash, preflight_hash, preflight, code_hash = verify_gate()
    features, baseline, train_scores, providers = verify_inputs(source_hashes, preflight)
    models, candidate_frames, race_frames, eval_full = {}, [], [], {}
    for year in YEARS:
        model, candidates, races, full = fit_fold(year, features, baseline, train_scores,
                                                   providers, source_hashes, lock_hash, preflight)
        models[year] = model
        candidate_frames.append(candidates)
        race_frames.append(races)
        eval_full[year] = full
    candidates = pd.concat(candidate_frames, ignore_index=True)
    races = pd.concat(race_frames, ignore_index=True)
    require(candidates["api_record_id"].is_unique and races["race_id"].is_unique, "duplicate output keys")
    draws, bootstrap_info = bootstrap(races, source_hashes, preflight)
    report = make_report(races, eval_full, bootstrap_info)
    report.update({"source_lock_sha256": lock_hash, "preflight_sha256": preflight_hash,
                   "fit_code_sha256": code_hash, "root_approval_sha256": sha256(APPROVAL),
                   "models": {str(y): {"training_counts": models[y]["training_counts"],
                                        "objective_value": models[y]["optimizer"]["objective_value"],
                                        "gradient_max_abs": models[y]["optimizer"]["gradient_max_abs"]}
                              for y in YEARS}})

    model_paths = {year: OUT / f"model_{year}.json" for year in YEARS}
    candidate_path, race_path = OUT / "candidate_predictions.parquet", OUT / "race_choices.parquet"
    report_path, draws_path, receipt_path = OUT / "REPORT.json", OUT / "bootstrap_draws.parquet", OUT / "FIT_RECEIPT.json"
    for year, path in model_paths.items():
        write_json(path, models[year])
    write_parquet(candidate_path, candidates)
    write_parquet(race_path, races)
    write_json(report_path, report)
    write_parquet(draws_path, draws)
    receipt = {
        "status": "PASS", "scope": "three_fixed_expanding_fits_and_prespecified_evaluation",
        "fits_completed": 3, "evaluation_years": list(YEARS), "fit_code_sha256": code_hash,
        "plan_sha256": sha256(PLAN), "preflight_sha256": preflight_hash,
        "source_lock_sha256": lock_hash, "root_approval_sha256": sha256(APPROVAL),
        "source_hashes": source_hashes,
        "output_sha256": {p.name: sha256(p) for p in [*model_paths.values(), candidate_path, race_path, report_path, draws_path]},
        "primary_gate_pass": report["primary_four_distance_cohort"]["primary_gate_pass"],
        "primary_summary": report["primary_four_distance_cohort"],
        "all_distance_summary": report["all_distance_cohort"],
        "fit_once_per_evaluation_year": True, "database_or_network_access": False,
        "existing_model_or_registry_modified": False,
    }
    write_json(receipt_path, receipt)
    return receipt


if __name__ == "__main__":
    try:
        result = run()
    except (FitError, source_preflight.PreflightError) as exc:
        raise SystemExit(f"FIT BLOCKED: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))

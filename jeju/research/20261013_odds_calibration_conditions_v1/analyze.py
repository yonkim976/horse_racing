#!/usr/bin/env python3
"""Read-only post-race calibration and condition diagnostics for Jeju QPL pairs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261013_odds_calibration_conditions_v1"
RESEARCH = ROOT / "jeju/research"

PAIR_REL = Path("20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet")
PAIR_RECEIPT_REL = Path("20261012_pair_jockey_id_v1/outputs/PREDICTION_RECEIPT.json")
PAIR_MANIFEST_REL = Path("20261012_pair_jockey_id_v1/ARTIFACT_MANIFEST.json")
PAIR_POLICY_REL = Path("20261012_pair_jockey_id_v1/pair_jockey_id_report.py")
RACE_ROWS_REL = Path("20261013_postrace_ev_exploration_v1/race_rows.csv")
POST_SOURCE_REL = Path("20261013_postrace_ev_exploration_v1/SOURCE_HASHES.json")
POST_REVIEW_REL = Path("20261013_postrace_ev_exploration_v1/ROOT_REVIEW.json")
POST_REPORT_REL = Path("20261013_postrace_ev_exploration_v1/REPORT.json")
FEATURE_REL = Path("20261010_style_history_ablation_v1/outputs/features.parquet")
STYLE_MANIFEST_REL = Path("20261010_style_history_ablation_v1/ARTIFACT_MANIFEST.json")
STYLE_FINAL_REL = Path("20261010_style_history_ablation_v1/outputs/final_verification.json")
SCORE25_REL = Path("20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/evaluation_scores.parquet")
SCORE26_REL = Path("20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet")
BOOT_REL = Path("20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy")
BOOT_RECEIPT_REL = Path("20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json")

EXPECTED = {
    PAIR_REL: "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6",
    RACE_ROWS_REL: "4fc2e924dcf4f987c22962977d42dd83a786bebc2f70606bc565bd97d2869198",
    FEATURE_REL: "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    SCORE25_REL: "45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12",
    SCORE26_REL: "0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a",
    BOOT_REL: "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
}

POLICIES = {
    "jockey_id_candidate": {
        "flag": "selected_jockey_id_candidate",
        "p_col": "jockey_id_candidate_calibrated_probability",
        "race_selector": "jockey_id_candidate",
        "role": "primary",
    },
    "jockey_basic_candidate": {
        "flag": "selected_jockey_basic_candidate",
        "p_col": "candidate_calibrated_probability",
        "race_selector": "jockey_basic_candidate",
        "role": "comparator",
    },
}

PERIODS = ["all", "2025", "2026_partial"]
ODDS_BANDS = ["[1,2)", "[2,3)", "[3,5)", "[5,10)", "[10,inf)"]
PROB_BANDS = ["[0,.15)", "[.15,.20)", "[.20,.30)", "[.30,.40)", "[.40,1]"]
SMALL_N = 30
LIMITED_N = 80


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_path(rel: Path) -> Path:
    return RESEARCH / rel


def verify_inputs() -> tuple[dict, np.ndarray, dict]:
    source_records = {}
    for rel, expected in EXPECTED.items():
        path = repo_path(rel)
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"Locked source hash mismatch: {rel}: {actual}")
        source_records[str(Path("jeju/research") / rel)] = {
            "sha256": actual,
            "bytes": path.stat().st_size,
        }

    pair_receipt_path = repo_path(PAIR_RECEIPT_REL)
    pair_receipt = load_json(pair_receipt_path)
    if pair_receipt.get("status") != "PASS":
        raise ValueError("Pair prediction receipt is not PASS")
    if pair_receipt.get("pair_predictions_sha256") != EXPECTED[PAIR_REL]:
        raise ValueError("Pair prediction receipt does not lock the requested parquet")

    pair_manifest_path = repo_path(PAIR_MANIFEST_REL)
    pair_manifest = load_json(pair_manifest_path)
    locked_sources = pair_manifest.get("external_sources", {})
    for rel, expected in [(FEATURE_REL, EXPECTED[FEATURE_REL]),
                          (SCORE25_REL, EXPECTED[SCORE25_REL]),
                          (SCORE26_REL, EXPECTED[SCORE26_REL])]:
        source_key = str(Path("jeju/research") / rel)
        if locked_sources.get(source_key, {}).get("sha256") != expected:
            raise ValueError(f"Pair artifact manifest does not lock {rel}")

    post_source_path = repo_path(POST_SOURCE_REL)
    post_source = load_json(post_source_path)
    post_review_path = repo_path(POST_REVIEW_REL)
    post_review = load_json(post_review_path)
    if post_review.get("status") != "PASS":
        raise ValueError("Verified post-race price review is not PASS")
    if post_source.get("outputs_sha256", {}).get("race_rows.csv") != EXPECTED[RACE_ROWS_REL]:
        raise ValueError("Post-race source hash chain does not lock race_rows.csv")
    if post_review.get("reviewed_output_sha256", {}).get("race_rows.csv") != EXPECTED[RACE_ROWS_REL]:
        raise ValueError("Post-race root review does not verify race_rows.csv")
    report_hash = sha256(repo_path(POST_REPORT_REL))
    if post_review.get("report_sha256") != report_hash:
        raise ValueError("Post-race review does not verify its report")

    for year, rel in [(2025, SCORE25_REL), (2026, SCORE26_REL)]:
        receipt_item = pair_receipt.get("evaluation_score_sources", {}).get(str(year), {})
        if receipt_item.get("score_sha256") != EXPECTED[rel]:
            raise ValueError(f"Pair prediction receipt does not lock the {year} score file")

    schedule = np.load(repo_path(BOOT_REL), allow_pickle=False)
    schedule_receipt_path = repo_path(BOOT_RECEIPT_REL)
    schedule_receipt = load_json(schedule_receipt_path)
    if (schedule.shape != (2000, 269) or schedule.dtype != np.int32
            or schedule_receipt.get("status") != "FROZEN_BEFORE_EVALUATION_METRICS"
            or schedule_receipt.get("schedule_sha256") != EXPECTED[BOOT_REL]):
        raise ValueError("Fixed date bootstrap schedule does not match its receipt")

    evidence = {
        "pair_receipt": {"path": str(Path("jeju/research") / PAIR_RECEIPT_REL),
                         "sha256": sha256(pair_receipt_path)},
        "pair_manifest": {"path": str(Path("jeju/research") / PAIR_MANIFEST_REL),
                          "sha256": sha256(pair_manifest_path)},
        "pair_policy_source": {"path": str(Path("jeju/research") / PAIR_POLICY_REL),
                               "sha256": sha256(repo_path(PAIR_POLICY_REL))},
        "postrace_source_hashes": {"path": str(Path("jeju/research") / POST_SOURCE_REL),
                                   "sha256": sha256(post_source_path)},
        "postrace_root_review": {"path": str(Path("jeju/research") / POST_REVIEW_REL),
                                 "sha256": sha256(post_review_path)},
        "postrace_report": {"path": str(Path("jeju/research") / POST_REPORT_REL),
                            "sha256": report_hash},
        "style_artifact_manifest": {"path": str(Path("jeju/research") / STYLE_MANIFEST_REL),
                                    "sha256": sha256(repo_path(STYLE_MANIFEST_REL))},
        "style_final_verification": {"path": str(Path("jeju/research") / STYLE_FINAL_REL),
                                     "sha256": sha256(repo_path(STYLE_FINAL_REL))},
        "date_schedule_receipt": {"path": str(Path("jeju/research") / BOOT_RECEIPT_REL),
                                  "sha256": sha256(schedule_receipt_path)},
    }
    return source_records, schedule, {"evidence": evidence, "pair_receipt": pair_receipt,
                                     "post_review": post_review, "schedule_receipt": schedule_receipt}


def pair_key(left: int, right: int) -> str:
    low, high = sorted((int(left), int(right)))
    return f"{low}-{high}"


def odds_band(value: float) -> str | None:
    if not np.isfinite(value) or value <= 0 or value == 9999.9:
        return None
    if value < 2:
        return "[1,2)" if value >= 1 else None
    if value < 3:
        return "[2,3)"
    if value < 5:
        return "[3,5)"
    if value < 10:
        return "[5,10)"
    return "[10,inf)"


def probability_band(value: float) -> str | None:
    if not np.isfinite(value) or value < 0 or value > 1:
        return None
    if value < 0.15:
        return "[0,.15)"
    if value < 0.20:
        return "[.15,.20)"
    if value < 0.30:
        return "[.20,.30)"
    if value < 0.40:
        return "[.30,.40)"
    return "[.40,1]"


def field_group(value: float) -> str:
    if pd.isna(value):
        return "unknown"
    value = int(value)
    if value <= 8:
        return "<=8"
    if value == 9:
        return "9"
    if value == 10:
        return "10"
    return ">=11"


def count_group(value: float, boundaries: list[tuple[int, int | None]], labels: list[str]) -> str:
    if pd.isna(value):
        return "unknown"
    value = int(value)
    for (low, high), label in zip(boundaries, labels):
        if value >= low and (high is None or value <= high):
            return label
    return "unknown"


def distance_label(value: float) -> str:
    if pd.isna(value):
        return "unknown"
    return str(int(value)) if float(value).is_integer() else str(float(value))


def days_group(left: float, right: float) -> str:
    if pd.isna(left) or pd.isna(right):
        return "unknown"
    value = max(float(left), float(right))
    if value <= 14:
        return "<=14"
    if value <= 35:
        return "15-35"
    if value <= 60:
        return "36-60"
    return "61+"


def gap_group(value: float) -> str:
    if not np.isfinite(value):
        return "unknown"
    if value < 0.5:
        return "[0,.5)"
    if value < 1:
        return "[.5,1)"
    return "[1,inf)"


def style_overlap_group(left: float, right: float) -> str:
    if pd.isna(left) or pd.isna(right):
        return "missing"
    if left <= 0.33 and right <= 0.33:
        return "both_low"
    return "observed_other"


def support_status(n: int) -> str:
    if n < SMALL_N:
        return f"small_lt_{SMALL_N}"
    if n < LIMITED_N:
        return f"limited_{SMALL_N}_to_{LIMITED_N - 1}"
    return f"supported_ge_{LIMITED_N}"


def date_bootstrap_ci(frame: pd.DataFrame, date_codes: dict[str, int], schedule: np.ndarray) -> dict:
    empty = {"gap_ci95_low_pp": np.nan, "gap_ci95_high_pp": np.nan,
             "bootstrap_replicates": 0, "bootstrap_zero_denominator_replicates": len(schedule)}
    if frame.empty:
        return empty
    codes = frame["race_date"].map(date_codes).to_numpy(dtype=np.int32)
    n_by_date = np.bincount(codes, minlength=269).astype(np.float64)
    p_by_date = np.bincount(codes, weights=frame["p"].to_numpy(dtype=float), minlength=269)
    hit_by_date = np.bincount(codes, weights=frame["hit"].to_numpy(dtype=float), minlength=269)
    n = n_by_date[schedule].sum(axis=1)
    p_sum = p_by_date[schedule].sum(axis=1)
    hits = hit_by_date[schedule].sum(axis=1)
    valid = n > 0
    if not valid.any():
        return empty
    gaps_pp = 100 * (p_sum[valid] - hits[valid]) / n[valid]
    low, high = np.quantile(gaps_pp, [0.025, 0.975], method="linear")
    return {"gap_ci95_low_pp": float(low), "gap_ci95_high_pp": float(high),
            "bootstrap_replicates": int(valid.sum()),
            "bootstrap_zero_denominator_replicates": int((~valid).sum())}


def metrics(frame: pd.DataFrame, date_codes: dict[str, int] | None = None,
            schedule: np.ndarray | None = None, with_ci: bool = False) -> dict:
    n = len(frame)
    if n == 0:
        base = {
            "n": 0, "hits": 0, "p_sum": 0.0, "p_mean": np.nan,
            "hit_rate_pct": np.nan, "gap_pp": np.nan, "o_e_ratio": np.nan,
            "brier": np.nan, "log_loss": np.nan,
            "both_top3": 0, "exactly_one_top3": 0, "neither_top3": 0,
            "both_top3_pct": np.nan, "exactly_one_top3_pct": np.nan, "neither_top3_pct": np.nan,
        }
        if with_ci:
            base.update(date_bootstrap_ci(frame, date_codes or {}, schedule if schedule is not None else np.zeros((0, 0), dtype=np.int32)))
        return base
    p = frame["p"].to_numpy(dtype=float)
    y = frame["hit"].to_numpy(dtype=float)
    p_clip = np.clip(p, 1e-15, 1 - 1e-15)
    hits = int(y.sum())
    both = int(frame["both_top3"].sum())
    exactly_one = int(frame["exactly_one_top3"].sum())
    neither = int(frame["neither_top3"].sum())
    p_sum = float(p.sum())
    hit_rate = hits / n
    base = {
        "n": n,
        "hits": hits,
        "p_sum": p_sum,
        "p_mean": float(p.mean()),
        "hit_rate_pct": float(100 * hit_rate),
        "gap_pp": float(100 * (p.mean() - hit_rate)),
        "o_e_ratio": float(hits / p_sum) if p_sum > 0 else np.nan,
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(-np.mean(y * np.log(p_clip) + (1 - y) * np.log(1 - p_clip))),
        "both_top3": both,
        "exactly_one_top3": exactly_one,
        "neither_top3": neither,
        "both_top3_pct": float(100 * both / n),
        "exactly_one_top3_pct": float(100 * exactly_one / n),
        "neither_top3_pct": float(100 * neither / n),
    }
    if with_ci:
        base.update(date_bootstrap_ci(frame, date_codes or {}, schedule if schedule is not None else np.zeros((0, 0), dtype=np.int32)))
    return base


def add_summaries(frame: pd.DataFrame, date_codes: dict[str, int], schedule: np.ndarray,
                  group_cols: list[str], with_ci: bool) -> pd.DataFrame:
    rows = []
    for keys, group in frame.groupby(group_cols, sort=True, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_cols, keys))
        row.update(metrics(group, date_codes, schedule, with_ci))
        row["support_status"] = support_status(len(group))
        rows.append(row)
    return pd.DataFrame(rows)


def build_context() -> tuple[pd.DataFrame, dict, list[str]]:
    pair = pd.read_parquet(repo_path(PAIR_REL))
    date_inventory = sorted(pair["race_date"].astype(str).unique().tolist())
    prices = pd.read_csv(repo_path(RACE_ROWS_REL))
    feature = pd.read_parquet(repo_path(FEATURE_REL))
    score25 = pd.read_parquet(repo_path(SCORE25_REL))
    score26 = pd.read_parquet(repo_path(SCORE26_REL))
    scores = pd.concat([score25.assign(year=2025), score26.assign(year=2026)], ignore_index=True)

    pair = pair[pair["evaluation_year"].isin([2025, 2026])].copy()
    if pair[["race_id", "race_date", "evaluation_year", "horse_i", "horse_j"]].isna().any().any():
        raise ValueError("Selected pair source has missing race or horse keys")
    prices = prices[prices["year"].isin([2025, 2026])].copy()
    price_invalid = (~prices["price_valid"].astype(bool)) | (~np.isfinite(prices["final_quote"]))
    invalid_prices_by_selector = prices.assign(_invalid=price_invalid).groupby("selector")["_invalid"].sum().astype(int).to_dict()
    if price_invalid.any():
        prices = prices[~price_invalid].copy()

    feature = feature[feature["year"].isin([2025, 2026])].copy()
    if feature.duplicated(["race_id", "horse_number"]).any():
        raise ValueError("Frozen features contain duplicate race_id + horse_number keys")
    if scores["api_record_id"].duplicated().any() or feature["api_record_id"].duplicated().any():
        raise ValueError("Score or feature api_record_id is not unique")
    feature = feature.merge(scores[["api_record_id", "score"]], on="api_record_id", how="left", validate="one_to_one")
    if feature["score"].isna().any():
        raise ValueError("Some 2025/2026 frozen feature rows have no F1_STYLE6 evaluation score")
    feature["score_rank"] = feature.groupby("race_id")["score"].rank(method="min", ascending=False)
    expected_cutoff = pd.to_datetime(feature["race_date"]) - pd.to_timedelta(2, unit="D")
    if not (pd.to_datetime(feature["history_cutoff"]).to_numpy() == expected_cutoff.to_numpy()).all():
        raise ValueError("Frozen feature history_cutoff is not consistently race_date minus two days")
    latest_history = pd.to_datetime(feature["latest_history_date"], errors="coerce")
    if (latest_history.notna() & (latest_history > pd.to_datetime(feature["history_cutoff"]))).any():
        raise ValueError("A frozen feature has a latest history date after its prediction cutoff")

    runner_cols = ["api_record_id", "horse_id", "finish_position", "grade_raw", "field_n",
                   "observed_starts", "same_valid_times", "days_since_start",
                   "hist_s1f_relpos_mean5", "history_cutoff", "latest_history_date",
                   "score", "score_rank"]
    feat_by_number = feature[["race_id", "horse_number", *runner_cols]].copy()
    all_context = []
    for policy, spec in POLICIES.items():
        selected = pair[pair[spec["flag"]].astype(bool)].copy()
        counts = selected.groupby("evaluation_year")["race_id"].nunique().to_dict()
        if counts != {2025: 654, 2026: 488}:
            raise ValueError(f"Unexpected selected race counts for {policy}: {counts}")
        if selected["race_id"].duplicated().any():
            raise ValueError(f"More than one selected pair per race for {policy}")
        selected["selector"] = policy
        selected = selected.rename(columns={"score_i": "pair_score_i_source", "score_j": "pair_score_j_source"})
        selected["p"] = selected[spec["p_col"]].astype(float)
        selected["pair"] = [pair_key(a, b) for a, b in zip(selected["horse_i"], selected["horse_j"])]
        quote_cols = ["race_id", "pair", "year", "race_date", "p", "final_quote", "ev_proxy",
                      "price_valid", "price_exclusion_reason", "hit", "source_run_id", "source_hash",
                      "api301_page_sha256", "qpl_returns_sha256", "prediction_parquet_sha256"]
        quote_rows = prices[prices["selector"] == spec["race_selector"]][quote_cols].copy()
        selected = selected.merge(quote_rows, on=["race_id", "pair"], how="left", suffixes=("_prediction", "_quote"), validate="one_to_one")
        selected["p"] = selected["p_prediction"].astype(float)
        if not (selected["race_date_prediction"].astype(str).to_numpy() == selected["race_date_quote"].astype(str).to_numpy()).all():
            raise ValueError(f"Prediction and verified price race dates do not match for {policy}")
        selected["race_date"] = selected["race_date_prediction"].astype(str)
        if selected["final_quote"].isna().any() or selected["hit"].isna().any():
            raise ValueError(f"Missing verified price or label after join for {policy}")
        p_diff = np.abs(selected["p"] - selected["p_quote"])
        if (p_diff > 1e-12).any():
            raise ValueError(f"Saved pair probability does not match verified race row for {policy}")
        if not (selected["y_pair"].astype(int).to_numpy() == selected["hit"].astype(int).to_numpy()).all():
            raise ValueError(f"Pair-label mismatch against verified result rows for {policy}")
        if (selected["evaluation_year"].astype(int).to_numpy() != selected["year"].astype(int).to_numpy()).any():
            raise ValueError(f"Evaluation year mismatch for {policy}")
        selected["price_valid"] = selected["price_valid"].astype(bool)
        selected["posthoc_score"] = selected["p"] * selected["final_quote"].astype(float) - 1

        left = feat_by_number.rename(columns={"horse_number": "horse_i", **{c: f"{c}_i" for c in runner_cols}})
        right = feat_by_number.rename(columns={"horse_number": "horse_j", **{c: f"{c}_j" for c in runner_cols}})
        selected = selected.merge(left, on=["race_id", "horse_i"], how="left", validate="many_to_one")
        selected = selected.merge(right, on=["race_id", "horse_j"], how="left", validate="many_to_one")
        if selected["api_record_id_i"].isna().any() or selected["api_record_id_j"].isna().any():
            raise ValueError(f"Official runner features do not match both selected program numbers for {policy}")
        for source_col, score_col in [("pair_score_i_source", "score_i"), ("pair_score_j_source", "score_j")]:
            if (np.abs(selected[source_col].to_numpy(dtype=float) - selected[score_col].to_numpy(dtype=float)) > 1e-12).any():
                raise ValueError(f"Stored pair score does not match the official-id F1_STYLE6 join for {policy}")
        selected["finish_position_i"] = selected["finish_position_i"].astype(int)
        selected["finish_position_j"] = selected["finish_position_j"].astype(int)
        selected["both_top3"] = (selected["finish_position_i"] <= 3) & (selected["finish_position_j"] <= 3)
        selected["exactly_one_top3"] = ((selected["finish_position_i"] <= 3) ^ (selected["finish_position_j"] <= 3))
        selected["neither_top3"] = (selected["finish_position_i"] > 3) & (selected["finish_position_j"] > 3)
        if not (selected["both_top3"].astype(int).to_numpy() == selected["hit"].astype(int).to_numpy()).all():
            raise ValueError(f"Pair hit flag is inconsistent with official finish positions for {policy}")

        selected["distance_condition"] = selected["distance_m"].map(distance_label)
        selected["grade_condition"] = selected["grade_raw_i"].astype(str)
        selected["field_n_condition"] = selected["field_n_i"].map(field_group)
        selected["min_observed_starts"] = selected[["observed_starts_i", "observed_starts_j"]].min(axis=1, skipna=False)
        selected["observed_starts_condition"] = selected["min_observed_starts"].map(
            lambda x: count_group(x, [(0, 0), (1, 2), (3, 9), (10, None)], ["0", "1-2", "3-9", "10+"]))
        selected["min_same_valid_times"] = selected[["same_valid_times_i", "same_valid_times_j"]].min(axis=1, skipna=False)
        selected["same_valid_times_condition"] = selected["min_same_valid_times"].map(
            lambda x: count_group(x, [(0, 0), (1, 2), (3, None)], ["0", "1-2", "3+"]))
        selected["days_since_start_condition"] = [days_group(a, b) for a, b in zip(selected["days_since_start_i"], selected["days_since_start_j"])]
        selected["score_gap_abs"] = np.abs(selected["score_i"] - selected["score_j"])
        selected["score_gap_condition"] = selected["score_gap_abs"].map(gap_group)
        selected["style_overlap_condition"] = [style_overlap_group(a, b) for a, b in zip(selected["hist_s1f_relpos_mean5_i"], selected["hist_s1f_relpos_mean5_j"])]
        selected["weak_score_rank"] = selected[["score_rank_i", "score_rank_j"]].max(axis=1)
        selected["weak_score_rank_group"] = pd.cut(
            selected["weak_score_rank"], [-np.inf, 2, 3, np.inf], labels=["<=2", "3", ">=4"], right=True
        ).astype(str)
        selected["odds_band"] = selected["final_quote"].map(odds_band)
        selected["probability_band"] = selected["p"].map(probability_band)
        if selected[["odds_band", "probability_band"]].isna().any().any():
            raise ValueError(f"Unexpected quote or probability outside locked bands for {policy}")
        all_context.append(selected)

    context = pd.concat(all_context, ignore_index=True)
    if len(context) != 2284 or context["race_id"].nunique() != 1142:
        raise ValueError("Expected 2 selectors × 1,142 races in selected pair context")
    context["year"] = context["evaluation_year"].astype(int)
    context["race_date"] = context["race_date"].astype(str)
    meta = {
        "invalid_price_rows_by_selector": invalid_prices_by_selector,
        "price_rows_after_validity_filter": int(len(prices)),
        "score_rows": int(len(scores)),
        "feature_rows_2025_2026": int(len(feature)),
        "feature_races_2025_2026": int(feature["race_id"].nunique()),
        "feature_pair_runner_matches": int(2 * len(context)),
        "selected_rows": int(len(context)),
        "selected_races_per_policy": context.groupby("selector")["race_id"].nunique().astype(int).to_dict(),
        "odds_min": float(context["final_quote"].min()),
        "odds_max": float(context["final_quote"].max()),
        "probability_min": float(context["p"].min()),
        "probability_max": float(context["p"].max()),
        "history_cutoff_rule": "race_date minus two calendar days; verified for every joined 2025/2026 runner row",
        "latest_history_date_rule": "no observed latest_history_date is after history_cutoff; verified for every 2025/2026 frozen feature row",
        "horse_number_mapping": "pair horse_i/horse_j program numbers joined to frozen features by race_id + horse_number, then score by api_record_id",
        "selected_runner_field_missing_counts": {
            "observed_starts": int(context[["observed_starts_i", "observed_starts_j"]].isna().to_numpy().sum()),
            "same_valid_times": int(context[["same_valid_times_i", "same_valid_times_j"]].isna().to_numpy().sum()),
            "days_since_start": int(context[["days_since_start_i", "days_since_start_j"]].isna().to_numpy().sum()),
            "hist_s1f_relpos_mean5": int(context[["hist_s1f_relpos_mean5_i", "hist_s1f_relpos_mean5_j"]].isna().to_numpy().sum()),
            "latest_history_date": int(context[["latest_history_date_i", "latest_history_date_j"]].isna().to_numpy().sum()),
        },
    }
    return context, meta, date_inventory


def build_tables(context: pd.DataFrame, schedule: np.ndarray, date_inventory: list[str]) -> dict[str, pd.DataFrame]:
    dates = date_inventory
    if len(dates) != 269:
        raise ValueError(f"Expected original 269-date inventory, got {len(dates)}")
    date_codes = {date: i for i, date in enumerate(dates)}
    if schedule.min() < 0 or schedule.max() >= len(dates):
        raise ValueError("Fixed date schedule contains an index outside the date inventory")

    context = context.copy()
    context["posthoc_score"] = context["p"] * context["final_quote"] - 1
    context["condition_family"] = ""
    condition_cols = {
        "distance": "distance_condition",
        "grade_raw": "grade_condition",
        "field_n": "field_n_condition",
        "min_observed_starts": "observed_starts_condition",
        "min_same_valid_times": "same_valid_times_condition",
        "max_days_since_start": "days_since_start_condition",
        "f1_score_gap": "score_gap_condition",
        "front_history_overlap": "style_overlap_condition",
    }

    def in_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
        if period == "all":
            return df
        year = int(period[:4])
        return df[df["year"] == year]

    # Primary odds table includes the overall reference row, all three periods, and outcome diagnostics.
    odds_rows = []
    for selector in POLICIES:
        selected = context[context["selector"] == selector]
        for period in PERIODS:
            subset = in_period(selected, period)
            for band in ["all", *ODDS_BANDS]:
                group = subset if band == "all" else subset[subset["odds_band"] == band]
                row = {"selector": selector, "role": POLICIES[selector]["role"],
                       "period": period, "odds_band": band,
                       "source_selected_rows": int(len(subset)),
                       "price_invalid_rows": int(context[context["selector"] == selector]["price_valid"].eq(False).sum())}
                row.update(metrics(group, date_codes, schedule, with_ci=True))
                row["quote_mean"] = float(group["final_quote"].mean()) if len(group) else np.nan
                row["quote_median"] = float(group["final_quote"].median()) if len(group) else np.nan
                odds_rows.append(row)
    odds_table = pd.DataFrame(odds_rows)

    # Probability × final-price cross table; the crossed cells remain descriptive and have no CI.
    probability_rows = []
    for selector in POLICIES:
        selected = context[context["selector"] == selector]
        for period in PERIODS:
            subset = in_period(selected, period)
            for (pband, oband), group in subset.groupby(["probability_band", "odds_band"], sort=True):
                row = {"selector": selector, "role": POLICIES[selector]["role"], "period": period,
                       "probability_band": pband, "condition_expression": f"p in {pband}",
                       "odds_band": oband}
                row.update(metrics(group, date_codes, schedule, with_ci=False))
                row["support_status"] = support_status(len(group))
                probability_rows.append(row)
    probability_table = pd.DataFrame(probability_rows)

    condition_rows = []
    condition_cross_rows = []
    for selector in POLICIES:
        selected = context[context["selector"] == selector]
        for period in PERIODS:
            subset = in_period(selected, period)
            for family, col in condition_cols.items():
                for value, group in subset.groupby(col, sort=True, dropna=False):
                    row = {"selector": selector, "role": POLICIES[selector]["role"],
                           "period": period, "condition_family": family,
                           "condition_value": str(value),
                           "condition_expression": f"{col} = {value}",
                           "price_invalid_rows": int(context[context["selector"] == selector]["price_valid"].eq(False).sum())}
                    row.update(metrics(group, date_codes, schedule, with_ci=True))
                    condition_rows.append(row)
                    for band, band_group in group.groupby("odds_band", sort=True):
                        cross = {"selector": selector, "role": POLICIES[selector]["role"],
                                 "period": period, "condition_family": family,
                                 "condition_value": str(value),
                                 "condition_expression": f"{col} = {value}",
                                 "odds_band": band}
                        cross.update(metrics(band_group, date_codes, schedule, with_ci=False))
                        condition_cross_rows.append(cross)
    condition_table = pd.DataFrame(condition_rows)
    condition_cross = pd.DataFrame(condition_cross_rows)

    # These EV groups were already examined in the preceding post-race exploration.
    group_definitions = {
        "posthoc_score_ge_0": ("posthoc_score >= 0", lambda df: df["posthoc_score"] >= 0),
        "p_ge_030_and_score_ge_010": ("p >= 0.30 AND posthoc_score >= 0.10", lambda df: (df["p"] >= 0.30) & (df["posthoc_score"] >= 0.10)),
        "p_ge_030_and_score_ge_020": ("p >= 0.30 AND posthoc_score >= 0.20", lambda df: (df["p"] >= 0.30) & (df["posthoc_score"] >= 0.20)),
    }
    group_rows = []
    for selector in POLICIES:
        selected = context[context["selector"] == selector]
        for period in PERIODS:
            subset = in_period(selected, period)
            for group_id, (expression, predicate) in group_definitions.items():
                group = subset[predicate(subset)]
                for band in ["all", *ODDS_BANDS]:
                    cell = group if band == "all" else group[group["odds_band"] == band]
                    row = {"selector": selector, "role": POLICIES[selector]["role"],
                           "period": period, "group_id": group_id,
                           "group_expression": expression, "odds_band": band,
                           "previously_explored_exactly": bool(selector == "jockey_id_candidate" and period == "all"),
                           "independent_validation": False,
                           "posthoc_score_mean": float(cell["posthoc_score"].mean()) if len(cell) else np.nan,
                           "quote_mean": float(cell["final_quote"].mean()) if len(cell) else np.nan}
                    row.update(metrics(cell, date_codes, schedule, with_ci=(band == "all")))
                    group_rows.append(row)
    selected_groups = pd.DataFrame(group_rows)

    # Preserve condition value order and make sparse rows explicit through support_status.
    condition_table["condition_value"] = condition_table["condition_value"].astype(str)
    return {
        "odds_calibration": odds_table,
        "probability_odds_cells": probability_table,
        "condition_calibration": condition_table,
        "condition_odds_cells": condition_cross,
        "selected_group_diagnostics": selected_groups,
    }


def compact_rows(frame: pd.DataFrame, filters: dict[str, str], columns: list[str]) -> list[dict]:
    mask = pd.Series(True, index=frame.index)
    for col, value in filters.items():
        mask &= frame[col].astype(str) == str(value)
    chosen = frame.loc[mask, columns]
    return chosen.replace({np.nan: None}).to_dict(orient="records")


def write_outputs(context: pd.DataFrame, meta: dict, tables: dict[str, pd.DataFrame],
                  input_hashes: dict, source_meta: dict, schedule: np.ndarray) -> dict:
    STUDY.mkdir(parents=True, exist_ok=True)
    pair_cols = [
        "selector", "race_id", "race_date", "year", "distance_m", "grade_raw_i", "field_n_i",
        "horse_i", "horse_j", "horse_id_i", "horse_id_j", "api_record_id_i", "api_record_id_j",
        "score_i", "score_j", "score_rank_i", "score_rank_j", "weak_score_rank", "weak_score_rank_group",
        "score_gap_abs", "p", "final_quote", "odds_band", "probability_band", "posthoc_score", "hit",
        "finish_position_i", "finish_position_j", "both_top3", "exactly_one_top3", "neither_top3",
        "observed_starts_i", "observed_starts_j", "min_observed_starts", "observed_starts_condition",
        "same_valid_times_i", "same_valid_times_j", "min_same_valid_times", "same_valid_times_condition",
        "days_since_start_i", "days_since_start_j", "days_since_start_condition",
        "hist_s1f_relpos_mean5_i", "hist_s1f_relpos_mean5_j", "style_overlap_condition",
        "history_cutoff_i", "history_cutoff_j", "latest_history_date_i", "latest_history_date_j",
        "distance_condition", "grade_condition", "field_n_condition", "score_gap_condition",
        "source_run_id", "source_hash", "api301_page_sha256", "qpl_returns_sha256", "prediction_parquet_sha256",
    ]
    context_out = context[pair_cols].rename(columns={"grade_raw_i": "grade_raw", "field_n_i": "field_n"})
    context_path = STUDY / "pair_context.csv"
    context_out.to_csv(context_path, index=False, encoding="utf-8")

    output_paths = {"pair_context.csv": context_path}
    for name, frame in tables.items():
        path = STUDY / f"{name}.csv"
        frame.to_csv(path, index=False, encoding="utf-8")
        output_paths[path.name] = path

    odds = tables["odds_calibration"]
    selected_odds = odds[(odds["selector"] == "jockey_id_candidate") & (odds["period"] == "all")]
    outcome_rows = compact_rows(selected_odds, {}, ["odds_band", "n", "hits", "p_mean", "hit_rate_pct", "gap_pp", "gap_ci95_low_pp", "gap_ci95_high_pp", "o_e_ratio", "brier", "log_loss", "both_top3", "exactly_one_top3", "neither_top3", "bootstrap_zero_denominator_replicates"])
    current_groups = tables["selected_group_diagnostics"]
    existing_group_rows = compact_rows(current_groups[(current_groups["selector"] == "jockey_id_candidate") & (current_groups["period"] == "all") & (current_groups["odds_band"] == "all")], {}, ["group_id", "n", "hits", "p_mean", "hit_rate_pct", "gap_pp", "gap_ci95_low_pp", "gap_ci95_high_pp", "previously_explored_exactly"])
    current_conditions = tables["condition_calibration"]
    supported_conditions = current_conditions[(current_conditions["selector"] == "jockey_id_candidate") & (current_conditions["period"] == "all") & (current_conditions["n"] >= 50)].copy()
    high_gap = supported_conditions.sort_values(["gap_pp", "n"], ascending=[False, False]).head(10)
    low_gap = supported_conditions.sort_values(["gap_pp", "n"], ascending=[True, False]).head(10)

    summary_metrics = {}
    for selector in POLICIES:
        summary_metrics[selector] = compact_rows(odds, {"selector": selector, "period": "all", "odds_band": "all"},
            ["n", "hits", "p_mean", "hit_rate_pct", "gap_pp", "gap_ci95_low_pp", "gap_ci95_high_pp", "o_e_ratio", "brier", "log_loss"])[0]
    outcome_overall = summary_metrics["jockey_id_candidate"]

    def condition_row(family: str, value: str, period: str) -> dict | None:
        rows = current_conditions[(current_conditions["selector"] == "jockey_id_candidate") &
                                  (current_conditions["condition_family"] == family) &
                                  (current_conditions["condition_value"].astype(str) == value) &
                                  (current_conditions["period"] == period)]
        if rows.empty:
            return None
        return rows.iloc[0][["condition_family", "condition_value", "period", "n", "hits", "p_mean",
                             "hit_rate_pct", "gap_pp", "gap_ci95_low_pp", "gap_ci95_high_pp"]].replace({np.nan: None}).to_dict()

    condition_examples = []
    for family, value in [("grade_raw", "제2등급"), ("distance", "1300"), ("min_observed_starts", "3-9"), ("distance", "1610")]:
        periods = [condition_row(family, value, period) for period in PERIODS]
        condition_examples.append({"family": family, "value": value, "period_rows": periods})

    report = {
        "status": "PASS",
        "study": "20261013_odds_calibration_conditions_v1",
        "scope": "fixed pair event probability calibration conditioned on validated final QPL quote and frozen pre-race history fields",
        "interpretation": {
            "final_quote": "post-race condition only; no pre-race price, executable strategy, causal effect, profitability validation, or independent validation claim",
            "calibration_gap": "positive means mean probability exceeds empirical hit rate; negative means it is below",
            "log_loss": "probabilities clipped to [1e-15, 1 - 1e-15] for calculation",
            "qpl_event": "both selected horses finish in official Top 3; pair probability remains a QPL event probability",
            "conditions": "eight fixed exploratory condition families; not causal attribution; multiple condition views share the same repeated evaluation period",
            "field_n": "complete evaluated field size; its prediction-time public availability timestamp is unresolved",
            "front_history": "historic relative-position overlap only; not a claim that a horse led the current race",
            "score_gap": "raw F1_STYLE6 output score units, not seconds or probability",
        },
        "cohort": {
            "years": {"2025": 654, "2026_partial": 488},
            "races_per_selector": {"2025": 654, "2026_partial": 488, "total": 1142},
            "selectors": POLICIES,
            "context_rows": len(context),
            "total_unique_races": int(context["race_id"].nunique()),
        },
        "source_validation": {
            **meta,
            "hashes": input_hashes,
            "upstream_evidence_hashes": source_meta["evidence"],
            "price_review_status": source_meta["post_review"].get("status"),
            "price_review_selector_rows": source_meta["post_review"].get("selector_race_rows_verified"),
            "network": False,
            "database_read_or_write": False,
            "model_fit_refit_recalibration_or_reprediction": False,
        },
        "bootstrap": {
            "schedule_sha256": EXPECTED[BOOT_REL],
            "schedule_shape": list(schedule.shape),
            "date_inventory_sha256": source_meta["schedule_receipt"].get("date_inventory_sha256"),
            "date_inventory_count": source_meta["schedule_receipt"].get("dates_per_draw"),
            "date_min": source_meta["schedule_receipt"].get("date_min"),
            "date_max": source_meta["schedule_receipt"].get("date_max"),
            "method": "fixed whole-period date draws; period and condition masks applied within each stored draw; percentile 95% CI; zero-denominator repetitions omitted and counted",
        },
        "overall_calibration_all_prices": summary_metrics,
        "primary_current_all_odds_rows": outcome_rows,
        "current_odds_by_period": odds[(odds["selector"] == "jockey_id_candidate") & (odds["odds_band"] != "all")][["period", "odds_band", "n", "hits", "p_mean", "hit_rate_pct", "gap_pp", "gap_ci95_low_pp", "gap_ci95_high_pp", "o_e_ratio"]].replace({np.nan: None}).to_dict(orient="records"),
        "pair_outcome_current_overall": outcome_overall,
        "previously_seen_ev_group_current": existing_group_rows,
        "condition_examples_current_descriptive": condition_examples,
        "zero_event_bootstrap_limitations": [
            "The current [10,inf) quote stratum has 0 observed hits in 68 pairs. A nonparametric date bootstrap resamples those same zero observed hits and cannot create an unobserved success; its gap interval therefore reflects variation in resampled n and mean p, not a confidence interval that resolves the true rare-event rate.",
            "The 9-pair 1610m condition also has 0 observed hits. Its bootstrap interval is particularly unsuitable as a causal or filter rule.",
            "Zero observed hits do not mean the event probability is zero. Individual misses are not confirmed model errors.",
        ],
        "current_supported_condition_high_gap_descriptive": high_gap[["condition_family", "condition_value", "n", "hits", "p_mean", "hit_rate_pct", "gap_pp", "gap_ci95_low_pp", "gap_ci95_high_pp"]].replace({np.nan: None}).to_dict(orient="records"),
        "current_supported_condition_low_gap_descriptive": low_gap[["condition_family", "condition_value", "n", "hits", "p_mean", "hit_rate_pct", "gap_pp", "gap_ci95_low_pp", "gap_ci95_high_pp"]].replace({np.nan: None}).to_dict(orient="records"),
        "output_rows": {"pair_context.csv": len(context_out), **{f"{name}.csv": len(frame) for name, frame in tables.items()}},
    }
    report_path = STUDY / "REPORT.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    output_paths["REPORT.json"] = report_path

    current_by_band = [r for r in outcome_rows if r["odds_band"] != "all"]
    high = max(current_by_band, key=lambda x: x["gap_pp"])
    low = min(current_by_band, key=lambda x: x["gap_pp"])
    def lookup_odds_row(period: str, band: str) -> pd.Series:
        return odds[(odds["selector"] == "jockey_id_candidate") &
                    (odds["period"] == period) & (odds["odds_band"] == band)].iloc[0]
    favorite_all = lookup_odds_row("all", "[1,2)")
    favorite_2025 = lookup_odds_row("2025", "[1,2)")
    favorite_2026 = lookup_odds_row("2026_partial", "[1,2)")
    mid_long_2025 = lookup_odds_row("2025", "[5,10)")
    mid_long_2026 = lookup_odds_row("2026_partial", "[5,10)")
    grade2_2025 = condition_row("grade_raw", "제2등급", "2025")
    grade2_2026 = condition_row("grade_raw", "제2등급", "2026_partial")
    distance1300_2025 = condition_row("distance", "1300", "2025")
    distance1300_2026 = condition_row("distance", "1300", "2026_partial")
    career39_2025 = condition_row("min_observed_starts", "3-9", "2025")
    career39_2026 = condition_row("min_observed_starts", "3-9", "2026_partial")
    readme = [
        "# 최종 QPL 배당 구간별 보정 및 오차 조건 사후 진단",
        "",
        "이 보고서는 고정된 pair 선택과 확률을 유지한 채, 검증된 최종 QPL 배당 및 예측 전 고정 이력 조건별로 pair 사건의 확률 잔차를 기술한다. 최종 배당은 사후 조건이므로 실제 사전 전략·인과·수익성·독립 검증의 근거가 아니다.",
        "",
        "## 핵심 관측",
        "",
        f"현재 기수-ID 후보의 전체 유효 가격 표본은 {outcome_overall['n']:,}건이며 평균확률 {outcome_overall['p_mean']:.3f}, 적중률 {outcome_overall['hit_rate_pct']:.2f}%, gap {outcome_overall['gap_pp']:+.2f}%p (날짜 bootstrap 95% CI {outcome_overall['gap_ci95_low_pp']:+.2f}~{outcome_overall['gap_ci95_high_pp']:+.2f})다.",
        f"현재 후보 배당층 중 가장 큰 양의 관측 gap은 {high['odds_band']}에서 {high['gap_pp']:+.2f}%p (n={high['n']})이고, 가장 작은 gap은 {low['odds_band']}에서 {low['gap_pp']:+.2f}%p (n={low['n']})다. 이는 같은 반복 평가 자료에서 탐색한 층간 기술 차이다.",
        "현재 전체 1,142경주 중 pair 둘 다 Top3는 283건, 하나만 Top3는 648건, 둘 다 미입상은 211건이다. 미적중 859건 중 648건(75.4%)은 선택 pair의 한 말만 입상했다. 이는 pair 조합의 불확실성에 대한 후속 가설일 뿐, 개별 실패의 원인을 확정하지 않는다.",
        "고정 조건 주변표에서 제2등급은 n=74, gap −14.44%p (95% CI −25.37~−3.38); 1300m는 n=55, −12.14%p (−24.83~−0.31)다. 경력 최소 3–9회는 n=528, +3.16%p (−0.36~+6.57)로 작고 불확실한 과대평가 방향이다. 이러한 조건은 반복 개발 자료의 탐색 결과이며 다중 조건을 본 선택 효과가 남는다.",
        "[10,∞) 배당은 n=68에서 관측 적중이 0건이며, 1610m 조건은 n=9에서 0건이다. 고정 nonparametric bootstrap은 관측된 0건을 재표집하므로 성공 사건을 새로 만들 수 없다. 해당 gap CI는 진짜 희귀 사건률을 해소하지 않으며, 0건이 실제 확률 0이라는 뜻도 아니다.",
        "",
        "확률 gap은 `100 × (평균 p − hit rate)`이며 양수는 평균확률의 집단 과대평가, 음수는 과소평가를 뜻한다. O/E는 적중 수를 확률 합으로 나눈 값이고, Brier와 log loss는 각 선택 pair의 QPL 사건 확률을 대상으로 한다.",
        f"`[1,2)` 최종배당층의 gap은 전체 {favorite_all['gap_pp']:+.2f}%p였고 연도별로 2025 {favorite_2025['gap_pp']:+.2f}%p, 2026 부분연도 {favorite_2026['gap_pp']:+.2f}%p로 같은 과소평가 방향이다. `[5,10)`은 전체 +{lookup_odds_row('all', '[5,10)')['gap_pp']:.2f}%p였으며 연도별 2025 {mid_long_2025['gap_pp']:+.2f}%p, 2026 {mid_long_2026['gap_pp']:+.2f}%p로 양수 방향이나 2026 CI는 0을 포함한다.",
        f"고정 주변 조건의 예로 제2등급 gap은 연도별 {grade2_2025['gap_pp']:+.2f}%p (n={grade2_2025['n']}), {grade2_2026['gap_pp']:+.2f}%p (n={grade2_2026['n']}); 1300m는 {distance1300_2025['gap_pp']:+.2f}%p (n={distance1300_2025['n']}), {distance1300_2026['gap_pp']:+.2f}%p (n={distance1300_2026['n']})다. 경력 최소 3–9회는 두 연도에 각각 {career39_2025['gap_pp']:+.2f}%p, {career39_2026['gap_pp']:+.2f}%p다. 이 방향은 진단 단서이며 표본 수·연도 CI·배당층 내 잔차와 함께 읽어야 한다.",
        "",
        "## 입력과 재현",
        "",
        "- 코호트: 2025년 654경주 + 2026년 부분연도 488경주, 두 고정 선택기 각각 1,142경주.",
        "- 가격·정답은 원문 재검증 PASS를 받은 기존 race_rows를 사용했다. 확률과 pair label은 저장된 pair parquet와 모두 일치한다.",
        "- 두 선택 말은 공식 `race_id + horse_number`로 frozen feature에 연결하고, 평가 점수는 `api_record_id`로 F1_STYLE6 score에 연결했다. 말 번호와 horse ID를 혼동하지 않았다.",
        "- 말 이력은 경주일 2일 전 cutoff로 고정됐고 최신 이력일이 cutoff 이후인 행은 없다. 출전두수는 평가 원천의 정상완주 완전 편성 수이며 예측 당시 공개 시각은 복구되지 않았다.",
        "- 날짜 CI는 고정 2,000×269 schedule을 재사용한다. 조건×배당 상세 교차표에는 CI를 계산하지 않는다.",
        "- 재현: 저장소 루트에서 `.venv/bin/python jeju/research/20261013_odds_calibration_conditions_v1/analyze.py`.",
        "",
        "## 표와 범위",
        "",
        "`odds_calibration.csv`는 선택기·기간·최종배당 층의 calibration, pair 착순 결과 및 CI를 포함한다. `probability_odds_cells.csv`는 고정 확률 구간과 배당 구간의 보조 교차표다. `condition_calibration.csv`는 8개 고정 조건 가족의 주변 잔차와 CI, `condition_odds_cells.csv`는 해당 조건 내부 배당층 잔차를 보존한다. `selected_group_diagnostics.csv`는 이전에 확인한 EV≥0 및 고확률+EV 집단을 재현하며 새 독립 검증으로 표시하지 않는다. `pair_context.csv`는 분석 행별 조인키·조건·실제 착순을 남긴다.",
        "",
        "분석은 여러 고정 조건을 같은 반복 개발 평가 기간에 살펴본 탐색이며 별도 사전등록·독립 검증이 아니다. 개별 미적중이나 조건 간 차이는 단독 원인으로 확정하지 않는다. 배당에 따른 감점계수·재보정·모델이나 운영 선택은 이 결과로 만들지 않았다.",
        "",
        "원천과 출력 SHA-256 및 입력 hash chain은 `SOURCE_HASHES.json`에 기록한다. 파일은 이 연구 폴더 안에만 생성한다.",
        "",
        "검토 메모와 개선 우선순위는 [감독 검토와 개선 방향](REVIEW_AND_NEXT_STEPS.md)을 참조한다.",
    ]
    readme_path = STUDY / "README.md"
    readme_path.write_text("\n".join(readme) + "\n", encoding="utf-8")
    output_paths["README.md"] = readme_path

    plan_path = STUDY / "PLAN.md"
    output_hashes = {name: sha256(path) for name, path in output_paths.items()}
    output_hashes["PLAN.md"] = sha256(plan_path)
    output_hashes["analyze.py"] = sha256(STUDY / "analyze.py")
    source_manifest = {
        "study": "20261013_odds_calibration_conditions_v1",
        "scope": "local read-only post-race diagnostics; source and output hashes verified; manifest hash excludes itself",
        "inputs": input_hashes,
        "upstream_evidence_hashes": source_meta["evidence"],
        "upstream_review": {
            "status": source_meta["post_review"].get("status"),
            "actual_prepurchase_strategy_validated": source_meta["post_review"].get("actual_prepurchase_strategy_validated"),
            "profitability_confirmed": source_meta["post_review"].get("profitability_confirmed"),
        },
        "read_only": {"network": False, "database": False, "model_fit": False, "recalibration": False, "reprediction": False},
        "outputs_sha256": output_hashes,
        "output_bytes": {name: path.stat().st_size for name, path in output_paths.items()},
        "row_counts": report["output_rows"],
    }
    source_hash_path = STUDY / "SOURCE_HASHES.json"
    source_hash_path.write_text(json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    input_hashes, schedule, source_meta = verify_inputs()
    context, source_summary, date_inventory = build_context()
    date_inventory_hash = hashlib.sha256("\n".join(date_inventory).encode("utf-8")).hexdigest()
    if (len(date_inventory) != 269 or
            date_inventory_hash != source_meta["schedule_receipt"].get("date_inventory_sha256")):
        raise ValueError("Full pair-parquet date inventory does not match the fixed schedule receipt")
    tables = build_tables(context, schedule, date_inventory)

    # Preserve existing exploratory subgroup definitions and check their previously reported main-sample sizes.
    previous = tables["selected_group_diagnostics"]
    current_all = previous[(previous["selector"] == "jockey_id_candidate") &
                           (previous["period"] == "all") & (previous["odds_band"] == "all")]
    observed_counts = dict(zip(current_all["group_id"], current_all["n"].astype(int)))
    expected_counts = {
        "posthoc_score_ge_0": 326,
        "p_ge_030_and_score_ge_010": 52,
        "p_ge_030_and_score_ge_020": 39,
    }
    if observed_counts != expected_counts:
        raise ValueError(f"Previously reviewed current-policy subgroup counts changed: {observed_counts}")

    # Make deterministic, review-friendly numeric formats without rounding source metrics.
    report = write_outputs(context, source_summary, tables, input_hashes, source_meta, schedule)
    print(json.dumps({"status": report["status"], "output_rows": report["output_rows"],
                      "current_overall": report["overall_calibration_all_prices"]["jockey_id_candidate"],
                      "current_odds": report["primary_current_all_odds_rows"],
                      "output_dir": str(STUDY)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

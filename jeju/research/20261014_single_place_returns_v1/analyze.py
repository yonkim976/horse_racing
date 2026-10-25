"""Gated, fixed-contract analysis of single-horse place probabilities/returns.

No outcome or payout input is opened until the source-audit PASS receipt and
the root's hash-pinned calculation approval both validate.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
OUT = STUDY / "outputs"
PRELIGHT = OUT / "probability_preflight_receipt.json"
ANCHORS = OUT / "selected_anchors_label_free.csv"
APPROVAL = STUDY / "ROOT_CALCULATION_APPROVAL.json"
AUDIT_DIR = STUDY / "source_audit"
AUDIT_FINAL = AUDIT_DIR / "SOURCE_AUDIT_FINAL.json"
INVENTORY = AUDIT_DIR / "SOURCE_INVENTORY.json"
PLC_ROWS = AUDIT_DIR / "PLC_PRICE_ROWS.csv"
OFFICIAL_RESULTS = AUDIT_DIR / "OFFICIAL_RUNNER_RESULTS.csv"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
RUNNERS = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/report/runner_predictions.parquet"
BOOTSTRAP = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"

EXPECTED = {
    "plan_sha256": "1df08e456657e17cded5a5068bddb5a49b75d988b692632f21c12d0dc23574a5",
    "features_sha256": "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    "runner_predictions_sha256": "706bca01e5f5e780a8ffbe9e2ad4553fea9e3d76df097b4c9648d7aabac44e56",
    "bootstrap_sha256": "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
    "bootstrap_receipt_sha256": "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e",
}
STAKE_KRW = 1000
EXPECTED_RUNNERS = 17412
EXPECTED_RACES = 1779
EXPECTED_DATES = 269
EXPECTED_PRICE_RACES = 1142
EXPECTED_PRICE_RUNNERS = 11083
EXPECTED_TOP3_SUPPORT = 1743
EXPECTED_TOP2_UNSUPPORTED = 36
PRICE_END = pd.Timestamp("2026-09-19")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"required gate/receipt is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def verify_gates() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate metadata gates before opening any outcome or price rows."""
    approval = read_json(APPROVAL)
    audit = read_json(AUDIT_FINAL)
    preflight = read_json(PRELIGHT)
    require(approval.get("status") == "APPROVED" and approval.get("approved") is True,
            "calculation approval is not explicitly APPROVED")
    require(approval.get("approved_by") == "root", "unexpected approver")
    require(approval.get("scope") == "fixed_single_anchor_outcome_and_ROI_analysis",
            "approval scope does not match this analysis")
    require(approval.get("stake_krw") == STAKE_KRW and approval.get("fits_allowed") == 0,
            "approval stake/fit constraints do not match the frozen plan")
    require(audit.get("status") == "PASS", "source audit is not final PASS")
    prohibited = audit.get("prohibited_metrics", {})
    require(prohibited.get("outcomes_or_metrics_computed") is False
            and prohibited.get("performance_computed") is False and prohibited.get("ROI_computed") is False,
            "source-audit receipt indicates performance metrics were computed")
    payout_contract = audit.get("return_contract", {})
    require(payout_contract.get("price_unit") == "raw decimal gross return multiplier per stake unit; no transformation"
            and payout_contract.get("source_is_winner_only_paid_payout") is False
            and payout_contract.get("quotes_present_for_losers") is True
            and payout_contract.get("nonqualifier_gross_return") == "zero",
            "audited odds/return contract does not match the frozen ROI implementation")
    require(preflight.get("status") == "PASS" and preflight.get("target_labels_read") is False
            and preflight.get("payout_inputs_read") is False
            and preflight.get("performance_metrics_computed") is False,
            "label-free probability preflight is missing or invalid")

    paths = {
        "plan_sha256": STUDY / "PLAN.md",
        "analysis_code_sha256": Path(__file__).resolve(),
        "source_audit_final_sha256": AUDIT_FINAL,
        "source_price_rows_sha256": PLC_ROWS,
        "source_inventory_sha256": INVENTORY,
        "probability_preflight_sha256": PRELIGHT,
    }
    for field, path in paths.items():
        require(path.is_file(), f"approval-pinned input is missing: {path}")
        actual = sha256(path)
        expected = approval.get(field)
        require(isinstance(expected, str) and expected == actual,
                f"approval hash mismatch for {field}")
    require(approval.get("plan_sha256") == EXPECTED["plan_sha256"], "approved plan hash is not the frozen plan")
    require(sha256(FEATURES) == EXPECTED["features_sha256"],
            "frozen feature/outcome source hash changed")
    require(sha256(RUNNERS) == EXPECTED["runner_predictions_sha256"],
            "frozen native probability source hash changed")
    require(sha256(BOOTSTRAP) == EXPECTED["bootstrap_sha256"],
            "fixed date-bootstrap schedule hash changed")
    require(sha256(BOOTSTRAP_RECEIPT) == EXPECTED["bootstrap_receipt_sha256"],
            "fixed date-bootstrap receipt hash changed")
    require(sha256(ANCHORS) == preflight.get("anchor_output", {}).get("sha256"),
            "label-free anchor output does not match its receipt")
    require(preflight.get("counts", {}).get("races") == EXPECTED_RACES
            and preflight.get("counts", {}).get("runner_rows") == EXPECTED_RUNNERS
            and preflight.get("counts", {}).get("race_days") == EXPECTED_DATES
            and preflight.get("counts", {}).get("native_probability_supported_races") == EXPECTED_TOP3_SUPPORT
            and preflight.get("counts", {}).get("Top2_probability_unavailable_races") == EXPECTED_TOP2_UNSUPPORTED,
            "frozen probability cohort counts changed")
    require(sha256(INVENTORY) == approval.get("source_inventory_sha256"),
            "source inventory hash changed")
    require(sha256(PLC_ROWS) == approval.get("source_price_rows_sha256"),
            "PLC source hash changed")
    artifacts = audit.get("artifacts", {})
    require(artifacts.get("PLC_PRICE_ROWS.csv", {}).get("sha256") == sha256(PLC_ROWS),
            "audit receipt does not pin PLC source rows")
    require(artifacts.get("SOURCE_INVENTORY.json", {}).get("sha256") == sha256(INVENTORY),
            "audit receipt does not pin source inventory")
    official_hash = artifacts.get("OFFICIAL_RUNNER_RESULTS.csv", {}).get("sha256")
    require(isinstance(official_hash, str) and sha256(OFFICIAL_RESULTS) == official_hash,
            "audit receipt does not pin the official-results cache")
    return approval, audit, preflight


def parse_bool(series: pd.Series, name: str) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    normalized = series.astype("string").str.strip().str.lower()
    mapping = {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}
    result = normalized.map(mapping)
    require(result.notna().all(), f"unrecognized boolean values in {name}")
    return result.astype(bool)


def load_contract_data() -> tuple[pd.DataFrame, dict[str, Any]]:
    preflight = read_json(PRELIGHT)
    anchors = pd.read_csv(ANCHORS, dtype={"race_id": "string", "horse_id": "string"})
    required_anchor = {"race_id", "race_date", "year", "horse_id", "horse_number",
                       "api_record_id", "field_n", "p_top3", "p_place", "place_finish_cutoff"}
    require(required_anchor.issubset(anchors.columns), "anchor columns do not match the preflight contract")
    anchors["race_date"] = pd.to_datetime(anchors["race_date"], errors="raise").dt.normalize()
    require(len(anchors) == EXPECTED_RACES and anchors.race_id.nunique() == EXPECTED_RACES,
            "anchor file does not contain exactly one row per fixed cohort race")
    require(anchors.api_record_id.notna().all() and anchors.api_record_id.is_unique,
            "anchor API keys are missing or duplicated")

    features = pd.read_parquet(FEATURES, columns=["api_record_id", "race_id", "race_date", "year",
                                                  "horse_id", "horse_number", "finish_position", "field_n"])
    features = features.loc[features.year.isin([2024, 2025, 2026])].copy()
    require(len(features) == EXPECTED_RUNNERS and features.api_record_id.is_unique,
            "frozen feature runner count/key uniqueness changed")
    require(features.finish_position.notna().all(), "official finish labels are incomplete")
    require((features.finish_position > 0).all(), "nonpositive/invalid official finish rank")
    features["race_date"] = pd.to_datetime(features.race_date, errors="raise").dt.normalize()

    # Independently audited complete result roster, used to verify frozen features.
    official = pd.read_csv(OFFICIAL_RESULTS, dtype={"race_id": "string", "kra_horse_id": "string"})
    official_required = {"race_id", "horse_number", "kra_horse_id", "finish_position"}
    require(official_required.issubset(official.columns), "official result cache columns changed")
    official["finish_position"] = pd.to_numeric(official.finish_position, errors="raise")
    official["horse_number"] = pd.to_numeric(official.horse_number, errors="raise").astype("int64")
    if "field_size" in official:
        official["field_size"] = pd.to_numeric(official.field_size, errors="raise").astype("int64")
    require(len(official) == EXPECTED_RUNNERS, "official result cache row count changed")
    official_key = ["race_id", "horse_number", "kra_horse_id"]
    require(not official[official_key].isna().any().any() and not official.duplicated(official_key).any(),
            "official result keys are missing or duplicated")

    features = features.copy()
    features["horse_id"] = features.horse_id.astype("string")
    official_columns = official_key + ["finish_position"] + (["field_size"] if "field_size" in official else [])
    joined_all = features.merge(
        official[official_columns].rename(columns={
            "kra_horse_id": "official_horse_id", "finish_position": "official_finish_position"
        }),
        left_on=["race_id", "horse_number", "horse_id"], right_on=["race_id", "horse_number", "official_horse_id"],
        how="left", validate="one_to_one", indicator=True,
    )
    require(joined_all._merge.eq("both").all(), "official results do not cover frozen feature runners")
    require(np.array_equal(joined_all.finish_position.to_numpy(), joined_all.official_finish_position.to_numpy()),
            "official results disagree with frozen feature finish ranks")
    if "field_size" in joined_all.columns:
        require(np.array_equal(joined_all.field_n.to_numpy(), joined_all.field_size.to_numpy()),
                "official result field sizes disagree with frozen feature roster")
    require(np.array_equal(joined_all.field_n.to_numpy(),
                           joined_all.groupby("race_id", sort=False).api_record_id.transform("size").to_numpy()),
            "frozen cohort field sizes do not match runner roster")

    anchors = anchors.merge(
        features[["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "field_n", "finish_position"]],
        on="api_record_id", how="left", validate="one_to_one", suffixes=("_anchor", "_feature"), indicator=True,
    )
    require(anchors._merge.eq("both").all(), "selected anchors do not match frozen feature outcomes")
    for col in ["race_id", "horse_id", "horse_number", "field_n"]:
        require(np.array_equal(anchors[f"{col}_anchor"].astype(str).to_numpy(),
                               anchors[f"{col}_feature"].astype(str).to_numpy()),
                f"anchor and feature {col} mismatch")
    require(np.array_equal(anchors.race_date_anchor.to_numpy(), anchors.race_date_feature.to_numpy()),
            "anchor and feature dates mismatch")
    require(np.array_equal(anchors.year_anchor.to_numpy(), anchors.year_feature.to_numpy()),
            "anchor and feature years mismatch")
    anchors = anchors.drop(columns=["_merge"])
    anchors = anchors.rename(columns={
        "race_id_anchor": "race_id", "race_date_anchor": "race_date", "year_anchor": "year",
        "horse_id_anchor": "horse_id", "horse_number_anchor": "horse_number", "field_n_anchor": "field_n",
        "race_date_feature": "feature_race_date", "year_feature": "feature_year",
        "horse_id_feature": "feature_horse_id", "horse_number_feature": "feature_horse_number",
        "field_n_feature": "feature_field_n",
    })
    anchors["place_finish_cutoff"] = anchors.field_n.map(lambda n: 3 if int(n) >= 8 else 2)
    require(anchors.p_place.isna().eq(anchors.field_n.le(7)).all(), "Top2 probability support boundary changed")
    require(np.array_equal(anchors.p_place.notna().to_numpy(), anchors.field_n.ge(8).to_numpy()),
            "native Top3 probability availability does not follow field-size contract")
    anchors["place_hit"] = anchors.finish_position.le(anchors.place_finish_cutoff)
    anchors["p_top3"] = pd.to_numeric(anchors.p_top3, errors="raise")
    supported = anchors.loc[anchors.p_place.notna()].copy()
    require(len(supported) == EXPECTED_TOP3_SUPPORT, "Top3-supported race count changed")
    require(np.allclose(supported.p_place.to_numpy(float), supported.p_top3.to_numpy(float), rtol=0, atol=0),
            "selected p_place is not the original saved native p_top3")

    # Cross-check the saved evaluation target against the official finish rank for every runner.
    saved_y = pd.read_parquet(RUNNERS, columns=["api_record_id", "race_id", "horse_number", "variant", "y"])
    saved_y = saved_y.loc[saved_y.variant.eq("F1_STYLE6"), ["api_record_id", "race_id", "horse_number", "y"]]
    require(len(saved_y) == EXPECTED_RUNNERS and saved_y.api_record_id.is_unique,
            "saved F1_STYLE6 outcome labels changed")
    label_check = features[["api_record_id", "race_id", "horse_number", "finish_position"]].merge(
        saved_y, on=["api_record_id", "race_id", "horse_number"], how="left", validate="one_to_one",
        indicator=True,
    )
    require(label_check._merge.eq("both").all() and label_check.y.notna().all(),
            "saved F1_STYLE6 labels do not cover the frozen official runner roster")
    expected_y = label_check.finish_position.le(3).astype("int64")
    require(np.array_equal(label_check.y.astype("int64").to_numpy(), expected_y.to_numpy()),
            "saved F1_STYLE6 y disagrees with official finish_position <= 3")
    return anchors, {"feature_runner_rows": len(features), "official_runner_rows": len(official),
                     "saved_y_rows": len(saved_y), "top3_label_parity": "PASS"}


def load_price_rows(anchors: pd.DataFrame) -> pd.DataFrame:
    prices = pd.read_csv(PLC_ROWS, low_memory=False, dtype={
        "race_id": "string", "kra_horse_id": "string", "pool_code": "string",
    })
    needed = {"race_id", "race_date_local", "horse_number", "kra_horse_id", "odds", "odds_unit",
              "pool_code", "official_field_size", "official_finish_position",
              "qualifies_under_project_place_rule"}
    require(needed.issubset(prices.columns), "audited PLC cache columns changed")
    prices = prices.loc[prices.pool_code.eq("PLC")].copy()
    prices["race_date"] = pd.to_datetime(prices.race_date_local, errors="raise").dt.normalize()
    prices["horse_number"] = pd.to_numeric(prices.horse_number, errors="raise").astype("int64")
    prices["official_field_size"] = pd.to_numeric(prices.official_field_size, errors="raise").astype("int64")
    prices["official_finish_position"] = pd.to_numeric(prices.official_finish_position, errors="raise")
    prices["odds_numeric"] = pd.to_numeric(prices.odds, errors="coerce")
    key = ["race_id", "kra_horse_id"]
    require(len(prices) == EXPECTED_PRICE_RUNNERS and prices.race_id.nunique() == EXPECTED_PRICE_RACES,
            "audited PLC cohort coverage changed")
    require(not prices[key].isna().any().any() and not prices.duplicated(key).any(),
            "audited PLC cache has missing/duplicate race-runner keys")
    require(prices.race_date.le(PRICE_END).all() and prices.race_date.dt.year.isin([2025, 2026]).all(),
            "PLC cache contains races outside the frozen payout period")
    require(prices.odds_unit.notna().all() and prices.odds_unit.nunique() == 1,
            "PLC quote unit is missing or inconsistent")
    require(prices.odds_numeric.notna().all() and np.isfinite(prices.odds_numeric.to_numpy(float)).all()
            and prices.odds_numeric.gt(0).all()
            and not prices.odds_numeric.isin([9999.9]).any(), "PLC prices include missing/special values")
    require(prices.qualifies_under_project_place_rule.notna().all(), "PLC official place outcomes are missing")
    if "official_scratched" in prices:
        require(not parse_bool(prices.official_scratched, "official_scratched").any(),
                "PLC cohort includes scratched runners")
    if "official_disqualified" in prices:
        require(not parse_bool(prices.official_disqualified, "official_disqualified").any(),
                "PLC cohort includes disqualified runners")
    prices["qualifies_under_project_place_rule"] = parse_bool(
        prices.qualifies_under_project_place_rule, "qualifies_under_project_place_rule"
    )
    # Match the complete PLC roster and official outcomes to the primary frozen features.
    full_features = pd.read_parquet(FEATURES, columns=["race_id", "horse_id", "horse_number", "finish_position", "field_n"])
    period = full_features.loc[full_features.race_id.isin(prices.race_id.unique())].copy()
    cross = prices.merge(period, left_on=["race_id", "kra_horse_id", "horse_number"],
                         right_on=["race_id", "horse_id", "horse_number"], how="left",
                         validate="one_to_one", indicator=True, suffixes=("_audit", "_feature"))
    require(cross._merge.eq("both").all() and len(cross) == EXPECTED_PRICE_RUNNERS,
            "PLC source does not cover the fixed official runner roster")
    require(np.array_equal(cross.official_finish_position.to_numpy(), cross.finish_position.to_numpy()),
            "PLC audit outcome differs from frozen official finish rank")
    require(np.array_equal(cross.official_field_size.to_numpy(), cross.field_n.to_numpy()),
            "PLC official field size differs from frozen feature roster")
    expected_qualifies = cross.finish_position.le(np.where(cross.field_n.to_numpy() >= 8, 3, 2))
    require(np.array_equal(cross.qualifies_under_project_place_rule.to_numpy(bool), expected_qualifies.to_numpy()),
            "PLC audit place-eligibility flag disagrees with frozen finish rank")

    # Only the selected horse's quote is carried forward. A miss pays zero; lack
    # of a selected-horse quote on a hit is an error, never a silently dropped race.
    selected = anchors.loc[anchors.race_date.ge(pd.Timestamp("2025-01-01")) & anchors.race_date.le(PRICE_END),
                           ["race_id", "horse_id", "horse_number", "race_date", "finish_position",
                            "place_hit", "place_finish_cutoff"]].copy()
    selected = selected.merge(
        prices[["race_id", "kra_horse_id", "horse_number", "odds_numeric", "official_finish_position",
                "qualifies_under_project_place_rule"]],
        left_on=["race_id", "horse_id", "horse_number"], right_on=["race_id", "kra_horse_id", "horse_number"],
        how="left", validate="one_to_one", indicator=True,
    )
    require(len(selected) == EXPECTED_PRICE_RACES and selected._merge.eq("both").all(),
            "selected runner payout coverage is incomplete")
    require(np.array_equal(selected.place_hit.to_numpy(bool),
                           selected.qualifies_under_project_place_rule.to_numpy(bool)),
            "selected place outcomes disagree with PLC official results")
    expected_selected_hit = selected.official_finish_position.le(selected.place_finish_cutoff)
    require(np.array_equal(selected.place_hit.to_numpy(bool), expected_selected_hit.to_numpy(bool)),
            "selected official finish rank disagrees with the locked place cutoff")
    require(np.array_equal(selected.official_finish_position.to_numpy(), selected.finish_position.to_numpy()),
            "selected official PLC result differs from the primary frozen feature result")
    selected["gross_return_krw"] = np.where(selected.place_hit, STAKE_KRW * selected.odds_numeric, 0.0)
    selected["stake_krw"] = STAKE_KRW
    return selected.drop(columns=["_merge"])


def load_bootstrap(dates: pd.Series) -> tuple[np.ndarray, dict[str, int]]:
    draws = np.load(BOOTSTRAP, allow_pickle=False)
    expected_dates = sorted(pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates.unique())
    require(draws.shape == (2000, EXPECTED_DATES), "fixed date-bootstrap shape changed")
    require(draws.dtype.kind in "iu" and draws.min() >= 0 and draws.max() < EXPECTED_DATES,
            "fixed date-bootstrap indices are invalid")
    require(len(expected_dates) == EXPECTED_DATES, "fixed cohort date count changed")
    receipt = read_json(BOOTSTRAP_RECEIPT)
    date_hash = hashlib.sha256("\n".join(expected_dates).encode("utf-8")).hexdigest()
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS"
            and receipt.get("date_inventory_sha256") == date_hash
            and receipt.get("schedule_sha256") == sha256(BOOTSTRAP)
            and receipt.get("source_features_sha256") == EXPECTED["features_sha256"],
            "fixed bootstrap receipt/date inventory does not match the evaluation cohort")
    require(receipt.get("seed") == 20261011 and receipt.get("draws") == 2000
            and receipt.get("dates_per_draw") == EXPECTED_DATES,
            "fixed bootstrap generation recipe changed")
    # The fixed array stores sampled date IDs; convert each draw to date multiplicities.
    weights = np.stack([np.bincount(draw, minlength=EXPECTED_DATES) for draw in draws]).astype(np.int64)
    require(np.all(weights.sum(axis=1) == EXPECTED_DATES), "bootstrap frequency rows do not sum to 269 dates")
    return weights, {d: i for i, d in enumerate(expected_dates)}


def ci_for(group: pd.DataFrame, schedule: np.ndarray, date_index: dict[str, int]) -> dict[str, float | None]:
    dates = group.race_date.dt.strftime("%Y-%m-%d").map(date_index).to_numpy(dtype=np.int64)
    weights = schedule[:, dates]
    hits = group.place_hit.to_numpy(dtype=np.float64)
    n = weights @ np.ones(len(group), dtype=np.float64)
    h = weights @ hits
    hit_rates = np.divide(h, n, out=np.full_like(h, np.nan), where=n > 0)
    valid = int(np.isfinite(hit_rates).sum())
    out: dict[str, float | None] = {
        "place_hit_rate_ci_low": float(np.nanpercentile(hit_rates, 2.5)) if valid else None,
        "place_hit_rate_ci_high": float(np.nanpercentile(hit_rates, 97.5)) if valid else None,
        "place_hit_rate_ci_valid_draws": valid,
        "place_hit_rate_ci_undefined_draws": len(hit_rates) - valid,
    }
    if "gross_return_krw" in group and group.gross_return_krw.notna().all():
        gross = weights @ group.gross_return_krw.to_numpy(dtype=np.float64)
        stakes = weights @ group.stake_krw.to_numpy(dtype=np.float64)
        roi = np.divide(gross, stakes, out=np.full_like(gross, np.nan), where=stakes > 0) - 1.0
        roi_valid = int(np.isfinite(roi).sum())
        out["roi_ci_low"] = float(np.nanpercentile(roi, 2.5)) if roi_valid else None
        out["roi_ci_high"] = float(np.nanpercentile(roi, 97.5)) if roi_valid else None
        out["roi_ci_valid_draws"] = roi_valid
        out["roi_ci_undefined_draws"] = len(roi) - roi_valid
    else:
        out["roi_ci_low"] = None
        out["roi_ci_high"] = None
        out["roi_ci_valid_draws"] = 0
        out["roi_ci_undefined_draws"] = schedule.shape[0]
    return out


def probability_ci(group: pd.DataFrame, schedule: np.ndarray,
                   date_index: dict[str, int]) -> dict[str, float | int | None]:
    if group.empty:
        return {"p_hit_rate_ci_low": None, "p_hit_rate_ci_high": None,
                "calibration_gap_ci_low": None, "calibration_gap_ci_high": None,
                "probability_ci_valid_draws": 0, "probability_ci_undefined_draws": schedule.shape[0]}
    dates = group.race_date.dt.strftime("%Y-%m-%d").map(date_index).to_numpy(dtype=np.int64)
    weights = schedule[:, dates]
    n = weights @ np.ones(len(group), dtype=np.float64)
    hit = weights @ group.place_hit.to_numpy(dtype=np.float64)
    prob = weights @ group.p_place.to_numpy(dtype=np.float64)
    hit_rate = np.divide(hit, n, out=np.full_like(hit, np.nan), where=n > 0)
    gap = np.divide(hit - prob, n, out=np.full_like(hit, np.nan), where=n > 0)
    valid = int(np.isfinite(hit_rate).sum())
    return {
        "p_hit_rate_ci_low": float(np.nanpercentile(hit_rate, 2.5)) if valid else None,
        "p_hit_rate_ci_high": float(np.nanpercentile(hit_rate, 97.5)) if valid else None,
        "calibration_gap_ci_low": float(np.nanpercentile(gap, 2.5)) if valid else None,
        "calibration_gap_ci_high": float(np.nanpercentile(gap, 97.5)) if valid else None,
        "probability_ci_valid_draws": valid,
        "probability_ci_undefined_draws": len(hit_rate) - valid,
    }


def summary_row(cohort: str, label: str, value: str, group: pd.DataFrame, schedule: np.ndarray,
                date_index: dict[str, int]) -> dict[str, Any]:
    n = len(group)
    p_group = group.loc[group.p_place.notna()].copy()
    p_n = len(p_group)
    row: dict[str, Any] = {
        "cohort": cohort, "dimension": label, "group": value,
        "race_n": n, "date_n": int(group.race_date.nunique()),
        "starter_n": int(group.field_n.sum()),
        "place_hit_n": int(group.place_hit.sum()),
        "place_hit_rate": float(group.place_hit.mean()) if n else None,
        "p_support_n": p_n,
        "p_support_hit_n": int(p_group.place_hit.sum()) if p_n else None,
        "p_support_hit_rate": float(p_group.place_hit.mean()) if p_n else None,
        "mean_p": float(p_group.p_place.mean()) if p_n else None,
        "calibration_gap_hit_minus_p": float(p_group.place_hit.mean() - p_group.p_place.mean()) if p_n else None,
        "brier": float(np.mean((p_group.p_place.to_numpy(float) - p_group.place_hit.to_numpy(float)) ** 2)) if p_n else None,
        "log_loss": float(np.mean(-p_group.place_hit.to_numpy(float) * np.log(np.clip(p_group.p_place.to_numpy(float), 1e-15, 1 - 1e-15))
                                   -(1.0 - p_group.place_hit.to_numpy(float)) * np.log1p(-np.clip(p_group.p_place.to_numpy(float), 1e-15, 1 - 1e-15)))) if p_n else None,
        "odds_race_n": 0, "odds_hit_n": None, "odds_hit_rate": None,
        "stake_krw": None, "gross_return_krw": None, "roi": None,
        "mean_hit_odds": None, "mean_hit_return_krw": None,
        "break_even_hit_rate": None, "break_even_odds": None,
    }
    row.update(ci_for(group, schedule, date_index))
    row.update(probability_ci(p_group, schedule, date_index))
    odds_group = group.loc[group.odds_numeric.notna()].copy()
    if len(odds_group):
        hits = odds_group.loc[odds_group.place_hit]
        stake = float(odds_group.stake_krw.sum())
        gross = float(odds_group.gross_return_krw.sum())
        actual_rate = float(odds_group.place_hit.mean())
        row.update({
            "odds_race_n": len(odds_group),
            "odds_hit_n": int(odds_group.place_hit.sum()),
            "odds_hit_rate": actual_rate,
            "stake_krw": stake,
            "gross_return_krw": gross,
            "roi": gross / stake - 1.0,
            "mean_hit_odds": float(hits.odds_numeric.mean()) if len(hits) else None,
            "mean_hit_return_krw": float(hits.gross_return_krw.mean()) if len(hits) else None,
            "break_even_hit_rate": float(1.0 / hits.odds_numeric.mean()) if len(hits) else None,
            "break_even_odds": float(1.0 / actual_rate) if actual_rate > 0 else None,
        })
        roi_ci = ci_for(odds_group, schedule, date_index)
        for key in ("roi_ci_low", "roi_ci_high", "roi_ci_valid_draws", "roi_ci_undefined_draws"):
            row[key] = roi_ci[key]
    return row


def make_summaries(frame: pd.DataFrame, schedule: np.ndarray, date_index: dict[str, int],
                   cohort: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for dimension, groups in [
        ("all", [("all", frame)]),
        ("year", [(str(k), v) for k, v in frame.groupby("year", sort=True)]),
        ("field_size", [(str(k), v) for k, v in frame.groupby("field_n", sort=True)]),
    ]:
        rows.extend(summary_row(cohort, dimension, value, group, schedule, date_index) for value, group in groups)

    supported = frame.loc[frame.p_place.notna()].copy()
    supported["probability_band"] = pd.cut(
        supported.p_place, bins=np.linspace(0, 1, 11), right=False,
        labels=[f"[{i / 10:.1f},{(i + 1) / 10:.1f}{']' if i == 9 else ')'}" for i in range(10)], include_lowest=True,
    ).astype("string")
    supported.loc[supported.p_place.eq(1.0), "probability_band"] = "[0.9,1.0]"
    require(supported.probability_band.notna().all(), "a supported probability fell outside fixed bins")
    band_labels = [f"[{i / 10:.1f},{(i + 1) / 10:.1f}{']' if i == 9 else ')'}" for i in range(10)]
    for band in band_labels:
        group = supported.loc[supported.probability_band.eq(band)]
        rows.append(summary_row(cohort, "probability_band", band, group, schedule, date_index))
    unavailable = frame.loc[frame.p_place.isna()]
    rows.append(summary_row(cohort, "probability_unavailable", "field_n<=7 Top2", unavailable, schedule, date_index))
    for threshold in (0.5, 0.6, 0.7, 0.8, 0.9):
        group = supported.loc[supported.p_place.ge(threshold)]
        rows.append(summary_row(cohort, "probability_threshold", f">={threshold:.1f}", group, schedule, date_index))
    return pd.DataFrame(rows)


def make_race_rows(anchors: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    out = anchors[["race_id", "race_date", "year", "horse_id", "horse_number", "field_n",
                   "score", "p_top3", "p_place", "place_finish_cutoff", "finish_position", "place_hit"]].copy()
    out = out.rename(columns={"finish_position": "official_finish_position"})
    out["payout_period"] = out.race_date.ge(pd.Timestamp("2025-01-01")) & out.race_date.le(PRICE_END)
    selected = prices[["race_id", "kra_horse_id", "odds_numeric", "gross_return_krw", "stake_krw"]].rename(
        columns={"kra_horse_id": "horse_id", "odds_numeric": "place_odds_multiple"}
    )
    out = out.merge(selected, on=["race_id", "horse_id"], how="left", validate="one_to_one")
    out.loc[~out.payout_period, ["place_odds_multiple", "gross_return_krw", "stake_krw"]] = np.nan
    return out.sort_values(["race_date", "race_id"], kind="stable").reset_index(drop=True)


def write_new(path: Path, content: str) -> None:
    require(path.resolve().parent == OUT.resolve(), "output path escaped the study outputs directory")
    with path.open("x", encoding="utf-8", newline="") as f:
        f.write(content)


def main() -> None:
    # This gate must stay first: no label, result-cache, or price rows are read above it.
    approval, audit, preflight = verify_gates()
    anchors, validation = load_contract_data()
    prices = load_price_rows(anchors)
    anchors = anchors.merge(
        prices[["race_id", "horse_id", "odds_numeric", "gross_return_krw", "stake_krw"]],
        on=["race_id", "horse_id"], how="left", validate="one_to_one",
    )
    schedule, date_index = load_bootstrap(anchors.race_date)
    payout_cohort = anchors.loc[anchors.odds_numeric.notna()].copy()
    summaries = pd.concat([
        make_summaries(anchors, schedule, date_index, "evaluation_all"),
        make_summaries(payout_cohort, schedule, date_index, "payout_2025_2026"),
    ], ignore_index=True)
    race_rows = make_race_rows(anchors, prices)

    require(len(race_rows) == EXPECTED_RACES and int(race_rows.place_hit.sum()) == int(anchors.place_hit.sum()),
            "race-level output row count or hit reconciliation failed")
    all_row = summaries.loc[summaries.dimension.eq("all") & summaries.cohort.eq("evaluation_all")].iloc[0]
    require(all_row.race_n == EXPECTED_RACES and all_row.p_support_n == EXPECTED_TOP3_SUPPORT,
            "overall probability summary denominator mismatch")
    require(all_row.odds_race_n == EXPECTED_PRICE_RACES and all_row.stake_krw == STAKE_KRW * EXPECTED_PRICE_RACES,
            "overall price-period denominator/stake mismatch")
    require(math.isfinite(float(all_row.roi)), "overall payout ROI is non-finite")
    payout_all = summaries.loc[summaries.dimension.eq("all") & summaries.cohort.eq("payout_2025_2026")].iloc[0]
    require(payout_all.race_n == EXPECTED_PRICE_RACES and payout_all.p_support_n == 1106
            and payout_all.odds_race_n == EXPECTED_PRICE_RACES,
            "payout-cohort probability/ROI denominators mismatch")

    summary_path = OUT / "single_place_summary.csv"
    race_path = OUT / "single_place_race_results.csv"
    receipt_path = OUT / "single_place_analysis_receipt.json"
    readme_path = OUT / "single_place_analysis_README.md"
    for path in (summary_path, race_path, receipt_path, readme_path):
        require(not path.exists(), f"refusing to overwrite existing result: {path}")
    summary_text = summaries.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    race_text = race_rows.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    receipt = {
        "status": "PASS", "scope": "fixed_single_anchor_outcome_and_ROI_analysis",
        "approval_sha256": sha256(APPROVAL), "analysis_code_sha256": sha256(Path(__file__).resolve()),
        "source_audit_final_sha256": sha256(AUDIT_FINAL), "source_inventory_sha256": sha256(INVENTORY),
        "source_price_rows_sha256": sha256(PLC_ROWS), "official_runner_results_sha256": sha256(OFFICIAL_RESULTS),
        "source_audit_return_contract": audit.get("return_contract"),
        "source_price_timing": audit.get("price_timing"),
        "probability_preflight_sha256": sha256(PRELIGHT), "features_sha256": sha256(FEATURES),
        "runner_predictions_sha256": sha256(RUNNERS), "bootstrap_schedule_sha256": sha256(BOOTSTRAP),
        "bootstrap_receipt_sha256": sha256(BOOTSTRAP_RECEIPT),
        "counts": {"races": EXPECTED_RACES, "dates": EXPECTED_DATES, "runners": EXPECTED_RUNNERS,
                   "top3_probability_supported": EXPECTED_TOP3_SUPPORT,
                   "top2_probability_unavailable": EXPECTED_TOP2_UNSUPPORTED,
                   "payout_races": EXPECTED_PRICE_RACES, "payout_runner_rows": EXPECTED_PRICE_RUNNERS},
        "validation": validation,
        "fixed_contract": {"stake_krw": STAKE_KRW, "probability_bins": "fixed 0.1 increments [0,.1),...,[.9,1]",
                           "thresholds": [0.5, 0.6, 0.7, 0.8, 0.9], "bootstrap_replicates": 2000,
                           "bootstrap_unit": "race date", "fit_or_recalibration_runs": 0},
        "outputs": {"summary": {"path": str(summary_path.relative_to(ROOT)),
                                  "sha256": hashlib.sha256(summary_text.encode()).hexdigest()},
                    "race_rows": {"path": str(race_path.relative_to(ROOT)),
                                  "sha256": hashlib.sha256(race_text.encode()).hexdigest()}},
        "interpretation": "retrospective post-race descriptive results, not independent future validation",
    }
    readme = (
        "# 단일 연승 축 확률·사후 배당 결과\n\n"
        "고정 F1_STYLE6 저장 점수로 경주당 한 마리를 선택했습니다. 8두 이상은 저장된 exact-Top3 주변확률을 평가했고, "
        "7두 경주는 실제 Top2 결과·수익만 포함하며 확률은 unavailable로 남겼습니다. 확률 bins/threshold, 1,000원 고정 stake, "
        "결과/배당 원천 및 날짜 bootstrap 일정은 승인된 연구 계획에 고정되어 있습니다. PLC 가격은 API301 사후 odds quote이며 "
        "사전 공개 가능 시점은 확인되지 않았습니다. 미적중 총환급은 0원으로 계산했습니다.\n\n"
        "`single_place_summary.csv`에는 전체·연도·필드크기·확률구간·고정 threshold별 분모, 평균 확률, 적중률, 보정차이, "
        "Brier/log loss, 환급/ROI 및 날짜 CI가 있습니다. `mean_hit_odds`는 당첨마 odds multiplier 평균이고, "
        "`mean_hit_return_krw`는 적중당 총환급원입니다. 손익분기 적중률은 평균 적중 odds의 역수이며 `break_even_odds`는 실제 적중률의 역수입니다.\n\n"
        "`single_place_race_results.csv`는 경주별 선택·결과·확률·사후 odds quote·가정 총환급입니다. 이 자료는 평가에 사용된 과거 경주의 "
        "사후 기술통계이며 독립 미래검증이나 배당 전 기대수익을 뜻하지 않습니다.\n"
    )
    write_new(summary_path, summary_text)
    write_new(race_path, race_text)
    write_new(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    write_new(readme_path, readme)


if __name__ == "__main__":
    main()

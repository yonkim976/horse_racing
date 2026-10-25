"""Fixed-policy retrospective PLC analysis using frozen F1_STYLE6 predictions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
SOURCE_DIR = ROOT / "jeju/research/20261014_single_place_returns_v1"
PREDICTIONS = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/report/runner_predictions.parquet"
PLC_ROWS = SOURCE_DIR / "source_audit/PLC_PRICE_ROWS.csv"
OFFICIAL_ROWS = SOURCE_DIR / "source_audit/OFFICIAL_RUNNER_RESULTS.csv"
AUDIT_FINAL = SOURCE_DIR / "source_audit/SOURCE_AUDIT_FINAL.json"
PLC_REVIEW = SOURCE_DIR / "ROOT_PLC_SOURCE_REVIEW.json"
OFFICIAL_REVIEW = SOURCE_DIR / "ROOT_OFFICIAL_SOURCE_REVIEW.json"
BOOTSTRAP = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
ROOT_PLC_REFERENCE = STUDY / "ROOT_PLC_QUOTE_REFERENCE.csv"
ROOT_RAW_REVIEW = ROOT / "jeju/research/20261015_all_pair_postrace_value_v1/ROOT_RAW_SOURCE_REVIEW.json"

STAKE_KRW = 1000
PRICE_END = pd.Timestamp("2026-09-19")
EXPECTED_HASHES = {
    "jeju/research/20261015_all_runner_place_value_v1/PLAN.md": "f6485aac47eae9a895e1b601d2e4b2b1ed4a4b8566bd3622fd75c70869c4ebca",
    "jeju/research/20261010_style_history_ablation_v1/outputs/report/runner_predictions.parquet": "706bca01e5f5e780a8ffbe9e2ad4553fea9e3d76df097b4c9648d7aabac44e56",
    "jeju/research/20261014_single_place_returns_v1/source_audit/PLC_PRICE_ROWS.csv": "257326a9788a88f3fc6f8462c03af1f11b6b4e62e04a4e885d5d812c8bd4e52b",
    "jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv": "4ae6133d9d537f9ca6b351ed909a945b88a428cb4babcdf15659e266a68f2df6",
    "jeju/research/20261014_single_place_returns_v1/source_audit/SOURCE_AUDIT_FINAL.json": "10967bdca3609aa1f535be1815b5281c6e8f53e367f5bdc32c030e59fd589880",
    "jeju/research/20261014_single_place_returns_v1/ROOT_PLC_SOURCE_REVIEW.json": "8d6c35c5e3aff56825a5ad0eed94bfac44622b98448ee35b44f492de3534738b",
    "jeju/research/20261014_single_place_returns_v1/ROOT_OFFICIAL_SOURCE_REVIEW.json": "eda599dc6243ff7db310b1855a434aac26e22456873e9b9befc2722d34364913",
    "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy": "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
    "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json": "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e",
    "jeju/research/20261015_all_runner_place_value_v1/ROOT_PLC_QUOTE_REFERENCE.csv": "f21068f583ada9dd24287a43ed5dc28acd50cde87725163e92336b2015266f96",
    "jeju/research/20261015_all_pair_postrace_value_v1/ROOT_RAW_SOURCE_REVIEW.json": "e6437455a06d2eb1f85cc80014c2c9c5ed4ce7a2d4422d4a29ade55d7877f182",
    "jeju/research/20261015_all_runner_place_value_v1/ROOT_STRATEGY_REFERENCE.csv": "f483bb73884a2ef059ff9b2d614ba6ae549f65f456280e9f26ca7fa6c34cb84a",
    "jeju/research/20261015_all_runner_place_value_v1/ROOT_SELECTION_REFERENCE.csv": "9b480a83e54350043fb16cfb8302861cd4b4c999e6f8fb1bf30e5837dd9e3c10",
}

POLICIES = [
    ("p_rank_1", "확률 순위 1위"),
    ("p_rank_2", "확률 순위 2위"),
    ("p_rank_3", "확률 순위 3위"),
    ("p_rank_1_ev_positive", "확률 1위, EV 양수"),
    ("all_runners_max_ev_positive", "전체 출전마 중 최대 EV 양수"),
    ("top3_max_ev_positive", "확률 상위 3두 중 최대 EV 양수"),
    ("p_ge_0_40_max_ev_positive", "p≥0.40 중 최대 EV 양수"),
    ("p_ge_0_50_max_ev_positive", "p≥0.50 중 최대 EV 양수"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def verify_source_gates() -> dict[str, str]:
    paths = {
        "jeju/research/20261015_all_runner_place_value_v1/PLAN.md": STUDY / "PLAN.md",
        "jeju/research/20261010_style_history_ablation_v1/outputs/report/runner_predictions.parquet": PREDICTIONS,
        "jeju/research/20261014_single_place_returns_v1/source_audit/PLC_PRICE_ROWS.csv": PLC_ROWS,
        "jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv": OFFICIAL_ROWS,
        "jeju/research/20261014_single_place_returns_v1/source_audit/SOURCE_AUDIT_FINAL.json": AUDIT_FINAL,
        "jeju/research/20261014_single_place_returns_v1/ROOT_PLC_SOURCE_REVIEW.json": PLC_REVIEW,
        "jeju/research/20261014_single_place_returns_v1/ROOT_OFFICIAL_SOURCE_REVIEW.json": OFFICIAL_REVIEW,
        "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy": BOOTSTRAP,
        "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json": BOOTSTRAP_RECEIPT,
        "jeju/research/20261015_all_runner_place_value_v1/ROOT_PLC_QUOTE_REFERENCE.csv": ROOT_PLC_REFERENCE,
        "jeju/research/20261015_all_pair_postrace_value_v1/ROOT_RAW_SOURCE_REVIEW.json": ROOT_RAW_REVIEW,
        "jeju/research/20261015_all_runner_place_value_v1/ROOT_STRATEGY_REFERENCE.csv": STUDY / "ROOT_STRATEGY_REFERENCE.csv",
        "jeju/research/20261015_all_runner_place_value_v1/ROOT_SELECTION_REFERENCE.csv": STUDY / "ROOT_SELECTION_REFERENCE.csv",
    }
    actual: dict[str, str] = {}
    for rel, path in paths.items():
        require(path.is_file(), f"required frozen source is missing: {path}")
        actual[rel] = sha256(path)
        require(actual[rel] == EXPECTED_HASHES[rel], f"SHA-256 mismatch: {rel}")

    audit = read_json(AUDIT_FINAL)
    plc_review = read_json(PLC_REVIEW)
    official_review = read_json(OFFICIAL_REVIEW)
    raw_review = read_json(ROOT_RAW_REVIEW)
    require(audit.get("status") == "PASS", "PLC source audit is not PASS")
    require(plc_review.get("status") == "PASS" and official_review.get("status") == "PASS",
            "independent source review is not PASS")
    require(audit.get("prohibited_metrics", {}).get("outcomes_or_metrics_computed") is False,
            "source audit is not a label-free source gate")
    artifacts = audit.get("artifacts", {})
    require(artifacts.get("PLC_PRICE_ROWS.csv", {}).get("sha256") == actual[
        "jeju/research/20261014_single_place_returns_v1/source_audit/PLC_PRICE_ROWS.csv"],
        "PLC source hash disagrees with source audit")
    require(artifacts.get("OFFICIAL_RUNNER_RESULTS.csv", {}).get("sha256") == actual[
        "jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv"],
        "official result hash disagrees with source audit")
    require(audit.get("source_coverage", {}).get("priced_races") == 1142
            and audit.get("source_coverage", {}).get("priced_runner_rows") == 11083,
            "audited PLC coverage changed")
    require(audit.get("place_rule", {}).get("races_with_8_or_more_runners") == 1106
            and audit.get("place_rule", {}).get("races_with_7_or_fewer_runners") == 36,
            "audited field-size support changed")
    require(plc_review.get("every_cohort_runner_quote_present") is True
            and plc_review.get("invalid_or_special_odds") == 0,
            "PLC independent review does not verify complete, valid runner quotes")
    require(official_review.get("runner_keys_and_horse_ids_verified") == 17412
            and official_review.get("official_and_model_actual_field_sizes_match") is True,
            "official runner identity/field review changed")
    require(raw_review.get("status") == "PASS" and raw_review.get("all_plc_runner_quotes") == 11083
            and raw_review.get("plc_target_runners_complete") is True
            and raw_review.get("database_access") is False,
            "independent direct-JSON PLC source review changed")
    receipt = read_json(BOOTSTRAP_RECEIPT)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS"
            and receipt.get("seed") == 20261011 and receipt.get("draws") == 2000
            and receipt.get("dates_per_draw") == 269
            and receipt.get("source_features_sha256") ==
            "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
            "fixed 269-date bootstrap receipt changed")
    return actual


def load_label_free_cohort() -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    predictions = pd.read_parquet(
        PREDICTIONS,
        columns=["race_id", "race_date", "year", "horse_id", "horse_number", "field_n",
                 "variant", "score", "p_top3"],
    )
    predictions = predictions.loc[predictions.variant.eq("F1_STYLE6")].copy()
    require(len(predictions) == 17412 and predictions.race_id.nunique() == 1779,
            "frozen F1_STYLE6 prediction roster changed")
    predictions["race_id"] = predictions.race_id.astype("string")
    predictions["horse_id"] = predictions.horse_id.astype("string")
    predictions["horse_number"] = pd.to_numeric(predictions.horse_number, errors="raise").astype("int64")
    predictions["field_n"] = pd.to_numeric(predictions.field_n, errors="raise").astype("int64")
    predictions["score"] = pd.to_numeric(predictions.score, errors="raise")
    predictions["p_top3"] = pd.to_numeric(predictions.p_top3, errors="raise")
    predictions["race_date"] = pd.to_datetime(predictions.race_date, errors="raise").dt.normalize()
    predictions["year"] = predictions.race_date.dt.year.astype("int64")
    require(not predictions[["race_id", "horse_id", "horse_number"]].duplicated().any(),
            "prediction runner key is duplicated")
    require(np.isfinite(predictions.score.to_numpy(float)).all(), "prediction score is not finite")
    require(predictions.groupby("race_id").size().eq(predictions.groupby("race_id").field_n.first()).all(),
            "prediction field size differs from frozen runner roster")
    date_inventory = sorted(predictions.race_date.dt.strftime("%Y-%m-%d").unique().tolist())
    require(len(date_inventory) == 269, "frozen prediction date inventory changed")

    prices = pd.read_csv(
        PLC_ROWS,
        usecols=["race_id", "race_date_local", "horse_number", "kra_horse_id", "odds", "source_sha256",
                 "odds_unit", "pool_code", "official_field_size"],
        dtype={"race_id": "string", "kra_horse_id": "string", "pool_code": "string"},
    )
    prices = prices.loc[prices.pool_code.eq("PLC")].copy()
    prices["race_date"] = pd.to_datetime(prices.race_date_local, errors="raise").dt.normalize()
    prices["year"] = prices.race_date.dt.year.astype("int64")
    prices["horse_number"] = pd.to_numeric(prices.horse_number, errors="raise").astype("int64")
    prices["field_n"] = pd.to_numeric(prices.official_field_size, errors="raise").astype("int64")
    prices["odds"] = pd.to_numeric(prices.odds, errors="coerce")
    prices = prices.loc[prices.race_date.dt.year.isin([2025, 2026])
                        & prices.race_date.le(PRICE_END)].copy()
    require(len(prices) == 11083 and prices.race_id.nunique() == 1142,
            "frozen PLC source period/count changed")
    require(not prices[["race_id", "kra_horse_id", "horse_number"]].isna().any().any()
            and not prices.duplicated(["race_id", "kra_horse_id", "horse_number"]).any(),
            "PLC source runner keys are missing or duplicated")
    require(prices.odds.notna().all() and np.isfinite(prices.odds.to_numpy(float)).all()
            and prices.odds.gt(0).all() and not prices.odds.eq(9999.9).any(),
            "PLC source contains zero, special, null or invalid odds")
    require(prices.odds_unit.eq("decimal_gross_return_multiple_per_stake_unit").all(),
            "PLC source odds unit changed")
    require(prices.groupby("race_id").size().eq(prices.groupby("race_id").field_n.first()).all(),
            "PLC prices do not cover every runner in each priced race")

    raw_reference = pd.read_csv(
        ROOT_PLC_REFERENCE,
        usecols=["race_id", "horse_number", "raw_quote", "source_sha256"],
        dtype={"race_id": "string", "source_sha256": "string"},
    )
    raw_reference["horse_number"] = pd.to_numeric(raw_reference.horse_number, errors="raise").astype("int64")
    raw_reference["raw_quote"] = pd.to_numeric(raw_reference.raw_quote, errors="raise")
    require(len(raw_reference) == 11083
            and not raw_reference.duplicated(["race_id", "horse_number"]).any(),
            "root direct-JSON quote reference has missing or duplicate keys")
    raw_compare = prices.merge(
        raw_reference, on=["race_id", "horse_number"], how="outer", validate="one_to_one",
        indicator=True, suffixes=("_audit", "_root"),
    )
    require(raw_compare._merge.eq("both").all()
            and raw_compare.odds.eq(raw_compare.raw_quote).all()
            and raw_compare.source_sha256_audit.eq(raw_compare.source_sha256_root).all(),
            "audited PLC rows differ from root's independent direct-JSON quote reference")

    joined = prices.merge(
        predictions[["race_id", "horse_id", "horse_number", "race_date", "year", "field_n",
                     "score", "p_top3"]],
        left_on=["race_id", "kra_horse_id", "horse_number"],
        right_on=["race_id", "horse_id", "horse_number"],
        how="left", validate="one_to_one", indicator=True, suffixes=("_price", "_prediction"),
    )
    require(joined._merge.eq("both").all() and len(joined) == 11083,
            "PLC price cohort does not join to every frozen model runner")
    require(joined.field_n_price.eq(joined.field_n_prediction).all(),
            "model field size differs from PLC complete runner roster")
    require(joined.race_date_price.eq(joined.race_date_prediction).all()
            and joined.year_price.eq(joined.year_prediction).all(),
            "model and PLC race dates disagree")
    supported = joined.loc[joined.field_n_price.ge(8)].copy()
    unsupported = joined.loc[joined.field_n_price.le(7)]
    require(supported.race_id.nunique() == 1106 and len(supported) == 10831
            and unsupported.race_id.nunique() == 36 and len(unsupported) == 252,
            "Top3 supported/unsupported PLC cohort counts changed")
    require(supported.p_top3.notna().all() and np.isfinite(supported.p_top3.to_numpy(float)).all()
            and supported.p_top3.between(0, 1).all(),
            "native Top3 runner probabilities are unavailable or outside [0, 1]")
    require(supported.groupby("race_id").size().eq(supported.groupby("race_id").field_n_price.first()).all(),
            "supported price races do not contain complete fields")

    # Rank by the frozen model score; exact score ties go to the lower horse number.
    # Tiny representation differences in saved marginal probabilities do not break a score tie.
    ranked_parts: list[pd.DataFrame] = []
    for _, race in supported.groupby("race_id", sort=True):
        race = race.sort_values(["score", "horse_number"], ascending=[False, True], kind="stable").copy()
        race["probability_rank"] = np.arange(1, len(race) + 1, dtype="int64")
        race["model_ev"] = race.p_top3 * race.odds - 1.0
        ranked_parts.append(race)
    ranked = pd.concat(ranked_parts, ignore_index=True)
    raw_reference_check = {
        "root_direct_json_quote_rows": int(len(raw_reference)),
        "exact_race_horse_number_quote_and_page_sha_matches": int(len(raw_compare)),
        "missing_or_duplicate_or_mismatched_raw_quotes": 0,
    }
    return ranked, date_inventory, raw_reference_check


def best_ev(candidates: pd.DataFrame) -> tuple[pd.Series | None, int]:
    positive = candidates.loc[candidates.model_ev.gt(0)].copy()
    if positive.empty:
        return None, 0
    positive = positive.sort_values(
        ["model_ev", "probability_rank", "horse_number"],
        ascending=[False, True, True], kind="stable",
    )
    return positive.iloc[0], len(positive)


def select_fixed_policies(runners: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for race_id, race in runners.groupby("race_id", sort=True):
        race = race.sort_values("probability_rank", kind="stable")
        rank1 = race.loc[race.probability_rank.eq(1)].iloc[0]
        candidates_by_policy: list[tuple[str, pd.Series | None, int, str]] = []
        for rank in (1, 2, 3):
            candidates_by_policy.append((f"p_rank_{rank}", race.loc[race.probability_rank.eq(rank)].iloc[0],
                                         1, f"fixed_probability_rank_{rank}"))
        rank1_pick = rank1 if rank1.model_ev > 0 else None
        candidates_by_policy.append(("p_rank_1_ev_positive", rank1_pick,
                                     int(rank1_pick is not None),
                                     "rank1_ev_positive" if rank1_pick is not None else "rank1_ev_not_positive"))
        pick, count = best_ev(race)
        candidates_by_policy.append(("all_runners_max_ev_positive", pick, count,
                                     "max_positive_ev" if pick is not None else "no_positive_ev_candidate"))
        pick, count = best_ev(race.loc[race.probability_rank.le(3)])
        candidates_by_policy.append(("top3_max_ev_positive", pick, count,
                                     "max_positive_ev" if pick is not None else "no_positive_ev_candidate"))
        for threshold, policy_id in [(0.40, "p_ge_0_40_max_ev_positive"),
                                     (0.50, "p_ge_0_50_max_ev_positive")]:
            candidates = race.loc[race.p_top3.ge(threshold)]
            pick, count = best_ev(candidates)
            candidates_by_policy.append((policy_id, pick, count,
                                         "max_positive_ev" if pick is not None else "no_positive_ev_candidate"))

        for policy_id, pick, eligible_count, reason in candidates_by_policy:
            row: dict[str, Any] = {
                "race_id": str(race_id),
                "race_date": race.race_date_price.iloc[0],
                "year": int(race.year_price.iloc[0]),
                "field_n": int(race.field_n_price.iloc[0]),
                "policy_id": policy_id,
                "eligible_candidate_count": int(eligible_count),
                "selected": pick is not None,
                "selection_reason": reason,
            }
            if pick is None:
                row.update({
                    "horse_id": None, "horse_number": None, "probability_rank": None,
                    "score": None, "p_top3": None, "plc_odds": None, "model_ev": None,
                })
            else:
                row.update({
                    "horse_id": str(pick.kra_horse_id),
                    "horse_number": int(pick.horse_number),
                    "probability_rank": int(pick.probability_rank),
                    "score": float(pick.score),
                    "p_top3": float(pick.p_top3),
                    "plc_odds": float(pick.odds),
                    "model_ev": float(pick.model_ev),
                })
            rows.append(row)
    selected = pd.DataFrame(rows)
    expected_rows = runners.race_id.nunique() * len(POLICIES)
    require(len(selected) == expected_rows, "fixed policy selection grid is incomplete")
    require(selected.groupby(["race_id", "policy_id"]).size().eq(1).all(),
            "fixed policy has more than one row per race")
    return selected


def attach_outcomes(selected: pd.DataFrame, runners: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    # Outcome fields are first opened after all policy choices have been materialized.
    official = pd.read_csv(
        OFFICIAL_ROWS,
        usecols=["race_id", "race_date_local", "horse_number", "kra_horse_id", "field_size", "status",
                 "finish_position", "scratched", "disqualified"],
        dtype={"race_id": "string", "kra_horse_id": "string"},
    )
    official["horse_number"] = pd.to_numeric(official.horse_number, errors="raise").astype("int64")
    official["field_size"] = pd.to_numeric(official.field_size, errors="raise").astype("int64")
    official["race_date_local"] = pd.to_datetime(official.race_date_local, errors="raise").dt.normalize()
    official["finish_position"] = pd.to_numeric(official.finish_position, errors="raise")
    require(len(official) == 17412 and not official.duplicated(
        ["race_id", "kra_horse_id", "horse_number"]).any(), "official runner key changed")
    require(official.status.eq("completed").all()
            and pd.to_numeric(official.scratched, errors="raise").eq(0).all()
            and pd.to_numeric(official.disqualified, errors="raise").eq(0).all(),
            "official source includes incomplete or nonstarter rows")

    cohort = runners[["race_id", "race_date_price", "year_price", "field_n_price", "kra_horse_id",
                      "horse_number", "probability_rank", "score", "p_top3", "odds", "model_ev"]].copy()
    cohort = cohort.merge(
        official,
        on=["race_id", "kra_horse_id", "horse_number"], how="left",
        validate="one_to_one", indicator=True, suffixes=("_model", "_official"),
    )
    require(cohort._merge.eq("both").all() and len(cohort) == len(runners),
            "supported PLC cohort does not join to the official result roster")
    require(cohort.field_n_price.eq(cohort.field_size).all(),
            "official field size differs from the complete price/model cohort")
    require(cohort.race_date_price.eq(cohort.race_date_local).all(),
            "official and model race dates disagree")
    require(cohort.finish_position.notna().all() and cohort.finish_position.gt(0).all(),
            "official finish positions are incomplete")
    cohort = cohort.drop(columns=["_merge"])

    source_outcomes = pd.read_csv(
        PLC_ROWS,
        usecols=["race_id", "horse_number", "kra_horse_id", "official_finish_position",
                 "qualifies_under_project_place_rule", "official_scratched", "official_disqualified"],
        dtype={"race_id": "string", "kra_horse_id": "string"},
    )
    source_outcomes["horse_number"] = pd.to_numeric(source_outcomes.horse_number, errors="raise").astype("int64")
    source_outcomes["official_finish_position"] = pd.to_numeric(
        source_outcomes.official_finish_position, errors="raise")
    source_outcomes["qualifies_under_project_place_rule"] = (
        source_outcomes.qualifies_under_project_place_rule.astype("string").str.strip().str.lower()
        .map({"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False})
    )
    require(source_outcomes.qualifies_under_project_place_rule.notna().all(),
            "PLC source outcome qualifier contains invalid values")
    source_outcomes["official_scratched"] = pd.to_numeric(source_outcomes.official_scratched, errors="raise")
    source_outcomes["official_disqualified"] = pd.to_numeric(source_outcomes.official_disqualified, errors="raise")
    check = cohort.merge(
        source_outcomes,
        on=["race_id", "kra_horse_id", "horse_number"], how="left",
        validate="one_to_one", indicator=True,
    )
    require(check._merge.eq("both").all(), "official outcome source does not cover selected cohort")
    expected_hit = check.finish_position.le(3)
    require(np.array_equal(check.finish_position.to_numpy(), check.official_finish_position.to_numpy()),
            "official rank and audited PLC source rank disagree")
    require(np.array_equal(expected_hit.to_numpy(bool),
                           check.qualifies_under_project_place_rule.to_numpy(bool)),
            "official finish position and audited PLC eligibility disagree")
    require(check.official_scratched.eq(0).all() and check.official_disqualified.eq(0).all(),
            "PLC outcome source includes scratched or disqualified runners")
    cohort["hit"] = cohort.finish_position.le(3)
    cohort["gross_return_krw"] = np.where(cohort.hit, STAKE_KRW * cohort.odds, 0.0)
    cohort["stake_krw"] = STAKE_KRW
    outcome_cols = cohort[["race_id", "kra_horse_id", "horse_number", "finish_position", "hit",
                           "gross_return_krw", "stake_krw"]]

    selected = selected.merge(
        outcome_cols,
        left_on=["race_id", "horse_id", "horse_number"],
        right_on=["race_id", "kra_horse_id", "horse_number"],
        how="left", validate="many_to_one", indicator=True,
    )
    picked = selected.selected
    require(selected.loc[picked, "_merge"].eq("both").all(),
            "selected horse does not join to official result")
    require(selected.loc[~picked, "_merge"].eq("left_only").all(),
            "unselected rows unexpectedly have result labels")
    selected = selected.drop(columns=["_merge", "kra_horse_id"])
    selected["gross_return_krw"] = selected.gross_return_krw.fillna(0.0)
    selected["stake_krw"] = selected.stake_krw.fillna(0.0)
    selected["net_profit_krw"] = selected.gross_return_krw - selected.stake_krw
    selected["hit"] = selected.hit.astype("boolean")
    return selected, {
        "official_price_runner_rows_joined": int(len(check)),
        "official_rank_price_eligibility_match": True,
        "supported_cohort_finish_ties": int(cohort.duplicated(["race_id", "finish_position"]).sum()),
        "race_field_counts": cohort.groupby("race_id").size().value_counts().sort_index().to_dict(),
    }


def load_date_bootstrap(date_inventory: list[str]) -> tuple[np.ndarray, dict[str, int]]:
    receipt = read_json(BOOTSTRAP_RECEIPT)
    date_hash = hashlib.sha256("\n".join(date_inventory).encode("utf-8")).hexdigest()
    require(receipt.get("date_inventory_sha256") == date_hash and len(date_inventory) == 269,
            "bootstrap date order does not match the fixed evaluation schedule")
    draws = np.load(BOOTSTRAP, allow_pickle=False)
    require(draws.shape == (2000, 269) and draws.dtype.kind in "iu"
            and draws.min() >= 0 and draws.max() < 269,
            "fixed date-bootstrap array changed")
    weights = np.stack([np.bincount(draw, minlength=269) for draw in draws]).astype(np.int64)
    require(np.all(weights.sum(axis=1) == 269), "bootstrap draws do not contain 269 dates")
    return weights, {date: i for i, date in enumerate(date_inventory)}


def bootstrap_interval(group: pd.DataFrame, weights: np.ndarray,
                       date_index: dict[str, int]) -> dict[str, Any]:
    if group.empty:
        return {"hit_valid": 0, "hit_zero_stake": 2000, "hit_low_pct": None, "hit_high_pct": None,
                "roi_valid": 0, "roi_zero_stake": 2000, "roi_low_pct": None, "roi_high_pct": None}
    date_ids = group.race_date.astype("string").map(date_index).to_numpy(dtype=np.int64)
    row_weights = weights[:, date_ids]
    selected = group.selected.to_numpy(dtype=np.float64)
    hit = group.hit.fillna(False).to_numpy(dtype=np.float64) * selected
    gross = group.gross_return_krw.to_numpy(dtype=np.float64)
    stakes = group.stake_krw.to_numpy(dtype=np.float64)
    count_draw = row_weights @ selected
    hit_draw = row_weights @ hit
    gross_draw = row_weights @ gross
    stake_draw = row_weights @ stakes
    hit_rate = np.divide(hit_draw, count_draw, out=np.full_like(hit_draw, np.nan), where=count_draw > 0)
    roi = np.divide(gross_draw, stake_draw, out=np.full_like(gross_draw, np.nan), where=stake_draw > 0) - 1.0
    valid_hit = np.isfinite(hit_rate)
    valid_roi = np.isfinite(roi)
    return {
        "hit_valid": int(valid_hit.sum()), "hit_zero_stake": int((~valid_hit).sum()),
        "hit_low_pct": float(np.nanpercentile(hit_rate, 2.5) * 100) if valid_hit.any() else None,
        "hit_high_pct": float(np.nanpercentile(hit_rate, 97.5) * 100) if valid_hit.any() else None,
        "roi_valid": int(valid_roi.sum()), "roi_zero_stake": int((~valid_roi).sum()),
        "roi_low_pct": float(np.nanpercentile(roi, 2.5) * 100) if valid_roi.any() else None,
        "roi_high_pct": float(np.nanpercentile(roi, 97.5) * 100) if valid_roi.any() else None,
    }


def summary_row(group: pd.DataFrame, policy_id: str, policy_name: str, period: str,
                expected_races: int, weights: np.ndarray, date_index: dict[str, int]) -> dict[str, Any]:
    bets = group.loc[group.selected].copy()
    n_bets = len(bets)
    stake = float(bets.stake_krw.sum())
    gross = float(bets.gross_return_krw.sum())
    hits = int(bets.hit.fillna(False).sum())
    ci = bootstrap_interval(group, weights, date_index)
    if n_bets:
        hit_rate = 100.0 * hits / n_bets
        roi = 100.0 * (gross / stake - 1.0)
        mean_p = float(100.0 * bets.p_top3.mean())
        mean_odds = float(bets.plc_odds.mean())
        mean_ev = float(100.0 * bets.model_ev.mean())
        expected_net = float((bets.model_ev * bets.stake_krw).sum())
    else:
        hit_rate = roi = mean_p = mean_odds = mean_ev = expected_net = None
    positive_returns = np.sort(
        bets.loc[bets.gross_return_krw.gt(0), "gross_return_krw"].to_numpy(dtype=float)
    )[::-1]
    sensitivity: dict[str, Any] = {}
    for top_k in (1, 3, 5):
        removed_returns = positive_returns[:top_k]
        removed_gross = float(removed_returns.sum())
        removed_stake = float(len(removed_returns) * STAKE_KRW)
        remaining_stake = stake - removed_stake
        sensitivity[f"roi_excluding_top_{top_k}_paid_bets_pct"] = (
            100.0 * ((gross - removed_gross) / remaining_stake - 1.0)
            if remaining_stake > 0 else None
        )
        sensitivity[f"gross_removed_top_{top_k}_krw"] = removed_gross
        sensitivity[f"stake_removed_top_{top_k}_krw"] = removed_stake
    row = {
        "period": period,
        "policy_id": policy_id,
        "policy": policy_name,
        "eligible_races": int(expected_races),
        "selected_races": int(n_bets),
        "no_bet_races": int(expected_races - n_bets),
        "coverage_pct": 100.0 * n_bets / expected_races if expected_races else None,
        "hits": hits,
        "hit_rate_pct": hit_rate,
        "hit_ci95_low_pct": ci["hit_low_pct"],
        "hit_ci95_high_pct": ci["hit_high_pct"],
        "mean_p_top3_pct": mean_p,
        "mean_plc_odds": mean_odds,
        "mean_model_ev_pct": mean_ev,
        "model_expected_net_krw": expected_net,
        "stake_krw": stake,
        "gross_return_krw": gross,
        "net_profit_krw": gross - stake,
        "roi_pct": roi,
        "roi_ci95_low_pct": ci["roi_low_pct"],
        "roi_ci95_high_pct": ci["roi_high_pct"],
        "hit_ci_valid_draws": ci["hit_valid"],
        "hit_ci_zero_eligible_draws": ci["hit_zero_stake"],
        "roi_ci_valid_draws": ci["roi_valid"],
        "roi_ci_zero_stake_draws": ci["roi_zero_stake"],
        **sensitivity,
    }
    return row


def make_summary(selected: pd.DataFrame, weights: np.ndarray,
                 date_index: dict[str, int]) -> pd.DataFrame:
    names = dict(POLICIES)
    rows: list[dict[str, Any]] = []
    periods = [("all", None), ("2025", 2025), ("2026_partial", 2026)]
    for period, year in periods:
        period_rows = selected if year is None else selected.loc[selected.year.eq(year)]
        n_races = int(period_rows.race_id.nunique())
        for policy_id, _ in POLICIES:
            policy_rows = period_rows.loc[period_rows.policy_id.eq(policy_id)].copy()
            rows.append(summary_row(policy_rows, policy_id, names[policy_id], period,
                                    n_races, weights, date_index))
    return pd.DataFrame(rows)


def make_case_examples(selected: pd.DataFrame) -> pd.DataFrame:
    rank3 = selected.loc[selected.policy_id.eq("p_rank_3")].copy()
    rank1 = selected.loc[selected.policy_id.eq("p_rank_1"),
                         ["race_id", "horse_number", "p_top3", "plc_odds", "model_ev",
                          "finish_position", "hit", "gross_return_krw"]].copy()
    rank1 = rank1.rename(columns={
        "horse_number": "rank1_horse_number", "p_top3": "rank1_p_top3",
        "plc_odds": "rank1_plc_odds", "model_ev": "rank1_model_ev",
        "finish_position": "rank1_finish_position", "hit": "rank1_hit",
        "gross_return_krw": "rank1_gross_return_krw",
    })
    rank3 = rank3.merge(rank1, on="race_id", how="left", validate="one_to_one")
    rank3 = rank3.sort_values(["race_date", "race_id"], kind="stable")
    n_each = min(10, int(rank3.hit.fillna(False).sum()), int((~rank3.hit.fillna(False)).sum()))
    require(n_each > 0, "rank-3 result sample cannot be balanced across hits and misses")
    samples: list[pd.DataFrame] = []
    for outcome, label in [(True, "hit"), (False, "miss")]:
        part = rank3.loc[rank3.hit.fillna(False).eq(outcome)].copy()
        indexes = np.linspace(0, len(part) - 1, num=n_each).round().astype(int)
        example = part.iloc[indexes].copy()
        example["rank3_result_group"] = label
        example["example_sampling"] = "evenly spaced by race date within hit/miss group"
        samples.append(example)
    columns = [
        "race_date", "race_id", "year", "field_n", "rank3_result_group", "example_sampling",
        "horse_number", "p_top3", "plc_odds", "model_ev", "finish_position", "hit",
        "gross_return_krw", "net_profit_krw", "rank1_horse_number", "rank1_p_top3",
        "rank1_plc_odds", "rank1_model_ev", "rank1_finish_position", "rank1_hit",
        "rank1_gross_return_krw",
    ]
    result = pd.concat(samples, ignore_index=True).rename(columns={
        "horse_number": "rank3_horse_number", "p_top3": "rank3_p_top3",
        "plc_odds": "rank3_plc_odds", "model_ev": "rank3_model_ev",
        "finish_position": "rank3_finish_position", "hit": "rank3_hit",
        "gross_return_krw": "rank3_gross_return_krw", "net_profit_krw": "rank3_net_profit_krw",
    })
    columns = [c.replace("horse_number", "horse_number") for c in columns]
    columns = [
        "race_date", "race_id", "year", "field_n", "rank3_result_group", "example_sampling",
        "rank3_horse_number", "rank3_p_top3", "rank3_plc_odds", "rank3_model_ev",
        "rank3_finish_position", "rank3_hit", "rank3_gross_return_krw", "rank3_net_profit_krw",
        "rank1_horse_number", "rank1_p_top3", "rank1_plc_odds", "rank1_model_ev",
        "rank1_finish_position", "rank1_hit", "rank1_gross_return_krw",
    ]
    return result[columns].sort_values(["rank3_result_group", "race_date", "race_id"], kind="stable")


def crosscheck_root_references(selected: pd.DataFrame, summary: pd.DataFrame) -> dict[str, Any]:
    summary_path = STUDY / "ROOT_STRATEGY_REFERENCE.csv"
    selection_path = STUDY / "ROOT_SELECTION_REFERENCE.csv"
    require(sha256(summary_path) == EXPECTED_HASHES[
        "jeju/research/20261015_all_runner_place_value_v1/ROOT_STRATEGY_REFERENCE.csv"],
        "root independent strategy reference hash changed")
    require(sha256(selection_path) == EXPECTED_HASHES[
        "jeju/research/20261015_all_runner_place_value_v1/ROOT_SELECTION_REFERENCE.csv"],
        "root independent selection reference hash changed")
    summary_ref = pd.read_csv(summary_path)
    selection_ref = pd.read_csv(selection_path, dtype={"race_id": "string"})
    require(len(summary_ref) == 24 and len(selection_ref) == 6183,
            "root independent strategy/selection reference row count changed")
    strategy_map = {
        "rank_1": "p_rank_1", "rank_2": "p_rank_2", "rank_3": "p_rank_3",
        "rank_1_ev_positive": "p_rank_1_ev_positive", "max_ev_all": "all_runners_max_ev_positive",
        "max_ev_top3": "top3_max_ev_positive", "max_ev_p040": "p_ge_0_40_max_ev_positive",
        "max_ev_p050": "p_ge_0_50_max_ev_positive",
    }
    period_map = {"all": "all", "2025": "2025", "2026": "2026_partial"}
    summary_pairs = {
        "eligible_races": "eligible_races", "bets": "selected_races", "hits": "hits",
        "stake": "stake_krw", "gross": "gross_return_krw", "net": "net_profit_krw",
        "roi": "roi_pct", "mean_p": "mean_p_top3_pct", "mean_edge": "mean_model_ev_pct",
        "mean_quote": "mean_plc_odds", "valid_draws": "roi_ci_valid_draws",
        "undefined_draws": "roi_ci_zero_stake_draws", "roi_ci_low": "roi_ci95_low_pct",
        "roi_ci_high": "roi_ci95_high_pct", "hit_rate_ci_low": "hit_ci95_low_pct",
        "hit_rate_ci_high": "hit_ci95_high_pct",
        "roi_without_top1_hits": "roi_excluding_top_1_paid_bets_pct",
        "roi_without_top3_hits": "roi_excluding_top_3_paid_bets_pct",
        "roi_without_top5_hits": "roi_excluding_top_5_paid_bets_pct",
    }
    summary_ref = summary_ref.rename(columns={name: f"{name}_root" for name in summary_pairs})
    summary_ours = summary.copy()
    summary_ours["root_strategy"] = summary_ours.policy_id.map({v: k for k, v in strategy_map.items()})
    summary_ours["root_period"] = summary_ours.period.map({v: k for k, v in period_map.items()})
    merged_summary = summary_ref.merge(
        summary_ours, left_on=["strategy", "period"], right_on=["root_strategy", "root_period"],
        how="outer", validate="one_to_one", indicator=True,
    )
    require(merged_summary._merge.eq("both").all(), "root strategy summary rows do not match")
    numeric_mismatches: dict[str, int] = {}
    for left, right in summary_pairs.items():
        scale = 100.0 if right.endswith("_pct") else 1.0
        a = pd.to_numeric(merged_summary[f"{left}_root"], errors="coerce").to_numpy(float)
        b = pd.to_numeric(merged_summary[right], errors="coerce").to_numpy(float) / scale
        numeric_mismatches[left] = int((~np.isclose(a, b, rtol=0, atol=1e-10, equal_nan=True)).sum())
    require(not any(numeric_mismatches.values()),
            f"root summary values differ: {numeric_mismatches}")

    ours = selected.loc[selected.selected].copy()
    ours["root_strategy"] = ours.policy_id.map({v: k for k, v in strategy_map.items()})
    ours = ours.rename(columns={
        "horse_number": "horse_i_ours", "p_top3": "p_ours", "plc_odds": "quote_ours",
        "model_ev": "edge_ours", "hit": "y_ours", "gross_return_krw": "gross_ours",
    })
    ref = selection_ref.loc[selection_ref.horse_j.eq(0)].copy()
    merged_selection = ours.merge(
        ref, left_on=["root_strategy", "race_id"], right_on=["strategy", "race_id"],
        how="outer", validate="one_to_one", indicator=True, suffixes=("_ours", "_root"),
    )
    require(merged_selection._merge.eq("both").all(),
            "root independent selection rows do not match fixed policy selections")
    row_checks = {
        "horse_number": np.array_equal(merged_selection.horse_i_ours.to_numpy(),
                                       merged_selection.horse_i.to_numpy()),
        "probability": np.allclose(merged_selection.p_ours.to_numpy(float),
                                   merged_selection.p.to_numpy(float), rtol=0, atol=1e-12),
        "quote": np.array_equal(merged_selection.quote_ours.to_numpy(float),
                                merged_selection.quote.to_numpy(float)),
        "model_ev": np.allclose(merged_selection.edge_ours.to_numpy(float),
                                merged_selection.edge.to_numpy(float), rtol=0, atol=1e-12),
        "hit": np.array_equal(merged_selection.y_ours.fillna(False).to_numpy(bool),
                              merged_selection.y_pair.to_numpy(bool)),
        "gross_return": np.array_equal(merged_selection.gross_ours.to_numpy(float),
                                       merged_selection.gross.to_numpy(float)),
    }
    require(all(row_checks.values()), f"root independent selection values differ: {row_checks}")
    return {
        "root_strategy_summary_rows_exact": int(len(merged_summary)),
        "root_selected_bets_exact": int(len(merged_selection)),
        "summary_field_mismatch_counts": numeric_mismatches,
        "selection_field_checks": row_checks,
        "root_reference_hashes": {
            "ROOT_STRATEGY_REFERENCE.csv": sha256(summary_path),
            "ROOT_SELECTION_REFERENCE.csv": sha256(selection_path),
        },
    }


def main() -> None:
    input_hashes = verify_source_gates()
    runners, date_inventory, raw_reference_check = load_label_free_cohort()
    selected = select_fixed_policies(runners)
    weights, date_index = load_date_bootstrap(date_inventory)
    selected, outcome_checks = attach_outcomes(selected, runners)
    summary = make_summary(selected, weights, date_index)
    examples = make_case_examples(selected)
    root_crosscheck = crosscheck_root_references(selected, summary)

    selected_path = STUDY / "selected_rows.csv"
    examples_path = STUDY / "case_examples.csv"
    summary_path = STUDY / "summary.csv"
    selected.to_csv(selected_path, index=False, encoding="utf-8")
    examples.to_csv(examples_path, index=False, encoding="utf-8")
    summary.to_csv(summary_path, index=False, encoding="utf-8", float_format="%.10g")

    tie_groups = runners.groupby(["race_id", "score"], sort=False).p_top3.nunique()
    tie_probability = runners.groupby(["race_id", "score"], sort=False).p_top3.agg(["min", "max", "count"])
    tie_probability = tie_probability.loc[(tie_probability["count"] > 1)
                                          & tie_probability["max"].gt(tie_probability["min"])]
    tie_ulp_spreads = ((tie_probability["max"] - tie_probability["min"])
                       / np.spacing(tie_probability["max"])).round().astype(int)
    rank_by_p = runners.sort_values(["race_id", "p_top3", "horse_number"],
                                    ascending=[True, False, True], kind="stable")
    rank_by_p["rank_by_p"] = rank_by_p.groupby("race_id", sort=False).cumcount() + 1
    rank_by_score = runners.sort_values(["race_id", "score", "horse_number"],
                                        ascending=[True, False, True], kind="stable")
    rank_by_score["rank_by_score"] = rank_by_score.groupby("race_id", sort=False).cumcount() + 1
    rank_compare = rank_by_p[["race_id", "horse_number", "rank_by_p"]].merge(
        rank_by_score[["race_id", "horse_number", "rank_by_score"]],
        on=["race_id", "horse_number"], validate="one_to_one",
    )
    strategy_report: dict[str, Any] = {}
    for policy_id, _ in POLICIES:
        row = summary.loc[summary.period.eq("all") & summary.policy_id.eq(policy_id)].iloc[0]
        strategy_report[policy_id] = {
            key: (None if pd.isna(value) else float(value) if isinstance(value, (float, np.floating))
                  else int(value) if isinstance(value, (int, np.integer)) else value)
            for key, value in row.to_dict().items()
        }
    report = {
        "status": "PASS",
        "study": "F1_STYLE6 all-runner native Top3 probability and post-race PLC price analysis",
        "probability_semantics": "saved native Top3 set marginal; not per-runner sigmoid",
        "cohort": {
            "period": "2025 through 2026-09-19",
            "price_races_before_probability_support": 1142,
            "price_runner_rows_before_probability_support": 11083,
            "top3_supported_races": int(runners.race_id.nunique()),
            "top3_supported_runner_rows": int(len(runners)),
            "top3_supported_dates": int(runners.race_date_price.nunique()),
            "excluded_small_field_races_without_native_top2_probability": 36,
            "excluded_small_field_runner_rows": 252,
            "year_races": {str(int(year)): int(count) for year, count in
                           runners.groupby("year_price").race_id.nunique().items()},
        },
        "independent_raw_quote_crosscheck": raw_reference_check,
        "selection": {
            "policy_count": len(POLICIES),
            "flat_stake_krw": STAKE_KRW,
            "ev_definition": "p_top3 * raw PLC quote - 1",
            "probability_rank_tie_rule": "same saved model score: lower horse number first",
            "ev_tie_rule": "maximum EV, then probability rank, then lower horse number",
            "score_tie_groups": int((runners.groupby(["race_id", "score"]).size() > 1).sum()),
            "score_tie_groups_with_probability_variation": int((tie_groups > 1).sum()),
            "score_tie_probability_variation_groups": int(len(tie_probability)),
            "score_tie_probability_spread_ulp_min": int(tie_ulp_spreads.min()) if len(tie_ulp_spreads) else None,
            "score_tie_probability_spread_ulp_max": int(tie_ulp_spreads.max()) if len(tie_ulp_spreads) else None,
            "rows_whose_order_would_differ_if_ranked_by_saved_probability_directly": int(
                rank_compare.rank_by_p.ne(rank_compare.rank_by_score).sum()),
            "fixed_probability_boundaries": [0.40, 0.50],
        },
        "returns": {
            "qualifying_finish": "official finish position <= 3 for field size >= 8",
            "hit_gross_return_krw": "1000 * final raw PLC quote, including principal",
            "miss_gross_return_krw": 0,
            "roi_definition": "gross return / actual stake - 1",
            "taxes": "excluded",
            "price_timing": "final post-race stored quote; pre-purchase availability unverified",
            **outcome_checks,
        },
        "independent_root_reproduction": root_crosscheck,
        "uncertainty": {
            "method": "reuse fixed race-date bootstrap schedule",
            "dates_in_schedule": 269,
            "resamples": 2000,
            "interval": "95% percentile interval; displayed in percent",
            "zero_stake_draws": "reported for ROI; those draws have undefined ROI",
            "outlier_sensitivity": "exclude each of the largest 1, 3 or 5 winning wager rows, including their stake",
            "difference_intervals": "none computed; each policy is summarized independently",
        },
        "summary_table": {
            "header_columns": int(len(summary.columns)),
            "data_rows": int(len(summary)),
            "expected_data_rows": int(len(POLICIES) * 3),
            "header_row_count_matches_data_schema": True,
            "ci_units": "hit rate and ROI intervals are percent; no difference CI is reported",
        },
        "case_examples": {
            "policy": "p_rank_3",
            "rows": int(len(examples)),
            "hit_rows": int(examples.rank3_hit.sum()),
            "miss_rows": int((~examples.rank3_hit).sum()),
            "sampling": "up to ten evenly spaced chronological examples per outcome group",
            "includes_probability_rank_1_comparator": True,
        },
        "policies": strategy_report,
        "interpretation": [
            "This is retrospective development-cohort analysis, not independent future validation.",
            "Final PLC quotes have no verified pre-race publication time, so EV selection is not a demonstrated buy-before-race strategy.",
            "2026 is partial through 2026-09-19; no threshold search or best-boundary recommendation was performed.",
        ],
        "output_hashes": {
            "selected_rows.csv": sha256(selected_path),
            "case_examples.csv": sha256(examples_path),
            "summary.csv": sha256(summary_path),
            "README.md": sha256(STUDY / "README.md"),
        },
    }
    report_path = STUDY / "REPORT.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")

    input_hashes["jeju/research/20261015_all_runner_place_value_v1/analysis.py"] = sha256(STUDY / "analysis.py")
    input_hashes["jeju/research/20261015_all_runner_place_value_v1/README.md"] = sha256(STUDY / "README.md")
    input_hashes["jeju/research/20261015_all_runner_place_value_v1/REPORT.json"] = sha256(report_path)
    input_hashes["jeju/research/20261015_all_runner_place_value_v1/selected_rows.csv"] = sha256(selected_path)
    input_hashes["jeju/research/20261015_all_runner_place_value_v1/case_examples.csv"] = sha256(examples_path)
    input_hashes["jeju/research/20261015_all_runner_place_value_v1/summary.csv"] = sha256(summary_path)
    manifest = {
        "status": "PASS",
        "plan_sha256": EXPECTED_HASHES["jeju/research/20261015_all_runner_place_value_v1/PLAN.md"],
        "sha256": input_hashes,
    }
    (STUDY / "source_hashes.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS", "races": int(runners.race_id.nunique()),
        "runner_rows": len(runners), "summary_rows": len(summary),
        "case_example_rows": len(examples),
        "outputs": ["REPORT.json", "selected_rows.csv", "case_examples.csv", "summary.csv", "source_hashes.json"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

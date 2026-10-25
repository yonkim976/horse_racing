"""Compare frozen operating HY_R_FORM and saved research bets on shared 2026 races."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
LEGACY = ROOT / "data/research/jeju_native_transition_holdout_v13_20260916"
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"
OP_COMPARE = ROOT / "jeju/research/20261009_operating_model_comparison_v1/outputs"
PAIR_STUDY = ROOT / "jeju/research/20261015_all_pair_postrace_value_v1"
PAIR_PRED = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
PLC_STUDY = ROOT / "jeju/research/20261015_all_runner_place_value_v1"
PLC_PRED = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/report/runner_predictions.parquet"
PLC_SOURCE = ROOT / "jeju/research/20261014_single_place_returns_v1/source_audit"
PLC_ROOT_REVIEW = ROOT / "jeju/research/20261014_single_place_returns_v1"
BOOTSTRAP = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
REGISTRY = ROOT / "config/prediction_model_registry.json"
HY_MODEL = ROOT / "jeju/models/current/HY_R_FORM.pkl"
RESOLVER = ROOT / ".agents/skills/horse-racing-prediction-publisher/scripts/resolve_main_model.py"
HY_FUNCTION = ROOT / "src/horse_racing/analysis/jeju_hybrid_evaluation.py"

STAKE_KRW = 1_000
EXPECTED_REGISTRY_SHA = "944e4aad25c99d3d346dab23c7f7596c216d8722a548dea2c7c07abf9b10b70b"
EXPECTED_HY_SHA = "f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706"
EXPECTED_PAIR_SHA = "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6"
EXPECTED_F1_SHA = "706bca01e5f5e780a8ffbe9e2ad4553fea9e3d76df097b4c9648d7aabac44e56"
EXPECTED_QPL_REVIEW_SHA = "e6437455a06d2eb1f85cc80014c2c9c5ed4ce7a2d4422d4a29ade55d7877f182"
EXPECTED_PLC_AUDIT_SHA = "10967bdca3609aa1f535be1815b5281c6e8f53e367f5bdc32c030e59fd589880"
EXPECTED_PLC_REVIEW_SHA = "8d6c35c5e3aff56825a5ad0eed94bfac44622b98448ee35b44f492de3534738b"
EXPECTED_OFFICIAL_REVIEW_SHA = "eda599dc6243ff7db310b1855a434aac26e22456873e9b9befc2722d34364913"
EXPECTED_SCHEDULE_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_SCHEDULE_RECEIPT_SHA = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"

QPL_MODELS = ("operating_hy_r_form", "research_pair_id_baseline")
PLC_MODELS = ("operating_hy_r_form", "research_f1_style6")
QPL_POLICIES = [
    ("rank_1", "확률 rank 1"),
    ("rank_2", "확률 rank 2"),
    ("rank_3", "확률 rank 3"),
    ("rank_4", "확률 rank 4"),
    ("rank_5", "확률 rank 5"),
    ("rank_1_ev_gt_0", "rank 1, 사후 EV > 0"),
    ("all_max_ev_gt_0", "전체 후보 중 최대 EV > 0"),
    ("top3_max_ev_gt_0", "확률 rank 1–3 중 최대 EV > 0"),
    ("top5_max_ev_gt_0", "확률 rank 1–5 중 최대 EV > 0"),
    ("p_ge_020_max_ev_gt_0", "p ≥ 0.20 중 최대 EV > 0"),
    ("p_ge_030_max_ev_gt_0", "p ≥ 0.30 중 최대 EV > 0"),
    ("top3_max_ev_gt_020", "확률 rank 1–3 중 최대 EV > 0.20"),
    ("p_ge_020_max_ev_gt_020", "p ≥ 0.20 중 최대 EV > 0.20"),
]
PLC_POLICIES = [
    ("p_rank_1", "확률 rank 1"),
    ("p_rank_2", "확률 rank 2"),
    ("p_rank_3", "확률 rank 3"),
    ("p_rank_1_ev_positive", "rank 1, 사후 EV > 0"),
    ("all_runners_max_ev_positive", "전체 말 중 최대 EV > 0"),
    ("top3_max_ev_positive", "확률 rank 1–3 중 최대 EV > 0"),
    ("p_ge_0_40_max_ev_positive", "p ≥ 0.40 중 최대 EV > 0"),
    ("p_ge_0_50_max_ev_positive", "p ≥ 0.50 중 최대 EV > 0"),
]


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(frame: pd.DataFrame, name: str) -> None:
    path = (STUDY / name).resolve()
    require(path.parent == STUDY.resolve(), f"output escaped the new study directory: {name}")
    frame.to_csv(path, index=False, na_rep="")


def registry_resolution() -> dict[str, Any]:
    require(sha256_file(REGISTRY) == EXPECTED_REGISTRY_SHA, "active model registry hash changed")
    require(sha256_file(HY_MODEL) == EXPECTED_HY_SHA, "active HY_R_FORM artifact hash changed")
    result = subprocess.run(
        [sys.executable, "-B", str(RESOLVER), "--repo-root", str(ROOT), "--domain", "jeju"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    resolved = json.loads(result.stdout)
    require(resolved.get("ok") is True and resolved.get("champion_id") == "HY_R_FORM",
            "registry resolver did not resolve HY_R_FORM")
    require(resolved.get("active_profile") == "jeju-hy-r-form-20260919-v1",
            "registry active profile changed")
    artifacts = {item.get("name"): item for item in resolved.get("verified_artifacts", [])}
    require(artifacts.get("HY_R_FORM_model", {}).get("sha256") == EXPECTED_HY_SHA,
            "resolver did not verify the current HY_R_FORM artifact hash")
    return resolved


def parse_race_date(race_id: str) -> str:
    return str(race_id).rsplit("_", 2)[0]


def normal_pair(a: Any, b: Any) -> tuple[int, int]:
    x, y = int(a), int(b)
    require(x != y, "pair repeats a horse number")
    return (x, y) if x < y else (y, x)


def load_bootstrap(all_pair_dates: list[str]) -> tuple[np.ndarray, list[str], dict[str, int]]:
    require(sha256_file(BOOTSTRAP) == EXPECTED_SCHEDULE_SHA, "fixed 269-date bootstrap schedule hash changed")
    require(sha256_file(BOOTSTRAP_RECEIPT) == EXPECTED_SCHEDULE_RECEIPT_SHA,
            "fixed bootstrap receipt hash changed")
    receipt = json.loads(BOOTSTRAP_RECEIPT.read_text(encoding="utf-8"))
    dates = sorted(set(all_pair_dates))
    inventory_sha = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS"
            and receipt.get("draws") == 2000 and receipt.get("dates_per_draw") == 269
            and receipt.get("date_inventory_sha256") == inventory_sha,
            "fixed bootstrap schedule does not match the 269-date evaluation inventory")
    draws = np.load(BOOTSTRAP, allow_pickle=False)
    require(draws.shape == (2000, 269) and draws.dtype.kind in "iu"
            and draws.min() >= 0 and draws.max() < 269,
            "fixed bootstrap schedule shape or indices changed")
    return draws, dates, {day: ix for ix, day in enumerate(dates)}


def fixed_schedule_weights(draws: np.ndarray) -> np.ndarray:
    return np.stack([np.bincount(row, minlength=269) for row in draws]).astype(np.int64)


def source_hashes(paths: dict[str, Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for label, path in paths.items():
        require(path.is_file(), f"source file is missing: {label}")
        result[label] = sha256_file(path)
    return result


def read_source_reviews() -> dict[str, Any]:
    qpl_review_path = PAIR_STUDY / "ROOT_RAW_SOURCE_REVIEW.json"
    qpl_census_path = PAIR_STUDY / "SOURCE_CENSUS.json"
    plc_audit_path = PLC_SOURCE / "SOURCE_AUDIT_FINAL.json"
    plc_review_path = PLC_ROOT_REVIEW / "ROOT_PLC_SOURCE_REVIEW.json"
    official_review_path = PLC_ROOT_REVIEW / "ROOT_OFFICIAL_SOURCE_REVIEW.json"
    require(sha256_file(qpl_review_path) == EXPECTED_QPL_REVIEW_SHA, "QPL direct source review hash changed")
    require(sha256_file(plc_audit_path) == EXPECTED_PLC_AUDIT_SHA, "PLC source audit hash changed")
    require(sha256_file(plc_review_path) == EXPECTED_PLC_REVIEW_SHA, "PLC source review hash changed")
    require(sha256_file(official_review_path) == EXPECTED_OFFICIAL_REVIEW_SHA,
            "official runner review hash changed")
    qpl_review = json.loads(qpl_review_path.read_text(encoding="utf-8"))
    qpl_census = json.loads(qpl_census_path.read_text(encoding="utf-8"))
    plc_audit = json.loads(plc_audit_path.read_text(encoding="utf-8"))
    plc_review = json.loads(plc_review_path.read_text(encoding="utf-8"))
    official_review = json.loads(official_review_path.read_text(encoding="utf-8"))
    require(qpl_review.get("status") == "PASS" and qpl_review.get("database_access") is False
            and qpl_review.get("all_qpl_pair_quotes") == 48539
            and qpl_review.get("qpl_target_pairs_complete") is True,
            "QPL direct quote review is not complete and PASS")
    require(qpl_census.get("status") == "PASS", "QPL full source census is not PASS")
    require(plc_audit.get("status") == "PASS"
            and plc_audit.get("prohibited_metrics", {}).get("outcomes_or_metrics_computed") is False,
            "PLC price source audit is not a label-free PASS")
    require(plc_review.get("status") == "PASS" and plc_review.get("every_cohort_runner_quote_present") is True
            and plc_review.get("invalid_or_special_odds") == 0,
            "PLC direct quote review is incomplete or not PASS")
    require(official_review.get("status") == "PASS"
            and official_review.get("runner_keys_and_horse_ids_verified") == 17412,
            "official runner result review is incomplete or not PASS")
    return {
        "qpl_direct_review": qpl_review,
        "qpl_source_census_status": qpl_census.get("status"),
        "plc_source_audit": plc_audit,
        "plc_direct_review": plc_review,
        "official_result_review": official_review,
    }


def load_operating_and_cohort() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    align_path = OP_COMPARE / "race_alignment.csv"
    alignment = pd.read_csv(align_path, dtype={"race_id": "string"})
    require(len(alignment) == 531 and alignment.reason.eq("matched").sum() == 467,
            "prior operating/common research race alignment changed")
    require(alignment.reason.value_counts().to_dict().get("operating_only") == 43
            and alignment.reason.value_counts().to_dict().get("new_only") == 21,
            "operating-only or later research-only race counts changed")
    common_ids = set(alignment.loc[alignment.reason.eq("matched"), "race_id"].astype(str))

    # Read saved inputs without opening labels; outcomes are joined after every policy is fixed.
    hy_saved = pd.read_parquet(
        LEGACY / "horse_predictions.parquet",
        columns=["entry_id", "race_id", "horse_id", "event_date", "distance_m", "model", "score",
                 "beta", "order_score", "beta_order", "pl_place_probability"],
    )
    hy_saved = hy_saved.loc[hy_saved.model.eq("HY_R_FORM")].copy()
    frozen = pd.read_parquet(
        LEGACY / "frozen_scores.parquet",
        columns=["entry_id", "race_id", "horse_id", "event_date", "distance_m", "model", "score",
                 "beta", "order_score", "beta_order"],
    )
    frozen = frozen.loc[frozen.model.eq("HY_R_FORM")].copy()
    require(len(hy_saved) == len(frozen) == 4852 and hy_saved.race_id.nunique() == 510,
            "saved frozen HY evaluation coverage changed")
    frozen_check = hy_saved.merge(
        frozen, on=["entry_id", "race_id", "horse_id", "event_date", "distance_m", "model"],
        how="outer", validate="one_to_one", indicator=True, suffixes=("_prediction", "_frozen"),
    )
    require(frozen_check._merge.eq("both").all(), "HY saved predictions do not align with frozen raw scores")
    for column in ["score", "beta", "order_score", "beta_order"]:
        a = frozen_check[f"{column}_prediction"].to_numpy(float)
        b = frozen_check[f"{column}_frozen"].to_numpy(float)
        require(np.array_equal(a, b, equal_nan=True), f"saved HY {column} differs from frozen score source")

    races = pd.read_parquet(DATA / "races.parquet", columns=["race_id", "event_number"])
    entries = pd.read_parquet(DATA / "entries.parquet", columns=["entry_id", "horse_number"])
    require(not races.race_id.duplicated().any() and not entries.entry_id.duplicated().any(),
            "operating source race/entry identifiers are duplicated")
    hyd = hy_saved.merge(races, on="race_id", how="left", validate="many_to_one", indicator=True)
    require(hyd._merge.eq("both").all(), "saved HY scores are missing native race keys")
    hyd = hyd.drop(columns="_merge").merge(entries, on="entry_id", how="left", validate="one_to_one",
                                              indicator=True)
    require(hyd._merge.eq("both").all(), "saved HY scores are missing horse numbers")
    hyd = hyd.drop(columns="_merge")
    hyd["race_id_key"] = [f"{d}_2_{int(n)}" for d, n in zip(hyd.event_date, hyd.event_number)]
    hyd["race_date"] = hyd.event_date.astype(str)
    hyd["horse_id"] = hyd.horse_id.astype(str)
    hyd["horse_number"] = pd.to_numeric(hyd.horse_number, errors="raise").astype(int)
    require(not hyd.duplicated(["race_id_key", "horse_id"]).any(), "HY runner keys are duplicated")
    common_hy = hyd.loc[hyd.race_id_key.isin(common_ids)].copy()
    require(common_hy.race_id_key.nunique() == 467 and len(common_hy) == 4475,
            "matched operating HY roster coverage changed")
    raw_score_tied_races = int(hyd.groupby("race_id_key").score.apply(lambda values: values.duplicated().any()).sum())

    # Reproduce the native HY set probabilities from saved scores using the production evaluator.
    sys.path.insert(0, str(ROOT / "src"))
    from horse_racing.analysis.jeju_hybrid_evaluation import distribution

    pair_records: list[dict[str, Any]] = []
    runner_records: list[dict[str, Any]] = []
    race_distribution_check: list[dict[str, Any]] = []
    for race_id, race in common_hy.groupby("race_id_key", sort=True):
        race = race.sort_values("horse_number", kind="stable").reset_index(drop=True)
        n = len(race)
        require(n >= 3 and race.horse_number.nunique() == n, f"invalid HY race field: {race_id}")
        require(race.beta.nunique() == 1 and race.beta_order.nunique() == 1,
                f"HY race has inconsistent temperature values: {race_id}")
        scores = race.score.to_numpy(float)
        order_scores = race.order_score.to_numpy(float)
        beta_set = float(race.beta.iloc[0])
        beta_order = float(race.beta_order.iloc[0])
        require(np.isfinite(scores).all() and np.isfinite(order_scores).all(),
                f"HY score is not finite: {race_id}")
        sets, _, log_sets, _, marginals = distribution(scores, order_scores, beta_set, beta_order)
        set_p = np.exp(log_sets)
        require(np.isclose(set_p.sum(), 1.0, atol=1e-12, rtol=0), f"HY set probabilities do not sum to 1: {race_id}")
        require(np.allclose(marginals, race.pl_place_probability.to_numpy(float), atol=1e-12, rtol=0),
                f"HY native runner marginal differs from saved probability: {race_id}")
        require(np.isclose(marginals.sum(), 3.0, atol=1e-12, rtol=0),
                f"HY native runner marginals do not sum to 3: {race_id}")
        pair_matrix = np.zeros((n, n), dtype=float)
        for set_index, members in enumerate(sets):
            for local_i, local_j in combinations(members.tolist(), 2):
                pair_matrix[local_i, local_j] += float(set_p[set_index])
                pair_matrix[local_j, local_i] += float(set_p[set_index])
        expected_pairs = n * (n - 1) // 2
        pair_sum = float(np.triu(pair_matrix, 1).sum())
        require(np.isclose(pair_sum, 3.0, atol=1e-12, rtol=0),
                f"HY native pair marginal mass does not sum to 3: {race_id}")
        race_distribution_check.append({"race_id": race_id, "field_n": n, "set_probability_sum": float(set_p.sum()),
                                        "runner_probability_sum": float(marginals.sum()),
                                        "pair_probability_sum": pair_sum, "expected_pair_count": expected_pairs})
        for i, row in race.iterrows():
            runner_records.append({
                "race_id": race_id, "race_date": row.race_date, "year": int(row.race_date[:4]),
                "distance_m": int(row.distance_m), "field_n": n, "horse_id": row.horse_id,
                "horse_number": int(row.horse_number), "score": float(row.score),
                "p_top3": float(marginals[i]),
            })
        for i in range(n):
            for j in range(i + 1, n):
                pair_records.append({
                    "race_id": race_id, "race_date": race.race_date.iloc[0], "year": int(race.race_date.iloc[0][:4]),
                    "distance_m": int(race.distance_m.iloc[0]), "field_n": n,
                    "horse_i": int(race.horse_number.iloc[i]), "horse_j": int(race.horse_number.iloc[j]),
                    "horse_id_i": race.horse_id.iloc[i], "horse_id_j": race.horse_id.iloc[j],
                    "p": float(pair_matrix[i, j]),
                })
    op_pairs = pd.DataFrame(pair_records)
    op_runners = pd.DataFrame(runner_records)
    require(op_pairs.race_id.nunique() == 467 and op_runners.race_id.nunique() == 467,
            "native HY pair or runner reconstruction lost common races")

    saved_common = pd.read_parquet(
        OP_COMPARE / "runner_predictions.parquet",
        columns=["race_id", "race_date", "horse_id", "horse_number", "variant", "p_top3"],
    )
    saved_common = saved_common.loc[saved_common.variant.eq("HY_R_FORM")].copy()
    saved_common["race_id"] = saved_common.race_id.astype(str)
    saved_common["horse_id"] = saved_common.horse_id.astype(str)
    saved_common["horse_number"] = pd.to_numeric(saved_common.horse_number, errors="raise").astype(int)
    native_join = op_runners.merge(saved_common, on=["race_id", "horse_id", "horse_number"], how="outer",
                                   validate="one_to_one", indicator=True, suffixes=("_native", "_saved"))
    require(native_join._merge.eq("both").all() and len(native_join) == 4475,
            "native HY runner roster differs from independently saved common comparison output")
    require(np.allclose(native_join.p_top3_native, native_join.p_top3_saved, atol=1e-12, rtol=0),
            "native HY runner marginal reproduction differs from saved comparison output")
    require(np.array_equal(native_join.race_date_native.astype(str), native_join.race_date_saved.astype(str)),
            "HY saved runner race date changed")

    cohort = alignment.copy()
    cohort["race_date"] = cohort.race_id.map(parse_race_date)
    cohort["qpl_eligible"] = cohort.reason.eq("matched")
    field_sizes = common_hy.groupby("race_id_key").size().rename("field_n")
    cohort = cohort.merge(field_sizes, left_on="race_id", right_index=True, how="left", validate="one_to_one")
    cohort["plc_eligible"] = cohort.qpl_eligible & cohort.field_n.ge(8)
    cohort["exclusion_detail"] = np.select(
        [cohort.reason.eq("operating_only"), cohort.reason.eq("new_only"),
         cohort.reason.eq("matched") & cohort.field_n.le(7)],
        ["outside_normal_complete_common_race_cohort_operating_only",
         "research_evaluation_after_operating_saved_coverage",
         "less_than_8_runners_outside_fixed_F1_STYLE6_PLC_support"], default="included",
    )
    require(cohort.qpl_eligible.sum() == 467 and cohort.plc_eligible.sum() == 436,
            "common QPL/PLC eligibility counts changed")
    return op_pairs, op_runners, cohort, {
        "common_race_ids": sorted(common_ids),
        "native_distribution_by_race": race_distribution_check,
        "hy_rows_common": int(len(op_runners)),
        "hy_unique_common_runners": int(len(op_runners)),
        "hy_common_dates": sorted(op_runners.race_date.unique().tolist()),
        "hy_exact_raw_score_tied_races": raw_score_tied_races,
        "alignment_reason_counts": alignment.reason.value_counts().to_dict(),
        "alignment_rows": int(len(alignment)),
    }


def load_qpl_prediction_and_quotes(common_ids: set[str], op_pairs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    prediction = pd.read_parquet(
        PAIR_PRED,
        columns=["race_id", "race_date", "evaluation_year", "horse_i", "horse_j",
                 "jockey_id_candidate_calibrated_probability"],
    )
    prediction = prediction.loc[prediction.evaluation_year.eq(2026)
                                & prediction.race_id.astype(str).isin(common_ids)].copy()
    prediction["race_id"] = prediction.race_id.astype(str)
    prediction["race_date"] = pd.to_datetime(prediction.race_date, errors="raise").dt.strftime("%Y-%m-%d")
    keys = [normal_pair(a, b) for a, b in zip(prediction.horse_i, prediction.horse_j)]
    prediction["horse_i"] = [x for x, _ in keys]
    prediction["horse_j"] = [y for _, y in keys]
    prediction["p"] = pd.to_numeric(prediction.jockey_id_candidate_calibrated_probability, errors="raise")
    research_pairs = prediction[["race_id", "race_date", "horse_i", "horse_j", "p"]].copy()
    require(not research_pairs.duplicated(["race_id", "horse_i", "horse_j"]).any(),
            "saved research pair keys are duplicated")
    require(np.isfinite(research_pairs.p.to_numpy(float)).all() and research_pairs.p.between(0, 1).all(),
            "saved research pair probabilities are invalid")

    quotes = pd.read_csv(
        PAIR_STUDY / "ROOT_QPL_QUOTE_REFERENCE.csv",
        usecols=["race_id", "horse_i", "horse_j", "raw_quote", "source_sha256"],
        dtype={"race_id": "string", "source_sha256": "string"},
    )
    quotes = quotes.loc[quotes.race_id.astype(str).isin(common_ids)].copy()
    keys = [normal_pair(a, b) for a, b in zip(quotes.horse_i, quotes.horse_j)]
    quotes["horse_i"] = [x for x, _ in keys]
    quotes["horse_j"] = [y for _, y in keys]
    quotes["race_id"] = quotes.race_id.astype(str)
    quotes["race_date"] = quotes.race_id.map(parse_race_date)
    quotes["quote"] = pd.to_numeric(quotes.raw_quote, errors="raise")
    require(not quotes.duplicated(["race_id", "horse_i", "horse_j"]).any(),
            "direct QPL quote keys are duplicated")
    require(np.isfinite(quotes.quote.to_numpy(float)).all() and quotes.quote.gt(0).all()
            and not quotes.quote.eq(9999.9).any(), "QPL source contains invalid final prices")

    op = op_pairs.rename(columns={"p": "p"}).copy()
    op = op.merge(quotes[["race_id", "race_date", "horse_i", "horse_j", "quote", "source_sha256"]],
                  on=["race_id", "horse_i", "horse_j"], how="outer", validate="one_to_one", indicator=True,
                  suffixes=("_op", "_quote"))
    require(op._merge.eq("both").all(), "QPL quotes do not cover the full HY native pair roster")
    require(op.race_id.nunique() == 467 and len(op) == int(op_pairs.groupby("race_id").size().sum()),
            "QPL HY quote cohort changed")
    require(np.array_equal(op.race_date_op.astype(str), op.race_date_quote.astype(str)),
            "QPL quote and HY prediction dates disagree")
    op = op.drop(columns="_merge").rename(columns={"race_date_op": "race_date"})

    research = research_pairs.merge(
        quotes[["race_id", "race_date", "horse_i", "horse_j", "quote", "source_sha256"]],
        on=["race_id", "horse_i", "horse_j"], how="outer", validate="one_to_one", indicator=True,
    )
    require(research._merge.eq("both").all() and research.race_id.nunique() == 467,
            "QPL quotes do not cover the full research pair roster")
    require(np.array_equal(research.race_date_x.astype(str), research.race_date_y.astype(str)),
            "QPL quote and research prediction dates disagree")
    research = research.drop(columns=["_merge", "race_date_y"]).rename(columns={"race_date_x": "race_date"})
    race_meta = op_pairs[["race_id", "field_n", "distance_m"]].drop_duplicates("race_id")
    research = research.merge(race_meta, on="race_id", how="left", validate="many_to_one")
    require(research.field_n.notna().all() and research.distance_m.notna().all(),
            "research QPL probabilities are missing matched race metadata")

    all_ids = set(op_pairs.race_id.astype(str))
    expected_pair_counts = (op_pairs.groupby("race_id").size()).to_dict()
    for frame, label in [(op, "HY"), (research, "research"), (quotes, "quote")]:
        got = frame.groupby("race_id").size().to_dict()
        require(set(got) == all_ids and got == expected_pair_counts,
                f"{label} QPL pair roster is incomplete or differs from complete field combinations")
    op["model"] = QPL_MODELS[0]
    research["model"] = QPL_MODELS[1]
    return op, research, {
        "qpl_races": 467,
        "qpl_dates": int(op.race_date.nunique()),
        "qpl_pair_rows_per_model": int(len(op)),
        "qpl_complete_field_pair_roster": True,
        "qpl_full_price_rows": int(len(quotes)),
        "qpl_valid_quote_rows": int(quotes.quote.notna().sum()),
        "qpl_missing_or_invalid_quotes": 0,
    }


def load_plc_predictions_and_quotes(common_ids: set[str], op_runners: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    f1 = pd.read_parquet(
        PLC_PRED,
        columns=["race_id", "race_date", "year", "horse_id", "horse_number", "field_n", "variant", "score", "p_top3"],
    )
    f1 = f1.loc[f1.variant.eq("F1_STYLE6") & f1.race_id.astype(str).isin(common_ids)].copy()
    f1["race_id"] = f1.race_id.astype(str)
    f1["race_date"] = pd.to_datetime(f1.race_date, errors="raise").dt.strftime("%Y-%m-%d")
    f1["horse_id"] = f1.horse_id.astype(str)
    f1["horse_number"] = pd.to_numeric(f1.horse_number, errors="raise").astype(int)
    f1["field_n"] = pd.to_numeric(f1.field_n, errors="raise").astype(int)
    f1["score"] = pd.to_numeric(f1.score, errors="raise")
    f1["p_top3"] = pd.to_numeric(f1.p_top3, errors="raise")
    f1 = f1.rename(columns={"field_n": "field_n_f1", "score": "score_f1", "p_top3": "p_f1"})
    require(f1.race_id.nunique() == 467 and len(f1) == 4475,
            "saved F1_STYLE6 common runner roster changed")

    op = op_runners.copy().rename(columns={"field_n": "field_n_hy", "score": "score_hy", "p_top3": "p_hy"})
    shared = op.merge(
        f1[["race_id", "race_date", "horse_id", "horse_number", "field_n_f1", "score_f1", "p_f1"]],
        on=["race_id", "race_date", "horse_id", "horse_number"], how="outer", validate="one_to_one",
        indicator=True,
    )
    require(shared._merge.eq("both").all() and len(shared) == 4475,
            "HY and F1_STYLE6 runner IDs/numbers differ in common QPL cohort")
    require(shared.field_n_hy.eq(shared.field_n_f1).all(), "HY and F1 field sizes differ")
    require(np.isfinite(shared.p_hy.to_numpy(float)).all() and shared.p_hy.between(0, 1).all()
            and np.isfinite(shared.p_f1.to_numpy(float)).all() and shared.p_f1.between(0, 1).all(),
            "runner Top3 probabilities are invalid")
    require(np.allclose(shared.groupby("race_id").p_hy.sum().to_numpy(float), 3.0, atol=1e-12, rtol=0)
            and np.allclose(shared.groupby("race_id").p_f1.sum().to_numpy(float), 3.0, atol=1e-8, rtol=0),
            "native runner Top3 probability sum changed")
    shared = shared.drop(columns="_merge")

    # Restrict both models to the same fixed F1_STYLE6 8+ runner support.
    supported_ids = set(shared.loc[shared.field_n_hy.ge(8), "race_id"].astype(str))
    require(len(supported_ids) == 436 and shared.loc[shared.field_n_hy.le(7), "race_id"].nunique() == 31,
            "common PLC support cohort changed")
    unsupported_runner_rows = int(shared.loc[shared.field_n_hy.le(7), "race_id"].size)
    shared = shared.loc[shared.race_id.isin(supported_ids)].copy()

    prices = pd.read_csv(
        PLC_SOURCE / "PLC_PRICE_ROWS.csv",
        usecols=["race_id", "race_date_local", "horse_number", "kra_horse_id", "odds", "source_sha256",
                 "odds_unit", "pool_code", "official_field_size"],
        dtype={"race_id": "string", "kra_horse_id": "string", "source_sha256": "string", "pool_code": "string"},
    )
    prices = prices.loc[prices.pool_code.eq("PLC") & prices.race_id.astype(str).isin(supported_ids)].copy()
    prices["race_id"] = prices.race_id.astype(str)
    prices["race_date"] = pd.to_datetime(prices.race_date_local, errors="raise").dt.strftime("%Y-%m-%d")
    prices["horse_id"] = prices.kra_horse_id.astype(str)
    prices["horse_number"] = pd.to_numeric(prices.horse_number, errors="raise").astype(int)
    prices["field_n_price"] = pd.to_numeric(prices.official_field_size, errors="raise").astype(int)
    prices["quote"] = pd.to_numeric(prices.odds, errors="raise")
    prices = prices[["race_id", "race_date", "horse_id", "horse_number", "field_n_price", "quote",
                     "source_sha256", "odds_unit"]]
    require(not prices.duplicated(["race_id", "horse_id", "horse_number"]).any(),
            "PLC quote keys are duplicated")
    require(np.isfinite(prices.quote.to_numpy(float)).all() and prices.quote.gt(0).all()
            and not prices.quote.eq(9999.9).any(), "PLC source contains invalid final prices")
    require(prices.odds_unit.eq("decimal_gross_return_multiple_per_stake_unit").all(),
            "PLC source odds unit changed")

    root_quotes = pd.read_csv(
        PLC_STUDY / "ROOT_PLC_QUOTE_REFERENCE.csv",
        usecols=["race_id", "horse_number", "raw_quote", "source_sha256"],
        dtype={"race_id": "string", "source_sha256": "string"},
    )
    root_quotes = root_quotes.loc[root_quotes.race_id.astype(str).isin(supported_ids)].copy()
    root_quotes["race_id"] = root_quotes.race_id.astype(str)
    root_quotes["horse_number"] = pd.to_numeric(root_quotes.horse_number, errors="raise").astype(int)
    root_quotes["raw_quote"] = pd.to_numeric(root_quotes.raw_quote, errors="raise")
    ref_check = prices.merge(root_quotes, on=["race_id", "horse_number"], how="outer", validate="one_to_one",
                             indicator=True, suffixes=("_audit", "_root"))
    require(ref_check._merge.eq("both").all() and ref_check.quote.eq(ref_check.raw_quote).all()
            and ref_check.source_sha256_audit.eq(ref_check.source_sha256_root).all(),
            "PLC audit quotes differ from direct JSON reference")

    joined = shared.merge(prices, on=["race_id", "race_date", "horse_id", "horse_number"], how="outer",
                          validate="one_to_one", indicator=True)
    require(joined._merge.eq("both").all() and len(joined) == len(shared),
            "PLC price source does not cover the complete common supported runner roster")
    require(joined.field_n_hy.eq(joined.field_n_price).all(), "PLC quote field size differs from model roster")
    require(joined.groupby("race_id").size().eq(joined.groupby("race_id").field_n_hy.first()).all(),
            "PLC common prices do not cover every starter")
    require(np.allclose(joined.groupby("race_id").p_hy.sum().to_numpy(float), 3.0, atol=1e-12, rtol=0)
            and np.allclose(joined.groupby("race_id").p_f1.sum().to_numpy(float), 3.0, atol=1e-8, rtol=0),
            "PLC runner marginal sum changed")

    operating = joined[["race_id", "race_date", "field_n_hy", "horse_id", "horse_number", "score_hy", "p_hy",
                        "quote", "source_sha256"]].copy().rename(
                            columns={"field_n_hy": "field_n", "score_hy": "score", "p_hy": "p"})
    research = joined[["race_id", "race_date", "field_n_f1", "horse_id", "horse_number", "score_f1", "p_f1",
                       "quote", "source_sha256"]].copy().rename(
                           columns={"field_n_f1": "field_n", "score_f1": "score", "p_f1": "p"})
    operating["model"] = PLC_MODELS[0]
    research["model"] = PLC_MODELS[1]
    return operating, research, {
        "plc_races": int(len(supported_ids)), "plc_dates": int(joined.race_date.nunique()),
        "plc_runner_rows_per_model": int(len(joined)), "plc_full_price_rows": int(len(prices)),
        "plc_valid_quote_rows": int(prices.quote.notna().sum()), "plc_quote_reference_matches": int(len(ref_check)),
        "plc_unsupported_7_or_fewer_races": 31, "plc_unsupported_7_or_fewer_runners": unsupported_runner_rows,
        "plc_supported_cohort_full_roster": True,
    }


def prepare_qpl_ranked(frame: pd.DataFrame) -> pd.DataFrame:
    result: list[pd.DataFrame] = []
    for race_id, race in frame.groupby("race_id", sort=True):
        race = race.sort_values(["p", "horse_i", "horse_j"], ascending=[False, True, True], kind="stable").copy()
        race["probability_rank"] = np.arange(1, len(race) + 1, dtype=int)
        race["model_ev"] = race.p * race.quote - 1.0
        race["hit"] = False
        race["selected"] = False
        race["stake_krw"] = 0.0
        race["gross_return_krw"] = 0.0
        race["net_profit_krw"] = 0.0
        result.append(race)
    return pd.concat(result, ignore_index=True)


def best_qpl_ev(candidates: pd.DataFrame, threshold: float) -> tuple[pd.Series | None, int]:
    eligible = candidates.loc[candidates.model_ev.gt(threshold)].copy()
    if eligible.empty:
        return None, 0
    # Existing QPL study uses ascending unordered horse_i, horse_j for score ties only.
    eligible = eligible.sort_values(["model_ev", "horse_i", "horse_j"], ascending=[False, True, True], kind="stable")
    return eligible.iloc[0], len(eligible)


def choose_qpl(model_frame: pd.DataFrame) -> pd.DataFrame:
    chosen_rows: list[dict[str, Any]] = []
    for race_id, race in model_frame.groupby("race_id", sort=True):
        race = race.sort_values("probability_rank", kind="stable")
        candidates: list[tuple[str, pd.Series | None, int, str]] = []
        for rank in range(1, 6):
            row = race.loc[race.probability_rank.eq(rank)]
            candidates.append((f"rank_{rank}", row.iloc[0] if not row.empty else None,
                               int(not row.empty), f"fixed_probability_rank_{rank}"))
        rank1 = race.loc[race.probability_rank.eq(1)].iloc[0]
        rank1_pick = rank1 if rank1.model_ev > 0 else None
        candidates.append(("rank_1_ev_gt_0", rank1_pick, int(rank1_pick is not None),
                           "rank1_ev_positive" if rank1_pick is not None else "rank1_ev_not_positive"))
        for policy, subset, threshold in [
            ("all_max_ev_gt_0", race, 0.0),
            ("top3_max_ev_gt_0", race.loc[race.probability_rank.le(3)], 0.0),
            ("top5_max_ev_gt_0", race.loc[race.probability_rank.le(5)], 0.0),
            ("p_ge_020_max_ev_gt_0", race.loc[race.p.ge(0.20)], 0.0),
            ("p_ge_030_max_ev_gt_0", race.loc[race.p.ge(0.30)], 0.0),
            ("top3_max_ev_gt_020", race.loc[race.probability_rank.le(3)], 0.20),
            ("p_ge_020_max_ev_gt_020", race.loc[race.p.ge(0.20)], 0.20),
        ]:
            pick, count = best_qpl_ev(subset, threshold)
            candidates.append((policy, pick, count, "max_posthoc_ev" if pick is not None else "no_candidate_above_fixed_threshold"))
        for policy_id, pick, candidate_count, reason in candidates:
            row = {
                "race_id": str(race_id), "race_date": str(race.race_date.iloc[0]),
                "year": int(str(race.race_date.iloc[0])[:4]),
                "field_n": int(race.field_n.iloc[0]), "model": str(race.model.iloc[0]),
                "policy_id": policy_id, "eligible_candidate_count": int(candidate_count),
                "selected": pick is not None, "selection_reason": reason,
            }
            if pick is None:
                row.update({"horse_i": None, "horse_j": None, "pair": None, "probability_rank": None,
                            "p": None, "quote": None, "model_ev": None})
            else:
                row.update({"horse_i": int(pick.horse_i), "horse_j": int(pick.horse_j),
                            "pair": f"{int(pick.horse_i)}-{int(pick.horse_j)}",
                            "probability_rank": int(pick.probability_rank), "p": float(pick.p),
                            "quote": float(pick.quote), "model_ev": float(pick.model_ev)})
            chosen_rows.append(row)
    result = pd.DataFrame(chosen_rows)
    expected = model_frame.race_id.nunique() * len(QPL_POLICIES)
    require(len(result) == expected and not result.duplicated(["race_id", "model", "policy_id"]).any(),
            "QPL policy choice grid is incomplete")
    return result


def prepare_plc_ranked(frame: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for _, race in frame.groupby("race_id", sort=True):
        race = race.sort_values(["score", "horse_number"], ascending=[False, True], kind="stable").copy()
        race["probability_rank"] = np.arange(1, len(race) + 1, dtype=int)
        race["model_ev"] = race.p * race.quote - 1.0
        parts.append(race)
    return pd.concat(parts, ignore_index=True)


def best_plc_ev(candidates: pd.DataFrame) -> tuple[pd.Series | None, int]:
    positive = candidates.loc[candidates.model_ev.gt(0)].copy()
    if positive.empty:
        return None, 0
    positive = positive.sort_values(["model_ev", "probability_rank", "horse_number"],
                                    ascending=[False, True, True], kind="stable")
    return positive.iloc[0], len(positive)


def choose_plc(model_frame: pd.DataFrame) -> pd.DataFrame:
    chosen_rows: list[dict[str, Any]] = []
    for race_id, race in model_frame.groupby("race_id", sort=True):
        race = race.sort_values("probability_rank", kind="stable")
        rank1 = race.loc[race.probability_rank.eq(1)].iloc[0]
        candidates: list[tuple[str, pd.Series | None, int, str]] = []
        for rank in (1, 2, 3):
            pick = race.loc[race.probability_rank.eq(rank)].iloc[0]
            candidates.append((f"p_rank_{rank}", pick, 1, f"fixed_probability_rank_{rank}"))
        pick = rank1 if rank1.model_ev > 0 else None
        candidates.append(("p_rank_1_ev_positive", pick, int(pick is not None),
                           "rank1_ev_positive" if pick is not None else "rank1_ev_not_positive"))
        for policy, subset in [
            ("all_runners_max_ev_positive", race),
            ("top3_max_ev_positive", race.loc[race.probability_rank.le(3)]),
            ("p_ge_0_40_max_ev_positive", race.loc[race.p.ge(0.40)]),
            ("p_ge_0_50_max_ev_positive", race.loc[race.p.ge(0.50)]),
        ]:
            best, count = best_plc_ev(subset)
            candidates.append((policy, best, count, "max_positive_ev" if best is not None else "no_positive_ev_candidate"))
        for policy_id, pick, candidate_count, reason in candidates:
            row = {
                "race_id": str(race_id), "race_date": str(race.race_date.iloc[0]), "year": int(race.race_date.iloc[0][:4]),
                "field_n": int(race.field_n.iloc[0]), "model": str(race.model.iloc[0]),
                "policy_id": policy_id, "eligible_candidate_count": int(candidate_count),
                "selected": pick is not None, "selection_reason": reason,
            }
            if pick is None:
                row.update({"horse_id": None, "horse_number": None, "probability_rank": None,
                            "score": None, "p": None, "quote": None, "model_ev": None})
            else:
                row.update({"horse_id": str(pick.horse_id), "horse_number": int(pick.horse_number),
                            "probability_rank": int(pick.probability_rank), "score": float(pick.score),
                            "p": float(pick.p), "quote": float(pick.quote), "model_ev": float(pick.model_ev)})
            chosen_rows.append(row)
    result = pd.DataFrame(chosen_rows)
    expected = model_frame.race_id.nunique() * len(PLC_POLICIES)
    require(len(result) == expected and not result.duplicated(["race_id", "model", "policy_id"]).any(),
            "PLC policy choice grid is incomplete")
    return result


def official_outcomes(common_ids: set[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    official = pd.read_csv(
        PLC_SOURCE / "OFFICIAL_RUNNER_RESULTS.csv",
        usecols=["race_id", "race_date_local", "field_size", "status", "horse_number", "scratched",
                 "finish_position", "disqualified", "kra_horse_id"],
        dtype={"race_id": "string", "kra_horse_id": "string", "status": "string"},
    )
    official = official.loc[official.race_id.astype(str).isin(common_ids)].copy()
    official["race_id"] = official.race_id.astype(str)
    official["race_date"] = pd.to_datetime(official.race_date_local, errors="raise").dt.strftime("%Y-%m-%d")
    official["horse_id"] = official.kra_horse_id.astype(str)
    official["horse_number"] = pd.to_numeric(official.horse_number, errors="raise").astype(int)
    official["field_n"] = pd.to_numeric(official.field_size, errors="raise").astype(int)
    official["finish_position"] = pd.to_numeric(official.finish_position, errors="raise")
    require(not official.duplicated(["race_id", "horse_id", "horse_number"]).any(),
            "official outcome runner keys are duplicated")
    require(official.status.eq("completed").all()
            and pd.to_numeric(official.scratched, errors="raise").eq(0).all()
            and pd.to_numeric(official.disqualified, errors="raise").eq(0).all()
            and official.finish_position.notna().all() and official.finish_position.gt(0).all(),
            "official outcome source contains incomplete/nonstarter rows")
    official["hit"] = official.finish_position.le(3)
    counts = official.groupby("race_id").hit.sum()
    require(len(counts) == 467 and counts.eq(3).all(),
            "common complete-race cohort does not have exactly three Top3 labels per race")
    return official[["race_id", "race_date", "horse_id", "horse_number", "field_n", "finish_position", "hit"]], {
        "official_rows_for_common_races": int(len(official)),
        "official_races": int(official.race_id.nunique()),
        "races_with_exactly_3_top3_runners": int(counts.eq(3).sum()),
        "common_race_dead_heats": int(official.duplicated(["race_id", "finish_position"]).sum()),
    }


def attach_outcomes(qpl_selections: pd.DataFrame, plc_selections: pd.DataFrame,
                    op_runners: pd.DataFrame, plc_runners: pd.DataFrame,
                    official: pd.DataFrame, common_ids: set[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    # First assert model rosters and labels against the official runner source.
    op_roster = op_runners.merge(
        official[["race_id", "race_date", "horse_id", "horse_number", "field_n", "hit"]],
        on=["race_id", "race_date", "horse_id", "horse_number"], how="outer", validate="one_to_one",
        indicator=True, suffixes=("_model", "_official"),
    )
    require(op_roster._merge.eq("both").all() and op_roster.field_n_model.eq(op_roster.field_n_official).all(),
            "HY saved runner roster differs from official result IDs/field sizes")
    op_roster = op_roster.drop(columns="_merge")
    saved_labels = pd.read_parquet(
        LEGACY / "horse_predictions.parquet",
        columns=["entry_id", "race_id", "horse_id", "event_date", "model", "official_top3"],
    )
    saved_labels = saved_labels.loc[saved_labels.model.eq("HY_R_FORM")].copy()
    races = pd.read_parquet(DATA / "races.parquet", columns=["race_id", "event_number"])
    labels = saved_labels.merge(races, on="race_id", how="left", validate="many_to_one")
    labels["race_id"] = [f"{d}_2_{int(n)}" for d, n in zip(labels.event_date, labels.event_number)]
    labels = labels.loc[labels.race_id.isin(common_ids)].copy()
    labels["horse_id"] = labels.horse_id.astype(str)
    label_check = op_roster.merge(labels[["race_id", "horse_id", "official_top3"]],
                                  on=["race_id", "horse_id"], how="outer", validate="one_to_one", indicator=True)
    require(label_check._merge.eq("both").all()
            and np.array_equal(label_check.official_top3.to_numpy(int), label_check.hit.to_numpy(int)),
            "saved HY Top3 labels disagree with official result source")

    pair_labels = pd.read_parquet(PAIR_PRED, columns=["race_id", "evaluation_year", "horse_i", "horse_j", "y_pair"])
    pair_labels = pair_labels.loc[pair_labels.evaluation_year.eq(2026)
                                  & pair_labels.race_id.astype(str).isin(common_ids)].copy()
    pair_keys = [normal_pair(a, b) for a, b in zip(pair_labels.horse_i, pair_labels.horse_j)]
    pair_labels["race_id"] = pair_labels.race_id.astype(str)
    pair_labels["horse_i"] = [x for x, _ in pair_keys]
    pair_labels["horse_j"] = [y for _, y in pair_keys]
    pair_labels["y_pair"] = pd.to_numeric(pair_labels.y_pair, errors="raise").astype(int)
    official_by_num = official.assign(horse_number=official.horse_number.astype(int)).set_index(["race_id", "horse_number"]).hit
    expected_hit = [int(bool(official_by_num.loc[(r, i)]) and bool(official_by_num.loc[(r, j)]))
                    for r, i, j in zip(pair_labels.race_id, pair_labels.horse_i, pair_labels.horse_j)]
    require(np.array_equal(pair_labels.y_pair.to_numpy(int), np.asarray(expected_hit, dtype=int)),
            "saved research pair labels disagree with official Top3 pair events")

    qpl = qpl_selections.copy()
    qpl = qpl.merge(
        official[["race_id", "race_date", "horse_number", "hit"]].rename(
            columns={"horse_number": "horse_i", "hit": "hit_i"}),
        on=["race_id", "race_date", "horse_i"], how="left", validate="many_to_one", indicator="_merge_i",
    )
    qpl = qpl.merge(
        official[["race_id", "horse_number", "hit"]].rename(
            columns={"horse_number": "horse_j", "hit": "hit_j"}),
        on=["race_id", "horse_j"], how="left", validate="many_to_one", indicator="_merge_j",
    )
    selected = qpl.selected.fillna(False)
    require(qpl.loc[selected, "_merge_i"].eq("both").all() and qpl.loc[selected, "_merge_j"].eq("both").all(),
            "selected QPL pair is missing an official outcome")
    qpl["hit"] = selected & qpl.hit_i.fillna(False) & qpl.hit_j.fillna(False)
    qpl["stake_krw"] = selected.astype(float) * STAKE_KRW
    qpl["gross_return_krw"] = np.where(qpl.hit, qpl.quote.fillna(0).astype(float) * STAKE_KRW, 0.0)
    qpl["net_profit_krw"] = qpl.gross_return_krw - qpl.stake_krw
    qpl = qpl.drop(columns=["_merge_i", "_merge_j", "hit_i", "hit_j"])

    plc = plc_selections.merge(
        official[["race_id", "race_date", "horse_id", "horse_number", "field_n", "finish_position", "hit"]].rename(
            columns={"hit": "hit_official"}),
        on=["race_id", "race_date", "horse_id", "horse_number"], how="left", validate="many_to_one",
        indicator=True, suffixes=("_model", "_official"),
    )
    selected = plc.selected.fillna(False)
    require(plc.loc[selected, "_merge"].eq("both").all()
            and plc.loc[~selected, "_merge"].eq("left_only").all(),
            "PLC selection does not map one-to-one to official outcome")
    require(plc.loc[selected, "field_n_model"].eq(plc.loc[selected, "field_n_official"]).all(),
            "selected PLC model field size differs from official field size")
    plc_selected_rows_joined = int(plc.loc[selected, "_merge"].eq("both").sum())
    plc["hit"] = selected & plc.hit_official.fillna(False)
    plc["stake_krw"] = selected.astype(float) * STAKE_KRW
    plc["gross_return_krw"] = np.where(plc.hit, plc.quote.fillna(0).astype(float) * STAKE_KRW, 0.0)
    plc["net_profit_krw"] = plc.gross_return_krw - plc.stake_krw
    plc = plc.drop(columns=["_merge", "field_n_official", "finish_position", "hit_official"])

    qpl_source_outcome_rows = pd.read_csv(
        PAIR_STUDY / "pair_rows.csv",
        usecols=["race_id", "pair", "model", "official_hit"],
        dtype={"race_id": "string", "pair": "string", "model": "string"},
    )
    qpl_source_outcome_rows = qpl_source_outcome_rows.loc[
        qpl_source_outcome_rows.race_id.astype(str).isin(common_ids)
        & qpl_source_outcome_rows.model.eq("pair_id_baseline")].copy()
    expected_pairs = pair_labels.copy()
    expected_pairs["pair"] = [f"{i}-{j}" for i, j in zip(expected_pairs.horse_i, expected_pairs.horse_j)]
    source_label_check = qpl_source_outcome_rows.merge(expected_pairs[["race_id", "pair", "y_pair"]],
                                                        on=["race_id", "pair"], how="outer", validate="one_to_one",
                                                        indicator=True)
    require(source_label_check._merge.eq("both").all()
            and np.array_equal(pd.to_numeric(source_label_check.official_hit).to_numpy(int),
                               source_label_check.y_pair.to_numpy(int)),
            "prior QPL source labels differ from independent official Top3 pair events")
    return qpl, plc, {
        "official_roster_rows_checked": int(len(op_roster)),
        "saved_hy_labels_match_official": True,
        "research_pair_label_rows_checked": int(len(pair_labels)),
        "research_pair_labels_match_official": True,
        "prior_qpl_row_labels_match_official": int(len(source_label_check)),
        "plc_selected_rows_joined": plc_selected_rows_joined,
    }


def bootstrap_metrics(group: pd.DataFrame, date_weights: np.ndarray, date_index: dict[str, int]) -> dict[str, Any]:
    date_ix = group.race_date.astype(str).map(date_index)
    require(date_ix.notna().all(), "strategy date is absent from fixed 269-date schedule")
    row_weights = date_weights[:, date_ix.to_numpy(dtype=int)]
    chosen = group.selected.to_numpy(dtype=float)
    hits = group.hit.fillna(False).to_numpy(dtype=float) * chosen
    gross = group.gross_return_krw.to_numpy(dtype=float)
    stakes = group.stake_krw.to_numpy(dtype=float)
    n_draw = row_weights @ chosen
    hit_draw = row_weights @ hits
    gross_draw = row_weights @ gross
    stake_draw = row_weights @ stakes
    hit_rate = np.divide(hit_draw, n_draw, out=np.full_like(hit_draw, np.nan), where=n_draw > 0)
    roi = np.divide(gross_draw, stake_draw, out=np.full_like(gross_draw, np.nan), where=stake_draw > 0) - 1.0
    hit_valid, roi_valid = np.isfinite(hit_rate), np.isfinite(roi)
    return {
        "hit_rate_ci95_low_pct": float(np.nanpercentile(hit_rate, 2.5) * 100) if hit_valid.any() else None,
        "hit_rate_ci95_high_pct": float(np.nanpercentile(hit_rate, 97.5) * 100) if hit_valid.any() else None,
        "hit_rate_valid_draws": int(hit_valid.sum()), "hit_rate_zero_bet_draws": int((~hit_valid).sum()),
        "roi_ci95_low_pct": float(np.nanpercentile(roi, 2.5) * 100) if roi_valid.any() else None,
        "roi_ci95_high_pct": float(np.nanpercentile(roi, 97.5) * 100) if roi_valid.any() else None,
        "roi_valid_draws": int(roi_valid.sum()), "roi_zero_stake_draws": int((~roi_valid).sum()),
    }


def paired_difference(a: pd.DataFrame, b: pd.DataFrame, date_weights: np.ndarray,
                      date_index: dict[str, int], model_a: str, model_b: str) -> dict[str, Any]:
    key = ["race_id"]
    joined = a.merge(b, on=key, how="outer", validate="one_to_one", suffixes=("_a", "_b"), indicator=True)
    require(joined._merge.eq("both").all() and len(joined) == len(a) == len(b),
            f"paired model choices do not cover identical races for {model_a}/{model_b}")
    date_ix = joined.race_date_a.astype(str).map(date_index)
    require(date_ix.notna().all() and np.array_equal(joined.race_date_a.astype(str), joined.race_date_b.astype(str)),
            "paired model dates differ or are absent from fixed schedule")
    row_weights = date_weights[:, date_ix.to_numpy(dtype=int)]

    def ratio(frame_suffix: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        gross = joined[f"gross_return_krw{frame_suffix}"].to_numpy(float)
        stake = joined[f"stake_krw{frame_suffix}"].to_numpy(float)
        hits = joined[f"hit{frame_suffix}"].to_numpy(bool).astype(float)
        selected = joined[f"selected{frame_suffix}"].to_numpy(bool).astype(float)
        g = row_weights @ gross
        s = row_weights @ stake
        h = row_weights @ (hits * selected)
        n = row_weights @ selected
        roi = np.divide(g, s, out=np.full_like(g, np.nan), where=s > 0) - 1.0
        hit_rate = np.divide(h, n, out=np.full_like(h, np.nan), where=n > 0)
        return roi, hit_rate, s

    roi_a, hr_a, _ = ratio("_a")
    roi_b, hr_b, _ = ratio("_b")
    valid_roi = np.isfinite(roi_a) & np.isfinite(roi_b)
    valid_hr = np.isfinite(hr_a) & np.isfinite(hr_b)
    diff_roi = roi_a - roi_b
    diff_hr = hr_a - hr_b
    point_a = float((a.gross_return_krw.sum() / a.stake_krw.sum() - 1.0) * 100) if a.stake_krw.sum() > 0 else None
    point_b = float((b.gross_return_krw.sum() / b.stake_krw.sum() - 1.0) * 100) if b.stake_krw.sum() > 0 else None
    hit_a = float(a.loc[a.selected, "hit"].mean() * 100) if a.selected.any() else None
    hit_b = float(b.loc[b.selected, "hit"].mean() * 100) if b.selected.any() else None
    return {
        "model_a": model_a, "model_b": model_b,
        "roi_delta_a_minus_b_pp": None if point_a is None or point_b is None else point_a - point_b,
        "roi_delta_ci95_low_pp": float(np.nanpercentile(diff_roi[valid_roi], 2.5) * 100) if valid_roi.any() else None,
        "roi_delta_ci95_high_pp": float(np.nanpercentile(diff_roi[valid_roi], 97.5) * 100) if valid_roi.any() else None,
        "roi_delta_valid_draws": int(valid_roi.sum()), "roi_delta_zero_stake_draws": int((~valid_roi).sum()),
        "hit_rate_delta_a_minus_b_pp": None if hit_a is None or hit_b is None else hit_a - hit_b,
        "hit_rate_delta_ci95_low_pp": float(np.nanpercentile(diff_hr[valid_hr], 2.5) * 100) if valid_hr.any() else None,
        "hit_rate_delta_ci95_high_pp": float(np.nanpercentile(diff_hr[valid_hr], 97.5) * 100) if valid_hr.any() else None,
        "hit_rate_delta_valid_draws": int(valid_hr.sum()), "hit_rate_delta_zero_bet_draws": int((~valid_hr).sum()),
    }


def summarize(frame: pd.DataFrame, policies: list[tuple[str, str]], date_weights: np.ndarray,
              date_index: dict[str, int], product: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    policy_names = dict(policies)
    summary_rows: list[dict[str, Any]] = []
    bootstrap_rows: list[dict[str, Any]] = []
    paired_rows: list[dict[str, Any]] = []
    models = sorted(frame.model.unique().tolist())
    for policy_id, policy_name in policies:
        model_frames: dict[str, pd.DataFrame] = {}
        for model in models:
            g = frame.loc[frame.model.eq(model) & frame.policy_id.eq(policy_id)].copy()
            require(g.race_id.nunique() == int(frame.groupby("model").race_id.nunique().min())
                    and not g.duplicated(["race_id"]).any(), f"incomplete strategy/race grid: {model}/{policy_id}")
            model_frames[model] = g
            bets = g.loc[g.selected].copy()
            n_bets = len(bets)
            stake = float(bets.stake_krw.sum())
            gross = float(bets.gross_return_krw.sum())
            net = gross - stake
            hits = int(bets.hit.sum())
            ci = bootstrap_metrics(g, date_weights, date_index)
            paid = bets.loc[bets.gross_return_krw.gt(0)].sort_values(
                ["gross_return_krw", "race_date", "race_id"], ascending=[False, True, True], kind="stable")
            sensitivity: dict[str, Any] = {}
            for top_k in (1, 3, 5):
                removed = paid.head(top_k)
                remaining_stake = stake - STAKE_KRW * len(removed)
                remaining_gross = gross - float(removed.gross_return_krw.sum())
                sensitivity[f"top_{top_k}_winning_tickets_removed"] = int(len(removed))
                sensitivity[f"top_{top_k}_winning_gross_removed_krw"] = float(removed.gross_return_krw.sum())
                sensitivity[f"top_{top_k}_winning_stake_removed_krw"] = float(STAKE_KRW * len(removed))
                sensitivity[f"roi_without_top_{top_k}_winning_tickets_pct"] = (
                    100.0 * (remaining_gross / remaining_stake - 1.0) if remaining_stake > 0 else None
                )
            summary_rows.append({
                "product": product, "model": model, "policy_id": policy_id, "policy": policy_name,
                "period": "2026_partial_common_cohort", "eligible_races": int(g.race_id.nunique()),
                "selected_races": n_bets, "no_bet_races": int(g.race_id.nunique() - n_bets),
                "coverage_pct": 100.0 * n_bets / g.race_id.nunique() if g.race_id.nunique() else None,
                "hits": hits, "hit_rate_pct": 100.0 * hits / n_bets if n_bets else None,
                "mean_p_selected_pct": float(100 * bets.p.mean()) if n_bets else None,
                "mean_p_actual_hits_pct": float(100 * bets.loc[bets.hit, "p"].mean()) if hits else None,
                "mean_final_quote": float(bets.quote.mean()) if n_bets else None,
                "mean_quote_on_hits": float(bets.loc[bets.hit, "quote"].mean()) if hits else None,
                "mean_posthoc_ev_pct": float(100 * bets.model_ev.mean()) if n_bets else None,
                "stake_krw": stake, "gross_return_krw": gross, "net_profit_krw": net,
                "roi_pct": 100 * (gross / stake - 1.0) if stake > 0 else None,
                **ci, **sensitivity,
            })
            bootstrap_rows.append({"product": product, "model": model, "policy_id": policy_id, **ci})
        paired_rows.append({"product": product, "policy_id": policy_id,
                            **paired_difference(model_frames["operating_hy_r_form"],
                                                model_frames["research_pair_id_baseline" if product == "QPL" else "research_f1_style6"],
                                                date_weights, date_index, "operating_hy_r_form",
                                                "research_pair_id_baseline" if product == "QPL" else "research_f1_style6")})
    return pd.DataFrame(summary_rows), pd.DataFrame(bootstrap_rows), pd.DataFrame(paired_rows)


def rank_diagnostics(qpl_pairs: pd.DataFrame, plc_runners: pd.DataFrame,
                     qpl_selected: pd.DataFrame, plc_selected: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    qpl_cal_source = qpl_pairs.copy()
    qpl_cal_source["brier_loss"] = (qpl_cal_source.p - qpl_cal_source.hit.astype(float)) ** 2
    qpl_cal = qpl_cal_source.loc[qpl_cal_source.probability_rank.le(5)].groupby(
        ["model", "probability_rank"], as_index=False
    ).agg(candidate_count=("p", "size"), races=("race_id", "nunique"), mean_p=("p", "mean"),
         observed_hit_rate=("hit", "mean"), brier=("brier_loss", "mean"))
    qpl_cal["observed_hit_rate_pct"] = qpl_cal.pop("observed_hit_rate") * 100
    qpl_cal["mean_p_pct"] = qpl_cal.pop("mean_p") * 100
    plc_cal_source = plc_runners.copy()
    plc_cal_source["brier_loss"] = (plc_cal_source.p - plc_cal_source.hit.astype(float)) ** 2
    plc_cal = plc_cal_source.loc[plc_cal_source.probability_rank.le(5)].groupby(
        ["model", "probability_rank"], as_index=False
    ).agg(candidate_count=("p", "size"), races=("race_id", "nunique"), mean_p=("p", "mean"),
         observed_hit_rate=("hit", "mean"), brier=("brier_loss", "mean"))
    plc_cal["observed_hit_rate_pct"] = plc_cal.pop("observed_hit_rate") * 100
    plc_cal["mean_p_pct"] = plc_cal.pop("mean_p") * 100
    qpl_dist = qpl_selected.loc[qpl_selected.selected].groupby(["model", "policy_id", "probability_rank"], as_index=False).agg(
        selected_races=("race_id", "nunique"), hits=("hit", "sum"), stake_krw=("stake_krw", "sum"),
    )
    plc_dist = plc_selected.loc[plc_selected.selected].groupby(["model", "policy_id", "probability_rank"], as_index=False).agg(
        selected_races=("race_id", "nunique"), hits=("hit", "sum"), stake_krw=("stake_krw", "sum"),
    )
    return qpl_cal, plc_cal, qpl_dist, plc_dist


def qpl_cases(selected: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for model, model_rows in selected.groupby("model", sort=True):
        chosen = model_rows.loc[model_rows.policy_id.eq("top3_max_ev_gt_0") & model_rows.selected
                                & model_rows.probability_rank.gt(1)].copy()
        rank1 = model_rows.loc[model_rows.policy_id.eq("rank_1"),
                               ["race_id", "horse_i", "horse_j", "p", "quote", "model_ev", "hit"]].copy()
        rank1 = rank1.rename(columns={"horse_i": "rank1_horse_i", "horse_j": "rank1_horse_j", "p": "rank1_p",
                                      "quote": "rank1_quote", "model_ev": "rank1_ev", "hit": "rank1_hit"})
        chosen = chosen.merge(rank1, on="race_id", how="left", validate="one_to_one")
        for outcome, label in [(True, "hit"), (False, "miss")]:
            pool = chosen.loc[chosen.hit.eq(outcome)].copy()
            if pool.empty:
                continue
            median_ev = float(pool.model_ev.median())
            pool["distance_to_median_ev"] = (pool.model_ev - median_ev).abs()
            pool = pool.sort_values(["distance_to_median_ev", "race_date", "race_id"], kind="stable").head(5)
            pool["case_group"] = label
            pool["sampling_rule"] = "top3_max_ev_positive rank switches nearest median selected EV within outcome"
            pool["model"] = model
            parts.append(pool)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def plc_cases(selected: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for model, model_rows in selected.groupby("model", sort=True):
        rank3 = model_rows.loc[model_rows.policy_id.eq("p_rank_3")].copy()
        rank1 = model_rows.loc[model_rows.policy_id.eq("p_rank_1"),
                               ["race_id", "horse_number", "p", "quote", "model_ev", "hit"]].copy()
        rank1 = rank1.rename(columns={"horse_number": "rank1_horse_number", "p": "rank1_p",
                                      "quote": "rank1_quote", "model_ev": "rank1_ev", "hit": "rank1_hit"})
        rank3 = rank3.merge(rank1, on="race_id", how="left", validate="one_to_one")
        rank3 = rank3.sort_values(["race_date", "race_id"], kind="stable")
        n_each = min(10, int(rank3.hit.sum()), int((~rank3.hit).sum()))
        if n_each == 0:
            continue
        for outcome, label in [(True, "hit"), (False, "miss")]:
            pool = rank3.loc[rank3.hit.eq(outcome)]
            indexes = np.linspace(0, len(pool) - 1, num=n_each).round().astype(int)
            example = pool.iloc[indexes].copy()
            example["case_group"] = label
            example["sampling_rule"] = "evenly spaced by race date within rank-3 hit/miss group"
            example["model"] = model
            parts.append(example)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def source_path_map() -> dict[str, Path]:
    return {
        "registry": REGISTRY, "current_hy_model": HY_MODEL,
        "resolver": RESOLVER, "hy_distribution_source": HY_FUNCTION,
        "hy_evaluation_manifest": LEGACY / "manifest.json", "hy_split_dates": LEGACY / "split_dates.json",
        "hy_protocol": LEGACY / "protocol.json", "hy_saved_predictions": LEGACY / "horse_predictions.parquet",
        "hy_frozen_scores": LEGACY / "frozen_scores.parquet", "native_races": DATA / "races.parquet",
        "native_entries": DATA / "entries.parquet", "prior_common_alignment": OP_COMPARE / "race_alignment.csv",
        "prior_common_runner_predictions": OP_COMPARE / "runner_predictions.parquet",
        "pair_research_predictions": PAIR_PRED,
        "pair_primary_plan": PAIR_STUDY / "PLAN.md", "pair_price_reference": PAIR_STUDY / "ROOT_QPL_QUOTE_REFERENCE.csv",
        "pair_source_review": PAIR_STUDY / "ROOT_RAW_SOURCE_REVIEW.json",
        "pair_source_census": PAIR_STUDY / "SOURCE_CENSUS.json",
        "plc_research_predictions": PLC_PRED, "plc_prior_plan": PLC_STUDY / "PLAN.md",
        "plc_source_rows": PLC_SOURCE / "PLC_PRICE_ROWS.csv",
        "official_result_rows": PLC_SOURCE / "OFFICIAL_RUNNER_RESULTS.csv",
        "plc_source_audit": PLC_SOURCE / "SOURCE_AUDIT_FINAL.json",
        "plc_source_review": PLC_ROOT_REVIEW / "ROOT_PLC_SOURCE_REVIEW.json",
        "official_source_review": PLC_ROOT_REVIEW / "ROOT_OFFICIAL_SOURCE_REVIEW.json",
        "plc_quote_reference": PLC_STUDY / "ROOT_PLC_QUOTE_REFERENCE.csv",
        "bootstrap_schedule": BOOTSTRAP, "bootstrap_receipt": BOOTSTRAP_RECEIPT,
    }


def main() -> None:
    require(STUDY.name == "20261015_operating_postrace_value_comparison_v1", "unexpected destination folder")
    resolved = registry_resolution()
    reviews = read_source_reviews()
    op_pairs, op_runners, cohort, operating_audit = load_operating_and_cohort()
    common_ids = set(cohort.loc[cohort.qpl_eligible, "race_id"].astype(str))
    qpl_op, qpl_research, qpl_audit = load_qpl_prediction_and_quotes(common_ids, op_pairs)
    plc_op, plc_research, plc_audit = load_plc_predictions_and_quotes(common_ids, op_runners)

    # Freeze ranks and every policy choice from p and post-race quotes before opening any outcome labels.
    qpl_op_ranked = prepare_qpl_ranked(qpl_op)
    qpl_research_ranked = prepare_qpl_ranked(qpl_research)
    qpl_decisions = pd.concat([choose_qpl(qpl_op_ranked), choose_qpl(qpl_research_ranked)], ignore_index=True)
    plc_op_ranked = prepare_plc_ranked(plc_op)
    plc_research_ranked = prepare_plc_ranked(plc_research)
    plc_decisions = pd.concat([choose_plc(plc_op_ranked), choose_plc(plc_research_ranked)], ignore_index=True)

    # The frozen date schedule is loaded and aligned before outcome metrics are attached.
    pair_dates = pd.read_parquet(PAIR_PRED, columns=["race_date"]).race_date
    draws, date_inventory, date_index = load_bootstrap(pd.to_datetime(pair_dates, errors="raise").dt.strftime("%Y-%m-%d").tolist())
    date_weights = fixed_schedule_weights(draws)
    require(date_weights.shape == (2000, 269) and np.all(date_weights.sum(axis=1) == 269),
            "date-bootstrap weights are invalid")

    official, official_audit = official_outcomes(common_ids)
    qpl_selections, plc_selections, outcome_audit = attach_outcomes(
        qpl_decisions, plc_decisions, op_runners, plc_op, official, common_ids,
    )

    # Attach labels to the complete candidate tables after policy selections have been frozen.
    qpl_op_all = qpl_op_ranked.merge(
        official[["race_id", "horse_number", "hit"]].rename(columns={"horse_number": "horse_i", "hit": "hit_i"}),
        on=["race_id", "horse_i"], how="left", validate="many_to_one",
    ).merge(
        official[["race_id", "horse_number", "hit"]].rename(columns={"horse_number": "horse_j", "hit": "hit_j"}),
        on=["race_id", "horse_j"], how="left", validate="many_to_one",
    )
    qpl_op_all["hit"] = qpl_op_all.hit_i.fillna(False) & qpl_op_all.hit_j.fillna(False)
    qpl_research_all = qpl_research_ranked.merge(
        official[["race_id", "horse_number", "hit"]].rename(columns={"horse_number": "horse_i", "hit": "hit_i"}),
        on=["race_id", "horse_i"], how="left", validate="many_to_one",
    ).merge(
        official[["race_id", "horse_number", "hit"]].rename(columns={"horse_number": "horse_j", "hit": "hit_j"}),
        on=["race_id", "horse_j"], how="left", validate="many_to_one",
    )
    qpl_research_all["hit"] = qpl_research_all.hit_i.fillna(False) & qpl_research_all.hit_j.fillna(False)
    qpl_all = pd.concat([qpl_op_all, qpl_research_all], ignore_index=True)

    plc_runner_frames = []
    for source_frame in [plc_op_ranked, plc_research_ranked]:
        joined = source_frame.merge(official[["race_id", "horse_id", "horse_number", "hit"]].rename(
                                        columns={"hit": "hit_official"}),
                                    on=["race_id", "horse_id", "horse_number"], how="left",
                                    validate="one_to_one", indicator=True, suffixes=("_model", "_official"))
        require(joined._merge.eq("both").all(), "PLC full runner candidates do not join to official labels")
        joined["hit"] = joined.hit_official.astype(bool)
        plc_runner_frames.append(joined.drop(columns=["_merge", "hit_official"]))
    plc_all = pd.concat(plc_runner_frames, ignore_index=True)

    qpl_summary, qpl_bootstrap, qpl_paired = summarize(qpl_selections, QPL_POLICIES, date_weights, date_index, "QPL")
    plc_summary, plc_bootstrap, plc_paired = summarize(plc_selections, PLC_POLICIES, date_weights, date_index, "PLC")
    qpl_cal, plc_cal, qpl_dist, plc_dist = rank_diagnostics(qpl_all, plc_all, qpl_selections, plc_selections)
    qpl_case_table = qpl_cases(qpl_selections)
    plc_case_table = plc_cases(plc_selections)

    # The paired intervals use exactly the same date draws, including zero-weighted comparison dates.
    write_csv(cohort.sort_values(["race_date", "race_id"], kind="stable"), "cohort.csv")
    write_csv(qpl_all.sort_values(["model", "race_id", "probability_rank"], kind="stable"), "qpl_pair_rows.csv")
    write_csv(qpl_selections.sort_values(["model", "race_id", "policy_id"], kind="stable"), "qpl_selected_rows.csv")
    write_csv(qpl_summary, "qpl_strategy_summary.csv")
    write_csv(qpl_cal, "qpl_rank_calibration.csv")
    write_csv(qpl_dist, "qpl_selection_rank_distribution.csv")
    write_csv(qpl_bootstrap, "qpl_bootstrap_ci.csv")
    write_csv(qpl_paired, "qpl_paired_differences.csv")
    write_csv(qpl_case_table, "qpl_cases.csv")
    write_csv(plc_all.sort_values(["model", "race_id", "probability_rank"], kind="stable"), "plc_runner_rows.csv")
    write_csv(plc_selections.sort_values(["model", "race_id", "policy_id"], kind="stable"), "plc_selected_rows.csv")
    write_csv(plc_summary, "plc_strategy_summary.csv")
    write_csv(plc_cal, "plc_rank_calibration.csv")
    write_csv(plc_dist, "plc_selection_rank_distribution.csv")
    write_csv(plc_bootstrap, "plc_bootstrap_ci.csv")
    write_csv(plc_paired, "plc_paired_differences.csv")
    write_csv(plc_case_table, "plc_cases.csv")

    resolved_artifacts = {item.get("name"): item for item in resolved.get("verified_artifacts", [])}
    audit = {
        "status": "PASS", "comparison_type": "retrospective_final_price_oracle",
        "operating_model_registry_resolution": {
            "active_profile": resolved.get("active_profile"), "champion_id": resolved.get("champion_id"),
            "registry_sha256": resolved.get("registry_sha256"),
            "model_artifact": resolved_artifacts.get("HY_R_FORM_model"),
        },
        "temporal_scope": {
            "operating_fit": {"from": "2018-08-31", "through": "2025-06-28", "races": 3974},
            "operating_tune": {"from": "2025-07-04", "through": "2025-09-27", "races": 192},
            "operating_calibration": {"from": "2025-10-02", "through": "2025-12-27", "races": 167},
            "operating_saved_evaluation": {"from": "2026-01-02", "through": "2026-09-12", "races": 510,
                                             "entries": 4852},
            "current_hy_2025_oos_predictions_available": False,
            "current_hy_saved_outputs_are_actual_live_published_predictions": False,
            "2026_is_partial_and_reused_development_data": True,
            "history_updates_are_sequential_t_minus_2": True,
        },
        "cohort": {
            "qpl_common_races": 467, "qpl_common_dates": qpl_audit["qpl_dates"],
            "qpl_period": ["2026-01-02", "2026-09-12"],
            "plc_common_supported_races": 436, "plc_common_dates": plc_audit["plc_dates"],
            "plc_period": [str(plc_all.race_date.min()), str(plc_all.race_date.max())],
            "operating_only_vs_prior_common_cohort": 43, "later_research_only_after_operating_cutoff": 21,
            "common_races_excluded_from_f1_style6_plc_for_field_n_le_7": 31,
            "year_2025_comparison": "unavailable: current HY fitted/tuned/calibrated during 2025; no retained year-frozen HY score archive",
        },
        "coverage_audit": {**operating_audit, **qpl_audit, **plc_audit, **official_audit, **outcome_audit},
        "native_probability_contract": {
            "qpl_hy": "sum exact native HY Top3-set probability over every set containing both horses",
            "plc_hy": "native HY runner Top3 marginal from the same saved-score distribution",
            "set_mass_sum_checked_per_race": True,
            "runner_top3_mass_sum_checked_per_race": True,
            "pair_top3_joint_mass_sum_checked_per_race": True,
            "runner_product_used": False,
            "single_unordered_top3_set_probability_used_as_pair_probability": False,
            "operating_exact_raw_score_tied_races": operating_audit["hy_exact_raw_score_tied_races"],
        },
        "rules": {"qpl_rule_count": len(QPL_POLICIES), "plc_rule_count": len(PLC_POLICIES),
                  "summary_rows": int(len(qpl_summary) + len(plc_summary)),
                  "max_selected_tickets_per_race": 1, "stake_krw_per_selected_ticket": STAKE_KRW},
        "bootstrap": {"schedule_sha256": EXPECTED_SCHEDULE_SHA, "draws": 2000, "dates_per_draw": 269,
                      "date_inventory_sha256": hashlib.sha256("\n".join(date_inventory).encode()).hexdigest(),
                      "all_noneligible_dates_zero_selection": True,
                      "paired_operating_minus_research_intervals": True},
        "source_review_status": {
            "qpl_raw_source_review": reviews["qpl_direct_review"].get("status"),
            "qpl_full_census": reviews["qpl_source_census_status"],
            "plc_source_audit": reviews["plc_source_audit"].get("status"),
            "plc_direct_quote_review": reviews["plc_direct_review"].get("status"),
            "official_roster_review": reviews["official_result_review"].get("status"),
        },
        "non_actions": {"training": False, "calibration_fit": False, "network": False, "database_write": False,
                         "registry_or_operations_change": False, "old_study_modified": False},
    }
    save_json(STUDY / "SOURCE_AUDIT.json", audit)
    save_json(STUDY / "REPORT.json", {
        "status": "PASS", "interpretation": "post-race final-price oracle; retrospective 2026 partial development data",
        "qpl_strategy_summary": qpl_summary.to_dict(orient="records"),
        "qpl_paired_differences": qpl_paired.to_dict(orient="records"),
        "plc_strategy_summary": plc_summary.to_dict(orient="records"),
        "plc_paired_differences": plc_paired.to_dict(orient="records"),
        "source_audit": "SOURCE_AUDIT.json",
    })
    hashes = source_hashes(source_path_map())
    hashes["frozen_plan"] = sha256_file(STUDY / "PLAN.md")
    hashes["analysis_code"] = sha256_file(STUDY / "analysis.py")
    save_json(STUDY / "SOURCE_MANIFEST.json", {
        "status": "PASS", "source_sha256": hashes, "registry_resolver": resolved,
        "output_rows": {
            "cohort.csv": int(len(cohort)), "qpl_pair_rows.csv": int(len(qpl_all)),
            "qpl_selected_rows.csv": int(len(qpl_selections)), "qpl_strategy_summary.csv": int(len(qpl_summary)),
            "qpl_rank_calibration.csv": int(len(qpl_cal)), "qpl_selection_rank_distribution.csv": int(len(qpl_dist)),
            "qpl_bootstrap_ci.csv": int(len(qpl_bootstrap)), "qpl_paired_differences.csv": int(len(qpl_paired)),
            "plc_runner_rows.csv": int(len(plc_all)), "plc_selected_rows.csv": int(len(plc_selections)),
            "plc_strategy_summary.csv": int(len(plc_summary)), "plc_rank_calibration.csv": int(len(plc_cal)),
            "plc_selection_rank_distribution.csv": int(len(plc_dist)), "plc_bootstrap_ci.csv": int(len(plc_bootstrap)),
            "plc_paired_differences.csv": int(len(plc_paired)),
        },
    })
    README = f"""# 운영 HY_R_FORM과 저장 연구 모델의 동일 경주 사후 가치 비교

현재 운영 등록부에서 해시 검증된 HY_R_FORM의 저장된 2026 평가 점수와, 기존 연구에서 고정한 `pair_id_baseline` QPL 확률 및 `F1_STYLE6` PLC 확률을 동일한 경주·최종 표시 배당에 적용했다. 모든 고정 정책을 전산출했고, QPL은 467경주·70일, PLC는 같은 경주 중 F1_STYLE6 native Top3 확률을 지원하는 436경주·69일로 비교했다.

비교 cohort는 2026-01-02~09-12의 467개 complete/normal 공통 경주다. 운영 저장 평가 510경주 중 43경주는 기존 정상 편성 비교 cohort 밖이고, 연구 예측 중 21경주는 09-17~19로 운영 평가 cutoff 뒤라 포함하지 않았다. PLC는 두 모델을 같은 8두 이상 조건에 맞춰 7두 이하 31경주를 제외했다. 2025년 HY 예측은 현재 frozen model의 fit·tune·calibration 기간에 포함되며 연도별 OOS raw-score archive가 없어 비교하지 않았다.

HY의 QPL pair 확률은 운영 함수가 산출하는 정확한 unordered Top3-set 확률을 모두 합산해, 해당 두 말이 같이 Top3에 드는 joint probability로 계산했다. HY의 PLC 확률은 같은 분포의 native runner Top3 주변확률이며 저장 `pl_place_probability`와 일치했다. runner 확률끼리 곱하거나 단일 Top3 집합 확률을 QPL pair 확률로 대신하지 않았다. 연구 QPL은 저장 `jockey_id_candidate_calibrated_probability`; 연구 PLC는 저장 F1_STYLE6 native `p_top3`다.

최종 가격이 결과 뒤에 확정되므로 `p × final odds − 1`은 사후 oracle 선택 점수다. ROI는 stake 포함 최종 총환급에서 stake를 빼 계산했다. 이 자료는 반복 분석된 부분연도 개발 자료이며 실제 사전 구매 가능성·운영 게시 성적·독립 미래 검증을 뜻하지 않는다. 2026 예측은 저장된 offline frozen 평가 산출물로, 각 경주일 실제 live 게시 출력이 아니다. 경주 이력은 T−2 시점까지 순차 갱신한다.

재현 코드는 `.venv/bin/python -B jeju/research/20261015_operating_postrace_value_comparison_v1/analysis.py`이다. 모든 13개 QPL 및 8개 PLC 규칙, 정책별 2,000×269 paired-date bootstrap, 미선택 경주, 최대 당첨 1·3·5건과 티켓 stake를 함께 뺀 민감도는 CSV로 보존했다. 기존 고정 bootstrap은 비교 cohort 밖 날짜도 각 draw에 포함하고, 그 날짜는 선택 0건으로 반영한다. root 독립 재계산은 별도 review 작업에서 수행한다.

주요 표는 `qpl_strategy_summary.csv`, `plc_strategy_summary.csv`, 두 `*_paired_differences.csv`, `qpl_rank_calibration.csv`, `plc_rank_calibration.csv`다. 전 후보확률·선택·가격·결과는 `qpl_pair_rows.csv`, `plc_runner_rows.csv`, `qpl_selected_rows.csv`, `plc_selected_rows.csv`에 있다. Cohort 제외 근거와 원천 해시는 각각 `cohort.csv`, `SOURCE_AUDIT.json`, `SOURCE_MANIFEST.json`, `FINAL_MANIFEST.json`을 본다.
"""
    (STUDY / "README.md").write_text(README, encoding="utf-8")
    final_files = sorted(p for p in STUDY.iterdir() if p.is_file() and p.name != "FINAL_MANIFEST.json")
    final_manifest = {p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size} for p in final_files}
    save_json(STUDY / "FINAL_MANIFEST.json", {"status": "PASS", "files": final_manifest,
                                               "files_count": len(final_manifest)})
    print(json.dumps({"status": "PASS", "qpl_races": 467, "plc_races": 436,
                      "qpl_pair_rows_per_model": qpl_audit["qpl_pair_rows_per_model"],
                      "plc_runner_rows_per_model": plc_audit["plc_runner_rows_per_model"],
                      "summary_rows": len(qpl_summary) + len(plc_summary),
                      "qpl_top_policies": qpl_summary.sort_values("roi_pct", ascending=False)
                      [["model", "policy_id", "eligible_races", "selected_races", "hits", "roi_pct"]]
                      .head(6).to_dict(orient="records"),
                      "plc_top_policies": plc_summary.sort_values("roi_pct", ascending=False)
                      [["model", "policy_id", "eligible_races", "selected_races", "hits", "roi_pct"]]
                      .head(6).to_dict(orient="records")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

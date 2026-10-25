"""Evaluate complete-price Jeju operating candidates in five non-PLC/QPL pools."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
LEGACY = ROOT / "data/research/jeju_native_transition_holdout_v13_20260916"
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"
PREVIOUS = ROOT / "jeju/research/20261015_operating_postrace_value_comparison_v1"
PAIR_PRED = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
SOURCE_PREFLIGHT = STUDY / "SOURCE_PREFLIGHT.json"
SOURCE_QUOTES = STUDY / "candidate_quotes.csv"
OFFICIAL = ROOT / "jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv"
TLA_RESEARCH = ROOT / "jeju/research/20261015_research_other_pool_support_v1/tla_set_probabilities.parquet"
TLA_RECEIPT = ROOT / "jeju/research/20261015_other_pools_rootreview_v1/ROOT_RESEARCH_TLA_RECEIPT.json"
BOOTSTRAP = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
REGISTRY = ROOT / "config/prediction_model_registry.json"
HY_MODEL = ROOT / "jeju/models/current/HY_R_FORM.pkl"
RESOLVER = ROOT / ".agents/skills/horse-racing-prediction-publisher/scripts/resolve_main_model.py"
HY_FUNCTION = ROOT / "src/horse_racing/analysis/jeju_hybrid_evaluation.py"
STAKES = 1_000.0

EXPECTED = {
    "registry": "944e4aad25c99d3d346dab23c7f7596c216d8722a548dea2c7c07abf9b10b70b",
    "hy_model": "f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706",
    "hy_function": "61409385b5748d2df6a34fcd4eca5bd453669c0421c024f34e55aca216050aa7",
    "tla_research": "7c7bafcb315a9f9595e06aa1ee12ca0affbcf3abcc13426e90e079261d29b382",
    "bootstrap": "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
    "bootstrap_receipt": "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e",
}

POOLS = ("WIN", "QNL", "EXA", "TLA", "TRI")
POOL_LABELS = {"WIN": "단승", "QNL": "복승", "EXA": "쌍승", "TLA": "삼복승", "TRI": "삼쌍승"}
POLICIES = [
    ("p_rank_1", "p rank 1"),
    ("p_rank_2", "p rank 2"),
    ("p_rank_3", "p rank 3"),
    ("p_rank_4", "p rank 4"),
    ("p_rank_5", "p rank 5"),
    ("p_rank_1_ev_positive", "p rank 1 EV > 0"),
    ("all_max_ev_positive", "all candidates max EV > 0"),
    ("top3_max_ev_positive", "p ranks 1-3 max EV > 0"),
    ("top5_max_ev_positive", "p ranks 1-5 max EV > 0"),
    ("top3_max_ev_gt_020", "p ranks 1-3 max EV > 0.20"),
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


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(frame: pd.DataFrame, name: str) -> None:
    path = (STUDY / name).resolve()
    require(path.parent == STUDY.resolve(), f"output escaped new study directory: {name}")
    frame.to_csv(path, index=False, na_rep="")


def numeric_key(row: pd.Series) -> tuple[int, int, int]:
    return tuple(int(row[column]) if pd.notna(row[column]) else 0
                 for column in ["horse_no_1", "horse_no_2", "horse_no_3"])


def key_columns(key: tuple[int, ...]) -> tuple[int | None, int | None, int | None]:
    vals = tuple(int(v) for v in key) + (None, None, None)
    return vals[0], vals[1], vals[2]


def key_text(key: tuple[int, ...]) -> str:
    return "-".join(str(int(v)) for v in key)


def key_for_pool(pool: str, values: tuple[int, ...]) -> tuple[int, ...]:
    vals = tuple(int(v) for v in values)
    return tuple(sorted(vals)) if pool in {"QNL", "TLA"} else vals


def registry_resolution() -> dict[str, Any]:
    require(sha256_file(REGISTRY) == EXPECTED["registry"], "active registry SHA changed")
    require(sha256_file(HY_MODEL) == EXPECTED["hy_model"], "HY_R_FORM model SHA changed")
    require(sha256_file(HY_FUNCTION) == EXPECTED["hy_function"], "HY distribution function SHA changed")
    result = subprocess.run(
        [sys.executable, "-B", str(RESOLVER), "--repo-root", str(ROOT), "--domain", "jeju"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    resolved = json.loads(result.stdout)
    require(resolved.get("ok") is True and resolved.get("champion_id") == "HY_R_FORM"
            and resolved.get("active_profile") == "jeju-hy-r-form-20260919-v1",
            "read-only resolver no longer selects active HY_R_FORM")
    model_record = {row.get("name"): row for row in resolved.get("verified_artifacts", [])}
    require(model_record.get("HY_R_FORM_model", {}).get("sha256") == EXPECTED["hy_model"],
            "resolver did not verify the current HY_R_FORM pkl hash")
    return resolved


def load_bootstrap() -> tuple[np.ndarray, list[str], dict[str, int]]:
    require(sha256_file(BOOTSTRAP) == EXPECTED["bootstrap"], "fixed bootstrap schedule SHA changed")
    require(sha256_file(BOOTSTRAP_RECEIPT) == EXPECTED["bootstrap_receipt"],
            "fixed bootstrap receipt SHA changed")
    receipt = json.loads(BOOTSTRAP_RECEIPT.read_text(encoding="utf-8"))
    pair = pd.read_parquet(PAIR_PRED, columns=["race_date"])
    dates = sorted(set(pd.to_datetime(pair.race_date, errors="raise").dt.strftime("%Y-%m-%d")))
    inventory_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS"
            and receipt.get("draws") == 2000 and receipt.get("dates_per_draw") == 269
            and receipt.get("date_inventory_sha256") == inventory_hash,
            "fixed 2,000x269 schedule differs from prior common date inventory")
    draws = np.load(BOOTSTRAP, allow_pickle=False)
    require(draws.shape == (2000, 269) and draws.dtype.kind in "iu"
            and draws.min() >= 0 and draws.max() < 269, "invalid bootstrap draws")
    return draws, dates, {date: index for index, date in enumerate(dates)}


def schedule_weights(draws: np.ndarray) -> np.ndarray:
    return np.stack([np.bincount(row, minlength=269) for row in draws]).astype(np.int64)


def main() -> None:
    resolved_model = registry_resolution()
    source = json.loads(SOURCE_PREFLIGHT.read_text(encoding="utf-8"))
    require(source.get("status") == "PASS"
            and source.get("phase") == "source_only_preflight_before_probability_returns",
            "candidate source preflight has not passed")
    require(sha256_file(SOURCE_QUOTES) == source.get("source_hashes", {}).get("candidate_quotes_output"),
            "quote candidate artifact hash differs from source preflight")

    prior_cohort = pd.read_csv(PREVIOUS / "cohort.csv", dtype={"race_id": "string", "race_date": "string"})
    cohort = prior_cohort.loc[prior_cohort.qpl_eligible.astype(bool)].copy()
    cohort["race_id"] = cohort.race_id.astype(str)
    require(len(cohort) == cohort.race_id.nunique() == 467, "prior common matched race cohort changed")
    common_ids = set(cohort.race_id)
    universal_ids = set(pd.read_csv(STUDY / "source_exclusions.csv", dtype={"race_id": "string"}).race_id.astype(str))
    tri_incomplete = universal_ids
    universal_ids = common_ids - tri_incomplete
    require(len(tri_incomplete) == 245 and len(universal_ids) == 222,
            "TRI complete price race exclusions changed")

    # Reconcile frozen prediction score inputs and join event/horse numbers using saved native keys.
    saved = pd.read_parquet(
        LEGACY / "horse_predictions.parquet",
        columns=["entry_id", "race_id", "horse_id", "event_date", "distance_m", "model", "score",
                 "beta", "order_score", "beta_order", "pl_place_probability"],
    )
    saved = saved.loc[saved.model.eq("HY_R_FORM")].copy()
    frozen = pd.read_parquet(
        LEGACY / "frozen_scores.parquet",
        columns=["entry_id", "race_id", "horse_id", "event_date", "distance_m", "model", "score",
                 "beta", "order_score", "beta_order"],
    )
    frozen = frozen.loc[frozen.model.eq("HY_R_FORM")].copy()
    score_join = saved.merge(
        frozen, on=["entry_id", "race_id", "horse_id", "event_date", "distance_m", "model"],
        how="outer", validate="one_to_one", indicator=True, suffixes=("_saved", "_frozen"),
    )
    require(score_join._merge.eq("both").all() and len(score_join) == 4852,
            "saved HY predictions differ from frozen score roster")
    for column in ["score", "beta", "order_score", "beta_order"]:
        require(np.array_equal(score_join[f"{column}_saved"].to_numpy(float),
                               score_join[f"{column}_frozen"].to_numpy(float), equal_nan=True),
                f"saved HY {column} differs from frozen score input")

    races = pd.read_parquet(DATA / "races.parquet", columns=["race_id", "event_number"])
    entries = pd.read_parquet(DATA / "entries.parquet", columns=["entry_id", "horse_number"])
    require(not races.race_id.duplicated().any() and not entries.entry_id.duplicated().any(),
            "saved native race/entry keys are duplicated")
    hyd = saved.merge(races, on="race_id", how="left", validate="many_to_one", indicator=True)
    require(hyd._merge.eq("both").all(), "saved predictions lack saved event numbers")
    hyd = hyd.drop(columns="_merge").merge(entries, on="entry_id", how="left", validate="one_to_one", indicator=True)
    require(hyd._merge.eq("both").all(), "saved predictions lack horse numbers")
    hyd = hyd.drop(columns="_merge")
    hyd["race_id"] = [f"{d}_2_{int(n)}" for d, n in zip(hyd.event_date, hyd.event_number)]
    hyd["race_date"] = pd.to_datetime(hyd.event_date, errors="raise").dt.strftime("%Y-%m-%d")
    hyd["horse_id"] = hyd.horse_id.astype(str)
    hyd["horse_number"] = pd.to_numeric(hyd.horse_number, errors="raise").astype(int)
    hyd = hyd.loc[hyd.race_id.isin(common_ids)].copy()
    require(hyd.race_id.nunique() == 467 and len(hyd) == 4475, "HY frozen common runner support changed")
    require(not hyd.duplicated(["race_id", "horse_id"]).any()
            and not hyd.duplicated(["race_id", "horse_number"]).any(), "HY common runner keys duplicate")

    sys.path.insert(0, str(ROOT / "src"))
    from horse_racing.analysis.jeju_hybrid_evaluation import distribution

    probability_rows: list[dict[str, Any]] = []
    mass_audit_rows: list[dict[str, Any]] = []
    for race_id, race in hyd.groupby("race_id", sort=True):
        race = race.sort_values("horse_number", kind="stable").reset_index(drop=True)
        n = len(race)
        require(n >= 3 and race.horse_number.nunique() == n, f"invalid HY roster: {race_id}")
        require(race.beta.nunique() == 1 and race.beta_order.nunique() == 1,
                f"inconsistent within-race HY temperatures: {race_id}")
        sets, orders, log_sets, log_joint, marginals = distribution(
            race.score.to_numpy(float), race.order_score.to_numpy(float),
            float(race.beta.iloc[0]), float(race.beta_order.iloc[0]),
        )
        order_p = np.exp(log_joint)
        require(np.isclose(order_p.sum(), 1.0, rtol=0, atol=1e-12), f"ordered HY probability mass != 1: {race_id}")
        require(np.isclose(np.exp(log_sets).sum(), 1.0, rtol=0, atol=1e-12), f"HY set mass != 1: {race_id}")
        require(np.isclose(marginals.sum(), 3.0, rtol=0, atol=1e-12), f"HY runner Top3 mass != 3: {race_id}")
        if race.pl_place_probability.notna().all():
            require(np.allclose(marginals, race.pl_place_probability.to_numpy(float), rtol=0, atol=1e-12),
                    f"HY native ordered probability runner marginals differ from saved top3 p: {race_id}")
        nums = race.horse_number.to_numpy(int)
        order_numbers = nums[orders]
        order_frame = pd.DataFrame({"a": order_numbers[:, 0], "b": order_numbers[:, 1],
                                    "c": order_numbers[:, 2], "mass": order_p})
        order_frame["u1"] = np.minimum(order_frame.a, order_frame.b)
        order_frame["u2"] = np.maximum(order_frame.a, order_frame.b)
        order_frame["t1"] = order_frame[["a", "b", "c"]].min(axis=1)
        order_frame["t3"] = order_frame[["a", "b", "c"]].max(axis=1)
        order_frame["t2"] = order_frame[["a", "b", "c"]].sum(axis=1) - order_frame.t1 - order_frame.t3
        masses = {
            "WIN": order_frame.groupby("a", sort=True).mass.sum().to_dict(),
            "QNL": {(int(a), int(b)): float(p) for (a, b), p in
                    order_frame.groupby(["u1", "u2"], sort=True).mass.sum().items()},
            "EXA": {(int(a), int(b)): float(p) for (a, b), p in
                    order_frame.groupby(["a", "b"], sort=True).mass.sum().items()},
            "TLA": {(int(a), int(b), int(c)): float(p) for (a, b, c), p in
                    order_frame.groupby(["t1", "t2", "t3"], sort=True).mass.sum().items()},
            "TRI": {(int(a), int(b), int(c)): float(p) for (a, b, c), p in
                    order_frame.groupby(["a", "b", "c"], sort=True).mass.sum().items()},
        }
        for pool in POOLS:
            pool_values = list(masses[pool].values())
            require(np.isclose(sum(pool_values), 1.0, rtol=0, atol=1e-12),
                    f"HY {pool} event probability mass != 1: {race_id}")
            for key, probability in masses[pool].items():
                key = key_for_pool(pool, tuple(key) if isinstance(key, tuple) else (int(key),))
                h1, h2, h3 = key_columns(key)
                probability_rows.append({"race_id": race_id, "race_date": race.race_date.iloc[0], "field_n": n,
                                        "pool": pool, "selection_key": key_text(key),
                                        "horse_no_1": h1, "horse_no_2": h2, "horse_no_3": h3,
                                        "p": float(probability), "model": "operating_hy_r_form"})
        mass_audit_rows.append({"race_id": race_id, "field_n": n,
                                "ordered_top3_mass": float(order_p.sum()),
                                "top3_set_mass": float(np.exp(log_sets).sum()),
                                "runner_top3_marginal_sum": float(marginals.sum()),
                                **{f"{pool}_event_mass": float(sum(masses[pool].values())) for pool in POOLS}})
    operating_prob = pd.DataFrame(probability_rows)
    expected_candidate_counts = {"WIN": 4475, "QNL": 19388, "EXA": 38776, "TLA": 50017, "TRI": 300102}
    require(operating_prob.groupby("pool").size().to_dict() == expected_candidate_counts,
            "native HY event probability table has wrong candidate cardinality")

    # Independent native F1_STYLE6 TLA research event probabilities, supplied with a separate PASS receipt.
    require(sha256_file(TLA_RESEARCH) == EXPECTED["tla_research"], "research native TLA artifact SHA changed")
    research_receipt = json.loads(TLA_RECEIPT.read_text(encoding="utf-8"))
    require(research_receipt.get("status") == "PASS" and research_receipt.get("rows") == 50017
            and research_receipt.get("artifact_sha256") == EXPECTED["tla_research"],
            "independent native TLA probability audit did not pass")
    tla_research = pd.read_parquet(TLA_RESEARCH)
    required_tla_cols = {"race_id", "race_date", "field_n", "horse_no_1", "horse_no_2", "horse_no_3",
                         "horse_id_1", "horse_id_2", "horse_id_3", "set_probability"}
    require(required_tla_cols.issubset(tla_research.columns), "research TLA artifact schema changed")
    tla_research["race_id"] = tla_research.race_id.astype(str)
    require(len(tla_research) == 50017 and tla_research.race_id.nunique() == 467
            and set(tla_research.race_id) == common_ids, "research TLA artifact race coverage changed")
    tla_research["selection_key"] = [key_text(tuple(sorted((int(a), int(b), int(c)))))
                                     for a, b, c in zip(tla_research.horse_no_1,
                                                        tla_research.horse_no_2, tla_research.horse_no_3)]
    require(not tla_research.duplicated(["race_id", "selection_key"]).any(), "research TLA keys are duplicated")
    tla_research["p"] = pd.to_numeric(tla_research.set_probability, errors="raise")
    require(np.isfinite(tla_research.p.to_numpy(float)).all() and tla_research.p.between(0, 1).all(),
            "research TLA probabilities are outside [0,1]")
    research_sums = tla_research.groupby("race_id").p.sum()
    require(np.allclose(research_sums.to_numpy(float), 1.0, rtol=0, atol=1e-12),
            "research TLA unordered set probabilities do not sum to 1")
    roster_fields = hyd.groupby("race_id").size()
    require(tla_research.groupby("race_id").field_n.first().eq(roster_fields).all(),
            "research TLA field size differs from native HY roster")
    research_tla_prob = tla_research[["race_id", "race_date", "field_n", "selection_key", "horse_no_1", "horse_no_2",
                                     "horse_no_3", "p"]].copy()
    research_tla_prob["pool"] = "TLA"
    research_tla_prob["model"] = "research_f1_style6_native"
    require(set(research_tla_prob.selection_key) == set(operating_prob.loc[
        operating_prob.pool.eq("TLA"), "selection_key"])
        and not research_tla_prob.merge(operating_prob.loc[operating_prob.pool.eq("TLA"),
            ["race_id", "selection_key"]], on=["race_id", "selection_key"], how="outer",
            validate="one_to_one", indicator=True)._merge.ne("both").any(),
        "research TLA full candidate key set differs from the native 467-race roster")

    probability = pd.concat([operating_prob, research_tla_prob], ignore_index=True, sort=False)
    quotes = pd.read_csv(SOURCE_QUOTES, dtype={"race_id": "string", "race_date": "string",
                                               "pool": "string", "selection_key": "string",
                                               "source_page_sha256": "string"})
    quotes["race_id"] = quotes.race_id.astype(str)
    quotes["parsed_odds"] = pd.to_numeric(quotes.parsed_odds, errors="coerce")
    joined = probability.merge(
        quotes, on=["race_id", "race_date", "pool", "selection_key"], how="outer",
        validate="many_to_one", indicator=True, suffixes=("_p", "_q"),
    )
    require(joined._merge.eq("both").all(), "native event probability and full price candidates do not match one-to-one")
    require(joined.loc[joined.model.eq("operating_hy_r_form"), "model"].notna().all(), "HY event p missing")
    joined = joined.drop(columns="_merge")
    joined["quote"] = joined.parsed_odds
    joined["ev"] = joined.p * joined.quote - 1.0
    joined["pool_label_ko"] = joined.pool.map(POOL_LABELS)
    tri_invalid = joined.pool.eq("TRI") & joined.quote_status.ne("valid")
    require(tri_invalid.sum() == 15343 and joined.loc[tri_invalid, "model"].eq("operating_hy_r_form").sum() == 15343,
            "TRI invalid candidate quote count changed")
    require(joined.loc[~tri_invalid, "quote_status"].eq("valid").all(), "non-TRI or TLA research price is invalid")

    # Complete-price scopes were fixed in PLAN before candidate policy evaluation.
    source_exclusions = pd.read_csv(STUDY / "source_exclusions.csv", dtype={"race_id": "string"})
    tri_incomplete_ids = set(source_exclusions.race_id.astype(str))
    universal_ids = common_ids - tri_incomplete_ids
    scope_rows: list[dict[str, Any]] = []
    for pool in POOLS:
        primary_ids = universal_ids if pool == "TRI" else common_ids
        for scope, ids in [("per_pool_primary", primary_ids), ("universal_222", universal_ids)]:
            scope_rows.extend({"pool": pool, "scope": scope, "race_id": rid,
                               "primary_scope_equals_universal": pool == "TRI"}
                              for rid in sorted(ids))
    scopes = pd.DataFrame(scope_rows).drop_duplicates(["pool", "scope", "race_id"])
    require(scopes.groupby(["pool", "scope"]).race_id.nunique().to_dict() == {
        (pool, scope): (467 if scope == "per_pool_primary" and pool != "TRI" else 222)
        for pool in POOLS for scope in ["per_pool_primary", "universal_222"]
    }, "primary/universal scope race counts changed")

    # Validate probability candidate cardinality and p mass by pool/model/race.
    counts_by_model = joined.groupby(["model", "pool"]).size().to_dict()
    require(all(counts_by_model[("operating_hy_r_form", pool)] == expected_candidate_counts[pool] for pool in POOLS),
            "HY candidate rows changed after attaching API301 quotes")
    require(counts_by_model[("research_f1_style6_native", "TLA")] == 50017,
            "research TLA candidate row count changed")
    p_sums = joined.groupby(["model", "pool", "race_id"]).p.sum()
    require(np.allclose(p_sums.to_numpy(float), 1.0, rtol=0, atol=1e-12),
            "per-race candidate event probabilities fail to sum to 1")

    # Choices use only p, fixed odds, and the fixed PLAN; official outcomes are not loaded here.
    choices, decisions = build_decisions(joined, scopes)
    write_csv(decisions, "policy_decisions_pre_outcome.csv")
    preoutcome_sha = sha256_file(STUDY / "policy_decisions_pre_outcome.csv")

    candidate_export = joined[["race_id", "race_date", "pool", "pool_label_ko", "model", "selection_key",
                               "field_n", "horse_no_1", "horse_no_2", "horse_no_3", "p", "raw_odds", "quote",
                               "quote_status", "ev", "source_run_id", "source_page_path", "source_page_sha256"]].copy()
    primary_by_pool = {pool: set(scopes.loc[scopes.scope.eq("per_pool_primary") & scopes.pool.eq(pool),
                                             "race_id"].astype(str)) for pool in POOLS}
    candidate_export["primary_price_complete"] = [
        str(race_id) in primary_by_pool[pool]
        for pool, race_id in zip(candidate_export.pool, candidate_export.race_id)
    ]
    candidate_export["universal_222_price_complete"] = candidate_export.race_id.isin(universal_ids)

    official = pd.read_csv(OFFICIAL, dtype={"race_id": "string", "kra_horse_id": "string"})
    official = official.loc[official.race_id.astype(str).isin(common_ids)].copy()
    official["race_id"] = official.race_id.astype(str)
    official["horse_number"] = pd.to_numeric(official.horse_number, errors="raise").astype(int)
    official["finish_position"] = pd.to_numeric(official.finish_position, errors="raise").astype(int)
    official_by_race = {rid: dict(zip(part.finish_position, part.horse_number))
                        for rid, part in official.groupby("race_id", sort=False)}
    require(all(set(result) >= {1, 2, 3} for result in official_by_race.values()),
            "official outcome file lacks an exact ordered Top3")
    labels = []
    for row in candidate_export.itertuples(index=False):
        result = official_by_race[row.race_id]
        first, second, third = result[1], result[2], result[3]
        actual_key = {
            "WIN": (first,), "QNL": tuple(sorted((first, second))), "EXA": (first, second),
            "TLA": tuple(sorted((first, second, third))), "TRI": (first, second, third),
        }[row.pool]
        labels.append(int(tuple(int(x) for x in row.selection_key.split("-")) == actual_key))
    candidate_export["hit"] = np.asarray(labels, dtype=np.int8)
    write_csv(candidate_export, "candidate_rows.csv")

    hit_lookup = candidate_export[["race_id", "race_date", "pool", "model", "selection_key", "hit"]].rename(
        columns={"selection_key": "selected_selection_key"}
    )
    decisions = decisions.merge(
        hit_lookup,
        on=["race_id", "race_date", "pool", "model", "selected_selection_key"], how="left",
        validate="many_to_one", indicator=True,
    )
    require(decisions.loc[decisions.selected, "_merge"].eq("both").all(),
            "selected event has no official outcome")
    decisions["hit"] = decisions.selected & decisions.hit.fillna(0).astype(bool)
    decisions = decisions.drop(columns="_merge")
    decisions["stake_krw"] = decisions.selected.astype(float) * STAKES
    decisions["gross_return_krw"] = np.where(
        decisions.selected & decisions.hit, decisions.selected_quote.astype(float) * STAKES, 0.0
    )
    decisions["net_profit_krw"] = decisions.gross_return_krw - decisions.stake_krw
    selected = decisions.loc[decisions.selected].copy()
    require(selected.groupby(["pool", "model", "scope", "policy_id", "race_id"]).size().le(1).all(),
            "more than one ticket selected for a race-policy")
    write_csv(decisions, "policy_decisions.csv")
    write_csv(selected, "selected_rows.csv")

    rank_cal, rank_distribution = rank_diagnostics(candidate_export, decisions, scopes)
    write_csv(rank_cal, "probability_rank_calibration.csv")
    write_csv(rank_distribution, "selection_rank_distribution.csv")

    draws, schedule_dates, date_index = load_bootstrap()
    weights = schedule_weights(draws)
    summaries, bootstrap, paired = summarize(decisions, weights, date_index)
    write_csv(summaries, "strategy_summary.csv")
    write_csv(bootstrap, "strategy_bootstrap_ci.csv")
    write_csv(paired, "tla_paired_differences.csv")
    write_csv(pd.DataFrame(mass_audit_rows), "probability_mass_audit.csv")

    # Candidate export is written after official labels were joined; decisions are separately pinned pre-outcome.
    source_hashes = {
        "registry": sha256_file(REGISTRY), "hy_model": sha256_file(HY_MODEL),
        "hy_distribution_function": sha256_file(HY_FUNCTION),
        "hy_saved_predictions": sha256_file(LEGACY / "horse_predictions.parquet"),
        "hy_frozen_scores": sha256_file(LEGACY / "frozen_scores.parquet"),
        "native_races": sha256_file(DATA / "races.parquet"), "native_entries": sha256_file(DATA / "entries.parquet"),
        "prior_cohort": sha256_file(PREVIOUS / "cohort.csv"),
        "source_preflight": sha256_file(SOURCE_PREFLIGHT), "candidate_quotes": sha256_file(SOURCE_QUOTES),
        "official_runner_results": sha256_file(OFFICIAL), "research_tla_probabilities": sha256_file(TLA_RESEARCH),
        "research_tla_receipt": sha256_file(TLA_RECEIPT),
        "bootstrap_schedule": sha256_file(BOOTSTRAP), "bootstrap_receipt": sha256_file(BOOTSTRAP_RECEIPT),
        "frozen_plan": sha256_file(STUDY / "PLAN.md"), "analysis_code": sha256_file(Path(__file__)),
    }
    save_json(STUDY / "SOURCE_MANIFEST.json", {
        "status": "PASS", "source_sha256": source_hashes, "registry_resolver": resolved_model,
        "source_coverage": source,
        "fixed_scopes": {"per_pool_primary": {pool: (222 if pool == "TRI" else 467) for pool in POOLS},
                         "universal_222": {pool: 222 for pool in POOLS}},
        "research_support": {"TLA": "F1_STYLE6 native exact unordered Top3 set_probability",
                             "other_pools": "no retained genuine native matching research event probabilities"},
        "pre_outcome_policy_decision_sha256": preoutcome_sha,
        "pre_outcome_choices_created_before_label_join": True,
        "network": False, "training_fits": 0, "calibration_fits": 0,
        "old_study_or_operating_artifact_modified": False,
    })
    summary_records = summaries.to_dict(orient="records")
    report = {
        "status": "PASS", "interpretation": "retrospective final-price oracle on repeated 2026 development dates",
        "cohort": {"shared_races": 467, "shared_dates": 70, "operating_runners": 4475,
                   "tri_incomplete_price_races": 245, "tri_complete_price_races": 222},
        "pool_definitions": {"WIN": "first-place single", "QNL": "unordered first and second",
                             "EXA": "ordered first then second", "TLA": "unordered official Top3 set",
                             "TRI": "exact ordered first, second, third"},
        "selection_contract": {"policy_count": len(POLICIES), "policies": [
            {"policy_id": p, "label": label} for p, label in POLICIES], "stake_krw": STAKES,
            "max_tickets_per_race_per_policy": 1, "ev": "p * final displayed odds - 1",
            "gross_return": "1000 KRW * final displayed odds on exact event hit; else 0",
            "candidate_tie_break": "numeric event tuple ascending; preserve order for EXA/TRI",
            "max_ev_tie_break": "numeric event tuple ascending; preserve order for EXA/TRI"},
        "probability_source": {"operating": "full native HY ordered Top3 joint; all matching order mass summed",
                               "research_tla": "independently audited F1_STYLE6 native unordered Top3 set probability",
                               "research_other_pools": "unavailable; no proxy probability used"},
        "source_audit": json.loads(SOURCE_PREFLIGHT.read_text(encoding="utf-8")),
        "strategy_summary": summary_records,
        "tla_paired_differences": paired.to_dict(orient="records"),
        "pre_outcome_choices_sha256": preoutcome_sha,
        "bootstrap": {"draws": 2000, "dates_per_draw": 269, "fixed_original_inventory": schedule_dates,
                      "same_schedule_for_every_market_and_policy": True,
                      "dates_outside_each_eligible_cohort_are_zero_selection": True},
        "limits": [
            "Final prices are post-race values; EV/ROI are retrospective oracle scores, not pre-purchase evidence.",
            "The shared cohort has been used repeatedly and is not independent future validation.",
            "TRI excludes 245 races with at least one 9999.9 invalid-odds sentinel; no quote is imputed.",
            "Other-pool research probabilities are unavailable except TLA; no rank or probability proxy is substituted.",
            "Native model comparisons do not establish stable profit or a best post-race threshold.",
        ],
        "output_rows": {"candidate_rows": int(len(candidate_export)), "candidate_quotes": int(len(quotes)),
                        "policy_decisions": int(len(decisions)), "selected_rows": int(len(selected)),
                        "strategy_summary": int(len(summaries)), "paired_tla_rules": int(len(paired)),
                        "probability_mass_audit": int(len(mass_audit_rows))},
        "source_manifest": "SOURCE_MANIFEST.json",
    }
    save_json(STUDY / "REPORT.json", report)
    save_readme(summaries, paired, report)
    build_final_manifest()
    print(json.dumps({"status": "PASS", "source_rows": source["expected_candidate_rows_467"],
                      "candidate_probability_rows": len(candidate_export), "summary_rows": len(summaries),
                      "paired_tla_rules": len(paired), "report_sha256": sha256_file(STUDY / "REPORT.json")},
                     ensure_ascii=False, indent=2))


def policy_candidates(group: pd.DataFrame) -> dict[str, pd.DataFrame]:
    sort_columns = ["race_id", "p", "horse_no_1", "horse_no_2", "horse_no_3"]
    ascending = [True, False, True, True, True]
    ranked = group.sort_values(sort_columns, ascending=ascending, kind="mergesort", na_position="last").copy()
    ranked["probability_rank"] = ranked.groupby("race_id", sort=False).cumcount() + 1
    by_race = {rid: part for rid, part in ranked.groupby("race_id", sort=False)}
    selected_by_policy: dict[str, list[pd.Series]] = {policy: [] for policy, _ in POLICIES}
    for race_id, part in by_race.items():
        candidates = {
            "p_rank_1": part.loc[part.probability_rank.eq(1)],
            "p_rank_2": part.loc[part.probability_rank.eq(2)],
            "p_rank_3": part.loc[part.probability_rank.eq(3)],
            "p_rank_4": part.loc[part.probability_rank.eq(4)],
            "p_rank_5": part.loc[part.probability_rank.eq(5)],
        }
        rank1 = candidates["p_rank_1"]
        require(len(rank1) == 1, f"probability rank 1 missing: {race_id}")
        if float(rank1.iloc[0].ev) > 0:
            candidates["p_rank_1_ev_positive"] = rank1
        else:
            candidates["p_rank_1_ev_positive"] = part.iloc[0:0]
        for policy, rank_filter, threshold in [
            ("all_max_ev_positive", None, 0.0),
            ("top3_max_ev_positive", 3, 0.0),
            ("top5_max_ev_positive", 5, 0.0),
            ("top3_max_ev_gt_020", 3, 0.20),
        ]:
            pool = part if rank_filter is None else part.loc[part.probability_rank.le(rank_filter)]
            ranked_ev = pool.sort_values(["ev", "horse_no_1", "horse_no_2", "horse_no_3"],
                                         ascending=[False, True, True, True], kind="mergesort")
            winner = ranked_ev.iloc[0:1]
            candidates[policy] = winner if float(winner.iloc[0].ev) > threshold else part.iloc[0:0]
        for policy, _ in POLICIES:
            chosen = candidates.get(policy)
            if chosen is not None and len(chosen):
                selected_by_policy[policy].append(chosen.iloc[0])
    return {policy: pd.DataFrame(rows, columns=ranked.columns) if rows else ranked.iloc[0:0].copy()
            for policy, rows in selected_by_policy.items()}


def expected_event_count(pool: str, field_n: int) -> int:
    n = int(field_n)
    if pool == "WIN":
        return n
    if pool == "QNL":
        return n * (n - 1) // 2
    if pool == "EXA":
        return n * (n - 1)
    if pool == "TLA":
        return n * (n - 1) * (n - 2) // 6
    if pool == "TRI":
        return n * (n - 1) * (n - 2)
    raise RuntimeError(f"unknown pool: {pool}")


def build_decisions(candidates: pd.DataFrame, scopes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    decisions = []
    selected_frames = []
    for (pool, model), base in candidates.groupby(["pool", "model"], sort=True):
        pool_scopes = scopes.loc[scopes.pool.eq(pool)]
        for scope, scope_rows in pool_scopes.groupby("scope", sort=True):
            eligible_ids = set(scope_rows.race_id.astype(str))
            eligible = base.loc[base.race_id.astype(str).isin(eligible_ids)
                                & base.quote_status.eq("valid")].copy()
            require(eligible.race_id.nunique() == len(eligible_ids), f"missing eligible candidate races {pool} {scope}")
            actual_counts = eligible.groupby("race_id").size().sort_index()
            race_fields = eligible.groupby("race_id").field_n.nunique()
            require(race_fields.eq(1).all(), f"field size changes within candidate event rows {pool} {scope}")
            expected_counts = eligible.groupby("race_id").field_n.first().map(
                lambda n: expected_event_count(pool, int(n))
            ).sort_index()
            require(actual_counts.index.equals(expected_counts.index)
                    and np.array_equal(actual_counts.to_numpy(), expected_counts.to_numpy()),
                    f"per-race candidate cardinality does not equal complete event space {pool} {scope}")
            require(eligible.p.notna().all() and eligible.quote.notna().all()
                    and np.isfinite(eligible.p.to_numpy(float)).all()
                    and np.isfinite(eligible.quote.to_numpy(float)).all(),
                    f"invalid p or quote in eligible scope {pool} {scope}")
            selected = policy_candidates(eligible)
            for policy, label in POLICIES:
                chosen = selected[policy].copy()
                chosen["policy_id"] = policy
                chosen["policy_label"] = label
                chosen["scope"] = scope
                chosen["selected"] = True
                selected_frames.append(chosen)
                chosen_cols = ["race_id", "race_date", "selection_key", "horse_no_1", "horse_no_2",
                               "horse_no_3", "probability_rank", "p", "quote", "ev"]
                chosen = chosen[chosen_cols].rename(columns={
                    "selection_key": "selected_selection_key", "horse_no_1": "selected_horse_no_1",
                    "horse_no_2": "selected_horse_no_2", "horse_no_3": "selected_horse_no_3",
                    "probability_rank": "selected_probability_rank", "p": "selected_p",
                    "quote": "selected_quote", "ev": "selected_ev",
                })
                dec = scope_rows[["race_id"]].copy()
                dec["race_date"] = dec.race_id.map(base.set_index("race_id").race_date.to_dict())
                dec = dec.merge(chosen, on=["race_id", "race_date"], how="left", validate="one_to_one")
                dec["pool"] = pool
                dec["model"] = model
                dec["scope"] = scope
                dec["policy_id"] = policy
                dec["policy_label"] = label
                dec["selected"] = dec.selected_selection_key.notna()
                decisions.append(dec)
    decision_rows = pd.concat(decisions, ignore_index=True)
    selected_rows = pd.concat(selected_frames, ignore_index=True) if selected_frames else pd.DataFrame()
    require(decision_rows.groupby(["pool", "model", "scope", "policy_id"]).race_id.nunique().sum()
            == len(decision_rows), "policy decision denominators have duplicate race-policy keys")
    require(decision_rows.selected.sum() == len(selected_rows), "selected decisions do not reconcile to ticket rows")
    return selected_rows, decision_rows


def rank_diagnostics(candidates: pd.DataFrame, decisions: pd.DataFrame, scopes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    calibration_rows = []
    for (pool, model), base in candidates.groupby(["pool", "model"], sort=True):
        for scope, scope_rows in scopes.loc[scopes.pool.eq(pool)].groupby("scope", sort=True):
            ids = set(scope_rows.race_id.astype(str))
            cand = base.loc[base.race_id.astype(str).isin(ids) & base.quote_status.eq("valid")].copy()
            cand = cand.sort_values(["race_id", "p", "horse_no_1", "horse_no_2", "horse_no_3"],
                                    ascending=[True, False, True, True, True], kind="mergesort")
            cand["probability_rank"] = cand.groupby("race_id", sort=False).cumcount() + 1
            # Outcomes are joined only after fixed policy decisions were frozen.
            hit_map = decisions.loc[(decisions.pool.eq(pool) & decisions.model.eq(model) & decisions.scope.eq(scope)),
                                    ["race_id", "policy_id", "selected_selection_key", "hit"]]
            # Candidate labels arrive through the post-outcome decision table for selected rows only; full labels are attached below.
            # The caller supplies `hit` on the candidate frame after selections are frozen.
            require("hit" in cand.columns, "candidate official outcome labels are not attached")
            for rank in range(1, 6):
                group = cand.loc[cand.probability_rank.eq(rank)]
                calibration_rows.append({"pool": pool, "model": model, "scope": scope,
                                         "probability_rank": rank, "candidate_events": int(len(group)),
                                         "mean_p": float(group.p.mean()) if len(group) else None,
                                         "hits": int(group.hit.sum()),
                                         "observed_hit_rate": float(group.hit.mean()) if len(group) else None,
                                         "brier_score": float(((group.p - group.hit.astype(float)) ** 2).mean()) if len(group) else None})
    distribution_rows = []
    for row in decisions.loc[decisions.selected].itertuples(index=False):
        distribution_rows.append({"pool": row.pool, "model": row.model, "scope": row.scope,
                                  "policy_id": row.policy_id, "selected_probability_rank": row.selected_probability_rank,
                                  "selected": 1})
    ranks = pd.DataFrame(distribution_rows)
    if len(ranks):
        counts = ranks.groupby(["pool", "model", "scope", "policy_id", "selected_probability_rank"],
                              as_index=False).selected.sum()
        totals = ranks.groupby(["pool", "model", "scope", "policy_id"], as_index=False).selected.sum()
        dist = counts.merge(totals, on=["pool", "model", "scope", "policy_id"], suffixes=("_rank", "_total"))
        dist["selection_rank_pct"] = 100 * dist.selected_rank / dist.selected_total
    else:
        dist = pd.DataFrame()
    return pd.DataFrame(calibration_rows), dist


def bootstrap_group(group: pd.DataFrame, weights: np.ndarray, date_index: dict[str, int]) -> dict[str, Any]:
    race_dates = group.race_date.astype(str).map(date_index)
    require(race_dates.notna().all(), "eligible race date missing from original 269-date schedule")
    row_weights = weights[:, race_dates.to_numpy(int)]
    selected = group.selected.to_numpy(bool).astype(float)
    hits = (group.hit.fillna(False).to_numpy(bool) & group.selected.to_numpy(bool)).astype(float)
    gross = group.gross_return_krw.to_numpy(float)
    stake = group.stake_krw.to_numpy(float)
    draws_bets = row_weights @ selected
    draws_hits = row_weights @ hits
    draws_gross = row_weights @ gross
    draws_stake = row_weights @ stake
    roi = np.divide(draws_gross - draws_stake, draws_stake,
                    out=np.full(draws_stake.shape, np.nan), where=draws_stake > 0) * 100
    hit_rate = np.divide(draws_hits, draws_bets,
                         out=np.full(draws_bets.shape, np.nan), where=draws_bets > 0) * 100
    return {
        "roi_ci95_low_pct": float(np.nanpercentile(roi, 2.5)),
        "roi_ci95_high_pct": float(np.nanpercentile(roi, 97.5)),
        "roi_valid_draws": int(np.isfinite(roi).sum()),
        "roi_zero_stake_draws": int((draws_stake == 0).sum()),
        "hit_rate_ci95_low_pct": float(np.nanpercentile(hit_rate, 2.5)),
        "hit_rate_ci95_high_pct": float(np.nanpercentile(hit_rate, 97.5)),
        "hit_rate_valid_draws": int(np.isfinite(hit_rate).sum()),
        "hit_rate_zero_bet_draws": int((draws_bets == 0).sum()),
        "roi_draws": roi, "hit_rate_draws": hit_rate,
    }


def summarize(decisions: pd.DataFrame, weights: np.ndarray, date_index: dict[str, int]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    copy = decisions.copy()
    copy["stake_krw"] = copy.selected.astype(float) * STAKES
    copy["gross_return_krw"] = np.where(copy.selected & copy.hit, copy.selected_quote.astype(float) * STAKES, 0.0)
    copy["net_profit_krw"] = copy.gross_return_krw - copy.stake_krw
    summary_rows, bootstrap_rows, paired_rows = [], [], []
    roi_vectors: dict[tuple[str, str, str, str], np.ndarray] = {}
    roi_points: dict[tuple[str, str, str, str], float | None] = {}
    for keys, group in copy.groupby(["pool", "model", "scope", "policy_id"], sort=True):
        pool, model, scope, policy = keys
        chosen = group.loc[group.selected].copy()
        eligible_races = int(group.race_id.nunique())
        bets = int(chosen.race_id.nunique())
        hits = int(chosen.hit.sum())
        stake = float(group.stake_krw.sum())
        gross = float(group.gross_return_krw.sum())
        net = float(group.net_profit_krw.sum())
        roi = (100 * net / stake) if stake > 0 else None
        roi_points[keys] = roi
        bs = bootstrap_group(group, weights, date_index)
        roi_vectors[keys] = bs.pop("roi_draws")
        bs.pop("hit_rate_draws")
        bootstrap_rows.append({"pool": pool, "model": model, "scope": scope, "policy_id": policy, **bs})

        win_rows = chosen.loc[chosen.hit].sort_values(
            ["gross_return_krw", "race_date", "race_id", "selected_selection_key"],
            ascending=[False, True, True, True], kind="mergesort",
        )
        sensitivity = {}
        for count in (1, 3, 5):
            removed = win_rows.head(count)
            rem_gross = float(removed.gross_return_krw.sum())
            rem_stake = float(removed.stake_krw.sum())
            remaining_stake = stake - rem_stake
            sensitivity[f"top_{count}_winning_tickets_removed"] = int(len(removed))
            sensitivity[f"top_{count}_winning_gross_removed_krw"] = rem_gross
            sensitivity[f"top_{count}_winning_stake_removed_krw"] = rem_stake
            sensitivity[f"roi_without_top_{count}_winning_tickets_pct"] = (
                100 * ((gross - rem_gross) - (stake - rem_stake)) / remaining_stake
                if remaining_stake > 0 else None
            )
        summary_rows.append({
            "pool": pool, "pool_korean": POOL_LABELS[pool], "model": model,
            "scope": scope, "policy_id": policy,
            "policy": next(label for candidate, label in POLICIES if candidate == policy),
            "eligible_races": eligible_races, "selected_races": bets,
            "no_bet_races": eligible_races - bets, "coverage_pct": 100 * bets / eligible_races,
            "hits": hits, "hit_rate_pct": 100 * hits / bets if bets else None,
            "mean_p_selected_pct": 100 * float(chosen.selected_p.mean()) if bets else None,
            "mean_p_actual_hits_pct": 100 * float(chosen.loc[chosen.hit, "selected_p"].mean()) if hits else None,
            "mean_final_quote": float(chosen.selected_quote.mean()) if bets else None,
            "mean_posthoc_ev_pct": 100 * float(chosen.selected_ev.mean()) if bets else None,
            "stake_krw": stake, "gross_return_krw": gross, "net_profit_krw": net,
            "roi_pct": roi, **sensitivity,
        })

    # Paired ROI differences are restricted to the same TLA race-date draw for each model/scope/policy.
    for scope in ["per_pool_primary", "universal_222"]:
        for policy, _ in POLICIES:
            key_op = ("TLA", "operating_hy_r_form", scope, policy)
            key_rs = ("TLA", "research_f1_style6_native", scope, policy)
            if key_op not in roi_vectors or key_rs not in roi_vectors:
                continue
            delta = roi_vectors[key_op] - roi_vectors[key_rs]
            point_delta = (roi_points[key_op] - roi_points[key_rs]
                           if roi_points[key_op] is not None and roi_points[key_rs] is not None else None)
            paired_rows.append({"pool": "TLA", "scope": scope, "policy_id": policy,
                                "model_a": "operating_hy_r_form", "model_b": "research_f1_style6_native",
                                "roi_delta_a_minus_b_pp": point_delta,
                                "roi_delta_bootstrap_mean_pp": float(np.nanmean(delta)) if np.isfinite(delta).any() else None,
                                "roi_delta_ci95_low_pp": float(np.nanpercentile(delta, 2.5)),
                                "roi_delta_ci95_high_pp": float(np.nanpercentile(delta, 97.5)),
                                "roi_delta_valid_draws": int(np.isfinite(delta).sum()),
                                "roi_delta_zero_stake_draws": int(np.isnan(delta).sum()),
                                "roi_delta_positive_draws": int((delta > 0).sum())})
    return pd.DataFrame(summary_rows), pd.DataFrame(bootstrap_rows), pd.DataFrame(paired_rows)


def save_readme(summaries: pd.DataFrame, paired: pd.DataFrame, report: dict[str, Any]) -> None:
    # User-facing headline is generated only after all fixed-policy outcomes are computed.
    lines = [
        "# 단승·복승·쌍승·삼복승·삼쌍승 운영 모델의 동일 경주 사후 비교",
        "",
        "이 분석은 이전 operating 대 research 비교의 동일한 2026-01-02~09-12 normal common cohort 467경주·70일을 출발점으로 삼았다. WIN/QNL/EXA/TLA는 전체 467경주에 완전한 final-price 후보 집합을 확인했다. TRI는 API301의 invalid 9999.9 배당 sentinel이 하나 이상 포함된 245경주를 제외해 222경주만 complete-price 평가가 가능했다. 모든 다섯 pool을 같은 222경주에서 비교하는 표도 별도로 제공한다.",
        "",
        "HY_R_FORM event p는 저장된 운영 score를 production full ordered Top3 joint distribution에 넣어 계산했다. WIN은 첫째, QNL은 처음 두 말의 무순서 쌍, EXA는 처음 두 말의 정확한 순서쌍, TLA는 unordered Top3 세트, TRI는 정확한 ordered 1-2-3 사건이다. 각 확률은 해당 사건에 속하는 모든 ordered mass의 합이다. native F1_STYLE6 research probability는 root가 독립 검산한 TLA set probability만 비교했다. 나머지 네 시장의 research 확률은 사용하거나 만들어내지 않았다.",
        "",
        "모든 규칙은 결과를 보기 전에 PLAN.md에 고정했다: p rank 1–5, rank1 EV>0, all-candidate max EV>0, top3/top5 max EV>0, top3 max EV>0.20. 각 policy는 경주당 최대 1장·1,000원이며 `EV=p×final odds−1`이다. 배당은 결과 뒤에 보관된 final price이므로 EV/ROI는 사후 oracle 점수이며 사전 매수 가능성이나 미래 성과를 뜻하지 않는다. 2026 공통 기간은 여러 번 확인된 개발 자료이고 독립 OOS가 아니다.",
        "",
        "## 결과",
        "",
        "아래 `strategy_summary.csv`는 120개의 market×model×scope×policy 결과, `tla_paired_differences.csv`는 TLA operating−research 날짜 paired ROI 차이를 담는다. ROI CI는 전체 2,000×269 fixed date schedule을 재사용하고 scope 밖 날짜에는 선택 0건을 둔다. 상위 1·3·5 당첨 환급 ticket 및 stake를 뺀 민감도도 summary에 포함된다. 고정 정책 중 최고 관측 ROI를 최선의 전략으로 선택하지 않는다.",
        "",
        "| Pool / scope | Model | Policy | Bets / eligible | Hits | Net (KRW) | ROI |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for pool in POOLS:
        primary = summaries.loc[(summaries.pool.eq(pool)) & summaries.scope.eq("per_pool_primary")]
        for model in sorted(primary.model.unique()):
            row = primary.loc[primary.model.eq(model) & primary.policy_id.eq("all_max_ev_positive")]
            if row.empty:
                continue
            v = row.iloc[0]
            lines.append(f"| {pool} / primary {int(v.eligible_races)} | {model} | all max EV > 0 | "
                         f"{int(v.selected_races)} / {int(v.eligible_races)} | {int(v.hits)} | "
                         f"{int(v.net_profit_krw):,} | {v.roi_pct:.2f}% |")
    lines.extend(["", "Research-native comparison is available for TLA only. Its full 467-race and universal 222-race paired results are in `tla_paired_differences.csv`; ROI intervals should be interpreted separately for each declared cohort.",
                  "", "## Files", "",
                  "`candidate_quotes.csv` holds every expected API301 candidate quote, raw value, source run and supplying page SHA, including invalid sentinel rows. `candidate_rows.csv` joins native probabilities and final prices for all operating event candidates and native research TLA candidates, then records exact official event hits. `policy_decisions_pre_outcome.csv` pins choices made from p and fixed final prices before outcome labels are joined. `source_exclusions.csv` lists each TRI-incomplete race and sentinel count. See `SOURCE_PREFLIGHT.json`, `SOURCE_MANIFEST.json`, `probability_mass_audit.csv`, `probability_rank_calibration.csv`, `selection_rank_distribution.csv`, `strategy_bootstrap_ci.csv`, and `FINAL_MANIFEST.json` for audits and details.",
                  "", "Reproduce source audit with `.venv/bin/python -B jeju/research/20261015_other_pools_postrace_value_v1/source_preflight.py` and analysis with `.venv/bin/python -B jeju/research/20261015_other_pools_postrace_value_v1/analysis.py`.", ""])
    (STUDY / "README.md").write_text("\n".join(lines), encoding="utf-8")


def build_final_manifest() -> None:
    artifacts = {}
    for path in sorted(STUDY.iterdir()):
        if path.is_file() and path.name != "FINAL_MANIFEST.json":
            artifacts[path.name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    save_json(STUDY / "FINAL_MANIFEST.json", {
        "status": "PASS", "files": artifacts, "files_count": len(artifacts),
        "report_sha256": sha256_file(STUDY / "REPORT.json"),
        "root_receipt_attached_after_independent_review": False,
    })


if __name__ == "__main__":
    main()

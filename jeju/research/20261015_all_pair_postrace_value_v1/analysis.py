#!/usr/bin/env python3
"""Read-only all-pair QPL post-race value analysis for frozen Jeju predictions."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261015_all_pair_postrace_value_v1"
BASELINE = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
RIDING = ROOT / "jeju/research/20261015_pair_riding_conditions_v1/outputs/evaluation_pair_predictions.parquet"
HELPER_PATH = ROOT / "jeju/research/20261013_pair_payout_audit_v1/analyze.py"
DB_FILE = ROOT / "data/horse_racing.sqlite3"
SCHEDULE = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
SCHEDULE_RECEIPT = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
ROOT_SOURCE_REVIEW = STUDY / "ROOT_RAW_SOURCE_REVIEW.json"
ROOT_QUOTE_REFERENCE = STUDY / "ROOT_QPL_QUOTE_REFERENCE.csv"
ROOT_STRATEGY_REFERENCE = STUDY / "ROOT_STRATEGY_REFERENCE.csv"
ROOT_SELECTION_REFERENCE = STUDY / "ROOT_SELECTION_REFERENCE.csv"
PLAN = STUDY / "PLAN.md"

EXPECTED_INPUTS = {
    BASELINE: "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6",
    RIDING: "c50f7cdd762cc4ed36e50b97bd4d6d979be408c7477f0c747c917e120cde9ced",
    HELPER_PATH: "0481c19a7e01f530d70a50bbe546e3f5a3d712615903b6b4f146d77099638cec",
    SCHEDULE: "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
    SCHEDULE_RECEIPT: "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e",
    ROOT_SOURCE_REVIEW: "e6437455a06d2eb1f85cc80014c2c9c5ed4ce7a2d4422d4a29ade55d7877f182",
    ROOT_QUOTE_REFERENCE: "1e5a158910f856aba29461767a8241e8305ac8c13298db5e0c22ceee5c63371f",
    ROOT_STRATEGY_REFERENCE: "14ee1270fcbc59040763767038701009e2738a673ecf753ce852201ffcfb0aea",
    ROOT_SELECTION_REFERENCE: "19e89c832403d29526d101ea705114699913a73fdfc746a17ae44bb925b5a6ec",
}
STAKE_KRW = 1_000
EXPECTED_BY_YEAR = {2025: 654, 2026: 488}
PERIODS = ("all", "2025", "2026_partial")
STRATEGIES = [
    ("rank_1", "probability rank 1", "rank", 1, None, None),
    ("rank_2", "probability rank 2", "rank", 2, None, None),
    ("rank_3", "probability rank 3", "rank", 3, None, None),
    ("rank_4", "probability rank 4", "rank", 4, None, None),
    ("rank_5", "probability rank 5", "rank", 5, None, None),
    ("rank_1_ev_gt_0", "rank 1, score > 0", "rank_ev", 1, None, 0.0),
    ("all_max_ev_gt_0", "all pairs, max score > 0", "max_ev", None, None, 0.0),
    ("top3_max_ev_gt_0", "ranks 1–3, max score > 0", "max_ev", None, 3, 0.0),
    ("top5_max_ev_gt_0", "ranks 1–5, max score > 0", "max_ev", None, 5, 0.0),
    ("p_ge_020_max_ev_gt_0", "p >= 0.20, max score > 0", "max_ev_p", None, 0.20, 0.0),
    ("p_ge_030_max_ev_gt_0", "p >= 0.30, max score > 0", "max_ev_p", None, 0.30, 0.0),
    ("top3_max_ev_gt_020", "ranks 1–3, max score > 0.20", "max_ev", None, 3, 0.20),
    ("p_ge_020_max_ev_gt_020", "p >= 0.20, max score > 0.20", "max_ev_p", None, 0.20, 0.20),
]
MODEL_SOURCES = {
    "pair_id_baseline": {
        "path": BASELINE,
        "column": "jockey_id_candidate_calibrated_probability",
        "role": "primary",
    },
    "riding_conditions_candidate": {
        "path": RIDING,
        "column": "riding_conditions_candidate_calibrated_probability",
        "role": "supplementary unadopted candidate",
    },
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def pair_key(a: Any, b: Any) -> str:
    left, right = sorted((int(a), int(b)))
    require(left != right, "pair repeats a horse number")
    return f"{left}-{right}"


def race_key(race_id: Any) -> tuple[str, int, int]:
    date, meet, number = str(race_id).rsplit("_", 2)
    return date, int(meet), int(number)


def load_helper():
    sys.path.insert(0, str(ROOT / "src"))
    spec = importlib.util.spec_from_file_location("readonly_all_pair_api301_helper", HELPER_PATH)
    require(spec is not None and spec.loader is not None, "read-only API301 helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_predictions() -> tuple[pd.DataFrame, dict[str, dict]]:
    frames: dict[str, pd.DataFrame] = {}
    input_hashes = {}
    for model, source in MODEL_SOURCES.items():
        path = source["path"]
        actual_sha = sha256_file(path)
        require(actual_sha == EXPECTED_INPUTS[path], f"frozen prediction SHA changed: {model}")
        input_hashes[str(path.relative_to(ROOT))] = actual_sha
        frame = pd.read_parquet(
            path,
            columns=["race_id", "race_date", "evaluation_year", "horse_i", "horse_j", "y_pair", source["column"]],
        )
        frame = frame.loc[frame["evaluation_year"].isin((2025, 2026))].copy()
        frame["race_id"] = frame["race_id"].astype(str)
        frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        require(frame["race_date"].notna().all(), f"invalid prediction date: {model}")
        frame["year"] = pd.to_numeric(frame["evaluation_year"], errors="raise").astype(int)
        frame["pair"] = [pair_key(a, b) for a, b in zip(frame["horse_i"], frame["horse_j"])]
        frame["p"] = pd.to_numeric(frame[source["column"]], errors="raise").astype(float)
        frame["hit"] = pd.to_numeric(frame["y_pair"], errors="raise").astype(int)
        require(not frame.duplicated(["race_id", "pair"]).any(), f"duplicate prediction pair: {model}")
        require(np.isfinite(frame["p"]).all() and frame["p"].between(0, 1).all(), f"invalid saved probabilities: {model}")
        require(frame["hit"].isin((0, 1)).all(), f"invalid pair labels: {model}")
        frames[model] = frame[["race_id", "race_date", "year", "horse_i", "horse_j", "pair", "p", "hit"]].copy()

    primary = frames["pair_id_baseline"]
    secondary = frames["riding_conditions_candidate"]
    primary_keys = set(zip(primary["race_id"], primary["pair"]))
    secondary_keys = set(zip(secondary["race_id"], secondary["pair"]))
    require(primary_keys == secondary_keys, "baseline and riding candidate pair rosters differ")
    left = primary.set_index(["race_id", "pair"]).sort_index()
    right = secondary.set_index(["race_id", "pair"]).sort_index()
    require(left["hit"].equals(right["hit"]), "pair outcome labels differ between frozen files")
    require(left["year"].equals(right["year"]), "year attribution differs between frozen files")
    counts = primary.groupby("year")["race_id"].nunique().to_dict()
    require(counts == EXPECTED_BY_YEAR, f"fixed price cohort changed: {counts}")
    require(primary["race_id"].nunique() == 1_142 and len(primary) == 48_539,
            "fixed pair/race cohort changed")
    return primary, frames


def classify_quote(value: float | None) -> str:
    if value is None:
        return "missing"
    if not math.isfinite(float(value)):
        return "nonfinite"
    if float(value) == 9999.9:
        return "sentinel_9999_9"
    if float(value) <= 0:
        return "nonpositive"
    return "valid"


def source_audit(predictions: pd.DataFrame, ranked_frames: dict[str, pd.DataFrame], helper) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    targets = {race_key(value) for value in predictions["race_id"].unique()}
    require(all(meet == helper.MEET for _, meet, _ in targets), "non-Jeju race in price cohort")
    results = helper.read_results(targets)
    require(set(results) == targets, "official results do not cover all fixed races")

    official_by_race: dict[str, dict] = {}
    wanted: dict[tuple[str, int, int], list[tuple[str, str]]] = defaultdict(list)
    expected_pairs_by_race: dict[str, set[str]] = {}
    race_result_census = Counter()
    for key, result in results.items():
        race_id = f"{key[0]}_{key[1]}_{key[2]}"
        podium, _, _, qnl_plus = helper.result_keys(result)
        qpl_winners = [x.removeprefix("QPL:") for x in qnl_plus if x.startswith("QPL:")]
        require(qpl_winners, f"official Top3 does not yield a QPL key: {race_id}")
        wanted[key].extend(("QPL", item) for item in qpl_winners)
        starters = sorted(r["horse_number"] for r in result["runners"] if not r["scratched"])
        placed = [r for r in result["runners"] if not r["scratched"] and not r["disqualified"]
                  and r["finish_position"] is not None and 1 <= int(r["finish_position"]) <= 3]
        placed_ranks = [int(r["finish_position"]) for r in placed]
        race_result_census["races_with_exactly_three_top3_runners"] += int(len(placed) == 3)
        race_result_census["races_with_nonstandard_top3_runner_count"] += int(len(placed) != 3)
        race_result_census["races_with_top3_dead_heat"] += int(len(placed_ranks) != len(set(placed_ranks)))
        race_result_census["races_with_scratched_runner"] += int(any(r["scratched"] for r in result["runners"]))
        race_result_census["scratched_runner_rows"] += sum(int(r["scratched"]) for r in result["runners"])
        race_result_census["disqualified_runner_rows"] += sum(int(r["disqualified"]) for r in result["runners"])
        expected_pairs = {pair_key(a, b) for a, b in itertools.combinations(starters, 2)}
        expected_pairs_by_race[race_id] = expected_pairs
        official_by_race[race_id] = {
            "podium": set(int(x) for x in podium),
            "starters": set(int(x) for x in starters),
            "runner_by_number": {int(r["horse_number"]): r for r in result["runners"]},
            "race_db_id": int(result["race_db_id"]),
        }

    chosen, archive_summary = helper.archive_rows(targets, wanted)
    require(len(chosen) == len({(d, meet) for d, meet, _ in targets}), "latest complete API301 day run missing")
    pred_by_race = {race_id: group for race_id, group in predictions.groupby("race_id", sort=False)}
    quote_map: dict[tuple[str, str], dict] = {}
    page_rows: dict[tuple[str, str, int], dict] = {}
    page_hashes: set[str] = set()
    source_rows = 0
    source_key_collision_count = 0
    source_key_order_mismatch_count = 0
    field_set_mismatch_races: list[str] = []
    prediction_set_mismatch_races: list[str] = []
    label_mismatches = 0
    scratched_or_missing_pairs = 0
    quote_status = Counter()
    race_status = Counter()
    source_semantic_rows = []
    page_run_summary = []

    for (date, meet), run in sorted(chosen.items()):
        require(meet == helper.MEET, "unexpected meet in API301 source")
        require(len(run["hashes"]) == len(run["paths"]) == int(run["page_count"]),
                f"API301 page metadata does not align: {date}")
        page_run_summary.append({
            "race_date": date,
            "source_run_id": str(run["run_id"]),
            "complete_runs_for_date": int(run["complete_run_count"]),
            "latest_complete_run_retrieved_at_ms": int(run["retrieved_at_ms"]),
            "page_count": int(run["page_count"]),
            "page_sha256s": list(run["hashes"]),
        })
        for page_number, (relative_path, page_hash) in enumerate(zip(run["paths"], run["hashes"]), start=1):
            page_hashes.add(str(page_hash))
            page_rows[(date, str(run["run_id"]), page_number)] = {
                "race_date": date,
                "meet_code": meet,
                "source_run_id": str(run["run_id"]),
                "page_number": page_number,
                "source_path": str(relative_path),
                "page_sha256": str(page_hash),
            }

        for key in sorted(k for k in targets if k[:2] == (date, meet)):
            race_id = f"{key[0]}_{key[1]}_{key[2]}"
            source_by_pair: dict[str, tuple[float | None, str, str]] = {}
            raw_source_pair_keys = set()
            for (race_number, pool, selection), value in run["values"].items():
                if race_number != key[2] or pool != "QPL":
                    continue
                parts = [int(part) for part in str(selection).split("-") if part]
                require(len(parts) == 2 and parts[0] != parts[1], f"invalid full-field QPL key: {race_id}")
                normalized = pair_key(parts[0], parts[1])
                if str(selection) != normalized:
                    source_key_order_mismatch_count += 1
                if normalized in source_by_pair:
                    source_key_collision_count += 1
                page_hash = run["page_for_key"].get((key[2], "QPL", selection))
                require(page_hash is not None, f"QPL page hash missing: {race_id}")
                source_by_pair[normalized] = (None if value is None else float(value), str(page_hash), str(selection))
                raw_source_pair_keys.add(normalized)
                source_rows += 1

            expected_pairs = expected_pairs_by_race[race_id]
            prediction_pairs = set(pred_by_race[race_id]["pair"])
            if raw_source_pair_keys != expected_pairs:
                field_set_mismatch_races.append(race_id)
            if prediction_pairs != expected_pairs:
                prediction_set_mismatch_races.append(race_id)

            predicted_group = pred_by_race[race_id].sort_values(["pair"], kind="mergesort")
            for row in predicted_group.itertuples(index=False):
                official = official_by_race[race_id]
                parts = [int(x) for x in row.pair.split("-")]
                runners = [official["runner_by_number"].get(x) for x in parts]
                if len(runners) != 2 or any(x is None or x["scratched"] for x in runners):
                    scratched_or_missing_pairs += 1
                official_hit = int(set(parts).issubset(official["podium"]))
                if official_hit != int(row.hit):
                    label_mismatches += 1
                record = source_by_pair.get(row.pair)
                if record is None:
                    quote = None
                    page_hash = ""
                    source_key = ""
                else:
                    quote, page_hash, source_key = record
                status = classify_quote(quote)
                quote_status[status] += 1
                quote_map[(race_id, row.pair)] = {
                    "final_quote": quote,
                    "quote_status": status,
                    "source_page_sha256": page_hash,
                    "source_key": source_key,
                }
                source_semantic_rows.append({
                    "race_id": race_id,
                    "pair": row.pair,
                    "hit": int(row.hit),
                    "official_hit": official_hit,
                    "quote": quote,
                    "quote_status": status,
                    "page_sha256": page_hash,
                    "race_db_id": official["race_db_id"],
                })
            race_valid = all(classify_quote(source_by_pair.get(pair, (None, "", ""))[0]) == "valid"
                             for pair in expected_pairs)
            race_status["full_field_key_exact"] += int(raw_source_pair_keys == expected_pairs)
            race_status["prediction_pair_set_exact"] += int(prediction_pairs == expected_pairs)
            race_status["all_quotes_valid"] += int(race_valid)

    source_pages = pd.DataFrame(page_rows.values()).sort_values(
        ["race_date", "source_run_id", "page_number"], kind="mergesort"
    ).reset_index(drop=True)
    source_pages = source_pages.drop_duplicates(["race_date", "source_run_id", "page_number"])
    page_usage_hashes = set(source_pages["page_sha256"])
    require(page_hashes == page_usage_hashes, "source page index/hash inventory mismatch")

    # Independently compare all keys and prices with the supervisor's direct raw-JSON audit.
    direct_review = json.loads(ROOT_SOURCE_REVIEW.read_text(encoding="utf-8"))
    require(direct_review.get("status") == "PASS" and direct_review.get("qpl_target_pairs_complete") is True,
            "independent direct raw-JSON source review did not pass")
    direct = pd.read_csv(ROOT_QUOTE_REFERENCE, dtype=str, keep_default_na=False)
    direct["pair"] = [pair_key(a, b) for a, b in zip(direct["horse_i"], direct["horse_j"])]
    require(len(direct) == 48_539 and not direct.duplicated(["race_id", "pair"]).any(),
            "independent raw-JSON QPL reference roster changed")
    helper_prices = {(row["race_id"], row["pair"]): row["quote"] for row in source_semantic_rows}
    helper_hashes = {(row["race_id"], row["pair"]): row["page_sha256"] for row in source_semantic_rows}
    direct_prices = {}
    direct_hashes = {}
    for row in direct.itertuples(index=False):
        direct_prices[(str(row.race_id), str(row.pair))] = Decimal(str(row.raw_quote))
        direct_hashes[(str(row.race_id), str(row.pair))] = str(row.source_sha256)
    require(set(helper_prices) == set(direct_prices), "helper and direct-JSON source pair keys differ")
    quote_value_matches = sum(
        Decimal(str(helper_prices[key])) == value for key, value in direct_prices.items()
    )
    require(quote_value_matches == 48_539, "helper and direct-JSON final QPL quotes differ")
    same_page_hash_count = sum(helper_hashes[key] == direct_hashes[key] for key in direct_hashes)
    direct_reference = {
        "status": str(direct_review["status"]),
        "method": str(direct_review["method"]),
        "independently_verified_pages": int(direct_review["verified_pages"]),
        "raw_items_read": int(direct_review["raw_items_read"]),
        "qpl_pair_quotes": int(direct_review["all_qpl_pair_quotes"]),
        "candidate_pair_key_matches": int(len(set(helper_prices) & set(direct_prices))),
        "quote_value_matches": int(quote_value_matches),
        "same_source_page_hash_matches": int(same_page_hash_count),
        "source_review_sha256": sha256_file(ROOT_SOURCE_REVIEW),
        "quote_reference_sha256": sha256_file(ROOT_QUOTE_REFERENCE),
    }

    joined_rows = []
    model_by_pair = {}
    for model in MODEL_SOURCES:
        pred = ranked_frames[model]
        model_by_pair[model] = pred.set_index(["race_id", "pair"])
    for row in source_semantic_rows:
        base = {
            "race_id": row["race_id"],
            "race_date": row["race_id"].rsplit("_", 2)[0],
            "year": int(row["race_id"].rsplit("_", 2)[0][:4]),
            "pair": row["pair"],
            "horse_i": int(row["pair"].split("-")[0]),
            "horse_j": int(row["pair"].split("-")[1]),
            "hit": int(row["hit"]),
            "official_hit": int(row["official_hit"]),
            "final_quote": row["quote"],
            "quote_status": row["quote_status"],
            "source_page_sha256": row["page_sha256"],
        }
        for model, pred_index in model_by_pair.items():
            source = pred_index.loc[(row["race_id"], row["pair"])]
            p = float(source["p"])
            base[f"{model}_p"] = p
            base[f"{model}_rank"] = int(source["rank"])
            base[f"{model}_posthoc_score"] = None if row["quote_status"] != "valid" else p * float(row["quote"]) - 1.0
        joined_rows.append(base)

    rows = pd.DataFrame(joined_rows).sort_values(["race_date", "race_id", "pair"], kind="mergesort").reset_index(drop=True)
    expected_pairs = len(predictions)
    require(len(rows) == expected_pairs, "API301 quote rows do not cover fixed candidate universe")
    census = {
        "status": "PASS" if (
            len(field_set_mismatch_races) == 0
            and len(prediction_set_mismatch_races) == 0
            and label_mismatches == 0
            and scratched_or_missing_pairs == 0
            and quote_status == Counter({"valid": expected_pairs})
            and source_key_collision_count == 0
        ) else "REVIEW_REQUIRED",
        "cohort": {
            "races": int(predictions["race_id"].nunique()),
            "race_dates": int(predictions["race_date"].nunique()),
            "pairs": int(expected_pairs),
            "years": {str(y): int(predictions.loc[predictions["year"].eq(y), "race_id"].nunique()) for y in (2025, 2026)},
        },
        "sources": {
            "method": "latest complete locally cached API301 run by race date; helper verifies page SHA against source_documents registry",
            "registry_rows_on_target_dates": int(archive_summary["api301_registry_rows_for_target_days"]),
            "complete_runs_on_target_dates": int(archive_summary["complete_runs"]),
            "duplicate_registry_alias_rows_collapsed": int(archive_summary["duplicate_registry_alias_rows_collapsed"]),
            "latest_complete_date_runs": int(len(chosen)),
            "verified_source_pages": int(len(source_pages)),
            "unique_source_page_hashes": int(len(page_hashes)),
            "source_url_exported": False,
            "request_parameters_exported": False,
            "credentials_exported": False,
        },
        "pair_quote_status": dict(quote_status),
        "independent_direct_raw_json_crosscheck": direct_reference,
        "audit_checks": {
            "expected_nonscratched_full_field_pair_rows": int(sum(len(v) for v in expected_pairs_by_race.values())),
            "source_qpl_pair_rows": int(source_rows),
            "source_key_collisions_after_unordered_normalization": int(source_key_collision_count),
            "source_nonascending_key_count": int(source_key_order_mismatch_count),
            "race_source_full_field_key_exact_count": int(race_status["full_field_key_exact"]),
            "race_prediction_pair_set_exact_count": int(race_status["prediction_pair_set_exact"]),
            "race_all_quotes_valid_count": int(race_status["all_quotes_valid"]),
            "source_or_field_key_mismatch_races": field_set_mismatch_races,
            "prediction_or_field_key_mismatch_races": prediction_set_mismatch_races,
            "prediction_label_vs_official_top3_mismatches": int(label_mismatches),
            "prediction_pairs_with_scratched_or_missing_entry": int(scratched_or_missing_pairs),
            "completed_race_result_census": dict(race_result_census),
        },
        "latest_run_by_date": page_run_summary,
    }
    require(census["status"] == "PASS", "API301 all-pair source census found an unresolved mismatch")
    semantic_digest = stable_sha256(source_semantic_rows)
    return rows, census | {"semantic_quote_result_sha256": semantic_digest}, source_pages


def attach_ranks(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    result = {}
    for model, frame in frames.items():
        frame = frame.sort_values(["race_id", "p", "horse_i", "horse_j"],
                                  ascending=[True, False, True, True], kind="mergesort").copy()
        frame["rank"] = frame.groupby("race_id", sort=False).cumcount() + 1
        require(frame.groupby("race_id")["rank"].max().eq(frame.groupby("race_id").size()).all(),
                f"rank sequence has a gap: {model}")
        result[model] = frame
    return result


def choose_per_race(rows: pd.DataFrame, strategy: tuple, scope: str) -> pd.DataFrame:
    strategy_id, label, kind, rank_arg, bound_arg, threshold = strategy
    picked = []
    for race_id, group in rows.groupby("race_id", sort=True):
        available = group.loc[group["quote_status"].eq("valid")].copy()
        chosen = None
        if kind == "rank":
            match = group.loc[group["rank"].eq(rank_arg)]
            if len(match):
                candidate = match.iloc[0]
                if candidate["quote_status"] == "valid":
                    chosen = candidate
        elif kind == "rank_ev":
            match = available.loc[available["rank"].eq(rank_arg)]
            if len(match) and float(match.iloc[0]["score"]) > float(threshold):
                chosen = match.iloc[0]
        else:
            candidates = available
            if kind == "max_ev" and bound_arg is not None:
                candidates = candidates.loc[candidates["rank"].le(int(bound_arg))]
            elif kind == "max_ev_p":
                candidates = candidates.loc[candidates["p"].ge(float(bound_arg))]
            if not candidates.empty:
                candidates = candidates.sort_values(["score", "horse_i", "horse_j"],
                                                    ascending=[False, True, True], kind="mergesort")
                candidate = candidates.iloc[0]
                if float(candidate["score"]) > float(threshold):
                    chosen = candidate
        record = {
            "race_id": str(race_id),
            "race_date": str(group["race_date"].iloc[0]),
            "year": int(group["year"].iloc[0]),
            "model": str(group["model"].iloc[0]),
            "scope": scope,
            "strategy": strategy_id,
            "strategy_label": label,
            "cohort_race_valid": bool(group["race_full_quote_valid"].iloc[0]),
            "bet": int(chosen is not None),
        }
        if chosen is not None:
            hit = int(chosen["hit"])
            quote = float(chosen["final_quote"])
            gross = Decimal(str(quote)) * Decimal(STAKE_KRW)
            require(gross == gross.to_integral_value(), "gross QPL payout is not an integer KRW amount")
            payout = int(gross) if hit else 0
            record.update({
                "pair": str(chosen["pair"]),
                "horse_i": int(chosen["horse_i"]),
                "horse_j": int(chosen["horse_j"]),
                "chosen_rank": int(chosen["rank"]),
                "p": float(chosen["p"]),
                "final_quote": quote,
                "score": float(chosen["score"]),
                "hit": hit,
                "stake_krw": STAKE_KRW,
                "return_krw": payout,
                "net_krw": payout - STAKE_KRW,
                "source_page_sha256": str(chosen["source_page_sha256"]),
            })
        else:
            record.update({
                "pair": "", "horse_i": None, "horse_j": None, "chosen_rank": None,
                "p": None, "final_quote": None, "score": None, "hit": None,
                "stake_krw": 0, "return_krw": 0, "net_krw": 0, "source_page_sha256": "",
            })
        picked.append(record)
    return pd.DataFrame(picked)


def format_rank_bin(rank: int) -> str:
    if rank <= 5:
        return str(rank)
    if rank <= 10:
        return "6-10"
    return "11+"


def period_rows(rows: pd.DataFrame, period: str) -> pd.DataFrame:
    if period == "2025":
        return rows.loc[rows["year"].eq(2025)]
    if period == "2026_partial":
        return rows.loc[rows["year"].eq(2026)]
    return rows


def summarize(selected: pd.DataFrame, eligible_races: int, period: str) -> dict:
    bets = selected.loc[selected["bet"].eq(1)].copy()
    n = len(bets)
    hits = int(bets["hit"].sum()) if n else 0
    stake = n * STAKE_KRW
    payout = int(bets["return_krw"].sum()) if n else 0
    net = payout - stake
    hit_quotes = bets.loc[bets["hit"].eq(1), "final_quote"]
    row = {
        "period": period,
        "eligible_price_races": int(eligible_races),
        "bets": int(n),
        "coverage_pct": n / eligible_races * 100 if eligible_races else None,
        "hits": hits,
        "hit_rate_pct": hits / n * 100 if n else None,
        "mean_p": float(bets["p"].mean()) if n else None,
        "mean_quote": float(bets["final_quote"].mean()) if n else None,
        "mean_winning_quote": float(hit_quotes.mean()) if len(hit_quotes) else None,
        "mean_model_ev": float(bets["score"].mean()) if n else None,
        "stake_krw": stake,
        "gross_return_krw": payout,
        "net_krw": net,
        "roi_pct": (payout / stake - 1) * 100 if stake else None,
    }
    winners = bets.loc[bets["hit"].eq(1)].sort_values(
        ["return_krw", "race_id"], ascending=[False, True], kind="mergesort"
    )
    for remove_n in (1, 3, 5):
        removed = winners.head(remove_n)
        remain_n = n - len(removed)
        remain_stake = remain_n * STAKE_KRW
        remain_payout = payout - int(removed["return_krw"].sum())
        row[f"roi_without_largest_{remove_n}_hits_pct"] = (
            (remain_payout / remain_stake - 1) * 100 if remain_stake else None
        )
        row[f"removed_largest_{remove_n}_hit_count"] = int(len(removed))
        row[f"removed_largest_{remove_n}_gross_return_krw"] = int(removed["return_krw"].sum())
    return row


def make_selections(pair_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    selections = []
    for model in MODEL_SOURCES:
        source = pair_rows.loc[pair_rows["model"].eq(model)].copy()
        for scope in ("complete_all_pair_quotes", "partial_prices_available"):
            for strategy in STRATEGIES:
                choice = choose_per_race(source, strategy, scope)
                if scope == "complete_all_pair_quotes":
                    choice = choice.loc[choice["cohort_race_valid"]].copy()
                selections.append(choice)
    all_rows = pd.concat(selections, ignore_index=True)
    summary_rows = []
    for (model, scope, strategy), group in all_rows.groupby(["model", "scope", "strategy"], sort=False):
        for period in PERIODS:
            period_group = period_rows(group, period)
            # The complete-price denominator excludes any race with an invalid/missing quote.
            eligible = int(period_group["cohort_race_valid"].sum()) if scope == "complete_all_pair_quotes" else len(period_group)
            metrics = summarize(period_group, eligible, period)
            metrics.update({
                "model": model,
                "model_role": MODEL_SOURCES[model]["role"],
                "price_scope": scope,
                "strategy": strategy,
                "strategy_label": str(period_group["strategy_label"].iloc[0]) if len(period_group) else strategy,
            })
            summary_rows.append(metrics)
    return all_rows, pd.DataFrame(summary_rows)


def load_schedule(all_prediction_dates: list[str]) -> tuple[list[str], np.ndarray, dict]:
    require(sha256_file(SCHEDULE) == EXPECTED_INPUTS[SCHEDULE], "frozen bootstrap schedule SHA changed")
    require(sha256_file(SCHEDULE_RECEIPT) == EXPECTED_INPUTS[SCHEDULE_RECEIPT], "frozen schedule receipt SHA changed")
    receipt = json.loads(SCHEDULE_RECEIPT.read_text(encoding="utf-8"))
    dates = sorted(set(all_prediction_dates))
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(len(dates) == 269 and date_hash == receipt.get("date_inventory_sha256"),
            "prediction race days do not match frozen schedule inventory")
    schedule = np.load(SCHEDULE, allow_pickle=False)
    require(schedule.shape == (2_000, 269) and schedule.dtype == np.int32,
            "frozen bootstrap schedule shape/dtype changed")
    require(((schedule >= 0) & (schedule < len(dates))).all(), "out-of-range frozen schedule index")
    return dates, schedule, receipt


def make_bootstrap(all_selections: pd.DataFrame, summary: pd.DataFrame, dates: list[str], schedule: np.ndarray) -> pd.DataFrame:
    date_to_idx = {d: i for i, d in enumerate(dates)}
    weights = np.stack([np.bincount(draw, minlength=len(dates)).astype(np.int32) for draw in schedule])
    rows = []
    for (model, scope, strategy), group in all_selections.groupby(["model", "scope", "strategy"], sort=False):
        rank1 = all_selections.loc[
            all_selections["model"].eq(model)
            & all_selections["scope"].eq(scope)
            & all_selections["strategy"].eq("rank_1")
        ]
        for period in PERIODS:
            period_group = period_rows(group, period)
            actual = summary.loc[
                summary["model"].eq(model)
                & summary["price_scope"].eq(scope)
                & summary["strategy"].eq(strategy)
                & summary["period"].eq(period)
            ].iloc[0]
            selected = period_group.loc[period_group["bet"].eq(1)].copy()
            selected["_date_index"] = selected["race_date"].map(date_to_idx).astype(int)
            date_n = np.bincount(selected["_date_index"], minlength=len(dates)).astype(np.int64)
            date_hits = np.bincount(selected["_date_index"], weights=selected["hit"], minlength=len(dates))
            date_returns = np.bincount(selected["_date_index"], weights=selected["return_krw"], minlength=len(dates))
            draw_n = weights @ date_n
            draw_hits = weights @ date_hits
            draw_returns = weights @ date_returns
            valid = draw_n > 0
            hit_rates = draw_hits[valid] / draw_n[valid] * 100
            roi = (draw_returns[valid] / (draw_n[valid] * STAKE_KRW) - 1) * 100

            rank1_period = period_rows(rank1, period)
            rank1_bets = rank1_period.loc[rank1_period["bet"].eq(1)].copy()
            rank1_bets["_date_index"] = rank1_bets["race_date"].map(date_to_idx).astype(int)
            base_n = np.bincount(rank1_bets["_date_index"], minlength=len(dates)).astype(np.int64)
            base_hits = np.bincount(rank1_bets["_date_index"], weights=rank1_bets["hit"], minlength=len(dates))
            base_returns = np.bincount(rank1_bets["_date_index"], weights=rank1_bets["return_krw"], minlength=len(dates))
            base_draw_n = weights @ base_n
            base_draw_hits = weights @ base_hits
            base_draw_returns = weights @ base_returns
            paired_valid = (draw_n > 0) & (base_draw_n > 0)
            paired_hit_delta = (
                draw_hits[paired_valid] / draw_n[paired_valid]
                - base_draw_hits[paired_valid] / base_draw_n[paired_valid]
            ) * 100
            paired_roi_delta = (
                (draw_returns[paired_valid] / (draw_n[paired_valid] * STAKE_KRW))
                - (base_draw_returns[paired_valid] / (base_draw_n[paired_valid] * STAKE_KRW))
            ) * 100
            rows.append({
                "model": model,
                "price_scope": scope,
                "strategy": strategy,
                "period": period,
                "bets": int(actual["bets"]),
                "hits": int(actual["hits"]),
                "hit_rate_pct": actual["hit_rate_pct"],
                "hit_rate_ci_low_pct": float(np.percentile(hit_rates, 2.5)) if valid.any() else None,
                "hit_rate_ci_high_pct": float(np.percentile(hit_rates, 97.5)) if valid.any() else None,
                "roi_pct": actual["roi_pct"],
                "roi_ci_low_pct": float(np.percentile(roi, 2.5)) if valid.any() else None,
                "roi_ci_high_pct": float(np.percentile(roi, 97.5)) if valid.any() else None,
                "valid_draws": int(valid.sum()),
                "zero_bet_draws": int((~valid).sum()),
                "paired_valid_draws_vs_rank1": int(paired_valid.sum()),
                "paired_zero_draws_vs_rank1": int((~paired_valid).sum()),
                "hit_rate_diff_vs_rank1_pct_points": (
                    float(actual["hit_rate_pct"] - summary.loc[
                        summary["model"].eq(model) & summary["price_scope"].eq(scope)
                        & summary["strategy"].eq("rank_1") & summary["period"].eq(period), "hit_rate_pct"
                    ].iloc[0]) if actual["hit_rate_pct"] is not None else None
                ),
                "hit_rate_diff_ci_low_pct_points": float(np.percentile(paired_hit_delta, 2.5)) if paired_valid.any() else None,
                "hit_rate_diff_ci_high_pct_points": float(np.percentile(paired_hit_delta, 97.5)) if paired_valid.any() else None,
                "roi_diff_vs_rank1_pct_points": (
                    float(actual["roi_pct"] - summary.loc[
                        summary["model"].eq(model) & summary["price_scope"].eq(scope)
                        & summary["strategy"].eq("rank_1") & summary["period"].eq(period), "roi_pct"
                    ].iloc[0]) if actual["roi_pct"] is not None else None
                ),
                "roi_diff_ci_low_pct_points": float(np.percentile(paired_roi_delta, 2.5)) if paired_valid.any() else None,
                "roi_diff_ci_high_pct_points": float(np.percentile(paired_roi_delta, 97.5)) if paired_valid.any() else None,
                "draw_count": int(schedule.shape[0]),
                "dates_per_draw": int(schedule.shape[1]),
                "schedule_sha256": EXPECTED_INPUTS[SCHEDULE],
            })
    return pd.DataFrame(rows)


def make_rank_calibration(pair_rows: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for model in MODEL_SOURCES:
        source = pair_rows.loc[pair_rows["model"].eq(model) & pair_rows["quote_status"].eq("valid")]
        rank_column = f"{model}_rank"
        p_column = f"{model}_p"
        source = source.copy()
        source["rank_bin"] = source[rank_column].map(lambda r: format_rank_bin(int(r)))
        for bin_name in [str(i) for i in range(1, 6)] + ["6-10", "11+"]:
            part = source.loc[source["rank_bin"].eq(bin_name)]
            if part.empty:
                continue
            p = part[p_column].astype(float)
            hits = part["hit"].astype(float)
            rows.append({
                "model": model,
                "role": MODEL_SOURCES[model]["role"],
                "probability_rank": bin_name,
                "pair_rows": int(len(part)),
                "race_count": int(part["race_id"].nunique()),
                "mean_p": float(p.mean()),
                "observed_hit_rate": float(hits.mean()),
                "calibration_gap_observed_minus_p": float(hits.mean() - p.mean()),
                "brier_score": float(np.mean((p - hits) ** 2)),
            })
    return pd.DataFrame(rows)


def make_rank_distribution(selections: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (model, scope, strategy), group in selections.groupby(["model", "scope", "strategy"], sort=False):
        for period in PERIODS:
            bets = period_rows(group, period).loc[lambda x: x["bet"].eq(1)].copy()
            total = len(bets)
            for rank_bin in [str(i) for i in range(1, 6)] + ["6-10", "11+"]:
                count = int(bets["chosen_rank"].map(lambda r: format_rank_bin(int(r))).eq(rank_bin).sum()) if total else 0
                rows.append({
                    "model": model,
                    "price_scope": scope,
                    "strategy": strategy,
                    "period": period,
                    "chosen_rank_bin": rank_bin,
                    "bets": count,
                    "share_of_bets_pct": count / total * 100 if total else None,
                    "total_bets": total,
                })
    return pd.DataFrame(rows)


def make_cases(selections: pd.DataFrame, pair_rows: pd.DataFrame) -> pd.DataFrame:
    candidates = selections.loc[
        selections["scope"].eq("complete_all_pair_quotes")
        & selections["bet"].eq(1)
        & selections["chosen_rank"].gt(1)
    ].copy()
    case_rows = []
    for (model, strategy), group in candidates.groupby(["model", "strategy"], sort=False):
        for hit in (1, 0):
            for rank_bin in ("2", "3", "4", "5", "6-10", "11+"):
                part = group.loc[group["hit"].eq(hit) & group["chosen_rank"].map(lambda r: format_rank_bin(int(r))).eq(rank_bin)].copy()
                if part.empty:
                    continue
                median_score = float(part["score"].median())
                part["_distance_from_median_score"] = (part["score"] - median_score).abs()
                part = part.sort_values(["_distance_from_median_score", "race_date", "race_id", "pair"], kind="mergesort").head(2)
                for item in part.itertuples(index=False):
                    source = pair_rows.loc[
                        pair_rows["model"].eq(model)
                        & pair_rows["race_id"].eq(item.race_id)
                    ]
                    first = source.loc[source[f"{model}_rank"].eq(1)].iloc[0]
                    chosen = source.loc[source["pair"].eq(item.pair)].iloc[0]
                    case_rows.append({
                        "model": model,
                        "role": MODEL_SOURCES[model]["role"],
                        "strategy": strategy,
                        "race_id": item.race_id,
                        "race_date": item.race_date,
                        "year": item.year,
                        "outcome": "hit" if hit else "miss",
                        "chosen_rank_bin": rank_bin,
                        "rank1_pair": first["pair"],
                        "rank1_p": float(first[f"{model}_p"]),
                        "rank1_quote": float(first["final_quote"]),
                        "rank1_score": float(first[f"{model}_posthoc_score"]),
                        "chosen_pair": item.pair,
                        "chosen_rank": int(item.chosen_rank),
                        "chosen_p": float(item.p),
                        "chosen_quote": float(item.final_quote),
                        "chosen_score": float(item.score),
                        "hit": int(item.hit),
                        "stake_krw": int(item.stake_krw),
                        "gross_return_krw": int(item.return_krw),
                        "net_krw": int(item.net_krw),
                        "selection_median_score": median_score,
                        "source_page_sha256": str(chosen["source_page_sha256"]),
                    })
    return pd.DataFrame(case_rows)


def verify_independent_strategy_reference(
    selections: pd.DataFrame,
    summary: pd.DataFrame,
    bootstrap: pd.DataFrame,
) -> dict:
    """Compare this run with separately derived root strategy and ticket references."""
    model_names = {
        "pair_id_baseline": "baseline_id",
        "riding_conditions_candidate": "riding_candidate",
    }
    strategy_names = {
        "rank_1": "rank_1", "rank_2": "rank_2", "rank_3": "rank_3",
        "rank_4": "rank_4", "rank_5": "rank_5",
        "rank_1_ev_gt_0": "rank_1_ev_positive",
        "all_max_ev_gt_0": "max_ev_all",
        "top3_max_ev_gt_0": "max_ev_top3",
        "top5_max_ev_gt_0": "max_ev_top5",
        "p_ge_020_max_ev_gt_0": "max_ev_p020",
        "p_ge_030_max_ev_gt_0": "max_ev_p030",
        "top3_max_ev_gt_020": "max_ev_top3_edge020",
        "p_ge_020_max_ev_gt_020": "max_ev_p020_edge020",
    }
    actual_rows = selections.loc[
        selections["scope"].eq("complete_all_pair_quotes") & selections["bet"].eq(1)
    ].copy()
    reference_rows = pd.read_csv(ROOT_SELECTION_REFERENCE, dtype=str, keep_default_na=False)
    actual_rows["reference_model"] = actual_rows["model"].map(model_names)
    actual_rows["reference_strategy"] = actual_rows["strategy"].map(strategy_names)
    reference_rows["reference_model"] = reference_rows["model"]
    reference_rows["reference_strategy"] = reference_rows["strategy"]
    keys = ["reference_model", "reference_strategy", "race_id"]
    actual_rows = actual_rows.sort_values(keys, kind="mergesort").reset_index(drop=True)
    reference_rows = reference_rows.sort_values(keys, kind="mergesort").reset_index(drop=True)
    require(len(actual_rows) == len(reference_rows), "independent strategy ticket row count differs")
    require(actual_rows[keys].equals(reference_rows[keys]), "independent strategy ticket keys differ")
    field_matches = {}
    for actual_name, reference_name in (
        ("horse_i", "horse_i"), ("horse_j", "horse_j"), ("p", "p"),
        ("final_quote", "quote"), ("score", "edge"), ("hit", "y_pair"),
        ("return_krw", "gross"), ("chosen_rank", "probability_rank"),
    ):
        left = pd.to_numeric(actual_rows[actual_name], errors="coerce")
        right = pd.to_numeric(reference_rows[reference_name], errors="coerce")
        require(np.allclose(left, right, rtol=0, atol=1e-12, equal_nan=True),
                f"independent selected ticket values differ: {actual_name}")
        field_matches[actual_name] = int(len(actual_rows))

    summary_reference = pd.read_csv(ROOT_STRATEGY_REFERENCE)
    actual_summary = summary.loc[summary["price_scope"].eq("complete_all_pair_quotes")].copy()
    actual_summary["reference_model"] = actual_summary["model"].map(model_names)
    actual_summary["reference_strategy"] = actual_summary["strategy"].map(strategy_names)
    actual_summary["reference_period"] = actual_summary["period"].map(
        {"all": "all", "2025": "2025", "2026_partial": "2026"}
    )
    summary_reference["reference_model"] = summary_reference["model"]
    summary_reference["reference_strategy"] = summary_reference["strategy"]
    summary_reference["reference_period"] = summary_reference["period"].astype(str)
    summary_keys = ["reference_model", "reference_strategy", "reference_period"]
    merged_summary = actual_summary.merge(summary_reference, on=summary_keys, validate="one_to_one", suffixes=("_actual", "_reference"))
    require(len(merged_summary) == 78, "independent strategy summary row count differs")
    summary_match_fields = {}
    for actual_name, reference_name, factor in (
        ("eligible_price_races", "eligible_races", 1.0),
        ("bets", "bets", 1.0), ("hits", "hits", 1.0),
        ("stake_krw", "stake", 1.0), ("gross_return_krw", "gross", 1.0),
        ("net_krw", "net", 1.0), ("roi_pct", "roi", 100.0),
        ("mean_p", "mean_p", 1.0), ("mean_model_ev", "mean_edge", 1.0),
        ("mean_quote", "mean_quote", 1.0),
        ("roi_without_largest_1_hits_pct", "roi_without_top1_hits", 100.0),
        ("roi_without_largest_3_hits_pct", "roi_without_top3_hits", 100.0),
        ("roi_without_largest_5_hits_pct", "roi_without_top5_hits", 100.0),
    ):
        left_name = actual_name + "_actual" if actual_name in {"bets", "hits", "mean_p", "mean_quote"} else actual_name
        right_name = reference_name + "_reference" if reference_name in {"bets", "hits", "mean_p", "mean_quote"} else reference_name
        left = pd.to_numeric(merged_summary[left_name], errors="coerce")
        right = pd.to_numeric(merged_summary[right_name], errors="coerce") * factor
        require(np.allclose(left, right, rtol=0, atol=1e-10, equal_nan=True),
                f"independent strategy summary differs: {actual_name}")
        summary_match_fields[actual_name] = int(len(merged_summary))

    actual_ci = bootstrap.loc[bootstrap["price_scope"].eq("complete_all_pair_quotes")].copy()
    actual_ci["reference_model"] = actual_ci["model"].map(model_names)
    actual_ci["reference_strategy"] = actual_ci["strategy"].map(strategy_names)
    actual_ci["reference_period"] = actual_ci["period"].map(
        {"all": "all", "2025": "2025", "2026_partial": "2026"}
    )
    merged_ci = actual_ci.merge(summary_reference, on=summary_keys, validate="one_to_one", suffixes=("_actual", "_reference"))
    require(len(merged_ci) == 78, "independent bootstrap row count differs")
    ci_match_fields = {}
    for actual_name, reference_name, factor in (
        ("roi_ci_low_pct", "roi_ci_low", 100.0),
        ("roi_ci_high_pct", "roi_ci_high", 100.0),
        ("hit_rate_ci_low_pct", "hit_rate_ci_low", 100.0),
        ("hit_rate_ci_high_pct", "hit_rate_ci_high", 100.0),
        ("zero_bet_draws", "undefined_draws", 1.0),
        ("valid_draws", "valid_draws", 1.0),
    ):
        actual_column = actual_name + "_actual" if actual_name == "valid_draws" else actual_name
        reference_column = reference_name + "_reference" if reference_name == "valid_draws" else reference_name
        left = pd.to_numeric(merged_ci[actual_column], errors="coerce")
        right = pd.to_numeric(merged_ci[reference_column], errors="coerce") * factor
        require(np.allclose(left, right, rtol=0, atol=1e-10, equal_nan=True),
                f"independent bootstrap CI differs: {actual_name}")
        ci_match_fields[actual_name] = int(len(merged_ci))
    return {
        "status": "PASS",
        "method": "row-by-row comparison with separately computed reference; no analysis output imported",
        "reference_hashes": {
            "strategy_reference_sha256": sha256_file(ROOT_STRATEGY_REFERENCE),
            "selection_reference_sha256": sha256_file(ROOT_SELECTION_REFERENCE),
        },
        "selected_ticket_rows": int(len(actual_rows)),
        "selected_ticket_fields_matching": field_matches,
        "strategy_period_rows": int(len(merged_summary)),
        "strategy_fields_matching_each_row": summary_match_fields,
        "bootstrap_period_rows": int(len(merged_ci)),
        "bootstrap_fields_matching_each_row": ci_match_fields,
    }


def main() -> None:
    require(STUDY.is_dir() and PLAN.is_file(), "study folder and fixed PLAN.md are required")
    for path, expected in EXPECTED_INPUTS.items():
        require(sha256_file(path) == expected, f"fixed input SHA-256 changed: {path.relative_to(ROOT)}")
    _, raw_frames = load_predictions()
    ranked_frames = attach_ranks(raw_frames)

    # Build the common pair universe with both fixed probability sources.
    pair_rows_by_key = {}
    for model, frame in ranked_frames.items():
        for row in frame.itertuples(index=False):
            pair_rows_by_key[(row.race_id, row.pair)] = {
                **pair_rows_by_key.get((row.race_id, row.pair), {}),
                f"{model}_p": float(row.p),
                f"{model}_rank": int(row.rank),
                "race_id": str(row.race_id),
                "race_date": str(row.race_date),
                "year": int(row.year),
                "pair": str(row.pair),
                "horse_i": int(row.horse_i),
                "horse_j": int(row.horse_j),
                "hit": int(row.hit),
            }
    predictions = pd.DataFrame(pair_rows_by_key.values())
    helper = load_helper()
    pair_rows, source_census, source_page_index = source_audit(predictions, ranked_frames, helper)
    race_price_valid = pair_rows.groupby("race_id")["quote_status"].apply(lambda s: s.eq("valid").all())
    pair_rows["race_full_quote_valid"] = pair_rows["race_id"].map(race_price_valid).astype(bool)
    for model in MODEL_SOURCES:
        pair_rows[f"{model}_posthoc_score"] = pair_rows.apply(
            lambda r: float(r[f"{model}_p"]) * float(r["final_quote"]) - 1.0 if r["quote_status"] == "valid" else np.nan,
            axis=1,
        )
        pair_rows["model"] = model
        pair_rows["p"] = pair_rows[f"{model}_p"]
        pair_rows["rank"] = pair_rows[f"{model}_rank"]
        pair_rows["score"] = pair_rows[f"{model}_posthoc_score"]
        model_rows = pair_rows.copy()
        if "all_model_rows" not in locals():
            all_model_rows = []
        all_model_rows.append(model_rows)
    pair_rows = pd.concat(all_model_rows, ignore_index=True)
    require(pair_rows["quote_status"].eq("valid").all(), "invalid quote exists after source census")
    require(pair_rows.loc[pair_rows["model"].eq("pair_id_baseline")].shape[0] == 48_539,
            "primary pair row count changed after joining quotes")
    require(pair_rows.loc[pair_rows["model"].eq("riding_conditions_candidate")].shape[0] == 48_539,
            "supplementary pair row count changed after joining quotes")

    selections, summary = make_selections(pair_rows)
    # Frozen bootstrap schedule covers the full 2024–2026 development roster, then masks to each price cohort.
    all_date_column = []
    for source in MODEL_SOURCES.values():
        all_date_column.extend(pd.read_parquet(source["path"], columns=["race_date"])["race_date"].tolist())
    all_dates = pd.to_datetime(pd.Series(all_date_column), errors="coerce").dt.strftime("%Y-%m-%d").dropna().tolist()
    dates, schedule, schedule_receipt = load_schedule(all_dates)
    bootstrap = make_bootstrap(selections, summary, dates, schedule)
    independent_crosscheck = verify_independent_strategy_reference(selections, summary, bootstrap)
    calibration = make_rank_calibration(pair_rows)
    rank_distribution = make_rank_distribution(selections)
    cases = make_cases(selections, pair_rows)
    primary_all = summary.loc[
        summary["model"].eq("pair_id_baseline")
        & summary["price_scope"].eq("complete_all_pair_quotes")
        & summary["strategy"].eq("all_max_ev_gt_0")
        & summary["period"].eq("all")
    ].iloc[0]
    primary_ci = bootstrap.loc[
        bootstrap["model"].eq("pair_id_baseline")
        & bootstrap["price_scope"].eq("complete_all_pair_quotes")
        & bootstrap["strategy"].eq("all_max_ev_gt_0")
        & bootstrap["period"].eq("all")
    ].iloc[0]
    yearly_primary = summary.loc[
        summary["model"].eq("pair_id_baseline")
        & summary["price_scope"].eq("complete_all_pair_quotes")
        & summary["strategy"].eq("all_max_ev_gt_0")
        & summary["period"].isin(["2025", "2026_partial"])
    ].set_index("period")

    # Persist compact, auditable rows: full pair/quote rows and only actual selected tickets.
    selected_rows = selections.loc[selections["bet"].eq(1)].copy()
    pair_rows.to_csv(STUDY / "pair_rows.csv", index=False)
    selected_rows.to_csv(STUDY / "selection_rows.csv", index=False)
    summary.to_csv(STUDY / "summary.csv", index=False)
    bootstrap.to_csv(STUDY / "bootstrap_ci.csv", index=False)
    calibration.to_csv(STUDY / "rank_calibration.csv", index=False)
    rank_distribution.to_csv(STUDY / "selection_rank_distribution.csv", index=False)
    cases.to_csv(STUDY / "cases.csv", index=False)
    source_page_index.to_csv(STUDY / "SOURCE_PAGE_INDEX.csv", index=False)
    (STUDY / "SOURCE_CENSUS.json").write_text(
        json.dumps(source_census, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )

    summary_records = []
    for row in summary.itertuples(index=False):
        summary_records.append({
            "model": str(row.model),
            "role": str(row.model_role),
            "price_scope": str(row.price_scope),
            "strategy": str(row.strategy),
            "period": str(row.period),
            "bets": int(row.bets),
            "hits": int(row.hits),
            "hit_rate_pct": None if pd.isna(row.hit_rate_pct) else float(row.hit_rate_pct),
            "mean_p": None if pd.isna(row.mean_p) else float(row.mean_p),
            "mean_quote": None if pd.isna(row.mean_quote) else float(row.mean_quote),
            "mean_model_ev": None if pd.isna(row.mean_model_ev) else float(row.mean_model_ev),
            "stake_krw": int(row.stake_krw),
            "gross_return_krw": int(row.gross_return_krw),
            "net_krw": int(row.net_krw),
            "roi_pct": None if pd.isna(row.roi_pct) else float(row.roi_pct),
        })
    report = {
        "status": "CONDITIONAL_POSTRACE_DIAGNOSTIC_ONLY",
        "study": "20261015_all_pair_postrace_value_v1",
        "interpretation": "post-race final quote oracle condition; not a pre-race expected value, profitability validation, or recommendation",
        "main_finding": {
            "model": "pair_id_baseline",
            "strategy": "all_max_ev_gt_0",
            "races": int(primary_all["bets"]),
            "observed_roi_pct": float(primary_all["roi_pct"]),
            "date_bootstrap_95pct_roi_ci_pct": [
                float(primary_ci["roi_ci_low_pct"]), float(primary_ci["roi_ci_high_pct"])
            ],
            "roi_after_removing_largest_winning_ticket_pct": float(primary_all["roi_without_largest_1_hits_pct"]),
            "yearly_roi_pct": {
                "2025": float(yearly_primary.loc["2025", "roi_pct"]),
                "2026_partial": float(yearly_primary.loc["2026_partial", "roi_pct"]),
            },
            "mean_selected_probability_pct": float(primary_all["mean_p"] * 100),
            "realized_hit_rate_pct": float(primary_all["hit_rate_pct"]),
            "conclusion": "The observed positive ROI is not evidence of established profit: the date-bootstrap interval is wide, the ROI turns negative after removing the largest winning ticket, yearly results differ, and realized hit rate is far below mean selected probability.",
        },
        "pool": "QPL only; saved probability is the event that both horses finish in the official Top3; QNL probability is not used",
        "stake_contract": {
            "per_selected_race_krw": STAKE_KRW,
            "gross_return_on_hit": "final displayed QPL multiplier × stake; the quote includes stake",
            "gross_return_on_miss_krw": 0,
            "roi": "(gross return − stake) / stake",
            "second_fee_deduction": False,
        },
        "cohort": {
            "races": 1_142,
            "race_dates": 171,
            "pair_rows_per_probability_source": 48_539,
            "year_counts": {"2025": 654, "2026_partial_through_2026_09_19": 488},
            "2024": {"races": 637, "reason_excluded": "no eligible verified local final QPL source coverage"},
        },
        "models": {
            model: {
                "path": str(source["path"].relative_to(ROOT)),
                "probability_column": source["column"],
                "role": source["role"],
            } for model, source in MODEL_SOURCES.items()
        },
        "source_census": source_census,
        "independent_direct_raw_json_crosscheck": source_census["independent_direct_raw_json_crosscheck"],
        "independent_root_strategy_crosscheck": independent_crosscheck,
        "source_coverage": {
            "full_quote_primary_races": int(pair_rows.loc[pair_rows["model"].eq("pair_id_baseline")].groupby("race_id")["race_full_quote_valid"].first().sum()),
            "partial_price_scope_races": 1_142,
            "candidate_pair_prices_valid": int(pair_rows.loc[pair_rows["model"].eq("pair_id_baseline"), "quote_status"].eq("valid").sum()),
            "candidate_pair_prices_invalid_or_missing": int(pair_rows.loc[pair_rows["model"].eq("pair_id_baseline"), "quote_status"].ne("valid").sum()),
        },
        "strategies_fixed_in_plan": [
            {"id": s[0], "rule": s[1]} for s in STRATEGIES
        ],
        "results_all_period": summary_records,
        "bootstrap": {
            "schedule_path": str(SCHEDULE.relative_to(ROOT)),
            "schedule_sha256": EXPECTED_INPUTS[SCHEDULE],
            "receipt_status": schedule_receipt.get("status"),
            "draws": int(schedule.shape[0]),
            "dates_per_draw": int(schedule.shape[1]),
            "unit": "race date; same frozen draws used for every model/rule",
            "zero_selected_draws_recorded": True,
        },
        "limits": [
            "Final displayed quotes are post-race in this analysis; p × quote − 1 is an oracle score, not an executable pre-race expected value.",
            "2025–2026 are repeated historical development data; these results are not independent future validation.",
            "Selection from the whole pair universe can favor long quotes; fixed probability-rank and p >= 0.20/0.30 rules expose that selection tradeoff.",
            "Quotes are final displayed gross multipliers; tax treatment is outside this analysis and no second fee is deducted.",
            "The riding-conditions model is supplementary and remains an unadopted research candidate.",
        ],
        "outputs": {
            "pair_rows": int(len(pair_rows)),
            "selection_rows": int(len(selected_rows)),
            "summary_rows": int(len(summary)),
            "bootstrap_rows": int(len(bootstrap)),
            "rank_calibration_rows": int(len(calibration)),
            "rank_distribution_rows": int(len(rank_distribution)),
            "representative_switch_cases": int(len(cases)),
            "verified_source_pages": int(len(source_page_index)),
        },
    }
    (STUDY / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    readme = make_readme(report, summary, bootstrap, calibration, cases)
    (STUDY / "README.md").write_text(readme, encoding="utf-8")

    outputs = [
        "PLAN.md", "analysis.py", "README.md", "REPORT.json", "SOURCE_CENSUS.json", "SOURCE_PAGE_INDEX.csv",
        "pair_rows.csv", "selection_rows.csv", "summary.csv", "bootstrap_ci.csv", "rank_calibration.csv",
        "selection_rank_distribution.csv", "cases.csv",
    ]
    manifest = {
        "inputs": {
            str(path.relative_to(ROOT)): {"sha256": sha256_file(path)} for path in EXPECTED_INPUTS
        } | {str(PLAN.relative_to(ROOT)): {"sha256": sha256_file(PLAN)}},
        "semantic_database_extract_sha256": source_census["semantic_quote_result_sha256"],
        "outputs_sha256": {name: sha256_file(STUDY / name) for name in outputs},
        "read_only": {
            "sqlite_uri_mode": "ro",
            "sqlite_query_only": True,
            "new_network_requests": False,
            "model_fit_or_refit": False,
            "database_writes": False,
            "operations_changes": False,
        },
        "source_metadata_export_policy": {
            "source_urls_exported": False,
            "request_parameters_exported": False,
            "credentials_exported": False,
            "page_hashes_preserved": True,
        },
    }
    (STUDY / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "source_census": {"pairs": 48_539, "valid_quotes": source_census["pair_quote_status"].get("valid", 0),
                          "races_full_quote": report["source_coverage"]["full_quote_primary_races"]},
        "strategy_rows": len(summary),
        "bootstrap_rows": len(bootstrap),
        "representative_switch_cases": len(cases),
        "outputs": str(STUDY),
    }, ensure_ascii=False, indent=2))


def make_readme(report: dict, summary: pd.DataFrame, bootstrap: pd.DataFrame,
                calibration: pd.DataFrame, cases: pd.DataFrame) -> str:
    all_rows = summary.loc[
        summary["period"].eq("all") & summary["price_scope"].eq("complete_all_pair_quotes")
    ].copy()
    all_rows = all_rows.sort_values(["model", "strategy"], kind="mergesort")
    by_model = {model: all_rows.loc[all_rows["model"].eq(model)].set_index("strategy") for model in MODEL_SOURCES}
    lines = [
        "# 전체 후보쌍 QPL 사후 가치 탐색",
        "",
        "저장된 모든 pair의 두 말 동시 Top3 확률과 해당 조합의 최종 복연승(QPL) 표시배당을 연결해, 확률 1위 외 후보를 사후 EV 점수로 선택했을 때의 실현 ROI를 계산했다. `p × final quote − 1`은 결승 뒤 확정 가격을 사용한 oracle 조건부 점수이며, 사전 기대수익이나 실제 구매 가능 전략을 검증하지 않는다.",
        "",
        "## 원천·코호트",
        "",
        f"API301의 최신 완전 로컬 원문 run과 페이지 SHA를 확인했다. 2025년 654경주와 2026년 9월 19일까지 488경주, 총 1,142경주·171일의 48,539개 pair 가격이 전부 유효했다. 전 pair QPL 키는 비취소 출전마 조합과 일치했고, 적중·미적중 pair 모두에서 가격이 원문에 있었다. 누락, 0, 비유한 값, 9999.9 sentinel, field mismatch, 저장 label/공식 Top3 mismatch는 없었다. 상세 census와 보존된 페이지 SHA 목록은 `SOURCE_CENSUS.json` 및 `SOURCE_PAGE_INDEX.csv`에 있다.",
        "",
        "2024년 637경주는 검증 가능한 로컬 최종 배당 자료가 없어 제외했다. primary는 pair-ID baseline이며 riding-conditions candidate는 보조 비교로 따로 표시했다. 모든 선택은 경주마다 최대 1장, 1,000원으로 계산했다. 적중환급은 최종 표시배당 배수 × 1,000원이고, 미적중 환급은 0원이다. 표시 배당에 원금이 포함되므로 ROI는 환급−투입을 계산했고 별도 수수료를 차감하지 않았다.",
        "",
        "## 전체 완전가격 cohort",
        "",
        "**해석:** primary에서 전 pair 최대 EV>0 선택은 관측 ROI가 +1.92%지만 수익이 확인된 것은 아니다. 날짜 bootstrap 95% CI가 −41.94%~+53.68%로 넓고, 최대 당첨 1건을 빼면 ROI −7.42%다. 연도별 ROI는 2025년 −10.32%, 2026년 +18.32%로 방향이 다르며, 선택 평균 확률 8.14%에 비해 실제 적중률은 2.63%였다. 따라서 이 결과는 고배당 꼬리 결과에 민감한 사후 진단이다.",
        "",
        "| 모델 | 규칙 | 선택/1,142 | 적중률 | 평균 p | 평균 배당 | 평균 p×배당−1 | 순손익 | ROI | ROI 95% 날짜 CI |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model, rows in by_model.items():
        ci = bootstrap.loc[
            bootstrap["model"].eq(model)
            & bootstrap["price_scope"].eq("complete_all_pair_quotes")
            & bootstrap["period"].eq("all")
        ].set_index("strategy")
        for strategy, row in rows.iterrows():
            c = ci.loc[strategy]
            hit = "—" if pd.isna(row["hit_rate_pct"]) else f"{row['hit_rate_pct']:.1f}% ({int(row['hits'])}/{int(row['bets'])})"
            roi = "—" if pd.isna(row["roi_pct"]) else f"{row['roi_pct']:.1f}%"
            ci_text = "—" if pd.isna(c["roi_ci_low_pct"]) else f"[{c['roi_ci_low_pct']:.1f}, {c['roi_ci_high_pct']:.1f}]%"
            pmean = "—" if pd.isna(row["mean_p"]) else f"{row['mean_p']:.3f}"
            qmean = "—" if pd.isna(row["mean_quote"]) else f"{row['mean_quote']:.2f}"
            evmean = "—" if pd.isna(row["mean_model_ev"]) else f"{row['mean_model_ev']:.3f}"
            lines.append(
                f"| {model} | {strategy} | {int(row['bets'])}/1,142 | {hit} | {pmean} | {qmean} | {evmean} | ₩{int(row['net_krw']):,} | {roi} | {ci_text} |"
            )
    rank3_cases = cases.loc[
        cases["model"].eq("pair_id_baseline")
        & cases["strategy"].eq("top3_max_ev_gt_0")
        & cases["chosen_rank"].eq(3)
    ]
    rank3_hit = rank3_cases.loc[rank3_cases["hit"].eq(1)].head(1)
    rank3_miss = rank3_cases.loc[rank3_cases["hit"].eq(0)].head(1)
    lines.extend([
        "",
        "## 확률 1위에서 후순위로 바뀐 사례",
        "",
        "아래는 primary pair-ID baseline에서 `top3_max_ev_gt_0` 규칙이 확률 1위 대신 확률 3위를 고른 사례다. 사례 표본은 적중·미적중별로 EV 중앙값에 가까운 경주를 선택해 최고 환급 사례에 치우치지 않게 했다.",
        "",
        "| 결과 | 경주 | rank 1 pair: p / 배당 / 점수 | 선택 rank 3 pair: p / 배당 / 점수 | 환급 |",
        "|---|---|---|---|---:|",
    ])
    for label, part in (("적중", rank3_hit), ("미적중", rank3_miss)):
        if part.empty:
            continue
        row = part.iloc[0]
        lines.append(
            f"| {label} | {row['race_id']} | {row['rank1_pair']}: {row['rank1_p']:.1%} / {row['rank1_quote']:.1f} / {row['rank1_score']:.3f} | {row['chosen_pair']}: {row['chosen_p']:.1%} / {row['chosen_quote']:.1f} / {row['chosen_score']:.3f} | ₩{int(row['gross_return_krw']):,} |"
        )
    lines.extend([
        "",
        "각 모델·규칙의 2025년과 2026년 부분연도 수치는 `summary.csv`에 있다. 날짜 bootstrap은 기존 고정 2,000×269 draw schedule을 모든 rule에 공통 적용했다. 0장인 반복 횟수와 rank 1 대비 paired hit/ROI 차이의 CI는 `bootstrap_ci.csv`에서 확인할 수 있다.",
        "",
        "고액 환급 제외 민감도(최대 당첨 환급 1·3·5건 및 그 티켓 투입을 함께 제거), 선택 확률 rank 분포, rank별 calibration은 `summary.csv`, `selection_rank_distribution.csv`, `rank_calibration.csv`에 있다. `cases.csv`는 rank 1 대신 rank 2 이상을 택한 경주에서 적중·미적중과 rank별로 중앙 EV에 가장 가까운 대표 사례를 균형 표집했다.",
        "",
        "전 pair에서 최대 `p × odds − 1`를 찾으면 높은 배당의 조합이 선택될 가능성이 커진다. 확률 rank 1–5, 확률 0.20/0.30 제한 규칙과 rank calibration을 함께 봐야 한다. 기준은 PLAN에 결과 확인 전에 고정했고, 결과를 보고 최적 경계는 고르지 않았다. 모델 학습·재예측, 네트워크 수집, DB 쓰기, 운영 변경은 없었다. 이 2025–2026 자료는 기존 개발 기간을 다시 사용한 사후 기술분석이다.",
        "",
        "재현: 저장소 루트에서 `.venv/bin/python -B jeju/research/20261015_all_pair_postrace_value_v1/analysis.py`.",
        "",
        "산출물: `PLAN.md`, `analysis.py`, `README.md`, `REPORT.json`, `SOURCE_CENSUS.json`, `SOURCE_MANIFEST.json`, `SOURCE_PAGE_INDEX.csv`, `pair_rows.csv`, `selection_rows.csv`, `summary.csv`, `bootstrap_ci.csv`, `rank_calibration.csv`, `selection_rank_distribution.csv`, `cases.csv`.",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()

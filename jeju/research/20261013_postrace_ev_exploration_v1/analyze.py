#!/usr/bin/env python3
"""Fixed-condition post-race QPL price exploration; no model fitting or network."""

from __future__ import annotations

import ast
import csv
import hashlib
import importlib.util
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261013_postrace_ev_exploration_v1"
PREDICTION = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
POLICY_SOURCE = ROOT / "jeju/research/20261012_pair_jockey_id_v1/pair_jockey_id_report.py"
QPL_RETURNS = ROOT / "jeju/research/20261013_pair_qpl_roi_v1/race_returns.csv"
QPL_HASHES = ROOT / "jeju/research/20261013_pair_qpl_roi_v1/SOURCE_HASHES.json"
QPL_REVIEW = ROOT / "jeju/research/20261013_pair_qpl_roi_v1/ROOT_REVIEW.json"
PAYOUT_AUDIT_CODE = ROOT / "jeju/research/20261013_pair_payout_audit_v1/analyze.py"
PAYOUT_AUDIT_REPORT = ROOT / "jeju/research/20261013_pair_payout_audit_v1/REPORT.json"
PAYOUT_AUDIT_SOURCE_HASHES = ROOT / "jeju/research/20261013_pair_payout_audit_v1/SOURCE_HASHES.json"
DB_FILE = ROOT / "data/horse_racing.sqlite3"
SCHEDULE = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
SCHEDULE_RECEIPT = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
PLAN = STUDY / "PLAN.md"

PREDICTION_SHA256 = "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6"
QPL_RETURNS_SHA256 = "8e1b1a2485d6c625445315bd856d7988fa9da54e3de0bd10b2dac02086179afa"
QPL_HASHES_SHA256 = "5d8498fecb5d7c1521aa3b85494e020e3337027432bb85f46506dafba1b92df6"
QPL_REVIEW_SHA256 = "e65a2c8476efe29241080a360bc4fc04e1a2733785cd9b03b98a4b39f27196b3"
PAYOUT_AUDIT_CODE_SHA256 = "0481c19a7e01f530d70a50bbe546e3f5a3d712615903b6b4f146d77099638cec"
PAYOUT_AUDIT_REPORT_SHA256 = "009b61510804b7db667c81daf0cdd57169c8d965b83d3622db607f2235bed553"
PAYOUT_AUDIT_SOURCE_HASHES_SHA256 = "017079e767405ec2079dfbf0575b0ce10f9ff5e2ccb4f32638b3ea7afc16278b"
SCHEDULE_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
SCHEDULE_RECEIPT_SHA256 = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"
STAKE_KRW = 10_000
EXPECTED_RACES_BY_YEAR = {2025: 654, 2026: 488}
PERIOD_RACES = {"all": 1_142, "2025": 654, "2026_partial": 488}
PERIODS = ("all", "2025", "2026_partial")
SELECTORS = {
    "jockey_id_candidate": {
        "flag": "selected_jockey_id_candidate",
        "probability": "jockey_id_candidate_calibrated_probability",
        "role": "primary",
    },
    "jockey_basic_candidate": {
        "flag": "selected_jockey_basic_candidate",
        "probability": "candidate_calibrated_probability",
        "role": "supplementary",
    },
}

CONDITIONS = [
    ("all_purchase", "all valid-price rows", lambda p, s: np.ones(len(p), dtype=bool)),
    ("p_ge_030", "p >= 0.30", lambda p, s: p >= 0.30),
    ("p_ge_040", "p >= 0.40", lambda p, s: p >= 0.40),
    ("score_ge_0", "score >= 0.00", lambda p, s: s >= 0.00),
    ("score_ge_005", "score >= 0.05", lambda p, s: s >= 0.05),
    ("score_ge_010", "score >= 0.10", lambda p, s: s >= 0.10),
    ("score_ge_020", "score >= 0.20", lambda p, s: s >= 0.20),
    ("score_ge_050", "score >= 0.50", lambda p, s: s >= 0.50),
    ("score_ge_100", "score >= 1.00", lambda p, s: s >= 1.00),
    ("p030_score_ge_0", "p >= 0.30 AND score >= 0.00", lambda p, s: (p >= 0.30) & (s >= 0.00)),
    ("p030_score_ge_010", "p >= 0.30 AND score >= 0.10", lambda p, s: (p >= 0.30) & (s >= 0.10)),
    ("p030_score_ge_020", "p >= 0.30 AND score >= 0.20", lambda p, s: (p >= 0.30) & (s >= 0.20)),
]
EV_BINS = (
    ("below_-1", "score < -1", lambda s: s < -1.0),
    ("[-1,0)", "-1 <= score < 0", lambda s: (s >= -1.0) & (s < 0.0)),
    ("[0,0.10)", "0 <= score < 0.10", lambda s: (s >= 0.0) & (s < 0.10)),
    ("[0.10,0.25)", "0.10 <= score < 0.25", lambda s: (s >= 0.10) & (s < 0.25)),
    ("[0.25,0.50)", "0.25 <= score < 0.50", lambda s: (s >= 0.25) & (s < 0.50)),
    ("[0.50,1.00)", "0.50 <= score < 1.00", lambda s: (s >= 0.50) & (s < 1.0)),
    ("[1.00,inf)", "score >= 1.00", lambda s: s >= 1.0),
)


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
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_id(value: object) -> str:
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def pair_key(a: object, b: object) -> str:
    left, right = sorted((int(canonical_id(a)), int(canonical_id(b))))
    require(left != right, "selected pair repeats one horse")
    return f"{left}-{right}"


def race_key(race_id: object) -> tuple[str, int, int]:
    date, meet, number = str(race_id).rsplit("_", 2)
    return date, int(meet), int(number)


def parse_decimal(value: object) -> Decimal | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def load_policy_source() -> str:
    """Read the declared policy map as syntax, without executing the report module."""
    source = POLICY_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(POLICY_SOURCE))
    policies = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "POLICIES" for target in node.targets
        ):
            policies = ast.literal_eval(node.value)
            break
    require(policies is not None, "candidate policy map missing from frozen source")
    require(
        policies.get("jockey_id_candidate")
        == ("selected_jockey_id_candidate", "jockey_id_candidate_calibrated_probability"),
        "current selector/probability source mapping changed",
    )
    require(
        policies.get("jockey_basic_candidate")
        == ("selected_jockey_basic_candidate", "candidate_calibrated_probability"),
        "basic selector/probability source mapping changed",
    )
    return sha256_file(POLICY_SOURCE)


def load_prediction_rows() -> tuple[pd.DataFrame, str]:
    require(sha256_file(PREDICTION) == PREDICTION_SHA256, "fixed prediction SHA-256 changed")
    columns = [
        "race_id", "race_date", "evaluation_year", "horse_i", "horse_j", "y_pair",
        "selected_jockey_id_candidate", "jockey_id_candidate_calibrated_probability",
        "selected_jockey_basic_candidate", "candidate_calibrated_probability",
    ]
    predictions = pd.read_parquet(PREDICTION, columns=columns)
    predictions["race_id"] = predictions["race_id"].map(canonical_id)
    predictions["race_date"] = pd.to_datetime(predictions["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    require(predictions["race_date"].notna().all(), "invalid race date in fixed predictions")
    predictions["evaluation_year"] = pd.to_numeric(predictions["evaluation_year"], errors="raise").astype(int)
    require(len(predictions) == 76_848, "fixed prediction row count changed")
    require(predictions["race_id"].nunique() == 1_779, "fixed prediction race count changed")
    require(predictions["race_date"].nunique() == 269, "fixed prediction date count changed")

    selected_parts = []
    for selector, policy in SELECTORS.items():
        flag = pd.to_numeric(predictions[policy["flag"]], errors="raise").astype(int)
        part = predictions.loc[flag.eq(1)].copy()
        part["selector"] = selector
        part["p"] = pd.to_numeric(part[policy["probability"]], errors="raise").astype(float)
        part["pair"] = [pair_key(a, b) for a, b in zip(part["horse_i"], part["horse_j"])]
        part["hit_prediction"] = pd.to_numeric(part["y_pair"], errors="raise").astype(int)
        part = part.loc[part["evaluation_year"].isin((2025, 2026))].copy()
        require(len(part) == 1_142 and part["race_id"].is_unique, f"selected cohort changed: {selector}")
        require(part["evaluation_year"].value_counts().to_dict() == EXPECTED_RACES_BY_YEAR,
                f"year cohort changed: {selector}")
        require(part["p"].notna().all() and np.isfinite(part["p"]).all(), f"non-finite saved p: {selector}")
        require(((part["p"] >= 0) & (part["p"] <= 1)).all(), f"saved p outside [0,1]: {selector}")
        selected_parts.append(part[[
            "selector", "race_id", "race_date", "evaluation_year", "pair", "p", "hit_prediction",
        ]])
    return pd.concat(selected_parts, ignore_index=True), sha256_file(PREDICTION)


def load_qpl_rows() -> tuple[pd.DataFrame, dict[str, str]]:
    require(sha256_file(QPL_RETURNS) == QPL_RETURNS_SHA256, "verified QPL race-return SHA-256 changed")
    require(sha256_file(QPL_HASHES) == QPL_HASHES_SHA256, "QPL input hash manifest changed")
    require(sha256_file(QPL_REVIEW) == QPL_REVIEW_SHA256, "QPL independent review changed")
    review = json.loads(QPL_REVIEW.read_text(encoding="utf-8"))
    require(review.get("status") == "PASS", "QPL return file lacks independent PASS review")
    frame = pd.read_csv(QPL_RETURNS, dtype=str, keep_default_na=False)
    frame = frame.loc[frame["selector"].isin(SELECTORS)].copy()
    frame["race_id"] = frame["race_id"].map(canonical_id)
    frame["year"] = pd.to_numeric(frame["year"], errors="raise").astype(int)
    frame["race_number"] = pd.to_numeric(frame["race_number"], errors="raise").astype(int)
    frame["hit"] = pd.to_numeric(frame["hit"], errors="raise").astype(int)
    frame["stake_krw"] = pd.to_numeric(frame["stake_krw"], errors="raise").astype(int)
    frame["return_krw"] = pd.to_numeric(frame["return_krw"], errors="raise").astype(int)
    frame["qpl_quote_decimal"] = frame["qpl_quote_odds"].map(parse_decimal)
    frame["paid_qpl_decimal"] = frame["paid_qpl_odds"].map(parse_decimal)
    frame["pair"] = [pair_key(a, b) for a, b in zip(frame["horse_i"], frame["horse_j"])]
    require(len(frame) == 2_284, "pinned return file does not contain 2 selectors × 1,142")
    require(not frame.duplicated(["selector", "race_id"]).any(), "duplicate selector/race payout row")
    for selector in SELECTORS:
        part = frame.loc[frame["selector"].eq(selector)]
        require(len(part) == 1_142, f"QPL return cohort changed: {selector}")
        require(part.groupby("year").size().to_dict() == EXPECTED_RACES_BY_YEAR,
                f"QPL return year counts changed: {selector}")
        require(part["stake_krw"].eq(STAKE_KRW).all(), f"QPL stake changed: {selector}")
    return frame, {
        "race_returns_sha256": QPL_RETURNS_SHA256,
        "source_hashes_sha256": QPL_HASHES_SHA256,
        "root_review_sha256": QPL_REVIEW_SHA256,
    }


def load_audit_helper():
    require(sha256_file(PAYOUT_AUDIT_CODE) == PAYOUT_AUDIT_CODE_SHA256, "pinned API301 helper changed")
    sys.path.insert(0, str(ROOT / "src"))
    spec = importlib.util.spec_from_file_location("readonly_pair_payout_audit_helper", PAYOUT_AUDIT_CODE)
    require(spec is not None and spec.loader is not None, "read-only API301 helper could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def readonly_db_extract(returns: pd.DataFrame) -> tuple[dict, dict, str, dict]:
    """Check selected final QPL rows and official results from SQLite in read-only mode."""
    uri = DB_FILE.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    target_ids = set(returns["race_id"])

    races: dict[str, dict] = {}
    for row in connection.execute(
        """SELECT r.id, r.race_date_local, r.race_number
           FROM races AS r
           JOIN racecourses AS c ON c.id = r.racecourse_id
           WHERE c.kra_meet_code = ? AND r.race_date_local BETWEEN ? AND ?
           ORDER BY r.race_date_local, r.race_number""",
        (2, "2025-01-01", "2026-09-19"),
    ):
        race_id = f"{row['race_date_local']}_2_{int(row['race_number'])}"
        if race_id in target_ids:
            require(race_id not in races, f"duplicate DB race business key: {race_id}")
            races[race_id] = {
                "race_db_id": int(row["id"]),
                "race_date": str(row["race_date_local"]),
                "race_number": int(row["race_number"]),
            }
    require(set(races) == target_ids and len(races) == 1_142, "DB race rows do not cover fixed cohort")

    result_rows: list[dict] = []
    podium_by_race: dict[str, list[int]] = {}
    quote_by_key: dict[tuple[str, str], Decimal] = {}
    race_id_by_db_id = {v["race_db_id"]: k for k, v in races.items()}
    race_db_ids = sorted(race_id_by_db_id)
    for offset in range(0, len(race_db_ids), 400):
        batch = race_db_ids[offset:offset + 400]
        placeholders = ",".join("?" for _ in batch)
        entries = connection.execute(
            f"""SELECT e.race_id, e.horse_number, e.scratched,
                       rr.finish_position, rr.disqualified
                FROM race_entries AS e
                JOIN race_results AS rr ON rr.race_entry_id = e.id
                WHERE e.race_id IN ({placeholders})
                ORDER BY e.race_id, e.horse_number""",
            batch,
        ).fetchall()
        for row in entries:
            race_id = race_id_by_db_id[int(row["race_id"])]
            finish = None if row["finish_position"] is None else int(row["finish_position"])
            result = {
                "race_id": race_id,
                "horse_number": int(row["horse_number"]),
                "scratched": int(bool(row["scratched"])),
                "finish_position": finish,
                "disqualified": int(bool(row["disqualified"])),
            }
            result_rows.append(result)
            if (
                not result["scratched"] and not result["disqualified"]
                and finish is not None and 1 <= finish <= 3
            ):
                podium_by_race.setdefault(race_id, []).append(result["horse_number"])
        quotes = connection.execute(
            f"""SELECT o.race_id, o.selection_key, o.odds
                FROM odds_snapshots AS o
                WHERE o.bet_type = ? AND o.race_id IN ({placeholders})
                ORDER BY o.race_id, o.selection_key""",
            ("QPL", *batch),
        ).fetchall()
        for row in quotes:
            race_id = race_id_by_db_id[int(row["race_id"])]
            key = (race_id, "-".join(map(str, sorted(
                int(part) for part in str(row["selection_key"]).split("-")
            ))))
            require(key not in quote_by_key, f"duplicate DB QPL quote key: {race_id}")
            quote_by_key[key] = Decimal(str(row["odds"]))

    for race_id in sorted(target_ids):
        podium = sorted(podium_by_race.get(race_id, []))
        require(len(podium) == 3 and len(set(podium)) == 3, f"official Top3 row count changed: {race_id}")
        podium_by_race[race_id] = podium

    selected_pair_rows: list[dict] = []
    for row in returns.itertuples(index=False):
        key = (row.race_id, row.pair)
        require(key in quote_by_key, f"selected DB QPL quote missing: {row.selector} {row.race_id}")
        quote = quote_by_key[key]
        require(quote == row.qpl_quote_decimal, f"DB/return quote mismatch: {row.selector} {row.race_id}")
        podium = podium_by_race[row.race_id]
        actual_hit = int(set(map(int, row.pair.split("-"))).issubset(set(podium)))
        require(actual_hit == row.hit, f"QPL hit differs from official result: {row.selector} {row.race_id}")
        selected_pair_rows.append({
            "selector": row.selector,
            "race_id": row.race_id,
            "pair": row.pair,
            "qpl_quote": str(quote),
        })
    connection.close()

    semantic_extract = {
        "definition": "sorted official finish rows for 1,142 cohort races plus exact selected QPL quote rows for 2 selectors",
        "official_result_rows": sorted(result_rows, key=lambda x: (x["race_id"], x["horse_number"])),
        "selected_qpl_quotes": sorted(selected_pair_rows, key=lambda x: (x["selector"], x["race_id"])),
    }
    digest = stable_sha256(semantic_extract)
    counts = {
        "race_rows": len(races),
        "official_result_rows": len(result_rows),
        "exact_selected_qpl_quotes": len(selected_pair_rows),
        "unique_race_pair_quotes": len({(r["race_id"], r["pair"]) for r in selected_pair_rows}),
        "official_podium_rows": len(podium_by_race),
        "semantic_extract_sha256": digest,
    }
    return races, podium_by_race, digest, counts


def source_page_extract(returns: pd.DataFrame) -> tuple[dict, pd.DataFrame, dict]:
    helper = load_audit_helper()
    targets = {race_key(race_id) for race_id in returns["race_id"]}
    require(len(targets) == 1_142 and all(meet == 2 for _, meet, _ in targets),
            "API301 targets differ from fixed Jeju cohort")
    pair_by_race: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for row in returns.itertuples(index=False):
        pair_by_race[race_key(row.race_id)].add(row.pair)
    wanted = {
        key: [("QPL", pair) for pair in sorted(pair_by_race.get(key, set()))]
        for key in targets
    }
    verified_runs, helper_counts = helper.archive_rows(targets, wanted)
    require(len(verified_runs) == len({(d, meet) for d, meet, _ in targets}),
            "latest complete API301 source run missing for a target date")

    page_rows: dict[tuple[str, str, int], dict] = {}
    page_usage: Counter[tuple[str, str, int]] = Counter()
    quote_by_key: dict[tuple[str, int, str], dict] = {}
    run_receipts: dict[str, dict] = {}
    for (day, meet), run in verified_runs.items():
        require(meet == 2, "unexpected non-Jeju API301 run")
        require(len(run["hashes"]) == len(run["paths"]) == int(run["page_count"]),
                f"API301 page index mismatch: {day}")
        run_id = str(run["run_id"])
        run_receipts[day] = {
            "run_id": run_id,
            "page_count": int(run["page_count"]),
            "complete_run_count_for_day": int(run["complete_run_count"]),
            "latest_run_retrieved_at_ms": int(run["retrieved_at_ms"]),
            "page_hashes": list(run["hashes"]),
        }
        for page_no, page_hash in enumerate(run["hashes"], start=1):
            page_rows[(day, run_id, page_no)] = {
                "race_date": day,
                "meet_code": meet,
                "source_run_id": run_id,
                "page_number": page_no,
                "page_sha256": str(page_hash),
                "selected_quote_rows_on_page": 0,
            }
        for race_date, race_meet, race_number in (
            key for key in targets if key[:2] == (day, meet)
        ):
            for pair in sorted(pair_by_race[(race_date, race_meet, race_number)]):
                source_key = (race_number, "QPL", pair)
                require(source_key in run["values"], f"exact pair absent from latest API301 pages: {day} R{race_number} {pair}")
                source_odds = run["values"][source_key]
                page_hash = run["page_for_key"].get(source_key)
                require(page_hash is not None, f"exact pair source page hash missing: {day} R{race_number}")
                quote_by_key[(day, race_number, pair)] = {
                    "source_quote": source_odds,
                    "source_page_sha256": str(page_hash),
                    "source_run_id": run_id,
                }
                matching_pages = [
                    i for i, candidate_hash in enumerate(run["hashes"], start=1)
                    if candidate_hash == page_hash
                ]
                require(len(matching_pages) == 1, f"source page hash not unique within run: {day} R{race_number}")
                page_usage[(day, run_id, matching_pages[0])] += 1
    for key, row in page_rows.items():
        row["selected_quote_rows_on_page"] = int(page_usage[key])
    page_index = pd.DataFrame(page_rows.values()).sort_values(
        ["race_date", "source_run_id", "page_number"]
    )
    unique_selected_quote_keys = {
        (race_key(row.race_id)[0], race_key(row.race_id)[2], row.pair)
        for row in returns.itertuples(index=False)
    }
    require(len(quote_by_key) == len(unique_selected_quote_keys),
            "local API301 exact-pair coverage differs from unique selected race pairs")
    return quote_by_key, page_index, {
        "target_dates": len(verified_runs),
        "verified_complete_latest_runs": len(run_receipts),
        "target_date_runs": run_receipts,
        "api301_registry_rows_for_target_days": int(helper_counts["api301_registry_rows_for_target_days"]),
        "complete_api301_runs_for_target_days": int(helper_counts["complete_runs"]),
        "api301_pages_in_latest_complete_runs": int(len(page_index)),
        "api301_pages_hash_verified": int(len(page_index)),
        "unique_selected_race_pair_quotes_verified": int(len(quote_by_key)),
        "selector_race_quote_occurrences_verified": int(len(returns)),
        "all_latest_run_pages_hash_verified": True,
        "metadata_exported": ["date", "meet code", "source run id", "page number", "page SHA-256"],
        "metadata_not_exported": ["source URL", "authentication fields", "request parameter JSON", "local raw-page path"],
    }


def classify_price(value: Decimal | None) -> tuple[bool, str]:
    if value is None:
        return False, "missing"
    if not value.is_finite():
        return False, "nonfinite"
    if value == Decimal("9999.9"):
        return False, "exception_9999_9"
    if value <= 0:
        return False, "nonpositive"
    return True, "valid"


def build_race_rows(
    selected: pd.DataFrame,
    returns: pd.DataFrame,
    source_quotes: dict,
    podiums: dict,
    source_hashes: dict[str, str],
) -> pd.DataFrame:
    joined = selected.merge(
        returns,
        on=["selector", "race_id"],
        how="left",
        validate="one_to_one",
        suffixes=("_prediction", "_return"),
    )
    require(len(joined) == 2_284 and joined["pair_return"].notna().all(),
            "selected predictions do not align to payout rows")
    output: list[dict] = []
    for row in joined.itertuples(index=False):
        require(row.pair_prediction == row.pair_return, f"selected pair changed in return file: {row.race_id}")
        require(row.race_date_prediction == row.race_date_return,
                f"selected race date changed in return file: {row.race_id}")
        require(int(row.evaluation_year) == int(row.year), f"year changed in return file: {row.race_id}")
        require(int(row.hit_prediction) == int(row.hit), f"saved pair label changed: {row.race_id}")
        quote = row.qpl_quote_decimal
        api_key = (str(row.race_date_prediction), int(row.race_number), str(row.pair_prediction))
        require(api_key in source_quotes, f"API301 quote missing: {row.race_id}")
        source_quote = source_quotes[api_key]
        require(source_quote["source_quote"] is not None, f"API301 exact pair quote is null: {row.race_id}")
        raw_decimal = Decimal(str(source_quote["source_quote"]))
        require(raw_decimal == quote, f"QPL final quote differs from exact API301 row: {row.selector} {row.race_id}")
        pair_numbers = set(map(int, row.pair_prediction.split("-")))
        official_hit = int(pair_numbers.issubset(set(podiums[row.race_id])))
        require(official_hit == int(row.hit), f"selected pair hit differs from official Top3: {row.selector} {row.race_id}")
        if int(row.hit):
            require(row.paid_qpl_decimal == quote, f"paid QPL odds mismatch on hit: {row.race_id}")
            expected_payout = quote * Decimal(STAKE_KRW)
            require(expected_payout == expected_payout.to_integral_value(),
                    f"non-integer QPL payout: {row.race_id}")
            require(int(expected_payout) == int(row.return_krw), f"QPL return arithmetic mismatch: {row.race_id}")
            original_page_hash = str(row.qpl_source_page_sha256 or "")
            require(
                not original_page_hash or original_page_hash == source_quote["source_page_sha256"],
                f"winning API301 source page mismatch: {row.race_id}",
            )
        else:
            require(row.paid_qpl_decimal == Decimal(0) and int(row.return_krw) == 0,
                    f"losing QPL payout must be zero: {row.race_id}")

        price_valid, exclusion = classify_price(quote)
        score = float(row.p) * float(quote) - 1.0 if price_valid else None
        stake = STAKE_KRW if price_valid else None
        payout = int(quote * Decimal(STAKE_KRW)) if price_valid and int(row.hit) else (0 if price_valid else None)
        net = payout - stake if price_valid else None
        output.append({
            "selector": row.selector,
            "race_id": row.race_id,
            "year": int(row.year),
            "race_date": str(row.race_date_prediction),
            "race_number": int(row.race_number),
            "pair": str(row.pair_prediction),
            "p": float(row.p),
            "final_quote": float(quote) if quote is not None else None,
            "ev_proxy": score,
            "price_valid": int(price_valid),
            "price_exclusion_reason": "" if price_valid else exclusion,
            "hit": int(row.hit),
            "stake_krw": stake,
            "return_krw": payout,
            "net_krw": net,
            "source_run_id": source_quote["source_run_id"],
            "source_hash": source_quote["source_page_sha256"],
            "api301_page_sha256": source_quote["source_page_sha256"],
            "qpl_returns_sha256": source_hashes["race_returns_sha256"],
            "prediction_parquet_sha256": PREDICTION_SHA256,
        })
    result = pd.DataFrame(output).sort_values(["selector", "race_date", "race_number"]).reset_index(drop=True)
    require(len(result) == 2_284, "per-race output row count changed")
    require(result.groupby("selector")["race_id"].nunique().eq(1_142).all(),
            "per-race output selector denominator changed")
    return result


def period_mask(frame: pd.DataFrame, period: str) -> np.ndarray:
    if period == "all":
        return np.ones(len(frame), dtype=bool)
    year = 2025 if period == "2025" else 2026
    return frame["year"].to_numpy(dtype=int) == year


def summary_metrics(frame: pd.DataFrame, selector: str, condition_id: str, expression: str,
                    period: str, total_races: int, eligible_price_races: int) -> dict:
    n = len(frame)
    hits = int(frame["hit"].sum()) if n else 0
    stake = n * STAKE_KRW
    payout = int(frame["return_krw"].sum()) if n else 0
    net = payout - stake
    score = frame["ev_proxy"].astype(float) if n else pd.Series(dtype=float)
    quotes = frame["final_quote"].astype(float) if n else pd.Series(dtype=float)
    p_values = frame["p"].astype(float) if n else pd.Series(dtype=float)
    hit_rows = frame.loc[frame["hit"].eq(1)] if n else frame
    hit_quotes = hit_rows["final_quote"].astype(float) if len(hit_rows) else pd.Series(dtype=float)
    sensitivity: dict[str, Any] = {}
    winners = frame.loc[frame["hit"].eq(1)].sort_values(
        ["return_krw", "race_id"], ascending=[False, True], kind="mergesort"
    )
    for k in (1, 3, 5):
        removed = winners.head(k)
        remaining = frame.drop(index=removed.index)
        remaining_stake = len(remaining) * STAKE_KRW
        remaining_payout = int(remaining["return_krw"].sum()) if len(remaining) else 0
        sensitivity[f"roi_without_top{k}_hit_pct"] = (
            (remaining_payout / remaining_stake - 1.0) * 100.0 if remaining_stake else None
        )
        sensitivity[f"removed_top{k}_race_count"] = int(len(removed))
        sensitivity[f"removed_top{k}_payout_krw"] = int(removed["return_krw"].sum()) if len(removed) else 0
    top5 = winners.head(5)
    top5_payout = int(top5["return_krw"].sum()) if len(top5) else 0
    return {
        "selector": selector,
        "condition_id": condition_id,
        "condition_expression": expression,
        "period": period,
        "period_race_denominator": int(total_races),
        "eligible_price_races": int(eligible_price_races),
        "eligible_price_coverage_pct": eligible_price_races / total_races * 100 if total_races else None,
        "n": int(n),
        "coverage_pct": n / total_races * 100 if total_races else None,
        "coverage_of_fixed_1142_pct": n / 1_142 * 100,
        "hits": hits,
        "hit_rate_pct": hits / n * 100 if n else None,
        "p_mean": float(p_values.mean()) if n else None,
        "quote_mean": float(quotes.mean()) if n else None,
        "quote_median": float(quotes.median()) if n else None,
        "mean_hit_final_quote": float(hit_quotes.mean()) if len(hit_quotes) else None,
        "posthoc_score_mean": float(score.mean()) if n else None,
        "stake_krw": stake,
        "payout_krw": payout,
        "net_krw": net,
        "roi_pct": (payout / stake - 1.0) * 100 if stake else None,
        "top5_payout_krw": top5_payout,
        "top5_payout_share_pct": top5_payout / payout * 100 if payout else None,
        **sensitivity,
    }


def make_summary_and_top5(race_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict] = []
    top5_rows: list[dict] = []
    for selector in SELECTORS:
        source = race_rows.loc[race_rows["selector"].eq(selector)].reset_index(drop=True)
        valid = source.loc[source["price_valid"].eq(1)].copy().reset_index(drop=True)
        for period in PERIODS:
            period_base = source.loc[period_mask(source, period)].copy()
            period_valid = valid.loc[period_mask(valid, period)].copy()
            total_races = len(period_base)
            eligible = len(period_valid)
            for condition_id, expression, selector_fn in CONDITIONS:
                mask = selector_fn(period_valid["p"].to_numpy(), period_valid["ev_proxy"].to_numpy())
                chosen = period_valid.loc[mask].copy()
                metrics = summary_metrics(
                    chosen, selector, condition_id, expression, period, total_races, eligible
                )
                summary_rows.append(metrics)
                winners = chosen.loc[chosen["hit"].eq(1)].sort_values(
                    ["return_krw", "race_id"], ascending=[False, True], kind="mergesort"
                ).head(5)
                payout_total = int(chosen["return_krw"].sum()) if len(chosen) else 0
                for rank, row in enumerate(winners.itertuples(index=False), start=1):
                    top5_rows.append({
                        "selector": selector,
                        "condition_id": condition_id,
                        "condition_expression": expression,
                        "period": period,
                        "rank_by_realized_payout": rank,
                        "race_id": row.race_id,
                        "race_date": row.race_date,
                        "year": int(row.year),
                        "pair": row.pair,
                        "p": float(row.p),
                        "final_quote": float(row.final_quote),
                        "ev_proxy": float(row.ev_proxy),
                        "return_krw": int(row.return_krw),
                        "net_krw": int(row.net_krw),
                        "selected_condition_payout_total_krw": payout_total,
                        "share_of_selected_condition_payout_pct": (
                            float(row.return_krw) / payout_total * 100 if payout_total else None
                        ),
                        "source_hash": row.source_hash,
                    })
    summary = pd.DataFrame(summary_rows)
    top5 = pd.DataFrame(top5_rows, columns=[
        "selector", "condition_id", "condition_expression", "period", "rank_by_realized_payout",
        "race_id", "race_date", "year", "pair", "p", "final_quote", "ev_proxy",
        "return_krw", "net_krw", "selected_condition_payout_total_krw",
        "share_of_selected_condition_payout_pct", "source_hash",
    ])
    require(len(summary) == 72, "fixed condition × selector × period count changed")
    return summary, top5


def make_bins(race_rows: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for selector in SELECTORS:
        source = race_rows.loc[
            race_rows["selector"].eq(selector) & race_rows["price_valid"].eq(1)
        ].reset_index(drop=True)
        for period in PERIODS:
            scope = source.loc[period_mask(source, period)].copy().reset_index(drop=True)
            total_races = PERIOD_RACES[period]
            for bin_id, expression, bin_fn in EV_BINS:
                mask = bin_fn(scope["ev_proxy"].to_numpy())
                part = scope.loc[mask].copy()
                metrics = summary_metrics(
                    part, selector, bin_id, expression, period, total_races, len(scope)
                )
                metrics["score_bin"] = bin_id
                rows.append(metrics)
    result = pd.DataFrame(rows)
    require(len(result) == 42, "fixed score bin × selector × period count changed")
    return result


def load_frozen_schedule(prediction_dates: list[str]) -> tuple[list[str], np.ndarray, dict]:
    require(sha256_file(SCHEDULE) == SCHEDULE_SHA256, "fixed date schedule SHA-256 changed")
    require(sha256_file(SCHEDULE_RECEIPT) == SCHEDULE_RECEIPT_SHA256, "fixed date receipt changed")
    receipt = json.loads(SCHEDULE_RECEIPT.read_text(encoding="utf-8"))
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "date schedule is not frozen")
    dates = sorted(set(prediction_dates))
    date_digest = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(len(dates) == 269 and date_digest == receipt.get("date_inventory_sha256"),
            "fixed prediction dates do not match schedule date inventory")
    schedule = np.load(SCHEDULE, allow_pickle=False)
    require(schedule.shape == (2_000, 269) and schedule.dtype == np.int32,
            "fixed date schedule shape/dtype changed")
    require(((schedule >= 0) & (schedule < len(dates))).all(), "invalid date index in fixed schedule")
    return dates, schedule, receipt


def make_bootstrap(
    race_rows: pd.DataFrame, summary: pd.DataFrame, dates: list[str], schedule: np.ndarray
) -> pd.DataFrame:
    date_to_idx = {d: i for i, d in enumerate(dates)}
    bootstrap_weights = np.stack([
        np.bincount(draw, minlength=len(dates)).astype(np.int32) for draw in schedule
    ])
    rows: list[dict] = []
    for selector in SELECTORS:
        source = race_rows.loc[
            race_rows["selector"].eq(selector) & race_rows["price_valid"].eq(1)
        ].copy()
        source["_day_idx"] = source["race_date"].map(date_to_idx).astype(int)
        for period in PERIODS:
            period_source = source.loc[period_mask(source, period)].copy()
            for condition_id, expression, selector_fn in CONDITIONS:
                chosen = period_source.loc[
                    selector_fn(
                        period_source["p"].to_numpy(),
                        period_source["ev_proxy"].to_numpy(),
                    )
                ].copy()
                date_n = np.bincount(chosen["_day_idx"].to_numpy(), minlength=len(dates)).astype(np.int64)
                date_hits = np.bincount(
                    chosen["_day_idx"].to_numpy(),
                    weights=chosen["hit"].to_numpy(dtype=float),
                    minlength=len(dates),
                )
                date_payout = np.bincount(
                    chosen["_day_idx"].to_numpy(),
                    weights=chosen["return_krw"].to_numpy(dtype=float),
                    minlength=len(dates),
                )
                draw_n = bootstrap_weights @ date_n
                draw_hits = bootstrap_weights @ date_hits
                draw_payout = bootstrap_weights @ date_payout
                valid = draw_n > 0
                hit_rates = draw_hits[valid] / draw_n[valid] * 100.0
                roi = (draw_payout[valid] / (draw_n[valid] * STAKE_KRW) - 1.0) * 100.0
                estimate = summary.loc[
                    summary["selector"].eq(selector)
                    & summary["condition_id"].eq(condition_id)
                    & summary["period"].eq(period)
                ].iloc[0]
                rows.append({
                    "selector": selector,
                    "condition_id": condition_id,
                    "condition_expression": expression,
                    "period": period,
                    "n": int(estimate["n"]),
                    "hits": int(estimate["hits"]),
                    "roi_pct": estimate["roi_pct"],
                    "hit_rate_pct": estimate["hit_rate_pct"],
                    "hit_rate_ci_low_pct": float(np.percentile(hit_rates, 2.5)) if valid.any() else None,
                    "hit_rate_ci_high_pct": float(np.percentile(hit_rates, 97.5)) if valid.any() else None,
                    "roi_ci_low_pct": float(np.percentile(roi, 2.5)) if valid.any() else None,
                    "roi_ci_high_pct": float(np.percentile(roi, 97.5)) if valid.any() else None,
                    "valid_draws": int(valid.sum()),
                    "undefined_draws_excluded": int((~valid).sum()),
                    "draw_count": int(schedule.shape[0]),
                    "date_count_per_draw": int(schedule.shape[1]),
                    "schedule_sha256": SCHEDULE_SHA256,
                })
    result = pd.DataFrame(rows)
    require(len(result) == 72, "date CI condition count changed")
    return result


def build_report(
    race_rows: pd.DataFrame,
    summary: pd.DataFrame,
    bins: pd.DataFrame,
    bootstrap: pd.DataFrame,
    page_index: pd.DataFrame,
    input_hashes: dict,
    api301_summary: dict,
    db_counts: dict,
    schedule_receipt: dict,
) -> dict:
    excluded_by_selector = {}
    for selector in SELECTORS:
        part = race_rows.loc[race_rows["selector"].eq(selector)]
        excluded_by_selector[selector] = {
            "rows": len(part),
            "valid_price_rows": int(part["price_valid"].sum()),
            "excluded_by_reason": dict(Counter(
                x for x in part.loc[part["price_valid"].eq(0), "price_exclusion_reason"].tolist()
            )),
        }
    overall = []
    for row in summary.loc[summary["period"].eq("all")].itertuples(index=False):
        overall.append({
            "selector": str(row.selector),
            "condition_id": str(row.condition_id),
            "n": int(row.n),
            "hits": int(row.hits),
            "hit_rate_pct": None if pd.isna(row.hit_rate_pct) else float(row.hit_rate_pct),
            "p_mean": None if pd.isna(row.p_mean) else float(row.p_mean),
            "quote_mean": None if pd.isna(row.quote_mean) else float(row.quote_mean),
            "posthoc_score_mean": None if pd.isna(row.posthoc_score_mean) else float(row.posthoc_score_mean),
            "stake_krw": int(row.stake_krw),
            "payout_krw": int(row.payout_krw),
            "net_krw": int(row.net_krw),
            "roi_pct": None if pd.isna(row.roi_pct) else float(row.roi_pct),
        })
    return {
        "status": "CONDITIONAL_POSTRACE_DIAGNOSTIC_ONLY",
        "study": "20261013_postrace_ev_exploration_v1",
        "plan_sha256": sha256_file(PLAN),
        "cohort": {
            "prediction_rows": 76_848,
            "fixed_evaluation_races": 1_779,
            "fixed_evaluation_dates": 269,
            "payout_supported_races": 1_142,
            "year_counts": {"2025": 654, "2026_partial_to_2026_09_19": 488},
            "selector_race_rows": 2_284,
            "selectors": list(SELECTORS),
            "meet": "Jeju",
            "pool": "QPL",
        },
        "probability_contract": {
            "jockey_id_candidate": {
                "selection_flag": "selected_jockey_id_candidate",
                "probability_column": "jockey_id_candidate_calibrated_probability",
                "event": "selected pair both finish in Top 3",
                "role": "primary",
            },
            "jockey_basic_candidate": {
                "selection_flag": "selected_jockey_basic_candidate",
                "probability_column": "candidate_calibrated_probability",
                "event": "selected pair both finish in Top 3",
                "role": "supplementary comparison",
            },
            "qnl_probability_used": False,
        },
        "price_audit": {
            "method": "exact date/Jeju/race/QPL/pair match to the latest complete locally stored API301 run; all page hashes checked against source_documents registry",
            "selector_race_quotes_checked": 2_284,
            "all_exact_selected_pair_quotes_match_qpl_quote_odds": True,
            "all_selected_pair_hits_rechecked_against_official_top3": True,
            "source_page_index_rows": int(len(page_index)),
            "source_page_hashes_verified": int(len(page_index)),
            **api301_summary,
        },
        "database": {
            "access": "SQLite mode=ro; PRAGMA query_only=ON; read transaction",
            "database_file_sha256": None,
            "semantic_extract": db_counts,
            "database_write": False,
        },
        "price_validity": {
            "rule": "finite, greater than zero, and not equal to 9999.9; independent of hit",
            "by_selector": excluded_by_selector,
            "invalid_price_rows_excluded_from_conditions": True,
        },
        "posthoc_score": {
            "formula": "saved p × final QPL quote − 1",
            "label": "oracle conditional score using final post-race price",
            "not_a_true_expected_value": True,
            "not_a_true_upper_bound": True,
            "not_an_executable_pre-purchase_rule": True,
        },
        "conditions": [
            {"condition_id": condition_id, "expression": expression}
            for condition_id, expression, _ in CONDITIONS
        ],
        "fixed_conditions_not_ranked_or_selected": True,
        "stake_krw_per_selected_race": STAKE_KRW,
        "realized_return": "hit × final_quote × 10,000 KRW; miss returns zero",
        "roi": "(total return − total stake) / total stake",
        "sensitivity": "Remove the highest 1/3/5 realized winning payouts and remove those races' stakes from the denominator.",
        "bootstrap": {
            "schedule": "existing fixed schedule; no new draws",
            "schedule_sha256": SCHEDULE_SHA256,
            "schedule_receipt_sha256": SCHEDULE_RECEIPT_SHA256,
            "schedule_status": schedule_receipt.get("status"),
            "draws": 2_000,
            "date_count": 269,
            "confidence_intervals": "95% percentile date-cluster intervals for hit rate and ROI",
            "empty_mask_draws": "excluded and counted per selector, condition, and period",
        },
        "overall_summary": overall,
        "output_rows": {
            "race_rows.csv": int(len(race_rows)),
            "summary.csv": int(len(summary)),
            "bin_summary.csv": int(len(bins)),
            "bootstrap_ci.csv": int(len(bootstrap)),
        },
        "limitations": [
            "The final payout was observed after the race; conditioning on it is an oracle-style retrospective diagnostic.",
            "No verified pre-purchase quote was available, so this does not evaluate a strategy that could have been executed before the race.",
            "The saved pair Top3 probability is uncertain; p × final quote is not a calibrated expected return.",
            "The analysis does not represent a profitability ceiling or guarantee future profits.",
            "2024 lacks verified QPL payout coverage; 2026 is a partial year and the 2025–2026 races are repeatedly used development data.",
            "Equal-stake arithmetic does not model price changes caused by actual purchases.",
            "No training, refitting, network access, database writes, or operational model changes were made.",
        ],
        "inputs": input_hashes,
    }


def make_readme(summary: pd.DataFrame) -> str:
    selector_labels = {
        "jockey_id_candidate": "현재 기수 ID 후보 (주 분석)",
        "jockey_basic_candidate": "직전 기수 기본 후보 (보조 비교)",
    }
    lines = [
        "# 사후 QPL 표시배당 기반 조건부 선별 탐색",
        "",
        "고정 pair 선택과 저장 확률에 사후 최종 QPL 표시배당을 결합해, 미리 최종배당을 알았다고 가정할 때의 조건부 점수와 실현 환급을 기술했다. p × final_quote − 1은 oracle 성격의 사후 점수다. 사전 구매 규칙, 기대수익 검증, 수익 상한 또는 미래 수익 근거가 아니다.",
        "",
        "주 승식은 복연승(QPL)이다. 저장 확률은 선택한 두 말이 함께 Top3에 들 확률이며 복승(QNL)에 쓰지 않았다. 주 분석은 selected_jockey_id_candidate와 jockey_id_candidate_calibrated_probability; 보조 비교는 selected_jockey_basic_candidate와 코드에서 확인한 candidate_calibrated_probability를 사용했다.",
        "",
        "고정 cohort는 2025년 654경주와 2026-09-19까지의 488경주다. 전체 저장 예측은 1,779경주·269일이며 2024년 637경주는 검증된 배당자료가 없어 환급 cohort에 없다. 각 선택기 1,142쌍의 최종 QPL quote를 로컬 API301 최신 완전 원문 페이지의 날짜·제주·경주번호·승식·정확한 두 마번과 전수 대조했다. 원문 페이지는 registry SHA로 검증했다. URL, 인증정보, 요청 파라미터와 원문 경로는 산출물에 싣지 않았다.",
        "",
        "모든 고정 조건은 summary.csv에 전체·2025·2026 부분연도로 담았다. coverage 분모는 해당 기간의 고정 경주 수이며 coverage_of_fixed_1142_pct도 함께 제공한다. 유효 가격은 finite, >0, 9999.9 제외로 결과와 무관하게 정했다. 제외 수는 REPORT.json에 선택기별로 기록했다. 미적중의 paid_qpl_odds=0은 점수나 선택에 쓰지 않았다.",
        "",
        "## 전체 cohort 고정 조건 결과",
        "",
        "| 선택기 | 조건 | 경주 | 적중 | 적중률 | 평균 점수 | 총환급 | 순손익 | ROI | 날짜 CI ROI 95% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    overall = summary.loc[summary["period"].eq("all")]
    ci = pd.read_csv(STUDY / "bootstrap_ci.csv")
    for row in overall.itertuples(index=False):
        interval = ci.loc[
            ci["selector"].eq(row.selector)
            & ci["condition_id"].eq(row.condition_id)
            & ci["period"].eq("all")
        ].iloc[0]
        roi_ci = (
            "—" if pd.isna(interval["roi_ci_low_pct"])
            else f"{interval['roi_ci_low_pct']:.2f}%–{interval['roi_ci_high_pct']:.2f}%"
        )
        payout = f"₩{int(row.payout_krw):,}"
        net = f"₩{int(row.net_krw):,}"
        mean_score = "—" if pd.isna(row.posthoc_score_mean) else f"{row.posthoc_score_mean:.4f}"
        hit_rate = "—" if pd.isna(row.hit_rate_pct) else f"{row.hit_rate_pct:.2f}%"
        roi = "—" if pd.isna(row.roi_pct) else f"{row.roi_pct:.2f}%"
        lines.append(
            f"| {selector_labels[row.selector]} | {row.condition_id} ({row.condition_expression}) | "
            f"{int(row.n)} | {int(row.hits)} | {hit_rate} | {mean_score} | {payout} | {net} | {roi} | {roi_ci} |"
        )
    lines.extend([
        "",
        "조건별 상위 5개 당첨 환급과 기여 비중은 top5.csv에, 사후 점수 구간표는 bin_summary.csv에 있다. bootstrap_ci.csv는 저장된 2,000×269 날짜 schedule을 재사용한 95% percentile CI이며 선택 경기 0건인 반복 수를 별도로 기록했다. 가장 큰 당첨 1·3·5건을 제거한 민감도와 제거한 경기의 투입 감소는 summary.csv에 담겼다.",
        "",
        "작업은 저장된 예측·환급 파일과 로컬 보관 원문만 읽었다. SQLite는 mode=ro, query_only=ON으로 열었다. 신규 수집·네트워크·학습·재예측·운영 모델 변경은 없었다. 같은 과거 개발 기간을 다시 사용한 기술 분석이며 특정 경계를 채택하거나 추천하지 않는다.",
        "",
        "재현: 저장소 루트에서 .venv/bin/python -B jeju/research/20261013_postrace_ev_exploration_v1/analyze.py.",
        "",
        "파일: PLAN.md, analyze.py, README.md, REPORT.json, SOURCE_HASHES.json, race_rows.csv, summary.csv, bin_summary.csv, bootstrap_ci.csv, top5.csv, SOURCE_PAGE_INDEX.csv.",
        "",
    ])
    return "\n".join(lines)


def write_outputs(
    race_rows: pd.DataFrame,
    summary: pd.DataFrame,
    bins: pd.DataFrame,
    bootstrap: pd.DataFrame,
    top5: pd.DataFrame,
    page_index: pd.DataFrame,
    report: dict,
    input_hashes: dict,
    db_digest: str,
) -> None:
    require(STUDY.resolve().is_relative_to((ROOT / "jeju/research").resolve()),
            "study path escaped research directory")
    page_index.to_csv(STUDY / "SOURCE_PAGE_INDEX.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    race_rows.to_csv(STUDY / "race_rows.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    summary.to_csv(STUDY / "summary.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    bins.to_csv(STUDY / "bin_summary.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    bootstrap.to_csv(STUDY / "bootstrap_ci.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    top5.to_csv(STUDY / "top5.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    report["price_audit"]["page_index_sha256"] = sha256_file(STUDY / "SOURCE_PAGE_INDEX.csv")
    with (STUDY / "REPORT.json").open("w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    (STUDY / "README.md").write_text(make_readme(summary), encoding="utf-8")

    output_names = [
        "PLAN.md", "analyze.py", "README.md", "REPORT.json", "race_rows.csv",
        "summary.csv", "bin_summary.csv", "bootstrap_ci.csv", "top5.csv", "SOURCE_PAGE_INDEX.csv",
    ]
    source_hashes = {
        "inputs": input_hashes,
        "semantic_database_extract": {
            "sha256": db_digest,
            "description": "sorted selected QPL quotes and official result rows; full SQLite file not hashed",
        },
        "outputs_sha256": {name: sha256_file(STUDY / name) for name in output_names},
        "read_only": {
            "sqlite_uri_mode": "ro",
            "query_only": True,
            "network": False,
            "model_fit_or_refit": False,
            "database_write": False,
        },
        "source_metadata_export_policy": {
            "source_urls_exported": False,
            "authentication_parameters_exported": False,
            "request_parameter_json_exported": False,
        },
    }
    with (STUDY / "SOURCE_HASHES.json").open("w", encoding="utf-8") as stream:
        json.dump(source_hashes, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> None:
    require(STUDY.is_dir(), "output directory missing")
    require(PLAN.is_file(), "fixed PLAN.md missing")
    policy_sha = load_policy_source()
    selected, prediction_sha = load_prediction_rows()
    returns, qpl_hashes = load_qpl_rows()
    require(sha256_file(PAYOUT_AUDIT_REPORT) == PAYOUT_AUDIT_REPORT_SHA256,
            "pinned QPL source-payout report changed")
    require(sha256_file(PAYOUT_AUDIT_SOURCE_HASHES) == PAYOUT_AUDIT_SOURCE_HASHES_SHA256,
            "pinned QPL source-payout hash manifest changed")
    _, podiums, db_digest, db_counts = readonly_db_extract(returns)
    api_quotes, page_index, api301_summary = source_page_extract(returns)
    race_rows = build_race_rows(selected, returns, api_quotes, podiums, qpl_hashes)
    summary, top5 = make_summary_and_top5(race_rows)
    bins = make_bins(race_rows)
    prediction_dates = pd.read_parquet(PREDICTION, columns=["race_date"])["race_date"]
    prediction_dates = pd.to_datetime(prediction_dates, errors="coerce").dt.strftime("%Y-%m-%d").dropna().tolist()
    dates, schedule, schedule_receipt = load_frozen_schedule(prediction_dates)
    bootstrap = make_bootstrap(race_rows, summary, dates, schedule)
    inputs = {
        "fixed_prediction_parquet": {"path": str(PREDICTION.relative_to(ROOT)), "sha256": prediction_sha},
        "selector_probability_source": {"path": str(POLICY_SOURCE.relative_to(ROOT)), "sha256": policy_sha},
        "verified_qpl_race_returns": {"path": str(QPL_RETURNS.relative_to(ROOT)), "sha256": QPL_RETURNS_SHA256},
        "qpl_returns_source_hashes": {"path": str(QPL_HASHES.relative_to(ROOT)), "sha256": QPL_HASHES_SHA256},
        "qpl_returns_root_review": {"path": str(QPL_REVIEW.relative_to(ROOT)), "sha256": QPL_REVIEW_SHA256},
        "api301_readonly_helper": {"path": str(PAYOUT_AUDIT_CODE.relative_to(ROOT)), "sha256": PAYOUT_AUDIT_CODE_SHA256},
        "payout_audit_report": {"path": str(PAYOUT_AUDIT_REPORT.relative_to(ROOT)), "sha256": PAYOUT_AUDIT_REPORT_SHA256},
        "payout_audit_source_hashes": {"path": str(PAYOUT_AUDIT_SOURCE_HASHES.relative_to(ROOT)), "sha256": PAYOUT_AUDIT_SOURCE_HASHES_SHA256},
        "date_schedule": {"path": str(SCHEDULE.relative_to(ROOT)), "sha256": SCHEDULE_SHA256},
        "date_schedule_receipt": {"path": str(SCHEDULE_RECEIPT.relative_to(ROOT)), "sha256": SCHEDULE_RECEIPT_SHA256},
        "study_plan": {"path": str(PLAN.relative_to(ROOT)), "sha256": sha256_file(PLAN)},
        "sqlite_file_sha256": None,
    }
    report = build_report(
        race_rows, summary, bins, bootstrap, page_index, inputs,
        api301_summary, db_counts, schedule_receipt,
    )
    write_outputs(
        race_rows, summary, bins, bootstrap, top5, page_index,
        report, inputs, db_digest,
    )
    print(json.dumps({
        "status": report["status"],
        "race_rows": len(race_rows),
        "condition_summary_rows": len(summary),
        "score_bin_rows": len(bins),
        "bootstrap_rows": len(bootstrap),
        "api301_exact_pairs_verified": len(api_quotes),
        "source_pages_hash_verified": len(page_index),
        "outputs": str(STUDY),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

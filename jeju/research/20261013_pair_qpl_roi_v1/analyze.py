"""Realized equal-stake QPL returns for frozen Jeju pair selectors."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
PAIR_FILE = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
PAIR_SHA256 = "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6"
AUDIT = ROOT / "jeju/research/20261013_pair_payout_audit_v1"
AUDIT_ANALYZE = AUDIT / "analyze.py"
AUDIT_ANALYZE_SHA256 = "0481c19a7e01f530d70a50bbe546e3f5a3d712615903b6b4f146d77099638cec"
DB_FILE = ROOT / "data/horse_racing.sqlite3"
STAKE_KRW = 10_000
MEET = 2

SELECTORS = {
    "jockey_id_candidate": "selected_jockey_id_candidate",
    "jockey_basic_candidate": "selected_jockey_basic_candidate",
    "expanded_candidate": "selected_expanded_candidate",
    "old_direct": "selected_old_direct",
    "raw_top2": "selected_raw_top2",
    "saved_f1_top2": "selected_saved_f1_top2",
    "joint_marginal_top2": "selected_candidate_joint_marginal_top2",
    "candidate_joint_maxpair": "selected_candidate_joint_maxpair",
    "matched_joint_maxpair": "selected_matched_joint_maxpair",
}
EXPECTED_FULL_HITS = {
    "jockey_id_candidate": 438,
    "jockey_basic_candidate": 429,
    "expanded_candidate": 427,
    "old_direct": 426,
    "raw_top2": 429,
    "saved_f1_top2": 429,
    "joint_marginal_top2": 434,
    "candidate_joint_maxpair": 422,
    "matched_joint_maxpair": 429,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_json_sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def race_key(race_id: str) -> tuple[str, int, int]:
    date, meet, number = str(race_id).rsplit("_", 2)
    return date, int(meet), int(number)


def pair_key(a: int, b: int) -> str:
    return "-".join(str(n) for n in sorted((int(a), int(b))))


def payout_krw(odds: float, stake: int) -> int:
    amount = Decimal(str(odds)) * stake
    require(amount == amount.to_integral_value(), "QPL return is not a whole won amount")
    return int(amount)


def load_audit_helper():
    require(file_sha256(AUDIT_ANALYZE) == AUDIT_ANALYZE_SHA256, "pinned payout-audit code changed")
    spec = importlib.util.spec_from_file_location("verified_pair_payout_audit", AUDIT_ANALYZE)
    require(spec is not None and spec.loader is not None, "payout-audit helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_qpl_quotes(race_db_ids: set[int]) -> tuple[dict, list[dict]]:
    uri = DB_FILE.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    placeholders = ",".join("?" for _ in race_db_ids)
    sql = f"""SELECT o.race_id AS race_db_id, o.selection_key, o.odds, o.observed_at_ms
              FROM odds_snapshots AS o
              WHERE o.bet_type = ? AND o.race_id IN ({placeholders})
              ORDER BY o.race_id, o.selection_key, o.observed_at_ms, o.id"""
    rows = connection.execute(sql, ("QPL", *sorted(race_db_ids))).fetchall()
    connection.close()
    quotes: dict[tuple[int, str], float] = {}
    canonical_rows = []
    for row in rows:
        key = (int(row["race_db_id"]), pair_key(*str(row["selection_key"]).split("-")))
        require(key not in quotes, "duplicate QPL quote for race and selection")
        odds = float(row["odds"])
        require(math.isfinite(odds) and odds > 0, "invalid QPL quote")
        quotes[key] = odds
        canonical_rows.append(
            {"race_db_id": key[0], "selection_key": key[1], "odds": odds,
             "observed_at_ms": int(row["observed_at_ms"])}
        )
    return quotes, canonical_rows


def main() -> None:
    require(file_sha256(PAIR_FILE) == PAIR_SHA256, "frozen pair prediction SHA-256 mismatch")
    predictions = pd.read_parquet(PAIR_FILE)
    helper = load_audit_helper()

    race_ids_by_selector: dict[str, pd.DataFrame] = {}
    full_hits = {}
    for selector, flag in SELECTORS.items():
        selected = predictions.loc[predictions[flag].eq(1)].copy()
        require(len(selected) == 1779 and selected["race_id"].is_unique,
                f"full selector roster changed: {selector}")
        full_hits[selector] = int(selected["y_pair"].sum())
        require(full_hits[selector] == EXPECTED_FULL_HITS[selector],
                f"full selector hits changed: {selector}")
        covered = selected.loc[selected["evaluation_year"].isin([2025, 2026])].copy()
        covered["race_key"] = covered["race_id"].map(race_key)
        race_ids_by_selector[selector] = covered

    common_races = set(race_ids_by_selector["jockey_id_candidate"]["race_id"])
    require(len(common_races) == 1142, "payout-supported race denominator changed")
    require(set(race_ids_by_selector["jockey_id_candidate"]["evaluation_year"].value_counts().to_dict().items())
            == {(2025, 654), (2026, 488)}, "year denominator changed")
    for selector, frame in race_ids_by_selector.items():
        require(set(frame["race_id"]) == common_races, f"selector race set differs: {selector}")

    targets = {race_key(race_id) for race_id in common_races}
    official = helper.read_results(targets)
    require(set(official) == targets, "official result coverage changed")
    db_id_by_race = {race_id: int(official[race_key(race_id)]["race_db_id"]) for race_id in common_races}
    quotes, quote_rows = read_qpl_quotes(set(db_id_by_race.values()))

    wanted_pairs: dict[tuple[str, int, int], set[str]] = defaultdict(set)
    for frame in race_ids_by_selector.values():
        for row in frame.itertuples(index=False):
            if int(row.y_pair) == 1:
                key = race_key(row.race_id)
                wanted_pairs[key].add(pair_key(row.horse_i, row.horse_j))
    wanted = {key: [("QPL", value) for value in sorted(wanted_pairs.get(key, set()))]
              for key in targets}
    verified_runs, _ = helper.archive_rows(targets, wanted)

    rows = []
    official_extract = []
    for race_id in sorted(common_races):
        key = race_key(race_id)
        result = official[key]
        runners = result["runners"]
        placed = [r for r in runners if not r["scratched"] and not r["disqualified"]
                  and r["finish_position"] is not None and 1 <= int(r["finish_position"]) <= 3]
        podium = sorted(int(r["horse_number"]) for r in placed)
        top_two = [int(r["horse_number"]) for r in placed if int(r["finish_position"]) <= 2]
        require(len(podium) == 3 and len(set(podium)) == 3 and len(top_two) == 2,
                f"official tie or incomplete result in covered race: {race_id}")
        official_extract.append({
            "race_id": race_id, "race_db_id": int(result["race_db_id"]),
            "runners": sorted(runners, key=lambda r: int(r["horse_number"])),
        })
        day_run = verified_runs[key[:2]]
        for selector, frame in race_ids_by_selector.items():
            selected = frame.loc[frame["race_id"].eq(race_id)]
            require(len(selected) == 1, f"selector does not choose exactly once: {selector} {race_id}")
            chosen = selected.iloc[0]
            chosen_pair = pair_key(chosen["horse_i"], chosen["horse_j"])
            hit = int(set(map(int, chosen_pair.split("-"))).issubset(set(podium)))
            require(hit == int(chosen["y_pair"]), f"frozen label differs from official Top3: {selector} {race_id}")
            qpl_quote = quotes.get((db_id_by_race[race_id], chosen_pair))
            require(qpl_quote is not None, f"selected QPL quote missing: {selector} {race_id}")
            source_hash = ""
            if hit:
                business_key = (key[2], "QPL", chosen_pair)
                source_odds = day_run["values"].get(business_key)
                require(source_odds is not None and source_odds > 0,
                        f"official API301 QPL key missing: {selector} {race_id}")
                require(math.isclose(qpl_quote, float(source_odds), rel_tol=0.0, abs_tol=1e-8),
                        f"DB/API301 winning QPL mismatch: {selector} {race_id}")
                source_hash = day_run["page_for_key"][business_key]
            paid_odds = qpl_quote if hit else 0.0
            returned = payout_krw(paid_odds, STAKE_KRW) if hit else 0
            rows.append({
                "race_id": race_id, "race_date": key[0], "year": int(chosen["evaluation_year"]),
                "race_number": key[2], "selector": selector,
                "horse_i": int(chosen["horse_i"]), "horse_j": int(chosen["horse_j"]),
                "selected_pair": chosen_pair, "official_top3_numbers": json.dumps(podium),
                "hit": hit, "qpl_quote_odds": qpl_quote, "paid_qpl_odds": paid_odds,
                "stake_krw": STAKE_KRW, "return_krw": returned,
                "net_krw": returned - STAKE_KRW, "qpl_source_page_sha256": source_hash,
            })

    returns = pd.DataFrame(rows).sort_values(["race_date", "race_number", "selector"])
    require(len(returns) == 9 * 1142, "race-return row count changed")
    for selector in SELECTORS:
        part = returns.loc[returns["selector"].eq(selector)]
        require(len(part) == 1142 and int(part["hit"].sum()) == int(
            race_ids_by_selector[selector].loc[race_ids_by_selector[selector]["evaluation_year"].isin([2025, 2026]), "y_pair"].sum()),
            f"return-row hit count changed: {selector}")

    summary_rows = []
    for selector in SELECTORS:
        method = returns.loc[returns["selector"].eq(selector)]
        for period, subset in (
            ("2025-2026", method),
            ("2025", method.loc[method["year"].eq(2025)]),
            ("2026_partial", method.loc[method["year"].eq(2026)]),
        ):
            hits = int(subset["hit"].sum())
            stake = int(subset["stake_krw"].sum())
            returned = int(subset["return_krw"].sum())
            paid_odds = sum((Decimal(str(x)) for x in subset.loc[subset["hit"].eq(1), "paid_qpl_odds"]), Decimal(0))
            summary_rows.append({
                "selector": selector, "period": period, "races": int(len(subset)),
                "hits": hits, "hit_rate_pct": 100 * hits / len(subset),
                "mean_paid_qpl_odds_on_hits": float(paid_odds / hits) if hits else None,
                "sum_paid_qpl_odds": float(paid_odds), "stake_krw": stake,
                "return_krw": returned, "net_profit_krw": returned - stake,
                "recovery_rate_pct": 100 * returned / stake,
                "roi_pct": 100 * (returned - stake) / stake,
            })
    summary = pd.DataFrame(summary_rows)

    method_by_race = {
        (row.selector, row.race_id): row for row in returns.itertuples(index=False)
    }
    comparisons = {
        "jockey_basic_candidate": "jockey_basic_candidate",
        "expanded_candidate": "expanded_candidate",
        "joint_marginal_top2": "joint_marginal_top2",
        "candidate_joint_maxpair": "candidate_joint_maxpair",
        "matched_joint_maxpair": "matched_joint_maxpair",
    }
    diagnostic_rows = []
    for comparator, name in comparisons.items():
        changed = []
        for race_id in sorted(common_races):
            current = method_by_race[("jockey_id_candidate", race_id)]
            other = method_by_race[(name, race_id)]
            if current.selected_pair == other.selected_pair:
                continue
            changed.append({
                "race_id": race_id, "current_pair": current.selected_pair,
                "comparator_pair": other.selected_pair,
                "current_hit": int(current.hit), "comparator_hit": int(other.hit),
                "current_paid_odds": float(current.paid_qpl_odds),
                "comparator_paid_odds": float(other.paid_qpl_odds),
                "current_return_krw": int(current.return_krw),
                "comparator_return_krw": int(other.return_krw),
                "delta_return_krw": int(current.return_krw) - int(other.return_krw),
            })
        ranked = sorted(changed, key=lambda x: (-abs(x["delta_return_krw"]), x["race_id"]))[:3]
        current_return = sum(x["current_return_krw"] for x in changed)
        comparator_return = sum(x["comparator_return_krw"] for x in changed)
        record = {
            "comparator": comparator, "changed_races": len(changed),
            "current_hits_on_changed": sum(x["current_hit"] for x in changed),
            "comparator_hits_on_changed": sum(x["comparator_hit"] for x in changed),
            "current_return_on_changed_krw": current_return,
            "comparator_return_on_changed_krw": comparator_return,
            "current_minus_comparator_net_krw": current_return - comparator_return,
        }
        for index in range(3):
            prefix = f"top{index + 1}_"
            if index < len(ranked):
                row = ranked[index]
                record.update({prefix + "race_id": row["race_id"], prefix + "current_pair": row["current_pair"],
                               prefix + "comparator_pair": row["comparator_pair"],
                               prefix + "current_paid_odds": row["current_paid_odds"],
                               prefix + "comparator_paid_odds": row["comparator_paid_odds"],
                               prefix + "delta_return_krw": row["delta_return_krw"]})
            else:
                record.update({prefix + field: None for field in
                               ("race_id", "current_pair", "comparator_pair", "current_paid_odds",
                                "comparator_paid_odds", "delta_return_krw")})
        diagnostic_rows.append(record)
    diagnostics = pd.DataFrame(diagnostic_rows)

    returns.to_csv(STUDY / "race_returns.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    summary.to_csv(STUDY / "summary.csv", index=False)
    diagnostics.to_csv(STUDY / "comparison_diagnostics.csv", index=False)

    audit_reference = pd.read_csv(AUDIT / "race_payouts.csv").set_index("race_id")
    current = returns.loc[returns["selector"].eq("jockey_id_candidate")].set_index("race_id")
    current_hits = current.loc[current["hit"].eq(1)]
    ref = audit_reference.loc[current_hits.index]
    require(len(current_hits) == 283, "current covered hit count changed")
    require(all(math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-8)
                for a, b in zip(current_hits["paid_qpl_odds"], ref["selected_qpl_dividend"])),
            "current QPL payout differs from the prior API301 audit")
    target_qpl_pages = sorted({h for h in returns.loc[returns["hit"].eq(1), "qpl_source_page_sha256"] if h})
    db_extract_hash = stable_json_sha256({"quotes": quote_rows, "official_results": official_extract})
    source_files = {
        "prediction_parquet": {"path": str(PAIR_FILE.relative_to(ROOT)), "sha256": PAIR_SHA256},
        "prediction_receipt": {"path": "jeju/research/20261012_pair_jockey_id_v1/outputs/PREDICTION_RECEIPT.json",
                               "sha256": file_sha256(PAIR_FILE.parent / "PREDICTION_RECEIPT.json")},
        "payout_audit_code": {"path": str(AUDIT_ANALYZE.relative_to(ROOT)), "sha256": AUDIT_ANALYZE_SHA256},
        "payout_audit_report": {"path": "jeju/research/20261013_pair_payout_audit_v1/REPORT.json",
                                 "sha256": file_sha256(AUDIT / "REPORT.json")},
        "payout_audit_source_hashes": {"path": "jeju/research/20261013_pair_payout_audit_v1/SOURCE_HASHES.json",
                                       "sha256": file_sha256(AUDIT / "SOURCE_HASHES.json")},
        "payout_audit_page_index": {"path": "jeju/research/20261013_pair_payout_audit_v1/SOURCE_PAGE_INDEX.json",
                                    "sha256": file_sha256(AUDIT / "SOURCE_PAGE_INDEX.json")},
        "payout_audit_race_rows": {"path": "jeju/research/20261013_pair_payout_audit_v1/race_payouts.csv",
                                   "sha256": file_sha256(AUDIT / "race_payouts.csv")},
        "sqlite_relevant_extract": {"path": str(DB_FILE.relative_to(ROOT)), "sha256": db_extract_hash,
                                    "definition": "SHA-256 of sorted target-race QPL quote rows and official-result rows"},
    }
    output_hashes = {
        filename: file_sha256(STUDY / filename)
        for filename in ("race_returns.csv", "summary.csv", "comparison_diagnostics.csv")
    }
    (STUDY / "SOURCE_HASHES.json").write_text(json.dumps({
        "files": source_files,
        "outputs_sha256": output_hashes,
        "api301_qpl_source_pages": {"unique_page_sha256_count": len(target_qpl_pages),
                                    "sha256s": target_qpl_pages},
        "read_only": {"sqlite_uri_mode": "ro", "query_only": True, "network": False,
                      "model_fit": False, "database_write": False},
    }, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    report = {
        "study": "20261013_pair_qpl_roi_v1",
        "cohort": {"races": 1142, "years": {"2025": 654, "2026_partial_through_2026-09-19": 488},
                   "payout_supported_races_only": True, "equal_races_per_selector": True},
        "stake": {"krw_per_race_and_selector": STAKE_KRW, "total_krw_per_selector": 11_420_000},
        "full_evaluation_hit_counts": full_hits,
        "same_denominator_summary": summary.loc[summary["period"].eq("2025-2026")].to_dict(orient="records"),
        "year_summary": summary.loc[~summary["period"].eq("2025-2026")].to_dict(orient="records"),
        "comparison_diagnostics": diagnostics.to_dict(orient="records"),
        "result_checks": {"official_top3_exactly_three_no_dead_heats": True,
                          "all_selector_labels_match_official_results": True,
                          "selected_qpl_quotes_present": True,
                          "every_hit_qpl_matches_api301_and_db": True,
                          "current_hit_payouts_match_prior_audit": True,
                          "current_hit_rows_compared_with_prior_audit": len(current_hits),
                          "distinct_api301_qpl_winning_pages": len(target_qpl_pages)},
        "return_definition": "Each selector buys one QPL pair per covered race for 10,000 KRW. Only an official Top3 pair is paid; misses return 0. ROI=(total return-total stake)/total stake.",
        "limitations": ["2024 is excluded because verified local QPL final payout coverage is unavailable.",
                        "2026 is a partial year through 2026-09-19.",
                        "This is a retrospective equal-stake accounting of frozen selections, not a prospective betting policy or a forecast of future returns.",
                        "Market odds were not prediction inputs; no model was fitted or changed."],
    }
    (STUDY / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                      encoding="utf-8")
    print(json.dumps({"output": str(STUDY), "cohort": report["cohort"],
                      "same_denominator_summary": report["same_denominator_summary"],
                      "comparison_diagnostics": report["comparison_diagnostics"],
                      "result_checks": report["result_checks"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

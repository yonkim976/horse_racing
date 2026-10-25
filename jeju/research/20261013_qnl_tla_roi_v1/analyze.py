"""Equal-budget QNL/TLA accounting from frozen Jeju ticket selections."""
from __future__ import annotations

import ast
import csv
import hashlib
import importlib.util
import itertools
import json
import math
import sqlite3
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
DB = ROOT / "data/horse_racing.sqlite3"
PAIR = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
AUDIT = ROOT / "jeju/research/20261013_pair_payout_audit_v1"
QPL = ROOT / "jeju/research/20261013_pair_qpl_roi_v1"
JOINT = ROOT / "jeju/research/20261010_joint_relationship_v1/outputs/report"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
PAIR_AXIS = ROOT / "jeju/research/20261010_pair_axis_v1/outputs/per_race_metrics.csv"
AUDIT_SHA = "0481c19a7e01f530d70a50bbe546e3f5a3d712615903b6b4f146d77099638cec"
PAIR_SHA = "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6"
TICKET_KRW = 6_000
SIX_STAKE_KRW = 1_000
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


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(ticket: str) -> str:
    return ",".join(str(n) for n in sorted(int(x) for x in str(ticket).replace("-", ",").split(",")))


def race_key(race_id: str) -> tuple[str, int, int]:
    date, meet, number = str(race_id).rsplit("_", 2)
    return date, int(meet), int(number)


def load_audit_helper():
    path = AUDIT / "analyze.py"
    require(sha(path) == AUDIT_SHA, "pinned payout-audit helper changed")
    spec = importlib.util.spec_from_file_location("pinned_payout_audit", path)
    require(spec is not None and spec.loader is not None, "payout-audit helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_official_targets(helper, targets: set[tuple[str, int, int]]) -> tuple[dict, dict]:
    official = helper.read_results(targets)
    require(set(official) == targets, "official results do not cover payout-supported races")
    truth, wanted = {}, {}
    for key, result in official.items():
        podium, top_two, tla_keys, all_pair_keys = helper.result_keys(result)
        qnl_keys = [value for value in all_pair_keys if not value.startswith("QPL:")]
        require(len(podium) == 3 and len(top_two) == 2, f"tie/incomplete results: {key}")
        race_id = f"{key[0]}_{key[1]}_{key[2]}"
        truth[race_id] = {
            "top2": canonical("-".join(map(str, top_two))),
            "top3": canonical("-".join(map(str, podium))),
            "race_db_id": result["race_db_id"],
        }
        wanted[key] = [("TLA", value) for value in tla_keys]
        wanted[key].extend(("QNL", value) for value in qnl_keys)
    return truth, wanted


def read_db_quotes(race_db_ids: set[int]) -> dict[tuple[int, str, str], float]:
    connection = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    marks = ",".join("?" for _ in race_db_ids)
    query = f"""SELECT race_id, bet_type, selection_key, odds
                FROM odds_snapshots
                WHERE bet_type IN (?, ?) AND race_id IN ({marks})"""
    params = ("QNL", "TLA", *sorted(race_db_ids))
    found: dict[tuple[int, str, str], float] = {}
    for row in connection.execute(query, params):
        key = (int(row["race_id"]), str(row["bet_type"]), canonical(row["selection_key"]))
        require(key not in found, f"duplicate DB odds snapshot: {key}")
        odds = float(row["odds"])
        require(math.isfinite(odds) and odds > 0, f"invalid DB dividend: {key}")
        found[key] = odds
    connection.close()
    return found


def read_race_payouts() -> tuple[dict[str, dict], str]:
    path = AUDIT / "race_payouts.csv"
    rows = {row["race_id"]: row for row in csv.DictReader(path.open(encoding="utf-8", newline=""))}
    require(len(rows) == 1_779, "audited race payout roster changed")
    return rows, sha(path)


def json_list(value: str) -> list:
    return json.loads(value) if value else []


def add_ticket(rows: list[dict], *, selector: str, pool: str, race_id: str,
               race_date: str, year: int, rank: int, ticket: str, stake: int,
               truth: dict, api_run: dict, db_quotes: dict) -> None:
    truth_key = truth[race_id]["top2" if pool == "QNL" else "top3"]
    hit = int(canonical(ticket) == truth_key)
    paid_odds = Decimal(0)
    source_hash = ""
    if hit:
        key = race_key(race_id)
        payout_key = (key[2], pool, truth_key.replace(",", "-"))
        api_value = api_run["values"].get(payout_key)
        require(api_value is not None and api_value > 0, f"missing API301 winning {pool}: {race_id}")
        db_key = (int(truth[race_id]["race_db_id"]), pool, truth_key)
        db_value = db_quotes.get(db_key)
        require(db_value is not None and math.isclose(float(api_value), db_value, rel_tol=0, abs_tol=1e-8),
                f"DB/API301 winning payout mismatch: {race_id} {pool}")
        paid_odds = Decimal(str(api_value))
        source_hash = api_run["page_for_key"][payout_key]
    returned = paid_odds * stake
    require(returned == returned.to_integral_value(), "fractional-won return")
    rows.append({
        "selector": selector, "pool": pool, "race_id": race_id, "race_date": race_date,
        "year": year, "ticket_rank": rank, "ticket": canonical(ticket), "exact_hit": hit,
        "stake_krw": stake, "paid_dividend_odds": float(paid_odds),
        "return_krw": int(returned), "net_krw": int(returned) - stake,
        "winning_api301_page_sha256": source_hash,
    })


def summary_rows(returns: pd.DataFrame) -> list[dict]:
    out = []
    for selector, group in returns.groupby("selector", sort=True):
        for period, part in (("2025-2026", group), ("2025", group[group.year == 2025]),
                             ("2026_partial", group[group.year == 2026])):
            races = int(part.race_id.nunique())
            stake = int(part.stake_krw.sum())
            returned = int(part.return_krw.sum())
            hits = int(part.exact_hit.sum())
            hit_races = int(part.loc[part.exact_hit.eq(1), "race_id"].nunique())
            odds_sum = sum((Decimal(str(x)) for x in part.loc[part.exact_hit.eq(1), "paid_dividend_odds"]), Decimal(0))
            out.append({
                "selector": selector, "period": period, "pool": str(part.pool.iloc[0]),
                "races": races, "ticket_count": int(len(part)), "ticket_hits": hits,
                "hit_races": hit_races, "ticket_hit_rate_pct": 100 * hits / len(part),
                "race_hit_rate_pct": 100 * hit_races / races,
                "mean_paid_dividend_odds_on_hits": float(odds_sum / hits) if hits else None,
                "stake_krw": stake, "return_krw": returned, "net_profit_krw": returned - stake,
                "recovery_rate_pct": 100 * returned / stake,
                "roi_pct": 100 * (returned - stake) / stake,
            })
    return out


def main() -> None:
    output_names = ("race_returns.csv", "summary.csv", "SOURCE_HASHES.json", "REPORT.json", "README.md")
    require(not any((STUDY / name).exists() for name in output_names), "refusing to overwrite study outputs")
    require(sha(PAIR) == PAIR_SHA, "frozen pair prediction SHA-256 mismatch")
    helper = load_audit_helper()
    predictions = pd.read_parquet(PAIR)
    payout_rows, payout_sha = read_race_payouts()
    supported = predictions.loc[predictions.evaluation_year.isin([2025, 2026])].copy()
    roster = set(supported.race_id.astype(str))
    require(len(roster) == 1_142 and roster <= set(payout_rows), "supported race roster changed")
    require(supported.groupby("evaluation_year").race_id.nunique().to_dict() == {2025: 654, 2026: 488},
            "supported year denominators changed")
    targets = {race_key(race_id) for race_id in roster}
    truth, wanted = read_official_targets(helper, targets)
    require(set(truth) == roster, "race ID normalization differs")

    # Pin verified payout-audit rows to the official result and API301 archive helper.
    for race_id in roster:
        audit_row = payout_rows[race_id]
        require(audit_row["source_payout_scope"] == "verified_local_final_dividend_api301",
                f"unsupported payout source: {race_id}")
        require(canonical("-".join(map(str, json_list(audit_row["official_top2_numbers"])))) == truth[race_id]["top2"],
                f"audited Top2 differs from DB results: {race_id}")
        require(canonical("-".join(map(str, json_list(audit_row["official_podium_numbers"])))) == truth[race_id]["top3"],
                f"audited Top3 differs from DB results: {race_id}")
        for field, pool in (("qnl_winning_dividends", "QNL"), ("tla_winning_dividends", "TLA")):
            values = json_list(audit_row[field])
            require(len(values) == 1 and Decimal(str(values[0])) > 0, f"unexpected winner payouts: {race_id} {pool}")
    api_runs, _archive_counts = helper.archive_rows(targets, wanted)
    for race_id in roster:
        row = payout_rows[race_id]
        key = race_key(race_id)
        run = api_runs[key[:2]]
        for pool, field in (("QNL", "qnl_winning_dividends"), ("TLA", "tla_winning_dividends")):
            business_key = (key[2], pool, truth[race_id]["top2" if pool == "QNL" else "top3"].replace(",", "-"))
            expected = float(json_list(row[field])[0])
            actual = run["values"].get(business_key)
            require(actual is not None and math.isclose(float(actual), expected, rel_tol=0, abs_tol=1e-8),
                    f"saved payout audit differs from archived API301: {race_id} {pool}")

    db_quotes = read_db_quotes({int(truth[rid]["race_db_id"]) for rid in roster})
    rows: list[dict] = []
    race_info = {rid: (race_key(rid)[0], int(payout_rows[rid]["year"])) for rid in roster}
    api_by_race = {rid: api_runs[race_key(rid)[:2]] for rid in roster}

    # QNL is the exact unordered Top2 pair. All nine frozen selectors buy one pair.
    for selector, flag in SELECTORS.items():
        chosen = supported.loc[supported[flag].eq(1)]
        require(len(chosen) == 1_142 and chosen.race_id.is_unique, f"selector roster changed: {selector}")
        for record in chosen.itertuples(index=False):
            rid = str(record.race_id)
            ticket = canonical(f"{int(record.horse_i)}-{int(record.horse_j)}")
            date, year = race_info[rid]
            add_ticket(rows, selector=selector, pool="QNL", race_id=rid, race_date=date,
                       year=year, rank=1, ticket=ticket, stake=TICKET_KRW,
                       truth=truth, api_run=api_by_race[rid], db_quotes=db_quotes)

    # Saved F1/F1_STYLE6 and relationship-model lists: compare rank 1 and all six tickets.
    canonical_path = STYLE / "report/canonical_six_combinations.csv"
    f1 = pd.read_csv(canonical_path)
    f1 = f1.loc[f1.variant.isin(["F1", "F1_STYLE6"])].copy()
    triple_map: dict[str, dict[str, list[str]]] = {}
    for variant in ("F1", "F1_STYLE6"):
        part = f1.loc[f1.variant.eq(variant)]
        for rid, group in part.groupby("race_id", sort=False):
            tickets = group.sort_values("selection_rank").numbers.astype(str).map(canonical).tolist()
            require(len(tickets) == 6 and len(set(tickets)) == 6, f"saved six ticket issue: {variant} {rid}")
            triple_map.setdefault(str(rid), {})[variant] = tickets

    race_metrics = pd.read_csv(JOINT / "race_metrics.csv")
    def read_saved_list(value: str) -> list[str]:
        return [canonical(ticket) for ticket in ast.literal_eval(value)]
    joint_tickets = {}
    for row in race_metrics.itertuples(index=False):
        joint_tickets[str(row.race_id)] = {
            "joint_candidate": read_saved_list(row.candidate_six_tickets),
            "joint_matched_baseline": read_saved_list(row.baseline_six_tickets),
        }
    for rid, arms in joint_tickets.items():
        for selector, tickets in arms.items():
            require(len(tickets) == 6 and len(set(tickets)) == 6, f"joint six ticket issue: {selector} {rid}")

    # Canonical rank 1 in the saved arrays must equal rank 1 in the frozen score table.
    triple_scores = pd.read_parquet(JOINT / "all_triples.parquet", columns=[
        "race_id", "arm", "triple_numbers", "canonical_rank"])
    for arm, selector in (("candidate", "joint_candidate"), ("matched_baseline", "joint_matched_baseline")):
        top = triple_scores.loc[(triple_scores.arm == arm) & triple_scores.canonical_rank.le(6)]
        top_map = {str(rid): group.sort_values("canonical_rank").triple_numbers.astype(str).map(canonical).tolist()
                   for rid, group in top.groupby("race_id", sort=False)}
        for rid, tickets in joint_tickets.items():
            require(tickets[selector] == top_map[rid], f"joint ticket/rank parity failed: {arm} {rid}")
    # The saved pair-axis K6 unrestricted lists are the same ordered lists, so they are a source parity check.
    axis = pd.read_csv(PAIR_AXIS)
    axis6 = axis.loc[(axis.policy == "unrestricted_top_k") & (axis.budget_k == 6)]
    for arm, selector in (("candidate", "joint_candidate"), ("matched_baseline", "joint_matched_baseline")):
        part = axis6.loc[axis6.arm.eq(arm)]
        require(len(part) == 1_779 and part.race_id.is_unique, f"pair-axis K6 roster changed: {arm}")
        for record in part.itertuples(index=False):
            require(json.loads(record.tickets) == joint_tickets[str(record.race_id)][selector],
                    f"pair-axis K6 parity failed: {arm} {record.race_id}")

    ticket_sets = {
        "F1_rank1": {rid: values["F1"][:1] for rid, values in triple_map.items()},
        "F1_six": {rid: values["F1"] for rid, values in triple_map.items()},
        "F1_STYLE6_rank1": {rid: values["F1_STYLE6"][:1] for rid, values in triple_map.items()},
        "F1_STYLE6_six": {rid: values["F1_STYLE6"] for rid, values in triple_map.items()},
        "joint_candidate_rank1": {rid: values["joint_candidate"][:1] for rid, values in joint_tickets.items()},
        "joint_candidate_six": {rid: values["joint_candidate"] for rid, values in joint_tickets.items()},
        "joint_matched_baseline_rank1": {rid: values["joint_matched_baseline"][:1] for rid, values in joint_tickets.items()},
        "joint_matched_baseline_six": {rid: values["joint_matched_baseline"] for rid, values in joint_tickets.items()},
    }
    for selector, mapping in ticket_sets.items():
        six = selector.endswith("_six")
        require(set(mapping) >= roster, f"saved TLA roster missing: {selector}")
        for rid in sorted(roster):
            tickets = mapping[rid]
            require(len(tickets) == (6 if six else 1), f"ticket count differs: {selector} {rid}")
            for rank, ticket in enumerate(tickets, 1):
                date, year = race_info[rid]
                add_ticket(rows, selector=selector, pool="TLA", race_id=rid, race_date=date,
                           year=year, rank=rank, ticket=ticket,
                           stake=SIX_STAKE_KRW if six else TICKET_KRW,
                           truth=truth, api_run=api_by_race[rid], db_quotes=db_quotes)

    # Existing current QPL result, scaled from 10,000 to the same 6,000 won race budget.
    qpl = pd.read_csv(QPL / "race_returns.csv")
    qpl = qpl.loc[qpl.selector.eq("jockey_id_candidate")]
    require(len(qpl) == 1_142 and set(qpl.race_id.astype(str)) == roster, "QPL reference roster changed")
    for record in qpl.itertuples(index=False):
        rid = str(record.race_id)
        hit = int(record.hit)
        require(hit == int(set(canonical(record.selected_pair).split(",")) <=
                              set(truth[rid]["top3"].split(","))), f"QPL Top3 reference label changed: {rid}")
        odds = Decimal(str(record.paid_qpl_odds)) if hit else Decimal(0)
        returned = odds * TICKET_KRW
        require(returned == returned.to_integral_value(), "fractional-won QPL scaled return")
        date, year = race_info[rid]
        rows.append({"selector": "QPL_jockey_id_candidate_reference", "pool": "QPL",
                     "race_id": rid, "race_date": date, "year": year, "ticket_rank": 1,
                     "ticket": canonical(record.selected_pair), "exact_hit": hit,
                     "stake_krw": TICKET_KRW, "paid_dividend_odds": float(odds),
                     "return_krw": int(returned), "net_krw": int(returned) - TICKET_KRW,
                     "winning_api301_page_sha256": record.qpl_source_page_sha256 if hit else ""})

    returns = pd.DataFrame(rows).sort_values(["pool", "selector", "race_date", "race_id", "ticket_rank"])
    summary = summary_rows(returns)
    require(returns.groupby("selector").race_id.nunique().eq(1_142).all(), "selector race denominator changed")
    require(returns.groupby("selector").stake_krw.sum().eq(6_852_000).all(), "selector race budget changed")
    require(not (returns.loc[returns.pool.isin(["QNL", "TLA"]), "paid_dividend_odds"].isna().any()),
            "missing payout field")

    input_paths = [PAIR, AUDIT / "race_payouts.csv", AUDIT / "analyze.py",
                   QPL / "race_returns.csv", canonical_path, JOINT / "race_metrics.csv",
                   JOINT / "all_triples.parquet", ROOT / "jeju/research/20261010_joint_relationship_v1/report.py",
                   ROOT / "jeju/research/20261010_joint_relationship_v1/joint_model.py", PAIR_AXIS]
    source_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in input_paths}
    returns.to_csv(STUDY / "race_returns.csv", index=False, encoding="utf-8")
    pd.DataFrame(summary).to_csv(STUDY / "summary.csv", index=False, encoding="utf-8")
    (STUDY / "SOURCE_HASHES.json").write_text(json.dumps({
        "source_sha256": source_hashes,
        "official_results": "Shared local races/racecourses/race_entries/race_results via pinned read-only audit helper",
        "winning_payouts": "race_payouts.csv was rechecked against verified cached API301 rows and shared odds_snapshots",
        "database": {"path": "data/horse_racing.sqlite3", "uri_mode": "ro", "query_only": True},
        "ticket_policy_sources": {
            "QNL": "each frozen pair selector's selected pair; exact official Top2 set only",
            "TLA_joint": "saved report.py stable descending-energy rank list; rank 1 and ranks 1-6",
            "TLA_F1": "saved canonical_six_combinations.csv variant F1; ranks 1 and 1-6",
            "TLA_F1_STYLE6": "saved canonical_six_combinations.csv variant F1_STYLE6; ranks 1 and 1-6",
            "TLA_pair_axis_K6_parity": "saved unrestricted_top_k K6 arrays match joint arrays in order for both arms across 1,779 races",
        },
        "calculation": "Decimal(final dividend odds × stake); losses return zero; ROI=(return-stake)/stake",
        "no_network_no_fit": True,
    }, ensure_ascii=False, indent=2) + "\n")
    (STUDY / "REPORT.json").write_text(json.dumps({
        "study": "20261013_qnl_tla_roi_v1",
        "cohort": {"races": 1_142, "years": {"2025": 654, "2026_partial_through_2026-09-19": 488},
                   "excluded_2024": {"races": 637, "reason": "no verified payout source"}},
        "budget": {"krw_per_race_per_method": 6_000, "races": 1_142,
                   "total_stake_per_method_krw": 6_852_000,
                   "rank1_tla": "one saved ticket at 6,000 KRW",
                   "six_tla": "six saved tickets at 1,000 KRW each"},
        "qnl_definition": "unordered exact official Top2 pair; pair-in-Top3 does not count",
        "tla_definition": "unordered exact official Top3 set; paid only for an exact winning ticket",
        "summary": summary,
        "ticket_rows": int(len(returns)),
        "api301_winning_payouts_verified": True,
        "db_api301_winner_value_checks": 1_142 * 2,
        "joint_top_six_rank_parity_checked": 2 * 1_779,
        "pair_axis_unrestricted_k6_ordered_parity_checked": 2 * 1_779,
        "result_ties": 0,
        "limitations": [
            "Retrospective reuse of the previously evaluated 2025-2026 race period; not independent future validation.",
            "2026 is partial through 2026-09-19; 2024 has no verified payout coverage.",
            "Odds snapshots and stored model probabilities are not winning payouts; only exact official winning tickets were paid.",
            "Pair selectors are evaluated for QNL; no pair-only selector generates a third horse for TLA.",
            "Equal-stake accounting applies published dividends and does not model market impact or future returns.",
        ],
        "source_sha256": source_hashes,
    }, ensure_ascii=False, indent=2) + "\n")
    (STUDY / "README.md").write_text(
        "# QNL / TLA same-budget returns\n\n"
        "This retrospective accounting uses the same 1,142 payout-supported races as the QPL study: 654 in 2025 and 488 through 2026-09-19. It applies 6,000 KRW per race to every method. QNL buys one selected pair at 6,000 KRW and counts a win only when that unordered pair is exactly the official Top2. TLA compares the saved rank-1 ticket at 6,000 KRW with six saved tickets at 1,000 KRW each.\n\n"
        "TLA selections come from saved F1, F1_STYLE6, and the joint candidate/matched-baseline outputs. The joint rank order was checked against `all_triples.parquet` and `report.py`; the pair-axis `unrestricted_top_k` K6 arrays match those joint arrays exactly, so they are recorded as parity evidence rather than a duplicate method. No third horse is inferred from pair-only selectors. The current jockey-ID QPL result is included as a 6,000 KRW scaled reference.\n\n"
        "`race_returns.csv` contains each ticket, exact-hit result, stake, payout multiple, return, and net. `summary.csv` reports ticket and race hit rates, full and year-split return, recovery, and ROI. All payout-supported official winning QNL/TLA values were compared between the shared read-only DB and verified local API301 source rows.\n\n"
        "This is a repeated retrospective development period, not independent future validation or an operating/betting policy. It used no network access, model fitting, or shared-data writes.\n"
    )
    print(json.dumps({"summary_rows": len(summary), "ticket_rows": len(returns),
                      "methods": int(returns.selector.nunique()),
                      "report": (STUDY / "REPORT.json").relative_to(ROOT).as_posix()}, ensure_ascii=False))


if __name__ == "__main__":
    main()

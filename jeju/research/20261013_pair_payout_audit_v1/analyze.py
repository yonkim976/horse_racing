"""Read-only payout audit for the frozen Jeju pair Top3 evaluation."""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import math
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261013_pair_payout_audit_v1"
PAIR_FILE = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
PREDICTION_RECEIPT = PAIR_FILE.parent / "PREDICTION_RECEIPT.json"
TLA_REFERENCE = ROOT / "reports/2026_trio_dividend_stats/winning_dividends_20260101_20261002.csv"
DIVIDEND_ARCHIVE = ROOT / "data/research/dividend_backfill_20261002_verified"
DB_FILE = ROOT / "data/horse_racing.sqlite3"
ENDPOINT = "/API301/Dividend_rate_total"
MEET = 2
POOLS = {"TLA", "QNL", "QPL"}
sys.path.insert(0, str(ROOT / "src"))
from horse_racing.collectors.kra_api import response_body  # noqa: E402
from horse_racing.parsers.horse_history import parse_meet_code  # noqa: E402
from horse_racing.parsers.race_day import FinalDividendItem, parse_items  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical(key: str) -> str:
    return "-".join(str(int(part)) for part in key.split("-") if part)


def race_key(race_id: str) -> tuple[str, int, int]:
    date, meet, number = str(race_id).rsplit("_", 2)
    return date, int(meet), int(number)


def read_results(targets: set[tuple[str, int, int]]) -> dict[tuple[str, int, int], dict]:
    connection = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    results: dict[tuple[str, int, int], dict] = {}
    rows = connection.execute(
        """SELECT r.race_date_local, c.kra_meet_code, r.race_number, r.id AS race_db_id,
                  e.horse_number, e.scratched, rr.finish_position, rr.disqualified
           FROM races r
           JOIN racecourses c ON c.id = r.racecourse_id
           JOIN race_entries e ON e.race_id = r.id
           JOIN race_results rr ON rr.race_entry_id = e.id
           WHERE r.race_date_local BETWEEN ? AND ? AND c.kra_meet_code = ?
           ORDER BY r.race_date_local, r.race_number, e.horse_number""",
        (min(k[0] for k in targets), max(k[0] for k in targets), MEET),
    ).fetchall()
    connection.close()
    for row in rows:
        key = (str(row["race_date_local"]), int(row["kra_meet_code"]), int(row["race_number"]))
        if key not in targets:
            continue
        entry = results.setdefault(key, {"race_db_id": int(row["race_db_id"]), "runners": []})
        require(entry["race_db_id"] == int(row["race_db_id"]), "duplicate race business key")
        entry["runners"].append(
            {
                "horse_number": int(row["horse_number"]),
                "finish_position": row["finish_position"],
                "scratched": bool(row["scratched"]),
                "disqualified": bool(row["disqualified"]),
            }
        )
    return results


def result_keys(result: dict) -> tuple[list[int], list[int], list[str], list[str]]:
    placed = [
        r for r in result["runners"]
        if not r["scratched"] and not r["disqualified"]
        and r["finish_position"] is not None and 1 <= int(r["finish_position"]) <= 3
    ]
    podium = sorted({int(r["horse_number"]) for r in placed})
    top_two = sorted(
        {int(r["horse_number"]) for r in placed if int(r["finish_position"]) <= 2}
    )
    require(len(podium) >= 3 and len(top_two) >= 2, "incomplete official finish positions")
    tla = ["-".join(map(str, c)) for c in itertools.combinations(podium, 3)]
    qnl = ["-".join(map(str, c)) for c in itertools.combinations(top_two, 2)]
    qpl = ["-".join(map(str, c)) for c in itertools.combinations(podium, 2)]
    return podium, top_two, tla, qnl + ["QPL:" + k for k in qpl]


def tie_audit(result: dict) -> dict:
    placed = [
        r for r in result["runners"]
        if not r["scratched"] and not r["disqualified"]
        and r["finish_position"] is not None and 1 <= int(r["finish_position"]) <= 3
    ]
    ranks = [int(r["finish_position"]) for r in placed]
    top_two = [rank for rank in ranks if rank <= 2]
    return {
        "top3_runner_count": len(placed),
        "top2_runner_count": len(top_two),
        "top3_dead_heat_rank_count": sum(ranks.count(rank) - 1 for rank in set(ranks)),
        "top2_dead_heat_rank_count": sum(top_two.count(rank) - 1 for rank in set(top_two)),
    }


def archive_rows(targets: set[tuple[str, int, int]], wanted: dict) -> tuple[dict, dict]:
    """Read verified local source pages for target day/meet runs; never reads source_url."""
    connection = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    docs = connection.execute(
        """SELECT id, local_path, sha256, request_params_json, retrieved_at_ms
           FROM source_documents WHERE endpoint = ? ORDER BY retrieved_at_ms, id""",
        (ENDPOINT,),
    ).fetchall()
    connection.close()
    target_days = {(date, meet) for date, meet, _ in targets if meet == MEET}
    groups: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    archive_registry_rows = 0
    duplicate_registry_aliases = 0
    for doc_id, local_path, expected_hash, params_json, retrieved_at_ms in docs:
        params = json.loads(params_json)
        raw_date = str(params.get("rc_date", ""))
        date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else ""
        try:
            meet = int(params.get("meet"))
            page_no = int(params.get("pageNo"))
            page_size = int(params.get("numOfRows"))
        except (TypeError, ValueError):
            continue
        if (date, meet) not in target_days:
            continue
        archive_registry_rows += 1
        raw_path = Path(str(local_path))
        if not raw_path.is_absolute():
            raw_path = ROOT / raw_path
        require(not raw_path.is_symlink(), "source symlink is not allowed")
        path = raw_path.resolve()
        require(path.is_relative_to(ROOT) and path.is_file(), "unsafe source path")
        run_match = re.search(r"(?:^|/)run_([^/]+)(?:/|$)", str(local_path))
        if run_match is not None:
            run_id = run_match.group(1)
        else:
            archive_root = DIVIDEND_ARCHIVE.resolve()
            require(path.is_relative_to(archive_root), "unrecognized source path without run identity")
            require(page_no == 1 and page_size >= 20000, "unexpected verified-backfill paging")
            run_id = "verified-backfill"
        groups[(date, meet, run_id)].append(
            {
                "id": int(doc_id), "path": path, "relative_path": str(local_path),
                "expected_hash": str(expected_hash), "retrieved_at_ms": int(retrieved_at_ms),
                "page_no": page_no, "page_size": page_size,
            }
        )

    complete_runs: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for (date, meet, run_id), pages in groups.items():
        if meet != MEET:
            continue
        by_page: dict[int, dict] = {}
        for page in pages:
            existing = by_page.get(page["page_no"])
            if existing is None:
                by_page[page["page_no"]] = page
            else:
                require(
                    existing["expected_hash"] == page["expected_hash"]
                    and existing["retrieved_at_ms"] == page["retrieved_at_ms"]
                    and existing["page_size"] == page["page_size"]
                    and existing["path"] == page["path"],
                    "conflicting duplicate API301 source registry page",
                )
                duplicate_registry_aliases += 1
        pages = list(by_page.values())
        page_numbers = [p["page_no"] for p in pages]
        if len(page_numbers) != len(set(page_numbers)) or len({p["page_size"] for p in pages}) != 1:
            continue
        payloads, counts, total_counts, source_hashes = [], [], [], []
        valid = True
        for page in sorted(pages, key=lambda p: p["page_no"]):
            body_bytes = page["path"].read_bytes()
            actual_hash = hashlib.sha256(body_bytes).hexdigest()
            require(actual_hash == page["expected_hash"], "cached source SHA-256 mismatch")
            payload = json.loads(body_bytes)
            body = response_body(payload)
            try:
                total = int(body.get("totalCount") or 0)
            except (TypeError, ValueError):
                valid = False
                break
            items = parse_items(payload, FinalDividendItem)
            payloads.append((page, items, actual_hash))
            counts.append(len(items))
            total_counts.append(total)
            source_hashes.append(actual_hash)
        if not valid or not pages:
            continue
        total = total_counts[0]
        page_size = pages[0]["page_size"]
        required_pages = max(1, math.ceil(total / page_size))
        if (
            len(set(total_counts)) != 1
            or set(page_numbers) != set(range(1, required_pages + 1))
            or sum(counts) != total
        ):
            continue
        values: dict[tuple[int, str, str], float | None] = {}
        page_for_key: dict[tuple[int, str, str], str] = {}
        duplicate = False
        for page, items, page_hash in payloads:
            for item in items:
                if item.race_date.isoformat() != date or parse_meet_code(item.meet_name) != MEET:
                    continue
                pool = str(item.bet_type)
                key = canonical(item.selection_key)
                business_key = (int(item.race_number), pool, key)
                if business_key in values:
                    duplicate = True
                    break
                values[business_key] = None if item.odds is None else float(item.odds)
                page_for_key[business_key] = page_hash
            if duplicate:
                break
        if duplicate:
            continue
        complete_runs[(date, meet)].append(
            {
                "run_id": run_id, "retrieved_at_ms": max(p["retrieved_at_ms"] for p in pages),
                "page_count": len(pages), "total_rows": total, "values": values,
                "page_for_key": page_for_key, "hashes": source_hashes,
                "paths": [p["relative_path"] for p in sorted(pages, key=lambda p: p["page_no"])],
            }
        )
    chosen: dict[tuple[str, int], dict] = {}
    for day_key in target_days:
        choices = complete_runs.get(day_key, [])
        require(choices, f"no complete cached API301 source run for {day_key[0]}")
        choices.sort(key=lambda x: (x["retrieved_at_ms"], x["run_id"]))
        latest = choices[-1]
        for race_date, meet, race_no in (k for k in targets if k[:2] == day_key):
            for pool, winning_key in wanted[(race_date, meet, race_no)]:
                key = (race_no, pool, winning_key)
                if key in latest["values"]:
                    continue
                require(False, f"official result key absent from latest API301 source: {day_key[0]} {pool}")
        chosen[day_key] = {**latest, "complete_run_count": len(choices), "registry_rows_for_target_days": archive_registry_rows}
    return chosen, {
        "api301_registry_rows_for_target_days": archive_registry_rows,
        "duplicate_registry_alias_rows_collapsed": duplicate_registry_aliases,
        "complete_runs": sum(len(v) for v in complete_runs.values()),
    }


def valid_payout(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def stats(values: pd.Series) -> dict:
    x = pd.to_numeric(values, errors="coerce").dropna()
    if x.empty:
        return {"n": 0, "mean": None, "median": None, "p90": None}
    return {
        "n": int(x.size), "mean": float(x.mean()), "median": float(x.median()),
        "p90": float(x.quantile(0.9, interpolation="linear")),
    }


def main() -> None:
    require(STUDY.is_dir(), "study output directory missing")
    predictions = pd.read_parquet(PAIR_FILE)
    selected = predictions.loc[predictions["selected_jockey_id_candidate"].eq(1)].copy()
    require(len(selected) == 1779 and selected["race_id"].is_unique, "selected race roster changed")
    require(int(selected["y_pair"].sum()) == 438, "frozen hit count changed")
    selected["race_key"] = selected["race_id"].map(race_key)
    targets = set(selected["race_key"])
    require(all(meet == MEET for _, meet, _ in targets), "evaluation roster includes a non-Jeju meet")
    results = read_results(targets)
    require(set(results) == targets, "official results do not cover frozen evaluation roster")

    race_rows, wanted = [], defaultdict(list)
    for race_id, group in predictions.groupby("race_id", sort=True):
        chosen = group.loc[group["selected_jockey_id_candidate"].eq(1)]
        require(len(chosen) == 1, "selected pair count changed")
        row = chosen.iloc[0]
        key = race_key(race_id)
        result = results[key]
        podium, top_two, tla_keys, qnl_keys_plus = result_keys(result)
        tie_info = tie_audit(result)
        qnl_keys = [k for k in qnl_keys_plus if not k.startswith("QPL:")]
        qpl_keys = [k.removeprefix("QPL:") for k in qnl_keys_plus if k.startswith("QPL:")]
        positive = {
            canonical(f"{int(r.horse_i)}-{int(r.horse_j)}")
            for r in group.itertuples(index=False) if int(r.y_pair) == 1
        }
        expected_positive = {
            canonical(f"{a}-{b}") for a, b in itertools.combinations(podium, 2)
        }
        require(positive == expected_positive, f"pair labels differ from official podium: {race_id}")
        pair_key = canonical(f"{int(row.horse_i)}-{int(row.horse_j)}")
        hit = int(pair_key in positive)
        require(hit == int(row.y_pair), f"selected pair hit label mismatch: {race_id}")
        for pool, event_keys in (("TLA", tla_keys), ("QNL", qnl_keys)):
            wanted[key].extend((pool, event_key) for event_key in event_keys)
        if hit:
            wanted[key].append(("QPL", pair_key))
        race_rows.append(
            {
                "race_id": str(race_id), "race_date": key[0], "meet_code": key[1],
                "race_number": key[2], "year": int(row.evaluation_year),
                "pair_hit": hit, "selected_pair": pair_key,
                "official_podium_numbers": json.dumps(podium, separators=(",", ":")),
                "official_top2_numbers": json.dumps(top_two, separators=(",", ":")),
                "winning_tla_keys_expected": json.dumps(tla_keys, separators=(",", ":")),
                "winning_qnl_keys_expected": json.dumps(qnl_keys, separators=(",", ":")),
                "race_db_id": result["race_db_id"],
                **tie_info,
            }
        )

    # The saved 2026 whole-period receipt verifies API301 backfill against exact local
    # official source pages. API301 cached pages for each evaluation day/meet are parsed
    # read-only here to match the final winning keys and the selected QPL.
    for row in race_rows:
        key = (row["race_date"], row["meet_code"], row["race_number"])
        row["source_payout_scope"] = "unsupported" if row["year"] == 2024 else "pending"
        row["tla_winning_dividends"] = None
        row["qnl_winning_dividends"] = None
        row["tla_race_mean"] = None
        row["qnl_race_mean"] = None
        row["selected_qpl_dividend"] = None
        row["source_run_id"] = None
        row["source_run_pages"] = None
        row["source_sha256s"] = "[]"

    supported = {k for k in targets if k[0][:4] in {"2025", "2026"}}
    needed = {key: wanted[key] for key in supported}
    chosen, archive_summary = archive_rows(supported, needed)
    for row in race_rows:
        key = (row["race_date"], row["meet_code"], row["race_number"])
        if key not in supported:
            continue
        run = chosen[key[:2]]
        tla_keys = json.loads(row["winning_tla_keys_expected"])
        qnl_keys = json.loads(row["winning_qnl_keys_expected"])
        pool_values: dict[str, list[float]] = {"TLA": [], "QNL": []}
        used_hashes = set()
        for pool, keys in (("TLA", tla_keys), ("QNL", qnl_keys)):
            for winning_key in keys:
                business_key = (key[2], pool, winning_key)
                value = run["values"].get(business_key)
                require(valid_payout(value), f"missing/invalid official winning payout {pool} {row['race_id']}")
                pool_values[pool].append(float(value))
                used_hashes.add(run["page_for_key"][business_key])
        row["tla_winning_dividends"] = json.dumps(pool_values["TLA"], separators=(",", ":"))
        row["qnl_winning_dividends"] = json.dumps(pool_values["QNL"], separators=(",", ":"))
        row["tla_race_mean"] = float(sum(pool_values["TLA"]) / len(pool_values["TLA"]))
        row["qnl_race_mean"] = float(sum(pool_values["QNL"]) / len(pool_values["QNL"]))
        if row["pair_hit"]:
            pair_key = row["selected_pair"]
            business_key = (key[2], "QPL", pair_key)
            value = run["values"].get(business_key)
            require(valid_payout(value), f"missing/invalid winning selected QPL payout {row['race_id']}")
            row["selected_qpl_dividend"] = float(value)
            used_hashes.add(run["page_for_key"][business_key])
        row["source_payout_scope"] = "verified_local_final_dividend_api301"
        row["source_run_id"] = run["run_id"]
        row["source_run_pages"] = run["page_count"]
        row["source_sha256s"] = json.dumps(sorted(used_hashes), separators=(",", ":"))

    race_df = pd.DataFrame(race_rows).sort_values(["year", "race_date", "race_number"])
    require(race_df.loc[race_df["year"].eq(2024), "source_payout_scope"].eq("unsupported").all(), "2024 source handling changed")
    require(race_df.loc[race_df["year"].isin([2025, 2026]), "tla_race_mean"].notna().all(), "payout coverage incomplete")
    require(int(race_df.loc[race_df["year"].isin([2025, 2026]), "pair_hit"].sum()) == 283, "covered hit count changed")

    reference = pd.read_csv(TLA_REFERENCE)
    reference = reference.loc[reference["meet"].eq(MEET)].copy()
    reference["key"] = list(zip(reference["race_date_local"].astype(str), reference["meet"].astype(int), reference["race_number"].astype(int)))
    reference_by_key = {tuple(r["key"]): r for _, r in reference.iterrows()}
    comparisons = []
    for row in race_df.loc[race_df["year"].eq(2026)].itertuples(index=False):
        key = (row.race_date, row.meet_code, row.race_number)
        ref = reference_by_key.get(key)
        require(ref is not None, f"2026 TLA report missing {row.race_id}")
        ref_keys = [canonical(x) for x in ast.literal_eval(ref["keys"])]
        ref_values = [float(x) for x in ast.literal_eval(ref["winning_dividends"])]
        got_keys = json.loads(row.winning_tla_keys_expected)
        got_values = json.loads(row.tla_winning_dividends)
        require(sorted(zip(ref_keys, ref_values)) == sorted(zip(got_keys, got_values)), f"2026 TLA raw/CSV mismatch {row.race_id}")
        require(math.isclose(float(ref["dividend"]), float(row.tla_race_mean), rel_tol=0.0, abs_tol=1e-8), f"2026 TLA mean mismatch {row.race_id}")
        comparisons.append(row.race_id)
    require(len(comparisons) == 488, "2026 CSV cross-check roster changed")

    groups = []
    for year in (2024, 2025, 2026, "2025-2026"):
        subset = race_df.loc[race_df["year"].isin([2025, 2026])] if year == "2025-2026" else race_df.loc[race_df["year"].eq(year)]
        for outcome, part in (("hit", subset.loc[subset["pair_hit"].eq(1)]), ("miss", subset.loc[subset["pair_hit"].eq(0)])):
            record = {
                "year": year, "pair_outcome": outcome, "evaluation_races": int(len(part)),
                "evaluation_hits": int(part["pair_hit"].sum()),
                "payout_supported_races": int(part["tla_race_mean"].notna().sum()),
                "payout_coverage": float(part["tla_race_mean"].notna().mean()) if len(part) else None,
            }
            for metric in ("tla_race_mean", "qnl_race_mean", "selected_qpl_dividend"):
                record[metric] = stats(part[metric])
            groups.append(record)
    group_df = pd.DataFrame(groups)
    race_df.to_csv(STUDY / "race_payouts.csv", index=False)
    group_df.to_csv(STUDY / "group_stats.csv", index=False)

    input_hashes = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in (PAIR_FILE, PREDICTION_RECEIPT, TLA_REFERENCE,
                     DIVIDEND_ARCHIVE / "report.json", DIVIDEND_ARCHIVE / "verification.json")
    }
    source_hashes = {
        "input_sha256": input_hashes,
        "method": "read-only sqlite source_documents registry; verified local API301 cached response pages; per-race page hashes are in race_payouts.csv",
        "source_pages_used": int(sum(len(json.loads(v)) for v in race_df.loc[race_df["year"].isin([2025, 2026]), "source_sha256s"])),
        "source_pages_unique": int(len({h for value in race_df.loc[race_df["year"].isin([2025, 2026]), "source_sha256s"] for h in json.loads(value)})),
        "archive_receipt": json.loads((DIVIDEND_ARCHIVE / "verification.json").read_text())["databases"]["local"],
    }
    (STUDY / "SOURCE_HASHES.json").write_text(json.dumps(source_hashes, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    report = {
        "study": "20261013_pair_payout_audit_v1",
        "model_source": "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet",
        "cohort": {"races": int(len(race_df)), "years": {str(y): int(race_df["year"].eq(y).sum()) for y in (2024, 2025, 2026)}, "hits": int(race_df["pair_hit"].sum()), "misses": int((race_df["pair_hit"] == 0).sum())},
        "result_tie_audit": {
            "races_with_exact_three_top3_runners": int(race_df["top3_runner_count"].eq(3).sum()),
            "races_with_exact_two_top2_runners": int(race_df["top2_runner_count"].eq(2).sum()),
            "races_with_top3_dead_heat": int(race_df["top3_dead_heat_rank_count"].gt(0).sum()),
            "races_with_top2_dead_heat": int(race_df["top2_dead_heat_rank_count"].gt(0).sum()),
        },
        "source_coverage": {
            "2024": {"races": int(race_df["year"].eq(2024).sum()), "payout_supported": int(race_df.loc[race_df["year"].eq(2024), "tla_race_mean"].notna().sum()), "reason": "no eligible local final dividend source found for evaluation dates"},
            "2025": {"races": int(race_df["year"].eq(2025).sum()), "payout_supported": int(race_df.loc[race_df["year"].eq(2025), "tla_race_mean"].notna().sum())},
            "2026": {"races": int(race_df["year"].eq(2026).sum()), "payout_supported": int(race_df.loc[race_df["year"].eq(2026), "tla_race_mean"].notna().sum()), "tla_reference_csv_matched": len(comparisons)},
            "2025_2026": {"races": int(race_df["year"].isin([2025, 2026]).sum()), "hits": int(race_df.loc[race_df["year"].isin([2025, 2026]), "pair_hit"].sum()), "misses": int((race_df.loc[race_df["year"].isin([2025, 2026]), "pair_hit"] == 0).sum())},
        },
        "statistics": group_df.to_dict(orient="records"),
        "pool_definitions": {"TLA": "unordered top-three (trio) official winning dividend; race value is the mean across all valid winning combinations where applicable", "QNL": "unordered top-two (quinella) official winning dividend; a distinct top-two event", "QPL": "selected pair's exact quinella-place dividend, reported only when the selected pair is a Top3 hit"},
        "analysis_limits": ["2024 has no local verified dividend coverage, so no payout estimate is reported for that year.", "Missed selected pairs have no payout; no losing quote is treated as payout.", "Payout association is descriptive and retrospective; it does not show that model hits cause lower payouts or support a new betting policy."],
        "source_inventory": archive_summary,
        "csv_crosscheck": {"2026_evaluation_races": len(comparisons), "all_tla_keys_and_values_match": True},
        "read_only": {"sqlite_uri_mode": "ro", "query_only": True, "sqlite_tables": ["source_documents", "races", "racecourses", "race_entries", "race_results"], "network": False, "model_fit": False},
        "input_sha256": input_hashes,
    }
    (STUDY / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(STUDY), "cohort": report["cohort"], "source_coverage": report["source_coverage"], "group_stats": report["statistics"], "csv_crosscheck": report["csv_crosscheck"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

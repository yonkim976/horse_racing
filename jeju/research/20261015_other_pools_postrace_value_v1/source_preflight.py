"""Read-only full candidate-price source preflight for the other Jeju pools."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
PREVIOUS = ROOT / "jeju/research/20261015_operating_postrace_value_comparison_v1"
FREQUENCY = ROOT / "jeju/research/20261014_pool_dividend_frequency_v1"
OFFICIAL = ROOT / "jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv"
PAYOUT_HELPER = ROOT / "jeju/research/20261013_pair_payout_audit_v1/analyze.py"
POOLS = ("WIN", "QNL", "EXA", "TLA", "TRI")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_prior_helper():
    spec = importlib.util.spec_from_file_location("jeju_readonly_api301_helper", PAYOUT_HELPER)
    require(spec is not None and spec.loader is not None, "unable to load the existing read-only API301 helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_race_id(value: str) -> tuple[str, int, int]:
    date, meet, number = str(value).rsplit("_", 2)
    return date, int(meet), int(number)


def canonical_tuple(*values: Any) -> tuple[int, ...]:
    out = tuple(int(value) for value in values if value not in (None, "", 0, "0"))
    return out


def selection_key(pool: str, key: tuple[int, ...]) -> str:
    if pool in {"QNL", "TLA"}:
        key = tuple(sorted(key))
    return "-".join(str(number) for number in key)


def expected_keys(numbers: list[int]) -> dict[str, set[tuple[int, ...]]]:
    n = len(numbers)
    pairs_unordered = {tuple(combo) for combo in itertools.combinations(numbers, 2)}
    pairs_ordered = {(a, b) for a in numbers for b in numbers if a != b}
    triples_unordered = {tuple(combo) for combo in itertools.combinations(numbers, 3)}
    triples_ordered = {tuple(combo) for combo in itertools.permutations(numbers, 3)}
    result = {
        "WIN": {(number,) for number in numbers},
        "QNL": pairs_unordered,
        "EXA": pairs_ordered,
        "TLA": triples_unordered,
        "TRI": triples_ordered,
    }
    expected = {
        "WIN": n,
        "QNL": math.comb(n, 2),
        "EXA": n * (n - 1),
        "TLA": math.comb(n, 3),
        "TRI": n * (n - 1) * (n - 2),
    }
    require({pool: len(result[pool]) for pool in POOLS} == expected,
            "candidate key generator disagrees with closed-form pool counts")
    return result


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    require(STUDY.exists() and STUDY.is_dir(), "new study directory is missing")
    cohort = pd.read_csv(PREVIOUS / "cohort.csv", dtype={"race_id": "string", "race_date": "string"})
    eligible = cohort.loc[cohort.qpl_eligible.astype(bool)].copy()
    eligible["race_id"] = eligible.race_id.astype(str)
    require(len(eligible) == eligible.race_id.nunique() == 467, "previous matched common cohort changed")
    require(eligible.race_date.min() == "2026-01-02" and eligible.race_date.max() == "2026-09-12",
            "common cohort dates changed")

    # The prior operating comparison's HY runner table is already independently joined to the official IDs.
    runner_path = ROOT / "jeju/research/20261009_operating_model_comparison_v1/outputs/runner_predictions.parquet"
    runners = pd.read_parquet(runner_path, columns=["race_id", "race_date", "horse_id", "horse_number", "variant"])
    runners = runners.loc[runners.variant.eq("HY_R_FORM") & runners.race_id.astype(str).isin(set(eligible.race_id))].copy()
    runners["race_id"] = runners.race_id.astype(str)
    runners["horse_id"] = runners.horse_id.astype(str)
    runners["horse_number"] = pd.to_numeric(runners.horse_number, errors="raise").astype(int)
    require(runners.race_id.nunique() == 467 and len(runners) == 4475,
            "HY common runner roster count changed")
    require(not runners.duplicated(["race_id", "horse_id"]).any()
            and not runners.duplicated(["race_id", "horse_number"]).any(),
            "HY common runner IDs or numbers are duplicated")

    official = pd.read_csv(OFFICIAL, dtype={"race_id": "string", "race_date_local": "string", "kra_horse_id": "string"})
    official = official.loc[official.race_id.astype(str).isin(set(eligible.race_id))].copy()
    official["race_id"] = official.race_id.astype(str)
    for col in ["horse_number", "field_size", "scratched", "disqualified"]:
        official[col] = pd.to_numeric(official[col], errors="raise").astype(int)
    official["finish_position"] = pd.to_numeric(official.finish_position, errors="coerce")
    require(len(official) == 4475 and official.race_id.nunique() == 467,
            "official runner/result coverage differs from the matched cohort")
    require(official.status.eq("completed").all() and official.scratched.eq(0).all()
            and official.disqualified.eq(0).all(), "common official roster has scratch, DQ, or incomplete status")
    official_counts = official.groupby("race_id").size().rename("official_n")
    require(official.groupby("race_id").field_size.nunique().eq(1).all()
            and official.groupby("race_id").field_size.first().eq(official_counts).all(),
            "official field size differs from complete runner roster")
    op_counts = runners.groupby("race_id").size().rename("operating_n")
    eligible_counts = pd.to_numeric(eligible.set_index("race_id").operating_n, errors="raise").astype(int)
    require(op_counts.eq(official_counts).all()
            and eligible_counts.eq(op_counts).all(),
            "operating roster differs from official field size")
    roster = runners.merge(
        official[["race_id", "kra_horse_id", "horse_number"]],
        left_on=["race_id", "horse_id", "horse_number"],
        right_on=["race_id", "kra_horse_id", "horse_number"],
        how="outer", validate="one_to_one", indicator=True,
    )
    require(roster._merge.eq("both").all(), "operating HY horse identity/number differs from official result roster")

    # Exact unique Top1/Top2/Top3 results were audited for the same official source.
    top_counts = official.assign(
        top1=official.finish_position.eq(1),
        top2=official.finish_position.le(2),
        top3=official.finish_position.le(3),
    ).groupby("race_id")[["top1", "top2", "top3"]].sum()
    require(top_counts["top1"].eq(1).all() and top_counts["top2"].eq(2).all()
            and top_counts["top3"].eq(3).all(),
            "common official results include ties or missing podium ranks")

    expected_by_race: dict[str, dict[str, set[tuple[int, ...]]]] = {}
    target_tuples: set[tuple[str, int, int]] = set()
    wanted: dict[tuple[str, int, int], list[tuple[str, str]]] = {}
    expected_totals = {pool: 0 for pool in POOLS}
    candidate_count_by_race: dict[str, dict[str, int]] = {}
    for race_id, part in runners.groupby("race_id", sort=True):
        numbers = sorted(part.horse_number.astype(int).tolist())
        candidate_keys = expected_keys(numbers)
        expected_by_race[race_id] = candidate_keys
        candidate_count_by_race[race_id] = {pool: len(candidate_keys[pool]) for pool in POOLS}
        for pool in POOLS:
            expected_totals[pool] += len(candidate_keys[pool])
        date, meet, race_no = parse_race_id(race_id)
        require(meet == 2, "non-Jeju race included in fixed cohort")
        target = (date, meet, race_no)
        require(target not in target_tuples, "duplicate target day/meet/race key")
        target_tuples.add(target)
        wanted[target] = [
            (pool, selection_key(pool, key))
            for pool in POOLS for key in sorted(candidate_keys[pool])
        ]

    expected_aggregate = {"WIN": 4475, "QNL": 19388, "EXA": 38776, "TLA": 50017, "TRI": 300102}
    require(expected_totals == expected_aggregate,
            f"full 467-race candidate universe changed: {expected_totals}")

    helper = load_prior_helper()
    chosen, archive_summary = helper.archive_rows(target_tuples, wanted)
    require(len(chosen) == 70, "API301 latest-complete run coverage does not span all 70 cohort dates")
    page_index_path = FREQUENCY / "SOURCE_PAGE_INDEX.csv"
    page_index = pd.read_csv(page_index_path, dtype={"race_date": "string", "source_run_id": "string", "source_page_path": "string", "source_page_sha256": "string"})
    page_index = page_index.loc[page_index.race_date.isin(set(eligible.race_date))].copy()
    require(page_index.race_date.nunique() == 70 and len(page_index) == 242,
            "prior source page index does not cover the 70 cohort dates / 242 pages")

    page_rows: list[dict[str, Any]] = []
    quote_by_key: dict[tuple[str, str, tuple[int, ...]], dict[str, Any]] = {}
    per_race_pool: list[dict[str, Any]] = []
    raw_invalids: dict[str, int] = {pool: 0 for pool in POOLS}
    raw_sentinels: dict[str, int] = {pool: 0 for pool in POOLS}
    source_paths_by_sha: dict[str, str] = {}
    for (date, meet), run in sorted(chosen.items()):
        require(meet == 2, "wrong API301 meet")
        date_rows = page_index.loc[page_index.race_date.eq(date)].copy()
        require(set(date_rows.source_run_id.astype(str)) == {str(run["run_id"])},
                f"API301 source run disagrees with frozen page index: {date}")
        index_paths = set(date_rows.source_page_path.astype(str))
        require(index_paths == set(run["paths"]), f"API301 page paths disagree with frozen index: {date}")
        index_hashes = dict(zip(date_rows.source_page_path.astype(str), date_rows.source_page_sha256.astype(str)))
        require(len(index_hashes) == len(date_rows) and len(date_rows) == len(run["paths"]),
                f"duplicate/missing page index rows for {date}")
        require(all(index_hashes[path] == digest for path, digest in zip(run["paths"], run["hashes"])),
                f"API301 page hash differs from frozen index: {date}")

        for path_text, page_hash in zip(run["paths"], run["hashes"]):
            path = (ROOT / path_text).resolve()
            require(path.is_relative_to(ROOT) and not path.is_symlink() and path.is_file(),
                    "cached API301 path is unsafe or missing")
            actual_hash = sha(path)
            require(actual_hash == page_hash, f"actual cached API301 page hash mismatch: {path_text}")
            source_paths_by_sha[page_hash] = path_text
            page_rows.append({"race_date": date, "meet": meet, "source_run_id": str(run["run_id"]),
                              "source_page_path": path_text, "source_page_sha256": page_hash,
                              "page_bytes": path.stat().st_size})
            payload = json.loads(path.read_bytes())
            body = helper.response_body(payload)
            items = (body.get("items") or {}).get("item", [])
            if isinstance(items, dict):
                items = [items]
            require(isinstance(items, list), "API301 item collection has an unsupported schema")
            for item in items:
                if str(item.get("rcDate", "")) != date.replace("-", ""):
                    continue
                if helper.parse_meet_code(str(item.get("meet", ""))) != meet:
                    continue
                pool = str(item.get("pool", ""))
                if pool not in POOLS:
                    continue
                race_id = f"{date}_{meet}_{int(item.get('rcNo'))}"
                if race_id not in expected_by_race:
                    continue
                key = canonical_tuple(item.get("chulNo"), item.get("chulNo2"), item.get("chulNo3"))
                if pool in {"QNL", "TLA"}:
                    key = tuple(sorted(key))
                identity = (race_id, pool, key)
                require(identity not in quote_by_key, f"duplicate API301 candidate quote key: {identity}")
                raw_quote = item.get("odds")
                parsed_quote = None
                try:
                    parsed_quote = float(raw_quote) if raw_quote is not None and str(raw_quote).strip() else None
                except (TypeError, ValueError):
                    parsed_quote = None
                is_sentinel = parsed_quote == 9999.9
                is_valid = parsed_quote is not None and math.isfinite(parsed_quote) and parsed_quote > 0 and not is_sentinel
                if is_sentinel:
                    raw_sentinels[pool] += 1
                if not is_valid:
                    raw_invalids[pool] += 1
                quote_by_key[identity] = {
                    "race_id": race_id, "race_date": date, "pool": pool,
                    "selection_key": selection_key(pool, key), "selection_tuple": key,
                    "raw_odds": raw_quote, "parsed_odds": parsed_quote,
                    "quote_status": "sentinel_9999_9" if is_sentinel else ("valid" if is_valid else "invalid_raw_odds"),
                    "source_run_id": str(run["run_id"]), "source_page_path": path_text,
                    "source_page_sha256": page_hash,
                }

    require(len(page_rows) == 242 and len(source_paths_by_sha) == 242,
            "selected API301 page count/hash inventory changed")

    missing_by_pool = {pool: 0 for pool in POOLS}
    extra_by_pool = {pool: 0 for pool in POOLS}
    race_rows = []
    for race_id, race_pools in expected_by_race.items():
        for pool in POOLS:
            expected = race_pools[pool]
            observed = {key for (rid, p, key) in quote_by_key if rid == race_id and p == pool}
            missing = expected - observed
            extra = observed - expected
            missing_by_pool[pool] += len(missing)
            extra_by_pool[pool] += len(extra)
            sentinels = sum(quote_by_key[(race_id, pool, key)]["quote_status"] == "sentinel_9999_9"
                            for key in expected.intersection(observed))
            invalid = sum(quote_by_key[(race_id, pool, key)]["quote_status"] != "valid"
                          for key in expected.intersection(observed))
            race_rows.append({"race_id": race_id, "race_date": parse_race_id(race_id)[0], "pool": pool,
                              "field_n": len({n for key in expected for n in key}) if pool != "WIN" else len(expected),
                              "expected_candidates": len(expected), "observed_candidates": len(observed),
                              "missing_candidates": len(missing), "extra_candidates": len(extra),
                              "valid_quotes": len(expected.intersection(observed)) - invalid,
                              "sentinel_quotes": sentinels, "invalid_quotes": invalid})
    require(missing_by_pool == {pool: 0 for pool in POOLS}, f"candidate quote coverage missing rows: {missing_by_pool}")
    require(extra_by_pool == {pool: 0 for pool in POOLS}, f"candidate quote coverage has extra rows: {extra_by_pool}")
    require({pool: sum(row["expected_candidates"] for row in race_rows if row["pool"] == pool) for pool in POOLS}
            == expected_aggregate, "candidate totals by pool changed")
    require(raw_sentinels == {"WIN": 0, "QNL": 0, "EXA": 0, "TLA": 0, "TRI": 15343},
            f"sentinel inventory differs from independently audited source: {raw_sentinels}")
    tri_incomplete = {row["race_id"] for row in race_rows if row["pool"] == "TRI" and row["invalid_quotes"] > 0}
    require(len(tri_incomplete) == 245 and 467 - len(tri_incomplete) == 222,
            "TRI complete-price race cohort differs from source audit")
    require(all(row["invalid_quotes"] == 0 for row in race_rows if row["pool"] != "TRI"),
            "a non-TRI pool has invalid quote rows")

    universal_ids = set(eligible.race_id.astype(str)) - tri_incomplete
    require(len(universal_ids) == 222, "universal all-market quote-complete scope changed")
    totals_222 = {pool: sum(len(expected_by_race[rid][pool]) for rid in universal_ids) for pool in POOLS}
    valid_222 = {pool: sum(
        quote_by_key[(rid, pool, key)]["quote_status"] == "valid"
        for rid in universal_ids for key in expected_by_race[rid][pool]
    ) for pool in POOLS}
    require(totals_222 == valid_222, f"universal 222 scope contains invalid quotes: {totals_222=} {valid_222=}")

    # Save the complete candidate price audit before any probability or return calculations.
    quote_rows = []
    for rid in sorted(expected_by_race):
        for pool in POOLS:
            for key in sorted(expected_by_race[rid][pool]):
                row = quote_by_key[(rid, pool, key)]
                quote_rows.append({key_name: row.get(key_name) for key_name in [
                    "race_id", "race_date", "pool", "selection_key", "raw_odds", "parsed_odds",
                    "quote_status", "source_run_id", "source_page_path", "source_page_sha256",
                ]})
    write_csv(STUDY / "candidate_quotes.csv", quote_rows,
              ["race_id", "race_date", "pool", "selection_key", "raw_odds", "parsed_odds",
               "quote_status", "source_run_id", "source_page_path", "source_page_sha256"])
    write_csv(STUDY / "source_page_index.csv", page_rows,
              ["race_date", "meet", "source_run_id", "source_page_path", "source_page_sha256", "page_bytes"])
    write_csv(STUDY / "pool_source_cohort.csv", race_rows,
              ["race_id", "race_date", "pool", "field_n", "expected_candidates", "observed_candidates",
               "missing_candidates", "extra_candidates", "valid_quotes", "sentinel_quotes", "invalid_quotes"])
    exclusions = [{"race_id": rid, "race_date": parse_race_id(rid)[0], "pool": "TRI",
                   "reason": "at_least_one_final_quote_is_9999_9_invalid_odds_sentinel",
                   "sentinel_quotes": next(row["sentinel_quotes"] for row in race_rows
                                            if row["race_id"] == rid and row["pool"] == "TRI"),
                   "expected_candidates": len(expected_by_race[rid]["TRI"])}
                  for rid in sorted(tri_incomplete)]
    write_csv(STUDY / "source_exclusions.csv", exclusions,
              ["race_id", "race_date", "pool", "reason", "sentinel_quotes", "expected_candidates"])

    official_tie_audit = {
        "races": 467, "official_runner_rows": int(len(official)), "operating_runner_rows": int(len(runners)),
        "exactly_one_each_finish_1_2_3": True, "dead_heat_top3_races": 0,
        "rosters_and_horse_ids_match": True, "scratch_dq_incomplete_races": 0,
    }
    report = {
        "status": "PASS", "phase": "source_only_preflight_before_probability_returns",
        "cohort": {"races": 467, "dates": 70, "start": "2026-01-02", "end": "2026-09-12",
                   "runner_rows": int(len(runners)), "race_ids_sha256": hashlib.sha256(
                       "\n".join(sorted(eligible.race_id.astype(str))).encode()).hexdigest()},
        "pool_definitions": {
            "WIN": "first-place horse, single selection",
            "QNL": "official first and second horses, unordered pair",
            "EXA": "official first then second, ordered pair",
            "TLA": "official Top3 set, unordered triple",
            "TRI": "official first, second, third in exact order",
        },
        "expected_candidate_rows_467": expected_totals,
        "source_quote_rows_467": {pool: sum(1 for row in quote_rows if row["pool"] == pool) for pool in POOLS},
        "candidate_keys_missing": missing_by_pool,
        "candidate_keys_extra": extra_by_pool,
        "invalid_quotes_by_pool": raw_invalids,
        "sentinel_quotes_by_pool": raw_sentinels,
        "tri": {"incomplete_races": len(tri_incomplete), "complete_price_races": len(universal_ids),
                "universal_scope_races": len(universal_ids), "expected_candidate_rows_in_universal_scope": totals_222,
                "valid_quote_rows_in_universal_scope": valid_222},
        "all_other_pools": {"complete_price_races": 467, "expected_candidate_rows": {k: v for k, v in expected_totals.items() if k != "TRI"}},
        "official_audit": official_tie_audit,
        "api301": {**archive_summary, "complete_days": 70, "selected_pages": len(page_rows),
                   "selected_unique_page_hashes": len(source_paths_by_sha),
                   "page_index_sha256": sha(page_index_path),
                   "source_page_hashes_match_index_and_files": True,
                   "latest_complete_run_matches_20261014_source_page_index": True,
                   "winner_only_reference_used_for_loser_quotes": False,
                   "price_timing": "archived final post-race API301 odds; official publication timestamp unavailable"},
        "source_hashes": {
            "prior_cohort": sha(PREVIOUS / "cohort.csv"),
            "prior_source_manifest": sha(PREVIOUS / "SOURCE_MANIFEST.json"),
            "official_runner_results": sha(OFFICIAL),
            "source_page_index": sha(page_index_path),
            "api301_archive_helper": sha(PAYOUT_HELPER),
            "candidate_quotes_output": sha(STUDY / "candidate_quotes.csv"),
            "source_page_index_output": sha(STUDY / "source_page_index.csv"),
            "pool_source_cohort_output": sha(STUDY / "pool_source_cohort.csv"),
            "source_exclusions_output": sha(STUDY / "source_exclusions.csv"),
        },
        "read_only": {"db_mode": "ro via existing archive helper", "network": False,
                      "training_or_calibration": False, "operating_artifacts_modified": False},
    }
    (STUDY / "SOURCE_PREFLIGHT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidate_counts": expected_totals,
                      "quote_rows": report["source_quote_rows_467"], "sentinels": raw_sentinels,
                      "tri_complete_races": len(universal_ids), "universal_candidate_rows": totals_222,
                      "source_pages": len(page_rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

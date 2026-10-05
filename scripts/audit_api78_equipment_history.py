"""Read-only cross-check of historical API78 cards against KRA result sources.

The local operational and research databases, saved API78 JSON, and optionally
KRA's public score pages are read. Nothing is written to either database.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from horse_racing.collectors.kra_api import KraApiClient
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parents[1]
OPERATIONAL = ROOT / "data/horse_racing.sqlite3"
JEJU_CORE = ROOT / "jeju/data/jeju_native_core.sqlite3"
SCORE_URL = "https://race.kra.co.kr/raceScore/ScoretableDetailList.do"


def _read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _name(value: str | None) -> str:
    text = re.sub(r"^\[[^]]+\]", "", (value or "").strip())
    return "".join(text.removeprefix("★").split()).casefold()


def _equipment(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def _score_status(value: str, rank: str = "") -> str:
    for status in ("출전취소", "출전제외", "경주제외", "주행중지", "실격", "경주취소"):
        if status in value:
            return status
    if rank.isdigit() and 1 <= int(rank) <= 30:
        return "ranked_finish"
    if re.search(r"\d+:\d+(?:\.\d+)?", value):
        return "timed_finish"
    return value or "blank"


def _card_rows() -> dict[tuple[str, int, int, int], tuple[str, str | None]]:
    with _read_only(OPERATIONAL) as db:
        documents = db.execute(
            """
            SELECT sd.local_path, sd.request_params_json, sd.retrieved_at_ms,
                   sd.ingestion_run_id
            FROM source_documents sd
            JOIN ingestion_runs ir ON ir.id = sd.ingestion_run_id
            WHERE sd.endpoint = '/API78/chulmainfo'
              AND ir.status IN ('completed', 'partial')
              AND json_extract(sd.request_params_json, '$.race_dt')
                  BETWEEN '20170101' AND '20260930'
            ORDER BY sd.retrieved_at_ms DESC, sd.id DESC
            """
        ).fetchall()
    # The newest complete observation for each meet/day wins. Older repeated
    # observations are not merged with it.
    chosen: dict[tuple[str, int], int] = {}
    rows: dict[tuple[str, int, int, int], tuple[str, str | None]] = {}
    for document in documents:
        params = json.loads(document["request_params_json"])
        day, meet = str(params["race_dt"]), int(params["rccrs_cd"])
        if meet not in (1, 2, 3):
            continue
        day_key = (day, meet)
        run_id = int(document["ingestion_run_id"])
        if day_key in chosen and chosen[day_key] != run_id:
            continue
        chosen[day_key] = run_id
        raw_path = Path(document["local_path"])
        if not raw_path.is_absolute():
            raw_path = ROOT / raw_path
        payload = json.loads(raw_path.read_bytes())
        items = payload["response"]["body"].get("items", {})
        if not isinstance(items, dict):
            continue
        items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]
        for item in items:
            number = re.search(r"\d+", str(item.get("raceNo", "")))
            if number is None:
                continue
            key = (day, meet, int(number.group()), int(item["gtno"]))
            rows[key] = (str(item.get("hrnm") or ""), item.get("equipCrs"))
    return rows


def _snapshot_drift() -> dict[str, object]:
    with _read_only(OPERATIONAL) as db:
        documents = db.execute(
            """
            SELECT sd.local_path, sd.request_params_json, sd.retrieved_at_ms
            FROM source_documents sd
            JOIN ingestion_runs ir ON ir.id = sd.ingestion_run_id
            WHERE sd.endpoint = '/API78/chulmainfo'
              AND ir.status = 'completed'
              AND json_extract(sd.request_params_json, '$.race_dt')
                  BETWEEN '20260901' AND '20260920'
            ORDER BY sd.retrieved_at_ms
            """
        ).fetchall()
    observations = defaultdict(list)
    for document in documents:
        params = json.loads(document["request_params_json"])
        day, meet = str(params["race_dt"]), int(params["rccrs_cd"])
        if meet not in (1, 2, 3):
            continue
        raw_path = Path(document["local_path"])
        if not raw_path.is_absolute():
            raw_path = ROOT / raw_path
        payload = json.loads(raw_path.read_bytes())
        items = payload["response"]["body"].get("items", {})
        if not isinstance(items, dict):
            continue
        items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]
        card = {}
        for item in items:
            number = re.search(r"\d+", str(item.get("raceNo", "")))
            if number is not None:
                card[(int(number.group()), int(item["gtno"]))] = _equipment(
                    item.get("equipCrs")
                )
        observations[(day, meet)].append((document["retrieved_at_ms"], card))
    changed = added = removed = compared = 0
    examples = []
    for (day, meet), snapshots in sorted(observations.items()):
        if len(snapshots) < 2:
            continue
        first = snapshots[0][1]
        last = snapshots[-1][1]
        shared = first.keys() & last.keys()
        compared += len(shared)
        added += len(last.keys() - first.keys())
        removed += len(first.keys() - last.keys())
        for race_gate in shared:
            if first[race_gate] != last[race_gate]:
                changed += 1
                if len(examples) < 8:
                    examples.append(
                        {
                            "day": day,
                            "meet": meet,
                            "race_gate": race_gate,
                            "first": first[race_gate],
                            "last": last[race_gate],
                        }
                    )
    return {
        "repeated_meet_days": sum(len(rows) >= 2 for rows in observations.values()),
        "shared_runner_rows_compared_first_last": compared,
        "equipment_values_changed": changed,
        "runners_appeared": added,
        "runners_disappeared": removed,
        "examples": examples,
    }


def _operational():
    races: set[tuple[str, int, int]] = set()
    entries: dict[tuple[str, int, int, int], tuple[str, bool]] = {}
    with _read_only(OPERATIONAL) as db:
        for row in db.execute(
            """
            SELECT replace(r.race_date_local, '-', '') day,
                   c.kra_meet_code meet, r.race_number race_no,
                   e.horse_number horse_no, h.name_ko horse_name,
                   e.equipment_card_observed_at_ms IS NOT NULL has_card
            FROM races r
            JOIN racecourses c ON c.id = r.racecourse_id
            JOIN race_entries e ON e.race_id = r.id
            JOIN horses h ON h.id = e.horse_id
            WHERE r.race_date_local BETWEEN '2017-01-01' AND '2026-09-30'
              AND c.kra_meet_code IN (1, 2, 3)
            """
        ):
            key = (row["day"], row["meet"], row["race_no"], row["horse_no"])
            races.add(key[:3])
            entries[key] = (row["horse_name"], bool(row["has_card"]))
    return races, entries


def _jeju_core():
    rows: dict[tuple[str, int, int], dict[int, tuple[str, int | None]]] = defaultdict(dict)
    with _read_only(JEJU_CORE) as db:
        for row in db.execute(
            """
            SELECT replace(race_date, '-', '') day, race_number race_no,
                   horse_number horse_no, horse_name, finish_position
            FROM race_result_rows
            WHERE meet_code = 2 AND race_date BETWEEN '2017-01-01' AND '2026-09-30'
            """
        ):
            if row["horse_no"] is not None:
                rows[(row["day"], 2, row["race_no"])][row["horse_no"]] = (
                    row["horse_name"], row["finish_position"]
                )
    return rows


def _scratches() -> set[tuple[str, int, int, int]]:
    with _read_only(OPERATIONAL) as db:
        return {
            (row["day"], row["meet"], row["race_no"], row["horse_no"])
            for row in db.execute(
                """
                SELECT replace(race_date_local, '-', '') day,
                       meet_code meet, race_number race_no, horse_number horse_no
                FROM race_scratches
                WHERE race_date_local BETWEEN '2017-01-01' AND '2026-09-30'
                  AND horse_number IS NOT NULL
                """
            )
        }


def _score(key: tuple[str, int, int]) -> tuple[tuple[str, int, int], dict[int, tuple[str, str, str, str]] | None, str | None]:
    day, meet, race_no = key
    try:
        response = httpx.get(
            SCORE_URL,
            params={
                "Act": "04",
                "Sub": "1",
                "meet": meet,
                "realRcDate": day,
                "realRcNo": race_no,
            },
            timeout=25,
            follow_redirects=True,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.content.decode("euc-kr"), "html.parser")
        caption = next(
            (
                node
                for node in soup.find_all("caption")
                if "경주상세성적" in node.get_text(" ", strip=True)
            ),
            None,
        )
        if caption is None:
            return key, None, "score_table_absent"
        table = caption.find_parent("table")
        headers = [th.get_text(" ", strip=True) for th in table.select("thead th")]
        positions = {
            label: next((i for i, text in enumerate(headers) if label in text), None)
            for label in ("순위", "마번", "마명", "장구현황")
        }
        # Older pages label this result/status cell "도착차" even when it
        # contains 출전취소; newer pages may call it 기록.
        positions["기록"] = next(
            (i for i, text in enumerate(headers) if "기록" in text or "도착차" in text),
            None,
        )
        if any(value is None for value in positions.values()):
            return key, None, "score_columns_absent"
        result = {}
        for tr in table.select("tbody tr"):
            cells = tr.find_all("td", recursive=False)
            if len(cells) != len(headers):
                continue
            horse_no = cells[positions["마번"]].get_text(" ", strip=True)
            if not horse_no.isdigit():
                continue
            result[int(horse_no)] = (
                cells[positions["마명"]].get_text(" ", strip=True),
                cells[positions["장구현황"]].get_text(" ", strip=True),
                cells[positions["순위"]].get_text(" ", strip=True),
                cells[positions["기록"]].get_text(" ", strip=True),
            )
        return key, result, None
    except (httpx.HTTPError, UnicodeError, ValueError) as exc:
        return key, None, type(exc).__name__


def _result_api_audit(
    api_only_entries: list[tuple[str, int, int, int]],
    absent_races: set[tuple[str, int, int]],
) -> dict[str, object]:
    target_entries = set(api_only_entries)
    target_races = {key for key in absent_races if key[1] in (1, 3)}
    years_meets = sorted(
        {(int(key[0][:4]), key[1]) for key in target_entries}
        | {(int(key[0][:4]), key[1]) for key in target_races}
    )
    statuses = {}
    race_statuses = defaultdict(list)
    page_counts = {}
    settings = get_settings()
    with KraApiClient(
        settings.data_go_kr_service_key.get_secret_value(),
        base_url=settings.kra_api_base_url,
    ) as client:
        for year, meet in years_meets:
            rows = []
            pages = list(
                client.iter_pages(
                    endpoint="/API4_3/raceResult_3",
                    operation="raceResult_3",
                    public_params={"meet": meet, "rc_year": str(year), "_type": "json"},
                    page_size=20000,
                )
            )
            for page in pages:
                items = page.payload["response"]["body"].get("items", {})
                if isinstance(items, dict):
                    items = items.get("item", [])
                if isinstance(items, dict):
                    items = [items]
                rows.extend(items or [])
            page_counts[f"{year}/{meet}"] = (len(pages), len(rows))
            for row in rows:
                venue = str(row.get("meet") or "")
                if (meet == 1 and venue != "서울") or (
                    meet == 3 and venue not in ("부산경남", "부경", "부산")
                ):
                    continue
                try:
                    key = (
                        str(row["rcDate"]),
                        meet,
                        int(row["rcNo"]),
                        int(row["chulNo"]),
                    )
                    order = int(row["ord"])
                except (KeyError, TypeError, ValueError):
                    continue
                if key in target_entries:
                    statuses[key] = (order, str(row.get("hrName") or ""))
                if key[:3] in target_races:
                    race_statuses[key[:3]].append(order)
    return {
        "annual_queries": page_counts,
        "api_only_entry_targets": len(target_entries),
        "api_only_entries_found_in_result_api": len(statuses),
        "api_only_entries_missing_from_result_api": len(target_entries - statuses.keys()),
        "api_only_entry_finish_codes": dict(
            sorted(Counter(order for order, _ in statuses.values()).items())
        ),
        "api_only_entry_ordinary_finishes": sum(
            1 <= order <= 30 for order, _ in statuses.values()
        ),
        "api_only_entry_positive_or_zero_examples": [
            {"key": key, "order": order, "horse_name": horse_name}
            for key, (order, horse_name) in sorted(statuses.items())
            if order == 0 or 1 <= order <= 30
        ],
        "api_only_non_jeju_race_targets": len(target_races),
        "api_only_non_jeju_races_in_result_api": len(race_statuses),
        "api_only_non_jeju_races_with_ranked_finish": sum(
            any(1 <= order <= 30 for order in orders)
            for orders in race_statuses.values()
        ),
        "api_only_non_jeju_races_without_ranked_finish": sum(
            not any(1 <= order <= 30 for order in orders)
            for orders in race_statuses.values()
        ),
        "api_only_non_jeju_races_missing_from_result_api": [
            key for key in sorted(target_races) if key not in race_statuses
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--result-api", action="store_true")
    parser.add_argument(
        "--entry-sample", type=int, default=0,
        help="Also check this many API-only entries per year/meet against score pages",
    )
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    cards = _card_rows()
    races, entries = _operational()
    core = _jeju_core()

    card_races = {key[:3] for key in cards}
    absent_races = card_races - races
    api_only_race_runner_rows = sum(key[:3] in absent_races for key in cards)
    api_only_entries = [key for key in cards if key[:3] in races and key not in entries]
    scratches = _scratches()
    missing_cards = [key for key, (_, has_card) in entries.items() if not has_card]
    jeju_absent = [key for key in absent_races if key[1] == 2]
    jeju_core_matches = [key for key in jeju_absent if key in core]
    jeju_core_api_rows = 0
    jeju_core_horse_matches = 0
    jeju_core_horse_disagree = 0
    jeju_ranked_races = 0
    for key in jeju_core_matches:
        jeju_ranked_races += any(
            finish is not None and 1 <= finish <= 30
            for _, finish in core[key].values()
        )
        for horse_no, (horse_name, _) in core[key].items():
            card = cards.get((*key, horse_no))
            if card is None:
                continue
            jeju_core_api_rows += 1
            if _name(horse_name) == _name(card[0]):
                jeju_core_horse_matches += 1
            else:
                jeju_core_horse_disagree += 1

    summary = {
        "scope": "2017-01-01 through 2026-09-30",
        "api78_runner_rows": len(cards),
        "api78_races": len(card_races),
        "operational_races": len(races),
        "api_only_races": len(absent_races),
        "api_only_race_runner_rows": api_only_race_runner_rows,
        "api_only_races_by_meet_year": dict(
            sorted(Counter(f"{key[0][:4]}/{key[1]}" for key in absent_races).items())
        ),
        "api_only_entry_rows_on_existing_races": len(api_only_entries),
        "api_only_entry_examples": sorted(api_only_entries)[:8],
        "api_only_entry_rows_with_recorded_scratch": sum(
            key in scratches for key in api_only_entries
        ),
        "operational_entries_without_api78_card": len(missing_cards),
        "jeju_api_only_races": len(jeju_absent),
        "jeju_api_only_races_in_independent_api4_3": len(jeju_core_matches),
        "jeju_api_only_races_with_ranked_finish": jeju_ranked_races,
        "jeju_api_only_races_without_ranked_finish": len(jeju_core_matches)
        - jeju_ranked_races,
        "jeju_api_only_card_runners_in_api4_3": jeju_core_api_rows,
        "jeju_api_only_horse_number_name_matches": jeju_core_horse_matches,
        "jeju_api_only_horse_number_name_disagreements": jeju_core_horse_disagree,
        "prospective_2026_snapshot_drift": _snapshot_drift(),
    }

    if args.web:
        non_jeju_absent = sorted(key for key in absent_races if key[1] != 2)
        entry_sample = []
        sampled_per_bucket = Counter()
        for key in sorted(api_only_entries):
            bucket = (key[0][:4], key[1])
            if sampled_per_bucket[bucket] < args.entry_sample:
                entry_sample.append(key)
                sampled_per_bucket[bucket] += 1
        web_keys = sorted(
            set(non_jeju_absent)
            | {key[:3] for key in missing_cards}
            | {key[:3] for key in entry_sample}
        )
        scores = {}
        errors = Counter()
        error_keys = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            future_to_key = {pool.submit(_score, key): key for key in web_keys}
            for future in as_completed(future_to_key):
                key, result, error = future.result()
                if error:
                    errors[error] += 1
                    error_keys.append({"race": key, "error": error})
                else:
                    scores[key] = result
        missing_in_score = 0
        missing_score_equipment = 0
        missing_name_disagree = 0
        for key in missing_cards:
            score = scores.get(key[:3], {}).get(key[3])
            if score is None:
                missing_in_score += 1
            else:
                missing_score_equipment += bool(_equipment(score[1]))
                missing_name_disagree += _name(entries[key][0]) != _name(score[0])
        api_score_compared = api_score_same = api_score_different = 0
        differences = []
        for key, (api_name, api_equipment) in cards.items():
            score = scores.get(key[:3], {}).get(key[3])
            if score is None or _name(api_name) != _name(score[0]):
                continue
            api_score_compared += 1
            if _equipment(api_equipment) == _equipment(score[1]):
                api_score_same += 1
            else:
                api_score_different += 1
                if len(differences) < 12:
                    differences.append(
                        {"key": key, "api78": api_equipment, "score": score[1]}
                    )
        summary["official_score_web"] = {
            "requested_races": len(web_keys),
            "successful_pages": len(scores),
            "errors": dict(errors),
            "error_keys": sorted(error_keys, key=lambda row: row["race"]),
            "api_only_non_jeju_races_with_score_rows": sum(
                bool(scores.get(key)) for key in non_jeju_absent
            ),
            "api_only_non_jeju_races_with_ranked_finish": sum(
                any(_score_status(row[3], row[2]) in ("ranked_finish", "timed_finish") for row in scores.get(key, {}).values())
                for key in non_jeju_absent
            ),
            "api_only_non_jeju_races_without_score_rows": sum(
                not bool(scores.get(key)) for key in non_jeju_absent
            ),
            "missing_card_entries_in_score": len(missing_cards) - missing_in_score,
            "missing_card_entries_absent_from_score": missing_in_score,
            "missing_card_entries_with_score_equipment": missing_score_equipment,
            "missing_card_entry_name_disagreements": missing_name_disagree,
            "api78_vs_score_rows_compared": api_score_compared,
            "api78_vs_score_equipment_equal_after_whitespace": api_score_same,
            "api78_vs_score_equipment_different": api_score_different,
            "sample_differences": differences,
            "api_only_entry_sample_size": len(entry_sample),
            "api_only_entry_sample_in_score": sum(
                key[3] in scores.get(key[:3], {}) for key in entry_sample
            ),
            "api_only_entry_sample_absent_from_score": sum(
                key[3] not in scores.get(key[:3], {}) for key in entry_sample
            ),
            "api_only_entry_sample_score_records": dict(
                sorted(
                    Counter(
                        _score_status(scores[key[:3]][key[3]][3], scores[key[:3]][key[3]][2])
                        for key in entry_sample
                        if key[3] in scores.get(key[:3], {})
                    ).items()
                )
            ),
            "missing_card_entry_score_records": dict(
                sorted(
                    Counter(
                        _score_status(scores[key[:3]][key[3]][3], scores[key[:3]][key[3]][2])
                        for key in missing_cards
                        if key[3] in scores.get(key[:3], {})
                    ).items()
                )
            ),
        }
    if args.result_api:
        summary["official_api4_3"] = _result_api_audit(
            api_only_entries, absent_races
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

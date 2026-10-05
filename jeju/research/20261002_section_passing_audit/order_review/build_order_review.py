"""Build source-linked, read-only review of section passing-order disagreements."""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "jeju/research/20260929_api_detail_sources/raw/full_year_sections_passing/20260929T143902.196014Z"
INPUT = ROOT / "jeju/research/20261002_section_passing_audit/root_audit/api4_group_order_disagreements.csv"
OUT = Path(__file__).resolve().parent
MAP = {
    "S1F": ("corner_7", "passrankS1f", "sjS1fOrd", "jeS1fTime"),
    "1C": ("corner_1", "passrankG8f_1c", "sj_1cOrd", "je_1cTime"),
    "2C": ("corner_2", "passrankG6f_2c", "sj_2cOrd", "je_2cTime"),
    "3C": ("corner_3", "passrankG4f_3c", "sj_3cOrd", "je_3cTime"),
    "4C": ("corner_4", "passrankG3f_4c", "sj_4cOrd", "je_4cTime"),
    "G1F": ("corner_8", "passrankG1f", "sjG1fOrd", "jeG1fTime"),
}


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def parse_groups(value):
    """Reproduce the prior conservative parser; its grammar is still unverified."""
    text = str(value).replace(" ", "")
    if not re.fullmatch(r"[0-9(),^=≡\-]+", text):
        return None
    matches = list(re.finditer(r"\([^()]+\)|\^?\d+", text))
    end, groups = 0, []
    for match in matches:
        if text[end:match.start()] and not re.fullmatch(r"[,=≡\-]+", text[end:match.start()]):
            return None
        token = match.group()
        group = [int(value) for value in re.findall(r"\d+", token)]
        if token.startswith("(") and not re.fullmatch(r"\(\^?\d+(?:,\^?\d+)*\)", token):
            return None
        groups.append(group)
        end = match.end()
    return groups if end == len(text) else None


def rank_bounds(horses, value_for):
    values = [(number(value_for(horse)), int(horse["horse_number"])) for horse in horses]
    values = [(value, horse_no) for value, horse_no in values if value is not None and value > 0]
    return {
        horse_no: (
            sum(1 for other, _ in values if other < value) + 1,
            sum(1 for other, _ in values if other <= value),
        )
        for value, horse_no in values
    }


def overlaps(left, right):
    return bool(left and right and max(left[0], right[0]) <= min(left[1], right[1]))


def pair_stats(horses, order_field, time_for):
    pairs = []
    for horse in horses:
        order = number(horse["selected_point"]["order_raw"])
        seconds = number(time_for(horse))
        if order is not None and 0 < order < 90 and seconds is not None and seconds > 0:
            pairs.append((order, seconds))
    same = opposite = tied = 0
    for i, first in enumerate(pairs):
        for second in pairs[i + 1 :]:
            order_delta, time_delta = first[0] - second[0], first[1] - second[1]
            if order_delta == 0 or time_delta == 0:
                tied += 1
            elif (order_delta < 0) == (time_delta < 0):
                same += 1
            else:
                opposite += 1
    return {
        "horses_with_positive_order_and_time": len(pairs),
        "pairs_compared": same + opposite + tied,
        "same_direction": same,
        "opposite_direction": opposite,
        "tied_on_either": tied,
    }


def load_original_pages(manifest, needed):
    sources = {"passing_corner": {}, "detail_section": {}}
    for dataset in sources:
        metadata = manifest["datasets"][dataset]
        for year in metadata["yearly"]:
            for page in year["pages"]:
                path = (BASE / page["response_file"]).resolve()
                if not path.is_relative_to(BASE.resolve()):
                    raise RuntimeError("manifest source path escapes archive root")
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != page["response_sha256"] or len(content) != page["response_bytes"]:
                    raise RuntimeError(f"page integrity mismatch: {page['response_file']}")
                response = json.loads(content)
                if response["response"]["header"]["resultCode"] != "00":
                    raise RuntimeError(f"unsuccessful source page: {page['response_file']}")
                items = response["response"]["body"]["items"]["item"]
                items = items if isinstance(items, list) else [items]
                if len(items) != page["actual_page_rows"]:
                    raise RuntimeError(f"page row-count mismatch: {page['response_file']}")
                for index, raw in enumerate(items, start=1):
                    try:
                        key = (str(raw["rcDate"]), int(raw["rcNo"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if key in needed:
                        sources[dataset][key] = {
                            "raw": raw,
                            "locator": {
                                "relative_path": path.relative_to(ROOT).as_posix(),
                                "page_no": page["page_no"],
                                "item_index_1_based": index,
                                "page_sha256": page["response_sha256"],
                                "page_bytes": page["response_bytes"],
                                "page_rows": page["actual_page_rows"],
                                "endpoint": metadata["endpoint"],
                                "operation": metadata["operation"],
                            },
                        }
    return sources


def main():
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        input_rows = list(csv.DictReader(stream))
    grouped = collections.defaultdict(list)
    for row in input_rows:
        grouped[(row["date"], int(row["race_no"]), row["point"])].append(row)
    needed = {(date.replace("-", ""), race) for date, race, _ in grouped}
    manifest = json.loads((BASE / "run_manifest.json").read_text(encoding="utf-8"))
    sources = load_original_pages(manifest, needed)
    database = (ROOT / "jeju/data/jeju_native_core.sqlite3").as_uri() + "?mode=ro"
    conn = sqlite3.connect(database, uri=True)
    conn.row_factory = sqlite3.Row
    cases, quick_keys, anomaly_flags = [], [], []
    pair_totals, api6_comparison, flagged_time = collections.Counter(), collections.Counter(), collections.Counter()

    for (date, race, point), flags in sorted(grouped.items()):
        api303_field, api6_field, order_field, time_field = MAP[point]
        source_key = (date.replace("-", ""), race)
        race_rows = conn.execute(
            """SELECT r.api_record_id,r.race_date,r.meet_code,r.race_number,r.horse_number,
                      r.horse_id,r.horse_name,r.finish_position,r.finish_status_raw,r.finish_time_seconds,
                      a.payload_json,a.payload_sha256,a.source_artifact_id,a.record_index,
                      s.raw_relative_path,s.sha256 page_sha,s.source_family,s.source_role,s.dataset_name,
                      s.endpoint,s.public_dataset_id
               FROM race_result_rows r JOIN api_records a USING(api_record_id)
               JOIN source_artifacts s USING(source_artifact_id)
               WHERE r.race_date=? AND r.meet_code=2 AND r.race_number=? ORDER BY r.horse_number""",
            (date, race),
        ).fetchall()
        api303_db = conn.execute(
            """SELECT a.api_record_id,a.payload_json,a.payload_sha256,a.record_index,a.source_artifact_id,
                      s.raw_relative_path,s.sha256 page_sha,s.source_family,s.source_role,s.dataset_name,
                      s.endpoint,s.public_dataset_id
               FROM api_records a JOIN source_artifacts s USING(source_artifact_id)
               JOIN api303_corner_rank_rows c USING(api_record_id)
               WHERE c.race_date=? AND c.meet_code=2 AND c.race_number=?""",
            (date, race),
        ).fetchone()
        api303_page = sources["passing_corner"].get(source_key)
        api6_page = sources["detail_section"].get(source_key)
        if not api303_db or not api303_page or not api6_page:
            raise RuntimeError(f"a raw API source is missing for {date} race {race}")
        if hashlib.sha256(api303_db["payload_json"].encode()).hexdigest() != api303_db["payload_sha256"]:
            raise RuntimeError("API303 database payload hash mismatch")
        raw303 = json.loads(api303_db["payload_json"])
        if raw303 != api303_page["raw"]:
            raise RuntimeError(f"API303 page and DB payload differ for {date} race {race}")
        raw6 = api6_page["raw"]
        notation = raw303.get(api303_field)
        groups = parse_groups(notation)
        group_bounds, position = {}, 1
        for group in groups or []:
            for number_value in group:
                group_bounds[number_value] = (position, position + len(group) - 1)
            position += len(group)

        horses = []
        for record in race_rows:
            if hashlib.sha256(record["payload_json"].encode()).hexdigest() != record["payload_sha256"]:
                raise RuntimeError("API4 payload hash mismatch")
            raw = json.loads(record["payload_json"])
            selected_time = conn.execute(
                """SELECT api_value_raw,api_value_json_type,time_seconds,time_status,website_seconds,
                          website_display,website_url,evidence_relative_path,evidence_sha256
                   FROM jeju_race_section_time_values WHERE api_record_id=? AND field_name=?""",
                (record["api_record_id"], time_field),
            ).fetchone()
            values_all_points = {}
            for label, (_, _, ordinal, seconds) in MAP.items():
                values_all_points[label] = {
                    "order_field": ordinal,
                    "order_raw": raw.get(ordinal),
                    "order_json_type": type(raw.get(ordinal)).__name__ if ordinal in raw else "missing_key",
                    "time_field": seconds,
                    "time_raw": raw.get(seconds),
                    "time_json_type": type(raw.get(seconds)).__name__ if seconds in raw else "missing_key",
                }
            horse = {key: record[key] for key in (
                "api_record_id", "race_date", "meet_code", "race_number", "horse_number", "horse_id",
                "horse_name", "finish_position", "finish_status_raw", "finish_time_seconds", "payload_sha256",
                "source_artifact_id", "record_index", "raw_relative_path", "page_sha", "source_family",
                "source_role", "dataset_name", "endpoint", "public_dataset_id",
            )}
            horse["api4_item_index_1_based"] = record["record_index"]
            horse["api4_payload_field_values_all_points"] = values_all_points
            horse["selected_point"] = {
                "order_field": order_field,
                "order_raw": raw.get(order_field),
                "order_json_type": type(raw.get(order_field)).__name__ if order_field in raw else "missing_key",
                "time_field": time_field,
                "time_raw": raw.get(time_field),
                "time_json_type": type(raw.get(time_field)).__name__ if time_field in raw else "missing_key",
                "postrace_time_view": None if selected_time is None else dict(selected_time),
            }
            horse["group_rank_bounds_by_program_no"] = list(group_bounds[record["horse_number"]]) if record["horse_number"] in group_bounds else None
            horse["listed_as_outside_group_bounds"] = any(int(flag["program_no"]) == record["horse_number"] for flag in flags)
            horses.append(horse)

        raw_ranks = rank_bounds(horses, lambda h: h["selected_point"]["time_raw"])
        reviewed_ranks = rank_bounds(horses, lambda h: (h["selected_point"]["postrace_time_view"] or {}).get("time_seconds"))
        for horse in horses:
            horse_no = int(horse["horse_number"])
            horse["raw_time_rank_bounds"] = list(raw_ranks[horse_no]) if horse_no in raw_ranks else None
            horse["review_selected_time_rank_bounds"] = list(reviewed_ranks[horse_no]) if horse_no in reviewed_ranks else None
            horse["raw_time_rank_overlaps_group_bounds"] = overlaps(raw_ranks.get(horse_no), group_bounds.get(horse_no))
            horse["review_time_rank_overlaps_group_bounds"] = overlaps(reviewed_ranks.get(horse_no), group_bounds.get(horse_no))

        raw_pairs = pair_stats(horses, order_field, lambda h: h["selected_point"]["time_raw"])
        reviewed_pairs = pair_stats(horses, order_field, lambda h: (h["selected_point"]["postrace_time_view"] or {}).get("time_seconds"))
        for name, value in (
            ("raw_same", raw_pairs["same_direction"]), ("raw_opposite", raw_pairs["opposite_direction"]),
            ("raw_ties", raw_pairs["tied_on_either"]), ("review_same", reviewed_pairs["same_direction"]),
            ("review_opposite", reviewed_pairs["opposite_direction"]), ("review_ties", reviewed_pairs["tied_on_either"]),
        ):
            pair_totals[name] += value

        flagged_rows = []
        for flag in flags:
            horse_no = int(flag["program_no"])
            horse = next((item for item in horses if item["horse_number"] == horse_no), None)
            review = {} if horse is None or horse["selected_point"]["postrace_time_view"] is None else horse["selected_point"]["postrace_time_view"]
            flagged_rows.append({
                "horse_id": flag["horse_id"], "program_no": horse_no, "api4_order": flag["api4_order"],
                "api303_group_rank_bounds": [int(flag["group_rank_min"]), int(flag["group_rank_max"])],
                "api4_raw_time": None if horse is None else horse["selected_point"]["time_raw"],
                "api4_raw_time_rank_bounds": None if horse is None else horse["raw_time_rank_bounds"],
                "api4_review_selected_time_seconds": review.get("time_seconds"),
                "api4_review_selected_time_status": review.get("time_status"),
                "raw_time_rank_overlaps_api303_group_bounds": False if horse is None else horse["raw_time_rank_overlaps_group_bounds"],
                "review_time_rank_overlaps_api303_group_bounds": False if horse is None else horse["review_time_rank_overlaps_group_bounds"],
                "api4_payload_sha256": None if horse is None else horse["payload_sha256"],
                "api4_source_page_path": None if horse is None else horse["raw_relative_path"],
                "api4_source_page_sha256": None if horse is None else horse["page_sha"],
            })
            if horse:
                flagged_time["raw"] += horse["raw_time_rank_overlaps_group_bounds"]
                flagged_time["review"] += horse["review_time_rank_overlaps_group_bounds"]
                if review.get("time_status") in ("website_corrected", "unresolved_official_website_anomaly", "website_review_not_applied", "api_source_changed_since_review"):
                    anomaly_flags.append({
                        "date": date, "race_no": race, "point": point, "horse_id": horse["horse_id"],
                        "program_no": horse_no, "status": review.get("time_status"),
                        "api4_raw_time": horse["selected_point"]["time_raw"],
                        "effective_time_seconds": review.get("time_seconds"), "website_seconds": review.get("website_seconds"),
                        "website_display": review.get("website_display"), "website_url": review.get("website_url"),
                        "evidence_relative_path": review.get("evidence_relative_path"), "evidence_sha256": review.get("evidence_sha256"),
                    })

        api6_value = raw6.get(api6_field)
        exact_match = str(notation) == str(api6_value)
        api6_comparison["exact" if exact_match else "different"] += 1
        case = {
            "race_key": {"race_date": date, "meet_code": 2, "race_number": race, "race_id_key": f"{date}:2:{race}"},
            "point": point,
            "flagged_observation_count": len(flags),
            "full_api4_roster_count": len(horses),
            "api4_source_rows_hash_verified": True,
            "field_mapping_used_for_review": {
                "api303_field": api303_field, "api6_field": api6_field,
                "api4_order_field": order_field, "api4_time_field": time_field,
                "mapping_status": "pre-existing audit hypothesis; source parity and API4 order/time coherence do not establish official point semantics",
            },
            "raw_group_notation": notation,
            "parser_output_groups_as_written": groups,
            "derived_group_rank_bounds_assuming_parentheses_are_ties_and_separator_tokens_mark_successive_groups": {
                str(horse_no): list(bounds) for horse_no, bounds in sorted(group_bounds.items())
            },
            "notation_semantics_caution": "Parser strips ^ and treats comma, hyphen, =, and ≡ as group boundaries; only parentheses receive special group-membership semantics. This is a mechanical hypothesis, not confirmed official grammar.",
            "api303_all_corner_fields_raw": {f"corner_{index}": raw303.get(f"corner_{index}") for index in range(1, 10)},
            "api6_selected_field_raw": api6_value,
            "api6_selected_field_exact_text_matches_api303": exact_match,
            "api6_all_passrank_fields_raw": {key: value for key, value in raw6.items() if key.lower().startswith("passrank")},
            "api4_all_starter_rows": horses,
            "api4_order_vs_its_own_raw_time_pairwise_comparison": raw_pairs,
            "api4_order_vs_review_selected_time_pairwise_comparison": reviewed_pairs,
            "flagged_rows_time_comparison": flagged_rows,
            "source_links": {
                "api303": {
                    "api_record_id": api303_db["api_record_id"], "source_artifact_id": api303_db["source_artifact_id"],
                    "record_index_1_based": api303_db["record_index"], "payload_sha256": api303_db["payload_sha256"],
                    "source_page_path": api303_db["raw_relative_path"], "source_page_sha256": api303_db["page_sha"],
                    "source_family": api303_db["source_family"], "source_role": api303_db["source_role"],
                    "dataset_name": api303_db["dataset_name"], "endpoint": api303_db["endpoint"],
                    "public_dataset_id": api303_db["public_dataset_id"], "raw_page_locator": api303_page["locator"],
                },
                "api6": {"raw_page_locator": api6_page["locator"], "race_row_key_fields": {"rcDate": raw6.get("rcDate"), "rcNo": raw6.get("rcNo")}, "page_row_matches_requested_key": True},
                "api4": {"database_source": "race_result_rows JOIN api_records JOIN source_artifacts", "row_count": len(horses), "horse_item_locators_are_per_starter_in_api4_all_starter_rows": True},
            },
        }
        cases.append(case)
        quick_keys.append({
            "race_key": case["race_key"], "point": point, "flagged_observations": len(flags),
            "api303_field": api303_field, "api6_field": api6_field,
            "api4_order_field": order_field, "api4_time_field": time_field,
            "api303_raw_group": notation, "api6_raw_group": api6_value,
            "api6_matches_api303": exact_match, "source_link_case_index": len(cases) - 1,
        })

    race_keys = sorted({(row["date"], int(row["race_no"])) for row in input_rows})
    raw_overlap = sum(item["raw_time_rank_overlaps_api303_group_bounds"] for case in cases for item in case["flagged_rows_time_comparison"])
    view_overlap = sum(item["review_time_rank_overlaps_api303_group_bounds"] for case in cases for item in case["flagged_rows_time_comparison"])
    summary = {
        "flagged_observations": len(input_rows), "unique_races": len(race_keys), "race_point_keys": len(cases),
        "api4_full_roster_rows": sum(case["full_api4_roster_count"] for case in cases),
        "api4_payload_sha256_verified": True, "api303_payload_and_page_match_verified": True,
        "api6_target_page_sha_size_row_count_verified": True,
        "api6_api303_selected_field_exact_text_matches": api6_comparison["exact"],
        "api6_api303_selected_field_differences": api6_comparison["different"],
        "flagged_api4_raw_time_rank_interval_overlaps_parsed_group": raw_overlap,
        "flagged_review_selected_time_rank_interval_overlaps_parsed_group": view_overlap,
        "api4_order_vs_rawtime_pairs": {"same_direction": pair_totals["raw_same"], "opposite_direction": pair_totals["raw_opposite"], "tied_on_either": pair_totals["raw_ties"]},
        "api4_order_vs_review_selected_time_pairs": {"same_direction": pair_totals["review_same"], "opposite_direction": pair_totals["review_opposite"], "tied_on_either": pair_totals["review_ties"]},
        "known_reviewed_or_unresolved_time_cases_among_flags": anomaly_flags,
    }
    output = {
        "title": "API4 horse passing-order disagreements: source-linked review",
        "generated_date": "2026-10-02",
        "scope": "Read-only re-review of the existing 27-race, 31-point, 105-observation disagreement CSV with original API4/API303/API6 source locators.",
        "input_csv": "jeju/research/20261002_section_passing_audit/root_audit/api4_group_order_disagreements.csv",
        "database_uri_mode": "SQLite mode=ro",
        "summary": summary,
        "field_mapping_hypothesis": {key: {"api303_field": value[0], "api6_field": value[1], "api4_order_field": value[2], "api4_time_field": value[3]} for key, value in MAP.items()},
        "interpretation_limits": [
            "Mappings among API303 corner_N, API6 passrank*, and API4 sj*Ord/je*Time are the pre-existing audit mapping, not official semantic validation.",
            "API6/API303 string equality under a mapping proves string parity for that race/field, not that the field denotes the same physical checkpoint as the API4 named point.",
            "API4 times are horse-level; API6 pass times are race-level. Absolute values are not treated as the same entity or comparable measurement.",
            "Rank-from-time is a descriptive cross-check only; raw times may be erroneous or unprovided. The postrace view may show corrections or unresolved anomalies.",
            "Group rank intervals depend on the unconfirmed parser assumptions. All original notation is retained verbatim.",
            "Non-candidate starters are not assumed to be wrong horses; the full current race_result_rows roster is included for context.",
            "No source values, database records, schema, or existing audit outputs were modified.",
        ],
        "point_key_list": quick_keys,
        "race_keys": [{"race_date": date, "meet_code": 2, "race_number": race, "race_id_key": f"{date}:2:{race}"} for date, race in race_keys],
        "point_reviews": cases,
    }
    (OUT / "source_linked_point_review.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    quick = {"title": "Quick race/point/key list for official page comparison", "generated_date": "2026-10-02", "source_input": "jeju/research/20261002_section_passing_audit/root_audit/api4_group_order_disagreements.csv", "summary": {"unique_races": len(race_keys), "race_point_keys": len(cases), "observations": len(input_rows)}, "races": []}
    for date, race in race_keys:
        points = []
        for case_index, case in enumerate(cases):
            if case["race_key"]["race_date"] == date and case["race_key"]["race_number"] == race:
                source = case["source_links"]
                points.append({
                    "point": case["point"], "flagged_observations": case["flagged_observation_count"],
                    **case["field_mapping_used_for_review"], "api303_raw_group": case["raw_group_notation"],
                    "api6_matches_api303": case["api6_selected_field_exact_text_matches_api303"], "source_link_case_index": case_index,
                    "api303_raw_page": source["api303"]["raw_page_locator"], "api6_raw_page": source["api6"]["raw_page_locator"],
                    "api303_db_record": {key: source["api303"][key] for key in ("api_record_id", "source_artifact_id", "record_index_1_based", "payload_sha256", "source_page_sha256", "source_page_path")},
                    "api4_starter_keys_and_source_links": [
                        {"horse_id": horse["horse_id"], "program_no": horse["horse_number"], "api_record_id": horse["api_record_id"],
                         "record_index_1_based": horse["api4_item_index_1_based"], "source_page_path": horse["raw_relative_path"],
                         "source_page_sha256": horse["page_sha"], "payload_sha256": horse["payload_sha256"]}
                        for horse in case["api4_all_starter_rows"]
                    ],
                })
        quick["races"].append({"race_date": date, "meet_code": 2, "race_number": race, "race_id_key": f"{date}:2:{race}", "points": points})
    (OUT / "quick_race_point_keys.json").write_text(json.dumps(quick, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    conn.close()
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

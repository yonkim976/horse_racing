"""Verify dot-suffix passing-order runners against archived KRA page evidence.

Read-only inputs: local website_evidence.json, its hashed HTML files, audit CSV,
and jeju_native_core.sqlite3 opened in SQLite read-only mode. Outputs stay in
this review's evidence directory.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
EVIDENCE = OUT / "evidence"
PROJECT = OUT.parents[3]
BASE = PROJECT / "jeju" / "research" / "20261002_section_remaining_review"
HTML_DIR = (BASE / "website_html").resolve()
WEB_JSON = BASE / "website_evidence.json"
AUDIT_CSV = PROJECT / "jeju" / "research" / "20261002_section_passing_audit" / "root_audit" / "unparsed_notations.csv"
DB = PROJECT / "jeju" / "data" / "jeju_native_core.sqlite3"

SECTION_FIELDS = (
    "jeS1fTime", "je_1cTime", "je_2cTime", "je_3cTime",
    "je_4cTime", "jeG3fTime", "jeG1fTime",
)
ORDER_FIELDS = (
    "sjS1fOrd", "sj_1cOrd", "sj_2cOrd", "sj_3cOrd", "sj_4cOrd", "sjG1fOrd",
)
POINT_FIELDS = {
    "S1F": "corner_7_raw", "1C": "corner_1_raw", "2C": "corner_2_raw",
    "3C": "corner_3_raw", "4C": "corner_4_raw", "G1F": "corner_8_raw",
}


def confined_path(base: Path, relative: str) -> Path:
    path = (base / relative).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Evidence path escapes its directory: {relative}") from exc
    return path


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_api4_zero_files(conn: sqlite3.Connection) -> dict:
    times_sql = " AND ".join(
        f"json_type(a.payload_json,'$.{field}')='integer' AND json_extract(a.payload_json,'$.{field}')=0"
        for field in SECTION_FIELDS
    )
    select_fields = ",".join(
        f"json_extract(a.payload_json,'$.{field}') AS {field},"
        f"json_type(a.payload_json,'$.{field}') AS {field}_json_type"
        for field in SECTION_FIELDS
    )
    rows = conn.execute(
        f"""SELECT r.race_date,r.race_number,r.horse_number,r.horse_id,r.horse_name,
                   r.finish_position,r.finish_status_raw,r.finish_time_seconds,
                   s.raw_relative_path,s.sha256 AS source_page_sha256,a.record_index,
                   a.payload_sha256 AS normalized_payload_sha256,{select_fields}
            FROM jeju_race_population_candidates r
            JOIN api_records a USING(api_record_id)
            JOIN source_artifacts s USING(source_artifact_id)
            WHERE r.finish_position BETWEEN 1 AND 89 AND r.finish_time_seconds>0
              AND {times_sql}
            ORDER BY r.race_date,r.race_number,r.horse_number"""
    ).fetchall()
    if len(rows) != 25:
        raise RuntimeError(f"Expected 25 all-time-zero finishers; found {len(rows)}")
    time_rows = [dict(row) for row in rows]
    write_csv(EVIDENCE / "api4_all_times_explicit_zero_25.csv", time_rows)

    order_sql = " AND ".join(
        f"json_type(a.payload_json,'$.{field}')='integer' AND json_extract(a.payload_json,'$.{field}')=0"
        for field in ORDER_FIELDS
    )
    order_select = ",".join(
        f"json_extract(a.payload_json,'$.{field}') AS {field},"
        f"json_type(a.payload_json,'$.{field}') AS {field}_json_type"
        for field in ORDER_FIELDS
    )
    order_rows = conn.execute(
        f"""SELECT r.race_date,r.race_number,r.horse_number,r.horse_id,r.horse_name,
                   r.finish_position,r.finish_status_raw,r.finish_time_seconds,
                   s.raw_relative_path,s.sha256 AS source_page_sha256,a.record_index,
                   a.payload_sha256 AS normalized_payload_sha256,{order_select}
            FROM jeju_race_population_candidates r
            JOIN api_records a USING(api_record_id)
            JOIN source_artifacts s USING(source_artifact_id)
            WHERE r.finish_position BETWEEN 1 AND 89 AND r.finish_time_seconds>0
              AND {order_sql}
            ORDER BY r.race_date,r.race_number,r.horse_number"""
    ).fetchall()
    if len(order_rows) != 1:
        raise RuntimeError(f"Expected one all-order-zero finisher; found {len(order_rows)}")
    write_csv(EVIDENCE / "api4_all_orders_explicit_zero_1.csv", [dict(row) for row in order_rows])

    legacy_keys = (
        ("2002-08-24", 5), ("2002-08-11", 1), ("2002-08-10", 1),
        ("2002-08-10", 2), ("2002-07-28", 4), ("2002-07-14", 3),
    )
    roster_rows = []
    for date, race_no in legacy_keys:
        roster_rows.extend(
            dict(row) for row in conn.execute(
                """SELECT race_date,race_number,horse_number,horse_id,horse_name,
                          finish_position,finish_status_raw,finish_time_seconds
                   FROM race_result_rows WHERE race_date=? AND race_number=?
                   ORDER BY horse_number""", (date, race_no)
            ).fetchall()
        )
    write_csv(EVIDENCE / "legacy_compact_race_rosters.csv", roster_rows)

    return {
        "all_time_zero_rows": len(time_rows),
        "all_time_zero_races": len({(r["race_date"], r["race_number"]) for r in time_rows}),
        "time_fields": list(SECTION_FIELDS),
        "time_json_types": sorted({r[f"{SECTION_FIELDS[0]}_json_type"] for r in time_rows}),
        "all_order_zero_rows": len(order_rows),
        "order_fields": list(ORDER_FIELDS),
        "order_json_types": sorted({r[f"{ORDER_FIELDS[0]}_json_type"] for r in order_rows}),
        "legacy_roster_rows": len(roster_rows),
        "legacy_race_rosters": len(legacy_keys),
    }


def enrich_time_zero_with_website_pages() -> dict:
    time_csv = EVIDENCE / "api4_all_times_explicit_zero_25.csv"
    order_csv = EVIDENCE / "api4_all_orders_explicit_zero_1.csv"
    with time_csv.open(encoding="utf-8-sig", newline="") as stream:
        time_rows = list(csv.DictReader(stream))
    with order_csv.open(encoding="utf-8-sig", newline="") as stream:
        order_rows = list(csv.DictReader(stream))
    evidence_by_key = {
        (item["date"], int(item["race_no"])): item
        for item in json.loads(WEB_JSON.read_text(encoding="utf-8"))
    }
    point_headers = ("S-1F", "1코너", "2코너", "3코너", "4코너", "G-3F", "G-1F")

    def get_site_rows(source_row: dict) -> tuple[dict, dict, dict]:
        key = (source_row["race_date"], int(source_row["race_number"]))
        page = evidence_by_key.get(key)
        if page is None or not page.get("identity_verified"):
            raise RuntimeError(f"No identity-verified website page for API4 row: {key}")
        result_table = next(
            (table for table in page["tables"] if table.get("rows")
             and table["rows"][0][:3] == ["순위", "마번", "마명"]), None
        )
        pass_table = next(
            (table for table in page["tables"] if table.get("rows")
             and table["rows"][0][:3] == ["순위", "마번", "S1F-1C-2C-3C-4C-G1F"]), None
        )
        if result_table is None or pass_table is None:
            raise RuntimeError(f"Missing result/pass table for {key}")

        def match_row(table: dict) -> tuple[list[str], dict[str, int]]:
            headers = table["rows"][0]
            number_index = headers.index("마번")
            matches = []
            for row in table["rows"][1:]:
                if len(row) <= number_index:
                    continue
                try:
                    displayed_number = int(row[number_index].strip())
                except ValueError:
                    continue
                if displayed_number == int(source_row["horse_number"]):
                    matches.append(row)
            if len(matches) != 1:
                raise RuntimeError(f"Website table has {len(matches)} rows for {key} #{source_row['horse_number']}")
            return matches[0], {name: headers.index(name) for name in headers}

        result_row, result_index = match_row(result_table)
        pass_row, pass_index = match_row(pass_table)
        return page, (result_row, result_index), (pass_row, pass_index)

    site_value_states = Counter()
    rank_match_count = 0
    for row in time_rows:
        page, result_data, pass_data = get_site_rows(row)
        result_row, result_index = result_data
        pass_row, pass_index = pass_data
        row["website_finish_rank"] = result_row[result_index["순위"]]
        row["website_finish_time"] = result_row[result_index["기록"]]
        row["website_finish_gap_or_status"] = result_row[result_index["도착차"]]
        row["website_pass_path_raw"] = pass_row[pass_index["S1F-1C-2C-3C-4C-G1F"]]
        for header, field in zip(point_headers, SECTION_FIELDS):
            value = pass_row[pass_index[header]]
            row[f"website_{field}"] = value
            site_value_states[value if value else "<blank>"] += 1
        row["website_finish_rank_matches_api4"] = row["website_finish_rank"].strip() == str(row["finish_position"])
        row["website_section_times_all_zero_or_blank"] = all(
            row[f"website_{field}"].strip() in ("", "0:00.0", "0:00.00", "0:00")
            for field in SECTION_FIELDS
        )
        row["website_html_path"] = page["raw_path"]
        row["website_html_sha256"] = page["sha256"]
        rank_match_count += row["website_finish_rank_matches_api4"]
    write_csv(time_csv, time_rows)

    order_summary = {"website_row_found": 0, "website_finish_rank_matches_api4": 0}
    for row in order_rows:
        page, result_data, pass_data = get_site_rows(row)
        result_row, result_index = result_data
        pass_row, pass_index = pass_data
        pass_path = pass_row[pass_index["S1F-1C-2C-3C-4C-G1F"]]
        row["website_finish_rank"] = result_row[result_index["순위"]]
        row["website_finish_time"] = result_row[result_index["기록"]]
        row["website_pass_path_raw"] = pass_path
        row["website_pass_path_has_numeric_rank"] = bool(re.search(r"\d", pass_path))
        for header in point_headers:
            row[f"website_{header}"] = pass_row[pass_index[header]]
        row["website_html_path"] = page["raw_path"]
        row["website_html_sha256"] = page["sha256"]
        order_summary["website_row_found"] += 1
        order_summary["website_finish_rank_matches_api4"] += int(
            row["website_finish_rank"].strip() == str(row["finish_position"])
        )
    write_csv(order_csv, order_rows)

    return {
        "time_zero_rows_with_official_site_pass_table": len(time_rows),
        "website_finish_rank_matches_api4_rows": rank_match_count,
        "website_section_time_cell_states": dict(site_value_states),
        "website_all_seven_section_times_zero_or_blank_rows": sum(
            row["website_section_times_all_zero_or_blank"] for row in time_rows
        ),
        "order_zero_row_website_check": order_summary,
        "order_zero_row_website_pass_path": order_rows[0]["website_pass_path_raw"],
        "order_zero_row_website_pass_path_has_numeric_rank": order_rows[0]["website_pass_path_has_numeric_rank"],
    }


def build_legacy_website_comparison_files() -> dict:
    group_comparisons_path = BASE / "group_website_comparisons.json"
    difference_review_path = BASE / "legacy_difference_website_review.json"
    group_comparisons = json.loads(group_comparisons_path.read_text(encoding="utf-8"))
    if len(group_comparisons) != 552:
        raise RuntimeError(f"Expected 552 source point comparisons; found {len(group_comparisons)}")
    by_key = {(row["date"], int(row["race_no"]), row["point"]): row for row in group_comparisons}

    target_2002 = [row for row in group_comparisons if row["date"].startswith("2002-")]
    api303_web_differences = [row for row in target_2002 if not row["api303_equal_website"]]
    if len(target_2002) != 108 or len(api303_web_differences) != 78:
        raise RuntimeError("Expected the 18 requested 2002 races to have 108 points and 78 API303/site differences")
    if any(not row["api6_equal_website"] for row in target_2002):
        raise RuntimeError("At least one API6 value differs from the official-site value in the reviewed 2002 races")
    website_fields = (
        "date", "race_no", "point", "website_raw", "api303_field", "api303_raw",
        "api303_equal_website", "api303_value_matching_website_points",
        "api6_field", "api6_raw", "api6_equal_website", "api6_value_matching_website_points",
    )
    write_csv(EVIDENCE / "website_api303_differences_78_points.csv", [
        {field: row.get(field) for field in website_fields} for row in api303_web_differences
    ])

    differences = json.loads(difference_review_path.read_text(encoding="utf-8"))
    if len(differences) != 26:
        raise RuntimeError(f"Expected 26 original API6/API303 differences; found {len(differences)}")
    if sum(bool(row["api6_equal_website"]) for row in differences) != 26:
        raise RuntimeError("API6/site equality count did not equal 26")
    if sum(bool(row["api303_equal_website"]) for row in differences) != 0:
        raise RuntimeError("API303/site equality count was nonzero for the original 26 differences")
    review_fields = (
        "date", "race_no", "point", "api303_field", "api6_field", "api303_raw", "api6_raw",
        "api6_value_matching_api303_fields", "website_raw", "api303_equal_website", "api6_equal_website",
    )
    write_csv(EVIDENCE / "api6_api303_website_review_26_points.csv", [
        {field: row.get(field) for field in review_fields} for row in differences
    ])

    audit_root = PROJECT / "jeju" / "research" / "20261002_section_passing_audit" / "root_audit"
    with (audit_root / "legacy_compact_notations.csv").open(encoding="utf-8-sig", newline="") as stream:
        compact_rows = list(csv.DictReader(stream))
    roster_by_race: dict[tuple[str, int], list[dict]] = {}
    with (EVIDENCE / "legacy_compact_race_rosters.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            roster_by_race.setdefault((row["race_date"], int(row["race_number"])), []).append(row)
    compact_out = []
    for row in compact_rows:
        key = (row["date"], int(row["race_no"]), row["point"])
        source_compare = by_key.get(key)
        if source_compare is None:
            raise RuntimeError(f"No official-site comparison for compact notation: {key}")
        roster = roster_by_race[(key[0], key[1])]
        compact_out.append({
            **row,
            "roster_program_numbers": ",".join(str(item["horse_number"]) for item in roster),
            "roster_min_program_no": min(int(item["horse_number"]) for item in roster),
            "roster_max_program_no": max(int(item["horse_number"]) for item in roster),
            "website_raw_at_point": source_compare["website_raw"],
            "api303_raw_at_point": source_compare["api303_raw"],
            "api6_raw_at_point": source_compare["api6_raw"],
            "api303_equal_website": source_compare["api303_equal_website"],
            "api6_equal_website": source_compare["api6_equal_website"],
        })
    if len(compact_out) != 10:
        raise RuntimeError(f"Expected 10 compact notation points; found {len(compact_out)}")
    write_csv(EVIDENCE / "legacy_compact_website_review_10_points.csv", compact_out)

    with (audit_root / "api6_api303_raw_differences.csv").open(encoding="utf-8-sig", newline="") as stream:
        raw_differences = list(csv.DictReader(stream))
    same_value_other_corner = sum(bool(row.get("api6_value_matching_api303_fields")) for row in raw_differences)
    return {
        "2002_website_compared_races": len({(r["date"], r["race_no"]) for r in target_2002}),
        "2002_website_compared_point_cells": len(target_2002),
        "2002_api6_exact_site_matches": sum(bool(row["api6_equal_website"]) for row in target_2002),
        "2002_api303_site_differences": len(api303_web_differences),
        "original_api6_api303_raw_disagreement_points": len(differences),
        "original_disagreements_api6_site_matches": sum(bool(row["api6_equal_website"]) for row in differences),
        "original_disagreements_api303_site_matches": sum(bool(row["api303_equal_website"]) for row in differences),
        "api6_values_also_present_in_another_api303_corner_field": same_value_other_corner,
        "legacy_compact_notation_points": len(compact_out),
        "compact_api6_exact_site_matches": sum(bool(row["api6_equal_website"]) for row in compact_out),
        "compact_api303_exact_site_matches": sum(bool(row["api303_equal_website"]) for row in compact_out),
        "compact_races": len({(r["date"], r["race_no"]) for r in compact_out}),
        "compact_race_rosters_are_single_digit_only": all(int(row["roster_max_program_no"]) < 10 for row in compact_out),
        "source_group_comparisons_sha256": hashlib.sha256(group_comparisons_path.read_bytes()).hexdigest(),
        "source_difference_review_sha256": hashlib.sha256(difference_review_path.read_bytes()).hexdigest(),
    }


def main() -> None:
    website_records = json.loads(WEB_JSON.read_text(encoding="utf-8"))
    pages = {}
    for record in website_records:
        key = (record.get("date"), int(record.get("race_no", -1)))
        if key in pages:
            raise RuntimeError(f"Duplicate website evidence key: {key}")
        raw_path = confined_path(BASE, record["raw_path"])
        raw_path.relative_to(HTML_DIR)
        blob = raw_path.read_bytes()
        if len(blob) != record["bytes"] or hashlib.sha256(blob).hexdigest() != record["sha256"]:
            raise RuntimeError(f"Website HTML hash/size mismatch: {raw_path.name}")
        if not record.get("identity_verified") or record.get("http_status") != 200:
            raise RuntimeError(f"Website page identity/HTTP check failed: {key}")
        pages[key] = record

    with AUDIT_CSV.open(encoding="utf-8-sig", newline="") as stream:
        unparsed = list(csv.DictReader(stream))
    if len(unparsed) != 162:
        raise RuntimeError(f"Expected 162 unparsed notation points; found {len(unparsed)}")

    db_uri = DB.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    conn.row_factory = sqlite3.Row
    out_rows = []
    page_keys = set()
    result_code_labels = {91: "실격", 92: "주행중지"}
    for notation_row in unparsed:
        key = (notation_row["date"], int(notation_row["race_no"]))
        page = pages.get(key)
        if page is None:
            raise RuntimeError(f"No verified official page for dot notation race: {key}")
        page_keys.add(key)
        raw_notation = notation_row["notation_raw"]
        if raw_notation.count("·") != 1:
            raise RuntimeError(f"Expected one middle dot in {key}: {raw_notation}")
        suffix = raw_notation.split("·", 1)[1]
        if not re.fullmatch(r"\(?\d+(?:,\d+)*\)?", suffix):
            raise RuntimeError(f"Unexpected dot suffix grammar in {key}: {suffix}")
        suffix_numbers = [int(value) for value in re.findall(r"\d+", suffix)]
        if len(suffix_numbers) not in (1, 2):
            raise RuntimeError(f"Unexpected suffix member count in {key}: {suffix}")
        table = next(
            (table for table in page["tables"]
             if table.get("rows") and table["rows"][0][:3] == ["순위", "마번", "마명"]),
            None,
        )
        if table is None:
            raise RuntimeError(f"No result table with rank/number/name headers: {key}")
        headers = table["rows"][0]
        rank_index = headers.index("순위")
        number_index = headers.index("마번")
        name_index = headers.index("마명")
        time_index = headers.index("기록")
        gap_index = headers.index("도착차")
        result_rows = [r for r in table["rows"][1:] if len(r) > max(rank_index, number_index, name_index, time_index, gap_index)]
        for program_no in suffix_numbers:
            site_matches = [r for r in result_rows if r[number_index].strip() == str(program_no)]
            if len(site_matches) != 1:
                raise RuntimeError(f"Official result table has {len(site_matches)} rows for {key} #{program_no}")
            site_row = site_matches[0]
            db_matches = conn.execute(
                """SELECT r.horse_id,r.horse_name,r.finish_position,r.finish_status_raw,
                          r.finish_time_seconds,a.payload_json,a.payload_sha256,
                          a.record_index,s.raw_relative_path,s.sha256 AS source_page_sha256
                   FROM race_result_rows r
                   JOIN api_records a USING(api_record_id)
                   JOIN source_artifacts s USING(source_artifact_id)
                   WHERE r.race_date=? AND r.race_number=? AND r.horse_number=?""",
                (key[0], key[1], program_no),
            ).fetchall()
            if len(db_matches) != 1:
                raise RuntimeError(f"API4 roster has {len(db_matches)} rows for {key} #{program_no}")
            db_row = db_matches[0]
            try:
                payload = json.loads(db_row["payload_json"])
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid stored API4 payload for {key} #{program_no}") from exc
            if hashlib.sha256(db_row["payload_json"].encode("utf-8")).hexdigest() != db_row["payload_sha256"]:
                raise RuntimeError(f"API4 payload hash mismatch for {key} #{program_no}")
            code = int(db_row["finish_position"]) if db_row["finish_position"] is not None else None
            expected_label = result_code_labels.get(code)
            website_label = site_row[gap_index].strip()
            api4_name = db_row["horse_name"] or ""
            website_name = site_row[name_index].strip()
            status_match = (
                expected_label is not None
                and website_label == expected_label
                and site_row[rank_index].strip() == ""
                and str(payload.get("ord")) == str(code)
            )
            if not api4_name or api4_name == website_name:
                name_match_mode = "exact"
            elif website_name.startswith("★") and website_name[1:] == api4_name:
                name_match_mode = "website_prefix_marker_only"
            else:
                name_match_mode = "unresolved_name_difference"
            out_rows.append({
                "date": key[0], "race_no": key[1], "point": notation_row["point"],
                "notation_raw": raw_notation, "dot_suffix_raw": suffix,
                "suffix_program_no": program_no, "website_place_cell": site_row[rank_index],
                "website_status_cell": website_label, "website_horse_name": website_name,
                "api4_finish_position": code, "api4_finish_status_raw": db_row["finish_status_raw"],
                "api4_horse_id": db_row["horse_id"], "api4_horse_name": api4_name,
                "api4_finish_time_seconds": db_row["finish_time_seconds"],
                "api4_raw_ord": payload.get("ord"), "api4_source_relative_path": db_row["raw_relative_path"],
                "api4_record_index": db_row["record_index"], "api4_source_page_sha256": db_row["source_page_sha256"],
                "website_html_path": page["raw_path"], "website_html_sha256": page["sha256"],
                "website_url": page["url"], "status_match": status_match,
                "horse_name_match_mode": name_match_mode,
            })

    if len(out_rows) != 166:
        raise RuntimeError(f"Expected 166 dot-suffix horse observations; found {len(out_rows)}")
    write_csv(EVIDENCE / "dot_suffix_website_api4_status_crosscheck_166.csv", out_rows)
    api4_zero_summary = build_api4_zero_files(conn)
    conn.close()
    api4_zero_summary.update(enrich_time_zero_with_website_pages())
    website_comparison_summary = build_legacy_website_comparison_files()

    status_counts = Counter(str(row["api4_finish_position"]) for row in out_rows)
    label_counts = Counter(row["website_status_cell"] for row in out_rows)
    mismatch_count = sum(not row["status_match"] for row in out_rows)
    name_marker_count = sum(row["horse_name_match_mode"] == "website_prefix_marker_only" for row in out_rows)
    unresolved_name_count = sum(row["horse_name_match_mode"] == "unresolved_name_difference" for row in out_rows)
    summary = {
        "unparsed_points": len(unparsed),
        "middle_dot_points": sum("·" in row["notation_raw"] for row in unparsed),
        "all_notations_are_dot_only_parser_exclusions": all(
            re.fullmatch(r"[0-9(),^=≡-]+", row["notation_raw"].replace("·", "").replace(" ", "")) is not None
            for row in unparsed
        ),
        "dot_suffix_horse_observations": len(out_rows),
        "unique_suffix_horses": len({(r["date"], r["race_no"], r["suffix_program_no"]) for r in out_rows}),
        "unique_suffix_races": len(page_keys),
        "official_website_pages_hash_size_identity_verified": len(page_keys),
        "all_saved_website_pages_hash_size_identity_verified": len(pages),
        "api4_finish_position_counts": dict(status_counts),
        "website_status_cell_counts": dict(label_counts),
        "status_or_identity_mismatch_observations": mismatch_count,
        "website_name_marker_only_observations": name_marker_count,
        "unresolved_horse_name_difference_observations": unresolved_name_count,
        "website_page_evidence_sha256": hashlib.sha256(WEB_JSON.read_bytes()).hexdigest(),
        "api4_zero_source_review": api4_zero_summary,
        "section_source_website_review": website_comparison_summary,
        "interpretation": "All suffix horses map by race and program number to official-site rows without a numeric placing and with a site status label matching the stored API4 special result code. The four name-display differences are a leading website star marker on the same horse name. No dot separator was normalized or used to assign individual ranks.",
    }
    (EVIDENCE / "dot_suffix_website_api4_status_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

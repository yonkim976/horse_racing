"""Read-only semantic audit of the 19 unresolved Jeju section-order races.

Inputs are retained KRA result HTML, retained API4/API303 database rows, and
retained API6 raw pages. The SQLite connection is opened with mode=ro and
query_only. This script writes only to its own semantic_review directory.
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
REVIEW = ROOT / "jeju/research/20261002_section_remaining_review"
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
API6_BASE = ROOT / "jeju/research/20260929_api_detail_sources/raw/full_year_sections_passing/20260929T143902.196014Z"
INPUT_CONFLICTS = REVIEW / "remaining_website_internal_order_conflicts.json"
INPUT_WEBSITES = REVIEW / "website_evidence.json"
INPUT_ADJUDICATIONS = REVIEW / "order_adjudications.json"

POINTS = ("S1F", "1C", "2C", "3C", "4C", "G1F")
API_FIELDS = {
    "S1F": "sjS1fOrd", "1C": "sj_1cOrd", "2C": "sj_2cOrd",
    "3C": "sj_3cOrd", "4C": "sj_4cOrd", "G1F": "sjG1fOrd",
}
ORDER_OUTPUTS = {
    "S1F": "s1f_order", "1C": "c1_order", "2C": "c2_order",
    "3C": "c3_order", "4C": "c4_order", "G1F": "g1f_order",
}
API303_FIELDS = {
    "S1F": "corner_7", "1C": "corner_1", "2C": "corner_2",
    "3C": "corner_3", "4C": "corner_4", "G1F": "corner_8",
}
API6_FIELDS = {
    "S1F": "passrankS1f", "1C": "passrankG8f_1c", "2C": "passrankG6f_2c",
    "3C": "passrankG4f_3c", "4C": "passrankG3f_4c", "G1F": "passrankG1f",
}
API_TIME_FIELDS = {
    "S1F": "jeS1fTime", "1C": "je_1cTime", "2C": "je_2cTime",
    "3C": "je_3cTime", "4C": "je_4cTime", "G1F": "jeG1fTime",
}
WEBSITE_GROUP_LABELS = {
    "S-1F": "S1F", "1코너": "1C", "2코너": "2C",
    "3코너": "3C", "4코너": "4C", "G-1F": "G1F",
}
WEBSITE_TIME_COLS = {"S1F": 3, "1C": 4, "2C": 5, "3C": 6, "4C": 7, "G1F": 9}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def page_table(web, heading):
    matches = [table["rows"] for table in web["tables"] if table.get("rows") and heading in table["rows"][0]]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one table headed by {heading!r}; found {len(matches)}")
    return matches[0]


def seconds(value):
    if value is None:
        return None
    s = str(value).strip()
    if s in ("", "-", "X", "0", "0.0", "0:00.0", "0:00.0.0"):
        return None
    try:
        if ":" in s:
            minute, sec = s.split(":", 1)
            value = int(minute) * 60 + float(sec)
        else:
            value = float(s)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def positive_rank(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
        if float(value) != number or not 1 <= number <= 89:
            return None
        return number
    except (TypeError, ValueError):
        return None


def parse_groups(raw):
    """Parse only the documented modern group grammar; return None otherwise."""
    s = re.sub(r"\s+", "", str(raw or ""))
    if not s or not re.fullmatch(r"[0-9(),^=≡\-]+", s):
        return None
    tokens = list(re.finditer(r"\([^()]+\)|\^?\d+", s))
    end = 0
    groups = []
    for token in tokens:
        between = s[end:token.start()]
        if between and not re.fullmatch(r"[,=≡\-]+", between):
            return None
        text = token.group()
        if text.startswith("("):
            if not re.fullmatch(r"\(\^?\d+(?:,\^?\d+)*\)", text):
                return None
        groups.append([int(n) for n in re.findall(r"\d+", text)])
        end = token.end()
    if end != len(s) or not groups:
        return None
    return groups


def bounds_from_groups(groups):
    bounds = {}
    pos = 1
    for group in groups:
        lo, hi = pos, pos + len(group) - 1
        for number in group:
            bounds[number] = (lo, hi)
        pos = hi + 1
    return bounds


def rank_distribution(values, roster_size):
    observed = [v for v in values if v is not None]
    counts = collections.Counter(observed)
    positive = sorted(v for v in observed if 1 <= v <= 89)
    return {
        "roster_size": roster_size,
        "positive_count": len(positive),
        "missing_count": len(values) - len(observed),
        "zero_count": sum(v == 0 for v in observed),
        "sentinel_or_out_of_range_count": sum(v < 0 or v >= 90 for v in observed),
        "duplicate_positive_rank_values": {str(k): v for k, v in sorted(counts.items()) if 1 <= k <= 89 and v > 1},
        "positive_rank_gaps_1_to_roster": [n for n in range(1, roster_size + 1) if n not in set(positive)],
        "positive_rank_values_outside_1_to_roster": [v for v in positive if v > roster_size],
        "positive_rank_is_permutation_1_to_roster": sorted(positive) == list(range(1, roster_size + 1)),
    }


def time_rank_bounds(time_by_no):
    valid = {n: t for n, t in time_by_no.items() if t is not None}
    output = {}
    for number, value in valid.items():
        lower = 1 + sum(other < value for other in valid.values())
        upper = sum(other <= value for other in valid.values())
        output[number] = (lower, upper)
    return output


def load_api6_for_years(years):
    manifest = read_json(API6_BASE / "run_manifest.json")
    out = {}
    counts = {"pages_checked": 0, "rows_loaded": 0}
    for dataset_name, target in (("passing_corner", "corner"), ("detail_section", "section")):
        for year in manifest["datasets"][dataset_name]["yearly"]:
            if int(year["year"]) not in years:
                continue
            for page in year["pages"]:
                path = (API6_BASE / page["response_file"]).resolve()
                if not path.is_relative_to(API6_BASE.resolve()):
                    raise ValueError("API6 source path escaped the retained raw directory")
                blob = path.read_bytes()
                if hashlib.sha256(blob).hexdigest() != page["response_sha256"]:
                    raise ValueError(f"API6 retained page hash mismatch: {page['response_file']}")
                payload = json.loads(blob)
                items = payload["response"]["body"]["items"]["item"]
                items = items if isinstance(items, list) else [items]
                counts["pages_checked"] += 1
                counts["rows_loaded"] += len(items)
                for item in items:
                    date = str(item["rcDate"])
                    key = (f"{date[:4]}-{date[4:6]}-{date[6:]}", int(item["rcNo"]))
                    out[(target, key)] = item
    return out, counts


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    conflicts = read_json(INPUT_CONFLICTS)
    conflict_keys = {(r["date"], int(r["race_no"])) for r in conflicts}
    websites = read_json(INPUT_WEBSITES)
    website_by_key = {(w["date"], int(w["race_no"])): w for w in websites}
    adjudications = read_json(INPUT_ADJUDICATIONS)
    official_conflicts = [r for r in adjudications if r.get("adjudication") == "website_also_individual_vs_group_conflict"]
    if len(conflicts) != 70 or len(conflict_keys) != 19 or len(official_conflicts) != 70:
        raise ValueError("The retained input no longer has the expected 70 observations / 19 races")

    db = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    api4 = {}
    api303 = {}
    roster_rows = {}
    for key in sorted(conflict_keys):
        rows = db.execute(
            "SELECT r.*, a.payload_json, a.payload_sha256, a.source_artifact_id "
            "FROM race_result_rows AS r JOIN api_records AS a USING (api_record_id) "
            "WHERE r.race_date=? AND r.meet_code=2 AND r.race_number=? ORDER BY r.horse_number",
            key,
        ).fetchall()
        roster_rows[key] = [dict(row) for row in rows]
        for row in rows:
            if row["horse_number"] is not None:
                api4[(key, int(row["horse_number"]))] = json.loads(row["payload_json"])
        corner = db.execute(
            "SELECT a.payload_json, a.payload_sha256 FROM api303_corner_rank_rows AS c "
            "JOIN api_records AS a USING (api_record_id) WHERE c.race_date=? AND c.race_number=?",
            key,
        ).fetchall()
        if len(corner) > 1:
            raise ValueError(f"Duplicate API303 source row for {key}")
        if corner:
            api303[key] = json.loads(corner[0]["payload_json"])
    db.close()

    api6, api6_counts = load_api6_for_years({int(d[:4]) for d, _ in conflict_keys})
    group_reviews = []
    runner_reviews = []
    action_fields = []
    action_groups = []
    mapping_hypotheses = []
    source_checks = []
    missing_groups = []
    identity_checks = []
    empty_group_labels = []

    for key in sorted(conflict_keys):
        date, race_no = key
        web = website_by_key[key]
        raw_html_path = (REVIEW / web["raw_path"]).resolve()
        if not raw_html_path.is_relative_to(REVIEW.resolve()):
            raise ValueError("Retained KRA HTML path escaped the evidence directory")
        raw_html = raw_html_path.read_bytes()
        html_sha = hashlib.sha256(raw_html).hexdigest()
        if html_sha != web["sha256"]:
            raise ValueError(f"Retained KRA page hash mismatch for {date} R{race_no}")

        detail = page_table(web, "마명")
        split = page_table(web, "S-1F")
        split_rows = {int(row[1]): row for row in split[1:] if len(row) > 2 and str(row[1]).strip().isdigit()}
        detail_rows = {int(row[1]): row for row in detail[1:] if len(row) > 2 and str(row[1]).strip().isdigit()}
        db_numbers = {int(row["horse_number"]) for row in roster_rows[key] if row["horse_number"] is not None}
        web_numbers = set(detail_rows)
        if db_numbers != web_numbers or set(split_rows) != web_numbers:
            identity_checks.append({
                "date": date, "race_no": race_no,
                "database_roster_numbers": sorted(db_numbers), "website_result_roster_numbers": sorted(web_numbers),
                "website_section_table_numbers": sorted(split_rows), "roster_numbers_match": db_numbers == web_numbers == set(split_rows),
            })
        html_soup = BeautifulSoup(raw_html, "html.parser")
        link_ids = {}
        for anchor in html_soup.find_all("a", href=True):
            m = re.fullmatch(r"javascript:goHorse\('(\d+)','2'\)", anchor["href"])
            if m:
                link_ids[anchor.get_text(strip=True)] = m.group(1)

        api_rows = {int(r["horse_number"]): r for r in roster_rows[key] if r["horse_number"] is not None}
        by_point = {}
        group_table = page_table(web, "통과순위")
        # KRA places S-1F in the table's header row; later points occupy body rows.
        for row in group_table:
            for cell in row:
                compact_cell = re.sub(r"\s+", " ", str(cell)).strip()
                for label, point in WEBSITE_GROUP_LABELS.items():
                    prefix = label + ":"
                    if compact_cell.startswith(prefix):
                        group_value = compact_cell.split(":", 1)[1].strip()
                        if group_value:
                            by_point[point] = group_value
                        else:
                            empty_group_labels.append({"date": date, "race_no": race_no, "point": point, "status": "blank_or_unused_on_official_page"})

        website_orders = {}
        website_times = {}
        for number, row in split_rows.items():
            rank_parts = [value.strip() for value in str(row[2]).split("-")]
            if len(rank_parts) == 7 and not rank_parts[-1]:
                rank_parts.pop()
            if len(rank_parts) != 6:
                raise ValueError(f"Unexpected website rank column count for {date} R{race_no} #{number}: {rank_parts}")
            for idx, point in enumerate(POINTS):
                text = rank_parts[idx]
                website_orders[(number, point)] = positive_rank(text) if text else None
                col = WEBSITE_TIME_COLS[point]
                website_times[(number, point)] = seconds(row[col] if len(row) > col else None)
            website_times[(number, "FINISH")] = seconds(row[10] if len(row) > 10 else None)

        all_present_points = [point for point in POINTS if point in by_point]
        for point in all_present_points:
            raw_group = by_point[point]
            parsed = parse_groups(raw_group)
            roster_numbers = sorted(web_numbers)
            flat = [number for group in parsed for number in group] if parsed else []
            counts = collections.Counter(flat)
            extras = sorted(set(flat) - web_numbers)
            missing = sorted(web_numbers - set(flat))
            duplicates = sorted(number for number, count in counts.items() if count > 1)
            structurally_complete = parsed is not None and not extras and not missing and not duplicates
            bounds = bounds_from_groups(parsed) if structurally_complete else {}
            point_rows = []
            candidate_bounds_counts = {}
            for candidate_point, field in API_FIELDS.items():
                examined = 0
                violations = 0
                absent = 0
                for number in roster_numbers:
                    rank = positive_rank(api4.get((key, number), {}).get(field))
                    if rank is None:
                        continue
                    examined += 1
                    if number not in bounds:
                        absent += 1
                    elif not bounds[number][0] <= rank <= bounds[number][1]:
                        violations += 1
                candidate_bounds_counts[candidate_point] = {"examined": examined, "out_of_bounds": violations, "positive_rank_horse_absent_from_group": absent}
            time_by_no = {}
            for number in roster_numbers:
                if point == "G1F":
                    finish = website_times.get((number, "FINISH"))
                    final_split = website_times.get((number, "G1F"))
                    elapsed = round(finish - final_split, 1) if finish is not None and final_split is not None and finish > final_split else None
                    time_by_no[number] = elapsed
                else:
                    time_by_no[number] = website_times.get((number, point))
            t_bounds = time_rank_bounds(time_by_no)
            same_point_group_violations = 0
            same_point_website_violations = 0
            same_point_api_violations = 0
            time_bounds_violations = 0
            missing_individual = 0
            time_order_matches_rank = 0
            time_order_compared = 0
            for number in roster_numbers:
                api_raw = api4.get((key, number), {})
                api_rank = positive_rank(api_raw.get(API_FIELDS[point]))
                web_rank = website_orders.get((number, point))
                lohi = bounds.get(number)
                time_lohi = t_bounds.get(number)
                if lohi is not None:
                    if api_rank is None or web_rank is None:
                        missing_individual += 1
                    else:
                        if not lohi[0] <= api_rank <= lohi[1]:
                            same_point_api_violations += 1
                        if not lohi[0] <= web_rank <= lohi[1]:
                            same_point_website_violations += 1
                            same_point_group_violations += 1
                if time_lohi is not None and lohi is not None and not (lohi[0] <= time_lohi[1] and time_lohi[0] <= lohi[1]):
                    time_bounds_violations += 1
                if web_rank is not None and time_lohi is not None:
                    time_order_compared += 1
                    if time_lohi[0] <= web_rank <= time_lohi[1]:
                        time_order_matches_rank += 1
                group_membership = next((gi + 1 for gi, g in enumerate(parsed or []) if number in g), None)
                group_bounds = bounds.get(number)
                time_value = time_by_no.get(number)
                is_flagged = any((x["date"], int(x["race_no"]), x["point"], int(x["program_no"])) == (date, race_no, point, number) for x in conflicts)
                point_rows.append({
                    "date": date, "race_no": race_no, "point": point, "program_no": number,
                    "horse_id": api_rows.get(number, {}).get("horse_id"),
                    "api4_field": API_FIELDS[point], "api4_order": api_rank,
                    "website_order": web_rank, "rank_flagged_in_existing_70": is_flagged,
                    "group_no": group_membership, "group_rank_min": group_bounds[0] if group_bounds else None,
                    "group_rank_max": group_bounds[1] if group_bounds else None,
                    "individual_time_seconds": website_times.get((number, point)),
                    "time_order_seconds_used": time_value,
                    "time_rank_min": time_lohi[0] if time_lohi else None,
                    "time_rank_max": time_lohi[1] if time_lohi else None,
                    "time_rank_overlaps_group_bounds": bool(time_lohi and group_bounds and time_lohi[0] <= group_bounds[1] and group_bounds[0] <= time_lohi[1]),
                    "time_rank_contains_website_order": bool(time_lohi and web_rank is not None and time_lohi[0] <= web_rank <= time_lohi[1]),
                })
            runner_reviews.extend(point_rows)
            mapping_hypotheses.append({
                "date": date, "race_no": race_no, "group_point": point,
                "official_group_raw": raw_group, "candidate_api4_rank_fields": candidate_bounds_counts,
                "native_mapping_field": API_FIELDS[point],
                "native_mapping_out_of_bounds": candidate_bounds_counts[point]["out_of_bounds"],
                "native_mapping_examined": candidate_bounds_counts[point]["examined"],
                "lowest_violation_candidate_fields": [name for name, value in candidate_bounds_counts.items()
                    if value["examined"] > 0 and value["out_of_bounds"] == min(v["out_of_bounds"] for v in candidate_bounds_counts.values() if v["examined"] > 0)],
                "interpretation": "Field-shift diagnostic only; fields are not remapped and this is not an optimal-match correction.",
            })

            if (date, race_no, point) in {(r["date"], int(r["race_no"]), r["point"]) for r in conflicts}:
                action_groups.append({
                    "date": date, "race_no": race_no, "point": point,
                    "api303_group_field": API303_FIELDS[point], "api303_group_raw": api303.get(key, {}).get(API303_FIELDS[point]),
                    "api6_group_field": API6_FIELDS[point],
                    "api6_group_raw": api6.get(("section", key), {}).get(API6_FIELDS[point]),
                    "website_group_raw": raw_group,
                    "api303_matches_website": compact_norm(api303.get(key, {}).get(API303_FIELDS[point])) == compact_norm(raw_group),
                    "api6_matches_website": compact_norm(api6.get(("section", key), {}).get(API6_FIELDS[point])) == compact_norm(raw_group),
                    "group_grammar_parsed": parsed is not None, "roster_group_membership_complete": structurally_complete,
                    "group_rank_interval_output": "NULL/withhold derived ranks at this point" if structurally_complete else "NULL/unparsed; retain raw source",
                    "withhold_from_selected_features": "group rank/interval derived from this point",
                    "preserve_raw_group": raw_group,
                })

            group_reviews.append({
                "date": date, "race_no": race_no, "point": point, "website_group_raw": raw_group,
                "official_symbol_grammar_parsed": parsed is not None,
                "group_count": len(parsed or []), "listed_member_count": len(flat), "full_website_roster_count": len(web_numbers),
                "group_numbers_duplicate": duplicates, "group_numbers_missing_from_full_roster": missing,
                "group_numbers_not_in_full_roster": extras, "cross_group_bounds_valid_for_all_roster": structurally_complete,
                "all_same_point_api4_positive_ranks_examined": candidate_bounds_counts[point]["examined"],
                "all_same_point_api4_bounds_violations": same_point_api_violations,
                "all_same_point_website_positive_ranks_examined": sum(website_orders.get((n, point)) is not None for n in web_numbers),
                "all_same_point_website_bounds_violations": same_point_website_violations,
                "preexisting_conflict_observations": sum((r["date"], int(r["race_no"]), r["point"]) == (date, race_no, point) for r in conflicts),
                "time_order_kind": "finish_time_minus_G1F_split" if point == "G1F" else "individual_cumulative_passing_time",
                "time_valid_runner_count": len(t_bounds), "time_bounds_violations": time_bounds_violations,
                "individual_order_vs_time_rank_matches": time_order_matches_rank,
                "individual_order_vs_time_rank_compared": time_order_compared,
                "time_rank_requires_selection_review": same_point_website_violations > 0 and time_bounds_violations > 0,
                "time_interpretation_limit": "Rounded individual times are diagnostic cross-checks; they do not establish the correct source field.",
            })
            if not structurally_complete:
                missing_groups.append(group_reviews[-1])

        for number in sorted(web_numbers):
            api_row = api_rows.get(number)
            if api_row is None:
                continue
            dbname = str(api_row["horse_name"] or "")
            webname = str(detail_rows[number][2] or "")
            webid = link_ids.get(webname)
            identity_checks.append({
                "date": date, "race_no": race_no, "program_no": number,
                "api_horse_id": api_row["horse_id"], "website_horse_id": webid,
                "api_horse_name": dbname, "website_horse_name": webname,
                "horse_id_matches": webid == api_row["horse_id"],
                "name_matches_ignoring_star": webname.removeprefix("★") == dbname,
            })

        for point in POINTS:
            if point not in by_point:
                continue
            source = api4
            for number in sorted(web_numbers):
                api_raw = source.get((key, number), {})
                raw_order = api_raw.get(API_FIELDS[point])
                raw_time = seconds(api_raw.get(API_TIME_FIELDS[point]))
                web_time = website_times.get((number, point))
                runner_reviews_row = next((r for r in runner_reviews if (r["date"], r["race_no"], r["point"], r["program_no"]) == (date, race_no, point, number)), None)
                if runner_reviews_row and runner_reviews_row["rank_flagged_in_existing_70"]:
                    api_rank = positive_rank(raw_order)
                    effective_time = runner_reviews_row["time_order_seconds_used"]
                    effective_rank = runner_reviews_row["time_rank_min"] if runner_reviews_row["time_rank_min"] == runner_reviews_row["time_rank_max"] else None
                    action_fields.append({
                        "date": date, "race_no": race_no, "point": point,
                        "program_no": number, "horse_id": api_rows[number]["horse_id"],
                        "api4_raw_field": API_FIELDS[point], "selection_field": ORDER_OUTPUTS[point],
                        "api4_raw_order": raw_order, "api4_order_integer": api_rank,
                        "website_order": website_orders.get((number, point)),
                        "website_group_raw": by_point[point],
                        "group_rank_min": runner_reviews_row["group_rank_min"], "group_rank_max": runner_reviews_row["group_rank_max"],
                        "individual_time_api4_seconds": raw_time, "individual_time_website_seconds": web_time,
                        "time_order_seconds_used": effective_time, "time_rank_min": runner_reviews_row["time_rank_min"],
                        "time_rank_max": runner_reviews_row["time_rank_max"],
                        "time_rank_overlaps_group_bounds": runner_reviews_row["time_rank_overlaps_group_bounds"],
                        "API4_time_equals_website": raw_time == web_time,
                        "API4_order_equals_website": api_rank == website_orders.get((number, point)),
                        "selected_value": None, "recommended_selected_status": "unresolved_conflict_hold",
                        "reason": "KRA individual rank and same-page group rank bounds conflict; no replacement rank selected.",
                    })
            group_value = by_point.get(point)
            if group_value:
                source_checks.append({
                    "date": date, "race_no": race_no, "point": point,
                    "api303_raw": api303.get(key, {}).get(API303_FIELDS[point]),
                    "api6_raw": api6.get(("section", key), {}).get(API6_FIELDS[point]),
                    "website_raw": group_value,
                    "api303_matches_website": compact_norm(api303.get(key, {}).get(API303_FIELDS[point])) == compact_norm(group_value),
                    "api6_matches_website": compact_norm(api6.get(("section", key), {}).get(API6_FIELDS[point])) == compact_norm(group_value),
                })

    field_counts = collections.Counter((row["date"], row["race_no"], row["point"], row["program_no"]) for row in action_fields)
    if len(action_fields) != 70 or any(value != 1 for value in field_counts.values()):
        expected = {(r["date"], int(r["race_no"]), r["point"], int(r["program_no"])) for r in conflicts}
        actual = set(field_counts)
        missing = sorted(expected - actual)
        details = [r for r in runner_reviews if any((r["date"], r["race_no"], r["point"], r["program_no"]) == m for m in missing)]
        raise ValueError(f"Field hold list mismatch: {len(action_fields)}; missing={missing}; details={details[:20]}")
    action_groups.sort(key=lambda row: (row["date"], int(row["race_no"]), POINTS.index(row["point"])))
    action_fields.sort(key=lambda row: (row["date"], int(row["race_no"]), POINTS.index(row["point"]), row["program_no"]))

    # Separate diagnostic for the 2025-11-01 5R riderless/stopped runner.
    special_key = ("2025-11-01", 5)
    special_no = 2
    special_source = next(r for r in roster_rows[special_key] if r["horse_number"] == special_no)
    special_detail = page_table(website_by_key[special_key], "마명")
    special_web_row = next(r for r in special_detail[1:] if str(r[1]).strip() == str(special_no))
    special_checks = []
    for point in ("4C", "G1F"):
        point_rows = [r for r in runner_reviews if (r["date"], r["race_no"], r["point"]) == (special_key[0], special_key[1], point)]
        group_review = next(r for r in group_reviews if (r["date"], r["race_no"], r["point"]) == (special_key[0], special_key[1], point))
        intervals = {r["program_no"]: (r["group_rank_min"], r["group_rank_max"]) for r in point_rows}
        special_point_row = next(r for r in point_rows if r["program_no"] == special_no)
        survivor_rows = [r for r in point_rows if r["program_no"] != special_no]
        compressed_checks = []
        for row in survivor_rows:
            raw_order = positive_rank(api4.get((special_key, row["program_no"]), {}).get(API_FIELDS[point]))
            compressed = raw_order - 1 if raw_order is not None and raw_order > 1 else None
            lo, hi = intervals[row["program_no"]]
            compressed_checks.append({
                "program_no": row["program_no"], "horse_id": row["horse_id"], "api4_order_raw": raw_order,
                "diagnostic_rank_after_excluding_special_runner": compressed,
                "group_rank_min": lo, "group_rank_max": hi,
                "compressed_rank_within_group_bounds": compressed is not None and lo is not None and lo <= compressed <= hi,
            })
        surviving_times = {r["program_no"]: r["time_order_seconds_used"] for r in survivor_rows}
        surviving_time_ranks = time_rank_bounds(surviving_times)
        time_checks = []
        for row in survivor_rows:
            tlohi = surviving_time_ranks.get(row["program_no"])
            lo, hi = intervals[row["program_no"]]
            time_checks.append({
                "program_no": row["program_no"], "time_order_seconds_used": row["time_order_seconds_used"],
                "time_rank_after_excluding_special_runner_min": tlohi[0] if tlohi else None,
                "time_rank_after_excluding_special_runner_max": tlohi[1] if tlohi else None,
                "group_rank_min": lo, "group_rank_max": hi,
                "time_rank_overlaps_group_bounds": bool(tlohi and lo is not None and tlohi[0] <= hi and lo <= tlohi[1]),
            })
        special_checks.append({
            "point": point,
            "website_group_raw": group_review["website_group_raw"],
            "special_horse_number": special_no,
            "special_horse_id": special_source["horse_id"],
            "special_horse_name": special_source["horse_name"],
            "website_result_place_text": special_web_row[11] if len(special_web_row) > 11 else None,
            "api_finish_position": special_source["finish_position"],
            "api_finish_status_raw": special_source["finish_status_raw"],
            "api_finish_time_seconds": special_source["finish_time_seconds"],
            "special_horse_api4_order": positive_rank(api4[(special_key, special_no)].get(API_FIELDS[point])),
            "special_horse_website_order": special_point_row["website_order"],
            "special_horse_group_rank_min": intervals[special_no][0],
            "special_horse_group_rank_max": intervals[special_no][1],
            "special_horse_4c_time_seconds": seconds(api4[(special_key, special_no)].get("je_4cTime")),
            "special_horse_g1f_split_seconds": seconds(api4[(special_key, special_no)].get("jeG1fTime")),
            "surviving_runner_count": len(survivor_rows),
            "surviving_runners_compressed_rank_within_group_count": sum(r["compressed_rank_within_group_bounds"] for r in compressed_checks),
            "surviving_runners_compressed_rank_checked": len(compressed_checks),
            "surviving_runner_time_ranks_within_group_count": sum(r["time_rank_overlaps_group_bounds"] for r in time_checks),
            "surviving_runner_time_ranks_checked": sum(r["time_rank_after_excluding_special_runner_min"] is not None for r in time_checks),
            "rank_compression_diagnostic": compressed_checks,
            "time_rank_exclusion_diagnostic": time_checks,
            "interpretation": "Removing #2 only from this comparison and decrementing the other nine positive ranks reproduces the group intervals in these checks. This explains a special-result rank-denominator pattern; it is not a source correction or permission to alter retained ranks/group text.",
        })
    special_case = {
        "race": {"date": special_key[0], "race_no": special_key[1]},
        "runner": {"program_no": special_no, "horse_id": special_source["horse_id"], "horse_name": special_source["horse_name"],
            "api_finish_position": special_source["finish_position"], "api_finish_status_raw": special_source["finish_status_raw"],
            "api_finish_time_seconds": special_source["finish_time_seconds"], "website_result_place_text": special_web_row[11] if len(special_web_row) > 11 else None},
        "points": special_checks,
        "decision": "Special-result comparison hypothesis only; retain API4 raw values and official group raw values, and keep both comparison feature families NULL where the parent quality view masks them.",
    }
    write_json(HERE / "special_result_case_20251101_5R.json", special_case)

    all_group_violations = [r for r in group_reviews if r["all_same_point_website_bounds_violations"]]
    outside_old = [r for r in runner_reviews if r["point"] in {g["point"] for g in group_reviews if g["date"] == r["date"] and g["race_no"] == r["race_no"]}
                   and r["website_order"] is not None and r["group_rank_min"] is not None
                   and not r["group_rank_min"] <= r["website_order"] <= r["group_rank_max"]
                   and not r["rank_flagged_in_existing_70"]]
    time_candidates = [r for r in action_fields if r["individual_time_api4_seconds"] is not None and
                       r["time_rank_min"] is not None and r["group_rank_min"] is not None and
                       not r["time_rank_overlaps_group_bounds"]]
    summary = {
        "scope": "19 retained official KRA result pages; complete result rosters; retained API4/API303 rows and API6 raw pages",
        "official_website_pages": len(conflict_keys), "races": len(conflict_keys),
        "existing_unresolved_conflict_observations": len(conflicts), "existing_unresolved_conflict_points": len(action_groups),
        "existing_conflict_race_count": len(conflict_keys), "individual_field_hold_rows": len(action_fields),
        "point_group_feature_hold_rows": len(action_groups),
        "additional_same_point_website_rank_bounds_violations_outside_existing_70": len(outside_old),
        "additional_outside_70_examples": outside_old[:50],
        "group_points_with_any_same_point_website_bounds_violation": len(all_group_violations),
        "group_points_examined": len(group_reviews),
        "blank_or_unused_group_point_labels": len(empty_group_labels),
        "blank_or_unused_group_point_examples": empty_group_labels,
        "all_group_points_with_complete_unique_roster_membership": sum(r["cross_group_bounds_valid_for_all_roster"] for r in group_reviews),
        "all_group_points_unparsed_or_roster_mismatch": len(missing_groups),
        "api4_website_order_equal_for_70": sum(r["API4_order_equals_website"] for r in action_fields),
        "api4_website_time_equal_for_70": sum(r["API4_time_equals_website"] for r in action_fields),
        "time_derived_rank_outside_same_page_group_bounds_among_70": len(time_candidates),
        "time_derived_rank_outside_group_examples": time_candidates,
        "all_70_time_rank_vs_official_order_counts": {
            "overlaps": sum(r["time_rank_min"] is not None and r["time_rank_max"] is not None and r["website_order"] is not None and r["time_rank_min"] <= r["website_order"] <= r["time_rank_max"] for r in action_fields),
            "does_not_overlap": sum(r["time_rank_min"] is not None and r["time_rank_max"] is not None and r["website_order"] is not None and not r["time_rank_min"] <= r["website_order"] <= r["time_rank_max"] for r in action_fields),
            "time_missing": sum(r["time_rank_min"] is None for r in action_fields),
        },
        "time_review_candidate_fields": [{"date": r["date"], "race_no": r["race_no"], "point": r["point"], "program_no": r["program_no"], "horse_id": r["horse_id"], "time_seconds": r["individual_time_api4_seconds"], "time_rank_min": r["time_rank_min"], "time_rank_max": r["time_rank_max"], "group_rank_min": r["group_rank_min"], "group_rank_max": r["group_rank_max"], "rank": r["website_order"]} for r in time_candidates],
        "api303_group_source_matches_website_at_20_conflict_points": sum(r["api303_matches_website"] for r in action_groups),
        "api6_group_source_matches_website_at_20_conflict_points": sum(r["api6_matches_website"] for r in action_groups),
        "all_database_website_roster_number_and_horse_identity_checks_pass": all(r.get("roster_numbers_match", True) and r.get("horse_id_matches", True) for r in identity_checks),
        "database_roster_issues": [r for r in identity_checks if "roster_numbers_match" in r and not r["roster_numbers_match"]],
        "horse_identity_issues": [r for r in identity_checks if "horse_id_matches" in r and not r["horse_id_matches"]],
        "api6_retained_source_integrity": api6_counts,
        "rank_field_shift_hypotheses": mapping_hypotheses,
        "rank_field_shift_hypothesis_limit": "Per-point candidate-field counts are descriptive only. They do not license an order-field swap, lag correction, or optimal matching.",
        "official_grammar_limit": "KRA defines the symbols and pack/gap semantics, but no source states that parentheses expose a member's exact ordinal rank; no within-parenthesis rank is reconstructed.",
        "selection_guidance": {
            "withhold_individual_selection_fields": sorted({r["selection_field"] for r in action_fields}),
            "withhold_individual_field_rows": [{"date": r["date"], "race_no": r["race_no"], "point": r["point"], "horse_id": r["horse_id"], "program_no": r["program_no"], "selection_field": r["selection_field"]} for r in action_fields],
            "withhold_group_derived_features": [{"date": r["date"], "race_no": r["race_no"], "point": r["point"], "raw_group_preserved": r["preserve_raw_group"]} for r in action_groups],
            "do_not_select_replacement_order": True,
        },
    }
    write_json(HERE / "semantic_audit_summary.json", summary)
    write_json(HERE / "field_hold_candidates.json", action_fields)
    write_json(HERE / "group_feature_hold_candidates.json", action_groups)
    write_json(HERE / "rank_field_shift_hypotheses.json", mapping_hypotheses)
    write_json(HERE / "group_point_audit.json", group_reviews)
    write_json(HERE / "special_result_case_20251101_5R.json", special_case)
    write_json(HERE / "runner_point_audit.json", runner_reviews)
    write_json(HERE / "source_crosscheck.json", source_checks)
    write_json(HERE / "identity_roster_checks.json", identity_checks)
    write_csv(HERE / "field_hold_candidates.csv", action_fields)
    write_csv(HERE / "group_feature_hold_candidates.csv", action_groups)
    write_csv(HERE / "group_point_audit.csv", group_reviews)
    write_csv(HERE / "runner_point_audit.csv", runner_reviews)
    write_csv(HERE / "rank_field_shift_hypotheses.csv", mapping_hypotheses)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("rank_field_shift_hypotheses", "selection_guidance", "time_review_candidate_fields", "time_derived_rank_outside_group_examples")}, ensure_ascii=False, indent=2))


def compact_norm(value):
    return re.sub(r"\s+", "", str(value or ""))


if __name__ == "__main__":
    main()

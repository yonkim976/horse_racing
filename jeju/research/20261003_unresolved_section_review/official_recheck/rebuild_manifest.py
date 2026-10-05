"""Build source-consistent evidence from already archived HTTP response bytes."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
PREVIOUS = ROOT / "jeju/research/20261002_section_remaining_review"
LABELS = {"S-1F": "S1F", "1코너": "1C", "2코너": "2C", "3코너": "3C", "4코너": "4C", "G-1F": "G1F"}
POINTS = ["S1F", "1C", "2C", "3C", "4C", "G1F"]


def clean(cell) -> str:
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).replace("\xa0", " ").strip()


def get_tables(soup):
    output = []
    for table in soup.find_all("table"):
        rows = [
            [clean(cell) for cell in row.find_all(["th", "td"], recursive=False)]
            for row in table.find_all("tr")
        ]
        rows = [row for row in rows if row]
        if rows:
            output.append({
                "caption": clean(table.find("caption")) if table.find("caption") else None,
                "rows": rows,
            })
    return output


def groups_from_tables(tables):
    group_table = next((t["rows"] for t in tables if t["rows"] and t["rows"][0][0] == "통과순위"), [])
    groups = {}
    for row in group_table:
        for cell in row:
            for label, point in LABELS.items():
                if cell.startswith(label + ":"):
                    groups[point] = cell.split(":", 1)[1].strip()
    return groups


def parse_groups(value):
    text = str(value).replace(" ", "")
    if not re.fullmatch(r"[0-9(),^=≡\-]+", text):
        return None
    matches = list(re.finditer(r"\([^()]+\)|\^?\d+", text))
    end = 0
    groups = []
    for match in matches:
        if text[end:match.start()] and not re.fullmatch(r"[,=≡\-]+", text[end:match.start()]):
            return None
        token = match.group()
        values = [int(value) for value in re.findall(r"\d+", token)]
        if token.startswith("(") and not re.fullmatch(r"\(\^?\d+(?:,\^?\d+)*\)", token):
            return None
        groups.append(values)
        end = match.end()
    if end != len(text):
        return None
    return groups


def parse_page(blob: bytes, encoding: str, key: tuple[str, int]) -> dict:
    soup = BeautifulSoup(blob, "html.parser", from_encoding=encoding or "euc-kr")
    tables = get_tables(soup)
    heading = None
    for table in tables:
        joined = " ".join(value for row in table["rows"] for value in row)
        match = re.search(r"(\d{4})년\s+(\d{2})월\s+(\d{2})일.*?제\s*(\d+)경주\s+제주", joined)
        if match and (f"{match[1]}-{match[2]}-{match[3]}", int(match[4])) == key:
            heading = table["rows"]

    ids_by_name = {}
    for anchor in soup.find_all("a", href=True):
        match = re.fullmatch(r"javascript:goHorse\('(\d+)','2'\)", anchor["href"].strip())
        if match:
            ids_by_name[anchor.get_text(strip=True)] = match[1]

    result_table = next((t["rows"] for t in tables if t["rows"] and "순위" in t["rows"][0] and "마번" in t["rows"][0] and "마명" in t["rows"][0]), [])
    passing_table = next((t["rows"] for t in tables if t["rows"] and "S1F-1C-2C-3C-4C-G1F" in " ".join(t["rows"][0])), [])
    finish = {}
    for row in result_table[1:]:
        if len(row) >= 3 and row[1].isdigit():
            finish[int(row[1])] = {"finish_rank_raw": row[0], "horse_name_raw": row[2]}

    runners = {}
    for row in passing_table[1:]:
        if len(row) < 3 or not row[1].isdigit():
            continue
        number = int(row[1])
        path_parts = row[2].split("-")
        path_by_point = dict(zip(POINTS, path_parts)) if len(path_parts) == 6 else None
        fin = finish.get(number, {})
        runners[number] = {
            "program_no": number,
            "horse_name_raw": fin.get("horse_name_raw"),
            "horse_id": ids_by_name.get(fin.get("horse_name_raw", "")),
            "finish_rank_raw": fin.get("finish_rank_raw"),
            "passing_order_path_raw": row[2],
            "six_point_order_raw": path_parts,
            "passing_order_by_point_raw": path_by_point,
            "passing_table_point_cells_raw": row[3:],
        }
    for number, fin in finish.items():
        if number not in runners:
            runners[number] = {
                "program_no": number,
                "horse_name_raw": fin["horse_name_raw"],
                "horse_id": ids_by_name.get(fin["horse_name_raw"]),
                "finish_rank_raw": fin["finish_rank_raw"],
                "passing_order_path_raw": None,
                "six_point_order_raw": None,
                "passing_order_by_point_raw": None,
                "passing_table_point_cells_raw": None,
            }

    reports = [pre.get_text("\n", strip=True) for pre in soup.find_all("pre") if pre.get_text("\n", strip=True)]
    return {
        "title": soup.title.get_text(strip=True) if soup.title else None,
        "heading": heading,
        "tables": tables,
        "identity_verified": heading is not None,
        "runners": [runners[n] for n in sorted(runners)],
        "result_runner_count": len(finish),
        "passing_runner_count": len(runners),
        "passing_groups_by_point": groups_from_tables(tables),
        "official_report_texts": reports,
    }


def rank_bounds(group_raw: str):
    groups = parse_groups(group_raw)
    if groups is None:
        return None, "group_not_parsed"
    positions = {}
    pos = 1
    for group in groups:
        for number in group:
            if number in positions:
                return None, "duplicate_program_number_in_group"
            positions[number] = (pos, pos + len(group) - 1)
        pos += len(group)
    return positions, None


def main():
    first_pass = json.loads((OUT / "official_pages_manifest.json").read_text())
    old_pages = json.loads((PREVIOUS / "website_evidence.json").read_text())
    old_by_key = {(p["date"], int(p["race_no"])): p for p in old_pages}
    flags = json.loads((PREVIOUS / "remaining_website_internal_order_conflicts.json").read_text())
    records = []
    for initial in first_pass:
        key = (initial["date"], int(initial["race_no"]))
        raw_path = OUT / initial["raw_path"]
        blob = raw_path.read_bytes()
        assert hashlib.sha256(blob).hexdigest() == initial["sha256"]
        parsed = parse_page(blob, initial.get("declared_charset"), key)
        old = old_by_key[key]
        old_path = (PREVIOUS / old["raw_path"]).resolve()
        assert old_path.is_relative_to(PREVIOUS.resolve())
        old_blob = old_path.read_bytes()
        old_parsed = parse_page(old_blob, "euc-kr", key)
        old_runners = {r["program_no"]: r for r in old_parsed["runners"]}
        new_runners = {r["program_no"]: r for r in parsed["runners"]}
        runner_differences = [
            {"program_no": n, "previous": old_runners.get(n), "current": new_runners.get(n)}
            for n in sorted(set(old_runners) | set(new_runners))
            if old_runners.get(n) != new_runners.get(n)
        ]
        record = {
            **{k: initial.get(k) for k in ("date", "race_no", "meet_code", "meet_label", "url", "retrieved_at_utc", "http_status", "content_type", "content_encoding", "declared_charset")},
            "raw_path": initial["raw_path"],
            "sha256": initial["sha256"],
            "bytes": len(blob),
            "previous_raw_path": old["raw_path"],
            "previous_sha256": old["sha256"],
            "raw_body_changed_vs_2026_10_02": initial["raw_body_changed_vs_2026_10_02"],
            **parsed,
            "previous_identity_verified": old["identity_verified"],
            "previous_runner_count": len(old_parsed["runners"]),
            "runner_differences_vs_2026_10_02": runner_differences,
            "passing_groups_changed_vs_2026_10_02": old_parsed["passing_groups_by_point"] != parsed["passing_groups_by_point"],
            "official_report_changed_vs_2026_10_02": old_parsed["official_report_texts"] != parsed["official_report_texts"],
            "http_status_ok": initial.get("http_status") == 200,
            "all_runners_have_horse_id": bool(parsed["runners"]) and all(r["horse_id"] for r in parsed["runners"]),
            "all_six_point_paths_present": bool(parsed["runners"]) and all(len(r["six_point_order_raw"] or []) == 6 and r["passing_order_by_point_raw"] for r in parsed["runners"]),
        }
        records.append(record)

    by_key = {(r["date"], int(r["race_no"])): r for r in records}
    checks = []
    for flag in flags:
        race = by_key[(flag["date"], int(flag["race_no"]))]
        number = int(flag["program_no"])
        runner = next((r for r in race["runners"] if r["program_no"] == number), None)
        point = flag["point"]
        fresh_group = race["passing_groups_by_point"].get(point)
        fresh_order_raw = (runner or {}).get("passing_order_by_point_raw", {}).get(point)
        bounds, bounds_error = rank_bounds(fresh_group) if fresh_group is not None else (None, "group_missing")
        bounds_for_runner = bounds.get(number) if bounds else None
        try:
            fresh_order_text = str(fresh_order_raw).strip() if fresh_order_raw is not None else ""
            fresh_order = int(fresh_order_text) if fresh_order_text.isdigit() else None
        except (TypeError, ValueError):
            fresh_order = None
        within = bool(bounds_for_runner and fresh_order is not None and bounds_for_runner[0] <= fresh_order <= bounds_for_runner[1])
        checks.append({
            "date": flag["date"], "race_no": int(flag["race_no"]), "point": point,
            "program_no": number, "horse_id_expected": flag["horse_id"],
            "horse_id_fresh": (runner or {}).get("horse_id"),
            "individual_order_previous": flag["website_order"],
            "individual_order_fresh_raw": fresh_order_raw,
            "individual_order_fresh": fresh_order,
            "group_raw_previous": flag["website_group_raw"],
            "group_raw_fresh": fresh_group,
            "group_changed": flag["website_group_raw"] != fresh_group,
            "rank_bounds_fresh": list(bounds_for_runner) if bounds_for_runner else None,
            "rank_bounds_error": bounds_error,
            "individual_order_within_fresh_group_bounds": within,
        })

    keyword_pattern = re.compile(r"정정|계측|측정|시계|구간|통과착순|통과조|순위표기|표기오류|기록오류")
    report_review = []
    for race in records:
        matched = [line for report in race["official_report_texts"] for line in report.splitlines() if keyword_pattern.search(line)]
        report_review.append({
            "date": race["date"], "race_no": race["race_no"],
            "report_count": len(race["official_report_texts"]),
            "report_texts": race["official_report_texts"],
            "keyword_hit_lines_for_manual_review": matched,
            "direct_section_order_or_measurement_correction_evidence": None,
            "classification_note": "기계 키워드 적중은 관련 정정 근거 판정이 아니며, 공식 원문 전체를 보존했다.",
        })

    summary = {
        "recheck_date": "2026-10-03",
        "official_pages": len(records),
        "http_200": sum(r["http_status_ok"] for r in records),
        "event_identity_verified": sum(r["identity_verified"] for r in records),
        "runner_ids_complete": sum(r["all_runners_have_horse_id"] for r in records),
        "six_point_runner_paths_complete": sum(r["all_six_point_paths_present"] for r in records),
        "flagged_observations_rechecked": len(checks),
        "unique_flagged_races": len({(c["date"], c["race_no"]) for c in checks}),
        "unique_flagged_points": len({(c["date"], c["race_no"], c["point"]) for c in checks}),
        "horse_id_matches": sum(c["horse_id_expected"] == c["horse_id_fresh"] for c in checks),
        "order_group_conflicts_still_outside_bounds": sum(not c["individual_order_within_fresh_group_bounds"] for c in checks),
        "group_changes_vs_previous": sum(c["group_changed"] for c in checks),
        "raw_pages_changed_vs_previous": sum(r["raw_body_changed_vs_2026_10_02"] for r in records),
        "races_with_report_text": sum(bool(r["official_report_texts"]) for r in records),
        "report_changed_vs_previous": sum(r["official_report_changed_vs_2026_10_02"] for r in records),
        "report_keyword_hit_lines": sum(len(r["keyword_hit_lines_for_manual_review"]) for r in report_review),
        "manual_report_conclusion": "pending_manual_read",
        "limits": "This checks directly displayed runner orders against conservative group rank bounds. No exact order is inferred inside parenthesized groups, and no majority-source judgment or database update is made.",
    }

    outputs = [
        ("manifest.json", records),
        ("flagged_observations_recheck.json", checks),
        ("official_report_review.json", report_review),
        ("summary.json", summary),
    ]
    for name, data in outputs:
        with (OUT / name).open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

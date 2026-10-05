"""Read-only API21 to DB4 starting-exam key comparison; no identity linking."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[2]
PARQUET = TASK / "input/starting_exam.parquet"
RPT_CSV = HERE / "api21_comparison_candidates.csv"
PRESENCE_CSV = HERE / "date_meet_presence.csv"
COVERAGE = TASK / "raw/coverage_summary.json"
OUT_SUMMARY = HERE / "api21_comparison_summary.json"
OUT_MISMATCHES = HERE / "api21_comparison_mismatches.csv"
MEETS = {"1": "1", "서울": "1", "3": "3", "부산경남": "3", "부경": "3", "영남": "3"}
def val(value):
    return "" if value is None else str(value)
def repo_path(value):
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError("source path escapes repository")
    return path
def sha(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
def main():
    presence = set()
    with PRESENCE_CSV.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if val(row.get("local_rpt_file_found")).lower() == "true":
                presence.add((val(row["body_exam_date"]), val(row["path_meet"])))
    coverage_doc = json.loads(COVERAGE.read_text(encoding="utf-8"))
    coverage = {(str(p["year"]), str(p["meet"])): val(p.get("status", p.get("coverage_status"))) for p in coverage_doc.get("partitions", [])}
    with RPT_CSV.open(encoding="utf-8-sig", newline="") as stream:
        rpt = list(csv.DictReader(stream))
    rpt_by_key = defaultdict(list)
    for row in rpt:
        row["_key"] = tuple(val(row.get(k)) for k in ("body_date", "path_meet", "body_exam_turn", "body_race_no", "horse_number_local_raw"))
        if all(row["_key"]): rpt_by_key[row["_key"]].append(row)
    api_by_key, unknown_meets = defaultdict(list), Counter()
    api_rows_total, outside_local_dates, missing_id_all_dates = 0, 0, 0
    missing_id_names = Counter()
    for batch in pq.ParquetFile(PARQUET).iter_batches(
            columns=["typed_fields_json", "raw_path", "raw_sha256", "source_page_no", "source_row_no"]):
        for item in batch.to_pylist():
            api_rows_total += 1
            raw = json.loads(item["typed_fields_json"] or "{}")
            if val(raw.get("hrNo")) in ("", "-"):
                missing_id_all_dates += 1
                missing_id_names["visible" if val(raw.get("hrName")).strip() else "blank"] += 1
            raw_meet = val(raw.get("meet")).strip()
            meet = MEETS.get(raw_meet)
            if not meet: unknown_meets[raw_meet] += 1; continue
            source_date = val(raw.get("trainDate"))
            event_date = f"{source_date[:4]}-{source_date[4:6]}-{source_date[6:8]}" if len(source_date) == 8 and source_date.isdigit() else source_date[:10]
            if not event_date or (event_date, meet) not in presence:
                outside_local_dates += bool(event_date)
                continue
            key = (event_date, meet, val(raw.get("daySerial")), val(raw.get("trainNo")), val(raw.get("chulNo")))
            if not all(key):
                continue
            api_by_key[key].append({"raw": raw, "path": item["raw_path"], "sha": item["raw_sha256"],
                                    "page": item["source_page_no"], "row": item["source_row_no"]})
    mismatches, counts = [], Counter(api_missing_official_id_rows_all_dates=missing_id_all_dates,
        api_missing_id_name_visible_all_dates=missing_id_names["visible"], api_missing_id_name_blank_all_dates=missing_id_names["blank"])
    def emit(kind, key, api=None, local=None):
        mismatches.append({"mismatch_type": kind, "date": key[0], "meet": key[1], "daySerial": key[2], "trainNo": key[3], "chulNo": key[4],
            "api_name": val(api["raw"].get("hrName")) if api else "", "api_passFlag": val(api["raw"].get("passFlag")) if api else "",
            "api_path": str(repo_path(api["path"])) if api else "", "api_sha256": api["sha"] if api else "", "api_page": api["page"] if api else "", "api_source_row": api["row"] if api else "",
            "rpt_name": local.get("horse_name_candidate", "") if local else "", "rpt_judgment": local.get("judgment_raw", "") if local else "",
            "rpt_reason": local.get("decision_reason_raw", "") if local else "", "rpt_parse_status": local.get("row_parse_status", "") if local else "",
            "rpt_path": str(repo_path(local["source_path"])) if local else "", "rpt_sha256": local.get("source_sha256", "") if local else "", "rpt_line": local.get("source_line_no", "") if local else ""})
    api_rows_local = sum(map(len, api_by_key.values()))
    for key, group in rpt_by_key.items():
        if len(group) > 1:
            counts["rpt_multiple_key_groups"] += 1
            counts["rpt_rows_on_multiple_keys"] += len(group)
            for local in group:
                emit("rpt_multiple_key", key, local=local)
    for key, group in api_by_key.items():
        if len(group) > 1:
            counts["api_multiple_key_groups"] += 1
            counts["api_rows_on_multiple_keys"] += len(group)
            signatures = {json.dumps(item["raw"], ensure_ascii=False, sort_keys=True) for item in group}
            if len(signatures) > 1:
                counts["api_duplicate_key_conflicting_payload_groups"] += 1
            for api in group:
                emit("api_multiple_key", key, api=api)
        for api in group:
            if val(api["raw"].get("hrNo")) not in ("", "-"):
                continue
            counts["api_missing_official_id_rows"] += 1
            local_rows = rpt_by_key.get(key, [])
            if local_rows:
                counts["missing_id_rows_with_rpt_key"] += 1
                counts["missing_id_api_name_visible" if val(api["raw"].get("hrName")).strip() else "missing_id_api_name_blank"] += 1
                if any(val(local.get("horse_name_candidate")).strip() for local in local_rows):
                    counts["missing_id_rpt_name_visible"] += 1
                for local in local_rows:
                    emit("missing_official_id_rpt_key_diagnostic", key, api, local)
        locals_for_key = rpt_by_key.get(key, [])
        if locals_for_key:
            counts["api_keys_with_rpt_key"] += 1
            counts["api_rows_with_rpt_key"] += len(group)
            if len(group) == len(locals_for_key) == 1:
                api, local = group[0], locals_for_key[0]
                api_name, rpt_name = val(api["raw"].get("hrName")), val(local.get("horse_name_candidate"))
                if not api_name.strip() or not rpt_name.strip():
                    counts["unique_key_name_missing"] += 1
                elif api_name == rpt_name:
                    counts["unique_key_name_same"] += 1
                    counts["pass_comparisons"] += 1
                    if val(api["raw"].get("passFlag")) != val(local.get("judgment_raw")):
                        counts["passflag_judgment_mismatches"] += 1
                        emit("passflag_judgment_mismatch", key, api, local)
                else:
                    counts["unique_key_name_different"] += 1
                    emit("horse_name_mismatch", key, api, local)
        else:
            counts["api_keys_without_rpt_key"] += 1
            counts["api_rows_without_rpt_key"] += len(group)
            for api in group: emit("api_key_without_rpt", key, api=api)
    for key, locals_for_key in rpt_by_key.items():
        if key in api_by_key:
            continue
        state = coverage.get((key[0][:4], key[1]), "missing")
        if (key[0], key[1]) in presence and state in ("complete", "zero"):
            counts["rpt_keys_absent_from_complete_api"] += 1
            for local in locals_for_key:
                emit("rpt_key_absent_from_api", key, local=local)
        else:
            counts["rpt_keys_excluded_incomplete_api_coverage"] += 1
    counts["api_rows_outside_local_dates_ignored"] = outside_local_dates
    counts["passflag_judgment_equal"] = counts["pass_comparisons"] - counts["passflag_judgment_mismatches"]
    with OUT_MISMATCHES.open("w", encoding="utf-8", newline="") as stream:
        fields = list(mismatches[0]) if mismatches else ["mismatch_type", "date", "meet"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(mismatches)
    summary = {"comparison": "diagnostic only; no horse identity linking; raw labels compared exactly", "api_parquet": str(PARQUET.resolve()),
        "api_parquet_sha256": sha(PARQUET), "rpt_candidates": str(RPT_CSV.resolve()), "rpt_candidates_sha256": sha(RPT_CSV),
        "api_rows_total": api_rows_total, "api_rows_on_local_file_dates": api_rows_local, "rpt_candidate_rows": len(rpt),
        "local_date_meet_pairs_with_files": len(presence), "api_unknown_meet_labels": dict(unknown_meets), "counts": dict(counts),
        "api_coverage_status_counts": dict(Counter(coverage.values())), "mismatch_rows": len(mismatches), "mismatch_dates": sorted({m["date"] for m in mismatches})}
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
if __name__ == "__main__":
    main()

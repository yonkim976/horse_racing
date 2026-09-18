"""Read-only verification of archived Jeju training, medical, and weight subsets.

This checks the retained data against its manifests and known native race keys.
The mixed medical/weight API response bodies were not archived, so their source
hashes can only be checked for presence, not independently recomputed here.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def horse_no(value: object) -> str:
    text = str(value or "").strip()
    if not text.isdigit():
        raise ValueError(f"Non-numeric horse number: {text!r}")
    return str(int(text))


def valid_day(value: object) -> int:
    text = str(value)
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"Invalid date: {value!r}")
    date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:]}")
    return int(text)


def add_example(examples: dict, kind: str, value: object, limit: int = 10) -> None:
    bucket = examples.setdefault(kind, [])
    if len(bucket) < limit:
        bucket.append(value)


def roster() -> tuple[
    set[str], dict[tuple[int, int, str], int | None], dict[tuple[int, int, str], int | None]
]:
    ids: set[str] = set()
    raw_keys: dict[tuple[int, int, str], int | None] = {}
    db_keys: dict[tuple[int, int, str], int | None] = {}
    for path in sorted((ROOT / "data/raw/jeju_native_results").glob("native_results_*.jsonl")):
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            if row.get("meet") != "제주" or not str(row.get("rank") or "").startswith("제"):
                raise ValueError(f"Unconfirmed native result: {path}")
            h = horse_no(row["hrNo"])
            key = (valid_day(row["rcDate"]), int(row["rcNo"]), h)
            if key in raw_keys:
                raise ValueError(f"Duplicate native result key: {key}")
            raw_keys[key] = int(row["chulNo"]) if row.get("chulNo") is not None else None
            ids.add(h)
    db = ROOT / "data/horse_racing.sqlite3"
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
        for race_date, race_number, raw_id, number in connection.execute(
            """SELECT r.race_date_local, r.race_number, h.kra_horse_id, e.horse_number
               FROM race_entries e JOIN races r ON r.id=e.race_id
               JOIN racecourses c ON c.id=r.racecourse_id
               JOIN horses h ON h.id=e.horse_id
               WHERE c.kra_meet_code=2 AND r.status='completed'"""
        ):
            h = horse_no(raw_id)
            key = (valid_day(race_date.replace("-", "")), int(race_number), h)
            if key in db_keys:
                raise ValueError(f"Duplicate DB native entry key: {key}")
            db_keys[key] = int(number)
            ids.add(h)
    return ids, raw_keys, db_keys


def source_items(payload: dict) -> tuple[list[dict], int]:
    body = payload["response"]["body"]
    wrapped = body.get("items") or {}
    value = wrapped.get("item") if isinstance(wrapped, dict) else None
    rows = [] if value is None else [value] if isinstance(value, dict) else value
    if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
        raise ValueError("Invalid API item shape")
    return rows, int(body.get("totalCount") or 0)


def canonical_line(row: dict) -> bytes:
    return (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def verify_training(dataset: str, ids: set[str]) -> dict:
    source = ROOT / "data/raw/kra_api_monthly" / dataset / "meet_2"
    destination = ROOT / "data/raw/jeju_native_training" / f"{dataset}_confirmed_native.jsonl.gz"
    manifest = json.loads(destination.with_suffix("").with_suffix(".manifest.json").read_text())
    source_chain = hashlib.sha256()
    source_native = hashlib.sha256()
    output_native = hashlib.sha256()
    counts = Counter()
    annual = defaultdict(Counter)
    examples: dict = {}
    first = last = None
    source_periods = set()
    natural_keys = set()
    payloads = set()
    for path in sorted(source.glob("*/page_*.json")):
        source_periods.add(path.parent.name)
        original = path.read_bytes()
        source_chain.update(path.relative_to(source).as_posix().encode())
        source_chain.update(hashlib.sha256(original).digest())
        rows, total = source_items(json.loads(original))
        counts["source_pages"] += 1
        counts["source_rows"] += len(rows)
        if len(rows) > total:
            counts["source_page_exceeds_total"] += 1
            add_example(examples, "source_page_exceeds_total", str(path.relative_to(ROOT)))
        for row in rows:
            if not str(valid_day(row["trDate"])).startswith(path.parent.name):
                counts["source_period_mismatch"] += 1
                add_example(examples, "source_period_mismatch", str(path.relative_to(ROOT)))
            if horse_no(row["hrNo"]) not in ids:
                continue
            counts["source_native_rows"] += 1
            source_native.update(canonical_line(row))
    with gzip.open(destination, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            row = json.loads(line)
            output_native.update(line.encode("utf-8"))
            counts["output_rows"] += 1
            day = valid_day(row["trDate"])
            first = day if first is None else min(first, day)
            last = day if last is None else max(last, day)
            annual[str(day // 10000)]["rows"] += 1
            key = (horse_no(row["hrNo"]), day)
            if key in natural_keys:
                counts["repeated_horse_day"] += 1
                add_example(examples, "repeated_horse_day", key)
            natural_keys.add(key)
            payload_hash = hashlib.sha256(line.encode("utf-8")).digest()
            if payload_hash in payloads:
                counts["exact_duplicate_rows"] += 1
                add_example(examples, "exact_duplicate_rows", {"line": line_number, "key": key})
            payloads.add(payload_hash)
            if row.get("meet") != "제주":
                counts["non_jeju_meet"] += 1
                add_example(examples, "non_jeju_meet", {"line": line_number, "row": row})
            if horse_no(row["hrNo"]) not in ids:
                counts["outside_confirmed_horse_roster"] += 1
                add_example(
                    examples, "outside_confirmed_horse_roster", {"line": line_number, "row": row}
                )
            if dataset == "horse_training":
                duration = float(row.get("trTerm") or 0)
                if duration > 0:
                    counts["positive_duration"] += 1
                    annual[str(day // 10000)]["positive_duration"] += 1
                if duration < 0:
                    counts["negative_duration"] += 1
                for field in ("run1Cnt", "run2Cnt"):
                    if float(row.get(field) or 0) > 0:
                        counts[f"positive_{field}"] += 1
    checks = {
        "source_path_hash_chain": source_chain.hexdigest()
        == manifest["source_paths_and_hashes_sha256"],
        "output_file_sha256": digest(destination) == manifest["output_sha256"],
        "source_native_equals_output_native": source_native.hexdigest()
        == output_native.hexdigest(),
        "source_pages": counts["source_pages"] == manifest["source_pages"],
        "source_rows": counts["source_rows"] == manifest["source_rows"],
        "native_rows": counts["output_rows"]
        == counts["source_native_rows"]
        == manifest["native_rows"],
        "confirmed_horse_ids": len(ids) == manifest["confirmed_native_horse_ids"],
        "first_last_dates": [first, last]
        == [manifest["first_native_record_date"], manifest["last_native_record_date"]],
        "meet_and_roster": not counts["non_jeju_meet"]
        and not counts["outside_confirmed_horse_roster"],
        "page_counts": not counts["source_page_exceeds_total"],
        "source_periods_match_dates": not counts["source_period_mismatch"],
    }
    return {
        "checks": checks,
        "counts": dict(counts),
        "annual": dict(sorted(annual.items())),
        "source_periods": {
            "count": len(source_periods),
            "first": min(source_periods),
            "last": max(source_periods),
        },
        "first_date": first,
        "last_date": last,
        "examples": examples,
        "source_native_sha256": source_native.hexdigest(),
        "output_native_sha256": output_native.hexdigest(),
    }


def verify_health(
    kind: str, ids: set[str], race_keys: dict[tuple[int, int, str], int | None]
) -> tuple[dict, set[tuple[int, int, str]]]:
    directory = ROOT / "data/raw/jeju_native_health_weight"
    paths = sorted(directory.glob(f"{kind}_*.jsonl"))
    expected = (
        {str(year) for year in range(2008, 2027)}
        if kind == "medical"
        else {
            f"{year:04d}{month:02d}"
            for year in range(2002, 2027)
            for month in range(1, 13)
            if "200201" <= f"{year:04d}{month:02d}" <= "202609"
        }
    )
    observed = {p.stem.split("_", 1)[1] for p in paths}
    counts = Counter()
    annual = defaultdict(Counter)
    examples: dict = {}
    keys: set[tuple[int, int, str]] = set()
    seen_lines: dict[str, tuple[str, int]] = {}
    duplicate_groups: dict[str, dict] = {}
    first = last = None
    manifest_failures = []
    for path in paths:
        period = path.stem.split("_", 1)[1]
        manifest = json.loads(path.with_suffix(".manifest.json").read_text())
        if digest(path) != manifest["native_rows_sha256"]:
            manifest_failures.append({"period": period, "check": "file_sha256"})
        page_rows = sum(int(page["total_count"]) for page in manifest["source_pages"])
        if page_rows != manifest["source_rows_all_jeju"]:
            manifest_failures.append({"period": period, "check": "reported_total_count"})
        counts["source_page_hashes_recorded"] += len(manifest["source_pages"])
        period_rows = period_diagnosed = 0
        for line_number, line in enumerate(path.open(encoding="utf-8"), 1):
            row = json.loads(line)
            counts["rows"] += 1
            period_rows += 1
            if line in seen_lines:
                counts["exact_duplicate_rows_across_files"] += 1
                add_example(
                    examples,
                    "exact_duplicate_rows_across_files",
                    {"path": str(path.relative_to(ROOT)), "line": line_number},
                )
                prior = seen_lines[line]
                entry = duplicate_groups.setdefault(line, {"row": row, "locations": [prior]})
                entry["locations"].append((str(path.relative_to(ROOT)), line_number))
            else:
                seen_lines[line] = (str(path.relative_to(ROOT)), line_number)
            h = horse_no(row["hrNo"])
            day = valid_day(row["clinicDate"] if kind == "medical" else row["rcDate"])
            first = day if first is None else min(first, day)
            last = day if last is None else max(last, day)
            annual[str(day // 10000)]["rows"] += 1
            if not str(day).startswith(period):
                counts["period_mismatch"] += 1
                add_example(
                    examples,
                    "period_mismatch",
                    {"path": str(path.relative_to(ROOT)), "line": line_number},
                )
            if row.get("meet") != "제주" or h not in ids:
                counts["non_native_or_unknown_horse"] += 1
                add_example(
                    examples,
                    "non_native_or_unknown_horse",
                    {"path": str(path.relative_to(ROOT)), "line": line_number},
                )
            if kind == "medical":
                if any(
                    str(row.get(field) or "").strip() not in {"", "-"}
                    for field in ("illName1", "illName2")
                ):
                    counts["diagnosed_rows"] += 1
                    annual[str(day // 10000)]["diagnosed_rows"] += 1
                    period_diagnosed += 1
            else:
                key = (day, int(row["rcNo"]), h)
                if key in keys:
                    counts["duplicate_weight_keys"] += 1
                    add_example(examples, "duplicate_weight_keys", key)
                keys.add(key)
                if key not in race_keys:
                    counts["extra_weight_keys"] += 1
                    add_example(examples, "extra_weight_keys", key)
                elif race_keys[key] is not None and int(row["chulNo"]) != race_keys[key]:
                    counts["weight_start_number_mismatch"] += 1
                    add_example(
                        examples,
                        "weight_start_number_mismatch",
                        {"key": key, "weight": row["chulNo"], "race": race_keys[key]},
                    )
                if float(row.get("wgHr") or 0) <= 0:
                    counts["nonpositive_weight"] += 1
                    add_example(examples, "nonpositive_weight", key)
        if period_rows != manifest["native_rows"]:
            manifest_failures.append({"period": period, "check": "retained_rows"})
        if kind == "medical" and period_diagnosed != manifest["native_rows_with_diagnosis"]:
            manifest_failures.append({"period": period, "check": "diagnosis_rows"})
    checks = {
        "all_periods_present": observed == expected,
        "manifest_hashes_counts": not manifest_failures,
        "meet_and_roster": not counts["non_native_or_unknown_horse"],
        "periods_match_dates": not counts["period_mismatch"],
        "no_exact_duplicate_rows": not counts["exact_duplicate_rows_across_files"],
    }
    if kind == "weight":
        checks.update(
            {
                "all_weight_keys_known": not counts["extra_weight_keys"],
                "weight_keys_unique": not counts["duplicate_weight_keys"],
                "start_numbers_match": not counts["weight_start_number_mismatch"],
                "positive_weights": not counts["nonpositive_weight"],
            }
        )
    return {
        "checks": checks,
        "counts": dict(counts),
        "annual": dict(sorted(annual.items())),
        "periods": {
            "found": len(observed),
            "expected": len(expected),
            "missing": sorted(expected - observed),
            "extra": sorted(observed - expected),
        },
        "first_date": first,
        "last_date": last,
        "manifest_failures": manifest_failures,
        "examples": examples,
        "exact_duplicate_groups": list(duplicate_groups.values()) if kind == "medical" else [],
    }, keys


def verify_text() -> dict:
    types = (
        "dacom55",
        "dacom72",
        "dacom71",
        "dacom23",
        "db4",
        "dacom12",
        "dacom13",
        "dacom01",
        "db5",
    )
    result = {}
    for kind in types:
        path = ROOT / "data/raw/kra_text/_manifests" / kind / "manifest.jsonl"
        discovered: set[str] = set()
        final: dict[str, dict] = {}
        for line in path.open(encoding="utf-8"):
            event = json.loads(line)
            if int(event["meet"]) != 2:
                continue
            remote = event["remote_path"]
            if event["status"] == "discovered":
                discovered.add(remote)
            elif event["status"] in {
                "downloaded",
                "skipped_existing",
                "skipped_duplicate_sha256",
                "verified_empty_source",
            }:
                final[remote] = event
        counts = Counter()
        examples: dict = {}
        dates = []
        for remote, event in final.items():
            local = Path(event["local_path"])
            if not local.is_absolute():
                local = ROOT / local
            if not local.is_file() or digest(local) != event["sha256"]:
                counts["missing_or_changed_file"] += 1
                add_example(examples, "missing_or_changed_file", remote)
                continue
            counts["verified_files"] += 1
            if local.stat().st_size == 0:
                counts["empty_files"] += 1
                if event["status"] != "verified_empty_source":
                    counts["unexpected_empty_file"] += 1
            if event.get("file_date"):
                dates.append(event["file_date"])
        result[kind] = {
            "manifest_sha256": digest(path),
            "discovered": len(discovered),
            "final": len(final),
            "counts": dict(counts),
            "first_file_date": min(dates) if dates else None,
            "last_file_date": max(dates) if dates else None,
            "checks": {
                "all_listed_final": discovered == set(final),
                "all_final_file_hashes_match": not counts["missing_or_changed_file"],
                "empty_files_explicit": not counts["unexpected_empty_file"],
            },
            "examples": examples,
        }
    return result


def compare_weight_to_db(weight_keys: set[tuple[int, int, str]]) -> dict:
    db = ROOT / "data/horse_racing.sqlite3"
    output = Counter()
    examples: dict = {}
    weights: dict[tuple[int, int, str], tuple[int, int | None]] = {}
    for path in sorted((ROOT / "data/raw/jeju_native_health_weight").glob("weight_*.jsonl")):
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            key = (valid_day(row["rcDate"]), int(row["rcNo"]), horse_no(row["hrNo"]))
            weights[key] = (
                int(row["wgHr"]),
                int(row["wgHrDiff"]) if row.get("wgHrDiff") is not None else None,
            )
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """SELECT r.race_date_local, r.race_number, h.kra_horse_id,
                      e.body_weight_kg, e.body_weight_change_kg
               FROM race_entries e JOIN races r ON r.id=e.race_id
               JOIN racecourses c ON c.id=r.racecourse_id
               JOIN horses h ON h.id=e.horse_id
               WHERE c.kra_meet_code=2 AND r.status='completed'"""
        )
        for race_date, race_no, hr_no, body_weight, weight_change in rows:
            key = (valid_day(race_date.replace("-", "")), int(race_no), horse_no(hr_no))
            if key in weight_keys:
                output["db_keys_with_api_weight"] += 1
                source_weight, source_change = weights[key]
                if body_weight is None or body_weight != source_weight:
                    output["db_body_weight_disagreement"] += 1
                    add_example(
                        examples,
                        "db_body_weight_disagreement",
                        {"key": key, "api": source_weight, "db": body_weight},
                    )
                if weight_change is not None and source_change != weight_change:
                    output["db_weight_change_disagreement"] += 1
                    add_example(
                        examples,
                        "db_weight_change_disagreement",
                        {"key": key, "api": source_change, "db": weight_change},
                    )
            else:
                output["db_keys_without_api_weight"] += 1
                category = (
                    "db_weight_null"
                    if body_weight is None
                    else "db_weight_zero"
                    if body_weight == 0
                    else "db_weight_positive"
                )
                output[category] += 1
                if category == "db_weight_positive":
                    add_example(examples, category, {"key": key, "db_weight": body_weight})
    return {
        "counts": dict(output),
        "examples": examples,
        "checks": {
            "common_db_body_weights_agree": not output["db_body_weight_disagreement"],
            "common_db_weight_changes_agree": not output["db_weight_change_disagreement"],
        },
    }


def compare_weight_to_old_results(weight_keys: set[tuple[int, int, str]]) -> dict:
    weights: dict[tuple[int, int, str], int] = {}
    for path in sorted((ROOT / "data/raw/jeju_native_health_weight").glob("weight_*.jsonl")):
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            weights[(valid_day(row["rcDate"]), int(row["rcNo"]), horse_no(row["hrNo"]))] = int(
                row["wgHr"]
            )
    counts = Counter()
    examples: dict = {}
    for path in sorted((ROOT / "data/raw/jeju_native_results").glob("native_results_*.jsonl")):
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            key = (valid_day(row["rcDate"]), int(row["rcNo"]), horse_no(row["hrNo"]))
            match = re.match(r"^\s*(\d+)", str(row.get("wgHr") or ""))
            result_weight = int(match.group(1)) if match else None
            if key in weight_keys:
                counts["old_result_keys_with_api_weight"] += 1
                if result_weight is not None and result_weight != weights[key]:
                    counts["old_result_weight_disagreement"] += 1
                    add_example(
                        examples,
                        "old_result_weight_disagreement",
                        {"key": key, "api": weights[key], "result": result_weight},
                    )
            else:
                counts["old_result_keys_without_api_weight"] += 1
                if result_weight is not None and result_weight > 0:
                    counts["old_result_positive_weight_without_api_weight"] += 1
                    add_example(
                        examples,
                        "old_result_positive_weight_without_api_weight",
                        {"key": key, "result": result_weight},
                    )
    return {
        "counts": dict(counts),
        "examples": examples,
        "checks": {
            "old_result_common_weights_agree": not counts["old_result_weight_disagreement"],
            "old_result_missing_api_has_no_positive_weight": not counts[
                "old_result_positive_weight_without_api_weight"
            ],
        },
    }


def verify_entry_medical_equipment_text() -> dict:
    """Compare dacom71 horse numbers/names only for confirmed positive native races."""
    confirmed_root = ROOT / "data/research/jeju_confirmed_race_time_ids_20260914"
    confirmed_races: set[tuple[str, int]] = set()
    for name in ("linked_official_ids.jsonl", "unresolved_29.jsonl"):
        for line in (confirmed_root / name).open(encoding="utf-8"):
            row = json.loads(line)
            if int(row["race_date"][:4]) >= 2015:
                confirmed_races.add((row["race_date"], int(row["race_number"])))
    official: dict[tuple[str, int, int], dict] = {}
    for path in sorted(
        (ROOT / "data/research/jeju_race_time_official_ids_20260914").glob(
            "official_native_results_*.jsonl"
        )
    ):
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            key = (str(row["rcDate"]), int(row["rcNo"]), int(row["chulNo"]))
            if key[:2] in confirmed_races:
                if key in official:
                    raise ValueError(f"Duplicate official result number: {key}")
                official[key] = {
                    "hrNo": horse_no(row["hrNo"]),
                    "hrName": str(row["hrName"]).strip(),
                }
    heading = re.compile(r"경주일:\s*(?:제주\s*)?(\d{4})\.(\d{2})\.(\d{2})\s+(\d+)\s*경주")
    horse_line = re.compile(r"^\s*(\d{1,2})\s+([^\s]+)(?:\s|$)")
    sections: set[tuple[str, int]] = set()
    text_rows: dict[tuple[str, int, int], dict] = {}
    counts = Counter()
    issues: list[dict] = []
    for path in sorted((ROOT / "data/raw/kra_text/dacom71/meet=2").rglob("*.rpt")):
        counts["files"] += 1
        race = None
        for line_number, line in enumerate(
            path.read_bytes().decode("cp949", errors="replace").splitlines(), 1
        ):
            match = heading.search(line)
            if match:
                counts["all_race_sections"] += 1
                race = (match.group(1) + match.group(2) + match.group(3), int(match.group(4)))
                if race in confirmed_races:
                    sections.add(race)
                continue
            match = horse_line.match(line)
            if match is None or race not in confirmed_races:
                continue
            key = (*race, int(match.group(1)))
            if key in text_rows:
                counts["duplicate_text_horse_numbers"] += 1
                issues.append(
                    {
                        "issue": "duplicate_dacom71_horse_number",
                        "key": key,
                        "path": str(path.relative_to(ROOT)),
                        "line": line_number,
                    }
                )
            text_rows[key] = {
                "hrName": match.group(2).strip(),
                "path": str(path.relative_to(ROOT)),
                "line": line_number,
            }
    official_in_sections = {key: value for key, value in official.items() if key[:2] in sections}
    for key, text_row in text_rows.items():
        if key not in official_in_sections:
            counts["text_number_absent_official"] += 1
            issues.append({"issue": "dacom71_number_absent_official", "key": key, **text_row})
        elif text_row["hrName"] != official_in_sections[key]["hrName"]:
            counts["name_disagreement"] += 1
            issues.append(
                {
                    "issue": "dacom71_official_name_disagreement",
                    "key": key,
                    "text": text_row,
                    "official": official_in_sections[key],
                }
            )
        else:
            counts["number_and_name_agree"] += 1
    for key in official_in_sections.keys() - text_rows.keys():
        counts["official_number_absent_text"] += 1
        issues.append(
            {
                "issue": "official_number_absent_dacom71",
                "key": key,
                "official": official_in_sections[key],
            }
        )
    missing_races = sorted(confirmed_races - sections)
    counts.update(
        {
            "confirmed_races": len(confirmed_races),
            "confirmed_races_with_text": len(sections),
            "confirmed_races_without_text": len(missing_races),
            "text_rows_in_confirmed_races": len(text_rows),
            "official_rows_in_text_sections": len(official_in_sections),
        }
    )
    return {
        "counts": dict(counts),
        "missing_races_by_year": dict(sorted(Counter(key[0][:4] for key in missing_races).items())),
        "missing_races": missing_races,
        "issues": issues,
        "checks": {
            "all_headings_parsed": counts["all_race_sections"] == 8320,
            "no_duplicate_text_numbers": not counts["duplicate_text_horse_numbers"],
            "no_missing_or_extra_numbers_within_present_sections": not counts[
                "text_number_absent_official"
            ]
            and not counts["official_number_absent_text"],
        },
        "interpretation": (
            "Horse number and name are a cross-check; Text contains no official horse ID. "
            "No medical/equipment content or publication time was validated."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/jeju_other_sources_verification_20260915/verification.json"),
    )
    args = parser.parse_args()
    ids, raw_keys, db_keys = roster()
    race_keys = dict(raw_keys)
    race_keys.update(db_keys)
    report = {
        "scope": (
            "Archived confirmed-native training, start training, medical and measured "
            "race-entry weight; local snapshot only"
        ),
        "input_sha256": {
            "data/horse_racing.sqlite3": digest(ROOT / "data/horse_racing.sqlite3"),
            "data/research/jeju_confirmed_race_time_ids_20260914/linked_official_ids.jsonl": digest(
                ROOT
                / "data/research/jeju_confirmed_race_time_ids_20260914/linked_official_ids.jsonl"
            ),
            "data/research/jeju_confirmed_race_time_ids_20260914/unresolved_29.jsonl": digest(
                ROOT / "data/research/jeju_confirmed_race_time_ids_20260914/unresolved_29.jsonl"
            ),
        },
        "known_native_horse_ids": len(ids),
        "known_race_horse_keys": {
            "raw": len(raw_keys),
            "db": len(db_keys),
            "union": len(race_keys),
        },
        "daily_training": verify_training("horse_training", ids),
        "start_training": verify_training("start_training", ids),
    }
    report["medical"], _ = verify_health("medical", ids, race_keys)
    report["weight"], weight_keys = verify_health("weight", ids, race_keys)
    report["text_archive"] = verify_text()
    report["entry_medical_equipment_text"] = verify_entry_medical_equipment_text()
    report["weight"]["db_comparison"] = compare_weight_to_db(weight_keys)
    report["weight"]["old_result_comparison"] = compare_weight_to_old_results(weight_keys)
    missing = sorted(set(race_keys) - weight_keys)
    report["weight"]["coverage"] = {
        "expected_keys": len(race_keys),
        "covered_keys": len(weight_keys & set(race_keys)),
        "missing_keys": len(missing),
        "percent": round(100 * len(weight_keys & set(race_keys)) / len(race_keys), 4),
        "missing_first_20": missing[:20],
        "missing_by_year": dict(sorted(Counter(str(key[0] // 10000) for key in missing).items())),
    }
    confirmed_root = ROOT / "data/research/jeju_confirmed_race_time_ids_20260914"
    confirmed_keys = set()
    for name in ("linked_official_ids.jsonl", "unresolved_29.jsonl"):
        for line in (confirmed_root / name).open(encoding="utf-8"):
            row = json.loads(line)
            confirmed_keys.add(
                (int(row["race_date"]), int(row["race_number"]), horse_no(row["hrNo"]))
            )
    report["weight"]["confirmed_result_coverage"] = {
        "expected_keys": len(confirmed_keys),
        "covered_keys": len(confirmed_keys & weight_keys),
        "missing_keys": len(confirmed_keys - weight_keys),
        "percent": round(100 * len(confirmed_keys & weight_keys) / len(confirmed_keys), 4),
    }
    report["all_checks_passed"] = all(
        all(section["checks"].values())
        for section in (
            report["daily_training"],
            report["start_training"],
            report["medical"],
            report["weight"],
            report["entry_medical_equipment_text"],
            *report["text_archive"].values(),
        )
    )
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    issues = output.parent / "issues.jsonl"
    with issues.open("w", encoding="utf-8") as stream:
        for day, race_no, h in missing:
            stream.write(
                json.dumps(
                    {
                        "issue": "no_retained_positive_weight_api_row",
                        "race_date": day,
                        "race_number": race_no,
                        "hrNo": h,
                        "confirmed_positive_result": (day, race_no, h) in confirmed_keys,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        for day, race_no, h in sorted((confirmed_keys - weight_keys) - set(race_keys)):
            stream.write(
                json.dumps(
                    {
                        "issue": "confirmed_result_weight_key_outside_original_weight_roster",
                        "race_date": day,
                        "race_number": race_no,
                        "hrNo": h,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        for group in report["medical"]["exact_duplicate_groups"]:
            stream.write(
                json.dumps(
                    {"issue": "exact_duplicate_medical_payload", **group}, ensure_ascii=False
                )
                + "\n"
            )
        for issue in report["entry_medical_equipment_text"]["issues"]:
            stream.write(json.dumps(issue, ensure_ascii=False) + "\n")
        for race_date, race_number in report["entry_medical_equipment_text"]["missing_races"]:
            stream.write(
                json.dumps(
                    {
                        "issue": "confirmed_race_without_dacom71_text",
                        "race_date": race_date,
                        "race_number": race_number,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    report["issues_file"] = str(issues.relative_to(ROOT))
    report["issues_sha256"] = digest(issues)
    report["all_checks_passed"] = report["all_checks_passed"] and all(
        all(report["weight"][name]["checks"].values())
        for name in ("db_comparison", "old_result_comparison")
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "all_checks_passed": report["all_checks_passed"],
                "daily_training": report["daily_training"]["counts"],
                "start_training": report["start_training"]["counts"],
                "medical": report["medical"]["counts"],
                "weight": report["weight"]["counts"],
                "weight_coverage": report["weight"]["coverage"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

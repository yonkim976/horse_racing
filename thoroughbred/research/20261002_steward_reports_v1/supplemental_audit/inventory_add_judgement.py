#!/usr/bin/env python3
"""Inventory API215 addJudgement text and locator ambiguity without source edits."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "thoroughbred/research/20261002_steward_reports_v1"
SOURCE = PACKAGE / "source"
OUTPUT = PACKAGE / "supplemental_audit"
DATA = SOURCE / "api_observations.parquet"

FULL_DATES = [
    re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})\s*년\s*(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일?"),
    re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})\s*[./-]\s*(?P<m>\d{1,2})\s*[./-]\s*(?P<d>\d{1,2})\s*\.?"),
    re.compile(r"(?<!\d)[`'’‘]?(?P<y>\d{2})\s*\.\s*(?P<m>\d{1,2})\s*[./-]\s*(?P<d>\d{1,2})\s*\.?"),
]
YEARLESS_DATE = re.compile(r"(?<!\d)(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일?")
RACE_NUMBERS = re.compile(r"(?:(?:제\s*)?(?P<race>\d{1,2})\s*경주|(?<!\d)(?P<rnum>\d{1,2})\s*R(?![가-힣A-Za-z]))")
PARAGRAPH_SPLIT = re.compile(r"(?=●\s*)|\n+|\r+")
SCHEDULE_WORDS = re.compile(r"(적용|적용하기|유예|재개|시행|예정|부터|까지|경마일부터|개시|시작)")
WEEKDAY_NAMES = ("월", "화", "수", "목", "금", "토", "일")
WEEKDAY_NUMBERS = {name: index for index, name in enumerate(WEEKDAY_NAMES)}


def h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def as_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def date_candidates(text: str) -> tuple[list[str], list[str], list[str]]:
    found: list[tuple[int, int, str]] = []
    invalid: list[str] = []
    for pattern in FULL_DATES:
        for match in pattern.finditer(text):
            y, m, d = int(match.group("y")), int(match.group("m")), int(match.group("d"))
            if y < 100:
                y += 2000
            raw = match.group(0)
            try:
                iso = date(y, m, d).isoformat()
            except ValueError:
                invalid.append(raw)
                continue
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end, _ in found):
                continue
            found.append((span[0], span[1], iso))
    # Keep month/day references separate; do not invent a year from the row date.
    yearless: list[str] = []
    for match in YEARLESS_DATE.finditer(text):
        span = match.span()
        if any(span[0] < end and span[1] > start for start, end, _ in found):
            continue
        raw = match.group(0).strip()
        value = f"{int(match.group('m')):02d}-{int(match.group('d')):02d}"
        if value not in yearless:
            yearless.append(value)
    full = sorted({iso for _, _, iso in found})
    return full, yearless, invalid


def parse_race_numbers(text: str) -> list[int]:
    return sorted({int(match.group("race") or match.group("rnum")) for match in RACE_NUMBERS.finditer(text)})


def weekday_checks(text: str) -> list[dict[str, Any]]:
    """Find stated weekdays adjacent to explicit dates; never correct source text."""
    checks: list[dict[str, Any]] = []
    seen_spans: list[tuple[int, int]] = []
    for pattern in FULL_DATES:
        for match in pattern.finditer(text):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in seen_spans):
                continue
            year = int(match.group("y"))
            if year < 100:
                year += 2000
            try:
                stated_date = date(year, int(match.group("m")), int(match.group("d")))
            except ValueError:
                continue
            tail = text[match.end():match.end() + 18]
            weekday_match = re.match(r"\s*[（(]\s*([월화수목금토일])(?:요일)?", tail)
            if not weekday_match:
                seen_spans.append(span)
                continue
            stated_weekday = weekday_match.group(1)
            actual_weekday = WEEKDAY_NAMES[stated_date.weekday()]
            nearby_same_month_day = []
            for year_candidate in range(stated_date.year - 10, stated_date.year + 11):
                try:
                    candidate = date(year_candidate, stated_date.month, stated_date.day)
                except ValueError:
                    continue
                if WEEKDAY_NAMES[candidate.weekday()] == stated_weekday:
                    nearby_same_month_day.append(candidate.isoformat())
            nearby_day_matches = []
            for offset in range(-3, 4):
                candidate = stated_date.fromordinal(stated_date.toordinal() + offset)
                if WEEKDAY_NAMES[candidate.weekday()] == stated_weekday:
                    nearby_day_matches.append(candidate.isoformat())
            checks.append({
                "mentioned_date": stated_date.isoformat(),
                "stated_weekday": stated_weekday,
                "actual_weekday": actual_weekday,
                "weekday_matches_calendar": actual_weekday == stated_weekday,
                "same_month_day_nearby_year_candidates": nearby_same_month_day,
                "nearby_date_candidates_same_year": nearby_day_matches,
            })
            seen_spans.append(span)
    return checks


def source_contexts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts_by_day = Counter(
        (r["actual_meet_code"], r["race_date_iso"]) for r in rows
        if r.get("actual_meet_code") and r.get("race_date_iso")
    )
    groups: dict[tuple[int, str], set[int]] = defaultdict(set)
    for row in rows:
        if row.get("actual_meet_code") and row.get("race_date_iso") and row.get("rcNo") is not None:
            groups[(row["actual_meet_code"], row["race_date_iso"])].add(row["rcNo"])
    result = []
    for (meet, day), races in sorted(groups.items()):
        result.append({
            "meet": meet,
            "race_date": day,
            "race_numbers": sorted(races),
            "source_race_rows_that_day": counts_by_day[(meet, day)],
        })
    return result


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    table = pq.read_table(DATA)
    rows = [r for r in table.to_pylist() if r["dataset"] == "api215_judge_report" and r["row_scope_status"] == "included"]
    nonblank = [r for r in rows if r.get("addJudgement") not in (None, "", "-")]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in nonblank:
        grouped[row["addJudgement"]].append(row)

    inventory: list[dict[str, Any]] = []
    occurrence_rows: list[dict[str, Any]] = []
    paragraphs: dict[str, dict[str, Any]] = {}
    future_records: list[dict[str, Any]] = []
    class_counts: Counter[str] = Counter()
    occurrence_class_counts: Counter[str] = Counter()
    future_pair_count = 0
    weekday_mismatch_records: list[dict[str, Any]] = []

    for text, matches in sorted(grouped.items(), key=lambda pair: h(pair[0])):
        text_hash = h(text)
        full_dates, yearless, invalid_dates = date_candidates(text)
        race_numbers = parse_race_numbers(text)
        weekday_audit = weekday_checks(text)
        bullet_count = text.count("●")
        if len(full_dates) == 1 and len(race_numbers) == 1:
            locator_class = "one_explicit_full_date_one_race_number_candidate"
        elif len(full_dates) == 1 and len(race_numbers) > 1:
            locator_class = "one_explicit_date_multiple_race_numbers"
        elif len(full_dates) > 1 or len(race_numbers) > 1:
            locator_class = "multiple_dates_or_races_ambiguous"
        elif len(full_dates) == 1:
            locator_class = "explicit_full_date_without_race_number"
        elif yearless and race_numbers:
            locator_class = "yearless_date_and_race_number_needs_context"
        elif race_numbers:
            locator_class = "race_number_without_explicit_full_date"
        elif yearless:
            locator_class = "yearless_date_without_race_number"
        else:
            locator_class = "no_explicit_date_race_locator"
        class_counts[locator_class] += 1
        occurrence_class_counts[locator_class] += len(matches)

        contexts = source_contexts(matches)
        source_meets = sorted({c["meet"] for c in contexts})
        source_dates = sorted({c["race_date"] for c in contexts})
        source_race_keys = sorted({r["race_key"] for r in matches if r.get("race_key")})
        candidate_race_keys = []
        if len(full_dates) == 1 and len(race_numbers) == 1 and len(source_meets) == 1:
            candidate_race_keys = [f"{source_meets[0]}:{full_dates[0]}:{race_numbers[0]}"]

        future_refs = []
        for source_day in source_dates:
            source_day_date = as_date(source_day)
            if not source_day_date:
                continue
            for mention in full_dates:
                mention_date = as_date(mention)
                if mention_date and mention_date > source_day_date:
                    future_refs.append({
                        "source_report_date": source_day,
                        "mentioned_date": mention,
                        "days_after_source_report_date": (mention_date - source_day_date).days,
                    })
        future_refs = sorted({(x["source_report_date"], x["mentioned_date"], x["days_after_source_report_date"]) for x in future_refs})
        schedule_language = bool(SCHEDULE_WORDS.search(text))
        weekday_mismatches = [check for check in weekday_audit if not check["weekday_matches_calendar"]]
        if weekday_mismatches:
            weekday_mismatch_records.append({
                "text_sha256": text_hash,
                "occurrence_count": len(matches),
                "source_contexts_json": json.dumps(contexts, ensure_ascii=False),
                "weekday_mismatches_json": json.dumps(weekday_mismatches, ensure_ascii=False),
                "manual_review_class": "candidate_date_or_weekday_typo_no_auto_correction",
                "text": text,
            })
        if future_refs:
            future_pair_count += len(future_refs)
            weekday_mismatch_dates = {check["mentioned_date"] for check in weekday_mismatches}
            future_date_has_own_weekday_conflict = any(mentioned in weekday_mismatch_dates for _, mentioned, _ in future_refs)
            if future_date_has_own_weekday_conflict:
                future_class = "future_date_with_weekday_conflict_candidate_typo"
            elif schedule_language:
                future_class = "future_effective_or_scheduled_date_possible"
            else:
                future_class = "future_reference_role_unresolved_needs_review"
            future_records.append({
                "text_sha256": text_hash,
                "occurrence_count": len(matches),
                "source_context_dates": json.dumps(source_dates, ensure_ascii=False),
                "future_date_references": json.dumps([
                    {"source_report_date": a, "mentioned_date": b, "days_after": c}
                    for a, b, c in future_refs
                ], ensure_ascii=False),
                "has_sanction_or_schedule_language": schedule_language,
                "manual_review_class": future_class,
                "weekday_mismatch_also_present": bool(weekday_mismatches),
                "forward_date_itself_has_weekday_mismatch": future_date_has_own_weekday_conflict,
                "text": text,
            })

        inventory_row = {
            "text_sha256": text_hash,
            "occurrence_count": len(matches),
            "unique_source_race_keys": len(source_race_keys),
            "source_race_keys_json": json.dumps(source_race_keys, ensure_ascii=False),
            "source_contexts_json": json.dumps(contexts, ensure_ascii=False),
            "source_date_min": min(source_dates) if source_dates else None,
            "source_date_max": max(source_dates) if source_dates else None,
            "explicit_full_dates_json": json.dumps(full_dates, ensure_ascii=False),
            "yearless_month_day_mentions_json": json.dumps(yearless, ensure_ascii=False),
            "invalid_date_tokens_json": json.dumps(invalid_dates, ensure_ascii=False),
            "race_number_candidates_json": json.dumps(race_numbers, ensure_ascii=False),
            "candidate_race_keys_json": json.dumps(candidate_race_keys, ensure_ascii=False),
            "locator_class": locator_class,
            "bullet_marker_count": bullet_count,
            "multiple_bullet_sections": bullet_count > 1,
            "weekday_mismatches_json": json.dumps(weekday_mismatches, ensure_ascii=False),
            "source_context_full_day_race_row_counts_json": json.dumps([
                {
                    "meet": context["meet"],
                    "race_date": context["race_date"],
                    "matching_rows_for_text": len(context["race_numbers"]),
                    "api_race_rows_that_day": context["source_race_rows_that_day"],
                    "text_present_on_every_api_race_row_that_day": len(context["race_numbers"]) == context["source_race_rows_that_day"],
                }
                for context in contexts
            ], ensure_ascii=False),
            "future_date_reference_count": len(future_refs),
            "future_date_references_json": json.dumps([
                {"source_report_date": a, "mentioned_date": b, "days_after": c}
                for a, b, c in future_refs
            ], ensure_ascii=False),
            "future_reference_has_schedule_language": schedule_language,
            "text": text,
        }
        inventory.append(inventory_row)

        for row in matches:
            occurrence_rows.append({
                "source_location": row["source_location"],
                "source_row_sha256": row["source_row_sha256"],
                "source_page_sha256": row["page_sha256"],
                "meet": row["actual_meet_code"],
                "race_date": row["race_date_iso"],
                "race_no": row["rcNo"],
                "race_key": row["race_key"],
                "text_sha256": text_hash,
            })

        # Split on explicit paragraph markers/newlines for a supplemental
        # paragraph inventory. Paragraph locator candidates stay provisional.
        raw_paragraphs = [part.strip() for part in PARAGRAPH_SPLIT.split(text) if part.strip()]
        for para in raw_paragraphs:
            ph = h(para)
            slot = paragraphs.setdefault(ph, {
                "paragraph_sha256": ph,
                "paragraph": para,
                "parent_text_hashes": set(),
                "source_item_occurrences": 0,
                "full_dates": date_candidates(para)[0],
                "yearless_dates": date_candidates(para)[1],
                "race_numbers": parse_race_numbers(para),
                "bullet_marker_count": para.count("●"),
            })
            slot["parent_text_hashes"].add(text_hash)
            slot["source_item_occurrences"] += len(matches)

    for row in inventory:
        row["text_hash_pinned"] = True
    paragraphs_out = []
    for item in sorted(paragraphs.values(), key=lambda x: x["paragraph_sha256"]):
        item["parent_text_hashes"] = sorted(item["parent_text_hashes"])
        paragraphs_out.append(item)

    write_csv(OUTPUT / "unique_addjudgement_values.csv", inventory, list(inventory[0]) if inventory else ["text_sha256", "text"])
    write_csv(OUTPUT / "addjudgement_occurrences.csv", occurrence_rows, [
        "source_location", "source_row_sha256", "source_page_sha256", "meet", "race_date", "race_no", "race_key", "text_sha256",
    ])
    write_csv(OUTPUT / "future_date_reference_candidates.csv", future_records, [
        "text_sha256", "occurrence_count", "source_context_dates", "future_date_references",
        "has_sanction_or_schedule_language", "weekday_mismatch_also_present", "manual_review_class", "text",
    ])
    write_csv(OUTPUT / "weekday_date_mismatch_candidates.csv", weekday_mismatch_records, [
        "text_sha256", "occurrence_count", "source_contexts_json", "weekday_mismatches_json", "manual_review_class", "text",
    ])
    (OUTPUT / "unique_addjudgement_paragraphs.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in paragraphs_out),
        encoding="utf-8",
    )

    source_page = PACKAGE / "official_web/seoul_report_index.html"
    page_bytes = source_page.read_bytes()
    page_text = page_bytes.decode("euc-kr", errors="replace")
    official_ui = {
        "source_path": str(source_page.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(page_bytes).hexdigest(),
        "captured_at_utc": json.loads((PACKAGE / "official_web/seoul_report_index.metadata.json").read_text())["captured_at_utc"],
        "encoding": "EUC-KR",
        "page_selected_date": "2026-09-20 (rcDate option in saved HTML)",
        "page_has_additional_judgement_heading": "alt=\"추가 심판사항\"" in page_text,
        "page_additional_judgement_value": "- (the pre element immediately under that page-level heading)",
        "api_same_date_rows": sum(r["rcDate"] == 20260920 and r["requested_meet"] == 1 for r in rows),
        "api_same_date_rows_addjudgement_dash": sum(r["rcDate"] == 20260920 and r["requested_meet"] == 1 and r["addJudgement"] == "-" for r in rows),
        "interpretation": "The official page presents `추가 심판사항` in a separate page/day section before the individual race detail tables. Its dash on 2026-09-20 agrees with all 11 API215 race rows for that meet/date. Repetition of addJudgement across multiple race rows, plus this page layout, supports preserving the value as day-wide supplemental text rather than assigning it to the containing race row. This does not validate older-archive completeness.",
    }
    (OUTPUT / "official_ui_semantics_check.json").write_text(json.dumps(official_ui, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "status": "complete_nonmutating_inventory",
        "source_observation_path": str(DATA.relative_to(ROOT)),
        "source_observation_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
        "source_scope": "API215 included rows only; addJudgement values null/empty/'-' excluded from nonblank inventory",
        "nonblank_item_occurrences": len(nonblank),
        "distinct_exact_field_values": len(grouped),
        "distinct_paragraphs_after_bullet_newline_split": len(paragraphs_out),
        "field_value_locator_class_counts": dict(class_counts),
        "field_occurrence_locator_class_counts": dict(occurrence_class_counts),
        "occurrence_rows_with_one_full_date_and_one_race_candidate": sum(
            r["locator_class"] == "one_explicit_full_date_one_race_number_candidate" for r in inventory
        ),
        "unique_values_with_multiple_dates_or_race_numbers": sum(
            r["locator_class"] in {"one_explicit_date_multiple_race_numbers", "multiple_dates_or_races_ambiguous"} for r in inventory
        ),
        "values_with_candidate_future_date_references": len(future_records),
        "future_date_reference_pairs": future_pair_count,
        "values_with_calendar_weekday_mismatch": len(weekday_mismatch_records),
        "calendar_weekday_mismatch_occurrences": sum(r["occurrence_count"] for r in weekday_mismatch_records),
        "future_reference_class_counts": dict(Counter(r["manual_review_class"] for r in future_records)),
        "values_repeated_across_every_api_race_row_of_a_source_day": sum(
            any(context["text_present_on_every_api_race_row_that_day"] for context in json.loads(row["source_context_full_day_race_row_counts_json"]))
            for row in inventory
        ),
        "future_date_interpretation": "A date later than the API row's rcDate is a forward reference, not itself a typo. Rows with a weekday/date conflict are listed independently as stronger calendar-error candidates; no date is corrected automatically.",
        "official_ui_semantics": official_ui,
        "database_accessed": False,
        "source_files_modified": False,
    }
    (OUTPUT / "supplemental_audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = """# API215 `addJudgement` supplemental-text audit

This is a nonmutating inventory built from the frozen API215 source observations. It does not modify `source/`, parse a source value into an asserted race or horse link, or access a database.

The audit pins each exact distinct nonblank `addJudgement` value by SHA-256 and preserves it in `unique_addjudgement_values.csv`; all 3,237 source-row occurrences are separately mapped to their source row/page hashes in `addjudgement_occurrences.csv`. `unique_addjudgement_paragraphs.jsonl` deduplicates text segments separated by explicit bullet markers or line breaks while retaining parent value hashes and occurrence counts. Date/race locators in the inventory are candidates only: multiple dates, races, bullet sections, missing years, and day-wide reuse can make a value ambiguous. `future_date_reference_candidates.csv` records explicit dates later than the containing API row's `rcDate`; a later date is not automatically a typo because sanction-effective dates and scheduled review dates are common in the prose. The independent weekday audit found seven distinct date/weekday contradictions (53 source-row occurrences); two forward-referenced dates have their own weekday contradiction and are stronger typo-review candidates: `’18.10.28(토)` on source context 2017-10-29, and `2024.8.26(토)` on source context 2024-08-25. Neither is corrected automatically; see `weekday_date_mismatch_candidates.csv`.

The saved official Seoul report HTML for 2026-09-20 has a separate page-level section titled `추가 심판사항`, whose value is `-`; the same date's 11 API215 race rows all have `addJudgement='-'`. Individual race details appear in separate sections. Together with repeated identical `addJudgement` values across race rows, the page layout supports treating this field as day-wide supplemental narrative. It does not prove the full availability or publication history of the older archive. Evidence path/hash and counts are in `official_ui_semantics_check.json` and `supplemental_audit_summary.json`.
"""
    (OUTPUT / "README.md").write_text(readme, encoding="utf-8")

    # Hash every final audit artifact except this file's own manifest entry.
    digest_map = {
        path.relative_to(OUTPUT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in OUTPUT.iterdir() if path.is_file() and path.name != "supplemental_audit_manifest.json"
    }
    manifest = {
        "status": "complete",
        "source_dataset_sha256": summary["source_observation_sha256"],
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "files_sha256": digest_map,
        "counts": {k: summary[k] for k in (
            "nonblank_item_occurrences", "distinct_exact_field_values", "distinct_paragraphs_after_bullet_newline_split",
        "values_with_candidate_future_date_references", "future_date_reference_pairs",
        "values_with_calendar_weekday_mismatch", "calendar_weekday_mismatch_occurrences",
        )},
    }
    (OUTPUT / "supplemental_audit_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "nonblank_occurrences": len(nonblank), "unique_values": len(grouped), "unique_paragraphs": len(paragraphs_out), "future_reference_values": len(future_records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Conservative API215 report paragraph extraction and event-roster linking.

Pure transformation only: callers provide a report occurrence and a roster (or
event-keyed roster map). This module does not open files, databases, or network
connections. Offsets are Python Unicode codepoint offsets, end-exclusive.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Mapping

TEXT_FIELDS = ("judgement", "addJudgement", "jkChange")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
QUOTE_CHARS = frozenset('“”＂"')
SENTENCE_END = frozenset("。！？!?；;")


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = "|".join("" if part is None else str(part) for part in parts)
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or not text.isascii() or not text.isdigit():
        return None
    try:
        return int(text)
    except (ValueError, OverflowError):
        return None


def _valid_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _event_key(meet: Any, event_date: Any, race_no: Any) -> tuple[int, str, int] | None:
    m, d, r = _int_or_none(meet), _valid_date(event_date), _int_or_none(race_no)
    if m not in (1, 3, 4) or d is None or r is None or r <= 0:
        return None
    return (m, d, r)


def _roster_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "program_no_raw": row.get("horse_program_no_raw", row.get("program_no_raw", row.get("program_no"))),
        "official_horse_id": row.get("horse_id_raw", row.get("official_horse_id", row.get("horse_id"))),
        "horse_name_raw": row.get("horse_name_raw", row.get("horse_name")),
        "event_execution_status": row.get("execution_status", row.get("event_execution_status")),
        "roster_source_file": row.get("source_file", row.get("roster_source_file")),
        "roster_source_item_index": row.get("source_item_index", row.get("roster_source_item_index")),
    }


def _provided_roster(runners: Any, key: tuple[int, str, int] | None,
                     parent_key: tuple[int, str, int] | None) -> list[Mapping[str, Any]]:
    """Accept either one already-scoped roster or a map keyed by (meet,date,race)."""
    if isinstance(runners, Mapping):
        raw = runners.get(key) if key is not None else None
        return list(raw or [])
    if key is None or key != parent_key:
        return []
    result: list[Mapping[str, Any]] = []
    for row in runners or []:
        row_key = _event_key(row.get("source_meet", row.get("actual_meet_code", row.get("meet"))),
                             row.get("result_date", row.get("race_date_iso", row.get("event_date"))),
                             row.get("result_race_no", row.get("rcNo", row.get("race_no"))))
        # Synthetic callers may pass a roster without event columns; the caller
        # contract then means this list is already scoped to the report event.
        if row_key is None or row_key == key:
            result.append(row)
    return result


def _name_matches_roster(raw_name: str, roster_name: str, meet: int | None) -> bool:
    """Permit one known KRA origin/display prefix, with exact event-entry evidence."""
    if raw_name == roster_name:
        return True
    allowed = ("[서울]", "[부산경남]", "[부경]", "[영천]", "[영남]")
    raw_base = next((raw_name[len(prefix):] for prefix in allowed if raw_name.startswith(prefix)), raw_name)
    roster_base = next((roster_name[len(prefix):] for prefix in allowed if roster_name.startswith(prefix)), roster_name)
    return bool(raw_base.strip()) and raw_base == roster_base and (raw_base != raw_name or roster_base != roster_name)


def _quote_pairs(text: str) -> list[tuple[int, int, str, str]]:
    """Pair adjacent supported quote tokens conservatively, retaining offsets."""
    chars = [(i, ch) for i, ch in enumerate(text) if ch in QUOTE_CHARS]
    pairs: list[tuple[int, int, str, str]] = []
    idx = 0
    while idx + 1 < len(chars):
        start, opening = chars[idx]
        end, closing = chars[idx + 1]
        # Quotes containing another quote token are ambiguous; do not pair over it.
        if end > start + 1:
            pairs.append((start, end, opening, closing))
        idx += 2
    return pairs


def _marker_name(text: str, marker_pos: int, pairs: list[tuple[int, int, str, str]]) -> tuple[str, int, int] | None:
    """Return name text and its span when a circled marker is adjacent to quotes."""
    # Marker inside quoted name: “⑤name” / “ ⑤name ”.
    for qstart, qend, _open, _close in pairs:
        if qstart < marker_pos < qend:
            before = text[qstart + 1:marker_pos]
            after = text[marker_pos + 1:qend]
            if before.strip() == "" and after.strip():
                left = marker_pos + 1
                right = qend
                while left < right and text[left].isspace():
                    left += 1
                while right > left and text[right - 1].isspace():
                    right -= 1
                return text[left:right], left, right
    # Marker immediately before a quoted name: ⑤＂name＂ / ⑤”name“.
    pos = marker_pos + 1
    while pos < len(text) and text[pos].isspace():
        pos += 1
    for qstart, qend, _open, _close in pairs:
        if qstart == pos:
            left, right = qstart + 1, qend
            while left < right and text[left].isspace():
                left += 1
            while right > left and text[right - 1].isspace():
                right -= 1
            if left < right:
                return text[left:right], left, right
    return None


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    for pos in range(start, end):
        ch = text[pos]
        is_end = ch in SENTENCE_END
        if ch == ".":
            # Keep dotted dates/times and numbered tokens intact; this secondary
            # view is intentionally conservative and never affects paragraph links.
            is_end = not (pos > start and text[pos - 1].isdigit())
        if not is_end:
            continue
        left, right = cursor, pos + 1
        while left < right and text[left].isspace():
            left += 1
        if left < right:
            spans.append((left, right))
        cursor = pos + 1
    left, right = cursor, end
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right - 1].isspace():
        right -= 1
    if left < right:
        spans.append((left, right))
    if not spans:
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            spans.append((left, right))
    return spans


# Exact leading target forms only. Two-digit years are interpreted as 20YY;
# no date elsewhere in the prose is used as event-routing evidence.
ADD_CONTEXT_RE = re.compile(
    r"^\s*[‘’'`]?(?P<year>20\d{2}|\d{2})\s*[./-]\s*(?P<month>\d{1,2})\s*[./-]\s*(?P<day>\d{1,2})"
    r"\s*\.?\s*(?:\((?P<weekday_label>[^)]{1,20})\)\s*)?(?:제\s*)?(?P<race>\d{1,2})\s*경주(?!\d)(?=\s|$|[.,:：에은는을를의])"
)
ADD_CONTEXT_ANY_RE = re.compile(
    r"(?P<year>20\d{2}|\d{2})\s*[./-]\s*(?P<month>\d{1,2})\s*[./-]\s*(?P<day>\d{1,2})"
    r"\s*\.?\s*(?:\((?P<weekday_label>[^)]{1,20})\)\s*)?(?:제\s*)?(?P<race>\d{1,2})\s*경주(?!\d)"
)
ADD_KOREAN_CONTEXT_RE = re.compile(
    r"^\s*(?:\[추가심판사항\]\s*)?(?P<year>20\d{2})\s*년\s*(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일"
    r"\s*(?:\(\s*(?P<weekday_label>[^)]{1,20})\s*\)\s*)?(?:제\s*)?(?P<race>\d{1,2})\s*경주(?!\d)(?=\s|$|[.,:：에은는을를의])"
)
ADD_KOREAN_CONTEXT_ANY_RE = re.compile(
    r"(?P<year>20\d{2})\s*년\s*(?P<month>\d{1,2})\s*월\s*(?P<day>\d{1,2})\s*일"
    r"\s*(?:\(\s*(?P<weekday_label>[^)]{1,20})\s*\)\s*)?(?:제\s*)?(?P<race>\d{1,2})\s*경주(?!\d)"
)


def _add_target(text: str, parent_key: tuple[int, str, int] | None) -> tuple[tuple[int, str, int] | None, str]:
    match = ADD_CONTEXT_RE.match(text) or ADD_KOREAN_CONTEXT_RE.match(text)
    if not match:
        return None, "add_judgement_target_context_missing_or_not_leading"
    all_headers = list(ADD_CONTEXT_ANY_RE.finditer(text)) + list(ADD_KOREAN_CONTEXT_ANY_RE.finditer(text))
    distinct_headers = {
        ((int(m.group("year")) if len(m.group("year")) == 4 else 2000 + int(m.group("year"))),
         int(m.group("month")), int(m.group("day")), int(m.group("race")))
        for m in all_headers
    }
    if len(distinct_headers) > 1:
        return None, "add_judgement_multiple_distinct_event_headers"
    weekday_codes = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
    for header in all_headers:
        hyear = int(header.group("year")) if len(header.group("year")) == 4 else 2000 + int(header.group("year"))
        try:
            hdate = date(hyear, int(header.group("month")), int(header.group("day")))
        except ValueError:
            return None, "add_judgement_target_date_invalid"
        hlabel = header.group("weekday_label")
        if hlabel is not None:
            hlabel = hlabel.strip()
            hlabel = hlabel[:-2] if hlabel.endswith("요일") else hlabel
            if hlabel not in weekday_codes:
                return None, "add_judgement_target_weekday_unrecognized"
            if hdate.weekday() != weekday_codes[hlabel]:
                return None, "add_judgement_target_weekday_mismatch"
    year_text = match.group("year")
    year = int(year_text) if len(year_text) == 4 else 2000 + int(year_text)
    try:
        parsed_date = date(year, int(match.group("month")), int(match.group("day")))
        d = parsed_date.isoformat()
    except ValueError:
        return None, "add_judgement_target_date_invalid"
    race = int(match.group("race"))
    if not 2010 <= year <= 2026:
        return None, "add_judgement_target_date_out_of_scope"
    if parent_key is None:
        return None, "add_judgement_parent_event_key_invalid"
    meet = parent_key[0]
    if d > parent_key[1]:
        return None, "add_judgement_target_after_parent_report_date"
    return (meet, d, race), "add_judgement_exact_leading_date_race_context"


def _paragraph_spans(text: str) -> list[tuple[int, int, int, str]]:
    """Return (index, start, end, split basis); retain all source slices."""
    delimiters = [i for i, ch in enumerate(text) if ch == "●"]
    if not delimiters:
        return [(0, 0, len(text), "whole_field_no_event_marker")]
    spans: list[tuple[int, int, int, str]] = []
    if text[:delimiters[0]].strip():
        spans.append((0, 0, delimiters[0], "preamble_before_event_marker"))
    for idx, marker_pos in enumerate(delimiters):
        start = marker_pos + 1
        end = delimiters[idx + 1] if idx + 1 < len(delimiters) else len(text)
        spans.append((len(spans), start, end, "event_marker_bullet"))
    return spans


def process_report(report: Mapping[str, Any], runners: Any) -> dict[str, list[dict[str, Any]]]:
    """Extract event paragraphs/sentences and conservatively link horse mentions.

    `runners` is either the exact parent-event roster list (synthetic/control
    use) or a dict keyed by `(actual_meet, ISO event_date, race_no)` (production).
    For `addJudgement`, only the exact leading date/race in that paragraph selects
    its own roster. No list fallback to the parent report roster is permitted.
    """
    parent_key = _event_key(report.get("actual_meet_code"), report.get("race_date_iso"), report.get("rcNo"))
    observation_locator = str(report.get("observation_locator") or _stable_id("obs_", report.get("capture_id"), report.get("source_location")))
    source_fields = {k: report.get(k) for k in ("capture_id", "dataset", "source_row_sha256", "source_path", "page_sha256", "source_location", "source_captured_at_utc", "source_captured_at_ms", "requested_at_utc", "requested_at_ms", "page_no", "row_no")}
    source_fields["historical_publication_time_verified"] = False
    source_fields["source_publication_at_kst"] = None
    paragraphs: list[dict[str, Any]] = []
    sentences: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    residuals: list[dict[str, Any]] = []
    context_groups: list[dict[str, Any]] = []

    for field in TEXT_FIELDS:
        original = report.get(field)
        if original is None or original in ("", "-", "null"):
            state = "null" if original is None else ("blank" if original == "" else ("dash_placeholder" if original == "-" else "literal_null"))
            paragraphs.append({
                **source_fields, "observation_locator": observation_locator,
                "report_text_field": field, "paragraph_index": 0,
                "paragraph_locator": _stable_id("para_", observation_locator, field, state),
                "paragraph_source_text_raw": original, "span_start_codepoint": None,
                "span_end_codepoint": None, "paragraph_raw": original,
                "paragraph_state": state, "split_basis": "source_field_state",
                "parent_actual_meet_code": parent_key[0] if parent_key else None,
                "parent_event_date": parent_key[1] if parent_key else None,
                "parent_race_no": parent_key[2] if parent_key else None,
                "target_actual_meet_code": None, "target_event_date": None,
                "target_race_no": None, "target_context_status": "source_field_not_text",
            })
            continue
        if not isinstance(original, str):
            original = str(original)
        field_spans = _paragraph_spans(original)
        field_anchor_valid: dict[tuple[tuple[int, str, int], str], set[tuple[str, str]]] = defaultdict(set)
        field_anchor_poison: set[tuple[tuple[int, str, int], str]] = set()
        field_anchor_locators: dict[tuple[tuple[int, str, int], str], set[str]] = defaultdict(set)
        # Pre-index only exact anchors from this one source field and target
        # event. This allows a later unnumbered paragraph reuse while preventing
        # cross-field and cross-event leakage.
        for fidx, fstart, fend, _ in field_spans:
            fraw = original[fstart:fend]
            if field == "addJudgement":
                fkey, _fstatus = _add_target(fraw, parent_key)
            else:
                fkey = parent_key
            if fkey is None:
                continue
            froster = [_roster_fields(row) for row in _provided_roster(runners, fkey, parent_key)]
            froster = [row for row in froster if row["program_no_raw"] not in (None, "") and str(row["program_no_raw"]).strip() and row["official_horse_id"] not in (None, "") and str(row["official_horse_id"]).strip() and row["horse_name_raw"] not in (None, "") and str(row["horse_name_raw"]).strip()]
            fpara = _stable_id("para_", observation_locator, field, fidx, fstart, fend)
            for marker_pos, marker_char, program_no in [(i, ch, CIRCLED.index(ch) + 1) for i, ch in enumerate(fraw) if ch in CIRCLED]:
                parsed = _marker_name(fraw, marker_pos, _quote_pairs(fraw))
                if not parsed:
                    continue
                name, name_start, name_end = parsed
                number_rows = [r for r in froster if _int_or_none(r["program_no_raw"]) == program_no]
                key_name = (fkey, name)
                cand_start, cand_end = min(marker_pos, name_start), max(marker_pos + 1, name_end)
                anchor_id = _stable_id("mention_", fpara, "circled_number_quoted_name_anchor", cand_start, cand_end, str(program_no), name)
                if len(number_rows) == 1 and _name_matches_roster(name, str(number_rows[0]["horse_name_raw"]), fkey[0]):
                    identity = (str(number_rows[0]["official_horse_id"]), str(number_rows[0]["program_no_raw"]))
                    canonical_key = (fkey, str(number_rows[0]["horse_name_raw"]))
                    field_anchor_valid[canonical_key].add(identity)
                    field_anchor_locators[canonical_key].add(anchor_id)
                else:
                    field_anchor_poison.add(key_name)
                    # If a display prefix was used, poison the corresponding
                    # roster name too when the number points to that entry.
                    for row in number_rows:
                        field_anchor_poison.add((fkey, str(row["horse_name_raw"])))

        for para_index, start, end, split_basis in field_spans:
            raw = original[start:end]
            if field == "addJudgement":
                target_key, target_status = _add_target(raw, parent_key)
            else:
                target_key, target_status = (parent_key, "parent_report_event_context")
                if target_key is None:
                    target_status = "parent_event_key_invalid"
            roster_raw = _provided_roster(runners, target_key, parent_key)
            roster = [_roster_fields(row) for row in roster_raw]
            # Rows with incomplete IDs/number/name cannot authorize a horse link.
            roster = [row for row in roster if row["program_no_raw"] not in (None, "") and str(row["program_no_raw"]).strip() and row["official_horse_id"] not in (None, "") and str(row["official_horse_id"]).strip() and row["horse_name_raw"] not in (None, "") and str(row["horse_name_raw"]).strip()]
            para_id = _stable_id("para_", observation_locator, field, para_index, start, end)
            paragraph = {
                **source_fields, "observation_locator": observation_locator,
                "report_text_field": field, "paragraph_index": para_index,
                "paragraph_locator": para_id, "paragraph_source_text_raw": original,
                "span_start_codepoint": start, "span_end_codepoint": end,
                "paragraph_raw": raw, "paragraph_state": "text",
                "split_basis": split_basis,
                "parent_actual_meet_code": parent_key[0] if parent_key else None,
                "parent_event_date": parent_key[1] if parent_key else None,
                "parent_race_no": parent_key[2] if parent_key else None,
                "target_actual_meet_code": target_key[0] if target_key else None,
                "target_event_date": target_key[1] if target_key else None,
                "target_race_no": target_key[2] if target_key else None,
                "target_context_status": target_status if target_key else target_status,
                "target_roster_row_count": len(roster),
            }
            paragraphs.append(paragraph)
            paragraph_sentences: list[dict[str, Any]] = []
            for sentence_index, (sstart, send) in enumerate(_sentence_spans(original, start, end)):
                sentence = {
                    **source_fields, "observation_locator": observation_locator,
                    "paragraph_locator": para_id,
                    "sentence_locator": _stable_id("sent_", para_id, sentence_index, sstart, send),
                    "report_text_field": field, "sentence_index": sentence_index,
                    "sentence_source_text_raw": original,
                    "span_start_codepoint": sstart, "span_end_codepoint": send,
                    "sentence_raw": original[sstart:send],
                    "target_actual_meet_code": target_key[0] if target_key else None,
                    "target_event_date": target_key[1] if target_key else None,
                    "target_race_no": target_key[2] if target_key else None,
                    "target_context_status": target_status,
                }
                sentences.append(sentence)
                paragraph_sentences.append(sentence)

            q_pairs = _quote_pairs(raw)
            circled_positions = [(i, ch, CIRCLED.index(ch) + 1) for i, ch in enumerate(raw) if ch in CIRCLED]
            anchor_spans: dict[tuple[int, int], dict[str, Any]] = {}
            marker_data: list[dict[str, Any]] = []
            for pos, char, program_no in circled_positions:
                parsed = _marker_name(raw, pos, q_pairs)
                item = {"pos": pos, "char": char, "program_no": program_no, "parsed": parsed}
                marker_data.append(item)
                if parsed:
                    name, nstart, nend = parsed
                    anchor_spans[(nstart, nend)] = item

            candidate_mentions: list[dict[str, Any]] = []
            handled_spans: set[tuple[int, int]] = set()
            for item in marker_data:
                pos = item["pos"]
                if item["parsed"]:
                    name, nstart, nend = item["parsed"]
                    left, right = min(pos, nstart), max(pos + 1, nend)
                    candidate_mentions.append({
                        "kind": "circled_number_quoted_name_anchor",
                        "raw": raw[left:right], "name": name,
                        "name_start": nstart, "name_end": nend,
                        "start": left, "end": right,
                        "program_no": str(item["program_no"]),
                        "marker": item["char"], "marker_start": pos,
                        "marker_end": pos + 1, "anchor": True,
                    })
                    handled_spans.add((nstart, nend))
                else:
                    candidate_mentions.append({
                        "kind": "unparsed_circled_marker", "raw": item["char"],
                        "name": None, "name_start": None, "name_end": None,
                        "start": pos, "end": pos + 1,
                        "program_no": str(item["program_no"]),
                        "marker": item["char"], "marker_start": pos,
                        "marker_end": pos + 1, "anchor": False,
                    })

            for qstart, qend, _opening, _closing in q_pairs:
                nstart, nend = qstart + 1, qend
                while nstart < nend and raw[nstart].isspace():
                    nstart += 1
                while nend > nstart and raw[nend - 1].isspace():
                    nend -= 1
                if nstart >= nend or (nstart, nend) in handled_spans:
                    continue
                # A circled numeral at the beginning of a quote was already
                # emitted as an anchor or residual; do not create a false name.
                if raw[nstart] in CIRCLED:
                    continue
                candidate_mentions.append({
                    "kind": "exact_quoted_roster_name", "raw": raw[nstart:nend],
                    "name": raw[nstart:nend], "name_start": nstart,
                    "name_end": nend, "start": qstart, "end": qend + 1,
                    "program_no": None, "marker": None,
                    "marker_start": None, "marker_end": None,
                    "anchor": False,
                })

            # Resolve explicit anchors first, then only safe report-field-local
            # quoted-name reuse. Invalid same-name anchors poison reuse.
            anchor_valid: dict[str, set[tuple[str, str]]] = defaultdict(set)
            anchor_poison: set[str] = set()
            anchor_locators: dict[str, set[str]] = defaultdict(set)
            if target_key:
                for (ctx, name), values in field_anchor_valid.items():
                    if ctx == target_key:
                        anchor_valid[name].update(values)
                        anchor_locators[name].update(field_anchor_locators.get((ctx, name), set()))
                anchor_poison.update(name for ctx, name in field_anchor_poison if ctx == target_key)
            resolved: list[dict[str, Any]] = []
            for cand in candidate_mentions:
                status = "candidate_unresolved"
                matched: list[dict[str, Any]] = []
                if not target_key:
                    status = "unresolved_target_event_context"
                elif not roster:
                    status = "no_event_runner_roster"
                elif cand["anchor"]:
                    wanted = _int_or_none(cand["program_no"])
                    num_matches = [r for r in roster if _int_or_none(r["program_no_raw"]) == wanted]
                    if len(num_matches) > 1:
                        status = "ambiguous_roster_number"
                    elif not num_matches:
                        status = "program_no_not_on_event_roster"
                    elif not _name_matches_roster(cand["name"], str(num_matches[0]["horse_name_raw"]), target_key[0]):
                        status = "number_name_mismatch"
                    elif not num_matches[0]["official_horse_id"]:
                        status = "missing_event_horse_id"
                    else:
                        matched = num_matches
                        status = "explicit_number_name_race_roster_exact" if str(num_matches[0]["horse_name_raw"]) == cand["name"] else "explicit_number_name_venue_prefix_exact"
                        anchor_valid[str(num_matches[0]["horse_name_raw"])].add((str(num_matches[0]["official_horse_id"]), str(num_matches[0]["program_no_raw"])))
                    if status not in ("explicit_number_name_race_roster_exact", "explicit_number_name_venue_prefix_exact") and cand["name"]:
                        anchor_poison.add(cand["name"])
                elif cand["name"]:
                    named = [r for r in roster if _name_matches_roster(cand["name"], str(r["horse_name_raw"]), target_key[0])]
                    identities = {(str(r["official_horse_id"]), str(r["program_no_raw"])) for r in named}
                    canonical_name = str(named[0]["horse_name_raw"]) if len(named) == 1 else cand["name"]
                    valid_anchors = anchor_valid.get(canonical_name, set())
                    # Second pass below handles anchors after this quote too.
                    status = "name_only_without_explicit_anchor"
                    if len(identities) > 1:
                        status = "ambiguous_roster_name"
                    elif not identities:
                        status = "quoted_name_not_on_event_roster"
                    elif cand["name"] in anchor_poison or canonical_name in anchor_poison:
                        status = "report_local_anchor_conflict"
                    elif len(valid_anchors) == 1 and identities == valid_anchors:
                        matched = named
                        status = "report_local_exact_name_from_unique_anchor"
                resolved.append({**cand, "status": status, "matched": matched})

            # Re-evaluate unnumbered candidates against all anchors in this same
            # source field+paragraph, including anchors appearing later in text.
            for cand in resolved:
                if cand["anchor"] or not cand.get("name") or not target_key or not roster:
                    continue
                named = [r for r in roster if _name_matches_roster(cand["name"], str(r["horse_name_raw"]), target_key[0])]
                identities = {(str(r["official_horse_id"]), str(r["program_no_raw"])) for r in named}
                canonical_name = str(named[0]["horse_name_raw"]) if len(named) == 1 else cand["name"]
                valid_anchors = anchor_valid.get(canonical_name, set())
                if cand["name"] in anchor_poison or canonical_name in anchor_poison or len(valid_anchors) > 1:
                    cand["status"], cand["matched"] = "report_local_anchor_conflict", []
                elif len(valid_anchors) == 1 and identities == valid_anchors:
                    cand["status"], cand["matched"] = "report_local_exact_name_from_unique_anchor", named

            per_horse_links: dict[tuple[str, str], dict[str, Any]] = {}
            for cand in resolved:
                mention_id = _stable_id("mention_", para_id, cand["kind"], cand["start"], cand["end"], cand.get("program_no"), cand.get("name"))
                mention_row = {
                    **source_fields, "observation_locator": observation_locator,
                    "paragraph_locator": para_id, "mention_locator": mention_id,
                    "report_text_field": field, "mention_kind": cand["kind"],
                    "mention_raw": original[start + cand["start"]:start + cand["end"]], "raw_name": cand.get("name"),
                    "raw_program_no": cand.get("program_no"),
                    "raw_circled_marker": cand.get("marker"),
                    "span_start_codepoint": start + cand["start"],
                    "span_end_codepoint": start + cand["end"],
                    "name_start_codepoint": start + cand["name_start"] if cand.get("name_start") is not None else None,
                    "name_end_codepoint": start + cand["name_end"] if cand.get("name_end") is not None else None,
                    "marker_start_codepoint": start + cand["marker_start"] if cand.get("marker_start") is not None else None,
                    "marker_end_codepoint": start + cand["marker_end"] if cand.get("marker_end") is not None else None,
                    "candidate_status": cand["status"],
                    "candidate_official_horse_id": cand["matched"][0]["official_horse_id"] if len(cand["matched"]) == 1 else None,
                    "candidate_roster_program_no_raw": cand["matched"][0]["program_no_raw"] if len(cand["matched"]) == 1 else None,
                    "target_actual_meet_code": target_key[0] if target_key else None,
                    "target_event_date": target_key[1] if target_key else None,
                    "target_race_no": target_key[2] if target_key else None,
                    "target_context_status": target_status,
                    "anchor_mention_locators_json": json.dumps(sorted(anchor_locators.get(str(cand["matched"][0]["horse_name_raw"]), set())) if cand.get("status") == "report_local_exact_name_from_unique_anchor" and cand.get("matched") else [], ensure_ascii=False, separators=(",", ":")),
                }
                mentions.append(mention_row)
                if cand["kind"] == "unparsed_circled_marker":
                    residuals.append({
                        **source_fields, "observation_locator": observation_locator,
                        "paragraph_locator": para_id, "mention_locator": mention_id,
                        "report_text_field": field, "marker_raw": cand["marker"],
                        "marker_value": cand["program_no"],
                        "span_start_codepoint": start + cand["start"],
                        "span_end_codepoint": start + cand["end"],
                        "residual_status": "circled_marker_without_supported_adjacent_quoted_name",
                    })
                for roster_row in cand["matched"]:
                    identity = (str(roster_row["official_horse_id"]), str(roster_row["program_no_raw"]))
                    link = per_horse_links.setdefault(identity, {
                        **source_fields, "observation_locator": observation_locator,
                        "paragraph_locator": para_id,
                        "official_horse_id": roster_row["official_horse_id"],
                        "program_no_raw": str(roster_row["program_no_raw"]),
                        "match_rule": cand["status"],
                        "linked_mention_locators": [],
                        "mention_semantics": "mentioned_in_report_paragraph",
                        "status": "linked",
                        "target_actual_meet_code": target_key[0],
                        "target_event_date": target_key[1],
                        "target_race_no": target_key[2],
                        "target_context_status": target_status,
                        "event_execution_status": roster_row["event_execution_status"],
                        "roster_source_file": roster_row["roster_source_file"],
                        "roster_source_item_index": roster_row["roster_source_item_index"],
                        "roster_horse_name_raw": roster_row["horse_name_raw"],
                    })
                    link["linked_mention_locators"].append(mention_id)
            for link in per_horse_links.values():
                ids = set(link["linked_mention_locators"])
                link["linked_mention_locators_json"] = json.dumps(link.pop("linked_mention_locators"), ensure_ascii=False, separators=(",", ":"))
                linked_sents = [s["sentence_locator"] for s in paragraph_sentences if any(
                    m["mention_locator"] in ids and
                    m["span_start_codepoint"] >= s["span_start_codepoint"] and
                    m["span_end_codepoint"] <= s["span_end_codepoint"] for m in mentions if m["paragraph_locator"] == para_id
                )]
                link["linked_sentence_locators_json"] = json.dumps(linked_sents, ensure_ascii=False, separators=(",", ":"))
                links.append(link)

            context_groups.append({"field": field, "target_key": target_key, "target_status": target_status,
                                   "paragraph_locator": para_id, "marker_count": len(circled_positions)})

    return {
        "paragraphs": paragraphs,
        "sentences": sentences,
        "mentions": mentions,
        "links": links,
        "marker_residuals": residuals,
    }

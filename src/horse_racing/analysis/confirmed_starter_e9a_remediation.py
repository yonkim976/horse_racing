"""Predicate-scoped E9-A review candidates; never a pre-race feature.

The v3 extractor is retained as a candidate generator. A candidate is clear only
when its horse and role can be attached to an asserted local predicate. This is
deliberately a lower-recall review tool, not an estimate of population accuracy.
"""

from __future__ import annotations

import re
from typing import Any

from horse_racing.analysis.confirmed_starter_e9a import Runner, extract_report

RULE_VERSION = "e9a_predicate_scope_v9"
MARKER = re.compile(r"(?P<number>[①-⑳])\s*[“”\"](?P<name>[^“”\"]+)[“”\"]")
START = re.compile(r"출발이 늦|늦게 나오는|출발이 좋지 못|출발이 좋지 않|발진이 늦")
BLOCK = re.compile(r"안쪽 공간이 여의치 않아|진로가 여의치 않아|진로가 막혀|앞이 막혀")
VICTIM = re.compile(r"주행이 불편|밀렸|밀리며|불편하였")
CONTACT = re.compile(r"접촉하|부딪쳤|부딪친|부딪치며")
MOVE = re.compile(r"기대며 나가|기대며 들어|진로를 변경|진로변경|안으로 들어가|바깥으로 나가")
NEGATED = re.compile(r"(?:사실은|것은|적은|상황은)\s*(?:없|아니)|지\s*않|않았|없었|아니었")
CONDITIONAL = re.compile(r"만약|가정|이라면|였다면|가능성이 있|추정|수도 있")
QUOTE = re.compile(r"진술|주장|언급|전언|보고하였|말하였")
JOINT = re.compile(r"^\s*(?:[,，]\s*|[와과]\s*|및\s*)$")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _bullets(full_text: str) -> list[tuple[int, str]]:
    return [
        (match.start(1) + len(match.group(1)) - len(match.group(1).lstrip()), text)
        for match in re.finditer(r"(?:^|●)([^●]*)", full_text)
        if (text := match.group(1).strip())
    ]


def _sentence_bounds(text: str, position: int) -> tuple[int, int]:
    start = max(text.rfind(".", 0, position), text.rfind(";", 0, position)) + 1
    ends = [value for value in (text.find(".", position), text.find(";", position)) if value >= 0]
    return start, min(ends) + 1 if ends else len(text)


def _is_asserted(text: str, cue_start: int, cue_end: int) -> bool:
    start, end = _sentence_bounds(text, cue_start)
    sentence = text[start:end]
    if CONDITIONAL.search(sentence):
        return False
    # A quoted rider account can follow a separately asserted observation in
    # the same bullet. Only the quoted/attributed portion is rejected.
    if text[:cue_start].count("‘") > text[:cue_start].count("’"):
        return False
    if QUOTE.search(sentence) and (
        "‘" in sentence[: cue_start - start]
        or "“" not in sentence
        and "고 진술" in sentence
        or sentence.strip().startswith(("기수는", "기승기수는"))
        or re.search(r"(?:기수|기승기수|조교사|마주).{0,50}$", sentence[: cue_start - start])
        and re.search(r"진술|주장|언급|말하였", sentence[cue_end - start :])
    ):
        return False
    comma = text.find(",", cue_end, end)
    tail = text[cue_end : comma if comma >= 0 else end]
    local_negative = NEGATED.search(text[max(start, cue_start - 8) : cue_end])
    if text[cue_start:cue_end] == "출발이 좋지 않":
        local_negative = None
    if NEGATED.search(tail[:35]) or local_negative:
        return False
    return True


def _markers(text: str, runners: list[Runner]) -> list[tuple[int, int, Runner | None, int, str]]:
    by_number = {runner.horse_number: runner for runner in runners}
    found = []
    for match in MARKER.finditer(text):
        number = CIRCLED.index(match.group("number")) + 1
        name = match.group("name").strip()
        runner = by_number.get(number)
        if runner is not None and runner.horse_name != name:
            runner = None
        found.append((match.start(), match.end(), runner, number, name))
    return found


def _subjects(
    text: str,
    cue: re.Match[str],
    markers: list[tuple[int, int, Runner | None, int, str]],
    *,
    event_type: str,
) -> list[tuple[int, int, Runner | None, int, str]]:
    sentence_start, sentence_end = _sentence_bounds(text, cue.start())
    if event_type == "start_delay":
        following = next((m for m in markers if cue.end() <= m[0] < sentence_end), None)
        if following and re.match(
            r"(?:었던|았던|했던|못했던|않았던|였던)", text[cue.end() : following[0]]
        ):
            return [following]
    preceding = [m for m in markers if sentence_start <= m[0] < cue.start()]
    if not preceding:
        return []
    # Do not reach across an intervening independent predicate or past 90 chars.
    last = preceding[-1]
    if cue.start() - last[1] > 90:
        return []
    subjects = [last]
    for previous in reversed(preceding[:-1]):
        gap = text[previous[1] : subjects[0][0]]
        if JOINT.fullmatch(gap):
            subjects.insert(0, previous)
        else:
            break
    return subjects


def _clause(text: str, position: int, marker_start: int) -> tuple[int, int, str]:
    sentence_start, sentence_end = _sentence_bounds(text, position)
    start = max(sentence_start, min(marker_start, position))
    end = min(
        sentence_end,
        text.find(",", position) + 1 if "," in text[position:sentence_end] else sentence_end,
    )
    return start, end, text[start:end]


def _identity(marker: tuple[int, int, Runner | None, int, str]) -> list[Any] | None:
    return list(marker[2].source_key) if marker[2] else None


def _event_clause(text: str, row: dict[str, Any]) -> tuple[int, int, str] | None:
    """Locate the local assertion supporting an old role; otherwise abstain."""
    markers = list(MARKER.finditer(text))
    number = row["quoted_horse_number"]
    if number is None:
        return None
    if row["event_type"] == "contact":
        for cue in CONTACT.finditer(text):
            preceding = [marker for marker in markers if marker.start() < cue.start()]
            if len(preceding) < 2:
                continue
            actor, victim = preceding[-2:]
            actor_number = CIRCLED.index(actor.group("number")) + 1
            victim_number = CIRCLED.index(victim.group("number")) + 1
            expected = actor_number if row["role"] == "actor" else victim_number
            between = text[actor.end() : victim.start()]
            if (
                expected == number
                and MOVE.search(between)
                and "서로" not in text[actor.start() : cue.end()]
                and _is_asserted(text, cue.start(), cue.end())
            ):
                return _clause(text, cue.start(), actor.start())
        return None
    if row["event_type"] == "interference" and row["role"] == "victim":
        for index, marker in enumerate(markers):
            if CIRCLED.index(marker.group("number")) + 1 != number:
                continue
            next_start = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            cue = VICTIM.search(text, marker.end(), min(next_start, marker.end() + 45))
            if cue and _is_asserted(text, cue.start(), cue.end()):
                return _clause(text, cue.start(), marker.start())
        return None
    if row["event_type"] == "interference" and row["role"] == "actor":
        for index, marker in enumerate(markers):
            if CIRCLED.index(marker.group("number")) + 1 != number:
                continue
            next_start = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            cue = MOVE.search(text, marker.end(), min(next_start, marker.end() + 80))
            if cue is None and index + 1 < len(markers):
                joint_end = min(len(text), markers[index + 1].end() + 80)
                joint_text = text[marker.end() : joint_end]
                if "각각" in joint_text:
                    cue = MOVE.search(text, markers[index + 1].end(), joint_end)
            if cue and _is_asserted(text, cue.start(), cue.end()):
                return _clause(text, cue.start(), marker.start())
        return None
    return None


def _scoped_predicates(
    fields: dict[str, str | None], runners: list[Runner]
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for field in ("judgement", "addJudgement"):
        for bullet_start, text in _bullets(fields.get(field) or ""):
            if text.startswith("<추가심판사항>"):
                continue
            markers = _markers(text, runners)
            for event_type, pattern, role in (
                ("start_delay", START, "affected"),
                ("blocked_or_controlled", BLOCK, "victim"),
            ):
                for cue in pattern.finditer(text):
                    subjects = _subjects(text, cue, markers, event_type=event_type)
                    asserted = _is_asserted(text, cue.start(), cue.end())
                    if not subjects:
                        found.append(
                            {
                                "source_field": field,
                                "event_type": event_type,
                                "role": "unknown",
                                "horse_source_key": None,
                                "certainty": "abstain",
                                "reason": "predicate_subject_unresolved",
                                "clause_start": bullet_start + cue.start(),
                                "clause_end": bullet_start + cue.end(),
                                "clause_text": text[cue.start() : cue.end()],
                            }
                        )
                    for marker in subjects:
                        local_start, local_end, local_text = _clause(text, cue.start(), marker[0])
                        found.append(
                            {
                                "source_field": field,
                                "event_type": event_type,
                                "role": role if asserted and marker[2] else "unknown",
                                "horse_source_key": _identity(marker),
                                "quoted_horse_number": marker[3],
                                "quoted_horse_name": marker[4],
                                "certainty": "clear" if asserted and marker[2] else "abstain",
                                "reason": None
                                if asserted and marker[2]
                                else (
                                    "identity_unknown"
                                    if marker[2] is None
                                    else "not_asserted_observation"
                                ),
                                "clause_start": bullet_start + local_start,
                                "clause_end": bullet_start + local_end,
                                "clause_text": local_text,
                            }
                        )
    return found


def _recover_sentence_facts(
    fields: dict[str, str | None], runners: list[Runner], context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Recover direct interference facts when a later condition vetoed a v3 bullet."""
    recovered: list[dict[str, Any]] = []
    for field in ("judgement", "addJudgement"):
        for bullet_start, bullet_text in _bullets(fields.get(field) or ""):
            if bullet_text.startswith("<추가심판사항>"):
                continue
            for sentence_match in re.finditer(r"[^.;]+[.;]?", bullet_text):
                raw_sentence = sentence_match.group()
                sentence = raw_sentence.strip()
                if not sentence:
                    continue
                sentence_start = (
                    bullet_start
                    + sentence_match.start()
                    + len(raw_sentence)
                    - len(raw_sentence.lstrip())
                )
                candidates = extract_report(
                    {"judgement": sentence, "addJudgement": None}, runners, context=context
                )
                for candidate in candidates:
                    if (
                        candidate["certainty"] != "clear"
                        or candidate["event_type"] != "interference"
                    ):
                        continue
                    clause = _event_clause(sentence, candidate)
                    if clause is None:
                        continue
                    local_start, local_end, local_text = clause
                    recovered.append(
                        {
                            **candidate,
                            "source_field": field,
                            "span_start": bullet_start,
                            "span_end": bullet_start + len(bullet_text),
                            "span_text": bullet_text,
                            "clause_start": sentence_start + local_start,
                            "clause_end": sentence_start + local_end,
                            "clause_text": local_text,
                            "rule_version": RULE_VERSION,
                            "rule": "sentence_scoped_recovered_interference",
                        }
                    )
    return recovered


def remediate_report(
    fields: dict[str, str | None], runners: list[Runner], *, context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return v9 evidence with conservative holds and predicate-level offsets."""
    old = extract_report(fields, runners, context=context)
    scoped = _scoped_predicates(fields, runners)
    out: list[dict[str, Any]] = []
    matched: set[int] = set()
    for row in old:
        updated = {**row, "rule_version": RULE_VERSION}
        if row["certainty"] != "clear":
            out.append(updated)
            continue
        if row["event_type"] in {"start_delay", "blocked_or_controlled"}:
            matches = [
                (index, item)
                for index, item in enumerate(scoped)
                if item["event_type"] == row["event_type"]
                and item["source_field"] == row["source_field"]
                and item["horse_source_key"] == row["horse_source_key"]
                and item["certainty"] == "clear"
                and row["span_start"] <= item["clause_start"] < row["span_end"]
            ]
            if matches:
                index, item = matches[0]
                matched.add(index)
                updated.update(
                    {key: item[key] for key in ("clause_start", "clause_end", "clause_text")}
                )
            else:
                updated.update(
                    certainty="hold", role="unknown", reason="predicate_subject_not_validated"
                )
        elif row["event_type"] in {"interference", "contact"}:
            clause = _event_clause(row["span_text"], row)
            if clause is None:
                updated.update(
                    certainty="hold",
                    role="unknown",
                    reason="event_role_clause_not_validated",
                )
            else:
                local_start, local_end, local_text = clause
                updated.update(
                    clause_start=row["span_start"] + local_start,
                    clause_end=row["span_start"] + local_end,
                    clause_text=local_text,
                )
        else:
            updated.update(certainty="hold", role="unknown", reason="role_not_reviewed")
        out.append(updated)
    for index, item in enumerate(scoped):
        if index in matched or item["certainty"] != "clear":
            continue
        full_text = fields[item["source_field"]] or ""
        bullet = next(
            (
                (start, text)
                for start, text in _bullets(full_text)
                if start <= item["clause_start"] < start + len(text)
            ),
            None,
        )
        if bullet is None:
            continue
        bullet_start, bullet_text = bullet
        out.append(
            {
                **context,
                **item,
                "span_start": bullet_start,
                "span_end": bullet_start + len(bullet_text),
                "span_text": bullet_text,
                "location_raw": None,
                "rule_version": RULE_VERSION,
                "rule": "predicate_scoped_" + item["event_type"],
            }
        )
    existing = {
        (
            row["source_field"],
            row["span_start"],
            row["event_type"],
            row["role"],
            tuple(row["horse_source_key"] or []),
        )
        for row in out
        if row["certainty"] == "clear"
    }
    for row in _recover_sentence_facts(fields, runners, context):
        identity = (
            row["source_field"],
            row["span_start"],
            row["event_type"],
            row["role"],
            tuple(row["horse_source_key"] or []),
        )
        if identity not in existing:
            existing.add(identity)
            out.append(row)
    return out

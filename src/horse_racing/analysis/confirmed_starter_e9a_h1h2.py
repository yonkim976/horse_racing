"""E9-A H1/H2 gates over the preserved v9 evidence candidates.

No output is a pre-race feature. The actor gate accepts only an asserted local
actor action tied to an observed victim or an explicit causal finding.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from horse_racing.analysis.confirmed_starter_e9a import Runner
from horse_racing.analysis.confirmed_starter_e9a_remediation import (
    CIRCLED,
    CONTACT,
    MARKER,
    MOVE,
    VICTIM,
    _is_asserted,
    _sentence_bounds,
    remediate_report,
)

RULE_VERSION = "e9a_h1h2_v1"
_DENIAL = re.compile(r"책임이 없|원인이 아니|원인 아님|무관|관계없|영향이 없|방해하지 않|정상 주행")
_CAUSE = re.compile(r"원인으로 판단|원인으로|원인이라고 판단|발생한 상황")
_CHAIN = re.compile(r"동 과정에서|이로 인해|그로 인해|그 결과")
_REVIEW_FINDING = re.compile(r"판단|처분|원인")


def conflicted_numbers(runners: list[Runner]) -> set[int]:
    """Fail closed on duplicate race number or source ID, including exact repeats.

    Duplicate names at *different unique numbers* remain distinguishable by
    the quoted number. A conflict in one number does not suppress other unique
    runners in that race.
    """
    by_number: dict[int, list[Runner]] = defaultdict(list)
    by_source: dict[str, list[Runner]] = defaultdict(list)
    for runner in runners:
        by_number[runner.horse_number].append(runner)
        by_source[runner.horse_source_id].append(runner)
    conflict = {number for number, rows in by_number.items() if len(rows) != 1}
    for rows in by_source.values():
        if len(rows) != 1:
            conflict.update(row.horse_number for row in rows)
    return conflict


def _marker_matches(text: str, number: int, name: str) -> list[re.Match[str]]:
    return [
        marker
        for marker in MARKER.finditer(text)
        if CIRCLED.index(marker.group("number")) + 1 == number
        and marker.group("name").strip() == name
    ]


def _observations(text: str, victim: dict[str, Any]) -> list[tuple[int, int]]:
    markers = list(MARKER.finditer(text))
    found = []
    for index, marker in enumerate(markers):
        if (
            CIRCLED.index(marker.group("number")) + 1 != victim["quoted_horse_number"]
            or marker.group("name").strip() != victim["quoted_horse_name"]
        ):
            continue
        next_start = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        cue = VICTIM.search(text, marker.end(), min(next_start, marker.end() + 55))
        if cue and _is_asserted(text, cue.start(), cue.end()):
            found.append((marker.start(), cue.end()))
    return found


def _actions(text: str, actor: dict[str, Any]) -> list[tuple[int, int, int]]:
    markers = list(MARKER.finditer(text))
    found = []
    for index, marker in enumerate(markers):
        if (
            CIRCLED.index(marker.group("number")) + 1 != actor["quoted_horse_number"]
            or marker.group("name").strip() != actor["quoted_horse_name"]
        ):
            continue
        next_start = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        cue = MOVE.search(text, marker.end(), min(next_start, marker.end() + 85))
        if cue is None and index + 1 < len(markers):
            joint_end = min(len(text), markers[index + 1].end() + 85)
            if "각각" in text[marker.end() : joint_end]:
                cue = MOVE.search(text, markers[index + 1].end(), joint_end)
        if cue and _is_asserted(text, cue.start(), cue.end()):
            found.append((marker.start(), cue.start(), cue.end()))
    return found


def _relation(actor: dict[str, Any], victims: list[dict[str, Any]]) -> dict[str, Any] | None:
    text = actor["span_text"]
    candidates: list[tuple[int, int, int, int, int, int, str, list[Any]]] = []
    for victim in victims:
        for victim_start, victim_end in _observations(text, victim):
            for action_start, action_cue_start, action_end in _actions(text, actor):
                if action_start <= victim_start:
                    actor_sentence = _sentence_bounds(text, action_cue_start)
                    victim_sentence = _sentence_bounds(text, victim_start)
                    between = text[action_start:victim_end]
                    next_markers = [
                        marker
                        for marker in MARKER.finditer(text)
                        if action_cue_start < marker.start() <= victim_start
                    ]
                    direct = (
                        actor_sentence == victim_sentence
                        and len(next_markers) == 1
                        and next_markers[0].start() == victim_start
                    )
                    chained = (
                        actor_sentence == victim_sentence
                        and _CHAIN.search(between) is not None
                        and len(next_markers) <= 3
                    )
                    causal = (
                        _CAUSE.search(text[victim_end : actor_sentence[1]]) is not None
                        and actor_sentence == victim_sentence
                    )
                    if (direct or chained or causal) and not _DENIAL.search(between):
                        relation_type = (
                            "direct_action_to_victim"
                            if direct
                            else "explicit_chain"
                            if chained
                            else "causal_finding"
                        )
                        candidates.append(
                            (
                                action_start,
                                victim_end,
                                action_start,
                                action_end,
                                victim_start,
                                victim_end,
                                relation_type,
                                victim["horse_source_key"],
                            )
                        )
                else:
                    action_sentence = _sentence_bounds(text, action_cue_start)
                    bridge = text[victim_start : action_sentence[1]]
                    reviewed_cause = (
                        (
                            "것에 대해" in text[victim_end:action_start]
                            or "상황에 대해" in text[victim_end:action_start]
                        )
                        and (
                            "충분한 거리 없이" in text[action_start:action_end]
                            or "부주의" in text[action_start:action_end]
                        )
                        and _REVIEW_FINDING.search(text[action_end : action_sentence[1]])
                    )
                    if (
                        action_sentence == _sentence_bounds(text, victim_start)
                        and (_CAUSE.search(text[action_end : action_sentence[1]]) or reviewed_cause)
                        and not _DENIAL.search(bridge)
                    ):
                        candidates.append(
                            (
                                victim_start,
                                action_sentence[1],
                                action_start,
                                action_end,
                                victim_start,
                                victim_end,
                                "victim_then_causal_finding",
                                victim["horse_source_key"],
                            )
                        )
    if not candidates:
        return None
    # Prefer the tightest supported relationship, which picks the later
    # ⑦→⑧ discomfort clause rather than the earlier mutual contact in 1698.
    start, end, action_start, action_end, victim_start, victim_end, relation_type, victim_key = min(
        candidates, key=lambda item: (item[1] - item[0], -item[0])
    )
    base = actor["span_start"]
    return {
        "relation_type": relation_type,
        "relation_span_start": base + start,
        "relation_span_end": base + end,
        "relation_span_text": text[start:end],
        "actor_action_span_start": base + action_start,
        "actor_action_span_end": base + action_end,
        "victim_observation_span_start": base + victim_start,
        "victim_observation_span_end": base + victim_end,
        "victim_horse_source_key": victim_key,
    }


def _contact_relation(
    actor: dict[str, Any], victims: list[dict[str, Any]]
) -> dict[str, Any] | None:
    clause = actor.get("clause_text")
    if not clause or not MOVE.search(clause) or not CONTACT.search(clause):
        return None
    for victim in victims:
        if (
            victim["event_type"] == "contact"
            and victim["source_field"] == actor["source_field"]
            and victim["span_start"] == actor["span_start"]
            and CIRCLED[victim["quoted_horse_number"] - 1] in clause
            and "서로" not in clause
        ):
            return {
                "relation_type": "directed_contact",
                "relation_span_start": actor["clause_start"],
                "relation_span_end": actor["clause_end"],
                "relation_span_text": clause,
                "actor_action_span_start": actor["clause_start"],
                "actor_action_span_end": actor["clause_end"],
                "victim_observation_span_start": victim["clause_start"],
                "victim_observation_span_end": victim["clause_end"],
                "victim_horse_source_key": victim["horse_source_key"],
            }
    return None


def extract_report_h1h2(
    fields: dict[str, str | None], runners: list[Runner], *, context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Filter v9 candidate identities and require event-linked actor evidence."""
    prior = remediate_report(fields, runners, context=context)
    conflict = conflicted_numbers(runners)
    clean: list[dict[str, Any]] = []
    seen_conflicts: set[tuple[Any, ...]] = set()
    for row in prior:
        updated = {**row, "rule_version": RULE_VERSION}
        number = row.get("quoted_horse_number")
        if number in conflict:
            updated.update(
                certainty="abstain",
                role="unknown",
                horse_source_key=None,
                reason="roster_number_or_source_id_not_unique",
            )
            key = (row["source_field"], row["span_start"], row["event_type"], number)
            if key in seen_conflicts:
                continue
            seen_conflicts.add(key)
        clean.append(updated)
    by_bullet: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in clean:
        if row["certainty"] == "clear" and row["role"] == "victim":
            by_bullet[(row["source_field"], row["span_start"], row["event_type"])].append(row)
    result = []
    for row in clean:
        if row["certainty"] != "clear" or row["role"] != "actor":
            result.append(row)
            continue
        victims = by_bullet.get((row["source_field"], row["span_start"], row["event_type"]), [])
        relation = (
            _contact_relation(row, victims)
            if row["event_type"] == "contact"
            else _relation(row, victims)
            if row["event_type"] == "interference"
            else None
        )
        if relation is None:
            result.append(
                {
                    **row,
                    "certainty": "hold",
                    "role": "unknown",
                    "reason": "actor_victim_relationship_not_validated",
                }
            )
        else:
            result.append({**row, **relation})
    return result

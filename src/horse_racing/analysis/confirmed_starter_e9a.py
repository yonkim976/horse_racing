"""Conservative E9-A steward-text event evidence, not a prediction feature."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

RULE_VERSION = "e9a_steward_rules_v3"
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_HORSE = re.compile(r"(?P<number>[①-⑳])\s*[“”\"](?P<name>[^“”\"]+)[“”\"]")
_START = re.compile(r"출발이 늦|늦게 나오는|출발이 좋지 못|출발이 좋지 않|발진이 늦")
_BLOCK = re.compile(r"안쪽 공간이 여의치 않아|진로가 여의치 않아|진로가 막혀|앞이 막혀")
_VICTIM = re.compile(r"(?:의 주행이 불편|가 밀렸|이 밀렸|가 불편하였|가 밀리며)")
_CONTACT = re.compile(r"접촉하|부딪쳤|부딪친|부딪치며")
_MOVE = re.compile(r"기대며 나가|기대며 들어|진로를 변경|진로변경|안으로 들어가|바깥으로 나가")
_NEGATION = re.compile(r"방해하지 않|접촉하지 않|부딪치지 않|밀리지 않|진로를 변경하지 않")
_UNCERTAIN = re.compile(r"추정|가능성이 있|만약|가정|진술")
_SPECULATIVE = re.compile(r"만약|가정하|가능성이 있|것으로 추정|으로 추정|이라면|였다면")
_START_NEG = re.compile(r"출발이 늦지 않|출발이 늦은 것은 아니|늦게 나오지 않")
_LOCATION = re.compile(
    r"출발 시|출발 후 약 \d+m|[1-4](?:~|-)[1-4]코너(?: 구간| 지점)?|"
    r"[1-4]코너(?: 지점| 구간)?|결승선 전방 약 \d+m 지점|결승선 직선주로|"
    r"건너편 직선주로"
)


@dataclass(frozen=True)
class Runner:
    meet: int
    race_date: str
    race_number: int
    horse_number: int
    horse_source_id: str
    horse_name: str

    @property
    def source_key(self) -> tuple[int, str, int, int, str]:
        return (
            self.meet,
            self.race_date,
            self.race_number,
            self.horse_number,
            self.horse_source_id,
        )


@dataclass(frozen=True)
class _Marker:
    start: int
    end: int
    number: int
    name: str
    runner: Runner | None
    conflict: str | None


def _markers(text: str, runners: list[Runner]) -> list[_Marker]:
    by_number: dict[int, list[Runner]] = {}
    by_name: dict[str, list[Runner]] = {}
    for runner in runners:
        by_number.setdefault(runner.horse_number, []).append(runner)
        by_name.setdefault(runner.horse_name, []).append(runner)
    markers = []
    for match in _HORSE.finditer(text):
        number = _CIRCLED.index(match.group("number")) + 1
        name = match.group("name").strip()
        candidates = by_number.get(number, [])
        runner = (
            candidates[0] if len(candidates) == 1 and candidates[0].horse_name == name else None
        )
        conflict = None
        if runner is None:
            conflict = (
                "duplicate_name_or_number"
                if len(by_name.get(name, [])) > 1 or len(candidates) > 1
                else "number_name_conflict_or_unlisted"
            )
        markers.append(_Marker(match.start(), match.end(), number, name, runner, conflict))
    return markers


def _quoted_uncertainty(text: str, position: int) -> bool:
    return text[:position].count("‘") > text[:position].count("’")


def extract_report(
    fields: dict[str, str | None], runners: list[Runner], *, context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return evidence rows; no result/next-race inputs or inferred loss score."""
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for field in ("judgement", "addJudgement"):
        full_text = fields.get(field) or ""
        for bullet in re.finditer(r"(?:^|●)([^●]*)", full_text):
            text = bullet.group(1).strip()
            if not text:
                continue
            start = bullet.start(1) + len(bullet.group(1)) - len(bullet.group(1).lstrip())
            end = start + len(text)
            markers = _markers(text, runners)
            location_match = _LOCATION.search(text)
            location = location_match.group() if location_match else None
            base = {
                **context,
                "source_field": field,
                "span_start": start,
                "span_end": end,
                "span_text": text,
                "location_raw": location,
                "rule_version": RULE_VERSION,
            }
            before_count = len(evidence)

            def emit(
                event_type: str,
                role: str,
                marker: _Marker | None,
                rule: str,
                *,
                certainty: str = "clear",
                reason: str | None = None,
                local_field: str = field,
                local_start: int = start,
                local_base: dict[str, Any] = base,
            ) -> None:
                if marker is not None and marker.conflict:
                    certainty = "abstain"
                    reason = marker.conflict
                    role = "unknown"
                identity = list(marker.runner.source_key) if marker and marker.runner else None
                key = (local_field, local_start, event_type, role, tuple(identity or []), rule)
                if key in seen:
                    return
                seen.add(key)
                evidence.append(
                    {
                        **local_base,
                        "event_type": event_type,
                        "role": role,
                        "horse_source_key": identity,
                        "quoted_horse_number": marker.number if marker else None,
                        "quoted_horse_name": marker.name if marker else None,
                        "rule": rule,
                        "certainty": certainty,
                        "reason": reason,
                    }
                )

            if text.startswith("<추가심판사항>"):
                emit(
                    "unresolved",
                    "unknown",
                    None,
                    "cross_race_addendum",
                    certainty="abstain",
                    reason="addendum_may_describe_different_race",
                )
                continue
            if text.startswith(("경주 결과", "경주 후")):
                if "모래" in text:
                    emit(
                        "sand_overlap_only",
                        "unknown",
                        None,
                        "post_race_sand",
                        certainty="abstain",
                        reason="existing_sand_domain_or_rider_statement",
                    )
                continue
            if _SPECULATIVE.search(text):
                emit(
                    "unresolved",
                    "unknown",
                    None,
                    "speculative_or_conditional",
                    certainty="abstain",
                    reason="not_an_asserted_observation",
                )
                continue
            if _NEGATION.search(text) and not (_CONTACT.search(text) or _VICTIM.search(text)):
                continue
            if "모래" in text and not (
                _START.search(text)
                or _BLOCK.search(text)
                or _VICTIM.search(text)
                or _CONTACT.search(text)
            ):
                emit(
                    "sand_overlap_only",
                    "unknown",
                    None,
                    "sand_only",
                    certainty="abstain",
                    reason="existing_sand_domain_not_e9_event",
                )
                continue

            for cue in _START.finditer(text):
                if _START_NEG.search(text[max(0, cue.start() - 3) : cue.end() + 18]):
                    continue
                if _quoted_uncertainty(text, cue.start()):
                    emit(
                        "start_delay",
                        "unknown",
                        None,
                        "quoted_start",
                        certainty="abstain",
                        reason="quoted_or_conditional_text",
                    )
                    continue
                following = next(
                    (
                        m
                        for m in markers
                        if cue.end() <= m.start <= cue.end() + 14
                        and text[cue.end() : m.start].startswith(("었던", "은", "던"))
                    ),
                    None,
                )
                if following:
                    subjects = [following]
                else:
                    clause_start = max(text.rfind(sep, 0, cue.start()) for sep in (",", ".", ";"))
                    subjects = [m for m in markers if clause_start < m.start < cue.start()]
                    if not subjects:
                        subjects = [m for m in markers if m.end <= cue.start()][-1:]
                    elif len(subjects) > 1 and not any(
                        word in text[clause_start + 1 : cue.start()]
                        for word in ("각각", "모두", "와 ", "과 ")
                    ):
                        subjects = subjects[-1:]
                if not subjects:
                    emit(
                        "start_delay",
                        "unknown",
                        None,
                        "start_no_subject",
                        certainty="abstain",
                        reason="subject_not_identified",
                    )
                for subject in subjects:
                    emit("start_delay", "affected", subject, "explicit_start_delay")

            for cue in _BLOCK.finditer(text):
                if "경주 결과" in text[: cue.start()] or _quoted_uncertainty(text, cue.start()):
                    emit(
                        "blocked_or_controlled",
                        "unknown",
                        None,
                        "reported_block",
                        certainty="abstain",
                        reason="post_race_statement_or_quote",
                    )
                    continue
                subjects = [m for m in markers if cue.start() - 90 <= m.start < cue.start()]
                if len(subjects) > 3:
                    emit(
                        "blocked_or_controlled",
                        "unknown",
                        None,
                        "block_many_names",
                        certainty="abstain",
                        reason="multiple_subjects_ambiguous",
                    )
                elif subjects:
                    for subject in subjects:
                        emit("blocked_or_controlled", "victim", subject, "explicit_space_block")
                else:
                    emit(
                        "blocked_or_controlled",
                        "unknown",
                        None,
                        "block_no_subject",
                        certainty="abstain",
                        reason="subject_not_identified",
                    )

            for marker_index, marker in enumerate(markers):
                next_marker_start = (
                    markers[marker_index + 1].start
                    if marker_index + 1 < len(markers)
                    else len(text)
                )
                following = text[marker.end : min(next_marker_start, marker.end + 28)]
                victim_match = _VICTIM.search(following)
                if victim_match and not _NEGATION.search(following):
                    emit("interference", "victim", marker, "explicit_discomfort_or_pushed")
                    before = [m for m in markers if m.end <= marker.start]
                    after = [m for m in markers if m.start > marker.end]
                    actor: _Marker | None = None
                    if before and _MOVE.search(text[before[-1].end : marker.start]):
                        actor = before[-1]
                    elif after and "것에 대해" in text[marker.end : after[0].start + 1]:
                        actor_text = text[after[0].end : after[0].end + 100]
                        if _MOVE.search(actor_text):
                            actor = after[0]
                    if actor:
                        emit("interference", "actor", actor, "explicit_actor_movement")

            for cue in _CONTACT.finditer(text):
                if _quoted_uncertainty(text, cue.start()):
                    emit(
                        "contact",
                        "unknown",
                        None,
                        "quoted_contact",
                        certainty="abstain",
                        reason="quoted_or_conditional_text",
                    )
                    continue
                preceding = [m for m in markers if cue.start() - 90 <= m.start < cue.start()]
                pair = preceding[-2:]
                if len(pair) != 2:
                    emit(
                        "contact",
                        "unknown",
                        None,
                        "contact_no_pair",
                        certainty="abstain",
                        reason="pair_not_identified",
                    )
                    continue
                between = text[pair[0].end : pair[1].start]
                if _MOVE.search(between) and "서로" not in text[pair[0].start : cue.end()]:
                    emit("contact", "actor", pair[0], "movement_to_contact")
                    emit("contact", "victim", pair[1], "movement_to_contact")
                else:
                    for participant in pair:
                        emit(
                            "contact",
                            "unknown",
                            participant,
                            "mutual_contact",
                            certainty="ambiguous",
                            reason="causal_role_not_explicit",
                        )

            if _UNCERTAIN.search(text) and len(evidence) == before_count:
                emit(
                    "unresolved",
                    "unknown",
                    None,
                    "uncertain_text",
                    certainty="abstain",
                    reason="conditional_or_reported_not_factual",
                )
    return evidence

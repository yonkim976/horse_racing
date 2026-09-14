"""Fail-closed roster identity and event-linked actor regressions."""

import json
from pathlib import Path

from horse_racing.analysis.confirmed_starter_e9a import Runner
from horse_racing.analysis.confirmed_starter_e9a_h1h2 import extract_report_h1h2
from scripts.run_confirmed_starter_e9a import POPULATION, _raw_item, _runners

RUNNERS = [
    Runner(1, "20250101", 1, 1, "H1", "가온"),
    Runner(1, "20250101", 1, 2, "H2", "나래"),
    Runner(1, "20250101", 1, 3, "H3", "다온"),
]


def _rows(text: str, runners: list[Runner] | None = None) -> list[dict]:
    return extract_report_h1h2(
        {"judgement": text, "addJudgement": None},
        RUNNERS if runners is None else runners,
        context={},
    )


def _clear(rows: list[dict]) -> set[tuple[str, str, int]]:
    return {
        (row["event_type"], row["role"], row["quoted_horse_number"])
        for row in rows
        if row["certainty"] == "clear"
    }


def test_duplicate_number_different_name_is_order_invariant_abstain() -> None:
    conflict = [Runner(1, "20250101", 1, 1, "BAD", "다른말"), RUNNERS[0]]
    text = "①“가온”은 출발이 늦었음."
    forward = _rows(text, conflict)
    backward = _rows(text, list(reversed(conflict)))
    assert forward == backward
    assert not _clear(forward)
    assert any(row["certainty"] == "abstain" for row in forward)


def test_duplicate_number_same_name_distinct_id_and_duplicate_key_abstain() -> None:
    other = Runner(1, "20250101", 1, 1, "OTHER", "가온")
    for roster in ([RUNNERS[0], other], [other, RUNNERS[0]], [RUNNERS[0], RUNNERS[0]]):
        assert not _clear(_rows("①“가온”은 출발이 늦었음.", roster))


def test_duplicate_source_id_across_numbers_only_holds_affected_identities() -> None:
    duplicate_id = Runner(1, "20250101", 1, 2, "H1", "나래")
    roster = [RUNNERS[0], duplicate_id, RUNNERS[2]]
    rows = _rows("①“가온”은 출발이 늦었고, ③“다온”은 출발이 늦었음.", roster)
    assert ("start_delay", "affected", 1) not in _clear(rows)
    assert ("start_delay", "affected", 3) in _clear(rows)


def test_unique_identity_and_renumbered_name_remain_clear_order_invariant() -> None:
    renamed = [Runner(1, "20250101", 1, 4, "H4", "하늘"), RUNNERS[1]]
    text = "④“하늘”은 출발이 늦었음."
    assert _clear(_rows(text, renamed)) == _clear(_rows(text, list(reversed(renamed))))
    assert ("start_delay", "affected", 4) in _clear(_rows(text, renamed))


def test_same_name_at_distinct_unique_numbers_uses_quoted_number() -> None:
    same_name = [RUNNERS[0], Runner(1, "20250101", 1, 2, "H2", "가온")]
    text = "①“가온”과 ②“가온”은 각각 출발이 늦었음."
    forward = _clear(_rows(text, same_name))
    backward = _clear(_rows(text, list(reversed(same_name))))
    assert forward == backward
    assert {number for kind, role, number in forward if kind == "start_delay"} == {1, 2}


def test_disconnected_actor_is_held_but_victim_remains_clear() -> None:
    text = (
        "①“가온”의 주행이 불편했던 것에 대해 ②“나래”는 책임이 없으며 "
        "③“다온”이 안으로 진로변경한 것이 원인으로 판단. "
        "이후 ②“나래”가 바깥으로 나가 정상 주행하였음."
    )
    rows = _rows(text)
    assert ("interference", "victim", 1) in _clear(rows)
    assert ("interference", "actor", 2) not in _clear(rows)
    assert any(row["quoted_horse_number"] == 2 and row["certainty"] == "hold" for row in rows)


def test_direct_and_victim_first_causal_actor_are_linked() -> None:
    direct = _rows("②“나래”가 안으로 들어가 ①“가온”의 주행이 불편하였음.")
    assert ("interference", "actor", 2) in _clear(direct)
    assert any(row.get("relation_type") == "direct_action_to_victim" for row in direct)
    reverse = _rows(
        "①“가온”의 주행이 불편했던 것에 대해, ②“나래” 기승기수가 "
        "충분한 거리 없이 안으로 진로변경한 것이 원인으로 판단."
    )
    assert ("interference", "actor", 2) in _clear(reverse)
    assert any(row.get("relation_type") == "victim_then_causal_finding" for row in reverse)


def test_separate_sentence_or_negated_relationship_does_not_clear_actor() -> None:
    separate = _rows("①“가온”의 주행이 불편하였음. 이후 ②“나래”가 바깥으로 나가 주행하였음.")
    assert ("interference", "actor", 2) not in _clear(separate)
    denied = _rows(
        "①“가온”의 주행이 불편했던 것에 대해 ②“나래”는 책임이 없으며 ②“나래”가 바깥으로 나갔음."
    )
    assert ("interference", "actor", 2) not in _clear(denied)


def test_actual_1698_actor_links_later_discomfort_not_mutual_contact() -> None:
    selected = next(
        row
        for row in json.loads(POPULATION.read_text(encoding="utf-8"))["population"]
        if row["race_id"] == 1698
    )
    item = _raw_item(
        Path(selected["source_local_path"]),
        selected["race_date"].replace("-", ""),
        selected["race_number"],
    )
    assert item is not None
    fields = {"judgement": item.get("judgement"), "addJudgement": item.get("addJudgement")}
    rows = extract_report_h1h2(fields, _runners([selected])[1698], context={})
    actor = next(
        row
        for row in rows
        if row["event_type"] == "interference"
        and row["role"] == "actor"
        and row["quoted_horse_number"] == 7
        and row["span_start"] == 2
    )
    assert "지속해서" in actor["relation_span_text"]
    assert "⑧“매직사일런스”가 불편" in actor["relation_span_text"]
    assert "서로 부딪쳤" not in actor["relation_span_text"]
    source = fields[actor["source_field"]] or ""
    for prefix in ("relation_span", "actor_action_span", "victim_observation_span"):
        start = actor[f"{prefix}_start"]
        end = actor[f"{prefix}_end"]
        assert 0 <= start < end <= len(source)
    assert (
        source[actor["relation_span_start"] : actor["relation_span_end"]]
        == actor["relation_span_text"]
    )

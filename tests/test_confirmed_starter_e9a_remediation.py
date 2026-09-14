"""Regression probes for E9-A predicate and assertion scope."""

import json
from pathlib import Path

from horse_racing.analysis.confirmed_starter_e9a import Runner
from horse_racing.analysis.confirmed_starter_e9a_remediation import remediate_report
from scripts.run_confirmed_starter_e9a import POPULATION, _raw_item, _runners

RUNNERS = [
    Runner(1, "20250101", 1, 1, "H1", "가온"),
    Runner(1, "20250101", 1, 2, "H2", "나래"),
]


def _clear(text: str) -> set[tuple[str, str, int]]:
    rows = remediate_report({"judgement": text}, RUNNERS, context={})
    return {
        (row["event_type"], row["role"], row["quoted_horse_number"])
        for row in rows
        if row["certainty"] == "clear"
    }


def test_late_then_contact_does_not_attach_to_next_horse() -> None:
    rows = _clear("①“가온”은 출발이 늦은 후 ②“나래”와 부딪쳤음.")
    assert ("start_delay", "affected", 1) in rows
    assert ("start_delay", "affected", 2) not in rows


def test_relative_late_attaches_to_following_horse() -> None:
    rows = _clear("②“나래”가 안으로 들어가 출발이 좋지 못했던 ①“가온”와 부딪쳤음.")
    assert ("start_delay", "affected", 1) in rows
    assert ("start_delay", "affected", 2) not in rows


def test_joint_subjects_are_not_missed() -> None:
    rows = _clear("①“가온”, ②“나래”는 각각 출발이 늦었음.")
    assert ("start_delay", "affected", 1) in rows
    assert ("start_delay", "affected", 2) in rows


def test_blocked_scope_does_not_reach_normal_horse() -> None:
    rows = _clear("①“가온”은 정상 주행하였고, ②“나래”는 진로가 막혀 제어하였음.")
    assert ("blocked_or_controlled", "victim", 1) not in rows
    assert ("blocked_or_controlled", "victim", 2) in rows


def test_interference_positive_quote_negative_and_conditional() -> None:
    assert ("interference", "victim", 1) in _clear("①“가온”의 주행이 불편하였음.")
    assert not {
        row
        for row in _clear(
            "기수는 ‘①“가온”의 주행이 불편했던 것에 대해 ②“나래”가 안으로 진로변경했다’고 진술."
        )
        if row[0] == "interference"
    }
    assert ("interference", "victim", 1) not in _clear("①“가온”이 밀렸다는 사실은 없음.")
    assert ("interference", "victim", 1) not in _clear(
        "만약 ①“가온”이 밀렸다면 ②“나래”가 원인일 수 있음."
    )


def test_mixed_fact_and_rider_quote_preserves_fact_only() -> None:
    rows = _clear("①“가온”의 주행이 불편하였음. 기수는 ‘②“나래”의 주행이 불편했다’고 진술.")
    assert ("interference", "victim", 1) in rows
    assert ("interference", "victim", 2) not in rows


def test_three_sealed_wrong_subject_reports_and_raw_clause_offsets() -> None:
    population = json.loads(POPULATION.read_text(encoding="utf-8"))["population"]
    selected = [row for row in population if row["race_id"] in {3275, 3095, 277}]
    assert len(selected) == 3
    runners = _runners(selected)
    expected = {3275: ({4}, {3}), 3095: ({7}, {9}), 277: ({1, 5, 8}, {9})}
    for record in selected:
        path = Path(record["source_local_path"])
        item = _raw_item(path, record["race_date"].replace("-", ""), record["race_number"])
        assert item is not None
        fields = {"judgement": item.get("judgement"), "addJudgement": item.get("addJudgement")}
        rows = remediate_report(fields, runners[record["race_id"]], context={})
        clear = [row for row in rows if row["certainty"] == "clear"]
        starts = {row["horse_source_key"][3] for row in clear if row["event_type"] == "start_delay"}
        required, prohibited = expected[record["race_id"]]
        assert required <= starts
        assert not (prohibited & starts)
        for row in clear:
            source = fields[row["source_field"]] or ""
            assert source[row["clause_start"] : row["clause_end"]] == row["clause_text"]


def test_factual_victim_and_joint_actor_survive_scoped_review() -> None:
    population = json.loads(POPULATION.read_text(encoding="utf-8"))["population"]
    selected = [row for row in population if row["race_id"] in {127, 286}]
    assert len(selected) == 2
    runners = _runners(selected)
    for record in selected:
        item = _raw_item(
            Path(record["source_local_path"]),
            record["race_date"].replace("-", ""),
            record["race_number"],
        )
        assert item is not None
        rows = remediate_report(
            {"judgement": item.get("judgement"), "addJudgement": item.get("addJudgement")},
            runners[record["race_id"]],
            context={},
        )
        clear = {
            (row["event_type"], row["role"], row["horse_source_key"][3])
            for row in rows
            if row["certainty"] == "clear"
        }
        if record["race_id"] == 127:
            assert ("interference", "victim", 10) in clear
        else:
            assert ("interference", "actor", 4) in clear


def test_later_contact_clause_is_used_after_mutual_contact() -> None:
    text = "①“가온”과 ②“나래”는 서로 접촉하였고, ②“나래”가 안으로 들어가 ①“가온”과 부딪쳤음."
    rows = remediate_report({"judgement": text}, RUNNERS, context={})
    assert all(
        "안으로 들어가" in row["clause_text"]
        for row in rows
        if row["event_type"] == "contact" and row["certainty"] == "clear"
    )


def test_subject_rule_generalizes_to_renamed_renumbered_reordered_roster() -> None:
    renamed = [
        Runner(1, "20250101", 1, 4, "H4", "하늘"),
        Runner(1, "20250101", 1, 5, "H5", "바다"),
    ]
    text = "④“하늘”은 출발이 늦은 후 ⑤“바다”와 부딪쳤음."
    forward = remediate_report({"judgement": text}, renamed, context={})
    backward = remediate_report({"judgement": text}, list(reversed(renamed)), context={})
    for rows in (forward, backward):
        assert {
            row["horse_source_key"][3]
            for row in rows
            if row["event_type"] == "start_delay" and row["certainty"] == "clear"
        } == {4}


def test_identity_conflict_cross_race_addendum_and_mutual_contact_do_not_clear() -> None:
    conflict = remediate_report({"judgement": "①“다른말”은 출발이 늦었음."}, RUNNERS, context={})
    assert not any(row["certainty"] == "clear" for row in conflict)
    addendum = remediate_report(
        {"judgement": "<추가심판사항> 전날 제2경주 ①“가온”은 출발이 늦었음."},
        RUNNERS,
        context={},
    )
    assert not any(row["certainty"] == "clear" for row in addendum)
    mutual = remediate_report(
        {"judgement": "①“가온”과 ②“나래”는 서로 접촉하였음."}, RUNNERS, context={}
    )
    assert not any(row["certainty"] == "clear" for row in mutual)
    assert any(row["certainty"] == "ambiguous" for row in mutual)


def test_factual_sentence_survives_separate_conditional_sentence() -> None:
    rows = _clear("①“가온”의 주행이 불편하였음. 만약 ②“나래”가 밀렸다면 확인이 필요함.")
    assert ("interference", "victim", 1) in rows
    assert ("interference", "victim", 2) not in rows


def test_unquoted_rider_claim_is_not_independent_observation() -> None:
    rows = _clear("기수는 ①“가온”의 주행이 불편했다고 진술하였음.")
    assert ("interference", "victim", 1) not in rows

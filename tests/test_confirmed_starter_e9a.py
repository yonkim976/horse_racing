from __future__ import annotations

import json
from pathlib import Path

from horse_racing.analysis.confirmed_starter_e9a import Runner, extract_report
from scripts.run_confirmed_starter_e9a import LABELS, POPULATION, _anchor_span, _raw_item, _runners

RUNNERS = [
    Runner(1, "20250104", 1, 1, "H1", "가온"),
    Runner(1, "20250104", 1, 2, "H2", "나래"),
    Runner(1, "20250104", 1, 3, "H3", "다온"),
]
CONTEXT = {"race_id": 10, "report_id": 20, "source_sha256": "abc"}


def extract(text: str, runners: list[Runner] | None = None) -> list[dict]:
    return extract_report(
        {"judgement": text, "addJudgement": None},
        runners if runners is not None else RUNNERS,
        context=CONTEXT,
    )


def test_start_delay_group_and_directed_interference_roles() -> None:
    rows = extract(
        "● 출발 시 ①“가온”과 ②“나래”는 각각 출발이 늦었음."
        " ● 3코너 지점에서 ③“다온”의 주행이 불편했던 것에 대해, "
        "②“나래” 기승기수가 충분한 거리 없이 안으로 진로변경하였음."
    )
    starts = [row for row in rows if row["event_type"] == "start_delay"]
    assert {row["horse_source_key"][3] for row in starts} == {1, 2}
    assert {row["role"] for row in starts} == {"affected"}
    directed = [row for row in rows if row["event_type"] == "interference"]
    assert {(row["role"], row["horse_source_key"][3]) for row in directed} == {
        ("victim", 3),
        ("actor", 2),
    }
    assert all(row["span_end"] > row["span_start"] for row in rows)


def test_push_and_mutual_contact_are_not_conflated() -> None:
    rows = extract(
        "● 출발 시 ①“가온”이 바깥으로 기대며 나가 ③“다온”이 밀렸음. "
        "● ①“가온”과 ②“나래”는 서로 접촉하였음."
    )
    assert ("actor", 1) in {
        (r["role"], r["horse_source_key"][3]) for r in rows if r["event_type"] == "interference"
    }
    assert ("victim", 3) in {
        (r["role"], r["horse_source_key"][3]) for r in rows if r["event_type"] == "interference"
    }
    contact = [r for r in rows if r["event_type"] == "contact"]
    assert len(contact) == 2
    assert {r["role"] for r in contact} == {"unknown"}
    assert {r["certainty"] for r in contact} == {"ambiguous"}


def test_victim_phrase_must_not_cross_the_next_horse_marker() -> None:
    rows = extract(
        "● 출발 후 약 200m 지점에서 ①“가온”이 안으로 들어가 "
        "②“나래”의 주행이 불편했던 상황에 대해 기승기수가 진로변경하였음."
    )
    victims = [
        row["horse_source_key"][3]
        for row in rows
        if row["event_type"] == "interference" and row["role"] == "victim"
    ]
    assert victims == [2]


def test_negative_quote_and_cross_race_addendum_abstain() -> None:
    rows = extract(
        "● ①“가온”은 ②“나래”의 주행을 방해하지 않았음. "
        "● 기수는 ‘①“가온”이 출발이 늦었다’고 진술. "
        "● <추가심판사항> 전날 제2경주 ②“나래”가 밀렸음."
    )
    assert not any(r["certainty"] == "clear" for r in rows)
    assert any(r["rule"] == "cross_race_addendum" for r in rows)


def test_conditional_and_negated_start_do_not_become_clear_events() -> None:
    hypothetical = extract("● 만약 ①“가온”과 ②“나래”가 접촉하였다면 불편했을 것임.")
    assert hypothetical and all(r["certainty"] == "abstain" for r in hypothetical)
    negated = extract("● 출발 시 ①“가온”은 출발이 늦지 않았음.")
    assert not any(r["event_type"] == "start_delay" for r in negated)


def test_exact_number_name_identity_conflict_and_partial_name() -> None:
    rows = extract("● 출발 시 ①“가”는 출발이 늦었음.")
    assert rows and rows[0]["certainty"] == "abstain"
    assert rows[0]["horse_source_key"] is None
    rows = extract("● 출발 시 ②“가온”은 출발이 늦었음.")
    assert rows and rows[0]["certainty"] == "abstain"


def test_same_name_requires_number_and_number_collision_abstains() -> None:
    same_name = [RUNNERS[0], Runner(1, "20250104", 1, 2, "H2", "가온")]
    explicit = extract("● ①“가온”과 ②“가온”은 각각 출발이 늦었음.", same_name)
    assert {tuple(row["horse_source_key"]) for row in explicit} == {
        same_name[0].source_key,
        same_name[1].source_key,
    }
    unnumbered = extract("● 가온은 출발이 늦었음.", same_name)
    assert unnumbered and unnumbered[0]["horse_source_key"] is None
    collision = [RUNNERS[0], Runner(1, "20250104", 1, 1, "OTHER", "가온")]
    rows = extract("● ①“가온”은 출발이 늦었음.", collision)
    assert rows and rows[0]["certainty"] == "abstain"


def test_speculative_contact_abstains() -> None:
    rows = extract("● ①“가온”과 ②“나래”가 접촉한 것으로 추정하였음.")
    assert rows and all(row["certainty"] == "abstain" for row in rows)


def test_runner_input_order_does_not_change_evidence() -> None:
    text = "● 출발 시 ①“가온”과 ②“나래”는 각각 출발이 늦었음."
    forward = extract(text, RUNNERS)
    reverse = extract(text, list(reversed(RUNNERS)))
    assert forward == reverse


def test_sand_only_is_separate_and_requires_no_outcome() -> None:
    rows = extract("● ①“가온”은 모래를 맞자 예민하게 반응하였음.")
    assert len(rows) == 1
    assert rows[0]["event_type"] == "sand_overlap_only"
    assert rows[0]["certainty"] == "abstain"


def test_sealed_sixty_review_anchors_and_entry_identity_are_available() -> None:
    manifest = json.loads(POPULATION.read_text(encoding="utf-8"))
    labels = json.loads(LABELS.read_text(encoding="utf-8"))["labels"]
    selected = [row for row in manifest["population"] if row["sample_group"]]
    assert len(selected) == len(labels) == 60
    runners = _runners(selected)
    for row in selected:
        assert runners[row["race_id"]]
        item = _raw_item(
            Path(row["source_local_path"]), row["race_date"].replace("-", ""), row["race_number"]
        )
        assert item is not None
        fields = {"judgement": item.get("judgement"), "addJudgement": item.get("addJudgement")}
        assert _anchor_span(fields, labels[str(row["race_id"])][1]) is not None

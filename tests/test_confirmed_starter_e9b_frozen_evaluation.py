"""Synthetic-only contracts; never invoke the frozen extractor on E9-B reports."""

import pytest

from scripts.confirmed_starter_e9b_compare import compare

K1 = [1, "20250101", 1, 1, "H1"]
K2 = [1, "20250101", 1, 2, "H2"]
K3 = [1, "20250101", 1, 3, "H3"]


def doc(report_id=1):
    return {
        "report_id": report_id,
        "fields": {"judgement": "ABCDEF", "addJudgement": "GHI"},
        "roster": [{"horse_source_key": key} for key in (K1, K2, K3)],
    }


def ann(
    ident,
    key=K1,
    event_type="contact",
    role="victim",
    status="asserted",
    scope="core",
    relation=None,
):
    return {
        "annotation_id": ident,
        "horse_source_key": key,
        "event_type": event_type,
        "role": role,
        "assertion_status": status,
        "comparison_scope": scope,
        "source_field": "judgement",
        "span_start": 0,
        "span_end": 3,
        "span_text": "ABC",
        "actor_victim_relationship": relation,
    }


def ref(annotations=None, report_id=1):
    return {"report_id": report_id, "review_state": "complete", "annotations": annotations or []}


def evidence(
    ident, key=K1, event_type="contact", role="victim", report_id=1, certainty="clear", **extra
):
    return {
        "evidence_id": ident,
        "report_id": report_id,
        "horse_source_key": key,
        "event_type": event_type,
        "role": role,
        "certainty": certainty,
        "source_field": "judgement",
        "span_start": 0,
        "span_end": 3,
        "span_text": "ABC",
        **extra,
    }


def test_duplicate_evidence_collapses_but_preserves_ids():
    result = compare([doc()], [ref([ann("M1")])], [], [evidence("E1"), evidence("E2")])
    assert result["overall"]["tp"] == 1
    assert result["overall"]["clear_evidence_rows"] == 2
    assert result["units"][0]["evidence_ids"] == ["E1", "E2"]
    assert result["conservation"]["clear_tp_plus_fp_plus_unscorable"] == 1


def test_missing_extra_reports_not_inner_joined():
    with pytest.raises(ValueError, match="reference report mismatch"):
        compare([doc()], [ref(report_id=2)], [], [])
    with pytest.raises(ValueError, match="extra output reports"):
        compare([doc()], [ref()], [], [evidence("E1", report_id=2)])
    with pytest.raises(ValueError, match="duplicate"):
        compare([doc(), doc()], [ref()], [], [])


def test_positive_precedes_mask_and_quoted_is_not_positive():
    mask = [
        {
            "report_id": 1,
            "event_type": "contact",
            "horse_numbers": [1],
            "roles": ["victim"],
            "reason": "unknown",
        }
    ]
    result = compare(
        [doc()], [ref([ann("M1", status="quoted"), ann("M2")])], mask, [evidence("E1")]
    )
    assert result["overall"]["tp"] == 1
    assert result["units"][0]["reference_ids"] == ["M2"]
    quoted_only = compare([doc()], [ref([ann("M1", status="quoted")])], mask, [evidence("E1")])
    assert quoted_only["overall"]["unscorable"] == 1
    assert quoted_only["overall"]["recall"] is None


def test_mask_unscorable_and_zero_denominators():
    mask = [
        {
            "report_id": 1,
            "event_type": "contact",
            "horse_numbers": [1],
            "roles": ["victim"],
            "reason": "role unknown",
        }
    ]
    masked = compare([doc()], [ref()], mask, [evidence("E1")])
    assert masked["overall"]["unscorable"] == 1
    assert masked["overall"]["precision"] is None
    empty = compare([doc()], [ref()], [], [])
    assert empty["overall"]["precision"] is None
    assert empty["overall"]["recall"] is None
    assert empty["overall"]["f1"] is None


def test_roster_identity_and_span_contract_failures():
    result = compare([doc()], [ref()], [], [evidence("E1", key=[1, "20250101", 1, 4, "X"])])
    assert result["metrics_status"] == "blocked_by_output_contract"
    assert any(row["reason"] == "key_outside_roster" for row in result["contract_failures"])
    result = compare([doc()], [ref()], [], [evidence("E1", span_end=8)])
    assert any(row["reason"] == "invalid_clear_span" for row in result["contract_failures"])
    result = compare([doc()], [ref()], [], [evidence("E1", key=None)])
    assert any(row["reason"] == "empty_clear_identity" for row in result["contract_failures"])


def test_same_horse_multiple_events_and_multiple_victims_not_cartesian():
    relation1 = {
        "actor_source_key": K1,
        "victim_source_key": K2,
        "relation_field": "judgement",
        "relation_span_start": 0,
        "relation_span_end": 3,
        "relation_span_text": "ABC",
    }
    relation2 = {**relation1, "victim_source_key": K3}
    refs = [
        ann("M1", key=K1, role="actor", relation=relation1),
        ann("M2", key=K2, role="victim", relation=relation1),
        ann("M3", key=K1, role="actor", relation=relation2),
        ann("M4", key=K3, role="victim", relation=relation2),
        ann("M5", key=K1, event_type="interference", role="actor"),
    ]
    outputs = [
        evidence("E1", key=K1, role="actor", victim_horse_source_key=K2),
        evidence("E2", key=K1, role="actor", victim_horse_source_key=K3),
        evidence("E3", key=K1, event_type="interference", role="actor"),
    ]
    result = compare([doc()], [ref(refs)], [], outputs)
    assert result["overall"]["tp"] == 2
    assert result["overall"]["fn"] == 2
    assert result["relations"]["confirmed_reference_pairs"] == 2
    assert result["relations"]["confirmed_pairs_recovered"] == 2
    assert len(result["relations"]["rows"]) == 2

"""Contract tests for metadata-only sampling and blind source rendering."""

import json
import random

from scripts.build_confirmed_starter_e9b_blind_package import (
    SEED,
    _annotation_schema,
    _identity_issues,
    _raw_item,
    render_markdown,
    select_records,
)


def _metadata(n: int = 100) -> list[dict]:
    return [
        {
            "race_id": n - index,
            "report_id": index + 1,
            "sample_group": "random" if index < 60 else None,
            "race_date": "2025-01-01",
            "race_number": 1,
            "source_sha256": f"hash{index}",
            "source_local_path": f"raw{index}.json",
        }
        for index in range(n)
    ]


def test_seeded_sample_uses_sorted_metadata_and_excludes_old_sixty() -> None:
    rows = _metadata()
    excluded, candidates, selected = select_records(rows, set(range(1, 61)))
    assert len(excluded) == 60
    assert len(candidates) == 40
    assert all(row["report_id"] > 60 for row in selected)
    assert selected == random.Random(SEED).sample(candidates, 30)
    assert candidates == sorted(candidates, key=lambda row: (row["race_id"], row["report_id"]))


def test_other_recorded_detailed_exposure_is_excluded_with_reason() -> None:
    rows = _metadata()
    excluded, candidates, selected = select_records(rows, set(range(1, 61)) | {61})
    assert any(
        row == {"report_id": 61, "reason": "other_recorded_e9a_detailed_exposure"}
        for row in excluded
    )
    assert len(candidates) == 39
    assert all(row["report_id"] != 61 for row in selected)


def test_raw_item_uses_exact_report_identity(tmp_path) -> None:
    path = tmp_path / "raw.json"
    item = {
        "rcDate": "20250101",
        "rcNo": 2,
        "meet": "서울",
        "judgement": "  원문, 그대로.\n",
        "addJudgement": None,
    }
    path.write_text(json.dumps({"response": {"body": {"items": {"item": [item]}}}}))
    assert _raw_item(path, "2025-01-01", 2) == item
    assert _raw_item(path, "2025-01-01", 3) is None


def test_roster_collision_does_not_imply_replacement() -> None:
    clean = [
        {"horse_number": 1, "horse_source_id": "H1"},
        {"horse_number": 2, "horse_source_id": "H2"},
    ]
    assert _identity_issues(clean) == []
    assert "duplicate_horse_number" in _identity_issues(
        clean + [{"horse_number": 1, "horse_source_id": "H3"}]
    )


def test_markdown_contains_unmodified_text_and_no_prediction_fields() -> None:
    raw = "  첫 줄, 원문 그대로.\n둘째 줄 `abc`  "
    doc = {
        "report_id": 1,
        "race_id": 2,
        "race_date": "2025-01-01",
        "race_number": 3,
        "source_file": "raw.json",
        "source_sha256_expected": "hash",
        "source_sha256_observed": "hash",
        "coverage_status": "ready_for_blind_reading",
        "coverage_issues": [],
        "roster": [],
        "fields": {"judgement": raw, "addJudgement": None},
    }
    rendered = render_markdown([doc])
    assert raw in rendered
    assert "extractor_output" not in rendered
    assert "predicted_label" not in rendered


def test_annotation_is_only_a_schema_not_a_filled_no_event_label() -> None:
    schema = _annotation_schema()
    assert schema["properties"]["review_state"]["enum"] == ["unread", "complete", "unreadable"]
    assert "confirmed_absent" in schema["properties"]["event_presence"]["enum"]
    assert "annotations" in schema["properties"]
    assert "documents" not in schema

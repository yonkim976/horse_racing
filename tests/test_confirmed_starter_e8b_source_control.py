from __future__ import annotations

import json
from pathlib import Path

from horse_racing.collectors.kra_api import ENTRY_SHEET_ENDPOINT
from horse_racing.parsers.entry_sheet import parse_entry_sheet_page
from horse_racing.parsers.race_day import RacePlanItem, parse_items
from scripts.run_confirmed_starter_e8b_source_control import (
    DATE,
    EXISTING,
    EXPECTED_EXISTING_SHA,
    SOURCES,
    _sha,
    compare_first_page,
)


def test_fixed_control_evidence_is_pre_may_31_nonempty_and_hashed() -> None:
    assert DATE == "20260517"
    for endpoint, path in EXISTING.items():
        assert path.is_file()
        raw = path.read_bytes()
        assert _sha(raw) == EXPECTED_EXISTING_SHA[endpoint]
        payload = json.loads(raw)
        items = (
            parse_entry_sheet_page(payload).items
            if endpoint == ENTRY_SHEET_ENDPOINT
            else parse_items(payload, RacePlanItem)
        )
        assert items
        assert all(item.race_date.strftime("%Y%m%d") == DATE for item in items)


def test_source_snapshot_targets_are_relative_and_present() -> None:
    assert all(not path.is_absolute() and path.is_file() for path in SOURCES)


def test_first_page_comparison_never_certifies_complete_dataset() -> None:
    payload = json.loads((Path(__file__).parent / "fixtures/entry_sheet_page.json").read_text())
    items = parse_entry_sheet_page(payload).items
    result = compare_first_page(
        ENTRY_SHEET_ENDPOINT,
        items,
        items[:1],
        new_meta={"totalCount": 20, "pageNo": 1, "numOfRows": 2},
    )
    assert result["first_page_nonempty"]
    assert result["complete_dataset"] == "not_assessed_first_page_only"
    assert len(result["removed_keys"]) == 1
    assert not result["T_minus_30_claim"]

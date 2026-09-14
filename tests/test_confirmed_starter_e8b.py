from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from horse_racing.analysis.confirmed_starter_e8b import (
    BudgetTransport,
    CaptureError,
    CaptureStore,
    PilotCapture,
    audit_batch,
)
from horse_racing.collectors.kra_api import ENTRY_SHEET_ENDPOINT

FIXTURE = Path(__file__).parent / "fixtures/entry_sheet_page.json"


def payload(*, page: int = 1, total: int = 2, items: list[dict] | None = None) -> dict:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    body = value["response"]["body"]
    body["pageNo"] = str(page)
    body["numOfRows"] = "2"
    body["totalCount"] = str(total)
    if items is not None:
        body["items"]["item"] = items
    return value


def make_pilot(
    tmp_path: Path, responses: list[httpx.Response], *, limit: int = 12, clock=None
) -> tuple[PilotCapture, BudgetTransport, CaptureStore]:
    calls = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/B551015/API26_2/entrySheet_2"
        return next(calls)

    store = CaptureStore(tmp_path / "capture", clock=clock)
    transport = BudgetTransport(httpx.MockTransport(handler), limit=limit)
    pilot = PilotCapture(
        store,
        service_key="secret-test",
        base_url="https://example.test/B551015",
        transport=transport,
    )
    return pilot, transport, store


def public(page: int = 1) -> dict:
    return {"meet": 1, "rc_date": "20260822", "_type": "json", "pageNo": page, "numOfRows": 2}


def test_complete_pages_and_source_keys(tmp_path: Path) -> None:
    rows = payload()["response"]["body"]["items"]["item"]
    third = {**rows[0], "chulNo": "3", "hrNo": "5003"}
    pilot, transport, store = make_pilot(
        tmp_path,
        [
            httpx.Response(200, json=payload(total=3, items=rows)),
            httpx.Response(200, json=payload(page=2, total=3, items=[third])),
        ],
    )
    batch = pilot.batch(ENTRY_SHEET_ENDPOINT, "20260822", batch_id="one", page_size=2)
    assert batch["complete"]
    assert batch["actual_items_day"] == 3
    assert batch["race_counts"] == {"1": 3}
    assert len(batch["source_keys"][0]) == 5
    assert transport.count == 2
    assert store.journal.exists()
    pilot.close()


def test_missing_total_count_preserves_raw(tmp_path: Path) -> None:
    value = payload()
    del value["response"]["body"]["totalCount"]
    body = json.dumps(value).encode()
    pilot, transport, store = make_pilot(tmp_path, [httpx.Response(200, content=body)])
    result = pilot.page(ENTRY_SHEET_ENDPOINT, public(), batch="bad")
    assert result["failure"] == "CaptureError"
    assert (store.raw / result["body_sha256"]).read_bytes() == body
    assert transport.count == 1
    pilot.close()


def test_parser_failure_preserves_raw(tmp_path: Path) -> None:
    value = payload()
    value["response"]["body"]["items"]["item"][0]["rcDate"] = "bad"
    body = json.dumps(value).encode()
    pilot, _, store = make_pilot(tmp_path, [httpx.Response(200, content=body)])
    result = pilot.page(ENTRY_SHEET_ENDPOINT, public(), batch="bad")
    assert result["failure"] == "ValidationError"
    assert (store.raw / result["body_sha256"]).read_bytes() == body
    pilot.close()


def test_budget_counts_retry_and_redirect_not_followed(tmp_path: Path) -> None:
    pilot, transport, _ = make_pilot(
        tmp_path, [httpx.Response(503), httpx.Response(200, json=payload())], limit=2
    )
    result = pilot.page(ENTRY_SHEET_ENDPOINT, public(), batch="retry")
    assert result["failure"] is None and transport.count == 2
    with pytest.raises(CaptureError, match="budget"):
        pilot.page(ENTRY_SHEET_ENDPOINT, public(), batch="extra")
    pilot.close()
    second, count, _ = make_pilot(
        tmp_path / "other",
        [httpx.Response(302, headers={"location": "https://example.test/other"})],
    )
    redirect = second.page(ENTRY_SHEET_ENDPOINT, public(), batch="redirect")
    assert redirect["failure"] == "CaptureError" and count.count == 1
    second.close()


def test_clock_regression_and_ordered_timestamps(tmp_path: Path) -> None:
    samples = iter([100, 101, 102, 103])
    pilot, _, _ = make_pilot(
        tmp_path, [httpx.Response(200, json=payload())], clock=lambda: next(samples)
    )
    result = pilot.page(ENTRY_SHEET_ENDPOINT, public(), batch="clock")
    assert [
        result[k]
        for k in ("requested_at_ms", "received_at_ms", "parsed_at_ms", "commit_completed_at_ms")
    ] == [100, 101, 102, 103]
    pilot.close()
    bad_samples = iter([100, 99])
    bad, _, _ = make_pilot(
        tmp_path / "bad", [httpx.Response(200, json=payload())], clock=lambda: next(bad_samples)
    )
    with pytest.raises(CaptureError, match="clock regressed"):
        bad.page(ENTRY_SHEET_ENDPOINT, public(), batch="bad")
    bad.close()


def test_transport_failure_is_audited_without_response_metadata(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated")

    store = CaptureStore(tmp_path / "capture")
    transport = BudgetTransport(httpx.MockTransport(handler), limit=2)
    pilot = PilotCapture(
        store,
        service_key="secret-test",
        base_url="https://example.test/B551015",
        transport=transport,
    )
    batch = pilot.batch(ENTRY_SHEET_ENDPOINT, "20260822", batch_id="network", page_size=2)
    assert not batch["complete"]
    assert "page_failure" in batch["issues"]
    assert transport.count == 2
    pilot.close()


def test_audit_rejects_missing_duplicate_page_and_identity_conflict(tmp_path: Path) -> None:
    rows = payload()["response"]["body"]["items"]["item"]
    pilot, _, _ = make_pilot(tmp_path, [httpx.Response(200, json=payload(items=rows[:1]))])
    page = pilot.page(ENTRY_SHEET_ENDPOINT, public(), batch="x")
    missing = audit_batch(
        [page], endpoint=ENTRY_SHEET_ENDPOINT, race_date="20260822", expected_pages=2, batch_id="x"
    )
    assert "missing_or_duplicate_pages" in missing["issues"]
    duplicate = audit_batch(
        [page, page],
        endpoint=ENTRY_SHEET_ENDPOINT,
        race_date="20260822",
        expected_pages=2,
        batch_id="x",
    )
    assert "missing_or_duplicate_pages" in duplicate["issues"]
    assert "duplicate_source_keys" in duplicate["issues"]
    conflict = {
        **page,
        "items": [page["items"][0], page["items"][0].model_copy(update={"horse_id": "different"})],
        "meta": {**page["meta"], "actualItems": 2},
    }
    audited = audit_batch(
        [conflict],
        endpoint=ENTRY_SHEET_ENDPOINT,
        race_date="20260822",
        expected_pages=1,
        batch_id="x",
    )
    assert "horse_number_identity_conflict" in audited["issues"]
    pilot.close()

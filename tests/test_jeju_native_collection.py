"""Regression checks for native-only collection and ignored API date filters."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from scripts import collect_jeju_native_health_weight as collector


def _fake_client(monkeypatch: pytest.MonkeyPatch, rows: list[dict]) -> None:
    payload = {
        "response": {
            "body": {
                "items": {"item": rows},
                "totalCount": len(rows),
            }
        }
    }
    page = SimpleNamespace(
        payload=payload,
        body=json.dumps(payload).encode(),
        status_code=200,
        retrieved_at_ms=1,
        source_url="https://example.test/without-key",
    )

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def iter_pages(self, **_kwargs):
            yield page

    monkeypatch.setattr(
        collector,
        "get_settings",
        lambda: SimpleNamespace(
            data_go_kr_service_key=SecretStr("fake"), kra_api_base_url="https://example.test"
        ),
    )
    monkeypatch.setattr(collector, "KraApiClient", FakeClient)


def test_weight_query_rejects_server_ignoring_requested_month(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _fake_client(
        monkeypatch,
        [{"meet": "제주", "hrNo": 3001, "rcDate": 20260821, "rcNo": 4, "wgHr": 271}],
    )
    with pytest.raises(ValueError, match="ignored requested weight period"):
        collector.collect_period(
            kind="weight",
            period="200207",
            ids={"3001"},
            race_horse={(20020728, 4, "3001")},
            output_dir=tmp_path,
        )
    assert list(tmp_path.iterdir()) == []


def test_weight_archive_keeps_only_confirmed_native_measured_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _fake_client(
        monkeypatch,
        [
            {"meet": "제주", "hrNo": 3001, "rcDate": 20020728, "rcNo": 4, "wgHr": 271},
            {"meet": "제주", "hrNo": 1001, "rcDate": 20020728, "rcNo": 4, "wgHr": 300},
            {"meet": "제주", "hrNo": 3001, "rcDate": 20020729, "rcNo": 4, "wgHr": 0},
        ],
    )
    result = collector.collect_period(
        kind="weight",
        period="200207",
        ids={"3001"},
        race_horse={(20020728, 4, "3001")},
        output_dir=tmp_path,
    )
    assert result["native_rows"] == 1
    rows = [
        json.loads(line) for line in (tmp_path / "weight_200207.jsonl").read_text().splitlines()
    ]
    assert rows == [{"meet": "제주", "hrNo": 3001, "rcDate": 20020728, "rcNo": 4, "wgHr": 271}]

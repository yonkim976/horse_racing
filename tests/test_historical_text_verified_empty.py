from __future__ import annotations

from datetime import date

import httpx

from horse_racing.collectors.kra_text import KraTextFile
from scripts.collect_historical_text_verified_empty import VerifiedEmptyKraTextClient


def _file() -> KraTextFile:
    return KraTextFile(
        meet=2,
        file_type="dacom12",
        remote_path="chollian/jeju/sokbo/horse-weight/20060318dacom12.rpt",
        filename="20060318dacom12.rpt",
        file_date=date(2006, 3, 18),
        list_page=190,
    )


def test_persistent_empty_requires_three_reads() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"")

    with VerifiedEmptyKraTextClient(transport=httpx.MockTransport(handler)) as client:
        report = client.fetch_file(_file())

    assert calls == 3
    assert report.status_code == 200
    assert report.body == b""


def test_transient_empty_is_recovered() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"confirmed" if calls == 2 else b"")

    with VerifiedEmptyKraTextClient(transport=httpx.MockTransport(handler)) as client:
        report = client.fetch_file(_file())

    assert calls == 2
    assert report.body == b"confirmed"

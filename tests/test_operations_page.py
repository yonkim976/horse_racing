"""Offline checks for the standalone operations guide."""

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "operations_page", ROOT / "scripts/build_operations_page.py"
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_document_registry_and_job_mapping():
    data = builder.payload()
    assert len(data["jobs"]) == 12
    assert len({job["id"] for job in data["jobs"]}) == 12
    assert sum(job["place"] == "local" for job in data["jobs"]) == 10
    assert sum(job["place"] == "cloud" for job in data["jobs"]) == 2
    assert len(data["documents"]) == 9
    assert len(data["pending"]) == 6
    assert data["asOf"] == "2026-10-12"
    used = {api for job in data["jobs"] for api in job["apis"]}
    assert used == set(builder.API)
    for doc in data["documents"]:
        content = (ROOT / "docs" / doc["id"]).read_bytes()
        assert doc["sha256"] == hashlib.sha256(content).hexdigest()
    for job in data["jobs"]:
        assert job["manual"] and job["check"] and job["evidence"]


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [
        ("水", []),
        ("수요일 15:10·16:10", [("15:10", [2], False), ("16:10", [2], False)]),
        ("목요일 15:10·금요일 09:10", [("15:10", [3], False), ("09:10", [4], False)]),
        ("매일 09:00·20:30", [("09:00", list(range(7)), False), ("20:30", list(range(7)), False)]),
        (
            "수요일 17:40, 주간 마지막 경주일 18:40",
            [("17:40", [2], False), ("18:40", list(range(7)), True)],
        ),
    ],
)
def test_schedule_semantics(schedule, expected):
    if not expected:
        with pytest.raises(ValueError, match="schedule_could_not_be_parsed"):
            builder.schedule_events(schedule)
        return
    actual = builder.schedule_events(schedule)
    assert actual["kind"] == "calendar"
    assert [
        (item["time"], item["days"], item["conditional"]) for item in actual["events"]
    ] == expected


@pytest.mark.parametrize("minutes", [2, 15])
def test_intervals_are_not_fixed_calendar_entries(minutes):
    assert builder.schedule_events(f"약 {minutes}분 간격") == {
        "kind": "interval",
        "minutes": minutes,
        "events": [],
    }


def test_markdown_is_data_and_script_json_cannot_break_out():
    source = (
        "# 제목\n\n<script>alert(1)</script>\n\n```sh\n$(bad)\n```\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |"
    )
    blocks = builder.markdown_blocks(source)
    assert blocks[1] == {"type": "paragraph", "text": "<script>alert(1)</script>"}
    assert blocks[2] == {"type": "code", "text": "$(bad)"}
    assert blocks[3]["rows"] == [["1", "2"]]
    encoded = builder.safe_json({"text": "</script><script>alert(1)</script>&\u2028\u2029"})
    assert "<" not in encoded and ">" not in encoded and "&" not in encoded
    assert json.loads(encoded)["text"].startswith("</script>")
    with pytest.raises(ValueError, match="unclosed_markdown_fence"):
        builder.markdown_blocks("```\nunfinished")


@pytest.mark.parametrize(
    "secret",
    [
        "https://discord.com/api/webhooks/1234567890/fictional_test_token",
        "postgresql://user:fictional_test_password@localhost/test",
        "sbp_" + "f" * 30,
        "eyJ" + "x" * 20 + "." + "y" * 20 + "." + "z" * 20,
    ],
)
def test_credentials_rejected_without_echoing(secret):
    with pytest.raises(ValueError) as error:
        builder.validate_public_text(secret)
    assert secret not in str(error.value)


def test_generated_page_matches_current_document_hashes():
    html = (ROOT / "operations/index.html").read_text()
    match = re.search(
        r'<script id="operations-data" type="application/json">(.*?)</script>', html, re.S
    )
    assert match
    data = json.loads(match[1])
    assert data["documents"] == builder.payload()["documents"]
    assert data["jobs"] == builder.payload()["jobs"]
    assert "__OPERATIONS_DATA__" not in html
    assert "connect-src 'none'" in html
    assert not re.search(r'<(?:script|link|img)\b[^>]*(?:src|href)="https?://', html)
    builder.validate_public_text(html)
    for dangerous_api in ("innerHTML", "eval(", "fetch(", "XMLHttpRequest", "WebSocket("):
        assert dangerous_api not in html

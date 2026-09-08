from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from test_race_day import migrated_session

from horse_racing.collectors.kra_text import KraTextClient, KraTextError
from horse_racing.db.models import IngestionRun, SourceDocument
from horse_racing.services.text_archive import download_text_archive


def _list_html(remote_path: str, filename: str) -> bytes:
    return (f'<a href="/dbdata/fileDownLoad.do?fn={remote_path}&meet=1">{filename}</a>').encode(
        "cp949"
    )


def test_download_text_archive_writes_manifest_and_resumes(tmp_path: Path) -> None:
    filename = "20260822dacom11.rpt"
    remote_path = f"chollian/seoul/jungbo/rcresult/{filename}"
    report = "경마성적표 테스트\r\n".encode("cp949")
    calls = {"list": 0, "file": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("textDataList.do"):
            calls["list"] += 1
            if b"pageIndex=1" in request.content:
                return httpx.Response(200, content=_list_html(remote_path, filename))
            return httpx.Response(200, content=b"<html></html>")
        if request.url.path.endswith("fileDownLoad.do"):
            calls["file"] += 1
            return httpx.Response(
                200,
                content=report,
                headers={"content-type": "application/octet-stream"},
            )
        return httpx.Response(404)

    session_factory = migrated_session(tmp_path)
    raw_dir = tmp_path / "raw"
    with (
        KraTextClient(transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        first = download_text_archive(
            session,
            client,
            file_type="dacom11",
            code_name="경마성적표",
            meets=[1],
            raw_data_dir=raw_dir,
            start_date=date(2026, 8, 22),
            end_date=date(2026, 8, 22),
            delay_seconds=0,
        )
        second = download_text_archive(
            session,
            client,
            file_type="dacom11",
            code_name="경마성적표",
            meets=[1],
            raw_data_dir=raw_dir,
            start_date=date(2026, 8, 22),
            end_date=date(2026, 8, 22),
            delay_seconds=0,
        )

        assert first.files_discovered == 1
        assert first.files_fetched == 1
        assert first.files_written == 1
        assert second.files_discovered == 1
        assert second.files_fetched == 0
        assert second.files_skipped == 1
        assert calls["file"] == 1
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 1

        lines = [
            json.loads(line)
            for line in first.manifest_path.read_text(encoding="utf-8").splitlines()
        ]
        assert [event["status"] for event in lines] == [
            "discovered",
            "downloaded",
            "discovered",
            "skipped_existing",
        ]
        downloaded = lines[1]
        assert downloaded["sha256"]
        assert Path(downloaded["local_path"]).read_bytes() == report


def test_download_text_archive_records_discovery_before_failure(tmp_path: Path) -> None:
    filename = "20260822dacom11.rpt"
    remote_path = f"chollian/seoul/jungbo/rcresult/{filename}"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("textDataList.do"):
            return httpx.Response(200, content=_list_html(remote_path, filename))
        return httpx.Response(404, request=request)

    session_factory = migrated_session(tmp_path)
    with (
        KraTextClient(transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        with pytest.raises(KraTextError, match="HTTP 404"):
            download_text_archive(
                session,
                client,
                file_type="dacom11",
                code_name="경마성적표",
                meets=[1],
                raw_data_dir=tmp_path / "raw",
                start_date=date(2026, 8, 22),
                end_date=date(2026, 8, 22),
                delay_seconds=0,
            )

        run = session.scalar(select(IngestionRun))
        assert run is not None
        assert run.status == "failed"
        manifest = tmp_path / "raw/kra_text/_manifests/dacom11/manifest.jsonl"
        statuses = [
            json.loads(line)["status"] for line in manifest.read_text(encoding="utf-8").splitlines()
        ]
        assert statuses == ["discovered", "failed"]


def test_download_text_archive_recovers_existing_file_provenance(tmp_path: Path) -> None:
    filename = "20260822dacom11.rpt"
    remote_path = f"chollian/seoul/jungbo/rcresult/{filename}"
    report = "이미 저장된 경마성적표\r\n".encode("cp949")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("textDataList.do"):
            if b"pageIndex=1" in request.content:
                return httpx.Response(200, content=_list_html(remote_path, filename))
            return httpx.Response(200, content=b"<html></html>")
        raise AssertionError("기존 파일은 다시 다운로드하면 안 됩니다.")

    raw_dir = tmp_path / "raw"
    target = (
        raw_dir
        / "kra_text/dacom11/meet=1/year=2026/month=08/day=22"
        / filename
    )
    target.parent.mkdir(parents=True)
    target.write_bytes(report)
    session_factory = migrated_session(tmp_path)
    with (
        KraTextClient(transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        summary = download_text_archive(
            session,
            client,
            file_type="dacom11",
            code_name="경마성적표",
            meets=[1],
            raw_data_dir=raw_dir,
            start_date=date(2026, 8, 22),
            end_date=date(2026, 8, 22),
            delay_seconds=0,
        )

        assert summary.files_fetched == 0
        assert summary.files_skipped == 1
        document = session.scalar(select(SourceDocument))
        assert document is not None
        assert document.local_path == str(target)
        assert json.loads(document.request_params_json)["recovered_existing"] is True


def test_list_files_keeps_undated_reference_file() -> None:
    remote_path = "chollian/seoul/jungbo/basic/db7.rpt"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_list_html(remote_path, "db7.rpt"))

    with KraTextClient(transport=httpx.MockTransport(handler)) as client:
        files = client.list_files(
            meet=1,
            file_type="db7",
            code_name="마명변경내역",
            page_index=1,
        )

    assert len(files) == 1
    assert files[0].filename == "db7.rpt"
    assert files[0].file_date is None

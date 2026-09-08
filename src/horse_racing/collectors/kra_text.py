from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

KRA_TEXT_BASE_URL = "https://race.kra.co.kr"
RUNNING_TRIAL_FILE_TYPE = "dacom23"
RUNNING_TRIAL_CODE_NAME = "주행심사결과"
TEXT_FILE_TYPES: dict[str, str] = {
    "dacom01": "출전표",
    "dacom11": "경마성적표",
    "dacom12": "출전마체중안내",
    "dacom13": "기수변경말취소주로상태",
    "dacom21": "말성적조회",
    "dacom22": "기수성적조회",
    "dacom23": RUNNING_TRIAL_CODE_NAME,
    "dacom52": "승급말현황",
    "dacom55": "일별조교현황",
    "dacom71": "출전마진료및장구현황",
    "dacom72": "말진료현황",
    "db1": "경주마정보",
    "db2": "기수정보",
    "db3": "조교사정보",
    "db4": "출발심사결과",
    "db5": "출발조교현황",
    "db6": "마주정보",
    "db7": "마명변경내역",
}


class KraTextError(RuntimeError):
    """Raised when the KRA Text archive cannot be listed or downloaded."""


class KraTextTransientError(KraTextError):
    """Raised for a retryable KRA Text transport or server failure."""


@dataclass(frozen=True, slots=True)
class KraTextFile:
    meet: int
    file_type: str
    remote_path: str
    filename: str
    file_date: date | None
    list_page: int
    listed_size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class FetchedTextReport:
    file: KraTextFile
    source_url: str
    requested_at_ms: int
    retrieved_at_ms: int
    status_code: int
    content_type: str | None
    body: bytes


class KraTextClient:
    def __init__(
        self,
        *,
        base_url: str = KRA_TEXT_BASE_URL,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": "horse-racing-data-platform/0.1"},
        )

    def __enter__(self) -> KraTextClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def iter_running_trial_files(
        self,
        *,
        meet: int,
        start_date: date,
        end_date: date,
        max_pages: int = 500,
    ) -> Iterator[KraTextFile]:
        if meet not in {1, 2, 3}:
            raise ValueError("meet는 1(서울), 2(제주), 3(부산경남) 중 하나여야 합니다.")
        if end_date < start_date:
            raise ValueError("종료일이 시작일보다 앞설 수 없습니다.")

        yield from self.iter_files(
            meet=meet,
            file_type=RUNNING_TRIAL_FILE_TYPE,
            code_name=RUNNING_TRIAL_CODE_NAME,
            start_date=start_date,
            end_date=end_date,
            max_pages=max_pages,
        )

    def iter_files(
        self,
        *,
        meet: int,
        file_type: str,
        code_name: str,
        start_date: date | None = None,
        end_date: date | None = None,
        max_pages: int = 500,
    ) -> Iterator[KraTextFile]:
        """Iterate one Text archive category, newest first, with duplicate removal."""
        if meet not in {1, 2, 3}:
            raise ValueError("meet는 1(서울), 2(제주), 3(부산경남) 중 하나여야 합니다.")
        if not re.fullmatch(r"[a-zA-Z0-9_]+", file_type):
            raise ValueError("file_type 형식이 올바르지 않습니다.")
        if not code_name.strip():
            raise ValueError("code_name이 비어 있습니다.")
        if max_pages < 1:
            raise ValueError("max_pages는 1 이상이어야 합니다.")
        if start_date is not None and end_date is not None and end_date < start_date:
            raise ValueError("종료일이 시작일보다 앞설 수 없습니다.")

        seen: set[str] = set()
        for page_index in range(1, max_pages + 1):
            files = self.list_files(
                meet=meet,
                file_type=file_type,
                code_name=code_name,
                page_index=page_index,
            )
            if not files:
                return
            page_dates = [file.file_date for file in files if file.file_date is not None]
            for file in files:
                if file.remote_path in seen:
                    continue
                seen.add(file.remote_path)
                if start_date is not None and (
                    file.file_date is None or file.file_date < start_date
                ):
                    continue
                if end_date is not None and (file.file_date is None or file.file_date > end_date):
                    continue
                yield file
            if start_date is not None and page_dates and min(page_dates) < start_date:
                return
        raise KraTextError(f"KRA Text 목록이 {max_pages}페이지를 초과했습니다.")

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, KraTextTransientError)),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def list_files(
        self,
        *,
        meet: int,
        file_type: str,
        code_name: str,
        page_index: int,
    ) -> list[KraTextFile]:
        try:
            response = self._client.post(
                "/dbdata/textDataList.do",
                data={
                    "Act": "12",
                    "Sub": "1",
                    "meet": str(meet),
                    "fileType": file_type,
                    "codeName": code_name,
                    "pageIndex": str(page_index),
                },
            )
        except httpx.TransportError as exc:
            raise KraTextTransientError("KRA Text 목록 연결에 실패했습니다.") from exc
        _raise_for_status(response, context="목록")

        html = response.content.decode("cp949", errors="replace")
        soup = BeautifulSoup(html, "lxml")
        files: list[KraTextFile] = []
        for anchor in soup.select('a[href*="fileDownLoad.do"]'):
            href = str(anchor.get("href", ""))
            query = parse_qs(urlparse(href).query)
            remote_path = query.get("fn", [""])[0]
            if not remote_path:
                continue
            filename = PurePosixPath(remote_path).name
            report_match = re.match(
                r"(?P<date>\d{8})(?P<type>[a-zA-Z0-9_]+)\.rpt$", filename
            )
            if report_match is not None and report_match.group("type") != file_type:
                continue
            date_match = re.match(r"(?P<date>\d{8})", filename)
            file_date = (
                _filename_date(date_match.group("date")) if date_match is not None else None
            )
            files.append(
                KraTextFile(
                    meet=meet,
                    file_type=file_type,
                    remote_path=remote_path,
                    filename=filename,
                    file_date=file_date,
                    list_page=page_index,
                    listed_size_bytes=_listed_size_bytes(anchor.parent.get_text(" ", strip=True)),
                )
            )
        return files

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, KraTextTransientError)),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def fetch_file(self, file: KraTextFile) -> FetchedTextReport:
        requested_at_ms = _now_ms()
        try:
            response = self._client.get(
                "/dbdata/fileDownLoad.do",
                params={"fn": file.remote_path, "meet": file.meet},
            )
        except httpx.TransportError as exc:
            raise KraTextTransientError("KRA Text 파일 연결에 실패했습니다.") from exc
        retrieved_at_ms = _now_ms()
        _raise_for_status(response, context=file.filename)
        if not response.content:
            raise KraTextError(f"KRA Text 파일이 비어 있습니다: {file.filename}")
        return FetchedTextReport(
            file=file,
            source_url=str(response.request.url),
            requested_at_ms=requested_at_ms,
            retrieved_at_ms=retrieved_at_ms,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            body=response.content,
        )


def _raise_for_status(response: httpx.Response, *, context: str) -> None:
    if response.status_code == 429 or response.status_code >= 500:
        raise KraTextTransientError(f"KRA Text {context} 서버 오류: HTTP {response.status_code}")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise KraTextError(f"KRA Text {context} 요청 실패: HTTP {response.status_code}") from exc


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _filename_date(value: str) -> date | None:
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")
    except ValueError:
        return None


def _listed_size_bytes(text: str) -> int | None:
    match = re.search(r"([\d,]+(?:\.\d+)?)\s*(bytes?|[KMG]B)\b", text, re.IGNORECASE)
    if match is None:
        return None
    amount = float(match.group(1).replace(",", ""))
    unit = match.group(2).lower()
    multiplier = {"b": 1, "byte": 1, "bytes": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3}
    return int(amount * multiplier[unit])

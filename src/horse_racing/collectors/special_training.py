from __future__ import annotations

import math
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from horse_racing.collectors.kra_api import (
    KraApiError,
    KraApiRateLimitError,
    KraApiTransientError,
)

SWIM_TRAINING_ENDPOINT = "/API216/SwimTr"
SWIM_TRAINING_OPERATION = "SwimTr"
HILL_TRAINING_ENDPOINT = "/hilldriving/gethilldriving"
HILL_TRAINING_OPERATION = "gethilldriving"


@dataclass(frozen=True, slots=True)
class FetchedXmlPage:
    endpoint: str
    operation: str
    source_url: str
    public_params: Mapping[str, str | int]
    requested_at_ms: int
    retrieved_at_ms: int
    status_code: int
    content_type: str | None
    body: bytes
    items: tuple[dict[str, str], ...]
    total_count: int


class KraXmlApiClient:
    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = "https://apis.data.go.kr/B551015",
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not service_key.strip():
            raise ValueError("공공데이터포털 서비스키가 비어 있습니다.")
        self._service_key = service_key
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=True,
        )

    def __enter__(self) -> KraXmlApiClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def iter_pages(
        self,
        *,
        endpoint: str,
        operation: str,
        public_params: Mapping[str, str | int],
        page_size: int = 20_000,
        service_key_parameter: str = "ServiceKey",
    ) -> Iterator[FetchedXmlPage]:
        if page_size < 1 or page_size > 20_000:
            raise ValueError("page_size는 1 이상 20,000 이하여야 합니다.")

        page_no = 1
        while True:
            page_params = {
                **public_params,
                "pageNo": page_no,
                "numOfRows": page_size,
            }
            fetched = self._fetch_xml(
                endpoint,
                operation,
                page_params,
                service_key_parameter=service_key_parameter,
            )
            yield fetched
            total_pages = max(1, math.ceil(fetched.total_count / page_size))
            if page_no >= total_pages:
                return
            page_no += 1

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, KraApiTransientError)),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _fetch_xml(
        self,
        endpoint: str,
        operation: str,
        public_params: Mapping[str, str | int],
        *,
        service_key_parameter: str,
    ) -> FetchedXmlPage:
        requested_at_ms = _now_ms()
        params = {**public_params, service_key_parameter: self._service_key}
        try:
            response = self._client.get(endpoint.lstrip("/"), params=params)
        except httpx.TransportError as exc:
            raise KraApiTransientError("KRA XML API 네트워크 연결에 실패했습니다.") from exc
        retrieved_at_ms = _now_ms()

        if response.status_code == 429:
            raise KraApiRateLimitError("KRA API 일일 호출 제한에 도달했습니다.")
        if response.status_code >= 500:
            raise KraApiTransientError(f"KRA API 서버 오류: HTTP {response.status_code}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise KraApiError(f"KRA API 요청 실패: HTTP {response.status_code}") from exc

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise KraApiError("KRA API가 유효한 XML을 반환하지 않았습니다.") from exc
        result_code = (root.findtext(".//resultCode") or "").strip()
        if result_code not in {"00", "0000"}:
            result_message = (root.findtext(".//resultMsg") or "알 수 없는 오류").strip()
            raise KraApiError(f"KRA API 오류 {result_code}: {result_message}")

        items = tuple(
            {child.tag: (child.text or "").strip() for child in item}
            for item in root.findall(".//item")
        )
        total_count = _as_int(root.findtext(".//totalCount"), default=len(items))
        redacted_url = str(
            httpx.URL(
                str(response.request.url).split("?")[0],
                params=public_params,
            )
        )
        return FetchedXmlPage(
            endpoint=endpoint,
            operation=operation,
            source_url=redacted_url,
            public_params=dict(public_params),
            requested_at_ms=requested_at_ms,
            retrieved_at_ms=retrieved_at_ms,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            body=response.content,
            items=items,
            total_count=total_count,
        )


def _as_int(value: str | None, *, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _now_ms() -> int:
    return time.time_ns() // 1_000_000

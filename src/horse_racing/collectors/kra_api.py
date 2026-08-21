from __future__ import annotations

import math
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

ENTRY_SHEET_ENDPOINT = "/API26_2/entrySheet_2"
ENTRY_SHEET_OPERATION = "entrySheet_2"
RACE_PLAN_ENDPOINT = "/API154/racePlan"
RACE_PLAN_OPERATION = "racePlan"
AI_RACE_RESULT_ENDPOINT = "/API155/raceResult"
AI_RACE_RESULT_OPERATION = "raceResult"
DETAILED_RACE_RESULT_ENDPOINT = "/API156/raceRsutDtl"
DETAILED_RACE_RESULT_OPERATION = "raceRsutDtl"
FINAL_DIVIDEND_ENDPOINT = "/API301/Dividend_rate_total"
FINAL_DIVIDEND_OPERATION = "Dividend_rate_total"


class KraApiError(RuntimeError):
    """Raised when the KRA gateway returns an invalid or unsuccessful response."""


class KraApiTransientError(KraApiError):
    """Raised for retryable transport and server failures."""


@dataclass(frozen=True, slots=True)
class FetchedPage:
    endpoint: str
    operation: str
    source_url: str
    public_params: Mapping[str, str | int]
    requested_at_ms: int
    retrieved_at_ms: int
    status_code: int
    content_type: str | None
    body: bytes
    payload: dict[str, Any]


class KraApiClient:
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

    def __enter__(self) -> KraApiClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def iter_entry_sheet_pages(
        self,
        *,
        race_date: str,
        meet: int,
        page_size: int = 100,
    ) -> Iterator[FetchedPage]:
        if meet not in {1, 2, 3, 4}:
            raise ValueError("meet는 1(서울), 2(제주), 3(부산경남), 4(영천) 중 하나여야 합니다.")
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size는 1 이상 1000 이하여야 합니다.")

        yield from self.iter_pages(
            endpoint=ENTRY_SHEET_ENDPOINT,
            operation=ENTRY_SHEET_OPERATION,
            public_params={
                "meet": meet,
                "rc_date": race_date,
                "_type": "json",
            },
            page_size=page_size,
            service_key_parameter="ServiceKey",
        )

    def iter_pages(
        self,
        *,
        endpoint: str,
        operation: str,
        public_params: Mapping[str, str | int],
        page_size: int = 1000,
        service_key_parameter: str = "serviceKey",
    ) -> Iterator[FetchedPage]:
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size는 1 이상 1000 이하여야 합니다.")

        page_no = 1
        while True:
            page_params = {
                **public_params,
                "pageNo": page_no,
                "numOfRows": page_size,
            }
            fetched = self._fetch_json(
                endpoint,
                operation,
                page_params,
                service_key_parameter=service_key_parameter,
            )
            yield fetched

            body = response_body(fetched.payload)
            total_count = _as_int(body.get("totalCount"), default=0)
            actual_page_size = _as_int(body.get("numOfRows"), default=page_size)
            total_pages = max(1, math.ceil(total_count / max(actual_page_size, 1)))
            if page_no >= total_pages:
                return
            page_no += 1

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, KraApiTransientError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    def _fetch_json(
        self,
        endpoint: str,
        operation: str,
        public_params: Mapping[str, str | int],
        *,
        service_key_parameter: str = "serviceKey",
    ) -> FetchedPage:
        requested_at_ms = _now_ms()
        request_params = {**public_params, service_key_parameter: self._service_key}
        try:
            response = self._client.get(endpoint.lstrip("/"), params=request_params)
        except httpx.TransportError as exc:
            raise KraApiTransientError("KRA API 네트워크 연결에 실패했습니다.") from exc
        retrieved_at_ms = _now_ms()

        if response.status_code >= 500:
            raise KraApiTransientError(f"KRA API 서버 오류: HTTP {response.status_code}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise KraApiError(f"KRA API 요청 실패: HTTP {response.status_code}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise KraApiError("KRA API가 JSON이 아닌 응답을 반환했습니다.") from exc
        if not isinstance(payload, dict):
            raise KraApiError("KRA API 최상위 응답이 JSON 객체가 아닙니다.")

        header = _response_header(payload)
        result_code = str(header.get("resultCode", ""))
        if result_code not in {"00", "0000"}:
            result_message = str(header.get("resultMsg", "알 수 없는 오류"))
            raise KraApiError(f"KRA API 오류 {result_code}: {result_message}")

        redacted_url = str(httpx.URL(str(response.request.url).split("?")[0], params=public_params))
        return FetchedPage(
            endpoint=endpoint,
            operation=operation,
            source_url=redacted_url,
            public_params=dict(public_params),
            requested_at_ms=requested_at_ms,
            retrieved_at_ms=retrieved_at_ms,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            body=response.content,
            payload=payload,
        )


def _response_root(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    response = payload.get("response", payload)
    if not isinstance(response, Mapping):
        raise KraApiError("KRA API response 객체를 찾을 수 없습니다.")
    return response


def _response_header(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    header = _response_root(payload).get("header", {})
    if not isinstance(header, Mapping):
        raise KraApiError("KRA API header 객체를 찾을 수 없습니다.")
    return header


def response_body(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    body = _response_root(payload).get("body", {})
    if not isinstance(body, Mapping):
        raise KraApiError("KRA API body 객체를 찾을 수 없습니다.")
    return body


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_ms() -> int:
    return time.time_ns() // 1_000_000

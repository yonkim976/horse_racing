import httpx
import pytest

from horse_racing.collectors.kra_api import KraApiClient, KraApiError, KraApiTransientError
from horse_racing.jobs.local_race_day import LocalKraApiClient
from horse_racing.jobs.local_resilience import safe_failure


def success():
    return {
        "response": {
            "header": {"resultCode": "00"},
            "body": {"totalCount": 0, "items": {"item": []}},
        }
    }


def fetch(client):
    return list(
        client.iter_pages(
            endpoint="/API156/raceRsutDtl",
            operation="raceRsutDtl",
            public_params={"rccrs_cd": 1, "race_dt": "20261011"},
        )
    )


def test_live_get_retries_non_json_once_and_recovers():
    requests = []

    def handler(request):
        requests.append(request)
        return (
            httpx.Response(200, text="temporary gateway HTML")
            if len(requests) == 1
            else httpx.Response(200, json=success())
        )

    with LocalKraApiClient("synthetic-secret", transport=httpx.MockTransport(handler)) as client:
        assert len(fetch(client)) == 1
    assert len(requests) == 2


def test_live_get_stops_after_two_invalid_responses_and_has_safe_diagnostics():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text="synthetic-secret gateway HTML")

    with LocalKraApiClient("synthetic-secret", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KraApiTransientError) as exc:
            fetch(client)
    assert len(requests) == 2
    assert safe_failure(exc.value) == {
        "error_type": "KraApiTransientError",
        "error_reason": "api_bad_json",
        "http_status": 200,
    }
    assert "synthetic-secret" not in str(safe_failure(exc.value))


def test_authentication_failure_is_not_retried_or_leaked():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "30", "resultMsg": "remote synthetic-secret echo"}
                }
            },
        )

    with LocalKraApiClient("synthetic-secret", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KraApiError) as exc:
            fetch(client)
    assert len(requests) == 1
    assert safe_failure(exc.value)["api_result_code"] == "30"
    assert safe_failure(exc.value)["error_reason"] == "api_authentication"
    assert "synthetic-secret" not in str(exc.value)


def test_xml_gateway_auth_error_is_not_misclassified_as_transient_html():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            text="""<OpenAPI_ServiceResponse><cmmMsgHeader>
        <errMsg>synthetic-secret</errMsg><returnReasonCode>30</returnReasonCode>
        </cmmMsgHeader></OpenAPI_ServiceResponse>""",
        )

    with LocalKraApiClient("synthetic-secret", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KraApiError) as exc:
            fetch(client)
    assert len(requests) == 1
    assert safe_failure(exc.value)["error_reason"] == "api_authentication"
    assert "synthetic-secret" not in str(exc.value)


def test_gateway_header_is_transient_but_no_data_is_not_silently_accepted():
    for code, error in [("05", KraApiTransientError), ("03", KraApiError)]:
        with KraApiClient(
            "test",
            transport=httpx.MockTransport(
                lambda request, code=code: httpx.Response(
                    200, json={"response": {"header": {"resultCode": code}}}
                )
            ),
        ) as client:
            with pytest.raises(error) as exc:
                KraApiClient._fetch_json.__wrapped__(
                    client, "/API156/raceRsutDtl", "raceRsutDtl", {}
                )
            assert safe_failure(exc.value)["api_result_code"] == code

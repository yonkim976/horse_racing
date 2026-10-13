from __future__ import annotations

import pytest
from starlette.requests import Request

from horse_racing.web.request_policy import (
    RequestPolicy,
    normalized_query_key,
)


def make_request(path: str, query: str = "", *, user_agent: str = "") -> Request:
    raw = query.encode()
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": raw,
            "headers": [(b"user-agent", user_agent.encode())] if user_agent else [],
            "server": ("mapilog.xyz", 443),
            "client": ("127.0.0.1", 12345),
        }
    )


def test_rejects_input_complexity_before_route_loader() -> None:
    policy = RequestPolicy()
    too_many_horses = "&".join(f"horse={index}" for index in range(41))
    too_many_horses_response = policy.check_request(
        make_request("/analysis", too_many_horses), client_key="horse-list"
    )
    assert too_many_horses_response is not None
    assert too_many_horses_response.status_code == 422
    assert too_many_horses_response.policy_diagnostics == {
        "category": "request_validation",
        "reason": "invalid_request",
        "count": None,
        "limit": None,
    }

    oversized = policy.check_request(
        make_request("/analysis", "q=" + "x" * 4100), client_key="long-query"
    )
    assert oversized is not None and oversized.status_code == 422

    broad_validation = policy.check_request(
        make_request("/validation", "start=2020-01-01&end=2022-01-01"),
        client_key="wide-range",
    )
    assert broad_validation is not None and broad_validation.status_code == 422

    deep_page = policy.check_request(
        make_request("/horses", "page=201"), client_key="deep-page"
    )
    assert deep_page is not None and deep_page.status_code == 422

    broad_analysis = policy.check_request(
        make_request("/analysis", "start=2020-01-01&end=2022-01-01"),
        client_key="analysis-range",
    )
    assert broad_analysis is not None and broad_analysis.status_code == 422

    huge_path = policy.check_request(
        make_request("/races/" + "9" * 1100), client_key="huge-path"
    )
    assert huge_path is not None and huge_path.status_code == 422


@pytest.mark.parametrize("path", ["/analysis", "/api/analysis/export.csv", "/validation"])
@pytest.mark.parametrize(
    "query",
    [
        "start=2026-01-01",
        "start=2026-01-01&end=",
        "end=2026-01-01",
        "start=&end=2026-01-01",
    ],
)
def test_date_ranges_must_be_paired(path: str, query: str) -> None:
    response = RequestPolicy().check_request(
        make_request(path, query), client_key=f"one-sided-{path}-{query}"
    )
    assert response is not None and response.status_code == 422
    assert "시작일과 종료일을 함께" in response.body.decode()


@pytest.mark.parametrize("path", ["/analysis", "/api/analysis/export.csv", "/validation"])
def test_absent_or_empty_date_ranges_keep_route_defaults(path: str) -> None:
    policy = RequestPolicy()
    assert policy.check_request(make_request(path), client_key=f"default-{path}") is None
    assert policy.check_request(
        make_request(path, "start=&end="), client_key=f"empty-{path}"
    ) is None
    assert policy.check_request(
        make_request(path, "start=2026-01-01&end=2026-12-31"),
        client_key=f"paired-{path}",
    ) is None


def test_semantic_cache_key_coalesces_irrelevant_query_but_preserves_effective_inputs() -> None:
    base = normalized_query_key(make_request("/analysis"))
    tracking_a = normalized_query_key(make_request("/analysis", "utm_source=one"))
    tracking_b = normalized_query_key(make_request("/analysis", "noise=two"))
    assert base == ""
    assert tracking_a == "__has_query=1"
    assert tracking_b == "__noindex=1"

    first = normalized_query_key(make_request("/analysis", "meet=2&date=2026-09-23"))
    second = normalized_query_key(make_request("/analysis", "date=2026-09-23&meet=2"))
    assert first == second == "date=2026-09-23&meet=2"
    assert normalized_query_key(make_request("/analysis", "date=2026-09-22&meet=2")) != first
    assert normalized_query_key(make_request("/analysis", "race_id=1&tab=records")) != (
        normalized_query_key(make_request("/analysis", "race_id=1&tab=memo"))
    )

    home_one = normalized_query_key(make_request("/", "race_id=14&trial_id=4"))
    home_two = normalized_query_key(make_request("/", "trial_id=4&race_id=14"))
    assert home_one == home_two == "race_id=14&trial_id=4"
    assert normalized_query_key(make_request("/races/14", "utm_source=one")) == "__has_query=1"
    assert normalized_query_key(make_request("/analysis", "date=2026-09-23&q=one")) == (
        "date=2026-09-23"
    )


def test_mobile_legacy_redirect_inputs_remain_supported() -> None:
    legacy = make_request("/m/analysis", "race_id=123&entry=4&date=2026-09-23")
    assert RequestPolicy().check_request(legacy, client_key="legacy") is None
    assert normalized_query_key(legacy) == ""

    normal_mobile = make_request("/analysis", "date=2026-09-23&meet=2", user_agent="iPhone")
    assert RequestPolicy().check_request(normal_mobile, client_key="mobile") is None


def test_costly_route_rotation_shares_client_quota_and_returns_retry_after(monkeypatch) -> None:
    import horse_racing.web.request_policy as module

    monkeypatch.setitem(module._QUOTAS, "expensive", (24, 8))
    client = "route-rotation"
    policy = RequestPolicy()
    for i in range(8):
        route = "/analysis" if i % 2 == 0 else "/forecast"
        assert policy.check_request(make_request(route), client_key=client, now=100.0) is None
    limited = policy.check_request(make_request("/validation"), client_key=client, now=100.0)
    assert limited is not None
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert limited.headers["Cache-Control"] == "no-store"
    assert limited.policy_diagnostics == {
        "category": "expensive",
        "reason": "burst_limit",
        "count": 8,
        "limit": 8,
    }


def test_csv_has_a_tighter_endpoint_quota() -> None:
    client = "csv-budget"
    policy = RequestPolicy()
    for i in range(2):
        assert policy.check_request(
            make_request("/api/analysis/export.csv"), client_key=client, now=200.0 + i
        ) is None
    limited = policy.check_request(
        make_request("/api/analysis/export.csv"), client_key=client, now=203.0
    )
    assert limited is not None and limited.status_code == 429


def test_dashboard_and_distance_pages_share_expensive_request_budget(monkeypatch) -> None:
    import horse_racing.web.request_policy as module

    monkeypatch.setitem(module._QUOTAS, "expensive", (24, 8))
    policy = RequestPolicy()
    for i in range(8):
        route = "/" if i % 2 == 0 else "/racecourses/seoul/distances"
        assert (
            policy.check_request(make_request(route), client_key="dashboard", now=300)
            is None
        )
    limited = policy.check_request(make_request("/analysis"), client_key="dashboard", now=300)
    assert limited is not None and limited.status_code == 429


def test_yeongcheon_distance_page_accepts_the_distance_query_policy() -> None:
    response = RequestPolicy().check_request(
        make_request(
            "/racecourses/yeongcheon/distances",
            "year=2026&distance=1200&grade=1%EB%93%B1%EA%B8%89&page=1",
        ),
        client_key="yeongcheon-distance",
    )
    assert response is None


def test_distance_trial_view_is_validated_and_separated_in_cache_key() -> None:
    policy = RequestPolicy()
    path = "/racecourses/seoul/distances"
    regular = make_request(path, "year=2026")
    trials = make_request(path, "view=trials&year=2026")

    assert policy.check_request(regular, client_key="distance-regular") is None
    assert policy.check_request(trials, client_key="distance-trials") is None
    assert normalized_query_key(regular) == "year=2026"
    assert normalized_query_key(trials) == "view=trials&year=2026"
    assert normalized_query_key(regular) != normalized_query_key(trials)

    for query in ("view=regular", "view=unknown", "view="):
        rejected = policy.check_request(
            make_request(path, query), client_key=f"invalid-distance-view-{query}"
        )
        assert rejected is not None and rejected.status_code == 422


def test_distance_benchmark_band_is_validated_and_separated_in_cache_key() -> None:
    policy = RequestPolicy()
    path = "/racecourses/seoul/distances"
    dry = make_request(path, "year=2026&distance=1200&band=%EA%B1%B4%EC%A1%B0")
    wet = make_request(path, "year=2026&distance=1200&band=%EB%B6%88%EB%9F%89")
    assert policy.check_request(dry, client_key="distance-dry") is None
    assert policy.check_request(wet, client_key="distance-wet") is None
    assert normalized_query_key(dry) != normalized_query_key(wet)
    assert "band=%EB%B6%88%EB%9F%89" in normalized_query_key(wet)

    for value in ("invalid", ""):
        rejected = policy.check_request(
            make_request(path, f"distance=1200&band={value}"),
            client_key=f"invalid-distance-band-{value}",
        )
        assert rejected is not None and rejected.status_code == 422


def test_race_and_trial_path_ids_cannot_bypass_the_expensive_budget() -> None:
    policy = RequestPolicy()
    for path in ("/races/+1", "/running-trials/+1", "/races/-1"):
        invalid = policy.check_request(make_request(path), client_key="noncanonical")
        assert invalid is not None and invalid.status_code == 422

    # Leading zeroes still resolve to the same integer route, so accept them
    # while counting the request against the shared and detail quotas.
    assert policy.check_request(
        make_request("/races/0001"), client_key="padded", now=350
    ) is None


def test_dashboard_meet_and_numeric_entity_fallback_ids_are_bounded() -> None:
    policy = RequestPolicy()
    assert policy.check_request(make_request("/", "meet="), client_key="empty-meet") is None
    for value in ("0", "5", "999999999999999999999", "seoul", "１"):
        response = policy.check_request(
            make_request("/", f"meet={value}"), client_key=f"bad-meet-{value}"
        )
        assert response is not None and response.status_code == 422

    overlarge_numeric_key = policy.check_request(
        make_request("/horses/9223372036854775808"), client_key="large-entity-id"
    )
    assert overlarge_numeric_key is not None and overlarge_numeric_key.status_code == 422
    assert policy.check_request(
        make_request("/horses/003001"), client_key="official-key"
    ) is None


def test_policy_state_is_per_app_and_sliding_window_prunes_old_requests() -> None:
    first, second = RequestPolicy(), RequestPolicy()
    for i in range(25):
        assert first.check_request(
            make_request("/analysis"), client_key="steady", now=400 + i * 3
        ) is None
    assert second.check_request(make_request("/analysis"), client_key="steady", now=472) is None


def test_live_quota_buckets_are_not_evicted_when_capacity_is_full(monkeypatch) -> None:
    import horse_racing.web.request_policy as module

    monkeypatch.setattr(module, "_MAX_CLIENT_BUCKETS", 2)
    policy = RequestPolicy()
    assert policy.check_request(make_request("/analysis"), client_key="first", now=500) is None
    limited = policy.check_request(
        make_request("/analysis"), client_key="second", now=501
    )
    assert limited is not None and limited.status_code == 429
    assert policy.check_request(make_request("/analysis"), client_key="first", now=502) is None
    # Once the first client's whole window is idle its state expires and a new
    # client can reserve both of the bounded slots.
    assert policy.check_request(make_request("/analysis"), client_key="second", now=562) is None


def test_calendar_query_accepts_only_one_valid_month() -> None:
    policy = RequestPolicy()
    for query in (
        "month=2026-00",
        "month=2026-13",
        "month=2026-8",
        "month=0000-01",
        "month=2026-08&month=2026-09",
        "month=2026-08&tenant=other",
        "month=2026-08&" + "x" * 2100,
    ):
        rejected = policy.check_request(
            make_request("/api/calendar", query), client_key=f"calendar-{len(query)}"
        )
        assert rejected is not None and rejected.status_code == 422, query

    assert policy.check_request(
        make_request("/api/calendar", "month=2026-08"), client_key="calendar-valid"
    ) is None


@pytest.mark.parametrize("query", ["page=201", "page=99999999999999999999", "page=1&page=2", "q=" + "a" * 101])
def test_horse_separate_list_has_directory_query_bounds(query):
    response = RequestPolicy().check_request(
        make_request("/horses/list", query), client_key="directory-bounds",
    )
    assert response is not None and response.status_code == 422


def test_entity_response_keys_separate_filters_and_detail_tabs():
    for path, first, second in [
        ("/owners", "meet=1&period=month", "meet=2&period=month"),
        ("/jockeys", "period=month", "period=year"),
        ("/horses/list", "grade=1&origin=domestic", "grade=2&origin=domestic"),
        ("/horses/0045769", "tab=profile", "tab=records"),
        ("/jockeys/080361", "tab=partners&period=month", "tab=partners&period=year"),
    ]:
        assert normalized_query_key(make_request(path, first)) != normalized_query_key(
            make_request(path, second),
        )

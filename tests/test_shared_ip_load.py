"""Offline shared-NAT integration exercise; no network or production DB use."""

import asyncio

from scripts.verify_shared_ip_load import run_shared_ip_load


def test_one_hundred_browser_journeys_share_a_peer_ip(tmp_path) -> None:
    report = asyncio.run(
        run_shared_ip_load(
            tmp_path,
            client_count=100,
            simulated_latency_seconds=0.001,
        )
    )

    assert report["client_count"] == 100
    assert report["peer_ip_count"] == 1
    assert report["database"]["database_kind"] == "seeded local SQLite"
    assert report["database"]["web_read_only_guard"] is True
    assert report["database"]["max_active_session_contexts"] <= 3
    assert report["database"]["select_statements"] > 0
    assert report["layout_cache_bypass_dashboard_loader_calls"] == 2
    assert report["asset_cache_control"] == "public, max-age=3600"
    assert report["asset_revalidation_status"] in {200, 304}
    assert report["warmup_home_requests"] == 2
    assert 0 <= report["warmup_dashboard_loader_calls"] <= 2

    cold = report["journey_phases"]["cold"]
    warm = report["journey_phases"]["warm"]
    for phase in (cold, warm):
        assert phase["request_count"] >= 700
        assert phase["completed_browser_journeys"] == 100
        assert phase["429_count"] == 0
        assert phase["error_status_counts"] == {}
        assert phase["p95_journey_ms"] >= phase["p50_journey_ms"]
    assert cold["loader_calls"]["load_calendar_index"] == 1
    assert warm["loader_calls"]["load_calendar_index"] == 0
    assert warm["select_statements"] <= cold["select_statements"]
    assert warm["loader_calls"].get("load_dashboard", 0) == 0

"""Exercise the real middleware stack without connecting to a database."""

import asyncio
import importlib
import json
from collections.abc import Callable

import httpx
import pytest
from fastapi import Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.testclient import TestClient

from horse_racing.web.app import create_app
from horse_racing.web.security import ActiveRequestGate, parse_trusted_proxy_cidrs


def middleware_client(
    handler: Callable, *, peer: str = "testclient",
) -> TestClient:
    def forbidden_database():
        raise AssertionError("Middleware regression tests must not open a database")

    app = create_app(session_factory=forbidden_database)
    app.router.routes.clear()
    app.add_api_route("/{path:path}", handler, methods=["GET"])
    return TestClient(app, client=(peer, 50000))


def test_origin_guard_rejects_direct_requests_before_route_loader(monkeypatch, capsys) -> None:
    token = "a" * 32
    monkeypatch.setenv("MAPILOG_ORIGIN_TOKEN", token)
    calls = []

    async def render():
        calls.append(True)
        return PlainTextResponse("ok")

    with middleware_client(render) as client:
        assert client.get("/").status_code == 403
        assert client.get("/", headers={"X-Mapilog-Origin-Token": "wrong"}).status_code == 403
        assert client.get("/", headers={"X-Mapilog-Origin-Token": token}).status_code == 403
        accepted = client.get("/", headers={
            "X-Mapilog-Origin-Token": token,
            "CF-Connecting-IP": "203.0.113.5",
        })
        assert client.get("/").status_code == 403

    assert accepted.status_code == 200
    assert accepted.text == "ok"
    assert calls == [True]
    output = capsys.readouterr().out
    assert token not in output
    assert '"category":"origin_guard"' in output


def test_origin_guard_uses_verified_cloudflare_client_ip(monkeypatch) -> None:
    token = "a" * 32
    monkeypatch.setenv("MAPILOG_ORIGIN_TOKEN", token)

    async def render(request: Request):
        module = importlib.import_module("horse_racing.web.app")
        return PlainTextResponse(module._client_rate_key(request))

    with middleware_client(render, peer="10.1.2.3") as client:
        first = client.get("/robots.txt", headers={
            "X-Mapilog-Origin-Token": token,
            "CF-Connecting-IP": "203.0.113.5",
            "X-Forwarded-For": "198.51.100.99",
        })
        second = client.get("/robots.txt", headers={
            "X-Mapilog-Origin-Token": token,
            "CF-Connecting-IP": "2001:db8::5",
        })
        invalid = client.get("/robots.txt", headers={
            "X-Mapilog-Origin-Token": token,
            "CF-Connecting-IP": "not-an-ip",
        })

    assert first.text == "203.0.113.5"
    assert second.text == "2001:db8::5"
    assert invalid.status_code == 403


def test_origin_guard_rejects_short_configured_token(monkeypatch) -> None:
    monkeypatch.setenv("MAPILOG_ORIGIN_TOKEN", "too-short")
    with pytest.raises(ValueError, match="at least 32 characters"):
        create_app()


def test_home_cache_preserves_selected_race_and_trial() -> None:
    calls = []

    async def render(request: Request):
        selection = (request.query_params.get("race_id"), request.query_params.get("trial_id"))
        calls.append(selection)
        return PlainTextResponse(str(selection))

    with middleware_client(render) as client:
        race_one = client.get("/?race_id=1")
        race_two = client.get("/?race_id=2")
        trial = client.get("/?trial_id=1")
        same_race = client.get("/?utm_source=example&race_id=1")

    assert race_one.status_code == race_two.status_code == trial.status_code == 200
    assert race_one.text != race_two.text != trial.text
    assert same_race.text == race_one.text
    assert calls == [("1", None), ("2", None), (None, "1")]


def test_unknown_queries_share_cache_without_overwriting_unqueried_seo() -> None:
    calls = []

    async def render(request: Request):
        marker = "noindex" if request.url.query else "index"
        calls.append(marker)
        return PlainTextResponse(marker)

    with middleware_client(render) as client:
        first = client.get("/races/1?utm_source=first")
        second = client.get("/races/1?utm_source=second")
        canonical = client.get("/races/1")

    assert first.text == second.text == "noindex"
    assert canonical.text == "index"
    assert calls == ["noindex", "index"]


def test_cookie_and_authorization_requests_do_not_share_anonymous_cache() -> None:
    calls = []

    async def render(request: Request):
        identity = request.headers.get("authorization") or request.headers.get("cookie") or "anon"
        calls.append(identity)
        return PlainTextResponse(identity)

    with middleware_client(render) as client:
        assert client.get("/").text == "anon"
        assert client.get("/", headers={"Authorization": "Bearer example"}).text == "Bearer example"
        assert client.get("/", headers={"Cookie": "session=example"}).text == "session=example"
        assert client.get("/").text == "anon"

    assert calls == ["anon", "Bearer example", "session=example"]


def test_costly_route_rotation_shares_one_client_budget() -> None:
    async def render():
        return PlainTextResponse("ok")

    paths = [
        "/", "/analysis", "/forecast", "/validation", "/races/1",
        "/horses", "/predictions", "/data-status", "/racecourses/jeju/distances",
    ]
    with middleware_client(render) as client:
        results = [client.get(path) for path in paths]

    assert all(result.status_code == 200 for result in results[:8])
    assert results[-1].status_code == 429
    assert results[-1].headers["retry-after"] == "60"


def test_denial_logs_are_structured_and_omit_client_ip_and_query(capsys) -> None:
    async def render():
        return PlainTextResponse("ok")

    with middleware_client(render, peer="203.0.113.44") as client:
        for _ in range(8):
            assert client.get("/analysis?horse=123&token=private").status_code == 200
        denied = client.get("/analysis?horse=123&token=private")

    assert denied.status_code == 429
    output = capsys.readouterr().out
    event = json.loads(output.strip().splitlines()[-1])
    assert event == {
        "event": "request_policy_denied",
        "severity": "WARNING",
        "status_code": 429,
        "category": "expensive",
        "reason": "burst_limit",
        "path": "/analysis",
        "count": 8,
        "limit": 8,
        "retry_after": "60",
        "duration_ms": event["duration_ms"],
        "response_bytes": len(denied.content),
    }
    assert "203.0.113.44" not in output
    assert "token" not in output


def test_sampled_success_logs_normalized_path_duration_and_bytes(monkeypatch, capsys) -> None:
    module = importlib.import_module("horse_racing.web.app")
    monkeypatch.setattr(module.random, "random", lambda: 0.0)

    async def render():
        return PlainTextResponse("sample")

    with middleware_client(render) as client:
        response = client.get("/races/123?secret=value")

    assert response.status_code == 200
    output = capsys.readouterr().out
    event = json.loads(output.strip().splitlines()[-1])
    assert event["event"] == "request_sample"
    assert event["severity"] == "INFO"
    assert event["path"] == "/races/{id}"
    assert event["status_code"] == 200
    assert event["duration_ms"] >= 0
    assert event["response_bytes"] == len(response.content)
    assert "secret" not in output


def test_distinct_app_instances_do_not_share_usage_records() -> None:
    async def render():
        return PlainTextResponse("ok")

    with middleware_client(render) as first:
        for _ in range(8):
            assert first.get("/analysis").status_code == 200
        assert first.get("/analysis").status_code == 429
    with middleware_client(render) as second:
        assert second.get("/analysis").status_code == 200


def test_buffered_response_preserves_all_set_cookie_headers() -> None:
    calls = []

    async def render():
        calls.append(1)
        response = PlainTextResponse("ok")
        response.set_cookie("first", "one")
        response.set_cookie("second", "two")
        return response

    with middleware_client(render) as client:
        response = client.get("/")
        assert len(response.headers.get_list("set-cookie")) == 2
        client.cookies.clear()
        assert client.get("/").status_code == 200
    assert len(calls) == 2


def test_oversized_responses_are_blocked_with_or_without_compression() -> None:
    async def render():
        return PlainTextResponse("x" * (2 * 1024 * 1024 + 1))

    with middleware_client(render) as client:
        for encoding in ("gzip", "identity"):
            response = client.get("/api/predictions", headers={"Accept-Encoding": encoding})
            assert response.status_code == 413
            assert response.headers["cache-control"] == "no-store"
            assert len(response.content) < 1024


def test_response_size_denial_logs_limit_and_observed_size(capsys) -> None:
    async def render():
        return PlainTextResponse("x" * (2 * 1024 * 1024 + 1))

    with middleware_client(render) as client:
        response = client.get("/api/predictions")

    event = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert response.status_code == 413
    assert event["category"] == "response_size"
    assert event["reason"] == "content_length_limit"
    assert event["count"] > event["limit"] == 2 * 1024 * 1024
    assert event["path"] == "/api/predictions"
    assert event["retry_after"] is None


def test_validation_denial_logs_safe_generic_reason(capsys) -> None:
    async def render():
        return PlainTextResponse("ok")

    with middleware_client(render) as client:
        response = client.get("/analysis?start=invalid&token=secret")

    event = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert response.status_code == 422
    assert event["category"] == "request_validation"
    assert event["reason"] == "invalid_request"
    assert event["path"] == "/analysis"
    assert "token" not in json.dumps(event)
    assert "secret" not in json.dumps(event)


def test_stream_without_content_length_is_also_capped() -> None:
    async def render():
        async def chunks():
            for _ in range(4):
                yield b"x" * (1024 * 1024)

        return StreamingResponse(chunks(), media_type="text/csv")

    with middleware_client(render) as client:
        response = client.get("/api/analysis/export.csv")
    assert response.status_code == 413
    assert len(response.content) < 1024


def test_only_trusted_peer_can_set_forwarded_https_scheme(monkeypatch) -> None:
    module = importlib.import_module("horse_racing.web.app")
    monkeypatch.setattr(module, "_TRUSTED_PROXY_CIDRS", parse_trusted_proxy_cidrs("10.0.0.0/8"))

    async def render(request: Request):
        return PlainTextResponse(request.url.scheme)

    with middleware_client(render, peer="10.1.2.3") as trusted:
        assert trusted.get("/", headers={"X-Forwarded-Proto": "https"}).text == "https"
    with middleware_client(render, peer="203.0.113.1") as untrusted:
        assert untrusted.get("/", headers={"X-Forwarded-Proto": "https"}).text == "http"


def test_concurrency_guard_rejects_excess_and_releases_cancelled_request(
    monkeypatch, capsys
) -> None:
    module = importlib.import_module("horse_racing.web.app")
    gate = ActiveRequestGate(limit=2)
    monkeypatch.setattr(module, "ActiveRequestGate", lambda **kwargs: gate)

    async def exercise():
        app = create_app()
        app.router.routes.clear()
        entered = 0
        occupied = asyncio.Event()
        release = asyncio.Event()

        @app.get("/robots.txt")
        async def render():
            nonlocal entered
            entered += 1
            if entered == 2:
                occupied.set()
            await release.wait()
            return PlainTextResponse("ok")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first = asyncio.create_task(client.get("/robots.txt"))
            second = asyncio.create_task(client.get("/robots.txt"))
            try:
                await asyncio.wait_for(occupied.wait(), timeout=3)
                denied = await client.get("/robots.txt")
                assert denied.status_code == 503
                assert denied.headers["retry-after"] == "1"
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
                release.set()
                assert (await second).status_code == 200
                assert (await client.get("/robots.txt")).status_code == 200
            finally:
                release.set()
                for task in (first, second):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(first, second, return_exceptions=True)

    asyncio.run(exercise())
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    denied = next(event for event in events if event.get("status_code") == 503)
    assert denied["category"] == "concurrency"
    assert denied["reason"] == "active_request_limit"
    assert denied["count"] == denied["limit"] == 2
    assert denied["retry_after"] == "1"

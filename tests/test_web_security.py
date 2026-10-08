from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from horse_racing.web.app import create_app
from horse_racing.web.security import (
    ActiveRequestGate,
    AsyncLockCapacityExceeded,
    AsyncLockRegistry,
    BoundedAsyncGate,
    BoundedRequestLimiter,
    BoundedTTLCache,
    SyncLockRegistry,
    bounded_size,
    parse_trusted_proxy_cidrs,
    resolve_client_ip,
)


def test_forwarded_for_requires_trusted_peer_and_valid_chain() -> None:
    networks = parse_trusted_proxy_cidrs("10.0.0.0/8, 192.0.2.0/24")
    assert resolve_client_ip("203.0.113.7", "198.51.100.9", networks) == "203.0.113.7"
    assert resolve_client_ip("10.1.2.3", "198.51.100.9, 192.0.2.2", networks) == "198.51.100.9"
    assert resolve_client_ip("10.1.2.3", "198.51.100.9, nope", networks) == "10.1.2.3"
    too_many_hops = "198.51.100.9, " + ",".join(["192.0.2.1"] * 33)
    assert resolve_client_ip("10.1.2.3", too_many_hops, networks) == "10.1.2.3"


def test_proxy_wildcard_is_rejected_and_empty_is_safe_default() -> None:
    assert parse_trusted_proxy_cidrs("") == ()
    with pytest.raises(ValueError):
        parse_trusted_proxy_cidrs("0.0.0.0/0")


def test_bounded_limiter_does_not_evict_active_clients_to_reset_quota() -> None:
    limiter = BoundedRequestLimiter(max_clients=3, idle_ttl=120)
    limits = dict(window_seconds=60, window_limit=1, burst_seconds=10, burst_limit=1)
    assert limiter.allow("client-a", now=1, **limits)
    assert limiter.allow("client-b", now=2, **limits)
    assert not limiter.allow("client-c", now=3, **limits)  # shares full overflow bucket
    assert not limiter.allow("client-d", now=4, **limits)
    assert len(limiter) == 2
    assert not limiter.allow("client-a", now=5, **limits)


def test_ttl_cache_enforces_entry_and_total_byte_bounds() -> None:
    cache: BoundedTTLCache[str, bytes] = BoundedTTLCache(
        max_entries=2, max_bytes=5, size_of=len
    )
    now = monotonic()
    assert cache.set("a", b"123", ttl=10, now=now)
    assert cache.set("b", b"45", ttl=10, now=now)
    assert cache.byte_size == 5
    assert cache.set("c", b"xy", ttl=10, now=now)
    assert len(cache) == 2
    assert cache.get("a", now=now + 1) is None
    assert cache.get("b", now=now + 1) == b"45"
    assert cache.get("c", now=now + 11) is None


def test_bounded_size_walks_slotted_dataclasses() -> None:
    @dataclass(slots=True)
    class Payload:
        body: list[str]

    payload = Payload(["x" * 20_000])
    assert bounded_size(payload, limit=10_000) > 10_000
    cache: BoundedTTLCache[str, Payload] = BoundedTTLCache(
        max_entries=4,
        max_bytes=8_000,
        max_entry_bytes=1_000,
        size_of=lambda value: bounded_size(value, limit=1_000),
    )
    assert not cache.set("large", payload, ttl=10)
    assert len(cache) == 0


def test_page_size_does_not_follow_shared_model_class_metadata() -> None:
    class SharedModel:
        metadata = {"large_shared_registry": "x" * 100_000}

    @dataclass(slots=True)
    class Page:
        model: type
        rows: list[str]

    assert bounded_size(Page(SharedModel, ["small page"]), limit=10_000) < 10_000
    assert bounded_size(Page(SharedModel, ["x" * 20_000]), limit=10_000) > 10_000


def test_lock_registries_have_fixed_memory_after_success_and_exception() -> None:
    sync_locks: SyncLockRegistry[str] = SyncLockRegistry(stripes=8)
    for index in range(1000):
        with pytest.raises(RuntimeError):
            with sync_locks.hold(str(index)):
                raise RuntimeError("loader failed")
    assert len(sync_locks) == 8

    async def exercise_async_registry() -> None:
        locks: AsyncLockRegistry[str] = AsyncLockRegistry(stripes=8)
        for index in range(1000):
            with pytest.raises(RuntimeError):
                async with locks.hold(str(index)):
                    raise RuntimeError("body read failed")
        assert len(locks) == 8

    asyncio.run(exercise_async_registry())


def test_active_request_gate_fails_closed_at_capacity() -> None:
    gate = ActiveRequestGate(limit=1)
    assert gate.try_enter()
    assert not gate.try_enter()
    gate.leave()
    assert gate.try_enter()
    gate.leave()


def test_blocked_user_agent_cannot_poison_shared_cache() -> None:
    client = TestClient(create_app())
    blocked = client.get("/health", headers={"User-Agent": "ClaudeBot"})
    normal = client.get("/health", headers={"User-Agent": "Mozilla/5.0"})
    assert blocked.status_code == 403
    assert blocked.headers["cache-control"] == "no-store"
    assert normal.status_code == 200


def test_bounded_async_gate_cancellation_timeout_and_recovery() -> None:
    async def exercise() -> None:
        gate = BoundedAsyncGate(limit=1, max_waiters=1, wait_timeout=0.04)
        assert await gate.acquire()
        waiting = asyncio.create_task(gate.acquire())
        await asyncio.sleep(0)
        assert gate.waiting_count == 1
        assert not await gate.acquire()  # full queue fails without growing state
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert gate.waiting_count == 0
        assert gate.active_count == 1
        await gate.release()
        assert await gate.acquire()

        timed_out = asyncio.create_task(gate.acquire())
        assert not await timed_out
        assert gate.waiting_count == 0
        await gate.release()
        assert await gate.acquire()
        await gate.release()
        assert gate.active_count == gate.waiting_count == 0

    asyncio.run(exercise())


def test_async_singleflight_waiters_are_bounded_and_recover_after_cancel() -> None:
    async def exercise() -> None:
        locks: AsyncLockRegistry[str] = AsyncLockRegistry(
            stripes=8, max_waiters=2, wait_timeout=0.04
        )
        entered = asyncio.Event()
        release_owner = asyncio.Event()

        async def owner() -> None:
            async with locks.hold("same-key"):
                entered.set()
                await release_owner.wait()

        async def waiter() -> None:
            async with locks.hold("same-key"):
                raise AssertionError("same-key waiter should not pass the owner")

        owner_task = asyncio.create_task(owner())
        await entered.wait()
        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        assert locks.outstanding_count == 2
        with pytest.raises(AsyncLockCapacityExceeded):
            async with locks.hold("different-key"):
                pass

        waiter_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter_task
        release_owner.set()
        await owner_task
        assert locks.outstanding_count == 0
        async with locks.hold("same-key"):
            assert locks.outstanding_count == 1
        assert locks.outstanding_count == 0

    asyncio.run(exercise())


def test_crawler_and_human_quotas_do_not_share_token_state() -> None:
    limiter = BoundedRequestLimiter(max_clients=8)
    human_limits = dict(
        window_seconds=60,
        window_limit=5,
        burst_seconds=10,
        burst_limit=5,
        strict_sliding_window=False,
    )
    crawler_limits = dict(
        window_seconds=60,
        window_limit=1,
        burst_seconds=10,
        burst_limit=1,
        strict_sliding_window=True,
    )

    assert limiter.allow("shared-ip", now=1, **human_limits)
    assert limiter.allow("shared-ip", now=2, **crawler_limits)
    assert not limiter.allow("shared-ip", now=3, **crawler_limits)
    assert limiter.allow("shared-ip", now=4, **human_limits)
    assert len(limiter) == 2

from __future__ import annotations

import asyncio
import ipaddress
import sys
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, fields, is_dataclass
from math import ceil
from threading import RLock
from time import monotonic


@dataclass
class _CacheEntry[V]:
    expires_at: float
    value: V
    size: int


class BoundedTTLCache[K, V]:
    """Thread-safe TTL/LRU cache bounded by entry count and estimated bytes."""

    def __init__(
        self,
        *,
        max_entries: int,
        max_bytes: int,
        max_entry_bytes: int | None = None,
        size_of: Callable[[V], int],
    ) -> None:
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.max_entry_bytes = (
            max_bytes
            if max_entry_bytes is None
            else min(max_bytes, max_entry_bytes)
        )
        self.size_of = size_of
        self._entries: OrderedDict[K, _CacheEntry[V]] = OrderedDict()
        self._bytes = 0
        self._lock = RLock()

    def get(self, key: K, *, now: float | None = None) -> V | None:
        current = monotonic() if now is None else now
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= current:
                self._remove(key)
                return None
            self._entries.move_to_end(key)
            return entry.value

    def set(self, key: K, value: V, *, ttl: float, now: float | None = None) -> bool:
        current = monotonic() if now is None else now
        size = max(0, self.size_of(value))
        if size > self.max_entry_bytes or self.max_entries <= 0:
            return False
        with self._lock:
            self._prune_expired(current)
            self._remove(key)
            self._entries[key] = _CacheEntry(current + ttl, value, size)
            self._bytes += size
            while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                oldest = next(iter(self._entries))
                self._remove(oldest)
        return True

    def __len__(self) -> int:
        with self._lock:
            self._prune_expired(monotonic())
            return len(self._entries)

    @property
    def byte_size(self) -> int:
        with self._lock:
            self._prune_expired(monotonic())
            return self._bytes

    def _remove(self, key: K) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= entry.size

    def _prune_expired(self, now: float) -> None:
        for key, entry in list(self._entries.items()):
            if entry.expires_at <= now:
                self._remove(key)


class SyncLockRegistry[K]:
    """Fixed-size striped lock pool; attacker-chosen keys cannot grow its state."""

    def __init__(self, *, stripes: int = 128) -> None:
        self._entries = tuple(RLock() for _ in range(stripes))

    @contextmanager
    def hold(self, key: K) -> Iterator[None]:
        lock = self._entries[hash(key) % len(self._entries)]
        with lock:
            yield

    def __len__(self) -> int:
        return len(self._entries)


class AsyncLockCapacityExceeded(RuntimeError):
    """Raised when a single-flight wait reaches its bound or timeout."""


class AsyncLockRegistry[K]:
    """Fixed-size single-flight stripes with bounded, timed waiter state."""

    def __init__(
        self,
        *,
        stripes: int = 256,
        max_waiters: int = 1024,
        wait_timeout: float = 30.0,
    ) -> None:
        self._entries = tuple(
            BoundedAsyncGate(limit=1, max_waiters=max_waiters, wait_timeout=wait_timeout)
            for _ in range(max(1, stripes))
        )
        # This no-wait gate bounds total in-progress lock holders and waiters
        # across all stripes, including same-key single-flight bursts.
        self._capacity = BoundedAsyncGate(limit=max_waiters, max_waiters=0)

    @asynccontextmanager
    async def hold(self, key: K):
        if not await self._capacity.acquire():
            raise AsyncLockCapacityExceeded("single-flight waiter capacity reached")
        lock = self._entries[hash(key) % len(self._entries)]
        lock_acquired = False
        try:
            lock_acquired = await lock.acquire()
            if not lock_acquired:
                raise AsyncLockCapacityExceeded("single-flight lock timed out or is full")
            yield
        finally:
            try:
                if lock_acquired:
                    await asyncio.shield(lock.release())
            finally:
                await asyncio.shield(self._capacity.release())

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def outstanding_count(self) -> int:
        return self._capacity.active_count

    @property
    def max_waiters(self) -> int:
        return self._capacity.limit


def bounded_size(value: object, *, limit: int, max_nodes: int = 20_000) -> int:
    """Estimate retained Python object size, stopping once the cache limit is crossed."""
    seen: set[int] = set()
    stack = [value]
    total = 0
    nodes = 0
    while stack:
        item = stack.pop()
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        nodes += 1
        if nodes > max_nodes:
            return limit + 1
        try:
            total += sys.getsizeof(item)
        except TypeError:
            total += 64
        if total > limit:
            return limit + 1
        if isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, (list, tuple, set, frozenset, deque)):
            stack.extend(item)
        elif is_dataclass(item) and not isinstance(item, type):
            stack.extend(getattr(item, field.name) for field in fields(item))
        elif not isinstance(item, type) and hasattr(item, "__dict__"):
            # Shared ORM model classes are metadata, not retained per-page data.
            stack.append(vars(item))
        if total > limit:
            return limit + 1
    return total


class ActiveRequestGate:
    """Bound in-flight request work and response buffering for one app instance."""

    def __init__(self, *, limit: int = 128) -> None:
        self.limit = limit
        self._active = 0
        self._lock = RLock()

    def try_enter(self) -> bool:
        with self._lock:
            if self._active >= self.limit:
                return False
            self._active += 1
            return True

    def leave(self) -> None:
        with self._lock:
            if self._active > 0:
                self._active -= 1

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active


class BoundedAsyncGate:
    """FIFO async admission with fixed active and pending-request bounds."""

    def __init__(
        self,
        *,
        limit: int,
        max_waiters: int,
        wait_timeout: float = 30.0,
    ) -> None:
        self.limit = max(1, limit)
        self.max_waiters = max(0, max_waiters)
        self.wait_timeout = max(0.01, wait_timeout)
        self._active = 0
        self._waiters: deque[asyncio.Future[None]] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        loop = asyncio.get_running_loop()
        async with self._lock:
            if self._active < self.limit and not self._waiters:
                self._active += 1
                return True
            if len(self._waiters) >= self.max_waiters:
                return False
            waiter: asyncio.Future[None] = loop.create_future()
            self._waiters.append(waiter)

        try:
            await asyncio.wait_for(waiter, timeout=self.wait_timeout)
            return True
        except TimeoutError:
            await self._withdraw(waiter)
            return False
        except BaseException:
            await self._withdraw(waiter)
            raise

    async def _withdraw(self, waiter: asyncio.Future[None]) -> None:
        async with self._lock:
            try:
                self._waiters.remove(waiter)
            except ValueError:
                # The slot was assigned just before timeout or cancellation.
                if not waiter.cancelled() and waiter.done():
                    self._active = max(0, self._active - 1)
                    self._wake_next()

    async def release(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)
            self._wake_next()

    def _wake_next(self) -> None:
        while self._waiters:
            waiter = self._waiters.popleft()
            if waiter.cancelled():
                continue
            self._active += 1
            waiter.set_result(None)
            return

    @property
    def active_count(self) -> int:
        return self._active

    @property
    def waiting_count(self) -> int:
        return len(self._waiters)


@dataclass
class _EventWindow:
    started_at: float
    emitted: int = 0
    suppressed: int = 0


class BoundedEventSampler:
    """Rate-limit repetitive diagnostics while retaining a suppression count."""

    def __init__(
        self,
        *,
        max_keys: int = 32,
        window_seconds: float = 60.0,
        events_per_window: int = 10,
    ) -> None:
        self.max_keys = max(1, max_keys)
        self.window_seconds = max(1.0, window_seconds)
        self.events_per_window = max(1, events_per_window)
        self._events: OrderedDict[str, _EventWindow] = OrderedDict()
        self._lock = RLock()

    def should_log(self, category: str, *, now: float) -> tuple[bool, int]:
        """Return whether to emit and how many prior events were suppressed."""
        with self._lock:
            event = self._events.get(category)
            if event is not None and now - event.started_at >= self.window_seconds:
                suppressed = event.suppressed
                event.started_at = now
                event.emitted = 0
                event.suppressed = 0
            else:
                suppressed = 0
            if event is None:
                if len(self._events) >= self.max_keys:
                    expired = next(
                        (
                            key for key, value in self._events.items()
                            if now - value.started_at >= self.window_seconds
                        ),
                        None,
                    )
                    if expired is None:
                        return False, 0
                    self._events.pop(expired, None)
                event = _EventWindow(started_at=now)
                self._events[category] = event
            self._events.move_to_end(category)
            if event.emitted < self.events_per_window:
                event.emitted += 1
                return True, suppressed
            event.suppressed += 1
            return False, 0


@dataclass
class _DualRateBucket:
    last_updated: float
    last_seen: float
    window_tokens: float
    burst_tokens: float
    window_seconds: float
    window_limit: int
    burst_seconds: float
    burst_limit: int

    @classmethod
    def create(
        cls,
        now: float,
        *,
        window_seconds: float,
        window_limit: int,
        burst_seconds: float,
        burst_limit: int,
    ) -> _DualRateBucket:
        return cls(
            last_updated=now,
            last_seen=now,
            window_tokens=float(window_limit),
            burst_tokens=float(burst_limit),
            window_seconds=window_seconds,
            window_limit=window_limit,
            burst_seconds=burst_seconds,
            burst_limit=burst_limit,
        )

    def update_policy(
        self,
        now: float,
        *,
        window_seconds: float,
        window_limit: int,
        burst_seconds: float,
        burst_limit: int,
    ) -> None:
        self.refill(now)
        if (self.window_seconds, self.window_limit) != (window_seconds, window_limit):
            self.window_tokens = min(float(window_limit), self.window_tokens)
            self.window_seconds = window_seconds
            self.window_limit = window_limit
        if (self.burst_seconds, self.burst_limit) != (burst_seconds, burst_limit):
            self.burst_tokens = min(float(burst_limit), self.burst_tokens)
            self.burst_seconds = burst_seconds
            self.burst_limit = burst_limit
        self.last_seen = now

    def refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.last_updated)
        self.window_tokens = min(
            float(self.window_limit),
            self.window_tokens + elapsed * self.window_limit / self.window_seconds,
        )
        self.burst_tokens = min(
            float(self.burst_limit),
            self.burst_tokens + elapsed * self.burst_limit / self.burst_seconds,
        )
        self.last_updated = max(self.last_updated, now)

    def deny_diagnostics(self) -> dict[str, int | str] | None:
        if self.window_tokens < 1.0:
            return {
                "category": "client_rate",
                "reason": "window_limit",
                "count": min(self.window_limit, ceil(self.window_limit - self.window_tokens)),
                "limit": self.window_limit,
            }
        if self.burst_tokens < 1.0:
            return {
                "category": "client_rate",
                "reason": "burst_limit",
                "count": min(self.burst_limit, ceil(self.burst_limit - self.burst_tokens)),
                "limit": self.burst_limit,
            }
        return None

    def consume(self, now: float) -> None:
        self.refill(now)
        self.window_tokens = max(0.0, self.window_tokens - 1.0)
        self.burst_tokens = max(0.0, self.burst_tokens - 1.0)
        self.last_seen = now


class BoundedRequestLimiter:
    """Bounded per-client token buckets with an exact crawler rolling window."""

    OVERFLOW_KEY = "__overflow__"

    def __init__(self, *, max_clients: int = 4096, idle_ttl: float = 120.0) -> None:
        self.max_clients = max(1, max_clients)
        self.idle_ttl = idle_ttl
        self._times: OrderedDict[tuple[str, str], _DualRateBucket] = OrderedDict()
        self._crawler_times: dict[tuple[str, str], deque[float]] = {}
        self._lock = RLock()

    def allow(
        self,
        client: str,
        *,
        now: float,
        window_seconds: float,
        window_limit: int,
        burst_seconds: float,
        burst_limit: int,
        strict_sliding_window: bool = False,
    ) -> bool:
        allowed, _ = self.allow_with_diagnostics(
            client,
            now=now,
            window_seconds=window_seconds,
            window_limit=window_limit,
            burst_seconds=burst_seconds,
            burst_limit=burst_limit,
            strict_sliding_window=strict_sliding_window,
        )
        return allowed

    def allow_with_diagnostics(
        self,
        client: str,
        *,
        now: float,
        window_seconds: float,
        window_limit: int,
        burst_seconds: float,
        burst_limit: int,
        strict_sliding_window: bool = False,
    ) -> tuple[bool, dict[str, int | str]]:
        """Check a quota and return bounded, identity-free denial metadata."""
        policy = "crawler" if strict_sliding_window else "human"
        overflow_policy = "all" if self.max_clients == 1 else policy
        overflow_key = (self.OVERFLOW_KEY, overflow_policy)
        client_key = (client, policy)
        with self._lock:
            self._prune(now)
            bucket = self._times.get(client_key)
            category = "client_rate"
            overflowed = False
            if bucket is None:
                # Reserve one overflow bucket for each policy so a crawler at
                # a shared peer cannot spend the human visitors' quota state.
                regular_capacity = max(0, self.max_clients - min(self.max_clients, 2))
                if client == self.OVERFLOW_KEY:
                    bucket = self._times.get(overflow_key)
                    client_key = overflow_key
                elif len(self._times) < regular_capacity:
                    bucket = _DualRateBucket.create(
                        now,
                        window_seconds=window_seconds,
                        window_limit=window_limit,
                        burst_seconds=burst_seconds,
                        burst_limit=burst_limit,
                    )
                    self._times[client_key] = bucket
                else:
                    bucket = self._times.get(overflow_key)
                    client_key = overflow_key
                    overflowed = True
                if bucket is None:
                    bucket = _DualRateBucket.create(
                        now,
                        window_seconds=window_seconds,
                        window_limit=window_limit,
                        burst_seconds=burst_seconds,
                        burst_limit=burst_limit,
                    )
                    self._times[client_key] = bucket
            bucket.update_policy(
                now,
                window_seconds=window_seconds,
                window_limit=window_limit,
                burst_seconds=burst_seconds,
                burst_limit=burst_limit,
            )
            category = "client_state_capacity" if overflowed else "client_rate"
            crawler_bucket: deque[float] | None = None
            if strict_sliding_window:
                crawler_bucket = self._crawler_times.setdefault(client_key, deque())
                while crawler_bucket and crawler_bucket[0] < now - window_seconds:
                    crawler_bucket.popleft()
                crawler_burst_count = sum(
                    timestamp >= now - burst_seconds for timestamp in crawler_bucket
                )
                if (
                    len(crawler_bucket) >= window_limit
                    or crawler_burst_count >= burst_limit
                ):
                    exceeded_window = len(crawler_bucket) >= window_limit
                    return False, {
                        "category": category,
                        "reason": "window_limit" if exceeded_window else "burst_limit",
                        "count": len(crawler_bucket) if exceeded_window else crawler_burst_count,
                        "limit": window_limit if exceeded_window else burst_limit,
                    }
            diagnostics = bucket.deny_diagnostics()
            if diagnostics is not None:
                bucket.last_seen = now
                diagnostics["category"] = category
                return False, diagnostics
            bucket.consume(now)
            if crawler_bucket is not None:
                crawler_bucket.append(now)
            self._times.move_to_end(client_key)
            return True, {
                "category": "",
                "reason": "",
                "count": max(0, ceil(window_limit - bucket.window_tokens)),
                "limit": window_limit,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._times)

    def _prune(self, now: float) -> None:
        expired = [
            key for key, bucket in self._times.items()
            if now - bucket.last_seen >= self.idle_ttl
        ]
        for key in expired:
            self._times.pop(key, None)
            self._crawler_times.pop(key, None)


def parse_trusted_proxy_cidrs(
    value: str | None,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse explicit proxy CIDRs. Empty configuration trusts no proxy headers."""
    if not value or not value.strip():
        return ()
    networks = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        network = ipaddress.ip_network(item, strict=False)
        if network.prefixlen == 0:
            raise ValueError("trusted proxy CIDRs must not include a blanket wildcard")
        networks.append(network)
    return tuple(networks)


def _is_trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address, networks) -> bool:
    return any(address.version == network.version and address in network for network in networks)


def resolve_client_ip(
    peer: str | None,
    forwarded_for: str | None,
    trusted_proxy_cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> str:
    """Resolve a client only through a validated chain of explicitly trusted peers."""
    fallback = peer or "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer or "")
    except ValueError:
        return fallback
    if not forwarded_for or not _is_trusted(peer_ip, trusted_proxy_cidrs):
        return str(peer_ip)
    # Bound parsing work and reject the entire header if any hop is malformed.
    if len(forwarded_for) > 2048:
        return str(peer_ip)
    try:
        chain = [ipaddress.ip_address(part.strip()) for part in forwarded_for.split(",")]
    except ValueError:
        return str(peer_ip)
    if not chain or len(chain) > 32:
        return str(peer_ip)
    candidate = chain[-1]
    # XFF is client, proxy1, ..., proxyN. Walk from the nearest hop outward;
    # stop at the first address not in our explicit trusted-proxy set.
    for hop in reversed(chain):
        if _is_trusted(hop, trusted_proxy_cidrs):
            continue
        candidate = hop
        break
    else:
        candidate = chain[0]
    return str(candidate)


def trusted_forwarded_scheme(
    peer: str | None,
    forwarded_proto: str | None,
    trusted_proxy_cidrs: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> str | None:
    """Return a validated forwarded scheme only when the direct peer is trusted."""
    try:
        peer_ip = ipaddress.ip_address(peer or "")
    except ValueError:
        return None
    if not _is_trusted(peer_ip, trusted_proxy_cidrs):
        return None
    if forwarded_proto and forwarded_proto.strip().lower() in {"http", "https"}:
        return forwarded_proto.strip().lower()
    return None

from __future__ import annotations

import asyncio
import ipaddress
import sys
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, fields, is_dataclass
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


class AsyncLockRegistry[K]:
    """Fixed-size async single-flight stripes with no cancellation leaks."""

    def __init__(self, *, stripes: int = 256) -> None:
        self._entries = tuple(asyncio.Lock() for _ in range(stripes))

    @asynccontextmanager
    async def hold(self, key: K):
        lock = self._entries[hash(key) % len(self._entries)]
        async with lock:
            yield

    def __len__(self) -> int:
        return len(self._entries)


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
        elif hasattr(item, "__dict__"):
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


class BoundedRequestLimiter:
    """Per-client sliding-window limiter with bounded, non-evicting records."""

    OVERFLOW_KEY = "__overflow__"

    def __init__(self, *, max_clients: int = 4096, idle_ttl: float = 120.0) -> None:
        self.max_clients = max(1, max_clients)
        self.idle_ttl = idle_ttl
        self._times: OrderedDict[str, deque[float]] = OrderedDict()
        self._last_seen: dict[str, float] = {}
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
    ) -> bool:
        allowed, _ = self.allow_with_diagnostics(
            client,
            now=now,
            window_seconds=window_seconds,
            window_limit=window_limit,
            burst_seconds=burst_seconds,
            burst_limit=burst_limit,
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
    ) -> tuple[bool, dict[str, int | str]]:
        """Check a quota and return bounded, identity-free denial metadata."""
        with self._lock:
            self._prune(now)
            bucket = self._times.get(client)
            category = "client_rate"
            overflowed = False
            if bucket is None:
                regular_capacity = max(0, self.max_clients - 1)
                if client == self.OVERFLOW_KEY:
                    bucket = self._times.setdefault(self.OVERFLOW_KEY, deque())
                elif len(self._times) < regular_capacity:
                    bucket = deque()
                    self._times[client] = bucket
                else:
                    # New identities share a fail-closed quota until existing records age out.
                    bucket = self._times.setdefault(self.OVERFLOW_KEY, deque())
                    client = self.OVERFLOW_KEY
                    overflowed = True
            while bucket and bucket[0] < now - window_seconds:
                bucket.popleft()
            burst_count = sum(timestamp >= now - burst_seconds for timestamp in bucket)
            if overflowed:
                category = "client_state_capacity"
            if len(bucket) >= window_limit or burst_count >= burst_limit:
                self._last_seen[client] = now
                exceeded = "window" if len(bucket) >= window_limit else "burst"
                return False, {
                    "category": category,
                    "reason": f"{exceeded}_limit",
                    "count": len(bucket) if exceeded == "window" else burst_count,
                    "limit": window_limit if exceeded == "window" else burst_limit,
                }
            bucket.append(now)
            self._last_seen[client] = now
            self._times.move_to_end(client)
            return True, {"category": "", "reason": "", "count": len(bucket), "limit": window_limit}

    def __len__(self) -> int:
        with self._lock:
            return len(self._times)

    def _prune(self, now: float) -> None:
        expired = [
            key for key, seen in self._last_seen.items()
            if now - seen >= self.idle_ttl and (not self._times.get(key))
        ]
        for key in expired:
            self._last_seen.pop(key, None)
            self._times.pop(key, None)
        # Active records with no recent timestamps may remain only up to the window cap;
        # prune old timestamps before considering whether an identity is idle.
        for key, bucket in list(self._times.items()):
            while bucket and bucket[0] < now - max(self.idle_ttl, 120.0):
                bucket.popleft()
            if not bucket and now - self._last_seen.get(key, now) >= self.idle_ttl:
                self._times.pop(key, None)
                self._last_seen.pop(key, None)


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

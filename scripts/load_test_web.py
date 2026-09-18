"""Small mixed-route load probe for local dashboard verification.

This is a local capacity signal, not a substitute for a deployed-environment test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import time
from collections import Counter

import httpx

PATHS = (
    "/",
    "/forecast",
    "/forecast?date=2026-09-17&race_id=28889",
    "/validation",
    "/analysis",
    "/races/28889",
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


async def sample_process(pid: int, stop: asyncio.Event, samples: list[tuple[int, float]]) -> None:
    while not stop.is_set():
        result = await asyncio.to_thread(
            subprocess.run,
            ["ps", "-o", "rss=,pcpu=", "-p", str(pid)],
            capture_output=True,
            check=False,
            text=True,
        )
        parts = result.stdout.split()
        if len(parts) == 2:
            samples.append((int(parts[0]), float(parts[1])))
        await asyncio.sleep(0.05)


async def run(base_url: str, requests: int, concurrency: int, pid: int | None) -> dict:
    semaphore = asyncio.Semaphore(concurrency)
    timings: list[float] = []
    statuses: Counter[int | str] = Counter()
    stop = asyncio.Event()
    samples: list[tuple[int, float]] = []
    sampler = asyncio.create_task(sample_process(pid, stop, samples)) if pid else None
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)

    async with httpx.AsyncClient(base_url=base_url, timeout=30, limits=limits) as client:

        async def fetch(index: int) -> None:
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(PATHS[index % len(PATHS)])
                    statuses[response.status_code] += 1
                except Exception as exc:  # noqa: BLE001 - load result records transport failures
                    statuses[type(exc).__name__] += 1
                timings.append((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        await asyncio.gather(*(fetch(index) for index in range(requests)))
        elapsed = time.perf_counter() - started
    stop.set()
    if sampler:
        await sampler
    errors = sum(count for status, count in statuses.items() if status != 200)
    return {
        "requests": requests,
        "concurrent_clients": concurrency,
        "duration_seconds": round(elapsed, 3),
        "requests_per_second": round(requests / elapsed, 1),
        "latency_ms": {
            "median": round(statistics.median(timings), 1),
            "p95": round(percentile(timings, 0.95), 1),
            "max": round(max(timings), 1),
        },
        "statuses": dict(statuses),
        "error_rate": round(errors / requests, 5),
        "server_peak_rss_mib": round(max((row[0] for row in samples), default=0) / 1024, 1),
        "server_peak_cpu_percent": max((row[1] for row in samples), default=0),
        "paths": list(PATHS),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--server-pid", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(run(args.base_url, args.requests, args.concurrency, args.server_pid)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Exercise a seeded local web app with 100 clients sharing one peer IP.

Run from an empty scratch directory with the repository's test environment,
for example:

    python /path/to/repo/scripts/verify_shared_ip_load.py --scratch /tmp/load-check

This creates only a SQLite database under the requested scratch directory. It
does not call production data sources or network services.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import re
import threading
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.db.base import Base
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RunningTrial,
    RunningTrialResult,
)
from horse_racing.web.database import create_web_session_factory

_PEER_IP = "198.51.100.80"
_DESKTOP_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Chrome/128 Safari/537.36"
_MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"


class _SessionTracker:
    def __init__(self, factory: sessionmaker[Session], *, simulated_latency_seconds: float) -> None:
        self.factory = factory
        self.simulated_latency_seconds = simulated_latency_seconds
        self._lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0

    @contextmanager
    def __call__(self):
        with self._lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        try:
            with self.factory() as session:
                if self.simulated_latency_seconds:
                    time.sleep(self.simulated_latency_seconds)
                yield session
        finally:
            with self._lock:
                self.active -= 1


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((percentile / 100) * (len(ordered) - 1))))
    return round(ordered[index], 2)


def _seed_database(path: Path) -> tuple[sessionmaker[Session], Any, list[int]]:
    engine = create_engine_for_url(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        horses = [
            Horse(kra_horse_id=f"load-{index:03d}", name_ko=f"부하검증마{index:02d}")
            for index in range(1, 21)
        ]
        session.add_all([course, *horses])
        session.flush()

        race_days = [date(2026, 7, 31), date(2026, 8, 7), date(2026, 8, 14)]
        history_races = [
            Race(
                racecourse=course,
                race_date_local=race_day,
                race_number=1,
                distance_m=1400,
                grade="제6등급",
                race_name="시드 과거경주",
                field_size=10,
                status="completed",
            )
            for race_day in race_days
        ]
        main_races = [
            Race(
                racecourse=course,
                race_date_local=date(2026, 8, 21),
                race_number=number,
                distance_m=(1400, 1600, 1800)[number % 3],
                grade="제6등급",
                race_name=f"로컬 부하검증 {number}경주",
                field_size=10,
                status="completed",
            )
            for number in range(1, 11)
        ]
        session.add_all([*history_races, *main_races])
        session.flush()

        # Each detail page has a realistic field, and the shared horse pool has
        # a few past finishes for the recent-form query used by the page.
        for race_index, race in enumerate([*history_races, *main_races]):
            for horse_number in range(1, 11):
                horse = horses[(race_index + horse_number - 1) % len(horses)]
                entry = RaceEntry(
                    race=race,
                    horse=horse,
                    horse_number=horse_number,
                    gate_number=horse_number,
                    carried_weight_kg=54.0 + horse_number / 10,
                    body_weight_kg=470 + horse_number,
                    rating=30 + horse_number,
                )
                session.add(RaceResult(
                    race_entry=entry,
                    finish_position=horse_number,
                    finish_time_ms=88_000 + horse_number * 250,
                ))

        trial = RunningTrial(
            meet_code=1,
            trial_date_local=date(2026, 8, 14),
            trial_race_number=1,
            distance_m=800,
            observed_at_ms=1_800_000_000_000,
        )
        session.add(trial)
        for horse_number, horse in enumerate(horses[:10], start=1):
            session.add(RunningTrialResult(
                trial=trial,
                horse=horse,
                horse_number=horse_number,
                horse_name_raw=horse.name_ko,
                finish_position=horse_number,
                finish_time_ms=50_000 + horse_number * 100,
                observed_at_ms=1_800_000_000_000 + horse_number,
            ))
        session.commit()
        race_ids = [race.id for race in main_races]
    # Seed with collector privileges, then exercise the same guarded engine
    # used by the public web process rather than injecting a writable factory.
    engine.dispose()
    web_factory = create_web_session_factory(f"sqlite:///{path}")
    return web_factory, web_factory.kw["bind"], race_ids

async def run_shared_ip_load(
    scratch: str | Path,
    *,
    client_count: int = 100,
    simulated_latency_seconds: float = 0.004,
) -> dict[str, Any]:
    """Return measured status, latency, loader, and queue metrics."""
    scratch_path = Path(scratch).resolve()
    scratch_path.mkdir(parents=True, exist_ok=True)
    factory, engine, race_ids = _seed_database(scratch_path / "shared-ip-load.sqlite3")

    select_count = 0
    select_lock = threading.Lock()

    @event.listens_for(engine, "before_cursor_execute")
    def count_selects(_connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            with select_lock:
                select_count += 1

    app_module = importlib.import_module("horse_racing.web.app")
    loader_names = (
        "load_calendar_index",
        "load_dashboard",
        "load_race_page",
        "load_race_analysis_page",
    )
    loader_counts: Counter[str] = Counter()
    original_loaders = {name: getattr(app_module, name) for name in loader_names}
    loader_lock = threading.Lock()
    for name, loader in original_loaders.items():
        def counted_loader(*args, __name=name, __loader=loader, **kwargs):
            with loader_lock:
                loader_counts[__name] += 1
            return __loader(*args, **kwargs)

        setattr(app_module, name, counted_loader)

    tracker = _SessionTracker(factory, simulated_latency_seconds=simulated_latency_seconds)
    app = app_module.create_app(session_factory=tracker)
    transport = httpx.ASGITransport(app=app, client=(_PEER_IP, 48000))
    route_latencies: dict[str, list[float]] = defaultdict(list)
    route_statuses: dict[str, Counter[str]] = defaultdict(Counter)
    journey_latencies: dict[str, list[float]] = {"cold": [], "warm": []}
    phase_asset_count: Counter[str] = Counter()
    journey_completed: Counter[str] = Counter()
    request_total = 0
    home_assets: dict[str, list[str]] = {}
    asset_validators: dict[str, dict[str, str]] = {}

    async def get(
        client: httpx.AsyncClient,
        route_label: str,
        path: str,
        *,
        headers: dict[str, str],
    ) -> httpx.Response:
        nonlocal request_total
        started = time.perf_counter()
        response = await client.get(path, headers=headers)
        duration_ms = (time.perf_counter() - started) * 1000
        route_latencies[route_label].append(duration_ms)
        route_statuses[route_label][str(response.status_code)] += 1
        request_total += 1
        return response

    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://mapilog-load.test",
            timeout=40.0,
        ) as client:

            async def browser_journey(index: int, phase: str) -> None:
                started = time.perf_counter()
                layout_mode = index % 4
                if layout_mode == 0:
                    user_agent, layout, cookie = _MOBILE_UA, "mobile", ""
                elif layout_mode == 1:
                    user_agent, layout, cookie = _DESKTOP_UA, "mobile", "hr-layout=mobile"
                elif layout_mode == 2:
                    user_agent, layout, cookie = _MOBILE_UA, "desktop", "hr-layout=desktop"
                else:
                    user_agent, layout, cookie = _DESKTOP_UA, "desktop", ""
                headers = {"user-agent": user_agent}
                if cookie:
                    headers["cookie"] = cookie

                home = await get(client, f"{phase}:home", "/", headers=headers)
                if home.status_code != 200:
                    return
                static_urls = []
                for value in re.findall(r'(?:href|src)="([^"]+)"', home.text):
                    parsed = urlsplit(value)
                    if parsed.path.startswith("/static/"):
                        url = parsed.path + (f"?{parsed.query}" if parsed.query else "")
                        if url not in static_urls:
                            static_urls.append(url)
                home_assets[layout] = static_urls
                if index == 0:
                    assert static_urls, "mobile home should reference local CSS/JS assets"

                async def fetch_asset(url: str) -> httpx.Response:
                    conditional = asset_validators.get(url, {}) if phase == "warm" else {}
                    response = await get(
                        client, f"{phase}:asset", url, headers={**headers, **conditional}
                    )
                    if phase == "cold":
                        validators = {}
                        if response.headers.get("etag"):
                            validators["if-none-match"] = response.headers["etag"]
                        elif response.headers.get("last-modified"):
                            validators["if-modified-since"] = response.headers["last-modified"]
                        if validators:
                            asset_validators[url] = validators
                    return response

                assets = await asyncio.gather(*(fetch_asset(url) for url in static_urls))
                phase_asset_count[phase] += sum(
                    1 for response in assets if response.status_code == 200
                )

                calendar = await get(
                    client,
                    f"{phase}:calendar",
                    "/api/calendar?month=2026-08",
                    headers=headers,
                )
                guide = await get(client, f"{phase}:guide", "/guide", headers=headers)
                privacy = await get(client, f"{phase}:privacy", "/privacy", headers=headers)
                if calendar.status_code == 200:
                    assert [item["date"] for item in calendar.json()] == [
                        "2026-08-21", "2026-08-14", "2026-08-07",
                    ]
                if guide.status_code == 200:
                    assert "이용" in guide.text or "가이드" in guide.text
                if privacy.status_code == 200:
                    assert "개인정보" in privacy.text

                for offset in range(3):
                    race_id = race_ids[(index + offset) % len(race_ids)]
                    await get(
                        client,
                        f"{phase}:race_detail",
                        f"/races/{race_id}",
                        headers=headers,
                    )
                journey_latencies[phase].append((time.perf_counter() - started) * 1000)
                journey_completed[phase] += 1

            await asyncio.gather(*(
                browser_journey(index, "cold") for index in range(client_count)
            ))
            cold_loader_calls = dict(loader_counts)
            cold_select_count = select_count

            # Allow burst tokens to refill before repeating the same 100-client
            # journey against the now-warm process-local caches.
            await asyncio.sleep(10.1)
            await asyncio.gather(*(
                browser_journey(index, "warm") for index in range(client_count)
            ))
            warm_loader_calls = {
                name: loader_counts[name] - cold_loader_calls.get(name, 0)
                for name in loader_counts
            }
            warm_select_count = select_count - cold_select_count
            journey_statuses: dict[str, Counter[str]] = {"cold": Counter(), "warm": Counter()}
            for route, statuses in route_statuses.items():
                for phase in journey_statuses:
                    if route.startswith(f"{phase}:"):
                        journey_statuses[phase].update(statuses)

            # Confirm the layout query issues a private preference cookie and
            # keeps the browser-specific response out of shared HTTP caches.
            preference = await get(
                client,
                "layout_preference",
                "/?layout=mobile",
                headers={"user-agent": _DESKTOP_UA},
            )
            assert preference.status_code == 200
            assert "hr-layout=mobile" in preference.headers.get("set-cookie", "")
            assert preference.headers.get("cache-control") == "private, no-store"
            assert "cookie" in {
                item.strip().lower()
                for item in preference.headers.get("vary", "").split(",")
            }

            # Extra cookies and Authorization remain cache bypasses, while
            # the known layout-only cookie may share the private local variant.
            before = loader_counts["load_dashboard"]
            await get(
                client,
                "unknown_cookie_probe",
                "/",
                headers={"user-agent": _DESKTOP_UA, "cookie": "hr-layout=mobile; feature=1"},
            )
            await get(
                client,
                "authorization_probe",
                "/",
                headers={"user-agent": _DESKTOP_UA, "authorization": "Bearer local-test"},
            )
            cache_bypass_dashboard_loads = loader_counts["load_dashboard"] - before
            assert cache_bypass_dashboard_loads == 2

            # Browser revalidation must work with the same versioned asset URL.
            mobile_assets = home_assets.get("mobile", [])
            first_asset = mobile_assets[0] if mobile_assets else "/static/css/dashboard.css?v=19"
            asset_headers = {"user-agent": _MOBILE_UA}
            first = await get(client, "asset_revalidation", first_asset, headers=asset_headers)
            validator_headers: dict[str, str] = {}
            if first.headers.get("etag"):
                validator_headers["if-none-match"] = first.headers["etag"]
            elif first.headers.get("last-modified"):
                validator_headers["if-modified-since"] = first.headers["last-modified"]
            revalidated_status: int | None = None
            if validator_headers:
                second = await get(
                    client,
                    "asset_revalidation",
                    first_asset,
                    headers={**asset_headers, **validator_headers},
                )
                revalidated_status = second.status_code
            assert "max-age=3600" in first.headers.get("cache-control", "")
    finally:
        for name, loader in original_loaders.items():
            setattr(app_module, name, loader)

    total_statuses: Counter[str] = Counter()
    for statuses in route_statuses.values():
        total_statuses.update(statuses)
    all_latencies = [value for values in route_latencies.values() for value in values]
    statuses_with_errors = {
        status: count for status, count in total_statuses.items() if int(status) >= 400
    }
    return {
        "client_count": client_count,
        "peer_ip_count": 1,
        "shared_peer_ip": _PEER_IP,
        "journey_phases": {
            phase: {
                "request_count": sum(statuses.values()),
                "completed_browser_journeys": journey_completed[phase],
                "static_asset_200_count": phase_asset_count[phase],
                "status_counts": dict(sorted(statuses.items())),
                "429_count": statuses.get("429", 0),
                "error_status_counts": {
                    status: count for status, count in statuses.items() if int(status) >= 400
                },
                "p50_journey_ms": _percentile(journey_latencies[phase], 50),
                "p95_journey_ms": _percentile(journey_latencies[phase], 95),
                "loader_calls": cold_loader_calls if phase == "cold" else warm_loader_calls,
                "select_statements": cold_select_count if phase == "cold" else warm_select_count,
            }
            for phase, statuses in journey_statuses.items()
        },
        "all_requests_including_probes": request_total,
        "warm_phase_gap_seconds": 10.1,
        "route_request_counts": {
            route: sum(statuses.values()) for route, statuses in sorted(route_statuses.items())
        },
        "status_counts": dict(sorted(total_statuses.items())),
        "error_status_counts": statuses_with_errors,
        "rate_limit_429_count": total_statuses.get("429", 0),
        "p50_ms": {
            "request": _percentile(all_latencies, 50),
            "journey": _percentile([*journey_latencies["cold"], *journey_latencies["warm"]], 50),
        },
        "p95_ms": {
            "request": _percentile(all_latencies, 95),
            "journey": _percentile([*journey_latencies["cold"], *journey_latencies["warm"]], 95),
        },
        "per_route_ms": {
            route: {
                "p50": _percentile(values, 50),
                "p95": _percentile(values, 95),
                "requests": len(values),
            }
            for route, values in sorted(route_latencies.items())
        },
        "database": {
            "database_kind": "seeded local SQLite",
            "web_read_only_guard": True,
            "select_statements": select_count,
            "max_active_session_contexts": tracker.maximum_active,
            "configured_admission_limit": 3,
            "simulated_session_hold_latency_ms": round(simulated_latency_seconds * 1000, 2),
        },
        "loader_calls": dict(sorted(loader_counts.items())),
        "layout_cache_bypass_dashboard_loader_calls": cache_bypass_dashboard_loads,
        "asset_revalidation_status": revalidated_status,
        "asset_cache_control": first.headers.get("cache-control"),
        "home_asset_counts_by_layout": {
            layout: len(urls) for layout, urls in sorted(home_assets.items())
        },
        "scope_note": (
            "Offline ASGI/SQLite capacity check only. It does not prove Cloud Run request "
            "queue behavior, PostgreSQL latency, or Supabase connection capacity."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", required=True, help="local writable scratch directory")
    parser.add_argument("--clients", type=int, default=100)
    parser.add_argument("--simulated-session-latency-ms", type=float, default=4.0)
    args = parser.parse_args()
    if not 100 <= args.clients <= 250:
        parser.error("--clients must be between 100 and 250")
    result = asyncio.run(
        run_shared_ip_load(
            args.scratch,
            client_count=args.clients,
            simulated_latency_seconds=args.simulated_session_latency_ms / 1000,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

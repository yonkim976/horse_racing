"""Collect all API309 regions into Supabase; --apply required, no SQLite or notifications."""

import argparse
import json
import time
from datetime import datetime

from sqlalchemy.orm import Session

from horse_racing.db.engine import create_engine_for_url
from horse_racing.jobs import local_race_day as live
from horse_racing.jobs.canonical_post_race import write_json
from horse_racing.jobs.weekly_entry_cards import KST
from horse_racing.services.owner_catalog import fetch_catalog, persist_catalog


def execute(*, apply=False):
    if not apply:
        print(
            json.dumps(
                dict(
                    apply=False,
                    meets=[1, 3, 2],
                    sqlite_writes=False,
                    notifications=False,
                    deployments=False,
                )
            )
        )
        return 0
    started = time.time_ns() // 1_000_000
    settings = live.load_settings()
    directory = (
        live.ROOT
        / "data/research"
        / f"owner_catalog_{datetime.now(KST):%Y%m%d_%H%M%S}_{time.time_ns()}"
    )
    directory.mkdir(mode=0o700)
    with live.LocalKraApiClient(settings.data_go_kr_service_key.get_secret_value()) as client:
        client._client.follow_redirects = False
        observations, evidence = fetch_catalog(
            client, directory, observed_on=datetime.now(KST).date()
        )
    write_json(directory / "sources.json", evidence)
    engine = create_engine_for_url(settings.database_url)
    try:
        with Session(engine) as session, session.begin():
            summary = persist_catalog(session, observations, evidence, started_at_ms=started)
    finally:
        engine.dispose()
    write_json(directory / "report.json", summary)
    print(json.dumps({**summary, "evidence_directory": str(directory)}, ensure_ascii=False))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        return execute(apply=args.apply)
    except Exception as exc:
        print(json.dumps(dict(status="failed", error_type=type(exc).__name__)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

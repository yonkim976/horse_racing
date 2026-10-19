"""Refresh official rider classifications for upcoming runners; default is a plan."""

import argparse
import json
import time
from datetime import date

import httpx
from sqlalchemy.orm import Session

from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url
from horse_racing.services.training_riders_website import (
    ingest_training_riders,
    upcoming_training_horses,
)
from horse_racing.web.formatting import today_seoul


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--race-id", type=int, action="append", default=[])
    parser.add_argument("--horse-id", action="append", default=[])
    parser.add_argument("--as-of", type=date.fromisoformat, default=today_seoul())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"apply": False, "race_ids": args.race_id, "as_of": str(args.as_of)}))
        return
    settings = get_settings()
    engine = create_engine_for_url(settings.database_url)
    failures, results = 0, []
    try:
        with Session(engine, expire_on_commit=False) as session:
            horses = upcoming_training_horses(session, as_of=args.as_of, race_ids=args.race_id)
            if args.horse_id:
                horses = [h for h in horses if h.kra_horse_id in args.horse_id]
            session.rollback()
            if len(horses) > 500:
                raise ValueError("Upcoming runner scope exceeds 500 profile pages")
            with httpx.Client(
                timeout=25, headers={"User-Agent": "HorseRacingCollector/1.0"}
            ) as client:
                for horse in horses:
                    try:
                        result = ingest_training_riders(
                            session,
                            client,
                            horse=horse,
                            as_of=args.as_of,
                            raw_data_dir=settings.raw_data_dir,
                        )
                    except Exception as exc:
                        session.rollback()
                        failures += 1
                        result = {"horse": horse.kra_horse_id, "error_type": type(exc).__name__}
                    results.append(result)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    time.sleep(0.2)
        print(
            json.dumps(
                {
                    "profiles": len(results),
                    "matched": sum(r.get("matched", 0) for r in results),
                    "failures": failures,
                }
            ),
            flush=True,
        )
    finally:
        engine.dispose()
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

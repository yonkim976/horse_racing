"""Project saved API78 cards into official equipment +/- rows.

Only the latest saved page per (race date, meet) is used. Source JSON is
verified against source_documents.sha256 before any database write. No network
request is made. Run with --target local or --target remote --apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import SourceDocument
from horse_racing.parsers.gate_entry_sheet import parse_gate_entry_sheet_page
from horse_racing.services.gate_entry_sheet import _write_gate_numbers

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "remote"), required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.target == "local":
        database_url = f"sqlite:///{ROOT / 'data/horse_racing.sqlite3'}"
    else:
        database_url = get_settings().database_url
        if not database_url.startswith("postgresql"):
            raise SystemExit("remote target requires a PostgreSQL database URL")

    engine = create_engine_for_url(database_url)
    try:
        with Session(engine) as session:
            documents = session.scalars(
                select(SourceDocument)
                .where(SourceDocument.endpoint == "/API78/chulmainfo")
                .order_by(SourceDocument.retrieved_at_ms, SourceDocument.id)
            ).all()
            latest: dict[tuple[int, str], SourceDocument] = {}
            for document in documents:
                params = json.loads(document.request_params_json)
                latest[(int(params["rccrs_cd"]), str(params["race_dt"]))] = document

            prepared = []
            for (meet, race_date), document in sorted(latest.items()):
                path = Path(document.local_path)
                if not path.is_absolute():
                    path = ROOT / path
                body = path.read_bytes()
                if hashlib.sha256(body).hexdigest() != document.sha256:
                    raise ValueError(f"API78 source hash mismatch: document {document.id}")
                page = parse_gate_entry_sheet_page(json.loads(body))
                if any(item.race_date.strftime("%Y%m%d") != race_date for item in page.items):
                    raise ValueError(f"API78 source date mismatch: document {document.id}")
                prepared.append((meet, race_date, document.retrieved_at_ms, page.items))

            print(
                f"target={args.target} source_pages={len(documents)} "
                f"latest_cards={len(prepared)}"
            )
            print(f"runner_rows={sum(len(items) for _, _, _, items in prepared)}")
            if not args.apply:
                print("dry run only; pass --apply to save the cards and +/- marks")
                return

            written = 0
            for meet, _race_date, observed_at_ms, items in prepared:
                written += _write_gate_numbers(
                    session, meet=meet, items=items, observed_at_ms=observed_at_ms
                )
                session.commit()
            print(f"runner_rows_written={written}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

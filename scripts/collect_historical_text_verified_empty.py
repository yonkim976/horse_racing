"""Resume a KRA Text archive, accepting a 0-byte source only after three HTTP 200 reads."""

from __future__ import annotations

import argparse
from datetime import date

from horse_racing.collectors.kra_text import (
    TEXT_FILE_TYPES,
    FetchedTextReport,
    KraTextClient,
    KraTextError,
    KraTextFile,
)
from horse_racing.config import get_settings
from horse_racing.db.session import SessionLocal
from horse_racing.services.text_archive import download_text_archive


class VerifiedEmptyKraTextClient(KraTextClient):
    """Distinguish persistent missing source content from a single empty response."""

    def fetch_file(self, file: KraTextFile, *, allow_empty: bool = False) -> FetchedTextReport:
        if allow_empty:
            return super().fetch_file(file, allow_empty=True)
        try:
            return super().fetch_file(file)
        except KraTextError as exc:
            if not str(exc).startswith("KRA Text 파일이 비어 있습니다:"):
                raise
        confirmed: FetchedTextReport | None = None
        for _ in range(2):
            confirmed = super().fetch_file(file, allow_empty=True)
            if confirmed.body:
                return confirmed
        assert confirmed is not None
        print(f"verified_empty_source: {file.remote_path}", flush=True)
        return confirmed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-type", required=True, choices=TEXT_FILE_TYPES)
    parser.add_argument("--meets", nargs="+", type=int, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--delay-ms", type=int, default=500)
    args = parser.parse_args()
    settings = get_settings()
    with VerifiedEmptyKraTextClient(timeout_seconds=60) as client, SessionLocal() as session:
        summary = download_text_archive(
            session,
            client,
            file_type=args.file_type,
            code_name=TEXT_FILE_TYPES[args.file_type],
            meets=args.meets,
            raw_data_dir=settings.raw_data_dir,
            start_date=args.start,
            end_date=args.end,
            max_pages=2000,
            delay_seconds=args.delay_ms / 1000,
        )
    print(summary)


if __name__ == "__main__":
    main()

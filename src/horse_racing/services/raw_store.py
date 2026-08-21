from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from horse_racing.collectors.kra_api import FetchedPage


@dataclass(frozen=True, slots=True)
class StoredRawDocument:
    path: Path
    sha256: str


def store_entry_sheet_page(
    fetched: FetchedPage,
    *,
    raw_data_dir: Path,
    race_date: str,
    meet: int,
    run_id: int,
    page_no: int,
) -> StoredRawDocument:
    return store_kra_page(
        fetched,
        raw_data_dir=raw_data_dir,
        data_type="entry_sheet",
        race_date=race_date,
        meet=meet,
        run_id=run_id,
        page_no=page_no,
    )


def store_kra_page(
    fetched: FetchedPage,
    *,
    raw_data_dir: Path,
    data_type: str,
    race_date: str,
    meet: int,
    run_id: int,
    page_no: int,
) -> StoredRawDocument:
    digest = hashlib.sha256(fetched.body).hexdigest()
    target_dir = (
        raw_data_dir
        / "kra"
        / data_type
        / race_date[:4]
        / race_date[4:6]
        / race_date[6:8]
        / f"meet_{meet}"
        / f"run_{run_id}"
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"page_{page_no:04d}_{fetched.retrieved_at_ms}_{digest[:12]}.json"
    target_path = target_dir / filename
    target_path.write_bytes(fetched.body)
    return StoredRawDocument(path=target_path, sha256=digest)

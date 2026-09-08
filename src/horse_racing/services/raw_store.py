from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from horse_racing.collectors.kra_api import FetchedPage
from horse_racing.collectors.kra_text import FetchedTextReport, KraTextFile


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


def store_kra_text_report(
    fetched: FetchedTextReport,
    *,
    raw_data_dir: Path,
) -> StoredRawDocument:
    digest = hashlib.sha256(fetched.body).hexdigest()
    target_dir = kra_text_report_path(fetched.file, raw_data_dir=raw_data_dir).parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / fetched.file.filename
    temporary_path = target_path.with_suffix(f"{target_path.suffix}.part")
    temporary_path.write_bytes(fetched.body)
    temporary_path.replace(target_path)
    return StoredRawDocument(path=target_path, sha256=digest)


def kra_text_report_path(file: KraTextFile, *, raw_data_dir: Path) -> Path:
    target_dir = raw_data_dir / "kra_text" / file.file_type / f"meet={file.meet}"
    if file.file_date is None:
        target_dir = target_dir / "year=unknown"
    else:
        target_dir = (
            target_dir
            / f"year={file.file_date.year:04d}"
            / f"month={file.file_date.month:02d}"
            / f"day={file.file_date.day:02d}"
        )
    return target_dir / file.filename

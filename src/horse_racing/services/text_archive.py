from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.collectors.kra_text import KraTextClient, KraTextFile
from horse_racing.db.models import IngestionRun, SourceDocument
from horse_racing.services.raw_store import kra_text_report_path, store_kra_text_report


@dataclass(frozen=True, slots=True)
class TextArchiveDownloadSummary:
    run_id: int
    files_discovered: int
    files_fetched: int
    files_written: int
    files_skipped: int
    bytes_fetched: int
    manifest_path: Path


def download_text_archive(
    session: Session,
    client: KraTextClient,
    *,
    file_type: str,
    code_name: str,
    meets: list[int],
    raw_data_dir: Path,
    start_date: date | None = None,
    end_date: date | None = None,
    max_pages: int = 500,
    max_files: int | None = None,
    delay_seconds: float = 0.1,
) -> TextArchiveDownloadSummary:
    """Download one KRA Text category with a durable append-only manifest."""
    if not meets or any(meet not in {1, 2, 3} for meet in meets):
        raise ValueError("meets에는 1(서울), 2(제주), 3(부산경남)만 사용할 수 있습니다.")
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValueError("종료일이 시작일보다 앞설 수 없습니다.")
    if max_files is not None and max_files < 1:
        raise ValueError("max_files는 1 이상이어야 합니다.")
    if delay_seconds < 0:
        raise ValueError("delay_seconds는 0 이상이어야 합니다.")

    manifest_path = raw_data_dir / "kra_text" / "_manifests" / file_type / "manifest.jsonl"
    manifest = _TextManifest(manifest_path)
    known_digests = manifest.known_digests()
    run = IngestionRun(
        source="race.kra.co.kr/dbdata",
        data_type=f"kra_text_{file_type}",
        started_at_ms=_now_ms(),
        status="running",
    )
    session.add(run)
    session.commit()

    discovered = 0
    fetched_count = 0
    written = 0
    skipped = 0
    bytes_fetched = 0
    try:
        stop = False
        for meet in dict.fromkeys(meets):
            for listed_file in client.iter_files(
                meet=meet,
                file_type=file_type,
                code_name=code_name,
                start_date=start_date,
                end_date=end_date,
                max_pages=max_pages,
            ):
                if max_files is not None and discovered >= max_files:
                    stop = True
                    break
                discovered += 1
                base_event = _file_event(run.id, listed_file)
                manifest.append({**base_event, "status": "discovered"})

                target_path = kra_text_report_path(listed_file, raw_data_dir=raw_data_dir)
                if target_path.is_file() and target_path.stat().st_size > 0:
                    digest = _sha256_file(target_path)
                    known_digests.setdefault(digest, target_path)
                    _ensure_source_document_for_existing_file(
                        session,
                        run_id=run.id,
                        file_type=file_type,
                        code_name=code_name,
                        listed_file=listed_file,
                        target_path=target_path,
                        digest=digest,
                    )
                    session.commit()
                    manifest.append(
                        {
                            **base_event,
                            "status": "skipped_existing",
                            "local_path": str(target_path),
                            "sha256": digest,
                            "response_bytes": target_path.stat().st_size,
                        }
                    )
                    skipped += 1
                    continue

                try:
                    fetched = client.fetch_file(listed_file)
                except Exception as exc:
                    manifest.append({**base_event, "status": "failed", "error": str(exc)[:2000]})
                    raise
                fetched_count += 1
                bytes_fetched += len(fetched.body)
                digest = hashlib.sha256(fetched.body).hexdigest()
                canonical_path = known_digests.get(digest)
                if canonical_path is not None and canonical_path.is_file():
                    stored_path = canonical_path
                    event_status = "skipped_duplicate_sha256"
                    skipped += 1
                else:
                    stored = store_kra_text_report(fetched, raw_data_dir=raw_data_dir)
                    stored_path = stored.path
                    digest = stored.sha256
                    known_digests[digest] = stored_path
                    event_status = "downloaded"
                    written += 1

                session.add(
                    SourceDocument(
                        ingestion_run_id=run.id,
                        source_url=fetched.source_url,
                        endpoint="/dbdata/fileDownLoad.do",
                        operation=file_type,
                        request_params_json=json.dumps(
                            {
                                "meet": meet,
                                "fn": listed_file.remote_path,
                                "list_page": listed_file.list_page,
                                "code_name": code_name,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        requested_at_ms=fetched.requested_at_ms,
                        retrieved_at_ms=fetched.retrieved_at_ms,
                        http_status_code=fetched.status_code,
                        content_type=fetched.content_type,
                        response_bytes=len(fetched.body),
                        local_path=str(stored_path),
                        sha256=digest,
                    )
                )
                run.records_fetched = fetched_count
                run.records_written = written
                session.commit()
                manifest.append(
                    {
                        **base_event,
                        "status": event_status,
                        "source_url": fetched.source_url,
                        "local_path": str(stored_path),
                        "sha256": digest,
                        "response_bytes": len(fetched.body),
                        "retrieved_at_ms": fetched.retrieved_at_ms,
                    }
                )
                if delay_seconds:
                    time.sleep(delay_seconds)
            if stop:
                break

        run.status = "completed"
        run.completed_at_ms = _now_ms()
        run.records_fetched = fetched_count
        run.records_written = written
        session.commit()
    except Exception as exc:
        session.rollback()
        failed_run = session.get(IngestionRun, run.id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.completed_at_ms = _now_ms()
            failed_run.records_fetched = fetched_count
            failed_run.records_written = written
            failed_run.error_message = str(exc)[:2000]
            session.commit()
        raise

    return TextArchiveDownloadSummary(
        run_id=run.id,
        files_discovered=discovered,
        files_fetched=fetched_count,
        files_written=written,
        files_skipped=skipped,
        bytes_fetched=bytes_fetched,
        manifest_path=manifest_path,
    )


class _TextManifest:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"event_at_ms": _now_ms(), **event}
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

    def known_digests(self) -> dict[str, Path]:
        if not self.path.is_file():
            return {}
        digests: dict[str, Path] = {}
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            digest = event.get("sha256")
            local_path = event.get("local_path")
            if isinstance(digest, str) and isinstance(local_path, str):
                path = Path(local_path)
                if path.is_file():
                    digests.setdefault(digest, path)
        return digests


def _file_event(run_id: int, file: KraTextFile) -> dict[str, Any]:
    payload = asdict(file)
    payload["file_date"] = file.file_date.isoformat() if file.file_date else None
    return {"run_id": run_id, **payload}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_source_document_for_existing_file(
    session: Session,
    *,
    run_id: int,
    file_type: str,
    code_name: str,
    listed_file: KraTextFile,
    target_path: Path,
    digest: str,
) -> None:
    existing = session.scalar(
        select(SourceDocument.id).where(
            SourceDocument.operation == file_type,
            SourceDocument.local_path == str(target_path),
        )
    )
    if existing is not None:
        return
    stat = target_path.stat()
    observed_at_ms = stat.st_mtime_ns // 1_000_000
    session.add(
        SourceDocument(
            ingestion_run_id=run_id,
            source_url="https://race.kra.co.kr/dbdata/fileDownLoad.do",
            endpoint="/dbdata/fileDownLoad.do",
            operation=file_type,
            request_params_json=json.dumps(
                {
                    "meet": listed_file.meet,
                    "fn": listed_file.remote_path,
                    "list_page": listed_file.list_page,
                    "code_name": code_name,
                    "recovered_existing": True,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            requested_at_ms=observed_at_ms,
            retrieved_at_ms=observed_at_ms,
            http_status_code=200,
            content_type="application/octet-stream",
            response_bytes=stat.st_size,
            local_path=str(target_path),
            sha256=digest,
        )
    )


def _now_ms() -> int:
    return time.time_ns() // 1_000_000

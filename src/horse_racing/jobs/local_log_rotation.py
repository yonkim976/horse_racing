"""Archive then copytruncate ONLY six collector logs; no DB, secrets or network access."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = Path.home() / "Library/Logs/horse-racing"
LOCK_PATH = ROOT / "data/state/local-race-day.lock"
LOG_NAMES = tuple(
    f"{stem}{suffix}"
    for stem in ("local-live-race-day", "local-closing-dividends", "local-post-race-repair")
    for suffix in (".log", ".err.log")
)
ARCHIVE_PATTERN = re.compile(
    r"^(" + "|".join(re.escape(name) for name in LOG_NAMES)
    + r")\.(\d{8}T\d{6}Z)\.[0-9a-f]{32}\.gz$"
)


def secure_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.resolve() != path.absolute() or not path.is_dir():
        raise ValueError("unsafe_log_directory")
    if path.stat().st_uid != os.getuid():
        raise ValueError("log_directory_owner_mismatch")
    os.chmod(path, 0o700)


def open_regular(path: Path, flags: int):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        os.close(fd)
        raise ValueError("unsafe_log_file")
    return fd


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def archive_log(path: Path, archive_dir: Path, now: datetime) -> dict:
    result = {"log": path.name, "status": "missing", "bytes": 0}
    try:
        fd = open_regular(path, os.O_RDWR)
    except FileNotFoundError:
        return result
    with os.fdopen(fd, "r+b", buffering=0) as source:
        before = os.fstat(source.fileno())
        result["bytes"] = before.st_size
        if not before.st_size:
            return dict(result, status="empty")
        temp_fd, temp_name = tempfile.mkstemp(prefix=".rotation-", dir=archive_dir)
        temporary = Path(temp_name)
        digest = hashlib.sha256()
        try:
            with os.fdopen(temp_fd, "wb") as output:
                with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
                    remaining = before.st_size
                    while remaining:
                        block = source.read(min(remaining, 1024 * 1024))
                        if not block:
                            raise OSError("log_shrank_during_archive")
                        compressed.write(block)
                        digest.update(block)
                        remaining -= len(block)
                output.flush()
                os.fsync(output.fileno())
            verified = hashlib.sha256()
            with gzip.open(temporary, "rb") as check:
                while block := check.read(1024 * 1024):
                    verified.update(block)
            if digest.digest() != verified.digest():
                raise OSError("archive_verification_failed")
            timestamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
            archive = archive_dir / f"{path.name}.{timestamp}.{uuid.uuid4().hex}.gz"
            # Atomic publication without overwriting an existing archive.
            os.link(temporary, archive)
            directory_fd = os.open(archive_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            result.update(archive=archive.name, sha256=digest.hexdigest())
            current = path.stat(follow_symlinks=False)
            if signature(before) != signature(os.fstat(source.fileno())) or (
                current.st_dev, current.st_ino
            ) != (before.st_dev, before.st_ino):
                return dict(result, status="changed_preserved")
            # Keep the inode: launchd's existing output descriptors stay valid.
            source.truncate(0)
            os.fsync(source.fileno())
            return dict(result, status="rotated")
        finally:
            temporary.unlink(missing_ok=True)


def prune_archives(archive_dir: Path, now: datetime) -> list[str]:
    cutoff = now.astimezone(UTC) - timedelta(days=7)
    removed = []
    for path in archive_dir.iterdir():
        match = ARCHIVE_PATTERN.fullmatch(path.name)
        if not match:
            continue
        try:
            created = datetime.strptime(match[2], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        info = path.stat(follow_symlinks=False)
        if (
            created < cutoff and stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid() and info.st_nlink == 1
        ):
            path.unlink()
            removed.append(path.name)
    return sorted(removed)


def write_status(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".rotation-status-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def execute(*, apply=False, log_dir=LOG_DIR, lock_path=LOCK_PATH, now=None) -> dict:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    day = now.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()
    summary = {"status": "planned", "day_kst": day, "at": now.isoformat(), "logs": []}
    if not apply:
        summary.update(log_directory=str(log_dir), log_names=list(LOG_NAMES), retention_days=7)
        return summary
    secure_directory(log_dir)
    archive_dir = log_dir / "archives"
    secure_directory(archive_dir)
    status_path = log_dir / "rotation-status.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(open_regular(lock_path, os.O_RDWR | os.O_CREAT), "a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            summary["status"] = "skipped_collector_busy"
            # Do not replace another rotation's status file while it holds the lock.
            return summary
        if status_path.exists():
            with os.fdopen(open_regular(status_path, os.O_RDONLY), "r") as previous:
                prior = json.load(previous)
            if prior.get("day_kst") == day and prior.get("status") == "completed":
                return dict(summary, status="skipped_already_rotated_today")
        try:
            for name in LOG_NAMES:
                summary["logs"].append(archive_log(log_dir / name, archive_dir, now))
            summary["removed_archives"] = prune_archives(archive_dir, now)
            summary["status"] = (
                "partial" if any(r["status"] == "changed_preserved" for r in summary["logs"])
                else "completed"
            )
        except Exception as error:
            summary.update(status="failed", error_type=type(error).__name__)
            write_status(status_path, summary)
            raise
        write_status(status_path, summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        summary = execute(apply=args.apply)
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}))
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] != "partial" else 1


if __name__ == "__main__":
    raise SystemExit(main())

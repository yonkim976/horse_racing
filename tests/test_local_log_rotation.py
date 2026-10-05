import fcntl
import gzip
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from horse_racing.jobs import local_log_rotation as logs

NOW = datetime(2026, 10, 5, 18, tzinfo=UTC)  # 10/6 03:00 KST


def test_dry_run_no_filesystem_writes(tmp_path):
    target = tmp_path / "missing"
    result = logs.execute(log_dir=target, lock_path=tmp_path / "lock", now=NOW)
    assert result["status"] == "planned"
    assert len(result["log_names"]) == 6
    assert not target.exists()
    assert not (tmp_path / "lock").exists()


def test_archive_verify_truncate_preserves_inode_and_open_writer(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir()
    for name in logs.LOG_NAMES:
        value = b"official history\n" if not name.endswith("err.log") else b""
        (directory / name).write_bytes(value)
    original = directory / logs.LOG_NAMES[0]
    inode = original.stat().st_ino
    with original.open("ab") as existing_writer:
        result = logs.execute(apply=True, log_dir=directory, lock_path=tmp_path / "lock", now=NOW)
        assert result["status"] == "completed"
        assert original.stat().st_ino == inode and original.stat().st_size == 0
        existing_writer.write(b"next collection\n")
        existing_writer.flush()
    assert original.read_bytes() == b"next collection\n"
    assert len(list((directory / "archives").glob("*.gz"))) == 3
    for archive in (directory / "archives").iterdir():
        assert gzip.decompress(archive.read_bytes()) == b"official history\n"
        assert archive.stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    before = original.read_bytes()
    assert logs.execute(
        apply=True, log_dir=directory, lock_path=tmp_path / "lock", now=NOW
    )["status"] == "skipped_already_rotated_today"
    assert original.read_bytes() == before


def test_prune_only_owned_named_archives_older_than_seven_days(tmp_path):
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir()

    def archive(age):
        timestamp = (NOW - timedelta(days=age)).strftime("%Y%m%dT%H%M%SZ")
        path = archive_dir / f"{logs.LOG_NAMES[0]}.{timestamp}.{uuid.uuid4().hex}.gz"
        path.write_bytes(gzip.compress(b"history"))
        return path

    old, boundary, recent, future = (archive(age) for age in (8, 7, 6, -1))
    unrelated = archive_dir / "database.backup.gz"
    unrelated.write_bytes(b"preserve")
    invalid = archive_dir / f"{logs.LOG_NAMES[0]}.20261399T030000Z.{uuid.uuid4().hex}.gz"
    invalid.write_bytes(b"preserve")
    assert logs.prune_archives(archive_dir, NOW) == [old.name]
    assert not old.exists()
    assert all(p.exists() for p in (boundary, recent, future, unrelated, invalid))


def test_busy_collector_preserves_logs(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir()
    path = directory / logs.LOG_NAMES[0]
    path.write_text("preserve")
    lock_path = tmp_path / "lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = logs.execute(apply=True, log_dir=directory, lock_path=lock_path, now=NOW)
    assert result["status"] == "skipped_collector_busy"
    assert path.read_text() == "preserve"


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_unsafe_log_file_preserved(tmp_path, kind):
    directory = tmp_path / "logs"
    directory.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    path = directory / logs.LOG_NAMES[0]
    if kind == "symlink":
        path.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, path)
    else:
        os.mkfifo(path)
    with pytest.raises((ValueError, OSError)):
        logs.execute(apply=True, log_dir=directory, lock_path=tmp_path / "lock", now=NOW)
    assert outside.read_text() == "preserve"
    assert json.loads((directory / "rotation-status.json").read_text())["status"] == "failed"


def test_symlink_directory_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "logs"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError):
        logs.execute(apply=True, log_dir=link, lock_path=tmp_path / "lock", now=NOW)
    assert not list(actual.iterdir())


def test_write_during_archive_does_not_truncate(tmp_path, monkeypatch):
    directory = tmp_path / "logs"
    directory.mkdir()
    path = directory / logs.LOG_NAMES[0]
    path.write_text("before\n")
    original_link = logs.os.link

    def change_then_publish(source, destination):
        with path.open("a") as writer:
            writer.write("during archive\n")
        original_link(source, destination)

    monkeypatch.setattr(logs.os, "link", change_then_publish)
    result = logs.execute(apply=True, log_dir=directory, lock_path=tmp_path / "lock", now=NOW)
    assert result["status"] == "partial"
    assert path.read_text() == "before\nduring archive\n"
    assert result["logs"][0]["status"] == "changed_preserved"


def test_archive_failure_does_not_truncate(tmp_path, monkeypatch):
    directory = tmp_path / "logs"
    directory.mkdir()
    path = directory / logs.LOG_NAMES[0]
    path.write_text("preserve")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(logs.os, "link", fail)
    with pytest.raises(OSError):
        logs.execute(apply=True, log_dir=directory, lock_path=tmp_path / "lock", now=NOW)
    assert path.read_text() == "preserve"
    assert not list((directory / "archives").iterdir())

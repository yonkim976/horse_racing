from datetime import datetime, timedelta

import pytest

from scripts import recheck_daily_training as job


def test_dry_run_performs_no_io(monkeypatch):
    monkeypatch.setattr(job.live, "load_settings", lambda: pytest.fail("read secrets"))
    monkeypatch.setattr(job, "create_engine_for_url", lambda *_a: pytest.fail("DB opened"))
    monkeypatch.setattr(job.shutil, "disk_usage", lambda *_a: pytest.fail("disk accessed"))
    assert job.execute(day=datetime.now(job.training.KST).date(), meet=2) == 0


def test_snapshot_counts_only_requested_meet(monkeypatch):
    monkeypatch.setattr(
        job.training,
        "snapshot",
        lambda *_a: {1: (("meet_code", 1),), 2: (("meet_code", 2),), 3: (("meet_code", 3),)},
    )
    assert job.task_snapshot(None, datetime.now(job.training.KST).date(), 2) == {
        2: (("meet_code", 2),)
    }


@pytest.mark.parametrize("offset,meet", [(1, 2), (-14, 2), (0, 4)])
def test_invalid_scope_rejected_before_secrets(monkeypatch, offset, meet):
    monkeypatch.setattr(job.live, "load_settings", lambda: pytest.fail("read secrets"))
    with pytest.raises(ValueError):
        job.execute(
            day=datetime.now(job.training.KST).date() + timedelta(days=offset),
            meet=meet,
            apply=True,
        )

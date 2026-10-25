from collections import Counter
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts import recover_jeju_start_training as job


def test_no_io_plan_and_scope(monkeypatch):
    monkeypatch.setattr(job, "load_settings", lambda: pytest.fail("read credentials"))
    today = datetime.now(job.KST).date()
    assert job.execute(start=today - timedelta(days=8), end=today) == 0
    with pytest.raises(ValueError):
        job.execute(start=today - timedelta(days=14), end=today, apply=True)


def test_source_comparison_preserves_repetitions_and_does_not_use_location():
    item = SimpleNamespace(
        horse_id="3107491", stable_part=3, stable_number="12", rider_name="이동준", remark="양호"
    )
    saved = {
        "kra_horse_id": "3107491",
        "stable_part": 3,
        "stable_number": "12",
        "rider_name": "이동준",
        "remark": "양호",
        "location_raw": "400M 출발지점",
    }
    assert job.source_signature(item) == job.saved_signature(saved)
    assert Counter([job.source_signature(item)] * 2) != Counter([job.saved_signature(saved)])


def test_exclusive_artifact_serializes_dates_and_creates_directory(tmp_path):
    target = tmp_path / "capture/one.json"
    today = datetime.now(job.KST).date()
    job.write_json(target, {"date": today})
    assert str(today) in target.read_text()
    with pytest.raises(FileExistsError):
        job.write_json(target, {})


def test_cached_sources_reject_other_endpoint_or_meet():
    cached = job.CachedPages({"20261015": ["source"]})
    assert list(
        cached.iter_pages(
            endpoint=job.START_TRAINING_ENDPOINT, public_params={"meet": 2, "tr_date": "20261015"}
        )
    ) == ["source"]
    with pytest.raises(ValueError):
        cached.iter_pages(
            endpoint=job.START_TRAINING_ENDPOINT, public_params={"meet": 1, "tr_date": "20261015"}
        )

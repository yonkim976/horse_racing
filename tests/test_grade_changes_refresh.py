from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from horse_racing.db.models import Base, Horse, HorseGradeChange
from horse_racing.jobs import grade_changes as grades
from horse_racing.parsers.race_supplemental import HorseGradeChangeItem


def item(**values):
    return HorseGradeChangeItem.model_validate(
        dict(
            hrNo="000001",
            hrName="공식현재명",
            meet="서울",
            beforeRank="국5",
            rank="국4",
            stDate="20261005",
            spDate="-",
            blood="더러브렛",
        )
        | values
    )


def test_direction_excludes_initial_allocation():
    assert grades.direction("국5", "국4") == "promotion"
    assert grades.direction("제3", "제4") == "demotion"
    assert grades.direction("미검", "국6") == "initial_or_other"
    assert grades.direction("국4", "외4") == "same_grade"


def test_validate_conflicts_and_region():
    assert len(grades.validate_items([item(), item()], 1)) == 1
    with pytest.raises(ValueError, match="conflicting"):
        grades.validate_items([item(), item(blood="제주마")], 1)
    with pytest.raises(ValueError, match="wrong_key"):
        grades.validate_items([item()], 2)
    with pytest.raises(ValueError, match="date_range"):
        grades.validate_items([item(spDate="20261004")], 1)


def test_apply_is_idempotent_and_preserves_profiles_and_old_history():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        horse = Horse(kra_horse_id="000001", name_ko="보존할현재명", grade="국3")
        session.add(horse)
        session.flush()
        old = HorseGradeChange(
            horse_id=horse.id,
            meet_code=1,
            grade_before="국6",
            grade_after="국5",
            start_date_local=date(2026, 1, 1),
            observed_at_ms=1,
        )
        session.add(old)
        session.flush()
        before = grades.snapshot(session)
        counts = grades.apply_items(session, [item()], 2)
        after = grades.verify_saved(session, [item()], before, 2)
        assert counts["1"]["new"] == 1
        assert counts["1"]["new_promotion"] == 1
        assert len(after) == 2
        assert horse.name_ko == "보존할현재명" and horse.grade == "국3"
        counts = grades.apply_items(session, [item()], 3)
        grades.verify_saved(session, [item()], after, 3)
        assert counts["1"] == {"unchanged": 1}
        changed = item(spDate="20261012")
        counts = grades.apply_items(session, [changed], 4)
        grades.verify_saved(session, [changed], before, 4)
        assert counts["1"]["changed"] == 1
        assert (
            session.scalar(
                select(HorseGradeChange).where(HorseGradeChange.id == old.id)
            ).observed_at_ms
            == 1
        )
    engine.dispose()


def test_new_horse_is_linked_without_changing_existing_horse():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        counts = grades.apply_items(session, [item()], 1)
        assert counts["1"]["horses_added"] == 1
        assert len(grades.verify_saved(session, [item()], [], 1)) == 1
    engine.dispose()


def test_dry_run_has_no_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run performed I/O")

    monkeypatch.setattr(grades.live, "load_settings", forbidden)
    monkeypatch.setattr(grades.shutil, "disk_usage", forbidden)
    assert grades.execute() == 0

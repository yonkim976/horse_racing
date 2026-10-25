from datetime import date, datetime
from types import SimpleNamespace

import pytest

from horse_racing.jobs import canonical_post_race as core
from horse_racing.jobs import local_catalog as job
from horse_racing.jobs.canonical_refresh import deltas, section_scope
from horse_racing.jobs.reference_catalog import validate_trial_api
from horse_racing.parsers.running_trials import RunningTrialData, RunningTrialResultData


@pytest.mark.parametrize("mode", job.MODES)
def test_dry_run_reads_no_secret_or_files(monkeypatch, mode):
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run performed I/O")

    monkeypatch.setattr(job.live, "load_settings", forbidden)
    monkeypatch.setattr(job.shutil, "disk_usage", forbidden)
    assert job.execute(mode=mode) == 0


def test_schedules_include_early_cards_and_rechecks():
    assert job.SCHEDULES["cards"] == [
        {"Weekday": 3, "Hour": 15, "Minute": 10},
        {"Weekday": 3, "Hour": 16, "Minute": 10},
    ]
    assert job.SCHEDULES["trials"] == [
        {"Weekday": 4, "Hour": 15, "Minute": 10},
        {"Weekday": 4, "Hour": 19, "Minute": 10},
        {"Weekday": 5, "Hour": 9, "Minute": 10},
    ]
    assert job.SCHEDULES["canonical"] == [{"Hour": 21, "Minute": 0}, {"Hour": 9, "Minute": 15}]


def test_manual_canonical_scope_cannot_override_scheduled_or_other_modes(monkeypatch):
    now = datetime(2026, 10, 11, 0, 10, tzinfo=job.cards.KST)
    monkeypatch.setattr(job.live, "load_settings", lambda: pytest.fail("dry-run secret read"))
    assert (
        job.execute(mode="canonical", canonical_date=date(2026, 10, 10), canonical_days=1, now=now)
        == 0
    )
    for options, message in (
        ({"mode": "medical", "canonical_days": 1}, "manual_scope"),
        ({"mode": "canonical", "canonical_days": 1, "scheduled": True}, "manual_scope"),
        ({"mode": "canonical", "canonical_date": date(2026, 10, 12)}, "outside_recent"),
    ):
        with pytest.raises(ValueError, match=message):
            job.execute(now=now, **options)


def test_profile_guard_includes_holiday_monday():
    now = datetime(2026, 10, 12, 18, 40, tzinfo=job.cards.KST)
    assert job.profiles_due(now, date(2026, 10, 12))
    assert not job.profiles_due(now, date(2026, 10, 11))
    assert job.profiles_due(datetime(2026, 10, 7, 17, 40, tzinfo=job.cards.KST), None)
    assert not job.profiles_due(datetime(2026, 10, 7, 18, 40, tzinfo=job.cards.KST), None)


def test_delta_idempotency_correction_and_removal_guard():
    old = [dict(id=1, value=3, observed=1)]
    assert deltas(old, [dict(id=1, value=3, observed=2)], ("id",), ("value",)) == ([], [], [])
    added, changed, before = deltas(
        old, [dict(id=1, value=4), dict(id=2, value=5)], ("id",), ("value",)
    )
    assert added == [dict(id=2, value=5)]
    assert changed == [dict(id=1, value=4)] and before == old
    with pytest.raises(core.SourceMismatch, match="source_removed_existing_rows"):
        deltas(old, [], ("id",), ("value",))
    with pytest.raises(core.SourceMismatch, match="duplicate_refresh_key"):
        deltas([], old + old, ("id",), ("value",))


def test_explicit_void_race_does_not_block_other_races_but_unknown_98_does():
    from test_canonical_post_race import sample

    snapshot, data, races = sample()
    void = dict(
        snapshot[0],
        race_id=102,
        race_number=2,
        entry_id=202,
        finish_position=98,
        finish_time_ms=None,
        rank_remark="경주불성립",
    )
    raw = dict(data["sections"][0], rcNo=2, ord=98, rcTime=None)
    full_data = dict(data, sections=[*data["sections"], raw])
    scoped, filtered, text, excluded = section_scope([*snapshot, void], full_data, races)
    assert scoped == snapshot and filtered == data and text == races and excluded == [2]
    assert core.normalize_day(1, "2026-10-05", scoped, filtered, text)["sections"]
    unknown = dict(void, rank_remark=None)
    assert section_scope([*snapshot, unknown], full_data, races)[-1] == []
    for changed in ({"ord": 1}, {"hrNo": "0059999"}, {"rcTime": 80}):
        with pytest.raises(core.SourceMismatch, match="void_api_result_mismatch"):
            section_scope(
                [*snapshot, void],
                dict(full_data, sections=[data["sections"][0], dict(raw, **changed)]),
                races,
            )
    with pytest.raises(core.SourceMismatch, match="void_api_entry_coverage"):
        section_scope([*snapshot, void], data, races)


def trial_sources():
    row = RunningTrialResultData(
        horse_number=1,
        horse_name="말",
        jockey_name="기수",
        trainer_name="조교사",
        finish_time_ms=63000,
        finish_position=1,
    )
    trials = [RunningTrialData(date(2026, 10, 1), 1, 1, 1000, None, None, None, [row])]
    api = dict(
        trainDate=20261001,
        trainNo=1,
        chulNo=1,
        meet="서울",
        hrName="말",
        jkName="기수",
        trName="조교사",
        rcTime=63.0,
        ord=1,
        hrNo="0056500",
        jkNo="080578",
        trNo="070161",
    )
    return trials, api


def test_trial_identity_requires_independent_api_text_agreement():
    trials, raw = trial_sources()
    assert len(validate_trial_api(1, trials, [raw])) == 1
    for change in (
        {"hrName": "다른말"},
        {"jkName": "다른기수"},
        {"rcTime": 64},
        {"hrNo": "0"},
        {"trainNo": 2},
        {"meet": "제주"},
    ):
        with pytest.raises(core.SourceMismatch):
            validate_trial_api(1, trials, [dict(raw, **change)])
    with pytest.raises(core.SourceMismatch):
        validate_trial_api(1, trials, [])


def test_medical_mode_never_refreshes_profiles(monkeypatch, tmp_path):
    captured = {}

    def fake(settings, **kwargs):
        captured.update(kwargs)
        return {"status": "completed"}

    monkeypatch.setattr(job.horse_profile_medical, "refresh", fake)
    now = datetime(2026, 10, 7, 18, 10, tzinfo=job.cards.KST)
    job.collect("medical", SimpleNamespace(), now, tmp_path)
    assert captured["include_profiles"] is False
    assert captured["start"] == date(2026, 9, 24) and captured["end"] == date(2026, 10, 7)


def test_official_trial_identity_overrides_ambiguous_names_without_duplicate_results(tmp_path):
    from sqlalchemy import func, select
    from test_race_day import migrated_session

    from horse_racing.db.models import (
        Horse,
        IngestionRun,
        Jockey,
        RunningTrialResult,
        SourceDocument,
        Trainer,
    )
    from horse_racing.services.running_trials import _write_trial

    factory = migrated_session(tmp_path)
    trials, _ = trial_sources()
    with factory() as session:
        horse = Horse(kra_horse_id="0056500", name_ko="최신마명")
        jockey = Jockey(kra_jockey_id="080578", name_ko="최신기수명")
        trainer = Trainer(kra_trainer_id="070161", name_ko="최신조교사명")
        run = IngestionRun(source="test", data_type="trial", started_at_ms=1)
        session.add_all([horse, jockey, trainer, run])
        session.flush()
        doc = SourceDocument(
            ingestion_run_id=run.id,
            source_url="https://example.test",
            requested_at_ms=1,
            retrieved_at_ms=1,
            local_path="test",
            sha256="a" * 64,
        )
        session.add(doc)
        session.flush()
        ids = (horse.id, jockey.id, trainer.id)
        for timestamp in (1, 2):
            _, written, linked, unresolved = _write_trial(
                session,
                meet=1,
                data=trials[0],
                source_document_id=doc.id,
                observed_at_ms=timestamp,
                horse_candidates_by_name={},
                jockey_by_name={},
                trainer_by_name={},
                official_identity={(1, date(2026, 10, 1), 1, 1): ids},
            )
            session.flush()
            assert (written, linked, unresolved) == (1, 1, 0)
        assert session.scalar(select(func.count()).select_from(RunningTrialResult)) == 1
        saved = session.scalar(select(RunningTrialResult))
        assert (saved.horse_id, saved.jockey_id, saved.trainer_id) == ids
        assert saved.horse_name_raw == "말" and horse.name_ko == "최신마명"

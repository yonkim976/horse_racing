import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from horse_racing.jobs.weekly_entry_cards import (
    KST,
    Card,
    card_window,
    execute,
    fingerprint,
    require_target,
    validate_card,
    validate_existing,
    verify_saved,
)
from horse_racing.parsers.entry_sheet import parse_entry_sheet_page
from horse_racing.parsers.gate_entry_sheet import GateEntrySheetItem
from horse_racing.parsers.race_day import RacePlanItem


def example() -> Card:
    payload = json.loads((Path(__file__).parent / "fixtures/entry_sheet_page.json").read_text())
    entries = parse_entry_sheet_page(payload).items
    day = entries[0].race_date
    return Card(
        day,
        1,
        [
            RacePlanItem(
                raceDt=day.isoformat(),
                raceNo=entries[0].race_number,
                raceDs=entries[0].distance_m,
                rccrsNm="서울",
                ptinNhr=2,
            )
        ],
        entries,
        [
            GateEntrySheetItem(
                raceDt=day.isoformat(),
                raceNo=x.race_number,
                gtno=x.horse_number,
                hrnm=x.horse_name,
                equipCrs="망사눈가면+",
            )
            for x in entries
        ],
    )


def saved_rows(card: Card):
    return {
        (x.race_number, x.horse_id): {
            "id": i,
            "status": "scheduled",
            "scheduled_at_ms": None,
            "scratched": False,
            "horse_number": x.horse_number,
            "gate_number": x.horse_number,
            "carried_weight_kg": x.carried_weight_kg,
            "rating": x.rating,
            "kra_jockey_id": x.jockey_id,
            "kra_trainer_id": x.trainer_id,
            "kra_owner_id": x.owner_id,
            "equipment_card_raw": "망사눈가면+",
        }
        for i, x in enumerate(card.entries)
    }


def test_window_includes_holiday_monday_and_tuesday():
    anchor, days = card_window(date(2026, 10, 7))
    assert anchor == date(2026, 10, 7)
    assert days[-2:] == [date(2026, 10, 12), date(2026, 10, 13)]
    assert len(days) == 7


def test_thursday_manual_run_does_not_rewrite_previous_days():
    anchor, days = card_window(date(2026, 10, 1))
    assert anchor == date(2026, 9, 30)
    assert days[0] == date(2026, 10, 1)
    assert days[-1] == date(2026, 10, 6)


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///data/horse_racing.sqlite3",
        "postgresql://postgres.other:dummy@example.com:5432/postgres",
        "postgresql://postgres.target:dummy@example.com:6543/postgres",
    ],
)
def test_wrong_db_and_transaction_pooler_are_rejected(url):
    with pytest.raises(ValueError):
        require_target(url, "target")


def test_session_pooler_is_accepted():
    require_target("postgresql://postgres.target:dummy@example.com:5432/postgres", "target")


def test_dry_run_has_no_database_connection_or_api(monkeypatch):
    from horse_racing.config import Settings

    settings = Settings(
        _env_file=None, database_url="postgresql://postgres.target:dummy@example.com:5432/postgres"
    )
    monkeypatch.setattr("horse_racing.jobs.weekly_entry_cards.get_settings", lambda: settings)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No external work allowed in dry-run")

    monkeypatch.setattr("horse_racing.jobs.weekly_entry_cards.create_engine_for_url", forbidden)
    monkeypatch.setattr("horse_racing.jobs.weekly_entry_cards.KraApiClient", forbidden)
    assert execute("target", as_of=date(2026, 10, 7), force=False, dry_run=True) == 0


def test_full_source_card_validates():
    validate_card(example())


def test_fingerprint_is_order_independent_and_detects_late_changes():
    card = example()
    first = fingerprint([card])
    card.entries.reverse()
    card.gates.reverse()
    assert fingerprint([card]) == first
    card.entries[0].carried_weight_kg = 60
    assert fingerprint([card]) != first


@pytest.mark.parametrize("failure", ["missing_gate", "wrong_name", "duplicate", "field_size"])
def test_source_mismatch_blocks_writes(failure):
    card = example()
    if failure == "missing_gate":
        card.gates.pop()
    elif failure == "wrong_name":
        card.gates[0].horse_name = "다른말"
    elif failure == "duplicate":
        card.entries.append(card.entries[0])
    else:
        card.plans[0].field_size = 3
    with pytest.raises(ValueError):
        validate_card(card)


def test_completed_and_disappeared_runners_are_rejected():
    card = example()
    before = saved_rows(card)
    now_ms = int(datetime(2026, 8, 20, tzinfo=KST).timestamp() * 1000)
    validate_existing(card, before, now_ms)
    before[next(iter(before))]["status"] = "completed"
    with pytest.raises(ValueError):
        validate_existing(card, before, now_ms)
    before = saved_rows(card)
    before[(1, "missing-horse")] = copy.deepcopy(next(iter(before.values())))
    with pytest.raises(ValueError):
        validate_existing(card, before, now_ms)


def test_same_day_initial_card_is_rejected():
    card = example()
    now_ms = int(datetime.combine(card.day, datetime.min.time(), KST).timestamp() * 1000)
    with pytest.raises(ValueError):
        validate_existing(card, {}, now_ms)


def test_saved_values_and_cancellation_preservation():
    card = example()
    before = saved_rows(card)
    after = copy.deepcopy(before)
    verify_saved(card, before, after)
    key = next(iter(before))
    before[key]["scratched"] = after[key]["scratched"] = True
    verify_saved(card, before, after)
    after[key]["scratched"] = False
    with pytest.raises(ValueError):
        verify_saved(card, before, after)
    after[key]["scratched"] = True
    after[key]["rating"] = 12345
    with pytest.raises(ValueError):
        verify_saved(card, before, after)

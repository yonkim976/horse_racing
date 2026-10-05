import importlib.util
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from horse_racing.parsers.race_day import FinalDividendItem

spec = importlib.util.spec_from_file_location(
    "dividend_backfill",
    Path(__file__).resolve().parents[1] / "scripts/backfill_dividends_verified.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def item(pool, selection, odds=2.5, day="20261002"):
    numbers = [int(n) for n in selection.split("-")]
    return FinalDividendItem.model_validate(
        dict(
            rcDate=day,
            rcNo=1,
            meet="서울",
            pool=pool,
            chulNo=numbers[0],
            chulNo2=numbers[1] if len(numbers) > 1 else 0,
            chulNo3=numbers[2] if len(numbers) > 2 else 0,
            odds=odds,
        )
    )


def complete_items():
    return [
        item(p, "-".join(str(n) for n in range(1, arity + 1))) for p, arity in module.ARITY.items()
    ]


def validated(items):
    return module.validate(
        items, date(2026, 10, 2).isoformat(), 1, {1: (9, "completed")}, {1: {1, 2, 3}}
    )


def test_source_validation():
    expected, ignored, duplicate = validated(complete_items() + [item("WIN", "2", 0)])
    assert len(expected) == 7 and ignored == 1 and duplicate == 0
    assert validated(complete_items() + [item("WIN", "1")])[2] == 1
    with pytest.raises(ValueError, match="conflicting_source_duplicate"):
        validated(complete_items() + [item("WIN", "1", 4)])
    with pytest.raises(ValueError, match="unexpected_source_date"):
        validated([item("WIN", "1", day="20261001")])
    with pytest.raises(ValueError, match="missing_official_pools"):
        validated([item("WIN", "1")])
    with pytest.raises(ValueError, match="invalid_selection"):
        validated([item("TRI", "1-1-2")])


def test_cancelled_race_has_no_fabricated_odds():
    assert (
        module.validate([], "2026-03-20", 2, {1: (9, "confirmed_cancelled")}, {1: {1, 2}})[0] == {}
    )
    assert (
        module.validate(
            complete_items(), "2026-10-02", 1, {1: (9, "confirmed_cancelled")}, {1: {1, 2, 3}}
        )[0]
        == {}
    )


def test_reconciliation_idempotent_update_and_extra_guard():
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(
            text(
                "CREATE TABLE odds_snapshots(id INTEGER PRIMARY KEY, race_id INTEGER,"
                " bet_type TEXT, selection_key TEXT, odds REAL, observed_at_ms INTEGER)"
            )
        )
    expected = {(1, "WIN", "1"): 2.5}
    races = {1: (9, "completed")}
    with Session(engine) as session, session.begin():
        assert module.reconcile(session, races, expected, 10, False)["inserted"] == 1
        assert module.reconcile(session, races, expected, 10, True)["inserted"] == 1
        assert module.reconcile(session, races, expected, 20, True)["inserted"] == 0
        assert session.scalar(text("SELECT observed_at_ms FROM odds_snapshots")) == 10
        changed = module.reconcile(session, races, {(1, "WIN", "1"): 3.5}, 20, True)
        assert changed["updated"] == 1 and changed["changes"][0]["old_odds"] == 2.5
        with pytest.raises(ValueError, match="absent_from_positive"):
            module.reconcile(session, races, {}, 30, True)
        retained = module.reconcile(session, races, {}, 30, True, set(expected))
        assert retained["retained_nonstarter_zero_rows"] == 1
        assert session.scalar(text("SELECT odds FROM odds_snapshots")) == 3.5

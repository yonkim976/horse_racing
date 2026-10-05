"""Validate closing dividends against completed cards; never insert pre-race quotes."""

from __future__ import annotations

import math

from sqlalchemy import insert, select, text

from horse_racing.db.models import OddsSnapshot
from horse_racing.parsers.horse_history import parse_meet_code
from horse_racing.services.live_race_day import race_has_complete_results

ARITY = {"WIN": 1, "PLC": 1, "QNL": 2, "QPL": 2, "EXA": 2, "TLA": 3, "TRI": 3}
BACKFILL_LOCK = 63831012620261002


def settled(race):
    if not race_has_complete_results(race) or race.status != "completed":
        return False
    winners = [e for e in race.entries if e.result and e.result.finish_position == 1]
    # Cancelled races and date-echo/pre-opening placeholders are not settlements.
    # Official dead heats can have multiple first-place runners.
    return bool(winners) and all((e.result.finish_time_ms or 0) > 0 for e in winners)


def prepare(items, *, day, meet, races):
    """Allow a day response containing future races, but only select settled races.

    Missing pool data leaves that race pending, rather than failing other races or
    treating a partial publication as a complete dividend table.
    """
    known = {r.race_number: r for r in races}
    expected, zeros, pools = {}, set(), {}
    selected = {no: r for no, r in known.items() if settled(r)}
    for item in items:
        if item.race_date != day or parse_meet_code(item.meet_name) != meet:
            raise ValueError("dividend_date_venue_mismatch")
        race = known.get(item.race_number)
        if race is None:
            raise ValueError("dividend_unknown_race")
        if item.race_number not in selected:
            continue
        if item.bet_type not in ARITY:
            raise ValueError("dividend_unknown_pool")
        numbers = tuple(int(n) for n in item.selection_key.split("-"))
        if (
            len(numbers) != ARITY[item.bet_type]
            or len(set(numbers)) != len(numbers)
            or not set(numbers) <= {e.horse_number for e in race.entries}
        ):
            raise ValueError("dividend_invalid_selection")
        key = (race.id, item.bet_type, item.selection_key)
        if item.odds is None:
            zeros.add(key)
            continue
        if not math.isfinite(item.odds) or item.odds <= 0:
            raise ValueError("dividend_invalid_odds")
        if key in expected and expected[key] != item.odds:
            raise ValueError("dividend_conflicting_source")
        expected[key] = item.odds
        pools.setdefault(race.id, set()).add(item.bet_type)
    if zeros & set(expected):
        raise ValueError("dividend_conflicting_zero_source")
    ready = {r.id: r for r in selected.values() if pools.get(r.id) == set(ARITY)}
    pending = [r.race_number for r in selected.values() if r.id not in ready]
    return ready, {k: v for k, v in expected.items() if k[0] in ready}, zeros, pending


def read_existing(session, race_ids):
    rows = session.execute(
        select(
            OddsSnapshot.id,
            OddsSnapshot.race_id,
            OddsSnapshot.bet_type,
            OddsSnapshot.selection_key,
            OddsSnapshot.odds,
            OddsSnapshot.observed_at_ms,
        ).where(OddsSnapshot.race_id.in_(race_ids))
    )
    known = {}
    for row in rows:
        key = (row.race_id, row.bet_type, row.selection_key)
        if key in known:
            raise ValueError("dividend_duplicate_business_key")
        known[key] = (row.id, row.odds, row.observed_at_ms)
    return known


def reconcile(session, *, ready, expected, zeros, observed_ms):
    if not ready:
        return {"inserted": 0, "updated": 0, "unchanged": 0, "retained": 0, "changes": []}
    before = read_existing(session, ready)
    extra = set(before) - set(expected)
    nonstarters = {
        (r.id, e.horse_number)
        for r in ready.values()
        for e in r.entries
        if e.scratched and e.result and e.result.finish_position in {91, 92, 93, 94, 95, 96, 99}
    }
    allowed = {k for k in zeros if any((k[0], int(n)) in nonstarters for n in k[2].split("-"))}
    if extra - allowed:
        raise ValueError("dividend_stored_selection_absent_from_source")
    additions, changes = [], []
    for key, odds in expected.items():
        race_id, pool, selection = key
        if key not in before:
            additions.append(
                dict(
                    race_id=race_id,
                    bet_type=pool,
                    selection_key=selection,
                    odds=odds,
                    observed_at_ms=observed_ms,
                )
            )
        elif not math.isclose(before[key][1], odds, rel_tol=0, abs_tol=1e-8):
            changes.append(
                dict(
                    row_id=before[key][0],
                    value=odds,
                    stamp=observed_ms,
                    old_odds=before[key][1],
                    old_stamp=before[key][2],
                    key=list(key),
                )
            )
    for offset in range(0, len(additions), 1000):
        session.execute(insert(OddsSnapshot.__table__), additions[offset : offset + 1000])
    if changes:
        session.execute(
            text("UPDATE odds_snapshots SET odds=:value,observed_at_ms=:stamp WHERE id=:row_id"),
            [{k: row[k] for k in ("row_id", "value", "stamp")} for row in changes],
        )
    after = read_existing(session, ready)
    if set(after) != set(expected) | extra or any(
        not math.isclose(after[k][1], value, rel_tol=0, abs_tol=1e-8)
        for k, value in expected.items()
    ):
        raise ValueError("dividend_post_write_mismatch")
    return {
        "inserted": len(additions),
        "updated": len(changes),
        "unchanged": len(expected) - len(additions) - len(changes),
        "retained": len(extra),
        "changes": changes,
    }

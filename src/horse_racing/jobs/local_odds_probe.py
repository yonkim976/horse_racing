"""One-day API301 experiment: local SQLite only, never production databases."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from horse_racing.config import Settings
from horse_racing.jobs.local_log_rotation import open_regular, secure_directory, write_status

ROOT = Path(__file__).resolve().parents[3]
KST = ZoneInfo("Asia/Seoul")
OFFSETS = (16, 14, 12, 10, 8, 6, 4, 2, -10)
MEETS = {1: "서울", 2: "제주", 3: "부산경남", 4: "영천"}
ENDPOINT = "/API301/Dividend_rate_total"
LIMIT = 500  # Independent, conservative cap for this experiment, including failed requests.


def stamp(value):
    return int(value.timestamp() * 1000)


def directory(day):
    return ROOT / "data/research" / f"api301_snapshot_probe_{day:%Y%m%d}"


def connect(folder):
    secure_directory(folder)
    path = folder / "snapshots.sqlite3"
    fd = open_regular(path, os.O_CREAT | os.O_RDWR)
    os.fchmod(fd, 0o600)
    os.close(fd)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS responses (
          id INTEGER PRIMARY KEY, kind TEXT NOT NULL, meet INTEGER NOT NULL,
          requested_ms INTEGER NOT NULL, received_ms INTEGER,
          http_status INTEGER, result_code TEXT, total_count INTEGER,
          sha256 TEXT, payload BLOB, valid INTEGER NOT NULL DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS schedule (
          meet INTEGER NOT NULL, race_no INTEGER NOT NULL, start_ms INTEGER NOT NULL,
          source_start_ms INTEGER, observed_ms INTEGER NOT NULL, active INTEGER NOT NULL,
          PRIMARY KEY (meet,race_no));
        CREATE TABLE IF NOT EXISTS observations (
          id INTEGER PRIMARY KEY, meet INTEGER NOT NULL, race_no INTEGER NOT NULL,
          start_ms INTEGER NOT NULL, offset_minutes INTEGER NOT NULL,
          requested_ms INTEGER NOT NULL, received_ms INTEGER NOT NULL,
          source_start_ms INTEGER, status TEXT NOT NULL, returned_rows INTEGER NOT NULL,
          positive_rows INTEGER NOT NULL, values_json TEXT NOT NULL, value_hash TEXT,
          response_ids_json TEXT NOT NULL,
          UNIQUE(meet,race_no,start_ms,offset_minutes));
    """)
    return db


def request(db, client, key, kind, meet, day):
    """Bounded pages, no retries, no redirect, and archive before interpretation."""
    path = ENDPOINT if kind == "odds" else "/API154/racePlan"
    params = (
        {"meet": meet, "rc_date": day.strftime("%Y%m%d")}
        if kind == "odds"
        else {"rccrs_cd": meet, "race_dt": day.strftime("%Y%m%d")}
    )
    ids, rows, totals = [], [], set()
    first_requested = stamp(datetime.now(KST))
    for page_no in range(1, 6):
        if db.execute("SELECT count(*) FROM responses").fetchone()[0] >= LIMIT:
            raise RuntimeError("probe_request_budget_exhausted")
        requested = stamp(datetime.now(KST))
        cursor = db.execute(
            "INSERT INTO responses(kind,meet,requested_ms) VALUES(?,?,?)",
            (kind, meet, requested),
        )
        response_id = cursor.lastrowid
        db.commit()  # Count transport failures and crashes as attempts too.
        try:
            with client.stream(
                "GET",
                path.lstrip("/"),
                params={
                    **params,
                    "pageNo": page_no,
                    "numOfRows": 20000,
                    "_type": "json",
                    "serviceKey": key,
                },
            ) as response:
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 20_000_000:
                        raise ValueError("response_size_limit")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                received = stamp(datetime.now(KST))
                db.execute(
                    "UPDATE responses SET received_ms=?,http_status=?,sha256=?,payload=? "
                    "WHERE id=?",
                    (
                        received,
                        response.status_code,
                        hashlib.sha256(raw).hexdigest(),
                        raw,
                        response_id,
                    ),
                )
                db.commit()
                response.raise_for_status()
            root = json.loads(raw)
            root = root.get("response", root)
            code = str(root.get("header", {}).get("resultCode", ""))
            db.execute("UPDATE responses SET result_code=? WHERE id=?", (code, response_id))
            db.commit()
            if code in {"22", "23"}:
                raise RuntimeError("source_quota_stop")
            if code not in {"00", "0000"}:
                raise ValueError("source_error")
            body = root.get("body", {})
            total = int(body.get("totalCount") or 0)
            items = (body.get("items") or {}).get("item") or []
            items = [items] if isinstance(items, dict) else items
            if not isinstance(items, list) or not 0 <= total <= 100_000:
                raise ValueError("invalid_page")
            if int(body.get("pageNo", page_no)) != page_no:
                raise ValueError("wrong_page")
            totals.add(total)
            rows.extend(items)
            ids.append(response_id)
            db.execute(
                "UPDATE responses SET valid=1,total_count=? WHERE id=?", (total, response_id)
            )
            db.commit()
            if len(rows) >= total:
                if totals != {len(rows)}:
                    raise ValueError("incomplete_or_changing_pages")
                return rows, ids, first_requested, received
            if not items:
                raise ValueError("empty_intermediate_page")
        except Exception as exc:
            db.execute("UPDATE responses SET error=? WHERE id=?", (type(exc).__name__, response_id))
            db.commit()
            raise
    raise ValueError("page_limit")


def parse_schedule(items, meet, day, observed):
    result = []
    for row in items:
        if str(row.get("raceDt")) != day.strftime("%Y%m%d") or row.get("rccrsNm") != MEETS[meet]:
            raise ValueError("schedule_source_mismatch")
        race = int(row["raceNo"])
        start = datetime.combine(day, datetime.strptime(row["strtPargTm"], "%H:%M").time(), KST)
        source_start = None
        if row.get("strtTm") not in (None, "", "-", "0", 0):
            source_start = datetime.combine(
                day, datetime.strptime(row["strtTm"], "%H:%M").time(), KST
            )
        if not 1 <= race <= 30:
            raise ValueError("invalid_race")
        # strtTm is present even for future races: it is NOT proof of actual departure.
        result.append(
            (
                meet,
                race,
                stamp(source_start or start),
                stamp(source_start) if source_start else None,
                observed,
                1,
            )
        )
    if len({r[1] for r in result}) != len(result):
        raise ValueError("duplicate_schedule")
    return result


def normalize(items, meet, day):
    grouped, seen = {}, set()
    for row in items:
        if str(row.get("rcDate")) != day.strftime("%Y%m%d") or row.get("meet") != MEETS[meet]:
            raise ValueError("odds_source_mismatch")
        race = int(row["rcNo"])
        pool = str(row["pool"])
        numbers = tuple(int(row.get(k) or 0) for k in ("chulNo", "chulNo2", "chulNo3"))
        identity = (race, pool, *numbers)
        if pool not in {"WIN", "PLC", "QNL", "QPL", "EXA", "TLA", "TRI"}:
            raise ValueError("unknown_pool")
        if not 1 <= race <= 30 or not 1 <= numbers[0] <= 30:
            raise ValueError("invalid_odds_identity")
        if any(not 0 <= n <= 30 for n in numbers) or identity in seen:
            raise ValueError("invalid_or_duplicate_selection")
        seen.add(identity)
        value = row.get("odds")
        number = Decimal(str(value)) if value is not None else None
        if number is not None and (not number.is_finite() or number < 0):
            raise ValueError("invalid_odds")
        grouped.setdefault(race, []).append(
            [pool, *numbers, format(number.normalize(), "f") if number is not None else None]
        )
    return {race: sorted(values, key=lambda r: tuple(r[:4])) for race, values in grouped.items()}


def due(schedule, now_ms):
    result = []
    for row in schedule:
        for offset in OFFSETS:
            target = row["start_ms"] - offset * 60_000
            # Never manufacture missed snapshots after waking up or restarting.
            if 0 <= now_ms - target < 70_000:
                if offset > 0 and now_ms >= row["start_ms"]:
                    continue
                result.append((row, offset))
    return result


def save_observation(db, row, offset, values, ids, requested, received, *, error=False):
    encoded = json.dumps(values, separators=(",", ":"))
    positive = sum(v[-1] is not None and Decimal(v[-1]) > 0 for v in values)
    before = requested < row["start_ms"] and received < row["start_ms"]
    status = "present" if positive else "empty"
    if error:
        status = "error"
    if offset > 0 and not before:
        status = "crossed_start_not_pre_race"
    db.execute(
        "INSERT OR IGNORE INTO observations(meet,race_no,start_ms,offset_minutes,"
        "requested_ms,received_ms,source_start_ms,status,returned_rows,positive_rows,"
        "values_json,value_hash,response_ids_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["meet"],
            row["race_no"],
            row["start_ms"],
            offset,
            requested,
            received,
            row["source_start_ms"],
            status,
            len(values),
            positive,
            encoded,
            hashlib.sha256(encoded.encode()).hexdigest(),
            json.dumps(ids),
        ),
    )
    db.commit()


def comparison(db):
    result = []
    for race in db.execute("SELECT * FROM schedule ORDER BY start_ms,meet"):
        rows = db.execute(
            "SELECT * FROM observations WHERE meet=? AND race_no=? ORDER BY received_ms",
            (race["meet"], race["race_no"]),
        ).fetchall()
        pre = [
            r
            for r in rows
            if r["offset_minutes"] > 0
            and r["status"] == "present"
            and r["start_ms"] == race["start_ms"]
        ]
        changes = []
        for previous, current in zip(pre, pre[1:], strict=False):
            old = {tuple(v[:4]): v[-1] for v in json.loads(previous["values_json"])}
            new = {tuple(v[:4]): v[-1] for v in json.loads(current["values_json"])}
            changes.append(sum(old[k] != new[k] for k in old.keys() & new.keys()))
        result.append(
            dict(
                meet=race["meet"],
                race_no=race["race_no"],
                start_ms=race["start_ms"],
                observations=len(rows),
                schedule_versions=len({r["start_ms"] for r in rows}),
                pre_present=len(pre),
                pre_empty=sum(r["offset_minutes"] > 0 and r["status"] == "empty" for r in rows),
                changed_common_selections=changes,
                first_pre_present_ms=min((r["received_ms"] for r in pre), default=None),
                post_present=sum(
                    r["offset_minutes"] < 0 and r["status"] == "present" for r in rows
                ),
                conclusion=(
                    "pre_scheduled_start_changes_observed"
                    if any(changes)
                    else "pre_scheduled_start_values_observed"
                    if pre
                    else "no_pre_start_values_observed_yet"
                ),
            )
        )
    return result


def tick(db, client, key, day, now, *, baseline=False):
    now_ms = stamp(now)
    last = db.execute("SELECT max(requested_ms) FROM responses WHERE kind='plan'").fetchone()[0]
    if last is None or now_ms - last >= 600_000:
        for meet in MEETS:
            try:
                items, _ids, _requested, observed = request(db, client, key, "plan", meet, day)
                schedule = parse_schedule(items, meet, day, observed)
                with db:
                    db.execute("UPDATE schedule SET active=0 WHERE meet=?", (meet,))
                    db.executemany(
                        "INSERT INTO schedule VALUES(?,?,?,?,?,?) ON CONFLICT(meet,race_no) "
                        "DO UPDATE SET start_ms=excluded.start_ms,"
                        "source_start_ms=excluded.source_start_ms,"
                        "observed_ms=excluded.observed_ms,active=1",
                        schedule,
                    )
            except RuntimeError:
                raise
            except Exception as exc:
                emit("schedule_error", meet=meet, error=type(exc).__name__)
    schedule = db.execute("SELECT * FROM schedule WHERE active=1").fetchall()
    tasks = []
    for row, offset in due(schedule, now_ms):
        exists = db.execute(
            "SELECT 1 FROM observations WHERE meet=? AND race_no=? AND start_ms=? "
            "AND offset_minutes=?",
            (row["meet"], row["race_no"], row["start_ms"], offset),
        ).fetchone()
        if not exists:
            tasks.append((row, offset))
    meets = {row["meet"] for row, _ in tasks}
    if baseline:
        meets |= {row["meet"] for row in schedule}
    for meet in sorted(meets):
        try:
            items, ids, requested, received = request(db, client, key, "odds", meet, day)
            grouped = normalize(items, meet, day)
            for row, offset in tasks:
                if row["meet"] == meet:
                    save_observation(
                        db, row, offset, grouped.get(row["race_no"], []), ids, requested, received
                    )
            emit(
                "odds_response",
                meet=meet,
                rows=len(items),
                races={r: len(v) for r, v in grouped.items()},
                response_ids=ids,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            latest = db.execute(
                "SELECT id,requested_ms,received_ms FROM responses WHERE kind='odds' "
                "AND meet=? ORDER BY id DESC LIMIT 1",
                (meet,),
            ).fetchone()
            for row, offset in tasks:
                if row["meet"] == meet:
                    save_observation(
                        db,
                        row,
                        offset,
                        [],
                        [latest["id"]] if latest else [],
                        latest["requested_ms"] if latest else now_ms,
                        latest["received_ms"] or now_ms if latest else now_ms,
                        error=True,
                    )
            emit("odds_error", meet=meet, error=type(exc).__name__)
    # No arbitrary classification as 'real-time': timestamps are relative to published schedule.
    report = dict(
        day=str(day),
        checked_at=datetime.now(KST).isoformat(),
        requests=db.execute("SELECT count(*) FROM responses").fetchone()[0],
        races=comparison(db),
    )
    return report, max((r["start_ms"] for r in schedule), default=0)


def emit(event, **values):
    print(json.dumps(dict(event=event, **values), ensure_ascii=False), flush=True)


def execute(day, *, apply=False, watch=False):
    if not apply:
        emit("planned", day=str(day), offsets=OFFSETS, local_only=True)
        return 0
    if day != datetime.now(KST).date():
        emit("outside_test_date", day=str(day))
        return 0  # Before filesystem, credentials or network.
    folder = directory(day)
    secure_directory(folder)
    fd = open_regular(folder / "collector.lock", os.O_CREAT | os.O_RDWR)
    with os.fdopen(fd, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit("already_running")
            return 0
        settings = Settings(_env_file=ROOT / ".env")
        if settings.data_go_kr_service_key is None:
            raise ValueError("missing_api_key")
        key = settings.data_go_kr_service_key.get_secret_value()
        db = connect(folder)
        try:
            with httpx.Client(
                base_url="https://apis.data.go.kr/B551015/", timeout=18, follow_redirects=False
            ) as client:
                first = not db.execute(
                    "SELECT 1 FROM responses WHERE kind='odds' LIMIT 1"
                ).fetchone()
                while datetime.now(KST).date() == day:
                    report, last_start = tick(
                        db, client, key, day, datetime.now(KST), baseline=first
                    )
                    first = False
                    write_status(folder / "report.json", report)
                    if not watch or (
                        last_start and stamp(datetime.now(KST)) > last_start + 12 * 60_000
                    ):
                        break
                    time.sleep(20)
        finally:
            db.close()
    emit("finished", day=str(day), database=str(folder / "snapshots.sqlite3"))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    try:
        return execute(args.date, apply=args.apply, watch=args.watch)
    except Exception as exc:
        emit("failed", error=type(exc).__name__)
        if isinstance(exc, RuntimeError) and str(exc) in {
            "probe_request_budget_exhausted",
            "source_quota_stop",
        }:
            return 0  # Do not let launchd restart a quota-blocked experiment.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

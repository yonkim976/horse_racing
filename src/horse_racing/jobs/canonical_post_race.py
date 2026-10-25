"""Capture, validate and append official post-race data to Supabase only.

No operational SQLite is opened. Immutable annual score sources are untouched.
Capture is read-only against Supabase; --apply replays a captured artifact after
rechecking source hashes, natural keys and existing values in one transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from horse_racing.collectors.kra_api import response_body
from horse_racing.collectors.kra_text import KraTextClient
from horse_racing.jobs.local_race_day import LocalKraApiClient, load_settings
from horse_racing.parsers.dacom11 import parse_dacom11_report
from horse_racing.parsers.horse_history import parse_meet_code
from horse_racing.parsers.race_section import MEET_SECTION_SPECS
from horse_racing.parsers.race_supplemental import StewardReportItem
from horse_racing.services.race_passing import CORNER_POINTS

ROOT = Path(__file__).resolve().parents[3]
KST = ZoneInfo("Asia/Seoul")
ENDPOINTS = {
    "sections": "/API4_3/raceResult_3",
    "groups": "/API303/corner_rank",
    "race_detail": "/API6_1/raceDetailSectionRecord_1",
    "stewards": "/API215/JudgeReport",
}
DETAIL_GROUPS = {
    1: {
        "S1F": "passrankS1f",
        "1C": "passrankG8f_1c",
        "2C": "passrankG6f_2c",
        "3C": "passrankG4f_3c",
        "4C": "passrankG3f_4c",
        "G1F": "passrankG1f",
    },
    3: {
        "S1F": "passrankS1f",
        "G8F": "passrankG8f_1c",
        "G6F": "passrankG6f_2c",
        "G4F": "passrankG4f_3c",
        "G3F": "passrankG3f_4c",
        "G2F": "passrankG2f",
        "G1F": "passrankG1f",
    },
}
DETAIL_GROUPS[2] = DETAIL_GROUPS[1]
DETAIL_GROUPS[4] = DETAIL_GROUPS[3]
BUSAN_EXTRA = {
    "buS1fTime": ("S-1F", "segment"),
    "bu_10_8fTime": ("10-8F", "segment"),
    "bu_8_6fTime": ("8-6F", "segment"),
    "bu_6_4fTime": ("6-4F", "segment"),
    "bu_4_2fTime": ("4-2F", "segment"),
    "bu_2fGTime": ("2F-G", "segment"),
    "bu_3fGTime": ("G3F", "closing"),
    "bu_1fGTime": ("G1F", "closing"),
}
SNAPSHOT_SQL = """
SELECT c.kra_meet_code AS meet,r.race_date_local::text AS race_day,
       r.id AS race_id,r.race_number,r.distance_m,e.id AS entry_id,
       e.horse_number,h.kra_horse_id,e.scratched,
       z.finish_position,z.finish_time_ms,z.rank_remark
FROM races r JOIN racecourses c ON c.id=r.racecourse_id
JOIN race_entries e ON e.race_id=r.id JOIN horses h ON h.id=e.horse_id
LEFT JOIN race_results z ON z.race_entry_id=e.id
WHERE r.race_date_local BETWEEN %s AND %s AND r.status='completed'
ORDER BY 1,2,4,7
"""


class SourceMismatch(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SourceMismatch(message)


def millis(value):
    if value in (None, "", "-", "X"):
        return None
    number = Decimal(str(value))
    require(number.is_finite() and number >= 0, "invalid_time")
    return int(number * 1000) if number else None


def notation(value):
    return re.sub(r"\s+", "", str(value or ""))


def same_horse_label(text_name, api_name, meet):
    """Accept only the verified Busan visitor prefix alias, after the ID check.

    Do not strip arbitrary brackets or accept an unprefixed/different horse name.
    Original API/Text labels remain intact in their source documents.
    """
    left, right = notation(text_name), notation(api_name)
    if left == right:
        return True
    if meet != 1:
        return False
    aliases = [re.fullmatch(r"\[(?:부|영남)\](.+)", name) for name in (left, right)]
    return all(aliases) and aliases[0].group(1) == aliases[1].group(1)


def write_json(path, value):
    # Only new captures/results, never an existing research source or backup.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def digest_file(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def document(fetched, path):
    with path.open("xb") as handle:
        handle.write(fetched.body)
    return {
        "source_url": fetched.source_url,
        "endpoint": getattr(fetched, "endpoint", "dacom11"),
        "operation": getattr(fetched, "operation", "dacom11"),
        "request_params_json": json.dumps(dict(getattr(fetched, "public_params", {}))),
        "requested_at_ms": fetched.requested_at_ms,
        "retrieved_at_ms": fetched.retrieved_at_ms,
        "http_status_code": fetched.status_code,
        "content_type": fetched.content_type,
        "response_bytes": len(fetched.body),
        "local_path": str(path.relative_to(ROOT)),
        "sha256": digest_file(path),
    }


def fetch_api(client, kind, meet, day, directory):
    rows, documents = [], []
    endpoint = ENDPOINTS[kind]
    total = None
    for index, page in enumerate(
        client.iter_pages(
            endpoint=endpoint,
            operation=endpoint.rsplit("/", 1)[-1],
            public_params={"meet": meet, "rc_date": day.replace("-", ""), "_type": "json"},
            page_size=1000,
        ),
        1,
    ):
        documents.append(document(page, directory / f"{meet}_{day}_{kind}_{index}.json"))
        body = response_body(page.payload)
        total = int(body.get("totalCount") or 0)
        items = body.get("items") or {}
        if isinstance(items, dict):
            items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]
        require(isinstance(items, list), f"invalid_items:{kind}")
        rows.extend(items)
    require(len(rows) == total, f"page_count:{kind}")
    for row in rows:
        require(parse_meet_code(row.get("meet")) == meet, f"wrong_meet:{kind}")
        require(str(row.get("rcDate")) == day.replace("-", ""), f"wrong_date:{kind}")
    return rows, documents


def normalize_day(meet, day, snapshot, data, text_races, *, require_stewards=True):
    """Natural-key joins only; no inferred time kind or fabricated groups."""
    target = {(r["race_number"], r["horse_number"]): r for r in snapshot}
    expected_races = {r["race_number"] for r in snapshot}
    require(len(target) == len(snapshot), "duplicate_target_key")
    by_race = {}
    for row in snapshot:
        by_race.setdefault(row["race_number"], []).append(row)
    text = {}
    for race in text_races:
        require(parse_meet_code(race.meet_name) == meet, "text_wrong_meet")
        require(race.race_date.isoformat() == day, "text_wrong_date")
        require(race.race_number not in text, "text_duplicate_race")
        text[race.race_number] = race
    require(set(text) == expected_races, "text_race_coverage")
    sections, groups, stewards, issues = [], [], [], []
    seen = set()
    raw_by_entry = {}
    for raw in data["sections"]:
        key = (int(raw["rcNo"]), int(raw["chulNo"]))
        require(key not in seen, f"duplicate_api_entry:{key}")
        seen.add(key)
        require(key in target, f"api_unknown_entry:{key}")
        row = target[key]
        require(
            str(raw["hrNo"]).zfill(7) == row["kra_horse_id"].zfill(7), f"horse_id_mismatch:{key}"
        )
        require(int(raw["rcDist"]) == row["distance_m"], f"distance_mismatch:{key}")
        finish, rank = millis(raw.get("rcTime")), int(raw.get("ord") or 0)
        require(rank == row["finish_position"], f"db_rank_mismatch:{key}")
        require(finish == row["finish_time_ms"], f"db_finish_mismatch:{key}")
        if row["scratched"] and rank >= 90:
            require(finish is None, f"scratched_has_finish:{key}")
            require(
                all(
                    millis(raw.get(s.time_field)) is None
                    and not int(raw.get(s.position_field) or 0)
                    for s in MEET_SECTION_SPECS[meet]
                ),
                f"scratched_has_sections:{key}",
            )
            issues.append(
                {
                    "entry_id": row["entry_id"],
                    "race_number": key[0],
                    "horse_number": key[1],
                    "kind": "scratched_no_section",
                    "official_rank_code": rank,
                }
            )
            continue
        matches = [e for e in text[key[0]].entries if e.horse_number == key[1]]
        require(len(matches) == 1, f"text_entry_coverage:{key}")
        entry = matches[0]
        require(
            same_horse_label(entry.horse_name, raw["hrName"], meet),
            f"text_horse_name_mismatch:{key}",
        )
        if notation(entry.horse_name) != notation(raw["hrName"]):
            issues.append(
                {
                    "entry_id": row["entry_id"],
                    "race_number": key[0],
                    "horse_number": key[1],
                    "kind": "verified_busan_visitor_prefix_alias",
                    "api_name": raw["hrName"],
                    "text_name": entry.horse_name,
                }
            )
        if 1 <= rank < 90:
            require(not row["scratched"], f"finished_scratched:{key}")
            require(entry.finish_position == rank, f"text_rank_mismatch:{key}")
            require(entry.finish_time_ms == finish, f"text_finish_mismatch:{key}")
        else:
            if rank == 92 and not entry.finish_rank_raw:
                require(
                    "주행중지" in (entry.margin_text or "") and entry.finish_time_ms in (None, 0),
                    f"text_stopped_status_mismatch:{key}",
                )
            issues.append(
                {
                    "entry_id": row["entry_id"],
                    "race_number": key[0],
                    "horse_number": key[1],
                    "kind": "special_finish_status",
                    "official_rank_code": rank,
                }
            )
        stopped = rank == 92 and "주행중지" in (entry.margin_text or "") and finish is None
        if stopped:
            # Official missing-position sentinel; keep the API document unchanged.
            raw = dict(raw)
            fields = {s.position_field for s in MEET_SECTION_SPECS[meet] if s.position_field}
            sentinels = [field for field in sorted(fields) if int(raw.get(field) or 0) == 99]
            for field in sentinels:
                raw[field] = 0
            if sentinels:
                issues.append(
                    {
                        "entry_id": row["entry_id"],
                        "kind": "stopped_position_sentinel",
                        "official_value": 99,
                        "fields": sentinels,
                    }
                )
        if meet in (1, 2) and entry.passing_order_raw:
            pieces = entry.passing_order_raw.split("-")
            require(len(pieces) == 6, f"text_rank_shape:{key}")
            for point, part in zip(("S1F", "1C", "2C", "3C", "4C", "G1F"), pieces, strict=True):
                field = next(s.position_field for s in MEET_SECTION_SPECS[meet] if s.code == point)
                api_rank = int(raw.get(field) or 0)
                text_rank = int(re.sub(r"\D", "", part) or 0)
                if stopped and text_rank == 99:
                    text_rank = 0
                if api_rank and text_rank:
                    require(api_rank == text_rank, f"text_rank_mismatch:{key}:{point}")
                elif bool(api_rank) != bool(text_rank):
                    issues.append(
                        {
                            "entry_id": row["entry_id"],
                            "point": point,
                            "kind": "text_rank_availability_mismatch",
                            "api_rank": api_rank or None,
                            "text_rank": text_rank or None,
                        }
                    )
        values = {}

        def add(
            point,
            kind,
            value,
            position,
            source,
            field,
            *,
            key=key,
            finish=finish,
            values=values,
            row=row,
        ):
            elapsed = millis(value)
            pos = int(position or 0) or None
            if elapsed is None and pos is None:
                return
            require(
                pos is None or 1 <= pos <= len(by_race[key[0]]), f"invalid_position:{key}:{point}"
            )
            require(
                elapsed is None or finish is None or elapsed <= finish,
                f"time_exceeds_finish:{key}:{point}",
            )
            values[(point, kind)] = [row["entry_id"], point, kind, elapsed, pos, source, field]

        for spec in MEET_SECTION_SPECS[meet]:
            kind = "closing" if meet == 2 and spec.code in {"G3F", "G1F"} else "cumulative"
            position = raw.get(spec.position_field) if spec.position_field else None
            if meet == 2 and spec.code == "G3F":
                require(not int(position or 0), f"jeju_unexpected_g3f_rank:{key}")
                position = None
            add(spec.code, kind, raw.get(spec.time_field), position, "api4_3", spec.time_field)
        if meet in (3, 4):
            for field, (point, kind) in BUSAN_EXTRA.items():
                add(point, kind, raw.get(field), None, "api4_3", field)
        if meet == 1:
            add(
                "G3F",
                "closing",
                Decimal(entry.g3f_ms) / 1000 if entry.g3f_ms else None,
                None,
                "official_dacom11",
                "G-3F",
            )
            add(
                "G1F",
                "closing",
                Decimal(entry.g1f_ms) / 1000 if entry.g1f_ms else None,
                None,
                "official_dacom11",
                "G-1F",
            )
        # These are explicit columns of the official text, not value-based inference.
        for point, text_ms in (("S1F", entry.s1f_ms), ("G3F", entry.g3f_ms), ("G1F", entry.g1f_ms)):
            kind = "cumulative" if point == "S1F" else "closing"
            value = values.get((point, kind))
            if text_ms is not None:
                require(
                    value is not None and value[3] == text_ms,
                    f"text_section_mismatch:{key}:{point}",
                )
            if 1 <= rank < 90:
                require(
                    text_ms is not None and value is not None and value[3] is not None,
                    f"missing_required_time:{key}:{point}",
                )
        for point, text_ms in entry.corner_times_ms.items():
            value = values.get((point, "cumulative"))
            require(
                value is not None and value[3] == text_ms, f"text_corner_mismatch:{key}:{point}"
            )
        for point in ("G3F", "G1F"):
            cumulative = values.get((point, "cumulative"))
            closing = values.get((point, "closing"))
            if cumulative and closing and cumulative[3] and closing[3] and finish:
                if cumulative[3] + closing[3] != finish:
                    issues.append(
                        {
                            "entry_id": row["entry_id"],
                            "race_number": key[0],
                            "horse_number": key[1],
                            "kind": "time_sum_mismatch",
                            "point": point,
                            "cumulative_ms": cumulative[3],
                            "closing_ms": closing[3],
                            "finish_ms": finish,
                        }
                    )
                    # Raw evidence preserved; conflicting pair is not served as authoritative.
                    del values[(point, "cumulative")]
                    del values[(point, "closing")]
        sections.extend(values.values())
        raw_by_entry[key] = raw
    required = {key for key, row in target.items() if not row["scratched"]}
    require(required <= seen, f"missing_api_runners:{sorted(required - seen)}")
    for key, row in target.items():
        if key not in seen:
            issues.append(
                {
                    "entry_id": row["entry_id"],
                    "race_number": key[0],
                    "horse_number": key[1],
                    "kind": "scratched_no_section",
                }
            )
    detail = {int(r["rcNo"]): r for r in data["race_detail"]}
    require(
        len(detail) == len(data["race_detail"]) and set(detail) == expected_races,
        "detail_race_coverage",
    )
    summary = {int(r["rcNo"]): r for r in data["groups"]}
    require(
        len(summary) == len(data["groups"]) and set(summary) == expected_races,
        "group_race_coverage",
    )
    for number, raw in summary.items():
        require(
            int(detail[number]["rcDist"]) == by_race[number][0]["distance_m"],
            f"detail_distance:{number}",
        )
        for corner, point in CORNER_POINTS[meet].items():
            value = str(raw.get(f"corner_{corner}") or "").strip()
            if value in {"", "-", "X", "0"}:
                continue
            other = detail[number].get(DETAIL_GROUPS[meet][point])
            require(notation(value) == notation(other), f"api_group_conflict:{number}:{point}")
            numbers = [int(n) for n in re.findall(r"\d+", value)]
            require(len(numbers) == len(set(numbers)), f"group_duplicate_horse:{number}:{point}")
            require(
                set(numbers) <= {r["horse_number"] for r in by_race[number] if not r["scratched"]},
                f"group_unknown_horse:{number}:{point}",
            )
            spec = next(s for s in MEET_SECTION_SPECS[meet] if s.code == point)
            expected = {
                key[1]
                for key, r in raw_by_entry.items()
                if key[0] == number and int(r.get(spec.position_field) or 0) > 0
            }
            require(expected <= set(numbers), f"rank_group_coverage:{number}:{point}")
            if set(numbers) != expected:
                # E.g. Jeju 1400m publishes a 2C group and time but zero sj_2cOrd.
                # Keep the official group; do not invent runner-level ranks.
                issues.append(
                    {
                        "race_number": number,
                        "point": point,
                        "kind": "individual_rank_not_provided",
                        "horse_numbers": sorted(set(numbers) - expected),
                    }
                )
            groups.append([by_race[number][0]["race_id"], point, value])
    seen_reports = set()
    for raw in data["stewards"]:
        item = StewardReportItem.model_validate(raw)
        require(
            item.race_number in expected_races and item.race_number not in seen_reports,
            "steward_race_key",
        )
        require(item.judgement is not None, f"empty_steward:{item.race_number}")
        seen_reports.add(item.race_number)
        stewards.append(
            [
                meet,
                day,
                item.race_number,
                item.weather,
                item.members,
                item.judgement,
                item.additional_judgement,
                item.jockey_change_note,
            ]
        )
    if require_stewards:
        require(seen_reports == expected_races, "steward_race_coverage")
    require({r[0] for r in groups} == {r["race_id"] for r in snapshot}, "missing_race_groups")
    return {
        "meet": meet,
        "race_day": day,
        "target_snapshot": snapshot,
        "sections": sections,
        "groups": groups,
        "stewards": stewards,
        "issues": issues,
    }


def capture(connection, settings, start, end, directory):
    snapshot = connection.execute(SNAPSHOT_SQL, (start, end)).fetchall()
    require(bool(snapshot), "no_completed_races")
    days = sorted({(r["meet"], r["race_day"]) for r in snapshot})
    results = []
    with (
        LocalKraApiClient(settings.data_go_kr_service_key.get_secret_value()) as api_client,
        KraTextClient() as text_client,
    ):
        feeds = {}
        for meet, day in days:
            data, docs = {}, []
            for kind in ENDPOINTS:
                data[kind], fetched_docs = fetch_api(api_client, kind, meet, day, directory)
                docs.extend(fetched_docs)
            feed = 3 if meet == 4 else meet
            if feed not in feeds:
                feeds[feed] = list(
                    text_client.iter_files(
                        meet=feed,
                        file_type="dacom11",
                        code_name="경마성적표",
                        start_date=date.fromisoformat(start),
                        end_date=date.fromisoformat(end),
                    )
                )
            files = [f for f in feeds[feed] if str(f.file_date) == day]
            require(len(files) == 1, f"text_file_coverage:{meet}:{day}")
            fetched = text_client.fetch_file(files[0])
            docs.append(document(fetched, directory / f"{meet}_{day}_dacom11.rpt"))
            normalized = normalize_day(
                meet,
                day,
                [r for r in snapshot if r["meet"] == meet and r["race_day"] == day],
                data,
                parse_dacom11_report(fetched.body),
            )
            normalized["documents"] = docs
            path = directory / f"{meet}_{day}_canonical.json"
            write_json(path, normalized)
            results.append(str(path.relative_to(ROOT)))
            print(
                json.dumps(
                    {
                        "phase": "validated",
                        "meet": meet,
                        "date": day,
                        "races": len(normalized["stewards"]),
                        "sections": len(normalized["sections"]),
                        "groups": len(normalized["groups"]),
                        "issues": normalized["issues"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    manifest = {
        "start": start,
        "end": end,
        "captured_at_ms": int(time.time() * 1000),
        "batches": [{"path": path, "sha256": digest_file(ROOT / path)} for path in results],
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


def apply_batch(connection, artifact, expected_hash):
    require(artifact.resolve().is_relative_to((ROOT / "data/research").resolve()), "artifact_path")
    require(digest_file(artifact) == expected_hash, "artifact_hash_mismatch")
    batch = json.loads(artifact.read_text(encoding="utf-8"))
    for doc in batch["documents"]:
        path = (ROOT / doc["local_path"]).resolve()
        require(path.is_relative_to(artifact.parent.resolve()), "source_document_path")
        require(digest_file(path) == doc["sha256"], "source_document_hash_mismatch")
    meet, day = batch["meet"], batch["race_day"]
    sections, groups, stewards = batch["sections"], batch["groups"], batch["stewards"]
    source_file = str(artifact.relative_to(ROOT))
    now = int(time.time() * 1000)
    with connection.transaction():
        connection.execute("SET LOCAL lock_timeout='5s'")
        connection.execute("SET LOCAL statement_timeout='60s'")
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (26071005,))
        current = connection.execute(SNAPSHOT_SQL, (day, day)).fetchall()
        current = [r for r in current if r["meet"] == meet]
        require(current == batch["target_snapshot"], f"target_changed:{meet}:{day}")
        existing = connection.execute(
            "SELECT id,source_sha256 FROM race_point_source_batches WHERE source_file=%s",
            (source_file,),
        ).fetchone()
        if existing:
            require(existing["source_sha256"] == expected_hash, "existing_batch_hash_mismatch")
            batch_id = existing["id"]
        else:
            batch_id = connection.execute(
                """INSERT INTO race_point_source_batches
                (source_file,source_sha256,meet_code,race_year,section_row_count,
                 passing_group_row_count,loaded_at_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)
                RETURNING id""",
                (source_file, expected_hash, meet, int(day[:4]), len(sections), len(groups), now),
            ).fetchone()["id"]
        # Conflicting authoritative values are not overwritten. Same artifact is idempotent.
        existing_sections = connection.execute(
            """SELECT s.* FROM race_section_times s
            JOIN race_entries e ON e.id=s.race_entry_id JOIN races r ON r.id=e.race_id
            JOIN racecourses c ON c.id=r.racecourse_id
            WHERE c.kra_meet_code=%s AND r.race_date_local=%s""",
            (meet, day),
        ).fetchall()
        prior = {
            (r["race_entry_id"], r["point_code"], r["time_kind"]): r for r in existing_sections
        }
        new_sections = []
        for row in sections:
            old = prior.get(tuple(row[:3]))
            if old:
                require(
                    [
                        old["elapsed_time_ms"],
                        old["position_raw"],
                        old["source_name"],
                        old["source_field"],
                        old["source_batch_id"],
                    ]
                    == [*row[3:], batch_id],
                    f"existing_section_conflict:{row[:3]}",
                )
            else:
                new_sections.append([*row, batch_id])
        with connection.cursor() as cursor:
            if new_sections:
                with cursor.copy("""COPY race_section_times
                    (race_entry_id,point_code,time_kind,elapsed_time_ms,position_raw,
                     source_name,source_field,source_batch_id) FROM STDIN""") as copy:
                    for row in new_sections:
                        copy.write_row(row)
            old_groups = connection.execute(
                """SELECT g.* FROM race_passing_groups g
                JOIN races r ON r.id=g.race_id JOIN racecourses c ON c.id=r.racecourse_id
                WHERE c.kra_meet_code=%s AND r.race_date_local=%s""",
                (meet, day),
            ).fetchall()
            prior_groups = {(r["race_id"], r["point_code"]): r for r in old_groups}
            new_groups = []
            for row in groups:
                old = prior_groups.get(tuple(row[:2]))
                if old:
                    require(
                        [old["notation_raw"], old["source_batch_id"]] == [row[2], batch_id],
                        f"existing_group_conflict:{row[:2]}",
                    )
                else:
                    new_groups.append([*row, batch_id])
            if new_groups:
                with cursor.copy("""COPY race_passing_groups
                    (race_id,point_code,notation_raw,source_batch_id) FROM STDIN""") as copy:
                    for row in new_groups:
                        copy.write_row(row)
            prior_reports = connection.execute(
                """SELECT * FROM race_steward_reports
                WHERE meet_code=%s AND race_date_local=%s""",
                (meet, day),
            ).fetchall()
            prior_reports = {r["race_number"]: r for r in prior_reports}
            report_rows = []
            for row in stewards:
                old = prior_reports.get(row[2])
                if old:
                    require(
                        [
                            old[k]
                            for k in (
                                "weather",
                                "members",
                                "judgement",
                                "additional_judgement",
                                "jockey_change_note",
                            )
                        ]
                        == row[3:],
                        f"existing_steward_conflict:{meet}:{day}:{row[2]}",
                    )
                else:
                    report_rows.append([*row, now])
            if report_rows:
                cursor.executemany(
                    """INSERT INTO race_steward_reports
                    (meet_code,race_date_local,race_number,weather,members,judgement,
                     additional_judgement,jockey_change_note,observed_at_ms)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    report_rows,
                )
            for table in ("race_section_times", "race_passing_groups"):
                # Table names are fixed developer constants, never external inputs.
                count = connection.execute(
                    f"SELECT count(*) AS n FROM {table} WHERE source_batch_id=%s", (batch_id,)
                ).fetchone()["n"]
                expected = len(sections) if table == "race_section_times" else len(groups)
                require(count == expected, f"inserted_count:{table}")
            changed = len(new_sections) + len(new_groups) + len(report_rows)
            if changed:
                run_id = connection.execute(
                    """INSERT INTO ingestion_runs
                    (source,data_type,started_at_ms,completed_at_ms,status,
                     records_fetched,records_written)
                    VALUES ('KRA API + official dacom11','canonical_post_race',%s,%s,
                    'completed',%s,%s) RETURNING id""",
                    (now, int(time.time() * 1000), len(batch["target_snapshot"]), changed),
                ).fetchone()["id"]
                cursor.executemany(
                    """INSERT INTO source_documents
                    (ingestion_run_id,source_url,endpoint,operation,request_params_json,
                     requested_at_ms,retrieved_at_ms,http_status_code,content_type,
                     response_bytes,local_path,sha256)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [
                        [
                            run_id,
                            *[
                                doc[k]
                                for k in (
                                    "source_url",
                                    "endpoint",
                                    "operation",
                                    "request_params_json",
                                    "requested_at_ms",
                                    "retrieved_at_ms",
                                    "http_status_code",
                                    "content_type",
                                    "response_bytes",
                                    "local_path",
                                    "sha256",
                                )
                            ],
                        ]
                        for doc in batch["documents"]
                    ],
                )
            else:
                run_id = None
    return {
        "meet": meet,
        "race_day": day,
        "batch_id": batch_id,
        "run_id": run_id,
        "section_rows_added": len(new_sections),
        "group_rows_added": len(new_groups),
        "steward_rows_added": len(report_rows),
        "issues": batch["issues"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat, default=datetime.now(KST).date())
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    require(bool(args.start) != bool(args.manifest), "choose_start_or_manifest")
    require(not args.apply or args.manifest is not None, "capture_first_then_apply_manifest")
    settings = load_settings()
    url = make_url(settings.database_url).set(drivername="postgresql")
    with psycopg.connect(
        url.render_as_string(hide_password=False), autocommit=True, row_factory=dict_row
    ) as connection:
        if args.manifest:
            path = args.manifest.resolve()
            require(path.is_relative_to((ROOT / "data/research").resolve()), "manifest_path")
            manifest = json.loads(path.read_text(encoding="utf-8"))
            results = []
            for item in manifest["batches"]:
                artifact = ROOT / item["path"]
                require(digest_file(artifact) == item["sha256"], "manifest_hash_mismatch")
                if args.apply:
                    result = apply_batch(connection, artifact, item["sha256"])
                    results.append(result)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
            if args.apply:
                output = path.parent / f"apply_{time.time_ns()}.json"
                write_json(output, results)
                print(json.dumps({"result_file": str(output.relative_to(ROOT))}))
        else:
            require(args.start <= args.end <= datetime.now(KST).date(), "invalid_date_range")
            directory = (
                ROOT
                / "data/research"
                / ("score_point_updates_" + datetime.now(KST).strftime("%Y%m%d_%H%M%S"))
            )
            directory.mkdir(exist_ok=False)
            capture(connection, settings, str(args.start), str(args.end), directory)
            print(
                json.dumps(
                    {
                        "manifest": str((directory / "manifest.json").relative_to(ROOT)),
                        "database_writes": False,
                    }
                )
            )


if __name__ == "__main__":
    main()

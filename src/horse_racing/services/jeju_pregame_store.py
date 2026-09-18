"""Append-only observed pages and conservative as-of declaration replay.

No operating DB writes or prediction publication. Availability is the local
admission time AFTER raw bytes and parsing metadata have been written, never a
schedule, HTTP Last-Modified value, or backdated notice time.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from horse_racing.parsers.jeju_pregame import VERSION, parse_page


def now_ms():
    return time.time_ns() // 1_000_000


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def timestamp_ms(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("Explicit time zone required")
    return int(dt.timestamp() * 1000)


def write_new(path, body):
    # Each observation has its own UUID directory; files cannot be overwritten.
    with path.open("xb") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())


class PregameStore:
    def __init__(self, root: Path):
        self.root = root
        (root / "observations").mkdir(parents=True, exist_ok=True)
        self.clock = now_ms

    def record(
        self,
        *,
        kind,
        url,
        body,
        requested_ms,
        retrieved_ms,
        status_code,
        encoding="euc-kr",
        request_race=None,
        error=None,
        headers=None,
    ):
        if not 0 < requested_ms <= retrieved_ms <= self.clock():
            raise ValueError("Invalid observation clock")
        observation_id = uuid.uuid4().hex
        target = self.root / "observations" / observation_id
        target.mkdir()
        write_new(target / "raw.html", body)
        parsed = None
        parse_error = error
        if parse_error is None:
            try:
                if status_code != 200:
                    raise ValueError(f"HTTP status {status_code}")
                parsed = parse_page(kind, body, encoding)
                if request_race and (parsed.get("race_date"), parsed.get("race_number")) != tuple(
                    request_race
                ):
                    raise ValueError("Requested race does not match document race")
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                parsed = None
                parse_error = f"{type(exc).__name__}: {exc}"
        payload = dict(
            observation_id=observation_id,
            kind=kind,
            url=url,
            requested_ms=requested_ms,
            retrieved_ms=retrieved_ms,
            status_code=status_code,
            encoding=encoding,
            request_race=request_race,
            response_headers=headers or {},
            raw_sha256=digest(body),
            parser_version=VERSION,
            parsed=parsed,
            error=parse_error,
            semantic_sha256=digest(canonical(parsed)) if parsed is not None else None,
        )
        payload_bytes = canonical(payload)
        write_new(target / "observation.json", payload_bytes)
        # A crash before this final marker leaves an ineligible observation.
        admitted = self.clock()
        if admitted < retrieved_ms:
            raise ValueError("Clock moved backwards")
        write_new(
            target / "admission.json",
            canonical(dict(admitted_ms=admitted, observation_sha256=digest(payload_bytes))),
        )
        return {**payload, "known_at_ms": admitted}

    def observations(self, cutoff_ms=None):
        result = []
        for path in (self.root / "observations").iterdir():
            if not (path / "admission.json").exists():
                continue
            a = json.loads((path / "admission.json").read_bytes())
            if cutoff_ms is not None and a["admitted_ms"] > cutoff_ms:
                continue
            raw = (path / "raw.html").read_bytes()
            body = (path / "observation.json").read_bytes()
            if digest(body) != a["observation_sha256"]:
                raise ValueError("Observation tampering")
            p = json.loads(body)
            if digest(raw) != p["raw_sha256"] or p["observation_id"] != path.name:
                raise ValueError("Raw content/identity tampering")
            if not 0 < p["requested_ms"] <= p["retrieved_ms"] <= a["admitted_ms"]:
                raise ValueError("Invalid stored clock")
            if p["parsed"] is not None and digest(canonical(p["parsed"])) != p["semantic_sha256"]:
                raise ValueError("Semantic hash mismatch")
            result.append({**p, "known_at_ms": a["admitted_ms"]})
        return sorted(
            result, key=lambda p: (p["known_at_ms"], p["retrieved_ms"], p["observation_id"])
        )


def provenance(p):
    return dict(
        observation_id=p["observation_id"],
        source_url=p["url"],
        observed_at_ms=p["retrieved_ms"],
        known_at_ms=p["known_at_ms"],
        raw_sha256=p["raw_sha256"],
    )


def latest_observation(pages):
    """Ambiguous simultaneous revisions must not be ordered by random UUID."""
    if not pages:
        return None
    latest = pages[-1]
    simultaneous = [p for p in pages if p["known_at_ms"] == latest["known_at_ms"]]
    versions = {(p["semantic_sha256"], p["error"]) for p in simultaneous}
    if len(versions) > 1:
        return {**latest, "parsed": None, "error": "ambiguous_same_time_revision"}
    return latest


def replay(store, cutoff_ms, *, race_dates=None):
    observations = store.observations(cutoff_ms)
    schedules = [p for p in observations if p["kind"] == "schedule"]
    schedule = latest_observation(schedules)
    if not schedule or schedule["parsed"] is None:
        return dict(cutoff_ms=cutoff_ms, races=[], status="no_valid_latest_schedule")
    result = []
    for race in schedule["parsed"]["races"]:
        day, no = race["race_date"], race["race_number"]
        if race_dates and day not in race_dates:
            continue
        if timestamp_ms(race["scheduled_start_at"]) <= cutoff_ms:
            continue  # No retrospective after-start feature admission.
        cards = [
            p
            for p in observations
            if p["kind"] == "card" and tuple(p["request_race"] or ()) == (day, no)
        ]
        entry = dict(
            **race,
            declaration_complete=False,
            runners=[],
            issues=[],
            source=provenance(schedule),
            prediction_generated=False,
        )
        latest = latest_observation(cards)
        if not latest or latest["parsed"] is None:
            entry["issues"].append("missing_or_invalid_latest_card")
            result.append(entry)
            continue
        card = latest["parsed"]
        entry["card_source"] = provenance(latest)
        runners = {
            r["horse_number"]: {
                **r,
                "field_status": "declared",
                "body_weight_kg": None,
                "body_weight_delta_kg": None,
                "sources": {"declaration": provenance(latest)},
            }
            for r in card["runners"]
        }
        entry["declaration_complete"] = (
            card["complete"] and len(runners) == race["declared_count"] == race["listed_count"]
        )
        if not entry["declaration_complete"]:
            entry["issues"].append("declared_listed_card_count_mismatch")
        previous = next(
            (
                p
                for p in reversed(cards[:-1])
                if p["parsed"] and p["parser_version"] == latest["parser_version"]
            ),
            None,
        )
        if previous:
            old = {r["horse_id"]: r for r in previous["parsed"]["runners"]}
            new = {r["horse_id"]: r for r in card["runners"]}
            entry["card_revision"] = dict(
                added=sorted(new.keys() - old.keys()),
                removed=sorted(old.keys() - new.keys()),
                changed=sorted(h for h in new.keys() & old.keys() if new[h] != old[h]),
            )
            if entry["card_revision"]["removed"]:
                entry["issues"].append("card_removal_requires_notice_reconciliation")
        change_pages = [p for p in observations if p["kind"] == "changes"]
        latest_changes = latest_observation(change_pages)
        entry["change_page_observed"] = bool(latest_changes and latest_changes["parsed"])
        if not entry["change_page_observed"]:
            entry["issues"].append("missing_or_invalid_latest_changes")
        # Preserve notices disappearing from a newer rolling page. Idempotent repeats
        # do not become new events just because the same HTML was polled again.
        seen = set()
        for p in change_pages:
            if not p["parsed"]:
                continue
            for notice in p["parsed"]["notices"]:
                if (notice["race_date"], notice["race_number"]) != (day, no):
                    continue
                key = digest(canonical(notice))
                if key in seen:
                    continue
                seen.add(key)
                horse = runners.get(notice["horse_number"])
                if horse is None or horse["horse_name"] != notice["horse_name"]:
                    entry["issues"].append("notice_identity_mismatch")
                    continue
                if notice["published_at"] and timestamp_ms(notice["published_at"]) > cutoff_ms:
                    entry["issues"].append("notice_future_publication")
                    continue
                if notice["kind"] == "withdrawal":
                    horse["field_status"] = "withdrawn_observed"
                    horse["sources"]["withdrawal"] = provenance(p)
                elif p["known_at_ms"] > latest["known_at_ms"]:
                    # A newer full card is authoritative for its declared jockey;
                    # don't overwrite it with an older observed notice.
                    if horse["jockey_name"] not in {
                        notice["old_jockey_name"],
                        notice["new_jockey_name"],
                    }:
                        entry["issues"].append("jockey_notice_chain_conflict")
                        continue
                    horse["jockey_name"] = notice["new_jockey_name"]
                    horse["jockey_id"] = None  # Name does not establish a new ID.
                    horse["burden_kg"] = notice["new_burden_kg"]
                    horse["sources"]["jockey_change"] = provenance(p)
        weights = [
            p
            for p in observations
            if p["kind"] == "weight" and tuple(p["request_race"] or ()) == (day, no)
        ]
        weight_page = latest_observation(weights)
        if weight_page and weight_page["parsed"]:
            p = weight_page
            for value in p["parsed"]["runners"]:
                horse = runners.get(value["horse_number"])
                if horse is None or horse["horse_id"] != value["horse_id"]:
                    entry["issues"].append("weight_identity_mismatch")
                    continue
                if value["body_weight_kg"] is not None and value["body_weight_kg"] > 0:
                    horse.update({k: value[k] for k in ["body_weight_kg", "body_weight_delta_kg"]})
                    horse["sources"]["body_weight"] = provenance(p)
        entry["track"] = None
        tracks = [p for p in observations if p["kind"] == "track"]
        track_page = latest_observation(tracks)
        if track_page and track_page["parsed"]:
            p = track_page
            value = p["parsed"]
            if (
                value["effective_at"][:10] == day
                and timestamp_ms(value["effective_at"]) <= cutoff_ms
            ):
                entry["track"] = {**value, "source": provenance(p)}
        if entry["track"] is None:
            entry["issues"].append("no_same_day_observed_track")
        entry["runners"] = list(runners.values())
        entry["eligible_numbers"] = [
            n for n, r in runners.items() if r["field_status"] == "declared"
        ]
        entry["body_weight_rows"] = sum(r["body_weight_kg"] is not None for r in runners.values())
        entry["change_coverage"] = "observed notices only; absence is not exhaustive proof"
        result.append(entry)
    return dict(
        cutoff_ms=cutoff_ms,
        status="declaration_replay_only",
        races=result,
        observation_count=len(observations),
        model_fit_count=0,
        predictions=0,
    )

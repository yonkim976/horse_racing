"""Complete, append-only regional API309 owner observations; no name-based merges."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select, text

from horse_racing.collectors.kra_api import response_body
from horse_racing.db.models import IngestionRun, Owner, OwnerCatalogSnapshot, SourceDocument

ENDPOINT = "/API309/horseOwnerInfo"
DATA_TYPE = "owner_catalog_full"
REGIONS = {1: {"서울"}, 3: {"영남", "부산경남", "부경"}, 2: {"제주"}}
LOCK_KEY = 260810309


@dataclass(frozen=True)
class OwnerObservation:
    meet_code: int
    kra_owner_id: str
    official_name_ko: str
    registration_date: date | None
    total_registered_horses: int
    current_owned_horses: int


def parse_owner(raw, meet, observed_on):
    number = str(raw.get("owNo", "")).strip().zfill(6)
    name = str(raw.get("owName") or "").strip()
    total = str(raw.get("totHorses", "")).strip()
    current = str(raw.get("ownerHorses", "")).strip()
    if (
        raw.get("meet") not in REGIONS[meet]
        or not re.fullmatch(r"\d{6}", number)
        or number == "000000"
        or not 1 <= len(name) <= 100
        or not re.fullmatch(r"\d+", total)
        or int(total) > 2_147_483_647
        or not re.fullmatch(r"\d+", current)
        or int(current) > int(total)
    ):
        raise ValueError("invalid_owner_identity_region_or_total")
    registered = str(raw.get("stDate") or "").strip()
    if registered in ("", "-"):
        registration_date = None
    elif re.fullmatch(r"\d{8}", registered):
        registration_date = date(int(registered[:4]), int(registered[4:6]), int(registered[6:]))
        if registration_date > observed_on:
            raise ValueError("future_owner_registration_date")
    else:
        raise ValueError("invalid_owner_registration_date")
    return OwnerObservation(meet, number, name, registration_date, int(total), int(current))


def fetch_catalog(client, directory, *, observed_on, page_size=250):
    """Archive all pages before validating them; any incomplete region aborts publication."""
    observations, evidence = [], []
    for meet in REGIONS:
        pages, rows, totals = [], [], set()
        for page in client.iter_pages(
            endpoint=ENDPOINT,
            operation="horseOwnerInfo",
            public_params={"meet": meet, "_type": "json"},
            page_size=page_size,
        ):
            page_no = int(page.public_params["pageNo"])
            path = directory / f"api309_{meet}_{page_no}.json"
            with path.open("xb") as handle:
                handle.write(page.body)
            doc = dict(
                source_url=page.source_url,
                endpoint=ENDPOINT,
                operation="horseOwnerInfo",
                request_params_json=json.dumps(dict(page.public_params), sort_keys=True),
                requested_at_ms=page.requested_at_ms,
                retrieved_at_ms=page.retrieved_at_ms,
                http_status_code=page.status_code,
                content_type=page.content_type,
                response_bytes=len(page.body),
                local_path=str(path),
                sha256=hashlib.sha256(page.body).hexdigest(),
            )
            body = response_body(page.payload)
            total = int(body.get("totalCount") or 0)
            if not 1 <= total <= 20_000 or page_no != len(pages) + 1:
                raise ValueError("invalid_owner_catalog_total_or_page")
            items = (body.get("items") or {}).get("item") or []
            items = [items] if isinstance(items, dict) else items
            if int(body.get("pageNo", page_no)) != page_no or not items:
                raise ValueError("empty_or_wrong_owner_catalog_page")
            totals.add(total)
            for raw in items:
                row = parse_owner(raw, meet, observed_on)
                rows.append((row, len(evidence)))
            pages.append(page)
            evidence.append(doc)
            if len(pages) > 100:
                raise ValueError("owner_catalog_page_limit")
        if not pages or totals != {len(rows)}:
            raise ValueError("incomplete_owner_catalog_region")
        if len({row.kra_owner_id for row, _ in rows}) != len(rows):
            raise ValueError("duplicate_owner_in_region")
        observations.extend(rows)
    return observations, evidence


def business_key(row):
    return (
        row.meet_code,
        row.kra_owner_id,
        row.official_name_ko,
        row.registration_date,
        row.total_registered_horses,
        row.current_owned_horses,
    )


def latest_complete_run(session):
    return session.scalar(
        select(IngestionRun.id)
        .where(IngestionRun.data_type == DATA_TYPE, IngestionRun.status == "completed")
        .order_by(IngestionRun.started_at_ms.desc(), IngestionRun.id.desc())
        .limit(1)
    )


def persist_catalog(session, observations, evidence, *, started_at_ms):
    """One transaction: either every region is visible or none. Never modify owners."""
    if {row.meet_code for row, _ in observations} != set(REGIONS):
        raise ValueError("all_owner_regions_required")
    if len({(row.meet_code, row.kra_owner_id) for row, _ in observations}) != len(observations):
        raise ValueError("duplicate_owner_snapshot_key")
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET LOCAL lock_timeout='5s'"))
        session.execute(text("SET LOCAL statement_timeout='30s'"))
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
    owners = dict(session.execute(select(Owner.kra_owner_id, Owner.id)).all())
    previous_id = latest_complete_run(session)
    previous = (
        list(
            session.scalars(
                select(OwnerCatalogSnapshot).where(
                    OwnerCatalogSnapshot.ingestion_run_id == previous_id
                )
            )
        )
        if previous_id
        else []
    )
    if previous and {business_key(r) for r in previous} == {
        business_key(r) for r, _ in observations
    }:
        if all(r.owner_id == owners.get(r.kra_owner_id) for r in previous):
            return summarize(previous_id, "unchanged", previous)
    run = IngestionRun(
        source="data.go.kr/B551015/API309",
        data_type=DATA_TYPE,
        started_at_ms=started_at_ms,
        status="running",
    )
    session.add(run)
    session.flush()
    docs = []
    for values in evidence:
        doc = SourceDocument(ingestion_run_id=run.id, **values)
        session.add(doc)
        docs.append(doc)
    session.flush()
    snapshots = []
    for item, source_no in observations:
        row = OwnerCatalogSnapshot(
            ingestion_run_id=run.id,
            **asdict(item),
            owner_id=owners.get(item.kra_owner_id),
            observed_at_ms=max(d["retrieved_at_ms"] for d in evidence),
            source_document_id=docs[source_no].id,
        )
        snapshots.append(row)
    session.add_all(snapshots)
    session.flush()
    saved = list(
        session.scalars(
            select(OwnerCatalogSnapshot).where(OwnerCatalogSnapshot.ingestion_run_id == run.id)
        )
    )
    if {business_key(r) for r in saved} != {business_key(r) for r, _ in observations}:
        raise ValueError("owner_catalog_readback_mismatch")
    run.status = "completed"
    run.records_fetched = run.records_written = len(saved)
    run.completed_at_ms = time.time_ns() // 1_000_000
    return summarize(run.id, "completed", saved)


def summarize(run_id, status, rows):
    return dict(
        run_id=run_id,
        status=status,
        rows=len(rows),
        unique_official_ids=len({r.kra_owner_id for r in rows}),
        linked=sum(r.owner_id is not None for r in rows),
        unlinked=sum(r.owner_id is None for r in rows),
        regions={str(m): sum(r.meet_code == m for r in rows) for m in REGIONS},
    )

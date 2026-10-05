"""Scoped, reproducible repair. Research DB is read-only; no model changes.

Prepare -> backup both targets -> migrate -> apply -> verify -> replay.
Only horses already having Jeju starting-training history are in scope.
The entire old starting-training table is backed up, not the multi-GB database.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from sqlalchemy import create_engine, delete, insert, select, text
from sqlalchemy.orm import Session

from horse_racing.config import get_settings
from horse_racing.db.models import Horse, HorseStartTraining, IngestionRun, SourceDocument
from horse_racing.jobs.weekly_entry_cards import require_target

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "jeju/data/jeju_native_core.sqlite3"
COLLECTION = ROOT / "jeju/research/20261001_starting_training_website_load/collection"
FIELDS = (
    "horse_id_raw",
    "training_date",
    "stable_part",
    "stable_number",
    "rider_name",
    "remark",
    "location_raw",
    "occurrence_no",
)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, default=str)


def target_engine(target):
    if target == "local":
        return create_engine(
            "sqlite:///" + str(ROOT / "data/horse_racing.sqlite3"), hide_parameters=True
        )
    settings = get_settings()
    require_target(settings.database_url, "xkykmhhkjtosptoibduo")
    return create_engine(settings.database_url, hide_parameters=True)


def backup(output, target):
    engine = target_engine(target)
    destination = output / f"{target}_before.jsonl.gz"
    counts = Counter()
    state_digest = hashlib.sha256()
    with engine.connect() as conn, gzip.open(destination, "xt", encoding="utf-8") as f:
        if target == "supabase":
            conn.execute(text("SET TRANSACTION READ ONLY"))
        for row in (
            conn.execution_options(stream_results=True)
            .execute(text("SELECT * FROM horse_start_training ORDER BY id"))
            .mappings()
        ):
            serialized = json.dumps(dict(row), ensure_ascii=False, default=str, sort_keys=True)
            f.write(serialized + "\n")
            state_digest.update((serialized + "\n").encode())
            counts[row["meet_code"]] += 1
        scope = (
            conn.execute(
                text(
                    "SELECT DISTINCT h.kra_horse_id FROM horse_start_training t "
                    "JOIN horses h ON h.id=t.horse_id WHERE t.meet_code=2"
                )
            )
            .scalars()
            .all()
        )
        conn.rollback()
    meta = {
        "target": target,
        "rows_by_meet": dict(counts),
        "jeju_scope": sorted(scope),
        "backup_sha256": sha(destination),
        "state_digest": state_digest.hexdigest(),
    }
    write_json(output / f"{target}_before.json", meta)
    engine.dispose()
    print(
        json.dumps({k: v for k, v in meta.items() if k != "jeju_scope"}, ensure_ascii=False),
        flush=True,
    )


def website_parser():
    # Reuse the reviewed collector's pure parser without invoking its collector/writer.
    path = COLLECTION.parent / "jeju_collect_starting_website.py"
    spec = importlib.util.spec_from_file_location("reviewed_jeju_website_parser", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.parse


def prepare(output):
    local_meta = json.loads((output / "local_before.json").read_text())
    pg_meta = json.loads((output / "supabase_before.json").read_text())
    if local_meta["jeju_scope"] != pg_meta["jeju_scope"]:
        raise ValueError("Local/Supabase historical repair scopes differ")
    scope = set(local_meta["jeju_scope"])
    parse = website_parser()
    source_before = sha(RESEARCH)
    research = sqlite3.connect(f"file:{RESEARCH}?mode=ro", uri=True)
    research.row_factory = sqlite3.Row
    research.execute("PRAGMA query_only=ON")
    research.execute("BEGIN")
    artifact_rows = research.execute("""SELECT * FROM (SELECT a.*, row_number() OVER
        (PARTITION BY training_date ORDER BY requested_at_utc DESC,website_artifact_id DESC) rn
        FROM website_training_artifacts a WHERE status='complete')
        WHERE rn=1 ORDER BY training_date""").fetchall()
    raw_web = research.execute("""SELECT w.*,a.training_date FROM starting_training_website_rows w
        JOIN website_training_artifacts a USING(website_artifact_id)
        ORDER BY website_artifact_id,source_row_no""").fetchall()
    by_artifact = defaultdict(list)
    for row in raw_web:
        by_artifact[row["website_artifact_id"]].append(dict(row))
    artifacts, records = [], []
    groups_all, groups_scope = Counter(), Counter()
    for a in artifact_rows:
        # The research DB stores a jeju/-relative HTML path, not a collection-relative one.
        raw_path = (ROOT / "jeju" / a["html_relative_path"]).resolve(strict=True)
        if not raw_path.is_relative_to(COLLECTION.resolve()):
            raise ValueError("Research artifact escapes the reviewed collection directory")
        if sha(raw_path) != a["html_sha256"]:
            raise ValueError("Research HTML hash mismatch")
        parsed = parse(raw_path.read_bytes(), a["training_date"].replace("-", ""))
        stored = by_artifact[a["website_artifact_id"]]
        if len(parsed) != len(stored) or len(stored) != a["row_count"]:
            raise ValueError("Research website row counts mismatch")
        for p, w in zip(parsed, stored, strict=True):
            observed = [
                p[x]
                for x in [
                    "horse_id_raw",
                    "source_row_no",
                    "affiliation",
                    "trainer_no",
                    "horse_name",
                    "rider",
                    "location",
                    "note",
                ]
            ]
            expected = [
                w[x]
                for x in [
                    "horse_id_raw",
                    "source_row_no",
                    "affiliation_raw",
                    "trainer_no_raw",
                    "horse_name_raw",
                    "rider_raw",
                    "location_raw",
                    "note_raw",
                ]
            ]
            if observed != expected:
                raise ValueError("Research database differs from archived HTML")
            groups_all[(a["training_date"], p["horse_id_raw"])] += 1
            if p["horse_id_raw"] in scope:
                groups_scope[(a["training_date"], p["horse_id_raw"])] += 1
        artifacts.append(
            {
                "training_date": a["training_date"],
                "source_url": a["source_url"],
                "sha256": a["html_sha256"],
                "local_path": str(raw_path),
                "requested_at": a["requested_at_utc"],
                "rows": parsed,
            }
        )
    # Refresh only already-present operational dates outside the research archive.
    eng = target_engine("local")
    with eng.connect() as conn:
        extra_dates = (
            conn.execute(
                text(
                    "SELECT DISTINCT training_date_local FROM horse_start_training "
                    "WHERE meet_code=2 AND training_date_local>:last ORDER BY training_date_local"
                ),
                {"last": artifacts[-1]["training_date"]},
            )
            .scalars()
            .all()
        )
    eng.dispose()
    raw_dir = output / "raw"
    raw_dir.mkdir(exist_ok=False)
    for day in extra_dates:
        day = str(day)
        params = {
            "Act": "07",
            "Sub": "2",
            "meet": "2",
            "trDate": day.replace("-", "/"),
            "trDateReplace": day.replace("-", ""),
            "trNo": "",
            "trName": "",
        }
        response = httpx.get(
            "https://race.kra.co.kr/startingData/getStartingTrainListAll.do",
            params=params,
            follow_redirects=False,
            timeout=30,
        )
        response.raise_for_status()
        parsed = parse(response.content, day.replace("-", ""))
        if not parsed:
            raise ValueError("Fresh website snapshot is empty; existing data will not be replaced")
        path = raw_dir / (day + ".html")
        path.write_bytes(response.content)
        artifacts.append(
            {
                "training_date": day,
                "source_url": str(response.url),
                "sha256": sha(path),
                "local_path": str(path),
                "requested_at": datetime.now(UTC).isoformat(),
                "rows": parsed,
            }
        )
    years = Counter()
    for (day, _), n in groups_scope.items():
        years[day[:4]] += max(0, n - 1)
    for artifact in artifacts:
        ordinals = Counter()
        selected = []
        for raw in artifact.pop("rows"):
            hid = raw["horse_id_raw"]
            if hid not in scope:
                continue
            match = re.fullmatch(r"(\d+)조", raw["affiliation"])
            if not match:
                raise ValueError("Unexpected website affiliation; preserve rather than guess")
            ordinals[hid] += 1
            row = dict(
                horse_id_raw=hid,
                training_date=artifact["training_date"],
                stable_part=int(match[1]),
                stable_number=raw["trainer_no"],
                rider_name=raw["rider"],
                remark=raw["note"],
                location_raw=raw["location"],
                occurrence_no=ordinals[hid],
                source_row_no=raw["source_row_no"],
            )
            selected.append(row)
        artifact["records"] = selected
        records.extend(selected)
    research.rollback()
    research.close()
    if sha(RESEARCH) != source_before:
        raise ValueError(
            "Research DB changed while preparing; retry with a stable read-only snapshot"
        )
    bundle = {"scope": sorted(scope), "research_db_sha256": source_before, "artifacts": artifacts}
    write_json(output / "bundle.json", bundle)
    summary = {
        "research_artifact_dates": len(artifact_rows),
        "research_whole_website_rows": len(raw_web),
        "research_scoped_horse_day_extra_rows": sum(years.values()),
        "scoped_extra_rows_by_year": dict(sorted(years.items())),
        "scope_horses": len(scope),
        "prepared_rows": len(records),
        "fresh_dates": list(map(str, extra_dates)),
        "bundle_sha256": sha(output / "bundle.json"),
        "research_db_unchanged": True,
    }
    write_json(output / "prepare.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def load_bundle(output):
    summary = json.loads((output / "prepare.json").read_text())
    if sha(output / "bundle.json") != summary["bundle_sha256"]:
        raise ValueError("Prepared bundle hash mismatch")
    bundle = json.loads((output / "bundle.json").read_text())
    for artifact in bundle["artifacts"]:
        if sha(Path(artifact["local_path"])) != artifact["sha256"]:
            raise ValueError("Source HTML changed")
    return bundle


def apply(output, target, replay=False):
    bundle = load_bundle(output)
    scope = set(bundle["scope"])
    engine = target_engine(target)
    observed = time.time_ns() // 1_000_000
    report_path = output / (target + ("_replay.json" if replay else "_apply.json"))
    if report_path.exists():
        raise ValueError("Application report exists; do not overwrite an audit record")
    with Session(engine) as session:
        if target == "supabase":
            session.execute(text("SET LOCAL lock_timeout='10s'"))
            session.execute(text("SET LOCAL statement_timeout='120s'"))
            session.execute(text("LOCK TABLE horse_start_training IN SHARE ROW EXCLUSIVE MODE"))
        horses = dict(session.execute(select(Horse.kra_horse_id, Horse.id)).all())
        if not set(bundle["scope"]).issubset(horses):
            raise ValueError("Official horse IDs missing in target; no name matching is allowed")
        before = dict(
            session.execute(
                text("SELECT meet_code,count(*) FROM horse_start_training GROUP BY meet_code")
            ).all()
        )
        # Idempotency compares all prepared source fields plus artifact SHA, not just totals.
        expected = {
            (r["horse_id_raw"], r["training_date"], r["occurrence_no"]): (
                r["stable_part"],
                r["stable_number"],
                r["rider_name"],
                r["remark"],
                r["location_raw"],
                r["source_row_no"],
                a["sha256"],
            )
            for a in bundle["artifacts"]
            for r in a["records"]
        }
        current = {}
        for row in session.execute(
            select(Horse.kra_horse_id, HorseStartTraining, SourceDocument.sha256)
            .join(Horse, Horse.id == HorseStartTraining.horse_id)
            .outerjoin(SourceDocument, SourceDocument.id == HorseStartTraining.source_document_id)
            .where(HorseStartTraining.meet_code == 2)
        ):
            hid, r, digest = row
            if hid in scope:
                current[(hid, str(r.training_date_local), r.occurrence_no)] = (
                    r.stable_part,
                    str(r.stable_number) if r.stable_number is not None else None,
                    r.rider_name,
                    r.remark,
                    r.location_raw,
                    r.source_row_no,
                    digest,
                )
        dates = {a["training_date"] for a in bundle["artifacts"]}
        current = {k: v for k, v in current.items() if k[1] in dates}
        if current == expected:
            result = {
                "target": target,
                "skipped_unchanged": True,
                "rows": len(expected),
                "before": before,
                "after": before,
            }
            session.rollback()
        else:
            if replay:
                raise ValueError("Replay would change data; idempotency verification failed")
            scope_ids = {horses[x] for x in bundle["scope"]}
            # Exact pre-change export exists for BOTH targets. No other meet/table is replaced.
            backup_meta = json.loads((output / f"{target}_before.json").read_text())
            if sha(output / f"{target}_before.jsonl.gz") != backup_meta["backup_sha256"]:
                raise ValueError("Scoped rollback backup hash mismatch")
            with gzip.open(output / f"{target}_before.jsonl.gz", "rt", encoding="utf-8") as old:
                old_columns = list(json.loads(next(old)))
            # Columns came from a local backup, never from user input. Strict identifier allowlist.
            if not all(re.fullmatch(r"[a-z_]+", x) for x in old_columns):
                raise ValueError("Invalid backup schema")
            digest = hashlib.sha256()
            for row in session.execute(
                text("SELECT " + ",".join(old_columns) + " FROM horse_start_training ORDER BY id")
            ).mappings():
                digest.update(
                    (
                        json.dumps(dict(row), ensure_ascii=False, default=str, sort_keys=True)
                        + "\n"
                    ).encode()
                )
            if digest.hexdigest() != backup_meta["state_digest"]:
                raise ValueError("Target changed since its scoped backup; no replacement performed")
            run = IngestionRun(
                source="KRA verified Jeju starting-training website",
                data_type="horse_start_training_website_repair",
                started_at_ms=observed,
                status="running",
            )
            session.add(run)
            session.flush()
            doc_ids = {}
            documents = []
            for a in bundle["artifacts"]:
                stamp = int(
                    datetime.fromisoformat(a["requested_at"].replace("Z", "+00:00")).timestamp()
                    * 1000
                )
                doc = SourceDocument(
                    ingestion_run_id=run.id,
                    source_url=a["source_url"],
                    endpoint="/startingData/getStartingTrainListAll.do",
                    operation="verified_jeju_website_snapshot",
                    request_params_json=json.dumps(
                        {
                            "meet": 2,
                            "tr_date": a["training_date"],
                            "scope": "existing_jeju_start_training_horses",
                        }
                    ),
                    requested_at_ms=stamp,
                    retrieved_at_ms=stamp,
                    http_status_code=200,
                    content_type="text/html; charset=euc-kr",
                    response_bytes=Path(a["local_path"]).stat().st_size,
                    local_path=a["local_path"],
                    sha256=a["sha256"],
                )
                documents.append((a["training_date"], doc))
            session.add_all([d for _, d in documents])
            session.flush()
            doc_ids = {day: doc.id for day, doc in documents}
            # Atomic scoped replacement; no import of horses outside the existing cohort.
            for batch_start in range(0, len(scope_ids), 500):
                ids = sorted(scope_ids)[batch_start : batch_start + 500]
                session.execute(
                    delete(HorseStartTraining)
                    .where(
                        HorseStartTraining.meet_code == 2,
                        HorseStartTraining.horse_id.in_(ids),
                        HorseStartTraining.training_date_local.in_(
                            [date.fromisoformat(d) for d in dates]
                        ),
                    )
                    .execution_options(synchronize_session=False)
                )
            rows = []
            for a in bundle["artifacts"]:
                for r in a["records"]:
                    rows.append(
                        {
                            "horse_id": horses[r["horse_id_raw"]],
                            "meet_code": 2,
                            "training_date_local": date.fromisoformat(r["training_date"]),
                            "stable_part": r["stable_part"],
                            "stable_number": r["stable_number"],
                            "rider_name": r["rider_name"],
                            "remark": r["remark"],
                            "location_raw": r["location_raw"],
                            "occurrence_no": r["occurrence_no"],
                            "source_kind": "kra_website",
                            "source_document_id": doc_ids[a["training_date"]],
                            "source_row_no": r["source_row_no"],
                            "observed_at_ms": observed,
                        }
                    )
            for i in range(0, len(rows), 2000):
                session.execute(insert(HorseStartTraining), rows[i : i + 2000])
                if i % 20000 == 0:
                    print(
                        json.dumps(
                            {
                                "target": target,
                                "staged_rows": min(i + 2000, len(rows)),
                                "total": len(rows),
                            }
                        ),
                        flush=True,
                    )
            run.records_fetched = len(rows)
            run.records_written = len(rows)
            run.status = "completed"
            run.completed_at_ms = time.time_ns() // 1_000_000
            after = dict(
                session.execute(
                    text("SELECT meet_code,count(*) FROM horse_start_training GROUP BY meet_code")
                ).all()
            )
            if any(before.get(m, 0) != after.get(m, 0) for m in before if m != 2):
                raise ValueError("Another meet changed; rollback")
            session.commit()
            result = {
                "target": target,
                "skipped_unchanged": False,
                "rows": len(rows),
                "before": before,
                "after": after,
                "run_id": run.id,
                "backup": str(output / f"{target}_before.jsonl.gz"),
            }
    engine.dispose()
    write_json(report_path, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def verify(output, target):
    bundle = load_bundle(output)
    expected = {
        (r["horse_id_raw"], r["training_date"], r["occurrence_no"]): (
            r["stable_part"],
            r["stable_number"],
            r["rider_name"],
            r["remark"],
            r["location_raw"],
            r["source_row_no"],
            a["sha256"],
        )
        for a in bundle["artifacts"]
        for r in a["records"]
    }
    engine = target_engine(target)
    current = {}
    scope = set(bundle["scope"])
    dates = {a["training_date"] for a in bundle["artifacts"]}
    with Session(engine) as sess:
        if target == "supabase":
            sess.execute(text("SET TRANSACTION READ ONLY"))
        for hid, r, digest in sess.execute(
            select(Horse.kra_horse_id, HorseStartTraining, SourceDocument.sha256)
            .join(Horse, Horse.id == HorseStartTraining.horse_id)
            .outerjoin(SourceDocument, SourceDocument.id == HorseStartTraining.source_document_id)
            .where(HorseStartTraining.meet_code == 2)
        ):
            key = (hid, str(r.training_date_local), r.occurrence_no)
            if hid in scope and str(r.training_date_local) in dates:
                current[key] = (
                    r.stable_part,
                    str(r.stable_number) if r.stable_number is not None else None,
                    r.rider_name,
                    r.remark,
                    r.location_raw,
                    r.source_row_no,
                    digest,
                )
        result = {
            "target": target,
            "expected": len(expected),
            "actual": len(current),
            "missing": len(expected.keys() - current.keys()),
            "extra": len(current.keys() - expected.keys()),
            "different": sum(current[k] != v for k, v in expected.items() if k in current),
            "research_db_unchanged": sha(RESEARCH) == bundle["research_db_sha256"],
        }
        sess.rollback()
    engine.dispose()
    if (
        result["missing"]
        or result["extra"]
        or result["different"]
        or not result["research_db_unchanged"]
    ):
        raise ValueError(result)
    write_json(output / f"{target}_verify.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["backup", "prepare", "apply", "replay", "verify"])
    parser.add_argument("--target", choices=["local", "supabase"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "research"):
        raise ValueError("Audit output must be inside project research/")
    out.mkdir(parents=True, exist_ok=True)
    if args.mode == "prepare":
        prepare(out)
    elif not args.target:
        parser.error("--target is required")
    elif args.mode == "backup":
        backup(out, args.target)
    elif args.mode == "verify":
        verify(out, args.target)
    else:
        apply(out, args.target, replay=args.mode == "replay")


if __name__ == "__main__":
    main()

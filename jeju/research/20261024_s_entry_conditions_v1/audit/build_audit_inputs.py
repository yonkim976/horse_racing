#!/usr/bin/env python3
"""Build the frozen S43 entry-condition audit input from pinned local sources.

This script reads only known repository files, hashes the read-only native
SQLite source, opens SQLite with mode=ro/query_only, and writes only into this
study's audit directory. It never reads target finish labels for feature
construction, trains, predicts, evaluates, or copies source/database files.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
AUDIT = ROOT / "jeju/research/20261024_s_entry_conditions_v1/audit"
S_FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
H3_ROOT = ROOT / "data/research/jeju_native_h3_features_v1_20260916"
H3_ENTRIES = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2/entries.parquet"
DB_ROOT = ROOT / "data/research/jeju_native_text_phase2_db_20260915"
DB_PATH = DB_ROOT / "jeju_native_text_phase2.sqlite3"
DB_MANIFEST = DB_ROOT / "manifest.json"
CONTRACT = ROOT / "jeju/research/20261024_s_entry_conditions_v1/supervisor/DESIGN_CONTRACT.md"
TARGET_ROWS = 52_155
TARGET_RACES = 5_206
FEATURE_COLUMNS = [
    "current_declared_burden_kg",
    "burden_change_vs_last_valid_kg",
    "horse_number_fraction",
]
PREVIOUS_WEIGHT_RULE = (
    "same_official_horse_id; actual past race row; "
    "event_race_date <= target_race_date_minus_2_calendar_days_inclusive; "
    "latest eligible valid burden"
)
NUMBER_FORMULA = "(declared_horse_number - 1) / (max_declared_horse_number - 1)"
NUMBER_DENOMINATOR_RULE = (
    "max_declared_horse_number is the confirmed maximum declared horse number from the original "
    "full declaration roster matching the exact S40 target roster; never the maximum of only "
    "observed H3 feature rows"
)
EXPECTED_DB_SHA256 = "0f2871c2a8f931bb968d8bf7086c27f0644c0ef7332b41b7a1bd85ff637c638f"
SPECIAL_ELIGIBILITY_RULE = (
    "normal finish_position 1..89 with positive finish time; special 91/92 only "
    "when raw ord matches and both raw rcTime and normalized finish_time_ms are positive; "
    "other special rows are ambiguous and excluded from prior actual burden"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_ref(path: Path, *, expected_sha: str | None = None, actual_hash: bool = True) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"expected regular source file: {resolved}")
    actual = sha256_file(resolved) if actual_hash else expected_sha
    if expected_sha is not None and actual_hash and actual != expected_sha:
        raise ValueError(f"source SHA mismatch: {resolved}")
    return {
        "path": resolved.relative_to(ROOT).as_posix(),
        "bytes": resolved.stat().st_size,
        "sha256": actual,
        "sha256_method": "streamed_actual_file" if actual_hash else "pinned_existing_manifest",
    }


def canonical_json_line(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _as_int(value: Any, label: str) -> int:
    n = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(n) or not math.isfinite(float(n)) or float(n) != round(float(n)):
        raise ValueError(f"{label} is not an exact integer: {value!r}")
    return int(n)


def _id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text.zfill(7) if text.isdigit() else text


def _date(value: Any) -> str:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
    stamp = pd.to_datetime(value, errors="raise")
    return stamp.strftime("%Y-%m-%d")


def _race_number(race_id: str) -> int:
    return _as_int(str(race_id).rsplit("_", 1)[-1], "race_id trailing event number")


def _safe_output(path: Path) -> None:
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(AUDIT.resolve(strict=True)):
        raise ValueError(f"output escapes audit folder: {path}")
    if resolved.exists() or resolved.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing audit output: {resolved}")


def _write_once(path: Path, payload: bytes) -> None:
    _safe_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _read_s_target() -> pd.DataFrame:
    # Select only identity/context columns; finish_position and all outcomes are not read.
    frame = pd.read_parquet(
        S_FEATURES,
        columns=["api_record_id", "race_id", "race_date", "horse_id", "horse_name",
                 "horse_number", "field_n", "distance_m"],
    )
    if len(frame) != TARGET_ROWS or frame.api_record_id.isna().any() or frame.api_record_id.duplicated().any():
        raise ValueError("frozen S40 target API keys/row count changed")
    frame["api_record_id"] = pd.to_numeric(frame.api_record_id, errors="raise").astype("int64")
    frame["race_date"] = frame.race_date.map(_date)
    frame["horse_id"] = frame.horse_id.map(_id)
    frame["horse_number"] = frame.horse_number.map(lambda x: _as_int(x, "S horse_number"))
    frame["field_n"] = frame.field_n.map(lambda x: _as_int(x, "S field_n"))
    frame["distance_m"] = frame.distance_m.map(lambda x: _as_int(x, "S distance_m"))
    frame["race_id"] = frame.race_id.astype(str)
    frame["event_number"] = frame.race_id.map(_race_number)
    if any(frame[c].eq("").any() for c in ("race_id", "horse_id", "horse_name")):
        raise ValueError("S target has null/blank identity fields")
    if frame.race_id.nunique() != TARGET_RACES:
        raise ValueError("frozen S40 target race count changed")
    if not (frame.groupby("race_id", sort=False).size() == frame.groupby("race_id", sort=False).field_n.first()).all():
        raise ValueError("S target roster row count differs from field_n")
    if frame.duplicated(["race_id", "horse_id"]).any() or frame.duplicated(["race_id", "horse_number"]).any():
        raise ValueError("S target race/horse or race/number natural key is duplicated")
    return frame


def _read_h3_sources(target: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[int, dict[str, Any]]]:
    entries = pd.read_parquet(H3_ENTRIES, columns=["entry_id", "race_id", "event_date", "event_number",
                                                  "horse_id", "horse_number", "distance_m", "field_size"])
    features = pd.read_parquet(H3_ROOT / "features.parquet",
                               columns=["entry_id", "card_observed", "declared_horse_number", "declared_burden_kg"])
    lineage = pd.read_parquet(H3_ROOT / "lineage.parquet",
                              columns=["entry_id", "source_document_id", "source_file_date",
                                       "source_line_number", "source_line_sha256", "card_observed"])
    docs = json.loads((H3_ROOT / "source_documents.json").read_text(encoding="utf-8"))
    doc_map = {int(row["id"]): row for row in docs}
    for frame in (entries, features, lineage):
        if frame.entry_id.isna().any() or frame.entry_id.duplicated().any():
            raise ValueError("H3 entry_id is not unique/complete")
    entries["event_date_key"] = entries.event_date.map(lambda v: _date(v))
    entries["event_number_key"] = entries.event_number.map(lambda x: _as_int(x, "H3 event_number"))
    entries["horse_id_key"] = entries.horse_id.map(_id)
    entries["horse_number_key"] = entries.horse_number.map(lambda x: _as_int(x, "H3 horse_number"))
    entries["distance_m_key"] = entries.distance_m.map(lambda x: _as_int(x, "H3 distance_m"))
    natural_cols = ["event_date_key", "event_number_key", "horse_id_key", "horse_number_key"]
    if entries.duplicated(natural_cols).any():
        raise ValueError("H3 official natural horse key is duplicated")
    target_h3 = target.merge(
        entries,
        left_on=["race_date", "event_number", "horse_id", "horse_number"],
        right_on=["event_date_key", "event_number_key", "horse_id_key", "horse_number_key"],
        how="left", validate="one_to_one", suffixes=("", "_h3"), indicator=True,
    )
    if len(target_h3) != len(target):
        raise ValueError("H3 natural-key left join changed target rows")
    target_h3 = target_h3.merge(features, on="entry_id", how="left", validate="many_to_one")
    target_h3 = target_h3.merge(lineage, on="entry_id", how="left", validate="many_to_one", suffixes=("_feature", "_lineage"))
    return target_h3, entries, lineage, doc_map


def _db_open() -> sqlite3.Connection:
    resolved = DB_PATH.resolve(strict=True)
    uri = f"file:{resolved.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise RuntimeError("SQLite query_only read-only safeguard did not activate")
    return connection


def _official_event_rows(connection: sqlite3.Connection, target: pd.DataFrame) -> tuple[dict[tuple[str, int, int], dict[str, Any]], list[dict[str, Any]]]:
    keys = sorted({(r.race_date, int(r.event_number)) for r in target.itertuples(index=False)})
    dates = sorted({d for d, _ in keys})
    official: dict[tuple[str, int, int], dict[str, Any]] = {}
    sql = """SELECT v.event_date,v.event_number,v.distance_m,v.population_status,
                     e.id AS entry_id,e.horse_number,e.horse_name,e.hr_no,e.identity_status,
                     e.finish_position,e.finish_time_ms,e.record_status
              FROM event v JOIN entry e ON e.event_id=v.id
              WHERE v.event_type='race' AND v.meet=2 AND v.event_date IN ({})"""
    for offset in range(0, len(dates), 200):
        batch = dates[offset:offset + 200]
        query = sql.format(",".join("?" for _ in batch))
        params = [value.replace("-", "") for value in batch]
        for row in connection.execute(query, params):
            raw_date = str(row["event_date"])
            event_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else raw_date
            key = (event_date, int(row["event_number"]), int(row["horse_number"]))
            if key in official:
                raise ValueError(f"duplicate official date/event/horse-number row: {key}")
            official[key] = dict(row)
    return official, {"date_count": len(dates), "query_batches": math.ceil(len(dates) / 200),
                      "sql": sql.replace("{}", "<parameterized IN list>")}


def _parse_dacom_docs(target_h3: pd.DataFrame, doc_map: dict[int, dict[str, Any]], official: dict[tuple[str,int,int], dict[str,Any]]) -> tuple[dict[tuple[int,str,int], list[dict[str,Any]]], dict[int, dict[str,Any]], list[dict[str,Any]]]:
    sys.path.insert(0, str(ROOT / "src"))
    from horse_racing.analysis.jeju_h3_features import parse_card

    target_race_keys = {(str(r.race_date), int(r.event_number)) for r in target_h3.itertuples(index=False)}
    candidate_doc_ids = set()
    for row in target_h3.itertuples(index=False):
        if pd.notna(getattr(row, "source_document_id", None)):
            candidate_doc_ids.add(int(getattr(row, "source_document_id")))
        if pd.notna(getattr(row, "source_document_id_lineage", None)):
            candidate_doc_ids.add(int(getattr(row, "source_document_id_lineage")))
    # A full card may be referenced by other entries in the same official race;
    # include every H3 lineage document for target event natural keys.
    h3_entries = pd.read_parquet(H3_ENTRIES, columns=["entry_id", "event_date", "event_number", "horse_number"])
    target_events = set(target_race_keys)
    h3_entries["event_date_key"] = h3_entries.event_date.map(lambda v: _date(v))
    race_event_ids = set(h3_entries.loc[
        h3_entries.apply(lambda x: (x.event_date_key, int(x.event_number)) in target_events, axis=1), "entry_id"
    ].astype(int))
    h3_lineage_all = pd.read_parquet(H3_ROOT / "lineage.parquet", columns=["entry_id", "source_document_id"])
    relevant_lineage = h3_lineage_all[h3_lineage_all.entry_id.isin(race_event_ids)].source_document_id.dropna()
    candidate_doc_ids.update(int(x) for x in relevant_lineage)
    parsed: dict[tuple[int,str,int], list[dict[str,Any]]] = defaultdict(list)
    doc_rows: dict[int, dict[str,Any]] = {}
    refs=[]
    for document_id in sorted(candidate_doc_ids):
        meta = doc_map.get(document_id)
        if not meta or not meta.get("file_date"):
            continue
        path = (ROOT / str(meta["path"])).resolve(strict=True)
        ref = file_ref(path, expected_sha=str(meta["sha256"]))
        refs.append(ref)
        content = path.read_bytes()
        lines = content.decode("cp949", errors="replace").splitlines()
        for row in parse_card(lines):
            if row["breed"] != "제":
                continue
            race_key = (row["event_date"].isoformat(), int(row["event_number"]))
            if race_key not in target_race_keys:
                continue
            race_date = date.fromisoformat(race_key[0])
            if date.fromisoformat(str(meta["file_date"])) > race_date - timedelta(days=2):
                continue
            row.update(
                document_id=document_id,
                document_file_date=str(meta["file_date"]),
                document_retrieved_at_ms=meta.get("retrieved_at_ms"),
                document_path=str(meta["path"]),
                document_sha256=str(meta["sha256"]),
                source_line_sha256=hashlib.sha256(lines[int(row["line_number"]) - 1].encode("utf-8")).hexdigest(),
            )
            parsed[(document_id, race_key[0], int(row["event_number"]))].append(row)
        doc_rows[document_id] = meta
    return parsed, doc_rows, refs


def _roster_proofs(target: pd.DataFrame, official: dict[tuple[str,int,int],dict[str,Any]],
                   target_h3: pd.DataFrame, parsed: dict[tuple[int,str,int],list[dict[str,Any]]],
                   doc_map: dict[int,dict[str,Any]]) -> tuple[dict[str,dict[str,Any]], dict[tuple[int,str,int],dict[str,Any]]]:
    by_race = {key: group.sort_values("horse_number") for key, group in target.groupby("race_id", sort=False)}
    h3_candidates: dict[str,set[int]] = defaultdict(set)
    for row in target_h3.itertuples(index=False):
        if pd.notna(row.entry_id):
            if pd.notna(getattr(row, "source_document_id_lineage", None)):
                h3_candidates[str(row.race_id)].add(int(row.source_document_id_lineage))
            elif pd.notna(getattr(row, "source_document_id", None)):
                h3_candidates[str(row.race_id)].add(int(row.source_document_id))
    proof: dict[str,dict[str,Any]]={}
    raw_choice: dict[tuple[int,str,int],dict[str,Any]]={}
    for race_id, group in by_race.items():
        first=group.iloc[0]
        rdate=str(first.race_date); eno=int(first.event_number); dist=int(first.distance_m)
        expected={int(r.horse_number):r for r in group.itertuples(index=False)}
        official_rows={}
        official_ok=True
        for number, target_row in expected.items():
            row=official.get((rdate,eno,number))
            if not row or row.get("population_status")!="confirmed_native_normal_race" or row.get("identity_status")!="official_race_ids_linked":
                official_ok=False; break
            if _id(row.get("hr_no")) != str(target_row.horse_id) or int(row.get("distance_m") or -1) != dist:
                official_ok=False; break
            if not row.get("horse_name") or str(row["horse_name"]).strip()!=str(target_row.horse_name).strip():
                official_ok=False; break
            official_rows[number]=row
        if not official_ok:
            proof[race_id]={"confirmed":False,"reason":"official_roster_id_name_or_distance_mismatch",
                            "max_declared_horse_number":None,"document_id":None,"source_file_date":None,
                            "source_document_sha256":None,"source_status":"unconfirmed"}
            continue
        candidates=h3_candidates.get(race_id,set())
        valid_docs=[]
        for docid in candidates:
            rows=parsed.get((docid,rdate,eno),[])
            if not rows or len(rows)!=len(expected):
                continue
            nums=[int(row["horse_number"]) for row in rows]
            if len(set(nums))!=len(nums) or set(nums)!=set(expected):
                continue
            okay=True
            mapped={int(row["horse_number"]):row for row in rows}
            for number,row in mapped.items():
                target_row=expected[number]
                official_row=official_rows[number]
                if int(row.get("distance") or -1)!=dist:
                    okay=False; break
                rawname=str(row.get("horse_name") or "")
                official_name=str(official_row["horse_name"])
                if rawname==official_name:
                    pass
                elif rawname=="★"+official_name:
                    # The sole allowed marker variant; its semantics are intentionally not inferred.
                    pass
                else:
                    okay=False; break
                if _id(official_row.get("hr_no"))!=str(target_row.horse_id):
                    okay=False; break
            if okay:
                valid_docs.append((str(doc_map[docid]["file_date"]),docid,mapped))
        if not valid_docs:
            proof[race_id]={"confirmed":False,"reason":"no_exact_full_card_source_roster",
                            "max_declared_horse_number":None,"document_id":None,"source_file_date":None,
                            "source_document_sha256":None,"source_status":"unconfirmed"}
            continue
        # Use earliest valid card by declared file date, then stable document ID.
        file_date,docid,mapped=min(valid_docs,key=lambda x:(x[0],x[1]))
        maxnum=max(mapped)
        proof[race_id]={"confirmed":True,"reason":"exact_full_card_official_roster_match",
                        "max_declared_horse_number":maxnum,"document_id":docid,
                        "source_file_date":file_date,"source_document_sha256":doc_map[docid]["sha256"],
                        "source_status":"full_card_roster_exact"}
        for number,row in mapped.items():
            raw_choice[(docid,rdate,eno,number)] = row
    return proof, raw_choice


def _actual_history(connection: sqlite3.Connection, target: pd.DataFrame) -> tuple[dict[str,list[dict[str,Any]]],dict[str,Any],list[dict[str,Any]]]:
    horse_ids=sorted(set(target.horse_id.astype(str)))
    histories: dict[str,list[dict[str,Any]]] = defaultdict(list)
    query_rows=0
    query_digest=hashlib.sha256()
    category_counts=Counter()
    special_evidence=[]
    sql_template="""SELECT e.id AS entry_id,e.event_id,e.horse_number,e.horse_name,e.hr_no AS horse_id,
                       e.finish_position,e.finish_time_ms,e.record_status,e.identity_status,
                       v.event_date,v.event_number,v.distance_m,v.population_status,
                       s.id AS source_row_id,s.source_artifact_id,s.line_number,s.row_sha256,
                       s.normalized_json,a.path AS source_artifact_path,a.sha256 AS source_artifact_sha256,
                       CAST(json_extract(s.normalized_json,'$.wgBudam') AS REAL) AS burden_kg
                FROM entry e JOIN event v ON e.event_id=v.id
                JOIN source_row s ON s.id=e.source_row_id
                JOIN source_artifact a ON a.id=s.source_artifact_id
                WHERE v.event_type='race' AND v.meet=2 AND v.population_status='confirmed_native_normal_race'
                  AND e.identity_status='official_race_ids_linked' AND e.hr_no IN ({})
                  AND e.finish_position IS NOT NULL
                ORDER BY v.event_date,v.event_number,e.horse_number,s.id"""
    source_query_sql=sql_template.replace("{}","<bound-parameter-batch>")
    query_hash=hashlib.sha256(source_query_sql.encode("utf-8")).hexdigest()
    for offset in range(0,len(horse_ids),350):
        batch=horse_ids[offset:offset+350]
        query=sql_template.format(",".join("?" for _ in batch))
        for raw in connection.execute(query,batch):
            row=dict(raw); query_rows+=1
            try:
                payload=json.loads(row["normalized_json"])
            except Exception as exc:
                raise ValueError(f"invalid API4 native source JSON for row {row['source_row_id']}") from exc
            code=int(row["finish_position"])
            raw_ord=payload.get("ord")
            if raw_ord is None or int(raw_ord)!=code:
                raise ValueError(f"raw ord differs from normalized finish position for {row['source_row_id']}")
            if _id(payload.get("hrNo"))!=str(row["horse_id"]):
                raise ValueError(f"raw official horse ID mismatch for {row['source_row_id']}")
            if int(payload.get("chulNo") or -1)!=int(row["horse_number"]):
                raise ValueError(f"raw horse number mismatch for {row['source_row_id']}")
            if int(payload.get("rcNo") or -1)!=int(row["event_number"]):
                raise ValueError(f"raw event number mismatch for {row['source_row_id']}")
            if str(payload.get("rcDate") or "")!=str(row["event_date"]).replace("-",""):
                raise ValueError(f"raw race date mismatch for {row['source_row_id']}")
            rc_time=payload.get("rcTime")
            try:
                rc_time=float(rc_time) if rc_time is not None else 0.0
            except (TypeError,ValueError):
                rc_time=0.0
            finish_ms=row.get("finish_time_ms")
            try: finish_ms=int(finish_ms) if finish_ms is not None else None
            except (TypeError,ValueError): finish_ms=None
            burden=row.get("burden_kg")
            try: burden=float(burden) if burden is not None else float("nan")
            except (TypeError,ValueError): burden=float("nan")
            positive_finish=math.isfinite(burden) and 30.0<=burden<=100.0 and finish_ms is not None and finish_ms>0
            normal=1<=code<=89 and row.get("record_status")=="normal_completed" and positive_finish
            special_positive=code in (91,92) and raw_ord==code and rc_time>0 and positive_finish
            actual_start_class=("normal_completed" if normal else
                                "actual_positive_time_observation" if special_positive else
                                "ambiguous_special_nonpositive_time" if code in (91,92) else
                                "not_eligible_actual_start")
            payload_sections={k:payload.get(k) for k in ("jeS1fTime","jeG1fTime","jeG3fTime","jeS1fAccTime","jeG1fAccTime","jeG3fAccTime")}
            section_positive=sum(1 for v in payload_sections.values() if isinstance(v,(int,float)) and float(v)>0)
            category_counts[actual_start_class]+=1
            canonical={
                "source_row_id":int(row["source_row_id"]),"source_row_sha256":str(row["row_sha256"]),
                "source_artifact_id":int(row["source_artifact_id"]),"source_artifact_path":str(row["source_artifact_path"]),
                "source_artifact_sha256":str(row["source_artifact_sha256"]),"line_number":int(row["line_number"] or 0),
                "event_date":str(row["event_date"]),"event_number":int(row["event_number"]),
                "distance_m":int(row["distance_m"] or 0),"horse_id":str(row["horse_id"]),
                "horse_number":int(row["horse_number"]),"finish_position":code,
                "record_status":str(row["record_status"]),"actual_burden_kg":burden if math.isfinite(burden) else None,
                "raw_ord":int(raw_ord),"raw_rcTime":rc_time,"finish_time_ms":finish_ms,
                "actual_start_class":actual_start_class,
            }
            query_digest.update(canonical_json_line(canonical))
            if code in (91,92):
                special_evidence.append({
                    "event_date":str(row["event_date"]),"event_number":int(row["event_number"]),
                    "horse_number":int(row["horse_number"]),"horse_id":str(row["horse_id"]),
                    "source_row_id":int(row["source_row_id"]),"source_row_sha256":str(row["row_sha256"]),
                    "source_artifact_path":str(row["source_artifact_path"]),"source_artifact_sha256":str(row["source_artifact_sha256"]),
                    "line_number":int(row["line_number"] or 0),"ord":code,"rcTime":rc_time,
                    "finish_time_ms":finish_ms,"record_status":str(row["record_status"]),
                    "positive_section_fields":section_positive,"prior_start_eligible":bool(special_positive),
                    "start_class":actual_start_class,
                    "source_payload_evidence":{
                        "ord":int(raw_ord),"rcTime":rc_time,"finish_time_ms":finish_ms,
                        "record_status":str(row["record_status"]),"wgBudam":burden if math.isfinite(burden) else None,
                        **payload_sections,
                    },
                })
            if normal or special_positive:
                eventdate=date.fromisoformat(str(row["event_date"]))
                histories[str(row["horse_id"])].append({
                    "race_date":eventdate,"race_date_str":eventdate.isoformat(),"event_number":int(row["event_number"]),
                    "race_id":eventdate.isoformat()+"_2_"+str(int(row["event_number"])),
                    "horse_id":str(row["horse_id"]),"horse_number":int(row["horse_number"]),
                    "burden_kg":burden,"source_row_id":int(row["source_row_id"]),
                    "source_row_sha256":str(row["row_sha256"]),"source_artifact_id":int(row["source_artifact_id"]),
                    "source_artifact_path":str(row["source_artifact_path"]),"source_artifact_sha256":str(row["source_artifact_sha256"]),
                    "line_number":int(row["line_number"] or 0),"finish_position":code,
                    "start_class":actual_start_class,"record_status":str(row["record_status"]),
                })
    for horse_id,rows in histories.items():
        rows.sort(key=lambda x:(x["race_date"],x["event_number"],x["source_row_id"]))
        if len({x["race_date"] for x in rows})!=len(rows):
            raise ValueError(f"duplicate actual horse/day observations for {horse_id}")
    return histories,{"query_sql":source_query_sql,"query_sql_sha256":query_hash,"query_rows":query_rows,
                       "canonical_jsonl_sha256":query_digest.hexdigest(),"eligibility_counts":dict(category_counts),
                       "special_rows":len(special_evidence)},special_evidence


def _select_prior(histories: dict[str,list[dict[str,Any]]], ambiguous: dict[str,list[dict[str,Any]]],
                  horse_id: str, target_race_date: str, snapshot_end: date) -> dict[str,Any]:
    target_date=date.fromisoformat(str(target_race_date))
    cutoff=target_date-timedelta(days=2)
    complete=cutoff<=snapshot_end
    rows=histories.get(str(horse_id),[])
    ambiguous_rows=[row for row in ambiguous.get(str(horse_id),[]) if row["race_date"]<=cutoff]
    dates=[row["race_date"] for row in rows]
    pos=bisect.bisect_right(dates,cutoff)-1
    if pos<0:
        status=("source_snapshot_truncated_before_cutoff_no_observed_prior" if not complete else
                "no_prior_valid_actual_after_ambiguous_special" if ambiguous_rows else
                "no_prior_valid_actual_burden")
        return {"latest_prior_burden_kg":None,"latest_prior_race_date":None,"latest_prior_race_id":None,
                "latest_prior_horse_id":None,"latest_prior_source_row_id":None,"latest_prior_source_row_sha256":None,
                "latest_prior_source_artifact_id":None,"latest_prior_source_artifact_path":None,
                "latest_prior_source_artifact_sha256":None,"latest_prior_source_line_number":None,
                "latest_prior_start_class":None,
                "latest_prior_status":status,
                "prior_source_snapshot_complete":bool(complete),"latest_prior_cutoff":cutoff.isoformat(),
                "latest_prior_fallback_after_ambiguous_special":False}
    row=rows[pos]
    # Excluded ord 92 rows are not silently treated as a nonstarter or as a valid burden.
    # The status indicates when the selected valid observation precedes such a later ambiguous row.
    fallback=bool(ambiguous_rows and max(x["race_date"] for x in ambiguous_rows)>row["race_date"])
    status="fallback_after_ambiguous_special_92" if fallback else "latest_valid_actual_burden"
    if not complete:
        status="latest_observed_through_snapshot_cutoff_not_complete_asof_T_minus_2"
    return {"latest_prior_burden_kg":float(row["burden_kg"]),"latest_prior_race_date":row["race_date_str"],
            "latest_prior_race_id":row["race_id"],"latest_prior_horse_id":row["horse_id"],
            "latest_prior_source_row_id":row["source_row_id"],"latest_prior_source_row_sha256":row["source_row_sha256"],
            "latest_prior_source_artifact_id":row["source_artifact_id"],"latest_prior_source_artifact_path":row["source_artifact_path"],
            "latest_prior_source_artifact_sha256":row["source_artifact_sha256"],"latest_prior_source_line_number":row["line_number"],
            "latest_prior_start_class":row["start_class"],"latest_prior_status":status,
            "prior_source_snapshot_complete":bool(complete),"latest_prior_cutoff":cutoff.isoformat(),
            "latest_prior_fallback_after_ambiguous_special":fallback}


def main() -> None:
    AUDIT.mkdir(parents=True,exist_ok=True)
    outputs=[AUDIT/"entry_condition_inputs.parquet",AUDIT/"source_contract.json",AUDIT/"SOURCE_AUDIT.json",AUDIT/"SOURCE_AUDIT.md",AUDIT/"special_prior_evidence.json"]
    for output in outputs: _safe_output(output)
    contract_bytes=CONTRACT.read_bytes()
    contract_sha=hashlib.sha256(contract_bytes).hexdigest()
    target=_read_s_target()
    target_h3,h3_entries,h3_lineage,doc_map=_read_h3_sources(target)
    connection=_db_open()
    official,official_query_meta=_official_event_rows(connection,target)
    histories,history_query,special_evidence=_actual_history(connection,target)
    connection.close()

    # Confirm the full on-disk DB hash rather than reusing only the historical manifest pin.
    db_actual_sha=sha256_file(DB_PATH)
    db_manifest=json.loads(DB_MANIFEST.read_text(encoding="utf-8"))
    if db_actual_sha!=EXPECTED_DB_SHA256 or db_manifest.get("database_sha256")!=db_actual_sha:
        raise ValueError("read-only native DB stream hash does not match its frozen manifest")

    parsed,doc_rows,doc_refs=_parse_dacom_docs(target_h3,doc_map,official)
    roster_proof,raw_choice=_roster_proofs(target,official,target_h3,parsed,doc_map)

    # Build selected features and audit-only lineage while preserving all S40 rows.
    h3_natural_lookup={}
    for row in target_h3.itertuples(index=False):
        key=(str(row.race_date),int(row.event_number),str(row.horse_id),int(row.horse_number))
        if pd.isna(row.entry_id):
            continue
        if key in h3_natural_lookup:
            raise ValueError(f"duplicate S-to-H3 natural key: {key}")
        h3_natural_lookup[key]=row
    ambiguous_by_horse: dict[str,list[dict[str,Any]]] = defaultdict(list)
    for item in special_evidence:
        if not item["prior_start_eligible"]:
            ambiguous_by_horse[str(item["horse_id"])].append({
                "race_date":date.fromisoformat(item["event_date"]),"event_number":int(item["event_number"]),
                "source_row_id":int(item["source_row_id"]),"start_class":item["start_class"]})
    rows=[]
    snapshot_end=date(2026,9,12)
    for target_row in target.itertuples(index=False):
        race_id=str(target_row.race_id); rdate=str(target_row.race_date); eno=int(target_row.event_number)
        proof=roster_proof.get(race_id,{"confirmed":False,"reason":"no_roster_proof","source_status":"unconfirmed"})
        h3_row=None
        # The natural join requires official date/event/horse-ID/number equality.
        h3_row=h3_natural_lookup.get((rdate,eno,str(target_row.horse_id),int(target_row.horse_number)))
        current_weight=None; declared_number=None; source_doc=None; source_file_date=None
        source_line_number=None; source_line_sha=None; source_raw_name=None; source_doc_sha=None; source_retrieved=None
        current_source_status="no_dated_declaration_for_target"
        burden_status="missing_no_dated_declaration"
        full_doc_id=proof.get("document_id") if proof.get("confirmed") else None
        full_doc_date=proof.get("source_file_date") if proof.get("confirmed") else None
        full_doc_sha=proof.get("source_document_sha256") if proof.get("confirmed") else None
        if not proof.get("confirmed"):
            if proof.get("reason")=="official_roster_id_name_or_distance_mismatch":
                current_source_status="unverified_full_card_roster_conflict"
                burden_status="missing_full_card_roster_conflict"
            elif rdate>"2026-09-12":
                current_source_status="no_dated_declaration_snapshot"
                burden_status="missing_no_source_document_snapshot_tail"
            else:
                current_source_status="unverified_full_card_roster"
                burden_status="missing_full_card_roster_unverified"
        else:
            # Exact H3 declaration row, already accepted by the original frozen builder.
            if h3_row is not None and int(getattr(h3_row,"card_observed_feature",getattr(h3_row,"card_observed",0)) or 0)==1:
                # pandas suffixes can differ depending on duplicate card_observed; resolve from frame columns below.
                h3feat=target_h3.loc[target_h3.entry_id.eq(h3_row.entry_id)].iloc[0]
                observed=int(h3feat.get("card_observed_feature",h3feat.get("card_observed",0)) or 0)
                source_id_value=h3feat.get("source_document_id_lineage",h3feat.get("source_document_id"))
                if observed==1 and pd.notna(source_id_value):
                    source_id=int(source_id_value); meta=doc_map[source_id]
                    candidates=parsed.get((source_id,rdate,eno),[])
                    number=int(target_row.horse_number)
                    source_matches=[x for x in candidates if int(x["horse_number"])==number and int(x["line_number"])==int(h3feat.get("source_line_number") or -1)]
                    if len(source_matches)!=1: raise ValueError(f"H3 declared source line not uniquely found: {race_id}/{number}")
                    raw=source_matches[0]
                    official_row=official.get((rdate,eno,number))
                    if not official_row or _id(official_row.get("hr_no"))!=str(target_row.horse_id):
                        raise ValueError("H3 current declaration lacks matching official source identity")
                    if str(raw["horse_name"])!=str(official_row["horse_name"]) or str(official_row["horse_name"])!=str(target_row.horse_name):
                        raise ValueError("H3 exact-name declaration differs from official/current target name")
                    if int(raw.get("distance") or -1)!=int(target_row.distance_m): raise ValueError("H3 declaration distance mismatch")
                    if str(raw["source_line_sha256"])!=str(h3feat.get("source_line_sha256")): raise ValueError("H3 source line SHA mismatch")
                    burden=float(h3feat.get("declared_burden_kg") or float("nan"))
                    number_value=int(h3feat.get("declared_horse_number"))
                    if not math.isfinite(burden) or not 30<=burden<=100 or number_value!=number: raise ValueError("H3 current declaration value invalid")
                    current_weight=burden; declared_number=number_value
                    source_doc=source_id; source_file_date=str(meta["file_date"]); source_line_number=int(raw["line_number"])
                    source_line_sha=str(raw["source_line_sha256"]); source_raw_name=str(raw["horse_name"])
                    source_doc_sha=str(meta["sha256"]); source_retrieved=meta.get("retrieved_at_ms")
                    current_source_status="dacom01_exact_name_match"; burden_status="observed_h3_exact_name"
            # Only supplement the exact, single leading-star match approved by the supervisor.
            if current_weight is None:
                number=int(target_row.horse_number); official_row=official.get((rdate,eno,number))
                if official_row and _id(official_row.get("hr_no"))==str(target_row.horse_id) and str(official_row.get("horse_name"))==str(target_row.horse_name):
                    rows_in_full=parsed.get((int(full_doc_id),rdate,eno),[]) if full_doc_id is not None else []
                    alternatives=[x for x in rows_in_full if int(x["horse_number"])==number and
                                 str(x.get("horse_name"))=="★"+str(official_row["horse_name"]) and
                                 int(x.get("distance") or -1)==int(target_row.distance_m)]
                    if len(alternatives)==1 and h3_row is not None:
                        raw=alternatives[0]
                        burden=float(raw["burden"]); number_value=int(raw["horse_number"])
                        if math.isfinite(burden) and 30<=burden<=100 and number_value==number:
                            meta=doc_map[int(full_doc_id)]
                            current_weight=burden; declared_number=number_value
                            source_doc=int(full_doc_id); source_file_date=str(meta["file_date"])
                            source_line_number=int(raw["line_number"]); source_line_sha=str(raw["source_line_sha256"])
                            source_raw_name=str(raw["horse_name"]); source_doc_sha=str(meta["sha256"])
                            source_retrieved=meta.get("retrieved_at_ms")
                            current_source_status="dacom01_direct_single_star_marker_match"
                            burden_status="supplemented_exact_single_star_marker_only"
                if current_weight is None:
                    current_source_status="no_dated_declaration_for_target"
                    burden_status="missing_declaration_row_not_approved_for_supplement"
        # Unverified full-roster races are intentionally all-null at the race level.
        if not proof.get("confirmed"):
            current_weight=None; declared_number=None; source_doc=None; source_file_date=None
            source_line_number=None; source_line_sha=None; source_raw_name=None; source_doc_sha=None; source_retrieved=None

        # Number position is sourced from the independently confirmed complete
        # declaration roster, not conditioned on a nonmissing burden value.
        if proof.get("confirmed"):
            roster_row=raw_choice.get((int(full_doc_id),rdate,eno,int(target_row.horse_number)))
            if roster_row is None:
                raise ValueError(f"confirmed full-card roster lost target number: {race_id}/{target_row.horse_number}")
            roster_number=int(roster_row["horse_number"])
            if roster_number!=int(target_row.horse_number):
                raise ValueError(f"confirmed roster number differs from S40: {race_id}/{target_row.horse_number}")
            if declared_number is None:
                declared_number=roster_number
        max_number=proof.get("max_declared_horse_number") if proof.get("confirmed") else None
        fraction=None
        if declared_number is not None and max_number is not None and int(max_number)>1:
            fraction=(int(declared_number)-1)/(int(max_number)-1)
        if max_number is None:
            number_status="missing_full_card_denominator_unconfirmed"
        elif declared_number is None:
            number_status="missing_declared_number"
        elif int(max_number)<=1:
            number_status="denominator_not_above_one"
        else:
            number_status="observed_declared_number_fraction"

        prior=_select_prior(histories,ambiguous_by_horse,str(target_row.horse_id),rdate,snapshot_end)
        # When the current declaration is missing, the delta must remain missing even if an observed prior exists.
        delta=(float(current_weight)-float(prior["latest_prior_burden_kg"])
               if current_weight is not None and prior["latest_prior_burden_kg"] is not None else None)
        entry_id=int(h3_row.entry_id) if h3_row is not None else None
        source_event_number=eno
        h3_event_id=int(h3_row.event_number_key) if h3_row is not None else None
        output={
            "api_record_id":int(target_row.api_record_id),"race_id":race_id,"race_date":rdate,
            "horse_id":str(target_row.horse_id),"horse_number":int(target_row.horse_number),"field_n":int(target_row.field_n),
            "current_declared_burden_kg":current_weight,"burden_change_vs_last_valid_kg":delta,"horse_number_fraction":fraction,
            "entry_id":entry_id,"event_number":source_event_number,"source_event_number":h3_event_id,
            "target_distance_m":int(target_row.distance_m),"target_horse_name":str(target_row.horse_name),
            "declared_horse_number":declared_number,"max_declared_horse_number":max_number,
            "max_full_card_declared_horse_number":max_number,
            "full_card_roster_confirmed":bool(proof.get("confirmed")),"full_card_roster_status":proof.get("source_status"),
            "full_card_roster_reason":proof.get("reason"),"max_declared_horse_number_source_document_id":full_doc_id,
            "max_declared_horse_number_source_file_date":full_doc_date,
            "max_declared_horse_number_source_document_sha256":full_doc_sha,
            "max_declared_horse_number_source_status":proof.get("source_status"),
            "source_document_id":source_doc,"source_file_date":source_file_date,
            "source_document_sha256":source_doc_sha,"source_retrieved_at_ms":source_retrieved,
            "source_line_number":source_line_number,"source_line_sha256":source_line_sha,
            "source_raw_horse_name":source_raw_name,"source_type":"dacom01_h3_dated_declaration",
            "publication_time_status":"assumed_from_declaration_date_publication_unverified",
            "pre_race_availability_verified":False,"pre_race_availability_assumption":True,
            "current_source_status":current_source_status,"burden_status":burden_status,"number_status":number_status,
            "latest_prior_burden_kg":prior["latest_prior_burden_kg"],
            "latest_prior_race_date":prior["latest_prior_race_date"],"latest_prior_race_id":prior["latest_prior_race_id"],
            "latest_prior_horse_id":prior["latest_prior_horse_id"],
            "latest_prior_source_row_id":prior["latest_prior_source_row_id"],
            "latest_prior_source_row_sha256":prior["latest_prior_source_row_sha256"],
            "latest_prior_source_artifact_id":prior["latest_prior_source_artifact_id"],
            "latest_prior_source_artifact_path":prior["latest_prior_source_artifact_path"],
            "latest_prior_source_artifact_sha256":prior["latest_prior_source_artifact_sha256"],
            "latest_prior_source_line_number":prior["latest_prior_source_line_number"],
            "latest_prior_start_class":prior["latest_prior_start_class"],"latest_prior_status":prior["latest_prior_status"],
            "prior_source_snapshot_complete":prior["prior_source_snapshot_complete"],
            "latest_prior_cutoff":prior["latest_prior_cutoff"],
            "latest_prior_fallback_after_ambiguous_special":prior["latest_prior_fallback_after_ambiguous_special"],
            "latest_prior_eligibility_rule":SPECIAL_ELIGIBILITY_RULE,
        }
        rows.append(output)

    frame=pd.DataFrame(rows)
    if len(frame)!=TARGET_ROWS or frame.api_record_id.duplicated().any(): raise ValueError("built input failed exact target coverage")
    if frame.groupby("race_id").size().ne(frame.groupby("race_id").field_n.first()).any(): raise ValueError("built rows no longer preserve field_n")
    if frame["current_declared_burden_kg"].notna().ne(frame["burden_status"].str.startswith("observed_h3_exact_name")|
                                                       frame["burden_status"].eq("supplemented_exact_single_star_marker_only")).any():
        # Explicitly verify the positive-source classes; missing classes remain null.
        raise ValueError("current burden/status consistency failed")
    if frame["burden_change_vs_last_valid_kg"].notna().ne(frame["current_declared_burden_kg"].notna() & frame["latest_prior_burden_kg"].notna()).any():
        raise ValueError("burden delta missingness does not match current and prior values")
    if frame.loc[frame.race_date.gt("2026-09-12"),"current_declared_burden_kg"].notna().any():
        raise ValueError("2026 source-snapshot tail must remain current-burden null")
    if frame.loc[frame.race_date.gt("2026-09-12"),"burden_change_vs_last_valid_kg"].notna().any():
        raise ValueError("2026 source-snapshot tail must remain burden-delta null")

    # Source references are immutable, path-rooted records. The database is stream-hashed above.
    references=[]
    for path in [S_FEATURES,H3_ENTRIES,H3_ROOT/"features.parquet",H3_ROOT/"lineage.parquet",
                 H3_ROOT/"source_documents.json",DB_MANIFEST,CONTRACT,
                 ROOT/"src/horse_racing/analysis/jeju_h3_features.py",
                 ROOT/"src/horse_racing/analysis/jeju_native_top3_dataset.py",Path(__file__).resolve()]:
        references.append(file_ref(path))
    references.append(file_ref(DB_PATH,expected_sha=EXPECTED_DB_SHA256,actual_hash=False))
    # Replace the DB manifest-style reference with the actual streamed digest already verified.
    references[-1]["sha256_method"]="streamed_actual_file_verified_against_manifest"
    doc_ref_map={r["path"]:r for r in doc_refs}
    references.extend(doc_ref_map[k] for k in sorted(doc_ref_map))
    # Native result files used by the prior-burden query, verified against source_artifact SHA pins in SQLite.
    prior_artifacts={}
    for horse_rows in histories.values():
        for row in horse_rows:
            prior_artifacts[row["source_artifact_path"]]=row["source_artifact_sha256"]
    artifact_file_status=[]
    for relative, expected in sorted(prior_artifacts.items()):
        candidate=Path(relative)
        candidate=candidate if candidate.is_absolute() else ROOT/candidate
        if candidate.is_file():
            references.append(file_ref(candidate,expected_sha=expected))
            artifact_file_status.append({"path":relative,"database_sha256":expected,"file_present":True})
        else:
            artifact_file_status.append({"path":relative,"database_sha256":expected,"file_present":False,
                                         "note":"Native source payload rows remain in the pinned read-only SQLite source; raw artifact file was not available and was not copied."})
    history_query["source_artifact_files"]=artifact_file_status
    refs_by_path={item["path"]:item for item in references}
    references=list(refs_by_path.values())

    # Exact aggregate support and special-code impact counts, no outcome/performance statistics.
    current_by_year={}
    for year,group in frame.groupby(frame.race_date.str[:4]):
        current_by_year[str(year)]={"target_rows":len(group),"races":int(group.race_id.nunique()),
                                    "current_burden_nonmissing":int(group.current_declared_burden_kg.notna().sum()),
                                    "current_burden_missing":int(group.current_declared_burden_kg.isna().sum()),
                                    "number_fraction_nonmissing":int(group.horse_number_fraction.notna().sum()),
                                    "prior_actual_nonmissing":int(group.latest_prior_burden_kg.notna().sum()),
                                    "delta_nonmissing":int(group.burden_change_vs_last_valid_kg.notna().sum())}
    special_ids={int(x["source_row_id"]) for x in special_evidence}
    ambiguous_ids={int(x["source_row_id"]) for x in special_evidence if not x["prior_start_eligible"]}
    rows_with_fallback=int(frame.latest_prior_fallback_after_ambiguous_special.sum())
    counters={"target_rows":len(frame),"target_races":int(frame.race_id.nunique()),
              "full_card_roster_confirmed_races":int(pd.Series({k:v["confirmed"] for k,v in roster_proof.items()}).sum()),
              "full_card_roster_unconfirmed_races":int(sum(not v["confirmed"] for v in roster_proof.values())),
              "current_burden_nonmissing_rows":int(frame.current_declared_burden_kg.notna().sum()),
              "current_burden_missing_rows":int(frame.current_declared_burden_kg.isna().sum()),
              "star_marker_supplement_rows":int(frame.current_source_status.eq("dacom01_direct_single_star_marker_match").sum()),
              "number_fraction_nonmissing_rows":int(frame.horse_number_fraction.notna().sum()),
              "prior_actual_nonmissing_rows":int(frame.latest_prior_burden_kg.notna().sum()),
              "prior_actual_nohistory_rows":int(frame.latest_prior_burden_kg.isna().sum()),
              "prior_actual_delta_nonmissing_rows":int(frame.burden_change_vs_last_valid_kg.notna().sum()),
              "prior_snapshot_truncated_rows":int((~frame.prior_source_snapshot_complete).sum()),
              "prior_fallback_rows_after_ambiguous_special":rows_with_fallback,
              "event_2019_conflict_null_rows":int((frame.race_date.str.startswith("2019") & frame.burden_status.eq("missing_full_card_roster_conflict")).sum()),
              "tail_after_2026_09_12_rows":int(frame.race_date.gt("2026-09-12").sum()),
              "ambiguous_special_source_rows":len(ambiguous_ids)}

    # Persist the new feature+lineage table once, in compressed Parquet. Model readers later select only the 3 features.
    parquet_path=AUDIT/"entry_condition_inputs.parquet"
    _safe_output(parquet_path)
    frame.to_parquet(parquet_path,index=False,compression="zstd")
    with parquet_path.open("rb") as handle: os.fsync(handle.fileno())
    artifact_ref=file_ref(parquet_path)

    input_contract={
        "study":"20261024_s_entry_conditions_v1",
        "status":"SOURCE_AUDIT_PASS_PENDING_SUPERVISOR_REVIEW",
        "weight_unit":"kg","previous_weight_rule":PREVIOUS_WEIGHT_RULE,
        "number_fraction_formula":NUMBER_FORMULA,"max_number_column":"max_declared_horse_number",
        "number_denominator_rule":NUMBER_DENOMINATOR_RULE,
        "feature_columns":FEATURE_COLUMNS,"current_weight_source_type":"dacom01_h3_dated_declaration",
        "current_source_status_allowed_values":["dacom01_exact_name_match","dacom01_direct_single_star_marker_match",
            "no_dated_declaration_for_target","unverified_full_card_roster_conflict","no_dated_declaration_snapshot",
            "unverified_full_card_roster"],
        "publication_time_status":"assumed_from_declaration_date_publication_unverified",
        "pre_race_availability_verified":False,"pre_race_availability_assumption":True,
        "current_source_rule":"Existing H3 declared burden is reused only where exact natural keys and source line proof match. A new-input-only supplement permits exactly raw horse_name == '★'+official H3/source name, after validating target date/event_number/horse_number/distance/official horse ID and a full-card roster; no other normalization. The marker meaning is not inferred. Existing H3 files are unchanged.",
        "prior_weight_source":"API4/native result source_row.normalized_json $.wgBudam (actual carried burden), not a prior H3 declaration",
        "previous_weight_source_type":"api4_native_result_source_row.normalized_json.$.wgBudam_actual_carried_weight",
        "latest_prior_selection_rule":"maximum eligible event date <= T−2 inclusive; unique horse/day required; deterministic event_number/source_row_id order; duplicates rejected",
        "prior_start_rule":SPECIAL_ELIGIBILITY_RULE,
        "latest_prior_validity_rule":"raw ord == finish_position; burden 30..100 kg; normal_completed ord 1..89 with positive finish_time_ms; ord 91/92 require raw rcTime>0 and positive finish_time_ms and are labeled actual_positive_time_observation without ordinal semantics",
        "latest_prior_valid_statuses":["latest_valid_actual_burden","fallback_after_ambiguous_special_92","latest_observed_through_snapshot_cutoff_not_complete_asof_T_minus_2"],
        "latest_prior_valid_start_classes":["normal_completed","actual_positive_time_observation"],
        "latest_prior_status_values":["latest_valid_actual_burden","fallback_after_ambiguous_special_92","latest_observed_through_snapshot_cutoff_not_complete_asof_T_minus_2","no_prior_valid_actual_burden","no_prior_valid_actual_after_ambiguous_special","source_snapshot_truncated_before_cutoff_no_observed_prior"],
        "latest_prior_missing_statuses":["no_prior_valid_actual_burden","no_prior_valid_actual_after_ambiguous_special","source_snapshot_truncated_before_cutoff_no_observed_prior"],
        "latest_prior_fallback_flag_column":"latest_prior_fallback_after_ambiguous_special",
        "latest_prior_fallback_flag_meaning":"True when a later (but still T−2 eligible) ord 91/92 row lacks positive time evidence and the selected eligible actual burden is an earlier race observation; does not classify the special row as a nonstarter.",
        "prior_source_snapshot_end":"2026-09-12",
        "prior_source_snapshot_policy":"For targets whose T−2 cutoff is after the source snapshot end, latest observed prior burden is lineage-only and marked incomplete as of cutoff; target current declaration is unavailable for the 198-row tail, so burden_change remains NULL.",
        "ambiguous_special_policy":"The 24 S-ID-linked ord=92 rows have rcTime=0 and no positive finish_time_ms; some have partial split fields. They are held out as unknown, not labeled nonstarters. Previous-value selection may fall back to an earlier eligible actual result; this is marked when it occurs.",
        "prior_source_status_values":["latest_valid_actual_burden","fallback_after_ambiguous_special_92",
            "latest_observed_through_snapshot_cutoff_not_complete_asof_T_minus_2","no_prior_valid_actual_burden",
            "no_prior_valid_actual_after_ambiguous_special","source_snapshot_truncated_before_cutoff_no_observed_prior"],
        "prior_start_class_values":["normal_completed","actual_positive_time_observation"],
        "latest_prior_cutoff_rule":"Every input row stores latest_prior_cutoff = race_date minus 2 calendar days inclusive, regardless of whether a valid prior observation exists.",
        "full_card_roster_confirmed_statuses":["full_card_roster_exact"],
        "number_denominator_source_statuses":["full_card_roster_exact"],
        "full_card_roster_status_values":["full_card_roster_exact","unconfirmed"],
        "full_card_roster_reason_values":["exact_full_card_official_roster_match","official_roster_id_name_or_distance_mismatch","no_exact_full_card_source_roster"],
        "full_card_roster_max_relation":"When confirmed, the complete source roster number set equals the frozen S40 target roster number set; therefore max_full_card_declared_horse_number equals the S40 target race maximum. When unconfirmed, both denominator fields are NULL.",
        "prior_source_query":history_query,
        "input_artifact":{**artifact_ref,"format":"parquet","compression":"zstd","rows":len(frame),"races":int(frame.race_id.nunique()),
                           "path":"jeju/research/20261024_s_entry_conditions_v1/audit/entry_condition_inputs.parquet"},
        "feature_table_semantics":"All non-feature columns are audit lineage and must never be passed to a model; only exactly feature_columns may be used.",
        "source_references":references,
        "contract_sha256":contract_sha,
        "cohort":{"rows":TARGET_ROWS,"races":TARGET_RACES,"training_evaluation_source":"F1_STYLE6 frozen keys only; finish labels were not read by this builder"},
        "support":counters,
        "support_by_target_year":current_by_year,
    }
    _write_once(AUDIT/"source_contract.json",json.dumps(input_contract,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode("utf-8")+b"\n")
    _write_once(AUDIT/"special_prior_evidence.json",json.dumps(special_evidence,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode("utf-8")+b"\n")
    # Include source rows in the final immutable audit pin set and keep the field schema explicit.
    audit_json={
        "passed":True,"status":"SOURCE_AUDIT_PASS_PENDING_SUPERVISOR_REVIEW",
        "source_references":references,
        "source_contract_path":"jeju/research/20261024_s_entry_conditions_v1/audit/source_contract.json",
        "source_contract_sha256":sha256_file(AUDIT/"source_contract.json"),
        "input_artifact":artifact_ref,"input_schema_columns":list(frame.columns),
        "feature_columns":FEATURE_COLUMNS,"support":counters,"support_by_target_year":current_by_year,
        "full_card_roster_reason_counts":dict(Counter(v["reason"] for v in roster_proof.values())),
        "special_prior_evidence":{"rows":len(special_evidence),"codes":dict(Counter(str(x["ord"]) for x in special_evidence)),
          "eligible_positive_time_rows":sum(bool(x["prior_start_eligible"]) for x in special_evidence),
          "ambiguous_nonpositive_rows":sum(not bool(x["prior_start_eligible"]) for x in special_evidence),
          "rows_with_partial_section_time":sum(int(x["positive_section_fields"])>0 and not bool(x["prior_start_eligible"]) for x in special_evidence),
          "sample_path":"jeju/research/20261024_s_entry_conditions_v1/audit/special_prior_evidence.json"},
        "source_query":history_query,"official_roster_query":official_query_meta,
        "readonly_sqlite":{"mode":"ro","query_only":True,"database_sha256_streamed":db_actual_sha,
          "database_bytes":DB_PATH.stat().st_size,"snapshot_event_end":"2026-09-12"},
        "target_labels_read":False,"fit_or_evaluation_run":False,"new_source_copy_created":False,
        "allowed_current_marker_rule":"exactly one leading U+2605 STAR followed by the official name; no other normalization; marker meaning not inferred",
        "unresolved_limits":["Dacom01 file_date<=T-2 is a date-based availability assumption; original publication/revision timestamp was not recovered.",
          "The 2019 40-row identity/name-conflict cohort and 2026-09-17..19 198-row source tail remain NULL.",
          "The 24 ord=92 special rows with no positive official finish time are unknown and excluded from prior eligibility; this is not a declaration that they did not start."],
    }
    _write_once(AUDIT/"SOURCE_AUDIT.json",json.dumps(audit_json,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False).encode("utf-8")+b"\n")
    lines=[
        "# S 출전조건 원천 감사", "",
        "이 감사는 frozen S40 키만 사용해 현재 출전선언 부담중량, T−2 이전 실제 부담중량, 출주번호 비율의 3개 입력과 계보를 만들었습니다. 학습·추론·성과 평가·시장 자료는 사용하지 않았습니다.", "",
        f"- 출력: `{artifact_ref['path']}` ({artifact_ref['bytes']:,} bytes, SHA-256 `{artifact_ref['sha256']}`; ZSTD Parquet)",
        f"- Contract SHA-256: `{sha256_file(AUDIT/'source_contract.json')}`",
        f"- 분모: {counters['target_races']:,} races / {counters['target_rows']:,} rows; exact full-card roster confirmed {counters['full_card_roster_confirmed_races']:,} races.",
        f"- 현재 선언 부담: {counters['current_burden_nonmissing_rows']:,} rows; exact ★ supplement {counters['star_marker_supplement_rows']:,}; missing {counters['current_burden_missing_rows']:,}.",
        f"- 출주번호 fraction available: {counters['number_fraction_nonmissing_rows']:,}; prior actual burden available: {counters['prior_actual_nonmissing_rows']:,}; burden delta available: {counters['prior_actual_delta_nonmissing_rows']:,}.",
        "- 2019의 이름 충돌 네 경주 40행과 2026-09-17..19의 source tail 198행은 현재 부담·번호·delta를 NULL로 유지합니다. 최신 관측 이전 부담이 존재할 수 있는 tail 행은 snapshot 불완전 상태를 lineage에 표시합니다.",
        "- 135개의 raw `★` 접두행만 같은 date/event/horse number/distance와 공식 ID/name을 대조한 뒤 신규 입력에서 보완했습니다. 별표 의미는 추정하지 않았고 원래 H3 파일은 바꾸지 않았습니다.",
        "- 직전 실제 부담은 API4 `source_row.normalized_json.$.wgBudam`; 정상완주 1..89를 쓰고 ord 91/92는 raw `rcTime`와 normalized finish time이 모두 양수인 18행만 `actual_positive_time_observation`으로 포함합니다. 24개의 nonpositive ord92는 unknown으로 보류하고 앞선 valid actual이 선택되면 fallback status를 남깁니다.",
        f"- DB read-only hash: `{db_actual_sha}` ({DB_PATH.stat().st_size:,} bytes; mode=ro + `query_only=ON`; file copied 0).",
        f"- Native history query rows: {history_query['query_rows']:,}; canonical row/weight/status JSONL aggregate SHA-256 `{history_query['canonical_jsonl_sha256']}`.",
        "- Dacom01 `file_date <= T−2`는 문서날짜 기반 가정이며 실제 최초 공개·정정 시각은 입증되지 않았습니다. `retrieved_at_ms`는 수집 시각입니다.",
        "- 전체 출처 목록, schema, year counts, read-only SQL, special-code evidence 샘플은 `SOURCE_AUDIT.json`, `source_contract.json`, `special_prior_evidence.json`에 고정했습니다.",
        "- 생성 파일은 모두 기록된 뒤 마지막 진단 JSON 출력에서 tuple Counter key 직렬화 오류로 프로세스가 비정상 종료했습니다. Parquet/원천 참조 값은 바꾸지 않고 출력 serializer만 수정했으며, 이 실행 경로는 재생성하지 않았습니다.",
        "",
    ]
    _write_once(AUDIT/"SOURCE_AUDIT.md",("\n".join(lines)).encode("utf-8"))
    print(json.dumps({"passed":True,"support":counters,"input_artifact":artifact_ref,
                      "source_contract_sha256":sha256_file(AUDIT/"source_contract.json"),
                      "audit_json_sha256":sha256_file(AUDIT/"SOURCE_AUDIT.json"),
                      "history_query":history_query,"special_counts":{f"ord={k[0]}|eligible={k[1]}":v for k,v in Counter((x["ord"],x["prior_start_eligible"]) for x in special_evidence).items()},
                      "full_card_reason_counts":dict(Counter(v["reason"] for v in roster_proof.values()))},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()

"""Build strictly lagged race-context/form features for sealed r2 starters."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_context_features import (
    CONTEXT_FEATURES,
    CUTOFF_DAYS,
    FEATURE_DEFINITIONS,
    FEATURES,
    FORM_FEATURES,
    build_features,
    parse_body_weight,
    parse_track_moisture,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"
H3 = ROOT / "data/research/jeju_native_h3_features_v1_20260916"
DB = ROOT / "data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3"
OUT = ROOT / "data/research/jeju_native_context_features_v1_20260916"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date(value) -> date:
    text = str(value).replace("-", "")
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _source_rows(connection: sqlite3.Connection) -> dict[int, dict]:
    query = """
        SELECT e.id AS entry_id, e.horse_name, e.hr_no AS horse_id,
               e.horse_number, v.event_date, v.event_number, v.distance_m,
               v.weather, v.track_moisture_percent,
               json_extract(s.normalized_json, '$.track') AS track_raw,
               json_extract(s.normalized_json, '$.wgBudam') AS burden_kg,
               json_extract(s.normalized_json, '$.wgHr') AS body_weight_raw,
               json_extract(s.normalized_json, '$.jkName') AS jockey_name,
               json_extract(s.normalized_json, '$.jkNo') AS jockey_id,
               json_extract(s.normalized_json, '$.sjS1fOrd') AS early_rank,
               json_extract(s.normalized_json, '$.sjG1fOrd') AS g1_rank,
               json_extract(s.normalized_json, '$.sj_4cOrd') AS late_rank,
               json_extract(s.normalized_json, '$.jeS1fTime') AS s1f_seconds,
               json_extract(s.normalized_json, '$.jeG1fTime') AS g1f_seconds,
               json_extract(s.normalized_json, '$.jeG3fTime') AS g3f_seconds
        FROM entry e
        JOIN event v ON v.id = e.event_id
        JOIN source_row s ON s.id = e.source_row_id
        WHERE v.event_type = 'race' AND v.event_date <= '20251231'
    """
    result = {}
    for row in connection.execute(query):
        item = dict(row)
        item["event_date"] = _date(item["event_date"])
        if item["track_moisture_percent"] is None:
            item["track_moisture_percent"] = parse_track_moisture(item.get("track_raw"))
        item["body_weight_kg"] = parse_body_weight(item.pop("body_weight_raw"))
        item["time_ms"] = None
        result[int(item["entry_id"])] = item
    return result


def _history_rows(
    entries: pl.DataFrame, labels: pl.DataFrame, source: dict[int, dict], states: pl.DataFrame
):
    label_map = {int(row["entry_id"]): row for row in labels.iter_rows(named=True)}
    state_map = {
        int(row["entry_id"]): row
        for row in states.select("entry_id", "global_elo_pre", "distance_elo_pre").iter_rows(
            named=True
        )
    }
    records = []
    for row in entries.iter_rows(named=True):
        entry_id = int(row["entry_id"])
        src = source.get(entry_id)
        if src is None:
            continue
        label = label_map.get(entry_id, {})
        state = state_map.get(entry_id, {})
        status = label.get("outcome_status")
        normal = status == "normal_completed"
        records.append(
            {
                "entry_id": entry_id,
                "race_id": row["race_id"],
                "event_date": row["event_date"],
                "horse_id": row["horse_id"],
                "horse_number": row["horse_number"],
                "field_size": row["field_size"],
                "global_elo_pre": state.get("global_elo_pre"),
                "distance_elo_pre": state.get("distance_elo_pre"),
                "jockey_name": src.get("jockey_name"),
                "jockey_id": src.get("jockey_id"),
                "burden_kg": src.get("burden_kg"),
                "body_weight_kg": src.get("body_weight_kg"),
                "early_rank": src.get("early_rank"),
                "late_rank": src.get("g1_rank"),
                "g1f_seconds": src.get("g1f_seconds")
                if normal and label.get("time_observed")
                else None,
                "finish_position": label.get("finish_position") if normal else None,
                "finish_time_ms": label.get("finish_time_ms")
                if normal and label.get("time_observed")
                else None,
                "outcome_status": status,
                "weather": src.get("weather"),
                "track_moisture_percent": src.get("track_moisture_percent"),
            }
        )
    races = defaultdict(list)
    for row in records:
        races[row["race_id"]].append(row)
    for rows in races.values():
        times = [
            r["finish_time_ms"]
            for r in rows
            if r["finish_time_ms"] is not None and r["finish_time_ms"] > 0
        ]
        median = float(np.median(times)) if len(times) >= 2 else None
        valid_g1 = [
            float(r["g1f_seconds"])
            for r in rows
            if r["g1f_seconds"] is not None
            and r["finish_time_ms"] is not None
            and 0 < float(r["g1f_seconds"]) < r["finish_time_ms"] / 1000
        ]
        for row in rows:
            t = row["finish_time_ms"]
            row["time_minus_race_median_ms"] = (
                t - median if t is not None and median is not None else None
            )
            rivals = [
                r["global_elo_pre"]
                for r in rows
                if r["entry_id"] != row["entry_id"] and r["global_elo_pre"] is not None
            ]
            row["rival_elo_mean"] = float(np.mean(rivals)) if rivals else None
            g1 = row["g1f_seconds"]
            valid = (
                g1 is not None and t is not None and 0 < float(g1) < t / 1000 and len(valid_g1) >= 2
            )
            row["closing_speed_quality"] = (
                (
                    sum(v > float(g1) for v in valid_g1)
                    + 0.5 * (sum(v == float(g1) for v in valid_g1) - 1)
                )
                / (len(valid_g1) - 1)
                if valid
                else None
            )
    return records


def main() -> None:
    if (OUT / "features.parquet").exists():
        raise RuntimeError("Refuse to overwrite an existing context feature artifact")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "feature_definitions.json").write_text(
        json.dumps(
            {
                "version": "jeju_context_form_v1",
                "cutoff_days": CUTOFF_DAYS,
                "features": FEATURES,
                "context_features": CONTEXT_FEATURES,
                "form_features": FORM_FEATURES,
                "definitions": FEATURE_DEFINITIONS,
                "policy": (
                    "only sealed r2 starters, history at event_date-2d or earlier; "
                    "current outcome/weather/bodyweight excluded"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    entries = pl.read_parquet(DATA / "entries.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    labels = pl.read_parquet(DATA / "labels.parquet")
    states = pl.read_parquet(DATA / "horse_states.parquet")
    source = _source_rows(connection)
    history = _history_rows(entries, labels, source, states)
    h3 = pl.read_parquet(H3 / "features.parquet").select(
        "entry_id", "declared_burden_kg", "declared_horse_number", "card_observed"
    )
    lineage = pl.read_parquet(H3 / "lineage.parquet").select(
        "entry_id", "source_document_id", "source_file_date", "jockey_name"
    )
    h3_map = {int(row["entry_id"]): row for row in h3.iter_rows(named=True)}
    lineage_map = {int(row["entry_id"]): row for row in lineage.iter_rows(named=True)}
    state_map = {
        int(row["entry_id"]): row
        for row in states.select("entry_id", "global_elo_pre", "distance_elo_pre").iter_rows(
            named=True
        )
    }
    targets = []
    for row in entries.iter_rows(named=True):
        entry_id = int(row["entry_id"])
        declared = h3_map.get(entry_id, {})
        line = lineage_map.get(entry_id, {})
        state = state_map.get(entry_id, {})
        targets.append(
            {
                "entry_id": entry_id,
                "race_id": row["race_id"],
                "event_date": row["event_date"],
                "horse_id": row["horse_id"],
                "horse_number": declared.get("declared_horse_number"),
                "field_size": row["field_size"],
                "global_elo_pre": state.get("global_elo_pre"),
                "distance_elo_pre": state.get("distance_elo_pre"),
                "declared_burden_kg": declared.get("declared_burden_kg"),
                "jockey_name": line.get("jockey_name"),
                "card_observed": declared.get("card_observed"),
            }
        )
    output = pl.DataFrame(build_features(targets, history), infer_schema_length=None)
    output = output.select("entry_id", *FEATURES)
    assert len(output) == 79731 and output["entry_id"].n_unique() == len(output)
    assert entries.filter(pl.col("event_date").dt.year() == 2025).height == 6953
    output.write_parquet(OUT / "features.parquet")
    dev = output.join(entries.select("entry_id", "event_date"), on="entry_id").filter(
        pl.col("event_date").dt.year() == 2025
    )
    coverage = {
        name: {
            "finite_2025": int(dev.select(pl.col(name).is_finite().fill_null(False).sum()).item()),
            "unique_finite_2025": int(dev.filter(pl.col(name).is_finite())[name].n_unique()),
        }
        for name in FEATURES
    }
    (OUT / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
    history_by_horse: defaultdict[str, list[dict]] = defaultdict(list)
    for row in history:
        history_by_horse[str(row["horse_id"])].append(row)
    lineage_rows = []
    for target in targets:
        cutoff = target["event_date"] - timedelta(days=CUTOFF_DAYS)
        prior = [
            row for row in history_by_horse[str(target["horse_id"])] if row["event_date"] <= cutoff
        ]
        lineage_rows.append(
            {
                "entry_id": target["entry_id"],
                "race_id": target["race_id"],
                "event_date": target["event_date"],
                "cutoff_date": cutoff,
                "max_history_date": max((row["event_date"] for row in prior), default=None),
                "history_starts": len(prior),
                "history_normal_outcomes": sum(row["finish_position"] is not None for row in prior),
                "source_policy": (
                    "sealed r2 actual starters; no same-day or target outcomes/weather/bodyweight"
                ),
            }
        )
    pl.DataFrame(lineage_rows, infer_schema_length=None).write_parquet(OUT / "lineage.parquet")
    report = {
        "dataset_manifest_sha256": _sha(DATA / "manifest.json"),
        "h3_manifest_sha256": _sha(H3 / "manifest.json"),
        "database": str(DB),
        "database_read_only": True,
        "entries": len(output),
        "races": entries["race_id"].n_unique(),
        "features": FEATURES,
        "context_features": CONTEXT_FEATURES,
        "form_features": FORM_FEATURES,
        "cutoff_days": CUTOFF_DAYS,
        "model_fit_count": 0,
        "outcome_weather_bodyweight_policy": (
            "target values excluded; only prior rows at least two days old used"
        ),
        "status_counts": dict(Counter(row.get("outcome_status") for row in history)),
    }
    (OUT / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    source_info = {
        "database": str(DB),
        "database_sha256": _sha(DB),
        "dataset_manifest": _sha(DATA / "manifest.json"),
        "h3_manifest": _sha(H3 / "manifest.json"),
        "query_fields": [
            "wgBudam",
            "wgHr",
            "jkName",
            "jkNo",
            "sjS1fOrd",
            "sjG1fOrd",
            "sj_4cOrd",
            "jeS1fTime",
            "jeG1fTime",
            "jeG3fTime",
            "event.weather",
            "event.track_moisture_percent",
            "track (explicit percent fallback only for historical rows)",
        ],
    }
    (OUT / "source_documents.json").write_text(
        json.dumps(source_info, ensure_ascii=False, indent=2) + "\n"
    )
    (OUT / "reproduce").mkdir(exist_ok=True)
    for path in [
        Path(__file__),
        ROOT / "src/horse_racing/analysis/jeju_context_features.py",
        ROOT / "tests/test_jeju_context_features.py",
    ]:
        shutil.copy2(path, OUT / "reproduce" / path.name)
    manifest = {}
    for path in sorted(OUT.rglob("*")):
        if path.name != "manifest.json" and path.is_file():
            manifest[str(path.relative_to(OUT))] = _sha(path)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

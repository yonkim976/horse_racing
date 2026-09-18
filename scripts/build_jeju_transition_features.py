"""Expand historical context and declared transitions without current-result features."""

import json
import re
import shutil
import sqlite3

import polars as pl
from polars.testing import assert_frame_equal

from horse_racing.analysis.jeju_context_features import FEATURES as CONTEXT_FEATURES
from horse_racing.analysis.jeju_context_features import build_features as context_features
from horse_racing.analysis.jeju_context_features import parse_body_weight, parse_track_moisture
from horse_racing.analysis.jeju_transition_features import FEATURES, build_features
from scripts.build_jeju_context_features import _date, _history_rows
from scripts.freeze_jeju_transition_protocol import CTX, DATA, DB, FEAT, H3, OUT, ROOT, sha


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
        WHERE v.event_type = 'race' AND v.event_date <= '20260912'
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


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    assert sha(DB) == protocol["database_sha256"]
    FEAT.mkdir(exist_ok=False)
    entries = pl.read_parquet(DATA / "entries.parquet")
    labels = pl.read_parquet(DATA / "labels.parquet")
    states = pl.read_parquet(DATA / "horse_states.parquet")
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    source = _source_rows(c)
    history = _history_rows(entries, labels, source, states)
    assert len(history) == len(entries) == 84583
    cards = {
        r["entry_id"]: r for r in pl.read_parquet(H3 / "features.parquet").iter_rows(named=True)
    }
    lines = {
        r["entry_id"]: r for r in pl.read_parquet(H3 / "lineage.parquet").iter_rows(named=True)
    }
    sm = {
        r["entry_id"]: r
        for r in states.select("entry_id", "global_elo_pre", "distance_elo_pre").iter_rows(
            named=True
        )
    }
    em = {r["entry_id"]: r for r in entries.iter_rows(named=True)}
    targets = []
    for e in entries.iter_rows(named=True):
        eid = e["entry_id"]
        card = cards[eid]
        line = lines[eid]
        targets.append(
            dict(
                entry_id=eid,
                race_id=e["race_id"],
                horse_id=e["horse_id"],
                event_date=e["event_date"],
                field_size=e["field_size"],
                horse_number=card["declared_horse_number"],
                global_elo_pre=sm[eid]["global_elo_pre"],
                distance_elo_pre=sm[eid]["distance_elo_pre"],
                declared_burden_kg=card["declared_burden_kg"],
                jockey_name=line["jockey_name"],
                card_observed=card["card_observed"],
            )
        )
    context = pl.DataFrame(context_features(targets, history), infer_schema_length=None).select(
        "entry_id", *CONTEXT_FEATURES
    )
    old = pl.read_parquet(CTX / "features.parquet").sort("entry_id")
    assert_frame_equal(
        old,
        context.join(old.select("entry_id"), on="entry_id", how="semi").sort("entry_id"),
        check_exact=True,
    )
    context.write_parquet(FEAT / "context_features.parquet")
    cm = {r["entry_id"]: r for r in context.iter_rows(named=True)}
    grades = {
        r["entry_id"]: r["grade"]
        for r in c.execute(
            "select e.id entry_id,v.grade from entry e join event v on v.id=e.event_id "
            "where v.event_type='race' and v.event_date<='20260912'"
        )
    }
    past = []
    for row in history:
        eid = row["entry_id"]
        g = re.fullmatch(r"제([1-6])등급", str(grades.get(eid)))
        past.append(
            {
                k: row[k]
                for k in [
                    "entry_id",
                    "event_date",
                    "horse_id",
                    "burden_kg",
                    "finish_position",
                    "field_size",
                    "outcome_status",
                ]
            }
            | dict(
                grade=int(g.group(1)) if g else None,
                distance_m=em[eid]["distance_m"],
                rival_early_pressure_count=cm[eid]["rival_early_pressure_count"],
            )
        )
    newtargets = [
        dict(
            entry_id=e["entry_id"],
            horse_id=e["horse_id"],
            event_date=e["event_date"],
            distance_m=e["distance_m"],
            declared_grade_number=cards[e["entry_id"]]["declared_grade_number"],
            declared_burden_kg=cards[e["entry_id"]]["declared_burden_kg"],
            rival_early_pressure_count=cm[e["entry_id"]]["rival_early_pressure_count"],
        )
        for e in entries.iter_rows(named=True)
    ]
    rows, lineage = build_features(newtargets, past)
    tf = pl.DataFrame(rows, infer_schema_length=None)
    lin = pl.DataFrame(lineage, infer_schema_length=None)
    assert lin.filter(pl.col("previous_date") > pl.col("cutoff_date")).is_empty()
    tf.write_parquet(FEAT / "features.parquet")
    lin.write_parquet(FEAT / "lineage.parquet")
    pl.DataFrame(past, infer_schema_length=None).write_parquet(FEAT / "transition_history.parquet")
    pl.DataFrame(newtargets, infer_schema_length=None).write_parquet(
        FEAT / "transition_targets.parquet"
    )
    pl.DataFrame(history, infer_schema_length=None).write_parquet(FEAT / "context_history.parquet")
    pl.DataFrame(targets, infer_schema_length=None).write_parquet(FEAT / "context_targets.parquet")
    # Record which historical results a given target may consume, without attaching its outcome.
    result = dict(
        rows=len(tf),
        features=FEATURES,
        old_context_rows_exactly_reproduced=len(old),
        evaluation_features=4852,
        protocol_sha256=sha(OUT / "protocol.json"),
        database_sha256=sha(DB),
        sequential_history_policy="Historical results through targetT-2; no fit on2026.",
        source_parents=protocol["parents"],
    )
    (FEAT / "build_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (FEAT / "reproduce").mkdir()
    for path in [
        ROOT / "scripts/build_jeju_transition_features.py",
        ROOT / "src/horse_racing/analysis/jeju_transition_features.py",
        ROOT / "tests/test_jeju_transition_features.py",
    ]:
        shutil.copy2(path, FEAT / "reproduce" / path.name)
    manifest = {str(p.relative_to(FEAT)): sha(p) for p in sorted(FEAT.rglob("*")) if p.is_file()}
    (FEAT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    c.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

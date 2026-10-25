"""Read-only source/availability audit for the proposed Jeju style-history fields.

The audit reuses the locked F1 target population and its exact last-five same-
distance source slots. It reads the existing starter snapshot and queries only
quality-selected API4 order / API303 group component views for the referenced
source races. It does not build model features, fit, score, or publish.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
F1_FEATURES = F1_DIR / "outputs/features.parquet"
F1_LINEAGE = F1_DIR / "outputs/historical_lineage.parquet"
SOURCE_SNAPSHOT = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
BASE_LOCK = F1_DIR / "outputs/prepared_lock.json"
TIME_SOURCE_RECEIPT = ROOT / "jeju/research/20261009_section_ablation_review_v1/independent_outputs/independent_source_availability_receipt.json"
EXISTING_GROUP_RUNNERS = ROOT / "jeju/research/20261008_passing_group_running_style_v1/run01/runner_position_intervals.csv"
EXISTING_GROUP_POINTS = ROOT / "jeju/research/20261008_passing_group_running_style_v1/run01/race_point_audit.csv"
OUT_JSON = HERE / "source_audit.json"
OUT_DISTANCE = HERE / "support_by_distance_year.csv"
OUT_POINT = HERE / "point_support_by_distance.csv"
OUT_GROUP = HERE / "api303_group_support_by_distance.csv"
OUT_EXAMPLES = HERE / "cross_source_interval_examples.csv"
OUT_ROSTER = HERE / "full_roster_reconciliation_by_race.csv"
OUT_RACE_POINT = HERE / "race_point_quality_support.csv"
OUT_TIME = HERE / "point_time_chronology_by_distance.csv"
OUT_SOURCE_CACHE = HERE / "api4_full_started_point_quality_cache.parquet"
OUT_SLOT_CACHE = HERE / "actual_slot_point_eligibility.parquet"

POINT_FIELDS = {
    "S1F": "sjS1fOrd",
    "4C": "sj_4cOrd",
    "G1F": "sjG1fOrd",
}
ORDER_STATUS_OK = {"api_positive_unreviewed", "website_corrected"}
ORDER_STATUS_ALLOWED = ORDER_STATUS_OK | {
    "api_unavailable_or_nonpositive_or_sentinel",
    "website_review_not_applied",
    "api_source_changed_since_review",
    "unresolved_official_internal_conflict",
    "internal_conflict_review_not_applied",
    "api_source_changed_since_conflict_review",
}
GROUP_STATUS_ALLOWED = {
    "api_group_unavailable",
    "api_group_unreviewed",
    "unresolved_official_internal_conflict",
    "internal_conflict_review_not_applied",
    "api_source_changed_since_conflict_review",
}
GROUP_POINTS = {"S1F": "S1F", "4C": "4C", "G1F": "G1F"}
GROUP_TO_ORDER_POINT = {"S1F": "S1F", "4C": "4C", "G1F": "G1F"}
FIELD_MAP = {"S1F": "s1f_order", "4C": "c4_order", "G1F": "g1f_order"}
QUALITY_VIEWS = [
    "jeju_race_section_order_values",
    "jeju_race_section_order_quality_values",
    "jeju_race_section_order_quality",
    "jeju_race_section_group_quality_values",
    "jeju_race_section_group_quality",
    "jeju_race_section_time_values",
    "jeju_race_postrace_sections_2026",
    "jeju_race_postrace_sections_reviewed_2026",
    "jeju_race_postrace_sections_quality_2026",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def id_set_sha256(values: set[int]) -> str:
    payload = ",".join(str(value) for value in sorted(values)).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def write_new_json(path: Path, value: object) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_new_csv(path: Path, frame: pd.DataFrame) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    frame.to_csv(path, index=False, encoding="utf-8")


def write_new_parquet(path: Path, frame: pd.DataFrame) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    frame.to_parquet(path, index=False)


def parse_group_interval(value: object, roster: set[int]) -> dict[int, tuple[int, int]] | None:
    """Conservative roster-checked parser; never orders members within a group."""
    if value is None or pd.isna(value):
        return None
    text = str(value).replace(" ", "")
    token = r"(?:\(\^?\d+(?:,\^?\d+)*\)|\^?\d+)"
    if not re.fullmatch(token + r"(?:[,=≡\-]+" + token + r")*", text):
        return None
    groups = [list(map(int, re.findall(r"\d+", match.group()))) for match in re.finditer(token, text)]
    flat = [number for group in groups for number in group]
    if not flat or len(flat) != len(set(flat)) or set(flat) != roster:
        return None
    bounds: dict[int, tuple[int, int]] = {}
    rank_lo = 1
    flat: list[int] = []
    for group in groups:
        rank_hi = rank_lo + len(group) - 1
        for horse_number in group:
            if horse_number in bounds:
                return None
            bounds[horse_number] = (rank_lo, rank_hi)
            flat.append(horse_number)
        rank_lo = rank_hi + 1
    return bounds


def read_views(connection: sqlite3.Connection) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for name in QUALITY_VIEWS:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)
        ).fetchone()
        assert row and row[0], f"missing view DDL {name}"
        definitions[name] = str(row[0])
    q = definitions["jeju_race_postrace_sections_quality_2026"]
    assert "jeju_race_section_order_quality o ON o.api_record_id=a.api_record_id" in q
    assert "jeju_race_section_group_quality g ON g.api_record_id=a.api303_api_record_id" in q
    assert "FROM jeju_race_section_order_quality_values" in definitions["jeju_race_section_order_quality"]
    assert "FROM jeju_race_section_group_quality_values" in definitions["jeju_race_section_group_quality"]
    assert "quality_order_value" in definitions["jeju_race_section_order_quality"]
    assert "quality_order_status" in definitions["jeju_race_section_order_quality"]
    assert "group_value" in definitions["jeju_race_section_group_quality"]
    assert "group_status" in definitions["jeju_race_section_group_quality"]
    assert "website_review_not_applied" in definitions["jeju_race_section_order_values"]
    assert "FROM jeju_race_section_order_values" in definitions["jeju_race_section_order_quality_values"]
    assert "api_source_changed_since_review" in definitions["jeju_race_section_order_values"]
    assert "api_source_changed_since_conflict_review" in definitions["jeju_race_section_order_quality_values"]
    assert "section_internal_conflict_reviews" in definitions["jeju_race_section_order_quality_values"]
    assert "internal_conflict_review_not_applied" in definitions["jeju_race_section_order_quality_values"]
    assert "api_group_unavailable" in definitions["jeju_race_section_group_quality_values"]
    assert "section_internal_conflict_reviews" in definitions["jeju_race_section_group_quality_values"]
    assert "internal_conflict_review_not_applied" in definitions["jeju_race_section_group_quality_values"]
    return definitions


def query_order_values(connection: sqlite3.Connection, api_ids: list[int]) -> pd.DataFrame:
    frames = []
    fields = list(POINT_FIELDS.values())
    field_marks = ",".join("?" for _ in fields)
    for offset in range(0, len(api_ids), 4000):
        batch = api_ids[offset:offset + 4000]
        id_marks = ",".join("?" for _ in batch)
        frames.append(pd.read_sql_query(
            "SELECT api_record_id,race_date,meet_code,race_number,horse_number,horse_id,"
            "field_name,api_order_json_type,quality_order_value,quality_order_status "
            "FROM jeju_race_section_order_quality_values "
            f"WHERE api_record_id IN ({id_marks}) AND field_name IN ({field_marks})",
            connection, params=batch + fields,
        ))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def query_group_values(connection: sqlite3.Connection, race_keys: list[tuple[str, int, int]]) -> pd.DataFrame:
    frames = []
    points = list(GROUP_POINTS.values())
    point_marks = ",".join("?" for _ in points)
    for offset in range(0, len(race_keys), 250):
        batch = race_keys[offset:offset + 250]
        race_marks = ",".join("(?,?,?)" for _ in batch)
        params = [value for race in batch for value in race] + points
        frames.append(pd.read_sql_query(
            "SELECT api_record_id,race_date,meet_code,race_number,point,field_name,group_value,group_status "
            "FROM jeju_race_section_group_quality_values "
            f"WHERE (race_date,meet_code,race_number) IN (VALUES {race_marks}) AND point IN ({point_marks})",
            connection, params=params,
        ))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def query_time_values(connection: sqlite3.Connection, api_ids: list[int]) -> pd.DataFrame:
    frames = []
    fields = ["jeS1fTime", "je_4cTime", "jeG1fTime"]
    field_marks = ",".join("?" for _ in fields)
    for offset in range(0, len(api_ids), 4000):
        batch = api_ids[offset:offset + 4000]
        id_marks = ",".join("?" for _ in batch)
        frames.append(pd.read_sql_query(
            "SELECT api_record_id,race_date,meet_code,race_number,horse_number,horse_id,"
            "field_name,time_seconds,time_status FROM jeju_race_section_time_values "
            f"WHERE api_record_id IN ({id_marks}) AND field_name IN ({field_marks})",
            connection, params=batch + fields,
        ))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def order_is_integer_in_range(value: object, n: int) -> bool:
    if value is None or pd.isna(value) or n < 2:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(number) and number.is_integer() and 1 <= int(number) <= n)


def normalize_id_list(value: object) -> list[int]:
    """Read a Parquet list without relying on numpy's ambiguous truth value."""
    if value is None or value is pd.NA:
        return []
    if isinstance(value, float) and pd.isna(value):
        return []
    if isinstance(value, np.ndarray):
        return [int(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [int(item) for item in value]
    raise TypeError(f"unexpected last5_same_source_ids type: {type(value).__name__}")


def query_full_race_rows(connection: sqlite3.Connection, race_keys: list[tuple[str, int, int]]) -> pd.DataFrame:
    frames = []
    for offset in range(0, len(race_keys), 250):
        batch = race_keys[offset:offset + 250]
        marks = ",".join("(?,?,?)" for _ in batch)
        params = [value for race in batch for value in race]
        frames.append(pd.read_sql_query(
            "SELECT api_record_id,race_date,meet_code,race_number,horse_number,horse_id,"
            "race_distance_m,finish_position,finish_time_seconds,breed_assessment FROM race_result_rows "
            f"WHERE (race_date,meet_code,race_number) IN (VALUES {marks})",
            connection, params=params,
        ))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def inherited_started(finish_position: object) -> bool:
    """Use the inherited source rule exactly; don't reinterpret other codes."""
    if finish_position is None or pd.isna(finish_position):
        return False
    try:
        value = int(finish_position)
    except (TypeError, ValueError):
        return False
    return (1 <= value <= 89) or value in {91, 92}


def main() -> None:
    features = pd.read_parquet(F1_FEATURES)
    lineage_all = pd.read_parquet(F1_LINEAGE)
    snapshot = pd.read_parquet(SOURCE_SNAPSHOT)
    lineage = lineage_all.loc[lineage_all.history_kind.eq("last5_same_distance_start")].copy()
    assert len(features) == 52155 and features.api_record_id.is_unique
    assert len(lineage) == 178459
    assert lineage.source_api_record_id.nunique() == 50491
    assert not snapshot.api_record_id.duplicated().any()
    assert len(snapshot) == 92513

    # Recheck the already fixed target lineage; don't regenerate its window.
    slot_ids_by_target = (
        lineage.sort_values(["target_api_record_id", "slot_oldest_to_newest"])
        .groupby("target_api_record_id", sort=False).source_api_record_id
        .apply(lambda series: [int(value) for value in series])
    )
    assert set(slot_ids_by_target.index).issubset(set(features.api_record_id))
    for row in features[["api_record_id", "last5_same_source_ids"]].itertuples(index=False):
        ids = normalize_id_list(row.last5_same_source_ids)
        assert [int(value) for value in ids] == slot_ids_by_target.get(int(row.api_record_id), [])

    source_index = snapshot.set_index("api_record_id", drop=False)
    source_rows_for_slots = source_index.loc[lineage.source_api_record_id.astype("int64")].reset_index(drop=True)
    assert source_rows_for_slots.api_record_id.astype("int64").equals(lineage.source_api_record_id.astype("int64").reset_index(drop=True))
    assert source_rows_for_slots.horse_id.astype(str).reset_index(drop=True).equals(lineage.source_horse_id.astype(str).reset_index(drop=True))
    assert source_rows_for_slots.started.astype(bool).all() and lineage.source_started.astype(bool).all()
    assert source_rows_for_slots.race_id.astype(str).reset_index(drop=True).equals(lineage.source_race_id.astype(str).reset_index(drop=True))
    assert source_rows_for_slots.race_date.astype(str).reset_index(drop=True).equals(lineage.source_race_date.astype(str).reset_index(drop=True))
    assert source_rows_for_slots.race_distance_m.astype("int64").reset_index(drop=True).equals(lineage.source_distance_m.astype("int64").reset_index(drop=True))
    assert (source_rows_for_slots.race_distance_m.astype("int64").to_numpy() == lineage.target_distance_m.astype("int64").to_numpy()).all()

    target_meta = features.set_index("api_record_id")[["race_date", "year", "distance_m", "history_cutoff"]]
    cutoff = lineage.target_api_record_id.map(target_meta.history_cutoff)
    assert (lineage.source_race_date.astype(str).to_numpy() <= cutoff.astype(str).to_numpy()).all()
    assert (lineage.starter_n.astype("int64").to_numpy() == source_rows_for_slots.race_id.map(
        snapshot.loc[snapshot.started.astype(bool)].groupby("race_id").size()
    ).astype("int64").to_numpy()).all()

    db_uri = DB.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(db_uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    ddl = read_views(connection)

    referenced_races = sorted(set(lineage.source_race_id.astype(str)))
    snapshot_race_rows = snapshot.loc[snapshot.race_id.astype(str).isin(referenced_races)].copy()
    snapshot_race_rows["started"] = snapshot_race_rows.started.astype(bool)
    snapshot_starters = snapshot_race_rows.loc[snapshot_race_rows.started].copy()
    snapshot_starters["source_snapshot_valid_time"] = snapshot_starters.valid_time.astype(bool)
    assert snapshot_starters.api_record_id.is_unique
    assert snapshot_starters.groupby(["race_id", "horse_id"]).size().max() == 1
    assert snapshot_starters.groupby(["race_id", "horse_number"]).size().max() == 1

    race_keys_frame = snapshot_race_rows[["race_date", "meet_code", "race_number"]].drop_duplicates()
    race_keys = sorted((str(r.race_date), int(r.meet_code), int(r.race_number)) for r in race_keys_frame.itertuples(index=False))
    full_race_rows = query_full_race_rows(connection, race_keys)
    assert full_race_rows.api_record_id.is_unique
    full_race_rows["race_id"] = full_race_rows.race_date.astype(str) + "_" + full_race_rows.meet_code.astype(str) + "_" + full_race_rows.race_number.astype(str)
    full_race_rows["started"] = full_race_rows.finish_position.map(inherited_started)
    starters = full_race_rows.loc[full_race_rows.started].copy()
    starters["year"] = pd.to_datetime(starters.race_date).dt.year
    assert starters.api_record_id.notna().all()
    assert starters.horse_id.notna().all()
    assert starters.horse_number.notna().all()
    assert not starters.duplicated(["race_id", "api_record_id"]).any()
    assert not starters.duplicated(["race_id", "horse_id"]).any()
    assert not starters.duplicated(["race_id", "horse_number"]).any()
    snapshot_to_full = snapshot_race_rows[[
        "api_record_id", "race_date", "meet_code", "race_number", "horse_number", "horse_id",
        "race_distance_m", "finish_position",
    ]].merge(
        full_race_rows[[
            "api_record_id", "race_date", "meet_code", "race_number", "horse_number", "horse_id",
            "race_distance_m", "finish_position",
        ]], on="api_record_id", how="left", validate="one_to_one", suffixes=("_snapshot", "_full"), indicator=True,
    )
    assert snapshot_to_full._merge.eq("both").all()
    for column in ["race_date", "meet_code", "race_number", "horse_number", "horse_id", "race_distance_m", "finish_position"]:
        left = snapshot_to_full[f"{column}_snapshot"]
        right = snapshot_to_full[f"{column}_full"]
        if column in {"meet_code", "race_number", "horse_number", "race_distance_m", "finish_position"}:
            assert np.array_equal(pd.to_numeric(left, errors="coerce").to_numpy(),
                                  pd.to_numeric(right, errors="coerce").to_numpy(), equal_nan=True)
        else:
            assert left.astype("string").equals(right.astype("string"))
    assert starters.api_record_id.is_unique
    assert starters.groupby(["race_id", "horse_id"]).size().max() == 1
    assert starters.groupby(["race_id", "horse_number"]).size().max() == 1
    started_n_by_race = starters.groupby("race_id").size().to_dict()
    assert all(int(value) >= 1 for value in started_n_by_race.values())

    candidate_ids_by_race = {
        str(race_id): set(group.api_record_id.astype("int64"))
        for race_id, group in snapshot_starters.groupby(snapshot_starters.race_id.astype(str), sort=False)
    }
    full_ids_by_race = {
        str(race_id): set(group.api_record_id.astype("int64"))
        for race_id, group in starters.groupby("race_id", sort=False)
    }
    roster_audit = []
    for race_id in sorted(set(candidate_ids_by_race) | set(full_ids_by_race)):
        candidate_ids = candidate_ids_by_race.get(race_id, set())
        full_ids = full_ids_by_race.get(race_id, set())
        candidate_n = len(candidate_ids)
        full_n = len(full_ids)
        roster_audit.append({
            "race_id": race_id,
            "snapshot_started_n": candidate_n,
            "full_race_result_started_n": full_n,
            "full_minus_snapshot_started_n": full_n - candidate_n,
            "snapshot_started_ids_equal_full_roster": candidate_ids == full_ids,
            "full_started_ids_missing_from_snapshot_n": len(full_ids - candidate_ids),
            "snapshot_started_ids_absent_from_full_roster_n": len(candidate_ids - full_ids),
            "snapshot_started_ids_sha256": id_set_sha256(candidate_ids),
            "full_started_ids_sha256": id_set_sha256(full_ids),
            "full_started_null_api_id_n": int(starters.loc[starters.race_id.eq(race_id), "api_record_id"].isna().sum()),
            "full_started_null_horse_id_n": int(starters.loc[starters.race_id.eq(race_id), "horse_id"].isna().sum()),
            "full_started_null_horse_number_n": int(starters.loc[starters.race_id.eq(race_id), "horse_number"].isna().sum()),
            "full_started_breed_assessment_counts": {
                str(k): int(v) for k, v in starters.loc[starters.race_id.eq(race_id), "breed_assessment"].value_counts(dropna=False).items()
            },
        })
    roster_audit_df = pd.DataFrame(roster_audit)
    assert len(roster_audit_df) == len(race_keys)

    # Reuse only the three needed API4 order fields for all started runners in
    # exact referenced source races. IDs and field names remain bound values.
    order_rows = query_order_values(connection, starters.api_record_id.astype("int64").tolist())
    assert not order_rows.duplicated(["api_record_id", "field_name"]).any()
    order_identity = order_rows.merge(
        starters[["api_record_id", "race_date", "meet_code", "race_number", "horse_number", "horse_id"]],
        on="api_record_id", how="left", validate="many_to_one", suffixes=("_quality", "_full"), indicator=True,
    )
    assert order_identity._merge.eq("both").all()
    for column in ["race_date", "meet_code", "race_number", "horse_number", "horse_id"]:
        left, right = order_identity[f"{column}_quality"], order_identity[f"{column}_full"]
        if column in {"meet_code", "race_number", "horse_number"}:
            assert np.array_equal(pd.to_numeric(left, errors="coerce").to_numpy(),
                                  pd.to_numeric(right, errors="coerce").to_numpy(), equal_nan=True)
        else:
            assert left.astype("string").equals(right.astype("string"))
    # Missing constituent rows for full-roster starters are explicit support
    # failures; never shrink the denominator to the candidate snapshot.
    unknown_order = sorted(set(order_rows.quality_order_status.dropna().astype(str)) - ORDER_STATUS_ALLOWED)
    assert not unknown_order, unknown_order
    order_counts_by_field = order_rows.groupby("field_name").size().to_dict()
    assert set(order_counts_by_field).issubset(set(POINT_FIELDS.values()))

    order_rows["point"] = order_rows.field_name.map({value: key for key, value in POINT_FIELDS.items()})
    order_rows["race_id"] = (
        order_rows.race_date.astype(str) + "_" + order_rows.meet_code.astype(str) + "_" + order_rows.race_number.astype(str)
    )
    group_rows = query_group_values(connection, race_keys)
    assert not group_rows.duplicated(["race_date", "meet_code", "race_number", "point"]).any()
    unknown_group = sorted(set(group_rows.group_status.dropna().astype(str)) - GROUP_STATUS_ALLOWED)
    assert not unknown_group, unknown_group
    assert set(group_rows.point.astype(str)).issubset(set(GROUP_POINTS.values()))
    expected_group_keys = pd.MultiIndex.from_product(
        [race_keys, list(GROUP_POINTS.values())], names=["race_key", "point"]
    )
    expected_group = pd.DataFrame({
        "race_date": [key[0] for key, _point in expected_group_keys],
        "meet_code": [key[1] for key, _point in expected_group_keys],
        "race_number": [key[2] for key, _point in expected_group_keys],
        "point": [_point for _key, _point in expected_group_keys],
    })
    group_rows = expected_group.merge(
        group_rows, on=["race_date", "meet_code", "race_number", "point"], how="left", validate="one_to_one"
    )
    group_rows["group_status"] = group_rows.group_status.fillna("api_group_row_missing")
    group_rows["race_id"] = (
        group_rows.race_date.astype(str) + "_" + group_rows.meet_code.astype(str) + "_" + group_rows.race_number.astype(str)
    )
    race_started_numbers = {
        race_id: set(group.horse_number.dropna().astype(int))
        for race_id, group in starters.groupby("race_id", sort=False)
    }
    group_rows["bounds"] = [
        parse_group_interval(value, race_started_numbers.get(race_id, set()))
        if status == "api_group_unreviewed" else None
        for value, status, race_id in zip(group_rows.group_value.tolist(), group_rows.group_status.tolist(), group_rows.race_id.tolist())
    ]
    group_rows["parsed_interval_ok"] = group_rows.bounds.map(lambda value: value is not None)
    group_status_lookup = group_rows.set_index(["race_id", "point"]).group_status.to_dict()
    group_interval_lookup = group_rows.set_index(["race_id", "point"]).parsed_interval_ok.to_dict()
    source_time_rows = query_time_values(connection, sorted(lineage.source_api_record_id.astype("int64").unique().tolist()))
    assert not source_time_rows.duplicated(["api_record_id", "field_name"]).any()
    assert set(source_time_rows.field_name.astype(str)).issubset({"jeS1fTime", "je_4cTime", "jeG1fTime"})
    time_identity = source_time_rows.merge(
        starters[["api_record_id", "race_date", "meet_code", "race_number", "horse_number", "horse_id"]],
        on="api_record_id", how="left", validate="many_to_one", suffixes=("_quality", "_full"), indicator=True,
    )
    assert time_identity._merge.eq("both").all()
    for column in ["race_date", "meet_code", "race_number", "horse_number", "horse_id"]:
        left, right = time_identity[f"{column}_quality"], time_identity[f"{column}_full"]
        if column in {"meet_code", "race_number", "horse_number"}:
            assert np.array_equal(pd.to_numeric(left, errors="coerce").to_numpy(),
                                  pd.to_numeric(right, errors="coerce").to_numpy(), equal_nan=True)
        else:
            assert left.astype("string").equals(right.astype("string"))
    snapshot_starters["race_id"] = snapshot_starters.race_id.astype(str)
    snapshot_starters["year"] = pd.to_datetime(snapshot_starters.race_date).dt.year
    point_grid = pd.DataFrame({"field_name": list(POINT_FIELDS.values())})
    point_grid["point"] = point_grid.field_name.map({value: key for key, value in POINT_FIELDS.items()})
    starter_order = starters[["api_record_id", "race_id", "race_date", "race_distance_m", "horse_id", "horse_number"]].assign(_join=1).merge(
        point_grid.assign(_join=1), on="_join", validate="many_to_many", how="inner"
    ).drop(columns="_join").merge(
        order_rows[["api_record_id", "field_name", "api_order_json_type", "quality_order_value", "quality_order_status"]],
        on=["api_record_id", "field_name"], validate="one_to_one", how="left",
    )
    starter_order = starter_order.merge(
        snapshot_starters[["api_record_id", "source_snapshot_valid_time"]], on="api_record_id", how="left", validate="many_to_one"
    )
    starter_order["started_n"] = starter_order.race_id.map(started_n_by_race).astype("int64")
    starter_order["local_rank_ok"] = starter_order.apply(
        lambda row: isinstance(row.quality_order_status, str) and row.quality_order_status in ORDER_STATUS_OK
        and order_is_integer_in_range(row.quality_order_value, int(row.started_n)),
        axis=1,
    )

    # A point is eligible only if the entire inherited started roster has a
    # unique quality-selected integer permutation 1..N at that point.
    permutation_rows = []
    for race_id in sorted(started_n_by_race):
      for point in POINT_FIELDS:
        group = starter_order.loc[starter_order.race_id.eq(race_id) & starter_order.point.eq(point)].copy()
        n = int(started_n_by_race[race_id])
        values = [int(value) for value in group.quality_order_value.dropna().tolist()
                  if order_is_integer_in_range(value, n)]
        statuses_ok = bool(group.quality_order_status.isin(ORDER_STATUS_OK).all())
        expected_ids = full_ids_by_race[race_id]
        present_ids = set(group.api_record_id.astype("int64"))
        unique_ids = bool(group.api_record_id.is_unique and group.horse_id.astype(str).is_unique and present_ids == expected_ids)
        ids_missing_order_value = int(group.quality_order_status.isna().sum())
        ids_rejected_order = int((~group.local_rank_ok).sum())
        unique_ranks = len(values) == len(set(values))
        complete_set = len(group) == n and len(values) == n and set(values) == set(range(1, n + 1))
        api303_status = group_status_lookup.get((race_id, point))
        api303_gate_ok = api303_status in {"api_group_unreviewed", "api_group_unavailable"}
        group_parse_ok = bool(group_interval_lookup.get((race_id, point), False))
        api4_permutation_ok = bool(n >= 2 and statuses_ok and unique_ids and unique_ranks and complete_set)
        race_point_eligible = bool(api4_permutation_ok and api303_gate_ok)
        permutation_rows.append({
            "race_id": race_id,
            "point": point,
            "race_date": str(starters.loc[starters.race_id.eq(race_id), "race_date"].iloc[0]),
            "year": int(pd.to_datetime(starters.loc[starters.race_id.eq(race_id), "race_date"].iloc[0]).year),
            "race_distance_m": int(starters.loc[starters.race_id.eq(race_id), "race_distance_m"].iloc[0]) if pd.notna(starters.loc[starters.race_id.eq(race_id), "race_distance_m"].iloc[0]) else None,
            "started_n": n,
            "started_rows": int(len(group)),
            "full_started_n": n,
            "snapshot_roster_matches_full": bool(candidate_ids_by_race.get(race_id, set()) == expected_ids),
            "full_started_ids_missing_order_rows": ids_missing_order_value,
            "full_started_ids_rejected_order_rows": ids_rejected_order,
            "rank_rows_valid_1_to_n": int(len(values)),
            "rank_unique_n": int(len(set(values))),
            "all_quality_statuses_accepted": statuses_ok,
            "api4_order_permutation_valid": api4_permutation_ok,
            "api303_group_status": api303_status,
            "api303_interval_parse_pass_diagnostic_only": group_parse_ok,
            "api303_group_gate_supported": api303_gate_ok,
            "api303_group_status_gate": api303_gate_ok,
            "race_point_eligible": race_point_eligible,
            "complete_unique_1_to_n_permutation": api4_permutation_ok,
        })
    permutation = pd.DataFrame(permutation_rows)
    starter_order = starter_order.merge(
        permutation[["race_id", "point", "complete_unique_1_to_n_permutation", "api4_order_permutation_valid",
                     "race_point_eligible", "api303_group_status", "api303_group_gate_supported",
                     "api303_group_status_gate", "api303_interval_parse_pass_diagnostic_only"]],
        on=["race_id", "point"], validate="many_to_one", how="left",
    )
    starter_order["normalized_rank"] = np.nan
    rank_mask = (starter_order.race_point_eligible.astype(bool)
                 & starter_order.local_rank_ok.astype(bool) & starter_order.started_n.ge(2))
    starter_order.loc[rank_mask, "normalized_rank"] = (
        (pd.to_numeric(starter_order.loc[rank_mask, "quality_order_value"], errors="coerce") - 1)
        / (starter_order.loc[rank_mask, "started_n"] - 1)
    )
    assert starter_order.complete_unique_1_to_n_permutation.notna().all()

    source_race_rows = full_race_rows
    connection.close()

    # Narrow timing screen: compare selected cumulative S1F/C4 values and the
    # finish-minus-G1F closing checkpoint only on exact historical source IDs.
    source_time_ids = sorted(lineage.source_api_record_id.astype("int64").unique().tolist())
    time_status_domain = {
        "api_positive_unreviewed", "website_corrected", "website_review_not_applied",
        "api_source_changed_since_review", "unresolved_official_website_anomaly",
        "api_unavailable_or_nonpositive",
    }
    unknown_time_status = sorted(set(source_time_rows.time_status.dropna().astype(str)) - time_status_domain)
    assert not unknown_time_status, unknown_time_status
    time_values_wide = source_time_rows.pivot(index="api_record_id", columns="field_name", values="time_seconds")
    time_status_wide = source_time_rows.pivot(index="api_record_id", columns="field_name", values="time_status")
    time_values_wide.columns = [f"{name}_seconds" for name in time_values_wide.columns]
    time_status_wide.columns = [f"{name}_status" for name in time_status_wide.columns]
    time_ready = pd.DataFrame({"api_record_id": source_time_ids}).merge(
        time_values_wide.reset_index(), on="api_record_id", how="left", validate="one_to_one"
    ).merge(
        time_status_wide.reset_index(), on="api_record_id", how="left", validate="one_to_one"
    ).merge(
        snapshot_starters[["api_record_id", "source_snapshot_valid_time"]], on="api_record_id", how="left", validate="one_to_one"
    ).merge(
        full_race_rows[["api_record_id", "race_date", "race_distance_m", "finish_time_seconds"]],
        on="api_record_id", how="left", validate="one_to_one",
    )
    assert time_ready.source_snapshot_valid_time.notna().all()
    time_ok = {"api_positive_unreviewed", "website_corrected"}
    time_ready["s1f_c4_time_pair_valid"] = (
        time_ready.source_snapshot_valid_time.astype(bool)
        & time_ready.jeS1fTime_status.isin(time_ok)
        & time_ready.je_4cTime_status.isin(time_ok)
        & time_ready.jeS1fTime_seconds.notna() & time_ready.je_4cTime_seconds.notna()
        & time_ready.jeS1fTime_seconds.gt(0) & time_ready.je_4cTime_seconds.gt(0)
    )
    time_ready["c4_g1f_finish_checkpoint_pair_valid"] = (
        time_ready.source_snapshot_valid_time.astype(bool)
        & time_ready.je_4cTime_status.isin(time_ok) & time_ready.jeG1fTime_status.isin(time_ok)
        & time_ready.je_4cTime_seconds.notna() & time_ready.jeG1fTime_seconds.notna()
        & time_ready.finish_time_seconds.notna()
        & time_ready.je_4cTime_seconds.gt(0) & time_ready.jeG1fTime_seconds.gt(0)
        & time_ready.finish_time_seconds.gt(0)
        & time_ready.finish_time_seconds.gt(time_ready.jeG1fTime_seconds)
    )
    time_ready["finish_minus_g1f_checkpoint_seconds"] = (
        time_ready.finish_time_seconds - time_ready.jeG1fTime_seconds
    )
    time_rows_by_distance = []
    for distance, group in time_ready.groupby("race_distance_m", dropna=False, sort=True):
        s_pair = group.loc[group.s1f_c4_time_pair_valid]
        l_pair = group.loc[group.c4_g1f_finish_checkpoint_pair_valid]
        s_cmp = s_pair.jeS1fTime_seconds - s_pair.je_4cTime_seconds
        l_cmp = l_pair.je_4cTime_seconds - l_pair.finish_minus_g1f_checkpoint_seconds
        time_rows_by_distance.append({
            "source_distance_m": None if pd.isna(distance) else int(distance),
            "unique_actual_history_source_ids": int(len(group)),
            "source_valid_time_true_n": int(group.source_snapshot_valid_time.astype(bool).sum()),
            "s1f_c4_selected_time_pairs": int(len(s_pair)),
            "s1f_before_c4_time_n": int(s_cmp.lt(0).sum()),
            "s1f_equal_c4_time_n": int(s_cmp.eq(0).sum()),
            "s1f_not_before_c4_time_n": int(s_cmp.ge(0).sum()),
            "c4_to_finish_minus_g1f_pairs": int(len(l_pair)),
            "c4_before_finish_minus_g1f_checkpoint_n": int(l_cmp.lt(0).sum()),
            "c4_equal_finish_minus_g1f_checkpoint_n": int(l_cmp.eq(0).sum()),
            "c4_not_before_finish_minus_g1f_checkpoint_n": int(l_cmp.ge(0).sum()),
        })
    time_chronology = pd.DataFrame(time_rows_by_distance)

    full_field_rosters = {
        race_id: set(group.horse_number.dropna().astype(int))
        for race_id, group in source_race_rows.groupby("race_id", sort=False)
    }
    group_rows["mapped_started_n"] = [
        len(set(bounds or {}) & race_started_numbers.get(race_id, set()))
        for race_id, bounds in zip(group_rows.race_id, group_rows.bounds)
    ]
    group_rows["source_started_n"] = group_rows.race_id.map(started_n_by_race).fillna(0).astype(int)
    group_rows["started_roster_coverage"] = np.divide(
        group_rows.mapped_started_n,
        group_rows.source_started_n,
        out=np.zeros(len(group_rows), dtype=float),
        where=group_rows.source_started_n.gt(0),
    )
    group_rows["source_roster_number_n"] = group_rows.race_id.map(lambda race_id: len(full_field_rosters.get(race_id, set())))
    group_rows["group_member_n"] = group_rows.bounds.map(lambda bounds: len(bounds or {}))
    group_rows["group_member_numbers_all_in_full_source_roster"] = [
        bool(bounds is not None and set(bounds).issubset(full_field_rosters.get(race_id, set())))
        for race_id, bounds in zip(group_rows.race_id, group_rows.bounds)
    ]

    # For a separate cross-source consistency diagnostic only; group intervals
    # never fill, reorder, or repair API4 ranks.
    per_runner = starters[["api_record_id", "race_id", "race_date", "year", "race_distance_m", "horse_id", "horse_number"]].merge(
        starter_order[["api_record_id", "point", "quality_order_value", "quality_order_status", "local_rank_ok", "complete_unique_1_to_n_permutation"]],
        on="api_record_id", how="left", validate="one_to_many",
    )
    bounds_map = {
        (str(row.race_id), str(row.point)): row.bounds
        for row in group_rows[["race_id", "point", "bounds"]].itertuples(index=False)
    }
    group_status_map = {
        (str(row.race_id), str(row.point)): str(row.group_status)
        for row in group_rows[["race_id", "point", "group_status"]].itertuples(index=False)
    }
    mismatch_examples = []
    mismatch_counts = Counter()
    for row in per_runner.itertuples(index=False):
        bounds = bounds_map.get((str(row.race_id), str(row.point)))
        status = group_status_map.get((str(row.race_id), str(row.point)))
        if not row.local_rank_ok or bounds is None or status != "api_group_unreviewed":
            continue
        interval = bounds.get(int(row.horse_number))
        if interval is None:
            continue
        order_value = int(row.quality_order_value)
        if not interval[0] <= order_value <= interval[1]:
            mismatch_counts[str(row.point)] += 1
            if len(mismatch_examples) < 50:
                mismatch_examples.append({
                    "race_id": str(row.race_id),
                    "race_date": str(row.race_date),
                    "race_distance_m": None if pd.isna(row.race_distance_m) else int(row.race_distance_m),
                    "point": str(row.point),
                    "horse_id": str(row.horse_id),
                    "horse_number": int(row.horse_number),
                    "api4_quality_order": order_value,
                    "api303_member_rank_lo": int(interval[0]),
                    "api303_member_rank_hi": int(interval[1]),
                    "api303_group_status": status,
                    "api4_order_status": str(row.quality_order_status),
                })

    # Link strict point validity back to the original 178,459 actual slots.
    valid_lookup = starter_order.set_index(["api_record_id", "point"]).complete_unique_1_to_n_permutation
    eligible_lookup = starter_order.set_index(["api_record_id", "point"]).race_point_eligible
    order_lookup = starter_order.set_index(["api_record_id", "point"]).normalized_rank
    slot_rows = lineage[["target_api_record_id", "source_api_record_id", "source_race_id", "source_race_date",
                         "target_cutoff", "target_horse_id", "target_distance_m", "slot_oldest_to_newest"]].copy()
    slot_rows["source_api_record_id"] = slot_rows.source_api_record_id.astype("int64")
    slot_rows = slot_rows.merge(
        snapshot_starters[["api_record_id", "race_id", "race_distance_m", "horse_id", "horse_number", "source_snapshot_valid_time"]],
        left_on="source_api_record_id", right_on="api_record_id", validate="many_to_one", how="left",
    )
    slot_rows["year"] = pd.to_datetime(slot_rows.source_race_date).dt.year
    assert slot_rows.api_record_id.notna().all()
    assert slot_rows.race_id.astype(str).equals(slot_rows.source_race_id.astype(str).reset_index(drop=True))
    assert slot_rows.horse_id.astype(str).equals(slot_rows.target_horse_id.astype(str).reset_index(drop=True))
    assert slot_rows.race_distance_m.astype("int64").to_numpy().tolist() == slot_rows.target_distance_m.astype("int64").tolist()
    for point in POINT_FIELDS:
        slot_rows[f"{point}_point_permutation_ok"] = [bool(valid_lookup.get((int(api_id), point), False)) for api_id in slot_rows.source_api_record_id]
        slot_rows[f"{point}_race_point_eligible"] = [bool(eligible_lookup.get((int(api_id), point), False)) for api_id in slot_rows.source_api_record_id]
        slot_rows[f"{point}_r"] = [order_lookup.get((int(api_id), point), np.nan) for api_id in slot_rows.source_api_record_id]
    slot_rows["s1f_valid"] = slot_rows.source_snapshot_valid_time & slot_rows.S1F_race_point_eligible & slot_rows.S1F_r.notna()
    slot_rows["s1f_4c_pair_valid"] = slot_rows.source_snapshot_valid_time & slot_rows.S1F_race_point_eligible & slot_rows["4C_race_point_eligible"] & slot_rows.S1F_r.notna() & slot_rows["4C_r"].notna()
    slot_rows["4c_g1f_pair_valid"] = slot_rows.source_snapshot_valid_time & slot_rows["4C_race_point_eligible"] & slot_rows.G1F_race_point_eligible & slot_rows["4C_r"].notna() & slot_rows.G1F_r.notna()

    # Locked, source-only cache for the next study stage. It keeps every actual
    # slot and exposes selected rank values/statuses separately from group data.
    slot_cache = slot_rows[[
        "target_api_record_id", "source_api_record_id", "source_race_id", "source_race_date",
        "target_cutoff", "target_horse_id", "target_distance_m", "slot_oldest_to_newest",
        "source_snapshot_valid_time", "year",
    ]].copy()
    slot_cache["full_started_n"] = slot_cache.source_race_id.map(started_n_by_race).astype("int64")
    slot_cache["slot_position"] = slot_cache.slot_oldest_to_newest.astype("int64")
    slot_cache["source_horse_id"] = slot_cache.target_horse_id.astype(str)
    slot_cache["source_distance_m"] = slot_cache.target_distance_m.astype("int64")
    starter_point_lookup = starter_order.set_index(["api_record_id", "point"])
    for point, prefix in [("S1F", "s1f"), ("4C", "c4"), ("G1F", "g1f")]:
        for field, suffix in [
            ("quality_order_value", "order"), ("quality_order_status", "order_status"),
            ("normalized_rank", "r"), ("local_rank_ok", "individual_order_valid"),
            ("complete_unique_1_to_n_permutation", "full_point_permutation_valid"),
            ("race_point_eligible", "race_point_eligible"),
        ]:
            value_map = starter_point_lookup.xs(point, level="point")[field]
            slot_cache[f"{prefix}_{suffix}"] = slot_cache.source_api_record_id.map(value_map)
        slot_cache[f"{prefix}_api303_group_status"] = [
            group_status_lookup.get((str(race_id), point)) for race_id in slot_cache.source_race_id
        ]
        slot_cache[f"{prefix}_group_status_gate"] = slot_cache[f"{prefix}_api303_group_status"].isin(
            ["api_group_unreviewed", "api_group_unavailable"]
        )
        slot_cache[f"{prefix}_api303_group_status_gate"] = slot_cache[f"{prefix}_group_status_gate"]
        slot_cache[f"{prefix}_group_interval_parse_pass_diagnostic_only"] = [
            bool(group_interval_lookup.get((str(race_id), point), False)) for race_id in slot_cache.source_race_id
        ]
        slot_cache[f"{prefix}_final_point_eligible"] = (
            slot_cache.source_snapshot_valid_time.astype(bool)
            & slot_cache[f"{prefix}_race_point_eligible"].fillna(False).astype(bool)
            & slot_cache[f"{prefix}_r"].notna()
        )
    slot_cache["s1f_to_c4_forward_change"] = np.where(
        slot_cache.s1f_final_point_eligible & slot_cache.c4_final_point_eligible,
        slot_cache.s1f_r - slot_cache.c4_r,
        np.nan,
    )
    slot_cache["s1f_to_c4_pair_eligible"] = slot_cache.s1f_final_point_eligible & slot_cache.c4_final_point_eligible
    slot_cache["c4_to_g1f_forward_change"] = np.where(
        slot_cache.c4_final_point_eligible & slot_cache.g1f_final_point_eligible,
        slot_cache.c4_r - slot_cache.g1f_r,
        np.nan,
    )
    slot_cache["c4_to_g1f_pair_eligible"] = slot_cache.c4_final_point_eligible & slot_cache.g1f_final_point_eligible

    # Pair windows preserve the 5 actual source IDs; no old-slot backfill.
    counts_by_target = slot_rows.groupby("target_api_record_id").agg(
        s1f_n=("s1f_valid", "sum"), s1f_4c_pair_n=("s1f_4c_pair_valid", "sum"),
        c4_g1f_pair_n=("4c_g1f_pair_valid", "sum"), actual_slots=("source_api_record_id", "size"),
    ).reset_index()
    assert counts_by_target.actual_slots.le(5).all()
    target_rows = features[["api_record_id", "year", "distance_m"]].merge(
        counts_by_target, left_on="api_record_id", right_on="target_api_record_id", validate="one_to_one", how="left"
    )
    for column in ["s1f_n", "s1f_4c_pair_n", "c4_g1f_pair_n", "actual_slots"]:
        target_rows[column] = target_rows[column].fillna(0).astype(int)
    assert target_rows.actual_slots.le(5).all()
    assert target_rows[["s1f_n", "s1f_4c_pair_n", "c4_g1f_pair_n"]].le(target_rows.actual_slots, axis=0).all().all()
    distance_rows = []
    for (distance, year), group in target_rows.groupby(["distance_m", "year"], dropna=False, sort=True):
        record = {"target_distance_m": int(distance), "target_year": int(year), "targets": int(len(group)),
                  "targets_with_slots": int(group.actual_slots.gt(0).sum()), "actual_slots": int(group.actual_slots.sum())}
        for name, column in [("s1f", "s1f_n"), ("s1f_4c_pair", "s1f_4c_pair_n"), ("c4_g1f_pair", "c4_g1f_pair_n")]:
            record[f"{name}_valid_slots"] = int(group[column].sum())
            record[f"{name}_targets_n0"] = int(group[column].eq(0).sum())
            record[f"{name}_targets_n1_2"] = int(group[column].between(1, 2).sum())
            record[f"{name}_targets_n3_5"] = int(group[column].between(3, 5).sum())
            for n in range(6):
                record[f"{name}_targets_n{n}"] = int(group[column].eq(n).sum())
        distance_rows.append(record)

    # Point-by-distance support reports unique source races and started runners;
    # API303 interval rows are kept separate from the API4 permutation gate.
    point_rows = []
    for column in ["complete_unique_1_to_n_permutation", "api4_order_permutation_valid",
                   "api303_group_gate_supported", "race_point_eligible"]:
        permutation[column] = permutation[column].astype(bool)
    for (distance, point), group in permutation.groupby(["race_distance_m", "point"], dropna=False, sort=True):
        point_rows.append({
            "source_distance_m": None if pd.isna(distance) else int(distance),
            "point": str(point),
            "source_races": int(len(group)),
            "api4_order_permutation_valid_races": int(group.api4_order_permutation_valid.sum()),
            "api303_group_gate_supported_races": int(group.api303_group_gate_supported.sum()),
            "race_point_eligible_races": int(group.race_point_eligible.sum()),
            "api4_order_permutation_invalid_races": int((~group.api4_order_permutation_valid).sum()),
            "started_runner_rows": int(group.started_rows.sum()),
            "rank_rows_valid_1_to_n": int(group.rank_rows_valid_1_to_n.sum()),
        })

    group_rows = group_rows.merge(
        source_race_rows[["race_id", "race_distance_m"]].drop_duplicates(),
        left_on="race_id", right_on="race_id", validate="many_to_one", how="left",
    )
    group_summary = group_rows.groupby(["race_distance_m", "point", "group_status"], dropna=False).agg(
        source_race_points=("race_id", "size"), parsed_interval_points=("parsed_interval_ok", "sum"),
        started_runner_rows_mapped=("mapped_started_n", "sum"), source_started_n=("source_started_n", "sum"),
        full_started_roster_points=("started_roster_coverage", lambda x: int((x >= 1.0).sum())),
        mean_started_roster_coverage=("started_roster_coverage", "mean"),
        member_numbers_all_in_full_source_roster=("group_member_numbers_all_in_full_source_roster", "sum"),
    ).reset_index()
    group_summary = group_summary.rename(columns={"race_distance_m": "source_distance_m", "point": "api303_point"})

    # Target and shared source hashes are narrowly scoped. Rehash the DB once;
    # the prior lock is a comparison anchor, not a substitute for verification.
    base_lock = json.loads(BASE_LOCK.read_text(encoding="utf-8"))
    db_lock = base_lock["protected"]["jeju/data/jeju_native_core.sqlite3"]
    assert DB.stat().st_size == int(db_lock["bytes"])
    db_sha = sha256(DB)
    assert db_sha == str(db_lock["sha256"])
    time_receipt = json.loads(TIME_SOURCE_RECEIPT.read_text(encoding="utf-8"))
    assert time_receipt["database_reference"]["sha256_from_existing_time_extraction_lock"] == db_sha

    # Reconfirm four reviewed/unresolved time outcomes via the quality constituent.
    con_check = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
    con_check.execute("PRAGMA query_only=ON")
    time_cases = pd.read_sql_query(
        "SELECT api_record_id,field_name,time_seconds,time_status FROM jeju_race_section_time_values "
        "WHERE (api_record_id,field_name) IN (VALUES (?,?),(?,?),(?,?),(?,?)) "
        "ORDER BY api_record_id,field_name",
        con_check, params=[
            178142, "jeS1fTime", 180747, "jeS1fTime",
            191451, "jeG1fTime", 190686, "jeG1fTime",
        ],
    )
    con_check.close()
    selected_time_cases = {
        (int(row.api_record_id), str(row.field_name)): (None if pd.isna(row.time_seconds) else float(row.time_seconds), str(row.time_status))
        for row in time_cases.itertuples(index=False)
    }
    expected_time_cases = {
        (178142, "jeS1fTime"): (20.0, "website_corrected"),
        (180747, "jeS1fTime"): (17.8, "website_corrected"),
        (191451, "jeG1fTime"): (None, "unresolved_official_website_anomaly"),
        (190686, "jeG1fTime"): (16.0, "website_corrected"),
    }
    assert selected_time_cases == expected_time_cases

    # Current relevant points and fields are explicit in DDL, but DDL contains no
    # distance-specific physical measurement crosswalk. Keep that limitation.
    source_files = [
        F1_FEATURES, F1_LINEAGE, SOURCE_SNAPSHOT, BASE_LOCK, TIME_SOURCE_RECEIPT,
        F1_DIR / "CONTRACT.md", F1_DIR / "prepare.py",
        Path(__file__).resolve(),
        ROOT / "jeju/AGENTS.md", ROOT / "jeju/docs/RESTART_PLAN_20260928.md",
        ROOT / "jeju/research/RESEARCH_PUBLICATION_POLICY.md",
        ROOT / "jeju/research/20261008_passing_group_running_style_v1/PLAN.md",
        ROOT / "jeju/research/20261002_section_passing_audit/README.md",
        EXISTING_GROUP_RUNNERS, EXISTING_GROUP_POINTS,
        ROOT / "config/prediction_model_registry.json",
        ROOT / "jeju/models/current/HY_R_FORM.pkl",
        ROOT / "jeju/models/current/metadata.json",
    ]
    input_hashes = {
        path.relative_to(ROOT).as_posix(): {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in source_files
    }
    ddl_hashes = {name: hashlib.sha256(sql.encode("utf-8")).hexdigest() for name, sql in ddl.items()}
    prior_ddl_hashes = time_receipt["quality_view_dependency_ddl_sha256"]
    ddl_unchanged_from_time_audit = all(ddl_hashes[name] == prior_ddl_hashes[name] for name in ddl_hashes if name in prior_ddl_hashes)
    assert ddl_unchanged_from_time_audit

    order_status_counts = {
        point: {str(k): int(v) for k, v in group.quality_order_status.value_counts(dropna=False).items()}
        for point, group in starter_order.groupby("point", sort=True)
    }
    slot_order_status_counts = {
        point: {str(k): int(v) for k, v in group.quality_order_status.value_counts(dropna=False).items()}
        for point, group in slot_rows.merge(
            order_rows[["api_record_id", "field_name", "quality_order_status"]],
            left_on="source_api_record_id", right_on="api_record_id", how="left", validate="many_to_many"
        ).assign(point=lambda frame: frame.field_name.map({v: k for k, v in POINT_FIELDS.items()})).groupby("point", sort=True)
    }
    group_status_counts = {
        point: {str(k): int(v) for k, v in group.group_status.value_counts(dropna=False).items()}
        for point, group in group_rows.groupby("point", sort=True)
    }
    point_eligible_races = {
        point: int(group.loc[group.race_point_eligible, "race_id"].nunique())
        for point, group in permutation.groupby("point", sort=True)
    }
    api4_permutation_races = {
        point: int(group.loc[group.api4_order_permutation_valid, "race_id"].nunique())
        for point, group in permutation.groupby("point", sort=True)
    }
    group_counts_by_point_distance = group_summary.to_dict(orient="records")
    quality_status_counts_from_prior_receipt = time_receipt["quality_status_counts"]

    api4_cache = starter_order[[
        "race_id", "race_date", "race_distance_m", "api_record_id", "horse_id", "horse_number",
        "point", "field_name", "started_n", "quality_order_value", "quality_order_status",
        "local_rank_ok", "normalized_rank", "api303_group_status", "api303_group_gate_supported",
        "api303_group_status_gate", "api303_interval_parse_pass_diagnostic_only",
        "api4_order_permutation_valid", "race_point_eligible", "complete_unique_1_to_n_permutation",
        "source_snapshot_valid_time",
    ]].copy().rename(columns={
        "started_n": "full_started_n",
        "complete_unique_1_to_n_permutation": "point_permutation_valid",
    })
    api4_cache["started_n"] = api4_cache.full_started_n
    api4_cache["complete_unique_1_to_n_permutation"] = api4_cache.point_permutation_valid
    write_new_parquet(OUT_SOURCE_CACHE, api4_cache)
    write_new_parquet(OUT_SLOT_CACHE, slot_cache)
    write_new_csv(OUT_DISTANCE, pd.DataFrame(distance_rows))
    write_new_csv(OUT_POINT, pd.DataFrame(point_rows))
    write_new_csv(OUT_GROUP, group_summary)
    write_new_csv(OUT_EXAMPLES, pd.DataFrame(mismatch_examples))
    write_new_csv(OUT_ROSTER, roster_audit_df)
    write_new_csv(OUT_RACE_POINT, permutation)
    write_new_csv(OUT_TIME, time_chronology)
    artifact_hashes = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in [OUT_SOURCE_CACHE, OUT_SLOT_CACHE, OUT_DISTANCE, OUT_POINT, OUT_GROUP,
                     OUT_EXAMPLES, OUT_ROSTER, OUT_RACE_POINT, OUT_TIME]
    }
    full_roster_counts = {
        "referenced_races": int(len(race_keys)),
        "full_race_result_rows": int(len(full_race_rows)),
        "full_race_result_started_rows": int(len(starters)),
        "snapshot_rows_in_referenced_races": int(len(snapshot_race_rows)),
        "snapshot_started_rows_in_referenced_races": int(len(snapshot_starters)),
        "races_where_snapshot_started_n_differs_from_full": int(roster_audit_df.full_minus_snapshot_started_n.ne(0).sum()),
        "races_where_snapshot_started_n_is_smaller": int(roster_audit_df.full_minus_snapshot_started_n.gt(0).sum()),
        "sum_full_minus_snapshot_started_n": int(roster_audit_df.full_minus_snapshot_started_n.sum()),
        "max_full_minus_snapshot_started_n": int(roster_audit_df.full_minus_snapshot_started_n.max()),
        "full_started_null_api_id": int(starters.api_record_id.isna().sum()),
        "full_started_null_horse_id": int(starters.horse_id.isna().sum()),
        "full_started_null_horse_number": int(starters.horse_number.isna().sum()),
        "full_started_duplicate_api_id_rows": int(starters.duplicated(["race_id", "api_record_id"], keep=False).sum()),
        "full_started_duplicate_horse_id_rows": int(starters.duplicated(["race_id", "horse_id"], keep=False).sum()),
        "full_started_duplicate_horse_number_rows": int(starters.duplicated(["race_id", "horse_number"], keep=False).sum()),
        "snapshot_common_rows_exactly_match_full_base": True,
    }

    # Tie interpretation and status distinctions are recorded explicitly.
    summary = {
        "audit_status": "completed_source_definition_and_slot_support_only",
        "passed": True,
        "fit_or_prediction_work": False,
        "db_write": False,
        "uri_mode_ro_and_query_only": True,
        "f1_population": {
            "target_rows": int(len(features)),
            "target_races": int(features.race_id.nunique()),
            "evaluation_rows_2024_2026": int(features.year.ge(2024).sum()),
            "evaluation_races_2024_2026": int(features.loc[features.year.ge(2024), "race_id"].nunique()),
            "source_snapshot_rows": int(len(snapshot)),
            "source_snapshot_rows_in_referenced_history_races": int(len(snapshot_race_rows)),
            "source_snapshot_started_rows_in_referenced_history_races": int(len(snapshot_starters)),
            "full_race_result_started_rows_in_referenced_history_races": int(len(starters)),
            "actual_same_distance_last5_slots": int(len(lineage)),
            "distinct_slot_source_api_ids": int(lineage.source_api_record_id.nunique()),
            "distinct_slot_source_races": int(lineage.source_race_id.nunique()),
            "target_last5_slot_order_matches_saved_ids": True,
            "source_horse_distance_started_and_t_minus_2_checks": True,
            "n_started_source": "Full exact-key race_result_rows count using inherited finish_position 1..89 or 91/92 started rule; no reclassification of other codes. Candidate source_snapshot N is not reused for normalization.",
            "full_roster_reconciliation": full_roster_counts,
        },
        "candidate_6_field_definition": {
            "point_validity": "Keep API4 order validity and API303 group status as separate gates. Pure API4 permutation requires the full exact-key race_result_rows started ID set to have accepted API4 status in {api_positive_unreviewed, website_corrected}, integer order 1..N, and exact set 1..N without duplicate horse IDs/ranks; N is the full started roster. Race-point eligibility additionally requires API303 status api_group_unreviewed or api_group_unavailable. Missing/other group status holds the point. normalized_rank requires both gates; slot contribution additionally requires source_snapshot.valid_time=True.",
            "source_valid_time_gate": "Each actual source slot contributes to any mean+n only when its inherited source_snapshot.valid_time is True. Invalid source time NULLs that slot's three values and never causes older-slot backfill; actual slot count stays fixed.",
            "normalized_rank": "r=(order-1)/(N-1); 0=front, 1=back; only when N>=2 and point permutation passes.",
            "concept_1": {"mean": "mean S1F r over valid exact-distance last-five actual source slots", "n": "number of those slots, 0..5; mean NULL if n=0"},
            "concept_2": {"mean": "mean of S1F r - 4C r on same source slots where both full point permutations pass", "n": "paired slots, 0..5; positive means relative rank moved forward by 4C; mean NULL if n=0"},
            "concept_3": {"mean": "mean of 4C r - G1F r on same source slots where both full point permutations pass", "n": "paired slots, 0..5; positive means relative rank moved forward by G1F; mean NULL if n=0"},
            "feature_mapping": {
                "hist_s1f_relpos_mean5": "mean of slot-cache s1f_r over s1f_final_point_eligible slots",
                "hist_s1f_relpos_n": "count of those same source slots; 0..5; mean NULL at n=0",
                "hist_s1f_to_c4_forward_mean5": "mean of s1f_r - c4_r over s1f_to_c4_pair_eligible slots",
                "hist_s1f_to_c4_pair_n": "count of those same-slot eligible S1F/4C pairs; 0..5; mean NULL at n=0",
                "hist_c4_to_g1f_forward_mean5": "mean of c4_r - g1f_r over c4_to_g1f_pair_eligible slots",
                "hist_c4_to_g1f_pair_n": "count of those same-slot eligible 4C/G1F pairs; 0..5; mean NULL at n=0",
            },
            "field_count_columns": ["hist_s1f_relpos_mean5", "hist_s1f_relpos_n", "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n", "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n"],
            "group_data_role": "API303 interval source is reported separately for coverage/discordance; it never restores API4 intra-group order and never fills an API4 missing/conflict value.",
            "rank_order_relation_sign": "larger r is farther back; transition change is earlier r minus later r, so positive is relative advance",
            "no_finish_position_in_candidate_fields": True,
        },
        "quality_view_chain": {
            "quality_view": "jeju_race_postrace_sections_quality_2026",
            "quality_view_joins_order_aggregate_by_api4_record": True,
            "quality_view_joins_group_aggregate_by_api303_record": True,
            "order_aggregate_reads_order_quality_values": True,
            "group_aggregate_reads_group_quality_values": True,
            "order_fields": POINT_FIELDS,
            "api303_point_to_field": {"S1F": "corner_7", "1C": "corner_1", "2C": "corner_2", "3C": "corner_3", "4C": "corner_4", "G1F": "corner_8"},
            "quality_view_dependency_ddl_sha256": ddl_hashes,
            "ddl_matches_locked_section_time_audit": ddl_unchanged_from_time_audit,
            "api4_order_status_counts_referenced_started_runners": order_status_counts,
            "api4_order_status_counts_actual_slots_weighted": slot_order_status_counts,
            "api303_group_status_counts_referenced_races": group_status_counts,
            "quality_status_counts_full_domain_from_existing_locked_receipt": quality_status_counts_from_prior_receipt,
            "global_unresolved_record_counts_from_prior_quality_audit": {"api4_individual_order": 70, "api303_group_points": 20},
            "global_order_unresolved_preserved_by_quality_status_null_contract": True,
            "api303_unavailable_is_distinct_from_internal_conflict": True,
            "known_time_review_cases_reconfirmed": {f"{api_id}:{field}": {"time_seconds": seconds, "time_status": status} for (api_id, field), (seconds, status) in selected_time_cases.items()},
        },
        "chronology_and_distance": {
            "point_sequence_for_candidate": "S1F order -> 4C order -> G1F order, each by labeled point, using only same-race same-horse pairs.",
            "1300m_user_contract": "start -> 2C -> S1F is preserved; S1F is after 2C for this contract and is not a first-corner/pre-2C location.",
            "source_sequence_evidence": "Prior passing-group research used S1F-before-4C and 4C-before-G1F as descriptive point sequences; current section-time contract distinguishes S1F/C1-C4 elapsed point times from G3F/G1F closing-section durations. This audit checks selected S1F < selected 4C and selected 4C < (finish-G1F) by exact source distance. The latter is an estimated start-of-final-1F elapsed checkpoint used only as a temporal consistency proxy. These checks do not prove physical geometry. The older 1300m S1F/2C hold predates the current user-defined start->2C->S1F contract and is not copied as a new hold.",
            "s1f_universal_distance_assumption": "none; S1F is the source point label, not assumed to be 200m or 210m.",
            "distance_specific_point_semantics_in_quality_ddl": "not encoded; DDL exposes point fields but no physical-distance crosswalk. The candidate is relative order at the named source points, and support is reported by exact distance.",
            "4c_to_g1f_interpretation": "late relative-position change between labeled points; not final advance, speed, acceleration, or fitness cause.",
            "api303_parentheses": "members of one unordered group share an inclusive rank interval based on counts of preceding group members; no within-group member order is assigned.",
            "point_support_by_distance_and_year_file": OUT_POINT.name,
            "target_window_support_by_distance_and_year_file": OUT_DISTANCE.name,
            "api303_support_by_distance_file": OUT_GROUP.name,
            "quality_time_consistency_by_distance_file": OUT_TIME.name,
            "time_consistency_not_feature_or_source_gate": True,
        },
        "source_slot_quality": {
            "order_valid_status_allowlist": sorted(ORDER_STATUS_OK),
            "invalid_fail_closed_statuses": sorted(ORDER_STATUS_ALLOWED - ORDER_STATUS_OK),
            "group_status_source_domain": sorted(GROUP_STATUS_ALLOWED),
            "group_status_candidate_allowlist": ["api_group_unreviewed", "api_group_unavailable"],
            "api_group_unavailable_distinct_from_conflict": True,
            "api_group_unreviewed_is_not_official_website_confirmation": True,
            "api303_parser_is_diagnostic_only": True,
            "unknown_status_domain": {"api4_order": unknown_order, "api303_group": unknown_group},
            "quality_order_value_range": "integer 1..N_started, not finish rank and not bracket order from API303",
            "api4_order_permutation_valid_races_by_point": api4_permutation_races,
            "race_point_eligible_races_by_point": point_eligible_races,
            "api4_api303_interval_mismatch_count_by_point": dict(mismatch_counts),
            "api4_api303_interval_mismatch_rows_are_diagnostic_only": True,
            "same_distance_slots_kept_when_any_point_missing": True,
            "window_slot_n_backfill": False,
        },
        "input_hashes": {
            **input_hashes,
            "jeju/data/jeju_native_core.sqlite3": {"bytes": int(DB.stat().st_size), "sha256": db_sha, "sha_rehashed": True, "matches_existing_locks": True},
        },
        "artifacts": artifact_hashes,
        "cache_paths": {"full_started_point_quality": OUT_SOURCE_CACHE.name, "actual_slot_eligibility": OUT_SLOT_CACHE.name},
        "cache_rows": {"full_started_point_quality": int(len(api4_cache)), "actual_slot_eligibility": int(len(slot_cache))},
        "source_status_policy": {
            "api4_order_allowed": sorted(ORDER_STATUS_OK),
            "api303_group_status_allowed": ["api_group_unreviewed", "api_group_unavailable"],
            "api_group_unavailable_is_not_conflict": True,
            "api_group_unreviewed_is_not_official_website_confirmation": True,
            "api303_parser_is_diagnostic_only": True,
            "missing_or_conflict_group_status_holds_point": True,
        },
        "runtime": {"python": __import__("sys").version.split()[0], "pandas": pd.__version__, "numpy": np.__version__, "sqlite_query_only": 1},
    }

    write_new_json(OUT_JSON, summary)
    print(json.dumps({
        "status": summary["audit_status"],
        "rows": len(features), "last5_slots": len(lineage), "distinct_sources": int(lineage.source_api_record_id.nunique()),
        "source_races": len(referenced_races), "started_source_rows": len(starters),
        "permutation_valid_races": point_eligible_races,
        "mismatches": dict(mismatch_counts),
        "distance_rows": len(distance_rows), "point_rows": len(point_rows), "group_rows": len(group_summary),
        "output": str(OUT_JSON),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

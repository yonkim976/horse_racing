"""Read-only source checks and T-2 rolling jockey history for one pair arm."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
STARTS = ROOT / "jeju/research/20261009_jockey_effects_v1/input01/starts.csv"
STARTS_MANIFEST = ROOT / "jeju/research/20261009_jockey_effects_v1/input01/source_manifest.json"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
EXPANSION = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
EXPECTED = {
    STARTS: "78800c5c91219d58855ce046e39ead6a87729a49c8ba0d58ca9f78765921801a",
    STARTS_MANIFEST: "68e38ee6b2ec32040fa6a8a8fdce4039ece3f25e0869004d910c92a288f50bdc",
    FEATURES: "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    EXPANSION / "outputs/evaluation_pair_predictions.parquet": "f983d9c5dfa7c4d1129b407d5a3e367dc38e193c0c8fdbbaeff34d86b31af499",
}
HISTORY_COLUMNS = [
    "api_record_id", "race_id", "horse_id", "race_date", "race_distance_m",
    "field_n", "finish_position", "jockey_id",
]
ROSTER_COLUMNS = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "field_n"]
DISTANCES = {800, 900, 1000, 1110, 1200, 1300, 1400, 1610}
EXCLUDED_HORSE = "3005648"
SHRINKAGE_STARTS = 20.0


class InputError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise InputError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"input symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def load_starts(include_results: bool = True) -> pd.DataFrame:
    path = checked(STARTS)
    columns = HISTORY_COLUMNS if include_results else [
        "api_record_id", "race_id", "horse_id", "race_date", "race_distance_m", "jockey_id",
    ]
    types = {name: "string" for name in ("api_record_id", "race_id", "horse_id", "jockey_id")}
    frame = pd.read_csv(path, usecols=columns, dtype=types, low_memory=False)
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce").dt.normalize()
    require(frame["api_record_id"].notna().all() and frame["api_record_id"].is_unique, "source API key missing/duplicate")
    require(frame["jockey_id"].notna().all(), "event jockey ID is missing in eligible source rows")
    require(frame["jockey_id"].str.fullmatch(r"\d{6}").all(), "event jockey ID format changed")
    require(frame["race_date"].notna().all(), "source race date invalid")
    if include_results:
        frame["field_n"] = pd.to_numeric(frame["field_n"], errors="coerce")
        frame["finish_position"] = pd.to_numeric(frame["finish_position"], errors="coerce")
        require(frame["field_n"].notna().all() and frame["finish_position"].notna().all(), "historical complete-finish fields missing")
        require(frame["field_n"].ge(4).all() and frame["finish_position"].ge(1).all(), "invalid historical field/rank")
    return frame


def load_roster(path: Path = FEATURES, years: tuple[int, ...] = tuple(range(2019, 2027))) -> pd.DataFrame:
    frame = pd.read_parquet(checked(path), columns=ROSTER_COLUMNS)
    frame["api_record_id"] = frame["api_record_id"].astype("string")
    frame["race_id"] = frame["race_id"].astype("string")
    frame["horse_id"] = frame["horse_id"].astype("string")
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce").dt.normalize()
    frame = frame.loc[frame["year"].isin(years)].copy()
    require(frame["race_date"].notna().all(), "roster race date invalid")
    require(frame["api_record_id"].is_unique, "frozen roster API key is not unique")
    return frame


def attach_event_jockey(roster: pd.DataFrame, starts: pd.DataFrame) -> pd.DataFrame:
    keys = starts[["api_record_id", "race_id", "horse_id", "race_date", "jockey_id"]]
    result = roster.merge(keys, on="api_record_id", how="left", validate="one_to_one", indicator=True, suffixes=("", "_source"))
    require(result["_merge"].eq("both").all(), "frozen roster has no official event jockey source row")
    for column in ("race_id", "horse_id"):
        require(result[column].eq(result[f"{column}_source"]).all(), f"event {column} changed at API-key join")
    require(result["race_date"].eq(result["race_date_source"]).all(), "event date changed at API-key join")
    require(result["jockey_id"].notna().all(), "official event jockey ID missing after join")
    return result.drop(columns=["_merge", "race_id_source", "horse_id_source", "race_date_source"])


def preflight_source() -> dict:
    """Check source identity and roster coverage without reading finish labels."""
    hashes = {}
    for path, expected_hash in EXPECTED.items():
        resolved = checked(path)
        observed = sha256(resolved)
        require(observed == expected_hash, f"pinned source hash changed: {path.relative_to(ROOT)}")
        hashes[str(path.relative_to(ROOT))] = observed
    starts = load_starts(include_results=False)
    roster = load_roster()
    joined = attach_event_jockey(roster, starts)
    require(not joined["horse_id"].eq(EXCLUDED_HORSE).any(), "excluded horse entered roster")
    distances = set(pd.to_numeric(starts["race_distance_m"], errors="coerce").dropna().astype(int).unique())
    require(distances == DISTANCES, "source distance inventory changed")
    source_scope = {
        "rows": int(len(starts)), "races": int(starts["race_id"].nunique()),
        "first_date": starts["race_date"].min().date().isoformat(),
        "last_date": starts["race_date"].max().date().isoformat(),
        "jockey_ids": int(starts["jockey_id"].nunique()),
    }
    evaluation = joined.loc[joined["year"].between(2024, 2026)].copy()
    require(len(evaluation) == 17412, "evaluation runner coverage changed")
    require(evaluation["race_id"].nunique() == 1779, "evaluation race coverage changed")
    require(evaluation["race_date"].nunique() == 269, "evaluation date coverage changed")
    require(evaluation.groupby("year")["race_id"].nunique().to_dict() == {2024: 637, 2025: 654, 2026: 488},
            "evaluation year race inventory changed")
    roster_scope = {
        "rows": int(len(evaluation)), "races": int(evaluation["race_id"].nunique()),
        "dates": int(evaluation["race_date"].nunique()),
        "first_date": evaluation["race_date"].min().date().isoformat(),
        "last_date": evaluation["race_date"].max().date().isoformat(),
        "jockey_ids": int(evaluation["jockey_id"].nunique()),
        "missing_official_jockey_ids": int(evaluation["jockey_id"].isna().sum()),
        "key_mismatches": 0,
    }
    return {
        "status": "PASS", "scope": "source identity and official event-jockey key coverage only",
        "performance_metrics_computed": False, "finish_labels_read": False,
        "source_hashes": hashes, "source_scope": source_scope,
        "pair_input_years_2019_2025": {
            "rows": int(joined["year"].between(2019, 2025).sum()),
            "races": int(joined.loc[joined["year"].between(2019, 2025), "race_id"].nunique()),
            "dates": int(joined.loc[joined["year"].between(2019, 2025), "race_date"].nunique()),
        },
        "evaluation_roster_2024_2026": {
            **{key: value for key, value in roster_scope.items()},
            "years": {str(int(year)): int(count) for year, count in evaluation.groupby("year").size().items()},
        },
        "source_assumption": "cached event jockey ID is the historical rider snapshot; publication/change timestamp is unavailable",
    }


def rolling_features(target_rows: pd.DataFrame, starts: pd.DataFrame) -> pd.DataFrame:
    """Attach one field-relative, trailing-365d Top3 feature at each runner's T-2."""
    require({"api_record_id", "race_id", "race_date", "jockey_id"}.issubset(target_rows.columns), "target rows lack event key/date/rider")
    require({"api_record_id", "race_date", "field_n", "finish_position", "jockey_id"}.issubset(starts.columns), "history rows lack formula inputs")
    history = starts.sort_values(["jockey_id", "race_date", "api_record_id"], kind="mergesort")
    grouped = {}
    for rider_id, group in history.groupby("jockey_id", sort=False):
        dates = group["race_date"].to_numpy(dtype="datetime64[D]")
        top3 = group["finish_position"].to_numpy(dtype=float) <= 3
        expected = 3.0 / group["field_n"].to_numpy(dtype=float)
        grouped[str(rider_id)] = (
            dates,
            np.concatenate(([0], np.cumsum(np.ones(len(group), dtype=np.int64)))),
            np.concatenate(([0.0], np.cumsum(top3, dtype=np.int64))),
            np.concatenate(([0.0], np.cumsum(expected, dtype=float))),
        )
    rows = target_rows[["api_record_id", "race_id", "race_date", "jockey_id"]].copy()
    rows["race_date"] = pd.to_datetime(rows["race_date"], errors="coerce").dt.normalize()
    require(rows["race_date"].notna().all() and rows["jockey_id"].notna().all(), "invalid target event date/rider")
    n_values = np.zeros(len(rows), dtype=np.int64)
    success_values = np.zeros(len(rows), dtype=np.int64)
    expected_values = np.zeros(len(rows), dtype=float)
    for index, (rider_id, race_date) in enumerate(zip(rows["jockey_id"], rows["race_date"], strict=True)):
        values = grouped.get(str(rider_id))
        if values is None:
            continue
        dates, counts, successes, expected = values
        cutoff = np.datetime64((race_date - pd.Timedelta(days=2)).date().isoformat(), "D")
        lower_exclusive = cutoff - np.timedelta64(365, "D")
        left = int(np.searchsorted(dates, lower_exclusive, side="right"))
        right = int(np.searchsorted(dates, cutoff, side="right"))
        n_values[index] = int(counts[right] - counts[left])
        success_values[index] = int(successes[right] - successes[left])
        expected_values[index] = float(expected[right] - expected[left])
    delta = (success_values - expected_values) / (n_values.astype(float) + SHRINKAGE_STARTS)
    delta[n_values == 0] = 0.0
    result = rows[["api_record_id", "race_id", "race_date", "jockey_id"]].copy()
    result["jockey365_n"] = n_values
    result["jockey365_top3"] = success_values
    result["jockey365_expected_top3"] = expected_values
    result["jockey365_field_relative_top3"] = delta
    require(np.isfinite(delta).all() and np.isfinite(expected_values).all(), "non-finite rolling jockey history")
    require(result["api_record_id"].is_unique, "rolling feature runner key is not unique")
    return result


def write_once(path: Path, value: dict) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")

#!/usr/bin/env python3
"""Build compact, contract-bound inputs from frozen local research sources.

This program audits sources and constructs history features only. It performs
no fitting, prediction, calibration, or evaluation-metric calculation.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import ndtri


ROOT = Path(__file__).resolve().parents[4]
STUDY = ROOT / "jeju/research/20261022_dynamic_ability_pace_v1"
INPUTS = STUDY / "inputs"
AUDIT = STUDY / "audit"
SNAPSHOT = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
REFERENCE_FEATURES = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/features.parquet"
RACE_LEDGER = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/race_inclusion_ledger.csv"
OBSERVATIONS = ROOT / "jeju/research/20261021_phase_pace_prediction_v1/outputs/observations.parquet"
LABEL_REFERENCE = ROOT / "jeju/research/20261021_phase_pace_prediction_v1/outputs/features_and_targets.parquet"
SOURCE_MANIFEST = AUDIT / "source_manifest.json"
EXCLUSION_FILE = ROOT / "jeju/data/horse_exclusions.json"
CONTRACT = STUDY / "supervisor/DESIGN_CONTRACT.md"
DISTANCES = {800, 900, 1000, 1110, 1200, 1300, 1400, 1610}
SOURCE_EXPECTED = {
    "source_snapshot.parquet": "c2307afe79c4ca3a1c4a1ab46159be93450ca03450f8fd51063dd2318ed49403",
    "features.parquet": "6f6540d4786ada0c0e288ff5defc0d4c665cc796a025a074f19f3d4fe218f12f",
    "observations.parquet": "bcf056ea788f2637c17a6b404013a7718fa3ed6f2042f6693cf6f167dfaf83c7",
    "features_and_targets.parquet": "0dcf70c9cb4822fb3c5198e1a138648062f5d94d1ef9bf712929d40e2a0dca33",
    "race_inclusion_ledger.csv": "959274837a1eafe627851b505e271402b5c969f2aa31d7195824dc0112f28eb5",
    "horse_exclusions.json": "5a88a0f19880a5b19ed7bfdec5a2465cb6652cff4b91c5cbe255fff377bcf84a",
}
CHANNELS = ("rank", "margin", "early", "recovery")
SUFFIXES = (
    "all_mean",
    "exact_distance_deviation",
    "all_weight_sum",
    "exact_distance_weight_sum",
    "all_weighted_variance",
    "days_since_last_valid",
)
A_FEATURES = tuple(f"{ch}_{suffix}" for ch in CHANNELS for suffix in SUFFIXES) + (
    "distance_m", "field_size", "gate_scaled",
)
SUMMARY_FEATURES = (
    "early_mean_race_mean",
    "early_mean_race_max",
    "early_mean_race_known_count",
    "recovery_mean_race_mean",
    "recovery_mean_race_max",
    "recovery_mean_race_known_count",
)
RUNNER_PHASE_FEATURES = A_FEATURES + SUMMARY_FEATURES + (
    "early_mean_race_centered", "recovery_mean_race_centered",
)
RACE_Z_FEATURES = SUMMARY_FEATURES + ("distance_m", "field_size")
RUNNER_KEYS = (
    "api_record_id", "race_id", "race_date", "year", "horse_id",
    "horse_number", "race_distance_m", "field_n", "finish_position",
)
RACE_KEYS = ("race_id", "race_date", "year", "race_distance_m", "field_n")
RUNNER_LABELS = ("label_early", "label_recovery")
RACE_LABEL = "label_z_early_pack_ge2"
EVAL_EXPECTED = {
    "races": 1779, "runners": 17412, "dates": 269,
    "years": {"2024": 637, "2025": 654, "2026": 488},
}
TOTAL_EXPECTED = {"races": 5206, "runners": 52155}
HISTORY_START = date(2017, 1, 1)
MAX_AGE_DAYS = 730


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def records_sha256(frame: pd.DataFrame, columns: tuple[str, ...], key_column: str) -> str:
    digest = hashlib.sha256()
    ordered = frame.sort_values(key_column, kind="stable")
    for row in ordered[list(columns)].itertuples(index=False, name=None):
        values = [value.item() if isinstance(value, np.generic) else value for value in row]
        payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        digest.update(payload)
        digest.update(b"\n")
    return digest.hexdigest()


def safe_project_file(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT.resolve()), f"source path escapes project: {path}")
    return resolved


def write_once(path: Path, payload: bytes) -> None:
    resolved = path.resolve(strict=False)
    require(resolved.is_relative_to(STUDY.resolve()), f"output path escapes study: {path}")
    require(not path.exists(), f"refusing to overwrite existing input/audit: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()


def write_json_once(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    write_once(path, (payload + "\n").encode("utf-8"))


def write_frame_once(path: Path, frame: pd.DataFrame) -> None:
    resolved = path.resolve(strict=False)
    require(resolved.is_relative_to(STUDY.resolve()), f"output path escapes study: {path}")
    require(not path.exists(), f"refusing to overwrite existing input/audit: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False, compression="zstd")
        stream.flush()


def parse_groups(value: Any) -> list[list[int]] | None:
    if not isinstance(value, str):
        return None
    text = value.replace(" ", "")
    if not re.fullmatch(r"[0-9(),^=≡\-]+", text):
        return None
    matches = list(re.finditer(r"\([^()]+\)|\^?\d+", text))
    groups: list[list[int]] = []
    end = 0
    for match in matches:
        if text[end:match.start()] and not re.fullmatch(r"[,=≡\-]+", text[end:match.start()]):
            return None
        token = match.group()
        if token.startswith("(") and not re.fullmatch(r"\(\^?\d+(?:,\^?\d+)*\)", token):
            return None
        groups.append([int(n) for n in re.findall(r"\d+", token)])
        end = match.end()
    if end != len(text) or not groups:
        return None
    return groups


def usable_groups(group_value: Any, status: Any, roster: set[int]) -> list[list[int]] | None:
    if status != "api_group_unreviewed":
        return None
    groups = parse_groups(group_value)
    if not groups:
        return None
    numbers = [n for group in groups for n in group]
    if len(numbers) != len(set(numbers)) or set(numbers) != roster:
        return None
    return groups


def synthetic_checks() -> list[str]:
    checks: list[str] = []
    target = date(2020, 1, 10)
    cutoff = target - timedelta(days=2)
    lower = target - timedelta(days=730)
    dates = ["2018-01-10", "2018-01-11", "2020-01-07", "2020-01-08", "2020-01-09"]
    selected = [x for x in dates if lower.isoformat() <= x <= cutoff.isoformat()]
    require("2020-01-08" in selected and "2020-01-09" not in selected, "T−2 cutoff synthetic check failed")
    require("2018-01-10" in selected and "2018-01-09" not in selected, "730-day inclusive bound failed")
    checks.append("730_day_and_T_minus_2_inclusive")
    require(math.isclose(2.0 ** (-365 / 365), 0.5), "half-life weight check failed")
    w = np.asarray([1.0, 0.5])
    x = np.asarray([1.0, -1.0])
    mean_unshrunk = float(np.sum(w * x) / np.sum(w))
    shrunk = (3.0 * 0.0 + float(np.sum(w * x))) / (3.0 + float(np.sum(w)))
    variance = float(np.sum(w * (x - mean_unshrunk) ** 2) / np.sum(w))
    require(math.isclose(shrunk, 1 / 9) and math.isclose(variance, 8 / 9), "weighted shrinkage/variance check failed")
    exact_shrunk = (3.0 * shrunk) / 3.0
    require(exact_shrunk - shrunk == 0.0, "no exact-distance support must give zero deviation")
    checks.append("half_life_prior_shrinkage_and_population_variance")
    require(usable_groups("(1,2)=3-4", "api_group_unreviewed", {1, 2, 3, 4}) == [[1, 2], [3], [4]],
            "group parser / exact roster check failed")
    require(usable_groups("(1,2)=3", "api_group_unreviewed", {1, 2, 3, 4}) is None,
            "group roster mismatch must remain unknown")
    require(usable_groups("(1,2)=3-4", "unresolved_official_internal_conflict", {1, 2, 3, 4}) is None,
            "held group status must remain unknown")
    checks.append("quality_status_parser_and_exact_roster")
    require(len(A_FEATURES) == 27 and len(RUNNER_PHASE_FEATURES) == 35 and len(RACE_Z_FEATURES) == 8,
            "feature cardinality contract failed")
    checks.append("27_35_8_feature_cardinality")
    return checks


def verify_hashes() -> dict[str, dict[str, Any]]:
    paths = {
        "source_snapshot.parquet": SNAPSHOT,
        "features.parquet": REFERENCE_FEATURES,
        "observations.parquet": OBSERVATIONS,
        "features_and_targets.parquet": LABEL_REFERENCE,
        "race_inclusion_ledger.csv": RACE_LEDGER,
        "horse_exclusions.json": EXCLUSION_FILE,
    }
    observed: dict[str, dict[str, Any]] = {}
    for name, raw_path in paths.items():
        path = safe_project_file(raw_path)
        digest = sha256(path)
        require(digest == SOURCE_EXPECTED[name], f"frozen source hash mismatch: {name}")
        observed[name] = {"path": path.relative_to(ROOT).as_posix(), "sha256": digest, "bytes": path.stat().st_size}
    require(SOURCE_MANIFEST.is_file(), "source manifest is missing")
    manifest_digest = sha256(safe_project_file(SOURCE_MANIFEST))
    return {"files": observed, "source_manifest_sha256": manifest_digest}


def audit_population(snapshot: pd.DataFrame, ledger: pd.DataFrame, features_meta: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    snapshot = snapshot.copy()
    snapshot["horse_id"] = snapshot["horse_id"].astype(str)
    snapshot["race_date"] = snapshot["race_date"].astype(str)
    snapshot["race_id"] = snapshot["race_id"].astype(str)
    snapshot["race_distance_m"] = pd.to_numeric(snapshot["race_distance_m"], errors="coerce")
    snapshot["finish_position"] = pd.to_numeric(snapshot["finish_position"], errors="coerce")
    snapshot["finish_time_seconds"] = pd.to_numeric(snapshot["finish_time_seconds"], errors="coerce")
    snapshot["horse_number"] = pd.to_numeric(snapshot["horse_number"], errors="coerce")
    snapshot["year"] = pd.to_numeric(snapshot["year"], errors="raise").astype(int)
    ledger["race_id"] = ledger["race_id"].astype(str)
    ledger["race_date"] = ledger["race_date"].astype(str)
    ledger["included"] = ledger["included"].map(lambda x: str(x).lower() == "true" if not isinstance(x, bool) else x)
    candidate = snapshot[snapshot.race_date.ge("2017-01-01")].copy()
    require(candidate.race_id.nunique() == 5901, "candidate race count differs from frozen source")
    require(set(candidate.race_id) == set(ledger.race_id), "2017+ source and inclusion-ledger race keys differ")
    require(not ledger.race_id.duplicated().any(), "duplicate inclusion-ledger race")
    lg = ledger.set_index("race_id")
    race_rows: list[dict[str, Any]] = []
    for race_id, group in candidate.groupby("race_id", sort=True):
        item = lg.loc[race_id]
        require(group.race_date.nunique() == 1 and group.year.nunique() == 1, "race date/year varies within race")
        require(len(group) == int(item.field_n), f"ledger field size mismatch: {race_id}")
        require(group.race_date.iloc[0] == item.race_date and int(group.year.iloc[0]) == int(item.year),
                f"ledger date/year mismatch: {race_id}")
        if pd.notna(item.distance_m):
            require(group.race_distance_m.notna().all()
                    and np.all(group.race_distance_m.to_numpy(dtype=float) == float(item.distance_m)),
                    f"ledger distance mismatch: {race_id}")
        if bool(item.included):
            n = len(group)
            raw_positions = group.finish_position.to_numpy(dtype=float)
            require(np.isfinite(raw_positions).all() and np.equal(raw_positions, np.floor(raw_positions)).all(),
                    f"included rank is not a finite integer: {race_id}")
            positions = sorted(raw_positions.astype(int).tolist())
            require(group.race_distance_m.isin(DISTANCES).all(), f"included unsupported distance: {race_id}")
            require(n >= 6 and positions == list(range(1, n + 1)), f"included race not normal unique complete rank: {race_id}")
            require(group.finish_time_seconds.gt(0).all(), f"included race has invalid finish time: {race_id}")
            require(group.rank_class_raw.nunique(dropna=False) == 1, f"included race has class conflict: {race_id}")
            require(group.horse_id.nunique() == n, f"included race has duplicate horse: {race_id}")
            require(group.horse_number.notna().all() and group.horse_number.gt(0).all()
                    and group.horse_number.nunique() == n, f"included race has invalid/duplicate number: {race_id}")
            horse_numbers = group.horse_number.to_numpy(dtype=float)
            require(np.equal(horse_numbers, np.floor(horse_numbers)).all(), f"included horse number is not integer: {race_id}")
            require(group.race_distance_m.nunique() == 1, f"included distance conflict: {race_id}")
        race_rows.append({
            "race_id": race_id,
            "race_date": item.race_date,
            "year": int(item.year),
            "distance_m": None if pd.isna(item.distance_m) else int(item.distance_m),
            "field_n": int(item.field_n),
            "included": bool(item.included),
            "reasons": "" if pd.isna(item.reasons) else str(item.reasons),
            "reason_basis": "frozen_10_08_ledger; partial_vs_stored_result requires original full-result reference",
        })
    strict_ids = set(ledger.loc[ledger.included, "race_id"])
    strict = snapshot[snapshot.race_id.isin(strict_ids)].copy()
    strict["race_distance_m"] = strict.race_distance_m.astype(int)
    field_sizes = ledger.set_index("race_id").field_n
    strict["field_n"] = strict.race_id.map(field_sizes).astype(int)
    strict = strict.sort_values(["race_date", "race_id", "horse_number", "api_record_id"]).reset_index(drop=True)
    require(strict.race_id.nunique() == 5206 and len(strict) == 52155, "strict cohort size mismatch")
    require(not strict.api_record_id.duplicated().any(), "strict api_record_id is not unique")
    feature_keys = features_meta.copy()
    feature_keys["race_id"] = feature_keys.race_id.astype(str)
    feature_keys["race_date"] = feature_keys.race_date.astype(str)
    feature_keys["horse_id"] = feature_keys.horse_id.astype(str)
    feature_keys["race_distance_m"] = pd.to_numeric(feature_keys.distance_m, errors="raise").astype(int)
    feature_keys["field_n"] = pd.to_numeric(feature_keys.field_n, errors="raise").astype(int)
    compare = ["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "finish_position", "race_distance_m", "field_n"]
    left = strict[compare].sort_values("api_record_id").reset_index(drop=True)
    right = feature_keys[compare].sort_values("api_record_id").reset_index(drop=True)
    for column in compare:
        if column in {"api_record_id", "horse_number", "finish_position", "race_distance_m", "field_n"}:
            left[column] = pd.to_numeric(left[column], errors="raise").astype("int64")
            right[column] = pd.to_numeric(right[column], errors="raise").astype("int64")
    require(left.equals(right), "strict raw-source keys differ from reference feature metadata")
    return strict, pd.DataFrame(race_rows), {
        "snapshot_rows": int(len(snapshot)),
        "snapshot_races": int(snapshot.race_id.nunique()),
        "source_min_date": str(snapshot.race_date.min()),
        "source_max_date": str(snapshot.race_date.max()),
        "candidate_2017_plus_races": int(len(ledger)),
        "candidate_2017_plus_rows": int(len(candidate)),
        "included_races": int(strict.race_id.nunique()),
        "included_rows": int(len(strict)),
        "excluded_2017_plus_races": int((~ledger.included).sum()),
        "pre_2017_races": {"value": 3593, "basis": "inferred from 9,494 total minus 5,901 2017+ ledger races; not direct recount"},
        "excluded_reason_counts": dict(Counter(reason for text in ledger.loc[~ledger.included, "reasons"].fillna("")
                                                 for reason in str(text).split("|") if reason)),
        "census_rows": race_rows,
    }


def construct_phase_labels(observations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    observations = observations.copy()
    observations["horse_id"] = observations.horse_id.astype(str)
    observations["race_id"] = observations.race_id.astype(str)
    observations["race_date"] = observations.race_date.astype(str)
    observations["race_distance_m"] = pd.to_numeric(observations.race_distance_m, errors="raise").astype(int)
    observations["horse_number"] = pd.to_numeric(observations.horse_number, errors="coerce")
    observations["finish_position"] = pd.to_numeric(observations.finish_position, errors="coerce")
    observations["finish_time_seconds"] = pd.to_numeric(observations.finish_time_seconds, errors="coerce")
    early: dict[int, float] = {}
    recovery: dict[int, float] = {}
    race_z: dict[str, float] = {}
    history: dict[int, dict[str, float]] = {}
    for race_id, group in observations.groupby("race_id", sort=False):
        nums = group.horse_number.to_numpy(dtype=float)
        field = pd.to_numeric(group.field_n, errors="coerce").to_numpy(dtype=float)
        roster_ok = (
            group.horse_id.notna().all()
            and group.horse_id.astype(str).nunique() == len(group)
            and np.isfinite(nums).all()
            and np.equal(nums, np.floor(nums)).all()
            and (nums > 0).all()
            and len(set(nums.astype(int))) == len(group)
            and np.isfinite(field).all()
            and np.equal(field, np.floor(field)).all()
            and len(set(field)) == 1
            and int(field[0]) == len(group)
        )
        numbers = set(nums.astype(int)) if roster_ok else set()
        s1f = usable_groups(group.s1f_group.iloc[0], group.s1f_group_status.iloc[0], numbers) if roster_ok else None
        g1f = usable_groups(group.g1f_group.iloc[0], group.g1f_group_status.iloc[0], numbers) if roster_ok else None
        if s1f is not None:
            first = set(s1f[0])
            race_z[str(race_id)] = float(len(first) >= 2)
            for row in group.itertuples():
                early[int(row.api_record_id)] = float(int(row.horse_number) in first)
        else:
            race_z[str(race_id)] = np.nan
            for rid in group.api_record_id:
                early[int(rid)] = np.nan
        if g1f is not None:
            rank = pd.to_numeric(group.g1f_order, errors="coerce")
            status = group.g1f_order_status.astype("string")
            valid = rank.between(1, pd.to_numeric(group.field_n, errors="coerce")) & ~status.str.contains(
                "conflict|unresolved|not_applied|source_changed", case=False, na=True
            )
            valid &= rank.mod(1).eq(0)
            valid &= group.finish_position.between(1, 89) & group.finish_position.mod(1).eq(0)
            for row, ok in zip(group.itertuples(), valid.to_numpy()):
                val = float(int(row.g1f_order) - int(row.finish_position) >= 2) if ok else np.nan
                recovery[int(row.api_record_id)] = val
        else:
            for rid in group.api_record_id:
                recovery[int(rid)] = np.nan
        # Historical channel values are retained by ID; target outcome labels
        # are later filtered to the strict normal-complete population.
        for row in group.itertuples():
            history[int(row.api_record_id)] = {
                "early": early[int(row.api_record_id)],
                "recovery": recovery[int(row.api_record_id)],
            }
    result = pd.DataFrame({
        "api_record_id": list(history),
        "early": [history[k]["early"] for k in history],
        "recovery": [history[k]["recovery"] for k in history],
    })
    z_labels = pd.DataFrame({"race_id": list(race_z), "label_z_early_pack_ge2": list(race_z.values())})
    return result, z_labels


def verify_observation_roster(snapshot: pd.DataFrame, observations: pd.DataFrame) -> dict[str, Any]:
    source = snapshot.copy()
    source["race_date"] = source.race_date.astype(str)
    source["horse_id"] = source.horse_id.astype(str)
    source["race_id"] = source.race_id.astype(str)
    source["race_distance_m"] = pd.to_numeric(source.race_distance_m, errors="coerce")
    source["horse_number"] = pd.to_numeric(source.horse_number, errors="coerce")
    source["finish_position"] = pd.to_numeric(source.finish_position, errors="coerce")
    started = source.finish_position.between(1, 89) | source.finish_position.isin([91, 92])
    expected = source[
        source.race_date.between("2017-01-01", "2026-09-19")
        & source.race_distance_m.isin(DISTANCES)
        & started
    ].copy()
    actual = observations.copy()
    actual["race_date"] = actual.race_date.astype(str)
    actual["horse_id"] = actual.horse_id.astype(str)
    actual["race_id"] = actual.race_id.astype(str)
    actual["race_distance_m"] = pd.to_numeric(actual.race_distance_m, errors="coerce")
    actual["horse_number"] = pd.to_numeric(actual.horse_number, errors="coerce")
    actual["finish_position"] = pd.to_numeric(actual.finish_position, errors="coerce")
    require(expected.api_record_id.is_unique and actual.api_record_id.is_unique, "duplicate observation/source ID")
    require(set(expected.api_record_id) == set(actual.api_record_id), "10/21 observation IDs differ from frozen 10/08 started roster")
    keys = ["api_record_id", "race_id", "race_date", "horse_id", "race_distance_m", "horse_number", "finish_position"]
    left = expected[keys].sort_values("api_record_id").reset_index(drop=True)
    right = actual[keys].sort_values("api_record_id").reset_index(drop=True)
    for column in ("api_record_id", "race_distance_m", "horse_number", "finish_position"):
        left[column] = pd.to_numeric(left[column], errors="raise").astype("int64")
        right[column] = pd.to_numeric(right[column], errors="raise").astype("int64")
    require(left.equals(right), "10/21 observation identity/roster columns differ from frozen 10/08 source")
    return {
        "status": "PASS",
        "rows": int(len(actual)),
        "races": int(actual.race_id.nunique()),
        "keys": keys,
        "source_roster_match": True,
    }


def verify_phase_sources(observations: pd.DataFrame, strict: pd.DataFrame, phase: pd.DataFrame,
                         z_labels: pd.DataFrame, label_reference: pd.DataFrame) -> dict[str, Any]:
    require(observations.api_record_id.is_unique, "phase observation IDs are not unique")
    require(len(observations) == 56618 and observations.race_id.nunique() == 5693, "phase observation cohort mismatch")
    strict_ids = set(strict.api_record_id.astype(int))
    observation_ids = set(observations.api_record_id.astype(int))
    require(strict_ids <= observation_ids and observation_ids == set(label_reference.api_record_id.astype(int)),
            "phase observations and label-only reference IDs differ")
    # Reconstruct labels over the entire history roster. Only strict-cohort
    # rows are later exposed as phase-head targets.
    labels = label_reference.set_index("api_record_id").loc[sorted(observation_ids)].reset_index()
    check = observations[["api_record_id", "finish_position", "race_id"]].merge(
        phase, on="api_record_id", how="left", validate="one_to_one"
    ).sort_values("api_record_id").reset_index(drop=True)
    require(check.early.isna().equals(labels.y_s1f.isna()), "S1F label knownness differs from audit reference")
    known_early = check.early.notna()
    require(np.array_equal(check.loc[known_early, "early"].to_numpy(float),
                           labels.loc[known_early.to_numpy(), "y_s1f"].eq(0).to_numpy(float)),
            "reconstructed early labels differ from y_s1f==0")
    require(check.recovery.isna().equals(labels.y_last200_recovery.isna()),
            "recovery label knownness differs from audit reference")
    known_recovery = check.recovery.notna()
    require(np.array_equal(check.loc[known_recovery, "recovery"].to_numpy(float),
                           labels.loc[known_recovery.to_numpy(), "y_last200_recovery"].to_numpy(float)),
            "reconstructed recovery labels differ from audit reference")
    z_map = z_labels.set_index("race_id").label_z_early_pack_ge2
    for rid, group in observations.groupby("race_id", sort=False):
        label = float(z_map.loc[rid])
        source = labels.loc[labels.api_record_id.isin(group.api_record_id), "y_count"]
        if math.isnan(label):
            require(source.isna().all(), f"Z unknownness differs for {rid}")
        else:
            require(source.notna().all() and bool((source.ge(1)).all()) == bool(label),
                    f"Z label differs from y_count for {rid}")
    strict_label_rows = check[check.api_record_id.isin(strict_ids)]
    strict_z = z_labels.set_index("race_id").loc[strict.race_id.unique(), "label_z_early_pack_ge2"]
    return {
        "phase_history_roster": {"races": int(observations.race_id.nunique()), "rows": int(len(observations))},
        "strict_target": {"races": int(strict.race_id.nunique()), "rows": int(len(strict))},
        "strict_label_support": {
            "early_known_rows": int(strict_label_rows.early.notna().sum()),
            "early_unknown_rows": int(strict_label_rows.early.isna().sum()),
            "recovery_known_rows": int(strict_label_rows.recovery.notna().sum()),
            "recovery_unknown_rows": int(strict_label_rows.recovery.isna().sum()),
            "z_known_races": int(strict_z.notna().sum()),
        },
        "history_source_label_reconstruction": {
            "rows_checked": int(len(check)),
            "races_checked": int(observations.race_id.nunique()),
            "early_known_rows": int(check.early.notna().sum()),
            "recovery_known_rows": int(check.recovery.notna().sum()),
            "z_known_races": int(z_labels.label_z_early_pack_ge2.notna().sum()),
        },
        "independent_label_reconstruction": "PASS against label-only y_s1f, y_last200_recovery, y_count",
        "existing_engineered_features_read": False,
    }


def channel_stats(values: np.ndarray, distances: np.ndarray, hist_dates: list[str],
                  target_date: date, target_distance: int, prior: float) -> tuple[dict[str, float], dict[str, Any]]:
    valid = np.isfinite(values)
    xv = values[valid]
    if not len(xv):
        return {
            "all_mean": np.nan,
            "exact_distance_deviation": np.nan,
            "all_weight_sum": 0.0,
            "exact_distance_weight_sum": 0.0,
            "all_weighted_variance": np.nan,
            "days_since_last_valid": np.nan,
        }, {"all_n": 0, "exact_n": 0, "latest": None}
    valid_dates = np.asarray(hist_dates, dtype=object)[valid]
    valid_dist = distances[valid]
    age_days = np.asarray([(target_date - date.fromisoformat(x)).days for x in valid_dates], dtype=np.float64)
    weights = np.power(2.0, -age_days / 365.0)
    sum_w = float(weights.sum())
    unshrunk = float(np.sum(weights * xv) / sum_w)
    global_mean = (3.0 * prior + float(np.sum(weights * xv))) / (3.0 + sum_w)
    variance = float(np.sum(weights * np.square(xv - unshrunk)) / sum_w) if len(xv) >= 2 else np.nan
    exact_mask = valid_dist == target_distance
    exact_w = weights[exact_mask]
    exact_x = xv[exact_mask]
    exact_sum = float(exact_w.sum())
    exact_mean = (3.0 * global_mean + float(np.sum(exact_w * exact_x))) / (3.0 + exact_sum) if len(exact_x) else global_mean
    latest = max(valid_dates.tolist())
    return {
        "all_mean": float(global_mean),
        "exact_distance_deviation": float(exact_mean - global_mean),
        "all_weight_sum": sum_w,
        "exact_distance_weight_sum": exact_sum,
        "all_weighted_variance": variance,
        "days_since_last_valid": float((target_date - date.fromisoformat(latest)).days),
    }, {"all_n": int(len(xv)), "exact_n": int(len(exact_x)), "latest": latest}


def build_history_features(strict: pd.DataFrame, snapshot: pd.DataFrame,
                           observations: pd.DataFrame, phase: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = snapshot.copy()
    base["horse_id"] = base.horse_id.astype(str)
    base["race_date"] = base.race_date.astype(str)
    base["race_id"] = base.race_id.astype(str)
    base["race_distance_m"] = pd.to_numeric(base.race_distance_m, errors="coerce")
    base["finish_position"] = pd.to_numeric(base.finish_position, errors="coerce")
    base["finish_time_seconds"] = pd.to_numeric(base.finish_time_seconds, errors="coerce")
    ledger_path = RACE_LEDGER
    ledger = pd.read_csv(ledger_path)
    strict_races = set(ledger.loc[ledger.included.astype(str).str.lower().eq("true"), "race_id"].astype(str))
    complete = base[base.race_id.isin(strict_races)].copy()
    complete["race_distance_m"] = complete.race_distance_m.astype(int)
    require(len(complete) == 52155, "history strict source row count mismatch")
    complete["race_rank"] = np.nan
    complete["race_margin"] = np.nan
    for race_id, group in complete.groupby("race_id", sort=False):
        n = len(group)
        ranks = group.finish_position.to_numpy(dtype=float)
        times = group.finish_time_seconds.to_numpy(dtype=float)
        require(np.isfinite(times).all() and (times > 0).all(), f"invalid historical complete times: {race_id}")
        require(np.isfinite(ranks).all() and np.equal(ranks, np.floor(ranks)).all(),
                f"historical rank is not an exact integer: {race_id}")
        require(sorted(ranks.astype(int).tolist()) == list(range(1, n + 1)), f"invalid historical complete ranks: {race_id}")
        rank_x = ndtri(1.0 - (ranks - 0.5) / n)
        median = float(np.median(times))
        margin_x = np.log(median / times)
        complete.loc[group.index, "race_rank"] = rank_x
        complete.loc[group.index, "race_margin"] = margin_x
    obs = observations.copy()
    obs["horse_id"] = obs.horse_id.astype(str)
    obs["race_date"] = obs.race_date.astype(str)
    obs["race_id"] = obs.race_id.astype(str)
    obs["race_distance_m"] = pd.to_numeric(obs.race_distance_m, errors="raise").astype(int)
    phase_map = phase.set_index("api_record_id")
    obs["early_x"] = obs.api_record_id.map(phase_map.early)
    obs["recovery_x"] = obs.api_record_id.map(phase_map.recovery)
    history = obs[["api_record_id", "race_id", "race_date", "horse_id", "race_distance_m", "early_x", "recovery_x"]].merge(
        complete[["api_record_id", "race_rank", "race_margin"]],
        on="api_record_id", how="left", validate="one_to_one"
    )
    history = history[history.race_date.ge("2017-01-01")].copy()
    require(history.api_record_id.is_unique and len(history) == 56618, "history event key mismatch")
    history = history.sort_values(["horse_id", "race_date", "race_id", "api_record_id"]).reset_index(drop=True)
    strict = strict.sort_values(["race_date", "race_id", "horse_number", "api_record_id"]).reset_index(drop=True)
    target_groups = {horse: frame for horse, frame in history.groupby("horse_id", sort=False)}
    output_rows: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    prior_by_channel = {"rank": 0.0, "margin": 0.0, "early": 0.5, "recovery": 0.5}
    hcols = {"rank": "race_rank", "margin": "race_margin", "early": "early_x", "recovery": "recovery_x"}
    for target in strict.itertuples():
        target_date = date.fromisoformat(str(target.race_date))
        lower = target_date - timedelta(days=MAX_AGE_DAYS)
        cutoff = target_date - timedelta(days=2)
        horse = str(target.horse_id)
        hist = target_groups.get(horse)
        if hist is None:
            selected = history.iloc[0:0]
        else:
            dates = hist.race_date.tolist()
            lo = bisect.bisect_left(dates, lower.isoformat())
            hi = bisect.bisect_right(dates, cutoff.isoformat())
            selected = hist.iloc[lo:hi]
        out: dict[str, Any] = {
            "api_record_id": int(target.api_record_id),
            "race_id": str(target.race_id),
            "race_date": str(target.race_date),
            "year": int(target.year),
            "horse_id": horse,
            "horse_number": int(target.horse_number),
            "race_distance_m": int(target.race_distance_m),
            "field_n": int(target.field_n),
            "finish_position": int(target.finish_position),
            "strict_cohort": True,
        }
        diag_base = {
            "api_record_id": int(target.api_record_id),
            "race_id": str(target.race_id),
            "history_start": HISTORY_START.isoformat(),
            "history_lower_inclusive": lower.isoformat(),
            "history_cutoff_inclusive": cutoff.isoformat(),
            "left_censored_at_2017_start": lower < HISTORY_START,
        }
        for channel in CHANNELS:
            vals = pd.to_numeric(selected[hcols[channel]], errors="coerce").to_numpy(dtype=float) if len(selected) else np.asarray([], dtype=float)
            dists = selected.race_distance_m.to_numpy(dtype=np.int64) if len(selected) else np.asarray([], dtype=np.int64)
            dates = selected.race_date.tolist() if len(selected) else []
            stats, diag = channel_stats(vals, dists, dates, target_date, int(target.race_distance_m), prior_by_channel[channel])
            for suffix, value in stats.items():
                out[f"{channel}_{suffix}"] = value
            lineage_rows.append({
                **diag_base,
                "channel": channel,
                "valid_observations_all_n": diag["all_n"],
                "valid_observations_exact_distance_n": diag["exact_n"],
                "latest_history_date": diag["latest"],
                "no_valid_history": diag["all_n"] == 0,
            })
        out["distance_m"] = int(target.race_distance_m)
        out["field_size"] = int(target.field_n)
        out["gate_scaled"] = float((int(target.horse_number) - 1) / (int(target.field_n) - 1))
        output_rows.append(out)
    runner = pd.DataFrame(output_rows)
    lineage = pd.DataFrame(lineage_rows)
    require(len(runner) == 52155 and len(lineage) == 4 * 52155, "history output size mismatch")
    return runner, lineage


def support_census(runner: pd.DataFrame, races: pd.DataFrame) -> dict[str, Any]:
    report: dict[str, Any] = {"cohort": "strict_normal_complete_5206", "folds": {}}
    for vintage in range(2019, 2027):
        train_year_max = vintage - 2
        cal_year = vintage - 1
        fold: dict[str, Any] = {
            "target_year": vintage,
            "train_max_year": train_year_max,
            "calibration_year": cal_year,
            "heads": {},
        }
        for head, frame, label in [
            ("early_runner", runner, "label_early"),
            ("recovery_runner", runner, "label_recovery"),
            ("early_pack_race", races, RACE_LABEL),
        ]:
            head_counts: dict[str, Any] = {}
            for part, mask in [
                ("train", frame.year.le(train_year_max)),
                ("calibration", frame.year.eq(cal_year)),
            ]:
                q = frame.loc[mask, ["race_id", label]].copy()
                q = q[q[label].notna()]
                positives = int(q[label].eq(1).sum())
                negatives = int(q[label].eq(0).sum())
                minimum = 50 if part == "train" else 10
                head_counts[part] = {
                    "known_rows": int(len(q)),
                    "known_races": int(q.race_id.nunique()),
                    "positive": positives,
                    "negative": negatives,
                    "minimum_each_class": minimum,
                    "support_pass": positives >= minimum and negatives >= minimum,
                }
            fold["heads"][head] = head_counts
        report["folds"][str(vintage)] = fold
    return report


def main() -> None:
    started = time.monotonic()
    checks = synthetic_checks()
    source_hashes = verify_hashes()
    snapshot_path = safe_project_file(SNAPSHOT)
    observation_path = safe_project_file(OBSERVATIONS)
    # Read only the frozen raw table, ID/label-only reference columns, and
    # source observations needed for quality labels/history. No DB is opened.
    snapshot = pd.read_parquet(snapshot_path)
    ledger = pd.read_csv(safe_project_file(RACE_LEDGER))
    feature_meta = pd.read_parquet(
        safe_project_file(REFERENCE_FEATURES),
        columns=["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "finish_position", "distance_m", "field_n"],
    )
    observations = pd.read_parquet(observation_path)
    label_reference = pd.read_parquet(
        safe_project_file(LABEL_REFERENCE),
        columns=["api_record_id", "y_s1f", "y_last200_recovery", "y_count"],
    )
    require(label_reference.api_record_id.is_unique, "label-only reference IDs are not unique")
    roster_review = verify_observation_roster(snapshot, observations)
    excluded = json.loads(safe_project_file(EXCLUSION_FILE).read_text(encoding="utf-8"))["horses"]
    forbidden_ids = {str(h) for h, v in excluded.items() if not v.get("reimport_allowed", False)}
    require(not (set(snapshot.horse_id.astype(str)) & forbidden_ids), "frozen snapshot contains an excluded horse")
    strict, census, cohort = audit_population(snapshot, ledger, feature_meta)
    phase, z_labels = construct_phase_labels(observations)
    phase_review = verify_phase_sources(observations, strict, phase, z_labels, label_reference)
    # The 10/21 observation roster is the history source only; target labels and
    # phase heads use the same strict cohort as the joint models.
    strict_ids = set(strict.api_record_id.astype(int))
    targets = strict[["api_record_id", "race_id", "race_date", "horse_id", "horse_number",
                      "race_distance_m", "finish_position"]].merge(
        phase, on="api_record_id", how="left", validate="one_to_one"
    )
    target_labels = targets[["api_record_id", "early", "recovery"]].rename(
        columns={"early": "label_early", "recovery": "label_recovery"}
    )
    runner, lineage = build_history_features(strict, snapshot, observations, phase)
    runner = runner.merge(target_labels, on="api_record_id", how="left", validate="one_to_one")
    runner["strict_cohort"] = True
    # Build one row per strict race and summarize historical phase means only.
    runner["early_mean_race_mean"] = runner.groupby("race_id", sort=False)["early_all_mean"].transform("mean")
    runner["early_mean_race_max"] = runner.groupby("race_id", sort=False)["early_all_mean"].transform("max")
    runner["early_mean_race_known_count"] = runner.groupby("race_id", sort=False)["early_all_mean"].transform("count").astype("int16")
    runner["recovery_mean_race_mean"] = runner.groupby("race_id", sort=False)["recovery_all_mean"].transform("mean")
    runner["recovery_mean_race_max"] = runner.groupby("race_id", sort=False)["recovery_all_mean"].transform("max")
    runner["recovery_mean_race_known_count"] = runner.groupby("race_id", sort=False)["recovery_all_mean"].transform("count").astype("int16")
    runner["early_mean_race_centered"] = runner.early_all_mean - runner.early_mean_race_mean
    runner["recovery_mean_race_centered"] = runner.recovery_all_mean - runner.recovery_mean_race_mean
    race = runner.groupby("race_id", sort=False).first().reset_index()
    race = race.merge(z_labels, on="race_id", how="left", validate="one_to_one")
    race["strict_cohort"] = True
    require(set(runner.race_id) == set(ledger.loc[ledger.included, "race_id"].astype(str)), "runner target race keys mismatch")
    require(set(race.race_id) == set(ledger.loc[ledger.included, "race_id"].astype(str)), "race input keys mismatch")
    # Exact 2024–2026 evaluation keys are bound to the source reference.
    eval_runner = runner[runner.year.ge(2024) & runner.race_date.le("2026-09-19")]
    eval_race = race[race.year.ge(2024) & race.race_date.le("2026-09-19")]
    eval_years = {str(k): int(v) for k, v in eval_race.groupby("year").race_id.nunique().items()}
    require(len(eval_runner) == 17412 and eval_race.race_id.nunique() == 1779, "evaluation cohort mismatch")
    require(eval_runner.race_date.nunique() == 269 and eval_years == EVAL_EXPECTED["years"], "evaluation year/date support mismatch")
    eval_key_receipt = {
        "reference_path": REFERENCE_FEATURES.relative_to(ROOT).as_posix(),
        "reference_sha256": source_hashes["files"]["features.parquet"]["sha256"],
        "runner_key_columns": ["api_record_id", "race_id", "race_date", "horse_id", "horse_number"],
        "runner_key_sha256": records_sha256(
            eval_runner,
            ("api_record_id", "race_id", "race_date", "horse_id", "horse_number"),
            "api_record_id",
        ),
        "race_key_columns": ["race_id", "race_date", "race_distance_m", "field_n"],
        "race_key_sha256": records_sha256(
            eval_race,
            ("race_id", "race_date", "race_distance_m", "field_n"),
            "race_id",
        ),
        "hash_encoding": "UTF-8 compact JSON array per row, rows sorted by first key column, LF after each row",
    }
    support = support_census(runner, race)
    elapsed = time.monotonic() - started
    source_manifest_sha = source_hashes["source_manifest_sha256"]
    input_files = {
        "model_inputs.parquet": runner[list(RUNNER_KEYS) + ["strict_cohort"] + list(A_FEATURES)
                                       + list(SUMMARY_FEATURES) + ["early_mean_race_centered", "recovery_mean_race_centered"]
                                       + list(RUNNER_LABELS)].copy(),
        "race_inputs.parquet": race[list(RACE_KEYS) + ["strict_cohort"] + list(RACE_Z_FEATURES) + [RACE_LABEL]].copy(),
        "history_lineage.parquet": lineage,
    }
    for filename, frame in input_files.items():
        if filename == "history_lineage.parquet":
            path = INPUTS / filename
        else:
            path = INPUTS / filename
        write_frame_once(path, frame)
    write_frame_once(AUDIT / "race_census.parquet", census)
    write_json_once(AUDIT / "phase_fold_support.json", support)
    write_json_once(AUDIT / "synthetic_checks.json", {
        "status": "PASS",
        "checks": checks,
        "executed_before_source_read": True,
        "fit_or_prediction": False,
    })
    file_meta: dict[str, Any] = {}
    for filename, frame in input_files.items():
        path = INPUTS / filename
        file_meta[filename] = {
            "path": filename,
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "rows": int(len(frame)),
            "races": int(frame.race_id.nunique()) if "race_id" in frame.columns else int(frame.api_record_id.nunique()),
            "columns": list(frame.columns),
        }
    eval_cohort = {
        "races": int(eval_race.race_id.nunique()),
        "runners": int(len(eval_runner)),
        "dates": int(eval_runner.race_date.nunique()),
        "years": eval_years,
    }
    known_counts = {
        "early": {"known": int(runner.label_early.notna().sum()), "unknown": int(runner.label_early.isna().sum())},
        "recovery": {"known": int(runner.label_recovery.notna().sum()), "unknown": int(runner.label_recovery.isna().sum())},
        "z": {"known": int(race[RACE_LABEL].notna().sum()), "unknown": int(race[RACE_LABEL].isna().sum())},
    }
    manifest = {
        "status": "PASS",
        "study": "20261022_dynamic_ability_pace_v1",
        "contract": "supervisor/DESIGN_CONTRACT.md",
        "contract_sha256": sha256(CONTRACT),
        "source_manifest_sha256": source_manifest_sha,
        "source_hashes": source_hashes["files"],
        "builder_sha256": sha256(Path(__file__).resolve()),
        "files": file_meta,
        "a_features": list(A_FEATURES),
        "runner_phase_features": list(RUNNER_PHASE_FEATURES),
        "race_z_features": list(RACE_Z_FEATURES),
        "runner_key_columns": list(RUNNER_KEYS) + ["strict_cohort"],
        "race_key_columns": list(RACE_KEYS) + ["strict_cohort"],
        "runner_labels": list(RUNNER_LABELS),
        "race_label": RACE_LABEL,
        "normal_complete_cohort": TOTAL_EXPECTED,
        "eval_cohort": {"races": eval_cohort["races"], "runners": eval_cohort["runners"],
                        "dates": eval_cohort["dates"], "plc_races": 1743, "plc_unknown": 36},
        "eval_year_races": eval_cohort["years"],
        "history_start": "2017-01-01",
        "history_max_age_days": 730,
        "history_cutoff": "race_date_minus_2_calendar_days_inclusive",
        "same_day_updates": False,
        "publication_time_verified": False,
        "strict_target_population_only": True,
        "wider_history_source": {"races": 5693, "rows": 56618, "strict_cohort": False},
        "label_availability": known_counts,
        "phase_fold_support_path": "../audit/phase_fold_support.json",
        "support_minimums": {"train_each_class": 50, "calibration_each_class": 10},
        "cohort_audit": {k: v for k, v in cohort.items() if k != "census_rows"},
        "phase_source_review": phase_review,
        "observation_roster_review": roster_review,
        "evaluation_key_receipt": eval_key_receipt,
        "synthetic_checks": checks,
        "elapsed_seconds": round(elapsed, 3),
        "training_or_evaluation_performed": False,
        "database_opened": False,
    }
    write_json_once(INPUTS / "input_manifest.json", manifest)
    write_json_once(AUDIT / "input_verification.json", {
        "status": "PASS",
        "strict_cohort": TOTAL_EXPECTED,
        "eval_cohort": eval_cohort,
        "feature_counts": {"A": len(A_FEATURES), "runner_phase": len(RUNNER_PHASE_FEATURES), "race_Z": len(RACE_Z_FEATURES)},
        "phase_label_reconstruction": phase_review,
        "observation_roster_review": roster_review,
        "evaluation_key_receipt": eval_key_receipt,
        "elapsed_seconds": round(elapsed, 3),
        "training_or_evaluation_performed": False,
    })
    print(json.dumps({
        "status": "PASS",
        "inputs": {name: {"sha256": meta["sha256"], "bytes": meta["bytes"], "rows": meta["rows"], "races": meta["races"]}
                   for name, meta in file_meta.items()},
        "eval_cohort": eval_cohort,
        "labels": known_counts,
        "elapsed_seconds": round(elapsed, 3),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit("prepare.py has no runtime options; all source and output paths are fixed")
    main()

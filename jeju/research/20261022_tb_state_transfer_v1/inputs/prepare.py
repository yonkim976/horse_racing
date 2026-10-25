"""Build the frozen Jeju rank/distance-state inputs; never fits or scores a model."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.special import expit


ROOT = Path(__file__).resolve().parents[4]
STUDY = ROOT / "jeju/research/20261022_tb_state_transfer_v1"
INPUTS = STUDY / "inputs"
AUDIT = STUDY / "audit"
CONTRACT = STUDY / "supervisor/DESIGN_CONTRACT.md"
TB_STATE = ROOT / "thoroughbred/research/20261022_dynamic_race_model_v1/state.py"
SOURCE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
F1_TARGET = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
ELIGIBILITY = AUDIT / "history_eligibility.parquet"
EXCLUSIONS = ROOT / "jeju/data/horse_exclusions.json"
SOURCE_MANIFEST = AUDIT / "source_manifest.json"
VERIFY_STATES = STUDY / "supervisor/verify_states.py"

TARGET_COLUMNS = ["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "distance_m", "field_n"]
SOURCE_COLUMNS = ["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "race_distance_m",
                  "finish_position", "finish_time_seconds", "started", "valid_time"]
SUPPORTED_DISTANCES = {800, 900, 1000, 1110, 1200, 1300, 1400, 1610}
STATE_COLUMNS = [
    "state_rank_mean", "state_rank_sd", "state_distance_slope", "state_distance_sd",
    "state_rank_current", "state_rank_current_sd", "state_rank_n",
    "state_days_since_rank_observation", "state_rank_current_field_gap",
    "state_rank_current_field_rank",
]
KEY_COLUMNS = ["api_record_id", "race_id", "race_date", "cutoff", "historydate"]
OUTPUT_FILES = ["state_features.parquet", "state_lineage.parquet", "input_manifest.json", "synthetic_checks.json"]


@dataclass
class RankState:
    mean: np.ndarray
    cov: np.ndarray
    n: int = 0
    last_date: date | None = None
    last_race_id: str | None = None

    @classmethod
    def prior(cls) -> "RankState":
        return cls(np.zeros(2, dtype=float), np.diag([2.0, 0.5]).astype(float), 0, None, None)

    def clone(self) -> "RankState":
        return RankState(self.mean.copy(), self.cov.copy(), int(self.n), self.last_date, self.last_race_id)


def digest(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": h.hexdigest()}


def manifest_pins() -> dict[str, dict]:
    """Check source hashes from the frozen audit manifest before opening data inputs."""
    manifest = json.loads(SOURCE_MANIFEST.read_text())
    refs = manifest.get("sources", {})
    ledger = manifest.get("history_eligibility_ledger", {})
    mapping = {
        SOURCE: refs.get(str(SOURCE.relative_to(ROOT))),
        F1_TARGET: refs.get(str(F1_TARGET.relative_to(ROOT))),
        EXCLUSIONS: refs.get(str(EXCLUSIONS.relative_to(ROOT))),
        TB_STATE: refs.get(str(TB_STATE.relative_to(ROOT))),
        CONTRACT: refs.get(str(CONTRACT.relative_to(ROOT))),
        VERIFY_STATES: refs.get(str(VERIFY_STATES.relative_to(ROOT))),
        ELIGIBILITY: ledger,
    }
    pins = {}
    for path, expected in mapping.items():
        if not isinstance(expected, dict) or "sha256" not in expected or "bytes" not in expected:
            raise ValueError(f"source manifest has no pinned hash/size for {path.relative_to(ROOT)}")
        if expected.get("path") and expected["path"] != str(path.relative_to(ROOT)):
            raise ValueError(f"source manifest path mismatch for {path.relative_to(ROOT)}")
        actual = digest(path)
        if actual["sha256"] != expected["sha256"] or actual["bytes"] != expected["bytes"]:
            raise ValueError(f"source manifest hash/size mismatch before read: {path.relative_to(ROOT)}")
        pins[str(path)] = actual
    pins[str(SOURCE_MANIFEST)] = digest(SOURCE_MANIFEST)
    return pins


def assert_pins_unchanged(pins: dict[str, dict]) -> None:
    for path_text, expected in pins.items():
        actual = digest(Path(path_text))
        if actual["sha256"] != expected["sha256"] or actual["bytes"] != expected["bytes"]:
            raise ValueError(f"source changed during input generation: {expected['path']}")


def require_nonblank_ids(series: pd.Series, label: str) -> pd.Series:
    if series.isna().any():
        raise ValueError(f"null {label} values")
    raw = series.tolist()
    normalized = [str(value) for value in raw]
    if any(not value.strip() or value != value.strip() for value in normalized):
        raise ValueError(f"blank or whitespace-padded {label} values")
    raw_tokens = [f"{type(value).__name__}:{value!r}" for value in raw]
    reverse: dict[str, set[str]] = defaultdict(set)
    for norm, token in zip(normalized, raw_tokens):
        reverse[norm].add(token)
    collisions = [key for key, tokens in reverse.items() if len(tokens) > 1]
    if collisions:
        raise ValueError(f"normalization collision in {label}: {collisions[:3]}")
    return pd.Series(normalized, index=series.index, dtype="string")


def exact_integer_series(series: pd.Series, label: str) -> pd.Series:
    """Reject missing, non-finite, fractional, or out-of-range values before integer casting."""
    if series.isna().any():
        raise ValueError(f"null {label} values")
    converted = []
    for value in series.tolist():
        number = float(value)
        if not math.isfinite(number) or number != math.floor(number) or abs(number) > 2**53:
            raise ValueError(f"non-exact integer {label}: {value!r}")
        converted.append(int(number))
    return pd.Series(converted, index=series.index, dtype="int64")


def json_scalar(value):
    if pd.isna(value):
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        out = float(value)
        if not math.isfinite(out):
            return None
        return out
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    return str(value)


def canonical_source_row_hashes(snapshot: pd.DataFrame) -> dict[str, str]:
    """Canonical hash: SOURCE_COLUMNS order, API-ID stable sort, compact UTF-8 JSONL."""
    hashes: dict[str, str] = {}
    for race_id, group in snapshot.groupby("race_id", sort=False, dropna=False):
        if pd.isna(race_id):
            raise ValueError("null race_id prevents canonical row digest")
        group = group.sort_values(["api_record_id", "horse_number", "horse_id"], kind="mergesort", na_position="last")
        h = hashlib.sha256()
        for row in group[SOURCE_COLUMNS].itertuples(index=False, name=None):
            payload = json.dumps([json_scalar(value) for value in row], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            h.update(payload.encode("utf-8"))
            h.update(b"\n")
        hashes[str(race_id)] = h.hexdigest()
    return hashes


def date_value(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return pd.Timestamp(value).date()


def propagate(state: RankState, query_date: date) -> tuple[RankState, float]:
    """Pure query-time propagation; stored state is never mutated."""
    out = state.clone()
    days = 0 if out.last_date is None else (query_date - out.last_date).days
    if days < 0:
        raise ValueError(f"query precedes last observation: {query_date} < {out.last_date}")
    dt = min(days / 30.0, 24.0)
    decay = math.exp(-days / 1500.0)
    out.mean *= decay
    out.cov = out.cov * (decay ** 2) + np.diag([0.035, 0.008]) * dt
    out.cov[0, 0] = min(out.cov[0, 0], 2.0)
    out.cov[1, 1] = min(out.cov[1, 1], 0.5)
    out.cov = (out.cov + out.cov.T) / 2.0
    validate_cov(out.cov)
    return out, float(days)


def validate_cov(cov: np.ndarray) -> None:
    if cov.shape != (2, 2) or not np.isfinite(cov).all():
        raise ValueError("rank covariance is not a finite 2x2 matrix")
    if not np.allclose(cov, cov.T, atol=1e-10, rtol=0):
        raise ValueError("rank covariance is asymmetric")
    if float(np.linalg.eigvalsh(cov).min()) < -1e-9:
        raise ValueError("rank covariance is not positive semidefinite")


def validate_event_frame(frame: pd.DataFrame) -> None:
    if frame.empty:
        raise ValueError("empty historical event")
    for key in ("horse_id", "horse_number", "api_record_id"):
        if frame[key].isna().any() or frame[key].duplicated().any():
            raise ValueError(f"invalid/duplicate {key} in event {frame.race_id.iloc[0]}")
    ids = frame.horse_id.astype(str)
    if ids.duplicated().any():
        raise ValueError(f"duplicate horse ID in event {frame.race_id.iloc[0]}")
    nums = pd.to_numeric(frame.horse_number, errors="raise").to_numpy(float)
    if not np.isfinite(nums).all() or not np.equal(nums, np.floor(nums)).all() or len(set(nums)) != len(frame):
        raise ValueError(f"invalid horse numbers in event {frame.race_id.iloc[0]}")
    ranks = pd.to_numeric(frame.finish_position, errors="raise").to_numpy(float)
    if not np.isfinite(ranks).all() or not np.equal(ranks, np.floor(ranks)).all():
        raise ValueError(f"non-integer historical ranks in event {frame.race_id.iloc[0]}")
    if sorted(ranks.astype(int).tolist()) != list(range(1, len(frame) + 1)):
        raise ValueError(f"rank is not exact 1..N in event {frame.race_id.iloc[0]}")
    if len(frame) < 4:
        raise ValueError(f"fewer than four runners in event {frame.race_id.iloc[0]}")
    if not frame.started.eq(True).all() or not frame.valid_time.eq(True).all():
        raise ValueError(f"non-normal or invalid-time runner in event {frame.race_id.iloc[0]}")
    times = pd.to_numeric(frame.finish_time_seconds, errors="raise").to_numpy(float)
    if not np.isfinite(times).all() or (times <= 0).any():
        raise ValueError(f"invalid finish time in event {frame.race_id.iloc[0]}")
    distances = pd.to_numeric(frame.race_distance_m, errors="raise").to_numpy(float)
    if not np.isfinite(distances).all() or not np.equal(distances, distances[0]).all():
        raise ValueError(f"inconsistent distance in event {frame.race_id.iloc[0]}")
    if distances[0] not in SUPPORTED_DISTANCES:
        raise ValueError(f"unsupported distance in event {frame.race_id.iloc[0]}: {distances[0]}")


def race_updates(event: pd.DataFrame, snapshots: dict[str, RankState], event_date: date) -> dict[str, RankState]:
    """Calculate each runner update from the same pre-race opponent snapshots."""
    event = event.sort_values("horse_id", kind="mergesort").reset_index(drop=True)
    validate_event_frame(event)
    h = np.array([1.0, (float(event.race_distance_m.iloc[0]) - 1100.0) / 500.0])
    horses = event.horse_id.astype(str).tolist()
    prior_states = [propagate(snapshots.get(horse, RankState.prior()), event_date)[0] for horse in horses]
    ranks = event.finish_position.to_numpy(dtype=float)
    mus = np.array([float(h @ s.mean) for s in prior_states])
    variances = np.array([float(h @ s.cov @ h) for s in prior_states])
    updated: dict[str, RankState] = {}
    for i, horse in enumerate(horses):
        rival_ix = [j for j in range(len(horses)) if j != i]
        # Sorted horse IDs make the floating-point reduction deterministic under row permutations.
        vj = variances[rival_ix]
        c = 1.0 / np.sqrt(1.0 + np.pi * (variances[i] + vj) / 8.0)
        p = expit((mus[i] - mus[rival_ix]) * c)
        y = (ranks[i] < ranks[rival_ix]).astype(float)
        grad = 4.0 * float(np.mean((y - p) * c))
        curvature = 4.0 * float(np.mean(p * (1.0 - p) * c ** 2))
        state = prior_states[i]
        precision = np.linalg.inv(state.cov) + curvature * np.outer(h, h)
        cov_new = np.linalg.inv(precision)
        cov_new = (cov_new + cov_new.T) / 2.0
        mean_new = state.mean + cov_new @ h * grad
        validate_cov(cov_new)
        if not np.isfinite(mean_new).all():
            raise ValueError("rank update produced non-finite mean")
        updated[horse] = RankState(mean_new, cov_new, state.n + 1, event_date, str(event.race_id.iloc[0]))
    return updated


def process_day(day_events: list[pd.DataFrame], states: dict[str, RankState], event_date: date) -> None:
    """Use pre-day snapshots for every race, then commit every horse together."""
    seen: set[str] = set()
    staged: dict[str, RankState] = {}
    for event in sorted(day_events, key=lambda e: str(e.race_id.iloc[0])):
        event = event.sort_values("horse_id", kind="mergesort").reset_index(drop=True)
        validate_event_frame(event)
        horses = event.horse_id.astype(str).tolist()
        overlap = seen.intersection(horses)
        if overlap:
            raise ValueError(f"same horse in multiple eligible races on {event_date}: {sorted(overlap)[:3]}")
        seen.update(horses)
        staged.update(race_updates(event, states, event_date))
    states.update(staged)


def query_features(state: RankState | None, query_date: date, distance_m: float) -> tuple[list[float], str | None]:
    stored = state if state is not None else RankState.prior()
    s, days = propagate(stored, query_date)
    h = np.array([1.0, (float(distance_m) - 1100.0) / 500.0])
    var = float(h @ s.cov @ h)
    if var < -1e-9 or not np.isfinite(var):
        raise ValueError("invalid current-distance rank variance")
    values = [s.mean[0], math.sqrt(s.cov[0, 0]), s.mean[1], math.sqrt(s.cov[1, 1]),
              float(h @ s.mean), math.sqrt(max(0.0, var)), int(s.n),
              float(days) if s.last_date is not None else float("nan")]
    if not np.isfinite(np.asarray(values[:7], dtype=float)).all():
        raise ValueError("state feature is non-finite")
    return values, s.last_race_id


def load_sources() -> tuple[pd.DataFrame, dict[date, list[pd.DataFrame]], dict]:
    ledger = pd.read_parquet(ELIGIBILITY)
    ledger["race_id"] = require_nonblank_ids(ledger.race_id, "ledger race_id")
    ledger["race_date"] = pd.to_datetime(ledger.race_date, errors="raise").dt.date
    ledger["source_rows"] = exact_integer_series(ledger.source_rows, "ledger source_rows")
    ledger["snapshot_rank_time_eligible"] = ledger.snapshot_rank_time_eligible.astype(str).str.lower().eq("true")
    ledger["db_full_roster_exact"] = ledger.db_full_roster_exact.astype(str).str.lower().eq("true")
    ledger["history_update_eligible"] = ledger.history_update_eligible.astype(str).str.lower().eq("true")
    if ledger.race_id.duplicated().any():
        raise ValueError("ledger race IDs are duplicated")
    if len(ledger) != 8431:
        raise ValueError(f"ledger candidate count drift: {len(ledger)}")
    eligible = ledger[ledger.history_update_eligible].copy()
    if len(eligible) != 7066 or eligible.race_id.nunique() != 7066:
        raise ValueError(f"eligible ledger count drift: {len(eligible)}")
    if not eligible.db_full_roster_exact.all():
        raise ValueError("eligible ledger contains a race without full-roster DB confirmation")

    snapshot = pq.read_table(SOURCE, columns=SOURCE_COLUMNS).to_pandas()
    snapshot["race_date"] = pd.to_datetime(snapshot.race_date, errors="raise").dt.date
    candidate = snapshot[[d >= date(2010, 1, 1) for d in snapshot.race_date]].copy()
    candidate["race_id"] = require_nonblank_ids(candidate.race_id, "source race_id")
    if set(candidate.race_id) != set(ledger.race_id):
        raise ValueError("2010+ source race IDs differ from the audited ledger IDs")
    if candidate.race_date.isna().any():
        raise ValueError("source race_date is missing")

    # Bind every ledger row to its frozen source rows. The canonical hash schema is
    # documented in audit/SOURCE_AUDIT.md; the non-hash ledger cells are preserved.
    row_hashes = canonical_source_row_hashes(candidate)
    if set(row_hashes) != set(ledger.race_id):
        raise ValueError("canonical source-row digest race key set differs from ledger")
    expected_hash = ledger.set_index("race_id").source_rows_sha256.astype(str).to_dict()
    hash_mismatches = [rid for rid, value in row_hashes.items() if expected_hash.get(rid) != value]
    if hash_mismatches:
        raise ValueError(f"ledger source-row hash mismatch for {len(hash_mismatches)} race(s); first={hash_mismatches[:3]}")
    got_counts = candidate.groupby("race_id", sort=False).size().to_dict()
    ledger_counts_all = ledger.set_index("race_id").source_rows.to_dict()
    if ledger_counts_all != got_counts:
        raise ValueError("ledger row counts differ from current source snapshot")
    ledger_dates = ledger.set_index("race_id").race_date.to_dict()
    for race_id, group in candidate.groupby("race_id", sort=False):
        if group.race_date.nunique(dropna=False) != 1 or group.race_date.iloc[0] != ledger_dates[str(race_id)]:
            raise ValueError(f"ledger/source race_date mismatch for {race_id}")
    ledger_distance = ledger.set_index("race_id").distance_m
    for race_id, group in candidate.groupby("race_id", sort=False):
        distance = pd.to_numeric(group.race_distance_m, errors="coerce").to_numpy(float)
        recorded = pd.to_numeric(pd.Series([ledger_distance.loc[str(race_id)]]), errors="coerce").iloc[0]
        if len(distance) and np.isfinite(distance).all() and np.equal(distance, distance[0]).all() and np.isfinite(recorded):
            if float(distance[0]) != float(recorded):
                raise ValueError(f"ledger/source race_distance mismatch for {race_id}")

    source = candidate[candidate.race_id.isin(set(eligible.race_id))].copy()
    source["horse_id"] = require_nonblank_ids(source.horse_id, "source horse_id")
    source["api_record_id"] = exact_integer_series(source.api_record_id, "source api_record_id")
    source["horse_number"] = exact_integer_series(source.horse_number, "source horse_number")
    if source.api_record_id.duplicated().any():
        raise ValueError("historical API record IDs are duplicated")
    if source.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("historical race contains duplicate horse IDs")
    if len(source) != 69752 or source.race_id.nunique() != 7066:
        raise ValueError(f"eligible source row/race count drift: {len(source)}/{source.race_id.nunique()}")
    eligible_counts = eligible.set_index("race_id").source_rows.to_dict()
    eligible_got_counts = source.groupby("race_id", sort=False).size().to_dict()
    if eligible_counts != eligible_got_counts:
        raise ValueError("eligible ledger row counts differ from current source snapshot")

    exclusions = json.loads(EXCLUSIONS.read_text())
    excluded_ids = {str(horse_id) for horse_id in exclusions.get("horses", {})}
    if source.horse_id.isin(excluded_ids).any():
        raise ValueError("excluded horse appears in eligible history; fail closed")

    by_date: dict[date, list[pd.DataFrame]] = defaultdict(list)
    for (event_date, race_id), g in source.groupby(["race_date", "race_id"], sort=True):
        validate_event_frame(g)
        ledger_distance = float(eligible.loc[eligible.race_id.astype(str).eq(str(race_id)), "distance_m"].iloc[0])
        if float(g.race_distance_m.iloc[0]) != ledger_distance:
            raise ValueError(f"ledger/source distance differs for {race_id}")
        by_date[event_date].append(g.copy())
    for event_date, day_events in by_date.items():
        horse_counts: dict[str, int] = defaultdict(int)
        for event in day_events:
            for horse_id in event.horse_id.astype(str):
                horse_counts[horse_id] += 1
        duplicates = [horse_id for horse_id, n in horse_counts.items() if n > 1]
        if duplicates:
            raise ValueError(f"same horse in multiple eligible races on {event_date}: {duplicates[:3]}")

    target = pq.read_table(F1_TARGET, columns=TARGET_COLUMNS).to_pandas()
    target["race_id"] = require_nonblank_ids(target.race_id, "target race_id")
    target["horse_id"] = require_nonblank_ids(target.horse_id, "target horse_id")
    target["api_record_id"] = exact_integer_series(target.api_record_id, "target api_record_id")
    target["horse_number"] = exact_integer_series(target.horse_number, "target horse_number")
    target["field_n"] = exact_integer_series(target.field_n, "target field_n")
    target["race_date"] = pd.to_datetime(target.race_date, errors="raise").dt.date
    if len(target) != 52155 or target.api_record_id.isna().any() or target.api_record_id.duplicated().any():
        raise ValueError("F1 target key-row count or API key uniqueness drift")
    if target.duplicated(["race_id", "horse_id"]).any():
        raise ValueError("F1 target duplicate runner within race")
    if target.race_id.nunique() != 5206:
        raise ValueError("F1 target race count drift")
    for race_id, g in target.groupby("race_id", sort=False):
        nums = g.horse_number.to_numpy(dtype=np.int64)
        if len(set(nums)) != len(g):
            raise ValueError(f"invalid target horse numbers in {race_id}")
        if int(g.field_n.iloc[0]) != len(g) or not g.field_n.eq(len(g)).all():
            raise ValueError(f"target field_n does not equal row count in {race_id}")
        d = pd.to_numeric(g.distance_m, errors="raise").to_numpy(float)
        if not np.isfinite(d).all() or not np.equal(d, d[0]).all() or d[0] not in SUPPORTED_DISTANCES:
            raise ValueError(f"invalid target distance in {race_id}")
    target_ledger_2017 = set(eligible.loc[eligible.race_date >= date(2017, 1, 1), "race_id"].astype(str))
    if set(target.race_id) != target_ledger_2017 or len(set(target.race_id)) != 5206:
        raise ValueError("target cohort does not exactly match eligible 2017+ history races")
    source_by_race = {str(race_id): g for (event_date, race_id), g in source.groupby(["race_date", "race_id"], sort=False)}
    for race_id, g in target.groupby("race_id", sort=False):
        raw = source_by_race.get(str(race_id))
        if raw is None or len(raw) != len(g):
            raise ValueError(f"target/source roster row count mismatch in {race_id}")
        target_keys = set(zip(g.api_record_id.to_numpy(dtype=np.int64), g.horse_id.astype(str), g.horse_number.to_numpy(dtype=np.int64)))
        source_keys = set(zip(raw.api_record_id.to_numpy(dtype=np.int64), raw.horse_id.astype(str), raw.horse_number.to_numpy(dtype=np.int64)))
        if target_keys != source_keys:
            raise ValueError(f"target/source API/horse roster mismatch in {race_id}")
        if g.race_date.nunique() != 1 or raw.race_date.nunique() != 1 or g.race_date.iloc[0] != raw.race_date.iloc[0]:
            raise ValueError(f"target/source race_date mismatch in {race_id}")
        if g.race_date.iloc[0] != ledger_dates[str(race_id)]:
            raise ValueError(f"target/ledger race_date mismatch in {race_id}")
        if float(g.distance_m.iloc[0]) != float(raw.race_distance_m.iloc[0]):
            raise ValueError(f"target/source distance mismatch in {race_id}")
    if target.race_date.min() < date(2017, 1, 1) or target.race_date.max() > date(2026, 9, 19):
        raise ValueError("target date range outside frozen contract")

    # Exact frozen year and evaluation census, without reading target labels.
    target["year"] = pd.Series([d.year for d in target.race_date], index=target.index)
    eval_rows = target[target.race_date >= date(2024, 1, 1)]
    if (len(eval_rows), eval_rows.race_id.nunique(), eval_rows.race_date.nunique()) != (17412, 1779, 269):
        raise ValueError("frozen common evaluation cohort count drift")
    source_races = source.drop_duplicates("race_id")
    warmup = source_races[source_races.race_date < date(2017, 1, 1)]
    training = source_races[source_races.race_date >= date(2017, 1, 1)]
    if (len(warmup), len(source[source.race_date < date(2017, 1, 1)])) != (1860, 17597):
        raise ValueError("warm-up cohort count drift")
    if (len(training), len(source[source.race_date >= date(2017, 1, 1)])) != (5206, 52155):
        raise ValueError("2017+ historical source cohort count drift")
    census = {
        "historical_eligible_all": {"races": 7066, "rows": 69752, "date_min": str(source.race_date.min()), "date_max": str(source.race_date.max())},
        "warmup_2010_2016": {"races": 1860, "rows": 17597},
        "target_2017_plus": {"races": 5206, "rows": 52155},
        "common_eval_2024_2026_09_19": {"races": 1779, "rows": 17412, "days": 269, "plc_races": 1743},
    }
    return target.sort_values(["race_date", "race_id", "horse_id"], kind="mergesort").reset_index(drop=True), dict(by_date), census


def build_features(target: pd.DataFrame, by_date: dict[date, list[pd.DataFrame]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    states: dict[str, RankState] = {}
    event_dates = sorted(by_date)
    cursor = 0
    output_rows: list[dict] = []
    lineage_rows: list[dict] = []
    target = target.copy()
    target["cutoff"] = [d - timedelta(days=2) for d in target.race_date]
    for cutoff, group in target.groupby("cutoff", sort=True):
        while cursor < len(event_dates) and event_dates[cursor] <= cutoff:
            event_date = event_dates[cursor]
            process_day(by_date[event_date], states, event_date)
            cursor += 1
        group_rows: list[dict] = []
        for row in group.itertuples(index=False):
            values, latest_race = query_features(states.get(str(row.horse_id)), cutoff, float(row.distance_m))
            s = states.get(str(row.horse_id))
            historydate = s.last_date if s is not None else None
            base = {
                "api_record_id": int(row.api_record_id), "race_id": str(row.race_id),
                "race_date": row.race_date, "cutoff": cutoff, "historydate": historydate,
            }
            base.update(dict(zip(STATE_COLUMNS[:8], values)))
            base["state_rank_current_field_gap"] = np.nan
            base["state_rank_current_field_rank"] = np.nan
            group_rows.append(base)
            lineage_rows.append({
                "api_record_id": int(row.api_record_id), "race_id": str(row.race_id),
                "horse_id": str(row.horse_id), "cutoff": cutoff, "historydate": historydate,
                "latest_history_race_id": latest_race, "history_update_count": int(s.n) if s is not None else 0,
            })
        part = pd.DataFrame(group_rows)
        for race_id, ix in part.groupby("race_id", sort=False).groups.items():
            scores = part.loc[ix, "state_rank_current"].astype(float)
            part.loc[ix, "state_rank_current_field_gap"] = scores - scores.mean()
            part.loc[ix, "state_rank_current_field_rank"] = scores.rank(method="average", pct=True, ascending=True)
        output_rows.extend(part.to_dict(orient="records"))
    features = pd.DataFrame(output_rows, columns=KEY_COLUMNS + STATE_COLUMNS)
    lineage = pd.DataFrame(lineage_rows, columns=["api_record_id", "race_id", "horse_id", "cutoff", "historydate", "latest_history_race_id", "history_update_count"])
    if len(features) != 52155 or len(lineage) != 52155:
        raise ValueError("state input row count drift")
    if features.api_record_id.duplicated().any() or features.duplicated(["race_id", "api_record_id"]).any():
        raise ValueError("duplicate output target key")
    for row in features.itertuples(index=False):
        if row.historydate is not None and not pd.isna(row.historydate) and row.historydate > row.cutoff:
            raise ValueError(f"history source after cutoff for API row {row.api_record_id}")
    finite_features = features[STATE_COLUMNS].drop(columns=["state_days_since_rank_observation"])
    if not np.isfinite(finite_features.to_numpy(dtype=float)).all():
        raise ValueError("non-finite state feature outside explicit no-history age NaN")
    no_history = features.state_rank_n.eq(0)
    if not features.loc[no_history, "state_days_since_rank_observation"].isna().all():
        raise ValueError("no-history age must be NaN")
    if not features.loc[~no_history, "state_days_since_rank_observation"].notna().all():
        raise ValueError("observed history age is missing")
    return features, lineage


def replay_one_cutoff(target_race: pd.DataFrame, by_date: dict[date, list[pd.DataFrame]], cutoff: date) -> pd.DataFrame:
    replay: dict[str, RankState] = {}
    for event_date in sorted(d for d in by_date if d <= cutoff):
        process_day(by_date[event_date], replay, event_date)
    sorted_race = target_race.sort_values("api_record_id", kind="mergesort").reset_index(drop=True)
    rows = []
    for row in sorted_race.itertuples(index=False):
        vals, _ = query_features(replay.get(str(row.horse_id)), cutoff, float(row.distance_m))
        rows.append(vals)
    out = pd.DataFrame(rows, columns=STATE_COLUMNS[:8])
    out["state_rank_current_field_gap"] = out.state_rank_current - out.state_rank_current.mean()
    out["state_rank_current_field_rank"] = out.state_rank_current.rank(method="average", pct=True, ascending=True).to_numpy()
    return out[STATE_COLUMNS]


def run_prefix_checks(target: pd.DataFrame, by_date: dict[date, list[pd.DataFrame]], features: pd.DataFrame) -> dict:
    check_rows = []
    # The supervisor separately performs an all-row independent Woodbury verification.
    # Keep this builder-local replay as a small early/middle/late prefix smoke check.
    selections = [(2017, 0), (2024, 1), (2026, 2)]
    for year, selection in selections:
        year_rows = target[[d.year == year for d in target.race_date]]
        if year_rows.empty:
            raise ValueError(f"missing target year for prefix replay: {year}")
        pos = 0 if selection == 0 else (len(year_rows) // 2 if selection == 1 else len(year_rows) - 1)
        row = year_rows.iloc[pos]
        cutoff = row.race_date - timedelta(days=2)
        race = target[target.race_id.eq(row.race_id)]
        replay = replay_one_cutoff(race, by_date, cutoff)
        out = features[features.race_id.eq(row.race_id)].sort_values("api_record_id").reset_index(drop=True)
        diff = np.abs(replay[STATE_COLUMNS].to_numpy(float) - out[STATE_COLUMNS].to_numpy(float))
        max_error = float(np.nanmax(diff)) if diff.size else 0.0
        if max_error > 1e-10:
            raise ValueError(f"independent prefix replay mismatch for {row.race_id}: {max_error}")
        check_rows.append({"year": int(year), "race_id": str(row.race_id), "cutoff": str(cutoff), "max_abs_error": max_error})
    return {"method": "fresh full replay through three representative early/middle/late target cutoffs",
            "scope_note": "three sampled races; supervisor/verify_states.py independently checks all saved state rows",
            "races": len(check_rows), "checks": check_rows,
            "passed": True, "max_abs_error": max(x["max_abs_error"] for x in check_rows)}


def tiny_event(race_id: str, event_date: date, horses: list[str], ranks: list[int]) -> pd.DataFrame:
    n = len(horses)
    return pd.DataFrame({
        "api_record_id": [int(hashlib.sha256(f"{race_id}:{h}".encode()).hexdigest()[:12], 16) for h in horses],
        "race_id": [race_id] * n, "race_date": [event_date] * n, "horse_id": horses,
        "horse_number": list(range(1, n + 1)), "race_distance_m": [1200.0] * n,
        "finish_position": ranks, "finish_time_seconds": [75.0 + i / 10 for i in ranks],
        "started": [True] * n, "valid_time": [True] * n,
    })


def synthetic_checks() -> dict:
    d0, d1, cut = date(2020, 1, 1), date(2020, 1, 10), date(2020, 1, 5)
    r1 = tiny_event("r1", d0, ["a", "b", "c", "d"], [1, 2, 3, 4])
    r2 = tiny_event("r2", d0, ["e", "f", "g", "h"], [4, 2, 1, 3])
    future = tiny_event("future", d1, ["a", "b", "c", "d"], [1, 2, 3, 4])
    future_changed = future.copy()
    future_changed["finish_position"] = [4, 3, 2, 1]

    def run(events: list[pd.DataFrame], until: date) -> dict[str, RankState]:
        by_day: dict[date, list[pd.DataFrame]] = defaultdict(list)
        for event in events:
            by_day[event.race_date.iloc[0]].append(event)
        states: dict[str, RankState] = {}
        for event_date in sorted(d for d in by_day if d <= until):
            process_day(by_day[event_date], states, event_date)
        return states

    baseline = run([r1, r2], d0)
    permuted = run([r2.sample(frac=1, random_state=7), r1.sample(frac=1, random_state=3)], d0)
    for h in baseline:
        if not np.allclose(baseline[h].mean, permuted[h].mean, atol=1e-12, rtol=0):
            raise ValueError("synthetic row/day permutation changed means")
        if not np.allclose(baseline[h].cov, permuted[h].cov, atol=1e-12, rtol=0):
            raise ValueError("synthetic row/day permutation changed covariances")
    before = run([r1, r2], cut)
    after = run([r1, r2, future_changed], cut)
    if set(before) != set(after) or any(not np.allclose(before[h].mean, after[h].mean, atol=0, rtol=0) for h in before):
        raise ValueError("synthetic future-outcome mutation changed prefix state")
    test_state = baseline["a"].clone()
    saved = (test_state.mean.copy(), test_state.cov.copy(), test_state.n, test_state.last_date)
    queried, _ = query_features(test_state, date(2020, 4, 10), 1400.0)
    if len(queried) != 8 or not np.array_equal(test_state.mean, saved[0]) or not np.array_equal(test_state.cov, saved[1]) or test_state.n != saved[2] or test_state.last_date != saved[3]:
        raise ValueError("query mutated stored synthetic state")
    propagated, days = propagate(test_state, date(2021, 1, 1))
    validate_cov(propagated.cov)
    if days != 366:
        raise ValueError("synthetic idle propagation day count mismatch")
    duplicate = tiny_event("bad", d0, ["a", "b", "c", "d"], [1, 2, 3, 4])
    rejected = False
    try:
        process_day([r1, duplicate], {}, d0)
    except ValueError as exc:
        rejected = "multiple eligible races" in str(exc)
    if not rejected:
        raise ValueError("duplicate same-horse same-day event was not rejected")
    return {
        "passed": True,
        "future_outcome_mutation_invariant_through_cutoff": True,
        "query_does_not_mutate_stored_state": True,
        "same_race_row_and_same_day_race_order_invariant": True,
        "duplicate_horse_same_day_rejected": True,
        "idle_propagation_covariance_psd_finite": True,
        "idle_days_tested": 366,
        "checks": 6,
    }


def canonical_key_digest(target: pd.DataFrame) -> str:
    h = hashlib.sha256()
    ordered = target.sort_values("api_record_id", kind="mergesort")
    for row in ordered[["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "distance_m", "field_n"]].itertuples(index=False, name=None):
        encoded = "\t".join(str(x) for x in row).encode("utf-8") + b"\n"
        h.update(encoded)
    return h.hexdigest()


def build() -> dict:
    for name in OUTPUT_FILES:
        path = INPUTS / name
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing input artifact: {path}")
    source_pins = manifest_pins()
    check = synthetic_checks()
    target, by_date, census = load_sources()
    features, lineage = build_features(target, by_date)
    prefix = run_prefix_checks(target, by_date, features)
    assert_pins_unchanged(source_pins)
    INPUTS.mkdir(parents=True, exist_ok=True)
    AUDIT.mkdir(parents=True, exist_ok=True)
    feature_path = INPUTS / "state_features.parquet"
    lineage_path = INPUTS / "state_lineage.parquet"
    features.to_parquet(feature_path, index=False, compression="zstd")
    lineage.to_parquet(lineage_path, index=False, compression="zstd")
    check["prefix_replay"] = prefix
    check_path = INPUTS / "synthetic_checks.json"
    check_path.write_text(json.dumps(check, indent=2, sort_keys=True) + "\n")
    assert_pins_unchanged(source_pins)
    files = {p.name: {**digest(p), "rows": len(features) if p == feature_path else (len(lineage) if p == lineage_path else None)}
             for p in (feature_path, lineage_path, check_path)}
    source_files = {name: digest(path) for name, path in {
        "source_snapshot": SOURCE, "f1_style6_target_keys_source": F1_TARGET,
        "history_eligibility_ledger": ELIGIBILITY, "horse_exclusions": EXCLUSIONS,
        "tb_rank_state_reference": TB_STATE, "design_contract": CONTRACT,
        "source_manifest": SOURCE_MANIFEST, "supervisor_all_row_verifier": VERIFY_STATES,
    }.items()}
    manifest = {
        "study": "20261022_tb_state_transfer_v1",
        "purpose": "contracted raw rank/distance state input construction only; no model fit, prediction, or evaluation",
        "builder": digest(Path(__file__)),
        "source_manifest_sha256": source_files["source_manifest"]["sha256"],
        "source_files": source_files,
        "files": files,
        "target_key_digest_sha256": canonical_key_digest(target),
        "feature_schema": KEY_COLUMNS + STATE_COLUMNS,
        "lineage_schema": list(lineage.columns),
        "target_metadata_columns_read": TARGET_COLUMNS,
        "target_table_outcome_columns_read": [],
        "history_observation_columns_read": SOURCE_COLUMNS,
        "history_event_outcomes_used_only_for_events_at_or_before_each_target_cutoff": True,
        "target_feature_columns_read": [],
        "source_hash_lock": "required hashes/sizes checked against source_manifest before data reads and again after feature generation and artifact writes",
        "cutoff": {"rule": "race_date minus two calendar days; source event date <= cutoff inclusive", "publication_timestamp": "not present/verified in source"},
        "state_contract": {
            "distance_basis": "h=[1,(d-1100)/500]",
            "prior_mean": [0.0, 0.0], "prior_covariance": [[2.0, 0.0], [0.0, 0.5]],
            "propagation": {"mean_decay_days": 1500, "process_variance_per_30_days": [0.035, 0.008], "max_dt_30_day_units": 24, "diagonal_caps": [2.0, 0.5]},
            "rank_update": "contracted opponent-pairwise logistic gradient/curvature update; same-race pre-update snapshots and same-date batch commit",
            "history_roster": "only full-roster exact, unique actual horse/API IDs and numbers, positive finite time, all-normal exact integer ranks 1..N, N>=4, supported consistent distance",
            "no_history": "n=0, prior mean/covariance, age NaN",
        },
        "cohort_census": census,
        "validation": {"synthetic": check, "builder_prefix_replay": prefix,
                       "supervisor_all_row_verifier_reference": source_files["supervisor_all_row_verifier"]},
        "fit_or_evaluation_run": False,
    }
    manifest_path = INPUTS / "input_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest["manifest_file"] = {"path": str(manifest_path.relative_to(ROOT)), "bytes": manifest_path.stat().st_size,
                                 "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    # Keep the manifest self-hash outside itself to avoid a recursive digest; report it on stdout.
    print(json.dumps({"manifest": str(manifest_path.relative_to(ROOT)), "manifest_sha256": manifest["manifest_file"]["sha256"],
                      "features": files[feature_path.name], "lineage": files[lineage_path.name], "census": census,
                      "prefix_replay_races": prefix["races"], "prefix_replay_max_abs_error": prefix["max_abs_error"]}, indent=2))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run only synthetic safeguards; do not read/write cohort artifacts")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(synthetic_checks(), indent=2, sort_keys=True))
    else:
        build()


if __name__ == "__main__":
    main()

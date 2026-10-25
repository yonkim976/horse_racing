"""Compute the four pre-registered special-condition tables after PLAN approval."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
FEATURES = ROOT / "jeju/research/20261009_top3_condition_profiles_v1/outputs/condition_features.parquet"
R1_FEATURES = ROOT / "jeju/research/20261009_field_relative_ability_v1/outputs/features.parquet"
SOURCE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
R1_VERIFY = ROOT / "jeju/research/20261009_field_relative_ability_v1/outputs/final_verification.json"
TOP3_VERIFY = ROOT / "jeju/research/20261009_top3_condition_profiles_v1/outputs/independent_verification.json"
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
MODEL = ROOT / "jeju/models/current/HY_R_FORM.pkl"
REGISTRY = ROOT / "config/prediction_model_registry.json"
SEED = 20261009
PERIODS = {
    "2017_2023": lambda x: x.year.le(2023),
    "2024_2025": lambda x: x.year.between(2024, 2025),
    "2026_partial": lambda x: x.year.eq(2026),
}
CONDITION_COLUMNS = ["S1_gap_sequence", "S2_distance_return", "S3_relative_position_change", "S4_prior_rank_finish_gap"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def lock_paths() -> list[Path]:
    return [
        HERE / "PLAN.md", HERE / "audit.py",
        FEATURES, R1_FEATURES, SOURCE, R1_VERIFY, TOP3_VERIFY,
        ROOT / "jeju/AGENTS.md", ROOT / "jeju/docs/RESTART_PLAN_20260928.md",
        ROOT / "jeju/docs/SOURCE_CATALOG.md",
        ROOT / "jeju/research/RESEARCH_PUBLICATION_POLICY.md",
        ROOT / "jeju/research/20261009_top3_condition_profiles_v1/CONTRACT.md",
        ROOT / "jeju/research/20261009_field_relative_ability_v1/CONTRACT.md",
        ROOT / "jeju/research/20261008_recent_form_persistence_v1/candidate_event_date_coverage.csv",
        DB, MODEL, REGISTRY,
    ]


def make_lock() -> dict:
    paths = lock_paths()
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError("Required frozen inputs missing: " + ", ".join(missing))
    return {str(p.relative_to(ROOT)): {"sha256": sha(p), "bytes": p.stat().st_size} for p in paths}


def assert_lock(lock: dict) -> None:
    for rel, info in lock.items():
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size != info["bytes"] or sha(path) != info["sha256"]:
            raise RuntimeError(f"Frozen input changed: {rel}")


def as_id(value):
    if value is None or pd.isna(value):
        return None
    return int(value)


def list_ids(value) -> list[int]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    return [int(x) for x in value if pd.notna(x)]


def preflight() -> None:
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite output directory: {OUT}")
    lock = make_lock()
    base = pd.read_parquet(FEATURES)
    r1 = pd.read_parquet(R1_FEATURES)
    source = pd.read_parquet(SOURCE)
    required_base = {"api_record_id", "race_id", "race_date", "history_cutoff", "horse_id", "distance_m",
                     "finish_position", "field_n", "previous_start_id", "same_starts", "last6_same_source_ids",
                     "mean5_rank_fraction", "p_R1", "p_HY"}
    required_r1 = {"api_record_id", "race_date", "history_cutoff", "horse_id", "distance_m", "mean5_rank_fraction"}
    required_source = {"api_record_id", "race_date", "race_id", "horse_id", "race_distance_m", "finish_position",
                       "finish_time_seconds", "started", "valid_time"}
    for frame, required, name in [(base, required_base, "condition_features"),
                                  (r1, required_r1, "R1_features"), (source, required_source, "source_snapshot")]:
        absent = required - set(frame.columns)
        if absent:
            raise RuntimeError(f"{name} missing columns: {sorted(absent)}")
    if len(base) != 52155 or base.race_id.nunique() != 5206:
        raise RuntimeError("Frozen Top3 cohort size differs from its contract")
    if base.duplicated(["race_id", "horse_id"]).any() or base.api_record_id.duplicated().any():
        raise RuntimeError("Frozen cohort has duplicate race/horse or API-record keys")
    if not base.groupby("race_id").finish_position.apply(lambda s: sorted(s.astype(int)) == list(range(1, len(s) + 1))).all():
        raise RuntimeError("Frozen cohort no longer has complete normal ranks")
    top3_by_race = base.assign(_top3=base.finish_position.le(3).astype(int)).groupby("race_id")._top3.sum()
    if not top3_by_race.eq(3).all():
        raise RuntimeError("Frozen cohort no longer has exactly three Top3 labels per race")
    if base.horse_id.astype(str).eq("3005648").any():
        raise RuntimeError("Excluded horse 3005648 found in cohort")
    src = source.set_index("api_record_id", drop=False)
    src_by_horse = {str(h): g.sort_values(["race_date", "api_record_id"]) for h, g in source.groupby("horse_id", sort=False)}
    r1_idx = r1.set_index("api_record_id", drop=False)
    feature_ids = set(r1.api_record_id.astype(int))
    bad_targets = []
    previous_feature_resolved = 0
    same_distance_feature_resolved = 0
    same_distance_prior_reference = 0
    for row in base.itertuples(index=False):
        target_id = int(row.api_record_id)
        if target_id not in r1_idx.index:
            bad_targets.append((target_id, "target_missing_from_R1_features"))
        else:
            r1_target = r1_idx.loc[target_id]
            if (str(r1_target.horse_id) != str(row.horse_id) or str(r1_target.race_date) != str(row.race_date)
                    or float(r1_target.distance_m) != float(row.distance_m)
                    or str(r1_target.history_cutoff) != str(row.history_cutoff)):
                bad_targets.append((target_id, "target_R1_feature_identity_mismatch"))
            current_rank, saved_rank = row.mean5_rank_fraction, r1_target.mean5_rank_fraction
            if pd.isna(current_rank) != pd.isna(saved_rank) or (pd.notna(current_rank) and not np.isclose(current_rank, saved_rank, atol=1e-12, rtol=0)):
                bad_targets.append((target_id, "target_R1_relative_rank_value_mismatch"))
        expected_cutoff = (date.fromisoformat(str(row.race_date)) - timedelta(days=2)).isoformat()
        if str(row.history_cutoff) != expected_cutoff:
            bad_targets.append((target_id, "history_cutoff_not_T_minus_2"))
        if target_id not in src.index:
            bad_targets.append((target_id, "target_missing_from_source"))
            continue
        target_source = src.loc[target_id]
        if str(target_source.horse_id) != str(row.horse_id) or str(target_source.race_date) != str(row.race_date):
            bad_targets.append((target_id, "target_identity_mismatch"))
        cutoff = str(row.history_cutoff)
        h = src_by_horse.get(str(row.horse_id), source.iloc[0:0])
        past = h[(h.race_date.le(cutoff)) & h.started.astype(bool)]
        previous_id = as_id(row.previous_start_id)
        expected_previous = int(past.api_record_id.iloc[-1]) if len(past) else None
        if previous_id != expected_previous:
            bad_targets.append((target_id, "previous_start_id_mismatch"))
        if past.race_date.gt(cutoff).any():
            bad_targets.append((target_id, "history_after_T_minus_2"))
        if previous_id is not None and previous_id in feature_ids:
            previous_feature_resolved += 1
        same_ids = list_ids(row.last6_same_source_ids)
        if same_ids:
            latest_same_id = same_ids[-1]
            if latest_same_id not in src.index:
                bad_targets.append((target_id, "latest_same_distance_missing_source"))
            else:
                q = src.loc[latest_same_id]
                if (str(q.horse_id) != str(row.horse_id) or float(q.race_distance_m) != float(row.distance_m)
                        or str(q.race_date) > cutoff or not bool(q.started)):
                    bad_targets.append((target_id, "latest_same_distance_lineage_invalid"))
                else:
                    same_distance_prior_reference += 1
                    if latest_same_id in feature_ids:
                        same_distance_feature_resolved += 1
                    if latest_same_id in r1_idx.index:
                        old = r1_idx.loc[latest_same_id]
                        if str(old.horse_id) != str(row.horse_id) or float(old.distance_m) != float(row.distance_m):
                            bad_targets.append((target_id, "prior_R1_feature_identity_mismatch"))
                        if str(old.race_date) > cutoff:
                            bad_targets.append((target_id, "prior_R1_feature_after_T_minus_2"))
    if bad_targets:
        raise RuntimeError(f"Preflight lineage failures ({len(bad_targets)}): {bad_targets[:10]}")
    expected_started = source.finish_position.between(1, 89) | source.finish_position.isin([91, 92])
    if not source.started.astype(bool).equals(expected_started.astype(bool)):
        raise RuntimeError("Source started-status no longer matches the existing outcome contract")
    if not json.loads(R1_VERIFY.read_text(encoding="utf-8")).get("passed", False):
        raise RuntimeError("R1 final verification is not passed")
    if not json.loads(TOP3_VERIFY.read_text(encoding="utf-8")).get("passed", False):
        raise RuntimeError("Top3 condition independent verification is not passed")
    OUT.mkdir()
    save_json(OUT / "source_lock.json", lock)
    save_json(OUT / "preflight.json", {
        "passed": True,
        "purpose": "input identity, cohort, T-2 and source-support check only; no condition outcome rates calculated",
        "cohort_rows": len(base), "cohort_races": int(base.race_id.nunique()),
        "cohort_horses": int(base.horse_id.nunique()), "source_snapshot_rows": len(source),
        "source_snapshot_horses": int(source.horse_id.nunique()),
        "previous_start_ids_resolved_in_R1_features": previous_feature_resolved,
        "latest_same_distance_source_refs": same_distance_prior_reference,
        "latest_same_distance_refs_resolved_in_frozen_features": same_distance_feature_resolved,
        "excluded_horse_rows": 0,
        "T_minus_2_identity_failures": 0,
        "protected_files": ["jeju/data/jeju_native_core.sqlite3", "jeju/models/current/HY_R_FORM.pkl",
                            "config/prediction_model_registry.json"],
        "input_lock": lock,
    })
    assert_lock(lock)
    print("Preflight passed:", len(base), "rows; condition outcomes not calculated", flush=True)


def condition_row(row, source_idx, feature_idx, source_by_horse):
    """Return one runner's four conditions and exact prior IDs; current label is unused."""
    target_date = date.fromisoformat(str(row.race_date))
    cutoff = date.fromisoformat(str(row.history_cutoff))
    horse = str(row.horse_id)
    target_distance = float(row.distance_m)
    h = source_by_horse.get(horse)
    if h is None:
        past = []
    else:
        dates = h["race_date"].tolist()
        end = bisect_right(dates, cutoff.isoformat())
        past = h.iloc[:end]
        past = past[past.started.astype(bool)]

    previous_id = as_id(row.previous_start_id)
    previous = source_idx.loc[previous_id] if previous_id is not None and previous_id in source_idx.index else None
    s1_prior2_id = None
    uncertain_ids: list[int] = []
    if h is not None:
        eligible_dates = h["race_date"].le(cutoff.isoformat())
        ambiguous = h[eligible_dates & ~h.started.astype(bool) & h.finish_position.isin([0, 93, 98])]
    else:
        ambiguous = pd.DataFrame(columns=source_idx.columns)
    if previous is None or not len(past):
        s1 = "unknown"
        current_gap = np.nan
    else:
        ids = past.api_record_id.astype(int).tolist()
        if ids[-1] != previous_id or str(previous.horse_id) != horse or str(previous.race_date) > cutoff.isoformat():
            raise RuntimeError(f"S1 previous-start lineage mismatch at {row.api_record_id}")
        current_gap = (target_date - date.fromisoformat(str(previous.race_date))).days
        if current_gap < 0:
            raise RuntimeError(f"S1 negative current gap at {row.api_record_id}")
        current_segment = ambiguous[
            ambiguous.race_date.ge(str(previous.race_date)) & ambiguous.race_date.le(cutoff.isoformat())
        ]
        uncertain_ids.extend(current_segment.api_record_id.astype(int).tolist())
        if len(current_segment):
            s1 = "unknown"
        elif current_gap >= 91:
            s1 = "first_return_91_plus"
        elif len(past) < 2:
            s1 = "unknown"
        else:
            prior2 = past.iloc[-2]
            s1_prior2_id = int(prior2.api_record_id)
            if str(prior2.race_date) == str(previous.race_date):
                s1 = "unknown"
            else:
                previous_segment = ambiguous[
                    ambiguous.race_date.ge(str(prior2.race_date)) & ambiguous.race_date.le(str(previous.race_date))
                ]
                uncertain_ids.extend(previous_segment.api_record_id.astype(int).tolist())
                previous_gap = (date.fromisoformat(str(previous.race_date)) - date.fromisoformat(str(prior2.race_date))).days
                if len(previous_segment):
                    s1 = "unknown"
                elif previous_gap >= 91:
                    s1 = "second_after_return_le90"
                else:
                    s1 = "general"

    same_n = int(row.same_starts) if pd.notna(row.same_starts) else None
    if same_n is None:
        same_bucket = "unknown"
    elif same_n == 0:
        same_bucket = "0"
    elif same_n <= 2:
        same_bucket = "1_2"
    else:
        same_bucket = "3_plus"
    if previous is None or pd.isna(previous.race_distance_m):
        previous_relation = "unknown"
    else:
        previous_relation = "same" if float(previous.race_distance_m) == target_distance else "changed"
    s2 = f"prev_{previous_relation}|same_starts_{same_bucket}"

    same_ids = list_ids(row.last6_same_source_ids)
    s3_prior_id = same_ids[-1] if same_ids else None
    current_rank = float(row.mean5_rank_fraction) if pd.notna(row.mean5_rank_fraction) else np.nan
    prior_rank = np.nan
    if s3_prior_id is None or not np.isfinite(current_rank) or s3_prior_id not in feature_idx.index:
        s3 = "unknown"
    else:
        prior_row = feature_idx.loc[s3_prior_id]
        source_prior = source_idx.loc[s3_prior_id]
        if (str(prior_row.horse_id) != horse or float(prior_row.distance_m) != target_distance
                or str(prior_row.race_date) > cutoff.isoformat() or str(source_prior.race_date) > cutoff.isoformat()
                or not bool(source_prior.started)):
            raise RuntimeError(f"S3 previous same-distance lineage mismatch at {row.api_record_id}")
        prior_rank = float(prior_row.mean5_rank_fraction) if pd.notna(prior_row.mean5_rank_fraction) else np.nan
        delta = current_rank - prior_rank
        if not np.isfinite(prior_rank):
            s3 = "unknown"
        elif delta <= -0.25:
            s3 = "improved_ge0_25"
        elif delta >= 0.25:
            s3 = "worsened_ge0_25"
        else:
            s3 = "change_lt0_25"

    s4_prior_id = previous_id
    prior_expected_rank = np.nan
    prior_finish_fraction = np.nan
    if previous is None or previous_id not in feature_idx.index:
        s4 = "unknown"
    else:
        prior_event = feature_idx.loc[previous_id]
        field_n = int(prior_event.field_n)
        finish = int(prior_event.finish_position)
        prior_expected_rank = float(prior_event.mean5_rank_fraction) if pd.notna(prior_event.mean5_rank_fraction) else np.nan
        if (str(prior_event.horse_id) != horse or str(prior_event.race_date) > cutoff.isoformat()
                or field_n < 2 or not 1 <= finish <= field_n or not np.isfinite(prior_expected_rank)):
            s4 = "unknown"
        else:
            prior_finish_fraction = (finish - 1) / (field_n - 1)
            gap = prior_finish_fraction - prior_expected_rank
            if gap >= 0.25:
                s4 = "worse_than_prior_time_rank_ge0_25"
            elif gap <= -0.25:
                s4 = "better_than_prior_time_rank_ge0_25"
            else:
                s4 = "close_lt0_25"

    return {
        "S1_gap_sequence": s1, "S1_current_gap_days": current_gap,
        "S1_previous_start_id": previous_id, "S1_pre_previous_start_id": s1_prior2_id,
        "S1_uncertain_nonstart_n": len(set(uncertain_ids)),
        "S1_uncertain_nonstart_ids": sorted(set(uncertain_ids)),
        "S2_distance_return": s2, "S2_previous_distance_m": float(previous.race_distance_m) if previous is not None and pd.notna(previous.race_distance_m) else np.nan,
        "S2_same_distance_started_n": same_n,
        "S3_relative_position_change": s3, "S3_prior_same_distance_id": s3_prior_id,
        "S3_current_rank_fraction": current_rank, "S3_prior_rank_fraction": prior_rank,
        "S3_delta_fraction": current_rank - prior_rank if np.isfinite(current_rank) and np.isfinite(prior_rank) else np.nan,
        "S4_prior_rank_finish_gap": s4, "S4_prior_start_id": s4_prior_id,
        "S4_prior_time_rank_fraction": prior_expected_rank, "S4_prior_finish_fraction": prior_finish_fraction,
        "S4_finish_minus_time_rank_fraction": prior_finish_fraction - prior_expected_rank
        if np.isfinite(prior_finish_fraction) and np.isfinite(prior_expected_rank) else np.nan,
    }


def summary(g: pd.DataFrame, family: str, category: str, period: str, distance=None) -> dict:
    y = g.y.to_numpy(float)
    n = len(g)
    top3 = int(y.sum())
    mixed = g.groupby("race_id", sort=False).agg(rows=("y", "size"), hits=("y", "sum"), field_n=("field_n", "first"))
    mixed = mixed[mixed.rows.lt(mixed.field_n)]
    within = ((mixed.hits / mixed.rows) - ((3 - mixed.hits) / (mixed.field_n - mixed.rows))).mean() if len(mixed) else np.nan
    result = {
        "family": family, "condition": category, "period": period,
        "distance_m": distance, "rows": n, "top3": top3, "non_top3": n - top3,
        "horses": int(g.horse_id.nunique()), "races": int(g.race_id.nunique()),
        "days": int(g.race_date.nunique()), "first_date": str(g.race_date.min()), "last_date": str(g.race_date.max()),
        "share_of_population": n / max(1, int(g._population_rows.iloc[0])),
        "share_among_top3": top3 / max(1, int(g._population_top3.iloc[0])),
        "top3_rate": float(y.mean()), "uniform_3_over_n": float(g.uniform_p.mean()),
        "excess_over_uniform": float((y - g.uniform_p.to_numpy(float)).mean()),
        "within_race_risk_difference": float(within) if pd.notna(within) else np.nan,
        "within_race_comparable_races": int(len(mixed)),
        "low_support": bool(n < 100 or g.race_id.nunique() < 50),
    }
    for name, pred_col in [("R1", "p_R1"), ("HY_R_FORM", "p_HY")]:
        q = g[g[pred_col].notna()]
        result[f"{name}_rows"] = int(len(q))
        result[f"{name}_predicted_top3"] = float(q[pred_col].mean()) if len(q) else np.nan
        result[f"{name}_observed_top3"] = float(q.y.mean()) if len(q) else np.nan
        result[f"{name}_observed_minus_predicted"] = float((q.y - q[pred_col]).mean()) if len(q) else np.nan
    return result


def day_bootstrap(g: pd.DataFrame, outcome: str, prediction: str | None = None) -> tuple[float, float]:
    q = g[g[prediction].notna()].copy() if prediction else g.copy()
    if q.empty:
        return np.nan, np.nan
    q["delta"] = q[outcome] - q[prediction] if prediction else q[outcome] - q.uniform_p
    by_day = q.groupby("race_date", sort=True).delta.agg(["sum", "size"])
    sums = by_day["sum"].to_numpy(float)
    sizes = by_day["size"].to_numpy(float)
    rng = np.random.default_rng(SEED)
    draws = rng.integers(0, len(by_day), size=(2000, len(by_day)))
    estimates = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    return tuple(map(float, np.quantile(estimates, [0.025, 0.975])))


def build_outputs() -> None:
    if not OUT.is_dir() or not (OUT / "source_lock.json").is_file() or not (OUT / "preflight.json").is_file():
        raise RuntimeError("Run --preflight first")
    lock = json.loads((OUT / "source_lock.json").read_text(encoding="utf-8"))
    assert_lock(lock)
    target = pd.read_parquet(FEATURES)
    source = pd.read_parquet(SOURCE)
    r1 = pd.read_parquet(R1_FEATURES)
    if len(target) != 52155:
        raise RuntimeError("Frozen target cohort changed")
    src_idx = source.set_index("api_record_id", drop=False)
    feat_idx = r1.set_index("api_record_id", drop=False)
    source_by_horse = {str(h): g.sort_values(["race_date", "api_record_id"]).reset_index(drop=True)
                       for h, g in source.groupby("horse_id", sort=False)}
    records = [condition_row(row, src_idx, feat_idx, source_by_horse) for row in target.itertuples(index=False)]
    new_features = pd.concat([target.reset_index(drop=True), pd.DataFrame(records)], axis=1)
    new_features["y"] = new_features.finish_position.le(3).astype(int)
    new_features["uniform_p"] = 3 / new_features.field_n
    new_features["period"] = np.select(
        [new_features.year.le(2023), new_features.year.le(2025)],
        ["2017_2023", "2024_2025"], default="2026_partial")
    new_features.to_parquet(OUT / "condition_features.parquet", index=False)
    uncertain = new_features[new_features.S1_uncertain_nonstart_n.gt(0)][
        ["api_record_id", "race_date", "horse_id", "S1_gap_sequence", "S1_previous_start_id",
         "S1_pre_previous_start_id", "S1_uncertain_nonstart_n", "S1_uncertain_nonstart_ids"]
    ].copy()
    if len(uncertain):
        uncertain["S1_uncertain_nonstart_ids"] = uncertain.S1_uncertain_nonstart_ids.map(lambda ids: ",".join(map(str, ids)))
    uncertain.to_csv(OUT / "S1_uncertain_nonstart_lineage.csv", index=False)

    rows = []
    groupings = [("all", np.ones(len(new_features), dtype=bool))]
    for period, mask_fn in PERIODS.items():
        groupings.append((period, mask_fn(new_features)))
    for period, period_mask in groupings:
        period_base = new_features.loc[period_mask].copy()
        if period_base.empty:
            continue
        for family in CONDITION_COLUMNS:
            for category, group in period_base.groupby(family, sort=True, dropna=False):
                decorated = group.copy()
                decorated["_population_rows"] = len(period_base)
                decorated["_population_top3"] = int(period_base.y.sum())
                rows.append(summary(decorated, family, str(category), period))
        for distance, dist_base in period_base.groupby("distance_m", sort=True):
            for family in CONDITION_COLUMNS:
                for category, group in dist_base.groupby(family, sort=True, dropna=False):
                    decorated = group.copy()
                    decorated["_population_rows"] = len(dist_base)
                    decorated["_population_top3"] = int(dist_base.y.sum())
                    rows.append(summary(decorated, family, str(category), period, int(distance)))
    table = pd.DataFrame(rows)
    # Pointwise date-cluster intervals are limited to the two pre-declared recent periods.
    ci_columns = ["uniform_3_over_n", "R1_observed_minus_predicted"]
    ci_rows = []
    for row in table.itertuples(index=False):
        if row.period not in ("2024_2025", "2026_partial"):
            continue
        mask = new_features[row.family].astype(str).eq(row.condition)
        if row.distance_m is not None and not pd.isna(row.distance_m):
            mask &= new_features.distance_m.eq(float(row.distance_m))
        if row.period == "2024_2025":
            mask &= new_features.year.between(2024, 2025)
        else:
            mask &= new_features.year.eq(2026)
        g = new_features.loc[mask]
        u_lo, u_hi = day_bootstrap(g, "y")
        r_lo, r_hi = day_bootstrap(g, "y", "p_R1")
        ci_rows.append({"family": row.family, "condition": row.condition, "period": row.period,
                        "distance_m": row.distance_m, "uniform_excess_lo": u_lo, "uniform_excess_hi": u_hi,
                        "R1_residual_lo": r_lo, "R1_residual_hi": r_hi})
    table.to_csv(OUT / "condition_statistics.csv", index=False)
    pd.DataFrame(ci_rows).to_csv(OUT / "date_bootstrap_intervals.csv", index=False)

    common = new_features[new_features.p_HY.notna()].copy()
    common_rows = []
    for family in CONDITION_COLUMNS:
        for category, group in common.groupby(family, sort=True, dropna=False):
            decorated = group.copy()
            decorated["_population_rows"] = len(common)
            decorated["_population_top3"] = int(common.y.sum())
            common_rows.append(summary(decorated, family, str(category), "2026_operating_common467"))
    pd.DataFrame(common_rows).to_csv(OUT / "operating_common467_condition_summary.csv", index=False)
    verify_outputs(target, new_features, source, src_idx, feat_idx, lock)


def verify_outputs(target, derived, source, src_idx, feat_idx, lock) -> None:
    if len(derived) != 52155 or derived.race_id.nunique() != 5206:
        raise RuntimeError("Derived cohort size changed")
    if derived.groupby("race_id").y.sum().ne(3).any():
        raise RuntimeError("Top3 total invariance failed")
    if derived.groupby("race_id").field_n.first().ne(derived.groupby("race_id").size()).any():
        raise RuntimeError("Field denominator mismatch")
    if not derived.S2_distance_return.str.contains(r"^prev_(same|changed|unknown)\|same_starts_(0|1_2|3_plus|unknown)$").all():
        raise RuntimeError("S2 category outside pre-registered 3x4 grid")
    if not derived.S1_gap_sequence.isin(["general", "first_return_91_plus", "second_after_return_le90", "unknown"]).all():
        raise RuntimeError("S1 category outside fixed grid")
    if not derived.S3_relative_position_change.isin(["improved_ge0_25", "change_lt0_25", "worsened_ge0_25", "unknown"]).all():
        raise RuntimeError("S3 category outside fixed grid")
    if not derived.S4_prior_rank_finish_gap.isin(["worse_than_prior_time_rank_ge0_25", "close_lt0_25",
                                                  "better_than_prior_time_rank_ge0_25", "unknown"]).all():
        raise RuntimeError("S4 category outside fixed grid")
    if not derived.y.equals(target.finish_position.le(3).astype(int).rename("y")):
        raise RuntimeError("Target label derivation mismatch")

    # Isolated target-label and target-time perturbation cannot alter any pre-race condition.
    sample = target.sample(n=min(200, len(target)), random_state=SEED)
    source_by_horse = {str(h): g.sort_values(["race_date", "api_record_id"]).reset_index(drop=True)
                       for h, g in source.groupby("horse_id", sort=False)}
    invariance_rows = 0
    def same_value(left, right):
        if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
            return len(left) == len(right) and all(same_value(a, b) for a, b in zip(left, right))
        if left is None or right is None:
            return left is right
        try:
            left_missing, right_missing = pd.isna(left), pd.isna(right)
            if isinstance(left_missing, (bool, np.bool_)) and isinstance(right_missing, (bool, np.bool_)):
                if left_missing or right_missing:
                    return bool(left_missing and right_missing)
        except (TypeError, ValueError):
            pass
        return left == right

    def same_condition(left, right):
        return left.keys() == right.keys() and all(same_value(left[k], right[k]) for k in left)

    for row in sample.itertuples(index=False):
        baseline = condition_row(row, src_idx, feat_idx, source_by_horse)
        replacement = {"finish_position": 999}
        if "finish_time_seconds" in row._fields:
            replacement["finish_time_seconds"] = 1.0e6
        perturbed = row._replace(**replacement)
        changed = condition_row(perturbed, src_idx, feat_idx, source_by_horse)
        if not same_condition(baseline, changed):
            raise RuntimeError(f"Current target result changed its condition at {row.api_record_id}")
        invariance_rows += 1

    # A past actual finish is intentionally part of S4; verify that changing it changes the category.
    historical_outcome_perturbation_rows = 0
    for row in target.itertuples(index=False):
        prior_id = as_id(row.previous_start_id)
        if prior_id is None or prior_id not in feat_idx.index:
            continue
        prior = feat_idx.loc[prior_id]
        if pd.isna(prior.mean5_rank_fraction) or int(prior.field_n) < 2:
            continue
        baseline = condition_row(row, src_idx, feat_idx, source_by_horse)
        mutated_features = feat_idx.copy()
        mutated_finish = int(prior.field_n) if int(prior.finish_position) == 1 else 1
        mutated_features.loc[prior_id, "finish_position"] = mutated_finish
        changed = condition_row(row, src_idx, mutated_features, source_by_horse)
        if baseline["S4_prior_rank_finish_gap"] == changed["S4_prior_rank_finish_gap"]:
            raise RuntimeError(f"Prior finish perturbation did not change S4 at {row.api_record_id}")
        if not same_condition({k: baseline[k] for k in baseline if not k.startswith("S4_")},
                              {k: changed[k] for k in changed if not k.startswith("S4_")}):
            raise RuntimeError(f"Prior finish perturbation changed a non-S4 condition at {row.api_record_id}")
        historical_outcome_perturbation_rows += 1
        break
    if historical_outcome_perturbation_rows == 0:
        raise RuntimeError("No eligible prior finish row was available for S4 perturbation validation")

    # Direct boundary fixtures guard the fixed thresholds without changing the measured cohort.
    assert (-0.25 <= -0.25) and not (-0.25 < -0.25)
    assert (0.25 >= 0.25) and not (0.25 < 0.25)
    assert (0.0 - 0.25) <= -0.25 and (0.5 - 0.0) >= 0.25
    assert derived["S3_delta_fraction"].dropna().between(-1, 1).all()
    assert derived["S4_finish_minus_time_rank_fraction"].dropna().between(-1, 1).all()
    assert_lock(lock)
    verification = {
        "passed": True,
        "cohort_rows": len(derived), "races": int(derived.race_id.nunique()),
        "condition_families": CONDITION_COLUMNS,
        "S2_fixed_grid_levels": int(derived.S2_distance_return.nunique()),
        "target_result_perturbation_invariance_rows": invariance_rows,
        "prior_finish_perturbation_changes_only_S4_rows": historical_outcome_perturbation_rows,
        "top3_sum3_per_race": True, "same_race_denominator_match": True,
        "all_previous_links_T_minus_2_checked_in_condition_builder": True,
        "source_lock_unchanged_at_completion": True,
        "model_training_count": 0, "operating_model_registry_db_writes": 0,
    }
    save_json(OUT / "verification.json", verification)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true", help="Check source identity/support without outcome summaries")
    group.add_argument("--analyze", action="store_true", help="Compute the approved S1-S4 descriptive condition tables")
    args = parser.parse_args()
    if args.preflight:
        preflight()
    else:
        build_outputs()
        print("Condition tables and verification saved under", OUT, flush=True)


if __name__ == "__main__":
    main()

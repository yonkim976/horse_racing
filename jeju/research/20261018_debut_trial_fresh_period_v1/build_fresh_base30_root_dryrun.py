"""Rebuild fresh F1_STYLE6 inputs from frozen source plus the root read-only snapshot.

This is a no-score implementation dry run. It only writes to this study folder,
never opens SQLite, and does not pair model scores with fresh outcomes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ROOT_REVIEW = ROOT / "jeju/research/20261018_debut_trial_fresh_rootreview_v1"
PROFILE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1"
FIELD = ROOT / "jeju/research/20261009_field_relative_ability_v1"
FINISH = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
STYLE_AUDIT = ROOT / "jeju/research/20261010_style_history_source_audit_v1"
OUT = HERE / "outputs"
OUT_FEATURES = OUT / "root_dryrun_fresh_features_30.parquet"
OUT_RECEIPT = OUT / "root_dryrun_fresh_build.json"
BASE_FEATURES = [
    "distance_m", "grade_raw", "field_n", "observed_starts", "days_since_start",
    "previous_age", "previous_sex", "same_starts", "same_valid_times", "days_since_same",
    "last_time_s", "mean5_s", "valid_n5", "opp_mean5_valid_n",
    "opp_mean5_valid_fraction", "opp_mean5_median_s", "mean5_minus_opp_mean_s",
    "mean5_minus_opp_median_s", "mean5_minus_opp_fast2mean_s", "opp_mean5_faster_n",
    "mean5_rank_fraction", "previous_finish_relative_rank", "previous_top3",
    "previous_result_status", "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_module(name: str, path: Path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load fixed feature code: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def strict_bool(series: pd.Series, name: str) -> pd.Series:
    if series.isna().any():
        raise AssertionError(f"{name} contains NULL")
    if pd.api.types.is_bool_dtype(series):
        return series.astype(bool)
    mapping = {"True": True, "False": False, "1": True, "0": False, 1: True, 0: False}
    out = series.map(lambda x: mapping.get(x, mapping.get(str(x))))
    if out.isna().any():
        raise AssertionError(f"{name} has an unknown boolean token")
    return out.astype(bool)


def build_full_point_cache(raw_extra: pd.DataFrame, source: pd.DataFrame, group_raw: pd.DataFrame, audit):
    required = {
        "api_record_id", "race_id", "race_date", "race_distance_m", "horse_id", "horse_number",
        "point", "field_name", "full_started_n", "quality_order_value", "quality_order_status",
        "local_rank_ok", "api303_group_status", "race_point_eligible", "normalized_rank",
    }
    assert required.issubset(raw_extra.columns), required - set(raw_extra.columns)
    extra = raw_extra.copy()
    extra["api_record_id"] = pd.to_numeric(extra.api_record_id, errors="raise").astype("int64")
    extra["local_rank_ok"] = strict_bool(extra.local_rank_ok, "local_rank_ok")
    extra["race_point_eligible"] = strict_bool(extra.race_point_eligible, "race_point_eligible")
    extra["quality_order_value"] = pd.to_numeric(extra.quality_order_value, errors="coerce")
    extra["full_started_n"] = pd.to_numeric(extra.full_started_n, errors="raise").astype("int64")
    order_allowed = set(audit.ORDER_STATUS_ALLOWED)
    order_good = set(audit.ORDER_STATUS_OK)
    group_allowed = set(audit.GROUP_STATUS_ALLOWED)
    group_good = {"api_group_unreviewed", "api_group_unavailable"}
    assert extra.quality_order_status.notna().all()
    assert set(extra.quality_order_status.astype(str)).issubset(order_allowed), "unknown/changed API4 order status"
    assert extra.api303_group_status.notna().all()
    assert set(extra.api303_group_status.astype(str)).issubset(group_allowed), "unknown/changed API303 status"

    point_ok = {}
    for key, g in extra.groupby(["race_id", "point"], sort=False):
        n_values = g.full_started_n.unique()
        assert len(n_values) == 1
        n = int(n_values[0])
        ranks = g.quality_order_value.to_numpy(float)
        good = (
            len(g) == n and g.api_record_id.nunique() == n and g.horse_id.astype(str).nunique() == n
            and g.horse_number.astype(str).nunique() == n and g.local_rank_ok.all()
            and g.quality_order_status.astype(str).isin(order_good).all()
            and n >= 2 and np.array_equal(np.sort(ranks), np.arange(1, n + 1, dtype=float))
        )
        point_ok[(str(key[0]), str(key[1]))] = bool(good)
    extra["point_permutation_valid"] = [point_ok[(str(r), str(p))] for r, p in zip(extra.race_id, extra.point)]
    extra["api4_order_permutation_valid"] = extra.point_permutation_valid
    extra["api303_group_gate_supported"] = extra.api303_group_status.astype(str).isin(group_good)
    extra["api303_group_status_gate"] = extra.api303_group_gate_supported
    derived_eligible = extra.point_permutation_valid & extra.api303_group_gate_supported
    assert extra.race_point_eligible.equals(derived_eligible), "root cache eligibility differs from frozen gate"
    extra["race_point_eligible"] = derived_eligible
    n_by_id = source.set_index("api_record_id").started.groupby(level=0).first() if False else None
    source_valid = source.set_index("api_record_id").valid_time.astype(bool)
    extra["source_snapshot_valid_time"] = extra.api_record_id.map(source_valid)
    assert extra.source_snapshot_valid_time.notna().all()
    extra["started_n"] = extra.full_started_n
    extra["complete_unique_1_to_n_permutation"] = extra.point_permutation_valid
    expected_rank = (extra.quality_order_value - 1) / (extra.full_started_n - 1)
    expected_rank = expected_rank.where(extra.race_point_eligible)
    actual_rank = pd.to_numeric(extra.normalized_rank, errors="coerce")
    assert np.allclose(actual_rank.to_numpy(float), expected_rank.to_numpy(float), rtol=0, atol=0, equal_nan=True)
    extra["normalized_rank"] = expected_rank

    # Carry the raw API303 group interval through the same audited parser; this
    # field is diagnostic only and never contributes to model inputs.
    assert {"race_id", "point", "group_value", "group_status"}.issubset(group_raw.columns)
    assert not group_raw.duplicated(["race_id", "point"]).any()
    started = source.loc[source.started.astype(bool)]
    roster_by_race = {str(r): set(pd.to_numeric(g.horse_number, errors="raise").astype(int))
                      for r, g in started.groupby("race_id", sort=False)}
    group_map = group_raw.set_index([group_raw.race_id.astype(str), group_raw.point.astype(str)])
    parse_map = {}
    for key, row in group_raw.iterrows():
        race_id, point = str(row.race_id), str(row.point)
        parsed = audit.parse_group_interval(row.group_value, roster_by_race.get(race_id, set()))
        parse_map[(race_id, point)] = parsed is not None
    extra["api303_interval_parse_pass_diagnostic_only"] = [
        bool(parse_map[(str(r), str(p))]) for r, p in zip(extra.race_id, extra.point)
    ]
    return extra


def build_new_slot_cache(features: pd.DataFrame, source: pd.DataFrame, full_cache: pd.DataFrame) -> pd.DataFrame:
    point = full_cache.set_index(["api_record_id", "point"], drop=False)
    source_by_id = source.set_index("api_record_id", drop=False)
    specs = {"s1f": "S1F", "c4": "4C", "g1f": "G1F"}
    rows = []
    for target in features.itertuples(index=False):
        ids = list(target.last5_same_source_ids or [])
        assert len(ids) <= 5 and len(ids) == len(set(map(int, ids)))
        for slot_no, source_id in enumerate(ids, 1):
            source_id = int(source_id)
            assert source_id in source_by_id.index
            past = source_by_id.loc[source_id]
            assert isinstance(past, pd.Series) and bool(past.started)
            assert str(past.horse_id) == str(target.horse_id)
            assert int(past.race_distance_m) == int(target.distance_m)
            assert str(past.race_date) <= str(target.history_cutoff)
            record = dict(
                target_api_record_id=int(target.api_record_id), source_api_record_id=source_id,
                slot_oldest_to_newest=int(slot_no), slot_position=int(slot_no),
                source_horse_id=str(past.horse_id), source_distance_m=int(past.race_distance_m),
                source_race_id=str(past.race_id), source_race_date=str(past.race_date),
                target_cutoff=str(target.history_cutoff), target_horse_id=str(target.horse_id),
                target_distance_m=int(target.distance_m),
                source_snapshot_valid_time=bool(past.valid_time),
            )
            values = {}
            for prefix, point_name in specs.items():
                p = point.loc[(source_id, point_name)]
                assert isinstance(p, pd.Series)
                perm = bool(p.point_permutation_valid)
                group_gate = bool(p.api303_group_gate_supported)
                race_gate = bool(p.race_point_eligible)
                assert race_gate == (perm and group_gate)
                order_ok = bool(p.local_rank_ok)
                r = float(p.normalized_rank) if pd.notna(p.normalized_rank) else np.nan
                order = float(p.quality_order_value) if pd.notna(p.quality_order_value) else np.nan
                record.update({
                    f"{prefix}_r": r,
                    f"{prefix}_order": order,
                    f"{prefix}_order_status": str(p.quality_order_status),
                    f"{prefix}_individual_order_valid": order_ok,
                    f"{prefix}_full_point_permutation_valid": perm,
                    f"{prefix}_race_point_eligible": race_gate,
                    f"{prefix}_api303_group_status": str(p.api303_group_status),
                    f"{prefix}_group_status_gate": group_gate,
                    f"{prefix}_api303_group_status_gate": group_gate,
                    f"{prefix}_group_interval_parse_pass_diagnostic_only": bool(p.api303_interval_parse_pass_diagnostic_only),
                    f"{prefix}_final_point_eligible": bool(p.source_snapshot_valid_time and race_gate and np.isfinite(r)),
                })
                values[prefix] = r
            record["full_started_n"] = int(p.full_started_n)
            record["s1f_to_c4_pair_eligible"] = bool(record["s1f_final_point_eligible"] and record["c4_final_point_eligible"])
            record["s1f_to_c4_forward_change"] = values["s1f"] - values["c4"] if record["s1f_to_c4_pair_eligible"] else np.nan
            record["c4_to_g1f_pair_eligible"] = bool(record["c4_final_point_eligible"] and record["g1f_final_point_eligible"])
            record["c4_to_g1f_forward_change"] = values["c4"] - values["g1f"] if record["c4_to_g1f_pair_eligible"] else np.nan
            rows.append(record)
    return pd.DataFrame(rows)


def compare_exact(generated: pd.DataFrame, expected: pd.DataFrame, columns: list[str], label: str) -> dict:
    left = generated.sort_values("api_record_id", kind="stable").reset_index(drop=True)
    right = expected.sort_values("api_record_id", kind="stable").reset_index(drop=True)
    assert left.api_record_id.astype("int64").equals(right.api_record_id.astype("int64")), f"{label} IDs/order differ"
    errors = {}
    for c in columns:
        if c in {"grade_raw", "previous_sex", "previous_result_status"}:
            assert left[c].astype("string").fillna("<NULL>").equals(right[c].astype("string").fillna("<NULL>")), c
            errors[c] = 0.0
        else:
            a = pd.to_numeric(left[c], errors="coerce").to_numpy(float)
            b = pd.to_numeric(right[c], errors="coerce").to_numpy(float)
            assert np.allclose(a, b, rtol=0, atol=1e-12, equal_nan=True), c
            delta = np.abs(a - b)
            errors[c] = float(np.nanmax(delta)) if np.isfinite(delta).any() else 0.0
    return {"columns": columns, "max_abs_error": max(errors.values(), default=0.0), "column_errors": errors}


def main() -> dict:
    assert not OUT_FEATURES.exists() and not OUT_RECEIPT.exists(), "refusing to overwrite dry-run artifacts"
    baseline_builder = load_module("fresh_period_dryrun_baseline_builder", PROFILE / "run.py")
    field_builder = load_module("fresh_period_dryrun_field_builder", FIELD / "run.py")
    finish_builder = load_module("fresh_period_dryrun_finish_builder", FINISH / "prepare.py")
    style_builder = load_module("fresh_period_dryrun_style_builder", STYLE / "prepare.py")
    style_audit = load_module("fresh_period_dryrun_style_audit", STYLE_AUDIT / "audit_source_definitions.py")

    old_source = pd.read_parquet(PROFILE / "outputs_v2/source_snapshot.parquet")
    fresh_source = pd.read_parquet(ROOT_REVIEW / "ROOT_RAW_NEW_ROWS.parquet")
    old_source["horse_id"] = old_source.horse_id.astype("string")
    fresh_source["horse_id"] = fresh_source.horse_id.astype("string")
    fresh_source["started"] = strict_bool(fresh_source.started, "fresh.started")
    fresh_source["valid_time"] = strict_bool(fresh_source.valid_time, "fresh.valid_time")
    source = pd.concat([old_source, fresh_source], ignore_index=True, sort=False)
    source["race_date"] = source.race_date.astype("string")
    source["race_id"] = source.race_id.astype("string")
    source["year"] = pd.to_numeric(source.year, errors="raise").astype("int64")
    source["api_record_id"] = pd.to_numeric(source.api_record_id, errors="raise").astype("int64")
    assert source.api_record_id.is_unique
    source = source.sort_values(["race_date", "race_number", "horse_number", "api_record_id"], kind="stable").reset_index(drop=True)
    assert old_source.race_date.max() == "2026-09-19" and fresh_source.race_date.min() > "2026-09-19"
    assert len(fresh_source) == 464 and fresh_source.race_id.nunique() == 49

    old_ledger = pd.read_csv(PROFILE / "outputs_v2/race_inclusion_ledger.csv", dtype={"race_id": "string"})
    target_roster = pd.read_parquet(ROOT_REVIEW / "ROOT_TARGET_ROSTER.parquet")
    target_roster["api_record_id"] = target_roster.api_record_id.astype("int64")
    assert len(target_roster) == 426 and target_roster.race_id.nunique() == 45
    included_ids = set(target_roster.race_id.astype(str))
    new_races = fresh_source[["race_id", "race_date", "year", "race_distance_m"]].drop_duplicates("race_id").copy()
    assert len(new_races) == 49
    new_races["included"] = new_races.race_id.astype(str).isin(included_ids)
    new_races["reasons"] = np.where(new_races.included, "", "source_roster_quality_hold")
    ledger = pd.concat([old_ledger, new_races], ignore_index=True, sort=False)
    assert ledger.race_id.is_unique

    j1 = baseline_builder.build_features(source, ledger)
    r1 = field_builder.relative(j1)
    quality = finish_builder.race_quality(source)
    f1, _ = finish_builder.build_history_features(r1, source, quality)

    old_full = pd.read_parquet(STYLE_AUDIT / "api4_full_started_point_quality_cache.parquet")
    old_slots = pd.read_parquet(STYLE_AUDIT / "actual_slot_point_eligibility.parquet")
    extra_full_raw = pd.read_parquet(ROOT_REVIEW / "ROOT_EXTRA_FULL_POINT_CACHE.parquet")
    extra_groups = pd.read_parquet(ROOT_REVIEW / "ROOT_EXTRA_SELECTED_GROUPS.parquet")
    extra_full = build_full_point_cache(extra_full_raw, source, extra_groups, style_audit)
    full_cache = pd.concat([old_full, extra_full], ignore_index=True, sort=False)
    assert not full_cache.duplicated(["api_record_id", "point"]).any()

    fresh_features_f1 = f1.loc[f1.api_record_id.isin(set(target_roster.api_record_id))].copy()
    assert len(fresh_features_f1) == 426
    target_slots = pd.read_parquet(ROOT_REVIEW / "ROOT_TARGET_STYLE_SLOTS.parquet")
    derived_slots = build_new_slot_cache(fresh_features_f1, source, full_cache)
    target_pairs = set(zip(target_slots.target_api_record_id.astype("int64"), target_slots.source_api_record_id.astype("int64")))
    derived_pairs = set(zip(derived_slots.target_api_record_id.astype("int64"), derived_slots.source_api_record_id.astype("int64")))
    assert target_pairs == derived_pairs and len(derived_slots) == len(target_slots), "last5 slot IDs/order differ from root census"
    slot_cache = pd.concat([old_slots, derived_slots], ignore_index=True, sort=False)
    style_builder._validate_cache_shape(full_cache, slot_cache)
    point_checks = style_builder._validate_full_point_permutations(full_cache, source, slot_cache)
    style_features, _ = style_builder.build_style_features(f1, source, slot_cache)
    fresh_30 = style_features.loc[style_features.api_record_id.isin(set(target_roster.api_record_id))].copy()
    fresh_30 = fresh_30.sort_values(["race_date", "race_id", "horse_number"], kind="stable").reset_index(drop=True)

    reference_30 = pd.read_parquet(ROOT_REVIEW / "ROOT_FRESH_BASE30.parquet")
    reference_features = json.loads((STYLE / "outputs/F1_STYLE6_2026/meta.json").read_text(encoding="utf-8"))["features"]
    candidate_features = json.loads((ROOT / "jeju/research/20261018_debut_trial_ablation_v1/outputs/F1_STYLE6_DEBUT_TRIAL4_2026/meta.json").read_text(encoding="utf-8"))["features"]
    assert reference_features == candidate_features[:30] == BASE_FEATURES
    assert candidate_features[30:] == [
        "trial_peer_relative_time_mean3", "trial_peer_relative_time_n3",
        "trial_days_since_latest_event_pre", "trial_event_count_pre",
    ]
    comparison = compare_exact(fresh_30, reference_30, BASE_FEATURES, "root fresh 30-input reference")
    assert comparison["max_abs_error"] <= 1e-12

    with OUT_FEATURES.open("xb") as stream:
        fresh_30.to_parquet(stream, index=False)
    receipt = {
        "passed": True,
        "status": "root_snapshot_feature_builder_dryrun_only",
        "database_opened": False,
        "fresh_outcomes_paired_with_scores": False,
        "fresh_model_predictions_or_metrics_computed": False,
        "candidate_fit_or_calibration_calls": 0,
        "scope": {"raw_rows_for_history": 464, "raw_races": 49, "eligible_target_rows": 426,
                  "eligible_target_races": 45, "cold_target_rows": int(fresh_30.observed_starts.eq(0).sum()),
                  "cold_target_races": int(fresh_30.loc[fresh_30.observed_starts.eq(0), "race_id"].nunique()),
                  "target_dates": sorted(fresh_30.race_date.unique().tolist())},
        "style_full_point_checks": int(point_checks),
        "fresh_target_style_slots": int(len(derived_slots)),
        "independent_root_reference": comparison,
        "input_hashes": {
            str(p.relative_to(ROOT)): sha(p) for p in [
                PROFILE / "outputs_v2/source_snapshot.parquet",
                PROFILE / "outputs_v2/race_inclusion_ledger.csv",
                STYLE_AUDIT / "api4_full_started_point_quality_cache.parquet",
                STYLE_AUDIT / "actual_slot_point_eligibility.parquet",
                ROOT_REVIEW / "ROOT_RAW_NEW_ROWS.parquet",
                ROOT_REVIEW / "ROOT_TARGET_ROSTER.parquet",
                ROOT_REVIEW / "ROOT_EXTRA_FULL_POINT_CACHE.parquet",
                ROOT_REVIEW / "ROOT_EXTRA_SELECTED_GROUPS.parquet",
                ROOT_REVIEW / "ROOT_TARGET_STYLE_SLOTS.parquet",
                ROOT_REVIEW / "ROOT_FRESH_BASE30.parquet",
            ]
        },
        "output_sha256": sha(OUT_FEATURES),
        "source_auditor_bundle_finalized": False,
        "root_scoring_release_received": False,
    }
    with OUT_RECEIPT.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return receipt


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))

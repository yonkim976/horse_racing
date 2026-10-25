"""Independent, read-only checks for the frozen style-history source cache."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "jeju/research/20261010_style_history_source_audit_v1"
F1 = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs"
PROFILE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2"
POINTS = {"S1F": "s1f", "4C": "c4", "G1F": "g1f"}
FIELD_NAMES = {"S1F": "sjS1fOrd", "4C": "sj_4cOrd", "G1F": "sjG1fOrd"}
ORDER_OK = {"api_positive_unreviewed", "website_corrected"}
GROUP_OK = {"api_group_unreviewed", "api_group_unavailable"}


def assert_artifact_hashes(receipt: dict) -> None:
    for name, meta in receipt["artifacts"].items():
        path = SOURCE / name
        assert path.is_file() and path.stat().st_size == int(meta["bytes"]), name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == meta["sha256"], name


def verify() -> dict:
    receipt = json.loads((SOURCE / "source_audit.json").read_text())
    assert receipt["passed"] is True
    assert receipt["fit_or_prediction_work"] is False
    assert receipt["db_write"] is False
    assert receipt["uri_mode_ro_and_query_only"] is True
    assert_artifact_hashes(receipt)

    full = pd.read_parquet(SOURCE / "api4_full_started_point_quality_cache.parquet")
    slots = pd.read_parquet(SOURCE / "actual_slot_point_eligibility.parquet")
    snapshot = pd.read_parquet(PROFILE / "source_snapshot.parquet")
    features = pd.read_parquet(F1 / "features.parquet")
    assert len(full) == 186744 and full.race_id.nunique() == 6269
    assert len(slots) == 178459
    assert len(features) == 52155 and features.race_id.nunique() == 5206
    assert int(features.year.ge(2024).sum()) == 17412
    assert int(features.loc[features.year.ge(2024), "race_id"].nunique()) == 1779

    roster = receipt["f1_population"]["full_roster_reconciliation"]
    assert roster["referenced_races"] == 6269
    assert roster["full_race_result_rows"] == roster["snapshot_rows_in_referenced_races"] == 62709
    assert roster["full_race_result_started_rows"] == roster["snapshot_started_rows_in_referenced_races"] == 62248
    for key in (
        "races_where_snapshot_started_n_differs_from_full",
        "full_started_null_api_id", "full_started_null_horse_id",
        "full_started_null_horse_number", "full_started_duplicate_api_id_rows",
        "full_started_duplicate_horse_id_rows", "full_started_duplicate_horse_number_rows",
    ):
        assert roster[key] == 0, key
    assert roster["snapshot_common_rows_exactly_match_full_base"] is True

    assert not full.duplicated(["race_id", "point", "api_record_id"]).any()
    assert not full.duplicated(["race_id", "point", "horse_id"]).any()
    assert not full.duplicated(["race_id", "point", "horse_number"]).any()
    assert full.field_name.astype(str).equals(full.point.map(FIELD_NAMES).astype(str))
    group_keys = ["race_id", "point"]
    grouped = full.groupby(group_keys, sort=False)
    point_audit = grouped.agg(
        rows=("api_record_id", "size"), n=("full_started_n", "first"),
        n_values=("full_started_n", "nunique"), api_ids=("api_record_id", "nunique"),
        horse_ids=("horse_id", "nunique"), horse_numbers=("horse_number", "nunique"),
        perm_n=("api4_order_permutation_valid", "nunique"), alias_n=("point_permutation_valid", "nunique"),
        complete_n=("complete_unique_1_to_n_permutation", "nunique"),
        group_status_n=("api303_group_status", "nunique"), gate_n=("api303_group_gate_supported", "nunique"),
        gate_alias_n=("api303_group_status_gate", "nunique"), race_point_n=("race_point_eligible", "nunique"),
        perm=("api4_order_permutation_valid", "first"), group_status=("api303_group_status", "first"),
        group_gate=("api303_group_gate_supported", "first"), race_point=("race_point_eligible", "first"),
    )
    assert point_audit.n_values.eq(1).all()
    assert point_audit.rows.eq(point_audit.n).all()
    assert point_audit.n.eq(point_audit.api_ids).all()
    assert (point_audit.n == point_audit.horse_ids).all()
    assert (point_audit.n == point_audit.horse_numbers).all()
    assert point_audit[["perm_n", "alias_n", "complete_n", "group_status_n", "gate_n",
                        "gate_alias_n", "race_point_n"]].eq(1).all().all()
    assert point_audit.perm.astype(bool).equals(full.groupby(group_keys, sort=False).point_permutation_valid.first().astype(bool))
    assert point_audit.perm.astype(bool).equals(full.groupby(group_keys, sort=False).complete_unique_1_to_n_permutation.first().astype(bool))
    assert point_audit.group_gate.astype(bool).equals(point_audit.group_status.astype(str).isin(GROUP_OK))
    assert point_audit.race_point.astype(bool).equals(point_audit.perm.astype(bool) & point_audit.group_gate.astype(bool))
    perm_rows = full.loc[full.api4_order_permutation_valid.astype(bool)].copy()
    perm_rows["order_num"] = pd.to_numeric(perm_rows.quality_order_value, errors="coerce")
    perm_rows["order_integral"] = perm_rows.order_num.notna() & np.isclose(perm_rows.order_num, np.round(perm_rows.order_num))
    assert perm_rows.local_rank_ok.all() and perm_rows.quality_order_status.astype(str).isin(ORDER_OK).all()
    assert perm_rows.order_integral.all()
    assert perm_rows.order_num.ge(1).all() and (perm_rows.order_num <= perm_rows.full_started_n).all()
    order_stats = perm_rows.groupby(group_keys, sort=False).order_num.agg(["count", "nunique", "min", "max"])
    expected_n = point_audit.loc[point_audit.perm.astype(bool), "n"].astype(float)
    order_stats = order_stats.reindex(expected_n.index)
    assert np.array_equal(order_stats["count"].to_numpy(float), expected_n.to_numpy(float))
    assert np.array_equal(order_stats["nunique"].to_numpy(float), expected_n.to_numpy(float))
    assert order_stats["min"].eq(1).all()
    assert np.array_equal(order_stats["max"].to_numpy(float), expected_n.to_numpy(float))
    full_n = full.full_started_n.to_numpy(float)
    orders = pd.to_numeric(full.quality_order_value, errors="coerce").to_numpy(float)
    rank = pd.to_numeric(full.normalized_rank, errors="coerce").to_numpy(float)
    usable = (full.api4_order_permutation_valid.astype(bool) & full.api303_group_gate_supported.astype(bool)).to_numpy()
    assert np.array_equal(np.isfinite(rank), usable)
    assert np.allclose(rank[usable], (orders[usable] - 1) / (full_n[usable] - 1), rtol=0, atol=1e-12)
    checks = len(point_audit)

    race_ids = set(full.race_id.astype(str))
    snapshot_races = snapshot.loc[snapshot.race_id.astype(str).isin(race_ids)]
    snapshot_starters = snapshot_races.loc[snapshot_races.started.astype(bool)]
    assert len(snapshot_races) == 62709 and len(snapshot_starters) == 62248
    full_ids = {str(race): set(g.api_record_id.astype("int64"))
                for race, g in full.groupby("race_id", sort=False)}
    for race, group in snapshot_starters.groupby(snapshot_starters.race_id.astype(str), sort=False):
        assert set(group.api_record_id.astype("int64")) == full_ids[race]
    full_n_by_race = full.groupby("race_id", sort=False).full_started_n.first().astype(int).to_dict()

    assert not slots.duplicated(["target_api_record_id", "slot_oldest_to_newest"]).any()
    assert slots.target_horse_id.astype(str).equals(slots.source_horse_id.astype(str))
    assert slots.target_distance_m.astype("int64").equals(slots.source_distance_m.astype("int64"))
    assert slots.slot_position.astype("int64").equals(slots.slot_oldest_to_newest.astype("int64"))
    assert slots.source_race_date.astype(str).le(slots.target_cutoff.astype(str)).all()
    snap = snapshot.set_index("api_record_id", drop=False)
    slot_lists = (slots.sort_values(["target_api_record_id", "slot_position"], kind="stable")
                  .groupby("target_api_record_id", sort=False).source_api_record_id
                  .agg(lambda values: [int(value) for value in values]).to_dict())
    for row in features[["api_record_id", "last5_same_source_ids"]].itertuples(index=False):
        actual = slot_lists.get(int(row.api_record_id), [])
        expected = [] if row.last5_same_source_ids is None else [int(x) for x in row.last5_same_source_ids]
        assert actual == expected and len(actual) <= 5 and len(actual) == len(set(actual)), int(row.api_record_id)
    target_attrs = features[["api_record_id", "horse_id", "distance_m", "race_date", "history_cutoff"]].copy()
    target_attrs["expected_cutoff"] = (pd.to_datetime(target_attrs.race_date, format="%Y-%m-%d")
                                       - pd.Timedelta(days=2)).dt.strftime("%Y-%m-%d")
    assert target_attrs.history_cutoff.astype(str).equals(target_attrs.expected_cutoff.astype(str))
    slot_target = slots.merge(target_attrs, left_on="target_api_record_id", right_on="api_record_id",
                              how="left", validate="many_to_one", suffixes=("_slot", "_target"))
    assert slot_target.api_record_id.notna().all()
    assert slot_target.target_horse_id.astype(str).equals(slot_target.horse_id.astype(str))
    assert slot_target.target_distance_m.astype("int64").equals(slot_target.distance_m.astype("int64"))
    assert slot_target.target_cutoff.astype(str).equals(slot_target.expected_cutoff.astype(str))
    assert slot_target.source_race_date.astype(str).le(slot_target.target_cutoff.astype(str)).all()
    assert slot_target.full_started_n.astype(int).equals(slot_target.source_race_id.map(full_n_by_race).astype(int))

    # Vectorized identity check for every actual slot's source-snapshot row.
    source_attrs = snapshot[["api_record_id", "race_id", "race_date", "horse_id",
                             "race_distance_m", "started", "valid_time"]]
    slot_source = slots.merge(source_attrs, left_on="source_api_record_id", right_on="api_record_id",
                              how="left", validate="many_to_one", suffixes=("_slot", "_snapshot"))
    assert slot_source.api_record_id.notna().all()
    assert slot_source.started.astype(bool).all()
    assert slot_source.source_race_id.astype(str).equals(slot_source.race_id.astype(str))
    assert slot_source.source_race_date.astype(str).equals(slot_source.race_date.astype(str))
    assert slot_source.source_horse_id.astype(str).equals(slot_source.horse_id.astype(str))
    assert slot_source.source_distance_m.astype("int64").equals(slot_source.race_distance_m.astype("int64"))
    assert slot_source.source_snapshot_valid_time.astype(bool).equals(slot_source.valid_time.astype(bool))

    for point, prefix in POINTS.items():
        perm = slots[f"{prefix}_full_point_permutation_valid"].astype(bool)
        group_gate = slots[f"{prefix}_group_status_gate"].astype(bool)
        status = slots[f"{prefix}_api303_group_status"].astype(str)
        assert group_gate.equals(status.isin(GROUP_OK))
        assert slots[f"{prefix}_api303_group_status_gate"].astype(bool).equals(group_gate)
        assert slots[f"{prefix}_race_point_eligible"].astype(bool).equals(perm & group_gate)
        n = slots.full_started_n.to_numpy(float)
        order = slots[f"{prefix}_order"].to_numpy(float)
        rank = slots[f"{prefix}_r"].to_numpy(float)
        usable = (perm & group_gate).to_numpy()
        assert np.array_equal(np.isfinite(rank), usable)
        assert np.allclose(rank[usable], (order[usable] - 1) / (n[usable] - 1), rtol=0, atol=1e-12)
        expected_point_eligible = slots.source_snapshot_valid_time.astype(bool) & usable
        assert slots[f"{prefix}_final_point_eligible"].astype(bool).to_numpy().tolist() == expected_point_eligible.tolist()

    for left, right, flag, value in (
        ("s1f", "c4", "s1f_to_c4_pair_eligible", "s1f_to_c4_forward_change"),
        ("c4", "g1f", "c4_to_g1f_pair_eligible", "c4_to_g1f_forward_change"),
    ):
        expected = slots[f"{left}_final_point_eligible"].astype(bool) & slots[f"{right}_final_point_eligible"].astype(bool)
        assert slots[flag].astype(bool).equals(expected)
        observed = slots[value].to_numpy(float)
        assert np.array_equal(np.isfinite(observed), expected.to_numpy())
        change = slots[f"{left}_r"].to_numpy(float) - slots[f"{right}_r"].to_numpy(float)
        assert np.allclose(observed[expected.to_numpy()], change[expected.to_numpy()], rtol=0, atol=1e-12)

    valid_counts = {
        "s1f_final_point_eligible": int(slots.s1f_final_point_eligible.sum()),
        "s1f_to_c4_pair_eligible": int(slots.s1f_to_c4_pair_eligible.sum()),
        "c4_to_g1f_pair_eligible": int(slots.c4_to_g1f_pair_eligible.sum()),
    }
    assert valid_counts == {
        "s1f_final_point_eligible": 177688,
        "s1f_to_c4_pair_eligible": 177450,
        "c4_to_g1f_pair_eligible": 177498,
    }
    chronology = pd.read_csv(SOURCE / "point_time_chronology_by_distance.csv")
    assert chronology.s1f_not_before_c4_time_n.sum() == 0
    assert chronology.c4_not_before_finish_minus_g1f_checkpoint_n.sum() == 0
    assert receipt["chronology_and_distance"]["time_consistency_not_feature_or_source_gate"] is True

    return {
        "passed": True,
        "full_cache_rows": int(len(full)),
        "source_races": int(full.race_id.nunique()),
        "race_point_groups_checked": checks,
        "full_started_rows": int(len(snapshot_starters)),
        "snapshot_full_roster_set_mismatches": 0,
        "actual_history_slots": int(len(slots)),
        "target_rows": int(len(features)),
        "target_races": int(features.race_id.nunique()),
        "eval_rows": int(features.year.ge(2024).sum()),
        "eval_races": int(features.loc[features.year.ge(2024), "race_id"].nunique()),
        "valid_slot_counts": valid_counts,
        "fit_or_prediction_work": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))

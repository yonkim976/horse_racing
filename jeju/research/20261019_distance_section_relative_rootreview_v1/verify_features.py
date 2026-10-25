"""Independent arithmetic, chronology, and aggregation review of frozen inputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "jeju/research/20261019_distance_section_relative_source_v1"
MODEL = ROOT / "jeju/research/20261019_distance_section_relative_ablation_v1/outputs"
DISTANCES = [900, 1000, 1110, 1200]


def load(name):
    return pd.read_parquet(SOURCE / f"{name}.parquet")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def main():
    baseline = pd.read_parquet(ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet")
    raw = pd.read_parquet(ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet")
    frozen = load("target_f1_style6_features")
    pd.testing.assert_frame_equal(baseline, frozen, check_exact=True)
    ref = load("reference_section_intervals").set_index("api_record_id").sort_index()
    roster = load("benchmark_reference_roster").set_index("api_record_id").sort_index()
    expected = raw.loc[raw.meet_code.eq(2) & raw.started & raw.race_distance_m.isin(DISTANCES)].set_index("api_record_id").sort_index()
    assert len(ref)==len(roster)==len(expected)==55860
    assert ref.index.equals(expected.index) and roster.index.equals(expected.index)
    for col in ["race_id","race_date","horse_id","horse_number","race_distance_m","valid_time"]:
        assert ref[col].astype("string").equals(expected[col].astype("string")), col
    assert not roster.horse_id.astype(str).eq("3005648").any()
    q = load("api4_quality_source_snapshot")
    assert q.api_record_id.is_unique
    assert not q.horse_id.astype(str).eq("3005648").any()
    masks = load("source_race_point_quality_masks")
    assert not masks.duplicated(["race_id","point"]).any()
    assert len(masks)==5668*4
    full_roster_n=int(masks.groupby("race_id").expected_full_roster_runner_rows.first().sum())
    assert full_roster_n==55914
    assert len(q)==55860 and set(q.api_record_id)==set(ref.index)
    if "quality_view_started_roster_complete" in masks:
        incomplete=masks.loc[~masks.quality_view_started_roster_complete]
        assert incomplete.race_id.nunique()==7 and not incomplete.point_clear_full_race.any()
    # Reconstruct the recorded fail-closed conjunction, then independently
    # bind the per-race mask to every reference participant used below.
    clear = (
        masks.order_started_api_id_set_exact & masks.order_started_horse_identity_exact
        & masks.group_status_coverage_present
        & masks.api303_selection_consistent_across_started_roster
        & masks.group_selected_source_fingerprint_matches_quality_view
        & masks.group_quality_status_matches_quality_view
        & masks.order_status_missing_or_unknown_or_hold_n.eq(0)
        & masks.group_status_missing_or_unknown_or_hold_n.eq(0)
    )
    assert clear.equals(masks.point_clear_full_race)
    mask_lookup=masks.set_index(["race_id","point"]).point_clear_full_race
    good={"api_positive_unreviewed","website_corrected"}
    endpoint_ok={}
    for point in ["s1f","c3","c4","g1f"]:
        vals=pd.to_numeric(ref[f"{point}_time_seconds"],errors="coerce")
        endpoint_ok[point]=np.isfinite(vals)&vals.gt(0)&ref[f"{point}_time_status"].isin(good)
        asserted=ref.race_id.map(mask_lookup.xs(point,level="point")).astype(bool)
        assert asserted.equals(ref[f"{point}_point_clear_full_race"])
    s,c3,c4,t,g1=[pd.to_numeric(ref[col],errors="coerce") for col in
                   ["s1f_time_seconds","c3_time_seconds","c4_time_seconds","finish_time_seconds","g1f_time_seconds"]]
    values={1:s,2:c3-s,3:c4-c3,4:t-g1-c4,5:g1}
    ends={1:["s1f"],2:["s1f","c3"],3:["c3","c4"],4:["c4","g1f"],5:["g1f"]}
    medians={}
    for seg,vals in values.items():
        expected_ok=np.isfinite(vals)&vals.gt(0)&ref.valid_time
        for point in ends[seg]:
            expected_ok &= endpoint_ok[point]&ref[f"{point}_point_clear_full_race"]
        if seg==4:
            expected_ok &= np.isfinite(t)&t.gt(0)
        assert expected_ok.equals(ref[f"seg_{seg}_feature_eligible"]), seg
        assert np.allclose(vals,ref[f"seg_{seg}_raw_delta_seconds"],rtol=0,atol=1e-12,equal_nan=True)
        assert np.allclose(vals.where(expected_ok),ref[f"seg_{seg}_feature_seconds"],rtol=0,atol=1e-12,equal_nan=True)
        x=ref.loc[expected_ok,["race_id","race_date","race_distance_m"]].copy()
        x["value"]=vals.loc[expected_ok]
        med=x.groupby(["race_id","race_date","race_distance_m"],sort=True).value.agg(["median","size"]).reset_index()
        medians[f"seg_{seg}"]=med
    complete=pd.concat(values,axis=1).notna().all(axis=1)
    assert np.allclose(pd.concat(values,axis=1).loc[complete].sum(axis=1),t.loc[complete],rtol=0,atol=1e-9)
    source_medians=load("reference_race_segment_medians")
    for seg,med in medians.items():
        worker=source_medians.loc[source_medians.segment_id.eq(seg)&source_medians.reference_race_eligible].set_index("race_id").sort_index()
        ours=med.set_index("race_id").sort_index()
        assert ours.index.equals(worker.index)
        assert np.allclose(ours["median"],worker.race_median_seconds,rtol=0,atol=1e-12)
        assert np.array_equal(ours["size"],worker.eligible_runner_n)
    stats=load("source_event_benchmark_stats")
    max_b_error=0.0
    for (dist,seg), group in stats.groupby(["race_distance_m","segment_id"],sort=True):
        med=medians[seg]
        med=med.loc[med.race_distance_m.eq(dist)].sort_values(["race_date","race_id"],kind="stable")
        dates=med.race_date.astype(str).to_numpy()
        vals=med["median"].to_numpy()
        for row in group.itertuples(index=False):
            cutoff=(pd.Timestamp(row.source_race_date)-pd.Timedelta(days=2)).date().isoformat()
            assert row.reference_cutoff_t_minus_2==cutoff
            n=int(np.count_nonzero(dates<=cutoff))
            assert row.prior_eligible_race_n==n and bool(row.benchmark_exists)==(n>=20)
            if n:
                assert str(row.reference_first_race_date)==dates[0]
                assert str(row.reference_last_race_date)==dates[n-1]<=cutoff
            if n>=20:
                err=abs(float(vals[:n].mean())-float(row.mean_of_prior_race_medians_seconds))
                assert err<2e-10,(dist,seg,cutoff,err)
                max_b_error=max(max_b_error,err)
            else:
                assert pd.isna(row.mean_of_prior_race_medians_seconds)
    slots=load("target_last5_lineage")
    long=load("target_last5_relative_history")
    assert len(slots)==135855 and len(long)==len(slots)*5
    assert not long.duplicated(["target_api_record_id","slot_oldest_to_newest","segment_id"]).any()
    expected_slots=pd.read_parquet(ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs/historical_lineage.parquet")
    target_ids=set(baseline.loc[baseline.distance_m.isin(DISTANCES),"api_record_id"])
    expected_slots=expected_slots.loc[expected_slots.history_kind.eq("last5_same_distance_start")&expected_slots.target_api_record_id.isin(target_ids)]
    keys=["target_api_record_id","slot_oldest_to_newest"]
    for col in ["source_api_record_id","source_race_date","target_cutoff","source_distance_m","source_horse_id"]:
        a=slots.set_index(keys).sort_index()[col].astype("string")
        b=expected_slots.set_index(keys).sort_index()[col].astype("string")
        assert a.equals(b),col
    assert slots.source_race_date.astype(str).le(slots.target_cutoff.astype(str)).all()
    bmap=stats.set_index(["source_race_id","segment_id"])
    for seg in [f"seg_{i}" for i in range(1,6)]:
        h=long.loc[long.segment_id.eq(seg)].copy()
        raw_values=h.source_api_record_id.map(ref[f"{seg}_raw_delta_seconds"])
        source_ok=h.source_api_record_id.map(ref[f"{seg}_feature_eligible"])
        local=bmap.xs(seg,level="segment_id")
        benchmark=h.source_race_id.map(local.mean_of_prior_race_medians_seconds)
        good_b=h.source_race_id.map(local.benchmark_exists)
        residual=(benchmark-raw_values).where(source_ok&good_b)
        assert np.allclose(residual,h.relative_performance_seconds,rtol=0,atol=1e-12,equal_nan=True)
    candidate_paths=list(MODEL.glob("features*.parquet"))
    assert len(candidate_paths)==1,candidate_paths
    feature_path=candidate_paths[0]
    candidate=pd.read_parquet(feature_path)
    pd.testing.assert_frame_equal(candidate[baseline.columns],baseline,check_exact=True)
    assert len(candidate.columns)==len(baseline.columns)+10
    for i in range(1,6):
        h=long.loc[long.segment_id.eq(f"seg_{i}")]
        grouped=h.groupby("target_api_record_id").relative_performance_seconds.agg(["mean","count"])
        expected_mean=candidate.api_record_id.map(grouped["mean"])
        expected_n=candidate.api_record_id.map(grouped["count"])
        expected_n=expected_n.where(~candidate.distance_m.isin(DISTANCES),expected_n.fillna(0))
        assert np.allclose(candidate[f"hist_relative_seg_{i}_mean5"],expected_mean,rtol=0,atol=1e-12,equal_nan=True)
        assert np.allclose(candidate[f"hist_relative_seg_{i}_n"],expected_n,rtol=0,atol=0,equal_nan=True)
    receipt=dict(passed=True,baseline_columns_unchanged=True,baseline_rows=len(baseline),
                 reference_rows=len(ref),reference_races=roster.race_id.nunique(),
                 quality_rows=len(q),full_point_mask_roster_rows=full_roster_n,
                 full_race_points=len(masks),
                 benchmark_rows_checked=len(stats),benchmark_max_abs_error=max_b_error,
                 target_slots_checked=len(slots),relative_interval_rows_checked=len(long),
                 added_features_checked=10,feature_sha256=sha(feature_path),
                 source_manifest_sha256=sha(SOURCE/"artifact_manifest.json"),
                 database_opened=False,models_fitted=0)
    with (HERE/"ROOT_FEATURE_REVIEW.json").open("x") as stream:
        json.dump(receipt,stream,ensure_ascii=False,indent=2)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()

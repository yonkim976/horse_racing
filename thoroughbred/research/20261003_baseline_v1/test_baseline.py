"""Checks for the substantive temporal and shared-distribution contracts."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import softmax

SPEC = importlib.util.spec_from_file_location("tb_restart", Path(__file__).with_name("run.py"))
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


def fixture():
    rows = []
    for date in ["2016-12-30", "2017-01-01", "2017-01-02", "2017-01-03", "2018-01-01"]:
        for horse in range(5):
            rows.append(dict(meet=1,race_date=pd.Timestamp(date),race_no=1,program_no=horse+1,
                horse_id=str(horse),horse_name=str(horse),race_key=f"1:{date}:1",outcome=horse+1,
                finish=60.+horse,result_distance=1000.,distance_m=1000.,grade_raw="국6",age=3.,
                carried_weight=54.,body_weight=470.+horse,sex="암",S1F_cumulative_time=14.,
                G1F_cumulative_time=47.+horse,G3F_cumulative_time=23.+horse,
                **{"1F_G_closing_time":np.nan,"3F_G_closing_time":np.nan}))
    return pd.DataFrame(rows)


def test_uniform_joint_and_all_pool_sums():
    ix,q,p = RUN.joint(np.zeros((7,3)),[1,1,1])
    np.testing.assert_allclose(q,1/(7*6*5))
    np.testing.assert_allclose(p,np.tile([1/7,2/7,3/7],(7,1)))
    _,_,qnl,qpl,tla = RUN.pool_probabilities(ix,q,7)
    np.testing.assert_allclose([qnl.sum(),qpl.sum(),tla.sum()],[1,3,1])
    np.testing.assert_allclose(qpl,3/21)


def test_extreme_scores_stay_finite_and_first_stage_matches_softmax():
    scores = np.array([[1000,-2000,900],[-1000,2000,-900],[0,0,0],[2,3,4],[5,-3,9]],float)
    _,q,p = RUN.joint(scores,[.35,4.,1.])
    assert np.isfinite(q).all() and (q>=0).all()
    assert (np.diff(p,axis=1)>=-1e-12).all()
    np.testing.assert_allclose(p.sum(axis=0),[1,2,3])
    np.testing.assert_allclose(p[:,0],softmax(scores[:,0]/.35))


def test_two_day_cutoff_and_warmup_are_distinct():
    h,_,_ = RUN.prepare_records(fixture())
    f,_ = RUN.build_features(h,2)
    target = f[(f.horse_id=="0") & f.race_date.eq("2017-01-03")].iloc[0]
    assert target.history_count==2  # Dec30 + Jan1; Jan2 must not enter.
    assert target.history_source_date==pd.Timestamp("2017-01-01")
    first = f[(f.horse_id=="0") & f.race_date.eq("2017-01-01")].iloc[0]
    assert first.history_count==1  # Warm-up contributes despite no warm-up target training.
    assert np.isnan(first.same_distance_last_finish)  # Old raw track time not pooled.


def test_current_and_future_outcomes_and_times_do_not_change_current_features():
    a = fixture()
    h,_,_ = RUN.prepare_records(a)
    f,contracts = RUN.build_features(h,2)
    b = a.copy()
    current_and_future = b.race_date.ge("2017-01-03")
    b.loc[current_and_future,"outcome"] = 92
    b.loc[current_and_future,"finish"] = 200.
    b.loc[current_and_future,"body_weight"] = 600.
    changed,_,_ = RUN.prepare_records(b)
    updated,_ = RUN.build_features(changed,2)
    columns = contracts["history_records"]
    left = f[f.race_date.eq("2017-01-03")].sort_values("horse_id")
    right = updated[updated.race_date.eq("2017-01-03")].sort_values("horse_id")
    pd.testing.assert_frame_equal(left[columns].reset_index(drop=True),right[columns].reset_index(drop=True))


def test_dnf_retained_nonstarter_omitted_top3_tie_held():
    a = fixture()
    date = a.race_date.eq("2017-01-03")
    a.loc[date & a.horse_id.eq("4"),"outcome"] = 92
    a.loc[a.race_date.eq("2017-01-02") & a.horse_id.eq("4"),"outcome"] = 95
    h,_,_ = RUN.prepare_records(a)
    assert len(h[date.reindex(h.index,fill_value=False)])==5
    assert h[h.race_date.eq("2017-01-02")].shape[0]==4
    ledger = RUN.cohort_ledger(a,h,5)
    assert ledger[ledger.race_date.eq("2017-01-03")].status.iloc[0]=="eligible"
    a.loc[date & a.horse_id.eq("3"),"outcome"] = 3
    h,_,_ = RUN.prepare_records(a)
    ledger = RUN.cohort_ledger(a,h,5)
    assert "nonunique_or_missing_top3" in ledger[ledger.race_date.eq("2017-01-03")].status.iloc[0]


def test_nullable_result_distance_and_plain_plan_distance_can_join():
    a = fixture()
    a["distance_m"] = a.distance_m.astype("int32")
    a["result_distance"] = a.result_distance.astype("Int32")
    a.loc[0,"result_distance"] = pd.NA
    h,_,_ = RUN.prepare_records(a)
    f,_ = RUN.build_features(h,2)
    assert len(f)==len(h)
    current = f[f.race_date.eq("2017-01-03")].sort_values("horse_id")
    np.testing.assert_array_equal(current.same_distance_history_count,[1,2,2,2,2])

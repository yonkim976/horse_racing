"""Check report claims, repeated-day equivalence, and source role/ID consistency."""

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'


def main():
    e=pd.read_csv(OUT/'adjusted_effects.csv')
    a=e[e.window_days.eq(14)&e.unit.eq('rows')&e.volume_controls].drop(columns='unit').reset_index(drop=True)
    b=e[e.window_days.eq(14)&e.unit.eq('days')&e.volume_controls].drop(columns='unit').reset_index(drop=True)
    pd.testing.assert_frame_equal(a,b,atol=1e-12,rtol=1e-12)
    joint=e[e.model.eq('joint_positive')&e.target.eq('top3')]
    assert joint.q.ge(.05).all()
    main_joint=joint[joint.window_days.eq(14)&joint.unit.eq('rows')&joint.volume_controls]
    assert ((main_joint.ci_low<=0)&(main_joint.ci_high>=0)).all()
    expected={('2018_2020','서울'):1.15,('2018_2020','부산'):2.18,
              ('2024_2025','서울'):0.55,('2024_2025','부산'):0.75}
    for (period,meet),value in expected.items():
        row=main_joint[main_joint.period.eq(period)&main_joint.meet.eq(meet)&main_joint.rider.eq('race')&main_joint.term.eq('count_5plus_vs_1')].iloc[0]
        assert round(row.estimate*100,2)==value
    win=e[e.model.eq('joint_positive')&e.target.eq('win')&e.rider.eq('race')&e.meet.eq('부산')&e.term.eq('last_d8_14_vs_d1_2')&e.unit.eq('rows')&e.volume_controls]
    old=win[win.period.eq('2018_2020')&win.window_days.eq(14)].iloc[0]
    old28=win[win.period.eq('2018_2020')&win.window_days.eq(28)].iloc[0]
    recent=win[win.period.eq('2024_2025')&win.window_days.eq(14)].iloc[0]
    assert round(old.estimate*100,2)==-6.55 and old.q<.05 and old.level_n==290
    assert round(old28.estimate*100,2)==-6.94 and old28.q<.05
    assert round(recent.estimate*100,2)==-.43 and recent.ci_low<0<recent.ci_high
    audit=pd.read_csv(OUT/'same_day_multiple_audit.csv')
    assert audit.multiple_jockey_dates.sum()==0 and audit.multiple_training_dates.sum()==8
    d=pd.read_parquet(ROOT/'thoroughbred/research/20261012_jockey_switch_trainer_intent/outputs/analysis_rows.parquet',
                      columns=['row_key','horse_id','date','jockey_id','meet','year'])
    d['meet_code']=d.meet.map({'서울':'1','부산':'3'})
    con=duckdb.connect(str(ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'),read_only=True)
    con.register('r',d)
    query="""SELECT r.year,r.meet,t.rider_type_raw,count(*) AS events,count(DISTINCT r.row_key) AS starts
      FROM r JOIN daily_training_rider_linked t ON t.official_horse_id=r.horse_id AND t.meet=r.meet_code
      AND t.event_date>=r.date-INTERVAL 14 DAY AND t.event_date<r.date
      AND t.rider_official_id_linked=r.jockey_id AND r.jockey_id!=''
      JOIN training_date_coverage c ON c.dataset=t.dataset AND c.event_date=t.event_date AND c.meet=t.meet
      AND c.selected_capture_id=t.capture_id WHERE c.coverage_status='complete_rows' AND NOT c.inventory_count_mismatch
      AND coalesce(trim(t.rider_type_raw),'')!='기수' GROUP BY ALL ORDER BY 1,2,3"""
    (OUT/'role_identity_consistency_query.sql').write_text(query+'\n')
    identities=con.execute(query).df();con.close()
    identities.to_csv(OUT/'role_identity_consistency_audit.csv',index=False)
    assert identities.events.sum()==3 and identities.year.eq(2019).all()
    features=pd.read_parquet(OUT/'dose_timing_features.parquet')
    assert features.jockey_rows.eq(features.jockey_days).all()
    assert features.race_jockey_rows.eq(features.race_jockey_days).all()
    for role in ['any','race']:
        assert not np.isinf(features[role+'_last_gap'].dropna()).any()
    (OUT/'followup_verification.json').write_text(json.dumps(dict(
        passed=True,count_day_estimates_and_q_equivalent_rows=len(a),
        main_joint_top3_all_95ci_include_zero=len(main_joint),joint_top3_all_sensitivity_q_not_below_005=len(joint),
        actual_jockey_count_five_plus_contrasts_checked=4,
        historical_busan_win_timing_signal_and_recent_uncertainty_checked=True,
        no_same_day_jockey_duplicates=True,
        role_identity_consistency_audit='Three observations in 2019 Busan match race rider ID but non-jockey raw role; raw role preserved; zero such recent observations',
        role_identity_audit_added_after_primary_results=True,primary_exposure_definition_unchanged=True,
        figure_visually_inspected=True,production_changed=False),ensure_ascii=False,indent=2)+'\n')
    print('Follow-up assertions and role/identity audit passed')


if __name__=='__main__':main()

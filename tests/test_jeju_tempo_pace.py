from datetime import date,timedelta
import math
from horse_racing.analysis.jeju_tempo_pace import build_features,historical_observations,group_position

def row(rid,day,horse=1,distance=1000):
    return dict(entry_id=rid*10+horse,race_id=rid,event_date=date(2025,1,day),horse_id=str(horse),
        horse_number=horse,distance_m=distance,grade='제5등급',track_class='dry',field_size=2,
        outcome_status='normal_completed',segment_quality='usable',finish_position=horse,
        total_seconds=80.+horse,s1f_seconds=18.+horse/10,g1f_seconds=17.+horse/10,
        early_rank=horse,c3_rank=horse,c4_rank=horse,c3_seconds=30.+horse/10,
        c4_seconds=45.+horse/10,tempo=2,corner_4='(1,2)')

def test_target_outcome_and_future_do_not_affect_features():
    rows=[row(1,1),row(1,1,2),row(2,4),row(2,4,2)]
    t=dict(entry_id=99,event_date=date(2025,1,4),horse_id='1',horse_number=1,distance_m=1000)
    a=build_features([t],historical_observations(rows,minimum=1))[0]
    rows[2]['total_seconds']=1.;rows[2]['finish_position']=2
    rows += [row(3,8),row(3,8,2)]
    b=build_features([t|{'finish_position':1,'tempo':5}],historical_observations(rows,minimum=1))[0]
    for k in a[0]:
        assert a[0][k]==b[0][k] or math.isnan(a[0][k]) and math.isnan(b[0][k])

def test_two_day_boundary_and_distance_separation():
    obs=historical_observations([row(1,1),row(1,1,2),row(2,2),row(2,2,2)],minimum=1)
    t=dict(entry_id=99,event_date=date(2025,1,3),horse_id='1',horse_number=2,distance_m=1000)
    _,l=build_features([t],obs)
    assert l[0]['source_entry_ids']==[11]
    f,_=build_features([t|{'distance_m':1110}],obs)
    assert f[0]['pace_history_count_3']==0
    assert math.isnan(f[0]['tempo_last'])

def test_par_uses_only_earlier_races_and_minimum():
    rows=[row(1,1),row(1,1,2),row(2,2),row(2,2,2),row(3,3),row(3,3,2)]
    obs=historical_observations(rows,minimum=1)
    assert math.isnan(obs[2]['par_total_residual'])
    assert obs[4]['par_reference_count']==1
    assert abs(obs[4]['par_total_residual']+.5)<1e-8
    assert all(math.isnan(x['par_total_residual']) for x in historical_observations(rows,minimum=20))

def test_group_notation_is_only_explicit_membership():
    assert group_position('(^3,6),(1,2,4)-5',1)==(3,1.)
    assert group_position('(^3,6),(1,2,4)-5',2)==(3,0.)
    assert math.isnan(group_position('1-2-3',1)[0])

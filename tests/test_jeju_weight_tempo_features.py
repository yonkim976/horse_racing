from datetime import date
import math
from horse_racing.analysis.jeju_weight_tempo_features import build,tempo_observations,TEMPO

def row(race,day,horse=1,weight=300):
    return dict(entry_id=race*10+horse,race_id=race,event_date=date(2025,1,day),horse_id=str(horse),
        distance_m=1000,grade='제5',tempo=2,outcome_status='normal_completed',segment_quality='usable',
        body_weight_kg=weight,total_seconds=80.+horse,s1f_seconds=18.,g1f_seconds=17.)


def test_current_weight_changes_only_current_weight_inputs():
    rows=[row(1,1),row(1,1,2),row(2,4),row(2,4,2)]
    a=build(rows)[0][-2]
    rows[2]['body_weight_kg']=310;rows[2]['total_seconds']=10;rows[2]['tempo']=5
    b=build(rows)[0][-2]
    assert a['live_weight_delta_kg']==0 and b['live_weight_delta_kg']==10
    for k in TEMPO:assert a[k]==b[k] or math.isnan(a[k]) and math.isnan(b[k])


def test_past_weight_T_minus_2_and_missing_current():
    f,lineage,_=build([row(1,1),row(2,2,weight=999),row(3,3,weight=None)])
    assert lineage[-1]['past_weight_entry_ids']==[11]
    assert math.isnan(f[-1]['live_weight_kg']) and math.isnan(f[-1]['live_weight_delta_kg'])


def test_tempo_reference_excludes_same_and_previous_day():
    rows=[row(1,1),row(1,1,2),row(2,2),row(2,2,2),row(3,3),row(3,3,2)]
    obs=tempo_observations(rows,minimum=1)
    assert math.isnan(obs[2]['tempo_residual_total'])
    assert obs[4]['tempo_reference_count']==1 and obs[4]['tempo_residual_total']==-.5
    assert all(math.isnan(r['tempo_residual_total']) for r in tempo_observations(rows))


def test_unknown_tempo_not_reconstructed_from_current_finish():
    rows=[row(1,1),row(1,1,2),row(2,3),row(2,3,2)]
    rows[-2]['tempo']=None;rows[-1]['tempo']=None
    assert math.isnan(tempo_observations(rows,minimum=1)[-1]['tempo_residual_total'])

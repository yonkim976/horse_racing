import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SPEC=importlib.util.spec_from_file_location('pace',Path(__file__).with_name('run.py'))
PACE=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(PACE)


def data():
    rows=[]
    for date in ['2016-12-30','2017-01-01','2017-01-02','2017-01-03','2018-01-01']:
        for horse in range(5):
            rows.append(dict(horse_id=str(horse),program_no=horse+1,race_key='1:'+date+':1',meet=1,
              race_date=pd.Timestamp(date),race_no=1,distance_m=1200.,grade=6.,grade_kind='국',year=pd.Timestamp(date).year,
              month=pd.Timestamp(date).month,field_size=5,previous_age=3.,S1F_fraction=horse/4.,G3F_fraction=(4-horse)/4.,
              S1F_lead=float(horse==0),G3F_lead=float(horse==4),S1F_front=float(horse<3),G3F_front=float(horse>1),
              advance=(horse-(4-horse))/4.,historical_start_time=14.+horse*.1))
    h=pd.DataFrame(rows)
    features=h.drop(columns=['S1F_fraction','G3F_fraction','S1F_lead','G3F_lead','S1F_front','G3F_front','advance','historical_start_time'])
    return features,h


def test_warmup_and_two_day_history_cutoff():
    f,h=data(); out,_=PACE.add_history(f,h,2,.2)
    first=out[out.race_date.eq('2017-01-01')].sort_values('horse_id')
    np.testing.assert_allclose(first.pace_last3_S1F_fraction,np.arange(5)/4.)
    target=out[out.race_date.eq('2017-01-03')]
    assert target.pace_source_date.eq('2017-01-01').all()
    assert target.pace_last10_S1F_fraction_count.eq(2).all()


def test_current_future_point_labels_do_not_enter_features():
    f,h=data(); out,columns=PACE.add_history(f,h,2,.2)
    h.loc[h.race_date.ge('2017-01-03'),'S1F_fraction']=1.
    h.loc[h.race_date.ge('2017-01-03'),'G3F_fraction']=0.
    h.loc[h.race_date.ge('2017-01-03'),'historical_start_time']=25.
    other,_=PACE.add_history(f,h,2,.2)
    a=out[out.race_date.eq('2017-01-03')][columns].reset_index(drop=True)
    b=other[other.race_date.eq('2017-01-03')][columns].reset_index(drop=True)
    pd.testing.assert_frame_equal(a,b)


def test_competitor_counts_are_relative_and_exclude_self():
    f,h=data(); out,_=PACE.add_history(f,h,2,.11)
    one=out[out.race_date.eq('2017-01-03')].sort_values('horse_id')
    np.testing.assert_array_equal(one.pace_close_competitors,[1,2,2,2,1])
    np.testing.assert_array_equal(one.pace_faster_competitors,[0,0,1,2,3])


def test_tempo_class_probabilities_include_uncertainty_and_sum_one():
    p=PACE.tempo_probabilities(14.,np.array([-.6,-.2,0.,.2,.6]),13.7,14.3)
    np.testing.assert_allclose(p,[.2,.6,.2]); assert np.isclose(p.sum(),1)
    np.testing.assert_allclose(PACE.tempo_probabilities(13.,np.array([0.]),13.7,14.3),[1,0,0])

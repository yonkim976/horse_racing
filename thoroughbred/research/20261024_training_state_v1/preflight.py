"""Verify temporal personal baselines and complete-population contracts before fit."""
import numpy as np
import pandas as pd
import study_common as c
import build_features as b

def main():
    dates=pd.to_datetime(['2019-01-01','2019-01-30','2019-02-20','2019-03-01','2019-03-02'])
    a=pd.DataFrame({'anchor_id':np.arange(5),'meet':1,'horse_id':'H','race_date':dates})
    z=pd.DataFrame({'anchor_id':np.arange(5),'training_source_max_date':dates-pd.Timedelta(days=2)})
    for name in c.BASIC:z[name]=np.arange(1,6,dtype=float)*10
    z['train_coverage28']=1.;z['train_days14']=2.;z['train_days28']=3.
    f=b.add_personal(a,z,2)
    assert f.train_self_history_n.tolist()==[0,1,2,3,3]
    assert np.isnan(f.train_minutes14_delta_self3.iloc[1])
    assert abs(f.train_minutes14_delta_self3.iloc[3]-20)<1e-12
    assert f.self_latest_race_date.iloc[4]==dates[2]  # Prior-day start excluded by T−2.
    changed=z.copy();changed.loc[4,'train_minutes14']=999999
    again=b.add_personal(a,changed,2)
    assert f.iloc[:4].equals(again.iloc[:4])
    checks={}
    for lag in [2,7]:
        d=pd.read_parquet(c.OUT/f'feature_delta_t{lag}.parquet');base=c.old.frame()
        assert len(d)==178497 and d.row_number.is_unique and not d.duplicated(c.KEY).any()
        assert d.train_coverage28.eq(1).all()
        assert d.train_days7.le(7).all() and d.train_days14.le(14).all() and d.train_days28.le(28).all()
        assert d.train_days7.le(d.train_days14).all() and d.train_days14.le(d.train_days28).all()
        assert d.loc[d.train_days28.eq(0),'train_minutes28'].isna().all()
        assert d.loc[d.train_qa_days28.gt(0),'train_minutes28'].isna().all()
        for name in ['training_source_max_date','self_latest_race_date']:
            assert (d[name].isna() | (d[name]<=base.race_date-pd.Timedelta(days=lag))).all()
        assert np.isinf(d[c.BASIC+c.PERSONAL].to_numpy(float)).sum()==0
        checks[str(lag)]={'rows':len(d),'races':int(base.race_key.nunique()),'evaluation_rows':int(base.year.ge(2024).sum())}
    c.save(c.OUT/'preflight.json',{'status':'passed','temporal_fixture_passed':True,'future_value_mutation_passed':True,
        'near_race_previous_start_excluded':True,'population_checks':checks})
    print('Preflight passed',flush=True)
if __name__=='__main__':main()

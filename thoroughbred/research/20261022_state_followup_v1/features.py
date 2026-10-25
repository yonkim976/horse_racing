"""Simple finishing-rank history with the same forward-only history universe."""
import numpy as np
import pandas as pd
import support as s

def observed_percentile(h):
    h=h.copy().reset_index(drop=True);values=np.full(len(h),np.nan)
    for ix in h.groupby('race_key',sort=False).indices.values():
        g=h.iloc[ix];rank=g.finish_order.to_numpy(float)
        normal=g.result_status.eq('finished').to_numpy()&np.isfinite(rank)&(rank>0)
        if normal.sum()<2:continue
        scores=rank[normal];y=(scores[:,None]<scores[None,:]).sum(1)+.5*((scores[:,None]==scores[None,:]).sum(1)-1)
        values[ix[normal]]=y/(len(scores)-1)
    h['fraction']=values
    return h

def build(f,h):
    h=observed_percentile(h).sort_values(['horse_id','race_date']).reset_index(drop=True)
    assert not h.duplicated(['horse_id','race_date']).any()
    g=h.groupby('horse_id',sort=False).fraction
    h['simple_last']=h.fraction
    h['simple_mean3']=g.transform(lambda v:v.rolling(3,min_periods=1).mean())
    h['simple_mean5']=g.transform(lambda v:v.rolling(5,min_periods=1).mean())
    h['simple_std5']=g.transform(lambda v:v.rolling(5,min_periods=2).std())
    h['simple_count_all']=h.fraction.notna().groupby(h.horse_id).cumsum().astype(float)
    total=h.fraction.fillna(0).groupby(h.horse_id).cumsum()
    h['simple_mean_all']=total/h.simple_count_all.replace(0,np.nan)
    h['simple_count5']=g.transform(lambda v:v.rolling(5,min_periods=1).count())
    cols=s.SIMPLE[:7]
    h=h.rename(columns={'race_date':'simple_source_date'})
    query=f[['horse_id','cutoff_date','row_number','race_key']].copy()
    joined=pd.merge_asof(query.sort_values('cutoff_date'),h[['horse_id','simple_source_date']+cols].sort_values('simple_source_date'),
        by='horse_id',left_on='cutoff_date',right_on='simple_source_date',direction='backward')
    joined=joined.sort_values('row_number').reset_index(drop=True)
    for col in ['simple_count_all','simple_count5']:joined[col]=joined[col].fillna(0)
    grouped=joined.groupby('race_key').simple_mean_all
    joined['simple_mean_all_field_gap']=joined.simple_mean_all-grouped.transform('mean')
    joined['simple_mean_all_field_rank']=grouped.rank(pct=True,method='average')
    assert (joined.simple_source_date.isna()|joined.simple_source_date.le(joined.cutoff_date)).all()
    return joined[['row_number','simple_source_date']+s.SIMPLE]

def main():
    s.check();assert not (s.OUT/'simple_features.parquet').exists()
    f=s.old.frame();h=s.oldstate.observations();out=build(f,h)
    out.to_parquet(s.OUT/'simple_features.parquet',index=False,compression='zstd')
    s.save(s.OUT/'feature_audit.json',{'rows':len(out),'history_rows':len(h),'features':s.SIMPLE,
        'sha256':s.sha(s.OUT/'simple_features.parquet'),'all_sources_before_cutoff':True,
        'future_outcomes_used_as_input':False})
    print('Simple features ready',len(out),s.storage(),flush=True)

if __name__=='__main__':main()

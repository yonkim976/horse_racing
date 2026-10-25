"""Forward-only, opponent-aware approximate state filters. No smoothing."""
import copy
import numpy as np
import pandas as pd
import duckdb
from scipy.special import expit
import common as c

NAMES=['rank_mean','rank_sd','distance_slope','distance_sd','rank_current','rank_current_sd',
       'form_mean','form_trend','form_sd','form_trend_sd','early_mean','early_sd',
       'close_mean','close_sd','risk_rate','rank_n','form_n','early_n','close_n','observed_n','days']

def prior():
    return dict(rank=np.zeros(2),rv=np.diag([2.,.5]),form=np.zeros(2),fv=np.diag([1.,.04]),
        section=np.zeros(2),sv=np.ones(2),n=np.zeros(4),risk=np.array([1.,49.]),date=None,starts=0)

def propagate(s,date):
    s=copy.deepcopy(s)
    days=0. if s['date'] is None else max(0.,float((date-s['date']).days))
    dt=min(days/30.,24.)
    decay=np.exp(-days/1500.)
    s['rank']*=decay
    s['rv']=s['rv']*decay**2+np.diag([.035,.008])*dt
    s['rv'][0,0]=min(s['rv'][0,0],2.)
    s['rv'][1,1]=min(s['rv'][1,1],.5)
    F=np.array([[1.,min(dt,6.)],[0.,np.exp(-days/240.)]])
    s['form']=F@s['form']
    s['fv']=F@s['fv']@F.T+np.diag([.035,.003])*dt
    s['section']*=decay
    s['sv']=np.minimum(s['sv']*decay**2+.04*dt,1.)
    s['risk']=np.array([1.,49.])+(s['risk']-np.array([1.,49.]))*np.exp(-days/730.)
    return s,days

class Filter:
    def __init__(self):self.horses={};self.latest=None

    def query(self,horse,date,distance):
        original=self.horses.get(horse,prior())
        s,days=propagate(original,date)
        h=np.array([1.,(float(distance)-1500.)/500.])
        v=[s['rank'][0],np.sqrt(s['rv'][0,0]),s['rank'][1],np.sqrt(s['rv'][1,1]),
           h@s['rank'],np.sqrt(h@s['rv']@h),*s['form'],np.sqrt(s['fv'][0,0]),
           np.sqrt(s['fv'][1,1]),s['section'][0],np.sqrt(s['sv'][0]),s['section'][1],
           np.sqrt(s['sv'][1]),s['risk'][0]/s['risk'].sum(),*s['n'],s['starts'],days]
        assert len(v)==len(NAMES) and np.isfinite(v).all()
        return v,original['date']

    def update(self,g):
        date=g.race_date.iloc[0]
        assert self.latest is None or date>=self.latest
        self.latest=date
        ids=g.horse_id.to_list()
        assert len(ids)==len(set(ids))
        states=[propagate(self.horses.get(h,prior()),date)[0] for h in ids]
        distance=float(g.result_distance.iloc[0]);h=np.array([1.,(distance-1500.)/500.])
        mu=np.array([h@s['rank'] for s in states]);var=np.array([h@s['rv']@h for s in states])
        rank=g.finish_order.to_numpy(float)
        normal=g.result_status.eq('finished').to_numpy() & np.isfinite(rank) & (rank>0)
        section=g[['early_adjusted','last600_adjusted']].to_numpy(float,copy=True)
        section[(section[:,0]<10)|(section[:,0]>25),0]=np.nan
        section[(section[:,1]<25)|(section[:,1]>70),1]=np.nan
        original_section=np.array([s['section'] for s in states])
        for i,(horse,s) in enumerate(zip(ids,states)):
            others=np.arange(len(g))!=i
            good=others & normal
            if normal[i] and good.sum()>=3:
                scale=1/np.sqrt(1+np.pi*(var[i]+var[good])/8)
                p=expit((mu[i]-mu[good])*scale)
                y=(rank[i]<rank[good]).astype(float)+.5*(rank[i]==rank[good])
                grad=float(np.mean((y-p)*scale)*4)
                curvature=float(np.mean(p*(1-p)*scale**2)*4)
                V=np.linalg.inv(np.linalg.inv(s['rv'])+curvature*np.outer(h,h))
                s['rank']=s['rank']+V@h*grad
                s['rv']=V;s['n'][0]+=1
            obs=float(g.record_index.iloc[i])
            if normal[i] and np.isfinite(obs):
                v=s['fv'];gain=v[:,0]/(v[0,0]+.8)
                residual=np.clip(obs-s['form'][0],-3*np.sqrt(v[0,0]+.8),3*np.sqrt(v[0,0]+.8))
                s['form']+=gain*residual
                s['fv']=v-np.outer(gain,v[0,:]);s['n'][1]+=1
            for k,seconds in enumerate([.45,1.2]):
                good=others & normal & np.isfinite(section[:,k])
                if normal[i] and np.isfinite(section[i,k]) and good.sum()>=3:
                    observation=original_section[good,k].mean()+(np.median(section[good,k])-section[i,k])/seconds
                    v=s['sv'][k];gain=v/(v+1.)
                    residual=np.clip(observation-s['section'][k],-3,3)
                    s['section'][k]+=gain*residual;s['sv'][k]=v*(1-gain);s['n'][2+k]+=1
            status=g.result_status.iloc[i]
            if status in ['finished','did_not_finish','disqualified']:
                s['risk'][0 if status!='finished' else 1]+=1
            s['date']=date;s['starts']+=1
            self.horses[horse]=s

def observations():
    h=pd.read_parquet(c.HISTORY)
    with duckdb.connect(str(c.DB),read_only=True) as db:
        raw=db.execute("""SELECT CAST(e.canonical_meet AS VARCHAR)||':'||strftime(e.race_date,'%Y%m%d')||':'||CAST(e.race_no AS VARCHAR) AS race_key,
            e.chul_no AS program_no, e.hr_no AS horse_id, e.finish_order, e.result_status, r.distance_m AS official_distance
            FROM entry_result e JOIN race r ON e.race_id=r.race_id
            WHERE e.canonical_meet IN (1,3) AND e.race_date>=DATE '2010-01-01'""").df()
    assert not raw.duplicated(c.KEY).any()
    h=h.merge(raw,on=c.KEY,how='left',validate='one_to_one')
    # Non-starters and absent outcomes cannot be treated as performances.
    h=h[h.result_status.isin(['finished','did_not_finish','disqualified'])].copy()
    h['result_distance']=h.result_distance.fillna(h.official_distance)
    missing=h[h.result_distance.isna()]
    exclusions={'missing_distance_rows':len(missing),'missing_distance_races':missing.race_key.unique().tolist()}
    h=h[h.result_distance.notna()].copy()
    for raw_col,adj in [('early','early_adjusted'),('last600','last600_adjusted')]:
        h[adj]=h[adj].fillna(h[raw_col])
    h=h.sort_values(['race_date','race_key','program_no']).reset_index(drop=True)
    h.attrs['exclusions']=exclusions
    return h

def generate(f,h,progress=False):
    filt=Filter();events=list(h.groupby('race_date',sort=True));cursor=0
    values=np.zeros((len(f),len(NAMES)));sources=np.full(len(f),np.datetime64('NaT','ns'),dtype='datetime64[ns]')
    for date,ix in f.groupby('cutoff_date',sort=True).indices.items():
        while cursor<len(events) and events[cursor][0]<=date:
            for _,g in events[cursor][1].groupby('race_key',sort=False):filt.update(g)
            cursor+=1
            if progress and cursor%300==0:print('state history days',cursor,flush=True)
        for i in ix:
            row=f.iloc[i];v,source=filt.query(row.horse_id,date,row.distance_m)
            values[i]=v
            if source is not None:
                assert source<=date
                sources[i]=np.datetime64(source)
    out=pd.DataFrame(values,columns=['state_'+x for x in NAMES])
    out['state_source_date']=pd.to_datetime(sources)
    for name in ['rank_current','form_mean','early_mean','close_mean']:
        col='state_'+name
        grouped=out[col].groupby(f.race_key)
        out[col+'_field_gap']=out[col]-grouped.transform('mean')
        out[col+'_field_rank']=grouped.rank(pct=True,method='average')
    out.insert(0,'row_number',f.row_number.to_numpy())
    return out

def main():
    c.check_inputs()
    assert not (c.OUT/'state_features.parquet').exists()
    f=c.base.load_frame();h=observations();out=generate(f,h,True)
    out.to_parquet(c.OUT/'state_features.parquet',index=False,compression='zstd')
    cols=[x for x in out if x.startswith('state_') and x!='state_source_date']
    c.save(c.OUT/'state_contract.json',{'features':cols,'count':len(cols),
        'rows':len(out),'observations':len(h),'historical_races':int(h.race_key.nunique()),'exclusions':h.attrs['exclusions'],
        'observations_from':str(h.race_date.min().date()),'observations_to':str(h.race_date.max().date()),
        'state_sha256':c.sha(c.OUT/'state_features.parquet'),
        'all_sources_before_cutoff':bool((out.state_source_date.isna()|out.state_source_date.le(f.cutoff_date)).all()),
        'prior':{'rank_variance':[2,.5],'form_variance':[1,.04],'risk':[1,49]},
        'approximate_uncertainty':True})
    print('state features complete',len(out),len(cols),c.storage_check(),flush=True)

if __name__=='__main__':main()

"""Read-only frozen sources and strictly prior late-survival history."""
from pathlib import Path
import importlib.util
import hashlib
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
O=HERE/'outputs'
M=O/'models'
PREV=R/'20261021_busan_joint_pace_stack'
spec=importlib.util.spec_from_file_location('pace57j',PREV/'experiment.py')
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
SEED=20261021


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def save(name,value):
    (O/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def check():
    for name,expected in json.loads((O/'input_manifest.json').read_text()).items():
        p=ROOT/name
        assert p.stat().st_size==expected['bytes'] and sha(p)==expected['sha256'],name


def add_labels(q):
    q=q.copy()
    q['g3front']=np.where(q.g3f_complete,q.g3f_p.le(1/3).astype(float),np.nan)
    q['g1front']=np.where(q.g1f_complete,q.g1f_p.le(1/3).astype(float),np.nan)
    known=q.raw_finish_rank.between(1,30)|q.raw_finish_rank.isin([91,92])
    q['top3']=np.where(known,q.raw_finish_rank.between(1,3).astype(float),np.nan)
    q['strict_survival']=np.where(q.g3front.notna()&q.g1front.notna()&known,
          (q.g3front.eq(1)&q.g1front.eq(1)&q.top3.eq(1)).astype(float),np.nan)
    return q


def histories(allq):
    q=add_labels(allq.sort_values(['horse_id','date']).reset_index(drop=True))
    lead=q.group_observed&q.role4.eq(0)
    cond=[lead&q.g3front.notna(),lead&q.g1front.notna(),lead&q.strict_survival.notna(),
          lead&q.g1front.eq(1)&q.top3.notna(),q.group_observed&~lead&q.top3.notna()]
    sources=['g3front','g1front','strict_survival','top3','top3']
    names=['leader_g3_hold','leader_g1_hold','leader_strict_survive','leader_g1_finish','nonleader_finish']
    values=np.column_stack([np.where(mask,q[col],np.nan) for mask,col in zip(cond,sources)])
    horse=q.horse_id.to_numpy();days=q.date.to_numpy('datetime64[D]').astype('int64');ix=np.arange(len(q))
    sums=np.zeros_like(values);counts=np.zeros_like(values)
    for lag in range(1,6):
        old=np.maximum(0,ix-lag);age=days-days[old]
        eligible=(ix>=lag)&(horse==horse[old])&(age>=2)&(age<=730)
        good=np.isfinite(values[old])&eligible[:,None]
        sums+=np.where(good,values[old],0);counts+=good
    out={}
    for j,name in enumerate(names):
        out[name+'_mean5']=np.divide(sums[:,j],counts[:,j],out=np.full(len(q),np.nan),where=counts[:,j]>0)
        out[name+'_n5']=counts[:,j]
    return q,pd.DataFrame(out)


def load():
    raw=pd.read_parquet(prior.PACE/'feature_context.parquet')
    allq,allh=histories(raw)
    take=allq.meet.eq('부산').to_numpy()
    q=allq.loc[take].reset_index(drop=True);h=allh.loc[take].reset_index(drop=True)
    original=pd.read_parquet(prior.PACE/'feature_context.parquet',columns=['row_key'])
    oldx=pd.read_parquet(prior.PACE/'feature_frame.parquet');oldx.index=original.row_key
    cols=[c for c in json.loads((prior.PACE/'feature_groups.json').read_text())['F'] if c!='jockey_changed']
    x=oldx.loc[q.row_key,cols].reset_index(drop=True)
    oldh=pd.read_parquet(PREV/'outputs/lead_history_additions.parquet')
    assert len(oldh)==len(q)==66240
    x=pd.concat([x,oldh],axis=1)
    rx=pd.read_parquet(PREV/'outputs/race_inputs.parquet')
    aux=pd.read_parquet(PREV/'outputs/aux_predictions.parquet')
    races=pd.read_parquet(PREV/'outputs/count_predictions.parquet')
    # This helper only reads previous inputs and builds in-memory matrices.
    p,b,d,extra=prior.main_inputs(q,x,None,rx,aux)
    j=pd.concat([d,extra['J']],axis=1)
    assert len(j.columns)==330 and not any('jockey' in c or 'trainer' in c for c in j)
    return q,h,x,races,aux,p,j


def ability_history(q,p):
    """Five prior normal Busan runs, including targets that did not finish normally."""
    out=np.full((len(q),2),np.nan)
    ps=p.sort_values(['horse_id','date'])
    groups={key:g for key,g in ps.groupby('horse_id',sort=False)}
    for horse,indices in q.groupby('horse_id',sort=False).groups.items():
        if horse not in groups:continue
        old=groups[horse];dates=pd.to_datetime(old.date).to_numpy('datetime64[D]').astype('int64')
        values=old.performance.to_numpy(float)
        prefix=np.r_[0,np.cumsum(values)]
        ix=np.asarray(indices);cut=q.loc[ix,'date'].to_numpy('datetime64[D]').astype('int64')-2
        end=np.searchsorted(dates,cut,side='right');start=np.maximum(0,end-5);n=end-start
        out[ix,0]=np.divide(prefix[end]-prefix[start],n,out=np.full(len(ix),np.nan),where=n>0)
        out[ix,1]=n
    return out


def build_bias_context(q,p):
    q=q.copy();ability=ability_history(q,p)
    q['prior_ability']=ability[:,0];q['prior_ability_n']=np.nan_to_num(ability[:,1])
    rank=q.groupby('source_key').prior_ability.rank(ascending=False,method='average',pct=True)
    q['ability_band']=np.where(rank.isna(),-1,np.where(rank.le(1/3),0,np.where(rank.le(2/3),1,2)))
    q['history_band']=np.where(q.prior_ability_n.le(2),0,np.where(q.prior_ability_n.le(4),1,2))
    q['field_band']=np.where(q.field_size.le(8),0,np.where(q.field_size.le(11),1,2))
    q['grade_band']=q.grade_num.fillna(-1).astype(int)
    q['leader']=q.group_observed&q.role4.eq(0)
    support=q.last600_peer_adv_n5.ge(3)&q.late_peer_adv_n5.ge(3)
    q['past_late_type']=np.select([~support,q.last600_peer_adv_mean5.gt(0)&q.late_peer_adv_mean5.gt(0),
        q.last600_peer_adv_mean5.gt(0),q.late_peer_adv_mean5.gt(0)],
        ['insufficient','both_fast','g3_only','g1_only'],default='neither')
    q['early_count']=q.source_key.map(pd.read_csv(prior.R/'20261021_busan_leader_pack_outcomes/outputs/race_outcomes.csv').set_index('source_key').leader_count)
    return q

"""Read-only body mass summaries and direct sex-by-distance contrasts."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from scipy.stats import t

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
SOURCE=HERE.parent/'20261007_sex_ability_gap'
PAIRS=[('암','수'),('거','수'),('암','거')]
LOAD=['weight','body_weight','weight_squared','body_squared']
FORM=['rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap']
FE=['distance_m','year','month','age','moisture','grade']
RESULT=[]


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def load():
    d=pd.read_parquet(SOURCE/'outputs/population.parquet')
    assert len(d)==151074 and d.source_key.nunique()==13928 and not d.row_key.duplicated().any()
    d['distance_group']=np.select([d.distance_m.le(1400),d.distance_m.le(1800)],['short','middle'],default='long')
    d['seconds_per_1000m']=1000*d.finish/d.distance_m
    d['age_squared']=d.age**2
    return d


def describe(d):
    rows=[]
    for scope,keys in [('all',['sex']),('venue',['meet','sex']),('distance_group',['meet','distance_group','sex']),('distance',['meet','distance_m','sex'])]:
        for k,g in d.groupby(keys):
            k=(k,) if not isinstance(k,tuple) else k
            row=dict(scope=scope,**dict(zip(keys,k)),n=len(g),horses=g.horse_id.nunique(),races=g.source_key.nunique())
            for col in ['body_weight','weight']:
                v=g[col];perhorse=g.groupby('horse_id')[col].mean()
                row.update({col+'_mean':v.mean(),col+'_median':v.median(),col+'_p20':v.quantile(.2),col+'_p80':v.quantile(.8),
                            col+'_horse_equal_mean':perhorse.mean()})
            row.update(win_rate=g.win.mean(),top3_rate=g.top3.mean())
            rows.append(row)
    pd.DataFrame(rows).to_csv(OUT/'weight_and_population_summary.csv',index=False)
    counts=d.groupby(['meet','distance_group','sex']).agg(n=('row_key','size'),horses=('horse_id','nunique'),races=('source_key','nunique'),days=('day_key','nunique')).reset_index()
    counts.to_csv(OUT/'distance_group_counts.csv',index=False)


def demean(x,c):
    n=np.bincount(c)
    m=np.column_stack([np.bincount(c,weights=a)/n for a in x.T])
    return x-m[c]


def numeric(g,cols):
    z=[];labels=[]
    for col in cols:
        v=g[col].to_numpy(float);missing=~np.isfinite(v)
        if missing.all():continue
        v=np.where(missing,np.median(v[~missing]),v)
        if v.std()>1e-10:z.append((v-v.mean())/v.std());labels.append(col)
        if missing.any():z.append(missing.astype(float));labels.append(col+'_missing')
    return np.column_stack(z) if z else np.empty((len(g),0)),labels


def cluster(score,ids,dfcor):
    ix=pd.factorize(ids)[0];n=ix.max()+1;s=np.bincount(ix,weights=score)
    return float(s@s)*n/(n-1)*dfcor,n


def supported(g,keys,target,reference):
    if len(g)<200:return False
    for sex in [target,reference]:
        z=g[g.sex.eq(sex)]
        if len(z)<100 or z.horse_id.nunique()<30 or z.day_key.nunique()<20:return False
    return not keys or len(g[keys].drop_duplicates())>=20


def run(g,target,reference,keys,cols,outcomes,meta,joint=False):
    raw=g[g.sex.isin([target,reference])].copy()
    q=raw.copy()
    if keys:q=q[q.groupby(keys,dropna=False).sex.transform('nunique').eq(2)].copy()
    if not len(q):return
    c=pd.factorize(pd.MultiIndex.from_frame(q[keys]))[0] if keys else np.zeros(len(q),int)
    sx=q.sex.eq(target).to_numpy(float)
    z,names=numeric(q,cols)
    groups=['short','middle'] if joint else ['all']
    if joint:
        indicator=np.column_stack([q.distance_group.eq(x).to_numpy(float) for x in groups])
        x=np.column_stack([sx[:,None]*indicator,*[z*indicator[:,j,None] for j in range(2)]])
        names=[f'target:{x}' for x in groups]+[f'{group}:{name}' for group in groups for name in names]
        vectors={'short_gap':np.array([1.,0.]),'middle_gap':np.array([0.,1.]),'middle_minus_short':np.array([-1.,1.])}
    else:
        x=np.column_stack([sx,z]);names=['target']+names;vectors={'all_gap':np.ones(1)}
    y=q[outcomes].to_numpy(float)
    xd,yd=demean(x,c),demean(y,c)
    gram=xd.T@xd;inv=np.linalg.pinv(gram,rcond=1e-12);beta=inv@xd.T@yd;resid=yd-xd@beta
    rank=np.linalg.matrix_rank(xd,tol=1e-8);df=len(q)-c.max()-1-rank
    proj=inv@gram;dfcor=(len(q)-1)/max(df,1)
    support={g:supported(q if g=='all' else q[q.distance_group.eq(g)],keys,target,reference) for g in groups}
    for kind,vshort in vectors.items():
        v=np.zeros(x.shape[1]);v[:len(vshort)]=vshort
        identifiable=np.allclose(proj@v,v,atol=1e-7)
        needed=['short','middle'] if kind=='middle_minus_short' else ([kind.split('_')[0]] if joint else ['all'])
        ok=identifiable and df>0 and all(support[a] for a in needed)
        for j,part in enumerate(outcomes):
            score=(xd@(inv@v))*resid[:,j]
            vh,nh=cluster(score,q.horse_id,dfcor);vd,nd=cluster(score,q.day_key,dfcor);vi,_=cluster(score,q.horse_id+':'+q.day_key,dfcor)
            se=np.sqrt(max(vh,vd,vh+vd-vi,0));crit=t.ppf(.975,min(nh,nd)-1)
            b=float(v@beta[:,j]) if identifiable else np.nan
            mult=100 if part in ['win','top3','top5'] else 1
            record=meta|dict(target=target,reference=reference,part=part,contrast=kind,
                difference=b*mult,se=se*mult,lower=(b-crit*se)*mult if ok else np.nan,upper=(b+crit*se)*mult if ok else np.nan,
                supported=ok,estimable=identifiable,input_pair_n=len(raw),common_n=len(q),excluded_fraction=1-len(q)/len(raw),
                fe_groups=int(c.max()+1),residual_df=int(df),design_rank=int(rank),horse_clusters=nh,date_clusters=nd,
                controls='|'.join(names),unit='kg' if part in ['body_weight','weight'] else ('percentage_points' if part in ['win','top3','top5'] else ('seconds_per_1000m' if part=='seconds_per_1000m' else 'seconds')))
            for dg in groups:
                s=q if dg=='all' else q[q.distance_group.eq(dg)]
                record[dg+'_n']=len(s);record[dg+'_target_n']=int(s.sex.eq(target).sum());record[dg+'_reference_n']=int(s.sex.eq(reference).sum())
                record[dg+'_horses']=s.horse_id.nunique();record[dg+'_races']=s.source_key.nunique()
            RESULT.append(record)


"""Read-only all-distance profiles and strictly prior-five research features."""

import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
DB=ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
DISTANCES=[1000,1200,1300,1400,1500,1600,1800,1900,2000,2200]
POINTS=['S1F','G8F','G6F','G4F','G3F','G2F','G1F']
REMAINING=dict(G8F=1600,G6F=1200,G4F=800,G3F=600,G2F=400,G1F=200)
STYLES=['선행잔류','선행이탈','선입잔류','선입이탈','중반진출','막판진출','후미정체','중단혼합']
SEED=20261021


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def save(name,x):
    (OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def check():
    for name,old in json.loads((OUT/'input_manifest.json').read_text()).items():
        p=ROOT/name
        assert p.stat().st_size==old['bytes'] and sha(p)==old['sha256'],name


def layout(dist):
    groups={0:['START'],200:['S1F'],dist:['FIN']}
    for p,remaining in REMAINING.items():
        if 0<dist-remaining<dist:groups.setdefault(dist-remaining,[]).append(p)
    return [(groups[x][0],x) for x in sorted(groups)]


def load():
    with duckdb.connect(str(DB),read_only=True) as c:
        d=c.execute('''SELECT result_date AS date,try_cast(result_race_no AS INT) AS race_no,
        horse_id_raw AS horse_id,horse_name_raw AS horse_name,try_cast(horse_program_no_raw AS INT) AS program_no,
        try_cast(race_distance_m_raw AS INT) AS distance,try_cast(result_rank_raw AS INT) AS finish_rank,
        try_cast(finish_time_seconds_raw AS DOUBLE) AS finish,grade_raw AS grade,
        try_cast(horse_age_raw AS DOUBLE) AS age,horse_sex_raw AS sex,
        try_cast(carried_weight_raw AS DOUBLE) AS carried_weight,track_condition_raw AS moisture,
        source_file,source_item_index FROM confirmed_runners WHERE source_meet=?
        AND try_cast(result_rank_raw AS INT) BETWEEN 1 AND 30
        AND try_cast(finish_time_seconds_raw AS DOUBLE)>0
        AND try_cast(race_distance_m_raw AS INT) IN (1000,1200,1300,1400,1500,1600,1800,1900,2000,2200)
        AND result_date BETWEEN ? AND ?''',['3','20100101','20260918']).df()
        s=c.execute('''SELECT race_date AS date,race_no,horse_id,point_code,measure_kind,time_ms,passing_order
        FROM section_measurements_api WHERE meet=? AND race_date BETWEEN ? AND ?
        AND measure_kind IN ('cumulative_time','passing_order')''',[3,'20100101','20260918']).df()
    key=['date','race_no','horse_id']
    assert not d.duplicated(key).any()
    for kind,value,prefix,scale in [('cumulative_time','time_ms','',1000),('passing_order','passing_order','p_',1)]:
        q=s[s.measure_kind.eq(kind)]
        assert not q.duplicated(key+['point_code']).any()
        w=q.pivot(index=key,columns='point_code',values=value).astype(float).div(scale)
        d=d.merge(w.add_prefix(prefix).reset_index(),on=key,how='left',validate='one_to_one')
    d=d.sort_values(['horse_id','date','race_no']).reset_index(drop=True)
    d['row_id']=np.arange(len(d));d['year']=d.date.str[:4].astype(int)
    assert len(d)==133755
    assert not d.duplicated(['horse_id','date']).any()
    return d


def history(d,columns,same=False):
    """Prefix arithmetic excludes current row; invalid values consume a five-slot place."""
    keys=['horse_id','distance'] if same else ['horse_id']
    order=d.sort_values(keys+['date','race_no']).index.to_numpy()
    g=d.loc[order]
    changed=g[keys].ne(g[keys].shift()).any(axis=1).to_numpy()
    i=np.arange(len(g));start=np.maximum.accumulate(np.where(changed,i,0));lo=np.maximum(start,i-5)
    z=g[columns].to_numpy(float);valid=np.isfinite(z)
    total=np.vstack([np.zeros(len(columns)),np.cumsum(np.where(valid,z,0),axis=0)])
    count=np.vstack([np.zeros(len(columns),dtype=np.int64),np.cumsum(valid,axis=0)])
    counts=count[i]-count[lo]
    means=np.divide(total[i]-total[lo],counts,out=np.full_like(z,np.nan),where=counts>0)
    prefix='same_' if same else 'all_'
    data={}
    for j,name in enumerate(columns):
        a=np.full(len(d),np.nan);a[order]=means[:,j];data[prefix+name+'_mean']=a
        a=np.zeros(len(d));a[order]=counts[:,j];data[prefix+name+'_n']=a
    previous=np.where(i>start,i-1,-1)
    mapped=np.full(len(d),-1,dtype=int);mapped[order]=np.where(previous>=0,order[np.maximum(previous,0)],-1)
    data[prefix+'previous_row']=mapped
    slots=np.minimum(i-start,5);outslots=np.zeros(len(d),dtype=int);outslots[order]=slots
    data[prefix+'slots']=outslots
    perf=g.performance.to_numpy(float)
    window=i[:,None]-np.arange(1,6)
    mask=window>=start[:,None]
    recent=perf[np.maximum(window,0)];recent=np.where(mask,recent,-np.inf)
    best=recent.max(axis=1);best[~np.isfinite(best)]=np.nan
    outbest=np.full(len(d),np.nan);outbest[order]=best;data[prefix+'performance_best']=outbest
    for name in ['performance','sec1000','rank_fraction','distance','carried_weight']:
        arr=d[name].to_numpy(float);data[prefix+name+'_last']=np.where(mapped>=0,arr[np.maximum(mapped,0)],np.nan)
    good=mapped>=0
    assert (d.loc[mapped[good],'date'].to_numpy()<d.loc[good,'date'].to_numpy()).all()
    return pd.DataFrame(data)


def main():
    check();d=load();race=['date','race_no']
    d['normal_n']=d.groupby(race).horse_id.transform('size')
    d['performance']=1000/d.distance*(d.groupby(race).finish.transform('median')-d.finish)
    d['sec1000']=d.finish*1000/d.distance
    observed=d[['p_S1F','p_G3F','p_G2F','finish_rank','normal_n']].max(axis=1)
    d['observed_n']=observed.groupby([d.date,d.race_no]).transform('max')
    denom=(d.observed_n-1).replace(0,np.nan)
    d['rank_fraction']=(d.finish_rank-1)/denom
    for p in POINTS:
        d['p_'+p]=d['p_'+p].where(d['p_'+p].between(1,30))
    d['early_q']=(d.p_S1F-1)/denom
    d['mid_gain']=(d.p_S1F-d.p_G3F)/denom
    d['late_gain']=(d.p_G2F-d.finish_rank)/denom
    valid=d[['p_S1F','p_G3F','p_G2F']].notna().all(axis=1)&d.observed_n.ge(2)
    front=d.early_q.le(1/3);stay=d.rank_fraction.le(1/3)
    d['style8']=np.select([~valid,d.p_S1F.eq(1)&stay,d.p_S1F.eq(1)&~stay,
        front&stay,front&~stay,d.mid_gain.ge(.2),d.late_gain.ge(.2),
        d.early_q.gt(2/3)&d.rank_fraction.ge(d.early_q-.1)],
        ['미확인']+STYLES[:-1],default=STYLES[-1])
    d['coarse_style']=np.select([d.early_q.isna(),d.p_S1F.eq(1),front,d.early_q.le(2/3)],
        ['미확인','선행','선입','중단'],default='후미')
    d['late_tag']=np.select([d.late_gain.isna(),d.late_gain.ge(.2),d.late_gain.le(-.2)],
        ['미확인','후반회복','후반밀림'],default='후반유지')
    extra={};support=[];distribution=[];layouts=[]
    for i in range(1,9):
        for suffix in ['seconds','length','index','delta','field_adv']:
            extra[f's{i}_{suffix}']=np.full(len(d),np.nan)
    complete=np.zeros(len(d),dtype=bool)
    for dist,group in d.groupby('distance'):
        ix=group.index.to_numpy();points=layout(int(dist));labels=[p for p,_ in points]
        positions=np.array([m for _,m in points]);lengths=np.diff(positions)
        x=np.column_stack([np.zeros(len(group))]+[group[p].to_numpy(float) for p in labels[1:-1]]+[group.finish.to_numpy(float)])
        seconds=np.diff(x,axis=1);good=np.isfinite(x).all(axis=1)&(seconds>0).all(axis=1)
        complete[ix]=good
        np.testing.assert_allclose(seconds[good].sum(axis=1),group.loc[good,'finish'],atol=1e-10,rtol=0)
        assert lengths.sum()==dist
        for j,(left,right) in enumerate(zip(points,points[1:]),1):
            t=np.where(good,seconds[:,j-1],np.nan);length=int(lengths[j-1])
            idx=100*length*group.finish.to_numpy()/dist/t
            ts=pd.Series(t,index=ix)
            median=ts.groupby([group.date,group.race_no]).transform('median').to_numpy()
            extra[f's{j}_seconds'][ix]=t;extra[f's{j}_length'][ix]=length
            extra[f's{j}_index'][ix]=idx;extra[f's{j}_delta'][ix]=idx-100
            extra[f's{j}_field_adv'][ix]=1000/length*(median-t)
            layouts.append(dict(distance=int(dist),segment=j,left=left[0],right=right[0],start_m=left[1],end_m=right[1],length_m=length))
            for scope,mask in [('all',good),('2024_2026',good&group.year.ge(2024).to_numpy())]:
                if mask.any():distribution.append(dict(distance=int(dist),segment=j,length_m=length,scope=scope,n=int(mask.sum()),
                    seconds_mean=float(np.mean(t[mask])),index_mean=float(np.mean(idx[mask])),index_p20=float(np.quantile(idx[mask],.2)),index_p80=float(np.quantile(idx[mask],.8))))
        support.append(dict(distance=int(dist),rows=len(group),races=group[race].drop_duplicates().shape[0],complete=int(good.sum()),
            segments=len(lengths),lengths='+'.join(map(str,lengths)),first_date=group.date.min(),last_date=group.date.max()))
    d=pd.concat([d,pd.DataFrame(extra)],axis=1);d['complete']=complete
    assert int(complete.sum())==133733
    common=[]
    for name,length,t in [('early',200,d.S1F),('tail600',600,d.finish-d.G3F),('tail400',400,d.finish-d.G2F),('tail200',200,d.finish-d.G1F)]:
        t=t.where(d.complete&t.gt(0));index=100*length*d.finish/d.distance/t
        median=t.groupby([d.date,d.race_no]).transform('median')
        d['c_'+name+'_index']=index;d['c_'+name+'_adv']=1000/length*(median-t)
        common.extend(['c_'+name+'_index','c_'+name+'_adv'])
    for j,name in enumerate(STYLES):d['style_'+str(j)]=np.where(valid,d.style8.eq(name).astype(float),np.nan)
    for j,name in enumerate(['선행','선입','중단','후미']):d['coarse_'+str(j)]=np.where(d.coarse_style.ne('미확인'),d.coarse_style.eq(name).astype(float),np.nan)
    base=['performance','sec1000','rank_fraction']
    allcols=base+common+['early_q','mid_gain','late_gain']+['coarse_'+str(i) for i in range(4)]+['style_'+str(i) for i in range(8)]
    samecols=base+[f's{i}_{kind}' for i in range(1,9) for kind in ['index','field_adv']]
    allhist=history(d,allcols);samehist=history(d,samecols,True)
    features=pd.concat([allhist,samehist],axis=1)
    # Not-applicable segment slots are NULL, not observed0.
    for i in range(1,9):
        absent=d[f's{i}_length'].isna()
        features.loc[absent,[f'same_s{i}_{kind}_{agg}' for kind in ['index','field_adv'] for agg in ['mean','n']]]=np.nan
    features['distance']=d.distance.astype(float)
    features['grade']=pd.to_numeric(d.grade.str.extract(r'(\d+)',expand=False),errors='coerce')
    features['age']=d.age;features['sex']=d.sex.map({'수':0,'암':1,'거':2})
    features['weight']=d.carried_weight;features['month']=pd.to_datetime(d.date).dt.month
    prev=features.all_previous_row.to_numpy(int);ok=prev>=0
    days=np.full(len(d),np.nan);dates=pd.to_datetime(d.date)
    days[ok]=(dates.loc[ok].to_numpy()-dates.iloc[prev[ok]].to_numpy())/np.timedelta64(1,'D')
    features['days_since']=days
    features['weight_change']=features.weight-features.all_carried_weight_last
    baseline=['distance','grade','age','sex','weight','month','days_since','weight_change','all_distance_last','all_carried_weight_last']
    for scope in ['all','same']:
        baseline += [f'{scope}_{p}_{stat}' for p in base for stat in ['mean','n','last']]+[scope+'_performance_best']
    shape=[f'same_s{i}_index_{a}' for i in range(1,9) for a in ['mean','n']]+[f'all_c_{p}_index_{a}' for p in ['early','tail600','tail400','tail200'] for a in ['mean','n']]
    absolute=[f'same_s{i}_field_adv_{a}' for i in range(1,9) for a in ['mean','n']]+[f'all_c_{p}_adv_{a}' for p in ['early','tail600','tail400','tail200'] for a in ['mean','n']]+[f'all_{p}_{a}' for p in ['early_q','mid_gain','late_gain']+[f'coarse_{i}' for i in range(4)] for a in ['mean','n']]
    finer=[f'all_style_{i}_mean' for i in range(8)]+['all_style_0_n']
    featurelists=dict(B0=baseline,B1=baseline+shape,B2=baseline+shape+absolute,B3=baseline+shape+absolute+finer)
    assert all(len(v)==len(set(v)) for v in featurelists.values())
    for columns in featurelists.values():
        assert not set(columns)&{'finish','finish_rank','performance','style8'}
    features.to_parquet(OUT/'features.parquet',index=False)
    d.to_parquet(OUT/'profiles.parquet',index=False)
    save('feature_sets.json',featurelists)
    pd.DataFrame(support).to_csv(OUT/'distance_support.csv',index=False)
    pd.DataFrame(layouts).to_csv(OUT/'segment_layouts.csv',index=False)
    pd.DataFrame(distribution).to_csv(OUT/'segment_distributions.csv',index=False)
    recent=d[d.year.ge(2024)]
    recent.groupby(['distance','style8']).size().rename('n').reset_index().to_csv(OUT/'style_distribution.csv',index=False)
    # Compare consecutive normal same-distance starts; unknown labels consume slots.
    q=d.sort_values(['horse_id','distance','date','race_no']).copy()
    q['previous_style']=q.groupby(['horse_id','distance']).style8.shift()
    pairs=q[q.year.ge(2024)&q.style8.ne('미확인')&q.previous_style.notna()&q.previous_style.ne('미확인')]
    stability=pairs.assign(same=pairs.style8.eq(pairs.previous_style)).groupby('distance').agg(pairs=('same','size'),same_rate=('same','mean'))
    stability.to_csv(OUT/'style_stability.csv')
    pd.crosstab(pairs.previous_style,pairs.style8).to_csv(OUT/'style_transition.csv')
    save('preparation_summary.json',dict(rows=len(d),complete=int(complete.sum()),distances=len(support),
        feature_counts={k:len(v) for k,v in featurelists.items()},style8_recent_n=int(recent.style8.ne('미확인').sum()),
        same_distance_style_pairs=len(pairs),style_repeat_rate=float(pairs.style8.eq(pairs.previous_style).mean()),
        no_current_result_features=True,history_strictly_previous_date=True,database_mode='read_only',operating_model_changed=False))
    print((OUT/'preparation_summary.json').read_text())


if __name__=='__main__':main()

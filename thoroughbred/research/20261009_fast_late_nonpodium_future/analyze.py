"""Chronological future starts after fast-closing non-podium index starts."""
from pathlib import Path
import gzip,json,hashlib,math
import numpy as np,pandas as pd
from scipy.stats import t,false_discovery_control
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';F=R/'20261008_middle_late_style_validation';C=R/'20261008_field_pace_prediction'
TARGETS=['next_top3','three_top3','return180','any180_top3','next_abnormal_zero']
SEGMENTS=[('부산','600'),('부산','400'),('부산','200'),('서울','600'),('서울','200')]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def moisture_band(s):return np.select([s.between(1,5),s.between(6,9),s.between(10,14),s.between(15,19),s.ge(20)],['1~5','6~9','10~14','15~19','20+'],default='unknown')
def score_ci(g,score,estimate,target):
    variances=[];numbers=[]
    for ids in [g.horse_id.astype(str),g.date.dt.strftime('%Y-%m-%d'),g.horse_id.astype(str)+':'+g.date.dt.strftime('%Y-%m-%d')]:
        codes=pd.factorize(ids)[0];n=int(codes.max()+1);s=np.bincount(codes,weights=score);variances.append(float(s@s)*n/(n-1) if n>1 else np.nan);numbers.append(n)
    # Shared future race dates can join different index dates; duplicate scores
    # across first-three future dates give an additional conservative sensitivity.
    dates=[];scores=[]
    for lag in ([1,2,3] if target in ['three_top3','any180_top3'] else [1]):
        ok=g['future_within'+str(lag)].to_numpy(bool);dates.extend(g.loc[ok,'future_date'+str(lag)].dt.strftime('%Y-%m-%d'));scores.extend(np.asarray(score)[ok])
    future_var=0.;future_groups=0
    if dates:
        codes=pd.factorize(np.asarray(dates))[0];future_groups=int(codes.max()+1);s=np.bincount(codes,weights=scores);future_var=float(s@s)*future_groups/(future_groups-1) if future_groups>1 else 0.
    if min(numbers[:2])<2:return dict(estimate=float(estimate),se=np.nan,lower=np.nan,upper=np.nan,p=np.nan,df=np.nan,future_date_groups=future_groups)
    var=max(0.,variances[0],variances[1],variances[0]+variances[1]-variances[2],future_var);se=math.sqrt(var);df=min(numbers[:2]+([future_groups] if future_groups>1 else []))-1;c=t.ppf(.975,df);p=float(2*t.sf(abs(estimate/se),df)) if se else float(estimate==0)
    return dict(estimate=float(estimate),se=se,lower=estimate-c*se,upper=estimate+c*se,p=p,df=df,future_date_groups=future_groups)
def prepare():
    src=pd.read_parquet(F/'outputs/trajectory_rows.parquet');sec=pd.read_parquet(C/'outputs/section_observations.parquet');cols=['row_key','source_key','horse_id','horse_name','meet','date','year','distance_m','grade_bucket','field_size','gate','source_file','source_item_index','raw_finish_rank','normal_outcome','finish_p','finish_p_mean5','valid_position5','supported5','rating','age_current','p_s1f','p_g3f','p_g1f']
    d=src[cols].copy();d=d.merge(sec[['row_key','moisture','finish','last600','late']],on='row_key',how='left',validate='one_to_one');d['quality_base']=d.row_key.isin(sec.row_key);d['moisture_band']=moisture_band(d.moisture)
    records=[];raw_inputs=[]
    for name,g in d.groupby('source_file'):
        path=(ROOT/name).resolve();assert path.is_relative_to((R/'20260929_calendar_api_v1/raw/race_execution_probe').resolve());raw_inputs.append(dict(path=name,bytes=path.stat().st_size,sha256=sha(path)));items=json.load(gzip.open(path,'rt'))['response']['body']['items']['item']
        for r in g.itertuples():
            z=items[int(r.source_item_index)];assert str(z['hrNo']).zfill(7)==r.horse_id and int(z['rcDate'])==int(r.date.strftime('%Y%m%d'))
            finish=float(z['rcTime']);bus=r.meet=='부산';tail600=float(z['bu_3fGTime']) if bus else finish-float(z['seG3fAccTime']);tail200=float(z['bu_1fGTime']) if bus else finish-float(z['seG1fAccTime']);tail400=float(z['bu_2fGTime']) if bus else np.nan
            acc600=float(z['buG3fAccTime' if bus else 'seG3fAccTime']);acc200=float(z['buG1fAccTime' if bus else 'seG1fAccTime']);acc400=float(z['buG2fAccTime']) if bus else np.nan
            records.append(dict(row_key=r.row_key,raw_finish_seconds=finish,raw_tail600=tail600,raw_tail400=tail400,raw_tail200=tail200,raw_acc600=acc600,raw_acc400=acc400,raw_acc200=acc200))
    d=d.merge(pd.DataFrame(records),on='row_key',validate='one_to_one')
    for segment in ['600','400','200']:
        tail=d['raw_tail'+segment];acc=d['raw_acc'+segment];ok=d.quality_base&d.normal_outcome&tail.gt(0)&acc.gt(0)&np.isclose(tail+acc,d.raw_finish_seconds,atol=1e-7)&d.raw_tail600.ge(d.raw_tail200)&d.raw_tail600.lt(d.raw_finish_seconds)
        if segment=='400':ok&=d.meet.eq('부산')&tail.ge(d.raw_tail200)&tail.le(d.raw_tail600)
        d['time'+segment]=np.where(ok,tail,np.nan)
        group=d.groupby('source_key')['time'+segment];n=group.transform('count');adequate=n.ge(6)&n.ge(.8*d.field_size)
        for quantile,label in [(.1,'10'),(.2,'20'),(.3,'30')]:
            threshold=group.transform(lambda x:x.quantile(quantile));d['race_q'+label+'_'+segment]=np.where(adequate,threshold,np.nan);d['race_fast'+label+'_'+segment]=np.where(adequate&tail.notna()&d['time'+segment].notna(),tail.le(threshold+1e-9),np.nan)
    same=d.quality_base;assert np.allclose(d.loc[same,'last600'],d.loc[same,'time600'],atol=1e-7,equal_nan=True);assert np.allclose(d.loc[same,'late'],d.loc[same,'time200'],atol=1e-7,equal_nan=True)
    winner=d[d.raw_finish_rank.eq(1)&d.raw_finish_seconds.gt(0)].groupby('source_key').raw_finish_seconds.min()
    d['finish_gap']=d.finish-d.source_key.map(winner)
    thresholds=[]
    for segment in ['600','400','200']:
        d['prior_fast20_'+segment]=np.nan;d['prior_q20_'+segment]=np.nan;d['prior_n_'+segment]=0
        for year in range(2019,2027):
            ref=d[d.year.between(year-3,year-1)&d['time'+segment].notna()]
            stats=ref.groupby(['meet','distance_m','grade_bucket','moisture_band']).agg(n=('row_key','size'),races=('source_key','nunique'),q20=('time'+segment,lambda x:x.quantile(.2)))
            for key,s in stats.iterrows():thresholds.append(dict(segment=segment,evaluation_year=year,reference_first_year=year-3,reference_last_year=year-1,meet=key[0],distance_m=key[1],grade_bucket=key[2],moisture_band=key[3],n=int(s.n),races=int(s.races),q20=float(s.q20),supported=s.n>=100 and s.races>=10))
            supported=stats[(stats.n>=100)&(stats.races>=10)].reset_index();subset=d[d.year.eq(year)].merge(supported,on=['meet','distance_m','grade_bucket','moisture_band'],how='left',validate='many_to_one').set_index('row_key');ix=d.year.eq(year);out=subset.loc[d.loc[ix,'row_key']]
            d.loc[ix,'prior_q20_'+segment]=out.q20.to_numpy();d.loc[ix,'prior_n_'+segment]=out.n.fillna(0).to_numpy();d.loc[ix,'prior_fast20_'+segment]=np.where(out['time'+segment].notna()&out.q20.notna(),out['time'+segment].le(out.q20+1e-9),np.nan)
    pd.DataFrame(thresholds).to_csv(O/'prior_thresholds.csv',index=False)
    d=d.sort_values(['horse_id','date']).reset_index(drop=True);assert d.groupby('horse_id').date.diff().dt.days.dropna().ge(2).all();ends=d.groupby('meet').date.max();end=ends.min();d['mature180']=d.date.le(end-pd.Timedelta(days=180));group=d.groupby('horse_id')
    for lag in [1,2,3]:
        for c in ['row_key','date','raw_finish_rank','field_size','meet','distance_m']:d['future_'+c.replace('row_key','key').replace('raw_finish_rank','rank').replace('field_size','size')+str(lag)]=group[c].shift(-lag)
        date=d['future_date'+str(lag)];within=date.notna()&date.le(d.date+pd.Timedelta(days=180))&date.le(end);rank=d['future_rank'+str(lag)];normal=rank.between(1,d['future_size'+str(lag)]);d['future_within'+str(lag)]=within;d['future_top3_'+str(lag)]=np.where(within&normal,rank.le(3),np.nan)
    d['next_top3']=np.where(d.mature180,d.future_top3_1,np.nan);d['next_abnormal_zero']=np.where(d.mature180&d.future_within1,d.future_rank1.between(1,3),np.nan);d['return180']=np.where(d.mature180,d.future_within1,np.nan)
    three=d[[f'future_top3_{lag}' for lag in [1,2,3]]];complete=three.notna().all(axis=1)&d.mature180;d['three_top3']=np.where(complete,three.eq(1).any(axis=1),np.nan)
    anywin=three.eq(1).any(axis=1);unknown=np.zeros(len(d),bool)
    for lag in [1,2,3]:unknown|=d['future_within'+str(lag)]&d['future_top3_'+str(lag)].isna()
    d['any180_top3']=np.where(d.mature180&(anywin|~unknown),anywin,np.nan);d['next_days']=(d.future_date1-d.date).dt.days
    d.to_parquet(O/'analysis_rows.parquet',index=False)
    paths=[F/'outputs/trajectory_rows.parquet',C/'outputs/section_observations.parquet'];dump(O/'source_audit.json',dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha(p)) for p in paths]+raw_inputs,n=len(d),races=d.source_key.nunique(),data_end_by_meet={k:str(v.date()) for k,v in ends.items()},common_followup_end=str(end.date()),mature_index_cutoff=str((end-pd.Timedelta(days=180)).date()),predictive_models_trained=0,future_used_in_index_flags=False,uses_track_speed=False));return d
def windows(d):
    yield '2024_2025',d[d.year.between(2024,2025)&d.mature180]
    yield '2026_mature',d[d.year.eq(2026)&d.mature180]
    yield '2018_2023',d[d.year.le(2023)&d.mature180]
def sample(d,meet,segment,definition):return d[d.meet.eq(meet)&d.normal_outcome&d.raw_finish_rank.gt(3)&d.quality_base&d[definition+'_'+segment].notna()]
def summary(g):
    out=dict(n=len(g),races=g.source_key.nunique(),horses=g.horse_id.nunique(),dates=g.date.nunique(),next_days_median=float(g.loc[g.future_within1,'next_days'].median()),finish_rank_mean=float(g.raw_finish_rank.mean()),past_finish_mean=float(g.finish_p_mean5.mean()),small_sample=g.source_key.nunique()<30 or g.date.nunique()<10)
    for c in TARGETS:out[c+'_n']=int(g[c].notna().sum());out[c+'_mean']=float(g[c].mean());out[c+'_events']=float(g[c].sum())
    return out
def raw_contrast(g,col,target):
    z=g[g[target].notna()];a=z[z[col].eq(1)];b=z[z[col].eq(0)]
    if not len(a) or not len(b):return None
    ma=a[target].mean();mb=b[target].mean();s=np.r_[(a[target]-ma)/len(a),-(b[target]-mb)/len(b)];out=dict(n_a=len(a),n_b=len(b),races=z.source_key.nunique(),horses=z.horse_id.nunique(),coverage=1.,mean_a=float(ma),mean_b=float(mb))|score_ci(pd.concat([a,b]),s,ma-mb,target);return out
def controls(g,stage='full'):
    cols={}
    if stage in ['finish','full']:
        for k in range(5,int(g.raw_finish_rank.max())+1):cols['finish_rank'+str(k)]=g.raw_finish_rank.eq(k).to_numpy(float)
    fields=(['finish_gap'] if stage in ['finish','full'] else [])+(['finish_p_mean5','valid_position5','rating','age_current'] if stage in ['past','finish','full'] else [])+(['p_s1f'] if stage=='full' else [])
    for c in fields:
        val=g[c];fill=.5 if c in ['finish_p_mean5','p_s1f'] else 0.;cols[c+'_missing']=val.isna().to_numpy(float);cols[c]=val.fillna(fill).to_numpy();cols[c+'_sq']=val.fillna(fill).to_numpy()**2
    return np.column_stack(list(cols.values())) if cols else np.zeros((len(g),0))
def adjusted(g,col,target,stage='full'):
    z=g[g[target].notna()].copy();st=z.groupby('source_key')[col].agg(['min','max']);common=st[(st['min']==0)&(st['max']==1)].index;original_n=len(z);z=z[z.source_key.isin(common)]
    if len(z)<30 or not len(common):return None
    x=z[col].to_numpy();y=z[target].to_numpy();a=controls(z,stage);values=np.column_stack([x,y,a]);codes=pd.factorize(z.source_key)[0];n=np.bincount(codes);means=np.column_stack([np.bincount(codes,weights=values[:,j])/n for j in range(values.shape[1])]);demeaned=values-means[codes];coef,_,rank,_=np.linalg.lstsq(demeaned[:,2:],demeaned[:,:2],rcond=None);res=demeaned[:,:2]-demeaned[:,2:]@coef;rx,ry=res.T;den=rx@rx
    if den<1e-8:return None
    beta=float(rx@ry/den);error=ry-beta*rx;dfres=len(z)-len(common)-rank-1
    if dfres<=0:return None
    influence=rx*error/den*np.sqrt(len(z)/dfres)
    return dict(n_a=int(x.sum()),n_b=int(len(z)-x.sum()),races=z.source_key.nunique(),horses=z.horse_id.nunique(),coverage=float(len(z)/original_n),control_rank=int(rank),absorbed_races=len(common),effective_exposure_variance=float(den/len(z)))|score_ci(z,influence,beta,target)
def same_horse(g,col,target):
    z=g[g[target].notna()].copy();before=len(z);keys=['horse_id','meet','distance_m','grade_bucket'];z['cell']=z[keys].astype(str).agg('|'.join,axis=1);st=z.groupby(['cell',col]).agg(n=(target,'size'),mean=(target,'mean')).unstack(col)
    if 0. not in st['n'] or 1. not in st['n']:return None,[]
    st=st[st['n'][[0.,1.]].notna().all(axis=1)];
    if not len(st):return None,[]
    w=st['n'][1.]*st['n'][0.]/(st['n'][1.]+st['n'][0.]);tot=w.sum();ma=float((w*st['mean'][1.]).sum()/tot);mb=float((w*st['mean'][0.]).sum()/tot);z=z[z.cell.isin(st.index)];isa=z[col].eq(1).to_numpy();n=np.where(isa,z.cell.map(st['n'][1.]),z.cell.map(st['n'][0.]));score=np.where(isa,1,-1)*z.cell.map(w).to_numpy()/tot/n*(z[target].to_numpy()-np.where(isa,ma,mb))
    result=dict(n_a=int(isa.sum()),n_b=int((~isa).sum()),races=z.source_key.nunique(),horses=z.horse_id.nunique(),cells=len(st),coverage=float(len(z)/before),mean_a=ma,mean_b=mb)|score_ci(z,score,ma-mb,target)
    details=[dict(cell=k,n_a=int(st.loc[k,('n',1.)]),n_b=int(st.loc[k,('n',0.)]),mean_a=float(st.loc[k,('mean',1.)]),mean_b=float(st.loc[k,('mean',0.)]),weight=float(w[k])) for k in st.index];return result,details
def analyze(d):
    metrics=[];comparisons=[];cells=[];sens=[];coverage=[]
    for window,full in windows(d):
        for meet,segment in SEGMENTS:
            for definition in ['race_fast20','prior_fast20']:
                col=definition+'_'+segment;g=sample(full,meet,segment,definition)
                coverage.append(dict(window=window,meet=meet,segment=segment,definition=definition,nonpodium_quality_n=int((full.meet.eq(meet)&full.normal_outcome&full.raw_finish_rank.gt(3)&full.quality_base).sum()),supported_n=len(g),fast_n=int(g[col].eq(1).sum())))
                for flag,z in g.groupby(col):metrics.append(dict(window=window,meet=meet,segment=segment,definition=definition,fast=bool(flag))|summary(z))
                if window=='2018_2023':continue
                for target in TARGETS:
                    result=raw_contrast(g,col,target)
                    if result:comparisons.append(dict(window=window,meet=meet,segment=segment,definition=definition,target=target,method='raw')|result)
                    if target not in ['next_top3','three_top3']:continue
                    result=adjusted(g,col,target)
                    if result:comparisons.append(dict(window=window,meet=meet,segment=segment,definition=definition,target=target,method='same_race_adjusted')|result)
                    result,cs=same_horse(g,col,target)
                    if result:comparisons.append(dict(window=window,meet=meet,segment=segment,definition=definition,target=target,method='same_horse')|result);cells.extend(dict(window=window,meet=meet,segment=segment,definition=definition,target=target)|c for c in cs)
            if window=='2018_2023':continue
            for cutoff in ['10','30']:
                col='race_fast'+cutoff+'_'+segment;g=sample(full,meet,segment,'race_fast'+cutoff)
                result=raw_contrast(g,col,'next_top3')
                if result:sens.append(dict(window=window,meet=meet,segment=segment,cutoff=cutoff,method='raw')|result)
                result=adjusted(g,col,'next_top3')
                if result:sens.append(dict(window=window,meet=meet,segment=segment,cutoff=cutoff,method='same_race_adjusted')|result)
    out=pd.DataFrame(comparisons)
    for (window,method),g in out.groupby(['window','method']):
        ix=g[g.target.isin(['next_top3','three_top3'])&g.p.notna()].index
        if len(ix):out.loc[ix,'bh_q']=false_discovery_control(out.loc[ix,'p']);out.loc[ix,'bh_family']=window+':'+method
    pd.DataFrame(metrics).to_csv(O/'cohort_metrics.csv',index=False);out.to_csv(O/'comparisons.csv',index=False);pd.DataFrame(cells).to_csv(O/'same_horse_cells.csv',index=False);pd.DataFrame(sens).to_csv(O/'cutoff_sensitivity.csv',index=False);pd.DataFrame(coverage).to_csv(O/'coverage.csv',index=False)
    # Distance tables remain descriptive; no borrowed correction between courses.
    regions=[]
    for meet,segment in SEGMENTS:
        full=d[d.year.between(2024,2025)&d.mature180];g=sample(full,meet,segment,'race_fast20')
        for (distance,flag),z in g.groupby(['distance_m','race_fast20_'+segment]):regions.append(dict(meet=meet,segment=segment,distance_m=distance,fast=bool(flag))|summary(z))
    pd.DataFrame(regions).to_csv(O/'distance_metrics.csv',index=False)
def main():
    assert not(O/'analysis_rows.parquet').exists();d=prepare();print('Prepared',len(d),flush=True);analyze(d);print('Completed future analysis',flush=True)
if __name__=='__main__':main()

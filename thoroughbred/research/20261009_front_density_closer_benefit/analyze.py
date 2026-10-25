"""Observed front density, actual early speed and past-only rear cohorts."""
from pathlib import Path
import json,hashlib,importlib.util
import numpy as np,pandas as pd
from scipy.stats import false_discovery_control
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs'
F=R/'20261008_middle_late_style_validation';C=R/'20261008_field_pace_prediction';S=R/'20261008_running_style_foundation'
spec=importlib.util.spec_from_file_location('prior_observed',F/'analyze.py');prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
TARGETS=['top3','top5','finish_p','recovery','gain_late','fade','nonfinish']
COHORTS={'past_back':'back_profile','back_repeat':'closer_candidate','back_low':'back_low_recovery','past_lead':'lead_profile'}
EXPOSURES={'past_lead_other_band':('3+','0~1'),'actual_pack_band':('3+','1'),'pace_band':('fast','slow')}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def moisture_band(v):return np.select([v.between(1,5),v.between(6,9),v.between(10,14),v.between(15,19),v.ge(20)],['1~5','6~9','10~14','15~19','20+'],default='unknown')
def count_band(v,low=1):return np.where(v.isna(),'unknown',np.where(v.le(low),str(low) if low==1 else '0~1',np.where(v.eq(2),'2','3+')))
def matched(g,col,a,b,keys,target,min_n,min_races):
    g=g[g[col].isin([a,b])&g[target].notna()].copy();g['cell']=g[keys].astype(str).agg('|'.join,axis=1)
    st=g.groupby(['cell',col]).agg(n=(target,'size'),races=('source_key','nunique'),mean=(target,'mean')).unstack(col)
    if a not in st['n'] or b not in st['n']:return None,[]
    st=st[st['n'][[a,b]].notna().all(axis=1)&st['n'][[a,b]].min(axis=1).ge(min_n)&st['races'][[a,b]].min(axis=1).ge(min_races)]
    if not len(st):return None,[]
    w=st['n'][a]*st['n'][b]/(st['n'][a]+st['n'][b]);tot=w.sum();ma=float((w*st['mean'][a]).sum()/tot);mb=float((w*st['mean'][b]).sum()/tot)
    z=g[g.cell.isin(st.index)];isa=z[col].eq(a).to_numpy();n=np.where(isa,z.cell.map(st['n'][a]),z.cell.map(st['n'][b]));score=np.where(isa,1,-1)*z.cell.map(w).to_numpy()/tot/n*(z[target].to_numpy()-np.where(isa,ma,mb))
    result=dict(target=target,cell_columns='|'.join(keys),cells=len(st),n_a=int(isa.sum()),n_b=int((~isa).sum()),horses=z.horse_id.nunique(),dates=z.date.nunique(),races=z.source_key.nunique(),coverage=float(len(z)/len(g)),mean_a=ma,mean_b=mb)|prior.score_ci(z,score,ma-mb)
    cells=[dict(cell=key,n_a=int(st.loc[key,('n',a)]),n_b=int(st.loc[key,('n',b)]),mean_a=float(st.loc[key,('mean',a)]),mean_b=float(st.loc[key,('mean',b)]),weight=float(w[key])) for key in st.index]
    return result,cells
def prepare():
    d=pd.read_parquet(F/'outputs/trajectory_rows.parquet')
    f=pd.read_parquet(S/'outputs/observed_styles.parquet',columns=['row_key','s1f_time']);c=pd.read_parquet(C/'outputs/feature_context.parquet',columns=['row_key','first_group_size'])
    assert d.row_key.is_unique and f.row_key.is_unique and c.row_key.is_unique
    d=d.merge(f,on='row_key',validate='one_to_one').merge(c,on='row_key',validate='one_to_one')
    d['moisture_band']=moisture_band(d.moisture)
    races=[]
    for key,g in d.groupby('source_key',sort=False):
        z=g.iloc[0];assert len(g)==z.field_size
        for col in ['meet','date','year','distance_m','grade_bucket','field_size']:assert g[col].nunique(dropna=False)==1,(key,col)
        assert g.first_group_size.nunique(dropna=False)==1
        early_valid=bool(g.s1f_complete.all() and g.s1f_time.gt(0).all() and g.s1f_time.notna().all())
        races.append(dict(source_key=key,horse_id=key,meet=z.meet,date=z.date,year=z.year,distance_m=z.distance_m,grade_bucket=z.grade_bucket,field_size=len(g),moisture=float(g.moisture.median()) if g.moisture.notna().any() else np.nan,past_lead_count=int(g.lead_profile.sum()),supported_count=int(g.supported5.sum()),support_fraction=float(g.supported5.mean()),actual_pack_count=float(z.first_group_size),pace_valid=early_valid,pace_seconds=float(g.s1f_time.nsmallest(3).mean()) if early_valid else np.nan,zero_or_missing_times=int((~g.s1f_time.gt(0)).sum()),past_finish_mean=float(g.finish_p_mean5.mean())))
    q=pd.DataFrame(races);q['moisture_band']=moisture_band(q.moisture);q['past_lead_band']=np.where(q.past_lead_count.le(1),'0~1',np.where(q.past_lead_count.eq(2),'2','3+'));q['actual_pack_band']=count_band(q.actual_pack_count)
    q['pace_band']='unknown';q['pace_q25']=np.nan;q['pace_q75']=np.nan;q['pace_reference_n']=0
    thresholds=[]
    for year in range(2019,2027):
        ref=q[q.year.between(year-3,year-1)&q.pace_valid]
        for key,g in ref.groupby(['meet','distance_m','grade_bucket']):
            n=len(g);lo=float(g.pace_seconds.quantile(.25));hi=float(g.pace_seconds.quantile(.75));thresholds.append(dict(evaluation_year=year,reference_first_year=year-3,reference_last_year=year-1,meet=key[0],distance_m=key[1],grade_bucket=key[2],n=n,q25=lo,q75=hi,supported=n>=30))
            if n<30:continue
            ix=q.index[(q.year==year)&(q.meet==key[0])&(q.distance_m==key[1])&(q.grade_bucket==key[2])]
            q.loc[ix,'pace_q25']=lo;q.loc[ix,'pace_q75']=hi;q.loc[ix,'pace_reference_n']=n
            valid=ix[q.loc[ix,'pace_valid']];v=q.loc[valid,'pace_seconds'];q.loc[valid,'pace_band']=np.where(v.le(lo),'fast',np.where(v.ge(hi),'slow','middle'))
    pd.DataFrame(thresholds).to_csv(O/'pace_thresholds.csv',index=False)
    keep=['source_key','past_lead_count','supported_count','support_fraction','actual_pack_count','pace_valid','pace_seconds','pace_band','pace_q25','pace_q75','pace_reference_n']
    d=d.merge(q[keep],on='source_key',validate='many_to_one')
    d['past_lead_other']=d.past_lead_count-d.lead_profile.astype(int);d['past_lead_other_band']=np.where(d.past_lead_other.le(1),'0~1',np.where(d.past_lead_other.eq(2),'2','3+'))
    d['actual_pack_band']=count_band(d.actual_pack_count);d['actual_front_other']=d.actual_pack_count-d.role4.eq(0).astype(int);d['actual_other_band']=np.where(d.actual_front_other.isna(),'unknown',np.where(d.actual_front_other.le(1),'0~1',np.where(d.actual_front_other.eq(2),'2','3+')))
    cols=['row_key','source_key','horse_id','horse_name','meet','date','year','distance_m','grade_bucket','gate','field_size','moisture','moisture_band','supported5','lead_profile','back_profile','closer_candidate','back_low_recovery','finish_p_mean5','past_finish_band','role4','p_s1f','p_g3f','p_g1f','raw_finish_rank','s1f_time','s1f_complete','top3','top5','finish_p','recovery','gain_late','fade','nonfinish','past_lead_count','supported_count','support_fraction','actual_pack_count','past_lead_other','past_lead_other_band','actual_pack_band','actual_front_other','actual_other_band','pace_valid','pace_seconds','pace_band','pace_q25','pace_q75','pace_reference_n']
    d=d[cols];d.to_parquet(O/'analysis_rows.parquet',index=False);q.to_parquet(O/'race_context.parquet',index=False)
    paths=[F/'outputs/trajectory_rows.parquet',F/'analyze.py',S/'outputs/observed_styles.parquet',C/'outputs/feature_context.parquet',C/'outputs/source_audit.json']
    raw=[x for x in json.loads((C/'outputs/source_audit.json').read_text())['inputs'] if x['path'].endswith('.json.gz')]
    dump(O/'source_audit.json',dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha(p)) for p in paths]+raw,n=len(d),races=len(q),data_end_by_meet={k:str(v.date()) for k,v in d.groupby('meet').date.max().items()},models_trained=0,uses_current_pace_as_prerace_input=False,uses_track_speed=False))
    return d,q
def windows(d):
    yield '2024_2025',d[d.year.between(2024,2025)]
    yield '2026_partial',d[d.year.eq(2026)]
    yield '2018_2023',d[d.year.le(2023)]
def scopes(d,detail):
    yield 'all','all',d
    for key,g in d.groupby('meet'):yield 'meet',key,g
    if detail:
        for (m,dist),g in d.groupby(['meet','distance_m']):yield 'meet_distance',f'{m}|{dist}',g
def metrics(d,q):
    rows=[];race_rows=[];joint=[]
    for window,full in windows(d):
        for scope,label,g in scopes(full,window!='2018_2023'):
            for cohort,flag in COHORTS.items():
                z=g[g[flag]]
                for exposure in EXPOSURES:
                    for status,zz in z.groupby(exposure):
                        row=dict(window=window,scope=scope,label=label,cohort=cohort,exposure=exposure,status=status,n=len(zz),races=zz.source_key.nunique(),horses=zz.horse_id.nunique(),dates=zz.date.nunique(),support_fraction_mean=float(zz.support_fraction.mean()),small_sample=zz.source_key.nunique()<30 or zz.date.nunique()<10)
                        for t in TARGETS:row[t+'_n']=int(zz[t].notna().sum());row[t+'_mean']=float(zz[t].mean())
                        rows.append(row)
        for cohort,flag in COHORTS.items():
            for (a,b),g in full[full[flag]].groupby(['past_lead_other_band','pace_band']):
                row=dict(window=window,cohort=cohort,past_lead_other_band=a,pace_band=b,n=len(g),races=g.source_key.nunique())
                for t in TARGETS:row[t+'_n']=int(g[t].notna().sum());row[t+'_mean']=float(g[t].mean())
                joint.append(row)
    for window,full in windows(q):
        for scope,label,g in scopes(full,window!='2018_2023'):
            for exposure in ['past_lead_band','actual_pack_band']:
                for status,z in g.groupby(exposure):race_rows.append(dict(window=window,scope=scope,label=label,exposure=exposure,status=status,races=len(z),pace_n=int(z.pace_seconds.notna().sum()),pace_mean=float(z.pace_seconds.mean()),fast_n=int(z.pace_band.ne('unknown').sum()),fast_rate=float(z.loc[z.pace_band.ne('unknown'),'pace_band'].eq('fast').mean()),support_fraction_mean=float(z.support_fraction.mean()),field_size_mean=float(z.field_size.mean())))
    pd.DataFrame(rows).to_csv(O/'cohort_metrics.csv',index=False);pd.DataFrame(race_rows).to_csv(O/'race_pace_metrics.csv',index=False);pd.DataFrame(joint).to_csv(O/'joint_lead_pace_metrics.csv',index=False)
def comparisons(d,q):
    rows=[];cells=[];race_rows=[];race_cells=[]
    basekeys=['meet','distance_m','grade_bucket','year','field_size','moisture_band','past_finish_band']
    for window,full in windows(d):
        if window=='2018_2023':continue
        for cohort,flag in COHORTS.items():
            source=full[full[flag]]
            for exposure,(a,b) in EXPOSURES.items():
                for target in ['top3','recovery']:
                    # Unadjusted differences with the same cluster convention.
                    z=source[source[exposure].isin([a,b])&source[target].notna()];ga=z[z[exposure].eq(a)];gb=z[z[exposure].eq(b)]
                    if len(ga) and len(gb):
                        ma=ga[target].mean();mb=gb[target].mean();gg=pd.concat([ga,gb]);score=np.r_[(ga[target]-ma)/len(ga),-(gb[target]-mb)/len(gb)]
                        rows.append(dict(window=window,cohort=cohort,exposure=exposure,a=a,b=b,target=target,method='raw',n_a=len(ga),n_b=len(gb),mean_a=ma,mean_b=mb,races=gg.source_key.nunique(),horses=gg.horse_id.nunique(),coverage=1.)|prior.score_ci(gg,score,ma-mb))
                    methods=[('conditions',basekeys,5,2,source),('same_horse',['horse_id','meet','distance_m','grade_bucket'],1,1,source),('supported80',basekeys,5,2,source[source.support_fraction.ge(.8)])]
                    if exposure=='actual_pack_band':methods.append(('leave_self_out',basekeys,5,2,source))
                    for method,keys,mn,mr,z in methods:
                        col='actual_other_band' if method=='leave_self_out' else exposure;aa,bb=('3+','0~1') if method=='leave_self_out' else(a,b)
                        result,cs=matched(z,col,aa,bb,keys,target,mn,mr)
                        if result:
                            rows.append(dict(window=window,cohort=cohort,exposure=exposure,a=aa,b=bb,method=method)|result)
                            cells.extend(dict(window=window,cohort=cohort,exposure=exposure,method=method,target=target)|c for c in cs)
    for window,full in windows(q):
        if window=='2018_2023':continue
        for exposure,a,b in [('past_lead_band','3+','0~1'),('actual_pack_band','3+','1')]:
            result,cs=matched(full,exposure,a,b,['meet','distance_m','grade_bucket','year','field_size','moisture_band'],'pace_seconds',3,3)
            if result:
                race_rows.append(dict(window=window,exposure=exposure,a=a,b=b)|result);race_cells.extend(dict(window=window,exposure=exposure)|c for c in cs)
    results=pd.DataFrame(rows)
    for (window,method),g in results.groupby(['window','method']):
        ix=g[g.p.notna()].index
        if len(ix):results.loc[ix,'bh_q']=false_discovery_control(results.loc[ix,'p']);results.loc[ix,'bh_family']=window+':'+method
    pd.DataFrame(results).to_csv(O/'comparisons.csv',index=False);pd.DataFrame(cells).to_csv(O/'matched_cells.csv',index=False);pd.DataFrame(race_rows).to_csv(O/'race_pace_comparisons.csv',index=False);pd.DataFrame(race_cells).to_csv(O/'race_pace_matched_cells.csv',index=False)
def main():
    assert not(O/'analysis_rows.parquet').exists();d,q=prepare();print('Prepared',len(d),len(q),flush=True);metrics(d,q);comparisons(d,q);print('Completed',flush=True)
if __name__=='__main__':main()

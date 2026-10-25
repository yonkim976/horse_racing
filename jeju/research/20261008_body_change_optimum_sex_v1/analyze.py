"""Retrospective Jeju body changes and quadratic weight ranges. No DB writes."""
from pathlib import Path
import importlib.util
import json
import sqlite3
import numpy as np
import pandas as pd
from scipy.stats import t, f

H=Path(__file__).resolve().parent;ROOT=H.parents[2];PRE=H.parent/'20261008_weight_speed_v2'
sp=importlib.util.spec_from_file_location('preserved_weight',PRE/'analyze.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
PLAN=json.loads((H/'PLAN.json').read_text());sha=a.sha;SEED=20261008
def save(name,v):
    with (H/name).open('x',encoding='utf-8') as z:json.dump(v,z,ensure_ascii=False,indent=2,allow_nan=False)
def csv(name,v):
    with (H/name).open('x',encoding='utf-8') as z:v.to_csv(z,index=False)
def clean(v):
    if isinstance(v,dict):return {k:clean(z) for k,z in v.items()}
    if isinstance(v,list):return [clean(z) for z in v]
    if isinstance(v,np.generic):v=v.item()
    return None if isinstance(v,float) and not np.isfinite(v) else v
def bh(df,keys):
    if len(df):
        for _,g in df.groupby(keys,dropna=False):df.loc[g.index,'q_BH']=a.old.bh(g.p.to_numpy())
    return df
def info(g,pair=False):
    return {'rows':len(g),'races':int(g.race_id.nunique()),'horses':int(g.horse_id.nunique()),'dates':int(g.race_date.nunique())}
def supported(g,pair=False):return a.support(g,pairs=pair)['supported']
def infer(m,v):
    z=a.infer(m,v)
    if 'speed_change_pct_per_kg' in z:z['speed_change_pct_for_contrast']=z.pop('speed_change_pct_per_kg')
    return z
def vec(m,col,value=1):return a.get_vector(m,col,value)

def load():
    refs=[H/'PLAN.json',H/'analyze.py',PRE/'analyze.py',PRE/'PLAN.json',PRE/'source_lineage.csv',PRE/'pair_lineage.csv',PRE/'input_audit.json',a.old.OLD/'audit/source_rows.csv',a.old.OLD/'audit/history_ids.json',a.old.OLD/'modeling.py',a.prior.H/'analyze.py' if hasattr(a.prior,'H') else a.PRE/'analyze.py',a.old.HERE/'analyze.py',ROOT/'jeju/data/horse_exclusions.json',ROOT/'jeju/AGENTS.md']
    refs=list(dict.fromkeys(refs));save('source_manifest.json',[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in refs])
    dbsha=sha(a.old.DB);assert dbsha==json.loads((PRE/'input_audit.json').read_text())['database_sha256']
    d,h=a.old.load();q=a.old.all_features(d,h).reset_index(drop=True)
    lineage=pd.read_csv(PRE/'source_lineage.csv',dtype={'horse_id':str},low_memory=False)
    q=q.merge(lineage[['api_record_id','body_kg','reported_body_change_raw','jockey_id','result_payload_sha256']],on='api_record_id',validate='one_to_one')
    q['time']=q.finish_time_seconds;q['log_time100']=100*np.log(q.time);q['body10']=(q.body_kg-278)/10;q['body2']=q.body10**2;q['burden']=q.carried_weight_kg-55
    q['prior_finish_fraction']=[(d.loc[h[str(rid)][-1],'finish_position']-1)/(d.loc[h[str(rid)][-1],'field_n']-1) if h[str(rid)] else np.nan for rid in q.api_record_id]
    q['relative_time']=q.time-q.groupby('race_id').time.transform('median')
    q['body_deviation10']=(q.body_kg-q.groupby('horse_id').body_kg.transform('median'))/10;q['body_deviation2']=q.body_deviation10**2
    assert len(q)==52155 and q.race_id.nunique()==5206 and q.api_record_id.is_unique
    sexsets=q.groupby('horse_id').sex.agg(lambda z:set(z));conflict=set(sexsets[sexsets.map(lambda z:'암' in z and len(z-{'암','unknown'})>0)].index)
    q['sex_inference_ok']=~q.horse_id.isin(conflict)&q.sex.isin(['수','암','거'])
    pairs=pd.read_csv(PRE/'pair_lineage.csv',dtype={'horse_id':str},low_memory=False)
    ix=q.set_index('api_record_id');pairs['sex']=ix.loc[pairs.pair_id,'sex'].to_numpy();pairs['previous_sex']=ix.loc[pairs.previous_api_record_id,'sex'].to_numpy()
    pairs['sex_inference_ok']=~pairs.horse_id.isin(conflict)&pairs.sex.eq(pairs.previous_sex)&pairs.sex.isin(['수','암','거'])
    pairs['gain10']=pairs.body_change_kg.clip(lower=0)/10;pairs['loss10']=(-pairs.body_change_kg.clip(upper=0))/10
    pairs['previous_body10']=(pairs.previous_body_kg-278)/10;pairs['previous_body2']=pairs.previous_body10**2
    pairs['stable_for_body']=pairs.month.eq(pairs.previous_month)&pairs.band.eq(pairs.previous_band)&pairs.burden_change.abs().le(1)
    con=sqlite3.connect(a.old.DB.as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON')
    chronology=pd.read_sql_query('SELECT r.api_record_id,r.horse_id,r.race_date,r.body_weight_raw FROM race_result_rows r',con)
    tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%profile%'")];save('profile_table_inventory.json',tables)
    con.close()
    chronology.horse_id=chronology.horse_id.astype(str);parsed=chronology.body_weight_raw.str.extract(r'^\s*(\d+(?:\.\d+)?)\s*(?:\(([^()]*)\))?\s*$');chronology['body']=pd.to_numeric(parsed[0],errors='coerce');chronology=chronology.sort_values(['horse_id','race_date','api_record_id'])
    chronology['previous_observed_body']=chronology.groupby('horse_id').body.shift();chronology['previous_observed_date']=chronology.groupby('horse_id').race_date.shift()
    zz=q[['api_record_id','horse_id','race_date','body_kg','reported_body_change_raw']].merge(chronology[['api_record_id','previous_observed_body','previous_observed_date']],on='api_record_id',validate='one_to_one')
    zz['reported_change']=pd.to_numeric(zz.reported_body_change_raw,errors='coerce');zz['observed_change']=zz.body_kg-zz.previous_observed_body;zz['comparable']=zz.reported_change.notna()&zz.previous_observed_body.notna()&zz.previous_observed_date.lt(zz.race_date);zz['agrees']=zz.reported_change.eq(zz.observed_change)
    csv('reported_change_chronology_audit.csv',zz)
    csv('source_lineage.csv',q[['api_record_id','horse_id','race_id','race_date','race_distance_m','sex','event_age','body_kg','reported_body_change_raw','carried_weight_kg','body_deviation10','sex_inference_ok','history_cutoff','result_payload_sha256']])
    csv('pair_lineage.csv',pairs[['pair_id','previous_api_record_id','horse_id','distance','race_date','previous_date','body_kg','previous_body_kg','body_change_kg','gain10','loss10','sex','previous_sex','sex_inference_ok','stable_for_body']])
    csv('sex_conflict_horses.csv',pd.DataFrame([{'horse_id':k,'event_sexes':','.join(sorted(sexsets[k])),'starts':int(q.horse_id.eq(k).sum())} for k in sorted(conflict)],columns=['horse_id','event_sexes','starts']))
    raw=q.groupby(['race_distance_m','sex']).agg(starts=('api_record_id','size'),horses=('horse_id','nunique'),mean_body_kg=('body_kg','mean'),median_body_kg=('body_kg','median'),p10_body_kg=('body_kg',lambda z:z.quantile(.1)),p90_body_kg=('body_kg',lambda z:z.quantile(.9)),mean_race_relative_seconds=('relative_time','mean')).reset_index();csv('body_by_distance_sex.csv',raw)
    def bins(z):return pd.cut(z,[-np.inf,-10,-3,3,10,np.inf],right=False,labels=['loss10plus','loss3toUnder10','stableUnder3','gain3toUnder10','gain10plus'])
    pp=pairs.copy();pp['body_change_group']=bins(pp.body_change_kg)
    csv('raw_pair_body_changes.csv',pp.groupby(['distance','sex','body_change_group'],observed=True).agg(pairs=('pair_id','size'),horses=('horse_id','nunique'),body_change_mean_kg=('body_change_kg','mean'),time_delta_mean_s=('time_delta','mean'),relative_time_delta_mean_s=('relative_time_delta','mean'),burden_change_mean_kg=('burden_change','mean')).reset_index())
    audit={'rows':len(q),'races':q.race_id.nunique(),'horses':q.horse_id.nunique(),'pairs':len(pairs),'last_date':q.race_date.max(),'sex_conflict_horses':len(conflict),'sex_conflict_starts':int((~q.sex_inference_ok).sum()),'same_sex_valid_pairs':int(pairs.sex_inference_ok.sum()),'printed_change_comparable':int(zz.comparable.sum()),'printed_change_agrees':int((zz.comparable&zz.agrees).sum()),'printed_change_missing':int(zz.reported_change.isna().sum()),'database_sha256':dbsha,'body_is_retrospective':True,'age_is_race_event_control_not_2026_profile_age':True}
    save('input_audit.json',clean(audit));return q,pairs,dbsha

def pair_fit(g,variant='primary',sex=False):
    targets=[];targetvals=[]
    if sex:
        for sx in ['수','암','거']:
            for kind in ['gain10','loss10']:targets.append(kind+'_'+sx);targetvals.append(g[kind]*g.sex.eq(sx))
    else:targets=['gain10','loss10'];targetvals=[g[c] for c in targets]
    numeric=['increase_kg','decrease_kg','previous_burden_kg','previous_body10','previous_body2','log_gap','age','previous_relative_time','previous_finish_fraction','previous_hist_mean','field_change']+[c for c in g if c.startswith(('band=','gate='))]+['sin1','cos1','sin2','cos2']
    if variant=='no_prior_performance':numeric=[c for c in numeric if c not in ['previous_relative_time','previous_finish_fraction','previous_hist_mean']]
    nx,design=a.standardized_nuisance(g,numeric,['year_grade']+(['sex'] if sex else []));cols=targets+['intercept']+design['nuisance_columns'];x=np.column_stack(targetvals+[np.ones(len(g)),nx]);y=g[['time_delta','log_time_delta100']].to_numpy()
    fits=a.core_fit(x,y,g,cols,len(targets),fe=False)
    for m in fits:m['design']=design
    return fits

def row_fit(g,variant='absolute',sex=False,omit_body=False):
    targets=[];vals=[]
    base=['body_deviation10','body_deviation2'] if variant=='within_median' else ['body10','body2']
    if not omit_body:
        for sx in (['수','암','거'] if sex else ['all']):
            for c in base:targets.append(c+'_'+sx if sex else c);vals.append(g[c]*g.sex.eq(sx) if sex else g[c])
    numeric=['burden','hist_mean','hist_last','prior_finish_fraction','log_same_count','log_starts','log_gap','event_age','age_squared']
    if variant=='no_history':numeric=[c for c in numeric if c not in ['hist_mean','hist_last','prior_finish_fraction']]
    nx,design=a.standardized_nuisance(g,numeric,['sex','horse_number']);cols=targets+design['nuisance_columns'];x=np.column_stack(vals+[nx]);y=g[['time','log_time100']].to_numpy()
    fits=a.core_fit(x,y,g,cols,len(targets))
    for m in fits:m['design']=design
    return fits

def curve_info(m,g,sex='all',within=False):
    names=['body_deviation10','body_deviation2'] if within else ['body10','body2'];names=[c+'_'+sex if sex!='all' else c for c in names]
    v1=vec(m,names[0]);v2=vec(m,names[1]);lin=infer(m,v1);quad=infer(m,v2);b1=lin['effect'];b2=quad['effect'];center=0 if within else 278
    bodies=g.body_deviation10*10 if within else g.body_kg;lo,hi=bodies.quantile([.1,.9]);min5,max95=bodies.quantile([.05,.95]);vertex=center-10*b1/(2*b2) if b2>0 else np.nan
    sub=np.array(m['cov'])[np.ix_([m['columns'].index(c) for c in names],[m['columns'].index(c) for c in names])]
    draws=np.random.default_rng(SEED).multivariate_normal([b1,b2],sub,size=10000);pos=draws[:,1]>0;vertices=center-10*draws[pos,0]/(2*draws[pos,1]);vlow,vhigh=np.quantile(vertices,[.025,.975]) if len(vertices)>100 else [np.nan,np.nan]
    r={'sex':sex,**info(g),'linear':b1,'quadratic':b2,'ci_lo':quad['ci_lo'],'ci_hi':quad['ci_hi'],'p':quad['p'],'vertex_kg_or_deviation':vertex,'vertex_ci_lo':vlow,'vertex_ci_hi':vhigh,'positive_curvature_draw_fraction':pos.mean(),'body_p10':lo,'body_p90':hi,'body_p05':min5,'body_p95':max95,'inside_supported_range':bool(lo<=vertex<=hi),'both_sides_supported':bool((bodies<vertex).mean()>=.1 and (bodies>vertex).mean()>=.1)}
    return r

def individual(q,models):
    records=[];residuals=[];support=[]
    for period,mask in [('past',q.year.le(2023)),('later',q.year.ge(2024))]:
        for dist,g in q[mask].groupby('race_distance_m'):
            if not supported(g):continue
            fits=row_fit(g,omit_body=True);m=fits[0];s=m['design'];nx,_=a.standardized_nuisance(g,['burden','hist_mean','hist_last','prior_finish_fraction','log_same_count','log_starts','log_gap','event_age','age_squared'],['sex','horse_number'])
            z,lu,_=a.prior.fe_matrix(g);y=g.time.to_numpy();yr=y-z@lu.solve(np.asarray(z.T@y));xr=nx-z@lu.solve(np.asarray(z.T@nx));r=yr-xr@np.array(m['beta'])
            rr=g[['horse_id','race_distance_m','race_date','api_record_id','body_kg','sex']].copy();rr['period']=period;rr['adjusted_residual_s']=r;residuals.append(rr);models.append({'family':'individual_adjustment','period':period,'distance':int(dist),'model':m})
    res=pd.concat(residuals,ignore_index=True);csv('individual_adjusted_residuals.csv',res)
    for (horse,dist),g in res[res.period.eq('past')].groupby(['horse_id','race_distance_m']):
        eligible=len(g)>=30 and g.body_kg.nunique()>=8 and g.body_kg.max()-g.body_kg.min()>=20
        support.append({'horse_id':horse,'distance':int(dist),'past_starts':len(g),'past_distinct_body':g.body_kg.nunique(),'past_body_span':g.body_kg.max()-g.body_kg.min(),'eligible':eligible})
        if not eligible:continue
        gg=res[(res.horse_id==horse)&res.race_distance_m.eq(dist)]
        for period,z in gg.groupby('period'):
            enough=period=='past' or (len(z)>=15 and z.body_kg.nunique()>=6 and z.body_kg.max()-z.body_kg.min()>=15)
            if not enough:continue
            center=float(g.body_kg.median());v=(z.body_kg.to_numpy()-center)/10;xx=np.column_stack([np.ones(len(z)),v,v*v]);bread=np.linalg.inv(xx.T@xx);coef=bread@(xx.T@z.adjusted_residual_s.to_numpy());e=z.adjusted_residual_s.to_numpy()-xx@coef;cov=bread@((xx*e[:,None]).T@(xx*e[:,None]))@bread*len(z)/(len(z)-3);se=np.sqrt(cov[2,2]);critical=t.ppf(.975,len(z)-3);vertex=center-10*coef[1]/(2*coef[2]) if coef[2]>0 else np.nan;lo,hi=z.body_kg.quantile([.1,.9]);inside=lo<=vertex<=hi;left=int((z.body_kg<vertex).sum());right=int((z.body_kg>vertex).sum())
            records.append({'horse_id':horse,'distance':int(dist),'period':period,'starts':len(z),'distinct_body':z.body_kg.nunique(),'body_min':z.body_kg.min(),'body_max':z.body_kg.max(),'center_kg':center,'linear':coef[1],'quadratic':coef[2],'ci_lo':coef[2]-critical*se,'ci_hi':coef[2]+critical*se,'p':float(2*t.sf(abs(coef[2]/se),len(z)-3)),'vertex_kg':vertex,'inside_supported_range':inside,'starts_left':left,'starts_right':right})
    df=bh(pd.DataFrame(records),['period']);df['candidate']=df.quadratic.gt(0)&df.ci_lo.gt(0)&df.q_BH.lt(.05)&df.inside_supported_range&df.starts_left.ge(5)&df.starts_right.ge(5)
    csv('individual_support.csv',pd.DataFrame(support));csv('individual_curve_results.csv',df)
    past=df[df.period.eq('past')].copy();later=df[df.period.eq('later')];joined=past.merge(later,on=['horse_id','distance'],how='left',suffixes=('_past','_later'),validate='one_to_one');joined['vertex_gap_kg']=(joined.vertex_kg_later-joined.vertex_kg_past).abs();joined['repeated_candidate']=joined.candidate_past&joined.candidate_later.fillna(False)&joined.vertex_gap_kg.le(5);csv('individual_period_comparison.csv',joined)
    nearfar=[]
    for r in joined[joined.candidate_past].itertuples():
        g=res[res.period.eq('later')&res.horse_id.eq(r.horse_id)&res.race_distance_m.eq(r.distance)].copy();g['distance_from_past_vertex']=(g.body_kg-r.vertex_kg_past).abs();g['group']=np.where(g.distance_from_past_vertex.le(5),'near',np.where(g.distance_from_past_vertex.ge(10),'far','middle'));n=g.group.value_counts()
        if n.get('near',0)>=5 and n.get('far',0)>=5:nearfar.append(g[g.group.ne('middle')].assign(past_vertex=r.vertex_kg_past))
    if nearfar:csv('individual_later_near_far_rows.csv',pd.concat(nearfar,ignore_index=True))
    else:csv('individual_later_near_far_rows.csv',pd.DataFrame(columns=['horse_id','race_distance_m','race_date','api_record_id','body_kg','adjusted_residual_s','group']))
    result={'eligible_horse_distance_cells':len(past),'past_candidates':int(past.candidate.sum()),'later_supported_cells':len(later),'later_candidates_all_supported':int(later.candidate.sum()),'past_candidates_with_later_support':int(joined[joined.candidate_past].starts_later.notna().sum()),'repeated_candidates':int(joined.repeated_candidate.sum()),'near_far_supported_past_candidates':len(nearfar),'label':'retrospective_shape_repetition_not_out_of_sample_prediction'};save('individual_summary.json',result)
    return result

def main():
    q,pairs,dbsha=load();models=[];effects=[];curves=[];sexdiff=[];status=[]
    for period,(lo,hi) in PLAN['pair_periods'].items():
        for variant in (['primary','stable','no_prior_performance'] if period=='full' else ['primary']):
            z=pairs[pairs.year.between(lo,hi)];z=z[z.stable_for_body] if variant=='stable' else z
            for dist,g in z.groupby('distance'):
                status.append({'family':'pair','period':period,'variant':variant,'distance':int(dist),**info(g),'estimated':supported(g,True)})
                if not supported(g,True):continue
                for m in pair_fit(g,variant):
                    models.append({'family':'pair','period':period,'variant':variant,'distance':int(dist),'model':m})
                    for exposure in ['gain10','loss10']:effects.append({'family':'pair','period':period,'variant':variant,'distance':int(dist),'target':m['target'],'sex':'all','exposure':exposure,**info(g),**infer(m,vec(m,exposure))})
                print('pair',period,variant,int(dist),len(g),flush=True)
    for period,(lo,hi) in PLAN['row_periods'].items():
        for variant in (['absolute','no_history','within_median'] if period=='full' else ['absolute']):
            for dist,g in q[q.year.between(lo,hi)].groupby('race_distance_m'):
                status.append({'family':'row','period':period,'variant':variant,'distance':int(dist),**info(g),'estimated':supported(g)})
                if not supported(g):continue
                for m in row_fit(g,variant):
                    models.append({'family':'row','period':period,'variant':variant,'distance':int(dist),'model':m});curves.append({'period':period,'variant':variant,'distance':int(dist),'target':m['target'],**curve_info(m,g,within=variant=='within_median')})
                    for kg in ([-10,0,10] if variant=='within_median' else [260,280,300]):
                        body1=(kg/10 if variant=='within_median' else (kg-278)/10);c1='body_deviation10' if variant=='within_median' else 'body10';c2='body_deviation2' if variant=='within_median' else 'body2';v=vec(m,c1)+vec(m,c2,2*body1+1)
                        effects.append({'family':'row','period':period,'variant':variant,'distance':int(dist),'target':m['target'],'sex':'all','exposure':f'plus10kg_from{kg}',**info(g),**infer(m,v)})
                print('row',period,variant,int(dist),len(g),flush=True)
    # Sex-specific response estimates and direct differences use a single joint model.
    for family,data,distcol in [('pair',pairs[pairs.sex_inference_ok],'distance'),('row',q[q.sex_inference_ok],'race_distance_m')]:
        for dist,g in data.groupby(distcol):
            enough=all(supported(g[g.sex.eq(sx)],family=='pair') and len(g[g.sex.eq(sx)])>=100 for sx in ['수','암','거'])
            status.append({'family':family+'_sex','period':'full','variant':'joint','distance':int(dist),**info(g),'estimated':enough})
            if not enough:continue
            fits=pair_fit(g,sex=True) if family=='pair' else row_fit(g,sex=True)
            for m in fits:
                models.append({'family':family+'_sex','period':'full','variant':'joint','distance':int(dist),'model':m})
                if family=='pair':
                    for sx in ['수','암','거']:
                        for exposure in ['gain10','loss10']:effects.append({'family':'pair_sex','period':'full','variant':'joint','distance':int(dist),'target':m['target'],'sex':sx,'exposure':exposure,**info(g[g.sex.eq(sx)]),**infer(m,vec(m,exposure+'_'+sx))})
                    for exposure in ['gain10','loss10']:sexdiff.append({'family':'pair','period':'full','distance':int(dist),'target':m['target'],'contrast':'female_minus_male_'+exposure,**infer(m,vec(m,exposure+'_암')-vec(m,exposure+'_수'))})
                else:
                    for sx in ['수','암','거']:curves.append({'period':'full','variant':'sex_joint','distance':int(dist),'target':m['target'],**curve_info(m,g[g.sex.eq(sx)],sex=sx)})
                    v=np.row_stack([vec(m,c+'_암')-vec(m,c+'_수') for c in ['body10','body2']]);b=v@np.array(m['beta']);cov=v@np.array(m['cov'])@v.T;stat=float(b@np.linalg.pinv(cov)@b/2);sexdiff.append({'family':'row','period':'full','distance':int(dist),'target':m['target'],'contrast':'female_minus_male_curve_2df','effect':stat,'p':float(f.sf(stat,2,m['critical_df']))})
            print(family,'sex',int(dist),len(g),flush=True)
    ef=bh(pd.DataFrame(effects),['family','period','variant','sex','exposure']);cu=bh(pd.DataFrame(curves),['period','variant','sex']);sd=bh(pd.DataFrame(sexdiff),['family','period','contrast'])
    cu['candidate_supported']=cu.quadratic.gt(0)&cu.ci_lo.gt(0)&cu.q_BH.lt(.05)&cu.inside_supported_range&cu.both_sides_supported&cu.vertex_ci_lo.ge(cu.body_p05)&cu.vertex_ci_hi.le(cu.body_p95)
    csv('effects.csv',ef);csv('body_curves.csv',cu);csv('sex_differences.csv',sd);csv('model_support.csv',pd.DataFrame(status))
    ind=individual(q,models);save('models.json',clean(models))
    assert sha(a.old.DB)==dbsha
    for z in json.loads((H/'source_manifest.json').read_text()):assert sha(Path(z['path']))==z['sha256']
    save('verification.json',{'status':'passed','models':len(models),'source_rows':len(q),'pairs':len(pairs),'database_sha256':dbsha,'all_source_hashes_unchanged':True,'database_unchanged':True,'maximum_fe_orthogonality':max(m['model']['orthogonality'] for m in models),'maximum_joint_beta_error':max(m['model']['joint_beta_error'] for m in models),'sex_from_event_not_current_profile':True,'no_fixed_correction_or_optimum_adopted':True,'individual':ind})
    print('PAIR FULL',ef[(ef.family=='pair')&ef.period.eq('full')&ef.variant.eq('primary')&ef.target.eq('time_s')][['distance','exposure','rows','effect','ci_lo','ci_hi','q_BH']].to_string(index=False),flush=True)
    print('CURVE FULL',cu[cu.period.eq('full')&cu.variant.eq('absolute')&cu.target.eq('time_s')][['distance','quadratic','ci_lo','ci_hi','q_BH','vertex_kg_or_deviation','vertex_ci_lo','vertex_ci_hi','candidate_supported']].to_string(index=False),flush=True)
    print('SEX DIFF',sd[sd.target.eq('time_s')][['family','distance','contrast','effect','p','q_BH']].to_string(index=False),flush=True)
    print('INDIVIDUAL',ind,flush=True)
if __name__=='__main__':main()

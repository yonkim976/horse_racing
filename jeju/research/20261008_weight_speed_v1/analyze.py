"""Read-only Jeju body mass, carried load and average-speed associations."""
from pathlib import Path
import importlib.util
import json
import re
import sqlite3
import numpy as np
import pandas as pd
from scipy.stats import t, spearmanr
from scipy.sparse import bmat, csc_matrix, diags
from scipy.sparse.linalg import spsolve

H=Path(__file__).resolve().parent;ROOT=H.parents[2]
PRE=H.parent/'20261008_gate_record_seconds_v1'
sp=importlib.util.spec_from_file_location('weight_prior',PRE/'analyze.py');prior=importlib.util.module_from_spec(sp);sp.loader.exec_module(prior)
old=prior.old;sha=prior.sha;PLAN=json.loads((H/'PLAN.json').read_text());DIST=PLAN['distances'];BANDS=['건조','양호','다습','포화','불량'];SEED=20261008
def save(name,v):
    with (H/name).open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2,allow_nan=False)
def csv(name,df):
    with (H/name).open('x',encoding='utf-8') as f:df.to_csv(f,index=False)
def support(g,pairs=False):
    minimum=PLAN['pair_minimum' if pairs else 'row_minimum'];n=len(g) if pairs else g.race_id.nunique()
    return {'rows':len(g),'races':int(g.race_id.nunique()),'dates':int(g.race_date.nunique()),'horses':int(g.horse_id.nunique()),
            'supported':bool(n>=minimum['pairs' if pairs else 'races'] and g.race_date.nunique()>=minimum['dates'] and g.horse_id.nunique()>=minimum['horses'])}

def load():
    dbhash=sha(old.DB);before=old.DB.stat();d,h=old.load();q=old.all_features(d,h)
    q=q[q.strict&q.race_distance_m.isin(DIST)].copy()
    con=sqlite3.connect(old.DB.as_uri()+'?mode=ro',uri=True);con.execute('PRAGMA query_only=ON')
    extra=pd.read_sql_query('SELECT r.api_record_id,r.body_weight_raw,r.carried_weight_kg burden_db,r.jockey_id,a.payload_sha256 result_payload_sha256 FROM race_result_rows r JOIN api_records a ON a.api_record_id=r.api_record_id',con)
    assert extra.api_record_id.is_unique
    q=q.merge(extra,on='api_record_id',validate='one_to_one');assert q.carried_weight_kg.eq(q.burden_db).all()
    parsed=q.body_weight_raw.str.extract(r'^\s*(\d+(?:\.\d+)?)\s*(?:\(([^()]*)\))?\s*$')
    q['body_kg']=pd.to_numeric(parsed[0],errors='coerce');q['reported_body_change_raw']=parsed[1]
    q['weight_valid']=q.body_kg.gt(0)&q.carried_weight_kg.gt(0)
    invalid=q[~q.weight_valid];csv('weight_exclusions.csv',invalid[['api_record_id','horse_id','race_date','body_weight_raw','carried_weight_kg']])
    q=q[q.weight_valid].sort_values(['race_date','race_number','horse_number']).copy()
    # Verify stored weight fields against a fixed original-API sample and all extrema.
    rng=np.random.default_rng(SEED);ids=set(rng.choice(q.api_record_id,256,replace=False).tolist())
    for col in ['body_kg','carried_weight_kg']:
        ids.update(q.loc[q[col].isin([q[col].min(),q[col].max()]),'api_record_id'].tolist())
    fields=q.set_index('api_record_id');raw_checks=[]
    for rid in sorted(ids):
        raw=con.execute('SELECT payload_json,payload_sha256 FROM api_records WHERE api_record_id=?',(int(rid),)).fetchone();r=json.loads(raw[0]);z=fields.loc[rid]
        assert str(r['wgHr'])==z.body_weight_raw and float(r['wgBudam'])==z.carried_weight_kg and raw[1]==z.result_payload_sha256
        raw_checks.append({'api_record_id':int(rid),'body_weight_raw':z.body_weight_raw,'carried_weight_kg':float(z.carried_weight_kg),'result_payload_sha256':raw[1]})
    con.close()
    excluded=json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())['horses'];assert not(set(q.horse_id)&{k for k,v in excluded.items() if not v['reimport_allowed']})
    assert q.race_date.max()=='2026-09-19' and q.api_record_id.is_unique
    fractions=[]
    for rid in q.api_record_id:
        ids=h[str(rid)];r=d.loc[ids[-1]] if ids else None
        fractions.append((r.finish_position-1)/(r.field_n-1) if r is not None and r.field_n>1 and 1<=r.finish_position<=r.field_n else np.nan)
    q['prior_finish_fraction']=fractions
    q['body10']=(q.body_kg-278)/10;q['body_squared']=q.body10**2;q['burden']=q.carried_weight_kg-55
    q['burden_body']=q.burden*q.body10;q['time']=q.finish_time_seconds;q['log_time100']=100*np.log(q.time)
    q['speed_mps']=q.race_distance_m/q.time;q['load_pct_body']=100*q.carried_weight_kg/q.body_kg
    q['relative_time']=q.time-q.groupby('race_id').time.transform('median');q['finish_fraction']=(q.finish_position-1)/(q.field_n-1)
    cols=['api_record_id','race_id','horse_id','race_date','race_distance_m','year','month','field_n','horse_number','rank_class_raw','finish_position','time','speed_mps','body_weight_raw','body_kg','reported_body_change_raw','carried_weight_kg','load_pct_body','jockey_id','moisture','band','history_cutoff','api4_3_payload_sha256','result_payload_sha256']
    csv('source_lineage.csv',q[cols]);csv('weight_api_sample_checks.csv',pd.DataFrame(raw_checks))
    assert sha(old.DB)==dbhash and old.DB.stat().st_mtime_ns==before.st_mtime_ns
    save('input_audit.json',{'database_sha256':dbhash,'database_bytes':before.st_size,'database_unchanged':True,'rows':len(q),'races':int(q.race_id.nunique()),'horses':int(q.horse_id.nunique()),'body_missing_or_invalid':len(invalid),'body_min_max_kg':[float(q.body_kg.min()),float(q.body_kg.max())],'burden_min_max_kg':[float(q.carried_weight_kg.min()),float(q.carried_weight_kg.max())],'body_parser_all_valid':bool(len(invalid)==0),'original_api_weight_samples_checked':len(raw_checks),'actual_burden_agrees_quality_extraction':True,'body_is_retrospective_current_race_measurement':True})
    return d,h,q,dbhash

def correlation(x,y):
    x=np.asarray(x,float);y=np.asarray(y,float)
    return float(np.corrcoef(x,y)[0,1]) if np.std(x)>1e-12 and np.std(y)>1e-12 else None
def corr_boot(g):
    z=pd.DataFrame({'horse':g.horse_id,'n':1.,'x':g.body_kg,'y':g.carried_weight_kg,'xx':g.body_kg**2,'yy':g.carried_weight_kg**2,'xy':g.body_kg*g.carried_weight_kg}).groupby('horse').sum().to_numpy()
    rng=np.random.default_rng(SEED);out=[]
    for _ in range(1000):
        n,x,y,xx,yy,xy=z[rng.integers(0,len(z),len(z))].sum(axis=0);out.append((xy-x*y/n)/np.sqrt((xx-x*x/n)*(yy-y*y/n)))
    return np.quantile(out,[.025,.975]).tolist()
def describe(q):
    correlations=[]
    for distance,g in [(0,q)]+list(q.groupby('race_distance_m')):
        lo,hi=corr_boot(g);horse=g.groupby('horse_id')[['body_kg','carried_weight_kg']].mean()
        wh=g[['body_kg','carried_weight_kg']]-g.groupby('horse_id')[['body_kg','carried_weight_kg']].transform('mean')
        wr=g[['body_kg','carried_weight_kg']]-g.groupby('race_id')[['body_kg','carried_weight_kg']].transform('mean')
        z,lu,fe=prior.fe_matrix(g);v=g[['body_kg','carried_weight_kg']].to_numpy();both=v-z@lu.solve(np.asarray(z.T@v))
        correlations.append({'distance':int(distance),**support(g),'pearson_raw':correlation(g.body_kg,g.carried_weight_kg),'raw_horse_boot_lo':lo,'raw_horse_boot_hi':hi,'spearman_raw':float(spearmanr(g.body_kg,g.carried_weight_kg).statistic),'horse_mean_pearson':correlation(horse.body_kg,horse.carried_weight_kg),'within_horse_pearson':correlation(wh.body_kg,wh.carried_weight_kg),'within_race_pearson':correlation(wr.body_kg,wr.carried_weight_kg),'race_horse_residual_pearson':correlation(both[:,0],both[:,1]),'mean_body_kg':float(g.body_kg.mean()),'mean_carried_kg':float(g.carried_weight_kg.mean()),'mean_load_pct_body':float(g.load_pct_body.mean())})
    csv('body_burden_correlations.csv',pd.DataFrame(correlations))
    q=q.copy();q['body_bin']=pd.cut(q.body_kg,[0,250,280,310,np.inf],right=False,labels=['under250','250to279','280to309','310plus'])
    csv('body_load_groups.csv',q.groupby(['race_distance_m','body_bin'],observed=True).agg(starts=('api_record_id','size'),horses=('horse_id','nunique'),body_mean_kg=('body_kg','mean'),burden_mean_kg=('carried_weight_kg','mean'),load_mean_pct=('load_pct_body','mean')).reset_index())
    csv('annual_support.csv',q.groupby(['race_distance_m','year']).agg(rows=('api_record_id','size'),races=('race_id','nunique'),dates=('race_date','nunique'),horses=('horse_id','nunique')).reset_index())

def standardized_nuisance(g,numeric,cats=()):
    frame=pd.DataFrame(index=g.index);medians={}
    for col in numeric:
        v=pd.to_numeric(g[col],errors='coerce');med=float(v.median()) if v.notna().any() else 0.;medians[col]=med
        frame[col]=v.fillna(med);frame[col+'_missing']=v.isna().astype(float)
    for col in cats:
        for level in sorted(g[col].astype(str).unique())[1:]:frame[col+'='+level]=g[col].astype(str).eq(level).astype(float)
    sd=frame.std(ddof=0).replace(0,1);mean=frame.mean()
    return ((frame-mean)/sd).to_numpy(),{'nuisance_columns':list(frame.columns),'nuisance_means':mean.tolist(),'nuisance_sd':sd.tolist(),'nuisance_medians':medians}

def core_fit(x,y,g,columns,n_targets,fe=True,horse=True):
    if fe:
        z,lu,info=prior.fe_matrix(g,horse);v=np.column_stack([y,x]);rr=v-z@lu.solve(np.asarray(z.T@v));yr=rr[:,:y.shape[1]];xr=rr[:,y.shape[1]:];orth=float(np.max(np.abs(z.T@rr)))
        assert orth<1e-7
    else:xr=x;yr=y;info={'rank':0};orth=0.;z=None
    xx=xr[:,:n_targets]
    if x.shape[1]>n_targets:xx=xx-xr[:,n_targets:]@np.linalg.lstsq(xr[:,n_targets:],xx,rcond=1e-9)[0]
    assert np.linalg.matrix_rank(xx,tol=1e-7)==n_targets,('target_identification',np.linalg.matrix_rank(xx))
    rank=int(np.linalg.matrix_rank(xr,tol=1e-7));df=len(g)-info['rank']-rank;assert df>20,('df',df)
    penalty=np.r_[np.zeros(n_targets),np.ones(x.shape[1]-n_targets)]
    if not fe:penalty[columns.index('intercept')]=0
    bread=np.linalg.inv(xr.T@xr+np.diag(penalty));beta=bread@(xr.T@yr)
    joint_error=0.
    if fe:
        xs=csc_matrix(x);system=bmat([[z.T@z,z.T@xs],[xs.T@z,xs.T@xs+diags(penalty)]],format='csc');rhs=np.vstack([z.T@y,x.T@y]);joint=spsolve(system,rhs)
        joint_error=float(np.max(np.abs(joint[z.shape[1]:]-beta)));assert joint_error<1e-6,joint_error
    critdf=int(min(g.race_date.nunique(),g.horse_id.nunique())-1);models=[]
    for j,target in enumerate(['time_s','log_time100']):
        res=yr[:,j]-xr@beta[:,j];dc=prior.cluster_cov(xr,res,bread,g.race_date,df);hc=prior.cluster_cov(xr,res,bread,g.horse_id,df);cov=dc+hc
        assert np.linalg.eigvalsh(cov).min()>-1e-7
        models.append({'target':target,'columns':columns,'beta':beta[:,j].tolist(),'cov':cov.tolist(),'date_cov':dc.tolist(),'horse_cov':hc.tolist(),'critical_df':critdf,'residual_df':int(df),'fe':info,'orthogonality':orth,'joint_beta_error':joint_error})
    return models
def infer(m,vector):
    v=np.asarray(vector);pt=float(v@np.array(m['beta']));se=float(np.sqrt(max(0,v@np.array(m['cov'])@v)));cr=float(t.ppf(.975,m['critical_df']));lo=pt-cr*se;hi=pt+cr*se
    out={'effect':pt,'ci_lo':lo,'ci_hi':hi,'se':se,'p':float(2*t.sf(abs(pt/se),m['critical_df'])) if se>0 else 1.}
    if m['target']=='log_time100':out|={'speed_change_pct_per_kg':100*np.expm1(-pt/100),'speed_ci_lo_pct':100*np.expm1(-hi/100),'speed_ci_hi_pct':100*np.expm1(-lo/100)}
    return out
def get_vector(m,column,value=1.):
    v=np.zeros(len(m['columns']));v[m['columns'].index(column)]=value;return v
def row_fit(g,variant):
    numeric=['hist_mean','hist_last','prior_finish_fraction','log_same_count','log_starts','log_gap','event_age','age_squared','body_squared']
    if variant=='no_history':numeric=[c for c in numeric if c not in ['hist_mean','hist_last','prior_finish_fraction']]
    nx,s=standardized_nuisance(g,numeric,['sex','horse_number']);targets=['burden','body10']+(['burden_body'] if variant=='interaction' else [])
    x=np.column_stack([g[targets].to_numpy(),nx]);columns=targets+s['nuisance_columns'];y=g[['time','log_time100']].to_numpy()
    fits=core_fit(x,y,g,columns,len(targets),horse=variant!='race_only')
    for m in fits:m['design']=s
    return fits

def make_pairs(q):
    g=q.sort_values(['horse_id','race_distance_m','race_date','race_number']).reset_index(drop=True)
    pre=g.groupby(['horse_id','race_distance_m'],sort=False).shift();gap=(pd.to_datetime(g.race_date)-pd.to_datetime(pre.race_date)).dt.days
    keep=gap.between(7,60)&g.year.eq(pre.year)&g.grade.eq(pre.grade)
    a=pre[keep].reset_index(drop=True);b=g[keep].reset_index(drop=True)
    pairs=pd.DataFrame({'pair_id':b.api_record_id.astype(int),'previous_api_record_id':a.api_record_id.astype(int),'horse_id':b.horse_id,'distance':b.race_distance_m.astype(int),'year':b.year.astype(int),'year_grade':b.year.astype(str)+':'+b.grade.astype(str),'race_id':b.race_id,'previous_race_id':a.race_id,'race_date':b.race_date,'previous_date':a.race_date,'gap':gap[keep].to_numpy(),'month':b.month,'previous_month':a.month,'band':b.band,'previous_band':a.band,'body_kg':b.body_kg,'previous_body_kg':a.body_kg,'burden_kg':b.carried_weight_kg,'previous_burden_kg':a.carried_weight_kg,'time':b.time,'previous_time':a.time,'same_jockey':b.jockey_id.eq(a.jockey_id)&b.jockey_id.notna(),'previous_finish_fraction':a.finish_fraction,'previous_relative_time':a.relative_time,'previous_hist_mean':a.hist_mean,'age':b.event_age,'field_change':b.field_n-a.field_n,'grade':b.grade})
    pairs['burden_change']=pairs.burden_kg-pairs.previous_burden_kg;pairs['increase_kg']=pairs.burden_change.clip(lower=0);pairs['decrease_kg']=pairs.burden_change.clip(upper=0)
    pairs['body_change_kg']=pairs.body_kg-pairs.previous_body_kg;pairs['body_change10']=pairs.body_change_kg/10;pairs['log_gap']=np.log1p(pairs.gap)
    pairs['time_delta']=pairs.time-pairs.previous_time;pairs['log_time_delta100']=100*np.log(pairs.time/pairs.previous_time);pairs['speed_change_pct']=100*(pairs.previous_time/pairs.time-1)
    pairs['relative_time_delta']=b.relative_time-a.relative_time
    for bb in BANDS[1:]:pairs['band='+bb]=b.band.eq(bb).astype(float)-a.band.eq(bb).astype(float)
    for k in range(1,int(q.horse_number.max())):pairs[f'gate={k}']=b.horse_number.eq(k).astype(float)-a.horse_number.eq(k).astype(float)
    def phase(s):
        dt=pd.to_datetime(s);return 2*np.pi*(dt.dt.dayofyear.to_numpy()-1)/np.where(dt.dt.is_leap_year,366,365)
    ph=phase(b.race_date);pa=phase(a.race_date)
    for k in [1,2]:pairs[f'sin{k}']=np.sin(k*ph)-np.sin(k*pa);pairs[f'cos{k}']=np.cos(k*ph)-np.cos(k*pa)
    pairs['stable_conditions']=pairs.band.eq(pairs.previous_band)&pairs.month.eq(pairs.previous_month)&pairs.body_change_kg.abs().le(5)
    assert pairs.pair_id.is_unique and pairs.gap.between(7,60).all();ref=q.set_index('api_record_id')
    for col in ['horse_id','race_distance_m','year','grade']:
        assert np.array_equal(ref.loc[pairs.pair_id,col].to_numpy(),ref.loc[pairs.previous_api_record_id,col].to_numpy())
    assert (pairs.previous_date<pairs.race_date).all()
    csv('pair_lineage.csv',pairs)
    pairs['change_group']=np.select([pairs.burden_change.le(-3),pairs.burden_change.le(-1),pairs.burden_change.lt(1),pairs.burden_change.lt(3),pairs.burden_change.lt(5)],['down3plus','down1toUnder3','stableUnder1','up1toUnder3','up3toUnder5'],default='up5plus')
    csv('raw_change_groups.csv',pairs.groupby(['distance','change_group']).agg(pairs=('pair_id','size'),horses=('horse_id','nunique'),mean_burden_change_kg=('burden_change','mean'),mean_time_delta_s=('time_delta','mean'),median_time_delta_s=('time_delta','median'),mean_speed_change_pct=('speed_change_pct','mean'),mean_previous_finish_fraction=('previous_finish_fraction','mean'),mean_body_change_kg=('body_change_kg','mean')).reset_index())
    csv('pair_support.csv',pairs.groupby(['distance','year']).agg(pairs=('pair_id','size'),horses=('horse_id','nunique'),dates=('race_date','nunique'),increased_pairs=('increase_kg',lambda x:int((x>0).sum())),stable_pairs=('burden_change',lambda x:int((x==0).sum()))).reset_index())
    return pairs
def pair_fit(g,variant):
    numeric=['body_change10','previous_burden_kg','log_gap','age','previous_relative_time','previous_finish_fraction','previous_hist_mean','field_change']
    if variant=='no_previous_performance':numeric=[c for c in numeric if c not in ['previous_relative_time','previous_finish_fraction','previous_hist_mean']]
    numeric += [c for c in g.columns if c.startswith(('band=','gate='))]+['sin1','cos1','sin2','cos2']
    nx,s=standardized_nuisance(g,numeric,['year_grade']);columns=['increase_kg','decrease_kg','intercept']+s['nuisance_columns']
    x=np.column_stack([g[['increase_kg','decrease_kg']].to_numpy(),np.ones(len(g)),nx]);y=g[['time_delta','log_time_delta100']].to_numpy()
    fits=core_fit(x,y,g,columns,2,fe=False)
    for m in fits:m['design']=s
    return fits

def main():
    refs=[H/'PLAN.json',H/'CONTEXT_SNAPSHOT.md',H/'analyze.py',PRE/'analyze.py',old.HERE/'analyze.py',old.OLD/'modeling.py',old.OLD/'audit/source_rows.csv',old.OLD/'audit/history_ids.json',ROOT/'jeju/scripts/build_native_core_from_api_raw.py',ROOT/'jeju/data/horse_exclusions.json']
    sources=[{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in refs];save('source_manifest.json',sources)
    d,h,q,dbhash=load();describe(q);pairs=make_pairs(q);models=[];rows=[];sup=[]
    for period,(start,end) in PLAN['row_periods'].items():
        for distance in DIST:
            g=q[q.race_distance_m.eq(distance)&q.year.between(start,end)]
            for variant in (['primary','race_only','no_history','exact_ten','interaction'] if period=='full' else ['primary']):
                if variant=='exact_ten':g1=g[g.field_n.eq(10)]
                else:g1=g
                s=support(g1);entry={'family':'row','period':period,'distance':distance,'variant':variant}|s
                if not s['supported']:sup.append(entry|{'estimated':False});continue
                try:fits=row_fit(g1,variant)
                except AssertionError as exc:sup.append(entry|{'estimated':False,'reason':str(exc)});continue
                sup.append(entry|{'estimated':True})
                for m in fits:
                    models.append(entry|{'model':m})
                    for col in ['burden','body10']+(['burden_body'] if variant=='interaction' else []):rows.append(entry|{'target':m['target'],'exposure':col}|infer(m,get_vector(m,col)))
                    if variant=='interaction':
                        for body in [250,280,310]:rows.append(entry|{'target':m['target'],'exposure':f'burden_at_body{body}kg'}|infer(m,get_vector(m,'burden')+get_vector(m,'burden_body',(body-278)/10)))
                print('row',period,distance,variant,len(g1),flush=True)
    for period,(start,end) in PLAN['pair_periods'].items():
        for distance in DIST:
            base=pairs[pairs.distance.eq(distance)&pairs.year.between(start,end)]
            for variant in (['primary','no_previous_performance','stable_conditions','same_jockey'] if period=='full' else ['primary']):
                g=base[base[variant]] if variant in ['stable_conditions','same_jockey'] else base
                s=support(g,True);entry={'family':'pair','period':period,'distance':distance,'variant':variant}|s
                if not s['supported']:sup.append(entry|{'estimated':False});continue
                try:fits=pair_fit(g,variant)
                except AssertionError as exc:sup.append(entry|{'estimated':False,'reason':str(exc)});continue
                sup.append(entry|{'estimated':True})
                for m in fits:
                    models.append(entry|{'model':m})
                    for col in ['increase_kg','decrease_kg']:rows.append(entry|{'target':m['target'],'exposure':col}|infer(m,get_vector(m,col)))
                print('pair',period,distance,variant,len(g),flush=True)
    result=pd.DataFrame(rows)
    for _,g in result.groupby(['family','period','variant','exposure']):result.loc[g.index,'q_BH']=old.bh(g.p)
    csv('effects.csv',result);csv('support.csv',pd.DataFrame(sup));save('models.json',models)
    assert all(sha(Path(m['path']))==m['sha256'] for m in sources) and sha(old.DB)==dbhash
    # Full endpoint history checks, without replacing current observed body mass with T-2 data.
    ref=d[['horse_id','race_distance_m','race_date']].to_dict('index');checked=0
    for r in q.itertuples():
        for rid in h[str(r.api_record_id)]:
            v=ref[rid];assert v['horse_id']==r.horse_id and v['race_distance_m']==r.race_distance_m and v['race_date']<=r.history_cutoff;checked+=1
    save('verification.json',{'status':'passed','database_and_sources_unchanged':True,'database_sha256':dbhash,'source_rows':len(q),'races':int(q.race_id.nunique()),'pair_count':len(pairs),'fitted_outcome_models':len(models),'history_endpoints_checked':checked,'all_pair_keys_distance_year_grade_valid':True,'projected_vs_augmented_joint_beta_max_error':max(m['model']['joint_beta_error'] for m in models),'projection_orthogonality_max':max(m['model']['orthogonality'] for m in models),'current_body_mass_is_retrospective':True,'fixed_per_kg_correction_adopted':False,'operational_change':False})
    print(result.query("variant=='primary' and exposure in ['burden','increase_kg']")[['family','period','distance','target','exposure','rows','effect','ci_lo','ci_hi','q_BH']].to_string(index=False),flush=True)
if __name__=='__main__':main()

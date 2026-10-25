"""Raw section audit, SQL future-slot joins, independent absorbed OLS and clusters."""
from pathlib import Path
import json,gzip,hashlib,math,itertools
from collections import defaultdict
import numpy as np,pandas as pd,duckdb
from scipy.stats import t
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';checks=0
TARGETS=['next_top3','three_top3','return180','any180_top3','next_abnormal_zero']
def ck(ok,label,n=1):
    global checks
    assert bool(ok),label;checks+=n
def close(a,b,label):
    a=np.asarray(a,float);b=np.asarray(b,float);ck(a.shape==b.shape and np.allclose(a,b,atol=1e-9,rtol=1e-8,equal_nan=True),label,a.size)
def choose(d,w):return d[d.year.between(2024,2025)&d.mature180] if w=='2024_2025' else d[d.year.eq(2026)&d.mature180] if w=='2026_mature' else d[d.year.le(2023)&d.mature180]
def sample(d,r):
    col=r.definition+'_'+str(r.segment);g=choose(d,r.window);return g[g.meet.eq(r.meet)&g.normal_outcome&g.raw_finish_rank.gt(3)&g.quality_base&g[col].notna()].copy(),col
def scored(g,score,estimate,target):
    vals=[];ns=[]
    for keys in [g.horse_id.tolist(),g.date.tolist(),list(zip(g.horse_id,g.date))]:
        sums=defaultdict(float)
        for key,x in zip(keys,score):sums[key]+=x
        n=len(sums);ns.append(n);vals.append(sum(x*x for x in sums.values())*n/(n-1) if n>1 else np.nan)
    sums=defaultdict(float)
    for i,r in enumerate(g.itertuples()):
        for lag in ([1,2,3] if target in ['three_top3','any180_top3'] else [1]):
            if getattr(r,'future_within'+str(lag)):sums[getattr(r,'future_date'+str(lag))]+=score[i]
    nf=len(sums);vf=sum(x*x for x in sums.values())*nf/(nf-1) if nf>1 else 0.
    if min(ns[:2])<2:return [estimate,np.nan,np.nan,np.nan,np.nan,np.nan]
    se=math.sqrt(max(0,vals[0],vals[1],vals[0]+vals[1]-vals[2],vf));df=min(ns[:2]+([nf] if nf>1 else []))-1;c=t.ppf(.975,df);p=2*t.sf(abs(estimate/se),df) if se else float(estimate==0)
    return [estimate,se,estimate-c*se,estimate+c*se,p,df]
def bh(p):
    p=np.array(p);idx=np.argsort(p);v=np.minimum.accumulate((p[idx]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];out=np.zeros(len(p));out[idx]=np.minimum(1,v);return out
def independent_controls(g,stage='full'):
    blocks=[g.raw_finish_rank.eq(k).to_numpy(float) for k in range(5,int(g.raw_finish_rank.max())+1)] if stage in ['finish','full'] else []
    fields=(['finish_gap'] if stage in ['finish','full'] else [])+(['finish_p_mean5','valid_position5','rating','age_current'] if stage in ['past','finish','full'] else [])+(['p_s1f'] if stage=='full' else [])
    for name in fields:
        a=g[name];value=a.fillna(.5 if name in ['finish_p_mean5','p_s1f'] else 0);blocks.extend([a.isna().to_numpy(float),value.to_numpy(float),(value**2).to_numpy(float)])
    return np.column_stack(blocks) if blocks else np.zeros((len(g),0))
def verify_contrast(db,g,col,r,details=None):
    z=g[g[r.target].notna()].copy();n0=len(z)
    if r.method=='raw':
        a=z[z[col].eq(1)];b=z[z[col].eq(0)];ma=a[r.target].mean();mb=b[r.target].mean();score=np.r_[(a[r.target]-ma)/len(a),-(b[r.target]-mb)/len(b)];z=pd.concat([a,b]);est=ma-mb;close([len(a),len(b),ma,mb],[r.n_a,r.n_b,r.mean_a,r.mean_b],'raw comparison support')
    elif r.method=='same_race_adjusted':
        db.register('sample',z);keys=db.execute(f'SELECT source_key FROM sample GROUP BY source_key HAVING min("{col}")=0 AND max("{col}")=1').df().source_key;z=z[z.source_key.isin(keys)];control=independent_controls(z,getattr(r,'stage','full'));x=z[col].to_numpy();y=z[r.target].to_numpy();X=np.column_stack([x,control]);frame=pd.DataFrame(np.column_stack([y,X]),index=z.index);centered=frame-frame.groupby(z.source_key).transform('mean');y0=centered.iloc[:,0].to_numpy();X0=centered.iloc[:,1:].to_numpy();beta,_,rank,_=np.linalg.lstsq(X0,y0,rcond=None);errors=y0-X0@beta;score=np.linalg.pinv(X0)[0]*errors*np.sqrt(len(z)/(len(z)-len(keys)-rank));est=beta[0]
        close([x.sum(),len(z)-x.sum(),rank-1,len(keys),len(z)/n0],[r.n_a,r.n_b,r.control_rank,r.absorbed_races,r.coverage],'independent race absorption support')
    elif r.method=='same_horse':
        z['cell']=z[['horse_id','meet','distance_m','grade_bucket']].astype(str).agg('|'.join,axis=1);db.register('sample',z);s=db.execute(f'SELECT cell,"{col}" side,count(*) n,avg("{r.target}") mean FROM sample GROUP BY cell,side').df().pivot(index='cell',columns='side',values=['n','mean']);s=s[s['n'][[0.,1.]].notna().all(axis=1)];w=s['n'][1.]*s['n'][0.]/(s['n'][1.]+s['n'][0.]);weights=w/w.sum();ma=float((weights*s['mean'][1.]).sum());mb=float((weights*s['mean'][0.]).sum());z=z[z.cell.isin(s.index)];score=[]
        for a in z.to_dict('records'):
            side=a[col];score.append((1 if side==1 else -1)*weights[a['cell']]/s['n'][side][a['cell']]*(a[r.target]-(ma if side==1 else mb)))
        est=ma-mb;close([z[col].eq(1).sum(),z[col].eq(0).sum(),len(z)/n0,len(s),ma,mb],[r.n_a,r.n_b,r.coverage,r.cells,r.mean_a,r.mean_b],'same horse means/support')
        cs=details[(details.window==r.window)&(details.meet==r.meet)&(details.segment==r.segment)&(details.definition==r.definition)&(details.target==r.target)].set_index('cell');ck(set(cs.index)==set(s.index),'horse cells identities');close(w.loc[cs.index],cs.weight,'harmonic weights')
        for side,suffix in [(1.,'a'),(0.,'b')]:close(s['n'][side].loc[cs.index],cs['n_'+suffix],'horse cell counts');close(s['mean'][side].loc[cs.index],cs['mean_'+suffix],'horse cell means')
    close(scored(z,np.asarray(score),est,r.target),[r.estimate,r.se,r.lower,r.upper,r.p,r.df],'independent estimate and multi-cluster CI')
def main():
    d=pd.read_parquet(O/'analysis_rows.parquet');db=duckdb.connect();db.register('d',d);ck(len(d)==159014 and d.row_key.is_unique and d.source_key.nunique()==14636,'whole roster')
    audit=json.loads((O/'source_audit.json').read_text())
    for a in audit['inputs']:
        p=ROOT/a['path'];ck(p.stat().st_size==a['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==a['sha256'],'input hash')
    raw_n=0
    for filename,g in d.groupby('source_file'):
        p=(ROOT/filename).resolve();ck(p.is_relative_to((R/'20260929_calendar_api_v1/raw/race_execution_probe').resolve()),'raw boundary');items=json.load(gzip.open(p,'rt'))['response']['body']['items']['item']
        for r in g.itertuples():
            a=items[int(r.source_item_index)];ck(str(a['hrNo']).zfill(7)==r.horse_id and int(a['rcDate'])==int(r.date.strftime('%Y%m%d')) and int(a['rcNo'])==int(r.source_key.split(':')[-1]),'raw identity');close(a['ord'],r.raw_finish_rank,'raw finish rank');bus=r.meet=='부산';finish=float(a['rcTime']);tail=[float(a['bu_3fGTime']),float(a['bu_2fGTime']),float(a['bu_1fGTime'])] if bus else [finish-float(a['seG3fAccTime']),np.nan,finish-float(a['seG1fAccTime'])];acc=[float(a['buG3fAccTime']),float(a['buG2fAccTime']),float(a['buG1fAccTime'])] if bus else [float(a['seG3fAccTime']),np.nan,float(a['seG1fAccTime'])];close([finish]+tail+acc,[r.raw_finish_seconds,r.raw_tail600,r.raw_tail400,r.raw_tail200,r.raw_acc600,r.raw_acc400,r.raw_acc200],'raw section seconds');raw_n+=1
    sec=pd.read_parquet(R/'20261008_field_pace_prediction/outputs/section_observations.parquet').set_index('row_key');ck(np.array_equal(d.quality_base,d.row_key.isin(sec.index)),'legacy quality population')
    winner=db.execute('SELECT source_key,min(raw_finish_seconds) win FROM d WHERE raw_finish_rank=1 AND raw_finish_seconds>0 GROUP BY source_key').df().set_index('source_key').win;close(d.finish-d.source_key.map(winner),d.finish_gap,'official winner time gap including section-missing winner')
    for segment in ['600','400','200']:
        tm=d['time'+segment];tail=d['raw_tail'+segment];acc=d['raw_acc'+segment];ok=d.quality_base&d.normal_outcome&tail.gt(0)&acc.gt(0)&np.isclose(tail+acc,d.raw_finish_seconds,atol=1e-7)&d.raw_tail600.ge(d.raw_tail200)&d.raw_tail600.lt(d.raw_finish_seconds)
        if segment=='400':ok&=d.meet.eq('부산')&tail.ge(d.raw_tail200)&tail.le(d.raw_tail600)
        close(np.where(ok,tail,np.nan),tm,'independent section valid mask');ck(d.loc[tm.notna(),'raw_tail600'].ge(d.loc[tm.notna(),'raw_tail200']).all(),'nested cumulative intervals')
        sql=db.execute(f'SELECT source_key,count(time{segment}) n,quantile_cont(time{segment},0.1) q10,quantile_cont(time{segment},0.2) q20,quantile_cont(time{segment},0.3) q30 FROM d GROUP BY source_key').df().set_index('source_key');n=d.source_key.map(sql.n);adequate=n.ge(6)&n.ge(.8*d.field_size)
        for label in ['10','20','30']:
            q=d.source_key.map(sql['q'+label]);close(np.where(adequate,q,np.nan),d['race_q'+label+'_'+segment],'SQL within-race quantile');close(np.where(adequate&tm.notna(),tm.le(q+1e-9),np.nan),d['race_fast'+label+'_'+segment],'SQL good flag')
    bus=d.meet.eq('부산')&d.time400.notna();close((d.loc[bus,'time600']-d.loc[bus,'time400'])+(d.loc[bus,'time400']-d.loc[bus,'time200'])+d.loc[bus,'time200'],d.loc[bus,'time600'],'three exclusive 200m pieces sum to600');ck(d.loc[d.meet.eq('서울'),'time400'].isna().all(),'no Seoul400 fabricated')
    # SQL LEAD sees every actual roster slot, including invalid future results.
    leadcols=[]
    for lag in [1,2,3]:
        for source,name in [('row_key','key'),('date','date'),('raw_finish_rank','rank'),('field_size','size'),('meet','meet'),('distance_m','distance_m')]:leadcols.append(f'lead({source},{lag}) OVER(PARTITION BY horse_id ORDER BY date) AS {name}{lag}')
    f=db.execute('SELECT row_key,'+','.join(leadcols)+' FROM d').df().set_index('row_key').loc[d.row_key]
    end=d.groupby('meet').date.max().min();ck(str(end.date())==audit['common_followup_end'],'common end');mature=d.date.le(end-pd.Timedelta(days=180));close(mature,d.mature180,'180day administrative maturity')
    future=[];unknown=np.zeros(len(d),bool)
    for lag in [1,2,3]:
        for name in ['key','date','rank','size','meet','distance_m']:
            a=f[name+str(lag)].reset_index(drop=True);b=d['future_'+name+str(lag)]
            if name=='date':ck(np.array_equal(a.to_numpy('datetime64[ns]').view('i8'),b.to_numpy('datetime64[ns]').view('i8')),'SQL future dates',len(d))
            elif name in ['key','meet']:ck(a.fillna('').astype(str).equals(b.fillna('').astype(str)),'SQL future identity',len(d))
            else:close(a,b,'SQL future fields')
        when=f['date'+str(lag)].reset_index(drop=True);rank=f['rank'+str(lag)].to_numpy();size=f['size'+str(lag)].to_numpy();within=when.notna()&when.le(d.date+pd.Timedelta(days=180))&when.le(end);normal=(rank>=1)&(rank<=size);answer=np.where(within&normal,rank<=3,np.nan);future.append(answer);close(within,d['future_within'+str(lag)],'future horizon actual slots');close(answer,d['future_top3_'+str(lag)],'future outcome');unknown|=within&~normal
    values=np.column_stack(future);anywin=np.any(values==1,axis=1);complete=np.isfinite(values).all(axis=1)&mature
    close(np.where(mature,values[:,0],np.nan),d.next_top3,'next target');close(np.where(complete,anywin,np.nan),d.three_top3,'three actual starts supported');close(np.where(mature,d.future_within1,np.nan),d.return180,'return rate');close(np.where(mature&(anywin|~unknown),anywin,np.nan),d.any180_top3,'180day cumulative max3 target');close(np.where(mature&d.future_within1,d.future_rank1.between(1,3),np.nan),d.next_abnormal_zero,'abnormalzero sensitivity')
    th=pd.read_csv(O/'prior_thresholds.csv',dtype={'segment':str})
    db.register('thresholds',th)
    for segment in ['600','400','200']:
        mapped=db.execute('SELECT d.row_key,CASE WHEN th.supported THEN th.q20 END q20,CASE WHEN th.supported THEN th.n ELSE 0 END n FROM d LEFT JOIN thresholds th ON th.evaluation_year=d.year AND th.segment=? AND th.meet=d.meet AND th.distance_m=d.distance_m AND th.grade_bucket=d.grade_bucket AND th.moisture_band=d.moisture_band',[segment]).df().set_index('row_key').loc[d.row_key];close(mapped.q20,d['prior_q20_'+segment],'prior threshold mapping');close(mapped.n,d['prior_n_'+segment],'prior support mapping');close(np.where(d['time'+segment].notna()&mapped.q20.notna().to_numpy(),d['time'+segment].to_numpy()<=mapped.q20.to_numpy()+1e-9,np.nan),d['prior_fast20_'+segment],'prior good flag')
    for (year,segment),g in th.groupby(['evaluation_year','segment']):
        stats=db.execute(f'SELECT meet,distance_m,grade_bucket,moisture_band,count(time{segment}) n,count(DISTINCT source_key) races,quantile_cont(time{segment},0.2) q20 FROM d WHERE year BETWEEN ? AND ? AND time{segment} IS NOT NULL GROUP BY ALL',[int(year)-3,int(year)-1]).df().set_index(['meet','distance_m','grade_bucket','moisture_band']);saved=g.set_index(['meet','distance_m','grade_bucket','moisture_band']);ck(set(saved.index)==set(stats.index),'prior cells');close(stats.loc[saved.index,['n','races','q20']],saved[['n','races','q20']],'SQL prior reference statistics');ck((g.reference_last_year<g.evaluation_year).all(),'past-only years')
    for r in pd.read_csv(O/'cohort_metrics.csv',dtype={'segment':str}).itertuples():
        g,col=sample(d,r);g=g[g[col].eq(int(r.fast))];db.register('sample',g);vals=db.execute('SELECT count(*),count(DISTINCT source_key),count(DISTINCT horse_id),count(DISTINCT date),'+','.join(f'count({c}),avg({c}),sum({c})' for c in TARGETS)+' FROM sample').fetchone();close(vals,[r.n,r.races,r.horses,r.dates]+[v for c in TARGETS for v in [getattr(r,c+'_n'),getattr(r,c+'_mean'),getattr(r,c+'_events')]],'SQL summaries')
    table=pd.read_csv(O/'comparisons.csv',dtype={'segment':str});details=pd.read_csv(O/'same_horse_cells.csv',dtype={'segment':str})
    for r in table.itertuples():
        g,col=sample(d,r);verify_contrast(db,g,col,r,details)
    for _,g in table.dropna(subset=['bh_family']).groupby('bh_family'):close(bh(g.p),g.bh_q,'BH family')
    sens=pd.read_csv(O/'cutoff_sensitivity.csv',dtype={'segment':str,'cutoff':str})
    for r in sens.itertuples():
        row=r._asdict();row.update(definition='race_fast'+r.cutoff,target='next_top3');rr=type('Row',(),row)();g,col=sample(d,rr);verify_contrast(db,g,col,rr)
    shared={'thoroughbred/research/'+s for s in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
    for a in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']:
        if a['path'] in shared:continue
        p=ROOT/a['path'];ck(p.stat().st_size==a['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==a['sha256'],'previous research preserved');preserved+=1
    result=dict(passed=True,checks=checks,raw_section_rows=raw_n,SQL_future_slot_rows=len(d),contrast_rows=len(table),cutoff_sensitivity_rows=len(sens),previous_files_preserved=preserved,future_skipped_invalid_slots=False,Seoul400_generated=False,regression_method='independent full absorbed design versus sequential residualization',predictive_models_trained=0)
    dump=json.dumps(result,ensure_ascii=False,indent=2)+'\n';(O/'verification.json').write_text(dump);print(dump,flush=True)
if __name__=='__main__':main()

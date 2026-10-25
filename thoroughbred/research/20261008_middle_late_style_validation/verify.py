"""Raw positions, SQL slot histories, independent summaries and clustered contrasts."""
from pathlib import Path
import gzip,hashlib,json,math
import numpy as np,pandas as pd,duckdb
from scipy.stats import t
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';checks=0
TARGETS=['p_s1f','p_g3f','p_g1f','finish_p','gain_middle','gain_400','gain_200','gain_late','middle_surge','late_surge','last200_surge','recovery','recovery_when_back600','late_any','last200_any','top3','top5','fade','late_cond_adv','last600_adv','late_cond_fast','recovery_and_fast200','fast200_given_recovery','recovery_and_top3','nonfinish']
def check(x,label,n=1):
    global checks
    assert bool(x),label;checks+=n
def close(a,b,label):
    a=np.asarray(a,float);b=np.asarray(b,float);check(a.shape==b.shape and np.allclose(a,b,atol=1e-10,rtol=1e-9,equal_nan=True),label,a.size)
def scored(g,score,mean):
    variances=[];numbers=[]
    for ids in [g.horse_id.tolist(),g.date.tolist(),list(zip(g.horse_id,g.date))]:
        sums={}
        for key,v in zip(ids,score):sums[key]=sums.get(key,0)+v
        n=len(sums);numbers.append(n);variances.append(sum(v*v for v in sums.values())*n/(n-1) if n>1 else np.nan)
    if min(numbers[:2])<2:return [mean,np.nan,np.nan,np.nan,np.nan,np.nan]
    se=math.sqrt(max(0,variances[0],variances[1],variances[0]+variances[1]-variances[2]));df=min(numbers[:2])-1;c=t.ppf(.975,df);p=2*t.sf(abs(mean/se),df) if se else float(mean==0)
    return [mean,se,mean-c*se,mean+c*se,p,df]
def ci(g,col):
    z=g[g[col].notna()];v=z[col].to_numpy();return scored(z,(v-v.mean())/len(v),v.mean()) if len(z) else [np.nan]*6
def bh(p):
    p=np.asarray(p);idx=np.argsort(p);ordered=np.minimum.accumulate((p[idx]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];out=np.empty(len(p));out[idx]=np.minimum(1,ordered);return out
def window(d,w):
    return d[d.year.between(2024,2025)] if w=='2024_2025' else d[d.year.eq(2026)] if w=='2026_partial' else d[d.year.le(2023)] if w=='2018_2023' else d
def select(d,w,scope,label):
    g=window(d,w)
    if scope=='meet':g=g[g.meet.eq(label)]
    elif scope=='meet_distance':
        meet,dist=label.split('|');g=g[g.meet.eq(meet)&g.distance_m.eq(int(dist))]
    return g
def cohort(g,code):
    cols={'past_lead':'lead_profile','past_fore_strict':'fore_strict_profile','past_front':'front_profile','past_back':'back_profile','past_rear_strict':'rear_strict_profile','back_repeat':'closer_candidate','back_low':'back_low_recovery','back_unknown':'back_unknown_recovery'}
    return g if code=='all' else g[g[cols[code]]]
def summaries(db,d,filename,flow=False):
    rows=pd.read_csv(O/filename)
    for r in rows.itertuples():
        g=cohort(select(d,r.window,r.scope,r.label),r.cohort)
        if flow:g=g[g['lead_realization' if r.cohort=='past_lead' else 'front_realization'].eq(r.status)]
        db.register('sample',g);out=db.execute('SELECT count(*),count(DISTINCT source_key),count(DISTINCT horse_id),count(DISTINCT date),'+','.join('count("'+c+'"),avg("'+c+'")' for c in TARGETS)+' FROM sample').fetchone();expected=[r.n,r.races,r.horses,r.dates]+[v for c in TARGETS for v in [getattr(r,c+'_n'),getattr(r,c+'_mean')]];close(out,expected,'SQL summary '+filename)
        for c in ['recovery','top3']:
            z=ci(g,c);close(z[2:4],[getattr(r,c+'_lower'),getattr(r,c+'_upper')],'independent summary CI')
        check(r.small_sample==(g.source_key.nunique()<30 or g.date.nunique()<10),'small sample')
    return len(rows)
def main():
    d=pd.read_parquet(O/'trajectory_rows.parquet');check(len(d)==159014 and d.row_key.is_unique,'full roster');check(d.source_key.nunique()==14636,'race count');audit=json.loads((O/'source_audit.json').read_text())
    for r in audit['inputs']:
        p=ROOT/r['path'];check(p.stat().st_size==r['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'],'input hash')
    rawchecks=0
    for filename,g in d.groupby('source_file'):
        p=(ROOT/filename).resolve();check(p.is_relative_to((ROOT/'thoroughbred/research').resolve()),'raw boundary');items=json.load(gzip.open(p,'rt'))['response']['body']['items']['item']
        for r in g.itertuples():
            z=items[r.source_item_index];check(str(z['hrNo']).zfill(7)==str(r.horse_id).zfill(7) and int(z['rcDate'])==int(r.date.strftime('%Y%m%d')) and int(z['rcNo'])==int(r.source_key.split(':')[2]),'raw identity');prefix='sj' if r.meet=='서울' else 'bu';close([z[prefix+'S1fOrd'],z[prefix+'G3fOrd'],z[prefix+'G1fOrd'],z['ord'],z['chulNo'],z['rcDist']],[r.s1f,r.g3f,r.g1f,r.raw_finish_rank,r.gate,r.distance_m],'raw ranks');rawchecks+=1
    print('verified raw official positions',rawchecks,flush=True)
    db=duckdb.connect();db.register('roster',d)
    for point in ['s1f','g3f','g1f']:
        q=db.execute(f'SELECT source_key,count(*)=max(field_size) AND count(DISTINCT {point})=max(field_size) AND min({point})=1 AND max({point})=max(field_size) ok FROM roster GROUP BY source_key').df().set_index('source_key');close(d.source_key.map(q.ok),d[point+'_complete'],'independent completeness');out=np.where(d[point+'_complete'],(d[point]-1)/(d.field_size-1),np.nan);close(out,d['p_'+point],'relative rank')
    normal=d.raw_finish_rank.between(1,d.field_size);close(normal,d.normal_outcome,'normal finish');close(np.where(normal,(d.raw_finish_rank-1)/(d.field_size-1),np.nan),d.finish_p,'finish relative');close(~normal,d.nonfinish,'abnormal missing finish marker')
    for name,a,b in [('middle','p_s1f','p_g3f'),('400','p_g3f','p_g1f'),('200','p_g1f','finish_p'),('late','p_g3f','finish_p')]:close(d[a]-d[b],d['gain_'+name],'phase gain')
    common=d[['p_s1f','p_g3f','p_g1f','finish_p']].notna().all(axis=1);close(common,d.path_complete,'common path mask');close(d.loc[common,['gain_middle','gain_400','gain_200']].sum(axis=1),d.loc[common,'p_s1f']-d.loc[common,'finish_p'],'telescoping gain')
    valid=d.g3f_complete&normal;recovery=np.where(valid,d.p_g3f.ge(.5)&d.gain_late.ge(.25),np.nan);close(recovery,d.recovery,'old recovery target');close(np.where(d.group_observed&normal,d.role4.le(1)&(d.finish_p-d.group_mean_relative).ge(.30),np.nan),d.fade,'old fade target')
    for name,col in [('middle_surge','gain_middle'),('late_surge','gain_late'),('last200_surge','gain_200')]:close(np.where(d[col].notna(),d[col]>=.25,np.nan),d[name],'surge event')
    close(np.where(d.gain_late.notna(),d.gain_late>1e-12,np.nan),d.late_any,'any late');close(np.where(d.gain_200.notna(),d.gain_200>1e-12,np.nan),d.last200_any,'any last200')
    for k in [3,5]:close(np.where(normal,d.raw_finish_rank.le(k),np.nan),d['top'+str(k)],'top finish')
    close(np.where(d.late_cond_adv.notna(),d.late_cond_adv>0,np.nan),d.late_cond_fast,'conditional fast');close(np.where(valid&d.late_cond_adv.notna(),d.recovery.eq(1)&d.late_cond_adv.gt(0),np.nan),d.recovery_and_fast200,'recovery with fast200');close(np.where(valid&d.p_g3f.ge(.5),d.recovery.eq(1),np.nan),d.recovery_when_back600,'recovery conditional opportunity');close(np.where(d.recovery.eq(1)&d.late_cond_adv.notna(),d.late_cond_adv.gt(0),np.nan),d.fast200_given_recovery,'fast given recovery');close(np.where(valid,d.recovery.eq(1)&d.top3.eq(1),np.nan),d.recovery_and_top3,'recovery plus top3')
    # Independent SQL LAG for actual slots, including invalid observations.
    cols=['recovery','gain_middle','gain_late','gain_200','recovery_and_fast200'];lagcols=[]
    for lag in range(1,6):
        for col in cols+['role4','date']:lagcols.append(f'lag("{col}",{lag}) OVER(PARTITION BY horse_id ORDER BY date) "{col}_{lag}"')
    db.execute('CREATE TEMP TABLE lagged AS SELECT row_key,date,'+','.join(lagcols)+' FROM roster')
    fresh=lambda lag:f'date_diff(\'day\',date_{lag},date) BETWEEN 2 AND 730'
    expressions=['row_key']
    for col in cols:
        count='+'.join(f'CASE WHEN {fresh(lag)} AND {col}_{lag} IS NOT NULL THEN 1 ELSE 0 END' for lag in range(1,6));sums='+'.join(f'CASE WHEN {fresh(lag)} AND {col}_{lag} IS NOT NULL THEN {col}_{lag} ELSE 0 END' for lag in range(1,6));expressions +=[f'({count}) "{col}_n"',f'({sums})/nullif(({count}),0) "{col}_mean"']
    for j in range(4):expressions.append('('+ '+'.join(f'CASE WHEN {fresh(lag)} AND role4_{lag}={j} THEN 1 ELSE 0 END' for lag in range(1,6))+f') role_count_{j}')
    q=db.execute('SELECT '+','.join(expressions)+' FROM lagged').df().set_index('row_key').loc[d.row_key]
    for col in cols:close(q[col+'_n'],d['past_'+col+'_n5'],'SQL slot counts');close(q[col+'_mean'],d['past_'+col+'_mean5'],'SQL slot means')
    for j in range(4):close(q['role_count_'+str(j)],d['count5_'+str(j)],'SQL prior style counts')
    supported=q[[f'role_count_{j}' for j in range(4)]].sum(axis=1).eq(5).to_numpy();close(supported,d.supported5,'five real valid slots');close(d.past_recovery_count5,d.past_recovery_mean5.fillna(0)*d.past_recovery_n5,'recovery count');check((d.history_last.isna()|(d.history_last<=d.date-pd.Timedelta(days=2))).all(),'T minus two')
    for target,mask in [('lead_profile',supported&d.count5_0.ge(3)),('fore_strict_profile',supported&d.count5_1.ge(3)),('front_profile',supported&(d.count5_0+d.count5_1).ge(3)&d.count5_0.lt(3)),('back_profile',supported&(d.count5_2+d.count5_3).ge(3)),('rear_strict_profile',supported&d.count5_3.ge(3)),('closer_candidate',d.back_profile&d.past_recovery_n5.eq(5)&d.past_recovery_count5.ge(2)),('back_low_recovery',d.back_profile&d.past_recovery_n5.eq(5)&d.past_recovery_count5.lt(2)),('back_unknown_recovery',d.back_profile&d.past_recovery_n5.ne(5))]:close(mask,d[target],'cohort '+target)
    check((d.closer_candidate.astype(int)+d.back_low_recovery.astype(int)+d.back_unknown_recovery.astype(int)).eq(d.back_profile.astype(int)).all(),'back partition');check((d.lead_profile.astype(int)+d.front_profile.astype(int)+d.back_profile.astype(int)).eq(d.supported5.astype(int)).all(),'supported coarse partition')
    check(d.lead_realization.equals(pd.Series(np.select([d.role4.eq(0),d.role4.eq(1),d.role4.ge(2)],['선행유지','선입이동','중단후미밀림'],default='초반미관측'))),'lead realization');check(d.front_realization.equals(pd.Series(np.select([d.role4.between(0,1),d.role4.ge(2)],['앞선확보','중단후미밀림'],default='초반미관측'))),'front realization')
    counts=dict(cohort=summaries(db,d,'cohort_metrics.csv'),front_flow=summaries(db,d,'front_realization_metrics.csv',True));print('verified cohort and front-flow summaries',counts,flush=True)
    for r in pd.read_csv(O/'common_path_metrics.csv').itertuples():
        g=cohort(select(d,r.window,r.scope,r.label),r.cohort);g=g[g.path_complete];close([len(g)]+[g[c].mean() for c in ['p_s1f','p_g3f','p_g1f','finish_p','gain_middle','gain_400','gain_200']],[r.n,r.p_s1f_mean,r.p_g3f_mean,r.p_g1f_mean,r.finish_p_mean,r.gain_middle_mean,r.gain_400_mean,r.gain_200_mean],'common mean path')
    for r in pd.read_csv(O/'coverage.csv').itertuples():
        g=select(d,r.window,r.scope,r.label);close([len(g),g.source_key.nunique(),g.p_s1f.notna().sum(),g.p_g3f.notna().sum(),g.p_g1f.notna().sum(),g.finish_p.notna().sum(),g.supported5.sum(),g.past_recovery_n5.eq(5).sum()],[r.n,r.races,r.s1f_n,r.g3f_n,r.g1f_n,r.finish_n,r.supported5_n,r.past_recovery5_n],'coverage')
    for r in pd.read_csv(O/'recovery_threshold_sensitivity.csv').itertuples():
        g=window(d,r.window);g=g[g.back_profile&g.past_recovery_n5.eq(5)];g=g[g.past_recovery_count5.ge(r.threshold).eq(r.repeat_candidate)];close([len(g)]+[g[c].mean() for c in TARGETS],[r.n]+[getattr(r,c+'_mean') for c in TARGETS],'threshold sensitivity')
    rr=pd.read_csv(O/'closer_repetition_comparisons.csv')
    for r in rr.itertuples():
        g=select(d,r.window,r.scope,r.label);a=g[g.closer_candidate&g.recovery.notna()];b=g[g.back_low_recovery&g.recovery.notna()];ma=a.recovery.mean();mb=b.recovery.mean();score=np.r_[(a.recovery-ma)/len(a),-(b.recovery-mb)/len(b)];close(scored(pd.concat([a,b]),score,ma-mb),[r.estimate,r.se,r.lower,r.upper,r.p,r.df],'raw repetition contrast');close([len(a),len(b),ma,mb],[r.n_a,r.n_b,r.mean_a,r.mean_b],'raw repetition support')
    for _,g in rr.dropna(subset=['bh_family']).groupby(['window','bh_family']):close(bh(g.p),g.bh_q,'raw repetition BH')
    matched=pd.read_csv(O/'matched_comparisons.csv');cells=pd.read_csv(O/'matched_cells.csv');matched_cells=0
    for r in matched.itertuples():
        g=window(d,r.window);g=cohort(g,r.cohort).copy()
        if r.exposure=='repeat':g=g[g.closer_candidate|g.back_low_recovery].copy();g['repeat']=np.where(g.closer_candidate,'repeat','low')
        g=g[g[r.exposure].isin([r.a,r.b])&g[r.target].notna()].copy();keys=r.cell_columns.split('|');g['cell']=g[keys].astype(str).agg('|'.join,axis=1);db.register('matched_sample',g);st=db.execute(f'SELECT cell,"{r.exposure}" side,count(*) n,count(DISTINCT source_key) races,avg("{r.target}") mean FROM matched_sample GROUP BY cell,side').df().pivot(index='cell',columns='side',values=['n','races','mean']);minn,minr=(10,2) if r.exposure=='repeat' else (1,1);ok=st['n'].notna().all(axis=1)&st['n'].min(axis=1).ge(minn)&st['races'].min(axis=1).ge(minr);st=st[ok];check(len(st)==r.cells,'independent matched cells');w=st['n'][r.a]*st['n'][r.b]/(st['n'][r.a]+st['n'][r.b]);w/=w.sum();ma=float((w*st['mean'][r.a]).sum());mb=float((w*st['mean'][r.b]).sum());z=g[g.cell.isin(st.index)];score=[]
        for item in z.to_dict('records'):
            side=item[r.exposure];sgn=1 if side==r.a else -1;globalmean=ma if side==r.a else mb;score.append(sgn*w[item['cell']]/st['n'][side][item['cell']]*(item[r.target]-globalmean))
        close(scored(z,np.array(score),ma-mb),[r.estimate,r.se,r.lower,r.upper,r.p,r.df],'matched clustered contrast');close([z[r.exposure].eq(r.a).sum(),z[r.exposure].eq(r.b).sum(),len(z)/len(g),ma,mb],[r.n_a,r.n_b,r.coverage,r.mean_a,r.mean_b],'matched support and means')
        cs=cells[(cells.window==r.window)&(cells.comparison==r.comparison)&(cells.target==r.target)].set_index('cell');check(set(cs.index)==set(st.index),'matched cell identities')
        for side,suffix in [(r.a,'a'),(r.b,'b')]:close(st['n'][side].loc[cs.index],cs['n_'+suffix],'matched detail counts');close(st['mean'][side].loc[cs.index],cs['mean_'+suffix],'matched detail means')
        close(st['n'][r.a].loc[cs.index]*st['n'][r.b].loc[cs.index]/(st['n'][r.a].loc[cs.index]+st['n'][r.b].loc[cs.index]),cs.weight,'harmonic weights');matched_cells+=len(st)
    for _,g in matched.dropna(subset=['bh_family']).groupby(['window','bh_family']):close(bh(g.p),g.bh_q,'matched BH')
    for r in pd.read_csv(O/'position_transition_counts.csv').itertuples():
        g=cohort(select(d,'2024_2025',r.scope,r.label),r.cohort);a,b=r.stage.split('->');g=g[g[a].notna()&g[b].notna()];fa=np.where(g[a]<=1/3,0,np.where(g[a]<=2/3,1,2));ta=np.where(g[b]<=1/3,0,np.where(g[b]<=2/3,1,2));check(((fa==r.from_band)&(ta==r.to_band)).sum()==r.n,'transition count')
    ex=pd.read_csv(O/'fixed_example_trajectories.csv',dtype={'horse_id':str});check(len(ex)==21 and ex.source_key.nunique()==2,'fixed full examples');expect=d[d.source_key.isin(ex.source_key)].set_index('row_key').loc[ex.row_key];close(expect[['role4','p_s1f','p_g3f','p_g1f','finish_p','past_recovery_count5','past_recovery_n5','gain_middle','gain_400','gain_200']],ex[['role4','p_s1f','p_g3f','p_g1f','finish_p','past_recovery_count5','past_recovery_n5','gain_middle','gain_400','gain_200']],'all case trajectories')
    h=pd.read_csv(O/'horse_observed_summary.csv',dtype={'horse_id':str});main=window(d,'2024_2025')
    for r in h.itertuples():
        g=main[main.horse_id.eq(r.horse_id)&main.meet.eq(r.meet)];c=g[g.closer_candidate];lead=g[g.lead_profile];fore=g[g.front_profile];close([len(g),len(c),c.recovery.notna().sum(),c.recovery.eq(1).sum(),c.recovery.mean(),len(lead),lead.role4.ge(0).sum(),lead.role4.eq(0).sum(),lead.role4.eq(1).sum(),lead.role4.ge(2).sum(),len(fore),fore.role4.ge(2).sum()],[r.n,r.closer_candidate_n,r.closer_observed_n,r.closer_actual_recoveries,r.closer_recovery_rate,r.lead_profile_n,r.lead_observed_n,r.lead_kept,r.lead_fell_to_fore,r.lead_missed_front,r.front_profile_n,r.front_missed],'horse observed summaries')
    retained=d[['early','middle1','middle2','late','finish']].notna().all(axis=1);close(d.loc[retained,['early','middle1','middle2','late']].sum(axis=1),d.loc[retained,'finish'],'independent time segments sum');check(((d.distance_m-800)>0).all(),'middle stage physical length');shared={'thoroughbred/research/'+s for s in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
    for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']:
        if r['path'] in shared:continue
        p=ROOT/r['path'];check(p.stat().st_size==r['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'],'prior preserved');preserved+=1
    result=dict(passed=True,checks=checks,raw_official_position_rows=rawchecks,SQL_slot_rows=len(d),summary_rows=counts,matched_cells_recomputed=matched_cells,previous_files_preserved=preserved,models_trained=0,current_results_in_past_profiles=False,actual_intention_or_cause_identified=False)
    (O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()

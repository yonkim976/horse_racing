"""Independent SQL aggregations and dictionary cluster variance, raw-time audit."""
from pathlib import Path
import json,hashlib,gzip,importlib.util
import pandas as pd,numpy as np,duckdb
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs'
spec=importlib.util.spec_from_file_location('independent_prior_verify',R/'20261008_middle_late_style_validation/verify.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
checks=0
def ck(ok,label,n=1):
    global checks
    assert bool(ok),label;checks+=n
def close(a,b,label):
    a=np.asarray(a,float);b=np.asarray(b,float);ck(a.shape==b.shape and np.allclose(a,b,atol=1e-10,rtol=1e-9,equal_nan=True),label,a.size)
def main():
    d=pd.read_parquet(O/'analysis_rows.parquet');q=pd.read_parquet(O/'race_context.parquet');db=duckdb.connect();db.register('d',d)
    ck(len(d)==159014 and d.row_key.is_unique and len(q)==14636,'roster contracts')
    audit=json.loads((O/'source_audit.json').read_text())
    for r in audit['inputs']:
        p=ROOT/r['path'];ck(p.stat().st_size==r['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'],'input preserved')
    original=pd.read_parquet(R/'20261008_middle_late_style_validation/outputs/trajectory_rows.parquet').set_index('row_key').loc[d.row_key]
    for col in ['supported5','lead_profile','back_profile','closer_candidate','back_low_recovery','top3','top5','finish_p','recovery','gain_late','fade','nonfinish','p_s1f','p_g3f','p_g1f']:close(original[col],d[col],'unaltered prior '+col)
    raw_n=0
    for filename,g in original.groupby('source_file'):
        p=(ROOT/filename).resolve();ck(p.is_relative_to((R/'20260929_calendar_api_v1/raw/race_execution_probe').resolve()),'raw path boundary');items=json.load(gzip.open(p,'rt'))['response']['body']['items']['item']
        positions=d.set_index('row_key').loc[g.index]
        for r in positions.itertuples():
            source=original.loc[r.Index];z=items[int(source.source_item_index)];ck(str(z['hrNo']).zfill(7)==str(r.horse_id).zfill(7),'raw horse identity');close(z['seS1fAccTime' if r.meet=='서울' else 'buS1fTime'],r.s1f_time,'raw S1F seconds');raw_n+=1
    # Whole-roster exposure totals and first pack count are derived independently.
    st=db.execute('SELECT source_key,count(*) n,sum(cast(lead_profile AS INT)) lead,sum(cast(supported5 AS INT)) support,sum(cast(role4=0 AS INT)) pack,bool_and(s1f_complete AND s1f_time>0 AND s1f_time IS NOT NULL) is_valid FROM d GROUP BY source_key').df().set_index('source_key').loc[q.source_key]
    close(st.n,q.field_size,'whole roster N');close(st.lead,q.past_lead_count,'whole roster candidates');close(st.support/q.field_size.to_numpy(),q.support_fraction,'history coverage')
    close(st.is_valid,q.pace_valid,'pace validity');close(np.where(st.pack>0,st.pack,np.nan),q.actual_pack_count,'actual first pack')
    early=db.execute('SELECT source_key,avg(s1f_time) early FROM (SELECT *,row_number() OVER(PARTITION BY source_key ORDER BY s1f_time) rn FROM d) WHERE rn<=3 GROUP BY source_key').df().set_index('source_key').loc[q.source_key]
    close(np.where(q.pace_valid,early.early,np.nan),q.pace_seconds,'fastest three full roster')
    close(d.past_lead_count-d.lead_profile,d.past_lead_other,'self excluded candidates');close(d.actual_pack_count-d.role4.eq(0),d.actual_front_other,'self excluded actual pack')
    thresholds=pd.read_csv(O/'pace_thresholds.csv');db.register('q',q)
    for r in thresholds.itertuples():
        sample=q[q.year.between(r.evaluation_year-3,r.evaluation_year-1)&q.meet.eq(r.meet)&q.distance_m.eq(r.distance_m)&q.grade_bucket.eq(r.grade_bucket)&q.pace_valid]
        db.register('reference',sample);out=db.execute('SELECT count(*),quantile_cont(pace_seconds,0.25),quantile_cont(pace_seconds,0.75) FROM reference').fetchone();close(out,[r.n,r.q25,r.q75],'SQL past-only quantiles');ck(r.supported==(r.n>=30) and r.reference_last_year<r.evaluation_year,'reference before evaluation')
    for r in q.itertuples():
        if r.pace_reference_n>=30:
            expected='unknown' if not r.pace_valid else 'fast' if r.pace_seconds<=r.pace_q25 else 'slow' if r.pace_seconds>=r.pace_q75 else 'middle';ck(expected==r.pace_band,'pace band')
        else:ck(r.pace_band=='unknown','unsupported reference')
    targets=['top3','top5','finish_p','recovery','gain_late','fade','nonfinish'];flags={'past_back':'back_profile','back_repeat':'closer_candidate','back_low':'back_low_recovery','past_lead':'lead_profile'}
    metrics=pd.read_csv(O/'cohort_metrics.csv')
    for r in metrics.itertuples():
        g=v.select(d,r.window,r.scope,r.label);g=g[g[flags[r.cohort]]&g[r.exposure].eq(r.status)];db.register('sample',g)
        result=db.execute('SELECT count(*),count(DISTINCT source_key),count(DISTINCT horse_id),count(DISTINCT date),'+','.join('count('+t+'),avg('+t+')' for t in targets)+' FROM sample').fetchone();close(result,[r.n,r.races,r.horses,r.dates]+[x for t in targets for x in [getattr(r,t+'_n'),getattr(r,t+'_mean')]],'SQL metric')
    results=pd.read_csv(O/'comparisons.csv');cellrows=pd.read_csv(O/'matched_cells.csv');matched_n=0
    race_results=pd.read_csv(O/'race_pace_comparisons.csv');race_cells=pd.read_csv(O/'race_pace_matched_cells.csv')
    for races,table,details in [(False,results,cellrows),(True,race_results,race_cells)]:
        for r in table.itertuples():
            g=v.window(q if races else d,r.window).copy()
            if not races:g=g[g[flags[r.cohort]]]
            method='conditions' if races else r.method
            if method=='supported80':g=g[g.support_fraction.ge(.8)]
            exposure='actual_other_band' if method=='leave_self_out' else r.exposure
            target='pace_seconds' if races else r.target
            g=g[g[exposure].isin([r.a,r.b])&g[target].notna()].copy()
            if method=='raw':
                a=g[g[exposure].eq(r.a)];b=g[g[exposure].eq(r.b)];ma=a[target].mean();mb=b[target].mean();z=pd.concat([a,b]);score=np.r_[(a[target]-ma)/len(a),-(b[target]-mb)/len(b)];close([len(a),len(b),ma,mb],[r.n_a,r.n_b,r.mean_a,r.mean_b],'raw support')
            else:
                keys=r.cell_columns.split('|');g['cell']=g[keys].astype(str).agg('|'.join,axis=1);db.register('matched_sample',g)
                stats=db.execute(f'SELECT cell,"{exposure}" side,count(*) n,count(DISTINCT source_key) races,avg("{target}") mean FROM matched_sample GROUP BY cell,side').df().pivot(index='cell',columns='side',values=['n','races','mean'])
                mn,mr=(3,3) if races else (1,1) if method=='same_horse' else (5,2)
                keep=stats['n'].notna().all(axis=1)&stats['n'].min(axis=1).ge(mn)&stats['races'].min(axis=1).ge(mr);stats=stats[keep];ck(len(stats)==r.cells,'matched cell count');w=stats['n'][r.a]*stats['n'][r.b]/(stats['n'][r.a]+stats['n'][r.b]);weights=w/w.sum();ma=float((weights*stats['mean'][r.a]).sum());mb=float((weights*stats['mean'][r.b]).sum());z=g[g.cell.isin(stats.index)];score=[]
                for item in z.to_dict('records'):
                    side=item[exposure];score.append((1 if side==r.a else -1)*weights[item['cell']]/stats['n'][side][item['cell']]*(item[target]-(ma if side==r.a else mb)))
                close([z[exposure].eq(r.a).sum(),z[exposure].eq(r.b).sum(),len(z)/len(g),ma,mb],[r.n_a,r.n_b,r.coverage,r.mean_a,r.mean_b],'matched means support')
                cs=details[(details.window==r.window)&(details.exposure==r.exposure)]
                if not races:cs=cs[(cs.cohort==r.cohort)&(cs.method==r.method)&(cs.target==r.target)]
                cs=cs.set_index('cell');ck(set(cs.index)==set(stats.index),'cell identities')
                close(w.loc[cs.index],cs.weight,'harmonic weights')
                for side,suffix in [(r.a,'a'),(r.b,'b')]:close(stats['n'][side].loc[cs.index],cs['n_'+suffix],'cell n');close(stats['mean'][side].loc[cs.index],cs['mean_'+suffix],'cell mean')
                matched_n+=len(cs)
            close(v.scored(z,np.asarray(score),ma-mb),[r.estimate,r.se,r.lower,r.upper,r.p,r.df],'independent cluster CI')
    for _,g in results.dropna(subset=['bh_family']).groupby('bh_family'):close(v.bh(g.p),g.bh_q,'independent BH')
    shared={'thoroughbred/research/'+s for s in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
    for r in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']:
        if r['path'] in shared:continue
        p=ROOT/r['path'];ck(p.stat().st_size==r['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'],'previous study preserved');preserved+=1
    out=dict(passed=True,checks=checks,raw_time_rows=raw_n,SQL_summary_rows=len(metrics),matched_cells_recomputed=matched_n,previous_files_preserved=preserved,pace_reference_uses_future=False,operating_model_changed=False,models_trained=0)
    (O/'verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()

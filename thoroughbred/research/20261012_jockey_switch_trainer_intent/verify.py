"""Independent raw identity, SQL chronology, annual ranking, aggregation and sparse model audit."""
from pathlib import Path
import gzip,json,hashlib,math
import numpy as np,pandas as pd,duckdb
from scipy import sparse,stats
from scipy.sparse.linalg import lsqr
from scipy.stats import false_discovery_control
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';checks=0
def eq(a,b,tol=1e-9):
    global checks
    a=np.asarray(a);b=np.asarray(b);assert a.shape==b.shape,(a.shape,b.shape)
    if a.dtype.kind in 'biufc' and b.dtype.kind in 'biufc':assert np.allclose(a,b,atol=tol,rtol=tol,equal_nan=True),np.nanmax(np.abs(a-b))
    else:assert np.array_equal(pd.Series(a.ravel()).fillna('MISSING').astype(str),pd.Series(b.ravel()).fillna('MISSING').astype(str))
    checks+=a.size
def audit():
    d=pd.read_parquet(O/'analysis_rows.parquet');d['date']=pd.to_datetime(d.date);raw=[]
    for file,g in d.groupby('source_file'):
        with gzip.open(ROOT/file,'rt') as f:items=json.load(f)['response']['body']['items']['item']
        for r in g.itertuples():
            a=items[int(r.source_item_index)]
            ids=[str(a[c]).strip() for c in ['hrNo','jkNo','trNo','owNo']];ids=[s if s.strip('0') and s not in ['None','nan',''] else '' for s in ids];ids[0]=ids[0].zfill(7)
            eq([r.horse_id,r.jockey_id,r.trainer_id,r.owner_id,r.jockey_name,r.trainer_name],ids+[a['jkName'],a['trName']])
            eq([r.raw_finish_rank,r.raw_time,r.weight,r.body_weight,r.distance_m,r.gate],[float(a['ord']),float(a['rcTime']),float(a['wgBudam']),float(str(a['wgHr']).split('(')[0]),float(a['rcDist']),float(a['chulNo'])])
            eq([r.date.strftime('%Y%m%d')],[str(a['rcDate'])]);raw.append((r.row_key,r.source_key,r.raw_finish_rank,r.raw_time))
    normal=d.raw_finish_rank.between(1,d.field_size);eq(d.normal_outcome,normal)
    eq(d.top3,np.where(normal,d.raw_finish_rank.le(3),np.nan));eq(d.finish_p,np.where(normal,(d.raw_finish_rank-1)/(d.field_size-1),np.nan))
    con=duckdb.connect();con.register('starts',d)
    q=con.sql('''SELECT row_key,lag(row_key) over w pkey,lag(date) over w pdate,
      lag(jockey_id) over w pjk,lag(trainer_id) over w ptr,lag(owner_id) over w pow,
      lag(top3) over w ptop,lag(finish_p) over w prank,lag(distance_m) over w pdist
      FROM starts WINDOW w AS (PARTITION BY horse_id ORDER BY date) ORDER BY row_key''').df()
    s=d.sort_values('row_key');eq(s.row_key,q.row_key)
    for col,name in [('row_key','pkey'),('jockey_id','pjk'),('trainer_id','ptr'),('owner_id','pow'),('top3','ptop'),('finish_p','prank'),('distance_m','pdist')]:eq(s['previous_'+col],q[name])
    eq(s.previous_date.fillna(pd.Timestamp('1900-01-01')).astype(str),pd.to_datetime(q.pdate).fillna(pd.Timestamp('1900-01-01')).astype(str))
    ranks=pd.read_csv(O/'annual_jockey_rankings.csv',dtype={'jockey_id':str});good=d[normal&d.jockey_id.ne('')];rankcheck=0
    for (yr,meet),g in good.groupby(['year','meet']):
        stats0=g.groupby('jockey_id').agg(n=('row_key','size'),events=('top3','sum'));venue=g.top3.mean();stats0['score']=(stats0.events+50*venue)/(stats0.n+50)
        eligible=stats0[stats0.n>=100].reset_index().sort_values(['score','jockey_id'],ascending=[False,True]);top=set(eligible.head(math.ceil(.2*len(eligible))).jockey_id)
        a=ranks[(ranks.reference_year==yr)&(ranks.meet==meet)].set_index('jockey_id').loc[stats0.index]
        eq(a.n,stats0.n);eq(a.events,stats0.events);eq(a.score,stats0.score);eq(a.top,np.array([x in top for x in stats0.index]));eq(a.eligible,stats0.n.ge(100));rankcheck+=len(a)
    lookup=ranks.set_index(['evaluation_year','meet','jockey_id'])
    for current,col in [('current','jockey_id'),('previous','previous_jockey_id')]:
        keys=pd.MultiIndex.from_arrays([d.year,d.meet,d[col]]);expected=lookup.reindex(keys)
        eq(d[current+'_top'].fillna(False).astype(bool),expected.top.fillna(False).astype(bool));eq(d[current+'_eligible'].fillna(False).astype(bool),expected.eligible.fillna(False).astype(bool))
        eq(d[current+'_score'],expected.score)
    pref=pd.read_csv(O/'annual_trainer_preference.csv',dtype={'trainer_id':str,'jockey_id':str})
    for row in pref.itertuples():
        z=d[(d.year==row.reference_year)&d.meet.eq(row.meet)&d.trainer_id.eq(row.trainer_id)];c=z.jockey_id.value_counts().rename_axis('jid').reset_index(name='n').sort_values(['n','jid'],ascending=[False,True]).iloc[0]
        eq([row.jockey_id],[c.jid]);eq([row.pair_n,row.trainer_n,row.share],[c.n,len(z),c.n/len(z)]);eq([row.supported],[len(z)>=50 and c.n>=20 and c.n/len(z)>=.15])
    supported=d.current_eligible.eq(True)&d.previous_eligible.eq(True);known=d.previous_jockey_id.notna()&d.previous_jockey_id.ne('')&d.jockey_id.ne('')
    main=normal&supported&known&d.gap_days.between(2,180)&d.trainer_id.eq(d.previous_trainer_id)&d.trainer_id.ne('')&d.meet.eq(d.previous_meet)
    eq(d.main_eligible,main);eq(d.changed,known&d.jockey_id.ne(d.previous_jockey_id))
    ct=d.current_top.eq(True);pt=d.previous_top.eq(True);same=d.jockey_id.eq(d.previous_jockey_id)
    cats=np.where(same,np.where(ct,'retained_top','retained_ordinary'),np.where(ct,np.where(pt,'top_to_top','ordinary_to_top'),np.where(pt,'top_to_ordinary','ordinary_to_ordinary')))
    cats=np.where(known&supported,cats,'unclassified');eq(d.category,cats)
    raw=pd.DataFrame(raw,columns=['row_key','source_key','rank','time']);win=raw[raw['rank'].eq(1)&raw.time.gt(0)].groupby('source_key').time.min();eq(d.time_gap,d.quality_time-d.source_key.map(win))
    for file,kind in [('category_metrics.csv','category'),('destination_jockey_metrics.csv','jockey'),('trainer_jockey_pair_metrics.csv','pair'),('preferred_booking_metrics.csv','preferred')]:
        table=pd.read_csv(O/file,dtype={'jockey_id':str,'trainer_id':str})
        for row in table.itertuples():
            s=d[d.year.between(2024,2025)] if row.window=='2024_2025' else d[d.year.eq(2026)]
            if kind=='category' and row.category.startswith('all_'):
                s=s[s.normal_outcome&s.identity_supported&s.gap_days.between(2,180)&s.stable_trainer&s.same_venue];s=s[s.changed.eq(row.category=='all_changed')]
            else:s=s[s.main_eligible]
            if hasattr(row,'meet') and row.meet!='전체':s=s[s.meet.eq(row.meet)]
            if kind=='category' and not row.category.startswith('all_'):s=s[s.category.eq(row.category)]
            if kind in ['jockey','pair']:s=s[s.changed&s.jockey_id.eq(row.jockey_id)]
            if kind=='pair':s=s[s.trainer_id.eq(row.trainer_id)]
            if kind=='preferred':s=s[s.changed&s.preference_supported.eq(True)&s.to_preferred.eq(row.preferred)]
            paired=s[s.previous_top3.notna()];eq([row.n,row.horses,row.races,row.dates,row.top3_events],[len(s),s.horse_id.nunique(),s.source_key.nunique(),s.date.nunique(),s.top3.sum()])
            eq([row.top3_rate,row.previous_top3_rate,row.paired_current_top3_rate,row.paired_top3_change,row.rank_improvement_mean,row.time_gap_mean,row.same_condition_time_change],[s.top3.mean(),paired.previous_top3.mean(),paired.top3.mean(),(paired.top3-paired.previous_top3).mean(),s.rank_improvement.mean(),s.time_gap.mean(),s.raw_time_change_same.mean()])
    for file,groups in [('adjusted_associations.csv',['window','meet','model','target']),('destination_switch_associations.csv',['window','target']),('distance_time_associations.csv',['target']),('sensitivity.csv',['sensitivity','target']),('same_calendar_year_associations.csv',['year','target'])]:
        t=pd.read_csv(O/file)
        for _,g in t.groupby(groups):eq(g.q,false_discovery_control(g.p.to_numpy(),method='bh'))
    diag=pd.read_csv(O/'model_diagnostics.csv');assert diag.max_fe_mean.max()<1e-8 and diag.normal_equation_max.max()<1e-6
    # Independently solve full sparse race+horse model (LSQR, no normal equations or analysis import).
    effects=pd.read_csv(O/'adjusted_associations.csv');reg=[]
    for target in ['top3','finish_p','time_gap']:
        g=d[main&d.year.between(2024,2025)&d[target].notna()].copy();n=len(g)
        cats=['retained_top','ordinary_to_top','top_to_top','top_to_ordinary','ordinary_to_ordinary'];x=np.column_stack([g.category.eq(c).to_numpy(float) for c in cats]);c=[]
        for name in ['finish_p_mean5','finish_p_n5','previous_finish_p','previous_top3','gap_days','distance_change','grade_change','rating','age_current','weight','body_weight','gate_relative','previous_score']:
            v=g[name].to_numpy(float);bad=~np.isfinite(v);v=np.where(bad,0,v);c.append(bad.astype(float))
            if name=='gap_days':v=np.log1p(v)
            c.append(v)
            if name in ['rating','age_current','weight','body_weight','finish_p_mean5','previous_finish_p','gap_days','gate_relative']:c.append(v*v)
        c=np.column_stack(c);sd=c.std(axis=0);c=c[:,sd>1e-12]/sd[sd>1e-12];x=np.column_stack([x,c]);race=pd.factorize(g.source_key)[0];horse=pd.factorize(g.horse_id)[0];nr=race.max()+1;nh=horse.max()+1
        fe=sparse.coo_matrix((np.ones(2*n),(np.r_[np.arange(n),np.arange(n)],np.r_[race,horse+nr])),shape=(n,nr+nh)).tocsr();full=sparse.hstack([sparse.csr_matrix(x),fe]).tocsr()
        fit=lsqr(full,g[target].to_numpy(float),atol=1e-12,btol=1e-12,iter_lim=30000);coef=fit[0][:5]
        expected=effects[(effects.window=='2024_2025')&effects.meet.eq('전체')&effects.model.eq('race_horse_controls')&effects.target.eq(target)].set_index('term').loc[cats]
        eq(coef,expected.estimate,tol=2e-6)
        # Minimum norm influence solves full.T @ weights = e_upgrade independently.
        unit=np.zeros(full.shape[1]);unit[1]=1;weights=lsqr(full.T,unit,atol=1e-12,btol=1e-12,iter_lim=30000)[0]
        rowdiag=diag[(diag.window=='2024_2025')&diag.meet.eq('전체')&diag.model.eq('race_horse_controls')&diag.target.eq(target)].iloc[0]
        score=weights*(g[target].to_numpy(float)-full@fit[0])*np.sqrt(n/rowdiag.residual_df)
        variances=[];counts=[]
        for fields in [['horse_id'],['date'],['horse_id','date']]:
            tmp=g[fields].copy();tmp['score']=score;sums=tmp.groupby(fields).score.sum();k=len(sums);counts.append(k);variances.append(float(np.sum(sums.to_numpy()**2))*k/(k-1))
        se=np.sqrt(max(variances[0],variances[1],variances[0]+variances[1]-variances[2],0));crit=stats.t.ppf(.975,min(counts[:2])-1)
        row=expected.loc['ordinary_to_top'];eq([se,coef[1]-crit*se,coef[1]+crit*se],[row.se,row.ci_low,row.ci_high],tol=2e-6)
        contrasts=effects[(effects.window=='2024_2025')&effects.meet.eq('전체')&effects.model.eq('race_horse_controls')&effects.target.eq(target)].set_index('term')
        eq([coef[1]-coef[0],coef[1]-coef[4]],contrasts.loc[['upgrade_vs_retained_top','upgrade_vs_ordinary_switch'],'estimate'],tol=2e-6)
        reg.append(dict(target=target,iterations=int(fit[2]),stop_code=int(fit[1]),max_coefficient_error=float(np.max(np.abs(coef-expected.estimate.to_numpy()))),independent_upgrade_ci_error=float(abs(se-row.se))))
    for r in json.loads((O/'source_audit.json').read_text())['inputs']:eq([hashlib.sha256((ROOT/r['path']).read_bytes()).hexdigest()],[r['sha256']])
    result=dict(passed=True,checks=checks,raw_rows=len(d),sql_actual_previous_slots=len(d),prior_year_jockey_rows=rankcheck,trainer_preference_rows=len(pref),independent_sparse_full_model=reg,all_reported_tables_reaggregated=True,source_hashes_unchanged=True)
    (O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':audit()

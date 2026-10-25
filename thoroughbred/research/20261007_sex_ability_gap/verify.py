"""Independent raw-source, SQL aggregation, sparse dummy regression and score checks."""
from pathlib import Path
import gzip
import hashlib
import json
import numpy as np
import pandas as pd
import duckdb
from scipy import sparse
from scipy.sparse.linalg import lsmr
from scipy.stats import t

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
CORE=['early','middle1','middle2','late']
LOAD=['weight','body_weight','weight_squared','body_squared']
FORM=['rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap']


def main():
    audit=json.loads((OUT/'source_audit.json').read_text())
    for name,expected in audit['inputs'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected,name
    d=pd.read_parquet(OUT/'population.parquet')
    original=pd.read_parquet(HERE.parent/'20261007_seasonal_same_moisture/outputs/population.parquet')
    pd.testing.assert_frame_equal(d[original.columns].set_index('row_key').sort_index(),original.set_index('row_key').sort_index())
    assert len(d)==151074 and d.source_key.nunique()==13928
    assert not d.row_key.duplicated().any() and not d.duplicated(['source_key','horse_id']).any()
    assert d.groupby('source_key')[['date','distance_m','meet','grade','moisture','sex_condition']].nunique().eq(1).all().all()
    assert set(d.sex)=={'암','수','거'} and d.horse_id.str.fullmatch(r'\d{7}').all()
    np.testing.assert_allclose(d[CORE].sum(axis=1),d.finish,atol=1e-10)
    np.testing.assert_allclose(d.middle2+d.late,d.last600,atol=1e-10)
    assert d.loc[d.meet.eq('서울'),'last400'].isna().all()
    assert (d.last_history_date.isna() | d.last_history_date.lt(d.date)).all()
    bands=pd.cut(d.moisture,[0,5,9,14,19,np.inf],labels=['건조','양호','다습','포화','불량']).astype(str)
    assert bands.eq(d.band).all()
    raw_n=0
    for filename,g in d.groupby('source_file'):
        with gzip.open(ROOT/filename,'rt',encoding='utf-8') as stream:
            items=json.load(stream)['response']['body']['items']['item']
        for r in g.itertuples():
            x=items[int(r.source_item_index)]
            assert str(x['hrNo']).zfill(7)==r.horse_id and str(x['sex'])==r.sex
            assert str(x.get('sexCond',''))==r.sex_condition
            assert str(x['rcDate'])==r.date.strftime('%Y%m%d')
            assert int(x['ord'])==r.rank_raw
            assert float(str(x['wgHr']).split('(')[0])==r.body_weight
            assert np.isclose(float(x['rcTime']),r.finish)
            if r.meet=='서울':
                early=float(x['seS1fAccTime']); last600=r.finish-float(x['seG3fAccTime']); late=r.finish-float(x['seG1fAccTime'])
            else:
                early=float(x['buS1fTime']);last600=float(x['bu_3fGTime']);late=float(x['bu_1fGTime'])
                if np.isfinite(r.last400): assert np.isclose(float(x['bu_2fGTime']),r.last400)
            np.testing.assert_allclose([early,last600,late],[r.early,r.last600,r.late],atol=1e-10)
            raw_n+=1
    con=duckdb.connect()
    con.register('d',d)
    sql=con.execute('''select meet,distance_m,sex,count(*) as n,count(distinct source_key) as races,
        avg(finish) as mean,quantile_cont(finish,.2) as p20,quantile_cont(finish,.5) as median,quantile_cont(finish,.8) as p80
        from d group by all order by meet,distance_m,sex''').df()
    observed=pd.read_csv(OUT/'observed_distributions.csv')
    saved=observed[observed.scope.eq('distance') & observed.part.eq('finish')].sort_values(['meet','distance_m','sex']).reset_index(drop=True)
    np.testing.assert_allclose(sql[['n','races','mean','p20','median','p80']],saved[['n','races','mean','p20','median','p80']],atol=1e-10)
    score_checks=0
    for key,g in d.groupby(['meet','distance_m','grade','band']):
        recent=g[g.year.ge(2024)].finish.to_numpy()
        # Independent direct comparison at quantiles, with ties counted half.
        for r in g.iloc[np.unique(np.linspace(0,len(g)-1,min(5,len(g))).astype(int))].itertuples():
            if not len(recent): assert pd.isna(r.common_recent_score)
            else:
                score=100*(np.sum(recent>r.finish)+.5*np.sum(recent==r.finish))/len(recent)
                assert abs(score-r.common_recent_score)<1e-10
                score_checks+=1
    ledger=pd.read_parquet(OUT/'selection_ledger.parquet')
    assert set(ledger[ledger.selected].row_key)==set(d.row_key)
    sel=pd.read_csv(OUT/'selection_by_sex.csv')
    recalculated=ledger.groupby(['meet','distance_m','sex_raw','selection_reason']).size().rename('n').reset_index()
    pd.testing.assert_frame_equal(sel[recalculated.columns].sort_values(list(recalculated.columns[:-1])).reset_index(drop=True),
        recalculated.sort_values(list(recalculated.columns[:-1])).reset_index(drop=True),check_dtype=False)
    contrasts=pd.read_csv(OUT/'contrasts.csv')
    checks=[];matched_checks=0
    d['age_squared']=d.age**2
    for r in contrasts[contrasts.scope.eq('distance') & contrasts.part.eq('finish') & contrasts.specification.isin(['raw','context','grade']) & contrasts.estimable.fillna(False)].itertuples():
        g=d[d.meet.eq(r.meet)&d.distance_m.eq(r.distance_m)&d.sex.isin([r.target,r.reference])].copy()
        keys=[] if r.specification=='raw' else ['year','month','age','moisture']+(['grade'] if r.specification=='grade' else [])
        if keys:
            g=g[g.groupby(keys).sex.transform('nunique').eq(2)]
            wide=g.groupby(keys+['sex']).finish.agg(['mean','size']).unstack('sex')
            w=wide['size'][r.target]*wide['size'][r.reference]/(wide['size'][r.target]+wide['size'][r.reference])
            expected=np.average(wide['mean'][r.target]-wide['mean'][r.reference],weights=w)
        else:
            expected=g[g.sex.eq(r.target)].finish.mean()-g[g.sex.eq(r.reference)].finish.mean()
        assert len(g)==r.common_n
        assert abs(expected-r.difference)<1e-8,(r.meet,r.distance_m,r.specification,expected,r.difference)
        matched_checks+=1
    # Alternate sparse explicit FE + controls, no use of production demeaning or inverse.
    focal=contrasts[contrasts.part.eq('finish') & contrasts.estimable.fillna(False) & contrasts.distance_m.isin([1200,1400,1800]) &
        ((contrasts.scope.eq('distance')&contrasts.specification.isin(['load_body','full'])) |
         (contrasts.scope.eq('same_race')&contrasts.specification.eq('race_full')) |
         (contrasts.scope.eq('era')&contrasts.specification.eq('full')&contrasts.window.eq('jan_aug')&contrasts.contrast_kind.eq('gap_change')))]
    for r in focal.itertuples():
        g=d[d.meet.eq(r.meet)&d.distance_m.eq(r.distance_m)&d.sex.isin([r.target,r.reference])].copy()
        keys=['year','month','age','moisture','grade']
        if r.scope=='same_race':
            g=g[g.mixed_actual&g.complete_retained_race&~g.original_nonstandard];keys=['source_key']
        if r.scope=='era':
            g=g[g.month.le(8)]
            g['recent']=g.year.ge(2024).astype(float)
        g=g[g.groupby(keys).sex.transform('nunique').eq(2)]
        if r.scope=='era':
            cross=[x for x in keys if x!='year']
            g=g[g.groupby(cross).recent.transform('nunique').eq(2)]
            g=g[g.groupby(keys).sex.transform('nunique').eq(2)]
        assert len(g)==r.common_n
        gc=pd.factorize(pd.MultiIndex.from_frame(g[keys]))[0]
        dummy=sparse.csr_matrix((np.ones(len(g)),(np.arange(len(g)),gc)),shape=(len(g),gc.max()+1))
        names=LOAD+([] if r.specification=='load_body' else FORM)
        if r.scope=='same_race':names=['age','age_squared']+names
        nums=[]
        for name in names:
            x=g[name].to_numpy(float,copy=True);missing=np.isnan(x)
            if missing.all():continue
            x[missing]=np.median(x[~missing])
            if x.std()>1e-10:nums.append((x-x.mean())/x.std())
            if missing.any():nums.append(missing.astype(float))
        c=np.column_stack(nums) if nums else np.empty((len(g),0))
        sx=g.sex.eq(r.target).to_numpy(float)
        target=sx
        if r.scope=='era':
            e=g.recent.to_numpy(float)
            c=np.column_stack([sx,c*(1-e[:,None]),c*e[:,None]])
            target=sx*e
        nuisance=sparse.hstack([dummy,sparse.csr_matrix(c)],format='csr')
        fitted=lsmr(nuisance,target,atol=1e-12,btol=1e-12,maxiter=20000)
        assert fitted[1] in [1,2],fitted[1]
        sx_resid=target-nuisance@fitted[0]
        beta=float(sx_resid@g.finish.to_numpy()/(sx_resid@target))
        full=sparse.hstack([nuisance,sparse.csr_matrix(target[:,None])],format='csr')
        sol=lsmr(full,g.finish.to_numpy(),atol=1e-12,btol=1e-12,maxiter=20000)
        residual=g.finish.to_numpy()-full@sol[0]
        effect_error=abs(beta-r.difference)
        assert effect_error<3e-7,(r.scope,r.distance_m,effect_error)
        score=sx_resid*residual/(sx_resid@target)
        variance=[]
        for ids in [g.horse_id,g.day_key,g.horse_id+':'+g.day_key]:
            sums=pd.Series(score).groupby(ids.to_numpy()).sum()
            m=len(sums)
            variance.append(float((sums**2).sum()*m/(m-1)*(len(g)-1)/r.residual_df))
        se=np.sqrt(max(variance[0],variance[1],variance[0]+variance[1]-variance[2]))
        assert abs(se-r.se)<3e-7,(r.scope,r.distance_m,se,r.se)
        checks.append(dict(scope=r.scope,meet=r.meet,distance_m=r.distance_m,target=r.target,reference=r.reference,specification=r.specification,
            alternate_difference=beta,saved_difference=r.difference,error=effect_error,alternate_se=se,saved_se=r.se))
    pd.DataFrame(checks).to_csv(OUT/'independent_model_checks.csv',index=False)
    supported=contrasts[contrasts.supported.fillna(False)]
    critical=t.ppf(.975,np.minimum(supported.horse_clusters,supported.date_clusters)-1)
    np.testing.assert_allclose(supported.lower,supported.difference-critical*supported.se,atol=1e-9)
    np.testing.assert_allclose(supported.upper,supported.difference+critical*supported.se,atol=1e-9)
    assert contrasts.loc[~contrasts.supported.fillna(False),'lower'].isna().all()
    assert contrasts.loc[~contrasts.supported.fillna(False),'upper'].isna().all()
    # Independent interaction identity, not independent temporal validation.
    era=contrasts[contrasts.scope.eq('era')].pivot_table(index=['meet','distance_m','target','reference','specification','window'],columns='contrast_kind',values='difference')
    good=era.dropna()
    np.testing.assert_allclose(good.recent_gap-good.old_gap,good.gap_change,atol=1e-9)
    payload=dict(passed=True,inputs_unchanged=True,seasonal_population_exactly_reused=True,raw_rows_checked=raw_n,
        duplicate_runner_rows=0,raw_sex_identity_rank_body_section_mismatches=0,sql_distribution_rows=len(sql),
        direct_common_score_checks=score_checks,exact_weighted_difference_checks=matched_checks,
        independent_sparse_regression_and_cluster_se_checks=len(checks),
        max_sparse_coefficient_error=max(x['error'] for x in checks),all_reported_ci_recalculated=True,
        era_interaction_identity_checks=len(good),unsupported_ci_null=True,
        limitations='Arithmetic and source validation; observational inference remains conditional on overlap, model specification and selection. No future prediction validation.')
    (OUT/'verification.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(payload,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

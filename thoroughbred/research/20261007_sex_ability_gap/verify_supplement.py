"""Independent validation of expanded starter outcomes and moisture-panel estimates."""
from pathlib import Path
import json,gzip
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import lsmr
from scipy.stats import t

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
LOAD=['weight','body_weight','weight_squared','body_squared']
FORM=['rating','rating_squared','prior_finish','prior_top3','prior_early','log_starts','log_gap']


def main():
    d=pd.read_parquet(OUT/'population.parquet')
    d['age_squared']=d.age**2
    r=pd.read_parquet(OUT/'original_starter_outcomes.parquet')
    c=pd.read_csv(OUT/'supplement_contrasts.csv')
    assert not r.row_key.duplicated().any()
    assert set(d.row_key).issubset(set(r.row_key))
    assert set(r[r.retained].row_key)==set(d.row_key)
    raw_n=0
    for filename,g in r.groupby('source_file'):
        with gzip.open(ROOT/filename,'rt') as f:items=json.load(f)['response']['body']['items']['item']
        for x in g.itertuples():
            it=items[x.source_item_index]
            assert str(it['hrNo']).zfill(7)==x.horse_id and int(it['ord'])==x.rank_code and str(it['sex'])==x.sex
            if x.rank_code==0:assert pd.isna(x.top3) and pd.isna(x.win)
            else:assert x.top3==int(1<=int(it['ord'])<=3) and x.win==int(int(it['ord'])==1)
            raw_n+=1
    matched=0;numeric=[]
    for x in c[c.estimable.fillna(False)].itertuples():
        if x.scope=='moisture_panel':
            g=d[d.meet.eq(x.meet)&d.distance_m.eq(x.distance_m)&d.band.eq(x.subgroup)&d.sex.isin([x.target,x.reference])].copy()
            keys=['year','month','age','moisture','grade'];names=[] if x.specification=='grade' else LOAD+FORM
        else:
            g=r[r.meet.eq(x.meet)&r.distance_m.eq(x.distance_m)&r.sex.isin([x.target,x.reference])&r.top3.notna()&~r.sex_condition.eq('암')].copy()
            keys=['source_key'];names=[] if x.specification=='all_starters_race' else ['age','age_squared']+LOAD
        g=g[g.groupby(keys).sex.transform('nunique').eq(2)].copy()
        assert len(g)==x.common_n
        if not names:
            z=g.groupby(keys+['sex'])[x.part].agg(['mean','size']).unstack('sex')
            w=z['size'][x.target]*z['size'][x.reference]/(z['size'][x.target]+z['size'][x.reference])
            difference=np.average(z['mean'][x.target]-z['mean'][x.reference],weights=w)
            if x.part in ['win','top3']:difference*=100
            assert abs(difference-x.difference)<1e-8
            matched+=1
        elif x.distance_m in [1200,1400] and x.target=='암' and x.reference=='수' and (x.scope!='moisture_panel' or x.subgroup=='건조'):
            group=pd.factorize(pd.MultiIndex.from_frame(g[keys]))[0]
            dummy=sparse.csr_matrix((np.ones(len(g)),(np.arange(len(g)),group)),shape=(len(g),group.max()+1))
            nums=[]
            for name in names:
                v=g[name].to_numpy(float,copy=True);missing=np.isnan(v)
                if missing.all():continue
                v[missing]=np.median(v[~missing])
                if v.std()>1e-10:nums.append((v-v.mean())/v.std())
                if missing.any():nums.append(missing.astype(float))
            z=sparse.hstack([dummy,sparse.csr_matrix(np.column_stack(nums))],format='csr')
            sex=g.sex.eq(x.target).to_numpy(float)
            sol=lsmr(z,sex,atol=1e-12,btol=1e-12,maxiter=20000)
            sx=sex-z@sol[0]
            b=float(sx@g[x.part].to_numpy()/(sx@sex))
            full=sparse.hstack([z,sparse.csr_matrix(sex[:,None])],format='csr')
            fit=lsmr(full,g[x.part].to_numpy(),atol=1e-12,btol=1e-12,maxiter=20000)
            resid=g[x.part].to_numpy()-full@fit[0]
            influence=sx*resid/(sx@sex)
            vv=[]
            for ids in [g.horse_id,g.day_key,g.horse_id+':'+g.day_key]:
                scores=pd.Series(influence).groupby(ids.to_numpy()).sum();m=len(scores)
                vv.append(float((scores**2).sum()*m/(m-1)*(len(g)-1)/x.residual_df))
            se=np.sqrt(max(vv[0],vv[1],vv[0]+vv[1]-vv[2]))
            multiplier=100 if x.part in ['top3','win'] else 1
            assert abs(b*multiplier-x.difference)<1e-7
            assert abs(se*multiplier-x.se)<1e-7
            numeric.append(dict(scope=x.scope,meet=x.meet,distance_m=x.distance_m,part=x.part,difference_error=abs(b*multiplier-x.difference),se_error=abs(se*multiplier-x.se)))
    supported=c[c.supported.fillna(False)]
    critical=t.ppf(.975,np.minimum(supported.horse_clusters,supported.date_clusters)-1)
    np.testing.assert_allclose(supported.lower,supported.difference-critical*supported.se,atol=1e-9)
    np.testing.assert_allclose(supported.upper,supported.difference+critical*supported.se,atol=1e-9)
    assert c.loc[~c.supported.fillna(False),'lower'].isna().all()
    # Every independent core time coefficient sums to the whole-time coefficient on identical samples.
    primary=pd.read_csv(OUT/'contrasts.csv')
    keys=['scope','meet','distance_m','subgroup','window','specification','target','reference','contrast_kind']
    p=primary[primary.scope.eq('distance')&primary.part.isin(['early','middle1','middle2','late','finish'])].pivot(index=keys,columns='part',values='difference').dropna()
    np.testing.assert_allclose(p.early+p.middle1+p.middle2+p.late,p.finish,atol=1e-9)
    # Recheck tied-tail definitions for all distance distributions, including score direction.
    dist=pd.read_csv(OUT/'observed_distributions.csv')
    tail_checks=0
    for row in dist[dist.scope.eq('distance')].itertuples():
        g=d[d.meet.eq(row.meet)&d.distance_m.eq(row.distance_m)&d.sex.eq(row.sex)]
        vals=g[row.part].dropna();q=vals.quantile([.2,.8])
        higher_faster=row.part in ['common_recent_score','early_relative_pct','late_relative_pct']
        fast=vals[vals.ge(q.loc[.8])] if higher_faster else vals[vals.le(q.loc[.2])]
        slow=vals[vals.le(q.loc[.2])] if higher_faster else vals[vals.ge(q.loc[.8])]
        assert len(fast)==row.fast20_n and len(slow)==row.slow20_n
        assert abs(fast.mean()-row.fast20_mean)<1e-9 and abs(slow.mean()-row.slow20_mean)<1e-9
        fq=g.finish.quantile(.2)
        assert abs(g.loc[g.finish.le(fq),row.part].mean()-row.finish_fast20_part_mean)<1e-9
        tail_checks+=1
    (OUT/'supplement_verification.json').write_text(json.dumps(dict(passed=True,raw_original_starters_checked=raw_n,
        unknown_rank_rows_kept_null=int(r.top3.isna().sum()),exact_matching_estimates_checked=matched,
        sparse_regression_cluster_checks=len(numeric),core_coefficient_sum_checks=len(p),tied_tail_distribution_checks=tail_checks,
        reported_ci_recalculated=True,details=numeric),ensure_ascii=False,indent=2)+'\n')
    print('supplement verified',raw_n,matched,len(numeric),len(p),tail_checks)


if __name__=='__main__':main()

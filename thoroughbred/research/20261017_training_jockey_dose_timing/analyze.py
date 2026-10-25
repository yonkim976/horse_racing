"""Read-only follow-up: observed training rider count and last-ride timing."""

import importlib.util
import json
import math
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import linalg, sparse
from scipy.sparse.linalg import lsmr

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
PREVIOUS = HERE.parent / '20261017_training_jockey_performance'
spec = importlib.util.spec_from_file_location('jockey_presence', PREVIOUS / 'analyze.py')
parent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent)
helpers = parent.helpers
sha, dump = parent.sha, parent.dump
COUNT_LEVELS = ['0', '1', '2', '3_4', '5plus']
PERIODS = [('2018_2020', 2018, 2020), ('2024_2025', 2024, 2025), ('2026_partial', 2026, 2026)]
INDEPENDENT = []
UNIDENTIFIED = []


def count_bin(values):
    a = np.asarray(values)
    return np.select([a == 0, a == 1, a == 2, (a >= 3) & (a <= 4)], COUNT_LEVELS[:4], default='5plus')


def recency_bin(values):
    a = np.asarray(values, dtype=float)
    return np.select([~np.isfinite(a), a <= 2, a <= 4, a <= 7, a <= 14],
                     ['none', 'd1_2', 'd3_4', 'd5_7', 'd8_14'], default='d15_28')


def prepare():
    OUT.mkdir(exist_ok=True)
    prior_audit = json.loads((PREVIOUS / 'outputs/source_audit.json').read_text())
    assert sha(parent.DB) == prior_audit['inputs'][0]['sha256'], 'Training DB changed: audit before reusing the frozen study'
    d = pd.read_parquet(parent.STARTS)
    d['meet_code'] = d.meet.map({'서울': '1', '부산': '3'})
    assert d.meet_code.notna().all() and d.row_key.is_unique
    con = duckdb.connect(str(parent.DB), read_only=True)
    con.register('r', d[['row_key', 'horse_id', 'meet_code', 'date', 'jockey_id']])
    query = (PREVIOUS / 'outputs/feature_query.sql').read_text()
    anchor = 'min(t.event_date) AS first_training_date'
    assert query.count(anchor) == 1
    additional = """
        max(t.event_date) FILTER(WHERE t.rider_type_raw='기수') AS last_any_jockey_date,
        max(t.event_date) FILTER(WHERE t.rider_type_raw='기수' AND t.rider_official_id_linked=r.jockey_id
          AND r.jockey_id!='') AS last_race_jockey_date,
        count(t.observation_id) FILTER(WHERE t.rider_type_raw='기수' AND t.rider_official_id_linked IS NOT NULL
          AND t.rider_official_id_linked!=r.jockey_id) AS other_jockey_rows,
        count(DISTINCT t.event_date) FILTER(WHERE t.rider_type_raw='기수' AND t.rider_official_id_linked IS NOT NULL
          AND t.rider_official_id_linked!=r.jockey_id) AS other_jockey_days,
    """
    query = query.replace(anchor, additional + anchor)
    (OUT / 'feature_query.sql').write_text(query)
    f = con.execute(query).df()
    f['window_supported'] = f.supported_calendar_days.eq(f.window_days)
    f['any_jockey'] = f.jockey_rows.gt(0)
    f['race_jockey_confirmed'] = f.race_jockey_rows.gt(0)
    f['other_jockey_only_confirmed'] = f.any_jockey & ~f.race_jockey_confirmed
    f['classification'] = np.select([f.training_rows.eq(0), f.any_jockey, f.unknown_role_rows.gt(0)],
        ['no_training', 'jockey_confirmed', 'no_jockey_label_unknown_roles'], default='known_no_jockey')
    old = pd.read_parquet(PREVIOUS / 'outputs/training_window_features.parquet')
    pd.testing.assert_frame_equal(f[old.columns].sort_values(['row_key','window_days']).reset_index(drop=True),
        old.sort_values(['row_key','window_days']).reset_index(drop=True), check_dtype=False, atol=0, rtol=0)
    assert len(f) == len(d) * 2 and not f[['row_key','window_days']].duplicated().any()
    multiple = con.execute("""
      WITH t AS (
        SELECT t.* FROM daily_training_rider_linked t JOIN training_date_coverage c
        ON c.dataset=t.dataset AND c.event_date=t.event_date AND c.meet=t.meet
          AND c.selected_capture_id=t.capture_id
        WHERE t.event_date>=DATE '2017-12-01' AND t.meet IN ('1','3')
          AND c.coverage_status='complete_rows' AND NOT c.inventory_count_mismatch
      ), a AS (
        SELECT year(event_date) AS year,meet,official_horse_id,event_date,
          count(*) AS training_rows,count(*) FILTER(WHERE rider_type_raw='기수') AS jockey_rows
        FROM t GROUP BY ALL
      ) SELECT year,meet,count(*) AS horse_dates,sum(training_rows) AS training_rows,
        sum(jockey_rows) AS jockey_rows,count(*) FILTER(WHERE training_rows>1) AS multiple_training_dates,
        count(*) FILTER(WHERE jockey_rows>1) AS multiple_jockey_dates,
        max(jockey_rows) AS max_jockey_rows_per_date FROM a GROUP BY ALL ORDER BY 1,2
    """).df()
    multiple.to_csv(OUT / 'same_day_multiple_audit.csv', index=False)
    con.close()
    joined = d.merge(f, on='row_key', validate='one_to_many')
    for role, last_col, row_col, day_col in [
        ('any', 'last_any_jockey_date', 'jockey_rows', 'jockey_days'),
        ('race', 'last_race_jockey_date', 'race_jockey_rows', 'race_jockey_days')
    ]:
        joined[role+'_last_gap'] = (joined.date-joined[last_col]).dt.days
        positive = joined[row_col].gt(0)
        assert joined.loc[positive,role+'_last_gap'].between(1,joined.loc[positive,'window_days']).all()
        assert joined.loc[~positive,role+'_last_gap'].isna().all()
        assert joined[day_col].le(joined[row_col]).all()
        f = f.merge(joined[['row_key','window_days',role+'_last_gap']], on=['row_key','window_days'], validate='one_to_one')
    f.to_parquet(OUT / 'dose_timing_features.parquet', index=False)
    inputs = [parent.DB, parent.STARTS, PREVIOUS/'analyze.py', parent.HELPER,
              PREVIOUS/'outputs/feature_query.sql', PREVIOUS/'outputs/training_window_features.parquet']
    dump(OUT/'source_audit.json', dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha(p)) for p in inputs],
        starts=len(d), feature_rows=len(f), parent_shared_features_exactly_reproduced=True,
        start_date=str(d.date.min().date()),end_date=str(d.date.max().date()),
        end_by_venue={k:str(v.date()) for k,v in d.groupby('meet').date.max().items()},
        read_only=True,selected_complete_captures_only=True,race_day_excluded=True,
        recent_counts_are_observed_lower_bounds=True,recent_last_gap_is_last_observed_not_necessarily_last_actual=True,
        production_changed=False,prediction_gain_tested=False))
    return joined


def cohort(d, period, lo, hi, days, role, unit):
    base = d[d.year.between(lo,hi)&d.window_days.eq(days)&d.normal_outcome&d.window_supported&d.training_rows.gt(0)].copy()
    before = len(base)
    if period == '2018_2020':
        base = base[base.unknown_role_rows.eq(0)]
        if role == 'race':
            base = base[base.jockey_unlinked_rows.eq(0)]
    if role == 'race':
        base = base[base.jockey_id.fillna('').ne('')]
    col = ('jockey_' if role == 'any' else 'race_jockey_') + ('rows' if unit == 'rows' else 'days')
    base['dose'] = base[col].astype(int)
    base['dose_bin'] = count_bin(base.dose)
    base['last_gap'] = base[role+'_last_gap']
    base['last_bin'] = recency_bin(base.last_gap)
    base['other_dose_bin'] = count_bin(base['other_jockey_rows' if unit == 'rows' else 'other_jockey_days'])
    return base, before


def metrics(g):
    return dict(n=len(g),horses=g.horse_id.nunique(),races=g.source_key.nunique(),dates=g.date.nunique(),
        wins=int(g.win.sum()),win_rate=float(g.win.mean()),top3_events=int(g.top3.sum()),top3_rate=float(g.top3.mean()),
        finish_p=float(g.finish_p.mean()),time_n=int(g.time_gap.notna().sum()),time_gap=float(g.time_gap.mean()) if g.time_gap.notna().any() else None,
        prior5_finish_p=float(g.finish_p_mean5.mean()) if g.finish_p_mean5.notna().any() else None,
        training_days=float(g.training_days.mean()),dose_mean=float(g.dose.mean()),
        mean_last_gap=float(g.last_gap.mean()) if g.last_gap.notna().any() else None,
        unknown_role_share=float(g.unknown_role_rows.sum()/g.training_rows.sum()),
        small_bin=len(g)<100 or g.horse_id.nunique()<20 or g.date.nunique()<10)


def design(g, model):
    levels = COUNT_LEVELS[1:] if model == 'frequency' else COUNT_LEVELS[2:]
    data = {'count_'+k:g.dose_bin.eq(k).astype(float) for k in levels if g.dose_bin.eq(k).any()}
    contrasts = []
    if model == 'frequency':
        for k in levels:
            if 'count_'+k in data:contrasts.append(('count_'+k+'_vs_0', {'count_'+k:1}, 'count',k,'0'))
        for k in COUNT_LEVELS[2:]:
            if 'count_'+k in data and 'count_1' in data:
                contrasts.append(('count_'+k+'_vs_1', {'count_'+k:1,'count_1':-1},'count',k,'1'))
    else:
        for k in COUNT_LEVELS[2:]:
            if 'count_'+k in data:contrasts.append(('count_'+k+'_vs_1', {'count_'+k:1},'count',k,'1'))
        for k in ['d3_4','d5_7','d8_14','d15_28']:
            if g.last_bin.eq(k).any():
                data['last_'+k] = g.last_bin.eq(k).astype(float)
                contrasts.append(('last_'+k+'_vs_d1_2', {'last_'+k:1},'last',k,'d1_2'))
    return pd.DataFrame(data,index=g.index),contrasts


def fit(g, meta, volume, model):
    effects, diagnostics = [], []
    if model == 'joint_positive':g=g[g.dose.gt(0)].copy()
    if len(g)<500:
        diagnostics.append(dict(**meta,volume_controls=volume,model=model,fit_status='insufficient_total_n',n=len(g)))
        return effects,diagnostics
    for outcomes in [['win','top3','finish_p'],['time_gap']]:
        z=g[g[outcomes].notna().all(axis=1)].copy()
        exposure, contrasts=design(z,model)
        c=parent.nuisance(z,volume)
        if meta['rider']=='race':
            extras=pd.get_dummies(z.other_dose_bin,prefix='other_count',dtype=float).drop(columns=['other_count_0'],errors='ignore')
            c=pd.concat([c,extras],axis=1)
        rawx=np.column_stack([exposure.to_numpy(float),c.to_numpy(float)])
        rawy=z[outcomes].to_numpy(float)
        codes=[pd.factorize(z.horse_id)[0],pd.factorize(z.source_key)[0]]
        a,fe_rank=helpers.demean(np.column_stack([rawx,rawy]),codes)
        xx,y=a[:,:rawx.shape[1]],a[:,rawx.shape[1]:]
        gram=xx.T@xx; vals,vecs=linalg.eigh(gram)
        keep=vals>max(float(vals[-1])*1e-12,1e-12)
        inverse=(vecs[:,keep]/vals[keep])@vecs[:,keep].T
        beta=inverse@(xx.T@y);residual=y-xx@beta
        rank=int(keep.sum());df=len(z)-fe_rank-rank
        assert df>0
        projector=inverse@gram
        errors=[]; checks=[]
        for term,weights,kind,level,reference in contrasts:
            v=np.zeros(xx.shape[1])
            for name,value in weights.items():v[exposure.columns.get_loc(name)]=value
            error=float(np.max(np.abs(v@projector-v)))
            if error>=1e-6:
                UNIDENTIFIED.append(dict(**meta,volume_controls=volume,model=model,targets=','.join(outcomes),term=term,error=error))
                continue
            groups=[z[z['dose_bin' if kind=='count' else 'last_bin'].eq(k)] for k in [level,reference]]
            sufficient=all(len(s)>=100 and s.horse_id.nunique()>=20 and s.date.nunique()>=10 for s in groups)
            base=xx@(inverse@v)
            for j,target in enumerate(outcomes):
                estimate=float(v@beta[:,j]);ci=helpers.cluster_ci(z,base*residual[:,j]*math.sqrt(len(z)/df),estimate)
                effects.append(dict(**meta,volume_controls=volume,model=model,target=target,term=term,kind=kind,
                    level=level,reference=reference,n=len(z),level_n=len(groups[0]),reference_n=len(groups[1]),
                    bin_support_sufficient=sufficient,**ci))
            errors.append(error)
            checks.append((term,v))
        normal_error=float(np.max(np.abs(xx.T@residual)))
        assert normal_error<1e-5
        diagnostics.append(dict(**meta,volume_controls=volume,model=model,targets=','.join(outcomes),fit_status='fit',
            n=len(z),p=xx.shape[1],rank=rank,fe_rank=fe_rank,residual_df=df,
            normal_equation_max=normal_error,max_contrast_identification_error=max(errors,default=0),
            dose_changing_horses=int(z.groupby('horse_id').dose_bin.nunique().gt(1).sum()),
            recency_changing_horses=int(z.groupby('horse_id').last_bin.nunique().gt(1).sum())))
        if meta['period']=='2026_partial' and meta['window_days']==14 and meta['unit']=='rows' and meta['rider']=='race' and volume and model=='joint_positive' and outcomes[0]=='win':
            rows=np.arange(len(z));n1=codes[0].max()+1;n2=codes[1].max()+1
            fe=sparse.coo_matrix((np.ones(2*len(z)),(np.r_[rows,rows],np.r_[codes[0],codes[1]+n1])),shape=(len(z),n1+n2)).tocsr()
            full=sparse.hstack([sparse.csr_matrix(rawx),fe],format='csr')
            alt=lsmr(full,rawy[:,1],atol=1e-12,btol=1e-12,maxiter=20000)
            comparison={term:dict(primary=float(v@beta[:,1]),independent=float(v@alt[0][:len(v)]),
                                  absolute_error=float(abs(v@beta[:,1]-v@alt[0][:len(v)]))) for term,v in checks}
            assert max(x['absolute_error'] for x in comparison.values())<2e-6
            INDEPENDENT.append(dict(**meta,model=model,target='top3',stop=int(alt[1]),iterations=int(alt[2]),
                method='full sparse FE/dummy design LSMR',contrasts=comparison))
    return effects,diagnostics


def run(d):
    raw,grids,coverage,effects,diagnostics=[],[],[],[],[]
    for period,lo,hi in PERIODS:
        for days,unit,volumes in [(14,'rows',[True,False]),(28,'rows',[True]),(14,'days',[True])]:
            for rider in ['any','race']:
                support,before=cohort(d,period,lo,hi,days,rider,unit)
                coverage.append(dict(period=period,window_days=days,unit=unit,rider=rider,
                    eligible_before_role_identity_check=before,eligible_after=len(support),positive=int(support.dose.gt(0).sum()),
                    excluded=before-len(support)))
                for meet,g in support.groupby('meet'):
                    meta=dict(period=period,window_days=days,unit=unit,rider=rider,meet=meet)
                    for dimension,column in [('count','dose_bin'),('last','last_bin')]:
                        for level,s in g.groupby(column):raw.append(dict(**meta,dimension=dimension,level=level,**metrics(s)))
                    for (count,last),s in g.groupby(['dose_bin','last_bin']):
                        grids.append(dict(**meta,count=count,last=last,**metrics(s)))
                    for volume in volumes:
                        for model in ['frequency','joint_positive']:
                            print('FIT',meta,'volume',volume,model,'n',len(g),flush=True)
                            es,ds=fit(g,meta,volume,model);effects.extend(es);diagnostics.extend(ds)
    pd.DataFrame(raw).to_csv(OUT/'raw_performance.csv',index=False)
    pd.DataFrame(grids).to_csv(OUT/'raw_count_timing_grid.csv',index=False)
    pd.DataFrame(coverage).to_csv(OUT/'cohort_coverage.csv',index=False)
    e=helpers.bh(pd.DataFrame(effects),['period','window_days','unit','volume_controls'])
    e.to_csv(OUT/'adjusted_effects.csv',index=False)
    pd.DataFrame(diagnostics).to_csv(OUT/'model_diagnostics.csv',index=False)
    dump(OUT/'unidentified_contrasts.json',UNIDENTIFIED)
    return e


def verify(d,e):
    sample=d[d.normal_outcome&d.window_days.eq(14)].sample(64,random_state=20261018)
    con=duckdb.connect(str(parent.DB),read_only=True)
    for row in sample.itertuples():
        events=con.execute("""SELECT t.event_date,t.rider_type_raw,t.rider_official_id_linked
          FROM daily_training_rider_linked t JOIN training_date_coverage c
          ON c.dataset=t.dataset AND c.event_date=t.event_date AND c.meet=t.meet
          AND c.selected_capture_id=t.capture_id WHERE t.official_horse_id=? AND t.meet=?
          AND t.event_date>=?::DATE-INTERVAL 14 DAY AND t.event_date<?::DATE
          AND c.coverage_status='complete_rows' AND NOT c.inventory_count_mismatch""",
          [row.horse_id,row.meet_code,row.date,row.date]).fetchall()
        for role,expected_count,expected_days,gap in [('any',row.jockey_rows,row.jockey_days,row.any_last_gap),
            ('race',row.race_jockey_rows,row.race_jockey_days,row.race_last_gap)]:
            dates=[date for date,kind,ident in events if kind=='기수' and (role=='any' or ident==row.jockey_id and row.jockey_id!='')]
            assert len(dates)==expected_count and len(set(dates))==expected_days
            if dates:assert (row.date.date()-max(dates)).days==gap
            else:assert pd.isna(gap)
    con.close()
    raw=pd.read_csv(OUT/'raw_performance.csv',dtype={'level':str})
    for row in raw.itertuples():
        period,lo,hi=next(p for p in PERIODS if p[0]==row.period)
        z,_=cohort(d,period,lo,hi,row.window_days,row.rider,row.unit)
        z=z[z.meet.eq(row.meet)&z['dose_bin' if row.dimension=='count' else 'last_bin'].eq(row.level)]
        assert len(z)==row.n
        for target,col in [('win','win_rate'),('top3','top3_rate'),('finish_p','finish_p')]:
            assert abs(z[target].mean()-getattr(row,col))<1e-12
    audit=json.loads((OUT/'source_audit.json').read_text())
    for source in audit['inputs']:assert sha(ROOT/source['path'])==source['sha256']
    dump(OUT/'verification.json',dict(passed=True,independent_source_windows=len(sample),
        independently_recomputed_raw_groups=len(raw),parent_features_exactly_reproduced=True,
        no_future_or_race_day_training=True,unknown_role_counts_not_imputed_to_actual_zero=True,
        count_vs_unique_day_audited=True,last_gap_nan_for_no_confirmed_ride=True,
        independent_models=INDEPENDENT,adjusted_contrasts=len(e),unidentified_contrasts=len(UNIDENTIFIED),
        source_hashes_unchanged=True,production_changed=False,predictive_gain_tested=False))


if __name__=='__main__':
    begin=time.time();data=prepare();effects=run(data);verify(data,effects)
    print('COMPLETE seconds',round(time.time()-begin,1),flush=True)

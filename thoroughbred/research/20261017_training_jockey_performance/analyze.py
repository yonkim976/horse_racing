"""Read-only observational study of pre-race daily-training rider labels."""

from pathlib import Path
import hashlib
import importlib.util
import json
import math
import time

import duckdb
import numpy as np
import pandas as pd
from scipy import linalg, sparse
from scipy.sparse.linalg import lsmr

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
DB = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
STARTS = HERE.parent / '20261012_jockey_switch_trainer_intent/outputs/analysis_rows.parquet'
HELPER = HERE.parent / '20261012_jockey_switch_trainer_intent/analyze.py'
spec = importlib.util.spec_from_file_location('prior_study_helpers', HELPER)
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(p, x):
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def prepare():
    OUT.mkdir(exist_ok=True)
    d = pd.read_parquet(STARTS)
    assert d.row_key.is_unique
    d['meet_code'] = d.meet.map({'서울': '1', '부산': '3'})
    assert d.meet_code.notna().all()
    con = duckdb.connect(str(DB), read_only=True)
    con.register('r', d[['row_key', 'horse_id', 'meet_code', 'date', 'jockey_id']])
    query = """
    WITH t AS (
      SELECT t.* FROM daily_training_rider_linked t
      JOIN training_date_coverage c ON c.dataset=t.dataset AND c.event_date=t.event_date
        AND c.meet=t.meet AND c.selected_capture_id=t.capture_id
      WHERE t.meet IN ('1','3') AND t.event_date >= DATE '2017-12-01'
        AND c.coverage_status='complete_rows' AND NOT c.inventory_count_mismatch
    ), a AS (
      SELECT r.row_key, w.days AS window_days,
        count(t.observation_id) AS training_rows,
        count(DISTINCT t.event_date) AS training_days,
        count(t.observation_id) FILTER(WHERE t.rider_type_raw='기수') AS jockey_rows,
        count(DISTINCT t.event_date) FILTER(WHERE t.rider_type_raw='기수') AS jockey_days,
        count(t.observation_id) FILTER(WHERE coalesce(trim(t.rider_type_raw),'') IN ('','-')) AS unknown_role_rows,
        count(t.observation_id) FILTER(WHERE t.rider_type_raw='기수' AND t.rider_official_id_linked=r.jockey_id
          AND r.jockey_id!='') AS race_jockey_rows,
        count(DISTINCT t.event_date) FILTER(WHERE t.rider_type_raw='기수' AND t.rider_official_id_linked=r.jockey_id
          AND r.jockey_id!='') AS race_jockey_days,
        count(t.observation_id) FILTER(WHERE t.rider_type_raw='기수' AND t.rider_official_id_linked IS NULL) AS jockey_unlinked_rows,
        sum(try_cast(t.duration_seconds_raw AS DOUBLE)) AS duration_seconds,
        count(try_cast(t.duration_seconds_raw AS DOUBLE)) AS duration_observed_rows,
        sum(try_cast(t.canter_count_raw AS DOUBLE)) AS canter_count,
        sum(try_cast(t.gallop_count_raw AS DOUBLE)) AS gallop_count,
        min(t.event_date) AS first_training_date, max(t.event_date) AS last_training_date
      FROM r CROSS JOIN (VALUES (14),(28)) w(days)
      LEFT JOIN t ON t.official_horse_id=r.horse_id AND t.meet=r.meet_code
        AND t.event_date>=r.date-w.days*INTERVAL 1 DAY AND t.event_date<r.date
      GROUP BY r.row_key,w.days
    ), c AS (
      SELECT r.row_key,w.days AS window_days,
        count(c.event_date) FILTER(WHERE c.coverage_status IN ('complete_rows','complete_zero_rows')
          AND NOT c.inventory_count_mismatch) AS supported_calendar_days
      FROM r CROSS JOIN (VALUES (14),(28)) w(days)
      LEFT JOIN training_date_coverage c ON c.dataset='daily_training' AND c.meet=r.meet_code
        AND c.event_date>=r.date-w.days*INTERVAL 1 DAY AND c.event_date<r.date
      GROUP BY r.row_key,w.days
    ) SELECT * FROM a JOIN c USING(row_key,window_days)
    """
    (OUT / 'feature_query.sql').write_text(query)
    f = con.execute(query).df()
    assert len(f) == len(d) * 2
    f['window_supported'] = f.supported_calendar_days.eq(f.window_days)
    f['any_jockey'] = f.jockey_rows.gt(0)
    f['race_jockey_confirmed'] = f.race_jockey_rows.gt(0)
    f['other_jockey_only_confirmed'] = f.any_jockey & ~f.race_jockey_confirmed
    f['classification'] = np.select([
        f.training_rows.eq(0), f.any_jockey, f.unknown_role_rows.gt(0)
    ], ['no_training', 'jockey_confirmed', 'no_jockey_label_unknown_roles'],
        default='known_no_jockey')
    assert (f.race_jockey_rows <= f.jockey_rows).all()
    assert (f.jockey_rows + f.unknown_role_rows <= f.training_rows).all()
    assert f[['row_key', 'window_days']].duplicated().sum() == 0
    f.to_parquet(OUT / 'training_window_features.parquet', index=False)
    raw_audit = con.execute("""
      SELECT year(t.event_date) AS year,t.meet,t.rider_type_raw AS rider_role,
        count(*) AS n,count(DISTINCT t.observation_id) AS unique_observation_ids,
        count(*) FILTER(WHERE t.rider_official_id_linked IS NOT NULL) AS linked_official_ids
      FROM daily_training_rider_linked t JOIN training_date_coverage c
        ON c.dataset=t.dataset AND c.event_date=t.event_date AND c.meet=t.meet
        AND c.selected_capture_id=t.capture_id
      WHERE t.event_date>=DATE '2017-12-01' AND c.coverage_status='complete_rows'
        AND NOT c.inventory_count_mismatch GROUP BY ALL ORDER BY 1,2,3
    """).df()
    raw_audit.to_csv(OUT / 'source_role_audit.csv', index=False)
    assert raw_audit.n.eq(raw_audit.unique_observation_ids).all()
    coverage = con.execute("""SELECT dataset,meet,year(event_date) AS year,coverage_status,
      count(*) AS calendar_days,sum(inventory_count_mismatch::INT) AS mismatches
      FROM training_date_coverage WHERE dataset='daily_training' AND event_date>=DATE '2017-12-01'
      GROUP BY ALL ORDER BY 2,3,4""").df()
    coverage.to_csv(OUT / 'source_calendar_coverage.csv', index=False)
    con.close()
    joined = d.merge(f, on='row_key', validate='one_to_many')
    for col in ['first_training_date', 'last_training_date']:
        assert (joined[col].isna() | (joined[col] < joined.date)).all()
        assert (joined[col].isna() | (joined[col] >= joined.date-pd.to_timedelta(joined.window_days, unit='D'))).all()
    counts = joined.groupby(['meet', 'year', 'window_days', 'normal_outcome', 'window_supported', 'classification'], dropna=False).agg(
        n=('row_key','size'), horses=('horse_id','nunique'), race_jockey_confirmed=('race_jockey_confirmed','sum')
    ).reset_index()
    counts.to_csv(OUT / 'classification_coverage.csv', index=False)
    dump(OUT / 'source_audit.json', dict(
        inputs=[dict(path=str(p.relative_to(ROOT)), bytes=p.stat().st_size, sha256=sha(p)) for p in [DB, STARTS, HELPER]],
        starts=len(d), feature_rows=len(f), races=int(d.source_key.nunique()), horses=int(d.horse_id.nunique()),
        start_date=str(d.date.min().date()), end_date=str(d.date.max().date()),
        data_end_by_venue={k:str(v.date()) for k,v in d.groupby('meet').date.max().items()},
        training_source_read_only=True, raw_role_preserved=True,
        calendar_support_requires='complete_rows or complete_zero_rows, selected capture and no inventory count mismatch',
        historical_prerace_availability_certified=False, roles_unknown_are_not_non_jockey=True,
        future_training_used=False, race_day_training_used=False, production_changed=False,
    ))
    return joined


def nuisance(g, volume):
    z = {}
    fields = ['finish_p_mean5','finish_p_n5','previous_finish_p','previous_top3',
              'gap_days','distance_change','grade_change','rating','age_current',
              'weight','body_weight','gate_relative']
    if volume:
        fields += ['training_days','duration_seconds','canter_count','gallop_count']
    for field in fields:
        v = g[field].to_numpy(float)
        missing = ~np.isfinite(v)
        assert not np.any(v[np.isfinite(v)] < 0) if field in ['duration_seconds','canter_count','gallop_count'] else True
        if field in ['gap_days','duration_seconds','canter_count','gallop_count']:
            v = np.log1p(np.maximum(v, 0))
        v = np.where(missing, 0, v)
        z[field+'_missing'] = missing.astype(float)
        z[field] = v
        if field in ['finish_p_mean5','previous_finish_p','rating','age_current','weight','body_weight','gate_relative','gap_days']:
            z[field+'_sq'] = v*v
    a = pd.DataFrame(z, index=g.index)
    for field, values in [('jockey_year',g.jockey_id.astype(str)+':'+g.year.astype(str)), ('trainer',g.trainer_id.fillna(''))]:
        a = pd.concat([a, pd.get_dummies(values, prefix=field, drop_first=True, dtype=float)], axis=1)
    scale = a.std(ddof=0)
    a = a.loc[:,scale.gt(1e-12)] / scale[scale.gt(1e-12)]
    return a


INDEPENDENT = []


def fit(g, metadata, volume):
    results, diagnostics = [], []
    terms = ['any_jockey','race_jockey_confirmed','other_jockey_only_confirmed']
    # Identical outcome support is projected once. Missing time-gap values stay missing.
    for outcomes in [['win','top3','finish_p'], ['time_gap']]:
        z = g[g[outcomes].notna().all(axis=1)].copy()
        if len(z) < 500:
            continue
        c = nuisance(z, volume)
        raw_x = np.column_stack([z[terms].to_numpy(float), c.to_numpy(float)])
        raw_y = z[outcomes].to_numpy(float)
        codes = [pd.factorize(z.horse_id)[0], pd.factorize(z.source_key)[0]]
        a, fe_rank = helpers.demean(np.column_stack([raw_x,raw_y]), codes)
        nx = raw_x.shape[1]
        allx, y = a[:,:nx], a[:,nx:]
        for encoding, take, contrasts in [
            ('any', [0]+list(range(3,nx)), [('any_jockey_vs_reference', [1])]),
            ('split', [1,2]+list(range(3,nx)), [
                ('race_jockey_vs_reference',[1,0]), ('other_jockey_vs_reference',[0,1]),
                ('race_vs_other_jockey',[1,-1])])
        ]:
            xx = allx[:,take]
            # All nuisance columns were scaled before the FE projection.
            gram = xx.T@xx
            eigenvalues, eigenvectors = linalg.eigh(gram)
            good = eigenvalues > max(float(eigenvalues[-1])*1e-12, 1e-12)
            inverse = (eigenvectors[:,good]/eigenvalues[good])@eigenvectors[:,good].T
            beta = inverse@(xx.T@y)
            residual = y-xx@beta
            rank = int(good.sum())
            residual_df = len(z)-fe_rank-rank
            assert residual_df > 0
            projector = inverse@gram
            for name, weights in contrasts:
                v = np.zeros(xx.shape[1]); v[:len(weights)] = weights
                error = float(np.max(np.abs(v@projector-v)))
                assert error < 1e-6, (metadata, encoding, name, error)
                influence_base = xx@(inverse@v)
                for k, target in enumerate(outcomes):
                    estimate = float(v@beta[:,k])
                    ci = helpers.cluster_ci(z, influence_base*residual[:,k]*math.sqrt(len(z)/residual_df), estimate)
                    results.append(dict(**metadata,volume_controls=volume,encoding=encoding,target=target,term=name,
                                        n=len(z),horses=z.horse_id.nunique(),races=z.source_key.nunique(),**ci))
            normal_error = float(np.max(np.abs(xx.T@residual)))
            assert normal_error < 1e-5
            diagnostics.append(dict(**metadata,volume_controls=volume,encoding=encoding,targets=','.join(outcomes),
                n=len(z),p=xx.shape[1],rank=rank,fe_rank=fe_rank,residual_df=residual_df,
                normal_equation_max=normal_error,fe_projection='exact_sparse_connected_components',
                number_horses_with_exposure_change=int(z.groupby('horse_id').any_jockey.nunique().gt(1).sum())))
            # Two full-design sparse fits independently check FE absorption and contrast estimation.
            if metadata['period']=='2026_partial' and metadata['window_days']==14 and volume and encoding=='split' and outcomes[0]=='win':
                row = np.arange(len(z)); n1=codes[0].max()+1; n2=codes[1].max()+1
                fe = sparse.coo_matrix((np.ones(2*len(z)),(np.r_[row,row],np.r_[codes[0],codes[1]+n1])),shape=(len(z),n1+n2)).tocsr()
                fullx = sparse.hstack([sparse.csr_matrix(raw_x[:,take]),fe],format='csr')
                alt = lsmr(fullx,raw_y[:,1],atol=1e-12,btol=1e-12,maxiter=20000)
                checks = {}
                for name,weights in contrasts:
                    v=np.zeros(xx.shape[1]);v[:len(weights)]=weights
                    checks[name]=dict(primary=float(v@beta[:,1]),independent=float(v@alt[0][:len(v)]),
                                      absolute_error=float(abs(v@beta[:,1]-v@alt[0][:len(v)])))
                assert max(v['absolute_error'] for v in checks.values())<2e-6
                INDEPENDENT.append(dict(**metadata,method='full sparse design LSMR, no FE absorption',target='top3',
                                        stop=int(alt[1]),iterations=int(alt[2]),contrasts=checks))
    return results, diagnostics


def run(d):
    summaries, effects, diagnostics, volume_rows = [], [], [], []
    periods = [('2018_2020',2018,2020),('2024_2025',2024,2025),('2026_partial',2026,2026)]
    for period,lo,hi in periods:
        for days in [14,28]:
            support = d[d.year.between(lo,hi)&d.window_days.eq(days)&d.normal_outcome&d.window_supported&d.training_rows.gt(0)].copy()
            if period=='2018_2020':
                support=support[support.classification.isin(['jockey_confirmed','known_no_jockey'])]
            support['split_group']=np.select([support.race_jockey_confirmed,support.any_jockey],
                                             ['race_jockey_confirmed','other_jockey_only_confirmed'],default='reference')
            for meet,g in support.groupby('meet'):
                metadata=dict(period=period,window_days=days,meet=meet)
                for grouping in ['classification','split_group']:
                    for group,s in g.groupby(grouping):
                        summaries.append(dict(**metadata,grouping=grouping,group=group,n=len(s),horses=s.horse_id.nunique(),
                            races=s.source_key.nunique(),wins=int(s.win.sum()),win_rate=s.win.mean(),
                            top3_events=int(s.top3.sum()),top3_rate=s.top3.mean(),finish_p=s.finish_p.mean(),
                            time_n=int(s.time_gap.notna().sum()),time_gap=s.time_gap.mean(),
                            prior5_finish_p=s.finish_p_mean5.mean(),training_days=s.training_days.mean(),
                            duration_seconds=s.duration_seconds.mean(),jockey_days=s.jockey_days.mean(),
                            unknown_role_share=s.unknown_role_rows.sum()/s.training_rows.sum()))
                for any_jockey,s in g.groupby('any_jockey'):
                    volume_rows.append(dict(**metadata,any_jockey=bool(any_jockey),n=len(s),
                        training_days=s.training_days.mean(),duration_seconds=s.duration_seconds.mean(),
                        prior5_finish_p=s.finish_p_mean5.mean(),prior_top3=s.previous_top3.mean(),
                        win_rate=s.win.mean(),top3_rate=s.top3.mean(),finish_p=s.finish_p.mean(),time_gap=s.time_gap.mean()))
                for volume in ([True,False] if days==14 else [True]):
                    print('FIT',metadata,'volume',volume,'n',len(g),flush=True)
                    es,ds=fit(g,metadata,volume)
                    effects.extend(es);diagnostics.extend(ds)
    pd.DataFrame(summaries).to_csv(OUT/'raw_performance.csv',index=False)
    pd.DataFrame(volume_rows).to_csv(OUT/'binary_raw_performance.csv',index=False)
    e=helpers.bh(pd.DataFrame(effects),['period','window_days','volume_controls'])
    e.to_csv(OUT/'adjusted_effects.csv',index=False)
    pd.DataFrame(diagnostics).to_csv(OUT/'model_diagnostics.csv',index=False)
    return e


def verify(d,e):
    # Independent pandas aggregation of the final groups used by the report.
    check=pd.read_csv(OUT/'binary_raw_performance.csv')
    for row in check.itertuples():
        lo,hi=(2018,2020) if row.period=='2018_2020' else ((2024,2025) if row.period=='2024_2025' else (2026,2026))
        z=d[d.year.between(lo,hi)&d.window_days.eq(row.window_days)&d.meet.eq(row.meet)&d.normal_outcome&d.window_supported&d.training_rows.gt(0)]
        if row.period=='2018_2020':z=z[z.classification.isin(['jockey_confirmed','known_no_jockey'])]
        z=z[z.any_jockey.eq(row.any_jockey)]
        assert len(z)==row.n
        for target in ['win','top3','finish_p','time_gap']:
            col=target+'_rate' if target in ['win','top3'] else target
            assert abs(z[target].mean()-getattr(row,col))<1e-12
    # All selected source observations count once per horse/date, verify representative windows from source directly.
    sample=d[d.window_days.eq(14)&d.normal_outcome].sample(60,random_state=20261017)
    con=duckdb.connect(str(DB),read_only=True)
    for row in sample.itertuples():
        a=con.execute("""SELECT count(*),count(DISTINCT t.event_date),
          count(*) FILTER(WHERE t.rider_type_raw='기수'),
          count(*) FILTER(WHERE t.rider_type_raw='기수' AND t.rider_official_id_linked=? AND ?!='')
          FROM daily_training_rider_linked t JOIN training_date_coverage c
          ON c.dataset=t.dataset AND c.event_date=t.event_date AND c.meet=t.meet
          AND c.selected_capture_id=t.capture_id
          WHERE t.official_horse_id=? AND t.meet=? AND t.event_date>=?::DATE-INTERVAL 14 DAY
          AND t.event_date<?::DATE AND c.coverage_status='complete_rows' AND NOT c.inventory_count_mismatch""",
          [row.jockey_id,row.jockey_id,row.horse_id,row.meet_code,row.date,row.date]).fetchone()
        assert a==(row.training_rows,row.training_days,row.jockey_rows,row.race_jockey_rows), (row.row_key,a)
    con.close()
    audit=json.loads((OUT/'source_audit.json').read_text())
    for inp in audit['inputs']:assert sha(ROOT/inp['path'])==inp['sha256']
    dump(OUT/'verification.json',dict(passed=True,source_windows_independently_checked=len(sample),
        aggregated_groups_independently_checked=len(check),input_hashes_unchanged=True,
        no_training_unknown_roles_and_known_non_jockey_separated=True,
        future_and_race_day_events_excluded=True,full_calendar_coverage_enforced=True,
        date_and_horse_cluster_variance_maximum=True,
        adjusted_contrasts=len(e),independent_models=INDEPENDENT,
        production_changed=False,prediction_improvement_tested=False))


if __name__=='__main__':
    t=time.time(); data=prepare(); effect=run(data); verify(data,effect)
    print('COMPLETE seconds',round(time.time()-t,1),flush=True)

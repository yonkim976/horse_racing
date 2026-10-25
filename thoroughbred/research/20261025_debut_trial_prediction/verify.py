"""Independent source/window, numeric prediction, and probability-score checks."""

import json

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import expit,logit
from scipy.stats import rankdata

from prepare import DB,HERE,OUT,ROOT,dump,sha


def independent_encode(frame,schema):
    pieces=[]
    raw=np.array([[float(row[col]) if pd.notna(row[col]) else np.nan for col in schema['numeric']]
                  for _,row in frame.iterrows()],dtype=float)
    missing=~np.isfinite(raw)
    fixed=np.where(missing,np.array(schema['medians'])[None,:],raw)
    pieces.append((fixed-np.array(schema['medians']))/np.array(schema['scales']))
    pieces.append(missing.astype(float))
    for col in schema['categorical']:
        values=frame[col].fillna('미상').astype(str).to_numpy()
        pieces.append(np.array([[float(v==level) for level in schema['categories'][col]] for v in values]))
    return np.concatenate(pieces,axis=1)


def leaf(node,row):
    while 'split_index' in node:
        assert node['decision_type']=='<='
        node=node['left_child'] if row[node['split_feature']]<=node['threshold'] else node['right_child']
    return node['leaf_value']


def auc(y,p):
    y=np.asarray(y);r=rankdata(p,method='average');n1=y.sum();n0=len(y)-n1
    return float((r[y==1].sum()-n1*(n1+1)/2)/(n1*n0))


def main():
    d=pd.read_parquet(OUT/'debut_cohort.parquet');p=pd.read_parquet(OUT/'predictions.parquet')
    manifest=json.loads((OUT/'model_manifest.json').read_text());audit=json.loads((OUT/'source_audit.json').read_text())
    assert sha(DB)==audit['inputs'][0]['sha256']
    primary=d[d.primary_eligible].copy();assert primary.horse_id.is_unique
    assert primary.origin.eq('한국').all() and primary.prior_n5.eq(0).all()
    assert primary.selected_trial_date.le(primary.cutoff).all() and primary.trial_gap_days.between(2,365).all()
    con=duckdb.connect(str(DB),read_only=True)
    con.register('r',primary[['row_key','horse_id','date','cutoff']])
    prior=con.execute("""SELECT r.row_key,count(p.horse_id_raw) AS n FROM r LEFT JOIN confirmed_runners p
      ON lpad(p.horse_id_raw,7,'0')=r.horse_id AND p.result_date<strftime(r.date,'%Y%m%d')
      AND (try_cast(p.result_rank_raw AS INTEGER) BETWEEN 1 AND 89 OR p.result_rank_raw IN ('91','92'))
      GROUP BY r.row_key""").df()
    assert prior.n.eq(0).all()
    latest=con.execute("""SELECT r.row_key,t.participant_row_id,t.trial_date FROM r
      JOIN trial_participants_entity_reviewed t ON lpad(t.resolved_horse_id,7,'0')=r.horse_id
      AND cast(t.trial_date AS DATE)<=r.cutoff AND cast(t.trial_date AS DATE)>=r.date-INTERVAL 365 DAY
      WHERE t.api_passFlag='합격'
      QUALIFY row_number() OVER(PARTITION BY r.row_key ORDER BY cast(t.trial_date AS DATE) DESC,
        try_cast(t.trial_no AS INTEGER) DESC,t.participant_row_id DESC)=1""").df()
    z=primary.merge(latest,on='row_key',validate='one_to_one')
    assert len(z)==len(primary) and z.selected_trial_id.eq(z.participant_row_id).all()
    # Verify raw race and trial cells without using the preparation's numeric columns.
    sample=primary.sample(80,random_state=20261025)
    cache={};raw_checks=0
    import gzip
    for row in sample.itertuples():
        for path in [row.source_file,row.trial_source_file]:
            full=(ROOT/path).resolve();assert full.is_relative_to(ROOT)
            if path not in cache:
                opener=gzip.open if full.suffix=='.gz' else open
                with opener(full,'rt') as f:cache[path]=json.load(f)['response']['body']['items']['item']
        race=cache[row.source_file][int(row.source_item_index)]
        trial=cache[row.trial_source_file][int(row.trial_source_item_index)]
        assert str(race['hrNo']).zfill(7)==row.horse_id and int(race['ord'])==row.rank
        assert str(trial.get('hrNo',row.horse_id)).zfill(7)==row.horse_id
        for name,col in [('rcTime','finish'),('rcTimeS1f','early'),('rcTimeG1f','late')]:
            if pd.notna(getattr(row,col)):
                assert abs(float(trial[name])-getattr(row,col))<1e-12
                raw_checks+=1
    # Explicit scalar lookup of historical features on a fixed sample.
    f=pd.read_parquet(OUT/'field_history_audit.parquet').sample(40,random_state=20261025)
    for row in f.itertuples():
        history=con.execute("""SELECT result_date,try_cast(result_rank_raw AS INTEGER) AS rank FROM confirmed_runners
          WHERE lpad(horse_id_raw,7,'0')=? AND result_date<=strftime(?::DATE-INTERVAL 2 DAY,'%Y%m%d')
          AND result_date>=strftime(?::DATE-INTERVAL 730 DAY,'%Y%m%d')
          AND (try_cast(result_rank_raw AS INTEGER) BETWEEN 1 AND 89 OR result_rank_raw IN ('91','92'))
          ORDER BY result_date DESC LIMIT 5""",[row.horse_id,row.date,row.date]).df()
        assert len(history)==row.prior_n5
        expected=history['rank'].le(3).mean() if len(history) else .25
        assert abs(expected-row.prior_top3_mean5)<1e-12
        if len(history):assert pd.to_datetime(history.result_date,format='%Y%m%d').max()==row.history_last
    for row in primary.sample(20,random_state=20261026).itertuples():
        for role in ['jockey','trainer']:
            # Column names are a fixed two-element allowlist, never request text.
            query="""SELECT count(*),sum(CASE WHEN result_rank_raw='1' THEN 1 ELSE 0 END),
              sum(CASE WHEN try_cast(result_rank_raw AS INTEGER) BETWEEN 1 AND 3 THEN 1 ELSE 0 END)
              FROM confirmed_runners WHERE jockey_id_raw=? AND result_date<=strftime(?::DATE-INTERVAL 2 DAY,'%Y%m%d')
              AND result_date>=strftime(?::DATE-INTERVAL 365 DAY,'%Y%m%d')
              AND (try_cast(result_rank_raw AS INTEGER) BETWEEN 1 AND 89 OR result_rank_raw IN ('91','92'))"""
            if role=='trainer':query=query.replace('jockey_id_raw','trainer_id_raw')
            n,w,t=con.execute(query,[getattr(row,role+'_id_raw'),row.date,row.date]).fetchone()
            assert n==getattr(row,role+'_history_n')
            assert abs(((w or 0)+2)/(n+20)-getattr(row,role+'_prior_win'))<1e-12
            assert abs(((t or 0)+5)/(n+20)-getattr(row,role+'_prior_top3'))<1e-12
    con.close()
    replay=0;max_error=0.;reference_checks=0;feature_contract=[]
    by_year={year:primary.merge(pd.read_parquet(OUT/f'reference_features_{year}.parquet'),on='row_key',validate='one_to_one') for year in [2024,2025,2026]}
    for year,frame in by_year.items():
        ref=json.loads((OUT/f'reference_{year}.json').read_text())
        selected=frame[frame.year.eq(year)].sample(12,random_state=20261025)
        for target,r in ref.items():
            assert pd.Timestamp(r['last_trial'])<pd.Timestamp(f'{year-1}-01-01')
            numeric=selected[r['numeric']].to_numpy(float)
            numeric=np.where(np.isfinite(numeric),numeric,r['imputer'])
            values=[(numeric-r['mean'])/r['scale']]
            for col,categories in zip(r['categorical'],r['categories'],strict=True):
                values.append(np.column_stack([selected[col].fillna('미상').astype(str).eq(v).to_numpy(float) for v in categories]))
            expected=np.column_stack(values)@np.array(r['coef'])+r['intercept']
            actual=selected[target]-selected[target+'_resid']
            assert np.allclose(expected,actual,atol=1e-10,equal_nan=True)
            reference_checks+=len(selected)
    forbidden={'top3','win','rank','finish_p','horse_id','row_key','race_key','horse_rating_raw','carried_weight_raw','horse_weight_raw',
               'finish_time_seconds_raw','odds_win_raw','track_condition_raw'}
    for info in manifest:
        schema=json.loads((HERE/info['schema_file']).read_text())
        assert forbidden.isdisjoint(schema['numeric']+schema['categorical'])
        year=info['year'];frame=by_year[year];train=frame[frame.year<=year-2];cal=frame[frame.year.eq(year-1)]
        assert len(train)==info['train_n'] and len(cal)==info['cal_n']
        assert train.date.max()==pd.Timestamp(info['train_end']) and cal.date.max()==pd.Timestamp(info['cal_end'])
        assert cal.date.max()<frame[frame.year.eq(year)].date.min()
        v=train[schema['numeric']].apply(pd.to_numeric,errors='coerce').to_numpy(float)
        with __import__('warnings').catch_warnings():
            __import__('warnings').simplefilter('ignore',RuntimeWarning)
            med=np.nanmedian(v,axis=0);med=np.where(np.isfinite(med),med,0)
        assert np.allclose(med,schema['medians'])
        for col,categories in schema['categories'].items():assert categories==sorted(train[col].fillna('미상').astype(str).unique())
        subset=p[p.algorithm.eq(info['algorithm'])&p.model.eq(info['model'])&p.target.eq(info['target'])&p.year.eq(year)]
        assert len(subset)==info['test_n'] and subset.row_key.is_unique
        picked=subset.sample(6,random_state=20261025)
        rows=frame.set_index('row_key').loc[picked.row_key]
        matrix=independent_encode(rows,schema)
        model=HERE/info['model_file'];assert sha(model)==info['model_sha256']
        if info['algorithm']=='lightgbm':
            booster=lgb.Booster(model_file=str(model));trees=booster.dump_model()['tree_info']
            raw=np.array([sum(leaf(t['tree_structure'],row) for t in trees) for row in matrix])
            raw_cal=booster.predict(independent_encode(cal,schema),raw_score=True)
        else:
            coef=json.loads(model.read_text());raw=matrix@np.array(coef['coef'])+coef['intercept']
            raw_cal=independent_encode(cal,schema)@np.array(coef['coef'])+coef['intercept']
        raw_p=np.clip(expit(raw),1e-6,1-1e-6)
        probability=expit(info['platt_coef']*logit(raw_p)+info['platt_intercept'])
        error=float(np.max(np.abs(probability-picked.p.to_numpy())))
        assert error<1e-10 and np.allclose(raw_p,picked.p_raw,atol=1e-10)
        high=np.quantile(expit(info['platt_coef']*logit(np.clip(expit(raw_cal),1e-6,1-1e-6))+info['platt_intercept']),.8)
        assert abs(high-info['high_threshold'])<1e-10
        assert subset.high_group.eq(subset.p.ge(high)).all()
        max_error=max(max_error,error);replay+=len(picked)
        feature_contract.append(dict(year=year,algorithm=info['algorithm'],model=info['model'],target=info['target'],
            features=schema['numeric']+schema['categorical'],n_columns_transformed=matrix.shape[1],max_replay_error=error))
    m=pd.read_csv(OUT/'metrics.csv')
    for row in m.itertuples():
        z=p[p.algorithm.eq(row.algorithm)&p.model.eq(row.model)&p.target.eq(row.target)]
        if row.subset in ['서울','부산']:z=z[z.meet.eq(row.subset)]
        elif row.subset!='all':z=z[z.year.eq(int(row.subset))]
        y=z[row.target].to_numpy();prob=z.p.to_numpy()
        assert len(z)==row.n and int(y.sum())==row.events
        assert abs(np.mean((prob-y)**2)-row.brier)<1e-12
        assert abs(np.mean(-y*np.log(prob)-(1-y)*np.log1p(-prob))-row.logloss)<1e-12
        assert abs(auc(y,prob)-row.auc)<1e-12
    # Absolute high-group uncertainty uses a common Top3-based selection for both outcomes.
    rows=[]
    for model in ['context','total','sections','trial_focused']:
        z=p[p.algorithm.eq('lightgbm')&p.model.eq(model)&p.target.eq('top3')&p.high_group]
        daily=z.groupby('date').agg(n=('row_key','size'),win=('win','sum'),top3=('top3','sum'))
        rng=np.random.default_rng(20261025);w=rng.multinomial(len(daily),np.full(len(daily),1/len(daily)),size=2000)
        den=w@daily.n.to_numpy()
        for target in ['top3','win']:
            boot=w@daily[target].to_numpy()/den
            rows.append(dict(model=model,selection='Top3-model calibration-year upper20pct cutoff',target=target,
                n=len(z),events=int(z[target].sum()),rate=float(z[target].mean()),
                ci_low=float(np.quantile(boot,.025)),ci_high=float(np.quantile(boot,.975))))
    pd.DataFrame(rows).to_csv(OUT/'same_high_group_intervals.csv',index=False)
    dump(OUT/'feature_contract.json',feature_contract)
    assert sha(DB)==audit['inputs'][0]['sha256']
    dump(OUT/'verification.json',dict(passed=True,primary_first_starts_independently_checked=len(prior),
        latest_passes_independently_checked=len(latest),raw_source_rows_sampled=len(sample),raw_time_cells_checked=raw_checks,
        historical_field_windows_checked=len(f),people_scalar_lookups=40,reference_values_recomputed=reference_checks,
        models_replayed=len(manifest),scalar_predictions_replayed=replay,max_probability_replay_error=max_error,
        calibration_thresholds_recomputed=len(manifest),metric_groups_recomputed=len(m),
        future_trial_and_race_outcomes_excluded_from_features=True,first_start_horse_disjointness=True,
        raw_first_start_DNF_or_DQ_included=int(primary['rank'].isin([91,92]).sum()),
        final_roster_entry_proxy_not_certified_as_historical_entry=True,source_hash_preserved=True,
        production_changed=False,prospective_validation=False))
    print('VERIFIED',len(manifest),'models,',replay,'scalar predictions; error',max_error,flush=True)


if __name__=='__main__':main()

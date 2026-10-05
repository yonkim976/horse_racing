"""Independent artifact replay and pre-race history verification."""
import importlib.util
import json
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
SPEC=importlib.util.spec_from_file_location('pace_check',HERE/'run.py')
RUN=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(RUN)


def main():
    c=RUN.cfg(); a=json.loads((OUT/'data_audit.json').read_text()); s=json.loads((OUT/'summary.json').read_text())
    checks=[]
    def check(name,passed):
        checks.append({'check':name,'passed':bool(passed)})
        if not passed: raise AssertionError(name)
    check('source preserved',RUN.BASE.sha(ROOT/c['source_db'])==a['source_sha256'])
    check('production registry preserved',RUN.BASE.sha(ROOT/'config/prediction_model_registry.json')==a['registry_sha256'])
    check('baseline source code preserved',RUN.BASE.sha(RUN.BASE_PATH/'run.py')==a['baseline_code_sha256'])
    check('baseline input preserved',RUN.BASE.sha(RUN.BASE_PATH/'outputs/features.parquet')==a['baseline_features_sha256'])
    check('pace code frozen',RUN.BASE.sha(HERE/'run.py')==a['code_sha256']==s['code_sha256'])
    check('config frozen',RUN.BASE.sha(HERE/'config.json')==a['config_sha256']==s['config_sha256'])
    for name,digest in s['result_hashes'].items(): check('artifact hash '+name,RUN.BASE.sha(OUT/name)==digest)
    features=pd.read_parquet(OUT/'features.parquet'); labels=pd.read_parquet(OUT/'labels.parquet')
    f=features.merge(labels,on=RUN.KEY,validate='one_to_one')
    r=pd.read_parquet(OUT/'race_features.parquet').merge(pd.read_parquet(OUT/'race_labels.parquet'),on='race_key',validate='one_to_one')
    p=pd.read_parquet(OUT/'runner_predictions.parquet'); metrics=pd.read_csv(OUT/'point_metrics.csv'); t=pd.read_csv(OUT/'tempo_predictions.csv')
    check('no warm-up target rows',features.year.ge(2017).all())
    check('pace T-2 cutoff',(features.pace_source_date.isna() | features.pace_source_date.le(features.race_date-pd.Timedelta(days=2))).all())
    contract=json.loads((OUT/'feature_contract.json').read_text())
    forbidden={'S1F_rank','G3F_rank','S1F_fraction','G3F_fraction','outcome','tempo_time','actual_rank'}
    check('actual target columns excluded from feature whitelist',not set(contract['runner'])&forbidden and not set(contract['race'])&forbidden)
    check('predictions unique',not p.duplicated(RUN.KEY+['point','variant']).any())
    for point in c['points']:
        expected=f[f.year.isin(c['evaluation_years']) & f[f'{point}_complete']]
        expected_keys=set(zip(expected.race_key,expected.horse_id))
        for variant in c['variants']:
            one=p[p.point.eq(point)&p.variant.eq(variant)]
            check('complete point keyset '+point+'/'+variant,set(zip(one.race_key,one.horse_id))==expected_keys)
            check('probability sums '+point+'/'+variant,np.max(np.abs(one.groupby('race_key')[['prob_lead','prob_front3']].sum().to_numpy()-[1,3]))<1e-10)
            check('probability ordering '+point+'/'+variant,((one.prob_lead>=0)&(one.prob_lead<=one.prob_front3+1e-12)&(one.prob_front3<=1+1e-12)).all())
    sample=features.sample(100,random_state=c['seed'])[['horse_id','race_date','pace_source_date']]
    with duckdb.connect(a['source_db'],read_only=True) as db:
        db.register('sample',sample)
        actual=db.execute("""
          SELECT s.horse_id,s.race_date,s.pace_source_date,max(strptime(r.result_date,'%Y%m%d')::DATE) checked_date
          FROM sample s LEFT JOIN confirmed_runners r ON r.horse_id_raw=s.horse_id
           AND r.source_meet IN ('1','3')
           AND strptime(r.result_date,'%Y%m%d')::DATE<=s.race_date-interval 2 day
           AND (try_cast(r.result_rank_raw as int) BETWEEN 1 AND 20 OR try_cast(r.result_rank_raw as int) IN (91,92))
          GROUP BY ALL
        """).fetchdf()
    check('100 independent history source dates',((actual.pace_source_date==actual.checked_date)|(actual.pace_source_date.isna()&actual.checked_date.isna())).all())
    max_error=0.
    for bundle in s['models']:
        path=OUT/'models'/f"{bundle['meet']}_{bundle['year']}"
        for model in bundle['models']:
            check('model hash '+path.name+'/'+model['file'],RUN.BASE.sha(path/model['file'])==model['sha256'])
            check('chronology '+path.name+'/'+model['file'],model['training_year_end']<model['calibration_year']<model['evaluation_year'])
            is_tempo=model['file']=='tempo.txt'
            frame=r if is_tempo else f
            point=model['file'].split('.')[0]
            eligible=frame.tempo_complete if is_tempo else frame[f'{point}_complete']
            selected=frame[(frame.meet==bundle['meet'])&frame.year.eq(bundle['year'])&eligible].race_key.drop_duplicates().sample(1,random_state=c['seed']).iloc[0]
            one=frame[frame.race_key.eq(selected)].sort_values('program_no') if not is_tempo else frame[frame.race_key.eq(selected)]
            x=one[model['columns']].copy()
            for col,vocab in model['vocabulary'].items(): x[col]=pd.Categorical(x[col],categories=vocab)
            pred=lgb.Booster(model_file=str(path/model['file'])).predict(x)
            if is_tempo:
                saved=t[(t.race_key==selected)&t.variant.eq('field_model')].iloc[0]
                replay=pred[0]+bundle['tempo']['field_model']['bias']
                check('tempo replay '+selected,abs(replay-saved.predicted_time)<1e-10)
                check('tempo error replay '+selected,abs(abs(replay-saved.actual_time)-saved.absolute_error)<1e-10)
            else:
                saved=p[(p.race_key==selected)&p.point.eq(point)&p.variant.eq('field_model')].sort_values('program_no')
                max_error=max(max_error,float(np.max(np.abs(pred-saved.predicted_fraction.to_numpy()))))
                # Lead probability is first-stage softmax, independent of the joint helper.
                temp=bundle['point_temperatures'][point+':field_model'][0]
                logits=-pred/temp; lead=np.exp(logits-logsumexp(logits))
                check('lead probability independent replay '+selected+'/'+point,np.max(np.abs(lead-saved.prob_lead.to_numpy()))<1e-10)
                truth=one[f'{point}_rank'].to_numpy(dtype=float)
                observed_error=np.mean(np.abs(1+np.clip(pred,0,1)*(one.field_size.to_numpy()-1)-truth))
                saved_metric=metrics[(metrics.race_key==selected)&metrics.point.eq(point)&metrics.variant.eq('field_model')].iloc[0]
                check('position error independent replay '+selected+'/'+point,abs(observed_error-saved_metric.position_mae)<1e-10)
    check('all sampled regressor predictions replay',max_error<1e-10)
    supported=t[['prob_fast','prob_normal','prob_slow']].dropna()
    check('tempo class probabilities normalized',np.max(np.abs(supported.sum(axis=1)-1))<1e-10 and (supported>=-1e-12).all().all())
    check('tempo complete evaluation counts',t.groupby('variant').size().eq(r[r.year.isin(c['evaluation_years'])&r.tempo_complete].shape[0]).all())
    result={'passed':len(checks),'failed':0,'max_prediction_replay_error':max_error,'production_changed':False,'checks':checks}
    RUN.BASE.save_json(OUT/'verification.json',result)
    print(json.dumps({k:result[k] for k in ['passed','failed','max_prediction_replay_error']}))


if __name__=='__main__': main()

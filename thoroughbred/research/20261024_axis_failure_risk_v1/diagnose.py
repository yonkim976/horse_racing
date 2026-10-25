"""Post-evaluation descriptions only; no extra fits or selected rules."""
import json
import failure_common as c
import numpy as np
import pandas as pd

def main():
    c.check();m=pd.read_parquet(c.OUT/'race_predictions.parquet')
    features=[];folds=[]
    for file in sorted((c.OUT/'risk_models').glob('*/metadata.json')):
        meta=json.loads(file.read_text());gain=meta['gain'];total=sum(gain.values())
        features.append({key:value/total if total else 0. for key,value in gain.items()})
        folds.append({'meet':meta['meet'],'year':meta['evaluation_year'],'trees':meta['trees'],
            'training_races':meta['training_races'],'calibration_races':meta['calibration_races'],
            'lambda':meta['policy_lambda'],'calibration_policy_hits':meta['calibration_policy_hits'],
            'warning_thresholds':meta['warning_thresholds']})
    importance=pd.DataFrame(features).mean().sort_values(ascending=False)
    by_condition=[]
    for cols in [['meet','distance_m'],['meet','grade_raw']]:
        for key,g in m.groupby(cols):
            by_condition.append({'by':'+'.join(cols),'values':dict(zip(cols,[v.item() if isinstance(v,np.generic) else v for v in key])),
                'races':len(g),'failures':int(g.failure.sum()),'base_brier':float(g.base_risk_brier.mean()),
                'model_brier':float(g.model_risk_brier.mean()),'base_axis_hits':int(g.axis_hit.sum()),
                'selected_axis_hits':int(g.selected_hit.sum())})
    flagged=m.model_risk_warning.to_numpy(bool);baseflag=m.base_risk_warning.to_numpy(bool)
    v={'post_hoc_descriptive_only':True,'no_new_rules_selected':True,'folds':folds,
        'risk_score_correlation':float(np.corrcoef(m.base_risk,m.model_risk)[0,1]),
        'mean_absolute_probability_change':float(abs(m.model_risk-m.base_risk).mean()),
        'p95_absolute_probability_change':float(abs(m.model_risk-m.base_risk).quantile(.95)),
        'warning_overlap':int((flagged&baseflag).sum()),'new_only_warnings':int((flagged&~baseflag).sum()),
        'base_only_warnings':int((~flagged&baseflag).sum()),
        'model_missed_failures':int((m.failure.eq(1)&~flagged).sum()),
        'mean_gain_share':{k:float(v) for k,v in importance.items()},'gain_is_not_causal_effect':True,
        'conditions':by_condition}
    c.save(c.OUT/'diagnostics.json',v)
    print(json.dumps({k:v[k] for k in ['risk_score_correlation','mean_absolute_probability_change','warning_overlap','new_only_warnings','base_only_warnings','model_missed_failures']},ensure_ascii=False))

if __name__=='__main__':main()

"""Post-hoc additive model-score explanations, never a physical causal claim."""
import json
import numpy as np
import pandas as pd
import axis_common as c
import lightgbm as lgb

def group(name):
    if name in ['previous_carried_weight','current_carried_weight','current_vs_previous_carried_weight']:return 'carried_weight'
    if name.startswith(('moist_','profile_')):return 'historical_record_profile'
    if name.startswith(('state_rank_','state_distance_')):return 'dynamic_rank'
    if name.startswith('state_form_'):return 'dynamic_form'
    if name.startswith('state_early_'):return 'dynamic_early'
    if name.startswith('state_close_'):return 'dynamic_close'
    if name.startswith('state_'):return 'dynamic_other'
    early=set(c.old.base.contracts()['early47'])-set(c.old.base.contracts()['ability22'])
    late=set(c.old.base.contracts()['late66'])-set(c.old.base.contracts()['ability22'])
    if name in ['section_previous_distance','section_same_distance_n5']:return 'distance_history'
    if name in early:return 'historical_early_gate'
    if name in late:return 'historical_late_style'
    assert name in c.old.base.contracts()['ability22'],name
    return 'race_history_context'

def main():
    c.check();f=c.frame();cases=pd.read_parquet(c.OUT/'target_cases.parquet');rows=[];maximum=0.
    for year in [2024,2025,2026]:
        p=c.PREV/'outputs/models'/f'state_gbm_3_{year}'
        meta=json.loads((p/'metadata.json').read_text());g=cases[cases.year.eq(year)]
        one=f[f.meet.eq(3)&f.year.eq(year)].set_index(c.KEY)
        ai=pd.MultiIndex.from_arrays([g.race_key,g.axis_program_no,g.axis_horse_id],names=c.KEY)
        bi=pd.MultiIndex.from_arrays([g.race_key,g.alt_program_no,g.alt_horse_id],names=c.KEY)
        ordered=pd.concat([one.loc[ai],one.loc[bi]],ignore_index=True)
        x,_=c.old.base.encode(ordered,meta['features'],vocabulary=meta['category_vocabulary'])
        model=lgb.Booster(model_file=str(c.ROOT/meta['model_path']))
        contribution=model.predict(x,pred_contrib=True,num_threads=4)
        raw=model.predict(x,raw_score=True,num_threads=4)
        diff=contribution[:len(g)]-contribution[len(g):]
        error=max(float(abs(contribution.sum(1)-raw).max()),float(abs(diff.sum(1)-g.score_gap.to_numpy()).max()))
        assert error<1e-10;maximum=max(maximum,error)
        out=pd.DataFrame(diff[:,:-1],columns=meta['features']);out['race_key']=g.race_key.to_numpy();out['year']=year
        out['axis_hit']=g.axis_hit.to_numpy();out['alt_hit']=g.alt_hit.to_numpy();rows.append(out)
    combined=pd.concat(rows,ignore_index=True)
    combined.to_parquet(c.OUT/'decision_contributions.parquet',index=False,compression='zstd')
    features=c.old.features()['state_gbm'];groups={key:[x for x in features if group(x)==key] for key in sorted({group(x) for x in features})}
    summary=[]
    for period in ['all','2026']:
        part=combined if period=='all' else combined[combined.year.eq(2026)]
        for label,mask in [('axis_missed_alt_hit',part.axis_hit.eq(0)&part.alt_hit.eq(1)),('axis_hit_alt_missed',part.axis_hit.eq(1)&part.alt_hit.eq(0))]:
            g=part[mask]
            summary.append({'period':period,'case':label,'races':len(g),
                'mean_score_gap':float(g[features].sum(axis=1).mean()),
                'group_mean_contributions':{key:float(g[cols].sum(axis=1).mean()) for key,cols in groups.items()},
                'largest_axis_favouring_features':g[features].mean().sort_values(ascending=False).head(10).to_dict()})
    c.save(c.OUT/'decision_explanations.json',{'method':'LightGBM pred_contrib additive tree attribution; axis minus alternate',
        'post_hoc_diagnostic_added_after_switch_evaluation':True,'changes_to_frozen_learning_or_selection':False,
        'physical_causality_claim':False,'races':len(combined),'runner_explanations':2*len(combined),
        'maximum_score_reconstruction_error':maximum,'feature_groups':groups,'summary':summary})
    print('Decision explanations passed',maximum,json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()

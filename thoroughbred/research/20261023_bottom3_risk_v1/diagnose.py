"""Descriptive follow-up after the frozen evaluation; no rule/model selection."""
import json
import risk_common as c
import numpy as np
import pandas as pd

def main():
    c.check()
    m=pd.read_parquet(c.OUT/'race_metrics.parquet')
    rr=pd.read_parquet(c.OUT/'runner_predictions.parquet')
    baseprobs=pd.read_parquet(c.PREV/'outputs/runner_probabilities.parquet')
    baseprobs=baseprobs[baseprobs.variant.eq('state_gbm')]
    pp=rr.merge(baseprobs[c.KEY+['top3']],on=c.KEY,validate='1:1')
    a=m.merge(pp,left_on=['race_key','base_axis'],right_on=['race_key','program_no'],validate='1:1')
    rows=[]
    for name,g in [('all',a),('seoul',a[a.meet.eq(1)]),('busan',a[a.meet.eq(3)]),
        ('busan_grade5_1300_1600',a[a.meet.eq(3)&a.grade.eq('국5등급')&a.distance_m.isin([1300,1600])])]:
        fail=g[g.base_axis_hit.eq(0)]
        bottom=fail.bottom_truth.gt(0);normal=fail.result_status.eq('finished')
        rows.append({'scope':name,'races':len(g),'axis_misses':len(fail),
            'miss_actual_bottom_any_credit':int(bottom.sum()),'miss_actual_bottom_credit':float(fail.bottom_truth.sum()),
            'miss_normal_nonbottom_fourth_fifth':int((~bottom&normal&fail.finish_order.le(5)).sum()),
            'miss_normal_nonbottom_sixth_or_lower':int((~bottom&normal&fail.finish_order.ge(6)).sum()),
            'miss_nonfinishers':int((~normal).sum()),
            'axes_flagged_bottom':int(g.model_selected.sum()),
            'failed_axes_flagged_bottom':int(fail.model_selected.sum())})
    overlap=rr.assign(both=rr.baseline_selected&rr.model_selected).groupby('race_key').both.sum()
    groups=[]
    for fields in [['meet','distance_m'],['meet','grade'],['meet','field_size']]:
        for key,g in m.groupby(fields):
            groups.append({'by':'+'.join(fields),'values':dict(zip(fields,[x.item() if isinstance(x,np.generic) else x for x in key])),
                'races':len(g),'baseline_bottom_precision':float(g.baseline_correct.mean()/3),
                'model_bottom_precision':float(g.model_correct.mean()/3),
                'baseline_false_podium_rate':float(g.baseline_podium_excluded.mean()/3),
                'model_false_podium_rate':float(g.model_podium_excluded.mean()/3),
                'base_axis_hits':int(g.base_axis_hit.sum()),'selected_axis_hits':int(g.selected_axis_hit.sum())})
    c.save(c.OUT/'diagnostics.json',{'post_hoc_descriptive_only':True,'axis_failure_composition':rows,
        'mean_bottom_selection_overlap':float(overlap.mean()),'identical_bottom_sets_races':int(overlap.eq(3).sum()),
        'bottom_selection_overlap_counts':{str(k):int(v) for k,v in overlap.value_counts().sort_index().items()},
        'groups':groups,'no_new_rules_from_subgroups':True})
    axes=[]
    for policy in ['base','exclude','selected']:
        g=m[['race_key',policy+'_axis']].rename(columns={policy+'_axis':'program_no'}).merge(pp,on=['race_key','program_no'],validate='1:1')
        g['policy']=policy
        axes.append(g[['race_key','program_no','horse_id','finish_order','result_status','top3','bottom_truth','model_bottom_probability','policy']])
    pd.concat(axes,ignore_index=True).to_parquet(c.OUT/'axis_details.parquet',index=False,compression='zstd')
    c.save(c.OUT/'decision.json',{'bottom_precision_improved':True,
        'bottom_precision_ci95_lower_positive':json.loads((c.OUT/'results.json').read_text())['all']['bottom_comparison']['difference_ci95'][0]>0,
        'false_podium_exclusion_increased':bool(m.model_podium_excluded.sum()>m.baseline_podium_excluded.sum()),
        'axis_selected_net_hits':int(m.selected_axis_hit.sum()-m.base_axis_hit.sum()),
        'axis_2026_net_hits':int((m.selected_axis_hit-m.base_axis_hit)[m.year.eq(2026)].sum()),
        'retain_as_diagnostic_candidate':True,'adopt_as_exclusion_policy':False,'replace_research_baseline':False,
        'ten_percent_relative_axis_improvement_achieved':False,'production_changed':False})
    print(json.dumps(rows,ensure_ascii=False),flush=True)

if __name__=='__main__':main()

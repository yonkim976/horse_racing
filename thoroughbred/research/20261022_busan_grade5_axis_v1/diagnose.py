"""Descriptive, explicitly post-hoc failure patterns; never model inputs."""
import numpy as np
import pandas as pd
import duckdb
import axis_common as c

def summarize(g):
    return {'races':len(g),'hits':int(g.axis_hit.sum()),'misses':int((1-g.axis_hit).sum()),
        'hit_rate':float(g.axis_hit.mean()),'predicted_mean':float(g.axis_probability.mean()),
        'second_hits':int(g.alt_hit.sum()),'second_only':int(((g.axis_hit==0)&(g.alt_hit==1)).sum()),
        'axis_only':int(((g.axis_hit==1)&(g.alt_hit==0)).sum()),
        'top2_contains_podium':int((g.axis_hit|g.alt_hit).sum()),
        'top3_contains_podium':int((g.axis_hit|g.alt_hit|g.third_hit).sum())}

def conditions(f):
    def bins(x,edges,labels):return pd.cut(x,edges,labels=labels,right=False).astype('str').where(x.notna(),'missing')
    out={'axis_probability':bins(f.axis_probability,[-np.inf,.55,.7,np.inf],['<.55','.55-.70','>=.70']),
        'probability_gap':bins(f.probability_gap,[-np.inf,.05,.15,np.inf],['<.05','.05-.15','>=.15']),
        'history':bins(f.axis_history_count,[-np.inf,4,8,np.inf],['<=3','4-7','>=8']),
        'days_since_last':bins(f.axis_days_since_last,[-np.inf,21,61,np.inf],['<21','21-60','>60']),
        'distance_change':pd.Series(np.select([f.axis_distance_change.lt(0),f.axis_distance_change.gt(0)],['shorter','longer'],default='same'),index=f.index).where(f.axis_distance_change.notna(),'missing')}
    for label,series in [('same_distance',f.axis_section_same_distance_n5),('promoted',f.axis_promoted),
        ('front_probability',f.axis_front_gate_probability),('faster_opponents',f.axis_dirgate_inner_faster_n+f.axis_dirgate_outer_faster_n),
        ('declining_form',f.axis_state_form_trend)]:
        if label=='same_distance':flag=series.eq(0);yes,no='zero','one_or_more'
        elif label=='promoted':flag=series.eq(1);yes,no='yes','no'
        elif label=='front_probability':flag=series.ge(.5);yes,no='>=.5','<.5'
        elif label=='faster_opponents':flag=series.ge(2);yes,no='>=2','<2'
        else:flag=series.lt(0);yes,no='negative','nonnegative'
        out[label]=pd.Series(np.where(flag,yes,no),index=f.index).where(series.notna(),'missing')
    return out

def main():
    c.check();allp=pd.read_parquet(c.OUT/'pairs.parquet');f=allp[allp.phase.eq('evaluation')].copy()
    target=f[f.target].copy();assert len(target)==210
    summaries=[]
    for scope,g in [('all_target',target),('2026_target',target[target.year.eq(2026)]),('all_busan',f)]:
        summaries.append({'scope':scope,**summarize(g)})
    for col in ['year','distance_m']:
        for value,g in target.groupby(col):summaries.append({'scope':f'{col}_{int(value)}',**summarize(g)})
    groups=[]
    for scope,g in [('all',target),('2026',target[target.year.eq(2026)])]:
        for name,labels in conditions(g).items():
            for value,ix in labels.groupby(labels).groups.items():groups.append({'scope':scope,'condition':name,'value':value,**summarize(g.loc[ix])})
    with duckdb.connect(str(c.old.DB),read_only=True) as db:
        names=db.execute("""SELECT CAST(canonical_meet AS VARCHAR)||':'||strftime(race_date,'%Y%m%d')||':'||CAST(race_no AS VARCHAR) race_key,
            chul_no program_no,hr_no horse_id,horse_name_raw,finish_order,result_status
            FROM entry_result WHERE canonical_meet=? AND race_date BETWEEN ? AND ?""",[3,'2024-01-01','2026-09-20']).df()
    assert not names.duplicated(c.KEY).any()
    history=pd.read_parquet(c.old.HISTORY,columns=c.KEY+['role','early','last600','late','middle_gain','gain400','gain200'])
    for prefix in ['axis','alt']:
        mapping={k:prefix+'_'+k for k in ['program_no','horse_id','horse_name_raw','finish_order','result_status']}
        target=target.merge(names.rename(columns=mapping),on=['race_key',prefix+'_program_no',prefix+'_horse_id'],how='left',validate='one_to_one')
    h=history.rename(columns={k:'observed_'+k for k in history if k not in ['race_key','program_no','horse_id']})
    h=h.rename(columns={'program_no':'axis_program_no','horse_id':'axis_horse_id'})
    target=target.merge(h,on=['race_key','axis_program_no','axis_horse_id'],how='left',validate='one_to_one')
    assert target.axis_result_status.notna().all() and target.alt_result_status.notna().all()
    observed=[]
    for scope,g in [('all',target),('2026',target[target.year.eq(2026)])]:
        failed=g[g.axis_hit.eq(0)]
        bins={'finish_4_5':int((failed.axis_result_status.eq('finished')&failed.axis_finish_order.between(4,5)).sum()),
              'finish_6_plus':int((failed.axis_result_status.eq('finished')&failed.axis_finish_order.ge(6)).sum()),
              'nonfinish_or_dq':int((~failed.axis_result_status.eq('finished')).sum())}
        assert sum(bins.values())==len(failed)
        for label,part in [('hit',g[g.axis_hit.eq(1)]),('miss',failed)]:
            observed.append({'scope':scope,'axis_result':label,'races':len(part),'role_available':int(part.observed_role.notna().sum()),
                'first_early_group':int(part.observed_role.eq(0).sum()),
                'early_role_counts':{str(int(k)):int(v) for k,v in part.observed_role.value_counts().items()},
                'gain200_available':int(part.observed_gain200.notna().sum()),
                'lost_position_last200':int(part.observed_gain200.lt(0).sum()),
                'last600_mean':float(part.observed_last600.mean()),'finish_bins_among_misses':bins})
    target.to_parquet(c.OUT/'target_cases.parquet',index=False,compression='zstd')
    c.save(c.OUT/'diagnostics.json',{'summary':summaries,'pre_race_conditions':groups,'postrace_observations':observed,
        'post_hoc_selected_population':True,'causal_explanation_established':False,'multiple_comparison_adjusted':False,
        'new_rule_selected_from_diagnostic_bins':False})
    print('Diagnosis complete',summaries,c.storage(),flush=True)

if __name__=='__main__':main()

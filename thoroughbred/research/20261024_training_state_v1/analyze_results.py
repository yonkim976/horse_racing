"""Paired day-block uncertainty and descriptive, fixed-cohort diagnostics."""
import json
import numpy as np
import pandas as pd
import study_common as c

HITS=['axis_top3','quinella_one','quinella_three','qpl_one','qpl_three','qpl_count']
LOSSES=['runner_brier','trio_logloss','ordered_logloss','axis_brier']
def paired(g,metric):
    x=g[metric+'_new'].to_numpy(float);y=g[metric+'_base'].to_numpy(float)
    dates,idx=np.unique(g.race_date,return_inverse=True);n=np.bincount(idx);sums=np.bincount(idx,weights=x-y)
    rng=np.random.default_rng(20261024);draws=rng.integers(0,len(dates),size=(2000,len(dates)))
    values=sums[draws].sum(1)/n[draws].sum(1)
    return {'n':len(g),'baseline_total':float(y.sum()),'candidate_total':float(x.sum()),
        'baseline_mean':float(y.mean()),'candidate_mean':float(x.mean()),'difference':float((x-y).mean()),
        'relative_change':float(x.mean()/y.mean()-1) if y.mean()!=0 else None,
        'ci95':np.quantile(values,[.025,.975]).tolist(),
        'gained_races':int(((x>y) if metric in HITS else (x<y)).sum()),
        'lost_races':int(((x<y) if metric in HITS else (x>y)).sum())}

def main():
    b=pd.read_parquet(c.PREV/'outputs/race_metrics.parquet');b=b[b.variant.eq('state_gbm')].copy()
    a=pd.read_parquet(c.OUT/'race_metrics.parquet');f=c.old.frame();f=f[f.year>=2024].copy()
    context=f.groupby('race_key').agg(no_history_runners=('history_count',lambda x:int(x.eq(0).sum())),
        long_layoff_runners=('days_since_last',lambda x:int(x.ge(90).sum())))
    group_results=[];changes=[];folds=[]
    for variant in c.VARIANTS:
        new=a[a.variant.eq(variant)].copy();g=b.merge(new,on='race_key',suffixes=('_base','_new'),validate='one_to_one')
        assert len(g)==4799 and (g.race_date_base==g.race_date_new).all()
        g['race_date']=g.race_date_base;g=g.join(context,on='race_key')
        groups={'all':np.ones(len(g),bool),'seoul':g.meet_base.eq(1),'busan':g.meet_base.eq(3)}
        for year in [2024,2025,2026]:
            groups[str(year)]=g.year_base.eq(year)
            for meet in [1,3]:groups[f'meet{meet}_{year}']=g.year_base.eq(year)&g.meet_base.eq(meet)
        target=g.meet_base.eq(3)&g.grade_base.eq('국5등급')&g.distance_m_base.isin([1300,1600])
        # The exact grade string is checked against the inherited subgroup size.
        if target.sum()!=210:
            target=g.meet_base.eq(3)&g.grade_base.str.contains('국5',regex=False)&g.distance_m_base.isin([1300,1600])
        assert target.sum()==210
        groups['busan_grade5_1300_1600']=target;groups['busan_grade5_1300_1600_2026']=target&g.year_base.eq(2026)
        groups['race_has_debutant']=g.no_history_runners.gt(0);groups['race_no_debutant']=g.no_history_runners.eq(0)
        groups['race_has_layoff90']=g.long_layoff_runners.gt(0)
        groups['base_axis_history_le3']=g.axis_history_count_base.le(3)
        for name,mask in groups.items():
            s=g[mask];metrics={k:paired(s,k) for k in HITS+LOSSES}
            group_results.append({'variant':variant,'group':name,'races':len(s),'metrics':metrics})
        changed=g.axis_program_no_base.ne(g.axis_program_no_new)
        selected=g.loc[changed,['race_key','race_date','meet_base','year_base','grade_base','distance_m_base',
            'axis_program_no_base','axis_program_no_new','axis_top3_base','axis_top3_new','axis_probability_base','axis_probability_new']].copy()
        selected['variant']=variant;selected['net_hit']=selected.axis_top3_new-selected.axis_top3_base;changes.append(selected)
        for _,s in g.groupby(['meet_base','year_base']):
            folds.append({'variant':variant,'meet':int(s.meet_base.iloc[0]),'year':int(s.year_base.iloc[0]),'races':len(s),
                'baseline_axis_hits':int(s.axis_top3_base.sum()),'candidate_axis_hits':int(s.axis_top3_new.sum()),
                'axis_changes':int(s.axis_program_no_base.ne(s.axis_program_no_new).sum()),
                'gains':int((s.axis_top3_new>s.axis_top3_base).sum()),'losses':int((s.axis_top3_new<s.axis_top3_base).sum())})
    change=pd.concat(changes,ignore_index=True);change.to_parquet(c.OUT/'axis_changes.parquet',index=False,compression='zstd')
    pd.DataFrame(folds).to_csv(c.OUT/'fold_results.csv',index=False)
    gains=[]
    for p in sorted((c.OUT/'models').glob('*/metadata.json')):
        m=json.loads(p.read_text());total=sum(m['gain'].values());new=sum(v for k,v in m['gain'].items() if k.startswith('train_'))
        gains.append({'variant':m['variant'],'meet':m['venue'],'year':m['evaluation_year'],'trees':m['trees'],
            'training_feature_gain_share':new/total,'top_training_features':sorted([(k,v) for k,v in m['gain'].items() if k.startswith('train_')],key=lambda x:-x[1])[:6]})
    ab=a[a.variant.eq('quantity_t2')].merge(a[a.variant.eq('personal_t2')],on='race_key',suffixes=('_base','_new'),validate='one_to_one')
    ab['race_date']=ab.race_date_base
    ablation=[{'group':name,'metrics':{k:paired(ab[mask],k) for k in HITS+LOSSES}}
        for name,mask in [('all',np.ones(len(ab),bool)),('seoul',ab.meet_base.eq(1)),('busan',ab.meet_base.eq(3))]]
    main_result=next(x for x in group_results if x['variant']=='personal_t2' and x['group']=='all')
    axis=main_result['metrics']['axis_top3'];loss=main_result['metrics']['runner_brier']
    decision={'main_variant':'personal_t2','main_axis_ci_positive':axis['ci95'][0]>0,
        'relative_ten_percent_reached_in_point_estimate':axis['relative_change']>=.1,
        'runner_brier_point_improved':loss['difference']<0,'promoted':False,
        'reason_for_no_operational_promotion':'Repeated development period and unverified historical publication times; prospective feature snapshots required.',
        'further_tuning_on_evaluation_stopped':True}
    c.save(c.OUT/'results.json',{'groups':group_results,'folds':folds,'feature_importance':gains,'personal_vs_quantity':ablation,
        'bootstrap':'2000 resamples of calendar dates with paired races, seed20261024',
        'primary':'personal_t2, all4799 races, axis1','subgroup_status':'descriptive; layoff threshold90days, low history<=3',
        'same_reused_development_period':True,'new_future_validation':False,'decision':decision})
    c.save(c.OUT/'decision.json',decision)
    for x in group_results:
        if x['group'] in ['all','seoul','busan','busan_grade5_1300_1600']:
            m=x['metrics']['axis_top3'];print(x['variant'],x['group'],m['candidate_total'],m['candidate_mean'],m['difference'],m['ci95'],flush=True)
if __name__=='__main__':main()

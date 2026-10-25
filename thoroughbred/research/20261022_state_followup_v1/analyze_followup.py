"""All predeclared candidate and fixed-policy probability comparisons."""
import numpy as np
import pandas as pd
import support as s

def all_rows():
    old=pd.read_parquet(s.old.BASE/'outputs/race_metrics.parquet')
    old=old[old.scope.eq('all_starters')&old.variant.isin(['additive89','full103'])]
    previous=pd.read_parquet(s.PREV/'outputs/race_metrics.parquet')
    new=pd.read_parquet(s.OUT/'race_metrics.parquet')
    f=pd.concat([old,previous,new],ignore_index=True)
    f['selected_mean_brier']=f[['axis_brier','qnl3_brier','qpl3_brier']].mean(axis=1)
    return f

def main():
    f=all_rows();metrics=s.oldanalysis.METRICS+['selected_mean_brier'];s.oldanalysis.METRICS=metrics
    overall=[];comparisons={}
    for variant,g in f.groupby('variant'):
        overall.append({'variant':variant,'races':len(g),'means':{m:float(g[m].mean()) for m in metrics},
            'hits':{m:int(g[m].sum()) for m in metrics[:6]}})
    pairs=[(a,b) for a in s.contracts() for b in ['state_gbm','strong89','additive89','full103']]
    pairs += [('rank_only','simple_rank'),('rank_only','no_rank'),('cal_candidate','state_gbm'),('cal_selected','state_gbm')]
    for candidate,reference in pairs:
        a=f[f.variant.eq(candidate)];b=f[f.variant.eq(reference)]
        data={'all':s.oldanalysis.paired(a,b)}
        for col in ['year','meet']:
            for value in sorted(a[col].unique()):data[f'{col}_{value}']=s.oldanalysis.paired(a[a[col].eq(value)],b[b[col].eq(value)])
        comparisons[f'{candidate}_vs_{reference}']=data
    decisions={}
    for v in s.contracts():
        m=comparisons[f'{v}_vs_state_gbm']['all']['metrics']
        keep=m['quinella_three']['difference_ci95'][0]>0 and m['axis_top3']['difference_ci95'][0]>-.01 and m['qpl_three']['difference_ci95'][0]>-.01 and m['ordered_logloss']['difference']<=0
        el=comparisons[f'{v}_vs_additive89']['all']['metrics']
        decisions[v]={'retain_over_state_gbm':bool(keep),
            'relative_ten_percent_point':{k:el[k]['relative_percent']>=10 for k in metrics[:5]},
            'relative_ten_percent_lower_ci':{k:el[k]['relative_percent_ci95'][0]>=10 for k in metrics[:5]}}
    m=comparisons['cal_selected_vs_state_gbm']['all']['metrics']
    decisions['cal_selected']={'probability_improvement_confirmed':m['selected_mean_brier']['difference_ci95'][1]<0 and m['ordered_logloss']['difference']<=0,
        'recommendations_unchanged':all(m[k]['difference']==0 for k in metrics[:6])}
    descriptive=[]
    for v,g in f.groupby('variant'):
        for label,pcol,ycol in [('axis','axis_probability','axis_top3'),('qnl3','qnl3_probability','quinella_three'),('qpl3','qpl3_probability','qpl_three')]:
            bins=np.minimum(9,(g[pcol]*10).astype(int));a=g.groupby(bins).agg(prob=(pcol,'sum'),hits=(ycol,'sum'))
            descriptive.append({'variant':v,'target':label,'predicted_mean':float(g[pcol].mean()),'observed_mean':float(g[ycol].mean()),
                'fixed_ten_bin_ece':float((a.prob-a.hits).abs().sum()/len(g))})
    s.save(s.OUT/'results.json',{'overall':overall,'comparisons':comparisons,'decisions':decisions,'calibration_descriptive':descriptive,
        'bootstrap':{'draws':2000,'cluster':'race_date','seed':20261024,'pointwise_not_multiple_comparison_adjusted':True},
        'historical_development_only':True,'production_changed':False})
    print({'overall':overall,'decisions':decisions},flush=True)

if __name__=='__main__':main()

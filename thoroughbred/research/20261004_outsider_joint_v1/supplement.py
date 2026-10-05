"""Frozen ambiguous-field slices, matched operating comparison, selection intervals."""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;OUT=HERE/'outputs'
PREVIOUS=HERE.parent/'20261004_close_contenders_v1/outputs'

def interval(delta,dates,rng):
    daily=pd.DataFrame({'date':dates,'delta':delta}).groupby('date').delta.agg(['sum','size']).to_numpy()
    picks=rng.integers(0,len(daily),size=(2000,len(daily)))
    draws=daily[picks]
    return np.quantile(draws[:,:,0].sum(axis=1)/draws[:,:,1].sum(axis=1),[.025,.975]).tolist()

def main(refresh=False):
    if (OUT/'supplement_summary.json').exists():
        if not refresh:raise FileExistsError('Existing supplementary report')
        archived=OUT/'supplement_summary_before_dnf_normalization.json'
        if archived.exists():raise FileExistsError('Existing archived supplementary report')
        (OUT/'supplement_summary.json').rename(archived)
    races=pd.read_csv(OUT/'race_metrics.csv');runners=pd.read_parquet(OUT/'runner_predictions.parquet')
    frozen=pd.read_csv(PREVIOUS/'race_diagnostics.csv');frozen=frozen[frozen.variant.eq('context')]
    joined=races.merge(frozen[['race_key','gap12','close5_count']],on='race_key',validate='many_to_one')
    rows=[]
    for (meet,variant),g in joined.groupby(['meet','variant']):
        for group,mask in [('all',np.ones(len(g),bool)),('gap12_le_2pp',g.gap12.le(.02+1e-12)),('close5_threeplus',g.close5_count.ge(3))]:
            s=g[mask]
            rows.append(dict(meet=int(meet),variant=variant,group=group,races=len(s),trio6_hit=float(s.top6_trio_hit.mean()),
                top5_podium=float(s.top5_contains_podium.mean()),top7_podium=float(s.top7_contains_podium.mean())))
    pd.DataFrame(rows).to_csv(OUT/'frozen_ambiguous_field_metrics.csv',index=False)
    # Restrict to identical runner identities and actual outcomes for operating comparison.
    operating=pd.read_csv(PREVIOUS/'race_diagnostics.csv');operating=operating[operating.variant.eq('operating_exact_2026')].copy()
    operating['bridge']=operating.race_key.str.replace('RACE:SEOUL:','1:',regex=False).str.replace('RACE:BUSAN:','3:',regex=False).str.replace(r':0([1-9])$',r':\1',regex=True)
    op_runners=pd.read_parquet(PREVIOUS/'operating_runner_predictions.parquet')
    # NaN in the operating snapshot and 91/92 in the API snapshot both mean no numeric finishing rank.
    # Normalize only non-ranks; every observed numeric finishing rank must still match.
    op_runners['comparison_rank']=op_runners.outcome.where(op_runners.outcome.between(1,20),0).astype(int)
    runners['comparison_rank']=runners.outcome.where(runners.outcome.between(1,20),0).astype(int)
    op_sets=op_runners.groupby('race_key').apply(lambda d:frozenset(zip(d.horse_id,d.comparison_rank)),include_groups=False)
    research_sets=runners[runners.variant.eq('context')].groupby('race_key').apply(lambda d:frozenset(zip(d.horse_id,d.comparison_rank)),include_groups=False)
    valid=[row.bridge for row in operating.itertuples() if row.bridge in research_sets.index and research_sets[row.bridge]==op_sets[row.race_key]]
    operating=operating[operating.bridge.isin(valid)]
    rng=np.random.default_rng(20261004);comparisons=[]
    for meet in (0,1,3):
        for variant in ['context','direct','upside','upside_joint']:
            left=races[races.variant.eq(variant)];right=operating
            if meet:left=left[left.meet.eq(meet)];right=right[right.meet.eq(meet)]
            p=left.merge(right,left_on='race_key',right_on='bridge',suffixes=('_research','_operating'),validate='one_to_one')
            for a,b in [('top6_trio_hit','trio6_hit'),('top5_contains_podium','a_top5_podium')]:
                comparisons.append(dict(meet=meet,variant=variant,races=len(p),metric=a,
                    research=float(p[a].mean()),operating=float(p[b].mean()),difference=float((p[a]-p[b]).mean()),
                    date_bootstrap_95_interval=interval(p[a]-p[b],p.race_date_research,rng)))
    selection=[]
    for (meet,variant),g in races.groupby(['meet','variant']):
        daily=g.assign(selected_hits=g.selected*g.top6_trio_hit).groupby('race_date').agg(hits=('selected_hits','sum'),selected=('selected','sum'),n=('race_key','size'))
        values=daily.to_numpy();picks=rng.integers(0,len(values),size=(2000,len(values)));draws=values[picks].sum(axis=1)
        ci=np.quantile(draws[:,0]/draws[:,1],[.025,.975]).tolist()
        selection.append(dict(meet=int(meet),variant=variant,selected_hit_95_interval=ci,selected=int(g.selected.sum()),races=len(g)))
    result=dict(operating_matched_races=len(valid),operating_matched_outcome_and_starter_sets=True,
        no_numeric_finish_rank_normalized_to_zero=True,
        operating_comparisons=comparisons,selection_intervals=selection,bootstrap_repeats=2000,seed=20261004,
        ambiguous_groups_defined_from_frozen_baseline=True)
    (OUT/'supplement_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(pd.DataFrame(rows).to_string(index=False))
    print('Operating overall comparison:',json.dumps([x for x in comparisons if x['meet']==0 and x['metric']=='top6_trio_hit']))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--refresh',action='store_true');args=parser.parse_args();main(args.refresh)

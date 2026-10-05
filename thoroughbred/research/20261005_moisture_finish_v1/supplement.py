"""Common outsider reference, exploratory slices and matched operating comparison."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;OUT=HERE/'outputs'
PARENT=HERE.parent/'20261004_outsider_joint_v1/outputs'
OPS=HERE.parent/'20261004_close_contenders_v1/outputs'
KEY=['race_key','program_no','horse_id']

def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def interval(delta,dates,rng):
    daily=pd.DataFrame({'date':dates,'delta':delta}).groupby('date').delta.agg(['sum','size']).to_numpy()
    draws=daily[rng.integers(0,len(daily),size=(2000,len(daily)))].sum(axis=1)
    return np.quantile(draws[:,0]/draws[:,1],[.025,.975]).tolist()

def main():
    target=OUT/'supplement_summary.json'
    if target.exists():raise FileExistsError('Completed supplementary evaluation')
    sources=[OUT/'race_metrics.csv',OUT/'runner_predictions.parquet',PARENT/'features.parquet',
             OPS/'race_diagnostics.csv',OPS/'operating_runner_predictions.parquet']
    hashes={str(p):sha(p) for p in sources}
    races=pd.read_csv(sources[0]);runners=pd.read_parquet(sources[1]);features=pd.read_parquet(sources[2])
    attrs=features.groupby('race_key',sort=False)[['distance_m','grade','history_count']].agg(
        distance_m=('distance_m','first'),grade=('grade','first'),minimum_history=('history_count','min')).reset_index()
    races=races.drop(columns=['distance_m','grade'],errors='ignore').merge(attrs,on='race_key',validate='many_to_one')
    # Parent auxiliary outsider counts used context5. Recompute EVERY variant against raw5.
    baseline={rid:set(g.sort_values('program_no').iloc[np.argsort(-g.sort_values('program_no').prob_top3.to_numpy(),kind='stable')[:5]].horse_id)
              for rid,g in runners[runners.variant.eq('raw')].groupby('race_key',sort=False)}
    rows=[]
    for (variant,rid),g in runners.groupby(['variant','race_key'],sort=False):
        g=g.sort_values('program_no');rank=np.argsort(-g.prob_top3.to_numpy(),kind='stable')
        truth=set(g.loc[g.outcome.le(3),'horse_id']);current=set(g.iloc[rank[:5]].horse_id)
        outside=truth-baseline[rid];inside=truth&baseline[rid]
        rows.append(dict(variant=variant,race_key=rid,baseline_outsiders=len(outside),
                         rescued_outsiders=len(outside&current),lost_insiders=len(inside-current)))
    aligned=races.drop(columns=['baseline_outsiders','rescued_outsiders','lost_insiders']).merge(pd.DataFrame(rows),on=['variant','race_key'],validate='one_to_one')
    for candidate in ['replace','replace_joint','augment','augment_joint']:
        a=races[races.variant.eq(candidate)].sort_values('race_key');b=aligned[aligned.variant.eq(candidate)].sort_values('race_key')
        for col in ['baseline_outsiders','rescued_outsiders','lost_insiders']:
            if not np.array_equal(a[col],b[col]):raise ValueError('New outsider reference mismatch')
    aligned.to_csv(OUT/'aligned_race_metrics.csv',index=False)
    outsider=[]
    for (meet,variant),g in aligned.groupby(['meet','variant']):
        for period,s in [('all',g)]+[(str(y),z) for y,z in g.groupby('evaluation_year')]:
            outside=int(s.baseline_outsiders.sum());rescued=int(s.rescued_outsiders.sum())
            outsider.append(dict(meet=int(meet),variant=variant,period=period,races=len(s),outside_podium_horses=outside,
                                 rescued=rescued,lost=int(s.lost_insiders.sum()),rescue_rate=rescued/outside,
                                 outside_races=int(s.baseline_outsiders.gt(0).sum())))
    pd.DataFrame(outsider).to_csv(OUT/'aligned_outsider_metrics.csv',index=False)
    slices=[]
    for (meet,variant),g in aligned.groupby(['meet','variant']):
        for label,column in [('distance','distance_m'),('grade','grade'),('low_history','low_history_present')]:
            for value,s in g.groupby(column,dropna=False):
                slices.append(dict(meet=int(meet),variant=variant,slice=label,value=str(value),races=len(s),
                                   trio6_hit=float(s.trio6_hit.mean()),trio_nll=float(s.trio_nll.mean()),
                                   top5_podium=float(s.top5_contains_podium.mean())))
    pd.DataFrame(slices).to_csv(OUT/'exploratory_slices.csv',index=False)
    op=pd.read_csv(sources[3]);op=op[op.variant.eq('operating_exact_2026')].copy()
    op_runners=pd.read_parquet(sources[4])
    for f in [runners,op_runners]:f['comparison_rank']=f.outcome.where(f.outcome.between(1,20),0).astype(int)
    op_sets=op_runners.groupby('race_key').apply(lambda g:frozenset(zip(g.program_no,g.horse_id,g.comparison_rank)),include_groups=False)
    new_sets=runners[runners.variant.eq('raw')].groupby('race_key').apply(
        lambda g:frozenset(zip(g.program_no,g.horse_id,g.comparison_rank)),include_groups=False)
    op['bridge']=(op.race_key.str.replace('RACE:SEOUL:','1:',regex=False).str.replace('RACE:BUSAN:','3:',regex=False)
                  .str.replace(r':0([1-9])$',r':\1',regex=True))
    op['matched']=[row.bridge in new_sets.index and new_sets[row.bridge]==op_sets[row.race_key] for row in op.itertuples()]
    matched=op[op.matched];rng=np.random.default_rng(20261005);comparisons=[]
    for meet in [0,1,3]:
        for variant in sorted(aligned.variant.unique()):
            a=aligned[aligned.variant.eq(variant)];b=matched
            if meet:a=a[a.meet.eq(meet)];b=b[b.meet.eq(meet)]
            paired=a.merge(b,left_on='race_key',right_on='bridge',suffixes=('_new','_operating'),validate='one_to_one')
            if len(paired)!=len(b):raise ValueError('Lost matched race')
            delta=paired.trio6_hit_new-paired.trio6_hit_operating
            comparisons.append(dict(meet=meet,variant=variant,races=len(paired),new_rate=float(paired.trio6_hit_new.mean()),
                                    operating_rate=float(paired.trio6_hit_operating.mean()),difference=float(delta.mean()),
                                    date_bootstrap_95_interval=interval(delta,paired.race_date_new,rng)))
    selection=[]
    for (meet,variant),g in aligned.groupby(['meet','variant']):
        keep=g[g.selected.eq(1)]
        selection.append(dict(meet=int(meet),variant=variant,selected=len(keep),total=len(g),
                              rate=float(keep.trio6_hit.mean()),hits=int(keep.trio6_hit.sum()),all_hits=int(g.trio6_hit.sum()),
                              date_bootstrap_95_interval=interval(keep.trio6_hit,keep.race_date,rng)))
    rescue=[]
    for meet in (1,3):
        for a,b in [('raw','replace'),('raw','augment'),('raw_joint','replace_joint'),('raw_joint','augment_joint')]:
            p=aligned[aligned.meet.eq(meet)&aligned.variant.eq(a)].merge(aligned[aligned.meet.eq(meet)&aligned.variant.eq(b)],on='race_key',suffixes=('_a','_b'),validate='one_to_one')
            delta=p.rescued_outsiders_b-p.rescued_outsiders_a
            rescue.append(dict(meet=meet,base=a,candidate=b,difference=float(delta.mean()),
                               date_bootstrap_95_interval=interval(delta,p.race_date_a,rng)))
    if any(sha(Path(p))!=h for p,h in hashes.items()):raise ValueError('Changed supplement input')
    result=dict(inputs=hashes,operating_matched_races=len(matched),bootstrap_draws=2000,bootstrap_seed=20261005,
                outsider_reference='raw Top3 marginal top5 for all variants; main inherited parent auxiliary rows use context5',
                main_paired_rescued_outsiders_comparison_superseded=True,
                operating_comparisons=comparisons,selection=selection,aligned_rescue_differences=rescue,
                exploratory_slices_are_not_policy_selection=True,policy_tuning=False)
    target.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps([x for x in comparisons if x['meet']==0]))

if __name__=='__main__':main()

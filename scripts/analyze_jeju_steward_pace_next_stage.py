"""Frozen-score error decomposition and next-start report association, no fitting."""
import hashlib
import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_steward_pace_diagnosis_20260917'
P=ROOT/'data/research/jeju_tempo_pace_pilot_20260917'
F=ROOT/'data/research/jeju_tempo_pace_features_20260917'
S=ROOT/'data/research/jeju_steward_events_v1_20260917'


def save(name,x):
    (OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str,allow_nan=False))


def finite_mean(values):
    xs=[x for x in values if x is not None and np.isfinite(x)]
    return float(np.mean(xs)) if xs else None


def summarize(group):
    return dict(entries=len(group),horses=len({r['horse_id'] for r in group}),
        days=len({r['event_date'] for r in group}),
        top3=sum(r['y'] for r in group),actual_rate=finite_mean([r['y'] for r in group]),
        mean_probability=finite_mean([r['p'] for r in group]),
        mean_residual=finite_mean([r['y']-r['p'] for r in group]))


def boot(rows,field,nonpodium=False):
    pool=[r for r in rows if r['previous_report_known'] and (not nonpodium or r['previous_nonpodium'])]
    exposed=[r for r in pool if r[field]];reference=[r for r in pool if not r['previous_explicit_event']]
    result=dict(exposed=summarize(exposed),no_extracted_event=summarize(reference),
        comparison='No extracted event is not a clean-trip label; observational, unadjusted multiplicity.')
    days=sorted({r['event_date'] for r in pool});dayix={d:i for i,d in enumerate(days)}
    totals=np.zeros((len(days),4))
    for col,g in [(0,exposed),(2,reference)]:
        for r in g:
            i=dayix[r['event_date']];totals[i,col]+=r['y']-r['p'];totals[i,col+1]+=1
    ix=np.random.default_rng(17).integers(0,len(days),(5000,len(days)))
    sampled=totals[ix].sum(axis=1)
    valid=(sampled[:,1]>0)&(sampled[:,3]>0)
    if len(exposed) and len(reference):
        e=sampled[valid,0]/sampled[valid,1];c=sampled[valid,2]/sampled[valid,3]
        result.update(exposed_residual_ci95=np.quantile(e,[.025,.975]).tolist(),
                      residual_difference=result['exposed']['mean_residual']-result['no_extracted_event']['mean_residual'],
                      difference_ci95=np.quantile(e-c,[.025,.975]).tolist())
    return result


def main():
    OUT.mkdir(exist_ok=False)
    obs=pl.read_parquet(F/'observations.parquet')
    allobs={r['entry_id']:r for r in obs.to_dicts()}
    lookup={(r['race_id'],r['horse_id']):r for r in allobs.values()}
    features={r['entry_id']:r for r in pl.read_parquet(F/'features.parquet').to_dicts()}
    steward={r['entry_id']:r for r in pl.read_parquet(S/'features.parquet').to_dicts()}
    races=pl.read_parquet(P/'race_predictions.parquet')
    base={r['race_id']:r for r in races.filter(pl.col('model')=='BASE__BASE').to_dicts()}
    pace={r['race_id']:r for r in races.filter(pl.col('model')=='PACE__BASE').to_dicts()}
    predictions=pl.read_parquet(P/'frozen_scores.parquet')
    ranks={}
    for (m,rid),g in predictions.filter(pl.col('model').is_in(['BASE__BASE','PACE__BASE'])).partition_by(['model','race_id'],as_dict=True).items():
        ids=g.sort(['score','horse_id'],descending=[True,False])['horse_id'].to_list()
        ranks[(m,rid)]={h:i+1 for i,h in enumerate(ids)}
    changes=[];swaps=[]
    for rid,b in base.items():
        p=pace[rid];bs=set(b['predicted_set']);ps=set(p['predicted_set'])
        category='both_hit' if b['set_hit'] and p['set_hit'] else 'new_hit' if p['set_hit'] else 'lost_hit' if b['set_hit'] else 'both_miss'
        actual={r['horse_id'] for r in allobs.values() if r['race_id']==rid and r['outcome_status']=='normal_completed' and r['finish_position'] in (1,2,3)}
        changes.append(dict(race_id=rid,event_date=b['event_date'],category=category,changed=bs!=ps,
            base_set=sorted(bs),pace_set=sorted(ps),actual_podium=sorted(actual),
            base_overlap=len(bs&actual),pace_overlap=len(ps&actual),
            base_missed_ranks=[ranks[('BASE__BASE',rid)][h] for h in actual-bs],
            pace_missed_ranks=[ranks[('PACE__BASE',rid)][h] for h in actual-ps]))
        for side,ids in [('added',ps-bs),('removed',bs-ps)]:
            for h in ids:
                r=lookup[(rid,h)];f=features[r['entry_id']];s=steward[r['entry_id']]
                swaps.append(dict(race_id=rid,event_date=b['event_date'],category=category,side=side,
                    entry_id=r['entry_id'],horse_id=h,horse_number=r['horse_number'],distance_m=r['distance_m'],
                    official_top3=h in actual,finish=r['finish_position'],c4_rank=r['c4_rank'],
                    actual_late_podium=(h in actual and r['c4_rank'] is not None and r['c4_rank']>=4),
                    base_rank=ranks[('BASE__BASE',rid)][h],pace_rank=ranks[('PACE__BASE',rid)][h],
                    past_c4_finish_gain=f['pace_c4_finish_gain_3'],past_c4_quality=f['pace_c4_quality_3'],
                    past_early_gap=f['pace_early_gap_3'],past_front_fade=f['pace_front_fade_3'],
                    previous_explicit_event=s['previous_explicit_event']))
    pl.from_dicts(changes).write_parquet(OUT/'race_changes.parquet')
    pl.from_dicts(swaps,infer_schema_length=None).write_parquet(OUT/'selection_swaps.parquet')
    summary={}
    for cat in ['both_hit','new_hit','lost_hit','both_miss']:
        rs=[r for r in changes if r['category']==cat]
        summary[cat]=dict(races=len(rs),changed_sets=sum(r['changed'] for r in rs))
    summary['swaps']={}
    for cat in ['new_hit','lost_hit','all']:
        for side in ['added','removed']:
            g=[r for r in swaps if r['side']==side and (cat=='all' or r['category']==cat)]
            summary['swaps'][cat+'_'+side]=dict(entries=len(g),top3=sum(r['official_top3'] for r in g),
                actual_late_podium=sum(r['actual_late_podium'] for r in g),
                previous_explicit_event=sum(r['previous_explicit_event'] is True for r in g),
                **{k:finite_mean([r[k] for r in g]) for k in ['base_rank','pace_rank','past_c4_finish_gain','past_c4_quality','past_early_gap','past_front_fade']})
    for model in ['base','pace']:
        missed=[x for r in changes for x in r[model+'_missed_ranks']]
        summary[model+'_missed_podium']=dict(total=len(missed),rank4or5=sum(x in (4,5) for x in missed),rank6plus=sum(x>=6 for x in missed))
    save('pace_summary.json',summary)
    # Same frozen marginal probabilities, no refitting and no posthoc probability uplift.
    rows=[]
    for r in pl.read_parquet(P/'horse_predictions.parquet').filter(pl.col('model')=='BASE__BASE').to_dicts():
        o=lookup[(r['race_id'],r['horse_id'])];s=steward[o['entry_id']]
        previous=allobs.get(s['previous_entry_id'])
        rows.append({**r,**s,'event_date':o['event_date'],
            'previous_nonpodium':bool(previous and previous['outcome_status']=='normal_completed' and previous['finish_position']>3)})
    pl.from_dicts(rows,infer_schema_length=None).write_parquet(OUT/'next_start_frozen_probabilities.parquet')
    associations={}
    for field in ['previous_explicit_event','previous_route_restriction','previous_wide_trip','previous_running_interference']:
        associations[field]=boot(rows,field)
        associations[field+'_previous_nonpodium']=boot(rows,field,True)
    save('next_start_associations.json',associations)
    save('coverage.json',dict(evaluation_entries=len(rows),known_previous_report=sum(r['previous_report_known'] for r in rows),
                             no_previous_report=sum(not r['previous_report_known'] for r in rows)))
    def sha(p):
        with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    save('manifest.json',dict(files={p.name:sha(p) for p in OUT.iterdir()},parents={str(x):sha(x) for x in [P/'manifest.json',S/'manifest.json',F/'manifest.json']}))
    print(json.dumps(summary,ensure_ascii=False))
    print(json.dumps(associations,ensure_ascii=False))


if __name__=='__main__':main()

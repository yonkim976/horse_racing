"""Descriptive debut-history and official grade strata; never pick models by subgroup."""
import hashlib,json,sqlite3
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
import polars as pl

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_debut_diagnosis_20260919'
MODEL=ROOT/'data/research/jeju_accuracy_candidates_20260919'
DATA=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'
DB=ROOT/'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False))
def summarize(rows):
    n=len(rows)
    return dict(races=n,days=len({r['event_date'] for r in rows}),**{k:sum(r[k] for r in rows) for k in ['pick_hit','set_hit','order_hit']},
        **{k+'_rate':sum(r[k] for r in rows)/n for k in ['pick_hit','set_hit','order_hit']},
        mean_field_size=sum(r['field_size'] for r in rows)/n,distance_counts=dict(Counter(r['distance_m'] for r in rows)),
        overlap_counts=dict(Counter(r['compatible_max_overlap'] for r in rows)))
def main():
    OUT.mkdir(exist_ok=False)
    pred=pl.read_parquet(MODEL/'race_predictions.parquet').to_dicts();target={r['race_id'] for r in pred}
    states=pl.read_parquet(DATA/'horse_states.parquet').filter(pl.col('race_id').is_in(target)).to_dicts()
    by_race=defaultdict(list);by_horse={}
    for r in states:by_race[r['race_id']].append(r);by_horse[(r['race_id'],r['horse_id'])]=r
    race_meta={r['race_id']:r for r in pl.read_parquet(DATA/'races.parquet').filter(pl.col('race_id').is_in(target)).to_dicts()}
    c=sqlite3.connect(f'file:{DB}?mode=ro',uri=True);c.row_factory=sqlite3.Row
    events={r['id']:dict(r) for r in c.execute("SELECT id,grade,event_name,event_date FROM event WHERE event_type='race' AND event_date BETWEEN '20240101' AND '20260912'")}
    cond=defaultdict(set)
    for r in c.execute("""SELECT v.id,json_extract(s.normalized_json,'$.ageCond') age_cond,json_extract(s.normalized_json,'$.prizeCond') prize_cond
       FROM event v JOIN entry e ON e.event_id=v.id JOIN source_row s ON s.id=e.source_row_id
       WHERE v.event_type='race' AND v.event_date BETWEEN '20240101' AND '20260912'"""):
        cond[r['id']].add((r['age_cond'],r['prize_cond']))
    c.close()
    meta=[];lookup={}
    for rid in sorted(target):
        rows=by_race[rid];n=len(rows);zero=sum(r['starts_pre']==0 for r in rows)
        assert n==race_meta[rid]['field_size']
        grade=events[rid]['grade'];assert len(cond[rid])==1
        age_cond,prize_cond=next(iter(cond[rid]))
        row=dict(race_id=rid,year=race_meta[rid]['event_date'].year,event_date=race_meta[rid]['event_date'],
          field_size=n,distance_m=race_meta[rid]['distance_m'],grade=grade,age_condition=age_cond,prize_condition=prize_cond,
          grade_group='grade6' if grade=='제6등급' else 'unknown' if not grade else 'other_grade',
          history_group='has_zero_history' if zero else 'all_have_history',zero_history_count=zero,zero_history_share=zero/n,
          all_zero_history=zero==n,boundary_tie=race_meta[rid]['boundary_tie'],
          mean_previous_starts=float(np.mean([r['starts_pre'] for r in rows])),
          missing_section_share=float(np.mean([r['section_g1f_ms_mean_pre'] is None for r in rows])))
        meta.append(row);lookup[rid]=row
    save('race_classification.json',meta)
    rows=[dict(**r,**{k:v for k,v in lookup[r['race_id']].items() if k not in r},
          pick_history_group='zero' if by_horse[(r['race_id'],r['pick_horse_id'])]['starts_pre']==0 else 'experienced') for r in pred]
    save('classified_predictions.json',rows)
    summary=[]
    for year in [2024,2025,2026,'ALL']:
        for model in ['BASE','PACE','NO_GROWTH']:
            g=[r for r in rows if (year=='ALL' or r['year']==year) and r['model']==model]
            for axis in ['history_group','grade_group','pick_history_group','cross']:
                groups=defaultdict(list)
                for r in g:groups[(r['grade_group']+'__'+r['history_group']) if axis=='cross' else r[axis]].append(r)
                for label,rr in sorted(groups.items()):summary.append(dict(year=year,model=model,axis=axis,group=label,**summarize(rr)))
    save('subgroup_summary.json',summary)
    horse_rows=[]
    for h in pl.read_parquet(MODEL/'horse_predictions.parquet').to_dicts():
        st=by_horse[(h['race_id'],h['horse_id'])];count=st['starts_pre']
        horse_rows.append(dict(**h,experience='zero' if count==0 else 'one_to_three' if count<=3 else 'four_plus',
            boundary_tie=lookup[h['race_id']]['boundary_tie'],event_date=lookup[h['race_id']]['event_date'],
            brier=(h['p']-h['y'])**2))
    hs=[]
    for year in [2024,2025,2026,'ALL']:
        for model in ['BASE','PACE','NO_GROWTH']:
            for exp in ['zero','one_to_three','four_plus']:
                rr=[r for r in horse_rows if (year=='ALL' or r['year']==year) and r['model']==model and r['experience']==exp and not r['boundary_tie']]
                if rr:hs.append(dict(year=year,model=model,experience=exp,entries=len(rr),races=len({r['race_id'] for r in rr}),
                    mean_probability=float(np.mean([r['p'] for r in rr])),actual_top3=float(np.mean([r['y'] for r in rr])),brier=float(np.mean([r['brier'] for r in rr]))))
    save('horse_experience_summary.json',hs)
    # Same date resampling for both groups; original year shares retained separately per group.
    base=[r for r in rows if r['model']=='BASE'];contrasts=[]
    for metric in ['pick_hit','set_hit','order_hit']:
        totals={'has_zero_history':np.zeros(5000),'all_have_history':np.zeros(5000)};counts=Counter();rng=np.random.default_rng(17)
        for year in [2024,2025,2026]:
            rr=[r for r in base if r['year']==year];days=sorted({r['event_date'] for r in rr});ix=rng.integers(0,len(days),(5000,len(days)))
            for label in totals:
                g=[r for r in rr if r['history_group']==label];count=np.array([sum(r['event_date']==d for r in g) for d in days]);wins=np.array([sum(r[metric] for r in g if r['event_date']==d) for d in days])
                den=count[ix].sum(axis=1);assert np.all(den>0)
                totals[label]+=wins[ix].sum(axis=1)/den*len(g);counts[label]+=len(g)
        samples=totals['has_zero_history']/counts['has_zero_history']-totals['all_have_history']/counts['all_have_history']
        actual={g:float(np.mean([r[metric] for r in base if r['history_group']==g])) for g in totals}
        contrasts.append(dict(metric=metric,contrast='has_zero_history minus all_have_history',difference=actual['has_zero_history']-actual['all_have_history'],
            simultaneous95_3metrics=np.quantile(samples,[.025/3,1-.025/3]).tolist(),interpretation='descriptive groups, no distance/grade/field-size causal adjustment'))
    save('history_group_contrasts.json',contrasts)
    save('coverage.json',dict(races=len(meta),entries=len(states),all_zero_history_races=sum(r['all_zero_history'] for r in meta),
        grade_counts=dict(Counter(r['grade'] for r in meta)),grade6_conditions=dict(Counter(str((r['age_condition'],r['prize_condition'])) for r in meta if r['grade_group']=='grade6')),
        boundary_tie_races_excluded_from_horse_probability_metrics=sum(r['boundary_tie'] for r in meta),
        official_new_horse_only_race_status='not established from available headers; zero-history is an observational proxy, grade6 is separate'))
    inputs=[Path(__file__),DB,MODEL/'prediction_lock.json',MODEL/'race_predictions.parquet',MODEL/'horse_predictions.parquet',DATA/'horse_states.parquet',DATA/'races.parquet']
    save('manifest.json',dict(inputs={str(p.relative_to(ROOT)):sha(p) for p in inputs},outputs={p.name:sha(p) for p in OUT.iterdir()}))
    print(json.dumps([r for r in summary if r['model']=='BASE' and r['axis'] in ['history_group','grade_group']],ensure_ascii=False))
    print(json.dumps(contrasts,ensure_ascii=False))
if __name__=='__main__':main()

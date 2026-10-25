"""Read-only references and fixed contracts for a single Busan axis study."""
from pathlib import Path
from datetime import datetime,timezone
import sys,json
import torch
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];R=HERE.parent;OUT=HERE/'outputs'
PREV=R/'20261022_dynamic_race_model_v1'
sys.path.insert(0,str(PREV))
import common as old

KEY=old.KEY
AXIS=['history_count','days_since_last','section_same_distance_n5','front_gate_probability',
      'dirgate_inner_faster_n','dirgate_outer_faster_n','rolelate_front_fade_mean5','state_rank_current_sd']
DIFF=['history_count','days_since_last','section_same_distance_n5','moist_last3_record_index_mean',
      'profile_trend','front_gate_probability','section_last600_mean3','section_late_mean3','style_fade_mean5',
      'state_rank_current','state_rank_current_sd','state_form_trend','state_close_mean',
      'current_vs_previous_carried_weight','promoted','distance_change']
FEATURES=['distance_m','grade_level','field_size','axis_score','score_gap']+['axis_'+x for x in AXIS]+['diff_'+x for x in DIFF]
assert len(FEATURES)==29

def sha(path):return old.sha(path)
def save(path,value):
    path=Path(path);assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def target(f):return f.meet.eq(3)&f.grade_raw.eq('국5등급')&f.distance_m.isin([1300,1600])

def freeze():
    paths=[HERE/'PLAN.md',*sorted(HERE.glob('*.py')),old.DB,old.HISTORY,
        old.base.SOURCE/'features.parquet',old.base.SOURCE/'feature_contract.json',
        old.base.ABILITY/'research_baseline_selection.json',old.BASE/'run.py',old.BASE/'probability.py',
        old.BASE/'evaluate.py',old.BASE/'config.json',PREV/'common.py',PREV/'state.py',
        PREV/'outputs/state_features.parquet',PREV/'outputs/state_contract.json',
        PREV/'outputs/race_metrics.parquet',PREV/'outputs/runner_probabilities.parquet',
        PREV/'outputs/tickets.parquet',ROOT/'config/prediction_model_registry.json']
    for year in [2024,2025,2026]:
        folder=PREV/'outputs/models'/f'state_gbm_3_{year}'
        paths += [folder/'metadata.json',folder/'scores.parquet',folder/'model.txt']
    data={str(p.relative_to(ROOT)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in paths}
    assert not (OUT/'input_manifest.json').exists()
    save(OUT/'input_manifest.json',data)
    save(OUT/'protocol_frozen.json',{'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'target_selected_after_previous_development_results':True,'new_experiment_not_run':True,
        'features':FEATURES,'ridge':.1,'switch_threshold':.05,'base_models_trained':0,'fits':6})
    names=['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']
    save(OUT/'preexisting_files.json',{str((R/n).relative_to(ROOT)):{'sha256':sha(R/n),'bytes':(R/n).stat().st_size} for n in names})

def check():
    for p,v in json.loads((OUT/'input_manifest.json').read_text()).items():assert sha(ROOT/p)==v['sha256'],p

def storage():
    total=sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file())
    assert total+139_039_058<300_000_000
    return total

def frame():
    f=old.frame();h=f[['horse_id','race_date','grade','distance_m']].copy()
    assert not h.duplicated(['horse_id','race_date']).any()
    h=h.rename(columns={'race_date':'previous_source_date','grade':'previous_grade','distance_m':'previous_distance'})
    left=f[['row_number','horse_id','cutoff_date']].sort_values('cutoff_date')
    right=h.sort_values('previous_source_date')
    previous=pd.merge_asof(left,right,left_on='cutoff_date',right_on='previous_source_date',by='horse_id',direction='backward')
    previous=previous.sort_values('row_number').reset_index(drop=True)
    assert (previous.row_number.to_numpy()==f.row_number.to_numpy()).all()
    for name in ['previous_source_date','previous_grade','previous_distance']:f[name]=previous[name]
    f['promoted']=(f.previous_grade>f.grade).astype(float).where(f.previous_grade.notna()&f.grade.notna())
    f['distance_change']=f.distance_m-f.previous_distance
    assert (f.previous_source_date.isna()|f.previous_source_date.le(f.cutoff_date)).all()
    return f

def paired(df,choice):
    base=df.axis_hit.to_numpy(float);candidate=df[choice].to_numpy(float)
    dates,ix=np.unique(df.race_date,return_inverse=True);nn=np.bincount(ix)
    aa=np.bincount(ix,weights=candidate);bb=np.bincount(ix,weights=base)
    draws=np.random.default_rng(20261025).integers(0,len(dates),size=(2000,len(dates)))
    am=aa[draws].sum(1)/nn[draws].sum(1);bm=bb[draws].sum(1)/nn[draws].sum(1)
    return {'races':len(df),'dates':len(dates),'baseline_hits':int(base.sum()),'candidate_hits':int(candidate.sum()),
        'baseline_rate':float(base.mean()),'candidate_rate':float(candidate.mean()),
        'gained':int(((base==0)&(candidate==1)).sum()),'lost':int(((base==1)&(candidate==0)).sum()),
        'net_hits':int((candidate-base).sum()),'difference':float((candidate-base).mean()),
        'difference_ci95':np.quantile(am-bm,[.025,.975]).tolist(),
        'relative_percent':float((candidate.mean()/base.mean()-1)*100),
        'relative_ci95':np.quantile((am/bm-1)*100,[.025,.975]).tolist()}

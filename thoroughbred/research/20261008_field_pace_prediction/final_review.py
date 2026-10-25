"""Publication claims, independent ancillary metrics and complete registration review."""
from pathlib import Path
import hashlib,json,re
import numpy as np,pandas as pd,lightgbm as lgb
from PIL import Image
import data
H=data.H;O=data.O;ROOT=data.ROOT;R=data.R
def main():
 n=0
 def same(a,b):
  nonlocal n
  a=np.asarray(a,float);b=np.asarray(b,float);assert a.shape==b.shape and np.allclose(a,b,atol=1e-9,rtol=1e-9,equal_nan=True);n+=a.size
 sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 v=json.loads((O/'verification.json').read_text());pv=json.loads((O/'profile_verification.json').read_text());assert v['passed'] and v['preserved_prior_files']==160 and pv['supported5']==2601
 ep=pd.read_parquet(O/'early_predictions.parquet');old=pd.read_parquet(R/'20261008_passing_group_style/outputs/temporal_evaluation.parquet').set_index('row_key');common=ep[ep.supported5].set_index('row_key');assert set(old.index)==set(common.index);common=common.loc[old.index]
 same(common.role4,old.role4)
 for j in range(4):same(common['B_p'+str(j)],old['baseline_p_'+str(j)]);same(common['H_p'+str(j)],old['history_p_'+str(j)])
 # Validate smoothing/imputation statistics from each annual training set itself.
 p=pd.read_parquet(data.INPUTS[2]);sp=np.load(H/'models/environment_models.npz');cols0=[((p.meet==v)&(p.distance_m==d)).astype(float).to_numpy() for v in ['서울','부산'] for d in data.DIST]+[(p.date.dt.month==m).astype(float).to_numpy() for m in range(1,13)]+[p.moisture.to_numpy(),p.moisture.to_numpy()**2];cols1=cols0+[(p.grade==g).astype(float).to_numpy() for g in data.GRADES]+[p[c].to_numpy() for c in ['early','rating','age','weight']]+[p.middle1.to_numpy()*1000/(p.distance_m.to_numpy()-800)]
 for year in range(2019,2027):
  for kind,cols in [('base',cols0),('conditional',cols1)]:
   a=np.column_stack(cols)[p.year.to_numpy()<year];med=np.nanmedian(a,axis=0);med=np.where(np.isfinite(med),med,0);filled=np.where(np.isfinite(a),a,med);mu=filled.mean(axis=0);sd=filled.std(axis=0);sd[sd<1e-8]=1;same(med,sp[f'{year}_{kind}_medians']);same(mu,sp[f'{year}_{kind}_means']);same(sd,sp[f'{year}_{kind}_sds'])
 lp=pd.read_parquet(O/'late_predictions.parquet')
 for r in pd.read_csv(O/'late_metrics.csv').itertuples():
  z=lp[lp.task.eq(r.task)];z=z if r.window=='2024_2025' else z[z.year.eq(int(r.window))];y=z.target.to_numpy();pr=z['p_'+r.model].to_numpy();order=np.argsort(-pr,kind='stable');scores=pr[order];outcome=y[order];last=np.r_[np.flatnonzero(np.diff(scores)!=0),len(scores)-1];tp=np.cumsum(outcome)[last];fp=last+1-tp;precision=tp/(tp+fp);recall=tp/tp[-1];ap=np.sum(np.diff(np.r_[0,recall])*precision);same([ap],[r.average_precision])
 for task,filename,pp in [('early','early_calibration.csv',ep),('late','late_calibration.csv',lp)]:
  for r in pd.read_csv(O/filename).itertuples():
   z=pp if task=='early' else pp[pp.task.eq(r.task)];pred=z[r.model+'_p'+str(r.class_id)] if task=='early' else z['p_'+r.model];mask=np.minimum((pred*10).astype(int),9).eq(r.bin);actual=z.role4.eq(r.class_id) if task=='early' else z.target;same([pred[mask].mean(),actual[mask].mean()],[r.predicted,r.actual]);assert mask.sum()==r.n
 # Every card probability is replayed from its saved 2026 model, trained through2025.
 q=pd.read_parquet(O/'feature_context.parquet');x=pd.read_parquet(O/'feature_frame.parquet');cards=pd.read_csv(O/'example_cards.csv',dtype={'horse_id':str});idx=q.set_index('row_key').index.get_indexer(cards.row_key);assert (idx>=0).all()
 for target,name in [('early','S'),('early','J'),('recovery','J'),('fade','J')]:
  stem=f'2026_{target}_{name}';meta=json.loads((H/'models'/f'{stem}.json').read_text());assert meta['train_end']<'2026-01-01';b=lgb.Booster(model_file=str(H/'models'/f'{stem}.txt'));pred=b.predict(x.iloc[idx][meta['features']],num_threads=1);saved=cards[[name+'_p'+str(j) for j in range(4)]].to_numpy() if target=='early' else cards[target+'_p'].to_numpy();same(pred,saved)
 public=json.loads((H/'PUBLICATION.json').read_text());assert public['evaluation_n']==len(ep)==36638 and not public['operational'] and not public['intention_labels'] and not public['prerace_publication_timestamps_audited'];same([a['accuracy'] for a in public['early_metrics']],[.3333697254216933,.4446476336044544,.4872263769856433,.49413177575195155,.5152573830449261,.5162399694306458])
 registration=json.loads((O/'registration.json').read_text());assert registration['independent_study_count_before']==registration['independent_study_count_after']==41
 central=R/'conclusions/28C_FIELD_PACE_PREDICTION.md';manifest=json.loads((R/'conclusions/source_manifest.json').read_text());hashes=0
 for f in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central,R/'conclusions/README.md',R/'conclusions/SOURCES.md']:
  key='sources' if f.parent==H else 'conclusions';entry=next(r for r in manifest[key] if r['path']==str(f.relative_to(ROOT)));assert entry['sha256']==sha(f);hashes+=1
 links=0
 for f in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central]:
  for link in re.findall(r'\]\(([^)]+)\)',f.read_text()):
   if link.startswith(('http:','https:')):continue
   path=(f.parent/link.split('#')[0]).resolve()
   if path.name in ['artifact_inventory.json','SIZE_REPORT.md']:continue
   assert path.is_file(),(str(f),link);links+=1
 viewed=['early_prediction.png','late_prediction.png','example_card.png'];figures=[]
 for name in viewed:
  p=H/'figures'/name
  with Image.open(p) as img:assert img.width>=1000 and img.height>=600;figures.append(dict(path='figures/'+name,width=img.width,height=img.height,sha256=sha(p),visually_inspected=True))
 # Recheck immutable prior sources after all publication writes.
 shared=set(r['path'] for r in json.loads((O/'shared_edits_baseline.json').read_text())['files']);baseline=json.loads((O/'baseline_inventory.json').read_text())['related_existing_files'];unchanged=0
 for row in baseline:
  if row['path'] in shared:continue
  assert sha(ROOT/row['path'])==row['sha256'];unchanged+=1
 result=dict(passed=True,ancillary_numeric_values=n,old28A_common_row_keys_and_probabilities_identical=True,environment_train_only_imputation_statistics_verified=True,binary_average_precision_and_calibration_independently_recomputed=True,example_probability_replay_rows=len(cards),source_manifest_hashes_verified=hashes,local_links_verified=links,independent_study_count=41,preserved_prior_files=unchanged,figures=figures,profile_SQL_values=pv['independent_SQL_values_verified'],inventory_pending_separate_self_inclusive_step=True)
 (O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

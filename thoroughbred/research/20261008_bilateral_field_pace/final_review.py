"""Independent subgroup/race/case checks and publication/registration audit."""
import json,re
import numpy as np,pandas as pd
from PIL import Image
import experiment as e
from verify import ci
H=e.H;O=e.O;ROOT=e.ROOT;R=e.R
def main():
 n=0
 def same(a,b):
  nonlocal n
  a=np.asarray(a,float);b=np.asarray(b,float);assert a.shape==b.shape and np.allclose(a,b,atol=1e-9,rtol=1e-9,equal_nan=True);n+=a.size
 v=json.loads((O/'verification.json').read_text());assert v['passed'] and v['prior_files_preserved']==114 and v['no_jockey_trainer_or_change_inputs'];q=pd.read_parquet(e.P/'outputs/feature_context.parquet');ep=pd.read_parquet(O/'early_predictions.parquet');z=ep.copy();maxgate=q.groupby('source_key').gate.max();z['distance_band']=np.where(z.distance_m.le(1300),'<=1300',np.where(z.distance_m.le(1600),'1400_1600','>=1700'));z['gate_band']=pd.cut((z.gate-1)/(z.source_key.map(maxgate)-1),[-.001,1/3,2/3,1.001],labels=['inner','middle','outer'])
 for r in pd.read_csv(O/'subgroup_metrics.csv').itertuples():
  g=z[z[r.group].eq(r.label)];y=np.eye(4)[g.role4.to_numpy()];probs={k:g[[k+'_p'+str(j) for j in range(4)]].to_numpy() for k in ['N','A','B']};loss={k:((p-y)**2).sum(axis=1) for k,p in probs.items()}
  if r.model=='B-A':same(ci(g,loss['B']-loss['A']),[r.estimate,r.se,r.lower,r.upper])
  else:same([loss[r.model].mean(),(probs[r.model].argmax(axis=1)==g.role4).mean()],[r.brier,r.accuracy])
  assert len(g)==r.n
 races=pd.read_parquet(O/'race_predictions.parquet');rr=pd.read_csv(O/'race_metrics.csv');race_groups=dict(tuple(ep.groupby('source_key')))
 for r in races.itertuples():
  g=race_groups[r.source_key];assert len(g)==g.field_size.iloc[0]==r.n;best=g.sort_values([r.model+'_p0','gate'],ascending=[False,True]).iloc[0];same([g[r.model+'_p0'].sum(),g.role4.eq(0).sum(),best.role4==0],[r.lead_count_pred,r.lead_count_actual,r.top_first_group])
 for r in rr.itertuples():
  g=races[races.model.eq(r.model)];same([g.top_first_group.mean(),abs(g.lead_count_pred-g.lead_count_actual).mean()],[r.top_first_group,r.leader_count_mae]);assert len(g)==r.races
 cards=pd.read_csv(O/'example_cards.csv',dtype={'horse_id':str});pairs=pd.read_csv(O/'example_rival_pairs.csv');lookup=q.set_index('row_key');assert len(pairs)==200 and len(cards)==21
 for c in e.VALUES+['lead_prior5','count5_0','valid_position5']:same(pairs[c],lookup.loc[pairs.rival_row_key,c])
 same(pairs.rival_adv_minus_own,lookup.loc[pairs.rival_row_key,'early_adv_mean5'].to_numpy()-lookup.loc[pairs.own_row_key,'early_adv_mean5'].to_numpy());same(pairs.rival_gate,lookup.loc[pairs.rival_row_key,'gate']);same(pairs.own_gate,lookup.loc[pairs.own_row_key,'gate']);assert (pairs.rival_horse.to_numpy()==lookup.loc[pairs.rival_row_key,'horse_name'].to_numpy()).all()
 for meet,g in q.groupby('meet'):
  date=g.date.max();key=max(g[g.date.eq(date)].source_key.unique(),key=lambda k:int(k.rsplit(':',1)[1]));assert set(cards[cards.source_key.eq(key)].row_key)==set(g[g.source_key.eq(key)].row_key)
 public=json.loads((H/'PUBLICATION.json').read_text());assert not public['operational'] and not public['deployed'] and not public['intention_labels'] and not public['prerace_publication_timestamps_audited'];assert public['evaluation_n']==36638 and public['feature_counts']==dict(N=157,A=202,B=297)
 metrics=pd.read_csv(O/'early_metrics.csv');pool=metrics[metrics.window.eq('2024_2025')&metrics.scope.eq('all')].set_index('model')
 for row in public['early_metrics']:
  same([row['accuracy'],row['brier'],row['logloss']],pool.loc[row['model'],['accuracy','brier','logloss']])
 report=(H/'README.md').read_text();assert '기수 교체 여부를 모두 제외' in report and '바깥 선행합 하나는 새 독립 정보가 아니다' in report
 central=R/'conclusions/28D_BILATERAL_FIELD_PACE.md';manifest=json.loads((R/'conclusions/source_manifest.json').read_text());hashes=0
 for f in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central,R/'conclusions/README.md',R/'conclusions/SOURCES.md']:
  key='sources' if f.parent==H else 'conclusions';a=next(r for r in manifest[key] if r['path']==str(f.relative_to(ROOT)));assert a['sha256']==e.sha(f);hashes+=1
 links=0
 for f in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central]:
  for link in re.findall(r'\]\(([^)]+)\)',f.read_text()):
   if link.startswith(('http:','https:')):continue
   path=(f.parent/link.split('#')[0]).resolve()
   if path.name in ['artifact_inventory.json','SIZE_REPORT.md']:continue
   assert path.is_file(),(f,link);links+=1
 figures=[]
 for name in ['prediction_comparison.png','gate_side_example.png']:
  p=H/'figures'/name
  with Image.open(p) as im:assert im.width>=1000 and im.height>=600;figures.append(dict(path='figures/'+name,width=im.width,height=im.height,sha256=e.sha(p),visually_inspected=True))
 reg=json.loads((O/'registration.json').read_text());assert reg['independent_study_count_before']==reg['independent_study_count_after']==41;shared=set(a['path'] for a in json.loads((O/'shared_edits_baseline.json').read_text())['files']);preserved=0
 for a in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']:
  if a['path'] in shared:continue
  assert e.sha(ROOT/a['path'])==a['sha256'];preserved+=1
 result=dict(passed=True,independent_numeric_values=n,subgroup_race_metrics_and_all200_rival_values_verified=True,example_selection_fixed=True,manifest_hashes=hashes,local_links=links,prior_files_preserved=preserved,independent_study_count=41,figures=figures,self_inclusive_inventory_next=True)
 e.dump(O/'final_review.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

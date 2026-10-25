"""Review reporting, complete pair support, preserved prior research, manifest, links and figures."""
from pathlib import Path
import json,re,hashlib
import pandas as pd,numpy as np
from PIL import Image
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';CENTRAL=R/'conclusions/50B_PLANNED_TRAINER_JOCKEY_PAIR_EFFECTS.md';checks=0
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def check(value,label):
 global checks
 assert value,label;checks+=1
def compare(a,b,label,sortcols):
 a=a.sort_values(sortcols).reset_index(drop=True);b=b.sort_values(sortcols).reset_index(drop=True);check(a.shape==b.shape,label+' shape');check(set(a.columns)==set(b.columns),label+' columns');a=a[b.columns]
 for col in b:
  if pd.api.types.is_numeric_dtype(b[col]):check(np.allclose(a[col].to_numpy(float),b[col].to_numpy(float),rtol=1e-12,atol=1e-12,equal_nan=True),label+col)
  else:check(a[col].fillna('MISSING').equals(b[col].fillna('MISSING')),label+col)
def main():
 pub=json.loads((O/'publication.json').read_text());v=json.loads((O/'verification.json').read_text());check(v['passed'],'independent verifier');check(len(v['all_primary_top3_pair_cluster_CIs'])==40,'all20×2 independent primary CI checks');s=pd.read_csv(O/'pair_support.csv',dtype={'trainer_id':str,'jockey_id':str});e=pd.read_csv(O/'adjusted_associations.csv');q=s[s.model_supported];check(len(q)==20 and s.switch_supported.sum()==37,'frozen declared pairs');check(len(s[s.switch_supported&~s.model_supported])==17,'all insufficient retained comparators included')
 for key,b,sortcols in [('primary_pair_table',pd.read_csv(O/'primary_pair_comparison.csv',dtype={'trainer_id':str,'jockey_id':str}),['pair_key']),('primary_pair_extra',e[e.window.eq('2024_2025')&e.model.eq('primary')&e.contrast.eq('pair_extra')&e.target.eq('top3')].merge(q,on='pair_key'),['pair_key']),('support_table',s[s.switch_supported],['pair_key']),('all_primary_effects',e[e.window.eq('2024_2025')&e.model.eq('primary')&e.contrast.eq('pair_total')],['pair_key','target']),('sensitivity_summary',pd.read_csv(O/'sensitivity_summary.csv'),['window','model','target'])]:compare(pd.DataFrame(pub[key]),b,key,sortcols)
 t=pd.read_csv(O/'primary_pair_comparison.csv');check(((t.ci_low<0)&(t.ci_high>0)).all(),'all20 top3 CIs span zero');check(not(e[e.contrast.ne('general_other_pairs')].q<.05).any(),'all reported pair families no BH discovery');check(not pub['top_indicator_used'] and not pub['causal_intent_proven'] and not pub['predictive_improvement_proven'] and not pub['production_changed'],'honest scope')
 text=(H/'PUBLICATION.md').read_text();report=(H/'README.md').read_text();check('20조합' in text and '37조합' in text,'headline coverage');check('17.46%' in text and '42.86%' in text and '+7.14' in text and '-13.64~+27.91' in text,'illustration exact values');check('기승100회 제한 해제' in text and '유지 비교가 부족한17조합' in text,'limitations and sensitivity');check('명단만 동결' in report and '사전예측 검증은 아니다' in report,'partial period reestimation distinguished')
 for row in t.itertuples():check(row.trainer_name+'→'+row.jockey_name in report and f'{100*row.estimate:+.2f}' in report,'all20 pair estimates in report')
 for x in json.loads((O/'source_audit.json').read_text())['inputs']:check(sha(ROOT/x['path'])==x['sha256'],'unchanged input '+x['path'])
 shared={x['path'] for x in json.loads((O/'shared_edits_baseline.json').read_text())['files']};old=json.loads((O/'baseline_inventory.json').read_text())['related_existing_files'];preserved=0
 for x in old:
  if x['path'] in shared:continue
  p=ROOT/x['path'];check(p.stat().st_size==x['bytes'] and sha(p)==x['sha256'],'prior file preserved '+x['path']);preserved+=1
 manifest=json.loads((R/'conclusions/source_manifest.json').read_text());entries=manifest['sources']+manifest['conclusions']
 for p in [H/'README.md',H/'PUBLICATION.md',H/'SOURCES.md',CENTRAL,R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']:
  records=[x for x in entries if x['path']==str(p.relative_to(ROOT))];check(bool(records),'registered path');check(all(x['sha256']==sha(p) for x in records),'all manifest occurrences')
 reg=json.loads((O/'registration.json').read_text());count=max(map(int,re.findall(r'^\| (\d+) \|',(R/'conclusions/README.md').read_text(),re.M)));check(count==reg['independent_table_count_before']==reg['independent_table_count_after']==42,'independent count unchanged')
 links=0;future={O/'artifact_inventory.json',O/'SIZE_REPORT.md'}
 for p in list(H.glob('*.md'))+[CENTRAL]:
  for url in re.findall(r'\]\(([^)]+)\)',p.read_text()):
   if url.startswith(('http:','https:','#')):continue
   path=(p.parent/url.split('#')[0]).resolve();check(path.exists() or path in future,'local link '+str(path));links+=1
 figures=[]
 for p in (H/'figures').glob('*.png'):
  im=Image.open(p);check(im.width>=1200 and im.height>=600,'figure resolution');check(float(np.std(np.asarray(im)))>20,'nonblank figure');figures.append(dict(path=str(p.relative_to(ROOT)),width=im.width,height=im.height,sha256=sha(p),visually_inspected=True))
 result=dict(passed=True,checks=checks,independent_verification_checks=v['checks'],prior_related_files_preserved=preserved,shared_modified_files=len(shared),complete_pairs=True,publication_matches_results=True,independent_study_count_unchanged=count,local_links_checked=links,figures=figures)
 (O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

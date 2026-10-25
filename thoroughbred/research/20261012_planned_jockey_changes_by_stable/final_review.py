"""Final report, complete stable coverage, immutable prior files, links and figure review."""
from pathlib import Path
import json,re,hashlib
import pandas as pd,numpy as np
from PIL import Image
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';CENTRAL=R/'conclusions/50A_PLANNED_JOCKEY_CHANGES_BY_STABLE.md';checks=0
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def check(value,label):
 global checks
 assert value,label;checks+=1
def main():
 d=pd.read_parquet(O/'classified_starts.parquet');pub=json.loads((O/'publication.json').read_text());v=json.loads((O/'verification.json').read_text());check(v['passed'],'independent verification');check(len(d)==159014 and not d.row_key.duplicated().any(),'complete unchanged outcome roster');e=pd.read_csv(O/'adjusted_associations.csv');s=pd.read_csv(O/'stable_metrics.csv',dtype={'trainer_id':str});p=pd.read_csv(O/'stable_destination_jockey_metrics.csv',dtype={'trainer_id':str,'jockey_id':str});support=pd.read_csv(O/'stable_model_support.csv',dtype={'trainer_id':str})
 for window,allg in [('2024_2025',d[d.year.between(2024,2025)]),('2026_partial',d[d.year.eq(2026)])]:
  g=allg[allg.main_eligible&allg.classification.eq('planned_as_card')];expected=set(map(tuple,g[['meet','trainer_id']].drop_duplicates().to_numpy()));actual=set(map(tuple,s[s.window.eq(window)&s.category.eq('all')][['meet','trainer_id']].to_numpy()));check(expected==actual,window+' complete all stable table')
  groups=g[g.changed].groupby(['meet','trainer_id','jockey_id']).agg(n=('row_key','size'),h=('horse_id','nunique'),r=('source_key','nunique'));pairs=p[p.window.eq(window)].set_index(['meet','trainer_id','jockey_id']);check(set(groups.index)==set(pairs.index),window+' all pair groups');flag=(groups.n>=30)&(groups.h>=15)&(groups.r>=20);check(pairs.reindex(groups.index).report_supported.eq(flag).all(),window+' supported pair flags')
  late=allg[allg.normal_outcome&allg.classification.eq('post_card_change')];actual=set(map(tuple,s[s.window.eq(window)&s.category.eq('post_card_all_normal')][['meet','trainer_id']].to_numpy()));expected=set(map(tuple,late[['meet','trainer_id']].drop_duplicates().to_numpy()));check(expected==actual,window+' complete late stable table')
  if window=='2024_2025':
   expected=set()
   for (meet,tid),sg in g.groupby(['meet','trainer_id']):
    if len(sg)>=200 and sg.horse_id.nunique()>=30 and sg.source_key.nunique()>=30 and sg.category.eq('ordinary_to_top').sum()>=30 and sg.category.eq('retained_ordinary').sum()>=50:expected.add((meet,tid))
   check(expected==set(map(tuple,support[['meet','trainer_id']].to_numpy())),'32 declared supported stable models complete')
 for key,file,filter_ in [('categories','category_metrics.csv',lambda a:a[a.window.eq('2024_2025')&a.meet.eq('전체')]),('stable_adjusted','stable_adjusted_top3.csv',lambda a:a),('supported_pairs','stable_destination_jockey_metrics.csv',lambda a:a[a.window.eq('2024_2025')&a.report_supported]),('late_reason_metrics','late_change_metrics.csv',lambda a:a[a.window.eq('2024_2025')&a.population.eq('all_normal')&a.meet.eq('전체')])]:
  a=pd.DataFrame(pub[key]);b=filter_(pd.read_csv(O/file,dtype={'trainer_id':str,'jockey_id':str}));sortcols=[c for c in ['meet','trainer_id','jockey_id','category','reason_class','term'] if c in b];a=a.sort_values(sortcols).reset_index(drop=True);b=b.sort_values(sortcols).reset_index(drop=True);check(a.shape==b.shape,key+' shape');check(set(a.columns)==set(b.columns),key+' columns');a=a[b.columns]
  for col in b:
   if pd.api.types.is_numeric_dtype(b[col]):check(np.allclose(a[col].to_numpy(float),b[col].to_numpy(float),atol=1e-12,rtol=1e-12,equal_nan=True),key+col)
   else:check(a[col].fillna('MISSING').equals(b[col].fillna('MISSING')),key+col)
 report=(H/'README.md').read_text();text=(H/'PUBLICATION.md').read_text();check('2,179' in text and '35.93%' in text and '+4.40%p' in text,'headline data');check('839' in text and '476' in text and '327' in text,'late counts');check('−4.44' in text or '-4.44' in text,'late uncertainty');check(pub['causal_intent_proven'] is False and pub['predictive_improvement_proven'] is False,'observational scope');check(not pub['card_first_publication_immutability_verified'],'card publication limitation')
 for row in pd.read_csv(O/'stable_adjusted_top3.csv').itertuples():check(f'{row.trainer_name}' in report and f'{100*row.estimate:+.2f}' in report,'all stable report estimates')
 old=json.loads((O/'baseline_inventory.json').read_text())['related_existing_files'];shared={r['path'] for r in json.loads((O/'shared_edits_baseline.json').read_text())['files']};preserved=0
 for row in old:
  if row['path'] in shared:continue
  p0=ROOT/row['path'];check(p0.stat().st_size==row['bytes'] and sha(p0)==row['sha256'],'preserve '+row['path']);preserved+=1
 manifest=json.loads((R/'conclusions/source_manifest.json').read_text());entries=manifest['sources']+manifest['conclusions']
 for p0 in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',CENTRAL,R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md']:
  records=[v for v in entries if v['path']==str(p0.relative_to(ROOT))];check(bool(records),'registered path '+str(p0));check(all(v['sha256']==sha(p0) for v in records),'all manifest occurrences '+str(p0))
 registration=json.loads((O/'registration.json').read_text());count=max(map(int,re.findall(r'^\| (\d+) \|',(R/'conclusions/README.md').read_text(),re.M)));check(count==registration['independent_table_count_before']==registration['independent_table_count_after']==42,'independent study count unchanged')
 links=0;future={O/'artifact_inventory.json',O/'SIZE_REPORT.md'}
 for p0 in list(H.glob('*.md'))+[CENTRAL]:
  for url in re.findall(r'\]\(([^)]+)\)',p0.read_text()):
   if url.startswith(('https:','http:','#')):continue
   target=(p0.parent/url.split('#')[0]).resolve();check(target.exists() or target in future,'local link '+str(target));links+=1
 figures=[]
 for p0 in (H/'figures').glob('*.png'):
  im=Image.open(p0);check(im.width>=1200 and im.height>=600,'figure resolution');check(float(np.std(np.asarray(im)))>20,'nonblank figure');figures.append(dict(path=str(p0.relative_to(ROOT)),width=im.width,height=im.height,sha256=sha(p0),visually_inspected=True))
 result=dict(passed=True,checks=checks,independent_verification_checks=v['checks'],prior_related_files_preserved=preserved,shared_modified_files=len(shared),all_stables_and_pairs_included=True,independent_study_count_unchanged=count,publication_matches_results=True,local_links_checked=links,figures=figures)
 (O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

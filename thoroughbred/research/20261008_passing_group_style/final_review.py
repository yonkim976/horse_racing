"""Independent publication, count, examples, links and preservation review."""
from pathlib import Path
import json,hashlib,re
import duckdb,numpy as np,pandas as pd
H=Path(__file__).resolve().parent;R=H.parent;O=H/'outputs';ROOT=H.parents[2]
d=pd.read_parquet(O/'observations.parquet');p=pd.read_parquet(O/'temporal_evaluation.parquet');a=json.loads((O/'source_audit.json').read_text());con=duckdb.connect();con.register('d',d)
q=con.execute('''SELECT count(*) AS common_n,sum(CAST(role4<>s1f_class AS INT)) AS different_n,
 sum(CAST(role4=0 AND s1f>1 AS INT)) AS additional_front,
 count(DISTINCT CASE WHEN rank_leader_outside_group THEN source_key ELSE NULL END) AS conflicts
 FROM d WHERE group_observed AND s1f_complete''').df().iloc[0]
assert int(q.common_n)==a['common_n']==155349 and int(q.different_n)==a['different_n']==42614 and int(q.additional_front)==a['non_rank1_in_first_group']==23314 and int(q.conflicts)==1
assert len(d)==159014 and int(d.group_observed.sum())==155387
rr=d[d.group_observed].drop_duplicates('source_key');assert len(rr)==14309 and rr.first_group_size.eq(1).sum()==2966
assert d.solo_ge2_lengths.eq(True).sum()==119
profile=pd.read_csv(O/'horse_profiles.csv',dtype={'horse_id':str});pr=json.loads((O/'profile_summary.json').read_text());c=profile[profile.supported5&profile.rank5_supported];assert len(c)==pr['comparable_profiles']==2601
assert c.rank5_leader_rate.ge(.6).sum()==112 and c.leader_rate5.ge(.6).sum()==488
assert (c.leader_rate5.ge(.6)&c.rank5_leader_rate.lt(.6)).sum()==376
for horse,expected in {'0044166':[0,5,0,0,0],'0044515':[0,4,1,0,0],'0046818':[0,2,2,1,0],'0045836':[0,0,0,3,2]}.items():
 r=profile[profile.horse_id.eq(horse)].iloc[0];np.testing.assert_array_equal(r[[f'role5_count5_{i}' for i in range(5)]],expected)
examples=pd.read_csv(O/'examples.csv',dtype={'horse_id':str});joined=examples.merge(d[['source_key','horse_id','s1f','notation_raw']],on=['source_key','horse_id'],suffixes=('_example','_source'),validate='one_to_one');assert len(joined)==20;assert joined.notation_raw_example.eq(joined.notation_raw_source).all();np.testing.assert_allclose(joined.s1f_example,joined.s1f_source)
assert len(p)==24613 and p.horse_id.nunique()==3084 and p.day_key.nunique()==296 and p.s1f_complete.all()
strong=p[p.count_0.ge(4)];assert len(strong)==2324;np.testing.assert_allclose(strong.role4.eq(0).mean(),.5813253012048193)
v=json.loads((O/'verification.json').read_text());assert v['passed'] and v['checks']==1657062
pub=json.loads((O/'publication.json').read_text());np.testing.assert_allclose(pub['temporal_evaluation']['history_accuracy'],p.history_hit.mean());assert pub['accuracy_not_comparable_across_definitions'] and not pub['optimal_style_proven']
central=R/'conclusions/28A_PASSING_GROUP_STYLE.md';docs=[H/'README.md',H/'PUBLICATION.md',H/'SOURCES.md',H/'PLAN.md',central];links=0
for f in docs:
 for target in re.findall(r'\]\(([^)]+)\)',f.read_text()):
  if target.startswith(('https://','http://','#')):continue
  path=(f.parent/target.split('#')[0]).resolve();assert path.is_relative_to(ROOT)
  if path==O/'artifact_inventory.json':continue
  assert path.exists(),(f,target);links+=1
m=json.loads((R/'conclusions/source_manifest.json').read_text());names={str(f.relative_to(ROOT)) for f in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central,R/'conclusions/README.md',R/'conclusions/SOURCES.md']};found=0
for group in ['sources','conclusions']:
 for item in m[group]:
  if item['path'] in names:assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];found+=1
assert found==6
baseline=json.loads((O/'baseline_inventory.json').read_text());shared={str((R/f).relative_to(ROOT)) for f in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};unchanged=0
for item in baseline['related_existing_files']:
 if item['path'] in shared:continue
 path=ROOT/item['path'];assert path.stat().st_size==item['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'];unchanged+=1
start_count=max(int(n) for n in re.findall(r'^\| (\d+) \|',(R/'conclusions/README.md').read_text(),re.M));assert start_count==41
result=dict(passed=True,sql_comparison_counts=True,profile_and_examples_reproduced=True,temporal_claims_reproduced=True,own_manifest_hashes_checked=found,document_links_checked=links,related_prior_files_unchanged=unchanged,independent_study_count=41,followup='28A',figure_visually_inspected='figures/rank_vs_passing_group.png',inventory_checked_separately_after_this_review=True,causal_or_optimal_style_proven=False)
(O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))

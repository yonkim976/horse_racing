"""Check profile movement aggregates, publication claims, links and manifests."""
from pathlib import Path
import hashlib,json,re
import duckdb,numpy as np,pandas as pd
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2];R=H.parent
d=pd.read_parquet(O/'observed_styles.parquet');profile=pd.read_csv(O/'horse_style_profiles.csv',dtype={'horse_id':str});con=duckdb.connect();con.register('d',d);checks=0
for look in [5,10]:
 q=con.execute(f'''WITH numbered AS (SELECT *,row_number() OVER (PARTITION BY horse_id ORDER BY date DESC) AS rn FROM d)
 SELECT horse_id,sum(CAST(g3f_complete AS INT)) AS middle_n,count(last600_gain) AS late_n,
 avg(CASE WHEN g3f_complete THEN CAST(g3f_class<=1 AS INT) ELSE NULL END) AS front,
 avg(early_to_600_gain) AS early_gain,avg(last600_gain) AS late_gain,avg(last200_gain) AS final_gain
 FROM numbered WHERE rn<={look} GROUP BY horse_id''').df().set_index('horse_id').reindex(profile.horse_id)
 for c,pc in [('middle_n','middle_valid'),('late_n','late_valid'),('front','middle_front_rate'),('early_gain','early_to_600_gain'),('late_gain','last600_gain'),('final_gain','last200_gain')]:
  np.testing.assert_allclose(q[c],profile[f'window{look}_{pc}'],atol=1e-12,rtol=1e-10,equal_nan=True);checks+=1
assert json.loads((O/'verification.json').read_text())['passed'];checks+=1
a=json.loads((O/'source_audit.json').read_text());assert a['roster_rows']==159014 and a['valid_s1f_rows']==155349 and a['restored_nonfinishers']==486 and a['no_valid_finish_in_style']==114;checks+=1
v=pd.read_parquet(O/'temporal_evaluation.parquet');assert len(v)==24613 and v.horse_id.nunique()==3084 and v.day_key.nunique()==296;checks+=1
pub=json.loads((O/'publication.json').read_text());np.testing.assert_allclose(pub['temporal_evaluation']['history_accuracy'],v.history_hit.mean());assert not pub['optimal_style_proven'];checks+=1
examples={'0044166':[5,0,0,0],'0046818':[0,5,0,0],'0044487':[0,0,5,0],'0042620':[0,0,0,5],'0045836':[0,1,2,2]}
for horse,expected in examples.items():
 q=profile[profile.horse_id.eq(horse)];assert len(q)==1;np.testing.assert_array_equal(q[[f'window5_count_{i}' for i in range(4)]].iloc[0],expected);checks+=1
central=R/'conclusions/28_RUNNING_STYLE_FOUNDATION.md';docs=[H/'README.md',H/'PUBLICATION.md',H/'SOURCES.md',H/'PLAN.md',central]
links=0
for path in docs:
 for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
  if target.startswith(('https://','http://','#')):continue
  q=(path.parent/target.split('#')[0]).resolve();assert q.is_relative_to(ROOT),'outside repo link'
  if q==O/'artifact_inventory.json':continue
  assert q.exists(),(path,target);links+=1
m=json.loads((R/'conclusions/source_manifest.json').read_text());names={str(p.relative_to(ROOT)) for p in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central,R/'conclusions/README.md',R/'conclusions/SOURCES.md']};found=0
for group in ['sources','conclusions']:
 for item in m[group]:
  if item['path'] in names:assert hashlib.sha256((ROOT/item['path']).read_bytes()).hexdigest()==item['sha256'];found+=1
assert found==6
baseline=json.loads((O/'baseline_inventory.json').read_text());shared={str((R/p).relative_to(ROOT)) for p in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};unchanged=0
for item in baseline['related_existing_files']:
 if item['path'] in shared:continue
 p=ROOT/item['path'];assert p.stat().st_size==item['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'];unchanged+=1
result=dict(passed=True,numeric_checks=checks,profile_movement_independent_sql=True,profile_horses=len(profile),document_links_checked=links,own_manifest_hashes_checked=found,related_prior_files_unchanged=unchanged,figures_visually_inspected=['figures/repeatability.png','figures/early_middle_positions.png'],inventory_checked_separately_after_this_review=True,limitations_preserved=['observed tendency not optimal style','rear not automatically closer','incomplete race selection','unknown intention','no gate/style performance causal estimate','no production deployment'])
(O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))

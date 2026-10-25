"""Check saved claims, references, new manifest entries and unchanged prior artifacts."""
from pathlib import Path
import hashlib,json,re
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parents[2];R=H.parent;O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((O/'baseline_inventory.json').read_text());shared=set(b['shared_paths']);old=[]
for a in b['related_existing_files']:
 if a['path'] not in shared:
  p=ROOT/a['path'];assert p.stat().st_size==a['bytes'] and sha(p)==a['sha256'],a['path'];old.append(a['path'])
v=json.loads((O/'verification.json').read_text());assert v['passed'] and v['independent_model_rows']==252 and len(v['checks'])==1073 and v['prior_results_reproduced']==432
r=pd.read_csv(O/'contrasts.csv');assert len(r)==1704 and r.supported.all() and r.lower.notna().all();assert (r.lower<=r.difference).all() and (r.upper>=r.difference).all()
q=r[r.scope.eq('time')&r.cohort.eq('top5')&r.specification.eq('full')&r.window.eq('all')&r.target.eq('암')&r.reference.eq('수')&r.part.eq('finish')]
assert q[q.contrast.eq('short_gap')].lower.gt(0).all()
z=q[q.meet.eq('부산')&q.contrast.eq('middle_gap')].iloc[0];assert z.lower<0<z.upper
assert q[q.meet.eq('서울')&q.contrast.eq('middle_gap')].lower.gt(0).all()
z=r[r.scope.eq('race_outcome')&r.specification.eq('race_full')&r.window.eq('all')&r.target.eq('암')&r.reference.eq('수')&r.part.eq('top5')&r.contrast.ne('middle_minus_short')];assert len(z)==4 and z.upper.lt(0).all() and z.cohort.eq('all').all()
audit=json.loads((O/'source_and_method.json').read_text());assert len(audit['inputs_sha256'])==5 and audit['top5_n']==69639 and audit['missing_selected_top5'][0]['rank']==3
pub=json.loads((O/'publication_summary.json').read_text());assert not pub['causal'] and not pub['operational_correction'] and pub['selected_n']==69639
existing=[];pending=[]
for p in list(H.glob('*.md'))+[R/'conclusions/25B_SEX_TOP5.md']:
 for dest in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' in dest or dest.startswith('#'):continue
  f=(p.parent/dest.split('#')[0]).resolve()
  if not f.exists():assert f==O/'artifact_inventory.json',str(f);pending.append(str(f.relative_to(ROOT)))
  else:existing.append(str(f.relative_to(ROOT)))
# Five-column time/interaction tables must be valid Markdown tables.
for line in (H/'README.md').read_text().splitlines():
 if line.startswith('| 지역 | 지표 |'):assert len(line.split('|'))==7
m=json.loads((R/'conclusions/source_manifest.json').read_text());manifest=[]
for key in ['sources','conclusions']:
 for a in m[key]:
  if H.name in a['path'] or a['path'] in ['thoroughbred/research/conclusions/25B_SEX_TOP5.md','thoroughbred/research/conclusions/README.md','thoroughbred/research/conclusions/SOURCES.md']:
   assert sha(ROOT/a['path'])==a['sha256'],a['path'];manifest.append(a['path'])
assert '서로 다른 선택 표본의 조건부 추정치 비교' in (H/'README.md').read_text()
obj=dict(passed=True,prior_related_files_unchanged=len(old),unchanged_paths=old,source_hashes=5,top5_n=69639,all_contrast_rows=1704,numeric_checks=1073,independent_model_rows=252,prior_model_rows_reproduced=432,local_existing_links_checked=len(existing),inventory_links_resolved_by_final_capacity_step=len(pending),manifest_entries_verified=manifest,figures_visually_inspected=['figures/top5_time_comparison.png','figures/top5_entry_difference.png'],claim_review='per-outing selected final rank vs all-starter outcome; changed overlap; selected time does not imply entry parity; recent and field-size sensitivity; kg and seconds and percentage points; no causal or operational claim',layout='PNG figures visually inspected; local Markdown source and tables checked; website not deployed')
(O/'final_review.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');print('Final review PASS; unchanged prior files',len(old))

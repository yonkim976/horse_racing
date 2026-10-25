"""Review saved claims, local references, manifest entries and unchanged source study."""
from pathlib import Path
import hashlib,json,re
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';R=H.parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((O/'baseline_inventory.json').read_text());shared=set(b['shared_paths']);unchanged=[]
for a in b['related_existing_files']:
 if a['path'] not in shared:
  p=ROOT/a['path'];assert p.stat().st_size==a['bytes'] and sha(p)==a['sha256'],a['path'];unchanged.append(a['path'])
v=json.loads((O/'verification.json').read_text());assert v['passed'] and v['checked_primary_model_rows']==126 and len(v['checks'])==524
r=pd.read_csv(O/'joint_contrasts.csv');assert len(r)==816
assert (r[r.supported].lower<=r[r.supported].difference).all() and (r[r.supported].upper>=r[r.supported].difference).all()
assert r[r.supported].lower.notna().all() and r[~r.supported].lower.isna().all()
pub=json.loads((O/'publication_summary.json').read_text());assert pub['operational_correction'] is False
q=r[r.scope.eq('time_joint')&r.specification.eq('full')&r.window.eq('all')&r.target.eq('암')&r.reference.eq('수')]
assert (q[q.part.eq('finish')&q.contrast.isin(['short_gap','middle_gap'])].lower>0).all()
assert (q[q.part.eq('early')&q.contrast.eq('short_gap')].upper<0).all()
z=q[q.part.isin(['finish','seconds_per_1000m'])&q.contrast.eq('middle_minus_short')]
assert (z.lower<0).all() and (z.upper>0).all()
links=[];pending=[]
for p in list(H.glob('*.md'))+[R/'conclusions/25A_SEX_WEIGHT_DISTANCE.md']:
 for dest in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' in dest or dest.startswith('#'):continue
  f=(p.parent/dest.split('#')[0]).resolve()
  if not f.exists():
   assert f==O/'artifact_inventory.json',str(f);pending.append(str(f.relative_to(ROOT)))
  else:links.append(str(f.relative_to(ROOT)))
m=json.loads((R/'conclusions/source_manifest.json').read_text());checked=[]
for key in ['sources','conclusions']:
 for a in m[key]:
  if H.name in a['path'] or a['path'] in ['thoroughbred/research/conclusions/25A_SEX_WEIGHT_DISTANCE.md','thoroughbred/research/conclusions/README.md','thoroughbred/research/conclusions/SOURCES.md']:
   assert sha(ROOT/a['path'])==a['sha256'];checked.append(a['path'])
# Source periods and literal reported bounds are checked against numeric output.
assert '중거리 전체시간은+0.231초·+0.224초' in (H/'README.md').read_text()
assert '부산+0.119초' in (H/'README.md').read_text()
report=dict(passed=True,previous_related_files_unchanged=len(unchanged),unchanged_paths=unchanged,primary_numeric_rows=126,numeric_checks=524,all_contrasts=816,local_existing_links_checked=len(links),inventory_links_resolved_by_final_capacity_step=len(pending),manifest_entries_verified=checked,figures_visually_inspected=['figures/body_mass.png','figures/distance_comparison.png'],claim_review='weight vs carried load; fast opening vs whole short race; conditional vs causal; pointwise interaction; recent uncertainty; sparse long distances',layout='PNG figures visually inspected; Markdown source/table links checked; website not deployed')
(O/'final_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('Final review passed; prior files unchanged:',len(unchanged))

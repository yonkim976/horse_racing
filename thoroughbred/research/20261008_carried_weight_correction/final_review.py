"""Preservation, claims, support labels and publication/index checks."""
from pathlib import Path
import hashlib,json,re
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;O=H/'outputs';R=H.parent;ROOT=H.parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((O/'baseline_inventory.json').read_text());shared=set(b['shared_paths']);old=[]
for a in b['related_existing_files']:
 if a['path'] not in shared:
  p=ROOT/a['path'];assert p.stat().st_size==a['bytes'] and sha(p)==a['sha256'],a['path'];old.append(a['path'])
v=json.loads((O/'verification.json').read_text());assert v['passed'] and v['independent_distance_models']==101 and v['independent_pooled_models']==24 and len(v['checks'])==303
r=pd.read_csv(O/'coefficients.csv');m=pd.read_csv(O/'diagnostics.csv');skip=pd.read_csv(O/'skipped.csv');assert len(r)==177 and len(m)==141 and len(skip)==15
assert not m.nuisance_names.fillna('').str.contains('sex').any()
assert not m[m.specification.eq('main')].nuisance_names.str.contains('body').any()
main=r[r.meet.eq('전체')&r.window.eq('all')&r.specification.eq('main')&r.distance_m.eq(0)].iloc[0];assert main.n==134233 and main.lower>0 and .031<main.coefficient<.032
recent=r[r.meet.eq('전체')&r.window.eq('complete_2024_2025')&r.specification.eq('main')&r.distance_m.eq(0)].iloc[0];assert recent.lower<0<recent.upper and .014<recent.coefficient<.015
c=pd.read_csv(O/'candidates.csv');assert c.conservative_candidate.eq(0).all() and not c.operational_adoption.any()
table=pd.read_csv(O/'illustrative_003_lookup.csv');assert table.carried_kg.between(52,57).all();assert np.max(abs(table.time_to_add_for54+.03*(table.carried_kg-54)*table.distance_m/1000))<1e-10
pub=json.loads((O/'publication_summary.json').read_text(),parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)));assert not pub['causal'] and not pub['operational'] and not pub['forecast_validation']
central=R/'conclusions/11B_CARRIED_WEIGHT_CORRECTION.md';manifest=json.loads((R/'conclusions/source_manifest.json').read_text());checked=[]
for key in ['sources','conclusions']:
 for a in manifest[key]:
  if H.name in a['path'] or a['path'] in [str(central.relative_to(ROOT)),'thoroughbred/research/conclusions/README.md','thoroughbred/research/conclusions/SOURCES.md']:
   assert sha(ROOT/a['path'])==a['sha256'],a['path'];checked.append(a['path'])
assert len(checked)==6
existing=[];pending=[]
for p in list(H.glob('*.md'))+[central]:
 for dest in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' in dest or dest.startswith('#'):continue
  q=(p.parent/dest.split('#')[0]).resolve()
  if not q.exists():assert q==O/'artifact_inventory.json',str(q);pending.append(str(q.relative_to(ROOT)))
  else:existing.append(str(q.relative_to(ROOT)))
text=(H/'README.md').read_text()
for claim in ['134,233','0.03초/(kg·1000m)','74.892초','75.072초','0(보류)','다음 경주의 사전예측 검증이 아니다','65~68날짜','순수한 인과적 손실']:assert claim in text,claim
obj=dict(passed=True,prior_related_files_unchanged=len(old),unchanged_paths=old,models=177,distance_models=141,pooled_models=36,skipped_models=15,independent_distance_models=101,independent_pooled_models=24,numeric_checks=303,manifest_entries_verified=checked,local_links_checked=len(existing),pending_inventory_links=len(pending),figures_visually_inspected=['figures/pooled_load_slopes.png','figures/distance_load_slopes.png'],claim_review='sex/body features absent in main; observational averaged coefficient vs causal loss; repeated-comparison selection; recent and distance sensitivity; actual-date cross-venue covariance; heldout nuisance refit is not forecasting; short heldout support marked; rounded illustrative value distinct from held adoption; signed54kg formula',layout='PNG figures visually inspected; Markdown links and claims checked; no website implementation or deployment')
(O/'final_review.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');print('Final review PASS; unchanged related inputs',len(old))

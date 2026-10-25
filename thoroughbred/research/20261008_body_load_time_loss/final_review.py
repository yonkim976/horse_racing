"""Review claims, local references, preservation and new manifest entries."""
from pathlib import Path
import hashlib,json,re
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parents[2];R=H.parent;O=H/'outputs';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((O/'baseline_inventory.json').read_text());shared=set(b['shared_paths']);old=[]
for a in b['related_existing_files']:
 if a['path'] not in shared:
  p=ROOT/a['path'];assert p.stat().st_size==a['bytes'] and sha(p)==a['sha256'],a['path'];old.append(a['path'])
v=json.loads((O/'verification.json').read_text());assert v['passed'] and v['independent_model_count']==23 and v['independent_contrast_rows']==366 and len(v['checks'])==760
r=pd.read_csv(O/'load_contrasts.csv');m=pd.read_csv(O/'model_diagnostics.csv');skipped=pd.read_csv(O/'skipped_models.csv');assert len(r)==3705 and len(m)==65 and len(skipped)==2
assert r[r.supported].lower.notna().all() and r[~r.supported].lower.isna().all();assert r.estimable.all()
z=r[r.part.eq('finish')&r.specification.eq('horse_race_full')&r.window.eq('all')&r.distance_m.eq(1200)&r.to_load.eq(55)]
assert z[z.body_kg.eq(480)&z.contrast.eq('load_change')].lower.gt(0).all()
q=z[z.contrast.eq('light_minus_heavy')];assert len(q)==2 and q.lower.lt(0).all() and q.upper.gt(0).all()
q=r[r.modifier_bh_q.notna()];assert len(q)==12 and q.modifier_bh_q.gt(.05).all()
q=r[r.window.eq('complete_2024_2025')&r.distance_m.eq(1200)&r.body_kg.eq(480)&r.to_load.eq(55)&r.part.eq('finish')&r.contrast.eq('load_change')];assert len(q)==2 and q.lower.lt(0).all() and q.upper.gt(0).all()
pub=json.loads((O/'publication_summary.json').read_text());assert not pub['causal'] and not pub['operational_correction']
existing=[];pending=[]
for p in list(H.glob('*.md'))+[R/'conclusions/11A_BODY_LOAD_TIME.md']:
 for dest in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' in dest or dest.startswith('#'):continue
  f=(p.parent/dest.split('#')[0]).resolve()
  if not f.exists():assert f==O/'artifact_inventory.json',str(f);pending.append(str(f.relative_to(ROOT)))
  else:existing.append(str(f.relative_to(ROOT)))
manifest=json.loads((R/'conclusions/source_manifest.json').read_text());checked=[]
for key in ['sources','conclusions']:
 for a in manifest[key]:
  if H.name in a['path'] or a['path'] in ['thoroughbred/research/conclusions/11A_BODY_LOAD_TIME.md','thoroughbred/research/conclusions/README.md','thoroughbred/research/conclusions/SOURCES.md']:
   assert sha(ROOT/a['path'])==a['sha256'],a['path'];checked.append(a['path'])
text=(H/'README.md').read_text();assert '480kg 말의54→55kg 차이는 서울 약+0.055초·부산+0.031초' in text
assert '인과적 손실' in text and '상위5위' in text and '최근' in text and '지원 부족' in text
obj=dict(passed=True,prior_related_files_unchanged=len(old),unchanged_paths=old,model_count=65,contrasts=3705,skipped_recent1000_models=2,independent_models=23,independent_contrasts=366,numeric_checks=760,manifest_entries_verified=checked,local_links_checked=len(existing),inventory_links_resolved_by_final_capacity_step=len(pending),figures_visually_inspected=['figures/conditional_load_curves.png','figures/body_modifier_by_distance.png'],claim_review='conditional association vs causal loss; fixed body kg vs per-kg carried change; changed FE population; pointwise/BH distinction; recent/top5/rating sensitivity; unsupported endpoints; observed-band table does not trim models',layout='PNG figures visually inspected; Markdown links/source checked; no website deployment')
(O/'final_review.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');print('Final review PASS; old files unchanged',len(old))

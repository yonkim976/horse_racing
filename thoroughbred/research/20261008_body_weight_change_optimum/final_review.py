"""Final preservation, support, claims and publication/index review."""
from pathlib import Path
import hashlib,json,re
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2];R=H.parent;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((O/'baseline_inventory.json').read_text());shared=set(b['shared_paths']);unchanged=[]
for a in b['related_existing_files']:
 if a['path'] not in shared:
  p=ROOT/a['path'];assert p.stat().st_size==a['bytes'] and sha(p)==a['sha256'],a['path'];unchanged.append(a['path'])
assert len(unchanged)==145
v=json.loads((O/'verification.json').read_text());assert v['passed'] and v['raw_body_and_change_checks']==151074 and v['input_hashes_verified']==20
assert (v['independent_distance_models'],v['independent_pooled_models'],v['independent_individual_models'],len(v['checks']))==(182,42,24,1324)
m=pd.read_csv(O/'models.csv');d=pd.read_csv(O/'diagnostics.csv');c=pd.read_csv(O/'contrasts.csv');sk=pd.read_csv(O/'skipped.csv');assert (len(m),len(d),len(c),len(sk))==(280,226,1556,8)
assert not d.nuisance_names.fillna('').str.contains('sex').any();a=json.loads((O/'source_audit.json').read_text());assert a['raw_reported_change_observed']==140926 and a['verified_zero_changes']==9464 and a['effective_change_missing']==684 and a['effective_change_observed']==150390
f=pd.read_parquet(O/'body_features.parquet');assert len(f)==151074 and f.row_key.is_unique and f.change_origin.eq('verified_zero').sum()==9464 and f.body_change.isna().sum()==684
absolute=m[m.metric.eq('absolute')&m.window.eq('all')&m.specification.eq('main')&m.distance_m.gt(0)];assert len(absolute)==13 and not absolute.minimum_supported.any()
for metric,expected in [('relative',12),('past_relative',2)]:
 q=m[m.metric.eq(metric)&m.window.eq('all')&m.specification.eq('main')&m.distance_m.gt(0)];assert (q.minimum_supported&q.curvature_bh_q.lt(.05)).sum()==expected
main=c[c.meet.eq('전체')&c.window.eq('all')&c.specification.eq('main')&c.distance_m.eq(0)];q=main[main.metric.eq('past_relative')].set_index('target_kg');assert .039<q.loc['-10','difference_per1000m']*1.2<.040 and .047<q.loc['10','difference_per1000m']*1.2<.048
q=main[main.metric.eq('change_bins')].set_index('target_kg');assert q.loc['≤−15','lower']>0 and q.loc['≥+15','lower']>0 and q.loc['−5~−1','lower']<0<q.loc['−5~−1','upper']
p=json.loads((O/'individual_summary.json').read_text());assert (p['eligible_groups'],p['eligible_horses'],p['estimable_full'],p['full_candidate_groups'],p['full_candidate_bh05_groups'])==(103,100,84,5,0)
assert (p['train_candidate_groups'],p['train_candidates_with_test_curve'],p['repeat_groups'],p['repeat_after_train_bh_groups'])==(2,1,1,0)
pub=json.loads((O/'publication_summary.json').read_text(),parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)));assert not pub['causal'] and not pub['operational'] and not pub['forecast_validation'] and pub['absolute_distance_minima_confirmed']==0
central=R/'conclusions/11C_BODY_WEIGHT_CHANGE_OPTIMUM.md';manifest=json.loads((R/'conclusions/source_manifest.json').read_text());checked=[]
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
for phrase in ['133,681','104,752','0.039초','0.047초','13개 거리 조합','후향 참조','후기 미추정1개','미래 기록의 사전예측 검증이 아니다','제곱식 모양을 강제하지 않은']:assert phrase in text,phrase
obj=dict(passed=True,prior_related_files_unchanged=len(unchanged),unchanged_paths=unchanged,models=280,distance_models=226,pooled_models=54,contrasts=1556,skipped_models=8,independent_distance_models=182,independent_pooled_models=42,independent_personal_models=24,numeric_checks=1324,manifest_entries_verified=checked,local_links_checked=len(existing),pending_inventory_links=len(pending),figures_visually_inspected=['figures/body_change_curves.png','figures/distance_body_distributions.png','figures/individual_optimum_support.png'],claim_review='raw reported change vs verified zero vs unresolved blank; same horse/race vs personal relative-time exploration; signed change vs usual deviation vs absolute mass; common1200 illustration vs actual distance slopes; retrospective vs prior-only reference; sample differences; quadratic/category check; unsupported absolute minima; distance and personal BH; small chronological repetition with missing test curve; observational relation vs causal loss or mass prescription',layout='three PNGs visually inspected; prose/tables/source links reviewed; publication JSON nulls checked; no deployment')
(O/'final_review.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');print('Final review PASS;',len(unchanged),'prior related files unchanged')

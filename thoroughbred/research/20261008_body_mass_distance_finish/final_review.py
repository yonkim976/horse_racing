"""Preservation, source aggregation, support, public claims and links review."""
from pathlib import Path
import hashlib,json,re
import numpy as np,pandas as pd,duckdb
from scipy.stats import false_discovery_control
H=Path(__file__).resolve().parent;O=H/'outputs';R=H.parent;ROOT=H.parents[2];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
b=json.loads((O/'baseline_inventory.json').read_text());unchanged=[]
for a in b['related_existing_files']:
 if a['path'] not in b['shared_paths']:
  p=ROOT/a['path'];assert p.stat().st_size==a['bytes'] and sha(p)==a['sha256'],a['path'];unchanged.append(a['path'])
v=json.loads((O/'verification.json').read_text());cv=json.loads((O/'categorical_verification.json').read_text());assert v['passed'] and cv['passed'];assert (v['raw_body_and_finish_section_checks'],v['input_hashes_verified'],v['independent_distance_models'],v['independent_group_models'],v['independent_joint_models'],len(v['checks']))==(151074,21,456,216,108,3344);assert cv['independent_distance_coefficients']==248 and len(cv['checks'])==932
m=pd.read_csv(O/'models.csv');c=pd.read_csv(O/'contrasts.csv');cat=pd.read_csv(O/'categorical_contrasts.csv');dg=pd.read_csv(O/'diagnostics.csv');assert (len(m),len(c),len(cat),len(dg))==(672,2208,624,456);assert not dg[dg.specification.eq('main')].nuisance_names.str.contains('sex').any();ix=c.primary&c.meet.eq('전체');assert ix.sum()==8 and c.loc[ix,'supported'].all();np.testing.assert_allclose(false_discovery_control(c.loc[ix,'p'].to_numpy()),c.loc[ix,'bh_q'],atol=1e-10);ix2=cat.exploratory_primary;assert ix2.sum()==4 and cat.loc[ix2,'supported'].all();np.testing.assert_allclose(false_discovery_control(cat.loc[ix2,'p'].to_numpy()),cat.loc[ix2,'bh_q'],atol=1e-10)
# Recalculate raw counts/mean/quantiles with SQL rather than the analysis groupby.
d=pd.read_parquet(H.parent/'20261007_sex_ability_gap/outputs/population.parquet');con=duckdb.connect();con.register('d',d);raw=con.execute("""select meet,distance_m,case when body_weight<=450 then '≤450' when body_weight<=469 then '451–469' when body_weight<=489 then '470–489' when body_weight<=509 then '490–509' else '≥510' end mass_bin,count(*) n,count(distinct horse_id) horses,count(distinct date) dates,avg(finish) finish_mean,quantile_cont(finish,.5) finish_median,quantile_cont(finish,.2) finish_p20,quantile_cont(finish,.8) finish_p80,avg(late) late_mean,avg(last600) last600_mean,avg(late-(last600-late)/2) fade_mean from d group by all order by meet,distance_m,mass_bin""").df();saved=pd.read_csv(O/'observed_mass_sections.csv').sort_values(['meet','distance_m','mass_bin']).reset_index(drop=True);assert raw[['meet','distance_m','mass_bin']].equals(saved[['meet','distance_m','mass_bin']]);cols=['n','horses','dates','finish_mean','finish_median','finish_p20','finish_p80','late_mean','last600_mean','fade_mean'];np.testing.assert_allclose(raw[cols],saved[cols],atol=1e-9)
def point(metric,outcome,comparison,target):return c[c.metric.eq(metric)&c.outcome.eq(outcome)&c.comparison.eq(comparison)&c.target_kg.eq(target)&c.scope.eq('joint')&c.window.eq('all')&c.specification.eq('main')&c.meet.eq('전체')].iloc[0]
a=point('past_relative','finish1000','short',10);assert .042<a.estimate*1.2<.043 and a.lower>0;b1=point('past_relative','finish1000','short_minus_long',10);assert b1.lower<0<b1.upper;b2=point('past_relative','late','long',-10);assert b2.lower<0<b2.upper
for metric,target in [('absolute',450),('past_relative',-10)]:
 r=point(metric,'late','long_minus_short',target);assert r.lower<0<r.upper
for metric,target,outcome,group in [('absolute','≥530','finish1000','short'),('absolute','≤430','late','long'),('past_relative','≤−15','late','long')]:
 r=cat[cat.metric.eq(metric)&cat.target.eq(target)&cat.outcome.eq(outcome)&cat.group.eq(group)&cat.window.eq('all')&cat.specification.eq('main')&cat.meet.eq('전체')].iloc[0];assert r.lower<0<r.upper
pub=json.loads((O/'publication_summary.json').read_text(),parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)));assert not pub['causal'] and not pub['operational'] and not pub['forecast_validation'] and not pub['large_horse_sprint_disadvantage_confirmed'] and not pub['light_horse_long_late_disadvantage_confirmed'];assert pub['within_horse_heavy_slow_association'] and not pub['sprint_specific_heavy_disadvantage_confirmed']
central=R/'conclusions/11D_BODY_MASS_DISTANCE_FINISH.md';manifest=json.loads((R/'conclusions/source_manifest.json').read_text());entries=[]
for key in ['sources','conclusions']:
 for a in manifest[key]:
  if H.name in a['path'] or a['path'] in [str(central.relative_to(ROOT)),'thoroughbred/research/conclusions/README.md','thoroughbred/research/conclusions/SOURCES.md']:assert sha(ROOT/a['path'])==a['sha256'],a['path'];entries.append(a['path'])
assert len(entries)==6;links=[];pending=[]
for p in list(H.glob('*.md'))+[central]:
 for dest in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  if '://' in dest or dest.startswith('#'):continue
  q=(p.parent/dest.split('#')[0]).resolve()
  if not q.exists():assert q==O/'artifact_inventory.json';pending.append(str(q))
  else:links.append(str(q))
text=(H/'README.md').read_text()
for phrase in ['148,126','0.042초','사후 탐색','1900m 이상','순수하게 타고난 골격의 효과를 분리한 것은 아니다','마지막400m를 만든 것이 아니다','0.0508','앞선 전개','미래 예측 검증이 아니다']:assert phrase in text,phrase
obj=dict(passed=True,prior_related_files_unchanged=len(unchanged),unchanged_paths=unchanged,raw_SQL_cells_verified=len(raw)*len(cols),models=672,distance_models=456,group_models=216,joint_models=108,contrasts=2208,categorical_distance_models=248,categorical_contrasts=624,numeric_checks=len(v['checks'])+len(cv['checks']),manifest_entries_verified=entries,local_links_checked=len(links),pending_inventory_links=len(pending),figures_visually_inspected=['figures/hypothesis_contrasts.png','figures/categorical_tail_checks.png'],claim_review='same-race absolute mass is not pure skeletal size; same-horse prior-only deviation; total time versus prepace conditional late and disjoint preceding400 fade; short/long direct contrasts; eight planned BH versus four post-primary exploratory BH; tail support and recent99-row limitation; race-selected normal starts and missing prior features;1900m+ excluded; causal/physiological/forecast/operational claims not established')
(O/'final_review.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');print('Final review PASS:',len(unchanged),'preserved,',len(raw)*len(cols),'SQL cells,',len(links),'links')

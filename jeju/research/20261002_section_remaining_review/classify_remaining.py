"""Adjudicate original flags against observed website rows, without correcting sources."""
import importlib.util,json,collections
from pathlib import Path
OUT=Path(__file__).resolve().parent
p=OUT.parents[2]/'jeju/research/20261002_section_passing_audit/root_audit/audit_corner.py'
spec=importlib.util.spec_from_file_location('corner_audit',p);audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
rows=json.loads((OUT/'order_flag_website_review.json').read_text());result=[]
for r in rows:
 groups=audit.parse_groups(r['website_group_raw']);assert groups is not None
 bounds={};pos=1
 for g in groups:
  for n in g:bounds[n]=(pos,pos+len(g)-1)
  pos+=len(g)
 num=int(r['program_no']);lo,hi=bounds[num];order=r['website_order']
 consistent=order is not None and lo<=order<=hi
 status='website_also_individual_vs_group_conflict' if not consistent else ('resolved_api303_point_disagreement' if not r['api303_matches_website_group'] else 'resolved_api4_website_order_disagreement')
 result.append({**r,'website_rank_min':lo,'website_rank_max':hi,'website_order_within_group_bounds':consistent,'adjudication':status})
counts=collections.Counter(r['adjudication'] for r in result)
races={s:len({(r['date'],r['race_no']) for r in result if r['adjudication']==s}) for s in counts}
remaining=[r for r in result if not r['website_order_within_group_bounds']]
all_runner=json.loads((OUT/'runner_website_comparisons.json').read_text());all_diffs=[r for r in all_runner if not r['orders_equal']]
positive=[r for r in all_diffs if r['api_order'] is not None and 0<r['api_order']<90]
sentinel=[r for r in all_diffs if r['api_order'] is not None and r['api_order']>=90]
identity=json.loads((OUT/'website_horse_identity_verification.json').read_text())
summary={'original_flag_observations':len(rows),'original_flag_races':len({(r['date'],r['race_no']) for r in rows}),'adjudication_counts':dict(counts),'adjudication_races':races,'website_confirmed_internal_conflict_observations':len(remaining),'website_confirmed_internal_conflict_points':len({(r['date'],r['race_no'],r['point']) for r in remaining}),'website_confirmed_internal_conflict_races':len({(r['date'],r['race_no']) for r in remaining}),'api_vs_website_positive_order_differences':len(positive),'api_vs_website_positive_order_difference_races':len({(r['date'],r['race_no']) for r in positive}),'api_99_vs_website_blank_observations':len(sentinel),'api_99_vs_website_blank_races':len({(r['date'],r['race_no']) for r in sentinel}),'website_horse_ids_equal':all(r['identity_equal'] for r in identity),'website_names_equal_ignoring_star_display_marker':all(r['name_equal_ignoring_leading_star_marker'] for r in identity),'positive_order_corrections_applied':False,'limits':'Website rank and same-website group disagree in remaining cases; correct alternative cannot be inferred. Group bounds are conservative and within-group exact ranks are not reconstructed.'}
for name,data in [('order_adjudications.json',result),('remaining_website_internal_order_conflicts.json',remaining),('positive_order_website_correction_candidates.json',positive),('special_order_sentinel_observations.json',sentinel),('adjudication_summary.json',summary)]:
 (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
print('remaining races',sorted({(r['date'],r['race_no']) for r in remaining}))

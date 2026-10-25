"""Post-fit coverage diagnostic: distinguish no eligible rows from no observed pair rows."""
from pathlib import Path
import json
import numpy as np,pandas as pd,duckdb
H=Path(__file__).resolve().parent;O=H/'outputs';R=H.parent

def main():
 d=pd.read_parquet(R/'20261012_planned_jockey_changes_by_stable/outputs/classified_starts.parquet');d['pair_key']=d.meet+':'+d.trainer_id+':'+d.jockey_id;four=pd.read_csv(O/'frozen_four_pairs.csv').pair_key.tolist();d=d[d.year.between(2019,2026)&d.pair_key.isin(four)].copy();d['primary_flag']=d.main_eligible&d.classification.eq('planned_as_card');d['expanded']=d.normal_outcome&d.identity_supported&d.stable_trainer&d.same_venue&d.gap_days.between(2,180)&d.classification.eq('planned_as_card');con=duckdb.connect();con.register('starts',d)
 rows=con.sql('''WITH pops AS (SELECT *, 'all_observed_pair_starts' population FROM starts UNION ALL SELECT *, 'all_as_card_pair_starts' population FROM starts WHERE classification='planned_as_card' UNION ALL SELECT *, 'primary' population FROM starts WHERE primary_flag UNION ALL SELECT *, 'expanded_no_annual_minimum' population FROM starts WHERE expanded)
 SELECT pair_key,year,population,CASE WHEN changed THEN 'switched' ELSE 'retained' END state,count(*) n,count(distinct horse_id) horses,count(distinct source_key) races,sum(top3) top3_events,avg(top3) top3_rate FROM pops GROUP BY pair_key,year,population,state''').df()
 grid=pd.MultiIndex.from_product([four,range(2019,2027),['all_observed_pair_starts','all_as_card_pair_starts','primary','expanded_no_annual_minimum'],['switched','retained']],names=['pair_key','year','population','state']);out=rows.set_index(list(grid.names)).reindex(grid).reset_index()
 for c in ['n','horses','races','top3_events']:out[c]=out[c].fillna(0).astype(int)
 # Independent direct masks confirm every SQL group including explicit zero rows.
 checks=0
 for r in out.itertuples():
  z=d[d.pair_key.eq(r.pair_key)&d.year.eq(r.year)&d.changed.eq(r.state=='switched')]
  if r.population=='all_as_card_pair_starts':z=z[z.classification.eq('planned_as_card')]
  elif r.population=='primary':z=z[z.primary_flag]
  elif r.population=='expanded_no_annual_minimum':z=z[z.expanded]
  assert [len(z),z.horse_id.nunique(),z.source_key.nunique(),int(z.top3.sum())]==[r.n,r.horses,r.races,r.top3_events];checks+=4
 assert not out[out.pair_key.eq('서울:070091:080562')&out.year.ge(2024)].n.any();assert not out[out.pair_key.eq('서울:070170:080515')&out.year.ge(2025)].n.any()
 out.to_csv(O/'population_coverage_diagnostic.csv',index=False);(O/'coverage_verification.json').write_text(json.dumps(dict(passed=True,checks=checks,diagnostic_created_after_main_results=True,not_a_new_adjusted_model=True,zero_pair_absences_confirmed_across_all_observed_starts=True),ensure_ascii=False,indent=2)+'\n');print(out[out.year.eq(2026)&out.population.eq('expanded_no_annual_minimum')].to_string(index=False))
if __name__=='__main__':main()

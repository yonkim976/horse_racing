"""Read-only feasibility audit; counts are observations or candidate tuples, not visits."""
from pathlib import Path
from bisect import bisect_left, bisect_right
from collections import defaultdict
import json
import duckdb

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / 'outputs'
OUT.mkdir(exist_ok=True)
c = duckdb.connect(str(ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'), read_only=True)

def rows(sql):
    cur = c.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]

result = {'status': 'feasibility_only_no_effect_estimates', 'audit_date': '2026-10-14'}
result['coverage'] = rows('''select meet_code, min(event_date) first_date, max(event_date) last_date,
 count(*) observations, count(distinct linked_horse_official_id) linked_horses,
 count(*) filter(where linked_horse_official_id is not null) linked_observations
 from medical_current_api_records group by 1 order by 1''')
result['medical_years'] = rows('''select substr(event_date,1,4) as event_year,meet_code,
 count(*) observations,count(distinct linked_horse_official_id) linked_horses
 from medical_current_api_records group by 1,2 order by 1,2''')
result['race_years'] = rows('''select substr(result_date,1,4) as race_year,source_meet,
 count(distinct horse_id_raw) horses from runner_results
 where result_date>='20180101' group by 1,2 order by 1,2''')
result['race_coverage'] = rows('''select source_meet,min(result_date) first_date,max(result_date) last_date,
 count(*) as result_rows from runner_results group by 1 order by 1''')
result['top_phrases'] = rows('''select illness_raw,count(*) observed_slots
 from medical_api16_current_phrase_review where illness_raw not in ('-','')
 group by 1 order by observed_slots desc,illness_raw limit 12''')
# Temporary views exist only in this connection. Exact tuple collapse does not identify episodes.
c.execute('''create temp view med as select distinct linked_horse_official_id id,
 cast(event_date as date) d,meet_code,hospital_name_raw,ill_name1_raw,ill_name2_raw
 from medical_current_api_records where linked_horse_official_id is not null''')
c.execute('''create temp view rr as select distinct horse_id_raw id,
 cast(strptime(result_date,'%Y%m%d') as date) d from runner_results
 where execution_status in ('executed_plan_and_result','executed_result_only_verified')
 and try_cast(result_rank_raw as integer)>0''')
c.execute('''create temp view linked as select m.*,p.d previous_date,n.d next_date
 from med m asof left join rr p on m.id=p.id and m.d>p.d
 asof left join rr n on m.id=n.id and m.d<n.d''')
result['tuple_linkage'] = rows('''select count(*) candidate_tuples,count(distinct id) horses,
 count(*) filter(where previous_date is not null) prior_race_available,
 count(*) filter(where next_date is not null) later_race_available,
 count(*) filter(where previous_date is not null and next_date is not null) both_available,
 count(*) filter(where next_date is null) no_later_race_in_snapshot
 from linked''')[0]
result['linkage_years'] = rows('''select year(d) as event_year, count(*) candidate_tuples,
 count(*) filter(where previous_date is not null and next_date is not null) both_available
 from linked group by 1 order by 1''')
result['checks'] = {
 'observations_equal_prior_load': sum(x['observations'] for x in result['coverage']) == 243411,
 'linked_equal_prior_load': sum(x['linked_observations'] for x in result['coverage']) == 238344,
 'tuple_count_not_above_linked': result['tuple_linkage']['candidate_tuples'] <= 238344,
 'both_not_above_later': result['tuple_linkage']['both_available'] <= result['tuple_linkage']['later_race_available'],
 'strict_temporal_order': c.execute('''select count(*) from linked where previous_date>=d or next_date<=d''').fetchone()[0] == 0,
 'asof_preserves_tuple_count': c.execute('select count(*) from med').fetchone()[0] == result['tuple_linkage']['candidate_tuples'],
}
dates = defaultdict(list)
for hid, day in c.execute('select id,d from rr order by id,d').fetchall():
    dates[hid].append(day)
checked = 0
for hid, day, before, after in c.execute('select id,d,previous_date,next_date from linked').fetchall():
    ds = dates[hid]
    lo, hi = bisect_left(ds, day), bisect_right(ds, day)
    assert before == (ds[lo-1] if lo else None)
    assert after == (ds[hi] if hi<len(ds) else None)
    checked += 1
result['independent_bisect_checks'] = checked * 2
result['checks']['independent_dates_agree'] = checked == result['tuple_linkage']['candidate_tuples']
assert all(result['checks'].values())
(OUT / 'feasibility.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result['tuple_linkage'],ensure_ascii=False))
c.close()

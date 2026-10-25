"""Reconcile published numerical tables against the preserved source snapshot."""
from pathlib import Path
import hashlib
import json
import math
import sqlite3

import numpy as np
import pandas as pd

H = Path(__file__).resolve().parent
O = H/'reviewed_run02'
KEYS = ['era','race_distance_m','rank_class_raw','track_state']
FIELDS = ['finish_time_seconds','s1f_time_seconds','c1_time_seconds','c2_time_seconds',
          'c3_time_seconds','c4_time_seconds','g3f_time_seconds','g1f_time_seconds']


def percentile(y, probability):
    a = sorted(y)
    position = (len(a)-1)*probability
    left = math.floor(position)
    right = math.ceil(position)
    return a[left]*(right-position)+a[right]*(position-left) if right != left else a[left]


def close(left, right):
    assert abs(float(left)-float(right)) < 2e-7, (left,right)


def main():
    receipt = json.loads((H/'extraction.json').read_text())
    raw = pd.read_parquet(H/'source_rows.parquet')
    a = pd.read_csv(O/'analysis_rows.csv',dtype={'horse_id':str})
    cells = pd.read_csv(O/'cell_benchmarks.csv')
    flags = pd.read_csv(O/'outlier_candidates.csv',dtype={'horse_id':str})
    assert raw.api_record_id.is_unique and a.api_record_id.is_unique
    expected = raw[raw.finish_position.between(1,89)&raw.finish_time_seconds.gt(0)&raw.race_distance_m.isin([800,900,1000,1110,1200,1300,1400,1610])]
    assert set(expected.api_record_id) == set(a.api_record_id)
    assert not a.horse_id.eq('3005648').any()
    assert raw.loc[(raw.race_date.eq('2026-01-17'))&raw.race_number.eq(5)&raw.horse_id.eq('3016494'),'g1f_time_seconds'].isna().all()
    for date, horse, field, value in [('2024-03-02','3018048','s1f_time_seconds',20),('2025-10-17','3017473','s1f_time_seconds',17.8),('2026-03-06','3018729','g1f_time_seconds',16)]:
        close(raw.loc[raw.race_date.eq(date)&raw.horse_id.eq(horse),field].iloc[0],value)
    connection = sqlite3.connect(':memory:')
    a.to_sql('observations',connection,index=False)
    computed = pd.read_sql_query('''SELECT era,race_distance_m,rank_class_raw,track_state,
      COUNT(*) n,COUNT(DISTINCT race_id) races,COUNT(DISTINCT race_date) dates,
      AVG(finish_time_seconds) mean_s FROM observations GROUP BY era,race_distance_m,rank_class_raw,track_state''',connection)
    full = cells[cells.time_field.eq('finish_time_seconds')]
    cmp = full.merge(computed,on=KEYS,validate='one_to_one',suffixes=('_saved','_sql'))
    for field in ['n','races','dates','mean_s']:
        assert np.allclose(cmp[field+'_saved'],cmp[field+'_sql'],atol=2e-7,rtol=0)
    groups = {k:g for k,g in a.groupby(KEYS)}
    expected_flags = set()
    checked = 0
    for row in cells.itertuples():
        key = tuple(getattr(row,k) for k in KEYS)
        g = groups[key]
        vals = g[row.time_field].dropna()
        assert len(vals) == row.n
        if not len(vals):
            assert not row.supported
            continue
        y = vals.tolist()
        close(sum(y)/len(y),row.mean_s)
        close(percentile(y,.5),row.median_s)
        q1,q3 = percentile(y,.25),percentile(y,.75)
        close(q1,row.p25_s);close(q3,row.p75_s)
        checked += 1
        if row.supported:
            review,extreme = q3+1.5*(q3-q1),q3+3*(q3-q1)
            mild = [v for v in y if v<=review+1e-9]
            strong = [v for v in y if v<=extreme+1e-9]
            close(sum(mild)/len(mild),row.mean_without_review_s)
            close(sum(strong)/len(strong),row.mean_without_extreme_s)
            for index,value in vals.items():
                if value>review+1e-9:
                    expected_flags.add((int(a.at[index,'api_record_id']),row.time_field,value>extreme+1e-9))
    actual_flags = set(zip(flags.api_record_id,flags.time_field,flags.extreme_candidate))
    assert actual_flags == expected_flags
    for field in FIELDS[1:]:
        prefix = field.replace('_time_seconds','')
        status = prefix+'_order_status'
        if status not in raw:
            continue
        bad = raw[raw[status].fillna('').str.contains('conflict|not_applied|source_changed',regex=True)]
        bad_keys = set(zip(bad.race_date,bad.meet_code,bad.race_number))
        masked = a.apply(lambda r:(r.race_date,r.meet_code,r.race_number) in bad_keys,axis=1)
        assert a.loc[masked,field].isna().all()
        good_ids = a.loc[~masked,'api_record_id']
        src = raw.set_index('api_record_id').loc[good_ids,field].to_numpy(float)
        got = a.loc[~masked,field].to_numpy(float)
        assert np.allclose(src,got,equal_nan=True,atol=2e-7)
    # Recent figures must use the recent population, not a relabelled full-period table.
    recent = pd.read_csv(O/'recent_cell_benchmarks.csv')
    for row in recent[recent.time_field.eq('finish_time_seconds')].itertuples():
        z = groups[tuple(getattr(row,k) for k in KEYS)]
        z = z[z.year.ge(2024 if row.period=='2024plus' else 2026)]
        assert len(z)==row.n
        close(z.finish_time_seconds.mean(),row.mean_s)
    with Path(receipt['db_path']).open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest()==receipt['db_sha256']
    with (H/'source_rows.parquet').open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest()==receipt['snapshot_sha256']
    result = {'status':'passed','source_population_reconciled':True,'corrected_three_times_and_one_null_preserved':True,
              'all_disputed_race_points_held':True,'sqlite_group_mean_count_checks':len(cmp),
              'manual_sorted_quantile_and_mean_checks':checked,'outlier_observations_verified':len(actual_flags),
              'recent_population_verified':True,'database_and_snapshot_unchanged':True}
    with (O/'verification.json').open('x') as stream:
        json.dump(result,stream,indent=2)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()

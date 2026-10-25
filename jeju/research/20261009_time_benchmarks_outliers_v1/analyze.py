"""Descriptive Jeju time tables; source snapshot and database are immutable inputs."""
from pathlib import Path
import hashlib
import json
import math
import re

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'reviewed_run02'
FIELDS = ['finish_time_seconds', 's1f_time_seconds', 'c1_time_seconds',
          'c2_time_seconds', 'c3_time_seconds', 'c4_time_seconds',
          'g3f_time_seconds', 'g1f_time_seconds']
KEYS = ['era', 'race_distance_m', 'rank_class_raw', 'track_state']
DISTANCES = [800, 900, 1000, 1110, 1200, 1300, 1400, 1610]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save_json(name, obj):
    with (OUT / name).open('x', encoding='utf-8') as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)


def save_csv(name, frame):
    with (OUT / name).open('x', encoding='utf-8') as stream:
        frame.to_csv(stream, index=False, float_format='%.8f')


def next_tenth(value):
    # Observed times have tenth-second precision. A fence is exceeded strictly.
    return (math.floor((value + 1e-9) * 10) + 1) / 10


def summary(g, field):
    z = g[g[field].notna() & g[field].gt(0)].copy()
    out = {'time_field': field, 'eligible_starts': len(g), 'n': len(z),
           'missing_n': len(g)-len(z), 'races': z.race_id.nunique(),
           'dates': z.race_date.nunique(), 'horses': z.horse_id.nunique(),
           'first_date': z.race_date.min() if len(z) else None,
           'last_date': z.race_date.max() if len(z) else None}
    if not len(z):
        return out | {'supported': False, 'support_status': 'no_observation'}
    y = z[field].to_numpy(float)
    p10, q1, median, q3, p90, p95, p99 = np.quantile(y, [.1, .25, .5, .75, .9, .95, .99], method='linear')
    iqr = q3-q1
    mild, extreme = q3+1.5*iqr, q3+3*iqr
    supported = len(z) >= 100 and out['races'] >= 10 and out['dates'] >= 10 and iqr > 0
    mean = y.mean()
    clusters = z.assign(score=y-mean).groupby('race_date').score.sum().to_numpy()
    dates = len(clusters)
    se = np.sqrt(dates/(dates-1) * (clusters@clusters)/len(y)**2) if dates > 1 else np.nan
    width = t.ppf(.975, dates-1)*se if dates > 1 else np.nan
    a = y <= mild+1e-9
    b = y <= extreme+1e-9
    return out | {'supported': supported, 'support_status': 'reference_supported' if supported else 'limited_sample',
                  'mean_s': mean, 'mean_ci95_lo_s': mean-width, 'mean_ci95_hi_s': mean+width,
                  'sd_s': np.std(y, ddof=1) if len(y)>1 else np.nan,
                  'p10_s': p10, 'p25_s': q1, 'median_s': median, 'p75_s': q3,
                  'p90_s': p90, 'p95_s': p95, 'p99_s': p99, 'min_s': y.min(), 'max_s': y.max(),
                  'iqr_s': iqr, 'review_fence_raw_s': mild, 'extreme_fence_raw_s': extreme,
                  'review_from_s': next_tenth(mild) if supported else np.nan,
                  'extreme_from_s': next_tenth(extreme) if supported else np.nan,
                  'review_candidates_n': int((~a).sum()) if supported else np.nan,
                  'extreme_candidates_n': int((~b).sum()) if supported else np.nan,
                  'review_candidates_pct': 100*(~a).mean() if supported else np.nan,
                  'extreme_candidates_pct': 100*(~b).mean() if supported else np.nan,
                  'mean_without_review_s': y[a].mean() if supported else np.nan,
                  'mean_without_extreme_s': y[b].mean() if supported else np.nan,
                  'review_removal_shift_s': mean-y[a].mean() if supported else np.nan,
                  'extreme_removal_shift_s': mean-y[b].mean() if supported else np.nan,
                  'fast_outer_candidates_n': int((y<q1-3*iqr-1e-9).sum()) if supported else np.nan}


def table(d, keys):
    rows = []
    for key, g in d.groupby(keys, dropna=False, sort=True):
        if not isinstance(key, tuple):
            key = (key,)
        for field in FIELDS:
            rows.append(dict(zip(keys, key)) | summary(g, field))
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(exist_ok=False)
    receipt = json.loads((HERE/'extraction.json').read_text())
    assert sha(HERE/'source_rows.parquet') == receipt['snapshot_sha256']
    d = pd.read_parquet(HERE/'source_rows.parquet')
    assert d.api_record_id.is_unique
    assert not d.duplicated(['race_date', 'meet_code', 'race_number', 'horse_id']).any()
    assert not d.horse_id.astype(str).eq('3005648').any()
    d['race_id'] = d.race_date + '_' + d.meet_code.astype(str) + '_' + d.race_number.astype(str)
    d['year'] = d.race_date.str[:4].astype(int)
    d['era'] = np.where(d.year.lt(2019), '2017_2018', '2019plus')
    labels = d.track_raw.fillna('').str.extract(r'^\s*(건조|양호|다습|포화|불량)\s*')[0]
    d['track_state'] = labels.fillna('unknown')
    d['moisture_pct'] = pd.to_numeric(d.track_raw.fillna('').str.extract(r'(\d+(?:\.\d+)?)\s*%')[0], errors='coerce')
    band = pd.cut(d.moisture_pct, [0,5,9,14,19,100], labels=['건조','양호','다습','포화','불량'])
    d['track_label_numeric_agree'] = band.astype(str).eq(d.track_state)
    save_csv('track_inventory.csv', d.groupby(['track_raw','track_state','moisture_pct','track_label_numeric_agree'],dropna=False).agg(n=('api_record_id','size')).reset_index())
    d['rank_class_raw'] = d.rank_class_raw.fillna('(unknown)')
    valid = d.finish_position.between(1,89) & d.finish_time_seconds.gt(0)
    current = d.race_distance_m.isin(DISTANCES)
    save_csv('population_ledger.csv', d[['api_record_id','race_id','race_date','horse_id','race_distance_m','finish_position','finish_time_seconds']].assign(valid_finish=valid,current_distance=current,included=valid&current))
    base = d[valid & current].copy()
    quality = []
    for field in FIELDS[1:]:
        prefix = field.replace('_time_seconds', '')
        status = prefix+'_time_status'
        for value, g in base.groupby(status,dropna=False):
            quality.append({'time_field':field, 'source_time_status':value, 'rows':len(g), 'positive_values':int(g[field].gt(0).sum())})
        # Quarantined rank/group conflicts also make exact timing at that point uncertain.
        order = prefix+'_order_status'
        if order in d:
            conflict = d[order].fillna('').str.contains('conflict|not_applied|source_changed', regex=True)
            # Hold every observed runner's timing at the same disputed race point,
            # including when the flagged runner itself has a special final status.
            conflict_races = set(d.loc[conflict, 'race_id'])
            blocked = base.race_id.isin(conflict_races)
        else:
            blocked = pd.Series(False, index=base.index)
        quality.append({'time_field':field,'source_time_status':'additional_point_conflict_hold','rows':int(blocked.sum()),'positive_values':int((blocked&base[field].gt(0)).sum())})
        base.loc[blocked,field] = np.nan
        base.loc[~base[field].gt(0),field] = np.nan
    save_csv('time_quality_inventory.csv',pd.DataFrame(quality))
    save_csv('grade_support.csv',base.groupby(['era','year','rank_class_raw']).agg(n=('api_record_id','size'),races=('race_id','nunique')).reset_index())
    assert not (base.track_state.ne('unknown') & ~base.track_label_numeric_agree).any()
    save_csv('analysis_rows.csv',base)
    cell = table(base,KEYS)
    save_csv('cell_benchmarks.csv',cell)
    # Recent periods are separate reference populations; no era mixing.
    recent = []
    for name, start in [('2024plus',2024),('2026partial',2026)]:
        recent.append(table(base[base.year.ge(start)],KEYS).assign(period=name))
    save_csv('recent_cell_benchmarks.csv',pd.concat(recent,ignore_index=True))
    save_csv('annual_cell_benchmarks.csv',table(base,['year']+KEYS))
    save_csv('distance_overview.csv',table(base,['era','race_distance_m']))
    flags = []
    common = []
    for key, g in base.groupby(KEYS,dropna=False):
        rows = cell
        for col, value in zip(KEYS,key):
            rows = rows[rows[col].eq(value)]
        full = rows[rows.time_field.eq(FIELDS[0])].iloc[0]
        if full.supported:
            keep = g.finish_time_seconds.le(full.extreme_fence_raw_s+1e-9)
            for field in FIELDS:
                z = g.loc[keep,field].dropna()
                common.append(dict(zip(KEYS,key)) | {'time_field':field,'excluded_full_extreme_n':int((~keep).sum()),'remaining_starts':int(keep.sum()),'field_n':len(z),'mean_s':z.mean() if len(z) else np.nan})
        for row in rows.itertuples():
            if not row.supported:
                continue
            z = g[g[row.time_field].gt(row.review_fence_raw_s+1e-9)]
            for obs in z.itertuples():
                val = getattr(obs,row.time_field)
                flags.append(dict(zip(KEYS,key)) | {'api_record_id':obs.api_record_id,'race_id':obs.race_id,'race_date':obs.race_date,'horse_id':obs.horse_id,'horse_name':obs.horse_name,'horse_number':obs.horse_number,'finish_position':obs.finish_position,'time_field':row.time_field,'time_s':val,'review_from_s':row.review_from_s,'extreme_from_s':row.extreme_from_s,'extreme_candidate':bool(val>row.extreme_fence_raw_s+1e-9),'cell_n':row.n,'seconds_above_median':val-row.median_s})
    flags = pd.DataFrame(flags)
    save_csv('outlier_candidates.csv',flags)
    save_csv('sections_without_full_extreme.csv',pd.DataFrame(common))
    finish = cell[cell.time_field.eq(FIELDS[0])]
    supported = finish[finish.supported]
    save_json('summary.json',{
        'source_rows':len(d),'included_rows':len(base),'included_races':base.race_id.nunique(),
        'included_dates':base.race_date.nunique(),'included_horses':base.horse_id.nunique(),
        'invalid_finish_n':int((~valid).sum()),'warmup_valid_finish_n':int((valid&~current).sum()),
        'first_date':base.race_date.min(),'last_date':base.race_date.max(),
        'finish_cells':len(finish),'supported_finish_cells':len(supported),
        'supported_finish_starts':int(supported.n.sum()),
        'review_finish_candidates':int(supported.review_candidates_n.sum()),
        'extreme_finish_candidates':int(supported.extreme_candidates_n.sum()),
        'weighted_review_mean_shift_s':float(np.average(supported.review_removal_shift_s,weights=supported.n)),
        'weighted_extreme_mean_shift_s':float(np.average(supported.extreme_removal_shift_s,weights=supported.n)),
        'no_global_seconds_cutoff_adopted':True,'database_sha256':receipt['db_sha256']})
    db = Path(receipt['db_path'])
    assert sha(db) == receipt['db_sha256']
    print(json.dumps(json.loads((OUT/'summary.json').read_text()),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()

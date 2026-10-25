"""Compare preserved Jeju records across years and late-year months."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd
from scipy.stats import t

H = Path(__file__).resolve().parent
ROOT = H.parents[2]
SOURCE = H.parent/'20261009_time_benchmarks_outliers_v1/reviewed_run02/analysis_rows.csv'
FIELDS = ['finish_time_seconds','s1f_time_seconds','c1_time_seconds','c2_time_seconds',
          'c3_time_seconds','c4_time_seconds','g3f_time_seconds','g1f_time_seconds']
KEYS = ['race_distance_m','rank_class_raw','track_state']


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def save(name, value):
    with (H/name).open('x',encoding='utf-8') as stream:
        if isinstance(value,pd.DataFrame):
            value.to_csv(stream,index=False,float_format='%.9f')
        else:
            json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)


def aggregate(d, keys):
    long = d.melt(id_vars=list(dict.fromkeys(keys+['race_id','race_date','horse_id'])),
                  value_vars=FIELDS,var_name='time_field',value_name='time_s').dropna(subset=['time_s'])
    return long.groupby(keys+['time_field'],dropna=False).agg(
        n=('time_s','size'),races=('race_id','nunique'),dates=('race_date','nunique'),
        horses=('horse_id','nunique'),mean_s=('time_s','mean'),median_s=('time_s','median'),
        first_date=('race_date','min'),last_date=('race_date','max')).reset_index()


def contrast(z, left_mask, right_mask, strata, label, dist, field, detail):
    left = z.loc[left_mask].dropna(subset=[field]).copy()
    right = z.loc[right_mask].dropna(subset=[field]).copy()
    def stats(a):
        return a.groupby(strata).agg(n=(field,'size'),races=('race_id','nunique'),
                                      dates=('race_date','nunique'),mean_s=(field,'mean'),median_s=(field,'median'))
    both = stats(left).join(stats(right),how='inner',lsuffix='_left',rsuffix='_right')
    support = (both.n_left.ge(30)&both.n_right.ge(30)&both.races_left.ge(5)&
               both.races_right.ge(5)&both.dates_left.ge(5)&both.dates_right.ge(5))
    supported = both.loc[support].copy()
    base = {'comparison':label,'race_distance_m':dist,'time_field':field,
            'strata':'+'.join(strata),'available_n_left':len(left),'available_n_right':len(right),
            'raw_mean_left_s':left[field].mean() if len(left) else np.nan,
            'raw_mean_right_s':right[field].mean() if len(right) else np.nan,
            'common_cells':len(supported),'supported':len(supported)>0}
    if supported.empty:
        return base
    supported['weight'] = (supported.n_left+supported.n_right)/(supported.n_left+supported.n_right).sum()
    point = float(supported.weight @ (supported.mean_right_s-supported.mean_left_s))
    lmean = float(supported.weight @ supported.mean_left_s)
    rmean = float(supported.weight @ supported.mean_right_s)
    contributions = []
    counts=[]
    for sample, side, sign in [(left,'left',-1),(right,'right',1)]:
        x = sample.merge(supported.reset_index(),on=strata,how='inner',validate='many_to_one')
        x['influence'] = sign*x.weight*(x[field]-x['mean_s_'+side])/x['n_'+side]
        contributions.append(x.groupby('race_date').influence.sum())
        counts.append((len(x),x.race_id.nunique(),x.race_date.nunique()))
    # The recent group is part of the full group in one contrast. Summing by
    # original date preserves covariance from the overlapping observations.
    combined = pd.concat(contributions,axis=1).fillna(0).sum(axis=1)
    days = len(combined)
    se = np.sqrt(days/(days-1)*float(combined@combined)) if days>1 else np.nan
    width = t.ppf(.975,days-1)*se if days>1 else np.nan
    x=supported.reset_index().assign(comparison=label,race_distance_m=dist,time_field=field)
    x['difference_s']=x.mean_right_s-x.mean_left_s
    detail.append(x)
    return base | {'n_left':counts[0][0],'n_right':counts[1][0],
                   'races_left':counts[0][1],'races_right':counts[1][1],
                   'dates_left':counts[0][2],'dates_right':counts[1][2],
                   'standard_mean_left_s':lmean,'standard_mean_right_s':rmean,
                   'difference_right_minus_left_s':point,'ci95_lo_s':point-width,'ci95_hi_s':point+width,
                   'weighted_cell_median_difference_s':float(supported.weight@(supported.median_right_s-supported.median_left_s))}


def main():
    plan={'source':str(SOURCE.relative_to(ROOT)),'period_start':'2019-01-01','period_end':'2026-09-19',
          'recent_three_calendar_years':'2024-01-01 through available 2026-09-19; not three complete years',
          'year_season_comparisons':'each 2019..2025 October-December vs January-September, plus July-September',
          'october_only':'each 2019..2025 October vs July-September',
          'same_calendar_window':'January1..September19 in every year; additionally common month strata',
          'grouping':'exact distance,original grade,track state,time field; year strata for pooled season comparisons',
          'minimum_per_side_per_stratum':'30 observations,5 races,5 race dates; analyst reference support policy',
          'standard_weights':'pooled two-side observation counts on common supported strata, fixed across both means',
          'difference_sign':'right minus left seconds; negative=faster right period',
          'uncertainty':'race-date cluster t approximation including overlap covariance; no multiple-comparison testing claims',
          'limitations':'unadjusted for horse ability,burden,field composition; descriptive,not causal or prospective',
          'quality':'inherit reviewed_run02 point holds,corrections,exclusions; no additional trimming',
          '2026_october_observed':False}
    save('PLAN.json',plan)
    source_sha=sha(SOURCE)
    d=pd.read_csv(SOURCE,dtype={'horse_id':str})
    d=d[d.year.ge(2019)].copy()
    assert d.api_record_id.is_unique and d.race_date.max()=='2026-09-19'
    assert not d.horse_id.eq('3005648').any()
    d['month']=d.race_date.str[5:7].astype(int)
    d['month_day']=d.race_date.str[5:10]
    d['quarter']=np.where(d.month.ge(10),'Oct_Dec',np.where(d.month.ge(7),'Jul_Sep','Jan_Jun'))
    save('source_manifest.json',{'source_path':str(SOURCE),'source_sha256':source_sha,'source_rows':len(d),
         'prior_quality_report':'../20261009_time_benchmarks_outliers_v1/README.md',
         'source_database_sha256':json.loads((SOURCE.parent/'summary.json').read_text())['database_sha256'],
         'source_api_record_ids':d.api_record_id.astype(int).tolist()})
    save('year_month_cells.csv',aggregate(d,['year','month']+KEYS))
    save('annual_cells.csv',aggregate(d,['year']+KEYS))
    periods=[]
    for name,mask in [('2019_2026_available',d.year.ge(2019)),('2024_2026_available',d.year.ge(2024)),
                      ('2019_2023',d.year.le(2023)),('2019_2025_same_Jan1_Sep19',d.year.le(2025)&d.month_day.le('09-19')),
                      ('2026_same_Jan1_Sep19',d.year.eq(2026)&d.month_day.le('09-19'))]:
        periods.append(aggregate(d.loc[mask],KEYS).assign(period=name))
    save('period_cells.csv',pd.concat(periods,ignore_index=True))
    season=[]
    for name,mask in [('Jan_Sep',d.month.le(9)),('Jul_Sep',d.month.between(7,9)),
                      ('October',d.month.eq(10)),('Oct_Dec',d.month.ge(10))]:
        season.append(aggregate(d.loc[mask],['year']+KEYS).assign(season=name))
    save('season_cells.csv',pd.concat(season,ignore_index=True))
    out=[];details=[]
    for dist,z in d.groupby('race_distance_m'):
        for field in FIELDS:
            def add(label,left,right,strata):
                out.append(contrast(z,left,right,strata,label,int(dist),field,details))
            ordinary=['rank_class_raw','track_state']
            add('recent3_vs_full',z.year.ge(2019),z.year.ge(2024),ordinary)
            add('recent3_vs_2019_2023',z.year.le(2023),z.year.ge(2024),ordinary)
            add('2026_vs_history_same_Jan1_Sep19',z.year.le(2025)&z.month_day.le('09-19'),z.year.eq(2026),ordinary)
            add('2026_vs_history_same_Jan1_Sep19_month_matched',z.year.le(2025)&z.month_day.le('09-19'),z.year.eq(2026),ordinary+['month'])
            historic=z.year.le(2025)
            add('pooled_Q4_vs_JanSep',historic&z.month.le(9),historic&z.month.ge(10),['year']+ordinary)
            add('pooled_Q4_vs_JulSep',historic&z.month.between(7,9),historic&z.month.ge(10),['year']+ordinary)
            add('pooled_October_vs_JulSep',historic&z.month.between(7,9),historic&z.month.eq(10),['year']+ordinary)
            for year in range(2019,2026):
                mask=z.year.eq(year)
                add(f'{year}_Q4_vs_JanSep',mask&z.month.le(9),mask&z.month.ge(10),ordinary)
                add(f'{year}_Q4_vs_JulSep',mask&z.month.between(7,9),mask&z.month.ge(10),ordinary)
    save('standardized_comparisons.csv',pd.DataFrame(out))
    save('common_cell_contributions.csv',pd.concat(details,ignore_index=True))
    assert sha(SOURCE)==source_sha
    save('run_summary.json',{'source_rows':len(d),'races':d.race_id.nunique(),'dates':d.race_date.nunique(),
                           'last_date':d.race_date.max(),'comparisons':len(out),
                           'supported_comparisons':sum(x['supported'] for x in out),'source_unchanged':True,
                           '2026_Q4_rows':int((d.year.eq(2026)&d.month.ge(10)).sum())})
    print(pd.DataFrame(out).query("time_field=='finish_time_seconds' and comparison in ['recent3_vs_full','pooled_Q4_vs_JanSep','2026_vs_history_same_Jan1_Sep19_month_matched']")[[
        'comparison','race_distance_m','common_cells','n_left','n_right','difference_right_minus_left_s','ci95_lo_s','ci95_hi_s']].to_string(index=False))


if __name__=='__main__':
    main()

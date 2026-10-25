"""Frozen Busan S1F leader-pack outcomes; descriptive statistics only."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
BASE = R / '20261008_running_style_foundation/outputs/observed_styles.parquet'
GROUPS = R / '20261008_passing_group_style/outputs/observations.parquet'
SNAP = R / '20261002_moisture_position/outputs/passing_snapshot.parquet'
DISTANCES = [1000, 1200, 1300, 1400, 1500, 1600, 1800, 1900, 2000, 2200]
PERIODS = ['all', '2024', '2025', '2024_2025', '2026']
SCOPES = ['normal_complete', 'all_known_outcomes', 'normal_no_ties']


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                     allow_nan=False) + '\n')


def check_inputs():
    for name, expected in json.loads((OUT / 'input_manifest.json').read_text()).items():
        path = ROOT / name
        assert path.stat().st_size == expected['bytes'] and sha(path) == expected['sha256'], name
    prior = json.loads((R / '20261008_passing_group_style/outputs/source_audit.json').read_text())
    for path in [BASE, SNAP]:
        assert sha(path) == prior['inputs'][str(path.relative_to(ROOT))]
    assert json.loads((R / '20261008_passing_group_style/outputs/verification.json').read_text())['passed']


def load():
    columns = ['row_key', 'source_key', 'horse_id', 'horse_name', 'meet', 'date',
               'year', 'day_key', 'distance_m', 'field_size', 'gate', 'rank',
               'source_file', 'source_item_index', 'grade_normalized']
    d = pd.read_parquet(BASE, columns=columns)
    d = d[d.meet.eq('부산')].copy()
    group_columns = ['row_key', 'group_observed', 'first_group', 'group_index',
                     'first_group_size', 'notation_raw', 'selected_source',
                     'selection_status', 'leader_conflict_race']
    d = d.merge(pd.read_parquet(GROUPS, columns=group_columns),
                on='row_key', validate='one_to_one')
    assert len(d) == 66240 and d.source_key.nunique() == 6053
    assert not d.duplicated(['source_key', 'gate']).any()
    assert d.groupby('source_key').size().eq(d.groupby('source_key').field_size.first()).all()
    d['normal'] = d['rank'].between(1, 30)
    d['known_outcome'] = d.normal | d['rank'].isin([91, 92])
    d['top3'] = d['rank'].between(1, 3)
    d['win'] = d['rank'].eq(1)
    audit = []
    for key, g in d.groupby('source_key', sort=True):
        valid = bool(g.group_observed.all()) and not bool(g.leader_conflict_race.any())
        normal = bool(g.normal.all())
        known = bool(g.known_outcome.all())
        same_rank = bool(g.loc[g.normal, 'rank'].duplicated().any())
        a = dict(source_key=key, date=g.date.iloc[0].strftime('%Y-%m-%d'),
                 year=int(g.year.iloc[0]), distance=int(g.distance_m.iloc[0]),
                 field_size=len(g), normal_complete=valid and normal,
                 all_known_outcomes=valid and known,
                 normal_no_ties=valid and normal and not same_rank,
                 valid_s1f=valid, normal=normal, known_outcome=known,
                 duplicate_finish_rank=same_rank, nonnormal_count=int((~g.normal).sum()),
                 whole_race_top3=int(g.top3.sum()), whole_race_winners=int(g.win.sum()),
                 exclusion_reason='retained' if valid and normal else
                 'invalid_s1f' if not valid else 'nonnormal_outcome')
        audit.append(a)
    audit = pd.DataFrame(audit)
    assert audit.normal_complete.sum() == 5891
    d = d.merge(audit[['source_key'] + SCOPES + ['duplicate_finish_rank']],
                on='source_key', validate='many_to_one')
    leaders = d[d.all_known_outcomes & d.first_group.eq(True)].copy()
    leaders['leader_count'] = leaders.first_group_size.astype(int)
    assert leaders.groupby('source_key').size().eq(leaders.groupby('source_key').leader_count.first()).all()
    leaders['distance'] = leaders.distance_m.astype(int)
    leaders['compact_count'] = np.where(leaders.leader_count.ge(3), '3+', leaders.leader_count.astype(str))
    leaders['date'] = leaders.date.dt.strftime('%Y-%m-%d')
    races = []
    for key, g in leaders.groupby('source_key', sort=True):
        a = audit.set_index('source_key').loc[key].to_dict()
        a.update(source_key=key, leader_count=int(g.leader_count.iloc[0]),
                 compact_count=g.compact_count.iloc[0], top3_count=int(g.top3.sum()),
                 winner_count=int(g.win.sum()), group_win=bool(g.win.any()),
                 notation_raw=g.notation_raw.iloc[0], selected_source=g.selected_source.iloc[0],
                 selection_status=g.selection_status.iloc[0],
                 leader_programs=','.join(str(int(x)) for x in g.gate),
                 leader_ids=','.join(g.horse_id),
                 leader_names='|'.join(g.horse_name),
                 leader_finishes=','.join(str(int(x)) for x in g['rank']))
        races.append(a)
    races = pd.DataFrame(races)
    assert races.leader_count.between(1, 10).all()
    return audit, leaders, races


def period(frame, value):
    if value == 'all':
        return frame
    if value == '2024_2025':
        return frame[frame.year.between(2024, 2025)]
    return frame[frame.year.eq(int(value))]


def ci(frame, outcome, cluster):
    n = len(frame)
    if not n:
        return (None, None)
    y = frame[outcome].to_numpy(float)
    codes, ids = pd.factorize(frame[cluster])
    k = len(ids)
    if k < 2:
        return (None, None)
    residual_sum = np.bincount(codes, weights=y-y.mean())
    se = np.sqrt(k/(k-1) * np.sum(residual_sum**2) / n**2)
    half = t.ppf(.975, k-1) * se
    return (float(max(0, y.mean()-half)*100), float(min(1, y.mean()+half)*100))


def row(races, starts, metadata, confidence):
    n = len(races)
    e = len(starts)
    k = int(races.top3_count.sum())
    w = int(races.winner_count.sum())
    c = [int(races.top3_count.eq(i).sum()) for i in range(5)]
    assert sum(c) == n and sum(i*c[i] for i in range(5)) == k
    assert e == int(races.leader_count.sum()) and k == int(starts.top3.sum()) and w == int(starts.win.sum())
    r = dict(metadata, races=n, leader_starts=e, top3_horses=k, winner_horses=w,
             group_win_races=int(races.group_win.sum()), days=races.date.nunique(),
             horses=starts.horse_id.nunique(),
             duplicate_rank_races=int(races.duplicate_finish_rank.sum()),
             multiple_winner_races=int(races.winner_count.gt(1).sum()),
             extra_winners_beyond_group_event=int((races.winner_count-races.group_win.astype(int)).sum()),
             two_plus_top3_races=sum(c[2:]), any_top3_races=n-c[0],
             first_date=None if not n else races.date.min(),
             last_date=None if not n else races.date.max(),
             sample_status='무표본' if not n else '소표본' if e < 100 or n < 30 or races.date.nunique() < 20 else '기준 충족')
    for i in range(5):
        r[f'exact{i}_top3_races'] = c[i]
        r[f'exact{i}_top3_pct'] = 100*c[i]/n if n else None
    for name, num, den in [('individual_top3_pct', k, e), ('individual_win_pct', w, e),
                           ('group_win_pct', r['group_win_races'], n),
                           ('two_plus_top3_pct', sum(c[2:]), n),
                           ('any_top3_pct', n-c[0], n)]:
        r[name] = 100*num/den if den else None
    if confidence:
        for outcome in ['top3', 'win']:
            for cluster in ['date', 'horse_id']:
                lo, hi = ci(starts, outcome, cluster)
                r[f'{outcome}_{cluster}_lower95'] = lo
                r[f'{outcome}_{cluster}_upper95'] = hi
    return r


def aggregate(races, starts, compact=False):
    rows = []
    values = ['1', '2', '3+'] if compact else list(range(1, 11))
    col = 'compact_count' if compact else 'leader_count'
    for scope in SCOPES:
        for window in PERIODS:
            ar = period(races[races[scope]], window)
            ast = period(starts[starts[scope]], window)
            for dist in ['all'] + DISTANCES:
                dr = ar if dist == 'all' else ar[ar.distance.eq(dist)]
                ds = ast if dist == 'all' else ast[ast.distance.eq(dist)]
                for count in values:
                    z = dr[dr[col].eq(count)]
                    s = ds[ds[col].eq(count)]
                    rows.append(row(z, s, dict(scope=scope, period=window, distance=str(dist),
                                               leader_count=str(count)), confidence=scope == 'normal_complete'))
    return pd.DataFrame(rows)


def main():
    check_inputs()
    audit, leaders, races = load()
    audit.to_csv(OUT/'race_audit.csv', index=False, encoding='utf-8-sig')
    leaders.to_parquet(OUT/'leader_starts.parquet', index=False)
    races.to_csv(OUT/'race_outcomes.csv', index=False, encoding='utf-8-sig')
    exact = aggregate(races, leaders)
    compact = aggregate(races, leaders, compact=True)
    exact.to_csv(OUT/'exact_rates.csv', index=False, encoding='utf-8-sig')
    compact.to_csv(OUT/'compact_rates.csv', index=False, encoding='utf-8-sig')
    main_rates = exact[exact.scope.eq('normal_complete') & exact.period.eq('all')]
    main_rates.to_csv(OUT/'distance_size_main.csv', index=False, encoding='utf-8-sig')
    fields = []
    for window in ['all', '2026']:
        rs = period(races[races.normal_complete], window)
        ls = period(leaders[leaders.normal_complete], window)
        for field, g in rs.groupby('field_size'):
            for count in ['1', '2', '3+']:
                z = g[g.compact_count.eq(count)]
                s = ls[ls.source_key.isin(z.source_key)]
                fields.append(row(z, s, dict(period=window, field_size=int(field),
                                             leader_count=count), confidence=True))
    pd.DataFrame(fields).to_csv(OUT/'field_size_rates.csv', index=False, encoding='utf-8-sig')
    summary = dict(period=['2018-01-05', '2026-09-18'], source_races=len(audit),
                   source_starts=66240, valid_s1f_races=int(audit.valid_s1f.sum()),
                   normal_complete_races=int(audit.normal_complete.sum()),
                   primary_leader_starts=int(leaders.normal_complete.sum()),
                   all_known_races=int(audit.all_known_outcomes.sum()),
                   duplicate_rank_primary=int((audit.normal_complete & audit.duplicate_finish_rank).sum()),
                   exact_cells=len(exact), compact_cells=len(compact),
                   source_contains_only_verified_previous_research_roster=True,
                   dnf_in_primary=False, new_fits=0, database_access=False,
                   production_changed=False, future_probability=False)
    save('summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(main_rates[main_rates.distance.eq('all')][['leader_count','races','leader_starts',
          'individual_win_pct','individual_top3_pct','group_win_pct','two_plus_top3_pct']].round(3).to_string(index=False))
    check_inputs()


if __name__ == '__main__':
    main()

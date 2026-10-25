"""Read-only, group-interval running style research. No operational integration."""
from pathlib import Path
import hashlib
import json
import re
import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / 'jeju/data/jeju_native_core.sqlite3'
COHORT = ROOT / 'jeju/research/20261007_environment_correction_pilot_v1/audit/source_rows.csv'
POINTS = ['s1f', 'c1', 'c2', 'c3', 'c4', 'g1f']
DISTANCES = [800, 900, 1000, 1110, 1200, 1300, 1400, 1610]
LABELS = {'lead': '선두군형 후보', 'front': '선입형 후보', 'middle': '중단형 후보',
          'rear': '후미대기형 후보', 'mixed': '혼합 또는 집단경계 불확실',
          'insufficient': '자료부족', 'held': '측정정의보류'}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def csv(path, frame):
    frame.to_csv(path, index=False, encoding='utf-8-sig')


def parse(value, roster):
    """Conservative grammar, no compressed numbers or stopped-runner suffix."""
    if value is None or pd.isna(value):
        return None, 'quality_value_unavailable'
    s = str(value).replace(' ', '')
    if '·' in s:
        return None, 'stopped_suffix_withheld'
    token = r'(?:\(\^?\d+(?:,\^?\d+)*\)|\^?\d+)'
    if not re.fullmatch(token + r'(?:[,=≡\-]+' + token + r')*', s):
        return None, 'unsupported_grammar'
    groups = [list(map(int, re.findall(r'\d+', m.group())))
              for m in re.finditer(token, s)]
    flat = [n for g in groups for n in g]
    if len(flat) != len(set(flat)):
        return None, 'duplicate_number'
    if set(flat) != set(roster):
        return None, 'roster_mismatch'
    return groups, 'usable_group_interval'


def positions(groups):
    n = sum(map(len, groups))
    out, before = {}, 0
    for idx, group in enumerate(groups):
        lo, hi = before + 1, before + len(group)
        # Integer arithmetic makes the chosen one-third boundary exact.
        zone = ('front' if 3 * (hi - 1) <= n - 1 else
                'middle' if 3 * (lo - 1) > n - 1 and 3 * (hi - 1) <= 2 * (n - 1) else
                'rear' if 3 * (lo - 1) > 2 * (n - 1) else 'ambiguous')
        for number in group:
            out[number] = {'rank_lo': lo, 'rank_hi': hi, 'zone': zone,
                           'first_group': idx == 0, 'solo_lead': idx == 0 and len(group) == 1}
        before = hi
    return out


def wilson(k, n):
    if not n:
        return np.nan, np.nan
    z = 1.959963984540054
    p, den = k / n, 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return mid - half, mid + half


def profile(g, limit=10, minimum=5):
    end = g.race_date.max()
    cutoff = (date.fromisoformat(end) - timedelta(days=730)).isoformat()
    q = g[g.race_date >= cutoff].sort_values(['race_date', 'race_number', 'api_record_id']).tail(limit)
    h = q[q.race_distance_m != 1300]
    valid = h[h.s1f_zone.notna()]
    n = len(valid)
    row = {'horse_id': str(q.horse_id.iloc[-1]), 'horse_name': q.horse_name.iloc[-1],
           'age_2026': q.age_2026.iloc[-1], 'scope_distance_m': int(g.race_distance_m.iloc[0]) if g.race_distance_m.nunique() == 1 else 0,
           'recent_limit': limit, 'window_first_date': q.race_date.min(), 'last_eligible_race_date': end,
           'has_eligible_start_2025_2026': end >= '2025-01-01',
           'window_starts': len(q), 'definition_held_1300_starts': int((q.race_distance_m == 1300).sum()),
           'early_definition_supported_starts': len(h), 's1f_valid_starts': n,
           's1f_valid_fraction': n / len(h) if len(h) else np.nan,
           'source_api_record_ids': '|'.join(map(str, q.api_record_id)),
           's1f_valid_api_record_ids': '|'.join(map(str, valid.api_record_id))}
    for name, mask in [('front', valid.s1f_zone == 'front'), ('middle', valid.s1f_zone == 'middle'),
                       ('rear', valid.s1f_zone == 'rear'), ('ambiguous', valid.s1f_zone == 'ambiguous'),
                       ('first_group', valid.s1f_first_group == True), ('solo_lead', valid.s1f_solo_lead == True)]:
        k = int(mask.sum())
        low, high = wilson(k, n)
        row.update({name + '_count': k, name + '_fraction': k / n if n else np.nan,
                    name + '_wilson95_lo': low, name + '_wilson95_hi': high})
    if not len(h):
        label = 'held'
    elif n < minimum or n / len(h) < .6:
        label = 'insufficient'
    elif row['front_fraction'] >= .6 and row['first_group_fraction'] >= .6:
        label = 'lead'
    elif row['front_fraction'] >= .6:
        label = 'front'
    elif row['middle_fraction'] >= .6:
        label = 'middle'
    elif row['rear_fraction'] >= .6:
        label = 'rear'
    else:
        label = 'mixed'
    row.update(style_code=label, style_label=LABELS[label])
    for name in ['early_to_c4', 'c4_to_g1f']:
        pair = q[q[name + '_definite_gain2'].notna()]
        k, count = int(pair[name + '_definite_gain2'].sum()), len(pair)
        low, high = wilson(k, count)
        row.update({name + '_pairs': count, name + '_definite_gain2_count': k,
                    name + '_definite_gain2_fraction': k / count if count else np.nan,
                    name + '_wilson95_lo': low, name + '_wilson95_hi': high})
    row['late_gain_tag'] = ('4C→G1F 확실한2두이상 전진 반복' if row['c4_to_g1f_pairs'] >= minimum and
                           row['c4_to_g1f_definite_gain2_fraction'] >= .6 else '전진 반복 기준 미충족 또는 자료부족')
    return row


def semantic_checks():
    a, _ = parse('(^1,2,3),4-(5,6),7,8,9,10', range(1, 11))
    b, _ = parse('(^3,1,2),4-(6,5),7,8,9,10', range(1, 11))
    assert positions(a) == positions(b)
    assert positions(a)[2]['rank_lo'] == 1 and positions(a)[2]['rank_hi'] == 3
    assert parse('(1,1),2', [1, 2])[1] == 'duplicate_number'
    assert parse('1,2', [1, 2, 3])[1] == 'roster_mismatch'
    assert parse('1,2·3', [1, 2, 3])[1] == 'stopped_suffix_withheld'
    assert parse(None, [1, 2])[0] is None
    assert parse('1(2,3)', [1, 2, 3])[0] is None
    assert positions([[1, 2, 3, 4, 5], [6], [7], [8], [9], [10]])[1]['zone'] == 'ambiguous'
    assert positions([[1], [2], [3], [4], [5], [6], [7], [8], [9], [10]])[4]['zone'] == 'front'


def main():
    out = HERE / 'run01'
    out.mkdir(exist_ok=False)
    semantic_checks()
    sources = [COHORT, HERE / 'PLAN.md', ROOT / 'jeju/data/horse_exclusions.json',
               ROOT / 'jeju/research/20261003_unresolved_section_review/semantic_review/README.md',
               ROOT / 'jeju/research/20261002_section_passing_audit/root_audit/audit_corner.py',
               ROOT / 'jeju/data/schema/migrations/20261003_add_section_internal_conflict_quality.sql']
    lineage = [{'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sources]
    before, dbsha = DB.stat(), sha(DB)
    save(out / 'source_manifest.json', {'database': {'path': str(DB.relative_to(ROOT)), 'bytes': before.st_size, 'sha256': dbsha},
                                       'files': lineage, 'plan_frozen_sha256': sha(HERE / 'PLAN.md')})
    s = pd.read_csv(COHORT, low_memory=False)
    s = s[(s.year >= 2017) & s.strict & s.race_distance_m.isin(DISTANCES)].copy()
    cols = ['api_record_id', 'race_date', 'meet_code', 'race_number', 'horse_number', 'horse_id',
            'horse_name', 'age_2026', 'race_distance_m', 'api4_3_payload_sha256', 'api4_3_source_page_sha256',
            'api4_3_source_page_path', 'api303_api_record_id', 'api303_payload_sha256',
            'api303_source_page_sha256', 'api303_source_page_path']
    cols += [p + suffix for p in POINTS for suffix in ['_group', '_group_status']]
    with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as con:
        con.execute('PRAGMA query_only=ON')
        # Column names are a constant program allowlist, dates are bound parameters.
        d = pd.read_sql_query('SELECT ' + ','.join(cols) + ' FROM jeju_race_postrace_sections_quality_2026 WHERE race_date BETWEEN ? AND ?', con, params=('2017-01-01', '2026-09-19'))
        roster = pd.read_sql_query('SELECT api_record_id,race_date,meet_code,race_number,horse_number,horse_id FROM race_result_rows WHERE race_date BETWEEN ? AND ?', con, params=('2017-01-01', '2026-09-19'))
    assert not d.api_record_id.duplicated().any()
    d = d[d.api_record_id.isin(s.api_record_id)].copy()
    assert len(d) == len(s)
    m = d[['api_record_id', 'api4_3_payload_sha256']].merge(s[['api_record_id', 'api4_3_payload_sha256']], on='api_record_id', validate='one_to_one')
    assert (m.api4_3_payload_sha256_x == m.api4_3_payload_sha256_y).all()
    for a in [d, roster]:
        a['race_id'] = a.race_date + '_' + a.meet_code.astype(str) + '_' + a.race_number.astype(str)
        a['horse_id'] = a.horse_id.astype(str)
    excluded = json.loads((ROOT / 'jeju/data/horse_exclusions.json').read_text())['horses']
    assert not set(d.horse_id) & {k for k, v in excluded.items() if not v['reimport_allowed']}
    rs = {k: set(map(int, g.horse_number)) for k, g in roster.groupby('race_id') if not g.horse_number.isna().any()}
    d['year'] = d.race_date.str[:4].astype(int)
    # Group source is saved once per race, not repeated for every horse.
    sourcecols = [c for c in cols if c not in ['horse_name', 'age_2026'] and '_group' not in c]
    csv(out / 'source_lineage.csv', d[sourcecols + ['race_id']])
    points, result = [], []
    for rid, g in d.groupby('race_id', sort=True):
        assert set(map(int, g.horse_number)) == rs[rid] and len(g) == len(rs[rid])
        first, parsed = g.iloc[0], {}
        for p in POINTS:
            assert g[p + '_group'].nunique(dropna=False) == 1
            assert g[p + '_group_status'].nunique(dropna=False) == 1
            value, quality = first[p + '_group'], first[p + '_group_status']
            if quality != 'api_group_unreviewed':
                assert pd.isna(value), (rid, p, quality)
            groups, status = parse(value, rs[rid])
            pos = positions(groups) if groups is not None else None
            parsed[p] = pos
            if pos:
                assert len(pos) == len(g)
                assert all(1 <= r['rank_lo'] <= r['rank_hi'] <= len(g) for r in pos.values())
                # Invariance for every observed pack, including group member reversal.
                assert pos == positions([list(reversed(x)) for x in groups])
            points.append({'race_id': rid, 'race_date': first.race_date, 'year': int(first.year),
                           'race_distance_m': int(first.race_distance_m), 'field_n': len(g), 'point': p,
                           'api303_api_record_id': first.api303_api_record_id,
                           'group_value': value, 'quality_status': quality, 'parse_status': status,
                           'group_count': len(groups) if groups else np.nan,
                           'ambiguous_runners': sum(r['zone'] == 'ambiguous' for r in pos.values()) if pos else np.nan})
        for r in g.itertuples(index=False):
            row = {'api_record_id': r.api_record_id, 'race_id': rid, 'race_date': r.race_date,
                   'race_number': r.race_number, 'year': r.year, 'horse_id': r.horse_id,
                   'horse_name': r.horse_name, 'age_2026': r.age_2026, 'horse_number': r.horse_number,
                   'race_distance_m': int(r.race_distance_m), 'field_n': len(g)}
            for p in ['s1f', 'c4', 'g1f']:
                v = parsed[p].get(int(r.horse_number)) if parsed[p] else None
                for name in ['rank_lo', 'rank_hi', 'zone', 'first_group', 'solo_lead']:
                    row[p + '_' + name] = v[name] if v else None
            row['early_definition_supported'] = int(r.race_distance_m) != 1300
            for name, early, late in [('early_to_c4', 's1f', 'c4'), ('c4_to_g1f', 'c4', 'g1f')]:
                usable = row[early + '_rank_lo'] is not None and row[late + '_rank_lo'] is not None
                if name == 'early_to_c4' and not row['early_definition_supported']:
                    usable = False
                row[name + '_definite_gain2'] = row[late + '_rank_hi'] <= row[early + '_rank_lo'] - 2 if usable else None
            result.append(row)
    a, p = pd.DataFrame(result), pd.DataFrame(points)
    csv(out / 'race_point_audit.csv', p)
    csv(out / 'runner_position_intervals.csv', a)
    coverage = p.assign(usable=p.parse_status == 'usable_group_interval', valid_runner_n=np.where(p.parse_status == 'usable_group_interval', p.field_n, 0))
    csv(out / 'point_coverage_by_distance_year.csv', coverage.groupby(['race_distance_m', 'year', 'point']).agg(races=('race_id', 'size'), usable_races=('usable', 'sum'), runner_opportunities=('field_n', 'sum'), usable_runners=('valid_runner_n', 'sum'), ambiguous_runners=('ambiguous_runners', 'sum')).reset_index())
    csv(out / 'point_status_counts.csv', p.groupby(['race_distance_m', 'point', 'quality_status', 'parse_status'], dropna=False).agg(races=('race_id', 'size'), runners=('field_n', 'sum')).reset_index())
    profiles = {}
    for scope, keys in [('horse', ['horse_id']), ('horse_distance', ['horse_id', 'race_distance_m'])]:
        for limit, minimum in [(10, 5), (5, 3)]:
            rows = []
            for _, g in a.groupby(keys, sort=True):
                row = profile(g, limit, minimum)
                row['scope_distance_m'] = 0 if scope == 'horse' else int(g.race_distance_m.iloc[0])
                rows.append(row)
            frame = pd.DataFrame(rows)
            profiles[(scope, limit)] = frame
            csv(out / f'{scope}_profiles_recent{limit}.csv', frame)
    stable = []
    for scope in ['horse', 'horse_distance']:
        keys = ['horse_id', 'scope_distance_m']
        joined = profiles[(scope, 10)].merge(profiles[(scope, 5)], on=keys, suffixes=('_10', '_5'), validate='one_to_one')
        concrete = ['lead', 'front', 'middle', 'rear']
        for recent in [False, True]:
            q = joined[joined.has_eligible_start_2025_2026_10] if recent else joined
            both = q[q.style_code_10.isin(concrete) & q.style_code_5.isin(concrete)]
            stable.append({'scope': scope, 'recent_2025_2026_only': recent, 'profile_cells': len(q),
                           'recent10_concrete_cells': int(q.style_code_10.isin(concrete).sum()),
                           'both_concrete_cells': len(both), 'same_concrete_cells': int((both.style_code_10 == both.style_code_5).sum()),
                           'agreement_fraction': float((both.style_code_10 == both.style_code_5).mean()) if len(both) else None,
                           'interpretation': 'overlapping_samples_descriptive_sensitivity_not_forward_prediction'})
    csv(out / 'window_sensitivity.csv', pd.DataFrame(stable))
    summary = {'period_start': '2017-01-01', 'period_end': '2026-09-19', 'partial_2026': True,
               'rows': len(a), 'races': a.race_id.nunique(), 'horses': a.horse_id.nunique(),
               'distance_rows': {str(int(k)): int(v) for k, v in a.groupby('race_distance_m').size().items()},
               's1f_usable_rows': int(a.s1f_zone.notna().sum()),
               's1f_ambiguous_rows': int((a.s1f_zone == 'ambiguous').sum()),
               's1f_early_definition_supported_usable_rows': int((a.s1f_zone.notna() & a.early_definition_supported).sum()),
               'horse_recent10_styles': profiles[('horse', 10)].style_label.value_counts().to_dict(),
               'horse_distance_recent10_styles': profiles[('horse_distance', 10)].style_label.value_counts().to_dict(),
               'same_race_prematch_features_created': False, 'future_prediction_tested': False,
               'traditional_style_truth_validated': False, 'operational_change': False}
    save(out / 'summary.json', summary)
    assert all(sha(ROOT / r['path']) == r['sha256'] for r in lineage)
    assert sha(DB) == dbsha and (DB.stat().st_size, DB.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    save(out / 'verification.json', {'status': 'passed', 'source_rows': len(a), 'race_point_checks': len(p),
                                    'full_roster_reconciled': True, 'group_member_permutation_invariant_all_usable_points': True,
                                    'synthetic_semantic_checks_passed': True, 'quality_blocked_values_never_restored': True,
                                    '1300_early_classification_withheld': True, 'one_profile_per_scope_key': True,
                                    'database_unchanged': True, 'database_sha256': dbsha, 'source_files_unchanged': True,
                                    'plan_sha256': sha(HERE / 'PLAN.md'), 'code_sha256': sha(Path(__file__))})
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()

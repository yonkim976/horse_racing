"""Postrace taxonomy and nonoverlapping style-change research, no model writes."""
from pathlib import Path
from datetime import date, timedelta
from collections import Counter
import json
import numpy as np
import pandas as pd
from extract import sha, save, ROOT, HERE, PREV

LABEL = {
    'held_1300': '1300m 초반 측정정의 보류', 'early_missing': '초반 통과조 결측',
    'early_ambiguous': '초반 집단경계 불확실',
    'lead_hold_top3': '선행 유지·입상', 'front_hold_top3': '선입 유지·입상',
    'front_advance_top3': '선입 전진·입상', 'closing_top3': '추입 입상',
    'closing_fail': '추입불발', 'lead_fade': '선행 약화', 'front_fade': '선입 약화',
    'back_reversal': '후방 전진 후 위치 재하락',
    'back_midmove_top3': '중반 전진·입상(후반 추입 미확정)',
    'back_midmove_out': '중반 전진·미입상(후반 추입 미확정)',
    'back_top3_uncertain': '후방 입상·추입근거 불충분',
    'back_fast_noadvance': '후방 빠른 구간·전진 미확정',
    'back_advance_time_unknown': '후방 전진·구간기록 근거 부족',
    'back_advance_notfast': '후방 전진·구간 우수 미확인',
    'back_no_evidence': '후방 유지 또는 움직임 미확정',
    'front_loss_time_unknown': '전방 위치 하락·느린 구간 근거 부족',
    'lead_to_front_top3': '선행권→선입권 입상',
    'front_top3_uncertain': '전방 출발·입상(유지/전진 미확정)',
    'front_out_no_fade': '전방 출발·미입상(약화 기준 미충족)',
}
CORE = ['lead_hold_top3', 'front_hold_top3', 'front_advance_top3', 'closing_top3',
        'closing_fail', 'lead_fade', 'front_fade']
EARLY = {'lead': '선행권', 'front': '선입권', 'middle': '중단', 'rear': '후미',
         'ambiguous': '집단경계 불확실', 'missing': '결측', 'held': '측정정의 보류'}


def csv(out, name, frame):
    frame.to_csv(out / name, index=False, encoding='utf-8-sig')


def gain(a, start, end, loss=False):
    known = a[start + '_rank_lo'].notna() & a[end + '_rank_lo'].notna()
    value = a[end + '_rank_lo'] >= a[start + '_rank_hi'] + 2 if loss else a[end + '_rank_hi'] <= a[start + '_rank_lo'] - 2
    return pd.Series(np.where(known, value.astype(float), np.nan), index=a.index)


def build_features(a, d):
    d = d.copy()
    d.horse_id = d.horse_id.astype(str)
    for col in ['horse_id', 'race_date', 'race_distance_m']:
        m = a[['api_record_id', col]].merge(d[['api_record_id', col]], on='api_record_id', validate='one_to_one')
        assert m[col + '_x'].equals(m[col + '_y'])
    a = a.merge(d.drop(columns=['horse_id', 'race_date', 'race_distance_m']), on='api_record_id', validate='one_to_one')
    a['top3'] = a.finish_position <= 3
    assert a.finish_position.between(1, a.field_n).all()
    a['relative_time_s'] = a.finish_time_seconds - a.groupby('race_id').finish_time_seconds.transform('median')
    a['final_rank_lo'] = a.finish_position
    a['final_rank_hi'] = a.finish_position
    a['early_position'] = np.select([
        a.race_distance_m == 1300, a.s1f_zone.isna(), a.s1f_zone == 'ambiguous',
        (a.s1f_zone == 'front') & a.s1f_first_group.eq(True), a.s1f_zone == 'front',
        a.s1f_zone == 'middle', a.s1f_zone == 'rear'],
        ['held', 'missing', 'ambiguous', 'lead', 'front', 'middle', 'rear'], default='missing')
    pairs = [('early_c4', 's1f', 'c4'), ('c4_g1f', 'c4', 'g1f'), ('g1f_final', 'g1f', 'final'),
             ('early_g1f', 's1f', 'g1f'), ('early_final', 's1f', 'final')]
    for name, start, end in pairs:
        for suffix, loss in [('gain2', False), ('loss2', True)]:
            a[name + '_' + suffix] = gain(a, start, end, loss)
            if start == 's1f':
                a.loc[a.race_distance_m == 1300, name + '_' + suffix] = np.nan
    conflict = r'unresolved|not_applied|source_changed'
    g1_block = a.g1f_group_status.str.contains(conflict, na=True) | a.g1f_order_status.str.contains(conflict, na=True)
    g3_block = g1_block | a.c4_group_status.str.contains(conflict, na=True) | a.c4_order_status.str.contains(conflict, na=True)
    raw3, raw1 = a.g3f_time_seconds, a.g1f_time_seconds
    pair_bad = raw3.notna() & raw1.notna() & (raw1 > raw3)
    for p, block in [('g3f', g3_block), ('g1f', g1_block)]:
        raw = a[p + '_time_seconds']
        valid = raw.gt(0) & raw.lt(a.finish_time_seconds) & ~pair_bad & ~block
        valid &= ~a[p + '_time_status'].str.contains(conflict, na=True)
        a[p + '_used_time_s'] = raw.where(valid)
        a[p + '_time_use_status'] = np.select([block, pair_bad, raw.isna() | raw.le(0), ~valid],
            ['internal_point_conflict_withheld', 'section_time_order_withheld', 'selected_time_unavailable', 'time_consistency_withheld'], default='positive_selected_time_used')
        n = a.groupby('race_id')[p + '_used_time_s'].transform('count')
        rank = a.groupby('race_id')[p + '_used_time_s'].rank(method='average')
        enough = (n >= 6) & (n >= .8 * a.field_n)
        a[p + '_reference_n'] = n
        a[p + '_relative_rank_fraction'] = ((rank - 1) / (n - 1)).where(enough)
        a[p + '_good'] = np.where(enough & rank.notna(), (3 * (rank - 1) <= n - 1).astype(float), np.nan)
        a[p + '_poor'] = np.where(enough & rank.notna(), (3 * (rank - 1) >= 2 * (n - 1)).astype(float), np.nan)
    both = a.g3f_good.notna() & a.g1f_good.notna()
    a['closing_good'] = np.where(both, (a.g3f_good.eq(1) | a.g1f_good.eq(1)).astype(float), np.nan)
    a['last200_minus_prior400_average_s'] = a.g1f_used_time_s - (a.g3f_used_time_s - a.g1f_used_time_s) / 2
    a['late_gain2'] = a.c4_g1f_gain2.eq(1) | a.g1f_final_gain2.eq(1)
    a['any_gain2'] = a.late_gain2 | a.early_c4_gain2.eq(1)
    a['position_reversal'] = ((a.early_c4_gain2.eq(1) & (a.c4_g1f_loss2.eq(1) | a.g1f_final_loss2.eq(1))) |
                              (a.c4_g1f_gain2.eq(1) & a.g1f_final_loss2.eq(1)))
    front = a.early_position.isin(['lead', 'front'])
    a['fade_middle'] = front & a.early_c4_loss2.eq(1) & a.g3f_poor.eq(1)
    a['fade_late'] = front & a.c4_zone.eq('front') & a.c4_g1f_loss2.eq(1) & a.g3f_poor.eq(1)
    a['fade_final'] = front & a.g1f_zone.eq('front') & a.g1f_final_loss2.eq(1) & a.g1f_poor.eq(1)
    a['fade_any'] = a[['fade_middle', 'fade_late', 'fade_final']].any(axis=1)
    a['fade_phase'] = ['·'.join(s for s, yes in zip(['중반부터', '후반', '막판'], values) if yes)
                       for values in a[['fade_middle', 'fade_late', 'fade_final']].itertuples(index=False, name=None)]
    types = []
    for r in a.itertuples(index=False):
        e = r.early_position
        if e in ['held', 'missing', 'ambiguous']:
            t = {'held': 'held_1300', 'missing': 'early_missing', 'ambiguous': 'early_ambiguous'}[e]
        elif e in ['lead', 'front']:
            if r.fade_any:
                t = 'lead_fade' if e == 'lead' else 'front_fade'
            elif e == 'lead' and r.c4_zone == 'front' and r.g1f_zone == 'front' and r.g1f_first_group == True and r.top3:
                t = 'lead_hold_top3'
            elif e == 'front' and r.any_gain2 and r.closing_good == 1 and r.top3:
                t = 'front_advance_top3'
            elif e == 'front' and r.c4_zone == 'front' and r.g1f_zone == 'front' and r.top3:
                t = 'front_hold_top3'
            elif r.early_c4_loss2 == 1 or r.c4_g1f_loss2 == 1 or r.g1f_final_loss2 == 1:
                t = 'front_loss_time_unknown'
            elif e == 'lead' and r.g1f_zone == 'front' and r.g1f_first_group == False and r.top3:
                t = 'lead_to_front_top3'
            elif r.top3:
                t = 'front_top3_uncertain'
            else:
                t = 'front_out_no_fade'
        else:
            if r.late_gain2 and r.closing_good == 1:
                t = 'back_reversal' if r.position_reversal else ('closing_top3' if r.top3 else 'closing_fail')
            elif r.late_gain2:
                t = 'back_advance_time_unknown' if pd.isna(r.closing_good) else 'back_advance_notfast'
            elif r.early_c4_gain2 == 1:
                t = 'back_midmove_top3' if r.top3 else 'back_midmove_out'
            elif r.top3:
                t = 'back_top3_uncertain'
            elif r.closing_good == 1:
                t = 'back_fast_noadvance'
            else:
                t = 'back_no_evidence'
        types.append(t)
    a['type_code'] = types
    a['type_label'] = a.type_code.map(LABEL)
    a['core_type_match'] = a.type_code.isin(CORE)
    a['early_position_label'] = a.early_position.map(EARLY)
    return a


def block(g, prefix='', threshold=3):
    c = Counter(g.early_position)
    valid = len(g) - c['missing'] - c['held']
    dominant = 'uncertain'
    if len(g) == 5 and valid >= 4:
        for e in ['lead', 'front', 'middle', 'rear']:
            if c[e] >= threshold:
                dominant = e
    row = {'n': len(g), 'style': dominant, 'style_label': EARLY.get(dominant, '혼합·불확실'),
           'top3_count': int(g.top3.sum()), 'relative_time_mean_s': float(g.relative_time_s.mean()) if len(g) else np.nan,
           'raw_time_mean_s': float(g.finish_time_seconds.mean()) if len(g) else np.nan,
           'g3f_relative_mean': float(g.g3f_relative_rank_fraction.mean()) if len(g) else np.nan,
           'g1f_relative_mean': float(g.g1f_relative_rank_fraction.mean()) if len(g) else np.nan,
           'grade_values': '|'.join(sorted(set(g.rank_class_raw.dropna()))),
           'track_values': '|'.join(sorted(set(g.track_raw.dropna()))),
           'carried_weight_mean_kg': float(g.carried_weight_kg.mean()) if len(g) else np.nan,
           'field_n_mean': float(g.field_n.mean()) if len(g) else np.nan,
           'first_date': g.race_date.min() if len(g) else None, 'last_date': g.race_date.max() if len(g) else None,
           'source_api_record_ids': '|'.join(map(str, g.api_record_id)),
           'closing_top3_count': int(g.type_code.eq('closing_top3').sum()),
           'closing_fail_count': int(g.type_code.eq('closing_fail').sum()),
           'fade_count': int(g.fade_any.sum())}
    row.update({e + '_count': c[e] for e in ['lead', 'front', 'middle', 'rear', 'ambiguous', 'missing', 'held']})
    return {prefix + k: v for k, v in row.items()}


def recent_profile(g, scope):
    cutoff = (date.fromisoformat(g.race_date.max()) - timedelta(days=730)).isoformat()
    q = g[g.race_date >= cutoff].tail(10)
    support = q[q.race_distance_m != 1300]
    valid = support[support.s1f_zone.notna()]
    n = len(valid)
    r = {'horse_id': str(g.horse_id.iloc[-1]), 'horse_name': g.horse_name.iloc[-1],
         'age_2026': g.age_2026.iloc[-1], 'distance_m': 0 if scope == 'horse' else int(g.race_distance_m.iloc[0]),
         'last_date': q.race_date.max(), 'first_date': q.race_date.min(), 'window_n': len(q),
         'definition_supported_n': len(support), 's1f_valid_n': n,
         'core_type_n': int(support.core_type_match.sum()),
         'source_api_record_ids': '|'.join(map(str, q.api_record_id))}
    for code in LABEL:
        r[code + '_count'] = int(q.type_code.eq(code).sum())
    for e in ['lead', 'front', 'middle', 'rear', 'ambiguous', 'missing', 'held']:
        r['early_' + e + '_count'] = int(q.early_position.eq(e).sum())
    if len(support) == 0:
        style, fit = '측정정의보류', '측정정의보류'
    elif n < 5 or n / len(support) < .6:
        style, fit = '자료부족', '자료부족'
    else:
        closing_n = r['closing_top3_count'] + r['closing_fail_count']
        style = '혼합·집단경계 불확실'
        if closing_n / n >= .6:
            style = '추입형 후보'
        else:
            for e, label in [('lead', '선행권형 후보'), ('front', '선입형 후보'),
                             ('middle', '중단대기형(추입반복 미확인)'), ('rear', '후미대기형(추입반복 미확인)')]:
                if r['early_' + e + '_count'] / n >= .6:
                    style = label
                    break
        if r['core_type_n'] / len(support) >= .6:
            fit = '제안유형으로 대부분 설명'
        elif r['early_ambiguous_count'] / len(support) >= .4:
            fit = '집단경계 불확실 비중 큼'
        else:
            fit = '제안유형 밖 전개 비중 큼'
    r['style_candidate'] = style
    r['taxonomy_fit_status'] = fit
    r['core_type_fraction'] = r['core_type_n'] / len(support) if len(support) else np.nan
    r['classification_uncertainty_fraction'] = r['early_ambiguous_count'] / len(support) if len(support) else np.nan
    types = q.type_label.value_counts()
    r['most_common_race_type'] = types.index[0]
    r['most_common_race_type_n'] = int(types.iloc[0])
    return r


def latest_change(g, threshold):
    cutoff = (date.fromisoformat(g.race_date.max()) - timedelta(days=730)).isoformat()
    q = g[g.race_date >= cutoff].tail(10)
    r = {'horse_id': str(g.horse_id.iloc[-1]), 'horse_name': g.horse_name.iloc[-1],
         'distance_m': int(g.race_distance_m.iloc[0]), 'last_date': g.race_date.max(), 'threshold_in5': threshold}
    if r['distance_m'] == 1300:
        status = '측정정의보류'
    elif len(q) < 10:
        status = '자료부족'
    else:
        b1, b2 = block(q.iloc[:5], 'A_', threshold), block(q.iloc[5:], 'B_', threshold)
        r.update(b1); r.update(b2)
        old, new = r['A_style'], r['B_style']
        if old != 'uncertain' and new != 'uncertain':
            status = '성향유지' if old == new else '성향변화후보'
        elif new != 'uncertain':
            status = '최근 성향 집중'
        elif old != 'uncertain':
            status = '최근 성향 분산'
        else:
            status = '혼합·불확실'
    r['change_status'] = status
    return r


def first_transition(g):
    if int(g.race_distance_m.iloc[0]) == 1300:
        return None
    for end in range(10, len(g) + 1):
        q = g.iloc[end - 10:end]
        if (date.fromisoformat(q.race_date.max()) - date.fromisoformat(q.race_date.min())).days > 730:
            continue
        ba, bb = block(q.iloc[:5], 'A_'), block(q.iloc[5:], 'B_')
        if ba['A_style'] == 'uncertain' or bb['B_style'] == 'uncertain' or ba['A_style'] == bb['B_style']:
            continue
        r = {'horse_id': str(g.horse_id.iloc[-1]), 'horse_name': g.horse_name.iloc[-1],
             'distance_m': int(g.race_distance_m.iloc[0]), 'change_end_date': q.race_date.max(),
             'change_end_api_record_id': int(q.api_record_id.iloc[-1])}
        r.update(ba); r.update(bb)
        lower = (date.fromisoformat(q.race_date.max()) + timedelta(days=2)).isoformat()
        upper = (date.fromisoformat(q.race_date.max()) + timedelta(days=365)).isoformat()
        follow = g[(g.race_date >= lower) & (g.race_date <= upper)].head(5)
        r.update(block(follow, 'C_'))
        r['B_minus_A_top3_count'] = r['B_top3_count'] - r['A_top3_count']
        r['B_minus_A_relative_time_s'] = r['B_relative_time_mean_s'] - r['A_relative_time_mean_s']
        r['C_minus_A_top3_count'] = r['C_top3_count'] - r['A_top3_count'] if len(follow) == 5 else np.nan
        r['C_minus_A_relative_time_s'] = r['C_relative_time_mean_s'] - r['A_relative_time_mean_s'] if len(follow) == 5 else np.nan
        r['performance_associated_change_candidate'] = r['B_minus_A_top3_count'] >= 2 and r['B_minus_A_relative_time_s'] <= -.5
        r['new_style_persists_in_C'] = len(follow) == 5 and r['C_style'] == r['B_style']
        r['followup_supports_candidate'] = (r['performance_associated_change_candidate'] and r['new_style_persists_in_C'] and
                                             r['C_minus_A_top3_count'] >= 1 and r['C_minus_A_relative_time_s'] <= -.25)
        r['status'] = ('후속 지지 후보' if r['followup_supports_candidate'] else
                       '성과동반 변화 후보·후속 미확인' if r['performance_associated_change_candidate'] else '위치 성향 변화 관측')
        return r  # Earliest qualifying change, never selected by later performance.
    return None


def checks(a, events):
    fail = a[a.type_code == 'closing_fail']
    assert (~fail.top3).all() and fail.late_gain2.all() and fail.closing_good.eq(1).all()
    assert fail.early_position.isin(['middle', 'rear']).all() and (~fail.position_reversal).all()
    win = a[a.type_code == 'closing_top3']
    assert win.top3.all() and win.late_gain2.all() and win.closing_good.eq(1).all()
    assert a[a.type_code.isin(['lead_fade', 'front_fade'])].fade_any.all()
    assert not a[a.race_distance_m == 1300].core_type_match.any()
    for p in ['g3f', 'g1f']:
        bad = a[p + '_time_use_status'] != 'positive_selected_time_used'
        assert a.loc[bad, p + '_used_time_s'].isna().all()
        assert a.loc[bad, p + '_relative_rank_fraction'].isna().all()
    for r in events.itertuples():
        sets = [set(str(getattr(r, prefix + '_source_api_record_ids')).split('|')) - {''} for prefix in ['A', 'B', 'C']]
        assert not sets[0] & sets[1] and not sets[0] & sets[2] and not sets[1] & sets[2]
        assert len(sets[0]) == len(sets[1]) == 5
        assert r.A_last_date < r.B_first_date
        if r.C_n:
            assert date.fromisoformat(r.C_first_date) >= date.fromisoformat(r.B_last_date) + timedelta(days=2)
    return {'status': 'passed', 'closing_fail_rows': len(fail), 'closing_top3_rows': len(win),
            'taxonomy_rules_checked_all_rows': len(a), 'transition_triplets_checked': len(events),
            'quality_withheld_times_never_restored': True, 'transition_windows_nonoverlapping_and_T_minus2': True,
            '1300_classification_withheld': True, 'future_information_not_used_for_change_selection': True}


def main():
    out = HERE / 'run01'
    out.mkdir(exist_ok=False)
    inp = HERE / 'input01'
    assert json.loads((inp / 'verification.json').read_text())['status'] == 'passed'
    manifest = json.loads((inp / 'source_manifest.json').read_text())
    assert all(sha(ROOT / r['path']) == r['sha256'] for r in manifest['files'])
    a = pd.read_csv(PREV / 'run01/runner_position_intervals.csv', dtype={'horse_id': str})
    d = pd.read_csv(inp / 'selected_quality_times.csv', dtype={'horse_id': str})
    a = build_features(a, d).sort_values(['horse_id', 'race_distance_m', 'race_date', 'race_number', 'api_record_id']).reset_index(drop=True)
    csv(out, 'runner_types_and_evidence.csv', a)
    print('Runner taxonomy built', len(a), flush=True)
    csv(out, 'type_counts_distance_year_field.csv', a.groupby(['race_distance_m', 'year', 'field_n', 'type_code', 'type_label']).agg(starts=('api_record_id', 'size'), top3=('top3', 'sum')).reset_index())
    csv(out, 'time_quality_and_coverage.csv', a.groupby(['race_distance_m', 'g3f_time_use_status', 'g1f_time_use_status'], dropna=False).size().reset_index(name='starts'))
    profile_data = {}
    for scope, keys in [('horse', ['horse_id']), ('horse_distance', ['horse_id', 'race_distance_m'])]:
        profiles = [recent_profile(g.sort_values(['race_date', 'race_number', 'api_record_id']), scope) for _, g in a.groupby(keys, sort=True)]
        profile_data[scope] = pd.DataFrame(profiles)
        csv(out, f'{scope}_profiles.csv', profile_data[scope])
        print('Profiles built', scope, len(profiles), flush=True)
    changes, events = [], []
    for _, g in a.groupby(['horse_id', 'race_distance_m'], sort=True):
        g = g.sort_values(['race_date', 'race_number', 'api_record_id'])
        for threshold in [3, 4]:
            changes.append(latest_change(g, threshold))
        event = first_transition(g)
        if event is not None:
            events.append(event)
    changes, events = pd.DataFrame(changes), pd.DataFrame(events)
    csv(out, 'latest_nonoverlapping_changes.csv', changes)
    csv(out, 'first_transition_followup.csv', events)
    print('Changes built', len(events), flush=True)
    sensitivity = []
    for threshold in [.25, .5, 1.0]:
        candidate = (events.B_minus_A_top3_count >= 2) & (events.B_minus_A_relative_time_s <= -threshold)
        continued = candidate & events.new_style_persists_in_C & (events.C_minus_A_top3_count >= 1) & (events.C_minus_A_relative_time_s <= -.25)
        sensitivity.append({'B_vs_A_time_gain_threshold_s': threshold, 'change_events': len(events),
                            'candidate_events': int(candidate.sum()), 'full5_followup_candidates': int((candidate & events.C_n.eq(5)).sum()),
                            'followup_supported_candidates': int(continued.sum())})
    csv(out, 'performance_threshold_sensitivity.csv', pd.DataFrame(sensitivity))
    check = checks(a, events)
    assert all(sha(ROOT / r['path']) == r['sha256'] for r in manifest['files'])
    check.update(code_sha256=sha(Path(__file__)), plan_sha256=sha(HERE / 'PLAN.md'), source_hashes_unchanged=True)
    save(out / 'verification.json', check)
    summary = {'period_start': '2017-01-01', 'period_end': '2026-09-19', 'partial_2026': True,
               'starts': len(a), 'races': int(a.race_id.nunique()), 'horses': int(a.horse_id.nunique()),
               'core_type_starts': int(a.core_type_match.sum()), 'runner_type_counts': a.type_label.value_counts().to_dict(),
               'horse_style_candidates': profile_data['horse'].style_candidate.value_counts().to_dict(),
               'horse_taxonomy_fit': profile_data['horse'].taxonomy_fit_status.value_counts().to_dict(),
               'horse_distance_taxonomy_fit': profile_data['horse_distance'].taxonomy_fit_status.value_counts().to_dict(),
               'latest_change_status60': changes[changes.threshold_in5 == 3].change_status.value_counts().to_dict(),
               'latest_change_status80': changes[changes.threshold_in5 == 4].change_status.value_counts().to_dict(),
               'first_change_events': len(events), 'first_changes_full5_followup': int(events.C_n.eq(5).sum()),
               'new_position_persists_full5_followup': int(events.new_style_persists_in_C.sum()),
               'performance_associated_change_candidates': int(events.performance_associated_change_candidate.sum()),
               'followup_supported_candidates': int(events.followup_supports_candidate.sum()),
               'independent_future_holdout': False, 'causal_optimal_style_identified': False, 'operational_change': False}
    save(out / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()

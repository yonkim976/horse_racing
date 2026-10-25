"""Independent rank arithmetic and chronological first-change audit."""
from pathlib import Path
from collections import Counter
from datetime import date, timedelta
import json
import numpy as np
import pandas as pd
from extract import sha, save, HERE, ROOT


def dominant(positions, valid_count):
    if len(positions) != 5 or valid_count < 4:
        return 'uncertain'
    c = Counter(positions)
    return next((e for e in ['lead', 'front', 'middle', 'rear'] if c[e] >= 3), 'uncertain')


def main():
    out = HERE / 'run01'
    a = pd.read_csv(out / 'runner_types_and_evidence.csv', dtype={'horse_id': str})
    d = pd.read_csv(HERE / 'input01/selected_quality_times.csv').set_index('api_record_id')
    checked = 0
    for _, g in a.groupby('race_id'):
        for p in ['g3f', 'g1f']:
            values = g[p + '_used_time_s'].to_numpy()
            n = np.isfinite(values).sum()
            ranks = np.array([1 + np.sum(values < x) + (np.sum(values == x) - 1) / 2 if np.isfinite(x) else np.nan for x in values])
            possible = n >= 6 and n >= .8 * len(g)
            expected = (ranks - 1) / (n - 1) if possible else np.full(len(g), np.nan)
            np.testing.assert_allclose(expected, g[p + '_relative_rank_fraction'], equal_nan=True)
            raw = d.loc[g.api_record_id, p + '_time_seconds'].to_numpy()
            finite = np.isfinite(values)
            np.testing.assert_array_equal(values[finite], raw[finite])
            checked += len(g)
    # A fast clock alone must not create closing_fail.
    fails = a[a.type_code == 'closing_fail']
    assert (fails.finish_position > 3).all()
    assert fails.early_position.isin(['middle', 'rear']).all()
    actual_late_gain = (fails.g1f_rank_hi <= fails.c4_rank_lo - 2) | (fails.finish_position <= fails.g1f_rank_lo - 2)
    assert actual_late_gain.all()
    assert fails.g3f_good.notna().all() and fails.g1f_good.notna().all()
    assert (fails.g3f_good.eq(1) | fails.g1f_good.eq(1)).all()
    events = pd.read_csv(out / 'first_transition_followup.csv', dtype={'horse_id': str})
    event_map = {(r.horse_id, r.distance_m): r for r in events.itertuples()}
    earliest_found = 0
    for (horse, distance), g in a.groupby(['horse_id', 'race_distance_m']):
        if distance == 1300:
            assert (horse, distance) not in event_map
            continue
        g = g.sort_values(['race_date', 'race_number', 'api_record_id']).reset_index(drop=True)
        pos, dates, ids = g.early_position.tolist(), g.race_date.tolist(), g.api_record_id.tolist()
        expected_end = None
        for end in range(10, len(g) + 1):
            if (date.fromisoformat(dates[end - 1]) - date.fromisoformat(dates[end - 10])).days > 730:
                continue
            p1, p2 = pos[end - 10:end - 5], pos[end - 5:end]
            old = dominant(p1, sum(x not in ['missing', 'held'] for x in p1))
            new = dominant(p2, sum(x not in ['missing', 'held'] for x in p2))
            if old != 'uncertain' and new != 'uncertain' and old != new:
                expected_end = end
                break
        if expected_end is None:
            assert (horse, distance) not in event_map
            continue
        earliest_found += 1
        r = event_map[(horse, distance)]
        assert r.change_end_api_record_id == ids[expected_end - 1]
        blockA, blockB = g.iloc[expected_end - 10:expected_end - 5], g.iloc[expected_end - 5:expected_end]
        lower = (date.fromisoformat(dates[expected_end - 1]) + timedelta(days=2)).isoformat()
        upper = (date.fromisoformat(dates[expected_end - 1]) + timedelta(days=365)).isoformat()
        blockC = g[g.race_date.between(lower, upper)].head(5)
        for prefix, q in [('A', blockA), ('B', blockB), ('C', blockC)]:
            rawids = getattr(r, prefix + '_source_api_record_ids')
            captured = [] if pd.isna(rawids) else list(map(int, str(rawids).split('|')))
            assert q.api_record_id.tolist() == captured
            assert int((q.finish_position <= 3).sum()) == getattr(r, prefix + '_top3_count')
            if len(q):
                np.testing.assert_allclose(q.relative_time_s.mean(), getattr(r, prefix + '_relative_time_mean_s'))
        candidate = (r.B_top3_count - r.A_top3_count >= 2 and r.B_relative_time_mean_s - r.A_relative_time_mean_s <= -.5)
        assert candidate == r.performance_associated_change_candidate
        follow_style = dominant(blockC.early_position.tolist(), int((~blockC.early_position.isin(['missing', 'held'])).sum()))
        follow = (candidate and len(blockC) == 5 and follow_style == r.B_style and
                  r.C_top3_count - r.A_top3_count >= 1 and r.C_relative_time_mean_s - r.A_relative_time_mean_s <= -.25)
        assert follow == r.followup_supports_candidate
    assert earliest_found == len(events)
    # Reconcile every compact profile count to its actual saved window.
    byid = a.set_index('api_record_id')
    profile_rows = 0
    for scope in ['horse', 'horse_distance']:
        h = pd.read_csv(out / f'{scope}_profiles.csv', dtype={'horse_id': str})
        for r in h.itertuples():
            ids = list(map(int, r.source_api_record_ids.split('|')))
            q = byid.loc[ids]
            assert q.horse_id.eq(r.horse_id).all() and len(q) <= 10
            if scope == 'horse_distance':
                assert q.race_distance_m.eq(r.distance_m).all()
            assert q.type_code.eq('closing_fail').sum() == r.closing_fail_count
            assert q.type_code.eq('closing_top3').sum() == r.closing_top3_count
            assert q.core_type_match.sum() == r.core_type_n
            assert r.window_n == len(q)
            profile_rows += 1
    save(out / 'verification_independent.json', {'status': 'passed', 'runner_time_rank_checks': checked,
                                               'closing_fail_rules_independently_checked': len(fails),
                                               'first_change_events_independently_reconstructed': earliest_found,
                                               'profile_rows_reconciled': profile_rows,
                                               'no_best_outcome_change_point_selection': True,
                                               'A_B_C_ids_and_time_order_reconciled': True,
                                               'code_sha256': sha(Path(__file__))})
    print('Independent audit passed:', checked, 'time ranks;', earliest_found, 'first changes;', profile_rows, 'profiles')


if __name__ == '__main__':
    main()

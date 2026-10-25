"""Reconcile saved profiles to row IDs and the earlier audited group parser."""
from pathlib import Path
import importlib.util
import json
import hashlib
from datetime import date, timedelta

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'run01'


def main():
    oldpath = ROOT / 'jeju/research/20261002_section_passing_audit/root_audit/audit_corner.py'
    spec = importlib.util.spec_from_file_location('preserved_group_audit', oldpath)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    a = pd.read_csv(OUT / 'runner_position_intervals.csv', dtype={'horse_id': str})
    p = pd.read_csv(OUT / 'race_point_audit.csv')
    assert not a.api_record_id.duplicated().any()
    rows = {k: g for k, g in a.groupby('race_id')}
    checked = 0
    for r in p[p.point.isin(['s1f', 'c4', 'g1f'])].itertuples():
        g = rows[r.race_id]
        if r.parse_status != 'usable_group_interval':
            assert g[r.point + '_rank_lo'].isna().all()
            assert g[r.point + '_zone'].isna().all()
            continue
        packs = old.parse_groups(r.group_value)
        assert packs is not None
        offset = 0
        for pack in packs:
            q = g[g.horse_number.isin(pack)]
            assert len(q) == len(pack)
            assert (q[r.point + '_rank_lo'] == offset + 1).all()
            assert (q[r.point + '_rank_hi'] == offset + len(pack)).all()
            checked += len(pack)
            offset += len(pack)
        assert offset == len(g)
    assert a[a.race_distance_m == 1300].early_to_c4_definite_gain2.isna().all()
    by_id = a.set_index('api_record_id')
    profile_checks = 0
    for scope, keys in [('horse', ['horse_id']), ('horse_distance', ['horse_id', 'race_distance_m'])]:
        histories = {}
        for key, g in a.groupby(keys):
            key = key if isinstance(key, tuple) else (key,)
            histories[key] = g.sort_values(['race_date', 'race_number', 'api_record_id'])
        for limit in [10, 5]:
            h = pd.read_csv(OUT / f'{scope}_profiles_recent{limit}.csv', dtype={'horse_id': str})
            assert not h.duplicated(['horse_id', 'scope_distance_m']).any()
            for r in h.itertuples():
                key = (r.horse_id,) if scope == 'horse' else (r.horse_id, r.scope_distance_m)
                g = histories[key]
                cutoff = (date.fromisoformat(g.race_date.max()) - timedelta(days=730)).isoformat()
                wanted = g[g.race_date >= cutoff].tail(limit)
                ids = [int(v) for v in r.source_api_record_ids.split('|')]
                assert ids == wanted.api_record_id.tolist()
                q = by_id.loc[ids]
                assert q.horse_id.eq(r.horse_id).all()
                if scope == 'horse_distance':
                    assert q.race_distance_m.eq(r.scope_distance_m).all()
                valid = q[(q.race_distance_m != 1300) & q.s1f_zone.notna()]
                assert r.s1f_valid_starts == len(valid)
                assert r.front_count + r.middle_count + r.rear_count + r.ambiguous_count == len(valid)
                for zone in ['front', 'middle', 'rear', 'ambiguous']:
                    assert getattr(r, zone + '_count') == int((valid.s1f_zone == zone).sum())
                assert r.first_group_count == int(valid.s1f_first_group.sum())
                assert r.solo_lead_count == int(valid.s1f_solo_lead.sum())
                if scope == 'horse_distance' and r.scope_distance_m == 1300:
                    assert r.style_code == 'held'
                profile_checks += 1
    # Every denominator includes ambiguous packs rather than silently dropping them.
    result = {'status': 'passed', 'independent_preserved_parser_runner_points_checked': checked,
              'saved_profile_rows_reconciled': profile_checks, 'recent_windows_exactly_reconstructed': True,
              'all_profile_numerators_denominators_reconciled': True,
              'ambiguous_positions_not_dropped_from_style_denominators': True,
              '1300_early_progress_and_style_withheld': True,
              'forward_prediction_or_independent_holdout': False,
              'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (OUT / 'verification_independent.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

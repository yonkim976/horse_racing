"""Reconcile retained Busan audit outputs; no DB access or timing imputation."""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
OLD = R / '20261017_section_layout_by_distance_v1/outputs'
REMAINING = {'G8F': 1600, 'G6F': 1200, 'G4F': 800, 'G3F': 600,
             'G2F': 400, 'G1F': 200}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def read_csv(name):
    with (OLD / name).open(newline='') as f:
        return list(csv.DictReader(f))


def main():
    manifest = json.loads((OUT / 'input_manifest.json').read_text())
    for name, expected in manifest.items():
        p = ROOT / name
        assert p.stat().st_size == expected['bytes'] and sha(p) == expected['sha256'], name
    rows = [r for r in read_csv('distance_layouts.csv') if r['meet'] == '3']
    point_rows = []
    for r in rows:
        d = int(r['distance_m'])
        points = {0: ['START'], 200: ['S1F'], d: ['FIN']}
        for name, left in REMAINING.items():
            if 0 < d - left < d:
                points.setdefault(d - left, []).append(name)
        positions = sorted(points)
        lengths = [b - a for a, b in zip(positions, positions[1:])]
        assert sum(lengths) == d
        assert '+'.join(map(str, lengths)) == r['lengths_m']
        assert ' → '.join(points[x][0] for x in positions) == r['points']
        for index, x in enumerate(positions):
            point_rows.append(dict(distance_m=d, point=points[x][0],
                                   aliases='='.join(points[x]), elapsed_m=x,
                                   remaining_m=d-x, previous_length_m=None if index == 0 else x-positions[index-1],
                                   status='official_nominal_definition_not_surveyed_coordinate'))
    with (OUT / 'checkpoint_distances.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(point_rows[0])); w.writeheader(); w.writerows(point_rows)
    with (OUT / 'distance_layouts.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    bad = [x for x in json.loads((OLD / 'checkpoint_exceptions.json').read_text()) if x['meet'] == 3]
    absent = [x for x in read_csv('missing_distance_rows.csv') if x['meet'] == '3']
    aliases = [x for x in read_csv('alias_checks.csv') if x['meet'] == '3']
    yearly = [x for x in read_csv('yearly_support.csv') if x['meet'] == '3']
    known = sum(int(r['rows']) for r in rows)
    complete = sum(int(r['detail_complete']) for r in rows)
    basic = sum(int(r['basic_complete']) for r in rows)
    missing = sum(x['missing'] for x in bad)
    order = sum(x['nonpositive_or_order'] for x in bad)
    assert known == 133755 and complete == 133733 and len(bad) == 22
    assert len(absent) == 10 and missing == 20 and order == 2
    assert sum(int(y['rows']) for y in yearly) == known
    assert sum(int(y['detail_complete']) for y in yearly) == complete
    assert len(aliases) == 3 and all(int(a['both_observed']) == 0 for a in aliases)
    assert sum(int(r['alias_conflicts']) for r in rows) == 0
    save('record_exceptions.json', bad)
    save('missing_distance_rows.json', absent)
    save('alias_observation_limits.json', aliases)
    save('summary.json', dict(
        source='retained research57 outputs, not a fresh DB/raw audit', checked_on='2026-10-20',
        source_dates=['2010-01-08', '2026-09-18'], normal_runner_rows=known+len(absent),
        distance_known_rows=known, detailed_complete=complete,
        detailed_complete_percent=100*complete/known, basic_complete=basic,
        detail_exceptions=len(bad), missing_detail=missing, nonpositive_or_order=order,
        exception_races=len({(x['date_key'],x['race_no']) for x in bad}),
        distance_missing_rows=len(absent),
        exceptions_by_distance=dict(Counter(str(x['distance_m']) for x in bad)),
        ordinary_same_nominal_alias_rows_not_dual_observed=sum(int(a['missing_one_or_both']) for a in aliases),
        historical_route_changes_fully_verified=False, timing_order_same_physical_line_verified=False,
        geometry_sources_conflict=True, new_imputed_times=0, models_changed=0, database_access=False))
    save('verification.json', dict(status='verified_retained_outputs_and_nominal_distance_arithmetic',
        protected_input_hashes=len(manifest), input_hashes_unchanged=True,
        distance_layouts_checked=len(rows), all_nominal_lengths_sum_to_distance=True,
        table_points_match_independent_formula=True, year_totals_match=True,
        missing_and_order_counts_verified=True, raw_source_reaudit=False,
        inherited_audit='research57 verified 62831 Busan runner comparisons with zero time difference',
        alias_equality_dual_observations=0, no_historical_survey_claim=True,
        no_database_access=True, no_model_changes=True, no_web_changes=True))
    print((OUT / 'summary.json').read_text())


if __name__ == '__main__':
    main()

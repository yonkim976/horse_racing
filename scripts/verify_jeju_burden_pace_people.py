"""Independent split arithmetic, burden source, and lineage replay."""
import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/research/jeju_burden_pace_people_audit_20260918'


def main():
    manifest = json.loads((OUT/'manifest.json').read_text())
    for name, digest in manifest['inputs'].items():
        with (ROOT/name).open('rb') as f:
            assert hashlib.file_digest(f, 'sha256').hexdigest() == digest, name
    for name, digest in manifest['outputs'].items():
        assert hashlib.sha256((OUT/name).read_bytes()).hexdigest() == digest, name
    c = sqlite3.connect(f"file:{ROOT/'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'}?mode=ro", uri=True)
    g3 = dict(c.execute("""SELECT e.id,json_extract(s.normalized_json,'$.jeG3fTime')
        FROM entry e JOIN source_row s ON s.id=e.source_row_id"""))
    c.close()
    observations = pl.read_parquet(ROOT/'data/research/jeju_tempo_pace_features_20260917/observations.parquet').to_dicts()
    rows = {r['entry_id']:r for r in observations}
    groups = defaultdict(list)
    for r in observations:
        try:
            a, b, total, first = float(g3[r['entry_id']]), float(r['g1f_seconds']), float(r['total_seconds']), float(r['s1f_seconds'])
        except (TypeError, ValueError):
            continue
        if (r['outcome_status']=='normal_completed' and r['segment_quality']=='usable' and
            r['distance_m']>=900 and b>0 and a>b and total>a and first>0 and total-a>first):
            groups[r['race_id']].append((r['entry_id'], total-a, a-b, b))
    flags = {}
    for group in groups.values():
        mid, last = median(x[1] for x in group), median(x[3] for x in group)
        for eid, early, between, finish in group:
            flags[eid] = int(early-mid<=-.3 and finish-last>=.5 and finish-between/2>=.5)
    summary = json.loads((OUT/'summary.json').read_text())
    recent_ids = {r['entry_id'] for r in observations if date(2023,1,1)<=r['event_date']<=date(2026,9,12) and r['distance_m']>=800}
    assert len(recent_ids)==summary['starts']==25529
    assert sum(e in recent_ids for e in flags)==summary['valid_splits']
    assert sum(v for e,v in flags.items() if e in recent_ids)==summary['fast_then_fade']
    declarations = {r['entry_id']:r['declared_burden_kg'] for r in pl.read_parquet(
        ROOT/'data/research/jeju_native_transition_features_v1_20260916/context_targets.parquet').to_dicts()}
    lineage = json.loads((OUT/'evaluation_lineage.json').read_text())
    pred = {(r['race_id'],r['horse_id']):r for r in pl.read_parquet(ROOT/'data/research/jeju_tempo_pace_pilot_20260917/horse_predictions.parquet').filter(pl.col('model')=='BASE__BASE').to_dicts()}
    assert len(lineage)==len(pred)==4852
    fade_n = fade_top3 = 0
    ps = []
    for r in lineage:
        o = rows[r['entry_id']]
        p = pred[(o['race_id'],o['horse_id'])]
        # pandas JSON export keeps ten decimal places; parquet retains doubles.
        assert p['y']==r['y'] and abs(p['p']-r['p'])<1e-9
        assert declarations[o['entry_id']]==o['burden_kg']
        if r['previous_entry_id'] is None:
            continue
        prev = rows[int(r['previous_entry_id'])]
        assert prev['horse_id']==o['horse_id']
        assert (o['event_date']-prev['event_date']).days>=2
        if r['burden_delta'] is not None:
            assert abs(declarations[o['entry_id']]-prev['burden_kg']-r['burden_delta'])<1e-9
        assert flags.get(prev['entry_id'])==r['previous_fast_then_fade']
        if r['previous_fast_then_fade']==1 and r['previous_top3'] is False and r['burden_group']=='decrease':
            fade_n+=1;fade_top3+=r['y'];ps.append(r['p'])
    reported = json.loads((OUT/'next_start_associations.json').read_text())['previous_fade_nonpodium_burden_decrease']
    assert fade_n==reported['starts'] and fade_top3==reported['top3']
    assert abs(np.mean(ps)-reported['predicted_rate'])<1e-9
    result = dict(input_and_output_hashes=True, independent_split_arithmetic=True,
        lineage_horse_identity_and_T_minus_2=True, declarations_equal_observed_burden_all_4852=True,
        fixed_predictions_match_within_json_precision=True, probability_tolerance=1e-9,
        fade_count=summary['fast_then_fade'],
        fade_then_decrease_starts=fade_n, fade_then_decrease_top3=fade_top3)
    (OUT/'independent_verification.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':
    main()

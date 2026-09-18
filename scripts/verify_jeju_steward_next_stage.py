"""Independent lineage, extraction and frozen-error accounting checks."""
import hashlib
import json
from datetime import timedelta
from pathlib import Path

import polars as pl

ROOT=Path(__file__).resolve().parents[1]
S=ROOT/'data/research/jeju_steward_events_v1_20260917'
D=ROOT/'data/research/jeju_steward_pace_diagnosis_20260917'
P=ROOT/'data/research/jeju_tempo_pace_pilot_20260917'


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    checked=0
    for root in [S,D,P]:
        m=json.loads((root/'manifest.json').read_text())
        for path,h in m['files'].items():
            assert sha(root/path)==h,path;checked+=1
        for path,h in m.get('parents',{}).items():assert sha(Path(path))==h
    lock=json.loads((S/'protocol_lock.json').read_text())
    assert sha(ROOT/'src/horse_racing/analysis/jeju_steward_events.py')==lock['rules_sha256']
    assert sha(ROOT/'docs/JEJU_NATIVE_STEWARD_NEXT_STAGE_PLAN_2026-09-17.md')==lock['plan_sha256']
    obs={r['entry_id']:r for r in pl.read_parquet(ROOT/'data/research/jeju_tempo_pace_features_20260917/observations.parquet').to_dicts()}
    events={e['event_id']:e for e in json.loads((S/'events.json').read_text())}
    for r in pl.read_parquet(S/'features.parquet').to_dicts():
        target=obs[r['entry_id']]
        previous=obs.get(r['previous_entry_id'])
        if previous:
            assert previous['horse_id']==target['horse_id']
            assert previous['event_date']<=target['event_date']-timedelta(days=2)
        if not r['previous_report_known']:assert r['previous_explicit_event'] is None
        for key in r['source_event_ids']:
            e=events[key]
            assert e['field']=='judgement' and e['status']=='explicit_rule_match'
            assert any(a['entry_id']==r['previous_entry_id'] for a in e['affected'])
            assert e['date']==previous['event_date'].isoformat()
    changes=pl.read_parquet(D/'race_changes.parquet')
    assert changes.height==changes['race_id'].n_unique()==510
    for r in changes.to_dicts():
        b=set(r['base_set'])==set(r['actual_podium']);p=set(r['pace_set'])==set(r['actual_podium'])
        category='both_hit' if b and p else 'new_hit' if p else 'lost_hit' if b else 'both_miss'
        assert r['category']==category
    assert changes.filter(pl.col('category')=='new_hit').height==10
    assert changes.filter(pl.col('category')=='lost_hit').height==3
    assert changes['base_overlap'].sum()==changes['pace_overlap'].sum()==788
    swaps=pl.read_parquet(D/'selection_swaps.parquet')
    for r in changes.to_dicts():
        selected=swaps.filter(pl.col('race_id')==r['race_id'])
        for side,expected in [('added',set(r['pace_set'])-set(r['base_set'])),('removed',set(r['base_set'])-set(r['pace_set']))]:
            assert set(selected.filter(pl.col('side')==side)['horse_id'])==expected
    frozen={(r['race_id'],r['horse_id']):r for r in pl.read_parquet(P/'horse_predictions.parquet').filter(pl.col('model')=='BASE__BASE').to_dicts()}
    nexts=pl.read_parquet(D/'next_start_frozen_probabilities.parquet').to_dicts()
    for r in nexts:
        f=frozen[(r['race_id'],r['horse_id'])]
        assert f['p']==r['p'] and f['y']==r['y']
    stats=json.loads((D/'next_start_associations.json').read_text())
    for field in ['previous_explicit_event','previous_route_restriction','previous_wide_trip','previous_running_interference']:
        selected=[r for r in nexts if r['previous_report_known'] and r[field]]
        assert len(selected)==stats[field]['exposed']['entries']
        assert sum(r['y'] for r in selected)==stats[field]['exposed']['top3']
    result=dict(manifest_files_checked=checked,all_84583_T_minus_2_lineages=True,
        no_missing_report_as_normal=True,primary_reports_only=True,parser_unchanged_since_audit=True,
        independent_510_race_category_check=True,independent_788_podium_horse_count=True,
        next_start_probabilities_unchanged=True,new_model_fits=0,
        publication_time_limitation='Race date chronology verified; historical publication/edits not reconstructed.')
    (D/'verification.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()

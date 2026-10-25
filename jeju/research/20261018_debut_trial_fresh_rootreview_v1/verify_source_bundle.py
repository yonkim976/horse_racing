"""Compare the independently generated final source freeze with root snapshots."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from independent_build import ROOT,HERE,RAW,sha,dump_new

SOURCE=ROOT/'jeju/research/20261018_debut_trial_fresh_source_v1/outputs'

def main():
    manifest_path=SOURCE/'audit_manifest.json';m=json.loads(manifest_path.read_text())
    assert sha(manifest_path)=='c3e08c29c6acd8c263b64649e4816e287427338464af966c103623084f56e44a'
    assert m['history_reconciliation']['current_db_vs_frozen_sep19_old_rows_clean']
    for name,h in m['output_sha256'].items():
        assert Path(name).name==name and sha(SOURCE/name)==h,name
    old=pd.read_parquet(RAW);actual=pd.read_parquet(SOURCE/'fresh_raw_race_rows.parquet').set_index('api_record_id')
    reference=pd.read_parquet(HERE/'ROOT_RAW_NEW_ROWS.parquet').set_index('api_record_id')
    assert set(actual.index)==set(reference.index)
    reference=reference.loc[actual.index]
    for col in [c for c in old.columns if c!='api_record_id']:
        a=actual[col];b=reference[col]
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            assert np.allclose(a.to_numpy(float),b.to_numpy(float),atol=0,rtol=0,equal_nan=True),col
        else:assert a.astype('string').fillna('<NULL>').equals(b.astype('string').fillna('<NULL>')),col
    target=pd.read_parquet(SOURCE/'eligible_target_roster.parquet');expected=pd.read_parquet(HERE/'ROOT_TARGET_ROSTER.parquet')
    assert set(target.api_record_id)==set(expected.api_record_id)
    cold=pd.read_parquet(SOURCE/'cold_target_roster.parquet');expectedcold=pd.read_parquet(HERE/'ROOT_COLD_TARGETS.parquet')
    assert set(cold.api_record_id)==set(expectedcold.api_record_id)
    slots=pd.read_parquet(SOURCE/'actual_slot_point_eligibility_fresh_targets.parquet')
    ref=pd.read_parquet(HERE/'ROOT_FRESH_STYLE_LINEAGE.parquet')
    keys=['target_api_record_id','source_api_record_id'];joined=slots.merge(ref,on=keys,validate='one_to_one')
    assert len(joined)==len(ref)==len(slots)==1319
    assert (joined.source_race_date==joined.source_date).all() and (joined.target_cutoff==joined.cutoff).all()
    assert (joined.source_snapshot_valid_time==joined.source_valid_time).all()
    for prefix,col in [('s1f','S1F'),('c4','4C'),('g1f','G1F')]:
        assert joined[f'{prefix}_final_point_eligible'].eq(np.isfinite(joined[col])).all()
        a=joined[f'{prefix}_r'].where(joined[f'{prefix}_final_point_eligible']).to_numpy(float)
        assert np.allclose(a,joined[col].to_numpy(float),rtol=0,atol=0,equal_nan=True),col
    actual_trial=pd.read_parquet(SOURCE/'api20_linked_full_peer_event_rows.parquet').set_index('api_record_id')
    expected_trial=pd.read_parquet(HERE/'ROOT_API20_FULL_SOURCE_ROWS.parquet').set_index('api_record_id')
    assert set(actual_trial.index)==set(expected_trial.index)
    for col in ['payload_json','payload_sha256','raw_relative_path','response_sha256','record_index','response_bytes']:
        assert actual_trial[col].astype('string').equals(expected_trial.loc[actual_trial.index,col].astype('string')),col
    proof=dict(status='PASS',manifest_sha256=sha(manifest_path),artifact_hashes_checked=len(m['output_sha256']),
               raw_race_values_exact=True,raw_rows=len(actual),target_rows=len(target),cold_rows=len(cold),
               style_slots_exact=len(joined),all_point_values_and_eligibility_masks_exact=True,
               trial_original_source_rows_exact=len(actual_trial),old_history_parity_clean=True,
               audit_code_sha256=sha(SOURCE.parent/'audit_source.py'),source_files=m['output_sha256'],
               predictions_computed=False)
    dump_new('ROOT_FROZEN_SOURCE_BUNDLE_REVIEW.json',proof)
    print(json.dumps({k:v for k,v in proof.items() if k!='source_files'},indent=2))

if __name__=='__main__':
    main()

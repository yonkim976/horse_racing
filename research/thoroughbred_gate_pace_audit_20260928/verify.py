"""Check saved research contracts and seal the completed artifacts."""
import importlib.metadata
import numpy as np
import pandas as pd
from common import *

def main():
    lock=json.loads((OUT/'protocol_lock.json').read_text())
    for name,h in lock['files'].items():assert sha(OUT/name)==h,name
    d=pd.read_parquet(OUT/'runners.parquet');q=pd.read_parquet(OUT/'quarter_effects.parquet');a=pd.read_parquet(OUT/'adjusted_strata.parquet')
    assert not d.entry_id.duplicated().any()
    assert (d.last_history_date.isna()|d.last_history_date.lt(d.race_date)).all()
    assert d.groupby('race_id').top3.sum().eq(3).all()
    assert d.groupby('race_id').win.sum().eq(1).all()
    assert d.finish_pct.between(0,1).all() and d.s1f_pct.dropna().between(0,1).all()
    assert len(d)==175766 and d.race_id.nunique()==16233
    assert (q.standardized_ci_low<=q.standardized_effect).all() and (q.standardized_ci_high>=q.standardized_effect).all()
    assert len(q)==78 and q.groupby('venue').period_candidate.sum().to_dict()=={'BUSAN':13,'SEOUL':10}
    assert q.deviation_q.between(0,1).all() and np.isfinite(q.standardized_effect).all()
    pairs=pd.read_parquet(OUT/'pack_pairs.parquet');look=d.set_index(['race_id','horse_number']).top3
    inner=pd.MultiIndex.from_frame(pairs[['race_id','inner_horse_number']]);outer=pd.MultiIndex.from_frame(pairs[['race_id','outer_horse_number']])
    expected=look.reindex(outer).to_numpy()-look.reindex(inner).to_numpy()
    assert np.array_equal(expected,pairs.top3_difference.to_numpy())
    pq=json.loads((OUT/'passing_quality.json').read_text());assert pq['raw_source_samples']==pq['source_matches']==15
    rr=json.loads((OUT/'raw_rank_checks.json').read_text());assert rr['checked_races']==rr['matched_races']==1244
    assert all(x['max_contrast_nonestimability']<1e-7 for x in json.loads((OUT/'sensitivity_diagnostics.json').read_text()))
    sd=pd.read_parquet(OUT/'sensitivity_quarters.parquet');primary=sd[sd.variant.eq('primary')].merge(q,on=['venue','quarter'])
    assert np.allclose(primary.effect,primary.standardized_effect,atol=1e-9)
    report=ROOT/'docs/THOROUGHBRED_GATE_PACE_BIAS_REVIEW_2026-09-28.md'
    assert report.exists() and (OUT/'quarter_gate_effects.png').exists()
    dump('verification.json',{'passed':True,'prior_date_contract':True,'source_rank_matches':rr['matched_races'],'source_rank_entries':rr['checked_entries'],'source_passing_matches':15,'pack_pairs_rechecked':len(pairs),'frozen_protocol_hashes_checked':len(lock['files']),'quarter_contrasts_reproduced':len(primary),'operational_db_mutations':0,'predictive_models_trained':0,'versions':{x:importlib.metadata.version(x) for x in ['numpy','pandas','scipy','matplotlib','pyarrow']}})
    files=sorted(p for p in OUT.iterdir() if p.is_file() and p.name!='manifest.json')+[report]
    dump('manifest.json',{'study':'thoroughbred_gate_pace_audit_20260928','status':'complete_observational_only','files':[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files]})
    print('PASS:',len(files),'files sealed in manifest; model/DB updates: 0')

if __name__=='__main__':main()

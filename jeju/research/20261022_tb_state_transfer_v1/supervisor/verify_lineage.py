"""Independent per-horse as-of join of eligible history, without state math."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
STUDY=HERE.parent


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    raw_path=ROOT/'jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet'
    target_path=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet'
    ledger_path=STUDY/'audit/history_eligibility.parquet'
    state_path=STUDY/'inputs/state_features.parquet'
    lineage_path=STUDY/'inputs/state_lineage.parquet'
    raw=pd.read_parquet(raw_path)
    ledger=pd.read_parquet(ledger_path)
    history=raw.loc[raw.race_id.isin(ledger.loc[ledger.history_update_eligible.eq('True'),'race_id'])]
    assert not history.duplicated(['horse_id','race_date']).any()
    target=pd.read_parquet(target_path,columns=['api_record_id','race_id','race_date','horse_id','history_cutoff'])
    state=pd.read_parquet(state_path).set_index('api_record_id').loc[target.api_record_id]
    lineage=pd.read_parquet(lineage_path).set_index('api_record_id').loc[target.api_record_id]
    assert state.index.is_unique and lineage.index.is_unique and len(target)==52155
    for frame in (state,lineage):assert np.array_equal(frame.race_id,target.race_id)
    assert np.array_equal(lineage.horse_id,target.horse_id)
    cutoff=pd.to_datetime(target.race_date).to_numpy(dtype='datetime64[D]')-np.timedelta64(2,'D')
    for column in (target.history_cutoff,state.cutoff,lineage.cutoff):
        assert np.array_equal(pd.to_datetime(column).to_numpy(dtype='datetime64[D]'),cutoff)
    expected_n=np.zeros(len(target),dtype=int)
    expected_day=np.full(len(target),np.datetime64('NaT','D'))
    expected_race=np.full(len(target),None,dtype=object)
    history_map={h:g.sort_values('race_date') for h,g in history.groupby('horse_id')}
    for horse,positions in target.groupby('horse_id',sort=False).indices.items():
        rows=history_map.get(horse)
        if rows is None:continue
        days=pd.to_datetime(rows.race_date).to_numpy(dtype='datetime64[D]')
        counts=np.searchsorted(days,cutoff[positions],side='right')
        expected_n[positions]=counts
        has=counts>0
        expected_day[positions[has]]=days[counts[has]-1]
        expected_race[positions[has]]=rows.race_id.to_numpy()[counts[has]-1]
    for col in (state.state_rank_n,lineage.history_update_count):assert np.array_equal(col,expected_n)
    for col in (state.historydate,lineage.historydate):
        got=pd.to_datetime(col).to_numpy(dtype='datetime64[D]')
        assert np.array_equal(np.isnat(got),np.isnat(expected_day))
        keep=~np.isnat(got)
        assert np.array_equal(got[keep],expected_day[keep])
    got=lineage.latest_history_race_id.fillna('').to_numpy()
    assert np.array_equal(got,pd.Series(expected_race).fillna('').to_numpy())
    result={'passed':True,'rows':len(target),'eligible_history_rows':len(history),
            'all_cutoff_dates_exact_T_minus_2':True,'all_latest_history_dates_and_race_ids_exact':True,
            'all_history_counts_exact':True,'method':'independent per-horse sorted dates and searchsorted(side=right)',
            'no_history_rows':int((expected_n==0).sum()),
            'file_hashes':{str(p.relative_to(ROOT)):sha(p) for p in
                          (raw_path,target_path,ledger_path,state_path,lineage_path,Path(__file__))}}
    with (HERE/'LINEAGE_VERIFICATION.json').open('x') as stream:
        json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()

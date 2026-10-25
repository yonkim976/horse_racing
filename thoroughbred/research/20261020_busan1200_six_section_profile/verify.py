"""Independent arithmetic, exact-past-five and preserved raw sample checks."""

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

import analyze as a


def main():
    a.check_inputs()
    d=pd.read_parquet(a.OUT/'runner_profiles.parquet')
    x=np.column_stack([np.zeros(len(d)),d[a.POINTS].to_numpy(float),d.finish_seconds.to_numpy(float)])
    independent=np.diff(x,axis=1)
    complete=np.isfinite(x).all(axis=1)&(independent>0).all(axis=1)
    assert np.array_equal(complete,d.complete_six)
    assert complete.sum()==34660
    for i,s in enumerate(a.PARTS):
        valid=np.isfinite(independent[:,i])&(independent[:,i]>0)&(x[:,i]>=0)&(x[:,i+1]<=x[:,-1])
        actual=d[s+'_seconds'].to_numpy()
        np.testing.assert_array_equal(np.isfinite(actual),valid)
        np.testing.assert_allclose(actual[valid],independent[valid,i],atol=1e-10,rtol=0)
        idx=d[s+'_index'].to_numpy()
        np.testing.assert_allclose(idx[valid],(200/actual[valid])/(1200/d.finish_seconds.to_numpy()[valid])*100,atol=1e-10,rtol=0)
        np.testing.assert_allclose(d.loc[valid,s+'_delta'],idx[valid]-100,atol=1e-10,rtol=0)
        np.testing.assert_array_equal(d.loc[valid,s+'_delta'].to_numpy()>1e-10,
            d.loc[valid,s+'_equivalent_advantage_seconds'].to_numpy()>1e-10)
    indexes=d[[s+'_index' for s in a.PARTS]].to_numpy()
    np.testing.assert_allclose((100/indexes[complete]).sum(axis=1),6,atol=1e-10,rtol=0)
    # Independent prefix sums/counts for prior5 slots; avoid pandas rolling implementation.
    checked=0
    for _,g in d.groupby('horse_id',sort=False):
        n=len(g);i=np.arange(n);lo=np.maximum(0,i-5)
        for s in a.PARTS:
            for kind in ['index','seconds']:
                z=g[s+'_'+kind].to_numpy(float);valid=np.isfinite(z)
                total=np.r_[0,np.cumsum(np.where(valid,z,0))]
                count=np.r_[0,np.cumsum(valid)]
                sums=total[i]-total[lo];counts=count[i]-count[lo]
                means=np.divide(sums,counts,out=np.full(n,np.nan),where=counts>0)
                np.testing.assert_allclose(g['past5_'+s+'_'+kind+'_mean'],means,atol=1e-9,rtol=0,equal_nan=True)
                if kind=='index':np.testing.assert_array_equal(g['past5_'+s+'_n'],counts)
            checked+=n
        previous=g.date.shift()
        assert (previous.dropna().to_numpy()<g.loc[previous.notna(),'date'].to_numpy()).all()
    examples=pd.read_csv(a.OUT/'example_runners.csv',dtype={'date':str,'horse_id':str})
    fieldmap=dict(zip(a.POINTS,['buS1fAccTime','buG4fAccTime','buG3fAccTime','buG2fAccTime','buG1fAccTime']))
    source_meta=[];cells=0
    for name,g in examples.groupby('source_file'):
        path=(a.ROOT/name).resolve()
        assert path.is_relative_to(a.ROOT)
        before=a.sha(path)
        with gzip.open(path,'rt',encoding='utf-8') as f:
            items=json.load(f)['response']['body']['items']['item']
        for row in g.itertuples():
            raw=items[int(row.source_item_index)]
            assert str(raw['rcDate'])==row.date and int(raw['rcNo'])==row.race_no
            assert str(raw['hrNo']).zfill(7)==row.horse_id and int(raw['rcDist'])==1200
            expected=[float(raw[fieldmap[p]]) for p in a.POINTS]+[float(raw['rcTime'])]
            actual=[getattr(row,p) for p in a.POINTS]+[row.finish_seconds]
            np.testing.assert_allclose(actual,expected,atol=1e-10,rtol=0)
            cells+=len(expected)
        assert a.sha(path)==before
        source_meta.append(dict(path=name,sha256=before,bytes=path.stat().st_size,rows_checked=len(g)))
    a.save('raw_source_manifest.json',source_meta)
    # Two equivalent 13.7s finishes can have different self-normalized indices.
    sample=d[d.date.eq('20260918')&d.race_no.eq(6)].set_index('program_no')
    assert sample.loc[2,'finish_rank']==1
    assert abs(sample.loc[2,'s6_seconds']-sample.loc[3,'s6_seconds'])<1e-10
    assert sample.loc[2,'s6_index']<sample.loc[3,'s6_index']
    example=np.array([72/(11*6)*100,72/(12*6)*100,72/(13*6)*100])
    np.testing.assert_allclose(example,[109.0909090909091,100,92.3076923076923])
    result=json.loads((a.OUT/'verification.json').read_text())
    result.update(status='verified',independent_formula_and_sign_checked_rows=len(d),
        prior5_slot_segment_checks=checked,prior5_incomplete_slots_not_backfilled=True,
        raw_example_runners=len(examples),raw_example_time_cells=cells,raw_sample_max_error=0,
        same_last_segment_different_self_index_example_verified=True,
        reciprocal_index_identity_verified=True,raw_sources_unchanged=True)
    a.save('verification.json',result)
    a.save('preparation_repair.json',dict(issue='First analysis preparation stopped before outputs because nullable pandas boolean masks were not accepted by numpy.select.',
        resolution='Passing-order arrays converted to float/NaN before boolean comparisons; analysis and independent checks rerun.',data_changed=False))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()

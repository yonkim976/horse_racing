"""Verify evidence tiers, target coverage and every stored timing partition."""
import ast
import json

import numpy as np
import pandas as pd

import run as e


def main():
    e.check()
    for p in e.HERE.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
    d=pd.read_csv(e.OUT/'race_evidence.csv',dtype={'date_key':str})
    old=pd.read_csv(e.PRIOR/'equal_races.csv',dtype={'date_key':str})
    assert set(zip(d.date_key,d.race_no))==set(zip(old.date_key,old.race_no)) and len(d)==47
    assert d.live_equal.eq(d.normal_equal).all() and d.live_rows.eq(d.normal_rows).all()
    assert d.live_equal.sum()==480 and d.live_earlier.sum()==1 and d.live_rows.sum()==481
    assert not d.direct_change_verified.any() and not d.direct_no_change_verified.any() and not d.explicit_change.any()
    assert d.clock.gt('18:00').all() and d.clock_differs_from_plan.sum()==3
    source=json.loads((e.OUT/'retained_source_manifest.json').read_text())
    for x in source:
        p=e.ROOT/x['path'];assert e.sha(p)==x['sha256'] and p.stat().st_size==x['bytes']
    assert len(source)==156 and sum(x['matching_lines'] for x in source)==0
    a=pd.read_parquet(e.PRIOR/'runner_audit.parquet').set_index(['date_key','race_no','horse_id'])
    ledger=pd.read_parquet(e.OUT/'partition_audit.parquet')
    defs=pd.read_csv(e.OUT/'partition_definitions.csv')
    counts=[]
    for layout,z in ledger.groupby('layout'):
        parts=defs[defs.layout.eq(layout)]
        expected={'ordinary8':8,'overlap7':7,'common4':4}[layout]
        assert len(parts)==expected and parts.left.iloc[0]=='START' and parts.right.iloc[-1]=='FIN'
        assert parts.right.tolist()[:-1]==parts.left.tolist()[1:]
        selected=a.loc[pd.MultiIndex.from_frame(z[['date_key','race_no','horse_id']])]
        matrix=np.column_stack([np.zeros(len(z))]+[selected[p+'_ms'].to_numpy() for p in parts.right if p!='FIN']+[selected.finish_seconds.to_numpy()*1000])
        okay=np.isfinite(matrix).all(axis=1)&(np.diff(matrix,axis=1)>0).all(axis=1)
        if layout=='ordinary8':okay=okay&selected.comparison.eq('later').to_numpy()
        if layout=='overlap7':okay=okay&selected.comparison.eq('equal').to_numpy()
        np.testing.assert_array_equal(okay,z.usable)
        np.testing.assert_allclose(np.diff(matrix[okay],axis=1).sum(axis=1)/1000,z.loc[z.usable,'partition_sum_seconds'],atol=1e-8,rtol=0)
        np.testing.assert_allclose(z.loc[z.usable,'partition_sum_seconds'],selected.finish_seconds.to_numpy()[okay],atol=1e-8,rtol=0)
        assert (parts.usable_rows==okay.sum()).all()
        normal=int((okay&selected.normal_finish.to_numpy()).sum());assert (parts.normal_usable_rows==normal).all()
        if layout=='common4':assert parts.length_m.tolist()==[200,1000,400,200] and parts.length_m.sum()==1800
        else:assert parts.length_m.iloc[1:-1].isna().all()
        counts.append(dict(layout=layout,rows=len(z),usable=int(okay.sum()),normal_usable=normal))
    e.save(e.OUT/'verification.json',dict(status='verified',live_target_keys=47,live_normal_equal=480,
        route_direct_confirmed=0,route_unresolved=47,no_absence_as_no_change=True,
        retained_source_hashes=156,partition_checks=counts,all_duration_sums_verified=True,
        unverified_corner_lengths_null=True,common_distance_sum=1800,new_models=0,production_changed=False,
        database_access=False))
    e.check();print((e.OUT/'verification.json').read_text())


if __name__=='__main__':main()

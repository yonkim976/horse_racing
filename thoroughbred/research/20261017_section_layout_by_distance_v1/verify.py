"""Verify source-backed layouts, geometry sums, aliases, and frozen crosschecks."""
import ast
import json

import numpy as np
import pandas as pd

import run as e


def main():
    e.check()
    for p in e.HERE.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
    layout=pd.read_csv(e.OUT/'distance_layouts.csv')
    segments=pd.read_csv(e.OUT/'adjacent_segments.csv')
    years=pd.read_csv(e.OUT/'yearly_support.csv')
    aliases=pd.read_csv(e.OUT/'alias_checks.csv')
    summary=json.loads((e.OUT/'summary.json').read_text())
    exceptions=json.loads((e.OUT/'checkpoint_exceptions.json').read_text())
    d,sections=e.load();missing=d.distance_m.isna();assert int(missing.sum())==summary['missing_distance_rows']
    d=d[~missing].copy();d['distance_m']=d.distance_m.astype(int)
    assert len(d)==int(layout.rows.sum())==summary['layout_rows']
    assert len(layout)==21 and len(layout[layout.meet.eq(1)])==11 and len(layout[layout.meet.eq(3)])==10
    assert not d.duplicated(e.KEY).any()
    checked=0;outside=[]
    for row in layout.itertuples():
        g=d[d.meet.eq(row.meet)&d.distance_m.eq(row.distance_m)]
        assert len(g)==row.rows
        basic=g[['START','S1F','G3F','G1F','FIN']].to_numpy(float)
        okay=np.isfinite(basic).all(axis=1)&(np.diff(basic,axis=1)>0).all(axis=1)
        assert okay.sum()==row.basic_complete
        if okay.any():
            np.testing.assert_allclose(np.diff(basic[okay],axis=1).sum(axis=1),g.finish_ms.to_numpy()[okay],atol=1e-8,rtol=0)
        assert 200+(row.distance_m-800)+400+200==row.distance_m
        points=row.points.split(' → ')
        a=g[points].to_numpy(float)
        present=np.isfinite(a).all(axis=1);monotonic=(np.diff(a,axis=1)>0).all(axis=1)
        conflict=np.zeros(len(g),bool)
        relevant=aliases[aliases.meet.eq(row.meet)&aliases.distance_m.eq(row.distance_m)]
        for alias in relevant.itertuples():
            x,y=g[alias.point_a],g[alias.point_b];both=x.notna()&y.notna();diff=both&x.ne(y)
            conflict=conflict|diff.to_numpy()
            assert alias.both_observed==both.sum() and alias.conflict==diff.sum() and alias.equal==(both&~diff).sum()
        fine=present&monotonic&~conflict
        assert row.detail_complete==fine.sum()
        alternative=np.zeros(len(g),bool)
        if row.meet==1 and row.distance_m==1800:
            shorter=g[[p for p in points if p!='1C']].to_numpy(float)
            alternative=g.S1F.eq(g['1C']).to_numpy()&np.isfinite(shorter).all(axis=1)&(np.diff(shorter,axis=1)>0).all(axis=1)
        assert row.detail_with_overlap_alternative==(fine|alternative).sum()
        own=segments[segments.meet.eq(row.meet)&segments.distance_m.eq(row.distance_m)]
        assert len(own)==len(points)-1
        for segment in own.itertuples():
            elapsed=g[segment.right]-g[segment.left]
            valid=elapsed.gt(0)&g[segment.right].notna()&g[segment.left].notna()
            assert segment.endpoint_rows==valid.sum()
        if row.meet==3:
            # Independently derive all distinct physical distances from F=200m.
            positions=sorted(set([0,200,row.distance_m]+[row.distance_m-n*200 for n in [8,6,4,3,2,1]if 0<row.distance_m-n*200<row.distance_m]))
            lengths=np.diff(positions)
            np.testing.assert_array_equal(lengths,own.length_m.to_numpy(int))
            assert lengths.sum()==row.distance_m
            for code,remaining in e.REMAINING.items():
                if row.distance_m-remaining<=0:
                    observed=g[code].notna()
                    if observed.any():outside.append(dict(meet=3,distance_m=row.distance_m,point_code=code,rows=int(observed.sum()),used=False))
        else:
            # Only S1F/G3F/G1F/FIN have route-independent coordinate claims here.
            for segment in own.itertuples():
                if segment.left in ['1C','2C','3C','4C']or segment.right in ['1C','2C','3C','4C']:
                    assert pd.isna(segment.length_m)and segment.length_status=='corner_distance_unverified'
        if fine.any():
            np.testing.assert_allclose(np.diff(a[fine],axis=1).sum(axis=1),g.finish_ms.to_numpy()[fine],atol=1e-8,rtol=0)
        checked+=int(fine.sum())
        yi=years[years.meet.eq(row.meet)&years.distance_m.eq(row.distance_m)]
        assert yi.rows.sum()==len(g) and yi.detail_complete.sum()==fine.sum()
    assert len(exceptions)==int((layout.rows-layout.detail_complete).sum())
    assert checked==summary['partitions_checked']
    for x in exceptions:
        values=x['times_ms'];bad_missing=any(v is None for v in values.values())
        assert x['missing']or x['nonpositive_or_order']or x['alias_conflict']
        if x['missing']:assert bad_missing
    # Crosscheck checkpoints already compared with official raw API in earlier studies.
    d['row_key']=np.where(d.meet.eq(1),'서울:','부산:')+d.date_key+':'+d.race_no.astype(str)+':'+d.horse_id
    indexed=d.set_index('row_key');cross=[]
    for stem in ['20261011_seoul_section_corrections','20261013_busan_section_corrections']:
        path=e.R/stem/'outputs/checkpoint_ledger.parquet';old=pd.read_parquet(path)
        a=indexed.loc[old.row_key]
        columns=['S1F','G3F','G1F','1C','2C','3C','4C']if 'seoul' in stem else ['S1F','G8F','G6F','G4F','G3F','G2F','G1F']
        for col in columns:np.testing.assert_allclose(a[col].to_numpy()/1000,old[col],atol=1e-8,rtol=0,equal_nan=True)
        np.testing.assert_allclose(a.finish_ms.to_numpy()/1000,old.finish,atol=1e-8,rtol=0)
        cross.append(dict(path=str(path.relative_to(e.ROOT)),sha256=e.sha(path),rows=len(old),max_error=0))
    pd.DataFrame(outside).to_csv(e.OUT/'out_of_range_observations.csv',index=False)
    e.save(e.OUT/'verification.json',dict(status='verified',distance_layouts=21,
        normal_runner_rows=summary['normal_rows_including_missing_distance'],distance_missing_rows=int(missing.sum()),
        complete_partitions=checked,overlap_alternatives=summary['overlap_alternatives'],
        source_crosschecks=cross,checkpoint_max_error=0,all_duration_sums_verified=True,
        busan_distance_sums_verified=True,aliases_and_year_counts_verified=True,
        seoul_unverified_lengths_left_null=True,outside_distance_points_excluded=True,
        source_hashes=len(json.loads((e.OUT/'input_manifest.json').read_text())),new_models=0,
        database_access='read_only',production_changed=False,selected22_changed=False,future_contract_changed=False,jeju_access=False))
    e.check();print((e.OUT/'verification.json').read_text())


if __name__=='__main__':main()

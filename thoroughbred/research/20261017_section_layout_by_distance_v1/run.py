"""Read-only sectional layout inventory; no invented physical checkpoints."""
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
DB=ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
SEOUL={1000:['S1F','G3F','4C','G1F'],1100:['S1F','3C','G3F','4C','G1F'],
       1200:['S1F','3C','G3F','4C','G1F'],1300:['S1F','3C','G3F','4C','G1F'],
       1400:['S1F','3C','G3F','4C','G1F'],1600:['S1F','3C','G3F','4C','G1F'],
       1700:['S1F','2C','3C','G3F','4C','G1F'],
       1800:['S1F','1C','2C','3C','G3F','4C','G1F'],
       1900:['S1F','1C','2C','3C','G3F','4C','G1F'],
       2000:['S1F','1C','2C','3C','G3F','4C','G1F'],
       2300:['S1F','1C','2C','3C','G3F','4C','G1F']}
ALIASES={1000:'3C',1600:'2C',1700:'1C'}
REMAINING={'G8F':1600,'G6F':1200,'G4F':800,'G3F':600,'G2F':400,'G1F':200}
KEY=['meet','date_key','race_no','horse_id']


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb')as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def save(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def freeze():
    OUT.mkdir(parents=True,exist_ok=True)
    paths=[HERE/'PLAN.md',HERE/'run.py',DB,DB.parent/'manifest.json',
           ROOT/'docs/SEOUL_SECTION_REPAIR_2026-09-08.md',
           R/'20261011_seoul_section_corrections/analyze.py',
           R/'20261013_busan_section_corrections/analyze.py',
           ROOT/'config/prediction_model_registry.json',
           R/'20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json',
           R/'20261010_axis_signal_calibration_v1/outputs/future_validation_contract.json']
    manifest={str(p.relative_to(ROOT)):sha(p)for p in paths};target=OUT/'input_manifest.json'
    if target.exists():assert json.loads(target.read_text())==manifest
    else:save(target,manifest)
    before=OUT/'publication_before.json'
    if not before.exists():
        files=[R/n for n in ['README.md','ARTIFACT_SIZE_LOG.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json']]
        save(before,{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p))for p in files})
        snap=OUT/'publication_before';snap.mkdir()
        for p in files:(snap/str(p.relative_to(R)).replace('/','__')).write_bytes(p.read_bytes())


def check():
    for path,digest in json.loads((OUT/'input_manifest.json').read_text()).items():assert sha(ROOT/path)==digest,path


def load():
    with duckdb.connect(str(DB),read_only=True)as c:
        runners=c.execute("""select try_cast(source_meet as int) meet,result_date date_key,
            try_cast(result_race_no as int) race_no,horse_id_raw horse_id,
            try_cast(horse_program_no_raw as int) program_no,
            try_cast(race_distance_m_raw as int) distance_m,
            try_cast(finish_time_seconds_raw as double)*1000 finish_ms
            from confirmed_runners where source_meet in ('1','3')
            and try_cast(result_rank_raw as int) between 1 and 30
            and try_cast(finish_time_seconds_raw as double)>0""").df()
        sections=c.execute("""select try_cast(meet as int) meet,race_date date_key,
            try_cast(race_no as int) race_no,horse_id,point_code,measure_kind,time_ms,
            source_field from section_measurements_api where meet in (1,3)
            and measure_kind!='passing_order'""").df()
    assert not runners.duplicated(KEY).any()
    q=sections[sections.measure_kind.eq('cumulative_time')]
    assert not q.duplicated(KEY+['point_code']).any()
    d=runners.merge(q.pivot(index=KEY,columns='point_code',values='time_ms'),on=KEY,how='left',validate='one_to_one')
    d['START']=0.0;d['FIN']=d.finish_ms
    d['year']=d.date_key.str[:4].astype(int)
    return d,sections


def busan_layout(distance):
    grouped={0:['START'],200:['S1F'],distance:['FIN']}
    for code,remaining in REMAINING.items():
        position=distance-remaining
        if 0<position<distance:grouped.setdefault(position,[]).append(code)
    positions=sorted(grouped)
    # S1F is canonical when an identical physical checkpoint has two labels.
    labels=[grouped[p][0]for p in positions]
    return labels,positions,{p:codes for p,codes in grouped.items()if len(codes)>1}


def audit():
    d,sections=load()
    support=[];segments=[];yearly=[];exceptions=[];aliases=[];fieldrows=[]
    missing_distance=d[d.distance_m.isna()].copy()
    d=d[d.distance_m.notna()].copy();d['distance_m']=d.distance_m.astype(int)
    for(meet,distance),g in d.groupby(['meet','distance_m']):
        distance=int(distance);meet=int(meet)
        basic=['START','S1F','G3F','G1F','FIN']
        basic_matrix=g[basic].to_numpy(float)
        coarse=np.isfinite(basic_matrix).all(axis=1)&(np.diff(basic_matrix,axis=1)>0).all(axis=1)
        if meet==1:
            points=['START']+SEOUL[distance]+['FIN']
            coordinates=[0]+[200 if p=='S1F'else distance-600 if p=='G3F'else distance-200 if p=='G1F'else None for p in SEOUL[distance]]+[distance]
            dup={}
            if distance in ALIASES:dup={200:['S1F',ALIASES[distance]]}
        else:
            points,coordinates,dup=busan_layout(distance)
        matrix=g[points].to_numpy(float)
        present=np.isfinite(matrix).all(axis=1)
        monotonic=(np.diff(matrix,axis=1)>0).all(axis=1)
        conflict=np.zeros(len(g),bool)
        for position,codes in dup.items():
            a,b=g[codes[0]],g[codes[1]]
            both=a.notna()&b.notna();different=both&a.ne(b)
            conflict|=different.to_numpy()
            aliases.append(dict(meet=meet,distance_m=distance,point_a=codes[0],point_b=codes[1],
                same_nominal_position_m=position,both_observed=int(both.sum()),equal=int((both&~different).sum()),
                conflict=int(different.sum()),missing_one_or_both=int((~both).sum())))
        fine=present&monotonic&~conflict
        overlap=np.zeros(len(g),bool)
        if meet==1 and distance==1800:
            overlap=g.S1F.eq(g['1C']).to_numpy()
            alternative=[p for p in points if p!='1C']
            a=g[alternative].to_numpy(float)
            overlap=overlap&np.isfinite(a).all(axis=1)&(np.diff(a,axis=1)>0).all(axis=1)
        for left,right,lpos,rpos in zip(points,points[1:],coordinates,coordinates[1:]):
            seconds=(g[right]-g[left])/1000
            okay=g[left].notna()&g[right].notna()&seconds.gt(0)
            length=None if lpos is None or rpos is None else rpos-lpos
            segments.append(dict(meet=meet,distance_m=distance,left=left,right=right,
                 length_m=length,length_status='known_nominal_distance'if length is not None else'corner_distance_unverified',
                 endpoint_rows=int(okay.sum()),all_partition_rows=int(fine.sum()),
                 seconds_mean=float(seconds[okay].mean())if okay.any()else None))
        actual=np.diff(matrix,axis=1)
        if fine.any():np.testing.assert_allclose(actual[fine].sum(axis=1),g.finish_ms.to_numpy()[fine],atol=1e-8,rtol=0)
        lengths=[b-a for a,b in zip(coordinates,coordinates[1:])]if meet==3 else None
        if lengths is not None:assert sum(lengths)==distance
        row=dict(meet=meet,distance_m=distance,rows=len(g),races=g[KEY[:3]].drop_duplicates().shape[0],
             first_date=g.date_key.min(),last_date=g.date_key.max(),
             basic_complete=int(coarse.sum()),detail_complete=int(fine.sum()),
             detail_with_overlap_alternative=int((fine|overlap).sum()),overlap_alternative=int(overlap.sum()),
             missing_detail=int((~present).sum()),nonpositive_or_order=int((present&~monotonic).sum()),
             alias_conflicts=int(conflict.sum()),points=' → '.join(points),segments=len(points)-1,
             lengths_m=None if lengths is None else '+'.join(map(str,lengths)))
        support.append(row)
        for year,ix in g.groupby('year').indices.items():
            yearly.append(dict(meet=meet,distance_m=distance,year=int(year),rows=len(ix),
                basic_complete=int(coarse[ix].sum()),detail_complete=int(fine[ix].sum()),
                detail_with_overlap_alternative=int((fine[ix]|overlap[ix]).sum())))
        bad=~fine
        for j in np.flatnonzero(bad):
            r=g.iloc[j]
            exceptions.append(dict(meet=meet,distance_m=distance,date_key=r.date_key,race_no=int(r.race_no),
                horse_id=r.horse_id,program_no=int(r.program_no),missing=not bool(present[j]),
                nonpositive_or_order=bool(present[j]and not monotonic[j]),alias_conflict=bool(conflict[j]),
                overlap_alternative=bool(overlap[j]),times_ms={p:None if pd.isna(r[p])else float(r[p])for p in points+([ALIASES[distance]]if meet==1 and distance in ALIASES else[])}))
    for(meet,point,kind,field),g in sections.groupby(['meet','point_code','measure_kind','source_field']):
        fieldrows.append(dict(meet=int(meet),point_code=point,measure_kind=kind,source_field=field,rows=len(g)))
    pd.DataFrame(support).to_csv(OUT/'distance_layouts.csv',index=False)
    pd.DataFrame(segments).to_csv(OUT/'adjacent_segments.csv',index=False)
    pd.DataFrame(yearly).to_csv(OUT/'yearly_support.csv',index=False)
    pd.DataFrame(aliases).to_csv(OUT/'alias_checks.csv',index=False)
    pd.DataFrame(fieldrows).to_csv(OUT/'measurement_fields.csv',index=False)
    save(OUT/'checkpoint_exceptions.json',exceptions)
    missing_distance.to_csv(OUT/'missing_distance_rows.csv',index=False)
    save(OUT/'summary.json',dict(normal_rows_including_missing_distance=len(d)+len(missing_distance),
         layout_rows=len(d),missing_distance_rows=len(missing_distance),distance_layouts=len(support),
         partitions_checked=int(sum(r['detail_complete']for r in support)),
         overlap_alternatives=int(sum(r['overlap_alternative']for r in support)),
         exceptions=len(exceptions),database_access='read_only',new_models=0,
         production_changed=False,source_cutoff='2026-09-29; actual race results through2026-09-20',
         physical_corner_lengths_verified=False,interpolated_checkpoints=False))
    save(OUT/'official_sources.json',dict(checked_on='2026-10-17',sources=[
         dict(url='https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1',
              facts='S1F start200m; G3F finish600m; G1F finish200m. General corners1C/2C/3C/4C finish1680/1400/810/530m; not independently verified against each historical route'),
         dict(url='https://race.kra.co.kr/raceScore/cornerRecordDesc.do',
              facts='F=200m; cumulative and closing periods differ; fixed400m rows overlap S1F for1200/1600/2000; initial100/300m for1300/1500/1900'),
         dict(url='https://race.kra.co.kr/chulmainfo/RacingcourseStructure.do?Act=02&Sub=10&meet=3',
              facts='Busan furlong boards at200m intervals; not every board has a stored individual-horse measurement')]))
    print(pd.DataFrame(support).to_string(index=False),flush=True)


if __name__=='__main__':
    freeze();check();audit();check()

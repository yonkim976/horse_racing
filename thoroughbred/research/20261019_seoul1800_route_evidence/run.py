"""Preserve route evidence tiers and derive valid observed timing partitions."""
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
PRIOR=R/'20261019_seoul1800_s1f_1c_audit/outputs'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def save(path,obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def check():
    for name,digest in json.loads((OUT/'input_manifest.json').read_text()).items():assert sha(ROOT/name)==digest,name


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    paths=[HERE/'PLAN.md',HERE/'run.py',HERE/'browser_checks.csv',PRIOR/'equal_races.csv',PRIOR/'runner_audit.parquet',
           ROOT/'config/prediction_model_registry.json',ROOT/'docs/SEOUL_MAP_REDESIGN_2026-09-08.md']
    manifest={str(p.relative_to(ROOT)):sha(p) for p in paths};p=OUT/'input_manifest.json'
    if p.exists():assert json.loads(p.read_text())==manifest
    else:save(p,manifest)
    before=OUT/'publication_before.json'
    if not before.exists():
        shared=[R/n for n in ['README.md','ARTIFACT_SIZE_LOG.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json']]
        save(before,{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in shared})
        snap=OUT/'publication_before';snap.mkdir()
        for p in shared:(snap/str(p.relative_to(R)).replace('/','__')).write_bytes(p.read_bytes())
    old=pd.read_csv(PRIOR/'equal_races.csv',dtype={'date_key':str,'scheduled_start_raw':str})
    web=pd.read_csv(HERE/'browser_checks.csv',dtype={'date_key':str})
    d=old.merge(web,on=['date_key','race_no'],validate='one_to_one')
    assert len(d)==len(old)==len(web)==47 and not d.explicit_change.any()
    assert d.live_equal.eq(d.normal_equal).all() and d.live_rows.eq(d.normal_rows).all()
    d['scorecard_url']='https://race.kra.co.kr/raceScore/ScoretableDetailList.do?meet=1&realRcDate='+d.date_key+'&realRcNo='+d.race_no.astype(str)
    d['checked_on']='2026-10-19';d['direct_change_verified']=False;d['direct_no_change_verified']=False
    d['route_evidence']='indirect_consistent_with_historical_alternate_start;individual_route_unverified'
    d['clock_differs_from_plan']=d.clock.str.replace(':','',regex=False).ne(d.scheduled_start_raw.str.zfill(4))
    # Search only actually retained official report files on the target dates.
    files=[];hits=[];counts=[]
    for ds in sorted(d.date_key.unique()):
        n=0
        for kind in sorted((ROOT/'data/raw/kra_text').iterdir()):
            if not kind.is_dir():continue
            p=kind/'meet=1'/('year='+ds[:4])/('month='+ds[4:6])/('day='+ds[6:])/f'{ds}{kind.name}.rpt'
            if not p.exists():continue
            blob=p.read_bytes()
            try:text=blob.decode('utf-8')
            except UnicodeDecodeError:text=blob.decode('cp949',errors='replace')
            found=[line.strip() for line in text.splitlines() if re.search(r'출발\s*지점|주로\s*변경|내주로|외주로',line)]
            files.append(dict(path=str(p.relative_to(ROOT)),sha256=sha(p),bytes=p.stat().st_size,matching_lines=len(found)))
            hits.extend(dict(path=str(p.relative_to(ROOT)),line=line) for line in found);n+=1
        counts.append(dict(date_key=ds,retained_files=n))
    save(OUT/'retained_source_manifest.json',files);save(OUT/'retained_text_hits.json',hits)
    pd.DataFrame(counts).to_csv(OUT/'retained_date_support.csv',index=False)
    d.to_csv(OUT/'race_evidence.csv',index=False)
    a=pd.read_parquet(PRIOR/'runner_audit.parquet')
    eqkeys=set(zip(d.date_key,d.race_no));a['race_has_equal_pattern']=[(x,y) in eqkeys for x,y in zip(a.date_key,a.race_no)]
    layouts={
        'ordinary8':['START','S1F','1C','2C','3C','G3F','4C','G1F','FIN'],
        'overlap7':['START','S1F','2C','3C','G3F','4C','G1F','FIN'],
        'common4':['START','S1F','G3F','G1F','FIN']}
    parts=[];ledgers=[]
    for layout,points in layouts.items():
        subset=a.copy() if layout=='common4' else a[~a.race_has_equal_pattern].copy() if layout=='ordinary8' else a[a.race_has_equal_pattern].copy()
        values=pd.DataFrame({p:np.zeros(len(subset)) if p=='START' else subset.finish_seconds.to_numpy()*1000 if p=='FIN' else subset[p+'_ms'].to_numpy() for p in points})
        matrix=values.to_numpy(float);present=np.isfinite(matrix).all(axis=1)
        monotonic=(np.diff(matrix,axis=1)>0).all(axis=1)
        usable=present&monotonic
        if layout=='ordinary8':usable=usable&subset.comparison.eq('later').to_numpy()
        if layout=='overlap7':usable=usable&subset.comparison.eq('equal').to_numpy()
        if usable.any():np.testing.assert_allclose(np.diff(matrix[usable],axis=1).sum(axis=1),subset.finish_seconds.to_numpy()[usable]*1000,atol=1e-8,rtol=0)
        for left,right in zip(points,points[1:]):
            length=({'START':200,'S1F':1000,'G3F':400,'G1F':200}.get(left)) if layout=='common4' else 200 if left=='START' or (left=='G1F' and right=='FIN') else None
            parts.append(dict(layout=layout,left=left,right=right,length_m=length,rows=len(subset),usable_rows=int(usable.sum()),normal_usable_rows=int((usable&subset.normal_finish.to_numpy()).sum())))
        z=subset[['date_key','race_no','horse_id','normal_finish','comparison']].copy();z['layout']=layout;z['usable']=usable
        z['partition_sum_seconds']=np.where(usable,np.diff(matrix,axis=1).sum(axis=1)/1000,np.nan)
        ledgers.append(z)
    pd.DataFrame(parts).to_csv(OUT/'partition_definitions.csv',index=False)
    pd.concat(ledgers).to_parquet(OUT/'partition_audit.parquet',index=False)
    save(OUT/'summary.json',dict(target_races=47,live_scorecards_checked=47,live_normal_rows=int(d.live_rows.sum()),
        live_equal_rows=int(d.live_equal.sum()),live_earlier_rows=int(d.live_earlier.sum()),
        explicit_change_scorecards=0,individual_change_verified=0,individual_route_unresolved=47,
        all_scorecard_clocks_after1800=bool(d.clock.gt('18:00').all()),displayed_clock_differences=int(d.clock_differs_from_plan.sum()),
        retained_files=len(files),retained_keyword_hits=len(hits),retained_dates=len(counts),
        official_2024_normalization_verified=True,new_models=0,database_access=False,production_changed=False))
    save(OUT/'official_sources.json',dict(checked_on='2026-10-19',sources=[
        dict(url='https://race.kra.co.kr/down/raceplan_2019.pdf',pdf_page=16,fact='optional Seoul1800 start at1700 position;outer course after2C;total distance unchanged'),
        dict(url='https://race.kra.co.kr/down/raceplan_2023.pdf',pdf_page=14,fact='same optional night/adverse-weather alternate start rule'),
        dict(url='https://race.kra.co.kr/down/raceplan2024_20240828.pdf#page=11',pdf_page=11,fact='Night long-distance starts normalized;1800/1900 use original start positions'),
        dict(url='https://board.kra.co.kr/board/viewBoard.do?boardNo=135&remarkNo=0',fact='public board title/content search for 출발지점 returned0;does not establish complete historical absence')],
        attempts=[dict(method='web_tool',result='old scorecards inaccessible'),dict(method='terminal_urllib',result='DNS unavailable;no response retained'),
                  dict(method='cua_iab',result='all47 official scorecards read via DOM;no explicit route statement'),
                  dict(method='cua_video_link',result='one20190720video click did not expose a playable tab;no footage verification')]))
    check();print((OUT/'summary.json').read_text())


if __name__=='__main__':main()

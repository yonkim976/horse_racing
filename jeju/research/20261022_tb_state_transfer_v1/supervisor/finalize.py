"""Seal completed supervised research without changing any prior artifact."""
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
STUDY=HERE.parent
ROOT=HERE.parents[3]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4194304),b''):h.update(block)
    return h.hexdigest()


def main():
    destination=STUDY/'FINAL_MANIFEST.json'
    assert not destination.exists()
    start=json.loads((HERE/'SESSION_START.json').read_text())
    for filename in ('STATE_VERIFICATION.json','LINEAGE_VERIFICATION.json',
                     'ROSTER_VERIFICATION.json','RESULT_VERIFICATION.json'):
        assert json.loads((HERE/filename).read_text())['passed']
    review=json.loads((STUDY/'review/RESULT_REVIEW.json').read_text())
    print({'review_status':review.get('status')},flush=True)
    pins={}
    def pin(path,expected_sha,size=None):
        path=path.resolve(strict=True)
        assert path.is_relative_to(ROOT)
        assert sha(path)==expected_sha,str(path)
        if size is not None:assert path.stat().st_size==size,str(path)
        pins[str(path.relative_to(ROOT))]={'path':str(path.relative_to(ROOT)),
                                          'bytes':path.stat().st_size,'sha256':expected_sha}
    for item in start['preserve']:pin(ROOT/item['path'],item['sha256'],item['bytes'])
    source=json.loads((STUDY/'audit/source_manifest.json').read_text())
    for name,item in source['sources'].items():pin(ROOT/name,item['sha256'],item['bytes'])
    roster=json.loads((HERE/'ROSTER_VERIFICATION.json').read_text())
    pin(ROOT/roster['db_path'],roster['db_sha256'],roster['db_bytes'])
    prior_bytes=0;prior_studies=[]
    for name in ('20261022_joint_wager_baseline_v1','20261022_rank_stage_temperature_v1',
                 '20261022_dynamic_ability_pace_v1'):
        parent=ROOT/'jeju/research'/name
        old=json.loads((parent/'FINAL_MANIFEST.json').read_text())
        entries=old.get('files',old.get('files_excluding_manifest'))
        for item in entries:
            relative=item['path']
            path=ROOT/relative if relative.startswith('jeju/') else parent/relative
            pin(path,item['sha256'],item.get('bytes',item.get('size_bytes')))
        old_files=[p for p in parent.rglob('*') if p.is_file()]
        total=sum(p.stat().st_size for p in old_files)
        expected=old.get('total_new_file_bytes_including_manifest',old.get('new_study_total_bytes_including_manifest'))
        assert total==expected,(name,total,expected)
        prior_bytes+=total
        prior_studies.append({'path':str(parent.relative_to(ROOT)),'files':len(old_files),'bytes':total})
    assert prior_bytes==start['prior_session_bytes']==38597581
    records=[];groups=defaultdict(int)
    for path in sorted(STUDY.rglob('*')):
        if not path.is_file():continue
        assert not path.is_symlink()
        size=path.stat().st_size
        records.append({'path':str(path.relative_to(ROOT)),'bytes':size,'sha256':sha(path)})
        groups[path.relative_to(STUDY).parts[0]]+=size
    total=sum(item['bytes'] for item in records)
    manifest={'status':'COMPLETED_VERIFIED_RESEARCH','completed_at_utc':datetime.now(timezone.utc).isoformat(),
              'study':str(STUDY.relative_to(ROOT)),
              'decision':'S passes frozen probability gates; retain as next research-validation candidate; F1_STYLE6 remains comparison baseline; no production change',
              'future_independent_validation':False,'market_edge_verified':False,'axis_relative_10pct_target_reached':False,
              'study_budget_bytes':100000000,'session_budget_bytes':300000000,
              'files_excluding_manifest':records,'file_count_including_manifest':len(records)+1,
              'preserved_source_references':list(pins.values()),
              'prior_session_studies':prior_studies,'prior_session_bytes':prior_bytes,
              'manifest_bytes':0,'new_study_bytes_including_manifest':0,'session_bytes_including_manifest':0,
              'disk_free_bytes_at_finalize':shutil.disk_usage(ROOT).free,
              'storage_groups_bytes_excluding_manifest':dict(groups),
              'largest_new_files':sorted(records,key=lambda x:x['bytes'],reverse=True)[:10],
              'byte_accounting':'Logical regular-file bytes including code, documentation, receipts and this manifest; existing source/DB references not copied',
              'self_hash_omitted':True}
    for _ in range(12):
        encoded=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
        new_total=total+len(encoded)
        if manifest['manifest_bytes']==len(encoded) and manifest['new_study_bytes_including_manifest']==new_total:break
        manifest.update(manifest_bytes=len(encoded),new_study_bytes_including_manifest=new_total,
                        session_bytes_including_manifest=prior_bytes+new_total)
    else:raise RuntimeError('manifest byte count did not stabilize')
    assert new_total<=100000000 and prior_bytes+new_total<=300000000
    with destination.open('xb') as stream:stream.write(encoded)
    print(json.dumps({'new_study_bytes':new_total,'session_bytes':prior_bytes+new_total,
                      'new_files':len(records)+1,'source_pins':len(pins),
                      'free_bytes':manifest['disk_free_bytes_at_finalize'],
                      'manifest_sha256':sha(destination)},indent=2))


if __name__=='__main__':main()

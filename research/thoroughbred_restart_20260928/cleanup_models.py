"""Delete only manifest-listed noncurrent Thoroughbred trained models and old prediction caches.

User authorization: 2026-09-28, keep the final model and delete other model versions.
No DB, registry, raw data, feature tables, code, or research conclusions are deleted.
"""
from pathlib import Path
from collections import Counter
import json,hashlib,argparse,subprocess

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
BASE=ROOT/'data/research'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def dump(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def record(p):return {'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)}

def plan():
    if (OUT/'deletion_plan.json').exists() or (OUT/'deletion_receipt.json').exists():
        raise FileExistsError('Cleanup plan is immutable; use a new directory for another cleanup request')
    assert json.loads((OUT/'replay_before.json').read_text())['passed']
    reg=ROOT/'config/prediction_model_registry.json';registry=json.loads(reg.read_text());profile=registry['profiles'][registry['domains']['thoroughbred']['active_profile']]
    keep={ROOT/x['path'] for x in profile['artifacts'].values()}
    for key in ['A_model','BC_model','WIN_ORDER_model']:
        keep.update((ROOT/profile['artifacts'][key]['path']).parent.iterdir())
    # Registered legacy inference reads this even while selected A is current_A.
    keep.add(BASE/'thoroughbred_boundary_20260918_v6/models/2026H2/context_temperature.json')
    roots=sorted(p for p in BASE.glob('thoroughbred*') if p.is_dir());targets=[];retained=[]
    tracked=set(subprocess.check_output(['git','ls-files','--','data/research'],cwd=ROOT,text=True).splitlines())
    for root in roots:
        for p in sorted(root.rglob('*')):
            assert not p.is_symlink(),str(p)
            if not p.is_file():continue
            rel=p.relative_to(root)
            is_candidate=('models' in rel.parts or 'predictions' in rel.parts)
            if is_candidate and p not in keep:
                assert str(p.relative_to(ROOT)) not in tracked,str(p)
                targets.append(record(p))
            else:retained.append(record(p))
    assert targets and all((ROOT/x['path']).is_relative_to(BASE) for x in targets)
    for p in keep:assert p.exists(),str(p)
    for item in profile['artifacts'].values():assert sha(ROOT/item['path'])==item['sha256']
    result={'status':'planned','scope':'only noncurrent model-directory files and generic prediction-cache directories under existing data/research/thoroughbred* studies','registry':record(reg),'protected_dependency_paths':[str(p.relative_to(ROOT)) for p in sorted(keep)],'delete':targets,'retain':retained,'file_count':len(targets),'bytes':sum(x['bytes'] for x in targets)}
    dump(OUT/'deletion_plan.json',result)
    sums=Counter();counts=Counter()
    for r in targets:k=Path(r['path']).parts[2];sums[k]+=r['bytes'];counts[k]+=1
    lines=['# 삭제 전 확정 목록 — 2026-09-28','','현재 등록된 최종 3개 학습 모델(A, B/C, 순서축)과 실행 의존성을 보호한다. 과거 연도 가중치와 비채택 후보의 모델 파일 및 이전 예측 캐시를 삭제한다. 원천 DB·학습 표본·피처 생성 코드·현재 예측·연구 결과표·보고서는 유지한다.','','| 연구 디렉터리 | 파일 수 | MiB |','|---|---:|---:|']
    lines += [f'| {k} | {counts[k]} | {sums[k]/1048576:.2f} |' for k in sorted(sums)]
    lines += ['',f'합계 {len(targets):,}개, {result["bytes"]:,} bytes. 정확한 경로·해시는 deletion_plan.json에 보존한다.','', '이전 manifest는 당시 완전한 산출물의 기록이다. 정리 후에는 삭제된 모델을 포함한 과거 전체 manifest 검사/과거 모델 재추론이 실패하는 것이 예상된다. 현재 운영 모델 검증은 별도로 유지한다.']
    (OUT/'DELETION_PLAN.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'files':len(targets),'bytes':result['bytes'],'MiB':result['bytes']/1048576,'keep':len(keep)},ensure_ascii=False))

def execute():
    p=OUT/'deletion_plan.json';plan=json.loads(p.read_text());assert not (OUT/'deletion_receipt.json').exists()
    assert sha(ROOT/plan['registry']['path'])==plan['registry']['sha256']
    keep=set(plan['protected_dependency_paths']);targets=plan['delete'];deleted=[]
    # Check the whole exact deletion set and all retained study files before first mutation.
    for r in targets+plan['retain']:
        f=ROOT/r['path'];assert f.exists() and not f.is_symlink() and f.resolve().is_relative_to(BASE.resolve()),r['path']
        assert f.stat().st_size==r['bytes'] and sha(f)==r['sha256'],r['path']
    for r in targets:
        assert r['path'] not in keep
        f=ROOT/r['path'];assert ('models' in f.relative_to(BASE).parts or 'predictions' in f.relative_to(BASE).parts)
        f.unlink();deleted.append(r['path'])
    for r in plan['retain']:assert sha(ROOT/r['path'])==r['sha256'],r['path']
    assert all(not (ROOT/r['path']).exists() for r in targets)
    roots=sorted({Path(x).parts[2] for x in deleted})
    for name in roots:
        folder=BASE/name
        for d in sorted((x for x in folder.rglob('*') if x.is_dir()),key=lambda x:len(x.parts),reverse=True):
            if ('models' in d.relative_to(folder).parts or 'predictions' in d.relative_to(folder).parts) and not any(d.iterdir()):d.rmdir()
        (folder/'MODEL_WEIGHTS_RETIRED_2026-09-28.md').write_text('# 모델 파일 정리 기록\n\n2026-09-28 사용자 요청으로 현재 운영 모델 외의 학습 가중치와 과거 예측 캐시를 정리했다. 분석 자료·피처·코드·보고서·평가 결과는 보존했다.\n\n현재 모델: A=v5 2026H2 rolling_all, B/C=v4 2026 top3_growth_strength, 순서축=v2 2026 H3_relative. 운영 등록부 경로를 그대로 유지한다.\n\n정확한 삭제 목록: `research/thoroughbred_restart_20260928/deletion_plan.json`. 삭제 후 검증: 같은 폴더 `replay_after.json` 및 `resolver_after_thoroughbred.json`. 과거 manifest는 삭제 전 기록이므로 완전 재생 가능 상태를 뜻하지 않는다. 이전 학습 가중치의 재추론은 재학습 없이 불가하다.\n')
    receipt={'status':'deleted','files':len(deleted),'bytes':sum(r['bytes'] for r in targets),'plan_sha256':sha(p),'retained_files_verified':len(plan['retain']),'registry_unchanged':sha(ROOT/plan['registry']['path'])==plan['registry']['sha256'],'deleted_paths':deleted,'raw_or_DB_files_deleted':0,'post_replay_pending':True}
    dump(OUT/'deletion_receipt.json',receipt);print(json.dumps({k:v for k,v in receipt.items() if k!='deleted_paths'},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['plan','execute']);args=parser.parse_args()
    plan() if args.mode=='plan' else execute()

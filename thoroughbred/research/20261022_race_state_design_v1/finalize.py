"""Finalize the local design record and exact retained artifact inventory."""
from pathlib import Path
import json
import re
import probe as p

RESEARCH=p.HERE.parent
CONCLUSION=RESEARCH/'conclusions/58B_RACE_STATE_MODEL_DESIGN.md'
MARKER='race_state_design_20261022'
BEFORE=json.loads((p.OUT/'preexisting_files.json').read_text())
INVENTORY=p.OUT/'artifact_inventory.json'

def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def upsert(path,body):
    start=f'<!-- {MARKER}:start -->';end=f'<!-- {MARKER}:end -->'
    old=path.read_text()
    block=f'{start}\n{body.rstrip()}\n{end}'
    if start in old:
        a=old.index(start);b=old.index(end,a)+len(end)
        text=old[:a]+block+old[b:]
    else:
        assert p.sha(path)==BEFORE[str(path.relative_to(p.ROOT))]['sha256'],path
        text=old+'\n\n'+block+'\n'
    path.write_text(text)

def indexes(s):
    title='연구58B 동적 능력·경주 공동착순 설계'
    note=('새 모델은 미학습 제안. 동적 능력·불확실성, 편성 전체 상호작용, 조건부 공동착순 직접 학습을 우선. '
          '기존 EL89의 복연 합집합 최적화 한 정책은 2,484→2,478경주, 개선 미확인. 상대 10%와 10%p 구분. 운영 유지.')
    upsert(RESEARCH/'README.md',f'[{title}]({p.HERE.name}/README.md): {note}')
    upsert(RESEARCH/'conclusions/README.md',f'[{title}]({CONCLUSION.name}): {note}')
    upsert(RESEARCH/'conclusions/SOURCES.md',f'[{title}]({CONCLUSION.name}) · '
        f'[원문](../{p.HERE.name}/README.md) · [사전계획](../{p.HERE.name}/PLAN.md) · '
        f'[정책 결과](../{p.HERE.name}/outputs/results.json) · [검증](../{p.HERE.name}/outputs/verification.json) · '
        f'[DB 감사](../{p.HERE.name}/outputs/database_audit.json). {note}')
    upsert(RESEARCH/'ARTIFACT_SIZE_LOG.md',
        '| 날짜 | 작업 | 신규 파일 | 신규 bytes | MiB | 수정 파일 | 수정 최종 bytes | 순증감 bytes | 명세 |\n'
        '|---|---|---:|---:|---:|---:|---:|---:|---|\n'
        f'| 2026-10-22 | 동적 능력·경주 공동착순 설계와 복연 선택 진단 | {s["new_file_count"]} | '
        f'{s["new_bytes"]} | {s["new_bytes"]/1048576:.6f} | 5 | {s["modified_final_bytes"]} | '
        f'{s["modified_delta_bytes"]:+d} | [명세]({p.HERE.name}/outputs/artifact_inventory.json) |\n\n'
        f'최대 `{s["largest_file"]["path"]}` {s["largest_file"]["bytes"]:,} bytes. '
        f'연구58·58A·58B 신규 보관 파일 합계 {s["combined_new_bytes"]:,} bytes. 신규 학습 0·기존 확률 재사용·DB 쓰기 0.')

def sources():
    target=RESEARCH/'conclusions/source_manifest.json'
    m=json.loads(target.read_text())
    if MARKER not in m['data_end_by_study']:
        assert p.sha(target)==BEFORE[str(target.relative_to(p.ROOT))]['sha256']
    paths=[x for x in p.HERE.rglob('*') if x.is_file() and x.suffix in {'.md','.py','.json'} and x!=INVENTORY]
    for key,files in [('sources',paths),('conclusions',[CONCLUSION])]:
        lookup={x['path']:i for i,x in enumerate(m[key])}
        for path in sorted(files):
            item={'path':str(path.relative_to(p.ROOT)),'sha256':p.sha(path)}
            if item['path'] in lookup:m[key][lookup[item['path']]]=item
            else:m[key].append(item)
    m['data_end_by_study'][MARKER]={'study':p.HERE.name,'evaluation_start':'2024-01-05',
        'evaluation_end':'2026-09-20','races':4799,'runner_rows':50754,
        'new_models':0,'new_policy_count':1,'new_independent_test':False,
        'policy_improvement_confirmed':False,'architecture_status':'proposed_not_trained','production_changed':False}
    m['updated_at']='2026-10-22'
    dump(target,m)

def inventory():
    paths=[x for x in p.HERE.rglob('*') if x.is_file() and '__pycache__' not in x.parts]+[CONCLUSION]
    assert all(not x.is_symlink() for x in paths)
    files=[{'path':str(x.relative_to(p.ROOT)),'bytes':x.stat().st_size} for x in sorted(paths)]
    modifications=[]
    for name,old in BEFORE.items():
        path=p.ROOT/name
        modifications.append({'path':name,'bytes_before':old['bytes'],'bytes_after':path.stat().st_size,
            'delta_bytes':path.stat().st_size-old['bytes'],'sha256_before':old['sha256'],'sha256_after':p.sha(path)})
    previous=sum(json.loads((RESEARCH/name/'outputs/artifact_inventory.json').read_text())['summary']['new_bytes']
        for name in ['20261022_probability_comparison_v1','20261022_probability_followup_v1'])
    total=sum(x['bytes'] for x in files)
    s={'new_file_count':len(files),'new_bytes':total,'largest_file':max(files,key=lambda x:x['bytes']),
       'modified_file_count':5,'modified_final_bytes':sum(x['bytes_after'] for x in modifications),
       'modified_delta_bytes':sum(x['delta_bytes'] for x in modifications),
       'previous_two_studies_new_bytes':previous,'combined_new_bytes':previous+total}
    assert total<5_000_000 and s['combined_new_bytes']<300_000_000
    return {'study':p.HERE.name,'date_kst':'2026-10-22','status':'complete','summary':s,
        'new_files':files,'modified_existing_files':modifications,'self_inclusive':True,
        'units':'logical bytes; MiB=bytes/1048576','excluded':'Existing inputs and transient bytecode; no DB/model/source copies'}

def main():
    p.inputs_check()
    v=json.loads((p.OUT/'verification.json').read_text())
    r=json.loads((p.OUT/'results.json').read_text())
    assert v['status']=='passed' and r['overall']['old_hits']==2484 and r['overall']['new_hits']==2478
    CONCLUSION.write_text('''# 동적 능력·경주 전체 공동착순 설계와 복연 선택 진단

2026-10-22 · 연구58B · 새 구조는 제안 단계, 정책 진단 한 가지 실행 · 운영 미반영.

같은 DB에서 상대 10% 이상 향상을 보장할 근거는 없다. 우선 제안은 말의 능력과 불확실성을 시간에 따라 추정하고, 출전마 전체의 상호작용과 조건부 1·2·3착을 직접 공동 학습하는 작은 모델이다. 기존 고정 요약 변수·말별 점수·사후 확률 조립의 구조와 구분한다. 새로운 구조의 모델 학습은 하지 않았다.

현재 EL89 기준 상대 10% 목표는 축 61.28→67.41%, 복승 3조합 28.94→31.84%, 복연 3조합 51.76→56.94%다. 10%p 상승이나 경주 선별·추천 수 증가와 구분해야 한다.

선택 정책만 바꿀 여지도 한 번 검증했다. 같은 EL89 삼복 분포에서 모든 세 쌍 묶음을 열거해 복연 하나 이상 적중 확률을 정확히 최대화했지만, 4,799경주 적중은 2,484→2,478, 차이 −0.125%p(95% −0.777~+0.530)였다. 적중 조합 총수는 3,282→3,220으로 줄었다. 모델상 평균 최적 합집합 확률은 53.10%로 기존 52.72%보다 소폭 높았을 뿐이다. 이는 해당 확률 아래 선택의 범위이며 실제 적중률 상한이 아니다. 정책은 채택하지 않는다.

서울·부산 원시 DB 스키마 8개와 2017년 이후 182,675행·16,599경주를 읽기 전용으로 확인했다. 원시 자료 존재가 시점 가용성·구간 의미·누락의 해결을 뜻하지 않는다. 2024~2026년은 반복 사용한 개발 자료이며 새 모델의 최종 평가는 경기 전 입력을 봉인한 미래 자료가 필요하다. 사전 시장 배당 확장은 별도 원천 수집이 필요한 다른 과제다.

[전체 설계와 근거](../20261022_race_state_design_v1/README.md) · [사전계획](../20261022_race_state_design_v1/PLAN.md) · [정책 결과](../20261022_race_state_design_v1/outputs/results.json) · [검증](../20261022_race_state_design_v1/outputs/verification.json).
''')
    dump(p.OUT/'completion_checks.json',{'status':'passed','frozen_input_count':len(json.loads((p.OUT/'input_manifest.json').read_text())),
        'new_trained_models':0,'new_policy_count':1,'architecture_is_untrained_proposal':True,
        'policy_improvement_confirmed':False,'additional_policy_search_stopped':True,
        'database_read_only':True,'deployment_or_publication':False,'verification_sha256':p.sha(p.OUT/'verification.json')})
    if not INVENTORY.exists():dump(INVENTORY,{})
    s=inventory()['summary']
    for _ in range(15):
        indexes(s);sources()
        current=inventory();dump(INVENTORY,current);after=inventory()
        if current==after and s==after['summary']:break
        s=after['summary']
    else:raise RuntimeError('inventory did not stabilize')
    assert json.loads(INVENTORY.read_text())==inventory()
    links=0
    for path in [p.HERE/'README.md',p.HERE/'PUBLICATION.md',CONCLUSION]:
        for link in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if '://' in link or link.startswith('#'):continue
            assert (path.parent/link.split('#')[0]).exists(),(path,link)
            links+=1
    m=json.loads((RESEARCH/'conclusions/source_manifest.json').read_text())
    entries=[x for k in ['sources','conclusions'] for x in m[k] if p.HERE.name in x['path'] or x['path']==str(CONCLUSION.relative_to(p.ROOT))]
    assert all(p.sha(p.ROOT/x['path'])==x['sha256'] for x in entries)
    print(json.dumps({'status':'passed',**s,'local_links_checked':links,'source_hashes_checked':len(entries)},ensure_ascii=False))

if __name__=='__main__':main()

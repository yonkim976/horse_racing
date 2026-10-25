"""Self-inclusive logical byte inventory with stable totals and task-only shared deltas."""
from pathlib import Path
from collections import defaultdict
import hashlib,json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
INV=OUT/'artifact_inventory.json'
SIZE=OUT/'SIZE_REPORT.md'
LOG=HERE.parent/'ARTIFACT_SIZE_LOG.md'
CENTRAL=HERE.parent/'conclusions/50_JOCKEY_SWITCH_TRAINER_INTENT.md'
TASK=HERE.name


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def build():
    old={v['path']:v for v in json.loads((OUT/'shared_edits_baseline.json').read_text())['files']}
    owned={v['path']:v for v in json.loads((OUT/'shared_own_edits.json').read_text())['files']}
    paths=set(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.add(CENTRAL);paths.update(ROOT/name for name in old)
    records=[]
    for p in sorted(paths):
        name=str(p.relative_to(ROOT));previous=old.get(name);size=p.stat().st_size
        own_delta=owned[name]['own_delta_bytes'] if previous else size
        if previous and p==LOG:
            own_line=next(line for line in LOG.read_text().splitlines() if f'<!-- {TASK} -->' in line)
            own_delta=len((own_line+'\n').encode('utf-8'))
        after_external=size-previous['bytes']-own_delta if previous else 0
        row=dict(path=name,status='modified' if previous else 'new',bytes=size,
                 prior_bytes=previous['bytes'] if previous else 0,
                 delta_bytes=own_delta,
                 outside_task_delta_after_edit_bytes=after_external,
                 outside_task_delta_bytes=(previous['outside_task_delta_before_edit']+after_external) if previous else 0)
        if p!=INV:row['sha256']=sha(p)
        records.append(row)
    new=[r for r in records if r['status']=='new'];modified=[r for r in records if r['status']=='modified']
    nb=sum(x['bytes'] for x in new);delta=sum(x['delta_bytes'] for x in modified)
    totals=dict(new_file_count=len(new),new_bytes=nb,new_mib=f'{nb/1048576:.6f}',modified_file_count=len(modified),
        modified_final_bytes=sum(x['bytes'] for x in modified),modified_delta_bytes=delta,net_added_bytes=nb+delta,
        net_added_mib=f'{(nb+delta)/1048576:.6f}',outside_task_shared_delta_bytes=sum(x['outside_task_delta_bytes'] for x in modified))
    parts=defaultdict(lambda:dict(files=0,bytes=0))
    for x in new:
        ext=Path(x['path']).suffix or '(none)';parts[ext]['files']+=1;parts[ext]['bytes']+=x['bytes']
    return dict(completed_on='2026-10-12',task=TASK,measurement='Logical file contents; 1 MiB=1048576 bytes',
        scope='Only this study directory, its new central conclusion and five explicitly modified shared indexes/log; unchanged inputs/DB/temp/cache excluded',
        self_inventory_and_size_records_included=True,self_sha256_omitted=True,
        totals=totals,new_components_by_extension=dict(sorted(parts.items())),files=records)


def size_text(x):
    t=x['totals']
    rows=['# 작업 산출물 용량\n',f'2026-10-12 · {TASK} · 파일 내용의 정확한 바이트. 1MiB=1,048,576바이트.\n',
        f"신규 **{t['new_file_count']}개·{t['new_bytes']:,}바이트·{t['new_mib']}MiB**. 수정 {t['modified_file_count']}개 최종 {t['modified_final_bytes']:,}바이트, 이번 작업 수정 순증감 {t['modified_delta_bytes']:+,}바이트. 신규와 수정분을 합친 순증가는 **{t['net_added_bytes']:,}바이트·{t['net_added_mib']}MiB**다.\n",
        '## 신규 구성\n','| 형식 | 파일 수 | 바이트 |\n|---|---:|---:|']
    for key,v in x['new_components_by_extension'].items():rows.append(f"| {key} | {v['files']} | {v['bytes']} |")
    rows+=['\n## 수정 파일\n','| 경로 | 최종 바이트 | 이번 작업 순증감 |\n|---|---:|---:|']
    for r in x['files']:
        if r['status']=='modified':rows.append(f"| {r['path']} | {r['bytes']} | {r['delta_bytes']:+} |")
    rows+=['\n입력 DB·기존 참조·임시 실행 로그·폰트 캐시는 제외했다. 시작 시 관련 기존325개 파일의 목록·크기·해시는 baseline_inventory.json, 공유 파일 수정 직전 크기는 shared_edits_baseline.json, 본 작업 수정 완료 직후 기준은 shared_own_edits.json에 있다. 공유 파일을 다른 작업이 바꾼 부분은 수정 전후로 나눠 별도 표시하며 이번 작업 순증감에서 제외한다.',
        '\n이 문서·artifact_inventory.json·상위 ARTIFACT_SIZE_LOG.md의 이번 추가 행도 집계했다. 파일별 경로·정확한 크기·SHA-256은 [명세](artifact_inventory.json)를 따른다. 자기 파일의 SHA-256만 순환을 피하기 위해 생략했다.']
    return '\n'.join(rows)+'\n'


def log_row(t):
    return f"| 2026-10-12 | 기수 교체·상위 기수·조교사 관계 | {t['new_file_count']} | {t['new_bytes']} | {t['new_mib']} | {t['modified_file_count']} | {t['modified_delta_bytes']:+} | {t['net_added_bytes']:+} | [명세]({TASK}/outputs/artifact_inventory.json) | <!-- {TASK} -->"


def update_log(row):
    content=LOG.read_text();lines=content.splitlines();mark=f'<!-- {TASK} -->'
    found=False
    for i,line in enumerate(lines):
        if mark in line:lines[i]=row;found=True
    if not found:lines.append(row)
    LOG.write_text('\n'.join(lines)+'\n')


def main():
    if not INV.exists():INV.write_text('{}\n')
    if not SIZE.exists():SIZE.write_text('')
    for iteration in range(50):
        x=build();SIZE.write_text(size_text(x));update_log(log_row(x['totals']))
        x=build();INV.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
        if all((ROOT/r['path']).stat().st_size==r['bytes'] for r in x['files']) and SIZE.read_text()==size_text(x) and log_row(x['totals']) in LOG.read_text():
            break
    else:raise RuntimeError('Self-inclusive size totals did not converge')
    y=json.loads(INV.read_text())
    for r in y['files']:
        p=ROOT/r['path'];assert p.stat().st_size==r['bytes'],r['path']
        if 'sha256' in r:assert sha(p)==r['sha256'],r['path']
    assert sum(r['bytes'] for r in y['files'] if r['status']=='new')==y['totals']['new_bytes']
    assert y['totals']['new_bytes']+y['totals']['modified_delta_bytes']==y['totals']['net_added_bytes']
    print(json.dumps(y['totals'],ensure_ascii=False,indent=2))


if __name__=='__main__':main()

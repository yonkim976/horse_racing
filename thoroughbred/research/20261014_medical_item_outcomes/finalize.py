"""Register immutable research findings and record exact, self-inclusive artifact sizes."""
from pathlib import Path
import hashlib,json,re
import numpy as np,pandas as pd

H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs'
CENTRAL=H.parent/'conclusions/55A_MEDICAL_ITEM_OUTCOMES.md'
MARK='<!-- medical_item_outcomes_20261014 -->'

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def dump(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')

def main():
 base=json.loads((O/'baseline.json').read_text())
 for item in base['shared']+base['references']:
  assert sha(ROOT/item['path'])==item['sha256'],item['path']
 db=json.loads((O/'database_reference.json').read_text())
 sources=['# 최근 의료기록 성과 분석의 출처','','## 고정 입력','',
  f"- 연구 코어 `{db['path']}`: {db['bytes']:,} bytes; SHA-256 `{db['sha256']}`. 읽기 전용 참조이며 신규 용량에서 제외한다.",
  '- 원천은 최신 연도별 API16과 코어 경주 결과다. Text와 다른 API 관측본을 합산하지 않았다.',
  '- 원천 공개 시각은 미확인이다. 이번 추정은 후향적 관측 연관성이며 임상 경중·치료 인과효과·운영 예측의 검증이 아니다.','',
  '## 공식 착순 코드 참고','',
  '[KRA 출전상세정보](https://race.kra.co.kr/chulmainfo/chulmaDetailInfo10Score.do?Act=02&Sub=1&meet=1&rcDate=20190602&rcNo=8)의 순위 특이사항에서 91 실격·92 주행중지와 93~95 제외·취소를 구분한다. 2026년 10월 14일 확인했으며 말별 임상 진단이나 모든 원천 코드의 검증 근거로 확장하지 않는다.','',
  '## 이전 자료 보존','',
  '다음 파일들은 내용·바이트·SHA-256을 작업 전후 대조했다. 사전 용어 문서는 의미·원천 한계의 참고이며 성적 효과의 근거는 새 추정치다.','']
 for item in base['references']:
  sources.append(f"- `{item['path']}`: {item['bytes']} bytes; `{item['sha256']}`")
 (H/'SOURCES.md').write_text('\n'.join(sources)+'\n')
 # Final statistical/editorial checks precede source-manifest hashing.
 e=pd.read_csv(O/'adjusted_associations.csv');cov=pd.read_csv(O/'followup_coverage.csv');ver=json.loads((O/'verification.json').read_text())
 assert ver['status']=='passed' and ver['models']==41 and ver['coefficient_rows']==6204
 assert len(list((O/'models').glob('*.npz')))==41
 a=e.query("period=='2024_2025' and variant=='primary' and state=='new'")
 assert len(a)==561
 assert cov.set_index('period').loc['2024_2025','rows']==70587
 assert cov.set_index('period').loc['2026_partial','rows']==14797
 perf=a[a.domain.eq('conditional_performance')&a.supported&a.identified]
 bad=(perf.target.str.startswith('top3')&perf.estimate.lt(0))|(~perf.target.str.startswith('top3')&perf.estimate.gt(0))
 assert int((bad&perf.q_domain.lt(.05)).sum())==0
 wait=a[a.target.eq('restricted_wait_180')].set_index('family')
 for fam in ['fracture','tendon_ligament','post_arthroscopy','post_castration','lameness','physical_therapy']:
  assert wait.loc[fam,'supported'] and wait.loc[fam,'estimate']>0 and wait.loc[fam,'q_joint']<.05
 for p in H.glob('*.py'):compile(p.read_text(),str(p),'exec')
 review={'status':'passed','models':41,'independent_checks':ver['checks'],
  'figures_visually_reviewed':1,'primary_joint_BH_tests_per_state':561,
  'conditional_performance_domain_BH_tests_per_state':297,
  'conditional_performance_domain_supported_declines':0,
  'same_baseline_used_for_all_three_followups':True,'later_ability_outcomes_not_used_as_new_prior_form':True,
  'joint_nonreturn_nonpodium_not_called_persistent_poor_performance':True,
  'post_estimation_domain_sensitivity_disclosed':True,
  'no_causal_clinical_severity_or_production_claim':True,'prior_files_preserved':len(base['references'])}
 dump(O/'final_review.json',review)
 note=('2024~2025년1,621두·70,587주,2026첫분기별도. 능력·진료전성적 보정 후 '
       '골절문구+62.9일·건/인대+38.7일·파행+12.5일의180일제한대기 차이. '
       '복귀성적 영역별 다중비교 확정저하0,두세경주 지속미확정. '
       '41모형 독립재현·미복귀 결합결과 구분,임상/인과/예측미확정·운영유지.')
 links=[('thoroughbred/research/README.md','20261014_medical_item_outcomes/README.md'),
        ('thoroughbred/research/conclusions/README.md','55A_MEDICAL_ITEM_OUTCOMES.md'),
        ('thoroughbred/research/conclusions/SOURCES.md','55A_MEDICAL_ITEM_OUTCOMES.md')]
 for path,link in links:
  p=ROOT/path;text=p.read_text();assert MARK not in text
  if path.endswith('conclusions/README.md'):
   nums=[int(v) for v in re.findall(r'^\| (\d+) \|',text,re.M)];last=max(nums);assert last==42
   pattern=re.compile(r'^\| '+str(last)+r' \|.*$',re.M);match=pattern.search(text);assert match
   row='\n| 43 | [의료 항목별 출전 공백과 복귀 성적](55A_MEDICAL_ITEM_OUTCOMES.md) | 능력·직전 상태 보정 후 출전 지연 연관, 복귀 성적·지속 저하는 후보/불확실 | 관측 연구·임상/인과/예측 미확정·운영 미반영 |'
   text=text[:match.end()]+row+text[match.end():]
  p.write_text(text+f'\n\n{MARK}\n[의료 항목별 출전 공백과 복귀 성적]({link}): {note}\n')
 manifest_path=ROOT/'thoroughbred/research/conclusions/source_manifest.json'
 manifest=json.loads(manifest_path.read_text())
 files=sorted(p for p in H.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
 for p in files:manifest['sources'].append(dict(path=str(p.relative_to(ROOT)),sha256=sha(p)))
 manifest['conclusions'].append(dict(path=str(CENTRAL.relative_to(ROOT)),sha256=sha(CENTRAL)))
 manifest['medical_item_outcomes_added']=True;manifest['medical_item_outcomes_note']=note
 manifest['medical_item_outcomes_independent_table_number']=43
 manifest['data_end_by_study']['medical_item_outcomes_20261014']={
  'primary_landmarks':'2024-01-01~2025-12-29','confirmation_landmarks':'2026-01-05~2026-03-16',
  'actual_used_followup_last_date':'2026-09-12','calendar_followup_days':180,'models':41}
 changed={item['path'] for item in base['shared'][:3]}
 for key in ['sources','conclusions']:
  for item in manifest[key]:
   if item['path'] in changed:item['sha256']=sha(ROOT/item['path'])
 dump(manifest_path,manifest)
 # Exact logical bytes, with inventory/size report/log row included in the fixed point.
 inv=O/'artifact_inventory.json';size=O/'artifact_size.md';log=ROOT/'thoroughbred/research/ARTIFACT_SIZE_LOG.md'
 original_log=log.read_text();assert MARK not in original_log
 inv.write_text('{}\n');size.write_text('')
 last=None
 for _ in range(30):
  fresh=sorted([p for p in H.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[CENTRAL])
  new=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size) for p in fresh]
  mod=[]
  for item in base['shared']:
   p=ROOT/item['path'];n=p.stat().st_size
   mod.append(dict(path=item['path'],before_bytes=item['bytes'],final_bytes=n,own_delta_bytes=n-item['bytes'],external_delta_bytes=0))
  total=sum(x['bytes'] for x in new);delta=sum(x['own_delta_bytes'] for x in mod)
  data=dict(new_file_count=len(new),new_total_bytes=total,new_total_mib=f'{total/1048576:.6f}',new_files=new,
   modified_file_count=len(mod),modified_final_bytes=sum(x['final_bytes'] for x in mod),modified_files=mod,
   own_modified_delta_bytes=delta,net_added_bytes=total+delta,self_included=True,
   unchanged_inputs_database_temporary_files_and_caches_excluded=True)
  dump(inv,data)
  size.write_text(f'# 최근 의료기록 성과 연구의 용량\n\n신규 {len(new)}파일 {total:,} bytes ({total/1048576:.6f} MiB). '
    f'기존 {len(mod)}파일 최종 {data["modified_final_bytes"]:,} bytes, 자체 순증감 {delta:+,} bytes. '
    '중앙 결론·명세·용량 문서를 포함한다. 기존 DB·참고자료·캐시·임시는 제외한다.\n')
  log.write_text(original_log+f'\n{MARK}\n- 2026-10-14 의료 항목별 출전 공백·복귀1~3전: '
    f'신규 {len(new)}파일 {total:,} bytes ({total/1048576:.6f} MiB); 기존 {len(mod)}파일 자체 순증감 {delta:+,} bytes. '
    '[명세](20261014_medical_item_outcomes/outputs/artifact_inventory.json).\n')
  state=(total,delta,inv.stat().st_size,size.stat().st_size,log.stat().st_size)
  if state==last:break
  last=state
 else:raise AssertionError('size inventory did not converge')
 for item in data['new_files']:assert (ROOT/item['path']).stat().st_size==item['bytes'],item['path']
 for item in data['modified_files']:assert (ROOT/item['path']).stat().st_size==item['final_bytes'],item['path']
 for item in base['references']:assert sha(ROOT/item['path'])==item['sha256']
 for key in ['sources','conclusions']:
  for item in manifest[key]:
   if item['path'].startswith(str(H.relative_to(ROOT))) or item['path']==str(CENTRAL.relative_to(ROOT)) or item['path'] in changed:
    assert sha(ROOT/item['path'])==item['sha256'],item['path']
 print(json.dumps({k:data[k] for k in ['new_file_count','new_total_bytes','new_total_mib','modified_file_count','own_modified_delta_bytes']},ensure_ascii=False))
 print('largest',max(data['new_files'],key=lambda x:x['bytes']))
if __name__=='__main__':main()

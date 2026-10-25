"""Preserve research catalog provenance and register exact self-inclusive logical bytes."""
from pathlib import Path
import hashlib,json
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs'
CENTRAL=H.parent/'conclusions/55B_MEDICAL_RISK_CATALOG.md';MARK='<!-- medical_risk_catalog_20261014 -->'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def main():
 # Artifact Tool's expanded export inspection is a disposable tool representation.
 # Native XLSX content and compact independent verification are preserved instead.
 auto_inspection=O/'medical_risk_catalog.xlsx.inspect.ndjson'
 if auto_inspection.exists():auto_inspection.unlink()
 b=json.loads((O/'baseline.json').read_text())
 for x in b['references']+b['shared']:assert sha(ROOT/x['path'])==x['sha256'],x['path']
 summary=json.loads((O/'summary.json').read_text());verification=json.loads((O/'verification.json').read_text())
 assert verification['status']=='passed' and summary['total_exact_phrases']==12908
 assert sum(summary['priority_counts'].values())==12908
 rules={'version':'research-attention-v1','status':'candidate_not_individually_clinically_reviewed',
  'priority_labels':{'A':'우선 검토','B':'주의 관찰','C':'영향 미확인','T':'처치 예방 검사 등','U':'판정 보류'},
  'priority_is_not_severity_or_probability':True,'C_is_not_low_risk':True,
  'delay_bands':{'D3':'supported, estimate >=30 days, positive, pooled joint BH q<0.05','D2':'same, estimate >=7 and <30 days',
   'D1':'same below7 days, or domain-only significance labeled separately','D0':'delay not established','U':'insufficient or mapping/compound hold'},
  'thresholds_are_editorial_not_learned':True,'exact_raw_effects_estimated':0,
  'compound_coefficients_not_assigned':True,'contextual_and_parser_only_mappings_held':369,
  'clinical_prior_sources_are_not_patient_diagnoses':True,
  'large_group_delay_can_raise_attention_only_when_raw_observed_in_primary':True,
  'all_five_grades_are_research_candidates':True,'production_changed':False}
 dump(H/'risk_rules.json',rules)
 notes=json.loads((O/'clinical_source_notes.json').read_text())
 text=['# 의료 항목 주의 등급의 출처','','## 기존 통계와 사전','',
  '- 통계 효과는 20261014_medical_item_outcomes의 41개 모형·33분류 결과를 그대로 참고했다. 원문별 직접 효과를 새로 추정하지 않았다.',
  '- 정확한 용어·판정 상태는 medical_v1 사전과 연구 코어의 원문 슬롯을 사용했다. 과거 파서 전용·문맥 필요·제외 판정은 보류했다.',
  '- 연구 코어는 읽기 전용이다. 원천별 관측 수는 중복을 포함하며 실제 방문 수가 아니다. 기존 DB 크기는 신규 용량에서 제외한다.','',
  '## 전문 수의학 참고','']
 for x in notes:text.append(f"- [{x['title']}]({x['url']}), 확인 {x['access_date']}: {x['supported_claim']} 개인별 중증도나 국내 효과의 근거로 확대하지 않는다.")
 text+=['','## 입력 보존 해시','']
 for x in b['references']:text.append(f"- `{x['path']}`: {x['bytes']} bytes; SHA-256 `{x['sha256']}`")
 (H/'SOURCES.md').write_text('\n'.join(text)+'\n')
 review=dict(status='passed',all_catalog_rows=12908,previous_files_preserved=96,
  workbook_sheets_visually_reviewed=2,workbook_preview_ranges_reviewed=3,
  labels_are_not_calibrated_horse_risk=True,group_estimates_not_raw_term_estimates=True,
  no_low_risk_inferred_from_missing_significance=True,
  verified_conditional_performance_decline_count=0,production_changed=False)
 dump(O/'final_review.json',review)
 note=('정확한 원문·사전항목12,908개를 A843/B2312/C2304/T158/U7291로 정리. '
       '검토우선순위와 분류별 지연·복귀성적·원문지원 분리,369문맥/파서보류. '
       '원문별직접효과0·개별중증도/확률미추정,전체엑셀검증·운영유지.')
 for f,link in [('thoroughbred/research/README.md','20261014_medical_risk_catalog/README.md'),
                ('thoroughbred/research/conclusions/README.md','55B_MEDICAL_RISK_CATALOG.md'),
                ('thoroughbred/research/conclusions/SOURCES.md','55B_MEDICAL_RISK_CATALOG.md')]:
  p=ROOT/f;old=p.read_text();assert MARK not in old
  p.write_text(old+f'\n\n{MARK}\n[의료 항목별 주행 관련 주의 등급]({link}): {note} 독립 연구43의 후속, 연구 수 유지.\n')
 mp=ROOT/'thoroughbred/research/conclusions/source_manifest.json';m=json.loads(mp.read_text())
 files=sorted(p for p in H.rglob('*') if p.is_file() and 'node_modules' not in p.parts and '__pycache__' not in p.parts)
 for p in files:m['sources'].append(dict(path=str(p.relative_to(ROOT)),sha256=sha(p)))
 m['conclusions'].append(dict(path=str(CENTRAL.relative_to(ROOT)),sha256=sha(CENTRAL)))
 m['medical_risk_catalog_added']=True;m['medical_risk_catalog_note']=note
 m['data_end_by_study']['medical_risk_catalog_20261014']={'clinical_reference_access':'2026-10-14','local_effects_source':'20261014_medical_item_outcomes','new_regressions':0,'universe_rows':12908}
 changed={x['path'] for x in b['shared'][:3]}
 for key in ['sources','conclusions']:
  for x in m[key]:
   if x['path'] in changed:x['sha256']=sha(ROOT/x['path'])
 dump(mp,m)
 inv=O/'artifact_inventory.json';size=O/'artifact_size.md';log=ROOT/'thoroughbred/research/ARTIFACT_SIZE_LOG.md';original=log.read_text();assert MARK not in original
 inv.write_text('{}\n');size.write_text('');last=None
 for _ in range(30):
  fresh=sorted([p for p in H.rglob('*') if p.is_file() and 'node_modules' not in p.parts and '__pycache__' not in p.parts]+[CENTRAL])
  new=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size) for p in fresh]
  modified=[]
  for x in b['shared']:
   n=(ROOT/x['path']).stat().st_size;modified.append(dict(path=x['path'],before_bytes=x['bytes'],final_bytes=n,own_delta_bytes=n-x['bytes'],external_delta_bytes=0))
  total=sum(x['bytes'] for x in new);delta=sum(x['own_delta_bytes'] for x in modified)
  data=dict(new_file_count=len(new),new_total_bytes=total,new_total_mib=f'{total/1048576:.6f}',new_files=new,
   modified_file_count=len(modified),modified_final_bytes=sum(x['final_bytes'] for x in modified),modified_files=modified,
   own_modified_delta_bytes=delta,net_added_bytes=total+delta,self_included=True,
   original_inputs_db_dependency_symlink_temporary_files_and_caches_excluded=True)
  dump(inv,data)
  size.write_text(f'# 의료 항목 주의 등급의 용량\n\n신규 {len(new)}파일 {total:,} bytes ({total/1048576:.6f} MiB). '
   f'기존 {len(modified)}파일 자체 순증감 {delta:+,} bytes, 최종 {data["modified_final_bytes"]:,} bytes. '
   '명세·용량·중앙 결론 포함, DB·기존 입력·의존성 연결·임시·캐시 제외.\n')
  log.write_text(original+f'\n{MARK}\n- 2026-10-14 의료 항목 주행 주의 등급: 신규 {len(new)}파일 {total:,} bytes '
   f'({total/1048576:.6f} MiB); 기존 {len(modified)}파일 자체 순증감 {delta:+,} bytes. '
   '[명세](20261014_medical_risk_catalog/outputs/artifact_inventory.json).\n')
  state=(total,delta,inv.stat().st_size,size.stat().st_size,log.stat().st_size)
  if state==last:break
  last=state
 else:raise AssertionError('inventory fixed point failed')
 for x in data['new_files']:assert (ROOT/x['path']).stat().st_size==x['bytes']
 for x in data['modified_files']:assert (ROOT/x['path']).stat().st_size==x['final_bytes']
 for x in b['references']:assert sha(ROOT/x['path'])==x['sha256']
 print(json.dumps({k:data[k] for k in ['new_file_count','new_total_bytes','new_total_mib','modified_file_count','own_modified_delta_bytes']}))
 print('largest',max(new,key=lambda x:x['bytes']))
if __name__=='__main__':main()

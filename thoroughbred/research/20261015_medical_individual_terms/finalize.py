"""Register split-term revision and exact self-inclusive artifact storage."""
from pathlib import Path
import hashlib,json
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs'
CENTRAL=H.parent/'conclusions/55C_MEDICAL_INDIVIDUAL_TERMS.md';MARK='<!-- medical_individual_terms_20261015 -->'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
 b=json.loads((O/'baseline.json').read_text())
 for x in b['references']+b['shared']:assert sha(ROOT/x['path'])==x['sha256'],x['path']
 assert json.loads((O/'verification.json').read_text())['status']=='passed'
 # Expanded exporter trace is disposable; compact verification and XLSX are retained.
 trace=O/'medical_individual_terms.xlsx.inspect.ndjson'
 if trace.exists():trace.unlink()
 dump(O/'final_review.json',dict(status='passed',visual_previews_reviewed=5,changed_sheets_visually_reviewed=3,
  individual_terms=3500,reviewed_split_parents=3716,dictionary_only_candidate_split_parents=5110,
  held_parent_phrases=402,official_comma_titles_kept_whole=49,
  new_regressions=0,new_event_links=0,priority_not_clinical_severity=True,
  original_workbook_saved_separately=True,production_changed=False))
 note=('복합원문8,826개를 기존검토3,716개/전체사전일치후보5,110개로 구분해 분리. '
       '사전항목3,500개에 자체등급·관측수 표시,원문12,908개/연결표21,738행 보존. '
       '공식쉼표제목49개유지·402개보류·새회귀/사건연결0·운영유지.')
 changed=[]
 for f,link in [('thoroughbred/research/README.md','20261015_medical_individual_terms/README.md'),
  ('thoroughbred/research/conclusions/README.md','55C_MEDICAL_INDIVIDUAL_TERMS.md'),
  ('thoroughbred/research/conclusions/SOURCES.md','55C_MEDICAL_INDIVIDUAL_TERMS.md')]:
  p=ROOT/f;text=p.read_text();assert MARK not in text
  p.write_text(text+f'\n\n{MARK}\n[의료 원문 구성 항목별 판별]({link}): {note} 독립 연구43 후속, 연구 수 유지.\n');changed.append(f)
 inv=O/'artifact_inventory.json';size=O/'artifact_size.md';inv.write_text('{}\n');size.write_text('')
 mp=ROOT/'thoroughbred/research/conclusions/source_manifest.json';m=json.loads(mp.read_text())
 files=sorted(p for p in H.rglob('*') if p.is_file() and 'node_modules' not in p.parts and '__pycache__' not in p.parts)
 for p in files:m['sources'].append(dict(path=str(p.relative_to(ROOT)),sha256=sha(p)))
 m['conclusions'].append(dict(path=str(CENTRAL.relative_to(ROOT)),sha256=sha(CENTRAL)))
 m['medical_individual_terms_note']=note
 m['data_end_by_study']['medical_individual_terms_20261015']={'catalog_source':'20261014_medical_risk_catalog','new_regressions':0,'individual_terms':3500,'reviewed_split_parents':3716,'dictionary_candidate_split_parents':5110}
 newpaths={str(p.relative_to(ROOT)) for p in files}|set(changed)|{str(CENTRAL.relative_to(ROOT))}
 log=ROOT/'thoroughbred/research/ARTIFACT_SIZE_LOG.md';original=log.read_text();assert MARK not in original
 last=None
 for _ in range(30):
  for key in ['sources','conclusions']:
   for x in m[key]:
    if x['path'] in newpaths:x['sha256']=sha(ROOT/x['path'])
  dump(mp,m)
  fresh=sorted(files+[CENTRAL]);new=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size) for p in fresh]
  modified=[dict(path=x['path'],before_bytes=x['bytes'],final_bytes=(ROOT/x['path']).stat().st_size,own_delta_bytes=(ROOT/x['path']).stat().st_size-x['bytes'],external_delta_bytes=0) for x in b['shared']]
  total=sum(x['bytes'] for x in new);delta=sum(x['own_delta_bytes'] for x in modified)
  data=dict(new_file_count=len(new),new_total_bytes=total,new_total_mib=f'{total/1048576:.6f}',new_files=new,
   modified_file_count=len(modified),modified_final_bytes=sum(x['final_bytes'] for x in modified),modified_files=modified,
   own_modified_delta_bytes=delta,net_added_bytes=total+delta,self_included=True,
   existing_inputs_db_symlink_caches_and_disposable_export_trace_excluded=True)
  dump(inv,data)
  size.write_text(f'# 병명별 분리 산출물 용량\n\n신규 {len(new)}파일 {total:,} bytes ({total/1048576:.6f} MiB). 기존 {len(modified)}파일 자체 순증감 {delta:+,} bytes, 최종 {data["modified_final_bytes"]:,} bytes. 명세·용량·중앙 결론 포함; 기존 입력·DB·의존성 연결·캐시·임시 내보내기 추적 제외.\n')
  log.write_text(original+f'\n{MARK}\n- 2026-10-15 의료 원문 병명별 분리: 신규 {len(new)}파일 {total:,} bytes ({total/1048576:.6f} MiB); 기존 {len(modified)}파일 자체 순증감 {delta:+,} bytes. [명세](20261015_medical_individual_terms/outputs/artifact_inventory.json).\n')
  state=tuple(sha(p) for p in [inv,size,log,mp])
  if state==last:break
  last=state
 else:raise AssertionError('inventory did not converge')
 for x in data['new_files']:assert (ROOT/x['path']).stat().st_size==x['bytes']
 for x in data['modified_files']:assert (ROOT/x['path']).stat().st_size==x['final_bytes']
 for x in b['references']:assert sha(ROOT/x['path'])==x['sha256']
 for key in ['sources','conclusions']:
  for x in m[key]:
   if x['path'] in newpaths:assert sha(ROOT/x['path'])==x['sha256'],x['path']
 print(json.dumps({k:data[k] for k in ['new_file_count','new_total_bytes','new_total_mib','modified_file_count','modified_final_bytes','own_modified_delta_bytes']},ensure_ascii=False))
 print('largest',max(new,key=lambda x:x['bytes']))
if __name__=='__main__':main()

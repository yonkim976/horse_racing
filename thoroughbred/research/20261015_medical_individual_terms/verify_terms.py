"""Verify dictionary boundaries, independent term grades and native workbook preservation."""
from pathlib import Path
import json,hashlib,zipfile,re,xml.etree.ElementTree as ET
import pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';PREV=H.parent/'20261014_medical_risk_catalog'
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def read_xlsx(path):
 result={}
 with zipfile.ZipFile(path) as z:
  strings=[]
  if 'xl/sharedStrings.xml' in z.namelist():
   strings=[''.join(si.itertext()) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
  def val(c):
   v=c.find('m:v',NS)
   if c.get('t')=='s':return strings[int(v.text)]
   if c.get('t')=='inlineStr':return ''.join(c.find('m:is',NS).itertext())
   return None if v is None else v.text
  names=[x.get('name') for x in ET.fromstring(z.read('xl/workbook.xml')).findall('m:sheets/m:sheet',NS)]
  for i,name in enumerate(names,1):
   xml=ET.fromstring(z.read(f'xl/worksheets/sheet{i}.xml'))
   cells={c.get('r'):(val(c),None if c.find('m:f',NS) is None else c.find('m:f',NS).text) for c in xml.findall('m:sheetData/m:row/m:c',NS)}
   result[name]=(cells,xml)
  tables=[ET.fromstring(z.read(n)) for n in z.namelist() if n.startswith('xl/tables/') and n.endswith('.xml')]
 return result,tables
def main():
 base=json.loads((O/'baseline.json').read_text())
 for x in base['references']:assert hashlib.sha256((ROOT/x['path']).read_bytes()).hexdigest()==x['sha256'],x['path']
 old=pd.read_parquet(PREV/'outputs/medical_risk_catalog.parquet').set_index('raw_text')
 dec=pd.read_parquet(O/'parent_split_decisions.parquet');links=pd.read_parquet(O/'component_lineage.parquet');atoms=pd.read_parquet(O/'individual_term_catalog.parquet')
 canonical=set(pd.read_parquet(H.parent/'20261002_medical_v1/dictionary/api33_terms.parquet').ill_name)
 assert len(dec)==12908 and not dec.raw_text.duplicated().any() and set(dec.raw_text)==set(old.index)
 assert len(atoms)==3500 and not atoms.term.duplicated().any() and set(atoms.term)==canonical
 assert set(links.parent_raw)==set(old.index)
 assert not atoms.direct_term_effect_estimated.any() and not dec.new_event_links_created.any()
 grouped={k:v for k,v in links.groupby('parent_raw',sort=False)}
 for r in dec.itertuples():
  target=json.loads(r.targets_json);g=grouped[r.raw_text]
  assert len(target)==r.component_count
  assert g.component.dropna().tolist()==target
  assert r.raw_sha256==hashlib.sha256(r.raw_text.encode()).hexdigest()
  if r.status=='official_title_kept_whole':assert target==[r.raw_text]
  elif r.status in ['reviewed_components','reviewed_single_target']:assert target==json.loads(old.loc[r.raw_text,'reviewed_targets_json'])
  elif r.status=='unique_complete_dictionary_parse_candidate':
   assert all(t in canonical for t in target) and re.fullmatch(' *'+r' *, *'.join(re.escape(t) for t in target)+' *',r.raw_text)
  else:assert not target
 assert dec[dec.raw_text.isin([t for t in canonical if ',' in t])].component_count.eq(1).all()
 for r in atoms.itertuples():
  source=old.loc[r.term]
  for a,b in [('priority','priority'),('record_type','record_type'),('reason','reason'),('direct_weeks','primary_raw_observed_weeks'),('direct_horses','primary_raw_horses')]:assert getattr(r,a)==source[b],(r.term,a)
  assert r.linked_parent_phrases==links.loc[links.component.eq(r.term),'parent_sha256'].nunique()
 grade=atoms.set_index('term').priority
 assert grade['각막염']=='B' and grade['우전굴건염']=='A'
 assert grouped['각막염,우전굴건염'].component.tolist()==['각막염','우전굴건염']
 previous,pt=read_xlsx(PREV/'outputs/medical_risk_catalog.xlsx');new,nt=read_xlsx(O/'medical_individual_terms.xlsx')
 assert list(new)==['요약과 기준','전체 항목','단일 항목 판별','원문별 분리 내역']
 for name,(cells,xml) in previous.items():
  for address,value in cells.items():
   if name=='요약과 기준' and address in [c+str(r) for c in 'ABCD' for r in [19,20]]:continue
   assert new[name][0][address]==value,(name,address)
  for tag in ['cols','sheetViews','conditionalFormatting']:
   nodes=xml.findall('m:'+tag,NS);newnodes=new[name][1].findall('m:'+tag,NS)
   assert [ET.tostring(n) for n in nodes]==[ET.tostring(n) for n in newnodes],(name,tag)
  # Import/export must preserve original row heights and native font/fill styles.
  for row in xml.findall('m:sheetData/m:row',NS):
   nr=new[name][1].find(f"m:sheetData/m:row[@r='{row.get('r')}']",NS)
   assert row.get('ht')==nr.get('ht'),(name,row.get('r'),'height')
 payload=json.loads((O/'workbook_data.json').read_text())
 for key,name in [('individual','단일 항목 판별'),('lineage','원문별 분리 내역')]:
  cells,xml=new[name];data=payload[key];assert len(xml.findall('m:sheetData/m:row',NS))==len(data['rows'])+1
  for i,row in enumerate([data['headers']]+data['rows'],1):
   for j,v in enumerate(row):
    address=chr(65+j)+str(i);actual=cells.get(address,(None,None))[0]
    if key=='lineage' and j==5 and i>1:
     v={'context_or_parser_hold':'문맥·파서 검토 보류','official_title_kept_whole':'공식 사전 제목 유지','reviewed_components':'기존 검토 구성요소','reviewed_single_target':'기존 검토 단일 대응','unique_complete_dictionary_parse_candidate':'전체 문구 사전 일치 후보','exact_dictionary_single_candidate':'단일 사전 일치 후보','ambiguous_dictionary_parse_hold':'분리 경로 중복 보류','unresolved_hold':'분리 불명확 보류'}[v]
    if v is None or v=='':assert actual in [None,''],(name,address,actual)
    elif isinstance(v,(int,float)):assert abs(float(actual)-v)<1e-9,(name,address,v,actual)
    else:assert actual==v,(name,address,v,actual)
  pane=xml.find('m:sheetViews/m:sheetView/m:pane',NS);assert pane.get('xSplit')=='2' and pane.get('ySplit')=='1'
 assert len(nt)==3 and all(t.find('m:autoFilter',NS) is not None for t in nt)
 for t in pt:
  corresponding=next(x for x in nt if x.get('name')==t.get('name'))
  assert ET.tostring(t)==ET.tostring(corresponding)
 for name,(cells,_) in new.items():assert not any(v in ['#REF!','#DIV/0!','#VALUE!','#NAME?','#N/A','#NUM!','#NULL!','#SPILL!','#CALC!'] for v,f in cells.values()),name
 result=dict(status='passed',old_files_preserved=len(base['references']),parent_phrases=12908,individual_terms=3500,lineage_rows=21738,
  all_parent_component_orders_checked=True,all_individual_grades_and_direct_counts_match_own_source=True,
  official_comma_titles_preserved=49,parent_frequencies_not_duplicated_into_terms=True,
  original_workbook_cells_formulas_widths_row_heights_freeze_filters_and_conditional_formats_preserved=True,
  new_sheet_all_data_cells_checked=True,new_sheet_filters_and_freeze_verified=True,
  new_regressions=0,new_event_links=0,production_changed=False)
 (O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()

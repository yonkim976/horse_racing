"""Coverage, rule guards, exact-term provenance and native XLSX export checks."""
from pathlib import Path
import json,hashlib,zipfile,xml.etree.ElementTree as ET
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';D=H.parent/'20261002_medical_v1/dictionary'
def main():
 a=pd.read_parquet(O/'medical_risk_catalog.parquet');counts=pd.read_parquet(O/'source_phrase_counts.parquet');d=pd.read_parquet(D/'phrase_decisions.parquet');canon=pd.read_parquet(D/'api33_terms.parquet')
 expected=set(counts.raw)|set(d.raw_text)|set(canon.ill_name);assert set(a.raw_text)==expected and not a.raw_text.duplicated().any()
 assert a.priority.isin(['A','B','C','T','U']).all()
 assert not a.direct_raw_term_effect_estimated.any() and not a.verified_performance_decline.any()
 blocked=d[d.contextual_evidence_required.eq(True)|d.review_status.eq('excluded')].raw_text
 assert a.set_index('raw_text').loc[blocked,'priority'].eq('U').all()
 assert a[a.component_count.gt(1)].family_delay_days.isna().all()
 assert a[a.mapping_scope.eq('blocked_context_or_excluded')].family_delay_days.isna().all()
 assert a.raw_sha256.eq(a.raw_text.map(lambda s:hashlib.sha256(s.encode()).hexdigest())).all()
 by=a.set_index('raw_text')
 for raw,priority in [('운동기인성폐출혈','A'),('마비성근색소뇨증','A'),('비출혈','B'),('정치','T'),('재료판매','T'),('인푸렌자예방접종','T')]:assert by.loc[raw,'priority']==priority,(raw,by.loc[raw,'priority'])
 e=pd.read_csv(H.parent/'20261014_medical_item_outcomes/outputs/item_summary.csv').set_index('family')
 group=a[a.family_delay_days.notna()]
 for fam,g in group.groupby('statistical_family'):
  assert np.allclose(g.family_delay_days,e.loc[fam,'restricted_wait_180_estimate'],rtol=0,atol=1e-10)
  assert g.evidence_scope.str.contains('원문별 직접 효과 미추정').all()
 base=json.loads((O/'baseline.json').read_text())
 for x in base['references']:assert hashlib.sha256((ROOT/x['path']).read_bytes()).hexdigest()==x['sha256']
 ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
 with zipfile.ZipFile(O/'medical_risk_catalog.xlsx') as z:
  strings=[]
  if 'xl/sharedStrings.xml' in z.namelist():
   for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',ns):strings.append(''.join(si.itertext()))
  def value(cell):
   v=cell.find('m:v',ns)
   if cell.get('t')=='s':return strings[int(v.text)]
   if cell.get('t')=='inlineStr':return ''.join(cell.find('m:is',ns).itertext())
   return None if v is None else v.text
  details=ET.fromstring(z.read('xl/worksheets/sheet2.xml'));rows=details.findall('m:sheetData/m:row',ns)
  assert len(rows)==len(a)+1
  texts=[];priorities=[]
  for row in rows[1:]:
   cells={c.get('r').rstrip('0123456789'):c for c in row.findall('m:c',ns)}
   texts.append(value(cells['A']));priorities.append(value(cells['B']))
  assert texts==a.raw_text.tolist() and priorities==a.priority.tolist()
  pane=details.find('m:sheetViews/m:sheetView/m:pane',ns);assert pane is not None and pane.get('ySplit')=='1' and pane.get('xSplit')=='2'
  tables=[n for n in z.namelist() if n.startswith('xl/tables/') and n.endswith('.xml')];assert len(tables)==1
  assert ET.fromstring(z.read(tables[0])).find('m:autoFilter',ns) is not None
  summary=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));cells={x.get('r'):x for x in summary.findall('.//m:sheetData/m:row/m:c',ns)}
  for i,priority in enumerate(['A','B','C','T','U'],5):assert float(value(cells['C'+str(i)]))==int(a.priority.eq(priority).sum())
  assert float(value(cells['C10']))==len(a)
 result=dict(status='passed',universe_rows=len(a),all_raw_strings_and_priorities_preserved_in_xlsx=True,
  native_filter_and_freeze_panes_verified=True,all_five_grade_counts_and_total_recalculated=True,
  blocked_context_rows=len(blocked),old_files_preserved=len(base['references']),
  all_group_estimates_match_source=True,raw_term_direct_effects_claimed=0,confirmed_performance_declines_claimed=0,
  clinical_severity_not_assigned=True,production_changed=False)
 (O/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()

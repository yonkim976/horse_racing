"""Read saved XLSX XML to confirm formula caches, filters and source counts."""
import json,zipfile
import xml.etree.ElementTree as ET
from analysis import HERE,save
NS={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def main():
 folder=HERE/'outputs/20261020-leader-pack-size';file=folder/'선두묶음_거리별_입상우승.xlsx';receipt=folder/'saved_workbook_verification.json';assert not receipt.exists()
 assert json.loads((folder/'workbook_verification.json').read_text())['status']=='passed';data=json.loads((HERE/'run01/rates.json').read_text());keys=['individual_top3_pct','individual_win_pct','any_top3_pct','one_top3_pct','two_plus_top3_pct','zero_top3_pct','group_win_pct','two_top3_pct','three_top3_pct'];formulas=values=0
 with zipfile.ZipFile(file) as z:
  book=ET.fromstring(z.read('xl/workbook.xml'));assert [s.attrib['name'] for s in book.find('x:sheets',NS)]==['거리별 결과','집계 원수치']
  first=ET.fromstring(z.read('xl/worksheets/sheet1.xml'));second=ET.fromstring(z.read('xl/worksheets/sheet2.xml'));cells={c.attrib['r']:c for c in first.findall('.//x:c',NS)};raw={c.attrib['r']:c for c in second.findall('.//x:c',NS)}
  for i,r in enumerate(data):
   for j,key in enumerate(keys):
    c=cells[f'{chr(69+j)}{10+i}'];assert c.find('x:f',NS) is not None and c.attrib.get('t')!='e';formulas+=1;v=c.find('x:v',NS);text=None if v is None else v.text
    if r[key] is None:assert text in [None,'']
    else:assert text is not None and abs(float(text)-r[key]/100)<1e-11
    values+=1
   for col,key in [('D','races'),('E','leader_starts'),('F','top3_horses'),('G','winner_horses'),('H','zero_top3_races'),('I','one_top3_races'),('J','two_top3_races'),('K','three_top3_races')]:
    assert float(raw[f'{col}{7+i}'].find('x:v',NS).text)==r[key]
  for sheet in [first,second]:
   assert not any(c.attrib.get('t')=='e' for c in sheet.findall('.//x:c',NS));assert sheet.find('.//x:pane',NS) is not None and sheet.find('.//x:tableParts',NS) is not None
  table_files=[n for n in z.namelist() if n.startswith('xl/tables/') and n.endswith('.xml')];assert len(table_files)==2
  for name in table_files:assert ET.fromstring(z.read(name)).find('x:autoFilter',NS) is not None
 save(receipt,{'status':'passed','saved_rate_formula_caches_verified':values,'saved_formula_cells_verified':formulas,'saved_source_count_cells_verified':len(data)*8,'filter_tables':2,'frozen_headers_both_sheets':True,'unexpected_error_cells':0,'xlsx_bytes':file.stat().st_size});print('Saved XLSX verified',values,'cached rates',flush=True)
if __name__=='__main__':main()

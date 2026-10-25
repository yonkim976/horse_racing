import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {SpreadsheetFile,FileBlob} from '@oai/artifact-tool';
const here=path.dirname(fileURLToPath(import.meta.url)),out=path.join(here,'outputs');
const data=JSON.parse(await fs.readFile(path.join(out,'workbook_data.json'),'utf8'));
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(here,'../20261014_medical_risk_catalog/outputs/medical_risk_catalog.xlsx')));
const before=await wb.render({sheetName:'요약과 기준',range:'A13:C18',scale:1.3,format:'png'});
await fs.writeFile(path.join(out,'original_summary_preview.png'),new Uint8Array(await before.arrayBuffer()));
const status={context_or_parser_hold:'문맥·파서 검토 보류',official_title_kept_whole:'공식 사전 제목 유지',reviewed_components:'기존 검토 구성요소',reviewed_single_target:'기존 검토 단일 대응',unique_complete_dictionary_parse_candidate:'전체 문구 사전 일치 후보',exact_dictionary_single_candidate:'단일 사전 일치 후보',ambiguous_dictionary_parse_hold:'분리 경로 중복 보류',unresolved_hold:'분리 불명확 보류'};
for(const row of data.lineage.rows)row[5]=status[row[5]]??row[5];
const literal=v=>typeof v==='string'&&v.startsWith('=')?"'"+v:v;
function add(name,part,cols,widths,wrapped,tableName,grades){
 const sh=wb.worksheets.add(name),rows=[part.headers,...part.rows].map(r=>r.map(literal)),end=rows.length;
 sh.showGridLines=false;sh.tabColor='#273B53';
 sh.getRange(`A1:${cols.at(-1)}${end}`).values=rows;
 sh.getRange(`A1:${cols.at(-1)}${end}`).format={font:{name:'Arial',size:10},rowHeight:30,verticalAlignment:'center'};
 sh.getRange(`A1:${cols.at(-1)}1`).format={fill:'#273B53',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:36,horizontalAlignment:'center'};
 cols.forEach((c,i)=>sh.getRange(`${c}1:${c}${end}`).format.columnWidth=widths[i]);
 for(const i of wrapped)sh.getRange(`${cols[i]}2:${cols[i]}${end}`).format.wrapText=true;
 let start=2,last=0;
 part.rows.forEach((row,i)=>{
  const lines=Math.max(1,...wrapped.map(j=>Math.ceil([...String(row[j]??'')].reduce((s,ch)=>s+(ch.charCodeAt(0)>255?1.7:1),0)/(widths[j]*.88))));
  const height=Math.max(30,22*lines);
  if(last&&last!==height){sh.getRange(`A${start}:${cols.at(-1)}${i+1}`).format.rowHeight=last;start=i+2;}
  last=height;
 });
 sh.getRange(`A${start}:${cols.at(-1)}${end}`).format.rowHeight=last;
 sh.freezePanes.freezeRows(1);sh.freezePanes.freezeColumns(2);
 sh.tables.add(`A1:${cols.at(-1)}${end}`,true,tableName).showFilterButton=true;
 for(const c of grades){
  sh.getRange(`${c}2:${c}${end}`).conditionalFormats.add('containsText',{text:'A',format:{fill:'#FBE8E5',font:{color:'#8C3026',bold:true}}});
  sh.getRange(`${c}2:${c}${end}`).conditionalFormats.add('containsText',{text:'U',format:{fill:'#FFF0CC',font:{color:'#70571C'}}});
 }
 return sh;
}
const ind=add('단일 항목 판별',data.individual,[...'ABCDEFGHIJKLMN'],[48,18,18,105,28,36,36,36,19,21,23,21,52,90],[0,3,4,5,6,7,12,13],'IndividualMedicalTerms',['B']);
ind.getRange(`I2:J${data.individual.rows.length+1}`).setNumberFormat('#,##0');
ind.getRange(`K2:K${data.individual.rows.length+1}`).setNumberFormat('0.0');
ind.getRange(`L2:L${data.individual.rows.length+1}`).setNumberFormat('#,##0');
add('원문별 분리 내역',data.lineage,[...'ABCDEFGH'],[60,15,50,15,20,40,18,74],[0,2,5],'MedicalTermLineage',['D','E']);
const overview=wb.worksheets.getItem('요약과 기준');
overview.getRange('A19:D20').values=[['병명별 확인','새 시트 「단일 항목 판별」: 중복 제거 3,500개 항목. 등급은 검토 우선순위',null,null],['원문 분리 근거','「원문별 분리 내역」: 기존 검토 3,716개 / 사전 일치 후보 5,110개 / 보류 402개',null,null]];
overview.getRange('A19:D20').format.font={name:'Arial',size:10};
overview.getRange('A19:D20').format.rowHeight=32;
overview.getRange('B19:B20').format.wrapText=true;
wb.recalculate();
const inspection=await wb.inspect({kind:'table',range:"'요약과 기준'!A4:D10",include:'values,formulas',tableMaxRows:7,tableMaxCols:4,maxChars:4000});
await fs.writeFile(path.join(out,'formula_inspection.ndjson'),inspection.ndjson);
for(const [sheetName,range,name] of [['요약과 기준','A13:C20','revised_summary_preview.png'],['단일 항목 판별','A1:C10','individual_preview.png'],['단일 항목 판별','D1:H5','individual_evidence_preview.png'],['원문별 분리 내역','A1:G10','lineage_preview.png']]){
 const blob=await wb.render({sheetName,range,scale:1.4,format:'png'});
 await fs.writeFile(path.join(out,name),new Uint8Array(await blob.arrayBuffer()));
}
await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,'medical_individual_terms.xlsx'));
console.log(JSON.stringify({individual:data.individual.rows.length,lineage:data.lineage.rows.length,sheets:4}));

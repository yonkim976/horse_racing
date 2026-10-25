import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const here=path.dirname(fileURLToPath(import.meta.url));
const out=path.join(here,'outputs');
const data=JSON.parse(await fs.readFile(path.join(out,'workbook_data.json'),'utf8'));
const wb=Workbook.create();
const overview=wb.worksheets.add('요약과 기준');
const detail=wb.worksheets.add('전체 항목');
overview.showGridLines=false;detail.showGridLines=false;
overview.tabColor='#273B53';
const literal=v=>typeof v==='string'&&v.startsWith('=')?"'"+v:v;
const vals=[data.headers,...data.rows].map(row=>row.map(literal));
detail.getRange(`A1:O${vals.length}`).values=vals;
detail.getRange(`A1:O${vals.length}`).format.font={name:'Arial',size:10};
detail.getRange(`A1:O${vals.length}`).format.rowHeight=24;
detail.getRange('A1:O1').format={fill:'#273B53',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:34};
const widths={A:48,B:12,C:18,D:105,E:28,F:36,G:36,H:36,I:15,J:17,K:21,L:52,M:40,N:85,O:90};
for(const [column,width] of Object.entries(widths)){
 detail.getRange(`${column}1:${column}${vals.length}`).format.columnWidth=width;
}
detail.getRange(`I2:J${vals.length}`).setNumberFormat('#,##0');
detail.getRange(`K2:K${vals.length}`).setNumberFormat('0.0');
detail.freezePanes.freezeRows(1);detail.freezePanes.freezeColumns(2);
const table=detail.tables.add(`A1:O${vals.length}`,true,'MedicalRiskCatalog');table.showFilterButton=true;
for(const column of ['A','D','L','N','O'])detail.getRange(`${column}2:${column}${vals.length}`).format.wrapText=true;
detail.getRange(`A1:O${vals.length}`).format.verticalAlignment='center';
detail.getRange('A1:O1').format.horizontalAlignment='center';
const wrapCols=[0,3,11,13,14];
let previousHeight=0,start=2;
for(let i=0;i<data.rows.length;i++){
 const lineCount=Math.max(...wrapCols.map(j=>{
  const str=String(data.rows[i][j]??'');
  const units=[...str].reduce((sum,ch)=>sum+(ch.charCodeAt(0)>255?1.7:1),0);
  return Math.ceil(units/(Object.values(widths)[j]*.88));
 }));
 const height=Math.max(24,22*lineCount);
 if(previousHeight&&height!==previousHeight){detail.getRange(`A${start}:O${i+1}`).format.rowHeight=previousHeight;start=i+2;}
 previousHeight=height;
}
detail.getRange(`A${start}:O${vals.length}`).format.rowHeight=previousHeight;
detail.getRange(`B2:B${vals.length}`).conditionalFormats.add('containsText',{text:'A',format:{fill:'#FBE8E5',font:{color:'#8C3026',bold:true}}});
detail.getRange(`B2:B${vals.length}`).conditionalFormats.add('containsText',{text:'U',format:{fill:'#FFF0CC',font:{color:'#70571C'}}});
overview.getRange('A2').values=[['의료 항목별 주행 관련 주의 등급']];
overview.getRange('A2').format.font={name:'Arial',size:16,bold:true};
overview.getRange('A4:D4').values=[['등급','해석','항목 수','주의할 점']];
const definitions=[
 ['A','우선 검토',null,'주행 관련 기전 또는 큰 출전 지연 분류의 근거. 개별 말의 현재 중증도 아님'],
 ['B','주의 관찰',null,'통증·보행·호흡·전신 상태 등과 관련해 추가 확인'],
 ['C','영향 미확인',null,'안전 또는 저위험 판정이 아님'],
 ['T','처치 예방 검사 등',null,'원래 질병과 위험도를 처치명에서 추정하지 않음'],
 ['U','판정 보류',null,'뜻 불명확·문맥 필요·파서 전용·복합 미확인 등을 포함'],
 ];
overview.getRange('A5:D9').values=definitions;
for(let i=0;i<5;i++)overview.getRange(`C${i+5}`).formulas=[[`=COUNTIFS('전체 항목'!$B$2:$B$${vals.length},A${i+5})`]];
overview.getRange('A10:B10').values=[['전체','사전 제목·관측 원문·기존 검토 원문의 합집합']];
overview.getRange('C10').formulas=[['=SUM(C5:C9)']];
overview.getRange('A13:D18').values=[
 ['해석 기준','내용',null,null],
 ['분류별 통계','2024~2025년 33분류의 관측 연관성을 참고',null,null],
 ['원문별 효과','직접 추정 0개. 같은 분류 수치를 원문 효과로 읽지 않음',null,null],
 ['복귀 경기력','복귀 성적만 검정한 확정 저하 0개. 후보·표본 부족 구분',null,null],
 ['출전 지연','180일 제한 대기기간 차이. 평균 회복일이나 인과효과 아님',null,null],
 ['개별 말 적용','진료일·부위·반복·회복 상태 없이 자동 감점하지 않음',null,null],
 ];
overview.getRange('A21:D21').values=[['수의학 참고','주행 관련 근거','자료 확인일','출처']];
overview.getRange(`A22:D${21+data.sources.length}`).values=data.sources.map(s=>[s.title,s.supported_claim,s.access_date,s.url]);
overview.getRange('A4:D28').format.font={name:'Arial',size:10};
overview.getRange('A4:D28').format.rowHeight=32;
overview.getRange('A4:D28').format.verticalAlignment='center';
for(const r of [4,13,21])overview.getRange(`A${r}:D${r}`).format={fill:'#273B53',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:28};
overview.getRange('A1:A28').format.columnWidth=32;
overview.getRange('B1:B28').format.columnWidth=86;
overview.getRange('C1:C28').format.columnWidth=16;
overview.getRange('D1:D28').format.columnWidth=105;
overview.getRange('C5:C10').setNumberFormat('#,##0');
wb.recalculate();
const inspection=await wb.inspect({kind:'table',range:"'요약과 기준'!A4:D10",include:'values,formulas',tableMaxRows:7,tableMaxCols:4,maxChars:4000});
await fs.writeFile(path.join(out,'workbook_inspection.ndjson'),inspection.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},maxChars:2000});
await fs.writeFile(path.join(out,'workbook_formula_scan.ndjson'),errors.ndjson);
for(const [sheet,range,name] of [['요약과 기준','A2:C18','summary_preview.png'],['전체 항목','A1:C13','catalog_preview.png'],['전체 항목','D1:H6','evidence_preview.png']]){
 const blob=await wb.render({sheetName:sheet,range,scale:1.5,format:'png'});
 await fs.writeFile(path.join(out,name),new Uint8Array(await blob.arrayBuffer()));
}
const file=await SpreadsheetFile.exportXlsx(wb);await file.save(path.join(out,'medical_risk_catalog.xlsx'));
console.log(JSON.stringify({rows:data.rows.length,sheets:2,xlsx:'medical_risk_catalog.xlsx'}));

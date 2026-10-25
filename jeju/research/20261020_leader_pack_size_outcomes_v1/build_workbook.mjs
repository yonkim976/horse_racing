import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const here=path.dirname(fileURLToPath(import.meta.url));
const records=JSON.parse(await fs.readFile(path.join(here,'run01/rates.json'),'utf8'));
const validation=JSON.parse(await fs.readFile(path.join(here,'verification01/verification.json'),'utf8'));
if(validation.status!=='passed'||records.length!==189)throw Error('Verified rates required');
const outputDir=path.join(here,'outputs','20261020-leader-pack-size');
await fs.mkdir(outputDir,{recursive:true});
const wb=Workbook.create();
const sheet=wb.worksheets.add('거리별 결과');
const raw=wb.worksheets.add('집계 원수치');
const periodName={all:'전체', '2024_2025':'2024~2025', '2026':'2026'};
const rawData=records.map(r=>[periodName[r.period],r.distance==='all'?'전체':Number(r.distance),r.leader_count,r.races,r.leader_starts,r.top3_horses,r.winner_horses,r.zero_top3_races,r.one_top3_races,r.two_top3_races,r.three_top3_races,r.days,r.sample_status]);
raw.getRange('A2').values=[['선두 묶음의 거리별 집계 원수치']];
raw.getRange('A3').values=[['출처: 검증된 실제 통과조 경주별 원장. 2017-01-13~2026-09-19 정상완주 5,200경주.']];
raw.getRange('A4').values=[['한 행은 기간·거리·정확한 선두 두수 조합. 0경주는 미관측이며 0성공과 구분.']];
raw.getRange('A6:M6').values=[['기간','거리m','선두 두수','경주 수','말 출전 수','입상말 수','우승말 수','입상 0두 경주','정확 1두 경주','정확 2두 경주','정확 3두 경주','경주일 수','표본 상태']];
raw.getRange(`A7:M${6+records.length}`).values=rawData;
raw.tables.add(`A6:M${6+records.length}`,true,'LeaderPackCounts').showFilterButton=true;
sheet.getRange('A2').values=[['제주 선두 묶음 두수별 입상과 우승']];
sheet.getRange('A3').values=[['2017-01-13~2026-09-19 · S1F 첫 묶음 · 5,200경주 · 입상은 최종 1~3착']];
sheet.getRange('A4').values=[['말 입상·우승은 말 출전 수로, 그룹 비율은 해당 조건의 경주 수로 나눕니다.']];
sheet.getRange('A5').values=[['그룹 0두 + 정확 1두 + 2두 이상 입상 = 100%. 미관측 조합은 비율을 비워 뒀습니다.']];
sheet.getRange('A6').values=[['거리·두수·기간 필터로 비교하세요. 소표본은 100말출전 또는 30경주 또는 20경주일 미만입니다.']];
sheet.getRange('E8').values=[['말 한 마리 기준']];
sheet.getRange('G8').values=[['경주 기준의 그룹 사건']];
sheet.getRange('A9:N9').values=[['기간','거리m','선두 두수','경주 수','말 입상률','말 우승률','1두 이상 입상','정확 1두 입상','2두 이상 입상','입상 0두','그룹 우승','정확 2두 입상','정확 3두 입상','표본 상태']];
const last=9+records.length;
const formulas=records.map((r,i)=>{
 const row=10+i,s=7+i,q="'집계 원수치'!";
 return [`=${q}A${s}`,`=${q}B${s}`,`=${q}C${s}`,`=${q}D${s}`,
  `=IF(D${row}=0,"",${q}F${s}/${q}E${s})`,
  `=IF(D${row}=0,"",${q}G${s}/${q}E${s})`,
  `=IF(D${row}=0,"",SUM(${q}I${s}:K${s})/D${row})`,
  `=IF(D${row}=0,"",${q}I${s}/D${row})`,
  `=IF(D${row}=0,"",SUM(${q}J${s}:K${s})/D${row})`,
  `=IF(D${row}=0,"",${q}H${s}/D${row})`,
  `=IF(D${row}=0,"",${q}G${s}/D${row})`,
  `=IF(D${row}=0,"",${q}J${s}/D${row})`,
  `=IF(D${row}=0,"",${q}K${s}/D${row})`,
  `=${q}M${s}`];
});
sheet.getRange(`A10:N${last}`).formulas=formulas;
sheet.tables.add(`A9:N${last}`,true,'LeaderPackRates').showFilterButton=true;
for(const s of [sheet,raw]){
 s.showGridLines=false;
 s.getUsedRange().format.font={name:'Arial',size:11,color:'#172B3A'};
 s.getUsedRange().format.verticalAlignment='center';
 s.getUsedRange().format.rowHeight=23;
 s.getRange('A2').format.font={name:'Arial',size:16,bold:true,color:'#17334D'};
 s.getRange('A3:A6').format.font={name:'Arial',size:10,color:'#526476'};
 s.getRange('A:A').format.columnWidth=15;
 s.getRange('B:D').format.columnWidth=11;
 s.getRange('E:N').format.columnWidth=14;
 s.getRange('A2:A2').format.rowHeight=30;
}
sheet.tabColor='#17334D';
sheet.getRange(`C10:D${last}`).setNumberFormat('#,##0');
sheet.getRange(`E10:M${last}`).setNumberFormat('0.00%');
sheet.getRange(`C10:M${last}`).format.horizontalAlignment='right';
sheet.getRange('A9:N9').format={fill:'#17334D',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center',rowHeight:43};
sheet.getRange('E8:F8').format.fill='#E4EEF7';
sheet.getRange('G8:M8').format.fill='#EAF2EC';
sheet.getRange('E8:M8').format.font={name:'Arial',size:10,bold:true,color:'#29465B'};
sheet.getRange(`N10:N${last}`).conditionalFormats.add('containsText',{text:'소표본',format:{fill:'#FFF2CE',font:{color:'#885C16'}}});
sheet.getRange(`N10:N${last}`).conditionalFormats.add('containsText',{text:'무표본',format:{fill:'#F0F2F4',font:{color:'#6B7280'}}});
sheet.freezePanes.freezeRows(9);sheet.freezePanes.freezeColumns(4);
raw.getRange('A6:M6').format={fill:'#345367',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',verticalAlignment:'center',rowHeight:43};
raw.getRange(`C7:L${6+records.length}`).setNumberFormat('#,##0');
raw.getRange(`C7:L${6+records.length}`).format.horizontalAlignment='right';
raw.freezePanes.freezeRows(6);raw.freezePanes.freezeColumns(3);
// Verify recalculation through a temporary count change, then restore it.
const original=raw.getRange('F8').values[0][0];
raw.getRange('F8').values=[[original+1]];wb.recalculate();
const changed=sheet.getRange('E11').values[0][0];
if(Math.abs(changed-(original+1)/records[1].leader_starts)>1e-12)throw Error('Formula recalculation failed');
raw.getRange('F8').values=[[original]];wb.recalculate();
const values=sheet.getRange(`A10:N${last}`).values;
let checked=0,blankRows=0;
const keys=['individual_top3_pct','individual_win_pct','any_top3_pct','one_top3_pct','two_plus_top3_pct','zero_top3_pct','group_win_pct','two_top3_pct','three_top3_pct'];
for(let i=0;i<records.length;i++){
 if(values[i][3]!==records[i].races)throw Error(`Count mismatch ${i}`);
 for(let k=0;k<keys.length;k++){
  const actual=values[i][4+k],expected=records[i][keys[k]];
  if(expected===null){if(actual!==''&&actual!==null)throw Error(`Expected blank ${i}`);}
  else if(typeof actual!=='number'||Math.abs(actual-expected/100)>1e-11)throw Error(`Rate mismatch ${i} ${keys[k]} ${actual}`);
  checked++;
 }
 if(records[i].races===0)blankRows++;
}
const inspect=await wb.inspect({kind:'table',range:'거리별 결과!A9:N16',include:'values,formulas',tableMaxRows:8,tableMaxCols:14,maxChars:6000});
await fs.writeFile(path.join(outputDir,'inspect.txt'),inspect.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'Formula error scan'});
await fs.writeFile(path.join(outputDir,'formula_scan.txt'),errors.ndjson);
for(const [s,range,file] of [[sheet,'A1:N17','results_preview.png'],[raw,'A1:M14','counts_preview.png']]){
 const blob=await wb.render({sheetName:s.name,range,scale:1,format:'png'});
 await fs.writeFile(path.join(outputDir,file),new Uint8Array(await blob.arrayBuffer()));
}
const xlsx=await SpreadsheetFile.exportXlsx(wb);
const target=path.join(outputDir,'선두묶음_거리별_입상우승.xlsx');await xlsx.save(target);
await fs.writeFile(path.join(outputDir,'workbook_verification.json'),JSON.stringify({status:'passed',output:target,result_rows:records.length,formula_rates_matched:checked,unobserved_rows_preserved_blank:blankRows,temporary_source_change_recalculated_and_restored:true,sheets_rendered:2},null,2)+'\n');
console.log(JSON.stringify({output:target,rows:records.length,rates:checked,blankRows}));

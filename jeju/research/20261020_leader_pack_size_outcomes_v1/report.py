"""Report exact pack-size outcomes with every requested distance combination."""
import json
import pandas as pd
from analysis import HERE,save,clean,DISTANCES
OUTPUT='outputs/20261020-leader-pack-size/선두묶음_거리별_입상우승.xlsx'
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows])
def pct(x):return '—' if pd.isna(x) else f'{x:.2f}%'
def main():
 v=json.loads((HERE/'verification01/verification.json').read_text());assert v['status']=='passed';assert json.loads((HERE/'outputs/20261020-leader-pack-size/saved_workbook_verification.json').read_text())['status']=='passed'
 rates=pd.read_csv(HERE/'run01/rates.csv',dtype={'period':str,'distance':str});main=rates[(rates.period=='all')&(rates.distance=='all')]
 def display(g,full=False):
  rows=[]
  for r in g.itertuples():
   row=[str(r.leader_count),str(r.races),pct(r.individual_top3_pct),pct(r.individual_win_pct),pct(r.group_win_pct),pct(r.zero_top3_pct),pct(r.one_top3_pct),pct(r.two_plus_top3_pct)]
   if full:row += [str(r.two_top3_races),str(r.three_top3_races)]
   rows.append(row)
  return table(['선두 두수','경주 수','말 입상률','말 우승률','그룹 우승','입상 0두','정확 1두 입상','2두 이상 입상']+(['정확2두 경주','정확3두 경주'] if full else []),rows)
 sections=[]
 for distance in DISTANCES:
  g=rates[(rates.period=='all')&(rates.distance==str(distance))];sections.append(f'## {distance}m\n\n'+display(g)+'\n')
 rows=[]
 for period in ['2024_2025','2026']:
  for r in rates[(rates.period==period)&(rates.distance=='all')].itertuples():rows.append([period.replace('_','~'),str(r.leader_count),str(r.races),pct(r.individual_top3_pct),pct(r.individual_win_pct),pct(r.one_top3_pct),pct(r.two_plus_top3_pct)])
 recent=table(['기간','선두 두수','경주 수','말 입상률','말 우승률','정확1두 입상','2두이상 입상'],rows)
 nonempty=rates[(rates.period=='all')&(rates.distance!='all')&rates.races.gt(0)].copy()
 nonempty.to_csv(HERE/'거리별_두수별_주요결과.csv',index=False,encoding='utf-8-sig')
 text=f'''# 선두 묶음 두수와 거리별 입상 우승 및 동반 입상

S1F 첫 묶음을정확히1~7두로나눠거리별입상·우승과그룹내동반입상을집계했다. **선두2두의경우전체2,148경주에서정확1두입상56.15%,2두모두입상22.49%,전부비입상21.37%**였다. 선두3두일때는정확1두47.13%,2두이상36.81%다. 그룹두수에따라한마리의입상률과그룹에서여러말이입상할가능성은다르게움직인다.

## 분모와 표본

2017-01-13~2026-09-19정상완주완전편성중S1F품질완전5,200경주·첫묶음10,384말출전이다. 현재8거리·400m/사용자제외말제외·2026부분연도의고정자료이며DB나최신10월경주로확장하지않았다. 첫묶음불명확6경주는앞선연구에서경주전체로제외했다. S1F는기본200m,1110/1610m는210m이며1300m는기존2C→S1F계약을유지했다. 실제앞쪽묶음과과거각질을혼합하지않는다.

| 지표 | 분모와 계산 |
|---|---|
| 말 입상률 | 그룹입상마수합계 ÷ 그룹말출전수 |
| 말 우승률 | 그룹우승마수합계 ÷ 그룹말출전수 |
| 그룹 우승 | 해당그룹에서우승마가나온경주수 ÷ 해당조건경주수 |
| 정확1두 입상 | 그룹중정확히1두만1~3착한경주수 ÷ 해당조건경주수 |
| 2두 이상 입상 | 그룹중2두또는3두가1~3착한경주수 ÷ 해당조건경주수 |
| 입상0두 | 해당그룹에서1~3착말이없던경주수 ÷ 해당조건경주수 |

입상은최종1~3착이다. 따라서그룹이4~7두라도한경주입상마는최대3두다. **0두·정확1두·2두이상은서로배타적이며합계100%**다. ‘정확1두’는‘최소1두’와다르다. 그룹우승률은말우승률×선두두수이며,더많은말을묶은그룹우승률을말한마리의우승률과동일시하지않는다.

## 전체 기간

{display(main,True)}

선두2두의원수치는0두459경주·정확1두1,206경주·2두모두483경주다. 말입상수는1,206+2×483=2,172두,그룹말출전수4,296회이므로말입상률50.56%가된다. 그룹우승은956/2,148=44.51%,말우승은956/4,296=22.25%로다르다.

선두3두의2두이상346경주는정확2두306경주와정확3두40경주의합계다. 선두4두의2두이상136경주는정확2두108·정확3두28경주다. 선두6두10경주·7두1경주는특히소표본이며7두그룹우승100%는단한경주에서나온비율이다.

## 거리별 결과

아래표는해당거리·정확한선두두수조건의경주를분모로한다. 말입상/우승만분모가말출전수다. 관측경주가없는조합은경주수0·비율—로보존했다.100말출전또는30경주또는20경주일미만은소표본이며엑셀의표본상태열에표시했다. 숫자가큰비율도작은분모에서는일반확률로사용하지않는다.

{chr(10).join(sections)}
800m선두2두는2두모두입상34.75%였고,900m24.46%,1000m19.41%,1110m12.99%,1200m15.15%였다. 이는원시관측이며편성능력·그룹구성·게이트·전략차이가남는다. 1300/1400/1610m및선두5~7두의많은거리셀은작아서거리별고정효과로채택하지않는다.

## 최근 기간 전체 거리

{recent}

최근기간×거리×두수도엑셀/CSV전체표에보존했다.2026년거리별/큰묶음표본은더작으며전체기간결과를독립검증한표본은아니다.

## 엑셀과 경주별 원장

**[거리별 두수별 입상 우승 엑셀]({OUTPUT})**은‘거리별결과’에서기간·거리·두수를필터링할수있다. 말입상/우승,최소1두,정확1두,2두이상,0두,그룹우승,정확2두/3두를모두표시한다.‘집계원수치’의분자·분모를직접참조하는수식으로계산했고미관측조합의비율은빈칸으로유지했다.

[전체189셀 CSV](run01/rates.csv) · [전체기간 거리별 주요결과](거리별_두수별_주요결과.csv) · [5,200경주별 첫 묶음 입상수와 원문](run01/race_outcomes.csv). 원문안의마번순서는개별선두순위를뜻하지않는다.

## 검산과 한계

[계획](PLAN.md)과[입력해시](source_manifest.json)를보존했다. 말별첫묶음파일에서5,200경주의N/K/W를독립재집계했고메모리SQL로189셀·27분할합계를검산했다. 정확입상수합계·가중입상마수·우승마수·확률합계및말/경주분모관계를확인했다. [검증](verification01/verification.json)은통과다. 엑셀1,701비율수식과저장캐시를독립수치와대조하고입력변경후재계산·복원·두시트미리보기를확인했다.

실제S1F위치와정상완주선택에조건부인후향기술통계다. 묶음크기만으로경합강도·빠른페이스·편안한선행을확정하지않으며같은능력말을그룹에넣는원인효과도아니다. 사전예측성능·개별미래확률·고정가산·운영반영은채택하지않았다. DB개방/쓰기·외부수집없음.
'''
 assert not (HERE/'README.md').exists();(HERE/'README.md').write_text(text)
 save(HERE/'decision.json',{'status':'exact_leader_pack_size_distance_group_outcomes_completed','source_start':'2017-01-13','source_end':'2026-09-19','partial_2026':True,'primary_point':'s1f','source_races':5200,'leader_starts':10384,'exact_size_min':1,'exact_size_max':7,'aggregate_cells':len(rates),'nonempty_whole_period_distance_cells':len(nonempty),'overall_rates':clean(main),'individual_and_group_denominators_separated':True,'exclusive_zero_one_two_plus_reported':True,'same_ability_causal_effect_identified':False,'database_opened':False,'operationally_applied':False,'workbook':OUTPUT});print('Detailed report saved',len(nonempty),'nonempty distance-size cells',flush=True)
if __name__=='__main__':main()

"""Render verified solo-leader rates with a one-row-per-solo-race export."""
import json
import pandas as pd
from analysis import HERE,save,clean,DISTANCES
LABELS={'solo':'첫 묶음 1두','pair':'첫 묶음 2두','three_plus':'첫 묶음 3두 이상','shared':'첫 묶음 2두 이상 합계'}
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows])
def main():
 v=json.loads((HERE/'verification01/verification.json').read_text());assert v['status']=='passed'
 rates=pd.read_csv(HERE/'run01/rates.csv',dtype={'distance':str,'period':str});solo=pd.read_csv(HERE/'run01/solo_starts.csv',dtype={'horse_id':str});main=rates[(rates.point=='s1f')&(rates.period=='all')&(rates.distance=='all')];one=main[main.category.eq('solo')].iloc[0];assert (one.starts,one.races,one.top3,one.wins)==(1761,1761,1104,612)
 rows=[]
 for r in main.itertuples():rows.append([LABELS[r.category],f'{r.races:,}',f'{r.starts:,}',f'{r.top3:,}/{r.starts:,} · {r.top3_rate_pp:.2f}%',f'{r.wins:,}/{r.starts:,} · {r.win_rate_pp:.2f}%'])
 size_table=table(['첫 묶음 크기','경주','그룹 말 출전','입상/출전 · 입상률','우승/출전 · 우승률'],rows)
 def distance_table(period):
  rows=[]
  for distance in DISTANCES:
   r=rates[(rates.point=='s1f')&(rates.period==period)&(rates.distance==str(distance))&(rates.category=='solo')].iloc[0];rows.append([f'{distance}m',str(r.starts),f'{r.top3}/{r.starts} · {r.top3_rate_pp:.2f}%',f'{r.wins}/{r.starts} · {r.win_rate_pp:.2f}%','소표본' if r.low_support else '기준 충족'])
  return table(['거리','단독 관측 경주','입상','우승','기술표본 기준'],rows)
 rows=[]
 for period in ['2024_2025','2026']:
  r=rates[(rates.point=='s1f')&(rates.period==period)&(rates.distance=='all')&(rates.category=='solo')].iloc[0];rows.append([period.replace('_','~'),str(r.starts),f'{r.top3}/{r.starts} · {r.top3_rate_pp:.2f}%',f'{r.wins}/{r.starts} · {r.win_rate_pp:.2f}%',f'{r.top3_date_low:.2f}~{r.top3_date_high:.2f}%'])
 recent_table=table(['기간','단독 관측 경주','입상','우승','입상률 날짜95%'],rows)
 rows=[]
 for r in rates[(rates.point=='c4')&(rates.period=='all')&(rates.distance=='all')].itertuples():rows.append([LABELS[r.category],str(r.starts),f'{r.top3_rate_pp:.2f}%',f'{r.win_rate_pp:.2f}%'])
 c4_table=table(['4C 첫 묶음 크기','말 출전','입상률','우승률'],rows)
 export=solo[solo.point.eq('s1f')][['race_id','race_date','race_number','race_distance_m','field_n','horse_id','horse_name','horse_number','finish_position','top3','group_value']].copy();assert len(export)==1761 and export.race_id.nunique()==1761 and export.top3.sum()==1104 and export.finish_position.eq(1).sum()==612
 export=export.rename(columns={'race_id':'경주ID','race_date':'경주일','race_number':'경주번호','race_distance_m':'거리m','field_n':'출전두수','horse_id':'말ID','horse_name':'마명','horse_number':'마번','finish_position':'최종착순','top3':'입상','group_value':'S1F통과조원문'});export.to_csv(HERE/'경주별_S1F_단독선행.csv',index=False,encoding='utf-8-sig')
 text=f'''# 첫 통과조가 한 마리인 단독 선행의 입상률

S1F 첫 통과조 묶음이 정확히1두인 **1,761경주에서 그 말의 입상률은62.69%(1,104/1,761), 우승률은34.75%(612/1,761)**였다. 첫 묶음에 여러 말이 있던 경우의 말 한 마리당 입상률45.26%보다 높게 관측됐다. 단독선행에 배치하는 원인효과를 추정한 결과는 아니다.

## 단독 선행의 의미와 표본

그 경주의S1F통과조에서첫묶음이한마리인경우다. 예를들어 `1-(2,3)-(4,5),6`이면1번말을S1F단독선행으로본다. `(1,2)-(3,4),5,6`에서는첫묶음2두이고그중1두를임의로단독선행으로고르지않는다. 이는예시표기다.

그지점에서앞에별도말묶음이없는한마리라는뜻이며,직후추격마와의정확한거리·편안함·경합부재·경주내내선행은이표기만으로확정하지않는다.1110·1610mS1F는출발후210m이고1300m는기존계약인2C→S1F순서를유지한다.

앞선[실제통과조연구](../20261020_actual_pack_top3_v1/README.md)의2017-01-13~2026-09-19정상완주완전편성중S1F품질완전5,200경주·52,095출전을사용했다.400m/사용자제외말은제외됐고2026년은9월19일까지다. 이중첫묶음은10,384말출전이며첫묶음1두인경주가1,761개(33.87%)다. 현재DB·10월경주로확장하지않았다.

## 첫 묶음 크기별 비교

입상은최종1~3착이다. 아래는모두첫묶음에속한말의한번출전당입상/우승비율이다. 첫묶음2두가있으면2출전으로세므로말출전수와경주수는다르다.

{size_table}

단독관측62.69%의날짜군집95%는{one.top3_date_low:.2f}~{one.top3_date_high:.2f}%, 말군집95%는{one.top3_horse_low:.2f}~{one.top3_horse_high:.2f}%다. 이설명구간은단독관측그룹의비율불확실성이며,능력등을고려한단독선행효과의구간은아니다.

첫묶음2두이상합계는8,623출전·3,439경주다. 단독과의원시입상률차이약17.43%p에는능력·기수전략·게이트·거리·경합등의차이가함께포함돼있다. 비교군의‘그룹에서최소1두입상’확률을단독말한마리의비율과섞지않았다. 앞선첫묶음전체48.22%는이표의1두/2두/3두이상분자를합친결과다.

## 거리별 단독 선행 관측

{distance_table('all')}

800m단독관측의입상률78.64%,우승률48.30%가높게관측됐다.1000m는입상61.49%·우승33.54%,1110m는49.72%·22.88%다.1300m20경주·1400m38경주·1610m4경주는소표본이며1610m50%를안정적인확률로사용하지않는다. 표본기준은100출전·30경주·20경주일이며충족이원인효과나미래성능의검증을뜻하지않는다.

## 최근 기간

{recent_table}

2026년은단독관측157경주에서102두입상(64.97%)·47두우승(29.94%)이었다. 같은2026년첫묶음2두이상은808말출전의입상42.45%·우승15.97%다. 모든기간은이미사용한자료의후향관측이고새독립검증은아니다.

{distance_table('2026')}

2026거리별단독표본은1~53경주로작다.800m의0/1,1300m의6/7,1200m의16/20등을일반확률로채택하지않는다.

## 4C 보충

{c4_table}

4C는별도의더늦은관측단면이다. 단독선행시점과유효경주분모가다르므로S1F와의차이를전개이동효과로해석하지않는다.

## 경주별 자료와 검산

[경주별 S1F 단독선행 CSV](경주별_S1F_단독선행.csv)는1,761경주의원문·단독말ID/마명/마번·최종착순을한줄씩제공한다. [모든 첫 묶음 말](run01/leaders.csv),[S1F/4C단독관측](run01/solo_starts.csv),[기간·거리·묶음크기별 전체표](run01/rates.csv)도보존했다.

[검증](verification01/verification.json)은통과다. 원문첫토큰의숫자명단을별도로읽어{v['first_pack_tokens_and_rosters_recomputed']:,}경주지점의첫묶음크기/명단과{v['leader_rows_matched']:,}말출전을확인했다. 별도SQL의{v['SQL_cells_and_cluster_intervals']}비율셀·군집구간과{v['partitions_match_parent_cells']}분할셀의합계를원연구첫묶음전체와대조했다. 입력해시·바이트는유지했다. [계획](PLAN.md)·[원천해시](source_manifest.json)를함께보관한다.

실제로단독선행을했던말의사후관측비율이다. 과거선행형의사전입상확률이나선행예측적중률과다르며정상완주선택·미관측능력/전략·게시시각의한계가남는다. 고정가산·개별미래확률·인과효과·운영반영은채택하지않았다. DB개방/쓰기·외부수집없음.
'''
 assert not (HERE/'README.md').exists();(HERE/'README.md').write_text(text)
 save(HERE/'decision.json',{'status':'solo_first_pack_top3_descriptive_comparison_completed','source_start':'2017-01-13','source_end':'2026-09-19','partial_2026':True,'primary_point':'s1f','definition':'first observed passing pack contains exactly one horse','solo_races':1761,'solo_top3':1104,'solo_wins':612,'primary_rates':clean(main),'solo_per_race_export_rows':len(export),'same_ability_causal_effect_identified':False,'database_opened':False,'operationally_applied':False});print('Solo leader report and race export saved',flush=True)
if __name__=='__main__':main()

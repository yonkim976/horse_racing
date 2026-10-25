"""Report observed pack membership, keeping runner and race denominators distinct."""
import json
import pandas as pd
from analysis import HERE,save,clean,DISTANCES
LABELS={0:'선두 묶음',1:'두 번째 묶음',2:'세 번째 이후 뒤쪽'}
def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows])
def main():
 v=json.loads((HERE/'verification01/verification.json').read_text());assert v['status']=='passed'
 rates=pd.read_csv(HERE/'run01/rates.csv',dtype={'period':str,'distance':str});rr=pd.read_csv(HERE/'run01/race_groups.csv');coverage=pd.read_csv(HERE/'run01/coverage.csv',dtype={'period':str,'distance':str})
 main=rates[(rates.point=='s1f')&(rates.period=='all')&(rates.distance=='all')].sort_values('group_code');assert main.starts.sum()==52095 and main.top3.sum()==15600
 rows=[]
 for r in main.itertuples():rows.append([LABELS[r.group_code],f'{r.top3:,}/{r.starts:,}',f'{r.rate_pp:.2f}%',f'{r.date_low:.2f}~{r.date_high:.2f}%',f'{r.mean_group_size:.2f}두',f'{r.top3_share_pp:.2f}%'])
 main_table=table(['실제 S1F 위치','입상/그룹 출전','출전당 입상률','날짜95%','경주당 평균 두수','전체 입상마 중 비율'],rows)
 def dist_table(period):
  rows=[]
  for distance in DISTANCES:
   z=rates[(rates.point=='s1f')&(rates.period==period)&(rates.distance==str(distance))].sort_values('group_code');R=int(z.eligible_races.iloc[0]);row=[f'{distance}m',f'{R:,}']
   for r in z.itertuples():row.append(f'{r.rate_pp:.2f}% ({r.top3:,}/{r.starts:,})')
   rows.append(row)
  return table(['거리','유효 경주','선두 묶음','두 번째 묶음','뒤쪽'],rows)
 rows=[]
 for period in ['2024_2025','2026']:
  z=rates[(rates.point=='s1f')&(rates.period==period)&(rates.distance=='all')].sort_values('group_code');rows.append([period.replace('_','~'),str(z.eligible_races.iloc[0])]+[f'{r.rate_pp:.2f}% ({r.top3:,}/{r.starts:,})' for r in z.itertuples()])
 recent_table=table(['기간','유효 경주','선두 묶음','두 번째 묶음','뒤쪽'],rows)
 rows=[]
 for r in rates[(rates.point=='c4')&(rates.period=='all')&(rates.distance=='all')].sort_values('group_code').itertuples():rows.append([LABELS[r.group_code],f'{r.top3:,}/{r.starts:,}',f'{r.rate_pp:.2f}%'])
 c4_table=table(['4C 위치','입상/그룹 출전','출전당 입상률'],rows)
 rows=[]
 for r in main.itertuples():rows.append([LABELS[r.group_code],str(r.races_with_group),f'{r.race_any_top3_pp:.2f}%',f'{r.equal_race_mean_rate_pp:.2f}%'])
 race_table=table(['S1F 그룹','그룹 존재 경주','그룹에서 최소1두 입상한 경주 비율','경주별 그룹 입상률의 단순평균'],rows)
 s=rr[rr.point.eq('s1f')];keys=['race_id','race_date','race_number','race_distance_m','field_n','group_value'];per=s[keys].drop_duplicates('race_id').set_index('race_id')
 for code,name in [(0,'선두'),(1,'두번째'),(2,'뒤쪽')]:
  z=s[s.group_code.eq(code)].set_index('race_id')
  for field,korean in [('entries','두수'),('top3_count','입상수'),('winner_count','우승수'),('rate_pp','입상률')]:per[name+'_'+korean]=z[field]
 per=per.reset_index().rename(columns={'race_id':'경주ID','race_date':'경주일','race_number':'경주번호','race_distance_m':'거리m','field_n':'출전두수','group_value':'S1F통과조원문'})
 assert len(per)==5200 and (per[['선두_입상수','두번째_입상수','뒤쪽_입상수']].sum(axis=1)==3).all();per.to_csv(HERE/'경주별_초반3그룹.csv',index=False,encoding='utf-8-sig')
 text=f'''# 실제 통과조 세 그룹별 입상률

이번 비교는 과거 각질이 아니라 **그 경주 S1F에서 실제로 어느 묶음에 있었는지**를 기준으로 한다. 전체 출전당 Top3는 **선두 묶음48.22%, 두 번째 묶음35.64%, 세 번째 이후21.30%**였다. 거리별로는1400m를 제외한 원시 비율에서 선두 묶음이 가장 높았다. 실제 앞쪽 위치와 입상의 관찰 연관이며, 같은 능력의 말을 선행에 보내면 이만큼 확률이 오른다는 원인효과는 아니다.

## 세 그룹의 기준

S1F 통과조 원문의 첫 번째 묶음=선두, 두 번째 묶음=두 번째/선입 위치, 세 번째 이후 모든 묶음=뒤쪽으로 나눴다. 괄호 안에 여러 말이 있으면 모두 같은 묶음이며 내부 순서는 개별 착순으로 만들지 않았다. 예를 들어 `(1,2)-(3,4)-(5,6),7,8`이라면선두1·2번,두번째3·4번,뒤쪽5·6·7·8번이다. 이는 분류 설명을 위한 예시다.

두 번째 묶음이 전통적 선입이나 물리적 레일2선을 항상 뜻하지 않는다. 뒤쪽도 추입 위치에 해당할 뿐 추입형·추입 성공을 확정하지 않는다. 이 연구에서는 ‘뒤쪽’으로 표시한다.

주지점은S1F다.1110·1610m의S1F는출발후210m이며그외기본설명은200m다.1300m는기존사용자계약인출발→2C→S1F순서에따라해석한다. 따라서다른거리와완전히동일한코스상지점을관측했다고가정하지않는다. 보충4C는별도표로구분했다.

## 기간과 표본

고정된2017-01-13~2026-09-19 정상완주 완전편성52,155출전·5,206경주·2,813두의 CSV와 품질 통과조 감사표를 사용했다.400m와사용자제외말은제외했고현재8거리를유지했다.2026년은9월19일까지이며최신10월경주를추가한집계가아니다.

S1F가불명확한6경주·60출전을경주전체로제외해 **5,200경주·52,095출전**을비교했다. 통과조를일부만알때모르는말을뒤쪽으로채우지않았다.4C는5경주·48출전제외로5,201경주·52,107출전이다. 제외경주와사유는 [경주별 가용 원장](run01/race_census.csv),기간·거리별분모는 [범위 표](run01/coverage.csv)에있다.

## 전체 입상률과 입상마 구성비

입상은 최종1~3착이다. **출전당 입상률=해당 그룹의 입상마 수/해당 그룹 말의 출전 수**이며 표의 주비교다. 전체입상마중비율은분모가전체입상15,600두인별도지표다.

{main_table}

선두는그룹말한번출전당약48%로가장높다. 반면입상마전체에서뒤쪽출신은40.69%로가장많다. 뒤쪽그룹은평균약5.7두로선두약2두보다크기때문이다. **‘입상마 중 뒤쪽 출신이 많음’과‘뒤쪽 말 한 마리의 입상률이 높음’은 다른 계산이다.**

## 거리별 초반 실제 위치

괄호는입상수/그룹출전수다. 같은거리에출전한각그룹의원시비율이며말의능력·게이트·전략등을조정한결과가아니다.

{dist_table('all')}

800m에서는61.10%→40.29%→16.46%로차이가크다.1000m에서도44.92%→33.84%→22.25%로앞쪽순서가높다.1110·1200m는뒤쪽입상률이각24.15%·26.02%로800m보다높지만선두보다낮다.1400m는두번째36.21%가선두34.38%보다조금높으며88경주다.1610m는9경주·각그룹16/19/49출전으로소표본이라순서를일반화하지않는다.1300m63경주·1400m88경주도큰거리보다지원이작다.

## 최근 기간과 거리

{recent_table}

2026년전체도선두46.11%→두번째37.35%→뒤쪽23.39%다. 최근에뒤쪽입상률이전체기간보다높다는기술차이는거리·두수·출전마구성변화가포함돼있으며시대효과로분리한결과가아니다.

{dist_table('2026')}

2026년800m3경주·1300m20경주·1400m14경주·1610m6경주는소표본이다. 특히800m의두번째50%대선두40%는각8/5출전에기댄비율이므로전체기간의단거리결론을뒤집는근거로쓰지않는다.

## 경주 단위 계산과 경주별 자료

{race_table}

한경주에서최소1두입상하는사건은세그룹이동시에충족할수있어비율합계가100%가아니다. 그룹이존재하는경주만분모로삼았다. 그룹두수가많으면최소1두입상가능성도커지므로말한마리의비교에는앞선출전당비율을사용한다. 경주별비율의단순평균과전체말출전을합친비율도따로보존했다.

**[경주별 초반3그룹 CSV](경주별_초반3그룹.csv)**는5,200경주한줄씩원문·거리·전체두수·세그룹두수/입상수/우승수/입상률을제공한다. 각경주의세그룹입상수합계는항상3이다. [묶음별 경주 상세](run01/race_groups.csv)에는S1F/4C각3행과그룹마번·입상마번이있고,[말별 실제 그룹](run01/runner_groups.csv)에는말ID·마명·최종착순이있다. 마번나열은그룹내개별위치순위를뜻하지않는다. 없는그룹의두수는0이고입상률은결측으로유지했다.

## 4C 보충

{c4_table}

4C단면도앞쪽이높았다. 다만측정시점과유효경주가S1F와다르므로48.22%에서54.30%로의차이를전진시키는효과로해석하지않는다.4C는더많은경주진행정보를포함한사후위치다.

## 검산과 적용 범위

[사전계획](PLAN.md)과[원천해시](source_manifest.json)를보존했다. 기존보수파서와독립상태기계파서를대조해{v['valid_pack_strings_independently_parsed']:,}개원문·{v['runner_group_assignments_recomputed']:,}말별그룹·{v['race_group_rows_recomputed']:,}경주그룹행을검산했다. 별도메모리SQL의{v['SQL_raw_cells_and_cluster_intervals']}집계셀·날짜/말군집t95%와{v['coverage_rows_recomputed']}분모행,각경주입상3두/우승1두및입상마구성비합계100%를확인했다. [검증](verification01/verification.json)은통과다.

[입상률·우승률·구간 전체](run01/rates.csv). 개별군집구간은설명구간이며새사전예측성능검증이아니다. 실제초반위치에는말의능력·기수전략·게이트등이함께반영되고정상완주/완전편성을사후선택했다. 이관찰값을과거각질별사전확률이나선행전환의인과보정치로쓰지않는다. DB개방/쓰기·외부수집·운영반영없음. 앞선[과거 각질별 비교](../20261020_style_top3_comparison_v1/README.md)는다른질문의결과로보존한다.
'''
 assert not (HERE/'README.md').exists();(HERE/'README.md').write_text(text)
 save(HERE/'decision.json',{'status':'actual_passing_pack_top3_descriptive_comparison_completed','source_start':'2017-01-13','source_end':'2026-09-19','partial_2026':True,'primary_point':'s1f','group_definition':'first passing pack / second passing pack / third and later packs','eligible_races':5200,'eligible_starts':52095,'excluded_races':6,'primary_rates':clean(main),'race_level_export_rows':len(per),'past_horse_style_used_as_group':False,'causal_effect_identified':False,'future_prediction_tested':False,'database_opened':False,'operationally_applied':False})
 print('Observed pack report and per-race table saved',len(per),'races',flush=True)
if __name__=='__main__':main()

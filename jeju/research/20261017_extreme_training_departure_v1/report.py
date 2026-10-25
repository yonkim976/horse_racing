"""Render a Korean report directly from verified contrast and support tables."""
import json
import pandas as pd
from data import HERE,save
NAMES={'days_group':'조교 일수','minutes_group':'누적 시간','daily_minutes_group':'관측일당 시간','combo_group':'일수와 시간 동시'}
LABELS={'big_decrease':'크게 감소','big_increase':'크게 증가','moderate_decrease':'보통 감소','moderate_increase':'보통 증가','usual':'평소 범위','extreme_decrease':'초극단 감소','extreme_increase':'초극단 증가','other':'그 밖의 조합'}
def ci(r):return f'{r.effect:+.3f} ({r.date_low:+.3f}~{r.date_high:+.3f})'
def markdown(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows])
def main():
 out=HERE/'report01';out.mkdir(exist_ok=False);v=json.loads((HERE/'verification01/verification.json').read_text());assert v['status']=='passed'
 hold_verification=json.loads((HERE/'verification01/held_identifiability.json').read_text());assert hold_verification['status']=='passed'
 ef=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str});raw=pd.read_csv(HERE/'analysis01/raw_primary.csv',dtype={'period':str});support=pd.read_csv(HERE/'verification01/support.csv',dtype={'period':str});models=json.loads((HERE/'analysis01/models.json').read_text());d=json.loads((HERE/'decision.json').read_text())
 assert not ef.direction_supported.any()
 rows=[]
 for field in ['days_group','minutes_group']:
  for label in ['big_decrease','usual','big_increase']:
   a=raw[raw.model.eq('joint')&raw.period.eq('all')&raw.field.eq(field)&raw.group.eq(label)].iloc[0];b=raw[raw.model.eq('joint')&raw.period.eq('2026')&raw.field.eq(field)&raw.group.eq(label)].iloc[0]
   rows.append([NAMES[field],LABELS[label],f'{a.starts:,}',f'{a.top3_pp_mean:.2f}%',f'{b.starts:,}',f'{b.top3_pp_mean:.2f}%'])
 rawtable=markdown(['기준','그룹','전체 출전','전체 Top3','2026 출전','2026 Top3'],rows)
 rows=[];recent=[]
 for period in ['all','2024_2025','2026']:
  for field in ['days_group','minutes_group']:
   for label in ['big_decrease','big_increase']:
    z=ef[ef.family.eq('primary')&ef.period.eq(period)&ef.field.eq(field)&ef.positive_group.eq(label)];a=z[z.target.eq('relative_time')].iloc[0];b=z[z.target.eq('top3_pp')].iloc[0]
    row=[NAMES[field]+' '+LABELS[label],ci(a),ci(b)]
    if period=='all':rows.append(row)
    else:recent.append([period]+row)
 effecttable=markdown(['평소 범위 대비','조정 빠름 초 (날짜95%)','조정 Top3 %p (날짜95%)'],rows)
 recenttable=markdown(['기간','평소 범위 대비','조정 빠름 초 (날짜95%)','조정 Top3 %p (날짜95%)'],recent)
 rows=[]
 for field in ['days_group','minutes_group']:
  for label in ['extreme_decrease','extreme_increase']:
   rr=raw[raw.period.eq('all')&raw.model.eq('ultra')&raw.field.eq(field)&raw.group.eq(label)].iloc[0];er=ef[ef.period.eq('all')&ef.model.eq('ultra')&ef.field.eq(field)&ef.positive_group.eq(label)&ef.target.eq('relative_time')].iloc[0]
   rows.append([NAMES[field],LABELS[label],f'{rr.starts:,}',f'{rr.top3_pp_mean:.2f}%',ci(er)])
 ultratable=markdown(['기준','구간','출전','원시 Top3','조정 빠름 초 (날짜95%)'],rows)
 rows=[]
 for r in ef[ef.family.eq('gradient')&ef.period.eq('all')&ef.target.eq('relative_time')].itertuples():rows.append([NAMES[r.field],LABELS[r.positive_group]+' 대 '+LABELS[r.reference_group],ci(r)])
 gradienttable=markdown(['기준','직접 비교','조정 빠름 초 (날짜95%)'],rows)
 exploratory=ef[((ef.date_low>0)&(ef.horse_low>0))|((ef.date_high<0)&(ef.horse_high<0))]
 assert len(exploratory)==5 and exploratory.family.eq('sensitivity').all()
 rows=[]
 for r in exploratory.itertuples():rows.append([r.model+'/'+r.variant,NAMES[r.field]+' '+LABELS[r.positive_group],r.target,ci(r)])
 exploratorytable=markdown(['모형과 민감도','평소 범위 대비','목표','차이 (날짜95%)'],rows)
 held=support[~support.support|support.status.ne('fitted')]
 held.to_csv(out/'held_comparisons.csv',index=False,encoding='utf-8-sig')
 h=raw[raw.period.eq('2026')&raw.model.eq('ultra')&raw.group.str.startswith('extreme')][['field','group','starts','horses']]
 hr=[]
 for field in ['days_group','minutes_group']:
  for label in ['extreme_decrease','extreme_increase']:
   z=h[h.field.eq(field)&h.group.eq(label)];hr.append([NAMES[field]+' '+LABELS[label],int(z.iloc[0].starts) if len(z) else 0,int(z.iloc[0].horses) if len(z) else 0])
 heldtable=markdown(['2026 초극단 구간','출전','말 수'],hr)
 combo=[]
 for r in ef[ef.model.eq('combo')&ef.period.eq('all')&ef.target.eq('relative_time')].itertuples():combo.append([LABELS[r.positive_group],f'{r.positive_starts:,}',ci(r)])
 combotable=markdown(['일수와 누적 시간이 모두','출전','둘 다 평소 대비 빠름 초 (날짜95%)'],combo)
 text=f'''# 말별 평소 조교량의 큰 증감과 성적 변화

크게 늘거나 줄어든 경우도 주모형에서 안정적인 조정 성적 차이를 확인하지 못했다. 다만 **조교 일수가 크게 줄어든 경우 기록 악화 신호가 일부 민감도에서 관측됐다.** 따라서 큰 증감도 영향이 없다고 확정하지 않는다. 기록 악화의 일정한 크기, 원인효과, 최근 기간의 반복은 아직 확보하지 못했다.

## 비교 기준과 표본

앞선 [개인 평소량 연구](../20261017_personal_training_departure_v1/README.md)의 고정 입력을 사용했다. 2017-01-13~2026-09-19 원천52,155출전·5,206경주·2,813두, 현재8거리·원천7~13두 정상완주완전편성 결과다. 분석가능 표본은 2017-02-03부터45,021출전·2,279두이며, 2024~2025년11,280출전·2026년4,116출전이다. 2026년은부분연도다. 현재조교미관측134와평소이력부족7,000은0으로채우지않고구분했다. 400m·사용자제외말은 결과표본에 편입하지 않았다.

현재 준비는 D−14~D−2 중 직전 실제 출전일 다음 날 이후다. 평소는 T−2까지 완료한 최근730일 최대5회 준비의 중앙값(최소3회)이며 현재/미래 준비·성적을 제외했다. 정상완주 결과선정 밖 실제출전 준비도 평소에 포함했다. 일수는 관측날짜수, 시간은 유효 입퇴장기간 합계다. 무원행/시간미제공은 실제0조교로 해석하지 않으며 하루 실제운동횟수·강도·속도·거리는 측정하지 못한다.

사전 [계획](PLAN.md)에 따라 큰변화는 **일수±4일 이상·누적시간50% 이상 감소/증가**로 정했다. 평소범위는 일수차이−2일초과~+2일미만, 시간비율0.75초과~1.25미만이다. 중간변화도 별도범주로 모형에 포함했다. 초극단은 일수±6일이상, 시간75%이상감소/2배이상증가다. [경주별 주분류](input01/primary_groups.csv)와 [분모 원장](input01/denominator_census.json)을 보존했다.

## 원시 입상률

Top3는 최종1~3착 비율이다. 아래 차이는 능력·편성·간격 등을 조정하기 전이다.

{rawtable}

일수 크게감소/증가 그룹은 평균 출전간격17.29/53.60일, 준비창의 사용가능날짜8.56/12.99일이었다. 시간 크게감소/증가 그룹의 평균 출전간격도17.96/50.25일이다. 그룹의 평소량·과거수행 등도 달라서 원시성적을 조교증감의 효과로 대입하지 않는다. 2026 시간 크게감소117출전의 원시44.44% 역시 조정 성적 향상을 뜻하지 않는다.

## 말의 능력과 편성 등을 고려한 결과

같은경주 효과와 말×정확거리×기수짝 효과를 고려하고 과거기록·착순, 직전성적, 실제출전간격, 부담중량, 체중, 게이트, 조교사, 평소량/이력수 및 현재/평소 준비가능날짜를 함께 사용했다. 비교범주는무벌점, 표준화한나머지변수는ridge1이다. 같은경주 효과는 공통경주조건을 고려하며 미관측 건강·관리선택까지 제거했다는 뜻은 아니다.

주모형은 일수와 누적시간의5범주를 함께 넣은 조건부 비교다. 같은짝에서 양쪽을 관측한 교차말20두, 각그룹100출전·30두·20경주일, 식별·잔여자유도>20을 요구했다. 날짜군집과 말군집의 t95%는 각각 계산했고 두 구간과 날짜BH를 함께 본다. 기록차이 **양수는 편성대비 빠름, 음수는 느림**이다.

{effecttable}

위 주비교는 기록·Top3·10두환산착순에서 날짜와말구간이모두0을포함했다. 큰증가의원시입상률저하나큰감소의높은원시입상률을고정가감으로옮길근거는없다. 크게변한것이보통변화와다른지도직접비교했다.

{gradienttable}

주평소대비72검정, 큰변화대중간변화36검정, 기존H1기대초과최근16검정은 각각BH가족으로 보았고 지원은모두0개다. 가족 전체의 미지원은 효과가정확히0이거나 개별마에차이가없다는 증명이 아니다.

## 최근 기간

{recenttable}

최근 기간은 구간이 넓고 방향도 달라진다. 예를 들어 시간 크게감소의 조정기록은2024~2025년에+0.303초,2026년에−0.009초다. 최근두기간에서같은방향의지원이반복된비교는0개다. 과거에 이미 사용한 기간의 후향분석이며 새 독립검증은 아니다.

## 더 극단적인 변화와 동시 변화

{ultratable}

전체기간 초극단4구간도 기록·착순·입상률에서 안정적지원은 없었다. 2026초극단모형은관측된11개범주항중독립변화10개로전체가식별되지않아효과를보류했다. 표본수만충족한일부대비도전체조건부모형식별과는별개다. 실제2026표본은다음과같다.

{heldtable}

{combotable}

일수·시간 모두큰감소는 느림방향이고 날짜구간상한이0에가깝지만0을포함하며, 이를확정감점으로채택하지않는다. 2026모두큰감소49출전/모두큰증가87출전은사전100출전지원기준미달로보류했다. 관측일당시간50%이상감소는전체147출전·최근23/16출전으로자료가특히작다. 관측일당시간과동시변화·초극단의지원보충검정은같은BH가족({v['BH_tests_by_family']['secondary']}개)이며방향지원0개였다.

## 일부 민감도에서 남은 기록 악화 신호

7/28일창, 최근10회(최소5)평소값, 준비가능일당비율, 현재절대량추가, 말거리효과와기수주효과,90일이하간격, 평소4일·60분이상, 일수/시간단독을 보존했다. 아래5개효과는 개별 날짜/말95%가같은방향으로0을벗어난탐색결과다. 민감도전체에다중검정지원을부여한결론은아니다.

{exploratorytable}

`relative_time`은양수빠름초, `rank10_quality`는양수10두환산착순개선이다. 즉 일수큰감소의 일부비교에서약0.13~0.21초느린방향이보였다. 주모형에서시간증감까지함께고려하면−0.105초(−0.233~+0.024)로불확실하다. 여러민감도·최근기간에서같은확정차이가유지되지않아 **큰감소를무조건무해하다고도, 일정하게나쁘다고도확정할수없다.**

## 검산과 보존

[검증](verification01/verification.json)은통과했다. 앞선불변입력의준비창170,142행/평소기준312,930행SQL검증을재사용하고, 이번새경계38개·주분류45,021행을독립조건문으로확인했다. {v['support_cells_recomputed']}지원셀·{v['raw_cells_and_intervals_recomputed']}원시셀과구간·{v['effects_and_cluster_covariances_recomputed']}효과와공분산을독립union-find고정효과/Schur정규방정식으로검산했다. 최대계수차이{v['maximum_beta_difference']:.3g}, 최대공분산차이{v['maximum_covariance_difference']:.3g}다.

[효과 전체](analysis01/effects.csv) · [모형 원장](analysis01/models.json) · [지원 전체](verification01/support.csv) · [보류 구간](report01/held_comparisons.csv) · [원시 전체](analysis01/raw_primary.csv) · [일수와 시간의 교차 표본](analysis01/joint_group_counts.csv) · [최근 반복](analysis01/repeat_checks.csv) · [입력 해시](input01/source_manifest.json) · [판정](decision.json).

최근 공유DB에는별도승인된기승자종류보완609행이있으나이번고정CSV와원조교날짜/시간은보존됐다. 종류로조교량을선별하지않는다. [게시시점 원천 변경](PUBLICATION_PROVENANCE.md)에근거를분리한다. 이번연구는DB개방/쓰기·외부수집·운영모델변경을하지않았다. 정상완주/조교관측선택, 건강·승부선택·강도·게시시각미관측과과거반복분석의한계를유지한다. 말별최적량·컨디션진단·원인효과·새예측증분·고정가산을확정하지않았고기수/각질추후재개상태도유지했다.
'''
 assert not __import__('re').search('[\u3040-\u30ff]',text)
 assert not (HERE/'README.md').exists();(HERE/'README.md').write_text(text)
 def records(frame):return frame.astype(object).where(pd.notna(frame),None).to_dict('records')
 save(out/'summary.json',{'primary_large_changes':records(ef[ef.family.eq('primary')&ef.positive_group.str.startswith('big')]),'primary_raw_groups':records(raw[raw.model.eq('joint')]),'pointwise_sensitivity_signals':records(exploratory),'decision':d})
 save(out/'verification.json',{'status':'passed','primary_large_effect_rows':int((ef.family.eq('primary')&ef.positive_group.str.startswith('big')).sum()),'pointwise_sensitivity_rows':len(exploratory),'held_support_rows':len(held),'readme_bytes':(HERE/'README.md').stat().st_size})
 print('Report rendered from verified effects',flush=True)
if __name__=='__main__':main()

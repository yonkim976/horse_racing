"""Publish frozen results and explicit all-runner/gate-side scope in Korean."""
import os,json
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/bilateral_field_pace_mpl')
import numpy as np,pandas as pd,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import experiment as e
H=e.H;O=e.O;F=H/'figures';LABELS=['선행','선입','중단','후미'];NAMES={'oldF':'이전 F·교체표식 포함','N':'기수 완전 제외 기준','A':'전원 구성 확장','B':'안쪽·바깥쪽 구분 추가'}
font_manager.fontManager.addfont('/System/Library/Fonts/AppleSDGothicNeo.ttc');plt.rcParams.update({'font.family':'Apple SD Gothic Neo','axes.unicode_minus':False,'font.size':11,'figure.dpi':130})
def table(df):
 def fmt(v):
  if isinstance(v,(float,np.floating)):
   if not np.isfinite(v):return '미관측'
   if float(v).is_integer():return str(int(v))
   return f'{v:.3g}' if 0<abs(v)<.0001 else f'{v:.4f}'
  return str(v)
 return '| '+' | '.join(df.columns)+' |\n|'+'|'.join(['---']*len(df.columns))+'|\n'+'\n'.join('| '+' | '.join(fmt(v) for v in row)+' |' for row in df.itertuples(index=False,name=None))
def interval(r):return f'{r.estimate:+.6f} [{r.lower:+.6f}, {r.upper:+.6f}]'
def interpretation(r):
 return ('확률오차를 아주 작게 줄였다' if abs(r.estimate)<.001 else '확률오차를 추가로 줄였다') if r.upper<0 else ('확률오차가 오히려 커졌다' if r.lower>0 else '확률오차의 추가 개선은 불확실했다')
def main():
 audit=json.loads((O/'source_audit.json').read_text());contract=json.loads((O/'feature_contract.json').read_text());v=json.loads((O/'verification.json').read_text());metrics=pd.read_csv(O/'early_metrics.csv');co=pd.read_csv(O/'early_comparisons.csv');lm=pd.read_csv(O/'late_metrics.csv');lc=pd.read_csv(O/'late_comparisons.csv');diag=pd.read_csv(O/'strong_front_side_diagnostic.csv');cards=pd.read_csv(O/'example_cards.csv',dtype={'horse_id':str});ep=pd.read_parquet(O/'early_predictions.parquet');summary=metrics[metrics.window.eq('2024_2025')&metrics.scope.eq('all')].set_index('model');common=metrics[metrics.window.eq('2024_2025')&metrics.scope.eq('supported5')].set_index('model');pooled=co[co.window.eq('2024_2025')&co.scope.eq('all')].set_index('comparison');sides=pooled.loc['B-A'];whole=pooled.loc['A-N']
 finding=f'''**전체 상대를 보는 기존 방향을 유지하면서, 전원의 각질·구간 구성과 게이트 안팎을 명시적으로 비교했다.** 기존에는 바깥 상대도 전체 비교에 포함됐지만 방향별로는 안쪽 선행성향 합만 있었다. 이번에는 기수·조교사 성향과 기수 교체 여부를 모두 제외했다.

2024·2025년 같은 {len(ep):,}출전에서 초반 네 각질 정확도는 기준 N {summary.loc['N','accuracy']*100:.2f}%, 전원 구성 확장 A {summary.loc['A','accuracy']*100:.2f}%, 안쪽/바깥쪽 구분 B {summary.loc['B','accuracy']*100:.2f}%였다. 전원 구성 확장의 Brier A−N은 {interval(whole)}로, {interpretation(whole)}. 안팎 구분의 B−A는 {interval(sides)}로, {interpretation(sides)}. 음수는 개선이며 괄호는 말·날짜 군집95% 구간이다. 전체·부분집단의 정확도와 확률오차를 구분한다.'''
 # Fixed plotting scale and same rows, including the old-F comparison with its residual change flag.
 order=['oldF','N','A','B'];fig,ax=plt.subplots(1,2,figsize=(12,5));colors=['#acb7c0','#819cb0','#4f87a9','#245572']
 for k,(metric,scale,label,ylim) in enumerate([('accuracy',100,'초반 4범주 정확도 (%)',(0,65)),('brier',1,'Brier · 낮을수록 좋음',(0,.8))]):
  values=summary.loc[order,metric].to_numpy()*scale;ax[k].bar(order,values,color=colors);ax[k].set_ylim(*ylim);ax[k].set_ylabel(label)
  for j,val in enumerate(values):ax[k].text(j,val+(ylim[1]-ylim[0])*.012,f'{val:.2f}' if k==0 else f'{val:.4f}',ha='center')
 fig.suptitle(f'출전마 전원과 게이트 안팎 · 2024·2025 시간순 평가 {len(ep):,}출전');fig.text(.5,.01,'oldF 이전 비교  |  N 기수 완전 제외  |  A 전원 각질·구간 확장  |  B 안쪽·바깥쪽 구분',ha='center',fontsize=10);fig.tight_layout(rect=[0,.05,1,.94]);fig.savefig(F/'prediction_comparison.png');plt.close(fig)
 key=cards.source_key.iloc[0];card=cards[cards.source_key.eq(key)];xx=np.arange(len(card));fig,ax=plt.subplots(1,2,figsize=(12,6));labels=[f'{r.gate} {r.horse_name}' for r in card.itertuples()]
 for a in ax:a.set_yticks(xx,labels);a.invert_yaxis()
 ax[0].barh(xx-.17,card.inner_strong_front_n,height=.34,label='안쪽',color='#d09b58');ax[0].barh(xx+.17,card.outer_strong_front_n,height=.34,label='바깥쪽',color='#477d9c');ax[0].set_xlabel('과거 선행3/5 이상인 상대 수');ax[0].legend(loc='lower left',bbox_to_anchor=(0,1.01),ncol=2);ax[1].barh(xx-.17,card.inner_faster_front_n,height=.34,label='안쪽',color='#d09b58');ax[1].barh(xx+.17,card.outer_faster_front_n,height=.34,label='바깥쪽',color='#477d9c');ax[1].set_xlabel('나보다 초반 잔차가 빠른 선행 후보 수');ax[1].legend(loc='lower left',bbox_to_anchor=(0,1.01),ncol=2);fig.suptitle(f'{key} · 같은 편성도 자기 게이트와 능력에 따라 상대 구성이 다름');fig.text(.5,.01,'자료 마지막 날 마지막 경주를 고정한 회고 사례. 후보 수는 실제 경합이나 압박의 관측값이 아님.',ha='center',fontsize=10);fig.tight_layout(rect=[0,.05,1,.94]);fig.savefig(F/'gate_side_example.png');plt.close(fig)
 readable=summary.reset_index()[['model','n','accuracy','brier','logloss']];readable['model']=readable.model.map(NAMES);readable.columns=['모형','평가 출전','정확도','Brier','로그손실'];comp=pooled.reset_index()[['comparison','estimate','lower','upper','bh_q_three']]
 case=cards[['source_key','gate','horse_name','inner_n','outer_n','inner_strong_front_n','outer_strong_front_n','inner_faster_front_n','outer_faster_front_n','B_p0','role4']].copy();case['role4']=case.role4.map(dict(enumerate(LABELS))).fillna('미관측');case.columns=['경주','게이트','말','안쪽 수','바깥 수','안쪽 선행후보','바깥 선행후보','안쪽 빠른 선행후보','바깥 빠른 선행후보','선행확률','실제 초반']
 pairtotal=len(pd.read_csv(O/'example_rival_pairs.csv'));worst=cards[cards.role4.eq(0)].sort_values('B_p0').iloc[0];best=cards.sort_values('B_p0',ascending=False).iloc[0]
 source='# 입력·출처와 보존\n\n2026-10-08. 신규 수집 없이28C의 검증된 전체 명단·시점 제한 과거 이력을 읽기 전용 재사용했다. 아래7개 직접 입력과 전이 출처 원문18개·파생3개의 해시는 이전 [출처](../20261008_field_pace_prediction/SOURCES.md)와 [원천 감사](../20261008_field_pace_prediction/outputs/source_audit.json)에 연결된다. 기존119파일을 계산 전 목록화하고 공유5개를 제외한114개를 보존한다.\n\n| 직접 입력 | 바이트 | SHA-256 |\n|---|---:|---|\n'
 for r in audit['inputs']:source+=f"| [{r['path'].split('/')[-1]}]({os.path.relpath(e.ROOT/r['path'],H)}) | {r['bytes']} | `{r['sha256']}` |\n"
 source+='\n원문은 한국마사회 API4_3 실전 결과와 기존 S1F 통과조 자료다. [공식 경주성적표 설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)의 S1F200m·G3F/G1F 지점과 마지막600/200m 시간을 구분한다. 첫 마군은 단독 선두와 다르다. 최종 명단의 당시 사전 공개시각·사후 정정은 감사하지 않았다. 기수/조교사 관련 변수는 이번 모형에서 모두 제외했으며 과거 말 기록에 남은 기수 영향을 인과적으로 제거한 것은 아니다.\n';(H/'SOURCES.md').write_text(source)
 report=f'''# 출전마 전원과 게이트 안팎을 함께 보는 전개 예측

2026-10-08 · 연구28 후속28D · 서울·부산 · 종료 서울2026-09-20/부산2026-09-18 · 연구 후보.

{finding}

## 무엇을 새로 확인했는가

기존에도 자기 자신을 제외한 전원이 전체 상대 집계에 들어갔다. ‘전체 선행성향 합−안쪽 합=바깥 합’이므로 바깥 선행합 하나는 새 독립 정보가 아니다. 이번 확장의 핵심은 **바깥에 몇 마리가 있고, 어떤 각질 분포이며, 그중 누가 자기보다 초반이 빠른가**를 안쪽과 같은 방식으로 입력한 것이다.

| 범위 | 반영 내용 |
|---|---|
| 각 말 | 최근 실제5/10슬롯의 네 각질 빈도, 원래 위치·성적·구간 이력 |
| 전체 상대 | 네 각질 비율 평균과 지원, 초반200m·마지막600/200m 원초와 잔차, 단독선두율 |
| 안쪽·바깥쪽 각각 | 같은 정보의 평균·지원, 선행/앞선 후보 수, 빠른 상대 수, 빠른 선행후보 수, 빠른 상대의 선행성향 합 |
| 결측 | 신마·기록 부족 상대도 명단 유지, 방향별 인원·유효수/지원비율과 미관측 표시 |

자기 기록을 상대 평균에 포함하지 않는다. 각 말의 어느 쪽에도 상대가 없으면 인원·합은0, 평균·지원비율은 미관측이다. ‘기록이 없어서 빠른 상대를 알 수 없음’과 ‘알려진 빠른 상대가0두’를 구분한다. 게이트 번호 사이의 취소 공백은 유지한다. 번호의 안팎이지 실제 주행 중 레일 위치나 물리적 경로 길이가 아니다.

선행 후보는 최근5슬롯 선행3회 이상, 앞선 후보는 선행+선입3회 이상이다. 빠른 상대는 과거 평균 초반 환경 잔차가 자기보다 큰 말이며 동률을 제외한다. 원초 빠름도 별도로 저장했다. 마지막600m와200m는 겹치므로 독립 능력 점수처럼 더하지 않는다. 후보 수·성향 합은 실제 경합의 공동확률이 아니다.

선행성향 합은 각 상대의 (과거 선행횟수+1)/(유효 각질수+4)를 더한 값이다. 이력 미관측 말의0.25는 사전값이므로 관측 성향으로 오해하지 않는다. 유효수·기록 지원과 함께 읽어야 하며 이번 경주에서 각 말이 선행할 예측확률의 합도 아니다.

## 같은 표본·같은 설정의 시간순 검증

전체159,014출전·14,636경주·12,516두를 상대 명단에 유지했다. 주 성능평가는2024·2025의36,638출전·4,405두·3,465경주다. N은 기존 F에서 기수 교체 표식까지 제거한157개, A는202개, B는297개 입력이다. 기수·조교사 성향과 식별자·교체 여부가 실제 저장 모형에 없는지 확인했다.

{table(readable)}

![같은 평가행 비교](figures/prediction_comparison.png)

{table(comp)}

B−A가 주 비교다. A−N은 전원 구성의 명시적 확장이고 N−oldF는 기수 교체 표식 제거다. 세 대비 BH를 표시했다. N과 B의 차이 전체를 바깥 게이트만의 효과로 해석하지 않는다. 기존 유효5전 공통24,613출전에서는 N {common.loc['N','accuracy']*100:.2f}%, A {common.loc['A','accuracy']*100:.2f}%, B {common.loc['B','accuracy']*100:.2f}%였다. 연도별 전체/지원수·정확도·확률오차는 [성능 원표](outputs/early_metrics.csv), [군집구간](outputs/early_comparisons.csv), [지역·거리·등급·게이트 구간](outputs/subgroup_metrics.csv), [교정표](outputs/early_calibration.csv)를 따른다.

모든 학습은 평가연도 이전 자료만 사용했다.2024모형은2023년까지,2025모형은2024년까지다. 학습률0.04·15잎·최소잎150·L2=10·180회·seed42를 고정해 결과를 보고 튜닝하지 않았다. 과거 실제 슬롯·T−2·730일·전년까지의 환경 기준을 재사용했다. 현재 경주의 실제 각질·시간·함수율·체중·rating·배당은 입력하지 않았다. 명단 메타정보의 당시 사전 공개시각은 미감사이므로 회고 시간순 실험이다.

2024·2025년은 이전 연구에서도 사용한 후향 기간이다. 시간순 분리를 지킨 비교이며, 아직 보지 않은 미래 경주에서 독립 검증을 완료한 것은 아니다.

## 평소 선행형에서 안팎 상대를 보면

아래는 과거5슬롯 선행3회 이상, 초반 잔차3전 이상인 말의 관찰표다. 안/중/외 게이트 구간마다 안쪽·바깥쪽의 ‘자기보다 초반이 빠른 선행후보’가 있는지 나눴다. 현재 경주 실제 전개로 후보를 미리 골라내지 않았다.

{table(diag)}

거리·말 능력·두수·지원·선행 경쟁이 섞인 기술통계다. 외곽 상대 유무의 인과효과나 강제 선행실패 손실이 아니다. 구간마다 표본 수가 다르고 어떤 조합은 적다. 안팎이 모두 복잡한 편성에서 한쪽만으로 결론을 내리지 않는다.

예를 들어 안쪽 게이트이고 안쪽에 빠른 선행후보가 없는 경우, 바깥에도 없으면 첫 마군 포함률71.0%(877출전), 바깥에 있으면45.5%(865출전)였다. 중간 게이트의 같은 비교는65.9%(739출전) 대39.8%(294출전)였다. 바깥 상대도 살펴야 한다는 관찰 근거지만 자기 능력이 낮을수록 ‘자기보다 빠른 상대’가 늘어나는 구조도 있어 원인 효과로 읽지 않는다.

이 관찰 차이가 새 방향별 입력의 예측 개선을 뜻하지는 않는다. B−A는2024년−0.000161,2025년+0.000244로 방향이 달랐고 두 연도 모두 구간이0을 포함했다. 기존에도 전체 상대 속도와 게이트 정보가 있었으며 바깥 선행합은 계산 가능했다. 이번 결과만으로 방향별 확장 B를 우수 모형으로 채택하거나 외측 압박 가산점을 확정할 근거는 없다.

## 후반 순위 회복·앞선 후퇴

28C와 같은 목표를 유지했다. 회복은 결승 전600m에서 뒤쪽 상대위치0.5 이상인 말이 결승까지0.25 이상 회복, 후퇴는 초반 선행/선입이면서 결승 상대위치가 초반 마군평균보다0.30 이상 뒤인 사건이다. 현재 실제 앞선 여부로 사전 표본을 고르지 않으며 미완주/미관측 목표는0으로 대체하지 않는다. 이 결과는 추입 의도·육체적 붕괴의 정답이 아니다.

{table(lm[lm.window.eq('2024_2025')][['task','model','n','prevalence','brier','auc','low20_rate','high20_rate']])}

{table(lc[lc.window.eq('2024_2025')][['task','estimate','lower','upper','bh_q_two']])}

이 후반 비교는 N과 B의 전체 입력 확장 효과이며 방향 구분만의 독립 효과가 아니다. [원표](outputs/late_metrics.csv) · [교정표](outputs/late_calibration.csv).

## 출전마 전원을 보존한 같은 편성 사례

이전28C와 같은 자료 마지막 날짜 마지막 경주를 고정했다.2026모형은2025년까지 학습했고 사례 결과를 학습하거나 현재 입력에 넣지 않았다. 좋은 결과의 경주를 고른 것이 아니며 당시 실제 사전 발행도 아니다. 두 경주21두, 자기 제외 방향이 있는 상대 {pairtotal}쌍을 모두 저장했다.

{table(case)}

![게이트 양쪽의 선행후보](figures/gate_side_example.png)

이 고정 사례에서 가장 높은 선행확률은 {best.horse_name} {best.B_p0*100:.1f}%였다. 실제 첫 마군 중 가장 낮게 예측한 말은 {worst.horse_name} {worst.B_p0*100:.1f}%였다. 위치확률은 고정 작전이 아니며, 낮은 확률 사건도 발생한다. 실제 추진·제어·진로·작전 지시 자료가 없어 이런 차이의 원인을 확정하지 않는다.

[출전마별 전체/안팎 입력과 확률](outputs/example_cards.csv) · [모든 상대 쌍별 각질·기록](outputs/example_rival_pairs.csv). 각 상대의 최근5/10전 네 각질, 초반/막판 시간·잔차, 선행 성향과 게이트 방향을 대조할 수 있다. 모형은 이들을 전체·방향별 요약으로 사용하며, 말별 전체 주행경로의 공동확률이나 모든 게이트 순서 조합을 직접 학습한 결과는 아니다.

## 검증·보존·적용 범위

독립 SQL 자기 제외·전원·안팎 집계 {v['independent_SQL_values']:,}개 값, 게이트 대칭 {v['mirror_races']}경주, 현재 결과/기수 변조, 별도 트리 경로와 저장 예측, 확률·군집/BH·교정·상대 전수 검증을 통과했다. 총 검사 {v['checks']:,}개, 기존 {v['prior_files_preserved']}파일 보존이다. 입력/결측/게이트 집계를 검증한 것이 모든 미래 경주의 성능 보장은 아니다.

[계산 전 계획](PLAN.md) · [출처](SOURCES.md) · [검증](outputs/verification.json) · [게시요약](PUBLICATION.md) · [게시JSON](PUBLICATION.json) · [중앙28D](../conclusions/28D_BILATERAL_FIELD_PACE.md) · [용량](outputs/SIZE_REPORT.md). 기존 독립 연구 수41·DB·운영 모델·웹 배포는 유지한다. 기수·조교사는 이번 입력에서 제외했지만 과거 말 기록 속 기수 영향을 인과적으로 분리한 것은 아니다. 직접 작전 의도·주행경로·강제 선행실패의 성적 손실·입상확률 개선은 별도 미검증이다.
''';(H/'README.md').write_text(report)
 public=f'''# 게이트 안쪽과 바깥쪽 상대를 함께 보는 전개

{finding}

각 말의 최근5/10전 각질·초반/막판 기록을 자기 제외 전원, 안쪽, 바깥쪽으로 비교한다. 바깥의 선행형 수와 자기보다 초반이 빠른 선행형 수를 구분하고 신마/결측 상대도 편성에 남긴다. 정보가 없는 것과 경쟁 상대0두를 구분한다. 선행은 S1F 첫 마군 전체이며 단독 선두가 아니다.

평소 선행3/5인 말 중 안쪽 게이트·안쪽 빠른 선행후보 없음 조건에서 바깥에도 빠른 선행후보가 없으면 첫 마군71.0%(877출전), 있으면45.5%(865출전)였다. 자기 능력·거리 등이 섞인 관찰 차이이며 외곽 상대의 인과효과가 아니다. 이 차이와 새 입력의 추가 예측 가치는 구분한다. 방향별 확장의 성능 우위는 확인하지 못했다.

[같은 두 편성21두](outputs/example_cards.csv)와 [상대200쌍](outputs/example_rival_pairs.csv)은 자료 마지막 날짜 마지막 경주를 고정한 회고 예시다. 숫자는 후보 구성을 설명하며 실제 경합·기수 의도·물리적 외곽 손실을 직접 측정한 값이 아니다.

서울·부산, 자료 종료2026-09-20/09-18. 주 평가2024·2025,2026사례는2025년까지 학습했다. 당시 사전 명단 공표시각은 미감사다. 연구 후보이며 운영 반영·배포 전이다.

[보고서](README.md) · [예측 성능 그림](figures/prediction_comparison.png) · [안팎 사례 그림](figures/gate_side_example.png) · [출처](SOURCES.md) · [검증](outputs/verification.json).
''';(H/'PUBLICATION.md').write_text(public)
 obj=dict(study_id=H.name,followup='28D',title='출전마 전원과 게이트 안팎의 전개 예측',updated='2026-10-08',status='research_candidate',operational=False,deployed=False,intention_labels=False,prerace_publication_timestamps_audited=False,excluded=['jockey tendencies','trainer tendencies','jockey change flag'],roster_n=159014,evaluation_n=len(ep),evaluation_years=[2024,2025],feature_counts={k:len(v) for k,v in contract['groups'].items()},early_metrics=summary.reset_index().to_dict('records'),early_comparisons=pooled.reset_index().to_dict('records'),late_metrics=lm[lm.window.eq('2024_2025')].to_dict('records'),late_comparisons=lc[lc.window.eq('2024_2025')].to_dict('records'),case_runners=len(cards),case_rival_pairs=pairtotal,scope='Self-excluded whole roster and bilateral gate-side summaries; not joint paths, direct intent or causal pressure',links=dict(report='README.md',sources='SOURCES.md',examples='outputs/example_cards.csv',rival_pairs='outputs/example_rival_pairs.csv',verification='outputs/verification.json'))
 e.dump(H/'PUBLICATION.json',obj);print('Published Korean report, sources, MD/JSON and two figures')
if __name__=='__main__':main()

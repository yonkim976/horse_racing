"""Korean research documents, publication data and verified-input figures."""
from pathlib import Path
import json,os
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/field_pace_prediction_mpl')
import numpy as np,pandas as pd,matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import data
H=data.H;O=data.O;FIG=H/'figures';LABELS=data.LABELS
font_manager.fontManager.addfont('/System/Library/Fonts/AppleSDGothicNeo.ttc');plt.rcParams.update({'font.family':'Apple SD Gothic Neo','axes.unicode_minus':False,'font.size':11,'figure.dpi':130})
NAMES={'B':'지역·거리·두수 빈도','H':'최근5전 빈도','P':'위치·성적·메타 이력','S':'+ 과거 구간기록','F':'+ 편성 비교','J':'+ 기수·조교사 이력'}
def table(df):
 def f(v):
  if isinstance(v,(float,np.floating)):
   if not np.isfinite(v):return '미관측'
   return f'{v:.3g}' if 0<abs(v)<.0001 else f'{v:.4f}'
  return str(v)
 return '| '+' | '.join(df.columns)+' |\n|'+'|'.join(['---']*len(df.columns))+'|\n'+'\n'.join('| '+' | '.join(f(v) for v in row)+' |' for row in df.itertuples(index=False,name=None))
def ci(r,scale=1):return f"{r.estimate*scale:+.4f} [{r.lower*scale:+.4f}, {r.upper*scale:+.4f}]"
def main():
 audit=json.loads((O/'source_audit.json').read_text());verify=json.loads((O/'verification.json').read_text());em=pd.read_csv(O/'early_metrics.csv');ec=pd.read_csv(O/'early_comparisons.csv');lm=pd.read_csv(O/'late_metrics.csv');lc=pd.read_csv(O/'late_comparisons.csv');gm=pd.read_csv(O/'grade_matched_comparisons.csv');gr=pd.read_csv(O/'grade_repeatability.csv');cards=pd.read_csv(O/'example_cards.csv',dtype={'horse_id':str});ep=pd.read_parquet(O/'early_predictions.parquet');ctx=pd.read_parquet(O/'feature_context.parquet');race=pd.read_csv(O/'race_metrics.csv')
 allm=em[em.window.eq('2024_2025')&em.scope.eq('all')].set_index('model');supported=em[em.window.eq('2024_2025')&em.scope.eq('supported5')].set_index('model');main=ec[ec.window.eq('2024_2025')&ec.scope.eq('all')&ec.comparison.eq('J-S')].iloc[0]
 # One report row per historical strong-front runner, grouped by prior relative speed.
 e=ep.merge(ctx[['row_key','count5_0','field_rank_early_adv_mean5','field_strong_front_other','early_n5']],on='row_key',validate='one_to_one');z=e[e.count5_0.ge(3)&e.early_n5.ge(3)&e.field_rank_early_adv_mean5.notna()].copy();z['speed_group']=pd.cut(z.field_rank_early_adv_mean5,[-.001,1/3,2/3,1.001],labels=['편성 내 과거 초반 빠른쪽','중간','느린쪽']);z['first_group']=z.role4.eq(0);diag=z.groupby('speed_group',observed=True).agg(n=('row_key','size'),horses=('horse_id','nunique'),actual_first_group=('first_group','mean'),estimated_first_group=('J_p0','mean')).reset_index();diag.to_csv(O/'strong_front_relative_speed.csv',index=False)
 fig,ax=plt.subplots(1,2,figsize=(12,4.8));order=['B','H','P','S','F','J'];colors=['#a8b6c5','#92a8bd','#7395b0','#4d83b0','#28658e','#164768'];ax[0].bar(order,allm.loc[order,'brier'],color=colors);ax[0].set_ylim(0,.8);ax[0].set_ylabel('4범주 Brier · 낮을수록 좋음');ax[1].bar(order,allm.loc[order,'accuracy']*100,color=colors);ax[1].set_ylim(0,65);ax[1].set_ylabel('초반 각질 분류 정확도 (%)')
 for j,metric,scale in [(0,'brier',1),(1,'accuracy',100)]:
  for i,name in enumerate(order):ax[j].text(i,allm.loc[name,metric]*scale+.01*ax[j].get_ylim()[1],f'{allm.loc[name,metric]*scale:.3f}' if j==0 else f'{allm.loc[name,metric]*scale:.1f}',ha='center')
 fig.suptitle(f'2024·2025 시간순 평가 · {len(ep):,}출전 · 해당 연도 이전만 학습');fig.text(.5,.01,'B 빈도  |  H 최근5전  |  P 위치·성적  |  S 구간 추가  |  F 편성 추가  |  J 기수·조교사 추가',ha='center',fontsize=10);fig.tight_layout(rect=[0,.05,1,.94]);fig.savefig(FIG/'early_prediction.png');plt.close(fig)
 fig,ax=plt.subplots(1,2,figsize=(12,4.8))
 for i,task in enumerate(['recovery','fade']):
  row=lm[lm.task.eq(task)&lm.window.eq('2024_2025')&lm.model.eq('J')].iloc[0];vals=[row.low20_rate*100,row.prevalence*100,row.high20_rate*100];ax[i].bar(['예측 하위20%','전체','예측 상위20%'],vals,color=['#9bb4c9','#648da9','#275c7e']);ax[i].set_ylim(0,max(vals)*1.25);ax[i].set_ylabel('관측 발생률 (%)');ax[i].set_title('후반 순위 회복' if task=='recovery' else '앞선 뒤 순위 후퇴')
  for j,v in enumerate(vals):ax[i].text(j,v+max(vals)*.025,f'{v:.1f}%',ha='center')
 fig.suptitle('출전 전 이력으로 본 후반 움직임 · 실제 현재 구간기록은 입력하지 않음');fig.text(.5,.01,'순위 회복은 추입 의도, 순위 후퇴는 육체적 붕괴를 직접 입증하지 않는다.',ha='center',fontsize=10);fig.tight_layout(rect=[0,.05,1,.94]);fig.savefig(FIG/'late_prediction.png');plt.close(fig)
 first=cards.source_key.iloc[0];card=cards[cards.source_key.eq(first)];fig,ax=plt.subplots(figsize=(10,6));bottom=np.zeros(len(card));palette=['#e09e4b','#57a1ac','#6b86bd','#aeafbb'];xx=np.arange(len(card))
 for j,label in enumerate(LABELS):v=card['J_p'+str(j)].to_numpy()*100;ax.barh(xx,v,left=bottom,label=label,color=palette[j]);bottom+=v
 ax.set_yticks(xx,[f'{r.gate} {r.horse_name}' for r in card.itertuples()]);ax.invert_yaxis();ax.set_xlim(0,100);ax.set_xlabel('말별 초반 각질 확률 (%)');ax.legend(ncol=4,loc='lower center',bbox_to_anchor=(.5,1.01));ax.set_title(f'{first} · 자료 마지막 날 마지막 경주 · 회고 예시',pad=44);fig.tight_layout();fig.savefig(FIG/'example_card.png');plt.close(fig)
 source='# 출처와 입력 감사\n\n2026-10-08. 새 수집 없이 기존 읽기 전용 자료3개와 원문18개를 대조했다. 각 원문 API4_3 응답의 출전 번호로 기수·조교사·연령을 확인했다.\n\n공식 정의: [한국마사회 경주성적표 설명](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1). S1F는 출발 후200m, G3F/G1F는 결승 전600/200m 지점이며 3F-G/1F-G 시간과 통과 위치를 구분한다. 괄호로 묶인 마군의 좌우 순서는 착순 순위가 아니다.\n\n| 입력 | 바이트 | SHA-256 |\n|---|---:|---|\n'
 for r in audit['inputs']:source+=f"| [{Path(r['path']).name}]({os.path.relpath(data.ROOT/r['path'],H)}) | {r['bytes']} | `{r['sha256']}` |\n"
 source+='\n기수·조교사는 최종 결과 원문의 실제 출전 식별자다. 당시 사전 공표시각·사후 정정·기수 변경 공표를 감사하지 않았다. 영상·작전 지시·진술 자료가 없어 직접 전술 의도 정답은 없다. 기존 연구 전체 기간의 공통 점수나 미래 기준은 사전 입력으로 사용하지 않았다.\n';(H/'SOURCES.md').write_text(source)
 methods='''초반 각질은 S1F 통과조를 기준으로 선행·선입·중단·후미 네 범주다. **선행은 첫 마군 전체**다. 그 밖은 마군 평균 상대위치1/3·2/3 경계로 구분한다. 한 경주 여러 말이 선행일 수 있으므로 각 말의 네 확률만 합이1이며, 말 전체의 선행확률 합은1이 아니다. 후미를 자동으로 추입형이라 부르지 않는다.

최근5/10전은 실제 출전 슬롯이며 T−2까지·730일 이내 기록만 쓴다. 미관측을 건너뛰지 않고 유효수와 함께 부분 평균을 썼다. 기수·조교사 이력은 T−2까지 직전365일이며 같은 날·전날 결과를 배제했다. 선행빈도와 말의 사전 선행빈도 대비 편차를20회 강도로 축소했다. 이 편차는 완전한 능력 보정이나 직접 작전 의도가 아니다.

과거 구간기록은 원초, 같은 경주 상대시간, 전년까지 학습한 지역×정확거리·월·함수율 기준 잔차로 구분했다. 등급 간 능력차를 지우지 않도록 기본 환경모형에는 등급을 넣지 않았다. 마지막200m 조건부 잔차는 과거 경주의 실제 초반·중간과 등급·rating·연령·부담중량을 더해 설명한 값이다. 이 과거 잔차만 다음 경주 입력으로 사용한다. 2018년 환경 잔차는 미관측이다. G3F와 G1F의 겹치는 기록을 별도 능력으로 가산하지 않는다.

P는 현재 지역·거리·등급·게이트·두수·연령과 과거 위치·착순·rating·회복/후퇴 이력, S는 자기 구간 이력, F는 상대마와의 초반 속도 차이·순위·선행 후보 수·내측 상대 성향, J는 기수·조교사 이력을 차례로 추가한다. 신마·기록 결측 상대도 명단에서 제거하지 않는다. 현재 경주의 S1F/G3F/G1F·착순·시간·함수율·체중·rating·배당은 입력하지 않는다.

LightGBM 학습률0.04·15잎·최소잎150·L2=10·180회·seed42를 고정했다. 2024년은2023년까지, 2025년은2024년까지 학습했으며 평가로 튜닝하지 않았다. 2026년 사례는2025년까지 학습한 별도 동결모형이다. 말·실제 날짜·교집합 군집의 보수적인 최대 분산으로95% 구간을 계산했다. 주 비교 J−S와 보조 S−P/F−S/J−F 네 대비에 BH를 표시했다. 전체기간은 과거 이력과 환경 기준의 학습 자료이고, 주 성능평가는2024·2025년이다.'''
 emtable=em[em.window.eq('2024_2025')&em.scope.eq('all')][['model','n','accuracy','brier','logloss']].copy();emtable['model']=emtable.model.map(NAMES);emtable.columns=['모형','평가 출전','정확도','Brier','로그손실']
 ectable=ec[ec.window.eq('2024_2025')&ec.scope.eq('all')][['comparison','estimate','lower','upper','bh_q_four_comparisons']];gmtable=gm[['target','cells','high_n','low_n','high_mean','low_mean','estimate','lower','upper']]
 lmtable=lm[lm.window.eq('2024_2025')][['task','model','n','prevalence','brier','auc','low20_rate','high20_rate']]
 casecols=['source_key','gate','horse_name','J_p0','J_p1','J_p2','J_p3','recovery_p','fade_p','role4'];casetable=cards[casecols].copy();casetable['role4']=casetable.role4.map(dict(enumerate(LABELS))).fillna('미관측');casetable.columns=['경주','게이트','말','선행','선입','중단','후미','후반 회복','앞선 후퇴','실제 초반']
 interpretation=f'''**전개 예상에 쓸 추가 정보는 있었다.** 전체 평가 {len(ep):,}출전에서 최근5전 빈도의 정확도는 {allm.loc['H','accuracy']*100:.1f}%, 위치·성적 이력 P는 {allm.loc['P','accuracy']*100:.1f}%, 자기 구간기록 S는 {allm.loc['S','accuracy']*100:.1f}%, 편성·기수·조교사까지 넣은 J는 {allm.loc['J','accuracy']*100:.1f}%였다. 주 비교 J−S Brier 차이는 {ci(main)}다. 구간기록과 상대 비교를 넣는 효과를 별도로 확인한 결과이며, 전개 의도를 맞혔다는 결과는 아니다.

실무에서는 각 말을 고정 각질 하나로 정하지 않고 **평소 위치 분포 → 이번 편성에서 위치 확보 확률 → 후반 회복/후퇴 확률**을 함께 읽는 편이 맞다. S1F가 상대보다 빠르고 과거 첫 마군 진입이 반복된 말은 앞선 후보로 보되, 바깥 게이트·빠른 내측 상대·앞선 후보 밀집도에 따라 이번 확률이 달라진다. 상대 후보 수는 관측된 실제 경합 강도가 아니다. S1F 시간은 반응·가속·기수 추진이 함께 들어간200m 기록이므로 독립적인 출발 반응시간으로 읽지 않는다.

막판 구간시간이 빠른 것과 뒤에서 순위를 회복한 것은 다르다. 앞에서 위치를 지키며 빠르게 끝낸 말도 있고, 느린 흐름에서 뒤쪽 말이 순위만 회복할 수도 있다. 과거 마지막600/200m 시간·조건부200m 잔차·실제 회복/후퇴 이력을 함께 보존했다. 후반 시간의 빠름/느림을 체력이나 최적 전술의 직접 증거로 단정하지 않는다.'''
 report=f'''# 편성 안의 초반 위치와 후반 움직임 예측

2026-10-08 · 연구28 후속28C · 서울·부산 · 자료 종료 서울2026-09-20, 부산2026-09-18 · 연구 후보, 운영 반영 전.

{interpretation}

## 시간순 성능

전체 명단 {audit['roster_n']:,}출전·{audit['races']:,}경주·{audit['horses']:,}두를 유지했다. 통과조 관측 {audit['early_observed']:,}, 정상 구간기록 {audit['normal_sections_n']:,}출전이다. 2024·2025 평가 {len(ep):,}출전·{ep.horse_id.nunique():,}두·{ep.source_key.nunique():,}경주다. 결측 각질은 학습/정답 평가에서 제외하지만 상대 편성 입력에는 남긴다.

{table(emtable)}

![초반 확률 비교](figures/early_prediction.png)

Brier는 네 범주의 확률오차 합이며 낮을수록 좋다. 정확도는 가장 높은 확률의 범주가 실제 범주와 같은 비율이다. J의 개선이 네 범주를 완전히 구분한다는 뜻은 아니다. 연도별 수치와 전체/지원5전 비교는 [원표](outputs/early_metrics.csv)에 있다. 기존28A와 공통인 유효5전 지원24,613출전에서 H 정확도 {supported.loc['H','accuracy']*100:.1f}%, J {supported.loc['J','accuracy']*100:.1f}%, Brier {supported.loc['H','brier']:.4f}→{supported.loc['J','brier']:.4f}다.

{table(ectable)}

차이는 추가 모형−이전 모형으로 음수가 개선이다.95% 군집구간과 네 대비 BH를 병기했다. 연도별 결과는 [대비 원표](outputs/early_comparisons.csv), 확률과 실제 빈도의 관계는 [교정표](outputs/early_calibration.csv)에 있다. 경주별 최고 선행확률마와 선행두수 평가는 전원 초반 관측 경주만 사용한다.

{table(race)}

## 상위등급이면 각질이 더 뚜렷한가

{table(gr)}

strong5는 과거 실제5전 중 같은 범주4회 이상, mode_repeat는 다음 경주의 과거 최빈 범주 반복률이다. 원시 등급 비교에는 이력량·연령·거리 구성 차이가 섞인다. 상위1·2등급과 국5·국6을 지역×정확거리×연도×이력수×연령 공통셀에서 비교한 결과는 아래와 같다. 각 집단20출전 이상인 셀의 조화표본수로 가중했다. 셀 밖에는 일반화하지 않으며 승급의 인과효과가 아니다.

{table(gmtable)}

고등급일수록 무조건 뚜렷해진다고 일반화하기보다, [등급별 예측오차](outputs/early_metrics.csv)와 실제 반복성·지원수를 함께 판단한다.95% 구간 및 두 대비 BH는 [비교 원표](outputs/grade_matched_comparisons.csv)에 보존했다.

이 공통 범위24셀·4,033출전에서 강한 과거 성향 비율은 상위32.7%, 하위35.9%였고 차이는−3.15%p [−8.92,+2.63]다. 다음 각질 반복률도44.1% 대47.3%, 차이−3.17%p [−8.14,+1.80]였다. 두 비교 모두 BH q=0.2845로, **상위등급에서 더 뚜렷해진다는 근거는 이 비교에서 확인하지 못했다.** 같다는 증명이나 모든 거리의 결론도 아니다.

## 막판 회복과 앞선 후퇴

후반 회복은 결승 전600m에서 상대순위0.5 이상인 말이 결승까지0.25 이상 회복한 사건이다. 앞선 후퇴는 S1F 선행/선입이면서 결승 상대위치가 초반 마군평균보다0.30 이상 뒤인 사건이다. 현재 경주의 실제 앞선 여부로 예측 표본을 먼저 고르지 않고, 모든 유효 목표를 대상으로 사전 변수만 학습했다. 미완주·미관측 정답은0으로 바꾸지 않았다. 이런 사건은 추입 의도나 육체적 붕괴의 정답이 아니다.

{table(lmtable)}

![후반 발생률](figures/late_prediction.png)

AUC는 사건 구분 순서 성능이다. 하위/상위20%는 예측 확률 기준이며, 발생률이 예측 확률 자체와 같지는 않다. [후반 군집 비교](outputs/late_comparisons.csv)와 [교정표](outputs/late_calibration.csv)를 함께 보존했다. 전체 사전 모형 J와 P의 통합 Brier 차이는 회복 {ci(lc[lc.task.eq('recovery')&lc.window.eq('2024_2025')].iloc[0])}, 후퇴 {ci(lc[lc.task.eq('fade')&lc.window.eq('2024_2025')].iloc[0])}다.

평소 선행 이력3/5 이상이며 초반 기록3전 이상 있는 말의 편성 내 과거 초반잔차 순위별 실제 첫 마군 비율도 보았다. 아래 표는 선택된 역사 표본의 기술통계이며, 강한 상대가 선행 실패를 일으킨 인과효과가 아니다.

{table(diag)}

## 같은 편성의 회고 사례

서울·부산의 자료 마지막 날짜에서 마지막 경주 번호를 고정 선택했다. 잘 맞는 경주를 골라낸 것이 아니다.2026 모형은2025년 말까지 학습했고 해당 경주 이전 이력만 입력했다. 최종 출전 명단 메타정보의 실제 사전 공표시각은 감사하지 않았으므로 당시 사전 발행 실적이 아니다. 실제 결과는 아래 비교 열에만 썼다.

{table(casetable)}

![한 편성 확률](figures/example_card.png)

각 말의 네 초반 확률과 후반 사건 확률을 함께 보되, 회복·후퇴가 어느 각질을 시도하려는 의지를 뜻하지는 않는다. 이름·기수/조교사·구간 지원수·자기 S와 편성 J의 확률 차이는 [사례 원표](outputs/example_cards.csv)에 있다.

부산 사례의 프라임시크릿은 자기 구간 이력 S의 선행확률51.7%에서 편성·기수/조교사를 더한 J의72.3%로 올라갔고 실제 첫 마군에 들어갔다. 마하타이탄은53.4%였지만 실제 중단이었다. 스타마타는 후미90.1%였는데 실제 첫 마군에 들어가 큰 예측 실패가 났다. 이를 전술 변경이나 적극 추진의 증거로 확정할 수는 없다. 이 예시들은 확률을 고정 작전으로 읽으면 안 되는 이유를 보여준다.

현재 말별 이력은 [12,516두 프로필](outputs/latest_horse_pace_profiles.csv)에 저장했다. 기준일2026-09-22(T−2)이며 최근 실제5/10슬롯의 위치 분포, 구간 평균/유효수, 마지막200m 조건부 잔차, 회복/후퇴 이력을 담았다. 과거 자료의 말도 포함하므로 active_365·days_since_last·supported5를 함께 봐야 한다. 이번 편성을 지정하지 않은 말에는 위치확률을 발행하지 않았다. [프로필 독립 SQL 검증](outputs/profile_verification.json)을 병기했다.

## 방법과 적용 범위

{methods}

게이트·상대의 힘 때문에 원래 원하는 자리를 못 잡았는지는 통과 결과만으로 확정할 수 없다. 같은 말의 기수·게이트·편성별 반복 변화와 말의 과거빈도를 넘는 기수/조교사 성향은 간접 단서다. 직접 의지를 검증하려면 출발 후 추진, 고삐 제어, 진로막힘, 실제 작전 지시/사전 발언 같은 별도 정답과 시점 자료가 필요하다. 본 연구에는 그 자료가 없다.

## 검증과 산출물

독립 SQL 실제5/10슬롯, 원문 식별자, 연간 ridge 정상방정식, 자기 제외 상대 입력, 같은 날/미래 결과 변조, 별도 트리 경로 해석기, 확률·군집구간·BH·등급 셀을 검증했다. [검증 결과](outputs/verification.json) {verify['checks']:,}개 비교가 통과했으며 기존 {verify['preserved_prior_files']}개 참조 파일을 보존했다. [계산 전 계획](PLAN.md) · [출처21개와 해시](SOURCES.md) · [입력 감사](outputs/source_audit.json) · [게시요약](PUBLICATION.md) · [게시JSON](PUBLICATION.json) · [용량](outputs/SIZE_REPORT.md) · [중앙28C](../conclusions/28C_FIELD_PACE_PREDICTION.md).

연구용 모형·확률·각 말 입력은 본 폴더에 보존했다. 기존 독립 연구 수·DB·운영 예측모델·웹 배포는 변경하지 않았다. 자료 뒤의 새 편성·다른 지역/시즌·직접 전술 의도·선행 실패의 인과손실·승률 개선은 아직 검증하지 않았다.
'''
 (H/'README.md').write_text(report)
 public=f'''# 각질은 평소 성향과 이번 편성을 함께 봐야 한다

{interpretation}

서울·부산2024·2025 시간순 평가 {len(ep):,}출전이다. 자기 구간기록을 넣은 S와 편성·기수·조교사를 더한 J의 Brier 차이는 {ci(main)}였다. 현재 경주의 실제 구간기록을 예측 입력으로 사용하지 않았다. 기수·조교사 효과는 기록상 성향이며 전술 의도를 직접 확인한 결과가 아니다.

상위등급의 반복성은 이력량과 거리를 맞춘 [공통셀 비교](outputs/grade_matched_comparisons.csv) 범위에서 읽어야 한다. 막판은 마지막600/200m 시간과 순위 회복·앞선 후퇴를 구분한다. [후반 평가표](outputs/late_metrics.csv)에서 예측 상하위 집단의 실제 발생률을 확인할 수 있다.

자료 마지막 날 마지막 경주를 고정한 [서울·부산 사례](outputs/example_cards.csv)는 각 말의 네 위치 확률을 보여준다. 선행확률은 첫 마군에 들어갈 확률이며 단독 선두·우승확률이 아니다. 이 회고 사례를 실제 사전 공표 실적으로 표시하지 않는다.

[연구 보고서](README.md) · [초반 성능 그림](figures/early_prediction.png) · [후반 그림](figures/late_prediction.png) · [출처](SOURCES.md) · [검증](outputs/verification.json). 자료 종료 서울2026-09-20·부산2026-09-18. 연구 후보이며 운영 반영·공개 배포 전이다.
''';(H/'PUBLICATION.md').write_text(public)
 obj=dict(study_id=H.name,followup='28C',title='편성 안의 초반 위치와 후반 움직임 예측',updated='2026-10-08',status='research_candidate',operational=False,deploy_completed=False,regions=['서울','부산'],data_end_by_meet=audit['end_by_meet'],evaluation_years=[2024,2025],evaluation_n=len(ep),roster_n=len(ctx),early_definition='S1F passing groups; first group is all front-group horses, not sole leader',intention_labels=False,prerace_publication_timestamps_audited=False,early_metrics=allm.reset_index().to_dict('records'),early_comparisons=ec[ec.window.eq('2024_2025')&ec.scope.eq('all')].replace({np.nan:None}).to_dict('records'),late_metrics=lm[lm.window.eq('2024_2025')].to_dict('records'),grade_matched=gm.to_dict('records'),links=dict(report='README.md',sources='SOURCES.md',verification='outputs/verification.json',examples='outputs/example_cards.csv',early_figure='figures/early_prediction.png',late_figure='figures/late_prediction.png'),limitations=['Chronological retrospective experiment using final roster metadata; actual prepublication timestamps not audited','No direct tactical intention, reaction latency or collapse mechanism labels','Conditional observational grade overlap; no causal promotion effect','No operational forecast or win-probability validation'])
 (H/'PUBLICATION.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print('Wrote reports, publication MD/JSON, descriptive table and three figures')
if __name__=='__main__':main()

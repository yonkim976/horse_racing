"""Publish separate performance, subgroup prediction, and incremental-feature findings."""

import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import HERE,OUT,dump,parent

LABELS={'base':'기존 심사 모형','identity':'기수 일치 추가','quality':'심사 기수 실력 추가','quality_identity':'실력과 일치 함께 추가'}
G_LABEL={'same':'같은 기수','different':'다른 기수'}


def md(headers,rows):
    return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+''.join('| '+' | '.join(map(str,row))+' |\n' for row in rows)


def records(df):return json.loads(df.to_json(orient='records',double_precision=15,force_ascii=False))


def main():
    verified=json.loads((OUT/'verification.json').read_text());assert verified['passed']
    source=json.loads((OUT/'source_audit.json').read_text())
    raw=pd.read_csv(OUT/'raw_performance.csv');frozen=pd.read_csv(OUT/'frozen_group_metrics.csv')
    gaps=pd.read_csv(OUT/'performance_gaps.csv');adjusted=pd.read_csv(OUT/'adjusted_associations.csv')
    metrics=pd.read_csv(OUT/'extended_metrics.csv');ci=pd.read_csv(OUT/'paired_loss_intervals.csv')
    auc=pd.read_csv(OUT/'group_auc_intervals.csv')
    main_raw=raw[raw.period.eq('2024_2026')&raw.meet.eq('all')&raw.classification.eq('rider_group')].set_index('group')
    primary=frozen[frozen.algorithm.eq('lightgbm')&frozen.model.eq('sections')&frozen.subset.eq('all')]
    new=metrics[metrics.algorithm.eq('lightgbm')&metrics.base.eq('sections')&metrics.subset.eq('all')]
    main_ci=ci[ci.algorithm.eq('lightgbm')&ci.base.eq('sections')&ci.subset.eq('all')]
    performance_table=md(['기수 관계','표본','실제 입상률','실제 우승률','심사 평균','심사~데뷔 간격'],
        [[G_LABEL[g],f'{int(main_raw.loc[g,"n"]):,}',f'{main_raw.loc[g,"top3_rate"]*100:.2f}%',f'{main_raw.loc[g,"win_rate"]*100:.2f}%',
          f'{main_raw.loc[g,"mean_trial_finish"]:.2f}초',f'{main_raw.loc[g,"mean_gap_days"]:.1f}일'] for g in ['same','different']])
    frozen_table=md(['기수 관계','실제 입상률','기존 예상 입상률','입상 AUC','우승 AUC'],
        [[G_LABEL[g],f'{main_raw.loc[g,"top3_rate"]*100:.2f}%',
          f'{primary[primary.group.eq(g)&primary.target.eq("top3")].iloc[0].mean_p*100:.2f}%',
          f'{primary[primary.group.eq(g)&primary.target.eq("top3")].iloc[0].auc:.3f}',
          f'{primary[primary.group.eq(g)&primary.target.eq("win")].iloc[0].auc:.3f}'] for g in ['same','different']])
    new_table=md(['입력','입상 AUC','우승 AUC','입상 Brier','우승 Brier'],
        [[LABELS[a],f'{new[new.addition.eq(a)&new.target.eq("top3")].iloc[0].auc:.6f}',
          f'{new[new.addition.eq(a)&new.target.eq("win")].iloc[0].auc:.6f}',
          f'{new[new.addition.eq(a)&new.target.eq("top3")].iloc[0].brier:.6f}',
          f'{new[new.addition.eq(a)&new.target.eq("win")].iloc[0].brier:.6f}'] for a in LABELS])
    assoc_table=md(['대상','통제','일치-불일치 조정 차이 %p','95% 구간 %p'],
        [['입상' if r.target=='top3' else '우승','지역×연도' if r.fixed_effect=='venue_year' else '같은 경주',
          f'{r.estimate*100:+.2f}',f'[{r.ci_low*100:+.2f},{r.ci_high*100:+.2f}]'] for r in adjusted.itertuples()])
    yearrows=[]
    for year in [2024,2025,2026]:
        z=frozen[frozen.algorithm.eq('lightgbm')&frozen.model.eq('sections')&frozen.target.eq('top3')&frozen.subset.eq(str(year))].set_index('group')
        yearrows.append([str(year)+(' 부분연도' if year==2026 else ''),int(z.loc['same','n']),f'{z.loc["same","top3_rate"]*100:.2f}%',
            int(z.loc['different','n']),f'{z.loc["different","top3_rate"]*100:.2f}%'])
    years_table=md(['기간','일치 표본','일치 입상률','불일치 표본','불일치 입상률'],yearrows)
    rawgap=gaps[gaps.algorithm.eq('lightgbm')&gaps.model.eq('sections')&gaps.subset.eq('all')&gaps.target.eq('top3')&gaps.quantity.eq('raw_gap')].iloc[0]
    residual=gaps[gaps.algorithm.eq('lightgbm')&gaps.model.eq('sections')&gaps.subset.eq('all')&gaps.target.eq('top3')&gaps.quantity.eq('actual_minus_expected_gap')].iloc[0]
    identity=main_ci[main_ci.target.eq('top3')&main_ci.extended.eq('identity')&main_ci.reference.eq('base')&main_ci.loss.eq('brier')].iloc[0]
    aucdiff=auc[auc.target.eq('top3')&auc.group.eq('same_minus_different')].iloc[0]
    continuity=raw[raw.period.eq('2024_2026')&raw.meet.eq('all')&raw.classification.eq('continuity_group')].set_index('group')
    earlier=continuity.loc['last_different_but_seen_same']
    usage=pd.read_csv(OUT/'identity_feature_usage.csv')
    alternative=[]
    fp=pd.read_parquet(OUT/'frozen_predictions_grouped.parquet')
    fp=fp[fp.algorithm.eq('lightgbm')&fp.model.eq('sections')]
    for definition in ['latest_completed_same','any_same_completed']:
        for subset,z in [('all',fp)]+list(fp.groupby('meet')):
            for (target,value),g in z.groupby(['target',definition]):
                alternative.append(dict(definition=definition,subset=subset,target=target,group='same' if value else 'different',
                    wins=int(g.win.sum()),top3_events=int(g.top3.sum()),win_rate=float(g.win.mean()),top3_rate=float(g.top3.mean()),**parent.score(g)))
    alternative=pd.DataFrame(alternative);alternative.to_csv(OUT/'alternative_definitions.csv',index=False)
    publication=f'''# 주행심사와 데뷔전 기수가 같으면 성적과 예측이 달라지는가

2026-10-25. **같은 기수의 원시 입상률은 더 높았다. 그러나 심사기록·기수 실력·간격 등을 고려한 추가 차이는 불확실했고, 기수 일치 정보를 예측모형에 더한 개선도 거의 없었다.** ‘같은 기수라 더 잘 뛰었다’와 ‘같다는 정보가 예측을 더 잘하게 한다’를 구분한 결과다.

## 무엇을 같은 기수로 보았는가

연구59와 같은 국내산 신마8,884두 중 최근2024~2026년 평가2,573두를 중심으로 비교했다. ‘같음’은데뷔 이틀 전까지 확인된 **마지막 합격 주행심사의 실제 완료 기수ID와 데뷔전 실제 기수ID가 같은 경우**다. 이름이나0초 편성 기수로 연결하지 않았다. 전체8,884두에서API 직접8,424건·공식 완료심사 보완460건으로 기수를 확인했고 미확인0건이었다.

## 실제 성적은 얼마나 달랐는가

{performance_table}
같은 기수의 입상률은다른 기수보다{rawgap.estimate*100:+.2f}%p 높았고 날짜 군집95% 구간은[{rawgap.ci_low*100:+.2f},{rawgap.ci_high*100:+.2f}]%p였다. 우승률 차이는약+0.84%p였지만95% 구간에0이 포함됐다. 같은 기수 그룹은심사 기록부터 평균 약0.10초 빠르고 데뷔까지 간격도 짧았다. 따라서 입상률의 원시 차이를 호흡이나 기수 유지의 효과로 그대로 읽을 수 없다.

{years_table}
2024년에는일치 그룹 입상률이 더 낮았고,2025·2026년에는높았다. 시기에 관계없는 일정 가산값을 정하기 어렵다.

기존 심사 모형이예상한 입상률 차이를 뺀‘실제-예상’ 잔차의 일치-불일치 차이는{residual.estimate*100:+.2f}%p,95% 구간[{residual.ci_low*100:+.2f},{residual.ci_high*100:+.2f}]%p로0을 포함했다. 이는고정모형의 집단별 보정 차이이며 순수 기수 효과는 아니다. 별도 회귀에서도같은 경주 또는지역·연도를 맞추고 기존 예측·현재/심사 기수의 과거 실력과간격을 고려했다.

{assoc_table}
같은 경주에서두 기수관계 집단이 함께 있는369경주·2,072출전이 있었다. 조정값이양수인 것은가능한 연관 방향이지만95% 구간이0을 포함하므로 추가효과를확정하거나 효과가없다고 단정하지 않는다. 신마는각 말의첫 출전1행뿐이라 같은 말 고정효과는 넣지 않았다.

## 기존 심사 예측은 어느 집단에서 잘 맞았는가

기수 일치를 아직 입력하지 않은 연구59의고정 구간 모형을 두 집단으로 나누었다.

{frozen_table}
입상 AUC의일치-불일치 차이는{aucdiff.estimate:+.3f},날짜 재표집95% 구간[{aucdiff.ci_low:+.3f},{aucdiff.ci_high:+.3f}]로0을 포함했다. 우승 AUC 차이도0을 포함했다. **기수가 바뀌면 심사 기록의 예측력을 낮춰야 한다는 근거는 확인되지 않았다.** 집단의 실제 입상률과 구성이 달라 AUC·Brier 점추정만으로 어느 기수가 더 낫다고 판단하지 않는다. AUC는적중률이 아니다.

## 일치 정보를 추가하면 예측이 좋아졌는가

기존 모형과 같은 연도 분할·설정을 유지하고 일치1열,심사 기수의 과거 실력,두 묶음의 합을 비교했다. 심사 기수 실력은심사일과 데뷔일 각각T-2 이전365일의실제 경주 성적이며, 현재 데뷔 기수와의차이도 포함했다. 원시ID·이름은 모델 입력이 아니다.

{new_table}
일치만 추가한입상 Brier 차이는{identity.estimate:+.6f},95% 구간[{identity.ci_low:+.6f},{identity.ci_high:+.6f}]였다. 거의0이고 구간에도0이 포함됐다. 우승 예측은기존 구간 모형과 정확히 같았다. 이 설정의 세 연도 우승 모형에서는일치 변수가 실제 분기에 사용되지 않았다. Logistic 모형과 전체시간 모형의민감도에서도 확실한 추가 개선을 확인하지 못했다. 심사 기수 실력을 추가한 경우도일관된 개선은 없었다.

실력 정보에는현재 기수와의 과거 성적 차이가 들어가므로 같음의 간접 단서가 될 수도 있다. 따라서실력과 일치의2×2 비교를 인과적 분해로 읽지 않는다. 고정된 입력·학습설정 안에서의 추가 예측 가치 평가다.

## 말의 이력을 읽을 때

마지막 합격 기수가달랐던1,062두 중{int(earlier.n)}두는다른 완료 심사·연습에서 데뷔 기수가 탔던 기록이 있었다. 나머지994두도일반 일별조교나 비공개 훈련에서 처음 만났다는 뜻은 아니다. ‘최종 합격 기수 불일치’와‘그 말에 기승 경험이 없음’을 같은 뜻으로 쓰지 않는다.

현재는기수 일치·불일치를 심사기록 옆에 보조 정보로 표시할 수 있지만, 일치 시 일괄 가산·불일치 시 심사능력 감산은 채택하지 않았다. 심사 전체·구간 기록과편성을 우선 사용하고 일치 여부의 별도 가산은 유보한다.

자료 종료는서울{source['source_end_by_meet']['서울']}·부산{source['source_end_by_meet']['부산']}이며2026은부분연도다. 기존 연구와 같은 후향 시간순 검증으로,2018~Y-2 학습·Y-1 교정·Y 평가를 유지했다. 실제 데뷔 기수ID는최종 결과에서 확인한 것으로 당시 출전표 확정·기수 교체 시각의 이용 가능성은 미인증이다. 이번 연구를 전향 운영 성능이나 기수 배정의 인과효과로 표현하지 않는다.
'''
    (HERE/'PUBLICATION.md').write_text(publication)
    interpretation=md(['검토','판단'],[
        ['원시 입상률','일치23.63%·불일치20.06%, 일치가 높지만 연도별 방향은 다름'],
        ['추가 성적 연관','기초능력·기수과거실력·간격 통제 후95% 구간에0 포함'],
        ['기존 심사 예측의 신뢰','두 집단의AUC 차이95% 구간에0 포함'],
        ['신규 일치 입력','입상AUC0.803743→0.803840, 확실한 오차 개선 없음'],
        ['실전 처리','보조 이력 표시, 별도 확률/기록 가산과 운영 반영 미채택']])
    details=f'''# 주행심사 데뷔 기수 일치 후속 연구59A

2026-10-25. [이용자용 결론](PUBLICATION.md) · [사전 계획](PLAN.md) · [출처](SOURCES.md) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json).

{interpretation}
## 원천과 분류

연구59의국내산 첫 실제출발8,884두·최근 평가2,573두를 바꾸지 않았다. 선택 사건은동일한T-2 이전365일 내마지막 합격 심사이며공식 완료기수만연결했다. `jockey_id_for_completed_trial`과최종 경주 원문의`jockey_id_raw`를6자리 영숫자 문자열로 비교했고,이름과 편성기수는 쓰지 않았다. 미확인은별도이나 이번 모집단에는0건이었다. 공식 웹 보조460건과API 직접8,424건은신원상태에 남겼다.

양수 시간과완료 기수ID가 있는 다른 주행심사·연습을365일 안에서모아기승 경험을 보조 분류했다. 마지막 합격과마지막 완료 심사는다를 수 있고,일반 일별조교를 포함한 익숙함을 측정한 것은 아니다. 모형 입력의기수 일치는마지막 합격 기준이다.

## 성적과 고정모형 진단

2018~2023 참고분포,2024~2025·2026부분·최근합계,지역별 원시율과기존 total/sections 예측을 보존했다. 실제 입상률·우승률·심사시간·간격·현재/심사 기수의과거 성적을 비교했다. 고정예측의AUC·AP·Brier·log loss·실제-예측 차이를 두집단에서 계산했다. 원시 차이와잔차 차이는날짜 군집 영향함수로95% 구간을 계산했다. 그룹별AUC 불확실성은고정예측을 날짜단위2,000회 재표집한 보조 진단이며 새학습/선택을 하지 않았다.

보조 선형확률 모형의설명변수는일치표식,기존 held-out logit예측·제곱,log1p심사간격,현재 기수의365일 우승/입상/표본,심사 기수의심사일 및데뷔일 시점 과거실력이다. 연속 공변량을표준화하고지역×연도FE 또는경주FE로평균을제거한 최소제곱을 썼다. 같은말FE는고유 말1행이라 쓰지 않았다. 날짜군집분산·군집수/(군집수-1)·n/잔차자유도와t(df=경주일수-1)를 사용했다. 현재 기수와심사 기수의과거 성적이 같은군에서는일치하는것을 전수 확인했다.

{assoc_table}
같은 경주 비교의369개 혼합경주·2,072출전 외단일집단 경주는일치표식의경주내직접대조를 제공하지 않는다. 조정 회귀는후향 관측차이이며 성적차이의인과효과나개별 확률 가산으로 쓰지 않는다.

## 새 입력의 시간순 평가

기존 sections에identity,quality,quality_identity의2×2 비교를 했다. identity는일치1열과공통 인코딩의결측표식이다. quality는심사일·데뷔일 각각T-2 이전365일심사기수의표본·우승/Top3률과현재기수 대비차이다. 우승률은(우승+2)/(출발+20),Top3는(입상+5)/(출발+20)으로완화했다. 신원ID자체는학습하지 않았다. 심사기수의당시자격을미래프로필로소급하지않았고공식완료기수의실제과거경주만 집계했다.

연구59의학습·교정 경계를그대로유지했다. 각Y의2018~Y-2 학습·Y-1 교정·Y 평가이며조건 기준/결측 대입/범주·척도는기존학습기간기준이다. LightGBM200회·lr0.04·leaves7·minleaf80·L2=10·seed20261025·thread1,Platt C100을 고정했다. total+identity 및Logistic sections+identity(C0.3)는민감도다. 기존모델은재학습하지않고새모델30개만 저장했다. 테스트를보고설정·임계값을바꾸지않았다.

{new_table}
지표는전체·연도·지역·일치/불일치로 보존했다. 각추가모형-기본선 및합동-실력정보의차이는같은신마·날짜의paired bootstrap2,000회로 Brier/log loss의95% 구간을계산했다. 모형 추정오차·다중비교는포함하지않는다. 원시집단 AUC 차이와같은 모집단에서정보를더한예측개선은다른 질문이다.

신마의기수 배정은 무작위가 아니다. 심사기록·준비상태·기수수급·마방판단이 남고,현재기수와심사기수의실력차이는일치여부의간접 단서일수있다. 추정값을기수 호흡이나기수변경의순수효과로해석하지 않는다. 예측정보는T-2 사건날짜이지만최종명단/실제기수의당시공개시각은미검증이다.2024~2026은반복연구한과거자료이므로전향시험과구분한다.

## 독립 검증

공식 기수의원문 경주/심사 연결8,884건을 독립SQL로전수 확인했다.40개다른심사창과80개과거기수창을스칼라재계산했다. 동결예측15,438행의확률을원래파일과정확대조했다. 새모델30개의180개예측은저장 LightGBM트리경로 또는로지스틱계수로재현했고최대확률오차{verified['max_probability_replay_error']:.2e}였다. 모든교정 경계·지표128그룹을독립 계산했다. 네조정 회귀도경주/지역연도더미를직접넣은 별도최소제곱과대조해계수오차{verified['max_FE_coefficient_error']:.2e}를 확인했다. 이전연구파일{verified['parent_files_preserved']}개와연구DB SHA256가같다.

{years_table}
## 산출물과 재현

[기수 특징](outputs/rider_features.parquet), [신원 지원](outputs/identity_coverage.csv), [원시 성적](outputs/raw_performance.csv), [고정모형 진단](outputs/frozen_group_metrics.csv), [성적 차이](outputs/performance_gaps.csv), [조정 회귀](outputs/adjusted_associations.csv), [집단AUC 구간](outputs/group_auc_intervals.csv), [신규 예측](outputs/extended_predictions.parquet), [추가 지표](outputs/extended_metrics.csv), [추가 오차 구간](outputs/paired_loss_intervals.csv), [일치변수 사용](outputs/identity_feature_usage.csv), [그림](outputs/rider_match_validation.png), [웹 게시자료](outputs/web_research.json), [중앙59A](../conclusions/59A_DEBUT_TRIAL_JOCKEY_MATCH.md)를 보존했다.

프로젝트root에서연구 경로의 `analyze.py` → `verify.py` → `report.py` → `finalize.py` → `record_inventory.py`를 `.venv/bin/python`으로 실행한다. `PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLCONFIGDIR=/tmp/horse_debut_rider_match_mpl`을권장한다. `common.py`는연구59의인코딩·평가함수만읽어사용하며기존쓰기함수를호출하지않는다. 운영모델·DB·기존연구는변경하지않았다.
'''
    (HERE/'README.md').write_text(details)
    matplotlib.rcParams.update({'font.family':'AppleGothic','axes.unicode_minus':False,'font.size':10})
    fig,axes=plt.subplots(1,2,figsize=(13,5.5))
    x=np.arange(2);actual=[main_raw.loc[g,'top3_rate']*100 for g in ['same','different']]
    expected=[primary[primary.group.eq(g)&primary.target.eq('top3')].iloc[0].mean_p*100 for g in ['same','different']]
    axes[0].bar(x-.17,actual,.33,color='#236C9F',label='실제 입상률')
    axes[0].bar(x+.17,expected,.33,color='#A9BECB',label='기존 예상 입상률')
    axes[0].set_xticks(x,['같은 기수 (1,511두)','다른 기수 (1,062두)']);axes[0].set_ylabel('입상률 (%)');axes[0].set_ylim(0,30)
    axes[0].set_title('기존 모형도 두 집단의 성적 차이를 일부 예상');axes[0].legend()
    for i,(a,b) in enumerate(zip(actual,expected,strict=True)):
        axes[0].text(i-.17,a+.4,f'{a:.1f}%',ha='center');axes[0].text(i+.17,b+.4,f'{b:.1f}%',ha='center')
    for i,addition in enumerate(['identity','quality','quality_identity']):
        r=main_ci[main_ci.target.eq('top3')&main_ci.extended.eq(addition)&main_ci.reference.eq('base')&main_ci.loss.eq('brier')].iloc[0]
        axes[1].errorbar(r.estimate*1000,i,xerr=np.array([[r.estimate-r.ci_low],[r.ci_high-r.estimate]])*1000,fmt='o',capsize=4,color='#236C9F')
    axes[1].set_yticks(range(3)),axes[1].set_yticklabels(['일치만 추가','심사 기수 실력 추가','실력과 일치 함께'])
    axes[1].axvline(0,color='#555555',linestyle='--');axes[1].invert_yaxis()
    axes[1].set_xlabel('입상 Brier 변화 (0.001단위, 음수가 개선)');axes[1].set_title('추가 예측 개선의95% 구간이0을 포함')
    fig.suptitle('심사와 데뷔 기수 일치: 성적 차이와 추가 예측 가치는 구분',fontsize=16,y=.99)
    fig.text(.5,.025,'2024~2026년9월 국내산 신마2,573두 · 마지막 합격 실제 기수ID 기준 · 오른쪽은날짜 paired bootstrap2,000회\n고정된 연구모형 안의 후향 평가 · 배정의 인과효과/전향 운영 성능 미확정',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.12,1,.93));fig.savefig(OUT/'rider_match_validation.png',dpi=170);plt.close(fig)
    dump(OUT/'web_research.json',dict(title='주행심사와 데뷔전 기수 일치',as_of='2026-10-25',status='retrospective_followup_59A',
        publication=publication,raw=records(raw),frozen_metrics=records(frozen),metrics=records(metrics),
        intervals=records(ci),associations=records(adjusted),auc_intervals=records(auc),feature_usage=records(usage),alternative_definitions=records(alternative),
        definition='last completed passing trial official rider ID equals actual debut rider ID',
        new_predictive_improvement_confirmed=False,production_changed=False,prospective_validation=False))
    print('Report, figure and web summary rendered')


if __name__=='__main__':main()

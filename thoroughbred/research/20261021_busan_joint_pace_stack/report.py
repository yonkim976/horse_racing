"""Publish the fixed Busan pace-stack experiment, including negative results."""
import os
os.environ['MPLCONFIGDIR']='/private/tmp/busan_leader_pack_mpl_20261021'
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import experiment as a


LABELS={'B':'기존101개 연구모델','D':'전개·종반 이력 직접 추가',
        'I':'D+말별 독립 전개 예측','J':'D+선두 두수 공동 전개 예측'}


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])


def main():
    assert json.loads((a.O/'verification.json').read_text())['status']=='verified'
    metrics=pd.read_csv(a.O/'finish_metrics.csv',dtype={'window':str})
    diff=pd.read_csv(a.O/'paired_comparisons.csv',dtype={'window':str})
    early=pd.read_csv(a.O/'early_reference_metrics.csv',dtype={'window':str})
    aux=pd.read_csv(a.O/'aux_metrics.csv')
    count_reference=pd.read_csv(a.O/'count_reference_metrics.csv')
    contrasts=pd.read_csv(a.O/'early_reference_contrasts.csv',dtype={'window':str})
    totals=metrics[metrics.window.eq('all')]
    overall=table(['후보','축마 Top3','복승1조합','축+다음3두 복승3조합','축마 우승','기록MAE 초/1000m'],[
        [LABELS[r.model],f'{100*r.axis_top3:.2f}% ({r.axis_top3_hits}/{r.races})',
         f'{100*r.quinella_one:.2f}% ({r.quinella_one_hits}/{r.races})',
         f'{100*r.axis_next3:.2f}%',f'{100*r.win:.2f}%',f'{r.mae:.6f}'] for r in totals.itertuples()])
    annual=[]
    for year in ['2024','2025','2026']:
        for metric,title in [('axis_top3','축마 Top3'),('quinella_one','복승1조합')]:
            g=metrics[metrics.window.eq(year)].set_index('model')
            annual.append([year,title,int(g.races.iloc[0])]+[f'{100*g.loc[n,metric]:.2f}%' for n in a.MODELS])
    annual_table=table(['연도','지표','경주','B 기존101','D 이력직접','I 독립예측','J 공동예측'],annual)
    principal=diff[diff.window.eq('all') & diff.bh_q_primary6.notna()]
    main_contrasts=table(['비교','지표','차이 %p','날짜95%구간 %p','BH q'],[
        [r.new+'−'+r.old,r.metric,f'{100*r.difference:+.3f}',
         f'[{100*r.lower:+.3f}, {100*r.upper:+.3f}]',f'{r.bh_q_primary6:.3f}']
        for r in principal.itertuples()])
    early_rows=[]
    for year in ['all','2024','2025','2026']:
        g=early[early.window.eq(year)].set_index('model')
        ci=contrasts[contrasts.window.eq(year)].iloc[0]
        early_rows.append([year,int(g.loc['H','races']),
          f'{100*g.loc["H","hit_rate"]:.2f}% ({int(g.loc["H","hits"])})',
          f'{100*g.loc["I","hit_rate"]:.2f}% ({int(g.loc["I","hits"])})',
          f'{100*ci.difference:+.2f} [{100*ci.lower:+.2f}, {100*ci.upper:+.2f}]'])
    early_table=table(['연도','전두수 S1F 관측 경주','과거선행빈도 기준','초반예측 I/J','차이·날짜95%구간 %p'],early_rows)
    count_rows=[]
    for year in a.YEARS:
        ref=count_reference[count_reference.year.eq(year)].iloc[0]
        count_rows.append([year,'이전연도까지 전체빈도',f'{100*ref.accuracy:.2f}%',
                           f'{ref.count_brier:.6f}',f'{ref.count_nll:.6f}',f'{ref.count_mae:.3f}두'])
        count_rows.extend([
        [r.year,r.model,f'{100*r.count_accuracy:.2f}%',f'{r.count_brier:.6f}',
         f'{r.count_nll:.6f}',f'{r.count_mae:.3f}두'] for r in aux[aux.year.eq(year)].itertuples()])
    counts=table(['연도','후보','두수1/2/3+ 정확도','두수범주 Brier','두수범주 NLL','예상두수 MAE'],count_rows)
    mixture=table(['연도','독립 I 조건부Top3 Brier','공동 J 조건부Top3 Brier'],[
        [year,f'{aux[(aux.year==year)&(aux.model=="I")].iloc[0].top3_mixture_brier:.6f}',
         f'{aux[(aux.year==year)&(aux.model=="J")].iloc[0].top3_mixture_brier:.6f}'] for year in a.YEARS])

    fig,axes=plt.subplots(1,2,figsize=(11,4.5))
    aa=early[early.window.ne('all')]
    for name,col,label in [('H','#9b9b9b','Past-five frequency'),('I','#287b9b','Early prediction')]:
        g=aa[aa.model.eq(name)];axes[0].plot(g.window,100*g.hit_rate,'o-',label=label,color=col)
    axes[0].set_ylim(50,85);axes[0].set_ylabel('Selected horse in actual first pack (%)')
    axes[0].set_title('Early candidate selection, Busan');axes[0].legend(fontsize=9);axes[0].grid(axis='y',alpha=.15)
    for i,r in enumerate(principal.itertuples()):
        value=r.difference*100
        axes[1].errorbar(value,i,xerr=[[value-r.lower*100],[r.upper*100-value]],
                         fmt='o',color='#287b9b' if r.metric=='axis_top3' else '#bf7a43',capsize=3)
    axes[1].set_yticks(range(len(principal)),[r.new+'-'+r.old+': '+('Anchor Top3' if r.metric=='axis_top3' else 'Quinella1') for r in principal.itertuples()])
    axes[1].axvline(0,color='#777',lw=1);axes[1].set_xlabel('Difference (percentage points); date bootstrap 95%')
    axes[1].set_title('Additional finish-selection benefit');axes[1].grid(axis='x',alpha=.15)
    fig.tight_layout();fig.savefig(a.O/'pace_and_finish_evidence.png',dpi=170);plt.close(fig)

    body=f'''# 부산 선두 묶음 예측과 종반 유지의 성적 모델 연결

2026-10-21 · 연구57J · 시간순 후향 개발 비교 · 운영 변경 없음.

**초반 선두 후보 선정은 단순 과거빈도62.93%에서73.18%로 개선됐다. 그러나 이 예측을 성적 모델에 넣은 추가 효과는 아직 확인하지 못했다. 과거 이력을 직접 추가한 D 대비 독립예측 I의 축마 입상은 동일했고, 공동예측 J는5경주 감소했다. 복승은 I가3경주, J가5경주 늘었지만 주 비교6개의95%구간은 모두0을 포함했다. 2026년에는 기존101개 B 대비 I/J 모두 복승1조합이5경주 줄었다.**

## 범위와 비교 기준

기존 [부산 구간·각질101개 연구](../20261021_busan_all_distance_profiles/README.md)를 기준으로 [S1F 첫 묶음 두수 관측](../20261021_busan_leader_pack_outcomes/README.md)을 사전 예측으로 연결했다. 성적 평가의 대상은 기존과 같은2024~2026-09-18의1,976경주·21,452정상완주 출전, 정상완주6두 이상이다. 운영103/122모델이나 현재 운영 A/B/C를 평가한 결과가 아니다. 비완주 위험을 제거한 성적 평가라는 한계를 유지한다.

전개 예측에는 부산 전출전 명단을 유지했다. 실제 S1F 전두수 관측이 있는 평가1,961경주를 전개 경주지표에 사용했다(2024 718/2025 710/2026 533). 성적 평가의 나머지15경주도 사전 입력으로 예측하고 성적 평가에서 삭제하지 않았다. 보조모형 정답은 통과조 자료가 있는2018년부터, 성적 학습 정답은2017년부터다. 기존 성적 이력2010~2016 warm-up은 유지했다.

기수·조교사 성향/ID와기수교체를 제외했다. 과거 초반·종반 기록·그 편성 대비 우위·위치/각질·거리변화·게이트와상대 과거기록을 사용한다. 과거 첫 묶음에 속했던 출전의 G3F/G1F 기록과입상 이력을 최근5실제출전 슬롯에서 추가했다. 이력은T−2·730일 제한이며 불관측을 오래된 관측으로 보충하지 않는다. 현재 함수율·마체중·rating·배당·실제 구간은 새 전개모형에 넣지 않았다. 기존 B의 현재 중량 등 입력은 그대로 유지했다.

현재 거리·등급·게이트 등은 사후 확정 명단의 대리값으로 당시 공개/변경 시각을 완전 검증한 실전 사전 발행은 아니다. 이미 반복 사용한 과거 기간이므로 독립 미래검증으로 부르지 않는다.

## 실제 구현한 구조

1. 말별 S1F 첫 묶음 소속 확률을 학습했다. 단독 선두1위만의 확률과 다르다.
2. 경주별 첫 묶음 두수1/2/3+ 확률을 따로 학습했다.
3. 독립 소속 확률에서 공집합을 제외한 부분집합 분포 I를 만들었다. 공동 후보 J는 그 분포의 두수범주별 합이 경주 두수모형의 확률과 같도록 재가중한다. 3+ 안의 세부두수는 독립 모형의 조건부 분포를 유지한다.
4. 과거 실제 첫 묶음 소속·두수별 조건부Top3 모형을 학습했다. 예측할 때는 실제 전개를 입력하지 않고 소속0/1×두수1/2/3+ 여섯 시나리오를 각각 예측해 사전 전개분포로 적분했다. 과거 G3F/G1F는 이 모형의 입력이며 물리적 지구력·전술 의도의 직접 정답은 아니다.
5. 이렇게 얻은 말별 소속/단독/두수별 소속·예상두수·조건부Top3 적분과 종반 상호작용을 성적 회귀에 전달했다. 성적의 공동착순 확률이나 복승쌍 자체의 새 공동학습은 하지 않았다.

조건부Top3의 훈련 경주에서는 실제 당시 전개를 조건으로 쓴다. 평가 경주에는 예측분포와 가상 시나리오만 전달하므로 실제 현재 전개를 사전 입력으로 쓰는 방식과 구분된다. 조건부 정답을 관측한 집단의 선택 차이와 보조모형 오차는 남는다.

J는 두수별로만 재가중하므로 **동률을 제외한 말들의 소속확률 순서는 I와 같다.** 이번 구조가 최고 선행 후보를 새로 바꿔주는 것은 아니다. 미래 소속의 모든 상관관계·경합강도·주행경로를 학습한 모형도 아니다. 순위가 같은 말의 부동소수 동률은 원 말별 선행모형 점수와 마번으로 일관되게 처리했고 성적점수/모델은 변경하지 않았다. [수치 동률 원장](outputs/numerical_tie_audit.json).

보조모형은2020~2026 각각 전년까지 학습한21개(말별/두수/조건부Top3)다. 성적 연결용2020~2023 예측도 같은 시간순 외부 예측이다. 2017~2019의 보조예측은NULL로 두고 학습행을 버리지 않았다. 성적 모델9개를 새로 학습하고 기존 B3 3개를 재사용했다. 고정 학습법과나무수이며 시험연도 조기종료·튜닝·결과별 재학습은 없었다.

## 초반 후보와 선두 두수 예측

{early_table}

분모는말수가아닌경주수다. 최고 선행확률마1두가 실제 첫 묶음에 들어왔는지 평가한다. 그 말의 최종 우승/입상이나 첫 묶음 전체 명단을 완전히 맞춘 확률이 아니다. H는과거5전 선행빈도축소기준, I/J는새모형이다. J의후보순서가같아서포함률도같다.

{counts}

두수범주 정확도는약52~58%, 예상두수 오차는약1.0~1.1두다. 과거전체빈도의최빈범주인3+를고르는단순기준의정확도는2024 56.96%/2025 52.54%/2026 58.16%였고,J는세해모두이정확도를넘지못했다. 두수분포를잘맞힌다고표현할근거가약하다. 이추가단순기준은예측결과진단용이며모형선택/재학습에쓰지않았다.

공동화는I대비2024두수범주 확률오차를 줄였지만2025에는 악화했고2026도Brier/NLL이 작게 악화했다. 예상두수MAE만 줄었다고 두수분포 전체를 더 잘 맞혔다고 말하지 않는다.

조건부Top3 적분의 말별 Brier(낮을수록 좋음)도 공동화에서 좋아지지 않았다.

{mixture}

이 값은 전 출전 대상 보조모형의 개별 주변확률이며 말들의 합을3으로 강제한 운영 공동착순 확률이 아니다. [확률구간별 보정표](outputs/calibration.csv)에 예측/실제 빈도를 보존했다.

## 성적 연결 결과

{overall}

B는기존101입력, D는보조모형이쓰는사전이력을직접추가한통제군313열, I/J는같은D에각17개예측표현을추가한330열이다. 원천 정보의 독립 개수와 변환 입력 열 수는 다르며 같은 내용을 표현한 요약·상호작용도 있다. I/J는 동일한 열 구조로 예측값만 다르다. D−B는 게이트/상대 이력 등 여러 입력 묶음의 효과이며 전개예측기 자체의 효과로 읽지 않는다.

성적 목표는기존과같은 `(같은경주 정상완주 중앙초−본인 완주초)×1000/거리` 회귀다. 점수1위의Top3, 점수상위2두의복승1조합, 축과다음3두의복승3조합을평가했다. 같은원문착순의동착을임의정렬하지않고 우승동착/2위동착의복승쌍을구분했다. ‘축마 입상’은예측점수1위말의실제Top3이지우승률이아니다.

## 연도별 결과

{annual_table}

2026은 B의축마입상330/536에서 I/J332/536으로2경주 늘었지만, 복승은66/536에서61/536으로5경주 줄었다. 2024에는 D의축마입상441경주가 I435·J431로 낮아졌다. 2025의복승개선만보고공동화를채택하지않는다.

## 예측 연결만의 추가 효과

{main_contrasts}

주 비교6개는모두0을포함하고BH q도높다. I−D는축마입상62회복/62상실로순증0, 복승37회복/34상실로+3경주다. J−D는축마입상64회복/69상실로−5, 복승35회복/30상실로+5다. J−I는축마입상−5/복승+2경주였다. 공동화가확실히좋아졌다는근거는없다.

B대비J는축마+1.215%p [−0.405,+3.080],복승+0.658%p [−0.457,+1.797]로이쪽도불확실하다. D만으로도B대비축마+1.468%p였으므로 B대비 점추정 상승을 공동전개예측의 공으로 돌리면 안 된다. 기록MAE 개선과 축/복승 적중 개선도 별도다. 축복승3조합은참고로B25.20%→D26.77%→J26.97%였으며 이부지표로주판정을바꾸지않는다. 배당/ROI는평가하지않았다.

![초반 후보 선정과 성적 연결의 증거](outputs/pace_and_finish_evidence.png)

## 판단과 다음 질문

초반 선두 후보를 고르는 연구모형은 단순 빈도보다 유용했다. 현재는그예측을요약입력으로추가하는것만으로축마·복승이안정적으로좋아진다는근거가부족하다. 입력을직접넣은D의변화가상당부분을설명하고,두수모형은연도별교정이흔들리며,공동화는후보순위를바꾸지않는제한이있다.

이번공동분포는초반소속의분포다. ‘선두A가버티면B가함께들어오는가’라는복승쌍/후반동반관계를직접학습한결과는아니다. 다음연구를한다면첫묶음 소속/두수 분포의 교정을확인하고,개별확률요약 전달과쌍별조건부관계의추가가치를구분할필요가있다. 현재결과를본조건만골라추가채택하지않았고, 운영은유지했다.

## 검증·원장

원천15파일SHA/바이트를보존했다.30개저장모형재추론오차0, 독립부분집합전수열거28개와공동소속/단독/기대두수/조건부Top3적분을대조했다. 미래변조의과거입력불변·현재변조의본인이력불변·T−2·전년학습·2017~2019NULL·기수/조교사제외를확인했다. 1,976×4=7,904경주모델의축/복승정답과100개bootstrap대비·BH를별도검산했다. [계획](PLAN.md)과[검증](outputs/verification.json)을함께보관한다.

[성적 전체표](outputs/finish_metrics.csv) · [쌍차이95%구간](outputs/paired_comparisons.csv) · [거리·연도별](outputs/distance_metrics.csv) · [축교체 원장](outputs/changed_axis_races.csv) · [초반기준 대비](outputs/early_reference_metrics.csv) · [초반대비95%](outputs/early_reference_contrasts.csv) · [전개·두수 지표](outputs/aux_metrics.csv) · [전체 말 예측](outputs/aux_predictions.parquet) · [성적 예측](outputs/finish_predictions.parquet) · [입력 계약](outputs/feature_contract.json) · [원천해시](outputs/input_manifest.json) · [용량](outputs/artifact_inventory.json)
'''
    (a.HERE/'README.md').write_text(body)
    publication='''# 부산 선두 묶음 예측과 종반 유지 연결 실험

2026-10-21 · 연구57J · 후향 개발 비교 · 운영 미반영.

실제 첫 통과조의 소속·두수와 종반 G3F/G1F 이력을 연결해 학습했다. 최고 선행확률마가 실제 첫 묶음에 포함된 비율은 과거빈도62.93%→초반모형73.18%(1,961경주)였다. 첫 묶음 전체 명단이나 최종 우승을 맞힌 비율은 아니다.

성적 평가1,976경주에서 기존101입력 B의축마입상58.81%·복승1조합10.78%, 이력직접추가 D는60.27%·11.18%, 독립전개예측추가 I는60.27%·11.34%, 두수공동예측추가 J는60.02%·11.44%였다. D대비J는축−5/복승+5경주였고 주비교95%구간은모두0을포함했다. 2026 J는B대비축+2경주였지만복승−5경주다.

각연도전년까지학습한전개예측만성적입력으로전달했다. 2017~2019예측은NULL로유지했다. 기수·조교사는제외했고새보조21개/성적9개모형을학습했다. 기존101모형3개·원천·DB·운영등록부는유지했다.

공동화는두수범주만재가중해말들의선행순서를바꾸지않는다. 두수확률과조건부Top3의추가개선도연도별로일관되지않았다. 초반후보선정의유용성과최종성적개선을구분하며고정가산/운영교체는채택하지않았다. 성적평가는정상완주조건부이고반복사용한후향자료라독립미래검증이아니다.

[전체 결과](README.md) · [성적표](outputs/finish_metrics.csv) · [대비와 구간](outputs/paired_comparisons.csv) · [검증](outputs/verification.json)
'''
    (a.HERE/'PUBLICATION.md').write_text(publication)
    central=a.R/'conclusions/57J_BUSAN_JOINT_PACE_STACK.md'
    central.write_text(publication.replace('(README.md)',f'(../{a.HERE.name}/README.md)')
                       .replace('(outputs/',f'(../{a.HERE.name}/outputs/'))
    marker='<!-- busan_joint_pace_stack_20261021 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        path=a.R/name
        if marker not in path.read_text():
            link=a.HERE.name+'/README.md' if name=='README.md' else central.name
            with path.open('a') as f:
                f.write(f'\n\n{marker}\n[연구57J 부산 공동전개·종반 유지 연결]({link}): '
                  '초반 최고후보 첫묶음포함62.93→73.18%, 성적1,976경주에서 '
                  '이력직접D 대비 공동J 축−5/복승+5경주·추가효과 불확실. 시간순30모형·운영유지.\n')
    a.save('sources.json',dict(source_end='2026-09-18',source_manifest='input_manifest.json',
         new_external_data=False,new_database_access=False,new_models=30,reused_models=3,
         training_labels_start=2017,auxiliary_labels_start=2018,
         current_actual_pace_at_inference=False,normal_finisher_conditional_finish_evaluation=True,
         independent_future_validation=False,production_changed=False))
    print('Wrote report, central57J, publication summary and figure.')


if __name__=='__main__':main()

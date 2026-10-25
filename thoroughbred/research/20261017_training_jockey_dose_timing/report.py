"""Render predeclared dose/timing tables and a figure from saved estimates."""

import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
OUT=HERE/'outputs'
PERIODS=['2018_2020','2024_2025','2026_partial']
PERIOD_LABEL={'2018_2020':'2018~2020','2024_2025':'2024~2025','2026_partial':'2026 부분연도'}
ROLE_LABEL={'any':'전체 기수','race':'실제 출전 기수'}
LEVEL_LABEL={'0':'0회 표기','1':'1회','2':'2회','3_4':'3~4회','5plus':'5회 이상',
    'd1_2':'1~2일 전','d3_4':'3~4일 전','d5_7':'5~7일 전','d8_14':'8~14일 전','d15_28':'15~28일 전','none':'미확인'}


def md(headers,rows):
    return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+''.join('| '+' | '.join(map(str,r))+' |\n' for r in rows)


def records(frame):
    return json.loads(frame.to_json(orient='records',double_precision=15,force_ascii=False))


def main():
    raw=pd.read_csv(OUT/'raw_performance.csv',dtype={'level':str})
    effects=pd.read_csv(OUT/'adjusted_effects.csv',dtype={'level':str,'reference':str})
    audit=json.loads((OUT/'source_audit.json').read_text())
    verified=json.loads((OUT/'verification.json').read_text());assert verified['passed']
    coverage=pd.read_csv(OUT/'cohort_coverage.csv')
    main_raw=raw[raw.window_days.eq(14)&raw.unit.eq('rows')].copy()
    main_e=effects[effects.window_days.eq(14)&effects.unit.eq('rows')&effects.volume_controls].copy()
    main_raw.to_csv(OUT/'main14_raw.csv',index=False)
    main_e.to_csv(OUT/'main14_effects.csv',index=False)
    key=effects[effects.target.eq('top3')&effects.model.eq('joint_positive')&effects.term.isin(['count_3_4_vs_1','count_5plus_vs_1','last_d5_7_vs_d1_2','last_d8_14_vs_d1_2'])]
    key.to_csv(OUT/'key_sensitivity.csv',index=False)
    supported=main_e[main_e.target.eq('top3')&main_e.bin_support_sufficient&main_e.q.lt(.05)]
    supported.to_csv(OUT/'supported_main_top3_signals.csv',index=False)

    def raw_table(role,dimension,periods):
        levels=['1','2','3_4','5plus'] if dimension=='count' else ['d1_2','d3_4','d5_7','d8_14']
        rows=[]
        for period in periods:
            for meet in ['서울','부산']:
                s=main_raw[main_raw.period.eq(period)&main_raw.rider.eq(role)&main_raw.meet.eq(meet)&main_raw.dimension.eq(dimension)].set_index('level')
                values=[]
                for level in levels:
                    if level not in s.index:values.append('관측 없음');continue
                    row=s.loc[level]
                    values.append(f'{row.top3_rate*100:.2f}% ({int(row.n):,})'+('†' if row.small_bin else ''))
                rows.append([PERIOD_LABEL[period],meet]+values)
        return md(['기간','지역']+[LEVEL_LABEL[x] for x in levels],rows)

    def adjusted_table(kind,periods):
        levels=['2','3_4','5plus'] if kind=='count' else ['d3_4','d5_7','d8_14']
        rows=[]
        for period in periods:
            for role in ['any','race']:
                for meet in ['서울','부산']:
                    s=main_e[main_e.period.eq(period)&main_e.rider.eq(role)&main_e.meet.eq(meet)&main_e.target.eq('top3')&main_e.model.eq('joint_positive')&main_e.kind.eq(kind)].set_index('level')
                    values=[]
                    for level in levels:
                        if level not in s.index:values.append('식별 미지원');continue
                        row=s.loc[level]
                        values.append(f'{row.estimate*100:+.2f} [{row.ci_low*100:+.2f}, {row.ci_high*100:+.2f}]'+
                            (' *' if row.q<.05 and row.bin_support_sufficient else '')+(' †' if not row.bin_support_sufficient else ''))
                    rows.append([PERIOD_LABEL[period],ROLE_LABEL[role],meet]+values)
        return md(['기간','기수 구분','지역']+[LEVEL_LABEL[x] for x in levels],rows)

    interpretation=(HERE/'FINDINGS.md').read_text().strip()
    raw_counts=raw_table('any','count',PERIODS[:2])
    race_counts=raw_table('race','count',PERIODS[:2])
    raw_timing=raw_table('any','last',PERIODS[:2])
    race_timing=raw_table('race','last',PERIODS[:2])
    adj_count=adjusted_table('count',PERIODS[:2])
    adj_last=adjusted_table('last',PERIODS[:2])
    publication=f'''# 조교 기수 기승 횟수와 마지막 기승 시점

2026-10-17. 서울·부산, 경주 전14일의 일반조교를 기준으로 전체 기수와 실제 출전 기수를 나눠 비교했다. ‘횟수’는 원문에 기수로 표기된 일별조교 관측 수다. 같은 날 기수 중복 기승이 없어 이번 자료에서는 기승 횟수와 기승일수가 같다. 조교 중 달린 바퀴 수나 구보·습보 횟수와는 다른 값이다.

{interpretation}

## 횟수에 따른 원시 입상률

3위 이내 입상률이며 괄호는 출전 표본이다. 전체 기수는 여러 기수의 기승을 합친 횟수다. 실제 출전 기수는 공식ID가 출전 기수와 일치하는 기승만 센다.

전체 기수:

{raw_counts}
실제 출전 기수:

{race_counts}
2018~2020년은 역할 미상이 없는 출전으로 비교했다. 실제 출전 기수 분석에는 기수ID 미연결 관측도 없어야 한다. **최근2024~2025년의 횟수는 확인된 기승의 하한이다. 미상 조교일에 기수가 추가로 탔을 수 있어 실제 횟수와 다를 수 있다.** 표의 차이에는 말의 기존 능력·기수 배정·준비 상태의 선택이 포함된다.

## 마지막 기승이 경주 며칠 전이었는가

기수 기승이1회 이상 확인된 출전만 비교한다. 마지막 기승일과 경주일의 달력일 차이다. 최근 미상 조교일에 추가 기승이 있었다면 실제 마지막 기승은 표의 확인 기록보다 더 최근일 수 있다.

전체 기수:

{raw_timing}
실제 출전 기수:

{race_timing}
†는100출전 미만 또는20두 미만 또는10경주일 미만인 구간이다. 해당 구간의 높은 원시율을 최적 시점의 근거로 쓰지 않는다. 기승이 확인되지 않은 출전에는 마지막 날짜를 임의로 넣지 않았다.

## 횟수와 시점을 함께 고려한 비교

기수 기승이 확인된 말들 안에서 같은 말·같은 경주, 최근/직전 성적·출전 기수×연도·조교사·연령·rating·중량·체중·게이트·공백·거리/등급 변화와 전체 조교량을 고려했다. 실제 출전 기수 분석에는 다른 기수의 확인된 기승 횟수도 넣었다. %p는입상률 차이이며 대괄호는개별95% 구간이다. *는사전 지정된 다중비교에서BH q<0.05, †는표본 지원 부족이다.

횟수는1회가 기준이고 마지막 기승 시점도 함께 고려한 값이다.

{adj_count}
시점은마지막1~2일 전이 기준이고 기승 횟수도 함께 고려한 값이다. 음수는해당 시점 그룹의조정 입상률이1~2일 전 그룹보다 낮았다는 뜻이다.

{adj_last}
이는 무작위로 조교 횟수·날짜를 바꾼 효과가 아니다. 더 준비된 말에게 기수가 자주 탔거나, 경주 계획·말 상태에 따라 마지막 기승일이 정해졌을 수 있다. 횟수와 시점의 상호작용을 이용해 최적 조합을 선택한 분석도 아니다.

## 기록과 예측에 활용할 범위

기수 기승 횟수·마지막 확인 간격을 ‘최근 준비 과정에서 관측된 정보’로 보존할 수 있다. 실제 출전 기수의기승과 다른 기수 기승은분리하고, 역할 미상·ID미연결·조교 미관측을 별도로 표시해야 한다. 특정 횟수나 날짜에 일괄 확률 가산·기록 보정을 적용할 근거로 채택하지 않았다.

28일 창과조교량 제외 민감도,2026부분연도 결과도원장과 결과표에 남겼다. 예측에서는당시 공개된 조교 정보와 확정된 출전 기수만 사용해 시간순 추가 성능을 별도 검증해야 한다. 이번에는예측학습·운영 반영을 하지 않았다. 출전자료 종료는 서울{audit['end_by_venue']['서울']}·부산{audit['end_by_venue']['부산']}이다.
'''
    (HERE/'PUBLICATION.md').write_text(publication)
    support_table=md(['기간','구분','창','단위','역할/ID 확인 전','확인 후','기승 양성','제외'],
        [[PERIOD_LABEL[r.period],ROLE_LABEL[r.rider],r.window_days,r.unit,f'{r.eligible_before_role_identity_check:,}',
          f'{r.eligible_after:,}',f'{r.positive:,}',r.excluded] for r in coverage.itertuples()])
    diag=pd.read_csv(OUT/'model_diagnostics.csv')
    max_independent=max((v['absolute_error'] for model in verified['independent_models'] for v in model['contrasts'].values()),default=0)
    details=f'''# 조교 기수 기승 횟수와 시점 연구56A

완료일2026-10-17. [이용자용 결론](PUBLICATION.md) · [핵심 해석](FINDINGS.md) · [사전 계획](PLAN.md) · [출처](SOURCES.md) · [검증](outputs/verification.json) · [추가 검증](outputs/followup_verification.json) · [용량](outputs/artifact_inventory.json).

## 질문과 자료

기수가 조교에 기승한 횟수와 마지막 기승일부터 경주까지의 간격에 따라 성적이 다른지 확인했다. 전체 기수와 실제 출전 기수의 공식ID 일치를 분리했다. 연구56과 같은 서울·부산159,014출전, 경주 전14/28일 일반조교를 사용했다. 경주 당일 조교는 제외했다.

원천은API 기수 역할 표기다. 역사자료의 기수트랙라이더 포함 가능성, 최근 역할 미상, 미연결ID·사건별 충돌 보류를 유지했다. 날짜별 선택 캡처가 완전수집/완전0행이고 수량 불일치가 없어야 한다. 말별 조교0관측은 비교군에서 제외한다. 원천meet3은영남 통합 조교 원천이며 실제 조교 장소를 부산·영천으로 나눈 분석이 아니다.

2018~2020년은 모든 역할이 알려진 출전만 썼다. 실제 출전 기수 모형에는 기수 역할 관측의ID도 모두 연결되고 출전ID가 있어야 한다. 이는 존재 여부만 보았던 연구56보다 엄격하다. 최근2024~2025와2026부분연도는 확인된 횟수의 하한·마지막 확인 시점이다. 실제 마지막 기승은 미상일의 추가 기승으로 더 최근일 수 있다. 표기 전환기2021~2023은 감사에만 남겼다.

{support_table}
## 횟수와 시점

관측된 일별조교1건을 기승1회로 센다. 원천의 같은 말·날짜 기수 중복은0개여서 기승일수와 같다. 전체 조교에는 동일날 복수8건이 있으나 기수 중복은 아니다. 횟수는0·1·2·3~4·5회 이상으로 구분하며 선형 증가를 가정하지 않았다.

마지막 날짜는 해당 기수 관측일의 최댓값이다. 경주까지 달력일 차이를1~2·3~4·5~7·8~14일로 나누고,28일 창에는15~28일을 추가했다. 기승0표기에 가짜 날짜를 넣지 않았다. 공식ID와 원문 기수 역할을 함께 요구하며 이름만 같은 기록은 출전 기수로 연결하지 않았다.

결과를 계산한 뒤 역할/ID 일관성을 추가 감사했다. 원문이 비기수인데 실제 출전 기수ID와 일치하는 경우는2019년 부산3관측뿐이며 최근에는0개다. 원문 역할을 바꾸거나 기본 노출 정의를 수정하지 않았다. [추가 감사](outputs/role_identity_consistency_audit.csv)에 남겼다.

## 모형과 비교 기준

빈도 모형은 전체 지원 표본에서0회 표기 대비각 횟수, 추가로2·3~4·5+회 대1회를 계산했다. 최근0회는 실제 기승 없음이 아니다. 양성 공동 모형은 기승1회 이상인 집단에서 횟수와 마지막 시점을 함께 넣어1회 대비추가 횟수 및1~2일 전 대비다른 시점을 비교했다. 두 모형은 추정 집단과 질문이 다르다. 횟수×시점 상호작용은 추정하지 않았으므로 계수를 더해 최적 조합을 고르지 않는다.

같은 말/같은 경주FE, 출전 기수×연도·조교사FE와 연구56의 공변량을 썼다. 최근5전 상대착순/개수, 직전 상대착순/입상, 공백(log1p), 거리/등급 변화, rating·연령·부담중량·체중·상대 게이트, 지정된 제곱항과 결측표식을 포함했다. 기본 조교량은 조교일수와log1p 총시간·구보·습보다. 실제 출전 기수 모형에는 다른 기수의 확인 횟수0/1/2/3~4/5+더미도 넣었다.14일 조교량 제외와28일 창을 민감도로 보존했다.

같은 경주FE는 거리·함수율·월·등급·편성 등 경주 공통조건을 흡수한다. 같은 말FE는 시간에 고정된 능력을 흡수하지만, 변하는 준비 상태·부상·조교의 질·배정 판단은 완전히 설명하지 못한다. 조교량도 기수 참여와 함께 정해질 수 있어 통제 유무를 다른 조건부 질문으로 해석한다.

우승·3위 이내·상대착순에는 정상착순, 시간차에는 기존4MAD 정제시간 지원 표본만 썼다. 시간차는해당 말의 정제 전체시간-같은 경주 우승마 원시간으로 음수 계수가 더 작은 차이를 뜻한다. 상대착순도 낮을수록 좋다. 결측 결과를 채우지 않았다.

정확 sparse FE 투영과 표준화 공변량을 사용했다. Gram 최대 고유값의1e-12를 절단 기준으로 의사역행렬을 계산하고 대비 식별오차1e-6미만·정상방정식 오차1e-5미만·양의 잔차자유도를 확인했다. 식별 미지원 대비는 별도 보존한다.

말·날짜 각 단일 및말+날짜-교집합 이원 군집분산의 최대를 사용했다. n/잔차자유도와 군집수/(군집수-1)를 적용하고 t자유도는말/날짜 군집수 중 작은 값-1이다. BH q는기간×창×단위×조교량 여부 내두 지역·두 기수 정의·두 모형·네 결과·모든 계획 대비에 적용했다.95% 구간은 개별 비교 구간이다.100출전 미만 또는20두 미만 또는10경주일 미만은 지원 부족으로 표시했다.

## 결과와 검증

{interpretation}

2026부분연도 실제 출전 기수의 원시 성적도 보존했다.

{raw_table('race','count',[PERIODS[2]])}
{raw_table('race','last',[PERIODS[2]])}
공통 특징318,028행은 연구56 원장과 모든 공통 열을 정확 대조했다. 임의64개 출전의 원천 사건을 조회해 횟수·일수·마지막 날짜를 독립 계산했다. 원시{verified['independently_recomputed_raw_groups']}그룹을 별도 필터/평균으로 검산했다. 조정결과{len(effects)}개, 진단{len(diag)}행, 식별 미지원{verified['unidentified_contrasts']}건을 보존했다.2026년 두 지역의 출전 기수 양성 공동 모형은 모든 말/경주 더미를 직접 넣은LSMR로 재계산했으며 최대 대비오차는{max_independent:.2e}다. 횟수와 기승일수로 계산한 추정치·q의 일치 및 문서의 주요 수치도 추가 검증했다.

과거 실제 공개시각과 예측당시 출전 기수 확정 여부는 인증하지 않았다. 미래 프로필의 이름 연결과 사건 당시 역할·공개시점을 구분한다. 최적 횟수·최적 날짜·승부의지·인과효과·예측 개선·새 기록 보정은 미확정이다.

## 산출물과 재현

[특징 원장](outputs/dose_timing_features.parquet), [원시율](outputs/raw_performance.csv), [횟수×시점 표본](outputs/raw_count_timing_grid.csv), [조정결과](outputs/adjusted_effects.csv), [민감도](outputs/key_sensitivity.csv), [진단](outputs/model_diagnostics.csv), [원천 감사](outputs/source_audit.json), [그림](outputs/adjusted_count_timing.png), [웹 게시자료](outputs/web_research.json), [중앙 결론56A](../conclusions/56A_TRAINING_JOCKEY_DOSE_TIMING.md)를 보존했다.

프로젝트root에서 `.venv/bin/python`과 연구 폴더의 경로를 지정해 `analyze.py` → `verify_followup.py` → `report.py` → `finalize.py` → `record_inventory.py` 순서로 실행한다. `PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLCONFIGDIR=/tmp/horse_training_jockey_timing_mpl`을 권장한다. `FINDINGS.md`는 저장된 결과의 해석이며 미래 연구결과를 자동 선택하는 규칙이 아니다. 연구DB·운영 모델·기존 보정은 수정하지 않았다.
'''
    (HERE/'README.md').write_text(details)
    matplotlib.rcParams.update({'font.family':'AppleGothic','axes.unicode_minus':False,'font.size':10})
    fig,axes=plt.subplots(2,2,figsize=(13,9),sharex='col')
    series=[('2018_2020','서울','#1565A0','-'),('2018_2020','부산','#B75A13','-'),
            ('2024_2025','서울','#1565A0','--'),('2024_2025','부산','#B75A13','--')]
    for i,role in enumerate(['any','race']):
        for j,kind in enumerate(['count','last']):
            ax=axes[i,j]
            levels=['1','2','3_4','5plus'] if kind=='count' else ['d1_2','d3_4','d5_7','d8_14']
            for offset,(period,meet,color,style) in enumerate(series):
                s=main_e[main_e.period.eq(period)&main_e.meet.eq(meet)&main_e.rider.eq(role)&main_e.target.eq('top3')&main_e.model.eq('joint_positive')&main_e.kind.eq(kind)].set_index('level')
                x=np.arange(len(levels))+(offset-1.5)*.045;y=[0.];low=[0.];high=[0.]
                for level in levels[1:]:
                    r=s.loc[level];y.append(r.estimate*100);low.append((r.estimate-r.ci_low)*100);high.append((r.ci_high-r.estimate)*100)
                ax.errorbar(x,y,yerr=[low,high],fmt='o',markersize=4,capsize=2,color=color,linestyle=style,
                    linewidth=1,label=f'{PERIOD_LABEL[period]} {meet}')
            ax.axhline(0,color='#555555',linewidth=.8)
            ax.set_xticks(range(len(levels)),[LEVEL_LABEL[x] for x in levels]);ax.grid(axis='y',alpha=.2)
            ax.set_title(ROLE_LABEL[role]+(' · 횟수 (1회 기준)' if kind=='count' else ' · 마지막 기승 (1~2일 전 기준)'))
            ax.set_ylabel('조정 입상률 차이 (%p)')
    axes[0,0].legend(fontsize=9,loc='best',ncol=2)
    fig.suptitle('기승이 확인된 말들 안에서 횟수와 마지막 시점을 함께 고려한 비교',fontsize=16,y=.995)
    fig.text(.5,.02,'경주 전14일 · 같은 말/경주·과거성적·기수·조교사·조교량 통제 · 선은 개별95% 구간\n최근 횟수/시점은 역할 미상을 포함한 확인 기록 기준 · 최적 횟수/날짜 또는 인과효과를 뜻하지 않음',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.08,1,.97));fig.savefig(OUT/'adjusted_count_timing.png',dpi=170);plt.close(fig)
    web=dict(title='조교 기수 기승 횟수와 마지막 시점',as_of='2026-10-17',status='observational_followup_56A',
        raw14=records(main_raw),adjusted14=records(main_e),sensitivity=records(key),publication=publication,
        count_definition='observed daily training rows; identical to unique jockey-ridden dates in this source',
        recent_unknown_roles_present=True,causal=False,prediction_gain_tested=False,production_changed=False,
        end_by_venue=audit['end_by_venue'])
    (OUT/'web_research.json').write_text(json.dumps(web,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('Reports, tables, and figure rendered')


if __name__=='__main__':main()

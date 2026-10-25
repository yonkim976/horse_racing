"""Render research tables, publication text, and a scientific comparison figure."""

import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / 'outputs'
PERIODS = ['2018_2020','2024_2025','2026_partial']
LABELS = {'2018_2020':'2018~2020','2024_2025':'2024~2025','2026_partial':'2026 부분연도'}


def md(headers, rows):
    return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+''.join('| '+' | '.join(map(str,row))+' |\n' for row in rows)


def main():
    raw=pd.read_csv(OUT/'binary_raw_performance.csv')
    split=pd.read_csv(OUT/'raw_performance.csv')
    e=pd.read_csv(OUT/'adjusted_effects.csv')
    source=json.loads((OUT/'source_audit.json').read_text())
    validation=json.loads((OUT/'verification.json').read_text())
    assert validation['passed']
    main=e[e.window_days.eq(14)&e.volume_controls].copy()
    top=main[main.target.eq('top3')&main.term.eq('any_jockey_vs_reference')]
    def eff(period,meet,target,term='any_jockey_vs_reference'):
        return main[main.period.eq(period)&main.meet.eq(meet)&main.target.eq(target)&main.term.eq(term)].iloc[0]
    raw_rows=[]; adj_rows=[]; split_rows=[]; time_rows=[]
    for p in PERIODS:
        for meet in ['서울','부산']:
            a=raw[raw.period.eq(p)&raw.meet.eq(meet)&raw.window_days.eq(14)].set_index('any_jockey')
            yes,no=a.loc[True],a.loc[False]
            r=eff(p,meet,'top3'); w=eff(p,meet,'win'); t=eff(p,meet,'time_gap')
            raw_rows.append([LABELS[p],meet,f'{int(yes.n):,} / {int(no.n):,}',
                f'{yes.win_rate*100:.2f}% / {no.win_rate*100:.2f}%',
                f'{yes.top3_rate*100:.2f}% / {no.top3_rate*100:.2f}%',f'{(yes.top3_rate-no.top3_rate)*100:+.2f}%p'])
            adj_rows.append([LABELS[p],meet,f'{w.estimate*100:+.2f}',f'{r.estimate*100:+.2f}',
                             f'[{r.ci_low*100:+.2f}, {r.ci_high*100:+.2f}]',f'{r.q:.3f}'])
            time_rows.append([LABELS[p],meet,f'{int(t.n):,}',f'{t.estimate:+.3f}초',
                              f'[{t.ci_low:+.3f}, {t.ci_high:+.3f}]',f'{t.q:.3f}'])
            s=split[split.period.eq(p)&split.meet.eq(meet)&split.window_days.eq(14)&split.grouping.eq('split_group')].set_index('group')
            c,o=s.loc['race_jockey_confirmed'],s.loc['other_jockey_only_confirmed']
            delta=eff(p,meet,'top3','race_vs_other_jockey')
            split_rows.append([LABELS[p],meet,f'{int(c.n):,} / {int(o.n):,}',f'{c.top3_rate*100:.2f}% / {o.top3_rate*100:.2f}%',
                f'{delta.estimate*100:+.2f}%p',f'[{delta.ci_low*100:+.2f}, {delta.ci_high*100:+.2f}]',f'{delta.q:.3f}'])
    raw_table=md(['기간','지역','기수 확인 / 미확인 표본','우승률 확인 / 미확인','3위 이내 확인 / 미확인','원시 입상률 차이'],raw_rows)
    adjusted_table=md(['기간','지역','조정 우승률 차이 %p','조정 입상률 차이 %p','입상률 95% 구간 %p','입상률 BH q'],adj_rows)
    split_table=md(['기간','지역','출전기수 / 다른기수 표본','원시 입상률 출전 / 다른','조정 출전-다른 차이','95% 구간 %p','BH q'],split_rows)
    time_table=md(['기간','지역','정제 기록 표본','조정 우승마 시간차','95% 구간 초','BH q'],time_rows)
    sensitivity=e[e.target.eq('top3')&e.term.isin(['any_jockey_vs_reference','race_vs_other_jockey'])].copy()
    sensitivity.to_csv(OUT/'top3_sensitivity.csv',index=False)
    main.to_csv(OUT/'main14_effects.csv',index=False)
    overview=top.merge(raw[raw.window_days.eq(14)&raw.any_jockey][['period','meet','n','top3_rate']].rename(columns={'n':'confirmed_n','top3_rate':'confirmed_top3_rate'}),on=['period','meet'])
    overview=overview.merge(raw[raw.window_days.eq(14)&~raw.any_jockey][['period','meet','n','top3_rate']].rename(columns={'n':'reference_n','top3_rate':'reference_top3_rate'}),on=['period','meet'])
    overview.to_csv(OUT/'overview.csv',index=False)

    publication=f'''# 조교에 기수가 탔던 말은 성적이 더 좋은가?

2026-10-17. 서울·부산, 경주 전14일의 일반조교와 경주 결과를 비교했다. **기수 기승이 확인된 말들의 단순 성적은 더 좋았다. 다만 원래 성적이 좋은 말에게 기수 조교가 더 많이 배정됐고, 이를 고려하면 격차가 크게 줄었다.** 기수 조교 자체가 능력을 올렸다는 인과효과, 승부의지 또는 예측 개선을 확인한 결과는 아니다.

자료에서 ‘기수’는 API 기승자 구분의 기수 표기다. 2018~2020년은 비기수 표기가 충분하여 확인된 기수 기승 있음/없음을 비교할 수 있다. 최근2024~2025년의 대조군은 ‘기수 표기 미확인’이며 서울2,353출전 중2,318출전, 부산3,229출전 중3,200출전에 역할 미상 조교가 있다. **최근 미확인을 실제 기수 미기승으로 읽으면 안 된다.** 역사자료의 기수 표기에 기수트랙라이더가 포함됐을 가능성도 남는다.

원시 성적 차이는 다음과 같다. 2018~2020년 표의 미확인은 명시적 비기수 기록만 있는 대조군이고, 이후 표의 미확인은 역할 미상을 포함한다. 두 대조군을 합쳐 평균 효과로 만들지 않았다.

{raw_table}
같은 말의 기본 능력과 같은 경주 조건을 고정하고, 실제 출전 기수×연도·조교사·최근/직전 성적·연령·rating·중량·체중·상대 게이트·공백·거리/등급 변화·조교량을 고려한 관측 차이다. %p는 확률의 차이다. 95% 구간과 여러 비교를 고려한BH q를 함께 제공한다.

{adjusted_table}
2018~2020년 서울은 원시 입상률 약10.15%p 차이가 조정 후+2.66%p로 줄었고, 부산은 약11.84%p가+1.40%p로 줄었다. 서울의 입상률 연관은28일 창에서도+2.72%p로 유지됐다. 부산의 입상률은95% 구간에0이 포함된다. 최근2024~2025년의 추정은 서울+2.86%p·부산+2.08%p지만, 입상률은 두 지역 모두BH q<0.05를 충족하지 않았다.2026부분연도는 불확실성이 더 크다. 우승률도14일 기본 모형의 모든 기간·지역에서95% 구간에0이 포함된다.

실제 출전 기수가 조교에도 탔는지는 공식ID 일치로 따로 확인했다. 이름만 같은 경우는 연결하지 않았다. ‘다른 기수’는 출전 기수의 기승이 확인되지 않고 다른 기수의 기승만 확인된 그룹이다. 특히 최근 미상 조교일에는 출전 기수가 탔을 가능성까지 배제한 그룹이 아니다.

{split_table}
2018~2020년 부산에서는 출전 기수가 탄 경우가 다른 기수만 확인된 경우보다 조정 입상률+3.47%p였고,28일에서도+3.21%p였다. 그러나 서울과 최근 부산에서 같은 관계가 반복되지 않았다. **‘출전 기수가 직접 조교하면 항상 더 좋다’는 공통 규칙은 만들 수 없다.**

기록으로도 보조 확인했다. 이상치 정제 시간 자료가 있는 출전에서 같은 경주의 우승마와 시간차를 비교한 값이다. 음수는 시간차가 더 작았다는 뜻이며, 조교 때문에 단축된 시간이나 각 말에게 더할 보정값이 아니다.

{time_table}
이제 기록을 읽을 때는 기수 조교를 ‘준비 과정에서 관찰된 정보’로 볼 수 있다. 예를 들어2018~2020년 서울에서 기수 확인 말의 입상률29.36%와 미확인19.22%를 보고 모든 말에게10.15%p를 더하면, 기존 능력과 선택 차이를 중복 반영하게 된다. 조정값2.66%p도 개별 말의 확률 가산값으로 채택하지 않았다.

후속 예측 검증 후보는14/28일 기수 기승 확인·출전 기수 일치·기수 기승일수·전체 조교일 대비 비율이다. 역할 미상과 조교 미관측을 별도 표시하고, 조교량·기존 능력 피처가 있는 기준 모델에 추가했을 때의 시간순 성능을 확인해야 한다. 이번에는 예측 학습·운영 반영·초 단위 보정을 하지 않았다.

2018~2026 출전 원장159,014행을 조회하고, 실제 비교는2018~2020·2024~2025·2026부분연도로 나눴다. 경주 당일 조교를 제외하고, 직전14/28일의 전체 날짜 수집이 확인되며 조교가1일 이상 있는 정상착순 출전만 모형에 포함했다. 자료 종료일은 서울{source['data_end_by_venue']['서울']}·부산{source['data_end_by_venue']['부산']}이다. 정상착순 분석과 정제 시간 분석의 표본은 다르다. 미수집·미상·조교 미관측을0회 비기수 조교로 채우지 않았다.
'''
    (HERE/'PUBLICATION.md').write_text(publication)
    diagnostic=pd.read_csv(OUT/'model_diagnostics.csv')
    details=f'''# 조교 기수 기승과 출전 성적: 관측 연구

완료일2026-10-17. [이용자용 결론](PUBLICATION.md) · [사전 계획](PLAN.md) · [출처](SOURCES.md) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json).

질문은 경주 전에 기수가 직접 조교에 기승했던 말과 그렇지 않은 말 사이에 성적 차이가 있는지, 특히 실제 출전 기수가 조교에도 기승한 경우가 다른 기수만 확인된 경우와 다른지다. 주로빠르기·풍향풍속은 사용하지 않았다. 운영DB·연구DB·기존 채택계수는 수정하지 않았다.

## 모집단과 노출 정의

출전 입력은 기존 신원 검증 원장159,014행, {source['start_date']}~{source['end_date']}, 서울·부산이다. 과거 기수 교체 연구의 `main_eligible` 제한은 쓰지 않았다. 원장의 모든 분류·정상착순 여부를 보존한 뒤, 우승·3위 이내·상대착순에는정상착순158,528행 중 지원 표본을 썼다. 원시 착순의 실격/중지 등486행은 이 성적률에서 제외된다. 시간은 기존4MAD 품질 정제151,074행과 연결된 `quality_time`만 썼으며 결측을0초로 채우지 않았다. 현재 분석의14일 세 기간·두 지역 합계는103,501정상출전이다.

일별 일반조교 `daily_training_rider_linked`를 `training_date_coverage`의 선택캡처와 연결한다. 완전수집이며 inventory 수량 불일치가 없는 관측만 사용한다. 창 전체14/28개 날짜는 `complete_rows` 또는 `complete_zero_rows`로 지원돼야 한다. 실제 조교가 관측되지 않은 정상출전은14일 기준 전체1,053행이며 대조군에서 제외하고 별도 분류했다. 이 자료에서는 전체 날짜 지원이 없는 출전은0행이다.

공식 마번7자리, 원천 지역코드1/3, `race_date-window_days <= training_date < race_date`로 연결한다. 원천meet3은 영남 통합 조교 원천이므로 실제 조교 장소를 부산·영천으로 나눴다고 주장하지 않는다. 경주 지역은 기존 출전 입력의 부산이다. 원천사건 원장5,173,033행 전체를 복제하지 않고318,028행(출전×14/28)의 특징 원장을 저장했다. 원문 역할은 보존하고 당시 자격을2026프로필에서 소급 생성하지 않는다.

- `jockey_confirmed`: 원문 기수 역할1회 이상. 미상 역할일이 섞여 있어도 기수 표기 확인 자체는 양성이다.
- `known_no_jockey`: 조교1회 이상, 기수 표기0회, 모든 관측 역할이 명시적 비기수다. 조교보·조교승인·조교사·기수후보생은 원문 구분 그대로다.
- `no_jockey_label_unknown_roles`: 기수 표기0회이며 역할 미상이1회 이상이다. 실제 미기승으로 분류하지 않는다.
- `no_training`: 해당 말의 조교 관측0회. 완전수집 날짜의 말별0관측도 비기수 조교로 간주하지 않는다.

출전 기수 일치는 원문 기수 역할과 연결 공식ID의 문자열 일치를 함께 요구한다. 이름만 연결된080626 사건31행·충돌 보류1행은 출전 기수 ID 일치로 쓰지 않는다. 그 결과 출전 기수가 확인되지 않은 기수 양성 그룹에는 미연결ID 또는 미상일의 출전 기수 기승 가능성이 남는다.

2018~2020은기수 양성/명시적 비기수만 비교한다. 2021~2023은 원천 표기 전환 기간으로 분류 감사에 남기고 사전 지정된 성적 비교 기간에서 제외한다. 2024~2025와2026은 표기 확인/표기 미확인 비교다. 기간 간 모형 계수의 인과적 변화나 트렌드 차이를 직접 검정하지 않았다.2020 코로나 시기 비정상 경마 일정과2026부분연도라는 한계도 있다.

## 결과와 추정

{raw_table}
노출 양성 그룹은 과거 능력부터 더 좋았다. 2018~2020년 최근5전 상대착순 평균은 서울 양성0.456·대조0.540, 부산 양성0.450·대조0.547이다(낮을수록좋음). 단순 입상률 차이를 조교의 성과로 해석할 수 없는 근거다.

각 지역·기간·창별 선형확률/연속결과 회귀는 `outcome = exposure + horse_FE + race_FE + jockey×year_FE + trainer_FE + covariates + error`다. 우승·입상률의 계수는 확률 차이이며 범위 제한 로짓 예측확률은 아니다. 같은 경주FE가 거리·등급·함수율·월·편성 등 경주 공통조건을 흡수한다. 말FE는 시간에 고정된 능력을 흡수하고 변화하는 상태는 완전히 설명하지 못한다. 말이 더 잘 준비돼 기수가 조교에 참여했을 가능성, 출전계획·조교의 강도/질·부상·작전 등 관측되지 않은 선택은 남는다.

공변량은 최근5전 상대착순 평균/개수, 직전 상대착순·입상, 출전공백(log1p), 거리/등급 변화, rating·연령·부담중량·체중·상대 게이트다. 최근착순·rating·연령·중량·체중·게이트·공백은제곱항을 포함한다. 연속량 결측은0대입+별도 결측표식으로 처리하며 결측 결과를 대입하지 않는다. 기본 조교량 통제는 조교일수, log1p 총시간·구보·습보 횟수이며14일에서조교량 제외 민감도도 보존한다. 조교량은 기수 참여와 함께 정해질 수 있어 조교량 통제 유무를 다른 조건부 질문으로 해석한다.

노출 단일항 모형은기수표기유무, 두항 모형은출전 기수 확인/다른 기수만 확인을 기준군 대비 추정한다. 두항 모형의출전-다른 대비도 직접 계산한다. 우승마 시간차는정제된 해당 말 전체시간-같은 경주 우승마 원시간이며 시간 품질 지원 출전만 추정한다. 상대착순은출전 원장의 `finish_p`(0최상~1최하)를 쓴다.

{adjusted_table}
{split_table}
{time_table}
14일 조교량 제외 때 입상률 계수는2018~2020 서울+3.77%p/부산+2.05%p,2024~2025 서울+4.10%p/부산+2.51%p다. 조교량을고려한 기본값보다 커지므로 어떤 통제조건의 수치인지 항상 병기해야 한다.28일 기본값은2018~2020 서울+2.72%p/부산+1.51%p,2024~2025 서울+3.27%p/부산+1.21%p다.최근 입상률과 출전기수 직접기승의 보편적 우위는 미확정이다. 2024~2025 서울의 시간차 연관은14/28일에서 약-0.166/-0.154초이지만 이는후향적 조건부 연관이며 기록보정 상수로채택하지 않는다.

## 추정 불확실성과 검증

말·경주 이부 그래프의 연결성분을 고려한 정확 sparse FE 투영 후 공변량 최소제곱을 계산했다. 공변량은 투영 전에표준화했다. Gram 고유값 최대의1e-12보다 큰 성분으로 의사역행렬을 만들고, 각 노출대비의 식별 오차<1e-6, 정상방정식 오차<1e-5를 확인했다. 결과 support별 잔차자유도는 n-FE랭크-X랭크다.

대비별 influence에 n/잔차자유도 보정을 적용하고, 말 단일·날짜 단일·말+날짜-교집합 이원 군집 분산 중 최대를 택했다. 군집 개수/(개수-1)를 적용하고 t분포 자유도는말/날짜 군집수 중작은 값-1이다. 표의95% 구간은개별 비교 구간이고, BH q는기간×창×조교량통제 여부 내두 지역·네 결과·네 대비(32검정)에 적용했다. q는여러 사양 전체에대한 전역 보장은 아니며 모형과 자료의 편향을 해결하지 않는다.

모형 진단{len(diagnostic)}행, 조정 결과288개 대비를 보존했다.2026 두 지역의 입상률은 FE 흡수와독립적으로 말/경주 더미를모두 포함한 sparse LSMR로 재계산했고, 최대 대비오차{max(x['absolute_error'] for model in validation['independent_models'] for x in model['contrasts'].values()):.2e}다. 임의60개 출전 창을 원천SQL로 재집계해 조교행/일·기수행·출전기수행을 대조했다. 집계24그룹을 별도 pandas 필터/평균으로검산했다. 전체 날짜범위·분류 분할·기수ID·행수·출처 해시를 확인했다.

원천의 실제 과거 경주전 공개시각은 이번 연구에서 인증하지 않았다. 기수프로필 이름은 미래 스냅샷 연결이며 노출ID와사건 날짜의 의미를 구분한다. 예측검증 전에는특징의 당시 이용 가능성까지 확인해야 한다. 거리·등급별 기수기승 효과, 조교 참여의 인과효과, 새로운 예측모델 성능은이번 범위 밖이다.

## 산출물과 재현

`analyze.py`는 읽기전용 DB 조회와 특징·집계·회귀·검증을 수행한다. `report.py`는이미 저장한결과의 표·그림·게시요약을 만들고 `finalize.py`는중앙 문서 등록과 최종검증, `record_inventory.py`는용량을 기록한다. `.venv/bin/python`으로 순서대로 실행한다. `PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLCONFIGDIR=/tmp/horse_training_jockey_mpl`을권장한다. 기존 참고 DB는복제하지 않는다.

주요 파일은[특징 원장](outputs/training_window_features.parquet),[분류 지원](outputs/classification_coverage.csv),[원시 성적](outputs/raw_performance.csv),[이진 원시율](outputs/binary_raw_performance.csv),[조정 결과](outputs/adjusted_effects.csv),[민감도](outputs/top3_sensitivity.csv),[모형 진단](outputs/model_diagnostics.csv),[원천 감사](outputs/source_audit.json),[과학 그림](outputs/adjusted_top3.png),[웹 게시자료](outputs/web_research.json)다. [중앙 결론](../conclusions/56_TRAINING_JOCKEY_PERFORMANCE.md)에 같은 결론을 모았다.
'''
    (HERE/'README.md').write_text(details)
    (HERE/'SOURCES.md').write_text('''# 조교 기수 기승 성적 연구의 출처

분석일2026-10-17. 인터넷 신규 수집·운영DB 조회는 하지 않았다.

- 연구DB: `thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb`. 읽기전용 `daily_training_rider_linked`·`training_date_coverage` 사용. 원문 API 일별조교·공식ID·캡처원장·날짜별 완전수집 상태는 DB의 provenance 열에 남아 있다. 원시 사건자료를 이번 폴더에 중복 복제하지 않았다.
- [기승자ID 연결](../20261015_daily_training_rider_links_v1/README.md): 공식ID 일치·미연결·충돌보류의 근거.2026프로필은 당시 역할의 근거로 쓰지 않는다.
- [080626 동일 사건 이름 연결](../20261015_daily_training_event_names_v1/README.md): 다비드 이름은 확인됐으나 공식ID는NULL이므로출전기수 일치로쓰지 않는다.
- [기승자 역할 검증](../20261015_training_rider_roles_followup_v1/README.md): API의미상·조교승인·조교보와 홈페이지의기수·기수트랙라이더·주로조교를 임의로같게 취급하지 않는다. 과거 API 기수표기에기수트랙라이더가포함됐을가능성을 남긴다.
- 출전입력: [신원검증159,014행 원장](../20261012_jockey_switch_trainer_intent/outputs/analysis_rows.parquet). 실제 출전기수·말·조교사·날짜·착순과과거 이력. 해당연구의기수교체전용지원제한은이번에쓰지 않았다. 원장에원문파일·항목번호·행키가 있다.
- 정제시간의근거는기존[성별연구 모집단](../20261007_sex_ability_gap/README.md)의151,074품질시간과현재출전입력의 `quality_time` 연결이다. 우승·입상은정상착순 원장으로더넓게평가한다.
- 수치방법 재사용: [기수교체 연구 코드](../20261012_jockey_switch_trainer_intent/analyze.py)의FE 투영·군집분산·BH 함수만가져왔다. 입력준비·학습·원 연구의main은실행하지 않았다.
- [최근 홈페이지 조교인력 표시](../../../docs/TRAINING_WEBSITE_RIDER_EVIDENCE_2026-10-17.md)는API 역할 한계를알리는참고다. 현재출전입력 종료일이후자료를과거노출로합치지 않았다.

입력파일·코드 SHA256와크기는[원천 감사](outputs/source_audit.json), 실제사용역할은[역할분포](outputs/source_role_audit.csv),전체날짜지원은[날짜감사](outputs/source_calendar_coverage.csv)에 보존했다. 기존DB 해시는이전연구문서의과거해시를인용하지않고이번 실행시의파일을직접 계산했다.
''')
    matplotlib.rcParams.update({'font.family':'AppleGothic','axes.unicode_minus':False,'font.size':11})
    fig,axes=plt.subplots(1,2,figsize=(13,5.5),sharey=True)
    combinations=[(p,m) for p in PERIODS for m in ['서울','부산']]
    for ax,term,title in zip(axes,['any_jockey_vs_reference','race_vs_other_jockey'],['기수 표기 확인 - 대조군','출전 기수 확인 - 다른 기수만 확인']):
        for i,(p,m) in enumerate(combinations):
            r=eff(p,m,'top3',term)
            ax.errorbar(r.estimate*100,i,xerr=np.array([[r.estimate-r.ci_low],[r.ci_high-r.estimate]])*100,
                fmt='o',capsize=4,color='#1967A3' if m=='서울' else '#C66B22')
        ax.axvline(0,color='#555555',linewidth=1,linestyle='--')
        ax.set_title(title,pad=15);ax.set_xlabel('조정 3위 이내 입상률 차이 (%p)')
        ax.grid(axis='x',alpha=.2)
    axes[0].set_yticks(range(len(combinations)),[f'{LABELS[p]} · {m}' for p,m in combinations]);axes[0].invert_yaxis()
    fig.suptitle('경주 전14일 기수 조교 기승 표기와 성적의 관측 연관',fontsize=16,y=.99)
    fig.text(.5,.025,'점: 같은 말·경주·기수·조교사·과거성적·조교량 통제 추정 / 선: 개별 95% 구간\n2018~2020 대조군: 명시적 비기수 · 최근 대조군: 미상 역할 포함 · 인과/예측 효과 미확정',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.11,1,.93));fig.savefig(OUT/'adjusted_top3.png',dpi=170);plt.close(fig)
    summary=dict(title='조교 기수 기승 확인과 출전 성적',as_of='2026-10-17',
        status='observational_research_candidate',source_start_date=source['start_date'],source_end_by_venue=source['data_end_by_venue'],
        classification='historical confirmed jockey/non-jockey; recent confirmed/not-confirmed with unknown roles',
        causal=False,prediction_gain_tested=False,production_changed=False,
        raw14=raw[raw.window_days.eq(14)].to_dict(orient='records'),main14=main.to_dict(orient='records'),
        split_raw14=split[split.window_days.eq(14)&split.grouping.eq('split_group')].to_dict(orient='records'),
        sensitivity=sensitivity.to_dict(orient='records'),publication=publication)
    (OUT/'web_research.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('Reports and plot rendered')


if __name__=='__main__':
    main()

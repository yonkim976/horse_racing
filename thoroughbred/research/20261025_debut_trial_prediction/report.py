"""Render verified debut prediction findings without operational promotion."""

import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from prepare import HERE,OUT,dump

LABELS={'context':'기초 정보','trial_admin':'심사 이력·조건','total':'전체시간·착순 추가',
        'sections':'구간·전개 추가','trial_focused':'심사 중심'}
ORDER=list(LABELS)


def md(headers,rows):
    return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+''.join('| '+' | '.join(map(str,row))+' |\n' for row in rows)


def records(df):return json.loads(df.to_json(orient='records',double_precision=15,force_ascii=False))


def main():
    verified=json.loads((OUT/'verification.json').read_text());assert verified['passed']
    audit=json.loads((OUT/'source_audit.json').read_text())
    metrics=pd.read_csv(OUT/'metrics.csv');ci=pd.read_csv(OUT/'paired_loss_intervals.csv')
    high=pd.read_csv(OUT/'high_group.csv');absolute=pd.read_csv(OUT/'same_high_group_intervals.csv')
    single=pd.read_csv(OUT/'single_time_auc.csv');bands=pd.read_csv(OUT/'heldout_time_bands.csv')
    selection=pd.read_csv(OUT/'debutant_selection.csv')
    main=metrics[metrics.algorithm.eq('lightgbm')&metrics.subset.eq('all')].copy()
    baseline=main[main.model.eq('context')&main.target.eq('top3')].iloc[0]
    full=main[main.model.eq('sections')&main.target.eq('top3')].iloc[0]
    bwin=main[main.model.eq('context')&main.target.eq('win')].iloc[0]
    simple=single[single.subset.eq('all')&single.target.eq('top3')].set_index('feature').auc
    h=high[high.algorithm.eq('lightgbm')&high.subset.eq('all')&high.model.eq('sections')&high.target.eq('top3')].iloc[0]
    main_rows=[]
    for model in ORDER:
        t=main[main.model.eq(model)&main.target.eq('top3')].iloc[0]
        w=main[main.model.eq(model)&main.target.eq('win')].iloc[0]
        main_rows.append([LABELS[model],f'{t.auc:.3f}',f'{w.auc:.3f}',f'{t.brier:.5f}',f'{w.brier:.5f}'])
    main_table=md(['입력','입상 AUC','우승 AUC','입상 Brier','우승 Brier'],main_rows)
    yearly=[]
    for year in [2024,2025,2026]:
        base=metrics[metrics.algorithm.eq('lightgbm')&metrics.subset.eq(str(year))&metrics.model.eq('context')&metrics.target.eq('top3')].iloc[0]
        advanced=metrics[metrics.algorithm.eq('lightgbm')&metrics.subset.eq(str(year))&metrics.model.eq('sections')&metrics.target.eq('top3')].iloc[0]
        yearly.append([str(year)+(' 부분연도' if year==2026 else ''),f'{advanced.n:,}',f'{base.auc:.3f} → {advanced.auc:.3f}',f'{base.brier:.5f} → {advanced.brier:.5f}'])
    year_table=md(['평가연도','신마 수','입상 AUC 기초 → 전체','입상 Brier 기초 → 전체'],yearly)
    high_rows=[]
    for model in ['context','total','sections','trial_focused']:
        r=high[high.algorithm.eq('lightgbm')&high.subset.eq('all')&high.model.eq(model)&high.target.eq('top3')].iloc[0]
        high_rows.append([LABELS[model],f'{r.selected_n:,}',f'{r.selected_share*100:.1f}%',
            f'{r.selected_top3_rate*100:.2f}%',f'{r.selected_win_rate*100:.2f}%'])
    high_table=md(['입상 모형의 높은 평가 그룹','표본','전체 중 비중','실제 입상률','같은 그룹 우승률'],high_rows)
    time_rows=[]
    for band in ['<=62','62~63','63~64','64~65','>65']:
        row=[{'<=62':'62초 이하','62~63':'62초 초과~63초','63~64':'63초 초과~64초','64~65':'64초 초과~65초','>65':'65초 초과'}[band]]
        for meet in ['서울','부산']:
            r=bands[bands.meet.eq(meet)&bands.time_band.eq(band)].iloc[0]
            row.extend([f'{r.n:,}',f'{r.top3_rate*100:.2f}%'])
        time_rows.append(row)
    time_table=md(['마지막 합격 전체시간','서울 표본','서울 입상률','부산 표본','부산 입상률'],time_rows)
    stat=ci[ci.algorithm.eq('lightgbm')&ci.subset.eq('all')&ci.target.eq('top3')&ci.loss.eq('brier')]
    delta=stat[stat.extended.eq('sections')&stat.baseline.eq('context')].iloc[0]
    extra=stat[stat.extended.eq('sections')&stat.baseline.eq('total')].iloc[0]
    confidence=absolute[absolute.model.eq('sections')&absolute.target.eq('top3')].iloc[0]
    sel=selection[selection.algorithm.eq('lightgbm')&selection.subset.eq('all')&selection.model.eq('sections')&selection.target.eq('top3')].iloc[0]
    # A single chosen-debutant policy: use Top3 predictions for both actual outcomes.
    pred=pd.read_parquet(OUT/'predictions.parquet')
    chosen=[]
    for model in ['context','total','sections','trial_focused']:
        z=pred[pred.algorithm.eq('lightgbm')&pred.model.eq(model)&pred.target.eq('top3')]
        z=z.groupby('race_key').filter(lambda g:len(g)>=2)
        best=z.sort_values(['race_key','p','horse_id'],ascending=[True,False,True]).groupby('race_key').head(1)
        chosen.append(dict(model=model,races=len(best),top3_events=int(best.top3.sum()),top3_rate=float(best.top3.mean()),
            wins=int(best.win.sum()),win_rate=float(best.win.mean())))
    chosen=pd.DataFrame(chosen);chosen.to_csv(OUT/'same_debutant_choice.csv',index=False)
    publication=f'''# 주행심사로 신마의 첫 경주를 얼마나 예측할 수 있는가

2026-10-25. **주행심사 결과에는 신마 데뷔전의 우승·입상을 구분하는 뚜렷한 예측 신호가 있었다. 핵심 정보는 전체시간이고, 구간기록은 보완 정보로 볼 수 있다.** 서울·부산 국내산 첫 출전 신마 중2024~2026년 {int(full.n):,}두를 과거 연도로 학습·교정한 뒤 평가한 결과다.2026년은9월까지의 부분연도이며 전향적 실시간 검증은 아니다.

## 얼마나 구분했는가

평가 신마 전체의 실제 입상률은{baseline.event_rate*100:.2f}%, 우승률은{bwin.event_rate*100:.2f}%였다. AUC는입상마를 비입상마보다 높게 평가하는 구분력으로,0.5가 무작위 수준이고1에 가까울수록 좋다. AUC0.80을80% 적중률로 읽으면 안 된다. Brier는예측확률과0/1 결과의 제곱 오차로 낮을수록 좋다.

{main_table}
기초 정보에는 출전 조건과 T-2까지의 상대말·기수·조교사 이력이 들어간다. 심사 이력·조건 단계에는심사 횟수·실패·간격·함수율·심사 체중 등이 들어가지만 기록·착순은 없다. 전체시간 단계에는마지막/최고 전체시간·심사착순·회차 상대시간·과거 조건 기준 잔차를 추가한다. 구간 단계에는출발200·중간200/400·막판200·G3F 등과 상대속도·위치 변화를 추가한다. ‘심사 중심’은출전 거리·게이트·편성·인적 과거성적을 제외하고 심사 정보와 말 연령·성별·경주지역만 사용한 비교다.

전체 입력의 입상 Brier는기초 대비{(1-full.brier/baseline.brier)*100:.1f}% 감소했다. 날짜 단위 재표집에서차이는{delta.estimate:+.5f},95% 구간[{delta.ci_low:+.5f},{delta.ci_high:+.5f}]로 개선 방향이었다. 우승 예측도함께 개선됐다. 단순한 신마 집단의 성적 차이를 계산한 결과와 달리, 이후 연도의 정답을 학습에 쓰지 않고 예측 오차를 비교한 결과다.

{year_table}
## 높게 평가한 신마는 실제로 얼마나 잘 뛰었는가

각 평가연도의 직전 교정연도에서 예측 상위20% 경계를 고정하고, 그 경계 이상인 평가연도 신마를 모았다. 평가연도 결과를 보고 경계를 고르지 않았다. 아래 우승률과 입상률은모두 같은 입상 모형 선택 그룹의 결과다.

{high_table}
구간까지 사용한 모형의 높은 평가 그룹은{int(h.selected_n):,}두 중{int(h.selected_top3):,}두 입상({h.selected_top3_rate*100:.2f}%),{int(h.selected_wins):,}두 우승({h.selected_win_rate*100:.2f}%)이었다. 입상률의 날짜 군집95% 구간은[{confidence.ci_low*100:.1f},{confidence.ci_high*100:.1f}]%다. 이는 여러 경주에 걸친 신마의 점수 구분이며, 매 경주 한두를 골랐을 때의 적중률과 다르다.

심사 연결 신마가2두 이상인{int(sel.races):,}경주에서 가장 높은 입상 예측의 신마1두를 고르면 실제 입상률은{sel.selected_rate*100:.2f}%였다(기초 정보 모형32.85%). 이는신마들 사이에서 고른 성적이며 경험마까지 포함한 전체 출전마의 축 선택 성능은 아니다.

## 전체시간과 구간 중 무엇이 중요했는가

마지막 합격 전체시간만 빠른 순으로 읽어도 입상 AUC는{simple['finish']:.3f}이었다. 출발200만의AUC는{simple['early']:.3f}, 마지막200은{simple['late']:.3f}였다. 심사 전체시간이 가장 강한 단일 기록 신호였으며, 빠른 출발 하나만으로 능력을 판단하는 근거는 약했다.

{time_table}
이 표는2024~2026년 원시 분포다.62초 이하 집단은서울27두·부산35두로 작고, 함수율·연령·심사 전개를 맞춘 인과 비교가 아니다. 빠른 기록이 좋은 능력의 신호일 수 있지만, 느리게 통과한 말을 모두 낮은 능력으로 확정할 수는 없다.65초 초과에서도 입상한 말이 있었다.

전체시간 단계에 구간을 추가한 입상 Brier 차이는{extra.estimate:+.5f},95% 구간[{extra.ci_low:+.5f},{extra.ci_high:+.5f}]로0을 포함했다. 우승 Brier에는 작은 개선 신호가 있지만 log loss와 지역별 결과는 일률적이지 않았다. **심사 전체시간·조건의 활용 가치는 확인했지만, 구간 추가의 확실한 개선까지 같은 강도로 주장하지 않는다.**

## 어느 신마까지 적용되는가

2010년 이후 모든 실제 출발 이력에서 서울·부산의 국내산 첫 출발8,929건을 확인하고, 데뷔 전365일 안에 신마 사유 합격 이력이 있으며 마지막 합격 전체시간이 유효한8,884건을 분석했다. 최근 평가 표본은서울1,401두·부산1,172두다. 외산마1,361두는 해외 경력을 확인하지 못해 국내 첫 출전 분포만 남기고 주 성능 표본에서 제외했다. 실제 출발 후 중지·실격된 첫 출전도 실패로 유지했다.

주행심사는경주 이틀 전까지의 결과만 사용했다. ‘마지막 합격’이 재심 사유일 수도 있지만 이전 신마 합격과 국내 첫 출전 이력을 함께 확인했다. 이전 국내 다른 지역 출전도 첫 출전 판별에 반영했다.2024/2025/2026 각각2018~Y-2 학습, Y-1 확률교정, Y 평가이며, 현재 결과·배당·당일 체중·rating·함수율은 예측 입력에 넣지 않았다. 과거 이력 특징에는평가연도라도 T-2 이전에 이미 끝난 다른 경주의 결과가 들어갈 수 있다.

자료 종료는서울{audit['starts_end_by_meet']['서울']}·부산{audit['starts_end_by_meet']['부산']}이다. 출전 명단·거리·게이트 등의기초 조건은 최종 결과의 메타데이터를 출전표 대용으로 사용했으며, 실제 당시 출전표·변경 시각·심사 공개시각은 미인증이다. 따라서이는 보존 자료의 후향 시간순 검증이고 실제 운영 모델 개선이나 당일 예측 발행을 완료한 결과는 아니다.

신마를 평가할 때는 심사 전체시간에 함수율·간격·전개와 출전 편성을 함께 붙이는 것이 유용하다. 심사1000m 시간을 실전1200m 시간으로 비례 확대하거나 심사 기록점수를 고정 우승확률로 바꾸지는 않는다. 실제 예측 반영 전에는당시 공개 입력으로 전향 검증이 필요하다.
'''
    (HERE/'PUBLICATION.md').write_text(publication)
    sensitivity=metrics[metrics.algorithm.eq('logistic')&metrics.subset.eq('all')]
    sensitiv_table=md(['모형','대상','AUC','Brier'],[[LABELS[r.model],r.target,f'{r.auc:.3f}',f'{r.brier:.5f}'] for r in sensitivity.itertuples()])
    details=f'''# 주행심사와 국내산 신마 첫 출전 예측 연구59

2026-10-25. [게시 요약](PUBLICATION.md) · [사전 계획](PLAN.md) · [출처](SOURCES.md) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json).

## 질문과 결론

주행심사 전체시간과 구간·전개가 첫 출전의 우승·3위 이내 예측에 추가 가치를 주는지 평가했다. 입상AUC는기초0.682→전체시간0.795→구간0.804, 우승AUC는0.696→0.802→0.808이었다. 입상 Brier는0.16150→0.13645→0.13537이다. 심사 전체시간의 추가 가치는 확인됐지만 구간의 추가 입상 개선 구간은0을 포함했다. 운용 채택과 수익 평가는 하지 않았다.

## 자료와 대상

읽기전용 연구DB의 확인된 경주 결과{audit['raw_runner_rows']:,}행과 심사61,777행을 사용했다. 실제 출발은정상착순 및91실격·92주행중지이고,0·93~95 취소/제외는 실제 출발로 세지 않았다.2010년부터 공식 말ID로 첫 출발을 찾은 뒤2018년 이후 서울·부산 국내산을 주 표본으로 삼았다. 영천12경주도 앞선 국내 출전 판별과 관계자 과거 이력에는 포함하되 영천 데뷔 예측은 평가하지 않았다. 해외 출전 이력은 없으므로 외산마의 국내 첫 출발을 생애 첫 출발로 표현하지 않았다.

전체 국내 첫 출전10,290두 중 국내산8,929두, 외산1,361두다. 국내산45두는365일 안 신마 사유 합격 지원이 없어 주 분석에서 제외됐다. 나머지8,884두는 마지막 합격 전체시간이 유효했다. 구간 품질 때문에 이 표본을 더 줄이지 않았고 과거6행의구간 결측은 별도 표시·대입했다. 최근 평가2,573두의기본 독립구간은 모두 유효했다. 주 표본 중 첫 출발의중지/실격30건도0정답으로 유지했다. 말마다1행이라 학습·교정·평가의말ID가 겹치지 않는다.

심사는resolved_horse_id와 확인된 원천ID를 사용하고, 같은말의 T-2까지365일 안에 신마 사유 합격이 있어야 한다. 마지막 합격을 날짜·회차·관측ID 순으로 고른 뒤 전체시간 품질을 확인했다. 시간 좋은 과거 심사를 마지막 심사로 대체하지 않았다. 마지막 합격 사유는신마8,377건과 재심 등507건이다. 실제 간격은6~120일이었으나365일은연구 창으로만 사용했으며 공식 유효기간을 주장하지 않는다. 지역과 거리는 기존 검증 자료의서울·부산1000m 심사 범위다. 원문·신원·장소 검토 뷰를 연결했고 이름만으로 말을 합치지 않았다.

전체시간50~100초, S1F10~30, G3F25~60, G1F8~25, 독립중간200은8~30, 중간400은16~50초의 이전 품질 기준을 승계했다. 독립 구간은S1F / T-G3F-S1F / G3F-G1F / G1F이며1000m를200+200+400+200으로 나눈다. 부산 G400은순서·양수 범위를 확인한 별도 중첩 구간이다. fs200=20T/G1F, fs600=60T/G3F이고 최적 효율값을 뜻하지 않는다. 꼬리 결과를 보고 심사 기록을 추가 제거하지 않았다.

## 입력과 시간 경계

현재 경주의 착순·전체/구간시간·배당·당일 체중·rating·함수율을 입력에서 제외했다. 문서에‘전체시간’이라는 이름으로 들어가는값은심사 전체시간이다. 말ID·이름은 매칭용이며 모델 입력이 아니다. 출전표 대용의지역·월·연령·성별·원산지·거리·등급·게이트·최종 실제 출발두수와 T-2 상대말·기수·조교사 이력으로기초 모형을 만들었다. 최종 명단과기수 변경이 당시 T-2에 확정됐는지는 인증하지 않았다.

상대말은전체 실제 출발자를 남기고 자기 제외 최근5전(730일·T-2)의 입상/상대착순, 경험마수와 무경험수·최고 상대 성적을 계산했다. 기수·조교사는365일·T-2의우승/입상과표본을 사전 강도로 완화했다. 평가연도의이미 끝난 과거 경주가 이 이력에 들어가는 것은허용하되 현재/미래 사건은 제외한다. 상대말의 당일 성적은 쓰지 않는다. 전체 편성에서의 순위 확률이나 확률합3을 강제한 공동 모형은 아니다.

입력 묶음은[특징 계약](outputs/feature_contract.json)과 모델별schema에 보존했다. context → trial_admin → total → sections를 같은 표본에서 순차 비교하고 trial_focused를 별도 비교했다. total은순수 전체시간1열만의 효과가 아니라 전체/최고시간·착순·회차 상대기록·과거 조건 잔차의 추가 묶음이다. trial_admin에는심사 체중·간격·실패 등도 있어 심사 없이의기초와 차이가 난다.

각 평가연도Y에 이전Y-2년 말까지의 신마 사유 합격 심사로 지역·함수율구간·월·심사 나이·성별·부담중량에 대한Ridge(alpha10)를 학습했다. 전체·네 독립 구간의조건부 잔차를 계산했고 최적 능력/par나기존 실전 보정률로 표현하지 않았다. 입력 대입·표준화·범주 목록도 분류모형 학습기간에서만 결정했다.

## 학습과 평가

2018~Y-2 학습, Y-1 별도확률교정, Y 테스트로2024·2025·2026을 평가했다. 고정 LightGBM200회·학습률0.04·leaves7·minleaf80·L2=10·seed20261025·thread1이고 테스트 조기종료·탐색이 없다. 각우승/입상을별도 binary로 학습했으며 확률 사이의 순서/합 제약을 강제하지 않았다. Platt 교정은직전 연도에서logit을1변수로 하는LogisticRegression(C100)이며 테스트는사용하지 않았다. context/sections의LogisticRegression(C0.3)도 고정 민감도다.

{main_table}
{year_table}
{sensitiv_table}
지표는신마1두 동일가중으로 AUC·AP·Brier·log loss를 계산했다. 주 대비의날짜 단위paired bootstrap2,000회는같은 날짜를두 모형에서같이 재추출하고 해당 날짜의신마수를 유지한다. 학습된 모형에 조건부인95% 구간이며 재학습 불확실성·다중비교는 반영하지 않는다. 전체·연도·지역별 결과를모두 보존했다. 평가연도 상위20%를사후 고르지 않고 교정연도상위20% 예측 경계를 사용했다. 고평가 그룹의두 결과와95% 구간은모두 같은 입상 모형의 선택집단이다.

## 검증과 한계

주 표본8,884두의국내 선행 실제출발0건과 마지막 합격을 독립 SQL로 전수 확인했다.80두의경주·심사 원문을 직접 대조하고40개 상대말 이력·40회 인적 이력을스칼라 조회했다. 이전 조건 기준180개 값을계수·인코딩에서 독립 재계산했다.42개 모형의252개예측은LightGBM트리경로 또는로지스틱계수를 직접 계산해 재현했으며 최대확률오차는{verified['max_probability_replay_error']:.2e}다. 모든교정 경계와지표84그룹을 독립 계산했고 DB 해시가 같음을 확인했다.

예측력을 보인 것은조건부 시간순 후향 평가다. 과거 연도는프로젝트의 다른 연구에서반복 사용됐고 완전히 미사용인신규 전향 표본이 아니다. 실제 출전표와심사 공개시각·철회/교체의시점은 미검증이다. 신마1두의우승/입상 확률과 모든말 중축 선택·마권수익은다른 문제다. 심사 없는신마45두, 외산마, 제주·영천의데뷔 결과에같은 성능을적용하지 않는다. 실전거리별 시간을심사1000m에서 비례 환산하거나고정 보정값을만들지 않았다.

## 산출물과 재현

[코호트](outputs/debut_cohort.parquet), [지원](outputs/coverage.csv), [예측](outputs/predictions.parquet), [지표](outputs/metrics.csv), [날짜 군집구간](outputs/paired_loss_intervals.csv), [고평가 그룹](outputs/high_group.csv), [같은 그룹 불확실성](outputs/same_high_group_intervals.csv), [신마 중1두 선택](outputs/same_debutant_choice.csv), [보정표](outputs/calibration.csv), [단일 기록](outputs/single_time_auc.csv), [모형 원장](outputs/model_manifest.json), [그림](outputs/prediction_validation.png), [웹 게시자료](outputs/web_research.json), [중앙59](../conclusions/59_DEBUT_TRIAL_PREDICTION.md).

프로젝트root에서 `.venv/bin/python`으로연구 경로의 `prepare.py` → `model.py` → `verify.py` → `report.py` → `finalize.py` → `record_inventory.py`를 실행한다. `PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MPLCONFIGDIR=/tmp/horse_debut_trial_mpl`을 권장한다. 생성한 모델은연구 폴더에만 남기며 운영 레지스트리에 등록하지 않는다.
'''
    (HERE/'README.md').write_text(details)
    # All curves/bars use the fixed primary model, rather than choosing the best test algorithm.
    matplotlib.rcParams.update({'font.family':'AppleGothic','axes.unicode_minus':False,'font.size':10})
    fig,axes=plt.subplots(1,2,figsize=(13,5.5))
    aucs=[main[main.model.eq(m)&main.target.eq('top3')].iloc[0].auc for m in ORDER]
    bars=axes[0].bar(range(len(ORDER)),aucs,color=['#9A9A9A','#6D8C99','#2678B2','#14507A','#77A48A'])
    axes[0].set_xticks(range(len(ORDER)),['기초','심사 조건','전체시간','구간 추가','심사 중심'])
    axes[0].set_ylim(.5,.9);axes[0].set_ylabel('입상 AUC');axes[0].set_title('평가 신마2,573두의 구분력')
    for bar,v in zip(bars,aucs,strict=True):axes[0].text(bar.get_x()+bar.get_width()/2,v+.007,f'{v:.3f}',ha='center')
    models=['context','total','sections','trial_focused']
    values=[];lo=[];hi=[]
    for m in models:
        r=absolute[absolute.model.eq(m)&absolute.target.eq('top3')].iloc[0]
        values.append(r.rate*100);lo.append((r.rate-r.ci_low)*100);hi.append((r.ci_high-r.rate)*100)
    axes[1].bar(range(4),values,yerr=[lo,hi],capsize=4,color=['#9A9A9A','#2678B2','#14507A','#77A48A'])
    axes[1].set_xticks(range(4),['기초','전체시간','구간 추가','심사 중심'])
    axes[1].set_ylim(0,65);axes[1].set_ylabel('높은 평가 그룹의 실제 입상률 (%)');axes[1].set_title('직전 교정연도의 상위20% 경계로 선택')
    axes[1].axhline(baseline.event_rate*100,color='#555555',linestyle='--',label=f'전체 신마 {baseline.event_rate*100:.1f}%')
    axes[1].legend(loc='upper left')
    for j,v in enumerate(values):axes[1].text(j,v+hi[j]+1,f'{v:.1f}%',ha='center')
    fig.suptitle('주행심사 기록을 더하면 신마 첫 출전 예측이 나아지는가',fontsize=16,y=.99)
    fig.text(.5,.025,'2024~2026년(9월까지) 연도 분리 후향 평가 · 세로선: 고평가 그룹 입상률의 날짜 군집95% 구간\nAUC는 적중률이 아님 · 최종 명단 메타데이터를 출전표 대용으로 사용 · 실시간 운영 검증 미완료',ha='center',fontsize=10)
    fig.tight_layout(rect=(0,.12,1,.93));fig.savefig(OUT/'prediction_validation.png',dpi=170);plt.close(fig)
    dump(OUT/'web_research.json',dict(title='주행심사와 신마 데뷔전 예측',as_of='2026-10-25',
        status='retrospective_temporal_prediction_validation',publication=publication,
        metrics=records(metrics),high_groups=records(high),intervals=records(ci),time_bands=records(bands),
        same_debutant_choice=records(chosen),primary_rows=audit['primary_rows'],evaluation_rows=int(full.n),
        prediction_gain_observed=True,prospective_validation=False,production_changed=False))
    print('Report, web summary, and figure rendered')


if __name__=='__main__':main()

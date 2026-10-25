"""Publish local research evidence and a self-inclusive bounded inventory."""
import json
import re
import pandas as pd
import analyze as a

CENTRAL = a.R/'conclusions/58O_TRIO_GAIN_LOSS_DIAGNOSIS.md'
MARKER = '<!-- trio_gain_loss_20261025 -->'


def main():
    v=json.loads((a.OUT/'verification.json').read_text())
    assert v['status']=='passed'
    s=pd.read_csv(a.OUT/'condition_summary.csv')
    d=pd.read_parquet(a.OUT/'race_diagnostics.parquet')
    cases=d[d.transition.isin(['gained','lost'])]
    market=pd.read_csv(a.OUT/'market_case_diagnostics.csv')
    dist=pd.read_csv(a.OUT/'payout_distribution.csv')
    def value(x):
        return '—' if pd.isna(x) else f'{x:.2f}'
    def condition(dim,years=('2025','2026')):
        lines=['| 연도 | 조건 | 전체 경주 | 새 적중 | 상실 | 새 배당 평균 | 상실 배당 평균 | 환급 차이 |',
               '|---|---|---:|---:|---:|---:|---:|---:|']
        for y in years:
            z=s[s.period.eq(y)&s.dimension.eq(dim)]
            for row in z.itertuples():
                lines.append(f'| {y} | {row.value} | {row.races:,} | {row.gained} | {row.lost} | {value(row.gained_mean)} | {value(row.lost_mean)} | {row.delta_return:+,}원 |')
        return '\n'.join(lines)
    annual=['| 연도 | 경주 | 새 적중 / 상실 | 새 배당 / 상실 배당 평균 | 축6 ROI → 공동6 ROI | 환급 차이 |',
            '|---|---:|---:|---:|---:|---:|']
    for row in s[s.dimension.eq('all')].itertuples():
        annual.append(f'| {row.period} | {row.races:,} | {row.gained} / {row.lost} | {row.gained_mean:.2f} / {row.lost_mean:.2f}배 | {row.old_roi:.2%} → {row.new_roi:.2%} | {row.delta_return:+,}원 |')
    annual='\n'.join(annual)
    ranks=['| 집단 | 실제 입상마의 모델 순위 집합 | 경주 | 평균 삼복배당 | 환급 |',
           '|---|---|---:|---:|---:|']
    for (transition,pattern),g in cases.groupby(['transition','podium_model_ranks']):
        ranks.append(f'| {"새 적중" if transition=="gained" else "상실"} | {pattern} | {len(g)} | {g.dividend.mean():.2f}배 | {int(g.payout.sum()):,}원 |')
    ranks='\n'.join(ranks)
    tail=['| 연도 | 50배 미만 환급 차이 | 50배 이상 새 적중 / 상실 | 50배 이상 환급 차이 | 합계 |',
          '|---|---:|---:|---:|---:|']
    for y,g in cases.groupby('year'):
        low=g[g.dividend.lt(50)]; high=g[g.dividend.ge(50)]
        lo=int(low.delta_return.sum());hi=int(high.delta_return.sum())
        tail.append(f'| {y} | {lo:+,}원 | {high.transition.eq("gained").sum()} / {high.transition.eq("lost").sum()} | {hi:+,}원 | {lo+hi:+,}원 |')
    tail='\n'.join(tail)
    mlines=['| 연도 | 새 적중: 단승인기 상위2두 이상 입상 | 상실: 단승인기 상위2두 이상 입상 |',
            '|---|---:|---:|']
    for y in ['all',2024,2025,2026]:
        z=market if y=='all' else market[market.year.eq(y)]
        vals=[]
        for transition in ['gained','lost']:
            g=z[z.transition.eq(transition)];n=int(g.podium_market_top2.ge(2).sum())
            vals.append(f'{n}/{len(g)} ({n/len(g):.2%})')
        mlines.append(f'| {y} | {vals[0]} | {vals[1]} |')
    mlines='\n'.join(mlines)
    example=['| 실제 경주 | 등급·거리 | 정답 마번 집합 | 모델 순위 집합 | 배당 | 실제 S1F 첫 묶음 / 그중 입상 |',
             '|---|---|---|---|---:|---|']
    for row in cases[cases.transition.eq('lost')].nlargest(5,'payout').itertuples():
        label=row.race_key.split(':');venue='서울' if label[0]=='1' else '부산'
        example.append(f'| {label[1]} {venue}{label[2]}경주 | {row.grade_raw}·{row.distance}m | {row.actual} | {row.podium_model_ranks} | {row.dividend:.1f} | {int(row.observed_front_count)}두 / {int(row.observed_front_podium)}두 |')
    example='\n'.join(example)
    text='\n\n'.join([
        '# 연구 기준 공동확률6조합: 새 적중210경주와 상실145경주 진단',
        '2026-10-25 · 연구58O · state_gbm118 고정 · 새 학습0 · 운영 변경 없음.',
        '**새 방식은 모델1·2위 동반입상에 조합이 집중됐고, 기존에 담았던 모델1·4·5위 같은 조합을 줄였다. 상실145경주는 전부 축이 입상한 경주다. 후보 밖 말 포착을 늘리면서도 축이 살아남은 상태의 동반마 교체를 덜 담은 것이 직접적인 조합 선택 구조다. 2025·2026년은 이 과정에서 빠진 고배당 환급이 새 적중 환급보다 컸다.**',
        '## 비교 범위와 용어',
        '연구58M의 서울·부산 동일4,133경주(2024-01-05~2026-09-13)를 그대로 썼다. 매경주6개 고유 삼복승 조합, 장당1,000원, 경주당6,000원이다. 축6은 Top3 주변확률1위 축과 차순위4두의 모든 짝, 공동6은 같은 모델의 모든 삼복집합 중 확률상위6개다. 배당은 선택에 넣지 않았다. 2026년은 부분연도다. 현재 운영이 무엇인지와 별개로 앞선 연구 기준 버전을 고정한 진단이다.',
        '아래의 **모델1·4·5위**는 그 경주에서 모델이 매긴 순위이며 마번이나 실제1·2·3착을 뜻하지 않는다. 삼복이므로 집합 내부 실제 착순은 구분하지 않는다. 환급 차이는 공동6−축6이며, ROI=(환급−구매)/구매다. 공시 확정배당의 세전 가상정산으로 개인 세금·절사·실제 구매 풀 영향은 제외했다.',
        annual,
        '전체 환급은19,362,000→18,706,300원, 순손익은−5,436,000→−6,091,700원이다. 적중은1,121→1,186으로65경주 늘었지만 환급655,700원이 줄었다. 두 방식 모두 전체 수익률은 음수다.',
        '## 어떤 정답 조합을 서로 바꿨나',
        ranks,
        '상실145경주가 모두 축 입상인 것은 원래 축고정6장 적중을 잃은 표본의 정의상 필수다. 이를 새로 발견한 예측신호로 쓰지 않는다. 아래 순위 패턴 역시 가산형 점수와 상위6개 선택에서 생긴 구조를 분해한 것이며, 별도 경기 전 분류기의 성능을 검증한 결과가 아니다.',
        '새 적중 중168/210(80.0%)은 모델1·2위+6~8위,42경주는2·3·4위였다. 상실 중132/145(91.0%)는5위 말을 포함했고90경주는1·4·5위였다. 상실145경주는 전부1위 축을 포함하며 **전부 모델2위가 빠진 경주**다. 따라서 이 상실을 축 붕괴 문제로 설명하면 맞지 않는다. 후보 폭은 넓어졌으나, 그중 많은 조합이1·2위 동반입상에 의존했다.',
        '해당 GBM의 삼복집합 확률은 q(T)∝exp(집합 안3마리 점수 합/기존 온도)다. 입력에는 편성·전개 관련 값이 있지만 최종 집합 점수에 별도 두 말·세 말 상호작용항은 없다. 모델1·2위+후순위의 점수 합이1·4·5위보다 높으면 공동6은 전자를 산다. 이 정의로 모델 확률합을 최대화할 수 있어도 실제 환급액 최대화를 보장하지는 않는다.',
        '## 놓친 배당이 더 높았던 근거',
        '새 적중 배당 평균21.68배·중앙값16.0배, 상실은35.91배·24.7배다. 상실의90백분위72.66배는 새 적중41.49배보다 높다. 중앙값도 높아서 최고배당 한 건만의 차이는 아니다. 100배 이상은 새 적중2/210, 상실10/145였다.',
        mlines,
        '단승확정배당으로 매긴 공동순위(min rank) 기준이다. 배당동률은 같은 인기순위를 부여한다. 실제 입상3두 중 최대 단승배당의 평균은 새 적중16.60배·상실16.74배로 거의 같았다. 반면 시장상위2두 이상을 함께 담은 비율은62.38% 대29.66%였다. 한 마리의 극단적인 비인기보다 인기마 동반입상이 덜한 조합을 놓친 모습과 일치한다. 다만 삼복 조합별 실제 구매분포·풀 자료가 없어 배당 형성의 직접 인과나 사전 기대수익은 확인하지 못했다.',
        '단승배당은 핵심 집계 후 보조 설명으로 기존 DuckDB를 읽기 전용 조회했다.3752출전 전부를 말ID·마번·출처행·공식착순과 맞췄고, 별도 DB재조회로 배당을 대조했다. 기존 원시JSON6개 경로는 현재 파일이 없어 원문 재검증했다고 표현하지 않는다. 작은 원천 투영과 DB조회문·출처를 보존했으며, 확정배당을 입력으로 모델이나 티켓을 다시 고르지 않았다.',
        '## 2025년 환급611,400원 감소',
        '새68·상실56으로 적중은12경주 늘었지만 평균배당21.06대36.49배였다. 서울은−740,600원, 부산은+129,200원이다. 거리별로2000m−173,300원,1200m−170,500원,1400m−87,000원,1300m−85,700원 등이 겹쳤다. 등급별2등급−299,400원,3등급−248,700원,5등급−167,200원이 컸고4등급은+72,400원이었다. 즉 이 연도의 손실을4등급 하나로 설명할 수 없다.',
        '세부 교차표에서 서울2000m·2등급은 전체9경주 중 새0·상실2로−219,400원, 서울1400m·3등급은36경주 중 새1·상실2로−186,600원이었다. 모두 소수 고배당에 민감한 사후 셀이다. 2024년1400m에서는 새20·상실8로+529,200원이었지만2025년에는 새23·상실11에도−87,000원으로 바뀌었다. 2024년에 우연히 유리했던 환급 구성이 다음 연도에도 유지되지 않았다.',
        '## 2026년 환급456,100원 감소',
        '새63·상실39로 적중은24경주 늘었지만 평균배당21.14대45.84배로 격차가 더 컸다. 서울−409,000원, 부산−47,100원이다.1200m−456,900원·1400m−283,800원이 중심이고1800m+215,600원·1300m+69,400원 등이 일부 상쇄했다. 등급별4등급−557,200원,1등급−155,000원에 대해3등급+217,900원 등이 상쇄했다.',
        '지역×거리×등급에서는 서울1200m·4등급−253,400원(34경주, 새3·상실4), 서울1400m·4등급−191,100원(35경주, 새1·상실3)이 컸다. 부산1200m·6등급도−166,300원(36경주, 새3·상실3)이었다. 새 적중과 상실 수가 같거나 새 적중이 더 많아도 환급이 악화할 수 있다. 서울1400m·1등급−168,000원은 단1건 상실이므로 일반적인 등급효과로 확대하지 않는다.',
        '## 거리별 전체 분해',
        condition('distance'),
        '## 등급별 전체 분해',
        '등급 숫자는 국산·혼합 등급을 합친 층이다. 원래 국/혼/오픈 표기도 CSV에 보존했다. 서울·부산과 거리 구성 차이가 섞이므로 독립적인 등급효과가 아니다.',
        condition('grade_label'),
        '## 경주 전 전개 지표와 사후 실제 전개',
        '사전 지표는 각 출전마의 기존 front_gate_probability를 전마 합한 값이다. 합<2 / 2이상3미만 / 3이상으로 미리 나눴다. 전4,133경주에서 기존 예측지원과 결측 없는 전마 값을 확인했다. 이것은 예상 앞선 두수 지표이며 실제3두가 선행했다거나 빠른 페이스가 확정됐다는 뜻은 아니다. 이 지표를 이번에 새로 학습하거나 정답으로 재계산하지 않았다.',
        condition('predicted_pace'),
        '확률합3이상은2025년120경주 중 새2·상실5로−332,600원,2026년77경주 중 새2·상실4로−354,400원이었다. 그러나2024년에는142경주 중 새5·상실3으로+128,900원이었다. 전체339경주 중 새9·상실12에 불과해 이 경계에서 정책을 전환하라는 근거로 쓰기에는 부족하다. 임계값은 결과를 보고 최적화하지 않았다.',
        '사후 전개는 실제S1F **통과조의 첫 묶음**이다. 통과착순1위 한 마리를 선행으로 둔 것이 아니다. 말ID와 전체명단을 맞추고 전마 관측·모순 없음을 요구해4,048경주를 해석할 수 있었고85경주는 미상으로 남겼다. 결측을 후미나 경합 없음으로 채우지 않았다.',
        condition('observed_pace'),
        '2025년 실제첫묶음1두인 경주의 환급차가−356,400원이었고2026년은−132,600원이었다.2026년 실제첫묶음2두도−210,000원이었다. 손실이 실제첫묶음3두 이상에만 집중된 것은 아니다. 첫묶음 크기만으로 실제 속도 경합을 판단할 수도 없다. 새 적중/상실의 실제첫묶음 밖 입상마 평균도1.77/1.70두로 비슷했다. 따라서 추입마를 전반적으로 더 못 잡았다고 단정하지 않는다.',
        '2026년 실제전개가 확인된 상실37경주 중 축이 실제첫묶음에 속한 비율은67.57%(25/37), 새 적중62경주에서는37.10%(23/62)였다. 실제 앞선 축이 살아도 나머지 동반마가 달라진 경우를 놓친 모습이다. 이는 사후 해석이며 경주 전에 확정해 쓸 정보가 아니다.',
        '## 고배당 집중도와 민감도',
        tail,
        '2025년은50배 이상 상실10건 환급1,051,100원 대 새4건237,700원으로 차이−813,400원이었고,50배 미만에서는+202,000원이었다.2026년은 상실10건1,169,500원 대 새5건353,900원으로−815,600원,50배 미만에서는+359,500원이었다. 따라서 두 연도의 ROI 악화는 고배당 구간의 환급손실이 직접 지배했다.',
        '상실 환급 상위10건의 비중은2025년51.44%,2026년65.42%였다. 다만 최고1건을 빼도2025년 차이−403,900원,2026년−263,200원이어서 단1건만으로 설명되지는 않는다. 양쪽에 같은50배 상한을 씌우는 계산에서도2025년−98,000원·2026년+109,500원으로 달라진다. 상한/사후제외는 꼬리 민감도이며, 원래 구매액을 유지한 반사실 환급 분해다. 미래에 고배당 결과만 제외할 수 있다는 뜻이나 대체 전략의 실제 ROI가 아니다.',
        '## 조건 구성이 달라서 생긴 차이인가',
        '전체 새/상실의 평균 출전두수10.54/10.61, 축 입상예측66.0%/65.6%, 앞선확률합2.56/2.60은 비슷했다. 상실에서 과거이력 평균11.59전으로 새12.48전보다 조금 적었지만 확실한 분리 기준으로 검증하지 않았다.',
        '양집단 각5건 이상인 공통 셀에 같은 가중치를 주어 평균배당을 표준화했다. 연도×지역은355건 전부에서 새21.64배·상실35.71배, 연도×거리는273건에서21.12·36.40배, 연도×등급은299건에서20.63·33.35배였다. 구성 차이만으로 배당 격차가 사라지지는 않았다. 그러나 연도×지역×거리×등급을 동시에 맞춘 셀은 기준을 만족한 곳이0이어서 완전한 동조건 비교·독립효과 추정은 못 했다. 표본을 줄여 유리한 셀만 보고한 결과가 아니다.',
        '## 실제 상실 사례',
        example,
        '상위5건 모두 모델1·4·5위가 입상했다.2025-08-23 서울9경주207.5배는 실제첫묶음1두 중1두 입상,2026-03-14 서울7경주175.9배는 실제첫묶음1두가 전부 비입상이었다. 비슷한 선택구조의 실패라도 실제 전개는 다르므로 단일 선행/추입 원인으로 묶지 않는다.',
        '## 다음 검증으로 연결할 가설과 판단',
        '이번 자료에서 확인한 것은 **축 포함 후보3~5위의 동반입상 조합을 덜 담는 비용**이다. 후순위 말 한 마리를 늘리는 것만으로는 해결되지 않는다. 다음 실험은 모델1·2위 동반입상 예측이 과한지, 축 입상·모델2위 이탈 조건에서3~5위와6위 밖 중 누가 함께 들어오는지 조건부 분포를 보정하는 방향이 타당하다. 공동확률 선택과 시장가격 대비 가치 평가도 별도 목표로 검증해야 한다. 이 진단을 보고1·4·5위를 무조건 보존하거나 특정 거리·등급에서 정책을 바꾼 성적은 이번에 만들지 않았다.',
        '원래58M의 전체ROI 차이95%구간은−8.97~+3.39%p로0을 포함했다. 이번 거리·등급·전개 분해는 반복 사용한 개발기간의 사후 탐색이며, 다수의 소표본 셀에서 장래 효과나 인과원인을 확정하지 않는다. 명단·부중의 당시 공개시각 미확인, 입상동착 제외와 비정상완주마 후보 유지 등 기존 모집단 제한도 그대로다.',
        '## 검증과 재현',
        f'기존티켓49,596장 전부의 정답 라벨,355변경경주의 점수순위·정답집합 순위, 전체/연도별Decimal정산,52개 분할 항등식, 원천파일 해시,3752행 단승배당을 별도 재조회로 검증했다. 실제전개 미상85경주를 전체 분모에 유지했다. 새 학습0·DB쓰기0·운영변경0·외부수집0이다.',
        '계획 후 핵심 결과를 확인하고 단승배당을 사후 설명용으로 추가한 순서를 남긴다. 이는 새 사전가설 검정이 아니다. 이미 존재하는 DB와 모델·전체특징은 복사하지 않고 변경경주의 최소문맥과 집계만 보존했다.',
        '[사전계획](PLAN.md) · [분석](analyze.py) · [단승시장보조](market.py) · [별도검산](verify.py) · [전체조건표](outputs/condition_summary.csv) · [변경355경주](outputs/changed_cases.csv) · [배당분포](outputs/payout_distribution.csv) · [꼬리민감도](outputs/payout_sensitivity.csv) · [공통셀](outputs/common_cell_standardization.csv) · [시장비교](outputs/market_condition_comparison.csv) · [검증](outputs/verification.json) · [용량](outputs/artifact_inventory.json)',
        ''
    ])
    (a.HERE/'README.md').write_text(text)
    central='\n\n'.join(['# 연구58O: 공동확률6조합 새210·상실145 진단',
        '2026-10-25. 앞선 state_gbm118 고정, 새 학습·운영 변경 없음.',annual,
        '상실145경주는 전부 축 입상·모델2위 이탈,132건은모델5위 포함이었다.축입상은원래축고정적중상실이라는표본정의상필수이며새예측신호가아니다.새210중168건은1·2위+6~8위로후보폭을넓히면서1·2위동반입상에집중했다.시장상위2두동반입상은새62.38%·상실29.66%,입상마최대단승배당평균은비슷해인기마동반구성이달랐다.삼복구매분포없어인과/사전가치미확정.',
        '2025는서울−740,600원,2·3등급손실이컸다.2026은1200/1400m·4등급손실이중심이다.앞선확률합3+군은두연도손실이컸지만각년도변경7/6건의소표본이며2024는반대였다.실제S1F통과조는4,048경주관측·85미상;실제선두묶음1/2두에서도손실이커선행경합에의한축붕괴로설명할수없다.',
        tail,
        '50배미만은두연도모두환급이늘었으나고배당구간손실이이를넘었다.거리·등급·전개금액은서로겹치는별도분해이므로더하지않는다.개발기간사후진단·2026부분연도·소표본·확정단승자료원문JSON부재한계유지.',
        '[원문](../20261025_trio_gain_loss_diagnosis_v1/README.md) · [전체조건](../20261025_trio_gain_loss_diagnosis_v1/outputs/condition_summary.csv) · [검증](../20261025_trio_gain_loss_diagnosis_v1/outputs/verification.json)', ''])
    CENTRAL.write_text(central)
    (a.HERE/'PUBLICATION.md').write_text('# 게시 준비: 더 맞히고 환급이 줄어든 이유\n\n같은연구기준4,133경주·6조합에서새210/상실145를비교했다.상실은전부축이입상했고91.0%에모델5위가포함됐다.새적중은80%가모델1·2위+6~8위였다.평균배당21.68대35.91배,중앙값16.0대24.7배로상실이높았다.2025/26환급−611,400/−456,100원은50배이상에서잃은환급이주도했고50배미만에서는둘다개선됐다.실제통과조와사전앞선확률합을구분했으며,확정단승배당은사후설명용이다.새로운구매규칙이나미래수익을확인한결과가아니다.\n\n[상세](README.md) · [검증](outputs/verification.json)\n\n공개게시·배포·운영반영없음.\n')
    for path,line in [
        (a.R/'README.md','[연구58O 공동6 새210·상실145 진단](20261025_trio_gain_loss_diagnosis_v1/README.md):축은모두생존했으나모델2위이탈·5위동반조합을상실.2025/26고배당환급감소,거리·등급·사전/사후전개분리.'),
        (a.R/'conclusions/README.md','[연구58O 공동6 새적중·상실 조건](58O_TRIO_GAIN_LOSS_DIAGNOSIS.md):상실145건축입상·132건5위포함,고배당꼬리가2025/26환급악화주도.사후진단·운영유지.'),
        (a.R/'conclusions/SOURCES.md','[연구58O](58O_TRIO_GAIN_LOSS_DIAGNOSIS.md) · [원문](../20261025_trio_gain_loss_diagnosis_v1/README.md) · [원천해시](../20261025_trio_gain_loss_diagnosis_v1/outputs/input_manifest.json) · [검증](../20261025_trio_gain_loss_diagnosis_v1/outputs/verification.json).58M동결티켓·구간통과조·읽기전용DB단승배당보조,신규학습0.')]:
        old=path.read_text()
        if MARKER not in old:path.write_text(old+'\n\n'+MARKER+'\n'+line+'\n')
    manifest=a.R/'conclusions/source_manifest.json'
    m=json.loads(manifest.read_text())
    paths=[CENTRAL,a.HERE/'README.md',a.HERE/'PLAN.md',a.HERE/'analyze.py',a.HERE/'market.py',
           a.HERE/'verify.py',a.HERE/'finalize.py',a.OUT/'condition_summary.csv',a.OUT/'verification.json',
           a.OUT/'input_manifest.json',a.OUT/'market_provenance.json']
    additions={str(p.relative_to(a.ROOT)):a.sha(p) for p in paths}
    m['sources']=[x for x in m['sources'] if x['path'] not in additions]+[dict(path=p,sha256=h) for p,h in additions.items()]
    manifest.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
    inventory=a.OUT/'artifact_inventory.json'
    if not inventory.exists():a.save('artifact_inventory.json',{})
    before=json.loads((a.OUT/'publication_before.json').read_text())
    log=a.R/'ARTIFACT_SIZE_LOG.md'
    for _ in range(30):
        files=sorted([p for p in a.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[CENTRAL])
        total=sum(p.stat().st_size for p in files)
        line=f'| 2026-10-25 | 58O 공동6 새210·상실145 진단 | {len(files)} | {total:,} B ({total/1048576:.6f} MiB) | 5 | [명세](20261025_trio_gain_loss_diagnosis_v1/outputs/artifact_inventory.json) |'
        log.write_text('\n'.join(x for x in log.read_text().splitlines() if '58O 공동6 새210·상실145 진단' not in x)+'\n'+line+'\n')
        modified=[dict(path=p,before_bytes=x['bytes'],after_bytes=(a.ROOT/p).stat().st_size,
                       delta_bytes=(a.ROOT/p).stat().st_size-x['bytes']) for p,x in before.items()]
        obj=dict(new_files=len(files),new_bytes=total,new_mib=f'{total/1048576:.6f}',
            files=[dict(path=str(p.relative_to(a.ROOT)),bytes=p.stat().st_size,
                        sha256=None if p==inventory else a.sha(p)) for p in files],
            modified_files=modified,modified_delta_bytes=sum(x['delta_bytes'] for x in modified),
            new_models=0,original_database_copied=False)
        old=inventory.read_text();a.save('artifact_inventory.json',obj)
        if old==inventory.read_text():break
    else:raise AssertionError('inventory failed to converge')
    assert sum(p.stat().st_size for p in files)==obj['new_bytes']<5*1048576
    # Validate all links written for this research and exact self-inclusive hashes.
    for p in [a.HERE/'README.md',a.HERE/'PLAN.md',a.HERE/'PUBLICATION.md',CENTRAL]:
        for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if '://' not in link and not link.startswith('#'):
                assert (p.parent/link.split('#')[0]).exists(),(p,link)
    for row in obj['files']:
        p=a.ROOT/row['path']
        assert p.stat().st_size==row['bytes']
        if row['sha256']:assert a.sha(p)==row['sha256']
    for p,h in additions.items():assert a.sha(a.ROOT/p)==h
    print(json.dumps({k:v for k,v in obj.items() if k not in ['files','modified_files']},ensure_ascii=False))
    largest=max(obj['files'],key=lambda x:x['bytes'])
    print(json.dumps(largest,ensure_ascii=False))


if __name__=='__main__':main()

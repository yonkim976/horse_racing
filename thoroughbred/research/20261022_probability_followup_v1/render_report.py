"""Render a reproducible follow-up report from existing result tables."""
from __future__ import annotations
import json
import pandas as pd
import common as c

CONCLUSION=c.HERE.parent/"conclusions/58A_PROBABILITY_MIXTURE_TOP2_HEAD.md"
NAMES={"full103":"기존 F103","additive89":"기존 EL89","mix50":"50:50 혼합","mixcal":"과거교정 혼합",
    "crossF":"EL집합+F순서","top2_22":"EL집합+기존22 Top2","top2_89":"EL집합+새89 Top2"}
HITS=["axis_top3","quinella_one","quinella_three","qpl_one","qpl_three"]


def table(headers,rows):
    return "\n".join(["| "+" | ".join(map(str,headers))+" |","|"+"---|"*len(headers),
        *["| "+" | ".join(map(str,row))+" |" for row in rows]])


def pct(x):
    return f"{100*x:.2f}%"


def interval(z,scale=100,digits=2,wide=False):
    low=z.ci_99_low if wide else z.ci_low;high=z.ci_99_high if wide else z.ci_high
    return f"{z.difference*scale:+.{digits}f} [{low*scale:+.{digits}f}, {high*scale:+.{digits}f}]"


def render(storage=None):
    m=pd.read_csv(c.OUT/"metrics.csv",dtype={"level":str});main=m[m.scope.eq("all_starters")]
    total=main[main.dimension.eq("overall")].set_index("variant")
    d=pd.read_csv(c.OUT/"paired_differences.csv",dtype={"period":str});d=d[d.scope.eq("all_starters")]
    gl=pd.read_csv(c.OUT/"gain_loss_conditions.csv",dtype={"level":str})
    cal=pd.read_csv(c.OUT/"calibration_summary.csv")
    train=pd.read_csv(c.OUT/"training_diagnostics.csv")
    ev=json.loads((c.OUT/"evaluation_complete.json").read_text())
    def diff(candidate,baseline,metric,period="all"):
        return d[(d.candidate==candidate)&(d.baseline==baseline)&(d.metric==metric)&(d.period==period)].iloc[0]
    perf=table(["방법","n","축 Top3","복승1","복승3","복연1","복연3","복연 적중수/경주"],
        [[NAMES[v],int(total.loc[v,"races"]),*[pct(total.loc[v,x]) for x in HITS],f"{total.loc[v,'qpl_count']:.4f}"] for v in NAMES])
    primary=table(["EL89 대비","축 순증","복승1 순증","복승3 순증","복승3 차이[95%], %p","복승3 차이[99%], %p"],
        [[NAMES[v],int(total.loc[v,"axis_top3_hits"]-total.loc["additive89","axis_top3_hits"]),
          int(total.loc[v,"quinella_one_hits"]-total.loc["additive89","quinella_one_hits"]),
          int(total.loc[v,"quinella_three_hits"]-total.loc["additive89","quinella_three_hits"]),
          interval(diff(v,"additive89","quinella_three")),interval(diff(v,"additive89","quinella_three"),wide=True)] for v in c.cfg()["new_variants"]])
    annual=[]
    for year in ["2024","2025","2026"]:
        z=main[(main.dimension=="year")&(main.level==year)].set_index("variant")
        q=diff("top2_89","additive89","quinella_three",year)
        annual.append([year,int(z.loc['additive89','races']),
            f"{int(z.loc['additive89','axis_top3_hits'])} / {pct(z.loc['additive89','axis_top3'])}",
            f"{int(z.loc['additive89','quinella_one_hits'])} → {int(z.loc['top2_89','quinella_one_hits'])}",
            f"{int(z.loc['additive89','quinella_three_hits'])} → {int(z.loc['top2_89','quinella_three_hits'])}",
            interval(q),f"{int(q.gains)}/{int(q.losses)}"])
    years=table(["연도","n","축 동일","복승1 EL→새head","복승3 EL→새head","복승3 차이[95%], %p","회복/상실"],annual)
    proper=table(["방법","말Top3 Brier","복승 Brier","복연 Brier","삼복NLL","순서NLL","복승NLL","조건부3착NLL"],
        [[NAMES[v],*[f"{total.loc[v,k]:.6f}" for k in ["runner_brier","quinella_brier","qpl_brier","trio_logloss","ordered_logloss","quinella_logloss","conditional_third_logloss"]]] for v in NAMES])
    score_diff=table(["새89 Top2−EL89","차이[95%], 낮을수록 좋음"],
        [[name,interval(diff("top2_89","additive89",name),1,6)] for name in ["quinella_brier","quinella_logloss","conditional_third_logloss","ordered_logloss","qnl1_brier","qnl3_brier"]])
    cal_rows=[]
    for v in ["additive89","top2_89","mixcal"]:
        for target in ["axis","quinella_one","quinella_three_union","qpl_three_union"]:
            z=cal[(cal.variant==v)&(cal.target==target)].iloc[0]
            cal_rows.append([NAMES[v],target,pct(z.predicted),pct(z.observed),pct(z.ece)])
    cal_table=table(["방법","대상","평균예측","실제","10구간ECE"],cal_rows)
    count_table=table(["방법","0개","1개","2개","3개","적중조합 합"],
        [[NAMES[v],*[int(total.loc[v,f'qpl_count_{i}_races']) for i in range(4)],int(total.loc[v,'qpl_hits_total'])] for v in NAMES])
    def strata_table(dimension):
        z=main[(main.dimension==dimension)&main.variant.isin(["additive89","top2_89"])]
        rows=[]
        for level in z.level.unique():
            q=z[z.level.eq(level)].set_index("variant")
            a=gl[(gl.candidate=="top2_89")&(gl.baseline=="additive89")&(gl.dimension==dimension)&(gl.level==level)&(gl.metric=="quinella_three")].iloc[0]
            name={"1":"서울","3":"부산"}.get(level,level) if dimension=="meet" else level
            rows.append([name,int(q.loc['additive89','races']),pct(q.loc['additive89','axis_top3']),
                f"{pct(q.loc['additive89','quinella_one'])} → {pct(q.loc['top2_89','quinella_one'])}",
                f"{pct(q.loc['additive89','quinella_three'])} → {pct(q.loc['top2_89','quinella_three'])}",
                pct(q.loc['additive89','qpl_three']),f"{int(a.gains)}/{int(a.losses)}"])
        return table(["조건","n","축 동일","복승1 EL→새head","복승3 EL→새head","복연3 동일","복승3 회복/상실"],rows)
    conditional=[]
    clean=pd.read_csv(c.OUT/"unambiguous_metrics.csv")
    for source,scope,label in [(m,"all_starters","전체출발"),(m,"normal_finishers_conditioned","정상완주 조건부"),(clean,"all_starters","미해결2경주 제외")]:
        z=source[(source.scope==scope)&(source.dimension=="overall")].set_index("variant")
        for v in ["additive89","top2_89"]:
            row=z.loc[v]
            conditional.append([label,NAMES[v],int(row.races),int(row.starts),pct(row.axis_top3),pct(row.quinella_three),pct(row.qpl_three)])
    sens=table(["범위","방법","경주","행","축","복승3","복연3"],conditional)
    training=table(["분할","검증연도","선택반복","150회 손실","200회 손실"],
        [[r.fold,int(r.validation_year),int(r.best_iteration),f"{r.loss_at_150:.6f}",f"{r.loss_at_200:.6f}"] for _,r in train.iterrows()])
    fits=json.loads((c.OUT/"calibration_parameters.json").read_text())
    weights=table(["지역/평가연도","EL혼합비중","기존22 t3","새89 t3","1·2순서 t12"],
        [[f"{('서울' if r['meet']==1 else '부산')}/{r['evaluation_year']}",f"{r['mix_weight_el']:.4f}",
          f"{r['third_temperatures']['top2_22']:.4f}",f"{r['third_temperatures']['top2_89']:.4f}",f"{r['first_temperature']:.4f}"] for r in fits])
    storage_text="최종 용량명세 작성 대기."
    if storage:
        storage_text=(f"신규 {storage['new_file_count']:,}파일, {storage['new_bytes']:,} bytes ({storage['new_bytes']/1048576:.6f} MiB). "
            f"최대 `{storage['largest_file']['path']}` {storage['largest_file']['bytes']:,} bytes. "
            f"기존 연구문서 {storage['modified_file_count']}개 수정, 순증감 {storage['modified_delta_bytes']:+,} bytes. "
            f"연구58과 신규 파일을 합한 보관량은 {storage['combined_new_bytes']:,} bytes로 300MB 제한 이내다.")
    report=f"""# 모델 개선 후속: 확률 혼합과 복승 목표 분리

2026-10-22 · 연구58A · 서울·부산 · 후향 탐색 완료 · 운영 미반영.

**기존 89개 변수 후보를 확실히 능가하는 추가 개선은 확인하지 못했다.** 89개 입력을 사용하는 Top2 전용 모형은 축·복연을 그대로 유지하면서 복승 1조합 적중을 3경주, 3조합 적중을 7경주 늘렸지만 신뢰구간은 0을 포함했다. 확률 혼합은 일부 확률 오차를 낮췄으나 축·복연 적중을 낮췄다. 5개 후속안 모두 사전 개선 조건을 통과하지 못했다.

개선 방향은 구체화됐다. **학습이 200회 상한에 막혔는지 확인하고, 상위 3두 중 누가 3착인지 직접 학습하는 것**이 다음 우선순위다. 두 방법의 효과는 아직 검증하지 않았다. [다음 실험 명세](NEXT_EXPERIMENT.md)에 변경점·대조군·학습 분할·상한을 정리했다.

## 기존 결과에서 이어받은 질문

연구58의 EL89는 F103보다 축 적중이 39경주 많지만 복승 3조합 적중은 16경주 적었다. 기존 운영 A/B/C와 이 두 연구 모델은 다르다. EL/F의 축 선택은 605경주에서 달랐고, EL만 축 적중한 경주는 189개, F만 적중한 경주는 150개였다. 복승 3조합은 EL만 120개, F만 136개 적중했다. 이 차이를 후속 가설의 근거로 삼았다.

EL의 조건부 순서 NLL은 1.72052, F는 1.72369였다. F의 순서 예측이 더 좋다는 근거는 없으므로 순서 모형을 교차 적용하는 방법을 효과 분해용 대조군으로 뒀다. [선행연구 감사](audit_prior.md)에 기존 Top2·pair·정보 추가·보정의 성공과 실패, 이번 질문과의 차이를 정리했다.

## 고정한 방법과 검증 범위

[사전계획](PLAN.md), [설정](config.json), [동결한 100개 파일](outputs/input_manifest.json)을 평가 전에 고정했다. 새 학습은 89열 binary Top2 **최종 모형 6개**, 초기 학습과 재적합을 합해 12회로 끝냈다. 기존 Top2 6개와 Top3 12개를 읽기 전용으로 재사용했다. 정보 추가·거리별 규칙·평가기간 재교정은 수행하지 않았다.

| 방법 | 변경점 | 목적 |
|---|---|---|
| mix50 | 전체 순서 공동분포 EL/F를 50:50 혼합 | 단순 혼합 대조군 |
| mixcal | 이전 교정연도의 순서 NLL로 EL 비중 1개 학습 | 과거 가중치의 일반화 |
| crossF | EL 삼복 집합 × F 조건부 순서 | 집합·순서 효과 분리 |
| top2_22 | EL 집합 + 기존 22열 Top2로 조건부 3착 선택 | 기존 목표 전문화 대조군 |
| top2_89 | EL 집합 + 새 89열 Top2로 조건부 3착 선택 | 같은 출발정보로 복승 전문화 |

`P(T,c,a,b)=q_EL(T) × softmax_c(−s2_c/t3) × sigmoid((sF_a−sF_b)/t12)`로 3착 c와 남은 두 말의 1·2착 순서를 나눈다. 각 trio 안의 6개 순서 확률 합이 q_EL(T)와 같으므로 축 Top3·복연 전체 쌍 확률은 보존된다. 모든 승식 확률을 같은 공동분포에서 합산한다. 단승·순서 승식의 계산 구조가 유효하다는 것이 적중 검증을 마쳤다는 뜻은 아니다. 연승 공식 규칙은 미확인 상태다.

모든 후보는 같은 4,799경주·50,754출발행(2024-01-05~2026-09-20)에서 각 승식의 상위 1조합·3조합으로 비교했다. 학습 2017..Y−3, 검증 Y−2, 재적합 2017..Y−2, 교정 Y−1, 평가 Y로 분리했다. 2017년 이전 자료는 기존 이력 준비에만 사용했다. 2024~2026년은 기존 결과를 보고 후속 가설을 만든 반복 사용 자료다.

분포 혼합은 [Yao 등의 stacking 연구](https://sites.stat.columbia.edu/gelman/research/published/stacking.pdf)의 예측분포 결합 아이디어를 참고했다. Bayesian LOO 절차를 그대로 구현하지는 않았으며, 시계열 교정연도만 사용해 가중치를 정했다. 외부 경주자료는 수집하지 않았다.

## 같은 예산의 결과

{perf}

{primary}

차이 구간은 406개 날짜를 단위로 한 paired bootstrap 2,000회(seed 20261023)로 계산했다. 99% 구간은 5개 후속 방법의 EL 대비 복승 3조합 주 비교에 대한 Bonferroni family 5%용이다. 기타 여러 지표 전체의 오류율을 동시에 통제한다는 뜻은 아니다.

새 Top2_89는 EL 대비 복승 1조합 **+3경주(21회복/18상실)**, 3조합 **+7경주(39회복/32상실)**다. 복승 3조합 +0.15%p의 95% 구간은 −0.19~+0.49%p, 99% 구간은 −0.33~+0.63%p다. 기존 F103 대비로도 복승 3조합 적중은 여전히 9경주 적다. 축 +39경주의 이득은 EL을 그대로 유지한 효과다.

{years}

2024년 새 head의 복승 1조합·3조합 적중은 각각 −2/−1경주이고, 2025년에는 +3/+6, 2026년에는 +2/+2경주다. 모든 연도의 복승 3조합 차이 95% 구간은 0을 포함한다. 2026년은 9월 20일까지다. [모든 연도·조건별 표](outputs/metrics.csv), [대응 차이](outputs/paired_differences.csv)에 전체 후보를 보존했다.

복연 3조합의 적중 수 분포는 다음과 같다. 조건부 head 3개에서 EL과 완전히 같은 분포이며 확률 보존 검증과도 일치한다.

{count_table}

## 확률 품질과 적중을 구분한다

{proper}

{score_diff}

Top2_89는 EL 대비 순서 NLL을 낮췄지만 복승 NLL·Brier·조건부 3착 NLL 차이의 95% 구간은 0을 포함한다. 순서 NLL 개선에는 별도의 1·2위 logistic 온도 교정도 포함되므로 이를 Top2 목표만의 효과로 해석하지 않는다. 기존 22열 Top2와 비교하면 조건부 3착 NLL이 −0.006122(95% −0.009838~−0.002528)로 개선되지만, 복승 3조합은 +11경주(95% −0.25~+0.72%p)로 불확실하다. 선택한 복승 1조합·3조합의 Brier는 EL보다 오히려 소폭 커졌다.

{cal_table}

Top2_89의 복승 3조합 평균 예측 29.23%와 실제 29.09%, ECE 0.72%는 EL의 30.04%/28.94%, ECE 1.28%보다 가까웠다. 그러나 고정 10구간 ECE는 불확실성 구간이 아니고 선택 Brier와 판정이 다를 수 있다. 전체 복승 쌍의 평균 예측=관측은 쌍 확률 합이 1이라는 항등식일 수 있으므로 개선 증거로 삼지 않았다. [보정 구간표](outputs/calibration_overall.csv)를 함께 보존했다.

{weights}

혼합 가중치는 모두 경계 내부였지만 EL 비중이 0.546~0.916으로 변했다. 서울 2024년의 t12는 상한 4에 도달했다. 이 신호를 보고 범위를 늘려 다시 맞추지는 않았다. 가중치·온도 모두 이전 연도 정답만으로 정했고 평가 정답은 추천에 사용하지 않았다.

## 어디서 바뀌었는가

아래는 EL89→Top2_89 비교다. 축·복연은 같으며 복승만 변한다. 소표본 조건표로 채택 규칙을 만들지 않았다.

{strata_table('meet')}

{strata_table('distance_m')}

{strata_table('grade')}

[경주별 회복·상실](outputs/gain_loss_races.parquet)과 [조건별 집계](outputs/gain_loss_conditions.csv)에 기존·신규 선택과 차이를 보존했다. 실제 선행 성공 여부 같은 사후 정보를 입력이나 선택 필터로 추가하지 않았다. 관측된 조건 차이를 인과효과로 보지 않는다.

## 모집단·검증·남은 한계

정상 완주 50,608행, DNF 140행, DQ 3행, 미해결 special 3행을 포함한 50,754출발행을 주 결과로 사용했다. 비출발 697행과 상위 동착 28경주는 기존 계약대로 제외했고, 미해결 3행이 있는 2경주 제외 민감도도 제공한다. [이전 데이터 감사](../20261022_probability_comparison_v1/audit_data.md)를 그대로 이어받았다.

{sens}

정상 완주 조건부는 사후에 비완주 말을 포함한 순서를 제거해 재정규화한 진단이다. 실전 성능으로 해석할 수 없다. 미해결 2경주 제외 결과도 결론을 바꾸지 않는다.

[독립 검증](outputs/verification.json)은 동결 입력, 모델 점수, 조건부 확률 분해, 추천 적중 및 축·복연 보존을 검사한다. 수학 단위 테스트 5개가 통과했다. 최대 공동확률 제약 오차는 {ev['coherence_max_error']:.3g}, 고정 trio 질량 보존 오차는 {ev['trio_preservation_max_error']:.3g}였다. 재학습을 반복하지 않고 저장 모형과 코드·검증 로그를 확인했다. [독립 결과 해석](audit_results.md)도 첨부했다.

독립 검산에서 저장 모델 점수와 추천 적중·축·복연 보존은 전수 확인했다. 공동분포와 추가 확률 평가값의 독립 재계산은 지역·연도 6개 분할에서 1경주씩 수행했다. 교정값은 분할·해시·허용범위를 확인했고 최적화는 다시 실행하지 않았다.

2024~2026년의 반복 사용과 가설 선택 편향은 날짜 bootstrap이나 99% 구간으로 해소되지 않는다. 과거 출마표·부담중량의 실제 공개시각도 완전히 입증되지 않았다. 배당·구매비용을 검증하지 않았으므로 수익성 결론은 없다.

## 더 개선하려면 어디를 바꿀 것인가

검증 로그에서 학습 상한이 구체적인 점검 대상으로 드러났다.

{training}

6개 중 5개의 최적 반복수가 200회 상한이고 6개 모두 150→200회에서 검증 손실이 감소했다. **학습이 충분히 수렴했는지 미확인**이라는 뜻이다. 향상이 보장된 것은 아니며 이번에 상한을 바꿔 다시 탐색하지 않았다.

우선순위는 (1) 같은 Top2 목표에서 최대 반복수를 늘리고 과거 검증연도의 조기 종료로 선택, (2) 그와 별도 대조로 상위 3두 안의 3착을 직접 학습, (3) 축용 경주 그룹 ranking 목표 검토다. 학습 종료점과 목표 불일치를 먼저 검증할 근거가 생겼다. 구체적인 설계와 상한은 [NEXT_EXPERIMENT.md](NEXT_EXPERIMENT.md)에 있다.

독립 평가를 위해 보유한 9월 20일 이후 자료도 감사했다. 사후 수집한 79경주와 서울 10월 17~18일 결과는 존재하지만, 경기 전 새 후보 입력은 없다. 기존 예측 아카이브 16경주는 운영 모형용이고, 103열 계약과 직접 일치하는 항목은 거리 1열뿐이다. 이를 독립 성능 평가에 사용하지 않았다. [원천·시점 감사](audit_fresh_data.md)에 추가 원천 범위와 입력 복원 조건을 기록했다. 새로운 결과를 보기 전에 필요한 입력과 시각을 봉인해야 후속 성능을 주장할 수 있다.

이번 결론은 **EL89를 연구 기준으로 유지하고, Top2_89는 복승 전문화 연구 후보로 보존하며, 혼합·교차 head의 채택은 보류**하는 것이다. 5개 후속안 모두 사전 일반 개선·복승 전문화 조건을 충족하지 못했으며 추가 탐색은 종료했다. 운영 모델·DB·발행·웹사이트는 변경하지 않았다.

## 재현·산출물

아래 명령은 저장소 루트에서 실행한다. freeze는 최초 한 번 실행하고, train은 완료된 모형과 점수를 재사용한다. 기존 features·DB·모델·예측은 경로와 해시로 참조한다.

```sh
./.venv/bin/python -B thoroughbred/research/20261022_probability_followup_v1/study.py freeze
./.venv/bin/python -B thoroughbred/research/20261022_probability_followup_v1/study.py train
./.venv/bin/python -B thoroughbred/research/20261022_probability_followup_v1/study.py evaluate
./.venv/bin/python -B thoroughbred/research/20261022_probability_followup_v1/analyze.py
./.venv/bin/python -B thoroughbred/research/20261022_probability_followup_v1/test_heads.py
./.venv/bin/python -B thoroughbred/research/20261022_probability_followup_v1/verify.py
./.venv/bin/python -B thoroughbred/research/20261022_probability_followup_v1/finalize.py
```

[코드·입력 해시](outputs/input_manifest.json), [모형 메타데이터](outputs/training_complete.json), [교정값](outputs/calibration_parameters.json), [사전 판정](outputs/decision.json), [이전 실행환경](../20261022_probability_comparison_v1/outputs/environment.json)을 보존했다. 기존 F/EL 결과에서 추가로 필요한 확률 평가 열만 저장했다. parquet는 ignore 규칙에 따라 로컬 보관하며 별도 커밋·배포는 하지 않았다.

{storage_text}

[용량명세](outputs/artifact_inventory.json) · [완료감사](COMPLETION_AUDIT.md) · [미게시요약](PUBLICATION.md).
"""
    (c.HERE/"README.md").write_text(report,encoding="utf-8")
    (c.HERE/"PUBLICATION.md").write_text("""# 축과 복승의 역할을 나눠 본 결과

미게시 연구요약·운영 미반영. 이미 사용한 서울·부산 4,799경주에서 수행한 후향 탐색이다.

축에 강했던 89개 변수 모형의 3위 내 입상 예측을 고정하고, 1·2위에 들 말을 따로 학습해 복승 순서를 바꿨다. 축과 복연은 그대로 유지하면서 복승 1조합은 619→622경주, 3조합은 1,389→1,396경주를 맞혔다. 작은 증가지만 우연한 차이를 배제할 만큼 명확하지 않았다. 기존 103개 연구 모형의 복승 3조합 1,405경주에도 못 미쳤다.

두 모형의 확률을 혼합하는 방법도 시험했다. 전체 확률 오차가 작아져도 최상위 추천의 적중이 좋아지는 것은 아니었다. 이번 혼합은 축이나 복연의 적중을 낮춰 채택하지 않았다.

다음에 볼 구체적인 문제는 학습 종료점과 학습 목표다. 새 모형 6개 중 5개는 허용한 최대 200회에서 검증 손실이 가장 낮았으므로 더 학습할 여지가 있는지 확인할 필요가 있다. 또한 상위 3두 중 누가 3위인지 직접 학습하는 목표를 비교할 수 있다. 두 방법의 효과는 아직 검증하지 않았다.

새 경주의 입력을 경기 전에 고정해 검증해야 운영 교체를 판단할 수 있다. 배당·구매비용은 분석하지 않았으므로 수익성 결론은 없다.

[전체 근거와 재현](README.md) · [다음 실험 명세](NEXT_EXPERIMENT.md).
""",encoding="utf-8")
    CONCLUSION.write_text("""# 확률 혼합과 복승 전용 목표의 후속 검증

2026-10-22 · 연구58A · 서울·부산 · 운영 미반영.

새 89입력 Top2 모형 6개와 기존 Top2 6개·Top3 12개를 이용해 5개 방법을 사전에 고정하고 비교했다. EL89 집합을 유지하고 Top2 점수로 조건부 3착을 고른 뒤 1·2착 순서를 배분하면 축·복연 확률이 보존된다. 새 head는 EL 대비 복승 1조합 +3경주, 3조합 +7경주였으나 복승 3조합 차이의 95% 구간은 [−0.19,+0.49]%p, 5개 방법에 대한 99% 구간은 [−0.33,+0.63]%p로 개선을 확인하지 못했다. 기존 F103 대비 복승 3조합 적중은 여전히 9경주 적다.

50:50 혼합과 과거 교정 가중치를 사용한 혼합은 전체 분포의 일부 확률 오차를 줄였으나 축·복연 적중을 낮췄다. 순서 head 교차는 복승 3조합 +5경주로 불확실했다. 5개 안 모두 사전 일반 개선·복승 전문화 조건에 미달해 추가 탐색을 종료했다. EL89를 연구 기준으로 유지하고 Top2_89는 연구 후보로만 보존한다.

새 Top2 모형 6개 중 5개의 최적 반복수가 200회 상한이고, 6개 모두 150→200회에서 과거 검증 손실이 감소했다. 다음 우선순위는 학습 상한만 확장한 대조군과 상위 3두 중 3착을 직접 학습하는 조건부 목표다. 효과는 아직 미검증이다. 별도 경주 그룹 ranking 목표도 미실험 후보로 남긴다.

2024~2026년 4,799경주·50,754출발행은 이미 반복 사용한 자료다. 보유한 9월 20일 이후 사후 결과와 16경주 운영 예측 아카이브는 89/103열 입력 계약에 맞지 않아 독립 평가하지 않았다. 새 입력을 경기 전에 봉인하는 절차가 선행되어야 한다. 운영 교체·DB 쓰기·게시·수익성 주장은 없다.

[전체보고서](../20261022_probability_followup_v1/README.md) · [후속명세](../20261022_probability_followup_v1/NEXT_EXPERIMENT.md) · [결과표](../20261022_probability_followup_v1/outputs/metrics.csv) · [구간](../20261022_probability_followup_v1/outputs/paired_differences.csv) · [독립검증](../20261022_probability_followup_v1/outputs/verification.json).
""",encoding="utf-8")


if __name__=="__main__":
    p=c.OUT/"artifact_inventory.json"
    render(json.loads(p.read_text())["summary"] if p.exists() else None)

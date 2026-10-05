"""Render the completed numerical outputs into research and publication reports."""
# ruff: noqa: E501 -- long lines in the Korean Markdown report templates

import importlib.util
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
GRADES = ["국6", "국5", "국4", "국3", "2", "1"]
LABELS = dict(
    early="출발200m",
    middle1="200~600m",
    middle2="600~1000m",
    late="마지막200m",
    last600="마지막600m",
    last400="마지막400m",
    closing4c="4C 이후530m*",
    c4tog1="4C→G1F330m*",
)
STRUCTURES = dict(
    region="지역 공통", grade="등급 완화", grade_band="등급+함수율 완화", cell="등급×함수율 완화"
)


def md_table(d):
    lines = [
        "| " + " | ".join(map(str, d.columns)) + " |",
        "|" + "|".join(["---"] * len(d.columns)) + "|",
    ]
    lines += [
        "| " + " | ".join(str(x) for x in row) + " |"
        for row in d.itertuples(index=False, name=None)
    ]
    return "\n".join(lines)


def main():
    table = pd.read_csv(OUT / "par_candidates.csv")
    distribution = pd.read_csv(OUT / "relative_speed_distributions.csv")
    temporal = pd.read_csv(OUT / "temporal_par_validation.csv")
    ablation = pd.read_csv(OUT / "history_prediction_ablation.csv")
    sensitivity = pd.read_csv(OUT / "sensitivity.csv")
    summary = json.loads((OUT / "summary.json").read_text())
    test = temporal[temporal.stage.eq("test") & temporal.selected]
    mean_test = test.groupby(["meet", "part"])[["cell_mae", "runner_mae", "bias"]].mean()
    selected = summary["selected"]
    spec = importlib.util.spec_from_file_location("analysis", HERE / "analyze.py")
    analysis = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analysis)
    summary.update(analysis.runtime_metadata())
    analysis.save_json(OUT / "summary.json", summary)
    analysis.save_json(OUT / "web_relative_speed_par.json", analysis.web_export(table, selected))
    d = pd.read_parquet(OUT / "population_relative_speed.parquet")
    runner = pd.read_parquet(OUT / "recent_runner_relative_speed.parquet")
    keys = ["서울:20260920:11:0060340", "서울:20260920:11:0060719", "서울:20260920:11:0053501"]
    examples = []
    for key in keys:
        row = d[d.row_key.eq(key)].iloc[0]
        a = runner[runner.row_key.eq(key)].set_index("part")
        examples.append(
            dict(
                date="2026-09-20",
                race=11,
                region="서울",
                grade=row.grade,
                band=row.band,
                horse_id=row.horse_id,
                horse_name=row.horse_name,
                rank=int(row["rank"]),
                finish=float(row.finish),
                closing4c=float(row.closing4c),
                last200=float(row.late),
                relative4c=float(a.loc["closing4c", "relative_speed"]),
                par4c=float(a.loc["closing4c", "par"]),
                delta4c_pp=float(a.loc["closing4c", "delta_pp"]),
                relative200=float(a.loc["late", "relative_speed"]),
                delta200_pp=float(a.loc["late", "delta_pp"]),
            )
        )
    analysis.save_json(OUT / "examples.json", examples)

    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 11}
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for ax, meet, part in zip(axes, ["서울", "부산"], ["closing4c", "last400"], strict=True):
        t = (
            table[table.meet.eq(meet) & table.band.eq("건조") & table.part.eq(part)]
            .set_index("grade")
            .loc[GRADES]
        )
        raw = (
            distribution[
                distribution.meet.eq(meet)
                & distribution.band.eq("건조")
                & distribution.part.eq(part)
                & distribution.cohort.eq("all")
            ]
            .set_index("grade")
            .loc[GRADES]
        )
        x = np.arange(len(GRADES))
        ax.scatter(x - 0.08, raw["mean"], label="전체 출전마 관측 평균", color="#718096", s=45)
        # A bootstrap interval need not contain the original point estimate.
        ax.vlines(x + 0.08, t.ci_low, t.ci_high, color="#126e82", linewidth=2)
        ax.scatter(x + 0.08, t.par, label="좋은 기록 집단 par 후보·95% 구간", color="#126e82", s=48)
        ax.set_xticks(x, GRADES)
        ax.set_ylabel("구간 상대속도 (%)")
        ax.set_title(f"{meet} {LABELS[part]} · 건조")
        ax.grid(axis="y", alpha=0.2)
        ax.legend(loc="lower right", fontsize=9)
    fig.suptitle(
        "평균적인 전개와 좋은 전체 기록의 전개를 구분\n최근2024~2026년·완화 추정 후보, 서울530m는 명목 거리",
        fontsize=13,
    )
    fig.savefig(OUT / "relative_speed_par_comparison.png", dpi=170)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4.8), layout="constrained")
    a = ablation.sort_values(["meet", "year"])
    y = np.arange(len(a))
    ax.hlines(
        y,
        a.paired_delta_ci_low * 1000,
        a.paired_delta_ci_high * 1000,
        color="#126e82",
        linewidth=2.5,
    )
    ax.scatter(a.delta_seconds * 1000, y, color="#126e82", s=45)
    ax.axvline(0, color="#a54e38", linestyle="--", linewidth=1)
    ax.set_yticks(y, [f"{r.meet} {r.year}" for r in a.itertuples()])
    ax.invert_yaxis()
    ax.set_xlabel("추가 모형 MAE - 기본 모형 MAE (밀리초) · 날짜 재표집95% 구간")
    ax.set_title(
        "과거 구간 상대속도를 추가한 전체시간 예측\n음수는 개선·양수는 악화, 여섯 비교 모두 0 포함"
    )
    ax.grid(axis="x", alpha=0.2)
    fig.savefig(OUT / "history_prediction_ablation.png", dpi=170)
    plt.close(fig)

    general = distribution[
        (distribution.grade.eq("ALL"))
        & (distribution.band.eq("ALL"))
        & distribution.cohort.eq("all")
    ]
    general_rows = []
    for row in general.itertuples():
        pooled = table[table.meet.eq(row.meet) & table.part.eq(row.part)].region.iloc[0]
        general_rows.append(
            [
                row.meet,
                LABELS[row.part],
                str(row.n),
                f"{row.mean:.2f}",
                f"{row.p20:.2f}~{row.p80:.2f}",
                f"{pooled:.2f}",
                STRUCTURES[selected[row.meet + "|" + row.part]],
            ]
        )
    general_table = md_table(
        pd.DataFrame(
            general_rows,
            columns=[
                "지역",
                "구간",
                "출전",
                "전체 평균%",
                "P20~P80%",
                "지역 공통 후보%",
                "선택 구조",
            ],
        )
    )
    dry_rows = []
    for meet in ["서울", "부산"]:
        for grade in GRADES:
            t = table[
                table.meet.eq(meet) & table.grade.eq(grade) & table.band.eq("건조")
            ].set_index("part")
            closing = "closing4c" if meet == "서울" else "last400"
            c = t.loc[closing]
            dry_rows.append(
                [
                    meet,
                    grade,
                    f"{t.loc['late', 'par']:.2f}",
                    f"{t.loc['last600', 'par']:.2f}",
                    f"{c.par:.2f} [{c.ci_low:.2f}, {c.ci_high:.2f}]",
                    f"{c.reference_n} / {c.reference_races} / {c.reference_dates}",
                ]
            )
    dry_table = md_table(
        pd.DataFrame(
            dry_rows,
            columns=[
                "지역",
                "등급",
                "마지막200m%",
                "마지막600m%",
                "서울530m* / 부산400m%·95%구간",
                "해당셀 두/경주/일",
            ],
        )
    )
    validation_rows = []
    for (meet, part), row in mean_test.iterrows():
        reg = temporal[
            temporal.stage.eq("test")
            & temporal.meet.eq(meet)
            & temporal.part.eq(part)
            & temporal.structure.eq("region")
        ]
        validation_rows.append(
            [
                meet,
                LABELS[part],
                f"{row.cell_mae:.3f}",
                f"{reg.cell_mae.mean():.3f}",
                f"{row.runner_mae:.3f}",
                f"{row.bias:+.3f}",
            ]
        )
    validation_table = md_table(
        pd.DataFrame(
            validation_rows,
            columns=[
                "지역",
                "구간",
                "선택 셀평균 MAE%p",
                "공통 셀평균 MAE%p",
                "개별 MAE%p",
                "기준−실측 편향%p",
            ],
        )
    )
    ablation_rows = [
        [
            r.meet,
            r.year,
            f"{r.baseline_mae_seconds:.4f}",
            f"{r.added_mae_seconds:.4f}",
            f"{r.delta_seconds:+.4f}",
            f"[{r.paired_delta_ci_low:+.4f}, {r.paired_delta_ci_high:+.4f}]",
            f"{r.history_available_share * 100:.1f}%",
        ]
        for r in ablation.itertuples()
    ]
    ablation_table = md_table(
        pd.DataFrame(
            ablation_rows,
            columns=[
                "지역",
                "연도",
                "기본 MAE초",
                "+과거비율 MAE초",
                "추가−기본초",
                "차이95%구간초",
                "과거1200m 있음",
            ],
        )
    )
    example_rows = [
        [
            e["horse_name"],
            e["rank"],
            f"{e['finish']:.1f}",
            f"{e['closing4c']:.1f}",
            f"{e['relative4c']:.2f}",
            f"{e['delta4c_pp']:+.2f}",
            f"{e['last200']:.1f}",
            f"{e['relative200']:.2f}",
            f"{e['delta200_pp']:+.2f}",
        ]
        for e in examples
    ]
    example_table = md_table(
        pd.DataFrame(
            example_rows,
            columns=[
                "말",
                "착순",
                "전체초",
                "4C이후초",
                "4C비율%",
                "후보편차%p",
                "마지막200m초",
                "200m비율%",
                "후보편차%p",
            ],
        )
    )
    sensitivity_rows = []
    for (meet, variant), a in sensitivity.groupby(["meet", "variant"]):
        sensitivity_rows.append(
            [
                meet,
                variant,
                f"{a.difference_pp.abs().mean():.3f}",
                f"{a.difference_pp.abs().max():.3f}",
            ]
        )
    sensitivity_table = md_table(
        pd.DataFrame(
            sensitivity_rows, columns=["지역", "참조 변경", "평균 절대변화%p", "최대 절대변화%p"]
        )
    )

    report = f"""# 서울·부산1200m 구간 상대속도와 기준 전개 후보 v1

2026-10-04 완료. **구간 상대속도를 전개 설명에 사용할 수 있고,100% 대신 구간·지역별 기준이 필요하다. 다만 이번par는 좋은 기록 집단의 완화 추정 후보이며,최적 전개나 예측 개선은 확정하지 못했다.**

전체 정상 실전1200m41,623행 중 최근2024년 이후13,313행을 분포 참조로 삼았다. 서울7,897행·743경주·269일,부산5,416행·501경주·256일이다. 종료일은 서울2026-09-20,부산2026-09-18이다. 최종par 참조는 서울153경주459두·107일,부산105경주315두·80일이다. 영천·제주·주행심사·주로빠르기는 제외했다. 원천과 운영 모델을 변경하지 않았다.

## 무엇을 계산했는가

`R = (구간거리/구간시간) ÷ (1200m/전체시간) × 100`

비율은 각 출전에서 계산한 뒤 평균·분위수를 구한다. 전체 평균시간÷구간 평균시간으로 대신하지 않는다.100%는 자기 전체 평균속도와 같다는 뜻이다. 초반 가속·코스 구조 때문에 각 구간의 일반적인 수준은 다르다. 높은 비율20%·낮은 비율20%는 상대적인 전개 비중이며 좋은/나쁜 능력20%가 아니다. 비율 편차의 단위는%p다.

{general_table}

*서울530m·330m는 공식 설명의 명목 계측거리다. 실제 주행 경로·계측점 좌표를 검증한 물리 속도가 아니다. G3F→4C의 시간 차와 명목 거리의 정합성도 후속 좌표 검증 대상이다.400m와 같게 해석하거나 코너 가속·손실로 환산하지 않는다. 마지막600m·4C 이후·마지막200m는 겹치므로 점수를 합산하지 않는다.*

## 평균과 par 후보를 구분한 방법

Timeform의 좋은 전체 기록 기반par 접근에 착안했다. 프로젝트 자체 선정 규칙은 **등급·함수율·월·성별·나이·부담중량·rating·기존 이력 등을 고려한 전체시간 기대값 대비 우승 기록이 등급별 빠른20%인 경주에서 상위3두**다. 현재 결과를 이용한 사후 참조 선정이다. 우승마만이 아니라 상위3두를 사용하고 경주마다 총 가중치1을 주었다. Timeform의 한국 기준이나 정확한 원 알고리즘을 가져온 것이 아니다. 빠른 기록을 만든 전개가 효율의 원인이라는 인과 검증도 아니다.

전체시간 기대모형은 기존 Ridge(alpha10) 전처리를 재사용했다. 개발2021~2023년에는 해당 연도 이전 자료로 학습하고 이전3년만 참조해,지역 공통·등급·등급+함수율·등급×함수율 후보를 비교했다. 셀의 실측평균에 대한 MAE가 최소+0.01%p 이내면 단순한 구조를 골랐다. 테스트2024~2026년에는 구조를 고정하고 연도별로 이전 자료만 사용했다. 테스트 집단도 과거 모형과 과거 우승 잔차 경계로 골랐다. 테스트 연도에서 상위20% 경계를 다시 맞추지 않았다.

등급 평균은 지역 기준에40경주 강도로 완화한다. 함수율별 잔차도40경주 강도로 완화하고,개별 등급×상태의 추가 잔차는20경주 강도로 완화한다. 최종 참고값은 전체2018년 이후 기대모형과 최근2024년 이후 참조에서 다시 계산했으므로 **최종표를 과거 예측 검증에 소급하지 않는다.**

## 등급·함수율 기준을 얼마나 믿을 수 있는가

서울350개·부산300개 구간 셀,총650개 후보를 보존했다. 동일한 후보가 여러 셀에 반복되는 경우는 지역 공통 구조를 선택했기 때문이다. 건조·양호·다습·포화·불량을 모두 제공하지만,함수율 차이를 무조건 따로 부여하지 않았다.

해당 셀에 빠른 경주 상위마60두·20경주·20일 이상이면 `local_supported`로 표시했다. 이 기준을 만족하는 것은 부산 국6 건조의6개 구간뿐이다. 서울329·부산240개는 `smoothed_sparse`,최근 관측 자체가 없는 서울21·부산54개는 `unobserved`다. **세분화한 셀의 대부분은 자체 관측값으로 확정할 수 없다.** 지역 공통 후보는 각각 서울459두·153경주,부산315두·105경주를 사용한다. 셀 표본 상태와 빌려온 상위 집단의 근거를 구분해야 한다. 좁은 구간은 소표본의 독립적인 효과를 증명하지 않는다.

날짜200회 재표집마다 전체시간 모형을 다시 적합하고 빠른 경주를 다시 선정해par를 재추정했다. 전처리·구조는 고정했다. 따라서95%구간은 **선택한 모형·최근 참조 정의 안의 조건부 불확실성**이다. 모형 가정·기준선 변화·거리 좌표·구조 선정의 불확실성을 전부 포괄하지 않는다. 각 구간의 주변 평균 후보를 연결해 하나의 정확한 전체 시간배분으로 환산하지 않는다.

아래는 건조의 일부 등급 예시이며 전체 상태·원천 등급10종은CSV/JSON에 있다.

{dry_table}

![평균과 후보 비교](outputs/relative_speed_par_comparison.png)

## 다음 연도에서도 유지되는가

아래 오차는2024·2025·2026년의 연도별 결과를 동일 가중 평균한 값이다. 셀평균 비교에는 최소5두·3경주·3일인 테스트 셀을 사용했다. 개별 MAE는 경주를 동일 가중했다. **사후 좋은 기록 집단의 비율 기준 재현성**을 검사한 것이며 착순 예측이 아니다. 이전에 분석한 자료의 후향 시간순 검증으로,새 미래 자료를 기다려 검증한 결과도 아니다.

{validation_table}

세분화가 전반적으로 도움이 됐지만 서울200~600m는 지역 공통보다 셀평균 오차가 조금 더 컸다. 서울 마지막200m·4C 이후는 평균 기준이 이후 집단의 비율보다 각각 약0.91·0.69%p 높게 나타났다. 후보표를 소수점 단위 확정 최적값으로 읽지 않는 이유다. 기본 설명은 지역 공통과 관측 범위를 먼저 보여주고,등급·함수율 후보를 연구 상세로 연결하는 것이 적절하다.

## 선정·이상치에 따른 변화

기본 모집단의 사고·물리 이상 계측 제외를 이어 사용했다. 본 분석에서 빠르거나 느리다는 이유만으로 정상 기록을 삭제하지 않았다. 민감도 검사는 빠른 우승 잔차10%/30%,각 구간 비율 양끝1% 절사,전체 경주의 상위3두로 참조를 바꾼 경우다. 본 기준은20%다. 구조는 다시 선택하지 않았다.

{sensitivity_table}

극단 비율1% 절사의 변화는 작았지만 선정 방식 자체를 바꾸면 서울 일부 셀에서1%p 이상 달라졌다. 최적 효율을 확정하기 위해서는 좋은 기록 정의·연도 이동·추가 구간거리 검증을 더 해야 한다.

## 과거 비율을 넣으면 사전 기록 예측이 개선되는가

별도 Ridge 전체시간 예측에서 동일한 기존 메타정보·과거 기록 입력에,그 말의 이전 정상1200m 최대3회 상대속도 평균과 이력 수를 추가했다. 독립4구간·마지막600m·지역별4C/400m를 사용했다. 모든 이력은 날짜를 한 출전 이상 밀었고 지역 이동 이력도 과거라면 포함했다. 현재 전체시간·구간·착순·최종par는 입력하지 않았다. 현재 함수율은 두 모형 모두 입력에서 제외했다. 입력 스케일러·결측 대체·회귀는 각 평가연도 이전 자료에서만 학습했다.

오차는 경주 동일 가중 MAE다. 차이는 날짜2,000회 짝 재표집이며 적합된 두 모형을 고정한 조건부 구간이다.

{ablation_table}

**여섯 비교 모두 오차 차이의95%구간에0이 포함됐다.** 서울은 세 연도 모두 점 추정이 조금 악화됐고 부산은 일부 연도 소폭 개선됐지만 뚜렷한 추가 예측 가치를 입증하지 못했다. 표본이 정상 실전1200m로 제한되고 과거 이력도 이 선택 표본에 한정된다. 기존 메타정보가 모두 등록 마감 전에 공개됐다는 원천 시점 감사는 수행하지 않았으므로 실제 사전 발행 가능성을 검증한 모형도 아니다. 기존 피처와의 중복·승급/거리 변경·다른 모델 구조는 추가 과제다. 운영 모델이나 승률·수익 성능 개선으로 표현하지 않는다.

![과거 비율 예측 추가 검증](outputs/history_prediction_ablation.png)

## 실제 기록을 읽는 예시

2026-09-20 서울11경주 혼4·건조. 아래 편차는 **최종표로 한 후향 평가**다. 당시 사전 예측이 아니다.

{example_table}

이스트라코타는4C 이후 상대속도와 편차가 가장 높지만6착이었다. 팬텀프린스는 전체 기록이 더 빠르고1착이다. 높은 마무리 비율은 전체 기록 중 후반을 빠르게 달린 비중을 설명한다. 기존 시간 기준점수·전체시간·구간시간·실제 순위/시간차 회복과 함께 읽어야 한다. 편차를 초 단위 보정,우승확률,종합 능력점수로 바꾸지 않는다.

## 보존과 적용 상태

새 전체/구간 보정은 채택하지 않았다. 전체시간 함수율 환산의 기존 서울80%·부산90% 결정과 구간 보정 보류 상태를 유지한다. 웹 화면 구현·배포는 수행하지 않았다. 게시 준비 자료는 [독자용 요약](PUBLICATION.md)과 [웹 기준JSON](outputs/web_relative_speed_par.json)이다. 명목거리 표식·연구 후보 상태·소표본·기간·참조집단을 함께 게시해야 한다.

- [상세 분포](outputs/relative_speed_distributions.csv): 지역·등급·상태·전체/우승/상위3/하위3 착순 집단의 평균·분위수·높은/낮은 비율20%.
- [par 후보650셀](outputs/par_candidates.csv),[시간순 검증](outputs/temporal_par_validation.csv),[선정 경주](outputs/selected_fast_races.csv),[민감도](outputs/sensitivity.csv).
- [기록 예측 비교](outputs/history_prediction_ablation.csv),[출전별 비율](outputs/population_relative_speed.parquet),[최근 출전별 후보 편차](outputs/recent_runner_relative_speed.parquet),[실제 사례](outputs/examples.json).
- [계획](PLAN.md),[출처](SOURCES.md),[분석](analyze.py),[독립 검증](verify.py),[검증 결과](outputs/verification.json),[입력 해시·선정 설정](outputs/summary.json).
- [중앙 결론](../conclusions/10_RELATIVE_SPEED_PAR.md),[이번 작업 용량](outputs/artifact_inventory.json).

다음에는 새 날짜에서 기준의 이동을 확인하고,서울4C 계측 좌표와 시대별 정의를 대조하며,각 말의 비율 반복성과 전체 기록 수준·전개를 함께 평가하는 방식을 검증할 수 있다.
"""
    (HERE / "README.md").write_text(report, encoding="utf-8")
    publication = f"""# 구간 상대속도로1200m 전개 읽기

2026-10-04 연구 후보v1. 서울·부산1200m,자료 종료일 서울2026-09-20·부산2026-09-18.

전체 기록이 같은 말도 초반과 후반의 속도 배분은 다를 수 있다. 구간 상대속도는 구간 평균속도를 자기 전체 평균속도와 비교한다.100%는 둘이 같다는 뜻이다. 높은 마무리 비율만으로 좋은 말이나 우승마를 정할 수는 없다.

최근 전체 출전마의 마지막200m 평균은 서울91.43%,부산92.24%다. 좋은 전체 기록이 나온 경주의 상위마들로 만든 지역 공통 후보는 각각93.31%,93.85%였다. 마지막600m 후보는 서울98.37%,부산98.88%,서울4C 이후 명목530m는103.38%,부산 마지막400m는97.43%다.100%를 모든 구간의 기준으로 고정하지 않는다.

등급·함수율별 값도 계산했지만 표본이 작아 대부분 상위 집단의 값을 빌린 완화 추정이다. 전체 출전마의 평균과 좋은 기록 집단의par 후보를 구분한다. 후보는 최적 효율을 확정한 값이 아니며,초 단위 보정이나 운영 모델에 적용하지 않았다. 다음 연도 검증에서 평균 기준 이동도 관찰됐다.

## 기록과 전개를 함께 읽기

2026-09-20 서울11경주 혼4·건조의 실제 예시다. 최종 연구 기준으로 후향 평가했다.

{example_table}

이스트라코타는 막판 상대속도가 높았지만6착이다. 팬텀프린스는 더 빠른 전체 기록으로 우승했다. ‘후반 비중이 컸다’와 ‘전체 수준이 높다’를 함께 확인해야 한다. 시간 기준점수·전체/구간시간·통과순위·선두 시간차 회복을 연결해 읽고,겹치는 막판 구간의 점수를 합산하지 않는다.

## 예측과 거리의 한계

과거1200m 구간 비율을 추가한 전체시간 예측의2024~2026년 여섯 비교에서는 뚜렷한 개선을 입증하지 못했다. 이번 결과는 전개를 설명하는 연구용 지표다.

서울4C530m는 공식 설명의 명목 거리다. 실제 경로 길이나 계측점 좌표를 확정한 물리 속도가 아니다. 부산400m와 동일한 구간으로 비교하지 않는다. 정확한 코너 가속·외측 거리 손실·최적 에너지 분배는 별도 검증이 필요하다.

[원 연구·전체 표·검증](README.md),[공식·방법 출처](SOURCES.md),[웹에 연결할 기준 데이터](outputs/web_relative_speed_par.json). 웹 게시와 운영 보정 반영은 아직 수행하지 않았다.
"""
    (HERE / "PUBLICATION.md").write_text(publication, encoding="utf-8")
    stats = dict(
        test_mean_by_section=mean_test.reset_index().to_dict("records"),
        sensitivity=sensitivity.groupby(["meet", "variant"])
        .difference_pp.apply(lambda x: float(x.abs().max()))
        .reset_index(name="max_abs_difference_pp")
        .to_dict("records"),
        ablation_all_intervals_include_zero=bool(
            ((ablation.paired_delta_ci_low <= 0) & (ablation.paired_delta_ci_high >= 0)).all()
        ),
    )
    analysis.save_json(OUT / "report_statistics.json", stats)
    print("Research report, publication summary, examples, web export and two figures rendered")


if __name__ == "__main__":
    main()

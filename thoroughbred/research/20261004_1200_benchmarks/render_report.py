"""Render a standalone research figure, benchmark tables and a readable report."""
# ruff: noqa: E501 -- Korean report prose is kept in complete sentences.

import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from analyze import BANDS, GRADES, HERE, OUT
from evaluate_record import evaluate


def number(value, digits=2):
    return "—" if pd.isna(value) else f"{value:.{digits}f}"


def table_markdown(g):
    lines = [
        "| 등급 | 관측 행/경주/일 | 관측 평균 | 추정 평균 | 빠른20% 경계 | 중앙 | 느린20% 경계 | 빠른20% 평균 | 느린20% 평균 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for grade in GRADES:
        r = g[g.grade.eq(grade)].iloc[0]
        support = " *" if r.status != "observed_supported" else ""
        lines.append(
            f"| {grade}{support} | {r.observed_n}/{r.observed_races}/{r.observed_days} | "
            + " | ".join(
                number(r[k])
                for k in [
                    "observed_mean",
                    "mean",
                    "p20",
                    "median",
                    "p80",
                    "fast20_mean",
                    "slow20_mean",
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main():
    b = pd.read_csv(OUT / "estimated_benchmarks.csv")
    f = b[b.part.eq("finish")]
    summary = json.loads((OUT / "summary.json").read_text())
    verification = json.loads((OUT / "verification.json").read_text())
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    fig, axes = plt.subplots(1, 2, figsize=(14, 7), sharey=True)
    colors = ["#205d96", "#ad4b26"]
    for ax, meet, color in zip(axes, ["서울", "부산"], colors, strict=True):
        g = f[f.meet.eq(meet) & f.band.eq("건조")].set_index("grade").loc[GRADES]
        y = np.arange(len(GRADES))
        ax.hlines(y, g.p20, g.p80, color=color, lw=8, alpha=0.22, label="가운데60% 기록 범위")
        ax.scatter(g["mean"], y, s=45, color=color, label="전체 평균", zorder=3)
        ax.scatter(g.fast20_mean, y, marker="<", s=45, color="#21815c", label="빠른20% 평균")
        ax.scatter(g.slow20_mean, y, marker=">", s=45, color="#b55153", label="느린20% 평균")
        ax.set_yticks(y, GRADES)
        ax.set_title(f"{meet}1200m · 건조 기준 추정", fontsize=16, pad=14)
        ax.set_xlabel("전체 기록(초) · 왼쪽일수록 빠름", fontsize=12)
        ax.grid(axis="x", alpha=0.15)
        ax.set_xlim(70, 81)
        ax.tick_params(axis="y", labelleft=True)
    axes[0].invert_yaxis()
    axes[0].legend(loc="lower left", bbox_to_anchor=(0, -0.23), ncol=2, fontsize=10, frameon=False)
    fig.suptitle("등급별 기록의 감을 잡는1200m 기준표", fontsize=20, y=0.98)
    fig.text(
        0.5,
        0.02,
        "2024년 이후 참조분포 · 함수율 효과를 맞춘 연구용 추정 · OPEN과 부산 상위등급은 소표본",
        ha="center",
        fontsize=10,
        color="#555555",
    )
    fig.subplots_adjust(top=0.86, bottom=0.20, wspace=0.12)
    fig.savefig(OUT / "dry_grade_benchmarks.png", dpi=160, facecolor="white")
    plt.close(fig)

    detailed = [
        "# 서울 부산1200m 등급과 주로상태별 전체 기록표\n",
        "단위는 초.2024년 이후 참조분포를 각 함수율 상태로 맞춘 추정치이며 관측 평균을 함께 표시한다. "
        "빠른20% 경계 이하는 빠른 쪽, 느린20% 경계 이상은 느린 쪽이다. 꼬리 평균은 경계값과 다르다. "
        "별표는 최근200행·20경주·20일 중 하나라도 미달하거나 최근 관측이 없는 조합이다. "
        "원시 자료의 부재를 실제 관측으로 바꾸지 않는다.\n",
    ]
    for meet in ["서울", "부산"]:
        for band in BANDS:
            detailed += [
                f"## {meet} {band}\n",
                table_markdown(f[f.meet.eq(meet) & f.band.eq(band)]),
                "",
            ]
    (HERE / "ALL_BENCHMARKS.md").write_text("\n".join(detailed), encoding="utf-8")

    examples = [
        evaluate("서울", "국5", "건조", "finish", 75.0),
        evaluate("서울", "국5", "포화", "finish", 75.0),
        evaluate("부산", "국6", "건조", "finish", 79.0),
    ]
    (OUT / "lookup_examples.json").write_text(
        json.dumps(examples, ensure_ascii=False, indent=2) + "\n"
    )
    methods = pd.DataFrame(summary["mean_validation"]).set_index(["meet", "method"])
    hidden = pd.DataFrame(summary["hidden_cell_validation"]).set_index("meet")
    rates = pd.DataFrame(summary["threshold_validation"]).set_index("meet")
    effects = f[f.grade.eq("국5")].set_index(["meet", "band"]).state_shift_from_dry
    status = {m: g.status.value_counts().to_dict() for m, g in f.groupby("meet")}
    e = examples[0]
    ep = examples[1]
    sections = [
        "# 서울 부산1200m 기록 평가 기준\n",
        "2026년10월4일. **영천을 제외하고 서울·부산의10개 원천등급×5개 함수율 상태100조합의 추정 기록표를 만들었다. "
        "빠른20%·가운데60%·느린20%의 범위와 평균을 나눴고, 같은 등급 안의 기록점수와1200m 전체등급 기록점수를 제공한다.** "
        "이 표는 한 번의 기록 수준을 읽는 연구용v1 기준이다.\n",
        "## 어떤 숫자를 읽을 것인가\n",
        "평균은 전체 유효 완주마의 산술평균이고 중앙값은 기록의 한가운데다. 빠른20% 평균은 빠른 쪽 꼬리에 속한 기록의 평균, "
        "P20는 그 집단에 들어가는 경계다. 느린20%도 평균과P80 경계를 구분한다. "
        "동률 때문에 실제 꼬리의 비중이 정확히20%가 아닐 수 있다. 전체 평균과 가운데60% 평균도 서로 다른 값이다.\n",
        "| 기록 점수 | 같은 비교집단에서의 해석 |\n|---:|---|\n"
        "| 90 이상 | 빠른 상위10% 수준 |\n| 80 이상 | 빠른 상위20% 수준 |\n"
        "| 50 전후 | 중앙 수준 |\n| 20~80 | 가운데60% 범위 |\n| 20 미만 | 느린 하위20% 수준 |\n| 10 미만 | 느린 하위10% 수준 |\n",
        "점수는 자신보다 느린 참조기록 비율×100이며 동률은 절반을 반영한다. "
        "50점은 평균초가 아니라 중앙값 수준이다. 백분위 점수는 시간 차이와 선형 관계가 아니다. "
        "80점이 우승확률80%나 승급 가능성80%라는 뜻은 아니다.\n",
        "같은 등급 점수는 해당 지역·거리·등급·주로의 기록과 비교한다. 전체등급 점수는 같은 지역1200m 전체 등급을 "
        "건조로 맞춘 고정 참조집단에서 비교한다. 따라서 국6과1등급의 같은 등급90점을 절대능력이 같다고 읽지 않는다. "
        "전체등급 점수도 경마장·다른 거리와 공통 절대척도가 아니며 출전 등급 구성에 영향을 받는다.\n",
        "## 서울 부산의 건조 기준\n",
    ]
    for meet in ["서울", "부산"]:
        sections += [f"### {meet}\n", table_markdown(f[f.meet.eq(meet) & f.band.eq("건조")]), ""]
    sections += [
        "![등급별 범위와 상하위 평균](outputs/dry_grade_benchmarks.png)\n",
        "건조 추정평균이 실제 건조 평균과 다른 이유는, 건조에서 관측된 말만 평균한 값이 아니라 "
        "같은 등급의 최근 전체 출전기록을 건조 상태로 맞춘 공통 참조분포이기 때문이다. "
        "원시 평균은 별도 필드로 보존했다.\n",
        "## 모든 주로상태와 구간\n",
        "[100조합 전체시간 표](ALL_BENCHMARKS.md), [전체시간CSV](outputs/whole_time_benchmarks.csv), "
        "[전체·구간650행CSV](outputs/estimated_benchmarks.csv)에 기록을 남겼다. "
        "출발200·중간①400·중간②400·막판200은 서로 겹치지 않는 구간이며 합계가1200m 전체다. "
        "막판600·부산400은 겹치는 보조 구간이다. 서울400은 원천이 없어 생성하지 않았다.\n",
        "각 구간의 빠른20%는 그 구간이 빠른 기록 집단이다. [전체기록 상하위 집단의 구간표](outputs/estimated_finish_cohorts.csv)는 "
        "전체시간으로 집단을 먼저 고르고 같은 말들의 구간을 평균한 별도 결과다. "
        "[착순상위3위·하위3위](outputs/observed_rank_cohorts.csv)는 실제 착순으로 구분한 관측 평균이며 미관측 셀은 추정하지 않았다.\n",
        "## 함수율 효과와 빈 조합의 추정\n",
        "같은 등급의 최근 기록 각각에 `예측(대상상태)−예측(관측상태)`만 더했다. "
        "말의 능력·중량·월·연도 등 구성은 참조집단으로 고정하고 상태만 바꾼다. "
        "모형에 과거 능력 이력을 넣어도 표의 점수를 개별 말의 잠재능력 추정치로 바꾸지는 않는다. "
        "분산이 상태에 따라 달라지는 효과까지 추정한 것이 아니라, 시간 분포가 이동한다는 가정을 사용했다.\n",
        "| 지역 | 건조 | 양호 | 다습 | 포화 | 불량 |\n|---|---:|---:|---:|---:|---:|",
    ]
    for meet in ["서울", "부산"]:
        sections.append(
            f"| {meet} | " + " | ".join(f"{effects[meet, band]:+.3f}" for band in BANDS) + " |"
        )
    sections += [
        "\n건조 대비 전체시간의 추정 차이(초). 양수는 느린 방향, 음수는 빠른 방향이다. "
        "양호·다습을 강제로 건조보다 빠르게 만들지 않았다.2021~2023 개발평가에서 등급별 추가상태 효과를 "
        "완화한 후보보다 지역 공통효과 후보가 선택되어, 이v1에서는 같은 지역의 등급들이 위 차이를 공유한다. "
        "이 표는 기존 전체시간 서울80%·부산90% 환산이나 운영 구간보정을 개정한 표가 아니다.\n",
        f"최근 관측은 서울47/50·부산41/50 조합이다. 최근에 없는12조합도 추정했지만 이 중5조합은 "
        f"2018년 이후 전체 승계자료에도 없다. 최근 표본이 충분한 조합은 서울{status['서울'].get('observed_supported', 0)}개·"
        f"부산{status['부산'].get('observed_supported', 0)}개다. "
        "최근 미관측·과거 미관측·소표본을 별도 필드로 구분했다.\n",
        "날짜 단위200회 재표집으로 평균·P20·중앙값·P80의 조건부95% 구간을 계산했다. "
        f"참조등급이 없는 반복은 해당 등급에서만 제외했고 최소 유효 반복은{verification['min_valid_bootstrap']}회다. "
        "전처리와 선택된 모형 구조를 고정한 재표집이며, 모든 모형 오류·전개·미래 변화까지 포함하는 범위가 아니다. "
        "평균의 구간과 개별 말의 예상기록 범위를 혼동하지 않는다.\n",
        "## 과거를 숨긴 검증\n",
        "2024·2025·2026 각각 이전 연도만 학습했고 기준분포는 평가 이전 최대3년으로 제한했다. "
        "동일한3년 참조기간의 원시 등급×상태 평균과 비교한 기준표 오차는 다음과 같다. "
        "모형의 개별 말 조건부 예측이 더 낮은 오차를 보였더라도 그 수치를 이 단순 기준표의 성능으로 대신 쓰지 않는다.\n",
        "| 지역 | 원시 셀평균 오차 | 추정 기준평균 오차 | 숨긴 조합 수 | 숨긴 조합 복원 오차 | 복원오차P90 |\n"
        "|---|---:|---:|---:|---:|---:|",
    ]
    for meet in ["서울", "부산"]:
        sections.append(
            f"| {meet} | {methods.loc[(meet, 'cell_raw_fallback'), 'cell_mean_mae']:.3f} | "
            f"{methods.loc[(meet, 'benchmark_shift_reference'), 'cell_mean_mae']:.3f} | "
            f"{hidden.loc[meet, 'cells']:.0f} | {hidden.loc[meet, 'mean_abs_error']:.3f} | "
            f"{hidden.loc[meet, 'p90_abs_error']:.3f} |"
        )
    sections += [
        "\n단위는 초. 연도×등급×상태 셀을 동등하게 평균한 절대오차다. ",
        "평균오차 감소는 서울·부산 모두 작아 확정적인 최적기록으로 부르지 않는다. "
        "조합 복원은 관측이 있던 조합을 모두 숨겨 검증한 결과다. 실제로 관측이 전혀 없는5조합은 "
        "직접 정답 검증을 할 수 없어 공통효과와 등급 참조집단의 가정에 의존한다.\n",
        f"과거 시간순 평가에서 빠른20% 경계 이하의 비율은 서울{rates.loc['서울', 'fast20_share']:.1%}·"
        f"부산{rates.loc['부산', 'fast20_share']:.1%}, 느린20% 경계 이상은 서울{rates.loc['서울', 'slow20_share']:.1%}·"
        f"부산{rates.loc['부산', 'slow20_share']:.1%}였다. "
        "따라서 향후 기록을 정확한20% 확률로 분류하는 보정이 완성된 것은 아니다. "
        "이미 살펴본 자료의 후향 시간순 검증이며 신규 미래 테스트가 아니다.\n",
        "## 실제 기록을 읽는 예시\n",
        f"가상 입력으로 서울 국5·건조75.0초를 넣으면 같은 등급 기록점수{e['same_grade_record_score']:.1f}, "
        f"전체등급 기록점수{e['all_grade_distance_record_score']:.1f}다. "
        f"평균{e['estimated_mean_seconds']:.2f}초보다{e['seconds_faster_than_mean']:.2f}초 빠르고 "
        f"상위20% 경계{e['fast20_boundary_seconds']:.2f}초보다 빠르다. "
        f"동일한75.0초라도 포화에서는 같은 등급 점수{ep['same_grade_record_score']:.1f}로 달라진다.\n",
        "```sh\nPYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261004_1200_benchmarks/evaluate_record.py \\\n"
        "  --meet 서울 --grade 국5 --band 건조 --time 75.0\n```\n",
        "`--part late --time 13.2`처럼 구간을 바꿀 수 있다. `last400`은 부산만 제공한다. "
        "현재 최종표는2026년10월4일 버전의 후향 기준이므로 과거 경주에 적용한 값을 사전 평가로 표현하지 않는다. "
        "[시간순 기록 점수](outputs/historical_record_scores.parquet)와 "
        "[말별 최근 기록 예시](outputs/latest_horse_record_examples.csv)는 해당 평가연도 이전 자료만 사용했다. "
        "후자는 말의 최신1200m 한 기록 예시이며 여러 출전의 종합능력 점수가 아니다.\n",
        "## 앞으로 거리별로 유지할 연구 계약\n",
        "같은 지역·거리에서 등급별 전체·구간 평균과 중앙값, P10·P20·P80·P90, 꼬리평균, "
        "실제착순 집단, 함수율 추정 상태, 같은등급 점수·전체등급 점수를 함께 보존한다. "
        "새 거리마다 구간 정의·주로효과·분포를 다시 계산하며1200m의 초 차이나 점수표를 복사하지 않는다. "
        "처음에는 한 번의 기록 점수를 기준으로 보고, 말의 종합평가는 향후 여러 출전의 중앙 수준·최근 변화·"
        "상위기록 재현성과 실제 초중반 전개를 함께 검증해 별도로 만든다. "
        "전체시간과 겹치는 구간점수를 임의로 더하지 않는다.\n",
        "## 원천과 검증\n",
        "원천41,623행, 최근13,313행. 자료 종료는 서울2026-09-20·부산2026-09-18이다. "
        "원천 DB에 접근하거나 수정하지 않았고, 읽은 두 입력의 SHA-256이 유지됐다. "
        f"독립SQL과 수치{verification['numeric_checks']:,}건, 시간순 점수{verification['chronological_score_checks']:,}건, "
        "계수 대조·구간 합·착순 연결·참조날짜를 검증했다.\n",
        "[계획](PLAN.md) · [출처](SOURCES.md) · [분석](analyze.py) · [기록 평가기](evaluate_record.py) · "
        "[검증](verify.py) · [검증 명세](outputs/verification.json) · [설정과 오차](outputs/summary.json) · "
        "[산출물 용량](outputs/artifact_inventory.json) · [세션 용량 원장](../ARTIFACT_SIZE_LOG.md)\n",
        "분석은 완료된outputs를 덮어쓰지 않는다. 재현은 별도 실행 폴더를 사용한다. 보고서와 그림만 재생성하려면 "
        "`MPLCONFIGDIR=/tmp/horse1200_benchmark_plot PYTHONDONTWRITEBYTECODE=1 .venv/bin/python "
        "thoroughbred/research/20261004_1200_benchmarks/render_report.py`를 실행한다.\n",
    ]
    (HERE / "README.md").write_text("\n".join(sections), encoding="utf-8")
    print("Report,100-cell table, figure and lookup examples saved")


if __name__ == "__main__":
    main()

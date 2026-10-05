"""Generate study report, a standalone plot, and day-clustered profile contrasts."""

# ruff: noqa: E501 -- Report prose stays as single paragraphs.
import json

import matplotlib
import numpy as np
import pandas as pd
from analyze import BANDS, HERE, OUT

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
NAMES = {
    "finish": "전체",
    "early": "출발200",
    "middle1": "중간①",
    "middle2": "중간②400",
    "middle": "중반합",
    "late": "마지막200",
    "last600": "마지막600",
    "last400": "마지막400",
}


def table(headers, rows):
    return "\n".join(
        ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        + ["| " + " | ".join(map(str, r)) + " |" for r in rows]
    )


def contrast(g, name="전체"):
    g = g[g.pace_middle.eq("보통")].copy()
    rows = []
    for a, b in [("느림", "보통"), ("빠름", "보통")]:
        agg = g.groupby(["date", "pace_early"]).res_late.agg(["sum", "count"])
        dates = g.date.unique()
        arrays = []
        for label in (a, b):
            v = agg.xs(label, level="pace_early").reindex(dates, fill_value=0)
            arrays.append((v["sum"].to_numpy(), v["count"].to_numpy()))
        rng = np.random.default_rng(20261003)
        idx = rng.integers(0, len(dates), (2000, len(dates)))
        means = [s[idx].sum(1) / n[idx].sum(1) for s, n in arrays]
        lo, hi = np.quantile(means[0] - means[1], [0.025, 0.975])
        point = arrays[0][0].sum() / arrays[0][1].sum() - arrays[1][0].sum() / arrays[1][1].sum()
        rows.append(
            dict(
                population=g.population.iloc[0],
                meet=g.meet.iloc[0],
                scope=name,
                early_a=a,
                early_b=b,
                middle="보통",
                difference_seconds=point,
                ci_low=lo,
                ci_high=hi,
                n_a=int(arrays[0][1].sum()),
                n_b=int(arrays[1][1].sum()),
            )
        )
    return rows


def main():
    scored = pd.read_parquet(OUT / "scored_recent.parquet")
    raw = pd.read_csv(OUT / "moisture_sections.csv")
    overall = pd.read_csv(OUT / "overall_sections.csv")
    prof = pd.read_csv(OUT / "pace_profiles.csv")
    summary = json.loads((OUT / "summary.json").read_text())
    checks = json.loads((OUT / "verification.json").read_text())
    contrasts = []
    for _, g in scored.groupby(["population", "meet"]):
        contrasts += contrast(g)
        for year, sub in g.groupby("year"):
            contrasts += contrast(sub, str(year))
    contrasts = pd.DataFrame(contrasts)
    contrasts.to_csv(OUT / "early_late_contrasts.csv", index=False)

    fig, axes = plt.subplots(2, 2, figsize=(12, 10), constrained_layout=True)
    order = ["느림", "보통", "빠름"]
    for ax, (pop, meet) in zip(
        axes.flat,
        [
            ("주행심사1000", "서울"),
            ("주행심사1000", "부산"),
            ("실전1200", "서울"),
            ("실전1200", "부산"),
        ],
        strict=True,
    ):
        sub = prof[(prof.population == pop) & (prof.meet == meet)]
        values = sub.pivot(
            index="pace_early", columns="pace_middle", values="fast_late_share"
        ).reindex(index=order, columns=order)
        count = sub.pivot(index="pace_early", columns="pace_middle", values="n").reindex(
            index=order, columns=order
        )
        mesh = ax.imshow(values * 100, vmin=0, vmax=80, cmap="YlGnBu")
        for i in range(3):
            for j in range(3):
                n = int(count.iloc[i, j])
                small = " *" if n < 20 else ""
                ax.text(
                    j,
                    i,
                    f"{values.iloc[i, j] * 100:.1f}%{small}\nn={n:,}",
                    ha="center",
                    va="center",
                    color="white" if values.iloc[i, j] > 0.5 else "#152238",
                    fontsize=12,
                )
        ax.set(
            xticks=range(3),
            yticks=range(3),
            xticklabels=order,
            yticklabels=order,
            xlabel="중반 페이스 (막판200 제외)",
            ylabel="출발200 페이스",
            title=f"{meet} {pop}",
        )
    fig.colorbar(mesh, ax=axes, shrink=0.7, label="빠른 막판200 비율 (%)")
    fig.suptitle(
        "초반·중반 전개에 따른 빠른 막판 빈도\n2024–2026 · 함수율/기본 조건을 고려한 과거 기준 · *12일 소표본",
        fontsize=16,
    )
    fig.savefig(OUT / "pace_profiles.png", dpi=160)
    plt.close(fig)

    lines = [
        "# 함수율과 구간 전개: 주행심사1000m·실전1200m",
        "",
        "2026-10-03. 주로빠르기 제외. 원천·기존 운영모형·공식 보정 결정은 변경하지 않았다.",
        "",
        "**초반과 중반이 모두 느리면 막판이 빠르다는 일반화는 성립하지 않았다. 초반은 느려도 중반을 보통 이상으로 유지한 기록에서 빠른 막판이 더 자주 나왔다. 초반이 빠르고 중반부터 처진 기록은 막판도 느린 경우가 많았다.** 이것은 개별 말의 관찰된 구간 전개이며, 의도적 페이스 조절이나 에너지 소모의 인과효과를 증명하지 않는다.",
        "",
        "## 모집단과 분석 기간",
        "",
        "주행심사는 `주행미합(신)`의 합격·불합격을 함께 사용했다. 실전은 정상 완주·순위 완전 경주의1200m이며 기존82개 품질 제외 경주는 재포함하지 않았다. 동일 말의 반복 기록을 포함하므로 표본 수는 출전행 수다. 주행심사 최근 합격마만의 이전 평균과 이번 전체 신마 집단 평균은 다르다.",
        "",
    ]
    lines.append(
        table(
            ["모집단", "지역", "최근 행", "날짜", "심사/경주", "종료일"],
            [
                [
                    pop,
                    meet,
                    f"{len(g):,}",
                    g.date.nunique(),
                    g.source_key.nunique(),
                    str(g.date.max().date()),
                ]
                for (pop, meet), g in scored.groupby(["population", "meet"])
            ],
        )
    )
    lines += [
        "",
        f"과거 학습을 포함한 유효행{summary['valid_rows']:,}; 제외{summary['excluded_rows']:,}. 주행심사 기존 물리적 구간 검증을 승계했고 함수율0/미확정7행을 추가 제외했다. 실전 연결집단41,638행 중 물리적 구간 범위를 벗어난15행을 제외했다. 부산2020-11-22의1행은400m 원천값이 전체시간76.9초와 같아400m만 결측 처리하고 나머지 유효구간을 보존했다. 분위수 상하위 꼬리를 임의 절단하지 않았다. 불합격 중 구간기록 자체가 없거나 비정상인 말은 분석하지 못하므로 전체 불합격마의 분포로 확대하지 않는다.",
        "",
        "## 독립 구간의 정의",
        "",
        table(
            ["거리", "출발", "중간①", "중간②", "막판", "전개 분류 중반"],
            [
                ["1000m", "0–200", "200–400", "400–800", "800–1000", "200–800(600m)"],
                ["1200m", "0–200", "200–600", "600–1000", "1000–1200", "200–1000(800m)"],
            ],
        ),
        "",
        "`중간①=T−G3F−S1F`, `중간②=G3F−G1F`, `막판=G1F`로 합계가 정확히 전체시간과 일치한다. 출발에는 가속이 포함되므로 출발200과 막판200의 초를 그대로 대조하지 않는다. 부산 마지막400은 API의 직접 관측값(실전 `bu_2fGTime`)이며 서울 코너 통과시간으로400m를 만들지 않았다. 마지막600과400은 중간②·막판과 겹치므로 아래 독립 구간의 합에 추가하지 않는다.",
        "",
        "## 최근 구간 기록의 전체 분포",
        "",
        "아래 값은 원시 초다. 범위는P10–P90이며 합격 최저선이나 최적 기록 기준이 아니다.",
        "",
    ]
    for (pop, meet), sub in overall.groupby(["population", "meet"]):
        lines += [
            f"### {meet} {pop}",
            "",
            table(
                ["구간", "평균", "중앙값", "P10–P90"],
                [
                    [
                        NAMES[p],
                        f"{r['mean']:.2f}",
                        f"{r['median']:.2f}",
                        f"{r['p10']:.2f}–{r['p90']:.2f}",
                    ]
                    for p in ["early", "middle1", "middle2", "late", "finish", "last600", "last400"]
                    for _, r in sub[sub.part.eq(p)].iterrows()
                ],
            ),
            "",
        ]
    lines += [
        "주행심사 신마 출발200 평균은 서울14.97·부산14.61초, 실전1200 전체등급은13.94·14.00초다. 최근 신마 합격만의 이전 기준은14.61·14.44초였다. 실전국6 출발200 평균은14.07·14.11초다. 주행심사의 초반이 실전보다 대체로 느린 모습과는 부합하지만 거리·나이·능력·출발 환경이 같지 않아 ‘무리한 초반 전개가 없다’고 확정하지 않는다. 상대적 빠름 분류는 공격적인 전개 의도를 뜻하지 않는다.",
        "",
        "## 함수율별 구간 기록",
        "",
        "건조1–5%, 양호6–9%, 다습10–14%, 포화15–19%, 불량20% 이상. 원시 평균은 당시 등급·말 구성·날짜도 반영하므로 보정계수로 직접 사용하지 않는다. 20일 미만은별표 표시.",
        "",
    ]
    for (pop, meet), sub in raw.groupby(["population", "meet"]):
        lines += [f"### {meet} {pop}", ""]
        rows = []
        for band in BANDS:
            s = sub[sub.band.eq(band)].set_index("part")
            n, days = int(s.loc["finish", "n"]), int(s.loc["finish", "days"])
            rows.append(
                [band + (" *" if days < 20 else ""), f"{n:,}/{days}"]
                + [
                    f"{s.loc[p, 'mean']:.2f}" if p in s.index else "—"
                    for p in ["early", "middle1", "middle2", "late", "finish", "last600", "last400"]
                ]
            )
        lines += [
            table(
                [
                    "함수율",
                    "행/일",
                    "출발200",
                    "중간①",
                    "중간②400",
                    "막판200",
                    "전체",
                    "막판600",
                    "부산400",
                ],
                rows,
            ),
            "",
        ]
    lines += [
        "1200m 포화·불량은 출발·중간·막판을 함께 빨라지게 하는 방향이 관찰된다. 주행심사는 특히 서울에서 원시 전체시간과 막판의 방향이 일률적이지 않고 불량 날짜도 적다. 합격마만의 함수율별 표는 [passed_moisture_sections.csv](outputs/passed_moisture_sections.csv)에 따로 보존했다.",
        "",
        "## 전개와 막판의 관계",
        "",
        "각 평가연도보다 이전 기록만으로 지역·모집단별 Ridge(alpha10) 기준을 학습했다. 함수율구간·월·성별·나이·부담중량을 반영한다. 실전은등급·rating·과거 순위/입상/초반위치·출전수·휴식간격도 추가했다. 당일 전체시간·순위·배당·합격판정은 설명변수에 넣지 않았다. 주행심사는 실제 잠재능력을 충분히 통제할 과거 이력이 없어 능력 혼합이 더 남는다.",
        "",
        "구간 잔차=실제 초−해당 구간 조건부 기준 초. 과거 학습 잔차P25보다 낮으면빠름, P25–P75는보통, P75보다 높으면느림. 최근 각 집단을 강제로25%씩 나눈 것이 아니다. 막판빠름도 과거 기준의P25 판정이다. 전체시간으로 집단을 나누지 않았다.",
        "",
        "막판의 ‘전개조건 추가 잔차’는 기본 조건에 실제 출발·중반 초를 더한 모델의 차이다. 초반 여유로 예상되는 빠른 막판과 그 전개에서도 예상보다 빠른 막판을 따로 볼 목적이다. 음수는기준보다 빠름. 집단 중앙값이 최적 Timeform par인 것은 아니다.",
        "",
        "![전개별 빠른 막판 빈도](outputs/pace_profiles.png)",
        "",
    ]
    for (pop, meet), sub in prof.groupby(["population", "meet"]):
        lines += [
            f"### {meet} {pop}",
            "",
            table(
                [
                    "출발/중반",
                    "행/일",
                    "막판200평균",
                    "기본잔차",
                    "빠른막판",
                    "전개조건 추가잔차",
                    "전개조건 대비빠름",
                ],
                [
                    [
                        f"{r.pace_early}/{r.pace_middle}" + (" *" if r.small_support else ""),
                        f"{r.n:,}/{r.days}",
                        f"{r.late_mean:.2f}",
                        f"{r.late_residual_mean:+.2f}",
                        f"{r.fast_late_share * 100:.1f}%",
                        f"{r.late_conditional_residual_mean:+.2f}",
                        f"{r.fast_conditional_late_share * 100:.1f}%",
                    ]
                    for r in sub.itertuples()
                ],
            ),
            "",
        ]
    lines += [
        "중간이 보통인 집단끼리 비교하면 초반느림은 빠른막판이 많고 초반빠름은 적었다. 날짜 단위 재표집2000회의 기본 막판잔차 평균 차이는 아래와 같다. 이 구간은 고정된 학습 기준의 추정오차를 포함하지 않으며 반복 말 효과를 별도로 군집화하지 않았다.",
        "",
    ]
    lines += [
        table(
            ["모집단", "지역", "출발 비교(중반보통)", "막판차이", "날짜군집95%구간"],
            [
                [
                    r.population,
                    r.meet,
                    f"{r.early_a}−{r.early_b}",
                    f"{r.difference_seconds:+.3f}",
                    f"{r.ci_low:+.3f}–{r.ci_high:+.3f}",
                ]
                for r in contrasts[contrasts.scope.eq("전체")].itertuples()
            ],
        ),
        "",
        "중간이 느린 집단은 느린막판도 많았다. 이런 기록에는 체력 보존뿐 아니라 능력 부족·상태·전개 차질이 섞일 수 있다. 초반·중간·막판의 통계 관계를 의도적 속도 조절의 인과효과로 읽지 않는다. 초반빠름/중반느림 주행심사는 서울·부산 각각12일뿐이라 수치를 일반화하지 않는다.",
        "",
        "## 전개조건을 추가할 필요가 있는가",
        "",
        "막판200의 연도 분리 평균절대오차(MAE). 이미 달린 초중반을 사용하는 사후 해석이며 출전 전 예측이 아니다.",
        "",
    ]
    val = pd.read_csv(OUT / "annual_validation.csv")
    val = val[val.part.eq("late")]
    rows = []
    for (pop, meet), g in val.groupby(["population", "meet"]):
        pivot = g.pivot(index="year", columns="model", values="mae")
        weights = g[g.model.eq("기본 조건")].set_index("year").n
        base, conditional = [
            np.average(pivot[c], weights=weights.reindex(pivot.index))
            for c in ("기본 조건", "초중반 추가")
        ]
        rows.append(
            [
                pop,
                meet,
                f"{base:.3f}초",
                f"{conditional:.3f}초",
                f"{(1 - conditional / base) * 100:.1f}%",
            ]
        )
    lines += [
        table(["모집단", "지역", "기본조건MAE", "초중반추가MAE", "오차감소"], rows),
        "",
        "네 집단 모두2024·2025·2026 각각에서 MAE가 줄었다. 다만 최근 기준 이동이 있어 예측 평균편향도 존재한다. 예를 들어2025서울1200 막판 기본편향+0.195초, 전개조건 추가+0.267초다. 전개를 설명하는 정보는 유용하지만 이 모델의 절대초를 확정 기준으로 배포하기는 이르다. 이미 관찰한 과거자료의 시간순 검증이며 신규 미래 테스트가 아니다.",
        "",
        "## 등급과 민감도",
        "",
        "등급별 최근 원시평균. 양 지역 국6/국5/국4/국3/2/1만 본문에 표시하고 혼합·OPEN은CSV에 유지했다.",
        "",
    ]
    grade = pd.read_csv(OUT / "grade_sections.csv")
    rows = []
    for meet in ["서울", "부산"]:
        for label in ["국6", "국5", "국4", "국3", "2", "1"]:
            sub = grade[(grade.meet == meet) & (grade.grade == label)].set_index("part")
            rows.append(
                [meet, label, f"{int(sub.loc['finish', 'n']):,}"]
                + [
                    f"{sub.loc[p, 'mean']:.2f}"
                    for p in ["early", "middle1", "middle2", "late", "finish"]
                ]
            )
    lines += [
        table(["지역", "등급", "행", "출발200", "중간①400", "중간②400", "막판200", "전체"], rows),
        "",
        "국6만 보아도 중반보통에서 초반느림/보통/빠름의 빠른막판 비율은 서울29.4/19.0/9.4%, 부산49.4/26.4/9.0%였다. 각 평가연도에도 같은 비율의 순서가 유지됐다. 신마합격만으로 좁히면 서울66.9/33.9/19.5%, 부산66.2/40.0/20.7%로 더 강해지며 통과시간에 따른 선택을 주의해야 한다. 이것이 합격·불합격을 함께 본 이유다.",
        "",
        "함수율별·연도별9칸, 국6·합격마 민감도를 별도 저장했다. 함수율 소표본 집단에서는 모든 순서가 같다고 단정하지 않는다. ‘함수율이 높으면 특정전개가 언제나 유리하다’는 새로운 보정 결정은 내리지 않았다.",
        "",
        "## 함수율 통제 모델의 참고 대비",
        "",
        "아래는2026평가를 위해2025까지 학습한 모델의 건조대비 적합 차이다. +는더 느림, −는더 빠름이며, 건조 환산 시 부호가 반대가 된다. 공식 보정표와 모집단·추정법이 다르다. 월은 반영했지만 개별 심사일·연도효과·주행심사 잠재능력을 모두 통제하지 못했다. 인과계수·최적 보정·새 채택값으로 사용하지 않는다.",
        "",
    ]
    env = pd.read_csv(OUT / "moisture_model_contrasts.csv")
    env = env[env.year.eq(2026)]
    rows = []
    for (pop, meet, band), g in env.groupby(["population", "meet", "band"]):
        if band == "건조":
            continue
        sub = g.set_index("part")
        rows.append(
            [pop, meet, band]
            + [
                f"{sub.loc[p, 'seconds_vs_dry']:+.3f}"
                for p in ["early", "middle1", "middle2", "late", "finish"]
            ]
        )
    lines += [
        table(["모집단", "지역", "함수율", "출발200", "중간①", "중간②", "막판200", "전체"], rows),
        "",
        "## 향후 기록 판정에 남길 항목",
        "",
        "1. 원시 전체·독립 구간시간, 함수율·지역·거리·등급을 보존한다.",
        "2. 구간별 같은 조건의 경험적 기준과 잔차를 따로 표시한다. 초반/중반/막판 빠름·보통·느림을 함께 기록한다.",
        "3. 막판은 기본조건 대비 빠름과 실제 초중반 전개 대비 빠름을 함께 본다. 초반여유+막판빠름을 보통전개+막판빠름과 동일 가산하지 않는다.",
        "4. 전체시간 성능과 막판 지표를 같이 본다. 중간까지 느린 기록을 단순히 체력 보존으로 해석하지 않는다.",
        "5. 보정계수의 채택은 별도 후속 검증으로 남긴다. 기존 전체시간 서울80%·부산90% 결정을1000m주행심사나 각 구간에 자동 전용하지 않는다.",
        "",
        "Timeform의FS%=100×구간거리×전체시간/(구간시간×전체거리)는 별도 계산했다. 최근 막판200 평균FS는 주행심사 서울96.89·부산96.41%, 실전1200 서울91.43·부산92.24%; 부산1200 막판400은96.04%다. 100%를 넘겨야 막판능력이 좋다는 기준으로 쓰지 않는다. 출발가속·자연스러운 감속·전개와 구간 길이를 반영한 효율적인 par가 별도로 필요하다.1200의 막판200은16.7%라 짧고 부산400은33.3%여서 후속 분석에 더 적합한 후보이나 이번 분석에서 최적 par를 확정하지 않았다.",
        "",
        "## 출처·검증·재현",
        "",
        "- [사전 계획](PLAN.md), [분석](analyze.py), [독립 검증](verify.py), [보고서/그림 생성](render_report.py)",
        "- [이전 주행심사 원천·공식 규정·Timeform 출처](../20261003_trial_time_baselines/SOURCES.md)",
        "- [실전 원천 일치 검증](../20261002_track_source_reconciliation/README.md), [정상완주·과거이력 집단](../20261002_gate_lateral_bias/README.md)",
        f"- 입력SHA-256·DB불변 확인. 원천{checks['source_rows_checked']:,}행 연결, 부산실전400m{checks['busan400_checked']:,}행, 독립SQL 집계{checks['independent_aggregate_metrics']:,}수치, 분류{checks['pace_classifications_checked']:,}건과36전개 집단 검증 통과.",
        "- 결과: [summary.json](outputs/summary.json), [verification.json](outputs/verification.json), [구간별함수율분포](outputs/moisture_sections.csv), [구간별등급분포](outputs/grade_sections.csv), [9칸전개](outputs/pace_profiles.csv), [함수율×전개](outputs/moisture_pace_profiles.csv), [연도×전개](outputs/year_pace_profiles.csv), [날짜군집차이](outputs/early_late_contrasts.csv), [연도별MAE](outputs/annual_validation.csv), [품질원장](outputs/quality_ledger.csv).",
        "",
        "```sh",
        ".venv/bin/python thoroughbred/research/20261003_sectional_pace_moisture/analyze.py",
        ".venv/bin/python thoroughbred/research/20261003_sectional_pace_moisture/verify.py",
        "MPLCONFIGDIR=/tmp/horse_sectional_plot .venv/bin/python thoroughbred/research/20261003_sectional_pace_moisture/render_report.py",
        "```",
        "",
        "완료된outputs가 있으면 분석은 덮어쓰기를 거부한다. 중간실행 outputs_initial/outputs_before_missing_moisture는 추적 제외로 보존했으며 최종 연구값은outputs만 사용한다.",
        "",
    ]
    (HERE / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("Report and plot saved.")


if __name__ == "__main__":
    main()

"""Build grade tables, conclusions, and a standalone figure from verified outputs."""

# ruff: noqa: E501 -- Korean report paragraphs remain single strings.
import json

import matplotlib
import numpy as np
import pandas as pd
from analyze import GRADES, HERE, OUT

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})


def table(headers, rows):
    return "\n".join(
        ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        + ["| " + " | ".join(map(str, row)) + " |" for row in rows]
    )


def main():
    stats = pd.read_csv(OUT / "grade_sections.csv")
    dry = pd.read_csv(OUT / "dry_grade_sections.csv")
    winners = pd.read_csv(OUT / "winner_grade_sections.csv")
    profiles = pd.read_csv(OUT / "grade_pace_profiles.csv")
    summary = json.loads((OUT / "summary.json").read_text())
    verification = json.loads((OUT / "verification.json").read_text())
    order = GRADES[:8]
    fig, axes = plt.subplots(3, 2, figsize=(12, 11), constrained_layout=True)
    for i, meet in enumerate(["서울", "부산", "영천"]):
        for j, part in enumerate(["finish", "late"]):
            g = stats[(stats.meet == meet) & (stats.part == part)].set_index("grade").reindex(order)
            ax = axes[i, j]
            ax.plot(range(len(order)), g["mean"], "o-", color=["#305b91", "#3c806b", "#ba6639"][i])
            if meet != "영천":
                ax.fill_between(
                    range(len(order)), g.mean_ci_low, g.mean_ci_high, color="#305b91", alpha=0.13
                )
            for k, row in enumerate(g.itertuples()):
                if np.isfinite(row.mean):
                    ax.annotate(
                        f"{row.mean:.2f}\nn={int(row.n):,}" + (" *" if row.small_support else ""),
                        (k, row.mean),
                        xytext=(0, 9),
                        textcoords="offset points",
                        ha="center",
                        fontsize=9,
                    )
            ax.set(
                xticks=range(len(order)),
                xticklabels=order,
                xlabel="원천 등급 (국산·혼합 분리)",
                ylabel="평균 초",
                title=f"{meet}1200m {'전체시간' if part == 'finish' else '마지막200m'}",
            )
            ax.grid(axis="y", alpha=0.2)
            values = g["mean"].dropna()
            ax.set_ylim(values.min() - 0.4, values.max() + (0.8 if part == "finish" else 0.45))
            if meet == "영천":
                ax.text(
                    0.03,
                    0.06,
                    "5경주·2일·50행 / 보정·등급 우열 확정 불가",
                    transform=ax.transAxes,
                    fontsize=10,
                )
    fig.suptitle("1200m 등급별 전체·막판 평균\n2024–2026 저장본 · 원시기록 · *소표본", fontsize=17)
    fig.savefig(OUT / "grade1200_sections.png", dpi=160)
    plt.close(fig)

    text = [
        "# 서울 부산 영천1200m 등급별 구간 분석",
        "",
        "2026-10-04. **등급별 시간 차이는 출발200m보다 중간과 후반에서 크게 나타났다. 국6·국5·국4에서는 초반이 느려도 중반을 유지한 경우 빠른 막판이 더 자주 나왔지만 상위·OPEN 등급의 소표본에는 순서 예외가 있었다. 영천은 원시50행을 확인했으나 자체 기준이나 주로 보정치를 정할 표본은 부족하다.**",
        "",
        "## 범위와 모집단",
        "",
        "서울·부산은 이전 구간 연구의 검증된1200m 집단41,623행을 승계했다. 최근2024년 이후 서울7,897행·부산5,416행, 영천9월13일·20일의50행을 분석했다. 저장본 종료일은 서울·영천2026-09-20, 부산2026-09-18이다. 현재 웹에 게시된10월 출전예정이나 이후 경주를 새로 수집한 결과가 아니다.",
        "",
        "정상 완주·완전착순·6두 이상 경주를 원천 집단으로 삼고 기존 품질 제외를 유지했다. 그 집단에서 이전 연구가 물리적 구간값 이상15행(최근3행)을 제외했기 때문에 최종 구간집단에는 해당 경주의 일부 출전행이 빠질 수 있다. 상하위 기록의 분위수 꼬리는 임의 절단하지 않았다. 평균은 우승마뿐 아니라 유효 기록을 가진 모든 완주마의 평균이다.",
        "",
        table(
            ["지역", "최근 행", "경주", "날짜", "종료일"],
            [
                [r["meet"], f"{r['n']:,}", r["races"], r["days"], r["end"]]
                for r in summary["recent_coverage"]
            ],
        ),
        "",
        "국6·국5·국4·혼4·국3·혼3·2·1·국OPEN·혼OPEN을 원천대로 분리했다. 혼합과 국산의 같은 숫자 등급을 합치지 않았다. OPEN은 능력이 일정한 숫자 등급으로 바꾸지 않았다. 모든 시간은 초이며 원시 평균은 최적 par나 승급 보정값이 아니다.",
        "",
        "독립 구간은 출발200(0–200), 중간①400(200–600), 중간②400(600–1000), 막판200(1000–1200). `중간①=전체−막판600−출발200`, `중간②=막판600−막판200`이며 합계는 전체와 같다. 막판600·400은 겹치는 보조 구간이다. 부산·영천은 직접400m 값을 사용했고 서울은 코너 기록에서400m를 임의 생성하지 않았다.",
        "",
        "## 등급별 원시 구간 평균",
        "",
        "20일·20경주·200행 중 하나라도 미달하면별표 표시. 영천은 모든 관측 등급이 소표본이다.",
        "",
    ]
    for meet in ["서울", "부산", "영천"]:
        rows = []
        for grade in GRADES:
            g = stats[(stats.meet == meet) & (stats.grade == grade)].set_index("part")
            if g.empty:
                rows.append([grade, "0/0/0"] + ["—"] * 7)
                continue
            f = g.loc["finish"]
            rows.append(
                [
                    grade + (" *" if f.small_support else ""),
                    f"{int(f.n):,}/{int(f.races)}/{int(f.days)}",
                ]
                + [
                    f"{g.loc[p, 'mean']:.2f}" if p in g.index else "—"
                    for p in ["early", "middle1", "middle2", "late", "finish", "last600", "last400"]
                ]
            )
        text += [
            f"### {meet}",
            "",
            table(
                [
                    "등급",
                    "행/경주/일",
                    "출발200",
                    "중간①400",
                    "중간②400",
                    "막판200",
                    "전체",
                    "막판600",
                    "막판400",
                ],
                rows,
            ),
            "",
        ]
    text += [
        "![등급별 전체와 막판 평균](outputs/grade1200_sections.png)",
        "",
        "## 등급 차이가 나타나는 구간",
        "",
    ]
    gaprows = []
    for meet in ["서울", "부산"]:
        g = stats[(stats.meet == meet) & stats.grade.isin(["국6", "1"])].pivot(
            index="part", columns="grade", values="mean"
        )
        gap = g["국6"] - g["1"]
        gaprows.append(
            [meet] + [f"{gap[p]:.3f}" for p in ["early", "middle1", "middle2", "late", "finish"]]
        )
    text += [
        table(["지역", "출발200 차이", "중간① 차이", "중간② 차이", "막판200 차이", "전체 차이"], gaprows),
        "",
        "국6−1등급의 평균 차이. 두 지역 모두600–1000m의400m 구간 차이가 가장 크고 출발200 차이는 상대적으로 작았다. 상위등급을 ‘초반만 빠른 말’로 설명하기 어렵다. 부산1등급은10일·98행이라 정밀한 경계값으로 쓰지 않는다. 등급별 말·나이·중량·함수율·개최시기 구성이 다르므로 한 말이 승급하면 이만큼 빨라진다는 뜻이 아니다.",
        "",
        "## 기록 분포와 비교 범위",
        "",
        "P10–P90는 가운데80%의 실제 기록 범위이며 합격선이나 능력의 확정 경계가 아니다. 인접 등급은 범위가 크게 겹친다.",
        "",
    ]
    rows = []
    for meet in ["서울", "부산", "영천"]:
        for grade in GRADES:
            g = stats[(stats.meet == meet) & (stats.grade == grade)].set_index("part")
            if g.empty:
                continue
            f, late_stat = g.loc["finish"], g.loc["late"]
            rows.append(
                [
                    meet,
                    grade,
                    f"{f['median']:.2f}",
                    f"{f.p10:.2f}–{f.p90:.2f}",
                    f"{late_stat['median']:.2f}",
                    f"{late_stat.p10:.2f}–{late_stat.p90:.2f}",
                ]
            )
    text += [
        table(["지역", "등급", "전체중앙값", "전체P10–P90", "막판중앙값", "막판P10–P90"], rows),
        "",
        "날짜 단위 재표집2000회 평균95%구간도CSV에 보존했다. 고정된 과거 표본의 조건부 구간이며 향후 개별 말 기록 범위나 미관측 말 능력·개최기간 변화까지 포함한 불확실성은 아니다. 영천1일 표본은 날짜 재표집 구간을 제시하지 않았고 혼4의2일 구간도 안정적인 추정으로 읽지 않는다.",
        "",
        "## 함수율과 우승마 선택의 영향",
        "",
        "건조만과 모든 함수율의 평균, 우승마만의 평균을 비교한다. 함수율별 전체 독립 구간과 연도별 결과는 별도CSV에 보존했다.",
        "",
    ]
    rows = []
    for meet in ["서울", "부산", "영천"]:
        for grade in GRADES:
            a = stats[(stats.meet == meet) & (stats.grade == grade) & stats.part.eq("finish")]
            b = dry[(dry.meet == meet) & (dry.grade == grade) & dry.part.eq("finish")]
            w = winners[
                (winners.meet == meet) & (winners.grade == grade) & winners.part.eq("finish")
            ]
            if a.empty:
                continue
            rows.append(
                [
                    meet,
                    grade,
                    f"{a.iloc[0]['mean']:.2f}",
                    f"{b.iloc[0]['mean']:.2f}" if len(b) else "—",
                    f"{int(b.iloc[0].n)}/{int(b.iloc[0].days)}" if len(b) else "0/0",
                    f"{w.iloc[0]['mean']:.2f}",
                    f"{int(w.iloc[0].n)}",
                ]
            )
    text += [
        table(
            ["지역", "등급", "전체집단평균", "건조평균", "건조행/일", "우승마평균", "우승행"], rows
        ),
        "",
        "건조만으로 제한해도 저등급과 상위등급의 전체시간 차이는 남지만 등급별 평균 차이는 달라진다. 건조 자체도 같은 날짜·중량·능력 조건으로 맞춘 비교는 아니다. 우승마 평균을 전체 완주마의 기준으로 대신 쓰지 않는다. 원시차를 기존 함수율 보정이나 새로운 구간 보정으로 직접 적용하지 않았다.",
        "",
        "## 등급별 초중반 전개와 막판",
        "",
        "서울·부산 지역별 모델에 등급·함수율·월·성별·나이·중량·rating·이전 성적·이전 초반위치·출전수·휴식간격을 반영했다. 평가연도 이전 기록만 학습했다. 이번에는 과거 잔차P25/P75를 등급별로 따로 고정했다. 이전 보고서의 전등급 공통 잔차 경계와 다르므로 비율이 일부 달라질 수 있다. 과거100행·10일 미만인 등급은 분류하지 않는 규칙을 사용했다.",
        "",
        "아래는 중반이 보통인 집단에서 출발느림/보통/빠름별 빠른막판200 비율이다. 비율 뒤 괄호는해당 전개 집단의 출전행 수. 초반과 중반은 서로 겹치지 않는 구간이고 당일 전체시간·순위·배당은 모델 설명변수로 넣지 않았다.",
        "",
    ]
    rows = []
    for meet in ["서울", "부산"]:
        for grade in GRADES:
            g = profiles[
                (profiles.meet == meet)
                & (profiles.grade == grade)
                & profiles.pace_middle.eq("보통")
            ].set_index("pace_early")
            if g.empty:
                continue
            values = []
            for pace in ["느림", "보통", "빠름"]:
                r = g.loc[pace]
                values.append(
                    f"{r.fast_late_share * 100:.1f}% ({int(r.n)})"
                    + (" *" if r.small_support else "")
                )
            rows.append([meet, grade] + values)
    text += [
        table(["지역", "등급", "출발느림", "출발보통", "출발빠름"], rows),
        "",
        "국6·국5·국4에서는 두 지역 모두 초반느림→보통→빠름 순으로 빠른막판 비율이 낮아졌다. 그러나 서울1등급은 보통8.2%·빠름18.8%로 순서 예외가 있었고 각각49·16행이다. 혼OPEN 등급에도 일부 예외가 있다. 상위등급의9칸 전개 집단은 원래보다 더 작으므로 모든 등급에 동일 초 보정을 강제하지 않는다.",
        "",
        "전개9칸마다 실제 막판시간, 기본조건 대비 잔차, 실제 초중반을 추가한 기준 대비 잔차를 함께 보존했다. ‘출발여유 때문에 빠른 막판’과 ‘그 전개에서도 예상보다 빠른 막판’을 구분할 목적으로, 실제 초중반을 쓰는 사후 해석이다. 출전 전 예측 개선이나 의도적 체력 안배의 인과효과를 검증한 결과가 아니다.",
        "",
        "## 영천에서 말할 수 있는 범위",
        "",
        "영천1200m는 국4 한 경주9행, 혼4 두 경주19행, 혼3 한 경주11행,2등급 한 경주11행이며 모두건조3%다. 국6·국5·국3·1·OPEN 등급의 정식1200m는 이 저장본에 없다. 따라서 현재 평균이 등급 순서대로 나오지 않아도 등급 우열이나 주로 우열로 해석하지 않는다.",
        "",
        "국4 막판200 평균12.76초는 부산국4 13.66초보다 빠르지만 영천은 단1경주다. 반대로 혼3의 영천 막판은14.05초로 부산13.40초보다 느렸다. 영천 공통 보정초를 설정할 일관된 증거가 아니다. 부산 또는 서울의 모델·계수를 영천에 적용하지 않았고 자체 페이스 분류도 제공하지 않았다.",
        "",
        "영천 직접 막판600값이0인11행은 유효한 `전체−buG3fAccTime`를 사용했다. 직접값이 있는39행과 같은 누적 계산이 일치함을 확인했다.50행의 구간 합과 직접400m 순서도 통과했다. 전체 API응답291행 중 확정 정식119행만 원천 대조했으며 시험·미확정 항목을 이번50행에 섞지 않았다.",
        "",
        "## 기준과 후속 적용",
        "",
        "현재는 지역×거리×원천등급×함수율을 먼저 구분한 경험적 평균·중앙값·범위를 비교 기준으로 사용한다. 실제 기록 판정에는 초중반 전개와 조건부 막판 잔차를 함께 남긴다. P25/P75는 연구용 상대 분류 기준이며 등급 능력을 확정하는 절대초 기준은 아니다.",
        "",
        "국6에서국5로 평균이 얼마나 달라지는지는 확인했지만 자동 승급 보정표·최적 Timeform par·영천 주로 보정은 채택하지 않았다. 기존 전체시간 서울80%·부산90% 연구 기준과 구간 보정 채택 보류를 유지한다.",
        "",
        "## 원천 검증과 산출물",
        "",
        f"입력·DB SHA-256 불변. 서울·부산41,623행을 승계하고 영천 확정 원천{verification['yeongcheon_confirmed_raw_rows_checked']}행·1200m50행을 대조했다. 독립SQL{verification['independent_sql_metrics']:,}수치, 등급별 분류{verification['grade_classifications_checked']:,}건, 전개{verification['independent_pace_groups']}집단,30개 지역×등급 표본 셀과 구간합·과거 날짜 검증을 통과했다.",
        "",
        "- [사전 계획](PLAN.md), [출처](SOURCES.md), [분석](analyze.py), [독립 검증](verify.py), [그림·보고서 생성](render_report.py)",
        "- [평균·분포·표본](outputs/grade_sections.csv), [건조만](outputs/dry_grade_sections.csv), [등급×함수율](outputs/moisture_grade_sections.csv), [등급×연도](outputs/year_grade_sections.csv)",
        "- [우승마만](outputs/winner_grade_sections.csv), [3위이내](outputs/top3_grade_sections.csv), [등급별9칸전개](outputs/grade_pace_profiles.csv), [과거 등급별 경계](outputs/grade_reference_thresholds.csv), [연도별 조건부 오차](outputs/grade_reference_validation.csv)",
        "- [영천5경주 구간](outputs/yeongcheon_race_sections.csv), [영천50행](outputs/yeongcheon_1200.parquet), [영천12개 정식경주 원장](outputs/yeongcheon_race_inventory.csv), [분석 명세](outputs/summary.json), [검증 명세](outputs/verification.json)",
        "- [새 산출물 용량 명세](outputs/artifact_inventory.json), [이 세션의 용량 기록 규정](../SESSION_ARTIFACT_POLICY.md), [작업별 용량 기록](../ARTIFACT_SIZE_LOG.md)",
        "",
        "```sh",
        "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261004_grade1200_sectional/analyze.py",
        "PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261004_grade1200_sectional/verify.py",
        "MPLCONFIGDIR=/tmp/horse_grade_plot PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261004_grade1200_sectional/render_report.py",
        "```",
        "",
        "완료된outputs가 있으면 분석은 덮어쓰기를 거부한다. 참고용 과거 원장·DB를 새 연구폴더에 전체 복제하지 않았다.",
        "",
    ]
    (HERE / "README.md").write_text("\n".join(text), encoding="utf-8")
    conclusion = [
        "# 서울 부산 영천1200m 등급별 구간 결론",
        "",
        "2026-10-04. [상세 보고서](../20261004_grade1200_sectional/README.md)의 결론. 주로빠르기는 제외했다. 기존 보정 결정과 운영모형은 유지한다.",
        "",
        "**등급이 높아질수록 대체로 전체·중간·막판 기록이 빠르며, 국6과1등급의 차이는 출발200보다600–1000m에서 컸다. 같은 막판초를 모든 등급에 적용하지 않는다. 영천은5경주·50행·2일로 별도 기준을 채택하지 않는다.**",
        "",
        "최근 저장본의 완주행 평균.1·2는 원천의1·2등급이며 국산·혼합OPEN은 별도로 보존했다.",
        "",
    ]
    rows = []
    for meet in ["서울", "부산", "영천"]:
        for grade in GRADES[:8]:
            g = stats[(stats.meet == meet) & (stats.grade == grade)].set_index("part")
            if g.empty:
                continue
            f = g.loc["finish"]
            rows.append(
                [
                    meet,
                    grade + (" *" if f.small_support else ""),
                    f"{int(f.n)}/{int(f.races)}/{int(f.days)}",
                ]
                + [
                    f"{g.loc[p, 'mean']:.2f}"
                    for p in ["early", "middle1", "middle2", "late", "finish"]
                ]
            )
    conclusion += [
        table(
            ["지역", "등급", "행/경주/일", "출발200", "200–600", "600–1000", "막판200", "전체"],
            rows,
        ),
        "",
        "단위 초。별표는200행·20경주·20일 중 하나라도 미달. 서울·부산은2024년 이후이며 영천은2026-09-13·20 확정 정식기록이다. 이후 기록을 새로 수집하지 않았다. 영천 미관측 등급은 추정하지 않았다.",
        "",
        "국6−1등급 전체시간 차이는 서울3.79초·부산3.63초, 출발200은0.30·0.39초,600–1000m는1.69·1.40초다. 승급 때 자동으로 빼는 보정값이 아니며 등급별 말·중량·날짜·함수율의 구성 차이가 포함된다.",
        "",
        "국6·국5·국4에서는 두 지역 모두 중반보통 집단의 초반느림→보통→빠름에 따라 빠른막판 비율이 낮아졌다. 국6의 비율은 서울28.2/18.3/8.8%, 부산48.6/24.0/7.0%다. 이번 경계는 과거 등급별 잔차P25/P75이므로 이전 전등급 공통 경계와 다르다. 서울1·OPEN 일부 전개에는 순서 예외가 있고 표본도 적어 모든 등급에 공통 보정초를 강제하지 않는다.",
        "",
        "영천은 모두건조3%로 함수율 대비를 할 수 없다. 국4 막판12.76초는1경주뿐이며 혼3 막판은14.05초로 부산보다 느렸다. 영천 고유의 빠른 주로 또는 등급 우열을 확정하지 않는다.50행 중11행의 막판600은 유효한 누적 지점에서 계산했고 직접값39행과 같은 계산을 대조했다.",
        "",
        "과거 연도만 학습한 서울·부산 등급별 상대 전개 분류를 보존했다. 실제 초중반을 사용한 조건부 막판은 사후 기록 해석이며 출전 전 예측 검증이 아니다. 영천은 자체 학습·페이스 분류를 제공하지 않았다. 평균·중앙값·P10–P90는 경험적 기준이며 최적 Timeform par나 새 보정표가 아니다.",
        "",
        "검증: 서울·부산41,623행의 기존 품질 기준 유지, 영천 정식119행·1200m50행 원천 대조, 구간합·연도 및 과거이력·등급 분류·독립SQL 집계 통과. 상세 수량은 [검증 명세](../20261004_grade1200_sectional/outputs/verification.json)에 보존했다.",
        "",
        "앞으로 이 세션의 모든 완료 작업은 새 산출물의 파일별 크기와 총용량을 [용량 기록](../ARTIFACT_SIZE_LOG.md)에 남기고 최종 답변에 보고한다. 이번 명세는 [artifact_inventory.json](../20261004_grade1200_sectional/outputs/artifact_inventory.json)에 있다.",
        "",
    ]
    (HERE.parent / "conclusions/07_GRADE1200_SECTIONS.md").write_text(
        "\n".join(conclusion).replace("초。", "초. "), encoding="utf-8"
    )
    print("Report, conclusions, and figure saved.")


if __name__ == "__main__":
    main()

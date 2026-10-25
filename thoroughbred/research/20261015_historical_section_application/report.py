"""Publish historical before/after application results and named horse examples."""

# ruff: noqa: E501 -- Generated Korean report paragraphs use semantic lines.

import importlib.util
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("history_report_source", HERE / "analyze.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)
LABELS = dict(
    early="초반200m",
    middle1="중반D−800m",
    middle2="결승 전600→200m400m",
    late="마지막200m",
    finish="전체",
    last600="마지막600m",
)


def table(df, headers):
    return "\n".join(
        ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        + [
            "| " + " | ".join(str(v) for v in row) + " |"
            for row in df.itertuples(index=False, name=None)
        ]
    )


def records(df):
    return json.loads(df.to_json(orient="records", force_ascii=False))


def main():
    application = json.loads((OUT / "application_summary.json").read_text())
    verified = json.loads((OUT / "verification.json").read_text())
    s = pd.read_csv(OUT / "before_after_summary.csv")
    overview = s[s.grain.eq("meet") & s.cohort.eq("all_applied") & s.section.eq("finish")].copy()
    shown = overview[
        [
            "meet",
            "rows",
            "delta_mean",
            "mean_absolute_delta",
            "delta_min",
            "delta_max",
            "abs_ge_01_rate",
        ]
    ].copy()
    for col in ["delta_mean", "mean_absolute_delta", "delta_min", "delta_max"]:
        shown[col] = shown[col].map(lambda v: f"{v:+.3f}")
    shown.abs_ge_01_rate = shown.abs_ge_01_rate.map(lambda v: f"{v * 100:.2f}%")
    overview_table = table(
        shown,
        [
            "지역",
            "완전 보정 출전",
            "평균 증감초",
            "평균 절대변화초",
            "최소초",
            "최대초",
            "0.1초 이상 변화",
        ],
    )
    sections = (
        s[s.grain.eq("meet") & s.cohort.eq("all_applied")]
        .pivot(index="section", columns="meet", values="mean_absolute_delta")
        .loc[A.TARGETS]
    )
    section_shown = sections.map(lambda v: f"{v:.3f}").reset_index()
    section_shown.section = section_shown.section.map(LABELS)
    section_table = table(section_shown, ["구간", "부산 평균 절대변화초", "서울 평균 절대변화초"])
    examples = pd.read_csv(OUT / "record_examples.csv")
    typical = examples[examples.distance_m.eq(1200) & examples.band.eq("포화")].copy()
    display = pd.DataFrame(
        [
            dict(
                meet=r.meet,
                horse_name=r.horse_name,
                date=r.date,
                section=LABELS[part],
                before=f"{getattr(r, 'raw_' + part):.3f}",
                after=f"{getattr(r, 'adjusted_' + part):.3f}",
                change=f"{getattr(r, 'add_' + part):+.3f}",
            )
            for r in typical.itertuples()
            for part in A.TARGETS
        ]
    )
    typical_table = table(
        display,
        ["지역", "마명", "날짜", "구간", "원기록초", "환산초", "보정초"],
    )
    changed = pd.read_csv(OUT / "changed_horse_examples.csv")
    flip = changed[changed.distance_m.eq(1200)].copy()
    flip_shown = flip[
        ["meet", "horse_name", "date", "band", "raw_finish", "add_finish", "adjusted_finish"]
    ].copy()
    for col in ["raw_finish", "add_finish", "adjusted_finish"]:
        flip_shown[col] = flip_shown[col].map(lambda v: f"{v:.3f}")
    flip_table = table(
        flip_shown, ["지역", "마명", "날짜", "상태", "원기록초", "보정초", "환산기록초"]
    )
    best = pd.read_csv(OUT / "horse_best_summary.csv")
    b = best[best.section.eq("finish")].copy()
    b.changed_rate = b.changed_rate.map(lambda v: f"{v * 100:.2f}%")
    best_table = table(
        b[["meet", "groups", "changed_best", "changed_rate"]],
        ["지역", "말×거리 비교집단", "최고기록 출전 변경", "변경률"],
    )
    race = pd.read_csv(OUT / "within_race_time_order_summary.csv")
    coverage = pd.read_csv(OUT / "coverage.csv")
    alternate = pd.read_csv(OUT / "alternate_before_after_summary.csv")
    publication = f"""# 서울 부산 과거 출전기록 보정 전후

2026-10-15 기준으로 기존 구간 보정 후보를 과거 출전기록에 적용했다. 151,074출전 중 {application["core_complete"]:,}출전에 함수율·월·게이트를 모두 적용할 수 있었다. 서울은 81,712출전, 부산은 57,222출전이다. 기존 추정 표본에서 제외했던 후미·이상치도 이번 적용 원장에는 남겨 두었다.

원기록과 환산기록을 나란히 보존했다. 공식 기록이나 운영 DB를 변경한 것은 아니다. 계수를 다시 추정하지 않았고, 기존 전체시간 서울80%·부산90%를 이번 직접 구간 후보에 추가하지 않았다.

## 전체기록은 얼마나 달라졌나

{overview_table}

평균 증감은 양의 보정과 음의 보정이 상쇄된 값이다. 실제 변화 크기는 평균 절대변화를 함께 봐야 한다. 이 표는 같은 지역에서 보정 전후 같은 출전들을 비교한 것이며, 서로 다른 거리 구성의 서울·부산 원기록 평균을 능력 차이로 비교하지 않는다.

## 구간별 평균 절대변화

{section_table}

중반 길이는 경주거리마다 다르므로 같은 길이의 구간끼리 비교하려면 상세 거리별 표를 사용한다. 초반과 마지막200m의 변화는 대부분 수백분의 몇 초였고, 중반 및 마지막600m의 누적 변화가 상대적으로 컸다. 마지막600m와 후반400m·마지막200m는 겹치므로 별도 능력처럼 합산하지 않는다.

## 실제1200m 출전의 보정 전후

각 지역 포화1200m에서 전체 보정의 중앙값에 가까운 출전을 골랐다. 단위 초다.

{typical_table}

구간별 보정치를 더한 합은 전체 보정치와 일치한다. 표시한 소수 셋째 자리는 계산 결과이며 원 계측이0.001초 정밀도였다는 뜻은 아니다.

## 같은 말의 과거 최고기록이 바뀌는가

같은 말·경기장·거리에서 완전 보정 가능한 기록이2개 이상인 집단을 비교했다. 동률은 집합으로 처리했다.

{best_table}

대부분의 최고기록은 유지됐지만, 주로·월·게이트가 달랐던 근소한 기록은 선택이 바뀌었다. 아래는 지역·거리별 변경 사례의 보정 후 선호 격차가 중앙값에 가까운 사례다.

{flip_table}

이 변화는 기록의 환산 순서가 바뀌었다는 뜻이다. 말의 실제 능력 순위나 다음 경주 성적이 더 정확해졌다는 검증은 아니다. 성장·부담중량 등 말별 보정을 새로 넣지 않았다.

## 같은 경주 안에서는

함수율과 월은 같은 경주의 모든 말에 같은 값이므로 말 사이 기록 차이를 바꾸지 않는다. 이번 같은 경주 내 변화는 게이트 보정에서만 발생했다. 원 출전명단 전체가 완전 보정되는 경주에서 엄격한 기록 순서 뒤집힘은 서울0쌍, 부산34쌍이었다. 부산은5,217경주 중31경주에서 발생했다. 원기록 동률을 작은 보정값으로 나눈 경우는 별도로 집계했고, 공식 착순은 변경하지 않았다.

## 적용이 부족한 기록

{application["records"] - application["core_complete"]:,}출전은 완전 보정을 제공하지 않았다. 서울1600m는 월별 전체 주기 지원이 부족해 이번 정책으로는 세 항목 완전 합산이 없다. 일부 상태·게이트 블록, 서울2000m와희소 장거리도 미지원이 남는다. 원장의missing_reason과 각 성분을 통해 확인할 수 있다. 부분 합산을 완전 보정처럼 표시하지 않았다.

자료는2018년 이후 고정 모집단이며 서울2026-09-20·부산2026-09-18까지다. 2026-10-15에 과거를 다시 환산한 결과로, 당시 알 수 있었던 계수로 수행한 예측 검증은 아니다.
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    (HERE / "README.md").write_text(
        publication
        + f"""
## 적용 방법과 검증

서울20261011·부산20261013의all_mad4/tail25 직접 구간 후보를 사용했다. 함수율40%·월30%·게이트30%와n/(n+100),한도,중심화가 이미 들어간 값이다.원 출전두수와게이트 순번을 유지해 날짜·함수율 상태·월·편성 블록·번호/상대그룹으로 배치 연결했다.함수율 숫자의 상태 경계는 기존 정의를 유지했다.운영용 계수 승격이나 재학습은 없다.

기본 원장에는전체151,074출전의 원기록,각 성분,완전/부분 가산,완전 환산 기록,추정 표본 포함 여부,후미 표식,미지원 사유가 있다.세부 대안 원장도 같은 행을 보존하며 서울코너/부산세부 유효성 표식을 적용했다.대안 완전 보정은{application["alternate_complete"]:,}행이다.기본/대안 원장을 한 기록에 합산하지 않는다.

독립 단건 조회{verified["independent_single_lookup_targets"]:,}개 구간을 배치와 대조한 최대 차이는{verified["max_single_lookup_error"]:.3g}초다.원기록 전수 일치,전체/600m/세부 분할합,양수 기록,부분/완전 구분,말별 최고기록 동률120집단을 확인했다.원 보정표·원천API·참조자료 해시도 유지됐다.

원장은core_historical_records.parquet와alternate_historical_records.parquet다.개별 열의raw_는원기록,moisture_add_/month_add_/gate_add_는성분,add_는완전가산,adjusted_는완전환산,partial_add_는알려진성분만의합이다.미지원 성분을0으로 대체한 완전 기록은 만들지 않았다.

before_after_summary.csv는완전 적용 전체와추정 표본만의 거리/함수율/월/게이트 요약이다.마명·날짜별사례는record_examples.csv,최고기록 변경은changed_horse_examples.csv,전체말별 비교는horse_best_record_comparisons.parquet다.연속출전 비교와경주내 기록순 비교도별도CSV로 보존했다.같은경주 순서는원 명단 전체가 적용되는경주에서만 비교했고,계측 동률/엄격한 역전도구분했다.

마필 생애 전체에서후향 최고기록을 비교한 것으로,새 예측용 변수나시간순 성능평가가 아니다.희소/미지원행을 제외한 적용 가능 집단에 조건부인 요약이므로전체출전자 능력 분포로 일반화하지 않는다.부담중량·성장·전개·실제내외측 보정을 새로합산하지 않았다.

재현:analyze.py→summarize.py→verify.py→report.py.프로젝트.venv/bin/python과PYTHONDONTWRITEBYTECODE=1,OPENBLAS_NUM_THREADS=1을 사용한다.웹게시 준비JSON만 만들고 배포하지 않았다.
"""
    )
    (HERE / "SOURCES.md").write_text("""# 과거 출전기록 보정 적용 출처

2026-10-15.기존 고정 자료를 읽기 전용으로 연결했다.

- 20261011_seoul_section_corrections:서울계측원장·보정표·단건조회·구간 정의.
- 20261013_busan_section_corrections:부산계측원장·보정표·단건조회·구간 정의.
- 20261007_sex_ability_gap/outputs/population.parquet:151,074출전의원기록과조건.
- 20261002_gate_lateral_bias/outputs/runners.parquet:151,115행의원게이트 명단과분모.
- 20261008_record_normalization_seconds와20261008_detached_tail_sensitivity:추정 표본/이탈후미 표식.
- 20260929_calendar_api_v1/raw/race_execution_probe:마명·날짜·경주·마필·완주기록 전수 연결.

모든 입력 및원천API 파일SHA-256은outputs/application_summary.json에 기록했다.운영DB·원기록·기존 계수 파일을수정하지 않았다.
""")
    chart(pd.read_parquet(OUT / "core_historical_records.parquet"), sections)
    A.dump(
        OUT / "web_research.json",
        dict(
            title="서울 부산 과거 출전기록 보정 전후",
            as_of="2026-10-15",
            status="retrospective_trial_application",
            publication=publication,
            overview=records(overview),
            section_summary=records(sections.reset_index()),
            coverage=records(coverage),
            examples=records(typical),
            changed_horse_examples=records(flip),
            horse_best_summary=records(best),
            within_race_summary=records(race),
            alternate_summary=records(alternate),
            coefficient_refit=False,
            production_changed=False,
            prediction_validation=False,
        ),
    )
    print("Historical application reports saved")


def chart(d, sections):
    plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), constrained_layout=True)
    for venue, g in d[d.complete].groupby("meet"):
        axes[0].hist(
            g.add_finish, bins=np.arange(-0.25, 0.401, 0.02), density=True, alpha=0.45, label=venue
        )
    axes[0].set_xlabel("전체기록 가산초")
    axes[0].set_ylabel("밀도")
    axes[0].set_title("완전 보정 출전의 전체기록 변화")
    axes[0].legend()
    x = np.arange(4)
    for i, venue in enumerate(["서울", "부산"]):
        axes[1].bar(x + (i - 0.5) * 0.35, sections.loc[A.CORE, venue], 0.35, label=venue)
    axes[1].set_xticks(x, ["초반200", "중반 D-800", "후반400", "막판200"])
    axes[1].set_ylabel("평균 절대변화 초")
    axes[1].set_title("구간기록 변화 크기 · 거리 혼합 표본")
    axes[1].legend()
    fig.suptitle("2026-10-15 후향 환산 · 기존 직접 구간 후보 · 예측 검증과 구분")
    fig.savefig(OUT / "historical_record_changes.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()

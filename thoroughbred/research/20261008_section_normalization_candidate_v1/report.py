# ruff: noqa: E501 -- Saved Markdown paragraphs retain readable native line breaks.
"""Prepare sectional tables, application examples and a local publication summary."""

import importlib.util
import json
import os
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("section_analysis", HERE / "analyze.py")
N = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(N)
SPEC2 = importlib.util.spec_from_file_location("section_application", HERE / "apply.py")
H = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(H)
LABELS = {
    "early": "출발200m",
    "middle1": "출발200m 후~결승600m 전",
    "middle2": "결승600m 전~200m 전",
    "late": "마지막200m",
    "last600": "마지막600m(겹침)",
    "finish": "전체시간",
}


def markdown(df):
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        values = [
            "미지원"
            if pd.isna(row[c])
            else f"{row[c]:.3f}"
            if isinstance(row[c], float)
            else str(row[c])
            for c in cols
        ]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["passed"]
    norm = H.SectionNormalizer(OUT)
    focus = []
    examples = []
    for meet, n, number in [("서울", 10, 10), ("부산", 12, 1)]:
        result = norm.normalize_record(
            early=14.0,
            last600=40.0,
            late=13.0,
            meet=meet,
            distance=1600,
            finish=100.0,
            moisture=3.0,
            record_date="2026-09-18",
            horse_number=number,
            roster=list(range(1, n + 1)),
            as_of="2026-10-08",
        )
        for part in ["early", "middle1", "middle2", "late", "last600", "finish"]:
            r = result["parts"][part]
            focus.append(
                dict(
                    meet=meet,
                    distance_m=1600,
                    field_size=n,
                    gate=number,
                    band="건조",
                    section=part,
                    label=LABELS[part],
                    gate_add_seconds=r["gate"],
                    method=r["method"],
                )
            )
    focus = pd.DataFrame(focus)
    focus.to_csv(OUT / "1600_section_gate_focus.csv", index=False)
    for title, meet, dist, n, number, moisture, finish, enabled in [
        ("서울1600 건조", "서울", 1600, 10, 10, 3.0, 100.0, False),
        ("서울1200 포화·월끄기", "서울", 1200, 11, 11, 17.0, 73.0, False),
        ("서울1200 포화·9월후보", "서울", 1200, 11, 11, 17.0, 73.0, True),
        ("서울1600 불량·전체미지원", "서울", 1600, 10, 10, 21.0, 100.0, False),
    ]:
        result = norm.normalize_record(
            early=14.0,
            last600=39.0,
            late=13.0,
            meet=meet,
            distance=dist,
            finish=finish,
            moisture=moisture,
            record_date="2026-09-18",
            horse_number=number,
            roster=list(range(1, n + 1)),
            as_of="2026-10-08",
            include_month=enabled,
        )
        for part in ["early", "middle1", "middle2", "late", "last600", "finish"]:
            examples.append(
                dict(
                    example=title,
                    meet=meet,
                    distance_m=dist,
                    field_size=n,
                    horse_number=number,
                    band=H.W.band_for(moisture),
                    section=part,
                    label=LABELS[part],
                    month_enabled=enabled,
                    **result["parts"][part],
                )
            )
    example = pd.DataFrame(examples)
    example.to_csv(OUT / "section_application_examples.csv", index=False)
    core = focus[
        focus.meet.eq("서울")
        & focus.section.isin(["early", "middle1", "middle2", "late", "finish"])
    ][["label", "gate_add_seconds", "method"]].copy()
    core.columns = ["구간", "더할초", "방법"]
    core["방법"] = core["방법"].map(
        {
            "direct_target": "직접 목표 추정",
            "identity_residual": "합계 일치 잔여값",
            "whole_time_v1_preserved": "기존 전체시간 v1",
        }
    )
    moist = pd.read_csv(OUT / "section_moisture_reference.csv")
    m = moist[
        moist.distance_m.eq(1200) & moist.band.isin(["건조", "양호", "다습", "포화", "불량"])
    ][["meet", "section", "band", "moisture_add_seconds"]]
    m = (
        m.pivot(index=["meet", "section"], columns="band", values="moisture_add_seconds")
        .reindex(columns=N.A.BANDS)
        .reset_index()
    )
    m["section"] = m.section.map(LABELS)
    m = m.rename(columns={"meet": "지역", "section": "구간"})
    m.to_csv(OUT / "1200_section_moisture_focus.csv", index=False)
    ex = example[example.example.eq("서울1200 포화·9월후보")][
        ["label", "raw", "moisture", "month", "gate", "total_add", "candidate", "method"]
    ].copy()
    ex.columns = ["구간", "원기록", "함수율", "월", "게이트", "총보정", "보정기록", "방법"]
    ex["방법"] = ex["방법"].map(
        {
            "direct_target": "직접 목표",
            "identity_residual": "잔여값",
            "whole_time_v1_preserved": "전체 v1",
        }
    )
    direct = (
        focus[focus.section.isin(["early", "last600", "late"])]
        .pivot(
            index=["meet", "distance_m", "field_size", "gate"],
            columns="section",
            values="gate_add_seconds",
        )
        .reset_index()
    )
    direct.to_csv(OUT / "direct_section_gate_focus.csv", index=False)
    text = f"""# 구간기록의 함수율·월·게이트 보정 후보 v1

구간기록에도 모델에서 시험할 초 단위 값을 만들었다. **출발200m·마지막600m·마지막200m를 직접 추정**하고 기존 구간 함수율 후보를 연결했다. 전체시간 보정을 거리 비율로 나누지 않았다. 직접 구간끼리 겹치는 부분이 있으므로 중간 잔여값을 따로 표시해 전체 합계와 일치시킨다.

## 서울1600m10두10번의 게이트 예시

건조에서 원래 시간에 더할 게이트 후보는 출발200m−0.034초, 마지막600m−0.083초, 마지막200m−0.044초다. 마지막200m는 마지막600m에 포함되므로 두 값을 함께 전체시간에 가산하지 않는다. 겹치지 않는4개 구간과 전체시간을 나란히 보면 다음과 같다.

{markdown(core)}

middle1은 이 거리에서800m, middle2는400m다. 중간800m의+0.006초는 독립 추정치가 아니라 기존 전체−0.111초에서 직접 early/last600 보정을 뺀 잔여값이다. 직접 구간은 조건부 기록 차이이며, 전개·게이트 선택의 영향도 포함한다. 구간 능력이나 실제 이동거리 손실을 직접 측정한 값은 아니다.

부산1600m12두1번 건조의 직접 게이트 후보는 출발200m−0.007초·마지막600m−0.081초·마지막200m−0.039초다. 전체 게이트 후보−0.103초는 기존v1 값을 유지한다. 거리와 두수가 달라지면 해당 조합의 표를 사용한다.

## 함수율은 기존 구간별 후보를 유지

1200m에서 원시 구간시간에 더할 기존 함수율 후보는 다음과 같다. 건조1~5%,양호6~9%,다습10~14%,포화15~19%,불량20% 이상이다. 수치는 기존2025년까지 학습한 구간 환경계수에서 나온 연구 후보다.

{markdown(m)}

서울 early/late60%·last60040%, 부산 early/late40%·last60030%의 기존 후보량을 재사용했다. 전체시간의 서울80%·부산90%를 구간에 복사하지 않았다. 다른 거리의 지원 여부와 값도 원래 표대로 유지했다. 구간 보정은 공식 채택과 구분되는 시험 후보이며, 기존 결과에서 다음 출전 예측 개선이 충분히 확인된 것은 아니다.

## 월·게이트의 새 구간 추정

같은149,624출전 원장에서 전체4MAD148,338출전과 최근2024년 이후4MAD를 사용했다.14개 지역×거리 중 표본이 되는 기간에서75개 공통 설계 모형으로3목표를 추정했다.26,601개 시간 프로필,25,860개 구간 게이트 lookup행,900개 월 lookup행을 보존했다. 직접 구간별로 이상치를 추가 제거한 결과는 아니며 기존 전체시간 잔차 기준을 유지했다.

게이트는 같은 경주·같은 말을 통제한다. 기본은 추정차이30%×n/(n+100), 상태 추가는(상태−기본 차이)15%×n_s/(n_s+100)다. 실제 두수에서 평균0으로 중심화한 후 기본 상한을early0.05초/last6000.08초/late0.04초, 상태 추가 상한을0.02/0.03/0.02초로 제한한다. q를 적용 스위치로 쓰지 않으며 미식별 기본은 중립0, 미관측/미식별 상태는 기본만 유지한다.

월은 동일 마필·등급×연도·정확 숫자 함수율·두수·성별조건·게이트·나이·중량·체중·레이팅·과거 이력을 통제한 연간1·2차 곡선이다. 월 추정차이30%×n_month/(n_month+100)을 반영하고 연간12월 평균0으로 중심화한다. early0.03초/last6000.06초/late0.03초 상한을 유지한다. 월은 건조 기준이 아니라 연간 평균 기준이다.

이 비율·상한은 모델 시험을 시작하기 위한 정책값이다. 최적량·베이지안 사후확률·인과 보정량으로 표시하지 않는다. 초반이 느려 막판이 빨라진 전개와 그 반대를 완전히 제거한 구간 능력 점수도 아니다. 새 구간값으로 다음 경주 성능이 좋아지는지는 별도 후속이다.

## 중간 구간과 전체 합계

직접 보정 A_early,A_last600,A_late와 기존 전체시간 A_finish를 이용해 다음 항등식을 지킨다.

- A_middle1 = A_finish − A_early − A_last600
- A_middle2 = A_last600 − A_late
- A_early + A_middle1 + A_middle2 + A_late = A_finish

함수율·월·게이트 성분마다 각각 이 관계를 적용한다. middle1은D−800m, middle2는 결승600m 전~200m 전400m다. middle2는 ‘마지막400m’와 다르다. 마지막600m와마지막200m를 독립 능력이나 추가 전체시간 효과로 합산하지 않는다.

중간 값은 **기존 전체 보정과 일치시키는 잔여 환산값**이다. 서로 다른 목표·후보률의 차이도 흡수하므로 중간의 독립 환경효과나 인과 분해로 해석하지 않는다. 직접 구간에 둔 작은 상한이 중간 잔여값에도 적용되는 것은 아니다. 첫 모델 입력으로는 직접3목표를 구분해 사용하고, 중간 잔여값의 독립 활용은 별도 검토할 수 있다.

## 계산 예시와 적용 함수

아래는 실제 말의 관측 기록이 아닌 가상 서울1200m·11두·외측·포화·9월 입력이다. 원기록73초, early14초,last60039초,late13초로 두고 함수율·월·게이트를 합쳤다.

{markdown(ex)}

기본 함수는 월 후보를 끄고 반환한다. `include_month=True`로 위 예시처럼 켤 수 있고 `gate_strength=0/0.5/1`로 시험 강도를 조절한다. [apply.py](apply.py)의 `SectionNormalizer.normalize_record`에 기존 전체시간 입력과early/last600/late를 전달하면 직접·잔여 구간과전체 결과를 구분해 받는다. 날짜·마번 전체 목록·숫자 함수율 검증은 기존 전체시간 함수 규칙을 유지한다.

서울4C530m와 부산 관측 마지막400m는 이번 직접 보정 대상에 포함하지 않았다. 계측 지점이 다르므로 다른 구간 보정을 복제하지 않는다. 실제 마군 내외측 주행 효과도 포함하지 않는다.

## 범위·검증·사용 시점

전체151,074출전에 원시·보정 후보 원장을 만들었다. 각 직접 구간은142,206출전에서 함수율까지 지원되고, 전체시간과4개 독립 구간이 모두 지원되는133,223출전에서 완결된 합계를 제공한다. 미지원은null로 남기며 중간잔여값도 필요한 항이 모두 있을 때만 계산한다. 희소 장거리는 자체 게이트/월 모형이 없다는 상태를 보존한다.

[독립 검증](outputs/verification.json)에서1200/1600m 전체기간36개 목표의 명시적 희소 고정효과 해를 대조했다. 최대 대비 오차{verification["max_contrast_error_seconds"]:.3g}초다. 수축5,760벡터·151,074출전 항등식·440개 개별/일괄 결과·잘못된 입력5개·기존 전체시간 v1과 구간 함수율 원본 보존·입력 해시를 확인했다. 현재 시점의 과거기록 정규화 원장이며 과거 당시 예측용 피처는 아니다.

서울 자료 종료2026-09-20·부산2026-09-18, 파일 사용 가능일2026-10-08이다. 이전as_of는 거부하고 과거 예측 평가 시점에는 당시 이전 자료로 표를 다시 만들어야 한다. 운영 모델·DB·웹 배포는 변경하지 않았다.

[계획](PLAN.md) · [직접 효과](outputs/section_seconds_profiles.csv) · [게이트 표](outputs/section_gate_lookup.csv) · [월 표](outputs/section_month_lookup.csv) · [구간 함수율](outputs/section_moisture_reference.csv) · [출전별 원장](outputs/runner_section_candidates.parquet) · [게시 요약](PUBLICATION.md) · [출처](SOURCES.md) · [용량](outputs/artifact_inventory.json).
"""
    (HERE / "README.md").write_text(text)
    publication = """# 구간기록에도 작은 보정값을 적용한다면

출발200m·마지막600m·마지막200m를 각각 목표로 삼아 구간 보정 후보를 만들었다. 서울1600m10두10번 게이트의 건조 주로 예시는 출발200m−0.034초·마지막600m−0.083초·마지막200m−0.044초다. 원래 구간기록에 더하는 값이며, 전체시간을 거리 비율로 나눈 값이 아니다.

마지막200m는 마지막600m에 포함된다. 두 값을 전체시간에 함께 더하지 않고, 출발200m·중간 구간·후반400m·마지막200m로 겹치지 않게 표시한다. 중간 구간의 보정은 기존 전체시간과 직접 구간의 차이를 맞추는 잔여값이며 독립적으로 추정한 환경효과와 구분한다.

기존 구간별 함수율 후보에 새 월·게이트 후보를 연결했다. 표본이 적으면 작게 반영하고 각 성분에 상한을 둔다. 구간 보정률은 전체시간의 보정률과 다르며 예측 성능으로 찾은 최적값은 아니다. 실제 경주 전개와 능력을 완전히 분리한 점수도 아니다.

직접 구간별 값·함수·출전 원장을 준비했고, 운영 모델과 다음 경주 예측 개선은 별도로 검토한다. 서울4C530m·부산 관측 마지막400m·실제 주행위치는 이번 직접 보정에 포함하지 않는다.

[계산 방법과 표](README.md).
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    sources = "# 고정 출처와 해시\n\n기존 로컬 원천과 연구 산출물만 재사용했다. 새 API·DB 조회는 없다.\n\n"
    for name, digest in summary["input_sha256"].items():
        p = N.ROOT / name
        sources += f"- [{p.name}]({os.path.relpath(p, HERE)}): SHA-256 `{digest}`\n"
    sources += "\n[구간 함수율 원 연구](../20261002_moisture_section_strength/README.md) · [전체 게이트 v1](../20261008_gate_model_candidate_v1/README.md) · [원시 구간 검증](../20261007_sex_ability_gap/README.md).\n"
    (HERE / "SOURCES.md").write_text(sources)
    gate = pd.read_csv(OUT / "section_gate_lookup.csv", dtype={"level": str})
    month = pd.read_csv(OUT / "section_month_lookup.csv")
    cols = [
        "meet",
        "distance_m",
        "field_size",
        "mode",
        "block",
        "band",
        "period",
        "level",
        "section",
        "base_n",
        "state_n",
        "status",
        "base_add_seconds",
        "state_add_seconds",
        "gate_add_seconds",
    ]
    payload = dict(
        title="구간기록 보정 후보 v1",
        status="trial_only",
        summary=summary,
        gate_lookup=json.loads(gate[cols].to_json(orient="records", force_ascii=False)),
        month_lookup=json.loads(month.to_json(orient="records", force_ascii=False)),
        focus=json.loads(focus.to_json(orient="records", force_ascii=False)),
        examples=json.loads(example.to_json(orient="records", force_ascii=False)),
        overlap="last200 is inside last600; middle1 and middle2 corrections are identity residuals",
        production_changed=False,
        prediction_validation=False,
    )
    (OUT / "web_section_candidate_v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
    )
    (
        HERE.parent / "conclusions/02A_SECTION_NORMALIZATION_CANDIDATE_V1.md"
    ).write_text("""# 구간기록 함수율·월·게이트 보정 후보 v1

출발200m·마지막600m·마지막200m를 직접 목표로75개 공통 설계 모형·26,601프로필을 추정하고 기존 구간 함수율 후보를 연결했다. 서울1600m10두10번 건조의 게이트 후보는각각−0.034초·−0.083초·−0.044초다. 마지막200m는 마지막600m에 포함되므로 전체시간에 중복 가산하지 않는다.

겹치지 않는4개 구간의 보정은 출발200m−0.034초·중간800m+0.006초·후반400m−0.038초·마지막200m−0.044초이고 전체−0.111초와 일치한다. 중간값은 직접 early/last600/late와 기존 전체 v1을 일치시키는 잔여 환산값이며 독립 중간효과나 인과 분해가 아니다.

게이트 기본30%·상태차15%와표본 수축, 월30%와표본 수축을 사용하며 각 직접 구간에 별도 상한을 둔다. 정책적 시험 시작값이고 최적량·예측 개선·공식 채택은 아니다. 기존 구간 함수율 서울early/late60%·last60040%,부산early/late40%·last60030%를 재사용하며 전체시간80%/90%를 복제하지 않는다.

전체151,074출전 원장, 직접 구간142,206출전·완결된 전체와4구간133,223출전을 제공한다.36개 독립 목표 풀이·수축·항등식·440개 개별/일괄 결과를 검증했다. 구간별 이상치 추가 제거는 하지 않았고 기존 전체시간4MAD 표본을 유지한다. 서울4C530m·부산 관측 마지막400m·실제 주행위치 제외, 운영 변경·다음 경주 예측 검증 없음.

37번째 실증 연구이며 기존 구간 공식 채택 보류를 유지하면서 별도 모델 시험 입력을 만든다. 사용 가능일2026-10-08 이전 예측용으로 쓰려면 그 시점 이전 자료로 다시 적합해야 한다.

[원 보고서](../20261008_section_normalization_candidate_v1/README.md) · [적용 함수](../20261008_section_normalization_candidate_v1/apply.py) · [게이트 표](../20261008_section_normalization_candidate_v1/outputs/section_gate_lookup.csv) · [검증](../20261008_section_normalization_candidate_v1/outputs/verification.json).
""")
    print(focus.to_string(index=False))


if __name__ == "__main__":
    main()

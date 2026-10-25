# ruff: noqa: E501 -- Stored Markdown paragraphs retain native line breaks.
"""Publish the trial lookup locally, without changing the operational model."""

import importlib.util
import json
import os
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("builder", HERE / "build.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
SPEC2 = importlib.util.spec_from_file_location("application", HERE / "apply.py")
H = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(H)


def markdown(df, cols):
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
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["passed"]
    summary = json.loads((OUT / "summary.json").read_text())
    table = pd.read_csv(OUT / "gate_correction_lookup.csv", dtype={"level": str})
    default = table[table.period.eq("all_mad4")]
    focus = default[
        (
            (
                default.meet.eq("서울")
                & default.distance_m.eq(1600)
                & default.field_size.eq(10)
                & default["mode"].eq("number")
                & default.level.eq("10")
            )
            | (
                default.meet.eq("부산")
                & default.distance_m.eq(1600)
                & default.field_size.eq(12)
                & default["mode"].eq("number")
                & default.level.eq("1")
            )
        )
    ].copy()
    focus.to_csv(OUT / "1600_trial_gate_values.csv", index=False)
    display = focus[
        [
            "meet",
            "distance_m",
            "field_size",
            "level",
            "band",
            "base_add_seconds",
            "state_add_seconds",
            "gate_add_seconds",
        ]
    ].rename(
        columns={
            "meet": "지역",
            "distance_m": "거리m",
            "field_size": "두수",
            "level": "게이트",
            "band": "상태",
            "base_add_seconds": "기본보정초",
            "state_add_seconds": "상태추가초",
            "gate_add_seconds": "최종게이트초",
        }
    )
    norm = H.Normalizer(OUT)
    examples = []
    for label, meet, dist, n, gate, moisture, finish in [
        ("서울1600 건조 10번", "서울", 1600, 10, 10, 3, 100.0),
        ("서울1600 포화 10번", "서울", 1600, 10, 10, 17, 100.0),
        ("부산1600 건조 1번", "부산", 1600, 12, 1, 3, 100.0),
        ("서울1200 건조 외측", "서울", 1200, 11, 11, 3, 73.0),
        ("서울1200 포화 외측", "서울", 1200, 11, 11, 17, 73.0),
        ("서울1600 불량 총보정 미지원", "서울", 1600, 10, 10, 21, 100.0),
    ]:
        values = norm.normalize_record(
            meet=meet,
            distance=dist,
            finish=finish,
            moisture=moisture,
            record_date="2026-09-18",
            horse_number=gate,
            roster=list(range(1, n + 1)),
            as_of="2026-10-08",
            include_month=True,
        )
        examples.append(
            dict(
                example=label,
                meet=meet,
                distance_m=dist,
                field_size=n,
                horse_number=gate,
                moisture=moisture,
                **values,
            )
        )
    example = pd.DataFrame(examples)
    example.to_csv(OUT / "application_examples.csv", index=False)
    compact = example[
        [
            "example",
            "raw_finish",
            "moisture_add_seconds",
            "month_add_seconds",
            "gate_add_seconds",
            "normalized_finish",
        ]
    ].rename(
        columns={
            "example": "가상예시",
            "raw_finish": "원기록",
            "moisture_add_seconds": "함수율",
            "month_add_seconds": "월후보",
            "gate_add_seconds": "게이트후보",
            "normalized_finish": "최종기록",
        }
    )
    details = f"""# 모델 시험용 기록 보정 v1

모델에 넣어 비교할 **실제 초 단위 잠정값**을 만들었다. 서울1600m10두10번은 건조−0.111초·포화−0.081초, 부산1600m12두1번은 건조−0.103초다. 기존 함수율 보정에 더할 수 있는 게이트 후보이며 최적량·공식 채택·예측 개선을 뜻하지 않는다. 엄격한 확증적 채택 기준을 통과한 값과 별도로 보존한다.

## 계산에 사용할 값

아래 수치를 원래 완주시간에 더한다. 음수는 불리한 조건의 기록을 조금 빠르게 환산하고, 양수는 유리한 조건의 기록을 조금 느리게 환산한다. 전체 게이트 평균을 이동시키지 않도록 같은 두수에서 평균0을 유지한다.

{markdown(display, list(display.columns))}

서울1200m11두 외측 그룹의 게이트 후보는 건조−0.028초·포화−0.004초다. 건조에서 나타난 외측 불리함을 작게 반영하고 포화에서는 더 줄인다. 내측은 각각+0.032초·+0.005초다. 내측은 마번 순서 앞4두, 중간3두, 외측은뒤4두로 구분한다. 실제 마번이 연속되지 않아도 상대 서열로 처리한다.

## 과도한 확정을 피하는 적용 규칙

기본 게이트 추정 차이의30%에 표본수 n/(n+100)을 곱한다. 주로상태별 추정치와 기본 추정치의 차이는15%에 상태 표본수 n_s/(n_s+100)을 곱한다. 각 실제 두수에서 두 성분을 각각 평균0으로 중심화하고 기본±0.15초·상태 추가±0.05초 상한을 벡터 전체 수축으로 지킨다. 후보의 최종 절댓값은±0.20초 이내이며 실제 이번 표의 최대는{summary["max_gate_seconds"]:.6f}초다. 상한은 달성 목표가 아니다.

30%·15%·100출전은 이번 v1의 **정책적 시작값**이다. 최적화나 예측 검증으로 찾은 값이 아니다. 수축은 표본이 적으면 자연스럽게 작아지게 하는 장치이며, 출전수가 독립 표본 수라고 가정하거나 겹치는 두 추정치를 독립 증거로 더하지 않는다. 이 규칙을 정식 계층모형·베이지안 사후 추정이라고 부르지 않는다.

q<0.05와100출전을 적용 켜짐/꺼짐 기준으로 쓰지 않는다. 식별되는 소표본도 작게 반영한다. 기본 블록의 전체 대비가 식별되지 않으면 중립0과 이유를 남기고, 상태 블록이 미관측/미식별이면 기본값만 유지한다. 중립0은 측정 효과0이 아니다. 최근 표본에 같은 규칙을 적용한 감도표는 별도 `recent_mad4`로 남겼고 기본표는 `all_mad4`다.

이 방식은 기존의 ‘확증 조건을 모두 충족한 새 보정0개’ 결론을 취소하지 않는다. 사용자가 필요로 하는 모델 시험 입력을 별도 만든 후속이다. 낮은 근거를 확정 근거로 승격한 것이 아니라 적용 강도를 작게 제한한 것이다.

## 함수율·월 후보와 조합

`moisture_gate_v1 = 원기록 + 채택 함수율 보정 + 게이트 후보`

`moisture_month_gate_v1 = 원기록 + 채택 함수율 보정 + 월 후보 + 게이트 후보`

함수율은 기존 채택값을 그대로 복사했다. 월은 기존6개 지역×거리 후보표만 재사용한다. 서울1600m에는 채택된 월 후보표가 없으므로 월 추가0과 후보 부재를 표시한다. 함수율 자체가 미지원인 경우 두 총보정기록은null이다. 게이트 성분만 별도로 사용할 수는 있지만 ‘전체 주로 보정 완료’로 표시하지 않는다. 다음 표는 실제 말의 관측 기록이 아닌 계산을 보여주는 가상 입력이다.

{markdown(compact, list(compact.columns))}

우선 모델 비교에 사용할 세 가지 강도는 게이트0배·0.5배·1배다.0배는 기존 함수율 기준,0.5배는 이 v1의 절반,1배는 이 표 그대로다. 월 후보는 별도 스위치로 둔다. 여러 거리·주로상태별로 다시 가장 잘 맞는 강도를 고르는 작업은 아직 수행하지 않았다. 기존 게이트 후보·번호와 그룹·실제 주행위치 효과를 추가 중복 가산하지 않는다. 전체시간 보정을 구간시간에 복제하지 않는다.

## 적용 함수와 현재 시점 원장

[apply.py](apply.py)의 `Normalizer.normalize_record`는 지역·거리·원기록·숫자 함수율·기록일·해당 마번·전체 출전마 마번 목록·적용 기준일을 받는다. `include_month=False`가 기본이고 `gate_strength=1.0`은 v1 전체 강도다. 함수는 모형·표 파일을 읽기만 하며 DB나 운영 코드를 수정하지 않는다.

정확1~10/1~12번이 모두 존재하는10/12두는 번호별 표를 사용한다. 취소 등으로 마번이 비면 해당 두수의 상대3그룹 표를 사용한다. 취소마가 제외된 실제 출전마 전체 목록을 전달하되, 경주후 분석 품질 제외로 목록을 추가 축소하지 않는다. 예를 들어11두 `[1,2,...,10,12]`의12번은 외측 그룹이며 가상의12두12번 효과를 받지 않는다. 표 밖의 거리·두수는 중립0과 `neutral_unavailable`을 반환한다.

전체151,074출전에 현재 시점의 시험값을 붙인 [후향 원장](outputs/runner_trial_normalization.parquet)을 만들었다.149,624출전에 게이트 후보가 있고, 함수율까지 지원되는133,223출전에 총보정기록을 만들었다. 나머지는 null/중립의 원인을 보존한다. 이는 현재 기준으로 과거 기록을 읽는 원장이며 당시 예측용으로 생성된 피처가 아니다.

서울 자료 종료2026-09-20·부산2026-09-18, 파일 작성일과 사용 가능일은2026-10-08이다. 함수는 그 이전 `as_of`를 거부한다. 과거 예측 검증에는 각 평가 시점 이전 자료만으로 같은 규칙의 표를 다시 만들어야 한다. 현재 표를 과거 평가 시점에 그대로 넣으면 미래자료가 섞인다.

## 검증과 현재 상태

8,620개 lookup행·1,920개 수축 벡터를 독립 산식으로 확인했다. 평균0 오차는{verification["max_weighted_mean_error_seconds"]:.3g}초이며,350개 개별 함수 결과와 일괄 원장·8개 잘못된 입력·마번 공백 처리·함수율 보존·입력 해시를 검증했다. 모형 성능 개선과 실운영 적용은 수행하지 않았다. 사용자는 이제 숫자와 적용 함수를 바탕으로 다음 모델 실험을 진행할 수 있다.

[고정 계획](PLAN.md) · [전체 게이트 표](outputs/gate_correction_lookup.csv) · [적용 설정](outputs/config.json) · [예시](outputs/application_examples.csv) · [독립 검증](outputs/verification.json) · [게시 요약](PUBLICATION.md) · [웹 데이터](outputs/web_gate_candidate_v1.json) · [출처](SOURCES.md) · [용량](outputs/artifact_inventory.json).
"""
    (HERE / "README.md").write_text(details)
    publication = """# 기록 보정의 작은 시작값

게이트 유불리를 모델에서 시험할 수 있도록 보수적인 초 단위 후보를 만들었다. 서울1600m10두10번은 건조−0.11초·포화−0.08초, 부산1600m12두1번은 건조−0.10초다. 불리한 조건의 기록을 약간 빠르게 환산하는 음수 보정이다.

거리·두수·게이트 기본 차이의 일부만 반영하고, 함수율 상태별 추가 차이는 표본이 적을수록 기본값에 가깝게 줄였다. 기존 함수율 보정에 이 값을 더하며 월 후보는 별도로 선택한다. 같은 두수에서 평균0을 유지하고 게이트 총보정의 절댓값은0.20초 이내로 제한했다.

이 숫자는 예측 성능으로 선택한 최적값이 아니라 시험용 시작값이다. 소표본을 확정 결과로 바꾸지 않고, 새 후보의 강도를0배·절반·전체로 비교할 수 있게 했다. 실제 주행위치 보정은 포함하지 않는다.

현재 시점에서 과거 출전기록을 읽는 원장과 적용 함수를 준비했다. 과거 시점 예측을 검증할 때는 당시 이전 자료로 표를 다시 만들어야 한다. 운영 모델 반영·다음 경주 성능 검증은 아직 수행하지 않았다.

[상세 방법과 표](README.md).
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    sources = "# 고정 출처\n\n새 데이터 조회 없이 앞 연구 산출물을 재사용했다. 원시 효과와 적용 규칙의 출처를 구분한다.\n\n"
    for name, digest in summary["input_sha256"].items():
        p = B.ROOT / name
        sources += f"- [{p.name}]({os.path.relpath(p, HERE)}): SHA-256 `{digest}`\n"
    sources += "\n[기본 게이트 시간 연구](../20261008_gate_lateral_seconds/README.md) · [상태 교차 연구](../20261008_moisture_gate_seconds/README.md) · [기존 함수율·월 후보](../20261008_record_normalization_seconds/README.md).\n"
    (HERE / "SOURCES.md").write_text(sources)
    usecols = [
        "meet",
        "distance_m",
        "field_size",
        "mode",
        "block",
        "band",
        "period",
        "level",
        "base_n",
        "state_n",
        "base_available",
        "state_available",
        "status",
        "base_add_seconds",
        "state_add_seconds",
        "gate_add_seconds",
    ]
    payload = dict(
        title="모델 시험용 게이트 시간 보정 v1",
        policy=summary["policy"],
        summary=summary,
        lookup=json.loads(table[usecols].to_json(orient="records", force_ascii=False)),
        focus=json.loads(focus.to_json(orient="records", force_ascii=False)),
        examples=json.loads(example.to_json(orient="records", force_ascii=False)),
        status="trial_only",
        production_changed=False,
        predictive_validation=False,
    )
    (OUT / "web_gate_candidate_v1.json").write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
    )
    central = HERE.parent / "conclusions/04E_GATE_MODEL_CANDIDATE_V1.md"
    central.write_text("""# 모델 시험용 게이트 시간 보정 v1

확증적 채택 보류와 구분하여 모델에 넣을 작은 초 단위 후보를 만들었다. 기본 게이트 효과30%×n/(n+100), 상태−기본 차이15%×n_s/(n_s+100)을 각각 같은 두수 평균0으로 중심화한다. 기본±0.15초·상태 추가±0.05초 상한, 합계±0.20초 이내다. 정책적 시작값이며 최적화·예측 검증·베이지안 추정 결과가 아니다. q를 적용 켜짐/꺼짐 기준으로 쓰지 않는다.

서울1600m10두10번 건조−0.111초·포화−0.081초, 부산1600m12두1번 건조−0.103초가 계산됐다. 서울1200m11두 외측은 건조−0.028초·포화−0.004초다. 기존 함수율에 가산하며 월 후보는 별도 스위치다. 원시효과와 부호를 반대로 적용하며 번호/그룹·기존 게이트·실제 주행위치를 중복하지 않는다.

8,620행 표와151,074출전 후향 원장, 적용 함수를 준비했다.14개 지역×거리의 기본 모형 범위를 유지한다. 기본 미식별/모형 부재는 중립0, 상태 미식별/미관측은 기본만 유지하고 이유를 남긴다. 함수율 미지원이면 총보정기록은null이다. 표 작성일2026-10-08 이전 as_of는 거부하며 과거 예측 평가용 표는 당시 이전 자료로 다시 만들어야 한다.

36번 상태 교차 연구의 적용 후속으로, 독립 실증 연구 수를 늘리지 않는다. 기존 확증적 후보0개 결론·전체시간 함수율 채택·월 후보는 유지한다. 이번 v1은 모델 시험용 후보이고 운영 변경·다음 경주 성능 검증은 없다.

[원 보고서](../20261008_gate_model_candidate_v1/README.md) · [적용 함수](../20261008_gate_model_candidate_v1/apply.py) · [전체 표](../20261008_gate_model_candidate_v1/outputs/gate_correction_lookup.csv) · [검증](../20261008_gate_model_candidate_v1/outputs/verification.json).
""")
    print(example[["example", "gate_add_seconds", "normalized_finish"]].to_string(index=False))


if __name__ == "__main__":
    main()

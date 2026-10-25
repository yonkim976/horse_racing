"""Write a reviewable local report; never promote the research candidate."""
# ruff: noqa: E501

import json
from pathlib import Path

import pandas as pd
import run as experiment

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
NAMES = {
    "baseline22": "현재 월·게이트·부중",
    "raw_sections": "구간 원기록 추가",
    "adjusted_sections": "구간 보정 적용",
    "style_history": "회복·후퇴 이력 추가",
    "field_context": "상대 편성 추가",
    "pace_stack": "전개 예측값 추가",
}


def main():
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["passed"]
    contracts = json.loads((OUT / "stack_feature_contract.json").read_text())
    metrics = pd.read_csv(OUT / "metrics.csv")
    pairs = json.loads((OUT / "paired_differences.json").read_text())["comparisons"]
    op = json.loads((OUT / "operating_comparisons.json").read_text())["comparisons"]
    source = json.loads((OUT / "input_manifest.json").read_text())
    text = [
        "# 구간·전개·상대 정보를 추가한 복승/축마 실험",
        "",
        "2026-10-09. 연구 후보. 운영/DB/웹 및 선택된22개 기준 모델 변경 없음.",
        "",
        "현재22개 입력을 고정하고 구간 원기록·구간 환경 보정·과거 회복/후퇴·현재 상대 편성·시간순 전개 예측값을 단계별로 추가했다. 같은 입력의3위이내 학습과2위이내 학습을 별도로 비교했다. 점추정이 높은 후보를 자동 승격하지 않는다.",
        "",
        "## 결과 해석",
        "",
        "가장 유망한 다음 연구 후보는 구간 보정과 회복·후퇴 이력을 포함한53개 입력이다.3위이내 학습에서 현재22개 대비 축2위이내는47.38%→48.97%(+76경주), 축과 상대3두의 복승3조합은26.21%→28.67%(+118경주)였다. 같은 경주의 날짜 단위95%구간은 각각+0.60~+2.72%p,+1.46~+3.51%p다. 복승1조합은12.00%→12.46%지만 차이 구간−0.28~+1.23%p라 개선 방향을 확정하지 않는다.",
        "",
        "구간 원기록 자체의 추가가 먼저 도움이 됐다. 원기록에서 구간 보정으로 바꾼 추가 적중 차이는 작고 불확실했다. 보정의3위이내 조합 NLL은 소폭 개선됐지만 Brier와 적중률 구간은0을 포함했다. 전체53개 후보의 향상을 보정 단독 효과로 해석하지 않는다.",
        "",
        "상대 편성70개와 전개 예측77개까지 추가해도53개보다 축/축3조합의 점추정이 높아지지 않았다.70개→77개의 주 적중 지표 차이 구간도0을 포함했다. 이 결과는 이번 입력·학습 구조에서 전개 보조예측의 추가 적중 효과를 확인하지 못했다는 뜻이다.2위이내 목표로 바꾼 경우에도 같은 입력의3위이내 목표 대비 주 적중 지표 차이 구간이 모두0을 포함했다.",
        "",
        "운영과 정확히 같은1,258경주에서는53개·3위이내 학습의 축2위이내50.24%와 운영49.76%의 차이가 불확실했다. 복승1조합은13.51%로 운영15.90%보다 낮았다(차이−2.38%p,95%구간−4.26~−0.57%p). 따라서 운영을 대체할 근거는 없고, 기존22개 선택을 유지한 채53개를 다음 검증 후보로 남긴다. 운영과 연구는 학습 구성도 달라 성능 차이를 입력만의 효과로 볼 수 없다.",
        "",
        "모든 구간은 반복 사용한 후향 표본의 탐색적 결과이며 다중비교를 보정하지 않았다. 향후 고정한 미사용 기간에서 다시 검증해야 한다.",
        "",
        "## 같은4,799경주의 전체 결과",
        "",
        "2024-01-05~2026-09-20,50,754출전.2026년은 부분연도. 각 열은 적중 경주 비율이고 괄호는 적중수다. 복승1조합은 평가순위1·2위, 축3조합은1위축과2/3/4위 상대, 상위4두6조합은 네 말의 모든 비순서쌍이다. 최고 공동확률 조합이나 실제 구매/수익률 성적이 아니다.",
        "",
        "| 학습목표 | 입력 후보 | 입력수 | 복승1조합 | 축2위이내 | 축3조합 | 축3위이내 | 상위4두6조합 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for target in [3, 2]:
        for variant in experiment.config()["variants"]:
            row = metrics[
                (metrics.target == target) & (metrics.variant == variant) & metrics.scope.eq("all")
            ].iloc[0]
            values = [
                f"{row[m] * 100:.2f}% ({int(row[m + '_hits']):,})"
                for m in ["quinella_one", "axis_top2", "axis_next3", "axis_top3", "quinella_box4"]
            ]
            text.append(
                f"|{target}위이내|{NAMES[variant]}|{len(contracts[variant])}|"
                + "|".join(values)
                + "|"
            )
    text += [
        "",
        "## 입력을 한 묶음씩 추가한 차이",
        "",
        "같은 경주의 날짜 단위 paired bootstrap2,000회, 탐색적95%구간. 여러 비교를 보정하지 않았고 이 기간은 과거 연구에서도 반복 확인했다. 구간이0을 포함하면 증가/감소 방향을 확정하지 않는다.",
        "",
        "| 목표 | 추가 단계 | 지표 | 차이%p | 95%구간%p | 새로 적중 / 기존 적중 누락 |",
        "|---|---|---|---:|---:|---:|",
    ]
    adjacent = {
        ("raw_sections", "baseline22"),
        ("adjusted_sections", "raw_sections"),
        ("style_history", "adjusted_sections"),
        ("field_context", "style_history"),
        ("pace_stack", "field_context"),
    }
    labels = {"quinella_one": "복승1조합", "axis_top2": "축2위이내", "axis_next3": "축3조합"}
    for row in pairs:
        if (
            row["meet"] != 0
            or row["period"] != "all"
            or row["metric"] not in labels
            or (row["variant"], row["reference"]) not in adjacent
        ):
            continue
        lo, hi = row["date_bootstrap_95_pp"]
        text.append(
            f"|{row['target']}위이내|{NAMES[row['variant']]}|{labels[row['metric']]}|{row['difference_pp']:+.2f}|{lo:+.2f}~{hi:+.2f}|{row['new_only']} / {row['base_only']}|"
        )
    text += [
        "",
        "## 운영과 같은1,258경주 비교",
        "",
        "2026-01-02~09-13. 마번·마필ID·숫자결과가 전부 일치하는 경주만 사용했다. 아래는 운영의 기존3위이내 확률 순위를 고정한 비교다. 운영의2위이내 확률 순위와 지역별 결과도JSON에 별도로 있다. 전체4,799경주 결과와 분모를 혼용하지 않는다.",
        "",
        "| 후보 | 복승1조합 | 축2위이내 | 축3조합 | 상위4두6조합 |",
        "|---|---:|---:|---:|---:|",
    ]
    baseline = [
        r
        for r in op
        if r["target"] == 3
        and r["variant"] == "baseline22"
        and r["comparator"] == "operating_top3"
        and r["meet"] == 0
    ]
    text.append(
        "|운영 기존 입상순위|"
        + "|".join(
            f"{next(r for r in baseline if r['metric'] == m)['base_rate'] * 100:.2f}%"
            for m in ["quinella_one", "axis_top2", "axis_next3", "quinella_box4"]
        )
        + "|"
    )
    for target in [3, 2]:
        for variant in experiment.config()["variants"]:
            rows = [
                r
                for r in op
                if r["target"] == target
                and r["variant"] == variant
                and r["comparator"] == "operating_top3"
                and r["meet"] == 0
            ]
            text.append(
                f"|{NAMES[variant]}・{target}위이내 학습|"
                + "|".join(
                    f"{next(r for r in rows if r['metric'] == m)['new_rate'] * 100:.2f}%"
                    for m in ["quinella_one", "axis_top2", "axis_next3", "quinella_box4"]
                )
                + "|"
            )
    text += [
        "",
        "## 입력과 시점",
        "",
        "전체 학습178,497행.2017년부터 목표 학습,2010~2016은 기존 실제슬롯warm-up. 새 구간·통과조는2018년부터라 이전 관측은 결측이다. 새 자료 지원이 없는 말·경주를 제외하지 않았다. 최근5전은T−2·730일내 실제출전 슬롯으로, 결측/부진 출전을 건너뛰지 않는다.",
        "",
        "- 구간은 출발200m·마지막600m·마지막200m의 직전/최근3평균/최근5최고/유효수와 직전거리/동거리 횟수다. 서울에 없는 마지막400m를 생성하지 않았고 부산400m는 이번 공통 실험에서 추가하지 않았다. 겹치는600/200을 별개 설명변수로 제공할 뿐 가산 점수를 만들지 않는다.",
        "- 초반각질은 통과조 첫마군 전원/선입/중단/후미다. 마군 안 내외측 배열을 앞뒤 순위로 읽지 않는다. 후반순위이동은 공식S1F/G3F/G1F/결승의 상대위치 차이며G3F는 결승600m전이다.",
        "- 과거 착순 원값·막판우수 비입상 표식은 새로 넣지 않았다. 회복/후퇴·마지막200m 이동을 계산할 때 과거 최종착순을 간접 사용한다. 과거 후미 빈도만으로 추입형을 확정하지 않는다.",
        "- 상대 편성은 현재 마번과(마번−1)/(실제출주두수−1) 스케일, 자기 제외 전체 상대의 과거 구간·선행/회복·지원/빠른 상대 수다. 취소 번호를 다시 붙이지 않아 이 스케일은1을 초과할 수 있으며 레일 거리나0~1 확정 주행위치가 아니다. 실제 내외측 주행·방향별 압박·경합 의도는 측정하지 않는다. 게이트 입력과 과거 구간 게이트 보정은 다른 단계다.",
        "- 초반4확률/회복/후퇴 보조모형은 이번70개 직접 입력으로2020~2026 각 예측연도의 이전 자료만 학습했다. 기존157/297입력 전개 모형의 직접 연결과 다른 실험이다. 주모형 학습행에도 같은 연도 정답으로 학습한 보조예측을 넣지 않는다.",
        "",
        "## 구간 보정의 범위",
        "",
        "전체기록22개는 그대로 보존하고 구간만 바꿨다.2020~2026 기록연도마다 전년까지 같은 말 월·정확 함수율 모형, 같은 경주/같은 말 게이트 모형을 재추정했다. 연도 이전 자료로 계산된 전체4MAD 마스크를 사용했다. 건조 숫자혼합 대비 상태 효과에 기존 구간별 보수율을 적용한다. 월30%/수축100/구간상한, 게이트기본30%·상태15%/수축100/구간상한을 유지한다.",
        "",
        "이는2026고정조회표를 과거로 가져온 결과가 아니고, 시간순으로 다시 만든 시험 후보다. 기존 고정 표의 값과 정확히 같지 않다.2018/2019·희소거리·함수율 미지원은 원초 유지. 함수율 지원이 있을 때 월/게이트 미지원 성분은중립0으로 두며, 원장의correction_supported는 함수율 부분의 지원을 뜻한다. 모든 세 성분이 확정됐다는 표시가 아니다. 월/게이트/함수율이 독립 인과효과라는 뜻도 아니다.",
        "",
        "## 학습·해석 한계",
        "",
        "Y평가,2017~Y−3초기학습,Y−2조기종료 후2017~Y−2재학습,Y−1온도교정. 기존22모형과 동일 설정/seed/1두수 가중치를 사용했다.3위모형은순위선택의복승 실적이고,2위모형은비순서쌍 합점수softmax를 전년온도로 교정했다. 말별 목표 주변확률 합은 각각3/2다. 타깃간NLL/Brier숫자를 그대로 비교하지 않는다.",
        "",
        "관측 회복/후퇴는 추입 의도·체력 붕괴를 확정하지 않으며 선행밀집/막판우수에 고정 확률 보너스를 주지 않았다. 신마/자료부족 결측, 현재 출전명단/중량의 사전 공개시각 미감사, 반복 사용한 후향 평가/다중비교, 부분2026의 한계를 유지한다. 적중률은 수익률이 아니다.",
        "",
        "## 검증·재현",
        "",
        f"검증 통과. 동결22개 전부 불변, 저장 주모형{verification['finish_heads_replayed']}개와 보조모형{verification['auxiliary_heads_replayed']}개 재추론, 기존50,754개 기준선 예측 재현. 독립 실제슬롯/자기제외/순위선택/확률합/T−2·730일/연도경계/해시 검사를 수행했다. 수치 검사{verification['numeric_checks']:,}개. 상세는[verification.json](outputs/verification.json).",
        "",
        "[사전 계획](PLAN.md) · [전체 입력 계약](outputs/stack_feature_contract.json) · [입력별 설명](FEATURES.md) · [집계/하위집단](outputs/metrics.csv) · [같은경주 차이](outputs/paired_differences.json) · [확률 품질 차이](outputs/paired_probability_differences.json) · [운영대조](outputs/operating_comparisons.json) · [관측지원](outputs/coverage.csv) · [확률교정](outputs/calibration.csv) · [원천해시](outputs/input_manifest.json).",
        "",
        "```sh",
        ".venv/bin/python thoroughbred/research/20261009_section_style_finish_v1/run.py prepare",
        ".venv/bin/python thoroughbred/research/20261009_section_style_finish_v1/run.py stack",
        ".venv/bin/python thoroughbred/research/20261009_section_style_finish_v1/run.py train",
        ".venv/bin/python thoroughbred/research/20261009_section_style_finish_v1/analyze.py",
        ".venv/bin/python thoroughbred/research/20261009_section_style_finish_v1/verify.py",
        "```",
        "",
        "완료된 모형/원천은 보존한다. [용량 명세](outputs/artifact_inventory.json).",
    ]
    content = "\n".join(text) + "\n"
    (HERE / "README.md").write_text(content)
    (HERE / "INPUT_DECISION.md").write_text(
        "# 입력 결정\n\n이 실험은 비교 연구다. 기존 사용자 선택 month_gate_weight22를 보존하며 운영 registry·웹 평가표·DB를 변경하지 않았다. 보고서의 점추정 최고를 자동 선택하지 않는다. 입력 증가와2위이내 학습목표 변경을 각각 검증했으며 이후 선택은 별도 판단이다.\n"
    )
    feature_text = [
        "# 입력 계약",
        "",
        "열 수는 파생값을 포함한 수이며 독립 원천 수가 아니다. raw_sections와adjusted_sections는같은 구간 요약의값만 다르다.",
        "",
        "| 후보 | 입력수 |",
        "|---|---:|",
    ]
    feature_text += [f"|{NAMES[k]}|{len(v)}|" for k, v in contracts.items()]
    feature_text += ["", "## 최종77개 열", "", "| 번호 | 입력 | 출처 |", "|---:|---|---|"]
    for i, col in enumerate(contracts["pace_stack"], 1):
        category = (
            "기존22"
            if col in experiment.BASE
            else "과거 구간/거리"
            if col.startswith("section_")
            else "과거 통과조/회복·후퇴"
            if col.startswith("style_")
            else "이번 상대/게이트"
            if col.startswith("field_")
            else "이전연도까지 학습한 보조예측"
        )
        feature_text.append(f"|{i}|`{col}`|{category}|")
    (HERE / "FEATURES.md").write_text("\n".join(feature_text) + "\n")
    sources = [
        "# 동결 원천",
        "",
        "모든 입력은 기존 로컬 연구 원장이다. 새 웹 수집/DB 갱신 없이 사용했다. 전체 입력은[매니페스트](outputs/input_manifest.json)에SHA256으로 보존했다.",
        "",
    ]
    sources += [f"- `{name}` — `{digest}`" for name, digest in source.items()]
    (HERE / "SOURCES.md").write_text("\n".join(sources) + "\n")
    # Include the manifest's own bytes; omit only its recursive self-hash.
    files = [
        p
        for p in sorted(HERE.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.name != "artifact_inventory.json"
    ]
    items = [
        dict(path=str(p.relative_to(HERE)), bytes=p.stat().st_size, sha256=experiment.sha(p))
        for p in files
    ]
    inventory = OUT / "artifact_inventory.json"
    own_size = 0
    other_size = sum(p.stat().st_size for p in files)
    for _ in range(12):
        experiment.save(
            inventory,
            dict(
                scope="this experiment only",
                self_hash_omitted=True,
                files=len(files) + 1,
                bytes=other_size + own_size,
                mib=(other_size + own_size) / 1048576,
                items=items
                + [dict(path="outputs/artifact_inventory.json", bytes=own_size, sha256=None)],
            ),
        )
        actual_size = inventory.stat().st_size
        if own_size == actual_size:
            break
        own_size = actual_size
    else:
        raise AssertionError("Self-inclusive inventory size did not converge")
    print("Report saved", HERE / "README.md")


if __name__ == "__main__":
    main()

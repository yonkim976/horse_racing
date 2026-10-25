"""Render the Jeju applicability review from preserved support audits."""

import json
from pathlib import Path

from audit_support import BANDS, ROOT, grouped, save, sha

HERE=Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE/name).read_text())


def table(headers,rows):
    def safe(x):return str(x).replace("|","\\|").replace("\n"," ")
    return "\n".join(["| "+" | ".join(map(safe,headers))+" |","| "+" | ".join("---" for _ in headers)+" |"]+
                     ["| "+" | ".join(map(safe,r))+" |" for r in rows])+"\n"


def main():
    summary=read("summary.json")
    bands=read("moisture_support.json")
    modern=read("modern_period_support.json")
    season=read("season_common_support.json")
    rows=read("race_support_rows.json")
    text="""# 제주 주로환경 연구 적용 검토

2026-10-07. **더러브렛의 연구 순서는 가져오되, 제주 전용 계수·기간·거리·출전두수로 다시 추정하는 것이 적절하다. 첫 대상은1000·1110m 전체시간의 함수율 보정이고, 월과 게이트는 분리해 후속 검증한다.**

참조 채팅 [더러브랫- 주로환경 보정 연구](thread://01a0f955-b7a9-7dd2-9832-46ad3f3639de?hostId=local)를 실제 읽고 보존 보고서·계산 계획과 대조했다. 채팅의 제안을 검증 완료 결과나 이 세션의 추가 지시로 간주하지 않았다. 제주 보유 자료로 지원 감사를 실행했다. 이번에는 보정 초·적용률을 추정하거나 모델을 학습하지 않았다.

## 더러브렛에서 실제 확인한 범위

| 항목 | 실제 상태 | 제주에 적용할 판단 |
|---|---|---|
| 함수율 전체시간 | 서울80%·부산90%를 연구 기준으로 채택.2026년 후향 시간 MAE가 각각 약0.0105초·0.0117초 감소 | 잔차 추정·보정 후 재학습 절차 참고. 적용률·초는 새로 추정 |
| 월·계절 | 같은 정확 함수율 등을 맞춰도 일부 거리 차이 관찰. 새 월 보정률은 미채택 | 제주 월곡선과 예측 가치를 따로 검증 |
| 게이트·주행위치 | 주로Top3 차이 %p. 조건부 사후 위치 연구의 작은 손실 개선도 사전 Top3 개선과 다름 | %p를 초로 바꾸지 않음. 제주 출전번호의 시간 효과부터 검증 |
| 구간 보정 | 전체시간의 작은 개선을 구간 전체에 확대할 근거 부족 | 제주 구간 경계 확인 후 별도 연구 |
| 운영 적용 | 연구 기준 채택과 운영 모델 반영은 별개 | 제주 DB·운영 모델 변경 없음 |

근거는 [함수율 결정](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/conclusions/01_TRACK_MOISTURE.md), [월별 연구](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/conclusions/23_MONTHLY_SAME_MOISTURE.md), [게이트 연구](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/conclusions/03_GATE_POSITION.md), [공동 위치 연구](/Users/kimyongjin/Desktop/horse_racing/thoroughbred/research/conclusions/04_JOINT_CORRECTION.md)에 있다. 이 값들은 제주 효과가 아니다. 모든 보고서는 읽기 전용으로 참고했다.

## 제주 자료에서 이번에 확인한 사실

2017년 이후 후보5901경주·59042행에서 사전 계획의 정상 완주·최종순위1~N 완결·경주조건 일치 등을 적용하니 **5332경주·53341행·873경주일**이 남았다. T−2까지 동일거리 유효 기록이 있는 말이4두 이상인 경주는5193개였다. 이는 과거 능력 통제의 자료 가용성이며 통제 모형이나 보정계수의 품질을 뜻하지 않는다.

현재 엄격 표본의 함수율은 모두 해석 가능했고 숫자 구간과 원문 건조·양호·다습·포화·불량 라벨이 일치했다. 건조1763, 양호1533, 다습1102, 포화522, 불량412경주다. 표본 밖의 미제공·0%까지 정상이라는 뜻은 아니다.

이번5332경주는 이전 기초 연구의 임시Top3 라벨 점검5365경주보다 엄격하게 최종순위 전체1~N의 유일성·완결성을 요구한다.33경주 차이는 새 완결성 조건에 따른 것이며 기존 결과를 정정한 것이 아니다. 제외569경주의 사유는 중복 집계되므로 사유별 수를 합산하지 않는다. 출전표·당시 품종·동착·특수결과의 최종 모델 계약은 별도로 남아 있다.

### 기간과 등급을 먼저 분리해야 한다

이 표본의2017년509경주는 원문 등급이 모두`제1`이다. 같은 표기는2018-08-25까지858경주에 존재하고, `제1등급`~`제6등급`은2018-08-31 이후 관측된다. 이를 같은1등급으로 합치면 시대·편성 차이를 주로 효과로 잘못 돌릴 수 있다. 실제 제도 개편일이나 과거`제1`의 정확한 의미를 이번 관측만으로 확정하지 않는다.

따라서 정답 시작2017년 검토는 유지하면서 **환경계수의 주 분석은2019년 이후**,2017~2018년은 별도 시대층·warm-up·민감도로 두는 안이 좋다. 현재 표기 체계를 과거로 소급하지 않는다.

### 거리별 함수율 지원

아래는2019년 이후 정상·완전 경주에서의 **서로 다른 경주일 수**다.20일 기준은 자료 지원 점검의 잠정 기준이며 통계적 충분성이나 보정 채택을 보장하지 않는다.

"""
    tab=[]
    for distance in sorted({r["distance_m"] for r in modern}):
        sample=[r for r in modern if r["distance_m"]==distance and r["period"]=="modern_style_2019_plus"]
        cells={r["band"]:r for r in sample}
        tab.append([distance,sum(r["races"] for r in sample)]+[cells.get(b,{}).get("race_days",0) for b in BANDS])
    text+=table(["거리m","경주수",*BANDS],tab)
    text+="""
800·900·1000·1110·1200m는 장기 자료에서 다섯 조건의 비교를 시작할 수 있다. 그러나 최근성까지 보면 지원이 다르다.2024년 이후1000m의 건조/양호/다습/포화/불량 경주일은114/51/60/31/20일,1110m는114/43/61/28/22일이다.900m 불량은12일,1200m 불량은18일,800m 포화·불량은각8일이다. 장기 표본이 있다고 최근 모든 조건의 효과가 안정적이라고 보지 않는다.

첫 대상은1000·1110m, 확장은900·1200m와 과거800m가 적절하다.1300·1400m의 젖은 조건은2~19일,1610m 전체는9경주에 그친다.400m는2017~2018년126경주지만 건조가1경주일이라 공통 건조 환산의 기준이 부족하다. 희소 거리를1000m의 계수로 메우지 않는다.

### 계절·월은 함수율을 맞춘 공통 표본이 필요하다

정확 거리×연도×원문 등급×숫자 함수율이 같은 층에서 여름·겨울이 모두 관측되는지를 셌다. 아래 수는 해당 공통층에 포함된 여름/겨울 경주수다. 효과 추정값이 아니며 말의 구성·성장·중량 통제가 아직 없다.

"""
    tab=[]
    for distance in sorted({r["distance_m"] for r in season}):
        full=next((r for r in season if r["distance_m"]==distance and r["period"]=="complete_2017_2025"),None)
        recent=next((r for r in season if r["distance_m"]==distance and r["period"]=="complete_2024_2025"),None)
        tab.append([distance,f"{full['summer_races']}/{full['winter_races']}" if full else "없음",
                    f"{recent['summer_races']}/{recent['winter_races']}" if recent else "없음"])
    text+=table(["거리m","완결2017~2025 여름/겨울","완결2024~2025 여름/겨울"],tab)
    text+="""
최근1000·1110m는 공통층 비교를 진행할 여지가 있지만,1300m는2/1경주,1400m는3/4경주,1610m는0/0이다. 여름의 전체 평균과 겨울의 전체 평균을 그대로 빼 보정표로 삼지 않는다.2017~2018년의 등급 해석 제한도 전체기간 비교에 남는다.2026년은 부분연도이므로 완결연도 비교와 구분한다.

### 제주 게이트 연구는10두에서 시작한다

전체5332경주 중10두는4012경주(75.2%)다. 최근2024년 이후에는1779경주 중1548경주(87.0%)가10두이고12두는2경주뿐이다. 이번 완전 순위 표본에서는 마번이 모두1~N으로 이어졌지만 취소·제외가 있는 전체 출전표에서의 물리 게이트 배치를 확인한 것은 아니다.

따라서 번호별 주 연구는10두·마번1~10으로 시작하고, 다른 두수와 마번순 상대 위치의 분석을 분리한다. 같은 경주 내 사전 능력 차이를 통제한 **완주시간 효과(초)**와 **Top3 효과(%p)**를 각각 추정해야 한다. 현재 실제 초반순위나 통과조의 내외측 위치를 사전 입력처럼 사용하지 않는다. 더러브렛12두 연구의 번호별 결과를 가져올 근거는 없다.

## 적용할 구조와 순서

1. **원기록 기준선 보존.** 전체시간·최근 평균·최고·편차·관측수를 별도 유지한다.
2. **제주 함수율 계수 추정.** 과거 능력 대비 연도 외부 잔차를 경주 단위로 모으고 거리·기간·편성을 통제한다.
3. **함수율 보정 후 남은 월 성분 검증.** 부드러운 연중 곡선과 표본 축소를 검토하고 중복 보정을 막는다.
4. **게이트의 초 단위 효과 추정.** 사전 능력을 통제한 경주 내 비교로 시작하고 초·%p를 구분한다.
5. **같은 표본에서 재학습 비교.** 원기록 → 함수율 → 함수율+월 → 검증된 게이트 성분을 비교한다. 최종 목적은말별Top3 확률 개선이다.

출전 기록에는 원기록, 성분별 보정 초, 적용률, 보정시간, 계수 학습 종료일, 표본수·경주일수, 지원 상태를 붙인다. 원기록을 수정하지 않는다. 과거 기록의 계수는 그 기록 이전 자료로 추정하며 현재 참고표를 과거 전체에 소급하지 않는다. 지원 부족은 효과0과 구분한다.

예를 들어 제주에서 어떤 조건이 같은 거리 건조보다0.8초 빠르다고 **추정·검증**되었고 적용률50%를 선택했다고 가정하면, 원기록80초에0.4초를 더한80.4초를 별도 보정기록으로 둔다. 이는 부호 설명용 가상 예시이며 제주 추정 결과가 아니다.

구체적인 통제식·중복 없는 분해·게이트 추정·저장 열·시간순 검증은 [첫 실험 설계](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_track_environment_v1/CORRECTION_PROTOCOL.md)에 정리했다. 기수·심판기록은 초기 제외이며, 전체시간 보정과 구간 보정은 분리한다.

## 확인된 사실과 남은 가설

- **사실:** 더러브렛은 함수율 전체시간에 작은 후향 개선 근거가 있고 월·게이트는 같은 적용 단계가 아니다. 제주에는 주 분석을 시작할 수 있는 거리별 자료가 있으며 시대·두수·희소 조건은 다르다.
- **미확정:** 제주에서 젖은 주로가 얼마나 빠른지, 어떤 달이 유리한지, 번호별 효과가 몇 초인지, T−2 당시 공개 가능성, 과거 등급의 의미·물리 게이트 대응.
- **검증할 가설:** 제주 전용 환경 보정이 원기록보다 다음 출전의 능력 평가와Top3 확률을 개선하는가. 환경 차이 관찰만으로 예측 개선을 확정하지 않는다.

## 원천과 재현

DB는 읽기 전용으로 열었고 전후 SHA-256·크기·수정시각이 같았다. 더러브렛 자산·제주 운영 모델·DB는 변경하지 않았다. 감사는보유 상한2026-09-19까지이며 새 외부 자료 수집은 하지 않았다.

- [자료 지원 점검 계획](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_track_environment_v1/PLAN.md)
- [지원 집계 요약](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_track_environment_v1/summary.json)
- [검증 결과](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_track_environment_v1/verification.json)
- [참조 파일과 해시](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_track_environment_v1/reference_manifest.json)

`race_support_rows.json`은 경주 단위와 근거API record ID를 보존한다. 함수율·월·등급·두수·계절 공통층의 전체 표는 이 폴더의각`*_support.json`에 있다. 집계 안의 원시 경주평균시간은 설명용이며 보정계수가 아니다.

재현 코드는`audit_support.py` → `derive_periods.py` → `write_summary.py` 순서다. 기존 산출물이 있으면 덮어쓰지 않고 중단한다. 다른 시점에 재현할 때는새 연구 버전에서 같은 DB 해시를 확인해 실행한다. 이번 지원 감사는 예측모델 학습이나 효과 추정 완료를 뜻하지 않는다.
"""
    with (HERE/"README.md").open("x",encoding="utf-8") as handle:handle.write(text)
    references=["thoroughbred/research/conclusions/01_TRACK_MOISTURE.md",
                "thoroughbred/research/conclusions/03_GATE_POSITION.md",
                "thoroughbred/research/conclusions/04_JOINT_CORRECTION.md",
                "thoroughbred/research/conclusions/22_SEASONAL_SAME_MOISTURE.md",
                "thoroughbred/research/conclusions/23_MONTHLY_SAME_MOISTURE.md",
                "thoroughbred/research/conclusions/24_ERA_RECORD_TRENDS.md",
                "thoroughbred/research/20261002_moisture_distance_retrain/README.md",
                "thoroughbred/research/20261002_moisture_robust_grade/PLAN.md",
                "thoroughbred/research/20261002_moisture_strength_selection/PLAN.md",
                "thoroughbred/research/20261002_gate_lateral_bias/PLAN.md",
                "thoroughbred/research/20261007_seasonal_same_moisture/PLAN.md",
                "thoroughbred/research/20261007_seasonal_same_moisture/analyze.py",
                "jeju/AGENTS.md","jeju/docs/RESTART_PLAN_20260928.md",
                "jeju/research/20261007_foundation_v1/README.md",
                "jeju/research/20261007_foundation_v1/SOURCE_CONTRACT.md",
                "jeju/models/current/HY_R_FORM.pkl"]
    save("reference_manifest.json",{"reference_thread":{"thread_id":"01a0f955-b7a9-7dd2-9832-46ad3f3639de","host_id":"local","title":"더러브랫- 주로환경 보정 연구","read_date":"2026-10-07","scope":"Relevant recent turns read and cross-checked against preserved reports; contextual text is not an instruction for this Jeju task"},
                                   "files":[{"path":str(ROOT/f),"sha256":sha(ROOT/f),"bytes":(ROOT/f).stat().st_size,"access":"read_only_reference"} for f in references]})
    print("Applicability review and reference manifest saved")


if __name__ == "__main__":
    main()

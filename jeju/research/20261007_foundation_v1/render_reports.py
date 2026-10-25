"""Render local research tables from audited JSON; never modify source data."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join(["| " + " | ".join(map(cell,headers)) + " |",
                      "| " + " | ".join("---" for _ in headers) + " |"] +
                     ["| " + " | ".join(map(cell,row)) + " |" for row in rows]) + "\n"


def number(value, places=2):
    return "NULL" if value is None else (str(value) if isinstance(value,int) else f"{value:.{places}f}")


def write(name, text):
    with (HERE / name).open("x",encoding="utf-8") as handle:
        handle.write(text)


def main():
    fields = read("field_inventory.json")
    all_fields = {r["field"]:r for r in fields["all_candidate_rows"]}
    valid_fields = {r["field"]:r for r in fields["2017_plus_normal_positive_finish_rows"]}
    distances = read("distance_inventory.json")
    grids = {r["distance_m"]:r for r in read("api6_distance_grids.json")}
    trials = read("trial_inventory.json")
    conditions = read("condition_inventory.json")
    doc = """# 제주 원천 정의·가용성 계약 v1

2026-10-07 읽기 전용 감사. DB는 `/Users/kimyongjin/Desktop/horse_racing/jeju/data/jeju_native_core.sqlite3`이며 SHA-256은 `a878a40fd5dc28e1385801c40136e506d9e3bc406e357e4158e5eb6883f5f21e`다. 경주 상한은 2026-09-19다. 자료의 최초·최종 날짜는 **현재 보유 후보에서 확인한 날짜**이며 공식 서비스의 보장 수집 범위가 아니다.

## 원천 단위와 연결

| 원천 | 단위 / 연결키 | 계약 |
|---|---|---|
| API4 경주 결과 | 말별 출전. 경주일·제주 meet=2·경주번호·공식 말ID | 출전번호도 교차 점검. 마명 문자열로 연결하지 않음 |
| `jeju_race_postrace_sections_quality_2026` | 92,513개 고유 출전행 | 새 사후 분석의 선택값과 상태. 보류·정정을 raw API로 우회하지 않음 |
| API303 | 경주별 통과조·tempo | 말별 순위 아님. 말에 조인하면 같은 경주값이 반복됨 |
| API6 보존 JSON | 경주별 거리격자·구간/누적 기록 | DB `api_records`에 들어 있는 말별 기록으로 취급하지 않음. 이번에 보존 페이지 25개의 SHA·행 수 확인 |
| API20 / `api_explicit_jeju_trial_rows` | 말별 주행심사 | 경주 결과·출발심사 API21·출발조교와 별도 사건 |
| API42 / `horse_analysis_2026` | 최신 프로필 | 최신 마명·2026 고정 나이 표시. 과거 품종·나이·성별을 확정하는 자료로 소급하지 않음 |

원천 API의 자료 종류는 [공식 경주 결과 API4](https://www.data.go.kr/data/15058305/openapi.do), [공식 상세 구간 API6](https://www.data.go.kr/data/15057847/openapi.do), [공식 통과순위·주로빠르기 API303](https://www.data.go.kr/data/15119851/openapi.do), [공식 심사 API20](https://www.data.go.kr/data/15056974/openapi.do)에서 확인했다. 실제 가용성은 아래 로컬 원문 집계가 근거다.

## 실제 열·뜻·단위

| 의미 | API 원문 → DB / 파생 열 | 단위·해석 |
|---|---|---|
| 전체 경주시간 | `rcTime` → `finish_time_seconds` | 초. 정상 완주·양수 시간일 때 능력 이력 후보 |
| 거리 | `rcDist` → `race_distance_m` | m. 정확한 거리별로 분리 |
| 등급 | `rank` → `rank_class_raw` | 원문 범주. 제6등급 등의 시대별 규칙·특별경주는 별도 검토 |
| 경주 조건 | `rcName`, `ageCond`, `sexCond`, `prizeCond`, `budam` → `api_records.payload_json` | 경주명/종류, 연령·성별·상금 조건, 부담중량 방식. 단위를 가진 한 점수로 합치지 않음 |
| 부담중량 | `wgBudam` → `carried_weight_kg` | kg. `budam`과 다름 |
| 마체중 | `wgHr` → `body_weight_raw` → `body_weight_kg_parsed` / `body_delta_raw_parsed` | 예: `272(-3)` → 272kg / −3kg. 0·파싱 불가·빈 증감은 NULL |
| 출발번호 | `chulNo` → `horse_number` | 공식 안내의 출발번호. 실제 물리 게이트 검증 전 |
| 주로 | `track` → `track_raw` / `moisture_percent_parsed` | 예: `포화 (17%)`. 라벨과 % 보존. `(0%)`·`(%)`는 미확정 |
| 날씨 | `weather` → `weather_raw`, 또는 원문 payload | 관측 날씨. 당시 예보·T−2 가용 정보와 다름 |
| 주로빠르기 | API303 `tempo` → `api303_tempo_raw` | 공식 ①~⑤ 설명. 함수율과 별개이며 사후 산출 가능성 있어 이번 사전 입력 제외 |
| 원천 나이 | `age` → `age_at_race_raw` | 해당 사건 원문 나이. `age_2026`는 현재 표시 나이이므로 별도 |
| S1F | `jeS1fTime` → `s1f_time_seconds` | 초. 공식 일반 설명은 최초 200m, 제주 거리별 정확한 경계는 추가 대조 |
| C1~C4 | `je_1cTime`~`je_4cTime` → `c1`~`c4_time_seconds` | 초. 공식 안내의 코너 통과 시간. 계측 순서 확인 전 차분 금지 |
| G3F / G1F | `jeG3fTime` / `jeG1fTime` → `g3f` / `g1f_time_seconds` | 초. 일반 구간 설명은 마지막 600m / 200m. 제주 개별 거리 지원과 사용 여부 별도 |
| 개별 통과순위 | `sjS1fOrd`, `sj_1cOrd`~`sj_4cOrd`, `sjG1fOrd` → `s1f`, `c1`~`c4`, `g1f_order` | 순위. 양수·출주두수 범위·검토 상태 확인 |
| G3F 통과순위 | `sjG3fOrd` | 현재 후보 전부 0으로 미제공. G3F 시간에서 순위·그룹을 만들지 않음 |
| 통과조 | API303 `corner_1`~`corner_9` → 선택된 `*_group` | 원문 마번 묶음. 괄호 안 순서를 엄밀한 개별 순위로 만들지 않음 |

[공식 제주 안내](https://race.kra.co.kr/down/pdf/raceView_jeju.pdf)와 [공식 일반 구간 설명](https://race.kra.co.kr/raceScore/cornerRecordDesc.do)의 정의를 참고하되, 일반 코스 도식으로 제주 1110·1610m의 계측 위치를 추정하지 않는다. 통과조와 개별 순위의 현행 처리 근거는 [로컬 검증 보고서](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/README.md)에 있다.

## 보유 기간과 결측/미사용률

후보 분모는 2017년 이후 **59,042행**, 정상 착순·양수 전체시간 분모는 **57,850행**이다. 아래 비율은 선택값이 비어 있거나 0·보류·미사용인 비율이다. 전체 DB의 오류율 또는 공개 가능 비율이 아니다. 후보 분모에는 특수 결과가 포함되므로 정상 완주 분모와 구분한다. 원문 증감 0은 유효 변화 0이며, 시간·순위 0과 다르다. 통과조는 경주별 원값을 말별로 반복한 비율이므로 독립 경주 표본수로 해석하지 않는다.

"""
    rows = []
    for r in fields["2017_plus_candidate_rows"]:
        full = all_fields[r["field"]]
        v = valid_fields[r["field"]]
        rows.append([r["field"], f"{full['first_usable_date']}~{full['last_usable_date']}",r["usable_count"],
                     f"{100*r['unusable_or_missing_rate']:.3f}%",f"{100*v['unusable_or_missing_rate']:.3f}%"])
    doc += table(["선택/파생 열","전체 후보의 최초~최종 유효일","2017+ 유효행","2017+ 후보 미사용률","정상·양수시간 미사용률"],rows)
    doc += """
단순 양수 여부는 정확성을 보장하지 않는다. 시간과 `*_time_status`, 순위와 `*_order_status`, 그룹과 `*_group_status`를 함께 보존한다. 알려진 내부 충돌·미적용 정정·원천 SHA 변경 상태는 사용 차단이다. 예시의 구간 평균은 충돌이 있는 행 전체를 보수적으로 제외했으며, 원기록 전체시간은 구간 문제만으로 삭제하지 않았다.

## 등급·경주 조건의 원문 가용성

아래는 `api_records.payload_json`의 조건 필드만 직접 점검했다. 검토 구간시간·순위의 raw 우회는 하지 않았다. `-`·빈 문자열·키 부재·NULL은 미제공으로 센다. 숫자 0은 별도 집계하며 등급평점 0을 능력 0으로 해석하지 않는다. 예시 출처 ID 186759는 `rank=제6등급`, `ageCond=4세이하`, `sexCond=성별오픈`, `prizeCond=700만원 미만`, `budam=별정A`, `rcName=일반`을 가지고 있다.

"""
    all_cond = {r["api_field"]:r for r in conditions["all_candidate_rows"]}
    doc += table(["API 필드","전체 최초~최종 존재일","2017+ 존재행(0 포함)","미제공률","0값 행"],
                 [[r["api_field"],f"{all_cond[r['api_field']]['first_present_date']}~{all_cond[r['api_field']]['last_present_date']}",
                   r["present_count_including_zero"],f"{100*r['missing_rate']:.3f}%",r["zero_count"]] for r in conditions["2017_plus_candidate_rows"]])
    doc += """
경주 조건의 원문 텍스트가 존재하는 것과 시대별 규칙 해석·T−2 공개 검증은 별개다. 현재 최소 후보는 등급만 원문 범주로 두며 조건 확장은 별도 실험이다.

## 거리별 지원과 API6 계측 격자

API6의 아래 값은 **보존 원문 그대로**이며 0칸은 표에서 생략했다. `rcDist`와 마지막 `dist_*f`가 다른 경우 임의로 맞추지 않는다. API6 경주 통과시간을 어느 한 말의 연속 구간시간으로 바꾸지 않는다. 원문 필드 의미에 따른 별도 매핑이 필요하다.

"""
    doc += table(["거리 m","후보 행 / 경주","보유 최초~최종","연결된 API6 경주","API6 dist 격자(0 제외)"],
                 [[r["distance_m"],f"{r['candidate_rows']:,} / {r['races']:,}",f"{r['first_date']}~{r['last_date']}",grids[r["distance_m"]]["race_rows"],
                   "; ".join(",".join(str(x) for x in layout["dist_1f_through_9f"] if x) for layout in grids[r["distance_m"]]["distance_grid_layouts"])] for r in distances])
    doc += """
1110m는 100~1100, 1610m는 100~1500 격자가 보인다. 이것만으로 S1F가 100m·200m·210m 중 어느 것인지 판정할 수 없다. 기존 코드의 210m를 확정 정의로 가져오지 않고, 같은 정확한 거리 내 원문 S1F 평균까지만 예시로 보존한다. 거리 간 초반 속도 환산은 보류한다. 1300m의 S1F/2C 순서 문제도 남는다. C1/C2는 희소·거리별 미사용이 많아 초기 보편 입력으로 두지 않는다.

## 주행심사

API 명시 제주 심사 15,736행·4,616두, 2002-06-12~2026-09-16. 과거 문서의 15,738행과 차이는 사용자 제외 말 삭제 2행에 해당하며 재편입하지 않는다. `rcDist` 키를 가진 원문은 **0행**이다. 전체시간·구간시간은 초, `wgBudam`·`wgHr`는 kg 단위로 다루되 아래는 양수 가용성만 센 것이다.

"""
    doc += table(["심사 API 필드","양수행","미사용률","양수 최초~최종"],
                 [[r["api_field"],r["positive_rows"],f"{100*r['unusable_or_missing_rate']:.3f}%",f"{r['first_date']}~{r['last_date']}"] for r in trials["fields"]])
    doc += """
현재 예시에는 심사의 관측수·최근 일자·최근 원문 전체시간만 별도로 표시한다. 경주시간과 통합하거나 신마의 동일거리 능력값으로 대체하지 않는다. 기존 TXT 상대심사 연구의 800m 범위를 API 전체에 소급하지 않는다.

## 초기 범위와 근거 파일

조교·출발심사·진료도 DB에 보존되어 있지만 이번 최소 기준선에는 넣지 않았다. 추가 연구 시 각각의 `jeju/AGENTS.md` 입력 계약부터 따른다. 심판기록과 기수 성향은 사용자 지시에 따라 초기 제외다.

이 문서의 수치 근거는 같은 폴더의 `field_inventory.json`, `condition_inventory.json`, `distance_inventory.json`, `api6_distance_grids.json`, `trial_inventory.json`이다. 전체 원천·페이지 해시는 `source_audit.json`, 알려진 보류 적용은 `verification.json`에 연결되어 있다. 사건 날짜·원천 수집시각·최초 공개시각·검토 적용시각을 서로 같은 것으로 취급하지 않는다.
"""
    write("SOURCE_CONTRACT.md",doc)
    cards = read("example_scorecards.json")
    ex = """# 실제 말별 평가표 예시 6두

대상일 2026-09-19, 이력 절단일 **2026-09-17 포함**. 1·2·6경주에서 관측 과거 출전수가 가장 적은 말과 많은 말을 각각 선택했고 동률은 말 ID로 정했다. 대상 경주의 착순·시간을 선택이나 평가 계산에 사용하지 않았다. 거리·등급·중량 등 이번 조건은 사후 결과 원장에서 재구성했으며 T−2 공개 검증 전이다.

모든 시간은 **주로 보정하지 않은 동일거리 원기록**이다. 서로 다른 거리의 시간을 직접 비교하지 않는다. 최신 마명과 2026 고정 표시 나이를 썼다. 관측 경주 출전수는 평생 경력이나 신마 판정이 아니다. NULL은 능력 0이 아니다. 확률·추천 조합은 아직 산출하지 않았다.

"""
    def val(c,k):
        return c["metrics"][k]["value"]
    ex += table(["말 / ID","표시 나이","목표 거리","관측 출전 / 동일거리 유효수","직전 동일거리 s","최근 ≤5 평균 s (n)","편차 s","365일 최고 s"],
                [[f"{c['display_horse_name_current']} / {c['horse_id']}",c["display_age_2026_current_profile"],c["target_distance_m"],
                  f"{val(c,'observed_start_count')} / {val(c,'same_distance_valid_time_count')}",number(val(c,"same_distance_last_time_s")),
                  f"{number(val(c,'same_distance_recent5_mean_s'))} ({c['metrics']['same_distance_recent5_mean_s']['n']})",number(val(c,"same_distance_recent5_std_s")),number(val(c,"same_distance_best365_s"))] for c in cards])
    interpretations = {
        "3107406":"관측 경주 이력은 없지만 심사 2행이 있다. 경주 이력 0을 미출전 확정이나 능력 부족으로 바꾸지 않는다. 심사 거리 미확정이므로 심사 67.8초를 900m 경주 기록에 섞지 않는다.",
        "3107451":"최근 평균과 최고가 구분된다. 365일 최고와 두 번째 기록 차는 1.1초다. 이 차이만으로 최고가 이상치 또는 반복 가능한 능력이라고 판정하지 않는다.",
        "3107838":"관측 출전 4회가 있어도 이번 1000m 유효 기록은 없다. 다른 거리 기록을 평균속도로 환산해 빈 능력값을 채우지 않았다. 전체 무이력마와 별도 결측 사유다.",
        "3103957":"최근 동일거리 평균 83.42초와 최고 82.3초를 따로 보존했다. 최고 당시 주로 포화 17%이므로 시간 단축을 순수 능력 향상으로 해석할 수 없다.",
        "3103294":"전체 관측 출전 20회지만 1610m는 2회다. 편차와 최고 기록에 대한 근거가 얇고, 마지막 관측 출전 이후 119일이라는 최근성도 함께 봐야 한다.",
        "3014773":"관측 출전이 123회여도 1610m 유효 기록은 5회다. 동일거리 최근 평균 134.6초와 최고 132.3초의 차이가 크다. 위치 변화는 전개 이력일 뿐 이번에도 앞선 또는 후방이라고 고정하지 않는다.",
    }
    ex += "\n## 각 말의 근거와 해석\n"
    for c in cards:
        ex += f"\n### {c['display_horse_name_current']} ({c['horse_id']})\n\n{interpretations[c['horse_id']]}\n\n"
        names = ["days_since_last_observed_start","same_distance_latest_minus_prior3_mean_s","same_distance_second_best_gap365_s",
                 "last_historical_body_weight_kg","last_minus_previous_body_weight_kg","last_historical_carried_weight_kg","last_observed_event_age",
                 "s1f_recent5_mean_s","g3f_recent5_mean_s","g1f_recent5_mean_s","early_rank_fraction_recent5","early_to_g1f_order_gain_recent5"]
        ex += table(["평가 열","값","n","단위"],[[k,number(val(c,k),4 if "fraction" in k else 2),c["metrics"][k]["n"],c["metrics"][k]["unit"]] for k in names])
        b = c["best_record_context"]
        if b:
            ex += f"\n365일 최고 원천: API record {b['api_record_id']}, {b['race_date']}, {b['race_distance_m']}m, {b['rank_class_raw']}, 부담중량 {b['carried_weight_kg']}kg, 체중 {b['body_weight_kg_parsed']}kg, 주로 `{b['track_raw']}`.\n"
        else:
            ex += "\n365일 최고: 관측 없음(NULL).\n"
        t = c["trial_observation_only"]
        ex += f"\n주행심사: 관측 {t['observed_rows']}행, 최근 {t['latest_date']}, 원문 전체시간 {number(t['latest_time_seconds'])}초. 거리 비교 불가 상태로 별도 보존.\n"
    ex += "\n전체 원천 ID·payload SHA·계산식은 `example_scorecards.json`과 `SCORECARD_SPEC.md`에 있다. 이 값들은 평가표의 계산 검토용이며 말 간 최종 순위나 입상확률이 아니다.\n"
    write("EXAMPLE_SCORECARDS.md",ex)
    print("Source contract and six example scorecards rendered",flush=True)


if __name__ == "__main__":
    main()

# E9-A: 심판보고서 주행 방해 관측 — 제한된 정보 연구

## 결론

서울 2025-01-01~2026-02-28의 보유 심판보고서 **1,200건**을 먼저 봉인하고, race_id 정렬 모집단에서 seed `20260913`으로 무작위 **30건**, 사전 고정 문구 후보에서 중복 없는 **30건**을 선정해 원문 60건만 상세 검토했다. 읽기 전용 DB SQL에 양쪽 날짜 상한을 직접 넣었고, 113개 원문 source document의 hash를 봉인 시 확인했다. 결과·다음 경주 성적·배당은 표본 선정이나 추출에 사용하지 않았고, 외부 API 요청·tree fit·성능 계산·운영 연결은 **0회**다.

최종 `e9a_steward_rules_v3`는 원문 span이 있는 evidence **371행**을 남겼다. 이 중 역할·식별이 명확한 비모래 사건 행은 **197행**, 상호 접촉의 가해/피해 역할이 명시되지 않아 ambiguous인 행은 **167행**, 원문 추가사항·말 식별 충돌 등을 이유로 abstain한 행은 **7행**이다. 60건 중 **57건**에서 명확한 E9-A 사건을 추출했고, 서로 다른 경주·말 source key는 **171개**다. 이는 *문서에 추가 관측이 존재하고 일부를 귀속할 수 있다*는 결과일 뿐, 예측력·원인 효과·전체 사건 빈도나 안전한 사전 가용성의 증거가 아니다. 문구 과대표집 30건을 포함하며, 무작위 30건도 이 작은 표본에서는 모두 적어도 한 명시 사건 검토 앵커를 가진 양성 문서였으므로 음성 사례에 대한 성능도 측정하지 못했다.

## 기존 연구와 구분

H1 manifest SHA256 `f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`, dataset SHA256 `9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`, 실제 선택 **136열** 이름/순서 hash `b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`를 확인했다. 전체 136개 목록과 H1이 선언한 source hash는 새 `population_manifest.json`에 그대로 기록했다. `sand_response.py`의 `_reported_events`와 모래 이상반응·회복 추출은 기존 기능이며, 다만 `sand_*` 열은 H1의 **선택된 136열에는 0개**다. 이번 사건을 기존 sand 관측이 전혀 없었던 것처럼 서술하지 않는다.

동일 60건에 기존 sand cue 함수를 적용하면 명시적 이상반응 말은 **2개 source key**, 회복 cue는 0개였다. E9-A의 명확한 사건 말 171개 중 이 sand 이상반응 말과 겹치는 것은 **1개**, 겹치지 않는 것은 170개다. 이 비교는 사건 유형의 정보 존재 진단이다. E8-B 과거 API26_2 재조회에서 식별키는 같아도 누적 필드가 77행·239셀 바뀐 사실을 고려했으며, 그 필드를 새 feature에 넣지 않았다. E6-B와 E7-B의 개발 비교에서 독립 미래 우월성이 확인되지 않은 상태도 유지한다.

## 표본·사건 계약과 감사 결과

표본의 모집단 SHA256은 `4f0fec19246fa6914d100c31975b972a403d8bf3f205bc007e74a1d0e1dd0f30`이다. 문구 후보는 `진로`, `방해`, `접촉`, `막혀`, `제어`, `출발이 늦`, `출발이 느`, `늦게 출발`, `발주불량`으로 사전에 고정했다. 무작위 30건을 제외한 후보는 1,054건이었고 그중 30건을 동일 RNG 상태에서 추가 추출했다. 이 후보 수나 60건 결과를 전체 사건 발생률로 환산하지 않는다.

추출기는 원문의 **출발 지연**, **접촉·밀림·진로 방해**, **공간 부족에 따른 진로 막힘**만 다룬다. 각 행에 race/report/source ID, 원문 SHA256, `judgement`/`addJudgement` 필드, 원문 문자 오프셋·문장 span, `(meet, rcDate, rcNo, chulNo, hrNo)` 식별키, 유형·역할(`affected`/`victim`/`actor`/`unknown`), 원문 위치 표현, 규칙 버전, clear/ambiguous/abstain과 이유를 보존했다. **371개 span 전부**가 해당 원문 필드의 오프셋 부분문자열과 일치하는지 검사했다. 거리·시간 손실, severity, 승률 보너스, 의학 상태는 만들지 않았다.

역할별 명확 행은 출발 지연 affected 76, 진로/밀림 피해 42·행위 28, 막힘 피해 33, 접촉 피해 9·행위 9다. 여러 말의 상호 접촉 **167행**은 사건 자체가 명시돼도 가해/피해를 임의로 정하지 않았다. 표본군별로 무작위 30건은 clear report 28·모호/abstain만 있는 report 2, 문구 과대표집 30건은 clear 29·모호/abstain만 1이다. 누락 source/report 원문은 표본에서 0건이나, 코드에서는 별도 결측 상태로 다룬다.

같은 에이전트가 원문을 읽어 **60건 각각에 하나의 명시 사건 앵커**를 적은 `reviewer_labels_v1.json`은 독립 전문가 gold가 아니며 사건 전체의 완전 라벨도 아니다. `report_review.jsonl`에는 이 검토 라벨과 추출 결과를 별도 열로 두었다. 앵커 불일치 2건은 `review_disagreements.json`에 공개했다: race_id **2151**의 `밀려` 변형을 규칙이 놓쳤고, **3712**의 `⑧“파워풀비전”`은 보유 출전 번호·이름과 충돌하여 출발 지연을 식별마에 강제 귀속하지 않았다. clear report가 아닌 나머지 3건(1752, 1957, 2686)은 상호 접촉만 명시되어 역할을 unknown으로 유지했다. 다른 경주에 관한 `<추가심판사항>`은 현재 경주 사건으로 소급 귀속하지 않았다.

첫 추출 출력은 다음 말의 문구까지 넘어가 앞 말에 피해 역할을 잘못 붙이는 문제를 드러냈다. 그 v1과 수정 중간 v2 산출물은 보존하고, 다음 말 표기에서 문맥을 끊고 부정·조건·추정 반례를 보강한 **v3만 최종 정보 진단**으로 사용한다. 같은 60건을 보며 규칙을 고쳤으므로 이 표본을 독립 test 또는 추출 정확도 추정치라 부르지 않는다.

## 시점과 후속 비교 초안 — 실행하지 않음

보고서 원문의 요청/수신 및 DB 관측 시각은 각 사건에 따로 있고, 원천 publication/effective 시각은 **null**이다. 수집 시각은 과거 경주 뒤이므로 전부 `retrospective_only / availability_unverified`다. 사건 경주일은 향후 target 경주일보다 **엄격히 이전**이어야 하고, 해당 보고서가 target 예측 시각 이전에 공개됐다는 별도 증거가 없으면 feature 값은 null이다. 다음 날부터 알려졌다고 가정하지 않는다. E1의 결과·미출주 상태 계약과 F_t 미검증도 유지한다.

추출 가능성이 있으므로 검증 전 비교 초안은 `BASE_136`에 아래 **한 묶음, 최대 3열**만 추가하는 것이다. 숫자·정의는 성적을 보고 고르지 않았다.

1. `steward_last_start_delay_affected`: 직전 *실제 출발*의 보고서에서 그 말의 명시적 출발 지연 affected가 있으면 1. 보고서·출전 식별·전체 문장 판독과 사전 공개가 검증됐고 해당 사건이 없을 때만 0, 그 외 null.
2. `steward_recent3_interference_victim_count`: target보다 이전인 최근 실제 출발 최대 3회에서 명확한 victim 역할의 진로/밀림 사건 수. actor·상호 접촉 unknown은 세지 않으며, 대상 출발의 원문/역할/공개가 하나라도 불명확하면 null. 세 출발 미만인 말은 실제 보유 출발만 대상으로 하되 이력 완전성이 입증돼야 한다.
3. `steward_recent3_report_coverage`: 같은 출발 최대 3회의 원문이 해당 target 시각 전에 공개·연결·판독 가능했음이 확인된 개수(0~3). 이력/공개 시각 자체가 확인되지 않으면 null. 사건 부재와 자료 부재를 분리하기 위한 후보이며 자동으로 0을 채우지 않는다.

실제 학습·성능 비교를 하게 된다면 기존 E6/E7의 F1~F3 `fit → tune → calibration → evaluation` 시간 분할과 BASE_136을 재사용하는 **초안**일 뿐이다. 2026-03월 이후 평가나 새 모델 실행은 이번에 없었다. 후보의 PIT 공개 근거와 독립 추출 검증 없이는 이 묶음을 학습 입력으로 만들지 않는다.

## 재현·보존·독립 검증

- 봉인 표본/원문 source manifest·동일 에이전트 라벨: `data/experiments/confirmed_starter_e9a_20260913/`. 최종 `event_evidence.jsonl`, `report_review.jsonl`, `review_disagreements.json`, `information_summary.json`, 실행 코드·출력·기존 보존 hash manifest: `data/experiments/confirmed_starter_e9a_20260913_v3/`.
- 코드/테스트: `src/horse_racing/analysis/confirmed_starter_e9a.py`, `scripts/seal_confirmed_starter_e9a.py`, `scripts/inspect_confirmed_starter_e9a.py`, `scripts/run_confirmed_starter_e9a.py`, `tests/test_confirmed_starter_e9a.py`. 기존 H1 dataset, E8-B 감사·대조 원문, 운영 원장, DB 등 **6개 보존 경로의 실행 전후 SHA256이 일치**했고 DB 자체도 `38f8ce36660cffd449007cfba37bde15ef80ce2f2029761a9047950162af55b5`로 불변이다. 출력 5개 파일의 hash는 `artifact_manifest.json`에서 확인한다.
- 관련 Ruff `check`/`format --check` 통과. 전체 `pytest -q` **632 passed, 2 warnings**(기존 Starlette deprecation, Polars PIT sortedness). 합성 회귀는 피해/행위, 다중 말, 상호 접촉, 부정·조건·인용·추정, 이름/번호 충돌, 외부 결과 없이 추출, 입력 순서 불변 및 원문 span 경계를 다룬다.

검증 담당자는 모집단·표본 seed 및 source hash, 60건 앵커의 원문 위치, 다중 말 귀속과 3712 충돌, 2151 누락, 167개 역할 unknown, 기존 sand 추출과의 중복, 사후 수집 원문의 PIT 불가를 우선 확인해 달라. 이번 산출물은 독립 검증에 제출하며 운영 승격이나 다음 학습 단계는 진행하지 않는다.

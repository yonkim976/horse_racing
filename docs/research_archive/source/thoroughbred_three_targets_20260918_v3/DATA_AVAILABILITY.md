# 더러브렛 3-목표 연구용 데이터 가용성 감사

감사 기준일은 2026-09-18이며, 통합 DuckDB와 원천 문서를 읽기 전용으로 조회했다. 이 문서는 무엇을 다음 실험에 넣을 수 있는지 판정하는 자료 감사이며, 모델 학습이나 운영 변경은 수행하지 않았다.

## 핵심 판단

서울·부경의 2006년 이후 확정 경주를 공통 시간 분할로 쓸 수 있다. 기본 목표 모집단은 36,748경주·410,168출전행이며, 서울 21,686경주·244,283행, 부경 15,056경주·165,831행, 영천 6경주·54행이다. 영천은 독립 학습 또는 일반화 성능 주장에 사용할 수 없다.

기본 실시간 모의실험에는 경주 조건, 거리, `chul_no`(출전번호만 있는 draw proxy), 부담중량, 공식 사람·말 ID 및 **현재 경주일보다 엄격히 앞선** 성적 이력만 사용한다. 현재 경주의 결과·시간·배당·착차는 제외한다.

| 사용자 가설 | 원천/연결 | 범위와 품질 | 가용성 판정 | 다음 시험 우선순위 |
| --- | --- | --- | --- | --- |
| gate × 거리 × 기간, 부경 안/밖 | `entry_result.chul_no`, `race.distance_m`, 날짜 | 목표 행에서 출전번호·부담중량은 전부 존재 | `chul_no`는 draw proxy다. 안/밖 레일·실제 게이트 위치·field-size 보정은 별도 필드가 없다 | P0. 경주 내 출전번호 분위/상대 위치를 field size와 함께 만들고, 부경×거리×연도 상호작용을 시간 외 평가 |
| 날씨·주로 보정 | `race.weather_raw`, `track_raw`, `track_moisture_percent` | 2006년 이후 확정 경주에서 거의 완전; 부경 track 1건, moisture 24건 결측 | 현재 경주 자료의 과거 공개시각이 `availability_unverified` | P3. 기본 모델 밖의 `availability_unverified` retrospective 실험만 |
| 서울 모래 보충/정비 | 없음 | 경주 `surface_regime`은 2016년 전후 체계 표시뿐 | 원천 부재라 정비의 직접 효과를 식별할 수 없다 | `surface_regime`은 시간 체계 proxy로만 층화한다. 직접 시험에는 날짜·시간·트랙 구간이 있는 공식 정비 로그가 필요하다 |
| 말별 모래 반응·회복 | 운영 SQLite의 `race_steward_reports` + 경주 roster·말명 | 서울 2025-01-04~2026-09-13 1,780건, 부경 2025-01-03~2026-09-11 1,244건. 운영 경주 자연키에는 100% 연결됐으나 통합 DuckDB에는 아직 연결되지 않았다 | 이는 **모래 보충 자료가 아니라** 심판 원문의 말별 모래 이상반응 후보이다. 원문은 race-level이고 말 ID가 없어 이름/문장 추출 및 서울·부경 표본 검증이 미완이다. 과거 공개시각도 미검증 | 다음 고정 실험 뒤 P4. strict-prior, 동결 roster 연결, 추출 정밀도 표본감사, coverage·unknown 분리를 전제로 한 별도 retrospective 후보 |
| 부담중량·체중·말별 최적체중 | `burden_weight_kg`, `horse_weight_kg`, `horse_weight_delta_kg`, `weight_event` | 부담중량은 목표 행 전부 존재. 체중은 서울 242,475/244,283, 부경 164,558/165,831행 | 부담중량은 카드 필드로 후보. 현재 경주 체중·증감과 `weight_event` 전체는 공개시각 미검증 | P0 부담중량 및 엄격한 과거 부담중량 이력. P3 체중/증감은 별도 retrospective 프로필 |
| 휴양·조교 | `days_since_last_race`, `training_event` | 휴양일은 strict prior 이력. 조교 7,749,406건, 서울 1998~, 부경 2004~ | 조교는 전부 `availability_unverified`; source absence를 0으로 해석할 수 없음 | P0 휴양일/과거 출전 이력. P3 조교량은 출처 coverage 보정과 함께 별도 실험 |
| 주행심사 대 정식경주 | `trial_entry`와 `hr_no` | 76,413행; 서울 2003~, 부경 2004~. 신원 확정 행은 많지만 일부 모호·미연결 | 거의 전부 `retrospective_only`; 2026 일부 API는 availability_unverified | P2. 확정 `hr_no`와 `trial_date < race_date`만 사용한 retrospective 이력; 기본 라이브 모델 제외 |
| 선행·페이스·막판 킥·거리 적성 | `section` | 서울은 `cumulative`·`verified_source_field`, 2006+ 1,327,985행, canonical closing 480,392개. 부경 2,495,550행은 전부 `source_specific_unverified`. 영천 278행/6경주 | 현재 경주 구간은 사후값이다. 다만 v2와 같은 **과거 공식 결과의 역사 가용성 가정** 아래, 서울의 과거 section/closing은 `event_date < race_date`로만 집계해 core 후보로 쓸 수 있다. 이 가정은 미래 라이브 배포 전 공개시각으로 검증해야 한다. 부경과 같은 값으로 합치면 안 됨 | P1. 서울 전용 엄격 과거 closing/section form을 가용성 가정과 함께 평가. 부경은 의미 검증 전 제외 |
| 기수·날씨 상호작용 | `jockey_no`, 날씨·주로 | 기수 ID는 목표 행 전부 존재 | 기수 ID는 후보, 날씨는 unverified | P0 기수의 train-only 범주/과거 집계. P3 기수×날씨는 retrospective-only |
| 사고·불리·trouble | 운영 SQLite의 `race_steward_reports`에는 2025~2026 원문이 있음 | 서울 1,780·부경 1,244 report/race key가 운영 `races`에 모두 자연키 연결. 통합 DuckDB에는 심판 원문·말 사건 테이블이 없음 | 자료 자체가 없는 것이 아니라 통합 연결·말별 추출·서울/부경 검증이 미완이다. 제주 전용 보수 추출기는 출발지연·진로제한·방해를 다루지만 더러브렛 이식 검증은 없다 | 이 고정 실험에는 추가하지 않는다. 후속 strict-prior 후보는 report-known/unknown을 분리하고, 말명 roster 매칭·부정문/진술 구분·표본 검수를 먼저 통과해야 한다 |
| speed·잠재력·엘리트 휴양 | 결과시간·순위, strict prior history | 공식 과거 결과는 충분. 기존 `style.py`는 S1F-착순 기반 `late_gain`, `energy.py`/`canonical_energy.py`는 S1F·G3F·G1F의 상대시간을 계산한다 | 과거 결과만 strict-date 집계 가능. 현재 v3 core는 서울·영천의 검증된 S1F position만 쓴다; 시간 기반 late-kick은 개최지·section 의미와 역사 가용성을 별도 검증해야 한다 | P0 과거 성적/휴양. P1 서울 section 보조 지표. ‘잠재력/엘리트’는 사전 등록된 과거 기반 정의가 있어야 함 |

## 시간·개최지 경계

- 서울 경주: 2000-01-08~2026-09-13; 모델 목표는 2006-01-07부터.
- 부경 경주: 2005-01-07~2026-09-11; 모델 목표는 2006-01-06부터.
- 영천: 2026-09-13 하루 6경주. 통합 모델의 unseen venue 추론·사례 보고까지만 가능하다.
- 같은 경주일의 정식 결과는 다음 경주 피처에 쓰지 않는다. 모든 새 집계는 `event_date < race_date` 또는 `history_race_date < race_date`여야 한다.
- 부경 구간은 `source_specific_unverified`다. 서울·영천의 누적시간 또는 closing 지표와 결합하지 않는다.

## 가용성·연결 위험

모든 조교 사건은 `availability_unverified`다. 공식 API 진료도 부경 2019-04-07~, 서울 2025-01-01~만 있고 공개 시각은 미검증이다. Text 진료와 주행심사 대부분은 `retrospective_only`다. Text 진료의 확정 ID 연결은 서울 368,626/1,349,468행, 부경 205,148/628,141행이므로 미확정·모호 이름 연결을 재시도해서는 안 된다.

운영 SQLite `data/horse_racing.sqlite3`는 API215 `JudgeReport`를 `meet_code + race_date_local + race_number` 자연키로 보관한다. 2026-09-18 읽기 전용 조회에서 서울 1,780건(18,855 출전행), 부경 1,244건(13,729 출전행)은 모두 운영 `races`에 연결됐다. 그러나 `observed_at_ms`는 2026-08-25~2026-09-17의 수집 시각일 뿐 각 과거 경주일의 공개 시각 증거가 아니며, 통합 DuckDB와 v3 `prepared_context.parquet`에는 이 원문이 없다. `sand_response.py`는 명시적 모래 반응·회복 parser와 same-date 후 상태 갱신을 구현하고 단위 테스트가 있지만, 서울·부경 전수 추출 정확도·말명 연결률·결측의 unknown 처리·다음 출전 예측 검증은 아직 없다. 원문 대량 출력이나 이 고정 run의 피처 추가는 하지 않는다.

마체중·장구·주로·날씨는 데이터값의 존재와 예측 시점의 공개 가능성을 구분해야 한다. 해당 변수를 쓴 결과는 `availability_unverified` 또는 `retrospective_only`라고 표기하고, 기본 결과표와 섞지 않는다.

## 실행 가능한 순서

1. **P0:** `protocol.json`의 연도별 순서를 고정한다. 각 평가연도 직전 연도 6월 30일까지 FIT, 7~9월 TUNE, 10~12월 CAL, 해당 역년 EVAL이다. 후보 선택에는 2021~2024만 쓰고, 2025~2026은 이미 노출된 참고 평가 구간이므로 새 독립 holdout으로 표현하거나 재선정에 쓰지 않는다. 이 분할로 거리×출전번호 proxy×개최지/시기 상호작용, 부담중량, 휴양과 엄격 과거 성적을 시험한다. 출전번호 효과는 field size 및 거리별로 계층화한다.
2. **P1:** 서울에서만 과거 section/closing form을 `event_date < race_date`로 집계해 v2의 역사 가용성 가정 아래 core ablation을 한다. 현재 경주 구간은 쓰지 않고, 부경을 포함시키지 않는다.
3. **P2:** 신원이 확정된 과거 주행심사를 `trial_date < race_date`로 연결한 retrospective ablation을 한다.
4. **P3:** 날씨·주로·체중·조교·의료는 가용 시각의 독립 증거가 생기기 전까지 별도 프로필로만 평가한다.
5. **P4 (다음 고정 run 이후):** 운영 심판 원문을 서울·부경 범위에서 frozen natural-key/roster linkage로 통합하고, 모래 반응·출발지연·진로제한·방해의 추출 정밀도와 report coverage/unknown을 먼저 감사한다. 이 단계는 모래 보충 효과와 분리한다.
6. 모래 보충은 여전히 현재 원천에 직접 사건 로그가 없으므로, 직접 효과 모델링 전 공식 정비 로그·키·발행시각을 수집·감사한다.

세부 행/연도 coverage는 `*_by_year.csv`, `section_by_venue.csv`, `medical_by_source.csv`, `trial_by_venue_year.csv`, `weight_by_venue_year.csv`, `operational_steward_report_coverage.csv`와 `availability_audit.json`에 기록했다.

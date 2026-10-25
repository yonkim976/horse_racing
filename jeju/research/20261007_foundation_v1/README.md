# 제주마 모델 기초 연구 v1

2026-10-07. 이번 연구의 첫 목표는 **말별 3위 이내 입상확률**이다. 과거 이력으로 만든 말별 평가표를 이번 편성과 결합하고, 이후 조합 평가로 확장한다. 우승확률은 별도 목표다. 기존 문서의 더 넓은 목표나 HY_R_FORM의 A/B/C 지표를 이번 목표와 동일시하지 않는다.

이번에는 원천 감사, 계산 가능한 평가표, 실제 6마리 예시와 실험 절차를 만들었다. 모델 학습은 실행하지 않았다. 제주 DB는 읽기 전용으로 열었고 전후 SHA-256·크기·수정시각이 일치했다. 운영 모델·등록부·더러브렛 코드는 수정하지 않았다.

## 확인한 사실

| 항목 | 현재 확인값 | 해석 |
|---|---:|---|
| 제주 후보 원장 | 92,513행 / 9,494경주 | 2002-07-06~2026-09-19. 품종의 과거 유효시점까지 확정한 학습 모집단은 아님 |
| 2017년 이후 후보 | 59,042행 / 5,901경주 | 실제 첫 경주일 2017-01-13 |
| 정상 숫자 착순·양수 전체시간 | 57,850행 / 5,828경주 | 이 행만 남겨 완전한 편성이라고 해석하지 않음 |
| 임시 경주 단위 라벨 점검 통과 | 5,365경주 | 모든 후보 정상 완주·양수 시간, 1·2·3위 각각 한 마리. 출전표 완전성·동착 심사는 별도 |
| API 주행심사 | 15,736행 / 4,616두 | 2002-06-12~2026-09-16. 원문에 명시적 거리 필드 없음 |
| 알려진 구간 보류 | 순위 70필드 / 통과조 20경주지점 | 품질 뷰에서 NULL. 통과조가 말별로 반복된 관측은 194개 |

2017년 이후 거리에는 400·800·900·1000·1110·1200·1300·1400·1610m가 있다. 거리별 시대와 표본량이 다르므로 고정된 더러브렛 거리군을 이식하지 않는다. 400m의 G3F 미제공을 능력 부족으로 처리하지 않는다.

현재 새 분석의 원천은 `jeju_race_postrace_sections_quality_2026`이다. 알려진 홈페이지 시간 정정 3개·순위 정정 14개를 사용하고, 광해청명 G1F 미확정 시간과 내부 충돌 필드는 NULL을 유지한다. 양수 원값 상태인 `api_positive_unreviewed`는 홈페이지 검증 완료를 뜻하지 않는다. 기존 [구간 품질 보고서](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261003_unresolved_section_review/README.md)와 [2017년 학습 품질 검토](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261002_section_remaining_review/TRAINING_FROM_2017.md)를 따른다.

## 기존 자산과 채택 여부

| 자산 | 확인한 상태 | 이번 연구에서의 용도 |
|---|---|---|
| `jeju/models/current/HY_R_FORM.pkl` | 현 운영 기준. SHA-256 `f1b9531e068cab51dff906961d56f51c7c4b0e5a86f378c9aa1f03f159ec9706` | 기존 성능 비교와 구현 참고. 변경·자동 승격 없음 |
| `data/research/jeju_native_top3_dataset_v1_20260915_r2/` | 이전 상태·파생 입력 산출물 | 원천 계약을 새 품질 뷰와 대조한 뒤 참고. 새 평가표와 혼용하지 않음 |
| `data/research/jeju_native_transition_holdout_v13_20260916/` | 전개 추가 후보가 사전 개선 기준을 통과하지 못함 | 실패한 가설과 시간 분할 참고 |
| `src/horse_racing/analysis/jeju_native_top3_states.py` | 과거 동일거리·시대 중앙값 대비 잔차. 메타데이터는 일별 주로 보정 미사용을 명시 | 주로 보정 완료 자산으로 취급하지 않음 |
| `data/research/jeju_accuracy_candidates_20260919/decision.json` | PACE·NO_GROWTH 미승격 | 확정 입력으로 가져오지 않음 |
| `data/research/jeju_observed_elo_20260922/decision.json` | A/B 미승격, 운영 변경 없음 | 상대 능력 단계의 후속 가설 |
| `data/research/jeju_trial_relative_20260922/decision.json` | A/B 미승격, 운영 변경 없음 | TXT 기반 심사 상대기록 실험. 경주 전체시간 보정의 검증 근거가 아님 |
| `data/research/jeju_trial_gate_20260928/decision.json` | 연구 통과 기준 실패, BASE 유지 | 심사·게이트 후속 연구의 반례 |
| `production_models/20261004/jeju/` | 운영 산출물 보존본 | 새 연구 기준선이나 새 데이터 파이프라인으로 사용하지 않음 |
| `jeju/snapshots/`, `jeju/features/` | 시작 점검 당시 실질 산출물 없음 | 이번 폴더에 원천·계산·예시를 먼저 보존 |

공통 경로의 자산은 읽기 전용으로 참고했다. 더러브렛에서 가져오는 것은 과거 시점 평가표, 묶음별 비교, 시간순 검증이라는 개발 방식이며 계수·구간 경계·각질 기준·입력 개수는 가져오지 않는다.

## 아직 모르는 부분

1. **제주 거리별 S1F와 코너의 정확한 계측 경계.** 공식 제주 안내는 최초 200m로 설명하지만 기존 코드의 1110·1610m 210m 해석과 원천 API6 거리격자가 바로 일치하지 않는다. API6는 경주 단위 자료이므로 말별 S1F와 같은 것으로 치환할 수 없다. 1300m의 S1F보다 작은 2C 시간도 오류로 단정하지 않는다. [공식 제주 안내](https://race.kra.co.kr/down/pdf/raceView_jeju.pdf), [일반 구간 설명](https://race.kra.co.kr/raceScore/cornerRecordDesc.do). **2026-10-18 후속 확인:** [공식 제주 성적표 용어해설 원문](../20261018_s1f_measurement_official_review/README.md)이 1110m·1610m의 S1F는 210m 지점임을 직접 명시했다. 위 S1F 거리 미확정은 해소됐으며 코너 경계·API6와의 대응은 별도 사항으로 남는다.
2. **실제 T−2 공개 가능성.** 현재 DB는 사후 수집·검토 자료다. 사건 날짜가 T−2 이내라는 사실만으로 그 당시 공개되었다고 입증되지 않는다. 현재 예시는 사건 날짜 기준의 회고 계산이다.
3. **출전번호와 실제 물리 게이트의 관계.** `chulNo`는 공식 안내의 출발번호다. 취소·제외 뒤 실제 배치까지 확인하지 않았으므로 물리 게이트로 부르지 않는다. [공식 제주 안내](https://race.kra.co.kr/down/pdf/raceView_jeju.pdf).
4. **API 주행심사의 거리.** TXT 심사에 800m 자료가 있어도 API20 전체 행에 일괄 부여하지 않는다. 사건별 연결과 시대별 규칙 확인이 필요하다. [공식 API20](https://www.data.go.kr/data/15056974/openapi.do).
5. **완전한 역사적 출전집합·품종·특수 결과 계약.** 현재 프로필을 과거 품종의 확정 근거로만 사용하지 않는다. 2017년 이후 DB 내부 후보 누락 점검이 0이어도 당시 출전표 완전성의 독립 검증은 아니다.

## 연구할 가설

- 동일거리 원기록의 최근 수준·최고 기록·안정성은 서로 다른 정보를 준다. 작은 기준선에서 분리해 비교한다.
- 함수율과 시대를 고려한 제주 전용 보정이 원기록보다 다음 경주의 입상 예측에 도움이 될 수 있다. 보정 오차 감소와 예측 개선은 각각 검증한다.
- 초반 위치의 효과는 거리·편성에 따라 달라질 수 있다. 현재의 위치 이력에서 이번 예상 각질로 바로 단정하지 않는다.
- 저경력마에는 심사가 유용할 수 있다. 거리·공개시점·표본 편향을 먼저 해결하고 별도 묶음으로 추가한다.

현재 예시에서 글라가게의 최근 동일거리 평균은 83.42초, 365일 최고는 82.3초다. 최고 기록 당시 주로는 포화 17%였다. 이 차이를 그대로 능력 향상이라고 설명하지 않는 것이 보정 연구의 출발점이다. 제주소리는 관측 경주 이력 0개지만 심사 관측은 2개다. 붉은노을은 경주 이력이 4개 있어도 목표 1000m 기록은 없다. 두 경우의 결측 원인을 구분한다.

## 산출물과 다음 순서

- [원천 정의·단위·기간·결측률](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_foundation_v1/SOURCE_CONTRACT.md)
- [말별 평가표 계산식](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_foundation_v1/SCORECARD_SPEC.md)
- [실제 6마리 평가표와 해석](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_foundation_v1/EXAMPLE_SCORECARDS.md)
- [최소 입력 후보·단계별 실험·검증 절차](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_foundation_v1/EXPERIMENT_PROTOCOL.md)
- [원천 해시와 집계](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_foundation_v1/source_audit.json), [계산·시점 검증](/Users/kimyongjin/Desktop/horse_racing/jeju/research/20261007_foundation_v1/verification.json)

다음 작업은 거리별 계측 정의, T−2 출전조건의 가용성, 경주 단위 라벨 계약을 확정하는 것이다. 그 뒤 원기록 최소 기준선을 학습하고, 주로 보정 및 정보 묶음을 같은 조건에서 비교한다. 기수·기수 성향·심판기록은 초기 입력에서 제외한다.

재현은 프로젝트 루트에서 `python3 jeju/research/20261007_foundation_v1/build_foundation.py --output-dir run_새이름`으로 실행한다. 출력은 이 연구 폴더의 새 하위 폴더에만 생성되며 기존 결과를 덮어쓰지 않는다. 생성 JSON에는 각 평가값의 관측수·계산식·원천 ID와 과거 행의 payload SHA가 있다. DB 해시가 달라지면 이 보고서와 같은 스냅샷의 재현으로 부르지 않는다.

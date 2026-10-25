# Bottom3 사전 설계·코드 검토

**판정: 사전 검토 통과 (`passed: true`).** 이 표시는 설계·원천·동결 코드가 계약에 맞는다는 리뷰 결과이며, 실행 승인이나 후보 채택을 뜻하지 않는다. 실자료 학습과 Bottom3 예측·성과 계산은 하지 않았다. 실행은 supervisor의 최종 hash-bound 승인 뒤에만 가능하다.

검토 대상 최종 해시는 계약 `ff6e3af2d454cd30edb56df1251700320b01de3478939c98199e0886bf22f084`, 구현계획 `2a613ba594dac2ef4d9622357a04b96b8b634bee0f70bbb2098791f4be6948fb`, 엔진 `92a4b41a6493cf88cf8d17e592f98ed75f0fb9fd446f28564774a35a6d608df0`, 테스트 `ce4f1d19c8322b635ae76aeabdd9ce1d8fcf3abba7b36bcdad5d3b9bdfe3846e`, 코드 묶음 `c55e4cf66c346cea92b23bc13bdbb82f4993ae169055157f99056ca286f4bd2b`, 구조 사전검사 `cb116d123e99e82780b10a94a5052e4457098409ce52fb332c648b8fedab7cdd`이다. 원천 감사는 `a69bc897e896427e38e2e61ce3470c909cea10c2a3dbfa7bab5c19b9b50c6137`, 세션 시작 기록은 `c7cd21d7300e0d3b4b070c51a10ca058bbb3214b73df6cc959b2cbff15c64bbe`로 확인했다.

사건 계약은 정상 완주 전원 명단에서 순위가 정확히 `1..N`일 때 `finish_position >= N-2`를 Bottom3로 표시한다. 모든 경주가 `N>=3`, 정확히 3개 양성인 것을 사전검사에서 확인했다. 고정 코호트는 52,155두·5,206경주·15,618개 양성이고, 평가 코호트는 17,412두·1,779경주·269일·5,337개 양성(2024/2025/2026: 637/654/488경주)이다. 미완주·동착·취소·불완전 편성을 마지막 순위로 재분류하지 않는다.

확률 엔진은 각 경주에서 크기 3인 모든 순서 없는 조합 `C(N,3)`에 `softmax(sum(u)/T)`를 적용한다. 주변 Bottom3 확률은 포함 조합의 합이며 합계가 3이다. Top3 확률의 보수나 부분 순위 분포로 대체하지 않는다. L은 저장된 S 점수의 부호를 바꾼 `-score_S` 기준선이고 Bottom3로 학습된 모델로 표현하지 않는다. B는 같은 S 40개 입력·범주 어휘·시간 분할·하이퍼파라미터를 사용하는 고정된 단일 Bottom3 이진 목적 모델이다. 연간 provider Y의 Y−1 자료만 온도 보정에 쓰고, 2017..Y−3 초기 학습, Y−2 조기 종료 및 재학습, Y 평가 경계를 유지한다. 1/N runner weight는 경주당 합계 1이다. 계약상 6회 LightGBM 호출과 6회 온도 적합 이외의 탐색은 없다.

정적 검토에서 원시 rank·field size·horse number를 정수 변환 전에 검증하고, 정확한 OOS 키·provider/실제 연도·calibration/evaluation 역할을 맞추며, train-only 범주 어휘와 동결 입력 해시를 확인했다. 실행은 approval 및 단회 exclusive claim을 요구하고, 출력은 study의 `experiment/` 아래 exclusive-create 방식으로 제한한다. 신뢰도 구간은 경주별 고정 bin 충분통계로 누적하므로 전체 subset 확률 벡터를 장기간 보관하지 않는다. 모델 경로, 코호트 명칭, PyArrow 버전, 정확 index와 실제 말번호 정렬도 동결본에서 점검했다.

초기 승인 게이트 검토에서 저장된 사전검사 JSON의 연도별 category-vocabulary 키가 문자열인데 fresh 구조 객체는 정수여서, timestamp만 제외한 직접 비교가 실패할 수 있는 serialization blocker를 확인했다. 최종 엔진은 preflight 생성 시 연도 키를 문자열로 정규화한다. 저장된 receipt와 독립 재생성한 fresh preflight를 동일 helper로 timestamp만 제외해 비교했고, 전체 객체가 같음을 확인했다. 양쪽 모두 연도 키 `2024`, `2025`, `2026`을 가지며 엔진 해시도 일치한다. 수정 전 receipt는 `experiment/preflight_revisions/source_preflight_pre_string_vocab_fix.json`에 보존되어 있다. 이 재검사는 구조만 다시 읽었으며 학습·확률·성과 계산을 하지 않았다.

최종 동결 코드의 synthetic 테스트 9개, 엔진 synthetic 검사 7개, source preflight가 PASS로 보고되었다. preflight는 학습·온도 최적화·Bottom3 확률·실성과 계산·DB 접근이 없다고 기록한다. supervisor의 별도 수학 합성 검산도 4개 편성에서 정규화·주변확률·불변성·선택 동률을 통과했고 실자료 성과를 계산하지 않았다.

평가 결과는 아직 없다. 회고 정상완주 코호트와 과거에 재사용한 2024–2026 구간에 대한 연구이며, 독립 미래 검증이나 공개 시점에 실제 구매 가능한 정보 집합을 증명하지 않는다. Bottom3 성능을 7승식 확률, 승식 적중 개선, 시장 우위 또는 실전 제외 안전성으로 일반화할 수 없다. 두 고정 게이트도 각각 확률 연구 후보와 제외 보조 후보를 구분하며, 두 번째 gate는 통계적 비열등성 주장이 아니다.

따라서 이 검토의 범위에서 실행을 막을 설계·정적 코드 결함은 찾지 못했다. supervisor는 위 해시가 자신의 승인 manifest와 일치하는지 확인한 후 별도로 단회 실행 여부를 결정할 수 있다.

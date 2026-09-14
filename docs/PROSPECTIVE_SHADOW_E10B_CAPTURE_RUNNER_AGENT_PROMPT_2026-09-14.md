# E10-B: 한 번짜리 전향 capture 실행부 준비 — offline 구현만

당신은 /Users/kimyongjin/Desktop/horse_racing의 구현 담당자다. 이번 목적은 공식 게시 근거가 확보됐을 때 실제 사전 원문 수집을 한 번 실행할 수 있도록 남은 실행부 결함을 해결하는 것이다. 모델 연구나 검증 체계 재설계가 아니다. 실제 HTTP·브라우징·자동화·수집·학습·추론·확률 발행·2026-06-01 이후 실제 결과 조회는 실행하지 않는다. 모든 시험은 합성 원문과 가짜 transport로 수행한다.

읽을 문서:
- docs/PROSPECTIVE_SHADOW_E10A_READINESS_2026-09-14.md
- docs/PROSPECTIVE_SHADOW_E10A_INDEPENDENT_REVIEW_2026-09-14.md
- data/logs/prospective_shadow_e10a_readiness_20260914.json
- src/horse_racing/analysis/confirmed_starter_e8b.py
- scripts/run_confirmed_starter_e8b.py

## 구현 범위

기존 BudgetTransport/PilotCapture/CaptureStore/parser/page 검사를 재사용하는 새 연구 전용 runner와 필요한 작은 helper만 작성한다. 과거 E8 코드·산출물, H1/E3–E9, registry, 다른 dirty 파일은 보존한다. 새 CAS·feature 저장기·수집 프레임워크를 만들지 않는다. 기존 runner를 그대로 subprocess로 실행하는 방식은 금지한다.

1. 누적 예산: 봉인된 세 원장의 2+3+2=7회와 총 12회 계약을 확인하고 최대 5회만 허용한다. ack는 별도 전송이 아니다. 원장 누락·해시 불일치·손상·설명 안 되는 추가 사용은 전송 전에 거부한다. 현재 읽을 수 있는 원장과 기록 밖 사용의 한계를 구분하고, 과거 기록 부재를 새 코드로 증명했다고 주장하지 않는다. CLI 숫자만 바꿔 상한을 늘릴 수 없어야 한다.

2. 재실행·중단·동시 실행에도 동일 5회가 새로 생기지 않게 한다. 작은 고정 campaign 상태/배타 잠금 또는 원자적 단일 사용 예약으로 구현한다. 출력 root 변경이 새 예산을 만들면 안 된다. 이 제한된 1회 파일럿에서는 잔여 allowance 전체를 사전에 한 번 예약하고, 실패·중단 시 자동 반환하지 않는 보수적 설계도 허용한다. 예약 5회와 확인된 실제 전송 횟수는 별도 기록한다. 네트워크 이전에 상태를 영속화하며, 미확정 중단을 0회 전송으로 단정하거나 자동 복구해 재사용하지 않는다. 실제 campaign 예약은 이번 offline 시험에서 생성/소비하지 않고 임시 합성 campaign만 사용한다.

3. 실행 전 봉인 protocol에 공식 게시 근거의 로컬 파일·hash·확인 시각·서울 대상일, 허용 endpoint, 원장 hash, allowance, 실행 소스 hash를 바인딩한다. 공식 게시 여부에 대한 사람/검증 담당자의 판단을 파일 존재만으로 자동 인증했다고 주장하지 않는다. 근거 부재, 대상일 불일치 또는 hash 오류는 HTTP 0회로 종료한다. 실제 실행 지시가 아직 없으며 이번 제출 상태는 이를 분명히 유지한다.

4. 일정 1 batch → 출전표 1 batch 순서다. 각 batch의 필요한 페이지와 제한된 실패 retry는 동일 allowance 안에서 센다. 출전표 두 번째 batch 자동 재조회는 제거한다. redirect는 따라가지 않는다. 실제 inner transport 호출(연결 실패 포함)을 센다. 예산 초과 차단 자체를 실제 전송으로 세지 않는다. 빈 응답 때문에 날짜를 바꾸거나 반복 조회하지 않는다. 불완전·예외 때도 가능한 원문/요청 원장/사용량/종료 사유를 보존한다.

5. 두 원천이 비어 있지 않고 날짜 전체 page/key 검사를 통과했을 때만 공통 경주 중 조건을 충족하는 가장 낮은 race number를 사례로 선택한다. source 예정시각에서 T−30을 계산하고 max(schedule 완료 ack, entry 완료 ack)와 비교한다. 둘 중 하나가 늦거나 예정시각을 읽을 수 없으면 해당 사례를 승인하지 않는다. 로컬 시계 역행 거부를 유지한다. 실제 시각을 과거로 지정하는 실험용 clock을 운영 명령에서 노출하지 않는다. 더 이른 capture를 정확한 T−30 최신 상태라고 표현하지 않는다.

6. `capture_only_completed`와 전향 사례 성공을 구분한다. raw 수집에 성공하더라도 F_t_eligibility=unverified, operating_model_status=not_activated를 유지한다. 실제 원문을 E8-A 합성 feature 계약으로 통과시키지 않는다. 136개 feature 재감사나 모델 연결은 범위 밖이다.

## 필요한 검증과 종료 조건

가짜 transport와 임시 디렉터리로 실제 새 runner 흐름을 시험한다. 7회 기사용→추가 최대5회, 여섯 번째 호출 차단, 재실행/새 root/동시 실행의 중복 예약 차단, 중단 후 allowance 재생성 금지, 손상·누락·변조 원장 거부, 게시 근거 부재/대상일 불일치 시 HTTP0회, retry/페이지/연결 실패 집계, 자동 두 번째 출전표 batch 없음, 정상 사례 및 한 원천 ack가 늦은 사례를 포함한다. 테스트 자체가 실제 외부 transport를 만들거나 호출하지 못하게 차단한다. 소스 시간이 없는 경우 추정하지 않는다.

관련 pytest/Ruff/format/diff를 실행한다. 공유 코드 변경 없이 새 실행부만 추가했다면 의미 있는 관련 회귀로 충분하며, 전체 pytest 숫자를 늘리는 것이 목표가 아니다. 범위 밖 기존 오류는 수정하지 않는다.

새 경로에 제출:
- 실행부 및 필요한 helper·회귀 테스트
- docs/PROSPECTIVE_SHADOW_E10B_CAPTURE_RUNNER_2026-09-14.md
- 합성 실행 증거, 보존/신규 hash manifest
- 향후 실제 실행에 필요한 정확한 명령과 남은 조건

보고서는 코드 준비 여부, 실제 전송 0회, 공식 게시 근거 미확인 상태, 실제 F_t 미검증을 구분한다. 완료 후 실제 수집을 시작하지 말고 독립 검증에 제출한다. 준비가 끝나면 같은 범위의 설계 문서를 추가로 반복하지 않고, 게시 근거와 명시적 수집 지시가 확보되는 시점에 실제 capture 단계로 넘어간다.

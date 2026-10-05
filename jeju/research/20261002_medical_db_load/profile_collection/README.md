# 제주 API16 진료 미연결 말 API42 프로필 수집 — 2026-10-02

## 결과

- API16 clinic 원문 12,030행·32페이지를 읽기 전용으로 확인하고 최신 프로필 공식 horse_id와 대조했다. 미연결 대상 81두·156행이다.
- 분석 상한 2026-09-19 안에 있는 76두·150행을 먼저 조회했고, 상한 이후 원문 5두·6행도 이어서 조회했다.
- 81두 모두 API42 현재 프로필 응답이 HTTP 200, resultCode=00, totalCount=1, 응답 행 1개, 요청 hrNo 정확 일치로 검증됐다. 전부 현재 breed=제주마이며 마명·출생 필드가 사용 가능하고, 각 원문 item의 218개 필드와 JSON 타입을 보존했다.
- API42 원문 응답 81개와 API16 원문 페이지·행 위치 156건이 독립 SHA·말 ID·진료일 대조를 통과했다. 상세 결과는 verification_summary.json에 있다.
- 첫 시도에서 같은 말 1건이 네트워크 ConnectError를 반환해 격리했고, 승인된 재시도는 성공했다. 나머지 80건은 첫 시도에서 성공했다. 최종 상태는 81두 전부 validated이며 정상 공백·비제주 응답·미해결 실패는 없다.
- 작은곰(3005648)은 진료 원문에 행이 없고 대상에서도 제외돼 있다. 재수집 허용 상태는 만들지 않았다.

## 요청량과 보안

- 기존 2026-10-02 KST API42 호출 21건, 이번 stage 시도 82건(검증 응답 81 + 초기 네트워크 오류 1), 확인 가능한 합계 103/일일 3,000건이다. 기준 checkpoint는 2026-10-01 확인본이며 공개 페이지는 실시간 잔여량을 표시하지 않는다. API21 호출은 API42와 별도 서비스 한도로 집계했다.
- stage 내 모든 API42 요청 시작 간격은 최소 1.05초였다.
- API42 키는 기존 get_settings()에서 메모리로만 읽었다. 저장 산출물에서 키와 인증 쿼리 URL 검사는 0건이다. HTTP/전송 오류는 응답 본문이나 인증 URL 없이 오류 유형만 기록했다.
- SQLite는 읽기 전용으로 열었고 DB 적재·수정은 하지 않았다.

## 해석 한계

breed=제주마는 각 API42 응답 시점의 현재 프로필 관측이다. 과거 진료일의 품종을 확정하지 않는다. meet=제주도 제주 경주장 자료라는 뜻이며 과거 품종 근거가 아니다. API42 말명·출생 필드 역시 조회시점 원문 그대로 보존했다.

## 산출물

- target_manifest.json: 81두 선택 근거와 API16 원문 행 위치
- collection_manifest.json: 결과, quota 기준, 성공·실패·보류 수 요약
- validated_profile_rows.jsonl: 검증된 API42 원문 item 및 응답·수집시각·요청·API16 출처 추적
- raw/api42_profiles/: API42 응답 원문; response_file은 이 stage 디렉터리 기준 상대 경로
- request_ledger.jsonl, quarantine_ledger.jsonl, run_manifest_*.json: 요청 및 격리 원장
- verification_summary.json: 응답 해시·타입·ID·행 위치·요청 간격·비밀값 보존 재검증 결과
- collect_profiles.py, verify_collection.py: 수집·검증 코드

예정 repo 배치 시 raw/api42_profiles/... 응답 경로의 논리 접두사는 jeju/research/20261002_medical_db_load/profile_collection/이다.

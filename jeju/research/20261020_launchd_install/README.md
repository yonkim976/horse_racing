# 제주 연구 DB 매일 22시 launchd 설치·실행 검증

2026-10-20 사용자 승인으로 현재 사용자 GUI launchd에 설치하고, **설치된 동일 서비스를 실제 실행해 성공을 확인했다.** 기존 Codex 예약 `db`는 앞선 단계에서 삭제했으며 새 Codex 예약은 만들지 않았다.

## 설치 상태

| 항목 | 설정 |
|---|---|
| label | `com.horse-racing.jeju-research-refresh` |
| 일정 | 매일 22:00, Mac 시스템 시간대 Asia/Seoul |
| 설치 파일 | `/Users/kimyongjin/Library/LaunchAgents/com.horse-racing.jeju-research-refresh.plist` |
| 실행 | 프로젝트 `.venv/bin/python -u -m jeju.refresh.launchd_runner` |
| 실제 갱신 명령 | `.venv/bin/python -u -m jeju.refresh.run --apply` |
| 대상 DB | `jeju/data/jeju_native_core.sqlite3` |
| 로그 | `~/Library/Logs/horse-racing/jeju-research-refresh.out.log` 및 `.err.log` |
| 구조화 상태 | `jeju/research/20261017_core_refresh/launchd_execution_status.json` |

현재 사용자가 로그인한 Mac에서 실행한다. 정시 실행에는 Mac이 깨어 있고 인터넷에 연결되어 있어야 한다. Codex 앱을 켜둘 필요는 없다. 설치 시 한국 시간대를 확인하며, 이후 Mac 시간대를 바꾸면 일정도 시스템 시간을 따른다. `RunAtLoad=false`, `KeepAlive=false`이므로 로그인 즉시 실행하거나 실패 직후 반복 재시도하지 않는다.

기존 갱신기의 최근 14일 재조회·일요일 최근 60일 대조 정책을 사용한다. 한국시간 21시 이후에는 당일까지, 그 전에는 전날까지 조회한다. 고정 날짜를 설치 인자에 넣지 않았다. API를 우선 수집하며 출발조교 홈페이지는 기존 공식 폼 POST 수집을 유지한다.

## 실제 실행 결과

- 실행 ID: `20261020T160014_afd748c7`
- 실행 시각: 2026-10-20 16:00:14~16:02:27 KST
- launchd 종료 코드: **0**, 실행 상태: **success**
- 조회 구간: **2026-10-06~2026-10-19**. 21시 이전 수동 검증 실행이므로 전날까지다. 오늘 22시 예약 실행은 10월 20일까지 조회하는 정책을 따른다.
- 공식 API **142페이지**, 홈페이지 **14페이지**의 원문 SHA와 API 페이지 완결성·건수를 확인했다. 수집 실패는 0건이다.
- 신규 적재: **일별조교 314행, 진료 23행, 마필 프로필 관측 12행**. 프로필 관측 추가는 신규 말 12두라는 뜻이 아니다.
- 경주결과·심사·구간 등 기존 자료의 재관측은 원문을 확인하고 유지했다. 최신 경주일은 10월 17일이며 날짜만으로 완전 수집을 선언하지 않는다.

출발조교 홈페이지 4일(10/7·8·14·15)은 이전 HTML과 SHA가 달라 보류 원장에 남았다. 추가 대조 결과 **파싱된 조교행 전체와 동일 내용의 반복 횟수는 이전 원문과 모두 일치**했다. 홈페이지 문서 SHA 변화이며 조교 필드 충돌은 확인되지 않았다. 기존값과 보류 근거는 보존했다. [4일 비교 근거](website_hold_comparison.json)를 따른다.

## 검증 및 보존

실제 갱신 직전 롤링 백업과 적용 후 DB를 별도 검증기로 대조했다.

- 기존 **42개 테이블·2,827,050행의 모든 기존 열**과 스키마 객체가 보존됐다.
- SQLite `integrity_check=ok`, 외래키 위반 0건, 재적재 검증 통과.
- 제외 말 `3005648`은 활성 6개 테이블에서 0행을 유지한다.
- 기존 시간 정정 3건·광해청명 NULL·순위 정정 14건·충돌 보류 90행·조교 기승자 분류를 보존했다.
- 10월 17일 5R 홈페이지 거리 정정 6칸(110~1110m)도 그대로 유지했다.
- 최신 DB SHA·refresh manifest·이 실행의 application manifest·runner의 `last_success`가 일치한다.
- 기존 다른 LaunchAgent 파일 15개는 설치 전후 해시가 같았다. 공유 운영 DB·더러브렛·모델·예측 발행은 변경하지 않았다.

설치 검토 중 기존 `check()`가 제외 말 검사 첫 테이블 뒤에서 성공 반환하던 부분을 수정해 6개 테이블 모두 검사하도록 했다. 테이블별 차단 검사 6건과 runner가 중복 실행·receipt 누락 시 과거 성공 상태를 보존하는 검사 3건, 합계 **9건 통과**했다. 원래 소스는 [수정 전 사본](refresh_run_before.py)에 보관했다.

옛 고정 기준 DB 소실은 이번 설치로 복원한 것이 아니다. 이번 검증은 실제 갱신 직전 생성된 정상 롤링 백업을 기준으로 수행했다. 과거 원본과 후속 백업의 시점을 혼동하지 않는다.

## 관리 명령

프로젝트 루트 `/Users/kimyongjin/Desktop/horse_racing`에서 실행한다.

```sh
.venv/bin/python -m jeju.refresh.launchd status
.venv/bin/python -m jeju.refresh.launchd run
.venv/bin/python -m jeju.refresh.launchd stop
.venv/bin/python -m jeju.refresh.launchd install
```

`run`은 같은 설치 서비스를 요청하며 실행 중인 작업을 강제 종료하지 않는다. 갱신기는 기존 공용 잠금으로 중복 적용을 막는다. 동일 설정 재설치는 실행 중 작업을 유지하고, 설정이 다르면 실행 중 재설치를 거부한다. `stop`은 서비스 등록을 해제한다.

각 실행의 실패·부분 수집은 종료 코드와 상태 파일에 기록한다. 이 스크립트는 채팅·Discord·메일 알림을 보내지 않는다. 로그 두 파일은 기존 운영 로그 회전 allowlist에 포함되지 않아 현재 자동 회전 대상은 아니다. 상세 구현은 [관리 모듈 안내](../../refresh/LAUNCHD.md)를 따른다.

## 근거 원장

- [설치·실제 실행 완료 영수증](completion_receipt.json)
- [설치 검증](install_verification.json)
- [실행 후 launchctl 상태](launchctl_after_run.txt)
- [실제 적재 manifest](../20261017_core_refresh/runs/20261020T160014_afd748c7/application_manifest.json)
- [42개 테이블 독립 검증](../20261017_core_refresh/runs/20261020T160014_afd748c7/independent_application_verification.json)

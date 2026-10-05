# 경마 데이터 자동 수집 통합 운영 안내

확인 기준은 2026년 10월 5일 오후 KST다. 현재 운영 중인 로컬 수집 3개, Google Cloud 수집 2개, 로컬 로그 정리 1개를 이 문서에서 함께 확인한다. 자동 수집은 Supabase 운영 DB를 갱신하며, 모델 재예측·웹 배포·로컬 SQLite 동기화는 수행하지 않는다.

프로젝트 위치는 `/Users/kimyongjin/Desktop/horse_racing`, Google 프로젝트는 `mapilog-509017`, 확인 리전은 `asia-northeast1`, Supabase 프로젝트는 `xkykmhhkjtosptoibduo`다. 다른 Google 프로젝트·리전의 모든 예약을 조사했다는 의미는 아니다. 기존 상세 보고서는 변경 근거와 과거 검증 기록으로 보존한다.

## 활성 예약 전체 목록

| 작업 | 실행 위치와 예약 이름 | 한국 시간 주기 | 수집하거나 정리하는 대상 | 현재 확인 |
|---|---|---|---|---|
| 주간 출마표 | Google Scheduler와 Run Job `mapilog-weekly-entry-cards` | 수요일 17:10·18:10·19:10 | API154 경주계획, API26_2 출전표, API78 출발번호·장구 증감 | Scheduler ENABLED |
| 매일 조교 | Google Scheduler와 Run Job `mapilog-daily-training` | 매일 14:30 | 실행일 포함 최근 7일의 일반·출발·수영·언덕조교 | Scheduler ENABLED, 오늘 실행 성공 |
| 당일 변경과 결과 | Mac `com.horse-racing.live-race-day` | 약 2분 간격 | API25 체중, API10 기수·부담중량 변경, API9 출전취소, API155 결과, API156 상세 결과 | 등록됨, 복구 후 반복 정상 종료 |
| 확정배당 | Mac `com.horse-racing.closing-dividends` | 약 15분 간격 | API301, 오늘 완료 경주의 7승식 제공 조합 | 등록됨, 실제 적재 검증 완료 |
| 결과 정정과 배당 보완 | Mac `com.horse-racing.post-race-repair` | 매일 09:00·20:30 | 실행일 포함 최근 7일의 API155·156 결과 및 API301 배당 | 등록됨, 실행 검증 완료 |
| 수집기 로그 정리 | Mac `com.horse-racing.log-rotation` | 매일 03:00 | 현재 로컬 로그 6개를 압축 보관 후 비우고, 7일 초과 압축본 삭제 | 등록됨, 1회 실제 검증 완료 |

Cloud Scheduler는 예약 호출만 담당하고 실제 수집은 Cloud Run Job이 수행한다. 호출이 성공했다고 수집·DB 저장까지 성공한 것은 아니므로 Job 최종 상태와 DB 실행 이력을 함께 확인한다. Mac 예약도 등록됨과 실제 성공은 구분한다. 실행 사이에는 프로세스가 `not running`으로 보여도 종료 코드 0이면 정상 대기일 수 있다.

## 각 수집기의 범위와 시간 제한

주간 출마표는 실행일이 속한 수요일부터 다음 화요일까지의 아직 지나지 않은 공개 일정을 탐색한다. 연휴의 월·화요일도 포함하며 이미 시작된 경주나 경주 당일 변경을 초기 출마표로 덮어쓰지 않는다. 늦게 공개된 출마표는 같은 수요일의 후속 예약에서 재확인한다.

매일 조교는 실행일 포함 최근 7일을 다시 조회해 지연 공개와 정정을 흡수한다. 제주 출발조교의 하루 여러 회는 `occurrence_no`별로 보존하며 같은 조회를 반복했다고 업무 행이 계속 증가하지 않도록 같은 저장 슬롯을 갱신한다. 슬롯 번호는 공식 훈련 시각이나 이벤트 ID가 아니다. 빈 응답으로 기존 기록을 지우지 않는다.

당일 수집은 다음 경주 하나가 아니라 오늘 DB에 출마표가 있는 경마장 전체를 날짜 단위로 확인한다. 정상 조회 창은 첫 경주 예정 1시간 전부터 마지막 경주 예정 2시간 후까지며, 08:00 이상 22:00 미만 제한도 적용한다. 예정 시각이 누락되면 09:00 이상 21:00 미만을 사용한다. 한 경마장이 모두 완료되면 해당 경마장 원천 재확인은 10분 간격으로 줄이고 다른 경마장은 계속 확인한다. 창 밖의 2분 예약은 수집을 건너뛴다.

확정배당은 같은 경주 시간 창과 09:00 이상 22:00 미만 제한을 적용한다. 완료 여부와 결과 범위를 검증한 경주만 적재한다. 경주 전 변동 배당이 아니며 미공개·0값으로 정상 배당을 덮어쓰지 않는다.

결과 보완은 기존 출마표에 연결된 출전행의 결과·정정을 보완한다. DB에 출마표 자체가 없는 경주를 자동 생성하는 작업은 아니다. 아직 시작 전인 오늘 경마장은 건너뛰고, 아직 상세 결과가 공개되지 않은 출전행은 대기로 남긴다. 7일을 넘어 뒤늦게 수정된 과거 자료는 별도 수동 검증이 필요하다.

당일·배당·결과 보완은 로컬 파일 잠금과 관련 PostgreSQL 잠금을 공유한다. 겹치면 기다리며 동시에 쓰는 대신 건너뛴다. 보완 작업이 한 번 건너뛰면 다음 예약이나 수동 실행으로 재확인해야 한다. 클라우드 조교 등 다른 모든 작업을 막는 전역 잠금은 아니다.

## 디스코드 알림

기존 사용자 웹훅을 유지한다. 주소·토큰·DB 비밀번호·API 키는 이 문서에 기록하지 않는다. 클라우드는 Secret Manager, 노트북은 기존 비밀 설정을 사용한다.

| 작업 | 보내는 시점 | 조용히 건너뛰는 경우 |
|---|---|---|
| 주간 출마표 | 완료·변경 없음·수집 실패 요약 | 프로그램 시작 전 장애는 알림을 보장하지 못함 |
| 매일 조교 | 종류별 신규·변경·유지·최신일과 실패 요약 | 프로그램 시작 전 장애는 알림을 보장하지 못함 |
| 당일 수집 | 체중·기수·취소·결과 변경, 새 완료 경주, 오류·복구 | 변경 없는 예약 실행. 같은 오류는 30분 간격 제한 |
| 확정배당 | 신규·수정 또는 오류 | 변경 없음이나 발표 대기만 있는 예약 실행 |
| 결과 보완 | 변경이 없어도 완료·대기·오류 집계 | 잠금으로 작업 자체를 건너뛴 경우 |
| 로그 정리 | Discord 없음 | 결과는 `rotation-status.json`과 launchd 상태로 확인 |

당일 알림은 전체 변경 건수와 말별 최대 8건 일부 상세를 표시한다. 취소 사유·기수 변경 전후의 모든 상세를 전송하는 것은 아니며, 주로·날씨·레이팅만의 변경도 별도 알림 대상이 아니다. Discord 실패는 성공한 DB 갱신을 되돌리지 않고, 도착 여부가 모호한 요청은 자동 재전송하지 않는다. Mac 종료, 실행 권한 차단, 컨테이너 기동 실패와 timeout 등 시작 전후 모든 장애를 독립적으로 감시하는 경보는 아직 없다.

## 로그와 원문 및 검증 기록 위치

| 기록 | 위치 | 이번 자동 삭제 대상 |
|---|---|---|
| 현재 로컬 수집 로그 | `/Users/kimyongjin/Library/Logs/horse-racing/` | 파일 삭제가 아니라 압축 후 내용만 비움 |
| 최근 압축 로그 | 위 폴더의 `archives/` | 이번 정리기가 만든 이름 규칙의 일반 파일 중 7일 초과분만 삭제 |
| 로그 정리 최신 결과 | 위 폴더의 `rotation-status.json` | 삭제하지 않음, 최신 결과로 교체 |
| 기존 프로젝트 로그 | 프로젝트 `data/logs/` | 제외, 과거 기록 보존 |
| 로컬 수집 상태 | `data/state/local-race-day.json`, `local-post-race.json` | 제외 |
| 검증과 변경 전후 기록 | `data/state/post-race-audit-*.json`, `post-race-change-*` 등 | 제외 |
| 로컬 공식 API 원문 | 설정된 로컬 원문 폴더, 기본 `data/raw/kra/` 계열 | 제외 |
| 클라우드 실행 로그 | Google Cloud Logging의 해당 Run Job 실행 | 제외, 이번 로컬 정리로 줄어들지 않음 |
| 클라우드 원문 | `gs://mapilog-509017-kra-raw`, 컨테이너 `/raw` 마운트 | 제외 |
| DB 수집 실행 원장 | Supabase `ingestion_runs`, 출처는 `source_documents` | 제외 |

로그 정리는 정확히 다음 6개만 대상으로 한다.

```text
local-live-race-day.log
local-live-race-day.err.log
local-closing-dividends.log
local-closing-dividends.err.log
local-post-race-repair.log
local-post-race-repair.err.log
```

압축 파일 이름에는 원래 로그 이름·UTC 보관 시각·고유값이 포함된다. 압축을 풀어 SHA-256이 원본과 같은지 확인한 다음 원본 파일의 내용만 비운다. 파일 자체와 inode는 유지하므로 기존 launchd 출력 연결을 끊지 않는다. 비어 있는 로그는 압축본을 만들지 않는다. 정상 완료 후 같은 한국 날짜에는 다시 비우지 않는다. 압축본은 성공한 정리 시각 기준 168시간을 초과하면 삭제하며, 매일 작업이 실행될 때 삭제되므로 정확히 168시간째 즉시 없어지는 것은 아니다.

수집기 공유 잠금을 얻지 못하면 건너뛰고, 압축 중 원본 변경을 감지하면 원본을 유지하며 `partial`로 기록한다. 압축 실패·검증 실패에도 원본을 비우지 않는다. 심볼릭 링크·다중 하드링크·특수 파일은 거부한다. 로그 디렉터리와 압축 폴더는 0700, 압축본과 결과 파일은 0600이다.

이 방식은 copytruncate다. 같은 잠금을 쓰지 않는 임의 프로세스가 마지막 변경 검사와 내용 비우기 사이에 쓰면 극히 짧은 경합 구간의 로그 유실 가능성은 남는다. 기존 worker도 잠금 밖에서 일부 계획·건너뜀 메시지를 쓰므로 무손실을 보장하지 않는다. 경주 시간이 아닌 새벽 03:00에 실행해 겹침을 줄이며, DB·원문·검증 기록은 별도로 보존한다. 실패나 건너뜀에 대한 무한 자동 재시도는 없으며 결과를 확인해 수동 실행하거나 다음 날 예약을 기다린다.

## 로컬 상태 확인과 수동 실행

아래 명령은 프로젝트 폴더에서 실행한다. 수집 명령은 `--apply`가 있어야 실제 DB 쓰기를 한다. 로그 정리는 `--apply`가 없으면 계획만 표시한다.

```sh
cd /Users/kimyongjin/Desktop/horse_racing
.venv/bin/python scripts/manage-local-race-day.py status
.venv/bin/python scripts/manage-local-post-race.py status
.venv/bin/python scripts/manage-local-log-rotation.py status

.venv/bin/python -m horse_racing.jobs.local_race_day --apply
.venv/bin/python -m horse_racing.jobs.local_post_race --mode dividends --apply
.venv/bin/python -m horse_racing.jobs.local_post_race --mode repair --apply
.venv/bin/python -m horse_racing.jobs.local_log_rotation
.venv/bin/python -m horse_racing.jobs.local_log_rotation --apply
```

세 관리 스크립트의 `install`은 해당 예약만 재등록하고, `stop`은 해당 예약만 중지한다. 특히 `manage-local-post-race.py`는 배당과 결과 보완 두 예약을 함께 관리한다. 로그 정리를 멈추고 싶다면 `manage-local-log-rotation.py stop`만 사용한다. 기존 `scripts/install-launchd.sh`는 과거 전체 동기화 예약 설치기이므로 현재 6개 작업 설치기로 사용하지 않는다.

Mac 예약은 로그인한 사용자 세션의 LaunchAgent다. 인터넷·로그인·잠자기 해제가 수집 조건이며, 꺼진 노트북에서 실행되지 않는다. 잠자기로 놓친 달력 예약은 깨어난 뒤 실행될 수 있지만 전원이 꺼져 놓친 예약의 실행을 보장하지 않는다. 로그 정리에는 네트워크가 필요 없으나 Python 실행과 프로젝트 접근 권한은 필요하다. 시스템 시간대가 `Asia/Seoul`에서 바뀌면 로컬 03:00·09:00·20:30의 한국 시간 의미도 달라진다. Google 예약은 `Asia/Seoul`을 명시했다.

## Google Cloud 상태 확인과 수동 실행

조회와 실행 모두 경마 프로젝트·리전을 명시한다. 기본 gcloud 프로젝트를 변경하거나 Fintor 작업을 건드리지 않는다.

```sh
gcloud scheduler jobs list --project=mapilog-509017 --location=asia-northeast1 --format='table(name.basename(),state,schedule,timeZone)'
gcloud run jobs executions list --job=mapilog-weekly-entry-cards --project=mapilog-509017 --region=asia-northeast1 --limit=5
gcloud run jobs executions list --job=mapilog-daily-training --project=mapilog-509017 --region=asia-northeast1 --limit=5

gcloud run jobs execute mapilog-weekly-entry-cards --project=mapilog-509017 --region=asia-northeast1 --async
gcloud run jobs execute mapilog-daily-training --project=mapilog-509017 --region=asia-northeast1 --async
```

마지막 두 `execute` 명령은 조회가 아니라 실제 수집을 시작하며 기존 리소스 실행 비용과 API 호출이 발생할 수 있다. 이번 문서 확인을 위해 클라우드 수집을 새로 실행하거나 예약·리소스를 변경하지 않았다. 기존 비용 안내는 [클라우드 적용 기록](WEEKLY_CARD_CLOUD_CRON_SETUP_2026-10-01.md)을 참고하며 그 당시 추정액을 현재 확정 청구액으로 해석하지 않는다. 로컬 로그 정리는 새 클라우드 리소스나 AI 호출을 만들지 않는다.

## 최근 실제 확인 결과

- 10월 5일 Cloud Scheduler 조회에서 두 예약은 모두 ENABLED이고 표의 시간대·주기와 일치했다. 다음 조교 호출은 10월 6일 14:30, 다음 주간 출마표 호출은 10월 7일 17:10 KST다.
- 오늘 조교 Run Job `mapilog-daily-training-bvkkh`는 14:30경 시작, 14:34:43 완료로 성공했다. Supabase 실행 `21187`도 `completed`, 오류 없음이며 조회 10,747행·처리 10,599행이었다. 처리 건수는 신규 추가 건수가 아니라 기존 행의 처리도 포함한다. 10월 3·4일 조교도 Job·DB 실행 성공을 확인했다.
- 주간 Job의 최신 실행 `mapilog-weekly-entry-cards-bmq9f`는 10월 2일의 연결 테스트 기록이며 신규 출마표 적재 성공으로 해석하지 않는다. 실제 출마표 67경주·700두와 원문 검증은 기존 10월 1일 적용 기록을 따른다.
- Mac 재시동 후 바탕화면 로그 접근 차단을 로그 위치 분리로 복구했다. 당일 실행 `21248`은 제주 5R 결과 10두, 배당 `21249`는 1,790행 신규 반영과 Discord 전송을 확인했다. 후속 2분 자동 실행 `21252`는 변경 없음·오류 없음으로 완료했다.
- 결과 보완 `21250`은 실제 오류 0건·종료 코드 0이지만 오늘 서울 54행·제주 15행 상세 결과 공개 대기가 있어 `partial`이었다. 이는 모든 당일 결과의 적재 완료라는 뜻이 아니다.
- 10월 5일 15:29:58 로그 정리 예약을 launchd 경유로 1회 검증했다. 내용 있는 로그 3개 38,455 bytes를 gzip 총 1,960 bytes로 보관하고 원본을 비웠으며, 나머지 오류 로그 3개는 비어 있어 보존했다. 오래된 압축본이 아직 없어서 실제 만료 삭제는 0건이다. 만료 삭제·재실행·쓰는 중인 파일 보존·잠금·링크 거부 등은 별도 테스트로 확인했다. 보관본으로 내용 복원이 가능하며 수집기 로그 파일은 삭제하지 않았다.
- 압축본 3개의 gzip 무결성을 재확인했고, 로그 정리 이후 당일 자동 실행 `21264`가 종료 코드 0·오류 없음으로 완료하며 같은 로그 파일에 새 내용을 기록하는 것도 확인했다. 수집기 출력 연결은 유지됐다.
- 로그 정리 10개와 기존 당일·사후 수집 51개를 합쳐 테스트 61개, Ruff와 plist 문법 검사가 통과했다. 실제 다음 새벽 03:00의 예약 시각 실행이나 복구 후 추가 재부팅까지 검증한 것은 아니다.

## 과거 예약과 아직 자동화하지 않은 항목

과거 `com.horse-racing.sync-morning`·`sync-evening` 전체 동기화 템플릿은 코드에 있지만 현재 사용자 세션에 등록된 서비스가 없고 설치 plist도 없었다. launchd enable 이력만 남은 것을 활성 작업으로 세지 않는다. 이번에 이 예약을 켜거나 삭제하지 않았다.

Codex의 `9월 19일 경주 데이터·제주 예측 10분 갱신` 예약은 설정상 PAUSED이며 9월 19일 종료 범위의 과거 작업이다. 현재 2분 수집기를 실행하는 주체는 Codex 채팅 자동화가 아니라 macOS launchd다. 이번에 Codex 예약 상태를 바꾸지 않았다.

아래 항목은 수동 수집·과거 적재와 별개로 이 통합 목록에서 활성 정기 자동화를 확인하지 못했다. 완료된 자동 수집으로 간주하지 않는다.

- 진료기록, 주행·출발심사 결과와 예정일, 관계자 기본정보·현역 상태·위탁 계약·승급·출전등록말 현황의 개별 정기 수집
- 심판리포트, 새 구간시간·통과착순·통과조 원천의 사후 정기 수집
- 경주 전 실시간 변동 배당과 속보 화면 전체
- 입력 변경 감지 후 해당 경주 모델 재예측과 새 예측 발행
- 로컬 SQLite 자동 동기화와 프론트 최신값·캐시 반영의 종단 간 검증
- 질병 설명 연결과 부상 영향 분류, 오래된 DB 자료의 스토리지 이전, 웹 서비스 배포 재개
- 시작 전 장애에 대한 독립 감시 경보와 클라우드 로그·원문·로컬 검증 기록의 별도 용량 보존 정책

## 상세 문서와 구현 위치

- [전체 갱신 공개 주기와 최초 계획](KRA_DATA_REFRESH_SCHEDULE_AND_CLOUD_JOBS_PLAN_2026-10-01.md)
- [주간 출마표와 매일 조교 클라우드 적용 기록](WEEKLY_CARD_CLOUD_CRON_SETUP_2026-10-01.md)
- [당일 수집과 디스코드 상세](LOCAL_RACE_DAY_COLLECTION_AND_DISCORD_HANDOFF_2026-10-02.md)
- [확정배당과 결과 보완 상세](LOCAL_POST_RACE_AUTOMATION_2026-10-03.md)
- [로그 정리 구현](../src/horse_racing/jobs/local_log_rotation.py), [설치와 상태 관리](../scripts/manage-local-log-rotation.py), [예약 설정](../scripts/launchd/com.horse-racing.log-rotation.plist)

후속 담당자는 예약 변경 시 이 통합 목록을 먼저 갱신하고, 실제 저장 검증과 상세 근거는 해당 작업 문서에 함께 남긴다. 문서의 확인 날짜 이후 외부 설정이 변경될 수 있으므로 운영 판단 전 상태 명령을 다시 실행한다.

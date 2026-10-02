# 주간 출마표 Google Cloud 크론 활성화·검증·비용 보고

작성: 2026-10-01 KST. **주간 Scheduler 활성화 완료. 수동 적재·원문 검증·예약 호출·중복 적재 방지 테스트 모두 성공했다.**

2026-10-02 추가 적용: 주간 출마표에 Discord 알림을 연결했고, 매일 14:30 KST 조교 갱신 예약도 활성화했다. 최신 설정과 검증은 문서 마지막의 추가 적용 기록을 참조한다. 아래 10월 1일 기록은 당시 배포 이력이다.

## 확인한 기존 리소스

- 경마 Google 프로젝트: `mapilog-509017`, 결제 연결 활성.
- 기존 웹 서비스/이미지 리전: 도쿄 `asia-northeast1`. 웹 서비스는 변경·재개하지 않는다.
- Artifact Registry: `mapilog` Docker 저장소를 수집 이미지에도 사용한다.
- 기존 Secret Manager: `horse-racing-database-url`, 활성 버전 1~3. 배포 시 확인한 버전에 고정해야 한다.
- 배포 전 확인 당시 경마 프로젝트의 Cloud Scheduler API는 비활성이었고 도쿄 Cloud Run Job 목록은 비어 있었다. 이번 작업에서 전용 API/Job/Scheduler를 활성화했다.
- 같은 결제 계정에 연결된 Fintor 프로젝트의 도쿄 Scheduler 2개를 확인했다. 다른 리전·프로젝트와 기존 무료 사용량 전체를 확인한 것은 아니므로 무료라고 확정하지 않는다.
- 로컬 Docker daemon은 실행 중이 아니므로 Cloud Build로 이미지를 빌드하는 계획이다.

## 새 작업의 동작

- 실행 진입점: `python -m horse_racing.jobs.weekly_entry_cards`
- 시간대: 명시적 `Asia/Seoul`.
- 조회 범위: 실행일이 속한 수요일~다음 화요일 중 아직 지나지 않은 날짜. 연휴 월·화요일까지 포함한다.
- 서울·제주·부산경남·영천을 모두 조회하고 API154에서 공개 경주계획을 탐색한다. 계획이 있는 날짜/지역에 API26_2와 API78을 추가 조회한다.
- 세 원천의 페이지 수, 날짜, 경주/말 키, 출발번호, 말 이름, 거리, 출전두수를 모두 검증한 뒤 적재한다.
- 기존 저장 일정이 공식 계획 조회에서 사라지거나 기존 말이 새 출마표에서 사라지면 자동 삭제·성공 처리하지 않고 실패한다.
- 미래 경주만 적재한다. 시작/완료 경주나 당일 경주를 주간 초기 출마표로 덮어쓰지 않는다.
- 저장 후 말별 부담중량·레이팅·관계자 ID·장구 원문·증감 분리행을 재검증한다.
- 기존 출전취소 상태를 보존한다. 취소 철회나 재출전 승인은 별도 작업이다.
- Session pooler의 세션 advisory lock으로 이 worker의 실행 중복을 막는다. 수동 CLI·다른 worker도 같은 잠금을 쓰도록 변경한 것은 아니다.
- 매 시도 공식 계획을 다시 조회한다. 같은 입력 해시로 이미 완료됐고 DB 값도 일치하면 적재를 건너뛴다. 늦게 공개된 다른 지역 경주나 변경된 출마표는 새로운 해시로 반영한다.
- 로그/DB: 성공한 주간 실행은 `ingestion_runs.data_type=weekly_entry_cards`, 원천별 child 실행과 원문도 보관한다. 수집 전에 실패하면 Cloud Run 로그에 실패가 기록되며 운영 적재 실행은 생성되지 않을 수 있다.
- 원천 API에 계획 자체가 아직 없고 운영 DB에도 일정이 없다면 미공개와 비경마일을 완전히 구분할 수 없다. 로그에는 `no_published_plan`으로 남기고 후속 예약에서 재조회한다. 연간 일정과 독립 대조하는 추가 검증은 아직 없다.
- API77·모델·예측 발행·진료·훈련·결과 등은 실행하지 않는다. 로컬 SQLite도 갱신하지 않는다.

## 적용한 예약과 리소스 설정

- Scheduler 1개, 수요일 **17:10 / 18:10 / 19:10 KST**. 최초 공개 확인과 지연 공개 재확인 용도다.
- 계획 cron: `10 17-19 * * 3`, 시간대 `Asia/Seoul`.
- Cloud Run Job 1개, task 1, parallelism 1, CPU 1, 메모리 512 MiB, task timeout 600초, task retries 0.
- Scheduler 호출 재시도 0으로 시작한다. 다음 시간대 시도가 별도 재확인이고, 호출 수락과 Job 최종 성공은 다르다.
- 수집 전용 계정과 Scheduler 호출 계정을 분리한다. 호출 계정에는 이 Job의 실행 권한만 부여한다.
- 기존 DB 접속 비밀값과 새 KRA API 키 비밀값을 런타임 주입한다. 키를 소스·빌드 인자·이미지·로그에 넣지 않는다.
- 새 비공개 GCS 원문 버킷을 도쿄에 만들고 `/raw`로 마운트한다. non-root UID/GID 10001에 맞춰 마운트한다. 기존 웹 Cloud Build 버킷을 원문 저장에 사용하지 않는다.
- `source_documents.local_path`는 컨테이너의 `/raw/...` 경로다. 클라우드 밖에서 원문을 확인할 때는 문서의 버킷과 동일 상대 경로의 GCS 객체를 읽어야 한다. 로컬에 같은 경로 파일이 생기는 것은 아니다.

## 비용: 확정 단가와 추정 총액을 구분

아래는 2026-10-01 공식 단가에 따른 추가분 계산이다. 기존 웹앱·Supabase Pro 비용은 포함하지 않는다. 실제 결제액은 무료 한도 잔여량·지역별 SKU·환율·세금·실제 실행량에 따라 달라진다.

| 항목 | 확인한 단가/계산 | 추가 비용 해석 |
|---|---|---|
| Scheduler | 결제 계정당 3개 무료, 초과 예약당 US$0.10/31일 | 새 예약 1개는 US$0 또는 US$0.10/31일. 호출 3회/주라고 3개 예약 과금은 아님 |
| Cloud Run Job | 기본 표 CPU US$0.000018/vCPU초, RAM US$0.000002/GiB초. Tokyo 배포 전 SKU 재확인 | 1 CPU·0.5 GiB로 600초 실행이면 약 US$0.0114/회. 월 5번의 수요일 × 3시도 × 600초 가정은 약 US$0.171/월, 무료분 적용 전 |
| API 키 비밀값 | 무료분 초과 시 자동 복제 활성 버전 약 US$0.06/월, 접근 US$0.03/1만 회 | 새 버전 1개를 유지하는 추가분. 기존 DB 비밀값 버전은 새로 만들지 않음 |
| 이미지 저장 | 무료분 초과 시 약 US$0.10/GiB·월 | 압축 이미지가 0.5 GiB라면 약 US$0.05/월. 실제 빌드 크기는 미측정 |
| Cloud Build | E2_MEDIUM US$0.003/분, 작업 timeout 10분 | 성공/실패와 별개로 사용시간 과금. 10분 가정 약 US$0.03/빌드. 무료 프로모션 적용 여부는 별도 |
| GCS 원문·작업·네트워크·로그 | 용량·요청·전송량에 따라 과금 | 현재 주간 소량 수집에서 소액 예상이나 정확한 무료 잔여량·FUSE 작업 수·실측 용량은 미확인 |

**계획 추가 비용은 월 US$0~1 정도로 예상하나, 이는 확정 견적도 청구 상한도 아니다.** 600초 timeout도 청구액 상한을 설정하는 기능은 아니다. 테스트·수동 실행·중복 트리거·재빌드가 늘면 비용이 증가한다. 기존 무료 한도와 계정 전체 사용량을 다 확인하지 않았으므로 정확한 실제 청구액을 사전에 보장할 수 없다.

공식 근거:

- [Cloud Scheduler 가격](https://cloud.google.com/scheduler/pricing)
- [Cloud Run 가격](https://cloud.google.com/run/pricing)
- [Secret Manager 가격](https://cloud.google.com/secret-manager/pricing)
- [Artifact Registry 가격](https://cloud.google.com/artifact-registry/pricing)
- [Cloud Build 가격](https://cloud.google.com/build/pricing)
- [Cloud Storage 가격](https://cloud.google.com/storage/pricing)

## 준비한 파일과 검증 상태

- `src/horse_racing/jobs/weekly_entry_cards.py`: worker.
- `Dockerfile.jobs`: digest 고정 베이스, 잠금 의존성, non-root 실행.
- `cloudbuild.jobs.yaml`: 수집 이미지 빌드·push만 수행. 기존 `cloudbuild.yaml` 웹 배포 경로와 분리.
- `.gcloudignore.jobs`, `Dockerfile.jobs.dockerignore`: allowlist로 `.env`, DB, 모델, 연구 폴더 업로드 차단.
- `tests/test_weekly_entry_cards.py`: 주간 범위, 잘못된 DB/Transaction pooler 차단, dry-run 무접속, 원천 불일치, 취소 보존, 입력 해시 테스트.
- 2026-10-07 dry-run으로 10월 7~13일 동적 범위 확인. API·DB 쓰기 0.
- worker·출마표·출발번호·경주계획·장구 관련 테스트 38개 통과. 이 결과는 클라우드 통합 실행 검증을 대신하지 않는다.
- Google Cloud SDK의 실제 업로드 필터로 allowlist를 확인했다. 업로드 대상은 빌드 설정·의존성 파일·README·`src`뿐이며 `.env`, DB, 모델, 연구 폴더 및 Python 캐시는 제외한다.
- 클라우드 이미지 빌드·수동 Job 실행·원문 GCS 영속성 검증은 통과했다. 예약 호출과 중복 적재 방지 실측은 아래 적용 기록을 참조한다.

## 승인 후 적용 순서

1. 비용 승인 확인. `mapilog-509017`을 모든 명령에 명시하고 기본 gcloud 프로젝트(Fintor)를 변경하지 않는다.
2. 새 수집/호출 서비스 계정, 비공개 원문 버킷, API 키 비밀값 생성. 필요한 리소스에만 IAM 부여. Scheduler API 활성화.
3. `.gcloudignore.jobs`를 사용해 `cloudbuild.jobs.yaml`로 이미지 빌드. 기존 웹 서비스에는 배포하지 않는다.
4. 고정 이미지 digest와 고정 비밀값 버전, `/raw` 영속 볼륨으로 Job 생성.
5. 수동 1회 실행 후 최종 성공·DB 저장값·원문 객체 검증. 재실행에서는 같은 입력을 건너뛰는지 확인.
6. 검증 통과 후 Scheduler 생성·활성화. 다음 예약 시각과 상태를 확인한다.
7. 디스코드 웹훅·성공/실패 알림은 사용자가 요청할 때 별도 연결한다.

## 실제 적용 기록

- 사용자가 비용 안내 후 활성화를 승인했다.
- 프로젝트 `mapilog-509017`, 리전 `asia-northeast1`만 변경했다. Fintor 및 기존 웹 서비스는 변경하지 않았다.
- Cloud Build `c652e6e5-c41a-4e27-ac28-f815d8fceabd` 성공. 10:37:12~10:38:18 UTC 실행.
- 이미지: `asia-northeast1-docker.pkg.dev/mapilog-509017/mapilog/weekly-entry-cards@sha256:b18d70590217eff8e5c3ff763ef16cc39d64e5a726c6294fa888d7df6c1ef706`.
- Job: `mapilog-weekly-entry-cards`, 1 CPU / 512 MiB / timeout 600초 / 재시도 0.
- 수집 계정: `mapilog-card-collector@mapilog-509017.iam.gserviceaccount.com`.
- 호출 계정: `mapilog-card-invoker@mapilog-509017.iam.gserviceaccount.com`.
- 버킷: `gs://mapilog-509017-kra-raw`, 도쿄 Standard / uniform access / public access prevention.
- DB 비밀값 버전 3은 값 노출 없이 대상 ref와 `SELECT 1` 성공을 검증했다. KRA 비밀값은 새로 생성한 `horse-racing-kra-service-key:1`.
- 수집 계정에는 비밀값 2개만 Secret Accessor, 원문 버킷만 Storage Object User 권한을 부여했다. 호출 계정에는 이 Job만 Run Invoker 권한을 부여했다.
- 첫 수동 실행: `mapilog-weekly-entry-cards-fwdqn`, **성공**. 19:39:47~19:43:32 KST, 약 3분 45초.
- 공식 조회 응답 40페이지를 확보하고 67경주·700두를 저장·검증했다. HTTP 재시도까지 포함한 요청 총횟수를 별도 계측한 것은 아니다.
- Supabase 부모 실행 `19761`과 child `19762~19785`, 총 25개가 모두 `completed`, 각 수집/적재 건수 일치.
- 원문 문서 48개, 총 1,172,562 bytes. 종료 후 GCS 객체 48개를 실제 읽어 길이·SHA-256을 대조했고 불일치 0건이다. 원문 URL/파라미터에 API 키를 포함하지 않는다.
- Scheduler `mapilog-weekly-entry-cards`: **ENABLED**, `Asia/Seoul`, 수요일 17:10·18:10·19:10, retry count 0.
- 다음 예약: **2026-10-07 17:10 KST** (`2026-10-07T08:10:00Z`).
- 예약 경유 수동 호출은 **HTTP 200 성공**. 최종 Job 실행 `mapilog-weekly-entry-cards-44gzh`도 **성공**했다.
- 두 번째 실행: 19:47:19~19:47:48 KST, 약 29초. 공식 자료를 재조회하고 `skipped_unchanged_window`, `previous_run=19761`로 정상 종료했다. 같은 입력/저장값에서는 새 적재를 하지 않는 경로가 실제 동작했다.
- 재실행 후 별도 읽기 전용 쿼리로 같은 입력 해시의 적재 기록이 **1개 유지**되는 것을 확인했다. 부모 `19761`은 `completed`, 700두 저장 상태다.

### 측정한 비용 입력값

- 이미지 저장 크기: 236,723,648 bytes (약 0.220 GiB). 무료분 소진 시 단순 전체 크기 계산은 약 US$0.022/월이며 공유 레이어·실제 저장 합산에 따라 달라질 수 있다.
- 첫 실행 약 225초: 기본 표 단가로 CPU·메모리만 약 US$0.0043/회 수준, 무료분·네트워크·로그 등 적용 전 추산. 실제 청구액을 조회한 값은 아니다.
- 첫 이미지 빌드는 약 66초. E2_MEDIUM 단가 단순 계산 약 US$0.0033, 무료분·청구 단위 등 적용 전 추산.
- 월 US$0~1의 승인된 예상 범위는 유지하며 정확한 청구액/상한을 보장하지 않는다.

### 수동 실행과 운영 확인

```sh
gcloud run jobs execute mapilog-weekly-entry-cards --project=mapilog-509017 --region=asia-northeast1 --async
gcloud scheduler jobs describe mapilog-weekly-entry-cards --project=mapilog-509017 --location=asia-northeast1
```

수동 실행도 현재 KST 기준 미래 출마표만 대상으로 한다. 당일 변경·완료 경주 수집에는 이 작업을 사용하지 않는다. 예약 호출 HTTP 성공과 Job 최종 성공은 서로 다른 상태이며, 최종 성공은 Cloud Run 실행 상태와 `ingestion_runs`/JSON 로그로 확인한다.

## 2026년 10월 2일 Discord 연결과 매일 조교 예약

주간 출마표와 매일 조교 갱신의 두 예약이 활성화돼 있다. 두 작업 모두 동일한 사용자 제공 Discord 웹훅을 Secret Manager 환경변수로 읽는다. 웹훅 자체는 이 문서·코드·이미지·로그에 저장하지 않는다. Fintor, 기존 웹 서비스, 예측 자동화는 변경하지 않았다.

| 작업 | Google 리소스 이름 | 한국 시간 예약 | 수집 범위 | Discord |
|---|---|---|---|---|
| 주간 출마표 | `mapilog-weekly-entry-cards` | 수요일 17:10·18:10·19:10 | 기존 주간 범위와 검증 유지 | 저장 완료·검증 후 변경 없음·실패 |
| 매일 조교 | `mapilog-daily-training` | 매일 14:30 | 실행일 포함 최근 7일, 일반·출발·수영·언덕조교 | 종류별 신규·변경·유지·최신일·실패 요약 |

### 런타임과 비밀값

- 프로젝트 `mapilog-509017`, 리전 `asia-northeast1`을 명령마다 명시했다. 기본 gcloud 프로젝트는 변경하지 않았다.
- 두 Job의 새 고정 이미지: `asia-northeast1-docker.pkg.dev/mapilog-509017/mapilog/weekly-entry-cards@sha256:80dc15fb8673c7c073ffc0d8b07c3b878b90931e46a18cc3c2a9555ab68a1f78`.
- Cloud Build `e9821538-ef77-4bd6-8612-e4fbee3152ad` 성공. 수집 전용 allowlist로 비밀 설정·운영 DB·연구 데이터·모델을 업로드에서 제외했다.
- 주간 Job의 기존 DB·API 키·볼륨·시간·재시도 설정을 유지하고 이미지와 Discord 비밀값 참조만 추가했다.
- 조교 Job: `python -m horse_racing.jobs.daily_training --apply`, 1 CPU·512MiB, task 1·parallelism 1, timeout 1800초, task retries 0.
- 조교 Scheduler: `30 14 * * *`, `Asia/Seoul`, 재시도 0, OAuth로 Cloud Run v2 실행 API 호출. `mapilog-card-invoker` 계정에 이 Job의 Run Invoker 권한을 부여했다.
- 수집 계정은 기존 `mapilog-card-collector`를 사용한다. DB와 KRA 비밀값은 기존 버전 `3`·`1`, Discord는 새 `horse-racing-discord-webhook:1`을 주입한다. Discord 비밀값 접근 권한은 수집 계정에만 추가했다.
- 원문은 기존 비공개 GCS 버킷 `mapilog-509017-kra-raw`의 영속 `/raw` 볼륨에 저장한다. UID/GID 10001을 유지한다.
- 로컬 비밀 설정 `.env.discord`는 Git 제외, 권한 600이다. 클라우드는 이 파일을 업로드하지 않고 `HORSE_RACING_DISCORD_WEBHOOK_URL`을 Secret Manager에서 주입한다.

### 갱신과 알림의 경계

Supabase만 자동 갱신한다. 로컬 SQLite 동기화, 예측 실행, 웹앱 배포, 결과·진료 등 다른 종류 수집은 포함하지 않는다. 일반조교는 서울·제주·부경, 출발조교는 서울·부경 API와 제주 공식 홈페이지, 수영·언덕은 기존 특수조교 수집기를 사용한다.

제주 출발조교의 동일 말·날짜 여러 행은 `occurrence_no`별로 유지한다. 다시 조회하면 같은 저장 슬롯을 갱신한다. 단, 슬롯은 시간순서나 공식 이벤트 ID를 뜻하지 않는다. 일반조교의 null 시간 중복은 날짜·지역 쓰기 잠금으로 방지한다. 업무 행과 달리 원문 관측·실행 이력은 매 실행 별도로 남는다.

빈 응답은 기존 기록을 삭제하지 않는다. 공개되지 않았다는 뜻과 실제 조교가 없었다는 뜻을 단정해서 섞지 않는다. 종류별 최신일은 이번 조회 범위 안에 저장된 기록의 최신일이다. 하루 1회 갱신이므로 경주 직전 실시간 갱신을 보장하지 않는다.

알림은 DB 저장·검증 뒤, DB 잠금/연결 정리 후 전송한다. Discord 전송 실패로 성공한 DB 갱신을 실패 처리하거나 다시 수집하지 않는다. `wait=true`로 메시지 저장 확인을 받으며 모든 mention을 끈다. 전송 시간초과는 도착 여부가 불명확하므로 자동 재전송하지 않는다.

애플리케이션이 포착한 수집 실패에는 실패 알림이 있다. 컨테이너 기동 실패, 프로세스 강제 종료, timeout, Scheduler 인증 실패, Discord 자체 장애까지 확실히 알리는 별도 Cloud Monitoring 경보는 아직 추가하지 않았다. 이 경우 Cloud Run/Scheduler 상태와 로그를 확인해야 한다.

### 최초 실행 검증

- 관련 단위·회귀 테스트 80개와 Ruff 검사 통과.
- 기존 주간 Job `mapilog-weekly-entry-cards-bmq9f`에서 일회성 연결 테스트 실행 성공·Discord 확인. 이 실행은 DB 적재·예측 실행을 하지 않았다. 주간 실제 수집 로직의 예약 실행은 기존 수요일 일정에 따른다.
- 조교 첫 실제 실행 `mapilog-daily-training-w8m4n` 성공. 부모 적재 실행 `19788` 완료, 50개 작업 실패 0건. worker 소요 186.2초, Cloud Run 최종 실행 약 3분 18초.
- 조회 범위 `2026-09-26`~`2026-10-02`, 확인된 네 종류 최신일은 모두 `2026-10-01`. 10월 2일 날짜별 조회는 빈 응답이어서 기존 기록을 보존했다.
- 저장 완료 뒤 Discord 요약 전송 확인. GCS 원문 표본 5개를 종료 후 다시 읽어 DB의 SHA-256·길이와 모두 일치했다. 이 검증은 모든 원문 파일 전수 검증은 아니다.

| 종류 | 신규 업무 행 | 변경 업무 행 | 유지 업무 행 | 최신 스냅샷에서 제외 |
|---|---:|---:|---:|---:|
| 일반조교 | 1,884 | 2 | 5,166 | 0 |
| 출발조교 | 281 | 254 | 154 | 0 |
| 수영조교 | 91 | 1 | 107 | 0 |
| 언덕조교 | 22 | 0 | 127 | 0 |

새 조교 Scheduler 호출은 HTTP 200으로 Cloud Run 실행 `mapilog-daily-training-hbrjm`을 생성했다. **예약 경유 재실행도 최종 성공**했고, 부모 `19839` 완료·50개 작업 실패 0건·Discord 요약 전송을 확인했다. worker 소요 185.9초, Cloud Run 최종 실행 약 3분 28초다. 두 실행은 각각 원천 조회 8,232행·처리 8,086행이다. 처리 건수는 신규 추가 건수가 아니라 기존 행 갱신을 포함한다. 언덕 두 요청의 중복 원천이 합쳐져 조회와 처리 건수가 다르다.

재실행 요약에서 네 종류 모두 신규·변경·최신 스냅샷 제외가 0건이었다. 별도 읽기 전용 DB 검증도 아래와 일치했다. 이 검증 범위는 최근 7일이며 과거 전체 DB 전수 중복 감사는 아니다.

| 종류 | 최근 7일 저장 행 | 저장 키 중복 그룹 |
|---|---:|---:|
| 일반조교 | 7,052 | 0 |
| 출발조교 | 689 | 0 |
| 수영조교 | 199 | 0 |
| 언덕조교 | 149 | 0 |

일반조교는 말·지역·날짜·시작/종료 시간(null 포함), 출발조교는 말·지역·날짜·저장 슬롯, 수영은 공식 말번호·지역·날짜, 언덕은 원천 행 해시 기준으로 검사했다. 제주 2026-09-30 출발조교는 106두·113행을 유지했다. 언덕 저장 행 149개 중 이번 재관측/처리는 146개이며, 미재관측 기존 3개는 삭제하지 않았다. 두 Scheduler가 `ENABLED`이고 주간 Job의 원래 실행 인자가 연결 테스트 뒤에도 유지된 것을 확인했다.

### 추가 비용

2026-10-02 변경 전 공식 가격을 확인하고 사용자에게 안내했다. 무료 잔여량·환율·세금·실제 사용량을 모두 확정할 수 없으므로 실제 청구 총액이나 상한은 보장하지 않는다. 기존 Supabase Pro와 기존 리소스 비용은 별도다.

- 새 Scheduler 1개: 무료 3개 한도 초과 시 US$0.10/31일. 기존 주간 Scheduler의 Discord 추가는 예약 수를 늘리지 않는다.
- 새 웹훅 자동 복제 비밀값 버전 1개: 무료분 초과 시 약 US$0.06/월, 접근 US$0.03/1만 회. 무료 한도는 결제 계정 기준 6개 버전·1만 접근이다.
- 조교 연산: 기본 단가 CPU US$0.000018/vCPU초 + RAM US$0.000002/GiB초. 매일 1800초·31회·1 CPU·0.5GiB 가정은 무료 적용 전 US$1.0602/월. 최초 실측 실행 시간 약 198초를 매일 유지한다고 가정하면 약 US$0.12/월이지만 후속 실행시간을 보장하는 값은 아니다.
- 이미지 빌드: E2_MEDIUM US$0.003/분. 이번 빌드 약 74초를 단순 적용하면 약 US$0.0037, 무료분·청구 단위 적용 전 추정이다. Cloud Build 설정 timeout 600초 사용 가정은 US$0.03이다.
- 이미지 저장·원문·FUSE 작업·외부 통신·로그·수동 검증 실행은 별도 사용량 과금이다. timeout은 청구 상한이 아니다.

가격 근거는 앞의 공식 링크와 동일하다. 이번에 새 Supabase 프로젝트나 컴퓨팅·디스크 확장, 웹 서비스 재개는 하지 않았다.

### 웹훅 교체와 수동 실행

기존 Discord 웹훅을 삭제하거나 기존 토큰을 무효화하면 그 주소의 연결은 끊긴다. 재발급은 예약 자체를 삭제하지 않지만, 새 주소를 설정하지 않으면 알림이 실패한다. 지금은 기존 사용자 제공 주소를 유지하고 있다.

중단을 줄이려면 별도 새 웹훅을 먼저 만들고, 새 주소를 비밀값의 새 버전으로 저장한 뒤 두 Job의 참조 버전을 함께 교체한다. 새 런타임 테스트와 진행 중인 옛 실행 종료를 확인한 다음 기존 Discord 웹훅을 폐기한다. 로컬에서 사용한다면 `.env.discord`도 새 주소로 교체한다. 주소는 Git·명령 인자·로그·문서에 쓰지 않는다. **현재 Job이 버전 1에 고정돼 있으므로 Secret Manager에 새 버전만 추가하는 것으로는 교체되지 않는다.**

```sh
gcloud scheduler jobs describe mapilog-daily-training --project=mapilog-509017 --location=asia-northeast1
gcloud run jobs execute mapilog-daily-training --project=mapilog-509017 --region=asia-northeast1 --async
gcloud run jobs executions list --job=mapilog-daily-training --project=mapilog-509017 --region=asia-northeast1 --limit=5
```

수동 실행도 실행일 기준 최근 7일과 같은 잠금·업무 키를 사용한다. 중복 실행 잠금은 이 worker 간 실행을 막으며, 다른 수집기의 전역 실행까지 모두 막는 것은 아니다.

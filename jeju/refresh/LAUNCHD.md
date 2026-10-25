# 제주 연구 DB 자동 갱신

2026-10-20 설치 및 설치된 서비스의 실제 실행·독립 검증을 완료했다. [설치 결과와 검증 근거](../research/20261020_launchd_install/README.md)를 따른다.

관리 모듈은 `jeju.refresh.launchd`이며, 고정 label `com.horse-racing.jeju-research-refresh`를 현재 사용자의 GUI launchd에 등록한다. 매일 시스템 시간대 `Asia/Seoul`의 22:00에 실행한다. `RunAtLoad`와 `KeepAlive`는 꺼져 있어 로그인 직후 실행하거나 실패 뒤 반복 재시도하지 않는다.

현재 사용자 로그인·Mac의 정시 깨어 있음·인터넷 연결이 필요하다. Codex 앱 실행은 필요하지 않다. 기존 갱신기는 최근 14일, 일요일에는 최근 60일을 재조회한다. 한국시간 21시 이후에는 당일까지, 그 전에는 전날까지 조회한다.

프로젝트 루트에서 다음 명령을 사용한다.

```sh
.venv/bin/python -m jeju.refresh.launchd install
.venv/bin/python -m jeju.refresh.launchd status
.venv/bin/python -m jeju.refresh.launchd run
.venv/bin/python -m jeju.refresh.launchd stop
```

`run`은 설치된 같은 서비스를 `launchctl kickstart`로 요청한다. runner가 `.venv/bin/python -u -m jeju.refresh.run --apply`를 실행하고, 그 실행의 stdout JSON이 가리킨 application receipt를 확인한다. 완전한 수집이 아닌 적용 결과는 exit code 2와 `partial_failure`로 표시한다. 이미 실행 중인 경우 `busy_duplicate`, 새 receipt가 없는 경우 `no_receipt`를 기록하며 두 상태는 `last_success`를 갱신하지 않는다. 구조화 상태는 `jeju/research/20261017_core_refresh/launchd_execution_status.json`에 저장한다.

launchd stdout/stderr는 `~/Library/Logs/horse-racing/jeju-research-refresh.out.log` 및 `jeju-research-refresh.err.log`에 기록한다. 현재 `local_log_rotation.py`의 로그 allowlist에는 이 두 이름이 없어 기존 자동 회전 대상이 아니다.

plist에는 API 자격 증명을 저장하지 않는다. 실행 프로세스는 현재 제주 갱신 코드가 사용하는 기존 설정을 그대로 읽는다.

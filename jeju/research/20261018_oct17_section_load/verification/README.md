# 독립 검증

`independent_verify.py`는 Python 표준 라이브러리 `HTMLParser`, `json`, `sqlite3`로
2026-10-17 제주 1~7R 원문을 독립 확인한다. 네트워크 호출은 하지 않는다.

원문 검증은 이미 완료했다. `source_verification.json`에는 API6/API303 원문 SHA,
7개 홈페이지 원문 SHA, 69두 홈페이지 표본, API6 39개 시간·거리 지점,
API303/API6 통과조 문자열 비교를 담았다. API6 구간·누적시간 39/39 일치,
API6 거리 33/39 일치, 각 원천의 제공 통과조 29/29 일치를 확인했다.
거리 불일치 6개는 5R의 `dist_1f`~`dist_6f`뿐이다.

`simulate_distance_guards.py`는 loader의 실제 DDL/view SQL과 저장된 API6
current raw view 정의를 읽어, 5R 원문 한 건으로 임시 SQLite 메모리 DB에서
기준값과 실패 상태를 재현한다. 리뷰 전체/단일행 삭제, API payload SHA·페이지
SHA·artifact ID·경주키·rcDist·거리 원값 변경 때 유효거리가 NULL로 차단되는지
확인한다. `preapply.json`에는 plan SHA, 14개 입력 해시, migration 일치,
read-only DB 사전 상태와 이 시뮬레이션 결과를 묶었다.

적재 후 확인은 공유 DB를 SQLite `mode=ro`와 `query_only`로 연다. API4 기존
69행과 홈페이지 말 ID·마번·착순, API6/API303 각각 7개 원문 JSON 및 source
artifact의 페이지 SHA·파일 경로·item 순서를 확인한다. 새
`api6_section_points_current` 뷰에서 검토가 바인딩된 5R 6개 거리만 홈페이지
값으로 읽히는지도 확인한다.

```sh
python3 research/20261018_oct17_section_load/verification/independent_verify.py \
  --require-loaded \
  --output research/20261018_oct17_section_load/verification/post_load_verification.json
```

검증 도구는 공유 DB를 수정하지 않는다. guard 시뮬레이션만 `:memory:` DB에서
loader SQL을 실행한다.

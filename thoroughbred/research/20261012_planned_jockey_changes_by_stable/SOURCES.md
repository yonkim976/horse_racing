# 출처와 재실행

기존 연구50의 [분석행](../20261012_jockey_switch_trainer_intent/outputs/analysis_rows.parquet), [전년도 순위](../20261012_jockey_switch_trainer_intent/outputs/annual_jockey_rankings.csv), [원시/모형 검증](../20261012_jockey_switch_trainer_intent/outputs/verification.json)을 불변 참조했다. 새 입력 파일별 경로·바이트·SHA-256·공식 다운로드 URL·보관 수집시각은 [source_audit.json](outputs/source_audit.json)의 source_inputs2937항목을 따른다. 입력 원본 자체를 새 산출물로 중복 복사하지 않았다.

- 공식 dacom01: 경주 전 명목일자의 주간 출전표 CP949. `data/raw/kra_text/_manifests/dacom01/manifest.jsonl`의 지원파일805개, 파일 내용의 경주일자·번호와 기수/조교사/말을 읽었다. 2026년9월부터 제목에 서울/부경이 붙는 형식을 처리했다. 수집은 경주 뒤이므로 최초 게시 시각/불변성 미인증.
- 공식 dacom13: 일일 변경/취소 원문 CP949. 명시 ‘기수변경이 없습니다’ 또는 기수변경 구역의 완전한 파싱을 날짜지원으로 삼았다. 중복SHA가 다른 지역 경로를 가리키는 경우에도 manifest의 요청지역을 보존했다. 반영 이유는 원문 표현이다.
- 공식 API10_1: 보관 JSON의 resultCode00,1페이지,totalCount=실제행수가 확인된 일자/지역만 지원으로 삼았다. 0건 수신과 수신 없음 구분. [공식 자료 정의](https://www.data.go.kr/data/15057181/openapi.do)(2026-10-12 열람): 경주 전 출전표 기승기수가 변경될 때 전후기수·중량·사유 제공. [공식 변경 화면](https://race.kra.co.kr/raceFastreport/ChulmapyoChange.do?Act=03&Sub=1&meet=1)은 정의 확인용이며 최신 화면의 경주는 고정 성적에 추가하지 않았다.
- API215: `20261002_steward_reports_v1/source/api_observations.parquet`의14,867경주 jkChange 전부-또는null. 해당 칸은 결측이며 변경 없음 근거로 사용하지 않았다.

원문줄은 card_rows.parquet/notice_rows.parquet의 source_path·line_no·source_sha256·source_line을 따른다. JSON notice의 line_no는 item배열의0기반 위치, 텍스트는1기반 줄이다. 실제 결과는 기존 source_file/source_item_index로 원문까지 추적 가능하다. API/텍스트의 같은 사건은 중복 출전으로 세지 않았으며 서로 다른 사유 문구도 보존했다.

재실행(저장된 입력만 사용, DB/네트워크 없음):

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_planned_jockey_changes_by_stable/extract.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_planned_jockey_changes_by_stable/analyze.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_planned_jockey_changes_by_stable/verify.py
MPLCONFIGDIR=/private/tmp/horse_jockey_switch_mpl PYTHONDONTWRITEBYTECODE=1 .venv/bin/python thoroughbred/research/20261012_planned_jockey_changes_by_stable/publish.py
```

register.py는 이미 등록한 후 재실행하지 않는다. 보고서 재생성 뒤에는 final_review.py와 record_inventory.py를 순서대로 실행해 변경 바이트·해시를 새로 맞춘다. 기존 연구/입력 원본은 실행으로 쓰지 않는다.

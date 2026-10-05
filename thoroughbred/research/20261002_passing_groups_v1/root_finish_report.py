"""Publish the completion report only after independent post-append gates pass."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORE = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1'


def main():
    reports = {name: json.loads((HERE/file).read_text()) for name,file in {
        'api_literal_source':'root_api_verification.json',
        'rpt_bytes_headers_capture':'root_rpt_verification.json',
        'complete_pair_evidence':'root_pair_evidence_verification.json',
        'new_data_and_selection':'root_new_data_verification.json',
        'existing_data_preservation':'root_preservation_verification.json',
    }.items()}
    assert all(report['all_passed'] for report in reports.values())
    applied = json.loads((HERE/'loader/apply_report.json').read_text())
    assert applied['applied'] and applied['status']=='applied'
    manifest = json.loads((CORE/'manifest.json').read_text())
    assert manifest['database_sha256']==applied['core_sha256_after']==reports['existing_data_preservation']['database_sha256']
    counts = applied['table_and_view_counts']
    summary = {'status':'applied_and_independently_verified','scope':{'start_date':'2010-01-01','cutoff_inclusive':'2026-09-29','actual_meets':[1,3,4],'model_period_start':'2017-01-01'},
        'database_path':str(CORE/'thoroughbred_core.duckdb'),'database_sha256':manifest['database_sha256'],
        'manifest_sha256':hashlib.sha256((CORE/'manifest.json').read_bytes()).hexdigest(),
        'api_pages':48,'api_raw_observations':29774,'confirmed_races':29710,'nonexecution_api_receipts':64,
        'selected_point_rows':144001,'selected_api_point_rows':142227,'selected_rpt_point_rows':1774,
        'cross_source_literal_discrepancies':50,'cross_source_discrepant_races':39,
        'unmapped_raw_api_slots':414,'rpt_raw_point_lines':111467,'rpt_nonempty_point_lines':83390,
        'rpt_blank_point_lines':28077,'rpt_files':1827,'rpt_files_with_exact_capture_timestamp':1826,
        'current_object_count':reports['existing_data_preservation']['current_objects'],
        'original_objects_preserved':153,'source_manifests_rows':26,
        'new_object_counts':counts,'independent_gates':{name:True for name in reports},
        'historical_publication_time_verified':False,'notation_grammar_parsed':False,
        'backup_pair':'thoroughbred/data/core_api_2010_20260929_v1/backups/20261002_before_passing_groups'}
    (HERE/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    readme = f'''# 경주 단위 통과조 적재·검증 완료

2026-10-02에 연구 코어에 실제 저장하고 주 에이전트의 독립 검증을 완료했다. 대상은 **2010-01-01~2026-09-29, 서울·부산경남·영천**이다. 제주를 제외하며 모델 개발·평가 대상은 2017년 이후다. 이번 API 관측의 실제 마지막 경주일은 2026-09-20이다.

DB: [thoroughbred_core.duckdb](../../data/core_api_2010_20260929_v1/thoroughbred_core.duckdb)

## 적재 결과

| 항목 | 수량 |
|---|---:|
| API303 전수 수집 | 35 연도·경마장 파티션, 48페이지 |
| API 원문 경주 관측 | 29,774행 |
| 확정 시행 경주와 연결 | 29,710경주 |
| 판정된 취소·불성립 경주 API 원문 | 64행, 별도 분류 |
| 조회용 통과조 | 144,001 경주·지점 |
| API 선택 / 성적표 보완 | 142,227 / 1,774 지점 |
| API·성적표 표기 차이 | 50지점, 39경주 |
| 성적표 원문 | 1,827파일, 17,371경주, 111,467지점행 |
| 성적표 값 있음 / 빈칸 | 83,390 / 28,077행 |
| 성적표 정확한 수집 원장 연결 | 1,826파일; 미연결 1파일은 시각 NULL |

확정 시행 **29,710경주 모두 값이 있는 지점을 최소 하나 이상 보유**한다. 이는 거리별 모든 지점의 완전성과 과거 공개 시각까지 확정했다는 뜻은 아니다. 짧은 거리의 미사용 지점이나 원문의 빈칸에 값을 만들지 않았다. API 중복 경주 키·누락된 확정 경주 키·분류되지 않은 API 경주 키는 0건이다. 활성 경주에서 제외된 기존 오류 72키는 감사 근거를 함께 보존하며 이번 API303 응답에는 없었다.

## 저장 구조

| 테이블·뷰 | 의미 |
|---|---|
| `passing_api_observations` | 페이지·행별 원문 값, 원본 타입/JSON, 수집 시각, 응답 해시 |
| `passing_rpt_point_observations` | 정확한 지점 라벨, 콜론 뒤 원문·패딩, 물리 바이트·줄·오프셋 |
| `passing_api_rpt_value_matches` | 같은 경주에서 값이 같은 원문 쌍 87,334건; 유일/복수 대응 근거 |
| `race_passing_groups` | 확정 경주 × 지점별 선택 값, 선택 원천·판정·대안 원문·매핑 버전 |
| `passing_race_coverage` | 확정 29,710경주별 원천·조회 지점·미대응 API 관측 수 |
| `passing_point_discrepancy_ledger` | API와 성적표의 표기가 다른 50지점의 두 원문 |
| `passing_api_unmapped_point_observations` | 지점 대응을 확정하지 않은 API 원문 414칸 |
| `passing_api_event_reconciliation` | 시행 29,710행 / 판정된 미시행 64행 |
| `passing_api_race_times` | API의 경주 단위 3F·4F 통과시간 및 템포 원문 |

괄호, 쉼표, `^`, `-`, `=`, `≡` 및 원문 공백은 보존했다. 비교할 때만 별도 값에서 양끝 ASCII 공백을 제거했다. 통과조의 그룹 문법·구성원·거리차를 파싱하지 않았고 말별 통과착순과 합치지 않았다. 경주 단위 3F/4F를 말별 구간시간으로 사용하지 않는다.

## 서울 2020~2021년 대응 검증

공식 설명의 기본 지점 대응을 그대로 적용하면 잘못 연결되는 원문이 재확인됐다. 성적표 1,495경주 모두 유일한 API 경주행에 연결됐다. 유효값 집합이 같은 529경주 중 381경주는 기본 칸까지 같고 148경주는 칸이 다르다. 나머지 966경주는 성적표 값 중 적어도 하나가 API 어느 칸에도 없으며, 누락 값 관측은 1,360개다. API에만 있는 추가 값 관측은 없었다.

연도 전체에 동일한 칸 교환 규칙을 적용하지 않았다. 같은 경주의 API 필드와 성적표 지점이 **유일한 동일 원문 값**으로 대응되는 경우에만 해당 API 값을 그 지점으로 조회한다. 반복된 같은 값 때문에 지점을 확정할 수 없는 API 414칸은 미대응 원장에 남긴다. API의 확정 지점 값이 없을 때는 정확한 성적표 지점 라벨의 유일값을 보조 선택한다. 이 방식으로 성적표 1,774지점을 보완했다.

## 원문 차이와 API 우선 정책

사용자의 API 기준 지시에 따라 지점이 확정된 유일 API 값은 성적표와 달라도 API를 선택한다. 50지점(39경주)은 `api_primary_with_rpt_discrepancy`로 표시하고 두 원문을 보존했다. 원인과 문법상의 동등성을 추정하지 않았다. 일부는 그룹 내 번호 순서만 다르고 일부는 그룹 구분 기호도 다르다. [전체 차이 목록](root_expected_value_conflicts.json)을 검토할 수 있다. API 내부에서 서로 다른 값이 경쟁하는 경우에는 보류하도록 설계했으며 이번 선택 결과에는 그런 보류가 없다.

원천 경로의 meet=3만으로 부산경남으로 처리하지 않았다. 2026-09-13 성적표의 `(영천)` 본문으로 확인된 6경주는 실제 영천(meet=4)에 연결했다. 성적표 수집 시각을 정확히 연결할 수 없는 파일은 `20220522dacom11.rpt`(서울)이며 경주·지점 원문은 정상 보존했다.

## 검증과 백업

- API 48페이지·29,774 원문행의 타입·값·페이지 순서·총 건수·SHA를 전량 대조했다.
- 성적표 1,827파일·111,467지점행의 CP949 원문, 줄·바이트·헤더·실제 장소와 수집 원장을 독립 대조했다.
- API↔성적표 값 쌍 87,334건의 전체 집합과 후보 수·유일 대응 판정이 일치했다.
- 새 입력 10개 테이블은 원본 입력 전체 행과 동일하다. 독립 계산한 144,001개 선택 값과 DB 조회 결과의 양방향 차이는 0건이다.
- 기존 **153개 객체의 스키마·테이블 전체 행·뷰 정의를 보존**했다. 원천 manifest는 기존 25행을 유지하고 1행을 추가했다.
- 기존 DB 명세의 필드·입력 목록·적재 이력은 보존하며 새 행 수와 DB 해시를 검증했다. 현재 DB는 **{summary['current_object_count']}객체**, 원천 manifest **26행**이다.
- 적재 직전 DB·명세를 [백업](../../data/core_api_2010_20260929_v1/backups/20261002_before_passing_groups/backup_pair_attestation.json)하고 원본과 두 해시의 동일성을 확인했다.

[사전 검증](loader/dry_run_report.json), [실제 적재](loader/apply_report.json), [새 데이터 검증](root_new_data_verification.json), [기존 데이터 보존 검증](root_preservation_verification.json), [요약](summary.json).

수집일은 관측 시각이며 과거 공개 시각은 별도 미확정이다. `historical_publication_time_verified=false`, `source_publication_at_kst=NULL`로 저장한다. 같은 경주의 통과조·종반 시간은 그 경주의 경주 전 예측 입력으로 사용하지 않는다. 전체 연구 DB 최종 동결 및 심판리포트·제재 본 적재는 후속 작업이다.

원천 설명: [한국마사회 API303](https://www.data.go.kr/data/15119851/openapi.do).

## 조회 예시

```sql
SELECT actual_meet_code, event_date, race_no, canonical_point_code,
       notation_raw, selected_source, selection_status
FROM race_passing_groups
WHERE event_date >= '2017-01-01'
ORDER BY actual_meet_code, event_date, race_no, canonical_point_code;
```
'''
    (HERE/'README.md').write_text(readme)
    mainplan = ROOT/'thoroughbred/research/20260929_database_rebuild_plan/README.md'
    text = mainplan.read_text()
    entry = f'- 2026-10-02 [통과조 적재·검증](../20261002_passing_groups_v1/README.md)을 완료했다. API303 35파티션·48페이지의 29,774원문행을 보존하고 확정 시행 29,710경주에 통과조 144,001경주·지점을 연결했다(API142,227·성적표보완1,774). 취소·불성립 API64행은 별도 분류했다. 서울2020~2021은 경주별 유일한 원문 대응만 적용하고 미대응 API414칸을 보존했다. 원문 차이50지점·39경주는 API우선 선택과 양쪽 원문을 남겼다. 입력 전체 행·독립 선택 전량 일치·기존153객체 보존·명세 해시를 검증했다. 현재 코어{summary["current_object_count"]}객체·원천manifest26행이며 적재 전 DB·명세 백업1쌍을 추가했다. 과거 공개시각 및 전체 DB최종동결은 미확정이다.\n\n'
    if '20261002_passing_groups_v1' not in text:
        lines=text.splitlines(keepends=True);lines.insert(2,entry);text=''.join(lines)
    text=text.replace('공식 API는 모두 있으나 본 적재 전이다.','당시 공식 API는 모두 있으나 본 적재 전이었다. 통과조는 현재 위의 본 적재 결과를 따른다.')
    text=text.replace('9,320키는 재수집 대상이다.','9,320키는 당시 재수집 대상이었으며 이번 통과조 적재에서 보완했다.')
    text=text.replace('현재 코어는 153객체·원천 manifest 25행이다.','진료 적재 완료 당시 코어는 153객체·원천 manifest 25행이었다.')
    mainplan.write_text(text)
    core_readme=ROOT/'thoroughbred/research/20260929_core_api_db_v1/README.md'
    text=core_readme.read_text()
    if '20261002_passing_groups_v1' not in text:
        lines=text.splitlines(keepends=True)
        lines.insert(2,f'> 2026-10-02 [통과조 본 적재·독립 검증](../20261002_passing_groups_v1/README.md) 완료: 확정 29,710경주·144,001경주/지점(API142,227·성적표1,774), API/RPT 원문 차이50지점은 API우선과 차이 표시를 보존했다. 기존153객체 보존을 검증했으며 현재 {summary["current_object_count"]}객체·원천manifest26행이다. 아래 초기 코어 수치는 당시 기록이다.\n\n')
        core_readme.write_text(''.join(lines))
    print(json.dumps({'status':summary['status'],'objects':summary['current_object_count'],'selected_points':144001,'confirmed_races':29710},ensure_ascii=False))


if __name__ == '__main__':
    main()

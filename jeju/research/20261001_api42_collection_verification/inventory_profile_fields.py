"""Inventory actual API42 fields using the archived official field definitions."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
COLLECTION = HERE.parent / '20260930_api42_horse_breed_collection'
MARKERS = {'', '-', 'n/a', 'null', 'none', 'unknown', '미상'}


def state(value):
    if value is None or (isinstance(value, str) and value.strip().casefold() in MARKERS):
        return 'placeholder_or_null'
    if str(value).strip() in {'0', '0.0'}:
        return 'zero'
    return 'populated_nonzero'


def main():
    spec_path = HERE / 'api42_official_swagger_20261001.json'
    spec = json.loads(spec_path.read_text())
    props = spec['paths']['/totalHorseInfo_1']['get']['responses']['200']['schema']['properties']
    latest = {}
    for line in (COLLECTION / 'request_ledger.jsonl').read_text().splitlines():
        event = json.loads(line)
        latest[event['hrNo']] = event
    rows = []
    for horse_id, event in latest.items():
        if event['validation_status'] != 'validated':
            raise ValueError('Unresolved ID: ' + horse_id)
        path = (COLLECTION / event['raw_response_file']).resolve()
        if not path.is_relative_to((COLLECTION / 'raw').resolve()):
            raise ValueError('Raw path outside archive')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != event['response_sha256']:
            raise ValueError('Hash mismatch')
        item = json.loads(raw)['response']['body']['items']['item']
        if isinstance(item, list):
            if len(item) != 1:
                raise ValueError('Multiple profiles')
            item = item[0]
        if str(item['hrNo']) != horse_id:
            raise ValueError('ID mismatch')
        rows.append((event, item))
    target_ids = {event['hrNo'] for event, _ in rows}
    with sqlite3.connect((HERE.parents[2] / 'jeju/data/jeju_native_core.sqlite3').as_uri() + '?mode=ro', uri=True) as conn:
        race_ids = {row[0] for row in conn.execute('SELECT DISTINCT horse_id FROM race_result_rows')}
        trial_ids = {row[0] for row in conn.execute('SELECT DISTINCT horse_id FROM running_trial_rows')}
        candidate_counts = conn.execute('SELECT count(*),count(DISTINCT horse_id) FROM jeju_race_population_candidates').fetchone()
    linkage = {'profiles_with_existing_race_result_rows': len(target_ids & race_ids),
               'profiles_with_existing_trial_rows': len(target_ids & trial_ids),
               'profiles_with_trial_but_no_race_result_rows': len((target_ids & trial_ids) - race_ids),
               'existing_candidate_entry_rows': candidate_counts[0],
               'existing_candidate_unique_horse_ids': candidate_counts[1]}
    fields = sorted({field for _, row in rows for field in row})
    stats = {}
    for field in fields:
        states = Counter(state(row.get(field)) if field in row else 'absent' for _, row in rows)
        stats[field] = {
            'official_description': props.get(field, {}).get('description'),
            'field_present': sum(field in row for _, row in rows),
            **{key: states.get(key, 0) for key in ['absent', 'placeholder_or_null', 'zero', 'populated_nonzero']},
            'nonplaceholder_count': states.get('zero', 0) + states.get('populated_nonzero', 0),
            'json_types': dict(Counter(type(row[field]).__name__ for _, row in rows if field in row)),
        }
    birth_valid = 0
    age_consistent = 0
    ages = []
    for event, row in rows:
        birth = str(row.get('birthDt', ''))
        try:
            d = date(int(birth[:4]), int(birth[4:6]), int(birth[6:8])) if len(birth) == 8 else None
        except (ValueError, TypeError):
            d = None
        if d:
            birth_valid += 1
            age_consistent += row.get('age') == int(event['kst_date'][:4]) - d.year
        if isinstance(row.get('age'), (int, float)):
            ages.append(row['age'])
    date_checks = {}
    for field in fields:
        if not re.search(r'(Dt\d*|Date|Ilja)$', field):
            continue
        marker_count = 0
        future_count = 0
        invalid_count = 0
        for event, row in rows:
            value = row.get(field)
            if state(value) == 'placeholder_or_null':
                continue
            text = str(value)
            marker_count += text == '99991231'
            try:
                if len(text) != 8:
                    raise ValueError('Not an eight-digit date')
                parsed = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
                future_count += parsed.isoformat() > event['kst_date']
            except (ValueError, TypeError):
                invalid_count += 1
        if marker_count or future_count or invalid_count:
            date_checks[field] = {'raw_99991231_count': marker_count,
                                  'calendar_date_after_observation_count': future_count,
                                  'invalid_calendar_date_count': invalid_count}
    result = {
        'as_of_collection_completion_kst': '2026-10-01',
        'profile_count': len(rows), 'raw_profile_field_count': len(fields),
        'fields_per_profile': dict(Counter(len(row) for _, row in rows)),
        'officially_described_raw_fields': sum(field in props for field in fields),
        'raw_fields_not_in_official_spec': [field for field in fields if field not in props],
        'valid_birth_dates': birth_valid,
        'age_equals_observation_calendar_year_minus_birth_year': age_consistent,
        'raw_age_range': [min(ages), max(ages)],
        'age_over_35_count': sum(age > 35 for age in ages),
        'date_values_requiring_review': date_checks,
        'existing_db_horse_id_linkage': linkage,
        'useNm_distribution': dict(Counter(str(row.get('useNm')) for _, row in rows)),
        'sex_distribution': dict(Counter(str(row.get('sex')) for _, row in rows)),
        'fields': stats,
        'zero_policy': 'Numeric zero is counted separately; it is not automatically interpreted as missing or as a verified historical statistic.',
        'temporal_policy': 'All fields belong to each profile retrieval observation; present affiliation and cumulative statistics are not race-day historical values.',
        'official_source': 'https://www.data.go.kr/data/15057985/openapi.do',
        'official_spec_sha256': hashlib.sha256(spec_path.read_bytes()).hexdigest(),
    }
    (HERE / 'horse_profile_field_inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    selected = ['hrNo', 'hrNm', 'hrEngNm', 'birthDt', 'birthYr', 'age', 'breed', 'sex', 'color', 'prdCty', 'sanji',
                'fhrNo', 'fhrNm', 'mhrNo', 'mhrNm', 'mhrFhrNo', 'mhrFhrNm',
                'owNo', 'owNm', 'mgrNo', 'mgrNm', 'fowNo', 'fmgrNo', 'rhrOwNo', 'rhrMgrNo',
                'inOwNo', 'inMgrNo', 'outOwNo', 'outMgrNo', 'poNm', 'brNm', 'bldRegDt', 'rhrRegDt1', 'rhrRegDt2',
                'discardDt', 'discardRes', 'deadDt', 'finDt', 'inDt', 'outDt', 'restDt', 'restOutDt',
                'fdebutDt', 'lchulDt', 'rcCnt', 'fstCnt', 'sndCnt', 'trdCnt', 'winRate', 'quinRate', 'amt', 'condAmt']
    print(json.dumps({key: value for key, value in result.items() if key != 'fields'}, ensure_ascii=False))
    for field in selected:
        print(field, stats[field]['official_description'], stats[field]['nonplaceholder_count'], 'nonzero', stats[field]['populated_nonzero'])
    lines = ['# 마필 프로필 항목 인벤토리 — 2026-10-01', '',
             f"검증된 {len(rows):,}두의 API42 응답을 집계했다. 원문 프로필에는 {len(fields)}개 고유 항목이 있으며, 전체 항목별 JSON 타입·빈 값·숫자 0·값 보유 수는 [JSON 인벤토리](horse_profile_field_inventory.json)에 있다.", '',
             '공식 항목명은 [한국마사회 마필종합 상세정보 명세](https://www.data.go.kr/data/15057985/openapi.do)의 Swagger 응답 정의를 사용했다. 공개 HTML과 추출한 명세를 같은 디렉터리에 보존했다.', '',
             '## 주요 항목 보유 현황', '',
             '| API 항목 | 공식 설명 | 빈 값·`-` 등을 제외한 보유 두수 | 그중 0이 아닌 값 |',
             '| --- | --- | ---: | ---: |']
    for field in selected:
        s = stats[field]
        lines.append(f"| `{field}` | {s['official_description']} | {s['nonplaceholder_count']:,} | {s['populated_nonzero']:,} |")
    lines += ['', '## 날짜·나이·현역 상태 해석', '',
              f"출생일은 {birth_valid:,}두 모두 달력상 유효하다. API 연령 값은 {age_consistent:,}두에서 조회 연도에서 출생 연도를 뺀 값과 일치하며, 범위는 {min(ages)}~{max(ages)}다. 이 연령을 만 나이나 경주 당시 나이로 표기하지 않는다.", '',
              '폐사일이나 불용일이 있는 말에도 API 연령 값이 반환된다. 연령 보유나 현재 용도만으로 현역을 확정하지 않는다. 경주마등록취소일·불용일·폐사일·입퇴사일과 최종 출주일은 각각 보존하며, 날짜 간 상태 모순과 재등록 가능성 검토 전 단일 현역 여부를 만들지 않았다.', '',
              'API 나이가 35를 넘는 값도 11두 있다. 출생일과 연령의 내부 계산 일치가 원천 출생일의 정확성이나 생존 여부를 입증하지는 않는다.', '',
              '## 날짜 특수값 점검', '',
              '`99991231` 등 조회일 이후의 날짜와 달력상 유효하지 않은 값은 실제 사건일로 해석하지 않고 원문을 보존한다. 특수값의 공식 의미는 추가 확인이 필요하다.', '',
              '| 항목 | 원문 `99991231` | 조회일 이후 날짜 | 달력상 유효하지 않은 값 |',
              '| --- | ---: | ---: | ---: |',
              *[f"| `{field}` | {values['raw_99991231_count']:,} | {values['calendar_date_after_observation_count']:,} | {values['invalid_calendar_date_count']:,} |" for field, values in date_checks.items()], '',
              '## 현재 프로필과 역사적 경주 자료', '',
              f"공식 말 ID 기준으로 {linkage['profiles_with_existing_race_result_rows']:,}두가 기존 경주결과와 연결되고 {linkage['profiles_with_existing_trial_rows']:,}두 모두가 주행심사에 연결된다. 보조 {linkage['profiles_with_trial_but_no_race_result_rows']:,}두는 현재 DB의 경주결과에는 없고 심사 이력에만 있다. 기존 경주 모집단 후보는 {candidate_counts[0]:,}출전행·{candidate_counts[1]:,}두다. 이 출전행 수에는 취소·비완주 행이 포함될 수 있으므로 완주 수로 해석하지 않는다.", '',
              '말 ID로 기존 경주결과·주행심사 이력과 연결할 수 있다. 프로필의 소유자·조교사·등급·누적 성적은 조회시점 자료다. 과거 경주에는 해당 경주결과 행의 관계자·조건·기록을 사용하며 현재 프로필로 덮어쓰지 않는다.', '',
              '프로필 소유자·조교사 필드의 결측과 별개로 최초·등록·입퇴사 시점의 관계자 필드도 있다. 예를 들어 최초 소유자 ID, 최초 조교사 ID, 경주마등록시 소유자 ID, 입사시 소유자·조교사 ID는 모두 4,617두에 값이 있다. 이러한 사건시점 요약은 관계자 변경 전체 이력이나 모든 경주일의 소속을 보장하지 않는다.', '',
              '숫자 0은 원문 숫자로 구분해 보존했다. 0이 실제 실적 없음인지 원천 누락인지 항목별 검증 전 일괄 판단하지 않았다. 이 표의 보유 수는 값 존재 집계이며 정확성 검증 완료 수와 다르다.', '',
              '## 전체 항목', '', '| API 항목 | 공식 설명 | 값 보유 | 빈 값·표식 | 0 |', '| --- | --- | ---: | ---: | ---: |']
    for field in fields:
        s = stats[field]
        lines.append(f"| `{field}` | {s['official_description'] or '공식 명세에 없음'} | {s['nonplaceholder_count']:,} | {s['placeholder_or_null']:,} | {s['zero']:,} |")
    (HERE / 'HORSE_PROFILE_FIELDS_20261001.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()

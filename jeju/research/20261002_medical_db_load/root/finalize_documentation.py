"""Record the verified native DB load and its input contract."""
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC,datetime
from pathlib import Path

PROJECT=Path('/Users/kimyongjin/Desktop/horse_racing')
FINAL=PROJECT/'jeju/research/20261002_medical_db_load'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def atomic(path,content):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
        tmp=Path(f.name);f.write(content.encode());f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def main():
    root=FINAL/'root'
    reports={}
    for file in ['root_production_source_verification.json','root_production_profiles_dictionary_verification.json','root_production_existing_data_verification.json']:
        value=json.loads((root/file).read_text());assert value['all_passed'];reports[file]=value
    source=reports['root_production_source_verification.json']
    profile=reports['root_production_profiles_dictionary_verification.json']
    before=json.loads((root/'root_before_load.json').read_text())
    db=PROJECT/'jeju/data/jeju_native_core.sqlite3'
    current_sha=sha(db)
    conn=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
    tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    assert all(t.isidentifier() for t in tables)
    counts={t:conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
    conn.close()
    summary={'status':'loaded_and_independently_verified','verified_at_utc':datetime.now(UTC).isoformat(),
             'database':'jeju/data/jeju_native_core.sqlite3','database_sha256':current_sha,
             'before_production_file_sha256':before['production_file_sha256'],
             'backup_database':'root/before_load.sqlite3','backup_sha256':before['database_sha256'],
             'backup_build_manifest':'root/before_load.build_manifest.json','backup_manifest_sha256':before['manifest_sha256'],
             'medical_rows':source['loaded_rows'],'medical_horses':source['loaded_horses'],
             'analysis_rows':source['analysis_rows'],'analysis_horses':source['analysis_horses'],
             'analysis_cutoff':'2026-09-19','raw_after_cutoff':source['raw_rows_after_cutoff'],
             'current_profile_population':profile['profile_population'],'new_profiles':profile['new_profiles_checked'],
             'existing_tables_preserved':16,'model_input_adoption':False,'history_completeness':'unconfirmed',
             'historical_publication_time':'unconfirmed','txt_medical_rows_loaded':0,
             'table_counts':counts,'verification_reports':list(reports)}
    atomic(FINAL/'summary.json',json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    atomic(FINAL/'README.md',(root/'FINAL_README.md').read_text())
    manifest=PROJECT/'jeju/data/jeju_native_core.build_manifest.json'
    old=json.loads(manifest.read_text())
    assert sha(manifest)==before['manifest_sha256']
    old['medical_api_load_20261002']=summary
    old['current_table_counts_after_medical_load_20261002']=counts
    old['original_build_fields_note']='Original 2026-09-29 build fields are historical; subsequent load sections and current table counts describe the active DB.'
    atomic(manifest,json.dumps(old,ensure_ascii=False,indent=2)+'\n')
    agents=PROJECT/'jeju/AGENTS.md'
    text=agents.read_text()
    section='''### 진료 API16 적재 및 입력 기준

- 진료 조회·재적재·집계는 [적재·독립 검증 보고서](research/20261002_medical_db_load/README.md)를 먼저 읽는다. 원문 연결 테이블은 `medical_api_rows`(12,030행·944두), 2026년 분석 조회는 `medical_api_rows_analysis_2026`(2026-09-19까지 11,991행·939두)이다. API42 미연결 81두의 현재 제주마 프로필을 추가해 최신 프로필은 4,718두다. 현재 프로필 품종을 과거 진료일의 품종 확정으로 해석하지 않는다.
- 원문 날짜·마명·병원·두 진료 문구·part·JSON 타입과 item 위치를 보존한다. `part` 의미는 미확정이며 식별자로 사용하지 않는다. 같은 내용의 반복행과 같은 날 복수행을 유지하고 원문 행 수를 진료 횟수로 단정하지 않는다. 재적재는 source artifact와 1부터 시작하는 item 위치로 막는다.
- `medical_api_diagnosis_slots`는 원문 두 슬롯이며, 검토·구성요소·설명 조회는 각각 `medical_api_diagnosis_slot_review`, `medical_api_diagnosis_components`, `medical_api_diagnosis_explanation_terms`로 분리한다. 1:N 설명 조인으로 출전키·진료 원행을 증식시키지 않는다. 공유 사전은 진료 사건이 아니며 TB의 진료 사건을 편입하지 않았다.
- API33 설명 `-`를 설명문으로 쓰지 않는다. 실제 확보한 공식 설명만 출처와 함께 사용한다. 접두어 파서 의존 356개와 사건 조건부 8개 규칙은 일반 연결에서 차단한다. 제외·미검토·설명 미확보 문구는 원문과 감사 상태를 보존한다. 진료 `-`는 unknown/NULL이며 건강함·미진료로 해석하지 않는다. 재료판매·검사·장제·예방·처치 문구를 질병으로 자동 분류하지 않는다.
- 최신 이름과 2026년 고정 나이는 기존 사용자 지정 정책을 따른다. `clinicDate`는 사건 날짜이며 공개시각은 미확정이다. 미래 경주 연결에는 최소 `clinic_date < race_date`와 공개시각 미확정을 적용하고 기존 모델 입력에 자동 반영하지 않는다. 과거 API 0행은 진료가 없었다는 증거가 아니다. 공식 말 ID가 확인되지 않은 제주 TXT는 보완 후보이며 이번 확정 ID 연결 테이블에 편입하지 않았다. 제외 말은 재편입하지 않는다.

'''
    assert '### 진료 API16 적재 및 입력 기준' not in text
    marker='### 2026-10-01 사용자 지정 이름·나이 분석 기준'
    assert marker in text
    atomic(agents,text.replace(marker,section+marker,1))
    print(json.dumps({k:summary[k] for k in ['status','medical_rows','analysis_rows','current_profile_population','database_sha256']},ensure_ascii=False))


if __name__=='__main__':main()

"""Publish reviewed local artifacts and preserve the independent backup pair."""
import hashlib
import json
import shutil
from pathlib import Path

PROJECT=Path('/Users/kimyongjin/Desktop/horse_racing')
STAGE=Path('/private/tmp/jeju_medical_20261002')
FINAL=PROJECT/'jeju/research/20261002_medical_db_load'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def main():
    assert not FINAL.exists(), 'Refuse to overwrite a previous published run.'
    before=json.loads((STAGE/'root/root_before_load.json').read_text())
    db=PROJECT/'jeju/data/jeju_native_core.sqlite3'
    manifest=PROJECT/'jeju/data/jeju_native_core.build_manifest.json'
    assert sha(db)==before['production_file_sha256'], 'Production DB changed since the independent baseline.'
    assert sha(manifest)==before['manifest_sha256'], 'Build manifest changed since the independent baseline.'
    for report in ['root_staging_source_verification.json','root_staging_profiles_dictionary_verification.json']:
        assert json.loads((STAGE/'root'/report).read_text())['all_passed']
    assert json.loads((STAGE/'root/root_credential_scan.json').read_text())['all_passed']
    review=json.loads((STAGE/'review/code_review.json').read_text())
    assert review['outcome']=='no_blocking_code_findings'
    for item in review['artifacts']:
        assert sha(Path(item['path']))==item['sha256'], 'Reviewed code changed.'
    replay=json.loads((STAGE/'load/staging_replay_report.json').read_text())
    assert replay['all_passed'], 'Staging replay was not verified.'
    FINAL.mkdir(parents=True)
    for path in (STAGE/'load').iterdir():
        if path.is_file() and path.suffix in ('.py','.sql','.json','.md'):
            shutil.copy2(path,FINAL/path.name)
    for folder in ['stage_v4','stage_v4_reapply']:
        src=STAGE/'load'/folder
        if src.exists():
            shutil.copytree(src,FINAL/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.sqlite3*'))
    for folder in ['profile_collection','history_gap_review','review']:
        src=STAGE/folder
        if src.exists():
            shutil.copytree(src,FINAL/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(STAGE/'root',FINAL/'root',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    assert sha(FINAL/'root/before_load.sqlite3')==before['database_sha256']
    assert sha(FINAL/'root/before_load.build_manifest.json')==before['manifest_sha256']
    publication={'published_to':str(FINAL),'production_database_modified':False,
                 'backup_sha256':before['database_sha256'],'backup_manifest_sha256':before['manifest_sha256'],
                 'production_precondition_sha256':before['production_file_sha256']}
    (FINAL/'artifact_publication.json').write_text(json.dumps(publication,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(publication,ensure_ascii=False))


if __name__=='__main__':main()

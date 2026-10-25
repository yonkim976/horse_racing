"""Read-only integrity check of this study, pinned sources and protected assets."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
STUDY=HERE.parent
ROOT=HERE.parents[3]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4194304),b''):h.update(block)
    return h.hexdigest()


def main():
    manifest=STUDY/'FINAL_MANIFEST.json'
    data=json.loads(manifest.read_text())
    for item in data['files_excluding_manifest']+data['preserved_source_references']:
        path=(ROOT/item['path']).resolve(strict=True)
        assert path.is_relative_to(ROOT),item['path']
        assert path.stat().st_size==item['bytes'],item['path']+' size'
        assert sha(path)==item['sha256'],item['path']+' SHA'
    paths=[p for p in STUDY.rglob('*') if p.is_file()]
    assert len(paths)==data['file_count_including_manifest']
    assert sum(p.stat().st_size for p in paths)==data['new_study_bytes_including_manifest']
    assert manifest.stat().st_size==data['manifest_bytes']
    assert data['new_study_bytes_including_manifest']<=data['study_budget_bytes']
    assert data['session_bytes_including_manifest']<=data['session_budget_bytes']
    print(json.dumps({'passed':True,'study_files':len(paths),
                      'source_references_checked':len(data['preserved_source_references']),
                      'new_bytes':data['new_study_bytes_including_manifest'],
                      'session_bytes':data['session_bytes_including_manifest'],
                      'manifest_sha256':sha(manifest)},indent=2))


if __name__=='__main__':main()

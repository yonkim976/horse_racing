"""Read-only check of all sealed study artifacts, inputs and storage accounting."""
import json

from preservation import ROOT, STUDY, sha


def main():
    path = STUDY / 'FINAL_MANIFEST.json'
    manifest = json.loads(path.read_text())
    for item in manifest['files_excluding_manifest'] + manifest['preserved_source_references']:
        source = (ROOT / item['path']).resolve(strict=True)
        assert source.is_relative_to(ROOT)
        assert source.stat().st_size == item['bytes'], item['path']
        assert sha(source) == item['sha256'], item['path']
    files = [p for p in STUDY.rglob('*') if p.is_file()]
    assert len(files) == manifest['file_count_including_manifest']
    size = sum(p.stat().st_size for p in files)
    assert size == manifest['new_study_bytes_including_manifest'] <= manifest['study_budget_bytes']
    assert path.stat().st_size == manifest['manifest_bytes']
    assert manifest['session_bytes_including_manifest'] == size + manifest['prior_session_bytes']
    assert manifest['session_bytes_including_manifest'] <= manifest['session_budget_bytes']
    print(json.dumps({'passed': True, 'study_files': len(files), 'new_bytes': size,
                     'session_bytes': manifest['session_bytes_including_manifest'],
                     'source_pins_checked': len(manifest['preserved_source_references']),
                     'manifest_sha256': sha(path)}, indent=2))


if __name__ == '__main__':
    main()

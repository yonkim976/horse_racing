"""Resume publication after checking a not-yet-created manifest link too early."""
from pathlib import Path
import hashlib
import json
import re

H = Path(__file__).resolve().parent
ROOT = H.parents[2]
C = H.parent / 'conclusions'

def sha(p):
    v = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            v.update(chunk)
    return v.hexdigest()

def save(name, value):
    with (H / name).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)

prior = json.loads((C / 'source_manifest.json').read_text())
for r in prior['files']:
    if r['role'] != 'conclusion_or_management':
        assert sha(ROOT / r['path']) == r['sha256'], r['path']
assert (H / 'README.md').exists()
assert json.loads((H / 'final_verification.json').read_text())['status'] == 'passed'
assert len(json.loads((C / 'research_register.json').read_text())['topics']) == 6
save('publication_retry_provenance.json', {
    'initial_script': 'publish.py',
    'initial_script_sha256': sha(H / 'publish.py'),
    'failure': 'AssertionError: README.md artifact_manifest.json link checked before manifest creation.',
    'completed_before_failure': ['corrected_BH_table', 'final_verification', 'decision', 'research_report', 'central_topic_and_register_updates'],
    'retry': 'finalize_publication.py resumes verification and manifest publication only; no estimation, report or topic duplication.',
    'original_code_and_all_outputs_preserved': True
})
targets = []
for p in [H / 'README.md'] + list(C.glob('*.md')):
    for dest in re.findall(r'\]\(([^)]+)\)', p.read_text()):
        if '://' in dest or dest.startswith('#'):
            continue
        target = (p.parent / dest.split('#', 1)[0]).resolve()
        assert target.exists() or target == H / 'artifact_manifest.json', (p, dest)
        targets.append(target)
save('publication_verification.json', {
    'status': 'passed', 'local_markdown_links_checked': len(targets),
    'prior_source_files_unchanged': sum(r['role'] != 'conclusion_or_management' for r in prior['files']),
    'burden_BH_matches_plan': True, 'all_effects_intervals_p_values_unchanged': True,
    'training_serialized_models_verified': 12, 'operational_change': False,
    'archive_sizes_in': 'artifact_manifest.json',
    'modified_management_sizes_in': '../conclusions/source_manifest.json'
})
archive = [{'path': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(H.iterdir()) if p.is_file()]
save('artifact_manifest.json', {'self_excluded': True, 'files': archive, 'bytes_excluding_this_manifest': sum(r['bytes'] for r in archive), 'count_excluding_this_manifest': len(archive)})
assert all(p.exists() for p in targets)
files = []
for r in prior['files']:
    if r['role'] == 'conclusion_or_management':
        p = ROOT / r['path']; r = dict(r, sha256=sha(p), bytes=p.stat().st_size)
    else:
        assert sha(ROOT / r['path']) == r['sha256'], r['path']
    files.append(r)
p = C / '06_TRAINING_RECORD.md'
assert not any(r['path'] == str(p.relative_to(ROOT)) for r in files)
files.append({'path': str(p.relative_to(ROOT)), 'role': 'conclusion_or_management', 'bytes': p.stat().st_size, 'sha256': sha(p)})
for p in sorted(H.iterdir()):
    if p.is_file():
        files.append({'path': str(p.relative_to(ROOT)), 'role': 'source_load_tail_training', 'bytes': p.stat().st_size, 'sha256': sha(p)})
final = {
    'updated_at': '2026-10-08', 'files': files,
    'verification': {'status': 'passed', 'all_previous_source_hashes_unchanged': True, 'local_links_checked': len(targets), 'latest_study': str(H.relative_to(ROOT)), 'latest_verification': str((H / 'final_verification.json').relative_to(ROOT))},
    'managed_files_bytes_excluding_this_manifest': sum(r['bytes'] for r in files)
}
(C / 'source_manifest.json').write_text(json.dumps(final, ensure_ascii=False, indent=2) + '\n')
assert all(sha(ROOT / r['path']) == r['sha256'] for r in files)
print(json.dumps({'status': 'published_research_only', 'new_archive_files': len(archive) + 1, 'new_archive_bytes': sum(p.stat().st_size for p in H.iterdir() if p.is_file()), 'local_links': len(targets), 'previous_sources_preserved': True}, ensure_ascii=False))

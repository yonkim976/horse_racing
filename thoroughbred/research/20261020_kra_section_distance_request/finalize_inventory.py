"""Verify protected inputs and account for this document-only follow-up."""

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
CENTRAL = R / 'conclusions/57D_KRA_SECTION_DISTANCE_REQUEST.md'
MARKER = '<!-- kra_section_distance_request_20261020 -->'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    inputs = json.loads((OUT / 'input_manifest.json').read_text())
    for name, expected in inputs.items():
        p = ROOT / name
        assert p.stat().st_size == expected['bytes'] and sha(p) == expected['sha256'], name

    # Local Markdown references must resolve; URLs are source citations, not fetched here.
    md_files = sorted(HERE.glob('*.md')) + [CENTRAL]
    count = 0
    for p in md_files:
        for link in re.findall(r'\]\(([^)]+)\)', p.read_text()):
            if '://' in link or link.startswith('#'):
                continue
            target = p.parent / link.split('#')[0]
            if target.name in {'verification.json', 'artifact_inventory.json'}:
                continue
            assert target.exists(), (p, link)
            count += 1
    save(OUT / 'verification.json', dict(
        status='inquiry_preparation_complete_distance_confirmation_pending',
        checked_on='2026-10-20', protected_inputs=len(inputs), protected_inputs_unchanged=True,
        local_links_checked=count, exact_corner_distances_newly_confirmed=0,
        unresolved_corner_points=['1C', '2C', '3C', '4C'],
        no_document_absence_claim=True, exhaustive_procurement_search=False,
        message_submitted=False, information_disclosure_submitted=False,
        database_access=False, models_changed=0, web_changes=0, deployed=False))

    source_manifest = R / 'conclusions/source_manifest.json'
    source_doc = json.loads(source_manifest.read_text())
    paths = sorted(p for p in HERE.rglob('*') if p.is_file()
                   and '__pycache__' not in p.parts
                   and p.name not in {'artifact_inventory.json'}) + [CENTRAL] + [
                       R / name for name in ['README.md', 'conclusions/README.md',
                                             'conclusions/SOURCES.md']]
    for p in paths:
        name = str(p.relative_to(ROOT))
        source_doc['sources'] = [x for x in source_doc['sources'] if x['path'] != name]
        source_doc['sources'].append(dict(path=name, sha256=sha(p), bytes=p.stat().st_size))
    source_doc['kra_section_distance_request_note'] = (
        '2026-10-20 연구57D. 공개 검색에서1800m 코너 계측명세 미확보;'
        '부존재 판정 아님. 문의서/자료요청표 준비, 미제출, 새 거리/모델/운영 변경 없음.')
    save(source_manifest, source_doc)

    before = json.loads((OUT / 'publication_before.json').read_text())
    inv = OUT / 'artifact_inventory.json'
    size_log = R / 'ARTIFACT_SIZE_LOG.md'
    original = ''.join(line for line in size_log.read_text().splitlines(keepends=True)
                       if MARKER not in line).rstrip() + '\n'
    inv.touch(exist_ok=True)
    previous = None
    for _ in range(30):
        files = sorted(p for p in HERE.rglob('*') if p.is_file()
                       and '__pycache__' not in p.parts) + [CENTRAL]
        rows = [dict(path=str(p.relative_to(ROOT)), bytes=p.stat().st_size,
                     sha256=None if p == inv else sha(p)) for p in files]
        total = sum(x['bytes'] for x in rows)
        size_log.write_text(original + (
            f'\n| 2026-10-20 | 서울1800 공식 계측명세 탐색·문의 준비 | {len(rows)} | {total} | '
            f'{total / 1048576:.6f} | {len(before)} | 명세 참조 | 명세 참조 | '
            f'[명세]({HERE.name}/outputs/artifact_inventory.json) | {MARKER}\n'))
        modified = [dict(path=name, before_bytes=old['bytes'],
                         bytes=(ROOT / name).stat().st_size,
                         delta_bytes=(ROOT / name).stat().st_size - old['bytes'],
                         sha256=sha(ROOT / name)) for name, old in before.items()]
        save(inv, dict(new_file_count=len(rows), new_bytes=total,
                       new_mib=f'{total / 1048576:.6f}', new_files=rows,
                       modified_file_count=len(modified),
                       modified_delta_bytes=sum(x['delta_bytes'] for x in modified),
                       modified_files=modified, inventory_self_hash_omitted=True))
        current = (total, inv.stat().st_size)
        if current == previous:
            break
        previous = current
    else:
        raise AssertionError('Inventory did not converge')
    data = json.loads(inv.read_text())
    for x in data['new_files'] + data['modified_files']:
        p = ROOT / x['path']
        assert p.stat().st_size == x['bytes'], x['path']
        assert x['sha256'] is None or sha(p) == x['sha256'], x['path']
    assert sum(x['bytes'] for x in data['new_files']) == data['new_bytes']
    for p in paths:
        row = next(x for x in source_doc['sources'] if x['path'] == str(p.relative_to(ROOT)))
        assert sha(p) == row['sha256']
    print(json.dumps(dict(new_file_count=data['new_file_count'], new_bytes=data['new_bytes'],
                          new_mib=data['new_mib'], modified_delta_bytes=data['modified_delta_bytes'],
                          largest=max(data['new_files'], key=lambda x: x['bytes'])), ensure_ascii=False))


if __name__ == '__main__':
    main()

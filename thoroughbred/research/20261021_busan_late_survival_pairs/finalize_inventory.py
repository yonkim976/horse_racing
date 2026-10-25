"""Verify protected inputs, local links and retained follow-up artifacts."""

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
CENTRAL = R / 'conclusions/57K_BUSAN_LATE_SURVIVAL_PAIRS.md'
MARKER = '<!-- busan_late_survival_pairs_20261021 -->'


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


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
    verification_path = OUT / 'verification.json'
    verification = json.loads(verification_path.read_text())
    verification['local_links_checked'] = count
    save(verification_path, verification)

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
    source_doc['busan_late_survival_pairs_note'] = (
        '2026-10-21 연구57K. 부산 종반생존/동반입상 편향 진단 및47연구모형.'
        '1976경주;종반예측축+4/복승+3불확실,관계쌍복연-18·운영유지.')
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
            f'\n| 2026-10-21 | 부산 종반생존·동반입상 편향 진단 및 모델 추가 | {len(rows)} | {total} | '
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

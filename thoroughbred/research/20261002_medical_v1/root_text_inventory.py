"""Independent count of all dated raw Text lines, without interpreting diagnosis."""
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TEXT = ROOT / 'data/raw/kra_text/dacom72'
START, END = date(2010, 1, 1), date(2026, 9, 29)
DATED = re.compile(r'^\s*(\d{4})[./-](\d{2})[./-](\d{2})(?:\s|$)')


def main():
    files, counts, non_dated, layout = [], Counter(), Counter(), Counter()
    for meet in ('1', '3'):
        for year in range(2010, 2027):
            for path in sorted((TEXT / f'meet={meet}' / f'year={year}').rglob('*.rpt')):
                raw = path.read_bytes()
                text = raw.decode('cp949', errors='replace')
                item = {'raw_path': str(path.relative_to(ROOT)), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                        'meet': meet, 'path_year': year, 'scoped_dated_lines': 0, 'outside_dated_lines': 0,
                        'invalid_date_lines': [], 'undated_nonempty_lines': 0,
                        'replacement_character_count': text.count('\ufffd')}
                for number, line in enumerate(text.splitlines(), 1):
                    encoded = line.encode('cp949')
                    layout['raw_lines'] += 1
                    layout['length_145_bytes'] += len(encoded) == 145
                    layout['separators_at_10_31_44'] += all(encoded[n:n+1] == b' ' for n in (10, 31, 44))
                    for a, b in ((0, 10), (11, 29), (29, 31), (32, 44), (45, len(encoded))):
                        encoded[a:b].decode('cp949')
                    match = DATED.match(line)
                    if match:
                        try:
                            event = date(*(int(v) for v in match.groups()))
                        except ValueError:
                            item['invalid_date_lines'].append(number)
                            continue
                        key = 'scoped_dated_lines' if START <= event <= END else 'outside_dated_lines'
                        item[key] += 1
                        if key == 'scoped_dated_lines':
                            counts[(meet, event.year)] += 1
                    elif line.strip():
                        item['undated_nonempty_lines'] += 1
                        non_dated[line[:100]] += 1
                files.append(item)
    result = {'files': files, 'source_file_count': len(files),
              'scoped_dated_lines': sum(f['scoped_dated_lines'] for f in files),
              'scoped_lines_by_meet_year': {f'{m}:{y}': n for (m, y), n in sorted(counts.items())},
              'outside_dated_lines': sum(f['outside_dated_lines'] for f in files),
              'invalid_date_line_count': sum(len(f['invalid_date_lines']) for f in files),
              'replacement_character_count': sum(f['replacement_character_count'] for f in files),
              'undated_nonempty_lines': sum(f['undated_nonempty_lines'] for f in files),
              'undated_line_examples': non_dated.most_common(20), 'fixed_width_layout': dict(layout),
              'fixed_width_cells_cp949_decodable': True}
    assert layout['raw_lines'] == layout['length_145_bytes'] == layout['separators_at_10_31_44']
    (HERE / 'root_text_inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, ensure_ascii=False))


if __name__ == '__main__':
    main()

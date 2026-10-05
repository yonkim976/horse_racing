"""Independent source-coordinate, physical-byte, header and capture audit."""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = HERE / 'rpt_mapping'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@lru_cache(maxsize=8)
def raw(path):
    target = (ROOT / path).resolve()
    assert target.is_relative_to(ROOT)
    return target.read_bytes()


def main():
    captures = defaultdict(set)
    for line in (ROOT / 'data/raw/kra_text/_manifests/dacom11/manifest.jsonl').read_text().splitlines():
        row = json.loads(line)
        if row.get('status') == 'downloaded' and row.get('local_path') and row.get('sha256') and row.get('retrieved_at_ms'):
            captures[(row['local_path'], row['sha256'])].add(datetime.fromtimestamp(row['retrieved_at_ms']/1000, timezone.utc))
    manifest = json.loads((SOURCE / 'manifest.json').read_text())
    for item in manifest['outputs']:
        assert sha(SOURCE / item['path']) == item['sha256']
    expected = pq.read_table(HERE / 'root_expected_rpt_points.parquet').to_pylist()
    keys = {(row['source_path'], row['line_no']): row for row in expected}
    points = pq.read_table(SOURCE / 'rpt_point_observations.parquet').to_pylist()
    headers = pq.read_table(SOURCE / 'rpt_race_headers.parquet').to_pylist()
    files = pq.read_table(SOURCE / 'rpt_source_files.parquet').to_pylist()
    seen = set()
    states = Counter()
    for row in points:
        key = (row['source_path'], row['source_line_no'])
        assert key in keys and key not in seen
        seen.add(key)
        original = keys[key]
        for field, other in [('actual_meet_code','actual_meet_code'), ('event_date','race_date_iso'), ('race_no','race_no'), ('print_label_raw','point_label_raw'), ('source_sha256','source_sha256'), ('source_line_byte_offset','byte_offset'), ('raw_line_text','raw_line')]:
            assert row[field] == original[other], (field, key)
        assert row['notation_raw'].strip(' ') == original['notation_trim']
        literal = raw(row['source_path'])
        offset = row['source_line_byte_offset']
        physical = literal[offset:offset+row['source_line_byte_length']]
        assert physical.hex() == row['raw_line_bytes_hex']
        body = physical.rstrip(b'\r\n')
        assert body.decode('cp949') == row['raw_line_text']
        assert body[row['colon_byte_offset_in_line']+1:].hex() == row['notation_raw_bytes_hex']
        assert bytes.fromhex(row['notation_raw_bytes_hex']).decode('cp949') == row['notation_raw']
        states[row['notation_state']] += 1
    assert len(seen) == len(expected) == 111467
    for row in headers:
        literal = raw(row['source_path'])
        assert hashlib.sha256(literal).hexdigest() == row['source_sha256']
        for prefix in ('title', 'venue'):
            physical = bytes.fromhex(row[prefix+'_line_bytes_hex'])
            offset = row[prefix+'_byte_offset']
            assert literal[offset:offset+len(physical)] == physical
            assert physical.rstrip(b'\r\n').decode('cp949') == row[prefix+'_line_raw']
    capture_counts = Counter()
    for row in [*files, *headers, *points]:
        times = captures[(row['source_path'],row['source_sha256'])]
        value = row['source_captured_at_utc']
        assert (value is not None) == bool(times), row['source_path']
        if value is not None:
            assert datetime.fromisoformat(value) in times
        capture_counts['with_timestamp' if value is not None else 'unknown'] += 1
    assert len(files) == 1827 and len(headers) == 17371
    result = {'all_passed':True,'source_files':len(files),'race_headers':len(headers),'point_lines':len(points),'notation_states':dict(states),'capture_status_rows':dict(capture_counts),'verification_script_sha256':sha(Path(__file__))}
    (HERE / 'root_rpt_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Read-only passing-group inventory against the confirmed research race set."""
import collections
import csv
import hashlib
import json
from pathlib import Path
import re

import duckdb

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
VENUES = {'서울': 1, '부산경남': 3, '영천': 4}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    core = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
    snap = ROOT / 'thoroughbred/data/section_passing_raw_2010plus_20260929_v1/section_passing_raw.duckdb'
    con = duckdb.connect(str(core), read_only=True)
    confirmed = {(VENUES[v], d, int(n)) for v, d, n in con.execute(
        'SELECT actual_venue_label_raw,race_date::VARCHAR,result_race_no_key FROM confirmed_races').fetchall()}
    con.close()
    con = duckdb.connect(str(snap), read_only=True)
    snap_rows = con.execute('''SELECT c.meet_code,c.race_date,c.race_number,
        p.point_code,p.notation_raw FROM op_race_passing_groups p
        JOIN op_race_context c USING(race_id)''').fetchall()
    con.close()
    valid_snap = [r for r in snap_rows if r[4] is not None and r[4].strip() not in ('','-','X')]
    snap_keys = {(int(m),d,int(n)) for m,d,n,_,_ in valid_snap}
    snap_groups = collections.Counter((int(m),d,int(n),point) for m,d,n,point,_ in valid_snap)
    text_headers, text_keys = set(),set()
    text_files = collections.Counter()
    text_group_lines, text_invalid_groups = 0,0
    header_re = re.compile(r'^제목\s*:\s*(\d{2,4})년(\d{1,2})월(\d{1,2})일.*?제\s*(\d+)\s*경주')
    point_re = re.compile(r'(S-?1F|C[1-4]|G-?(?:8|6|4|3|2|1)F)\s*:\s*(.*?)\s*$')
    decoding_errors,header_errors,header_date_disagreements = [],[],[]
    venue_aliases = {'서울':1, '부산':3, '부경':3, '부산경남':3, '영천':4}
    venue_bridges = []
    unknown_venues = []
    text_file_evidence = []
    for path in sorted((ROOT/'data/raw/kra_text/dacom11').rglob('*.rpt')):
        meta = re.search(r'meet=(\d+)/year=(\d+)',path.as_posix())
        if not meta or int(meta[1]) not in (1,3,4) or not 2010 <= int(meta[2]) <= 2026:
            continue
        meet = int(meta[1])
        raw = path.read_bytes()
        try:
            literal = raw.decode('cp949')
        except UnicodeDecodeError:
            decoding_errors.append(path.relative_to(ROOT).as_posix())
            continue
        current = None
        pending = None
        file_groups = 0
        for line_no,line in enumerate(literal.splitlines(),1):
            if line.startswith('제목') and '경주' in line:
                match = header_re.search(line)
                if not match:
                    header_errors.append({'path':path.relative_to(ROOT).as_posix(),'line':line_no,'literal':line})
                    current = None
                    continue
                year,month,day,number = map(int,match.groups())
                if year < 100: year += 2000
                date = f'{year:04d}-{month:02d}-{day:02d}'
                if date.replace('-','') != path.name[:8]:
                    header_date_disagreements.append({'path':path.relative_to(ROOT).as_posix(),'date':date,'line':line_no})
                current = None
                pending = (date,number) if '2010-01-01'<=date<='2026-09-29' else None
            venue = re.match(r'^\(([^)]+)\)\s*제\s*\d+일',line)
            if venue and pending:
                actual_meet = venue_aliases.get(venue[1])
                if actual_meet is None:
                    unknown_venues.append({'path':path.relative_to(ROOT).as_posix(),'line':line_no,'venue_raw':venue[1]})
                    current = None
                else:
                    current = (actual_meet,*pending)
                    text_headers.add(current)
                    if actual_meet != meet:
                        venue_bridges.append({'path':path.relative_to(ROOT).as_posix(),'line':line_no,
                            'source_path_meet':meet,'actual_meet':actual_meet,'venue_raw':venue[1],
                            'date':pending[0],'race_no':pending[1]})
            group = point_re.search(line)
            if group and current:
                if group[2].strip() in ('','-','X'):
                    text_invalid_groups += 1
                else:
                    text_keys.add(current)
                    text_group_lines += 1
                    file_groups += 1
        text_files[(meet,int(meta[2]))] += 1
        text_file_evidence.append({'path':path.relative_to(ROOT).as_posix(),
            'sha256':hashlib.sha256(raw).hexdigest(),'nonempty_point_lines':file_groups})
    local_available = snap_keys|text_keys
    coverage = []
    for (meet,year),total in sorted(collections.Counter((m,int(d[:4])) for m,d,_ in confirmed).items()):
        keys = {key for key in confirmed if key[0]==meet and key[1].startswith(str(year))}
        coverage.append({'meet':meet,'year':year,'confirmed_races':total,
            'snapshot_nonempty_races':len(keys&snap_keys),'rpt_race_headers':len(keys&text_headers),
            'rpt_nonempty_group_races':len(keys&text_keys),'local_either_source_present':len(keys&local_available),
            'local_source_gap':len(keys-local_available)})
    missing = [{'meet':m,'date':d,'race_no':n} for m,d,n in sorted(confirmed-local_available)]
    with (OUT/'passing_local_gaps.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['meet','date','race_no']);writer.writeheader();writer.writerows(missing)
    report={'status':'local_presence_inventory_only','core_source_sha256':sha(core),
        'snapshot_source_sha256':sha(snap),'confirmed_races':len(confirmed),
        'snapshot_rows':len(snap_rows),'snapshot_nonempty_rows':len(valid_snap),
        'snapshot_nonempty_race_keys':len(snap_keys),'snapshot_unmatched_confirmed_keys':len(snap_keys-confirmed),
        'snapshot_duplicate_race_point_keys':sum(n>1 for n in snap_groups.values()),
        'rpt_files':len(text_file_evidence),'rpt_header_races':len(text_headers),
        'rpt_nonempty_group_races':len(text_keys),'rpt_nonempty_point_lines':text_group_lines,
        'rpt_blank_or_placeholder_point_lines':text_invalid_groups,'rpt_decode_errors':decoding_errors,
        'rpt_header_errors':header_errors,'rpt_header_file_date_disagreements':header_date_disagreements,
        'rpt_actual_venue_bridges':venue_bridges,'rpt_unknown_actual_venues':unknown_venues,
        'rpt_file_counts_by_year_meet':[{'meet':m,'year':y,'files':n} for (m,y),n in sorted(text_files.items())],
        'rpt_unmatched_confirmed_keys':len(text_keys-confirmed),
        'rpt_noncore_keys':[{'meet':m,'date':d,'race_no':n} for m,d,n in sorted(text_keys-confirmed)],'coverage':coverage,
        'local_confirmed_covered':len(confirmed&local_available),'local_source_gap':len(missing),
        'interpretation':'Presence of at least one point is not correctness/completeness of every point. Snapshot is historical reference, not chosen final truth. Missing locally is not proof of missing official records.',
        'script_sha256':sha(Path(__file__))}
    (OUT/'passing_inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (OUT/'passing_rpt_file_evidence.json').write_text(json.dumps(text_file_evidence,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('coverage','rpt_file_counts_by_year_meet','rpt_header_errors')},ensure_ascii=False))


if __name__ == '__main__':
    main()

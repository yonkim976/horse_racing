#!/usr/bin/env python3
"""Collect public Jeju starting training rows; no DB writes or credentials."""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, json, re, threading, time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

BASE = 'https://race.kra.co.kr/startingData/getStartingTrainListAll.do'
EXPECTED = ['소속조', '조번', '마명', '기승자', '조교장소', '비고']
FIELDS = ['affiliation', 'trainer_no', 'horse_name', 'rider', 'location', 'note']

class TrainingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []; self.current = None; self.cell = None; self.ids = []
        self.inputs = {}; self.table_depth = 0
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'input' and 'name' in a: self.inputs[a['name']] = a.get('value', '')
        if tag == 'table': self.table_depth += 1
        if self.table_depth and tag == 'tr': self.current = []; self.ids = []
        if self.current is not None and tag in ('td', 'th'): self.cell = []
        if self.current is not None and tag == 'a':
            m = re.search(r"goPage1\(\s*['\"]([0-9]+)['\"]\s*\)", a.get('onclick', ''))
            if m: self.ids.append(m.group(1))
        if self.cell is not None and tag == 'br': self.cell.append(' ')
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.current.append(re.sub(r'\s+', ' ', ''.join(self.cell)).strip()); self.cell = None
        if tag == 'tr' and self.current is not None:
            self.rows.append((self.current, self.ids)); self.current = None; self.cell = None
        if tag == 'table': self.table_depth = max(0, self.table_depth - 1)


def parse(raw: bytes, date: str):
    text = raw.decode('euc-kr', errors='strict')
    p = TrainingParser(); p.feed(text)
    observed = p.inputs.get('trDateReplace')
    if observed != date: raise ValueError(f'wrong/missing hidden date: {observed!r}')
    if not any(cells == EXPECTED for cells, _ in p.rows):
        raise ValueError('expected training table header missing')
    out = []
    for cells, ids in p.rows:
        if cells == EXPECTED: continue
        if len(cells) != 6: raise ValueError(f'unexpected table width {len(cells)}')
        if len(ids) != 1 or not re.fullmatch(r'[0-9]{6,7}', ids[0]):
            raise ValueError('missing or ambiguous official horse ID')
        row = dict(zip(FIELDS, cells)); row['horse_id_raw'] = ids[0]
        row['source_row_no'] = len(out) + 1
        row['raw_row_json'] = dict(zip(EXPECTED, cells)) | {'horse_id_raw': ids[0]}
        out.append(row)
    return out


_lock = threading.Lock(); _next_request = 0.0

def throttle(interval):
    global _next_request
    with _lock:
        now = time.monotonic(); slot = max(now, _next_request); _next_request = slot + interval
    time.sleep(max(0, slot - now))


def fetch(date, output, interval):
    datetime.strptime(date, '%Y%m%d')
    if not re.fullmatch('[0-9]{8}', date): raise ValueError('invalid date')
    journal = output / 'metadata' / (date + '.json')
    if journal.exists():
        old = json.loads(journal.read_text())
        if old['status'] in ('complete', 'empty'):
            p = (output / old['html_path']).resolve()
            if not p.is_relative_to(output.resolve()): raise ValueError('unsafe cached path')
            if hashlib.sha256(p.read_bytes()).hexdigest() != old['html_sha256']:
                raise ValueError('cache hash mismatch')
            return old
    date_iso = date[:4] + '-' + date[4:6] + '-' + date[6:]
    params = {'Act': '07', 'Sub': '2', 'meet': '2', 'trDate': date_iso.replace('-', '/'),
              'trDateReplace': date, 'trNo': '', 'trName': ''}
    url = BASE + '?' + urlencode(params)
    meta = {'date': date_iso, 'url': url, 'requested_at': datetime.now(timezone.utc).isoformat(),
            'status': 'fetch_failed', 'attempts': []}
    for attempt in range(1, 4):
        try:
            throttle(interval)
            request = Request(url, headers={'User-Agent': 'JejuHorseResearch/1.0'})
            with urlopen(request, timeout=25) as response:
                final = urlparse(response.url)
                if final.scheme != 'https' or final.hostname != 'race.kra.co.kr':
                    raise ValueError('unexpected redirect host')
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024: raise ValueError('response too large')
                meta['http_status'] = response.status
                meta['content_type'] = response.headers.get('Content-Type')
            filename = 'html/' + date + '_' + str(attempt) + '.html'
            (output / filename).write_bytes(raw)
            meta['html_path'] = filename; meta['html_sha256'] = hashlib.sha256(raw).hexdigest()
            meta['response_bytes'] = len(raw)
            meta['received_at'] = datetime.now(timezone.utc).isoformat()
            try:
                rows = parse(raw, date)
            except Exception as exc:
                meta['status'] = 'parse_failed'; meta['error'] = str(exc)
                meta['attempts'].append({'attempt': attempt, 'status': 'parse_failed', 'error': str(exc)})
                break
            meta['rows'] = rows; meta['status'] = 'complete' if rows else 'empty'
            meta['attempts'].append({'attempt': attempt, 'status': meta['status']})
            meta.pop('error', None)
            break
        except Exception as exc:
            meta['error'] = type(exc).__name__ + ': ' + str(exc)
            meta['attempts'].append({'attempt': attempt, 'status': 'fetch_failed', 'error': meta['error']})
            if attempt < 3: time.sleep(attempt)
    temporary = journal.with_suffix('.tmp'); temporary.write_text(json.dumps(meta, ensure_ascii=False)); temporary.replace(journal)
    return meta


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--dates-file', type=Path, required=True); ap.add_argument('--limit', type=int)
    ap.add_argument('--workers', type=int, default=4); ap.add_argument('--interval', type=float, default=0.25)
    args = ap.parse_args(); output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    (output / 'html').mkdir(exist_ok=True); (output / 'metadata').mkdir(exist_ok=True)
    dates = json.loads(args.dates_file.read_text())['dates']
    # Validate anomalies and both temporal ends first; retain every date in the full run.
    priority = ['20240117', '20071017', '20141224', '20260916', '20260927']
    dates = [d for d in priority if d in dates] + [d for d in dates if d not in priority]
    if args.limit: dates = dates[:args.limit]
    results = []; start = time.monotonic(); last = start
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(fetch, d, output, args.interval): d for d in dates}
        for future in concurrent.futures.as_completed(jobs):
            result = future.result(); results.append(result)
            now = time.monotonic()
            if len(results) <= 5 or len(results) % 100 == 0 or now - last > 30:
                last = now
                print(json.dumps({'completed': len(results), 'total': len(dates), 'date': result['date'],
                    'status': result['status'], 'rows': len(result.get('rows', [])),
                    'failed': sum(x['status'] not in ('complete', 'empty') for x in results),
                    'seconds': round(now - start, 1)}, ensure_ascii=False), flush=True)
    manifest = {'schema_version': 1, 'source': 'jeju_starting_training_homepage',
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'requested_dates_count': len(dates), 'dates': sorted(results, key=lambda r: r['date'])}
    target = output / 'collection_manifest.json'
    temp = target.with_suffix('.tmp'); temp.write_text(json.dumps(manifest, ensure_ascii=False)); temp.replace(target)
    print(json.dumps({'done': True, 'dates': len(results), 'rows': sum(len(x.get('rows', [])) for x in results),
        'status_counts': {s: sum(x['status'] == s for x in results) for s in sorted({x['status'] for x in results})}}, ensure_ascii=False), flush=True)

if __name__ == '__main__': main()

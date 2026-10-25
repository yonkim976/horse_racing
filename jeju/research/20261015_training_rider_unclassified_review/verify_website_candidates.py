"""Independent read-only reparse of eight website pages and candidate joins."""
from pathlib import Path
from html.parser import HTMLParser
import hashlib,json,re,sqlite3
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
W=OUT/'website'
class Parser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.rows=[];self.row=None;self.cell=None;self.inputs={}
    def handle_starttag(self,t,a):
        a=dict(a)
        if t=='input':self.inputs[a.get('name')]=a.get('value')
        if t=='tr':self.row=[]
        elif t in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,d):
        if self.cell is not None:self.cell.append(d)
    def handle_endtag(self,t):
        if t in ('td','th') and self.cell is not None:self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if t=='tr' and self.row is not None:self.rows.append(self.row);self.row=None
manifest=json.loads((W/'retry_collection_manifest.json').read_text())
evidence=json.loads((W/'retry_website_event_evidence.json').read_text())
web={};hashes=0
for page in manifest['pages']:
    path=(ROOT/page['source_path']).resolve();assert path.is_relative_to(W.resolve())
    body=path.read_bytes();assert hashlib.sha256(body).hexdigest()==page['sha256'];hashes+=1
    p=Parser();p.feed(body.decode('euc-kr'));horse=page['horse_id'];assert p.inputs.get('hrNo')==horse
    head=next(r for r in p.rows if all(k in r for k in ('조교일자','기승자','입장시간','퇴장시간','조교시간')))
    cols={k:head.index(k) for k in ('조교일자','기승자','입장시간','퇴장시간','조교시간')}
    for r in p.rows:
        if len(r)<=max(cols.values()):continue
        dm=re.match(r'(\d{4})/(\d{2})/(\d{2})',r[cols['조교일자']]);mm=re.fullmatch(r'(\d+)분',r[cols['조교시간']])
        if not dm or not mm:continue
        key=(horse,'-'.join(dm.groups()),r[cols['입장시간']],r[cols['퇴장시간']],int(mm[1])*60)
        web.setdefault(key,[]).append(r[cols['기승자']])
c=sqlite3.connect((ROOT/'jeju/data/jeju_native_core.sqlite3').as_uri()+'?mode=ro',uri=True)
seen=set()
for e in evidence['evidence_rows']:
    i=e['row_id'];assert i not in seen;seen.add(i)
    r=c.execute('''select d.horse_id,d.training_date,d.start_time_local,d.end_time_local,d.duration_seconds,v.rider_type,d.prNo_raw from daily_training_api_rows d join daily_training_rider_type_values v using(daily_training_api_row_id) where d.daily_training_api_row_id=?''',(i,)).fetchone()
    assert r[5]=='미분류' and r[6]==e['prNo_raw']
    key=(r[0],r[1],r[2].split()[-1][:5],r[3].split()[-1][:5],r[4]);labels=web[key]
    assert len(labels)==1 and labels[0]==e['website_name_raw'] and labels[0].endswith('(관)') and e['website_type_candidate']=='주로조교'
assert len(seen)==534
out={'result':'passed','html_sha_verified':hashes,'independently_verified_current_unclassified_rows':len(seen),'website_type':'주로조교','db_access':'read_only','db_changes':0}
(OUT/'website_candidate_verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False))

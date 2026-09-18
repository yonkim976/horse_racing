"""Export the full SQLite schema and counts for the Jeju Text phase-2 DB."""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'data/research/jeju_native_text_phase2_db_20260915';DB=OUT/'jeju_native_text_phase2.sqlite3'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 c=sqlite3.connect(f'file:{DB}?mode=ro',uri=True);c.row_factory=sqlite3.Row;objects=[]
 for o in c.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type,name"):
  name=o['name'];objects.append({'type':o['type'],'name':name,'row_count':int(c.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]),'columns':[dict(x) for x in c.execute(f'PRAGMA table_info("{name}")')],'foreign_keys':[dict(x) for x in c.execute(f'PRAGMA foreign_key_list("{name}")')],'indexes':[dict(x) for x in c.execute(f'PRAGMA index_list("{name}")')] if o['type']=='table' else [],'sql':o['sql']})
 result={'catalog_version':'1','database_path':str(DB.relative_to(ROOT)),'database_sha256':sha(DB),'database_bytes':DB.stat().st_size,'objects':objects,'text_type_coverage':[dict(x) for x in c.execute('SELECT * FROM text_type_coverage ORDER BY text_type')],'record_status':[dict(x) for x in c.execute('SELECT record_type,link_status,COUNT(*) row_count FROM text_native_record GROUP BY record_type,link_status ORDER BY record_type,link_status')],'issue_status':[dict(x) for x in c.execute('SELECT issue_code,COUNT(*) row_count FROM text_parse_issue GROUP BY issue_code ORDER BY issue_code')]};c.close();p=OUT/'catalog.json';p.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n');print(json.dumps({'path':str(p.relative_to(ROOT)),'objects':len(objects),'sha256':result['database_sha256']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()

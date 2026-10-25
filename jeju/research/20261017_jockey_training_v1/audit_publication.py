"""Audit all prior central hashes without changing existing files."""
import json
from data import HERE,ROOT,sha,save
def main():
 p=ROOT/'jeju/research/conclusions/source_manifest.json';m=json.loads(p.read_text());drift=[]
 for r in m['files']:
  q=ROOT/r['path'];v={'sha256':sha(q),'bytes':q.stat().st_size} if q.is_file() else None
  if v is None or v['sha256']!=r['sha256'] or v['bytes']!=r['bytes']:drift.append({'path':r['path'],'registered':{'sha256':r['sha256'],'bytes':r['bytes']},'observed':v})
 out=HERE/'prepublication_audit01.json';assert not out.exists();save(out,{'entries_checked':len(m['files']),'central_manifest_sha256':sha(p),'drift':drift,'no_files_modified':True});print(json.dumps({'entries':len(m['files']),'drift':drift},ensure_ascii=False),flush=True)
if __name__=='__main__':main()

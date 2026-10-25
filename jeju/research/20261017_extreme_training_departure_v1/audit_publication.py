"""Read-only comparison with the previously registered research sources."""
import json
from data import HERE,ROOT,sha,save
def main():
 p=ROOT/'jeju/research/conclusions/source_manifest.json';m=json.loads(p.read_text());drift=[]
 for r in m['files']:
  q=(ROOT/r['path']).resolve();assert q.is_relative_to(ROOT)
  actual={'sha256':sha(q),'bytes':q.stat().st_size} if q.is_file() else None
  if actual is None or actual['sha256']!=r['sha256'] or actual['bytes']!=r['bytes']:drift.append({'path':r['path'],'registered':{'sha256':r['sha256'],'bytes':r['bytes']},'actual':actual})
 out=HERE/'prepublication_audit01.json';assert not out.exists();save(out,{'central_manifest_sha256':sha(p),'entries_checked':len(m['files']),'drift':drift,'no_files_modified':True})
 print('Prior source entries audited',len(m['files']),'drift',len(drift),flush=True)
if __name__=='__main__':main()

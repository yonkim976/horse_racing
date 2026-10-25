"""Read-only audit of the current central manifest before publication."""
import json
from data import HERE,ROOT,save,sha

def main():
 p=ROOT/'jeju/research/conclusions/source_manifest.json'
 m=json.loads(p.read_text());drift=[]
 for r in m['files']:
  q=ROOT/r['path'];actual={'sha256':sha(q),'bytes':q.stat().st_size} if q.is_file() else None
  if actual is None or actual['sha256']!=r['sha256'] or actual['bytes']!=r['bytes']:
   drift.append({'path':r['path'],'registered':{'sha256':r['sha256'],'bytes':r['bytes']},'observed':actual})
 out=HERE/'prepublication_audit01.json';assert not out.exists()
 save(out,{'status':'preexisting_drift_observed' if drift else 'passed','central_manifest_sha256':sha(p),'entries_checked':len(m['files']),'drift':drift,'no_files_modified':True})
 print(json.dumps({'entries':len(m['files']),'drift':drift},ensure_ascii=False),flush=True)
if __name__=='__main__':main()

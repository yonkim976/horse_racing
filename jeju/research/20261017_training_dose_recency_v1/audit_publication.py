"""Audit all existing central source entries before changing the indexes."""
import json
from data import HERE,ROOT,sha,save
def main():
 p=ROOT/'jeju/research/conclusions/source_manifest.json';m=json.loads(p.read_text());diff=[]
 for r in m['files']:
  q=ROOT/r['path'];actual={'sha256':sha(q),'bytes':q.stat().st_size} if q.is_file() else None
  if actual is None or actual['sha256']!=r['sha256'] or actual['bytes']!=r['bytes']:diff.append({'path':r['path'],'registered':{'sha256':r['sha256'],'bytes':r['bytes']},'actual':actual})
 p2=HERE/'prepublication_audit01.json';assert not p2.exists();save(p2,{'central_manifest_sha256':sha(p),'entries_checked':len(m['files']),'drift':diff,'no_files_modified':True});print('Central audit',len(m['files']),'entries',len(diff),'drifts',flush=True)
if __name__=='__main__':main()

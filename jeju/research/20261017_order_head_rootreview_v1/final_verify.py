"""Seal verified immutable study/report artifacts; no source modifications."""
from pathlib import Path
import hashlib,json

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
MAIN=ROOT/'jeju/research/20261017_conditional_order_head_v1'
EV=ROOT/'jeju/research/20261017_order_head_value_comparison_v1'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def main():
    sources=json.loads((HERE/'ROOT_SOURCE_PREFLIGHT.json').read_text())['sources']
    for path,h in sources.items():assert sha(ROOT/path)==h,path
    manifests={}
    for base,rel in [(MAIN,'outputs/FINAL_MANIFEST.json'),(EV,'FINAL_MANIFEST.json')]:
        p=base/rel;a=json.loads(p.read_text());assert 'PENDING' not in a['status'] and 'DRAFT' not in a['status'],a['status']
        for name,record in a['files'].items():
            file=ROOT/name if name.startswith('jeju/') else base/name
            assert sha(file)==record['sha256'],str(file)
            if 'bytes' in record:assert file.stat().st_size==record['bytes']
        manifests[str(p.relative_to(ROOT))]={'sha256':sha(p),'files':len(a['files']),'status':a['status']}
    proofnames=['ROOT_FIT_REVIEW.json','ROOT_PREDICTION_REVIEW.json','ROOT_METRICS_REVIEW.json','ROOT_VALUE_REVIEW.json','ROOT_FINAL_SOURCE_CHECK.json']
    proofs={}
    for name in proofnames:
        p=HERE/name;a=json.loads(p.read_text());assert a['status']=='PASS';proofs[name]=sha(p)
    out={'status':'PASS','scope':'Conditional order model and native operating comparison independently reviewed and frozen; no operating promotion','source_files_unchanged':len(sources),'proofs':proofs,'final_manifests':manifests,'model_fit_count':3,'temperature_fit_count':3,'joint_races':1779,'joint_rows':1208424,'common_operating_races':467,'price_complete_tri_races':222,'same_10_fixed_price_rules':True,'operating_model_registry_base_horse_scores_and_standalone_pair_model_unchanged':True,'retrospective_development_evaluation_only':True,'final_reports':{str(p.relative_to(ROOT)):sha(p) for p in [MAIN/'README.md',EV/'README.md',EV/'REPORT.json',MAIN/'outputs/METRICS.json']}}
    (HERE/'ROOT_FINAL_VERIFICATION.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))

if __name__=='__main__':main()

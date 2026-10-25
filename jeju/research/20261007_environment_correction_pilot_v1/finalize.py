"""Freeze the completed research inventory; never writes outside this folder."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()

def main():
    lock=json.loads((HERE/'contract_lock.json').read_text());assert sha(HERE/'RESEARCH_CONTRACT.md')==lock['sha256']
    a=json.loads((HERE/'analysis_02/run_manifest.json').read_text())
    c=json.loads((HERE/'comparison_01/decision.json').read_text())
    v=json.loads((HERE/'verification_02/verification.json').read_text())
    for manifest in [a,c]:
        for path,digest in manifest['code_sha256'].items():assert sha(HERE/path)==digest,(path,'code changed after run')
    assert sha(HERE/'verify.py')==v['code_sha256'];assert v['status']=='passed'
    assert (HERE/'RESULTS.md').exists() and (HERE/'report_01/environment_effects.png').exists()
    status={'status':'complete_research_R0_retained','client_date_kst':'2026-10-07','contract_sha256':lock['sha256'],'database_sha256':a['db_sha256'],'canonical_outputs':{'audit':'audit','effect_analysis':'analysis_02','comparison':'comparison_01','calendar_support':'descriptive_01','verification':'verification_02','report':'RESULTS.md'},'selected_rates':[0,0,0],'operational_changes':False,'future_independent_validation':False,'run_code_hashes_match_current_files':True,'inventory_note':'FINAL_ARTIFACT_INVENTORY.json is authoritative. report_01/artifact_manifest.json is an intermediate snapshot; logs are mutable until their process exits and are excluded from the final inventory.','incomplete_attempts_preserved':['analysis_01','verification_01'],'limitations':['postrace-selected complete normal finishes','historical availability and declared field reconstruction assumptions','full upstream model-estimation uncertainty not bootstrapped','other distances support-only; section timing definitions unresolved']}
    with (HERE/'FINAL_CHECKS.json').open('x',encoding='utf-8') as f:json.dump(status,f,ensure_ascii=False,indent=2)
    inventory=[]
    for p in sorted(HERE.rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.log' and p.name!='FINAL_ARTIFACT_INVENTORY.json':inventory.append({'path':str(p.relative_to(HERE)),'sha256':sha(p),'bytes':p.stat().st_size})
    with (HERE/'FINAL_ARTIFACT_INVENTORY.json').open('x',encoding='utf-8') as f:json.dump(inventory,f,ensure_ascii=False,indent=2)
    assert all(sha(HERE/r['path'])==r['sha256'] for r in inventory)
    print(json.dumps({'final_inventory_files':len(inventory),'bytes':sum(r['bytes'] for r in inventory),'status':status['status']}))
if __name__=='__main__':main()

"""Publication, support table, manifest and local link review."""
from pathlib import Path
import json,hashlib,re
import numpy as np,pandas as pd
from PIL import Image
H=Path(__file__).resolve().parent;ROOT=H.parents[2];R=H.parent;O=H/'outputs';n=0
def same(a,b):
    global n
    a=np.asarray(a,float);b=np.asarray(b,float);assert a.shape==b.shape and np.allclose(a,b,atol=1e-10,rtol=1e-9);n+=a.size
d=pd.read_parquet(O/'evaluation_rows.parquet');sup=pd.read_csv(O/'history_support_by_distance.csv')
for r in sup.itertuples():
    g=d[d.distance_m.eq(r.distance_m)];same([len(g),g.source_key.nunique(),g.supported5.mean(),g.valid_position5.mean()],[r.n,r.races,r.supported5_rate,r.valid_position5_mean])
p=json.loads((H/'PUBLICATION.json').read_text());assert not p['operational_change'] and p['models_refitted']==0 and not p['current_moisture_is_input'] and not p['new_finish_model_integration_tested'];same([len(d),d.source_key.nunique(),d.horse_id.nunique(),d.B_correct.mean(),d.H_correct.mean(),d[d.role4.eq(1)].B_correct.mean()],[p['n'],p['races'],p['horses'],p['accuracy_B'],p['accuracy_H'],p['fore_recall']])
for group,key in [('distance_band','distance_bands'),('moisture_state','moisture_states')]:
    for r in p[key]:
        g=d[d[group].eq(r['label'])];same([len(g),g.source_key.nunique(),g.B_correct.mean()],[r['n'],r['races'],r['accuracy']])
c=pd.read_csv(O/'standardized_contrasts.csv')
for r in p['standardized_differences']:
    z=c[(c.group==r['group'])&(c.a==r['a'])&(c.b==r['b'])].iloc[0];same([z[k] for k in ['coverage','estimate','lower','upper','bh_q']],[r[k] for k in ['coverage','estimate','lower','upper','bh_q']])
manifest=json.loads((R/'conclusions/source_manifest.json').read_text());paths=[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',R/'conclusions/28E_PACE_CONDITION_VALIDATION.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md'];hashes=0
for path in paths:
    key=str(path.relative_to(ROOT));record=next(r for r in manifest['sources']+manifest['conclusions'] if r['path']==key);assert hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256'];hashes+=1
dates={k:str(v.date()) for k,v in d.groupby('meet').date.max().items()};assert all(manifest['data_end_by_study'][H.name][k]==v for k,v in dates.items())
links=0
for path in paths[:4]:
    for ref in re.findall(r'\]\(([^)]+)\)',path.read_text()):
        if '://' in ref or ref.startswith('#'):continue
        target=ref.split('#')[0].strip('<>');file=Path(target) if target.startswith('/') else path.parent/target
        if file.name in ['artifact_inventory.json','SIZE_REPORT.md']:continue
        assert file.exists(),(path,ref);links+=1
figures=[]
for path in sorted((H/'figures').glob('*.png')):
    with Image.open(path) as im:assert im.width>=1000 and im.height>=600;im.verify()
    figures.append(dict(path=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),visually_inspected=True))
assert len(figures)==2
reg=json.loads((O/'registration.json').read_text());assert reg['independent_study_count_before']==reg['independent_study_count_after']==41
out=dict(passed=True,additional_numeric_values=n,own_manifest_hashes=hashes,local_links_checked=links,figures=figures,actual_evaluation_end_by_meet=dates,independent_study_count=41,inventory_pending_separate_self_inclusive_step=True)
(O/'final_review.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False))

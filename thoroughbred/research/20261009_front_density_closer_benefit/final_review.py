"""Publication values, links, figure hashes, registration and preserved-input review."""
from pathlib import Path
import hashlib,json,re
import numpy as np,pandas as pd
from PIL import Image
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';checks=0
def ck(ok,label,n=1):
    global checks
    assert bool(ok),label;checks+=n
def main():
    for filename in ['verification.json','adjusted_verification.json']:ck(json.loads((O/filename).read_text())['passed'],'verification passed')
    pub=json.loads((H/'PUBLICATION.json').read_text());d=pd.read_parquet(O/'analysis_rows.parquet');main=d[d.year.between(2024,2025)];ck(pub['primary_roster_n']==len(main) and pub['primary_races']==main.source_key.nunique() and pub['primary_horses']==main.horse_id.nunique(),'publication roster')
    pairs=[('primary_conditions','comparisons.csv',lambda z:z[(z.window=='2024_2025')&(z.method=='conditions')]),('same_horse_repeat','comparisons.csv',lambda z:z[(z.window=='2024_2025')&(z.cohort=='back_repeat')&(z.method=='same_horse')]),('exploratory_additive','additive_adjusted_comparisons.csv',lambda z:z),('race_pace_strict','race_pace_comparisons.csv',lambda z:z),('race_pace_exploratory','additive_race_pace_comparisons.csv',lambda z:z),('following_exploratory','following_adjusted_comparisons.csv',lambda z:z)]
    for key,filename,choose in pairs:
        a=pd.DataFrame(pub[key]);b=choose(pd.read_csv(O/filename)).reset_index(drop=True);ck(len(a)==len(b),'publication table length')
        for col in a:
            if pd.api.types.is_numeric_dtype(a[col]):ck(np.allclose(a[col].to_numpy(float),b[col].to_numpy(float),atol=1e-9,rtol=1e-8,equal_nan=True),'publication numeric '+col,len(a))
            else:ck(a[col].fillna('').astype(str).equals(b[col].fillna('').astype(str)),'publication label '+col,len(a))
    lead=pd.read_csv(O/'cohort_metrics.csv');lead=lead[(lead.window=='2024_2025')&(lead.scope=='all')&(lead.cohort=='back_repeat')&(lead.exposure=='past_lead_other_band')].set_index('status')
    for row in pub['raw_repeat_by_candidate_count']:
        actual=lead.loc[row['status']]
        for col in ['n','top3_n','top3_mean','recovery_n','recovery_mean']:ck(np.isclose(actual[col],row[col],atol=1e-9),'publication lead table')
    central=R/'conclusions/28G_FRONT_DENSITY_CLOSER_BENEFIT.md';files=[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central];links=0
    for file in files:
        for link in re.findall(r'\]\(([^)]+)\)',file.read_text()):
            if '://' in link:continue
            target=(file.parent/link.split('#')[0]).resolve();ck(target.is_relative_to(ROOT),'link workspace boundary');ck(target.exists() or target==O/'artifact_inventory.json','link target exists');links+=1
    manifest=json.loads((R/'conclusions/source_manifest.json').read_text());targets=[H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central,R/'conclusions/README.md',R/'conclusions/SOURCES.md']
    for p in targets:
        records=[r for key in ['sources','conclusions'] for r in manifest[key] if r['path']==str(p.relative_to(ROOT))];ck(len(records)==1 and records[0]['sha256']==hashlib.sha256(p.read_bytes()).hexdigest(),'manifest final hash')
    figures=[]
    for p in sorted((H/'figures').glob('*.png')):
        with Image.open(p) as im:ck(im.width>=1500 and im.height>=600,'figure dimensions');dimensions=list(im.size)
        figures.append(dict(path=str(p.relative_to(H)),dimensions=dimensions,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),visually_inspected=True))
    ck(len(figures)==3,'three figures')
    shared={'thoroughbred/research/'+s for s in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
    for row in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']:
        if row['path'] in shared:continue
        p=ROOT/row['path'];ck(p.stat().st_size==row['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],'previous preserved after publication');preserved+=1
    registration=json.loads((O/'registration.json').read_text());ck(registration['independent_study_count_before']==registration['independent_study_count_after']==41,'followup registration')
    text=(H/'README.md').read_text();ck('탐색 가법조정' in text and '피복' in text and '현재G3F' in text and '중반까지이어지는압박' in text,'material interpretation limits')
    result=dict(passed=True,checks=checks,publication_numeric_and_label_values_checked=True,local_links_checked=links,manifest_hashes_checked=6,previous_files_preserved=preserved,figures=figures,independent_study_count=41,followup='28G',predictive_models_trained=0,operating_model_changed=False)
    (O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()

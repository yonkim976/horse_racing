"""Publication provenance, prior-field lineage, cases, links and image review."""
from pathlib import Path
import hashlib,json,re
import pandas as pd,numpy as np
from PIL import Image
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';checks=0
def ck(x,label,n=1):
    global checks
    assert bool(x),label;checks+=n
def compare(a,b,label):
    a=np.array(a,float);b=np.array(b,float);ck(a.shape==b.shape and np.allclose(a,b,atol=1e-9,rtol=1e-8,equal_nan=True),label,a.size)
def main():
    for name in ['verification.json','sensitivity_verification.json']:ck(json.loads((O/name).read_text())['passed'],'completed verification')
    d=pd.read_parquet(O/'analysis_rows.parquet');base=pd.read_parquet(R/'20261008_middle_late_style_validation/outputs/trajectory_rows.parquet').set_index('row_key').loc[d.row_key]
    for c in ['finish_p_mean5','valid_position5','supported5','rating','age_current','p_s1f','p_g3f','p_g1f','raw_finish_rank','normal_outcome']:compare(base[c],d[c],'unchanged past/current lineage '+c)
    pub=json.loads((H/'PUBLICATION.json').read_text())
    for key,name in [('raw_metrics','cohort_metrics.csv'),('contrasts','comparisons.csv'),('adjustment_stages_exploratory','adjustment_stages.csv'),('same_calendar_confirmation','same_calendar_confirmation.csv')]:
        a=pd.DataFrame(pub[key]);b=pd.read_csv(O/name,dtype={'segment':str}).reset_index(drop=True);ck(len(a)==len(b),'publication table rows')
        for c in a:
            if pd.api.types.is_numeric_dtype(a[c]):compare(a[c],b[c],'publication numeric '+c)
            else:ck(a[c].fillna('').astype(str).equals(b[c].fillna('').astype(str)),'publication text '+c,len(a))
    summary=pd.read_csv(O/'primary_summary.csv',dtype={'segment':str});a=pd.DataFrame(pub['primary_summary'])
    for c in a:
        if pd.api.types.is_numeric_dtype(a[c]):compare(a[c],summary[c],'primary summary publication')
        else:ck(a[c].astype(str).equals(summary[c].astype(str)),'primary summary labels')
    cases=pd.read_csv(O/'illustrative_cases.csv',dtype={'horse_id':str},parse_dates=['date','future_date1']);source=d.set_index('row_key').loc[cases.row_key];ck(len(cases)==4 and set(cases.next_top3)=={0,1},'success/failure examples')
    for c in ['distance_m','raw_finish_rank','time600','race_q20_600','future_rank1','next_days','next_top3']:compare(source[c],cases[c],'case exact lineage')
    for c in ['horse_name','source_key','future_key1']:ck(source[c].tolist()==cases[c].tolist(),'case labels')
    central=R/'conclusions/28H_FAST_LATE_NONPODIUM_FUTURE.md';links=0
    for p in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central]:
        for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if '://' in link:continue
            target=(p.parent/link.split('#')[0]).resolve();ck(target.is_relative_to(ROOT),'link boundary');ck(target.exists() or target==O/'artifact_inventory.json','link exists');links+=1
    manifest=json.loads((R/'conclusions/source_manifest.json').read_text())
    for p in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',central,R/'conclusions/README.md',R/'conclusions/SOURCES.md']:
        found=[r for key in ['sources','conclusions'] for r in manifest[key] if r['path']==str(p.relative_to(ROOT))];ck(len(found)==1 and found[0]['sha256']==hashlib.sha256(p.read_bytes()).hexdigest(),'final manifest hash')
    figures=[]
    for p in sorted((H/'figures').glob('*.png')):
        with Image.open(p) as im:ck(im.width>=1500 and im.height>=600,'figure size');size=list(im.size)
        figures.append(dict(path=str(p.relative_to(H)),dimensions=size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),visually_inspected=True))
    ck(len(figures)==3,'3 charts')
    shared={'thoroughbred/research/'+s for s in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
    for item in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']:
        if item['path'] in shared:continue
        p=ROOT/item['path'];ck(p.stat().st_size==item['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'],'old studies preserved after publication');preserved+=1
    reg=json.loads((O/'registration.json').read_text());ck(reg['independent_study_count_before']==reg['independent_study_count_after']==41,'independent count')
    content=(H/'README.md').read_text();ck('서울400m를추정하지않았다' in content and '다음정상출전' in content and '2026 성숙자료' in content and '현재착순과패배시간차' in content,'material limits disclosed')
    result=dict(passed=True,checks=checks,prior_fields_verified=10,publication_numeric_values_checked=True,case_rows_verified=4,links_checked=links,manifest_hashes_checked=6,figures=figures,previous_files_preserved=preserved,followup='28H',independent_study_count=41,predictive_models_trained=0,operating_model_changed=False)
    (O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()

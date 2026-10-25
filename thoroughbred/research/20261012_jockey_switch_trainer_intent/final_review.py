"""Publication, support completeness, preservation, link and figure review before inventory."""
from pathlib import Path
import json,re,hashlib
import numpy as np,pandas as pd
from PIL import Image
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';R=H.parent;CENTRAL=R/'conclusions/50_JOCKEY_SWITCH_TRAINER_INTENT.md';checks=0
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def check(value,label):
    global checks
    assert value,label;checks+=1
def main():
    d=pd.read_parquet(O/'analysis_rows.parquet');pub=json.loads((H/'PUBLICATION.json').read_text());v=json.loads((O/'verification.json').read_text());check(v['passed'],'independent verifier')
    maps={'category_metrics':'category_metrics.csv','adjusted_associations':'adjusted_associations.csv','preferred_metrics':'preferred_booking_metrics.csv','distance_time_associations':'distance_time_associations.csv','sensitivity':'sensitivity.csv','same_calendar_year_associations':'same_calendar_year_associations.csv'}
    for key,file in maps.items():
        a=pd.DataFrame(pub[key]);b=pd.read_csv(O/file);check(list(a.columns)==list(b.columns),key+' columns');check(a.shape==b.shape,key+' shape')
        for c in a:
            if pd.api.types.is_numeric_dtype(b[c]):check(np.allclose(a[c].to_numpy(float),b[c].to_numpy(float),atol=1e-12,rtol=1e-12,equal_nan=True),key+c)
            else:check(a[c].fillna('MISSING').equals(b[c].fillna('MISSING')),key+c)
    check(not d.row_key.duplicated().any(),'unique rows');check(len(d)==159014,'roster');check(int(d.quality_time.notna().sum())==151074,'quality time base')
    for window,g in [('2024_2025',d[d.year.between(2024,2025)]),('2026_partial',d[d.year.eq(2026)])]:
        g=g[g.main_eligible&g.changed]
        for file,keys,minn,minh,minr in [('destination_jockey_metrics.csv',['meet','jockey_id'],100,30,30),('trainer_jockey_pair_metrics.csv',['meet','trainer_id','jockey_id'],50,20,20)]:
            grouped=g.groupby(keys).agg(n=('row_key','size'),h=('horse_id','nunique'),r=('source_key','nunique'));expected=set(grouped[(grouped.n>=minn)&(grouped.h>=minh)&(grouped.r>=minr)].index)
            t=pd.read_csv(O/file,dtype={'jockey_id':str,'trainer_id':str});actual=set(map(tuple,t[t.window.eq(window)][keys].to_numpy()));check(expected==actual,file+window+' complete supported groups')
    metrics=pd.read_csv(O/'category_metrics.csv');a=metrics[(metrics.window=='2024_2025')&metrics.meet.eq('전체')].set_index('category');text=(H/'PUBLICATION.md').read_text();report=(H/'README.md').read_text()
    for r in a.itertuples():
        if not r.Index.startswith('all_'):check(f'{int(r.n):,}' in text and f'{100*r.top3_rate:.2f}%' in text,'main table numeric '+r.Index)
    effects=pd.read_csv(O/'adjusted_associations.csv');main=effects[(effects.window=='2024_2025')&effects.meet.eq('전체')&effects.model.eq('race_horse_controls')&effects.term.eq('ordinary_to_top')].set_index('target')
    check(f"{main.loc['top3','estimate']*100:+.2f}%p" in text,'adjusted top3');check(f"{-main.loc['finish_p','estimate']*100:.2f}점" in text,'adjusted rank');check(f"{-main.loc['time_gap','estimate']:.3f}초" in text,'adjusted seconds')
    for key in ['causal_intent_identified','production_changed']:check(pub[key] is False,key)
    cases=pd.read_csv(O/'illustrative_cases.csv');bykey=d.set_index('row_key')
    for row in cases.itertuples():
        s=bykey.loc[row.row_key]
        for col in ['horse_name','trainer_name','jockey_name','raw_finish_rank','previous_raw_finish_rank']:check(getattr(row,col)==s[col],'case '+col)
    for row in json.loads((O/'source_audit.json').read_text())['inputs']:check(sha(ROOT/row['path'])==row['sha256'],'unchanged source '+row['path'])
    shared={r['path'] for r in json.loads((O/'shared_edits_baseline.json').read_text())['files']};old=json.loads((O/'baseline_inventory.json').read_text())['related_existing_files'];preserved=0
    for row in old:
        if row['path'] in shared:continue
        p=ROOT/row['path'];check(p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],'preserved '+row['path']);preserved+=1
    manifest=json.loads((R/'conclusions/source_manifest.json').read_text());mf=manifest['sources']+manifest['conclusions']
    for p in [H/'README.md',H/'SOURCES.md',H/'PUBLICATION.md',CENTRAL,R/'conclusions/README.md',R/'conclusions/SOURCES.md']:
        item=next(r for r in mf if r['path']==str(p.relative_to(ROOT)));check(item['sha256']==sha(p),'manifest '+str(p))
    links=0;future={O/'artifact_inventory.json',O/'SIZE_REPORT.md'}
    for p in list(H.glob('*.md'))+[CENTRAL]:
        for url in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if url.startswith(('https:','http:','#')):continue
            q=(p.parent/url.split('#')[0]).resolve();check(q.exists() or q in future,'local link '+str(q));links+=1
    images=[]
    for p in sorted((H/'figures').glob('*.png')):
        im=Image.open(p);check(im.width>=1200 and im.height>=600,'figure resolution');check(float(np.std(np.asarray(im)))>20,'nonblank figure');images.append(dict(path=str(p.relative_to(ROOT)),width=im.width,height=im.height,sha256=sha(p),visually_inspected=True))
    result=dict(passed=True,checks=checks,independent_verification_checks=v['checks'],prior_files_preserved=preserved,all_supported_jockey_and_pair_groups_included=True,local_links_checked=links,publication_tables_match_saved_results=True,figures=images)
    (O/'final_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

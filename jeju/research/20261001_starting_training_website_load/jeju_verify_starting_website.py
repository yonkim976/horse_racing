import json, sqlite3, re, hashlib, html
from pathlib import Path
from collections import Counter
BASE=Path('/private/tmp/jeju_training_website_collection_20261001')
manifest=json.loads((BASE/'collection_manifest.json').read_text())
api=json.loads(Path('/private/tmp/jeju_training_api_date_horse_counts.json').read_text())
c=sqlite3.connect('file:/Users/kimyongjin/Desktop/horse_racing/jeju/data/jeju_native_core.sqlite3?mode=ro',uri=True)
profiles={r[0] for r in c.execute("SELECT DISTINCT horse_id FROM horse_profile_observations WHERE breed_label_raw='제주마'")}
counts=Counter(); profile_horses=set(); native_dates=set(); locations=Counter(); diffs=[]; api_only=[]; web_only=[]
for m in manifest['dates']:
    assert m['status']=='complete' and m['http_status']==200
    raw=(BASE/m['html_path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==m['html_sha256']
    s=raw.decode('euc-kr'); independently=[]
    for row in re.findall(r'<tr\b[^>]*>([\s\S]*?)</tr>',s,re.I):
        ids=re.findall(r'goPage1\(\s*[\'\"]([0-9]+)[\'\"]\s*\)',row)
        if not ids:continue
        cells=re.findall(r'<td\b[^>]*>([\s\S]*?)</td>',row,re.I)
        assert len(cells)==6 and len(ids)==1
        texts=[re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>','',x))).strip() for x in cells]
        independently.append((ids[0],texts))
    assert len(independently)==len(m['rows'])
    assert [r['source_row_no'] for r in m['rows']]==list(range(1,len(m['rows'])+1))
    for (h,values),r in zip(independently,m['rows']):
        assert h==r['horse_id_raw']
        assert values==[r[k] for k in ['affiliation','trainer_no','horse_name','rider','location','note']]
    wc=Counter(r['horse_id_raw'] for r in m['rows']); dt=m['date'].replace('-',''); ac=Counter(api[dt])
    changed={h:{'api_count':ac[h],'website_count':wc[h]} for h in ac.keys()|wc.keys() if ac[h]!=wc[h]}
    if changed:diffs.append({'date':m['date'],'api_rows':sum(ac.values()),'website_rows':sum(wc.values()),'horse_differences':changed})
    for h in ac.keys()|wc.keys():
        if h in profiles and not ac[h] and wc[h]:web_only.append({'date':m['date'],'horse_id':h,'website_rows':wc[h]})
        if h in profiles and ac[h] and not wc[h]:api_only.append({'date':m['date'],'horse_id':h,'api_rows':ac[h]})
    counts['dates']+=1; counts['raw_rows']+=len(m['rows'])
    for r in m['rows']:
        if r['horse_id_raw'] in profiles:
            counts['native_rows']+=1; profile_horses.add(r['horse_id_raw']); native_dates.add(m['date']); locations[r['location']]+=1
            if m['date']<='2026-09-19':counts['native_rows_through_race_cutoff']+=1
            else:counts['native_rows_after_race_cutoff']+=1
        else:counts['outside_profile_population_rows']+=1
    if counts['dates']%500==0: print('verified dates',counts['dates'],flush=True)
summary={'independent_parser_all_rows_match':True,'all_source_hashes_match':True,'all_official_date_identifiers_match_collector':True,'counts':dict(counts),'native_horses':len(profile_horses),'native_dates':len(native_dates),'locations':dict(locations),'api_vs_website_differing_dates':diffs,'native_website_only_groups':web_only,'native_api_only_groups':api_only,'source_manifest_sha256':hashlib.sha256((BASE/'collection_manifest.json').read_bytes()).hexdigest()}
Path('/private/tmp/jeju_training_website_full_verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in summary.items() if k not in ['api_vs_website_differing_dates','native_website_only_groups','native_api_only_groups']},ensure_ascii=False,indent=2))
print('differences',[(d['date'],len(d['horse_differences'])) for d in diffs],flush=True)
print('website_only_native_groups',len(web_only),'API_only_native_groups',len(api_only),flush=True)

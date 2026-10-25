"""Read archived JSON directly using independently frozen complete-page inventory."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
 inventory=ROOT/'jeju/research/20261013_prepurchase_ev_audit_v1/SOURCE_PAGE_INDEX.json'
 assert sha(inventory)=='1dac9ab751fe0be8ad4da2e139f862500ea68f3a23ab290def9b42f3dfda6fb0'
 pages=json.loads(inventory.read_text());assert len(pages)==889
 # The prior independent inventory supplies all latest-complete pages, not selected quotes.
 chosen_path=ROOT/'jeju/research/20261013_postrace_ev_exploration_v1/SOURCE_PAGE_INDEX.csv'
 chosen=pd.read_csv(chosen_path,dtype={'source_run_id':str});assert len(chosen)==506
 wanted=set(chosen.page_sha256)
 f=pd.read_parquet(ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet',columns=['race_id','year','horse_number'])
 f=f[f.year.isin([2025,2026])];assert f.race_id.nunique()==1142
 keyset=set(zip(f.race_id.astype(str),f.horse_number.astype(int)));rosters=f.groupby('race_id').horse_number.apply(set).to_dict()
 seen=set();quotes={};examined=0
 for page in pages:
  if page['expected_sha256'] not in wanted or page['expected_sha256'] in seen:continue
  path=(ROOT/page['path_relative']).resolve();assert path.is_relative_to(ROOT) and not path.is_symlink()
  assert sha(path)==page['expected_sha256']==page['actual_sha256']
  seen.add(page['expected_sha256']);payload=json.loads(path.read_bytes())
  body=payload['response']['body'];items=(body.get('items') or {}).get('item',[])
  if isinstance(items,dict):items=[items]
  assert len(items)==page['item_count'];examined+=len(items)
  for item in items:
   if item.get('pool')!='PLC' or item.get('meet')!='제주':continue
   day=str(item['rcDate']);rid=f'{day[:4]}-{day[4:6]}-{day[6:]}_2_{int(item["rcNo"])}'
   number=int(item['chulNo']);key=(rid,number)
   if rid not in rosters:continue
   assert key in keyset and int(item.get('chulNo2',0))==int(item.get('chulNo3',0))==0
   assert key not in quotes
   value=float(item['odds']);assert np.isfinite(value) and value>0 and value!=9999.9
   quotes[key]={'race_id':rid,'horse_number':number,'odds':value,'source_sha256':page['expected_sha256']}
 assert seen==wanted and set(quotes)==keyset
 df=pd.DataFrame(quotes.values()).sort_values(['race_id','horse_number'])
 target=STUDY/'ROOT_PLC_REFERENCE.csv';assert not target.exists();df.to_csv(target,index=False)
 report={'status':'PASS','archived_page_index_sha256':sha(inventory),'chosen_page_index_sha256':sha(chosen_path),
  'raw_page_hashes_checked':len(seen),'raw_items_read':examined,'PLC_quotes':len(df),'races':1142,
  'every_cohort_runner_quote_present':True,'invalid_or_special_odds':0,'outcomes_or_metrics_computed':False,'output_sha256':sha(target)}
 dest=STUDY/'ROOT_PLC_SOURCE_REVIEW.json';assert not dest.exists();dest.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()

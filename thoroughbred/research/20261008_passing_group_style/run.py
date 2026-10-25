"""Official passing-group definitions and chronological tendency research."""
from pathlib import Path
import re,json,hashlib,importlib.util
import numpy as np,pandas as pd
H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2];P=H.parent/'20261008_running_style_foundation';SNAP=H.parent/'20261002_moisture_position/outputs/passing_snapshot.parquet'
spec=importlib.util.spec_from_file_location('parent_style',P/'run.py');parent=importlib.util.module_from_spec(spec);spec.loader.exec_module(parent)
NAMES=['선두1두','선두마군','앞선추종','중단','후미'];FOUR=['선행권','앞선추종','중단','후미'];TOKEN=re.compile(r'\((?:\^?\d+,)*\^?\d+\)|\^?\d+')
def dump(p,a):p.write_text(json.dumps(a,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def parse(raw):
 text=re.sub(r'\s+','',raw)
 if not text or len(text)>4096 or any(c not in '0123456789^(),-=≡' for c in text):raise ValueError('unsupported_notation')
 result=[];cursor=0;seen=[]
 for m in TOKEN.finditer(text):
  sep=text[cursor:m.start()]
  if (not result and sep) or (result and sep not in [',','-','=','≡']):raise ValueError('invalid_separator')
  members=[int(s) for s in re.findall(r'\d+',m.group())]
  if min(members)<1:raise ValueError('invalid_number')
  result.append((members,sep));seen+=members;cursor=m.end()
 if not result or cursor!=len(text) or len(seen)!=len(set(seen)):raise ValueError('duplicate_or_trailing')
 return result
def role(idx,b,k,n,a=1/3,z=2/3):
 if idx==0:return 0 if k==1 else 1
 q=(b+(k+1)/2-1)/(n-1)
 return 2 if q<=a else 3 if q<=z else 4
def prepare():
 keep=['row_key','source_key','horse_id','horse_name','meet','date','year','day_key','distance_m','field_size','gate','s1f','s1f_class','s1f_complete','history_supported','prior_count_0','prior_count_1','prior_count_2','prior_count_3','source_file','source_item_index']
 d=pd.read_parquet(P/'outputs/observed_styles.parquet',columns=keep);assert len(d)==159014 and d.row_key.is_unique
 s=pd.read_parquet(SNAP);s['meet']=s.actual_meet_code.map({1:'서울',3:'부산'});s['source_key']=s.meet+':'+pd.to_datetime(s.event_date).dt.strftime('%Y%m%d')+':'+s.race_no.astype(str)
 rosters={key:set(q.gate.astype(int)) for key,q in d.groupby('source_key',sort=False)};assert d.groupby('source_key').gate.nunique().eq(d.groupby('source_key').size()).all()
 rows=[];issues=[];races=[]
 for r in s.itertuples():
  if r.source_key not in rosters:continue
  try:
   packs=parse(r.notation_raw);nums=[n for members,_ in packs for n in members]
   if set(nums)!=rosters[r.source_key]:raise ValueError('roster_mismatch')
  except ValueError as e:
   issues.append(dict(source_key=r.source_key,point=r.canonical_point_code,notation_raw=r.notation_raw,reason=str(e),selected_source=r.selected_source));continue
  n=len(nums);before=0;first=len(packs[0][0]);strict=first==1 and len(packs)>1 and packs[1][1] in ['-','=','≡']
  races.append(dict(source_key=r.source_key,point=r.canonical_point_code,first_group_size=first,group_count=len(packs),field_size=n,solo=first==1,solo_ge2_lengths=strict,notation_raw=r.notation_raw,selected_source=r.selected_source,selection_status=r.selection_status))
  for idx,(members,sep) in enumerate(packs):
   k=len(members);c=role(idx,before,k,n);alt=role(idx,before,k,n,.25,.75);relative=(before+(k+1)/2-1)/(n-1)
   for lateral,num in enumerate(members):rows.append(dict(source_key=r.source_key,point=r.canonical_point_code,gate=num,group_index=idx,group_size=k,group_count=len(packs),first_group_size=first,group_mean_relative=relative,role5=c,role4=max(c-1,0),quarter_role4=max(alt-1,0),first_group=idx==0,solo_ge2_lengths=strict and idx==0,separator=sep,within_group_order=lateral,notation_raw=r.notation_raw,selected_source=r.selected_source,selection_status=r.selection_status))
   before+=k
 rr=pd.DataFrame(rows);assert not rr.duplicated(['source_key','point','gate']).any();rr.to_parquet(O/'passing_group_points.parquet',index=False);pd.DataFrame(races).to_csv(O/'race_group_summary.csv',index=False);pd.DataFrame(issues,columns=['source_key','point','notation_raw','reason','selected_source']).to_csv(O/'notation_issues.csv',index=False)
 early=rr[rr.point.eq('S1F')].drop(columns='point');d=d.merge(early,on=['source_key','gate'],how='left',validate='one_to_one');d['group_observed']=d.role4.notna();d['role4']=d.role4.fillna(-1).astype(int);d['role5']=d.role5.fillna(-1).astype(int)
 d['rank_leader_outside_group']=d.s1f_complete&d.s1f.eq(1)&d.role4.ne(0)&d.group_observed
 conflict=set(d.loc[d.rank_leader_outside_group,'source_key']);d['leader_conflict_race']=d.source_key.isin(conflict)
 common=d[d.group_observed&d.s1f_complete];ct=pd.crosstab(common.s1f_class,common.role4).reindex(index=range(4),columns=range(4),fill_value=0);ct.to_csv(O/'rank_group_crosstab.csv')
 data=dict(inputs={str(p.relative_to(ROOT)):sha(p) for p in [P/'outputs/observed_styles.parquet',SNAP,P/'run.py']},roster_n=len(d),roster_races=d.source_key.nunique(),group_n=int(d.group_observed.sum()),group_races=d.loc[d.group_observed,'source_key'].nunique(),group_horses=d.loc[d.group_observed,'horse_id'].nunique(),missing_n=int((~d.group_observed).sum()),missing_races=d.loc[~d.group_observed,'source_key'].nunique(),issues=len(issues),common_n=len(common),common_races=common.source_key.nunique(),different_n=int(common.role4.ne(common.s1f_class).sum()),different_rate=float(common.role4.ne(common.s1f_class).mean()),first_group_n=int(common.role4.eq(0).sum()),rank_leader_n=int(common.s1f_class.eq(0).sum()),non_rank1_in_first_group=int((common.role4.eq(0)&common.s1f.gt(1)).sum()),rank1_outside_first_group=len(conflict),quarter_different=int(common.quarter_role4.ne(common.role4).sum()),source_start=d.groupby('meet').date.min().astype(str).to_dict(),source_end=d.groupby('meet').date.max().astype(str).to_dict(),operational=False,causal=False)
 dump(O/'source_audit.json',data)
 rows=[]
 for name,q in [('all',common),('api303_only',common[common.selected_source.eq('api303')]),('exclude_leader_conflict',common[~common.leader_conflict_race])]:rows.append(dict(scope=name,n=len(q),different_rate=float(q.role4.ne(q.s1f_class).mean()),non_rank1_front_group=int((q.role4.eq(0)&q.s1f.gt(1)).sum())))
 pd.DataFrame(rows).to_csv(O/'source_sensitivity.csv',index=False)
 return d.sort_values(['horse_id','date']).reset_index(drop=True)
def history(d):
 for i in range(4):
  d[f'count_{i}']=d.role4.eq(i).astype(int).groupby(d.horse_id).transform(lambda s:s.shift(1).rolling(5,min_periods=1).sum()).fillna(0).astype(int)
 d['prior_n']=d.groupby('horse_id').cumcount().clip(upper=5);d['prior_valid']=d.role4.ge(0).astype(int).groupby(d.horse_id).transform(lambda s:s.shift(1).rolling(5,min_periods=1).sum()).fillna(0).astype(int)
 d['prior_last']=d.groupby('horse_id').date.shift(1);d['prior_oldest5']=d.groupby('horse_id').date.shift(5)
 assert d.groupby('horse_id').date.diff().dt.days.dropna().ge(2).all();assert (d.prior_last.isna()|(d.prior_last<=d.date-pd.Timedelta(days=2))).all()
 d['group_history_supported']=d.prior_n.eq(5)&d.prior_valid.eq(5)&(d.date-d.prior_oldest5).dt.days.le(730);d['dominance']=d[[f'count_{i}' for i in range(4)]].max(axis=1)/5;d['mode']=d[[f'count_{i}' for i in range(4)]].to_numpy().argmax(axis=1)
 return d
def evaluation(d):
 results=[];coverage=[]
 for year in [2024,2025]:
  train=d[d.year.lt(year)&d.group_observed].copy();train['s1f_class']=train.role4;current=d[d.year.eq(year)&d.group_observed];q=current[current.group_history_supported].copy();base=parent.baseline(train,q);c=q[[f'count_{i}' for i in range(4)]].to_numpy();pred=(c+3*base)/8;y=np.eye(4)[q.role4]
  for i in range(4):q[f'baseline_p_{i}']=base[:,i];q[f'history_p_{i}']=pred[:,i]
  q['baseline_brier']=((y-base)**2).sum(axis=1);q['history_brier']=((y-pred)**2).sum(axis=1);q['difference']=q.history_brier-q.baseline_brier;q['baseline_hit']=base.argmax(axis=1)==q.role4;q['history_hit']=pred.argmax(axis=1)==q.role4;q['mode_repeat']=q['mode']==q.role4;q['window']=str(year);results.append(q)
  coverage.append(dict(year=year,all_roster=int(d.year.eq(year).sum()),current_observed=len(current),supported=len(q),ineligible=len(current)-len(q),train_n=len(train),train_max_date=str(train.date.max().date())))
 p=pd.concat(results,ignore_index=True);p.to_parquet(O/'temporal_evaluation.parquet',index=False);pd.DataFrame(coverage).to_csv(O/'evaluation_coverage.csv',index=False);rows=[]
 for window in ['2024','2025','2024_2025']:
  a=p if window=='2024_2025' else p[p.window.eq(window)]
  for meet in ['전체','서울','부산']:
   q=a if meet=='전체' else a[a.meet.eq(meet)]
   rows.append(dict(window=window,meet=meet,baseline_accuracy=float(q.baseline_hit.mean()),history_accuracy=float(q.history_hit.mean()),baseline_brier=float(q.baseline_brier.mean()),history_brier=float(q.history_brier.mean()))|parent.cluster(q,q.difference))
 pd.DataFrame(rows).to_csv(O/'evaluation_metrics.csv',index=False)
 rows=[]
 for name,mask in [('all',p.dominance.ge(0)),('dominant3of5',p.dominance.ge(.6)),('strong4of5',p.dominance.ge(.8))]:
  q=p[mask];rows.append(dict(scope=name,n=len(q),repeat=float(q.mode_repeat.mean()),baseline_accuracy=float(q.baseline_hit.mean())))
 pd.DataFrame(rows).to_csv(O/'repeatability.csv',index=False)
 rows=[]
 for i in range(4):
  q=p[p['mode'].eq(i)&p.dominance.ge(.8)];rows.append(dict(style=FOUR[i],n=len(q),repeat=float(q.mode_repeat.mean())))
 pd.DataFrame(rows).to_csv(O/'strong_style_repeatability.csv',index=False)
 both=p[p.history_supported&p.s1f_complete].copy();both['rank_strong_leader']=both.prior_count_0.ge(4);both['group_strong_leader']=both.count_0.ge(4)
 rows=[]
 for name,mask,target in [('rank1_4of5',both.rank_strong_leader,both.s1f_class.eq(0)),('first_group_4of5',both.group_strong_leader,both.role4.eq(0))]:
  q=both[mask];rows.append(dict(definition=name,n=len(q),repeat=float(target[mask].mean())))
 pd.DataFrame(rows).to_csv(O/'front_tendency_comparison.csv',index=False)
 return p
def profiles(d):
 rows=[]
 for horse,q in d.groupby('horse_id',sort=False):
  last=q.iloc[-1];r=dict(horse_id=horse,horse_name=last.horse_name,meet=last.meet,last_date=str(last.date.date()),asof='2026-09-22',recent365=(pd.Timestamp('2026-09-22')-last.date).days<=365,total_n=len(q))
  for look in [5,10]:
   a=q.tail(look);valid=a.group_observed;support=len(a)==look and valid.all() and (pd.Timestamp('2026-09-22')-a.date.min()).days<=730;c=np.bincount(a.loc[valid,'role4'],minlength=4);c5=np.bincount(a.loc[valid,'role5'],minlength=5)
   r[f'valid{look}']=int(valid.sum());r[f'supported{look}']=bool(support);r[f'window_days{look}']=int((pd.Timestamp('2026-09-22')-a.date.min()).days)
   for i in range(5):r[f'role5_count{look}_{i}']=int(c5[i])
   for i in range(4):r[f'role4_count{look}_{i}']=int(c[i])
   r[f'mode{look}']=FOUR[int(c.argmax())] if support and c.max()/look>=.6 else '혼합' if support else '이력부족/미관측';r[f'strong{look}']=bool(support and c.max()/look>=.8);r[f'leader_rate{look}']=float(c[0]/look) if support else None
   r[f'solo_ge2_count{look}']=int(a.solo_ge2_lengths.eq(True).sum())
  # Same five actual roster slots, previous rank definition, no skipping missing observations.
  a=q.tail(5);rs=len(a)==5 and a.s1f_complete.all() and (pd.Timestamp('2026-09-22')-a.date.min()).days<=730;r['rank5_supported']=bool(rs);r['rank5_leader_rate']=float(a.s1f_class.eq(0).mean()) if rs else None;rows.append(r)
 r=pd.DataFrame(rows);r.to_csv(O/'horse_profiles.csv',index=False);r[r.recent365].to_csv(O/'recent_horse_profiles.csv',index=False)
 q=r[r.supported5&r.rank5_supported];summary=dict(asof='2026-09-22',cutoff='2026-09-20',horses=len(r),supported5=int(r.supported5.sum()),recent_supported5=int((r.recent365&r.supported5).sum()),strong5=int((r.supported5&r.strong5).sum()),recent_strong5=int((r.recent365&r.supported5&r.strong5).sum()),comparable_profiles=len(q),rank_leader_60=int(q.rank5_leader_rate.ge(.6).sum()),group_leader_60=int(q.leader_rate5.ge(.6).sum()),new_group_leader_60=int((q.leader_rate5.ge(.6)&q.rank5_leader_rate.lt(.6)).sum()))
 dump(O/'profile_summary.json',summary)
def main():
 assert not (O/'observations.parquet').exists(),'Refusing to overwrite completed study'
 d=history(prepare());d.to_parquet(O/'observations.parquet',index=False);evaluation(d);profiles(d);print('Computed passing group study',flush=True)
if __name__=='__main__':main()

"""Read-only official-position research; independent from production style features."""
from pathlib import Path
from collections import Counter
import gzip,hashlib,json,math
import numpy as np
import pandas as pd
from scipy.stats import t

H=Path(__file__).resolve().parent;O=H/'outputs';ROOT=H.parents[2]
LEDGER=H.parent/'20261007_sex_ability_gap/outputs/selection_ledger.parquet'
RAW=H.parent/'20260929_calendar_api_v1/raw/race_execution_probe'
LABELS=['선두','앞선','중단','후미']
def dump(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def classify(r,n,a=1/3,b=2/3):
 p=(np.asarray(r)-1)/(np.asarray(n)-1)
 return np.select([np.asarray(r)==1,p<=a,p<=b],[0,1,2],default=3)
def prepare():
 ledger=pd.read_parquet(LEDGER);assert len(ledger)==158528 and ledger.row_key.is_unique
 rows=[];hashes={str(LEDGER.relative_to(ROOT)):sha(LEDGER)}
 for path in sorted(p for p in RAW.glob('*/meet_[13].json.gz') if 2018<=int(p.parent.name)<=2026):
  assert path.resolve().is_relative_to(RAW.resolve());hashes[str(path.relative_to(ROOT))]=sha(path)
  items=json.load(gzip.open(path,'rt'))['response']['body']['items']['item']
  for i,r in enumerate(items):
   meet={1:'서울',3:'부산'}[int(path.name.split('_')[1].split('.')[0])];horse=str(r['hrNo']).zfill(7);key=f"{meet}:{r['rcDate']}:{r['rcNo']}";prefix='sj' if meet=='서울' else 'bu'
   rows.append(dict(row_key=key+':'+horse,source_key=key,horse_id=horse,meet=meet,raw_date=int(r['rcDate']),raw_distance=int(r.get('rcDist',0)),raw_finish_rank=float(r['ord']),horse_name=r['hrName'],gate=int(r['chulNo']),s1f=float(r[prefix+'S1fOrd']),g3f=float(r[prefix+'G3fOrd']),g1f=float(r[prefix+'G1fOrd']),s1f_time=float(r['seS1fAccTime'] if meet=='서울' else r['buS1fTime']),source_file=str(path.relative_to(ROOT)),source_item_index=i))
 raw=pd.DataFrame(rows);assert raw.row_key.is_unique
 # Only verified actual race keys, then restore the original non-scratch roster.
 observed=raw[raw.source_key.isin(ledger.source_key)&~raw.raw_finish_rank.isin([93,94,95])].copy()
 context=ledger[['source_key','date','distance_m','field_size','moisture','grade_normalized']].drop_duplicates();assert context.source_key.is_unique
 d=observed.merge(context,on='source_key',validate='many_to_one').merge(ledger[['row_key','selected','selection_reason','body_weight','sex_raw','sex_condition','finish_ms']],on='row_key',how='left',validate='one_to_one')
 d['selected']=d.selected.eq(True);d['selection_reason']=d.selection_reason.fillna('official_roster_nonfinisher_not_in_ledger');d['rank']=d.raw_finish_rank
 assert set(ledger.row_key).issubset(set(d.row_key));assert not d.duplicated(['horse_id','date']).any()
 assert (d.raw_date.astype(str)==d.date.dt.strftime('%Y%m%d')).all();assert ((d.raw_distance==0)|(d.raw_distance==d.distance_m)).all()
 d['year']=d.date.dt.year;d['day_key']=d.date.dt.strftime('%Y-%m-%d')
 raw_n=observed.groupby('source_key').size();assert d.source_key.map(raw_n).eq(d.field_size).all()
 races=[]
 for key,q in d.groupby('source_key',sort=False):
  n=int(q.field_size.iloc[0]);record=dict(source_key=key,meet=q.meet.iloc[0],date=str(q.date.iloc[0].date()),field_size=n,roster_rows=len(q))
  for point in ['s1f','g3f','g1f']:
   record[point+'_complete']=len(q)==n and sorted(q[point].tolist())==list(range(1,n+1))
  races.append(record)
 race=pd.DataFrame(races);d=d.merge(race[['source_key','s1f_complete','g3f_complete','g1f_complete']],on='source_key',validate='many_to_one')
 for point in ['s1f','g3f','g1f']:
  d[point+'_p']=((d[point]-1)/(d.field_size-1)).where(d[point+'_complete'])
  d[point+'_class']=np.where(d[point+'_complete'],classify(d[point],d.field_size),-1).astype(int)
 d['finish_p']=((d['rank']-1)/(d.field_size-1)).where(d['rank'].between(1,d.field_size))
 d['early_to_600_gain']=d.s1f_p-d.g3f_p;d['last600_gain']=d.g3f_p-d.finish_p;d['last200_gain']=d.g1f_p-d.finish_p
 valid=d.s1f_complete;d['quarter_class']=np.where(valid,classify(d.s1f,d.field_size,.25,.75),-1).astype(int)
 pct=d.s1f/d.field_size
 d['existing_feature_rule']=np.where(valid,np.select([pct<.35,pct<.55,pct<.75],[0,1,2],default=3),-1).astype(int)
 d['existing_web_rule']=np.where(valid,np.select([pct<=.25,pct<=.50,pct<=.75],[0,1,2],default=3),-1).astype(int)
 d=d.sort_values(['horse_id','date']).reset_index(drop=True);race.to_csv(O/'race_coverage.csv',index=False)
 audit=dict(input_sha256=hashes,raw_rows=len(raw),raw_races=raw.source_key.nunique(),ledger_rows=len(ledger),ledger_races=ledger.source_key.nunique(),roster_rows=len(d),roster_horses=d.horse_id.nunique(),restored_nonfinishers=len(d)-len(ledger),raw_outside_verified_roster=len(raw)-len(d),raw_outside_verified_roster_examples=raw[~raw.row_key.isin(d.row_key)].row_key.head(10).tolist(),valid_s1f_rows=int(valid.sum()),valid_s1f_races=int(race.s1f_complete.sum()),normal_record_rows_in_style=int((d.selected&d.s1f_complete).sum()),outside_normal_record_rows_in_style=int((~d.selected&d.s1f_complete).sum()),no_valid_finish_in_style=int((d.s1f_complete&d.finish_p.isna()).sum()),source_start=d.groupby('meet').date.min().astype(str).to_dict(),source_end=d.groupby('meet').date.max().astype(str).to_dict(),official_ranks=True,uses_track_speed=False,causal=False,operational=False)
 dump(O/'source_audit.json',audit);return d
def history(d):
 counts=np.zeros((len(d),4),int);same=np.zeros_like(counts);n=np.zeros(len(d),int);nv=np.zeros(len(d),int);ns=np.zeros(len(d),int);nsv=np.zeros(len(d),int);old=np.full(len(d),np.datetime64('NaT','ns'),dtype='datetime64[ns]');last=old.copy();sold=old.copy();slast=old.copy();means=np.full(len(d),np.nan);smeans=means.copy()
 for _,q in d.groupby('horse_id',sort=False):
  idx=q.index.to_numpy();dates=q.date.to_numpy();styles=q.s1f_class.to_numpy();pos=q.s1f_p.to_numpy();contexts=(q.meet+':'+q.distance_m.astype(str)).to_numpy();by={key:np.flatnonzero(contexts==key) for key in set(contexts)}
  for j,i in enumerate(idx):
   k=np.searchsorted(dates,dates[j]-np.timedelta64(2,'D'),side='right');ii=np.arange(max(0,k-5),k);n[i]=len(ii)
   if len(ii):
    valid=styles[ii]>=0;nv[i]=valid.sum();counts[i]=np.bincount(styles[ii][valid],minlength=4);old[i]=dates[ii[0]];last[i]=dates[ii[-1]];means[i]=np.nanmean(pos[ii]) if valid.any() else np.nan
   si=by[contexts[j]];ii=si[si<k][-5:];ns[i]=len(ii)
   if len(ii):
    valid=styles[ii]>=0;nsv[i]=valid.sum();same[i]=np.bincount(styles[ii][valid],minlength=4);sold[i]=dates[ii[0]];slast[i]=dates[ii[-1]];smeans[i]=np.nanmean(pos[ii]) if valid.any() else np.nan
 for z in range(4):d['prior_count_'+str(z)]=counts[:,z];d['same_count_'+str(z)]=same[:,z]
 d['prior_n']=n;d['prior_valid_n']=nv;d['prior_oldest']=old;d['prior_last']=last;d['prior_mean_p']=means;d['same_n']=ns;d['same_valid_n']=nsv;d['same_oldest']=sold;d['same_last']=slast;d['same_mean_p']=smeans
 d['history_supported']=(n==5)&(nv==5)&((d.date-pd.to_datetime(old)).dt.days<=730)
 d['same_supported']=(ns==5)&(nsv==5)&((d.date-pd.to_datetime(sold)).dt.days<=730)
 d['prior_mode']=counts.argmax(axis=1);d['prior_dominance']=counts.max(axis=1)/5;d['prior_strong']=d.history_supported&d.prior_dominance.ge(.8);d['prior_dominant']=d.history_supported&d.prior_dominance.ge(.6)
 assert (d.prior_last.isna()|(d.prior_last<=d.date-pd.Timedelta(days=2))).all();return d
def baseline(train,test):
 global_p=np.bincount(train.s1f_class,minlength=4)/len(train);dist={};field={}
 for key,q in train.groupby(['meet','distance_m']):dist[key]=np.bincount(q.s1f_class,minlength=4)/len(q)
 for key,q in train.groupby(['meet','distance_m','field_size']):field[key]=np.bincount(q.s1f_class,minlength=4)
 result=[]
 for r in test.itertuples():
  b=dist.get((r.meet,r.distance_m),global_p);c=field.get((r.meet,r.distance_m,r.field_size),np.zeros(4));result.append((c+20*b)/(sum(c)+20))
 return np.array(result)
def cluster(q,values,weights=None):
 v=np.asarray(values,float);w=np.ones(len(q)) if weights is None else np.asarray(weights,float);est=float(w@v/w.sum());s=w*(v-est)/w.sum();vs=[];groups=[]
 for ids in [q.horse_id,q.day_key,q.horse_id+':'+q.day_key]:
  c=pd.factorize(ids)[0];g=c.max()+1;score=np.bincount(c,weights=s);vs.append(float(score@score)*g/(g-1));groups.append(g)
 se=math.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));crit=t.ppf(.975,min(groups[:2])-1)
 return dict(estimate=est,se=se,lower=est-crit*se,upper=est+crit*se,n=len(q),horses=q.horse_id.nunique(),dates=q.day_key.nunique(),races=q.source_key.nunique())
def evaluation(d):
 predictions=[];coverage=[]
 for year in [2024,2025]:
  train=d[d.year.lt(year)&d.s1f_complete];alltest=d[d.year.eq(year)&d.s1f_complete];q=alltest[alltest.history_supported].copy();p0=baseline(train,q);y=np.eye(4)[q.s1f_class];c=q[['prior_count_'+str(i) for i in range(4)]].to_numpy();sc=q[['same_count_'+str(i) for i in range(4)]].to_numpy()
  q['baseline_brier']=((y-p0)**2).sum(axis=1);q['baseline_hit']=p0.argmax(axis=1)==q.s1f_class
  for i in range(4):q['baseline_p_'+str(i)]=p0[:,i]
  for strength in [1,3,5,10]:
   p=(c+strength*p0)/(5+strength);q[f'history_brier_{strength}']=((y-p)**2).sum(axis=1)
   if strength==3:
    q['history_hit']=p.argmax(axis=1)==q.s1f_class
    for i in range(4):q['history_p_'+str(i)]=p[:,i]
  p=(sc+3*p0)/(5+3);q['same_brier']=np.where(q.same_supported,((y-p)**2).sum(axis=1),np.nan)
  q['prior_mode_hit']=q.prior_mode.eq(q.s1f_class);q['prior_position_mae']=abs(q.s1f_p-q.prior_mean_p);q['brier_difference']=q.history_brier_3-q.baseline_brier
  q['window']=str(year);predictions.append(q);coverage.append(dict(year=year,all_actual_rows=int(d.year.eq(year).sum()),valid_current=len(alltest),prior5_supported=len(q),same_distance_supported=int(q.same_supported.sum()),history_ineligible=len(alltest)-len(q),train_n=len(train),train_max_date=str(train.date.max().date())))
 p=pd.concat(predictions,ignore_index=True);p.to_parquet(O/'temporal_evaluation.parquet',index=False);pd.DataFrame(coverage).to_csv(O/'evaluation_coverage.csv',index=False);rows=[]
 for window in ['2024','2025','2024_2025']:
  a=p if window=='2024_2025' else p[p.window.eq(window)]
  for meet in ['전체','서울','부산']:
   q=a if meet=='전체' else a[a.meet.eq(meet)]
   for weighting in ['start','race_equal']:
    w=np.ones(len(q)) if weighting=='start' else 1/q.groupby('source_key').row_key.transform('size').to_numpy();rows.append(dict(window=window,meet=meet,weighting=weighting,baseline_brier=float(np.average(q.baseline_brier,weights=w)),history_brier=float(np.average(q.history_brier_3,weights=w)),baseline_accuracy=float(np.average(q.baseline_hit,weights=w)),history_accuracy=float(np.average(q.history_hit,weights=w)))|cluster(q,q.brier_difference,w))
 pd.DataFrame(rows).to_csv(O/'evaluation_metrics.csv',index=False)
 rows=[]
 for k in [1,3,5,10]:rows.append(dict(strength=k,baseline_brier=float(p.baseline_brier.mean()),history_brier=float(p[f'history_brier_{k}'].mean()))|cluster(p,p[f'history_brier_{k}']-p.baseline_brier))
 pd.DataFrame(rows).to_csv(O/'shrinkage_sensitivity.csv',index=False)
 q=p[p.same_supported];pd.DataFrame([dict(comparison='same_distance_minus_mixed_history',mixed_brier=float(q.history_brier_3.mean()),same_distance_brier=float(q.same_brier.mean()))|cluster(q,q.same_brier-q.history_brier_3)]).to_csv(O/'same_distance_comparison.csv',index=False)
 rows=[]
 for meet in ['전체','서울','부산']:
  a=p if meet=='전체' else p[p.meet.eq(meet)]
  for scope in ['all','dominant_3of5','strong_4of5']:
   q=a if scope=='all' else a[a.prior_dominance.ge(.6 if scope=='dominant_3of5' else .8)]
   rows.append(dict(meet=meet,scope=scope,n=len(q),horses=q.horse_id.nunique(),mode_repeat=float(q.prior_mode_hit.mean()),baseline_accuracy=float(q.baseline_hit.mean()),history_accuracy=float(q.history_hit.mean())))
 pd.DataFrame(rows).to_csv(O/'repeatability.csv',index=False)
 rows=[]
 for style,q in p[p.prior_dominant].groupby('prior_mode'):
  rows.append(dict(prior_style=LABELS[style],n=len(q),strong_n=int(q.prior_strong.sum()),repeat=float(q.prior_mode_hit.mean()),strong_repeat=float(q.loc[q.prior_strong,'prior_mode_hit'].mean()),mean_prior_fraction=float(q.prior_dominance.mean())))
 pd.DataFrame(rows).to_csv(O/'style_repeatability.csv',index=False)
 return p
def describe(d):
 q=d[d.s1f_complete];q.groupby(['meet','distance_m','year','s1f_class']).size().rename('n').reset_index().to_csv(O/'style_distribution.csv',index=False)
 pd.crosstab(q.s1f_class,q.g3f_class).to_csv(O/'early_middle_transition.csv')
 rows=[]
 for k,g in q.groupby('s1f_class'):
  late=g.last600_gain.dropna();rows.append(dict(style=LABELS[k],n=len(g),last600_observed=len(late),last600_gain_mean=float(late.mean()),last600_gain_ge_20pct=float(late.ge(.2).mean()),middle_forward_rate=float(g.loc[g.g3f_complete,'g3f_class'].le(1).mean())))
 pd.DataFrame(rows).to_csv(O/'position_movement.csv',index=False)
 rows=[]
 for col in ['quarter_class','existing_feature_rule','existing_web_rule']:
  rows.append(dict(alternative=col,n=len(q),different_from_primary=int(q[col].ne(q.s1f_class).sum()),difference_rate=float(q[col].ne(q.s1f_class).mean()),label0_n=int(q[col].eq(0).sum()),label0_nonleaders=int((q[col].eq(0)&q.s1f.gt(1)).sum())))
 pd.DataFrame(rows).to_csv(O/'definition_sensitivity.csv',index=False)
def profiles(d):
 asof=pd.Timestamp('2026-09-22');rows=[];specific=[]
 for horse,q in d.groupby('horse_id',sort=False):
  a=q[q.date.le(asof-pd.Timedelta(days=2))];last=a.iloc[-1];r=dict(horse_id=horse,horse_name=last.horse_name,last_meet=last.meet,total_observed=len(a),last_date=str(last.date.date()),days_since_last=int((asof-last.date).days),asof=str(asof.date()),last_distance=int(last.distance_m))
  for look in [5,10]:
   g=a.tail(look);valid=g.s1f_class.ge(0);c=np.bincount(g.loc[valid,'s1f_class'],minlength=4);supported=len(g)==look and valid.all() and (asof-g.date.min()).days<=730
   r[f'window{look}_n']=len(g);r[f'window{look}_valid']=int(valid.sum());r[f'window{look}_days']=int((asof-g.date.min()).days);r[f'window{look}_supported']=bool(supported)
   for i in range(4):r[f'window{look}_count_{i}']=int(c[i])
   r[f'window{look}_mode']=LABELS[int(c.argmax())] if supported and c.max()/look>=.6 else '혼합' if supported else '이력부족/미관측';r[f'window{look}_dominance']=float(c.max()/look) if supported else None
   r[f'window{look}_mean_p']=float(g.s1f_p.mean()) if valid.any() else None
   r[f'window{look}_middle_valid']=int(g.g3f_complete.sum());r[f'window{look}_late_valid']=int(g.last600_gain.notna().sum())
   r[f'window{look}_middle_front_rate']=float(g.loc[g.g3f_complete,'g3f_class'].le(1).mean()) if g.g3f_complete.any() else None
   for col in ['early_to_600_gain','last600_gain','last200_gain']:r[f'window{look}_{col}']=float(g[col].mean()) if g[col].notna().any() else None
  r['strong5']=bool(r['window5_supported'] and r['window5_dominance']>=.8);r['recent365']=r['days_since_last']<=365;rows.append(r)
  for (meet,dist),b in a.groupby(['meet','distance_m']):
   g=b.tail(5);v=g.s1f_class.ge(0);c=np.bincount(g.loc[v,'s1f_class'],minlength=4);supported=len(g)==5 and v.all() and (asof-g.date.min()).days<=730
   specific.append(dict(horse_id=horse,horse_name=last.horse_name,meet=meet,distance_m=int(dist),total_n=len(b),recent5_n=len(g),valid_n=int(v.sum()),supported=bool(supported),last_date=str(g.date.max().date()),span_to_asof_days=int((asof-g.date.min()).days),mode=LABELS[int(c.argmax())] if supported and c.max()>=3 else '혼합' if supported else '이력부족/미관측',**{f'count_{i}':int(c[i]) for i in range(4)}))
 r=pd.DataFrame(rows);r.to_csv(O/'horse_style_profiles.csv',index=False);r[r.recent365].to_csv(O/'recent_horse_style_profiles.csv',index=False);pd.DataFrame(specific).to_parquet(O/'horse_distance_style_profiles.parquet',index=False)
 summary=dict(asof='2026-09-22',cutoff='2026-09-20',horses=len(r),supported5=int(r.window5_supported.sum()),strong5=int(r.strong5.sum()),dominant5=int((r.window5_supported&r.window5_dominance.ge(.6)).sum()),mixed5=int((r.window5_supported&r.window5_mode.eq('혼합')).sum()),supported10=int(r.window10_supported.sum()),recent365=int(r.recent365.sum()),recent_supported5=int((r.recent365&r.window5_supported).sum()),recent_strong5=int((r.recent365&r.strong5).sum()))
 both=r[r.window5_supported&r.window10_supported];summary['both5_10']=len(both);summary['same5_10_mode']=float(both.window5_mode.eq(both.window10_mode).mean());dump(O/'profile_summary.json',summary)
def main():
 assert not (O/'observed_styles.parquet').exists(),'Refusing to overwrite completed analysis'
 d=prepare();print('Prepared',len(d),flush=True);d=history(d);d.to_parquet(O/'observed_styles.parquet',index=False);describe(d);evaluation(d);profiles(d);print('Computed descriptive styles and temporal repeatability',flush=True)
if __name__=='__main__':main()

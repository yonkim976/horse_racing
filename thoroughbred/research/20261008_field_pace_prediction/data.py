"""Immutable inputs, annual section references and strictly prior field features."""
from pathlib import Path
import hashlib,json,gzip
import numpy as np,pandas as pd
from sklearn.linear_model import Ridge
H=Path(__file__).resolve().parent;ROOT=H.parents[2];R=H.parent;O=H/'outputs';M=H/'models'
INPUTS=[R/'20261008_horse_style_performance/outputs/roster.parquet',R/'20261008_running_style_foundation/outputs/observed_styles.parquet',R/'20261007_sex_ability_gap/outputs/population.parquet']
GRADES=['국6','국5','국4','혼4','국3','혼3','2','1','국OPEN','혼OPEN'];DIST=[1000,1200,1300,1400,1600,1700,1800,1900,2000,2200,2300]
LABELS=['선행','선입','중단','후미']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def env_matrix(p,conditional=False):
 cols={}
 for meet in ['서울','부산']:
  for dist in DIST:cols[f'{meet}_{dist}']=(p.meet.eq(meet)&p.distance_m.eq(dist)).to_numpy(float)
 for m in range(1,13):cols['month'+str(m)]=p.date.dt.month.eq(m).to_numpy(float)
 cols['moisture']=p.moisture.to_numpy(float);cols['moisture2']=p.moisture.to_numpy(float)**2
 if conditional:
  for grade in GRADES:cols['grade_'+grade]=p.grade.eq(grade).to_numpy(float)
  for col in ['early','rating','age','weight']:cols[col]=p[col].to_numpy(float)
  cols['middle1_per1000']=p.middle1.to_numpy(float)*1000/(p.distance_m.to_numpy()-800)
 return np.column_stack(list(cols.values())),list(cols)
def reference_fit(x,y):
 med=np.nanmedian(x,axis=0);med=np.where(np.isfinite(med),med,0);filled=np.where(np.isfinite(x),x,med);mean=filled.mean(axis=0);sd=filled.std(axis=0);sd[sd<1e-8]=1.;z=(filled-mean)/sd;fit=Ridge(alpha=10.,solver='cholesky').fit(z,y)
 return dict(medians=med,means=mean,sds=sd,beta=fit.coef_,intercept=np.atleast_1d(fit.intercept_))
def reference_predict(x,sp):return ((np.where(np.isfinite(x),x,sp['medians'])-sp['means'])/sp['sds'])@sp['beta'].T+sp['intercept']
def sections(p):
 q=p.copy().reset_index(drop=True);base,bnames=env_matrix(q);cond,cnames=env_matrix(q,True);store={};details=[]
 for col in ['early_adv','last600_adv','late_adv','late_cond_adv']:q[col]=np.nan
 for year in range(2019,2027):
  tr=q.year.lt(year).to_numpy();te=q.year.eq(year).to_numpy();s=reference_fit(base[tr],q.loc[tr,['early','last600','late']].to_numpy());cs=reference_fit(cond[tr],q.loc[tr,'late'].to_numpy());pred=reference_predict(base[te],s);cp=reference_predict(cond[te],cs).ravel();q.loc[te,['early_adv','last600_adv','late_adv']]=pred-q.loc[te,['early','last600','late']].to_numpy();q.loc[te,'late_cond_adv']=cp-q.loc[te,'late'].to_numpy()
  for prefix,obj in [('base',s),('conditional',cs)]:
   for key,val in obj.items():store[f'{year}_{prefix}_{key}']=val
  details.append(dict(year=year,train_n=int(tr.sum()),test_n=int(te.sum()),train_end=str(q.loc[tr,'date'].max().date())))
 for col,out in [('early','early_peer_adv'),('last600','last600_peer_adv'),('late','late_peer_adv')]:q[out]=q.groupby('source_key')[col].transform('mean')-q[col]
 q['late_cond_fast']=np.where(q.late_cond_adv.notna(),q.late_cond_adv.gt(0).astype(float),np.nan)
 q['late_cond_slow']=np.where(q.late_cond_adv.notna(),q.late_cond_adv.lt(0).astype(float),np.nan)
 keep=['row_key','source_key','horse_id','date','year','meet','distance_m','grade','moisture','age','weight','rating','early','middle1','middle2','late','last600','finish','early_adv','last600_adv','late_adv','late_cond_adv','early_peer_adv','last600_peer_adv','late_peer_adv','late_cond_fast','late_cond_slow']
 q[keep].to_parquet(O/'section_observations.parquet',index=False);np.savez_compressed(M/'environment_models.npz',**store);dump(M/'environment_models.json',dict(base_names=bnames,conditional_names=cnames,models=details,first_year_unadjusted=2018));return q[keep]
def prepare():
 a=pd.read_parquet(INPUTS[0]);f=pd.read_parquet(INPUTS[1]);p=pd.read_parquet(INPUTS[2]);assert len(a)==159014 and len(p)==151074 and a.row_key.is_unique and f.row_key.is_unique and p.row_key.is_unique
 a=a.merge(f[['row_key','g3f','g1f','g3f_p','g1f_p','g3f_complete','g1f_complete']],on='row_key',validate='one_to_one');raw=[];inputs=[]
 for filename,g in a.groupby('source_file',sort=True):
  path=(ROOT/filename).resolve();assert path.is_relative_to(ROOT);inputs.append(dict(path=filename,bytes=path.stat().st_size,sha256=sha(path)))
  with gzip.open(path,'rt') as stream:items=json.load(stream)['response']['body']['items']['item']
  for row in g.itertuples():
   item=items[row.source_item_index];assert str(item['hrNo']).zfill(7)==row.horse_id and str(item['rcDate'])==row.date.strftime('%Y%m%d') and int(item['chulNo'])==row.gate
   def ident(k):
    v=str(item.get(k,'')).strip();return v if v.isdigit() and int(v)>0 else ''
   age=float(item.get('age',0));raw.append(dict(row_key=row.row_key,jockey_id=ident('jkNo'),trainer_id=ident('trNo'),jockey_name=str(item.get('jkName','')),trainer_name=str(item.get('trName','')),age_current=age if age>0 else np.nan))
 a=a.merge(pd.DataFrame(raw),on='row_key',validate='one_to_one').sort_values(['horse_id','date']).reset_index(drop=True);assert a.groupby('horse_id').date.diff().dt.days.dropna().ge(2).all()
 a['grade_num']=a.grade_normalized.map({'국6':6,'국5':5,'국4':4,'혼4':4,'국3':3,'혼3':3,'2':2,'1':1});a['grade_bucket']=a.grade_num.map({6:'국6',5:'국5',4:'4등급',3:'3등급',2:'2등급',1:'1등급'}).fillna('OPEN')
 sec=sections(p);a=a.merge(sec.drop(columns=['source_key','horse_id','date','year','meet','distance_m','grade','age','weight']),on='row_key',how='left',validate='one_to_one')
 a['recovery']=np.where(a.g3f_complete&a.normal_outcome,(a.g3f_p.ge(.5)&(a.g3f_p-a.finish_p).ge(.25)).astype(float),np.nan)
 a['fade']=np.where(a.group_observed&a.normal_outcome,(a.role4.le(1)&(a.finish_p-a.group_mean_relative).ge(.30)).astype(float),np.nan)
 a.to_parquet(O/'observations.parquet',index=False)
 audit=dict(roster_n=len(a),races=a.source_key.nunique(),horses=a.horse_id.nunique(),early_observed=int(a.group_observed.sum()),recovery_observed=int(a.recovery.notna().sum()),fade_observed=int(a.fade.notna().sum()),normal_sections_n=len(sec),start_by_meet=a.groupby('meet').date.min().astype(str).to_dict(),end_by_meet=a.groupby('meet').date.max().astype(str).to_dict(),inputs=[dict(path=str(x.relative_to(ROOT)),bytes=x.stat().st_size,sha256=sha(x)) for x in INPUTS]+inputs,uses_track_speed=False,operational=False,direct_intention_labels=False,prerace_publication_timestamps_audited=False)
 dump(O/'source_audit.json',audit);return a
HISTORY_VALUES=['group_mean_relative','solo_rate','early','early_adv','early_peer_adv','last600','last600_adv','last600_peer_adv','late','late_adv','late_peer_adv','late_cond_adv','rating','finish_p','recovery','fade','late_cond_fast','late_cond_slow']
def histories(a):
 a=a.sort_values(['horse_id','date']).reset_index(drop=True);n=len(a);r=pd.DataFrame(index=a.index);r['past_total']=a.groupby('horse_id').cumcount();r['gate_relative']=(a.gate-1)/(a.field_size-1);r['distance_change']=np.nan;r['grade_change']=np.nan
 role=a.role4.to_numpy();value=a[HISTORY_VALUES[0:1]+HISTORY_VALUES[2:]].copy();value.insert(1,'solo_rate',np.where(a.group_observed,a.role5.eq(0).astype(float),np.nan));v=value.to_numpy(float);horse=a.horse_id.to_numpy();date=a.date.to_numpy('datetime64[D]').astype('int64');sums=np.zeros_like(v);squares=np.zeros_like(v);counts=np.zeros_like(v);roles=np.zeros((n,4));validpos=np.zeros(n);slot=np.zeros(n);freshslots=np.zeros(n)
 rows=np.arange(n)
 for lag in range(1,11):
  ix=np.maximum(0,rows-lag);same=(rows>=lag)&(horse[ix]==horse);age=date-date[ix];fresh=same&(age>=2)&(age<=730);vv=v[ix];finite=np.isfinite(vv)&fresh[:,None];sums+=np.where(finite,vv,0);squares+=np.where(finite,vv*vv,0);counts+=finite;slot+=same;freshslots+=fresh;observed=fresh&(role[ix]>=0);validpos+=observed
  for c in range(4):roles[:,c]+=observed&(role[ix]==c)
  if lag==1:
   r['history_last']=pd.to_datetime(np.where(same,a.date.to_numpy()[ix],np.datetime64('NaT')));r['gap_days']=np.where(same,age,np.nan);r['last_distance']=np.where(fresh,a.distance_m.to_numpy()[ix],np.nan);r['last_grade_num']=np.where(fresh,a.grade_num.to_numpy()[ix],np.nan);r['distance_change']=a.distance_m-r.last_distance;r['grade_change']=r.last_grade_num-a.grade_num;r['jockey_changed']=np.where(fresh,(a.jockey_id.to_numpy()[ix]!=a.jockey_id.to_numpy()).astype(float),np.nan)
  if lag in [5,10]:
   r[f'slots{lag}']=slot.copy();r[f'fresh_slots{lag}']=freshslots.copy();r[f'valid_position{lag}']=validpos.copy();r[f'history_oldest{lag}']=pd.to_datetime(np.where(same,a.date.to_numpy()[ix],np.datetime64('NaT')))
   for j,col in enumerate(HISTORY_VALUES):
    r[f'{col}_n{lag}']=counts[:,j].copy();r[f'{col}_mean{lag}']=np.divide(sums[:,j],counts[:,j],out=np.full(n,np.nan),where=counts[:,j]>0)
   for c in range(4):r[f'count{lag}_{c}']=roles[:,c].copy();r[f'rate{lag}_{c}']=np.divide(roles[:,c],validpos,out=np.full(n,np.nan),where=validpos>0)
   r[f'position_sd{lag}']=np.sqrt(np.maximum(0,np.divide(squares[:,0],counts[:,0],out=np.full(n,np.nan),where=counts[:,0]>0)-r[f'group_mean_relative_mean{lag}']**2));r[f'lead_prior{lag}']=(roles[:,0]+1)/(validpos+4)
 r['supported5']=r.slots5.eq(5)&r.valid_position5.eq(5);r['strong5']=r[[f'count5_{j}' for j in range(4)]].max(axis=1).ge(4)&r.supported5;r['mode5']=r[[f'count5_{j}' for j in range(4)]].to_numpy().argmax(axis=1)
 assert (r.history_last.isna()|(r.history_last<=a.date-pd.Timedelta(days=2))).all();return pd.concat([a,r],axis=1)
def entities(q):
 q=q.copy();lead=np.where(q.group_observed,q.role4.eq(0).astype(float),np.nan);res=lead-q.lead_prior5.to_numpy();dates=q.date.to_numpy('datetime64[D]').astype('int64')
 for kind in ['jockey','trainer']:
  out=np.full((len(q),4),np.nan);last=np.full(len(q),np.datetime64('NaT'),'datetime64[ns]')
  for ident,idx in q.groupby(kind+'_id').groups.items():
   if not ident:continue
   idx=np.asarray(idx);idx=idx[np.argsort(dates[idx],kind='stable')];dd=dates[idx];ok=np.isfinite(lead[idx]);vals=np.column_stack([ok,np.where(ok,lead[idx],0),np.where(ok,res[idx],0)]);cs=np.vstack([np.zeros(3),np.cumsum(vals,axis=0)]);lo=np.searchsorted(dd,dd-365,'left');hi=np.searchsorted(dd,dd-2,'right');z=cs[hi]-cs[lo];out[idx,0]=z[:,0];out[idx,1]=(z[:,1]+5)/(z[:,0]+20);out[idx,2]=z[:,2]/(z[:,0]+20);out[idx,3]=hi-lo;has=hi>lo;last[idx[has]]=q.date.to_numpy()[idx[hi[has]-1]]
  q[kind+'_history_n']=out[:,0];q[kind+'_lead_rate']=out[:,1];q[kind+'_conditional_front']=out[:,2];q[kind+'_roster_n']=out[:,3];q[kind+'_history_last']=pd.to_datetime(last)
 return q
FIELD_BASE=['early_mean5','early_adv_mean5','lead_prior5','late_cond_adv_mean5','rating_mean5']
def field_features(q):
 q=q.copy();r=pd.DataFrame(index=q.index)
 for col in FIELD_BASE:
  g=q.groupby('source_key')[col];total=g.transform('sum');count=g.transform('count');own=q[col];others=count-own.notna().astype(int);r['field_other_'+col]=(total-own.fillna(0))/others.replace(0,np.nan);r['field_gap_'+col]=own-r['field_other_'+col];r['field_coverage_'+col]=others/(q.field_size-1)
 for col,ascending in [('early_mean5',True),('early_adv_mean5',False)]:
  ranks=q.groupby('source_key')[col].rank(method='average',ascending=ascending);known=q.groupby('source_key')[col].transform('count');r['field_rank_'+col]=(ranks-1)/(known-1).replace(0,np.nan)
 r['field_lead_sum_other']=q.groupby('source_key').lead_prior5.transform('sum')-q.lead_prior5
 strong=q.count5_0.ge(3).astype(int);r['field_strong_front_other']=strong.groupby(q.source_key).transform('sum')-strong
 r['field_inner_front_sum']=np.nan;r['field_fastest_other_raw']=np.nan;r['field_best_other_adv']=np.nan
 for key,idx in q.groupby('source_key').groups.items():
  idx=np.asarray(idx);g=q.loc[idx];gate=g.gate.to_numpy();r.loc[idx,'field_inner_front_sum']=(gate[:,None]>gate[None,:])@g.lead_prior5.to_numpy()
  for col,out,func in [('early_mean5','field_fastest_other_raw',np.nanmin),('early_adv_mean5','field_best_other_adv',np.nanmax)]:
   x=g[col].to_numpy();mat=np.tile(x,(len(g),1));np.fill_diagonal(mat,np.nan);valid=np.isfinite(mat).any(axis=1);val=np.full(len(g),np.nan);val[valid]=func(mat[valid],axis=1);r.loc[idx,out]=val
 r['field_gap_fastest_raw']=q.early_mean5-r.field_fastest_other_raw;r['field_gap_best_adv']=q.early_adv_mean5-r.field_best_other_adv
 return pd.concat([q,r],axis=1)
def features(q):
 x=pd.DataFrame(index=q.index)
 for meet in ['서울','부산']:x['meet_'+meet]=q.meet.eq(meet).astype(float)
 for grade in GRADES:x['grade_'+grade]=q.grade_normalized.eq(grade).astype(float)
 for dist in DIST:x['distance_'+str(dist)]=q.distance_m.eq(dist).astype(float)
 base=['field_size','gate','gate_relative','age_current','distance_m','grade_num','past_total','gap_days','distance_change','grade_change','jockey_changed']
 for col in base:x[col]=q[col]
 x['month_sin']=np.sin(2*np.pi*q.date.dt.month/12);x['month_cos']=np.cos(2*np.pi*q.date.dt.month/12)
 position=[];section=[]
 for window in [5,10]:
  position +=[f'slots{window}',f'fresh_slots{window}',f'valid_position{window}',f'position_sd{window}',f'lead_prior{window}']+[f'{p}{window}_{j}' for p in ['count','rate'] for j in range(4)]
  for col in HISTORY_VALUES:
   dest=position if col in ['group_mean_relative','solo_rate','finish_p','recovery','fade','rating'] else section;dest +=[f'{col}_mean{window}',f'{col}_n{window}']
 for col in position+section:x[col]=q[col]
 field=[c for c in q if c.startswith('field_') and c!='field_size'];entity=[f'{k}_{v}' for k in ['jockey','trainer'] for v in ['history_n','lead_rate','conditional_front','roster_n']]
 for col in field+entity:x[col]=q[col]
 basic=[c for c in x if c not in section+field+entity];groups=dict(P=basic,S=basic+section,F=basic+section+field,J=basic+section+field+entity)
 assert len(set(x.columns))==len(x.columns);return x.astype(float),groups
def build():
 assert not (O/'feature_frame.parquet').exists(),'Refusing to overwrite finished features'
 a=prepare();q=field_features(entities(histories(a)));x,groups=features(q);q.to_parquet(O/'feature_context.parquet',index=False);x.to_parquet(O/'feature_frame.parquet',index=False);dump(O/'feature_groups.json',groups)
 q.groupby(['year','meet','grade_bucket']).agg(n=('row_key','size'),early=('group_observed','sum'),supported5=('supported5','sum'),recovery=('recovery','count'),fade=('fade','count')).reset_index().to_csv(O/'coverage.csv',index=False);print('Prepared',len(q),'rows',x.shape[1],'features',flush=True);return q,x,groups
if __name__=='__main__':build()

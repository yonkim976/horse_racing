"""Fixed saved out-of-time predictions: condition diagnostics, no model fitting."""
from pathlib import Path
import gzip, hashlib, json, math, re
import numpy as np
import pandas as pd
from scipy.stats import t, false_discovery_control

H=Path(__file__).resolve().parent; R=H.parent; ROOT=H.parents[2]; O=H/'outputs'
P=R/'20261008_field_pace_prediction'; D=R/'20261008_bilateral_field_pace'
LABELS=['선행','선입','중단','후미']; STATES=['건조','양호','다습','포화','불량']
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def state(m):
    return '건조' if 2<=m<=5 else '양호' if 6<=m<=9 else '다습' if 10<=m<=14 else '포화' if 15<=m<=19 else '불량' if m==20 else '미관측'
def interval(g,v):
    v=np.asarray(v,float); mean=float(v.mean()); return score_interval(g,(v-mean)/len(v),mean)
def score_interval(g,score,mean):
    vs=[]; ns=[]
    for ids in [g.horse_id.astype(str),g.date.dt.strftime('%Y-%m-%d'),g.horse_id.astype(str)+':'+g.date.dt.strftime('%Y-%m-%d')]:
        code=pd.factorize(ids)[0]; n=int(code.max()+1); s=np.bincount(code,weights=score)
        vs.append(float(s@s)*n/(n-1) if n>1 else float('nan'));ns.append(n)
    if min(ns[:2])<2:return dict(estimate=mean,se=None,lower=None,upper=None,p=None,df=None)
    se=math.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2])); df=min(ns[:2])-1; crit=t.ppf(.975,df)
    p=float(2*t.sf(abs(mean/se),df)) if se>0 else float(mean==0)
    return dict(estimate=mean,se=se,lower=mean-crit*se,upper=mean+crit*se,p=p,df=df)
def load():
    d=pd.read_parquet(D/'outputs/early_predictions.parquet')
    old=pd.read_parquet(P/'outputs/early_predictions.parquet')
    d=d.merge(old[['row_key']+['H_p'+str(j) for j in range(4)]],on='row_key',validate='one_to_one')
    q=pd.read_parquet(P/'outputs/feature_context.parquet')
    d=d.merge(q[['row_key','source_file','source_item_index','moisture','valid_position5']],on='row_key',validate='one_to_one')
    d=d.rename(columns={'moisture':'context_moisture'}); raw={}; files=[]
    for f,g in d.groupby('source_file'):
        path=(ROOT/f).resolve(); assert path.is_relative_to(R.resolve())
        records=json.load(gzip.open(path,'rt'))['response']['body']['items']['item']
        files.append(dict(path=f,bytes=path.stat().st_size,sha256=sha(path)))
        for row in g.itertuples():
            z=records[int(row.source_item_index)]; assert str(z['hrNo']).zfill(7)==str(row.horse_id).zfill(7)
            assert int(z['rcDate'])==int(row.date.strftime('%Y%m%d')) and int(z['rcNo'])==int(row.source_key.split(':')[2])
            assert {'서울':'서울','부산경남':'부산'}[str(z['meet'])]==row.meet and int(z['rcDist'])==row.distance_m and int(z['chulNo'])==row.gate
            track=str(z.get('track','')); m=re.search(r'(\d+(?:\.\d+)?)\s*%',track); value=float(m.group(1)) if m else np.nan
            raw[row.row_key]=(track,value)
    d['track_raw']=d.row_key.map(lambda k:raw[k][0]);d['moisture']=d.row_key.map(lambda k:raw[k][1]);d['moisture_state']=d.moisture.map(state)
    known=d.context_moisture.notna(); assert np.allclose(d.loc[known,'context_moisture'],d.loc[known,'moisture'])
    assert d.moisture.notna().all() and not d.moisture_state.eq('미관측').any()
    assert d.groupby('source_key').moisture.nunique().eq(1).all()
    d['distance_band']=np.where(d.distance_m.le(1300),'1000~1300m',np.where(d.distance_m.le(1600),'1400~1600m','1700m이상'))
    d['size_band']=np.where(d.field_size.le(9),'<=9',np.where(d.field_size.le(11),'10~11','>=12'))
    for name in ['H','N','A','B']:
        pr=d[[name+'_p'+str(j) for j in range(4)]].to_numpy(); assert np.allclose(pr.sum(1),1) and ((pr>=0)&(pr<=1)).all()
        d[name+'_pred']=pr.argmax(1);d[name+'_correct']=d[name+'_pred'].eq(d.role4).astype(int)
        d[name+'_brier']=((pr-np.eye(4)[d.role4.to_numpy()])**2).sum(1)
        d[name+'_logloss']=-np.log(pr[np.arange(len(d)),d.role4])
    d['B_back_correct']=(d.B_pred.ge(2)==d.role4.ge(2)).astype(int)
    d.to_parquet(O/'evaluation_rows.parquet',index=False)
    inputs=[D/'outputs/early_predictions.parquet',P/'outputs/early_predictions.parquet',P/'outputs/feature_context.parquet',R/'20261004_pace_finish_stack_v1/README.md',R/'20261003_pace_gate_moisture_v2/README.md']
    dump(O/'source_audit.json',dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha(p)) for p in inputs]+files,n=len(d),races=d.source_key.nunique(),horses=d.horse_id.nunique(),context_missing_recovered=int((~known).sum()),current_moisture_used_for_evaluation_only=True,models_refitted=False))
    return d
def groups(d):
    yield 'all','all',d
    for col in ['year','meet','distance_m','distance_band','moisture_state']:
        for key,g in d.groupby(col):yield col,str(key),g
    for cols in [('meet','distance_m'),('meet','moisture_state'),('year','distance_band'),('year','moisture_state'),('distance_band','moisture_state')]:
        for key,g in d.groupby(list(cols)):yield '_x_'.join(cols),'|'.join(map(str,key)),g
def metrics(d):
    rows=[];cls=[];conf=[];comp=[]
    for group,label,g in groups(d):
        meta=dict(group=group,label=label,n=len(g),races=g.source_key.nunique(),horses=g.horse_id.nunique(),dates=g.date.nunique(),small_sample=g.source_key.nunique()<30 or g.date.nunique()<10)
        for name in ['H','N','A','B']:
            ci=interval(g,g[name+'_correct']);br=interval(g,g[name+'_brier']);cm=pd.crosstab(g[name+'_pred'],g.role4).reindex(index=range(4),columns=range(4),fill_value=0).to_numpy()
            rec=np.divide(cm.diagonal(),cm.sum(0),out=np.full(4,np.nan),where=cm.sum(0)>0)
            rows.append(meta|dict(model=name,accuracy=ci['estimate'],accuracy_lower=ci['lower'],accuracy_upper=ci['upper'],brier=br['estimate'],brier_lower=br['lower'],brier_upper=br['upper'],logloss=float(g[name+'_logloss'].mean()),balanced_accuracy=float(np.nanmean(rec)),back_accuracy=float(((g[name+'_pred']>=2)==(g.role4>=2)).mean())))
            if name=='B':
                for j in range(4):
                    ng=cm[:,j].sum();pg=cm[j].sum();recall=cm[j,j]/ng if ng else np.nan;precision=cm[j,j]/pg if pg else np.nan
                    cls.append(meta|dict(class_id=j,class_name=LABELS[j],actual_n=int(ng),predicted_n=int(pg),correct_n=int(cm[j,j]),recall=recall,precision=precision,mean_probability=float(g['B_p'+str(j)].mean()),actual_share=float(g.role4.eq(j).mean())))
                    for k in range(4):conf.append(dict(group=group,label=label,predicted=j,actual=k,n=int(cm[j,k])))
        for a,b in [('N','H'),('B','H'),('B','A')]:
            for metric in ['correct','brier']:
                comp.append(meta|dict(comparison=a+'-'+b,metric=metric)|interval(g,g[a+'_'+metric]-g[b+'_'+metric]))
    c=pd.DataFrame(comp)
    for family,mask in [('overall',c.group.eq('all')),('condition_exploratory',c.group.isin(['distance_band','moisture_state']))]:
        ix=mask&c.p.notna();c.loc[ix,'bh_q']=false_discovery_control(c.loc[ix,'p']);c.loc[ix,'bh_family']=family
    pd.DataFrame(rows).to_csv(O/'condition_metrics.csv',index=False);pd.DataFrame(cls).to_csv(O/'class_metrics.csv',index=False);pd.DataFrame(conf).to_csv(O/'confusion_tables.csv',index=False);c.to_csv(O/'paired_comparisons.csv',index=False)
def standardized(d):
    rows=[];details=[]
    specs=[('moisture_state',s,'건조',['meet','distance_m','year','grade_bucket','size_band','supported5']) for s in STATES[1:]]
    specs += [('distance_band',s,'1000~1300m',['meet','year','grade_bucket','size_band','moisture_state','supported5']) for s in ['1400~1600m','1700m이상']]
    for col,a,b,cols in specs:
        g=d[d[col].isin([a,b])].copy();g['cell']=g[cols].astype(str).agg('|'.join,axis=1);valid=[]
        for cell,z in g.groupby('cell'):
            ga=z[z[col].eq(a)];gb=z[z[col].eq(b)];na=len(ga);nb=len(gb)
            if min(na,nb)<10 or min(ga.source_key.nunique(),gb.source_key.nunique())<2:continue
            w=na*nb/(na+nb);ma=ga.B_correct.mean();mb=gb.B_correct.mean();valid.append((cell,w,na,nb,ma,mb))
            details.append(dict(group=col,a=a,b=b,cell=cell,n_a=na,n_b=nb,races_a=ga.source_key.nunique(),races_b=gb.source_key.nunique(),weight=w,accuracy_a=ma,accuracy_b=mb,difference=ma-mb))
        total=sum(z[1] for z in valid);z=g[g.cell.isin([v[0] for v in valid])].copy();score=pd.Series(0.,index=z.index)
        estimate=0
        for cell,w,na,nb,ma,mb in valid:
            estimate+=w*(ma-mb)/total;mask=z.cell.eq(cell);isa=z[col].eq(a)
            score.loc[mask&isa]=w/total/na*(z.loc[mask&isa,'B_correct']-ma)
            score.loc[mask&~isa]=-w/total/nb*(z.loc[mask&~isa,'B_correct']-mb)
        ci=score_interval(z,score.to_numpy(),estimate)
        rows.append(dict(group=col,a=a,b=b,control_columns='|'.join(cols),matched_cells=len(valid),n_a=int(z[col].eq(a).sum()),n_b=int(z[col].eq(b).sum()),races=z.source_key.nunique(),coverage=float(len(z)/len(g)),raw_difference=float(g[g[col].eq(a)].B_correct.mean()-g[g[col].eq(b)].B_correct.mean()))|ci)
    out=pd.DataFrame(rows);out['bh_q']=false_discovery_control(out.p);out.to_csv(O/'standardized_contrasts.csv',index=False);pd.DataFrame(details).to_csv(O/'standardized_cells.csv',index=False)
def main():
    assert not (O/'evaluation_rows.parquet').exists(),'Preserve completed outputs'
    d=load();metrics(d);standardized(d);print('Completed fixed prediction diagnostics',len(d),flush=True)
if __name__=='__main__':main()

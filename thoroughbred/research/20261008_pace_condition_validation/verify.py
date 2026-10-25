"""Independent saved prediction SQL metrics, raw keyed join and scalar clusters."""
from pathlib import Path
import gzip,hashlib,json,math,re
import numpy as np,pandas as pd,duckdb
from scipy.stats import t
H=Path(__file__).resolve().parent;ROOT=H.parents[2];O=H/'outputs';checks=0
def check(x,name,n=1):
    global checks
    assert bool(x),name;checks+=n
def close(a,b,name):
    a=np.asarray(a,float);b=np.asarray(b,float);check(a.shape==b.shape and np.allclose(a,b,atol=1e-10,rtol=1e-9,equal_nan=True),name,a.size)
def ci(g,v):
    v=np.asarray(v,float);m=v.mean();return scored(g,(v-m)/len(v),m)
def scored(g,s,m):
    variances=[];numbers=[]
    for ids in [g.horse_id.tolist(),g.date.tolist(),list(zip(g.horse_id,g.date))]:
        sums={}
        for k,v in zip(ids,s):sums[k]=sums.get(k,0)+v
        n=len(sums);numbers.append(n);variances.append(sum(v*v for v in sums.values())*n/(n-1) if n>1 else np.nan)
    if min(numbers[:2])<2:return [m,np.nan,np.nan,np.nan,np.nan,np.nan]
    se=math.sqrt(max(0,variances[0],variances[1],variances[0]+variances[1]-variances[2]));df=min(numbers[:2])-1;c=t.ppf(.975,df);p=2*t.sf(abs(m/se),df) if se else float(m==0)
    return [m,se,m-c*se,m+c*se,p,df]
def select(d,group,label):
    if group=='all':return d
    cols=group.split('_x_');values=str(label).split('|');mask=np.ones(len(d),bool)
    for c,v in zip(cols,values):mask &= d[c].astype(str).eq(v)
    return d[mask]
def bh(p):
    p=np.asarray(p);idx=np.argsort(p);ordered=np.minimum.accumulate((p[idx]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];r=np.empty(len(p));r[idx]=np.minimum(1,ordered);return r
def main():
    d=pd.read_parquet(O/'evaluation_rows.parquet');check(len(d)==36638 and d.row_key.is_unique,'evaluation row keys');check(d.source_key.nunique()==3465,'races')
    raw_lookup={}
    audit=json.loads((O/'source_audit.json').read_text())
    for r in audit['inputs']:
        p=ROOT/r['path'];check(p.stat().st_size==r['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'],'input hash')
        if p.suffix=='.gz':
            records=json.load(gzip.open(p,'rt'))['response']['body']['items']['item']
            for z in records:
                key=(int(z['rcDate']),int(z['rcNo']),str(z['hrNo']).zfill(7));raw_lookup[(r['path'],key)]=z
    for r in d.itertuples():
        z=raw_lookup[(r.source_file,(int(r.date.strftime('%Y%m%d')),int(r.source_key.split(':')[2]),str(r.horse_id).zfill(7)))];m=float(str(z['track']).split('(')[1].split('%')[0]);close(m,r.moisture,'raw keyed moisture');check(z['track']==r.track_raw,'raw track');check(int(z['chulNo'])==r.gate and int(z['rcDist'])==r.distance_m,'raw runner')
        limits=[5,9,14,19,20];state=['건조','양호','다습','포화','불량'][next(i for i,v in enumerate(limits) if m<=v)];check(state==r.moisture_state,'moisture bin')
    known=d.context_moisture.notna();close(d.loc[known,'moisture'],d.loc[known,'context_moisture'],'preserved known');check((~known).sum()==789,'recovered missing')
    oldD=pd.read_parquet(H.parent/'20261008_bilateral_field_pace/outputs/early_predictions.parquet').set_index('row_key').loc[d.row_key];oldC=pd.read_parquet(H.parent/'20261008_field_pace_prediction/outputs/early_predictions.parquet').set_index('row_key').loc[d.row_key]
    for name in ['H','N','A','B']:
        src=oldC if name=='H' else oldD;cols=[name+'_p'+str(j) for j in range(4)];close(d[cols],src[cols],'unaltered predictions');pr=d[cols].to_numpy();close(pr.sum(1),np.ones(len(d)),'prob sums');check(((pr>=0)&(pr<=1)).all(),'prob bounds');pred=np.argmax(pr,axis=1);close(pred,d[name+'_pred'],'argmax');close(pred==d.role4,d[name+'_correct'],'correct');loss=np.sum(pr*pr,axis=1)-2*pr[np.arange(len(d)),d.role4]+1;close(loss,d[name+'_brier'],'brier scalar identity');close(-np.log(pr[np.arange(len(d)),d.role4]),d[name+'_logloss'],'logloss')
    db=duckdb.connect();ms=pd.read_csv(O/'condition_metrics.csv',dtype={'label':str})
    for row in ms.itertuples():
        g=select(d,row.group,row.label);db.register('sample',g);name=row.model
        out=db.execute(f'SELECT count(*),count(DISTINCT source_key),avg({name}_correct),avg({name}_brier),avg({name}_logloss),avg(CAST(({name}_pred>=2)=(role4>=2) AS INTEGER)) FROM sample').fetchone()
        close(out,[row.n,row.races,row.accuracy,row.brier,row.logloss,row.back_accuracy],'SQL metrics')
        cc=ci(g,g[name+'_correct']);bc=ci(g,g[name+'_brier']);close([cc[2],cc[3],bc[2],bc[3]],[row.accuracy_lower,row.accuracy_upper,row.brier_lower,row.brier_upper],'cluster bounds')
        recalls=[g[g.role4.eq(j)][name+'_correct'].mean() for j in range(4)];close(np.nanmean(recalls),row.balanced_accuracy,'balanced accuracy');check(row.small_sample==(g.source_key.nunique()<30 or g.date.nunique()<10),'small support flag')
    cm=pd.read_csv(O/'class_metrics.csv',dtype={'label':str});cf=pd.read_csv(O/'confusion_tables.csv',dtype={'label':str})
    for row in cm.itertuples():
        g=select(d,row.group,row.label);actual=g.role4.eq(row.class_id);pred=g.B_pred.eq(row.class_id);right=(actual&pred).sum();close([actual.sum(),pred.sum(),right],[row.actual_n,row.predicted_n,row.correct_n],'class support');close([right/actual.sum() if actual.sum() else np.nan,right/pred.sum() if pred.sum() else np.nan,g['B_p'+str(row.class_id)].mean(),actual.mean()],[row.recall,row.precision,row.mean_probability,row.actual_share],'class metrics')
    for row in cf.itertuples():
        g=select(d,row.group,row.label);check(((g.B_pred==row.predicted)&(g.role4==row.actual)).sum()==row.n,'confusion cell')
    co=pd.read_csv(O/'paired_comparisons.csv',dtype={'label':str})
    for row in co.itertuples():
        g=select(d,row.group,row.label);a,b=row.comparison.split('-');result=ci(g,g[a+'_'+row.metric]-g[b+'_'+row.metric]);close(result,[row.estimate,row.se,row.lower,row.upper,row.p,row.df],'paired difference clusters')
    for family,g in co.dropna(subset=['bh_family']).groupby('bh_family'):close(bh(g.p),g.bh_q,'paired BH')
    contrasts=pd.read_csv(O/'standardized_contrasts.csv');details=pd.read_csv(O/'standardized_cells.csv');cell_checks=0
    for row in contrasts.itertuples():
        g=d[d[row.group].isin([row.a,row.b])].copy();cols=row.control_columns.split('|');g['cell']=g[cols].astype(str).agg('|'.join,axis=1);db.register('matched',g)
        stats=db.execute(f'SELECT cell, "{row.group}" side,count(*) n,count(DISTINCT source_key) races,avg(B_correct) m FROM matched GROUP BY cell,side').df();pivot=stats.pivot(index='cell',columns='side',values=['n','races','m']);ok=(pivot['n'].min(axis=1)>=10)&(pivot['races'].min(axis=1)>=2)&pivot['n'].notna().all(axis=1);pivot=pivot[ok];check(len(pivot)==row.matched_cells,'matched cell number');valid=g[g.cell.isin(pivot.index)].copy();weights=(pivot['n'][row.a]*pivot['n'][row.b]/(pivot['n'][row.a]+pivot['n'][row.b]));weights/=weights.sum();m=float((weights*(pivot['m'][row.a]-pivot['m'][row.b])).sum());scores=[]
        for z in valid.itertuples():
            side=getattr(z,row.group);sgn=1 if side==row.a else -1;scores.append(sgn*weights[z.cell]/pivot['n'][side][z.cell]*(z.B_correct-pivot['m'][side][z.cell]))
        close(scored(valid,np.array(scores),m),[row.estimate,row.se,row.lower,row.upper,row.p,row.df],'standardized contrast clusters');close([valid[row.group].eq(row.a).sum(),valid[row.group].eq(row.b).sum(),len(valid)/len(g)],[row.n_a,row.n_b,row.coverage],'matched counts');close(g[g[row.group].eq(row.a)].B_correct.mean()-g[g[row.group].eq(row.b)].B_correct.mean(),row.raw_difference,'raw contrast')
        sub=details[(details.group==row.group)&(details.a==row.a)&(details.b==row.b)].set_index('cell');check(set(sub.index)==set(pivot.index),'all matched details')
        for side,suffix in [(row.a,'a'),(row.b,'b')]:
            for col,target in [('n','n_'+suffix),('races','races_'+suffix),('m','accuracy_'+suffix)]:close(pivot[col][side].loc[sub.index],sub[target],'matched detail values');cell_checks+=len(sub)
    close(bh(contrasts.p),contrasts.bh_q,'standardized BH')
    shared={'thoroughbred/research/'+s for s in ['README.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json','ARTIFACT_SIZE_LOG.md']};preserved=0
    for row in json.loads((O/'baseline_inventory.json').read_text())['related_existing_files']:
        if row['path'] in shared:continue
        p=ROOT/row['path'];check(p.stat().st_size==row['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],'preserved prior work');preserved+=1
    out=dict(passed=True,checks=checks,metrics_rows=len(ms),class_rows=len(cm),confusion_rows=len(cf),paired_rows=len(co),matched_detail_values=cell_checks,prior_files_preserved=preserved,raw_keyed_moisture_rows=len(d),new_models_trained=0,operating_model_changed=False)
    (O/'verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':main()

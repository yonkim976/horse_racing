"""Historical identity based rider switch study; no database or production writes."""
from pathlib import Path
import gzip,hashlib,json,math,re
import numpy as np
import pandas as pd
from scipy import stats,linalg,sparse
from scipy.sparse import csgraph
from scipy.sparse.linalg import splu

H=Path(__file__).resolve().parent; R=H.parent; ROOT=H.parents[2]; O=H/'outputs'
BASE=R/'20261008_field_pace_prediction/outputs/feature_context.parquet'
POP=R/'20261007_sex_ability_gap/outputs/population.parquet'
CATS=['retained_ordinary','retained_top','ordinary_to_top','top_to_top','top_to_ordinary','ordinary_to_ordinary']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def ident(v):
    s=str(v).strip();return s if re.fullmatch('[0-9A-Z]+',s) and any(c.isdigit() for c in s) and s.strip('0') else ''
def number(v):
    try:return float(v)
    except (ValueError,TypeError):return np.nan

def rankings(d,min_n=100,top_fraction=.2):
    good=d[d.normal_outcome&d.jockey_id.ne('')]
    a=good.groupby(['year','meet','jockey_id']).agg(n=('top3','size'),events=('top3','sum'),wins=('win','sum'),name=('jockey_name','last')).reset_index()
    avg=good.groupby(['year','meet']).top3.mean().rename('venue_rate').reset_index();a=a.merge(avg,on=['year','meet'])
    a['score']=(a.events+50*a.venue_rate)/(a.n+50);a['eligible']=a.n.ge(min_n);a['top']=False;a['order']=np.nan;a['eligible_count']=0
    for _,g in a[a.eligible].groupby(['year','meet']):
        ix=g.sort_values(['score','jockey_id'],ascending=[False,True]).index;k=math.ceil(len(ix)*top_fraction)
        a.loc[ix,'order']=np.arange(1,len(ix)+1);a.loc[ix,'eligible_count']=len(ix);a.loc[ix[:k],'top']=True
    a['reference_year']=a.year;a['evaluation_year']=a.year+1
    return a.drop(columns='year')

def attach_ranks(d,a):
    z=d.copy()
    for col,label in [('jockey_id','current'),('previous_jockey_id','previous')]:
        lookup=a[['evaluation_year','meet','jockey_id','n','score','eligible','top','order']].rename(columns={'evaluation_year':'year','jockey_id':col,**{c:label+'_'+c for c in ['n','score','eligible','top','order']}})
        z=z.drop(columns=[label+'_'+c for c in ['n','score','eligible','top','order'] if label+'_'+c in z],errors='ignore').merge(lookup,on=['year','meet',col],how='left',validate='many_to_one')
    z['rank_supported']=z.current_eligible.eq(True)&z.previous_eligible.eq(True)
    same=z.jockey_id.eq(z.previous_jockey_id);ct=z.current_top.eq(True);pt=z.previous_top.eq(True)
    z['category']=np.select([same&~ct,same&ct,~same&~pt&ct,~same&pt&ct,~same&pt&~ct,~same&~pt&~ct],CATS,default='unclassified')
    z.loc[~z.rank_supported|~z.identity_supported,'category']='unclassified'
    return z

def prepare():
    cols=['row_key','source_key','horse_id','horse_name','meet','date','year','distance_m','field_size','gate','source_file','source_item_index','raw_finish_rank','finish_p','normal_outcome','jockey_id','trainer_id','jockey_name','trainer_name','age_current','grade_num','grade_bucket','moisture','rating','finish_p_mean5','finish_p_n5','gate_relative']
    d=pd.read_parquet(BASE,columns=cols);d['date']=pd.to_datetime(d.date)
    rec=[];inputs=[]
    for file,g in d.groupby('source_file'):
        p=(ROOT/file).resolve();assert p.is_relative_to(R.resolve());inputs.append(dict(path=file,bytes=p.stat().st_size,sha256=sha(p)))
        with gzip.open(p,'rt') as f:items=json.load(f)['response']['body']['items']['item']
        for row in g.itertuples():
            a=items[int(row.source_item_index)]
            assert ident(a['hrNo']).zfill(7)==row.horse_id
            assert ident(a['jkNo'])==row.jockey_id or row.jockey_id==''
            assert ident(a['trNo'])==row.trainer_id or row.trainer_id==''
            rec.append(dict(row_key=row.row_key,raw_jockey_id=ident(a.get('jkNo')),raw_trainer_id=ident(a.get('trNo')),owner_id=ident(a.get('owNo')),owner_name=str(a.get('owName','')),weight=number(a.get('wgBudam')),body_weight=number(str(a.get('wgHr','')).split('(')[0]),raw_time=number(a.get('rcTime'))))
    d=d.merge(pd.DataFrame(rec),on='row_key',validate='one_to_one')
    repaired=int(d.jockey_id.ne(d.raw_jockey_id).sum());d['jockey_id']=d.pop('raw_jockey_id');d['trainer_id']=d.pop('raw_trainer_id')
    d['top3']=np.where(d.normal_outcome,d.raw_finish_rank.le(3),np.nan);d['win']=np.where(d.normal_outcome,d.raw_finish_rank.eq(1),np.nan)
    good=pd.read_parquet(POP,columns=['row_key','finish']);d=d.merge(good.rename(columns={'finish':'quality_time'}),on='row_key',how='left',validate='one_to_one')
    winner=d[d.raw_finish_rank.eq(1)&d.raw_time.gt(0)].groupby('source_key').raw_time.min()
    d['time_gap']=d.quality_time-d.source_key.map(winner)
    assert np.allclose(d.loc[d.quality_time.notna(),'quality_time'],d.loc[d.quality_time.notna(),'raw_time'])
    d=d.sort_values(['horse_id','date']).reset_index(drop=True);g=d.groupby('horse_id',sort=False)
    for c in ['row_key','date','meet','jockey_id','trainer_id','owner_id','top3','finish_p','raw_finish_rank','raw_time','quality_time','distance_m','grade_bucket','grade_num','weight','body_weight']:
        d['previous_'+c]=g[c].shift()
    d['gap_days']=(d.date-d.previous_date).dt.days
    assert d.gap_days.dropna().ge(2).all()
    d['identity_supported']=d.jockey_id.ne('')&d.previous_jockey_id.notna()&d.previous_jockey_id.ne('')
    d['changed']=d.identity_supported&d.jockey_id.ne(d.previous_jockey_id)
    d['stable_trainer']=d.trainer_id.ne('')&d.trainer_id.eq(d.previous_trainer_id)
    d['stable_owner']=d.owner_id.ne('')&d.owner_id.eq(d.previous_owner_id)
    d['same_venue']=d.meet.eq(d.previous_meet)
    d['distance_change']=d.distance_m-d.previous_distance_m;d['grade_change']=d.grade_num-d.previous_grade_num
    d['rank_improvement']=d.previous_finish_p-d.finish_p
    d['same_conditions']=d.same_venue&d.distance_m.eq(d.previous_distance_m)&d.grade_bucket.eq(d.previous_grade_bucket)
    d['raw_time_change_same']=np.where(d.same_conditions&d.quality_time.notna()&d.previous_quality_time.notna(),d.quality_time-d.previous_quality_time,np.nan)
    a=rankings(d);a.to_csv(O/'annual_jockey_rankings.csv',index=False);d=attach_ranks(d,a)
    pref=d[d.trainer_id.ne('')&d.jockey_id.ne('')].groupby(['year','meet','trainer_id','jockey_id']).size().rename('pair_n').reset_index()
    pref['trainer_n']=pref.groupby(['year','meet','trainer_id']).pair_n.transform('sum');pref['share']=pref.pair_n/pref.trainer_n
    pref=pref.sort_values(['year','meet','trainer_id','pair_n','jockey_id'],ascending=[True,True,True,False,True]).drop_duplicates(['year','meet','trainer_id'])
    pref['supported']=pref.trainer_n.ge(50)&pref.pair_n.ge(20)&pref.share.ge(.15);pref['reference_year']=pref.year;pref['year']+=1
    pref.to_csv(O/'annual_trainer_preference.csv',index=False)
    d=d.merge(pref.rename(columns={'jockey_id':'preferred_jockey_id','supported':'preference_supported','pair_n':'preference_pair_n','share':'preference_share','trainer_n':'preference_trainer_n'}).drop(columns='reference_year'),on=['year','meet','trainer_id'],how='left',validate='many_to_one')
    d['to_preferred']=d.preference_supported.eq(True)&d.jockey_id.eq(d.preferred_jockey_id)
    d['main_eligible']=d.normal_outcome&d.identity_supported&d.rank_supported&d.stable_trainer&d.same_venue&d.gap_days.between(2,180)
    d.to_parquet(O/'analysis_rows.parquet',index=False)
    dump(O/'source_audit.json',dict(inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha(p)) for p in [BASE,POP]]+inputs,rows=len(d),races=d.source_key.nunique(),horses=d.horse_id.nunique(),alphanumeric_jockey_rows_restored_from_raw=repaired,data_end_by_meet={k:str(v.date()) for k,v in d.groupby('meet').date.max().items()},primary='2024~2025',confirmation='2026 through source end; incomplete year',current_outcome_used_in_prior_rank=False,uses_track_speed=False,predictive_models_trained=0))
    return d

def period(d):
    for name,mask in [('2024_2025',d.year.between(2024,2025)),('2026_partial',d.year.eq(2026))]:yield name,d[mask]
def metrics(g):
    paired=g[g.previous_top3.notna()&g.top3.notna()]
    out=dict(n=len(g),horses=g.horse_id.nunique(),races=g.source_key.nunique(),dates=g.date.nunique(),top3_events=int(g.top3.sum()),top3_rate=g.top3.mean(),win_rate=g.win.mean(),previous_top3_n=len(paired),previous_top3_rate=paired.previous_top3.mean(),paired_current_top3_rate=paired.top3.mean(),paired_top3_change=(paired.top3-paired.previous_top3).mean(),rank_mean=g.raw_finish_rank.mean(),rank_relative_mean=g.finish_p.mean(),previous_rank_relative_mean=g.previous_finish_p.mean(),rank_improvement_n=int(g.rank_improvement.notna().sum()),rank_improvement_mean=g.rank_improvement.mean(),past5_rank=g.finish_p_mean5.mean(),time_n=int(g.time_gap.notna().sum()),time_gap_mean=g.time_gap.mean(),same_condition_time_n=int(g.raw_time_change_same.notna().sum()),same_condition_time_change=g.raw_time_change_same.mean())
    for label,sub,values in [('paired_top3',paired,paired.top3-paired.previous_top3),('rank_improvement',g[g.rank_improvement.notna()],g.loc[g.rank_improvement.notna(),'rank_improvement'])]:
        if len(sub)>1:
            m=values.mean();ci=cluster_ci(sub,(values-m).to_numpy()/len(sub),m)
            out.update({label+'_'+k:ci[k] for k in ['ci_low','ci_high','p']})
    return out

def demean(a,codes,tol=1e-10):
    # Exact sparse projection avoids very slow alternating convergence in thin horse/race chains.
    first=codes[0];n1=int(first.max()+1)
    if len(codes)==1:
        sums=np.zeros((n1,a.shape[1]));np.add.at(sums,first,a)
        return a-(sums/np.bincount(first)[:,None])[first],n1
    second=codes[1];n2=int(second.max()+1);rows=np.arange(len(a))
    graph=sparse.coo_matrix((np.ones(2*len(a)),(np.r_[first,second+n1],np.r_[second+n1,first])),shape=(n1+n2,n1+n2)).tocsr()
    ncomp,labels=csgraph.connected_components(graph,directed=False)
    drops=[np.flatnonzero(labels[n1:]==k)[0]+n1 for k in range(ncomp)]
    matrix=sparse.coo_matrix((np.ones(2*len(a)),(np.r_[rows,rows],np.r_[first,second+n1])),shape=(len(a),n1+n2)).tocsr()
    keep=np.ones(n1+n2,bool);keep[drops]=False;matrix=matrix[:,keep]
    normal=(matrix.T@matrix).tocsc();factor=splu(normal)
    out=a-matrix@factor.solve(np.asarray(matrix.T@a))
    assert np.max(np.abs(matrix.T@out))<1e-7
    return out,n1+n2-ncomp

def controls(g):
    z={}
    fields=['finish_p_mean5','finish_p_n5','previous_finish_p','previous_top3','gap_days','distance_change','grade_change','rating','age_current','weight','body_weight','gate_relative','previous_score']
    for c in fields:
        v=g[c].to_numpy(float);missing=~np.isfinite(v);v=np.where(missing,0,v);z[c+'_missing']=missing.astype(float)
        if c=='gap_days':v=np.log1p(v)
        z[c]=v
        if c in ['rating','age_current','weight','body_weight','finish_p_mean5','previous_finish_p','gap_days','gate_relative']:z[c+'_sq']=v*v
    return pd.DataFrame(z,index=g.index)

def cluster_ci(g,influence,estimate):
    vals=[];counts=[]
    for keys in [['horse_id'],['date'],['horse_id','date']]:
        code=pd.factorize(pd.MultiIndex.from_frame(g[keys]))[0];n=code.max()+1;s=np.bincount(code,weights=influence)
        vals.append(float(s@s)*n/max(n-1,1));counts.append(n)
    var=max(0,vals[0],vals[1],vals[0]+vals[1]-vals[2]);se=math.sqrt(var);df=max(1,min(counts[:2])-1);crit=stats.t.ppf(.975,df)
    return dict(estimate=float(estimate),se=se,ci_low=float(estimate-crit*se),ci_high=float(estimate+crit*se),p=float(2*stats.t.sf(abs(estimate/se),df)) if se else 1.,horse_clusters=counts[0],date_clusters=counts[1])

def fit(g,design,targets=('top3','finish_p','time_gap'),horse=False):
    results=[];diagnostics=[]
    for target in targets:
        z=g[g[target].notna()].copy();idx=g.index.get_indexer(z.index);x=design.iloc[idx].to_numpy(float);names=list(design.columns)
        c=controls(z).to_numpy(float);scale=np.std(c,axis=0);c=c[:,scale>1e-12]/scale[scale>1e-12]
        a=np.column_stack([x,c,z[target].to_numpy(float)]);codes=[pd.factorize(z.source_key)[0]]
        if horse:codes.append(pd.factorize(z.horse_id)[0])
        a,fe_rank=demean(a,codes);xall=a[:,:-1];y=a[:,-1];keep=np.std(xall,axis=0)>1e-10;retained=np.flatnonzero(keep);xx=xall[:,keep]
        beta,res,rank,s=linalg.lstsq(xx,y,cond=1e-10);inverse=linalg.pinv(xx,rtol=1e-10);residual=y-xx@beta
        # scale controls before demeaning avoids numerical disparity; dummy columns remain unscaled.
        unidentified=[];projector=inverse@xx
        for j,name in enumerate(names):
            if j not in retained:continue
            k=int(np.flatnonzero(retained==j)[0]);residual_df=len(z)-fe_rank-rank;assert residual_df>0
            influence=inverse[k]*residual*math.sqrt(len(z)/residual_df)
            if np.max(np.abs(projector[k]-np.eye(xx.shape[1])[k]))>=1e-6:
                unidentified.append(name);continue
            results.append(dict(target=target,term=name,n=len(z),horses=z.horse_id.nunique(),races=z.source_key.nunique(),**cluster_ci(z,influence,beta[k])))
        if all(c in names for c in ['ordinary_to_top','retained_top','ordinary_to_ordinary']):
            for term,reference in [('upgrade_vs_retained_top','retained_top'),('upgrade_vs_ordinary_switch','ordinary_to_ordinary')]:
                weight=np.zeros(len(beta))
                for name,value in [('ordinary_to_top',1),(reference,-1)]:
                    j=names.index(name);k=int(np.flatnonzero(retained==j)[0]);weight[k]=value
                influence=(weight@inverse)*residual*math.sqrt(len(z)/residual_df)
                results.append(dict(target=target,term=term,n=len(z),horses=z.horse_id.nunique(),races=z.source_key.nunique(),**cluster_ci(z,influence,weight@beta)))
        diagnostics.append(dict(target=target,n=len(z),p=xx.shape[1],rank=int(rank),fe_rank=int(fe_rank),residual_df=int(residual_df),projection='sparse_exact',unidentified_terms=';'.join(unidentified),normal_equation_max=float(np.max(np.abs(xx.T@residual))),max_fe_mean=max(float(np.max(np.abs(pd.DataFrame(a).groupby(code).mean().to_numpy()))) for code in codes)))
    return results,diagnostics

def category_design(g):return pd.DataFrame({cat:g.category.eq(cat).astype(float) for cat in CATS[1:]},index=g.index)
def bh(frame,groups):
    frame=frame.copy();frame['q']=np.nan
    for _,g in frame.groupby(groups,dropna=False):
        ix=g.p.sort_values().index;m=len(ix);q=np.minimum.accumulate((frame.loc[ix,'p'].to_numpy()*m/np.arange(1,m+1))[::-1])[::-1];frame.loc[ix,'q']=np.minimum(1,q)
    return frame

def run(d):
    summaries=[];coverage=[];effects=[];diagnostics=[];riders=[];pairs=[];preferences=[]
    for window,allg in period(d):
        for meet,g in [('전체',allg)]+list(allg.groupby('meet')):
            conditions=[('all_starts',np.ones(len(g),bool)),('normal_current',g.normal_outcome),('known_actual_previous_rider',g.identity_supported),('previous_2_180_days',g.gap_days.between(2,180)),('same_trainer',g.stable_trainer),('same_venue',g.same_venue),('both_prior_ranks_supported',g.rank_supported),('main',g.main_eligible)]
            mask=np.ones(len(g),bool)
            for name,test in conditions:mask&=np.asarray(test);coverage.append(dict(window=window,meet=meet,stage=name,n=int(mask.sum())))
            valid=g[g.main_eligible]
            for cat,s in valid.groupby('category'):summaries.append(dict(window=window,meet=meet,category=cat,**metrics(s)))
            raw=g[g.normal_outcome&g.identity_supported&g.gap_days.between(2,180)&g.stable_trainer&g.same_venue]
            for changed,s in raw.groupby('changed'):summaries.append(dict(window=window,meet=meet,category='all_changed' if changed else 'all_retained',**metrics(s)))
            for horse in [False,True]:
                rr,dd=fit(valid,category_design(valid),horse=horse)
                effects += [dict(window=window,meet=meet,model='race_horse_controls' if horse else 'race_controls',**x) for x in rr]
                diagnostics += [dict(window=window,meet=meet,model='race_horse_controls' if horse else 'race_controls',**x) for x in dd]
        valid=allg[allg.main_eligible]
        for (meet,jid),s in valid[valid.changed].groupby(['meet','jockey_id']):
            if len(s)<100 or s.horse_id.nunique()<30 or s.source_key.nunique()<30:continue
            riders.append(dict(window=window,meet=meet,jockey_id=jid,jockey_name=s.jockey_name.iloc[-1],**metrics(s)))
        for (meet,tid,jid),s in valid[valid.changed].groupby(['meet','trainer_id','jockey_id']):
            if len(s)<50 or s.horse_id.nunique()<20 or s.source_key.nunique()<20:continue
            pairs.append(dict(window=window,meet=meet,trainer_id=tid,trainer_name=s.trainer_name.iloc[-1],jockey_id=jid,jockey_name=s.jockey_name.iloc[-1],**metrics(s)))
        # Preferred booking comparison conditional on already switching; pair history is prior year only.
        z=valid[valid.changed&valid.preference_supported.eq(True)]
        for pref,s in z.groupby('to_preferred'):preferences.append(dict(window=window,preferred=bool(pref),**metrics(s)))
        design=pd.DataFrame({'to_preferred':z.to_preferred.astype(float),'destination_top':z.current_top.astype(float),'previous_top':z.previous_top.astype(float)},index=z.index)
        rr,dd=fit(z,design,horse=True)
        effects += [dict(window=window,meet='전체',model='preferred_among_switches',**x) for x in rr]
        diagnostics += [dict(window=window,meet='전체',model='preferred_among_switches',**x) for x in dd]
    pd.DataFrame(summaries).to_csv(O/'category_metrics.csv',index=False);pd.DataFrame(coverage).to_csv(O/'coverage.csv',index=False)
    pd.DataFrame(riders).to_csv(O/'destination_jockey_metrics.csv',index=False);pd.DataFrame(pairs).to_csv(O/'trainer_jockey_pair_metrics.csv',index=False);pd.DataFrame(preferences).to_csv(O/'preferred_booking_metrics.csv',index=False)
    effect=bh(pd.DataFrame(effects),['window','meet','model','target']);effect.to_csv(O/'adjusted_associations.csv',index=False)
    pd.DataFrame(diagnostics).to_csv(O/'model_diagnostics.csv',index=False)
    # Joint per-destination switch versus same-destination retained model; all eligible background riders retained.
    out=[]
    for window,g in period(d):
        g=g[g.main_eligible];supported=[(r['meet'],r['jockey_id']) for r in riders if r['window']==window]
        keys=g.meet+':'+g.jockey_id;allkeys=sorted(keys.unique());design={}
        baselines={sorted(keys[g.meet.eq(meet)].unique())[0] for meet in g.meet.unique()}
        for k in allkeys:
            if k not in baselines:design['jockey_'+k]=keys.eq(k).astype(float)
        covered=np.zeros(len(g),bool)
        for meet,jid in supported:
            k=meet+':'+jid;mask=keys.eq(k)&g.changed;covered|=mask;design['switch_'+k]=mask.astype(float)
        design['switch_other']=(g.changed&~covered).astype(float)
        rr,dd=fit(g,pd.DataFrame(design,index=g.index),targets=('top3','finish_p'),horse=True)
        out += [dict(window=window,**r) for r in rr if r['term'].startswith('switch_')]
        diagnostics += [dict(window=window,model='destination_joint',**r) for r in dd]
    bh(pd.DataFrame(out),['window','target']).to_csv(O/'destination_switch_associations.csv',index=False)
    pd.DataFrame(diagnostics).to_csv(O/'model_diagnostics.csv',index=False)
    # Distance-specific timing associations, with no extrapolation to unobserved distances.
    distance=[]
    g=d[d.main_eligible&d.year.between(2024,2025)]
    for (meet,dist),z in g.groupby(['meet','distance_m']):
        n=int(z.category.eq('ordinary_to_top').sum())
        if n<100 or z.source_key.nunique()<50:continue
        rr,dd=fit(z,category_design(z),targets=('time_gap',),horse=True)
        distance += [dict(meet=meet,distance_m=int(dist),upgrade_n=n,**r) for r in rr]
    bh(pd.DataFrame(distance),['target']).to_csv(O/'distance_time_associations.csv',index=False)
    sensitivity=[]
    base=d[d.year.between(2024,2025)]
    for name,g in [('stable_owner',base[base.main_eligible&base.stable_owner]),('previous_normal',base[base.main_eligible&base.previous_finish_p.notna()]),('gap730',base[base.normal_outcome&base.identity_supported&base.rank_supported&base.stable_trainer&base.same_venue&base.gap_days.between(2,730)]),('min50',attach_ranks(base,rankings(d,50,.2))),('top30',attach_ranks(base,rankings(d,100,.3)))]:
        if name in ['min50','top30']:g=g[g.normal_outcome&g.identity_supported&g.rank_supported&g.stable_trainer&g.same_venue&g.gap_days.between(2,180)]
        rr,dd=fit(g,category_design(g),targets=('top3','finish_p'),horse=True);sensitivity += [dict(sensitivity=name,**r) for r in rr]
    bh(pd.DataFrame(sensitivity),['sensitivity','target']).to_csv(O/'sensitivity.csv',index=False)
    calendar=[]
    for year in [2024,2025,2026]:
        z=d[d.main_eligible&d.year.eq(year)&d.date.dt.strftime('%m%d').le('0918')]
        rr,dd=fit(z,category_design(z),targets=('top3','finish_p'),horse=True)
        calendar += [dict(year=year,calendar_end='09-18',**r) for r in rr]
    bh(pd.DataFrame(calendar),['year','target']).to_csv(O/'same_calendar_year_associations.csv',index=False)
    # Illustrative paired observed changes, deterministic largest supported pair (not highest success).
    pairdf=pd.DataFrame(pairs);chosen=pairdf[pairdf.window.eq('2024_2025')].sort_values('n',ascending=False).head(4)
    examples=[]
    for p in chosen.itertuples():
        z=d[d.main_eligible&d.year.between(2024,2025)&d.changed&d.trainer_id.eq(p.trainer_id)&d.jockey_id.eq(p.jockey_id)&d.meet.eq(p.meet)]
        for _,s in z.groupby('top3'):
            r=s.sort_values(['date','row_key']).iloc[0];examples.append(r[['row_key','horse_name','date','meet','distance_m','jockey_name','trainer_name','previous_jockey_id','previous_raw_finish_rank','raw_finish_rank','category']].to_dict())
    pd.DataFrame(examples).to_csv(O/'illustrative_cases.csv',index=False)
    print(effect[(effect.window=='2024_2025')&(effect.term=='ordinary_to_top')].to_string(index=False))
    print(pd.DataFrame(summaries).query("window=='2024_2025' and meet=='전체'").to_string(index=False))

if __name__=='__main__':run(prepare())

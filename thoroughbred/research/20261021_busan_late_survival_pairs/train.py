"""Chronological late trajectory integration and symmetric pair classifiers."""
import itertools
import json
import warnings
import lightgbm as lgb
import numpy as np
import pandas as pd
import data as d

warnings.filterwarnings('ignore',category=pd.errors.PerformanceWarning)
PARAMS=dict(learning_rate=.04,num_leaves=15,min_data_in_leaf=100,lambda_l2=10.,
            verbosity=-1,num_threads=4,seed=d.SEED,deterministic=True,force_col_wise=True)
LATE=['g3_front','g1_front','top3','strict_survive','lead_top3','nonlead_top3','late_fade','late_restore']
HIST=['last600_peer_adv_mean5','late_peer_adv_mean5','last600_peer_adv_n5','late_peer_adv_n5',
      'early_adv_mean5','early_n5','lead_prior5','recovery_mean5','fade_mean5','past_total','gate_relative']


def fit(name,x,y,weights,params,rounds,dates):
    path=d.M/(name+'.txt')
    if path.exists():
        model=lgb.Booster(model_file=str(path));assert model.feature_name()==list(x.columns)
        return model
    model=lgb.train(params,lgb.Dataset(x,label=y,weight=weights),num_boost_round=rounds)
    model.save_model(str(path))
    d.save('models/'+name+'.json',dict(features=list(x.columns),n=len(x),
        train_start=str(pd.Series(dates).min().date()),train_end=str(pd.Series(dates).max().date()),
        index_sha256=__import__('hashlib').sha256('\n'.join(map(str,x.index)).encode()).hexdigest(),
        params=params,rounds=rounds,model_sha256=d.sha(path)))
    print('fit',name,len(x),x.shape[1],flush=True)
    return model


def scenario_predictions(models,x):
    n=len(x);g3=np.empty((n,2,3));g1=np.empty((n,2,3,2));end=np.empty((n,2,3,2,2))
    for early in range(2):
        for count in range(3):
            base=x.copy();base['scenario_early']=early;base['scenario_count']=count
            g3[:,early,count]=models['g3'].predict(base,num_threads=4)
            for mid in range(2):
                second=base.copy();second['scenario_g3']=mid
                g1[:,early,count,mid]=models['g1'].predict(second,num_threads=4)
                for late in range(2):
                    final=second.copy();final['scenario_g1']=late
                    end[:,early,count,mid,late]=models['end'].predict(final,num_threads=4)
    return g3,g1,end


def integrate(mass,g3,g1,end):
    n=len(mass);result=np.zeros((n,len(LATE)));conditional=np.zeros((n,2,3))
    for early in range(2):
        for count in range(3):
            w=mass[:,early,count]
            for mid in range(2):
                pm=g3[:,early,count] if mid else 1-g3[:,early,count]
                for late in range(2):
                    pl=g1[:,early,count,mid] if late else 1-g1[:,early,count,mid]
                    path=pm*pl;finish=path*end[:,early,count,mid,late]
                    conditional[:,early,count]+=finish
                    result[:,0]+=w*path*mid;result[:,1]+=w*path*late;result[:,2]+=w*finish
                    if early:
                        result[:,4]+=w*finish
                        if mid and late:result[:,3]+=w*finish
                        if mid and not late:result[:,6]+=w*path
                        if not mid and late:result[:,7]+=w*path
                    else:result[:,5]+=w*finish
    np.testing.assert_allclose(result[:,4]+result[:,5],result[:,2],atol=1e-12)
    return result,conditional


def train_chain(q,h,x,aux):
    path=d.O/'late_predictions.parquet'
    if path.exists():return pd.read_parquet(path)
    xx=pd.concat([x,h],axis=1)
    target_count=aux.set_index('row_key').actual_count
    # Training labels include 2018/19 before OOF forecasts start.
    allcount=pd.read_csv(d.R/'20261021_busan_leader_pack_outcomes/outputs/race_outcomes.csv').set_index('source_key').leader_count
    count=q.source_key.map(allcount)
    cc=np.minimum(count.fillna(1).to_numpy(int)-1,2)
    lead=q.role4.eq(0).astype(int)
    parts=[]
    for year in range(2020,2027):
        te=q.year.eq(year);models={}
        for stage,target in [('g3','g3front'),('g1','g1front'),('end','top3')]:
            tr=q.year.lt(year)&q.group_observed&q[target].notna()
            if stage in ['g1','end']:tr &= q.g3front.notna()
            if stage=='end':tr &= q.g1front.notna()
            matrix=xx.loc[tr].copy()
            matrix['scenario_early']=lead.loc[tr].to_numpy();matrix['scenario_count']=cc[tr]
            if stage in ['g1','end']:matrix['scenario_g3']=q.loc[tr,'g3front'].to_numpy()
            if stage=='end':matrix['scenario_g1']=q.loc[tr,'g1front'].to_numpy()
            models[stage]=fit(f'{year}_chain_{stage}',matrix,q.loc[tr,target],1/q.loc[tr,'field_size'],
                   PARAMS|dict(objective='binary'),180,q.loc[tr,'date'])
        current=q.loc[te].copy().reset_index(drop=True)
        a=aux.set_index('row_key').loc[current.row_key]
        mass=np.empty((len(a),2,3))
        for c,name in enumerate(['1','2','3p']):
            mass[:,1,c]=a['J_member'+name].to_numpy()
            mass[:,0,c]=a['J_count'+name].to_numpy()-mass[:,1,c]
        g3,g1,end=scenario_predictions(models,xx.loc[te].reset_index(drop=True))
        result,conditional=integrate(mass,g3,g1,end)
        out=current[['row_key','source_key','horse_id','date','year','gate','field_size',
                     'g3front','g1front','top3','group_observed','normal_outcome']].copy()
        for j,name in enumerate(LATE):out['chain_'+name]=result[:,j]
        for e in range(2):
            for c in range(3):out[f'chain_cond_e{e}_n{c}']=conditional[:,e,c]
        parts.append(out)
    result=pd.concat(parts,ignore_index=True)
    result.to_parquet(path,index=False)
    return result


def main_matrices(q,h,p,j,late):
    key='부산:'+p.date+':'+p.race_no.astype(str)+':'+p.horse_id
    hh=h.copy();hh.index=q.row_key
    history=hh.reindex(key).reset_index(drop=True).add_prefix('latehist_')
    H=pd.concat([j,history],axis=1)
    forecast=late.set_index('row_key')[['chain_'+c for c in LATE]].reindex(key).reset_index(drop=True)
    S=pd.concat([H,forecast],axis=1)
    assert H.columns.is_unique and S.columns.is_unique
    return H,S


def train_scores(q,h,p,j,late):
    path=d.O/'external_scores.parquet'
    H,S=main_matrices(q,h,p,j,late)
    d.save('feature_contract.json',dict(late_history=list(h.columns),
        chain_inputs=json.loads((d.PREV/'outputs/feature_contract.json').read_text())['auxiliary_horse']+list(h.columns),
        H=list(H.columns),S=list(S.columns),chain_outputs=LATE,score_model_training_start=2017,
        chain_training_start=2018,external_years=list(range(2020,2027)),jockey_trainer=False))
    if path.exists():return pd.read_parquet(path)
    parts=[]
    for year in range(2020,2027):
        tr=p.year.between(2017,year-1)&p.normal_n.ge(6);te=p.year.eq(year)&p.normal_n.ge(6)
        out=p.loc[te,['row_id','date','race_no','horse_id','horse_name','program_no','year','distance',
                     'grade','finish_rank','performance','normal_n']].copy()
        out['row_key']='부산:'+out.date+':'+out.race_no.astype(str)+':'+out.horse_id
        out['source_key']='부산:'+out.date+':'+out.race_no.astype(str)
        for name,matrix in [('H',H),('S',S)]:
            model=fit(f'{year}_finish_{name}',matrix.loc[tr],p.loc[tr,'performance'],1/p.loc[tr,'normal_n'],
                    PARAMS|dict(objective='regression',min_data_in_leaf=80,lambda_l2=2.,max_bin=63),
                    120,pd.to_datetime(p.loc[tr,'date']))
            out['score_'+name]=model.predict(matrix.loc[te],num_threads=4)
        parts.append(out)
    result=pd.concat(parts,ignore_index=True)
    frozen=pd.read_parquet(d.PREV/'outputs/finish_predictions.parquet').set_index('row_id')
    result['score_J']=result.row_id.map(frozen.score_J)
    result['score_B']=result.row_id.map(frozen.score_B)
    for year in [2024,2025,2026]:
        take=p.year.eq(year)&p.normal_n.ge(6)
        model=lgb.Booster(model_file=str(d.PREV/'outputs/models'/f'{year}_finish_J.txt'))
        predicted=model.predict(j.loc[take],num_threads=4)
        np.testing.assert_allclose(predicted,frozen.loc[p.loc[take,'row_id'],'score_J'],atol=1e-12,rtol=0)
    result.to_parquet(path,index=False)
    return result


def pair_joint(p,pi):
    p=np.clip(np.asarray(p,float),1e-6,1-1e-6);pmf=d.prior.polynomial(p)
    group=np.array([pmf[1],pmf[2],pmf[3:].sum()]);scale=pi/group
    ii,kk=np.triu_indices(len(p),1);zero=np.ones(len(ii));one=np.zeros(len(ii));two=np.zeros(len(ii))
    # Track only 0/1/2 successes in all leave-two-out distributions in parallel.
    for k,value in enumerate(p):
        prob=np.where((ii!=k)&(kk!=k),value,0.)
        two=(1-prob)*two+prob*one
        one=(1-prob)*one+prob*zero
        zero=(1-prob)*zero
    out=np.zeros((len(ii),2,2,3))
    for ea in range(2):
        for eb in range(2):
            own=(p[ii] if ea else 1-p[ii])*(p[kk] if eb else 1-p[kk])
            if ea+eb==0:bins=np.column_stack([one,two,np.maximum(0,1-zero-one-two)])
            elif ea+eb==1:bins=np.column_stack([zero,one,np.maximum(0,1-zero-one)])
            else:bins=np.column_stack([np.zeros(len(ii)),zero,np.maximum(0,1-zero)])
            out[:,ea,eb,:]=own[:,None]*bins*scale[None,:]
    np.testing.assert_allclose(out.sum(axis=(1,2,3)),1,atol=1e-9)
    return {(int(i),int(k)):out[j] for j,(i,k) in enumerate(zip(ii,kk))}


def build_pairs(scores,q,late,aux):
    """All symmetric normal-finisher pairs; no actual late states in inputs."""
    lookup=q.set_index('row_key');ll=late.set_index('row_key');aa=aux.set_index('row_key')
    matrices=[];meta=[];base_cols=None;full_cols=None
    # Pair keys refer to actual full fields; forecasts for normal finishers retain omitted starters.
    unsupported=[]
    supported_lookup=set(lookup.index);supported_late=set(ll.index);supported_early=set(aa.index)
    early_groups=aa.groupby('source_key',sort=False).indices
    for race_index,(key,g) in enumerate(scores.groupby('source_key',sort=True)):
        g=g.sort_values('program_no').reset_index(drop=True)
        n=len(g);keys=g.row_key
        keyset=set(keys)
        if not keyset.issubset(supported_lookup) or not keyset.issubset(supported_late) or not keyset.issubset(supported_early):
            assert int(g.year.iloc[0])<2024,'Evaluation roster must stay complete'
            unsupported.append(dict(source_key=key,year=int(g.year.iloc[0]),normal_starts=n,
                                    reason='historical OOF race outside frozen pace roster'))
            continue
        hist=lookup.loc[keys];pred=ll.loc[keys];early=aa.loc[keys]
        s=g.score_S.to_numpy();rank=pd.Series(s).rank(ascending=False,method='min').to_numpy()
        vals={'score':s,'rank':rank/n,'top3':pred.chain_top3.to_numpy(),
              'strict':pred.chain_strict_survive.to_numpy(),'g3':pred.chain_g3_front.to_numpy(),
              'g1':pred.chain_g1_front.to_numpy(),'lead_finish':pred.chain_lead_top3.to_numpy(),
              'nonlead_finish':pred.chain_nonlead_top3.to_numpy()}
        for col in HIST:vals[col]=hist[col].to_numpy(float)
        base={};ii,kk=np.triu_indices(n,1)
        for col,v in vals.items():
            base[col+'_min']=np.minimum(v[ii],v[kk]);base[col+'_max']=np.maximum(v[ii],v[kk])
        base['score_sum']=s[ii]+s[kk];base['top3_product']=vals['top3'][ii]*vals['top3'][kk]
        grade=pd.to_numeric(pd.Series([g.grade.iloc[0]]).str.extract(r'(\d+)',expand=False),errors='coerce').iloc[0]
        for name,value in [('distance',g.distance.iloc[0]),('grade',grade),('normal_n',n),
                           ('field_size',hist.field_size.iloc[0])]:base[name]=np.full(len(ii),value)
        # Joint S1F relation uses the entire original field, including nonfinishers.
        complete=aa.iloc[early_groups[key]].sort_values('gate')
        position={row:int(i) for i,row in enumerate(complete.index)}
        pi=complete[['J_count1','J_count2','J_count3p']].iloc[0].to_numpy(float)
        dist=pair_joint(complete.raw_lead.to_numpy(float),pi)
        rel={name:np.zeros(len(ii)) for name in ['early_both','early_one','scenario_both_top3',
             'scenario_both_lead_finish','scenario_mixed_finish','scenario_neither_finish',
             'conditional_dependence','late600_gap','late200_gap','early_gap','gate_gap',
             'inner_late_advantage']}
        cond=np.empty((n,2,3))
        for e in range(2):
            for c in range(3):cond[:,e,c]=pred[f'chain_cond_e{e}_n{c}']
        for outidx,(i,k) in enumerate(zip(ii,kk)):
            ai,ak=position[keys.iloc[i]],position[keys.iloc[k]]
            if ai>ak:
                mass=dist[(ak,ai)].transpose(1,0,2)
            else:mass=dist[(ai,ak)]
            rel['early_both'][outidx]=mass[1,1].sum()
            rel['early_one'][outidx]=mass[1,0].sum()+mass[0,1].sum()
            for ea in range(2):
                for eb in range(2):
                    value=float((mass[ea,eb]*cond[i,ea]*cond[k,eb]).sum())
                    rel['scenario_both_top3'][outidx]+=value
                    part='scenario_both_lead_finish' if ea and eb else 'scenario_neither_finish' if not ea and not eb else 'scenario_mixed_finish'
                    rel[part][outidx]+=value
        rel['conditional_dependence']=rel['scenario_both_top3']-base['top3_product']
        rel['late600_gap']=abs(vals['last600_peer_adv_mean5'][ii]-vals['last600_peer_adv_mean5'][kk])
        rel['late200_gap']=abs(vals['late_peer_adv_mean5'][ii]-vals['late_peer_adv_mean5'][kk])
        rel['early_gap']=abs(vals['early_adv_mean5'][ii]-vals['early_adv_mean5'][kk])
        gate=hist.gate.to_numpy();rel['gate_gap']=abs(gate[ii]-gate[kk])
        lateadv=vals['late_peer_adv_mean5']
        rel['inner_late_advantage']=np.where(gate[ii]<gate[kk],lateadv[ii]-lateadv[kk],lateadv[kk]-lateadv[ii])
        if base_cols is None:base_cols=list(base);full_cols=base_cols+list(rel)
        frame=pd.DataFrame(base|rel).astype(np.float32);matrices.append(frame)
        r=g.finish_rank.to_numpy()
        meta.append(pd.DataFrame(dict(source_key=key,date=str(g.date.iloc[0]),year=int(g.year.iloc[0]),
              distance=int(g.distance.iloc[0]),grade=str(g.grade.iloc[0]),normal_n=n,
              a_program=g.program_no.to_numpy()[ii],b_program=g.program_no.to_numpy()[kk],
              a_row_key=keys.to_numpy()[ii],b_row_key=keys.to_numpy()[kk],
              both_top3=((r[ii]<=3)&(r[kk]<=3)).astype(int),
              quinella=np.array([d.prior.quinella(va,vb) for va,vb in zip(r[ii],r[kk])],int),
              race_weight=1/len(ii))))
        if (race_index+1)%750==0:print('Prepared pair inputs',race_index+1,'races',flush=True)
    matrix=pd.concat(matrices,ignore_index=True);meta=pd.concat(meta,ignore_index=True)
    assert len(matrix)==len(meta) and not meta.duplicated(['source_key','a_program','b_program']).any()
    d.save('pair_feature_contract.json',dict(base=base_cols,full=full_cols,symmetric=True,
         actual_current_positions_in_inputs=False,all_normal_finisher_pairs=True,
         conditional_late_independence_is_approximation=True))
    d.save('pair_training_support.json',dict(excluded_historical_races=unsupported,
             evaluation_races_excluded=0,pair_rows=len(meta)))
    return matrix,meta,base_cols,full_cols


def train_pairs(scores,q,late,aux):
    path=d.O/'pair_predictions.parquet'
    if path.exists():return pd.read_parquet(path)
    matrix,meta,bcols,fcols=build_pairs(scores,q,late,aux)
    out=meta[meta.year.ge(2024)].copy()
    for year in [2024,2025,2026]:
        tr=meta.year.lt(year);te=meta.year.eq(year)
        assert meta.loc[tr,'date'].max()<meta.loc[te,'date'].min()
        for target in ['both_top3','quinella']:
            for name,cols in [('base',bcols),('full',fcols)]:
                model=fit(f'{year}_pair_{target}_{name}',matrix.loc[tr,cols],meta.loc[tr,target],
                    meta.loc[tr,'race_weight'],PARAMS|dict(objective='binary',min_data_in_leaf=150),
                    180,pd.to_datetime(meta.loc[tr,'date']))
                out.loc[te[te.index.isin(out.index)],'p_'+target+'_'+name]=model.predict(matrix.loc[te,cols],num_threads=4)
    out.to_parquet(path,index=False)
    # Retain only an independently reproducible small sample of pair input rows.
    ix=np.linspace(0,len(matrix)-1,41).astype(int)
    pd.concat([meta.iloc[ix].reset_index(drop=True),matrix.iloc[ix].reset_index(drop=True).add_prefix('input_')],axis=1).to_parquet(d.O/'pair_input_samples.parquet',index=False)
    return out


def main():
    d.check();assert (d.O/'bias_summary.json').exists(),'Run bias audit before fitting.'
    q,h,x,races,aux,p,j=d.load()
    late=train_chain(q,h,x,aux)
    scores=train_scores(q,h,p,j,late)
    pairs=train_pairs(scores,q,late,aux)
    d.save('run_summary.json',dict(new_chain_models=21,new_finish_models=14,new_pair_models=12,
       new_models=47,evaluation_races=1976,pair_eval_rows=len(pairs),source_end='2026-09-18',
       current_actual_pace_at_inference=False,jockey_trainer=False,production_changed=False,
       full_race_joint_finish_distribution=False))
    d.check();print('Completed47 model fits and chronological pair predictions.',flush=True)


if __name__=='__main__':main()

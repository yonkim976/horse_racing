"""Independent labels/history/latent paths/pair symmetry/model and selection checks."""
import itertools
import json
import math
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import false_discovery_control
import data as d
import train as tr


def main():
    d.check();q,h,x,races,aux,p,j=d.load()
    late=pd.read_parquet(d.O/'late_predictions.parquet')
    scores=pd.read_parquet(d.O/'external_scores.parquet')
    pairs=pd.read_parquet(d.O/'pair_predictions.parquet')
    assert json.loads((d.O/'run_summary.json').read_text())['new_models']==47
    assert pairs.source_key.nunique()==1976
    assert pairs.groupby('source_key').size().eq(pairs.groupby('source_key').normal_n.first().map(lambda n:n*(n-1)//2)).all()
    assert not pairs.duplicated(['source_key','a_program','b_program']).any()
    assert (pairs.a_program<pairs.b_program).all()
    for col in [c for c in pairs if c.startswith('p_')]:assert pairs[col].between(0,1).all(),col
    np.testing.assert_allclose(pairs.groupby('source_key').race_weight.sum(),1,atol=1e-12)
    ranklookup=scores.set_index(['source_key','program_no']).finish_rank
    av=pd.MultiIndex.from_frame(pairs[['source_key','a_program']].rename(columns={'a_program':'program_no'}))
    bv=pd.MultiIndex.from_frame(pairs[['source_key','b_program']].rename(columns={'b_program':'program_no'}))
    ar=ranklookup.reindex(av).to_numpy();br=ranklookup.reindex(bv).to_numpy()
    np.testing.assert_array_equal(pairs.both_top3,((ar>=1)&(ar<=3)&(br>=1)&(br<=3)).astype(int))
    win=((ar==1)&np.isin(br,[1,2]))|((br==1)&np.isin(ar,[1,2]))
    np.testing.assert_array_equal(pairs.quinella,win.astype(int))

    # Independently reconstruct recent-five conditional histories from scalar past records.
    raw=pd.read_parquet(d.prior.PACE/'feature_context.parquet').sort_values(['horse_id','date']).reset_index(drop=True)
    grouped={horse:g for horse,g in raw.groupby('horse_id',sort=False)}
    rng=np.random.default_rng(d.SEED)
    history_checks=0
    for ix in rng.choice(len(q),size=120,replace=False):
        current=q.iloc[ix];past=grouped[current.horse_id]
        past=past[past.date<current.date].tail(5)
        values=[[] for _ in range(5)]
        for r in past.itertuples():
            age=(current.date-r.date).days
            if not 2<=age<=730:continue
            known=1<=r.raw_finish_rank<=30 or r.raw_finish_rank in [91,92]
            yy=float(1<=r.raw_finish_rank<=3)
            lead=bool(r.group_observed and r.role4==0)
            g3=(r.g3f-1)/(r.field_size-1)<=1/3 if r.g3f_complete else None
            g1=(r.g1f-1)/(r.field_size-1)<=1/3 if r.g1f_complete else None
            if lead and g3 is not None:values[0].append(float(g3))
            if lead and g1 is not None:values[1].append(float(g1))
            if lead and g3 is not None and g1 is not None and known:values[2].append(float(g3 and g1 and yy))
            if lead and g1 and known:values[3].append(yy)
            if r.group_observed and not lead and known:values[4].append(yy)
        for name,v in zip(['leader_g3_hold','leader_g1_hold','leader_strict_survive','leader_g1_finish','nonleader_finish'],values):
            assert h.iloc[ix][name+'_n5']==len(v)
            np.testing.assert_allclose(h.iloc[ix][name+'_mean5'],np.mean(v) if v else np.nan,atol=1e-12,equal_nan=True)
            history_checks+=1
    # Actual future labels cannot alter a past history or their own history.
    _,original_h=d.histories(raw)
    altered=raw.copy();future=altered.year.eq(2026)
    altered.loc[future,['g3f_p','g1f_p','raw_finish_rank']]=0
    _,future_h=d.histories(altered)
    np.testing.assert_allclose(original_h[raw.year.lt(2026)],future_h[raw.year.lt(2026)],atol=0,rtol=0,equal_nan=True)
    altered=raw.copy();altered.loc[len(raw)-1,['g3f_p','g1f_p','raw_finish_rank']]=0
    _,own_h=d.histories(altered)
    np.testing.assert_allclose(original_h.iloc[-1],own_h.iloc[-1],atol=0,rtol=0,equal_nan=True)

    # Bias cohort and missingness counts from original ranks, not fitted model outputs.
    biasq=d.build_bias_context(q,p)
    valid=set(pd.read_csv(d.R/'20261021_busan_leader_pack_outcomes/outputs/race_outcomes.csv').source_key)
    z=biasq[biasq.source_key.isin(valid)].copy()
    coverage=pd.read_csv(d.O/'late_observation_coverage.csv')
    for r in coverage.itertuples():
        use=z[z.normal_outcome.eq(r.normal)&z.top3.eq(r.top3)]
        assert len(use)==r.starts and use.g3front.isna().sum()==r.g3_missing and use.g1front.isna().sum()==r.g1_missing
    # Verify same-population pooled standardization, including support counts and coverage.
    standardized=pd.read_csv(d.O/'horse_standardized_comparisons.csv',dtype={'period':str})
    for r in standardized.itertuples():
        a=z if r.period=='all' else z[z.year.eq(int(r.period))]
        if r.comparison=='leader_vs_other':a=a.assign(gr=a.leader.astype(int))
        else:
            a=a[a.leader&a.past_late_type.isin(['both_fast','g3_only'])].copy()
            a['gr']=a.past_late_type.eq('both_fast').astype(int)
        cells=[]
        for _,g in a.groupby(['distance_m','grade_band','field_band','ability_band','history_band']):
            left=g[g.gr.eq(0)];right=g[g.gr.eq(1)]
            if len(left)>=10 and len(right)>=10:cells.append((len(g),left.top3.mean(),right.top3.mean(),len(left),len(right)))
        assert len(cells)==r.cells
        if cells:
            aa=np.array(cells,float);delta=np.average(aa[:,2]-aa[:,1],weights=aa[:,0])
            np.testing.assert_allclose(delta,r.standardized_difference,atol=1e-12)
            assert aa[:,3].sum()==r.supported_n0 and aa[:,4].sum()==r.supported_n1
    # All observed pair numerators are reconstructed from full original starter rosters.
    counters={}
    for key,g in z.groupby('source_key'):
        ii,kk=np.triu_indices(len(g),1);year=int(g.year.iloc[0])
        lead=g.leader.to_numpy(int);rank=g.raw_finish_rank.to_numpy()
        typ=lead[ii]+lead[kk]
        both=((rank[ii]>=1)&(rank[ii]<=3)&(rank[kk]>=1)&(rank[kk]<=3)).astype(int)
        win=(((rank[ii]==1)&np.isin(rank[kk],[1,2]))|((rank[kk]==1)&np.isin(rank[ii],[1,2]))).astype(int)
        for period in ['all',str(year)]:
            for k in range(3):
                mask=typ==k
                count=counters.setdefault((period,k),np.zeros(3,dtype=int))
                count += [int(mask.sum()),int(both[mask].sum()),int(win[mask].sum())]
    for r in pd.read_csv(d.O/'pair_observed_rates.csv',dtype={'period':str}).itertuples():
        np.testing.assert_array_equal(counters[(r.period,r.lead_type)],[r.pairs,r.both_top3,r.quinella])
    pair_cells=pd.read_csv(d.O/'pair_common_cells.csv',dtype={'period':str})
    for r in pd.read_csv(d.O/'pair_standardized_comparisons.csv',dtype={'period':str}).itertuples():
        cells=pair_cells[pair_cells.period.eq(r.period)&pair_cells.outcome.eq(r.outcome)]
        left=cells[cells.both_lead.eq(0)];right=cells[cells.both_lead.eq(1)]
        assert len(left)==len(right)==r.cells and left['size'].ge(20).all() and right['size'].ge(20).all()
        calculated=(right.weight*right['mean']).sum()-(left.weight*left['mean']).sum()
        np.testing.assert_allclose(calculated,r.standardized_difference,atol=1e-12)

    # Every stored model has an independently reconstructed training mask and feature contract.
    newx=pd.concat([x,h],axis=1)
    countmap=pd.read_csv(d.R/'20261021_busan_leader_pack_outcomes/outputs/race_outcomes.csv').set_index('source_key').leader_count
    cnt=np.minimum(q.source_key.map(countmap).fillna(1).to_numpy(int)-1,2)
    H,S=tr.main_matrices(q,h,p,j,late)
    total_models=0;replay_max=0.;path_checks=0
    for year in range(2020,2027):
        models={}
        for stage,target in [('g3','g3front'),('g1','g1front'),('end','top3')]:
            take=q.year.lt(year)&q.group_observed&q[target].notna()
            if stage in ['g1','end']:take &= q.g3front.notna()
            if stage=='end':take &= q.g1front.notna()
            meta=json.loads((d.M/f'{year}_chain_{stage}.json').read_text())
            path=d.M/f'{year}_chain_{stage}.txt'
            assert meta['n']==int(take.sum()) and meta['model_sha256']==d.sha(path)
            assert pd.Timestamp(meta['train_end'])==q.loc[take,'date'].max()<pd.Timestamp(f'{year}-01-01')
            models[stage]=lgb.Booster(model_file=str(path));total_models+=1
        # Re-infer small full-field samples, then independently enumerate all24 paths per horse.
        keys=q[q.year.eq(year)].source_key.drop_duplicates().to_numpy()
        chosen=keys[[0,len(keys)//2,-1]]
        use=q[q.source_key.isin(chosen)].index
        g3,g1,end=tr.scenario_predictions(models,newx.loc[use].reset_index(drop=True))
        actual=late.set_index('row_key').loc[q.loc[use,'row_key']]
        early=aux.set_index('row_key').loc[q.loc[use,'row_key']]
        for row in range(len(use)):
            calc=np.zeros(8);conditional=np.zeros((2,3))
            for e,c,m,l in itertools.product(range(2),range(3),range(2),range(2)):
                name=['1','2','3p'][c]
                w=float(early.iloc[row]['J_member'+name])
                if not e:w=float(early.iloc[row]['J_count'+name])-w
                mid=float(g3[row,e,c]);last=float(g1[row,e,c,m]);success=float(end[row,e,c,m,l])
                pathprob=(mid if m else 1-mid)*(last if l else 1-last)
                final=pathprob*success;conditional[e,c]+=final
                calc[0]+=w*pathprob*m;calc[1]+=w*pathprob*l;calc[2]+=w*final
                if e:
                    calc[4]+=w*final
                    if m and l:calc[3]+=w*final
                    if m and not l:calc[6]+=w*pathprob
                    if not m and l:calc[7]+=w*pathprob
                else:calc[5]+=w*final
            stored=actual.iloc[row][['chain_'+n for n in tr.LATE]].to_numpy(float)
            np.testing.assert_allclose(calc,stored,atol=1e-12,rtol=0)
            np.testing.assert_allclose(conditional.ravel(),actual.iloc[row][[f'chain_cond_e{e}_n{c}' for e in range(2) for c in range(3)]].to_numpy(float),atol=1e-12,rtol=0)
            path_checks+=1
        train=p.year.between(2017,year-1)&p.normal_n.ge(6);test=p.year.eq(year)&p.normal_n.ge(6)
        for name,matrix in [('H',H),('S',S)]:
            meta=json.loads((d.M/f'{year}_finish_{name}.json').read_text());path=d.M/f'{year}_finish_{name}.txt'
            assert meta['n']==int(train.sum()) and meta['model_sha256']==d.sha(path)
            assert pd.Timestamp(meta['train_end'])==pd.to_datetime(p.loc[train,'date']).max()<pd.Timestamp(f'{year}-01-01')
            model=lgb.Booster(model_file=str(path));assert model.feature_name()==list(matrix.columns)
            pred=model.predict(matrix.loc[test],num_threads=4)
            truth=scores.set_index('row_id').loc[p.loc[test,'row_id'],'score_'+name].to_numpy()
            replay_max=max(replay_max,float(abs(pred-truth).max()));np.testing.assert_allclose(pred,truth,atol=1e-12,rtol=0)
            total_models+=1
    # A source sample carries enough symmetric inputs for exact pair-model replays.
    sample=pd.read_parquet(d.O/'pair_input_samples.parquet')
    paircontract=json.loads((d.O/'pair_feature_contract.json').read_text())
    labelmeta=pairs.set_index(['source_key','a_program','b_program'])
    # Recompute symmetric pair inputs from the two individual histories and forecasts.
    qq=q.set_index('row_key');ll=late.set_index('row_key');ss=scores.set_index('row_key')
    aa=aux.set_index('row_key');source_groups=aux.groupby('source_key',sort=False).indices
    scalar_pair_checks=0
    for row in sample.itertuples():
        keys=[row.a_row_key,row.b_row_key];hist=qq.loc[keys];pred=ll.loc[keys];sc=ss.loc[keys]
        g=scores[scores.source_key.eq(row.source_key)]
        ranks=[(int((g.score_S>value).sum())+1)/len(g) for value in sc.score_S]
        vals={'score':sc.score_S.to_numpy(),'rank':np.asarray(ranks),'top3':pred.chain_top3.to_numpy(),
              'strict':pred.chain_strict_survive.to_numpy(),'g3':pred.chain_g3_front.to_numpy(),
              'g1':pred.chain_g1_front.to_numpy(),'lead_finish':pred.chain_lead_top3.to_numpy(),
              'nonlead_finish':pred.chain_nonlead_top3.to_numpy()}
        for name in tr.HIST:vals[name]=hist[name].to_numpy(float)
        for name,value in vals.items():
            for suffix,expected in [('min',np.minimum(value[0],value[1])),('max',np.maximum(value[0],value[1]))]:
                np.testing.assert_allclose(getattr(row,'input_'+name+'_'+suffix),expected,atol=1e-6,rtol=1e-6,equal_nan=True)
                scalar_pair_checks+=1
        np.testing.assert_allclose(row.input_score_sum,vals['score'].sum(),atol=1e-6,rtol=1e-6)
        np.testing.assert_allclose(row.input_top3_product,vals['top3'].prod(),atol=1e-6,rtol=1e-6)
        original=aux.iloc[source_groups[row.source_key]].sort_values('gate')
        pv=np.clip(original.raw_lead.to_numpy(),1e-6,1-1e-6)
        i=int(np.flatnonzero(original.row_key.eq(keys[0]))[0]);k=int(np.flatnonzero(original.row_key.eq(keys[1]))[0])
        rest=np.delete(pv,[i,k]);poly=np.array([1.])
        for probability in rest:poly=np.convolve(poly,[1-probability,probability])
        fullpoly=poly.copy()
        for probability in [pv[i],pv[k]]:fullpoly=np.convolve(fullpoly,[1-probability,probability])
        pi=original[['J_count1','J_count2','J_count3p']].iloc[0].to_numpy(float)
        scale=pi/np.array([fullpoly[1],fullpoly[2],fullpoly[3:].sum()])
        mass=np.zeros((2,2,3))
        for ea,eb in itertools.product(range(2),repeat=2):
            own=(pv[i] if ea else 1-pv[i])*(pv[k] if eb else 1-pv[k])
            for n,pr in enumerate(poly):
                total=n+ea+eb
                if total:mass[ea,eb,min(total-1,2)]+=own*pr*scale[min(total-1,2)]
        conditional=np.array([[[pred.iloc[ii][f'chain_cond_e{e}_n{c}'] for c in range(3)] for e in range(2)] for ii in range(2)])
        expected=sum(float((mass[e,f]*conditional[0,e]*conditional[1,f]).sum()) for e,f in itertools.product(range(2),repeat=2))
        np.testing.assert_allclose([row.input_early_both,row.input_early_one,row.input_scenario_both_top3],
             [mass[1,1].sum(),mass[0,1].sum()+mass[1,0].sum(),expected],atol=1e-6,rtol=1e-6)
    for year in [2024,2025,2026]:
        for target in ['both_top3','quinella']:
            for typ in ['base','full']:
                path=d.M/f'{year}_pair_{target}_{typ}.txt';meta=json.loads(path.with_suffix('.json').read_text())
                assert meta['model_sha256']==d.sha(path) and pd.Timestamp(meta['train_end'])<pd.Timestamp(f'{year}-01-01')
                training=scores[scores.year.lt(year)].groupby('source_key').size()
                assert meta['n']==int((training*(training-1)/2).sum())
                model=lgb.Booster(model_file=str(path));cols=paircontract[typ];assert model.feature_name()==cols
                rows=sample[sample.year.eq(year)];matrix=rows[['input_'+c for c in cols]].copy();matrix.columns=cols
                if len(rows):
                    pred=model.predict(matrix,num_threads=4)
                    expected=labelmeta.loc[pd.MultiIndex.from_frame(rows[['source_key','a_program','b_program']]),'p_'+target+'_'+typ]
                    np.testing.assert_allclose(pred,expected,atol=1e-12,rtol=0)
                total_models+=1
    assert total_models==47

    # Joint early pair states are checked against exhaustive subsets and pair reversal.
    for key in q[q.year.eq(2026)].source_key.drop_duplicates().head(4):
        early=aux[aux.source_key.eq(key)].sort_values('gate');n=len(early)
        pv=np.clip(early.raw_lead.to_numpy(),1e-6,1-1e-6)
        pi=early[['J_count1','J_count2','J_count3p']].iloc[0].to_numpy(float)
        masks=np.array(list(itertools.product([0,1],repeat=n)),int)[1:]
        base=np.prod(np.where(masks,pv,1-pv),axis=1);category=np.minimum(masks.sum(axis=1)-1,2)
        den=np.bincount(category,weights=base,minlength=3);weight=base*pi[category]/den[category]
        joint=tr.pair_joint(pv,pi)
        rev=tr.pair_joint(pv[::-1],pi)
        for (i,k),mass in joint.items():
            brute=np.zeros((2,2,3))
            for m,c,w in zip(masks,category,weight):brute[m[i],m[k],c]+=w
            np.testing.assert_allclose(mass,brute,atol=1e-10,rtol=0)
            np.testing.assert_allclose(mass,rev[(n-1-k,n-1-i)].transpose(1,0,2),atol=1e-10,rtol=0)

    # Selections and all reported rate totals independently from stored candidate scores.
    rr=pd.read_csv(d.O/'race_metrics.csv').set_index('source_key')
    checks=0
    for key,g in scores[scores.year.ge(2024)].groupby('source_key'):
        pp=pairs[pairs.source_key.eq(key)];ranks=dict(zip(g.program_no.astype(int),g.finish_rank.astype(int)))
        for name in ['B','J','H','S','PB','PF']:
            if name in ['PB','PF']:
                typ='base' if name=='PB' else 'full'
                strength={v:0. for v in ranks}
                for item in pp.itertuples():
                    value=getattr(item,'p_both_top3_'+typ);strength[int(item.a_program)]+=value;strength[int(item.b_program)]+=value
                anchor=sorted(strength,key=lambda v:(-strength[v],v))[0]
                qn=sorted(pp.to_dict('records'),key=lambda a:(-a['p_quinella_'+typ],a['a_program'],a['b_program']))[:3]
                qpl=sorted(pp.to_dict('records'),key=lambda a:(-a['p_both_top3_'+typ],a['a_program'],a['b_program']))[:3]
            else:
                lookup=dict(zip(g.program_no.astype(int),g['score_'+name]));anchor=sorted(lookup,key=lambda v:(-lookup[v],v))[0]
                qn=sorted(pp.to_dict('records'),key=lambda a:(-lookup[a['a_program']]-lookup[a['b_program']],a['a_program'],a['b_program']))[:3];qpl=qn
            assert rr.loc[key,name+'_axis_top3']==int(ranks[anchor]<=3)
            assert rr.loc[key,name+'_quinella_one']==qn[0]['quinella']
            assert rr.loc[key,name+'_quinella_three']==int(any(a['quinella'] for a in qn))
            assert rr.loc[key,name+'_qpl_one']==qpl[0]['both_top3']
            assert rr.loc[key,name+'_qpl_three_count']==sum(a['both_top3'] for a in qpl)
            checks+=1
    summary=pd.read_csv(d.O/'selection_metrics.csv',dtype={'window':str})
    for row in summary.itertuples():
        z=rr if row.window=='all' else rr[rr.year.eq(int(row.window))]
        assert row.races==len(z)
        for metric in ['axis_top3','quinella_one','quinella_three','qpl_one','qpl_three_any','qpl_three_count']:
            np.testing.assert_allclose(getattr(row,metric),z[row.model+'_'+metric].mean(),atol=1e-12)
    dif=pd.read_csv(d.O/'paired_comparisons.csv',dtype={'window':str})
    for row in dif.itertuples():
        z=rr if row.window=='all' else rr[rr.year.eq(int(row.window))]
        delta=z[row.new+'_'+row.metric]-z[row.old+'_'+row.metric]
        days=pd.DataFrame(dict(date=z.date,delta=delta)).groupby('date').delta.agg(['sum','size'])
        rng=np.random.default_rng(d.SEED);ix=rng.integers(0,len(days),size=(2000,len(days)))
        boot=days['sum'].to_numpy()[ix].sum(axis=1)/days['size'].to_numpy()[ix].sum(axis=1)
        lo,hi=np.quantile(boot,[.025,.975]);np.testing.assert_allclose([row.difference,row.lower,row.upper],[delta.mean(),lo,hi],atol=1e-12)
    mask=dif.bh_q_primary5.notna();assert mask.sum()==5
    np.testing.assert_allclose(false_discovery_control(dif.loc[mask,'p_boot']),dif.loc[mask,'bh_q_primary5'],atol=1e-12)
    d.check()
    d.save('verification.json',dict(status='verified',new_models_checked=47,history_scalar_checks=history_checks,
        latent_paths_enumerated_horses=path_checks,finish_replay_max_error=replay_max,
        pair_event_rows_verified=len(pairs),race_model_selections_verified=checks,
        paired_contrasts_verified=len(dif),bias_standardization_checked=True,
        observed_pair_rate_tables_checked=True,pair_scalar_feature_checks=scalar_pair_checks,
        pair_joint_enumeration_and_reversal=True,future_mutation_safe=True,
        current_actual_late_inputs_excluded=True,training_chronology_checked=True,
        production_unchanged=True,conditional_normal_finisher_evaluation=True))
    print((d.O/'verification.json').read_text())


if __name__=='__main__':main()

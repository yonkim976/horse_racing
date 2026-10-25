"""One prior-year utility model, with an explicit validation selection policy."""
import json
import numpy as np
import pandas as pd
from scipy.special import logsumexp,softmax
from scipy.optimize import minimize
import axis_common as c

def matrix(frame,encoding=None):
    values=frame[c.FEATURES].to_numpy(float)
    if encoding is None:
        med=np.array([np.nanmedian(x) if np.isfinite(x).any() else 0. for x in values.T])
        filled=np.where(np.isfinite(values),values,med);mean=filled.mean(0);sd=filled.std(0)
        sd=np.where(sd>1e-8,sd,1.)
        encoding={'median':med.tolist(),'mean':mean.tolist(),'scale':sd.tolist()}
    med=np.array(encoding['median']);mean=np.array(encoding['mean']);sd=np.array(encoding['scale'])
    missing=~np.isfinite(values);filled=np.where(missing,med,values)
    x=np.column_stack([np.ones(len(frame)),np.clip((filled-mean)/sd,-8,8),missing.astype(float)])
    assert np.isfinite(x).all()
    return x,encoding

def probabilities(x,w):
    pair=x@w.T;logits=np.column_stack([pair[:,0],np.zeros(len(x)),pair[:,1]])
    return softmax(logits,axis=1)

def objective(flat,x,y,ridge=.1):
    w=flat.reshape(2,x.shape[1]);pair=x@w.T
    logits=np.column_stack([pair[:,0],np.zeros(len(x)),pair[:,1]])
    lp=logits-logsumexp(logits,axis=1,keepdims=True);p=np.exp(lp)
    truth=(y+1).astype(int);target=np.eye(3)[truth]
    loss=-lp[np.arange(len(y)),truth].mean()+ridge/2*np.square(w[:,1:]).sum()
    grad=(p-target)[:,[0,2]].T@x/len(y);grad[:,1:]+=ridge*w[:,1:]
    return float(loss),grad.ravel()

def fit(frame):
    x,enc=matrix(frame);y=frame.switch_label.to_numpy(int)
    opt=minimize(objective,np.zeros(2*x.shape[1]),args=(x,y),jac=True,method='L-BFGS-B',
        options={'maxiter':300,'ftol':1e-12,'gtol':1e-8})
    assert opt.success and np.isfinite(opt.x).all(),opt.message
    return {'features':c.FEATURES,'encoding':enc,'coefficients':opt.x.reshape(2,x.shape[1]).tolist(),
        'classes':['lose','neutral','gain'],'ridge':.1,'threshold':.05,'iterations':int(opt.nit),
        'objective':float(opt.fun),'gradient_norm':float(np.linalg.norm(opt.jac)),
        'fit_races':len(frame),'fit_start':str(frame.race_date.min().date()),'fit_end':str(frame.race_date.max().date()),
        'label_counts':{str(k):int((y==k).sum()) for k in [-1,0,1]}}

def predict(frame,model):
    assert model['features']==c.FEATURES
    x,_=matrix(frame,model['encoding']);p=probabilities(x,np.array(model['coefficients']))
    return p,p[:,2]-p[:,0]

def main():
    c.check();pairs=pd.read_parquet(c.OUT/'pairs.parquet');predictions=[];gates=[]
    for year in [2024,2025,2026]:
        path=c.OUT/'models'/f'{year}.json';assert not path.exists(),'No repeat tuning'
        prior=pairs[pairs.fold_year.eq(year)&pairs.phase.eq('calibration')]
        test=pairs[pairs.fold_year.eq(year)&pairs.phase.eq('evaluation')].copy()
        first=prior[prior.race_date.dt.month.le(6)];second=prior[prior.race_date.dt.month.ge(7)]
        assert prior.year.eq(year-1).all() and test.year.eq(year).all()
        pilot=fit(first);_,utility=predict(second,pilot);switch=utility>.05
        diff=second.switch_label.to_numpy()*switch;t=second.target.to_numpy(bool)
        gate=bool((switch&t).sum()>=5 and diff[t].sum()>0 and diff.sum()>=0)
        selection={'evaluation_year':year,'validation_target_races':int(t.sum()),
            'validation_target_switches':int((switch&t).sum()),'validation_target_net':int(diff[t].sum()),
            'validation_all_busan_net':int(diff.sum()),'selected':gate}
        final=fit(prior)
        model={'pilot':pilot,'final':final,'selection':selection,'input_fingerprint':c.sha(c.OUT/'input_manifest.json'),
               'pair_fingerprint':c.sha(c.OUT/'pairs.parquet'),'evaluation_year':year,'fit_year':year-1}
        c.save(path,model);p,utility=predict(test,final)
        test['gain_probability']=p[:,2];test['loss_probability']=p[:,0];test['expected_gain']=utility
        test['candidate_switch']=(utility>.05)&test.target
        test['selected_switch']=test.candidate_switch&gate
        for name in ['candidate','selected']:
            test[name+'_hit']=np.where(test[name+'_switch'],test.alt_hit,test.axis_hit)
            test[name+'_program_no']=np.where(test[name+'_switch'],test.alt_program_no,test.axis_program_no)
            test[name+'_axis_probability']=np.where(test[name+'_switch'],test.alt_probability,test.axis_probability)
        predictions.append(test);gates.append(selection)
        print('Fit',year,selection,'eval target switches',int(test.candidate_switch.sum()),flush=True)
    out=pd.concat(predictions,ignore_index=True)
    out.to_parquet(c.OUT/'axis_predictions.parquet',index=False,compression='zstd')
    result={'selection':gates,'comparisons':{},'new_base_models':0,'final_switch_models':3,'pilot_switch_models':3,
        'joint_distribution_and_pair_recommendations_unchanged':True,'new_future_test':False,'production_changed':False}
    old=pd.read_parquet(c.PREV/'outputs/race_metrics.parquet').query("variant=='state_gbm'")
    for name in ['candidate','selected']:
        pieces={'target':c.paired(out[out.target],name+'_hit'),'all_busan':c.paired(out,name+'_hit')}
        for year in [2024,2025,2026]:pieces[f'target_{year}']=c.paired(out[out.target&out.year.eq(year)],name+'_hit')
        for dist in [1300,1600]:pieces[f'target_{dist}m']=c.paired(out[out.target&out.distance_m.eq(dist)],name+'_hit')
        allr=old[['race_key','race_date','axis_top3']].rename(columns={'axis_top3':'axis_hit'}).merge(
            out[['race_key',name+'_hit']],on='race_key',how='left',validate='one_to_one')
        allr[name+'_hit']=allr[name+'_hit'].fillna(allr.axis_hit)
        pieces['all_4799']=c.paired(allr,name+'_hit')
        pieces['switches']=int(out[name+'_switch'].sum());result['comparisons'][name]=pieces
    q=result['comparisons']['selected']
    result['retain']=(q['target']['difference_ci95'][0]>0 and q['target_2026']['net_hits']>=0 and q['all_4799']['net_hits']>=0)
    c.save(c.OUT/'switch_results.json',result)
    print('Switch experiment complete',result['retain'],c.storage(),flush=True)

if __name__=='__main__':main()

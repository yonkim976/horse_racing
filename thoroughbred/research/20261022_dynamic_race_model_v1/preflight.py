"""Substantive tests of time boundaries, masking and the joint likelihood."""
import numpy as np
import pandas as pd
import torch
import common as c
import state,joint

def main():
    joint.seed();rng=np.random.default_rng(3);checks={};errors=[]
    for n in [4,7,14]:
        model=joint.RaceNet(12);x=rng.normal(size=(n,12)).astype('float32')
        orders,p=joint.distribution(model,x,1.23)
        marginal=c.prob.marginals(n,orders,p)
        perm=rng.permutation(n);o2,p2=joint.distribution(model,x[perm],1.23)
        lookup={tuple(o):v for o,v in zip(orders,p)}
        error=max(abs(v-lookup[tuple(perm[o])]) for o,v in zip(o2,p2));errors.append(error)
        assert error<2e-7
        truth=np.array([[2,0,3]])
        logits,mix=model.teacher(torch.tensor(x)[None],torch.ones((1,n),dtype=torch.bool),torch.tensor(truth))
        likelihood=np.exp(-joint.nll(logits,mix,torch.tensor(truth),1.23).item())
        assert abs(likelihood-lookup[tuple(truth[0])])<2e-7
        # Padding adds no runners; gradients are finite under teacher forcing.
        padded=np.pad(x,((0,3),(0,0)));mask=torch.tensor([[True]*n+[False]*3])
        a,b=model.teacher(torch.tensor(padded)[None],mask,torch.tensor(truth))
        padded_loss=joint.nll(a,b,torch.tensor(truth),1.23)
        assert abs(padded_loss.item()+np.log(likelihood))<2e-6
        model.train();a,b=model.teacher(torch.tensor(padded)[None],mask,torch.tensor(truth))
        joint.nll(a,b,torch.tensor(truth)).mean().backward()
        assert all(torch.isfinite(q.grad).all() for q in model.parameters() if q.grad is not None)
        checks[f'joint_{n}']={'orders':len(orders),'sum':float(p.sum()),'permutation_error':error}
    rows=[]
    for day in [1,8,15,22,29,36]:
        date=pd.Timestamp('2020-01-01')+pd.Timedelta(days=day)
        for i in range(4):
            rows.append(dict(race_key=f'r{day}',race_date=date,horse_id=f'h{i}',program_no=i+1,
                result_distance=1400,finish_order=i+1,result_status='finished',record_index=1.-i,
                early_adjusted=13.5+i*.1,last600_adjusted=37.+i))
    h=pd.DataFrame(rows);target=pd.DataFrame({'horse_id':[f'h{i}' for i in range(4)],
        'distance_m':[1600]*4,'race_key':['query']*4,'row_number':np.arange(4),
        'cutoff_date':[pd.Timestamp('2020-01-20')]*4})
    first=state.generate(target,h)
    changed=h.copy();future=changed.race_date>target.cutoff_date.iloc[0]
    changed.loc[future,['record_index','early_adjusted','last600_adjusted']]=999.
    changed.loc[future,'finish_order']=5-changed.loc[future,'finish_order']
    second=state.generate(target,changed)
    pd.testing.assert_frame_equal(first,second)
    filt=state.Filter()
    for _,g in h.groupby('race_date'):filt.update(g)
    near,_=filt.query('h0',pd.Timestamp('2020-02-06'),1600)
    late,_=filt.query('h0',pd.Timestamp('2020-07-06'),1600)
    assert late[5]>near[5] and late[8]>near[8]
    checks['future_outcomes_do_not_change_prior_features']=True
    checks['source_cutoff']=(first.state_source_date<=target.cutoff_date).all().item()
    checks['layoff_uncertainty_increases']={'rank_sd':[near[5],late[5]],'form_sd':[near[8],late[8]]}
    c.save(c.OUT/'preflight.json',{'status':'passed','checks':checks,'maximum_permutation_error':max(errors)})
    print('Preflight passed',flush=True)

if __name__=='__main__':main()

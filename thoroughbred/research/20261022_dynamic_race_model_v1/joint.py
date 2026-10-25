"""Small permutation-equivariant field encoder and joint order decoder."""
import random
import numpy as np
import pandas as pd
import torch
from torch import nn
from scipy.special import logsumexp
from scipy.optimize import minimize_scalar
from safetensors.torch import save_file,load_file
import common as c

SEED=20261022
torch.set_num_threads(2)

def seed():
    random.seed(SEED);np.random.seed(SEED);torch.manual_seed(SEED)
    torch.use_deterministic_algorithms(True)

def encode(f,cols,mask=None,meta=None):
    if meta is None:
        meta={'numeric':{},'categories':{},'features':cols}
        for col in cols:
            if pd.api.types.is_numeric_dtype(f[col]):
                v=f.loc[mask,col].to_numpy(float);v=v[np.isfinite(v)]
                median=float(np.median(v)) if len(v) else 0.
                scale=max(float(np.std(v)),.05) if len(v) else 1.
                meta['numeric'][col]=[median,scale]
            else:meta['categories'][col]=sorted(f.loc[mask,col].dropna().unique().tolist())
    blocks=[]
    for col in cols:
        if col in meta['numeric']:
            median,scale=meta['numeric'][col];v=f[col].to_numpy(float)
            missing=~np.isfinite(v)
            blocks += [np.clip((np.where(missing,median,v)-median)/scale,-8,8)[:,None],missing[:,None]]
        else:
            cats=meta['categories'][col];codes=pd.Categorical(f[col],categories=cats).codes+1
            blocks.append(np.eye(len(cats)+1)[codes])
    x=np.concatenate(blocks,axis=1).astype('float32')
    assert np.isfinite(x).all()
    return x,meta

class RaceNet(nn.Module):
    def __init__(self,inputs):
        super().__init__();d=32
        self.embedding=nn.Sequential(nn.Linear(inputs,d),nn.GELU(),nn.LayerNorm(d))
        self.attention=nn.MultiheadAttention(d,2,dropout=.1,batch_first=True)
        self.norm=nn.LayerNorm(d)
        self.ff=nn.Sequential(nn.Linear(d,64),nn.GELU(),nn.Dropout(.1),nn.Linear(64,d))
        self.norm2=nn.LayerNorm(d)
        self.dropout=nn.Dropout(.1)
        self.key=nn.Linear(d,d);self.pool=nn.Linear(d,d)
        self.selected1=nn.Linear(d,d,bias=False);self.selected2=nn.Linear(d,d,bias=False)
        self.stages=nn.Parameter(torch.randn(3,d)*.05)
        self.scenarios=nn.Parameter(torch.randn(2,d)*.05)
        self.output=nn.Linear(d,1,bias=False);self.base=nn.Linear(d,1)
        self.mixture=nn.Linear(d,2)

    def field(self,x,mask):
        h=self.embedding(x)
        a,_=self.attention(h,h,h,key_padding_mask=~mask,need_weights=False)
        h=self.norm(h+self.dropout(a));h=self.norm2(h+self.ff(h))
        pooled=(h*mask[:,:,None]).sum(1)/mask.sum(1)[:,None]
        return h,pooled

    def logits(self,h,pooled,stage,first=None,second=None):
        context=self.pool(pooled)+self.stages[stage]
        if first is not None:context=context+self.selected1(first)
        if second is not None:context=context+self.selected2(second)
        z=context[:,None,:]+self.scenarios[None,:,:]
        return self.base(h).squeeze(-1)[:,None,:]+self.output(torch.tanh(
            self.key(h)[:,None,:,:]+z[:,:,None,:])).squeeze(-1)

    def teacher(self,x,mask,y):
        h,pooled=self.field(x,mask);rows=torch.arange(len(x));available=mask.clone()
        logits=[]
        for stage in range(3):
            q=self.logits(h,pooled,stage,h[rows,y[:,0]] if stage>=1 else None,
                          h[rows,y[:,1]] if stage>=2 else None)
            logits.append(q.masked_fill(~available[:,None,:],-1e9))
            available=available.clone();available[rows,y[:,stage]]=False
        return torch.stack(logits,dim=2),self.mixture(pooled)

def nll(logits,mix,y,temperature=1.):
    lp=torch.log_softmax(logits/temperature,dim=-1)
    target=y[:,None,:,None].expand(-1,2,-1,1)
    conditional=lp.gather(-1,target).squeeze(-1).sum(-1)
    return -torch.logsumexp(torch.log_softmax(mix,dim=-1)+conditional,dim=-1)

def dataset(f,x):
    groups=list(f.groupby('race_key',sort=False).indices.values());nmax=max(map(len,groups))
    X=np.zeros((len(groups),nmax,x.shape[1]),dtype='float32');mask=np.zeros(X.shape[:2],dtype=bool)
    y=np.zeros((len(groups),3),dtype='int64');years=[];keys=[]
    for i,ix in enumerate(groups):
        g=f.iloc[ix];X[i,:len(ix)]=x[ix];mask[i,:len(ix)]=True
        y[i]=[np.flatnonzero(g.outcome.to_numpy()==k)[0] for k in [1,2,3]]
        years.append(g.year.iloc[0]);keys.append(g.race_key.iloc[0])
    return torch.from_numpy(X),torch.from_numpy(mask),torch.from_numpy(y),np.array(years),keys

def fit(data,train,valid,inputs,epochs=64,early=True):
    seed();model=RaceNet(inputs)
    opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
    X,M,Y,_,_=data;indices=np.flatnonzero(train);rng=np.random.default_rng(SEED)
    best=float('inf');best_epoch=0;history=[]
    for epoch in range(1,epochs+1):
        model.train();total=0.
        for ix in np.array_split(rng.permutation(indices),max(1,int(np.ceil(len(indices)/128)))):
            opt.zero_grad(set_to_none=True)
            logits,mix=model.teacher(X[ix],M[ix],Y[ix]);loss=nll(logits,mix,Y[ix]).mean()
            assert torch.isfinite(loss)
            loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1.)
            opt.step();total+=loss.item()*len(ix)
        v=None
        if early:
            model.eval();v=0.;vix=np.flatnonzero(valid)
            with torch.no_grad():
                for ix in np.array_split(vix,max(1,int(np.ceil(len(vix)/256)))):
                    a,b=model.teacher(X[ix],M[ix],Y[ix]);v+=nll(a,b,Y[ix]).sum().item()
            v/=len(vix)
            if v<best-1e-5:best=v;best_epoch=epoch
        history.append({'epoch':epoch,'train_order_nll':total/len(indices),'validation_order_nll':v})
        if epoch%8==0:print('joint epoch',epoch,'train',round(total/len(indices),5),'valid',v,flush=True)
        if early and epoch-best_epoch>=10:break
    return model,(best_epoch if early else epochs),history

def calibrate(model,data,mask):
    X,M,Y,_,_=data;all_logits=[];all_mix=[];all_y=[]
    model.eval()
    with torch.no_grad():
        indices=np.flatnonzero(mask)
        for ix in np.array_split(indices,max(1,int(np.ceil(len(indices)/256)))):
            a,b=model.teacher(X[ix],M[ix],Y[ix]);all_logits.append(a.numpy().astype(float))
            all_mix.append(b.numpy().astype(float));all_y.append(Y[ix].numpy())
    a=np.concatenate(all_logits);b=np.concatenate(all_mix);y=np.concatenate(all_y)
    def loss(t):
        lp=a/t-logsumexp(a/t,axis=-1,keepdims=True)
        correct=np.take_along_axis(lp,y[:,None,:,None],axis=-1).squeeze(-1).sum(-1)
        return float(-np.mean(logsumexp(b-logsumexp(b,axis=-1,keepdims=True)+correct,axis=-1)))
    opt=minimize_scalar(loss,bounds=(.35,4.),method='bounded')
    assert opt.success
    return float(opt.x),{'uncalibrated_order_nll':loss(1.),'calibrated_order_nll':loss(opt.x)}

@torch.no_grad()
def distribution(model,x,temperature):
    """Enumerate every branch, then normalize in float64 for exact marginals."""
    n=len(x);X=torch.as_tensor(x,dtype=torch.float32)[None];mask=torch.ones((1,n),dtype=torch.bool)
    model.eval();h,pool=model.field(X,mask)
    mixture=model.mixture(pool).numpy()[0].astype(float)
    mixture=np.exp(mixture-logsumexp(mixture))
    q1=model.logits(h,pool,0).numpy()[0].astype(float)/temperature
    p1=np.exp(q1-logsumexp(q1,axis=-1,keepdims=True))
    q2=model.logits(h.expand(n,-1,-1),pool.expand(n,-1),1,h[0]).numpy().transpose(1,0,2).astype(float)/temperature
    q2[:,np.arange(n),np.arange(n)]=-np.inf
    p2=np.exp(q2-logsumexp(q2,axis=-1,keepdims=True))
    aa,bb=np.where(~np.eye(n,dtype=bool));count=len(aa)
    q3=model.logits(h.expand(count,-1,-1),pool.expand(count,-1),2,h[0,aa],h[0,bb]).numpy().transpose(1,0,2).astype(float)/temperature
    q3[:,np.arange(count),aa]=-np.inf;q3[:,np.arange(count),bb]=-np.inf
    p3=np.exp(q3-logsumexp(q3,axis=-1,keepdims=True))
    ordered=c.prob._cached_orders(n);first,second,third=ordered.T
    lookup=np.full((n,n),-1,int);lookup[aa,bb]=np.arange(count)
    mass=(mixture[:,None]*p1[:,first]*p2[:,first,second]*p3[:,lookup[first,second],third]).sum(axis=0)
    assert np.isfinite(mass).all() and (mass>=0).all() and abs(mass.sum()-1)<1e-10
    return ordered,mass

def store(model,path):save_file({k:v.contiguous() for k,v in model.state_dict().items()},str(path))
def restore(path,inputs):
    model=RaceNet(inputs);model.load_state_dict(load_file(str(path)));model.eval();return model

"""Independent conditional-order probability and objective checks; no optimizer."""
from itertools import permutations,combinations
import numpy as np


def conditional_probability(utilities, order):
    s=np.asarray(utilities,float)
    w=np.exp(s-s.max())
    i,j,k=order
    return float(w[i]/w.sum()*w[j]/(w[j]+w[k]))


def data_nll(weights, triples, scale=1.):
    x=np.asarray(triples,float)
    s=np.einsum('rkd,d->rk',x,np.asarray(weights,float))*scale
    # Actual order rows are sorted [first, second, third].
    terms=[]
    for u in s:
        w=np.exp(u-u.max())
        terms.append(-np.log(w[0]/w.sum())-np.log(w[1]/(w[1]+w[2])))
    return float(np.mean(terms))


def objective_gradient(weights, triples, ridge=.01):
    x=np.asarray(triples,float);coef=np.asarray(weights,float)
    s=np.einsum('rkd,d->rk',x,coef)
    w=np.exp(s-s.max(axis=1,keepdims=True))
    p=w/w.sum(axis=1,keepdims=True)
    p23=w[:,1:]/w[:,1:].sum(axis=1,keepdims=True)
    grad=np.einsum('rk,rkd->rd',p,x)-x[:,0,:]
    grad+=np.einsum('rk,rkd->rd',p23,x[:,1:,:])-x[:,1,:]
    return data_nll(coef,x)+ridge*np.dot(coef,coef)/2,grad.mean(axis=0)+ridge*coef


def scale_gradient(logscale, weights, triples):
    scale=float(np.exp(logscale));x=np.asarray(triples,float)
    base=np.einsum('rkd,d->rk',x,np.asarray(weights,float))
    s=scale*base;w=np.exp(s-s.max(axis=1,keepdims=True))
    p=w/w.sum(axis=1,keepdims=True);p23=w[:,1:]/w[:,1:].sum(axis=1,keepdims=True)
    g=(p*base).sum(axis=1)-base[:,0]+(p23*base[:,1:]).sum(axis=1)-base[:,1]
    return data_nll(weights,x,scale),float(scale*g.mean())


def joint(scores,tau,utilities):
    a=np.asarray(scores,float);n=len(a)
    sets=list(combinations(range(n),3))
    energies=np.array([sum(sorted(a[list(s)].tolist())) for s in sets])/tau
    q=np.exp(energies-energies.max());q/=q.sum()
    orders=[];probs=[]
    for members,mass in zip(sets,q):
        local=np.asarray(utilities,float)[list(members)]
        for order in permutations(range(3)):
            orders.append(tuple(members[i] for i in order))
            probs.append(float(mass*conditional_probability(local,order)))
    return np.asarray(sets),q,np.asarray(orders),np.asarray(probs)


def selfcheck():
    rng=np.random.default_rng(20261017)
    x=rng.normal(size=(17,3,10));coef=rng.normal(size=10)/5
    value,grad=objective_gradient(coef,x)
    eps=1e-6
    finite=np.array([(objective_gradient(coef+np.eye(10)[i]*eps,x)[0]-objective_gradient(coef-np.eye(10)[i]*eps,x)[0])/(2*eps) for i in range(10)])
    assert np.allclose(grad,finite,atol=1e-8,rtol=0)
    logscale=.13;v,g=scale_gradient(logscale,coef,x)
    numeric=(scale_gradient(logscale+eps,coef,x)[0]-scale_gradient(logscale-eps,coef,x)[0])/(2*eps)
    assert abs(g-numeric)<1e-8
    for n in [4,7,10,12]:
        s=rng.normal(size=n);u=rng.normal(size=n)
        sets,q,orders,p=joint(s,1.1,u)
        assert np.allclose(p.reshape(-1,6).sum(axis=1),q,atol=1e-12,rtol=0)
        assert abs(p.sum()-1)<1e-12
        m0=np.bincount(sets.ravel(),weights=np.repeat(q,3),minlength=n)
        m1=np.bincount(orders.ravel(),weights=np.repeat(p,3),minlength=n)
        assert np.allclose(m0,m1,atol=1e-12,rtol=0)
    return dict(gradient_max_error=float(abs(grad-finite).max()),scale_gradient_error=float(abs(g-numeric)),coherence=True,model_fit=False)


if __name__=='__main__':print(selfcheck())

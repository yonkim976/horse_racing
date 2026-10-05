import pytest
from passing import parse

def test_group_order_keeps_lateral_order_not_numerical_sort():
    g=parse('(10,^3,9),2-1=7≡4')
    assert g[0]['members']==[10,3,9] and g[0]['marked']==[3]
    assert [x['separator'] for x in g]==['',',','-','=','≡']

def test_uncertain_and_duplicate_rejected():
    for s in ['(1,2),2','1 ·(2,3)','(1,2','(1,,2)','1abc2','0,1','1(2,3)']:
        with pytest.raises(ValueError):parse(s)

def test_race_fixed_effect_invariance():
    import numpy as np
    import pandas as pd
    from analyze import cluster_fit
    n=30;g=pd.DataFrame({'race_id':np.repeat(np.arange(n),6),'race_date':np.repeat(pd.date_range('2020-01-01',periods=n),6)})
    x=np.tile([0,0,0,1,1,1],n).astype(float)[:,None]
    y=.2*x[:,0]+np.repeat(np.arange(n)*.1,6)
    b,V,G,rank=cluster_fit(g,x,y)
    assert abs(b[0]-.2)<1e-10
    b2,_,_,_=cluster_fit(g,x,y+np.repeat(np.arange(n)**2,6))
    assert abs(b2[0]-b[0])<1e-10

def test_fdr_monotone():
    import numpy as np
    from analyze import bh
    p=np.array([.04,.001,.2,.03]);q=bh(p)
    assert np.all(q>=p) and np.all(np.diff(q[np.argsort(p)])>=-1e-12)

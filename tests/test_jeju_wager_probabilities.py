import numpy as np
import pytest
from horse_racing.analysis.jeju_wager_probabilities import markets,portfolio,ticket_hits,unit_expected_net


@pytest.mark.parametrize('n',[7,8,10])
def test_market_normalization_and_place_rule(n):
    v=markets([str(i) for i in range(n)],np.zeros(n),np.zeros(n))
    totals={k:sum(x['probability'] for x in rows) for k,rows in v['markets'].items()}
    for k in ['WIN','QNL','EXA','TLA','TRI']: assert totals[k]==pytest.approx(1)
    assert totals['PLC']==pytest.approx(2 if n==7 else 3)
    assert totals['QPL']==pytest.approx(3)
    assert v['markets']['QPL'][0]['probability']==pytest.approx(6/(n*(n-1)))


def test_overlapping_tickets_union_not_probability_sum():
    v=markets(list('abcdefgh'),np.zeros(8),np.zeros(8))
    p=portfolio(v,'PLC',8)
    assert p['any_hit_probability']==pytest.approx(1)
    assert p['expected_winning_tickets']==pytest.approx(3)
    assert portfolio(v,'TLA',6,anchor='a')['any_hit_probability']<=v['top3'][0]
    assert ticket_hits('PLC',('c',),tuple('abc'),8)
    assert not ticket_hits('PLC',('c',),tuple('abc'),7)


def test_joint_marginal_consistency_and_value():
    v=markets(list('abcdef'),np.arange(6)*.2,-np.arange(6)*.1)
    for i,h in enumerate(v['ids']):
        total=sum(r['probability'] for r in v['markets']['TLA'] if h in r['selection'])
        assert total==pytest.approx(v['top3'][i])
    assert unit_expected_net(.25,5)==pytest.approx(.25)
    assert unit_expected_net(.5,1.5)==pytest.approx(-.25)

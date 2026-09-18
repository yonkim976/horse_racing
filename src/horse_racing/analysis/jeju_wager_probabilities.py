"""Seven market views of one coherent ordered-podium distribution.

Research probabilities only: settlement with dead heats, refunds, and prices
needs a separate contract. No independent multiplication of place marginals.
"""
from itertools import combinations

import numpy as np

from horse_racing.analysis.jeju_hybrid_evaluation import distribution


def markets(ids, set_scores, order_scores, beta_set=1., beta_order=1.):
    ids = list(ids)
    if len(ids) != len(set(ids)) or len(ids)<3:
        raise ValueError('Unique horse ids, at least three, required')
    sets, orders, ls, lo, top3 = distribution(set_scores, order_scores, beta_set, beta_order)
    joint = np.exp(lo)
    n = len(ids)
    result = {}
    def add(name, selections, masks):
        result[name] = [dict(selection=tuple(ids[i] for i in s),
                            probability=float(joint[mask].sum()), outcome_mask=mask)
                        for s,mask in zip(selections,masks,strict=True)]
    singles = [(i,) for i in range(n)]
    add('WIN', singles, [orders[:,0]==i for i in range(n)])
    place_slots = 2 if n<=7 else 3
    add('PLC', singles, [np.any(orders[:,:place_slots]==i,axis=1) for i in range(n)])
    pairs = list(combinations(range(n),2))
    add('QNL', pairs, [np.isin(orders[:,:2],s).all(axis=1) for s in pairs])
    exact = [(i,j) for i in range(n) for j in range(n) if i!=j]
    add('EXA', exact, [(orders[:,:2]==s).all(axis=1) for s in exact])
    add('QPL', pairs, [np.isin(orders,s).sum(axis=1)==2 for s in pairs])
    add('TLA', list(map(tuple,sets)), [np.isin(orders,s).all(axis=1) for s in sets])
    # Ordered outcomes are unique; storing masks only for small candidate sets
    # avoids materializing the full N^6 identity matrix.
    result['TRI'] = [dict(selection=tuple(ids[i] for i in s), probability=float(p),
                          outcome_index=i) for i,(s,p) in enumerate(zip(orders,joint,strict=True))]
    for rows in result.values():
        rows.sort(key=lambda r:(-r['probability'],r['selection']))
    return dict(markets=result, joint=joint, orders=orders, top3=top3, ids=ids, place_slots=place_slots)


def portfolio(view, market, count, anchor=None):
    if count<1:
        raise ValueError('Positive ticket count required')
    rows = view['markets'][market]
    if anchor is not None:
        rows = [r for r in rows if anchor in r['selection']]
    chosen = rows[:count]
    covered = np.zeros(len(view['joint']),dtype=bool)
    for row in chosen:
        if 'outcome_mask' in row:
            covered |= row['outcome_mask']
        else:
            covered[row['outcome_index']] = True
    return dict(tickets=[r['selection'] for r in chosen], ticket_count=len(chosen),
                any_hit_probability=float(view['joint'][covered].sum()),
                expected_winning_tickets=float(sum(r['probability'] for r in chosen)),
                equal_total_budget_weight=1/len(chosen) if chosen else None)


def ticket_hits(market, ticket, actual_order, n):
    top = tuple(actual_order)
    if market=='WIN': return ticket[0]==top[0]
    if market=='PLC': return ticket[0] in top[:2 if n<=7 else 3]
    if market=='EXA': return tuple(ticket)==top[:2]
    if market=='QNL': return set(ticket)==set(top[:2])
    if market=='QPL': return set(ticket)<=set(top)
    if market=='TLA': return set(ticket)==set(top)
    if market=='TRI': return tuple(ticket)==top
    raise ValueError(market)


def unit_expected_net(probability, gross_decimal_odds):
    """Before tax; odds must include returned stake, use contemporaneous price."""
    if not 0<=probability<=1 or not np.isfinite(gross_decimal_odds) or gross_decimal_odds<=0:
        raise ValueError('Invalid probability or gross return multiplier')
    return probability*gross_decimal_odds-1

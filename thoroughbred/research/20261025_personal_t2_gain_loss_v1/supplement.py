"""Accounting decompositions and symmetric cohort sensitivity, no new selection."""
import pandas as pd
import analyze as a


def main():
    d=pd.read_parquet(a.OUT/'race_diagnostics.parquet')
    s=pd.read_csv(a.OUT/'condition_summary.csv')
    n=s[s.dimension.eq('all')].set_index('period').races
    q=s[s.dimension.isin(['venue','distance','grade_label','predicted_pace','observed_pace'])].copy()
    q['annual_contribution_pp']=q.delta_return/q.period.map(n)/6000*100
    q.to_csv(a.OUT/'annual_contributions.csv',index=False)
    tails=[];drop=[];patterns=[];ratios=[]
    for period in ['all',2024,2025,2026]:
        g=d if period=='all' else d[d.year.eq(period)]
        c=g[g.transition.isin(['gained','lost'])]
        ga=c[c.transition.eq('gained')];lo=c[c.transition.eq('lost')]
        ratios.append(dict(period=period,new_races=len(ga),lost_races=len(lo),
            count_ratio=len(ga)/len(lo),breakeven_count_ratio=lo.dividend.mean()/ga.dividend.mean(),
            new_mean=ga.dividend.mean(),lost_mean=lo.dividend.mean(),
            exact_delta_return=int(ga.payout.sum()-lo.payout.sum())))
        for threshold in [50,100]:
            for label,part in [('below',c[c.dividend.lt(threshold)]),('at_least',c[c.dividend.ge(threshold)])]:
                pg=part[part.transition.eq('gained')];pl=part[part.transition.eq('lost')]
                tails.append(dict(period=period,threshold=threshold,band=label,new_races=len(pg),lost_races=len(pl),
                    new_return=int(pg.payout.sum()),lost_return=int(pl.payout.sum()),
                    delta_return=int(pg.payout.sum()-pl.payout.sum()),
                    annual_contribution_pp=(pg.payout.sum()-pl.payout.sum())/(len(g)*6000)*100))
        for label,removed in [('none',set()),('largest_new',set(ga.nlargest(1,'payout').race_key)),
                             ('largest_lost',set(lo.nlargest(1,'payout').race_key)),
                             ('largest_each',set(ga.nlargest(1,'payout').race_key)|set(lo.nlargest(1,'payout').race_key))]:
            z=g[~g.race_key.isin(removed)]
            drop.append(dict(period=period,removed=label,removed_races=len(removed),races=len(z),
                old_return=int(z.old_return.sum()),new_return=int(z.new_return.sum()),stake=len(z)*6000,
                delta_return=int(z.delta_return.sum()),delta_roi_pp=z.delta_return.sum()/(len(z)*6000)*100))
        for (transition,pattern),z in c.groupby(['transition','podium_model_ranks']):
            patterns.append(dict(period=period,transition=transition,podium_model_ranks=pattern,
                races=len(z),mean_dividend=z.dividend.mean(),payout=int(z.payout.sum())))
    pd.DataFrame(tails).to_csv(a.OUT/'tail_decomposition.csv',index=False)
    pd.DataFrame(drop).to_csv(a.OUT/'cohort_sensitivity.csv',index=False)
    pd.DataFrame(patterns).to_csv(a.OUT/'rank_pattern_summary.csv',index=False)
    pd.DataFrame(ratios).to_csv(a.OUT/'count_price_balance.csv',index=False)
    print(pd.DataFrame(drop).to_string(index=False))


if __name__=='__main__':main()

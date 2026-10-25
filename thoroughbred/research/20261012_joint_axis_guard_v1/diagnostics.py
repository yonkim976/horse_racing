"""Describe fixed rejection stages; never select or change a policy from results."""
import numpy as np
import pandas as pd
import run as e


def main():
    e.check();d=pd.read_parquet(e.OUT/'decisions.parquet');d=d[d.proposed_switch].copy()
    d['first_rejection']=np.select([
        d.new_keep_fast_g3.isna()|d.new_keep_fast_g1.isna(),
        d.new_keep_fast_g3.lt(0)&d.new_keep_fast_g1.lt(0),d.new_keep_fast_g3.lt(0),d.new_keep_fast_g1.lt(0),
        ~d.support_pass,~d.recent_count_pass,~d.recent_record_pass],
        ['joint_missing','both_negative','g3_negative_only','g1_negative_only',
         'support_under2','recent_count_under2','recent_record_worse'],default='accepted')
    assert d.first_rejection.eq('accepted').equals(~d.joint_recent_blocked)
    rows=[]
    for period,z in e.windows(d):
        for reason,g in z.groupby('first_rejection'):
            n=g.original_switch_net
            rows.append(dict(period=period,reason=reason,races=len(g),
                original_gain=int(n.eq(1).sum()),original_loss=int(n.eq(-1).sum()),
                both_hit=int((g.old_hit.eq(1)&g.new_hit.eq(1)).sum()),
                both_miss=int((g.old_hit.eq(0)&g.new_hit.eq(0)).sum()),
                change_net_if_blocked=int(-n.sum())))
    pd.DataFrame(rows).to_csv(e.OUT/'rejection_reasons.csv',index=False)
    rows=[]
    for period,z in e.windows(d):
        stages=[('joint',~z.joint_pass),('support_added',z.joint_pass&~z.support_pass),
                ('recent_added',z.joint_pass&z.support_pass&~z.recent_pass)]
        assert sum(int(mask.sum())for _,mask in stages)==int(z.joint_recent_blocked.sum())
        for stage,mask in stages:
            g=z[mask];n=g.original_switch_net
            rows.append(dict(period=period,stage=stage,races=len(g),
                             recovered=int(n.eq(-1).sum()),sacrificed=int(n.eq(1).sum()),net=int(-n.sum())))
    pd.DataFrame(rows).to_csv(e.OUT/'stage_changes.csv',index=False)
    e.check();print('Rejection stages verified; policy unchanged')


if __name__=='__main__':main()

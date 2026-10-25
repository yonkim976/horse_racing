"""Describe selected low-support/negative-G1 cases without changing the policy."""
import pandas as pd
import run as e


def main():
    e.check();d=pd.read_parquet(e.OUT/'pair_frame.parquet');p=pd.read_parquet(e.OUT/'selector_predictions.parquet')
    z=p.merge(d.drop(columns=['race_date','year','switched','old_program_no','old_horse_id','new_program_no','new_horse_id']),on='race_key',validate='many_to_one')
    z=z[z.switched].copy()
    z['strict_joint_pass']=z.new_keep_fast_g3.ge(0)&z.new_keep_fast_g1.ge(0)&z.new_keep_fast_n.ge(2)
    z['strict_recent_pass']=z.old_profile_count3.ge(2)&z.new_profile_count3.ge(2)&z.new_moist_last3_record_index_mean.ge(z.old_moist_last3_record_index_mean)
    z['strict_accept']=z.strict_joint_pass&z.strict_recent_pass
    rows=[]
    for variant,a in z.groupby('variant'):
        for period,b in e.windows(a):
            categories={
                'g1_negative':b.new_keep_fast_g1.lt(0),
                'paired_support_under2':b.new_keep_fast_n.lt(2),
                'paired_g1_missing':b.new_keep_fast_g1.isna(),
                'recent_record_worse':b.new_moist_last3_record_index_mean.lt(b.old_moist_last3_record_index_mean),
                'strict_confirmation_would_reject':~b.strict_accept}
            for condition,mask in categories.items():
                q=b[mask];selected=q[q.choose_new];label=selected.switch_outcome
                rows.append(dict(variant=variant,period=period,condition=condition,cases=len(q),
                    selected_new=len(selected),new_gain=int(label.eq(1).sum()),new_loss=int(label.eq(-1).sum()),
                    neutral=int(label.eq(0).sum()),net_new_vs_old=int(label.sum())))
    pd.DataFrame(rows).to_csv(e.OUT/'no_hard_filter_cases.csv',index=False)
    # The old fixed-policy result is a comparator only; not part of learner input.
    strict=z[z.variant.eq('joint_logit')].copy()
    strict['strict_hit']=strict.new_outcome.between(1,3).where(strict.strict_accept,strict.old_outcome.between(1,3))
    strict['learned_hit']=strict.new_outcome.between(1,3).where(strict.choose_new,strict.old_outcome.between(1,3))
    rows=[]
    for period,b in e.windows(strict):
        delta=b.learned_hit.astype(int)-b.strict_hit.astype(int)
        rows.append(dict(period=period,cases=len(b),recovered=int(delta.eq(1).sum()),sacrificed=int(delta.eq(-1).sum()),net=int(delta.sum())))
    pd.DataFrame(rows).to_csv(e.OUT/'comparison_to_fixed_guard.csv',index=False)
    e.check();print('Diagnostic comparisons saved; learned policy unchanged')


if __name__=='__main__':main()

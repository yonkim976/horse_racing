"""Past-only style cohorts and observed position changes, without model fitting."""
from pathlib import Path
import hashlib,json,math
import numpy as np,pandas as pd
from scipy.stats import t,false_discovery_control
H=Path(__file__).resolve().parent;R=H.parent;ROOT=H.parents[2];O=H/'outputs';P=R/'20261008_field_pace_prediction';D=R/'20261008_bilateral_field_pace'
TARGETS=['p_s1f','p_g3f','p_g1f','finish_p','gain_middle','gain_400','gain_200','gain_late','middle_surge','late_surge','last200_surge','recovery','recovery_when_back600','late_any','last200_any','top3','top5','fade','late_cond_adv','last600_adv','late_cond_fast','recovery_and_fast200','fast200_given_recovery','recovery_and_top3','nonfinish']
COHORTS=['all','past_lead','past_fore_strict','past_front','past_back','past_rear_strict','back_repeat','back_low','back_unknown']
NAMES={'all':'전체','past_lead':'과거 선행형','past_fore_strict':'과거 선입형(엄격)','past_front':'과거 앞선권형','past_back':'과거 뒤쪽형','past_rear_strict':'과거 후미형(엄격)','back_repeat':'뒤쪽 반복회복 후보','back_low':'뒤쪽 회복반복 부족','back_unknown':'뒤쪽 회복이력 부족'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def event(valid,value):return np.where(valid,np.asarray(value,float),np.nan)
def score_ci(g,score,est):
    vars=[];ns=[]
    for ids in [g.horse_id.astype(str),g.date.dt.strftime('%Y-%m-%d'),g.horse_id.astype(str)+':'+g.date.dt.strftime('%Y-%m-%d')]:
        codes=pd.factorize(ids)[0];n=int(codes.max()+1);s=np.bincount(codes,weights=score);vars.append(float(s@s)*n/(n-1) if n>1 else np.nan);ns.append(n)
    if min(ns[:2])<2:return dict(estimate=float(est),se=np.nan,lower=np.nan,upper=np.nan,p=np.nan,df=np.nan)
    se=math.sqrt(max(0,vars[0],vars[1],vars[0]+vars[1]-vars[2]));df=min(ns[:2])-1;c=t.ppf(.975,df);p=float(2*t.sf(abs(est/se),df)) if se else float(est==0)
    return dict(estimate=float(est),se=se,lower=est-c*se,upper=est+c*se,p=p,df=df)
def ci(g,target):
    g=g[g[target].notna()];v=g[target].to_numpy();return score_ci(g,(v-v.mean())/len(v),v.mean()) if len(v) else dict(estimate=np.nan,se=np.nan,lower=np.nan,upper=np.nan,p=np.nan,df=np.nan)
def prepare():
    q=pd.read_parquet(P/'outputs/feature_context.parquet').sort_values(['horse_id','date']).reset_index(drop=True)
    keep=['row_key','source_key','horse_id','horse_name','meet','date','year','distance_m','grade_bucket','grade_normalized','gate','field_size','source_file','source_item_index','role4','group_mean_relative','group_observed','s1f','s1f_complete','g3f','g3f_complete','g1f','g1f_complete','raw_finish_rank','finish_p','normal_outcome','supported5','valid_position5','slots5','fresh_slots5','history_last','history_oldest5','count5_0','count5_1','count5_2','count5_3','recovery','fade','last600','late','middle1','middle2','early','finish','last600_adv','late_cond_adv','finish_p_mean5','early_adv_mean5','field_gap_early_adv_mean5','field_strong_front_other','gate_relative','moisture','rating','age_current']
    d=q[keep].copy();d['p_s1f']=np.where(d.s1f_complete,(d.s1f-1)/(d.field_size-1),np.nan);d['p_g3f']=np.where(d.g3f_complete,(d.g3f-1)/(d.field_size-1),np.nan);d['p_g1f']=np.where(d.g1f_complete,(d.g1f-1)/(d.field_size-1),np.nan)
    for name,a,b in [('middle','p_s1f','p_g3f'),('400','p_g3f','p_g1f'),('200','p_g1f','finish_p'),('late','p_g3f','finish_p')]:d['gain_'+name]=d[a]-d[b]
    for name,gain in [('middle_surge','gain_middle'),('late_surge','gain_late'),('last200_surge','gain_200')]:d[name]=event(d[gain].notna(),d[gain].ge(.25))
    d['late_any']=event(d.gain_late.notna(),d.gain_late.gt(1e-12));d['last200_any']=event(d.gain_200.notna(),d.gain_200.gt(1e-12));d['top3']=event(d.normal_outcome,d.raw_finish_rank.le(3));d['top5']=event(d.normal_outcome,d.raw_finish_rank.le(5));d['nonfinish']=(~d.normal_outcome).astype(float)
    d['late_cond_fast']=event(d.late_cond_adv.notna(),d.late_cond_adv.gt(0));d['recovery_and_fast200']=event(d.recovery.notna()&d.late_cond_adv.notna(),d.recovery.eq(1)&d.late_cond_adv.gt(0))
    d['recovery_when_back600']=event(d.p_g3f.ge(.5)&d.recovery.notna(),d.recovery.eq(1));d['fast200_given_recovery']=event(d.recovery.eq(1)&d.late_cond_adv.notna(),d.late_cond_adv.gt(0));d['recovery_and_top3']=event(d.recovery.notna()&d.top3.notna(),d.recovery.eq(1)&d.top3.eq(1));d['path_complete']=d[['p_s1f','p_g3f','p_g1f','finish_p']].notna().all(axis=1)
    # Histories use the preceding actual roster slots; invalid slots are retained.
    dates=d.date.to_numpy('datetime64[D]').astype('int64');horses=d.horse_id.to_numpy();ix=np.arange(len(d));names=['recovery','gain_middle','gain_late','gain_200','recovery_and_fast200'];counts={c:np.zeros(len(d)) for c in names};sums={c:np.zeros(len(d)) for c in names}
    for lag in range(1,6):
        prev=np.maximum(0,ix-lag);fresh=(ix>=lag)&(horses==horses[prev])&(dates-dates[prev]>=2)&(dates-dates[prev]<=730)
        for col in names:
            v=d[col].to_numpy()[prev];ok=fresh&np.isfinite(v);counts[col]+=ok;sums[col]+=np.where(ok,v,0)
    for col in names:d['past_'+col+'_n5']=counts[col];d['past_'+col+'_mean5']=np.divide(sums[col],counts[col],out=np.full(len(d),np.nan),where=counts[col]>0)
    d['past_recovery_count5']=sums['recovery'];assert np.allclose(d.past_recovery_n5,q.recovery_n5);assert np.allclose(d.past_recovery_mean5,q.recovery_mean5,equal_nan=True)
    d['lead_profile']=d.supported5&d.count5_0.ge(3);d['fore_strict_profile']=d.supported5&d.count5_1.ge(3);d['front_profile']=d.supported5&(d.count5_0+d.count5_1).ge(3)&~d.lead_profile;d['back_profile']=d.supported5&(d.count5_2+d.count5_3).ge(3);d['rear_strict_profile']=d.supported5&d.count5_3.ge(3)
    d['closer_candidate']=d.back_profile&d.past_recovery_n5.eq(5)&d.past_recovery_count5.ge(2);d['back_low_recovery']=d.back_profile&d.past_recovery_n5.eq(5)&d.past_recovery_count5.lt(2);d['back_unknown_recovery']=d.back_profile&~d.past_recovery_n5.eq(5)
    d['lead_realization']=np.select([d.role4.eq(0),d.role4.eq(1),d.role4.ge(2)],['선행유지','선입이동','중단후미밀림'],default='초반미관측');d['front_realization']=np.select([d.role4.between(0,1),d.role4.ge(2)],['앞선확보','중단후미밀림'],default='초반미관측')
    d['size_band']=np.where(d.field_size.le(9),'<=9',np.where(d.field_size.le(11),'10~11','>=12'));d['past_finish_band']=pd.cut(d.finish_p_mean5,[-.01,1/3,2/3,1.01],labels=['좋음','중간','낮음']).astype(object).fillna('미관측')
    d.to_parquet(O/'trajectory_rows.parquet',index=False)
    cases=pd.read_csv(D/'outputs/example_cards.csv');d[d.source_key.isin(cases.source_key)].sort_values(['source_key','gate']).to_csv(O/'fixed_example_trajectories.csv',index=False)
    paths=[P/'outputs/feature_context.parquet',R/'20261008_running_style_foundation/outputs/observed_styles.parquet',D/'outputs/example_cards.csv',P/'outputs/source_audit.json']
    raw=json.loads((P/'outputs/source_audit.json').read_text())['inputs'];raw=[r for r in raw if r['path'].endswith('.json.gz')]
    audit=dict(n=len(d),races=d.source_key.nunique(),horses=d.horse_id.nunique(),data_end_by_meet={k:str(v.date()) for k,v in d.groupby('meet').date.max().items()},inputs=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha(p)) for p in paths]+raw,uses_track_speed=False,current_outcomes_used_for_past_profiles=False,models_trained=0)
    dump(O/'source_audit.json',audit);return d
def cohort_masks(d):
    return dict(zip(COHORTS,[np.ones(len(d),bool),d.lead_profile,d.fore_strict_profile,d.front_profile,d.back_profile,d.rear_strict_profile,d.closer_candidate,d.back_low_recovery,d.back_unknown_recovery]))
def windows(d):
    yield '2024_2025',d[d.year.between(2024,2025)]
    yield '2026_partial',d[d.year.eq(2026)]
    yield '2018_2023',d[d.year.le(2023)]
    yield '2018_2026',d
def strata(d,details=True):
    yield 'all','all',d
    for meet,g in d.groupby('meet'):yield 'meet',meet,g
    if details:
        for (meet,dist),g in d.groupby(['meet','distance_m']):yield 'meet_distance',f'{meet}|{dist}',g
def summarize(g):
    row=dict(n=len(g),races=g.source_key.nunique(),horses=g.horse_id.nunique(),dates=g.date.nunique(),small_sample=g.source_key.nunique()<30 or g.date.nunique()<10)
    for col in TARGETS:row[col+'_n']=int(g[col].notna().sum());row[col+'_mean']=float(g[col].mean())
    for col in ['recovery','top3']:
        z=ci(g,col);row[col+'_lower']=z['lower'];row[col+'_upper']=z['upper']
    return row
def metrics(d):
    rows=[];flows=[];coverage=[];sensitivity=[];paths=[]
    for window,full in windows(d):
        for scope,label,g in strata(full,details=window in ['2024_2025','2026_partial']):
            coverage.append(dict(window=window,scope=scope,label=label,n=len(g),races=g.source_key.nunique(),s1f_n=int(g.p_s1f.notna().sum()),g3f_n=int(g.p_g3f.notna().sum()),g1f_n=int(g.p_g1f.notna().sum()),finish_n=int(g.finish_p.notna().sum()),supported5_n=int(g.supported5.sum()),past_recovery5_n=int(g.past_recovery_n5.eq(5).sum())))
            for code,mask in cohort_masks(g).items():
                z=g[mask]
                if len(z):
                    rows.append(dict(window=window,scope=scope,label=label,cohort=code,cohort_name=NAMES[code])|summarize(z))
                    same=z[z.path_complete]
                    if len(same):paths.append(dict(window=window,scope=scope,label=label,cohort=code,cohort_name=NAMES[code],n=len(same),p_s1f_mean=float(same.p_s1f.mean()),p_g3f_mean=float(same.p_g3f.mean()),p_g1f_mean=float(same.p_g1f.mean()),finish_p_mean=float(same.finish_p.mean()),gain_middle_mean=float(same.gain_middle.mean()),gain_400_mean=float(same.gain_400.mean()),gain_200_mean=float(same.gain_200.mean())))
            for cohort,mask,col in [('past_lead',g.lead_profile,'lead_realization'),('past_front',g.front_profile,'front_realization'),('past_fore_strict',g.fore_strict_profile,'front_realization')]:
                for status,z in g[mask].groupby(col):flows.append(dict(window=window,scope=scope,label=label,cohort=cohort,cohort_name=NAMES[cohort],status=status)|summarize(z))
        for threshold in [1,2,3]:
            g=full[full.back_profile&full.past_recovery_n5.eq(5)]
            for flag,z in g.groupby(g.past_recovery_count5.ge(threshold)):
                sensitivity.append(dict(window=window,threshold=threshold,repeat_candidate=bool(flag))|summarize(z))
    pd.DataFrame(rows).to_csv(O/'cohort_metrics.csv',index=False);pd.DataFrame(flows).to_csv(O/'front_realization_metrics.csv',index=False);pd.DataFrame(coverage).to_csv(O/'coverage.csv',index=False);pd.DataFrame(sensitivity).to_csv(O/'recovery_threshold_sensitivity.csv',index=False)
    pd.DataFrame(paths).to_csv(O/'common_path_metrics.csv',index=False)
    trans=[]
    main=d[d.year.between(2024,2025)]
    for scope,label,g in strata(main):
        for cohort,mask in [('all',np.ones(len(g),bool)),('past_back',g.back_profile),('back_repeat',g.closer_candidate),('past_lead',g.lead_profile),('past_front',g.front_profile)]:
            for a,b in [('p_s1f','p_g3f'),('p_g3f','p_g1f'),('p_g1f','finish_p')]:
                z=g[mask&g[a].notna()&g[b].notna()].copy()
                z['from_band']=np.where(z[a].le(1/3),0,np.where(z[a].le(2/3),1,2));z['to_band']=np.where(z[b].le(1/3),0,np.where(z[b].le(2/3),1,2))
                for (fa,ta),ng in z.groupby(['from_band','to_band']):trans.append(dict(scope=scope,label=label,cohort=cohort,stage=a+'->'+b,from_band=fa,to_band=ta,n=len(ng)))
    pd.DataFrame(trans).to_csv(O/'position_transition_counts.csv',index=False)
def matched(g,col,a,b,keys,target,min_n,min_races):
    g=g[g[col].isin([a,b])&g[target].notna()].copy();g['cell']=g[keys].astype(str).agg('|'.join,axis=1);cells=[]
    for key,z in g.groupby('cell'):
        ga=z[z[col].eq(a)];gb=z[z[col].eq(b)];na=len(ga);nb=len(gb)
        if min(na,nb)<min_n or min(ga.source_key.nunique(),gb.source_key.nunique())<min_races:continue
        w=na*nb/(na+nb);cells.append(dict(cell=key,n_a=na,n_b=nb,mean_a=float(ga[target].mean()),mean_b=float(gb[target].mean()),weight=w))
    if not cells:return None,[]
    z=g[g.cell.isin([c['cell'] for c in cells])].copy();tot=sum(c['weight'] for c in cells);ma=sum(c['weight']*c['mean_a'] for c in cells)/tot;mb=sum(c['weight']*c['mean_b'] for c in cells)/tot;score=pd.Series(0.,index=z.index)
    for c in cells:
        mask=z.cell.eq(c['cell']);isa=z[col].eq(a);score.loc[mask&isa]=c['weight']/tot/c['n_a']*(z.loc[mask&isa,target]-ma);score.loc[mask&~isa]=-c['weight']/tot/c['n_b']*(z.loc[mask&~isa,target]-mb)
    r=dict(target=target,cell_columns='|'.join(keys),cells=len(cells),n_a=int(z[col].eq(a).sum()),n_b=int(z[col].eq(b).sum()),horses=z.horse_id.nunique(),dates=z.date.nunique(),races=z.source_key.nunique(),coverage=float(len(z)/len(g)),mean_a=ma,mean_b=mb)|score_ci(z,score.to_numpy(),ma-mb)
    return r,cells
def comparisons(d):
    rows=[];cells=[];raw=[]
    for window,full in windows(d):
        if window not in ['2024_2025','2026_partial']:continue
        for scope,label,g in strata(full):
            z=g[g.closer_candidate|g.back_low_recovery];a=z[z.closer_candidate&z.recovery.notna()];b=z[z.back_low_recovery&z.recovery.notna()]
            if len(a) and len(b):
                gg=pd.concat([a,b]);ma=a.recovery.mean();mb=b.recovery.mean();score=np.r_[(a.recovery.to_numpy()-ma)/len(a),-(b.recovery.to_numpy()-mb)/len(b)];raw.append(dict(window=window,scope=scope,label=label,n_a=len(a),n_b=len(b),mean_a=float(ma),mean_b=float(mb))|score_ci(gg,score,ma-mb))
        close=full[full.closer_candidate|full.back_low_recovery].copy();close['repeat']=np.where(close.closer_candidate,'repeat','low')
        keys=['meet','distance_m','year','grade_bucket','size_band','past_finish_band']
        r,cs=matched(close,'repeat','repeat','low',keys,'recovery',10,2)
        if r:
            rows.append(dict(window=window,comparison='repeat-low',a='repeat',b='low',cohort='past_back',exposure='repeat')|r)
            cells += [dict(window=window,comparison='repeat-low',target='recovery')|c for c in cs]
        specs=[('past_lead','lead_profile','lead_realization','선입이동','선행유지'),('past_lead','lead_profile','lead_realization','중단후미밀림','선행유지'),('past_front','front_profile','front_realization','중단후미밀림','앞선확보')]
        for cohort,mask,col,a,b in specs:
            for target in ['top3','finish_p']:
                r,cs=matched(full[full[mask]],col,a,b,['horse_id','meet','distance_m','grade_bucket'],target,1,1)
                if r:
                    name=cohort+':'+a+'-'+b;rows.append(dict(window=window,comparison=name,a=a,b=b,cohort=cohort,exposure=col)|r);cells +=[dict(window=window,comparison=name,target=target)|c for c in cs]
    co=pd.DataFrame(rows)
    for window,g in co.groupby('window'):
        for family,ix in [('closer',g[g.target.eq('recovery')].index),('front_finish',g[~g.target.eq('recovery')].index)]:
            valid=co.loc[ix].p.notna();idx=co.loc[ix][valid].index;co.loc[idx,'bh_q']=false_discovery_control(co.loc[idx,'p']);co.loc[idx,'bh_family']=family
    rr=pd.DataFrame(raw)
    for window,g in rr.groupby('window'):
        for family,gg in [('overall',g[g.scope.eq('all')]),('distance_exploratory',g[g.scope.eq('meet_distance')])]:
            ix=gg[gg.p.notna()].index
            if len(ix):rr.loc[ix,'bh_q']=false_discovery_control(rr.loc[ix,'p']);rr.loc[ix,'bh_family']=family
    co.to_csv(O/'matched_comparisons.csv',index=False);pd.DataFrame(cells).to_csv(O/'matched_cells.csv',index=False);rr.to_csv(O/'closer_repetition_comparisons.csv',index=False)
def horse_summary(d):
    main=d[d.year.between(2024,2025)];rows=[]
    for (horse,meet),g in main.groupby(['horse_id','meet']):
        close=g[g.closer_candidate];lead=g[g.lead_profile];fore=g[g.front_profile]
        if not(len(close) or len(lead) or len(fore)):continue
        rows.append(dict(horse_id=horse,horse_name=g.sort_values('date').horse_name.iloc[-1],meet=meet,period='2024~2025',n=len(g),closer_candidate_n=len(close),closer_observed_n=int(close.recovery.notna().sum()),closer_actual_recoveries=int(close.recovery.eq(1).sum()),closer_recovery_rate=float(close.recovery.mean()),lead_profile_n=len(lead),lead_observed_n=int(lead.role4.ge(0).sum()),lead_kept=int(lead.role4.eq(0).sum()),lead_fell_to_fore=int(lead.role4.eq(1).sum()),lead_missed_front=int(lead.role4.ge(2).sum()),front_profile_n=len(fore),front_missed=int(fore.role4.ge(2).sum())))
    pd.DataFrame(rows).to_csv(O/'horse_observed_summary.csv',index=False)
def main():
    assert not (O/'trajectory_rows.parquet').exists(),'Preserve completed output';d=prepare();metrics(d);comparisons(d);horse_summary(d);print('Completed middle/late observed study',len(d),flush=True)
if __name__=='__main__':main()

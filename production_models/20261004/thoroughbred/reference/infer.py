"""Selected v6 probabilities for the preserved complete September 19/20 card."""
import json
import numpy as np
import pandas as pd
import core
from run_study import OUT,V2,V3,V4,V5,read,dump
from infer_targets import validate_frame,IDENTITY,key

def main():
    assert json.loads((OUT/'verification.json').read_text())['passed']
    dest=OUT/'future_predictions_20260919_20'
    if dest.exists():raise FileExistsError(dest)
    chosen={t:v['selected'] for t,v in json.loads((OUT/'selection.json').read_text())['by_target'].items()}
    f=read(V3/'prediction_input/future_20260919_20_context.parquet');x=read(V4/'future_predictions_20260919_20/prepared_v4_features.parquet');keys=['race_id','hr_no','race_date'];x=x[keys+[c for c in x if c.startswith('research_v4_')]]
    f=f.merge(x,on=keys,validate='one_to_one').sort_values(['race_date','race_id','chul_no','hr_no']).reset_index(drop=True);assert len(f)==294 and f.race_id.nunique()==27
    status=validate_frame(f,False);tc=core.tc;win=tc.load_v2_win_bundle(V2/'models/2026/H3_relative');bm=tc.load_bundle(V4/'models/2026/top3_growth_strength');am=tc.load_bundle(V5/'windows/models/2026H2/rolling_all')
    ws=tc.raw_scores(win,f)['win'];wp=tc.raw_scores(win,f,num_iteration=100)['win'];bs=tc.raw_scores(bm,f)['top3'];bp=tc.raw_scores(bm,f,num_iteration=60)['top3'];aas=tc.raw_scores(am,f)['top3'];wt=win.metadata['temperature_by_venue'];bt=bm.metadata['temperature_by_target_and_venue'];at=am.metadata['temperature_by_target_and_venue']['A']
    ap=json.loads((OUT/'models/2026H2/context_temperature.json').read_text());bpar=None if chosen['B']=='current_B' else json.loads((OUT/f'models/2026/{chosen["B"]}.json').read_text())
    aa=[];jj=[];maxerr=0.
    for rid,idx in f.groupby('race_id',sort=False).indices.items():
        card=f.iloc[idx];v=card.venue_code.iloc[0];horses=card.hr_no.astype(str).to_numpy();t=at.get(v,at['GLOBAL'])
        if chosen['A']=='context_temperature':t=core.contextual_temperature(aas[idx],t,np.array(ap['coefficients']),v)
        ja=tc.top3_set_joint(aas[idx],ws[idx],t,wt.get(v,1.));rank=np.argsort(np.argsort(-ja.inclusion_probability,kind='stable'))+1
        for i,(_,r) in enumerate(card.iterrows()):aa.append({**{c:r[c] for c in IDENTITY},'feature_cutoff':r.feature_cutoff,'A_slot_inclusion_probability':float(ja.inclusion_probability[i]),'pred_rank':int(rank[i]),'candidate':chosen['A'],'temperature':t,'model_version':OUT.name,'inference_status':status})
        if bpar is None:jb=tc.top3_set_joint(bs[idx],ws[idx],bt['B'].get(v,bt['B']['GLOBAL']),wt.get(v,1.))
        else:
            r=core.prepare_race(card,bp[idx],wp[idx],chosen['B']);temps=bpar['temperature_by_venue'];jb=core.joint(r,np.array(bpar['coefficients']),temps.get(v,temps['GLOBAL']),wt.get(v,1.))
        jc=tc.top3_set_joint(bs[idx],ws[idx],bt['C'].get(v,bt['C']['GLOBAL']),wt.get(v,1.))
        for target,j in [('A',ja),('B',jb),('C',jc)]:
            maxerr=max(maxerr,*tc.probability_invariants(j).values())
            if target=='A':continue
            p=j.set_probability if target=='B' else j.order_probability;support=j.sets if target=='B' else j.orders
            for rank,i in enumerate(np.argsort(-p,kind='stable')[:10],1):jj.append({'race_id':rid,'race_date':card.race_date.iloc[0],'venue_code':v,'race_no':card.race_no.iloc[0],'target':target,'prediction_rank':rank,'predicted_key':key(support[i],horses),'predicted_probability':float(p[i]),'candidate':chosen[target],'model_version':OUT.name,'inference_status':status})
    assert maxerr<1e-10;a=pd.DataFrame(aa);j=pd.DataFrame(jj);olda=read(V5/'future_predictions_20260919_20/A_predictions.parquet');oldj=read(V5/'future_predictions_20260919_20/B_C_top10_predictions.parquet')
    ac=a.merge(olda,on=['race_id','hr_no'],validate='one_to_one',suffixes=('_new','_old'));assert len(ac)==294
    if chosen['A']=='current_A':assert (ac.A_slot_inclusion_probability_new-ac.A_slot_inclusion_probability_old).abs().max()<1e-12
    changes={'A':int((a[a.pred_rank.eq(1)].set_index('race_id').hr_no.sort_index()!=olda[olda.pred_rank.eq(1)].set_index('race_id').hr_no.sort_index()).sum())};assert changes['A']==0
    retained={}
    for target in 'BC':
        q=j[j.target.eq(target)].merge(oldj[oldj.target.eq(target)],on=['race_id','target','prediction_rank'],validate='one_to_one',suffixes=('_new','_old'));assert len(q)==270
        if chosen[target]=='current_'+target:
            retained[target]=float(abs(q.predicted_probability_new-q.predicted_probability_old).max());assert retained[target]<1e-12 and q.predicted_key_new.eq(q.predicted_key_old).all()
        top=q[q.prediction_rank.eq(1)];changes[target]=int(sum(set(json.loads(r.predicted_key_new))!=set(json.loads(r.predicted_key_old)) if target=='B' else json.loads(r.predicted_key_new)!=json.loads(r.predicted_key_old) for _,r in top.iterrows()))
    dest.mkdir();a.to_parquet(dest/'A_predictions.parquet',index=False);j.to_parquet(dest/'B_C_top10_predictions.parquet',index=False)
    dump(OUT/'forecast_verification.json',{'passed':True,'selected':chosen,'races':27,'horse_rows':294,'top10_rows':540,'highest_choice_changes':changes,'retained_probability_errors':retained,'max_probability_error':maxerr,'source_card_date':'2026-09-17','history_max_date':'2026-09-13','same_day_future_update':False})
    bins=pd.read_csv(OUT/'A_bins.csv');bins=bins[bins.period.eq('development')&bins.candidate.eq(chosen['A'])];names=a.set_index(['race_id','hr_no']);tops=j[j.prediction_rank.eq(1)].set_index(['race_id','target'])
    def label(rid,h):
        r=names.loc[(rid,h)];return f'{int(r.chul_no)} {r.horse_name_normalized}'
    lines=['# 기존 자료 기반 v6 예상표','',
        '9월 17일 보존 출마표, 9월 13일까지의 과거 이력으로 계산한 27경주·294두입니다. 이후 출전 취소나 변경은 반영되지 않았습니다. 영천은 과거 6경주로 성능 검증 표본이 부족합니다.','',
        f"A `{chosen['A']}`, B `{chosen['B']}`, C `{chosen['C']}`. A/B/C는 각각 한 마리 입상, 세 마리 조합 전체, 정확한 1→2→3착 전체의 모델 추정확률입니다. 목표별 보정이므로 세 열을 곱하지 않습니다.",'',
        '| 날짜 | 개최지 | 경주 | A 한 마리 | A 표시 확률 | B 입상 3두 | B 확률 | C 정확한 순서 | C 확률 |','|---|---|---:|---|---:|---|---:|---|---:|']
    confidence=[]
    for _,r in a[a.pred_rank.eq(1)].sort_values(['race_date','venue_code','race_no']).iterrows():
        b=tops.loc[(r.race_id,'B')];c=tops.loc[(r.race_id,'C')];bs=' + '.join(label(r.race_id,h) for h in json.loads(b.predicted_key));cs=' → '.join(label(r.race_id,h) for h in json.loads(c.predicted_key));v={'SEOUL':'서울','BUSAN':'부산','YEONGCHEON':'영천'}[r.venue_code];date=str(pd.Timestamp(r.race_date).date())
        lines.append(f'| {date} | {v} | {int(r.race_no)} | {label(r.race_id,r.hr_no)} | {r.A_slot_inclusion_probability:.1%} | {bs} | {b.predicted_probability:.1%} | {cs} | {c.predicted_probability:.1%} |')
        q=bins[bins.lower.le(r.A_slot_inclusion_probability)&bins.upper.gt(r.A_slot_inclusion_probability)].iloc[0]
        confidence.append({'race_id':r.race_id,'date':date,'venue':v,'race_no':int(r.race_no),'horse':label(r.race_id,r.hr_no),'model_probability':r.A_slot_inclusion_probability,'development_bin_lower':q.lower,'development_bin_upper':q.upper,'development_races':int(q.races),'development_hit_rate':q.hit_rate,'development_wilson_low':q.wilson_low,'development_wilson_high':q.wilson_high,'applicable_venue_evidence':r.venue_code in ('SEOUL','BUSAN')})
    lines+=['','## A 표시 확률을 해석할 과거 근거','',
        '아래는 개발 기간(2021~2024)에서 같은 확률 구간의 최고 선택이 실제로 입상한 비율입니다. 모델 선택에도 사용한 과거 자료이므로 낙관 편향이 있을 수 있고 미래 적중률 보장은 아닙니다. 영천에는 서울·부산 수치를 그대로 적용하지 않습니다. 확률을 이 관측 비율로 덮어쓰지 않았습니다.','',
        '| 표시 확률 구간 | 경주 수 | 실제 적중률 | 95% Wilson 구간 |','|---|---:|---:|---:|']
    for _,q in bins.iterrows():lines.append(f'| {q.lower:.0%}–{q.upper:.0%} | {int(q.races)} | {q.hit_rate:.1%} | {q.wilson_low:.1%}–{q.wilson_high:.1%} |')
    (OUT/'UPCOMING_PREDICTIONS.md').write_text('\n'.join(lines)+'\n');pd.DataFrame(confidence).to_csv(OUT/'A_forecast_evidence.csv',index=False)
    print(json.dumps({'selected':chosen,'highest_choice_changes':changes,'max_probability_error':maxerr}))

if __name__=='__main__':main()

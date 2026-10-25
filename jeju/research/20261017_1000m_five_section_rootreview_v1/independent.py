"""Independent saved-model replay and additive Top3 distribution, no fitting."""
from pathlib import Path
from itertools import combinations
import json,hashlib
import numpy as np
import pandas as pd
import lightgbm as lgb

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def replay(frame,folder):
    meta=json.loads((folder/'meta.json').read_text());x=frame[meta['features']].copy()
    for col,categories in meta['vocabulary'].items():
        x[col]=pd.Categorical(x[col].astype('string'),categories=categories)
    model=lgb.Booster(model_file=str(folder/'top3.txt'))
    return model.predict(x,raw_score=True,num_threads=1),meta

def evaluate(frame,scores,tau,label):
    races=[];runners=[];tickets=[]
    for rid,indices in frame.groupby('race_id',sort=False).indices.items():
        f=frame.iloc[indices];nums=f.horse_number.to_numpy(int);z=np.asarray(scores)[indices]
        assert list(nums)==sorted(nums)
        sets=np.array(list(combinations(range(len(f)),3)),int)
        e=np.array([sum(sorted(z[s].tolist())) for s in sets]);a=e/tau;q=np.exp(a-a.max());q/=q.sum()
        p=np.bincount(sets.ravel(),weights=np.repeat(q,3),minlength=len(f));assert abs(p.sum()-3)<1e-12
        y=f.finish_position.le(3).to_numpy(float);truth=tuple(np.flatnonzero(y));t=next(i for i,s in enumerate(sets) if tuple(s)==truth)
        clipped=np.clip(p,1e-12,1-1e-12);ll=-(y*np.log(clipped)+(1-y)*np.log1p(-clipped));br=(p-y)**2
        top=sorted(range(len(z)),key=lambda i:(-float(z[i]),int(nums[i])))
        six=sorted(range(len(e)),key=lambda i:(-float(e[i]),tuple(nums[sets[i]])))[:6]
        row=dict(race_id=str(rid),race_date=str(f.race_date.iloc[0]),year=int(f.year.iloc[0]),distance_m=int(f.distance_m.iloc[0]),model=label,log_loss=float(ll.mean()),brier=float(br.mean()),trio_nll=float(-np.log(q[t])),six_combo_hit=int(t in six),pick_hit=int(y[top[0]]))
        for n in (3,4,5,6):
            hits=len(set(top[:n]).intersection(truth));row[f'top{n}_capture']=hits/3;row[f'top{n}_all3']=int(hits==3)
        races.append(row)
        for i,source in enumerate(f.itertuples(index=False)):
            runners.append(dict(api_record_id=source.api_record_id,race_id=str(rid),model=label,score=float(z[i]),p_top3=float(p[i]),log_loss=float(ll[i]),brier=float(br[i])))
        for rank,i in enumerate(six,1):tickets.append(dict(race_id=str(rid),model=label,selection_rank=rank,numbers=','.join(map(str,nums[sets[i]])),probability=float(q[i]),hit=int(i==t)))
    return pd.DataFrame(races),pd.DataFrame(runners),pd.DataFrame(tickets)

def baseline():
    features=pd.read_parquet(BASE/'features.parquet');old=pd.read_parquet(BASE/'report/runner_predictions.parquet');old=old[old.variant.eq('F1_STYLE6')]
    checks={};race_frames=[];runner_frames=[];ticket_frames=[]
    for year in (2024,2025,2026):
        frame=features[features.year.eq(year)].reset_index(drop=True);score,meta=replay(frame,BASE/f'F1_STYLE6_{year}')
        saved=pd.read_parquet(BASE/f'F1_STYLE6_{year}/evaluation_scores.parquet').set_index('api_record_id').loc[frame.api_record_id]
        score_error=float(abs(saved.score.to_numpy()-score).max());assert score_error<1e-12
        r,u,t=evaluate(frame,score,meta['tau'],'F1_STYLE6');check=u.merge(old[['api_record_id','p_top3']],on='api_record_id',validate='one_to_one',suffixes=('','_saved'))
        p_error=float(abs(check.p_top3-check.p_top3_saved).max());assert p_error<1e-12
        checks[str(year)]={'score_error':score_error,'probability_error':p_error,'rows':len(frame),'races':len(r)}
        race_frames.append(r);runner_frames.append(u);ticket_frames.append(t)
    pd.concat(race_frames).to_csv(HERE/'ROOT_BASELINE_RACE_METRICS.csv',index=False)
    pd.concat(runner_frames).to_parquet(HERE/'ROOT_BASELINE_RUNNERS.parquet',index=False)
    pd.concat(ticket_frames).to_csv(HERE/'ROOT_BASELINE_TICKETS.csv',index=False)
    out={'status':'PASS','folds':checks,'baseline_models_reloaded':3,'training_calls':0,'candidate_metrics_computed':False}
    (HERE/'ROOT_BASELINE_REPLAY.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))

if __name__=='__main__':baseline()

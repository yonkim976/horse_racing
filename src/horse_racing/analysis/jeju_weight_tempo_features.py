"""Current measured weight research inputs and strictly historical tempo pars."""
from collections import defaultdict, deque
from datetime import date, timedelta
import math
import statistics

WEIGHT=['live_weight_kg','live_weight_delta_kg','live_weight_delta_pct','live_weight_abs_delta_pct','live_weight_vs_mean3_pct','live_weight_prior_count']
TEMPO=['tempo_par_total_3','tempo_par_early_3','tempo_par_closing_3','tempo_par_shift_3','tempo_par_reference_min_3','tempo_par_count_3']


def valid(v):return isinstance(v,(int,float)) and math.isfinite(v) and v>0
def mean(xs):
    xs=[v for v in xs if isinstance(v,(int,float)) and math.isfinite(v)]
    return statistics.mean(xs) if xs else float('nan')
def regime(day):
    return str(day.year) if day.year>=2025 else 'post20180831' if day>=date(2018,8,31) else 'earlier'


def tempo_observations(rows,minimum=20):
    races=defaultdict(list)
    for r in rows:races[r['race_id']].append(dict(r))
    base=defaultdict(deque);by_tempo=defaultdict(deque);pending=deque();output=[]
    for g in sorted(races.values(),key=lambda x:(x[0]['event_date'],x[0]['race_id'])):
        r=g[0];day=r['event_date'];cut=day-timedelta(days=2)
        while pending and pending[0][0]<=cut:
            d,key,t,v=pending.popleft();base[key].append((d,v));by_tempo[(key,t)].append((d,v))
        key=(r['distance_m'],r['grade'],regime(day));tempo=r['tempo']
        b=base[key];t=by_tempo[(key,tempo)]
        for pool in [b,t]:
            while pool and pool[0][0]<day-timedelta(days=730):pool.popleft()
        pars={};shift=float('nan')
        for metric in ['total','early','closing']:
            bv=[v[metric] for _,v in b if valid(v[metric])];tv=[v[metric] for _,v in t if valid(v[metric])]
            pars[metric]=mean(tv) if tempo in (1,2,3,4,5) and len(bv)>=minimum and len(tv)>=minimum else float('nan')
            if metric=='total' and math.isfinite(pars[metric]):shift=pars[metric]-mean(bv)
        for x in g:
            ok=x['outcome_status']=='normal_completed' and x['segment_quality']=='usable'
            for name,col in [('total','total_seconds'),('early','s1f_seconds'),('closing','g1f_seconds')]:
                x['tempo_residual_'+name]=x[col]-pars[name] if ok and valid(x[col]) else float('nan')
            x['tempo_shift']=shift;x['tempo_reference_count']=len(t)
            x['tempo_reference_max_date']=str(t[-1][0]) if t else None
            output.append(x)
        vals={}
        for name,col in [('total','total_seconds'),('early','s1f_seconds'),('closing','g1f_seconds')]:
            vs=[x[col] for x in g if x['outcome_status']=='normal_completed' and x['segment_quality']=='usable' and valid(x[col])]
            vals[name]=statistics.median(vs) if len(vs)>=2 else float('nan')
        if valid(vals['total']):pending.append((day,key,tempo,vals))
    return output


def build(rows):
    obs=tempo_observations(rows);by_horse=defaultdict(list)
    for r in obs:by_horse[r['horse_id']].append(r)
    for g in by_horse.values():g.sort(key=lambda r:(r['event_date'],r['entry_id']))
    features=[];lineage=[]
    for r in rows:
        past=[x for x in by_horse[r['horse_id']] if x['event_date']<=r['event_date']-timedelta(days=2)]
        weights=[x for x in past if valid(x['body_weight_kg'])][-3:]
        same=[x for x in past if x['distance_m']==r['distance_m']][-3:]
        w=r['body_weight_kg'] if valid(r['body_weight_kg']) else float('nan')
        last=weights[-1]['body_weight_kg'] if weights else float('nan')
        delta=w-last;dp=100*delta/last
        f=dict(entry_id=r['entry_id'],live_weight_kg=w,live_weight_delta_kg=delta,live_weight_delta_pct=dp,
            live_weight_abs_delta_pct=abs(dp),live_weight_vs_mean3_pct=100*(w/mean([x['body_weight_kg'] for x in weights])-1),live_weight_prior_count=len(weights))
        for metric in ['total','early','closing']:f['tempo_par_'+metric+'_3']=mean([x['tempo_residual_'+metric] for x in same])
        supported=[x for x in same if math.isfinite(x['tempo_residual_total'])]
        f.update(tempo_par_shift_3=mean([x['tempo_shift'] for x in supported]),
            tempo_par_reference_min_3=min([x['tempo_reference_count'] for x in supported],default=float('nan')),
            tempo_par_count_3=len(supported))
        features.append(f);lineage.append(dict(entry_id=r['entry_id'],weight_current_source='historical_measured_weight_publication_time_unverified',
            past_weight_entry_ids=[x['entry_id'] for x in weights],past_tempo_entry_ids=[x['entry_id'] for x in same]))
    return features,lineage,obs

"""Historical track-relative records and measured checkpoint context, T-2 only."""
from collections import defaultdict, deque
from datetime import timedelta
import math
import re

PAR = ['par_total_residual_3','par_early_residual_3','par_closing_residual_3',
       'par_track_shift_3','par_supported_count_3','tempo_last','tempo_mean_3','tempo_known_count_3']
PACE = ['pace_c3_quality_3','pace_c4_quality_3','pace_early_gap_3','pace_c3_gap_3','pace_c4_gap_3',
        'pace_gap_change_3','pace_c3_c4_gain_3','pace_c4_finish_gain_3','pace_front_fade_3',
        'pace_pack_size_3','pace_pack_inner_3','pace_history_count_3','pace_current_low_number_x_stall']
FEATURES=PAR+PACE

def finite(x):
    return isinstance(x,(int,float)) and math.isfinite(x)

def avg(xs):
    x=[float(v) for v in xs if finite(v)]
    return sum(x)/len(x) if x else float('nan')

def group_position(text, horse_number):
    """Only explicit parenthesized lateral groups, not a blocked-path label."""
    groups=re.findall(r'\(([^()]*)\)',str(text or ''))
    matches=[]
    for g in groups:
        numbers=[int(n) for n in re.findall(r'\d+',g)]
        if horse_number in numbers:
            matches.append((len(numbers),float(numbers[0]==horse_number)))
    return matches[0] if len(matches)==1 else (float('nan'),float('nan'))

def regime(day):
    return str(day.year) if day.year>=2025 else '2018_2024' if day.year>=2018 else 'earlier'

def historical_observations(rows, minimum=20):
    """For past race A, compare against races strictly through A-2.

    Current A measurements are observations for later targets, never A predictors.
    """
    races=defaultdict(list)
    for r in rows:races[r['race_id']].append(dict(r))
    ordered=sorted(races.values(),key=lambda g:(g[0]['event_date'],g[0]['race_id']))
    base=defaultdict(deque);track=defaultdict(deque);pending=deque();out=[]
    for g in ordered:
        r=g[0];day=r['event_date'];cut=day-timedelta(days=2)
        while pending and pending[0][0]<=cut:
            dd,key,tr,values=pending.popleft()
            base[key].append((dd,values));track[(key,tr)].append((dd,values))
        key=(r['distance_m'],regime(day),r.get('grade'))
        for pool in [base[key],track[(key,r.get('track_class'))]]:
            while pool and pool[0][0]<day-timedelta(days=730):pool.popleft()
        b=list(base[key]);t=list(track[(key,r.get('track_class'))])
        # Unknown track does not create a meaningful weather class.
        use=t if r.get('track_class') and len(t)>=minimum else b
        par={};shift=float('nan')
        for metric in ['total','early','closing']:
            vals=[x[1][metric] for x in use if finite(x[1][metric])]
            par[metric]=avg(vals) if len(vals)>=minimum else float('nan')
        if len(t)>=minimum and r.get('track_class'):
            shift=par['total']-avg(x[1]['total'] for x in b)
        leader={name:min([x[name] for x in g if finite(x.get(name)) and x[name]>0],default=float('nan'))
                for name in ['s1f_seconds','c3_seconds','c4_seconds']}
        for x in g:
            normal=x.get('outcome_status')=='normal_completed'
            usable=normal and x.get('segment_quality')=='usable'
            for label,col in [('total','total_seconds'),('early','s1f_seconds'),('closing','g1f_seconds')]:
                v=x.get(col)
                x['par_'+label+'_residual']=v-par[label] if usable and finite(v) and v>0 else float('nan')
            x['par_track_shift']=shift
            x['par_reference_count']=len(use)
            for label,col in [('early','s1f_seconds'),('c3','c3_seconds'),('c4','c4_seconds')]:
                v=x.get(col)
                x['pace_'+label+'_gap']=v-leader[col] if finite(v) and v>0 else float('nan')
            field=x['field_size']
            for label in ['c3','c4']:
                pos=x.get(label+'_rank')
                x['pace_'+label+'_quality']=1-(pos-1)/(field-1) if finite(pos) and 1<=pos<=field and field>1 else float('nan')
            a=x.get('c3_rank');bpos=x.get('c4_rank');f=x.get('finish_position');e=x.get('early_rank')
            x['pace_c3_c4_gain']=a-bpos if finite(a) and finite(bpos) else float('nan')
            x['pace_c4_finish_gain']=bpos-f if normal and finite(bpos) and finite(f) else float('nan')
            x['pace_gap_change']=x['pace_c4_gap']-x['pace_early_gap']
            x['pace_front_fade']=float(e<=3 and not (normal and f<=3)) if finite(e) else float('nan')
            size,inner=group_position(x.get('corner_4'),x['horse_number'])
            x['pace_pack_size']=size;x['pace_pack_inner']=inner
            x['pace_stall']=float(bpos>=3 and f>=bpos) if normal and finite(bpos) else float('nan')
            out.append(x)
        valid=[x for x in g if x.get('outcome_status')=='normal_completed' and x.get('segment_quality')=='usable']
        def median(v):
            v=sorted(z for z in v if finite(z) and z>0)
            n=len(v);return (v[(n-1)//2]+v[n//2])/2 if n>=2 else float('nan')
        values={k:median(x.get(col) for x in valid) for k,col in
                [('total','total_seconds'),('early','s1f_seconds'),('closing','g1f_seconds')]}
        if finite(values['total']):pending.append((day,key,r.get('track_class'),values))
    return out

def build_features(targets, observations):
    by_horse=defaultdict(list)
    for row in observations:by_horse[row['horse_id']].append(row)
    for rows in by_horse.values():rows.sort(key=lambda r:(r['event_date'],r['entry_id']))
    result=[];lineage=[]
    for t in targets:
        cut=t['event_date']-timedelta(days=2)
        # Same-distance for record/pace magnitudes; no 200/210m pooling.
        hist=[r for r in by_horse[t['horse_id']] if r['event_date']<=cut and r['distance_m']==t['distance_m']][-3:]
        v={'entry_id':t['entry_id']}
        for f in PAR[:4]:v[f]=avg(r.get(f.removesuffix('_3')) for r in hist)
        v['par_supported_count_3']=sum(finite(r.get('par_total_residual')) for r in hist)
        v['tempo_last']=hist[-1].get('tempo',float('nan')) if hist else float('nan')
        v['tempo_mean_3']=avg(r.get('tempo') for r in hist)
        v['tempo_known_count_3']=sum(finite(r.get('tempo')) for r in hist)
        for f in PACE[:11]:v[f]=avg(r.get(f.removesuffix('_3')) for r in hist)
        v['pace_history_count_3']=len(hist)
        number=t.get('horse_number')
        v['pace_current_low_number_x_stall']=float(number<=2)*avg(r.get('pace_stall') for r in hist) if finite(number) else float('nan')
        result.append(v)
        lineage.append(dict(entry_id=t['entry_id'],cutoff=str(cut),source_entry_ids=[r['entry_id'] for r in hist],
                            max_source_date=str(hist[-1]['event_date']) if hist else None))
    return result,lineage

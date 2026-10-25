"""Make out-of-training axis/alternate pairs; no current race sections."""
import json
import numpy as np
import pandas as pd
import axis_common as c

def main():
    c.check();assert not (c.OUT/'pairs.parquet').exists();f=c.frame();rows=[]
    old=pd.read_parquet(c.PREV/'outputs/race_metrics.parquet').query("variant=='state_gbm' and meet==3").set_index('race_key')
    for year in [2024,2025,2026]:
        folder=c.PREV/'outputs/models'/f'state_gbm_3_{year}';meta=json.loads((folder/'metadata.json').read_text())
        scores=pd.read_parquet(folder/'scores.parquet').set_index('row_number')
        one=f[f.meet.eq(3)&f.year.isin([year-1,year])].copy()
        one['score']=one.row_number.map(scores.score);assert one.score.notna().all()
        for key,g in one.groupby('race_key',sort=False):
            g=g.sort_values('program_no');score=g.score.to_numpy(float)
            idx=c.old.scorer.probability_order(score)
            orders,mass=c.old.prob.ordered_distribution(score,c.old.prob.trio_distribution(score,meta['temperature']),meta['order_temperature'])
            marginal=c.old.prob.marginals(len(g),orders,mass)
            assert np.array_equal(idx,c.old.scorer.probability_order(marginal['top3']))
            a,b,d=[g.iloc[i] for i in idx[:3]]
            r={'race_key':key,'race_date':a.race_date,'meet':3,'year':int(a.year),'fold_year':year,
                'phase':'evaluation' if a.year==year else 'calibration','grade_raw':a.grade_raw,
                'grade_level':float(a.grade),'distance_m':float(a.distance_m),'field_size':len(g),
                'axis_score':float(a.score),'score_gap':float(a.score-b.score),'target':bool(a.grade_raw=='국5등급' and a.distance_m in [1300,1600])}
            for prefix,horse,i in [('axis',a,idx[0]),('alt',b,idx[1]),('third',d,idx[2])]:
                for col in ['program_no','horse_id','outcome']:r[prefix+'_'+col]=horse[col]
                r[prefix+'_hit']=int(1<=horse.outcome<=3);r[prefix+'_probability']=float(marginal['top3'][i])
            for name in c.AXIS:r['axis_'+name]=a[name]
            for name in c.DIFF:r['diff_'+name]=b[name]-a[name]
            for name in ['previous_source_date','cutoff_date','previous_grade','previous_distance','promoted','distance_change',
                         'section_last600_n5','section_late_n5','state_form_trend','state_close_mean','current_vs_previous_carried_weight']:
                r['axis_'+name]=a[name]
            r['probability_gap']=r['axis_probability']-r['alt_probability'];r['switch_label']=r['alt_hit']-r['axis_hit']
            if r['phase']=='evaluation':
                ref=old.loc[key]
                assert int(ref.axis_program_no)==r['axis_program_no'] and int(ref.axis_top3)==r['axis_hit']
                assert abs(ref.axis_probability-r['axis_probability'])<1e-12
            rows.append(r)
        print('Pairs',year,flush=True)
    out=pd.DataFrame(rows);assert not out.duplicated(['fold_year','race_key']).any()
    out.to_parquet(c.OUT/'pairs.parquet',index=False,compression='zstd')
    ev=out[out.phase.eq('evaluation')];assert len(ev)==1961 and ev.target.sum()==210
    c.save(c.OUT/'pairs_audit.json',{'rows':len(out),'evaluation_races':len(ev),'target_races':int(ev.target.sum()),
        'source_dates_before_cutoff':True,'original_axis_probability_reproduced':True,
        'raw_score_order_matches_top3_marginal_order':True,'postrace_sections_in_learning_inputs':False,
        'features':c.FEATURES,'pair_sha256':c.sha(c.OUT/'pairs.parquet')})
    print('Pairs done',len(out),c.storage(),flush=True)

if __name__=='__main__':main()

import re
from collections import Counter
import pandas as pd
import numpy as np
from scipy.stats import t
from common import *
from passing import parse
from analyze import bh

def estimate(g,col):
    r=g.groupby(['race_id','race_date'])[col].mean().dropna();n=len(r);G=r.index.get_level_values('race_date').nunique()
    if n<50 or G<20:return None
    e=r-r.mean();scores=e.groupby(level='race_date').sum();se=np.sqrt(G/(G-1)*np.square(scores).sum()/n**2);q=t.ppf(.975,G-1)
    return {'races':n,'days':G,'pairs':len(g),'difference':float(r.mean()),'ci_low':float(r.mean()-q*se),'ci_high':float(r.mean()+q*se),'p':float(2*t.sf(abs(r.mean()/se),G-1)) if se else 1.}

def main():
    d=pd.read_parquet(OUT/'runners.parquet');p=pd.read_parquet(OUT/'passing_raw.parquet')
    look={rid:g.set_index('horse_number').to_dict('index') for rid,g in d.groupby('race_id')}
    pairs=[];positions=[];issues=[];counts=Counter()
    for row in p.itertuples(index=False):
        if row.race_id not in look:continue
        counts['eligible_point_rows']+=1
        try:groups=parse(row.notation_raw)
        except ValueError as e:
            issues.append({'race_id':row.race_id,'point':row.point_code,'raw':row.notation_raw,'reason':str(e)});continue
        roster=look[row.race_id];ids=[i for g in groups for i in g['members']]
        if set(ids)!=set(roster):
            issues.append({'race_id':row.race_id,'point':row.point_code,'raw':row.notation_raw,'reason':'roster mismatch'});continue
        counts['parsed_and_roster_verified']+=1
        for j,pack in enumerate(groups):
            size=len(pack['members'])
            for k,num in enumerate(pack['members']):
                a=roster[num];positions.append({'race_id':row.race_id,'race_date':a['race_date'],'venue':a['venue'],'point':row.point_code,'gate_band':a['band'],'pack_size':size,'pack_index':j,'pack_side':'SINGLE' if size==1 else ('INNERMOST' if k==0 else ('OUTERMOST' if k==size-1 else 'MIDDLE'))})
            if size<2:continue
            inner=roster[pack['members'][0]];outer=roster[pack['members'][-1]]
            pairs.append({'race_id':row.race_id,'race_date':inner['race_date'],'venue':inner['venue'],'quarter':inner['quarter'],'point':row.point_code,'pack_index':j,'pack_size':size,'inner_horse_number':pack['members'][0],'outer_horse_number':pack['members'][-1],'top3_difference':outer['top3']-inner['top3'],'finish_pct_difference':outer['finish_pct']-inner['finish_pct'],'gate_pct_difference':outer['gate_pct']-inner['gate_pct'],'prior_top3_difference':outer['prior_top3_5']-inner['prior_top3_5']})
    pairs=pd.DataFrame(pairs);pos=pd.DataFrame(positions);pairs.to_parquet(OUT/'pack_pairs.parquet',index=False)
    transition=pos.groupby(['venue','point','gate_band','pack_side']).size().rename('observations').reset_index();transition['share']=transition.observations/transition.groupby(['venue','point','gate_band']).observations.transform('sum');transition.to_parquet(OUT/'gate_to_pack_position.parquet',index=False)
    stats=[]
    for (venue,point),g in pairs.groupby(['venue','point']):
        e=estimate(g,'top3_difference')
        if e:stats.append({'venue':venue,'point':point,**e,'mean_gate_pct_difference':float(g.gate_pct_difference.mean()),'mean_prior_top3_difference':float(g.prior_top3_difference.mean())})
    s=pd.DataFrame(stats);s['q']=bh(s.p);s.to_parquet(OUT/'pack_outcome_associations.parquet',index=False)
    periods=[]
    for (venue,point,quarter),g in pairs[pairs.point.isin(['S1F','G1F'])].groupby(['venue','point','quarter']):
        e=estimate(g,'top3_difference')
        if e:periods.append({'venue':venue,'point':point,'quarter':quarter,**e})
    periods=pd.DataFrame(periods);periods['q']=bh(periods.p);periods.to_parquet(OUT/'pack_quarter_associations.parquet',index=False)
    # Raw-source comparisons use fixed dates and race 1, chosen before examining outcome effects.
    examples=[];snippets=[]
    for meet,date in [(1,'20170107'),(3,'20170106'),(1,'20200105'),(3,'20240901')]:
        folder=ROOT/f'data/raw/kra_text/dacom11/meet={meet}/year={date[:4]}/month={date[4:6]}/day={date[6:]}'
        files=sorted(folder.glob('*.rpt'))
        if not files:continue
        f=files[0];text=f.read_bytes().decode('cp949',errors='replace');block=re.split(r'제목\s*:',text)[1]
        lines=block.splitlines();points={};saved=[]
        for line in lines:
            m=re.search(r'(S-?1F|C[1-4]|G-?[12468]F)\s*:\s*(.*)',line)
            if m and m.group(2).strip():
                raw=m.group(2).strip();point=m.group(1).replace('S-1F','S1F').replace('G-','G');point=point[1:]+'C' if point.startswith('C') else point
                points[point]=raw;saved.append(line)
        db=p[p.meet.eq(meet)&p.race_date.eq(f'{date[:4]}-{date[4:6]}-{date[6:]}')&p.race_number.eq(1)]
        for row in db.itertuples(index=False):
            if row.point_code not in points:continue
            raw=points[row.point_code];equal=re.sub(r'\s','',raw)==re.sub(r'\s','',row.notation_raw)
            examples.append({'meet':meet,'date':date,'race':1,'point':row.point_code,'raw_source':raw,'operational_raw':row.notation_raw,'equal_ignoring_whitespace':equal,'source_path':str(f.relative_to(ROOT)),'source_sha256':sha(f)})
        snippets.append(f'## meet {meet}, {date}, 1경주\n\n원천: `{f.relative_to(ROOT)}`\n\n```text\n'+ '\n'.join(lines[:6]+saved)+'\n```\n')
    dump('raw_source_comparisons.json',examples)
    (OUT/'RAW_EXAMPLES.md').write_text('# 통과조 원문 대조\n\n공식 설명: https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1\n\n괄호 내 순서는 같은 마군에서 상대 내측부터다. 절대 주로 라인 또는 정확한 주행거리로 변환하지 않았다.\n\n'+'\n'.join(snippets))
    dump('passing_quality.json',{'counts':dict(counts),'issue_counts':dict(Counter(r['reason'] for r in issues)),'issues':issues,'pack_pairs':len(pairs),'raw_source_samples':len(examples),'source_matches':sum(x['equal_ignoring_whitespace'] for x in examples),'position_is_relative_within_pack':True})
    print(s.to_string(index=False));print('raw source matches',sum(x['equal_ignoring_whitespace'] for x in examples),'/',len(examples))
if __name__=='__main__':main()

"""Render an offline, local-only viewer. All database text is inserted as text."""

import json
from pathlib import Path

import pandas as pd

HERE=Path(__file__).resolve().parent
OUT=HERE/'outputs'


def values(row, suffix):
    return [None if pd.isna(row[f's{i}_{suffix}']) else float(row[f's{i}_{suffix}']) for i in range(1,7)]


def basic(row):
    return dict(date=str(row.date),race=int(row.race_no),number=int(row.program_no),name=str(row.horse_name),
        rank=int(row.finish_rank),finish=float(row.finish_seconds),seconds=values(row,'seconds'),
        index=values(row,'index'),delta=values(row,'delta'),shape=str(row['shape']),
        position=str(row.observed_early_position),order=[None if pd.isna(row.get('order_'+p)) else int(row['order_'+p])
            for p in ['S1F','G4F','G3F','G2F','G1F']]+[int(row.finish_rank)])


def main():
    d=pd.read_parquet(OUT/'runner_profiles.parquet')
    selected=json.loads((OUT/'summary.json').read_text())['examples']
    races=[]
    for key in selected:
        group=d[d.date.eq(key['date'])&d.race_no.eq(key['race_no'])].sort_values('program_no')
        runners=[]
        for _,row in group.iterrows():
            entry=basic(row)
            entry['history']=[]
            hist=d[d.horse_id.eq(row.horse_id)&d.date.lt(row.date)].tail(5)
            for _,past in hist.iterrows():
                entry['history'].append(basic(past))
            entry['past_index']=[None if pd.isna(row[f'past5_s{i}_index_mean']) else float(row[f'past5_s{i}_index_mean']) for i in range(1,7)]
            entry['past_n']=[int(row[f'past5_s{i}_n']) for i in range(1,7)]
            runners.append(entry)
        races.append(dict(date=key['date'],race=key['race_no'],runners=runners))
    payload=json.dumps(races,ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    template=(HERE/'viewer_template.html').read_text()
    assert '__DATA__' in template
    (OUT/'viewer.html').write_text(template.replace('__DATA__',payload))
    (OUT/'viewer_data.json').write_text(json.dumps(races,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print('Rendered',len(races),'races')


if __name__=='__main__':
    main()

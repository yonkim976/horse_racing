"""Offline all-distance viewer and standard research figures."""

import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import prepare as p


def basic(row):
    points=p.layout(int(row.distance));n=len(points)-1
    def arr(suffix):return [None if pd.isna(row[f's{i}_{suffix}']) else float(row[f's{i}_{suffix}']) for i in range(1,n+1)]
    return dict(date=str(row.date),race=int(row.race_no),number=int(row.program_no),name=str(row.horse_name),
        rank=int(row.finish_rank),finish=float(row.finish),seconds=arr('seconds'),index=arr('index'),delta=arr('delta'),
        style=str(row.style8),late_tag=str(row.late_tag),early=None if pd.isna(row.p_S1F) else int(row.p_S1F),
        order=[None if label not in row or pd.isna(row['p_'+label]) else int(row['p_'+label]) for label,_ in points[1:-1]]+[int(row.finish_rank)])


def main():
    d=pd.read_parquet(p.OUT/'profiles.parquet');x=pd.read_parquet(p.OUT/'features.parquet')
    races=[]
    for distance,g in d.groupby('distance'):
        full=g.groupby(['date','race_no']).agg(rows=('horse_id','size'),complete=('complete','all'))
        keys=full[full.complete&full.rows.ge(6)].tail(2).reset_index()
        for key in keys.itertuples():
            selected=g[g.date.eq(key.date)&g.race_no.eq(key.race_no)].sort_values('program_no')
            runners=[]
            for _,row in selected.iterrows():
                info=basic(row);n=len(info['index'])
                info['past_index']=[None if pd.isna(x.loc[row.row_id,f'same_s{i}_index_mean']) else float(x.loc[row.row_id,f'same_s{i}_index_mean']) for i in range(1,n+1)]
                info['past_n']=[int(x.loc[row.row_id,f'same_s{i}_index_n']) for i in range(1,n+1)]
                hist=d[d.horse_id.eq(row.horse_id)&d.distance.eq(distance)&d.date.lt(row.date)].tail(5)
                info['history']=[basic(v) for _,v in hist.iterrows()]
                runners.append(info)
            points=p.layout(int(distance))
            segments=[dict(start=a[1],end=b[1],length=b[1]-a[1],left=a[0],right=b[0]) for a,b in zip(points,points[1:])]
            races.append(dict(distance=int(distance),date=key.date,race=int(key.race_no),segments=segments,runners=runners))
    metrics=pd.read_csv(p.OUT/'evaluation_metrics.csv').to_dict('records')
    data=dict(races=races,metrics=metrics)
    payload=json.dumps(data,ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    (p.OUT/'viewer.html').write_text((p.HERE/'viewer_template.html').read_text().replace('__DATA__',payload))
    p.save('viewer_data.json',data)
    ci=pd.read_csv(p.OUT/'paired_intervals.csv')
    z=ci[ci.scope.eq('all')&ci.metric.eq('mae')].copy()
    fig,ax=plt.subplots(figsize=(8,4.2))
    yy=np.arange(len(z));value=z.difference.to_numpy()*1000
    ax.errorbar(value,yy,xerr=np.vstack([(z.difference-z.low).to_numpy(),(z.high-z.difference).to_numpy()])*1000,
        fmt='o',color='#216c98',capsize=4)
    ax.axvline(0,color='#8c9aa5',ls='--');ax.set_yticks(yy,[a+' vs '+b for a,b in zip(z.new,z.old)])
    ax.set_xlabel('MAE difference (milliseconds per 1000m); negative = lower error')
    ax.set_title('Next-race record benchmark, 2024–2026 | paired date 95% intervals')
    ax.grid(axis='x',alpha=.18);ax.invert_yaxis();fig.tight_layout();fig.savefig(p.OUT/'next_race_effects.png',dpi=170);plt.close(fig)
    dist=pd.read_csv(p.OUT/'segment_distributions.csv');layouts=pd.read_csv(p.OUT/'segment_layouts.csv')
    fig,axes=plt.subplots(5,2,figsize=(12,14))
    for ax,distance in zip(axes.flat,p.DISTANCES):
        a=dist[dist.distance.eq(distance)&dist.scope.eq('2024_2026')]
        period='2024–2026'
        if a.empty:a=dist[dist.distance.eq(distance)&dist.scope.eq('all')];period='historical'
        layout=layouts[layouts.distance.eq(distance)]
        xx=(layout.start_m+layout.end_m)/2
        ax.plot(xx,a.index_mean,'o-',color='#216c98');ax.fill_between(xx,a.index_p20,a.index_p80,color='#b9d9eb',alpha=.55)
        ax.axhline(100,color='#7b8791',ls='--',lw=.8)
        ax.set_title(f'{distance}m | {period} | n={int(a.n.iloc[0]):,}')
        ax.set_xlim(0,distance);ax.set_ylim(70,125);ax.set_ylabel('Self-mean speed index');ax.grid(alpha=.15)
    for ax in axes[-1]:ax.set_xlabel('Distance from start (m); point = segment midpoint')
    fig.suptitle('Busan minimum measured segments | mean and individual P20–P80 | not optimal pace',y=.998)
    fig.tight_layout();fig.savefig(p.OUT/'distance_profile_curves.png',dpi=150);plt.close(fig)
    print('Rendered',len(races),'race examples')


if __name__=='__main__':main()

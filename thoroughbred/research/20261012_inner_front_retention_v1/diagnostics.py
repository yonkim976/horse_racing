"""Retain gains/losses and importance of each predefined information bundle."""
import json
import pandas as pd
import run as e


def main():
    d=pd.read_csv(e.OUT/'race_diagnostics.csv');rows=[]
    for year in ['all',2024,2025,2026]:
        z=d if year=='all' else d[d.year==year]
        b=z[z.variant=='baseline22'].set_index('race_key')
        a=z[z.variant=='combined55'].set_index('race_key')
        for metric in ['axis_top3','axis_top2','quinella_one','axis_next3','trio6']:
            x=a[metric];v=b[metric].reindex(a.index)
            rows.append(dict(period=str(year),metric=metric,new_hits=int(x.sum()),old_hits=int(v.sum()),
                             gains=int(((x==1)&(v==0)).sum()),losses=int(((x==0)&(v==1)).sum())))
    pd.DataFrame(rows).to_csv(e.OUT/'gain_loss.csv',index=False)
    bundles=dict(base=e.BASE,early=e.EARLY,front=e.PROB,retention=e.KEEP,interaction=e.INTER)
    importance=[]
    for folder in sorted((e.OUT/'models').iterdir()):
        m=json.loads((folder/'metadata.json').read_text());g=m['gain'];total=sum(g.values())
        for name,cols in bundles.items():
            importance.append(dict(model=folder.name,variant=m['variant'],year=m['evaluation_year'],bundle=name,
                                   gain=sum(g.get(c,0.) for c in cols),share=sum(g.get(c,0.) for c in cols)/total))
    pd.DataFrame(importance).to_csv(e.OUT/'bundle_importance.csv',index=False)
    e.check();print('Gain/loss and bundle diagnostics retained')


if __name__=='__main__':
    main()

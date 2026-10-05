"""Post-evaluation diagnostic: class accuracy versus always predicting normal."""
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent
OUT=HERE/'outputs'


def main():
    target=OUT/'tempo_normal_baseline.csv'
    if target.exists(): raise FileExistsError(target)
    f=pd.read_csv(OUT/'tempo_predictions.csv')
    f=f[f.variant.eq('field_model') & f.actual_class.notna()]
    rows=[]
    for (meet,year),one in f.groupby(['meet','year']):
        rows.append({'meet':int(meet),'year':int(year),'races':len(one),
          'always_normal_hit':float(one.actual_class.eq(1).mean()),'field_model_hit':float(one.class_hit.mean())})
    pd.DataFrame(rows).to_csv(target,index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__=='__main__': main()

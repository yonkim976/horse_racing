"""Enumerate fixed five-horse trio boxes against the previous six-ticket set."""
from pathlib import Path
import hashlib
import itertools
import json

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = HERE.parent
OUT = HERE/'outputs'
PREVIOUS = R/'20261024_axis4_trio_comparison_v1/outputs'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, obj):
    assert p.resolve().is_relative_to(HERE)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def main():
    OUT.mkdir(exist_ok=True)
    protected = [PREVIOUS/'race_results.parquet', PREVIOUS/'summary.csv', PREVIOUS/'verification.json',
        R/'20261022_probability_comparison_v1/outputs/population_flags.parquet', ROOT/'config/prediction_model_registry.json']
    manifest = {str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in protected}
    save(OUT/'input_manifest.json', manifest)
    shared = [R/'README.md',R/'conclusions/README.md',R/'conclusions/SOURCES.md',R/'conclusions/source_manifest.json',R/'ARTIFACT_SIZE_LOG.md']
    if not (OUT/'publication_before.json').exists():
        save(OUT/'publication_before.json',{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in shared})
    f = pd.read_parquet(PREVIOUS/'race_results.parquet')
    flags = pd.read_parquet(protected[3])
    official = {key:tuple(sorted(g.loc[g.finish_order.between(1,3),'program_no'].astype(int))) for key,g in flags.groupby('race_key')}
    got6=[];got10=[]
    for row in f.itertuples():
        other = list(map(int,row.companions.split(',')))
        five = [row.axis,*other]
        assert len(set(five))==5
        truth = official[row.race_key]
        assert truth==tuple(map(int,row.actual.split(','))) and len(truth)==3
        six = {tuple(sorted((row.axis,*t))) for t in itertools.combinations(other,2)}
        ten = {tuple(sorted(t)) for t in itertools.combinations(five,3)}
        assert len(six)==6 and len(ten)==10 and six.issubset(ten)
        h6=truth in six;h10=truth in ten
        assert h6==row.hit and h10==set(truth).issubset(set(five))
        assert not (h6 and not h10)
        assert not (h10 and not h6) or row.axis not in truth
        got6.append(h6);got10.append(h10)
    f['six_hit']=got6;f['ten_hit']=got10
    f['extra_hit']=f.ten_hit & ~f.six_hit
    rows=[]
    for scope, scoped in f.groupby('scope'):
        groups=[('all',scoped),*[(str(y),g) for y,g in scoped.groupby('year')],
            *[('seoul' if m==1 else 'busan',g) for m,g in scoped.groupby('meet')],
            ('2026H2',scoped[scoped.race_date.ge('2026-07-01')])]
        for name,g in groups:
            for model,z in g.groupby('model'):
                n=len(z);h6=int(z.six_hit.sum());h10=int(z.ten_hit.sum());delta=h10-h6
                rows.append(dict(scope=scope,subgroup=name,model=model,races=n,six_hits=h6,ten_hits=h10,
                    six_rate=h6/n,ten_rate=h10/n,extra_hits=delta,difference=delta/n,
                    relative_hit_gain=h10/h6-1,extra_four_hits_per_race=delta/n,
                    six_hits_per_ticket=h6/(n*6),ten_hits_per_ticket=h10/(n*10),
                    per_ticket_efficiency_ratio=(h10/10)/(h6/6),
                    axis_failures=int((~z.axis_hit).sum()),rescued_axis_failure_fraction=delta/int((~z.axis_hit).sum())))
    summary=pd.DataFrame(rows)
    summary.to_csv(OUT/'summary.csv',index=False)
    # Only newly covered races are retained; original full predictions remain referenced.
    f[f.extra_hit & f.scope.eq('identical_roster')][['race_key','race_date','model','axis','companions','actual']].to_parquet(OUT/'extra_hits.parquet',compression='zstd',index=False)
    previous=pd.read_csv(PREVIOUS/'summary.csv')
    check=summary[~summary.subgroup.eq('2026H2')].merge(previous,on=['scope','subgroup','model'],validate='1:1')
    assert len(check)==len(previous) and check.six_hits.eq(check.hits).all() and check.races_x.eq(check.races_y).all()
    for name,meta in manifest.items():
        assert sha(ROOT/name)==meta['sha256']
    save(OUT/'verification.json',dict(status='passed',race_policy_records_checked=len(f),
        summaries_matching_previous=len(check),official_truth_checked=True,
        all_six_sets_nested_in_ten=True,all_new_hits_require_axis_failure=True,
        original_sources_unchanged=True,new_models=0,production_changed=False,
        independent_future_test=False,unit_stake_cost_increase=10/6-1))
    print(summary[summary.scope.eq('identical_roster') & summary.subgroup.eq('all')].to_string(index=False))


if __name__=='__main__':
    main()

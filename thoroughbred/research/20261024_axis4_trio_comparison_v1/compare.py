"""Read-only replay of fixed axis+four trio tickets; no training or tuning."""
from pathlib import Path
import hashlib
import itertools
import json

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
R = HERE.parent
OUT = HERE / 'outputs'
PATHS = {
    'registry': ROOT/'config/prediction_model_registry.json',
    'operating': ROOT/'data/research/thoroughbred_boundary_20260918_v6/A_horse_predictions.parquet',
    'operating_splits': ROOT/'data/research/thoroughbred_offline_20260918_v5/windows/split_support.csv',
    'dynamic': R/'20261022_dynamic_race_model_v1/outputs/runner_probabilities.parquet',
    'dynamic_metrics': R/'20261022_dynamic_race_model_v1/outputs/race_metrics.parquet',
    'old': R/'20261022_probability_comparison_v1/outputs/runner_probabilities.parquet',
    'flags': R/'20261022_probability_comparison_v1/outputs/population_flags.parquet',
    'risk_runners': R/'20261024_axis_failure_risk_v1/outputs/conditional_runners.parquet',
    'risk_races': R/'20261024_axis_failure_risk_v1/outputs/race_predictions.parquet',
    'risk_decision': R/'20261024_axis_failure_risk_v1/outputs/decision.json',
    'risk_verification': R/'20261024_axis_failure_risk_v1/outputs/verification.json',
}


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()


def save(p, value):
    assert p.resolve().is_relative_to(HERE)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def rank(g):
    return g.assign(tie_score=g.top3.round(12)).sort_values(
        ['tie_score', 'program_no'], ascending=[False, True])


def score(g, model, scope):
    ordered = rank(g)
    axis = ordered.iloc[0]
    other = ordered.program_no.iloc[1:5].astype(int).tolist()
    truth = set(g.loc[g.outcome.between(1, 3), 'program_no'].astype(int))
    assert len(truth) == 3 and len(other) == 4
    tickets = [tuple(sorted((int(axis.program_no), *x))) for x in itertools.combinations(other, 2)]
    assert len(set(tickets)) == 6
    hit = tuple(sorted(truth)) in tickets
    simple = int(axis.program_no) in truth and truth.issubset(set(ordered.program_no.iloc[:5]))
    assert hit == simple
    parts = str(g.race_key.iloc[0]).split(':')
    return dict(race_key=g.race_key.iloc[0], race_date=pd.to_datetime(parts[1]),
        meet=int(parts[0]), year=int(parts[1][:4]), model=model, scope=scope,
        field_size=len(g), axis=int(axis.program_no),
        companions=','.join(map(str, other)), actual=','.join(map(str, sorted(truth))),
        axis_hit=int(axis.program_no) in truth, hit=bool(hit))


def aggregate(frame):
    rows = []
    for scope, scoped in frame.groupby('scope'):
        groups = [('all', scoped)]
        groups += [(str(y), g) for y, g in scoped.groupby('year')]
        groups += [('seoul' if m == 1 else 'busan', g) for m, g in scoped.groupby('meet')]
        for name, group in groups:
            for model, g in group.groupby('model'):
                ah = int(g.axis_hit.sum()); hits = int(g.hit.sum())
                rows.append(dict(scope=scope, subgroup=name, model=model, races=len(g),
                    hits=hits, hit_rate=hits/len(g), axis_hits=ah, axis_rate=ah/len(g),
                    hit_given_axis=hits/ah if ah else None,
                    axis_failures=len(g)-ah, companions_failures=ah-hits))
    return pd.DataFrame(rows)


def paired(frame):
    result = []
    for scope in ['identical_roster', 'matched_starters_sensitivity']:
        f = frame[frame.scope.eq(scope)]
        for subgroup, g in [('all', f), *[(str(y), z) for y, z in f.groupby('year')]]:
            p = g.pivot(index=['race_key', 'race_date'], columns='model', values='hit').astype(int)
            comparisons = [('operating_A_v5', x) for x in p.columns if x != 'operating_A_v5']
            comparisons += [('state_gbm118', 'axis_failure_selected')]
            n = p.groupby(level='race_date').size().to_numpy()
            rng = np.random.default_rng(20261024)
            weights = rng.multinomial(len(n), np.full(len(n), 1/len(n)), size=2000)
            den = weights@n
            for baseline, candidate in comparisons:
                diff = p[candidate]-p[baseline]
                daily = diff.groupby(level='race_date').sum().to_numpy()
                boot = (weights@daily)/den
                ci = np.quantile(boot, [.025, .975])
                result.append(dict(scope=scope, subgroup=subgroup, baseline=baseline, candidate=candidate,
                    races=len(p), dates=len(n), baseline_hits=int(p[baseline].sum()),
                    candidate_hits=int(p[candidate].sum()), difference=float(diff.mean()),
                    ci_low=float(ci[0]), ci_high=float(ci[1]),
                    gained=int(((p[baseline] == 0) & (p[candidate] == 1)).sum()),
                    lost=int(((p[baseline] == 1) & (p[candidate] == 0)).sum())))
    return pd.DataFrame(result)


def main():
    OUT.mkdir(exist_ok=True)
    sources = {str(p.relative_to(ROOT)): dict(bytes=p.stat().st_size, sha256=sha(p)) for p in PATHS.values()}
    manifest = OUT/'input_manifest.json'
    if manifest.exists():
        assert json.loads(manifest.read_text()) == sources
    else:
        save(manifest, sources)
    op = pd.read_parquet(PATHS['operating'])
    op = op[op.candidate.eq('current_A') & op.race_date.ge('2024-01-01') & op.venue_code.isin(['SEOUL', 'BUSAN'])].copy()
    z = op.race_id.str.extract(r'RACE:(SEOUL|BUSAN):(\d{8}):(\d+)')
    assert z.notna().all().all()
    op['race_key'] = z[0].map({'SEOUL': '1', 'BUSAN': '3'})+':'+z[1]+':'+z[2].astype(int).astype(str)
    dynamic = pd.read_parquet(PATHS['dynamic'])
    base = dynamic[dynamic.variant.eq('state_gbm')].copy()
    assert len(base) == 50754 and base.race_key.nunique() == 4799
    assert not base.duplicated(['race_key', 'horse_id']).any()
    flags = pd.read_parquet(PATHS['flags'])
    check = base.merge(flags[['race_key', 'program_no', 'horse_id', 'normal_finisher']],
        on=['race_key', 'program_no', 'horse_id'], validate='1:1')
    assert len(check) == len(base) and check.loc[check.outcome.between(1, 3), 'normal_finisher'].all()
    a = op.groupby('race_key').hr_no.agg(lambda x: tuple(sorted(x.astype(str))))
    b = base.groupby('race_key').horse_id.agg(lambda x: tuple(sorted(x.astype(str))))
    coverage = a.to_frame('operating').join(b.to_frame('research'), how='outer')
    overlap = coverage.dropna()
    identical = set(overlap[overlap.operating.eq(overlap.research)].index)
    common = set(overlap.index)
    assert len(identical) == 4133 and len(common) == 4769
    assert all(set(row.research).issubset(set(row.operating)) for row in overlap.itertuples())
    ids = base[['race_key', 'horse_id', 'program_no', 'outcome']]
    op = op.rename(columns={'hr_no': 'horse_id', 'probability': 'top3'})
    op = op.merge(ids, on=['race_key', 'horse_id'], validate='1:1')
    assert op.label.eq(op.outcome.between(1, 3).astype(int)).all()
    assert len(op) == len(base[base.race_key.isin(common)])
    prior = pd.read_parquet(PATHS['old']).query("variant=='full103'").copy()
    assert len(prior) == len(base)
    risk = pd.read_parquet(PATHS['risk_races'])
    rr = pd.read_parquet(PATHS['risk_runners'])
    rr = rr.merge(risk[['race_key', 'base_axis_probability', 'policy_lambda', 'model_risk']],
        on='race_key', how='inner', validate='m:1')
    newp = (1-rr.policy_lambda)*rr.base_axis_probability+rr.policy_lambda*(1-rr.model_risk)
    rr['top3'] = rr.given_axis_in*newp+rr.given_axis_out*(1-newp)
    assert len(rr) == len(base)
    assert np.max(np.abs(rr.groupby('race_key').top3.sum()-3)) < 1e-9
    models = {'operating_A_v5': op, 'full103': prior, 'state_gbm118': base,
        'state_joint118': dynamic[dynamic.variant.eq('state_joint')].copy(),
        'axis_failure_selected': rr}
    metric = pd.read_parquet(PATHS['dynamic_metrics'])
    saved_axes = {(x.variant, x.race_key): x.axis_program_no for x in metric.itertuples()}
    risk_axes = risk.set_index('race_key').selected_program_no.to_dict()
    records = []
    checks = 0
    for model, rows in models.items():
        for key, g in rows.groupby('race_key', sort=False):
            scopes = ['research_full'] if model != 'operating_A_v5' else []
            if key in common:
                scopes.append('matched_starters_sensitivity')
            if key in identical:
                scopes.append('identical_roster')
            row = score(g, model, scopes[0])
            if model in ['state_gbm118', 'state_joint118']:
                oldname = 'state_gbm' if model == 'state_gbm118' else 'state_joint'
                assert row['axis'] == saved_axes[(oldname, key)]
                checks += 1
            if model == 'axis_failure_selected':
                assert row['axis'] == risk_axes[key]
                checks += 1
            records.extend([{**row, 'scope': scope} for scope in scopes])
    frame = pd.DataFrame(records)
    frame.to_parquet(OUT/'race_results.parquet', index=False, compression='zstd')
    summary = aggregate(frame)
    summary.to_csv(OUT/'summary.csv', index=False)
    contrasts = paired(frame)
    contrasts.to_csv(OUT/'paired_differences.csv', index=False)
    coverage_report = pd.DataFrame({
        'operating_size': coverage.operating.map(lambda x: len(x) if isinstance(x, tuple) else None),
        'research_size': coverage.research.map(lambda x: len(x) if isinstance(x, tuple) else None),
        'identical': coverage.index.isin(identical),
        'common': coverage.index.isin(common),
    })
    coverage_report.to_csv(OUT/'cohort_coverage.csv', index_label='race_key')
    save(OUT/'verification.json', dict(status='passed', new_models=0, sources_checked=len(sources),
        identical_roster_races=len(identical), common_races=len(common), research_races=4799,
        source_saved_axes_checked=checks, ticket_enumeration_checks=len(frame),
        operating_label_disagreements=0, risk_probability_sum_max_error=float(np.max(np.abs(rr.groupby('race_key').top3.sum()-3))),
        no_current_2026_weights_applied_to_past=True,
        no_new_training=True, production_changed=False, independent_future_test=False))
    for name, expected in sources.items():
        assert sha(ROOT/name) == expected['sha256'], name
    print(summary[(summary.scope.eq('identical_roster')) & summary.subgroup.eq('all')].to_string(index=False))
    print(contrasts[(contrasts.scope.eq('identical_roster')) & contrasts.subgroup.eq('all')].to_string(index=False))


if __name__ == '__main__':
    main()

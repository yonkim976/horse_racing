"""Read frozen predictions; compare only identical complete 2026 fields and labels."""
from pathlib import Path
from itertools import combinations, permutations
from functools import lru_cache
import hashlib
import json
import sys

import numpy as np
import pandas as pd
from scipy.special import logsumexp

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LEGACY = ROOT / 'data/research/jeju_native_transition_holdout_v13_20260916'
NEW = HERE.parent / '20261009_field_relative_ability_v1/outputs'
DATA = ROOT / 'data/research/jeju_native_top3_dataset_v1_20260915_r2'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


@lru_cache(maxsize=16)
def layout(n):
    sets = np.array(list(combinations(range(n), 3)), int)
    orders = sets[:, np.array(list(permutations(range(3))), int)].reshape(-1, 3)
    return sets, orders


def pl_sets(z):
    """Direct sequential PL probability for each order, then sum its six permutations."""
    sets, orders = layout(len(z))
    weights = np.exp(z - max(z))
    a, b, c = weights[orders].T
    total = weights.sum()
    ordered = a / total * b / (total - a) * c / (total - a - b)
    q = ordered.reshape(-1, 6).sum(axis=1)
    assert np.isclose(q.sum(), 1, atol=1e-12)
    p = np.bincount(sets.ravel(), weights=np.repeat(q, 3), minlength=len(z))
    return sets, q, p


def bootstrap(g, variant, metric):
    a = g[g.variant.eq(variant)].set_index('race_id')
    b = g[g.variant.eq('HY_R_FORM')].set_index('race_id').loc[a.index]
    diff = pd.DataFrame({'date': a.race_date, 'd': a[metric] - b[metric]})
    daily = diff.groupby('date').d.agg(['sum', 'size'])
    rng = np.random.default_rng(20261009)
    ix = rng.integers(0, len(daily), size=(5000, len(daily)))
    v = daily['sum'].to_numpy()[ix].sum(axis=1) / daily['size'].to_numpy()[ix].sum(axis=1)
    return dict(variant=variant, metric=metric, delta=float(diff.d.mean()),
                lo=float(np.quantile(v, .025)), hi=float(np.quantile(v, .975)),
                races=len(a), days=len(daily), resamples=5000)


def main():
    out = HERE / 'outputs'
    out.mkdir(exist_ok=False)
    sources = [LEGACY / n for n in ['horse_predictions.parquet', 'race_predictions.parquet',
               'frozen_scores.parquet', 'protocol.json', 'prediction_lock.json', 'split_dates.json']]
    sources += [DATA / 'races.parquet', DATA / 'entries.parquet']
    sources += [NEW / n for n in ['runner_predictions.parquet', 'race_metrics.csv', 'six_combinations.csv',
                                'J0_2026/meta.json', 'R1_2026/meta.json']]
    protected = [ROOT / 'jeju/data/jeju_native_core.sqlite3', ROOT / 'jeju/models/current/HY_R_FORM.pkl',
                 ROOT / 'config/prediction_model_registry.json']
    before = {str(p.relative_to(ROOT)): dict(sha256=sha(p), bytes=p.stat().st_size)
              for p in sources + protected + [Path(__file__).resolve()]}
    save(out / 'source_lock.json', before)
    h = pd.read_parquet(LEGACY / 'horse_predictions.parquet')
    h = h[h.model.eq('HY_R_FORM')].copy()
    frozen = pd.read_parquet(LEGACY / 'frozen_scores.parquet')
    frozen = frozen[frozen.model.eq('HY_R_FORM')].set_index('entry_id').loc[h.entry_id]
    for col in ['score', 'beta', 'order_score', 'beta_order']:
        assert np.array_equal(h[col].to_numpy(), frozen[col].to_numpy()), col
    races = pd.read_parquet(DATA / 'races.parquet').set_index('race_id')
    h['race_date'] = h.event_date.astype(str)
    h['key'] = [f'{d}_2_{int(races.loc[r, "event_number"])}' for d, r in zip(h.race_date, h.race_id)]
    entries = pd.read_parquet(DATA / 'entries.parquet').set_index('entry_id')
    h['horse_number'] = entries.loc[h.entry_id, 'horse_number'].to_numpy()
    p = pd.read_parquet(NEW / 'runner_predictions.parquet')
    p = p[p.year.eq(2026)].copy()
    baseline = p[p.variant.eq('J0')]
    old_groups = {k: g for k, g in h.groupby('key')}
    new_groups = {k: g for k, g in baseline.groupby('race_id')}
    ledger = []
    common = []
    for key in sorted(old_groups.keys() | new_groups.keys()):
        a, b = old_groups.get(key), new_groups.get(key)
        reason = 'matched'
        if a is None:
            reason = 'new_only'
        elif b is None:
            reason = 'operating_only'
        elif set(a.horse_id) != set(b.horse_id):
            reason = 'horse_set_mismatch'
        else:
            aa = a.set_index('horse_id').sort_index()
            bb = b.set_index('horse_id').loc[aa.index]
            if not np.array_equal(aa.official_top3.to_numpy(int), bb.y.to_numpy(int)):
                reason = 'label_mismatch'
            elif not np.array_equal(aa.horse_number.to_numpy(int), bb.horse_number.to_numpy(int)):
                reason = 'number_mismatch'
            elif not np.array_equal(aa.distance_m.to_numpy(int), bb.distance_m.to_numpy(int)):
                reason = 'distance_mismatch'
        ledger.append(dict(race_id=key, reason=reason, operating_n=0 if a is None else len(a),
                           new_n=0 if b is None else len(b)))
        if reason == 'matched':
            common.append(key)
    pd.DataFrame(ledger).to_csv(out / 'race_alignment.csv', index=False)
    metrics = pd.read_csv(NEW / 'race_metrics.csv')
    tickets = pd.read_csv(NEW / 'six_combinations.csv')
    old_race = pd.read_parquet(LEGACY / 'race_predictions.parquet')
    old_race = old_race[old_race.model.eq('HY_R_FORM')].set_index('race_id')
    rr, pp, tt = [], [], []
    for key in common:
        a = old_groups[key].sort_values('horse_id', kind='stable')
        n = len(a)
        y = a.official_top3.to_numpy(int)
        assert y.sum() == 3 and not a.boundary_tie.any()
        sets, q, pr = pl_sets(a.score.to_numpy(float) * a.beta.to_numpy(float))
        assert np.allclose(pr, a.pl_place_probability, atol=1e-12, rtol=0)
        assert np.isclose(pr.sum(), 3, atol=1e-12)
        # Production tie convention: score-tied horse IDs ascending; set IDs ascending.
        rank = np.argsort(-a.score.to_numpy(), kind='stable')
        best = np.argsort(-q, kind='stable')[:6]
        truth = set(np.flatnonzero(y))
        hits = [int(set(sets[j]) == truth) for j in best]
        pc = np.clip(pr, 1e-12, 1-1e-12)
        ll = -y*np.log(pc) - (1-y)*np.log1p(-pc)
        br = (pr-y)**2
        old = old_race.loc[a.race_id.iloc[0]]
        assert np.isclose(br.mean(), old.place_brier, atol=1e-12)
        assert np.isclose(ll.mean(), old.place_logloss, atol=1e-12)
        assert bool(hits[0]) == bool(old.set_hit)
        assert a.horse_id.iloc[rank[0]] == old.pick_horse_id
        rr.append(dict(race_id=key, race_date=a.race_date.iloc[0], distance_m=int(a.distance_m.iloc[0]),
            field_n=n, variant='HY_R_FORM', brier=float(br.mean()), log_loss=float(ll.mean()),
            pick_hit=int(y[rank[0]]), top3_all3=int(truth <= set(rank[:3])),
            top5_all3=int(truth <= set(rank[:5])), top5_capture=len(truth & set(rank[:5]))/3,
            six_combo_hit=int(any(hits))))
        for i, row in enumerate(a.to_dict('records')):
            pp.append(dict(race_id=key, race_date=row['race_date'], horse_id=row['horse_id'],
                horse_number=int(row['horse_number']), variant='HY_R_FORM', y=int(y[i]),
                p_top3=float(pr[i]), brier=float(br[i]), log_loss=float(ll[i])))
        for k, j in enumerate(best, 1):
            tt.append(dict(race_id=key, variant='HY_R_FORM', selection_rank=k,
                numbers=','.join(map(str, sorted(a.horse_number.iloc[sets[j]].astype(int)))),
                probability=float(q[j]), hit=hits[k-1]))
        for v in ['J0', 'R1']:
            b = p[p.race_id.eq(key) & p.variant.eq(v)].sort_values('horse_number', kind='stable')
            assert set(b.horse_id) == set(a.horse_id)
            assert np.isclose(b.p_top3.sum(), 3, atol=1e-12)
            row = metrics[metrics.race_id.eq(key) & metrics.variant.eq(v)].iloc[0]
            rank_new = np.argsort(-b.score.to_numpy(), kind='stable')
            rr.append(dict(race_id=key, race_date=row.race_date, distance_m=int(row.distance_m),
                field_n=n, variant=v, pick_hit=int(b.y.iloc[rank_new[0]]),
                **{c:float(row[c]) for c in ['brier','log_loss','top3_all3','top5_all3','top5_capture','six_combo_hit']}))
            pp.extend(b[['race_id','race_date','horse_id','horse_number','variant','y','p_top3','brier','log_loss']].to_dict('records'))
            tt.extend(tickets[tickets.race_id.eq(key) & tickets.variant.eq(v)].to_dict('records'))
    result = pd.DataFrame(rr)
    runner = pd.DataFrame(pp)
    combo = pd.DataFrame(tt)
    assert not result.duplicated(['race_id','variant']).any()
    assert not runner.duplicated(['race_id','horse_id','variant']).any()
    assert result.groupby('variant').size().nunique() == 1
    cols = ['brier','log_loss','pick_hit','top3_all3','top5_all3','top5_capture','six_combo_hit']
    for (key, v), g in runner.groupby(['race_id','variant']):
        saved = result[result.race_id.eq(key) & result.variant.eq(v)].iloc[0]
        for c in ['brier','log_loss']:
            assert np.isclose(g[c].mean(), saved[c], atol=1e-12)
        t = combo[combo.race_id.eq(key) & combo.variant.eq(v)]
        assert len(t) == min(6, len(layout(len(g))[0]))
        assert int(t.hit.max()) == int(saved.six_combo_hit)
    for name, frame in [('race_metrics.csv',result), ('runner_predictions.parquet',runner),
                        ('six_combinations.csv',combo)]:
        frame.to_parquet(out/name,index=False) if name.endswith('parquet') else frame.to_csv(out/name,index=False)
    summary = result.groupby('variant')[cols].mean().reset_index()
    summary['races'] = len(common)
    summary.to_csv(out/'summary.csv',index=False)
    ci = pd.DataFrame([bootstrap(result,v,c) for v in ['J0','R1'] for c in cols])
    ci.to_csv(out/'paired_differences.csv',index=False)
    result.groupby(['distance_m','variant'])[cols].agg(['mean','size']).to_csv(out/'distance_metrics.csv')
    verify = dict(passed=True, common_races=len(common), runners_per_variant=len(runner)//3,
        dates=result.race_date.nunique(), first_date=result.race_date.min(), last_date=result.race_date.max(),
        alignment_counts=pd.DataFrame(ledger).reason.value_counts().to_dict(),
        operating_predictions_scores_match_frozen=True, operating_PL_marginals_recomputed=True,
        stored_operating_pick_set_brier_logloss_reproduced=True, all_labels_ids_numbers_distances_match=True,
        all_complete_fields_retained=True, fits=0, calibration_fits=0,
        native_distributions_preserved=True, probability_and_ticket_sums_verified=True,
        new_independent_holdout=False, protected_unchanged=True)
    for path, info in before.items():
        assert sha(ROOT/path) == info['sha256'], path
    save(out/'verification.json',verify)
    print(json.dumps(verify,ensure_ascii=False,indent=2))
    print(summary.to_string(index=False))
    print(ci.to_string(index=False))


if __name__ == '__main__':
    main()

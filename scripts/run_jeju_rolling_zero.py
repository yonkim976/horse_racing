"""Past-only quarterly predictions for annual zero-history place calibration."""
import json
import pickle
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar
from scipy.special import logit

from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from horse_racing.analysis.jeju_place_calibration import PositivePlattCalibrator
from horse_racing.analysis.jeju_zero_history_calibration import ZeroHistoryCalibrator
from scripts.run_jeju_place_objective import ROOT, DATA, OLD, ANN, load_frame, base_prob
from scripts.run_jeju_annual_revalidation import sha
from scripts.run_jeju_transition_holdout import data_frame
from scripts.run_jeju_context_experiment import rank_scores
from scripts.run_jeju_top3_experiment import race_groups, order_loss

OUT = ROOT / 'data/research/jeju_rolling_zero_20260920'
PREV = ROOT / 'data/research/jeju_place_objective_20260919'
PLAN = ROOT / 'docs/JEJU_ROLLING_ZERO_PROTOCOL_2026-09-20.md'
ARMS = ['BASE', 'Q4_ZERO', 'OOF_GLOBAL', 'OOF_ZERO']


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False))


def quarter_start(year, quarter):
    index = year * 4 + quarter - 1
    return date(index // 4, (index % 4) * 3 + 1, 1)


def rolling_parts(frame, year, quarter):
    a, b, c, d = [quarter_start(year, quarter + shift) for shift in [-2, -1, 0, 1]]
    intervals = {'fit': (date(2018, 8, 31), a), 'tune': (a, b), 'calibration': (b, c), 'prediction': (c, d)}
    parts = {k: frame.filter((pl.col('event_date') >= lo) & (pl.col('event_date') < hi)).sort('race_id', 'horse_id') for k, (lo, hi) in intervals.items()}
    parts['prediction'] = parts['prediction'].with_columns(pl.lit(None, dtype=pl.Float64).alias('finish_position'), pl.lit(None, dtype=pl.Int64).alias('label_top3'))
    return parts


def main():
    OUT.mkdir(exist_ok=False)
    (OUT / 'bundles').mkdir()
    oldpath = OLD / 'bundles/frozen_2026__HY_R_FORM.pkl'
    old = pickle.loads(oldpath.read_bytes())
    features = old['rank_bundle']['features']
    params = json.loads((OLD / 'protocol.json').read_text())['rank_params']
    inputs = [oldpath, PREV / 'frozen_probabilities.parquet', DATA / 'horse_states.parquet', DATA / 'labels.parquet', DATA / 'races.parquet', *sorted(ANN.glob('bundles/*__BASE.pkl'))]
    save('protocol.json', dict(created_at=datetime.now(UTC).isoformat(), plan_sha256=sha(PLAN), script_sha256=sha(Path(__file__)), features=features, params=params, arms=ARMS, max_fits=24, input_hashes={str(p.relative_to(ROOT)): sha(p) for p in inputs}))
    frame = load_frame()
    _, truth, _ = data_frame()
    meta = pl.read_parquet(DATA / 'races.parquet').select('race_id', 'boundary_tie')
    bounds, ledger, pools = [], [], []
    for year in [2023, 2024, 2025]:
        for quarter in [1, 2, 3, 4]:
            tag = f'{year}Q{quarter}'
            parts = rolling_parts(frame, year, quarter)
            for left, right in [('fit', 'tune'), ('tune', 'calibration'), ('calibration', 'prediction')]:
                assert parts[left]['event_date'].max() < parts[right]['event_date'].min()
            for role, f in parts.items():
                bounds.append(dict(fold=tag, role=role, first=f['event_date'].min(), last=f['event_date'].max(), rows=len(f), races=f['race_id'].n_unique()))
            pre = FitPreprocessor().fit(parts['fit'], features)
            xs = {k: pre.transform(v) for k, v in parts.items() if k in ['fit', 'tune']}
            ys = {k: np.where(np.isfinite(parts[k]['finish_position'].to_numpy()) & (parts[k]['finish_position'].to_numpy() <= 3), 4-parts[k]['finish_position'].to_numpy(), 0).astype(int) for k in xs}
            groups = {k: race_groups(parts[k], truth) for k in ['fit', 'tune', 'calibration']}
            models = []
            for seed in [17, 43]:
                m = lgb.LGBMRanker(objective='lambdarank', label_gain=[0, 1, 3, 7], random_state=seed, verbosity=-1, **params)
                m.fit(xs['fit'], ys['fit'], group=[hi-lo for lo, hi, _ in groups['fit']], eval_set=[(xs['tune'], ys['tune'])], eval_group=[[hi-lo for lo, hi, _ in groups['tune']]], eval_at=[3], callbacks=[lgb.early_stopping(30, verbose=False)])
                models.append(m)
                ledger.append(dict(fold=tag, seed=seed, best_iteration=int(m.best_iteration_)))
                save('fit_ledger.json', ledger)
            bundle = dict(features=features, preprocessor=pre, models=models)
            raw = rank_scores(bundle, parts['calibration'])
            opt = minimize_scalar(lambda x: order_loss(raw, groups['calibration'], np.exp(x)), bounds=(-4, 4), method='bounded', options={'xatol': 1e-5})
            assert opt.success
            bundle['beta'] = float(np.exp(opt.x))
            (OUT / f'bundles/{tag}.pkl').write_bytes(pickle.dumps(bundle))
            f = parts['prediction']
            pools.append(f.select('entry_id', 'race_id', 'horse_id', 'event_date', 'starts_pre', 'field_size').with_columns(pl.lit(tag).alias('fold'), pl.Series('p', base_prob(bundle, f))))
            print(tag, 'complete', flush=True)
    save('boundaries.json', bounds)
    pool = pl.concat(pools)
    assert pool['entry_id'].n_unique() == len(pool)
    pool.write_parquet(OUT / 'frozen_oof_probabilities.parquet')
    save('oof_lock.json', dict(created_at=datetime.now(UTC).isoformat(), files={str(p.relative_to(OUT)): sha(p) for p in [OUT / 'protocol.json', OUT / 'frozen_oof_probabilities.parquet', *sorted((OUT / 'bundles').glob('*.pkl'))]}))
    # Only now join outcome labels of historical out-of-sample predictions.
    labels = pl.read_parquet(DATA / 'labels.parquet').select('entry_id', 'label_top3')
    pool = pool.join(labels, on='entry_id', validate='1:1').join(meta, on='race_id', validate='m:1').filter(~pl.col('boundary_tie'))
    frozen = pl.read_parquet(PREV / 'frozen_probabilities.parquet')
    cal_ledger, outputs = [], []
    for year in [2024, 2025, 2026]:
        past = pool.filter(pl.col('event_date').dt.year() == year - 1)
        ev = frozen.filter(pl.col('year') == year)
        assert past['event_date'].max() < ev['event_date'].min()
        x, z, y, w = logit(np.clip(past['p'].to_numpy(), 1e-8, 1-1e-8)), (past['starts_pre'].to_numpy() == 0).astype(int), past['label_top3'].to_numpy(), 1/past['field_size'].to_numpy()
        g = PositivePlattCalibrator().fit(x, y, w)
        c = ZeroHistoryCalibrator().fit(x, z, y, w)
        assert g.success_ and c.success_
        xe, ze = logit(np.clip(ev['p_BASE'].to_numpy(), 1e-8, 1-1e-8)), (ev['starts_pre'].to_numpy() == 0).astype(int)
        outputs.append(ev.select('entry_id', 'race_id', 'horse_id', 'event_date', 'starts_pre', 'field_size', 'year', 'p_BASE', pl.col('p_BASE_ZERO').alias('p_Q4_ZERO')).with_columns(pl.Series('p_OOF_GLOBAL', g.predict(xe)), pl.Series('p_OOF_ZERO', c.predict(xe, ze))))
        (OUT / f'bundles/{year}__CAL.pkl').write_bytes(pickle.dumps(dict(global_cal=g, zero_cal=c)))
        cal_ledger.append(dict(year=year, races=past['race_id'].n_unique(), rows=len(past), zero_entries=int(z.sum()), first=past['event_date'].min(), last=past['event_date'].max(), global_params=[g.log_scale_, g.intercept_], zero_params=c.params_.tolist(), success=True, fallback=c.fallback_))
    save('calibration_ledger.json', cal_ledger)
    scores = pl.concat(outputs)
    scores.write_parquet(OUT / 'frozen_probabilities.parquet')
    save('prediction_lock.json', dict(created_at=datetime.now(UTC).isoformat(), files={str(p.relative_to(OUT)): sha(p) for p in [OUT / 'frozen_probabilities.parquet', *sorted((OUT / 'bundles').glob('*__CAL.pkl'))]}))
    evaluate(scores.join(labels, on='entry_id', validate='1:1').join(meta, on='race_id', validate='m:1'))


def evaluate(scores):
    races, horses = [], []
    for (rid,), part in scores.partition_by('race_id', as_dict=True).items():
        part = part.sort('horse_id')
        y, zero = part['label_top3'].to_numpy(), part['starts_pre'].to_numpy() == 0
        for name in ARMS:
            p = part['p_'+name].to_numpy()
            idx = int(np.argmax(p))
            races.append(dict(year=int(part['year'][0]), model=name, race_id=rid, event_date=part['event_date'][0], pick_horse_id=part['horse_id'][idx], pick_hit=bool(y[idx]), pick_zero=bool(zero[idx]), boundary_tie=part['boundary_tie'][0], brier=float(np.mean((p-y)**2))))
            horses.extend(dict(entry_id=int(e), year=int(part['year'][0]), model=name, race_id=rid, p=float(pp), y=int(yy), zero=bool(zz), boundary_tie=part['boundary_tie'][0]) for e, pp, yy, zz in zip(part['entry_id'], p, y, zero, strict=True))
    r, h = pl.from_dicts(races), pl.from_dicts(horses)
    r.write_parquet(OUT / 'race_predictions.parquet')
    h.write_parquet(OUT / 'horse_predictions.parquet')
    summary, experience = [], []
    for year in [2024, 2025, 2026, 'ALL']:
        for name in ARMS:
            rr = [a for a in races if a['model'] == name and (year == 'ALL' or a['year'] == year)]
            summary.append(dict(year=year, model=name, races=len(rr), hits=sum(a['pick_hit'] for a in rr), accuracy=float(np.mean([a['pick_hit'] for a in rr])), brier=float(np.mean([a['brier'] for a in rr if not a['boundary_tie']]))))
            for zero in [False, True]:
                hh = [a for a in horses if a['model'] == name and a['zero'] == zero and not a['boundary_tie'] and (year == 'ALL' or a['year'] == year)]
                experience.append(dict(year=year, model=name, zero=zero, entries=len(hh), predicted=float(np.mean([a['p'] for a in hh])), actual=float(np.mean([a['y'] for a in hh])), brier=float(np.mean([(a['p']-a['y'])**2 for a in hh]))))
    save('summary.json', summary)
    save('horse_experience.json', experience)
    save('quarters.json', r.with_columns(pl.col('event_date').dt.quarter().alias('quarter')).group_by('year', 'quarter', 'model').agg(pl.len().alias('races'), pl.col('pick_hit').sum()).sort('year', 'quarter', 'model').to_dicts())
    comparisons, changes = [], []
    for reference in ['BASE', 'Q4_ZERO']:
        rng, total_boot, total_n, delta_hits, per_year = np.random.default_rng(17), np.zeros(5000), 0, 0, []
        for year in [2024, 2025, 2026]:
            ref = r.filter((pl.col('year') == year) & (pl.col('model') == reference)).sort('race_id')
            cand = r.filter((pl.col('year') == year) & (pl.col('model') == 'OOF_ZERO')).sort('race_id')
            assert ref['race_id'].to_list() == cand['race_id'].to_list()
            d = cand['pick_hit'].to_numpy().astype(int) - ref['pick_hit'].to_numpy().astype(int)
            days = ref['event_date'].to_numpy()
            unique = np.unique(days)
            counts = np.array([np.sum(days == day) for day in unique])
            totals = np.array([d[days == day].sum() for day in unique])
            ix = rng.integers(0, len(unique), (5000, len(unique)))
            boot = totals[ix].sum(axis=1) / counts[ix].sum(axis=1)
            total_boot += boot * len(ref)
            total_n += len(ref)
            delta_hits += int(d.sum())
            per_year.append(dict(year=year, delta_hits=int(d.sum()), ci95=np.quantile(boot, [.025, .975]).tolist()))
            for a, b in zip(ref.to_dicts(), cand.to_dicts(), strict=True):
                if a['pick_horse_id'] != b['pick_horse_id']:
                    changes.append(dict(reference=reference, year=year, race_id=a['race_id'], event_date=a['event_date'], old_pick=a['pick_horse_id'], new_pick=b['pick_horse_id'], old_hit=a['pick_hit'], new_hit=b['pick_hit'], old_zero=a['pick_zero'], new_zero=b['pick_zero']))
        comparisons.append(dict(reference=reference, candidate='OOF_ZERO', delta_hits=delta_hits, difference=delta_hits/total_n, simultaneous95=np.quantile(total_boot/total_n, [.025/2, 1-.025/2]).tolist(), years=per_year))
    save('primary_comparisons.json', comparisons)
    save('changed_races.json', changes)
    base = comparisons[0]
    promote = all(a['simultaneous95'][0] > 0 for a in comparisons) and sum(a['delta_hits'] > 0 for a in base['years']) >= 2 and base['years'][-1]['delta_hits'] > 0
    save('decision.json', dict(promote_development=bool(promote), production_changed=False, reused_retrospective_data=True))
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    print(json.dumps(comparisons, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

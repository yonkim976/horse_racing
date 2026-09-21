"""Replay temporal predictions, calibrations, labels and one-horse selections."""
import json
import pickle
import numpy as np
import polars as pl
from scipy.special import logit
from scripts.run_jeju_rolling_zero import ROOT, OUT, DATA, PREV, PLAN, ARMS, load_frame, rolling_parts, base_prob, sha, save
from horse_racing.analysis.jeju_zero_history_calibration import objective_gradient


def main():
    protocol = json.loads((OUT / 'protocol.json').read_text())
    assert sha(PLAN) == protocol['plan_sha256']
    for path, expected in protocol['input_hashes'].items():
        assert sha(ROOT / path) == expected
    # Check remaining feature sources against their pre-existing build manifests.
    from scripts.freeze_jeju_transition_protocol import H3, FEAT
    source_checks = []
    for folder, names in [(DATA, ['accepted_orders.parquet', 'fold_assignments.parquet']), (H3, ['features.parquet']), (FEAT, ['features.parquet', 'context_features.parquet'])]:
        manifest = json.loads((folder / 'manifest.json').read_text())
        entries = manifest.get('files', manifest)
        for name in names:
            expected = entries[name]
            if isinstance(expected, dict):
                expected = expected['sha256']
            assert sha(folder / name) == expected
            source_checks.append(str((folder / name).relative_to(ROOT)))
    for file in ['oof_lock.json', 'prediction_lock.json']:
        for path, expected in json.loads((OUT / file).read_text())['files'].items():
            assert sha(OUT / path) == expected
    assert len(json.loads((OUT / 'fit_ledger.json').read_text())) == 24
    frame, total, maxerr = load_frame(), 0, 0.
    oof = pl.read_parquet(OUT / 'frozen_oof_probabilities.parquet')
    assert oof['entry_id'].n_unique() == len(oof)
    for year in [2023, 2024, 2025]:
        for quarter in [1, 2, 3, 4]:
            tag = f'{year}Q{quarter}'
            parts = rolling_parts(frame, year, quarter)
            for a, b in [('fit', 'tune'), ('tune', 'calibration'), ('calibration', 'prediction')]:
                assert parts[a]['event_date'].max() < parts[b]['event_date'].min()
            f = parts['prediction']
            assert f['label_top3'].null_count() == len(f) and f['finish_position'].null_count() == len(f)
            stored = oof.filter(pl.col('fold') == tag).sort('race_id', 'horse_id')
            assert f['entry_id'].to_list() == stored['entry_id'].to_list()
            p = base_prob(pickle.loads((OUT / f'bundles/{tag}.pkl').read_bytes()), f)
            np.testing.assert_allclose(p, stored['p'].to_numpy(), atol=1e-12, rtol=0)
            for part in stored.partition_by('race_id'):
                assert abs(part['p'].sum() - 3) < 1e-10
            maxerr = max(maxerr, float(np.max(np.abs(p-stored['p'].to_numpy()))))
            total += len(f)
    eligible = frame.filter(pl.col('event_date').dt.year().is_in([2023, 2024, 2025]))
    assert set(eligible['entry_id']) == set(oof['entry_id'])
    meta = pl.read_parquet(DATA / 'races.parquet').select('race_id', 'boundary_tie')
    labels = pl.read_parquet(DATA / 'labels.parquet').select('entry_id', 'label_top3')
    pool = oof.join(labels, on='entry_id', validate='1:1').join(meta, on='race_id', validate='m:1').filter(~pl.col('boundary_tie'))
    scores = pl.read_parquet(OUT / 'frozen_probabilities.parquet')
    previous = pl.read_parquet(PREV / 'frozen_probabilities.parquet').sort('entry_id')
    ordered = scores.sort('entry_id')
    assert ordered['entry_id'].to_list() == previous['entry_id'].to_list()
    np.testing.assert_array_equal(ordered['p_BASE'], previous['p_BASE'])
    np.testing.assert_array_equal(ordered['p_Q4_ZERO'], previous['p_BASE_ZERO'])
    gradients = []
    for year in [2024, 2025, 2026]:
        c = pickle.loads((OUT / f'bundles/{year}__CAL.pkl').read_bytes())
        f = scores.filter(pl.col('year') == year)
        past = pool.filter(pl.col('event_date').dt.year() == year-1)
        assert past['event_date'].max() < f['event_date'].min()
        x, z = logit(np.clip(f['p_BASE'].to_numpy(), 1e-8, 1-1e-8)), (f['starts_pre'].to_numpy() == 0).astype(int)
        np.testing.assert_allclose(c['global_cal'].predict(x), f['p_OOF_GLOBAL'], atol=1e-12, rtol=0)
        np.testing.assert_allclose(c['zero_cal'].predict(x, z), f['p_OOF_ZERO'], atol=1e-12, rtol=0)
        loss, gradient = objective_gradient(c['zero_cal'].params_, logit(np.clip(past['p'].to_numpy(), 1e-8, 1-1e-8)), (past['starts_pre'].to_numpy() == 0).astype(int), past['label_top3'].to_numpy(), 1/past['field_size'].to_numpy())
        assert abs(loss-c['zero_cal'].objective_) < 1e-12 and np.max(np.abs(gradient)) < 1e-6
        gradients.append(dict(year=year, max_abs_gradient=float(np.max(np.abs(gradient)))))
    truth = {a['entry_id']: a['label_top3'] for a in labels.to_dicts()}
    rp = pl.read_parquet(OUT / 'race_predictions.parquet')
    hp = pl.read_parquet(OUT / 'horse_predictions.parquet')
    for name in ARMS:
        hh = hp.filter(pl.col('model') == name).sort('entry_id')
        assert hh['entry_id'].to_list() == ordered['entry_id'].to_list()
        np.testing.assert_array_equal(hh['p'], ordered['p_'+name])
        assert hh['y'].to_list() == [truth[e] for e in hh['entry_id']]
    lookup = {(r['race_id'], r['model']): r for r in rp.to_dicts()}
    count = 0
    for (rid,), part in scores.partition_by('race_id', as_dict=True).items():
        part = part.sort('horse_id')
        picks = {}
        for name in ARMS:
            p = part['p_'+name].to_numpy()
            assert np.isfinite(p).all() and ((p > 0) & (p < 1)).all()
            idx = int(np.argmax(p))
            a = lookup[(rid, name)]
            assert a['pick_horse_id'] == part['horse_id'][idx]
            assert a['pick_hit'] == bool(truth[part['entry_id'][idx]])
            y = np.array([truth[e] for e in part['entry_id']])
            assert abs(a['brier'] - np.mean((p-y)**2)) < 1e-12
            picks[name] = a['pick_horse_id']
            count += 1
        assert picks['BASE'] == picks['OOF_GLOBAL']
    for row in json.loads((OUT / 'summary.json').read_text()):
        f = rp.filter(pl.col('model') == row['model'])
        if row['year'] != 'ALL':
            f = f.filter(pl.col('year') == row['year'])
        assert len(f) == row['races'] and f['pick_hit'].sum() == row['hits']
    assert scores['event_date'].max().isoformat() == '2026-09-12'
    save('verification.json', dict(passed=True, oof_probabilities_replayed=total, evaluation_probabilities_checked=len(scores)*4, race_selections_replayed=count, max_oof_absolute_error=maxerr, calibrator_gradients=gradients, input_hashes_unchanged=len(protocol['input_hashes']), additional_source_manifest_checks=source_checks, source_script_hash_matches=sha(ROOT / 'scripts/run_jeju_rolling_zero.py') == protocol['script_sha256']))
    print((OUT / 'verification.json').read_text())


if __name__ == '__main__':
    main()

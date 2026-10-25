"""Independent fixed-mask confidence and date-bootstrap review."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
PAIR = ROOT / 'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet'
QPL = ROOT / 'jeju/research/20261013_pair_qpl_roi_v1/race_returns.csv'
QNL = ROOT / 'jeju/research/20261013_qnl_tla_roi_v1/race_returns.csv'
EDGES = [0, .1, .15, .2, .25, .3, .4, .5, 1]
LABELS = ['[0.00,0.10)', '[0.10,0.15)', '[0.15,0.20)', '[0.20,0.25)',
          '[0.25,0.30)', '[0.30,0.40)', '[0.40,0.50)', '[0.50,1.00]']


def equal(got, want):
    if want is None or pd.isna(want):
        assert pd.isna(got)
    else:
        assert math.isclose(float(got), float(want), rel_tol=0, abs_tol=1e-8), (got, want)


def main():
    full = pd.read_parquet(PAIR)
    p = full.loc[full.selected_jockey_id_candidate.eq(1) & full.evaluation_year.isin([2025, 2026])].copy()
    p = p.set_index('race_id')
    assert len(p) == 1142 and p.index.is_unique
    confidence = p.jockey_id_candidate_calibrated_probability
    assert confidence.between(0, 1).all()
    sources = [pd.read_csv(QPL), pd.read_csv(QNL)]
    references = {}
    for pool, source in zip(['QPL', 'QNL'], sources):
        selected = source.loc[source.selector.eq('jockey_id_candidate')]
        if pool == 'QNL':
            selected = selected.loc[selected.pool.eq('QNL')]
        selected = selected.set_index('race_id').reindex(p.index)
        assert selected.index.is_unique and selected.return_krw.notna().all()
        hit = selected.hit if pool == 'QPL' else selected.exact_hit
        returns = selected.return_krw if pool == 'QPL' else selected.return_krw * 5 // 3
        if pool == 'QNL':
            assert selected.return_krw.mod(3).eq(0).all()
        refs = pd.DataFrame({'date': p.race_date, 'year': p.evaluation_year, 'confidence': confidence,
                            'hit': hit, 'return_krw': returns})
        refs['pair'] = p.horse_i.astype(int).astype(str) + '-' + p.horse_j.astype(int).astype(str)
        refs['bin'] = np.asarray(LABELS)[np.minimum(np.digitize(confidence, EDGES) - 1, 7)]
        references[pool] = refs
    records = pd.read_csv(STUDY / 'race_returns.csv').set_index(['pool', 'race_id'])
    assert len(records) == 2284 and records.index.is_unique
    for pool, refs in references.items():
        got = records.loc[pool].reindex(p.index)
        assert got.selected_pair.equals(refs.pair.rename('selected_pair'))
        assert got.confidence_bin.equals(refs.bin.rename('confidence_bin'))
        for col, expected in [('saved_top3_probability', refs.confidence), ('exact_hit', refs.hit),
                              ('return_krw', refs.return_krw), ('net_krw', refs.return_krw - 10000)]:
            assert np.allclose(got[col], expected, rtol=0, atol=1e-14)
        assert got.stake_krw.eq(10000).all()
    dates = sorted(full.race_date.unique())
    assert len(dates) == 269
    schedule_path = ROOT / 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy'
    assert hashlib.sha256(schedule_path.read_bytes()).hexdigest() == 'd141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd'
    schedule = np.load(schedule_path, allow_pickle=False)
    assert schedule.shape == (2000, 269) and schedule.dtype == np.int32
    weights = np.asarray([np.bincount(draw, minlength=269) for draw in schedule], dtype=np.int64)
    tables = {kind: pd.read_csv(STUDY / f'{kind}_stats.csv') for kind in ['bin', 'threshold']}
    cis = pd.read_csv(STUDY / 'bootstrap_ci.csv').set_index(['scope', 'pool', 'group', 'metric'])
    assert len(cis) == 288 and cis.index.is_unique
    for kind, table in tables.items():
        assert len(table) == 48
        for row in table.itertuples():
            ref = references[row.pool]
            scope = ref if row.scope == 'all' else ref.loc[ref.year.eq(2025 if row.scope == '2025' else 2026)]
            if kind == 'bin':
                part = scope.loc[scope.bin.eq(row.group)]
            else:
                t = 0 if row.group == 'all_baseline' else float(row.group[2:])
                part = scope.loc[scope.confidence.ge(t)]
            n, hits = len(part), int(part.hit.sum())
            returned = int(part.return_krw.sum())
            expected = {'n_races': n, 'scope_races': len(scope),
                'coverage_pct': n / len(scope) * 100, 'coverage_of_all_1142_pct': n / 1142 * 100,
                'race_days': part.date.nunique(), 'hits': hits, 'stake_krw': n * 10000,
                'return_krw': returned, 'net_krw': returned - n * 10000,
                'mean_saved_top3_probability': part.confidence.mean() if n else None,
                'hit_rate_pct': hits / n * 100 if n else None,
                'mean_paid_dividend_odds_on_hit': part.loc[part.hit.eq(1)].return_krw.mean() / 10000 if hits else None,
                'recovery_pct': returned / (n * 10000) * 100 if n else None,
                'net_roi_pct': (returned / (n * 10000) - 1) * 100 if n else None,
                'qpl_hit_minus_mean_probability_pct': (hits / n - part.confidence.mean()) * 100 if n and row.pool == 'QPL' else None}
            for col, value in expected.items():
                equal(getattr(row, col), value)
            ids = pd.Categorical(part.date, categories=dates).codes
            assert (ids >= 0).all()
            dn = np.bincount(ids, minlength=269)
            dh = np.bincount(ids, weights=part.hit, minlength=269)
            dr = np.bincount(ids, weights=part.return_krw, minlength=269)
            bn, bh, br = weights @ dn, weights @ dh, weights @ dr
            valid = bn > 0
            series = {'hit_rate_pct': bh[valid] / bn[valid] * 100,
                      'recovery_pct': br[valid] / (bn[valid] * 10000) * 100,
                      'net_roi_pct': br[valid] / (bn[valid] * 10000) * 100 - 100}
            for metric, vals in series.items():
                ci = cis.loc[(row.scope, row.pool, f'{kind}:{row.group}', metric)]
                assert ci.valid_draws == int(valid.sum())
                assert ci.empty_draws_dropped == int((~valid).sum())
                limits = np.quantile(vals, [.025, .975]) if len(vals) else [None, None]
                equal(ci.ci_low_pct, limits[0])
                equal(ci.ci_high_pct, limits[1])
    report = json.loads((STUDY / 'REPORT.json').read_text())
    for path, digest in report['source_sha256'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    for path, digest in report['output_sha256'].items():
        assert hashlib.sha256((STUDY / path).read_bytes()).hexdigest() == digest
    receipt = {'status': 'PASS', 'race_pool_rows_verified': len(records),
        'bin_and_threshold_rows_verified': 96, 'bootstrap_interval_rows_verified': len(cis),
        'input_and_output_hashes_match': True, 'saved_global_dates_and_draws_reused': True,
        'qnl_stake_scaling_exact': True, 'model_refit': False,
        'report_sha256': hashlib.sha256((STUDY / 'REPORT.json').read_bytes()).hexdigest()}
    (STUDY / 'ROOT_REVIEW.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()

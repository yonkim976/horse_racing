"""Root recomputation from locked choices and original runner labels; no selector imports."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = HERE.parent / '20261025_top5_set_selection_v1'
BASE = ROOT / 'jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet'
BOOT = ROOT / 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert sha(BASE) == 'c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1'
    assert sha(BOOT) == 'd141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd'
    receipt = json.loads((STUDY / 'outputs/selection_receipt.json').read_text())
    choices_path = STUDY / 'outputs/selections.jsonl'
    assert sha(choices_path) == receipt['selection_artifact']['sha256']
    choices = [json.loads(line) for line in choices_path.read_text().splitlines()]
    assert len(choices) == 1779 == len({c['race_id'] for c in choices})
    choices = {c['race_id']: c for c in choices}
    raw = pd.read_parquet(BASE, columns=['race_id', 'race_date', 'distance_m', 'year',
                                        'horse_id', 'horse_number', 'score', 'y'])
    rows = []
    for race_id, g in raw.groupby('race_id', sort=True):
        c = choices[race_id]
        truth = set(g.loc[g.y.eq(1), 'horse_id'].astype(str))
        assert len(truth) == 3 and set(g.y) <= {0, 1}
        base = g.sort_values(['score', 'horse_number'], ascending=[False, True]).iloc[:5]
        assert set(base.horse_id.astype(str)) == set(c['baseline_horse_ids'])
        b = set(c['baseline_horse_ids']); p = set(c['candidate_horse_ids'])
        assert len(b) == len(p) == 5 and p <= set(g.horse_id.astype(str))
        assert int(c['distance_m']) == int(g.distance_m.iloc[0])
        assert c['race_date'] == str(g.race_date.iloc[0])
        bc, pc = len(b & truth), len(p & truth)
        rows.append(dict(race_id=race_id, race_date=c['race_date'],
                         distance_m=int(c['distance_m']), year=int(g.year.iloc[0]),
                         baseline_captured=bc, candidate_captured=pc,
                         baseline_hit=int(bc == 3), candidate_hit=int(pc == 3),
                         delta=int(pc == 3) - int(bc == 3), changed=b != p))
    frame = pd.DataFrame(rows)
    dates = sorted(frame.race_date.unique())
    schedule = np.load(BOOT, allow_pickle=False)
    assert len(dates) == 269 and schedule.shape == (2000, 269)
    assert schedule.min() == 0 and schedule.max() == 268

    def result(g):
        daily = g.groupby('race_date').delta.agg(['sum', 'size']).reindex(dates, fill_value=0)
        numerators = daily['sum'].to_numpy()[schedule].sum(axis=1)
        denominators = daily['size'].to_numpy()[schedule].sum(axis=1)
        valid = denominators > 0
        delta_draws = numerators[valid] / denominators[valid]
        ci = np.quantile(delta_draws, [.025, .975], method='linear')
        n = len(g); bh = g.baseline_hit.eq(1); ph = g.candidate_hit.eq(1)
        return dict(races=n, baseline_hits=int(bh.sum()), candidate_hits=int(ph.sum()),
                    baseline_percent=100*float(bh.mean()), candidate_percent=100*float(ph.mean()),
                    delta_pp=100*float(g.delta.mean()), ci95_pp=(100*ci).tolist(),
                    valid_bootstrap_draws=int(valid.sum()),
                    candidate_only=int((ph & ~bh).sum()), baseline_only=int((bh & ~ph).sum()),
                    both_hit=int((bh & ph).sum()), both_miss=int((~bh & ~ph).sum()),
                    changed_sets=int(g.changed.sum()),
                    baseline_missing_counts={str(i): int(g.baseline_captured.eq(3-i).sum()) for i in range(4)},
                    candidate_missing_counts={str(i): int(g.candidate_captured.eq(3-i).sum()) for i in range(4)},
                    baseline_mean_captured=float(g.baseline_captured.mean()),
                    candidate_mean_captured=float(g.candidate_captured.mean()),
                    primary_gate_passed=bool(g.delta.mean() > 0 and ci[0] > 0))

    primary = frame[frame.distance_m.isin([900, 1000, 1110, 1200])]
    assert len(primary) == 1503
    result_all = dict(passed=True, new_fits=0, selection_sha256=sha(choices_path),
                      primary=result(primary), full=result(frame),
                      primary_by_year={str(y): result(g) for y, g in primary.groupby('year')},
                      full_by_distance={str(d): result(g) for d, g in frame.groupby('distance_m')})
    with (HERE / 'ROOT_OUTCOME_RECOMPUTATION.json').open('x') as f:
        json.dump(result_all, f, indent=2); f.write('\n')
    print(json.dumps({k: v for k, v in result_all.items() if k in ['passed', 'primary', 'full']}, indent=2))


if __name__ == '__main__':
    main()

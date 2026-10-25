"""Read-only supervisory checks; independent of the experiment loader."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
STYLE = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs'
HISTORY = ROOT / 'jeju/research/20261011_pair_top3_oos_expansion_v1/outputs'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    fp = STYLE / 'features.parquet'
    assert sha(fp) == '036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f'
    f = pd.read_parquet(fp, columns=[
        'api_record_id', 'race_id', 'race_date', 'year', 'horse_id', 'horse_number',
        'finish_position', 'field_n', 'history_cutoff', 'latest_history_date'])
    assert len(f) == 52155 and f.race_id.nunique() == 5206
    assert not f.api_record_id.duplicated().any()
    assert not f.duplicated(['race_id', 'horse_id']).any()
    assert not f.duplicated(['race_id', 'horse_number']).any()
    d = pd.to_datetime(f.race_date)
    cut = pd.to_datetime(f.history_cutoff)
    assert ((d - cut).dt.days == 2).all()
    latest = pd.to_datetime(f.latest_history_date, errors='coerce')
    assert (latest.isna() | latest.le(cut)).all()
    for _, group in f.groupby('race_id', sort=False):
        n = len(group)
        assert group.race_date.nunique() == group.year.nunique() == 1
        assert group.field_n.eq(n).all()
        assert sorted(group.finish_position.tolist()) == list(range(1, n + 1))
    refs = [{'path': str(fp.relative_to(ROOT)), 'sha256': sha(fp), 'size_bytes': fp.stat().st_size}]
    providers = []
    for role, years in [('calibration', range(2019, 2026)), ('evaluation', range(2024, 2027))]:
        for year in years:
            fold = year + 1 if role == 'calibration' else year
            base = HISTORY if fold < 2024 else STYLE
            folder = base / f'F1_STYLE6_{fold}'
            mp = folder / 'meta.json'
            sp = folder / f'{role}_scores.parquet'
            meta = json.loads(mp.read_text())
            assert sha(sp) == meta[f'{role}_scores_sha256']
            s = pd.read_parquet(sp)
            assert list(s.columns) == ['api_record_id', 'score']
            assert not s.api_record_id.duplicated().any() and np.isfinite(s.score).all()
            target = f.loc[f.year.eq(year)]
            assert set(s.api_record_id) == set(target.api_record_id)
            assert pd.Timestamp(meta['refit_max']) <= pd.Timestamp(target.race_date.min()) - pd.Timedelta(days=2)
            if role == 'evaluation':
                assert pd.Timestamp(meta['calibration_max']) <= pd.Timestamp(target.race_date.min()) - pd.Timedelta(days=2)
            providers.append(dict(role=role, year=year, fold=fold, runners=len(s),
                                  races=int(target.race_id.nunique()),
                                  refit_max=meta['refit_max'],
                                  date_min=target.race_date.min(), date_max=target.race_date.max(),
                                  raw_only=True, tau_read_as_input=False))
            refs += [dict(path=str(p.relative_to(ROOT)), sha256=sha(p), size_bytes=p.stat().st_size) for p in (mp, sp)]
    calibration = f.loc[f.year.between(2019, 2023)]
    evaluation = f.loc[f.year.between(2024, 2026)]
    assert calibration.race_id.nunique() == 2492
    assert evaluation.race_id.nunique() == 1779 and evaluation.race_date.nunique() == 269
    assert set(calibration.race_id).isdisjoint(set(evaluation.race_id))
    assert pd.Timestamp(calibration.race_date.max()) <= pd.Timestamp(evaluation.race_date.min()) - pd.Timedelta(days=2)
    plc_unknown = evaluation.loc[evaluation.field_n.lt(8)].drop_duplicates('race_id')
    assert len(plc_unknown) == 36 and set(plc_unknown.field_n) == {7}
    start = json.loads((HERE / 'SESSION_START.json').read_text())
    for item in start['sources']:
        assert sha(ROOT / item['path']) == item['sha256']
    report = dict(passed=True, feature_runners=len(f), feature_races=5206,
                  history_boundary='race_date - 2 calendar days, inclusive',
                  publication_time_verified=False,
                  source_population='frozen complete normal-finish postrace cohort',
                  calibration_races=2492, evaluation_races=1779, evaluation_dates=269,
                  plc_unknown_races=36, plc_eligible_races=1743,
                  plc_unknown_by_year=plc_unknown.groupby('year').size().to_dict(),
                  providers=providers, sources=refs,
                  experimental_code_imported=False, models_loaded=False,
                  database_opened=False, raw_features_refreshed=False,
                  protected_production_hashes_unchanged=True)
    out = HERE / 'SOURCE_REVIEW.json'
    with out.open('x') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ['providers', 'sources']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

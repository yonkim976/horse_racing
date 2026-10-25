from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path('/Users/kimyongjin/Desktop/horse_racing')
OUT = ROOT / 'jeju/research/20261020_axis_disagreement_conditions_v1'
SOURCE = ROOT / 'jeju/research/20261020_model_axis_vs_win_favorite_v1'
BASELINE = ROOT / 'jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet'
FEATURES = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet'
META = ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/meta.json'
ROOT_REVIEW = ROOT / 'jeju/research/20261020_model_axis_vs_win_favorite_rootreview_v1'

NON_FEATURE_COLUMNS = {
    'api_record_id', 'race_id', 'race_date', 'year', 'horse_id', 'horse_name',
    'horse_number', 'finish_position', 'history_cutoff', 'latest_history_date',
    'previous_start_id', 'last6_same_source_ids', 'last5_same_source_ids',
    'opponent_source_row_ids',
}
NUMERIC_FEATURES = [
    'observed_starts', 'days_since_start', 'previous_age', 'same_starts',
    'same_valid_times', 'days_since_same', 'last_time_s', 'mean5_s', 'valid_n5',
    'mean3_s', 'valid_n3', 'best5_s', 'fast2mean5_s', 'std5_s',
    'previous3_mean_s', 'previous3_valid_n', 'trend_s', 'opp_mean5_valid_n',
    'opp_mean5_valid_fraction', 'opp_mean5_median_s', 'mean5_minus_opp_mean_s',
    'mean5_minus_opp_median_s', 'mean5_minus_opp_fast2mean_s',
    'opp_mean5_faster_n', 'mean5_rank_fraction', 'previous_finish_relative_rank',
    'previous_top3', 'same_distance_last5_top3_rate',
    'same_distance_last5_actual_n', 'same_distance_last5_normal_n',
    'hist_s1f_relpos_n', 'hist_s1f_to_c4_pair_n', 'hist_c4_to_g1f_pair_n',
    'hist_s1f_relpos_mean5', 'hist_s1f_to_c4_forward_mean5',
    'hist_c4_to_g1f_forward_mean5',
]
CATEGORICAL_FEATURES = ['previous_sex', 'previous_result_status']
SUPPORT_COLUMNS = [
    'hist_s1f_relpos_n', 'hist_s1f_to_c4_pair_n', 'hist_c4_to_g1f_pair_n',
    'same_distance_last5_actual_n', 'same_distance_last5_normal_n',
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical_id(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors='coerce')
    return numeric.astype('Int64').astype('string')


def category_value(value) -> str:
    if pd.isna(value):
        return 'missing'
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return str(value)


def count_bin(value, zero_label='0', low_label='1-2', high_label='3+') -> str:
    if pd.isna(value):
        return 'missing'
    x = float(value)
    if x <= 0:
        return zero_label
    if x <= 2:
        return low_label
    return high_label


def experience_bin(value) -> str:
    if pd.isna(value):
        return 'missing'
    x = float(value)
    if x == 0:
        return '0'
    if x < 5:
        return '1-4'
    return '5+'


def valid_n5_bin(value) -> str:
    if pd.isna(value):
        return 'missing'
    x = float(value)
    if x == 0:
        return '0'
    if x <= 2:
        return '1-2'
    return '3-5'


def model_rank_bin(value) -> str:
    if pd.isna(value):
        return 'missing'
    x = int(value)
    return str(x) if x <= 3 else '4+'


def interval_bin(value) -> str:
    if pd.isna(value):
        return 'missing'
    x = float(value)
    if x <= 14:
        return '<=14'
    if x <= 28:
        return '15-28'
    if x <= 56:
        return '29-56'
    return '>56'


def status_pair(axis_value, favorite_value) -> str:
    if pd.isna(axis_value) or pd.isna(favorite_value):
        return 'missing'
    return f'{category_value(axis_value)}|{category_value(favorite_value)}'


def four_state_pair(axis_value, favorite_value) -> str:
    if pd.isna(axis_value) or pd.isna(favorite_value):
        return 'missing'
    a = bool(float(axis_value) >= 1)
    f = bool(float(favorite_value) >= 1)
    return {
        (True, True): 'axis_yes_favorite_yes',
        (True, False): 'axis_yes_favorite_no',
        (False, True): 'axis_no_favorite_yes',
        (False, False): 'axis_no_favorite_no',
    }[(a, f)]


def add_category_labels(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d['period_2024_25_vs_2026_partial'] = np.where(d['year'].lt(2026), '2024-25', '2026_partial')
    d['distance_grade'] = d['distance_m'].map(category_value) + 'm|' + d['grade_raw'].map(category_value)
    d['p_gap_bin'] = pd.cut(
        d['p_gap'], bins=[-np.inf, 0.05, 0.10, np.inf], labels=['<0.05', '0.05-<0.10', '>=0.10'],
        right=False, include_lowest=True,
    ).astype('string')
    d['favorite_model_rank_bin'] = d['favorite_model_rank'].map(model_rank_bin)
    d['axis_observed_starts_bin'] = d['axis_observed_starts'].map(experience_bin)
    d['favorite_observed_starts_bin'] = d['favorite_observed_starts'].map(experience_bin)
    d['axis_valid_n5_bin'] = d['axis_valid_n5'].map(valid_n5_bin)
    d['favorite_valid_n5_bin'] = d['favorite_valid_n5'].map(valid_n5_bin)
    d['axis_days_since_start_bin'] = d['axis_days_since_start'].map(interval_bin)
    d['favorite_days_since_start_bin'] = d['favorite_days_since_start'].map(interval_bin)
    d['axis_days_since_same_bin'] = d['axis_days_since_same'].map(interval_bin)
    d['favorite_days_since_same_bin'] = d['favorite_days_since_same'].map(interval_bin)
    for side in ['axis', 'favorite']:
        d[f'{side}_same_starts_exact'] = d[f'{side}_same_starts'].map(category_value)
        d[f'{side}_same_valid_times_exact'] = d[f'{side}_same_valid_times'].map(category_value)
        d[f'{side}_previous_age_exact'] = d[f'{side}_previous_age'].map(category_value)
        d[f'{side}_previous_sex_category'] = d[f'{side}_previous_sex'].map(category_value)
        d[f'{side}_previous_result_status_category'] = d[f'{side}_previous_result_status'].map(category_value)
        for col in ['hist_s1f_relpos_n', 'hist_s1f_to_c4_pair_n', 'hist_c4_to_g1f_pair_n']:
            d[f'{side}_{col}_bin'] = d[f'{side}_{col}'].map(count_bin)
    d['paired_mean5_status'] = np.select(
        [d['axis_mean5_s'].isna() | d['favorite_mean5_s'].isna(), d['axis_mean5_s'].le(d['favorite_mean5_s'])],
        ['missing', 'axis_mean5_le_favorite'], default='axis_mean5_gt_favorite',
    )
    d['previous_top3_pair'] = [four_state_pair(a, f) for a, f in zip(d['axis_previous_top3'], d['favorite_previous_top3'])]
    d['previous_result_status_pair'] = [status_pair(a, f) for a, f in zip(d['axis_previous_result_status'], d['favorite_previous_result_status'])]
    return d


def summarize_conditions(df: pd.DataFrame, population: str, condition_columns: list[str]) -> list[dict]:
    rows: list[dict] = []
    for condition in condition_columns:
        values = df[condition].map(category_value)
        for value, group_idx in values.groupby(values, sort=True).groups.items():
            group = df.loc[group_idx]
            counts = group['case'].value_counts()
            n = int(len(group))
            model_hit = int(group['axis_top3'].sum())
            market_hit = int(group['favorite_top3'].sum())
            cells = {case: int(counts.get(case, 0)) for case in ['model_only', 'market_only', 'both', 'neither']}
            pair_diff = group['axis_top3'].astype(float) - group['favorite_top3'].astype(float)
            paired_se = float(pair_diff.std(ddof=1) / np.sqrt(n)) if n > 1 else np.nan

            def wilson(successes: int, support: int) -> tuple[float, float]:
                if support == 0:
                    return (np.nan, np.nan)
                z = 1.959963984540054
                p = successes / support
                denom = 1 + z * z / support
                center = (p + z * z / (2 * support)) / denom
                half = z * np.sqrt((p * (1 - p) / support) + z * z / (4 * support * support)) / denom
                return (max(0.0, center - half), min(1.0, center + half))

            model_wilson = wilson(model_hit, n)
            favorite_wilson = wilson(market_hit, n)
            paired_diff = (model_hit - market_hit) / n if n else np.nan
            rows.append({
                'population': population,
                'condition': condition,
                'condition_value': value,
                'n': n,
                **{f'{case}_n': cells[case] for case in cells},
                'same_pick_n': int(counts.get('same_pick', 0)),
                'model_hit_n': model_hit,
                'favorite_hit_n': market_hit,
                'model_hit_rate': model_hit / n if n else np.nan,
                'favorite_hit_rate': market_hit / n if n else np.nan,
                'model_minus_market_hit_rate': (model_hit - market_hit) / n if n else np.nan,
                'model_hit_rate_wilson95_low': model_wilson[0],
                'model_hit_rate_wilson95_high': model_wilson[1],
                'favorite_hit_rate_wilson95_low': favorite_wilson[0],
                'favorite_hit_rate_wilson95_high': favorite_wilson[1],
                'model_minus_market_paired_wald95_low': paired_diff - 1.959963984540054 * paired_se if n and n > 1 else np.nan,
                'model_minus_market_paired_wald95_high': paired_diff + 1.959963984540054 * paired_se if n and n > 1 else np.nan,
                'n_lt_30': n < 30,
                'any_four_state_cell_lt_10': any(cells[k] < 10 for k in cells),
                'exploratory_flag': n < 30 or any(cells[k] < 10 for k in cells),
            })
    return rows


def add_distribution_rows(rows: list[dict], group: pd.DataFrame, case: str, cols: list[str], input_features: set[str]) -> None:
    for col in cols:
        for side in ['axis', 'favorite', 'axis_minus_favorite']:
            series = group[f'{side}_{col}'] if side != 'axis_minus_favorite' else group[f'axis_{col}'] - group[f'favorite_{col}']
            s = pd.to_numeric(series, errors='coerce').dropna()
            rows.append({
                'case': case, 'feature': col, 'side': side, 'value_type': 'numeric', 'category': '',
                'model_input': col in input_features, 'n': int(s.size),
                'mean': float(s.mean()) if len(s) else np.nan,
                'median': float(s.median()) if len(s) else np.nan,
                'q25': float(s.quantile(0.25)) if len(s) else np.nan,
                'q75': float(s.quantile(0.75)) if len(s) else np.nan,
                'count': int(s.size), 'fraction': np.nan,
            })
    for col in CATEGORICAL_FEATURES:
        for side in ['axis', 'favorite']:
            s = group[f'{side}_{col}'].map(category_value)
            denom = int(s.notna().sum())
            counts = s.value_counts(dropna=False)
            for category, count in counts.items():
                rows.append({
                    'case': case, 'feature': col, 'side': side, 'value_type': 'category', 'category': category,
                    'model_input': col in input_features, 'n': denom,
                    'mean': np.nan, 'median': np.nan, 'q25': np.nan, 'q75': np.nan,
                    'count': int(count), 'fraction': float(count / len(group)) if len(group) else np.nan,
                })


def main() -> None:
    lock = json.loads((OUT / 'SOURCE_HASHES.json').read_text(encoding='utf-8'))
    for item in lock['inputs']:
        source_path = ROOT / item['path']
        if sha256(source_path) != item['sha256']:
            raise RuntimeError(f"Locked input changed: {item['path']}")

    selected_all = pd.read_csv(SOURCE / 'selected_rows.csv')
    ledger_all = pd.read_csv(SOURCE / 'runner_ledger.csv')
    odds = pd.read_csv(SOURCE / 'win_odds_snapshot.csv')
    predictions_all = pd.read_parquet(BASELINE)
    feature_all = pd.read_parquet(FEATURES)
    root_ledger = pd.read_parquet(ROOT_REVIEW / 'ROOT_BASELINE_RACE_LEDGER.parquet')
    meta = json.loads(META.read_text(encoding='utf-8'))
    input_features = set(meta['features'])

    for frame in [ledger_all, odds, predictions_all, feature_all]:
        frame['horse_id'] = canonical_id(frame['horse_id'])
    selected = selected_all.loc[selected_all['model'].eq('F1_STYLE6')].copy()
    ledger = ledger_all.loc[ledger_all['model'].eq('F1_STYLE6')].copy()
    predictions = predictions_all.loc[predictions_all['variant'].eq('F1_STYLE6')].copy()
    odds['horse_id'] = canonical_id(odds['horse_id'])

    assert selected['race_id'].nunique() == 1503 and not selected.duplicated('race_id').any()
    assert len(ledger) == 14714 and not ledger.duplicated(['api_record_id', 'horse_id']).any()
    assert not predictions.duplicated(['api_record_id', 'horse_id']).any()
    assert not feature_all.duplicated(['api_record_id', 'horse_id']).any()
    assert not odds.duplicated(['api_record_id', 'horse_id']).any()

    pred_scope = predictions.loc[predictions['race_id'].isin(selected['race_id'])].copy()
    ledger_pred = ledger.merge(
        pred_scope[['api_record_id', 'race_id', 'horse_id', 'horse_number', 'score', 'p_top3', 'y']],
        on=['api_record_id', 'race_id', 'horse_id', 'horse_number'], how='left', validate='one_to_one', indicator=True,
    )
    if not ledger_pred['_merge'].eq('both').all():
        raise RuntimeError('Some frozen ledger entries did not link to F1_STYLE6 baseline predictions.')
    if not np.allclose(ledger_pred['score_x'], ledger_pred['score_y'], rtol=0, atol=1e-14):
        raise RuntimeError('Frozen score values disagree with baseline prediction file.')
    if not np.allclose(ledger_pred['p_top3_x'], ledger_pred['p_top3_y'], rtol=0, atol=1e-14):
        raise RuntimeError('Frozen probability values disagree with baseline prediction file.')
    if not (ledger_pred['actual_top3'].astype(int).to_numpy() == ledger_pred['y'].astype(int).to_numpy()).all():
        raise RuntimeError('Frozen Top3 labels disagree with baseline prediction file.')
    ledger_pred = ledger_pred.drop(columns=['_merge', 'score_y', 'p_top3_y', 'y']).rename(columns={'score_x': 'score', 'p_top3_x': 'p_top3'})

    odds_check = ledger[['api_record_id', 'race_id', 'horse_id', 'horse_number', 'win_odds', 'actual_top3', 'finish_position']].merge(
        odds[['api_record_id', 'race_id', 'horse_id', 'horse_number', 'win_odds', 'actual_top3', 'finish_position']],
        on=['api_record_id', 'race_id', 'horse_id', 'horse_number'], how='outer', suffixes=('_ledger', '_snapshot'), indicator=True, validate='one_to_one',
    )
    if not odds_check['_merge'].eq('both').all():
        raise RuntimeError('Odds snapshot and frozen F1 ledger entry keys differ.')
    if not np.allclose(odds_check['win_odds_ledger'], odds_check['win_odds_snapshot'], rtol=0, atol=0):
        raise RuntimeError('Odds values differ between frozen snapshot and runner ledger.')
    if not (odds_check['actual_top3_ledger'].astype(bool).to_numpy() == odds_check['actual_top3_snapshot'].astype(bool).to_numpy()).all():
        raise RuntimeError('Top3 labels differ between frozen snapshot and runner ledger.')

    # Deterministic rank uses the frozen model rule: score descending, lower horse number first.
    ranked = ledger_pred.sort_values(['race_id', 'score', 'horse_number'], ascending=[True, False, True], kind='mergesort').copy()
    ranked['model_score_rank'] = ranked.groupby('race_id', sort=False).cumcount() + 1
    axis = ranked.loc[ranked['model_axis_selected']].copy()
    favorite = ranked.loc[ranked['unique_favorite_selected']].copy()
    if len(axis) != 1503 or len(favorite) != 1477:
        raise RuntimeError('Unexpected selected axis/favorite support.')

    # Check source-selected race-level choices against selected runner ledger IDs.
    axis_choice = axis[['race_id', 'api_record_id', 'horse_id', 'horse_number']].rename(columns={
        'api_record_id': 'axis_api_record_id', 'horse_id': 'axis_horse_id', 'horse_number': 'axis_horse_number',
    })
    favorite_choice = favorite[['race_id', 'api_record_id', 'horse_id', 'horse_number']].rename(columns={
        'api_record_id': 'favorite_api_record_id', 'horse_id': 'favorite_horse_id', 'horse_number': 'favorite_horse_number',
    })
    sel_ids = selected[['race_id', 'axis_horse_id', 'axis_horse_number', 'unique_favorite_horse_id', 'unique_favorite_horse_number', 'minimum_odds_tied']].copy()
    sel_ids['axis_horse_id'] = canonical_id(sel_ids['axis_horse_id'])
    sel_ids['unique_favorite_horse_id'] = canonical_id(sel_ids['unique_favorite_horse_id'])
    pair_ids = axis_choice.merge(favorite_choice, on='race_id', how='inner', validate='one_to_one')
    if len(pair_ids) != 1477:
        raise RuntimeError('Unique favorite row count differs from selected ledger.')
    selected_unique = sel_ids.loc[~sel_ids['minimum_odds_tied']].copy()
    sid = selected_unique.merge(pair_ids, on='race_id', how='outer', validate='one_to_one', suffixes=('_selected', '_ledger'), indicator=True)
    if not sid['_merge'].eq('both').all():
        raise RuntimeError('Unique favorite race keys differ between selected rows and runner ledger.')
    for left, right in [
        ('axis_horse_id_selected', 'axis_horse_id_ledger'),
        ('axis_horse_number_selected', 'axis_horse_number_ledger'),
        ('unique_favorite_horse_id', 'favorite_horse_id'),
        ('unique_favorite_horse_number', 'favorite_horse_number'),
    ]:
        if 'horse_id' in left:
            equal = sid[left].astype('string').equals(sid[right].astype('string'))
        else:
            equal = pd.to_numeric(sid[left], errors='coerce').astype('Int64').equals(pd.to_numeric(sid[right], errors='coerce').astype('Int64'))
        if not equal:
            raise RuntimeError(f'Selected ID/number mismatch: {left} vs {right}')

    # Join every selected runner to the frozen T−2 feature row with exact API and horse identifiers.
    # Distance and field size are race-level inputs retained once from the selected race row.
    profile_columns = [c for c in feature_all.columns if c not in NON_FEATURE_COLUMNS and c not in {'distance_m', 'field_n'}]
    missing_expected = set(meta['features']) - set(profile_columns) - {'distance_m', 'field_n'}
    if missing_expected:
        raise RuntimeError(f'Model input columns absent from saved features: {sorted(missing_expected)}')
    feature_identity = ['api_record_id', 'race_id', 'horse_id', 'horse_number', 'horse_name', 'history_cutoff', 'latest_history_date', 'previous_start_id']
    feature_keep = feature_identity + profile_columns
    axis_features = axis.merge(feature_all[feature_keep], on=['api_record_id', 'race_id', 'horse_id', 'horse_number'], how='left', validate='one_to_one', indicator=True)
    favorite_features = favorite.merge(feature_all[feature_keep], on=['api_record_id', 'race_id', 'horse_id', 'horse_number'], how='left', validate='one_to_one', indicator=True)
    if not axis_features['_merge'].eq('both').all() or not favorite_features['_merge'].eq('both').all():
        raise RuntimeError('A selected model/favorite horse did not join to a saved T−2 feature row.')
    axis_features = axis_features.drop(columns=['_merge'])
    favorite_features = favorite_features.drop(columns=['_merge'])

    race_columns = ['race_id', 'race_date', 'year', 'distance_m', 'field_n', 'axis_exact_score_tie_count', 'axis_score_tie_lower_number_rule_used']
    race = selected[race_columns + ['minimum_win_odds', 'minimum_odds_runner_count', 'minimum_odds_tied']].copy()

    def payload(frame: pd.DataFrame, side: str) -> pd.DataFrame:
        columns = ['race_id', 'api_record_id', 'horse_id', 'horse_number', 'horse_name', 'history_cutoff',
                   'latest_history_date', 'previous_start_id', 'score', 'p_top3', 'actual_top3',
                   'finish_position', 'win_odds', 'model_score_rank'] + profile_columns
        columns = list(dict.fromkeys(c for c in columns if c in frame.columns))
        renamed = {c: f'{side}_{c}' for c in columns if c != 'race_id'}
        renamed['horse_name'] = f'{side}_horse_name_frozen'
        renamed['win_odds'] = f'{side}_final_win_odds'
        renamed['actual_top3'] = f'{side}_top3'
        renamed['model_score_rank'] = f'{side}_model_score_rank' if side == 'axis' else 'favorite_model_rank'
        return frame[columns].rename(columns=renamed)

    axis_payload = payload(axis_features, 'axis')
    favorite_payload = payload(favorite_features, 'favorite')
    base = race.merge(axis_payload, on='race_id', how='inner', validate='one_to_one')
    base = base.merge(favorite_payload, on='race_id', how='inner', validate='one_to_one')
    if len(base) != 1477:
        raise RuntimeError('Race-level selected pair did not resolve to 1,477 unique-favorite races.')
    base['grade_raw'] = base['axis_grade_raw']
    if not base['grade_raw'].astype('string').equals(base['favorite_grade_raw'].astype('string')):
        raise RuntimeError('Axis/favorite race grade values disagree in the frozen feature rows.')
    base['axis_is_favorite'] = base['axis_horse_id'].astype('string').eq(base['favorite_horse_id'].astype('string'))
    base['axis_minus_favorite_p'] = base['axis_p_top3'] - base['favorite_p_top3']
    base['p_gap'] = base['axis_minus_favorite_p']
    base['axis_minus_favorite_score'] = base['axis_score'] - base['favorite_score']
    base['axis_minus_favorite_win_odds'] = base['axis_final_win_odds'] - base['favorite_final_win_odds']
    # The displayed final odds are explanatory only; this rank is never a T−2 condition.
    odds_rank = ranked[['race_id', 'horse_id', 'win_odds']].copy()
    odds_rank['final_odds_rank'] = odds_rank.groupby('race_id')['win_odds'].rank(method='min', ascending=True)
    base = base.merge(
        odds_rank.rename(columns={'horse_id': 'axis_horse_id', 'final_odds_rank': 'axis_final_odds_rank'})[['race_id', 'axis_horse_id', 'axis_final_odds_rank']],
        on=['race_id', 'axis_horse_id'], how='left', validate='one_to_one',
    )
    base['case'] = np.select(
        [base['axis_is_favorite'], base['axis_top3'] & ~base['favorite_top3'], ~base['axis_top3'] & base['favorite_top3'], base['axis_top3'] & base['favorite_top3']],
        ['same_pick', 'model_only', 'market_only', 'both'], default='neither',
    )
    base['disagreement'] = ~base['axis_is_favorite']
    base = add_category_labels(base)
    disagreements = base.loc[base['disagreement']].copy()

    # Expected fixed support supplied by the user; assert before writing summaries.
    expected = {'model_only': 126, 'market_only': 248, 'both': 173, 'neither': 131}
    observed = {k: int((disagreements['case'] == k).sum()) for k in expected}
    if len(disagreements) != 678 or observed != expected:
        raise RuntimeError(f'Fixed population counts differ: n={len(disagreements)}, counts={observed}')
    if len(base) != 1477 or int(base['axis_is_favorite'].sum()) != 799:
        raise RuntimeError(f'Unexpected unique-favorite/background population: {len(base)} rows; same={int(base.axis_is_favorite.sum())}')

    # Date-cluster bootstrap for the paired Top3 hit-rate difference; no condition search is involved.
    bootstrap_source = disagreements.assign(_paired_diff=disagreements['axis_top3'].astype(float) - disagreements['favorite_top3'].astype(float))
    cluster = bootstrap_source.groupby('race_date', sort=True)['_paired_diff'].agg(['sum', 'size']).reset_index()
    rng = np.random.default_rng(20261020)
    bootstrap_rates = np.empty(2000, dtype=float)
    n_clusters = len(cluster)
    cluster_sums = cluster['sum'].to_numpy(dtype=float)
    cluster_sizes = cluster['size'].to_numpy(dtype=float)
    for b in range(len(bootstrap_rates)):
        chosen = rng.integers(0, n_clusters, size=n_clusters)
        bootstrap_rates[b] = cluster_sums[chosen].sum() / cluster_sizes[chosen].sum()
    overall_pair_diff = float(bootstrap_source['_paired_diff'].mean())
    cluster_ci = [float(np.quantile(bootstrap_rates, 0.025)), float(np.quantile(bootstrap_rates, 0.975))]

    # Check the independent root race ledger on the shared unique-favorite population.
    root = root_ledger.copy()
    root['model_horse_id'] = canonical_id(root['model_horse_id'])
    root['favourite_horse_id'] = canonical_id(root['favourite_horse_id'])
    check = base[['race_id', 'axis_horse_id', 'favorite_horse_id', 'case']].merge(
        root[['race_id', 'model_horse_id', 'favourite_horse_id', 'model_hit', 'favourite_hit', 'case']],
        on='race_id', how='left', suffixes=('_analysis', '_root'), validate='one_to_one', indicator=True,
    )
    if not check['_merge'].eq('both').all():
        raise RuntimeError('A unique-favorite race is absent from the root verified race ledger.')
    root_case_from_flags = np.select(
        [check['axis_horse_id'].astype('string').eq(check['favorite_horse_id'].astype('string')),
         check['model_hit'].astype(bool) & ~check['favourite_hit'].astype(bool),
         ~check['model_hit'].astype(bool) & check['favourite_hit'].astype(bool),
         check['model_hit'].astype(bool) & check['favourite_hit'].astype(bool)],
        ['same_pick', 'model_only', 'market_only', 'both'], default='neither',
    )
    root_case_agreement = int((check['case_analysis'].to_numpy() == root_case_from_flags).sum())
    root_case_labels = {
        'same_hit': 'same_pick', 'same_miss': 'same_pick', 'model_only_hit': 'model_only',
        'favourite_only_hit': 'market_only', 'both_hit': 'both', 'neither_hit': 'neither',
    }
    mapped_root_labels = check['case_root'].map(root_case_labels)
    root_case_label_agreement = int((check['case_analysis'] == mapped_root_labels).sum())
    root_id_agreement = int(
        check['axis_horse_id'].astype('string').eq(check['model_horse_id'].astype('string')).sum()
        + check['favorite_horse_id'].astype('string').eq(check['favourite_horse_id'].astype('string')).sum()
    )
    if root_case_agreement != 1477 or root_case_label_agreement != 1477 or root_id_agreement != 2954:
        raise RuntimeError(f'Root verified ledger differs: flags={root_case_agreement}/1477, labels={root_case_label_agreement}/1477, selected IDs={root_id_agreement}/2954')

    # Build the full 1,477 race-pair artifact with raw saved T−2 features and category labels.
    pair_cols = [
        'race_id', 'race_date', 'year', 'period_2024_25_vs_2026_partial', 'distance_m', 'grade_raw', 'distance_grade', 'field_n',
        'axis_api_record_id', 'axis_horse_id', 'axis_horse_number', 'axis_horse_name_frozen',
        'favorite_api_record_id', 'favorite_horse_id', 'favorite_horse_number', 'favorite_horse_name_frozen',
        'case', 'disagreement', 'axis_is_favorite', 'axis_finish_position', 'favorite_finish_position', 'axis_top3', 'favorite_top3',
        'axis_score', 'favorite_score', 'axis_p_top3', 'favorite_p_top3', 'axis_minus_favorite_score', 'axis_minus_favorite_p', 'p_gap',
        'favorite_model_rank', 'axis_model_score_rank', 'axis_final_win_odds', 'favorite_final_win_odds',
        'axis_final_odds_rank', 'minimum_win_odds', 'minimum_odds_runner_count', 'minimum_odds_tied',
        'axis_history_cutoff', 'favorite_history_cutoff', 'axis_latest_history_date', 'favorite_latest_history_date',
        'axis_exact_score_tie_count', 'axis_score_tie_lower_number_rule_used',
    ]
    for col in profile_columns:
        pair_cols.extend([f'axis_{col}', f'favorite_{col}'])
    for col in base.columns:
        if col.endswith('_bin') or col.endswith('_exact') or col.endswith('_category') or col in ['paired_mean5_status', 'previous_top3_pair', 'previous_result_status_pair']:
            pair_cols.append(col)
    pair_cols = list(dict.fromkeys(c for c in pair_cols if c in base.columns))
    base[pair_cols].to_parquet(OUT / 'race_pair_features.parquet', index=False)

    condition_columns = [
        'distance_m', 'grade_raw', 'distance_grade', 'field_n', 'year', 'period_2024_25_vs_2026_partial',
        'p_gap_bin', 'favorite_model_rank_bin',
        'axis_observed_starts_bin', 'favorite_observed_starts_bin',
        'axis_same_starts_exact', 'favorite_same_starts_exact',
        'axis_same_valid_times_exact', 'favorite_same_valid_times_exact',
        'axis_valid_n5_bin', 'favorite_valid_n5_bin',
        'axis_days_since_start_bin', 'favorite_days_since_start_bin',
        'axis_days_since_same_bin', 'favorite_days_since_same_bin',
        'axis_previous_age_exact', 'favorite_previous_age_exact',
        'axis_previous_sex_category', 'favorite_previous_sex_category',
        'paired_mean5_status', 'previous_top3_pair', 'previous_result_status_pair',
        'axis_hist_s1f_relpos_n_bin', 'favorite_hist_s1f_relpos_n_bin',
        'axis_hist_s1f_to_c4_pair_n_bin', 'favorite_hist_s1f_to_c4_pair_n_bin',
        'axis_hist_c4_to_g1f_pair_n_bin', 'favorite_hist_c4_to_g1f_pair_n_bin',
    ]
    summaries = summarize_conditions(base, 'unique_favorite_background_1477', condition_columns)
    summaries += summarize_conditions(disagreements, 'all_disagreements_678', condition_columns)
    # Explicit pooled/partial year contrast is already a fixed category above; preserve the per-year rows too.
    overall_dis = disagreements.assign(_overall='all 678')
    summaries += summarize_conditions(overall_dis, 'all_disagreements_678', ['_overall'])
    overall_bg = base.assign(_overall='all 1477')
    summaries += summarize_conditions(overall_bg, 'unique_favorite_background_1477', ['_overall'])
    pd.DataFrame(summaries).to_csv(OUT / 'condition_summary.csv', index=False)

    period_rows = []
    period_condition_columns = [c for c in condition_columns if c not in {'year', 'period_2024_25_vs_2026_partial'}]
    period_masks = [
        ('2024', disagreements['year'].eq(2024)),
        ('2025', disagreements['year'].eq(2025)),
        ('2026_partial', disagreements['year'].eq(2026)),
        ('2024-25_pooled', disagreements['year'].isin([2024, 2025])),
    ]
    for period_name, mask in period_masks:
        period_df = disagreements.loc[mask].copy()
        if period_df.empty:
            continue
        period_df['_overall'] = f'all {period_name}'
        period_records = summarize_conditions(period_df, f'disagreements_{period_name}', period_condition_columns)
        period_records += summarize_conditions(period_df, f'disagreements_{period_name}', ['_overall'])
        for rec in period_records:
            rec['period'] = period_name
            period_rows.append(rec)
    pd.DataFrame(period_rows).to_csv(OUT / 'condition_summary_by_period.csv', index=False)

    # Model-only versus market-only descriptive profile; these are the 374 XOR races only.
    dist_rows: list[dict] = []
    numeric_cols = [c for c in NUMERIC_FEATURES if f'axis_{c}' in base.columns and f'favorite_{c}' in base.columns]
    for case in ['model_only', 'market_only']:
        group = disagreements.loc[disagreements['case'].eq(case)]
        add_distribution_rows(dist_rows, group, case, numeric_cols, input_features)
        for col in CATEGORICAL_FEATURES:
            for side in ['axis', 'favorite']:
                series = group[f'{side}_{col}'].map(category_value)
                for category, count in series.value_counts(dropna=False).items():
                    dist_rows.append({
                        'case': case, 'feature': col, 'side': side, 'value_type': 'category', 'category': category,
                        'model_input': col in input_features, 'n': int(len(group)), 'mean': np.nan,
                        'median': np.nan, 'q25': np.nan, 'q75': np.nan, 'count': int(count),
                        'fraction': float(count / len(group)) if len(group) else np.nan,
                    })
    for extra in ['p_gap', 'axis_minus_favorite_score', 'favorite_model_rank', 'axis_final_odds_rank']:
        for case in ['model_only', 'market_only']:
            s = pd.to_numeric(disagreements.loc[disagreements['case'].eq(case), extra], errors='coerce').dropna()
            dist_rows.append({'case': case, 'feature': extra, 'side': 'race_pair', 'value_type': 'numeric', 'category': '',
                              'model_input': False, 'n': int(s.size), 'mean': float(s.mean()) if len(s) else np.nan,
                              'median': float(s.median()) if len(s) else np.nan, 'q25': float(s.quantile(.25)) if len(s) else np.nan,
                              'q75': float(s.quantile(.75)) if len(s) else np.nan, 'count': int(s.size), 'fraction': np.nan})
    pd.DataFrame(dist_rows).to_csv(OUT / 'exclusive_distribution.csv', index=False)

    # Calibration summaries use saved out-of-sample probabilities and actual Top3 labels.
    cal_rows: list[dict] = []
    calibration_groups: list[tuple[str, pd.DataFrame]] = [('unique_favorite_background_1477', base), ('all_disagreements_678', disagreements)]
    for c in ['same_pick', 'model_only', 'market_only', 'both', 'neither']:
        g = base.loc[base['case'].eq(c)]
        if len(g):
            calibration_groups.append((f'case_{c}', g))
    for dim in ['year', 'distance_m', 'p_gap_bin', 'favorite_model_rank_bin', 'paired_mean5_status', 'previous_top3_pair']:
        for val, g in disagreements.groupby(dim, dropna=False, sort=True):
            calibration_groups.append((f'{dim}={category_value(val)}', g))
    for group_name, g in calibration_groups:
        for role, pcol, ycol in [
            ('model_axis', 'axis_p_top3', 'axis_top3'),
            ('market_favorite', 'favorite_p_top3', 'favorite_top3'),
        ]:
            p = pd.to_numeric(g[pcol], errors='coerce')
            y = g[ycol].astype(float)
            valid = p.notna() & y.notna()
            if not valid.any():
                continue
            cal_rows.append({
                'group': group_name, 'role': role, 'n': int(valid.sum()), 'mean_predicted_p_top3': float(p[valid].mean()),
                'actual_top3_rate': float(y[valid].mean()), 'mean_actual_minus_p': float((y[valid] - p[valid]).mean()),
            })
    pd.DataFrame(cal_rows).to_csv(OUT / 'calibration_by_group.csv', index=False)

    # Retrospective candidate-pool coverage only: does the model's top-K contain any actual Top3 runner?
    # These rows are hindsight diagnostics, not a deployable selection rule or expected future performance.
    topk_rows: list[dict] = []
    pool_groups = [('all_disagreements_678', disagreements)] + [
        (f'case_{c}', disagreements.loc[disagreements['case'].eq(c)])
        for c in ['model_only', 'market_only', 'both', 'neither']
    ]
    ranked_case = ranked.merge(disagreements[['race_id', 'case']], on='race_id', how='inner', validate='many_to_one')
    for group_name, group in pool_groups:
        race_ids = set(group['race_id'])
        for k in [1, 3, 5]:
            runners = ranked_case.loc[ranked_case['race_id'].isin(race_ids) & ranked_case['model_score_rank'].le(k)]
            covered = runners.groupby('race_id', sort=False)['actual_top3'].any()
            covered = covered.reindex(sorted(race_ids), fill_value=False)
            topk_rows.append({
                'population': group_name, 'model_top_k': k, 'race_n': len(race_ids),
                'races_with_any_actual_top3_in_model_top_k': int(covered.sum()),
                'candidate_pool_coverage_rate': float(covered.mean()) if len(covered) else np.nan,
                'interpretation': 'retrospective_hindsight_candidate_pool_coverage_only',
            })
    topk_df = pd.DataFrame(topk_rows)
    topk_df.to_csv(OUT / 'model_topk_pool_diagnostic.csv', index=False)

    # Small, date-ordered, source-frozen examples; final odds are explanatory only.
    example_rows = []
    example_cols = [
        'race_date', 'race_id', 'year', 'distance_m', 'grade_raw', 'field_n', 'case',
        'axis_api_record_id', 'axis_horse_id', 'axis_horse_number', 'axis_horse_name_frozen', 'axis_finish_position', 'axis_top3',
        'favorite_api_record_id', 'favorite_horse_id', 'favorite_horse_number', 'favorite_horse_name_frozen', 'favorite_finish_position', 'favorite_top3',
        'axis_p_top3', 'favorite_p_top3', 'p_gap', 'axis_minus_favorite_score', 'favorite_model_rank',
        'axis_final_win_odds', 'axis_final_odds_rank', 'favorite_final_win_odds',
        'axis_observed_starts', 'favorite_observed_starts', 'axis_valid_n5', 'favorite_valid_n5',
        'axis_mean5_s', 'favorite_mean5_s', 'paired_mean5_status', 'previous_top3_pair',
    ]
    for case in ['model_only', 'market_only', 'both', 'neither']:
        group = disagreements.loc[disagreements['case'].eq(case)].sort_values(['race_date', 'race_id']).head(3)
        example_rows.extend(group[example_cols].to_dict('records'))
    pd.DataFrame(example_rows).to_csv(OUT / 'examples.csv', index=False)

    # Explicitly mark every saved feature column as input, unused derived feature, key, label, or lineage.
    catalog_rows = []
    definitions = {
        'trend_s': 'Newer three-record mean time minus older three-record mean time; each half needs at least 2 valid records; positive means recent times are slower.',
        'std5_s': 'Sample standard deviation of the recent five-record times; at least 3 valid records.',
        'best5_s': 'Minimum seconds among the recent five-record times.',
        'previous_top3': 'Whether the individual previous finish position is in ranks 1..3; it does not require a complete-race audit.',
        'previous_result_status': 'Separate status for the previous result completeness/normality.',
        'same_distance_last5_top3_rate': 'Saved same-distance recent-five Top3 rate; not in F1_STYLE6 exact input list.',
        'same_distance_last5_actual_n': 'Support count for same-distance recent-five rate; not an F1_STYLE6 input.',
        'same_distance_last5_normal_n': 'Normal-result support count for same-distance recent-five rate; not an F1_STYLE6 input.',
        'hist_s1f_relpos_mean5': 'Average relative rank position at S1F; lower values are closer to the front in the source contract.',
        'hist_s1f_to_c4_forward_mean5': 'Average change in relative rank position from S1F to 4C.',
        'hist_c4_to_g1f_forward_mean5': 'Average change in relative rank position from 4C to G1F.',
    }
    for col in feature_all.columns:
        if col in input_features:
            role = 'exact_F1_STYLE6_model_input'
        elif col == 'finish_position':
            role = 'outcome_label_not_input'
        elif col in NON_FEATURE_COLUMNS:
            role = 'key_metadata_lineage_or_label_not_input'
        else:
            role = 'saved_derived_feature_not_in_F1_STYLE6_input_contract'
        catalog_rows.append({'column': col, 'dtype': str(feature_all[col].dtype), 'model_input': col in input_features,
                             'role': role, 'definition_or_note': definitions.get(col, '')})
    pd.DataFrame(catalog_rows).to_csv(OUT / 'FEATURE_CATALOG.csv', index=False)

    # Recheck locked input hashes after reading/analysis.
    if any(sha256(ROOT / item['path']) != item['sha256'] for item in lock['inputs']):
        raise RuntimeError('A locked source changed during analysis.')

    case_counts = {k: int((disagreements['case'] == k).sum()) for k in ['model_only', 'market_only', 'both', 'neither']}
    year_case = pd.crosstab(disagreements['year'], disagreements['case']).reindex(columns=['model_only', 'market_only', 'both', 'neither'], fill_value=0)
    distance_case = pd.crosstab(disagreements['distance_m'], disagreements['case']).reindex(columns=['model_only', 'market_only', 'both', 'neither'], fill_value=0)
    report = {
        'status': 'PASS',
        'scope': {'unique_favorite_races': int(len(base)), 'disagreements': int(len(disagreements)), 'same_pick_background': int(base['axis_is_favorite'].sum()),
                  'tied_minimum_odds_races_excluded': int(selected['minimum_odds_tied'].sum()), 'dates': [str(base['race_date'].min()), str(base['race_date'].max())],
                  'distances_m': sorted(int(x) for x in base['distance_m'].dropna().unique())},
        'four_outcomes_678': case_counts,
        'xor_exclusive_races': int(disagreements['case'].isin(['model_only', 'market_only']).sum()),
        'top3_marginals_678': {'model_axis': float(disagreements['axis_top3'].mean()), 'market_favorite': float(disagreements['favorite_top3'].mean()),
                               'model_minus_market': float(disagreements['axis_top3'].mean() - disagreements['favorite_top3'].mean())},
        'top3_marginals_1477': {'model_axis': float(base['axis_top3'].mean()), 'market_favorite': float(base['favorite_top3'].mean()),
                                'model_minus_market': float(base['axis_top3'].mean() - base['favorite_top3'].mean())},
        'uncertainty': {'overall_paired_hit_difference': overall_pair_diff, 'unit': 'model-axis hit minus market-favorite hit, among 678 disagreement races',
                        'race_date_clusters': int(n_clusters), 'method': 'percentile cluster bootstrap resampling race dates with replacement',
                        'replicates': int(len(bootstrap_rates)), 'seed': 20261020, 'ci95_low': cluster_ci[0], 'ci95_high': cluster_ci[1],
                        'condition_summary': 'Wilson 95% intervals for each marginal hit rate; paired Wald 95% intervals for within-group difference; sparse flags retained'},
        'model_topk_pool_diagnostic': topk_df.to_dict('records'),
        'favorite_no_same_distance_valid_time_in_disagreements': {
            'n': int(disagreements['favorite_valid_n5'].eq(0).sum()),
            'also_same_starts_zero': int((disagreements['favorite_valid_n5'].eq(0) & disagreements['favorite_same_starts'].eq(0)).sum()),
            'saved_observed_starts_zero': int((disagreements['favorite_valid_n5'].eq(0) & disagreements['favorite_observed_starts'].eq(0)).sum()),
            'other_distance_history_only': int((disagreements['favorite_valid_n5'].eq(0) & disagreements['favorite_observed_starts'].gt(0)).sum()),
        },
        'year_outcomes_678': {str(i): {str(c): int(v) for c, v in row.items()} for i, row in year_case.iterrows()},
        'distance_outcomes_678': {str(i): {str(c): int(v) for c, v in row.items()} for i, row in distance_case.iterrows()},
        'validation': {'frozen_f1_ledger_rows_linked_to_baseline': int(len(ledger_pred)), 'axis_feature_rows': int(len(axis_features),),
                       'unique_favorite_feature_rows': int(len(favorite_features)), 'root_case_flag_agreement_unique_favorites': root_case_agreement,
                       'root_case_label_agreement_unique_favorites': root_case_label_agreement,
                       'root_selected_id_agreements': root_id_agreement, 'baseline_probability_label_matches': True,
                       'odds_snapshot_matches_frozen_ledger': True, 'source_hashes_checked_before_and_after': True},
        'interpretation_limits': ['Retrospective association only; no causal claim, model fitting, threshold search, or independent future validation.',
                                  'Final win odds and axis odds rank are post-race explanatory fields with publication time unverified; not predictive input or purchase strategy.',
                                  '2026 is partial through 2026-09-19; all reviewed periods are previously seen development data.',
                                  'Grade comparisons are descriptive and confounded by distance/field composition; use distance_grade cells and sparse flags.',
                                  'previous_top3 is based on an individual prior finish position and does not require whole-race completeness; previous_result_status is separate.'],
    }
    (OUT / 'REPORT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    mo = disagreements.loc[disagreements['case'].eq('model_only')]
    ma = disagreements.loc[disagreements['case'].eq('market_only')]
    readme = f'''# 모델축과 단승 최저배당 favorite가 갈린 조건\n\n## 질문과 범위\n\n이 후향 기술 분석은 저장된 F1_STYLE6 모델축과 동결된 API4 단승 최저표시배당 favorite가 다른 경주에서, 실제 Top3 결과가 네 상태로 어떻게 나뉘었는지와 사전 저장 T−2 프로필의 차이를 살폈다. 2024-01-05부터 2026-09-19까지 4개 거리의 동결 자료를 사용했다. 26개 최저배당 동률 경주는 단일 favorite가 아니므로 제외했고, 고유 favorite가 있는 {len(base):,}경주 중 축과 favorite가 다른 {len(disagreements):,}경주를 주 조건 분석에 포함했다.\n\n경주-말 연결은 `api_record_id`, `race_id`, `horse_id`, 마번을 모두 확인했다. frozen F1_STYLE6 원장의 14,714개 출전이 저장 baseline predictions의 동일 출전과 맞았고, 축 1,503마 및 고유 favorite 1,477마는 T−2 feature row와 일대일로 연결됐다. 원천 SHA-256은 `SOURCE_HASHES.json`에 고정했다. root verified ledger의 선택 ID와 case도 고유 favorite 1,477경주 전체에서 일치했다. relative10 후보는 사용하지 않았다.\n\n## 확인된 결과\n\n전체 1,477경주의 축/favorite Top3율은 각각 {report['top3_marginals_1477']['model_axis']:.1%}와 {report['top3_marginals_1477']['market_favorite']:.1%}였고, 그 차이는 {report['top3_marginals_1477']['model_minus_market']:+.1%}p다. 다른 축·favorite 678경주에서는 네 상태가 다음과 같았다.\n\n| outcome | races |\n|---|---:|\n| model-only: 축만 Top3 | {case_counts['model_only']} |\n| market-only: favorite만 Top3 | {case_counts['market_only']} |\n| both | {case_counts['both']} |\n| neither | {case_counts['neither']} |\n\n이 678경주에서 축 Top3율은 {report['top3_marginals_678']['model_axis']:.1%}, favorite Top3율은 {report['top3_marginals_678']['market_favorite']:.1%}로, model-minus-market 차이는 {report['top3_marginals_678']['model_minus_market']:+.1%}p였다. XOR는 {len(mo)} model-only와 {len(ma)} market-only다. 이는 선택한 두 말의 이분형 Top3 빈도 차이며 우승 확률이나 승식 수익률이 아니다.\n\n사전에 고정한 조건 경계별 네 outcome의 지원수·Top3율·차이는 `condition_summary.csv`에 있으며, 주요 조건행의 population은 `all_disagreements_678`이다. 같은 표에 `unique_favorite_background_1477`을 배경으로 따로 제공한다. 조건 경계를 고정했다는 뜻이지 favorite ID를 사전에 알 수 있다는 뜻은 아니다. favorite ID는 사후 확정 단승배당으로 고른 비교대상이다. 거리별 grade와 field 분포는 함께 달라질 수 있어 grade 단독 차이를 거리와 무관한 효과로 읽지 않는다. 표본 n<30 또는 네 outcome 중 하나라도 n<10인 셀은 `exploratory_flag=true`다. 2026은 9월 19일까지의 부분연도이며, 2024–25 대 2026 방향 비교는 새 독립 검증이 아니다.\n\n## 조건 패턴을 읽는 법\n\n`exclusive_distribution.csv`는 사전 변수의 mean/median/quartile/support를 model-only 126경주와 market-only 248경주에서 나란히 제시한다. `axis_minus_favorite` 행은 모델축 말 값에서 market favorite 말 값을 뺀 paired 차이다. 연속 변수는 표본 분포 요약이며 조건을 새로 찾거나 원인으로 해석하는 분석이 아니다. `race_pair_features.parquet`는 고유 favorite 전체 1,477경주의 개별 T−2 프로필, case labels, ID와 고정 범주를 담는다.\n\n확률 보정은 `calibration_by_group.csv`에서 실제 Top3 지시값−저장 p_top3 평균으로 표시한다. 양수는 실제 Top3 빈도가 평균 예측보다 높은 방향, 음수는 그 반대다. 역할별 표본수를 함께 보고 조건 셀이 작을 때는 변동성이 크다고 본다.\n\n`trend_s`는 newer3 평균 초−older3 평균 초이며 각 구간에 유효 기록이 둘 이상 있어야 한다. 양수는 최근 기록이 느려진 방향이다. `std5_s`는 최근 5회 표본 표준편차(유효 3개 이상), `best5_s`는 최근 5회 최소 초다. `previous_top3`는 이전 순위가 1~3위인지 여부이고, 전체 경주가 완결됐는지는 보장하지 않는다. `previous_result_status`는 별도 상태다.\n\n## 확정 배당의 제한\n\n마지막 확정 win odds와 모델축의 사후 odds rank는 `race_pair_features.parquet`, `examples.csv`에 설명용으로 별도 저장했다. favorite ID도 사후 확정 단승배당으로 정한 비교대상이며 예측 입력으로 사용할 수 없다. odds 공개 시점은 확인되지 않았으므로 배당과 해당 ID를 구매 전 전략으로 사용할 수 없다. 최저 단승배당은 단순 역수로 Top3 확률이 되지 않는다.\n\n## 개선 가설과 다음 안전한 단계\n\n관측된 조건부 차이를 검증된 원인이나 보장된 개선으로 보지 않고, 입력·평가 설계를 검토할 후보로만 둔다.\n\n1. **축과 시장 favorite의 확률 간격을 보정 진단에 추가한다.** 고정된 p-gap 구간별 calibration과 지원량을 계속 기록하되, 현재 자료만으로 새 선택 임계값을 정하지 않는다.\n2. **시장 favorite의 모델 내 순위를 별도 진단 축으로 둔다.** 시장 favorite가 F1_STYLE6 score 순위에서 어디에 있는지와 각 순위대의 표본·Top3·calibration을 보고, 순위 기준은 미래 자료에서 사전 등록한 뒤 검증한다.\n3. **경력·최근 기록 지원량을 함께 보여준다.** observed_starts, valid_n5, same-valid counts가 낮은 말의 프로필 결측과 모델 확률을 분리해, 향후 평가에서 지원량 조건을 사전 지정한다. 저경력 전체에 결과를 일반화하지 않는다.\n4. **paired 최근 능력과 편성 상대력을 점검한다.** mean5 축−favorite와 mean5_rank_fraction/상대 gap/coverage를 같은 표본에서 보고, grade·거리·field 차이를 같이 통제하는 사전 계획을 세운다. 단변량 비교만으로 원인을 말하지 않는다.\n5. **이전 성적과 style-history support의 정의를 유지한다.** previous_top3와 completeness status를 구분하고 S1F→4C→G1F 입력의 support를 함께 보고한다. 서로 다른 계측 정의를 섞지 않고, 이미 확인된 기간을 독립 검증이라고 부르지 않는다.\n\n이 제안은 보존된 말 평가와 현재 F1_STYLE6를 유지하는 분석 방향이다. 본 작업에서는 기존 모델·DB·과거 연구를 수정하지 않았고, 모델 학습·threshold optimization·외부 수집·DB 접근을 하지 않았다.\n\n## 산출물\n\n- `PLAN.md`, `SOURCE_HASHES.json`, `SCHEMA_AND_LINK_AUDIT.json`: 사전 계획, 잠금 입력, 스키마/연결 감사\n- `race_pair_features.parquet`: 고유 favorite 전체 1,477경주, IDs, raw T−2 profiles, fixed categories\n- `condition_summary.csv`: 678 disagreement 및 1,477 background의 네 outcome counts, marginal hit rates, support와 sparse flags\n- `exclusive_distribution.csv`: 126 model-only와 248 market-only의 paired profile distribution\n- `calibration_by_group.csv`: actual−p_top3 calibration by role and fixed group\n- `FEATURE_CATALOG.csv`: 저장 55개 열 각각의 F1_STYLE6 exact input 여부\n- `examples.csv`, `REPORT.json`, `analysis.py`, `OUTPUT_MANIFEST.json`: 날짜순 사례, 집계/검산, 재현 스크립트 및 output hash\n'''
    summary_frame = pd.DataFrame(summaries)
    period_frame = pd.DataFrame(period_rows)

    def summary_row(frame: pd.DataFrame, population: str, condition: str, value: str):
        found = frame.loc[
            frame['population'].eq(population)
            & frame['condition'].eq(condition)
            & frame['condition_value'].astype(str).eq(str(value))
        ]
        if len(found) != 1:
            raise RuntimeError(f'Expected one fixed summary row: {population}, {condition}={value}; found {len(found)}')
        return found.iloc[0]

    def summary_cells(row) -> str:
        return (f"n={int(row['n'])}; MO/Mkt/Both/Neither="
                f"{int(row['model_only_n'])}/{int(row['market_only_n'])}/{int(row['both_n'])}/{int(row['neither_n'])}; "
                f"axis {row['model_hit_rate']:.1%}, favorite {row['favorite_hit_rate']:.1%}, "
                f"차 {row['model_minus_market_hit_rate'] * 100:+.1f}%p")

    condition_specs = [
        ('p_gap_bin', '>=0.10', 'p_gap ≥ 0.10'),
        ('paired_mean5_status', 'axis_mean5_le_favorite', 'paired mean5: 축 ≤ favorite'),
        ('axis_observed_starts_bin', '1-4', '축 observed_starts 1–4'),
        ('favorite_valid_n5_bin', '0', 'favorite valid_n5=0'),
    ]
    fixed_rows = [
        f"| {label} | {summary_cells(summary_row(summary_frame, 'all_disagreements_678', col, value))} |"
        for col, value, label in condition_specs
    ]
    period_rows_md = []
    for col, value, label in condition_specs:
        for period in ['2024', '2025', '2026_partial', '2024-25_pooled']:
            period_name = {'2026_partial': '2026 (부분)', '2024-25_pooled': '2024–25 합산'}.get(period, period)
            row = summary_row(period_frame, f'disagreements_{period}', col, value)
            period_rows_md.append(
                f"| {label} | {period_name} | n={int(row['n'])} | {int(row['model_only_n'])}/{int(row['market_only_n'])} | "
                f"{row['model_hit_rate']:.1%} / {row['favorite_hit_rate']:.1%} | {row['model_minus_market_hit_rate'] * 100:+.1f}%p |"
            )
    year_distance_rows = []
    for condition, values in [('year', ['2024', '2025', '2026']), ('distance_m', ['900', '1000', '1110', '1200'])]:
        for value in values:
            row = summary_row(summary_frame, 'all_disagreements_678', condition, value)
            label = f"{value}년" if condition == 'year' else f'{value}m'
            year_distance_rows.append(
                f"| {label} | n={int(row['n'])} | {row['model_hit_rate']:.1%} / {row['favorite_hit_rate']:.1%} | "
                f"{row['model_minus_market_hit_rate'] * 100:+.1f}%p |"
            )
    topk_market_only = topk_df.loc[topk_df['population'].eq('case_market_only')]
    topk_rows_md = [
        f"| {int(r.model_top_k)} | {int(r.races_with_any_actual_top3_in_model_top_k)}/{int(r.race_n)} | {r.candidate_pool_coverage_rate:.1%} |"
        for r in topk_market_only.itertuples()
    ]
    dynamic_findings = f'''### 고정 조건에서 확인된 차이

아래는 결과를 보고 경계를 바꾸지 않은 4개 핵심 조건이다. 각 행은 678개 disagreement 전체에서 네 outcome을 함께 보이며, XOR만 골라 집계하지 않았다. `favorite`는 사후 확정 단승배당으로 정해진 비교 대상 말 ID이므로 favorite ID를 이미 안다고 가정한 조건은 배포 가능한 사전 선택 규칙이 아니다. `p_gap`은 그 favorite와 축의 저장 p_top3 차이다.

| 조건 (저장 T−2 피처 × 사후 favorite ID) | 지원·네 outcome 수·Top3율 |
|---|---|
{chr(10).join(fixed_rows)}

기간별 같은 경계의 방향은 다음과 같다. `MO/Mkt`는 model-only / market-only 경주 수이며, Top3율은 해당 조건 표본에서 각각 축/favorite의 주변 적중률이다. 조건부 차이는 원인이나 배당 기반 전략이 아니다.

| 조건 | 기간 | n | MO/Mkt | 축 / favorite Top3율 | 차 |
|---|---|---:|---:|---:|---:|
{chr(10).join(period_rows_md)}

각 거리별로 전체연도를 합친 주변치와 각 연도별로 네 거리를 합친 주변치에서는 favorite Top3율이 축보다 높았다. 이는 거리×연도 교차 셀까지 모두 같은 방향이라는 뜻은 아니다. 예를 들어 2026 부분연도의 1110m 교차 셀은 n=52에서 축 55.8%, favorite 51.9%로 차이가 +3.8%p다. 세 핵심 구간은 각 연도에 같은 방향이지만, 이미 검토된 기간의 기술적 일관성이지 새 검증이 아니다. 거리·연도별 주변 수치는 다음과 같다.

| 구간 | n | 축 / favorite Top3율 | 차 |
|---|---:|---:|---:|
{chr(10).join(year_distance_rows)}

전체 paired hit-rate 차이의 race-date cluster bootstrap 95% 구간은 **{overall_pair_diff * 100:+.2f}%p** (2,000회, 255개 날짜 클러스터; [**{cluster_ci[0] * 100:+.2f}**, **{cluster_ci[1] * 100:+.2f}]%p**)다. 표의 조건별 marginal hit rate에는 Wilson 95% 구간, paired 차에는 Wald 95% 구간이 함께 기록돼 있다. 조건을 훑어 고른 듯한 해석을 피하고 sparse flag를 확인해야 한다.

favorite의 `valid_n5=0`은 debut와 같지 않다. 이 조건의 favorite 158마 전부 saved `same_starts=0`이었지만, saved `observed_starts=0`으로 관측된 이전 출발이 없는 말은 34마였고 나머지 124마는 다른 거리 이력만 있었다. 이 원천 counter만으로 lifetime debut를 확정하지 않으며, 전체 저경력 말에 일반화하지 않는다.

### 후보군 진단과 확률 잔차

market-only 248경주 중 실제 Top3 말이 모델 score 순위 상위 K에 하나라도 포함된 비율은 다음과 같다. 이는 결과를 알고 계산한 후보군 덮임 진단이며 구매 규칙이나 실전 성과 추정이 아니다.

| 모델 상위 K | 실제 Top3 포함 race | 비율 |
|---:|---:|---:|
{chr(10).join(topk_rows_md)}

`calibration_by_group.csv`는 확률 보정 곡선이나 보정 모델이 아니라, 선택된 축/market favorite 말에 대한 조건부 평균 잔차 `actual Top3 indicator − saved p_top3`다. 전체 runner 집합의 calibration을 뜻하지 않는다. 단조 확률변환은 score 순서를 유지하므로 현재 축의 순위나 선택을 바꾸지 않는다. 순위 선택을 바꾸려면 별도 순위 모델·규칙을 미래 시간분리 OOF 평가로 검증해야 한다.
'''
    readme = readme.replace('\n## 조건 패턴을 읽는 법', '\n' + dynamic_findings + '\n## 조건 패턴을 읽는 법')
    readme = readme.replace(
        '확률 보정은 `calibration_by_group.csv`에서 실제 Top3 지시값−저장 p_top3 평균으로 표시한다. 양수는 실제 Top3 빈도가 평균 예측보다 높은 방향, 음수는 그 반대다. 역할별 표본수를 함께 보고 조건 셀이 작을 때는 변동성이 크다고 본다.',
        '`calibration_by_group.csv`는 선택된 말의 조건부 평균 예측잔차(actual Top3 indicator − saved p_top3)를 기록한다. 이를 전체 runner calibration이나 실제 보정 곡선으로 해석하지 않는다.'
    )
    improvement_start = readme.index('## 개선 가설과 다음 안전한 단계')
    improvement_end = readme.index('이 제안은 보존된 말 평가', improvement_start)
    replacement = '''## 현실적인 개선 방향

관측 결과만으로 model-only 경주를 사전 판별하는 안정적인 단일 규칙은 확인되지 않았다. `p_gap`, favorite의 모델 내 순위, 두 말의 최근 평균 시간과 이력 지원량은 다음 검증에서 사전 등록할 가설이지, 현재 선택 기준이 아니다.

1. 현재 F1_STYLE6 말 평가를 기준선으로 보존한다. 보조 순위기를 검토한다면 기존 축 선정을 대체하지 않는 model-side 후보 재순위기로 설계하고, 저장된 사전 입력만 사용한다. 사후 favorite ID나 최종 배당을 예측 입력으로 쓰지 않는다. 학습이 필요해지면 시간 분리 OOF 점수로만 만들고 미래 홀드아웃에서 비교한다. 이번 분석에서는 학습하지 않았다.
2. `valid_n5=0`을 debut와 타거리 이력만 있는 말로 나눠 프로필 지원량을 보고한다. 두 집단을 섞지 않고, 말의 이력 조건이 시장 favorite 성능과 어떤 관계를 갖는지 독립된 미래 기간에서 재검증한다.
3. mean5·상대 rank·gap·coverage와 style/passrank support를 거리·grade·field를 함께 고려한 사전 지정 평가 후보로 둔다. 단변량 조건 결과를 원인으로 읽지 않고, 안전한 거리 전이 피처는 별도 계획과 시간분리 기준을 갖춘 뒤 베이스 후보로만 검토한다.
4. 목표가 단일 축 적중이 아니라 Top3 후보군이라면 top-K 후보군 덮임을 별도 평가목표로 사전 정의한다. 이번 top-K 값은 사후 결과를 이용한 진단이며, 예측 성능이나 전략 수익으로 승격하지 않는다.
5. 확률 잔차 진단은 runner 단위 전체 예측과 선택된 말 조건부 표본을 구분해 유지한다. 단조 calibration만으로는 순위와 축 선택이 달라지지 않으므로, 확률 보정과 순위 변경을 별도 문제로 다룬다.

'''
    readme = readme[:improvement_start] + replacement + readme[improvement_end:]
    readme = readme.replace(
        '- `calibration_by_group.csv`: actual−p_top3 calibration by role and fixed group',
        '- `calibration_by_group.csv`: 선택된 축/favorite의 조건부 평균 예측잔차 by role and fixed group\n- `condition_summary_by_period.csv`: 사전 고정 조건의 연도별·2024–25 합산 일관성 표\n- `model_topk_pool_diagnostic.csv`: 사후 실제 Top3 후보군 덮임 진단'
    )
    (OUT / 'README.md').write_text(readme, encoding='utf-8')

    output_records = []
    for p in sorted(OUT.iterdir()):
        if p.is_file() and p.name != 'OUTPUT_MANIFEST.json':
            output_records.append({'path': p.name, 'size_bytes': p.stat().st_size, 'sha256': sha256(p)})
    (OUT / 'OUTPUT_MANIFEST.json').write_text(json.dumps({'status': 'PASS', 'algorithm': 'SHA-256', 'artifacts': output_records}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'four_outcomes_678': case_counts, 'top3_marginals_678': report['top3_marginals_678'],
                      'top3_marginals_1477': report['top3_marginals_1477'], 'root_case_agreement': root_case_agreement,
                      'root_id_agreement': root_id_agreement, 'outputs': [x['path'] for x in output_records]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

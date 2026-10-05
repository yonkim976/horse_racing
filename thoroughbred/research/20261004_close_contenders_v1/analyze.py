"""Read-only diagnosis using frozen research predictions and registered weights."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'outputs'
RESEARCH = ROOT / 'thoroughbred/research/20261004_pace_finish_stack_v1/outputs'
DATA = ROOT / 'data/research'
REGISTRY = ROOT / 'config/prediction_model_registry.json'
KEYS = ['race_key', 'program_no', 'horse_id']

def sha(p):
    with p.open('rb') as f:
        h = hashlib.file_digest(f, 'sha256')
    return h.hexdigest()

def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def operational():
    sys.path.insert(0, str(DATA / 'thoroughbred_three_targets_20260918_v3/code'))
    import targets_core as tc
    am = tc.load_bundle(DATA / 'thoroughbred_offline_20260918_v5/windows/models/2026H2/rolling_all')
    bc = tc.load_bundle(DATA / 'thoroughbred_followup_20260918_v4/model/models/2026/top3_growth_strength')
    win = tc.load_v2_win_bundle(DATA / 'thoroughbred_win_research_20260918_v2/models/2026/H3_relative')
    for model in (am, bc, win):
        training = model.metadata['training']
        latest = training.get('max_date', training.get('max_race_date'))
        assert pd.Timestamp(latest) < pd.Timestamp('2026-01-01')
    assert pd.Timestamp(win.metadata['calibration_period']['max']) < pd.Timestamp('2026-01-01')
    assert am.metadata['fit_cutoff'] == '2025-12-31'
    f = pd.read_parquet(DATA / 'thoroughbred_three_targets_20260918_v3/prepared_context.parquet')
    f['race_date'] = pd.to_datetime(f.race_date)
    f = f[f.race_date.between('2026-01-01', '2026-09-13') & f.venue_code.isin(['SEOUL', 'BUSAN'])].copy()
    extra = pd.read_parquet(DATA / 'thoroughbred_followup_20260918_v4/model/strict_features.parquet')
    extra['race_date'] = pd.to_datetime(extra.race_date)
    f = f.merge(extra, on=['race_id', 'hr_no', 'race_date'], validate='one_to_one')
    f = f.sort_values(['race_date', 'race_id', 'chul_no', 'hr_no']).reset_index(drop=True)
    assert not f.duplicated(['race_id', 'hr_no']).any()
    # Final starters: same risk set as the saved final_starters win evaluation.
    f = f[f.starter_eligible.astype(bool)].reset_index(drop=True)
    scores_a = tc.raw_scores(am, f)['top3']
    scores_b = tc.raw_scores(bc, f)['top3']
    scores_w = tc.raw_scores(win, f)['win']
    runners, combos, exclusions = [], [], []
    errors = []
    for rid, idx in f.groupby('race_id', sort=False).indices.items():
        g = f.iloc[idx]
        outcomes = pd.to_numeric(g.target_finish_order, errors='coerce').to_numpy()
        if len(g) < 5 or any((outcomes == k).sum() != 1 for k in (1, 2, 3)):
            exclusions.append(rid)
            continue
        venue = g.venue_code.iloc[0]
        wt = win.metadata['temperature_by_venue'][venue]
        ja = tc.top3_set_joint(scores_a[idx], scores_w[idx], am.metadata['temperature_by_target_and_venue']['A'][venue], wt)
        jb = tc.top3_set_joint(scores_b[idx], scores_w[idx], bc.metadata['temperature_by_target_and_venue']['B'][venue], wt)
        errors.append(max(*tc.probability_invariants(ja).values(), *tc.probability_invariants(jb).values()))
        pwin = np.bincount(ja.orders[:, 0], weights=ja.order_probability, minlength=len(g))
        ptop2 = sum(np.bincount(ja.orders[:, i], weights=ja.order_probability, minlength=len(g)) for i in (0, 1))
        for i, (_, r) in enumerate(g.iterrows()):
            runners.append(dict(race_key=rid, program_no=int(r.chul_no), horse_id=str(r.hr_no),
                meet=1 if venue == 'SEOUL' else 3, race_date=str(r.race_date.date()), evaluation_year=2026,
                variant='operating_exact_2026', outcome=float(outcomes[i]), field_size=len(g),
                prob_win=float(pwin[i]), prob_top2=float(ptop2[i]), prob_top3=float(ja.inclusion_probability[i]),
                raw_a_score=float(scores_a[idx][i]), raw_bc_score=float(scores_b[idx][i]), raw_win_score=float(scores_w[idx][i])))
        truth = set(g.loc[g.target_finish_order.between(1, 3), 'chul_no'].astype(int))
        for rank, j in enumerate(np.argsort(-jb.set_probability, kind='stable')[:6], 1):
            programs = sorted(g.iloc[jb.sets[j]].chul_no.astype(int))
            combos.append(dict(race_key=rid, meet=1 if venue == 'SEOUL' else 3, evaluation_year=2026,
                variant='operating_exact_2026', selection_rank=rank, programs=','.join(map(str, programs)),
                probability=float(jb.set_probability[j]), hit=int(set(programs) == truth)))
    audit = dict(input_races=int(f.race_id.nunique()), evaluated_races=len(errors), excluded_races=exclusions,
        max_probability_error=max(errors), profile='thoroughbred-main-20260919-v1',
        range=['2026-01-01', '2026-09-13'], minimum_starters=5, retrospective_reconstructed_card=True,
        A_training=am.metadata['training'], BC_training=bc.metadata['training'], WIN_training=win.metadata['training'])
    return pd.DataFrame(runners), pd.DataFrame(combos), audit

def describe_races(runners, combos):
    rows = []
    hit_lookup = combos.groupby(['variant', 'race_key']).hit.max()
    for (variant, rid), g in runners.groupby(['variant', 'race_key'], sort=False):
        g = g.sort_values('program_no')
        actual = g[g.outcome.between(1, 3)]
        assert len(actual) == 3 and set(actual.outcome) == {1., 2., 3.}
        w = g.sort_values(['prob_win', 'program_no'], ascending=[False, True])
        a = g.sort_values(['prob_top3', 'program_no'], ascending=[False, True])
        winner = int(g.loc[g.outcome.eq(1), 'program_no'].iloc[0])
        podium = set(actual.program_no)
        p = w.prob_win.to_numpy()
        row = dict(variant=variant, race_key=rid, meet=int(g.meet.iloc[0]),
            evaluation_year=int(g.evaluation_year.iloc[0]), race_date=str(pd.Timestamp(g.race_date.iloc[0]).date()),
            field_size=len(g), leader_win=p[0], gap12=p[0]-p[1],
            gap34_top3=float(a.prob_top3.iloc[2]-a.prob_top3.iloc[3]),
            trio6_hit=int(hit_lookup.loc[(variant, rid)]),
            winrank1_hit=int(winner == int(w.program_no.iloc[0])), axis_top3_hit=int(a.outcome.iloc[0] <= 3),
            count_15_25=int(g.prob_win.between(.15, .25).sum()))
        for delta in (.03, .05):
            name = f'close{int(delta*100)}'
            cluster = w[w.prob_win.ge(p[0]-delta-1e-12)]
            members = set(cluster.program_no)
            row.update({name+'_count':len(cluster), name+'_mass':float(cluster.prob_win.sum()),
                        name+'_winner':int(winner in members), name+'_podium':int(podium <= members)})
        for k in (3, 4, 5, 6, 7):
            row[f'win_top{k}'] = int(winner in set(w.head(k).program_no))
            row[f'a_top{k}_podium'] = int(podium <= set(a.head(k).program_no))
        row['outside_a5_count'] = len(podium-set(a.head(5).program_no))
        row['miss_outside_a5'] = int(not row['trio6_hit'] and row['outside_a5_count'] > 0)
        row['miss_inside_a5'] = int(not row['trio6_hit'] and row['outside_a5_count'] == 0)
        rows.append(row)
    return pd.DataFrame(rows)

def aggregate(races):
    values = []
    selectors = [('all', lambda g: np.ones(len(g), bool)),
        ('gap12_le_2pp', lambda g: g.gap12.le(.02+1e-12)),
        ('gap12_2_to_5pp', lambda g: g.gap12.gt(.02+1e-12)&g.gap12.le(.05+1e-12)),
        ('gap12_gt_5pp', lambda g: g.gap12.gt(.05+1e-12)),
        ('leader_le_25pct', lambda g: g.leader_win.le(.25)),
        ('two_or_more_15_to_25pct', lambda g: g.count_15_25.ge(2)),
        ('close5_one', lambda g: g.close5_count.eq(1)),
        ('close5_two', lambda g: g.close5_count.eq(2)),
        ('close5_threeplus', lambda g: g.close5_count.ge(3))]
    rates = [c for c in races if c.startswith(('win_top', 'a_top', 'miss_')) or c in
        ['trio6_hit', 'winrank1_hit', 'axis_top3_hit', 'close3_winner', 'close3_podium', 'close5_winner', 'close5_podium']]
    for variant, block in races.groupby('variant'):
        for meet in (0, 1, 3):
            b = block if meet == 0 else block[block.meet.eq(meet)]
            for year in (0, *sorted(b.evaluation_year.unique())):
                g = b if year == 0 else b[b.evaluation_year.eq(year)]
                for name, selector in selectors:
                    s = g[selector(g)]
                    if s.empty: continue
                    row = dict(variant=variant, meet=meet, year=int(year), group=name, races=len(s), total_races=len(g), fraction=len(s)/len(g))
                    row.update({c:float(s[c].mean()) for c in rates})
                    row.update(close5_mean_count=float(s.close5_count.mean()), close5_mean_mass=float(s.close5_mass.mean()),
                        leader_win_mean=float(s.leader_win.mean()), field_size_mean=float(s.field_size.mean()),
                        failures=int((1-s.trio6_hit).sum()),
                        failure_outside_a5_share=float(s.miss_outside_a5.sum()/max(1,(1-s.trio6_hit).sum())),
                        failure_inside_a5_share=float(s.miss_inside_a5.sum()/max(1,(1-s.trio6_hit).sum())))
                    values.append(row)
    return pd.DataFrame(values)

def main():
    if OUT.exists(): raise FileExistsError('Refusing diagnostic output overwrite')
    paths = [REGISTRY, RESEARCH/'runner_predictions.parquet', RESEARCH/'recommendations.parquet',
        DATA/'thoroughbred_three_targets_20260918_v3/prepared_context.parquet',
        DATA/'thoroughbred_followup_20260918_v4/model/strict_features.parquet']
    for folder, name in [
        ('thoroughbred_offline_20260918_v5/windows/models/2026H2/rolling_all', 'top3.txt'),
        ('thoroughbred_followup_20260918_v4/model/models/2026/top3_growth_strength', 'top3.txt'),
        ('thoroughbred_win_research_20260918_v2/models/2026/H3_relative', 'model.txt')]:
        paths += [DATA/folder/name, DATA/folder/'metadata.json']
    hashes = {str(p.relative_to(ROOT)):sha(p) for p in paths}
    assert hashes['config/prediction_model_registry.json'] == '944e4aad25c99d3d346dab23c7f7596c216d8722a548dea2c7c07abf9b10b70b'
    op, oc, audit = operational()
    research = pd.read_parquet(RESEARCH/'runner_predictions.parquet')
    research = research[research.variant.isin(['context','records'])].copy()
    rc = pd.read_parquet(RESEARCH/'recommendations.parquet')
    rc = rc[rc.variant.isin(['context','records'])].copy()
    runners = pd.concat([research, op], ignore_index=True)
    combos = pd.concat([rc, oc], ignore_index=True)
    assert not runners.duplicated(['variant', *KEYS]).any()
    assert (combos.groupby(['variant', 'race_key']).size() == 6).all()
    races = describe_races(runners, combos)
    results = aggregate(races)
    assert ((races.miss_outside_a5+races.miss_inside_a5+races.trio6_hit) == 1).all()
    assert all(sha(ROOT/k)==v for k,v in hashes.items())
    OUT.mkdir()
    op.to_parquet(OUT/'operating_runner_predictions.parquet', index=False)
    oc.to_parquet(OUT/'operating_trio6.parquet', index=False)
    races.to_csv(OUT/'race_diagnostics.csv', index=False)
    results.to_csv(OUT/'group_metrics.csv', index=False)
    dump(OUT/'audit.json', dict(source_hashes=hashes, operating=audit, research_races=int(races.variant.eq('context').sum()),
        source_unchanged=True, no_training=True, no_database_writes=True))
    shown = results[results.meet.eq(0)&results.year.eq(0)&results.group.isin(['all','gap12_le_2pp','two_or_more_15_to_25pct','close5_threeplus'])]
    print(shown[['variant','group','races','fraction','win_top3','a_top3_podium','a_top5_podium','a_top6_podium','trio6_hit','close5_mean_count','close5_winner','close5_podium','failure_outside_a5_share']].to_string(index=False))

if __name__ == '__main__': main()

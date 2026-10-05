"""Independent probability math and outcome/rank checks; no fitting or DB writes."""
from pathlib import Path
from itertools import combinations, permutations
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / 'outputs'
RESEARCH = ROOT / 'thoroughbred/research/20261004_pace_finish_stack_v1/outputs'
checks = 0
maximum_error = 0.

def check(condition):
    global checks
    checks += 1
    if not condition: raise AssertionError(f'Failed independent check {checks}')

def close(left, right):
    global maximum_error
    error = float(np.max(np.abs(np.asarray(left)-np.asarray(right))))
    maximum_error = max(maximum_error, error)
    check(error < 1e-11)

def hash_file(path):
    with path.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()

def main():
    audit = json.loads((OUT/'audit.json').read_text())
    for path, digest in audit['source_hashes'].items(): check(hash_file(ROOT/path) == digest)
    op = pd.read_parquet(OUT/'operating_runner_predictions.parquet')
    oc = pd.read_parquet(OUT/'operating_trio6.parquet')
    original = pd.read_parquet(RESEARCH/'runner_predictions.parquet')
    original = original[original.variant.isin(['records','context'])]
    rc = pd.read_parquet(RESEARCH/'recommendations.parquet')
    rc = rc[rc.variant.isin(['records','context'])]
    runners = pd.concat([original, op], ignore_index=True)
    recs = pd.concat([rc, oc], ignore_index=True)
    saved = pd.read_csv(OUT/'race_diagnostics.csv').set_index(['variant','race_key'])
    groups = pd.read_csv(OUT/'group_metrics.csv')
    check(len(saved) == runners[['variant','race_key']].drop_duplicates().shape[0])
    rec_groups = dict(tuple(recs.groupby(['variant','race_key'])))
    for key, g in runners.groupby(['variant','race_key']):
        q = saved.loc[key]
        w = sorted(g.to_dict('records'), key=lambda r:(-r['prob_win'], r['program_no']))
        a = sorted(g.to_dict('records'), key=lambda r:(-r['prob_top3'], r['program_no']))
        actual = {r['program_no'] for r in w if r['outcome'] in (1,2,3)}
        winner = next(r['program_no'] for r in w if r['outcome'] == 1)
        check(len(actual) == 3)
        for k in (3,4,5,6,7):
            check(q[f'win_top{k}'] == int(winner in {r['program_no'] for r in w[:k]}))
            check(q[f'a_top{k}_podium'] == int(actual <= {r['program_no'] for r in a[:k]}))
        for delta in (3,5):
            cluster = [r for r in w if r['prob_win']+delta/100+1e-12 >= w[0]['prob_win']]
            members = {r['program_no'] for r in cluster}
            check(q[f'close{delta}_count'] == len(cluster))
            check(q[f'close{delta}_winner'] == int(winner in members))
            check(q[f'close{delta}_podium'] == int(actual <= members))
        picked = rec_groups[key]
        truth_hit = int(any({int(n) for n in s.split(',')} == actual for s in picked.programs))
        check(q.trio6_hit == truth_hit)
        outsider = len(actual-{r['program_no'] for r in a[:5]})
        check(q.outside_a5_count == outsider)
        check(q.miss_outside_a5 == int(not truth_hit and outsider > 0))
        check(q.miss_inside_a5 == int(not truth_hit and outsider == 0))
        for name, target in [('prob_win',1),('prob_top2',2),('prob_top3',3)]: close(g[name].sum(), target)
    # Independently enumerate sets and orders from persisted operating raw scores.
    data = ROOT/'data/research'
    temps_a = json.loads((data/'thoroughbred_offline_20260918_v5/windows/models/2026H2/rolling_all/metadata.json').read_text())['temperature_by_target_and_venue']['A']
    temps_b = json.loads((data/'thoroughbred_followup_20260918_v4/model/models/2026/top3_growth_strength/metadata.json').read_text())['temperature_by_target_and_venue']['B']
    temps_w = json.loads((data/'thoroughbred_win_research_20260918_v2/models/2026/H3_relative/metadata.json').read_text())['temperature_by_venue']
    for rid, g in op.groupby('race_key'):
        g = g.sort_values('program_no')
        venue = 'SEOUL' if g.meet.iloc[0] == 1 else 'BUSAN'
        n = len(g)
        sets = list(combinations(range(n),3))
        sets_array = np.array(sets)
        weights = np.exp((g.raw_win_score.to_numpy()-g.raw_win_score.max())/temps_w[venue])
        set_prob = {}
        for role, score, temp in [('A',g.raw_a_score,temps_a[venue]),('B',g.raw_bc_score,temps_b[venue])]:
            energies = score.to_numpy()[sets_array].sum(axis=1)/temp
            probs = np.exp(energies-energies.max()); probs /= probs.sum()
            set_prob[role] = probs
        pwin = np.zeros(n); ptop2 = np.zeros(n); ptop3 = np.zeros(n)
        for si, s in enumerate(sets):
            orders = list(permutations(s))
            conditional = np.array([weights[i]/weights.sum()*weights[j]/weights[np.arange(n)!=i].sum()*weights[k]/weights[(np.arange(n)!=i)&(np.arange(n)!=j)].sum() for i,j,k in orders])
            conditional /= conditional.sum()
            for (i,j,k), p in zip(orders, conditional*set_prob['A'][si]):
                pwin[i] += p; ptop2[i] += p; ptop2[j] += p
                ptop3[i] += p; ptop3[j] += p; ptop3[k] += p
        close(pwin,g.prob_win); close(ptop2,g.prob_top2); close(ptop3,g.prob_top3)
        picked = oc[oc.race_key.eq(rid)].sort_values('selection_rank')
        best = np.argsort(-set_prob['B'],kind='stable')[:6]
        expected = [','.join(map(str,sorted(g.iloc[sets_array[j]].program_no.astype(int)))) for j in best]
        check(expected == picked.programs.tolist())
        close(set_prob['B'][best],picked.probability)
    # Verify saved group numerators/denominators independently from race rows.
    selectors = {'all': lambda d:np.ones(len(d),bool), 'gap12_le_2pp':lambda d:d.gap12<=.02+1e-12,
        'gap12_2_to_5pp':lambda d:(d.gap12>.02+1e-12)&(d.gap12<=.05+1e-12),
        'gap12_gt_5pp':lambda d:d.gap12>.05+1e-12,
        'leader_le_25pct':lambda d:d.leader_win<=.25,
        'two_or_more_15_to_25pct':lambda d:d.count_15_25>=2,
        'close5_one':lambda d:d.close5_count==1,
        'close5_two':lambda d:d.close5_count==2,
        'close5_threeplus':lambda d:d.close5_count>=3}
    table = saved.reset_index()
    for r in groups.itertuples():
        g = table[table.variant.eq(r.variant)]
        if r.meet: g = g[g.meet.eq(r.meet)]
        if r.year: g = g[g.evaluation_year.eq(r.year)]
        s = g[selectors[r.group](g)]
        check(r.races == len(s)); check(r.total_races == len(g))
        for col in ['trio6_hit','win_top3','a_top3_podium','a_top5_podium','close5_winner','close5_podium','miss_outside_a5','miss_inside_a5']:
            close(getattr(r,col),s[col].mean())
    for path, digest in audit['source_hashes'].items(): check(hash_file(ROOT/path) == digest)
    result = dict(passed=True, checks=checks, max_numeric_error=maximum_error,
        operating_races=int(op.race_key.nunique()), total_diagnostic_rows=len(saved))
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__ == '__main__': main()

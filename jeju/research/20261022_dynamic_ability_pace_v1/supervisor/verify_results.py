"""Independent model replay, fit-stationarity, seven-pool and bootstrap checks.

Does not import experiment code or fit any estimator. Reads text models and
reconstructs probabilities using the supervisor's explicit remaining sets.
"""
import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import expit

sys.dont_write_bytecode = True
from math_reference import (aggregate, distribution, mixture, rank_loss_derivatives,
                            inverse_temperature_derivatives, score_events,
                            stable_selection, winners)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
STUDY = HERE.parent
OUT = STUDY/'experiment/outputs'
MODEL_DIR = STUDY/'experiment/models'
BOOT = ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy'
STYLE = ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs'
ERRORS = defaultdict(float)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()


def near(name, left, right, tol=1e-10):
    a, b = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    assert a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all(), name
    error = float(np.max(np.abs(a-b))) if a.size else 0.
    ERRORS[name] = max(ERRORS[name], error)
    assert error <= tol, (name, error, tol)


def check_optimum(name, temperature, inverse_gradient):
    assert .35 <= temperature <= 4.
    if temperature == .35:
        assert inverse_gradient <= 2e-5, (name, temperature, inverse_gradient)
    elif temperature == 4.:
        assert inverse_gradient >= -2e-5, (name, temperature, inverse_gradient)
    else:
        assert abs(inverse_gradient) < 2e-5, (name, temperature, inverse_gradient)


def pl_calibration(frame, raw, temperature):
    frame = frame.copy(); frame['_raw'] = raw
    values = []
    for _, g in frame.groupby('race_id', sort=False):
        values.append(inverse_temperature_derivatives(g._raw.to_numpy(), np.argsort(g.finish_position.to_numpy())[:3], temperature))
    return np.mean(values, axis=0)


def binary_calibration(frame, raw, label, temperature):
    known = frame[label].notna().to_numpy()
    y = frame.loc[known, label].to_numpy(float); s = np.asarray(raw)[known]
    p = expit(s/temperature)
    cp = np.clip(p, 1e-12, 1-1e-12)
    loss = -y*np.log(cp)-(1-y)*np.log1p(-cp)
    z = pd.DataFrame({'race': frame.loc[known, 'race_id'].to_numpy(),
                      'loss': loss, 'gradient': s*(p-y), 'hessian': s*s*p*(1-p)})
    return z.groupby('race')[['loss', 'gradient', 'hessian']].mean().mean().to_numpy()


def scenario_inputs(group, gamma):
    l = group.p_early.to_numpy()-group.p_early.mean()
    h = group.p_recovery.to_numpy()-group.p_recovery.mean()
    x0 = np.array([l, h, np.zeros(len(l)), np.zeros(len(l))]).T
    x1 = np.array([l, h, l, h]).T
    a = group.a_utility.to_numpy()
    return a+x0@gamma, a+x1@gamma, x0, x1


def main(check_only=False):
    par = json.loads((OUT/'parameters.json').read_text())
    report = json.loads((OUT/'report.json').read_text())
    receipt = json.loads((OUT/'fit_run_receipt.json').read_text())
    assert receipt['status'] == 'COMPLETED_ONE_APPROVED_FIT_EVALUATE_RUN'
    for item in receipt['output_artifacts']:
        path = ROOT/item['path']
        assert path.is_relative_to(STUDY) and sha(path) == item['sha256']
        assert path.stat().st_size == item['bytes']
    data = pd.read_parquet(STUDY/'inputs/model_inputs.parquet')
    race_data = pd.read_parquet(STUDY/'inputs/race_inputs.parquet')
    oof = pd.read_parquet(OUT/'annual_oos_runner_predictions.parquet')
    race_oof = pd.read_parquet(OUT/'annual_oos_race_predictions.parquet')
    assert len(oof) == 42690 and len(race_oof) == 4271
    assert set(oof.api_record_id) == set(data.loc[data.year >= 2019, 'api_record_id'])
    for frame in (oof, race_oof):
        assert not frame.in_sample.any()
        assert (frame.model_train_max_year == frame.year-2).all()
        assert (frame.calibration_year == frame.year-1).all()
        assert (frame.prediction_year == frame.year).all()
    features = par['features']
    replay_count = calibration_count = 0
    for year in range(2019, 2027):
        fold = par['annual_oos_fold_parameters'][str(year)]
        train = data.loc[data.year <= year-2]
        cal = data.loc[data.year == year-1]
        pred = oof.loc[oof.year == year]
        target = data.set_index('api_record_id').loc[pred.api_record_id]
        assert fold['training_races'] == train.race_id.nunique()
        assert fold['training_runners'] == len(train)
        assert fold['calibration_races'] == cal.race_id.nunique()
        am = lgb.Booster(model_file=str(MODEL_DIR/f'A_{year}.txt'))
        assert am.feature_name() == features['A']
        assert sha(MODEL_DIR/f'A_{year}.txt') == fold['A']['model_sha256']
        raw = am.predict(target[features['A']], raw_score=True, num_threads=2)
        near('A_model_replay', raw, pred.score_a)
        t = fold['A']['temperature']
        near('A_utility', raw/t, pred.a_utility)
        cal_raw = am.predict(cal[features['A']], raw_score=True, num_threads=2)
        loss, grad, _ = pl_calibration(cal, cal_raw, t)
        near('A_calibration_nll', loss, fold['A']['objective_nll'])
        check_optimum(f'A_{year}', t, grad)
        calibration_count += 1; replay_count += len(pred)
        for stem in ('early', 'recovery'):
            phase = fold['phase'][stem]
            m = lgb.Booster(model_file=str(MODEL_DIR/f'PHASE_{stem}_{year}.txt'))
            assert m.feature_name() == features['runner_phase']
            assert sha(MODEL_DIR/f'PHASE_{stem}_{year}.txt') == phase['model_sha256']
            raw = m.predict(target[features['runner_phase']], raw_score=True, num_threads=2)
            near(stem+'_model_replay', raw, pred['logit_'+stem])
            t = phase['temperature']; p = np.clip(expit(raw/t), 1e-12, 1-1e-12)
            near(stem+'_probability', p, pred['p_'+stem])
            cr = m.predict(cal[features['runner_phase']], raw_score=True, num_threads=2)
            loss, grad, _ = binary_calibration(cal, cr, 'label_'+stem, t)
            near(stem+'_calibration_nll', loss, phase['objective_nll'])
            check_optimum(f'{stem}_{year}', t, grad)
            calibration_count += 1; replay_count += len(pred)
        phase = fold['phase']['z']
        m = lgb.Booster(model_file=str(MODEL_DIR/f'PHASE_z_{year}.txt'))
        assert m.feature_name() == features['race_Z']
        assert sha(MODEL_DIR/f'PHASE_z_{year}.txt') == phase['model_sha256']
        rp = race_oof.loc[race_oof.year == year]
        rt = race_data.set_index('race_id').loc[rp.race_id]
        rc = race_data.loc[race_data.year == year-1]
        raw = m.predict(rt[features['race_Z']], raw_score=True, num_threads=2)
        near('z_model_replay', raw, rp.logit_z)
        t = phase['temperature']
        near('z_probability', np.clip(expit(raw/t), 1e-12, 1-1e-12), rp.q_z)
        cr = m.predict(rc[features['race_Z']], raw_score=True, num_threads=2)
        loss, grad, _ = binary_calibration(rc, cr, 'label_z_early_pack_ge2', t)
        near('z_calibration_nll', loss, phase['objective_nll'])
        check_optimum(f'z_{year}', t, grad)
        calibration_count += 1; replay_count += len(rp)
    rz = race_oof.set_index('race_id')
    gamma_checks = []
    for year in (2024, 2025, 2026):
        rf = par['R_reference_fits'][str(year)]
        cr = pd.read_parquet(STYLE/f'F1_STYLE6_{year}/calibration_scores.parquet')
        cr = data.merge(cr, on='api_record_id', how='inner', validate='one_to_one')
        assert cr.year.eq(year-1).all()
        loss, grad, _ = pl_calibration(cr, cr.score, rf['temperature'])
        near('R_calibration_nll', loss, rf['objective_nll'])
        check_optimum(f'R_{year}', rf['temperature'], grad)
        calibration_count += 1
        bf = par['B_vintage_fits'][str(year)]
        gamma = np.array(bf['gamma']['gamma'])
        total_loss, total_grad = 0., np.zeros(4); count = missing = 0
        for rid, g in oof.loc[oof.year <= year-2].groupby('race_id'):
            z = rz.loc[rid, 'label_z_early_pack_ge2']
            if pd.isna(z): missing += 1; continue
            u0, u1, x0, x1 = scenario_inputs(g, gamma)
            u, x = (u1, x1) if z == 1 else (u0, x0)
            loss, grad, _ = rank_loss_derivatives(u, np.argsort(g.finish_position.to_numpy())[:3])
            total_loss += loss; total_grad += x.T@grad; count += 1
        objective = total_loss/count+.005*(gamma@gamma)
        gradient = total_grad/count+.01*gamma
        near('B_gamma_objective', objective, bf['gamma']['objective'])
        assert np.max(np.abs(gradient)) <= 5e-6
        assert bf['gamma_training_races'] == count and bf['gamma_training_races_missing_Z_excluded'] == missing
        gamma_checks.append(dict(year=year, races=count, excluded_missing_z=missing, gradient_inf=float(np.max(np.abs(gradient)))))
        t = bf['temperature_calibration']['temperature']; losses=[]; gradients=[]
        for rid, g in oof.loc[oof.year == year-1].groupby('race_id'):
            u0, u1, _, _ = scenario_inputs(g, gamma)
            actual = np.argsort(g.finish_position.to_numpy())[:3]
            l0, g0, _ = inverse_temperature_derivatives(u0, actual, t)
            l1, g1, _ = inverse_temperature_derivatives(u1, actual, t)
            q = rz.loc[rid, 'q_z']; parts=np.array([(1-q)*math.exp(-l0), q*math.exp(-l1)])
            losses.append(-math.log(parts.sum())); gradients.append(float(parts@np.array([g0,g1])/parts.sum()))
        near('B_calibration_nll', np.mean(losses), bf['temperature_calibration']['objective_nll'])
        check_optimum(f'B_{year}', t, np.mean(gradients)); calibration_count += 1
    print(json.dumps({'phase':'independent_model_and_fit_checks_passed','replayed_outputs':replay_count,'calibrations':calibration_count}), flush=True)
    metrics = pd.read_parquet(OUT/'race_pool_metrics.parquet').set_index(['race_id','arm','pool'])
    selected = pd.read_parquet(OUT/'selected_ticket_ledger.parquet').set_index(['race_id','arm','pool'])
    marginal = pd.read_parquet(OUT/'evaluation_runner_marginals.parquet').set_index(['race_id','arm','horse_number'])
    axis = pd.read_parquet(OUT/'win_axis_ledger.parquet').set_index(['race_id','arm'])
    assert len(metrics)==len(selected)==37251 and len(marginal)==52236 and len(axis)==5337
    ref_scores = pd.concat([pd.read_parquet(STYLE/f'F1_STYLE6_{y}/evaluation_scores.parquet').assign(year=y) for y in (2024,2025,2026)]).set_index('api_record_id')
    re = []; permutation_count=0
    for rid, g in oof.loc[oof.year >= 2024].groupby('race_id'):
        g = g.sort_values('horse_number'); numbers=g.horse_number.to_numpy(int); n=len(g)
        actual=tuple(np.argsort(g.finish_position.to_numpy())[:3]); year=int(g.year.iloc[0]); plc=3 if n>=8 else None
        gamma=np.array(par['B_vintage_fits'][str(year)]['gamma']['gamma'])
        u0,u1,_,_=scenario_inputs(g,gamma)
        r=ref_scores.loc[g.api_record_id,'score'].to_numpy()
        joints={'R':distribution(r,par['R_reference_fits'][str(year)]['temperature']),
                'A':distribution(g.a_utility.to_numpy()),
                'B':mixture(u0,u1,float(rz.loc[rid,'q_z']),par['B_vintage_fits'][str(year)]['temperature_calibration']['temperature'])}
        for arm,joint in joints.items():
            permutation_count+=len(joint); pools,rank_probs=aggregate(joint,n,plc)
            for pool, probs in pools.items():
                if pool=='PLC' and plc is None:continue
                metric,keys,p,y=score_events(pool,probs,actual,plc)
                saved=metrics.loc[(rid,arm,pool)]
                near('all_pool_nll',metric['log_loss'],saved.race_nll)
                near('all_pool_brier',metric['brier'],saved.race_brier)
                key,prob=stable_selection(probs); chosen=selected.loc[(rid,arm,pool)]
                assert json.loads(chosen.selected_ticket_key)==[int(numbers[i]) for i in key]
                assert bool(chosen.selected_hit)==(key in winners(pool,actual,plc))
                near('selected_probability',prob,chosen.selected_probability)
                re.append(dict(race_id=rid,race_date=g.race_date.iloc[0],arm=arm,pool=pool,nll=metric['log_loss'],brier=metric['brier']))
            for i,number in enumerate(numbers):
                m=marginal.loc[(rid,arm,int(number))]
                expected=[rank_probs[i,0],rank_probs[i,1],rank_probs[i,2],rank_probs[i,:2].sum(),rank_probs[i].sum()]
                near('all_runner_marginals',expected,m[['p_win','p_exact2','p_exact3','p_top2','p_top3']].to_numpy(float))
            key,_=stable_selection(pools['WIN']); ix=key[0]; a=axis.loc[(rid,arm)]
            assert a.selected_horse_number==numbers[ix] and bool(a.selected_hit_top3)==(ix in actual)
    checked=pd.DataFrame(re)
    boot=np.load(BOOT,allow_pickle=False); dates=sorted(checked.race_date.unique())
    assert len(dates)==269
    comparisons={v['comparison']:v for v in report['comparisons']}; axis_stats=[]
    stored_draws=pd.read_parquet(OUT/'comparison_bootstrap_draws.parquet')
    for left,right in [('A','R'),('B','A'),('B','R')]:
        name=left+'_minus_'+right
        tri=checked.loc[checked.pool.eq('TRI')].pivot(index=['race_id','race_date'],columns='arm',values='nll')
        delta=tri[left]-tri[right]; daily=delta.groupby(level='race_date').agg(['sum','count']).loc[dates]
        draws=daily['sum'].to_numpy()[boot].sum(axis=1)/daily['count'].to_numpy()[boot].sum(axis=1)
        near('bootstrap_all_draws',draws,stored_draws.loc[stored_draws.comparison.eq(name)].sort_values('draw').tri_nll_difference)
        near('bootstrap_interval',np.quantile(draws,[.025,.975]),comparisons[name]['tri_delta_nll_ci95'])
        ap=axis.reset_index().pivot(index=['race_id','race_date'],columns='arm',values='selected_hit_top3').astype(float)
        day=ap.groupby(level='race_date').sum().loc[dates]
        count=ap.groupby(level='race_date').size().loc[dates].to_numpy()
        lc=day[left].to_numpy()[boot].sum(axis=1); rc=day[right].to_numpy()[boot].sum(axis=1)
        denom=count[boot].sum(axis=1)
        relative=lc/rc-1
        axis_stats.append(dict(comparison=name,left_hits=int(ap[left].sum()),right_hits=int(ap[right].sum()),
                               absolute_difference=float((ap[left]-ap[right]).mean()),
                               absolute_difference_ci95=np.quantile((lc-rc)/denom,[.025,.975]).tolist(),
                               relative_change=float(ap[left].sum()/ap[right].sum()-1),
                               relative_change_ci95=np.quantile(relative,[.025,.975]).tolist(),
                               relative_10pct_point_reached=bool(ap[left].sum()>=1.1*ap[right].sum()),
                               relative_10pct_lower_ci_reached=bool(np.quantile(relative,.025)>=.1)))
    assert int(axis.xs('R',level='arm').selected_hit_top3.sum())==1023
    guards=[]
    start=json.loads((HERE/'SESSION_START.json').read_text())
    for item in start['preserve']:
        assert sha(ROOT/item['path'])==item['sha256'];guards.append(item['path'])
    result=dict(passed=True,model_files_replayed=32,scalar_calibrations_checked=calibration_count,
                prediction_values_replayed=replay_count,gamma_stationarity=gamma_checks,
                evaluation_races=1779,metric_rows_checked=len(metrics),selection_rows_checked=len(selected),
                runner_marginal_rows_checked=len(marginal),ordered_triples_reconstructed=permutation_count,
                bootstrap_draws_checked=6000,axis_comparisons=axis_stats,maximum_errors=dict(ERRORS),
                protected_files_unchanged=guards,fit_receipt_sha256=sha(OUT/'fit_run_receipt.json'),
                verifier_sha256=sha(Path(__file__).resolve()),engine_imported=False,models_refitted=False)
    if not check_only:
        with (HERE/'RESULT_VERIFICATION.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check-only',action='store_true')
    main(parser.parse_args().check_only)

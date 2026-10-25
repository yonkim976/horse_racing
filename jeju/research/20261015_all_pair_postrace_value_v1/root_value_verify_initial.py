"""Independent flat-stake post-race price analysis; no study analyzer imports."""
from pathlib import Path
import hashlib
import json
import sys
from decimal import Decimal
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
QPL = Path(__file__).resolve().parent
PLC = ROOT / 'jeju/research/20261015_all_runner_place_value_v1'
PRED = ROOT / 'jeju/research/20261015_pair_riding_conditions_v1/outputs/evaluation_pair_predictions.parquet'
SCHEDULE = ROOT / 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy'


def inputs():
    pairs = pd.read_parquet(PRED)
    all_dates = sorted(pd.to_datetime(pairs.race_date).dt.strftime('%Y-%m-%d').unique())
    pairs = pairs[pairs.evaluation_year.isin([2025, 2026])].copy()
    prices = pd.read_csv(QPL / 'ROOT_QPL_QUOTE_REFERENCE.csv', dtype={'race_id':str, 'raw_quote':str})
    pairs = pairs.merge(prices, on=['race_id','horse_i','horse_j'], validate='one_to_one')
    assert len(pairs) == 48539 and pairs.race_id.nunique() == 1142
    raw = pd.read_parquet(ROOT / 'jeju/research/20261010_style_history_ablation_v1/outputs/report/runner_predictions.parquet')
    raw = raw[raw.variant.eq('F1_STYLE6') & raw.year.isin([2025, 2026]) & raw.field_n.ge(8)].copy()
    plcprices = pd.read_csv(PLC / 'ROOT_PLC_QUOTE_REFERENCE.csv', dtype={'race_id':str, 'raw_quote':str})
    raw = raw.merge(plcprices, on=['race_id','horse_number'], validate='one_to_one')
    assert len(raw) == 10831 and raw.race_id.nunique() == 1106
    raw['horse_i'] = raw.horse_number
    raw['horse_j'] = 0
    raw['evaluation_year'] = raw.year
    raw['y_pair'] = raw.y
    return pairs, raw, all_dates


def policies(kind):
    result = [(f'rank_{k}', k, None, None, None) for k in (range(1,6) if kind=='QPL' else range(1,4))]
    result += [('rank_1_ev_positive',1,None,None,0), ('max_ev_all',None,None,None,0),
               ('max_ev_top3',None,3,None,0)]
    if kind == 'QPL':
        result += [('max_ev_top5',None,5,None,0), ('max_ev_p020',None,None,.20,0),
                   ('max_ev_p030',None,None,.30,0), ('max_ev_top3_edge020',None,3,None,.20),
                   ('max_ev_p020_edge020',None,None,.20,.20)]
    else:
        result += [('max_ev_p040',None,None,.40,0), ('max_ev_p050',None,None,.50,0)]
    return result


def main():
    pairs, runners, dates = inputs()
    schedule = np.load(SCHEDULE, allow_pickle=False)
    assert schedule.shape == (2000,269)
    weights = np.stack([np.bincount(draw,minlength=269) for draw in schedule])
    date_lookup = {d:i for i,d in enumerate(dates)}
    sources = [('QPL','baseline_id',pairs,'jockey_id_candidate_calibrated_probability'),
               ('QPL','riding_candidate',pairs,'riding_conditions_candidate_calibrated_probability'),
               ('PLC','F1_STYLE6',runners,'p_top3')]
    summaries=[]; selected=[]
    for kind,model,frame,pcol in sources:
        f=frame.copy()
        f['race_date']=pd.to_datetime(f.race_date).dt.strftime('%Y-%m-%d')
        f['p']=f[pcol]
        f['quote']=f.raw_quote.astype(float)
        f['edge']=f.p*f.quote-1
        ranking_col='score' if kind=='PLC' else 'p'
        f=f.sort_values(['race_id',ranking_col,'horse_i','horse_j'],ascending=[True,False,True,True])
        f['probability_rank']=f.groupby('race_id').cumcount()+1
        f['gross_if_hit']=f.raw_quote.map(lambda x:int(Decimal(x)*1000))
        f['gross']=f.gross_if_hit*f.y_pair.astype(int)
        for strategy,exact,top,pmin,edge in policies(kind):
            mask=pd.Series(True,index=f.index)
            if exact is not None:mask &= f.probability_rank.eq(exact)
            if top is not None:mask &= f.probability_rank.le(top)
            if pmin is not None:mask &= f.p.ge(pmin)
            if edge is not None:mask &= f.edge.gt(edge)
            chosen=f[mask].copy()
            if exact is None:
                tie=['probability_rank','horse_i','horse_j'] if kind=='PLC' else ['horse_i','horse_j']
                chosen=chosen.sort_values(['race_id','edge',*tie],ascending=[True,False,*([True]*len(tie))]).groupby('race_id').head(1)
            assert chosen.race_id.is_unique
            chosen['pool']=kind;chosen['model']=model;chosen['strategy']=strategy
            selected.append(chosen[['pool','model','strategy','race_id','race_date','evaluation_year','horse_i','horse_j','probability_rank','p','quote','edge','y_pair','gross']])
            for period in ['all','2025','2026']:
                c=chosen if period=='all' else chosen[chosen.evaluation_year.eq(int(period))]
                universe=f if period=='all' else f[f.evaluation_year.eq(int(period))]
                n=len(c); total=int(c.gross.sum()); hits=int(c.y_pair.sum())
                row={'pool':kind,'model':model,'strategy':strategy,'period':period,'eligible_races':universe.race_id.nunique(),'bets':n,'hits':hits,'stake':1000*n,'gross':total,'net':total-1000*n,'roi':total/(1000*n)-1 if n else None,'mean_p':float(c.p.mean()) if n else None,'mean_edge':float(c.edge.mean()) if n else None,'mean_quote':float(c.quote.mean()) if n else None,'mean_selected_rank':float(c.probability_rank.mean()) if n else None}
                di=c.race_date.map(date_lookup).to_numpy(int)
                counts=np.bincount(di,minlength=269)
                gross=np.bincount(di,weights=c.gross,minlength=269)
                wins=np.bincount(di,weights=c.y_pair,minlength=269)
                den=weights@counts;valid=den>0
                row['valid_draws']=int(valid.sum());row['undefined_draws']=int((~valid).sum())
                for name,numerator in [('roi',(weights@gross)/1000-den),('hit_rate',weights@wins)]:
                    draw=numerator[valid]/den[valid]
                    bounds=np.quantile(draw,[.025,.975]) if len(draw) else [None,None]
                    row[name+'_ci_low'],row[name+'_ci_high']=bounds
                for k in [1,3,5]:
                    winners=c[c.y_pair.eq(1)].sort_values(['gross','race_id'],ascending=[False,True]).head(k)
                    rem_n=n-len(winners); rem_gross=total-int(winners.gross.sum())
                    row[f'roi_without_top{k}_hits']=rem_gross/(1000*rem_n)-1 if rem_n else None
                summaries.append(row)
    summary=pd.DataFrame(summaries); choices=pd.concat(selected,ignore_index=True)
    for folder,kind in [(QPL,'QPL'),(PLC,'PLC')]:
        with (folder/'ROOT_STRATEGY_REFERENCE.csv').open('x') as out:summary[summary.pool.eq(kind)].to_csv(out,index=False)
        with (folder/'ROOT_SELECTION_REFERENCE.csv').open('x') as out:choices[choices.pool.eq(kind)].to_csv(out,index=False)
    print(summary[summary.period.eq('all')][['pool','model','strategy','bets','hits','roi','roi_ci_low','roi_ci_high','mean_selected_rank']].to_string(index=False))


def verify_reports():
    mappings = {
        'QPL': {'rank_1_ev_positive':'rank_1_ev_gt_0','max_ev_all':'all_max_ev_gt_0',
                'max_ev_top3':'top3_max_ev_gt_0','max_ev_top5':'top5_max_ev_gt_0',
                'max_ev_p020':'p_ge_020_max_ev_gt_0','max_ev_p030':'p_ge_030_max_ev_gt_0',
                'max_ev_top3_edge020':'top3_max_ev_gt_020','max_ev_p020_edge020':'p_ge_020_max_ev_gt_020'},
        'PLC': {'rank_1':'p_rank_1','rank_2':'p_rank_2','rank_3':'p_rank_3',
                'rank_1_ev_positive':'p_rank_1_ev_positive','max_ev_all':'all_runners_max_ev_positive',
                'max_ev_top3':'top3_max_ev_positive','max_ev_p040':'p_ge_0_40_max_ev_positive',
                'max_ev_p050':'p_ge_0_50_max_ev_positive'}}
    model_map={'baseline_id':'pair_id_baseline','riding_candidate':'riding_conditions_candidate'}
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    for folder,kind in [(QPL,'QPL'),(PLC,'PLC')]:
        reference=pd.read_csv(folder/'ROOT_STRATEGY_REFERENCE.csv',dtype={'period':str})
        selected_reference=pd.read_csv(folder/'ROOT_SELECTION_REFERENCE.csv',dtype={'race_id':str})
        for frame in (reference,selected_reference):
            frame['strategy']=frame.strategy.map(lambda x:mappings[kind].get(x,x))
            frame['model']=frame.model.map(lambda x:model_map.get(x,x))
        summary=pd.read_csv(folder/'summary.csv',dtype={'period':str})
        summary['period']=summary.period.replace({'2026_partial':'2026'})
        if kind=='QPL':
            summary=summary[summary.price_scope.eq('complete_all_pair_quotes')]
            keys=['model','strategy','period']
            cols={'eligible_races':('eligible_price_races',1),'bets':('bets',1),'hits':('hits',1),
                  'stake':('stake_krw',1),'gross':('gross_return_krw',1),'net':('net_krw',1),
                  'roi':('roi_pct',.01),'mean_p':('mean_p',1),'mean_edge':('mean_model_ev',1),'mean_quote':('mean_quote',1)}
            intervals=pd.read_csv(folder/'bootstrap_ci.csv',dtype={'period':str})
            intervals=intervals[intervals.price_scope.eq('complete_all_pair_quotes')]
            intervals['period']=intervals.period.replace({'2026_partial':'2026'})
            intervals=intervals.set_index(keys).sort_index()
            out=pd.read_csv(folder/'selection_rows.csv',dtype={'race_id':str})
            out=out[out.scope.eq('complete_all_pair_quotes')&out.bet.eq(1)]
            choice_cols={'probability_rank':'chosen_rank','p':'p','quote':'final_quote','edge':'score','y_pair':'hit','gross':'return_krw','horse_i':'horse_i','horse_j':'horse_j'}
        else:
            summary['strategy']=summary.policy_id
            summary['model']='F1_STYLE6'
            keys=['model','strategy','period']
            cols={'eligible_races':('eligible_races',1),'bets':('selected_races',1),'hits':('hits',1),
                  'stake':('stake_krw',1),'gross':('gross_return_krw',1),'net':('net_profit_krw',1),
                  'roi':('roi_pct',.01),'mean_p':('mean_p_top3_pct',.01),'mean_edge':('mean_model_ev_pct',.01),'mean_quote':('mean_plc_odds',1)}
            intervals=summary.set_index(keys).sort_index()
            out=pd.read_csv(folder/'selected_rows.csv',dtype={'race_id':str})
            out=out[out.selected.eq(1)].copy();out['strategy']=out.policy_id;out['model']='F1_STYLE6';out['horse_j']=0
            choice_cols={'probability_rank':'probability_rank','p':'p_top3','quote':'plc_odds','edge':'model_ev','y_pair':'hit','gross':'gross_return_krw','horse_i':'horse_number','horse_j':'horse_j'}
        reference=reference.set_index(keys).sort_index();summary=summary.set_index(keys).sort_index()
        assert summary.index.equals(reference.index)
        for source,(target,factor) in cols.items():
            assert np.allclose(reference[source],summary[target]*factor,rtol=0,atol=1e-8,equal_nan=True),(kind,source)
        for k in (1,3,5):
            col=f'roi_without_largest_{k}_hits_pct' if kind=='QPL' else f'roi_without_top_{k}_gross_pct'
            assert np.allclose(reference[f'roi_without_top{k}_hits'],summary[col]/100,rtol=0,atol=1e-8,equal_nan=True)
        for measure in ('roi','hit_rate'):
            for bound in ('low','high'):
                col=f'{measure}_ci_{bound}_pct' if kind=='QPL' else f'{"roi" if measure=="roi" else "hit"}_ci95_{bound}_pct'
                assert np.allclose(reference[f'{measure}_ci_{bound}'],intervals[col]/100,rtol=0,atol=1e-8,equal_nan=True)
        choice_keys=['model','strategy','race_id']
        selected_reference=selected_reference.set_index(choice_keys).sort_index();out=out.set_index(choice_keys).sort_index()
        assert selected_reference.index.equals(out.index)
        for source,target in choice_cols.items():
            assert np.allclose(selected_reference[source],out[target],rtol=0,atol=1e-8),(kind,source)
        if kind=='QPL':
            examples=pd.read_csv(folder/'cases.csv',dtype={'race_id':str})
            for e in examples.itertuples(index=False):
                chosen=out.loc[(e.model,e.strategy,e.race_id)]
                assert np.allclose([chosen.p,chosen.final_quote,chosen.score,chosen.hit,chosen.return_krw],
                                   [e.chosen_p,e.chosen_quote,e.chosen_score,e.hit,e.gross_return_krw],rtol=0,atol=1e-8)
        receipt={'status':'PASS','scope':'Root independent raw-price, policy selection, returns, sensitivity and date-bootstrap crosscheck; no study analyzer imports or model fitting',
                 'pool':kind,'summary_rows_verified':len(summary),'selected_tickets_verified':len(out),
                 'confidence_bounds_verified':4*len(summary),'comparison_tolerance':1e-8,
                 'root_reference_sha256':sha(folder/'ROOT_STRATEGY_REFERENCE.csv'),
                 'root_selection_reference_sha256':sha(folder/'ROOT_SELECTION_REFERENCE.csv'),
                 'root_code_sha256':sha(Path(__file__).resolve()),
                 'summary_sha256':sha(folder/'summary.csv'),'report_sha256':sha(folder/'REPORT.json'),
                 'actual_and_expected_rank_roi_cases_are_retrospective':True,
                 'model_training_or_reprediction':False}
        with (folder/'ROOT_VERIFICATION_RECEIPT.json').open('x') as f:json.dump(receipt,f,indent=2);f.write('\n')
        print(json.dumps(receipt))


if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='verify-reports':verify_reports()
    else:main()

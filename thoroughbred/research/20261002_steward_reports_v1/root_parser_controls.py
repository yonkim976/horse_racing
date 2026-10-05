"""Human specified linkage checks, independent of the extractor rules."""
import importlib.util
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main():
    spec = importlib.util.spec_from_file_location('steward_linker_review', HERE / 'linking/report_linker.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixtures = json.loads((HERE / 'root_negative_controls.json').read_text())
    roster = [{'horse_program_no_raw': str(r['number']), 'horse_id_raw': r['horse_id'], 'horse_name_raw': r['horse_name']} for r in fixtures['roster']]
    base = {'actual_meet_code': 1, 'race_date_iso': '2020-01-02', 'rcNo': 2, 'capture_id': 'control', 'source_location': 'synthetic'}
    outcomes = []
    for case in fixtures['cases']:
        result = module.process_report(dict(base, judgement=case['text']), roster)
        actual = sorted(int(r['program_no_raw']) for r in result['links'])
        assert actual == sorted(case['expected_linked_numbers']), (case['label'], actual)
        outcomes.append({'case': case['label'], 'actual_linked_numbers': actual, 'passed': True})
    empty = [dict(roster[0], horse_id_raw='')]
    assert not module.process_report(dict(base, judgement='● ①“가나다”가 출발이 늦었음.'), empty)['links']
    target_key, parent_key = (1, '2020-01-01', 1), (1, '2020-01-02', 2)
    rosters = {parent_key: roster, target_key: [dict(roster[0], horse_id_raw='0000999')]}
    cases = [
        ('supplement_prior_target', '● ‘20.1.1.(수) 제1경주에서 ①“가나다”가 출발이 늦었음.', ['0000999']),
        ('supplement_unknown_target', '● ①“가나다”가 출발이 늦었음.', []),
        ('supplement_future_target', '● ‘20.1.3.(금) 제1경주에서 ①“가나다”가 출발이 늦었음.', []),
        ('supplement_multiple_targets', '● ‘20.1.1.(수) 제1경주에서 ①“가나다”가 출발이 늦었고, ‘20.1.1.(수) 제2경주의 ②“라마바”와 다르게 심의하였음.', []),
        ('supplement_wrong_weekday', '● ‘20.1.1.(금) 제1경주에서 ①“가나다”가 출발이 늦었음.', []),
        ('supplement_korean_prior_target', '● 2020년 1월 1일(수) 제1경주에서 ①“가나다”가 출발이 늦었음.', ['0000999']),
        ('supplement_korean_wrong_weekday', '● 2020년 1월 1일(금) 제1경주에서 ①“가나다”가 출발이 늦었음.', []),
    ]
    for label, text, expected in cases:
        result = module.process_report(dict(base, addJudgement=text), rosters)
        actual = sorted(r['official_horse_id'] for r in result['links'])
        assert actual == sorted(expected), (label, actual)
        outcomes.append({'case': label, 'actual_horse_ids': actual, 'passed': True})
    observations = pq.read_table(HERE / 'source/api_observations.parquet').to_pylist()
    con = duckdb.connect(str(ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'), read_only=True)
    for case in json.loads((HERE / 'root_manual_expected_links.json').read_text()):
        report = next(r for r in observations if r['dataset']=='api215_judge_report' and str(r['actual_meet_code'])==case['meet'] and str(r['rcDate'])==case['date'] and str(r['rcNo'])==case['race_no'])
        columns = ['horse_program_no_raw','horse_id_raw','horse_name_raw']
        rows = con.execute('SELECT horse_program_no_raw,horse_id_raw,horse_name_raw FROM runner_results WHERE source_meet=? AND result_date=? AND result_race_no=?', [case['meet'],case['date'],case['race_no']]).fetchall()
        result = module.process_report(report, [dict(zip(columns,r)) for r in rows])
        paragraphs = {p['paragraph_locator']: p for p in result['paragraphs']}
        actual = {}
        for link in result['links']:
            p = paragraphs[link['paragraph_locator']]
            if p['report_text_field']==case['field']:
                actual.setdefault(p['paragraph_index'], []).append(int(link['program_no_raw']))
        assert len(actual)==len(case['expected_horses_by_bullet']), (case,actual)
        assert [sorted(actual[i]) for i in range(len(actual))] == [sorted(g) for g in case['expected_horses_by_bullet']], (case,actual)
        outcomes.append({'case': ':'.join([case['meet'],case['date'],case['race_no']]), 'passed': True, 'linked_horse_paragraphs':sum(map(len,actual.values()))})
    con.close()
    report = {'all_passed': True, 'checks': outcomes, 'empty_id_abstention': True}
    (HERE / 'root_parser_control_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()

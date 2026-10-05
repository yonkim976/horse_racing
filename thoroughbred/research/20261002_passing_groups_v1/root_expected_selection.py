"""Build an independent expected selection from raw API cells and printed labels."""
import json
from collections import Counter, defaultdict
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
MAPS = {1:{1:'1C',2:'2C',3:'3C',4:'4C',7:'S1F',8:'G1F'},3:{1:'G8F',2:'G6F',3:'G4F',5:'G3F',7:'S1F',8:'G2F',9:'G1F'},4:{1:'G8F',2:'G6F',3:'G4F',5:'G3F',7:'S1F',8:'G2F',9:'G1F'}}
RPT_MAP = {1:{'C1':'1C','C2':'2C','C3':'3C','C4':'4C','S-1F':'S1F','G-1F':'G1F'},3:{'S1F':'S1F','G8F':'G8F','G6F':'G6F','G4F':'G4F','G3F':'G3F','G2F':'G2F','G1F':'G1F'}}
RPT_MAP[4] = RPT_MAP[3]


def valid(value):
    return value is not None and value.strip(' ') not in ('','-','X')


def main():
    confirmed = {(row['meet'],row['event_date'],row['race_no']) for row in json.loads((HERE/'root_expected_confirmed_races.json').read_text())}
    printed = defaultdict(dict)
    rpt_candidates = defaultdict(set)
    for row in pq.read_table(HERE/'rpt_mapping/rpt_point_observations.parquet').to_pylist():
        key = (row['actual_meet_code'],row['event_date'],row['race_no'])
        if key not in confirmed or not valid(row['notation_raw']):
            continue
        point = RPT_MAP[key[0]][row['print_label_raw']]
        assert point not in printed[key]
        printed[key][point] = row['notation_raw']
        rpt_candidates[(*key,point)].add(row['notation_raw'])
    api_candidates = defaultdict(set)
    held = []
    for row in pq.read_table(HERE/'api_source/api_observations.parquet').to_pylist():
        key = (row['actual_meet_code'],row['race_date_iso'],row['rcNo'])
        if key not in confirmed:
            continue
        for field, nominal in MAPS[key[0]].items():
            value = row[f'corner_{field}']
            if not valid(value):
                continue
            point = nominal
            if key[0] == 1 and key[1][:4] in ('2020','2021'):
                choices = [point for point,rpt in printed[key].items() if value.strip(' ') == rpt.strip(' ')]
                if len(choices) != 1:
                    held.append((*key,f'corner_{field}',len(choices)))
                    continue
                point = choices[0]
            api_candidates[(*key,point)].add(value)
    rows = []
    states = Counter()
    conflicts = []
    for key in sorted(api_candidates.keys() | rpt_candidates.keys()):
        api, rpt = api_candidates[key], rpt_candidates[key]
        value, source = None,None
        if len(api) == 1:
            value, source = next(iter(api)), 'api303'
            if rpt and {item.strip(' ') for item in api} != {item.strip(' ') for item in rpt}:
                conflicts.append(dict(actual_meet_code=key[0],event_date=key[1],race_no=key[2],canonical_point_code=key[3],api_values=sorted(api),rpt_values=sorted(rpt)))
        elif not api and len(rpt) == 1:
            value, source = next(iter(rpt)), 'dacom11_rpt'
        states[source or 'held'] += 1
        rows.append(dict(actual_meet_code=key[0],event_date=key[1],race_no=key[2],canonical_point_code=key[3],notation_raw=value,selected_source=source))
    pq.write_table(pa.Table.from_pylist(rows),HERE/'root_expected_selected_points.parquet')
    report = {'expected_point_keys':len(rows),'selection_counts':dict(states),'cross_source_conflicting_point_keys':len(conflicts),'cross_source_conflicting_races':len({(row['actual_meet_code'],row['event_date'],row['race_no']) for row in conflicts}),'unmapped_suspect_api_slots':len(held),'races_with_selected_values':len({(row['actual_meet_code'],row['event_date'],row['race_no']) for row in rows if row['notation_raw'] is not None}),'unmapped_suspect_slots_by_candidate_label_count':dict(Counter(row[-1] for row in held))}
    (HERE/'root_expected_value_conflicts.json').write_text(json.dumps(conflicts,ensure_ascii=False,indent=2)+'\n')
    (HERE/'root_expected_selection.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()

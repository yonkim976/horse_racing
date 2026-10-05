"""Check every produced span, neutral horse relation and source-marker receipt."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    source = pq.read_table(HERE / 'source/api_observations.parquet').to_pylist()
    observations = {r['capture_id']+'|'+r['source_location']:r for r in source if r['dataset']=='api215_judge_report'}
    tables = {name:pq.read_table(HERE / 'linking' / file).to_pylist() for name,file in {
        'paragraphs':'report_event_paragraphs.parquet','sentences':'report_event_sentences.parquet',
        'mentions':'report_horse_mentions.parquet','links':'report_horse_links.parquet','residuals':'report_marker_residuals.parquet'}.items()}
    paragraphs = {p['paragraph_locator']:p for p in tables['paragraphs']}
    sentences = {p['sentence_locator']:p for p in tables['sentences']}
    mentions = {m['mention_locator']:m for m in tables['mentions']}
    assert len(paragraphs)==len(tables['paragraphs']) and len(mentions)==len(tables['mentions'])
    assert len(sentences)==len(tables['sentences'])
    for kind, field in [('paragraphs','paragraph_raw'),('sentences','sentence_raw'),('mentions','mention_raw'),('residuals','marker_raw')]:
        for row in tables[kind]:
            observation = observations[row['observation_locator']]
            raw = observation[row['report_text_field']]
            start,end = row['span_start_codepoint'],row['span_end_codepoint']
            if start is None:
                assert kind=='paragraphs' and row['paragraph_state']!='text' and row[field]==raw
                continue
            assert 0 <= start <= end <= len(raw)
            assert raw[start:end]==row[field], (kind,row['observation_locator'])
            assert row['page_sha256']==observation['page_sha256']
            if kind in ('mentions','sentences','residuals'):
                p = paragraphs[row['paragraph_locator']]
                assert p['observation_locator']==row['observation_locator']
                assert p['span_start_codepoint'] <= start <= end <= p['span_end_codepoint']
            if kind=='mentions' and row['name_start_codepoint'] is not None:
                assert raw[row['name_start_codepoint']:row['name_end_codepoint']]==row['raw_name']
    markers='①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
    marker_count=sum(sum(ch in markers for ch in (r.get(f) or '')) for r in observations.values() for f in ('judgement','addJudgement','jkChange'))
    assert marker_count==sum(m['marker_start_codepoint'] is not None for m in tables['mentions'])
    con=duckdb.connect(str(ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'),read_only=True)
    rosters={(int(m),d,int(n),int(p)):h for m,d,n,p,h in con.execute('SELECT source_meet,result_date,result_race_no,horse_program_no_raw,horse_id_raw FROM runner_results').fetchall()}
    con.close()
    seen=set()
    for link in tables['links']:
        p=paragraphs[link['paragraph_locator']]
        o=observations[link['observation_locator']]
        assert p['observation_locator']==link['observation_locator']
        assert link['mention_semantics']=='mentioned_in_report_paragraph' and link['status']=='linked'
        target=(int(link['target_actual_meet_code']),link['target_event_date'].replace('-',''),int(link['target_race_no']),int(link['program_no_raw']))
        assert rosters[target]==link['official_horse_id']
        assert link['target_event_date']<=o['race_date_iso']
        if p['report_text_field']!='addJudgement':
            assert target[:3]==(int(o['actual_meet_code']),str(o['rcDate']),int(o['rcNo']))
        else:
            assert p['target_context_status']=='add_judgement_exact_leading_date_race_context'
        key=(link['paragraph_locator'],link['official_horse_id'])
        assert key not in seen
        seen.add(key)
        mention_ids=json.loads(link['linked_mention_locators_json'])
        assert mention_ids
        for mid in mention_ids:
            m=mentions[mid]
            assert m['paragraph_locator']==link['paragraph_locator']
            assert m['candidate_official_horse_id']==link['official_horse_id']
            for anchor_id in json.loads(m['anchor_mention_locators_json']):
                a=mentions[anchor_id]
                assert a['observation_locator']==m['observation_locator']
                assert a['report_text_field']==m['report_text_field']
                assert (a['target_actual_meet_code'],a['target_event_date'],a['target_race_no'])==(m['target_actual_meet_code'],m['target_event_date'],m['target_race_no'])
                assert a['candidate_official_horse_id']==link['official_horse_id']
        for sid in json.loads(link['linked_sentence_locators_json']):
            assert sentences[sid]['paragraph_locator']==link['paragraph_locator']
    report={'all_passed':True,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
            'row_counts':{k:len(v) for k,v in tables.items()},'original_circled_markers_all_accounted_for':marker_count,
            'unique_linked_horses':len({l['official_horse_id'] for l in tables['links']}),
            'links_by_field':dict(Counter(paragraphs[l['paragraph_locator']]['report_text_field'] for l in tables['links'])),
            'links_by_rule':dict(Counter(l['match_rule'] for l in tables['links'])),
            'input_sha256':{p.name:sha(p) for p in (HERE/'linking').glob('*.parquet')}}
    (HERE/'root_linking_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()

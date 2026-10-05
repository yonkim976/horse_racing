"""Read-only checks of dictionary literal propagation and source pins."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
D = HERE / 'dictionary'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    manifest = json.loads((D / 'manifest.json').read_text())
    for name, item in manifest['source_files'].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT) and sha(path) == item['sha256'], name
    for name, item in manifest['output_files'].items():
        assert sha(D / name) == item['sha256'], name
        if name.endswith('.parquet'):
            assert pq.ParquetFile(D / name).metadata.num_rows == item['row_count'], name
    rows = pq.read_table(D / 'api33_source_rows.parquet').to_pylist()
    raw = json.loads((ROOT / rows[0]['source_json_path']).read_text())['entries']
    assert len(rows) == len(raw) == 3523
    for ordinal, (r, source) in enumerate(zip(rows, raw), 1):
        assert r['source_row_id'] == ordinal and json.loads(r['source_record_json']) == source
        assert (r['ill_name'], r['ill_eng_name'], r['ill_desc']) == (source['illName'], source['illEngName'], source['illDesc'])
        assert r['ill_desc'] == '-'
    terms = pq.read_table(D / 'api33_terms.parquet').to_pylist()
    assert Counter((r['ill_name'], r['ill_eng_name'], r['ill_desc']) for r in terms) == Counter({k: 1 for k in {(r['ill_name'], r['ill_eng_name'], r['ill_desc']) for r in rows}})
    assert len(terms) == 3511 and len({r['ill_name'] for r in terms}) == 3500
    decisions = pq.read_table(D / 'phrase_decisions.parquet').to_pylist()
    review_file = ROOT / decisions[0]['source_review_file']
    with review_file.open(encoding='utf-8-sig', newline='') as stream:
        review = {r['raw_text']: r for r in csv.DictReader(stream)}
    assert len(decisions) == len(review) == 5397
    decision_by_hash, prefix = {}, 0
    for r in decisions:
        assert r['raw_text_sha256'] == hashlib.sha256(r['raw_text'].encode()).hexdigest()
        source = review[r['raw_text']]
        assert r['review_decision'] == source['review_decision'] and r['evidence_note'] == source['evidence_note']
        assert r['mapped_kra_titles_raw'] == source['mapped_kra_titles']
        assert 'no_automatic_event_link' in r['event_link_policy']
        if r['review_decision'] == 'confirmed_dacom72_title_after_prefix':
            prefix += 1
            assert r['prefix_rule_reusable'] is False
            assert r['mapping_rule_scope'] == 'prior_rpt_parser_context_only'
        decision_by_hash[r['raw_text_sha256']] = r
    assert prefix == 356
    components = pq.read_table(D / 'phrase_components.parquet').to_pylist()
    grouped = {}
    for r in components:
        parent = decision_by_hash[r['raw_text_sha256']]
        assert r['raw_text'] == parent['raw_text']
        assert r['mapping_rule_scope'] == parent['mapping_rule_scope']
        grouped.setdefault(r['raw_text_sha256'], []).append((r['reviewed_target_ordinal'], r['target_ill_name']))
    for key, r in decision_by_hash.items():
        expected = [(i, value) for i, value in enumerate(r['mapped_kra_titles_raw'].split(' | '), 1) if value]
        assert sorted(grouped.get(key, [])) == expected, r['raw_text']
    explanations = pq.read_table(D / 'explanation_observations.parquet').to_pylist()
    assert len(explanations) == 145
    for r in explanations:
        path = (ROOT / r['source_file']).resolve()
        assert path.is_relative_to(ROOT) and sha(path) == r['source_file_sha256']
        assert r['source_publication_at_kst'] is None
        assert r['description_present'] == bool(r['description_text'])
        assert hashlib.sha256(r['source_record_json'].encode()).hexdigest() == r['source_row_sha256']
        assert r['source_kind'] != 'API33'
    result = {'all_passed': True, 'api33_raw_rows': 3523, 'api33_tuple_rows': 3511,
              'phrase_decisions': 5397, 'reviewed_targets': len(components),
              'prior_parser_prefix_rules_blocked': prefix, 'explanation_observations': len(explanations),
              'source_files_checked': len(manifest['source_files']),
              'script_sha256': sha(Path(__file__))}
    (HERE / 'root_dictionary_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

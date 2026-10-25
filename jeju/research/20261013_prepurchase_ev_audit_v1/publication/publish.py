"""Publish reviewed pre-purchase data audit, preserving all previous conclusions."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STUDY = ROOT / 'jeju/research/20261013_prepurchase_ev_audit_v1'
CENTRAL = ROOT / 'jeju/research/conclusions'
NAMES = ['22_DIRECT_PAIR_TOP3_MODEL.md', 'README.md', 'SOURCES.md',
         'research_register.json', 'source_manifest.json']


def sha(value):
    return hashlib.sha256(value).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def main():
    review = json.loads((STUDY / 'ROOT_REVIEW.json').read_text())
    report = json.loads((STUDY / 'REPORT.json').read_text())
    assert review['status'] == 'PASS'
    assert review['report_sha256'] == sha((STUDY / 'REPORT.json').read_bytes())
    for name, digest in review['reviewed_output_sha256'].items():
        assert sha((STUDY / name).read_bytes()) == digest
    before = {n: (CENTRAL / n).read_bytes() for n in NAMES}
    after = dict(before)
    after[NAMES[0]] += ('\n## 2026-10-13 후속: 확률·사전배당 EV 선별 자료 감사\n\n'
        '현재 기수 ID 후보의 말 평가·선택쌍·공동 Top3 확률은 고정했다. 배당 보유 '
        '2025년 654경주와 2026-09-19까지 488경주, 합계 1,142경주에서 예정 출발 '
        'T-5분을 고정 관측 경계로 사용했다. 현재 odds_snapshots는 같은 조합의 배당과 '
        '관측시각을 갱신하므로 최초 관측 이력을 보장하지 않는다. 현재 테이블에 '
        '사전 선택쌍 행이 없다는 사실만으로 과거 사전 배당 부재를 결론 내리지 않았다.\n\n'
        '171개 대상 날짜의 API301 원응답 889페이지를 registry와 SHA-256 대조했다. '
        '2026-09-05 3~6R에서 요청·수신이 경계보다 앞선 정확 선택쌍 QPL 값 네 건을 '
        '찾았다. 두 건은 1.0, 두 건은 9999.9였다. 1.0 두 건의 p×표시배당−1은 음수이고, '
        '9999.9는 공식 의미·구매 가능 여부 미확정으로 EV 계산에서 제외했다. 이를 '
        '무효배당·placeholder로 단정하거나 높은 수익 기회로 계산하지 않았다.\n\n'
        '네 값은 예정 출발 약 27~177분 전의 원천 후보로 T-5분의 최신 시세는 미확인이다. '
        '모든 대상 실제 출발시각이 비어 있고, 수집기 시계·당시 공개/구매 가능성·'
        '예측 공표시각도 독립 검증되지 않았다. 후속 동일 선택쌍 원문 값은 네 경주 모두 '
        '달랐다. 사전 원천 후보 4건과 검증된 공개·구매 가능 quote 0건을 구분하며, '
        '후자의 0은 부재 증명이 아니다. 의미 있는 EV 선별 ROI·신뢰구간은 산출하지 않았다.\n\n'
        '복연 손익분기 표시배당 1/p와 +10% 조건부 proxy 경계 1.10/p를 '
        '1,142경주에 대해 보존했으나 실제 배당·EV·환급으로 표시하지 않았다. '
        'pari-mutuel의 최종 배당은 변할 수 있어 p×사전표시배당−1은 조건부 proxy다. '
        '복승에는 정확 Top2 쌍 확률이 별도로 필요하며 현재 Top3 확률을 대입하지 않는다. '
        '감독이 1,142개 시각/확률 행·필요배당 행과 원문 889페이지 및 네 후보를 독립 '
        '재구성해 자료 감사 PASS했다. 수익성·운영 채택 판정은 없고 DB·모델을 변경하지 않았다. '
        '[보고서](../20261013_prepurchase_ev_audit_v1/README.md), '
        '[독립 검토](../20261013_prepurchase_ev_audit_v1/ROOT_REVIEW.json).\n').encode()
    after['README.md'] += ('\n[사전배당과 확률을 결합한 EV 선별 자료 감사]'
        '(../20261013_prepurchase_ev_audit_v1/README.md): 1,142경주 원문 889페이지에서 '
        '사전 선택쌍 후보 4건(1.0 두 건·의미 미확정 9999.9 두 건)을 확인했다. '
        '검증된 공개·구매 가능 quote와 대표 표본이 없어 EV 선별 수익률은 미산출이다. '
        '자료 감사 독립 검산 PASS; 모델·운영 변경 없음.\n').encode()
    after['SOURCES.md'] += ('\n- [20261013_prepurchase_ev_audit_v1]'
        '(../20261013_prepurchase_ev_audit_v1/README.md): 고정 QPL 선택쌍과 예정 T-5분 '
        '경계의 현재 DB·원문 시점 감사. [4개 원문 후보]'
        '(../20261013_prepurchase_ev_audit_v1/RAW_PRESTART_API301_CANDIDATES.csv), '
        '[독립 검토](../20261013_prepurchase_ev_audit_v1/ROOT_REVIEW.json). '
        '필요 표시배당은 이론값이며 사전배당 기반 ROI는 검증하지 않았다.\n').encode()
    register = json.loads(before['research_register.json'])
    register['updated_at'] = '2026-10-13'
    topic = next(t for t in register['topics'] if t['id'] == 'pair_top3_direct_20261011')
    key = 'prepurchase_ev_audit_20261013'
    assert key not in topic
    topic[key] = {'source': '../20261013_prepurchase_ev_audit_v1/README.md',
        'review': '../20261013_prepurchase_ev_audit_v1/ROOT_REVIEW.json',
        'cohort': report['scope'], 'raw_source_pages_hash_verified': 889,
        'decision': report['decision'], 'cutoff': 'scheduled_at_ms - 300000',
        'actual_start_missing': 1142, 'data_audit_independent_review': 'PASS',
        'qnl_probability_available': False, 'profitability_verified': False,
        'new_collector_executed': False, 'model_or_operational_change': False}
    after['research_register.json'] = encode(register)
    manifest = json.loads(before['source_manifest.json'])
    old_rows = {r['path']: r for r in manifest['files']}
    assert len(old_rows) == len(manifest['files'])
    rows = dict(old_rows)
    for name in NAMES[:-1]:
        path = (CENTRAL / name).relative_to(ROOT).as_posix()
        rows[path] = {**rows[path], 'sha256': sha(after[name]), 'bytes': len(after[name])}
    new = [p for p in STUDY.rglob('*') if p.is_file()
           and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
    for p in new:
        path = p.relative_to(ROOT).as_posix()
        assert path not in rows
        data = p.read_bytes()
        rows[path] = {'path': path, 'role': 'prepurchase_ev_data_audit', 'sha256': sha(data), 'bytes': len(data)}
    manifest['updated_at'] = '2026-10-13'
    manifest['files'] = sorted(rows.values(), key=lambda r: r['path'])
    manifest['managed_files_bytes_excluding_this_manifest'] = sum(r['bytes'] for r in rows.values())
    manifest['verification'][key] = {'status': 'PASS', 'new_source_rows': len(new),
        'prior_source_rows_preserved_except_four_updated_management_files': True,
        'root_review': 'jeju/research/20261013_prepurchase_ev_audit_v1/ROOT_REVIEW.json',
        'profitability_validated': False, 'operational_change': False}
    after['source_manifest.json'] = encode(manifest)
    backup = STUDY / 'publication/before'
    backup.mkdir(exist_ok=False)
    for name, data in before.items():
        (backup / name).write_bytes(data)
    assert all((CENTRAL / n).read_bytes() == before[n] for n in NAMES), 'Concurrent edit'
    for name in NAMES:
        assert (CENTRAL / name).read_bytes() == before[name], 'Concurrent edit'
        tmp = CENTRAL / (name + '.prepurchase.tmp')
        tmp.write_bytes(after[name]); tmp.replace(CENTRAL / name)
    changed = {(CENTRAL / n).relative_to(ROOT).as_posix() for n in NAMES[:-1]}
    assert all(rows[path] == row for path, row in old_rows.items() if path not in changed)
    old_register = json.loads(before['research_register.json'])
    old_topics = {t['id']: t for t in old_register['topics']}
    new_topics = {t['id']: t for t in register['topics']}
    assert old_topics.keys() == new_topics.keys()
    for ident, old_topic in old_topics.items():
        new_topic = dict(new_topics[ident])
        if ident == 'pair_top3_direct_20261011':
            del new_topic[key]
        assert old_topic == new_topic
    for n in NAMES:
        assert (CENTRAL / n).read_bytes() == after[n]
    receipt = {'status': 'PASS', 'before': {n: sha(v) for n,v in before.items()},
        'after': {n: sha(v) for n,v in after.items()}, 'new_source_rows': len(new),
        'prior_source_rows_preserved': len(old_rows)-4, 'all_prior_topic_values_preserved': True,
        'topic_count': len(new_topics)}
    (STUDY / 'publication/RECEIPT.json').write_bytes(encode(receipt))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()

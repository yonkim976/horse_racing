"""Append reviewed payout diagnostics; preserve model research conclusions."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STUDY = ROOT / 'jeju/research/20261013_pair_payout_audit_v1'
CENTRAL = ROOT / 'jeju/research/conclusions'
NAMES = ['22_DIRECT_PAIR_TOP3_MODEL.md', 'README.md', 'SOURCES.md',
         'research_register.json', 'source_manifest.json']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def main():
    assert (STUDY / 'ROOT_REVIEW.json').is_file(), 'Independent review required'
    assert json.loads((STUDY / 'ROOT_REVIEW.json').read_text())['status'] == 'PASS'
    before = {n: (CENTRAL / n).read_bytes() for n in NAMES}
    after = dict(before)
    diagnostic = {
        'source': '../20261013_pair_payout_audit_v1/README.md',
        'period': ['2025-01-03', '2026-09-19'],
        'races': 1142, 'pair_hits': 283, 'pair_misses': 859,
        'unavailable_2024_races': 637,
        'hit_definition': 'Selected jockey_id_candidate pair both finish in Top3',
        'winning_trio_mean_hit': 20.10600706713781,
        'winning_trio_mean_miss': 89.10349243306169,
        'winning_trio_median_hit': 12.9, 'winning_trio_median_miss': 39.9,
        'winning_quinella_mean_hit': 11.025795053003534,
        'winning_quinella_mean_miss': 30.81071012805588,
        'selected_hit_quinella_place_mean': 2.7434628975265016,
        'interpretation': 'Postrace descriptive diagnostic; winning race dividends are not model ticket returns',
        'model_changed': False, 'operational_promotion': False,
    }
    paragraph = ('\n## 2026-10-13 후속: 적중·미적중 경주의 당첨배당\n\n'
        '기수 ID 후보의 저장 pair 선택을 유지하고, 배당이 보유된 2025-01-03~2026-09-19의 '
        '1,142경주를 연결했다. 두 말 모두 Top3인 283경주의 실제 당첨 삼복승 배당은 평균 '
        '20.106배·중앙값 12.9배, 미적중 859경주는 평균 89.103배·중앙값 39.9배였다. '
        '평균 차이는 68.997배이며 미적중군이 4.432배 높다. 실제 당첨 복승 배당의 평균은 '
        '각각 11.026배와 30.811배다. 적중한 선택 pair 자체의 복연승 배당 평균은 2.743배다.\n\n'
        '2024년 637경주는 조합 배당 미보유로 제외했고 결측을 0으로 대체하지 않았다. '
        '2026년은 부분연도다. 적중 분류는 두 말 동시 Top3이며 삼복승 3두 적중이나 복승 '
        'Top2 적중이 아니다. 위 삼복·복승 값은 해당 경주의 실제 당첨조합 배당을 비교한 '
        '사후 기술통계이며, 우리 조합의 실현 배당·수익률을 뜻하지 않는다. '
        '말 평가·모델·운영 기준은 그대로 유지했다. '
        '[분석·원천 검증](../20261013_pair_payout_audit_v1/README.md).\n')
    after[NAMES[0]] += paragraph.encode()
    after['README.md'] += ('\n[두 말 pair 적중·미적중 배당 진단](../20261013_pair_payout_audit_v1/README.md): '
        '배당 보유 1,142경주에서 실제 당첨 삼복승 평균은 적중 20.106배, 미적중 89.103배였다. '
        '두 말 Top3 기준의 후향 기술통계이며 실현 수익률·모델 개선 판정은 아니다.\n').encode()
    after['SOURCES.md'] += ('\n- [20261013_pair_payout_audit_v1](../20261013_pair_payout_audit_v1/README.md): '
        '저장 기수 ID pair 선택과 로컬 API301·공유 DB 결과를 연결한 적중/미적중 배당 진단. '
        '2025~2026-09-19의 1,142경주; 2024 배당 미보유. 원문·키·집계 검토는 연구 폴더에 보존.\n').encode()
    register = json.loads(before['research_register.json'])
    register['updated_at'] = '2026-10-13'
    topic = next(t for t in register['topics'] if t['id'] == 'pair_top3_direct_20261011')
    topic['payout_diagnostic_20261013'] = diagnostic
    after['research_register.json'] = encoded(register)
    manifest = json.loads(before['source_manifest.json'])
    manifest['updated_at'] = '2026-10-13'
    rows = {r['path']: r for r in manifest['files']}
    for name in NAMES[:-1]:
        key = (CENTRAL / name).relative_to(ROOT).as_posix()
        assert key in rows
        rows[key] = {**rows[key], 'sha256': sha(after[name]), 'bytes': len(after[name])}
    new_files = [p for p in STUDY.rglob('*') if p.is_file() and 'publication' not in p.relative_to(STUDY).parts
                 and '__pycache__' not in p.parts]
    for path in new_files:
        key = path.relative_to(ROOT).as_posix()
        assert key not in rows, 'Refusing to replace published study'
        data = path.read_bytes()
        rows[key] = {'path': key, 'role': 'pair_payout_diagnostic', 'sha256': sha(data), 'bytes': len(data)}
    manifest['files'] = sorted(rows.values(), key=lambda r: r['path'])
    manifest['managed_files_bytes_excluding_this_manifest'] = sum(r['bytes'] for r in rows.values())
    manifest['verification']['pair_payout_20261013'] = {
        'root_review': 'jeju/research/20261013_pair_payout_audit_v1/ROOT_REVIEW.json',
        'status': 'PASS', 'new_source_rows': len(new_files),
        'old_nonmanagement_rows_preserved': True, 'database_or_model_changes': False}
    after['source_manifest.json'] = encoded(manifest)
    backup = STUDY / 'publication/before'
    backup.mkdir(exist_ok=False)
    for name, data in before.items():
        (backup / name).write_bytes(data)
    assert all((CENTRAL / n).read_bytes() == before[n] for n in NAMES), 'Concurrent change; retry from new snapshot'
    for name in NAMES:
        assert (CENTRAL / name).read_bytes() == before[name], 'Concurrent change'
        temp = CENTRAL / (name + '.pair_payout.tmp')
        temp.write_bytes(after[name])
        temp.replace(CENTRAL / name)
    receipt = {'status': 'PASS', 'before': {n: sha(b) for n, b in before.items()},
               'after': {n: sha(b) for n, b in after.items()}, 'new_source_rows': len(new_files)}
    (STUDY / 'publication/RECEIPT.json').write_bytes(encoded(receipt))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()

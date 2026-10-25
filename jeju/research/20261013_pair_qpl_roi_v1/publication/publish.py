"""Publish the reviewed descriptive QPL backtest with optimistic concurrency guards."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STUDY = ROOT / 'jeju/research/20261013_pair_qpl_roi_v1'
CENTRAL = ROOT / 'jeju/research/conclusions'
NAMES = ['22_DIRECT_PAIR_TOP3_MODEL.md', 'README.md', 'SOURCES.md',
         'research_register.json', 'source_manifest.json']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def main():
    review = json.loads((STUDY / 'ROOT_REVIEW.json').read_text())
    assert review['status'] == 'PASS'
    assert review['report_sha256'] == sha((STUDY / 'REPORT.json').read_bytes())
    report = json.loads((STUDY / 'REPORT.json').read_text())
    for row in json.loads((STUDY / 'SOURCE_HASHES.json').read_text())['files'].values():
        if 'definition' not in row:
            assert sha((ROOT / row['path']).read_bytes()) == row['sha256']
    before = {name: (CENTRAL / name).read_bytes() for name in NAMES}
    after = dict(before)
    labels = ['현재 기수 ID 후보', '직전 기수 기본 후보', '기수 정보 추가 전 확장 pair',
              '이전 직접 pair', '말 점수 Top2', '저장 입상확률 Top2',
              '공동 주변확률 Top2', '공동 최대 pair', '매칭 공동 최대 pair']
    table = ['| 방식 | 적중/1,142 | 총환급 | 순수익률 |', '|---|---:|---:|---:|']
    for label, row in zip(labels, report['same_denominator_summary']):
        table.append(f"| {label} | {row['hits']} | {row['return_krw']:,}원 | {row['roi_pct']:.2f}% |")
    text = ('\n## 2026-10-13 후속: 복연승 한 조합 등액 환급 비교\n\n'
        '배당이 있는 2025-01-03~2026-09-19의 동일한 1,142경주에서 각 저장 방식마다 '
        '복연승 한 조합을 10,000원씩 매수했다고 계산했다. 총투입은 방식당 11,420,000원이다. '
        '공식 Top3에 든 선택 쌍의 원금 포함 QPL 배당만 환급하며 미적중은 0원이다. '
        '순수익률은 `(총환급−총투입)/총투입`으로 계산한다.\n\n' + '\n'.join(table) + '\n\n'
        '현재 후보의 회수율은 67.986%, 순손실은 3,656,000원이다. 직전 기수 기본 후보보다 '
        '환급이 192,000원 늘었지만, 기수 정보 추가 전 확장 pair보다 168,000원, 공동 주변확률 '
        'Top2보다 131,000원 적었다. 현재 후보의 연도별 순수익률은 2025년 −33.777%, '
        '2026년 부분연도 −29.652%다. 비교한 모든 방식의 등액 수익률은 음수였다.\n\n'
        '2025-07-25 제주1R에서 현재 3-6 쌍은 2.3배, 확장 pair의 2-6 쌍은 31.5배로 '
        '둘 다 적중했다. 이 원문 배당은 별도로 검증했다. 적중수 증가만으로 수익률 개선을 '
        '단정할 수 없으며, 고배당 일부 경주가 이 표본의 순위를 바꿀 수 있다. '
        '2024년 637경주는 QPL 미보유로 제외했다. 반복 개발기간의 사후 회계 비교이며 '
        '미래 수익·최적 정책·운영 HY_R_FORM 대비 우세를 확인한 결과는 아니다. '
        '말 평가·선택·모델·운영 기준은 바꾸지 않았다. Luna xhigh 분석과 감독의 독립 '
        '10,278행 환급·27개 집계·197개 원문 페이지 대조가 일치했다. '
        '[전체 결과](../20261013_pair_qpl_roi_v1/README.md), '
        '[검토 결과](../20261013_pair_qpl_roi_v1/ROOT_REVIEW.json).\n')
    after[NAMES[0]] += text.encode()
    after['README.md'] += ('\n[복연승 한 조합 등액 수익률](../20261013_pair_qpl_roi_v1/README.md): '
        '동일 1,142경주에서 현재 후보 −32.01%, 직전 기수 기본 후보 −33.70%, '
        '기수 정보 추가 전 확장 pair −30.54%, 공동 주변확률 Top2 −30.87%였다. '
        '아홉 방식 모두 손실이며 과거표본의 단순 환급 비교다. 독립 검산 PASS; 운영 변경 없음.\n').encode()
    after['SOURCES.md'] += ('\n- [20261013_pair_qpl_roi_v1](../20261013_pair_qpl_roi_v1/README.md): '
        '저장 아홉 selector의 동일 1,142경주·복연승 한 조합·경주당 1만원 환급/손익 비교. '
        '원문 배당 197페이지와 10,278행 환급·27개 집계를 독립 검산했다. '
        '[공식 보고서](../20261013_pair_qpl_roi_v1/REPORT.json), '
        '[독립 검토](../20261013_pair_qpl_roi_v1/ROOT_REVIEW.json).\n').encode()
    register = json.loads(before['research_register.json'])
    old_topics = json.loads(before['research_register.json'])['topics']
    register['updated_at'] = '2026-10-13'
    topic = next(t for t in register['topics'] if t['id'] == 'pair_top3_direct_20261011')
    topic['equal_stake_qpl_backtest_20261013'] = {
        'source': '../20261013_pair_qpl_roi_v1/README.md',
        'review': '../20261013_pair_qpl_roi_v1/ROOT_REVIEW.json',
        'period': ['2025-01-03', '2026-09-19'], 'races_per_selector': 1142,
        'stake_krw_per_race': 10000, 'summaries': report['same_denominator_summary'],
        'year_summaries': report['year_summary'], 'operational_promotion': False,
        'interpretation': 'Retrospective fixed-selection gross-dividend accounting, not future profitability'}
    assert len(register['topics']) == len(old_topics) == 25
    assert all(x == y for x, y in zip(register['topics'], old_topics)
               if x['id'] != 'pair_top3_direct_20261011')
    after['research_register.json'] = encode(register)
    manifest = json.loads(before['source_manifest.json'])
    old_rows = {r['path']: r for r in manifest['files']}
    rows = dict(old_rows)
    for name in NAMES[:-1]:
        key = (CENTRAL / name).relative_to(ROOT).as_posix()
        rows[key] = {**rows[key], 'sha256': sha(after[name]), 'bytes': len(after[name])}
    new_paths = [p for p in STUDY.rglob('*') if p.is_file()
                 and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
    for path in new_paths:
        key = path.relative_to(ROOT).as_posix()
        assert key not in rows
        data = path.read_bytes()
        rows[key] = {'path': key, 'role': 'equal_stake_qpl_backtest', 'sha256': sha(data), 'bytes': len(data)}
    manifest['updated_at'] = '2026-10-13'
    manifest['files'] = sorted(rows.values(), key=lambda r: r['path'])
    manifest['managed_files_bytes_excluding_this_manifest'] = sum(r['bytes'] for r in rows.values())
    manifest['verification']['equal_stake_qpl_backtest_20261013'] = {
        'status': 'PASS', 'new_source_rows': len(new_paths), 'legacy_sources_preserved': True,
        'root_review': 'jeju/research/20261013_pair_qpl_roi_v1/ROOT_REVIEW.json',
        'all_methods_negative_sample_roi': True, 'operational_change': False}
    after['source_manifest.json'] = encode(manifest)
    backup = STUDY / 'publication/before'
    backup.mkdir(exist_ok=False)
    for name, data in before.items():
        (backup / name).write_bytes(data)
    assert all((CENTRAL / n).read_bytes() == before[n] for n in NAMES), 'Concurrent edit; rebase publication'
    for name in NAMES:
        assert (CENTRAL / name).read_bytes() == before[name]
        temp = CENTRAL / (name + '.qpl_roi.tmp')
        temp.write_bytes(after[name])
        temp.replace(CENTRAL / name)
    receipt = {'status': 'PASS', 'before': {n: sha(v) for n, v in before.items()},
               'after': {n: sha(v) for n, v in after.items()}, 'new_source_rows': len(new_paths)}
    (STUDY / 'publication/RECEIPT.json').write_bytes(encode(receipt))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()

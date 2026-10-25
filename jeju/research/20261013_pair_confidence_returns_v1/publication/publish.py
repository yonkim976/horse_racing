"""Publish the reviewed confidence-mask accounting without selecting a policy."""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
STUDY = ROOT / 'jeju/research/20261013_pair_confidence_returns_v1'
CENTRAL = ROOT / 'jeju/research/conclusions'
NAMES = ['22_DIRECT_PAIR_TOP3_MODEL.md', 'README.md', 'SOURCES.md',
         'research_register.json', 'source_manifest.json']


def sha(value):
    return hashlib.sha256(value).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def serializable(frame):
    return frame.astype(object).where(pd.notna(frame), None).to_dict(orient='records')


def main():
    review = json.loads((STUDY / 'ROOT_REVIEW.json').read_text())
    report = json.loads((STUDY / 'REPORT.json').read_text())
    assert review['status'] == 'PASS'
    assert review['report_sha256'] == sha((STUDY / 'REPORT.json').read_bytes())
    for path, digest in report['source_sha256'].items():
        assert sha((ROOT / path).read_bytes()) == digest
    for path, digest in report['output_sha256'].items():
        assert sha((STUDY / path).read_bytes()) == digest
    bins = pd.read_csv(STUDY / 'bin_stats.csv')
    thresholds = pd.read_csv(STUDY / 'threshold_stats.csv')
    intervals = pd.read_csv(STUDY / 'bootstrap_ci.csv')
    before = {n: (CENTRAL / n).read_bytes() for n in NAMES}
    after = dict(before)
    section = ('\n## 2026-10-13 후속: 확률 구간과 선별 경주 환급\n\n'
        '기수 ID 후보의 저장 선택 쌍과 보정 확률을 고정하고 2025년 654경주·2026-09-19까지 '
        '488경주를 구간별로 집계했다. 확률은 두 말 동시 Top3 사건에 대한 값으로 복승의 '
        '정확 Top2 확률은 아니다. 각 승식은 선택 경주마다 10,000원 한 장이며, 표본 기간은 '
        '이미 반복 사용한 후향 개발 자료다. 구간은 하한 포함·상한 미포함, 마지막은 1 포함이다.\n\n'
        '| 동시 Top3 예측확률 | 경주 | 복연 적중률 | 복연 ROI | 복승 적중률 | 복승 ROI |\n'
        '|---|---:|---:|---:|---:|---:|\n')
    labels = ['0~10%', '10~15%', '15~20%', '20~25%', '25~30%', '30~40%', '40~50%', '50% 이상']
    for label, group in zip(labels, report['fixed_bins']):
        qpl = bins.loc[(bins.scope == 'all') & (bins.pool == 'QPL') & (bins.group == group)].iloc[0]
        qnl = bins.loc[(bins.scope == 'all') & (bins.pool == 'QNL') & (bins.group == group)].iloc[0]
        section += (f'| {label} | {int(qpl.n_races)} | {qpl.hit_rate_pct:.2f}% | {qpl.net_roi_pct:.2f}% '
                    f'| {qnl.hit_rate_pct:.2f}% | {qnl.net_roi_pct:.2f}% |\n')
    section += ('\n복연은 전체 24.78% 적중·ROI −32.01%에서 p≥0.30의 252경주 '
        '(전체의 22.07%)에서는 39.29%·−13.77%였다. p≥0.50의 13경주에서는 적중률 '
        '46.15%라도 평균 적중배당이 1.40배로 낮아 ROI −35.38%였다. 확신도 증가와 '
        '수익률 증가는 같은 결과가 아니다.\n\n'
        '복승 p≥0.40의 61경주는 ROI +5.90%였지만 고정 날짜 bootstrap 95% 구간은 '
        '[−46.95%,+87.48%]였다. 같은 조건의 2025년 18경주는 +59.44%, 2026년 부분 '
        '43경주는 −16.51%로 방향이 달랐다. 40~50% 단일 구간의 +15.83%와 40% 이상 '
        '누적 조건의 +5.90%는 분모가 다르므로 합쳐 읽지 않는다.\n\n'
        '고정 8개 구간·8개 누적 조건을 전체/연도별로 비교했으며, 가장 좋은 사후 조건을 '
        '채택하거나 추천하지 않았다. 기존 2,000×269 날짜 schedule을 재사용하고 선택 '
        '표본이 없는 반복은 제외 수를 기록했다. 2024년 배당 미보유·2026년 부분연도·'
        '반복 표본이라는 한계는 남는다. 감독이 2,284개 승식별 원행, 96개 통계, 288개 '
        'CI를 독립 검산해 PASS했다. 모델·말 평가·운영 기준 변경은 없다. '
        '[전체 분석](../20261013_pair_confidence_returns_v1/publication/REPORT.md), '
        '[독립 검토](../20261013_pair_confidence_returns_v1/ROOT_REVIEW.json).\n')
    after[NAMES[0]] += section.encode()
    after['README.md'] += ('\n[확률 구간별 복승·복연 수익률](../20261013_pair_confidence_returns_v1/publication/REPORT.md): '
        '고정 현재 후보 p≥0.30에서 복연 ROI −13.77%(252경주), p≥0.40 복승 +5.90%'
        '(61경주, 95% 구간 −46.95~+87.48%)였다. 높은 확신의 낮은 배당·소표본·연도별 '
        '방향 차이가 남아 수익성 기준을 확정하지 않았다. 독립 검산 PASS; 운영 변경 없음.\n').encode()
    after['SOURCES.md'] += ('\n- [20261013_pair_confidence_returns_v1](../20261013_pair_confidence_returns_v1/README.md): '
        '고정 Top3 pair 확률의 8구간·8누적 조건, 같은 1,142경주와 1만원 등액 복승/복연 '
        '환급 비교. [전체 보고서](../20261013_pair_confidence_returns_v1/publication/REPORT.md), '
        '[독립 검토](../20261013_pair_confidence_returns_v1/ROOT_REVIEW.json). '
        '저장 날짜 재표집만 사용했으며 새로운 학습·임계값 채택은 없다.\n').encode()
    register = json.loads(before['research_register.json'])
    register['updated_at'] = '2026-10-13'
    topic = next(t for t in register['topics'] if t['id'] == 'pair_top3_direct_20261011')
    topic['confidence_returns_20261013'] = {
        'source': '../20261013_pair_confidence_returns_v1/publication/REPORT.md',
        'review': '../20261013_pair_confidence_returns_v1/ROOT_REVIEW.json',
        'confidence_definition': report['confidence_definition'], 'cohort': report['cohort'],
        'bin_summary': serializable(bins.loc[bins.scope.eq('all')]),
        'threshold_summary': serializable(thresholds.loc[thresholds.scope.eq('all')]),
        'high_confidence_roi_intervals': serializable(intervals.loc[
            intervals.scope.eq('all') & intervals.metric.eq('net_roi_pct')]),
        'threshold_selected_or_recommended': False, 'operational_change': False,
        'interpretation': 'Repeated retrospective fixed-mask comparison; uncertain high-confidence profitability'}
    after['research_register.json'] = encode(register)
    manifest = json.loads(before['source_manifest.json'])
    rows = {r['path']: r for r in manifest['files']}
    for name in NAMES[:-1]:
        key = (CENTRAL / name).relative_to(ROOT).as_posix()
        rows[key] = {**rows[key], 'sha256': sha(after[name]), 'bytes': len(after[name])}
    new = [p for p in STUDY.rglob('*') if p.is_file() and '__pycache__' not in p.parts
           and ('publication' not in p.relative_to(STUDY).parts
                or p.relative_to(STUDY).as_posix() == 'publication/REPORT.md')]
    for path in new:
        key = path.relative_to(ROOT).as_posix()
        assert key not in rows
        data = path.read_bytes()
        rows[key] = {'path': key, 'role': 'confidence_returns_diagnostic', 'sha256': sha(data), 'bytes': len(data)}
    manifest['updated_at'] = '2026-10-13'
    manifest['files'] = sorted(rows.values(), key=lambda r: r['path'])
    manifest['managed_files_bytes_excluding_this_manifest'] = sum(r['bytes'] for r in rows.values())
    manifest['verification']['confidence_returns_20261013'] = {
        'status': 'PASS', 'new_source_rows': len(new), 'old_sources_preserved': True,
        'root_review': 'jeju/research/20261013_pair_confidence_returns_v1/ROOT_REVIEW.json',
        'official_human_report_indexed': True, 'metadata_staging_excluded': True,
        'future_profitability_confirmed': False, 'operational_change': False}
    after['source_manifest.json'] = encode(manifest)
    backup = STUDY / 'publication/before'
    backup.mkdir(exist_ok=False)
    for name, data in before.items():
        (backup / name).write_bytes(data)
    assert all((CENTRAL / n).read_bytes() == before[n] for n in NAMES), 'Concurrent edit'
    for name in NAMES:
        assert (CENTRAL / name).read_bytes() == before[name]
        temporary = CENTRAL / (name + '.confidence.tmp')
        temporary.write_bytes(after[name])
        temporary.replace(CENTRAL / name)
    receipt = {'status': 'PASS', 'before': {n: sha(v) for n, v in before.items()},
        'after': {n: sha(v) for n, v in after.items()}, 'new_source_rows': len(new)}
    (STUDY / 'publication/RECEIPT.json').write_bytes(encode(receipt))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()

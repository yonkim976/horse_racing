"""Append reviewed cross-pool accounting without changing model conclusions."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
STUDY = ROOT / 'jeju/research/20261013_qnl_tla_roi_v1'
CENTRAL = ROOT / 'jeju/research/conclusions'
NAMES = ['22_DIRECT_PAIR_TOP3_MODEL.md', 'README.md', 'SOURCES.md',
         'research_register.json', 'source_manifest.json']


def sha(value):
    return hashlib.sha256(value).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def main():
    review = json.loads((STUDY / 'ROOT_REVIEW.json').read_text())
    assert review['status'] == 'PASS'
    assert review['report_sha256'] == sha((STUDY / 'REPORT.json').read_bytes())
    report = json.loads((STUDY / 'REPORT.json').read_text())
    for path, digest in report['source_sha256'].items():
        assert sha((ROOT / path).read_bytes()) == digest
    before = {n: (CENTRAL / n).read_bytes() for n in NAMES}
    after = dict(before)
    section = ('\n## 2026-10-13 후속: 복승·삼복승 동일 예산 환급\n\n'
        '동일한 2025-01-03~2026-09-19의 1,142경주에서 경주당 총 6,000원 '
        '(방식당 총 6,852,000원)을 투입한 사후 회계를 비교했다. 복승은 저장 선택 쌍이 '
        '공식 Top2와 정확히 같을 때만 지급했다. 삼복승은 별도로 저장된 rank1 한 티켓에 '
        '6,000원, 또는 rank1~6 여섯 티켓에 각 1,000원을 배분했다.\n\n'
        '| 방식 | 적중 경주 | 순수익률 |\n|---|---:|---:|\n'
        '| 복승 현재 기수 ID 선택 쌍 | 145 | −23.57% |\n'
        '| 복승 직전 기수 기본 선택 쌍 | 141 | −25.14% |\n'
        '| 복승 말 점수 Top2 | 138 | −26.37% |\n'
        '| 삼복승 이전 F1 한 조합 / 6조합 | 80 / 260 | −16.71% / −36.42% |\n'
        '| 삼복승 F1_STYLE6 한 조합 / 6조합 | 74 / 257 | −20.75% / −34.18% |\n'
        '| 삼복승 공동 관계 후보 한 조합 / 6조합 | 69 / 276 | −30.00% / −29.77% |\n\n'
        '현재 pair의 복승 환급은 5,236,800원, 순손실은 1,615,200원이었다. '
        '기존 공동 모델 매칭 기준선의 삼복 집계는 F1_STYLE6과 같지만 별도로 보존했다. '
        '복연 현재 후보 참고값을 포함한 18가지 방식이 모두 순손실이다. '
        '기수 ID pair 후보는 세 번째 말을 고르는 정책이 없으므로 그 후보의 삼복승 결과를 '
        '만든 것이 아니다. 삼복승은 기존 F1·STYLE6·공동 관계 티켓을 그대로 재사용했다. '
        '2024년은 배당 미보유로 제외했고, 반복 개발기간의 기술 회계이며 독립 미래 검증이 '
        '아니다. 별도 복승·삼복 전용 학습, 조합 최적화, 운영 HY_R_FORM 비교나 변경은 없다. '
        '감독의 독립 43,396개 티켓·54개 집계·221개 당첨 원문 페이지 대조가 PASS했다. '
        '[전체 결과](../20261013_qnl_tla_roi_v1/README.md), '
        '[검토 결과](../20261013_qnl_tla_roi_v1/ROOT_REVIEW.json).\n')
    after[NAMES[0]] += section.encode()
    after['README.md'] += ('\n[복승·삼복승 동일 예산 비교](../20261013_qnl_tla_roi_v1/README.md): '
        '현재 pair의 복승 −23.57%. 기존 공동 관계 모델의 삼복승은 한 조합 −30.00%, '
        '6조합 −29.77%; STYLE6 기준선은 −20.75%/−34.18%였다. '
        '18가지 방식 모두 손실인 과거표본 회계이며 운영 변경 없음.\n').encode()
    after['SOURCES.md'] += ('\n- [20261013_qnl_tla_roi_v1](../20261013_qnl_tla_roi_v1/README.md): '
        '같은 1,142경주·경주당 6,000원으로 저장 pair 복승과 저장 삼복 rank1/6장 환급을 비교했다. '
        '[보고서](../20261013_qnl_tla_roi_v1/REPORT.json), '
        '[독립 검토](../20261013_qnl_tla_roi_v1/ROOT_REVIEW.json). '
        '현재 pair로 세 번째 말을 새로 생성하지 않았다.\n').encode()
    register = json.loads(before['research_register.json'])
    register['updated_at'] = '2026-10-13'
    topic = next(t for t in register['topics'] if t['id'] == 'pair_top3_direct_20261011')
    topic['equal_budget_qnl_tla_20261013'] = {
        'source': '../20261013_qnl_tla_roi_v1/README.md',
        'review': '../20261013_qnl_tla_roi_v1/ROOT_REVIEW.json',
        'cohort': report['cohort'], 'budget': report['budget'],
        'summary': [r for r in report['summary'] if r['period'] == '2025-2026'],
        'pair_to_triple_policy_created': False, 'operational_change': False,
        'interpretation': 'Repeated retrospective gross-dividend accounting, not future profitability'}
    after['research_register.json'] = encode(register)
    manifest = json.loads(before['source_manifest.json'])
    rows = {r['path']: r for r in manifest['files']}
    for name in NAMES[:-1]:
        path = (CENTRAL / name).relative_to(ROOT).as_posix()
        rows[path] = {**rows[path], 'sha256': sha(after[name]), 'bytes': len(after[name])}
    new = [p for p in STUDY.rglob('*') if p.is_file()
           and 'publication' not in p.relative_to(STUDY).parts and '__pycache__' not in p.parts]
    for path in new:
        key = path.relative_to(ROOT).as_posix()
        assert key not in rows
        data = path.read_bytes()
        rows[key] = {'path': key, 'role': 'cross_pool_equal_budget_returns', 'sha256': sha(data), 'bytes': len(data)}
    manifest['updated_at'] = '2026-10-13'
    manifest['files'] = sorted(rows.values(), key=lambda r: r['path'])
    manifest['managed_files_bytes_excluding_this_manifest'] = sum(r['bytes'] for r in rows.values())
    manifest['verification']['equal_budget_qnl_tla_20261013'] = {
        'status': 'PASS', 'new_source_rows': len(new), 'legacy_sources_preserved': True,
        'root_review': 'jeju/research/20261013_qnl_tla_roi_v1/ROOT_REVIEW.json',
        'same_race_budget': 6000, 'operational_change': False}
    after['source_manifest.json'] = encode(manifest)
    backup = STUDY / 'publication/before'
    backup.mkdir(exist_ok=False)
    for name, data in before.items():
        (backup / name).write_bytes(data)
    assert all((CENTRAL / n).read_bytes() == before[n] for n in NAMES), 'Concurrent edit'
    for name in NAMES:
        assert (CENTRAL / name).read_bytes() == before[name]
        temporary = CENTRAL / (name + '.qnl_tla.tmp')
        temporary.write_bytes(after[name])
        temporary.replace(CENTRAL / name)
    receipt = {'status': 'PASS', 'before': {n: sha(v) for n, v in before.items()},
        'after': {n: sha(v) for n, v in after.items()}, 'new_source_rows': len(new)}
    (STUDY / 'publication/RECEIPT.json').write_bytes(encode(receipt))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()

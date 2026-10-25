"""Publish the verified local study and update only Jeju research management."""
from pathlib import Path
import hashlib
import json
import re

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'run01'
CENTRAL = ROOT / 'jeju/research/conclusions'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, v):
    p.write_text(json.dumps(v, ensure_ascii=False, indent=2) + '\n')


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)] +
                     ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def main():
    assert json.loads((OUT / 'verification.json').read_text())['status'] == 'passed'
    assert json.loads((OUT / 'verification_independent.json').read_text())['status'] == 'passed'
    old = json.loads((CENTRAL / 'source_manifest.json').read_text())
    for r in old['files']:
        p = (ROOT / r['path']).resolve()
        assert p.is_relative_to(ROOT)
        assert sha(p) == r['sha256'], r['path']
    a = pd.read_csv(OUT / 'runner_position_intervals.csv')
    h = pd.read_csv(OUT / 'horse_profiles_recent10.csv')
    hd = pd.read_csv(OUT / 'horse_distance_profiles_recent10.csv')
    summary = json.loads((OUT / 'summary.json').read_text())
    # Compact Korean tables expose raw counts, never future style probabilities.
    mapping = {'horse_id': '말ID', 'horse_name': '최신마명', 'scope_distance_m': '거리m_0은통합',
               'age_2026': '2026기준나이', 'last_eligible_race_date': '마지막대상출전일',
               'window_first_date': '최근표본시작일', 'window_starts': '최근대상출전수',
               'definition_held_1300_starts': '1300초반정의보류수', 's1f_valid_starts': '초반유효관측수',
               'style_label': '위치성향후보', 'front_count': '확실전방수', 'middle_count': '확실중단수',
               'rear_count': '확실후방수', 'ambiguous_count': '집단경계불확실수',
               'first_group_count': '선두군소속수', 'solo_lead_count': '단독선두수',
               'c4_to_g1f_pairs': '4C_G1F유효쌍수', 'c4_to_g1f_definite_gain2_count': '4C_G1F확실2두이상전진수',
               'late_gain_tag': '후반전진태그', 'has_eligible_start_2025_2026': '2025_2026대상출전관측'}
    for name, data in [('말별_각질후보', h), ('거리별_말별_각질후보', hd)]:
        data = data.sort_values(['last_eligible_race_date', 'horse_id', 'scope_distance_m'], ascending=[False, True, True])
        data[list(mapping)].rename(columns=mapping).to_csv(HERE / (name + '.csv'), index=False, encoding='utf-8-sig')
    examplekeys = [(3103290, 1110), (3103323, 1000), (3107551, 900), (3103288, 1000), (3017983, 1110)]
    examples = [hd[(hd.horse_id == horse) & (hd.scope_distance_m == dist)].iloc[0] for horse, dist in examplekeys]
    example_table = table(['말과 거리', '유효 관측', '전방 / 중단 / 후방 / 불확실', '선두군', '4C→G1F 확실 전진', '분류 후보'],
                          [[f'{r.horse_name} {r.scope_distance_m}m', f'{r.s1f_valid_starts}회',
                            f'{r.front_count} / {r.middle_count} / {r.rear_count} / {r.ambiguous_count}',
                            f'{r.first_group_count}/{r.s1f_valid_starts}',
                            f'{r.c4_to_g1f_definite_gain2_count}/{r.c4_to_g1f_pairs}', r.style_label] for r in examples])
    support = []
    for dist, g in a.groupby('race_distance_m'):
        valid = g.s1f_zone.notna()
        support.append([int(dist), len(g), g.race_id.nunique(), int(valid.sum()),
                        int((g.s1f_zone == 'ambiguous').sum()), '초반 판정 보류' if dist == 1300 else 'S1F 기준 후보'])
    support_table = table(['거리 m', '출전', '경주', 'S1F 유효', '집단경계 불확실', '초반 분류 상태'], support)
    current = h[h.has_eligible_start_2025_2026]
    labels = ['선두군형 후보', '선입형 후보', '중단형 후보', '후미대기형 후보', '혼합 또는 집단경계 불확실', '자료부족']
    class_table = table(['분류', '전체 말 수', '2025·2026 대상 출전 관측 말 수'],
                        [[label, int(h.style_label.eq(label).sum()), int(current.style_label.eq(label).sum())] for label in labels])
    report = f'''# 제주마 통과조 기반 말별 각질 후보

통과조로 **초반 위치 성향과 후반 전진 성향을 나누어 표시하는 방식**이 적합하다. 최근 출전에서 전방을 반복하는 말과 후방을 반복하는 말을 구분할 수 있지만, 같은 집단 안의 순서와 전술 의도는 확정할 수 없다. 후미대기와 추입도 별도다. 이번 결과는 설명용 분류 후보이며 미래 경주 예측 성능이나 전통적 각질의 정답을 검증한 결과가 아니다.

2017-01-01~2026-09-19 정상 완주·완전 경주 **{summary['rows']:,}출전·{summary['races']:,}경주·{summary['horses']:,}두**를 분석했다. 2026년은 부분연도다. 2025·2026년에 대상 출전이 관측된 말은 {len(current):,}두이며 현재 등록·활동마 전체라는 뜻은 아니다. 비정상 종료 경주·일부 후보만 보유한 경주·6두 미만 경주 등은 기존 strict 계약에 따라 제외됐다. 현재 거리8종만 사용하고400m는 제외했다.

## 통과조를 읽는 기준

공식 용어해설을 대조한 [보유 의미 검토](../20261003_unresolved_section_review/semantic_review/README.md)에 따르면 괄호 안 마번은 같은 집단 안에서 내측부터 적힌 것이다. `(1,5,7)`을1→5→7의 개별 순위로 해석하지 않는다. 앞선 말이2두라면 세 말 모두 **3~5위 범위**로 계산한다. 집단 내부를 바꾸어도 결과는 같아야 한다.

출전두수를 반영해 이 범위 전체가 앞1/3에 있으면 전방, 가운데1/3이면 중단, 뒤1/3이면 후방으로 센다. 범위가 경계를 걸치면 집단경계 불확실로 남긴다. 첫 집단 소속과 단독 선두는 별도 기록하며, 선두군 소속을 실제 단독 선행으로 바꾸지 않는다.

기본 위치는 S1F로만 분류한다. S1F가 없으면 다른 코너로 대신하지 않는다. 1300m는 S1F/2C 측정 정의가 미확정이므로 초반 각질 판정과S1F→4C 전진 판정을 보류한다. 해당 거리의 관측 범위와4C→G1F 전진은 별도 보존했다. 코너 표시 열을 모두 시간순으로 연결하지 않았고 G3F 막판시간을 통과조로 만들지 않았다.

## 말별 분류 규칙

말 전체 거리 통합과 정확거리별 프로필을 각각 만든다. **마지막 해당 대상 출전일 기준730일 안의 최근10회 대상 출전**을 쓴다. 오래된 유효 관측으로 결측을 채우지 않는다. 최소5회 유효S1F, 최근 정의 지원 출전의 유효율60% 이상에서 다음 규칙을 적용한다. 통합표의1300m는 초반 비율 분모에서 제외하고 제외 횟수를 표시한다.

| 후보 | 설명용 기준 |
|---|---|
| 선두군형 | 확실한 전방60% 이상이고 첫 집단 소속60% 이상 |
| 선입형 | 확실한 전방60% 이상이며 선두군형 기준에는 미달 |
| 중단형 | 확실한 중단60% 이상 |
| 후미대기형 | 확실한 후방60% 이상 |
| 혼합 또는 집단경계 불확실 | 한 위치가 반복 기준에 미달. 실제 위치 변화와 집단 관측 불확실성을 함께 포함 |
| 자료부족·측정정의보류 | 유효 표본·커버리지 미달 또는1300m 초반 의미 미확정 |

**60%·5회·730일·최근10회는 이번에 먼저 정한 설명 규칙이다. 최적 기준이나 미래 각질 확률로 검증하지 않았다.** 불확실한 집단도 유효 관측 분모에 포함해 확실한 위치의 비율을 과장하지 않는다. 전체 비율의 분자·분모 및 단순Wilson 점별95% 구간은 상세 프로필에 있다. 이 구간은 반복 출전의 독립성을 가정하는 기술 구간이며 미래 확률의 신뢰구간이 아니다.

## 실제 말별 사례

{example_table}

표의 관측 종료일은 흑룡시대·황룡강·흥부시대2026-09-19, 녹원매직09-04, 삼다장군09-18이다. 거리별 최근 대상 출전으로 계산했다. 후반 확실 전진은4C 순위범위 하한보다G1F 상한이2위 이상 앞선 경우다. 예를 들어4C가8~10위이고G1F가5~6위이면 적어도2두를 앞선 것으로 센다. 범위가 겹치면 전진하지 않았다는 뜻이 아니라 전진을 확정하지 못한 것이다.

흥부시대1000m와 삼다장군1110m는 모두 후방을 반복하지만 후반 확실 전진은 각각1/10회와6/10회다. **후방 위치만으로 두 말을 같은 추입형으로 묶으면 이 차이가 사라진다.** 삼다장군1110m에는 설명용 후반 전진 반복 태그를 붙였다. 순위 전진은 막판 속도·가속·입상·말의 능력과 같지 않다.

거리별표를 먼저 보는 편이 좋다. 예를 들어 흑룡시대1000m는 최근10회 전방8회·선두군3회로 선입형 후보,1110m는 전방8회·선두군7회로 선두군형 후보다. 두 거리의 관측 종료일도 각각2025-08-08과2026-09-19로 달라 순수한 거리 효과로 해석할 수 없다.

## 분류 범위와 불확실성

{class_table}

전체2813두 중 위치 후보4종에 들어간 말은708두다. 나머지는 혼합·집단경계 불확실 또는 자료부족이다. 이는 각질이 없다는 뜻이 아니다. S1F 유효52,095출전 중16,929출전(**{16929 / 52095:.1%}**)은 집단이 위치 구간 경계를 걸쳤다. 따라서 단일 각질명만 표시하기보다 **전방·중단·후방·불확실 비율, 선두군/단독 선두 비율, 후반 전진 비율, 거리, 관측 수·종료일**을 함께 보여주는 것이 적합하다.

{support_table}

S1F 유효52,095출전 중1300m606출전은 초반 명칭 판정에서 보류해 정의 지원 유효 관측은51,489출전이다. S1F60출전은 기존 충돌 보류로NULL이며 다른 원값으로 채우지 않았다. 주어진 정상 완주 표본의3개 핵심 지점에서는 문법·마번 집합 불일치가 없었다. 전체6개 지점의 유효율·미사용·보류 상태는 별도 표에 있다. 유효API 값의 `api_group_unreviewed`는 모든 홈페이지 대조를 완료했다는 뜻은 아니다.

최근5회(최소3회)와10회 비교에서 두 방식 모두 구체 후보4종으로 분류된632두 중560두가 같았다(88.6%). 2025·2026 대상 출전 관측 말에서는280두 중236두(84.3%)다. **최근5회가10회에 겹치고 양쪽 분류 가능 표본만 비교했으므로 미래 재현율·분류 정확도가 아니다.** 거리별 결과는 [윈도 민감도](run01/window_sensitivity.csv)에 있다. 1610m9경주는 소표본이며 전체 거리 통합으로 이 부족을 숨기지 않는다.

## 저장 자료와 사용 범위

- [말별 간단표](말별_각질후보.csv): 전체2813두, 최근 출전일 순.2025·2026 관측 여부와 기본 분자·분모.
- [거리별 말별 간단표](거리별_말별_각질후보.csv): 말×거리7828조합.1300m176조합의 초반 판정 보류 포함.
- [말별 최근10회 상세](run01/horse_profiles_recent10.csv)와 [거리별 상세](run01/horse_distance_profiles_recent10.csv): 비율·기술 구간·원천 출전ID.
- [출전별 위치 범위](run01/runner_position_intervals.csv), [경주별6지점 감사](run01/race_point_audit.csv), [거리·연도별 커버리지](run01/point_coverage_by_distance_year.csv), [품질 상태](run01/point_status_counts.csv).
- [원천 출전 연결](run01/source_lineage.csv), [입력 해시](run01/source_manifest.json), [계산 검증](run01/verification.json), [보존 파서와 원행 재대조](run01/verification_independent.json), [사전 계획](PLAN.md), [계산 코드](analyze.py), [검증 코드](verify.py), [출판 코드](publish.py), [보관 목록과 크기](artifact_manifest.json).

모든 연결은 공식 말ID다. 최신API42 마명과2026년 고정 나이를 사용하며 과거 출전 당시 나이와 구분한다. 제외 말3005648은 편입하지 않았다. 전체31,236경주×지점 점검과 괄호 내부 순서 불변 검사를 수행했고, 별도로 보존 파서의 구간 및 모든 최근 프로필의 출전ID·창·분자를 재대조했다. DB는읽기전용이며 실행전후SHA가동일하다.

재실행은새출력폴더를지정한후계산·검증·출판순서로진행한다. 기존run01은덮어쓰지않는다. 연구관리등록은운영모델반영과별개다. 미래입력채택시최소T−2의과거이력으로만프로필을구성하고후속경주의위치·전진을별도로검증해야한다. 이번에는같은경주의사후값을사전입력에연결하지않았고DB·운영모델·웹을변경하지않았다.
'''
    # Keep prose readable; no compressed execution-log phrasing in the report.
    report = report.replace('DB는읽기전용이며 실행전후SHA가동일하다.', 'DB는 읽기 전용이며 실행 전후 SHA가 동일하다.')
    report = report.replace('재실행은새출력폴더를지정한후계산·검증·출판순서로진행한다. 기존run01은덮어쓰지않는다. 연구관리등록은운영모델반영과별개다. 미래입력채택시최소T−2의과거이력으로만프로필을구성하고후속경주의위치·전진을별도로검증해야한다. 이번에는같은경주의사후값을사전입력에연결하지않았고DB·운영모델·웹을변경하지않았다.',
                            '재실행은 새 출력 폴더를 지정한 후 계산·검증·출판 순서로 진행한다. 기존run01은 덮어쓰지 않는다. 연구 관리 등록은 운영 모델 반영과 별개다. 미래 입력 채택 시 최소T−2의 과거 이력으로만 프로필을 구성하고 후속 경주의 위치·전진을 별도로 검증해야 한다. 이번에는 같은 경주의 사후값을 사전 입력에 연결하지 않았고 DB·운영 모델·웹을 변경하지 않았다.')
    report = re.sub(r'(?<=[가-힣])(?=[A-Za-z0-9])', ' ', report)
    (HERE / 'README.md').write_text(report)
    topic = '''# 통과조 기반 말별 각질 후보

통과조의 집단 범위로 초반 위치 성향과 후반 전진 성향을 나누어 표시한다. 같은 집단의 괄호 내부 순서는 개별 순위가 아니다. 후미대기형을 자동으로 추입형으로 바꾸지 않는다. 선두군 소속과 단독 선두도 구분한다.

2017-01-01~2026-09-19 정상 완주·완전 경주52,155출전·5,206경주·2,813두를 분석했다. 2026년은 부분연도다. 마지막 대상 출전일 기준730일 안의 최근10회, 유효S1F 최소5회·커버리지60% 이상, 확실 위치60% 반복 규칙을 사용했다. 이 기준은 설명용 사전 선택이며 최적화하거나 미래 정확도를 검증한 기준이 아니다.

전체 말별 후보는 선두군209두·선입207두·중단11두·후미대기281두, 혼합 또는 집단경계 불확실1358두·자료부족747두다. 현재 등록마 전체가 아니며2025·2026 대상 출전 관측 말은1198두다. S1F 유효52,095출전 중32.5%는 집단이 위치 경계를 걸쳤다. 단일 명칭과 함께 위치 비율·불확실 비율·관측 수·거리·종료일을 제공한다.

1300m는S1F/2C 측정 정의 미확정 때문에 초반 명칭과S1F→4C 전진을 보류한다.1610m는9경주로 소표본이다. 거리별표를 우선 해석하며 거리 간 관측 시기가 다를 수 있다.4C→G1F에서 순위범위로 확실한2두 이상 전진만 따로 센다. 삼다장군1110m는 후방10/10회·후반 확실 전진6/10회, 흥부시대1000m는 후방8/10회·전진1/10회다. 위치 변화가 막판 속도나 전술 의도의 정답은 아니다.

최근5회와10회 모두 구체 후보가 붙은632두 중560두(88.6%)가 같았다. 중첩 표본과 조건부 비교이며 미래 재현율·독립 검증이 아니다. 기존 품질 보류를 우회하지 않았고 DB·운영 모델·웹 반영은 없다.

- [상세 결과와 방법](../20261008_passing_group_running_style_v1/README.md)
- [말별 간단표](../20261008_passing_group_running_style_v1/말별_각질후보.csv)
- [거리별 말별 간단표](../20261008_passing_group_running_style_v1/거리별_말별_각질후보.csv)
- [사전 계획](../20261008_passing_group_running_style_v1/PLAN.md)과 [입력·출전·검증 목록](../20261008_passing_group_running_style_v1/artifact_manifest.json)

상태는 **통과조 기반 설명용 분류 후보 생성 완료, 전통적 각질 정답·미래 예측 미검증, 운영 미반영**이다. 향후 예측 입력은T−2 이전 과거 출전으로만 구성하고 다음 경주 위치와 전진에 대해 별도 평가해야 한다.
'''
    topic = re.sub(r'(?<=[가-힣])(?=[A-Za-z0-9])', ' ', topic)
    (CENTRAL / '07_RUNNING_STYLE.md').write_text(topic)
    readme = (CENTRAL / 'README.md').read_text()
    readme = readme.replace('·조교 연구다.', '·조교·통과조 기반 각질 연구다.')
    newrow = '| [통과조 기반 말별 각질](07_RUNNING_STYLE.md) | 최근 위치 성향과 후반 전진을 분리.2813두·거리별7828조합,1300m 초반 정의 보류 | 설명용 후보 생성,미래 예측·운영 미반영 |\n'
    readme = readme.replace('| [원 연구와 버전 목록]', newrow + '| [원 연구와 버전 목록]')
    (CENTRAL / 'README.md').write_text(readme)
    sources = (CENTRAL / 'SOURCES.md').read_text()
    addition = '| [20261008_passing_group_running_style_v1](../20261008_passing_group_running_style_v1/README.md) | 통과조 집단 순위 범위로 말별·거리별 최근 위치 성향과 후반 확실 전진을 분리.52,155출전·2,813두,1300m 초반 보류.설명용 규칙 후보이며 미래 예측 미검증 |\n\n'
    sources = sources.replace('같은 출전 자료가 여러 버전에 중복되므로', addition + '같은 출전 자료가 여러 버전에 중복되므로')
    (CENTRAL / 'SOURCES.md').write_text(sources)
    reg = json.loads((CENTRAL / 'research_register.json').read_text())
    assert not any(t['id'] == 'running_style' for t in reg['topics'])
    reg['scope'] = reg['scope'].replace('조교 연구.', '조교·통과조 기반 각질 연구.')
    reg['topics'].append({'id': 'running_style', 'title': '통과조 기반 말별 각질 후보',
                          'conclusion': '07_RUNNING_STYLE.md', 'latest_source': '../20261008_passing_group_running_style_v1/README.md',
                          'period_start': '2017-01-01', 'period_end': '2026-09-19', 'partial_2026': True,
                          'population': 'normal_complete_current_distance_strict_cohort', 'source_rows': 52155,
                          'races': 5206, 'horses': 2813, 'horse_distance_profiles': 7828,
                          'recent_window_starts': 10, 'window_max_days': 730, 'minimum_valid_early_observations': 5,
                          'style_repeat_threshold': .6, 'early_definition_held_distances_m': [1300],
                          'status': 'descriptive_group_interval_style_candidates_created',
                          'traditional_style_truth_validated': False, 'future_prediction_tested': False,
                          'operationally_applied': False})
    save(CENTRAL / 'research_register.json', reg)
    # Verify relative local links in all management Markdown and the new report.
    links = 0
    for p in list(CENTRAL.glob('*.md')) + [HERE / 'README.md', HERE / 'PLAN.md']:
        for target in re.findall(r'\]\(([^)]+)\)', p.read_text()):
            if '://' in target or target.startswith('#'):
                continue
            target = target.split('#')[0]
            if target.endswith('artifact_manifest.json'):
                continue  # Created immediately below.
            assert (p.parent / target).resolve().exists(), (p, target)
            links += 1
    save(HERE / 'publication_verification.json', {'status': 'passed', 'all_previous_source_hashes_unchanged': True,
                                                'local_links_checked': links, 'new_profile_files': 2,
                                                'future_prediction_tested': False, 'operational_change': False})
    files = [{'path': str(p.relative_to(HERE)), 'bytes': p.stat().st_size, 'sha256': sha(p)}
             for p in sorted(HERE.rglob('*')) if p.is_file() and p.name != 'artifact_manifest.json']
    save(HERE / 'artifact_manifest.json', {'self_excluded': True, 'files': files,
                                          'total_bytes_excluding_this_manifest': sum(r['bytes'] for r in files)})
    # Mutable management entries are refreshed, previous dated sources are preserved.
    records = {r['path']: r for r in old['files']}
    for p in CENTRAL.iterdir():
        if p.is_file() and p.name != 'source_manifest.json':
            records[str(p.relative_to(ROOT))] = {'path': str(p.relative_to(ROOT)), 'role': 'conclusion_or_management',
                                                'sha256': sha(p), 'bytes': p.stat().st_size}
    for p in sorted(HERE.rglob('*')):
        if p.is_file():
            records[str(p.relative_to(ROOT))] = {'path': str(p.relative_to(ROOT)), 'role': 'source_running_style',
                                                'sha256': sha(p), 'bytes': p.stat().st_size}
    old['files'] = list(records.values())
    old['verification'] = {'status': 'passed', 'all_previous_source_hashes_unchanged': True,
                           'latest_study': str(HERE.relative_to(ROOT)),
                           'latest_verification': str((HERE / 'publication_verification.json').relative_to(ROOT)),
                           'local_links_checked': links}
    old['managed_files_bytes_excluding_this_manifest'] = sum(r['bytes'] for r in old['files'])
    save(CENTRAL / 'source_manifest.json', old)
    assert all(sha(ROOT / r['path']) == r['sha256'] for r in old['files'])
    print(json.dumps({'published': str(HERE), 'study_files': len(files) + 1,
                      'study_bytes': sum(p.stat().st_size for p in HERE.rglob('*') if p.is_file()),
                      'local_links_checked': links}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

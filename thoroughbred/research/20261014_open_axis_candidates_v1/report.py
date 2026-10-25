"""Publish a reproducible, explicitly retrospective local research summary."""
import html
import json
import re

import pandas as pd

import run as e

LABEL = {'frozen103': '기존103', 'frozen122': '기존122', 'joint_logit': '직전 두축 선택51',
         'gain_logit_two': '이번 학습·두축만', 'gain_logit_all': '이번 학습·전체말',
         'gain_tree_two': '작은트리·두축만', 'gain_tree_all': '작은트리·전체말'}
PERIODS = ['2024', '2025', '2026', 'all']


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |']
                     + ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def main():
    e.check()
    verification = json.loads((e.OUT / 'verification.json').read_text())
    assert verification['status'] == 'verified'
    central = e.R / 'conclusions/53_OPEN_AXIS_CANDIDATES.md'
    assert not central.exists() or e.HERE.name in central.read_text(), 'conclusion53 occupied'
    m = pd.read_csv(e.OUT / 'metrics.csv', dtype={'period': str})
    changes = pd.read_csv(e.OUT / 'paired_differences.csv', dtype={'period': str})
    t = pd.read_csv(e.OUT / 'third_axis_summary.csv', dtype={'period': str})
    training = pd.read_csv(e.OUT / 'training_counts.csv')
    lookup = m.set_index(['variant', 'period'])
    variants = ['frozen103', 'frozen122', 'joint_logit', 'gain_logit_two', 'gain_logit_all']
    metric_tables = {}
    for metric in ['axis_top3', 'quinella_one', 'axis_next3']:
        metric_tables[metric] = table(['기간', '경주'] + [LABEL[v] for v in variants],
            [[p, int(lookup.loc[('gain_logit_all', p), 'n'])]
             + [f'{lookup.loc[(v, p), metric]*100:.2f}%' for v in variants] for p in PERIODS])
    rows = []
    for reference in ['joint_logit', 'gain_logit_two', 'frozen122']:
        for metric, label in [('axis_top3', '축입상'), ('quinella_one', '복승1개'), ('axis_next3', '축복승3개')]:
            x = changes[changes.variant.eq('gain_logit_all') & changes.reference.eq(reference)
                        & changes.period.eq('all') & changes.metric.eq(metric)].iloc[0]
            rows.append([LABEL[reference], label, int(x.gain), int(x.loss), int(x.net),
                         f'{x.difference_pp:+.3f}', f'[{x.lo_pp:+.3f}, {x.hi_pp:+.3f}]'])
    paired = table(['비교 기준', '지표', '새적중', '상실', '순증감', '차이%p', '날짜95%구간%p'], rows)
    rows = []
    for p in PERIODS:
        x = t[t.variant.eq('gain_logit_all') & t.period.eq(p)].iloc[0]
        rows.append([p, int(x.third_selected), int(x.third_top3),
                     f'{x.third_top3/x.third_selected*100:.2f}%', int(x.both_original_miss),
                     int(x.both_miss_rescued), int(x.third_gain_vs_prior), int(x.third_loss_vs_prior)])
    third = table(['기간', '제3축 선택', '제3축 입상', '선택군 입상률', '두원축 모두실패',
                   '그중 회복', '제3축 새적중 vs51', '제3축 상실 vs51'], rows)
    allrow = t[t.variant.eq('gain_logit_all') & t.period.eq('all')].iloc[0]
    body = f'''# 제3의 말을 포함한 전체 출전마 축 선택

2026-10-14. 연구53. **제3의 말로 두 원래 축이 모두 놓친202경주를 회복했지만, 직전 두축 선택모델 대비 전체 축 입상은61.12%→61.14%(+1경주)로 거의 같았다.** 2024+1/2025+22/2026−22로 엇갈렸다. 복승1개는12.17%→12.11%(−3),축복승3개는27.90%→28.59%(+33)였다. 동일한 새 학습모델의 두축 제한 대비 후보확대만 보면 축+10/복승1개−3/축복승3개+23이며 세 차이의95%구간 모두0을 포함한다. 운영 대체·미래검증 완료로 판정하지 않는다.

## 1. 무엇을 바꿨나

기존103/122능력모델은 동결했다. 122축을 기준으로 나머지 **모든 출전마**를 교체 후보로 만들었다. 제3의 말은 원래 두축 모두와 다른 말이며 모델3위 말에 국한되지 않는다. 실제 착순으로 후보를 찾거나 두축이 실제 실패한 경주만 학습하지 않았다. 기준과 후보 중 후보만Top3=득,기준만Top3=실,둘다성공/둘다실패=중립을 학습했다.

후보별P득−P실의 최대를 선택하되 기준축 기대득실은 정확히0이다. 최댓값 동점이면 기준축/122순위/마번 순서다. 같은 선택모형으로 two(원래두축만)와 all(전체출전마)을 각각 계산해 후보확대 효과와 선택모델학습 효과를 구분했다. 선택한축만 맨앞으로 이동하고 나머지122순위는 유지했다. 상대마나 조합 전용모델을 새로 학습한 실험이 아니다.

주후보는 다항로지스틱C=.1,분리대조는 작은3범주LightGBM이다. 설정·후보범위·기대득실0기준은 결과 전에[계획](PLAN.md)에 고정했다. 분리트리는 모든 경주에서122축을 유지해122와 동일 성적이었다. 보수적인 해당 설정에서 대안의 기대득실이0을 넘지 못한 결과이며 트리 방식 전체가 불가능하다는 뜻은 아니다. 이번 결과를 보고 설정이나 주후보를 바꾸지 않았다.

## 2. 시간순 자료와 입력

기초능력 학습2017+,2010~2016warm-up,T−2/730일 실제슬롯을 유지했다. 연구51에서 생성·검증된2020~2023의16개과거능력모형과2024~2026의12개동결모형 예측을 재사용했다. 평가연도Y의 선택학습은2020~Y−1만 사용한다.

{table(['평가연도', '과거학습 경주', '기준·대안 사례', '학습가중치 합', '학습 마지막날'], [[int(x.year), int(x.training_races), int(x.training_pairs), f'{x.training_weight:.0f}', x.training_max] for x in training.itertuples()])}

전체10,770경주·106,731대안사례다. 한 경주의 모든 대안 가중치 합이1이 되게 해 큰두수 경주의 과대표현을 줄였다. 원입력63개는 두말의 빠른초반뒤G3F/G1F·공동관측·유지율,최근보정기록·관측·추세·편성대비기록,첫조예상·게이트·경력·간격과 그차이,편성조건,103/122평가확률·순위,종반×지원/최근기록 관계다. 결측표시·학습어휘원핫 이후127열이다. 후보 ID·마번은 입력이 아니고 연결·동점처리에만 쓴다. 기수·조교사·배당·당일실제구간은 추가하지 않았다.

전처리중앙값/평균/표준편차/범주는 선택학습기간에서만 계산했다. G1F는G3F의일부라 두초를 합산한능력점수를 만들지 않는다. 출력은 교체득/중립/실의 조건부 추정이며 말의입상확률로 표시할수없다. 최대후보 선택에는 여러추정값 중 우연히 높게 나온 값을 고르는 위험이 있다. 별도문턱최적화나 후보범위축소로 결과를 수정하지 않았다.

## 3. 축 3위 이내

같은2024-01-05~2026-09-20의4,799경주·50,754출전이다. 2026은부분연도다.

{metric_tables['axis_top3']}

이번전체말−직전선택의 연도별 순증감은+1/+22/−22다. 특히2026은122의62.66%보다60.79%로−24경주,후향95%차이구간[−3.626,−0.075]%p였다. 2025의좋아진방향만으로 전체개선이라 판단하지 않는다. 같은9월20일까지의2024/2025대조도[전체지표](outputs/metrics.csv)에 남겼다.

## 4. 복승 1조합과 축복승 3조합

복승1개는 선택축+남은122최상위말의 비순서쌍이다. 축복승3개는 선택축+남은122상위3두 각1쌍으로,삼복3개가 아니다. 축선택목표는Top3이므로Top2 동반입상을 직접최적화한 결과가 아니다.

{metric_tables['quinella_one']}

{metric_tables['axis_next3']}

축복승3개는 직전선택 대비 합산+33경주(+0.688%p),날짜95%[+0.083,+1.254]%p의 탐색적신호다. 하지만 동일학습two 대비 후보확대만의+23경주 구간은[−0.022,+0.960]%p로0을 포함한다. 복승1개는−3이며,축복승의향상을 단일복승 또는 전반적확률품질개선으로 확대하지 않는다. 후보·연도·지표의다중비교를 보정하지 않았다.

## 5. 제3의 말이 무엇을 회복하고 잃었나

{third}

전체{int(allrow.third_selected)}경주에서 제3축을 선택하고{int(allrow.third_top3)}경주에서 입상했다. 선택군51.32%를 전체축입상률61.14%와 단순비교해 대안선택이무의미하다고할수는없다. 다른난도의 선택집단이며 같은경주의 기존선택과 짝비교해야한다. 두원축이모두실패한1,711경주중202경주(11.81%)를 회복했지만,이집단은실제결과로진단한것이고 사전실패탐지정확도가 아니다.

직전선택 대비 제3축이선택된곳의 새적중211/상실197은+14다. 제3축이아닌곳의 선택변화는새적중52/상실65로−13이고 합계+1이다. 따라서202경주회복을 전체순개선으로 읽으면 안 된다. 같은이번학습two 대비는제3축선택에서208회복/198상실=+10이었다. 2026의제3축은39회복/48상실(vs51)이며후향적으로조건을잘라 예외규칙을만들지 않았다. [제3축전체사례](outputs/third_axis_cases.csv),[조건별증감](outputs/slices.csv).

## 6. 같은 경주의 차이와 불확실성

{paired}

날짜군집bootstrap2000회seed20261014의고정예측짝비교다. 날짜상관을고려하지만 동일말반복상관·모델재학습불확실성을완전히포함하지않는다. 평가기간은이미반복사용한개발자료다. 과거시점학습을지켰어도 새독립평가는아니다. 운영모델과의이번새직접비교·삼복6조합·배당ROI는계산하지않았다.

## 검증과 결정

검증완료: 전체후보누락0,동일경주가중치,기준/후보라벨·특성원천,학습전처리/연도경계,동결능력28개·새선택6개 재추론,로지스틱3개재학습,현재정답거부/변조불변,행순서불변,19,196개축/복승독립재계산,기존지표정확재현,전체짝bootstrap재현,보호원천해시불변. 최대재추론오차0이다. 최초prepare에서같은정수값의dtype차이를과도하게거부한검사를 값비교로수정했으며학습/평가전수리기록과원manifest를보존했다. 특성값·계획·설정은변경하지않았다.

제3후보가실제누락을회복할수있다는사례는있다. 그러나축입상과단일복승의안정적향상은없고2026축은악화했다. 축복승3개의후향신호만으로운영을교체하지않는다. 다음연구근거는전체출전마의교체득실을한번에최대로고르는방식의불안정성과Top3축선택/Top2동반선택목표차이다. 새규칙이나후보튜닝은이번연구에추가하지않았다.

기존부담중량·명단의사전공개시각미감사,구간지원부족·결측,미관측컨디션/전술/실제경로,COVID기간,선택모형의상관입력,반복후향·부분2026의한계를승계한다. 운영·선택22·기존미래계약·DB·제주변경없음.

재현: `run.py prepare` → `run.py learn` → `run.py analyse` → `verify.py` → `report.py` → `finalize_inventory.py`.

[입력계약](outputs/feature_contract.json) · [학습표본](outputs/training_counts.csv) · [차이구간](outputs/paired_differences.csv) · [제3축요약](outputs/third_axis_summary.csv) · [검증](outputs/verification.json) · [모형재현](outputs/model_replay.json) · [용량](outputs/artifact_inventory.json)
'''
    (e.HERE / 'README.md').write_text(body)
    pub = f'''# 기존 두 축 밖에서 새 축을 찾으면 나아질까

2026-10-14. 연구53. 독립미래검증·운영반영 아님.

무엇을 알았는가: 전체출전마 중 제3축을758경주에서 골라389입상했다. 두원축모두실패한경주202개를 회복했지만기존적중도잃어 전체축입상은직전선택61.12%→61.14%(+1)였다. 연도별+1/+22/−22로2026은나빠졌다.

기록을 어떻게 읽는가: 122축과모든대안의교체득/중립/실을과거시간외예측만으로학습하고기대득실최고말을선택했다. 선택확률은말의입상확률이아니다. 결과로제3말을찾거나 실제두축이실패한경주만고르지않았다. 동일학습의두축제한/전체확대를따로비교했다.

사례와 득실: 제3축선택의추가적중211/상실197(vs직전선택),그밖의선택변화52/65로합계+1이었다. 복승1개12.17→12.11%,축복승3개27.90→28.59%였다. 동일새학습two 대비확대만의축+10/복승1개−3/축복승3개+23은모두차이구간이0을포함한다.

어디까지 적용되는가: 기존과같은4,799경주반복후향이다. 새선택6개와동결능력28개재추론·독립티켓19,196경주검증완료.2026축악화와단일복승개선부재로채택하지않는다. 운영·선택22·기존미래계약유지.

[전체보고서](README.md) · [제3축사례](outputs/third_axis_cases.csv) · [같은경주차이](outputs/paired_differences.csv) · [검증](outputs/verification.json)
'''
    (e.HERE / 'PUBLICATION.md').write_text(pub)
    central.write_text(pub.replace('(README.md)', f'(../{e.HERE.name}/README.md)')
                      .replace('(outputs/', f'(../{e.HERE.name}/outputs/') + '\n원연구: ' + e.HERE.name + '\n')
    # Static local reader; all textual content is escaped before HTML rendering.
    (e.HERE / 'report.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>제3축 후보 연구53</title>'
        '<style>body{margin:32px auto;max-width:1250px;padding:0 20px;font:16px/1.8 system-ui;color:#172033;background:#f5f7fb}'
        'table{border-collapse:collapse;background:white;width:100%;margin:24px 0}td,th{padding:9px;border:1px solid #d9dfe8}'
        'pre{white-space:pre-wrap;background:white;padding:24px;border-radius:12px}</style>'
        '<h1>제3의 말을 포함한 축 선택</h1><p>2026-10-14 · 연구53 · 후향검증 · 운영 유지</p>'
        + m[m.period.isin(PERIODS)].to_html(index=False, escape=True, float_format=lambda x: f'{x:.4f}')
        + '<pre>' + html.escape(body) + '</pre></html>')
    marker = '<!-- open_axis_candidates_v1_20261014 -->'
    summary = ('전체출전마교체득실학습/제3축758선택389입상,두원축동시실패202회복. '
               '직전선택대비축61.12→61.14(+1),복승1개−3/축복승3개+33. '
               '동일학습two대비확대효과구간0포함,2026축악화,운영유지.')
    for name in ['README.md', 'conclusions/README.md', 'conclusions/SOURCES.md']:
        path = e.R / name
        link = f'{e.HERE.name}/README.md' if name == 'README.md' else central.name
        if marker not in path.read_text():
            with path.open('a') as handle:
                handle.write(f'\n\n{marker}\n[제3의 말을 포함한 전체 출전마 축 선택]({link}): {summary}\n')
    e.save(e.OUT / 'completion.json', dict(status='complete_verified_published_locally',
          evaluation_races=4799, new_models=6, primary_variant='gain_logit_all',
          adopted=False, production_changed=False, selected22_changed=False, future_contract_changed=False,
          database_access=False, network_access=False, jeju_access=False))
    manifest = e.R / 'conclusions/source_manifest.json'
    source = json.loads(manifest.read_text())
    own = [p for p in e.HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts
           and 'publication_before' not in p.parts and p.name not in ['publication_before.json', 'artifact_inventory.json']]
    for path in own + [central] + [e.R / n for n in ['README.md', 'conclusions/README.md', 'conclusions/SOURCES.md']]:
        key = str(path.relative_to(e.ROOT))
        source['sources'] = [r for r in source['sources'] if r['path'] != key]
        source['sources'].append(dict(path=key, sha256=e.sha(path), bytes=path.stat().st_size))
    e.save(manifest, source)
    # Check local links except the inventory, created by the subsequent finalizer.
    for path in [e.HERE / 'README.md', e.HERE / 'PUBLICATION.md', central]:
        for link in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if not link.startswith(('https:', 'http:', '#')) and not link.endswith('artifact_inventory.json'):
                assert (path.parent / link).exists(), (path, link)
    e.check()
    print('Research53 report and publication sources saved; operating model unchanged')


if __name__ == '__main__':
    main()

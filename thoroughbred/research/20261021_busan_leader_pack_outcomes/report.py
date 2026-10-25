"""Readable tables, figures and repository research publication summary."""
from pathlib import Path
import json
import os
os.environ['MPLCONFIGDIR'] = '/private/tmp/busan_leader_pack_mpl_20261021'
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import analyze as a


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |',
                      '| '+' | '.join(['---']*len(headers))+' |'] +
                     ['| '+' | '.join(map(str, row))+' |' for row in rows])


def pct(v):
    return '—' if pd.isna(v) else f'{v:.2f}%'


def main():
    assert json.loads((a.OUT/'verification.json').read_text())['status'] == 'verified'
    exact = pd.read_csv(a.OUT/'exact_rates.csv', dtype={'period':str,'distance':str,'leader_count':str})
    compact = pd.read_csv(a.OUT/'compact_rates.csv', dtype={'period':str,'distance':str,'leader_count':str})
    summary = json.loads((a.OUT/'summary.json').read_text())
    main = exact[exact.scope.eq('normal_complete') & exact.period.eq('all')]
    cmain = compact[compact.scope.eq('normal_complete') & compact.period.eq('all')]
    allrows = main[main.distance.eq('all')]
    full = table(['선두 묶음 두수','경주','말 출전','우승마/출전 · 우승률','입상마/출전 · 입상률',
                  '그룹 우승','입상 0두','정확 1두 입상','2두 이상 입상','표본'], [
        [r.leader_count, f'{r.races:,}', f'{r.leader_starts:,}',
         f'{r.winner_horses:,}/{r.leader_starts:,} · {pct(r.individual_win_pct)}',
         f'{r.top3_horses:,}/{r.leader_starts:,} · {pct(r.individual_top3_pct)}',
         pct(r.group_win_pct),pct(r.exact0_top3_pct),pct(r.exact1_top3_pct),
         pct(r.two_plus_top3_pct),r.sample_status] for r in allrows.itertuples()])
    distrows = []
    for dist in a.DISTANCES:
        g = cmain[cmain.distance.eq(str(dist))].set_index('leader_count')
        row = [f'{dist}m']
        for n in ['1','2','3+']:
            z = g.loc[n]
            row.append(f'{pct(z.individual_win_pct)} / {pct(z.individual_top3_pct)} ({z.races:,}경주)')
        distrows.append(row)
    distances = table(['거리','선두 1두: 우승 / 입상','선두 2두: 말당 우승 / 입상',
                       '선두 3두 이상: 말당 우승 / 입상'], distrows)
    allrates = compact[compact.scope.eq('normal_complete') & compact.distance.eq('all')]
    recent = table(['기간','첫 묶음 두수','경주','우승률','입상률','2두 이상 입상'], [
        [r.period,r.leader_count,r.races,pct(r.individual_win_pct),pct(r.individual_top3_pct),
         pct(r.two_plus_top3_pct)] for r in allrates[allrates.period.ne('all')].itertuples()])
    sens = compact[compact.period.eq('all') & compact.distance.eq('all')]
    sensitivity = table(['표본','두수','경주','우승률','입상률'], [
        [dict(normal_complete='정상완주 완전편성',all_known_outcomes='91/92 비입상 포함',
              normal_no_ties='동일착순 경주 제외')[r.scope],r.leader_count,r.races,
         pct(r.individual_win_pct),pct(r.individual_top3_pct)] for r in sens.itertuples()])
    cis = table(['두수','입상률','날짜 군집 95%','말 군집 95%'], [
        [r.leader_count,pct(r.individual_top3_pct),
         f'{r.top3_date_lower95:.2f}~{r.top3_date_upper95:.2f}%',
         f'{r.top3_horse_id_lower95:.2f}~{r.top3_horse_id_upper95:.2f}%']
        for r in cmain[cmain.distance.eq('all')].itertuples()])
    exact_sections = []
    for dist in a.DISTANCES:
        g = main[main.distance.eq(str(dist))]
        exact_sections += [f'## {dist}m: 정확한 묶음 두수', '', table(
            ['두수','경주','말 출전','우승률','입상률','그룹 우승','정확1두','2두 이상','표본'],
            [[r.leader_count,r.races,r.leader_starts,pct(r.individual_win_pct),
              pct(r.individual_top3_pct),pct(r.group_win_pct),pct(r.exact1_top3_pct),
              pct(r.two_plus_top3_pct),r.sample_status] for r in g.itertuples()]), '']
    twos = cmain[cmain.distance.eq('all') & cmain.leader_count.eq('2')].iloc[0]
    pair = main[main.leader_count.eq('2') & main.distance.isin(['1000','1200','1300','1400','1600','1800'])]
    pair_table = table(['거리','선두2두 경주','2두 모두 입상 경주','2두 모두 입상률'], [
        [r.distance+'m',r.races,r.exact2_top3_races,pct(r.two_plus_top3_pct)] for r in pair.itertuples()])

    colors = ['#227a97','#cb783e','#6e699a']
    fig, axes = plt.subplots(1,2,figsize=(11,4.5))
    plot_dist = [1000,1200,1300,1400,1600,1800]
    for ax, metric, title in zip(axes, ['individual_win_pct','individual_top3_pct'],
                                 ['Win rate per leader start','Top3 rate per leader start']):
        for count,color in zip(['1','2','3+'],colors):
            g = cmain[cmain.leader_count.eq(count)].set_index('distance').loc[list(map(str,plot_dist))]
            ax.plot(range(len(g)),g[metric], 'o-',label=f'Pack {count}',color=color)
        ax.set_xticks(range(len(plot_dist)),plot_dist)
        ax.set_xlabel('Distance (m)');ax.set_ylabel('Observed rate (%)')
        ax.set_title(title);ax.set_ylim(0,90);ax.grid(axis='y',alpha=.15);ax.legend()
    fig.suptitle('Busan actual S1F first pack | 2018 to Sep 18, 2026 | normal-completion races')
    fig.tight_layout();fig.savefig(a.OUT/'distance_pack_rates.png',dpi=165);plt.close(fig)
    fig,ax = plt.subplots(figsize=(10,4.8))
    z=allrows.iloc[:7];xx=np.arange(len(z));width=.34
    ax.bar(xx-width/2,z.individual_win_pct,width,color=colors[0],label='Win per start')
    ax.bar(xx+width/2,z.individual_top3_pct,width,color=colors[1],label='Top3 per start')
    ax.set_xticks(xx,[f'{r.leader_count}\n{r.races:,} races' for r in z.itertuples()])
    ax.set_xlabel('Actual first-pack size at S1F');ax.set_ylabel('Observed rate (%)')
    ax.set_title('Busan: individual outcome rates by actual first-pack size')
    ax.set_ylim(0,75);ax.grid(axis='y',alpha=.15);ax.legend();fig.tight_layout()
    fig.savefig(a.OUT/'pack_size_rates.png',dpi=165);plt.close(fig)

    report = f'''# 부산: S1F 선두 묶음 두수·거리별 우승과 입상

2026-10-21 · 연구57I · 실제 통과조의 사후 관측 연구 · 운영 반영 없음.

**제주에서 쓴 실제 첫 통과조 기준을 부산에 적용했다. 정상완주 완전편성 5,891경주에서 선두1두 말의 우승률은 34.26%·입상률 63.07%, 선두2두일 때 각 말당 27.37%·56.57%, 선두3두 이상에서는 16.72%·41.13%였다. 거리별로 단독 선두의 성과가 다르고, 선두2두가 둘 다 입상할 비율도 1200m 32.74%에서 1800m 19.83%로 달랐다.**

## 무엇을 세었나

제주 [선두 묶음 두수 연구](../../../jeju/research/20261020_leader_pack_size_outcomes_v1/README.md)의 정의를 옮겼다. 실제 S1F 통과조가 `(2,5,8),1,...`이면 첫 묶음은2·5·8번 세 말이다. 괄호 내부를 앞뒤 순위로 읽지 않고, `2-(5,8),...`이면 첫 묶음은2번 한 말이다. 부산 S1F는 출발 후200m 지점이다. 실제 경합·빠른 초반·무압박 선행·경주 내내 선행은 이 표기만으로 확정하지 않는다.

이전에 검증한 부산 연구 출전명단 6,053경주·66,240출전, 2018-01-05~2026-09-18을 참조했다. S1F 전두수 명단이 맞는 5,991경주 중 모든 말이 정상 착순1~30인 5,891경주가 주분석이다. 첫 묶음 말 출전은16,799회다. 기존 원천 기간이2018년부터여서 제주 연구의2017년 시작과 다르며, 2017년이나 최신10월 자료를 새로 수집하지 않았다. 이 연구 모집단을 부산의 모든 과거 경주를 빠짐없이 포함한 목록이라고 주장하지 않는다. 1500m 무표본·1900m 과거표본도 남겼다.

말당 우승률=첫 묶음의 착순1 말 수/첫 묶음 말 출전, 말당 입상률=착순1~3 말 수/첫 묶음 말 출전이다. 그룹 우승률은 첫 묶음에서 우승마가 한 두 이상 나온 경주/경주다. `정확1두`와 `최소1두`는 다르며, 입상0두·정확1두·2두 이상은 서로 배타적이고 합100%다. 입상은 승식 지급규칙과 구분한 원문 착순1~3이다.

## 전체 두수별 결과

{full}

첫 묶음에 여러 말이 있을 때 개인 비율은 낮아져도 그룹에서 우승마·복수 입상마가 나오는 빈도는 높아질 수 있다. 더 큰 후보 집합을 고르는 데 따른 분모 구조도 함께 작용하므로, 이 표만으로 경합이 원인이라고 판단하지 않는다. 선두8~10두와 일부 거리 조합은 특히 소표본이다.

![전체 두수별 말당 우승·입상](outputs/pack_size_rates.png)

## 거리별 핵심 비교

아래 셀은 `말당 우승률 / 입상률 (경주 수)`다. 3두 이상은 정확3두의 비율이 아니라, 그 안의 모든 실제 첫 묶음 말 출전을 합친 가중 비율이다.

{distances}

1200m 단독 선두는 우승44.67%·입상72.13%, 1600m는25.73%·53.80%, 1800m는25.20%·51.97%였다. 거리별 말의 능력·등급·두수·게이트·전략 구성이 다르므로 거리 자체의 인과효과는 아니다. 1400m의 말당 우승률은 단독25.90%와2두26.61%로 단독이 더 높지 않았다. ‘단독이면 모든 거리에서 더 좋다’는 규칙으로 바꾸지 않는다.

1000m 단독은87경주(우승55.17%·입상81.61%)로 기술표본 기준100말출전에 못 미친다. 2000m 단독16경주,1900m 단독1경주,2200m 단독3경주를 일반 확률로 쓰지 않는다. 1500m는0관측이며 비율은0%가 아닌 미제공이다. 표본 기준은100말출전·30경주·20경주일을 모두 충족해야 한다.

![거리와 선두 묶음별 관측 비율](outputs/distance_pack_rates.png)

## 선두2두의 동반 입상

전체1,659경주 중 두 말 모두 입상한 것은 {int(twos.exact2_top3_races):,}경주({twos.two_plus_top3_pct:.2f}%)다. 정확1두 입상은 {int(twos.exact1_top3_races):,}경주({twos.exact1_top3_pct:.2f}%), 전부 비입상은 {int(twos.exact0_top3_races):,}경주({twos.exact0_top3_pct:.2f}%)였다. 각 말 입상률56.57%와 두 말 모두 입상률29.48%는 다른 사건이다.

{pair_table}

이것은 복연 후보 관계를 연구할 기초 관측값이지, 경주 전에 두 선두말을 이미 정확히 알 수 있다고 가정한 사전 조합 적중률은 아니다.

## 연도별·최근 기간

{recent}

2026년은9월18일까지다. 단독76경주의 우승31.58%·입상61.84%는 소표본 기준에 해당하며 거리별로 나누면 더 작다. 과거에 반복 분석한 후향 자료여서 새로운 독립 검증으로 부르지 않는다. 모든 최근 기간×거리×정확 두수는 [전체표](outputs/exact_rates.csv)에 보존했다.

## 불확실성·선택 표본·동일착순

{cis}

날짜/말 군집 t구간은 관측 비율의 설명적 불확실성이다. 능력을 맞춘 단독 선행 효과나 두 그룹 간 차이의 검정 구간이 아니다. 소표본의0%·100%에서 단순 군집 구간이0폭이 되더라도 확실한 미래 확률로 해석하지 않는다. 같은 말·같은 날짜의 반복 관측을 독립 말처럼 취급하지 않도록 군집을 나눴다.

{sensitivity}

비정상 착순91/92를 비우승·비입상으로 포함한 유효 통과조5,991경주에서도 전체 방향이 비슷했다. 그래도 통과조를 기록하지 못한62경주는 빠지고, 기존 연구에서 선정한 시행키의 범위 제약이 남는다. 기존 성별·기록 연구의 `selected` 플래그를 이번 성과 분모로 사용하지 않았다.

정상완주 주분석에는 동일 최종착순이 표시된100경주가 있다. 원문은 개별 순서로 나누지 않았다. 일부 경주는 전체 착순1~3 말이4두이고, 첫 묶음에 원문 우승마2두가 포함된 경주도2개였다. 따라서 제주 코드의 `승자 항상1두`, `입상마 최대3두`를 그대로 적용하지 않았다. 실제 첫 묶음의 입상4두 관측은0개지만 저장 열은 보존했다. 그룹 우승은 경주당 한 번, 말당 우승은 실제 원문1착마를 각각 센다. 동착 제외 민감도에서도 큰 방향은 비슷했다.

## 모델에 연결할 때

현재 첫 묶음은 해당 경주가 진행된 뒤 관측되는 값이다. 같은 경주의 사전 모델에 실제 묶음 두수를 넣으면 정보가 누수된다. 다음 연구 후보는 과거 자료만으로 이번 첫 묶음 소속·크기의 분포를 예측하고, 말의 기록 능력·거리와 함께 조건부 우승/입상 모형에 입력하는 것이다. 이번 표를 고정 확률·가산점으로 적용하지 않았으며 새 학습·운영 모델 교체는 없다.

## 검증과 원장

원문 전두수·첫 묶음을 별도 문자 파서로 확인했고, 연도별 원 API66,240출전의 말ID·날짜·경주번호·마번·착순을 대조했다. 별도 메모리SQL로 정확/요약2,145셀을 검산했고 날짜/말 군집 구간1,652쌍을 재계산했다. 원천18파일 SHA·바이트와 운영 등록부는 유지했다. DB접근·네트워크·새 학습·운영 변경은 없다.

[사전계획](PLAN.md) · [검증](outputs/verification.json) · [거리·정확두수 전체표](outputs/exact_rates.csv) · [거리·1/2/3+ 요약](outputs/compact_rates.csv) · [경주별 명단·원문·입상수](outputs/race_outcomes.csv) · [첫 묶음 말별 원장](outputs/leader_starts.parquet) · [경주 포함·보류](outputs/race_audit.csv) · [출전두수별 보충](outputs/field_size_rates.csv) · [원천해시](outputs/input_manifest.json) · [용량](outputs/artifact_inventory.json)

''' + '\n'.join(exact_sections)
    (a.HERE/'README.md').write_text(report)
    publication = '''# 부산 선두 묶음 두수와 거리별 우승·입상

2026-10-21 · 연구57I · 관측 연구 · 운영 미반영.

제주에서 사용한 실제 S1F 첫 통과조 기준을 부산에 적용했다. 정상완주 완전편성5,891경주에서 첫 묶음1두 말의 우승34.26%·입상63.07%,2두일 때 각 말당27.37%·56.57%,3두 이상은16.72%·41.13%였다. 첫 묶음2두가 함께 입상한 비율은29.48%로 개인 입상률과 구분한다.

1200m 단독 선두는 우승44.67%·입상72.13%,1800m는25.20%·51.97%였다.1400m는 단독 우승25.90%가2두의 말당26.61%보다 높지 않았다. 거리별 능력·등급·전략 구성 차이가 남아 단독 선행이나 거리의 인과효과로 해석하지 않는다.

원천은2018-01-05~2026-09-18 기존 검증 출전명단이다.1000m 단독87경주,2000m 단독16경주 및1900/2200m는 소표본이고1500m는 무표본이다. 2026 단독76경주도 소표본이다. 비정상 완주 포함·동일착순 제외 민감도에서도 전체 방향은 비슷했다.

실제 첫 묶음은 사후 정보다. 미래 예측에 쓰려면 과거 자료만으로 선두 묶음 소속·두수를 먼저 예측하고 능력과 함께 검증해야 한다. 표를 고정 확률로 가산하거나 운영 모델에 넣지 않았다. 원 API66,240출전·원문 통과조·2,145집계셀·군집구간1,652쌍을 검산했다.

[전체 결과](README.md) · [거리·두수별 전체표](outputs/exact_rates.csv) · [경주별 원장](outputs/race_outcomes.csv) · [검증](outputs/verification.json)
'''
    (a.HERE/'PUBLICATION.md').write_text(publication)
    central = a.R/'conclusions/57I_BUSAN_LEADER_PACK_OUTCOMES.md'
    central.write_text(publication.replace('(README.md)',f'(../{a.HERE.name}/README.md)')
                       .replace('(outputs/',f'(../{a.HERE.name}/outputs/'))
    marker = '<!-- busan_leader_pack_outcomes_20261021 -->'
    for name in ['README.md','conclusions/README.md','conclusions/SOURCES.md']:
        path = a.R/name
        if marker not in path.read_text():
            link = a.HERE.name+'/README.md' if name == 'README.md' else central.name
            with path.open('a') as f:
                f.write(f'\n\n{marker}\n[연구57I 부산 선두 묶음 두수·거리별 성과]({link}): '
                        '5,891경주. 단독 우승34.26%·입상63.07%, 2두 각 말당27.37%·56.57%. '
                        '선두2두 동반입상29.48%. 실제 S1F 사후 관측·동일착순/정상완주 민감도·운영 미반영.\n')
    a.save('sources.json', dict(source_end='2026-09-18', new_external_data=False,
        method='Jeju actual first S1F pack size outcomes transferred to frozen Busan roster',
        source_roster='2018-01-05 through 2026-09-18; previously verified research race keys',
        source_manifest='input_manifest.json', new_fits=0, database_access=False,
        observed_not_predicted_pack=True, operating_changed=False))
    print('Report, publication summary, central57I, tables and figures saved.')


if __name__ == '__main__':
    main()

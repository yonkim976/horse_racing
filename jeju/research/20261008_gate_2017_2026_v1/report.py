"""Validate pooled results and produce a standalone Korean report and figure."""
from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / '20261008_gate_all_distances_v1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_csv(name, frame):
    with (HERE / name).open('x', encoding='utf-8') as f:
        frame.to_csv(f, index=False)


def main():
    a = pd.read_csv(HERE / 'lateral_contrasts.csv')
    n = pd.read_csv(HERE / 'number_effects.csv')
    support = pd.read_csv(HERE / 'support.csv')
    fields = pd.read_csv(HERE / 'all_field_support.csv')
    raw = pd.read_csv(HERE / 'raw_lateral_rates.csv')
    old = pd.read_csv(PREVIOUS / 'lateral_contrasts.csv')
    keys = ['period', 'distance', 'target', 'contrast']
    matched = a[a.period.isin(['2019_2025', '2026_partial'])].merge(old, on=keys, suffixes=('_new', '_old'), validate='one_to_one')
    assert len(matched) == 8 * 6 * 2 * 2
    for col in ['effect', 'ci_lo', 'ci_hi', 'horse_ci_lo', 'horse_ci_hi', 'q_BH']:
        assert np.allclose(matched[col + '_new'], matched[col + '_old'], atol=1e-10, equal_nan=True)
    full = support[support.period == '2017_2026'].set_index('distance')
    assert full.ten_runner_races.to_dict() == {800:1057, 900:690, 1000:1067, 1110:700, 1200:304, 1300:47, 1400:63, 1610:2}
    for dist, r in full.iterrows():
        f = fields[fields.race_distance_m == dist]
        assert r.ten_runner_races == f[f.field_n == 10].races.sum()
        assert r.all_field_races == f.races.sum()
        subtotal = support[(support.distance == dist) & support.period.isin(['2017_2018','2019_2025','2026_partial'])].ten_runner_races.sum()
        assert subtotal == r.ten_runner_races
    assert 400 not in a.distance.unique()
    assert a[(a.distance == 1610)].effect.isna().all()
    main = a[(a.period == '2017_2026') & (a.target == 'top3') & (a.contrast == 'inner_minus_outer')].copy()
    oldmain = old[(old.period == '2019_2025') & (old.target == 'top3') & (old.contrast == 'inner_minus_outer')]
    compare = main[['distance','ten_runner_races','effect','ci_lo','ci_hi','q_BH','horse_ci_lo','horse_ci_hi','first_date','last_date','status']].merge(oldmain[['distance','ten_runner_races','effect']], on='distance', suffixes=('_2017_2026','_2019_2025'))
    save_csv('pooled_vs_previous.csv', compare)
    counts = fields.assign(ten_runner_races=np.where(fields.field_n == 10, fields.races, 0)).groupby(['year','race_distance_m'])[['races','ten_runner_races']].sum().reset_index()
    save_csv('annual_support.csv', counts)
    times = a[(a.period == '2017_2026') & (a.target == 'time') & (a.contrast == 'inner_minus_outer')]
    group = a[(a.period == '2017_2026') & (a.target == 'top3') & a.contrast.isin(['inner_minus_middle','outer_minus_middle','inner_minus_outer'])]
    numbers = n[(n.period == '2017_2026') & (n.target == 'top3')].pivot(index='number', columns='distance', values='effect')
    periods = a[(a.target == 'top3') & (a.contrast == 'inner_minus_outer')].pivot(index='distance', columns='period', values='effect').reindex(columns=['2017_2018','2019_2025','2024_2026','2026_partial','2017_2026'])
    rawtable = raw[raw.period == '2017_2026'].pivot(index='distance', columns='lateral', values='top3_rate') * 100
    table = main[['distance','ten_runner_races','days','effect','ci_lo','ci_hi','q_BH','horse_ci_lo','horse_ci_hi','status']].rename(columns={'distance':'거리(m)','ten_runner_races':'10두 경주','days':'경주일수','effect':'내−외 Top3(%p)','ci_lo':'날짜 95% 하한','ci_hi':'날짜 95% 상한','q_BH':'BH q','horse_ci_lo':'말 95% 하한','horse_ci_hi':'말 95% 상한','status':'표본 상태'})
    def html(frame):
        return frame.to_html(index=False, escape=True, na_rep='미추정', float_format=lambda x:f'{x:.3f}')
    sections = [
        ('전체 기간 내외측 결과', html(table)),
        ('기존 집계와 비교', html(compare)),
        ('실제 표본 시작·종료일과 출전두수 제한 전 표본', html(support[support.period=='2017_2026'])),
        ('내측·중간·외측 대조', html(group[['distance','contrast','effect','ci_lo','ci_hi','q_BH']])),
        ('전체시간: 음수면 내측이 빠른 방향', html(times[['distance','effect','ci_lo','ci_hi','q_BH']])),
        ('기간별 Top3 차이 비교', html(periods.reset_index())),
        ('번호별 Top3 효과: 10번호 평균 대비 %p', html(numbers.reset_index())),
        ('원시 Top3 진입률(%)', html(rawtable.reset_index())),
        ('연도별 정상 결과 표본', html(counts)),
    ]
    notes = '''<p>2017-01-01~2026-09-19 보유 자료를 합쳐 재계산했다. 2026년은 부분연도이며 모든 연도를 경주 수에 따라 합산했다. 400m는 사용자 지시에 따라 현재 대상에서 제외하고 원천은 보존했다.</p>
<p>정상 완전순위·정확히 10두·번호 1~10. 내측 1~3, 중간 4~7, 외측 8~10으로 정의했다. 각 거리의 동일거리 최근 5회 평균·직전 기록·관측 출전수·간격·사건 당시 원문 나이·부담중량·성별을 기존과 동일하게 조정하고 경주 내 중심화를 적용했다. 현행 2026 고정 나이를 과거 당시 나이로 쓰지 않았다. 과거 이력은 공식 말 ID·정확 거리·T−2 기준이며 2017년 이전 이력도 기존 계약대로 워밍업에 남는다.</p>
<p>시간과 Top3 선형확률 회귀를 별도로 계산했다. 날짜 군집 95% 구간은 점별 근사 구간이고 반복말 군집 구간도 제시했다. 기간마다 추정 가능한 모든 거리×3대조×2목표를 하나의 BH 다중비교 묶음으로 보정했다. 번호별 검정은 별도 묶음이다. 최소 30경주·20일 미달은 미추정, 100경주·40일·2개년 미달은 제한표본으로 표시했다. 이 기준이 통계적 충분성을 보장하지 않는다.</p>
<p>2017~2018과 2019 이후의 등급 명칭을 같은 등급으로 합치지 않았다. 같은 경주에 공통인 조건은 경주 고정효과로 흡수되지만, 시대별 번호 효과가 같다는 보장은 없다. 전체기간 평균은 현재 효과를 대신하지 않으므로 최근 2024~2026 및 2026 부분 결과도 함께 보존했다. 겹치는 기간을 독립 재현으로 부르지 않는다. 1300·1400·1610m는 각각 보유 표본이 2024·2020·2025년부터 시작하므로 2017년 경주를 새로 포함한 것이 아니다.</p>
<p>관측된 번호와 성적의 연관성이다. 물리적 게이트 대응과 실제 주행 내외측 위치는 미확정이며 인과효과·향후 예측 개선·고정 보정값을 입증하지 않는다. 사후 정상완주 선택, 미측정 능력, 공개시점 가정, 고정 Ridge 사양의 한계가 남는다. 10두 이외의 경주에 그대로 적용하지 않는다. DB·운영 모델·이전 보고서는 수정하지 않았다.</p>'''
    doc = '<!doctype html><html lang="ko"><meta charset="utf-8"><title>제주 2017~2026 거리별 번호 유불리</title><style>body{font:16px/1.65 system-ui;max-width:1300px;margin:40px auto;padding:0 24px;color:#172331}table{border-collapse:collapse;font-size:13px;white-space:nowrap}th,td{padding:6px 10px;border-bottom:1px solid #ddd;text-align:right}th{background:#eef3f7}section{overflow:auto;margin:30px 0}h1,h2{line-height:1.3}img{max-width:100%}</style><h1>제주 2017~2026 거리별 번호 유불리</h1>' + notes + '<img src="lateral_effects.png" alt="거리별 내측과 외측 Top3 차이 및 95% 구간">'
    doc += ''.join('<section><h2>'+title+'</h2>'+body+'</section>' for title,body in sections) + '</html>'
    with (HERE/'report.html').open('x',encoding='utf-8') as f:f.write(doc)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10,6), layout='constrained')
    for j, r in main.reset_index(drop=True).iterrows():
        if pd.notna(r.effect):
            ax.errorbar(r.effect, j, xerr=np.array([[r.effect-r.ci_lo],[r.ci_hi-r.effect]]), fmt='o', capsize=4, color='#15699c' if r.status=='basic_support' else '#929292')
            ax.text(29,j,f'n={r.ten_runner_races}',va='center',fontsize=10)
        else:ax.text(0,j,f'Not estimated (n={r.ten_runner_races})',va='center',color='gray')
    ax.set_yticks(range(len(main)), [f'{d}m' for d in main.distance]);ax.set_ylim(len(main)-0.5,-0.5);ax.axvline(0,color='black',ls='--',lw=1)
    ax.set_xlim(-7,37);ax.grid(axis='x',alpha=.15)
    ax.set_xlabel('Inner (1-3) minus outer (8-10) Top3: percentage points')
    ax.set_title('Jeju 2017 - 2026 Sep 19 | 10-runner races\nAdjusted observational associations; pointwise 95% date-cluster intervals\nGray: limited sample')
    fig.savefig(HERE/'lateral_effects.png',dpi=150);fig.savefig(HERE/'lateral_effects.svg');plt.close(fig)
    check = {'status':'passed','previous_main_and_2026_reproduced':True,'full_counts_match_annual_and_nonoverlapping_periods':True,'excluded_400':True,'1610_not_estimated':True,'report_code_sha256':sha(Path(__file__))}
    with (HERE/'report_verification.json').open('x') as f:json.dump(check,f,indent=2)
    inventory = [{'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(HERE.iterdir()) if p.is_file() and p.suffix!='.log']
    with (HERE/'artifact_manifest.json').open('x') as f:json.dump(inventory,f,indent=2)
    assert all(sha(HERE/r['path'])==r['sha256'] for r in inventory)
    print(table.to_string(index=False))
    print(times[['distance','effect','ci_lo','ci_hi','q_BH']].to_string(index=False))
    print('Report complete:', HERE/'report.html')


if __name__=='__main__':
    main()

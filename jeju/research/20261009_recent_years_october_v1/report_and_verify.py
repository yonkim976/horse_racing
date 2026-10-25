from pathlib import Path
import hashlib
import json
import os
import sqlite3

import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent
O=H/'run02'
ROOT=H.parents[2]
SOURCE=H.parent/'20261009_time_benchmarks_outliers_v1/reviewed_run02/analysis_rows.csv'
KEYS=['race_distance_m','rank_class_raw','track_state']


def table(frame,columns,labels):
    lines=['| '+' | '.join(labels)+' |','| '+' | '.join(['---']*len(labels))+' |']
    for row in frame[columns].itertuples(index=False,name=None):
        cells=[]
        for col,value in zip(columns,row):
            if pd.isna(value):cells.append('—')
            elif col in ['race_distance_m','year','n','n_left','n_right','common_cells']:cells.append(str(int(value)))
            elif isinstance(value,(float,int)):cells.append(f'{value:+.2f}' if 'difference' in col or col.startswith('delta_') else f'{value:.2f}')
            else:cells.append(str(value))
        lines.append('| '+' | '.join(cells)+' |')
    return '\n'.join(lines)


def main():
    raw=pd.read_csv(SOURCE,dtype={'horse_id':str})
    d=raw[raw.year.ge(2019)].copy()
    d['month']=d.race_date.str[5:7].astype(int)
    d['month_day']=d.race_date.str[5:10]
    c=pd.concat([pd.read_csv(O/'standardized_comparisons.csv'),pd.read_csv(O/'calendar_sensitivity.csv')],ignore_index=True)
    cells=pd.concat([pd.read_csv(O/'common_cell_contributions.csv'),pd.read_csv(O/'calendar_sensitivity_contributions.csv')],ignore_index=True)
    manifest=json.loads((O/'source_manifest.json').read_text())
    with SOURCE.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==manifest['source_sha256']
    assert d.api_record_id.is_unique and set(d.api_record_id)==set(manifest['source_api_record_ids'])
    assert not (d.year.eq(2026)&d.month.ge(10)).any()
    # A separate SQLite aggregation checks the saved monthly raw means and counts.
    con=sqlite3.connect(':memory:')
    d.to_sql('observations',con,index=False)
    sql=pd.read_sql_query('''SELECT year,month,race_distance_m,rank_class_raw,track_state,
          COUNT(*) n,AVG(finish_time_seconds) mean_s FROM observations
          GROUP BY year,month,race_distance_m,rank_class_raw,track_state''',con)
    monthly=pd.read_csv(O/'year_month_cells.csv')
    check=monthly[monthly.time_field.eq('finish_time_seconds')].merge(sql,on=['year','month']+KEYS,validate='one_to_one',suffixes=('_saved','_sql'))
    assert len(check)==len(sql)
    assert np.allclose(check.n_saved,check.n_sql)
    assert np.allclose(check.mean_s_saved,check.mean_s_sql,atol=1e-7,rtol=0)
    groups={key:g for key,g in cells.groupby(['comparison','race_distance_m','time_field'])}
    for row in c[c.supported].itertuples():
        g=groups[(row.comparison,row.race_distance_m,row.time_field)]
        assert len(g)==row.common_cells
        assert np.allclose(g.weight,(g.n_left+g.n_right)/(g.n_left+g.n_right).sum(),atol=2e-9)
        # Recompute with counts rather than saved rounded weights.
        weights=(g.n_left+g.n_right)/(g.n_left+g.n_right).sum()
        point=np.sum(weights*(g.mean_s_right-g.mean_s_left))
        assert abs(point-row.difference_right_minus_left_s)<1e-7
        assert int(g.n_left.sum())==row.n_left and int(g.n_right.sum())==row.n_right
        assert g[['n_left','n_right']].ge(30).all().all()
        assert g[['races_left','races_right','dates_left','dates_right']].ge(5).all().all()
    # Check individual saved common-cell means against source rows for the primary
    # 1000m seasonal and overlapping recent/full comparisons.
    for name in ['recent3_vs_full','pooled_Q4_vs_JanSep']:
        g=groups[(name,1000,'finish_time_seconds')]
        for row in g.itertuples():
            z=d[d.race_distance_m.eq(1000)&d.rank_class_raw.eq(row.rank_class_raw)&d.track_state.eq(row.track_state)]
            if name=='recent3_vs_full':left=z;right=z[z.year.ge(2024)]
            else:
                z=z[z.year.eq(row.year)];left=z[z.month.le(9)];right=z[z.month.ge(10)]
            assert len(left)==row.n_left and len(right)==row.n_right
            assert abs(left.finish_time_seconds.mean()-row.mean_s_left)<1e-7
            assert abs(right.finish_time_seconds.mean()-row.mean_s_right)<1e-7
    verification={'status':'passed','monthly_SQL_group_checks':len(check),
                  'weighted_contrasts_recomputed':int(c.supported.sum()),
                  '1000m_source_cell_comparisons_verified':True,'overlap_preserved_in_primary_influence_calculation':True,
                  'source_hash_unchanged':True,'2026_Q4_absent':True}
    with (O/'verification.json').open('x') as stream:json.dump(verification,stream,indent=2)
    finish=c[c.time_field.eq('finish_time_seconds')]
    p=finish[finish.comparison.eq('recent3_vs_full')&finish.race_distance_m.le(1200)].copy()
    q=finish[finish.comparison.eq('pooled_Q4_vs_JanSep')&finish.race_distance_m.le(1200)]
    cal=finish[finish.comparison.eq('recent3_vs_full_same_Jan1_Sep19_month_matched')&finish.race_distance_m.le(1200)]
    overview=p[['race_distance_m','difference_right_minus_left_s']].rename(columns={'difference_right_minus_left_s':'delta_recent'})
    overview=overview.merge(cal[['race_distance_m','difference_right_minus_left_s']].rename(columns={'difference_right_minus_left_s':'delta_same_calendar'}),on='race_distance_m')
    overview=overview.merge(q[['race_distance_m','difference_right_minus_left_s']].rename(columns={'difference_right_minus_left_s':'delta_q4'}),on='race_distance_m')
    overview.to_csv(O/'report_overview.csv',index=False)
    overview_table=table(overview,['race_distance_m','delta_recent','delta_same_calendar','delta_q4'],['거리 m','최근3년−장기 초','달력·월 구성 맞춘 차이 초','10~12월−1~9월 초'])
    primary_table=table(p,['race_distance_m','n_left','n_right','common_cells','difference_right_minus_left_s','ci95_lo_s','ci95_hi_s'],['거리 m','장기 출전','최근 출전','공통 조건','최근−장기 초','95% 하한','95% 상한'])
    q_table=table(q,['race_distance_m','n_left','n_right','common_cells','difference_right_minus_left_s','ci95_lo_s','ci95_hi_s'],['거리 m','1~9월 출전','10~12월 출전','공통 연도 조건','Q4−1~9월 초','95% 하한','95% 상한'])
    annual=finish[finish.race_distance_m.eq(1000)&finish.comparison.str.match(r'^20\d\d_Q4_vs_JanSep$')].copy()
    annual['year']=annual.comparison.str[:4].astype(int)
    annual_table=table(annual,['year','n_left','n_right','difference_right_minus_left_s','ci95_lo_s','ci95_hi_s'],['연도','1~9월 출전','10~12월 출전','Q4−1~9월 초','95% 하한','95% 상한'])
    sections=c[c.race_distance_m.eq(1000)&c.comparison.eq('recent3_vs_full')&c.supported][['time_field','difference_right_minus_left_s']].rename(columns={'difference_right_minus_left_s':'delta_recent'})
    other=c[c.race_distance_m.eq(1000)&c.comparison.eq('pooled_Q4_vs_JanSep')&c.supported][['time_field','difference_right_minus_left_s']].rename(columns={'difference_right_minus_left_s':'delta_q4'})
    sections=sections.merge(other,on='time_field')
    section_table=table(sections,['time_field','delta_recent','delta_q4'],['시간 필드','최근3년−장기 초','10~12월−1~9월 초'])
    # Publication figure: contrasts keep exact distances separate.
    os.environ.setdefault('MPLCONFIGDIR','/private/tmp/jeju_october_matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(1,2,figsize=(10,4.6),sharey=True)
    for ax,frame,title,color in [(axs[0],p,'2024-2026 vs 2019-2026','#2563eb'),(axs[1],q,'Oct-Dec vs Jan-Sep (2019-2025)','#b45309')]:
        ys=np.arange(len(frame));points=frame.difference_right_minus_left_s.to_numpy()
        errs=np.stack([points-frame.ci95_lo_s.to_numpy(),frame.ci95_hi_s.to_numpy()-points])
        ax.errorbar(points,ys,xerr=errs,fmt='o',capsize=4,color=color)
        ax.axvline(0,color='#64748b',lw=1);ax.set_title(title,fontsize=11)
        ax.set_yticks(ys,[f'{int(x)}m' for x in frame.race_distance_m]);ax.grid(axis='x',alpha=.2)
        ax.set_xlabel('Difference in seconds (negative = faster)')
    axs[0].invert_yaxis()
    fig.suptitle('Jeju finish-time comparisons within supported grade and track cells',fontsize=12)
    fig.tight_layout();fig.savefig(O/'period_and_q4_differences.png',dpi=170);plt.close(fig)
    report=f'''# 제주 최근 3년 기록과 10월 이후 평균의 비교

2026년10월9일. **최근3년은 보유 장기 평균보다 빠르지만, 과거10~12월 평균이 일관되게 낮은 것은 아니다.** 공통 등급·주로 조건을 맞춘800~1200m에서는10~12월이 오히려 느린 방향이었다.1110·1200m는 점별95%구간이0을 포함하고 연도별 예외도 있다.

최근3년은2024~2026년 보유분이며 완전한3개 연도가 아니다. 원천 상한은2026-09-19여서2026년10월 이후 실제 기록은 없다. 이번 결과로2026년10~12월 평균을 관측했다고 설명하거나 미래 평균을 확정하지 않는다.

## 비교 방법과 범위

이전 연구의 정정·보류·제외 정책을 반영한 출전 스냅샷에서2019년 이후46,381출전·4,677경주를 사용했다. 원천 ID와 해시를 연결했으며 외부 수집과DB 변경은 없다. 시간은 전체·S1F·1C·2C·3C·4C·G3F·G1F를 따로 집계했다. 코너의 누적시간과 종반 구간시간을 합산하지 않는다.

정확 거리 안에서 원문 등급과 주로상태가 같은 조건을 비교했다. 각 비교의 양쪽 모두30출전·5경주·5경주일 이상인 조건만 남기고, 양쪽 출전수를 합한 고정 비중으로 평균을 다시 계산했다. 계절 합산에는 연도도 같은 조건으로 묶어 연도 구성 차이를 줄였다. 이 지원 정책은 평균 비교를 위한 분석자 선택이며 앞선 이상치 경계의100출전 기준과 목적이 다르다.

아래 음수는 오른쪽 기간이 빠름, 양수는 느림이다. 장기 표본 안에 최근 표본이 포함되므로 두 집단을 독립으로 처리하지 않고 날짜별 영향값을 합쳐 중복 공분산을 반영했다.95%구간은 경주일 군집 t 근사이며 여러 비교에 대한 동시 신뢰구간은 아니다. 말 능력·부담중량·편성 등의 차이를 완전히 통제한 계절 인과효과가 아니다.

## 최근 3년과 장기의 차이

{overview_table}

첫 열은 실제 보유 기간끼리 등급·주로 비중을 맞춘 차이다. 둘째 열은 모든 연도를1월1일~9월19일로 제한하고 월별 구성까지 같은 비중으로 맞춘 추가 점검이다. 이때에도800·900·1000·1110m는 빠른 방향이 남았고1200m는−0.14초,95%−0.31~+0.03초로 불확실했다. 두 열은 공통 지원 조건의 집합이 달라 감소분 전체를 순수한 계절 효과라고 해석하지 않는다.

실제 보유 기간 비교의 표본과 구간은 다음과 같다.

{primary_table}

1300m는 장기와최근의 보유 출전이 동일해 차이0이다. 과거 대비 변화가 없다는 증거가 아니다.1400m는+0.04초,95%−0.48~+0.57초로 불확실하고1610m는 공통 지원이 없다. 이 범위에800~1200m의 결과를 확대하지 않는다.

앞서 예로 든1000m·제5등급·건조의 단순 평균은장기86.63초,최근3년86.05초,2026년84.60초다. 거리 전체 표는 여러 공통 등급·주로를 같은 비중으로 합친 것이므로 이 단일 조건 예시와 수치가 다르다.

## 과거 10월부터 12월까지의 평균

2019~2025년의 같은 연도·등급·주로 조건에서10~12월을1~9월과 비교했다.2026년은 이 비교에서 제외했다.

{q_table}

800·1000m는 공통 지원이 있는 모든 연도에서10~12월 평균이 더 느린 방향이었다.900m는2024년,1110m는2025년,1200m는2024년에 반대 방향이 있었지만 각각의 구간은0을 포함한다. 모든 연도·모든 거리에 적용할 고정 계절 차이는 확정하지 않았다.

1000m의 연도별 비교는 다음과 같다.2020년의 빈 값은 지원 부족이며 효과0이 아니다.

{annual_table}

10월만 따로 본 추가 점검에서도800m는1~9월보다+0.74초,1000m는+1.32초의 느린 방향이었다. 다만 각각3개 연도·등급·주로 공통 조건뿐이라 거리 전체의 일반적10월 효과로 채택하지 않는다.7~9월과 비교하면1000m의10월 차이는+0.85초,1110m는−0.03초로 불확실했다. 이 비교 역시 공통 조건이 다르므로10월이 반드시 일정한 만큼 느리다는 뜻은 아니다.

## 2026년의 빠른 기록과 구간별 차이

과거도1월1일~9월19일로 잘라 비교하면2026년은1000m−2.47초,1110m−2.84초의 빠른 방향이다. 월 구성까지 맞춘 더 제한된 공통 조건에서도1000m−2.27초(과거944·2026년343출전),1110m−3.38초(과거625·2026년298출전)가 남았다.2026년의 빠른 기록을 단지10~12월 미포함으로 설명하기는 어렵다. 이 수치는 선택된 공통 지원 범위의 관찰 차이로, 원인이나 향후 유지 여부는 미확정이다.

1000m의 구간별 비교는 다음과 같다. 최근3년은 초반S1F보다G3F·G1F의 빠른 방향이 컸고, 과거10~12월은 종반도 느린 방향이었다.

{section_table}

초반·코너·종반의 표본이 일부 다르고 시간이 겹치므로 차이를 합산하지 않는다. 추가적인 느린 꼬리 삭제는 하지 않았으며, 이전에 보류한 불확실한 계측 지점은 그대로 유지했다.

![기간별 전체시간 차이](run02/period_and_q4_differences.png)

## 참고표에 적용할 판단

현재 말 기록을 판단할 때 장기 평균 하나보다 최근 기간과 같은 달의 지원을 함께 확인하는 편이 맞다.2026년 현재 평균의 빠른 방향과 과거 늦가을·겨울의 느린 방향을 별도로 유지해야 한다. 과거10~12월 비교를 근거로2026년10월 이후에도 평균이 낮아질 것이라고 예측하지 않는다. 이전 함수율·월 환산 연구의 확정 적용률 미채택 상태도 바꾸지 않았다.

전체 월·연도·조건·구간 평균은[월별 표](run02/year_month_cells.csv),[기간별 표](run02/period_cells.csv),[계절별 표](run02/season_cells.csv)에 있다. [비중을 맞춘 전체 비교](run02/standardized_comparisons.csv),[달력 범위 추가 비교](run02/calendar_sensitivity.csv),[조건별 계산 근거](run02/common_cell_contributions.csv),[원천 연결](run02/source_manifest.json),[검증](run02/verification.json)을 보존했다.

재현 코드는[주 계산](analyze.py),[달력 추가 점검](calendar_sensitivity.py),[검증과 보고서](report_and_verify.py)다. 기존 출력이 있으면 덮어쓰지 않고 멈춘다. 초기에 열 이름을 잘못 참조해 첫 비교 직전에 멈춘 이력과 원집계는 보존했고 최종 결과는run02에 있다. 이미 여러 연구에서 사용한 보유 자료의 후향 기술통계이며 새로운 독립 미래 검증은 아니다.
'''
    # Reconcile prose denominator directly, before saving.
    assert len(d)==46381 and d.race_id.nunique()==4677
    with (H/'README.md').open('x',encoding='utf-8') as stream:stream.write(report)
    print(json.dumps(verification,indent=2))


if __name__=='__main__':main()

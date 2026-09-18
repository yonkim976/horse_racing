"""Race dossiers and comparison denominators for the outcome audit."""

import json

import polars as pl

from horse_racing.analysis.jeju_error_conditions import flags
from scripts.audit_jeju_error_conditions import METRICS, OUT, ROOT, paired_stats, save

LABELS = {
    "history_time_minus_same_race_median": "최근 경주 내 상대 총기록",
    "current_minus_previous_elo": "직전 대비 Elo 변화",
    "recent_finish_score_5_mean": "최근5회 착순점수",
    "dry_performance_mean": "과거 건조·양호 주로 성적",
    "jockey_history_win_rate": "기수 과거 승률",
    "weight_count_pre": "과거 체중 관측 수",
    "medical_90d_count": "최근90일 진료 기록 수",
    "closing_speed_quality_mean_3": "최근3회 막판 상대속도",
    "jockey_early_front_rate": "기수 초반 선두권 빈도",
    "speed_residual_mean_pre": "과거 보정 속도",
    "historical_early_front_rate": "말 초반 선두권 빈도",
}


def fmt(x, decimals=2):
    if x is None:
        return "미확인"
    if isinstance(x, (float, int)):
        return f"{x:.{decimals}f}"
    return str(x)


def rates(frame):
    result = []
    for key in [k for k in flags({}) if k.startswith("pre_")]:
        for selected in [None, True, False]:
            s = frame if selected is None else frame.filter(pl.col("selected") == selected)
            for value in [None, 0.0, 1.0]:
                part = s.filter(pl.col(key).is_null() if value is None else pl.col(key) == value)
                result.append(
                    dict(
                        condition=key,
                        population="all"
                        if selected is None
                        else "selected3"
                        if selected
                        else "not_selected",
                        value=value,
                        entries=len(part),
                        races=part["race_id"].n_unique(),
                        observed_rate=float(part["official_top3"].mean()) if len(part) else None,
                        mean_probability=float(part["place_probability"].mean())
                        if len(part)
                        else None,
                    )
                )
    return result


def case_section(pair, explanations, evidence):
    a = pair["missed__entry_id"]
    b = pair["selected__entry_id"]
    title = f"{pair['event_date']} 제주 {pair['missed__event_number']}경주 — {pair['missed__horse_name']} / {pair['selected__horse_name']}"  # noqa: E501
    lines = [f"## {title}", "", "| 관측 | 놓친 입상마 | 잘못 선택한 말 |", "|---|---:|---:|"]
    values = [
        ("예측 입상확률", "place_probability"),
        ("실제 착순", "finish_position"),
        ("직전 출전일", "previous_date"),
        ("이번 거리(m)", "distance_m"),
        ("거리 변화(m)", "pre_distance_change_m"),
        ("선언 부담중량(kg)", "pre_declared_burden_kg"),
        ("직전 대비 부담중량(kg)", "pre_burden_change_kg"),
        ("직전 대비 상대 Elo", "pre_rival_change_elo"),
        ("최근3회 대비 상대 Elo", "current_vs_previous_rival_elo"),
        ("출주번호 상대위치 변화", "pre_number_fraction_change"),
        ("선언 기수", "pre_declared_jockey"),
        ("직전 대비 기수교체(1=교체)", "pre_jockey_changed"),
        ("직전 상대착순점수(높을수록 좋음)", "pre_previous_finish_quality"),
        ("같은 거리 경험", "distance_starts_pre"),
        ("사전 선행형 상대 수 변화", "pre_early_pressure_change"),
        ("당일 초반 순위", "post_early_rank"),
        ("당일 결승200m전 순위", "post_g1_rank"),
        ("당일 막판200m(초)", "post_g1f_seconds"),
        ("막판 상대속도 변화(과거3회 대비)", "post_closing_vs_history"),
        ("당일 실제 체중 변화(kg)", "post_bodyweight_change_kg"),
        ("당일 함수율 변화(%p)", "post_moisture_change_pp"),
        ("자료 entry_id", "entry_id"),
        ("직전 entry_id", "previous_entry_id"),
    ]
    for label, key in values:
        vals = []
        for pre in ["missed", "selected"]:
            v = pair.get(pre + "__" + key)
            vals.append(f"{v:.1%}" if key == "place_probability" and v is not None else fmt(v))
        lines.append(f"| {label} | {' | '.join(vals)} |")
    grade = []
    for eid in [a, b]:
        now = evidence[eid]
        previous = (
            pair["missed__previous_entry_id"] if eid == a else pair["selected__previous_entry_id"]
        )
        old = evidence.get(previous, {})
        grade.append(f"{old.get('grade', '미확인')} → {now.get('grade', '미확인')}")
    lines.append(f"| 문서 등급(원문) | {' | '.join(grade)} |")
    lines += [
        "",
        "**모델이 잘못 선택한 말을 더 높게 평가한 항목**(원점수 기여 차이; 경주 원인과 다름):",
    ]
    for name, value in explanations[pair["race_id"]]["model_favored_selected"]:
        lines.append(f"- {LABELS.get(name, name)}: 놓친 말−선택한 말 {value:+.4f}")
    lines += [
        "",
        "**확인 수준:** 위 표의 조건 변화·통과순위·구간시간은 자료에서 관측한 사실이다. "
        "거리 단축·기수 교체·중량 변화가 이번 착순을 일으켰다는 인과는 확인하지 않았다. "
        "출발 지연·접촉·진로 방해·고의적인 힘 조절은 영상/심판 근거를 대조하지 않아 미확인이다.",
        "",
    ]
    if any(
        pair[p + "__previous_date"] and not pair[p + "__previous_date"].startswith("2025")
        for p in ["missed", "selected"]
    ):
        lines += [
            "이 사례는2024→2025 연도 경계를 포함한다. 등급 기준·공식 레이팅 일괄 조정이 있어 등급 숫자 변화만으로 개별 강급/편성 완화를 확정하지 않는다.",  # noqa: E501
            "",
        ]
    return lines


def main():
    frame = pl.read_parquet(OUT / "entry_conditions.parquet")
    pairs = pl.read_parquet(OUT / "paired_conditions.parquet").to_dicts()
    cols = list(dict.fromkeys(list(METRICS) + list(flags({}))))
    # Deduplicate the overlapping jockey-change metric in the first audit output.
    save("paired_statistics.json", paired_stats(pairs, cols))
    controls = json.loads((OUT / "all_entry_context.json").read_text())
    save("all_entry_context.json", list({(r["role"], r["metric"]): r for r in controls}.values()))
    population = rates(frame.filter(~pl.col("boundary_tie")))
    save("full_population_condition_rates.json", population)
    evidence = {
        r["entry_id"]: r
        for r in [json.loads(x) for x in (OUT / "source_evidence.jsonl").read_text().splitlines()]
    }
    explanations = {
        r["race_id"]: r for r in json.loads((OUT / "case_model_explanations.json").read_text())
    }
    sortedpairs = sorted(pairs, key=lambda r: (-r["score_margin"], r["race_id"]))
    chosen = [dict(reason="top6_score_margin", race_id=r["race_id"]) for r in sortedpairs[:6]]
    for flag in flags({}):
        eligible = [
            r
            for r in sortedpairs
            if r.get(
                "selected__" + flag if "worsened" in flag or "lost_3" in flag else "missed__" + flag
            )
            == 1
        ]
        if eligible:
            chosen.append(dict(reason=flag, race_id=eligible[0]["race_id"]))
    save("case_selection.json", chosen)
    casebook = [
        "# 놓친 입상마와 잘못 선택한 말: 332경주 대조표",
        "",
        "동착 경계 제외, 정확히 두 마리를 맞힌 모든 경주다. 사후 분석이며 모델 학습에 사용하지 않았다. "  # noqa: E501
        "사전/선언 조건과 당일 결과문서 관측을 구분한다. 수요일 게시시각 증빙은 완전하지 않다. "
        "당일 정보는 진단 전용이며 새 예측 변수로 연결하지 않았다.",
        "",
    ]
    for r in sorted(pairs, key=lambda r: (r["event_date"], r["missed__event_number"])):
        casebook += case_section(r, explanations, evidence)
    book = "\n".join(casebook)
    (OUT / "all_332_cases.md").write_text(book)
    summary = json.loads((OUT / "summary.json").read_text())
    stats = {r["metric"]: r for r in json.loads((OUT / "paired_statistics.json").read_text())}
    model = json.loads((OUT / "model_explanation_summary.json").read_text())
    lines = [
        "# 제주마 v12 예측 실패 조건 분석",
        "",
        "## 결론",
        "",
        "**이번 실패 표본에서는 과거 성적이 좋았던 말의 당일 수행 저하와, 과거 성적이 나빴던 말의 당일 반등이 주요 관측 패턴이었다.** "  # noqa: E501
        "모델 점수 분해에서도 최근 상대 기록·Elo 변화·최근 착순이 잘못 선택한 말을 지지했다. "
        "이는 실패 사례의 설명이지, 최근 성적 변수를 무조건 약화해야 한다는 증거는 아니다.",
        "",
        "부담중량 변화에는 차이가 있었지만 편성·출주번호·함수율 변화가 모든 누락 입상마에 유리했던 것은 아니다. "  # noqa: E501
        "기수 교체는 누락 사례에서 많았으나 전체 표본에서는 교체 말의 입상률이 더 낮았다. 따라서 기수 교체·직전 부진에 단순 가산점을 주는 개선은 지지되지 않는다.",  # noqa: E501
        "",
        "## 범위와 근거",
        "",
        f"기존 HY_R_FORM의 2025년715경주를 고정했다. 핵심은 두 마리 정답·경계 동착 제외 **332경주({summary['pair_days']}경기일)**의 일대일 비교다.",  # noqa: E501
        "보조로 비경계709경주·6,894출전행 전체를 분석했다. 같은 말의 반복 출전이 포함된다. "
        "원래 모델·예측·2026년 평가를 변경하지 않았고 추가 학습은0회다.",
        "",
        "사전 관측은 T−2까지의 이전 출전과 저장 출마표다. 당일 체중·날씨·구간·실제 기수는 결과문서 관측으로 별도 표시한다. "  # noqa: E501
        "T−2와 수요일 출마표 기준은 다를 수 있고 실제 과거 게시시각 증빙은 완전하지 않다.",
        "",
        "## 1. 직전 대비 무엇이 달랐나",
        "",
        "이전 이력이 양쪽 모두 관측된305쌍의 비교다. 경험 횟수는332쌍이다. 평균 차이 구간은 경기일 대응 bootstrap5,000회, seed17의95% 구간이다. "  # noqa: E501
        "다중 비교를 보정하지 않은 탐색 결과이며 인과관계나 새 규칙의 성능을 뜻하지 않는다.",
        "",
        "| 항목 | 놓친 입상마 | 잘못 선택한 말 | 차이95% 구간 |",
        "|---|---:|---:|---:|",
    ]
    for key, label, percent in [
        ("pre_burden_change_kg", "부담중량 변화(kg)", False),
        ("pre_jockey_changed", "기수교체 비율", True),
        ("pre_recent_poor_finish", "직전 상대착순 하위25% 비율", True),
        ("distance_starts_pre", "같은 거리 출전 경험 평균", False),
        ("pre_distance_change_m", "거리 변화(m)", False),
        ("pre_rival_change_elo", "직전 대비 상대 Elo 변화", False),
        ("current_vs_previous_rival_elo", "최근3회 대비 상대 Elo 변화", False),
        ("pre_number_fraction_change", "출주번호 상대위치 변화", False),
        ("pre_early_pressure_change", "선행형 상대 수 변화", False),
    ]:
        r = stats[key]
        factor = 100 if percent else 1
        suffix = "%p" if percent else ""
        left = f"{r['missed_mean']:.1%}" if percent else fmt(r["missed_mean"])
        right = f"{r['selected_mean']:.1%}" if percent else fmt(r["selected_mean"])
        ci = f"[{r['day_ci'][0] * factor:+.2f}, {r['day_ci'][1] * factor:+.2f}]{suffix}"
        lines.append(f"| {label} | {left} | {right} | {ci} |")
    lines += [
        "",
        "- 부담중량은 놓친 말에서 평균 감소, 잘못 선택한 말에서 평균 증가했다. 그러나 1kg 이상 감량 비율의 차이 구간은0을 포함한다. 감량만으로 입상을 설명할 수 없다.",  # noqa: E501
        "- 직전 대비 편성 강도·출주번호·선행형 상대 수 차이는 구간에0을 포함한다. 최근3회 대비 편성은 차이가 있지만 약2Elo의 작은 추정치다. 보편적 유리 조건으로 단정하지 않는다.",  # noqa: E501
        "- 출주번호는 선언 번호 대용치이며 물리 게이트 이득을 확정하지 않는다. 상대 강도 역시 기존 Elo 추정치다.",  # noqa: E501
        "",
        "## 2. 실제 경주에서는 무엇이 달랐나",
        "",
        "| 관측 패턴 | 놓친 입상마 | 잘못 선택한 말 | 양쪽 관측 쌍 |",
        "|---|---:|---:|---:|",
    ]
    for key, label in [
        ("post_early_improved_025", "초반 상대순위가 과거 평균보다0.25 이상 상승"),
        ("post_closing_improved_025", "막판 상대속도가 과거 평균보다0.25 이상 상승"),
        ("post_closing_worsened_025", "막판 상대속도가 과거 평균보다0.25 이상 하락"),
        ("post_lost_3places_from_early", "초반 대비 결승에서3계단 이상 하락"),
    ]:
        r = stats[key]
        lines.append(
            f"| {label} | {r['missed_mean']:.1%} | {r['selected_mean']:.1%} | {r['paired_n']} |"
        )
    lines += [
        "",
        "상대순위·상대속도는0~1 점수이며0.25는25% 빨라졌다는 뜻이 아니다. 막판 상대속도는 해당 경주 경쟁마 사이의 순위이므로 상대 구성 변화도 섞인다. "  # noqa: E501
        "초반 통과부터 결승까지 순위 하락은 결과를 직접 포함하는 묘사다. 이 수치를 예측력을 입증한 사전 신호로 사용하면 결과 누출이다.",  # noqa: E501
        "",
        "당일 체중 변화는 양쪽 관측198쌍뿐이었다. 평균 증감은 놓친 말−0.73kg, 잘못 선택한 말+0.20kg였지만 차이 구간에0이 포함됐다. "  # noqa: E501
        "절대10kg 이상 변화 비율은13.1% 대5.6%였으나 증감 방향과 정상 체중·건강 상태를 확인하지 않아 좋고 나쁨을 판정할 수 없다. "  # noqa: E501
        "함수율 변화의 차이도 뚜렷하지 않았다. 양쪽 말이 같은 당일 주로를 뛰므로 직전 주로 차이는 말의 주로 적응 효과와 같지 않다.",  # noqa: E501
        "",
        "## 3. 왜 모델은 잘못 선택했나",
        "",
        "고정된 순위 모델2개의 트리 기여도를 평균해 두 말의 점수 차이를 재구성했다. 선택된 쪽을 평균적으로 지지한 상위 항목은 다음과 같다. "  # noqa: E501
        "음수는 놓친 말의 점수가 더 낮아졌다는 뜻이며 확률%p가 아니다. 상관된 변수 사이의 기여 배분은 유일한 원인 설명이 아니다.",  # noqa: E501
        "",
        "| 항목 | 놓친 말−선택한 말 평균 점수 기여 |",
        "|---|---:|",
    ]
    for r in model["aggregates"][:8]:
        lines.append(
            f"| {LABELS.get(r['feature'], r['feature'])} | {r['mean_difference_all_pairs']:+.4f} |"
        )
    lines += [
        "",
        "이 결과는 모델이 과거 좋은 기록을 근거로 선택했다는 설명이다. 진료 건수·체중 관측 수 같은 항목은 자료량·경력과 얽힐 수 있으며 질병·체중의 인과효과를 뜻하지 않는다.",  # noqa: E501
        "",
        "## 4. 전체 표본을 보면 단순한 개선 규칙은 성립하지 않는다",
        "",
        "| 사전 조건 | 해당 출전 수 | 실제 입상률 | 평균 예측 | 반대 조건 실제 입상률 |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, label in [
        ("pre_jockey_changed", "기수 교체"),
        ("pre_recent_poor_finish", "직전 상대착순 하위25%"),
        ("pre_burden_down_1kg", "부담중량1kg 이상 감소"),
        ("pre_easier_field_20elo", "직전 대비 상대Elo20 이상 감소"),
        ("pre_distance_shorter", "거리 단축"),
    ]:
        yes = next(
            r
            for r in population
            if r["condition"] == key and r["population"] == "all" and r["value"] == 1
        )
        no = next(
            r
            for r in population
            if r["condition"] == key and r["population"] == "all" and r["value"] == 0
        )
        lines.append(
            f"| {label} | {yes['entries']} | {yes['observed_rate']:.2%} | {yes['mean_probability']:.2%} | {no['observed_rate']:.2%} |"  # noqa: E501
        )
    lines += [
        "",
        "각 조건의 미관측 행은 해당 비교에서 제외했다. 위 비율은 교란을 보정한 효과가 아니다. 기수 교체·직전 부진 말은 전체에서 이미 입상률이 낮고 모델 평균도 이를 반영한다. "  # noqa: E501
        "따라서 누락 입상마 사례만 보고 이 조건을 모두 우대하면 다른 경주의 오답을 늘릴 수 있다.",
        "",
        "## 5. 구체적 사례",
        "",
        "사례를 결론에 맞춰 고르지 않도록 원래 모델의 오판 점수 차이가 가장 큰6경주를 아래에 제시했다. 모든332경주 대조표도 별도 보존했다.",  # noqa: E501
        "",
    ]
    grade_diag = json.loads((OUT / "grade_transition_diagnostic.json").read_text())
    grade_group = next(
        r
        for r in grade_diag["full_population"]
        if r["population"] == "all" and r["grade6_to5"] == 1
    )
    grade_text = [
        "## 추가 사후 진단: 등급 이동과2025년 제도 변경",
        "",
        "아래는 위 분석의 사례를 확인한 뒤 추가한 탐색이다. 처음부터 지정한 가설이나 독립 검증 결과가 아니다. "  # noqa: E501
        "공식2025년 시행계획은 등급별 레이팅 기준 변경과 기존 레이팅35점 일괄 하향을 명시한다. "
        "6등급에서 수득상금 기준을 충족하면 레이팅 부여와 승급이 이루어진다. "
        "[한국마사회2025 제주 시행계획 PDF](https://race.kra.co.kr/down/raceplan2025_jeju.pdf), PDF4·8·12쪽. "  # noqa: E501
        "공식 레이팅과 자체 Elo는 별개이며 Elo에서35점을 빼라는 뜻이 아니다.",
        "",
        "연도 경계와OPEN·미확인 등급을 제외하고 양쪽의 이전 출전까지2025년인252쌍을 비교했다. "
        "6→5등급 이동은 놓친 말3/252(1.2%), 잘못 선택한 말21/252(8.3%)였다. "
        "현재 모델에는 당일 등급은 있지만 명시적인 직전 대비 등급 이동 변수는 없다.",
        "",
        f"전체 비교 가능한 표본에서6→5등급 이동184출전의 평균 입상 예측은{grade_group['mean_probability']:.2%}, 실제는{grade_group['observed_rate']:.2%}였다. "  # noqa: E501
        f"과대 예측 차이의 경기일95% 구간은[{100 * grade_group['bias_day_ci'][0]:+.2f}, {100 * grade_group['bias_day_ci'][1]:+.2f}]%p다. "  # noqa: E501
        "그러나 이 말들의 실제 입상률 자체는 나머지 비교 집단30.62%보다 높다. 승급마를 무조건 제외하는 근거가 아니라, "  # noqa: E501
        "좋은 최근 성적의 지속 가능성을 승급·거리·부담중량과 함께 보정할 필요가 있는지 시험할 근거다.",  # noqa: E501
        "",
    ]
    insert = lines.index("## 5. 구체적 사례")
    lines[insert:insert] = grade_text
    for r in sortedpairs[:6]:
        lines += case_section(r, explanations, evidence)
    lines += [
        "## 6. 개선으로 연결할 우선 가설",
        "",
        "1. **좋은 직전 성적의 재현 가능성:** 직전 좋은 성적과 승급·중량 증가·거리 변경·선행 경합을 함께 평가한다. 등급 이동은 연도별 제도 변경을 분리한다. 특히 단일 호성적을 지속 능력으로 해석하는지 점검한다. 현재 평균 변화 변수만으로 조건 간 결합을 충분히 표현하는지는 미확인이다.",  # noqa: E501
        "2. **부진 이후 반등 가능성:** 같은 거리 경험, 과거 최고 수행, 최근 구간 변화와 직전 전개의 불리함을 함께 사용한다. 기수 교체나 거리 단축 하나에 일괄 가산점을 주지 않는다. 아직 실제 반등을 사전에 구분할 수 있다는 증거는 아니다.",  # noqa: E501
        "3. **기록의 원인 확인:** 높은 오판 확신 사례부터 공식 심판 기록·경주 영상의 출발/진로/접촉을 대조한다. 현재 원장에는 이를 입증하는 라벨이 없어 포기 주행·체력 소진·기수 의도를 확정하지 않는다.",  # noqa: E501
        "4. **평가 규칙 유지:** 위 가설은2025년 오류를 보고 만든 것이므로 새 고정 후보를 설계한 뒤 미사용 기간에서 한 번 검증한다. 이번332경주만 다시 맞히도록 최적화하거나 당일 실제 구간시간을 사전 변수에 넣지 않는다.",  # noqa: E501
        "",
        "원래의 세 목표(한 마리 입상·상위 세 마리 집합·정확한 순서)를 유지한다. 이번 작업은 원인 진단이며 적중률 향상 실험이나 실전 모델 교체가 아니다.",  # noqa: E501
        "",
        f"- [332경주 전체 대조표]({OUT}/all_332_cases.md)",
        f"- [조건별 통계·불확실성]({OUT}/paired_statistics.json)",
        f"- [전체 출전마 비교]({OUT}/full_population_condition_rates.json)",
        f"- [모델 점수 설명]({OUT}/model_explanation_summary.json)",
        f"- [검증 결과]({OUT}/verification.json)",
        "",
    ]
    report = "\n".join(lines).replace("쌍의 일대일 비교다.", "쌍의 일대일 비교다.")
    (OUT / "report.md").write_text(report)
    (ROOT / "docs/JEJU_NATIVE_ERROR_CONDITIONS_REPORT_2026-09-16.md").write_text(report)
    print("Report and332dossiers complete")


if __name__ == "__main__":
    main()

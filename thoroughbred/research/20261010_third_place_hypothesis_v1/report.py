"""Preserve the supported difficulty result and the unproven causal explanation."""

# ruff: noqa: E501

import json

import pandas as pd
import run as e


def table(frame):
    def cell(v):
        return f"{v:.4f}" if isinstance(v, float) else str(v)

    return "\n".join(
        [
            "| " + " | ".join(frame.columns) + " |",
            "| " + " | ".join(["---"] * len(frame.columns)) + " |",
            *[
                "| " + " | ".join(cell(v) for v in row) + " |"
                for row in frame.itertuples(index=False, name=None)
            ],
        ]
    )


def main():
    e.check()
    for name in ["verification.json", "conditions_audit.json", "ordered_verification.json"]:
        assert json.loads((e.OUT / name).read_text())["status"] == "passed"
    assert not (e.HERE / "README.md").exists()
    positions = pd.read_csv(e.OUT / "position_summary.csv")
    differences = pd.read_csv(e.OUT / "paired_differences.csv")
    collapse = pd.read_csv(e.OUT / "collapse_summary.csv")
    patterns = pd.read_csv(e.OUT / "miss_patterns.csv")
    mechanics = pd.read_csv(e.OUT / "conditional_mechanics.csv")
    matched = pd.read_csv(e.OUT / "matched_collapse.csv")
    ordered = pd.read_csv(e.OUT / "ordered_summary.csv")
    ordered_d = pd.read_csv(e.OUT / "ordered_paired_differences.csv")
    def main_filter(f):
        return f.variant.eq("month_gate_weight22") & f.cohort.eq("full") & f.period.eq("all")
    base = positions[main_filter(positions)]
    base_c = collapse[main_filter(collapse)]
    base_d = differences[main_filter(differences)]
    base_patterns = patterns[main_filter(patterns)]
    third_miss_fail = base_patterns[
        (base_patterns.scope == "trio6_fail")
        & base_patterns.pattern.str.split("-").map(lambda v: "3" in v)
    ].races.sum()
    third_only_fail = base_patterns[
        (base_patterns.scope == "trio6_fail") & base_patterns.pattern.eq("3")
    ].iloc[0]
    full = positions[positions.cohort.eq("full") & positions.period.eq("all")]
    common = positions[positions.cohort.eq("matched_2026") & positions.period.eq("all")]
    body = f"""# 실제 3착마의 예측 난도와 유력마 탈락 가설

2026-10-10. 더러브랫 서울·부산의 기존 동결 예측을 비교했다. **‘3착마는 1·2착마보다 포착하기 어렵다’는 가설은 이번 자료에서 지지됐다. ‘주로 능력마가 탈락하면서 어부지리로 들어온다’는 인과 설명은 확인하지 못했다.** 유력마가 빠진 경주에서 후순위 3착이 늘었지만, 후순위 1·2착도 늘었고 3착에만 집중된 현상은 아니었다.

## 대상과 비교 기준

- 연구22/53입력: 같은 4,799경주/각50,754출전, 2024-01-05~2026-09-20. 현재 선택 연구모델은22개이고53개는 참고 후보다.
- 운영계열: 2026-01-02~09-13 기존 순서공동분포 재추론 자료. 원래1,265경주 중 마번·말ID·정상화착순 전체가 연구와 일치하는 **1,258경주/13,315출전**만 사용했다. 나머지7경주는 제외했다. 현재 실전 사전게시 예측 성적이 아니다.
- 주 지표는 실제1/2/3착마를 **같은 Top3 평가순위의 상위3/5/7두가 포함했는가**다. 자리별 서로 다른 기준을 적용하지 않았다. 말별 Top3확률은 정확3착 확률이 아니다.
- 운영 A의 저장된 순서공동분포에서는 정확1착=pWin, 정확2착=pTop2−pWin, 정확3착=pTop3−pTop2로 별도 확인했다. 각 착순당 한 자리로 맞춰 ‘2위 이내의 두 자리’와 ‘정확3위의 한 자리’를 직접 비교하는 오류를 피했다.

## H1: 실제 3착마는 더 낮게 평가됐는가

비율 열은0~1이다. 평균 예상순위는 낮을수록 모델이 높게 평가했다는 뜻이다.

{table(base[["actual_place", "races", "mean_model_rank", "top3_capture", "top5_capture", "top7_capture"]])}

22입력의 예상상위5두 포착률은 실제1착 **78.39%**, 2착 **68.41%**, 3착 **62.22%**였다.3착−2착 차이는 **−6.19%p**, 날짜군집bootstrap95%구간 **−8.14~−4.42%p**다. 평균 예상순위도1착3.51위,2착4.31위,3착4.81위로 뒤로 갔다.3착−2착 평균순위 차이+0.51위,95%구간+0.39~+0.63위다.22개와53개 모두2024/25/26 각 연도에서3착의 상위5두 포착률이2착보다 낮았고 각 구간도0을 포함하지 않았다.

{table(base_d[base_d.comparison.str.startswith("third_minus_")])}

{table(full[["variant", "actual_place", "races", "top3_capture", "top5_capture", "mean_model_rank"]])}

운영계열도 실제1/2/3착의 상위5두 포착률이82.19%/73.21%/65.58%였다.3착−2착은−7.63%p(CI−11.32~−3.95%p)다. 다른 분모의 연구/운영 수치를 그대로 모델 우열로 읽지 않도록 동일1,258경주 표도 보존했다.

{table(common[["variant", "actual_place", "races", "top3_capture", "top5_capture", "mean_model_rank"]])}

## 같은 한 자리: 정확1·2·3착의 한 마리 예측

운영계열 A의 동일1,258경주에서 각 정확착순 확률이 가장 높은 한 마리를 선택했다. 별도3착 전용 모델을 새 학습한 결과는 아니다.

{table(ordered)}

정확1착386/1,258 **30.68%**, 정확2착263/1,258 **20.91%**, 정확3착181/1,258 **14.39%**다.3착−2착은−6.52%p(CI−9.54~−3.54%p),3착−1착은−16.30%p(CI−19.59~−13.00%p)였다. 한 자리씩 비교해도3착이 어려웠다. 순서공동분포의 추론/보정 한계와 실제 불확실성이 섞인 성능이므로 이 차이를 경마의 보편적 물리법칙으로 확정하지 않는다.

{table(ordered_d)}

## H2: 유력마가 빠지면 예상 밖 3착이 늘어나는가

‘유력마’는 모델입상평가1위, ‘탈락’은 최종1~3착밖, ‘예상 밖’은 평가6위이하로 고정했다. 이는 실제 탈락 여부를 보고 나눈 **사후 진단**이며 경주 전에 붕괴를 예측했다는 뜻이 아니다.

{table(base_c[["condition", "races", "outside1", "outside2", "outside3", "rank3", "mean_outside_count"]])}

평가1위가 입상한2,862경주에서 후순위3착은 **32.67%**, 탈락한1,937경주에서는 **45.33%**였다(+12.66%p,CI+9.95~+15.40%p). 상위2두가 모두 입상하면21.46%, 둘 다 탈락하면57.45%다. 연관성은 있다.

그러나 같은 비교에서 후순위1착은13.73%→33.25%(+19.52%p),2착은25.05%→41.25%(+16.20%p)로 늘었다. **유력마 탈락은 전체 입상구성이 예상에서 벗어나는 경주와 연결된다.** 3착의 증가가2착 증가보다 더 크다는 증거는 없었다. 두 증가폭의 차이는−3.54%p,CI−7.51~+0.38%p다.

연도·지역·거리대·등급대·두수대·사전축입상확률대의 공통셀을 맞춘1,528개 축탈락 경주에서도 후순위3착45.09% 대 표준화한 축입상 대조군34.40%로 차이가 남았다. 하지만 비교조건 자체가 실제입상 결과를 포함하므로 인과효과가 아니며 잔여차이를 ‘어부지리’ 비율로 부를 수 없다.

{table(matched[main_filter(matched)])}

## 정답3두에서 상위말 하나가 빠지는 기계적 효과

평가1위가 입상하지 못했다면 입상3두를 나머지 말들이 채워야 한다. 기존 연구모델의 **비순서 삼복 공동분포**를 축포함/축제외로 조건화해 예상 후순위 입상마 수를 계산했다. 어느 말이 정확3착인지의 확률을 계산한 것은 아니다.

{table(mechanics[main_filter(mechanics)])}

축입상 경주의 실제 후순위 입상마 수는 평균0.715두, 조건분포 예상0.705두였다. 축탈락에서는 실제1.198두, 예상1.209두였다. 관측−예상 차이의 각95%구간은0을 포함했다. 유력마 탈락 조건에서 후순위 입상이 늘어나는 현상의 상당 부분은 기존 공동분포의 자리 재배분으로 설명된다. **어느 경주에서 유력마가 빠질지를 사전에 맞혔다는 뜻은 아니다.**

## ‘능력 없는 말이 운으로 3착’인가

이번의 모델점수와 과거기록은 능력의 대리값이며 진짜능력/운의 분해가 아니다. 과거최근3전 보정전체기록의 유효관측3회 이상인3착마4,018두 중 **50.25%는 이번편성 기록상위약1/3**이었다.1착마는63.85%,2착마는54.62%로,3착마의 사전기록 수준이 평균적으로 낮기는 하지만 절반은 최근기록상 상위권이었다. 최근5전 최고기록 기준으로도 유효3회 이상3착마4,029두 중47.60%가 편성상위약1/3이었다.

{table(base[["actual_place", "recent_percentile_n", "recent_percentile_mean", "recent_percentile_topthird", "best_percentile_n", "best_percentile_topthird", "late_recovery_rate"]])}

과거G3F·G1F 우수+회복빈도 조건은3착마13.94%,2착마13.98%,1착마12.34%로3착에만 특화된 특징은 아니었다.진로/출발사건/의도/사고/경합에서 누가 누구 덕분에 들어왔는지, 유력마가 정상적으로 달렸을 반사실에서는 누가3착인지 이번 자료로 확인할 수 없다.심판자료는 추가하지 않았다.

## 삼복 실패에서 3착 누락이 차지한 범위

전체4,799경주 중 실제입상3두가 예상상위5두에 모두 없는 후보포착실패는3,325개다.그중3착만5위밖이었던경주는1,057개(31.79%)였다. 실제삼복6조합 실패3,571개에서는 **3착만상위5두밖인경주{int(third_only_fail.races):,}개({third_only_fail.fraction * 100:.2f}%)**, 다른착순과의 동시누락까지 포함해 **3착이5위밖인경주{int(third_miss_fail):,}개({third_miss_fail / 3571 * 100:.2f}%)**였다. 상위5두 밖 말도6조합에 포함될 수 있으므로 후보포착 실패와 구매6조합 실패를 구분했다.

{table(base_patterns[base_patterns.scope.eq("trio6_fail")])}

따라서3착 포착은 중요한 병목이지만, 모든삼복실패가3착 때문이거나1·2착은 이미 충분히 맞히고 있다는 결론은 아니다. 입상3두의 동반관계를 유지하면서 놓친상대후보를 잡는 방향을 검증해야 한다. 삼복은순서가없으므로 정확3착전용모형의 적중 개선이 삼복6조합 개선으로 바로 이어지는지도 별도 확인해야 한다.

## 검증·적용 범위

원본해시와T−2과거시점,각경주단독1·2·3착,동일명단/결과,입상확률합3을 확인했다.9,598개 연구경주의 축포함/제외 조건분포를 별도삼복곱산식으로 재계산했다.104개 날짜bootstrap구간,실제착순별순위·포착분모/누락8패턴,탈락표91행·공통셀표39행·조건잔차구간20개를 독립대조했다.운영정확1·2·3착의 비음수/각합1/독립순위선택/paired구간도 검증했다. 숫자비정상착순91/92와운영누락은 기존공통경주정책대로 비입상0으로정상화했으며1·2·3착표식은변경하지않았다.초기정상화보완의코드해시도보존했다.

이는2024~26반복후향표본의진단이며다중비교를보정하지않았다.동일말반복상관을날짜bootstrap이모두제거하지않으며입력정정/당일중량·명단게시시각의PIT한계가유지된다.운영계열은고정재추론자료로현재라이브사전예측과다르다.정확3착난도가모든알고리즘과미래기간에서동일할지는미확인이다.운/능력의인과분해는하지않았다.모델을새학습하거나선택/운영/DB/제주/향후기간을변경·조회하지않았다.

[주계획](PLAN.md) · [정확착순계획](ORDERED_PLAN.md) · [착순별표](outputs/position_summary.csv) · [정확착순표](outputs/ordered_summary.csv) · [같은경주차이](outputs/paired_differences.csv) · [탈락표](outputs/collapse_summary.csv) · [조건분포](outputs/conditional_mechanics.csv) · [실패분해](outputs/miss_patterns.csv) · [검증](outputs/verification.json) · [조건통계대조](outputs/conditions_audit.json) · [정확착순대조](outputs/ordered_verification.json) · [용량](outputs/artifact_inventory.json).
"""
    (e.HERE / "README.md").write_text(body)
    pub = """# 게시 요약: 3착은 더 어려운가, 유력마 탈락의 어부지리인가

더러브랫 연구22입력의2024~26년4,799경주에서 예상상위5두의 실제1/2/3착 포착률은78.39%/68.41%/62.22%였다.고정운영계열의 공통1,258경주에서도 같은방향이었고, 각정확착순 확률1위한마리의 적중은1착30.68%,2착20.91%,3착14.39%였다.‘3착이 더 어렵다’는 가설은이번자료에서지지됐다.

평가1위가입상한경주의 후순위3착은32.67%,탈락한경주는45.33%였다.하지만후순위1·2착도더늘었고,기존삼복분포를축탈락으로조건화한후순위입상마수는관측과비슷했다.이는상위말이빠지면나머지말들의자리가늘어나는구조와전체혼전의연관성이며,3착만‘어부지리’라는인과증명은아니다.

예를들어모델6위말이3착에들었더라도상위평가말의사고덕분인지,자기능력으로들어왔는지는최종착순만으로구분할수없다.과거최근3전기록이충분한실제3착마중절반은편성기록상위약1/3이었다.‘어려움=능력없음/운’으로읽지않아야한다.

삼복6조합실패중3착만예상5위밖인경주는26.97%,다른말과동시누락까지포함해3착이예상5위밖인경주는48.14%였다.3착은중요한병목이지만전체실패를설명하지않는다.반복후향검증/운영재추론/PIT/다중비교한계를유지하고모델선택·운영은변경하지않았다.

[전체 보고서](README.md) · [검증](outputs/verification.json) · [정확착순 검증](outputs/ordered_verification.json).
"""
    (e.HERE / "PUBLICATION.md").write_text(pub)
    e.save(
        e.OUT / "decision.json",
        dict(
            status="third_place_harder_supported_opportunistic_cause_unproven",
            third_place_capture_harder_in_frozen_models=True,
            exact_position_one_slot_comparison_supports_difficulty=True,
            favorite_collapse_associated_with_all_podium_outsiders=True,
            third_specific_causal_windfall_proven=False,
            third_only_share_trio_failures=float(third_only_fail.fraction),
            third_any_outside_share_trio_failures=float(third_miss_fail / 3571),
            new_models=0,
            production_changed=False,
            selected_baseline_changed=False,
            future_period_access=False,
            database_access=False,
            jeju_access=False,
        ),
    )
    shared = [
        e.R / "README.md",
        e.R / "ARTIFACT_SIZE_LOG.md",
        e.R / "conclusions/README.md",
        e.R / "conclusions/SOURCES.md",
        e.R / "conclusions/source_manifest.json",
    ]
    before = {}
    for path in shared:
        before[str(path.relative_to(e.ROOT))] = dict(bytes=path.stat().st_size, sha256=e.sha(path))
        dest = e.OUT / "publication_before" / path.relative_to(e.R)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    e.save(e.OUT / "publication_before.json", before)
    target = e.R / "conclusions/37_THIRD_PLACE_HYPOTHESIS.md"
    assert not target.exists()
    target.write_text(
        pub.replace("(README.md)", f"(../{e.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{e.HERE.name}/outputs/"
        )
    )
    marker = "<!-- third_place_hypothesis_v1_20261010 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{e.HERE.name}/README.md" if path.parent == e.R else target.name
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[3착 예측난도와 유력마 탈락 가설]({link}):22입력4,799경주 상위5두 실제1/2/3착포착78.39/68.41/62.22%.운영공통1,258경주 정확1/2/3착한마리적중30.68/20.91/14.39%.3착어려움은지지되지만어부지리인과설명은미확인.운영유지.\n"
            )
    manifest = json.loads(shared[-1].read_text())
    add = (
        [
            e.HERE / n
            for n in [
                "PLAN.md",
                "ORDERED_PLAN.md",
                "README.md",
                "PUBLICATION.md",
                "ordered_check.py",
                "audit_conditions.py",
            ]
        ]
        + [
            e.OUT / n
            for n in [
                "source_lock.json",
                "ordered_source_lock.json",
                "cohort.json",
                "verification.json",
                "conditions_audit.json",
                "ordered_verification.json",
                "decision.json",
            ]
        ]
        + [target, shared[0], shared[2], shared[3]]
    )
    for path in add:
        name = str(path.relative_to(e.ROOT))
        manifest["sources"] = [row for row in manifest["sources"] if row["path"] != name]
        manifest["sources"].append(dict(path=name, sha256=e.sha(path), bytes=path.stat().st_size))
    e.save(shared[-1], manifest)
    e.save(
        e.OUT / "completion.json",
        dict(
            status="complete_verified_published_locally",
            research_races=4799,
            operating_matched_races=1258,
            new_models=0,
            production_changed=False,
            selected_baseline_changed=False,
            website_deployed=False,
            database_access=False,
            jeju_access=False,
            future_period_access=False,
        ),
    )
    e.check()
    print(pub, flush=True)


if __name__ == "__main__":
    main()

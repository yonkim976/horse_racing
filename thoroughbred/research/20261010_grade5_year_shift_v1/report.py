"""Publish cohort differences without claiming a proven 2026 causal regime shift."""

# ruff: noqa: E501

import json

import pandas as pd
import run as r


def table(frame):
    def cell(v):
        return f"{v:.6f}" if isinstance(v, float) else str(v)

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
    r.check()
    assert not (r.HERE / "README.md").exists()
    for name in ["verification.json", "context_audit.json"]:
        assert json.loads((r.OUT / name).read_text())["status"] == "passed"
    s = pd.read_csv(r.OUT / "summary.csv", dtype={"period": str})
    differences = pd.read_csv(r.OUT / "year_differences.csv")
    numeric = pd.read_csv(r.OUT / "numeric_shift.csv")
    cat = pd.read_csv(r.OUT / "categorical_shift.csv")
    std = pd.read_csv(r.OUT / "standardized.csv")
    controls = pd.read_csv(r.OUT / "controls.csv")
    cf = pd.read_csv(r.OUT / "coefficient_counterfactual.csv")
    regional = pd.read_csv(r.OUT / "within_region_features.csv")
    models = pd.read_csv(r.OUT / "base_model_metadata.csv")
    sensitivity = json.loads((r.OUT / "sensitivity.json").read_text())
    assert sensitivity["minimum_additional_failure_outcomes_to_reverse_brier_delta"] == 1
    target = numeric.query("scope=='calendar_matched'")
    target = target[
        target.feature.isin(
            [
                "axis_gap_section_early_mean3",
                "axis_moist_last3_record_index_mean",
                "axis_moist_last5_record_index_best",
                "axis_history_count",
                "axis_previous_age",
                "axis_gap_moist_last3_record_index_mean",
                "axis_gap_section_last600_mean3",
                "axis_gap_section_late_mean3",
                "field_size",
                "axis_probability",
            ]
        )
    ]
    cats = cat.query(
        "scope=='calendar_matched' and feature in ['meet_band','front_axis','distance_up','early_slow','history_band']"
    )
    body = f"""# 2026년 높은 확률5등급의 보정이 과했던 이유와 조건 차이

2026-10-10. **2026년에 보정계수가 크게 커져서라기보다, 그 표본에서는 원모델의 과신이 작아졌는데 과거에 학습한 집단 공통보정을 적용한 영향이 컸다.** 상대 초반기록과 과거 보정기록 점수의 차이는 관측됐다. 그러나2026년56경주뿐이라 ‘그 조건 때문에 성적이 좋아졌다’는 원인을 확정하지 못했다.5등급 외의 고확률축도2026년에 성적이 좋아졌고 단순 지역·기간 구성만으로는 설명되지 않았다.

## 대상·정의

원22입력의 평가1위축 중 **보정 전 Top3확률≥70%,5등급**을 고정했다.2024년71/2025년78/2026-09-20까지56경주,총205경주다. 축확률은 우승이 아닌3위이내 입상확률이다. 기존40의grade5_local_raw를 재사용했고 새보정이나능력모형을 학습하지 않았다. 이전계수는2020년이후과거연도만으로학습됐으며,기존22능력모형의학습은2017년부터다.

잔차=실제이탈(0/1)−원예상이탈확률이며 양수는입상확률과신방향이다. 표의비율열은0~1,점수열은기존보정기록지수다.

{table(s.query("scope=='full'")[["period", "n", "failures", "mean_axis_probability", "observed_axis_top3", "mean_correction", "residual", "brier_delta"]])}

2024·25합산은원예상입상75.21%대실제67.79%로 **7.42%p과신**,2026은74.71%대73.21%로 **1.50%p과신**이었다. 그런데2026보정은입상확률을평균6.52%p낮춰68.20%로만들었다. 관측평균과비교하면위험을5.02%p높게예상하게됐다. 평균필요보정과개별확률의최적보정은동일하지않으며이를새보정값으로채택하지않았다.

## 계수가 커진 탓인지 분리

2026년56경주의명단/원확률/최종결과를고정하고2025계수를그대로적용했다. 이는경주전에실행한새예측이아닌기존계수반사실계산이다.

{table(cf)}

2025계수0.304849로도예상이탈31.41%대실제26.79%로과했다.2026계수0.323024를쓰면31.80%다. **계수증가의추가효과는0.39%p정도**,보정전체6.52%p에비해작다. 따라서계수가갑자기폭증한것이주된산술원인은아니었다.

## 부분연도 차이를 맞춰도 남았나

2024·25도1월1일~9월20일만남기면119경주다. 원예상입상75.57%대실제64.71%,2026은74.71%대73.21%였다. 비교기간을맞춰도과신감소현상은남았다. 오히려차이가커졌다. ‘2026에는가을경주가없어서’만으로설명되지않는다.

{table(s.query("scope=='calendar_matched'")[["period", "n", "failures", "mean_axis_probability", "observed_axis_top3", "residual"]])}

과신잔차변화2026−이전은전체기간−5.92%p(CI−19.91~+7.82%p),같은달력기간−9.36%p(CI−23.71~+5.37%p)였다. 모두0을포함해확정적인연도체제변화로볼수는없다.

{table(differences)}

## 어떤 사전조건이 달랐나

아래는계절비교를맞춘 **2024·25의119경주 대2026의56경주**다. 최근기록은기존주로·월·게이트보정이반영된전체기록지수,상대구간은기존시간순구간보정이력이다. 새직접기수/게이트/내외측경로는추가하지않았다.

{table(target[["feature", "old_n", "new_n", "old_mean", "new_mean", "difference", "smd", "low", "high"]])}

- **초반 상대우위가 커졌다.** 과거초반200m최근3평균−자기제외경쟁마평균은−0.271초→−0.469초였다. 평균적으로0.20초더앞서는방향이며차이95%구간은−0.299~−0.104초였다. 과거관측55/56경주의정보이며이번경주출발속도나실제선행을확정한것은아니다. 서울도−0.275→−0.456초,부산도−0.261→−0.480초여서부산비중증가만의현상은아니었다.
- **최근·최고 전체기록점수가높았다.** 최근3평균0.476→0.636,최근5최고1.002→1.255였다. 하지만편성대비최근전체기록차는0.975→1.031로작고CI−0.093~+0.202가0을포함했다. 절대지수상승을곧바로상대능력우위확대로확정하지않는다. 최고지수상승은서울에서컸고부산에서는거의없었다.
- **상대적으로젊고이력이적었다.** 직전기록나이2.975→2.821,history_count4.664→3.875였다. history_count는기존730일과거출전범위의수이며최근5전유효수와다르다.7전이상이력비중22.7%→8.9%,3전이하37.8%→44.6%였다. 이것이좋은원인이라는인과주장은아니다.
- **과거선행성향비중은늘었다.** 유효3회이상중선행마군빈도60%이상축은20.2%→33.9%였다. 다만2026년미관측도26.8%이고실제당일선행예측이아니다. 이집단이탈은이전24경주45.8%,2026년19경주21.1%로달랐지만소표본사후연관성이다.
- **모든조건이유리하게바뀐것은아니다.** 두수는9.85→10.14로늘었고,거리연장비중21.0%→28.6%,중량2kg이상증가25.2%→33.9%였다. G3F상대우위는거의같고G1F상대우위는오히려작아졌다. ‘전체적으로쉬운편성이라서’라는단일설명은성립하지않는다.

위21숫자/18분류는여러탐색비교이며CI를동시검정보정하지않았다. 일부차이가관측돼도조건이실제입상상승을일으켰다고증명한것은아니다. 원22모형에최근기록등은이미들어있으므로관측차이를다시가산하면중복평가가될수있다.

{table(regional.query("scope=='calendar_matched' and feature in ['axis_gap_section_early_mean3','axis_moist_last3_record_index_mean','axis_moist_last5_record_index_best']"))}

{table(cats[["feature", "level", "old_n", "new_n", "old_share", "new_share", "old_failure_rate", "new_failure_rate"]])}

## 지역·거리·두수 구성 변화가 설명하나

부산비중은27.7%→51.8%,서울은72.3%→48.2%로큰변화가있었다. 하지만이전같은기간부산이탈률은45.45%로서울31.40%보다높았다. 이전지역별성적에2026지역비중을적용하면이탈률은 **35.29%→38.68%로상승**해야했다. 실제2026은26.79%였다. **부산비중증가때문에성적이좋아졌다는설명은방향이반대였다.**

서울은31.40%→25.93%,부산은45.45%→27.59%로양쪽지역내에서도낮아졌다. 지역×확률대공통셀52/56경주,지역×분기56/56경주에서도이전셀성적을그대로옮기면실제보다이탈을높게예상했다. 거리/두수도단순구성변화만으로설명되지않았다.

{table(std.query("scope=='calendar_matched' and scheme in ['meet_band','prob_band','distance_band','field_band','history_band','early_slow','region_probability','region_season','joint_context']")[["scheme", "old_n", "new_n", "new_coverage", "composition_residual", "within_residual", "total_residual"]])}

history_count구성변화는잔차약−2.16%p,초반느림분류구성변화는약−1.77%p방향이었다. 그러나각각별도표준화이며 **서로더하거나실제원인의기여율로부르면안된다**. 지역·확률·거리·두수결합셀은31/56경주만남으므로전체의설명으로확장하지않는다. 표준화는CI없는기술적점추정이고잔여차이는미관측조건/모형변화/표본변동이모두섞인다.

## 5등급만의 변화인가

같은달력기간의고확률비5등급축도원예상위험대비잔차가−0.66%p→−6.34%p로낮아졌다. 전체축의잔차도+2.51%p→−2.15%p로낮아졌다. **2026년에5등급축만특별히바뀐것은아니었다.**

{table(controls.query("scope=='calendar_matched'")[["group", "time", "n", "mean_raw_risk", "observed_axis_top3", "residual"]])}

5등급잔차변화에서비5등급고확률축변화를뺀값은같은기간−3.69%p(CI−19.91~+12.48%p)로불확실했다. 이는관측difference-in-differences진단이며인과평행추세를가정한효과추정이아니다.

연도별로22입력목록은같아도모형학습종료연도와온도보정연도가달랐다.2026능력모형은2024년까지학습/2025년온도보정이다. 따라서선택되는70%이상축의구성이연도별로같은대상이아니다. 아래메타데이터변화가해당성적변화의원인이라고입증한것은아니다.

{table(models[["meet", "year", "train_end", "calibration_year", "temperature", "trees"]])}

## 작은 표본에서의 과잉 해석 방지

2026년실제이탈은15건,원확률이예상한이탈수합계14.16건,보정후17.81건이었다. 보정후기대값보다 **약2.8경주덜이탈한관측**이다. 날짜군집95%이탈률구간은15.52~38.60%로넓다. 보정평균31.80%도이구간안에있다.

수학적감도계산에서는실제입상한경주중특정1경주가이탈했다고가정하면2026의Brier악화부호가바뀔수있었다. 실제결과를수정하거나그가정이맞다고주장한것은아니다. 작은56표본에서‘보정이잘못된체제로바뀌었다’를확정하기어렵다는뜻이다.

## 판단·검증

**산술적으로는2026관측에필요했던평균보정보다과거공통보정이컸다.** 조건차이중상대초반우위와최근기록점수는후속설명후보지만,기간·지역·거리·두수구성만으로설명되지않았고일반적인연도확률편향변화와표본변동도남았다. 고확률5등급을무조건같은강도로감점하는방법은보류한다. 원확률·상대초반·이력/기록지원에따른보정강도검증은후속과제이며이번에새규칙을학습하거나채택하지않았다.

원40예측/대상/착순/원본해시,205경주·연도분모·달력제한,46개숫자/연도차이구간,2개동시날짜DID구간,42개독립공통셀과분해항등식,계수고정계산,84개지역별숫자행을대조했다. 과거T−2/730일·당일중량PIT한계는기존동결검증을참조했다. 날짜bootstrap이반복말상관을모두제거하지않는다. 신규모델0개,22/운영/기존미래계약변경없음. DB/네트워크/제주/새기간자료접근없음.

[계획](PLAN.md) · [대상요약](outputs/summary.csv) · [숫자조건](outputs/numeric_shift.csv) · [분류조건](outputs/categorical_shift.csv) · [지역내비교](outputs/within_region_features.csv) · [구성분해](outputs/standardized.csv) · [다른등급대조](outputs/controls.csv) · [계수고정](outputs/coefficient_counterfactual.csv) · [불확실성](outputs/year_differences.csv) · [검증](outputs/verification.json) · [독립대조](outputs/context_audit.json) · [용량](outputs/artifact_inventory.json).
"""
    (r.HERE / "README.md").write_text(body)
    pub = """# 게시 요약: 2026년 높은확률5등급 보정 과잉 진단

2026년56경주는원예상입상74.71%대실제73.21%로과신이1.50%p였는데과거학습보정은6.52%p를낮췄다.2025계수를그대로써도과했고계수변경의추가기여는0.39%p뿐이었다.갑작스러운계수증가보다그표본에서작아진과신에과거집단공통보정을적용한영향이컸다.

같은1월~9월20일로맞춘이전119경주와비교하면상대초반200m우위가0.27초→0.47초로커졌고최근·최고전체기록지수도높았다.직전기록나이는낮고과거출전이력은적었다.다만편성대비전체기록우위확대는불확실했고두수/거리연장등모든조건이유리해진것도아니다.

부산비중증가는과거성적기준으로오히려이탈을늘리는방향이어서성적상승을설명하지못했다.고확률비5등급축도2026에더잘입상해5등급만의현상도아니었다.이력·초반구성차이는후속후보이지만인과기여율로해석할수없다.

예를들어56경주의실제이탈15건은보정기대17.81건보다약2.8건적다.연도차이95%구간은넓고0을포함했다.관측차이와구조적원인을구분하고일괄감점은보류한다.현재22/운영/미래계약유지,신규모델0개다.

[전체 보고서](README.md) · [검증](outputs/verification.json) · [조건별 원표](outputs/numeric_shift.csv).
"""
    (r.HERE / "PUBLICATION.md").write_text(pub)
    a2025, a2026 = cf.set_index("version").loc[
        ["2025_coefficient", "2026_coefficient"], "mean_risk"
    ]
    r.save(
        r.OUT / "decision.json",
        dict(
            status="overcorrection_explained_arithmetically_causal_shift_unproven",
            coefficient_increment_risk_change=float(a2026 - a2025),
            early_relative_advantage_shift_observed=True,
            simple_region_composition_explains_improvement=False,
            grade5_specific_regime_change_confirmed=False,
            small_sample_uncertainty_remains=True,
            new_models=0,
            production_changed=False,
            selected_baseline_changed=False,
            existing_future_contract_changed=False,
        ),
    )
    shared = [
        r.R / "README.md",
        r.R / "ARTIFACT_SIZE_LOG.md",
        r.R / "conclusions/README.md",
        r.R / "conclusions/SOURCES.md",
        r.R / "conclusions/source_manifest.json",
    ]
    before = {}
    for path in shared:
        before[str(path.relative_to(r.ROOT))] = dict(bytes=path.stat().st_size, sha256=r.sha(path))
        dest = r.OUT / "publication_before" / path.relative_to(r.R)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    r.save(r.OUT / "publication_before.json", before)
    target_path = r.R / "conclusions/41_GRADE5_YEAR_SHIFT.md"
    assert not target_path.exists()
    target_path.write_text(
        pub.replace("(README.md)", f"(../{r.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{r.HERE.name}/outputs/"
        )
    )
    marker = "<!-- grade5_year_shift_v1_20261010 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{r.HERE.name}/README.md" if path.parent == r.R else target_path.name
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[고확률5등급2026 조건변화와 과잉보정]({link}):2026원과신1.50%p에보정6.52%p,계수증가분0.39%p.기간맞춘초반상대우위0.27→0.47초.지역구성단독설명불가/비5등급도변화/56표본불확실,운영유지.\n"
            )
    manifest = json.loads(shared[-1].read_text())
    paths = (
        [
            r.HERE / name
            for name in [
                "PLAN.md",
                "README.md",
                "PUBLICATION.md",
                "run.py",
                "verify.py",
                "audit_context.py",
                "report.py",
            ]
        ]
        + [
            r.OUT / name
            for name in [
                "source_lock.json",
                "cohort.json",
                "verification.json",
                "context_audit.json",
                "decision.json",
                "sensitivity.json",
            ]
        ]
        + [target_path, shared[0], shared[2], shared[3]]
    )
    for path in paths:
        name = str(path.relative_to(r.ROOT))
        manifest["sources"] = [row for row in manifest["sources"] if row["path"] != name]
        manifest["sources"].append(dict(path=name, sha256=r.sha(path), bytes=path.stat().st_size))
    r.save(shared[-1], manifest)
    r.save(
        r.OUT / "completion.json",
        dict(
            status="complete_verified_published_locally",
            target_races=205,
            latest_year_target_races=56,
            new_models=0,
            database_access=False,
            network_access=False,
            jeju_access=False,
            future_data_access=False,
            production_changed=False,
            selected_baseline_changed=False,
            prior_future_contract_changed=False,
        ),
    )
    r.check()
    print(pub, flush=True)


if __name__ == "__main__":
    main()

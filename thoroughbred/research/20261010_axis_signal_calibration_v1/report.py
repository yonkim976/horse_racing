"""Publish the small retrospective gain without treating it as future validation."""

# ruff: noqa: E501

import json

import pandas as pd
import run as e


def table(d):
    def cell(v):
        return f"{v:.6f}" if isinstance(v, float) else str(v)

    return "\n".join(
        [
            "| " + " | ".join(d.columns) + " |",
            "| " + " | ".join(["---"] * len(d.columns)) + " |",
            *[
                "| " + " | ".join(cell(v) for v in row) + " |"
                for row in d.itertuples(index=False, name=None)
            ],
        ]
    )


def main():
    e.check()
    assert json.loads((e.OUT / "verification.json").read_text())["status"] == "passed"
    assert not (e.HERE / "README.md").exists()
    q = pd.read_csv(e.OUT / "quality.csv", dtype={"period": str})
    dif = pd.read_csv(e.OUT / "paired_differences.csv", dtype={"period": str})
    coeff = pd.read_csv(e.OUT / "coefficients.csv")
    pred = pd.read_parquet(e.OUT / "risk_predictions.parquet")
    transitions = []
    for tag, g in e.periods(pred):
        wide = g.pivot(index="race_key", columns="variant", values="flag")
        meta = g.drop_duplicates("race_key").set_index("race_key").loc[wide.index]
        for source, target in [("raw", "signals"), ("calibration", "signals")]:
            for before, after in [(False, False), (False, True), (True, False), (True, True)]:
                membership = wide[source].eq(before) & wide[target].eq(after)
                y = meta.loc[membership, "collapsed"]
                transitions.append(
                    dict(
                        period=tag,
                        source=source,
                        target=target,
                        before=before,
                        after=after,
                        n=len(y),
                        failures=int(y.sum()),
                        axis_top3=int((1 - y).sum()),
                    )
                )
    pd.DataFrame(transitions).to_csv(e.OUT / "warning_transitions.csv", index=False)
    transitions_frame = pd.DataFrame(transitions)
    for tag, frame in e.periods(pred):
        for source in ["raw", "calibration"]:
            g = transitions_frame[
                transitions_frame.period.eq(tag) & transitions_frame.source.eq(source)
            ]
            raw = frame[frame.variant.eq(source)]
            assert g.n.sum() == len(raw)
            assert g.failures.sum() == raw.collapsed.sum()
            assert g[g.before].n.sum() == raw.flag.sum()
            assert g[g.after].n.sum() == frame[frame.variant.eq("signals")].flag.sum()
    primary = dif.query(
        "period=='all' and group=='all' and left=='signals' and right=='calibration' and metric=='brier'"
    ).iloc[0]
    annual = dif.query(
        "period in ['2024','2025','2026'] and group=='all' and left=='signals' and right=='calibration' and metric=='brier'"
    )
    approved = bool(primary.high < 0 and annual.difference.lt(0).all())
    assert not approved
    full = q.query("period=='all' and group=='all'")
    body = f"""# 축 이탈 위험의 세 조건 보정 시험

2026-10-10. **초반 상대기록·거리 연장·높은 확률의5등급을 작은 위험 보정층에 연결했다. 전체 확률오차는 소폭 줄었지만 개선을 확정하지 못했다.** 2025~26은 개선 방향,2024는 악화 방향이었다. 현재22입력과운영을교체하지않고새기간검증계약을보존했다.

## 무엇을 연결했나

원말능력모형은2017년부터학습한월·게이트·부중22입력그대로다. 축은원점수1위(동점마번순),목표는축의최종1~3착밖여부다. 기존삼복공동분포에서원축확률의여집합q=1−pTop3를읽었다. 말별모델을다시학습하거나다른축을고른것이아니다.

새보정층은원위험logit에①과거초반200m최근3평균이자기제외경쟁마보다느림②직전대비200m이상거리연장③원축확률70%이상+5등급을추가한로지스틱식이다. 조건은38연구와동일하며부호를강제하지않았다. 원위험1개+조건3개+결측표식3개=7입력,상수포함8계수다. 원기록·이력정의는기존T−2/730일/실제출전슬롯을재사용했다. 상대구간은기존시간순시험구간보정자료이고직접기수/현재게이트/실제주행경로는넣지않았다. 이전2026당일중량등PIT한계는유지된다.

raw(원확률),calibration(원확률만보정),signals(세조건추가)3개를비교했다. 추가조건의효과를단순확률재보정과분리하기위해calibration이주대조군이다. 벌점L2=10고정,절편무벌점/기울기1중심/나머지0중심으로과도한보정을억제했다. 여러벌점이나조건문턱을시험해좋은것을고르지않았다.

## 시간순 학습·표본

기존원장2020~2026-09-20의10,770경주를사용했다. 평가2024년은2020~23,2025년은2020~24,2026년은2020~25만으로보정층을학습했다. 기존원말능력모형의시간순동결축/확률은재사용했다. 새위험모형은연도별2개×3년=6개,말능력모형은0개다. 평가표본은2024년1,761/2025년1,750/2026년1,288,합계4,799경주다.

**조건선택은이4,799경주를이미본38연구에서이뤄졌으므로,시간순으로재학습해도새독립검증이되지않는다.** 이번은재사용후향시험이다. 새기간성과는0경주다. 최신일은연구동결입력의종료일이며프로젝트전체DB의종료일을조사한것이아니다.

## 전체 확률 품질

Brier와로그손실은작을수록좋고,AUC는위험순위분리정도로클수록좋다. Brier차이를적중률의%p로읽지않는다.

{table(full[["variant", "n", "brier", "logloss", "auc", "mean_risk", "observed_risk"]])}

원확률Brier0.230332→세조건0.229885,차이−0.000447(CI−0.001429~+0.000528)이다. 주대조군인단순확률보정0.230591대비−0.000706(CI−0.001608~+0.000174)으로95%구간이0을포함했다. AUC는0.617845→0.622445의작은점추정변화이며AUC차이의유의성을따로검증하지않았다.

{table(dif.query("group=='all' and left=='signals' and right=='calibration'"))}

2024년Brier차이는+0.000336(악화),2025년−0.001444,2026년−0.001128이다.2025~26합산차이는−0.001310(CI−0.002394~−0.000237)로0아래였지만,그기간도조건선택에쓰였고전체결과/각연도불확실성이남는다. ‘새기간에서개선입증’으로표현하지않는다.

## 축 이탈을 더 많이 걸러냈나

경고문턱은평가당년결과나분포가아닌 **전년도위험분포상위30%경계**다. 평가연도경고수는정확히30%로고정되지않는다. 경고를자동구매제외로실행하지않았다.

{table(full[["variant", "flagged", "flagged_failures", "flagged_rate", "false_alarms", "quiet", "quiet_axis_top3"]])}

원확률은1,427경주경고중735경주축이탈(51.51%),세조건은1,411경주중731경주(51.81%)였다. 실제축입상인데경고한경주는692→680으로12개줄었지만,포착한축이탈도735→731로4개줄었다. **위험경고를냈다고절반가까운축이입상하는상황은바뀌지않았다.**

경고없는경주의축입상률은원확률3,372경주64.35%,세조건3,388경주64.40%다.분모와선택경주가달라paired적중차이로부르지않는다. 원축그대로이므로모든4,799경주의축입상률은두방법모두2,862/4,799=59.64%로같다. 삼복조합/배당/수익률효과를시험한것은아니다.

{table(pd.DataFrame(transitions).query("period=='all' and source=='raw'"))}

## 조건별 보정이 움직인 방향

{table(q.query("period=='all' and group in ['early_slower','distance_up200','high_probability_grade5']")[["group", "variant", "n", "mean_risk", "observed_risk", "brier"]])}

높은축확률의5등급205경주는실제이탈30.73%였고원위험평균24.93%→단순보정27.93%→세조건30.57%로움직였다. 초반느림1,067경주도예상42.68%→45.09%,실제45.74%로가까워졌다. 반면거리연장1,201경주는실제42.71%인데세조건44.79%로높아져해당집단Brier는원확률보다나빴다. 조건전체를무조건감점하는방식이적절하다는결론은아니다.

{table(coeff[coeff.variant.eq("signals")][["year", "feature", "coefficient", "odds_multiplier"]])}

2026계수에서초반느림/거리연장/높은확률5등급은각각위험오즈약1.21/1.30/1.24배방향이었다. 확률에각각21/30/24%p를더한다는뜻이아니며인과효과도아니다. 절편·기울기·다른조건을함께적용하므로같은조건이어도변화폭이다르다. 결측등급고확률표식은학습표본에서관측부족으로계수0이었다. 결측을평균성능과같다고증명한것이아니다.

## 새기간 검증을 위한 동결

2026-10-11~12-31서울·부산,최초300경주이상과20개날짜이상충족후한번평가하는[계약](outputs/future_validation_contract.json)을보존했다. raw/calibration/signals모두대조하며2026보정계수·문턱은2025-12-28까지학습한값으로고정한다. 기존22모형2026서울/부산해시와상위입력계약도동결참조한다. 결과보고모형/문턱을바꾸면새버전이다.

`run.predict(pre_race_axis_inputs, model_json)` 계산함수와6개저장계수재예측을검증했다. **새기간경주전22입력생성·명단/당일중량공개시각·확률/전개이력종료일·예측생성시각감사와자료수집은아직수행하지않았다.** 미래계약은운영연동완료나예측저장을뜻하지않는다. 경주전시각을확인할수없는새자료는사전검증성적으로합산하지않는다. 자동수집·알림·운영게시를설정하지않았다.

## 검증과 판단

원본해시·원축/확률/최종착순·10,770행원장불변·T−2이력·실제연도학습종료일·저장6모형재예측·수치최적화기울기·결측참거짓·결과변조입력불변·전년도경고문턱·105품질행·210날짜paired구간·기존22모형해시를대조했다. 날짜bootstrap은동일말반복상관을모두제거하지않고다중부분집단은탐색이다. 조합/수익률/자동축제외의가치는미검증이다.

**판단:연구후보로보존,현재22와운영유지.** 전체개선의불확실성과새기간미검증때문에공식축확률에덮어쓰지않는다. 이번작업은작은연구보정층의실제학습·시험·동결까지이며운영연결은아니다.

[계획](PLAN.md) · [확률품질](outputs/quality.csv) · [같은경주차이](outputs/paired_differences.csv) · [계수](outputs/coefficients.csv) · [경고변경](outputs/warning_transitions.csv) · [검증](outputs/verification.json) · [새기간계약](outputs/future_validation_contract.json) · [용량](outputs/artifact_inventory.json).
"""
    (e.HERE / "README.md").write_text(body)
    pub = """# 게시 요약: 축 위험의 세 조건 보정

초반상대기록느림·직전보다200m이상거리연장·원입상확률70%이상+5등급을원22입력축의이탈확률보정층에추가했다.2020년이후과거축예측으로연도별학습하고2024~26의4,799경주에서비교했다.원축은변하지않는다.

전체Brier는원확률0.230332에서0.229885로소폭줄었다.단순확률보정대비차이는−0.000706,95%구간−0.001608~+0.000174로개선을확정하지못했다.2025~26합산은개선방향이나조건선택에쓴반복후향자료다.

경고없는경주의축입상률은64.35%→64.40%였고위험경고경주에서도약48%의축이입상했다.조건이있다는이유로축을일괄제외할근거는부족하다.예를들어높은확률5등급의평균위험은관측에가까워졌지만거리연장은과대보정방향도나타났다.

2026-10-11이후의새기간계약과계수를동결했다.미래성과는0경주이며경주전입력생성/예측시각감사/새자료수집은별도필요하다.자동수집/운영게시/기준선교체를하지않았다.현재22와운영유지,연구후보로보존한다.

[전체 보고서](README.md) · [검증](outputs/verification.json) · [신규기간 계약](outputs/future_validation_contract.json).
"""
    (e.HERE / "PUBLICATION.md").write_text(pub)
    e.save(
        e.OUT / "decision.json",
        dict(
            status="small_retrospective_gain_uncertain_keep_baseline",
            primary_brier_difference=float(primary.difference),
            primary_ci=[float(primary.low), float(primary.high)],
            all_years_improved=bool(annual.difference.lt(0).all()),
            promotion_criterion_passed=approved,
            new_small_risk_models=6,
            new_horse_ability_models=0,
            prospective_predictions=0,
            prospective_evaluated_races=0,
            production_changed=False,
            selected_baseline_changed=False,
            operational_input_pipeline_complete=False,
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
    for p in shared:
        before[str(p.relative_to(e.ROOT))] = dict(bytes=p.stat().st_size, sha256=e.sha(p))
        dest = e.OUT / "publication_before" / p.relative_to(e.R)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(p.read_bytes())
    e.save(e.OUT / "publication_before.json", before)
    target = e.R / "conclusions/39_AXIS_SIGNAL_CALIBRATION.md"
    assert not target.exists()
    target.write_text(
        pub.replace("(README.md)", f"(../{e.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{e.HERE.name}/outputs/"
        )
    )
    marker = "<!-- axis_signal_calibration_v1_20261010 -->"
    for p in [shared[0], shared[2], shared[3]]:
        link = f"{e.HERE.name}/README.md" if p.parent == e.R else target.name
        with p.open("a") as f:
            f.write(
                f"\n\n{marker}\n[축위험 세조건 보정 시험]({link}):4,799경주Brier원0.230332→0.229885,단순보정대비차이CI0포함.위험경고없는축입상64.35→64.40%.운영유지,10/11이후새검증계약/계수보존,미래성과0.\n"
            )
    manifest = json.loads(shared[-1].read_text())
    paths = (
        [
            e.HERE / n
            for n in ["PLAN.md", "README.md", "PUBLICATION.md", "run.py", "verify.py", "report.py"]
        ]
        + [
            e.OUT / n
            for n in [
                "source_lock.json",
                "cohort.json",
                "verification.json",
                "future_validation_contract.json",
                "decision.json",
            ]
        ]
        + list((e.OUT / "models").glob("*.json"))
        + [target, shared[0], shared[2], shared[3]]
    )
    for p in paths:
        name = str(p.relative_to(e.ROOT))
        manifest["sources"] = [r for r in manifest["sources"] if r["path"] != name]
        manifest["sources"].append(dict(path=name, sha256=e.sha(p), bytes=p.stat().st_size))
    e.save(shared[-1], manifest)
    e.save(
        e.OUT / "completion.json",
        dict(
            status="retrospective_test_and_prospective_contract_complete",
            new_small_risk_models=6,
            prospective_evaluated_races=0,
            upstream_prospective_inputs_and_timestamps_pending=True,
            production_changed=False,
            selected_baseline_changed=False,
            database_access=False,
            network_access=False,
            jeju_access=False,
            website_deployed=False,
        ),
    )
    e.check()
    print(pub, flush=True)


if __name__ == "__main__":
    main()

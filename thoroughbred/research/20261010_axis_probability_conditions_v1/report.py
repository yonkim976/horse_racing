"""Publish cautious axis-risk diagnostics with frozen discovery disclosure."""

# ruff: noqa: E501

import json

import pandas as pd
import run as e


def table(d):
    def cell(v):
        return f"{v:.4f}" if isinstance(v, float) else str(v)

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
    assert not (e.HERE / "README.md").exists()
    for name in ["verification.json", "tables_audit.json"]:
        assert json.loads((e.OUT / name).read_text())["status"] == "passed"
    c = pd.read_csv(e.OUT / "conditions.csv", dtype={"period": str})
    m = pd.read_csv(e.OUT / "matched_conditions.csv", dtype={"period": str})
    b = pd.read_csv(e.OUT / "probability_bins.csv", dtype={"period": str})
    selection = json.loads((e.OUT / "discovery_selection.json").read_text())["rules"]
    selected = c[
        c.rule.isin(selection)
        & c.scope.eq("all")
        & c.period.isin(["2024", "2025", "2026", "2025_26"])
    ]
    robust = []
    for rule in selection:
        a = selected[selected.rule.eq(rule)].set_index("period")
        if (
            a.loc["2025", "residual_diff"] > 0
            and a.loc["2026", "residual_diff"] > 0
            and a.loc["2025_26", "residual_diff_low"] > 0
        ):
            robust.append(rule)
    assert not robust
    display = b[b.period.eq("all")][
        ["band", "n", "failures", "failure_rate", "expected_risk"]
    ].copy()
    display["failure_rate"] *= 100
    display["expected_risk"] *= 100
    display.columns = ["축입상확률", "경주수", "이탈수", "실제이탈률%", "평균예상이탈률%"]
    raw = c.query("period=='all' and scope=='all'").sort_values("failure_rate", ascending=False)
    exploratory = c[
        c.rule.isin(["early_slower", "distance_up200", "new_distance"]) & c.scope.eq("all")
    ]
    high = c[c.rule.eq("grade5") & c.scope.eq("prob70plus")]
    body = f"""# 축 입상확률별 이탈과 사전 조건 진단

2026-10-10. **축 이탈 건수는 입상확률50~60%에서741건으로 가장 많았고, 이탈률은40%미만에서62.67%로 가장 높았다.** 높은 확률에서 더 자주 이탈하는 역전 현상은 전체 구간표에서 나타나지 않았다. 사전 조건24개를 점검했지만2024년 추가위험 상위5개가2025~26에서 재현됐다는 근거는 부족했다. 일부 초반기록·거리변경 신호는 후속 연구 후보로 남긴다.

## 정의·범위

주 대상은 현재 선택 연구모델 월·게이트·부중 **22입력**, 서울·부산4,799경주(2024-01-05~2026-09-20)다. 축=모델입상점수1위, 동점은마번순. 이탈=최종1~3착밖. 축확률=기존 비순서 삼복공동분포의 축 포함확률이며 **우승확률이 아니다**. 전체 이탈1,937/4,799 **40.36%**, 평균예상이탈40.41%다. 2024년1,761경주,2025년1,750경주,2026년1,288경주다. 운영모델의 현재 라이브 성적과 구분한다.

현재22개 입력의 과거 전체기록에는 기존 주로·월·게이트 보정이 유지된다. 추가 진단용 구간/통과조 이력은 기존53입력 연구의 시간순 구간보정 자료에서 읽었다. 이 조건들이22입력에 모두 반영됐다는 뜻이 아니다. 기수·조교사·실제내외측경로를 추가하지 않았다.

## 확률 몇%에서 가장 자주 이탈했나

구간은하한포함/상한미포함이며90~100%만100%를포함한다. 주모델90%이상은0경주다.

{table(display)}

- **건수:**50~60%의741건은 전체이탈의38.25%다.60~70%574건과 합치면1,315건/67.89%다. 이 구간에 경주 자체가 많다는 점을 함께 봐야 한다.
- **비율:**40%미만은94/150=62.67%(날짜bootstrap95%구간55.10~70.21%).50~60%는45.21%,60~70%36.70%,70~80%25.43%,80~90%11.24%다.
- **높은 축도 실패:**70%이상은186/781=23.82%이탈했다.80~90%는89경주/10이탈이라11.24%의95%구간이4.76~17.48%로 넓다. 미래의 확정률로 읽지 않는다.
- 각 구간의 관측−평균예상이탈95%구간은0을 포함했다. 다만 이것만으로 세부 조건이나 개별말의 확률까지 정확하다고 할 수는 없다.

연도별·2025~26별 수치와 구간은[원표](outputs/probability_bins.csv)에 보존했다. 구간별 평균예상이탈은1−구간평균축확률이며 구간의 중간값이 아니다.

## 실제 이탈률이 높은 조건과 이미 모델이 알고 있는 위험

아래 비율은0~1이다. 조건은서로겹치며 더해서 해석하지 않는다. complement_rate는 해당 조건을 평가할 수 있는 비조건군의 실제이탈률이다. 결측은 해당조건분모에서만 제외했다.

{table(raw[["label", "n", "failures", "failure_rate", "expected_risk", "complement_rate"]].head(10))}

1·2위 점수차가작은900경주는48.78%이탈했고 모델도48.34%를 예상했다.12두이상837경주는46.48%이탈, 예상46.43%다. **혼전·다두수의 높은 위험은 이미 확률에 상당 부분 반영돼 있었다.** 점수차 문턱은점수/tau기준0.1이하이며 입상확률차0.1%p라는뜻이아니다.

84일이상공백182경주는47.80%이탈/예상43.80%지만, 비조건군과의 추가잔차차이95%구간은−2.81~+11.25%p로 불확실했다. 부담중량2kg이상증가39.44%,1700m이상37.75%,과거2전이하38.38%로 어느 조건이든 무조건 축불안이라고 볼 수 없다. 이는 모델이 이미 해당위험과 능력을 반영한 선택된 축의 결과다.

## 예상보다 더 놓치는 조건: 발견과 검증을 구분

잔차=실제이탈(0/1)−예상이탈확률. 조건군−비조건군 잔차차이가 양수면 해당조건에서 모델이 위험을 상대적으로 더 낮게 본 방향이다. 확률에 이미 반영된 난도를 그대로 새 효과라고 부르지 않기 위한 지표이며 완전한 인과 통제는 아니다.

2024년에표본80/이탈20이상·양의잔차차이 중 상위5조건을 먼저 선택했다: **선행성향축+경합후보2두이상, 다른선행성향마2두이상,1~4등급,과거선행성향강함,5등급**. 이후2025/26에 같은정의를 적용했다.

{table(selected[["period", "label", "n", "failure_rate", "expected_risk", "residual_diff", "residual_diff_low", "residual_diff_high"]])}

**5개 모두2025~26 합산 추가잔차차이의95%구간이0을 포함했다.** 예를들어선행축+경합은2024년51.45%이탈/예상40.58%였지만2025~26에서는39.64%/41.46%로 방향이 바뀌었다. ‘선행경합이면 축을 버리자’는 규칙은 재현되지 않았다. 선행성향은 과거3회이상 관측 중60%이상 첫 마군에 있었음이며 이번실제선행의 예측확률이 아니다.

전체 고정조건 결과에서 다음은 **탐색적 후속 후보**였다.2024년 상위5개로 선택되지 않았으므로 검증성공한 규칙처럼 승격하지 않는다.

{table(exploratory[["period", "label", "n", "failure_rate", "expected_risk", "residual_diff", "residual_diff_low", "residual_diff_high"]])}

- 과거초반200m최근3평균이경쟁마평균보다느린축: 전체45.74%이탈/예상42.68%,2025~2646.25%/42.62%.2025~26비조건군대비추가잔차차이+5.97%p(CI+1.78~+10.11%p)였다.2024와2026단독구간은0을포함했다.
- 직전대비200m이상거리연장: 전체42.71%/예상39.87%,2025~2642.91%/40.21%.2025~26추가잔차차이+4.67%p(CI+0.86~+8.51%p)지만2024와2025단독은불확실했다.
- 최근5전동일거리관측없음(구간이력3회이상): 전체43.05%/예상39.67%.2025~26추가차이+4.11%p의CI−0.05~+8.45%p는0을포함했다.

초반·종반은 과거 실제출전슬롯의 구간자료이며 결측을찾아건너뛰지 않는다. 경쟁마평균은 자기말제외, 관측있는말들의 평균이다. 상대말별 지원수가 동일하지 않고 과거거리·지역·편성·상태가 섞일 수 있다. 과거 빠른초반=이번게이트에서빠른출발, 과거선행=이번전개확정이라고 해석하지 않는다.

## 높은 축확률의 예외

사전고정한70%이상부분집단에서5등급축은63/205=**30.73%이탈**, 평균예상24.93%였다.2025~26에서는41/134=30.60%/예상24.83%다. 합산비조건군대비추가잔차차이+10.33%p(CI+1.12~+19.28%p),각연도단독은대체로불확실했다. 이는24조건과부분집단을여럿점검한탐색신호이며5등급전체축의이탈률40.63%(2025~26)와분모가다르다. **높은확률5등급축의 과신 여부를 따로 확인할 후보**, 자동축제외/고정감점 근거는 아니다.

{table(high[["period", "n", "failures", "failure_rate", "expected_risk", "residual_diff", "residual_diff_low", "residual_diff_high"]])}

## 공통조건을 맞춘 보조 비교

연도·지역·5%p축확률·거리대·등급대·두수대의공통셀에서양군각3경주이상일때비교했다. 초반느림2025~26조건군360경주는실제47.50%,표준화비조건군38.04%;거리연장304경주는44.08%대39.80%였다. 전체의일부만남고신뢰구간없는보조표라확정효과로읽지않는다. 두수/등급/거리자체처럼해당셀에서값이고정되는조건은공통비교가불가능하다.

{table(m[m.rule.isin(["early_slower", "distance_up200", "new_distance", "close_top2", "field12"]) & m.period.isin(["all", "2025_26"])])}

## 운영계열 참고와 한계

별도[참고표](outputs/reference_bins.csv)는연구53과운영계열공통1,258경주의기존확률이다. 운영계열은50~60%142/314=45.22%,60~70%136/419=32.46%,70~80%94/295=31.86%,80~90%18/102=17.65%이탈이었다. 연구22와축마·모형·기간·분모가달라같은숫자로합치지않는다. 운영70~80%는예상25.61%보다관측31.86%로높아별도확률보정감사후보이나이번22입력조건검증의결론은아니다. 저장재추론자료이며당시사전공개실적이아니다.

기존동결축·확률·최종착순,T−2과거시점,자기제외선행경쟁수,결측분리,240조건행(24×5기간×2범위),234잔차차이구간,60확률구간구간값,120표준화행을대조했다. 날짜군집bootstrap2,000회는반복말상관을모두제거하지않는다. 다중비교미보정,반복사용2024~26후향자료,당일중량/명단공개시각PIT한계가남는다. 출발/진로/심판자료로이탈원인을확인하지않았다. 이탈조건은관측연관성이고사고/컨디션의인과증명이아니다.

**다음은현재축확률을우선유지하고초반상대기록·거리연장·높은확률5등급을별도사전고정조건으로새기간에서검증하는것이다.** 이번결과를근거로고정감점하거나축을일괄버리지않는다. 신규모델0개,선택22/운영/DB/제주/미래기간변경·접근없음.

[계획](PLAN.md) · [확률구간](outputs/probability_bins.csv) · [전체조건](outputs/conditions.csv) · [발견후검증](outputs/selected_validation.csv) · [공통조건](outputs/matched_conditions.csv) · [검증](outputs/verification.json) · [독립표대조](outputs/tables_audit.json) · [용량](outputs/artifact_inventory.json).
"""
    # The actual number of bin intervals is read from the independent audit.
    count = json.loads((e.OUT / "tables_audit.json").read_text())["probability_bin_intervals"]
    body = body.replace("60확률구간구간값", f"{count}개확률구간신뢰구간")
    (e.HERE / "README.md").write_text(body)
    pub = """# 게시 요약: 축확률과 이탈 조건

더러브랫 선택연구22입력의2024~26년4,799경주에서축입상확률50~60%의이탈이741건으로가장많았다.그구간이탈률은45.21%였다.이탈률이가장높은구간은40%미만62.67%이며70~80%는25.43%,80~90%는11.24%(89경주)였다.축확률은우승이아닌3위이내입상확률이다.

1·2위평가가비슷하거나12두이상일때실제이탈률이높았지만이미모델도높은이탈률을예상했다.예를들어12두이상은실제46.48%대예상46.43%였다.조건이위험해보인다는이유로같은위험을다시차감하면중복평가가된다.

2024년추가위험상위5조건은2025~26에재현됐다는근거가부족했다.다른고정조건중초반상대기록느림/거리연장,70%이상축의5등급은추가감사후보다.선행경합만으로축을버리는규칙은재현되지않았다.탐색다중비교/반복후향표본이며원인이나개별축의탈락을확정하지않는다.

현재22입력과운영은유지했다.새학습·DB·제주·미래자료접근없음.운영계열참고표는별도분모의기존재추론자료로실전공개성적과다르다.

[전체 보고서](README.md) · [확률별 표](outputs/probability_bins.csv) · [조건별 표](outputs/conditions.csv) · [검증](outputs/verification.json).
"""
    (e.HERE / "PUBLICATION.md").write_text(pub)
    e.save(
        e.OUT / "decision.json",
        dict(
            status="risk_monotonic_selected_rules_not_replicated",
            selected_discovery_rules=selection,
            robust_validation_rules=robust,
            exploratory_next_candidates=[
                "early_slower",
                "distance_up200",
                "high_probability_grade5",
            ],
            new_models=0,
            production_changed=False,
            selected_baseline_changed=False,
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
    target = e.R / "conclusions/38_AXIS_PROBABILITY_CONDITIONS.md"
    assert not target.exists()
    target.write_text(
        pub.replace("(README.md)", f"(../{e.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{e.HERE.name}/outputs/"
        )
    )
    marker = "<!-- axis_probability_conditions_v1_20261010 -->"
    for p in [shared[0], shared[2], shared[3]]:
        link = f"{e.HERE.name}/README.md" if p.parent == e.R else target.name
        with p.open("a") as f:
            f.write(
                f"\n\n{marker}\n[축확률별 이탈과 사전 조건]({link}):22입력4,799경주,이탈건수최대50~60%741건/45.21%,이탈률최대40%미만62.67%.2024상위5조건2025~26재현미확인.초반/거리연장/고확률5등급추가감사후보,운영유지.\n"
            )
    manifest = json.loads(shared[-1].read_text())
    paths = (
        [
            e.HERE / n
            for n in [
                "PLAN.md",
                "README.md",
                "PUBLICATION.md",
                "run.py",
                "verify.py",
                "audit_tables.py",
                "report.py",
            ]
        ]
        + [
            e.OUT / n
            for n in [
                "source_lock.json",
                "cohort.json",
                "verification.json",
                "tables_audit.json",
                "discovery_selection.json",
                "decision.json",
            ]
        ]
        + [target, shared[0], shared[2], shared[3]]
    )
    for p in paths:
        name = str(p.relative_to(e.ROOT))
        manifest["sources"] = [a for a in manifest["sources"] if a["path"] != name]
        manifest["sources"].append(dict(path=name, sha256=e.sha(p), bytes=p.stat().st_size))
    e.save(shared[-1], manifest)
    e.save(
        e.OUT / "completion.json",
        dict(
            status="complete_verified_published_locally",
            races=4799,
            new_models=0,
            production_changed=False,
            selected_baseline_changed=False,
            database_access=False,
            jeju_access=False,
            future_period_access=False,
            website_deployed=False,
        ),
    )
    e.check()
    print(pub)


if __name__ == "__main__":
    main()

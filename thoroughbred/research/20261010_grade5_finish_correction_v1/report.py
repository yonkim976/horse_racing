"""Publish the fixed late-section candidates and their failed incremental test."""

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
    for name in ["verification.json", "diagnostic_audit.json"]:
        assert json.loads((r.OUT / name).read_text())["status"] == "passed"
    assert json.loads((r.OUT / "diagnostic_audit.json").read_text())["script_sha256"] == r.sha(
        r.HERE / "audit_diagnostics.py"
    )
    q = pd.read_csv(r.OUT / "quality.csv", dtype={"period": str})
    delta = pd.read_csv(r.OUT / "paired_differences.csv", dtype={"period": str})
    target = q[q.group.eq("target")]
    brier = target.pivot(index="period", columns="variant", values="brier")
    brier = brier.loc[["2024", "2025", "2026", "all", "2025_26"], r.VARIANTS].reset_index()
    primary = delta.query(
        "group=='target' and variant=='finish_interaction' and reference=='joint' and metric=='brier'"
    )
    additive = delta.query(
        "group=='target' and variant=='finish_add' and reference=='joint' and metric=='brier'"
    )
    full = q.query("period=='all' and group in ['all','supported_target']")[
        ["group", "variant", "n", "brier", "logloss"]
    ]
    probs = target[target.variant.isin(["constant", "joint", "finish_add", "finish_interaction"])][
        ["period", "variant", "n", "mean_top3", "actual_top3", "mean_cut"]
    ]
    allocation = pd.read_csv(r.OUT / "outcome_allocation.csv", dtype={"period": str})
    a26 = allocation.query(
        "period=='2026' and variant in ['joint','finish_add','finish_interaction']"
    )
    profiles = pd.read_csv(r.OUT / "profiles.csv", dtype={"period": str})
    profile_summary = profiles.query(
        "period in ['all','2026'] and variant in ['joint','finish_add','finish_interaction']"
    )
    correlations = pd.read_csv(r.OUT / "feature_correlation.csv")
    coeff = pd.read_csv(r.OUT / "coefficients.csv")
    terms = coeff.query(
        "variant=='finish_interaction' and term in ['g3f','g1f','early_positive_x_g3f','early_positive_x_g1f']"
    )
    examples = pd.read_csv(r.OUT / "examples.csv")
    body = f"""# 고확률 5등급 축: 초반 우위에 G3F·G1F를 추가한 보정

2026-10-10. **종반 기록을 추가해도 기존 초반+최근기록 보정을 안정적으로 개선하지 못했다.** G3F·G1F를 함께 넣은 단순 보정은2026년에 조금 좋아졌지만2024·2025년에는 나빠졌다. 초반 우위에 따라 종반 기록의 영향을 달리한 주 후보는 합산에서 오히려 더 나빴다. 운영에는 반영하지 않는다.

## 질문과 대상

초반이 빠른 축도 후반에 버틸 수 있는지 구분하면,42번의 고확률5등급 보정이 나아지는가? 원22입력 연구 모델의 입상확률70% 이상인5등급 축205경주를 대상으로 했다.2024/2025/2026-09-20까지71/78/56경주다. 전체4,799경주의 원축은 그대로이고 대상밖4,594경주의 확률은 원확률과 완전히 같다. 실제 축 입상은142/205=69.27%,전체2,862/4,799=59.64%로 **축을 바꾸지 않았으므로 적중률은 변하지 않는다.** 이번 연구는 동일 축의 입상확률 오차 비교이며 축 교체·후속 후보·조합 적중은 시험하지 않았다.

## 무엇을 추가했는가

모든 상대 우위는 자기 제외 상대마들의 과거 평균기록에서 축의 과거 평균기록을 뺀 초다. 양수면 축이 더 빠르다. 최근3전의 기존 보정 이력을 사용하고 당일 실제 전개나 결과는 사용하지 않았다.

| 입력 | 뜻 | 원천 필드 |
| --- | --- | --- |
| early | 초반200m 상대 우위초 | −axis_gap_section_early_mean3 |
| recent | 보정된 최근3전 전체기록 평균점수 | axis_moist_last3_record_index_mean |
| g3f | 마지막600m 상대 우위초 | −axis_gap_section_last600_mean3 |
| g1f | 마지막200m 상대 우위초 | −axis_gap_section_late_mean3 |

recent는 초·공식rating이 아닌 기존 월·게이트 보정 원장의 점수다. G1F는 G3F에 포함되므로 둘을 별개의 능력 점수로 합산하지 않았다. **이 입력은 과거 평균 구간기록의 조합으로, 같은 과거 경주에서 실제로 선행한 뒤 버틴 기록만 따로 골라낸 지표는 아니다.** 따라서 종반 유지의 대리변수를 시험한 결과다. 과거 거리·전개별 소모를 모두 맞춘 인과적 유지능력으로 해석하지 않는다.

비교3개 raw=원확률,constant=기존 일괄보정,joint=42번 초반+최근기록 보정은 [42번 연구](../20261010_grade5_adaptive_correction_v1/README.md) 원장을 그대로 재사용했다. 새 후보4개는 결과 전에 고정했다.

- g3f_add: joint의 입력에G3F를 추가해 다시 적합.
- g1f_add: joint의 입력에G1F를 추가해 다시 적합.
- finish_add: joint의 입력에G3F·G1F 모두 추가.
- finish_interaction(주 후보): finish_add에초반 우위×G3F,초반 우위×G1F의 관계를 추가.

평가연도Y마다2020~Y−1의 해당 대상만 학습했고 표본은388/459/537경주다. 평균·모집단 표준편차도 학습 대상만 사용했다. 입력z는±3 절단,결측은z=0+별도 표시다. 교호항은 `clip(max(초반우위초,0)/학습초반표준편차,0,3) × 종반z`이며 해당 구간 결측이면0이다. 모든 계수에동일L2=10,부호 강제·재튜닝·감점하한 없음. 새 소형 보정12개,새 말 능력모형0개다. 관계를 추가한 모델은 '좋은 종반이면 반드시 감점 완화'라는 규칙을 강제로 넣은 것이 아니라 그 관계가 과거 자료에 있는지 학습한 것이다.

## 연도별 확률 오차

Brier=(예측입상확률−실제입상여부)²의 평균으로 작을수록 좋다. 적중률(%)이 아니다. 이탈확률로 계산해도 같다.

{table(brier)}

종반을 각각 넣거나 함께 넣은 새 후보4개 모두 합산에서 이전joint0.200412를 넘지 못했다. 단순 동시추가finish_add는0.201253으로 약0.42% 악화됐고,주 후보finish_interaction은0.204218로 약1.90% 악화됐다.2026년 단순동시추가는0.199523→0.198819로 약0.35% 개선됐지만 여전히 일괄0.196698/원확률0.194464보다 나빴다.2026년 주 후보의 변화는0.199523→0.199501로 사실상 미미하다. 전체에서 사후 최상의 새 후보를 골라 채택하지 않았다.

주 후보−이전joint의 같은 경주 Brier차이95%CI다. 경주일 군집 paired bootstrap2,000회seed431010이며 음수면 개선이다.

{table(primary[["period", "n", "difference", "low", "high"]])}

주 비교 합산 차이+0.003805의95%CI[+0.001507,+0.006314]는 양수 범위로, 이번 반복 후향 표본에서는 관계를 추가한 보정이 더 나빴다. 시간순 학습과 계산 검증을 했더라도 조건 선정에2024~2026 결과를 이미 본 선택 편향이 남는다. 새 독립검증이나 모든 종반 가설에 대한 기각으로 해석하지 않는다.

단순동시추가−joint의 비교도 전부 보존했다.2026년의 작은 개선CI는0을 포함한다.

{table(additive[["period", "n", "difference", "low", "high"]])}

## 평균 확률과 2026년 이탈마 구분

mean_top3=평균 예측입상확률,actual_top3=실제입상률,mean_cut=원확률 대비 평균 감점.0~1단위다.

{table(probs)}

2026년 평균 예측은 이전joint69.87%/단순동시추가69.86%/관계추가69.94%,실제73.21%다. 종반 추가만으로 평균 과소평가를 해결하지 못했다.

아래는2026년 결과별 설명용 분해다. collapsed0=입상41두,1=이탈15두. g3f/g1f는 상대 우위초,risk는이탈확률,brier_difference는이전joint대비차이다. 이 표를 보고 새 조건을 추가하거나 다시 적합하지 않았다.

{table(a26)}

2026년 입상마의G3F/G1F 우위는평균1.307/0.451초,이탈마는1.147/0.244초였다. 종반 기록의 방향상 구분 신호는 관측됐다. 단순동시추가는 입상마·이탈마 양쪽에서 손실을 조금 줄였지만 합산개선CI가0을 포함했고 이전연도는 재현되지 않았다. 관계추가는 이탈마의 평균 위험을30.51→30.44%로 오히려 낮춰,이탈마 손실이 커졌다.

원확률70% 이상이라는 선택된 집단에서는 구간기록이 좋은 말이 이미 많다. 초반/G3F/G1F모두상대보다빠른158/205경주의실제입상은112/158=70.89%였고,그안에서도46두가이탈했다. 초반이빠르면서두종반이모두느린집단은12경주뿐이며10두가입상했다. 이것만으로 느린종반이유리하다는뜻은아니며,거리/전개/편성/기록관측차이가섞인소표본이라 단순 제외규칙의 근거로 쓸 수 없다.

{table(profile_summary)}

## 입력 중복과 관계의 안정성

학습 대상에서G3F와G1F의상관은0.875안팎이고 최근전체기록과종반기록도연관돼있다. 일부 새 정보가 이미recent와원확률에 담겨있을 수 있다. 상관이 높다는 사실만으로 이번 악화의 원인을 확정하지는 않는다. 공동 회귀의 계수는 다른 입력을 고정한 조건부 관계이며 물리적 인과효과가 아니다.

{table(correlations)}

주 후보의종반관련계수는아래와같다. G3F교호항은2024−0.144→2025−0.083→2026+0.006으로방향/크기가안정적이지않았다. G1F교호항도 부호가 바뀌었다. **종반이 빠르면 일관되게 축 위험을 줄여도 된다는 관계는 이 표현에서 확인하지 못했다.**

{table(terms)}

최근3전 전체기록 유효3개·초반/G3F/G1F의5전유효수각3개 이상147경주에서도 이전joint0.211109→단순0.212236→관계0.215513으로 악화됐다. 이 기준은 최근3전 모든 구간이 관측됐다는 보장이 아닌 이력지원 대리 기준이다.

{table(full)}

## 고정한 설명용 예시

원입상75%,초반0.5초상대우위,최근전체기록0.5점으로고정하고종반우위만달리한2026년주후보의예시다. 실제새경주예측이아니다.

{table(examples)}

G1F를같게두고G3F만좋게하면확률이낮아지는예시도나온다. 부호를강제하지않은조건부회귀결과이며 'G3F가빠르면불리하다'는보편규칙으로해석하면안된다. 중첩구간·전체기록과동시조건화한관계가운영에적합한지검증해야한다는신호이고,이번성능도개선을보이지않았다. 결과를보고부호를뒤집거나단조제약을새로적용하지않았다.

## 검증·한계·결정

- [사전 계획](PLAN.md)/코드/원천/운영레지스트리/선택22입력/기존미래검증계약의해시를고정했다. [독립검증](outputs/verification.json)에서12모형학습경계/표준화/교호항/계수최적성/재예측,140지표행,480날짜군집CI행,모든원축·참조확률·대상밖불변,결과/미사용필드변조무영향을확인했다.
- [진단감사](outputs/diagnostic_audit.json)는프로필분류4,799행,조건별지표168행,손실분해60행,예시9개와판정을별도로확인했다. 사후진단에서모형을재적합하지않았다.
- 원모델은2017년이후학습/그이전워밍업기록정의를유지한다.2020~2023원축은기존시간순OOF,2024~2026은기존동결예측이다.위험보정학습은이원장의2020년부터다. 과거이력T−2/730일/실제슬롯을유지했다. 미지원구간보정은기존방식의원초유지다.
- 같은평가기간을반복분석한선택편향,2026년56경주의소표본/부분연도,당일중량공개시각PIT미감사,지역별원모델/온도변경한계를유지한다. 직접기수/현재게이트/당일실제전개/결과입력은없다. 연구자료는2026-09-20종료이며전체DB최신일을확인한것은아니다.
- 과거평균초반+평균종반의관계는 **실제로빠른초반을쓴동일과거경주에서어떻게마무리했는가**를직접학습한것과다르다. 해당상황별지표가더좋을지는이번작업으로알수없다. 종반을고려하는방향전체가틀렸다고결론내리지않는다.
- 이번구간추가후보는유지하되채택하지않는다. DB/네트워크/제주접근,운영교체,이전미래검증계약변경은없다. 웹게시요약을준비했으며배포완료를뜻하지않는다.

[비교원장](outputs/predictions.parquet) · [지표](outputs/quality.csv) · [같은 경주 비교와CI](outputs/paired_differences.csv) · [계수](outputs/coefficients.csv) · [판정](outputs/decision.json) · [게시요약](PUBLICATION.md) · [용량명세](outputs/artifact_inventory.json).

재현순서run.py→verify.py→audit_diagnostics.py→report.py→finalize_inventory.py. run.py는동결출력덮어쓰기를방지하므로별도복제경로에서실행한다.
"""
    (r.HERE / "README.md").write_text(body)
    pub = """# 고확률5등급 축의 초반·종반 보정: 추가 개선 미확인

2026-10-10. 원 입상확률70% 이상인5등급 축205경주에서 초반 상대우위와 최근 전체기록에 G3F(마지막600m)·G1F(마지막200m) 상대기록을 추가했다. 동일 축의 확률 재보정이며 축 선정 적중률은 변하지 않는다.

무엇을 알았는가: 기존 초반+최근기록 보정의 합산 Brier0.200412에 비해 두 종반 단순추가는0.201253,초반 우위와 종반의 관계까지 추가한 주 후보는0.204218이었다. 단순추가가2026년0.199523→0.198819로 조금 나아졌지만2024·2025년은 나빠졌다. 주 후보의합산차이+0.003805,95%CI[+0.001507,+0.006314]로 이번 표본에서는 악화됐다. 기존 일괄보정보다 확실히 나아졌다는 근거도 없다.

어떻게 읽는가: 과거최근3전 보정구간기록을 자기 제외 상대마들과 비교했다. 좋은 종반기록이 실제로 빠른 초반을 쓴 상황의 유지능력을 직접 뜻하지는 않는다. G1F는G3F에 포함되고 기존 전체기록과도 연관되므로 별개의 능력처럼 합산하지 않았다.

사례:2026년 실제 입상마의G3F/G1F 상대우위는1.307/0.451초,이탈마는1.147/0.244초로 종반 구분 신호는 있었다. 그러나 그 신호를 새 보정에 넣은 추가 예측력은 연도별로 재현되지 않았다. 초반·두 종반이모두상대보다빠른158경주에서도46두가이탈해,세 구간기록만으로 안전한 축을 보장하지 못했다.

적용 범위:2024/2025/2026-09-20의71/78/56경주,각연도이전자료만적합했다. 반복후향가설선택이라는한계와2026년소표본을유지한다.12개소형보정·재예측·지표·경주일군집CI·진단표·해시검증완료.대상밖4,594경주·원축·운영·기존미래검증계약은유지한다.후보를채택하지않고기록하며웹사이트게시용요약을준비한단계다.

[원 보고서와 검증](README.md) · [연도별 오차](outputs/quality.csv) · [같은 경주 비교](outputs/paired_differences.csv)
"""
    (r.HERE / "PUBLICATION.md").write_text(pub)
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
    central = r.R / "conclusions/43_GRADE5_FINISH_CORRECTION.md"
    assert not central.exists()
    central.write_text(
        pub.replace("(README.md)", f"(../{r.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{r.HERE.name}/outputs/"
        )
    )
    marker = "<!-- grade5_finish_correction_v1_20261010 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{r.HERE.name}/README.md" if path.parent == r.R else central.name
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[고확률5등급 초반·G3F·G1F 보정]({link}): 대상205경주. 이전 초반+최근 Brier0.200412→종반단순0.201253/관계추가0.204218.2026단순소폭개선은CI0포함,관계추가합산악화,운영 유지.\n"
            )
    r.save(
        r.OUT / "completion.json",
        dict(
            status="complete_verified_published_locally",
            new_models=12,
            target_races=205,
            production_changed=False,
            selected_baseline_changed=False,
            prior_future_contract_changed=False,
            database_access=False,
            network_access=False,
            jeju_access=False,
        ),
    )
    manifest = json.loads(shared[-1].read_text())
    own = sorted(
        p
        for p in r.HERE.rglob("*")
        if p.is_file()
        and "publication_before" not in p.parts
        and "__pycache__" not in p.parts
        and p.name != "publication_before.json"
    )
    for path in own + [central, shared[0], shared[2], shared[3]]:
        name = str(path.relative_to(r.ROOT))
        manifest["sources"] = [row for row in manifest["sources"] if row["path"] != name]
        manifest["sources"].append(dict(path=name, sha256=r.sha(path), bytes=path.stat().st_size))
    r.save(shared[-1], manifest)
    r.check()
    print("Local report and conclusion43 published; late candidates not promoted.")


if __name__ == "__main__":
    main()

"""Publish same-start conditional history research without selecting a new winner."""

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
    for name in ["verification.json", "history_verification.json", "diagnostic_audit.json"]:
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
        "group=='target' and variant=='paired_full' and reference=='joint' and metric=='brier'"
    )
    rate = delta.query(
        "group=='target' and variant=='paired_rate' and reference in ['joint','finish_add'] and metric=='brier'"
    )
    avg_comparison = delta.query(
        "group=='target' and variant=='paired_full' and reference=='finish_add' and metric=='brier'"
    )
    coverage = pd.read_csv(r.OUT / "coverage.csv")
    allocation = pd.read_csv(r.OUT / "outcome_allocation.csv", dtype={"period": str})
    a26 = allocation.query("period=='2026' and variant in ['joint','paired_rate','paired_full']")
    profiles = pd.read_csv(r.OUT / "profiles.csv", dtype={"period": str})
    profile_result = profiles.query(
        "period in ['all','2026'] and variant in ['joint','paired_rate','paired_full']"
    )
    full = q.query("period=='all' and group in ['all','supported_target']")[
        ["group", "variant", "n", "brier", "logloss"]
    ]
    probabilities = target[
        target.variant.isin(["joint", "finish_add", "paired_rate", "paired_full"])
    ][["period", "variant", "n", "mean_top3", "actual_top3", "mean_cut"]]
    body = f"""# 동일한 과거 경주의 빠른 초반 뒤 G3F·G1F 유지 보정

2026-10-10. **같은 과거 출전의 빠른 초반과 종반을 직접 짝지어도, 이번 표현과 보정에서는 기존 방식보다 확실한 개선을 확인하지 못했다.** 유지 기록과 유지율을 함께 넣은 주 후보는 세 연도 모두 기존 초반+최근기록 보정보다 오차가 컸다. 유지율만 넣은 후보는2026년 소폭 개선됐지만2024·2025년과 합산에서는 나빠졌다. 후보를 운영에 반영하지 않는다.

## 대상과 비교

원22입력 연구 모델의 입상확률70% 이상인5등급 축205경주를 그대로 비교했다.2024/2025/2026-09-20까지71/78/56경주다. 전체4,799경주의 모든 원축이 동일하고,대상밖4,594경주 확률은 원확률 그대로다. 실제 대상축 입상은142/205=69.27%,전체는2,862/4,799=59.64%로 변하지 않는다. 같은 축의 입상확률 보정 시험이며,축 선정·후속 후보·조합을 바꾸는 시험은 아니다.

기존 비교군은 [43번 연구](../20261010_grade5_finish_correction_v1/README.md)의 원장을 재사용했다. raw=원확률,constant=일괄보정,joint=초반 상대우위+최근 전체기록,finish_add=평균G3F·G1F 추가,finish_interaction=평균종반과 초반의 관계까지 추가다. 주 비교는 새paired_full과 이전joint이며,평균종반 방식 및 일괄/원확률도 모두 비교했다.

## 같은 과거 경주를 어떻게 묶었는가

1. 당시 출전의 초반200m/G3F600m/G1F200m 보정초를 모두 동일race_key·horse_id로 묶었다. 그 경주의 자기 제외 상대평균−자신의 기록을 상대우위초로 정의했다. 양수면 빠르다.
2. 세 구간 각각 유효 상대5두 이상이고 해당 구간 관측두수/당시두수≥80%일 때만 전체 짝을 유효로 인정했다. 계산 오차로0초의 분류가 바뀌지 않도록 차이는 소수점10자리로 반올림했다.
3. 초반 우위>0이면 '빠른 초반 경험', 그 출전에서G3F우위≥0이면서G1F우위≥0이면 '두 종반 유지'로 기록했다. 통과착순 선행을 의미하지 않는다. 기준은 **당시 상대 평균보다 초반이 빨랐는가**이며 말이 평소보다 얼마나 힘을 더 썼는지나 생리적 소모량은 미측정이다.
4. 현재 축의T−2까지,730일 내 최근 실제5전 안에서만 합산했다. 미관측·부진 출전을 건너뛰어 유효 기록5개를 채우지 않았다. 같은 출전의 초반과 종반으로 계산한 값이며 서로 다른 경주의 최고기록을 조합한 값이 아니다.

새 입력은 빠른 초반 경험수fast_n,세 구간 유효출전수valid_n,빠른 초반을 썼던 출전들의G3F/G1F 평균 상대우위,두 종반 유지율이다. 기록평균은n/(n+3)으로0초 쪽에 수축했고,유지율은(유지횟수+1)/(경험수+2)로0.5 쪽에 수축했다. 경험0회면 세 유지지표는 결측으로 표시했고 횟수는 실제0이다. 관측 부족을 좋은 유지나 나쁜 유지로 임의 분류하지 않았다.

G1F는G3F에 포함된다. 공동 회귀와 규제로 중첩 구간을 함께 다루며 두 개의 독립 능력을 합산하지 않는다. 그 당시 편성 대비 유지 기록이므로,현재 상대/거리/경합 강도에서도 같은 능력을 보장하는 값은 아니다. 과거 입상/최종착순은 새 지표에 사용하지 않았다.

## 고정 후보와 학습

- paired_times: 기존early/recent+짝지은G3F/G1F 유지기록+fast_n/valid_n.
- paired_rate: 기존early/recent+짝지은 두 종반 유지율+fast_n/valid_n.
- paired_full(주 후보): 위 유지기록·유지율·두 관측수를 모두 사용.

평가Y년의2020~Y−1 대상만 학습했다.2024년용388/2025년용459/2026년용537경주다. 평균과 모집단 표준편차는 학습 대상에서만 계산했다. 원이탈확률logit에 절편/표준화입력/결측표시를 더했고,입력은±3 절단,모든 계수L2=10,BFGS초기0/gtol1e-7/maxiter1000으로 고정했다. 부호 강제·감점하한·결과 후 규제탐색 없이 신규 소형보정9개를 학습했다. 새 말 능력모형0개,원2017년 학습/이전 워밍업 체계는 유지했다.

## 연도별 결과

Brier는(예측입상확률−실제입상여부)²의 평균으로 **작을수록 좋다.** 적중률(%)이 아니며 이탈확률로 계산해도 같다.

{table(brier)}

주 후보의 합산 Brier는 이전joint0.200412→0.204635로 약2.11% 악화됐다. 평균종반을 추가한finish_add0.201253보다도 나빴다.2026년은joint0.199523→paired_full0.209416으로 악화가 컸다. 유지율만의paired_rate는2026년0.198676으로 조금 좋아졌지만 기존일괄0.196698/원확률0.194464를 넘지 못했다. 합산에서 세 새 후보 모두 기존joint나finish_add를 넘지 못했고,결과 후 최상의 새 후보를 골라 채택하지 않았다.

주 후보−joint의 paired 경주일 군집 bootstrap2,000회seed441010,95%CI다. 음수면 개선이다.

{table(primary[["period", "n", "difference", "low", "high"]])}

합산차이+0.004223,95%CI[-0.004397,+0.013910]는0을 포함한다. 점추정은 악화됐지만 통계적으로 악화가 확정됐다고 표현하지 않는다. '합산CI상한<0이고세연도모두개선'이라는 계획상 조건도 충족하지 않는다. 조건 선택에2024~2026 분석 결과를 이미 본 반복 후향 연구로,시간순 계산이어도 새 독립 확증 검증은 아니다.

기존 평균종반 방식 대비 주 후보의 결과도 보존했다.

{table(avg_comparison[["period", "n", "difference", "low", "high"]])}

유지율만의 작은2026년 개선도CI가0을 포함한다.

{table(rate[["period", "reference", "n", "difference", "low", "high"]])}

## 짝지은 경험의 관측 범위

history_observations326,327행과구간observations159,014행,기존연도별보정원장을읽었다. 원고확률5등급의2020~2026대상593개 축에 대해실제과거슬롯1,924개를묶었고고유과거출전문맥1,737개를독립검증했다. 단순원천복제를새산출물로중복보관하지않았다. 구간미관측이거나보정미지원인슬롯도그대로보존했다. 보정지원이없으면기존원초를사용했다.

{table(coverage)}

평가205경주 중빠른초반경험0회17경주,1회36경주,2회이상152경주다.경험2회이상대상에서도기존joint0.194797→paired_full0.199871로악화됐고paired_rate0.195106도기존을넘지못했다.이번전체결과를경험부족만으로설명할수없다.

{table(full)}

## 유지율 신호와 실제 입상

사전에 고정한 설명 분류다. supported_high_retention은fast_n≥2이며수축유지율≥0.5,supported_low_retention은fast_n≥2이며그미만이다. 경험0/1회는따로표시했다. 이분류를보고새임계값이나새계수를재탐색하지않았다.

{table(profile_result)}

유지율높은집단131경주의실제입상은95/131=72.52%,낮은집단21경주는13/21=61.90%였다. 방향상관측신호는있지만낮은집단21경주뿐이고,그차이가기존확률을넘는안정적추가예측력을뜻하지는않는다. 유지율을높게본집단에서도36두가이탈했다. 동일표본의조건별성적을새독립확률로바로사용하지않는다.

## 2026년에 어디서 손해가 났는가

아래는결과를본뒤의설명용분해다. collapsed0=실제입상41두,1=이탈15두. paired_g3/paired_g1은조건부평균우위를수축한초,risk는이탈확률,brier_difference는기존joint대비손실차이다.

{table(a26)}

2026년주후보는실제이탈마의평균위험을30.51→31.49%로높여이탈마손실합을0.175108줄였다. 그러나실제입상마의평균위험도29.99→31.84%로높여입상마손실합이0.729136늘었다. 일부이탈마를더경계했지만입상마를과하게깎은손해가더컸다. 유지율만후보는이탈마손실합0.300884감소/입상마0.253454증가로작은순개선이있었으나2024·2025년에재현되지않았다.

## 평균 예측확률

mean_top3/actual_top3는예측/실제입상,mean_cut은원확률대비감점,모두0~1단위다.

{table(probabilities)}

주후보의전체평균입상예측68.88%는실제69.27%와가깝지만,이전joint68.41%보다개별경주오차가컸다. 유지율만후보는전체평균69.28%로실제와거의같아도Brier는기존보다나빴다. 평균을맞추는것과이탈할개별축을구분하는능력은별도로검증해야한다.

## 검증과 결정

- [학습/예측독립검증](outputs/verification.json):9모형의시간순학습/표준화/계수최적성/저장예측,160지표행,600pairedCI행,모든원축/참조확률/대상밖불변,현재결과/미사용필드변조무영향확인.
- [동일출전이력독립검증](outputs/history_verification.json):593축의실제5슬롯재구성,1,924슬롯의동일출전짝/자기제외평균/80%관측조건/보정지원/T−2/730일/결측슬롯미건너뛰기/수축지표를확인했다. G3F와G1F가초반과다른출전에서가져온값이아님을검증했다.
- [진단감사](outputs/diagnostic_audit.json):조건별지표와결과별손실분해·판정을독립계산했고재학습하지않았다. [고정계획](PLAN.md),builder/학습/검증코드·원천·운영레지스트리·선택22입력·이전미래검증계약해시를보존했다.
- 반복후향조건선택,2026년56경주소표본/부분연도,당일중량공개시각PIT미감사,연도별원모형/온도변경한계를유지한다. 구간관측은2018년부터이고이전/미관측은결측이다. 빠른초반은당시상대대비정의며평소대비추가소모나같은절대페이스/작전을측정한것은아니다.
- 새지표는원천에있는기록으로만구성했다. 기수·직접현재게이트·심판기록·당일실제전개·최종결과를추가입력하지않았다. 자료종료일은2026-09-20이며프로젝트전체DB의최신일을확인한것은아니다.
- **이번표현의조건부유지기록은채택하지않는다.** 모든종반유지가설이틀렸다는판정이아니며이방법의추가효과미확인이다. 운영/DB/제주/이전미래검증계약변경없다. 게시용요약을준비했으며웹배포완료가아니다.

[같은출전슬롯원장](outputs/paired_history_slots.parquet) · [조건부유지입력](outputs/paired_features.parquet) · [비교예측](outputs/predictions.parquet) · [지표](outputs/quality.csv) · [같은경주손실차와CI](outputs/paired_differences.csv) · [계수](outputs/coefficients.csv) · [게시요약](PUBLICATION.md) · [용량명세](outputs/artifact_inventory.json).

재현순서는run.py→verify_history.py→verify.py→audit_diagnostics.py→report.py→finalize_inventory.py다. 동결산출물덮어쓰기를막으므로재실행은별도복제경로가필요하다.
"""
    (r.HERE / "README.md").write_text(body)
    pub = """# 같은 과거 경주의 빠른 초반 뒤 종반 유지: 추가 개선 미확인

2026-10-10. 원 입상확률70% 이상인5등급 축205경주에 대해,같은 과거 출전의 빠른 초반과G3F·G1F를 짝지어 보정했다. 기존 평균구간 방식보다 안정적으로 좋아지지는 않았다.

무엇을 알았는가: 주 후보(조건부G3F·G1F 유지기록+유지율)의 Brier는2024년0.197166/2025년0.208002/2026년0.209416이었다. 기존 초반+최근기록은각0.195147/0.205844/0.199523,평균종반추가는0.196790/0.207063/0.198819이었다. 합산주후보0.204635는기존초반+최근0.200412보다나빴고차이95%CI[-0.004397,+0.013910]로개선근거없다.유지율만후보는2026년에조금좋아졌지만2024·2025년과전체에서는나빠졌다.

어떻게 읽는가: 당시같은경주상대평균보다초반200m가빠른출전을고르고,그출전에서마지막600m/200m도상대평균이상이었는지계산했다.현재축의T−2/730일내최근실제5전에서만모았고결측출전을건너뛰지않았다.각구간상대5두이상/관측80%조건과소표본수축을적용했다.과거통과착순선행이나생리적추가소모를직접측정한지표는아니다.

사례: 빠른초반경험2회이상·유지율절반이상131경주는실제입상72.52%,유지율절반미만21경주는61.90%였다.관측신호는있으나기존예측을넘는추가효과는확인하지못했다.2026년주후보는이탈마손실을줄였지만실제입상마까지과하게감점한손해가더컸다.

적용 범위:2024/2025/2026-09-20의71/78/56경주.각연도이전자료만적합했고,593축·1924과거슬롯의동일출전짝/관측조건/시점,9모형·재예측·지표·날짜군집CI를검증했다.반복후향선택편향/2026년소표본한계유지.축동일로적중률불변,대상밖4594경주·운영·이전미래검증계약유지.연구후보를채택하지않고웹게시요약을준비한단계다.

[원 보고서와 검증](README.md) · [연도별 지표](outputs/quality.csv) · [같은 출전 슬롯](outputs/paired_history_slots.parquet)
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
    central = r.R / "conclusions/44_GRADE5_PAIRED_FINISH.md"
    assert not central.exists()
    central.write_text(
        pub.replace("(README.md)", f"(../{r.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{r.HERE.name}/outputs/"
        )
    )
    marker = "<!-- grade5_paired_finish_v1_20261010 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{r.HERE.name}/README.md" if path.parent == r.R else central.name
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[고확률5등급 동일출전 초반·종반 유지 보정]({link}): 대상205경주/593축의과거1924슬롯검증.합산Brier기존0.200412→조건부유지0.204635,세연도점추정악화/CI0포함,유지율만2026소폭개선은미재현.운영 유지.\n"
            )
    r.save(
        r.OUT / "completion.json",
        dict(
            status="complete_verified_published_locally",
            new_models=9,
            target_races=205,
            actual_slots=1924,
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
    print("Local report and conclusion44 published; paired candidates not promoted.")


if __name__ == "__main__":
    main()

"""Local results and runner-level G3F/G1F evidence; no web/DB mutation."""
# ruff: noqa: E501

import json
from pathlib import Path

import pandas as pd
import run as E

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
ORDER = ["style_history", *E.CONFIG["variants"]]
NAMES = {
    "style_history": "기존53개",
    "gate_front67": "방향별게이트·선행예측",
    "role_late89": "조건부종반·편성비교",
    "full103": "게이트·선행·종반전체",
}
LABELS = {
    "axis_top3": "축3위이내",
    "top5_all": "상위5두입상3두포괄",
    "axis_top2": "축2위이내",
    "top6_all": "상위6두포괄",
    "top3_all": "상위3두전부입상",
    "quinella_one": "복승1조합",
    "axis_next3": "축복승3조합",
    "target_brier": "입상Brier",
    "set_logloss": "조합NLL",
}


def cell(value, digits=2):
    return "미관측" if pd.isna(value) else f"{value:.{digits}f}"


def record(row, role, phase):
    value = row[f"rolelate_{role}_{phase}_mean5"]
    n = row[f"rolelate_{role}_{phase}_n5"]
    return f"{cell(value)} ({int(n)}회)"


def event(row, phase):
    value = row[f"rolelate_nonfront_{phase}_pass_mean5"]
    n = int(row[f"rolelate_nonfront_{phase}_pass_n5"])
    return "미관측" if pd.isna(value) else f"{value * 100:.0f}% ({n}회)"


def main():
    E.check_inputs()
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["passed"]
    metrics = pd.read_csv(OUT / "metrics.csv")
    differences = json.loads((OUT / "paired_differences.json").read_text())
    front = json.loads((OUT / "front_comparison.json").read_text())
    contracts = json.loads((OUT / "feature_contract.json").read_text())
    example = pd.read_csv(OUT / "example_card.csv")
    counts = pd.read_csv(OUT / "coverage.csv")
    runners = pd.read_parquet(OUT / "runner_predictions.parquet").sort_values(
        ["variant", "race_key", "raw_score", "program_no"], ascending=[True, True, False, True]
    )
    runners["prediction_rank"] = runners.groupby(["variant", "race_key"]).cumcount() + 1
    keys = ["race_key", "program_no", "horse_id"]
    baseline = runners[runners.variant.eq("style_history")][keys + ["prediction_rank"]]
    capture = []
    for variant in E.CONFIG["variants"]:
        g = runners[runners.variant.eq(variant)].merge(
            baseline, on=keys, suffixes=("", "_base"), validate="one_to_one"
        )
        actual = g.outcome.between(1, 3)
        rescued = int((actual & g.prediction_rank_base.gt(5) & g.prediction_rank.le(5)).sum())
        lost = int((actual & g.prediction_rank_base.le(5) & g.prediction_rank.gt(5)).sum())
        capture.append(
            dict(
                variant=variant,
                rescued_into5=rescued,
                lost_from5=lost,
                net_podium_horses=rescued - lost,
            )
        )
    pd.DataFrame(capture).to_csv(OUT / "outsider_capture.csv", index=False)
    text = [
        "# 이번 게이트·선행 유지·종반 역전 능력의 추가 검증",
        "",
        "2026-10-09. 서울·부산 연구 후보. 현재 선택22개/운영/DB/웹 변경 없음.",
        "",
        "게이트 안팎의 빠른 말과 선행성향을 입력하고 시간순으로 초반 첫마군 확률을 예측했다. 최근5실제슬롯 중 선행했던 경우와 비선행했던 경우의 G3F(마지막600m),G1F(마지막200m)를 나누고, 같은 과거경주의 상대기록·공식통과순위·최종착순으로 유지/실제추월 이력을 만들었다. 이번 편성의 예상선행마와 후발마의 종반기록 관계도 각각 입력했다.",
        "",
        "## 같은4,799경주의 최종입상 결과",
        "",
        "2024-01-05~2026-09-20,50,754출전.2026부분. 축은3위이내확률1순위,복승1조합은1·2순위,축복승3조합은1순위와2/3/4순위다. 상위5두포괄은입상3두를전부후보안에넣었는지이며구매조합적중률이아니다.",
        "",
        "| 후보 | 입력수 | 축3위이내 | 상위5두입상3두포괄 | 축2위이내 | 복승1조합 | 축복승3조합 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for variant in ORDER:
        g = metrics[metrics.scope.eq("all") & metrics.variant.eq(variant)].iloc[0]
        vals = [
            f"{g[m] * 100:.2f}%"
            for m in ["axis_top3", "top5_all", "axis_top2", "quinella_one", "axis_next3"]
        ]
        text.append(f"|{NAMES[variant]}|{len(contracts[variant])}|" + "|".join(vals) + "|")
    text += [
        "",
        "## 결과 해석",
        "",
        "게이트를추가한선행보조모형의Brier는0.147864→0.141810으로낮아졌고차이95%구간[−0.006775,−0.005376]은개선방향이었다. 반면선행1순위첫마군적중68.12→69.10%의차이구간은−0.06~+2.00%p라불확실했다. 선행확률품질과최종입상선택은구분한다.",
        "",
        "전체103개의축3위이내61.26→60.47%,상위5두포괄32.03→32.86%는각각차이구간−1.75~+0.16%p,−0.12~+1.83%p로향상을확정하지못했다. 축2위이내는48.97→47.51%(−70경주),차이−1.46%p[−2.44,−0.53]로탐색적비교에서저하우려가남았다. 현재선택22개/운영을유지하고새후보를자동채택하지않는다.",
        "",
        "전체추가에서기존5순위밖입상마635두를새로포착했지만기존안입상마618두를놓쳐포착마순증은17두였다. 입상3두전부포괄은40경주증가했으나축선정까지동시에개선하지는못했다. 가설의실현가능성과이번입력구성의성능은별도판단이다. 기존53개도운영승격된모델이아닌연구비교군이다.",
        "",
    ]
    text += [
        "",
        "## 동일경주 차이",
        "",
        "날짜단위paired bootstrap2,000회95%구간. 여러후보/지표를보정하지않은탐색적결과이며기존연구에서반복사용한과거기간이다.0을포함하면개선방향을확정하지않는다.자동승격없음.",
        "",
        "| 후보 | 지표 | 차이%p | 95%구간%p |",
        "|---|---|---:|---:|",
    ]
    for row in differences:
        if row["period"] == "all" and row["metric"] not in ["target_brier", "set_logloss"]:
            lo, hi = row["interval95"]
            text.append(
                f"|{NAMES[row['variant']]}|{LABELS[row['metric']]}|{row['difference']:+.2f}|{lo:+.2f}~{hi:+.2f}|"
            )
    text += [
        "",
        "## 게이트가 초반 선행 예측에 도움이 됐는가",
        "",
        "선행은S1F통과조의첫마군전원이다. 단독선두·결승승리·순수출발반응시간을뜻하지않는다. 기준53개보조모형과방향별게이트를더한65개보조모형을동일고정180회설정으로따로비교했다.2020~2026각예측연도이전자료만학습했고주모형훈련행에도자기연도정답으로학습한확률을넣지않았다. 모델의선행확률은입상확률과다르고,첫마군복수가능성이있어경주합을1로강제하지않았다.",
        "",
        "공식초반각질이전원유효한경주만선행정답평가에사용했고,이결측제외는최종입상4,799경주평가에는적용하지않았다.",
        "",
        "| 지표 | 평가경주 | 기준53 | 게이트65 | 차이 | 95%구간 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in front:
        lo, hi = row["interval95"]
        percent = row["metric"] == "first_front"
        label = "선행예측1순위가실제첫마군" if percent else "선행Brier(낮을수록좋음)"
        scale = 100 if percent else 1
        text.append(
            f"|{label}|{row['races']}|{row['baseline'] * scale:.4f}|{row['gate'] * scale:.4f}|{row['difference']:+.4f}|{lo:+.4f}~{hi:+.4f}|"
        )
    text += [
        "",
        "## 개별마 평가표 예시",
        "",
        f"고정규칙으로선택한마지막평가카드 `{example.race_key.iloc[0]}`. 결과로사례를선택하지않았다. 과거카드의T−2이력기반표이며오늘실시간출마표/추천이아니다. 확률은별도선행보조모형의출력이다. 기록은최근5실제출전중각전개에서관측한보정초평균이고괄호는관측회수다. 원초유지구간이섞일수있고과거거리구성/초반페이스가완전히같지않아초차만으로능력을확정하지않는다.",
        "",
        "| 마번 | 마명 | 선행예측% | 선행시G3F | 선행시G1F | 비선행시G3F | 비선행시G1F |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for _, row in example.iterrows():
        name = str(row.horse_name).replace("|", "\\|").replace("\n", " ")
        text.append(
            f"|{row.program_no}|{name}|{row.front_gate_probability * 100:.1f}|{record(row, 'front', 'g3f')}|{record(row, 'front', 'g1f')}|{record(row, 'nonfront', 'g3f')}|{record(row, 'nonfront', 'g1f')}|"
        )
    text += [
        "",
        "예상선행마의종반평균과자기비선행시종반의차이는양수면자기가빠른방향이다. 양구간모두빠른상대를같은마필끼리비교했다. 위협수/우위수는상대선행·비선행확률로가중한수치이며실제마필수나역전확률이아니다. 조건부기록미지원은일반최근3평균으로보완한상대관계가있으므로위표의지원수와함께읽는다.",
        "",
        "| 마번 | 예상선행마대비G3F우위초 | 예상선행마대비G1F우위초 | 선행시양구간빠른후발위협량 | 비선행시양구간빠른선행상대량 | 과거G3F뒤→선행마추월 | 과거G1F뒤→선행마추월 |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in example.iterrows():
        text.append(
            f"|{row.program_no}|{cell(row.relate_own_nonfront_g3f_adv)}|{cell(row.relate_own_nonfront_g1f_adv)}|{cell(row.relate_nonfront_threat_both_mass)}|{cell(row.relate_own_catch_both_mass)}|{event(row, 'g3f')}|{event(row, 'g1f')}|"
        )
    text += [
        "",
        "과거추월사건은그구간에서자기보다앞에있던S1F첫마군말을결승에서적어도한두넘어선경우다. 모든선행마를넘거나우승했다는뜻이아니다. 앞선선행마가없거나통과순위/정상결승이미지원이면실패0대신미관측이다. G3F와G1F의대상상대가다를수있다.",
        "",
        "이번경주의600m전/200m전시간차는사전에관측되지않았다. 따라서종반우위가있어도이번에반드시역전할정도의차이라는결론은내리지않는다. 초반소모·위치차·진로·실제내외측주행을포함한물리시뮬레이션도아니다. 과거실제추월근거와이번편성상대기록을설명변수로학습한실험이다.",
        "",
        "## 지원과해석",
        "",
        "| 지역 | 평가출전수 | 선행시G3F이력지원 | 비선행시G3F이력지원 | G3F추월기회이력 | G1F추월기회이력 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for meet, g in counts[counts.year.ge(2024)].groupby("meet"):
        text.append(
            f"|{'서울' if meet == 1 else '부산'}|{g.rows.sum()}|{g.front_history.sum()}|{g.nonfront_history.sum()}|{g.g3f_pass_history.sum()}|{g.g1f_pass_history.sum()}|"
        )
    text += [
        "",
        "- G3F는마지막600m,G1F는마지막200m이며시간이겹친다. 별개입력으로사용하고초를더하거나두독립성공확률로곱하지않는다.",
        "- 현재마번은게이트대리변수다. 취소로생긴번호공백은보존했다. 실제주행레일·경로·내외측압박의정답이아니다. 과거기록의게이트보정과이번게이트의전개입력은별도단계다.",
        "- 89개후보의편성종반관계에도시간순게이트선행확률이가중치로간접사용된다. 따라서89개후보를게이트정보없는순수종반단독효과로해석하지않는다. 선행보조확률은고정이진모형의출력으로별도확률교정을하지않았다.",
        "- 선행시기록이미관측인말을선행해도못버티는말로확정하지않는다. 과거역전빈도는최근5슬롯의작은지원수일수있고이번역전확률이아니다. 서로다른과거거리/편성/페이스를평균한절대초비교에는잔여혼합이있고같은과거경주상대우위입력도별도로보존했다.",
        "- 실제초반선행과최종성적의관측관계는컨디션·상대능력에함께영향받을수있다. 원인효과/최적작전/체력소진을확정하지않는다. 사전공개시각미감사/부분2026/후향기간재사용/다중비교미보정의기존한계를유지한다.",
        "",
        "## 재현검증",
        "",
        f"검증통과. 신규입상모형{verification['finish_models_replayed']}개와시간순선행모형{verification['front_models_replayed']}개재추론,원점수최대오차{verification['max_score_error']}. 기존53개불변,현재정답변조불변,이력마필/시점/730일,독립방향별상대수/과거추월사건,축/복승/포괄/확률재계산,원천·운영해시를확인했다. 운영승격없음.",
        "",
        "[사전계획](PLAN.md) · [전체입력](outputs/feature_contract.json) · [경주별결과](outputs/race_diagnostics.csv) · [같은경주차이](outputs/paired_differences.json) · [선행예측비교](outputs/front_comparison.json) · [말별예시](outputs/example_card.csv) · [전체평가마프로필](outputs/runner_profiles.parquet) · [과거전개별원장](outputs/history_events.parquet) · [검증](outputs/verification.json).",
        "",
        "```sh",
        ".venv/bin/python thoroughbred/research/20261009_gate_front_late_v1/run.py prepare",
        ".venv/bin/python thoroughbred/research/20261009_gate_front_late_v1/run.py front_stack",
        ".venv/bin/python thoroughbred/research/20261009_gate_front_late_v1/run.py finish_features",
        ".venv/bin/python thoroughbred/research/20261009_gate_front_late_v1/run.py train",
        ".venv/bin/python thoroughbred/research/20261009_gate_front_late_v1/run.py analyze",
        ".venv/bin/python thoroughbred/research/20261009_gate_front_late_v1/run.py verify",
        ".venv/bin/python thoroughbred/research/20261009_gate_front_late_v1/report.py",
        "```",
        "",
    ]
    (HERE / "README.md").write_text("\n".join(text))
    files = [
        p
        for p in sorted(HERE.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.name != "artifact_inventory.json"
    ]
    items = [
        dict(path=str(p.relative_to(HERE)), bytes=p.stat().st_size, sha256=E.sha(p)) for p in files
    ]
    inventory = OUT / "artifact_inventory.json"
    others, own = sum(p.stat().st_size for p in files), 0
    for _ in range(12):
        E.save(
            inventory,
            dict(
                files=len(files) + 1,
                bytes=others + own,
                mib=(others + own) / 1048576,
                self_hash_omitted=True,
                items=items
                + [dict(path="outputs/artifact_inventory.json", bytes=own, sha256=None)],
            ),
        )
        actual = inventory.stat().st_size
        if actual == own:
            break
        own = actual
    else:
        raise AssertionError("Inventory self-size did not converge")
    print("Report saved", HERE / "README.md")


if __name__ == "__main__":
    main()

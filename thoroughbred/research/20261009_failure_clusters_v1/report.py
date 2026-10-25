"""Preserve findings and publish a local research summary, without promotion."""

# ruff: noqa: E501

import json

import pandas as pd
import run as e


def table(frame):
    def cell(value):
        return f"{value:.4f}" if isinstance(value, float) else str(value)

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
    for name in ["verification.json", "independent_checks.json"]:
        assert json.loads((e.OUT / name).read_text())["status"] == "passed"
    assert not (e.HERE / "README.md").exists()
    races = pd.read_parquet(e.OUT / "clustered_races.parquet")
    runner = pd.read_csv(e.OUT / "runner_condition_summary.csv")
    race_summary = pd.read_csv(e.OUT / "race_condition_summary.csv")
    linkage = json.loads((e.OUT / "failure_linkage.json").read_text())
    selected = json.loads((e.OUT / "selected_conditions.json").read_text())["conditions"]
    primary = runner[
        runner.condition.eq("late_both_topthird & recover_often") & runner.period.eq("2025_2026")
    ].iloc[0]
    failures = races[races.trio_fail.eq(1)]
    outside = int(failures.outside5_count.ge(1).sum())
    counts = failures.failure_kind.value_counts().rename_axis("실패구분").reset_index(name="races")
    rules = runner[runner.period.eq("2025_2026") & runner.condition.isin(selected)]
    periods = runner[
        runner.condition.eq(primary.condition) & runner.period.isin(["2025", "2026", "2025_2026"])
    ]
    fields = race_summary[
        race_summary.period.eq("all") & race_summary.condition.str.startswith("field_band_")
    ].sort_values("races")
    body = f"""# 실패 경주와 낮게 평가한 입상마의 조건 군집

2026-10-09. 더러브랫 **선택 연구모델22입력 month_gate_weight22**의 동결2024~2026년 **{len(races):,}경주**, {races.race_date.min()}~{races.race_date.max()}를 조사했다. 주 지표는 삼복 확률순6조합(global6) 실패이며 복승·복연6조합을 보조 비교한다. 포함3+제외3 정책이나 운영ABC 모델 결과가 아니다. 원래 축을 강제하지 않는다. 전체5만754출전 중 예측6위이하2만6,759출전을 비교했다.

## 확인한 내용

실패가 한 군집에만 모이지는 않았다. 다만 **낮게 평가된 말 중 과거 G3F·G1F가 모두 상대적으로 좋고, 후반 순위 회복 이력도 잦은 경우**에 입상 과소평가가2025·2026년 모두 남았다.2024년 조건을 찾고 정의를 고정해 확인한 결과다. 반면 다두수·낮은축확률 경주의 높은 실패율은 모델도 상당 부분 예상했다. 단순히 어려운 편성과 모델이 추가로 놓치는 신호를 구분해야 한다.

## 실패 구조

전체{len(races):,}경주 중 삼복적중1,228, 실패{len(failures):,}다. 실패 중 **{outside:,}경주/{len(failures):,} = {outside / len(failures) * 100:.2f}%**에서 실제 입상마가 예측5위 밖에 있었다. 예측5위밖 말이2두 이상인 경주는959개, 입상3두가 모두5위안인데6조합에 빠진 경주는440개다. 축 자체가 입상하지 못한 실패경주는1,886개다. 축붕괴율과 외부입상마비율은 중복될 수 있다.

{table(counts)}

이는 상위5두 안에서 조합만 바꾸는 방식의 한계를 보여준다. 다만 global6은 순위6이하를 포함할 수도 있으므로 ‘5위밖 입상=무조건 실패’로 정의하지 않았다. 위 분해는 **실제로 실패한 경주**에서 계산했다.

## 가장 반복된 후순위 조건

비교대상은 예측6위 이하 전체다. 입상한 말만 모아 공통점을 찾지 않았다.

- G3F·G1F: 과거 최근3전 평균600m·200m 기록이 **각각 이번 편성의 말들 중 빠른 상위 약1/3**, 최근5전 각 구간 유효관측3회 이상이다. 지원되는 과거 기록에는 기존 구간 주로·월·게이트 보정이 포함된다. 결측을 제외한 평균순위 백분율>=2/3라 경계 동률은 포함한다.
- 회복: 과거 남은600m 지점에서 상대순위>=0.5인 말이 결승까지 상대순위를0.25 이상 회복한 표식이다. 상대순위는 두수에 따라 정규화된 값으로 고정3등 상승이라는 뜻이 아니다. 최근5전 유효관측3회 이상, 회복표식 평균>=0.4를 사용한다. 현재 경주의 회복이나 착순을 입력하지 않았다.

{table(periods[["period", "runners", "actual_top3", "actual_rate", "predicted_rate", "excess", "excess_difference_ci_low", "excess_difference_ci_high"]])}

2025~2026년 **{int(primary.runners):,}출전/{int(primary.actual_top3):,}입상**, 실제입상률 **{primary.actual_rate * 100:.2f}%**, 평균모델입상확률 **{primary.predicted_rate * 100:.2f}%**, 차이 **{primary.excess * 100:+.2f}%p**다. 여기서 모델입상확률은 기존 삼복3두 공동분포를 주변화한 합계3의 확률이다. 원시LightGBM 점수나 승률과 다르다.

조건없는 후순위 대조군과의 ‘실제−예측’ 차이는 **{primary.excess_difference * 100:+.2f}%p**, 날짜군집bootstrap95%구간 **{primary.excess_difference_ci_low * 100:+.2f}~{primary.excess_difference_ci_high * 100:+.2f}%p**다. 표의CI는 이 대조차이에 대한 구간이며 해당 조건 자체의 실제입상률CI가 아니다.2025년과2026년 각 구간도0보다 높았다.

연도·지역·거리대·등급대·두수대·예측순위대를 맞춘 공통셀에서는 비교가능 **{int(primary.matched_runners):,}출전**의 실제입상률 **{primary.matched_actual_rate * 100:.2f}%**, 같은 셀구성으로 표준화한 비조건 대조군 **{primary.matched_control_rate * 100:.2f}%**, 차이 **{primary.matched_difference * 100:+.2f}%p**였다. 셀별 조건말·비조건말 각각3출전 이상을 요구했고 지지표본밖119출전은 이 표준화 비교에서 제외했다. 모델확률을 정확히 일치시킨 비교나 인과효과 추정은 아니다.

해당349입상출전 중 실제 삼복실패경주에 나온 입상마는 **{linkage["winners_in_failed_races"]}출전**, 이를 포함한 실패경주는 **{linkage["failed_races_with_condition_winner"]}개**였다. 전체실패를 전부 설명하지 않는다. 기존53입력 후보가 이349두 중106두를 예측5위안으로 올렸지만, 해당 조건의 실제실패경주 중 후보53이 삼복을 맞힌 수는 {linkage["condition_failed_races_rescued53"]}개였다. 말순위 개선과 최종6조합 적중 개선은 다른 지표다.

## 다른 조건과의 관계

{table(rules[["condition", "runners", "actual_top3", "actual_rate", "predicted_rate", "excess_difference", "excess_difference_ci_low", "excess_difference_ci_high", "matched_difference"]])}

‘최근기록향상+회복’도 후속연도 합산에서는 양수였지만2025년 개별구간은0을 포함했다. ‘최고기록+종반’의 차이는2026년에 집중됐다. 회복 이력만 있는 경우 합산 대조차이의CI가0을 포함했다. 따라서 **모든 추입마가 저평가됐다**고 해석하거나 표의 겹치는 조건 효과를 더하면 안 된다.

최근향상은 보정 전체기록 지수의 최근3전−그이전3전>=0.5다. 최고기록은 최근5전 최고보정지수의 편성 내 상위약1/3/유효3전 이상이다. 등급·거리대별 교차표는 추가 설명통계로 저장했으며 그 결과를 보고 조건을 바꾸지 않았다.

## 실패가 많은 경주의 특징

{table(fields[["condition", "races", "trio_failure_rate", "expected_trio_failure", "qpl_failure_rate", "quinella_failure_rate"]])}

6~9두 삼복실패62.66%,10~11두75.78%,12두이상81.24%다. 복연실패도21.08%→33.47%→40.74%, 복승실패44.76%→57.89%→65.23%로 증가한다. 하지만 삼복예상실패도64.49%→75.03%→83.10%로 증가한다. 모델의 두수별 위험인식이 완전히 빠졌다고 볼 수 없다.

축입상확률<50%인815경주의 삼복실패는86.50%, 예상실패86.79%였다. 경력2전이하 말이25%이상인 편성의 실패73.77%는 그러한 말이 없는 편성75.10%보다 높지 않았다.6등급71.10%,5등급75.46%,1~4등급75.63%로, 이 표본에서 신마·6등급이 항상 더 실패한다는 가설은 지지되지 않았다. 두수 등 구성이 다른 원시비율이므로 등급의 인과적 난도로 해석하지 않는다.

2024년 사전정보만 적합한 경주4군집과 후순위말5군집을2025~2026년에 적용했지만, **실제−예상 실패/입상에서 뚜렷한 양의 추가누락을 보인 군집은95%구간 기준 확인되지 않았다.** 후순위 cluster0은 오히려 모델이 입상을 높게 봤다. 큰 군집으로 모든 실패를 설명하기보다 구간기록과 회복의 교집합이 이번 분석에서는 더 구체적인 신호였다.

## 검증·한계·다음 적용 후보

2024년 사전정보로만 결측처리·클립·표준화·KMeans중심을 적합했고, 고정12조건+66교집합 중2024년 기준으로 최대6개를 동결했다.2025·2026년 정의를 바꾸지 않았다. 원본해시/시점/기존적중/군집최단거리소속/결과변조불변성/조건별분모를 점검했다. 주변확률은 조합나열과 별개인 대칭다항식으로 재계산하고 모든셀표준화 및 핵심조건날짜bootstrap을 별도 코드로 대조했다.

여러 조건의 겹침·다중비교가 있고,2024~2026년은 이전 연구에서도 반복해서 본 후향 표본이다. 이95%구간은 탐색 전체의 다중검정 보정구간이나 새로운 미래기간의 성공보장이 아니다. 동일 말의 반복출전에 대한 추가상관은 날짜bootstrap만으로 모두 제거되지 않는다. 현재 부담중량의 실제사전게시시점 검증 미완료 한계도 유지한다. 과거 구간평균의 이전 거리와 초반 페이스 차이가 완전히 통제됐다는 뜻도 아니다. 경주중 출발실수·진로사고·심판사유는 이 자료만으로 원인을 정할 수 없다.

다음 검증 후보는 **상대G3F·G1F×과거회복×이번 예상초반경쟁**의 상호작용이다. 단순추입가산보다 같은거리 이력·기본능력·표본지원과 함께 좁혀 시험해야 한다. 기존53후보도 단순히 정보를 더 넣으면 모든문제가 해결되지 않음을 보여준다. 동일한 최대6조합/시간순평가에서 후보포착·기존적중손실·최종적중을 함께 비교하고, 별도향후기간으로 다시 검증해야 한다. 이번 작업은 진단이며 예측모델을 재학습하거나 운영을 승격하지 않았다.

[사전계획](PLAN.md) · [말조건표](outputs/runner_condition_summary.csv) · [경주조건표](outputs/race_condition_summary.csv) · [실패분해](outputs/failure_decomposition.csv) · [실패연결](outputs/failure_linkage.json) · [군집설정](outputs/feature_contract.json) · [검증](outputs/verification.json) · [독립대조](outputs/independent_checks.json) · [용량](outputs/artifact_inventory.json).
"""
    (e.HERE / "README.md").write_text(body)
    pub = """# 게시 요약: 실패 경주와 낮게 평가한 입상마

더러브랫 연구모델22입력의2024~2026년4,799경주에서 삼복 확률순6조합 실패3,571개 중3,131개(87.68%)는 실제입상마가 예측5위밖에 있었다. 상위5두 내부 조합만 바꿔서는 해결 범위가 제한된다.

2024년에서 찾은 조건을 고정했을 때,2025~2026년 예측6위이하 중 **과거 G3F·G1F 평균이 편성내 빠른 상위약1/3이고 후반회복이 잦은**1,610출전은 실제349입상(21.68%)으로 평균예상17.88%보다 많았다.2025·2026년에 모두 과소평가 방향이 남았다. 지역·연도·거리대·등급대·두수대·예측순위대 공통셀1,491출전에서는 실제21.93% 대 비조건표준화16.61%였다. 자동으로5.32%p를 가산하는 근거는 아니다.

예를 들어 최종착순은 낮아도 과거 후반600m·200m 기록이 경쟁마보다 좋고, 뒤쪽에서 실제로 회복한 이력이 있는 말은 후순위 검토 대상으로 볼 수 있다. 모든추입마 또는 휴양·거리변경 말을 일괄상향하는 결론은 아니다.6~9두/10~11두/12두이상 삼복실패62.66%/75.78%/81.24%는 모델예상위험에도 상당부분 반영됐다.

큰 비지도군집만으로 반복 검증된 추가누락군을 확인하지는 못했다. 정확한 교집합을 이번 예상전개와 연결해 시험할 후보가 생긴 단계다. 여러조건의 중복·다중비교와 반복후향평가 한계가 있고, 새향후기간의 검증이나6조합 적중개선은 아직 확인하지 않았다. 운영·선택 연구모델·제주·DB는 변경하지 않았다.

[전체 보고서](README.md) · [검증](outputs/verification.json) · [독립대조](outputs/independent_checks.json).
"""
    (e.HERE / "PUBLICATION.md").write_text(pub)
    e.save(
        e.OUT / "decision.json",
        dict(
            status="retrospective_underestimated_late_recovery_signal_no_promotion",
            selected_baseline_changed=False,
            production_changed=False,
            new_outcome_prediction_models=0,
            database_access=False,
            jeju_access=False,
            primary_condition=primary.condition,
            validation_runners=int(primary.runners),
            validation_actual_rate=float(primary.actual_rate),
            validation_model_rate=float(primary.predicted_rate),
            excess_difference_ci=[
                float(primary.excess_difference_ci_low),
                float(primary.excess_difference_ci_high),
            ],
            independent_future_validation=False,
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
    target = e.R / "conclusions/35_FAILURE_CLUSTERS.md"
    assert not target.exists()
    target.write_text(
        pub.replace("(README.md)", f"(../{e.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{e.HERE.name}/outputs/"
        )
    )
    marker = "<!-- failure_clusters_v1_20261009 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{e.HERE.name}/README.md" if path.parent == e.R else target.name
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[실패 경주와 후순위 입상마 조건 군집]({link}):삼복6조합 실패87.68%에 예측5위밖 입상마. 후순위 종반600·200m 상대우수+회복 조건은2025~26년1,610출전 실제21.68% 대 예상17.88%. 군집전체보다 조건교집합 신호이며 후향진단/운영유지.\n"
            )
    manifest = json.loads(shared[-1].read_text())
    add = (
        [e.HERE / n for n in ["PLAN.md", "README.md", "PUBLICATION.md", "independent_checks.py"]]
        + [
            e.OUT / n
            for n in [
                "source_lock.json",
                "verification.json",
                "independent_checks.json",
                "decision.json",
                "selected_conditions.json",
                "failure_linkage.json",
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
            races=len(races),
            primary_failure_count=len(failures),
            website_deployed=False,
            production_changed=False,
            selected_baseline_changed=False,
            database_access=False,
            jeju_access=False,
        ),
    )
    e.check()
    print(pub, flush=True)


if __name__ == "__main__":
    main()

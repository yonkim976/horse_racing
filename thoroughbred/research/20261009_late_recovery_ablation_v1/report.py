"""Publish the fixed small ablation, including negative and partial findings."""

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
    for name in ["verification.json", "statistics_audit.json"]:
        assert json.loads((e.OUT / name).read_text())["status"] == "passed"
    assert not (e.HERE / "README.md").exists()
    summary = pd.read_csv(e.OUT / "summary.csv")
    pairs = pd.read_csv(e.OUT / "paired_differences.csv")
    all_rows = (
        summary[summary.period.eq("all")]
        .set_index("variant")
        .loc[["baseline22", "late30", "recovery32", "pressure43", "reference53"]]
        .reset_index()
    )
    later = (
        summary[summary.period.eq("2025_2026")]
        .set_index("variant")
        .loc[["baseline22", "late30", "recovery32", "pressure43", "reference53"]]
        .reset_index()
    )
    pressure = all_rows[all_rows.variant.eq("pressure43")].iloc[0]
    delta = pairs[
        pairs.candidate.eq("pressure43")
        & pairs.baseline.eq("baseline22")
        & pairs.period.eq("all")
        & pairs.metric.eq("trio6")
    ].iloc[0]
    signal = pd.read_csv(e.OUT / "signal_race_gains_losses.csv")
    dates = pd.read_parquet(e.OUT / "features.parquet").race_date
    result_columns = [
        "variant",
        "races",
        "trio6_hits",
        "trio6_rate",
        "axis_top3_rate",
        "axis_top2_rate",
        "quinella_one_rate",
        "quinella_box4_rate",
    ]
    body = f"""# 종반·회복·선행경쟁을 조금씩 추가한 모델 비교

2026-10-09. 더러브랫 서울·부산. **이번30/32/43입력 후보는 현재22입력 기준 모델보다 삼복6조합·축 선정에서 뚜렷하게 좋아지지 않았다.** 낮게 평가했던 특정 종반·회복 입상마를 더 올리는 반응은 있었지만, 다른 입상마를 밀어낸 손실과 함께 평가하면 순개선이 남지 않았다. 운영/선택 연구모델은 유지한다.

## 고정한 실험

| 후보 | 입력수 | 추가한 묶음 |
| --- | ---: | --- |
| baseline22 | 22 | 현재 월·게이트·부담중량 모델, 기존6모형 재사용 |
| late30 | 30 | G3F·G1F 최근3평균/최근5유효수, 자기제외 상대차와 편성내 백분위8개 |
| recovery32 | 32 | 위30개+과거 후반회복 비율/관측수2개 |
| pressure43 | 43 | 위32개+과거 S1F·선행성향, 상대선행밀집/초반지원, 종반·회복×선행밀도11개 |
| reference53 | 53 | 기존 구간·거리변경·각질/회복/후퇴 이력 후보, 고정 참고 대조 |

이번 pressure43의 선행 경쟁은 과거S1F와 선행빈도에서 만든 **대리변수**다. 이번 경주의 실제전개나 경합의도 관측, 이전77입력 전개보조모형의 예측확률을 넣은 결과가 아니다. 기수·조교사·심판·직접게이트 입력을 추가하지 않았다. 과거기록에 이미 있는 주로·월·게이트 보정과 부중22개는 유지했다. 모델을 평가한 뒤 문턱이나 입력을 바꾸지 않았다.

## 동일4,799경주 결과

2024-01-05~2026-09-20,50,754출전.2017~{dates.max().date()} 전체178,497행을 기존 연도분할에 활용했다. 비율 열은0~1척도다. 삼복은 말점수합의 공동확률 상위6조합(global6)으로 고정했다. 축은 해당 모델의 점수1위이며, 원축을 강제하지 않았다. 복승1조합은 평가순위1·2위, 복승6은 순위상위4두의 모든 비순서쌍(박스)이다. **복승6은 별도Top2확률순6조합이 아니다.**

{table(all_rows[result_columns])}

삼복은22개25.59%,30개25.55%,32개25.55%,43개25.76%였다.43개는 **새적중{int(delta.gained)}경주/기존적중손실{int(delta.lost)}경주**, 순증8경주 **{delta.difference * 100:+.2f}%p**다. 날짜군집bootstrap95%구간 **{delta.ci_low * 100:+.2f}~{delta.ci_high * 100:+.2f}%p**로0을 포함한다. 개선이 확인됐다고 표현하지 않는다.

43개 복승상위4두박스6조합은39.05%→40.61%,+75경주(+1.56%p,CI+0.58~+2.57%p)였다. 하지만 축2위이내는47.38%→47.24%, 복승1조합12.00%→12.07%로 주축/단일조합의 개선은 확인하지 못했다. 특히32개 축2위이내는46.20%로 기준보다−1.19%p,CI−1.96~−0.38%p였다. 회복 입력 추가 자체가 모든 목표를 개선한다는 결론은 아니다.

## 후속연도에서도 유지됐는가

같은 후향 자료에서2024년을 제외한2025~2026년3,038경주다. 새로운 독립기간으로 부르지 않는다.

{table(later[result_columns])}

43개 삼복은 기준784적중→775적중으로 **−9경주(−0.30%p,CI−1.33~+0.73%p)**였다.2025년은423→423,2026년은361→352였다. 전체+8경주 증가는2024년에 집중됐고 후속연도에서 반복되지 않았다.43개 복승박스6의 후속연도 차이+1.22%p도CI−0.07~+2.45%p로0을 포함했다.

고정53개 참고 후보는 전체 삼복27.36%,2025~26년27.62%로22개 대비 각각+85/+55경주였다. 해당 삼복차이CI는전체+0.86~+2.68%p/후속+0.66~+2.91%p다. 그러나 동일기간 반복연구이고 이번에는 운영ABC와 새롭게 대조하지 않았다. **이번 작은 후보들이53개보다 낫다는 근거도,53개를 운영으로 승격할 새로운 근거도 아니다.**

## 왜 조건말을 올렸는데 적중은 그대로인가

기준22에서예측6위이하였던 실제입상4,366출전 중43개가5위안으로올린 수는 **{int(pressure.low_winners_up):,}({pressure.low_winner_recall * 100:.2f}%)**였다. 동시에 기준5위안의 실제입상10,031출전 중 **{int(pressure.old_winners_down):,}({pressure.old_winner_loss_rate * 100:.2f}%)**가6위이하로밀렸다. 두분모가다르므로비율을직접차감하지않는다. 손실과포착을함께보면실제3두가모두5위안에있던경주도1474→1458로줄었다.

{table(all_rows[["variant", "low_winners", "low_winners_up", "low_winner_recall", "old_winners", "old_winners_down", "old_winner_loss_rate", "top5_contains_truth_rate"]])}

앞서찾은 ‘종반600m·200m 모두편성상위약1/3+회복빈도>=.4,각관측3전이상’ 조건은기준22순위로고정했다.2025~26년해당후순위입상349두중5위안으로올린수는30개108두,32개108두,43개115두,기존53개106두다. **특정조건 포착만 보면43개가 더 반응했지만 전체조합은53개보다낮았다.**

{table(signal[signal.period.eq("2025_2026") & signal.baseline.eq("baseline22")])}

해당349두가나온340경주(기준삼복적중10/실패330)에서43개가맞힌수는20개,기존기준대비새적중11/손실1이었다.하지만그조건밖경주까지포함한전체에서는후속−9개였다. 이 조건은 사후평가에만 사용하며 실제입상 여부로 예측이나조합을 선택하지 않았다. 유용한조건 발견과 전편성순위 재학습의 성공은다르다.

## 확률 품질과 적용 판단

43개는 전체조합NLL4.3458→4.3314/말입상Brier0.17758→0.17702로 소폭 개선했고 차이CI도음수였다. 확률분포의품질과상위6선택의적중은같지않다. 작은확률차이나다른후보와의균형때문에적중이늘지않을수있으며 이를경주중단일원인으로단정하지않는다.

이번 결과로22개를30/32/43개로교체하지않는다. 기존53개는연구참고후보로보존한다. 다음연구가설은 기존능력평가와축을유지하고 상대후보만보완하는방식, 또는 직전·최고기록·동거리지원정보를함께보는방식이다. 이번실험은평균/회복의작은묶음이므로53개에있는직전·최고·거리·다른각질정보의개별효과를증명하지못했다. 특정추입조건에고정점수를주는규칙은채택하지않았다.

## 학습·검증·한계

서울/부산×2024/25/26×3후보=18모형을새학습했고기준6모형을재사용했다.3위이내LightGBM,동일seed20261004/1두수가중치/최대200/조기종료25다.2017~Y−3초기학습,Y−2조기종료,2017~Y−2재학습,Y−1온도교정,Y평가.2010~16warm-up과T−2/730일실제최근5슬롯은원본그대로다. 미지원/희소구간을결측으로유지하고행을제외하지않았다. 기존구간보정도원본연도별추정값을사용한다.

기준원점수50,754개/1,228삼복적중/축지표를재현했고저장모형24개를재추론했다.평가전체및고정역사표본72,018출전에대해자기제외상대차·백분위·선행밀집·초반지원율을직접비교하고현재결과변조불변성을확인했다. 독립삼복곱분포/선택6조합/확률합3/후순위이동을재구성했다. 모든270개날짜bootstrap구간과순위지표/새적중·손실/분모도별도코드로재계산했다. verifier 인덱스조회최적화는학습전수정으로이전/이후해시를보존했고검사내용은변경하지않았다.

2024~26은조건발견에도이미사용한반복후향표본이며다중비교미보정·부분2026·현재중량/출전명단의사전게시시각미감사한계가있다. 날짜bootstrap이동일말의모든반복상관을해결하지않는다. 과거G3F·G1F의이전거리/초반페이스차이가완전히제거됐다는뜻도아니다.이원천은9월20일까지라향후독립성적을만들지않았다.

2026-10-10 이후미사용경주를향후검증후보로예약했고,5후보/입력계약/2026모형해시/6조합규칙을 [향후검증계약](outputs/future_validation_contract.json)에보존했다.실제사전예측생성·수집·검증을수행한것은아니며향후기간중재튜닝하면별도버전으로구분해야한다.시점감사를완료해야실전검증으로읽을수있다.

[사전계획](PLAN.md) · [입력별계약](FEATURES.md) · [전체/연도집계](outputs/summary.csv) · [같은경주차이](outputs/paired_differences.csv) · [거리/등급/두수](outputs/stratified_summary.csv) · [적중변경경주](outputs/trio_changed_races.csv) · [검증](outputs/verification.json) · [통계대조](outputs/statistics_audit.json) · [용량](outputs/artifact_inventory.json).
"""
    (e.HERE / "README.md").write_text(body)
    explain = """# 입력별 계약

22개기준입력은원본변경없이유지한다.나머지는현재착순·현재구간·기수·조교사·심판·직접게이트를사용하지않는다.아래구간은지원되는과거기록의환경보정값이다.평균은최근실제3슬롯내유효기록,유효수는최근실제5슬롯이다.결측행을건너뛰어5개를채우지않는다.

| 이름 | 의미 |
| --- | --- |
| section_last600_mean3 / section_late_mean3 | 과거 G3F600m / G1F200m 최근3전 평균초,낮을수록빠름 |
| section_last600_n5 / section_late_n5 | 각구간최근5슬롯유효관측수 |
| last600_relative_adv / late_relative_adv | 현재편성의다른말과거구간평균−자기과거구간평균,양수면빠름;상대관측없으면결측 |
| last600_percentile / late_percentile | 편성내과거시간역순평균순위/유효말수,높을수록빠름;동률평균순위 |
| style_recovery_mean5 / style_recovery_n5 | 과거후반회복표식의최근5전평균/관측수.남은600m상대순위>=.5이면서결승까지상대순위회복>=.25 |
| section_early_mean3 / section_early_n5 | 과거 S1F200m 최근3평균/최근5전유효수 |
| style_role0_rate5 / style_role_n5 | 통과조기준과거선행빈도/최근5전유효각질관측수 |
| field_other_lead_mass | 자기제외,유효각질3전이상다른말의과거선행빈도합;아무상대관측없으면결측 |
| field_strong_front_n | 위상대중과거선행빈도>=.4말수;상대관측없으면결측 |
| field_early_faster_n | 자기보다과거S1F평균이빠른상대수;자기/상대구간각유효3전이상,자기미지원또는상대관측없으면결측 |
| field_early_support | 자기제외S1F유효3전이상관측말수/(두수−1);미지원상대비율을표시 |
| last600_x_lead_pressure / late_x_lead_pressure | 종반상대차×(field_other_lead_mass/(두수−1)) |
| recovery_x_lead_pressure | 과거회복빈도×위선행밀도 |

600m와200m는겹치는구간이며점수를독립가산하지않는다.선행밀도는동일편성자료에대한대리변수로당일경합의도나검증된실제선행수확률이아니다.모든입력전체목록은 [feature_contract.json](outputs/feature_contract.json)에보존했다.
"""
    (e.HERE / "FEATURES.md").write_text(explain)
    pub = """# 게시 요약: 종반·회복·선행경쟁 단계별 모델 시험

더러브랫22입력에종반기록8개→회복2개→선행경쟁11개를차례로추가해30/32/43입력후보18모형을학습했다.동일2024~26년4,799경주에서삼복확률순6조합적중은25.59%→25.55%→25.55%→25.76%였다.43개의새적중226/손실218,순증8개는차이95%구간−0.69~+0.98%p로불확실했다.2025~26년만보면기준784→775로9개줄었다.

종반600·200m가상대적으로좋고회복이잦은후순위입상마를올리는반응은있었다.하지만43개는기준후순위입상마721두를5위안으로올린동시에기준5위안입상마729두를밖으로밀었다.예를들어종반우수후순위한마리를맞게올려도원래들어온다른말을밀어내면최종삼복은놓칠수있다.같은조건의말을포착하는것과전체편성순위를더잘정하는것은다르다.

43개복승상위4두박스6조합은전체39.05%→40.61%였지만후속연도차이구간은0을포함했다.축2위이내/복승1조합개선은확인하지못했고별도복승확률순6조합실험도아니다.기존53입력참고후보의삼복27.36%보다이번작은후보들은낮았다.

현재22입력/운영모델은유지한다.선행경쟁은과거성향대리값이며실제전개/기수/심판자료를넣지않았다.반복후향평가이므로향후미사용기간검증이필요하다.자료끝은2026-09-20이고향후검증계약만보존했으며사전예측·실전검증을완료한것은아니다.

[전체 보고서](README.md) · [입력 설명](FEATURES.md) · [검증](outputs/verification.json) · [통계대조](outputs/statistics_audit.json).
"""
    (e.HERE / "PUBLICATION.md").write_text(pub)
    future_models = []
    for folder in sorted((e.OUT / "models").glob("*_2026")):
        meta = json.loads((folder / "metadata.json").read_text())
        meet = int(folder.name.split("_")[-2])
        model_path = (
            e.W / "models" / f"{meet}_2026_month_gate_weight22/top3.txt"
            if meta["variant"] == "baseline22"
            else folder / "model.txt"
        )
        future_models.append(
            dict(
                variant=meta["variant"],
                meet=meet,
                model_path=str(model_path.relative_to(e.ROOT)),
                sha256=e.sha(model_path),
                metadata_path=str((folder / "metadata.json").relative_to(e.ROOT)),
                metadata_sha256=e.sha(folder / "metadata.json"),
            )
        )
    for meet in [1, 3]:
        path = e.S / "outputs/finish_models" / f"3_style_history_{meet}_2026"
        future_models.append(
            dict(
                variant="reference53",
                meet=meet,
                model_path=str((path / "model.txt").relative_to(e.ROOT)),
                sha256=e.sha(path / "model.txt"),
                metadata_path=str((path / "metadata.json").relative_to(e.ROOT)),
                metadata_sha256=e.sha(path / "metadata.json"),
            )
        )
    e.save(
        e.OUT / "future_validation_contract.json",
        dict(
            status="reserved_not_evaluated",
            earliest_race_date=e.config()["prospective_period_start"],
            source_data_end=str(dates.max().date()),
            models=future_models,
            feature_contract_sha256=e.sha(e.OUT / "feature_contract.json"),
            reference53_feature_contract=str(
                (e.S / "outputs/feature_contract.json").relative_to(e.ROOT)
            ),
            reference53_feature_contract_sha256=e.sha(e.S / "outputs/feature_contract.json"),
            primary_policy="trio_global6",
            ticket_count=6,
            rank_tie_rule="program_no_ascending",
            current_prediction_timestamp_audit_required=True,
            refitting_or_rule_changes_require_new_version=True,
            existing_study_is_retrospective=True,
        ),
    )
    e.save(
        e.OUT / "decision.json",
        dict(
            status="small_ablation_no_clear_trio_or_axis_gain_no_promotion",
            research_baseline="month_gate_weight22",
            research_baseline_changed=False,
            production_changed=False,
            fitted_outcome_models=18,
            source_access="local_frozen_files",
            database_access=False,
            jeju_access=False,
            future_period_evaluated=False,
            primary_candidate="pressure43",
            primary_difference=float(delta.difference),
            primary_ci=[float(delta.ci_low), float(delta.ci_high)],
            overall_trio_gain=8,
            later_trio_gain=-9,
            reference53_retained_as_research_only=True,
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
    target = e.R / "conclusions/36_LATE_RECOVERY_ABLATION.md"
    assert not target.exists()
    target.write_text(
        pub.replace("(README.md)", f"(../{e.HERE.name}/README.md)")
        .replace("(FEATURES.md)", f"(../{e.HERE.name}/FEATURES.md)")
        .replace("(outputs/", f"(../{e.HERE.name}/outputs/")
    )
    marker = "<!-- late_recovery_ablation_v1_20261009 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{e.HERE.name}/README.md" if path.parent == e.R else target.name
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[종반·회복·선행경쟁 작은 입력 실험]({link}):30/32/43입력18모형.삼복6조합25.59%→25.55%→25.55%→25.76%,43개전체+8/후속−9경주.후순위포착과기존입상손실이함께발생해운영/22개유지.\n"
            )
    manifest = json.loads(shared[-1].read_text())
    add = (
        [
            e.HERE / n
            for n in [
                "PLAN.md",
                "config.json",
                "README.md",
                "FEATURES.md",
                "PUBLICATION.md",
                "audit_statistics.py",
            ]
        ]
        + [
            e.OUT / n
            for n in [
                "source_lock.json",
                "verification.json",
                "statistics_audit.json",
                "decision.json",
                "future_validation_contract.json",
                "feature_contract.json",
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
            new_outcome_models=18,
            evaluated_races=4799,
            new_candidate_variants=3,
            research_baseline_changed=False,
            production_changed=False,
            website_deployed=False,
            database_access=False,
            jeju_access=False,
            future_period_evaluated=False,
        ),
    )
    e.check()
    print(pub, flush=True)


if __name__ == "__main__":
    main()

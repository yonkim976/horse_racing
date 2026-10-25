"""Publish all prespecified candidates, without retrospectively selecting a winner."""

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
    for name in ["verification.json", "allocation_audit.json"]:
        assert json.loads((r.OUT / name).read_text())["status"] == "passed"
    assert json.loads((r.OUT / "allocation_audit.json").read_text())["script_sha256"] == r.sha(
        r.HERE / "audit_allocation.py"
    )
    q = pd.read_csv(r.OUT / "quality.csv", dtype={"period": str})
    delta = pd.read_csv(r.OUT / "paired_differences.csv", dtype={"period": str})
    target = q[q.group.eq("target")]
    primary = delta.query(
        "group=='target' and variant=='joint' and reference=='constant' and metric=='brier'"
    )
    main_result = primary[primary.period.eq("all")].iloc[0]
    brier = target.pivot(index="period", columns="variant", values="brier").reset_index()
    brier = brier.set_index("period").loc[["2024", "2025", "2026", "all", "2025_26"]].reset_index()
    probabilities = target[target.variant.isin(["raw", "constant", "joint"])][
        ["period", "variant", "n", "failures", "mean_top3", "actual_top3", "mean_cut"]
    ]
    alloc = pd.read_csv(r.OUT / "outcome_allocation.csv")
    examples = pd.read_csv(r.OUT / "examples.csv")
    body = f"""# 高확률 5등급 축의 초반·최근 기록에 따른 보정 강도

2026-10-10. **두 조건을 함께 넣으면 전체 평균 확률 오차는 줄었지만, 2026년은 기존 일괄 보정보다 나빠졌다. 이번 결과로 대체하지 않는다.**

원 입상확률 70% 이상인 5등급의 동일 축 205경주를 대상으로 했다. 2024/2025/2026년(9월20일까지)은 71/78/56경주다. 전체 4,799경주 중 나머지 4,594경주의 확률은 원확률 그대로다. 축의 실제 입상은 142/205=69.27%, 전체는 2,862/4,799=59.64%다. 이번 작업은 같은 축의 입상확률을 재보정하므로 **축 선정 적중률 자체는 변하지 않는다.** 다른 축 선택·후속 후보·조합 선정은 시험하지 않았다.

## 무엇을 적용했는가

- 초반 상대우위: 축의 보정된 최근3전 초반200m 평균시간과 이번 자기제외 경쟁마들의 해당 평균시간 차이의 부호를 반전했다. 0.5초면 축의 과거 초반기록이 상대들의 평균보다 0.5초 빠르다는 뜻이다. 당일 실제 선행 여부나 통과착순을 넣은 값이 아니다.
- 최근 기록: 기존 월·게이트 보정22입력 원장의 보정된 최근3전 전체기록 평균점수. 높을수록 좋으며 초·공식 rating·직접 우승확률이 아니다. 상대 평균과의 격차나 최근 최고기록은 이번 후보에 추가하지 않았다. 원모델에도 최근 기록이 들어 있으므로 추가 보정의 중복 활용이 도움이 되는지 비교한 것이다.
- 기존 일괄 보정은 해당 집단의 이탈 log odds에 상수를 더한다. 이번 후보는 그 상수와 함께 위 조건의 계수를 학습한다. 초반만(early), 최근만(recent), 둘 다(joint)를 결과 전 고정하고 joint를 주 후보로 정했다.

각 Y년은 2020~Y-1의 해당 집단만 학습했다. 학습 표본은 2024년용388, 2025년용459, 2026년용537이다. 평균·표준편차도 학습 표본만 사용했다. 입력은 평균0·표준편차1로 바꾸고 ±3에서 절단했다. 결측은 평균 대체+결측 표시다. 절편을 포함한 모든 계수에 L2=10을 동일 적용했고 결과를 본 후 규제나 부호를 바꾸지 않았다. 신규 소형 보정모형9개, 새 말 능력모형0개다. 원확률/기존 일괄 보정은 [40번 연구](../20261010_axis_single_signal_ablation_v1/README.md) 예측을 그대로 재사용했다.

## 연도별 확률 오차

Brier는 (예측입상확률-실제입상여부)²의 평균이며 **낮을수록 좋다**. 이탈확률로 계산해도 같은 값이다. 적중률(%)이 아니다.

{table(brier)}

원확률→일괄→두 조건의 전체 대상 Brier는 0.208518→0.204322→0.200412다. 두 조건은 일괄보다 평균 1.91% 낮았지만 2026년은 0.196698→0.199523으로 1.44% 높아졌다. 초반만 넣어도2026년은 악화됐고 최근만 넣은 후보도 일괄을 넘지 못했다. 전체에서 가장 좋아 보이는 후보를 사후 선택하지 않았다.

일괄 대비 joint Brier의 paired 경주일 군집 bootstrap95% 구간이다. 차이가 음수면 개선이다.

{table(primary[["period", "n", "difference", "low", "high"]])}

주 비교의 차이 {main_result.difference:.6f}, 95%CI[{main_result.low:.6f},{main_result.high:.6f}]는0을 포함한다. '전체 구간상한<0 + 세 연도 모두 개선'이라는 계획상 판단 조건도 충족하지 않는다. 연도별·구성요소 CI는 탐색적이며 다중 비교 확증 결과가 아니다. 전 연도의 결과를 이용해 조건을 고른 반복 후향 연구라는 선택 편향도 남아 있다.

## 평균 확률과 실제 성적

mean_top3=평균 예측입상확률, actual_top3=실제입상률, mean_cut=원확률 대비 입상확률 평균 감점. 표는0~1단위다.

{table(probabilities)}

2026년 평균 예측은 원74.71%/일괄68.20%/조건별69.87%, 실제73.21%다. 평균 감점은 일괄6.52%p에서4.84%p로 줄었다. 평균값은 실제에 가까워졌지만 개별 경주 오차는 커졌다. **평균 확률을 맞추는 일과 이탈할 말을 구분하는 일은 다르다.**

## 2026년에 손해가 난 이유

아래 표는 결과를 본 뒤 만든 설명용 분해이며 학습 조건을 다시 고른 것이 아니다. collapsed0=입상,1=이탈. constant_risk/joint_risk는 이탈확률, brier_difference_sum은 해당 그룹의 손실 차이 합이다.

{table(alloc)}

2024년 실제 입상마/이탈마의 평균 초반 상대우위는0.356/0.162초, 2025년은0.337/0.251초였다. 그러나2026년은0.458/0.498초로, 이탈한 말도 초반 우위가 컸다. 2026년 입상41두에서는 새 보정으로 손실 합이0.264231 줄었지만 이탈15두에서는0.422430 늘었다. 빠른 초반 이력이 있어 감점을 완화한 말 중 실제 이탈마가 포함됐기 때문이다. 평균값만으로 인과나 구조적 반전을 확정할 수 없으며56경주의 소표본이다. 초반 우위만으로 종반 유지·전개 성공을 보장하지 못한다.

조건2×2 표는 학습 집단의 평균을 경계로 나누었으며 [profiles.csv](outputs/profiles.csv)에 전부 보존했다. 검증 표본에서 유리한 임계값을 새로 찾지 않았다. 최근3전 유효기록3개 이상·초반5전 유효기록3개 이상147경주의 보조 분석은 일괄0.215280→joint0.211109다. 초반5전의 유효수는 최근3전이 모두 관측됐음을 뜻하지 않으므로 이 검사는 충분한 이력의 대리 기준이다. 지원 표본의 연도별 결과와 CI도 [quality.csv](outputs/quality.csv), [paired_differences.csv](outputs/paired_differences.csv)에 보존했다.

전체4,799경주의 Brier는 일괄0.230153→joint0.229986으로 변화가 작다. 대상밖은 변경하지 않았기 때문에 전체 변화는 대상205경주 효과를 희석한 값이다.

## 실제로 보정 강도가 어떻게 달라지는가

2026년 학습 모형의 결측 없는 경우다. 초반 우위와 최근 점수가 좋을수록 이탈 위험에 더하는 양이 줄어든다. 충분히 좋으면 원 입상확률보다 높아질 수도 있으며, joint205경주 중22경주가 그랬다. 감점만 허용하는 별도 후처리는 적용하지 않았다.

```text
z초반 = clip((초반우위초 - 0.340538) / 0.282340, -3, 3)
z기록 = clip((최근기록점수 - 0.669728) / 0.509604, -3, 3)
logit(새 이탈확률) = logit(원 이탈확률) + 0.303040
                     - 0.183626*z초반 - 0.169257*z기록
새 입상확률 = 1 - sigmoid(위 값)
```

입상확률75%로 고정한 설명용 입력 조합이다. 새로운 실제 경주의 예측이 아니다.

{table(examples)}

예를 들어 초반0.1초 우위·최근점수0이면75→60.27%, 초반0.5초 우위·최근점수1이면75→73.28%다. 같은 원확률에서도 보정 강도를 다르게 학습했다는 뜻이며 이 구체적 강도가 운영에 적합하다는 결론은 아니다.

## 검증과 적용 범위

- [계획](PLAN.md)·학습/검증 코드와 원천·운영 레지스트리·선택22입력·미래검증 계약의 해시를 결과 전 고정했다. 원22입력 축과 원확률은 변경하지 않았다. 2020~2023년 원축은 기존 시간순 OOF,2024~2026년은 기존 동결 예측이다.
- [독립 검증](outputs/verification.json):9모형의 학습 기간/평균/표준편차/계수 최적성/저장 재예측,100지표행,240 pairedCI행,결과·미사용 필드 변조 무영향,4,594대상밖 불변을 확인했다. [추가 감사](outputs/allocation_audit.json)는205조건 분류·조건별 지표·예시9개·손실분해를 확인했다.
- 과거 이력은 기존T−2/730일/실제출전슬롯 정의를 재사용했다. 미지원 구간 보정은 기존 방식대로 원초를 유지한다. 직접 기수·현재 게이트·당일 실제 전개·당일 착순은 입력하지 않았다.
- 조건은 이미2024~2026 결과를 본 뒤 선택됐으며 시간순 적합만으로 선택 편향이 사라지지 않는다. 당일중량 등의 실제 공개 시각(PIT) 감사가 완성되지 않은 기존 후향 한계도 남는다. 연도별 말 능력모형과 온도도 달라져 대상 집단이 같은 말의 반복 패널은 아니다.
- 2026년은9월20일까지만, 대상56경주다. 연구 원장의 종료일이며 전체 DB 최신일을 확인한 것이 아니다. 조건별 최근 기록은 절대 보정점수이며 현재 편성 대비 상대 기록으로 해석하지 않는다.
- DB·네트워크·제주·운영모형·미래검증 계약을 변경하지 않았다. 39번의 미래검증 계약에 이번 후보를 자동 추가하지 않았다. 게시용 문서를 준비한 것이며 웹 배포는 아니다.

다음 판단은 **연도별 재현성과 새 표본의 개별 경주 오차**가 기준이어야 한다. 평균 확률이 실제 성적에 가까워진 것만으로 축 이탈을 더 잘 찾는다고 판단하지 않는다. 이번 연구 후보는 보존하되 기존 보정/운영을 대체하지 않는다.

## 산출물

[전 경주 비교 원장](outputs/predictions.parquet), [연도별 지표](outputs/quality.csv), [같은 경주 손실차와CI](outputs/paired_differences.csv), [모형계수](outputs/coefficients.csv), [판정](outputs/decision.json), [설명용 예시](outputs/examples.csv), [용량명세](outputs/artifact_inventory.json), [게시요약](PUBLICATION.md). 재현 순서 run.py→verify.py→audit_allocation.py→report.py→finalize_inventory.py. run.py는 동결 산출물 덮어쓰기를 방지하므로 재실행은 별도 복제 폴더가 필요하다.
"""
    body = body.replace("# 高확률", "# 고확률")
    (r.HERE / "README.md").write_text(body)
    pub = """# 고확률 5등급 축의 조건별 보정: 평균 개선, 2026년 재현 실패

2026-10-10. 원 입상확률70% 이상인5등급 축205경주에서 초반 상대우위와 최근 보정기록에 따라 보정 강도를 달리 학습했다. 같은 축의 입상확률 재보정이며 축을 바꾸거나 조합을 다시 고른 시험은 아니다.

무엇을 알았는가: 기존 일괄 보정 대비 두 조건 보정의 Brier는2024년0.201851→0.195147,2025년0.212045→0.205844,2026년0.196698→0.199523이다. 합산0.204322→0.200412로 평균1.91% 개선됐지만2026년은1.44% 악화됐다. 합산 차이95%CI[-0.010259,+0.002625]에0이 포함돼 확실한 개선으로 판정하지 않는다.

어떻게 읽는가: 초반 우위는 보정된 과거 초반200m최근3전 기록이 이번 상대들보다 얼마나 빠른지다. 최근 기록은 보정된 전체기록 평균점수다. 좋은 두 조건에서는 감점이 줄고 좋지 않으면 커진다. 과거 통과착순이나 이번 실제 전개를 넣은 값이 아니다.

사례: 원 입상확률75%라면2026년용 모형에서 초반0.1초 우위·최근점수0은60.27%,초반0.5초 우위·최근점수1은73.28%다. 설명용 예시이며 실제 새 경주의 예측은 아니다.2026년 평균 예측은68.20→69.87%로 실제73.21%에 가까워졌지만 개별 경주 오차는 늘었다. 실제 이탈마도 초반 우위가 좋아 감점이 완화됐기 때문이다.

어디까지 적용되는가:2024/2025/2026-09-20의71/78/56경주,각 평가연도 이전 자료만 적합했다. 그러나 조건 선정에 해당 평가연도의 분석을 이미 봤으므로 독립 확증은 아니다. 대상밖4,594경주와 모든 원축은 불변이다. 소형 보정9개를 학습하고 재예측/지표/날짜군집CI/해시를 검증했다. 운영모형과 미래검증 계약은 유지한다. 웹사이트 게시용 요약을 준비한 단계다.

[원 보고서와 검증](README.md) · [확률오차 표](outputs/quality.csv) · [같은 경주 비교](outputs/paired_differences.csv)
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
    central = r.R / "conclusions/42_GRADE5_ADAPTIVE_CORRECTION.md"
    assert not central.exists()
    central.write_text(
        pub.replace("(README.md)", f"(../{r.HERE.name}/README.md)").replace(
            "(outputs/", f"(../{r.HERE.name}/outputs/"
        )
    )
    marker = "<!-- grade5_adaptive_correction_v1_20261010 -->"
    for path in [shared[0], shared[2], shared[3]]:
        link = f"{r.HERE.name}/README.md" if path.parent == r.R else central.name
        with path.open("a") as handle:
            handle.write(
                f"\n\n{marker}\n[高확률5등급 조건별 보정 시험]({link}): 초반 상대우위+최근 보정기록, 대상205경주. 일괄 대비 합산 Brier0.204322→0.200412이나2026년0.196698→0.199523. CI는0포함, 운영 유지.\n".replace(
                    "高확률", "고확률"
                )
            )
    manifest = json.loads(shared[-1].read_text())
    own = sorted(
        p
        for p in r.HERE.rglob("*")
        if p.is_file()
        and "publication_before" not in p.parts
        and p.name != "publication_before.json"
    )
    for path in own + [central, shared[0], shared[2], shared[3]]:
        name = str(path.relative_to(r.ROOT))
        manifest["sources"] = [row for row in manifest["sources"] if row["path"] != name]
        manifest["sources"].append(dict(path=name, sha256=r.sha(path), bytes=path.stat().st_size))
    r.save(shared[-1], manifest)
    r.save(
        r.OUT / "completion.json",
        dict(
            status="complete_verified_published_locally",
            new_models=9,
            target_races=205,
            production_changed=False,
            selected_baseline_changed=False,
            prior_future_contract_changed=False,
            database_access=False,
            network_access=False,
            jeju_access=False,
        ),
    )
    r.check()
    print("Local report and conclusion42 published; candidate not promoted.")


if __name__ == "__main__":
    main()

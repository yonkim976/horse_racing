# ruff: noqa: E501 -- Stored Korean Markdown paragraphs keep their native line breaks.
"""Write a local report/publication package from verified outputs."""

import importlib.util
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("cross", HERE / "analyze.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def table(d, cols):
    labels = {
        "period": "기간",
        "band": "상태",
        "effect_seconds": "외측-내측(초)",
        "ci_low": "95%하한",
        "ci_high": "95%상한",
        "q": "q",
        "supported": "지원",
    }
    lines = [
        "| " + " | ".join(labels.get(c, c) for c in cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in d.iterrows():
        values = []
        for c in cols:
            v = row[c]
            values.append(f"{v:.3f}" if isinstance(v, float) else str(v))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def main():
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["passed"]
    summary = json.loads((OUT / "summary.json").read_text())
    p = pd.read_csv(OUT / "seconds_profiles.csv", dtype={"level": str})
    grid = pd.read_csv(OUT / "coverage_grid.csv", dtype={"level": str})
    candidates = pd.read_csv(OUT / "correction_candidates.csv", dtype={"level": str})
    focus = p[
        p.adjustment.eq("dual")
        & p.meet.eq("서울")
        & p.distance_m.eq(1200)
        & p.block.eq("other_11")
        & p.family.isin(["outer_inner", "interaction"])
        & p.level.isin(["outer-inner", "outer_inner:outer-inner"])
    ].copy()
    focus.to_csv(OUT / "seoul1200_11_focus.csv", index=False)
    numbers = p[
        p.adjustment.eq("dual")
        & p.distance_m.eq(1600)
        & p.family.eq("number")
        & (
            (p.meet.eq("서울") & p.block.eq("exact10") & p.level.eq("10"))
            | (p.meet.eq("부산") & p.block.eq("exact12") & p.level.eq("1"))
        )
    ].copy()
    numbers.to_csv(OUT / "1600_number_focus.csv", index=False)
    counts = (
        grid.groupby(["meet", "distance_m", "status"]).size().unstack(fill_value=0).reset_index()
    )
    counts.to_csv(OUT / "distance_coverage.csv", index=False)
    population, _ = A.load()
    gate_source = pd.read_parquet(A.L.GATES)
    target = population[
        population.meet.eq("서울")
        & population.distance_m.eq(1200)
        & population.gate_block.eq("other_11")
    ].race_key.unique()
    contiguous = (
        gate_source[gate_source.race_key.isin(target)]
        .groupby("race_key")
        .horse_number.agg(lambda values: set(values) == set(range(1, 12)))
    )
    assert len(contiguous) == 788 and (~contiguous).sum() == 94
    pd.DataFrame(
        [
            dict(
                meet="서울",
                distance_m=1200,
                field_size=11,
                races=len(contiguous),
                contiguous_program_races=int(contiguous.sum()),
                gapped_program_races=int((~contiguous).sum()),
            )
        ]
    ).to_csv(OUT / "roster_audit.csv", index=False)
    intersections = p[
        p.adjustment.eq("dual")
        & p.family.eq("interaction")
        & p.period.isin(["all_mad4", "recent_mad4"])
    ]
    cols = ["meet", "distance_m", "band", "block", "level"]
    full = intersections[intersections.period.eq("all_mad4") & intersections.q.lt(0.05)]
    recent = intersections[intersections.period.eq("recent_mad4") & intersections.q.lt(0.05)]
    replicated = full.merge(recent, on=cols, suffixes=("_full", "_recent"))
    replicated.to_csv(OUT / "replicated_interactions.csv", index=False)
    assert len(replicated) == 1
    mainfocus = focus[
        focus.period.isin(["all_mad4", "recent_mad4"]) & focus.family.eq("outer_inner")
    ]
    mainfocus = mainfocus.assign(
        period=mainfocus.period.map({"all_mad4": "전체4MAD", "recent_mad4": "2024~2026 4MAD"})
    )
    maintable = table(
        mainfocus, ["period", "band", "effect_seconds", "ci_low", "ci_high", "q", "supported"]
    )
    single = replicated.iloc[0]
    status = "\n".join(f"- {k}: {v:,}행" for k, v in summary["status_counts"].items())
    main = f"""# 주로상태에 따라 게이트 시간 차이가 달라지는가

서울1200m11두 경주는 건조 때 외측이 내측보다 약0.30초 느렸고, 포화 때는 그 차이가 줄었다. **건조 대비 포화의 외측−내측 차이 변화는 전체−0.423초·최근−0.419초**였다. 전체·최근 다중비교에서 함께 남은 상태 간 차이는 이 조합 하나다. 포화에서 외측이 확실히 빠르다는 결론이나, 개별 말에0.42초를 보정하라는 의미는 아니다.

새 게이트 시간 보정 후보는 **0개**다. 상태별로 세분하면 표본과 안정성이 부족하므로, 기존 완주시간 함수율 보정은 유지하고 추가 게이트 보정은 보류한다. 기존 월 보정 후보의 지위도 유지한다.

## 자료와 완료 범위

서울2018-01-06~2026-09-20·부산2018-01-05~2026-09-18의151,074출전·13,928경주를 연결했다. 게이트151,115행과의 차이41행은 기존 구간 품질 모집단 차이다.19개 지역×거리 모두의 관측 범위를 표시하되, 모형은 기존 이상치 원장의149,624출전·14개 지역×거리만 적합한다.4MAD 후148,338출전이다.89모형·27,154시간 프로필·4,750조합 행을 정리했다. 영천은 제외했다.

모형 거리: 서울1000/1200/1300/1400/1600/1700/1800/2000m, 부산1000/1200/1300/1400/1600/1800m. 서울1900/2300m·부산1900/2000/2200m는 표본만 제공한다. 실전1000m는 최근 기간 모형을 적합할 표본이 부족하며 주행심사와 구분한다.

4,750행은 번호별2,090행·그룹별1,995행·외측−내측665행의 비교 목록이다. 번호와 그 번호에서 환산한 그룹은 중복된 증거이며 독립4,750표본이 아니다. 각 지역×거리마다5상태×50비교를 마련했다. 실제 없는 두수/상태는 미관측이며 물리적으로 가능한 모든 출발칸을 뜻하지 않는다. 전체4MAD의 상태 분류는 다음과 같다.

{status}

미관측1,258행에는 모형 자체가 없는 거리의 빈 조합도 포함한다. `model_unavailable`444행은 관측은 있지만 해당 모형이 없는 경우다. 지원804행은 최소50출전·50경주·20날짜의 각 비교집단과 선형 식별 조건을 충족한 참고치다. 모든 상태에 보정이 완성됐다는 뜻은 아니다. `coverage_grid.csv`는5개 기간별 지원/효과/구간/q를 각각 보존한다.

## 서울1200m11두 경주의 상태 차이

외측−내측은 양수면 외측이 느리고 음수면 외측이 빠르다.11두의 내측은 마번 순서 앞4두, 중간은 그다음3두, 외측은 뒤4두다. 마번1~11이 연속일 때1~4/5~7/8~11번과 일치한다. 이 거리11두 원천788경주 중94경주는 마번이 연속되지 않으므로 실제 번호 구간으로 고정하면 안 된다. 아래95% 구간은 개별 비교의 구간이며q는 같은 검정 가족 전체의 다중비교를 조정한 값이다.

{maintable}

포화−건조 변화: 전체{single.effect_seconds_full:.3f}초,95%구간[{single.ci_low_full:.3f},{single.ci_high_full:.3f}],q={single.q_full:.4f}; 최근{single.effect_seconds_recent:.3f}초,95%구간[{single.ci_low_recent:.3f},{single.ci_high_recent:.3f}],q={single.q_recent:.4f}. 이는 상태별 외내차 자체가 아니라 두 상태의 외내차를 뺀 상호작용이다. 포화 외내차의 구간은0을 포함하므로 ‘외측 우위’로 바꾸어 읽지 않는다.

전체 무제외−0.404초·양끝5% 제외−0.332초·완결2024~2025년−0.462초로 방향은 같았다. 다만 무제외q=0.276·양끝5%q=0.095이며 완결2년은 최소50경주 지원 미달이다. 경주만 통제한 감도 모형도 전체−0.373초·최근−0.371초의 같은 방향이나 전체q=0.083이다. 따라서 유망한 후속 관찰이며 모든 감도 조건을 통과한 확정 보정은 아니다.

최근 서울1300/1400m11두 양호−건조 변화도 관찰됐지만 전체·최근에서 함께q<0.05였던 조합은 아니다. 부산은 상태 간 상호작용이 이 기준에서 남지 않았다. 효과가 없다고 입증한 것이 아니라, 세분 표본과 불확실성이 크다는 뜻이다.

![서울1200m11두의 상태별 외내차와 건조 대비 변화](outputs/seoul1200_moisture_gate.png)

## 서울·부산1600m의 번호별 확인

서울1600m10두10번의 건조 기록 차이는 전체+0.710초·최근+0.807초였지만q=0.492·0.094다. 양호·다습·포화·불량은 해당 번호50경주 지원에도 미달했다. 포화 추정치가 작아 보인다고 건조와 유의하게 다르다고 판단할 수 없다.

부산1600m12두1번은 건조에서 전체+0.445초·최근+0.618초지만q=0.492·0.419다. 다습·포화·불량은 전체부터 소표본이고 최근 양호도 지원 미달이다. 이전 상태를 합친 번호별 차이와 기준 모집단·모형이 다르므로 그대로 대체하지 않는다. 이번 전체·최근 주 모형에서 **번호별q<0.05는 모두0개**였다.

## 계산과 해석

같은 경주와 같은 말의 효과를 동시에 통제해 상태×게이트를 추정했다. 한 경주 공통 함수율·월·등급은 경주 효과에 흡수된다. 기존 함수율 보정값을 모든 출전마에 더해도 경주 안 대비는 변하지 않는다. 나이·중량·체중·레이팅·과거 이력 등은 통제 변수이며 현재 실제 위치는 넣지 않았다. 부적합·기수·전개 선택과 상태×시대/월의 추가 상호작용까지 모두 통제한 인과 추정은 아니다.

정확1~10/1~12번이 모두 있는 경주는 번호별로, 나머지는6~9/10/11/12/13두 이상 구간의3그룹으로 계산했다. 정확1~10/1~12번이 모두 존재하는 블록의 그룹은 각각1~3/4~7/8~10번과1~4/5~8/9~12번이다. 취소 등에 따른 마번과 실제 출발칸 차이는 남는다. 그룹 비교는 게이트 위치이며 실제 마군 내 내외측 주행이 아니다. 기존 실제 주행위치 연구는 지점·마군별 별도 결과를 유지한다.

각 상태의 번호 차이는 같은 두수 전체 번호 평균 대비다. 그룹은 해당 상태의 원래 경주별 그룹 비중 평균으로 중심화한다. 건조와의 상태차 검정은 번호 중심 대비 또는 외측−내측 대비를 직접 빼고 공분산까지 반영한다. BH는 기간×흡수방식×번호/그룹/외내차/상호작용별로 모든 지역·거리를 함께 조정했다. 한 상태만 유의하다는 이유로 두 상태가 다르다고 판단하지 않는다.

지원 밖에도 식별되는 참고 추정치는 보존하지만 보정 후보에는 쓰지 않는다. 식별되지 않은63개 전체4MAD 비교의 효과·구간은null이다. 소표본에0초를 채우지 않는다. 후보0은 적용 보류 상태이며 효과0의 측정치가 아니다.

후보는5개 주 모형의 엄격 지원·2개 감도 모형의 지원·모두 같은 방향·전체/최근q<0.05를 요구했다.95% 구간의0에 가까운 끝을50%만 취하고표본 수축·0.10초 상한·0.01초 단위 버림을 적용한다. 해당 상태·두수의 전체 번호/그룹이 엄격 지원될 때만 평균0으로 중심화한다. 이번에는 원시 후보부터0개였다. 번호와 그룹, 기존 게이트 효과를 중복 더하지 않는다.

## 검증과 산출물

[독립 검증](outputs/verification.json): 명시적 마필·경주 더미의8개 독립 해와4개 군집 공분산 대조를 통과했다. 대비 최대 오차{verification["max_contrast_error_seconds"]:.3g}초, 상태차8,229식·27,154프로필·4,750표본행·2,653후보행을 검사했고 입력 해시는 변하지 않았다. 후향 전체자료에서 정한 이상치 경계를 최근자료에도 사용했으므로 당시 실시간에 만들 수 있었던 기준은 아니다. 다음 경주 예측 개선 검증은 사용자 지시에 따라 별도 후속으로 남긴다.

[계획](PLAN.md) · [전체 시간 프로필](outputs/seconds_profiles.csv) · [전체 조합 표](outputs/coverage_grid.csv) · [거리별 지원](outputs/distance_coverage.csv) · [서울1200m 상세](outputs/seoul1200_11_focus.csv) · [1600m 상세](outputs/1600_number_focus.csv) · [후보](outputs/correction_candidates.csv) · [게시 요약](PUBLICATION.md) · [웹 데이터](outputs/web_moisture_gate_seconds.json) · [출처](SOURCES.md) · [용량 명세](outputs/artifact_inventory.json).
"""
    (HERE / "README.md").write_text(main)
    publication = """# 주로상태와 게이트 유불리

같은 거리라도 주로상태에 따라 게이트의 상대적인 기록 차이가 달라질 수 있다. 서울1200m11두 경주는 건조에서 마번 순서 뒤4두인 외측 그룹이 앞4두인 내측 그룹보다 전체약0.31초·최근약0.29초 느렸다. 포화에서는 외내차가 작아졌고, 건조 대비 변화는 전체−0.42초·최근−0.42초였다.

이 수치는 ‘포화 때 외측이0.42초 빠르다’는 뜻이 아니다. 건조 때의 외측 불리함이 포화 때 줄어든 비교이며, 포화 자체의 외내차는 불확실하다. 전체·최근에서는 상태 간 차이가 다중비교를 통과했지만 무제외·양끝5%·완결2년의 모든 검증을 통과한 것은 아니다.

서울1600m10번과 부산1600m1번도 건조에서 느린 방향이 보였으나, 상태별 번호 비교는 표본과 다중비교 기준이 충분하지 않았다. 모든 말에 같은 게이트 보정 초를 더하기는 이르다. 새 게이트 시간 보정은 보류하며 기존 완주시간 함수율 보정과 월 후보를 유지한다.

서울·부산2018년~2026년9월,19개 지역×거리의 관측 조합을 정리했다. 시간 모형은14개 지역×거리이며 희소 장거리에는 값을 채우지 않는다. 게이트 내외측은 상대 마번 위치이고 실제 레일에서의 거리나 마군 내 주행위치와 구분한다. 다음 경주 예측 개선은 아직 이 연구에서 평가하지 않았다.

[방법과 전체 결과](README.md) · [조합별 근거](outputs/coverage_grid.csv).
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    sources = """# 고정 출처와 해시

모든 자료는 기존 로컬 연구 산출물의 읽기 전용 재사용이다. 이번에 새 API·DB 조회는 없다. 과거 원천 출처는 앞 연구 문서에 보존되어 있다.

"""
    for name, digest in summary["input_sha256"].items():
        path = A.ROOT / name
        import os

        sources += f"- [{path.name}]({os.path.relpath(path, HERE)}): SHA-256 `{digest}`\n"
    sources += "\n[직전 시간 연구](../20261008_gate_lateral_seconds/README.md) · [이상치·시간 보정 연구](../20261008_record_normalization_seconds/README.md).\n"
    (HERE / "SOURCES.md").write_text(sources)

    def records(df):
        return json.loads(df.to_json(orient="records", force_ascii=False))

    payload = dict(
        title="주로상태와 게이트 시간 차이",
        version="2026-10-08",
        status="research_only",
        correction_status="pending_zero",
        data_end={"서울": "2026-09-20", "부산": "2026-09-18"},
        summary=summary,
        coverage_grid=records(grid),
        focus=records(focus),
        number_focus=records(numbers),
        interactions=records(intersections),
        candidates=records(candidates),
        notes=[
            "effect positive = slower; correction sign opposite",
            "null = unobserved/nonestimable/model unavailable; unsupported estimates are reference only",
            "number/group/outer-inner rows overlap; do not add",
            "gate thirds are program-order groups, not actual lateral running positions",
        ],
    )
    (OUT / "web_moisture_gate_seconds.json").write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
    )
    central = HERE.parent / "conclusions/04D_MOISTURE_GATE_SECONDS.md"
    central.write_text(
        """# 函数율 상태와 게이트 시간 차이

서울1200m11두에서 건조 때의 외측−내측+0.305초가 포화에서−0.118초로 작아졌다. 건조 대비 변화는 전체−0.423초(q=0.0294)·최근−0.419초(q=0.0395)로, 전체·최근 다중비교에서 함께 남은 상태 간 차이는 이 조합 하나였다. 포화 자체의 외내차는 불확실하며 외측 확정 우위나0.42초 자동 보정을 뜻하지 않는다. 무제외·양끝5% 감도는q<0.05 미달, 완결2024~2025년은 최소 경주수 미달이다.

서울1600m10두10번·부산1600m12두1번의 건조 추정은 느린 방향이나 전체·최근 번호별 다중비교를 통과하지 못했다. 모든 상태·번호의 보정 완성은 아니다. 새 게이트 후보0개이며 기존 전체시간 함수율 채택·월 후보·게이트 추가 보류 상태를 유지한다.

19개 지역×거리의5상태×두수/번호/그룹4,750비교 행을 마련했다. 전체4MAD 지원804·소표본2,181·미관측1,258·관측은 있으나 모형 없음444·식별 불가63행이다. 번호와 환산 그룹은 중복 증거다. 모형은14개 지역×거리89개이고27,154프로필을 검증했다. 경주와 마필 고정효과를 통제한 후향 비교이며 실제 내외측 주행 및 인과 효과와 구분한다. 영천·풍향·풍속·주로빠르기 제외, 운영 변경·다음 경주 예측 검증 없음.

[원 보고서](../20261008_moisture_gate_seconds/README.md) · [전체 조합](../20261008_moisture_gate_seconds/outputs/coverage_grid.csv) · [독립 검증](../20261008_moisture_gate_seconds/outputs/verification.json) · [게시 요약](../20261008_moisture_gate_seconds/PUBLICATION.md).
""".replace("函数율", "함수율")
    )
    print("Reports and web payload written")


if __name__ == "__main__":
    main()

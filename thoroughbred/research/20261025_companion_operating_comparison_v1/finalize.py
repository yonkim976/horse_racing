"""Archive the companion comparison and append isolated central records."""

import importlib.util
import json
import re
import analyze as c

CONCLUSION = c.R / "conclusions/58R_COMPANION_OPERATING_COMPARISON.md"
ENGINE = c.ROOT / "production_models/thoroughbred_training_state_20261025_v1/archive_release.py"
spec = importlib.util.spec_from_file_location("companion_archive_helpers", ENGINE)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
a.HERE, a.ROOT, a.RESEARCH = c.HERE, c.ROOT, c.R
a.CONCLUSION, a.INVENTORY = CONCLUSION, c.OUT / "artifact_inventory.json"
a.MARKER = "companion_operating_comparison_20261025"
a.BEFORE = json.loads((c.OUT / "preexisting_files.json").read_text())
a.ADDITIONAL, a.PREVIOUS_BYTES = [CONCLUSION], c.PREVIOUS_BYTES
original_inventory = a.inventory


def inventory():
    v = original_inventory()
    v["study"] = v.pop("release")
    v["summary"]["previous_work_new_bytes"] = v["summary"].pop("previous_ten_studies_new_bytes")
    v["excluded"] = (
        "Referenced prediction/model/DB assets and transient caches; matched derived rank ledger and comparison outputs are included."
    )
    return v


a.inventory = inventory


def pct(x):
    return f"{100 * x:.2f}%"


def pp(x):
    return f"{100 * x:+.2f}%p"


def ci(x):
    return f"{100 * x[0]:+.2f}~{100 * x[1]:+.2f}%p"


def reports():
    c.require(json.loads((c.OUT / "verification.json").read_text())["status"] == "passed")
    result = json.loads((c.OUT / "results.json").read_text())
    lookup = {(x["scope"], x["meet"]): x for x in result["groups"]}
    allm = lookup["all_races", 0]["metrics"]
    main = allm[c.PRIMARY]
    lines = [
        "# 축 이외 동반 입상마도 이전 운영 모델보다 잘 찾는가",
        "",
        "**동반 후보의 개별 적중률이 전반적으로 높아졌다는 근거는 없다. 다만 추천 상위3두가 실제 입상3두와 모두 일치한 경주는101→121건으로 늘었다. 축 개선을 동반 후보 전체의 개선으로 일반화하면 안 된다.**",
        "",
        "2026-10-25, 서울733·부산525, 합계1,258경주13,315출전의 같은 공식말ID·마번·착순을 비교했다. 현재는 personal_t2_2026, 이전은 보존된 thoroughbred-main-20260919-v1다. ‘추천순위’는 우승순위가 아닌 말별Top3확률(A) 순위다. 이전 비교와 같은1,258경주이며 최근 실험의1,288경주와 다르다. 학습은 하지 않았다.",
        "",
        "## 추천순위별 실제 Top3 적중",
        "",
        "| 추천순위 | 이전 적중/1,258 | 현재 적중/1,258 | 적중률 이전→현재 | 차이 | 경주일95%구간 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for rank in range(1, 6):
        m = allm[f"rank{rank}_hit"]
        lines.append(
            f"| {rank}순위{'(축)' if rank == 1 else ''} | {int(m['old_total'])} | {int(m['current_total'])} | {pct(m['old_mean'])}→{pct(m['current_mean'])} | {pp(m['difference'])} | {ci(m['ci95'])} |"
        )
    lines += [
        "",
        "2~4순위는 점추정이 낮아졌고5순위는 조금 높아졌다. 각 동반 순위 차이의 구간은 모두0을 포함한다. 따라서 확정 악화라고 단정하지도, 동반마까지 전반적으로 좋아졌다고 주장하지도 않는다.",
        "",
        "## 동반 후보4두의 포괄력",
        "",
        f"주지표인 **축을 제외한 추천2~5순위4두에서 두 두 이상 입상한 경주**는 {int(main['old_total'])}→{int(main['current_total'])}건, {pct(main['old_mean'])}→{pct(main['current_mean'])}였다. 차이{pp(main['difference'])}, 95%구간{ci(main['ci95'])}로 개선 근거가 없다. 새 적중156경주·상실179경주로 순감23경주다.",
        "",
        "동반4두에서 찾은 실제입상마는 총1,980→1,953두, 경주당1.574→1.552두였다. 축 적중은30건 늘었지만 동반 후보 적중은27두 줄어, 상위5두 전체가 찾은 입상마 수는2,780→2,783두로3두만 늘었다. 전체 후보풀의 포괄력은 거의 같은 모습이며, 인과적으로 재배치 효과만 있었다고 확정하는 분석은 아니다.",
        "",
        "| 범위 | 경주 | 동반4두에서2두 이상 적중 | 비율 이전→현재 | 차이95%구간 |",
        "|---|---:|---:|---:|---:|",
    ]
    for meet, name in [(0, "전체"), (1, "서울"), (3, "부산")]:
        row = lookup["all_races", meet]
        m = row["metrics"][c.PRIMARY]
        lines.append(
            f"| {name} | {row['races']} | {int(m['old_total'])}→{int(m['current_total'])} | {pct(m['old_mean'])}→{pct(m['current_mean'])} | {ci(m['ci95'])} |"
        )
    lines += [
        "",
        "## 함께 맞히는 사건과 후보풀의 차이",
        "",
        "| A순위에 고정한 선택 | 이전 | 현재 | 차이 |95%구간|",
        "|---|---:|---:|---:|---:|",
    ]
    labels = {
        "companion2_both": "추천2·3순위 동시입상(축 적중 무관)",
        "top3_all3": "추천상위3두가 입상3두 전원",
        "top4_all3": "추천상위4두 안에 입상3두 전원",
        "top5_all3": "추천상위5두 안에 입상3두 전원",
        "axis_trio6": "A축+동반4두의 삼복6조합",
    }
    for key, label in labels.items():
        m = allm[key]
        lines.append(
            f"| {label} | {int(m['old_total'])} / {pct(m['old_mean'])} | {int(m['current_total'])} / {pct(m['current_mean'])} | {pp(m['difference'])} | {ci(m['ci95'])} |"
        )
    lines += [
        "",
        "개별 적중률과 동시 적중 사건은 다른 지표다. 상위3두 전원 일치는 +20경주·+1.59%p(95%+0.40~+2.82%p)로 후향 개선 신호가 있지만, 여러 보조지표를 함께 살펴본 결과이므로 독립 확증검정은 아니다. 상위5두 전원 포괄은448→472건으로 늘었지만 구간은0을 포함한다.",
        "",
        "A축+동반4두6조합은 A순위1위를 반드시 포함한6장이며, 이전B 공동분포에서 직접 상위6장을 뽑는 정책과 다르다. 삼복1조합도 A상위3두와 이전B최상위집합이 다를 수 있으므로 혼동하지 않는다.",
        "",
        "## 축을 같게 놓은 진단",
        "",
        "두 모델이 같은 축을 고른815경주 중, 그 공통축이 실제로 입상한565경주를 똑같이 비교했다. 서로 다른 축 성공 표본을 비교하지 않았다.",
        "",
        "| 동반마 선택 | 이전/565 | 현재/565 | 차이95%구간 |",
        "|---|---:|---:|---:|",
    ]
    common = lookup["same_axis_and_axis_hit", 0]["metrics"]
    for key, label in [
        ("companion2_both", "추천2·3순위가 나머지2두 모두 적중"),
        (c.PRIMARY, "추천2~5순위에 나머지2두 모두 포함"),
    ]:
        m = common[key]
        lines.append(
            f"| {label} | {int(m['old_total'])} / {pct(m['old_mean'])} | {int(m['current_total'])} / {pct(m['current_mean'])} | {ci(m['ci95'])} |"
        )
    lines += [
        "",
        "공통축이 맞았다는 조건에서는 상위 동반2두의 정확한 동시 선택이68→83건으로 증가했다. 반면 동반4두 안에 나머지2두를 모두 담은 경우는252→256건으로 차이가 작았다. 이 조건은 정답을 확인한 뒤의 진단이며 실제 경주 선택 규칙이나 전체 성과로 바꾸지 않는다.",
        "",
        "## 실제2착·3착 말을 찾았는가",
        "",
        "질문의1위가 실제 우승마를 뜻한 경우를 위해 실제2착·3착 말의 추천 포함률도 별도로 계산했다. 정답을 미리 알고 추천에서 제외하거나 새로 고르지 않았다.",
        "",
        "| 실제 착순 | 추천 범위 | 이전 | 현재 | 차이95%구간 |",
        "|---|---|---:|---:|---:|",
    ]
    for finish in [2, 3]:
        for k in [3, 5]:
            m = allm[f"actual{finish}_top{k}"]
            lines.append(
                f"| 실제{finish}착 | 상위{k}두 | {int(m['old_total'])} / {pct(m['old_mean'])} | {int(m['current_total'])} / {pct(m['current_mean'])} | {ci(m['ci95'])} |"
            )
    lines += [
        "",
        "상위5두에서 실제2착 포착은921→936건으로 늘었지만 실제3착은825→803건으로 줄었다. 후자의 지역별 감소는 서울−8건·부산−14건이다. 차이 구간은0을 포함하지만, 다음 개선에서 실제3착 후보의 누락을 점검할 이유는 있다. 특정후보의 우승 적중과 단순 동일시하지 않는다.",
        "",
        "## 같은 예산의 기존 조합 비교",
        "",
        "복승/복연은 이전A 공동분포에서 같은1/3선택을 재구성한 비교이며, 실제 게시/구매 원장은 아니다. 삼복은 이전B 원래 확률과 현재 공동분포의 같은6조합이다. 목표별A/B/C 분포를 섞지 않았다.",
        "",
        "| 지역 | 복승3조합 | 복연3조합 | B삼복6조합 |",
        "|---|---:|---:|---:|",
    ]
    for row in result["native_pool_comparison"]:
        text = {0: "전체", 1: "서울", 3: "부산"}[row["meet"]]
        values = [
            f"{int(row['metrics'][key]['old_total'])}→{int(row['metrics'][key]['current_total'])}"
            for key in ["quinella_three", "qpl_three", "trio_six"]
        ]
        lines.append("| " + text + " | " + " | ".join(values) + " |")
    lines += [
        "",
        "따라서 이전에 보고한 삼복6조합384→408건의 증가와 이번 동반 후보의 개별 적중률 감소는 모순이 아니다. 선택 정책과 채점 사건이 다르다. 부산 복연3조합314→299건 감소도 그대로 유지된다.",
        "",
        "## 검증과 해석 범위",
        "",
        "완전명부13,315출전과 정답을대조했다. 저장확률에서26,630개순위를별도Python정렬로확인했고,62,900개경주·지표값을독립집합연산으로재계산했다. A축+동반4두의15,096개삼복티켓을직접열거했고,9개주지표bootstrap구간과선행승식집계·구간도재현했다. 기존축800→830건과축선택도선행원장에일치했다.",
        "",
        "개별순위표는 말별 입상확률의 실측 적중률이다. 모델이 출력한 예측확률 평균 자체를 적중률로 표현하지 않았다. 예측확률 평균은 결과JSON의rank2_predicted~rank5_predicted에 별도로 보존했다.",
        "",
        "2026년1월~9월의 반복 사용한 후향 재구성 자료다. 실제 사전 게시 성적·독립 미래검증·수익률 비교가 아니며, 모델 구조/학습시대 차이 때문에 차이를 조교 하나의 인과효과로 해석하지 않는다. 신규 학습·운영 변경·DB쓰기·새 수집은 없다.",
        "",
        "[계획](PLAN.md) · [모델 식별](outputs/model_identity.json) · [출처해시](outputs/input_manifest.json) · [전체 결과](outputs/results.json) · [독립 검증](outputs/verification.json) · [파생 순위](outputs/matched_ranks.parquet) · [미게시 요약](PUBLICATION.md) · [용량 명세](outputs/artifact_inventory.json)",
    ]
    (c.HERE / "README.md").write_text("\n".join(lines) + "\n")
    public = [
        "# 축과 동반 후보의 성적은 따로 봐야 합니다",
        "",
        "게시용 초안·미게시. 2026-10-25.",
        "",
        "같은 서울·부산1,258경주에서 새 운영 모델의 축 입상 적중은800→830건으로 늘었습니다. 그러나 추천2순위는683→672건,3순위는534→519건으로 감소했습니다. 동반4두 중2두 이상 입상한 경주도695→672건으로 줄었으며 차이 구간은0을 포함합니다. 동반 후보의 개별 정확도가 전반적으로 좋아졌다고 말할 근거는 없습니다.",
        "",
        "함께 맞히는 성적에는 개선이 있었습니다. 추천상위3두가 실제입상3두와 전부 일치한 경주는101→121건,상위5두 안에3두가 모두 포함된 경우는448→472건이었습니다. 상위5두가 찾아낸 입상마 전체수는2,780→2,783두로 거의 같았습니다. 축의 향상과 후보풀 전체의 포괄력은 같은 지표가 아닙니다.",
        "",
        "실제3착 말이 상위5두 안에 든 경주는825→803건으로 줄었습니다. 확정 악화라는 뜻은 아니지만 이후 개선에서 점검할 부분입니다. 과거 재평가이며 실제 사전 게시 성적이나 수익률 보장은 아닙니다. 운영 모델 변경은 없습니다.",
        "",
        "[전체 보고서](README.md) · [전체 결과](outputs/results.json) · [검증](outputs/verification.json)",
    ]
    (c.HERE / "PUBLICATION.md").write_text("\n".join(public) + "\n")
    c.require(
        not CONCLUSION.exists() or "동반 입상마" in CONCLUSION.read_text(),
        "Conclusion name conflict",
    )
    CONCLUSION.write_text(
        "# 현재·이전 운영 모델의 동반 입상마 비교\n\n2026-10-25, 연구58R. 서울733·부산525의같은1,258경주·13,315출전을비교했다. 현재personal_t2_2026,이전thoroughbred-main-20260919-v1의A확률순위다.\n\n"
        "축800→830건이지만2순위683→672,3순위534→519,4순위415→411,5순위348→351이었다. 동반4두 중2두이상입상한경주는695→672(55.25→53.42%,−1.83%p,95%−4.88~+1.14%p)로개선근거가없다. 개별순위 차이의구간도0을포함한다.\n\n"
        "추천상위3두전원입상은101→121(8.03→9.62%,+1.59%p,95%+0.40~+2.82)로후향개선신호가있으나많은보조지표의반복개발기간이다. 상위5두전원포괄448→472,전체입상마수2,780→2,783으로후보풀포괄력은거의같다. 같은축이입상한565경주에서상위동반2두정확선택68→83,동반4두포괄252→256이었다. 조건부진단을운영선택으로바꾸지않는다.\n\n"
        "실제2착의상위5두포착921→936,실제3착825→803으로3착누락을다음에점검할필요가있다. 기존B삼복6조합384→408과A축고정6조합361→375는서로다른정책이다. 부산복연3조합314→299감소도유지된다. 새학습·운영변경·DB쓰기없음. 독립정렬26,630개·지표62,900개·티켓15,096개·구간9개를검증했다.\n\n"
        f"[원문](../{c.HERE.name}/README.md) · [결과](../{c.HERE.name}/outputs/results.json) · [검증](../{c.HERE.name}/outputs/verification.json) · [용량](../{c.HERE.name}/outputs/artifact_inventory.json)\n"
    )


def manifest():
    p = c.R / "conclusions/source_manifest.json"
    before = c.sha(p)
    v = json.loads(p.read_text())
    for key, sources in [
        ("sources", [x for x in a.owned_paths() if x not in [CONCLUSION, a.INVENTORY]]),
        ("conclusions", [CONCLUSION]),
    ]:
        lookup = {x["path"]: i for i, x in enumerate(v[key])}
        for source in sources:
            row = {"path": str(source.relative_to(c.ROOT)), "sha256": c.sha(source)}
            if row["path"] in lookup:
                v[key][lookup[row["path"]]] = row
            else:
                v[key].append(row)
    v["data_end_by_study"][a.MARKER] = {
        "study": c.HERE.name,
        "start": "2026-01-02",
        "end": "2026-09-13",
        "matched_races": 1258,
        "matched_starters": 13315,
        "current_profile": c.NEW_PROFILE,
        "old_profile": c.OLD_PROFILE,
        "new_models": 0,
        "production_changed": False,
        "new_independent_test": False,
        "actual_live_publications_compared": False,
    }
    v["updated_at"] = "2026-10-25"
    c.require(c.sha(p) == before, "Concurrent manifest update")
    a.dump(p, v)


def indexes(s):
    title = "연구58R 축 이외 동반 입상마의 운영 모델 비교"
    note = "동일1,258경주 축800→830이나 동반2/3순위683→672·534→519. 동반4두2두이상695→672,상위3두전원101→121. 후보풀전체 개선 근거 부족·학습0."
    a.upsert(c.R / "README.md", f"[{title}]({c.HERE.name}/README.md): {note}")
    a.upsert(c.R / "conclusions/README.md", f"[{title}]({CONCLUSION.name}): {note}")
    a.upsert(
        c.R / "conclusions/SOURCES.md",
        f"[{title}]({CONCLUSION.name}) · [원문](../{c.HERE.name}/README.md) · [결과](../{c.HERE.name}/outputs/results.json) · [검증](../{c.HERE.name}/outputs/verification.json). {note}",
    )
    a.upsert(
        c.R / "ARTIFACT_SIZE_LOG.md",
        "| 날짜 | 작업 | 신규 파일 | 신규 bytes | MiB | 수정 파일 | 수정 최종 bytes | 순증감 bytes | 명세 |\n|---|---|---:|---:|---:|---:|---:|---:|---|\n"
        + f"| 2026-10-25 | 동반 입상마 운영 비교 | {s['new_file_count']} | {s['new_bytes']} | {s['new_mib']:.6f} | {s['modified_file_count']} | {s['modified_final_bytes']} | {s['modified_delta_bytes']:+d} | [명세]({c.HERE.name}/outputs/artifact_inventory.json) |\n\n최대 `{s['largest_file']['path']}` {s['largest_file']['bytes']:,}bytes. 누적{s['combined_new_bytes']:,}/300,000,000bytes. 기존모델/DB/전체예측참조·복제없음. 다른작업순증{s['modified_external_delta_bytes']:,}bytes 보존,이번수정순증{s['modified_task_delta_bytes']:,}bytes.",
    )


def main():
    c.check()
    reports()
    p = c.HERE / "concurrent_updates.json"
    if not p.exists():
        a.dump(
            p,
            {
                n: {
                    "external_delta_bytes": (c.ROOT / n).stat().st_size - old["bytes"],
                    "handling": "Append own marker block / merge own source entries only",
                }
                for n, old in a.BEFORE.items()
            },
        )
    if not a.INVENTORY.exists():
        a.dump(a.INVENTORY, {})
    s = inventory()["summary"]
    for _ in range(32):
        indexes(s)
        manifest()
        v = inventory()
        a.dump(a.INVENTORY, v)
        after = inventory()
        if v == after and s == after["summary"]:
            break
        s = after["summary"]
    else:
        raise RuntimeError("Inventory did not converge")
    c.require(json.loads(a.INVENTORY.read_text()) == inventory())
    links = 0
    for p in [c.HERE / "README.md", c.HERE / "PUBLICATION.md", CONCLUSION]:
        for link in re.findall(r"\]\(([^)]+)\)", p.read_text()):
            if "://" not in link and not link.startswith("#"):
                c.require((p.parent / link.split("#")[0]).exists(), "Missing link: " + link)
                links += 1
    m = json.loads((c.R / "conclusions/source_manifest.json").read_text())
    own = {str(p.relative_to(c.ROOT)) for p in a.owned_paths() if p != a.INVENTORY}
    hashes = [x for key in ["sources", "conclusions"] for x in m[key] if x["path"] in own]
    c.require(len(hashes) == len(own))
    c.require(all(c.sha(c.ROOT / x["path"]) == x["sha256"] for x in hashes))
    print(
        json.dumps(
            {"status": "passed", **s, "links_checked": links, "source_hashes_checked": len(hashes)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

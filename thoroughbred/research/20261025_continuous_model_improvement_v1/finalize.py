"""Write experiment findings and merge only this study's central records."""

import importlib.util
import json
import re
import research as c

CONCLUSION = c.R / "conclusions/58Q_CONTINUOUS_MODEL_IMPROVEMENT.md"
ENGINE = c.ROOT / "production_models/thoroughbred_training_state_20261025_v1/archive_release.py"
spec = importlib.util.spec_from_file_location("release_archive_helpers", ENGINE)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
# Reuse only generic append, hash and self-inclusive inventory functions.
a.HERE, a.ROOT, a.RESEARCH = c.HERE, c.ROOT, c.R
a.CONCLUSION, a.INVENTORY = CONCLUSION, c.OUT / "artifact_inventory.json"
a.MARKER = "continuous_model_improvement_20261025"
a.BEFORE = json.loads((c.OUT / "preexisting_files.json").read_text())
a.ADDITIONAL = [CONCLUSION]
a.PREVIOUS_BYTES = c.PREVIOUS_BYTES
SHARED_DOCS = [c.ROOT / n for n in a.BEFORE if n not in a.CENTRAL]
original_inventory = a.inventory


def current_inventory():
    value = original_inventory()
    value["study"] = value.pop("release")
    value["summary"]["previous_work_new_bytes"] = value["summary"].pop(
        "previous_ten_studies_new_bytes"
    )
    value["excluded"] = (
        "Referenced DB, full history/base features and prior models; transient caches and app-owned deleted automation. New feature deltas, fitted models and outputs are included."
    )
    return value


a.inventory = current_inventory


def report():
    result = json.loads((c.OUT / "results.json").read_text())
    c.require(json.loads((c.OUT / "verification.json").read_text())["status"] == "passed")
    lookup = {(x["variant"], x["year"], x["meet"]): x for x in result["groups"]}
    labels = {
        "report_context": "심판 맥락·말 제재",
        "past_bodymass": "과거 마체중",
        "axis_rank": "축 순위 학습",
    }
    conclusion = (
        "세 방향 모두 이번 정의와 설정에서 축 적중 개선을 확인하지 못했다. 현재 운영 모델을 유지한다."
        if not any(x["promising_historical_candidate"] for x in result["decisions"])
        else "사전 기준을 충족한 후향 후보가 있으며 독립 미래검증이 추가로 필요하다."
    )
    c.save(
        c.OUT / "decision.json",
        {
            "production_changed": False,
            "main_conclusion": conclusion,
            "candidates": result["decisions"],
            "weekly_automation_deleted": True,
            "three_planned_hypotheses_completed": True,
            "new_independent_test": False,
        },
    )
    lines = [
        "# 현재 채팅에서 이어간 운영 모델 개선 실험",
        "",
        "2026-10-25 · 서울·부산 · 주간 예약 삭제 · 세 가설 완료 · 운영 변경 없음.",
        "",
        "**" + conclusion + "**",
        "",
        "현재 운영 personal_t2의 입력·학습 절차를 기준으로 세 방향을 평가 전에 고정해 시험했다. 주 비교는 2026년 전체 1,288경주이며, 기준선은 846건(65.68%)이다. 이전 운영과 비교했던 1,258경주의 830건(65.98%)과는 분모가 다르다. 2024/25 비교는 당시 연도별 personal_t2 가중치이며 현재2026 가중치를 과거 학습경주에 적용하지 않았다.",
        "",
        "## 2026년 축1두의 적중",
        "",
        "| 후보 | 입력 수 | 기준→후보 적중 | 후보 적중률 | 차이 | 경주일95%구간 | 3후보 보정 구간 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, extra in c.VARIANTS.items():
        x = lookup[name, 2026, 0]["metrics"]["axis_top3"]
        interval = lambda key: f"{100 * x[key][0]:+.2f}~{100 * x[key][1]:+.2f}%p"
        lines.append(
            f"| {labels[name]} | {136 + len(extra)} | {int(x['baseline_total'])}→{int(x['candidate_total'])} | {100 * x['candidate_mean']:.2f}% | {100 * x['difference']:+.2f}%p | {interval('ci95')} | {interval('ci_family98_333')} |"
        )
    lines += [
        "",
        "세 방향을 살펴본 개발 결과다. 98.333% 구간은 주지표의 세 후보 탐색에 대한 Bonferroni 구간이며, 반복 연구·연관된 하위집단·장기간 같은 말의 상관까지 모두 해결하는 독립 확증검정은 아니다.",
        "",
        "## 전체 기간과 지역 안정성",
        "",
        "| 후보 | 2024–26 전체4,799경주 | 2026 서울 | 2026 부산 | 2026 축 변경 | 실패 구제 / 적중 상실 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in c.VARIANTS:
        allm = lookup[name, 0, 0]["metrics"]["axis_top3"]
        row = lookup[name, 2026, 0]
        region = [lookup[name, 2026, m]["metrics"]["axis_top3"] for m in [1, 3]]
        lines.append(
            f"| {labels[name]} | {int(allm['baseline_total'])}→{int(allm['candidate_total'])} | {int(region[0]['baseline_total'])}→{int(region[0]['candidate_total'])} | {int(region[1]['baseline_total'])}→{int(region[1]['candidate_total'])} | {row['axis_changes']} | {row['axis_rescued']} / {row['axis_lost']} |"
        )
    lines += [
        "",
        "연도·지역별 구간과 모든 지표는 전체 결과 JSON에 보존했다. 거리·등급 표는 설명용 진단이며 그 결과로 대상 경주를 줄이거나 유리한 조건만 선택하지 않았다.",
        "",
        "## 같은 예산의 조합과 확률 품질: 2026년",
        "",
        "| 후보 | 복승1/3 적중 | 복연1/3 적중 | 삼복6 적중 | Top3 Brier ↓ | 집합NLL ↓ | 순서NLL ↓ |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in c.VARIANTS:
        m = lookup[name, 2026, 0]["metrics"]
        pair = lambda k: f"{int(m[k]['baseline_total'])}→{int(m[k]['candidate_total'])}"
        lines.append(
            f"| {labels[name]} | {pair('quinella_one')} / {pair('quinella_three')} | {pair('qpl_one')} / {pair('qpl_three')} | {pair('trio_six')} | {m['runner_brier']['baseline_mean']:.6f}→{m['runner_brier']['candidate_mean']:.6f} | {m['trio_logloss']['baseline_mean']:.6f}→{m['trio_logloss']['candidate_mean']:.6f} | {m['ordered_logloss']['baseline_mean']:.6f}→{m['ordered_logloss']['candidate_mean']:.6f} |"
        )
    lines += [
        "",
        "말과 조합의 수를 고정한 비교다. 구매액·구매 시점 배당을 사용한 수익률 실험은 아니다. 축 개선과 조합 개선을 구별한다.",
        "",
        "## 실제 추가한 정보와 구조",
        "",
        "심판 후보는 이전 실전3회의 리포트 지원·언급 맥락과 최근90일 공식 말 제재 등12열이다. 문단에 여러 말이 같이 나오므로 접촉·출발·주행행태·마체 단어는 해당 말의 피해나 부진 원인으로 단정하지 않는다. 공식 말 제재는 직접 ID가 확인된 기록만 사용했다. 소급 추가사항은 제외했고 리포트 미관측을 무사고로 대체하지 않았다. 과거 실전·조교와 마찬가지로 사건일 제한을 지켰지만 역사적 공개시각은 미인증이다.",
        "",
        "과거 마체중 후보는 직전값, 최근 평균·변화·변동, 관측수, 이번 부담중량/직전 마체중 비율6열이다. 현재 모델에서 빠진 추가 정보이지만 과거 DB 관찰 연구에서 다룬 적은 있다. 당일 마체중을 쓰지 않았고, 비율을 현재 실제 체중에 대한 부담률로 표현하지 않는다.",
        "",
        "축 순위 후보는 같은136열과 binary Top3 정답으로 경주 내 LambdaRank를 학습했다. NDCG@1 조기종료와 고정 truncation3을 사용했다. 같은 전년도 자료에서 집합·집합 내 순서 온도를 각각 보정했다. 평가 정답으로 변수·seed·문턱을 고르지 않았다.",
        "",
        "## 시간 분할과 검증",
        "",
        "평가연도Y에2017..Y−3 초기학습/Y−2 조기종료/2017..Y−2 재학습/Y−1 확률 보정/Y 평가를 적용했다. 두 지역×세 연도×세 후보로 최종18개·초기18회 학습했다. 다른 트리 설정·seed20261004·최대800회·중단25는 기준선과 동일하다. 기준선 가중치6개는 참조했다.",
        "",
        "원천 재계산936값, 미래 기록 삽입936값, 직접 문단 정규식96검사를 통과했다. pandas 결측 비교의 검증 코드 수정1건은 첫 학습 전에 별도 원장에 남겼으며 특징과 계획은 바뀌지 않았다. 저장18모델의 보정·평가 점수를 재추론하고 온도를 별도 수학으로 대조했다. 54경주의 전체 순열을 직접 열거해 확률·축·조합·손실을 검산했고 모든 저장 출전마 확률 합·단조성을 확인했다. 주/전체 범위의6개 축 차이·구간을 별도 집계했다.",
        "",
        "이 기간은 이미 반복 사용한2024–2026년 후향 개발 자료다. 신선한 미래 성능이나 당시 실제 사전 게시 성적이 아니다. 운영 등록부·가중치·기존 예측·DB·제주는 변경하지 않았다.",
        "",
        "## 판단과 다음 단계",
        "",
    ]
    for d in result["decisions"]:
        lines.append(
            f"- {labels[d['variant']]}: 사전 기준의 유망 후보 판정 `{d['promising_historical_candidate']}`. 세 후보 보정 구간 양수 `{d['criteria']['primary_family_interval_positive']}`. 개별 조건은 결과 JSON에 보존했다."
        )
    lines += [
        "",
        "새 후보를 자동 운영 승격하지 않는다. 다음 연구는 실패한 정보 묶음을 반복 조정하기보다, 이번 개선·악화가 생긴 경주를 출처와 대조해 새로운 정보가 있는지 판단하고 사전 스냅샷을 확보하는 방향으로 진행한다. 이번 단계의 세 가설을 모두 시험한 뒤 결과를 보고한다.",
        "",
        "## 예약 삭제와 현재 작업 방식",
        "",
        "사용자 지시로 ‘서울·부산 운영 모델 지속 개선’ 주간 heartbeat를 삭제했고 앱에서 삭제 완료를 확인했다. 현재 연구는 이 채팅의 지속 목표로 수행했다. 운영 모델 폴더의 예약 상태와 개선 절차도 갱신했다. 주간 예약을 새로 만들거나 다른 채팅에 메시지를 보내지 않았다.",
        "",
        "[계획](PLAN.md) · [입력 해시](outputs/input_manifest.json) · [원천 지원](outputs/source_audit.json) · [전체 결과](outputs/results.json) · [검증](outputs/verification.json) · [수정 원장](outputs/implementation_repairs.json) · [예약 삭제](outputs/automation_deletion.json) · [미게시 요약](PUBLICATION.md) · [용량 명세](outputs/artifact_inventory.json)",
    ]
    (c.HERE / "README.md").write_text("\n".join(lines) + "\n")
    primary_lines = [
        "# 운영 모델을 더 개선하기 위해 세 방향을 시험했습니다",
        "",
        "게시용 초안·미게시. 2026-10-25. 서울·부산.",
        "",
        "현재 기본 모델에 과거 심판 맥락·공식 말 제재, 과거 마체중을 각각 추가하고, 별도로 축 선택을 겨냥한 순위 학습을 시험했습니다. 같은2026년1,288경주의 기존 축 적중은846건입니다.",
        "",
    ]
    for name in c.VARIANTS:
        m = lookup[name, 2026, 0]["metrics"]["axis_top3"]
        primary_lines.append(
            f"- {labels[name]}: {int(m['candidate_total'])}건({100 * m['candidate_mean']:.2f}%), 기존 대비{100 * m['difference']:+.2f}%p. 95%구간{100 * m['ci95'][0]:+.2f}~{100 * m['ci95'][1]:+.2f}%p."
        )
    primary_lines += [
        "",
        "같은 과거 기간을 반복 연구한 개발 결과이며 독립 미래검증이 아닙니다. 현재 체중·배당을 쓴 결과가 아니며, 심판 문단의 단어를 그 말의 피해나 원인으로 확정하지 않습니다. 예측 수와 조합 예산을 유지했고 세 후보 탐색의 불확실성도 따로 확인했습니다. 운영 모델은 유지합니다.",
        "",
        "주간 예약은 사용자 요청으로 삭제했습니다. 이번 연구는 같은 채팅에서 이어서 실제 학습·평가·검증을 수행했습니다.",
        "",
        "[전체 보고서](README.md) · [전체 수치](outputs/results.json) · [검증](outputs/verification.json)",
    ]
    (c.HERE / "PUBLICATION.md").write_text("\n".join(primary_lines) + "\n")
    c.require(
        not CONCLUSION.exists() or "현재 채팅에서 이어간" in CONCLUSION.read_text(),
        "Conclusion name conflict",
    )
    CONCLUSION.write_text(
        "\n".join(lines[:15])
        + "\n\n세 가설의 시간순 학습·검증을 마쳤다. 운영 변경과 독립 미래검증은 아니다. 주간 예약은 삭제하고 현재 채팅의 지속 목표로 수행했다.\n\n"
        + f"[전체 보고서](../{c.HERE.name}/README.md) · [결과](../{c.HERE.name}/outputs/results.json) · [검증](../{c.HERE.name}/outputs/verification.json) · [용량](../{c.HERE.name}/outputs/artifact_inventory.json)\n"
    )
    log = c.ROOT / "production_models/thoroughbred_training_state_20261025_v1/IMPROVEMENT_LOG.md"
    block = (
        "\n\n<!-- continuous_model_improvement_results:start -->\n세 가설의18개 모델 학습·평가·원천/재추론 검증을 완료했다. "
        + " / ".join(
            f"{labels[n]} 2026축{int(lookup[n, 2026, 0]['metrics']['axis_top3']['candidate_total'])}건"
            for n in c.VARIANTS
        )
        + f". 기준846/1,288건. [상세 결과](../../thoroughbred/research/{c.HERE.name}/README.md). 운영 유지·독립 미래검증 아님.\n<!-- continuous_model_improvement_results:end -->\n"
    )
    old = log.read_text()
    if "<!-- continuous_model_improvement_results:start -->" not in old:
        log.write_text(old + block)
    return lookup


def manifest():
    path = c.R / "conclusions/source_manifest.json"
    before = c.sha(path)
    value = json.loads(path.read_text())
    paths = [p for p in a.owned_paths() if p not in [a.INVENTORY, CONCLUSION]] + SHARED_DOCS
    for key, sources in [("sources", paths), ("conclusions", [CONCLUSION])]:
        index = {x["path"]: i for i, x in enumerate(value[key])}
        for p in sources:
            item = {"path": str(p.relative_to(c.ROOT)), "sha256": c.sha(p)}
            if item["path"] in index:
                value[key][index[item["path"]]] = item
            else:
                value[key].append(item)
    value["data_end_by_study"][a.MARKER] = {
        "study": c.HERE.name,
        "evaluation_end": "2026-09-20",
        "training_snapshot_end": "2026-09-28",
        "new_models": 18,
        "candidate_family_size": 3,
        "primary_races": 1288,
        "all_races": 4799,
        "production_changed": False,
        "new_independent_test": False,
        "automation_deleted": True,
        "work_mode": "current_thread_goal",
    }
    value["updated_at"] = "2026-10-25"
    c.require(c.sha(path) == before, "Concurrent manifest edit")
    a.dump(path, value)


def indexes(summary):
    title = "연구58Q 현재 채팅의 세 방향 개선 실험"
    note = "personal_t2 기준 심판 맥락·과거 마체중·축 순위 학습, 18모델 시간순 검증. 주간 예약 삭제. 반복 개발기간·운영 유지."
    a.upsert(c.R / "README.md", f"[{title}]({c.HERE.name}/README.md): {note}")
    a.upsert(c.R / "conclusions/README.md", f"[{title}]({CONCLUSION.name}): {note}")
    a.upsert(
        c.R / "conclusions/SOURCES.md",
        f"[{title}]({CONCLUSION.name}) · [원문](../{c.HERE.name}/README.md) · [계획](../{c.HERE.name}/PLAN.md) · [검증](../{c.HERE.name}/outputs/verification.json). {note}",
    )
    s = summary
    a.upsert(
        c.R / "ARTIFACT_SIZE_LOG.md",
        "| 날짜 | 작업 | 신규 파일 | 신규 bytes | MiB | 수정 파일 | 수정 최종 bytes | 순증감 bytes | 명세 |\n|---|---|---:|---:|---:|---:|---:|---:|---|\n"
        + f"| 2026-10-25 | 현재 채팅 세 방향 개선 | {s['new_file_count']} | {s['new_bytes']} | {s['new_mib']:.6f} | {s['modified_file_count']} | {s['modified_final_bytes']} | {s['modified_delta_bytes']:+d} | [명세]({c.HERE.name}/outputs/artifact_inventory.json) |\n\n최대 `{s['largest_file']['path']}` {s['largest_file']['bytes']:,}bytes. 이전 누적과 합계{s['combined_new_bytes']:,}/300,000,000bytes. 다른 작업 순증{s['modified_external_delta_bytes']:,}bytes 보존, 이번 수정 순증{s['modified_task_delta_bytes']:,}bytes. DB/전체특징 복제 없음.",
    )


def main():
    c.check()
    report()
    concurrent = c.HERE / "concurrent_updates.json"
    if not concurrent.exists():
        a.dump(
            concurrent,
            {
                n: {
                    "external_delta_bytes": (c.ROOT / n).stat().st_size - old["bytes"]
                    if n in a.CENTRAL
                    else 0,
                    "handling": "Merge only own central records; preserve other work",
                }
                for n, old in a.BEFORE.items()
            },
        )
    if not a.INVENTORY.exists():
        a.dump(a.INVENTORY, {})
    summary = a.inventory()["summary"]
    for _ in range(32):
        indexes(summary)
        manifest()
        value = a.inventory()
        a.dump(a.INVENTORY, value)
        after = a.inventory()
        if value == after and summary == after["summary"]:
            break
        summary = after["summary"]
    else:
        raise RuntimeError("Inventory did not converge")
    links = 0
    for p in [c.HERE / "README.md", c.HERE / "PUBLICATION.md", CONCLUSION]:
        for link in re.findall(r"\]\(([^)]+)\)", p.read_text()):
            if "://" in link or link.startswith("#"):
                continue
            c.require((p.parent / link.split("#")[0]).exists(), "Missing link: " + link)
            links += 1
    v = json.loads((c.R / "conclusions/source_manifest.json").read_text())
    paths = {str(p.relative_to(c.ROOT)) for p in a.owned_paths() + SHARED_DOCS if p != a.INVENTORY}
    registered = [x for key in ["sources", "conclusions"] for x in v[key] if x["path"] in paths]
    c.require(len(registered) == len(paths))
    c.require(all(c.sha(c.ROOT / x["path"]) == x["sha256"] for x in registered))
    c.require(json.loads(a.INVENTORY.read_text()) == a.inventory())
    print(
        json.dumps(
            {
                "status": "passed",
                **summary,
                "links_checked": links,
                "source_hashes_checked": len(registered),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

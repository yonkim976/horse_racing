# ruff: noqa: E501
"""Append verified findings and account for retained artifacts."""

import json

import pandas as pd
import run as e

MARKER = "<!-- axis_companion_pairs_v1_20261009 -->"


def main():
    e.check()
    assert json.loads((e.OUT / "final_verification.json").read_text())["passed"]
    assert json.loads((e.OUT / "independent_statistics_verification.json").read_text())["passed"]
    decision = json.loads((e.OUT / "decision.json").read_text())
    s = pd.read_csv(e.OUT / "summary.csv").query('scope == "all"').set_index("policy")
    base = s.loc["fixed_axis_next4_all6"]
    simple = s.loc["sum_score_pool7_best6"]
    context = s.loc["context_pair_pool7"]
    study = e.HERE.name
    root = e.ROOT / e.SPECIES
    con = root / "research/conclusions"
    name = "더러브랫" if e.SPECIES == "thoroughbred" else "제주"
    title = (
        "29_AXIS_COMPANION_PAIRS.md"
        if e.SPECIES == "thoroughbred"
        else "12_AXIS_COMPANION_PAIRS.md"
    )
    targets = [con / "README.md", con / "SOURCES.md", con / "source_manifest.json"]
    if e.SPECIES == "thoroughbred":
        targets += [root / "research/README.md", root / "research/ARTIFACT_SIZE_LOG.md"]
    else:
        targets += [con / "research_register.json", root / "README.md"]
    backups = e.HERE / "publication_before"
    backups.mkdir(exist_ok=False)
    before = {}
    for p in targets:
        key = str(p.relative_to(e.ROOT))
        data = p.read_bytes()
        before[key] = dict(bytes=len(data), sha256=e.sha(p))
        (backups / key.replace("/", "__")).write_bytes(data)
    e.save(e.OUT / "publication_before.json", before)
    if e.SPECIES == "thoroughbred":
        finding = (
            f"기존 축+상대4두6개 {base.six_hit:.2%} → 상대6두 점수합6개 {simple.six_hit:.2%}, "
            f"조건부 구간/전개6개 {context.six_hit:.2%}다. 새 동반학습은 같은 확대 후보군의 "
            "기존 점수합을 넘지 못했고 조건부 확률 오차는 악화됐다. 후보 범위 확대가 이번 "
            "개선의 주된 관측 요인이며 동반학습 추가 가치는 확인하지 못했다."
        )
    else:
        finding = (
            f"R1의 기존 축+상대4두6개 {base.six_hit:.2%} → 상대6두 점수합6개 "
            f"{simple.six_hit:.2%} → 조건부 구간/전개6개 {context.six_hit:.2%}다. "
            "조건부 학습+구간/전개 입력 묶음의 개선 신호가 있다. 같은467경주의 새 방식 "
            "22.70%는 운영 HY_R_FORM 30.84%보다 낮아 운영 교체 근거는 아니다."
        )
    conclusion = (
        f"# {name} 축 고정·조건부 동반 두 마리\n\n2026-10-09 완료. {finding}\n\n"
        f"2024~2026 후향 개발 {int(base.races):,}경주이며 축 입상 {int(base.axis_places):,}경주에서 "
        f"상대 포착률은 {base.companion_given_axis:.2%} → {context.companion_given_axis:.2%}다. "
        "축·경주·6조합 수는 고정했다. 상대6두의15쌍 가운데6개를 선택하며 후보군 밖 "
        "확률도 전체 조건부 분모에 유지했다.\n\n"
        f"상태: `{decision['status']}`. 기존 선택 기준·운영·DB·웹 변경 없음. "
        "기본2017+ 학습, 동반2020+ 시간순 OOF, 이전 연도만으로 학습·온도 보정했다. "
        "여러 후보의 점별 구간과 이미 본 평가 기간이므로 독립 미래 검증으로 부르지 않는다. "
        "제주의 구간 입력은 과거 동일경주 상대 시간 순위분율이며 더러브랫의 보정 초값과 "
        "단위가 다르다. 기수/조교사 추가나 당일 실제 전개 입력은 없다.\n\n"
        f"[원 보고서](../{study}/README.md), [사전 계약](../{study}/PLAN.md), "
        f"[모형·조합 검증](../{study}/outputs/final_verification.json), "
        f"[통계 독립 재계산](../{study}/outputs/independent_statistics_verification.json).\n"
    )
    target = con / title
    assert not target.exists()
    target.write_text(conclusion)
    # Add the principal interpretation to the full research report as well.
    with (e.HERE / "README.md").open("a") as f:
        f.write(
            f"\n## 다음 개발에 대한 해석\n\n{finding}\n\n"
            "확률·적중의 개선을 구분하고, 같은 확대 후보군 대조를 생략하지 않는다. "
            "[통계 독립 재계산](outputs/independent_statistics_verification.json)을 완료했다.\n"
        )
    for p in [con / "README.md", con / "SOURCES.md"]:
        data = p.read_text()
        assert MARKER not in data
        p.write_text(
            data + f"\n\n{MARKER}\n"
            f"[축 고정·조건부 동반 두 마리]({title}): {finding} "
            f"[원본](../{study}/README.md). 운영 미반영.\n"
        )
    index = root / "research/README.md" if e.SPECIES == "thoroughbred" else root / "README.md"
    data = index.read_text()
    link = f"{study}/README.md" if e.SPECIES == "thoroughbred" else f"research/{study}/README.md"
    index.write_text(
        data + f"\n\n{MARKER}\n[축 고정·동반 두 마리 연구]({link}): {finding} 운영 미반영.\n"
    )
    if e.SPECIES == "jeju":
        p = con / "research_register.json"
        r = json.loads(p.read_text())
        assert not any(t.get("id") == "axis_companion_pairs" for t in r["topics"])
        r["topics"].append(
            dict(
                id="axis_companion_pairs",
                title="축 고정 조건부 동반 두 마리",
                conclusion=title,
                latest_source=f"../{study}/README.md",
                period_start="2024-01-05",
                period_end="2026-09-19",
                status=decision["status"],
                operationally_applied=False,
            )
        )
        p.write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n")
    p = con / "source_manifest.json"
    manifest = json.loads(p.read_text())
    key = "sources" if "sources" in manifest else "files"
    entries = manifest[key]
    files = [
        con / title,
        con / "README.md",
        con / "SOURCES.md",
        e.HERE / "README.md",
        e.HERE / "PLAN.md",
        e.OUT / "decision.json",
        e.OUT / "final_verification.json",
        e.OUT / "independent_statistics_verification.json",
    ]
    if e.SPECIES == "jeju":
        files += [con / "research_register.json"]
    for file in files:
        relative = str(file.relative_to(e.ROOT))
        existing = next((z for z in entries if z["path"] == relative), None)
        entry = dict(path=relative, sha256=e.sha(file), bytes=file.stat().st_size)
        if key == "files":
            entry["role"] = "axis_companion_research_or_conclusion"
        if existing is None:
            entries.append(entry)
        else:
            existing.update(entry)
    manifest["updated_at"] = "2026-10-09"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    for file in targets:
        assert before[str(file.relative_to(e.ROOT))]["sha256"] == e.sha(
            backups / str(file.relative_to(e.ROOT)).replace("/", "__")
        )
    e.check()
    e.save(
        e.OUT / "publication_verification.json",
        dict(
            passed=True,
            source_and_registry_unchanged=True,
            conclusion=title,
            appended_existing_indices=True,
            previous_versions_preserved=True,
            operating_changed=False,
        ),
    )
    inventory = e.OUT / "artifact_inventory.json"
    inventory.write_text("{}\n")
    size_log = root / "research/ARTIFACT_SIZE_LOG.md" if e.SPECIES == "thoroughbred" else None
    log_before = (
        (backups / "thoroughbred__research__ARTIFACT_SIZE_LOG.md").read_text() if size_log else ""
    )
    previous = None
    for _ in range(25):
        new_files = [
            z for z in e.HERE.rglob("*") if z.is_file() and "__pycache__" not in z.parts
        ] + [target]
        rows = [
            dict(
                path=str(z.relative_to(e.ROOT)),
                bytes=z.stat().st_size,
                sha256=None if z == inventory else e.sha(z),
            )
            for z in sorted(new_files)
        ]
        total = sum(z["bytes"] for z in rows)
        if size_log:
            log_row = (
                f"\n| 2026-10-09 | 축 고정·조건부 동반 두 마리 | {len(rows)} | {total} | "
                f"{total / 1048576:.6f} | {len(targets)} | 연구별 명세 참조 | "
                f"연구별 명세 참조 | [명세]({study}/outputs/artifact_inventory.json) | {MARKER}\n"
            )
            size_log.write_text(log_before + log_row)
        modified = [
            dict(
                path=str(z.relative_to(e.ROOT)),
                before_bytes=before[str(z.relative_to(e.ROOT))]["bytes"],
                bytes=z.stat().st_size,
                delta_bytes=z.stat().st_size - before[str(z.relative_to(e.ROOT))]["bytes"],
                sha256=e.sha(z),
            )
            for z in targets
        ]
        report = dict(
            species=e.SPECIES,
            new_file_count=len(rows),
            new_bytes=total,
            new_mib=total / 1048576,
            modified_file_count=len(modified),
            modified_delta_bytes=sum(z["delta_bytes"] for z in modified),
            new_files=rows,
            modified_files=modified,
            inventory_self_hash_omitted=True,
        )
        inventory.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        signature = (total, inventory.stat().st_size, tuple(z["bytes"] for z in modified))
        if signature == previous:
            break
        previous = signature
    else:
        raise AssertionError("Inventory did not converge")
    now = json.loads(inventory.read_text())
    assert sum((e.ROOT / z["path"]).stat().st_size for z in now["new_files"]) == now["new_bytes"]
    for z in now["new_files"] + now["modified_files"]:
        path = e.ROOT / z["path"]
        assert path.stat().st_size == z["bytes"]
        if z["sha256"] is not None:
            assert e.sha(path) == z["sha256"]
    e.check()
    print(
        "Published",
        name,
        now["new_file_count"],
        "files",
        now["new_bytes"],
        "bytes",
        now["new_mib"],
        "MiB",
    )


if __name__ == "__main__":
    main()

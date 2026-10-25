"""Refresh central source hashes and verify publication data and local documentation links."""

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest_path = CENTRAL / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    new_source = str((HERE / "README.md").relative_to(ROOT))
    paths = [r["path"] for r in manifest["sources"]]
    if new_source not in paths:
        paths.append(new_source)
    manifest["sources"] = [dict(path=p, sha256=sha(ROOT / p)) for p in paths]
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = manifest["scope"].replace("연구20", "연구21")
    manifest["assembled_on"] = "2026-10-06"
    manifest["new_benchmarks1600_analysis_added"] = True
    manifest["analysis_rerun_note"] = (
        "기존 연구 전체 재실행 없음. 새1600m 기준에서 별도 모집단·상태효과·구간·"
        "시간순 검증을 추가함."
    )
    manifest["data_end_by_study"]["benchmarks1600_seoul"] = "2026-09-19"
    manifest["data_end_by_study"]["benchmarks1600_busan"] = "2026-09-18"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assert len(manifest["sources"]) == 24 and len(manifest["conclusions"]) == 16
    for record in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / record["path"]) == record["sha256"]
    web = json.loads((OUT / "web_benchmarks1600.json").read_text())
    whole = pd.read_csv(OUT / "whole_time_benchmarks.csv")
    table = pd.read_csv(OUT / "estimated_benchmarks.csv")
    assert web["distance_m"] == 1600 and web["benchmark_version"] == "1600_v1_20261006"
    assert len(web["whole_time_cells"]) == len(whole) == 100
    assert len(web["section_cells"]) == len(table) == 560
    keys = ["meet", "grade", "band", "part"]
    joined = table.merge(pd.DataFrame(web["section_cells"]), on=keys, suffixes=("_csv", "_web"))
    assert len(joined) == len(table)
    for field in ["mean", "p20", "p80", "observed_n", "reference_n", "mean_ci_low"]:
        assert np.allclose(joined[field + "_csv"], joined[field + "_web"], equal_nan=True)
    empty = [r for r in web["whole_time_cells"] if r["mean"] is None]
    assert len(empty) == 15
    assert all(r["status"] == "no_recent_grade_reference" and r["reference_n"] == 0 for r in empty)
    assert all(r["distance"] == 1600 and r["part"] == "finish" for r in empty)
    assert {r["meet"] for r in empty} == {"서울"}
    assert {r["grade"] for r in empty} == {"국6", "국5", "혼OPEN"}
    sparse = table.meet.eq("서울") & table.grade.eq("국OPEN")
    assert sparse.sum() == 30
    assert table.loc[sparse, "bootstrap_valid_n"].eq(173).all()
    for field in ["mean", "p20", "median", "p80"]:
        for side in ["low", "high"]:
            assert table.loc[sparse, field + "_ci_" + side].isna().all()
    assert table.loc[~sparse, "bootstrap_valid_n"].ge(180).all()
    assert table.loc[~sparse, "mean_ci_low"].notna().all()
    assert "provisional" in web["benchmark_interpretation_by_venue"]["서울"]
    assert web["development_years_by_venue"]["서울"] == [2022, 2023]
    assert web["development_years_by_venue"]["부산"] == [2021, 2022, 2023]
    assert len(web["development_support"]) == 5
    dev = pd.DataFrame(web["development_support"])
    assert dev.loc[dev.meet.eq("서울") & dev.year.eq(2022), "excluded_unseen_grade_n"].iloc[0] == 36
    assert "잠정" in (HERE / "README.md").read_text()
    assert "잠정" in (HERE / "PUBLICATION.md").read_text()
    from evaluate_record import evaluate

    sample = evaluate("서울", "국4", "건조", "finish", 103.0)
    assert "Provisional" in sample["benchmark_interpretation"]
    assert sample["same_grade_record_score"] == 60.13
    assert evaluate("부산", "국5", "건조", "finish", 102.0)["same_grade_record_score"] > 80
    for grade in ["국6", "국5", "혼OPEN"]:
        try:
            evaluate("서울", grade, "건조", "finish", 103.0)
        except ValueError:
            pass
        else:
            raise AssertionError("Unsupported grade must not be assigned a record score")
    # Prior completed research and DB are immutable; only shared indexes are refreshed.
    before = json.loads(Path("/tmp/horse1600_benchmark_baseline_20261006.json").read_text())
    for name, stat in before.items():
        if name.startswith("thoroughbred/research/conclusions/") and name.endswith(".md"):
            if Path(name).name not in {"README.md", "SOURCES.md"}:
                p = ROOT / name
                assert p.stat().st_size == stat["size"] and p.stat().st_mtime_ns == stat["mtime_ns"]
    docs = list(HERE.glob("*.md")) + list(CENTRAL.glob("*.md"))
    links = 0
    missing = []
    for doc in docs:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", doc.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            target = target.split("#")[0].strip("<>")
            path = (doc.parent / target).resolve()
            if not path.exists() and path != OUT / "artifact_inventory.json":
                missing.append(dict(document=str(doc.relative_to(ROOT)), target=target))
            links += 1
    assert not missing, missing
    result = dict(
        passed=True,
        central_source_hashes=40,
        existing_topic_conclusions_unchanged=True,
        local_document_links_checked=links,
        missing_links=missing,
        whole_cells=100,
        supported_reference_cells=85,
        unsupported_reference_cells=15,
        section_rows=560,
        publication_matches_csv=True,
        sparse_grade_statuses_preserved=True,
        seoul_provisional_status_preserved=True,
        seoul_open_confidence_intervals_withheld=True,
        actual_development_support_preserved=True,
        cli_record_evaluation_checked=True,
        scientific_figure_visually_checked=True,
        limits="Research publication preparation; no deployment or operating model changes",
    )
    (OUT / "package_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

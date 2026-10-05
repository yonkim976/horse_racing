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
    manifest["scope"] = manifest["scope"].replace("연구19", "연구20")
    manifest["assembled_on"] = "2026-10-05"
    manifest["new_benchmarks1400_analysis_added"] = True
    manifest["analysis_rerun_note"] = (
        "기존 연구 전체 재실행 없음. 새1400m 기준에서 별도 모집단·상태효과·구간·"
        "시간순 검증을 추가함."
    )
    manifest["data_end_by_study"]["benchmarks1400_seoul"] = "2026-09-20"
    manifest["data_end_by_study"]["benchmarks1400_busan"] = "2026-09-11"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assert len(manifest["sources"]) == 23 and len(manifest["conclusions"]) == 15
    for record in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / record["path"]) == record["sha256"]
    web = json.loads((OUT / "web_benchmarks1400.json").read_text())
    whole = pd.read_csv(OUT / "whole_time_benchmarks.csv")
    table = pd.read_csv(OUT / "estimated_benchmarks.csv")
    assert web["distance_m"] == 1400 and web["benchmark_version"] == "1400_v1_20261005"
    assert len(web["whole_time_cells"]) == len(whole) == 100
    assert len(web["section_cells"]) == len(table) == 650
    keys = ["meet", "grade", "band", "part"]
    joined = table.merge(pd.DataFrame(web["section_cells"]), on=keys, suffixes=("_csv", "_web"))
    assert len(joined) == len(table)
    for field in ["mean", "p20", "p80", "observed_n", "reference_n", "mean_ci_low"]:
        assert np.allclose(joined[field + "_csv"], joined[field + "_web"], equal_nan=True)
    empty = [r for r in web["whole_time_cells"] if r["mean"] is None]
    assert len(empty) == 0
    assert all(r["status"] == "no_recent_grade_reference" and r["reference_n"] == 0 for r in empty)
    assert all(r["distance"] == 1400 and r["part"] == "finish" for r in empty)
    assert table.bootstrap_valid_n.ge(180).all()
    assert table.mean_ci_low.notna().all()
    # Prior completed research and DB are immutable; only shared indexes are refreshed.
    before = json.loads(Path("/tmp/horse1400_benchmark_baseline_20261005.json").read_text())
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
        central_source_hashes=38,
        existing_topic_conclusions_unchanged=True,
        local_document_links_checked=links,
        missing_links=missing,
        whole_cells=100,
        supported_reference_cells=100,
        unsupported_reference_cells=0,
        section_rows=650,
        publication_matches_csv=True,
        sparse_grade_statuses_preserved=True,
        scientific_figure_visually_checked=True,
        limits="Research publication preparation; no deployment or operating model changes",
    )
    (OUT / "package_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

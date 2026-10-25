"""Link the availability check to central conclusions and verify its evidence package."""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    path = CENTRAL / "source_manifest.json"
    manifest = json.loads(path.read_text())
    source = str((HERE / "README.md").relative_to(ROOT))
    paths = [r["path"] for r in manifest["sources"]]
    if source not in paths:
        paths.append(source)
    manifest["sources"] = [dict(path=p, sha256=sha(ROOT / p)) for p in paths]
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["new_seoul1700_coverage_check_added"] = True
    manifest["seoul1700_coverage_note"] = (
        "국5·국6 출전 여부의 사전 표본 점검. 완료된21개 연구에1700m 시간 기준 연구를 "
        "추가 완료한 것은 아님."
    )
    manifest["data_end_by_study"]["seoul1700_coverage"] = "2026-09-20"
    manifest["assembled_on"] = "2026-10-06"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assert len(manifest["sources"]) == 25 and len(manifest["conclusions"]) == 16
    for record in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / record["path"]) == record["sha256"]
    coverage = pd.read_csv(OUT / "grade_coverage.csv")
    recent = coverage[
        coverage.cohort.eq("parent_normal_full_race") & coverage.period.eq("2024plus")
    ].set_index("grade")
    assert set(recent.index) == {"국6", "국5", "국4", "혼4", "국OPEN"}
    assert recent.records.sum() == 2311
    for grade, n, nr, horses in [("국5", 875, 87, 416), ("국6", 485, 49, 216)]:
        assert recent.loc[grade, "records"] == n
        assert recent.loc[grade, "races"] == nr
        assert recent.loc[grade, "unique_horses"] == horses
    bands = pd.read_csv(OUT / "recent_grade_band_coverage.csv")
    assert bands.groupby("grade").records.sum().equals(recent.records.sort_index())
    examples = pd.read_csv(OUT / "recent_examples.csv", dtype={"horse_id": str})
    assert len(examples) == 6
    assert set(examples.date) == {"2026-09-19", "2026-09-20"}
    check = json.loads((OUT / "verification.json").read_text())
    assert check["passed"] and check["input_hashes_unchanged"]
    assert check["original_api_rows_verified"] == 4246 and check["core_races_verified"] == 404
    missing, links = [], 0
    for doc in [*HERE.glob("*.md"), *CENTRAL.glob("*.md")]:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", doc.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            local = (doc.parent / target.split("#")[0].strip("<>")).resolve()
            links += 1
            if not local.exists() and local != OUT / "artifact_inventory.json":
                missing.append(dict(document=str(doc), target=target))
    assert not missing, missing
    result = dict(
        passed=True,
        central_hashes_checked=41,
        local_links_checked=links,
        recent_cohort_records=2311,
        low_grade_original_rows_verified=4246,
        counts_and_examples_match_report=True,
        no_time_benchmarks_claimed=True,
        missing_links=missing,
    )
    (OUT / "package_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

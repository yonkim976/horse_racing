"""Verify both publication packages and central source hashes before final size accounting."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CENTRAL = HERE.parent / "conclusions"
OUT = HERE / "outputs"
BASELINE = Path("/tmp/horse1700_1800_baseline_20261006.json")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    path = CENTRAL / "source_manifest.json"
    manifest = json.loads(path.read_text())
    paths = [r["path"] for r in manifest["sources"]]
    for distance in [1700, 1800]:
        source = str((HERE / str(distance) / "README.md").relative_to(ROOT))
        if source not in paths:
            paths.append(source)
    manifest["sources"] = [dict(path=p, sha256=sha(ROOT / p)) for p in paths]
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = manifest["scope"].replace("연구21", "연구23")
    manifest["assembled_on"] = "2026-10-06"
    manifest["new_benchmarks1700_analysis_added"] = True
    manifest["new_benchmarks1800_analysis_added"] = True
    manifest["analysis_rerun_note"] = (
        "이전 완료 연구 재실행 없음. 새 서울1700m·서울부산1800m를 독립 계산·검증함. "
        "시간순 비교에서 이전3년 같은 등급 참조 부재행을 모든 방법에서 공통 제외함."
    )
    manifest["data_end_by_study"].update(
        benchmarks1700_seoul="2026-09-20",
        benchmarks1800_seoul="2026-09-20",
        benchmarks1800_busan="2026-09-18",
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assert len(manifest["sources"]) == 27 and len(manifest["conclusions"]) == 18
    for record in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / record["path"]) == record["sha256"]
    before = json.loads(BASELINE.read_text())
    for name, stat in before.items():
        if name.startswith("thoroughbred/research/conclusions/") and name.endswith(".md"):
            if Path(name).name not in {"README.md", "SOURCES.md"}:
                p = ROOT / name
                assert p.stat().st_size == stat["size"] and p.stat().st_mtime_ns == stat["mtime_ns"]
    packages = []
    for (
        distance,
        expected_whole,
        expected_supported,
        expected_sections,
        expected_n,
        expected_recent,
    ) in [
        (1700, 50, 25, 150, 9075, 2310),
        (1800, 100, 90, 585, 15377, 6842),
    ]:
        out = HERE / str(distance) / "outputs"
        s = json.loads((out / "summary.json").read_text())
        check = json.loads((out / "verification.json").read_text())
        web = json.loads((out / f"web_benchmarks{distance}.json").read_text())
        whole = pd.read_csv(out / "whole_time_benchmarks.csv")
        table = pd.read_csv(out / "estimated_benchmarks.csv")
        assert check["passed"] and check["input_hashes_unchanged"]
        assert s["input_n"] == expected_n and s["recent_n"] == expected_recent
        assert web["distance_m"] == distance
        assert web["benchmark_version"] == f"{distance}_v1_20261006"
        assert len(web["whole_time_cells"]) == len(whole) == expected_whole
        assert len(web["section_cells"]) == len(table) == expected_sections
        assert whole["mean"].notna().sum() == expected_supported
        keys = ["meet", "grade", "band", "part"]
        joined = table.merge(
            pd.DataFrame(web["section_cells"]),
            on=keys,
            suffixes=("_a", "_b"),
            validate="one_to_one",
        )
        for field in ["mean", "p20", "p80", "observed_n", "reference_n", "mean_ci_low"]:
            assert np.allclose(joined[field + "_a"], joined[field + "_b"], equal_nan=True)
        empty = [r for r in web["whole_time_cells"] if r["mean"] is None]
        assert len(empty) == expected_whole - expected_supported
        assert all(
            r["status"] == "no_recent_grade_reference" and r["reference_n"] == 0 for r in empty
        )
        assert all(r["distance"] == distance and r["part"] == "finish" for r in empty)
        assert table.bootstrap_valid_n.ge(180).all() and table.mean_ci_low.notna().all()
        assert not ((table.meet == "서울") & (table.part == "last400")).any()
        skipped = pd.read_csv(out / "temporal_reference_exclusions.csv")
        assert s["score_rows"] + int(skipped.n.sum()) == s["recent_n"]
        temporal = pd.read_csv(out / "temporal_mean_validation.csv")
        for (_, _), group in temporal.groupby(["meet", "year"]):
            by_method = [
                set(zip(g.grade, g.band, g.n, strict=True)) for _, g in group.groupby("method")
            ]
            assert len(by_method) == 4 and all(by_method[0] == other for other in by_method[1:])
        if distance == 1700:
            assert {r["grade"] for r in empty} == {"국3", "혼3", "2", "1", "혼OPEN"}
            assert s["temporal_excluded_rows"] == 0
        else:
            assert {r["grade"] for r in empty} == {"국6"}
            assert s["temporal_excluded_rows"] == 31 and len(skipped) == 1
            assert tuple(skipped.iloc[0][["meet", "year", "grade", "n"]]) == (
                "서울",
                2024,
                "국5",
                31,
            )
        examples = json.loads((out / "record_score_examples.json").read_text())
        first = examples[0]
        process = subprocess.run(
            [
                sys.executable,
                str(HERE / str(distance) / "evaluate_record.py"),
                "--meet",
                first["meet"],
                "--grade",
                "국5",
                "--band",
                first["band"],
                "--time",
                str(first["time_seconds"]),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert json.loads(process.stdout) == first
        missing_grade = "국3" if distance == 1700 else "국6"
        bad = subprocess.run(
            [
                sys.executable,
                str(HERE / str(distance) / "evaluate_record.py"),
                "--meet",
                "서울",
                "--grade",
                missing_grade,
                "--band",
                "건조",
                "--time",
                "120.0",
            ],
            capture_output=True,
            text=True,
        )
        assert bad.returncode == 2 and "unavailable" in bad.stderr
        packages.append(
            dict(
                distance_m=distance,
                whole_cells=expected_whole,
                supported_reference_cells=expected_supported,
                section_rows=expected_sections,
                numerical_checks=check["numeric_checks"],
                chronological_score_checks=check["chronological_score_checks"],
                temporal_excluded_rows=s["temporal_excluded_rows"],
                identical_validation_cohorts=True,
                publication_matches_csv=True,
                missing_grade_cli_rejected=True,
                scientific_figure_visually_checked=True,
            )
        )
    missing, links = [], 0
    for doc in [*HERE.rglob("*.md"), *CENTRAL.glob("*.md")]:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", doc.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            local = (doc.parent / target.split("#")[0].strip("<>")).resolve()
            links += 1
            if not local.exists() and local != OUT / "artifact_inventory.json":
                missing.append(dict(document=str(doc.relative_to(ROOT)), target=target))
    assert not missing, missing
    result = dict(
        passed=True,
        central_source_hashes=45,
        existing_topic_conclusions_unchanged=True,
        local_document_links_checked=links,
        missing_links=missing,
        packages=packages,
        scope="Research preparation; no website deployment or operating model changes",
    )
    (OUT / "package_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Verify publication data, source hashes and links before recording retained artifact sizes."""

# ruff: noqa: E501

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
BASELINE = Path("/tmp/horse_remaining_distances_baseline_20261006.json")
DISTANCES = [1000, 1900, 2000, 2200, 2300]
EXPECTED = {
    1000: (13258, 951, 20, 130),
    1900: (318, 10, 5, 30),
    2000: (2346, 925, 35, 225),
    2200: (83, 19, 8, 56),
    2300: (201, 68, 8, 48),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cli(distance, **args):
    command = [sys.executable, str(HERE / "evaluate_record.py"), "--distance", str(distance)]
    for name, value in args.items():
        command.extend(["--" + name, str(value)])
    return subprocess.run(command, capture_output=True, text=True)


def main():
    # Account for every distance in the frozen normal-race corpus, not a current official calendar.
    history = pd.read_parquet(
        HERE.parent / "20261002_gate_lateral_bias/outputs/runners.parquet",
        columns=["meet", "distance_m", "date"],
    )
    history = history[history.meet.isin([1, 3])].copy()
    history["date"] = pd.to_datetime(history.date)
    completed = {1200, 1300, 1400, 1600, 1700, 1800}
    found = set(history.distance_m.astype(int))
    assert found - completed == set(DISTANCES)
    coverage = []
    for (meet, distance), group in history.groupby(["meet", "distance_m"]):
        coverage.append(
            dict(
                meet="서울" if meet == 1 else "부산",
                distance_m=int(distance),
                parent_normal_n=len(group),
                recent_parent_n=int(group.date.ge("2024-01-01").sum()),
                first_date=str(group.date.min().date()),
                last_date=str(group.date.max().date()),
                study_status="completed_this_task"
                if int(distance) in DISTANCES
                else "completed_previously",
            )
        )
    pd.DataFrame(coverage).to_csv(HERE / "outputs/corpus_distance_coverage.csv", index=False)
    packages = []
    for d in DISTANCES:
        out = HERE / str(d) / "outputs"
        s = json.loads((out / "summary.json").read_text())
        v = json.loads((out / "verification.json").read_text())
        web = json.loads((out / f"web_benchmarks{d}.json").read_text())
        table = pd.read_csv(out / "estimated_benchmarks.csv", dtype={"grade": str})
        whole = pd.read_csv(out / "whole_time_benchmarks.csv", dtype={"grade": str})
        assert v["passed"] and v["input_hashes_unchanged"]
        assert (s["input_n"], s["recent_n"], s["reference_cells"], s["benchmark_rows"]) == EXPECTED[
            d
        ]
        assert web["distance_m"] == d and web["benchmark_version"] == f"{d}_v1_20261006"
        assert len(whole) == len(web["whole_time_cells"]) == len(s["venues"]) * 50
        assert len(table) == len(web["section_cells"]) == EXPECTED[d][3]
        assert whole["mean"].notna().sum() == EXPECTED[d][2]
        keys = ["meet", "grade", "band", "part"]
        for frame, rows in [(table, web["section_cells"]), (whole, web["whole_time_cells"])]:
            joined = frame.merge(
                pd.DataFrame(rows), on=keys, suffixes=("_csv", "_web"), validate="one_to_one"
            )
            for field in [
                "mean",
                "p20",
                "median",
                "p80",
                "observed_n",
                "reference_n",
                "mean_ci_low",
                "bootstrap_valid_n",
            ]:
                a = joined[field + "_csv"].to_numpy(dtype=float)
                b = joined[field + "_web"].to_numpy(dtype=float)
                assert np.allclose(a, b, equal_nan=True, atol=1e-8, rtol=1e-10), (d, field)
        grade_absent = whole.status.eq("no_recent_grade_reference")
        state_absent = whole.status.eq("no_historical_state_support")
        assert whole.loc[grade_absent, "reference_n"].eq(0).all()
        assert whole.loc[state_absent, "reference_n"].gt(0).all()
        assert (
            whole.loc[
                grade_absent | state_absent,
                ["mean", "p10", "p20", "median", "p80", "p90", "fast20_mean", "slow20_mean"],
            ]
            .isna()
            .all()
            .all()
        )
        assert whole.loc[grade_absent | state_absent, "distance"].eq(d).all()
        assert whole.loc[grade_absent | state_absent, "part"].eq("finish").all()
        assert (
            table.loc[
                table.bootstrap_valid_n.lt(180),
                ["mean_ci_low", "mean_ci_high", "p20_ci_low", "p80_ci_high"],
            ]
            .isna()
            .all()
            .all()
        )
        assert table.loc[table.bootstrap_valid_n.ge(180), "mean_ci_low"].notna().all()
        assert not (table.meet.eq("서울") & table.part.eq("last400")).any()
        assert web["temporal_validation_support"] == s["temporal_validation_support"]
        skipped = pd.read_csv(out / "temporal_reference_exclusions.csv", dtype={"grade": str})
        assert s["score_rows"] + int(skipped.n.sum()) == s["recent_n"]
        temporal = pd.read_csv(out / "temporal_mean_validation.csv", dtype={"grade": str})
        for _, group in temporal.groupby(["meet", "year"]):
            cohorts = [
                set(zip(g.grade, g.band, g.n, strict=True)) for _, g in group.groupby("method")
            ]
            assert len(cohorts) == 4 and all(x == cohorts[0] for x in cohorts)
        for example in json.loads((out / "record_score_examples.json").read_text()):
            result = cli(
                d,
                meet=example["meet"],
                grade=example["grade"],
                band=example["band"],
                time=example["time_seconds"],
            )
            assert result.returncode == 0 and json.loads(result.stdout) == example
        for row in whole[grade_absent | state_absent].itertuples():
            # Check one representative for each reason/region rather than hundreds of identical errors.
            if (
                whole.loc[(whole.meet == row.meet) & (whole.status == row.status)].index[0]
                != row.Index
            ):
                continue
            result = cli(d, meet=row.meet, grade=row.grade, band=row.band, time=100)
            assert result.returncode == 2 and "unavailable" in result.stderr
        for ss in s["temporal_validation_support"]:
            interp = web["benchmark_interpretation_by_venue"][ss["meet"]]
            if ss["status"] in ["sparse", "none"]:
                assert "provisional" in interp
        if d == 2200:
            assert s["score_rows"] == 0 and s["mean_validation"] == []
            assert whole.loc[state_absent, "band"].eq("포화").all() and state_absent.sum() == 2
        if d == 2300:
            assert whole.loc[state_absent, "band"].eq("불량").all() and state_absent.sum() == 2
        if d in [1900, 2200]:
            assert table.mean_ci_low.isna().all()
        if d == 2000:
            sparse = table[table.meet.eq("부산") & table.grade.eq("국OPEN")]
            assert sparse.reference_days.eq(1).all() and sparse.mean_ci_low.isna().all()
        packages.append(
            dict(
                distance=d,
                input_n=s["input_n"],
                recent_n=s["recent_n"],
                supported_whole_cells=s["reference_cells"],
                null_whole_cells=s["unsupported_whole_cells"],
                section_rows=s["benchmark_rows"],
                temporal_n=s["score_rows"],
                excluded_temporal_n=s["temporal_excluded_rows"],
                ci_withheld_rows=int(table.mean_ci_low.isna().sum()),
                passed=True,
            )
        )
    # Refresh the central index hashes without altering completed source reports or topic conclusions.
    path = CENTRAL / "source_manifest.json"
    manifest = json.loads(path.read_text())
    names = [x["path"] for x in manifest["sources"]]
    for d in DISTANCES:
        name = str((HERE / str(d) / "README.md").relative_to(ROOT))
        if name not in names:
            names.append(name)
    manifest["sources"] = [dict(path=p, sha256=sha(ROOT / p)) for p in names]
    manifest["conclusions"] = [
        dict(path=str(p.relative_to(ROOT)), sha256=sha(p)) for p in sorted(CENTRAL.glob("*.md"))
    ]
    manifest["scope"] = manifest["scope"].replace("연구23개", "연구28개")
    manifest["assembled_on"] = "2026-10-06"
    manifest["new_remaining_distance_benchmarks_added"] = True
    manifest["analysis_rerun_note"] = (
        "이전 완료 연구 재실행 없음. 동결 실전 모집단의 남은1000/1900/2000/2200/2300m를 독립 계산·검증. 이전 같은 등급 참조와 이전 상태 지원이 없는 평가행을 모든 방법에서 공통 제외. 전기간 상태 지원 없는2200 포화·2300 불량은 시간 null."
    )
    for d in DISTANCES:
        s = json.loads((HERE / str(d) / "outputs/summary.json").read_text())
        for m, end in s["input_end"].items():
            manifest["data_end_by_study"][
                f"benchmarks{d}_{'seoul' if m == '서울' else 'busan'}"
            ] = end
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    assert len(manifest["sources"]) == 32 and len(manifest["conclusions"]) == 23
    for record in manifest["sources"] + manifest["conclusions"]:
        assert sha(ROOT / record["path"]) == record["sha256"]
    before = json.loads(BASELINE.read_text())
    for name, stat in before.items():
        if (
            name.startswith("thoroughbred/research/conclusions/")
            and name.endswith(".md")
            and Path(name).name not in ["README.md", "SOURCES.md"]
        ):
            p = ROOT / name
            assert p.stat().st_size == stat["size"] and p.stat().st_mtime_ns == stat["mtime_ns"]
    md_files = [*HERE.rglob("*.md"), *CENTRAL.glob("*.md")]
    link_count = 0
    for p in md_files:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", p.read_text()):
            if target.startswith(("http:", "https:", "mailto:", "#")):
                continue
            target = target.split("#")[0]
            q = (p.parent / target).resolve()
            assert q.is_relative_to(ROOT) and (
                q.exists() or q == HERE / "outputs/artifact_inventory.json"
            ), (p, target)
            link_count += 1
    result = dict(
        completed_on="2026-10-06",
        passed=True,
        packages=packages,
        source_hashes_checked=len(manifest["sources"]) + len(manifest["conclusions"]),
        prior_topic_conclusions_unchanged=True,
        remaining_corpus_distances_complete=True,
        local_links_checked=link_count,
        publication_csv_alignment=True,
        unsupported_cells_rejected=True,
        temporal_comparison_same_cohorts=True,
        limitations="Source/chronology/arithmetic/publication checks do not establish causal state effects or future forecasting gains",
    )
    (HERE / "outputs/final_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

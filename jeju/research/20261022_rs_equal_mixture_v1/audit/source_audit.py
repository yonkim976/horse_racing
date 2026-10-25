#!/usr/bin/env python3
"""Read-only, deterministic source preflight for the fixed R/S mixture study."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl


PROJECT = Path(__file__).resolve().parents[4]
STUDY_REL = Path("jeju/research/20261022_rs_equal_mixture_v1")
AUDIT_REL = STUDY_REL / "audit"
CONTRACT_REL = STUDY_REL / "supervisor/DESIGN_CONTRACT.md"
EXPECTED_CONTRACT_SHA = "e3cd97f4c2081e23dc077bf20641e5012e39ece3a396b11fd6838bef971e13a8"

F1_REL = Path("jeju/research/20261010_style_history_ablation_v1")
F1_MANIFEST_REL = F1_REL / "ARTIFACT_MANIFEST.json"
F1_MANIFEST_SHA = "6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e"
F1_FEATURES_REL = F1_REL / "outputs/features.parquet"
F1_RUN_REL = F1_REL / "run.py"

TB_REL = Path("jeju/research/20261022_tb_state_transfer_v1")
TB_FINAL_REL = TB_REL / "FINAL_MANIFEST.json"
TB_FINAL_SHA = "86d0153e287f877add1b10c3172471cf5c3aac9f251890423cd7d97f75abba3a"
TB_SCORE_REL = TB_REL / "experiment/outputs/candidate_oos_scores.parquet"
TB_PARAMS_REL = TB_REL / "experiment/outputs/parameters.json"
TB_INPUT_MANIFEST_REL = TB_REL / "inputs/input_manifest.json"
TB_FIT_RECEIPT_REL = TB_REL / "experiment/outputs/fit_run_receipt.json"
TB_RESULTS_REL = TB_REL / "experiment/RESULTS.md"
TB_REPORT_REL = TB_REL / "experiment/outputs/report.json"
TB_SOURCE_MANIFEST_REL = TB_REL / "audit/source_manifest.json"
TB_ENGINE_REL = TB_REL / "experiment/state_transfer.py"

DYNAMIC_PARAMS_REL = Path("jeju/research/20261022_dynamic_ability_pace_v1/experiment/outputs/parameters.json")
DYNAMIC_ENGINE_REL = Path("jeju/research/20261022_dynamic_ability_pace_v1/experiment/dynamic_ability_pace.py")
JOINT_REL = Path("jeju/research/20261022_joint_wager_baseline_v1")
JOINT_FINAL_REL = JOINT_REL / "FINAL_MANIFEST.json"
JOINT_FINAL_SHA = "95872bdb4e3df145092d667e6f383e2c90a5641548bccaba374d6d4ed18d5d77"
JOINT_RULES_REL = JOINT_REL / "rules_contract/rules_contract.json"
JOINT_README_REL = JOINT_REL / "rules_contract/README.md"
JOINT_PREFLIGHT_REL = JOINT_REL / "experiment/outputs/source_preflight.json"
JOINT_REPORT_REL = JOINT_REL / "experiment/outputs/report.json"
JOINT_LEDGER_REL = JOINT_REL / "experiment/outputs/race_contract_ledger.parquet"

BOOTSTRAP_REL = Path("jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy")
BOOTSTRAP_RECEIPT_REL = Path("jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json")
EXPECTED_BOOTSTRAP_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_BOOTSTRAP_RECEIPT_SHA = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"
EXPECTED_DATE_INVENTORY_SHA = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"

EXPECTED_TOTAL = {2024: (637, 6329), 2025: (654, 6410), 2026: (488, 4673)}
EXPECTED_EVAL = {"races": 1779, "runners": 17412, "dates": 269}
EXPECTED_PLC = {"eligible_races": 1743, "unknown_open_races": 36}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def source_path(relative: Path) -> Path:
    """Resolve a static project-relative source and reject escapes/symlinks out."""
    require(not relative.is_absolute() and ".." not in relative.parts, f"unsafe source path: {relative}")
    candidate = (PROJECT / relative).resolve(strict=True)
    try:
        candidate.relative_to(PROJECT)
    except ValueError as exc:
        raise RuntimeError(f"source resolves outside project: {relative}") from exc
    require(candidate.is_file(), f"not a regular source file: {relative}")
    return candidate


def output_path(name: str) -> Path:
    require(name in {"SOURCE_AUDIT.json", "SOURCE_AUDIT.md"}, "unexpected output filename")
    audit_dir = (PROJECT / AUDIT_REL).resolve()
    expected_dir = PROJECT / STUDY_REL / "audit"
    require(audit_dir == expected_dir, "audit output directory escaped the study folder")
    audit_dir.mkdir(parents=True, exist_ok=True)
    result = audit_dir / name
    require(result.parent == audit_dir, "audit output escaped audit directory")
    return result


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def facts(relative: Path) -> dict[str, Any]:
    path = source_path(relative)
    return {"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": digest_file(path)}


def read_json(relative: Path) -> dict[str, Any]:
    return json.loads(source_path(relative).read_text(encoding="utf-8"))


def f1_manifest_entry(manifest: dict[str, Any], relative: Path) -> dict[str, Any]:
    entry = manifest.get("study_artifacts", {}).get(relative.as_posix())
    require(isinstance(entry, dict), f"F1 manifest has no pinned entry for {relative}")
    return entry


def tb_manifest_entry(manifest: dict[str, Any], relative: Path) -> dict[str, Any]:
    local = relative.relative_to(TB_REL).as_posix()
    matches = [x for x in manifest.get("files_excluding_manifest", []) if x.get("path") == f"{TB_REL.as_posix()}/{local}"]
    if not matches:
        matches = [x for x in manifest.get("files_excluding_manifest", []) if x.get("path") == local]
    require(len(matches) == 1, f"TB FINAL manifest entry missing or ambiguous for {relative}")
    item = matches[0]
    return {"bytes": item.get("bytes"), "sha256": item.get("sha256")}


def joint_manifest_entry(manifest: dict[str, Any], relative: Path) -> dict[str, Any]:
    local = relative.relative_to(JOINT_REL).as_posix()
    matches = [x for x in manifest.get("files", []) if x.get("path") == local]
    require(len(matches) == 1, f"joint FINAL manifest entry missing or ambiguous for {relative}")
    item = matches[0]
    return {"bytes": item.get("size_bytes"), "sha256": item.get("sha256")}


def verify_against(relative: Path, expected: dict[str, Any], manifest_label: str) -> dict[str, Any]:
    actual = facts(relative)
    require(actual["bytes"] == expected.get("bytes", expected.get("size_bytes")),
            f"byte count differs from {manifest_label}: {relative}")
    require(actual["sha256"] == expected.get("sha256"), f"SHA differs from {manifest_label}: {relative}")
    actual["pinned_by"] = manifest_label
    return actual


def ensure_unique(values: list[Any], label: str) -> None:
    require(all(v is not None for v in values), f"null {label}")
    require(len(values) == len(set(values)), f"duplicate {label}")


def finite_scores(frame: pl.DataFrame, label: str) -> None:
    require("score" in frame.columns, f"no score column in {label}")
    require(frame.height > 0, f"empty score table: {label}")
    require(frame.get_column("score").null_count() == 0, f"null raw score in {label}")
    bad = frame.select((~pl.col("score").is_finite()).sum()).item()
    require(int(bad) == 0, f"nonfinite raw score in {label}: {bad}")


def load_target_keys() -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    features = pl.read_parquet(
        source_path(F1_FEATURES_REL),
        columns=["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "finish_position", "field_n", "history_cutoff", "latest_history_date"],
    )
    evalf = features.filter(pl.col("year").is_in([2024, 2025, 2026]))
    require(evalf.height == EXPECTED_EVAL["runners"], f"target F1 rows {evalf.height}")
    require(features.get_column("api_record_id").null_count() == 0, "null api_record_id in frozen F1 feature source")
    ensure_unique(features.get_column("api_record_id").to_list(), "frozen F1 api_record_id")
    require(evalf.get_column("api_record_id").null_count() == 0, "null F1 api_record_id")
    ensure_unique(evalf.get_column("api_record_id").to_list(), "F1 api_record_id")

    # Check the frozen complete-finish roster and its date-only T-2 feature cutoff.
    race_summaries: list[dict[str, Any]] = []
    for group in evalf.partition_by("race_id", maintain_order=False):
        ids = group.get_column("api_record_id").to_list()
        nums = group.get_column("horse_number").to_list()
        ranks = group.get_column("finish_position").to_list()
        horse_ids = group.get_column("horse_id").to_list()
        dates = group.get_column("race_date").unique().to_list()
        years = group.get_column("year").unique().to_list()
        field = group.get_column("field_n").unique().to_list()
        require(len(dates) == len(years) == len(field) == 1, "inconsistent race-level date/year/field_n")
        require(len(ids) == len(set(ids)), "duplicate api_record_id inside race")
        require(len(horse_ids) == len(set(horse_ids)), "duplicate horse_id inside race")
        require(len(nums) == len(set(nums)), "duplicate horse number inside race")
        require(len(ids) == int(field[0]), "race roster rows do not equal field_n")
        require(sorted(ranks) == list(range(1, len(ids) + 1)), "evaluation roster is not a complete unique 1..N finish order")
        race_date = date.fromisoformat(dates[0])
        expect_cutoff = (race_date - timedelta(days=2)).isoformat()
        cutoffs = group.get_column("history_cutoff").unique().to_list()
        require(cutoffs == [expect_cutoff], f"feature T-2 cutoff mismatch for {group.get_column('race_id')[0]}")
        latest = group.get_column("latest_history_date").to_list()
        require(all(value is None or value <= expect_cutoff for value in latest), "latest historical feature date exceeds T-2")
        race_summaries.append({"race_id": group.get_column("race_id")[0], "race_date": dates[0], "year": int(years[0]), "field_n": int(field[0]), "rows": len(ids)})

    year_counts: dict[str, dict[str, int]] = {}
    for y in (2024, 2025, 2026):
        f = evalf.filter(pl.col("year") == y)
        actual = (f.get_column("race_id").n_unique(), f.height)
        require(actual == EXPECTED_TOTAL[y], f"F1 year {y} cohort mismatch: {actual}")
        year_counts[str(y)] = {"races": actual[0], "runners": actual[1]}
    dates = sorted(evalf.get_column("race_date").unique().to_list())
    require(len(race_summaries) == EXPECTED_EVAL["races"], "F1 target race count mismatch")
    require(len(dates) == EXPECTED_EVAL["dates"], "F1 target date count mismatch")
    return features, evalf, {
        "rows": evalf.height,
        "races": len(race_summaries),
        "race_days": len(dates),
        "date_min": dates[0],
        "date_max": dates[-1],
        "years": year_counts,
        "all_finish_orders_complete_1_to_N": True,
        "all_rows_have_correct_inclusive_T_minus_2_history_cutoff": True,
        "latest_history_date_not_after_cutoff": True,
        "sorted_date_inventory_sha256": hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest(),
    }


def audit() -> dict[str, Any]:
    contract = facts(CONTRACT_REL)
    require(contract["sha256"] == EXPECTED_CONTRACT_SHA, "design contract hash mismatch")

    f1_manifest_facts = facts(F1_MANIFEST_REL)
    require(f1_manifest_facts["sha256"] == F1_MANIFEST_SHA, "F1 ARTIFACT_MANIFEST hash mismatch")
    f1_manifest = read_json(F1_MANIFEST_REL)
    tb_final_facts = facts(TB_FINAL_REL)
    require(tb_final_facts["sha256"] == TB_FINAL_SHA, "TB FINAL_MANIFEST hash mismatch")
    tb_final = read_json(TB_FINAL_REL)
    joint_final_facts = facts(JOINT_FINAL_REL)
    require(joint_final_facts["sha256"] == JOINT_FINAL_SHA, "joint FINAL_MANIFEST hash mismatch")
    joint_final = read_json(JOINT_FINAL_REL)

    # Verify the actual source files against their existing authoritative manifests.
    verified_sources: list[dict[str, Any]] = []
    f1_run_expected = f1_manifest.get("source_references", {}).get(F1_RUN_REL.as_posix())
    require(isinstance(f1_run_expected, dict), "F1 manifest has no pinned raw-score producer code")
    f1_run_fact = verify_against(F1_RUN_REL, f1_run_expected, F1_MANIFEST_REL.as_posix())
    verified_sources.append(f1_run_fact)
    verified_sources.append(verify_against(F1_FEATURES_REL, f1_manifest_entry(f1_manifest, F1_FEATURES_REL), F1_MANIFEST_REL.as_posix()))
    f1_meta: dict[int, dict[str, Any]] = {}
    f1_eval_frames: dict[int, pl.DataFrame] = {}
    f1_cal_frames: dict[int, pl.DataFrame] = {}
    f1_eval_facts: dict[int, dict[str, Any]] = {}
    f1_cal_facts: dict[int, dict[str, Any]] = {}
    for year in (2024, 2025, 2026):
        folder = F1_REL / f"outputs/F1_STYLE6_{year}"
        meta_rel = folder / "meta.json"
        eval_rel = folder / "evaluation_scores.parquet"
        cal_rel = folder / "calibration_scores.parquet"
        f1_meta[year] = read_json(meta_rel)
        f1_eval_facts[year] = verify_against(eval_rel, f1_manifest_entry(f1_manifest, eval_rel), F1_MANIFEST_REL.as_posix())
        f1_cal_facts[year] = verify_against(cal_rel, f1_manifest_entry(f1_manifest, cal_rel), F1_MANIFEST_REL.as_posix())
        verified_sources.append(verify_against(meta_rel, f1_manifest_entry(f1_manifest, meta_rel), F1_MANIFEST_REL.as_posix()))
        verified_sources.extend([f1_eval_facts[year], f1_cal_facts[year]])
        f1_eval_frames[year] = pl.read_parquet(source_path(eval_rel))
        f1_cal_frames[year] = pl.read_parquet(source_path(cal_rel))

    f1_results_rel = F1_REL / "FINAL_RESULTS.md"
    verified_sources.append(verify_against(f1_results_rel, f1_manifest_entry(f1_manifest, f1_results_rel), F1_MANIFEST_REL.as_posix()))
    tb_score_fact = verify_against(TB_SCORE_REL, tb_manifest_entry(tb_final, TB_SCORE_REL), TB_FINAL_REL.as_posix())
    tb_params_fact = verify_against(TB_PARAMS_REL, tb_manifest_entry(tb_final, TB_PARAMS_REL), TB_FINAL_REL.as_posix())
    tb_report_fact = verify_against(TB_REPORT_REL, tb_manifest_entry(tb_final, TB_REPORT_REL), TB_FINAL_REL.as_posix())
    tb_results_fact = verify_against(TB_RESULTS_REL, tb_manifest_entry(tb_final, TB_RESULTS_REL), TB_FINAL_REL.as_posix())
    tb_source_manifest_fact = verify_against(TB_SOURCE_MANIFEST_REL, tb_manifest_entry(tb_final, TB_SOURCE_MANIFEST_REL), TB_FINAL_REL.as_posix())
    tb_engine_fact = verify_against(TB_ENGINE_REL, tb_manifest_entry(tb_final, TB_ENGINE_REL), TB_FINAL_REL.as_posix())
    verified_sources.extend([tb_score_fact, tb_params_fact, tb_report_fact, tb_results_fact, tb_source_manifest_fact, tb_engine_fact])

    # Pin the R temperature source to the previously saved raw-score PL reference fits.
    tb_params = read_json(TB_PARAMS_REL)
    dynamic_params_fact = facts(DYNAMIC_PARAMS_REL)
    dynamic_engine_expected = tb_params["input_hashes"]["reference_engine_sha256"]
    dynamic_engine_fact = facts(DYNAMIC_ENGINE_REL)
    require(dynamic_engine_fact["sha256"] == dynamic_engine_expected, "R temperature producer code differs from TB-pinned reference engine")
    dynamic_params = read_json(DYNAMIC_PARAMS_REL)
    verified_sources.extend([dynamic_params_fact, dynamic_engine_fact])
    require(dynamic_params_fact["sha256"] == tb_params["input_hashes"]["reference_parameters_sha256"],
            "R PL-temperature source differs from TB's pinned reference parameters")
    require(tb_params.get("contract_sha256") == EXPECTED_TB_CONTRACT_SHA, "TB candidate parameters contract changed")

    all_features, target_keys, target_cohort = load_target_keys()
    all_by_api = {
        int(row["api_record_id"]): (row["race_id"], row["race_date"], int(row["year"]), int(row["horse_number"]), int(row["field_n"]))
        for row in all_features.select(["api_record_id", "race_id", "race_date", "year", "horse_number", "field_n"]).iter_rows(named=True)
    }
    target_by_api = {
        int(row["api_record_id"]): (row["race_id"], row["race_date"], int(row["year"]), int(row["horse_number"]), int(row["field_n"]))
        for row in target_keys.select(["api_record_id", "race_id", "race_date", "year", "horse_number", "field_n"]).iter_rows(named=True)
    }
    require(target_cohort["sorted_date_inventory_sha256"] == EXPECTED_DATE_INVENTORY_SHA,
            "F1 evaluation date inventory differs from frozen bootstrap schedule")

    r_years: dict[str, Any] = {}
    r_combined_ids: list[int] = []
    for year in (2024, 2025, 2026):
        scores = f1_eval_frames[year]
        require(scores.columns == ["api_record_id", "score"], f"unexpected R score schema for {year}: {scores.columns}")
        api_ids = scores.get_column("api_record_id").to_list()
        ensure_unique(api_ids, f"R {year} api_record_id")
        finite_scores(scores, f"R {year}")
        expected_ids = set(target_keys.filter(pl.col("year") == year).get_column("api_record_id").to_list())
        require(set(api_ids) == expected_ids, f"R {year} raw score IDs do not exactly match F1 target rows")
        meta = f1_meta[year]
        require(scores.height == int(meta["evaluation_rows"]), f"R {year} evaluation rows differ from F1 metadata")
        require(int(target_keys.filter(pl.col("year") == year).get_column("race_id").n_unique()) == int(meta["evaluation_races"]),
                f"R {year} evaluation races differ from F1 metadata")
        calibration_scores = f1_cal_frames[year]
        require(calibration_scores.columns == ["api_record_id", "score"], f"unexpected R calibration score schema for {year}")
        cal_ids = calibration_scores.get_column("api_record_id").to_list()
        ensure_unique(cal_ids, f"R {year} calibration api_record_id")
        finite_scores(calibration_scores, f"R {year} calibration")
        expected_cal_ids = set(all_features.filter(pl.col("year") == year - 1).get_column("api_record_id").to_list())
        require(set(cal_ids) == expected_cal_ids, f"R {year} calibration raw score IDs do not exactly match previous-year F1 rows")
        cal_races = int(all_features.filter(pl.col("year") == year - 1).get_column("race_id").n_unique())
        require(calibration_scores.height == int(meta["calibration_rows"]), f"R {year} calibration rows differ from F1 metadata")
        require(cal_races == int(meta["calibration_races"]), f"R {year} calibration races differ from F1 metadata")
        reference = dynamic_params["R_reference_fits"][str(year)]
        require(reference["evaluation_score_sha256"] == f1_eval_facts[year]["sha256"], f"R {year} PL refit points at different eval score file")
        cal_year = year - 1
        require(reference["calibration_year"] == cal_year and reference["evaluation_year"] == year, f"R {year} temperature vintage mismatch")
        require(reference["calibration_score_sha256"] == f1_cal_facts[year]["sha256"], f"R {year} calibration score pin mismatch")
        require(reference["calibration_races"] == cal_races and reference["calibration_runners"] == calibration_scores.height,
                f"R {year} calibration counts differ from PL reference metadata")
        require(reference["score_semantics"] == "raw_score_before_temperature", f"R {year} score semantics are not raw")
        require(meta["refit_max"] == {2024: "2022-12-24", 2025: "2023-12-30", 2026: "2024-12-28"}[year],
                f"R {year} refit cutoff differs from stored F1 metadata")
        require(reference["temperature"] == tb_params["R_temperatures_reused"][str(year)]["temperature"],
                f"R {year} copied PL temperature mismatch")
        r_combined_ids.extend(int(x) for x in api_ids)
        r_years[str(year)] = {
            "raw_score_path": (F1_REL / f"outputs/F1_STYLE6_{year}/evaluation_scores.parquet").as_posix(),
            "raw_score_bytes": f1_eval_facts[year]["bytes"],
            "evaluation_rows": scores.height,
            "evaluation_races": int(target_keys.filter(pl.col("year") == year).get_column("race_id").n_unique()),
            "score_schema": scores.columns,
            "score_finite_rows": scores.height,
            "exact_f1_target_key_match": True,
            "raw_score_sha256": f1_eval_facts[year]["sha256"],
            "provider_meta_sha256": facts(F1_REL / f"outputs/F1_STYLE6_{year}/meta.json")["sha256"],
            "refit_max": meta["refit_max"],
            "calibration_year": cal_year,
            "calibration_rows": reference["calibration_runners"],
            "calibration_races": reference["calibration_races"],
            "calibration_finite_rows": calibration_scores.height,
            "calibration_exact_previous_year_F1_key_match": True,
            "calibration_raw_score_sha256": f1_cal_facts[year]["sha256"],
            "training_min": meta["training_min"],
            "initial_training_max": meta["initial_training_max"],
            "early_stopping_min": meta["early_stopping_min"],
            "calibration_min": meta["calibration_min"],
            "calibration_max": meta["calibration_max"],
            "evaluation_min": meta["evaluation_min"],
            "evaluation_max": meta["evaluation_max"],
            "temperature": reference["temperature"],
            "temperature_source": f"{DYNAMIC_PARAMS_REL.as_posix()}#R_reference_fits.{year}",
        }
    require(len(r_combined_ids) == EXPECTED_EVAL["runners"] and len(set(r_combined_ids)) == EXPECTED_EVAL["runners"],
            "combined R score keys are not exact unique target roster")

    # Candidate table contains multiple arms/roles. Select exactly S evaluation rows.
    s_all = pl.read_parquet(source_path(TB_SCORE_REL))
    expected_s_schema = ["arm", "year", "role", "api_record_id", "race_id", "race_date", "horse_number", "field_n", "score"]
    require(s_all.columns == expected_s_schema, f"unexpected S score table schema: {s_all.columns}")
    s = s_all.filter((pl.col("arm") == "S") & (pl.col("role") == "evaluation"))
    s_cal = s_all.filter((pl.col("arm") == "S") & (pl.col("role") == "calibration"))
    require(s.height == EXPECTED_EVAL["runners"], f"S selected rows do not match cohort: {s.height}")
    ensure_unique(s.get_column("api_record_id").to_list(), "S evaluation api_record_id")
    finite_scores(s, "S evaluation")
    s_ids = s.get_column("api_record_id").to_list()
    require(set(s_ids) == set(target_by_api), "S exact api_record_id set differs from F1 target")
    for row in s.select(["api_record_id", "race_id", "race_date", "year", "horse_number", "field_n", "score"]).iter_rows(named=True):
        expected = target_by_api[int(row["api_record_id"])]
        actual = (row["race_id"], row["race_date"], int(row["year"]), int(row["horse_number"]), int(row["field_n"]))
        require(actual == expected, f"S metadata key mismatch for api_record_id={row['api_record_id']}")
    s_years: dict[str, Any] = {}
    model_params = {(int(x["evaluation_year"]), x["arm"]): x for x in tb_params["models"]}
    for year in (2024, 2025, 2026):
        sy = s.filter(pl.col("year") == year)
        races = int(sy.get_column("race_id").n_unique())
        require((races, sy.height) == EXPECTED_TOTAL[year], f"S {year} row/race count mismatch")
        meta = model_params[(year, "S")]
        require(sy.height == int(meta["evaluation_rows"]) and races == int(meta["evaluation_races"]),
                f"S {year} evaluation score counts differ from stored fit metadata")
        cal = s_cal.filter(pl.col("year") == year)
        require(cal.height == int(meta["calibration_rows"]), f"S {year} calibration score rows mismatch stored fit metadata")
        ensure_unique(cal.get_column("api_record_id").to_list(), f"S {year} calibration api_record_id")
        finite_scores(cal, f"S {year} calibration")
        expected_cal_ids = set(all_features.filter(pl.col("year") == year - 1).get_column("api_record_id").to_list())
        cal_ids = cal.get_column("api_record_id").to_list()
        require(set(cal_ids) == expected_cal_ids, f"S {year} calibration score IDs do not exactly match prior-year F1 rows")
        cal_races = int(all_features.filter(pl.col("year") == year - 1).get_column("race_id").n_unique())
        require(cal_races == int(meta["calibration_races"]), f"S {year} calibration races differ from stored fit metadata")
        for row in cal.select(["api_record_id", "race_id", "race_date", "year", "horse_number", "field_n"]).iter_rows(named=True):
            expected = all_by_api[int(row["api_record_id"])]
            actual = (row["race_id"], row["race_date"], int(row["year"]) - 1, int(row["horse_number"]), int(row["field_n"]))
            require(int(row["year"]) == year and actual == expected,
                    f"S {year} calibration metadata key mismatch for api_record_id={row['api_record_id']}")
        require(meta["refit_max"] <= meta["calibration_min"], f"S {year} refit overlaps calibration")
        require(meta["calibration_min"].startswith(f"{year-1}-") and meta["calibration_max"].startswith(f"{year-1}-"),
                f"S {year} calibration is not prior-year")
        require(meta["evaluation_min"].startswith(f"{year}-") and meta["evaluation_max"].startswith(f"{year}-"),
                f"S {year} evaluation year mismatch")
        t = meta["temperature_fit"]["temperature"]
        require(math.isfinite(t) and t > 0, f"S {year} has invalid stored temperature")
        s_years[str(year)] = {
            "raw_score_path": TB_SCORE_REL.as_posix(),
            "raw_score_bytes": tb_score_fact["bytes"],
            "raw_score_sha256": tb_score_fact["sha256"],
            "evaluation_rows": sy.height,
            "evaluation_races": races,
            "raw_score_finite_rows": sy.height,
            "exact_f1_target_key_match": True,
            "refit_max": meta["refit_max"],
            "calibration_min": meta["calibration_min"],
            "calibration_max": meta["calibration_max"],
            "calibration_rows": meta["calibration_rows"],
            "calibration_races": meta["calibration_races"],
            "initial_training_max": meta["initial_train_max"],
            "training_min": meta["train_min"],
            "early_stopping_min": meta["early_stop_min"],
            "early_stopping_max": meta["early_stop_max"],
            "evaluation_min": meta["evaluation_min"],
            "evaluation_max": meta["evaluation_max"],
            "calibration_score_rows_exact_previous_year_F1_keys": cal.height,
            "temperature": t,
            "temperature_fit_metadata": meta["temperature_fit"],
        }
    require(set(s_all.get_column("arm").unique().to_list()) == {"C", "S"}, "unexpected saved S source arms")
    require(set(s_all.get_column("role").unique().to_list()) == {"calibration", "evaluation"}, "unexpected saved S score roles")

    # Check the fixed, pre-existing date schedule and rules source without deriving metrics.
    bootstrap_fact = facts(BOOTSTRAP_REL)
    bootstrap_receipt_fact = facts(BOOTSTRAP_RECEIPT_REL)
    require(bootstrap_fact["sha256"] == EXPECTED_BOOTSTRAP_SHA, "fixed bootstrap schedule SHA mismatch")
    require(bootstrap_receipt_fact["sha256"] == EXPECTED_BOOTSTRAP_RECEIPT_SHA, "bootstrap receipt SHA mismatch")
    bootstrap_receipt = read_json(BOOTSTRAP_RECEIPT_REL)
    require(bootstrap_receipt["schedule_sha256"] == bootstrap_fact["sha256"], "bootstrap receipt schedule hash mismatch")
    require(bootstrap_receipt["date_inventory_sha256"] == target_cohort["sorted_date_inventory_sha256"],
            "bootstrap date inventory does not match sorted target dates")
    schedule = np.load(source_path(BOOTSTRAP_REL), mmap_mode="r", allow_pickle=False)
    require(schedule.shape == (2000, 269) and schedule.dtype == np.dtype("int32"), "fixed bootstrap schedule dimensions/dtype mismatch")
    require(int(schedule.min()) >= 0 and int(schedule.max()) < 269, "bootstrap schedule index outside target date roster")

    joint_preflight = read_json(JOINT_PREFLIGHT_REL)
    require(joint_preflight["feature_sha256"] == facts(F1_FEATURES_REL)["sha256"], "prior rules preflight references different F1 features")
    require(joint_preflight["evaluation_races"] == EXPECTED_EVAL["races"] and joint_preflight["evaluation_runners"] == EXPECTED_EVAL["runners"],
            "prior rules preflight cohort differs")
    require(joint_preflight["plc_eligible_races"] == EXPECTED_PLC["eligible_races"] and joint_preflight["plc_unknown_races"] == EXPECTED_PLC["unknown_open_races"],
            "prior PLC cohort differs")
    ledger_fact = verify_against(JOINT_LEDGER_REL, joint_manifest_entry(joint_final, JOINT_LEDGER_REL), JOINT_FINAL_REL.as_posix())
    ledger = pl.read_parquet(source_path(JOINT_LEDGER_REL))
    require(ledger.height == EXPECTED_EVAL["races"] * 7, "reference wager/race ledger row count mismatch")
    require(ledger.select(pl.struct(["race_id", "pool"]).n_unique()).item() == ledger.height,
            "reference wager/race ledger has duplicate race/pool keys")
    target_race_ids = set(target_keys.get_column("race_id").unique().to_list())
    require(set(ledger.get_column("race_id").unique().to_list()) == target_race_ids,
            "reference ledger race IDs differ from F1 evaluation roster")
    unknown_plc = ledger.filter((pl.col("pool") == "PLC") & (pl.col("event_label_status") == "opening_field_unknown_quarantined"))
    valid_plc = ledger.filter((pl.col("pool") == "PLC") & pl.col("event_label_status").str.starts_with("structural_event_label_available"))
    require(unknown_plc.height == EXPECTED_PLC["unknown_open_races"], "reference ledger PLC unknown count mismatch")
    require(valid_plc.height == EXPECTED_PLC["eligible_races"], "reference ledger PLC eligible count mismatch")
    require(unknown_plc.get_column("actual_field_n").to_list() == [7] * EXPECTED_PLC["unknown_open_races"],
            "PLC quarantined races do not all have actual 7-starter fields")
    require(unknown_plc.get_column("N_at_open_observed").to_list() == [False] * EXPECTED_PLC["unknown_open_races"],
            "PLC quarantine includes observed opening rosters")
    require(ledger.filter(pl.col("pool") != "PLC").height == EXPECTED_EVAL["races"] * 6,
            "non-PLC ledger pools do not retain all evaluation races")
    verified_sources.append(ledger_fact)

    # Include existing R/S result receipts and rule artifacts as immutable references.
    for relative, expected, label in [
        (TB_INPUT_MANIFEST_REL, {"bytes": 8245, "sha256": "7561d6f91d5a1a5059add0741d912e33896b04810a19dd1dab955b0ebd229f5e"}, "TB input manifest frozen in fit receipt"),
        (TB_FIT_RECEIPT_REL, {"bytes": 8475, "sha256": "fb70195287f1bc56c0c9fbe19acc6b7ec08b01a42a7a336da1b0a0c9f4b3bbe2"}, "TB fit receipt and approved input hashes"),
        (DYNAMIC_PARAMS_REL, {"bytes": 44131, "sha256": dynamic_params_fact["sha256"]}, "TB input_manifest.reference_parameters_sha256"),
        (JOINT_RULES_REL, joint_manifest_entry(joint_final, JOINT_RULES_REL), JOINT_FINAL_REL.as_posix()),
        (JOINT_README_REL, joint_manifest_entry(joint_final, JOINT_README_REL), JOINT_FINAL_REL.as_posix()),
        (JOINT_PREFLIGHT_REL, joint_manifest_entry(joint_final, JOINT_PREFLIGHT_REL), JOINT_FINAL_REL.as_posix()),
        (JOINT_REPORT_REL, joint_manifest_entry(joint_final, JOINT_REPORT_REL), JOINT_FINAL_REL.as_posix()),
    ]:
        verified_sources.append(verify_against(relative, expected, label))

    # Temperature calibration uses Y-1 only; fitting cutoffs stay before calibration and evaluation.
    r_temperature_map = {y: r_years[str(y)]["temperature"] for y in (2024, 2025, 2026)}
    s_temperature_map = {y: s_years[str(y)]["temperature"] for y in (2024, 2025, 2026)}
    require(set(r_temperature_map) == set(s_temperature_map) == {2024, 2025, 2026}, "incomplete R/S temperature coverage")

    script_fact = facts(AUDIT_REL / "source_audit.py")
    reference_candidates = [
        *verified_sources,
        contract,
        f1_manifest_facts,
        tb_final_facts,
        joint_final_facts,
        bootstrap_fact,
        bootstrap_receipt_fact,
        script_fact,
    ]
    reference_map: dict[str, dict[str, Any]] = {}
    for item in reference_candidates:
        ref = {key: item[key] for key in ("path", "bytes", "sha256")}
        existing = reference_map.get(ref["path"])
        require(existing is None or existing == ref, f"conflicting source references for {ref['path']}")
        reference_map[ref["path"]] = ref
    source_references = [reference_map[key] for key in sorted(reference_map)]
    return {
        "passed": True,
        "status": "PASS_SOURCE_PREFLIGHT_ONLY",
        "pass_scope": "locked source and roster preflight only; does not authorize E probability or outcome evaluation",
        "study": STUDY_REL.as_posix(),
        "scope": "Read-only audit of locked R/S raw OOS inputs, fixed temperatures, evaluation keys, prior rules/bootstrap sources, and pre-existing result references. No E score/probability/loss/metric is created or inspected.",
        "contract": {**contract, "expected_sha256": EXPECTED_CONTRACT_SHA},
        "audit_script": script_fact,
        "source_references": source_references,
        "cohort": {
            **target_cohort,
            "expected": EXPECTED_EVAL,
            "year_counts": target_cohort["years"],
            "R": {"exact_key_match": True, "years": r_years},
            "S": {"arm_filter": "arm == 'S' AND role == 'evaluation'", "exact_key_and_metadata_match": True,
                  "score_schema": expected_s_schema,
                  "raw_score_source": {"path": TB_SCORE_REL.as_posix(), "bytes": tb_score_fact["bytes"], "sha256": tb_score_fact["sha256"]},
                  "all_saved_arms": sorted(s_all.get_column("arm").unique().to_list()),
                  "all_saved_roles": sorted(s_all.get_column("role").unique().to_list()), "years": s_years},
            "plc": {**EXPECTED_PLC, "status_source": JOINT_PREFLIGHT_REL.as_posix(),
                    "exclusion_reason": "actual_field_n=7, N_at_open_observed=false, and event label quarantined; quarantine only for PLC",
                    "reference_ledger": {**ledger_fact, "rows": ledger.height, "unique_race_pool_keys": True,
                                         "exact_target_race_id_match": True, "other_pool_rows": EXPECTED_EVAL["races"] * 6}},
        },
        "temperatures": {
            "R_source": DYNAMIC_PARAMS_REL.as_posix() + "#R_reference_fits",
            "R_source_sha256": dynamic_params_fact["sha256"],
            "R_source_semantics": "stored PL temperature fitted on prior-year raw calibration scores; not F1 meta.json tau",
            "R_by_year": {str(y): {"temperature": r_years[str(y)]["temperature"], "calibration_year": y - 1,
                                    "calibration_rows": r_years[str(y)]["calibration_rows"],
                                    "calibration_races": r_years[str(y)]["calibration_races"],
                                    "refit_max": r_years[str(y)]["refit_max"]} for y in (2024, 2025, 2026)},
            "S_source": TB_PARAMS_REL.as_posix() + "#models[arm=S].temperature_fit",
            "S_source_sha256": tb_params_fact["sha256"],
            "S_by_year": {str(y): {"temperature": s_years[str(y)]["temperature"], "calibration_min": s_years[str(y)]["calibration_min"],
                                    "calibration_max": s_years[str(y)]["calibration_max"],
                                    "refit_max": s_years[str(y)]["refit_max"]} for y in (2024, 2025, 2026)},
            "no_current_study_refitting_or_temperature_optimization": True,
        },
        "score_producer_evidence": {
            "R": {**f1_run_fact, "raw_score_semantics": "F1 producer calls LightGBM predict with raw_score=True and stores api_record_id,score; source code lines 129-140"},
            "S": {**tb_engine_fact, "raw_score_semantics": "state-transfer producer calls predict(raw_score=True), checks finite values, and writes evaluation rows by arm/year/role; source code lines 810-812 and 1299-1307"},
            "R_temperature_fit_engine": {**dynamic_engine_fact, "role": "saved R_reference_fits temperature producer pinned by TB parameters"},
        },
        "fixed_rules_and_bootstrap": {
            "rules_contract": facts(JOINT_RULES_REL),
            "rules_readme": facts(JOINT_README_REL),
            "bootstrap_schedule": {**bootstrap_fact, "shape": list(schedule.shape), "dtype": str(schedule.dtype)},
            "bootstrap_receipt": {**bootstrap_receipt_fact, "date_inventory_sha256": bootstrap_receipt["date_inventory_sha256"],
                                  "draws": bootstrap_receipt["draws"], "dates_per_draw": bootstrap_receipt["dates_per_draw"],
                                  "frozen_status": bootstrap_receipt["status"]},
        },
        "existing_result_references": [
            {"role": "R historical baseline report", **next(x for x in verified_sources if x["path"] == f1_results_rel.as_posix())},
            {"role": "S historical study report", **tb_results_fact},
            {"role": "S historical machine-readable report", **tb_report_fact},
            {"role": "prior joint-wager source/rule study report", **verify_against(JOINT_REPORT_REL, joint_manifest_entry(joint_final, JOINT_REPORT_REL), JOINT_FINAL_REL.as_posix())},
        ],
        "pinned_manifests": [
            {**f1_manifest_facts, "role": "F1 ARTIFACT_MANIFEST"},
            {**tb_final_facts, "role": "TB FINAL_MANIFEST"},
            {**joint_final_facts, "role": "prior joint wager FINAL_MANIFEST"},
            {**facts(TB_INPUT_MANIFEST_REL), "role": "TB input manifest"},
        ],
        "verified_source_files": verified_sources,
        "timing_and_reuse": {
            "fold_rule": "For evaluation year Y, source fits/refits end by Y-2 and calibration is Y-1; stored annual R/S temperatures are applied unchanged.",
            "history_rule": "The F1 source features have race_date minus 2 calendar days inclusive cutoff; audited per evaluation runner.",
            "publication_timestamp_verified": False,
            "final_opening_roster_verified": False,
            "cohort_status": "reused retrospective development/evaluation cohort, not fresh independent future validation",
            "same_2024_2026_development_cohort_reused": True,
        },
        "not_done": ["No models loaded", "No scores calibrated", "No E probability computed", "No outcome metric or bootstrap result computed", "No database opened", "No source file copied or modified"],
    }


EXPECTED_TB_CONTRACT_SHA = "7dc4b4f861e91e080a238e7ad85475fb50a9a5fa695896f554b131c9a6540092"


def write_report(result: dict[str, Any]) -> None:
    json_path = output_path("SOURCE_AUDIT.json")
    md_path = output_path("SOURCE_AUDIT.md")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    c = result["cohort"]
    temps = result["temperatures"]
    artifacts = result["existing_result_references"]
    source_count = len(result["verified_source_files"])
    md = f"""# R/S mixture source audit\n\nStatus: **{result['status']}**. This is a source preflight only; no E mixture probabilities or metrics were created or inspected.\n\n- Frozen contract SHA-256: `{result['contract']['sha256']}`.\n- F1 target: {c['rows']:,} runners, {c['races']:,} races, {c['race_days']} race days ({c['date_min']} to {c['date_max']}); all complete 1..N ranks and inclusive T−2 history cutoffs passed.\n- Both R and S raw score sources join exactly to the F1 target keys, with finite scores and no duplicate API keys. S uses the exact filter `arm == S AND role == evaluation`.\n- PLC retains {c['plc']['eligible_races']:,} races; {c['plc']['unknown_open_races']} seven-runner races with unknown opening roster are quarantined only for PLC. The other six wagers retain all {c['races']:,} races.\n- R temperatures are pinned from `{temps['R_source']}` (not the unrelated F1 meta `tau`); S temperatures are pinned from `{temps['S_source']}`. Both use prior-year calibration and fixed stored values.\n- Existing bootstrap schedule: `{result['fixed_rules_and_bootstrap']['bootstrap_schedule']['path']}` SHA-256 `{result['fixed_rules_and_bootstrap']['bootstrap_schedule']['sha256']}`, shape {result['fixed_rules_and_bootstrap']['bootstrap_schedule']['shape']}; its sorted-date inventory matches the frozen 269-date roster.\n- {source_count} source-file facts are pinned against the existing F1/TB/joint manifests. Existing result references are hashes only: {', '.join(f'`{item["path"]}`' for item in artifacts)}.\n\nThis 2024–2026 cohort has already been used in the earlier R/S studies. It is a repeated retrospective development period, not fresh future validation. Race-day/publication timestamps and the actual final pre-race purchase roster remain unverified. This audit does not authorize E evaluation; the new fixed 50:50 full-Q mixture remains exactly as specified by the contract.\n\nRe-run with `.venv/bin/python -B jeju/research/20261022_rs_equal_mixture_v1/audit/source_audit.py`. The script has no CLI inputs, reads static paths only, and writes only the two files in this `audit/` directory.\n"""
    md_path.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    result = audit()
    write_report(result)
    print(json.dumps({"status": result["status"], "source_files": len(result["verified_source_files"]),
                      "cohort": result["cohort"]["expected"], "audit_json": (PROJECT / AUDIT_REL / "SOURCE_AUDIT.json").as_posix()}, ensure_ascii=False))

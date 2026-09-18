"""Build a new immutable Jeju top-three research dataset, without model fitting."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from horse_racing.analysis.jeju_native_top3_dataset import (
    EXPECTED_DB_SHA256,
    extract_dataset,
)
from horse_racing.analysis.jeju_native_top3_states import build_states

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = (
    ROOT / "data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3"
)
DEFAULT_OUTPUT = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"
PLAN = ROOT / "docs/JEJU_NATIVE_TOP3_MODEL_V1_PLAN_2026-09-15.md"
FORBIDDEN_FEATURES = {
    "finish_position",
    "finish_time_ms",
    "label_win",
    "label_top3",
    "target_eligible",
    "top3_target_eligible",
    "official_top3_count",
    "winner_count",
    "order_key",
    "set_key",
    "outcome_status",
    "winOdds",
    "plcOdds",
    "source_row_id",
    "source_row_hash",
    "horse_id",
    "race_id",
    "entry_id",
    "horse_number",
    "split",
    "full_rank_valid",
    "top3_rank_valid",
    "full_rank_target_mask",
    "podium_tie",
    "boundary_tie",
}


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")


def protocol() -> dict[str, Any]:
    return {
        "version": "jeju_native_top3_v1_plan_r3",
        "scope": "dataset_creation_only_no_model_fit_or_prediction_evaluation",
        "population": "retrospective_confirmed_starter_conditional_jeju_native",
        "goals": ["top3_set_exact_accuracy", "top3_order_exact_accuracy"],
        "primary_decision": "maximum_probability_set_then_maximum_order_within_set",
        "outcome_policy": "compatible_top3_orders_and_unique_sets_for_official_dead_heats",
        "primary_target_distance_excluded": [400],
        "identity_policy": "exclude_entire_race_if_any_actual_starter_unresolved",
        "cutoff_timezone": "Asia/Seoul",
        "cutoff": "day_before_18:00",
        "historical_event_lag_days": 2,
        "availability_class": "assumed_not_verified_historical_publication",
        "history_start": "2002-07-28",
        "coefficient_start": "2018-08-31",
        "development": ["2025-01-01", "2025-12-27"],
        "frozen_historical": ["2026-01-01", "2026-09-12"],
        "historical_evaluation_executed": False,
        "model_fits_executed": 0,
        "state_method": "fixed_heuristics_no_learned_parameters",
        "seed_candidates_for_later_modeling": [17, 43],
        "delegated_model": "gpt-5.6-luna",
        "delegated_reasoning_effort": "high",
        "plan_sha256": file_hash(PLAN),
    }


def month_start_before(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 - months
    year, zero_month = divmod(index, 12)
    return date(year, zero_month + 1, 1)


def enrich_history_sections(db: Path, history: pl.DataFrame) -> pl.DataFrame:
    """Attach measured early/closing intervals as result-side history only."""
    query = """
        SELECT c.entry_id, CASE WHEN c.section_code='S1F'
            AND c.distance_from_start_m=210 THEN 'S1F210' ELSE c.section_code END,
            c.source_value_ms
        FROM section_checkpoint c
        JOIN entry e ON e.id=c.entry_id
        JOIN event v ON v.id=e.event_id
        WHERE v.event_type='race' AND e.segment_quality='usable'
          AND e.finish_position BETWEEN 1 AND 89
          AND c.source_value_ms>0 AND c.distance_is_approximate=0
          AND (
            (c.section_code='S1F' AND c.time_basis='cumulative'
             AND (c.distance_from_start_m=200 OR
                  (c.distance_from_start_m=210 AND v.distance_m IN (1110,1610))))
            OR (c.section_code='G1F' AND c.time_basis='closing'
                AND c.distance_from_start_m=v.distance_m-200)
            OR (c.section_code='G3F' AND c.time_basis='closing'
                AND c.distance_from_start_m=v.distance_m-600)
          )
    """
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
        rows = connection.execute(query).fetchall()
    sections = pl.DataFrame(
        rows,
        schema={"entry_id": pl.Int64, "section_code": pl.String, "source_value_ms": pl.Int64},
        orient="row",
    )
    if sections.select("entry_id", "section_code").unique().height != sections.height:
        raise ValueError("Duplicate section checkpoint")
    for code, column in (
        ("S1F", "section_s1f_ms"),
        ("S1F210", "section_s1f210_ms"),
        ("G1F", "section_g1f_ms"),
        ("G3F", "section_g3f_ms"),
    ):
        frame = sections.filter(pl.col("section_code") == code).select(
            "entry_id", pl.col("source_value_ms").alias(column)
        )
        history = history.join(frame, on="entry_id", how="left", validate="1:1")
    return history


def fold_assignments(entries: pl.DataFrame) -> pl.DataFrame:
    definitions = [
        ("dev_2025_q1", date(2025, 1, 1), date(2025, 3, 31)),
        ("dev_2025_q2", date(2025, 4, 1), date(2025, 6, 30)),
        ("dev_2025_q3", date(2025, 7, 1), date(2025, 9, 30)),
        ("dev_2025_q4", date(2025, 10, 1), date(2025, 12, 27)),
        ("frozen_2026", date(2026, 1, 1), date(2026, 9, 12)),
    ]
    rows = []
    races = entries.select("race_id", "event_date", "target_eligible").unique().to_dicts()
    for fold_id, start, end in definitions:
        tune_start = month_start_before(start, 6)
        cal_start = month_start_before(start, 3)
        for race in races:
            day = race["event_date"]
            if day > end:
                continue
            if day < date(2018, 8, 31):
                role = "state_history"
            elif not race["target_eligible"]:
                role = "label_ineligible"
            elif day < tune_start:
                role = "fit"
            elif day < cal_start:
                role = "tune"
            elif day <= start - timedelta(days=2):
                role = "calibration"
            elif day < start:
                role = "label_pending_at_cutoff"
            else:
                role = "evaluation"
            rows.append(
                {
                    "fold_id": fold_id,
                    "race_id": race["race_id"],
                    "event_date": day,
                    "role": role,
                    "evaluation_start": start,
                    "evaluation_end": end,
                }
            )
    return pl.DataFrame(rows).sort(["fold_id", "event_date", "race_id"])


def validate_tables(tables: dict[str, pl.DataFrame], registry: list[dict]) -> dict[str, Any]:
    entries, labels, states = (tables[name] for name in ("entries", "labels", "horse_states"))
    for name in ("entries", "labels", "horse_states"):
        frame = tables[name]
        if frame["entry_id"].n_unique() != frame.height:
            raise ValueError(f"Duplicate entry_id: {name}")
        if set(frame["entry_id"]) != set(entries["entry_id"]):
            raise ValueError(f"Missing or extra entry keys: {name}")
        for column, dtype in frame.schema.items():
            if dtype in (pl.Float32, pl.Float64):
                if frame.select(
                    (pl.col(column).is_not_null() & ~pl.col(column).is_finite()).any()
                ).item():
                    raise ValueError(f"Nonfinite values: {name}.{column}")
    feature_names = [item["feature_name"] for item in registry]
    if len(feature_names) != len(set(feature_names)):
        raise ValueError("Duplicate feature registry names")
    if set(feature_names) & FORBIDDEN_FEATURES:
        raise ValueError(f"Forbidden feature: {set(feature_names) & FORBIDDEN_FEATURES}")
    if set(feature_names) - set(states.columns):
        raise ValueError(f"Missing registered features: {set(feature_names) - set(states.columns)}")
    for name, column in (("accepted_orders", "order_key"), ("accepted_sets", "set_key")):
        frame = tables[name]
        if frame.select("race_id", column).unique().height != frame.height:
            raise ValueError(f"Duplicate top3 answer: {name}")
    active_races = set(entries.filter(pl.col("target_eligible"))["race_id"])
    for name in ("accepted_orders", "accepted_sets"):
        if active_races != set(tables[name]["race_id"]):
            raise ValueError(f"Answer coverage mismatch: {name}")
    key_bytes = "\n".join(
        f"{row[0]}:{row[1]}"
        for row in entries.select("race_id", "entry_id").sort(["race_id", "entry_id"]).iter_rows()
    ).encode()
    split_counts = (
        entries.group_by("split")
        .agg(pl.col("race_id").n_unique().alias("races"), pl.len().alias("entries"))
        .sort("split")
        .to_dicts()
    )
    state_splits = states.join(
        entries.select("entry_id", "split"), on="entry_id", how="left", validate="1:1"
    )
    feature_coverage = []
    for (split,), frame in state_splits.partition_by("split", as_dict=True).items():
        for item in registry:
            name = item["feature_name"]
            feature_coverage.append(
                {
                    "split": split,
                    "feature": name,
                    "arm": item["arm"],
                    "rows": frame.height,
                    "non_null_rows": frame[name].len() - frame[name].null_count(),
                    "non_null_rate": 1.0 - frame[name].null_count() / frame.height,
                }
            )
    return {
        "entry_keys_equal": True,
        "registered_features_present": True,
        "forbidden_feature_count": 0,
        "nonfinite_feature_count": 0,
        "target_answer_coverage": 1.0,
        "state_entry_coverage": 1.0,
        "entry_key_sha256": hashlib.sha256(key_bytes).hexdigest(),
        "split_counts": split_counts,
        "feature_count": len(feature_names),
        "feature_coverage": feature_coverage,
        "coverage_definition": "Non-null features; not proof of complete source capture",
        "tables": {
            name: {"rows": frame.height, "columns": {k: str(v) for k, v in frame.schema.items()}}
            for name, frame in tables.items()
        },
    }


def build(db: Path, output: Path) -> Path:
    if output.exists():
        raise FileExistsError(f"Immutable output already exists: {output}")
    db = db.resolve()
    before = file_hash(db)
    if before != EXPECTED_DB_SHA256:
        raise ValueError("Source DB does not match the reviewed snapshot")
    code_files = [
        Path(__file__),
        ROOT / "scripts/verify_jeju_native_top3_dataset.py",
        ROOT / "src/horse_racing/analysis/jeju_native_top3_dataset.py",
        ROOT / "src/horse_racing/analysis/jeju_native_top3_states.py",
        PLAN,
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        ROOT / "tests/test_jeju_native_top3_dataset.py",
        ROOT / "tests/test_jeju_native_top3_states.py",
        ROOT / "tests/test_jeju_native_top3_artifact.py",
    ]
    code_before = {
        str(path.relative_to(ROOT)): file_hash(path) for path in code_files if path.exists()
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(output.name + f".building-{os.getpid()}")
    staging.mkdir(exist_ok=False)
    write_json(staging / "protocol.json", protocol())
    print("Extracting read-only source cohort and top-three labels", flush=True)
    tables = extract_dataset(db)
    tables["history_results"] = enrich_history_sections(db, tables["history_results"])
    print(f"Building past-only states for {tables['entries'].height:,} entries", flush=True)
    states, state_metadata = build_states(db, tables["entries"], tables["history_results"])
    tables["horse_states"] = states
    tables["fold_assignments"] = fold_assignments(tables["entries"])
    registry = state_metadata["feature_registry"]
    checks = validate_tables(tables, registry)
    for name, frame in tables.items():
        frame.write_parquet(staging / f"{name}.parquet", compression="zstd")
    write_json(staging / "feature_registry.json", registry)
    write_json(staging / "state_metadata.json", state_metadata)
    write_json(staging / "dataset_report.json", checks)
    (staging / "README.md").write_text(
        "# 제주마 Top3 집합·정확 순서 연구 데이터셋\n\n"
        "목표: 실제 상위 세 마리 집합과 1·2·3착 순서를 각각 완전히 맞히는 예측.\n\n"
        "- entries: 비400m 출전 메타. labels: 분리된 정답.\n"
        "- accepted_orders / accepted_sets: 동착 호환 정답. 한 경주에 여러 정답 가능.\n"
        "- history_results: 400m을 포함한 과거 관측; 대상 결과 입력으로 사용 금지.\n"
        "- horse_states: T−2일까지의 과거로 만든 H0/H1/H2 보조 상태.\n"
        "- fold_assignments: 경주별 시간순 fit/tune/calibration/evaluation 역할.\n"
        "- source row/hash, target_eligible 등 메타는 모델 feature가 아님.\n"
        "- S1F 200m와 1110/1610m 경주의 S1F 210m는 별도 feature로 보존.\n"
        "- reproduce/: 생성 당시 코드·계획·의존성 계약의 사본.\n"
        "- feature_registry.json의 arm별 허용 열만 선택. H2는 공개시각 가정의 보조 arm.\n"
        "- coverage_unknown=1은 원천 전체 관측 완전성을 입증하지 못했다는 뜻.\n"
        "- protocol / dataset_report / state_metadata / manifest에서 계약·수량·hash 확인.\n\n"
        "이력 시작 전 경력은 관측되지 않을 수 있으며 첫 관측을 생애 첫 출전으로 단정하지 않습니다. "
        "모델 학습과 예측 성능 평가는 실행하지 않았습니다. "
        "사후 확인 출발집합과 역사적 공개시각 가정을 사용하는 연구 데이터입니다.\n\n"
        "재생성(새 디렉터리 지정):\n\n```bash\n"
        ".venv/bin/python scripts/build_jeju_native_top3_dataset.py --output /absolute/new/output\n"
        ".venv/bin/python scripts/verify_jeju_native_top3_dataset.py "
        "--dataset /absolute/new/output\n```\n"
    )
    write_json(
        staging / "run_ledger.json",
        {
            "action": "dataset_build",
            "model_fit_count": 0,
            "calibration_fit_count": 0,
            "parameter_fit_count": 0,
            "prediction_evaluation_count": 0,
            "created_at": datetime.now().astimezone().isoformat(),
        },
    )
    if file_hash(db) != before:
        raise RuntimeError("Source DB changed during build; refusing to seal")
    code_after = {
        str(path.relative_to(ROOT)): file_hash(path) for path in code_files if path.exists()
    }
    if code_after != code_before:
        raise RuntimeError("Dataset code or plan changed during build; refusing to seal")
    for path in code_files:
        if path.exists():
            snapshot = staging / "reproduce" / path.relative_to(ROOT)
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, snapshot)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    manifest = {
        "version": "jeju_native_top3_dataset_v1_r2",
        "created_at": datetime.now().astimezone().isoformat(),
        "source_db": {"path": str(db), "sha256": before, "hash_unchanged_after_build": True},
        "code": code_before,
        "git_commit": revision,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "polars": pl.__version__,
        },
        "files": {
            str(path.relative_to(staging)): {
                "sha256": file_hash(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        },
        "checks": {k: v for k, v in checks.items() if k != "tables"},
        "notes": [
            "Labels are not model features.",
            "Availability is historically assumed.",
            "No model trained and no historical prediction metric evaluated.",
            "Read feature_registry allow-lists; do not select all numeric columns.",
        ],
    }
    write_json(staging / "manifest.json", manifest)
    staging.rename(output)
    print(
        json.dumps(
            {
                "output": str(output),
                "counts": checks["split_counts"],
                "features": checks["feature_count"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.db, args.output.resolve())


if __name__ == "__main__":
    main()

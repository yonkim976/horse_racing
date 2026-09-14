#!/usr/bin/env python3
"""Read-only E7-A source and per-start feature audit; never fits a model."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict, deque
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Any

import polars as pl

from horse_racing.analysis.confirmed_starter_e6a_v2 import adapt_history_outcomes
from horse_racing.analysis.confirmed_starter_e7a import (
    BOUND,
    FEATURES,
    E7AContractError,
    build_sequence,
    canonical_relative_observations,
    exact_target_keys,
    independent_relative_check,
)
from horse_racing.analysis.features.base import as_date
from horse_racing.analysis.features.speed_figure import (
    _race_pars_and_variants,
    _race_summaries,
    performance_observations,
)

ROOT = Path(__file__).resolve().parents[1]
H1 = ROOT / "data/datasets/confirmed_starter_e2_h1_remediation_retrospective"
H1 = H1 / "start_minus_30m/dataset.parquet"
H1_MANIFEST = H1.with_name("manifest.json")
DB = ROOT / "data/horse_racing.sqlite3"
OUTPUT_BASE = ROOT / "data/experiments/confirmed_starter_e7a_20260913"
SEALED = {
    H1: "9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7",
    H1_MANIFEST: "f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801",
    ROOT / "data/experiments/confirmed_starter_e6b_20260913/artifact_manifest.json": "",
    ROOT / "data/experiments/confirmed_starter_e6a_v2_20260913_attempt4/artifact_manifest.json": (
        "24c667ed059fbf59eabc7676ee9222279fbd895711f958a6241efd2b0789d3b2"
    ),
    ROOT / "data/experiments/model_runs.jsonl": "",
}


def preserved_paths() -> set[Path]:
    """Carry forward all E6-B output and upstream frozen paths, plus E6-B source."""
    e6b = json.loads(
        (
            ROOT / "data/experiments/confirmed_starter_e6b_20260913/artifact_manifest.json"
        ).read_text()
    )
    return (
        set(SEALED)
        | {ROOT / name for name in e6b["outputs"]}
        | {ROOT / name for name in e6b["frozen_hashes_before"]}
        | {
            ROOT / "src/horse_racing/analysis/confirmed_starter_e6b.py",
            ROOT / "scripts/run_confirmed_starter_e6b.py",
            ROOT / "tests/test_confirmed_starter_e6b.py",
            ROOT / "docs/CONFIRMED_STARTER_E6B_2026-09-13.md",
            ROOT / "docs/CONFIRMED_STARTER_E6B_INDEPENDENT_REVIEW_2026-09-13.md",
        }
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def output_path() -> Path:
    if not OUTPUT_BASE.exists():
        return OUTPUT_BASE
    index = 2
    while Path(f"{OUTPUT_BASE}_attempt{index}").exists():
        index += 1
    return Path(f"{OUTPUT_BASE}_attempt{index}")


def read_rows(
    connection: sqlite3.Connection, query: str, parameters: tuple[Any, ...]
) -> pl.DataFrame:
    cursor = connection.execute(query, parameters)
    names = [item[0] for item in cursor.description]
    rows = cursor.fetchall()
    return pl.DataFrame(rows, schema=names, orient="row", infer_schema_length=None)


def load_history(connection: sqlite3.Connection, before_date: str) -> pl.DataFrame:
    rows = read_rows(
        connection,
        """
        SELECT r.race_date_local, r.id AS race_id, r.race_number,
               c.kra_meet_code AS meet_code, r.status AS race_status,
               r.distance_m, r.track_condition,
               e.id AS race_entry_id, e.horse_id, e.horse_number, e.scratched,
               rr.finish_position, rr.finish_time_ms, rr.rank_remark, rr.disqualified
        FROM race_entries e
        JOIN races r ON r.id=e.race_id
        JOIN racecourses c ON c.id=r.racecourse_id
        LEFT JOIN race_results rr ON rr.race_entry_id=e.id
        WHERE r.race_date_local < ? AND r.race_date_local <= ?
        ORDER BY r.race_date_local,r.id,e.id
        """,
        (before_date, BOUND),
    )
    return adapt_history_outcomes(rows)


def load_normal_finish(connection: sqlite3.Connection, before_date: str) -> pl.DataFrame:
    rows = read_rows(
        connection,
        """
        SELECT e.id AS race_entry_id,e.horse_id,r.id AS race_id,
               c.kra_meet_code AS meet_code,r.race_date_local AS race_date,
               r.distance_m,r.track_condition,
               rr.finish_position,rr.finish_time_ms
        FROM race_entries e
        JOIN races r ON r.id=e.race_id
        JOIN racecourses c ON c.id=r.racecourse_id
        JOIN race_results rr ON rr.race_entry_id=e.id
        WHERE r.status='completed' AND rr.finish_position BETWEEN 1 AND 89
          AND r.race_date_local < ? AND r.race_date_local <= ?
        ORDER BY r.race_date_local,r.id,e.id
        """,
        (before_date, BOUND),
    )
    return as_date(rows, "race_date").with_columns(pl.len().over("race_id").alias("starters"))


def load_selected_sections(
    connection: sqlite3.Connection, race_ids: set[int], before_date: str
) -> pl.DataFrame:
    frames = []
    ordered = sorted(race_ids)
    for offset in range(0, len(ordered), 300):
        ids = ordered[offset : offset + 300]
        markers = ",".join("?" for _ in ids)
        frames.append(
            read_rows(
                connection,
                f"""
                SELECT e.horse_id,e.id AS race_entry_id,r.id AS race_id,
                       c.kra_meet_code AS meet_code,r.race_date_local AS race_date,
                       r.distance_m,s.section_code,s.elapsed_time_ms,s.time_basis,
                       s.source_kind,rr.finish_position,rr.finish_time_ms
                FROM race_section_results s
                JOIN race_entries e ON e.id=s.race_entry_id
                JOIN races r ON r.id=e.race_id
                JOIN racecourses c ON c.id=r.racecourse_id
                LEFT JOIN race_results rr ON rr.race_entry_id=e.id
                WHERE r.id IN ({markers}) AND r.race_date_local < ?
                  AND r.race_date_local <= ?
                ORDER BY r.id,e.id,s.id
                """,
                (*ids, before_date, BOUND),
            )
        )
    return pl.concat(frames, how="vertical") if frames else pl.DataFrame()


def speed_source_frame(
    normal: pl.DataFrame, selected_entries: set[int]
) -> tuple[pl.DataFrame, dict[str, Any]]:
    observations = performance_observations(normal)
    summaries = _race_summaries(normal)
    summary_by_race = {summary.race_id: summary for summary in summaries}
    adjusted_pars, sample_sizes = _race_pars_and_variants(summaries)
    raw_pars: dict[int, float] = {}
    raw_sample_sizes: dict[int, int] = {}
    exact_history: dict[tuple[int, int, str], deque[tuple[date, float]]] = defaultdict(deque)
    distance_history: dict[tuple[int, int], deque[tuple[date, float]]] = defaultdict(deque)
    by_day: dict[date, list[Any]] = defaultdict(list)
    for summary in summaries:
        by_day[summary.race_date].append(summary)
    for day in sorted(by_day):
        for summary in by_day[day]:
            exact = exact_history[(summary.meet_code, summary.distance_m, summary.going)]
            fallback = distance_history[(summary.meet_code, summary.distance_m)]
            cutoff = day - timedelta(days=730)
            while exact and exact[0][0] < cutoff:
                exact.popleft()
            while fallback and fallback[0][0] < cutoff:
                fallback.popleft()
            values = (
                [value for _, value in exact]
                if len(exact) >= 12
                else ([value for _, value in fallback] if len(fallback) >= 20 else [])
            )
            if values:
                raw_pars[summary.race_id] = float(median(values))
                raw_sample_sizes[summary.race_id] = len(values)
        for summary in by_day[day]:
            exact_history[(summary.meet_code, summary.distance_m, summary.going)].append(
                (day, summary.top3_speed)
            )
            distance_history[(summary.meet_code, summary.distance_m)].append(
                (day, summary.top3_speed)
            )
    residuals: dict[tuple[date, int], list[float]] = defaultdict(list)
    for summary in summaries:
        raw = raw_pars.get(summary.race_id)
        if raw is not None:
            residuals[(summary.race_date, summary.meet_code)].append(
                math.log(summary.top3_speed / raw)
            )
    variants = {
        key: max(-0.06, min(0.06, float(median(values)) if len(values) >= 3 else 0.0))
        for key, values in residuals.items()
    }
    independent_par_mismatches = 0
    for summary in summaries:
        raw = raw_pars.get(summary.race_id)
        upstream = adjusted_pars.get(summary.race_id)
        if (raw is None) != (upstream is None):
            independent_par_mismatches += 1
        elif raw is not None:
            expected = raw * math.exp(variants[(summary.race_date, summary.meet_code)])
            if (
                abs(expected - upstream) > 1e-12
                or raw_sample_sizes[summary.race_id] != sample_sizes[summary.race_id]
            ):
                independent_par_mismatches += 1
    if independent_par_mismatches:
        raise E7AContractError(
            f"independent par/day-variant mismatches: {independent_par_mismatches}"
        )
    selected = normal.filter(pl.col("race_entry_id").is_in(selected_entries))
    rows = []
    mismatches = 0
    for row in selected.iter_rows(named=True):
        entry_id = int(row["race_entry_id"])
        race_id = int(row["race_id"])
        item = observations.get(entry_id)
        adjusted = adjusted_pars.get(race_id)
        raw = raw_pars.get(race_id)
        source_row = summary_by_race.get(race_id)
        variant = (
            variants[(source_row.race_date, source_row.meet_code)]
            if source_row is not None and raw is not None
            else None
        )
        figure = item.figure if item else None
        if figure is not None:
            speed = float(row["distance_m"]) / (float(row["finish_time_ms"]) / 1000.0)
            raw_figure = max(-10.0, min(10.0, 100.0 * math.log(speed / adjusted)))
            percentile = (
                (int(row["finish_position"]) - 1) / (max(1, int(row["starters"])) - 1)
                if int(row["starters"]) > 1
                else 0.0
            )
            independent = (
                max(raw_figure, -4.0) if percentile >= 0.60 and raw_figure < -4.0 else raw_figure
            )
            if abs(independent - figure) > 1e-10:
                mismatches += 1
        rows.append(
            {
                "race_entry_id": entry_id,
                "speed_figure": figure,
                "speed_par": adjusted,
                "speed_par_sample_n": sample_sizes.get(race_id),
                "speed_censored": item.censored if item else None,
                "speed_going": row["track_condition"],
                "speed_day_variant": variant,
                "source_race_date": row["race_date"].isoformat(),
            }
        )
    if mismatches:
        raise E7AContractError(f"independent speed-figure mismatches: {mismatches}")
    return pl.DataFrame(rows, infer_schema_length=None), {
        "selected_normal_entries": selected.height,
        "computed_observations": sum(item["speed_figure"] is not None for item in rows),
        "independent_figure_mismatches": mismatches,
        "independent_par_day_variant_mismatches": independent_par_mismatches,
        "par_races_checked": len(summaries),
        "par_policy": "prior 730d; going-specific >=12 else distance >=20; no full-period fallback",
        "day_variant": "past day/meet >=3 residuals; median clipped +/-0.06; day < target",
    }


def independent_slot_check(
    targets: pl.DataFrame,
    history: pl.DataFrame,
    evidence: pl.DataFrame,
    features: pl.DataFrame,
) -> dict[str, int]:
    """Naive independent all-row/date selection, distinct from primary date buckets."""
    by_horse: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in history.iter_rows(named=True):
        by_horse[int(row["horse_id"])].append(row)
    evidence_by_key = {
        (int(row["race_id"]), int(row["race_entry_id"]), int(row["slot"])): row
        for row in evidence.iter_rows(named=True)
    }
    features_by_key = {
        (int(row["race_id"]), int(row["race_entry_id"])): row
        for row in features.iter_rows(named=True)
    }
    mismatches = 0
    for target in targets.select(
        "race_id", "race_entry_id", "horse_id", "race_date_local"
    ).iter_rows(named=True):
        prior = [
            row
            for row in by_horse[int(target["horse_id"])]
            if row["race_date_local"] < target["race_date_local"]
            and row["start_state"] != "did_not_start"
        ]
        dates = sorted({row["race_date_local"] for row in prior}, reverse=True)
        blocked = False
        for slot in (1, 2, 3):
            expected = None
            if not blocked and len(dates) >= slot:
                same_date = [row for row in prior if row["race_date_local"] == dates[slot - 1]]
                if len(same_date) != 1 or same_date[0]["start_state"] not in {
                    "normal_finish",
                    "started_dnf",
                    "disqualified",
                }:
                    blocked = True
                else:
                    expected = same_date[0]
            actual = evidence_by_key[(int(target["race_id"]), int(target["race_entry_id"]), slot)]
            if (None if expected is None else expected["race_entry_id"]) != actual[
                "prior_race_entry_id"
            ]:
                mismatches += 1
            if (
                expected is not None
                and expected["race_date_local"] != actual["prior_race_date_local"]
            ):
                mismatches += 1
            expected_days = (
                None
                if expected is None
                else (
                    date.fromisoformat(target["race_date_local"])
                    - date.fromisoformat(expected["race_date_local"])
                ).days
            )
            feature_row = features_by_key[(int(target["race_id"]), int(target["race_entry_id"]))]
            if expected_days != feature_row[f"sequence_start{slot}_days_ago"]:
                mismatches += 1
    if mismatches:
        raise E7AContractError(f"independent slot mismatches: {mismatches}")
    return {"checked_slots": evidence.height, "mismatch_slots": 0}


def audit_coverage(
    features: pl.DataFrame, evidence: pl.DataFrame, h1: pl.DataFrame, selected_names: list[str]
) -> dict[str, Any]:
    rows = []
    for slot in (1, 2, 3):
        part = evidence.filter(pl.col("slot") == slot)
        item = {"slot": slot, "status_counts": dict(Counter(part["slot_status"].to_list()))}
        for name in ("early_rel", "last200_rel", "speed_figure"):
            item[name] = {
                "nonnull": features[f"sequence_start{slot}_{name}"].len()
                - features[f"sequence_start{slot}_{name}"].null_count(),
                "reason_counts": dict(Counter(part[f"{name}_reason"].to_list())),
            }
        item["days_ago_nonnull"] = (
            features[f"sequence_start{slot}_days_ago"].len()
            - features[f"sequence_start{slot}_days_ago"].null_count()
        )
        item["prior_meet_counts"] = dict(
            Counter(str(value) for value in part["prior_meet_code"].to_list())
        )
        rows.append(item)
    target_states = {}
    for status in ("started_dnf", "disqualified", "normal_finish"):
        keys = h1.filter(pl.col("outcome_state") == status).select("race_id", "race_entry_id")
        subset = features.join(keys, on=["race_id", "race_entry_id"], how="inner", validate="1:1")
        target_states[status] = {
            "rows": subset.height,
            "nonnull_by_feature": {
                name: subset.height - subset[name].null_count() for name in FEATURES
            },
        }
    duplicate = {}
    h1 = h1.sort("race_id", "race_entry_id")
    for name in FEATURES:
        duplicate[name] = {}
        for prior in selected_names:
            if h1.schema[prior] not in {
                pl.Float64,
                pl.Float32,
                pl.Int64,
                pl.Int32,
                pl.Int8,
                pl.UInt8,
            }:
                continue
            a = features[name].to_numpy()
            b = h1[prior].to_numpy()
            both_null = features[name].is_null().to_numpy() & h1[prior].is_null().to_numpy()
            valid = features[name].is_not_null().to_numpy() & h1[prior].is_not_null().to_numpy()
            equal = both_null.sum() + sum(
                abs(float(x) - float(y)) <= 1e-10
                for x, y, ok in zip(a, b, valid, strict=True)
                if ok
            )
            rate = float(equal / features.height)
            if rate >= 0.95:
                duplicate[name][prior] = rate
    return {
        "slots": rows,
        "target_state_coverage": target_states,
        "high_duplicate_rate_ge_0_95": duplicate,
    }


def main() -> None:
    output = output_path()
    output.mkdir(parents=True)
    before = {str(path.relative_to(ROOT)): sha(path) for path in sorted(preserved_paths())}
    db_before = sha(DB)
    for path, expected in SEALED.items():
        if expected and before[str(path.relative_to(ROOT))] != expected:
            raise E7AContractError(f"sealed input mismatch: {path}")
    h1 = pl.read_parquet(H1)
    if (
        h1.height != 15579
        or h1["race_id"].n_unique() != 1488
        or h1["race_date_local"].max() > BOUND
    ):
        raise E7AContractError("H1 scope mismatch")
    targets = h1.select("race_id", "race_entry_id", "horse_id", "race_date_local")
    before_target = h1["race_date_local"].max()
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        history = load_history(connection, before_target)
        normal = load_normal_finish(connection, before_target)
        if history.is_empty() or normal.is_empty():
            raise E7AContractError("no historical source")
        blank = pl.DataFrame(schema={"race_entry_id": pl.Int64})
        _, preliminary = build_sequence(targets, history, blank, blank)
        selected = set(preliminary["prior_race_entry_id"].drop_nulls().to_list())
        race_ids = set(preliminary["prior_race_id"].drop_nulls().to_list())
        sections = load_selected_sections(connection, race_ids, before_target)
    finally:
        connection.close()
    relative = canonical_relative_observations(
        sections, normal.filter(pl.col("race_id").is_in(race_ids))
    )
    relative_check = independent_relative_check(relative, normal)
    figures, speed_check = speed_source_frame(normal, selected)
    features, evidence = build_sequence(targets, history, relative, figures)
    slot_check = independent_slot_check(targets, history, evidence, features)
    exact_target_keys(targets, features)
    if len(FEATURES) != 12 or features.height != 15579 or evidence.height != 46737:
        raise E7AContractError("output denominator or feature count changed")
    features.write_parquet(output / "sequence_features.parquet")
    evidence.write_parquet(output / "sequence_evidence.parquet")
    selected_names = json.loads(H1_MANIFEST.read_text())["selected_feature_names"]
    coverage = audit_coverage(features, evidence, h1, selected_names)
    save_json(output / "coverage.json", coverage)
    save_json(
        output / "independent_validation.json",
        {"relative": relative_check, "speed": speed_check, "slots": slot_check},
    )
    save_json(
        output / "source_manifest.json",
        {
            "status": "retrospective_source_availability_unverified",
            "H1_rows": h1.height,
            "H1_races": h1["race_id"].n_unique(),
            "history_rows": history.height,
            "history_date_min": history["race_date_local"].min(),
            "history_date_max": history["race_date_local"].max(),
            "left_truncation": "DB starts " + str(history["race_date_local"].min()),
            "normal_finish_source_rows": normal.height,
            "selected_prior_entries": len(selected),
            "selected_prior_races": len(race_ids),
            "selected_section_rows": sections.height,
            "selected_section_date_max": sections["race_date"].max(),
            "date_bound_sql": "source race_date < max H1 target date AND <= 2026-05-31",
            "per_target_bound": "source race_date < each target race_date_local",
            "source_database": str(DB.relative_to(ROOT)),
            "source_database_sha256": db_before,
            "feature_names": list(FEATURES),
            "training_fit_calls": 0,
        },
    )
    after = {str(path.relative_to(ROOT)): sha(path) for path in sorted(preserved_paths())}
    db_after = sha(DB)
    if before != after or db_before != db_after:
        raise E7AContractError("sealed input or operating registry modified")
    save_json(
        output / "artifact_manifest.json",
        {
            "status": "audit_only_no_fit",
            "sealed_hashes_before": before,
            "sealed_hashes_after": after,
            "source_database_hash_before": db_before,
            "source_database_hash_after": db_after,
            "outputs": {
                str(path.relative_to(ROOT)): sha(path)
                for path in sorted(output.iterdir())
                if path.is_file() and path.name != "artifact_manifest.json"
            },
            "code_hashes": {
                "runner": sha(Path(__file__)),
                "feature_module": sha(ROOT / "src/horse_racing/analysis/confirmed_starter_e7a.py"),
            },
        },
    )
    print(output)


if __name__ == "__main__":
    main()

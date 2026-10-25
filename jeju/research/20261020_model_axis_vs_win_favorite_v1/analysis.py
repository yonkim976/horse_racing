"""Describe frozen F1_STYLE6 score-axis Top3 vs final WIN-odds minimum."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pandas as pd


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
EVAL = ROOT / "jeju/research/20261019_distance_section_relative_evaluation_v1"
SOURCE = ROOT / "jeju/research/20261019_distance_section_relative_source_v1"
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
DISTANCES = (900, 1000, 1110, 1200)
START = "2024-01-01"
END = "2026-09-19"
EXPECTED_RACES = 1503
EXPECTED_RUNNERS = 14714
CHUNK_SIZE = 500


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_study_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved != STUDY and STUDY not in resolved.parents:
        raise ValueError(f"Output path escaped study directory: {resolved}")
    return resolved


def write_csv(name: str, rows: list[dict]) -> Path:
    path = safe_study_path(STUDY / name)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")
    return path


def pct(n: int, d: int) -> float | None:
    return 100.0 * n / d if d else None


def read_predictions() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    files = {
        "baseline": EVAL / "outputs/baseline_runner_predictions.parquet",
        "candidate": EVAL / "outputs/candidate_runner_predictions.parquet",
    }
    baseline = pd.read_parquet(files["baseline"])
    candidate = pd.read_parquet(files["candidate"])
    keys = ["api_record_id", "race_id", "race_date", "year", "distance_m",
            "horse_id", "horse_number", "field_n", "y"]
    assert len(baseline) == len(candidate) == 17412
    assert baseline.api_record_id.is_unique and candidate.api_record_id.is_unique
    left = baseline[keys].sort_values("api_record_id").reset_index(drop=True)
    right = candidate[keys].sort_values("api_record_id").reset_index(drop=True)
    assert left.equals(right), "Frozen prediction variants must have identical roster and y"

    mask = (baseline.distance_m.isin(DISTANCES)
            & baseline.race_date.between(START, END, inclusive="both"))
    b = baseline.loc[mask].copy().sort_values("api_record_id").reset_index(drop=True)
    c = candidate.loc[candidate.api_record_id.isin(b.api_record_id)].copy()
    c = c.sort_values("api_record_id").reset_index(drop=True)
    assert len(b) == len(c) == EXPECTED_RUNNERS
    assert b.race_id.nunique() == c.race_id.nunique() == EXPECTED_RACES
    assert b.api_record_id.tolist() == c.api_record_id.tolist()
    assert b.y.isin([0, 1]).all() and c.y.isin([0, 1]).all()
    assert b.y.tolist() == c.y.tolist()
    assert b.apply(lambda row: int(row.race_date[:4]) == int(row.year), axis=1).all()
    assert b.score.map(math.isfinite).all() and c.score.map(math.isfinite).all()
    assert b.p_top3.map(math.isfinite).all() and c.p_top3.map(math.isfinite).all()
    assert b.p_top3.between(0, 1).all() and c.p_top3.between(0, 1).all()
    return b, c, {name: sha256(path) for name, path in files.items()}


def read_api4_rows(predictions: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    snapshot_path = SOURCE / "api4_quality_source_snapshot.parquet"
    snapshot = pd.read_parquet(
        snapshot_path, columns=["api_record_id", "api4_3_payload_sha256"]
    ).drop_duplicates("api_record_id")
    assert snapshot.api_record_id.is_unique
    snapshot_hash = snapshot.set_index("api_record_id").api4_3_payload_sha256

    wanted = predictions.api_record_id.astype("int64").tolist()
    source: dict[int, dict] = {}
    uri = DB.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=20) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        sql = """
            SELECT r.api_record_id, r.race_date, r.meet_code, r.race_number,
                   r.horse_number, r.horse_id, r.race_distance_m,
                   r.finish_position, a.payload_json, a.payload_sha256,
                   json_type(a.payload_json, '$.winOdds')
            FROM race_result_rows AS r
            JOIN api_records AS a USING (api_record_id)
            WHERE r.api_record_id IN ({placeholders})
        """
        for start in range(0, len(wanted), CHUNK_SIZE):
            batch = wanted[start:start + CHUNK_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                sql.format(placeholders=placeholders), batch
            ).fetchall()
            for row in rows:
                api_id = int(row[0])
                assert api_id not in source
                source[api_id] = {
                    "api_record_id": api_id,
                    "race_date": row[1],
                    "meet_code": row[2],
                    "race_number": row[3],
                    "horse_number": row[4],
                    "horse_id": row[5],
                    "distance_m": row[6],
                    "finish_position": row[7],
                    "payload_json": row[8],
                    "payload_sha256": row[9],
                    "win_odds_json_type": row[10],
                }
        connection.rollback()

    assert len(source) == len(wanted), f"API4 join coverage {len(source)}/{len(wanted)}"
    source_rows = []
    invalid = []
    for pred in predictions.itertuples(index=False):
        row = source[int(pred.api_record_id)]
        race_number = int(str(pred.race_id).rsplit("_", 1)[1])
        assert row["race_date"] == pred.race_date
        assert int(row["meet_code"]) == 2
        assert int(row["race_number"]) == race_number
        assert int(row["horse_number"]) == int(pred.horse_number)
        assert str(row["horse_id"]) == str(pred.horse_id)
        assert int(row["distance_m"]) == int(pred.distance_m)
        assert row["finish_position"] is not None
        assert bool(int(row["finish_position"]) <= 3) == bool(int(pred.y))
        assert row["payload_sha256"] == snapshot_hash.loc[int(pred.api_record_id)]

        payload = json.loads(row["payload_json"], parse_float=Decimal,
                             parse_int=Decimal)
        raw_odds = payload.get("winOdds")
        json_type = row["win_odds_json_type"]
        valid = (isinstance(raw_odds, Decimal) and raw_odds.is_finite()
                 and raw_odds > 0 and raw_odds != Decimal("9999.9")
                 and json_type in ("integer", "real"))
        if not valid:
            invalid.append({"race_id": pred.race_id,
                            "api_record_id": int(pred.api_record_id),
                            "json_type": json_type,
                            "raw_value": str(raw_odds)})
        source_rows.append({
            "api_record_id": int(pred.api_record_id),
            "race_id": str(pred.race_id),
            "race_date": str(pred.race_date),
            "race_number": race_number,
            "distance_m": int(pred.distance_m),
            "horse_id": str(pred.horse_id),
            "horse_number": int(pred.horse_number),
            "finish_position": int(row["finish_position"]),
            "actual_top3": bool(int(row["finish_position"]) <= 3),
            "win_odds_decimal": raw_odds if valid else None,
            "win_odds_json_type": json_type,
            "api4_payload_sha256": row["payload_sha256"],
        })

    assert not invalid, f"Invalid full-field WIN odds rows: {len(invalid)}"
    frame = pd.DataFrame(source_rows)
    assert frame.api_record_id.is_unique
    assert frame.actual_top3.sum() == int(predictions.y.sum())
    counts = Counter(frame.win_odds_json_type)
    race_sizes = frame.groupby("race_id").size()
    expected_sizes = predictions.groupby("race_id").field_n.first()
    assert race_sizes.sort_index().equals(expected_sizes.sort_index())
    return frame, {
        "joined_prediction_rows": len(frame),
        "payload_hash_matches_frozen_api4_snapshot": len(frame),
        "invalid_win_odds_rows": len(invalid),
        "win_odds_json_type_counts": dict(sorted(counts.items())),
        "races_with_complete_fullfield_prices": int(frame.race_id.nunique()),
        "field_rows_match_frozen_prediction_field_n": True,
        "y_matches_official_finish_position_top3": True,
        "min_win_odds": str(min(frame.win_odds_decimal)),
        "max_win_odds": str(max(frame.win_odds_decimal)),
        "api4_snapshot_sha256": sha256(snapshot_path),
    }


def axis_for_race(group: pd.DataFrame) -> tuple[pd.Series, int]:
    max_score = group.score.max()
    tied = group.loc[group.score.eq(max_score)].sort_values("horse_number")
    return tied.iloc[0], len(tied)


def build_records(prediction_sets: dict[str, pd.DataFrame],
                  source: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    runner_rows: list[dict] = []
    race_rows: list[dict] = []

    for model, predictions in prediction_sets.items():
        merged = predictions.merge(
            source, on=["api_record_id", "race_id", "race_date", "distance_m",
                        "horse_id", "horse_number"],
            how="left", validate="one_to_one", suffixes=("", "_source"),
        )
        assert len(merged) == len(predictions) and merged.win_odds_decimal.notna().all()
        assert (merged.y.astype(int) == merged.actual_top3.astype(int)).all()
        merged["year"] = merged.race_date.str.slice(0, 4).astype(int)
        for race_id, group in merged.groupby("race_id", sort=True):
            axis, axis_tie_count = axis_for_race(group)
            low_odds = min(group.win_odds_decimal)
            min_set = group.loc[group.win_odds_decimal.eq(low_odds)].sort_values("horse_number")
            representative = min_set.iloc[0]
            unique_favorite = min_set.iloc[0] if len(min_set) == 1 else None
            axis_id = str(axis.horse_id)
            min_ids = [str(v) for v in min_set.horse_id.tolist()]
            common = {
                "race_id": race_id,
                "race_date": str(group.race_date.iloc[0]),
                "year": int(group.year.iloc[0]),
                "distance_m": int(group.distance_m.iloc[0]),
                "model": model,
                "field_n": int(group.field_n.iloc[0]),
                "api4_runner_rows": int(len(group)),
                "all_runner_win_odds_valid": True,
                "minimum_win_odds": str(low_odds),
                "minimum_odds_runner_count": int(len(min_set)),
                "minimum_odds_tied": bool(len(min_set) > 1),
                "minimum_odds_horse_ids": ";".join(min_ids),
                "minimum_odds_horse_numbers": ";".join(map(str, min_set.horse_number.tolist())),
                "axis_horse_id": axis_id,
                "axis_horse_number": int(axis.horse_number),
                "axis_score": float(axis.score),
                "axis_exact_score_tie_count": int(axis_tie_count),
                "axis_score_tie_lower_number_rule_used": bool(axis_tie_count > 1),
                "axis_finish_position": int(axis.finish_position),
                "axis_top3": bool(axis.actual_top3),
                "axis_p_top3": float(axis.p_top3),
                "axis_is_in_minimum_odds_set": axis_id in min_ids,
                "minimum_odds_set_any_top3": bool(min_set.actual_top3.any()),
                "minimum_odds_set_top3_runner_count": int(min_set.actual_top3.sum()),
                "minimum_odds_set_mean_model_p_top3": float(min_set.p_top3.mean()),
                "lower_horse_number_minimum_odds_representative_id": str(representative.horse_id),
                "lower_horse_number_minimum_odds_representative_number": int(representative.horse_number),
                "representative_finish_position": int(representative.finish_position),
                "representative_top3": bool(representative.actual_top3),
                "representative_model_p_top3": float(representative.p_top3),
                "axis_same_as_tie_representative": bool(axis_id == str(representative.horse_id)),
            }
            if unique_favorite is None:
                common.update({
                    "unique_favorite_horse_id": "",
                    "unique_favorite_horse_number": "",
                    "unique_favorite_finish_position": "",
                    "unique_favorite_top3": "",
                    "unique_favorite_model_p_top3": "",
                    "axis_same_as_unique_favorite": "",
                })
            else:
                common.update({
                    "unique_favorite_horse_id": str(unique_favorite.horse_id),
                    "unique_favorite_horse_number": int(unique_favorite.horse_number),
                    "unique_favorite_finish_position": int(unique_favorite.finish_position),
                    "unique_favorite_top3": bool(unique_favorite.actual_top3),
                    "unique_favorite_model_p_top3": float(unique_favorite.p_top3),
                    "axis_same_as_unique_favorite": bool(axis_id == str(unique_favorite.horse_id)),
                })
            race_rows.append(common)

            max_score = group.score.max()
            top_ties = set(group.loc[group.score.eq(max_score), "api_record_id"].astype(int))
            representative_id = str(representative.horse_id)
            unique_id = str(unique_favorite.horse_id) if unique_favorite is not None else ""
            min_set_ids = set(min_ids)
            for row in group.itertuples(index=False):
                odds = row.win_odds_decimal
                runner_rows.append({
                    "race_id": race_id,
                    "race_date": str(row.race_date),
                    "year": int(row.year),
                    "distance_m": int(row.distance_m),
                    "model": model,
                    "field_n": int(row.field_n),
                    "api_record_id": int(row.api_record_id),
                    "horse_id": str(row.horse_id),
                    "horse_number": int(row.horse_number),
                    "finish_position": int(row.finish_position),
                    "actual_top3": bool(row.actual_top3),
                    "score": float(row.score),
                    "p_top3": float(row.p_top3),
                    "win_odds": str(odds),
                    "win_odds_json_type": row.win_odds_json_type,
                    "api4_payload_sha256": row.api4_payload_sha256,
                    "score_tied_at_axis": int(row.api_record_id) in top_ties,
                    "axis_exact_score_tie_count": int(axis_tie_count),
                    "model_axis_selected": str(row.horse_id) == axis_id,
                    "display_minimum_odds": str(low_odds),
                    "display_minimum_tie_count": int(len(min_set)),
                    "in_display_minimum_odds_set": str(row.horse_id) in min_set_ids,
                    "unique_favorite_selected": str(row.horse_id) == unique_id if unique_id else False,
                    "lower_number_tie_representative_selected": str(row.horse_id) == representative_id,
                })
    return race_rows, runner_rows


def slice_groups(df: pd.DataFrame):
    yield "overall", "all", df
    for year in (2024, 2025, 2026):
        yield "year", str(year), df.loc[df.year.eq(year)]
    for distance in DISTANCES:
        yield "distance_m", str(distance), df.loc[df.distance_m.eq(distance)]


def summarize(race_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    frame = pd.DataFrame(race_rows)
    summaries: list[dict] = []
    tie_summaries: list[dict] = []
    for model in ("F1_STYLE6", "F1_STYLE6_DISTANCE_SECTION_RELATIVE10"):
        model_frame = frame.loc[frame.model.eq(model)]
        for scope_name, scope_value, scope in slice_groups(model_frame):
            for cohort_name, cohort in (
                ("unique_display_minimum_primary", scope.loc[scope.minimum_odds_runner_count.eq(1)]),
                ("all_races_low_number_tie_representative_sensitivity", scope),
            ):
                n = len(cohort)
                axis_hit = int(cohort.axis_top3.sum())
                fav_col = "unique_favorite_top3" if cohort_name == "unique_display_minimum_primary" else "representative_top3"
                p_col = "unique_favorite_model_p_top3" if cohort_name == "unique_display_minimum_primary" else "representative_model_p_top3"
                same_col = "axis_same_as_unique_favorite" if cohort_name == "unique_display_minimum_primary" else "axis_same_as_tie_representative"
                valid = cohort.loc[cohort["axis_same_as_unique_favorite"].notna()] if cohort_name == "unique_display_minimum_primary" else cohort
                same = valid.loc[valid[same_col].astype(bool)]
                diff = valid.loc[~valid[same_col].astype(bool)]
                categories = {
                    "model_only_top3": (diff.axis_top3.astype(bool) & ~diff[fav_col].astype(bool)),
                    "favorite_only_top3": (~diff.axis_top3.astype(bool) & diff[fav_col].astype(bool)),
                    "both_top3": (diff.axis_top3.astype(bool) & diff[fav_col].astype(bool)),
                    "neither_top3": (~diff.axis_top3.astype(bool) & ~diff[fav_col].astype(bool)),
                }
                cat_n = {name: int(mask.sum()) for name, mask in categories.items()}
                assert sum(cat_n.values()) == len(diff)
                summaries.append({
                    "scope_dimension": scope_name,
                    "scope_value": scope_value,
                    "cohort": cohort_name,
                    "model": model,
                    "races": n,
                    "model_axis_top3_count": axis_hit,
                    "model_axis_top3_rate_pct": pct(axis_hit, n),
                    "mean_model_p_top3_at_axis_pct": 100 * cohort.axis_p_top3.mean() if n else None,
                    "favorite_top3_count": int(cohort[fav_col].astype(bool).sum()),
                    "favorite_top3_rate_pct": pct(int(cohort[fav_col].astype(bool).sum()), n),
                    "mean_model_p_top3_at_favorite_pct": 100 * cohort[p_col].astype(float).mean() if n else None,
                    "same_selected_horse_count": len(same),
                    "same_selected_horse_rate_pct": pct(len(same), n),
                    "same_horse_top3_rate_pct": pct(int(same.axis_top3.sum()), len(same)),
                    "same_horse_mean_model_p_top3_pct": 100 * same.axis_p_top3.mean() if len(same) else None,
                    "different_selected_horse_count": len(diff),
                    "different_selected_horse_rate_pct": pct(len(diff), n),
                    "different_pick_model_axis_top3_rate_pct": pct(int(diff.axis_top3.sum()), len(diff)),
                    "different_pick_favorite_top3_rate_pct": pct(int(diff[fav_col].astype(bool).sum()), len(diff)),
                    "different_pick_mean_model_p_top3_at_axis_pct": 100 * diff.axis_p_top3.mean() if len(diff) else None,
                    "different_pick_mean_model_p_top3_at_favorite_pct": 100 * diff[p_col].astype(float).mean() if len(diff) else None,
                    "different_picks_model_only_top3_count": cat_n["model_only_top3"],
                    "different_picks_model_only_top3_pct": pct(cat_n["model_only_top3"], len(diff)),
                    "different_picks_favorite_only_top3_count": cat_n["favorite_only_top3"],
                    "different_picks_favorite_only_top3_pct": pct(cat_n["favorite_only_top3"], len(diff)),
                    "different_picks_both_top3_count": cat_n["both_top3"],
                    "different_picks_both_top3_pct": pct(cat_n["both_top3"], len(diff)),
                    "different_picks_neither_top3_count": cat_n["neither_top3"],
                    "different_picks_neither_top3_pct": pct(cat_n["neither_top3"], len(diff)),
                })

            tied = scope.loc[scope.minimum_odds_runner_count.gt(1)]
            if len(tied):
                min_runner_rows = []
                for row in tied.itertuples(index=False):
                    minimum_set_size = len(row.minimum_odds_horse_ids.split(";"))
                    # Store race-weighted tied-set probability and runner-weighted hit rate.
                    min_runner_rows.append((int(row.year), int(row.distance_m), minimum_set_size,
                                            int(row.minimum_odds_set_top3_runner_count),
                                            float(row.minimum_odds_set_mean_model_p_top3)))
                tie_summaries.append({
                    "scope_dimension": scope_name,
                    "scope_value": scope_value,
                    "model": model,
                    "tied_minimum_races": len(tied),
                    "model_axis_top3_count": int(tied.axis_top3.sum()),
                    "model_axis_top3_rate_pct": pct(int(tied.axis_top3.sum()), len(tied)),
                    "axis_in_minimum_odds_set_count": int(tied.axis_is_in_minimum_odds_set.sum()),
                    "axis_in_minimum_odds_set_rate_pct": pct(int(tied.axis_is_in_minimum_odds_set.sum()), len(tied)),
                    "any_minimum_set_runner_top3_count": int(tied.minimum_odds_set_any_top3.sum()),
                    "any_minimum_set_runner_top3_rate_pct": pct(int(tied.minimum_odds_set_any_top3.sum()), len(tied)),
                    "minimum_set_runner_rows": int(sum(x[2] for x in min_runner_rows)),
                    "minimum_set_runner_top3_rate_pct": pct(sum(x[3] for x in min_runner_rows), sum(x[2] for x in min_runner_rows)),
                    "mean_model_p_top3_across_minimum_set_runners_pct": (
                        100 * sum(x[2] * x[4] for x in min_runner_rows) / sum(x[2] for x in min_runner_rows)
                    ),
                })
    return summaries, tie_summaries


def write_report(prediction_hashes: dict[str, str], source_check: dict,
                 source: pd.DataFrame, race_rows: list[dict],
                 summaries: list[dict], tie_summaries: list[dict]) -> dict:
    selected_ids = source.sort_values("api_record_id").apply(
        lambda row: f"{int(row.api_record_id)}:{row.api4_payload_sha256}\n", axis=1
    ).str.cat().encode("utf-8")
    source_fingerprint = hashlib.sha256(selected_ids).hexdigest()
    races = pd.DataFrame(race_rows)
    min_counts = races.loc[races.model.eq("F1_STYLE6")].drop_duplicates("race_id").minimum_odds_runner_count.value_counts().to_dict()
    report = {
        "status": "PASS_SOURCE_AND_ANALYSIS",
        "study": STUDY.name,
        "scope": {
            "dates": [START, END],
            "distances_m": list(DISTANCES),
            "baseline": "F1_STYLE6 (main)",
            "candidate": "F1_STYLE6_DISTANCE_SECTION_RELATIVE10 (held secondary)",
            "primary_frozen_races": EXPECTED_RACES,
            "primary_frozen_runner_rows": EXPECTED_RUNNERS,
            "main_unique_display_minimum_races": 1477,
            "tied_display_minimum_races_separate": 26,
        },
        "source": {
            "database": "jeju/data/jeju_native_core.sqlite3",
            "access": "SQLite URI mode=ro, PRAGMA query_only=ON, explicit read transaction",
            "source_table": "race_result_rows joined to api_records by api_record_id",
            "price_field": "api_records.payload_json.winOdds",
            "no_full_field_missing_or_invalid_rows": True,
            "prediction_to_api4_rows": source_check["joined_prediction_rows"],
            "payload_hash_matches_frozen_snapshot": source_check["payload_hash_matches_frozen_api4_snapshot"],
            "json_type_counts": source_check["win_odds_json_type_counts"],
            "selected_payload_id_hash_sha256": source_fingerprint,
            "api4_snapshot_sha256": source_check["api4_snapshot_sha256"],
        },
        "source_quality": source_check,
        "prediction_hashes": prediction_hashes,
        "display_minimum_price_races_by_multiplicity": {
            str(k): int(v) for k, v in sorted(min_counts.items())
        },
        "prediction_variants_use_same_races_and_labels": True,
        "main_metrics": [r for r in summaries if r["scope_dimension"] == "overall"
                         and r["cohort"] == "unique_display_minimum_primary"],
        "all_1503_tie_representative_sensitivity": [r for r in summaries
                                                    if r["scope_dimension"] == "overall"
                                                    and r["cohort"] == "all_races_low_number_tie_representative_sensitivity"],
        "tied_minimum_metrics": [r for r in tie_summaries if r["scope_dimension"] == "overall"],
        "interpretation": {
            "top3_actual_rate_is_not_win_implied_probability": True,
            "one_over_win_odds_not_used_as_top3_probability": True,
            "final_display_price_timestamp_unverified": True,
            "retrospective_description_not_purchase_strategy_validation": True,
            "model_fit_or_reprediction": False,
            "database_writes_or_external_collection": False,
        },
    }
    safe_study_path(STUDY / "REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def write_readme(report: dict) -> None:
    main = [r for r in report["main_metrics"]]
    all_rows = report["all_1503_tie_representative_sensitivity"]
    tie_rows = report["tied_minimum_metrics"]
    fmt = lambda value: "—" if value is None else f"{value:.2f}%"
    lines = [
        "# 예측 score 1위와 단승 최저표시배당마의 Top3 비교",
        "",
        "저장된 F1_STYLE6 score 1위 말과 경주 결과 원문에 기록된 단승 `winOdds` 최저 말이 Top3에 든 비율을 같은 고정 runner cohort에서 비교했다. **F1_STYLE6가 주 비교 대상**이고, `F1_STYLE6_DISTANCE_SECTION_RELATIVE10`는 보류된 비교 후보의 보조 결과다. 두 모델은 같은 경주·말 키와 label을 사용했다.",
        "",
        f"대상은 {report['scope']['primary_frozen_races']:,}경주·{report['scope']['primary_frozen_runner_rows']:,}마, 2024-01-01~2026-09-19, 900·1000·1110·1200m다. 전체 출전말별 양수 단승가격이 하나씩 확인된 뒤에만 경주 단위 최저가격을 정했다. API4 `race_result_rows`와 `api_records.payload_json.winOdds`를 `(api_record_id)`로 연결했고, payload hash는 frozen API4 source snapshot과 모두 일치했다.",
        "",
        "## 유일 최저표시배당 경주 1,477개",
        "",
        "단승 표시배당이 정확히 한 마리만 최저인 경주를 메인 단일 favorite 비교로 삼았다. 같은 표시값으로 공동 최저인 26경주는 아래에서 분리했다. 표의 실제 Top3 비율과 저장된 모델 p_top3 평균은 서로 다른 값이며, `1/단승배당`을 Top3 확률로 바꾸지 않았다.",
        "",
        "| 모델 | 경주 | score 1위 Top3 | 1위 선택 p_top3 평균 | 단승 최저마 Top3 | 최저마 p_top3 평균 | 같은 말 선택 | 같은 말 Top3 | 다른 말 선택 | 모델만 Top3 | 최저마만 Top3 | 둘 다 Top3 | 둘 다 미입상 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in main:
        lines.append(
            f"| {r['model']} | {r['races']:,} | {r['model_axis_top3_count']:,} ({fmt(r['model_axis_top3_rate_pct'])}) | {fmt(r['mean_model_p_top3_at_axis_pct'])} | {r['favorite_top3_count']:,} ({fmt(r['favorite_top3_rate_pct'])}) | {fmt(r['mean_model_p_top3_at_favorite_pct'])} | {r['same_selected_horse_count']:,} ({fmt(r['same_selected_horse_rate_pct'])}) | {fmt(r['same_horse_top3_rate_pct'])} | {r['different_selected_horse_count']:,} | {r['different_picks_model_only_top3_count']:,} ({fmt(r['different_picks_model_only_top3_pct'])}) | {r['different_picks_favorite_only_top3_count']:,} ({fmt(r['different_picks_favorite_only_top3_pct'])}) | {r['different_picks_both_top3_count']:,} ({fmt(r['different_picks_both_top3_pct'])}) | {r['different_picks_neither_top3_count']:,} ({fmt(r['different_picks_neither_top3_pct'])}) |"
        )
    lines += [
        "",
        "교차 4분할 비율의 분모는 다른 말을 고른 경주다. `summary.csv`에는 축과 favorite의 다른 선택 표본별 marginal Top3 비율, same-choice p 평균 및 2024·2025·2026 연도/거리별 같은 통계가 더 있다.",
        "",
        "## 최저표시배당 동률 26경주",
        "",
        "동률 값은 반올림된 표시배당일 수 있어 공동인기 1위로 확정하지 않고 ‘표시 최저배당 동률’로 표현했다. 아래는 동률 최저 말 집합 중 적어도 한 말이 Top3인지, 모델 축 말이 그 집합에 있는지를 별도로 보여준다.",
        "",
        "| 모델 | 동률 경주 | 축 Top3 | 축 말이 최저집합에 포함 | 최저집합 중 적어도 한 말 Top3 | 최저집합 말 단위 Top3율 | 최저집합 말 p_top3 평균 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in tie_rows:
        lines.append(
            f"| {r['model']} | {r['tied_minimum_races']:,} | {r['model_axis_top3_count']:,} ({fmt(r['model_axis_top3_rate_pct'])}) | {r['axis_in_minimum_odds_set_count']:,} ({fmt(r['axis_in_minimum_odds_set_rate_pct'])}) | {r['any_minimum_set_runner_top3_count']:,} ({fmt(r['any_minimum_set_runner_top3_rate_pct'])}) | {fmt(r['minimum_set_runner_top3_rate_pct'])} | {fmt(r['mean_model_p_top3_across_minimum_set_runners_pct'])} |"
        )
    lines += [
        "",
        "## 1,503경주 대표말 민감도",
        "",
        "동률 경주 26개는 단일 favorite가 없으므로, 보조 민감도에서는 공동 최저 말 중 낮은 마번을 기계적 대표로 정했다. 이 규칙은 동률 집합의 실제 선호 순위를 주장하지 않는다.",
        "",
        "| 모델 | 경주 | 축 Top3 | 낮은 마번 대표 Top3 | 같은 말 선택 | 다른 선택 중 모델 Top3율 | 다른 선택 중 대표 Top3율 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in all_rows:
        lines.append(
            f"| {r['model']} | {r['races']:,} | {r['model_axis_top3_count']:,} ({fmt(r['model_axis_top3_rate_pct'])}) | {r['favorite_top3_count']:,} ({fmt(r['favorite_top3_rate_pct'])}) | {r['same_selected_horse_count']:,} ({fmt(r['same_selected_horse_rate_pct'])}) | {fmt(r['different_pick_model_axis_top3_rate_pct'])} | {fmt(r['different_pick_favorite_top3_rate_pct'])} |"
        )
    lines += [
        "",
        "`selected_rows.csv`는 경주별 선택을, `runner_ledger.csv`는 모든 출전마의 말 ID·마번·공식 착순·최종 단승배당·모델 score/p_top3·score 및 배당 동률 플래그를 보존한다. `source_preflight.json`과 `source_hashes.json`은 원천 coverage·해시를, `REPORT.json`은 전체 결과 요약을 담는다.",
        "",
        "이 값은 확정된 최종 표시배당과 이미 끝난 경주 결과를 사후 결합한 기술 비교다. 배당 공개 시각을 검증할 수 없어 실제 구매 시점 전략의 성과를 검증하지 않는다. Top3 입상률은 우승 확률이 아니며, 단승 역배당률도 여기서 Top3 확률로 해석하지 않았다. 모델 재학습·재예측·결과 기반 threshold 탐색은 하지 않았다.",
        "",
        "파일 무결성은 [manifest.json](manifest.json)에 기록했다.",
        "",
    ]
    safe_study_path(STUDY / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    baseline, candidate, prediction_hashes = read_predictions()
    source, source_check = read_api4_rows(baseline)
    source_preflight = {
        "status": "PASS",
        "study": STUDY.name,
        "frozen_prediction_rows": len(baseline),
        "frozen_prediction_races": int(baseline.race_id.nunique()),
        "primary_prediction_rows": EXPECTED_RUNNERS,
        "primary_prediction_races": EXPECTED_RACES,
        "date_window": [START, END],
        "distance_m": list(DISTANCES),
        "baseline_sha256": prediction_hashes["baseline"],
        "candidate_sha256": prediction_hashes["candidate"],
        "api4_source_snapshot_sha256": source_check["api4_snapshot_sha256"],
        "source_join": "api4 race_result_rows and api_records via api_record_id; payload_json.winOdds",
        "db_mode": "SQLite URI mode=ro; PRAGMA query_only=ON; explicit read transaction",
        **source_check,
        "price_validity": "JSON integer/real, finite, positive; reject missing, zero, nonnumeric, and 9999.9; no value substitution",
    }
    safe_study_path(STUDY / "source_preflight.json").write_text(
        json.dumps(source_preflight, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    variants = {
        "F1_STYLE6": baseline,
        "F1_STYLE6_DISTANCE_SECTION_RELATIVE10": candidate,
    }
    race_rows, runner_rows = build_records(variants, source)
    summary, tie_summary = summarize(race_rows)
    write_csv("selected_rows.csv", race_rows)
    write_csv("runner_ledger.csv", runner_rows)
    odds_snapshot = source[[
        "api_record_id", "race_id", "race_date", "race_number", "distance_m",
        "horse_id", "horse_number", "finish_position", "actual_top3",
        "win_odds_decimal", "win_odds_json_type", "api4_payload_sha256",
    ]].rename(columns={"win_odds_decimal": "win_odds"})
    safe_study_path(STUDY / "win_odds_snapshot.csv")
    odds_snapshot.to_csv(STUDY / "win_odds_snapshot.csv", index=False, encoding="utf-8")
    write_csv("summary.csv", summary)
    write_csv("tie_summary.csv", tie_summary)
    source_manifest_path = SOURCE / "artifact_manifest.json"
    upstream = {
        "baseline_runner_predictions.parquet": prediction_hashes["baseline"],
        "candidate_runner_predictions.parquet": prediction_hashes["candidate"],
        "evaluation_input_lock.json": sha256(EVAL / "outputs/evaluation_input_lock.json"),
        "evaluation_FINAL_MANIFEST.json": sha256(EVAL / "outputs/FINAL_MANIFEST.json"),
        "api4_quality_source_snapshot.parquet": source_check["api4_snapshot_sha256"],
        "distance_source_artifact_manifest.json": sha256(source_manifest_path),
    }
    source_hashes = {
        "algorithm": "SHA-256",
        "upstream_files": upstream,
        "target_api4_payload_id_hash_sha256": hashlib.sha256(
            "".join(f"{int(r.api_record_id)}:{r.api4_payload_sha256}\n"
                    for r in source.sort_values("api_record_id").itertuples(index=False)).encode("utf-8")
        ).hexdigest(),
        "target_api4_payload_hash_match_count": source_check["payload_hash_matches_frozen_api4_snapshot"],
        "database_write": False,
    }
    safe_study_path(STUDY / "source_hashes.json").write_text(
        json.dumps(source_hashes, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = write_report(prediction_hashes, source_check, source, race_rows,
                          summary, tie_summary)
    write_readme(report)

    files = ["PLAN.md", "analysis.py", "source_preflight.json", "source_hashes.json",
             "REPORT.json", "README.md", "win_odds_snapshot.csv", "selected_rows.csv",
             "runner_ledger.csv", "summary.csv", "tie_summary.csv"]
    artifact_rows = {}
    for name in files:
        path = safe_study_path(STUDY / name)
        artifact_rows[name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
        if path.suffix == ".csv":
            artifact_rows[name]["data_rows"] = len(pd.read_csv(path))
    manifest = {
        "status": "PASS",
        "study": STUDY.name,
        "hash_algorithm": "SHA-256",
        "artifact_scope": "Files created within this study folder; manifest intentionally omits its own hash.",
        "artifacts": artifact_rows,
    }
    safe_study_path(STUDY / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "races": EXPECTED_RACES,
        "runner_rows": EXPECTED_RUNNERS,
        "source_check": source_check,
        "manifest_path": str(STUDY / "manifest.json"),
        "manifest_sha256": sha256(STUDY / "manifest.json"),
        "main_summary": report["main_metrics"],
        "all_races_sensitivity": report["all_1503_tie_representative_sensitivity"],
        "tied_minimum_summary": report["tied_minimum_metrics"],
    }, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

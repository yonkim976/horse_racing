#!/usr/bin/env python3
"""Validate complete runner probabilities before a database publication."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import polars as pl

TOLERANCE = 1e-6
A_COLUMNS = {
    "race_id",
    "hr_no",
    "chul_no",
    "A_slot_inclusion_probability",
    "pred_rank",
}
PUBLICATION_COLUMNS = {
    "race_id",
    "race_entry_id",
    "horse_number",
    "prob_win",
    "prob_top2",
    "prob_top3",
    "a_rank_in_race",
    "field_size",
}
THOROUGHBRED_PUBLICATION_COLUMNS = {
    "raw_a_top3_score",
    "raw_bc_top3_score",
    "raw_win_score",
}
JEJU_PUBLICATION_COLUMNS = {
    "raw_rank_score",
    "raw_order_score",
    "beta_set",
    "beta_order",
}
JEJU_COLUMNS = {
    "race_id",
    "entry_id",
    "horse_id",
    "horse_number",
    "top3_probability",
    "model_rank",
    "field_size",
    "rank_score",
    "order_score",
}


def read_frame(path: Path) -> pl.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pl.read_parquet(path)
    if suffix == ".csv":
        return pl.read_csv(path)
    raise ValueError(f"unsupported prediction format: {suffix}")


def require_columns(frame: pl.DataFrame, required: set[str]) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing columns: {', '.join(missing)}")


def validate_a(frame: pl.DataFrame) -> dict[str, object]:
    require_columns(frame, A_COLUMNS)
    selected = frame.select(sorted(A_COLUMNS))
    if selected.height == 0:
        raise ValueError("prediction payload is empty")
    if selected.null_count().select(pl.sum_horizontal(pl.all())).item() != 0:
        raise ValueError("A identity/probability columns contain null")
    duplicates = selected.select(pl.struct("race_id", "hr_no").is_duplicated().sum()).item()
    if duplicates:
        raise ValueError(f"duplicate (race_id, hr_no): {duplicates}")
    invalid = selected.filter(
        ~pl.col("A_slot_inclusion_probability").is_finite()
        | (pl.col("A_slot_inclusion_probability") < 0)
        | (pl.col("A_slot_inclusion_probability") > 1)
    ).height
    if invalid:
        raise ValueError(f"invalid A probabilities: {invalid}")

    max_sum_error = 0.0
    for key, group in selected.group_by("race_id"):
        race_id = key[0] if isinstance(key, tuple) else key
        total = float(group["A_slot_inclusion_probability"].sum())
        max_sum_error = max(max_sum_error, abs(total - min(3, group.height)))
        ranks = sorted(group["pred_rank"].cast(pl.Int64).to_list())
        if ranks != list(range(1, group.height + 1)):
            raise ValueError(f"rank permutation failed: race_id={race_id}")
    if max_sum_error > TOLERANCE:
        raise ValueError(f"A probability sum error: {max_sum_error}")
    return {
        "mode": "A",
        "races": selected["race_id"].n_unique(),
        "runner_rows": selected.height,
        "max_sum_error": max_sum_error,
    }


def validate_publication(frame: pl.DataFrame, domain: str) -> dict[str, object]:
    domain_columns = (
        THOROUGHBRED_PUBLICATION_COLUMNS
        if domain == "thoroughbred"
        else JEJU_PUBLICATION_COLUMNS
    )
    required = PUBLICATION_COLUMNS | domain_columns
    require_columns(frame, required)
    selected = frame.select(sorted(required))
    if selected.height == 0:
        raise ValueError("prediction payload is empty")
    if selected.null_count().select(pl.sum_horizontal(pl.all())).item() != 0:
        raise ValueError("publication columns contain null")
    duplicates = selected.select(
        pl.struct("race_id", "race_entry_id").is_duplicated().sum()
    ).item()
    if duplicates:
        raise ValueError(f"duplicate runner rows: {duplicates}")

    invalid = selected.filter(
        ~pl.col("prob_win").is_finite()
        | ~pl.col("prob_top2").is_finite()
        | ~pl.col("prob_top3").is_finite()
        | (pl.col("prob_win") < 0)
        | (pl.col("prob_top3") > 1)
        | (pl.col("prob_win") > pl.col("prob_top2") + TOLERANCE)
        | (pl.col("prob_top2") > pl.col("prob_top3") + TOLERANCE)
    ).height
    if invalid:
        raise ValueError(f"invalid or non-monotonic runner probabilities: {invalid}")

    max_sum_error = 0.0
    for key, group in selected.group_by("race_id"):
        race_id = key[0] if isinstance(key, tuple) else key
        if group["race_entry_id"].n_unique() != group.height:
            raise ValueError(f"duplicate race_entry_id: race_id={race_id}")
        field_sizes = group["field_size"].unique().to_list()
        if field_sizes != [group.height]:
            raise ValueError(
                f"field_size mismatch: race_id={race_id} values={field_sizes} rows={group.height}"
            )
        ranks = sorted(group["a_rank_in_race"].cast(pl.Int64).to_list())
        if ranks != list(range(1, group.height + 1)):
            raise ValueError(f"A rank permutation failed: race_id={race_id}")
        for column, target in (
            ("prob_win", 1.0),
            ("prob_top2", float(min(2, group.height))),
            ("prob_top3", float(min(3, group.height))),
        ):
            total = float(group[column].sum())
            max_sum_error = max(max_sum_error, abs(total - target))
            if not math.isclose(total, target, abs_tol=TOLERANCE):
                raise ValueError(
                    f"probability sum failed: race_id={race_id} {column}={total} target={target}"
                )
    return {
        "mode": "publication",
        "domain": domain,
        "races": selected["race_id"].n_unique(),
        "runner_rows": selected.height,
        "max_sum_error": max_sum_error,
    }


def validate_jeju(frame: pl.DataFrame) -> dict[str, object]:
    require_columns(frame, JEJU_COLUMNS)
    selected = frame.select(sorted(JEJU_COLUMNS))
    if selected.height == 0:
        raise ValueError("prediction payload is empty")
    if selected.null_count().select(pl.sum_horizontal(pl.all())).item() != 0:
        raise ValueError("Jeju identity/probability/raw-score columns contain null")
    duplicates = selected.select(
        pl.struct("race_id", "entry_id").is_duplicated().sum()
    ).item()
    if duplicates:
        raise ValueError(f"duplicate Jeju runner rows: {duplicates}")
    invalid = selected.filter(
        ~pl.col("top3_probability").is_finite()
        | ~pl.col("rank_score").is_finite()
        | ~pl.col("order_score").is_finite()
        | (pl.col("top3_probability") < 0)
        | (pl.col("top3_probability") > 1)
    ).height
    if invalid:
        raise ValueError(f"invalid Jeju probabilities/raw scores: {invalid}")

    max_sum_error = 0.0
    for key, group in selected.group_by("race_id"):
        race_id = key[0] if isinstance(key, tuple) else key
        if group["entry_id"].n_unique() != group.height:
            raise ValueError(f"duplicate entry_id: race_id={race_id}")
        if group["horse_id"].n_unique() != group.height:
            raise ValueError(f"duplicate horse_id: race_id={race_id}")
        field_sizes = group["field_size"].unique().to_list()
        if field_sizes != [group.height]:
            raise ValueError(
                f"field_size mismatch: race_id={race_id} values={field_sizes} rows={group.height}"
            )
        ranks = sorted(group["model_rank"].cast(pl.Int64).to_list())
        if ranks != list(range(1, group.height + 1)):
            raise ValueError(f"Jeju rank permutation failed: race_id={race_id}")
        total = float(group["top3_probability"].sum())
        error = abs(total - min(3, group.height))
        max_sum_error = max(max_sum_error, error)
        if error > TOLERANCE:
            raise ValueError(f"Jeju Top-3 probability sum failed: race_id={race_id} sum={total}")
    return {
        "mode": "jeju_hy_r_form",
        "races": selected["race_id"].n_unique(),
        "runner_rows": selected.height,
        "max_sum_error": max_sum_error,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--domain", choices=("thoroughbred", "jeju"), default="thoroughbred")
    parser.add_argument("--publication", action="store_true")
    args = parser.parse_args()
    frame = read_frame(args.path)
    if args.publication:
        result = validate_publication(frame, args.domain)
    elif args.domain == "jeju":
        result = validate_jeju(frame)
    else:
        result = validate_a(frame)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc

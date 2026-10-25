"""Label-free source and H1-only category checks for the jockey-ID pair study."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
OUT = STUDY / "outputs"
BASE = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
EXPECTED_H1 = {2024: 2147, 2025: 2818, 2026: 3458}
EXPECTED_H2 = {2024: 336, 2025: 311, 2026: 325}


class PreflightError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise PreflightError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"input symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    require(spec is not None and spec.loader is not None, f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def h1_rows(rows: pd.DataFrame, evaluation_year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = rows.loc[rows["year"].eq(evaluation_year - 1)].copy()
    h2 = source.loc[source["race_date"].dt.month.ge(7)].copy()
    require(not h2.empty, f"empty H2 roster for {evaluation_year}")
    first_h2 = h2["race_date"].min().date()
    cutoff = first_h2 - timedelta(days=2)
    earlier = rows.loc[rows["year"].between(2019, evaluation_year - 2)].copy()
    current = source.loc[
        source["race_date"].dt.month.le(6)
        & source["race_date"].dt.date.map(lambda date: date <= cutoff)
    ].copy()
    h1 = pd.concat([earlier, current], ignore_index=True)
    require(h1["api_record_id"].is_unique and h2["api_record_id"].is_unique,
            f"duplicate H1/H2 runner key in {evaluation_year}")
    require(h1["race_date"].max().date() <= first_h2 - timedelta(days=2),
            f"H1/H2 two-day purge failed in {evaluation_year}")
    require(int(h1["race_id"].nunique()) == EXPECTED_H1[evaluation_year],
            f"H1 race count changed in {evaluation_year}")
    require(int(h2["race_id"].nunique()) == EXPECTED_H2[evaluation_year],
            f"H2 race count changed in {evaluation_year}")
    return h1, h2


def collect() -> dict[str, Any]:
    source_helper = import_module("frozen_jockey_input_for_id_preflight", BASE / "jockey_input.py")
    source_preflight = source_helper.preflight_source()
    saved_preflight_path = checked(BASE / "outputs/SOURCE_PREFLIGHT.json")
    saved_preflight = json.loads(saved_preflight_path.read_text(encoding="utf-8"))
    require(saved_preflight == source_preflight, "existing basic source preflight changed")
    roster = source_helper.load_roster(years=tuple(range(2019, 2027)))
    starts = source_helper.load_starts(include_results=False)
    rows = source_helper.attach_event_jockey(roster, starts)
    fold_rows = {}
    source_hashes = {
        str(path.relative_to(ROOT)): sha256(checked(path))
        for path in (
            source_helper.STARTS, source_helper.STARTS_MANIFEST, source_helper.FEATURES,
            source_helper.EXPANSION / "outputs/evaluation_pair_predictions.parquet",
            BASE / "outputs/SOURCE_PREFLIGHT.json", BASE / "outputs/FIT.json",
            BASE / "outputs/APPROVAL.json", BASE / "outputs/FIT_RECEIPT.json", BASE / "outputs/evaluation_pair_predictions.parquet",
            BASE / "outputs/evaluation_race_probabilities.parquet",
            BASE / "outputs/PREDICTION_RECEIPT.json", BASE / "outputs/REPORT.json",
            BASE / "outputs/REPORT_RECEIPT.json", BASE / "ARTIFACT_MANIFEST.json",
            ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/expanded_h1_fit.json",
            ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/evaluation_pair_predictions.parquet",
            ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/HISTORICAL_SOURCE_LOCK.json",
            ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy",
        )
    }
    for year in (2024, 2025, 2026):
        h1, h2 = h1_rows(rows, year)
        vocab = tuple(sorted(h1["jockey_id"].astype(str).unique().tolist()))
        counts = h1["jockey_id"].value_counts()
        eval_rows = rows.loc[rows["year"].eq(year)]
        h2_unknown = h2.loc[~h2["jockey_id"].astype(str).isin(vocab)]
        eval_unknown = eval_rows.loc[~eval_rows["jockey_id"].astype(str).isin(vocab)]
        require(len(vocab) == 39, f"H1-only category count changed in {year}")
        require(int(counts.min()) >= 52, f"H1 minimum rider support below frozen census in {year}")
        require(h2_unknown.empty and eval_unknown.empty,
                f"unexpected heldout unknown ID in {year}; unknown handling remains zero by contract")
        h1_by_race = [race.copy() for _, race in h1.groupby("race_id", sort=True)]
        basis = import_module("pair_jockey_id_basis_for_preflight", STUDY / "pair_jockey_id_basis.py")
        moments = basis.fit_moments(h1_by_race, vocab)
        require(len(moments["degenerate_ids"]) == 0, f"degenerate H1 category scale in {year}")
        fold_rows[str(year)] = {
            "h1_rows": int(len(h1)), "h1_races": int(h1["race_id"].nunique()),
            "h1_dates": int(h1["race_date"].nunique()), "h1_first_date": h1["race_date"].min().date().isoformat(),
            "h1_last_date": h1["race_date"].max().date().isoformat(),
            "h1_vocabulary_ids": list(vocab), "h1_category_count": len(vocab),
            "h1_start_count_by_id": {str(key): int(value) for key, value in counts.sort_index().items()},
            "h1_minimum_starts_per_id": int(counts.min()), "h1_maximum_starts_per_id": int(counts.max()),
            "h2_rows": int(len(h2)), "h2_races": int(h2["race_id"].nunique()),
            "h2_unknown_id_rows": int(len(h2_unknown)), "h2_unknown_id_count": int(h2_unknown["jockey_id"].nunique()),
            "evaluation_rows": int(len(eval_rows)), "evaluation_races": int(eval_rows["race_id"].nunique()),
            "evaluation_unknown_id_rows": int(len(eval_unknown)),
            "evaluation_unknown_id_count": int(eval_unknown["jockey_id"].nunique()),
            "pi_sum": float(moments["pi"].sum()), "sigma_min": float(moments["sigma"].min()),
            "sigma_max": float(moments["sigma"].max()), "degenerate_ids": moments["degenerate_ids"],
            "h1_pairs_for_category_moments": int(moments["h1_pairs"]),
        }
    return {
        "status": "PASS", "study": STUDY.name,
        "scope": "source identity, event-ID coverage, fixed H1/H2/evaluation roster and H1-only category moments",
        "finish_labels_read": False, "performance_metrics_computed": False,
        "network_or_database_access": False,
        "source_hashes": dict(sorted(source_hashes.items())),
        "upstream_basic_source_preflight_sha256": sha256(saved_preflight_path),
        "source_scope": source_preflight["source_scope"],
        "pair_input_years_2019_2025": source_preflight["pair_input_years_2019_2025"],
        "evaluation_roster_2024_2026": source_preflight["evaluation_roster_2024_2026"],
        "category_encoding": {
            "formula": "W_r=(u_r-K*pi_r)/sigma_r; u_r=I(ID_i=r)+I(ID_j=r); K=known H1-ID count in pair",
            "vocabulary_policy": "sorted event jockey IDs observed in this fold H1 only",
            "rare_id_policy": "retain all H1 IDs; no pooling or performance-based threshold",
            "unknown_runner_policy": "all categorical basis contributions exactly zero",
            "moments": "H1 race-equal unordered-pair moments; pi=mu/2; sigma=sd(u-mu)",
        },
        "folds": fold_rows,
        "source_assumption": "cached event jockey ID is historical event snapshot; publication/change timestamp unavailable",
    }


def main() -> None:
    value = collect()
    path = OUT / "SOURCE_PREFLIGHT.json"
    require(path.resolve().is_relative_to(STUDY) and not path.is_symlink() and not path.exists(),
            "refusing to overwrite or escape source preflight output")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": value["status"], "path": str(path), "folds": value["folds"]},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()


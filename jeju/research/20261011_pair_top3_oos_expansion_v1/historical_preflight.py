"""Read-only source and cohort checks before historical STYLE6 refits."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
OUT = STUDY / "outputs"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
LINEAGE = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/style_history_lineage.parquet"
STYLE_PREPARE = ROOT / "jeju/research/20261010_style_history_ablation_v1/prepare.py"
FINISH_PREPARE = ROOT / "jeju/research/20261009_finish_history_ablation_v1/prepare.py"
BASELINE_RUN = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/run.py"
SOURCE_LOCK = OUT / "HISTORICAL_SOURCE_LOCK.json"
PREFLIGHT = OUT / "HISTORICAL_PREFLIGHT.json"
FOLDS = (2020, 2021, 2022, 2023)
EXPECTED_EXPANDED_H1 = {2024: (2147, 361), 2025: (2818, 462), 2026: (3458, 560)}
EXPECTED_OLD_H1 = {2024: (312, 47), 2025: (326, 50), 2026: (329, 50)}
EXPECTED_H2 = {2024: (336, 50), 2025: (311, 48), 2026: (325, 48)}
EXPECTED_EVAL = {2024: (637, 98), 2025: (654, 98), 2026: (488, 73)}

PINNED_EXISTING = {
    "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet": "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    "jeju/research/20261010_style_history_ablation_v1/outputs/style_history_lineage.parquet": "679501dc29cecdf82cf24946cfff3ba43728bfdfdcf69647425f823b40be86e8",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet": "360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/calibration_scores.parquet": "b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/calibration_scores.parquet": "6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/evaluation_scores.parquet": "b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/evaluation_scores.parquet": "45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet": "0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/meta.json": "15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/meta.json": "23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8",
    "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/meta.json": "e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d",
    "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy": "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
}


class PreflightError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise PreflightError(message)


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"source symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"source outside workspace: {path}")
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_once(path: Path, payload: dict) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def validate_rosters(frame: pd.DataFrame, label: str) -> dict:
    require(frame["api_record_id"].is_unique, f"duplicate runner key in {label}")
    require(not frame[["race_id", "horse_id"]].duplicated().any(), f"duplicate horse in {label}")
    results = {}
    for race_id, race in frame.groupby("race_id", sort=True):
        n = int(race["field_n"].iloc[0])
        numbers = race["horse_number"].astype(int).tolist()
        positions = race["finish_position"].astype(int).tolist()
        require(n >= 4, f"field_n below 4: {race_id}")
        require(len(race) == n and len(set(numbers)) == n, f"incomplete roster: {race_id}")
        require(sorted(positions) == list(range(1, n + 1)), f"finish ranks not 1..N: {race_id}")
        require(sum(p <= 3 for p in positions) == 3, f"Top3 label count changed: {race_id}")
    results["races"] = int(frame["race_id"].nunique())
    results["rows"] = int(len(frame))
    results["field_n_max"] = int(frame.groupby("race_id")["field_n"].first().max())
    return results


def main() -> None:
    require(not SOURCE_LOCK.exists() and not PREFLIGHT.exists(), "preflight receipts already exist")
    require(not (OUT / "HISTORICAL_FIT_APPROVAL.json").exists(), "fit approval exists before preflight")
    require(not (OUT / "HISTORICAL_REFIT_RECEIPT.json").exists(), "historical fit receipt exists before preflight")
    for fold in FOLDS:
        require(not (OUT / f"F1_STYLE6_{fold}").exists(), f"historical fold output already exists: {fold}")

    source_paths = [FEATURES, LINEAGE, STYLE_PREPARE, FINISH_PREPARE, BASELINE_RUN]
    source_hashes = {str(path.relative_to(ROOT)): sha256(checked(path)) for path in source_paths}
    for relative, expected in PINNED_EXISTING.items():
        actual = sha256(checked(ROOT / relative))
        require(actual == expected, f"frozen source hash changed: {relative}")
        source_hashes[relative] = actual

    features = pd.read_parquet(checked(FEATURES))
    required = {
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "field_n",
        "finish_position", "history_cutoff", "latest_history_date", "hist_s1f_relpos_mean5",
        "hist_s1f_relpos_n", "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
        "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
    }
    require(required.issubset(features.columns), f"missing frozen feature columns: {sorted(required-set(features.columns))}")
    require(len(features) == 52155 and features["api_record_id"].is_unique, "feature table row/key mismatch")
    dates = pd.to_datetime(features["race_date"], errors="coerce").dt.normalize()
    cutoffs = pd.to_datetime(features["history_cutoff"], errors="coerce").dt.normalize()
    latest = pd.to_datetime(features["latest_history_date"], errors="coerce").dt.normalize()
    require(dates.notna().all() and (cutoffs == dates - pd.Timedelta(days=2)).all(), "feature history cutoff is not race date T-2")
    require((latest.isna() | (latest <= cutoffs)).all(), "feature latest history exceeds T-2")

    lineage = pd.read_parquet(checked(LINEAGE), columns=["target_api_record_id", "target_cutoff", "source_race_date"])
    feature_dates = features.set_index("api_record_id")["race_date"]
    target_dates = pd.to_datetime(lineage["target_cutoff"], errors="coerce").dt.normalize()
    source_dates = pd.to_datetime(lineage["source_race_date"], errors="coerce").dt.normalize()
    target_race_dates = pd.to_datetime(lineage["target_api_record_id"].map(feature_dates), errors="coerce").dt.normalize()
    require(target_dates.notna().all() and (target_dates == target_race_dates - pd.Timedelta(days=2)).all(), "style lineage target cutoff mismatch")
    require(source_dates.notna().all() and (source_dates <= target_dates).all(), "style history source exceeds target cutoff")

    historical = features.loc[features["year"].between(2019, 2025)].copy()
    roster_summary = validate_rosters(historical, "2019-2025 historical pair source")
    all_summary = validate_rosters(features.loc[features["year"].between(2017, 2026)].copy(), "full feature table")

    cohort_summary = {}
    for year in (2024, 2025, 2026):
        year_rows = features.loc[features["year"].eq(year)].copy()
        prior_year_rows = features.loc[features["year"].eq(year - 1)].copy()
        current_year_prior = prior_year_rows.loc[pd.to_datetime(prior_year_rows["race_date"]).dt.month.le(6)]
        previous = features.loc[features["year"].between(2019, year - 2)].copy()
        h2_year = year - 1
        h2 = prior_year_rows.copy()
        h2_dates = pd.to_datetime(h2["race_date"]).dt.date
        h2 = h2.loc[pd.Series(h2_dates, index=h2.index).map(lambda d: d.month >= 7)]
        first_h2 = pd.to_datetime(h2["race_date"]).dt.date.min()
        last_h1 = first_h2 - timedelta(days=2)
        current_dates = pd.to_datetime(current_year_prior["race_date"]).dt.date
        retained = current_year_prior.loc[pd.Series(current_dates, index=current_year_prior.index).le(last_h1)]
        expanded = pd.concat([previous, retained], ignore_index=True)
        old = retained
        eval_rows = year_rows
        expanded_pair = validate_rosters(expanded, f"expanded H1 {year}")
        old_pair = validate_rosters(old, f"existing H1 subset {year}")
        h2_pair = validate_rosters(h2, f"H2 {year}")
        eval_pair = validate_rosters(eval_rows, f"evaluation {year}")
        observed = {
            "expanded_h1": (expanded_pair["races"], expanded["race_date"].nunique()),
            "old_h1": (old_pair["races"], old["race_date"].nunique()),
            "h2": (h2_pair["races"], h2["race_date"].nunique()),
            "evaluation": (eval_pair["races"], eval_rows["race_date"].nunique()),
        }
        require(observed["expanded_h1"] == EXPECTED_EXPANDED_H1[year], f"expanded H1 inventory mismatch {year}: {observed}")
        require(observed["old_h1"] == EXPECTED_OLD_H1[year], f"old H1 inventory mismatch {year}: {observed}")
        require(observed["h2"] == EXPECTED_H2[year], f"H2 inventory mismatch {year}: {observed}")
        require(observed["evaluation"] == EXPECTED_EVAL[year], f"evaluation inventory mismatch {year}: {observed}")
        cohort_summary[str(year)] = {
            "expanded_h1": expanded_pair | {"dates": int(expanded["race_date"].nunique())},
            "existing_h1": old_pair | {"dates": int(old["race_date"].nunique())},
            "h2": h2_pair | {"dates": int(h2["race_date"].nunique())},
            "evaluation": eval_pair | {"dates": int(eval_rows["race_date"].nunique())},
            "h2_first_date": first_h2.isoformat(),
            "last_h1_allowed_date": last_h1.isoformat(),
        }

    fixed_scores = {}
    for year in (2024, 2025, 2026):
        study_out = ROOT / f"jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_{year}"
        meta = json.loads(checked(study_out / "meta.json").read_text(encoding="utf-8"))
        for role in ("calibration", "evaluation"):
            path = checked(study_out / f"{role}_scores.parquet")
            score = pd.read_parquet(path)
            target_year = year - 1 if role == "calibration" else year
            target = features.loc[features["year"].eq(target_year), "api_record_id"]
            require(score.columns.tolist() == ["api_record_id", "score"], f"score schema changed: {path}")
            require(score["api_record_id"].is_unique and set(score["api_record_id"]) == set(target), f"fixed score coverage mismatch: {path}")
            require(np.isfinite(score["score"].to_numpy(dtype=float)).all(), f"nonfinite fixed scores: {path}")
            require(meta.get("refit_max") <= str(pd.to_datetime(features.loc[features["year"].eq(target_year), "race_date"]).min().date() - timedelta(days=2)), f"saved model T-2 failed: {year}/{role}")
            fixed_scores[f"{year}_{role}"] = {"rows": int(len(score)), "target_year": target_year, "refit_max": meta["refit_max"], "sha256": sha256(path)}

    lock = {
        "status": "PASS",
        "study": STUDY.name,
        "sources": source_hashes,
        "recipe_dependency_chain": [
            "20261010_style_history_ablation_v1/prepare.py",
            "20261009_finish_history_ablation_v1/prepare.py",
            "20261008_horse_profile_baseline_v1/run.py (PARAMS/SEED/CATS)",
        ],
        "historical_folds": list(FOLDS),
        "historical_scope": "raw calibration scores only; no temperatures/evaluation scores/metrics",
    }
    write_once(SOURCE_LOCK, lock)
    preflight = {
        "status": "PASS",
        "study": STUDY.name,
        "scope": "read-only source/cohort preflight; no fit, no score generation, no pair metrics",
        "historical_refit_performed": False,
        "raw_oos_scores_generated": False,
        "pair_fit_performed": False,
        "pair_performance_metrics_computed": False,
        "feature_rows": int(len(features)),
        "feature_races": int(features["race_id"].nunique()),
        "historical_2019_2025_roster_validation": roster_summary,
        "full_table_roster_validation": all_summary,
        "history_cutoff": "all feature rows equal race_date minus 2 days; latest_history_date is null or <= cutoff",
        "style_lineage": {"rows": int(len(lineage)), "target_cutoff_T2": True, "source_date_at_or_before_cutoff": True},
        "fixed_cohorts": cohort_summary,
        "fixed_score_sources": fixed_scores,
        "new_historical_scores_missing": [2019, 2020, 2021, 2022],
        "source_lock_sha256": sha256(SOURCE_LOCK),
        "historical_preflight_code_sha256": sha256(Path(__file__).resolve()),
        "historical_refit_code_sha256": sha256(STUDY / "historical_refit.py"),
        "plan_sha256": sha256(STUDY / "PLAN.md"),
    }
    write_once(PREFLIGHT, preflight)
    print(json.dumps(preflight, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

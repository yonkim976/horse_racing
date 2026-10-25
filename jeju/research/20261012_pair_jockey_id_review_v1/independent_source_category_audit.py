"""Independent, label-free source and categorical-basis review."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
REVIEW = ROOT / "jeju/research/20261012_pair_jockey_id_review_v1"
STUDY = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
STARTS = ROOT / "jeju/research/20261009_jockey_effects_v1/input01/starts.csv"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BASE_PAIRS = ROOT / "jeju/research/20261012_pair_jockey_basic_v1/outputs/evaluation_pair_predictions.parquet"
EXPECTED = {
    STARTS: "78800c5c91219d58855ce046e39ead6a87729a49c8ba0d58ca9f78765921801a",
    FEATURES: "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
    ROOT / "jeju/research/20261009_jockey_effects_v1/input01/source_manifest.json":
        "68e38ee6b2ec32040fa6a8a8fdce4039ece3f25e0869004d910c92a288f50bdc",
    ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy":
        "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
}
EXPECTED_H1 = {2024: 2147, 2025: 2818, 2026: 3458}
EXPECTED_H2 = {2024: 336, 2025: 311, 2026: 325}
EXPECTED_EVAL = {2024: 637, 2025: 654, 2026: 488}


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


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


def load_basis_module():
    path = checked(STUDY / "pair_jockey_id_basis.py")
    spec = importlib.util.spec_from_file_location("candidate_category_basis_for_independent_review", path)
    require(spec is not None and spec.loader is not None, "cannot load candidate categorical basis")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_joined_source() -> pd.DataFrame:
    features = pd.read_parquet(
        checked(FEATURES),
        columns=["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "field_n"],
        filters=[("year", ">=", 2019), ("year", "<=", 2026)],
    )
    for column in ("api_record_id", "race_id", "horse_id"):
        features[column] = features[column].astype("string")
    features["race_date"] = pd.to_datetime(features["race_date"], errors="raise").dt.normalize()
    require(features["api_record_id"].notna().all() and features["api_record_id"].is_unique,
            "feature API key is missing or duplicated")
    starts = pd.read_csv(
        checked(STARTS),
        usecols=["api_record_id", "race_id", "horse_id", "race_date", "jockey_id"],
        dtype={name: "string" for name in ("api_record_id", "race_id", "horse_id", "jockey_id")},
        low_memory=False,
    )
    starts["race_date"] = pd.to_datetime(starts["race_date"], errors="raise").dt.normalize()
    require(starts["api_record_id"].notna().all() and starts["api_record_id"].is_unique,
            "event-source API key is missing or duplicated")
    require(starts["jockey_id"].notna().all() and starts["jockey_id"].str.fullmatch(r"\d{6}").all(),
            "event-source official jockey ID is missing or malformed")
    source = starts[["api_record_id", "race_id", "horse_id", "race_date", "jockey_id"]]
    joined = features.merge(
        source, on="api_record_id", how="left", validate="one_to_one", indicator=True,
        suffixes=("_feature", "_event"),
    )
    require(joined["_merge"].eq("both").all(), "feature event ID lacks official jockey source row")
    for left, right in (
        ("race_id_feature", "race_id_event"),
        ("horse_id_feature", "horse_id_event"),
        ("race_date_feature", "race_date_event"),
    ):
        require(joined[left].eq(joined[right]).all(), f"event join mismatch: {left}")
    joined["race_id"] = joined["race_id_feature"]
    joined["horse_id"] = joined["horse_id_feature"]
    joined["race_date"] = joined["race_date_feature"]
    joined = joined.drop(columns=[
        "_merge", "race_id_feature", "race_id_event", "horse_id_feature", "horse_id_event",
        "race_date_feature", "race_date_event",
    ])
    return joined


def split_h1_h2(rows: pd.DataFrame, evaluation_year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    preceding = rows.loc[rows["year"].eq(evaluation_year - 1)].copy()
    h2 = preceding.loc[preceding["race_date"].dt.month.ge(7)].copy()
    require(not h2.empty, f"empty H2 for {evaluation_year}")
    first_h2 = h2["race_date"].min().date()
    purge_date = first_h2 - timedelta(days=2)
    earlier = rows.loc[rows["year"].between(2019, evaluation_year - 2)].copy()
    current = preceding.loc[
        preceding["race_date"].dt.month.le(6)
        & preceding["race_date"].dt.date.map(lambda day: day <= purge_date)
    ].copy()
    h1 = pd.concat([earlier, current], ignore_index=True)
    require(h1["api_record_id"].is_unique and h2["api_record_id"].is_unique,
            f"duplicate H1/H2 runner key in {evaluation_year}")
    require(h1["race_date"].max().date() <= purge_date, f"T-2 split purge fails in {evaluation_year}")
    require(h1["race_id"].nunique() == EXPECTED_H1[evaluation_year], f"H1 race count differs in {evaluation_year}")
    require(h2["race_id"].nunique() == EXPECTED_H2[evaluation_year], f"H2 race count differs in {evaluation_year}")
    return h1, h2


def independent_pair_moments(h1: pd.DataFrame, vocabulary: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    """Enumerate actual unordered pairs; no finish labels or candidate moment helper."""
    category_index = {jockey_id: index for index, jockey_id in enumerate(vocabulary)}
    per_race_means: list[np.ndarray] = []
    per_race_second_moments: list[np.ndarray] = []
    for race_id, group in h1.groupby("race_id", sort=True):
        race = group.sort_values("horse_number", kind="mergesort")
        ids = race["jockey_id"].astype(str).tolist()
        field_n = int(race["field_n"].iloc[0])
        require(len(ids) == field_n and len(set(race["horse_number"].astype(int))) == field_n,
                f"field roster mismatch in H1 race {race_id}")
        require(all(jockey_id in category_index for jockey_id in ids),
                f"H1 event ID absent from H1-only vocabulary in race {race_id}")
        pair_rows = np.zeros((field_n * (field_n - 1) // 2, len(vocabulary)), dtype=np.float64)
        pair_pos = 0
        for left, right in itertools.combinations(ids, 2):
            pair_rows[pair_pos, category_index[left]] += 1.0
            pair_rows[pair_pos, category_index[right]] += 1.0
            pair_pos += 1
        require(pair_pos == len(pair_rows), f"unordered pair enumeration mismatch in race {race_id}")
        race_mean = np.asarray([
            math.fsum(float(value) for value in pair_rows[:, column]) / len(pair_rows)
            for column in range(len(vocabulary))
        ], dtype=float)
        race_second = np.asarray([
            math.fsum(float(value) * float(value) for value in pair_rows[:, column]) / len(pair_rows)
            for column in range(len(vocabulary))
        ], dtype=float)
        per_race_means.append(race_mean)
        per_race_second_moments.append(race_second)
    mu = np.asarray([
        math.fsum(float(row[column]) for row in per_race_means) / len(per_race_means)
        for column in range(len(vocabulary))
    ], dtype=float)
    second = np.asarray([
        math.fsum(float(row[column]) for row in per_race_second_moments) / len(per_race_second_moments)
        for column in range(len(vocabulary))
    ], dtype=float)
    variance = second - mu * mu
    require(np.isfinite(variance).all() and (variance >= -1e-12).all(), "invalid enumerated H1 variance")
    sigma = np.sqrt(np.maximum(variance, 0.0))
    return mu, sigma


def source_pair_roster_check(rows: pd.DataFrame) -> dict[str, Any]:
    frame = pd.read_parquet(
        checked(BASE_PAIRS),
        columns=["race_id", "horse_i", "horse_j", "evaluation_year"],
    )
    frame["race_id"] = frame["race_id"].astype("string")
    actual: set[tuple[str, int, int]] = set()
    for row in frame.itertuples(index=False):
        left, right = int(row.horse_i), int(row.horse_j)
        require(left != right, f"self-pair in saved rolling pair roster: {row.race_id}")
        actual.add((str(row.race_id), min(left, right), max(left, right)))
    require(len(actual) == len(frame), "duplicate unordered pair in saved rolling roster")
    expected: set[tuple[str, int, int]] = set()
    eval_rows = rows.loc[rows["year"].between(2024, 2026)]
    for race_id, group in eval_rows.groupby("race_id", sort=True):
        horses = sorted(group["horse_number"].astype(int).tolist())
        require(len(horses) == int(group["field_n"].iloc[0]), f"evaluation field size mismatch: {race_id}")
        expected.update((str(race_id), left, right) for left, right in itertools.combinations(horses, 2))
    require(actual == expected, "saved rolling pair roster differs from current official-ID feature cohort")
    by_year = {
        str(year): {
            "races": int(group["race_id"].nunique()),
            "pairs": int(sum(int(field) * (int(field) - 1) // 2
                             for field in group.groupby("race_id")["field_n"].first())),
        }
        for year, group in eval_rows.groupby("year", sort=True)
    }
    return {
        "status": "PASS", "rows_read": len(frame), "unique_pairs": len(actual),
        "expected_unordered_pairs": len(expected), "exact_key_set_match": True,
        "year_counts": by_year,
    }


def semantic_unknown_check(basis, vocabulary: tuple[str, ...], pi: np.ndarray,
                           sigma: np.ndarray) -> dict[str, Any]:
    ids = tuple(vocabulary)
    theta = np.linspace(-0.4, 0.4, num=len(ids), dtype=float)
    alpha = np.asarray(basis.raw_effects(theta, pi, sigma), dtype=float)
    require(abs(math.fsum(float(pi[k] * alpha[k]) for k in range(len(ids)))) <= 1e-12,
            "known-ID raw effects are not H1 exposure-weight centered")
    unseen = "999999"
    require(unseen not in ids, "synthetic unknown ID collides with H1 vocabulary")
    for left_index, left in enumerate(ids):
        mixed = basis.pair_basis(left, unseen, ids, pi, sigma)
        expected = alpha[left_index]
        require(np.isclose(float(np.dot(mixed, theta)), expected, rtol=0.0, atol=1e-12),
                "known+unknown pair does not equal known runner effect")
        for right_index in range(left_index, len(ids)):
            right = ids[right_index]
            score = float(np.dot(basis.pair_basis(left, right, ids, pi, sigma), theta))
            require(np.isclose(score, alpha[left_index] + alpha[right_index], rtol=0.0, atol=1e-12),
                    "known pair score differs from per-ID centered-effect sum")
    zero_unknown = basis.pair_basis(unseen, unseen, ids, pi, sigma)
    require(np.array_equal(zero_unknown, np.zeros(len(ids))), "two unknown IDs do not have exact zero basis")
    reverse = basis.pair_basis(ids[0], ids[-1], ids, pi, sigma)
    reverse_order = basis.pair_basis(ids[-1], ids[0], ids, pi, sigma)
    require(np.array_equal(reverse, reverse_order), "categorical pair basis is not symmetric")
    return {
        "status": "PASS", "known_unknown_effect_check_pairs": len(ids),
        "known_known_effect_check_pairs": len(ids) * (len(ids) + 1) // 2,
        "unknown_unknown_basis_exactly_zero": True, "pair_basis_symmetric": True,
        "weighted_centered_effect_mean": math.fsum(float(pi[k] * alpha[k]) for k in range(len(ids))),
    }


def verify_frozen_21_moments() -> dict[str, Any]:
    """Read only stored standardization blocks; do not inspect stored fit metrics."""
    baseline_path = checked(
        ROOT / "jeju/research/20261012_pair_jockey_basic_v1/outputs/FIT.json"
    )
    expanded_path = checked(
        ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/expanded_h1_fit.json"
    )
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expanded = json.loads(expanded_path.read_text(encoding="utf-8"))
    checks = []
    for basic_fold, expanded_fold in zip(baseline["folds"], expanded["folds"], strict=True):
        require(basic_fold["evaluation_year"] == expanded_fold["evaluation_year"],
                "frozen moment fold years differ")
        old20 = basic_fold["old_pair_moments"]
        reference20 = expanded_fold["pair_standardization"]
        require(len(old20) == len(reference20) == 20 and old20 == reference20,
                f"frozen 20 style moments changed in {basic_fold['evaluation_year']}")
        rolling = basic_fold["new_pair_moment"]
        require(
            set(rolling) == {"mean", "scale", "degenerate", "support_weight",
                             "standardization_scope"}
            and rolling["standardization_scope"] == "H1-only race-equal pair rows, race total weight 1",
            f"saved rolling moment schema/scope changed in {basic_fold['evaluation_year']}",
        )
        checks.append({
            "evaluation_year": int(basic_fold["evaluation_year"]),
            "old20_exactly_equal_to_expanded_reference": True,
            "old20_count": len(old20),
            "saved_rolling_moment_present": True,
        })
    return {
        "status": "PASS",
        "scope": "read-only standardization blocks only; coefficient/objective/calibration fields were not inspected",
        "folds": checks,
    }


def collect() -> dict[str, Any]:
    input_hashes = {}
    for path, expected in EXPECTED.items():
        resolved = checked(path)
        actual = sha256(resolved)
        require(actual == expected, f"pinned input hash changed: {path}")
        input_hashes[str(path.relative_to(ROOT))] = {"sha256": actual, "bytes": resolved.stat().st_size}
    for path in (
        STUDY / "PLAN.md",
        STUDY / "pair_jockey_id_basis.py",
        STUDY / "source_preflight.py",
        STUDY / "outputs/SOURCE_PREFLIGHT.json",
        ROOT / "jeju/research/20261012_pair_jockey_basic_v1/outputs/FIT.json",
        ROOT / "jeju/research/20261012_pair_jockey_basic_v1/outputs/FIT_RECEIPT.json",
        BASE_PAIRS,
    ):
        resolved = checked(path)
        input_hashes[str(path.relative_to(ROOT))] = {
            "sha256": sha256(resolved), "bytes": resolved.stat().st_size,
        }
    preflight = json.loads(checked(STUDY / "outputs/SOURCE_PREFLIGHT.json").read_text(encoding="utf-8"))
    require(preflight.get("finish_labels_read") is False
            and preflight.get("performance_metrics_computed") is False
            and preflight.get("network_or_database_access") is False,
            "candidate preflight scope includes labels, metrics, or external access")
    checked_preflight_hashes = {}
    for relative, expected in preflight.get("source_hashes", {}).items():
        relative_path = Path(relative)
        require(not relative_path.is_absolute() and ".." not in relative_path.parts,
                "candidate preflight contains an unsafe source path")
        resolved = checked(ROOT / relative_path)
        actual = sha256(resolved)
        require(actual == expected, f"candidate preflight source hash changed: {relative}")
        checked_preflight_hashes[relative] = actual
    rows = load_joined_source()
    require(len(rows) == 42690, "joined 2019-2026 event cohort size changed")
    frozen_moments = verify_frozen_21_moments()
    basis = load_basis_module()
    folds: dict[str, Any] = {}
    for year in (2024, 2025, 2026):
        h1, h2 = split_h1_h2(rows, year)
        eval_rows = rows.loc[rows["year"].eq(year)].copy()
        require(eval_rows["race_id"].nunique() == EXPECTED_EVAL[year],
                f"evaluation race count changed in {year}")
        vocabulary = tuple(sorted(h1["jockey_id"].astype(str).unique().tolist()))
        h1_support = h1["jockey_id"].astype(str).value_counts()
        require(len(vocabulary) == 39 and int(h1_support.min()) >= 52,
                f"H1-only vocabulary/support changed in {year}")
        require(set(h2["jockey_id"].astype(str)).issubset(vocabulary),
                f"H2 has an unseen event jockey ID in {year}")
        require(set(eval_rows["jockey_id"].astype(str)).issubset(vocabulary),
                f"evaluation has an unseen event jockey ID in {year}")
        independent_mu, independent_sigma = independent_pair_moments(h1, vocabulary)
        h1_races = [race.copy() for _, race in h1.groupby("race_id", sort=True)]
        candidate_moments = basis.fit_moments(h1_races, vocabulary)
        candidate_mu = np.asarray(candidate_moments["mu"], dtype=float)
        candidate_sigma = np.asarray(candidate_moments["sigma"], dtype=float)
        require(np.allclose(candidate_mu, independent_mu, rtol=0.0, atol=1e-12),
                f"candidate H1 category means differ from enumerated unordered pairs in {year}")
        require(np.allclose(candidate_sigma, independent_sigma, rtol=0.0, atol=1e-12),
                f"candidate H1 category scales differ from enumerated unordered pairs in {year}")
        require(np.all(candidate_sigma > 1e-12) and not candidate_moments["degenerate_ids"],
                f"degenerate H1 ID scale in {year}")
        require(np.isclose(float(candidate_moments["pi"].sum()), 1.0, rtol=0.0, atol=1e-12),
                f"H1 exposure weights do not sum to one in {year}")
        semantic = semantic_unknown_check(
            basis, vocabulary, np.asarray(candidate_moments["pi"], dtype=float), candidate_sigma
        )
        saved = preflight["folds"][str(year)]
        require(saved["h1_vocabulary_ids"] == list(vocabulary), f"preflight H1 vocabulary differs in {year}")
        require(saved["h1_races"] == EXPECTED_H1[year]
                and saved["h2_races"] == EXPECTED_H2[year]
                and saved["evaluation_races"] == EXPECTED_EVAL[year],
                f"preflight fold counts differ in {year}")
        require(saved["h1_minimum_starts_per_id"] == int(h1_support.min())
                and saved["sigma_min"] == float(candidate_sigma.min()),
                f"preflight H1 support or scale summary differs in {year}")
        folds[str(year)] = {
            "h1_rows": int(len(h1)), "h1_races": int(h1["race_id"].nunique()),
            "h2_rows": int(len(h2)), "h2_races": int(h2["race_id"].nunique()),
            "evaluation_rows": int(len(eval_rows)), "evaluation_races": int(eval_rows["race_id"].nunique()),
            "vocabulary_count": len(vocabulary),
            "minimum_starts_per_id": int(h1_support.min()),
            "maximum_starts_per_id": int(h1_support.max()),
            "h2_unknown_rows": 0, "evaluation_unknown_rows": 0,
            "independent_vs_candidate_mu_max_abs": float(np.max(np.abs(candidate_mu - independent_mu))),
            "independent_vs_candidate_sigma_max_abs": float(np.max(np.abs(candidate_sigma - independent_sigma))),
            "pi_sum": float(candidate_moments["pi"].sum()),
            "sigma_min": float(candidate_sigma.min()), "sigma_max": float(candidate_sigma.max()),
            "degenerate_id_count": len(candidate_moments["degenerate_ids"]),
            "unknown_and_effect_coding": semantic,
        }
    pair_roster = source_pair_roster_check(rows)
    return {
        "status": "PASS",
        "study": STUDY.name,
        "scope": "independent label-free source join, frozen H1/H2/evaluation roster, H1 categorical moments, and unknown-ID semantics",
        "finish_labels_read": False,
        "performance_metrics_computed": False,
        "fit_or_optimizer_invoked": False,
        "network_or_database_access": False,
        "joined_event_rows_2019_2026": int(len(rows)),
        "source_key_join": {
            "unique_feature_api_keys": int(rows["api_record_id"].nunique()),
            "official_event_jockey_missing": int(rows["jockey_id"].isna().sum()),
            "race_horse_date_mismatches": 0,
        },
        "evaluation_pair_roster": pair_roster,
        "candidate_preflight_hashes_independently_verified": len(checked_preflight_hashes),
        "frozen_21_moment_reference_check": frozen_moments,
        "folds": folds,
        "input_hashes": dict(sorted(input_hashes.items())),
        "source_assumption": "cached event jockey ID is an historical event snapshot; publication/change timestamp is unavailable",
    }


def main() -> None:
    result = collect()
    output = REVIEW / "independent_source_category_audit.json"
    require(output.resolve().is_relative_to(REVIEW) and not output.is_symlink(),
            "refusing to escape review folder or write through a symlink")
    output.parent.mkdir(parents=True, exist_ok=True)
    result["review_script_sha256"] = sha256(checked(Path(__file__).resolve()))
    with output.open("w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "status": result["status"],
        "joined_rows": result["joined_event_rows_2019_2026"],
        "pair_roster": result["evaluation_pair_roster"],
        "fold_summaries": {
            year: {key: value for key, value in row.items()
                   if key in {"h1_races", "h2_races", "evaluation_races", "vocabulary_count",
                              "minimum_starts_per_id", "sigma_min", "degenerate_id_count",
                              "independent_vs_candidate_mu_max_abs",
                              "independent_vs_candidate_sigma_max_abs"}}
            for year, row in result["folds"].items()
        },
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

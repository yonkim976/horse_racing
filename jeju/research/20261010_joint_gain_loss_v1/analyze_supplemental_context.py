"""No-fit supplemental summaries for same-event context and lifetime distance history."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONTEXT_DIR = ROOT / "jeju/research/20261010_joint_gain_loss_context_v1"
STUDY = ROOT / "jeju/research/20261010_joint_relationship_v1"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
OUT = HERE / "outputs_supplemental"
CONTRACT_PATH = HERE / "SUPPLEMENTAL_CONTEXT_CONTRACT.json"
HISTORY_CONTRACT_PATH = HERE / "SAVED_HISTORY_EXTENSION_CONTRACT.json"
EXPECTED = {
    "jeju/research/20261010_joint_gain_loss_context_v1/runner_context.csv":
        "8dfbef38f04c52962efee8275cca48ae8f6fa14e59d7816ed50f0b4344642468",
    "jeju/research/20261010_joint_gain_loss_context_v1/CONDITION_AVAILABILITY_AUDIT.md":
        "42bbb7a31dcee14ac8b6abdb9e6bfaf1ffafafdd2af91161baa89dd4d03921ba",
    "jeju/research/20261010_joint_relationship_v1/outputs/report/runner_marginals.csv":
        "0e6a01607164a7cb54fbbb5fb445e975ea9fbadad21d4e7a842adfc915616a09",
    "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet":
        "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f",
}
CORE_LEDGER = HERE / "outputs/race_ledger_1779.csv"
CORE_RECEIPT = HERE / "outputs/analysis_receipt.json"
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20261008
BAND_ORDER = ["건조", "양호", "다습", "포화", "불량"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv_new(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, encoding="utf-8", mode="x", float_format="%.12g")


def write_json_new(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def verify_hashes() -> dict[str, str]:
    verified = {}
    for relative, expected in EXPECTED.items():
        actual = sha256(ROOT / relative)
        if actual != expected:
            raise AssertionError(f"source hash mismatch: {relative}")
        verified[relative] = actual
    return verified


def date_cluster_ci(group: pd.DataFrame) -> tuple[float, float, int]:
    by_date = [
        part.delta_hit6.to_numpy(float)
        for _, part in group.groupby("race_date", sort=True, observed=True)
    ]
    date_count = len(by_date)
    if date_count == 0:
        return float("nan"), float("nan"), 0
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = np.empty(BOOTSTRAP_DRAWS, dtype=float)
    for draw in range(BOOTSTRAP_DRAWS):
        chosen = rng.integers(0, date_count, size=date_count)
        total = 0.0
        n = 0
        for index in chosen:
            values = by_date[int(index)]
            total += float(values.sum())
            n += len(values)
        draws[draw] = total / n
    low, high = np.quantile(draws, [0.025, 0.975], method="linear")
    return float(low), float(high), date_count


def summarize_outcomes(group: pd.DataFrame, factor: str, condition: str) -> dict[str, Any]:
    n = len(group)
    low, high, date_count = date_cluster_ci(group)
    baseline_hits = int(group.baseline_hit6.sum())
    candidate_hits = int(group.candidate_hit6.sum())
    return {
        "factor": factor,
        "condition": condition,
        "races": n,
        "share_of_full_1779": n / 1779,
        "race_dates": int(group.race_date.nunique()),
        "gained": int(group.hit_class.eq("gained").sum()),
        "lost": int(group.hit_class.eq("lost").sum()),
        "net_gained_minus_lost": int(group.hit_class.eq("gained").sum() - group.hit_class.eq("lost").sum()),
        "both_hit": int(group.hit_class.eq("both_hit").sum()),
        "both_miss": int(group.hit_class.eq("both_miss").sum()),
        "baseline_hits": baseline_hits,
        "candidate_hits": candidate_hits,
        "baseline_hit_rate": baseline_hits / n if n else np.nan,
        "candidate_hit_rate": candidate_hits / n if n else np.nan,
        "candidate_minus_baseline_hit_rate": (candidate_hits - baseline_hits) / n if n else np.nan,
        "paired_date_ci95_low": low,
        "paired_date_ci95_high": high,
        "ci_dates": date_count,
        "ci_draws": BOOTSTRAP_DRAWS,
        "ci_seed": BOOTSTRAP_SEED,
    }


def vector_summary(df: pd.DataFrame, group_col: str, features: list[str], unit: str) -> pd.DataFrame:
    groups = [("all_1779", df)]
    for name in ["both_hit", "both_miss", "gained", "lost"]:
        groups.append((name, df.loc[df[group_col].eq(name)]))
    rows = []
    for group_name, part in groups:
        for feature in features:
            values = pd.to_numeric(part[feature], errors="coerce").dropna()
            rows.append({
                "outcome_group": group_name,
                "unit": unit,
                "feature": feature,
                "units": int(len(part)),
                "nonmissing_units": int(len(values)),
                "mean": float(values.mean()) if len(values) else np.nan,
                "median": float(values.median()) if len(values) else np.nan,
                "p25": float(values.quantile(.25)) if len(values) else np.nan,
                "p75": float(values.quantile(.75)) if len(values) else np.nan,
            })
    return pd.DataFrame(rows)


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"refuse to overwrite existing output directory: {OUT}")
    if not CONTRACT_PATH.is_file() or not HISTORY_CONTRACT_PATH.is_file():
        raise FileNotFoundError("supplemental contracts must exist before analysis")
    plan_hash = sha256(HERE / "SUPPLEMENTAL_CONTEXT_PLAN.md")
    contract_hash = sha256(CONTRACT_PATH)
    history_contract_hash = sha256(HISTORY_CONTRACT_PATH)
    input_hashes = verify_hashes()
    core_ledger_hash = sha256(CORE_LEDGER)
    core_receipt_hash = sha256(CORE_RECEIPT)

    context = pd.read_csv(CONTEXT_DIR / "runner_context.csv", dtype={"jockey_id": "string"})
    context = context.rename(columns={
        "race_id": "context_race_id",
        "race_date": "context_race_date",
        "evaluation_year": "context_evaluation_year",
    })
    runners = pd.read_csv(STUDY / "outputs/report/runner_marginals.csv")
    features = pd.read_parquet(STYLE / "outputs/features.parquet")
    ledger = pd.read_csv(CORE_LEDGER)
    if context.api_record_id.duplicated().any() or runners.api_record_id.duplicated().any():
        raise AssertionError("runner api_record_id must be unique")
    if features.api_record_id.duplicated().any():
        raise AssertionError("feature api_record_id must be unique")
    if len(context) != 17412 or len(runners) != 17412 or len(ledger) != 1779:
        raise AssertionError("fixed cohort row count mismatch")
    target_ids = set(runners.api_record_id)
    if target_ids != set(context.api_record_id):
        raise AssertionError("context and saved runner API keys differ")
    history_cols = [
        "api_record_id", "race_id", "race_date", "finish_position", "same_starts",
        "same_valid_times", "same_distance_last5_actual_n", "same_distance_last5_normal_n",
    ]
    target_features = features.loc[features.api_record_id.isin(target_ids), history_cols].copy()
    if len(target_features) != 17412 or set(target_features.api_record_id) != target_ids:
        raise AssertionError("feature subset does not exactly cover target runners")
    runner = (
        context.merge(
            runners[["api_record_id", "race_id", "race_date", "evaluation_year", "y_top3"]],
            on="api_record_id", how="outer", validate="one_to_one", suffixes=("_context", "_saved"),
            indicator="context_runner_join",
        )
        .merge(
            target_features, on="api_record_id", how="outer", validate="one_to_one",
            suffixes=("", "_feature"), indicator="feature_join",
        )
    )
    if not runner.context_runner_join.eq("both").all() or not runner.feature_join.eq("both").all():
        raise AssertionError("unexpected unmatched runner rows")
    parity_pairs = [
        ("context_race_id", "race_id"),
        ("context_race_id", "race_id_feature"),
        ("context_race_date", "race_date"),
        ("context_race_date", "race_date_feature"),
        ("context_evaluation_year", "evaluation_year"),
    ]
    for left, right in parity_pairs:
        if not runner[left].astype(str).equals(runner[right].astype(str)):
            raise AssertionError(f"runner key/date parity failed: {left} vs {right}")
    if not (runner.y_top3.astype(int).to_numpy() == (runner.finish_position.astype(int).to_numpy() <= 3)).all():
        raise AssertionError("saved y_top3 and saved actual finish-position labels differ")
    runner["race_id"] = runner.context_race_id
    runner["race_date"] = runner.context_race_date
    runner["evaluation_year"] = runner.context_evaluation_year
    runner = runner.drop(columns=["context_runner_join", "feature_join"])

    if set(runner.band.dropna().unique()) != set(BAND_ORDER):
        raise AssertionError("source moisture bands differ from the fixed five categories")
    if runner.band.isna().any() or runner.moisture.isna().any():
        raise AssertionError("race moisture/band missing; do not silently impute")
    for col in ["body_kg", "carried_weight_kg", "moisture"]:
        numeric = pd.to_numeric(runner[col], errors="coerce")
        if not np.isfinite(numeric.to_numpy(float)).all():
            raise AssertionError(f"non-finite context values in {col}")
        runner[col] = numeric
    if (runner.body_kg <= 0).any() or (runner.carried_weight_kg <= 0).any():
        raise AssertionError("body/burden values must be positive")
    race_constancy = runner.groupby("race_id", sort=False, observed=True).agg(
        band_n=("band", "nunique"),
        moisture_n=("moisture", "nunique"),
        date_n=("race_date", "nunique"),
        year_n=("evaluation_year", "nunique"),
    )
    if not race_constancy.eq(1).all().all():
        raise AssertionError("race-level moisture/band/date/year is not constant")

    race_outcome = ledger[[
        "race_id", "race_date", "evaluation_year", "hit_class", "baseline_hit6", "candidate_hit6", "delta_hit6",
    ]].copy()
    if race_outcome.race_id.duplicated().any() or set(race_outcome.race_id) != set(runner.race_id):
        raise AssertionError("race outcome join key mismatch")
    runner["carried_body_ratio"] = runner.carried_weight_kg / runner.body_kg
    race_vectors = runner.groupby("race_id", sort=False, observed=True).agg(
        context_race_date=("race_date", "first"),
        context_evaluation_year=("evaluation_year", "first"),
        band=("band", "first"),
        moisture=("moisture", "first"),
        runner_rows=("api_record_id", "size"),
        body_kg_mean=("body_kg", "mean"),
        body_kg_sd_population=("body_kg", lambda x: x.std(ddof=0)),
        body_kg_nonmissing=("body_kg", "count"),
        carried_weight_kg_mean=("carried_weight_kg", "mean"),
        carried_weight_kg_sd_population=("carried_weight_kg", lambda x: x.std(ddof=0)),
        carried_weight_kg_nonmissing=("carried_weight_kg", "count"),
        carried_body_ratio_mean=("carried_body_ratio", "mean"),
        carried_body_ratio_sd_population=("carried_body_ratio", lambda x: x.std(ddof=0)),
        carried_body_ratio_nonmissing=("carried_body_ratio", "count"),
        same_starts_roster_mean=("same_starts", "mean"),
        same_starts_roster_median=("same_starts", "median"),
        same_valid_times_roster_mean=("same_valid_times", "mean"),
        same_valid_times_roster_median=("same_valid_times", "median"),
        last5_actual_n_roster_mean=("same_distance_last5_actual_n", "mean"),
        last5_actual_n_roster_median=("same_distance_last5_actual_n", "median"),
        last5_normal_n_roster_mean=("same_distance_last5_normal_n", "mean"),
        last5_normal_n_roster_median=("same_distance_last5_normal_n", "median"),
    ).reset_index()
    race_vectors = race_vectors.merge(race_outcome, on="race_id", validate="one_to_one")
    if not race_vectors.context_race_date.astype(str).equals(race_vectors.race_date.astype(str)):
        raise AssertionError("race date mismatch against core ledger")
    if not race_vectors.context_evaluation_year.astype(int).equals(race_vectors.evaluation_year.astype(int)):
        raise AssertionError("evaluation year mismatch against core ledger")
    if len(race_vectors) != 1779 or race_vectors.race_id.nunique() != 1779:
        raise AssertionError("race vectors are not exactly one per fixed race")
    for name in ["body_kg", "carried_weight_kg", "carried_body_ratio"]:
        race_vectors[f"{name}_missing_share"] = 1 - race_vectors[f"{name}_nonmissing"] / race_vectors.runner_rows

    band_rows = [summarize_outcomes(race_vectors, "all", "all_1779")]
    for band in BAND_ORDER:
        band_rows.append(summarize_outcomes(race_vectors.loc[race_vectors.band.eq(band)], "moisture_band", band))
    band_table = pd.DataFrame(band_rows)
    if int(band_table.iloc[1:]["races"].sum()) != 1779:
        raise AssertionError("moisture bands do not partition the full cohort")
    if int(band_table.iloc[0]["races"]) != 1779:
        raise AssertionError("all-race moisture condition denominator is not 1779")

    race_context_features = [
        "body_kg_mean", "body_kg_sd_population", "body_kg_missing_share",
        "carried_weight_kg_mean", "carried_weight_kg_sd_population", "carried_weight_kg_missing_share",
        "carried_body_ratio_mean", "carried_body_ratio_sd_population", "carried_body_ratio_missing_share",
    ]
    context_by_outcome = vector_summary(race_vectors, "hit_class", race_context_features, "race")

    outcome_by_race = race_outcome.set_index("race_id").hit_class
    runner["hit_class"] = runner.race_id.map(outcome_by_race)
    top3 = runner.loc[runner.y_top3.eq(1)].copy()
    top3_per_race = top3.groupby("race_id", observed=True).size()
    if len(top3) != 3 * 1779 or not top3_per_race.eq(3).all():
        raise AssertionError("saved actual Top3 label is not exactly three runners per race")
    top3_84 = top3.loc[top3.hit_class.isin(["gained", "lost"])].copy()
    if len(top3_84) != 252 or top3_84.race_id.nunique() != 84:
        raise AssertionError("gained/lost Top3 diagnostic must be 3 runners x 84 races")
    top3_rows = top3_84[[
        "race_id", "race_date", "hit_class", "api_record_id", "horse_number", "finish_position",
        "body_kg", "carried_weight_kg", "carried_body_ratio", "moisture", "band",
    ]].copy()
    top3_race = top3_84.groupby(["race_id", "race_date", "hit_class"], sort=False, observed=True).agg(
        actual_top3_runner_count=("api_record_id", "size"),
        actual_top3_body_kg_mean=("body_kg", "mean"),
        actual_top3_body_kg_sd_population=("body_kg", lambda x: x.std(ddof=0)),
        actual_top3_carried_weight_kg_mean=("carried_weight_kg", "mean"),
        actual_top3_carried_weight_kg_sd_population=("carried_weight_kg", lambda x: x.std(ddof=0)),
        actual_top3_carried_body_ratio_mean=("carried_body_ratio", "mean"),
        actual_top3_carried_body_ratio_sd_population=("carried_body_ratio", lambda x: x.std(ddof=0)),
    ).reset_index()
    top3_summary = vector_summary(top3_race, "hit_class", [
        "actual_top3_body_kg_mean", "actual_top3_body_kg_sd_population",
        "actual_top3_carried_weight_kg_mean", "actual_top3_carried_weight_kg_sd_population",
        "actual_top3_carried_body_ratio_mean", "actual_top3_carried_body_ratio_sd_population",
    ], "race_with_three_actual_top3_runners")

    history_runner_summary = vector_summary(runner, "hit_class", [
        "same_starts", "same_valid_times", "same_distance_last5_actual_n", "same_distance_last5_normal_n",
    ], "runner")
    history_race_summary = vector_summary(race_vectors, "hit_class", [
        "same_starts_roster_mean", "same_starts_roster_median",
        "same_valid_times_roster_mean", "same_valid_times_roster_median",
        "last5_actual_n_roster_mean", "last5_actual_n_roster_median",
        "last5_normal_n_roster_mean", "last5_normal_n_roster_median",
    ], "race")
    history_summary = pd.concat([history_runner_summary, history_race_summary], ignore_index=True)

    OUT.mkdir(mode=0o700)
    write_csv_new(OUT / "moisture_band_condition_summary.csv", band_table)
    write_csv_new(OUT / "race_context_vectors.csv", race_vectors)
    write_csv_new(OUT / "race_context_by_outcome.csv", context_by_outcome)
    write_csv_new(OUT / "actual_top3_context_84_races.csv", top3_rows)
    write_csv_new(OUT / "actual_top3_context_summary.csv", top3_summary)
    write_csv_new(OUT / "lifetime_same_distance_support.csv", history_summary)
    output_hashes = {p.name: sha256(p) for p in sorted(OUT.glob("*.csv"))}
    receipt = {
        "status": "completed; retrospective no-fit supplemental analysis",
        "supplemental_plan_sha256": plan_hash,
        "supplemental_contract_sha256": contract_hash,
        "history_extension_contract_sha256": history_contract_hash,
        "core_race_ledger_sha256": core_ledger_hash,
        "core_analysis_receipt_sha256": core_receipt_hash,
        "input_hashes": input_hashes,
        "cohort": {
            "races": int(len(race_vectors)),
            "runners": int(len(runner)),
            "race_dates": int(race_vectors.race_date.nunique()),
            "date_min": str(race_vectors.race_date.min()),
            "date_max": str(race_vectors.race_date.max()),
            "context_runner_key_coverage": "17412/17412 exact api_record_id; race_id/date parity passed",
            "race_band_constancy": True,
            "race_moisture_constancy": True,
            "band_counts_races": {str(k): int(v) for k, v in race_vectors.band.value_counts().items()},
            "actual_top3_gained_lost_rows": int(len(top3_rows)),
            "actual_top3_gained_lost_races": int(top3_rows.race_id.nunique()),
        },
        "bootstrap": {
            "unit": "race_date", "draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED,
            "percentiles": [2.5, 97.5], "interpretation": "pointwise descriptive intervals",
        },
        "no_fit": True,
        "timing_note": (
            "Same-event body, carried weight and moisture are result-side context; source "
            "publication timing before prediction is unverified. No result-side variable "
            "is validated as a predictor."
        ),
        "excluded": [
            "per-jockey subgroup/rule exploration", "horse-number gate interpretation",
            "selected pair-lineage subset", "missing-value zero fill",
        ],
        "output_hashes": output_hashes,
    }
    write_json_new(OUT / "supplemental_receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

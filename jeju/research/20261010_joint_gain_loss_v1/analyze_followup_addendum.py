"""Correct the scoped Top3 label and produce fixed descriptive year cross-tabs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs_followup_addendum"
LEDGER_PATH = HERE / "outputs/race_ledger_1779.csv"
RACE_CONTEXT_PATH = HERE / "outputs_supplemental/race_context_vectors.csv"
TOP3_PATH = HERE / "outputs_supplemental/actual_top3_context_84_races.csv"
CONTEXT_MANIFEST_PATH = ROOT / "jeju/research/20261010_joint_gain_loss_context_v1/ARTIFACT_MANIFEST.json"
EXPECTED_INPUTS = {
    "jeju/research/20261010_joint_gain_loss_v1/outputs/race_ledger_1779.csv":
        "a32c10fe84af887ec8f258a252815b5e2303d7458a5086e6bef12f80c82f7f26",
    "jeju/research/20261010_joint_gain_loss_v1/outputs_supplemental/race_context_vectors.csv":
        "34caff2c75ccb0fd2b61fb22a4698157d02d787b123aa72d8b540b33c86bb3fd",
    "jeju/research/20261010_joint_gain_loss_v1/outputs_supplemental/actual_top3_context_84_races.csv":
        "c266cd22614fce461ce16410da417ac2fcc1682234e5e4bbe1eef079b83fffab",
    "jeju/research/20261010_joint_gain_loss_context_v1/ARTIFACT_MANIFEST.json":
        "a051458bf4b06c87b4d3a8a377c4eb06c0b6aa6f0a0c231e90b208e8d14d697f",
}
YEARS = [2024, 2025, 2026]
DISTANCES = [800, 900, 1000, 1110, 1200, 1300, 1400, 1610]
BANDS = ["건조", "양호", "다습", "포화", "불량"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_csv_new(path: Path, frame: pd.DataFrame) -> None:
    frame.to_csv(path, index=False, encoding="utf-8", mode="x", float_format="%.12g")


def write_json_new(path: Path, payload: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def condition_row(part: pd.DataFrame, stratum: str, year: int, value: Any) -> dict[str, Any]:
    n = len(part)
    baseline = int(part.baseline_hit6.sum())
    candidate = int(part.candidate_hit6.sum())
    gained = int(part.hit_class.eq("gained").sum())
    lost = int(part.hit_class.eq("lost").sum())
    return {
        "stratum": stratum,
        "evaluation_year": year,
        "year_is_partial": year == 2026,
        "condition": str(value),
        "races": n,
        "share_of_full_1779": n / 1779,
        "race_dates": int(part.race_date.nunique()),
        "support_status": "zero_support" if n == 0 else "observed",
        "gained": gained,
        "lost": lost,
        "net_gained_minus_lost": gained - lost,
        "both_hit": int(part.hit_class.eq("both_hit").sum()),
        "both_miss": int(part.hit_class.eq("both_miss").sum()),
        "baseline_hits": baseline,
        "candidate_hits": candidate,
        "baseline_hit_rate": baseline / n if n else np.nan,
        "candidate_hit_rate": candidate / n if n else np.nan,
        "candidate_minus_baseline_hit_rate": (candidate - baseline) / n if n else np.nan,
    }


def top3_summary(top3: pd.DataFrame) -> pd.DataFrame:
    if len(top3) != 252 or top3.race_id.nunique() != 84:
        raise AssertionError("expected 252 actual-top3 runners in 84 discordant races")
    if not top3.groupby("race_id", observed=True).size().eq(3).all():
        raise AssertionError("each discordant race must contribute exactly three actual finishers")
    race = top3.groupby(["race_id", "hit_class"], sort=True, observed=True).agg(
        actual_top3_runner_count=("api_record_id", "size"),
        actual_top3_body_kg_mean=("body_kg", "mean"),
        actual_top3_body_kg_sd_population=("body_kg", lambda x: x.std(ddof=0)),
        actual_top3_carried_weight_kg_mean=("carried_weight_kg", "mean"),
        actual_top3_carried_weight_kg_sd_population=("carried_weight_kg", lambda x: x.std(ddof=0)),
        actual_top3_carried_body_ratio_mean=("carried_body_ratio", "mean"),
        actual_top3_carried_body_ratio_sd_population=("carried_body_ratio", lambda x: x.std(ddof=0)),
    ).reset_index()
    features = [
        "actual_top3_body_kg_mean", "actual_top3_body_kg_sd_population",
        "actual_top3_carried_weight_kg_mean", "actual_top3_carried_weight_kg_sd_population",
        "actual_top3_carried_body_ratio_mean", "actual_top3_carried_body_ratio_sd_population",
    ]
    groups = [
        ("all_discordant_84", race),
        ("gained", race.loc[race.hit_class.eq("gained")]),
        ("lost", race.loc[race.hit_class.eq("lost")]),
    ]
    rows = []
    for group_name, part in groups:
        for feature in features:
            values = part[feature].dropna()
            rows.append({
                "scope": "gained_lost_only",
                "outcome_group": group_name,
                "unit": "race (three actual finishers collapsed within race)",
                "races": int(len(part)),
                "nonmissing_races": int(values.size),
                "actual_top3_runner_rows": int(part.actual_top3_runner_count.sum()),
                "mean": float(values.mean()) if len(values) else np.nan,
                "median": float(values.median()) if len(values) else np.nan,
                "p25": float(values.quantile(.25)) if len(values) else np.nan,
                "p75": float(values.quantile(.75)) if len(values) else np.nan,
            })
    return pd.DataFrame(rows)


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"refuse to overwrite: {OUT}")
    verified = {}
    for relative, expected in EXPECTED_INPUTS.items():
        actual = sha256(ROOT / relative)
        if actual != expected:
            raise AssertionError(f"input hash mismatch: {relative}")
        verified[relative] = actual
    plan_path = HERE / "FOLLOWUP_ADDENDUM_PLAN.md"
    contract_path = HERE / "FOLLOWUP_ADDENDUM_CONTRACT.json"
    plan_hash = sha256(plan_path)
    contract_hash = sha256(contract_path)

    ledger = pd.read_csv(LEDGER_PATH)
    context = pd.read_csv(RACE_CONTEXT_PATH)
    top3 = pd.read_csv(TOP3_PATH)
    if len(ledger) != 1779 or ledger.race_id.nunique() != 1779:
        raise AssertionError("race ledger is not exactly 1,779 unique races")
    if len(context) != 1779 or context.race_id.nunique() != 1779:
        raise AssertionError("race context is not exactly 1,779 unique races")
    if set(ledger.race_id) != set(context.race_id):
        raise AssertionError("race context and outcome race keys differ")
    race = ledger.merge(
        context[["race_id", "band", "moisture"]],
        on="race_id", how="outer", validate="one_to_one", indicator=True,
    )
    if not race._merge.eq("both").all():
        raise AssertionError("race context join is not complete")
    if not race.evaluation_year.isin(YEARS).all():
        raise AssertionError("unexpected evaluation year")
    if set(race.distance_m.unique().tolist()) != set(DISTANCES):
        raise AssertionError("unexpected exact distance levels")
    if set(race.band.unique()) != set(BANDS):
        raise AssertionError("unexpected moisture band levels")
    if int(race.hit_class.eq("gained").sum()) != 50 or int(race.hit_class.eq("lost").sum()) != 34:
        raise AssertionError("fixed discordant class totals differ from 50 gained / 34 lost")

    year_distance_rows = []
    for year in YEARS:
        for distance in DISTANCES:
            part = race.loc[race.evaluation_year.eq(year) & race.distance_m.eq(distance)]
            year_distance_rows.append(condition_row(part, "year_x_distance", year, distance))
    year_band_rows = []
    for year in YEARS:
        for band in BANDS:
            part = race.loc[race.evaluation_year.eq(year) & race.band.eq(band)]
            year_band_rows.append(condition_row(part, "year_x_moisture_band", year, band))
    year_distance = pd.DataFrame(year_distance_rows)
    year_band = pd.DataFrame(year_band_rows)
    for year in YEARS:
        expected_n = int(race.evaluation_year.eq(year).sum())
        if int(year_distance.loc[year_distance.evaluation_year.eq(year), "races"].sum()) != expected_n:
            raise AssertionError(f"year-distance cells do not partition year {year}")
        if int(year_band.loc[year_band.evaluation_year.eq(year), "races"].sum()) != expected_n:
            raise AssertionError(f"year-band cells do not partition year {year}")
    if int(year_distance.races.sum()) != 1779 or int(year_band.races.sum()) != 1779:
        raise AssertionError("cross-tabs do not partition all 1,779 races")

    corrected_top3 = top3_summary(top3)
    if set(corrected_top3.outcome_group.unique()) != {"all_discordant_84", "gained", "lost"}:
        raise AssertionError("corrected summary has an unexpected outcome scope")
    OUT.mkdir(mode=0o700)
    write_csv_new(OUT / "actual_top3_context_summary_corrected.csv", corrected_top3)
    write_csv_new(OUT / "year_distance_condition_summary.csv", year_distance)
    write_csv_new(OUT / "year_moisture_band_condition_summary.csv", year_band)
    output_hashes = {path.name: sha256(path) for path in sorted(OUT.glob("*.csv"))}
    receipt = {
        "status": "completed; retrospective reporting correction and fixed descriptive cross-tabs",
        "plan_sha256": plan_hash,
        "contract_sha256": contract_hash,
        "input_hashes": verified,
        "cohort": {
            "races": 1779,
            "race_dates": int(race.race_date.nunique()),
            "years": {str(year): int(race.evaluation_year.eq(year).sum()) for year in YEARS},
            "gained": 50,
            "lost": 34,
            "year_distance_cells": len(year_distance),
            "year_moisture_cells": len(year_band),
            "all_cross_tabs_partition_1779": True,
            "zero_support_distance_cells": int(year_distance.races.eq(0).sum()),
            "zero_support_moisture_cells": int(year_band.races.eq(0).sum()),
        },
        "correction": {
            "superseded_file": "outputs_supplemental/actual_top3_context_summary.csv",
            "superseded_sha256": "c05a11a6c8c1077fff45cc83fc711748aab491356cee3d1f48ea13ea7f2ccb79",
            "issue": "its all_1779 label incorrectly described the 84 discordant-race subset and it included empty both-hit/both-miss rows",
            "replacement_file": "outputs_followup_addendum/actual_top3_context_summary_corrected.csv",
            "replacement_scope": "all_discordant_84, gained, lost; each row is a race-level summary after collapsing three actual finishers within race",
            "original_preserved": True,
        },
        "intervals": "No confidence intervals were added to the year cross-tabs; counts/rates are descriptive.",
        "no_fit": True,
        "output_hashes": output_hashes,
    }
    write_json_new(OUT / "followup_receipt.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

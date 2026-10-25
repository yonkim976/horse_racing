"""Read-only source/key coverage audit for the 20261012 jockey pair review.

This checks existing score/source identity and roster contracts only. It does
not build model inputs, fit models, predict, or compute performance metrics.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
REVIEW = Path(__file__).resolve().parent
STARTS = ROOT / "jeju/research/20261009_jockey_effects_v1/input01/starts.csv"
STARTS_MANIFEST = ROOT / "jeju/research/20261009_jockey_effects_v1/input01/source_manifest.json"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
EXPANSION = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
PAIR_REFERENCE = EXPANSION / "evaluation_pair_predictions.parquet"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def score_path(year: int, role: str) -> tuple[Path, int, str]:
    if role == "calibration":
        provider = year + 1
        base = EXPANSION if provider <= 2023 else STYLE
    else:
        provider = year
        base = STYLE
    return base / f"F1_STYLE6_{provider}/{role}_scores.parquet", provider, role


def main() -> None:
    starts = pd.read_csv(
        STARTS,
        dtype={"api_record_id": "string", "race_id": "string", "horse_id": "string", "jockey_id": "string"},
        usecols=["api_record_id", "race_id", "race_date", "horse_id", "jockey_id", "finish_position", "result_payload_sha256"],
    )
    starts["race_date"] = pd.to_datetime(starts["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    features = pd.read_parquet(
        FEATURES,
        columns=["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "field_n", "finish_position", "history_cutoff", "latest_history_date"],
    )
    features["api_record_id"] = features["api_record_id"].astype("string")
    features["race_id"] = features["race_id"].astype("string")
    features["horse_id"] = features["horse_id"].astype("string")
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    features["history_cutoff"] = pd.to_datetime(features["history_cutoff"], errors="coerce").dt.strftime("%Y-%m-%d")
    features["latest_history_date"] = pd.to_datetime(features["latest_history_date"], errors="coerce").dt.strftime("%Y-%m-%d")

    assert len(starts) == 52_155 and starts["api_record_id"].is_unique
    assert len(features) == 52_155 and features["api_record_id"].is_unique
    assert starts["jockey_id"].notna().all() and starts["result_payload_sha256"].notna().all()
    assert starts["jockey_id"].str.fullmatch(r"[0-9]{6}").all()
    assert starts["jockey_id"].ne("000000").all()
    assert starts["horse_id"].ne("3005648").all()
    starts["race_day"] = pd.to_datetime(starts["race_date"], errors="coerce")
    identity = features[["api_record_id", "race_id", "race_date", "horse_id"]].merge(
        starts[["api_record_id", "race_id", "race_date", "horse_id", "jockey_id"]],
        on="api_record_id", how="outer", suffixes=("_feature", "_event"), indicator=True, validate="one_to_one",
    )
    assert identity["_merge"].eq("both").all()
    for key in ("race_id", "race_date", "horse_id"):
        assert identity[f"{key}_feature"].eq(identity[f"{key}_event"]).all(), f"event identity mismatch: {key}"

    dates = pd.to_datetime(features["race_date"], errors="coerce")
    cutoff = pd.to_datetime(features["history_cutoff"], errors="coerce")
    latest = pd.to_datetime(features["latest_history_date"], errors="coerce")
    assert dates.notna().all() and (cutoff == dates - pd.Timedelta(days=2)).all()
    assert (latest.isna() | (latest <= cutoff)).all()

    roster_rows = []
    for race_id, race in features.groupby("race_id", sort=True):
        n = int(race["field_n"].iloc[0])
        ranks = sorted(pd.to_numeric(race["finish_position"], errors="coerce").astype(int).tolist())
        assert len(race) == n and ranks == list(range(1, n + 1)), f"incomplete/abnormal roster: {race_id}"
        assert sum(rank <= 3 for rank in ranks) == 3, f"Top3 label count mismatch: {race_id}"
        roster_rows.append((race_id, n))

    score_roles = []
    for year in range(2019, 2026):
        score_roles.append((year, "calibration"))
    for year in range(2024, 2027):
        score_roles.append((year, "evaluation"))
    score_audit = []
    for year, role in score_roles:
        path, provider, provider_role = score_path(year, role)
        scores = pd.read_parquet(path, columns=["api_record_id"])
        scores["api_record_id"] = scores["api_record_id"].astype("string")
        expected = features.loc[features["year"].eq(year), "api_record_id"]
        assert scores["api_record_id"].is_unique
        assert len(scores) == len(expected) and set(scores["api_record_id"]) == set(expected), f"score ID coverage mismatch: {year}/{role}"
        joined = scores.merge(identity[["api_record_id", "jockey_id"]], on="api_record_id", how="left", validate="one_to_one")
        assert len(joined) == len(scores) and joined["jockey_id"].notna().all()
        score_audit.append({
            "target_year": year,
            "target_role": role,
            "provider_fold_year": provider,
            "provider_role": provider_role,
            "rows": int(len(scores)),
            "races": int(features.loc[features["year"].eq(year), "race_id"].nunique()),
            "source_to_event_id_missing": 0,
            "score_sha256": sha256(path),
        })

    # Count observable selected starts only. This does not infer actual starts
    # outside this complete-finisher source or compute the candidate rate.
    histories_by_rider = {
        rider: group["race_day"].sort_values().to_numpy(dtype="datetime64[ns]")
        for rider, group in starts.groupby("jockey_id", sort=False)
    }
    history_rows: dict[int, list[int]] = {}
    for row in identity[["api_record_id", "jockey_id"]].merge(
        features[["api_record_id", "race_date", "year"]], on="api_record_id", validate="one_to_one"
    ).itertuples(index=False):
        event_day = pd.Timestamp(row.race_date)
        cutoff_day = event_day - pd.Timedelta(days=2)
        first_day = cutoff_day - pd.Timedelta(days=364)
        history_days = histories_by_rider[row.jockey_id]
        n = int(history_days.searchsorted(cutoff_day.to_datetime64(), side="right")
                - history_days.searchsorted(first_day.to_datetime64(), side="left"))
        history_rows.setdefault(int(row.year), []).append(n)
    history_support = {
        str(year): {
            "target_rows": len(values),
            "rows_with_zero_observed_eligible_365d_starts": sum(value == 0 for value in values),
            "minimum_observed_eligible_365d_starts": min(values),
            "interpretation": "N=0 means no prior start in this selected source window; it does not prove the jockey had no actual start",
        }
        for year, values in sorted(history_rows.items())
        if 2019 <= year <= 2026
    }
    summary = {
        "status": "PASS",
        "scope": "existing source identity, score-key coverage and complete-roster audit; no new model inputs, fit, predictions or performance metrics",
        "database_or_network_access": False,
        "starts": {
            "rows": int(len(starts)),
            "api_record_id_unique": True,
            "races": int(starts["race_id"].nunique()),
            "race_dates": [str(starts["race_date"].min()), str(starts["race_date"].max())],
            "jockey_id_missing": 0,
            "jockey_id_zero": 0,
            "jockey_id_format_violations": 0,
            "result_payload_hash_missing": 0,
            "excluded_horse_3005648_rows": 0,
        },
        "feature_identity_join": {
            "rows": int(len(identity)),
            "api_record_id_one_to_one": True,
            "feature_event_race_date_horse_mismatches": 0,
            "history_cutoff_equals_race_date_minus_two_days": True,
            "latest_history_at_or_before_cutoff": True,
        },
        "complete_rosters": {
            "races": int(len(roster_rows)),
            "all_runner_counts_match_field_n": True,
            "all_finish_ranks_are_1_through_n": True,
            "all_races_have_exactly_three_top3_labels": True,
            "non_normal_or_non_finishing_runners_in_this_selected_source": "not represented; denominator is selected complete finishers",
        },
        "score_roles": score_audit,
        "rolling_365d_observed_start_support": history_support,
        "input_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in [STARTS, STARTS_MANIFEST, FEATURES, PAIR_REFERENCE]
        },
    }
    (REVIEW / "source_coverage.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

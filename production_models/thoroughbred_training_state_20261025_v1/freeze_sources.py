"""Lock source references and result-free cards for deployment replay; no DB writes."""

from pathlib import Path
import hashlib, json, sys
import torch  # noqa: F401 -- selects the macOS OpenMP runtime before research imports
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
R = ROOT / "thoroughbred/research"


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    assets = {
        "core_database": ROOT
        / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb",
        "dataset_database": ROOT / "thoroughbred/data/dataset_20260929_v1/thoroughbred.duckdb",
        "section_history": R
        / "20261009_section_style_finish_v1/outputs/history_observations.parquet",
        "role_history": R / "20261009_gate_front_late_v1/outputs/history_events.parquet",
        "profile_records": R
        / "20261008_profile_environment_ablation_v1/outputs/records_month_gate19.parquet",
    }
    (HERE / "source_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_name": "frozen_research_inputs_20261025",
                "assets": {
                    k: {
                        "path": str(p.relative_to(ROOT)),
                        "sha256": sha(p),
                        "bytes": p.stat().st_size,
                    }
                    for k, p in assets.items()
                },
                "history_end": "2026-09-20",
                "training_source_end": "2026-09-28",
                "historical_publication_times_certified": False,
                "refresh_policy": "New dated input manifests may replace data snapshots through --sources; never mutate model/calibration assets.",
            },
            indent=2,
        )
        + "\n"
    )
    sys.path.insert(0, str(R / "20261024_training_state_v1"))
    import study_common as c

    f = c.frame(2)
    selected = (f.meet.eq(1) & f.race_date.isin(pd.to_datetime(["2026-01-03", "2026-09-20"]))) | (
        f.meet.eq(3) & f.race_date.isin(pd.to_datetime(["2026-01-02", "2026-09-18"]))
    )
    part = f[selected].copy()
    cols = [
        "meet",
        "race_date",
        "race_no",
        "program_no",
        "horse_id",
        "distance_m",
        "grade_raw",
        "current_carried_weight",
        "field_size",
    ]
    # race_no is encoded in the research key, never inferred from an outcome.
    part["race_no"] = part.race_key.str.rsplit(":", n=1).str[-1].astype(int)
    part[cols].to_parquet(HERE / "fixtures/cards.parquet", index=False, compression="zstd")
    part[c.KEY + json.loads((HERE / "feature_contract.json").read_text())["features"]].to_parquet(
        HERE / "fixtures/expected_features.parquet", index=False, compression="zstd"
    )
    pp = pd.read_parquet(R / "20261024_training_state_v1/outputs/runner_probabilities.parquet")
    pp = pp[pp.variant.eq("personal_t2")].merge(part[c.KEY], on=c.KEY, validate="one_to_one")
    pp[c.KEY + ["win", "top2", "top3"]].to_parquet(
        HERE / "fixtures/expected_probabilities.parquet", index=False, compression="zstd"
    )
    (HERE / "fixtures/manifest.json").write_text(
        json.dumps(
            {
                "races": int(part.race_key.nunique()),
                "runners": len(part),
                "files": {p.name: sha(p) for p in (HERE / "fixtures").glob("*.parquet")},
                "result_columns_in_cards": False,
                "fixture_is_retrospective_not_a_new_forecast": True,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

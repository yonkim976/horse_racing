"""Independent frozen-score lineage audit; never fits or opens a database."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESEARCH = ROOT / "jeju/research"
STYLE = RESEARCH / "20261010_style_history_ablation_v1/outputs"
HIST = RESEARCH / "20261011_pair_top3_oos_expansion_v1/outputs"
PRED = RESEARCH / "20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"


def sha(p):
    with p.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    features_path = STYLE / "features.parquet"
    f = pd.read_parquet(features_path)
    assert len(f) == 52155 and f.api_record_id.is_unique
    assert not f.horse_id.astype(str).eq("3005648").any()
    cutoff = (pd.to_datetime(f.race_date) - pd.Timedelta(days=2)).dt.strftime("%Y-%m-%d")
    assert f.history_cutoff.astype(str).equals(cutoff)
    observed = f.latest_history_date.notna()
    assert f.loc[observed, "latest_history_date"].astype(str).le(cutoff[observed]).all()
    n = f.groupby("race_id").size()
    assert f.field_n.eq(f.race_id.map(n)).all()
    assert f.groupby("race_id").finish_position.apply(lambda s: sorted(s) == list(range(1, len(s) + 1))).all()
    columns = json.loads((STYLE / "F1_STYLE6_2026/meta.json").read_text())["features"]
    assert len(columns) == 30
    sources = {str(features_path.relative_to(ROOT)): sha(features_path), str(PRED.relative_to(ROOT)): sha(PRED)}
    providers = []
    all_oos = []
    for year in range(2019, 2026):
        folder = (HIST if year < 2023 else STYLE) / f"F1_STYLE6_{year + 1}"
        meta_path, score_path, model_path = folder / "meta.json", folder / "calibration_scores.parquet", folder / "top3.txt"
        m = json.loads(meta_path.read_text())
        assert m["features"] == columns and m["feature_count"] == 30
        assert sha(model_path) == m["model_sha256"]
        assert sha(score_path) == m["calibration_scores_sha256"]
        p = pd.read_parquet(score_path)
        x = f.loc[f.year.eq(year)].merge(p, on="api_record_id", how="outer", validate="one_to_one", indicator=True)
        assert x._merge.eq("both").all() and np.isfinite(x.score).all()
        assert pd.to_datetime(x.race_date).sub(pd.Timedelta(days=2)).ge(pd.Timestamp(m["refit_max"])).all()
        for path in [meta_path, score_path, model_path]:
            sources[str(path.relative_to(ROOT))] = sha(path)
        providers.append({"race_year": year, "provider_fold": year + 1, "role": "calibration_raw_score_only",
                          "rows": len(x), "races": x.race_id.nunique(), "first_date": str(x.race_date.min()),
                          "last_date": str(x.race_date.max()), "provider_refit_max": m["refit_max"],
                          "same_year_fitted_tau_allowed_as_training_input": False})
        all_oos.append(x)

    frozen = pd.read_parquet(PRED)
    assert len(frozen) == 17412 and frozen.race_id.nunique() == 1779
    eval_providers = []
    for year in [2024, 2025, 2026]:
        folder = STYLE / f"F1_STYLE6_{year}"
        mp, sp = folder / "meta.json", folder / "evaluation_scores.parquet"
        m, p = json.loads(mp.read_text()), pd.read_parquet(sp)
        assert sha(sp) == m["evaluation_scores_sha256"]
        x = frozen.loc[frozen.year.eq(year)].merge(p, on="api_record_id", suffixes=("_frozen", "_source"), validate="one_to_one", how="outer", indicator=True)
        assert x._merge.eq("both").all()
        np.testing.assert_array_equal(x.score_frozen, x.score_source)
        assert pd.to_datetime(x.race_date).sub(pd.Timedelta(days=2)).ge(pd.Timestamp(m["refit_max"])).all()
        assert pd.Timestamp(m["calibration_max"]) <= pd.Timestamp(x.race_date.min()) - pd.Timedelta(days=2)
        sources[str(mp.relative_to(ROOT))] = sha(mp)
        sources[str(sp.relative_to(ROOT))] = sha(sp)
        eval_providers.append({"year": year, "rows": len(x), "races": x.race_id.nunique(),
                               "provider_refit_max": m["refit_max"], "tau_calibration_max": m["calibration_max"]})
    historical = pd.concat(all_oos, ignore_index=True)
    training_counts = []
    for year in [2024, 2025, 2026]:
        prior = historical.loc[historical.year.lt(year)]
        first_eval = pd.Timestamp(frozen.loc[frozen.year.eq(year), "race_date"].min())
        assert pd.Timestamp(prior.race_date.max()) <= first_eval - pd.Timedelta(days=2)
        training_counts.append({"evaluation_year": year, "available_training_races": prior.race_id.nunique(),
                                "available_training_runners": len(prior), "last_training_date": str(prior.race_date.max())})
    result = {"passed": True, "features_rows": len(f), "feature_races": f.race_id.nunique(), "inputs": columns,
              "historical_oos_providers": providers, "frozen_evaluation_providers": eval_providers,
              "available_full_prior_year_training": training_counts, "source_hashes": sources,
              "frozen_primary_races": frozen.loc[frozen.distance_m.isin([900, 1000, 1110, 1200]), "race_id"].nunique(),
              "no_favorite_or_odds_columns": not any("odds" in c.lower() or "favorite" in c.lower() for c in frozen.columns),
              "database_opened": False, "models_fitted": 0,
              "limitations": ["T-2 event-date cutoff is not a verified historical publication timestamp.",
                              "2019-2025 calibration raw-score providers differ from same-year evaluation providers.",
                              "Historical fitted tau cannot be reused as a same-year training feature.",
                              "2024-2026 evaluation is repeatedly examined development data."]}
    with (HERE / "ROOT_SOURCE_AUDIT.json").open("x") as out:
        json.dump(result, out, indent=2, ensure_ascii=False)
    print(json.dumps({"passed": True, "historical_providers": providers, "training_counts": training_counts,
                      "source_hashes": len(sources)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

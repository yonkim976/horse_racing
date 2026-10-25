"""Root's independent implementation of the predeclared 11-column selector."""
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.special import expit

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / "jeju/research"
STYLE = RESEARCH / "20261010_style_history_ablation_v1/outputs"
HIST = RESEARCH / "20261011_pair_top3_oos_expansion_v1/outputs"
FEATURE_NAMES = [
    "score_rank", "score_z", "log1p_observed_starts", "log1p_days_since_start", "days_since_start_missing",
    "log1p_same_starts", "log1p_same_valid_times", "log1p_days_since_same", "days_since_same_missing",
    "mean5_rank_fraction", "mean5_rank_fraction_missing",
]


def rows_from_scores(features, scores):
    assert scores.api_record_id.is_unique
    x = scores[["api_record_id", "score"]].merge(features, on="api_record_id", validate="one_to_one")
    assert len(x) == len(scores)
    x = x.sort_values(["race_id", "score", "horse_number"], ascending=[True, False, True], kind="stable").reset_index(drop=True)
    assert np.isfinite(x.score).all()
    x["score_rank"] = x.groupby("race_id").cumcount() + 1
    mean = x.groupby("race_id").score.transform("mean")
    sd = x.groupby("race_id").score.transform(lambda s: s.std(ddof=0))
    x["score_z"] = (x.score - mean) / sd.where(sd.gt(0), 1.0)
    for name in ["observed_starts", "same_starts", "same_valid_times"]:
        assert x[name].notna().all() and x[name].ge(0).all()
        x[f"log1p_{name}"] = np.log1p(x[name].astype(float))
    for name in ["days_since_start", "days_since_same"]:
        assert x[name].dropna().ge(0).all()
        x[f"{name}_missing"] = x[name].isna().astype(float)
        x[f"log1p_{name}"] = np.log1p(x[name].fillna(0).astype(float))
    x["mean5_rank_fraction_missing"] = x.mean5_rank_fraction.isna().astype(float)
    x["mean5_rank_fraction"] = x.mean5_rank_fraction.fillna(0).astype(float)
    x["target_top3"] = x.finish_position.le(3).astype(int)
    out = x.loc[x.score_rank.le(3)].reset_index(drop=True)
    assert out.groupby("race_id").size().eq(3).all()
    assert np.isfinite(out[FEATURE_NAMES]).all().all()
    return out


def load_training_rows():
    features = pd.read_parquet(STYLE / "features.parquet")
    frames = []
    for year in range(2019, 2026):
        folder = (HIST if year < 2023 else STYLE) / f"F1_STYLE6_{year + 1}"
        scores = pd.read_parquet(folder / "calibration_scores.parquet")
        assert features.loc[features.api_record_id.isin(scores.api_record_id), "year"].eq(year).all()
        frame = rows_from_scores(features, scores)
        frame["provider_fold"] = year + 1
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def pairwise_objective(beta, frame, mean, scale):
    """Each mixed-label race contributes one mean positive-v-negative loss."""
    z = (frame[FEATURE_NAMES].to_numpy(dtype=float) - np.asarray(mean)) / np.asarray(scale)
    numerator = 0.0
    gradient = np.zeros(len(FEATURE_NAMES))
    race_n = 0
    pair_n = 0
    # Positions use a fresh index, independent of caller's retained row indices.
    local = frame[["race_id", "target_top3"]].reset_index(drop=True)
    for _, g in local.groupby("race_id", sort=True):
        positive = g.index[g.target_top3.eq(1)].to_numpy()
        negative = g.index[g.target_top3.eq(0)].to_numpy()
        if not len(positive) or not len(negative):
            continue
        dz = (z[positive, None, :] - z[None, negative, :]).reshape(-1, len(FEATURE_NAMES))
        logits = dz @ beta
        numerator += float(np.logaddexp(0, -logits).mean())
        gradient -= (expit(-logits)[:, None] * dz).mean(axis=0)
        race_n += 1
        pair_n += len(dz)
    assert race_n > 0 and pair_n == race_n * 2
    return (numerator / race_n + .5 * float(beta @ beta), gradient / race_n + beta, race_n, pair_n)


def select(frame, beta, mean, scale):
    out = frame.copy()
    z = (out[FEATURE_NAMES].to_numpy(dtype=float) - np.asarray(mean)) / np.asarray(scale)
    out["root_utility"] = z @ beta
    assert np.isfinite(out.root_utility).all()
    choices = out.sort_values(["race_id", "root_utility", "score", "horse_number"], ascending=[True, False, False, True], kind="stable").groupby("race_id", sort=True).head(1)
    return out, choices

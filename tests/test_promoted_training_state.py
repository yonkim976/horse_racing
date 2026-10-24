"""Operational contract regressions for the explicitly promoted 136-feature model."""

from pathlib import Path
import sys
import torch  # noqa: F401 -- selects the macOS OpenMP runtime before LightGBM
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "production_models/thoroughbred_training_state_20261025_v1"
sys.path.insert(0, str(BUNDLE))
import features
import feature_math
import inference


def card():
    f = pd.read_parquet(BUNDLE / "fixtures/cards.parquet")
    return f[
        f.meet.eq(1) & f.race_date.eq(f.loc[f.meet.eq(1), "race_date"].min()) & f.race_no.eq(1)
    ].copy()


def test_incomplete_roster_is_rejected():
    f = card()
    assert len(f) >= 3
    with pytest.raises(ValueError, match="incomplete"):
        features.validate_card(f.iloc[:-1])


def test_result_and_odds_columns_are_rejected():
    for column in ["outcome", "win_odds", "finish_order"]:
        with pytest.raises(ValueError, match="Result/odds"):
            features.validate_card(card().assign(**{column: 1}))


def test_program_numbers_are_unique_within_each_race():
    f = card()
    f.iloc[1, f.columns.get_loc("program_no")] = f.iloc[0].program_no
    with pytest.raises(ValueError, match="Duplicate"):
        features.validate_card(f)


def test_race_numbers_cannot_be_silently_truncated():
    with pytest.raises(ValueError, match="positive integers"):
        features.validate_card(card().assign(race_no=1.5))


def test_scratches_rebuild_the_field_instead_of_dropping_scored_rows():
    f = card()
    f["scratched"] = False
    f.iloc[0, f.columns.get_loc("scratched")] = True
    out = features.validate_card(f)
    assert len(out) == len(f) - 1 and out.field_size.eq(len(out)).all()
    assert f.iloc[0].horse_id not in set(out.horse_id)


def test_unverified_venue_or_year_cannot_use_these_weights():
    with pytest.raises(ValueError, match="Seoul/Busan"):
        features.validate_card(card().assign(meet=2))
    with pytest.raises(ValueError, match="2026"):
        features.validate_card(card().assign(race_date="2027-01-02"))


def test_future_history_is_not_selected():
    f = features.validate_card(card())
    f = f.iloc[:1].copy()
    cutoff = f.cutoff_date.iloc[0]
    h = pd.DataFrame(
        {"horse_id": [f.horse_id.iloc[0]] * 2, "race_date": [cutoff, cutoff + pd.Timedelta(days=1)]}
    )
    ix = feature_math.slots(f, h)
    assert ix[0, 0] == 0 and np.all(ix[0, 1:] == -1)


def test_locked_models_reproduce_saved_runner_probabilities_and_explanations():
    f = pd.read_parquet(BUNDLE / "verification/rebuilt_features.parquet")
    p, explanations, _, checks = inference.predict(f)
    expected = pd.read_parquet(BUNDLE / "fixtures/expected_probabilities.parquet")
    aligned = expected.merge(p, on=inference.KEY, validate="one_to_one")
    for old, new in [("win", "prob_win"), ("top2", "prob_top2"), ("top3", "prob_top3")]:
        np.testing.assert_allclose(aligned[old], aligned[new], rtol=0, atol=1e-12)
    assert len(explanations) == len(p) * 6 and checks["max_shap_additivity_error"] < 1e-6
    table = pd.DataFrame(explanations)
    assert table.groupby(["race_key", "horse_id", "contribution_direction"]).size().eq(3).all()
    assert table[table.contribution_direction.eq("positive")].contribution_value.gt(0).all()
    assert table[table.contribution_direction.eq("negative")].contribution_value.lt(0).all()


def test_missing_feature_column_fails_instead_of_using_legacy_weights():
    f = pd.read_parquet(BUNDLE / "verification/rebuilt_features.parquet")
    with pytest.raises(ValueError, match="Missing promoted"):
        inference.predict(f.drop(columns="train_minutes14_delta_self3"))

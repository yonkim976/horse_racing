from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from thoroughbred import cli


def test_registry_change_after_resolution_is_rejected(monkeypatch, tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text('{"same_profile_but_changed_content": true}')
    monkeypatch.setattr(cli, "REGISTRY_PATH", registry)
    with pytest.raises(RuntimeError, match="registry changed"):
        cli.load_registered_models({"registry_sha256": "0" * 64})


def test_predict_frame_rejects_partial_cards() -> None:
    frame = pd.read_parquet(cli.REPLAY_INPUT).drop(index=0).reset_index(drop=True)
    with pytest.raises(ValueError, match="field_size_full_card"):
        cli.validate_frame(frame, historical_replay=True)


def test_predict_frame_rejects_missing_required_features() -> None:
    frame = pd.DataFrame({"some_other_column": [1]})
    bundle = SimpleNamespace(categorical_features=("horse_type",), numeric_features=("speed",))
    with pytest.raises(ValueError, match="horse_type.*speed"):
        cli._required_feature_columns(frame, (bundle,))


def test_unknown_and_unvalidated_venues_are_distinguished() -> None:
    frame = pd.read_parquet(cli.REPLAY_INPUT)
    assert cli._validate_venues(frame, allow_unvalidated=True) == ["YEONGCHEON"]
    with pytest.raises(ValueError, match="not validated"):
        cli._validate_venues(frame, allow_unvalidated=False)
    frame["venue_code"] = "UNKNOWN"
    with pytest.raises(ValueError, match="unknown Thoroughbred venue"):
        cli._validate_venues(frame, allow_unvalidated=True)


def test_output_path_must_be_fresh_and_under_predictions(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions"
    output = predictions / "run-1"
    assert cli._validate_output_path(output, predictions) == output.resolve()
    output.mkdir(parents=True)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        cli._validate_output_path(output, predictions)
    with pytest.raises(ValueError, match="must be under"):
        cli._validate_output_path(tmp_path / "outside", predictions)


def test_registered_prediction_exactly_replays_preserved_fixture() -> None:
    frame = cli._load_verified_replay_fixture()
    resolution = cli.resolve_production_model()
    profile, a_bundle, bc_bundle, win_bundle = cli.load_registered_models(resolution)
    a_frame, combo_frame, scores, max_error = cli.predict_frame(
        frame,
        profile,
        a_bundle,
        bc_bundle,
        win_bundle,
        historical_replay=True,
        allow_unvalidated_venues=True,
    )

    assert len(a_frame) == 294
    assert len(combo_frame) == 540
    assert max_error <= 1e-10
    comparison = cli._verify_exact_replay(a_frame, combo_frame, scores)
    assert comparison == {
        "runner_rows": 294,
        "B_C_rows": 540,
        "max_probability_error": 0.0,
        "raw_scores_exact": True,
    }
    assert {"p_win", "p_top2", "p_top3", "p_exact_2", "p_exact_3"} <= set(a_frame.columns)
    assert {"raw_score_A", "raw_score_BC", "raw_score_WIN_ORDER"} <= set(a_frame.columns)
    assert set(combo_frame["combination_semantics"]) == {
        "unordered_top3_set",
        "ordered_1_2_3",
    }

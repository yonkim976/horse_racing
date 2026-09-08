import random
from pathlib import Path

import pytest

from horse_racing.analysis.experiments import (
    DuplicateRunError,
    ModelRun,
    compare_runs,
    get_run,
    hash_feature_names,
    load_runs,
    metric_delta,
    record_run,
    set_global_seed,
    sort_runs,
)


def _sample_run(**overrides: object) -> ModelRun:
    payload: dict[str, object] = {
        "dataset_version": "v1",
        "dataset_manifest": {"rows": 1000, "source": "test"},
        "feature_names": ["rating", "win_odds"],
        "model_type": "lightgbm",
        "hyperparameters": {"n_estimators": 200, "learning_rate": 0.05},
        "seed": 42,
        "train_period": "2025-01-03~2026-02-28",
        "valid_period": "2026-03-01~2026-05-31",
        "test_period": "2026-06-01~2026-08-21",
        "metrics": {"log_loss": 0.62, "auc": 0.71},
        "notes": "baseline",
    }
    payload.update(overrides)
    return ModelRun.model_validate(payload)


def test_record_and_reload_roundtrip(tmp_path: Path) -> None:
    ledger = tmp_path / "experiments" / "model_runs.jsonl"
    run = _sample_run(run_id="run-roundtrip")

    record_run(run, ledger_path=ledger)

    loaded = load_runs(ledger_path=ledger)
    assert ledger.is_file()
    assert len(loaded) == 1
    assert loaded[0] == run
    assert get_run("run-roundtrip", ledger_path=ledger) == run
    assert loaded[0].feature_hash == hash_feature_names(["rating", "win_odds"])
    assert len(loaded[0].feature_hash) == 64


def test_missing_metric_roundtrips_as_json_null(tmp_path: Path) -> None:
    ledger = tmp_path / "model_runs.jsonl"
    run = _sample_run(run_id="no-bets", metrics={"roi": None})

    record_run(run, ledger_path=ledger)
    loaded = load_runs(ledger_path=ledger)

    assert loaded[0].metrics["roi"] is None
    assert metric_delta(loaded[0], _sample_run(metrics={"roi": 0.1}), "roi") is None


def test_duplicate_run_id_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "model_runs.jsonl"
    run = _sample_run(run_id="same-id")
    record_run(run, ledger_path=ledger)

    with pytest.raises(DuplicateRunError, match="same-id"):
        record_run(_sample_run(run_id="same-id", notes="retry"), ledger_path=ledger)

    assert [item.run_id for item in load_runs(ledger_path=ledger)] == ["same-id"]


def test_set_global_seed_is_reproducible() -> None:
    set_global_seed(123)
    first = [random.random() for _ in range(8)]
    set_global_seed(123)
    second = [random.random() for _ in range(8)]
    set_global_seed(456)
    third = [random.random() for _ in range(8)]

    assert first == second
    assert third != first


def test_empty_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "missing" / "model_runs.jsonl"

    assert load_runs(ledger_path=ledger) == []
    assert get_run("any", ledger_path=ledger) is None
    assert not ledger.exists()


def test_compare_and_sort_helpers() -> None:
    left = _sample_run(
        run_id="a",
        metrics={"auc": 0.70, "log_loss": 0.62},
        hyperparameters={"n_estimators": 200, "learning_rate": 0.05},
        feature_names=["rating"],
    )
    right = _sample_run(
        run_id="b",
        model_type="catboost",
        metrics={"auc": 0.73, "log_loss": 0.60},
        hyperparameters={"n_estimators": 400, "learning_rate": 0.05},
        feature_names=["rating", "win_odds"],
        seed=7,
    )

    ranked = sort_runs([left, right], "auc")
    assert [run.run_id for run in ranked] == ["b", "a"]
    ranked_loss = sort_runs([left, right], "log_loss", descending=False)
    assert [run.run_id for run in ranked_loss] == ["b", "a"]
    assert metric_delta(left, right, "auc") == pytest.approx(0.03)

    comparison = compare_runs([left, right])
    assert comparison.run_ids == ["a", "b"]
    assert comparison.feature_hash_mismatch is True
    assert comparison.metrics["auc"]["b"] == pytest.approx(0.73)
    assert comparison.hyperparameters["n_estimators"]["a"] == 200
    assert comparison.hyperparameters["n_estimators"]["b"] == 400
    assert comparison.model_types["b"] == "catboost"


def test_compare_runs_requires_two_records() -> None:
    with pytest.raises(ValueError, match="2개"):
        compare_runs([_sample_run()])

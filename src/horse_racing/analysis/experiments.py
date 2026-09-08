"""Append-only JSON Lines ledger for reproducible model experiment runs."""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_LEDGER_PATH = Path("data/experiments/model_runs.jsonl")
_REPO_ROOT = Path(__file__).resolve().parents[3]


class DuplicateRunError(ValueError):
    """Raised when a run_id is already present in the ledger."""


def new_run_id() -> str:
    return str(uuid.uuid4())


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def current_git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            cwd=_REPO_ROOT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    commit = completed.stdout.strip()
    return commit or None


def hash_feature_names(names: Sequence[str]) -> str:
    canonical = json.dumps(list(names), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def set_global_seed(seed: int) -> None:
    """Fix the process-global RNG so a later training command can be reproduced.

    Only the stdlib ``random`` module is seeded. numpy is not a declared
    project dependency, so it is left untouched.
    """
    random.seed(seed)


class ModelRun(BaseModel):
    """One training/evaluation experiment, stored as a single JSONL record."""

    model_config = ConfigDict(protected_namespaces=())

    run_id: str = Field(default_factory=new_run_id)
    created_at_ms: int = Field(default_factory=now_ms)
    dataset_version: str
    dataset_manifest: dict[str, Any] = Field(default_factory=dict)
    feature_names: list[str] = Field(default_factory=list)
    feature_hash: str = ""
    model_type: str
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    seed: int
    train_period: str = ""
    valid_period: str = ""
    test_period: str = ""
    # Some evaluations are structurally unavailable (for example ROI when a
    # fixed rule places zero bets).  Keep the missing value explicit as null
    # instead of serializing NaN, which JSON represents ambiguously.
    metrics: dict[str, float | None] = Field(default_factory=dict)
    git_commit: str | None = Field(default_factory=current_git_commit)
    notes: str = ""

    @model_validator(mode="after")
    def _fill_feature_hash(self) -> ModelRun:
        computed = hash_feature_names(self.feature_names)
        if self.feature_hash != computed:
            self.feature_hash = computed
        return self


class RunComparison(BaseModel):
    """Side-by-side view of metrics, hyperparameters, and feature hashes."""

    run_ids: list[str]
    metrics: dict[str, dict[str, float | None]]
    hyperparameters: dict[str, dict[str, Any]]
    feature_hashes: dict[str, str]
    feature_hash_mismatch: bool
    model_types: dict[str, str]
    dataset_versions: dict[str, str]
    seeds: dict[str, int]


def resolve_ledger_path(ledger_path: Path | None = None) -> Path:
    return DEFAULT_LEDGER_PATH if ledger_path is None else Path(ledger_path)


def load_runs(*, ledger_path: Path | None = None) -> list[ModelRun]:
    path = resolve_ledger_path(ledger_path)
    if not path.exists():
        return []
    runs: list[ModelRun] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            runs.append(ModelRun.model_validate_json(stripped))
    return runs


def get_run(run_id: str, *, ledger_path: Path | None = None) -> ModelRun | None:
    for run in load_runs(ledger_path=ledger_path):
        if run.run_id == run_id:
            return run
    return None


def record_run(run: ModelRun, *, ledger_path: Path | None = None) -> None:
    path = resolve_ledger_path(ledger_path)
    existing = load_runs(ledger_path=path)
    if any(item.run_id == run.run_id for item in existing):
        raise DuplicateRunError(f"run_id already recorded: {run.run_id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(run.model_dump_json() + "\n")


def sort_runs(
    runs: Sequence[ModelRun],
    metric: str,
    *,
    descending: bool = True,
) -> list[ModelRun]:
    """Order runs by a metric. Missing values are placed last."""

    def sort_key(run: ModelRun) -> tuple[int, float]:
        value = run.metrics.get(metric)
        if value is None:
            return (1, 0.0)
        return (0, -value if descending else value)

    return sorted(runs, key=sort_key)


def compare_runs(runs: Sequence[ModelRun]) -> RunComparison:
    if len(runs) < 2:
        raise ValueError("비교하려면 2개 이상의 run이 필요합니다.")

    run_ids = [run.run_id for run in runs]
    metric_names = sorted({name for run in runs for name in run.metrics})
    hyperparameter_names = sorted({name for run in runs for name in run.hyperparameters})
    feature_hashes = {run.run_id: run.feature_hash for run in runs}

    return RunComparison(
        run_ids=run_ids,
        metrics={
            name: {run.run_id: run.metrics.get(name) for run in runs} for name in metric_names
        },
        hyperparameters={
            name: {run.run_id: run.hyperparameters.get(name) for run in runs}
            for name in hyperparameter_names
        },
        feature_hashes=feature_hashes,
        feature_hash_mismatch=len(set(feature_hashes.values())) > 1,
        model_types={run.run_id: run.model_type for run in runs},
        dataset_versions={run.run_id: run.dataset_version for run in runs},
        seeds={run.run_id: run.seed for run in runs},
    )


def metric_delta(
    left: ModelRun,
    right: ModelRun,
    metric: str,
) -> float | None:
    """Return ``right - left`` for a shared metric, or None if either is missing."""
    if (
        metric not in left.metrics
        or metric not in right.metrics
        or left.metrics[metric] is None
        or right.metrics[metric] is None
    ):
        return None
    return right.metrics[metric] - left.metrics[metric]


def values_differ(values: Mapping[str, Any]) -> bool:
    unique = list(values.values())
    if not unique:
        return False
    return any(item != unique[0] for item in unique[1:])

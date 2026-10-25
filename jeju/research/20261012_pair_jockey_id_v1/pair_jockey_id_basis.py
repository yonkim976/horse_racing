"""H1-only, race-equal, unknown-zero categorical jockey pair basis."""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np
import pandas as pd


class JockeyIdBasisError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise JockeyIdBasisError(message)


def fit_vocabulary(h1: pd.DataFrame) -> tuple[str, ...]:
    require("jockey_id" in h1, "H1 rows lack event jockey ID")
    ids = h1["jockey_id"].astype("string")
    require(ids.notna().all() and ids.str.fullmatch(r"\d{6}").all(), "invalid H1 event jockey ID")
    vocab = tuple(sorted(set(ids.astype(str))))
    require(bool(vocab), "empty H1 jockey vocabulary")
    return vocab


def fit_moments(h1_races: list[pd.DataFrame], vocabulary: tuple[str, ...]) -> dict[str, Any]:
    """Fit μ, π and σ with equal total weight per H1 race and equal pairs within race."""
    require(bool(h1_races) and bool(vocabulary), "empty H1 race set or jockey vocabulary")
    index = {jockey_id: i for i, jockey_id in enumerate(vocabulary)}
    race_means: list[np.ndarray] = []
    race_seconds: list[np.ndarray] = []
    starts_by_id = np.zeros(len(vocabulary), dtype=np.int64)
    races_by_id = np.zeros(len(vocabulary), dtype=np.int64)
    pair_count = 0
    for race in h1_races:
        ids = race["jockey_id"].astype("string").astype(str).tolist()
        require(len(ids) >= 4 and all(jockey_id in index for jockey_id in ids),
                "H1 race includes missing/unknown categorical jockey ID")
        counts = np.bincount([index[jockey_id] for jockey_id in ids], minlength=len(vocabulary)).astype(float)
        n = len(ids)
        pair_n = n * (n - 1) / 2.0
        # For category count c in a field of size n, sum(u)=c(n−1) and
        # sum(u²)=c(n−c)+4*C(c,2)=c*n+c²−2c across unordered pairs.
        pair_mean = 2.0 * counts / n
        pair_second = (counts * n + counts * counts - 2.0 * counts) / pair_n
        race_means.append(pair_mean)
        race_seconds.append(pair_second)
        starts_by_id += counts.astype(np.int64)
        races_by_id += (counts > 0).astype(np.int64)
        pair_count += int(pair_n)
    means = np.asarray(race_means, dtype=float)
    seconds = np.asarray(race_seconds, dtype=float)
    mu = means.mean(axis=0)
    pi = mu / 2.0
    variance = (seconds - 2.0 * mu[None, :] * means + mu[None, :] ** 2).mean(axis=0)
    sigma = np.sqrt(np.maximum(variance, 0.0))
    require(np.isfinite(mu).all() and np.isfinite(pi).all() and np.isfinite(sigma).all(),
            "non-finite H1 categorical moments")
    require(abs(float(np.sum(pi)) - 1.0) <= 1e-10, "H1 jockey category weights do not sum to one")
    return {
        "vocabulary": list(vocabulary),
        "mu": mu,
        "pi": pi,
        "sigma": sigma,
        "starts_by_id": starts_by_id,
        "races_by_id": races_by_id,
        "h1_races": len(h1_races),
        "h1_pairs": pair_count,
        "minimum_starts": int(starts_by_id.min()),
        "minimum_races": int(races_by_id.min()),
        "degenerate_ids": [vocabulary[i] for i, value in enumerate(sigma) if value <= 1e-12],
    }


def pair_basis(id_i: str, id_j: str, vocabulary: tuple[str, ...], pi: np.ndarray,
               sigma: np.ndarray) -> np.ndarray:
    """Return pair effect coding; an H1-unknown runner contributes exactly zero."""
    require(len(pi) == len(sigma) == len(vocabulary), "categorical moment dimensions differ")
    require(np.isfinite(pi).all() and np.isfinite(sigma).all(), "non-finite categorical moments")
    index = {jockey_id: i for i, jockey_id in enumerate(vocabulary)}
    ids = (str(id_i), str(id_j))
    u = np.zeros(len(vocabulary), dtype=float)
    known_n = 0
    for jockey_id in ids:
        pos = index.get(jockey_id)
        if pos is not None:
            u[pos] += 1.0
            known_n += 1
    centered = u - float(known_n) * pi
    result = np.zeros(len(vocabulary), dtype=float)
    active = sigma > 1e-12
    result[active] = centered[active] / sigma[active]
    require(np.isfinite(result).all(), "non-finite transformed categorical pair basis")
    return result


def race_pair_basis(race: pd.DataFrame, pairs: list[tuple[int, int]], vocabulary: tuple[str, ...],
                    pi: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Build symmetric pair category columns indexed by official horse number."""
    by_number = {int(row.horse_number): str(row.jockey_id) for row in race.itertuples(index=False)}
    require(len(by_number) == len(race), "duplicate horse number in categorical race rows")
    matrix = np.vstack([pair_basis(by_number[a], by_number[b], vocabulary, pi, sigma) for a, b in pairs])
    require(matrix.shape == (len(pairs), len(vocabulary)), "categorical pair design shape changed")
    return matrix


def raw_effects(theta: np.ndarray, pi: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Convert standardized θ to the implied known-ID runner effects α."""
    theta = np.asarray(theta, dtype=float)
    require(theta.shape == pi.shape == sigma.shape, "categorical coefficient/moment dimensions differ")
    require(np.isfinite(theta).all() and np.isfinite(pi).all() and np.isfinite(sigma).all(),
            "non-finite categorical effect inputs")
    alpha = np.zeros_like(theta)
    active = sigma > 1e-12
    alpha[active] = theta[active] / sigma[active]
    alpha[active] -= float(np.dot(pi[active], alpha[active]))
    return alpha


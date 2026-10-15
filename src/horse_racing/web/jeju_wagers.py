"""Read-only HY_R_FORM wager probabilities, cached without numerical ML dependencies."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from itertools import combinations, permutations
from math import exp, fsum, isclose, isfinite, log

from sqlalchemy import select
from sqlalchemy.orm import Session

from horse_racing.db.models import (
    ModelPrediction,
    PredictionModelComponent,
    PredictionRun,
    RaceEntry,
)

POOL_LABELS = {
    "WIN": "단승",
    "PLC": "연승",
    "QNL": "복승",
    "QPL": "복연승",
    "EXA": "쌍승",
    "TLA": "삼복승",
    "TRI": "삼쌍승",
}


def _logsum(values):
    values = tuple(values)
    peak = max(values)
    return peak + log(fsum(exp(value - peak) for value in values))


@lru_cache(maxsize=64)
def wager_probabilities(runners, beta_set: float, beta_order: float):
    """Enumerate the frozen hybrid's PL sets and within-set PL orders.

    Input is a tuple of (horse number, rank score, order score). Return immutable
    full-support pools. QPL sums to three, PLC to two/three; do not normalize them
    as mutually exclusive tickets. Keep these cache values independent of odds.
    """
    n = len(runners)
    if not 3 <= n <= 16 or len({row[0] for row in runners}) != n:
        raise ValueError("Invalid complete field")
    if any(not isfinite(value) or value <= 0 for value in (beta_set, beta_order)):
        raise ValueError("Invalid calibration")
    a = tuple(row[1] * beta_set for row in runners)
    b = tuple(row[2] * beta_order for row in runners)
    if not all(isfinite(value) for value in (*a, *b)):
        raise ValueError("Nonfinite scores")
    a = tuple(value - max(a) for value in a)
    b = tuple(value - max(b) for value in b)
    den0 = _logsum(a)
    den1 = tuple(_logsum(a[j] for j in range(n) if j != i) for i in range(n))
    den2 = {
        (i, j): _logsum(a[k] for k in range(n) if k not in (i, j))
        for i, j in combinations(range(n), 2)
    }
    joint = []
    for group in combinations(range(n), 3):
        orders = tuple(permutations(group))
        set_log = _logsum(
            a[i] + a[j] + a[k] - den0 - den1[i] - den2[tuple(sorted((i, j)))] for i, j, k in orders
        )
        within = tuple(
            b[i] - _logsum(b[t] for t in group) + b[j] - _logsum((b[j], b[k])) for i, j, k in orders
        )
        within_norm = _logsum(within)
        joint.extend(
            (order, set_log + value - within_norm)
            for order, value in zip(orders, within, strict=True)
        )
    normalizer = _logsum(value for _, value in joint)
    pools = {code: defaultdict(float) for code in POOL_LABELS}
    for (i, j, k), value in joint:
        probability = exp(value - normalizer)
        first, second, third = (runners[t][0] for t in (i, j, k))
        pools["WIN"][(first,)] += probability
        for number in (first, second) if n <= 7 else (first, second, third):
            pools["PLC"][(number,)] += probability
        pools["QNL"][tuple(sorted((first, second)))] += probability
        for pair in combinations((first, second, third), 2):
            pools["QPL"][tuple(sorted(pair))] += probability
        pools["EXA"][(first, second)] += probability
        pools["TLA"][tuple(sorted((first, second, third)))] += probability
        pools["TRI"][(first, second, third)] += probability
    return tuple(
        (code, tuple(sorted(values.items(), key=lambda row: (-row[1], row[0]))))
        for code, values in pools.items()
    )


def load_jeju_wagers(session: Session, *, race_id: int, meet_code: int):
    """Read one immutable publication; never silently drop scratched runners.

    OddsSnapshot currently includes postrace dividends without quote provenance.
    Deliberately do not use it as a prepurchase quote or write derived values.
    """
    if meet_code != 2:
        return None
    run = session.scalar(
        select(PredictionRun)
        .join(ModelPrediction, ModelPrediction.prediction_run_id == PredictionRun.id)
        .where(ModelPrediction.race_id == race_id, PredictionRun.publication_mode == "live")
        .order_by(PredictionRun.published_at_ms.desc(), PredictionRun.id.desc())
        .limit(1)
    )
    if run is None:
        return None
    unavailable = {
        "public_id": run.public_id,
        "pools": [],
        "message": "제주 운영 모델의 전체 출전마 원점수와 확률을 확인한 뒤 조합을 표시합니다.",
    }
    if run.domain != "jeju" or run.combination_algorithm_version != "jeju_hybrid_distribution_v1":
        return unavailable
    champion = session.scalar(
        select(PredictionModelComponent.id)
        .where(
            PredictionModelComponent.prediction_run_id == run.id,
            PredictionModelComponent.candidate_name == "HY_R_FORM",
        )
        .limit(1)
    )
    if champion is None:
        return unavailable
    rows = session.scalars(
        select(ModelPrediction)
        .where(ModelPrediction.prediction_run_id == run.id, ModelPrediction.race_id == race_id)
        .order_by(ModelPrediction.horse_number)
    ).all()
    current = session.execute(
        select(RaceEntry.id, RaceEntry.horse_number).where(
            RaceEntry.race_id == race_id, RaceEntry.scratched.is_(False)
        )
    ).all()
    if {(row.race_entry_id, row.horse_number) for row in rows} != set(current):
        return {
            **unavailable,
            "message": "출전마 변경이 있습니다. 변경을 반영한 예측 발행 후 조합을 표시합니다.",
        }
    required = (
        "raw_rank_score",
        "raw_order_score",
        "beta_set",
        "beta_order",
        "prob_win",
        "prob_top2",
        "prob_top3",
    )
    if not rows or any(
        row.field_size != len(rows)
        or row.starter_status != "starter"
        or any(getattr(row, key) is None for key in required)
        for row in rows
    ):
        return unavailable
    bs, bo = rows[0].beta_set, rows[0].beta_order
    if any(row.beta_set != bs or row.beta_order != bo for row in rows):
        return unavailable
    try:
        pools = wager_probabilities(
            tuple((row.horse_number, row.raw_rank_score, row.raw_order_score) for row in rows),
            bs,
            bo,
        )
        lookup = {code: dict(values) for code, values in pools}
        # Guard against mixing a different joint algorithm with stored marginals.
        for row in rows:
            number = row.horse_number
            win = lookup["WIN"][(number,)]
            top2 = fsum(p for key, p in lookup["QNL"].items() if number in key)
            top3 = fsum(p for key, p in lookup["TLA"].items() if number in key)
            if any(
                not isfinite(stored) or not isclose(actual, stored, abs_tol=2e-7, rel_tol=2e-7)
                for actual, stored in (
                    (win, row.prob_win),
                    (top2, row.prob_top2),
                    (top3, row.prob_top3),
                )
            ):
                return unavailable
    except (ValueError, OverflowError):
        return unavailable
    return {
        "public_id": run.public_id,
        "message": "",
        "field_size": len(rows),
        "pools": [
            {
                "code": code,
                "label": POOL_LABELS[code],
                "count": len(values),
                "rows": [
                    {"selection": list(key), "probability": probability}
                    for key, probability in values
                ],
            }
            for code, values in pools
        ],
    }

"""Small deterministic checks; they do not read study outcomes or fit models."""
from __future__ import annotations

import math
import numpy as np


def _pool_contract(engine, n: int) -> None:
    numbers = np.arange(1, n + 1, dtype=np.int64)
    scores = np.linspace(0.8, -0.7, n, dtype=np.float64)
    ranks = np.arange(1, n + 1, dtype=np.int64)
    plc_top = 2 if n == 5 else 3
    maps, marginal, mass = engine.probability_maps_from_scenarios([scores], [1.0], numbers, plc_top)
    assert math.isclose(mass, 1.0, rel_tol=0.0, abs_tol=3e-11)
    assert float(next(iter(maps["PLC"].values()))) >= 0.0
    assert math.isclose(float(sum(maps["PLC"].values())), float(plc_top), rel_tol=0.0, abs_tol=5e-11)
    assert math.isclose(float(marginal["p_win"].sum()), 1.0, rel_tol=0.0, abs_tol=3e-11)
    assert math.isclose(float(marginal["p_top2"].sum()), 2.0, rel_tol=0.0, abs_tol=3e-11)
    assert math.isclose(float(marginal["p_top3"].sum()), 3.0, rel_tol=0.0, abs_tol=3e-11)
    plc_truth = engine.truth_ticket_keys("PLC", numbers, ranks, plc_top)
    assert len(plc_truth) == plc_top
    metric, _selection = engine.pool_race_metrics("PLC", maps["PLC"], plc_truth)
    assert metric["event_count"] == plc_top and metric["ticket_count"] == n
    qpl_truth = engine.truth_ticket_keys("QPL", numbers, ranks, plc_top)
    assert len(qpl_truth) == 3
    assert len(maps["QPL"]) == math.comb(n, 2)
    assert math.isclose(float(sum(maps["QPL"].values())), 3.0, rel_tol=0.0, abs_tol=5e-11)
    assert set(engine.truth_ticket_keys("QNL", numbers, ranks, plc_top)) == {(1, 2)}


def run_tests(engine, runner) -> dict:
    assert len(engine.__reference_tree_sha256__) == 64
    _pool_contract(engine, 5)  # Known 5-runner contract: PLC is Top2.
    _pool_contract(engine, 8)  # Robust actual-8 lower bound: PLC is Top3.
    assert engine.plc_top_for_actual_field(7)[0] is None
    assert engine.plc_top_for_actual_field(8)[0] == 3

    tied = {(3, 4): 0.5, (1, 9): 0.5, (2, 7): 0.25, (1, 8): 0.1}
    assert runner._top_k_tickets(tied, 3) == [(1, 9), (3, 4), (2, 7)]

    # Verify the exact-union/count computation against a complete synthetic QPL map.
    numbers = np.arange(1, 9, dtype=np.int64)
    scores = np.asarray([0.2, 0.1, 0.0, -0.1, -0.2, -0.3, -0.4, -0.5], dtype=np.float64)
    maps, _marginals, _mass = engine.probability_maps_from_scenarios([scores], [1.0], numbers, 3)
    chosen = runner._top_k_tickets(maps["QPL"], 3)
    truth = engine.truth_ticket_keys("QPL", numbers, np.arange(1, 9), 3)
    record = {"numbers": numbers, "truths": truth, "tickets": maps["QPL"]}
    diag = runner._pair_selection_diagnostic(record, scores, "QPL", chosen, engine)
    distribution = np.asarray([diag[f"count_probability_{ix}"] for ix in range(4)])
    assert np.isfinite(distribution).all() and np.all(distribution >= 0.0)
    assert math.isclose(float(distribution.sum()), 1.0, rel_tol=0.0, abs_tol=3e-11)
    assert math.isclose(float(diag["selected_union_probability"]), float(distribution[1:].sum()),
                        rel_tol=0.0, abs_tol=1e-14)
    assert math.isclose(float(diag["expected_hits"]), float(np.dot(np.arange(4), distribution)),
                        rel_tol=0.0, abs_tol=1e-14)
    assert diag["realized_hit_count"] == sum(ticket in truth for ticket in chosen)

    receipt_rows = runner._model_receipt_rows({("C", 2024): {"arm": "stale", "year": -1, "best_iteration": 7}})
    assert receipt_rows == [{"arm": "C", "year": 2024, "best_iteration": 7}]

    try:
        runner._ensure_experiment_path(runner.EXPERIMENT / ".." / "outside.json")
    except RuntimeError:
        confinement_checked = True
    else:
        raise AssertionError("path confinement accepted a parent traversal")

    return {
        "status": "PASS_SYNTHETIC",
        "fit_calls": 0,
        "actual_probabilities_or_outcomes": False,
        "checks": [
            "5-runner PLC Top2 event and mass",
            "8-runner PLC Top3 and QPL three-hit event",
            "actual-7 PLC remains unknown without opening count",
            "full-field Q mass and runner marginal identities",
            "lexicographic deterministic numerical-tie selection",
            "QPL selected-ticket exact union and 0..3 count distribution",
            "sealed reference module loaded without changing its tree",
            "fit receipt model rows override stale metadata arm/year safely",
            "new-write path confinement",
        ],
        "path_confinement_checked": confinement_checked,
    }

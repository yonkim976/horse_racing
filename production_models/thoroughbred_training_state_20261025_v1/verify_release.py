"""Release checks against frozen research predictions, not a new performance test."""

from pathlib import Path
import importlib.util, json, re, subprocess, sys
import numpy as np
import pandas as pd
import inference
import features

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
R = ROOT / "thoroughbred/research"


def load_validator():
    p = (
        ROOT
        / ".agents/skills/horse-racing-prediction-publisher/scripts/validate_prediction_payload.py"
    )
    spec = importlib.util.spec_from_file_location("promotion_payload_validator", p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    card = pd.read_parquet(HERE / "fixtures/cards.parquet")
    f = pd.read_parquet(HERE / "verification/rebuilt_features.parquet")
    expected = pd.read_parquet(HERE / "fixtures/expected_features.parquet")
    aligned = expected[features.KEY].merge(f, on=features.KEY, validate="one_to_one")
    maximum = 0.0
    values = 0
    for col in features.CONTRACT["features"]:
        if pd.api.types.is_numeric_dtype(expected[col]):
            a = expected[col].to_numpy(float)
            b = aligned[col].to_numpy(float)
            np.testing.assert_allclose(a, b, atol=1e-9, rtol=0, equal_nan=True)
            common = np.isfinite(a) & np.isfinite(b)
            if common.any():
                maximum = max(maximum, float(np.max(np.abs(a[common] - b[common]))))
        else:
            assert expected[col].fillna("MISSING").equals(aligned[col].fillna("MISSING")), col
        values += len(f)
    sys.path.insert(0, str(R / "20261024_training_state_v1"))
    import study_common as previous

    full = previous.frame(2)
    full = full[full.year.eq(2026)].copy()
    full["race_no"] = full.race_key.str.rsplit(":", n=1).str[-1].astype(int)
    p, _, tickets, _ = inference.predict(full, explain=False)
    prior = pd.read_parquet(
        R / "20261024_training_state_v1/outputs/runner_probabilities.parquet"
    ).query("variant=='personal_t2'")
    prior = prior.merge(full[features.KEY], on=features.KEY, validate="one_to_one")
    pair = prior.merge(p, on=features.KEY, validate="one_to_one")
    prob_error = 0.0
    for old, new in [("win", "prob_win"), ("top2", "prob_top2"), ("top3", "prob_top3")]:
        error = float(np.max(np.abs(pair[old] - pair[new])))
        prob_error = max(prob_error, error)
        assert error < 1e-12
    metrics = pd.read_parquet(R / "20261024_training_state_v1/outputs/race_metrics.parquet")
    metrics = metrics[metrics.variant.eq("personal_t2") & metrics.year.eq(2026)].set_index(
        "race_key"
    )
    for key, g in p.groupby("race_key"):
        axis = g[g.a_rank_in_race.eq(1)].iloc[0]
        assert int(axis.program_no) == int(metrics.loc[key, "axis_program_no"])
    old_tickets = pd.read_parquet(R / "20261024_training_state_v1/outputs/tickets.parquet")
    old_tickets = old_tickets[
        old_tickets.variant.eq("personal_t2") & old_tickets.race_key.isin(set(p.race_key))
    ]
    lookup = {
        (row.race_key, row.pool, int(row.rank)): (int(row.program_a), int(row.program_b))
        for row in old_tickets.itertuples()
    }
    pair_checks = 0
    for t in tickets:
        if t["pool"] in ["quinella", "qpl"]:
            assert tuple(t["programs"]) == lookup[t["race_key"], t["pool"], t["rank"]]
            pair_checks += 1
    fixture, explanations, _, checks = inference.predict(f)
    # Synthetic fixture IDs exist only in this local validator input and are never published.
    fixture["race_id"] = pd.factorize(fixture.race_key)[0] + 1
    fixture["race_entry_id"] = np.arange(1, len(fixture) + 1)
    validator = load_validator()
    import polars as pl

    payload = validator.validate_publication(pl.from_pandas(fixture), "thoroughbred")
    assert len(explanations) == 6 * len(fixture)
    preview = json.loads((HERE / "verification/dry_run_preview/run_metadata.json").read_text())
    assert (
        preview["dry_run"]
        and preview["preview"]
        and preview["database_writes"] == preview["network_calls"] == 0
    )
    tests = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "tests/test_promoted_training_state.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    (HERE / "verification/pytest.txt").write_text(tests.stdout + tests.stderr)
    assert tests.returncode == 0, tests.stdout[-2000:]
    test_count = int(re.search(r"(\d+) passed", tests.stdout).group(1))
    v = {
        "status": "passed",
        "feature_builder_parity_passed": True,
        "result_free_cards": len(card),
        "feature_fixture_races": int(f.race_key.nunique()),
        "feature_values_checked": values,
        "feature_max_error": maximum,
        "numerical_replay_passed": True,
        "replayed_races": int(p.race_key.nunique()),
        "replayed_runners": len(p),
        "probabilities_checked": len(p) * 3,
        "max_probability_error": prob_error,
        "reproduced_pair_tickets": pair_checks,
        "all_axis_decisions_reproduced": True,
        "publication_payload_fixture_passed": True,
        "publication_fixture": payload,
        "synthetic_fixture_ids_not_published": True,
        "six_signed_explanations_per_runner": True,
        "max_shap_additivity_error": checks["max_shap_additivity_error"],
        "card_contract_checks_passed": True,
        "contract_tests": test_count,
        "cli_preview_passed": True,
        "new_training_fits": 0,
        "new_future_performance_validation": False,
        "no_database_or_network_writes": True,
        "verifier_sha256": features.sha(__file__),
    }
    (HERE / "verification/technical_verification.json").write_text(
        json.dumps(v, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(v, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

from horse_racing.analysis.gates import judge_g1


def _metrics(log_loss: float, ece: float = 0.01) -> dict[str, float]:
    return {"log_loss": log_loss, "ece": ece}


def test_judge_g1_passes_when_all_conditions_hold() -> None:
    decision = judge_g1(
        candidate=_metrics(0.27),
        baseline_b1=_metrics(0.31),
        baseline_b2=_metrics(0.29),
        meet_candidate={"1": _metrics(0.27), "3": _metrics(0.25)},
        meet_b1={"1": _metrics(0.31), "3": _metrics(0.29)},
        ablation_passed=True,
    )

    assert decision.passed is True
    assert all(decision.criteria.values())


def test_judge_g1_fails_on_bad_calibration() -> None:
    decision = judge_g1(
        candidate=_metrics(0.27, ece=0.04),
        baseline_b1=_metrics(0.31),
        baseline_b2=_metrics(0.29),
        meet_candidate={"1": _metrics(0.27), "3": _metrics(0.25)},
        meet_b1={"1": _metrics(0.31), "3": _metrics(0.29)},
        ablation_passed=True,
    )

    assert decision.passed is False
    assert decision.criteria["ece_at_most_003"] is False

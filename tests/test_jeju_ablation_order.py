"""The ablation protocol must remove whole declared groups without label leakage."""

import json

from horse_racing.analysis.jeju_context_features import FEATURES
from scripts.freeze_jeju_ablation_protocol import GROUPS, OUT


def test_new_feature_groups_partition_all_observations():
    flattened = sum(GROUPS.values(), [])
    assert len(flattened) == len(set(flattened)) == 40
    assert set(flattened) == set(FEATURES)


def test_leave_one_group_out_retains_base_and_removes_exact_group():
    p = json.loads((OUT / "protocol.json").read_text())
    all_features = p["joint_features"]
    assert len(all_features) == len(set(all_features)) == 108
    for group, removed in GROUPS.items():
        features = p["rank_candidates"]["R_NO_" + group.upper()]
        assert set(all_features) - set(features) == set(removed)
        assert set(p["base_features"]).issubset(features)
        assert len(features) == 108 - len(removed)
        assert not set(features) & {"finish_position", "label_top3", "body_weight_kg", "weather"}


def test_fit_budget_and_references_separate_new_candidates():
    p = json.loads((OUT / "protocol.json").read_text())
    assert p["counts"] == dict(
        estimator_fits=48, calibration_fits=28, bundles=28, reference_refits=0
    )
    assert not set(p["rank_candidates"]) & set(p["references"])
    assert p["joint_candidate"] not in p["references"]
    assert p["hybrid_candidate"] not in p["references"]

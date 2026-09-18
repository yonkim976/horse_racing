"""Freeze bounded trial recency/detail comparison before any fit."""

import json
from datetime import UTC, datetime

from horse_racing.analysis.jeju_trial_features import FEATURES, RECENCY_FEATURES
from scripts.run_jeju_joint_top3 import DATA, H3, ROOT, sha

OUT = ROOT / "data/research/jeju_native_trial_experiment_v11_20260916"
TRIAL = ROOT / "data/research/jeju_native_trial_features_v1_20260916"
CTX = ROOT / "data/research/jeju_native_context_features_v1_20260916"
V5 = ROOT / "data/research/jeju_native_context_experiment_v5_20260916"
V9 = ROOT / "data/research/jeju_native_experience_calibration_v9_20260916"


def main():
    old = json.loads((V5 / "protocol.json").read_text())
    full = old["base_features"] + old["context_features"] + old["form_features"]
    p = dict(
        version="trial_recency_detail_v11",
        created_at=datetime.now(UTC).isoformat(),
        base_features=old["base_features"],
        context_features=old["context_features"],
        form_features=old["form_features"],
        rank_candidates={
            "R_TRIAL_RECENCY": full + RECENCY_FEATURES,
            "R_TRIAL_DETAIL": full + FEATURES,
        },
        hybrids={"HY_TRIAL_RECENCY": "R_TRIAL_RECENCY", "HY_TRIAL_DETAIL": "R_TRIAL_DETAIL"},
        references=["R_FORM", "HY_R_FORM", "C_EXPERIENCE_FIXED"],
        comparisons=[
            ["R_TRIAL_RECENCY", "R_FORM"],
            ["R_TRIAL_DETAIL", "R_TRIAL_RECENCY"],
            ["R_TRIAL_DETAIL", "R_FORM"],
            ["HY_TRIAL_RECENCY", "HY_R_FORM"],
            ["HY_TRIAL_DETAIL", "HY_TRIAL_RECENCY"],
            ["HY_TRIAL_DETAIL", "HY_R_FORM"],
            ["HY_TRIAL_DETAIL", "C_EXPERIENCE_FIXED"],
        ],
        seeds=[17, 43],
        rank_params=old["params"],
        counts=dict(estimator_fits=16, calibration_fits=8, bundles=16, reference_refits=0),
        training="Four frozen chronological FIT/TUNE/CAL/EVAL folds; FIT preprocessing; "
        "TUNE NDCG@3 early stop30. Average2 seeds. No retries or EVAL feature selection.",
        calibration="Rank PL positive scalar CAL accepted-order NLL, log bounds[-4,4]. "
        "Hybrids reuse V5 HY_R_FORM order head AND beta_order without any refit.",
        hypothesis="Recency control adds3 features; detail adds7 more; original108 untouched. "
        "800m trial and race performance remain separate. Last3 valid within365d.",
        metrics="715 races for hits;709 nonboundary for marginal error; paired race/day "
        "bootstrap5000 seed17. Unadjusted exploratory intervals;2025 repeatedly used.",
        subgroup="All nonboundary horse entries with starts_pre=0; counts, Brier, logloss "
        "and mean probability vs observed. No correctness-conditioned subgroup.",
        decision="Research selection candidate only if paired set-hit day CI lower>0 against "
        "corresponding original and pick/order point differences>=0. "
        "No production promotion; independent future validation required.",
        leakage="Strict T-2 same official horse ID; no name conflict rescue. Actual-starter "
        "retrospective population, publication-time proof incomplete; not Wednesday "
        "live accuracy. No2026 predictions/evaluation; live declarations unused.",
        parents={
            str(d.relative_to(ROOT)): sha(d / "manifest.json")
            for d in [DATA, H3, CTX, TRIAL, V5, V9]
        },
    )
    assert len(full) == 108
    OUT.mkdir(exist_ok=False)
    (OUT / "protocol.json").write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n")
    print(p["counts"])


if __name__ == "__main__":
    main()

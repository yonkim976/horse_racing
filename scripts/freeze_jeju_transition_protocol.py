"""Freeze the first2026 evaluation of transition candidates before feature expansion."""

import json
import pickle
from datetime import UTC, datetime

from horse_racing.analysis.jeju_transition_features import BASIC, INTERACTIONS
from scripts.build_jeju_context_features import DB
from scripts.freeze_jeju_trial_protocol import CTX, DATA, H3, ROOT, V5, sha

OUT = ROOT / "data/research/jeju_native_transition_holdout_v13_20260916"
FEAT = ROOT / "data/research/jeju_native_transition_features_v1_20260916"
V4 = ROOT / "data/research/jeju_native_joint_top3_v4_20260916"
V12 = ROOT / "data/research/jeju_native_error_conditions_v12_20260916"


def main():
    p5 = json.loads((V5 / "protocol.json").read_text())
    p4 = json.loads((V4 / "protocol.json").read_text())
    old = pickle.loads((V5 / "bundles/dev_2025_q4__HY_R_FORM.pkl").read_bytes())
    base = p5["base_features"] + p5["context_features"] + p5["form_features"]
    assert len(base) == 108 and len(old["order_bundle"]["features"]) == 68
    p = dict(
        version="transition_2026_once_v13",
        created_at=datetime.now(UTC).isoformat(),
        base_features=p5["base_features"],
        context_features=p5["context_features"],
        form_features=p5["form_features"],
        rank_candidates={
            "R_FORM": base,
            "R_TRANSITION": base + BASIC,
            "R_TRANSITION_CONTEXT": base + BASIC + INTERACTIONS,
        },
        hybrids={
            "HY_R_FORM": "R_FORM",
            "HY_TRANSITION": "R_TRANSITION",
            "HY_TRANSITION_CONTEXT": "R_TRANSITION_CONTEXT",
        },
        references=["R_FORM", "HY_R_FORM"],
        order_features=old["order_bundle"]["features"],
        seeds=[17, 43],
        rank_params=p5["params"],
        order_params=p4["params"],
        joint_weight=1.0,
        fold="frozen_2026",
        evaluation_start="2026-01-02",
        evaluation_end="2026-09-12",
        expected_evaluation_races=510,
        expected_evaluation_entries=4852,
        counts=dict(rank_fits=6, order_fits=2, estimator_fits=8, calibration_fits=4, bundles=7),
        comparisons=[
            ["R_TRANSITION", "R_FORM"],
            ["R_TRANSITION_CONTEXT", "R_TRANSITION"],
            ["R_TRANSITION_CONTEXT", "R_FORM"],
            ["HY_TRANSITION", "HY_R_FORM"],
            ["HY_TRANSITION_CONTEXT", "HY_TRANSITION"],
            ["HY_TRANSITION_CONTEXT", "HY_R_FORM"],
        ],
        training="One existing frozen2026 FIT/TUNE/CAL/EVAL split. FIT-only preprocessing. All model fitting and temperatures end2025. "  # noqa: E501
        "Ranker fixed params, TUNE NDCG@3 stop30. Joint order MLP fixed max100 selects TUNE checkpoint. "  # noqa: E501
        "Two seeds averaged. Rebuild baseline with same split; no old2025 performance comparison denominator.",  # noqa: E501
        calibration="CAL rank positive scalar3fits log[-4,4] accepted orderNLL. One order scalar fitted with baseline rank sets. "  # noqa: E501
        "Both new hybrids reuse same order head AND baseline order scalar.",
        features="Six basic transitions plus seven fixed interaction products. Grades numeric1..6 only; grade comparison "  # noqa: E501
        "requires previous and target same calendar year, else missing. No raw official rating subtraction. "  # noqa: E501
        "Current grade and burden exclusively sealed declarations. Previous actual race atT-2; no current outcomes.",  # noqa: E501
        sequential="Weights frozen through2025. Historical states update through targetT-2 including earlier2026 outcomes. "  # noqa: E501
        "This is sequential retrospective evaluation, not a Jan1 static prediction of the full year.",  # noqa: E501
        outcome_access="Freeze protocol before extending2026 history features. Emit and hash all six model score tables "  # noqa: E501
        "before joining2026 targets for scoring. No adaptive retry or further selection after evaluation.",  # noqa: E501
        subgroup="All nonboundary entries with valid same-year grade6to5 transition. Entry-weighted predicted-minus-observed "  # noqa: E501
        "bias with paired race-day bootstrap5000 seed17. Missing and other entries reported separately.",  # noqa: E501
        primary="Set-hit difference vs HY_R_FORM for two new hybrids. Paired race-day bootstrap5000 seed17. "  # noqa: E501
        "Use97.5% two-sided intervals per comparison (Bonferroni two primary candidates). "
        "Research promotion only if lower>0 AND pick/order point differences>=0. Diagnostics95% unadjusted.",  # noqa: E501
        decision="If both pass prefer contextual only when its set hit rate exceeds basic; otherwise prefer basic. "  # noqa: E501
        "If none pass retain baseline. Never automatic production replacement. Probability-only improvement reported separately.",  # noqa: E501
        limitations="Actual starters, retrospectively collected dated cards, incomplete historical publication/revision proof. "  # noqa: E501
        "Not Wednesday live accuracy.2026 becomes evaluated evidence after this single run; no reuse as untouched holdout.",  # noqa: E501
        parents={
            str(d.relative_to(ROOT)): sha(d / "manifest.json") for d in [DATA, H3, CTX, V4, V5, V12]
        },
        database_sha256=sha(DB),
    )
    OUT.mkdir(exist_ok=False)
    (OUT / "protocol.json").write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n")
    print(p["counts"])


if __name__ == "__main__":
    main()

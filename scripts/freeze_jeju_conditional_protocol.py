"""Predeclare conditional order and contextual form replacement as a 2x2 comparison."""

import json
from datetime import UTC, datetime
from pathlib import Path

from horse_racing.analysis.jeju_rebound_features import FEATURES
from scripts.freeze_jeju_ablation_protocol import GROUPS
from scripts.run_jeju_ablation_order import CTX, DATA, H3, V3, V4, V5, sha
from scripts.run_jeju_ablation_order import OUT as V6

ROOT = Path(__file__).resolve().parents[1]
RB = ROOT / "data/research/jeju_native_rebound_features_v1_20260916"
OUT = ROOT / "data/research/jeju_native_conditional_order_v7_20260916"


def main():
    p5 = json.loads((V5 / "protocol.json").read_text())
    full = p5["base_features"] + p5["context_features"] + p5["form_features"]
    revised = [f for f in full if f not in GROUPS["growth"]] + FEATURES
    p = dict(
        version="conditional_order_contextual_rebound_v7",
        created_at=datetime.now(UTC).isoformat(),
        references=["R_FORM", "HY_R_FORM", "HY_FORM_ORDER", "J_FORM", "R_NO_GROWTH"],
        base_features=p5["base_features"],
        context_features=p5["context_features"],
        form_features=p5["form_features"],
        rebound_features=FEATURES,
        replaced_features=GROUPS["growth"],
        rank_candidates={"R_REBOUND": revised},
        order_candidates={"O_BASE": full, "O_REBOUND": revised},
        hybrids={
            "HY_C_BASE": ["R_FORM", "O_BASE"],
            "HY_C_REBOUND": ["R_FORM", "O_REBOUND"],
            "HY_RB_BASE": ["R_REBOUND", "O_BASE"],
            "HY_RB_REBOUND": ["R_REBOUND", "O_REBOUND"],
        },
        seeds=[17, 43],
        rank_params=p5["params"],
        order_params=dict(hidden_dim=16, l2=0.001, max_iter=100),
        counts=dict(estimator_fits=24, calibration_fits=20, bundles=28, reference_refits=0),
        conditional_loss="Equal race weight; conditional PL over each official podium set. "
        "Sum probabilities of compatible tied orders and average over distinct compatible "
        "sets. No inclusion head, no gradient from other finishers. All training races used; "
        "never select training/evaluation races by whether predicted set hits.",
        tie_calibration="CAL minimizes accepted JOINT order NLL with each fixed ranker set "
        "distribution; boundary ties use ranker-weighted compatible sets. Training uses "
        "uniform compatible set weights, calibration preserves full joint consistency.",
        training="Exact saved four chronological FIT/TUNE/CAL/EVAL partitions. FIT-only "
        "preprocessing. Ranker TUNE NDCG@3 early stop30; order model TUNE conditional "
        "NLL chooses checkpoint among initialization and100 L-BFGS iterations. Average "
        "two seed raw scores. Report optimizer nonconvergence; no EVAL-driven retries.",
        calibration="Ranker and hybrid scalar positive temperatures on CAL, log bounds[-4,4]. "
        "Order raw bundles have no independent calibration; each hybrid calibrates once.",
        hypothesis="2x2 ranker(original/rebound) x conditional order(original/rebound). "
        "Compare HY_C_BASE vs old HY_R_FORM to test direct order objective; compare "
        "HY_C_REBOUND vs HY_C_BASE for order features; HY_RB_BASE vs HY_C_BASE for ranker "
        "features; final combined vs each one-factor variant. No additional combinations.",
        features="Replace four raw growth/rebound proxies with ten same-distance historical "
        "features, pairwise observed minus Elo expected score, shrinkage n/(n+3), "
        "past wet/dry separation, race-relative time; no current weather or bodyweight.",
        metrics="715 races2025 for all hit rates/orderNLL;709 nonboundary for marginal errors. "
        "Single pick, MAPset, MAPorder within set. 5000 paired race/day draws seed17. "
        "Exploratory unadjusted95% intervals; repeated development, no promotion by best cell.",
        leakage="T-2 historical cutoff; frozen actual-starter population and retrospectively "
        "collected declaration cards. Exact historical publication/revision evidence absent. "
        "No2026 predictions/outcomes; live206 declaration dataset not used.",
    )
    for path, key in [
        (DATA, "dataset"),
        (H3, "h3"),
        (CTX, "context"),
        (V3, "v3"),
        (V4, "v4"),
        (V5, "v5"),
        (V6, "v6"),
        (RB, "rebound"),
    ]:
        p[key + "_manifest_sha256"] = sha(path / "manifest.json")
    assert len(full) == 108 and len(revised) == 114 and len(set(revised)) == 114
    OUT.mkdir(exist_ok=True)
    with (OUT / "protocol.json").open("x") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    print(p["counts"])


if __name__ == "__main__":
    main()

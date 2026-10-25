"""Reconstruct the existing score-argmax axis and fixed evaluation denominators."""
from pathlib import Path
import hashlib
import json
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"


def main():
    p = pd.read_parquet(SOURCE).sort_values(["race_id", "score", "horse_number"], ascending=[True, False, True], kind="stable")
    p["score_rank"] = p.groupby("race_id").cumcount() + 1
    b = p.loc[p.score_rank.eq(1)].copy()
    b["primary"] = b.distance_m.isin([900, 1000, 1110, 1200])
    for k in [3, 5]:
        counts = p.loc[p.score_rank.le(k)].groupby("race_id").y.sum()
        b[f"top{k}_actual_top3_n"] = b.race_id.map(counts).astype(int)
    assert len(b) == 1779 and b.primary.sum() == 1503
    rows = []
    for scope, x in [("primary_four_distances", b.loc[b.primary]), ("all_distances", b)]:
        rows.append({"scope": scope, "races": len(x), "dates": x.race_date.nunique(),
                     "baseline_hits": int(x.y.sum()), "baseline_top3_rate": float(x.y.mean()),
                     "top3_pool_any_actual_top3": int(x.top3_actual_top3_n.gt(0).sum()),
                     "top5_pool_any_actual_top3": int(x.top5_actual_top3_n.gt(0).sum())})
    with (HERE / "ROOT_BASELINE_RACE_LEDGER.parquet").open("xb") as out:
        b.to_parquet(out, index=False)
    with SOURCE.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with (HERE / "ROOT_BASELINE_RECEIPT.json").open("x") as out:
        json.dump({"passed": True, "source_sha256": digest, "comparisons": rows,
                   "new_selector_models_fitted": 0, "database_opened": False}, out, indent=2)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()

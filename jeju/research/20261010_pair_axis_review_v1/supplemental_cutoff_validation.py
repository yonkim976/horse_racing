"""Independent check of the frozen single-anchor .6/.8 cutoff supplement."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUTS = HERE / "outputs"
A_README = ROOT / "jeju/research/20261010_pair_axis_v1/README.md"
A_PER_RACE = ROOT / "jeju/research/20261010_pair_axis_v1/outputs/per_race_metrics.csv"
C_RESULTS = OUTPUTS / "policy_race_results.csv"
C_RECEIPT = OUTPUTS / "independent_validation_receipt.json"
EXPECTED_HASHES = {
    "a_readme": "5c737060cd6c46d52f95cdb930e99b35fd0754645b714ac10ceb8c8363bf7a04",
    "a_per_race": "78b75895ddd82a72a406aa2b9d4fa889946d25e6a8d8c8f50069aac286b267c1",
    "c_results": "966826e0de042ae837f80344a808331e2351b9accdd3b548b51714f2b7e8e28c",
}
EXPECTED = {
    ("candidate", 0.6): {"races": 684, "dates": 246, "years": {"2024": 250, "2025": 196, "2026": 238}, "axis_hits": 471,
                         "k3_single": 128, "k3_unrestricted": 128, "k4_single": 153, "k4_unrestricted": 154},
    ("matched_baseline", 0.6): {"races": 693, "dates": 245, "years": {"2024": 251, "2025": 191, "2026": 251}, "axis_hits": 477,
                                "k3_single": 125, "k3_unrestricted": 125, "k4_single": 158, "k4_unrestricted": 157},
    ("candidate", 0.8): {"races": 55, "dates": 51, "years": {"2024": 28, "2025": 7, "2026": 20}, "axis_hits": 45,
                         "k3_single": 11, "k3_unrestricted": 11, "k4_single": 12, "k4_unrestricted": 12},
    ("matched_baseline", 0.8): {"races": 60, "dates": 55, "years": {"2024": 35, "2025": 8, "2026": 17}, "axis_hits": 48,
                                "k3_single": 9, "k3_unrestricted": 9, "k4_single": 12, "k4_unrestricted": 12},
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def ticket_list(row: dict[str, str]) -> list[tuple[int, int, int]]:
    return [tuple(int(x) for x in ticket) for ticket in json.loads(row["selected_tickets"])]  # type: ignore[return-value]


def main() -> None:
    actual_hashes = {
        "a_readme": sha256(A_README),
        "a_per_race": sha256(A_PER_RACE),
        "c_results": sha256(C_RESULTS),
    }
    require(actual_hashes == EXPECTED_HASHES, f"frozen supplement source hash mismatch: {actual_hashes}")
    c_receipt = json.loads(C_RECEIPT.read_text(encoding="utf-8"))
    require(c_receipt.get("study") == "20261010_pair_axis_review_v1",
            "main independent receipt identifies a different study")
    require(c_receipt["artifact_hashes"]["policy_race_results.csv"]["sha256"] == EXPECTED_HASHES["c_results"],
            "main independent receipt does not pin the selected-race source")
    rows = read_csv(C_RESULTS)
    lookup = {
        (row["race_id"], row["arm"], row["policy"], int(row["ticket_budget"])): row
        for row in rows
    }
    race_ids = sorted({row["race_id"] for row in rows})
    summaries: list[dict[str, Any]] = []
    for arm in ("candidate", "matched_baseline"):
        for cutoff in (0.6, 0.8):
            selected_ids = [
                race_id for race_id in race_ids
                if float(lookup[(race_id, arm, "single_top3_anchor", 3)]["axis_probability"]) >= cutoff
            ]
            base_rows = [lookup[(race_id, arm, "single_top3_anchor", 3)] for race_id in selected_ids]
            years = dict(sorted(Counter(row["year"] for row in base_rows).items()))
            dates = {row["race_date"] for row in base_rows}
            axis_hits = sum(int(row["axis_hit"]) for row in base_rows)
            summary: dict[str, Any] = {
                "arm": arm,
                "cutoff": cutoff,
                "selected_races": len(selected_ids),
                "selected_dates": len(dates),
                "selected_races_by_year": years,
                "single_anchor_axis_hits": axis_hits,
                "budgets": {},
            }
            for k in (3, 4):
                single_rows = [lookup[(race_id, arm, "single_top3_anchor", k)] for race_id in selected_ids]
                unrestricted_rows = [lookup[(race_id, arm, "unrestricted_top_k", k)] for race_id in selected_ids]
                single_hits = sum(int(row["ticket_hit"]) for row in single_rows)
                unrestricted_hits = sum(int(row["ticket_hit"]) for row in unrestricted_rows)
                identical = sum(ticket_list(left) == ticket_list(right)
                                for left, right in zip(single_rows, unrestricted_rows, strict=True))
                summary["budgets"][str(k)] = {
                    "single_anchor_ticket_hits": single_hits,
                    "unrestricted_ticket_hits_same_races": unrestricted_hits,
                    "single_anchor_conditional_completion": single_hits / axis_hits,
                    "same_ticket_lists": identical,
                    "selected_races": len(selected_ids),
                }
            expected = EXPECTED[(arm, cutoff)]
            require(summary["selected_races"] == expected["races"], f"cutoff race count mismatch: {arm} {cutoff}")
            require(summary["selected_dates"] == expected["dates"], f"cutoff date count mismatch: {arm} {cutoff}")
            require(years == expected["years"], f"cutoff year distribution mismatch: {arm} {cutoff}")
            require(axis_hits == expected["axis_hits"], f"cutoff axis hits mismatch: {arm} {cutoff}")
            require(summary["budgets"]["3"]["single_anchor_ticket_hits"] == expected["k3_single"],
                    f"single-anchor K3 hit mismatch: {arm} {cutoff}")
            require(summary["budgets"]["3"]["unrestricted_ticket_hits_same_races"] == expected["k3_unrestricted"],
                    f"unrestricted K3 hit mismatch: {arm} {cutoff}")
            require(summary["budgets"]["4"]["single_anchor_ticket_hits"] == expected["k4_single"],
                    f"single-anchor K4 hit mismatch: {arm} {cutoff}")
            require(summary["budgets"]["4"]["unrestricted_ticket_hits_same_races"] == expected["k4_unrestricted"],
                    f"unrestricted K4 hit mismatch: {arm} {cutoff}")
            if cutoff == 0.8:
                require(summary["budgets"]["3"]["same_ticket_lists"] == len(selected_ids),
                        f"K3 tickets differ inside .8 subset: {arm}")
                require(summary["budgets"]["4"]["same_ticket_lists"] == len(selected_ids),
                        f"K4 tickets differ inside .8 subset: {arm}")
            summaries.append(summary)

    receipt = {
        "study": "20261010_pair_axis_review_v1",
        "check": "frozen single-anchor confidence subsets versus unrestricted tickets",
        "passed": True,
        "selection_rule": "fixed saved single-anchor Top3-inclusion probability cutoff, >= cutoff",
        "same_race_comparator": "unrestricted top K selected on exactly the same race subset",
        "no_new_fit_or_selection": True,
        "cohort_is_retrospective_and_not_independent_future_validation": True,
        "pinned_hashes": actual_hashes,
        "main_validator_sha256": c_receipt["validator_sha256"],
        "supplement_validator_sha256": sha256(Path(__file__).resolve()),
        "results": summaries,
        "interpretation": (
            "At >=0.8, single-anchor and unrestricted ticket lists are identical in every selected race; "
            "the subset shows axis-success rates, not a ticket-policy change. At >=0.6, ticket lists "
            "differ in some races and hit-count differences are small. No future coverage or superiority is established."
        ),
    }
    out = OUTPUTS / "supplemental_fixed_cutoff_receipt.json"
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "receipt": str(out), "sha256": sha256(out)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

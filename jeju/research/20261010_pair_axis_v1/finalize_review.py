"""Freeze the supervisory receipt and a non-circular study manifest once reviews pass."""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
REVIEW = ROOT / "jeju/research/20261010_pair_axis_review_v1"
DESIGN = ROOT / "jeju/research/20261010_pair_axis_design_v1"


def metadata(path):
    data = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def save_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    assert not (STUDY / "ARTIFACT_MANIFEST.json").exists()
    original = json.loads((STUDY / "outputs/ARTIFACT_MANIFEST.json").read_text())
    for entry in original["outputs"].values():
        assert metadata(ROOT / entry["path"])["sha256"] == entry["sha256"]
    assert metadata(ROOT / original["analysis_code"]["path"])["sha256"] == original["analysis_code"]["sha256"]
    for path, expected in original["source_input_hashes"].items():
        assert metadata(ROOT / path)["sha256"] == expected
    for file, key in [("PLAN.md", "plan_sha256"), ("INPUT_CONTRACT.md", "input_contract_sha256"),
                      ("PRECOMPUTE_LOCK.json", "precompute_lock_sha256")]:
        assert metadata(STUDY / file)["sha256"] == original[key]
    independent = json.loads((REVIEW / "outputs/independent_validation_receipt.json").read_text())
    assert independent["independent_of_a_helpers"]
    assert independent["policy_count"] == 35580
    assert all(x["passed"] for x in independent["source_hashes_after"].values())
    assert independent["frozen_a_output_parity"]["selection_order_labels_and_axes_exact_match"]
    assert independent["validator_sha256"] == metadata(REVIEW / "independent_validation.py")["sha256"]
    metrics = pd.read_csv(STUDY / "outputs/per_race_metrics.csv")
    assert len(metrics) == 1779 * 22
    assert (metrics.ticket_count == metrics.budget_k).all()
    contrasts = pd.read_csv(STUDY / "outputs/primary_comparisons.csv")
    # C independently reconstructs the frozen four primary contrasts and full tickets.
    assert len(contrasts) == len(independent["primary_bootstrap"]) == 4
    assert all(x["ci95_low"] <= 0 <= x["ci95_high"] for x in independent["primary_bootstrap"])
    supplemental = REVIEW / "outputs/supplemental_fixed_cutoff_receipt.json"
    assert supplemental.exists(), "C selective-summary review must be frozen first"
    supplement = json.loads(supplemental.read_text())
    assert supplement["passed"] is True
    assert supplement["pinned_hashes"]["a_readme"] == metadata(STUDY / "README.md")["sha256"]
    assert supplement["supplement_validator_sha256"] == metadata(REVIEW / "supplemental_cutoff_validation.py")["sha256"]
    receipt = {
        "status": "PASS", "reviewer": "root", "workers": "GPT-6 Luna xhigh",
        "scope": "Existing frozen q selection policies; no new fit, DB or operational change",
        "cohort": {"races": 1779, "runner_starts": 17412, "dates": 269,
                   "period": ["2024-01-05", "2026-09-19"], "partial_2026": True},
        "reviewed": [metadata(STUDY / "README.md"), metadata(STUDY / "analyze.py"),
                     metadata(REVIEW / "outputs/independent_validation_receipt.json"),
                     metadata(supplemental)],
        "root_checks": ["Source-q independent spotchecks reproduced full-cohort axis and ticket counts",
                        "Fixed .6/.8 subsets reproduced independently from per-race metrics",
                        "Same-budget comparisons, conditional denominators and confidence coverage reviewed",
                        "Four primary date-cluster intervals include zero; improvement not established"],
        "interpretation": ["Two-axis success around 24% is the main pair bottleneck",
                           "Single-axis .8 subset has only about 3% coverage; its tickets equal unrestricted tickets",
                           "Unordered Top3 q does not identify exact Top2 or win probabilities",
                           "Repeated historical development cohort; no independent future validation",
                           "Dedicated axis or conditional-companion learning remains an untested next hypothesis"]}
    save_new(STUDY / "SUPERVISORY_REVIEW.json", receipt)
    external = [ROOT / p for p in original["source_input_hashes"]]
    external += [p for p in DESIGN.iterdir() if p.is_file()]
    external += [REVIEW / "independent_validation.py", REVIEW / "supplemental_cutoff_validation.py",
                 REVIEW / "REVIEW_MEMO.md", REVIEW / "outputs/independent_validation_receipt.json", supplemental]
    local = [p for p in STUDY.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    manifest = {"study": STUDY.name, "status": "reviewed_no_fit_exploratory",
                "local_files": [metadata(p) for p in sorted(local)],
                "external_references": [metadata(p) for p in sorted(set(external))],
                "notes": "The original outputs manifest and frozen contracts are preserved byte-for-byte; this manifest excludes itself."}
    save_new(STUDY / "ARTIFACT_MANIFEST.json", manifest)
    print(json.dumps({"status": "PASS", "manifest": metadata(STUDY / "ARTIFACT_MANIFEST.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

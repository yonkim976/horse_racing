"""No-fit recovery path: report only from saved immutable parameters and tau."""
from __future__ import annotations

import json

import joint_model as jm
from report import run_report


def main() -> None:
    parameters_path = jm.OUT / "fit_parameters.json"
    receipt_path = jm.OUT / "fit_receipt.json"
    if not parameters_path.is_file() or not receipt_path.is_file():
        raise FileNotFoundError("no completed immutable fit artifact exists; finalizer never fits")
    parameters = jm.load_json(parameters_path)
    receipt = jm.load_json(receipt_path)
    if not receipt.get("passed") or receipt.get("parameters_sha256") != jm.sha256(parameters_path):
        raise AssertionError("fit artifact/receipt mismatch; refusing report recovery")
    target = jm.OUT / "final_report"
    result = run_report(target)
    print(json.dumps({"mode": "no-fit-report-recovery", "report": result},
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

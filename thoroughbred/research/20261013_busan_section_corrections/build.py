"""Apply the frozen Seoul shrinkage and cap algorithm to Busan estimates."""

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    analysis = module("busan_build_analysis", HERE / "analyze.py")
    builder = module("frozen_section_builder", analysis.SEOUL / "build.py")
    builder.OUT, builder.S = OUT, analysis
    builder.main()
    path = OUT / "candidate_policy.json"
    policy = json.loads(path.read_text())
    policy["available_from"] = "2026-10-13"
    policy["frozen_algorithm"] = str((analysis.SEOUL / "build.py").relative_to(analysis.ROOT))
    policy["adopted_finish_moisture_changed"] = False
    analysis.dump(path, policy)


if __name__ == "__main__":
    main()

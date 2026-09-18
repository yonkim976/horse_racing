"""Export actual input dimensions and descriptive normalized split gains."""

import json
import pickle
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data/research/jeju_native_h3_experiment_v3_20260916"


def main():
    gains = defaultdict(lambda: defaultdict(float))
    members = defaultdict(int)
    dimensions = defaultdict(list)
    for path in sorted((OUT / "bundles").glob("*.pkl")):
        with path.open("rb") as handle:
            bundle = pickle.load(handle)
        name = bundle["model_name"]
        dimensions[name].append(len(bundle["preprocessor"].names))
        for model in bundle["models"]:
            gain = model.booster_.feature_importance(importance_type="gain")
            total = max(float(gain.sum()), 1e-20)
            members[name] += 1
            for feature, value in zip(bundle["preprocessor"].names, gain, strict=True):
                gains[name][feature] += float(value) / total
    result = {
        name: [
            {"feature": feature, "mean_normalized_gain": value / members[name]}
            for feature, value in sorted(values.items(), key=lambda item: -item[1])
        ]
        for name, values in gains.items()
    }
    for filename, obj in [
        ("feature_importance.json", result),
        ("feature_dimensions.json", dict(dimensions)),
    ]:
        (OUT / filename).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

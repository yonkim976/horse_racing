"""Build conservative, additive direct-section trial factors; retain unknowns."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("seoul_direct_analysis", HERE / "analyze.py")
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
KEYS = ["distance_m", "scope", "period", "variant", "family", "block", "level", "section"]


def cap(section, family, scope):
    if family == "moisture":
        return 1.5 if section == "finish" else np.inf
    if section == "finish":
        return 0.12 if family == "month" else 0.15
    limits = {
        "early": (0.03, 0.05),
        "middle1": (0.12, 0.12),
        "middle2": (0.06, 0.08),
        "late": (0.03, 0.04),
    }
    if section in limits:
        return limits[section][0 if family == "month" else 1]
    if "_to_" in section:
        return 0.06 if family == "month" else 0.08
    return np.inf


def main():
    _, data = S.load()
    p = pd.read_csv(OUT / "effect_profiles.csv", dtype={"level": str})
    models = json.loads((OUT / "models.json").read_text())
    lookup = []
    for model in models:
        meta = {k: model[k] for k in ["distance_m", "scope", "period", "variant"]}
        q = p[p.matrix_key.eq(int(model["matrix_key"]))]
        s = S.sample(
            data, **{k: meta[k] for k in ["scope", "period", "variant"]}, dist=meta["distance_m"]
        )
        for (family, block), g in q.groupby(["family", "block"], observed=True):
            sections = model["parts"]
            levels = sorted(
                g.level.unique(), key=lambda v: (not v.isdigit(), int(v) if v.isdigit() else v)
            )
            effects = g.pivot(index="level", columns="section", values="effect_seconds").reindex(
                index=levels, columns=sections
            )
            support = (
                g.pivot(index="level", columns="section", values="supported")
                .reindex(index=levels, columns=sections)
                .fillna(False)
            )
            counts = []
            for level in levels:
                if family == "month":
                    count = int(s.month.eq(int(level)).sum())
                elif family in ["number", "group"]:
                    b = s[s.gate_block.eq(block)]
                    count = int(
                        (
                            b.horse_number.eq(int(level))
                            if family == "number"
                            else b.gate_side.eq(level)
                        ).sum()
                    )
                else:
                    detail = json.loads(g[g.level.eq(level)].iloc[0].support)
                    count = min(z["races"] for z in detail)
                counts.append(count)
            counts = np.array(counts, float)
            raw = effects.to_numpy(float)
            available = support.all(axis=1).to_numpy() & np.isfinite(raw).all(axis=1)
            fraction = 0.4 if family == "moisture" else 0.3
            factors = fraction * counts / (counts + 100)
            additions = -factors[:, None] * raw
            common_scale = np.ones(len(levels))
            if family != "moisture":
                required = (
                    len(levels) == 12
                    if family == "month"
                    else len(levels) == (int(block[5:]) if family == "number" else 3)
                )
                available[:] = bool(required and available.all())
                if available.all():
                    shares = (
                        np.ones(len(levels)) / len(levels)
                        if family == "month"
                        else counts / counts.sum()
                    )
                    additions -= shares @ additions
                    scale = min(
                        [
                            1.0,
                            *[
                                cap(part, family, meta["scope"])
                                / max(float(abs(additions[:, j]).max()), 1e-15)
                                for j, part in enumerate(sections)
                            ],
                        ]
                    )
                    additions *= scale
                    common_scale[:] = scale
            else:
                for i in range(len(levels)):
                    if available[i]:
                        scale = min(
                            [
                                1.0,
                                *[
                                    cap(part, family, meta["scope"])
                                    / max(abs(additions[i, j]), 1e-15)
                                    for j, part in enumerate(sections)
                                ],
                            ]
                        )
                        additions[i] *= scale
                        common_scale[i] = scale
            for i, level in enumerate(levels):
                for j, section in enumerate(sections):
                    source = g[g.level.eq(level) & g.section.eq(section)].iloc[0]
                    lookup.append(
                        meta
                        | dict(
                            family=family,
                            block=block,
                            level=level,
                            section=section,
                            length_m=S.core_length(meta["distance_m"], section),
                            available=bool(available[i]),
                            add_seconds=float(additions[i, j]) if available[i] else None,
                            n=int(counts[i]),
                            fraction=fraction,
                            shrink_factor=float(factors[i]),
                            cap_scale=float(common_scale[i]),
                            effect_seconds=source.effect_seconds,
                            ci_low=source.ci_low,
                            ci_high=source.ci_high,
                            q=source.q,
                            signal_supported=bool(source.supported),
                            status="trial_only",
                        )
                    )
    frame = pd.DataFrame(lookup)
    assert not frame.duplicated(KEYS).any()
    frame.to_csv(OUT / "correction_components.csv", index=False)
    primary = frame[frame.variant.eq("tail25") & frame.period.eq("all_mad4")]
    primary[primary.family.eq("moisture")].to_csv(OUT / "moisture_primary.csv", index=False)
    ranges = []
    for key, g in frame.groupby(["distance_m", "scope", "period", "variant", "family", "section"]):
        z = g[g.available]
        ranges.append(
            dict(
                zip(
                    ["distance_m", "scope", "period", "variant", "family", "section"],
                    key,
                    strict=True,
                )
            )
            | dict(
                available_levels=len(z),
                min_add=z.add_seconds.min(),
                max_add=z.add_seconds.max(),
            )
        )
    pd.DataFrame(ranges).to_csv(OUT / "component_ranges.csv", index=False)
    # Join both variants on all identities except variant.
    identities = [k for k in KEYS if k != "variant"]
    before = frame[frame.variant.eq("baseline")][
        identities + ["add_seconds", "effect_seconds", "available"]
    ]
    change = frame[frame.variant.eq("tail25")].merge(
        before, on=identities, validate="one_to_one", suffixes=("", "_baseline")
    )
    change["effect_change"] = change.effect_seconds - change.effect_seconds_baseline
    change["candidate_change"] = change.add_seconds - change.add_seconds_baseline
    change.to_csv(OUT / "tail_sensitivity.csv", index=False)
    S.dump(
        OUT / "candidate_policy.json",
        dict(
            available_from="2026-10-11",
            status="trial_only",
            main_variant="tail25",
            sign="normalized_seconds = observed_seconds + add_seconds",
            moisture_fraction=0.4,
            month_fraction=0.3,
            gate_fraction=0.3,
            shrink_k=100,
            moisture_reference=(
                "fixed race-equal numeric mix vs dry; same mix in baseline and tail25"
            ),
            month_reference="equal 12-month mean; centered after shrink",
            gate_reference=(
                "runner-exposure weighted mean in original roster block; centered after shrink"
            ),
            unsupported="null, never zero",
            state_gate_interaction=False,
            lateral_included=False,
            adopted_finish_moisture_changed=False,
            prediction_validation=False,
        ),
    )
    print("candidate components", len(frame), "available", int(frame.available.sum()))


if __name__ == "__main__":
    main()

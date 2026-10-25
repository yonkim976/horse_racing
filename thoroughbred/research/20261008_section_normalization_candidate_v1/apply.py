"""Trial sectional normalization with explicit overlap and whole-time identities."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PREV = HERE.parent / "20261008_gate_model_candidate_v1"
SPEC = importlib.util.spec_from_file_location("whole_apply", PREV / "apply.py")
W = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(W)
PARTS = ["early", "last600", "late"]
KEYS = W.KEYS + ["section"]


class SectionNormalizer:
    def __init__(self, directory=None):
        directory = Path(directory).resolve() if directory is not None else HERE / "outputs"
        if not directory.is_relative_to(HERE):
            raise ValueError("artifact directory must be inside this study folder")
        self.config = json.loads((directory / "config.json").read_text())
        self.whole = W.Normalizer()
        self.gates = pd.read_csv(directory / "section_gate_lookup.csv", dtype={"level": str})
        self.gate_index = self.gates.set_index(KEYS, verify_integrity=True)
        self.month = pd.read_csv(directory / "section_month_lookup.csv").set_index(
            ["meet", "distance_m", "section", "period", "month"], verify_integrity=True
        )
        self.moisture = pd.read_csv(directory / "section_moisture_reference.csv").set_index(
            ["meet", "distance_m", "section", "band"], verify_integrity=True
        )

    def normalize_record(self, *, early, last600, late, **kwargs):
        values = np.array([early, last600, late], float)
        finish = kwargs["finish"]
        if not np.isfinite(values).all() or not (
            early > 0 and last600 > late > 0 and finish > early + last600
        ):
            raise ValueError("section times must be finite, positive and consistent with finish")
        whole = self.whole.normalize_record(**kwargs)
        meet = kwargs["meet"]
        dist = kwargs["distance"]
        n = len(kwargs["roster"])
        band = whole["band"]
        month = pd.Timestamp(kwargs["record_date"]).month
        components = {}
        for part, raw in zip(PARTS, values, strict=True):
            key = (meet, dist, n, whole["gate_mode"], band, "all_mad4", whole["gate_level"], part)
            gate = 0.0
            status = "neutral_unavailable"
            if key in self.gate_index.index:
                r = self.gate_index.loc[key]
                gate = float(r.gate_add_seconds) * whole["gate_strength"]
                status = r.status
            mk = (meet, dist, part, "all_mad4", month)
            month_add = (
                float(self.month.loc[mk, "month_add_seconds"])
                if whole["month_enabled"] and mk in self.month.index
                else 0.0
            )
            sk = (meet, dist, part, band)
            moist = None
            if sk in self.moisture.index:
                r = self.moisture.loc[sk]
                if r.supported:
                    moist = float(r.moisture_add_seconds)
            total = None if moist is None else moist + month_add + gate
            components[part] = dict(
                raw=float(raw),
                moisture=moist,
                month=month_add,
                gate=gate,
                total_add=total,
                candidate=None if total is None else float(raw + total),
                method="direct_target",
                gate_status=status,
            )
        components["finish"] = dict(
            raw=float(finish),
            moisture=whole["moisture_add_seconds"],
            month=whole["month_add_seconds"],
            gate=whole["applied_gate_seconds"],
            total_add=whole["total_add_seconds"],
            candidate=whole["normalized_finish"],
            method="whole_time_v1_preserved",
        )
        for part, left, right, raw in [
            ("middle1", "finish", "early", finish - early - last600),
            ("middle2", "last600", "late", last600 - late),
        ]:
            c = dict(raw=float(raw), method="identity_residual")
            for name in ["moisture", "month", "gate", "total_add"]:
                operands = [components[left][name], components[right][name]] + (
                    [components["last600"][name]] if part == "middle1" else []
                )
                c[name] = (
                    None
                    if any(v is None for v in operands)
                    else float(operands[0] - sum(operands[1:]))
                )
            c["candidate"] = None if c["total_add"] is None else float(raw + c["total_add"])
            components[part] = c
        return dict(
            version=self.config["version"],
            status="trial_only",
            parts=components,
            as_of=whole["as_of"],
            month_enabled=whole["month_enabled"],
            complete_core=all(
                components[p]["candidate"] is not None
                for p in ["early", "middle1", "middle2", "late", "finish"]
            ),
        )

    def apply_population(self, population, as_of):
        d = self.whole.apply_population(population, as_of)
        d = d.merge(
            population[["row_key", "early", "middle1", "middle2", "late", "last600"]],
            on="row_key",
            validate="one_to_one",
        )
        for part in PARTS:
            gate = self.gates[self.gates.section.eq(part)][
                W.KEYS + ["gate_add_seconds", "status"]
            ].rename(
                columns={"gate_add_seconds": f"{part}_gate_add", "status": f"{part}_gate_status"}
            )
            d = d.merge(gate, on=W.KEYS, how="left", validate="many_to_one")
            d[f"{part}_gate_add"] = d[f"{part}_gate_add"].fillna(0.0)
            d[f"{part}_gate_status"] = d[f"{part}_gate_status"].fillna("neutral_unavailable")
            moist = self.moisture.reset_index()
            moist = moist[moist.section.eq(part)][
                ["meet", "distance_m", "band", "moisture_add_seconds"]
            ].rename(columns={"moisture_add_seconds": f"{part}_moisture_add"})
            d = d.merge(
                moist, on=["meet", "distance_m", "band"], how="left", validate="many_to_one"
            )
            month = self.month.reset_index()
            month = month[month.section.eq(part) & month.period.eq("all_mad4")][
                ["meet", "distance_m", "month", "month_add_seconds"]
            ].rename(columns={"month_add_seconds": f"{part}_month_add"})
            d = d.merge(
                month, on=["meet", "distance_m", "month"], how="left", validate="many_to_one"
            )
            d[f"{part}_month_add"] = d[f"{part}_month_add"].fillna(0.0)
            d[f"{part}_add"] = d[f"{part}_moisture_add"] + d[f"{part}_gate_add"]
            d[f"{part}_with_month_add"] = d[f"{part}_add"] + d[f"{part}_month_add"]
            d[f"{part}_candidate"] = d[part] + d[f"{part}_add"]
            d[f"{part}_with_month_candidate"] = d[part] + d[f"{part}_with_month_add"]
        for component, wholecol in [
            ("moisture", "moisture_add_seconds"),
            ("month", "month_candidate_add"),
            ("gate", "gate_add_seconds"),
        ]:
            d[f"middle1_{component}_add"] = (
                d[wholecol] - d[f"early_{component}_add"] - d[f"last600_{component}_add"]
            )
            d[f"middle2_{component}_add"] = (
                d[f"last600_{component}_add"] - d[f"late_{component}_add"]
            )
        for part in ["middle1", "middle2"]:
            d[f"{part}_add"] = d[f"{part}_moisture_add"] + d[f"{part}_gate_add"]
            d[f"{part}_with_month_add"] = d[f"{part}_add"] + d[f"{part}_month_add"]
            d[f"{part}_candidate"] = d[part] + d[f"{part}_add"]
            d[f"{part}_with_month_candidate"] = d[part] + d[f"{part}_with_month_add"]
        d["section_version"] = self.config["version"]
        return d

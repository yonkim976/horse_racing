"""Local trial-only finish-time normalization; caller supplies the full starter roster."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

KEYS = ["meet", "distance_m", "field_size", "mode", "band", "period", "level"]
BANDS = ["건조", "양호", "다습", "포화", "불량"]


def integer(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def band_for(moisture):
    if (
        isinstance(moisture, (bool, np.bool_))
        or not np.isfinite(moisture)
        or not 0 < moisture <= 100
    ):
        raise ValueError("moisture must be finite and in (0,100]")
    return BANDS[
        0
        if moisture <= 5
        else 1
        if moisture <= 9
        else 2
        if moisture <= 14
        else 3
        if moisture <= 19
        else 4
    ]


class Normalizer:
    def __init__(self, directory=None):
        here = Path(__file__).resolve().parent
        directory = Path(directory).resolve() if directory is not None else here / "outputs"
        # Only this workspace's generated artifacts are accepted by this local helper.
        if not directory.is_relative_to(here):
            raise ValueError("artifact directory must be inside this study folder")
        self.config = json.loads((directory / "config.json").read_text())
        self.lookup = pd.read_csv(directory / "gate_correction_lookup.csv", dtype={"level": str})
        self.index = self.lookup.set_index(KEYS, verify_integrity=True)
        self.moisture = pd.read_csv(directory / "moisture_reference.csv").set_index(
            ["meet", "distance_m", "band"], verify_integrity=True
        )
        self.month = pd.read_csv(directory / "month_candidate_reference.csv").set_index(
            ["meet", "distance_m", "month"], verify_integrity=True
        )

    def check_asof(self, as_of):
        when = pd.Timestamp(as_of)
        if pd.isna(when) or when.tz is not None:
            raise ValueError("as_of must be a timezone-naive calendar date")
        if when < pd.Timestamp(self.config["available_from"]):
            raise ValueError(
                "this fixed version did not exist before available_from; refit an as-of version"
            )
        return when

    def gate(self, meet, distance, band, roster, horse_number, period="all_mad4"):
        if meet not in ["서울", "부산"] or band not in BANDS:
            raise ValueError("unsupported venue or moisture band")
        distance = integer(distance, "distance")
        horse_number = integer(horse_number, "horse_number")
        roster = [integer(i, "roster entry") for i in roster]
        if not roster or len(set(roster)) != len(roster) or horse_number not in roster:
            raise ValueError(
                "roster must contain unique starter program numbers, including the horse"
            )
        if period not in ["all_mad4", "recent_mad4"]:
            raise ValueError("unknown period")
        n = len(roster)
        ordered = sorted(roster)
        ordinal = ordered.index(horse_number) + 1
        mode = "number" if n in [10, 12] and ordered == list(range(1, n + 1)) else "group"
        level = (
            str(horse_number)
            if mode == "number"
            else ["inner", "middle", "outer"][min(int(3 * (ordinal - 0.5) / n), 2)]
        )
        key = (meet, distance, n, mode, band, period, level)
        if key not in self.index.index:
            return dict(
                gate_add_seconds=0.0,
                base_add_seconds=0.0,
                state_add_seconds=0.0,
                gate_status="neutral_unavailable",
                gate_mode=mode,
                gate_level=level,
                gate_period=period,
            )
        r = self.index.loc[key]
        return dict(
            gate_add_seconds=float(r.gate_add_seconds),
            base_add_seconds=float(r.base_add_seconds),
            state_add_seconds=float(r.state_add_seconds),
            gate_status=r.status,
            gate_mode=mode,
            gate_level=level,
            gate_period=period,
        )

    def normalize_record(
        self,
        *,
        meet,
        distance,
        finish,
        moisture,
        record_date,
        horse_number,
        roster,
        as_of,
        include_month=False,
        gate_strength=1.0,
    ):
        when = self.check_asof(as_of)
        date = pd.Timestamp(record_date)
        if pd.isna(date) or date.tz is not None or date > when:
            raise ValueError("record_date must be a completed calendar date at or before as_of")
        if isinstance(finish, (bool, np.bool_)) or not np.isfinite(finish) or finish <= 0:
            raise ValueError("finish must be finite and positive")
        if not np.isfinite(gate_strength) or not 0 <= gate_strength <= 1:
            raise ValueError("gate_strength must be in [0,1]")
        band = band_for(moisture)
        gate = self.gate(meet, distance, band, roster, horse_number)
        key = (meet, distance, band)
        moisture_add = None
        if key in self.moisture.index:
            r = self.moisture.loc[key]
            if r.adopted_supported:
                moisture_add = float(r.add_seconds_conservative)
        monthkey = (meet, distance, date.month)
        month_available = monthkey in self.month.index
        month_add = (
            float(self.month.loc[monthkey, "month_candidate_add"])
            if include_month and month_available
            else 0.0
        )
        applied_gate = gate_strength * gate["gate_add_seconds"]
        total = None if moisture_add is None else moisture_add + month_add + applied_gate
        return dict(
            raw_finish=float(finish),
            band=band,
            moisture_add_seconds=moisture_add,
            moisture_supported=moisture_add is not None,
            month_add_seconds=month_add,
            month_candidate_available=month_available,
            month_enabled=include_month,
            **gate,
            gate_strength=float(gate_strength),
            applied_gate_seconds=applied_gate,
            total_add_seconds=total,
            normalized_finish=None if total is None else float(finish + total),
            status="trial_only",
            version=self.config["version"],
            as_of=str(when.date()),
            record_date=str(date.date()),
        )

    def apply_population(self, population, as_of):
        self.check_asof(as_of)
        columns = [
            "row_key",
            "race_key",
            "meet",
            "distance_m",
            "date",
            "month",
            "horse_id",
            "horse_number",
            "n",
            "gate_side",
            "gate_block",
            "band",
            "finish",
        ]
        d = population[columns].copy()
        d["field_size"] = d.n
        d["mode"] = np.where(d.gate_block.str.startswith("exact"), "number", "group")
        d["level"] = np.where(
            d["mode"].eq("number"), d.horse_number.astype(str), d.gate_side.astype(str)
        )
        d["period"] = "all_mad4"
        selected = self.lookup[
            KEYS + ["gate_add_seconds", "base_add_seconds", "state_add_seconds", "status"]
        ].rename(columns={"status": "gate_status"})
        d = d.merge(selected, on=KEYS, how="left", validate="many_to_one")
        d["gate_status"] = d.gate_status.fillna("neutral_unavailable")
        for name in ["gate_add_seconds", "base_add_seconds", "state_add_seconds"]:
            d[name] = d[name].fillna(0.0)
        moist = self.moisture.reset_index()[
            ["meet", "distance_m", "band", "adopted_supported", "add_seconds_conservative"]
        ]
        d = d.merge(moist, on=["meet", "distance_m", "band"], how="left", validate="many_to_one")
        d["moisture_supported"] = d.adopted_supported.fillna(False).astype(bool)
        d["moisture_add_seconds"] = d.add_seconds_conservative.where(d.moisture_supported)
        d = d.merge(
            self.month.reset_index(),
            on=["meet", "distance_m", "month"],
            how="left",
            validate="many_to_one",
        )
        d["month_candidate_available"] = d.month_candidate_add.notna()
        d["month_candidate_add"] = d.month_candidate_add.fillna(0.0)
        d["moisture_only_finish"] = d.finish + d.moisture_add_seconds
        d["moisture_gate_finish"] = d.moisture_only_finish + d.gate_add_seconds
        d["moisture_month_gate_finish"] = d.moisture_gate_finish + d.month_candidate_add
        d["version"] = self.config["version"]
        d["as_of"] = as_of
        d["retrospective_snapshot"] = True
        return d.drop(columns=["adopted_supported", "add_seconds_conservative"])

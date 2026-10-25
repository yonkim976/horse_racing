"""Read-only research lookup for completed records; lateral position is never an input."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
KEYS = [
    "meet",
    "distance_m",
    "field_size",
    "mode",
    "block",
    "band",
    "period",
    "level",
    "month",
    "target",
]
TARGETS = ["finish", "early", "last600", "late", "middle1", "middle2"]


def integer(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


class EnvironmentAtlas:
    def __init__(self, directory=None):
        directory = Path(directory).resolve() if directory is not None else HERE / "outputs"
        if not directory.is_relative_to(HERE):
            raise ValueError("artifact directory must be inside this study folder")
        self.config = json.loads((directory / "config.json").read_text())
        self.table = pd.read_parquet(directory / "combined_correction_lookup.parquet")
        self.index = self.table.set_index(KEYS, verify_integrity=True)

    def lookup(
        self,
        *,
        meet,
        distance,
        moisture,
        month,
        horse_number,
        roster,
        as_of,
        target="finish",
        period="all_mad4",
    ):
        when = pd.Timestamp(as_of)
        if (
            pd.isna(when)
            or when.tz is not None
            or when < pd.Timestamp(self.config["available_from"])
        ):
            raise ValueError(
                "fixed atlas is only available from its publication date; refit older versions"
            )
        if (
            meet not in ["서울", "부산"]
            or target not in TARGETS
            or period not in self.config["periods"]
        ):
            raise ValueError("unknown venue, target or coefficient period")
        distance = integer(distance, "distance")
        month = integer(month, "month")
        horse_number = integer(horse_number, "horse_number")
        if month > 12:
            raise ValueError("month must be in 1..12")
        if (
            isinstance(moisture, (bool, np.bool_))
            or not isinstance(moisture, (int, float, np.integer, np.floating))
            or not np.isfinite(moisture)
            or not 0 < moisture <= 100
        ):
            raise ValueError("moisture must be finite and in (0,100]")
        band = ["건조", "양호", "다습", "포화", "불량"][
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
        numbers = sorted(integer(value, "starter") for value in roster)
        if not numbers or len(set(numbers)) != len(numbers) or horse_number not in numbers:
            raise ValueError("supply the unique original full starter roster including this horse")
        n = len(numbers)
        exact = n in [10, 12] and numbers == list(range(1, n + 1))
        mode = "number" if exact else "group"
        block = (
            "exact" + str(n)
            if exact
            else "other_" + ("6to9" if n <= 9 else str(n) if n <= 12 else "13plus")
        )
        level = (
            str(horse_number)
            if exact
            else ["inner", "middle", "outer"][
                min(int(3 * (numbers.index(horse_number) + 0.5) / n), 2)
            ]
        )
        key = (meet, distance, n, mode, block, band, period, level, month, target)
        result = dict(
            meet=meet,
            distance=distance,
            band=band,
            month=month,
            field_size=n,
            gate_mode=mode,
            gate_level=level,
            target=target,
            coefficient_period=period,
            version=self.config["version"],
            status="trial_only",
            lateral_included=False,
        )
        if key not in self.index.index:
            return result | dict(
                moisture=None,
                month_add=None,
                gate=None,
                total_add=None,
                partial_add=None,
                symbol="?",
                complete=False,
                method="unavailable",
                gate_status="unavailable",
            )
        row = self.index.loc[key]

        def optional(name):
            value = row[name]
            return None if pd.isna(value) else float(value)

        return result | dict(
            moisture=optional("moisture_add_seconds"),
            month_add=optional("month_add_seconds"),
            gate=optional("gate_add_seconds"),
            total_add=optional("total_add_seconds"),
            partial_add=optional("partial_add_seconds"),
            symbol=row.symbol,
            complete=bool(row.complete),
            method=row.method,
            gate_status=row.gate_status,
            moisture_adopted=bool(row.adopted_moisture),
            month_source=row.source,
        )

    def normalize_record(self, *, finish, early, last600, late, record_date, **kwargs):
        date, when = pd.Timestamp(record_date), pd.Timestamp(kwargs["as_of"])
        if pd.isna(date) or date.tz is not None or date > when:
            raise ValueError("record_date must be completed and at or before as_of")
        raw = np.array([finish, early, last600, late], float)
        if not np.isfinite(raw).all() or not (
            finish > early + last600 and early > 0 and last600 > late > 0
        ):
            raise ValueError("raw section times must be finite, positive and consistent")
        values = dict(
            finish=finish,
            early=early,
            last600=last600,
            late=late,
            middle1=finish - early - last600,
            middle2=last600 - late,
        )
        parts = {}
        for target, value in values.items():
            result = self.lookup(target=target, month=int(date.month), **kwargs)
            result["raw"] = float(value)
            result["candidate"] = (
                None if result["total_add"] is None else float(value + result["total_add"])
            )
            parts[target] = result
        return dict(
            version=self.config["version"],
            status="trial_only",
            parts=parts,
            lateral_included=False,
            complete=all(p["complete"] for p in parts.values()),
        )

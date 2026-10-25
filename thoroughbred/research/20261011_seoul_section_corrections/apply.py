"""Read-only component lookup for Seoul research candidates."""

from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


class SeoulSections:
    def __init__(self):
        self.factors = pd.read_csv(HERE / "outputs/correction_components.csv", dtype={"level": str})

    def lookup(
        self,
        *,
        distance,
        moisture,
        month,
        horse_number,
        roster,
        as_of,
        scope="core",
        period="all_mad4",
        variant="tail25",
    ):
        if date.fromisoformat(as_of) < date(2026, 10, 11):
            raise ValueError("This retrospective artifact was not available before 2026-10-11")
        if (
            scope not in {"core", "corner"}
            or period not in {"all_mad4", "recent_mad4"}
            or variant not in {"baseline", "tail25"}
        ):
            raise ValueError("Unknown scope, period or filter")
        if any(
            isinstance(x, bool) or not isinstance(x, int)
            for x in [distance, moisture, month, horse_number, *roster]
        ):
            raise ValueError("Identifiers and measurements must be integers")
        if not 1 <= moisture <= 20 or not 1 <= month <= 12:
            raise ValueError("Invalid moisture or month")
        if (
            not 6 <= len(roster) <= 16
            or len(set(roster)) != len(roster)
            or min(roster) < 1
            or horse_number not in roster
        ):
            raise ValueError(
                "Use the complete original starting roster with unique positive numbers"
            )
        n = len(roster)
        if n in {10, 12} and set(roster) == set(range(1, n + 1)):
            block, family, level = f"exact{n}", "number", str(horse_number)
        else:
            block = "other_" + ("6to9" if n <= 9 else str(n) if n <= 12 else "13plus")
            family = "group"
            p = (sorted(roster).index(horse_number) + 0.5) / n
            level = ["inner", "middle", "outer"][min(int(3 * p), 2)]
        band = (
            "건조"
            if moisture <= 5
            else "양호"
            if moisture <= 9
            else "다습"
            if moisture <= 14
            else "포화"
            if moisture <= 19
            else "불량"
        )
        q = self.factors
        q = q[
            q.distance_m.eq(distance)
            & q.scope.eq(scope)
            & q.period.eq(period)
            & q.variant.eq(variant)
        ]
        result = {}
        for section, s in q.groupby("section"):
            identities = [
                ("moisture", "fixed_band_mix", band),
                ("month", "annual", str(month)),
                (family, block, level),
            ]
            terms = {}
            for name, (fam, blk, lv) in zip(["moisture", "month", "gate"], identities, strict=True):
                f = s[s.family.eq(fam) & s.block.eq(blk) & s.level.eq(lv)]
                terms[name] = (
                    float(f.iloc[0].add_seconds) if len(f) == 1 and f.iloc[0].available else None
                )
            complete = all(v is not None for v in terms.values())
            result[section] = dict(
                components=terms,
                complete=complete,
                total_add_seconds=sum(terms.values()) if complete else None,
            )
        return dict(
            distance_m=distance,
            scope=scope,
            band=band,
            month=month,
            gate_block=block,
            gate_family=family,
            gate_level=level,
            period=period,
            variant=variant,
            status="trial_only",
            sections=result,
        )

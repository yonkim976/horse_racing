"""Declared entry-card conditions and strictly lagged people history."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import polars as pl

HEADING = re.compile(
    r"(?:제목\s*:\s*|경주일\s*:\s*|;TI\s*).*?(20\d\d|\d\d)[.년\s]+(\d{1,2})[.월\s]+(\d{1,2}).*?(?:제\s*0*(\d+)\s*경주|(\d+)\s*경주)"
)
ROW = re.compile(
    r"^\s*(\d{1,2})\s+(\S+)\s+([제한래산검])\s+([수암거])\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\d+(?:\.\d+)?))?\s*$"
)
BASE_FEATURES = [
    "card_observed",
    "declared_horse_number",
    "declared_age",
    "declared_female",
    "declared_gelded",
    "declared_burden_kg",
    "declared_rating",
    "declared_grade_number",
    "declared_jockey_allowance_kg",
    "jockey_history_starts",
    "jockey_history_win_rate",
    "jockey_history_top3_rate",
    "trainer_history_starts",
    "trainer_history_win_rate",
    "trainer_history_top3_rate",
    "horse_jockey_history_starts",
    "horse_jockey_history_top3_rate",
    "jockey_identity_history_known",
    "trainer_identity_history_known",
]
RELATIVE_SOURCES = [
    "global_elo_pre",
    "distance_elo_pre",
    "speed_residual_mean_pre",
    "declared_rating",
    "declared_burden_kg",
    "declared_age",
    "jockey_history_top3_rate",
]
RELATIVE_FEATURES = [f"{x}__race_centered" for x in RELATIVE_SOURCES] + [
    f"{x}__race_percentile" for x in RELATIVE_SOURCES
]


def parse_card(lines):
    """Parse only declared runner rows; preserve header semantics and line numbers."""
    current = None
    grade = None
    rating_header = False
    distance = None
    result = []
    for number, line in enumerate(lines, 1):
        heading = HEADING.search(line)
        if heading:
            y, m, d, r1, r2 = heading.groups()
            year = int(y) + (2000 if len(y) == 2 else 0)
            current = (date(year, int(m), int(d)), int(r1 or r2))
            grade = None
            rating_header = False
            distance = None
        if current is None:
            continue
        if re.search(r"(?:출전|출주)\s*:", line):
            g = re.search(r"제\s*([1-6])\s*등급", line)
            grade = int(g.group(1)) if g else None
            dist = re.match(r"\s*(\d+)\s*M", line)
            distance = int(dist.group(1)) if dist else None
        if "마번" in line and "마" in line and ("기  수" in line or "기수" in line):
            rating_header = "레이팅" in line
        match = ROW.match(line)
        if not match:
            continue
        num, name, breed, sex, age, burden, jockey, trainer, owner, tail = match.groups()
        allowance = re.match(r"^\(-([0-9]+)\)(.+)$", jockey)
        raw_jockey = jockey
        if allowance:
            jockey = allowance.group(2)
        result.append(
            {
                "event_date": current[0],
                "event_number": current[1],
                "horse_number": int(num),
                "horse_name": name,
                "breed": breed,
                "age": int(age),
                "sex": sex,
                "burden": float(burden),
                "jockey_name": jockey,
                "jockey_raw": raw_jockey,
                "trainer_name": trainer,
                "rating": float(tail) if tail is not None and rating_header else None,
                "grade": grade,
                "distance": distance,
                "allowance": float(allowance.group(1)) if allowance else 0.0,
                "line_number": number,
            }
        )
    return result


def add_people_history(targets, history):
    """Past actual participants update identity-resolved statistics at date-2d.

    Name to official ID mappings are learned only from available historical
    rows. Ambiguous names receive an unknown state, not merged identities.
    """
    histories = sorted(history, key=lambda x: x["event_date"])
    names = {"jockey": defaultdict(set), "trainer": defaultdict(set)}
    stats = {"jockey": defaultdict(lambda: [0, 0, 0]), "trainer": defaultdict(lambda: [0, 0, 0])}
    pairs = defaultdict(lambda: [0, 0, 0])
    cursor = 0
    output = []
    for target in sorted(targets, key=lambda x: (x["event_date"], x["entry_id"])):
        limit = target["event_date"] - timedelta(days=2)
        while cursor < len(histories) and histories[cursor]["event_date"] <= limit:
            h = histories[cursor]
            cursor += 1
            for who in ["jockey", "trainer"]:
                name = h.get(who + "_name")
                identity = h.get(who + "_id")
                if not name or not identity:
                    continue
                names[who][name].add(identity)
                st = stats[who][identity]
                st[0] += 1
                st[1] += h["win"]
                st[2] += h["top3"]
                if who == "jockey":
                    st = pairs[(h["horse_id"], identity)]
                    st[0] += 1
                    st[1] += h["win"]
                    st[2] += h["top3"]
        row = dict(target)
        for who in ["jockey", "trainer"]:
            identities = names[who].get(target.get(who + "_name"), set())
            known = len(identities) == 1
            identity = next(iter(identities)) if known else None
            n, w, t = stats[who][identity] if known else (0, 0, 0)
            row[who + "_identity_history_known"] = int(known)
            row[who + "_history_starts"] = n
            row[who + "_history_win_rate"] = (w + 2) / (n + 20)
            row[who + "_history_top3_rate"] = (t + 6) / (n + 20)
            if who == "jockey":
                pn, _, pt = pairs[(target["horse_id"], identity)] if known else (0, 0, 0)
                row["horse_jockey_history_starts"] = pn
                row["horse_jockey_history_top3_rate"] = (pt + 3) / (pn + 10)
        output.append(row)
    return output


def add_relative(frame):
    expressions = []
    for c in RELATIVE_SOURCES:
        expressions.extend(
            [
                (pl.col(c) - pl.col(c).mean().over("race_id")).alias(c + "__race_centered"),
                (
                    (pl.col(c).rank(method="average").over("race_id") - 1)
                    / (pl.col(c).count().over("race_id") - 1).clip(lower_bound=1)
                ).alias(c + "__race_percentile"),
            ]
        )
    result = frame.with_columns(expressions)
    a = result.select(RELATIVE_FEATURES).to_numpy()
    assert not np.isinf(a.astype(float)).any()
    return result

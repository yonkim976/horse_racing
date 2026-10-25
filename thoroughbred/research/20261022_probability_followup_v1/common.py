"""Bounded paths and read-only reuse of the verified research58 implementation."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
ROOT = HERE.parents[2]
BASE = HERE.parent / "20261022_probability_comparison_v1"
OLD_TOP2 = HERE.parent / "20261009_section_style_finish_v1/outputs/finish_models"
sys.path.insert(0, str(BASE))
import run as base
import probability as prob
import evaluate as score


def cfg():
    return json.loads((HERE / "config.json").read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    p = Path(path).resolve()
    assert p.is_relative_to(HERE), p
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load_frame():
    f = base.load_frame()
    flags = pd.read_parquet(BASE / "outputs/population_flags.parquet")
    assert not flags.duplicated(base.KEY).any()
    f = f.merge(flags[base.KEY + ["normal_finisher", "ambiguous_flag"]], on=base.KEY, how="left", validate="one_to_one")
    f.index = f.row_number
    test = f[f.year.isin(cfg()["evaluation_years"])]
    assert len(test) == 50754 and test.race_key.nunique() == 4799
    assert test[["normal_finisher", "ambiguous_flag"]].notna().all().all()
    return f


def source_top2(venue, year):
    return OLD_TOP2 / f"2_baseline22_{venue}_{year}"


def check_inputs():
    for name, expected in json.loads((OUT / "input_manifest.json").read_text()).items():
        p = ROOT / name
        assert p.stat().st_size == expected["bytes"] and sha(p) == expected["sha256"], name


def storage_check():
    own = [(p, p.stat().st_size) for p in HERE.rglob("*") if p.is_file()]
    assert all(n < 100_000_000 for _, n in own)
    total = sum(n for _, n in own)
    assert total < cfg()["max_new_bytes"]
    old = sum(p.stat().st_size for p in BASE.rglob("*") if p.is_file())
    assert total + old < cfg()["max_combined_bytes"]
    return total

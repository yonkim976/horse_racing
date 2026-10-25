"""Apply frozen Seoul/Busan candidate components to historical starts, without refitting."""

import gzip
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
SEOUL = HERE.parent / "20261011_seoul_section_corrections"
BUSAN = HERE.parent / "20261013_busan_section_corrections"
SPEC = importlib.util.spec_from_file_location("history_seoul_source", SEOUL / "analyze.py")
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
CORE = S.CORE
TARGETS = CORE + ["finish", "last600"]
META = [
    "row_key",
    "meet",
    "horse_id",
    "horse_name",
    "date",
    "year",
    "month",
    "distance_m",
    "race_key",
    "race_no",
    "grade",
    "band",
    "moisture",
    "horse_number",
    "n",
    "gate_block",
    "gate_side",
    "gate_family",
    "gate_level",
    "mad4_keep",
    "tail25",
    "estimation_keep",
]


def dump(path, value):
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def load():
    population, eligible = S.A.load()
    flags = pd.read_parquet(S.FLAGS, columns=["row_key", "tail25"])
    population = population.merge(flags, on="row_key", validate="one_to_one")
    population = population.merge(
        eligible[["row_key", "mad4_keep"]], on="row_key", how="left", validate="one_to_one"
    )
    population["mad4_keep"] = population.mad4_keep.fillna(False).astype(bool)
    population["estimation_keep"] = population.mad4_keep & ~population.tail25
    population["gate_family"] = np.where(
        population.gate_block.str.startswith("exact"), "number", "group"
    )
    population["gate_level"] = np.where(
        population.gate_family.eq("number"),
        population.horse_number.astype(str),
        population.gate_side,
    )
    ledgers = [
        pd.read_parquet(folder / "outputs/checkpoint_ledger.parquet") for folder in [SEOUL, BUSAN]
    ]
    points = pd.concat(ledgers, ignore_index=True)
    extra = [c for c in points if c not in population or c == "row_key"]
    population = population.merge(points[extra], on="row_key", validate="one_to_one")
    names, raw_hashes = pd.Series(index=population.index, dtype=object), {}
    for source, group in population.groupby("source_file"):
        path = (ROOT / source).resolve()
        assert path.is_relative_to(ROOT / "thoroughbred/research/20260929_calendar_api_v1/raw")
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            items = json.load(stream)["response"]["body"]["items"]["item"]
        for row in group.itertuples():
            item = items[int(row.source_item_index)]
            assert str(item["hrNo"]).zfill(7) == row.horse_id
            assert str(item["rcDate"]) == row.date.strftime("%Y%m%d")
            assert int(item["rcNo"]) == row.race_no
            assert abs(float(item["rcTime"]) - row.finish) < 1e-8
            names.loc[row.Index] = str(item["hrName"])
        raw_hashes[source] = S.A.sha(path)
    population["horse_name"] = names
    assert names.notna().all()
    return population, raw_hashes


def apply_scope(population, folder, venue, scope):
    d = population[population.meet.eq(venue)].copy().reset_index(drop=True)
    factors = pd.read_csv(folder / "outputs/correction_components.csv", dtype={"level": str})
    factors = factors[
        factors.scope.eq(scope) & factors.period.eq("all_mad4") & factors.variant.eq("tail25")
    ]
    definitions = pd.read_csv(folder / "outputs/section_definitions.csv")
    definitions = definitions[definitions.scope.eq(scope)]
    targets = sorted(factors.section.unique())
    if scope == "core":
        targets = TARGETS
    else:
        targets = sorted(set(targets) | set(TARGETS))
    w = d[META].copy()
    w["scope"], w["as_of"] = scope, "2026-10-15"
    valid = (
        pd.Series(True, index=d.index)
        if scope == "core"
        else d["corner_valid" if venue == "서울" else "detail_valid"].fillna(False).astype(bool)
    )
    w["raw_partition_valid"] = valid
    for part in targets:
        w[f"raw_{part}"] = d[part] if part in d else np.nan
    for term in ["moisture", "month", "gate"]:
        if term == "moisture":
            q = factors[factors.family.eq("moisture")]
            keys = ["distance_m", "band"]
            q = q.rename(columns={"level": "band"})
            join = d[keys]
        elif term == "month":
            q = factors[factors.family.eq("month")].copy()
            q["month"] = q.level.astype(int)
            keys = ["distance_m", "month"]
            join = d[keys]
        else:
            q = factors[factors.family.isin(["number", "group"])].rename(
                columns={"block": "gate_block", "family": "gate_family", "level": "gate_level"}
            )
            keys = ["distance_m", "gate_block", "gate_family", "gate_level"]
            join = d[keys]
        q = q.assign(value=q.add_seconds.where(q.available))
        table = q.pivot(index=keys, columns="section", values="value").reset_index()
        looked = join.merge(table, on=keys, how="left", validate="many_to_one")
        assert len(looked) == len(d)
        for part in targets:
            w[f"{term}_add_{part}"] = looked[part] if part in looked else np.nan
    for part in targets:
        values = w[[f"{term}_add_{part}" for term in ["moisture", "month", "gate"]]]
        complete = values.notna().all(axis=1) & w[f"raw_{part}"].notna() & valid
        partial = values.sum(axis=1).where(values.notna().any(axis=1) & valid)
        w[f"partial_add_{part}"] = partial
        w[f"add_{part}"] = partial.where(complete)
        w[f"adjusted_{part}"] = w[f"raw_{part}"] + w[f"add_{part}"]
    w["complete"] = w[[f"adjusted_{part}" for part in TARGETS]].notna().all(axis=1) & valid
    w["missing_reason"] = ""
    for term in ["moisture", "month", "gate"]:
        missing = w[f"{term}_add_finish"].isna()
        w.loc[missing, "missing_reason"] += term + ";"
    w.loc[~valid, "missing_reason"] += "raw_partition;"
    w["missing_reason"] = w.missing_reason.str.rstrip(";")
    for dist, g in w.groupby("distance_m"):
        parts = definitions[
            definitions.distance_m.eq(dist) & definitions.partition
        ].section.tolist()
        good = g.complete
        if parts and good.any():
            assert all(f"adjusted_{part}" in w for part in parts)
            assert np.allclose(
                g.loc[good, [f"adjusted_{part}" for part in parts]].sum(axis=1),
                g.loc[good, "adjusted_finish"],
            )
            assert np.allclose(
                g.loc[good, [f"add_{part}" for part in parts]].sum(axis=1),
                g.loc[good, "add_finish"],
            )
    return w


def main():
    OUT.mkdir(exist_ok=True)
    population, raw_hashes = load()
    core, alternate = [], []
    for folder, venue, scope in [(SEOUL, "서울", "corner"), (BUSAN, "부산", "detail")]:
        core.append(apply_scope(population, folder, venue, "core"))
        alternate.append(apply_scope(population, folder, venue, scope))
    core = pd.concat(core, ignore_index=True)
    alternate = pd.concat(alternate, ignore_index=True)
    assert len(core) == len(population) == 151074
    assert not core.row_key.duplicated().any() and not alternate.row_key.duplicated().any()
    core.to_parquet(OUT / "core_historical_records.parquet", index=False)
    alternate.to_parquet(OUT / "alternate_historical_records.parquet", index=False)
    sources = [S.L.POP, S.L.GATES, S.L.LEDGER, S.FLAGS, HERE / "PLAN.md", HERE / "analyze.py"]
    for folder in [SEOUL, BUSAN]:
        sources += [
            folder / "outputs" / n
            for n in [
                "correction_components.csv",
                "checkpoint_ledger.parquet",
                "section_definitions.csv",
                "candidate_policy.json",
            ]
        ]
        sources.append(folder / "apply.py")
    dump(
        OUT / "application_summary.json",
        dict(
            as_of="2026-10-15",
            records=len(core),
            alternate_records=len(alternate),
            core_complete=int(core.complete.sum()),
            alternate_complete=int(alternate.complete.sum()),
            venues={
                venue: dict(
                    rows=len(g),
                    complete=int(g.complete.sum()),
                    start=str(g.date.min().date()),
                    end=str(g.date.max().date()),
                )
                for venue, g in core.groupby("meet")
            },
            core_missing_reasons=core.loc[~core.complete, "missing_reason"]
            .value_counts()
            .to_dict(),
            raw_name_source_sha256=raw_hashes,
            input_sha256={str(p.relative_to(ROOT)): S.A.sha(p) for p in sources},
            coefficient_refit=False,
            production_changed=False,
            prediction_validation=False,
        ),
    )
    print(
        "applied",
        len(core),
        "core complete",
        int(core.complete.sum()),
        "alternate complete",
        int(alternate.complete.sum()),
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Read-only replay of the sealed post-run WIN-axis descriptive diagnostic."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


PROJECT = Path(__file__).resolve().parents[5]
STUDY = PROJECT / "jeju/research/20261022_tb_state_transfer_v1"
EXPERIMENT = STUDY / "experiment"
OUTPUTS = EXPERIMENT / "outputs"
DIAGNOSTICS = EXPERIMENT / "diagnostics"
AXIS_PATH = OUTPUTS / "win_axis_ledger.parquet"
F1_FEATURES = PROJECT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
PARQUET_PATH = DIAGNOSTICS / "win_axis_year_distance_gain_loss.parquet"
MANIFEST_PATH = DIAGNOSTICS / "diagnostics_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def rebuild_axis_diagnostics() -> pd.DataFrame:
    axis = pd.read_parquet(AXIS_PATH)
    features = pd.read_parquet(F1_FEATURES, columns=["race_id", "race_date", "distance_m", "field_n"])
    race_meta = features.drop_duplicates("race_id").copy()
    race_meta["race_date"] = pd.to_datetime(race_meta.race_date, errors="raise").dt.strftime("%Y-%m-%d")
    race_meta = race_meta.loc[race_meta.race_date.between("2024-01-01", "2026-09-19")].copy()
    require(not race_meta.race_id.duplicated().any() and len(race_meta) == 1779,
            "fixed evaluation race metadata is not unique")
    race_meta["year_from_meta"] = pd.to_datetime(race_meta.race_date).dt.year.astype("int16")
    race_meta["distance_group"] = race_meta.distance_m.map(lambda x: f"{int(round(float(x)))}m")
    axis["race_date"] = pd.to_datetime(axis.race_date, errors="raise").dt.strftime("%Y-%m-%d")
    axis = axis.merge(race_meta[["race_id", "race_date", "year_from_meta", "distance_group"]],
                      on=["race_id", "race_date"], how="left", validate="many_to_one", indicator=True)
    require(axis._merge.eq("both").all() and len(axis) == 3 * 1779 and
            axis.year.eq(axis.year_from_meta).all(), "axis keys/year differ from frozen F1 metadata")
    axis = axis.drop(columns=["_merge", "year_from_meta"])
    require(int(axis.loc[axis.arm.eq("R"), "selected_hit_top3"].sum()) == 1023,
            "sealed R axis reference no longer has 1,023 hits")

    records: list[dict] = []
    groups = [("all", "all", axis)]
    groups.extend(("year", str(int(year)), frame) for year, frame in axis.groupby("year", sort=True))
    groups.extend(("distance", str(distance), frame)
                  for distance, frame in axis.groupby("distance_group", sort=True))
    for dimension, value, frame in groups:
        r_hits = int(frame.loc[frame.arm.eq("R"), "selected_hit_top3"].sum())
        for arm in ("R", "C", "S"):
            part = frame.loc[frame.arm.eq(arm)]
            hits = int(part.selected_hit_top3.sum())
            records.append({
                "record_type": "axis_by_group", "dimension": dimension, "group": value,
                "arm": arm, "comparison": None, "races": len(part), "hit_count": hits,
                "hit_rate": float(hits / len(part)),
                "relative_hit_change_vs_R": float(hits / r_hits - 1.0) if arm != "R" else 0.0,
                "left_only_hit_gain": None, "right_only_hit_loss": None,
                "both_hit": None, "both_miss": None, "delta_hits": None, "delta_hit_rate": None,
            })
        values = frame.pivot(index="race_id", columns="arm", values="selected_hit_top3")
        require(set(values.columns) == {"R", "C", "S"} and not values.isna().any().any(),
                f"paired axis coverage mismatch in {dimension}/{value}")
        for left, right in (("C", "R"), ("S", "C"), ("S", "R")):
            lhit, rhit = values[left].astype(bool), values[right].astype(bool)
            n = len(values)
            gain = int((lhit & ~rhit).sum())
            loss = int((~lhit & rhit).sum())
            both = int((lhit & rhit).sum())
            neither = int((~lhit & ~rhit).sum())
            records.append({
                "record_type": "paired_gain_loss", "dimension": dimension, "group": value,
                "arm": None, "comparison": f"{left}_minus_{right}", "races": n,
                "hit_count": None, "hit_rate": None, "relative_hit_change_vs_R": None,
                "left_only_hit_gain": gain, "right_only_hit_loss": loss,
                "both_hit": both, "both_miss": neither, "delta_hits": gain - loss,
                "delta_hit_rate": float((gain - loss) / n),
            })
    return pd.DataFrame.from_records(records)


def main() -> None:
    require(PARQUET_PATH.is_file() and MANIFEST_PATH.is_file(), "diagnostic artifacts are missing")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    source_paths = {
        "win_axis_ledger_sha256": AXIS_PATH,
        "f1_features_sha256": F1_FEATURES,
        "fit_run_receipt_sha256": OUTPUTS / "fit_run_receipt.json",
        "report_sha256": OUTPUTS / "report.json",
    }
    for key, path in source_paths.items():
        require(manifest.get("source_hashes", {}).get(key) == sha256_file(path),
                f"diagnostic source hash changed: {key}")
    artifact = manifest.get("artifact", {})
    require(artifact.get("path") == PARQUET_PATH.relative_to(PROJECT).as_posix() and
            artifact.get("bytes") == PARQUET_PATH.stat().st_size and
            artifact.get("sha256") == sha256_file(PARQUET_PATH), "diagnostic artifact receipt mismatch")
    stored = pd.read_parquet(PARQUET_PATH)
    expected = rebuild_axis_diagnostics()
    pd.testing.assert_frame_equal(stored, expected, check_dtype=False, check_exact=True)
    print(json.dumps({
        "status": "PASS_READ_ONLY_DIAGNOSTIC_REPLAY",
        "parquet_sha256": sha256_file(PARQUET_PATH),
        "rows": len(stored), "source_hashes_verified": len(source_paths),
        "metrics_recomputed_from_sealed_axis_only": True,
    }, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

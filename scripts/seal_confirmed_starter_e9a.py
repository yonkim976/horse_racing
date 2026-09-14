"""Seal the E9-A steward-report population before detailed text review."""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path("data/experiments/confirmed_starter_e9a_20260913")
DB = Path("data/horse_racing.sqlite3")
H1 = Path("data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m")
START = "2025-01-01"
END = "2026-02-28"
SEED = 20260913
CUES = (
    "진로",
    "방해",
    "접촉",
    "막혀",
    "제어",
    "출발이 늦",
    "출발이 느",
    "늦게 출발",
    "발주불량",
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, payload: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def seal() -> Path:
    manifest_path = H1 / "manifest.json"
    h1 = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = h1["selected_feature_names"]
    selected_hash = hashlib.sha256(
        json.dumps(selected, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if len(selected) != 136 or selected_hash != h1["selected_feature_hash"]:
        raise RuntimeError("H1 selected feature contract invalid")
    if sha(manifest_path) != "f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801":
        raise RuntimeError("H1 manifest hash changed")
    if sha(Path(h1["dataset"]["path"])) != h1["dataset"]["sha256"]:
        raise RuntimeError("H1 dataset hash changed")

    connection = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    cues_sql = " OR ".join(
        "instr(COALESCE(sr.judgement,'') || ' ' || COALESCE(sr.additional_judgement,''), ?) > 0"
        for _ in CUES
    )
    population_rows = connection.execute(
        f"""
        SELECT sr.id AS report_id, r.id AS race_id, sr.race_date_local AS race_date,
               sr.race_number AS race_number, sr.observed_at_ms AS report_observed_at_ms,
               CASE WHEN {cues_sql} THEN 1 ELSE 0 END AS cue_candidate
        FROM race_steward_reports AS sr
        JOIN racecourses AS rc ON rc.kra_meet_code=sr.meet_code
        JOIN races AS r ON r.racecourse_id=rc.id
          AND r.race_date_local=sr.race_date_local AND r.race_number=sr.race_number
        WHERE sr.meet_code=1
          AND sr.race_date_local BETWEEN ? AND ?
          AND r.race_date_local BETWEEN ? AND ?
        ORDER BY r.id, sr.id
        """,
        (*CUES, START, END, START, END),
    ).fetchall()
    source_rows = connection.execute(
        """
        SELECT id AS source_document_id, local_path, sha256, requested_at_ms,
               retrieved_at_ms, json_extract(request_params_json,'$.rc_date') AS source_date
        FROM source_documents
        WHERE endpoint='/API215/JudgeReport'
          AND json_extract(request_params_json,'$.meet')=1
          AND json_extract(request_params_json,'$.rc_date') BETWEEN ? AND ?
        ORDER BY source_date, id
        """,
        (START.replace("-", ""), END.replace("-", "")),
    ).fetchall()
    connection.close()
    sources: dict[str, dict] = {}
    for row in source_rows:
        key = str(row["source_date"])
        if key in sources:
            raise RuntimeError(f"multiple archived source documents for date {key}")
        path = Path(str(row["local_path"]))
        source = dict(row)
        source["verified_sha256"] = sha(path) if path.is_file() else None
        if source["verified_sha256"] != row["sha256"]:
            raise RuntimeError(f"source raw missing or hash mismatch for date {key}")
        sources[key] = source
    population: list[dict] = []
    for row in population_rows:
        record = dict(row)
        source = sources.get(record["race_date"].replace("-", ""))
        record["source_document_id"] = source["source_document_id"] if source else None
        record["source_sha256"] = source["sha256"] if source else None
        record["source_local_path"] = source["local_path"] if source else None
        record["source_requested_at_ms"] = source["requested_at_ms"] if source else None
        record["source_retrieved_at_ms"] = source["retrieved_at_ms"] if source else None
        population.append(record)
    if len({row["report_id"] for row in population}) != len(population):
        raise RuntimeError("duplicate report ids")
    rng = random.Random(SEED)
    random_sample = rng.sample(population, min(30, len(population)))
    random_ids = {row["report_id"] for row in random_sample}
    candidates = [
        row for row in population if row["cue_candidate"] and row["report_id"] not in random_ids
    ]
    cue_sample = rng.sample(candidates, min(30, len(candidates)))
    sample_groups = {row["report_id"]: "random" for row in random_sample}
    sample_groups.update({row["report_id"]: "cue_oversample" for row in cue_sample})
    for row in population:
        row["sample_group"] = sample_groups.get(row["report_id"])
    canonical = json.dumps(population, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ROOT.mkdir(parents=True, exist_ok=False)
    output = {
        "version": "e9a_population_v1",
        "sealed_at_utc": datetime.now(UTC).isoformat(),
        "scope": {"meet": 1, "date_start": START, "date_end": END, "read_only_db": True},
        "sampling": {
            "seed": SEED,
            "random_n": len(random_sample),
            "cue_oversample_n": len(cue_sample),
            "cues": CUES,
            "candidate_count": len(candidates),
            "random_ids_sorted": sorted(random_ids),
            "cue_ids_sorted": sorted(row["report_id"] for row in cue_sample),
        },
        "population_count": len(population),
        "population_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "population": population,
        "source_documents": sources,
        "h1": {
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha(manifest_path),
            "dataset_path": h1["dataset"]["path"],
            "dataset_sha256": h1["dataset"]["sha256"],
            "selected_feature_names": selected,
            "selected_feature_hash": selected_hash,
            "selected_sand_features": [name for name in selected if name.startswith("sand_")],
            "declared_source_sha256": h1["source_sha256"],
        },
        "db_sha256_before": sha(DB),
        "raw_text_reviewed_before_seal": False,
        "outcomes_consulted_for_sampling": False,
    }
    path = ROOT / "population_manifest.json"
    write_new(path, output)
    print(
        json.dumps(
            {
                "population": len(population),
                "random": len(random_sample),
                "cue": len(cue_sample),
                "manifest": str(path),
            },
            ensure_ascii=False,
        )
    )
    return path


if __name__ == "__main__":
    seal()

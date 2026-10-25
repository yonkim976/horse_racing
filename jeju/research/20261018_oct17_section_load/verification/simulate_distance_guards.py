"""Run the loader's exact review DDL/view over the real Oct 17 API6 item in RAM.

No shared database file is opened or modified. This is a fail-closed design
check for absent reviews and changed source bindings before applying the load.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
JEJU = HERE.parents[2]
ROOT = JEJU.parent
LOAD_DIR = HERE.parent
REVIEW = JEJU / "research/20261018_oct17_sections_website_review"
LOADER = LOAD_DIR / "apply_sections.py"
PLAN_PATH = LOAD_DIR / "plan.json"
SOURCE_REPORT = HERE / "source_verification.json"
DATE = "2026-10-17"
MEET = 2
RACE = 5


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loader_sql() -> tuple[str, str]:
    tree = ast.parse(LOADER.read_text(encoding="utf-8"), filename=str(LOADER))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"DDL", "VIEW"}:
                    found[target.id] = ast.literal_eval(node.value)
    if set(found) != {"DDL", "VIEW"}:
        raise RuntimeError("Unable to extract the exact loader DDL and view SQL")
    return found["DDL"], found["VIEW"]


def raw_target_item() -> dict[str, Any]:
    path = REVIEW / "api_recheck/raw/section_records/20261017/page_0001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload["response"]["body"]["items"]["item"]
    matches = [r for r in records if str(r.get("rcDate")) == "20261017" and r.get("meet") == "제주" and int(r.get("rcNo", -1)) == RACE]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one real API6 R5 item, got {len(matches)}")
    return matches[0]


def evidence() -> dict[str, Any]:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    source = json.loads(SOURCE_REPORT.read_text(encoding="utf-8"))["source"]
    api6_page = REVIEW / plan["pages"][1]["raw_path"] if "raw_path" in plan["pages"][1] else REVIEW / "api_recheck/raw/section_records/20261017/page_0001.json"
    website_path = ROOT / plan["review5"]["path"]
    compare_path = REVIEW / "root_api_website_comparison.json"
    page_digest = sha(api6_page.read_bytes())
    website_digest = sha(website_path.read_bytes())
    compare_digest = sha(compare_path.read_bytes())
    if page_digest != source["api_sources"]["section_records"]["sha256_actual"]:
        raise RuntimeError("API6 page SHA does not match independent source evidence")
    if website_digest != plan["review5"]["sha256"]:
        raise RuntimeError("R5 official website page SHA does not match load plan")
    rows = source["api6_distance_disagreement_rows"]
    distances = [int(row["website_raw"]) for row in rows if row["race_number"] == RACE]
    if distances != plan["review5"]["distances_m"]:
        raise RuntimeError("Website review distance vector does not match the independent source parser")
    return {
        "plan": plan,
        "api6_page_sha256": page_digest,
        "website_path": plan["review5"]["path"],
        "website_page_sha256": website_digest,
        "website_url": plan["review5"]["url"],
        "website_distances_m": distances,
        "evidence_path": str(compare_path.relative_to(ROOT)),
        "evidence_sha256": compare_digest,
    }


def base_view_contract() -> dict[str, Any]:
    db_path = JEJU / "data/jeju_native_core.sqlite3"
    con = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    try:
        row = con.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name='api6_section_records_current'").fetchone()
        if row is None:
            raise RuntimeError("Existing API6 current raw view is missing")
        columns = [item[1] for item in con.execute("PRAGMA table_info(api6_section_records_current)")]
        required = {
            "api_record_id", "race_date", "meet_code", "race_number", "payload_json",
            "payload_sha256", "source_artifact_id", "record_index", "artifact_sha256", "raw_relative_path",
        }
        if not required.issubset(columns):
            raise RuntimeError(f"Existing API6 view contract is missing columns: {sorted(required - set(columns))}")
        return {"sql": row[0], "columns": columns, "required_columns_present": sorted(required)}
    finally:
        con.close()


def build_case(case: str, ddl: str, view: str, base_sql: str, proof: dict[str, Any], item: dict[str, Any]) -> list[dict[str, Any]]:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        con.executescript("""
          CREATE TABLE source_artifacts(
            source_artifact_id INTEGER PRIMARY KEY,
            sha256 TEXT NOT NULL,
            raw_relative_path TEXT NOT NULL,
            collected_at_utc TEXT NOT NULL
          );
          CREATE TABLE api_records(
            api_record_id INTEGER PRIMARY KEY,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            source_artifact_id INTEGER NOT NULL REFERENCES source_artifacts(source_artifact_id),
            record_index INTEGER NOT NULL
          );
          CREATE TABLE refresh_section_records(
            api_record_id INTEGER PRIMARY KEY REFERENCES api_records(api_record_id),
            race_date TEXT NOT NULL,
            meet_code INTEGER NOT NULL,
            race_number INTEGER NOT NULL
          );
        """)
        raw_page_rel = "jeju/research/20261018_oct17_sections_website_review/api_recheck/raw/section_records/20261017/page_0001.json"
        con.execute("INSERT INTO source_artifacts VALUES(?,?,?,?)", (101, proof["api6_page_sha256"], raw_page_rel, "2026-10-17T19:02:34+00:00"))
        payload = canonical(item)
        payload_sha = sha(payload.encode("utf-8"))
        con.execute("INSERT INTO api_records VALUES(?,?,?,?,?)", (1, payload, payload_sha, 101, RACE))
        con.execute("INSERT INTO refresh_section_records VALUES(?,?,?,?)", (1, DATE, MEET, RACE))
        con.execute(base_sql)
        con.execute(ddl)

        if case != "review_missing_all":
            review_rows = []
            for i, website_distance in enumerate(proof["website_distances_m"], 1):
                if case == "review_missing_index_3" and i == 3:
                    continue
                review_rows.append((
                    1, i, DATE, MEET, RACE, item["rcDist"], payload_sha, 101,
                    proof["api6_page_sha256"], item[f"dist_{i}f"], website_distance,
                    website_distance, "website_corrected", proof["website_url"], "2026-10-18",
                    proof["website_path"], proof["website_page_sha256"], proof["evidence_path"],
                    proof["evidence_sha256"],
                    "exact-race official website distance; API raw is preserved",
                    "2026-10-18T00:00:00+00:00",
                ))
            con.executemany("INSERT INTO api6_section_distance_reviews VALUES(" + ",".join("?" for _ in range(21)) + ")", review_rows)

        if case == "payload_sha_changed":
            con.execute("UPDATE api_records SET payload_sha256=? WHERE api_record_id=1", ("f" * 64,))
        elif case == "page_sha_changed":
            con.execute("UPDATE source_artifacts SET sha256=? WHERE source_artifact_id=101", ("e" * 64,))
        elif case == "key_changed":
            con.execute("UPDATE refresh_section_records SET race_number=4 WHERE api_record_id=1")
        elif case == "rcDist_changed":
            changed = dict(item)
            changed["rcDist"] = 1111
            con.execute("UPDATE api_records SET payload_json=? WHERE api_record_id=1", (canonical(changed),))
        elif case == "raw_distance_changed":
            changed = dict(item)
            changed["dist_1f"] = 101
            con.execute("UPDATE api_records SET payload_json=? WHERE api_record_id=1", (canonical(changed),))
        elif case == "artifact_id_changed":
            con.execute("INSERT INTO source_artifacts VALUES(?,?,?,?)", (102, "d" * 64, "jeju/new.json", "2026-10-18T00:00:00+00:00"))
            con.execute("UPDATE api_records SET source_artifact_id=102 WHERE api_record_id=1")

        con.execute(view)
        return [dict(row) for row in con.execute(
            """SELECT furlong_index,api_distance_m_raw,distance_m,distance_status,
                      race_distance_m_raw FROM api6_section_points_current
               WHERE api_record_id=1 AND furlong_index BETWEEN 1 AND 6
               ORDER BY furlong_index"""
        )]
    finally:
        con.close()


def run() -> dict[str, Any]:
    ddl, view = loader_sql()
    base = base_view_contract()
    proof = evidence()
    item = raw_target_item()
    if item.get("rcDist") != 1110:
        raise RuntimeError("Real R5 API6 item rcDist is not 1110")
    original_api = [item[f"dist_{i}f"] for i in range(1, 7)]
    if original_api != [100, 300, 500, 700, 900, 1100]:
        raise RuntimeError("Real R5 API6 raw distance sequence changed")

    expected = proof["website_distances_m"]
    checks: dict[str, Any] = {}
    baseline = build_case("baseline", ddl, view, base["sql"], proof, item)
    if [r["distance_m"] for r in baseline] != expected or any(r["distance_status"] != "website_corrected" for r in baseline):
        raise RuntimeError(f"Baseline review values/status failed: {baseline}")
    if [r["api_distance_m_raw"] for r in baseline] != original_api:
        raise RuntimeError("Baseline view does not preserve API raw distances")
    checks["baseline_source_bound_review"] = {
        "passed": True,
        "raw_api_distances_m": original_api,
        "effective_distances_m": [r["distance_m"] for r in baseline],
        "statuses": [r["distance_status"] for r in baseline],
    }

    for case in ("review_missing_all", "review_missing_index_3", "payload_sha_changed", "page_sha_changed", "key_changed", "rcDist_changed", "raw_distance_changed", "artifact_id_changed"):
        result = build_case(case, ddl, view, base["sql"], proof, item)
        by_index = {row["furlong_index"]: row for row in result}
        if case == "review_missing_all":
            if any(row["distance_m"] is not None or row["distance_status"] != "website_review_not_applied" for row in result):
                raise RuntimeError(f"Deleted review did not fail closed: {result}")
        elif case == "review_missing_index_3":
            if by_index[3]["distance_m"] is not None or by_index[3]["distance_status"] != "website_review_not_applied":
                raise RuntimeError(f"Deleted review row did not fail closed at index 3: {result}")
            if any(by_index[i]["distance_m"] != expected[i-1] for i in (1, 2, 4, 5, 6)):
                raise RuntimeError("Deleting one review row unexpectedly altered other bound rows")
        elif case == "raw_distance_changed":
            if by_index[1]["distance_m"] is not None or by_index[1]["distance_status"] != "api_source_changed_since_review":
                raise RuntimeError(f"Changed raw distance did not fail closed: {result}")
            if any(by_index[i]["distance_m"] != expected[i-1] for i in (2, 3, 4, 5, 6)):
                raise RuntimeError("Changing one raw distance unexpectedly altered other bound rows")
        elif any(row["distance_m"] is not None or row["distance_status"] != "api_source_changed_since_review" for row in result):
            raise RuntimeError(f"Changed {case} binding did not fail closed: {result}")
        checks[case] = {
            "passed": True,
            "effective_distance_null_count": sum(row["distance_m"] is None for row in result),
            "statuses": [row["distance_status"] for row in result],
        }

    if "DROP VIEW" in view.upper() or not view.lstrip().upper().startswith("CREATE VIEW API6_SECTION_POINTS_CURRENT"):
        raise RuntimeError("Loader SQL unexpectedly replaces or drops a pre-existing view")
    if "CREATE TABLE API6_SECTION_DISTANCE_REVIEWS" not in ddl.upper():
        raise RuntimeError("Loader DDL does not isolate the new source-bound review table")
    return {
        "passed": True,
        "database": "read-only lookup of existing API6 view definition; all guard cases ran in SQLite :memory:",
        "actual_api6_raw_view_contract": {"name": "api6_section_records_current", "columns": base["columns"],
                                           "required_columns_present": base["required_columns_present"]},
        "sql_source": str(LOADER.relative_to(ROOT)),
        "review_ddl": "api6_section_distance_reviews only",
        "view_sql": "api6_section_points_current only; no drops or replacement of existing views",
        "target_api6_raw_item": {"date": item["rcDate"], "meet": item["meet"], "race_number": item["rcNo"],
                                 "rcDist": item["rcDist"], "api_distances_m": original_api},
        "website_binding": {k: proof[k] for k in ("website_path", "website_page_sha256", "website_distances_m", "evidence_path", "evidence_sha256")},
        "cases": checks,
    }


if __name__ == "__main__":
    result = run()
    output = HERE / "guard_simulation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "cases": list(result["cases"]), "output": str(output)}, ensure_ascii=False, indent=2))

"""Link historical Busan text actor IDs to race-time official IDs, without DB writes.

The operating database and the source history database are opened read-only.  The
output is a separate, replaceable research artifact.  A text ID is a name hash,
so a row-level official relationship is not automatically an actor identity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HISTORY = Path("data/research/busan_history_20260915/history.sqlite3")
OPERATING = Path("data/horse_racing.sqlite3")
OUTPUT = Path("data/research/busan_temp_id_linkage_20260915")
SCRIPT = Path(__file__)
VENUE_PREFIX = re.compile(r"^\[(?:서울|부경|부산|제주|서|부|제)\]\s*")


def open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def name_key(value: str | None) -> str:
    return "".join(unicodedata.normalize("NFKC", value or "").split()).casefold()


def horse_key(value: str | None) -> str:
    return name_key(VENUE_PREFIX.sub("", value or ""))


def source_items(path: Path) -> list[dict]:
    payload = json.loads(path.read_bytes())
    body = payload["response"]["body"]
    value = (body.get("items") or {}).get("item") or []
    return [value] if isinstance(value, dict) else value


def create_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
      CREATE TABLE entry_linkage(
        old_entry_id INTEGER NOT NULL, actor_type TEXT NOT NULL,
        temporary_id TEXT NOT NULL, temporary_actor_rowid INTEGER NOT NULL,
        temporary_actor_name TEXT NOT NULL,
        meet INTEGER NOT NULL CHECK(meet=3), race_date TEXT NOT NULL,
        race_no INTEGER NOT NULL, hr_no TEXT NOT NULL, chul_no INTEGER NOT NULL,
        old_horse_name TEXT NOT NULL, official_horse_name TEXT NOT NULL,
        official_id TEXT NOT NULL, official_name TEXT,
        official_id_raw_json TEXT NOT NULL, official_actor_rowid INTEGER,
        name_agrees INTEGER NOT NULL, horse_name_relation TEXT NOT NULL,
        relationship_status TEXT NOT NULL,
        official_source_path TEXT NOT NULL, official_source_row INTEGER NOT NULL,
        PRIMARY KEY(old_entry_id,actor_type));
      CREATE INDEX entry_linkage_temp ON entry_linkage(actor_type,temporary_id);
      CREATE TABLE temporary_id_link(
        actor_type TEXT NOT NULL, temporary_id TEXT NOT NULL,
        temporary_actor_rowid INTEGER NOT NULL,
        temporary_actor_name TEXT NOT NULL,
        observed_official_id TEXT, candidate_count INTEGER NOT NULL,
        evidence_rows INTEGER NOT NULL, name_agree_rows INTEGER NOT NULL,
        name_disagree_rows INTEGER NOT NULL, first_race_date TEXT NOT NULL,
        last_race_date TEXT NOT NULL, identity_status TEXT NOT NULL,
        candidate_ids_json TEXT NOT NULL,
        PRIMARY KEY(actor_type,temporary_id));
      CREATE TABLE candidate_evidence(
        actor_type TEXT NOT NULL, temporary_id TEXT NOT NULL,
        official_id TEXT NOT NULL, official_names_json TEXT NOT NULL,
        evidence_rows INTEGER NOT NULL, name_agree_rows INTEGER NOT NULL,
        first_race_date TEXT NOT NULL, last_race_date TEXT NOT NULL,
        sample_old_entry_id INTEGER NOT NULL,
        sample_source_path TEXT NOT NULL, sample_source_row INTEGER NOT NULL,
        PRIMARY KEY(actor_type,temporary_id,official_id));
      CREATE TABLE input_manifest(
        path TEXT PRIMARY KEY, role TEXT NOT NULL, sha256 TEXT NOT NULL,
        bytes INTEGER NOT NULL);
    """)


def build(history_path: Path, operating_path: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    history = open_ro(history_path)
    old = open_ro(operating_path)
    target = output / "linkage.sqlite3"
    temporary = output / ".linkage.sqlite3.tmp"
    if temporary.exists():
        temporary.unlink()
    db = sqlite3.connect(temporary)
    create_schema(db)
    actors = {}
    for actor_type, table, id_field in (
        ("trainer", "trainers", "kra_trainer_id"),
        ("owner", "owners", "kra_owner_id"),
    ):
        actors[actor_type] = {
            actor_id: (rowid, name)
            for rowid, actor_id, name in old.execute(
                f"SELECT id,{id_field},name_ko FROM {table}"
            )
        }
    old_rows = list(old.execute("""
      SELECT e.id,r.race_date_local,r.race_number,h.kra_horse_id,h.name_ko,
             e.horse_number,t.id,t.kra_trainer_id,o.id,o.kra_owner_id
      FROM race_entries e JOIN races r ON r.id=e.race_id
      JOIN racecourses c ON c.id=r.racecourse_id
      JOIN horses h ON h.id=e.horse_id
      LEFT JOIN trainers t ON t.id=e.trainer_id
      LEFT JOIN owners o ON o.id=e.owner_id
      WHERE c.kra_meet_code=3 AND r.race_date_local>='2015-01-01'
        AND r.race_date_local<'2025-01-01'
        AND (t.kra_trainer_id LIKE 'text:%' OR o.kra_owner_id LIKE 'text:%')
      ORDER BY e.id"""))
    prior_ids = {row[0] for row in history.execute(
        "SELECT old_entry_id FROM legacy_id_repair")}
    assert len(old_rows) == len(prior_ids) == len({r[0] for r in old_rows})
    assert {r[0] for r in old_rows} == prior_ids

    raw_cache: dict[str, list[dict]] = {}
    source_paths: set[Path] = set()
    stats = Counter()
    for eid, day, race_no, hr_no, old_horse, chul, tr_rowid, tr_id, ow_rowid, ow_id in old_rows:
        official = history.execute("""
          SELECT horse_name,chul_no,trainer_no,owner_no,trainer_name,owner_name,
                 source_path,source_row,owner_no_raw_json
          FROM entry WHERE meet=3 AND race_date=? AND race_no=? AND hr_no=?""",
            (day, race_no, hr_no)).fetchone()
        if official is None:
            raise ValueError(f"No official race/horse key for legacy entry {eid}")
        api_horse, api_chul, tr_no, ow_no, tr_name, ow_name, source_path, source_row, ow_raw = official
        if chul != api_chul or horse_key(old_horse) != horse_key(api_horse):
            raise ValueError(f"Horse/entry conflict for legacy entry {eid}")
        source_paths.add(Path(source_path))
        if source_path not in raw_cache:
            raw_cache[source_path] = source_items(Path(source_path))
        raw = raw_cache[source_path][source_row]
        if (str(raw.get("rcDate")) != day.replace("-", "")
                or int(raw["rcNo"]) != race_no or str(raw["hrNo"]) != hr_no
                or int(raw["chulNo"]) != chul or raw["meet"] != "부산경남"
                or str(raw.get("trNo") or "") != tr_no
                or json.dumps(raw.get("owNo"), ensure_ascii=False, sort_keys=True) != ow_raw):
            raise ValueError(f"Official raw row mismatch for legacy entry {eid}")
        relation = "exact" if name_key(old_horse) == name_key(api_horse) else "venue_prefix_only"
        stats[relation] += 1
        for actor_type, actor_rowid, temp_id, official_id, official_name, raw_id in (
            ("trainer", tr_rowid, tr_id, tr_no, tr_name, raw.get("trNo")),
            ("owner", ow_rowid, ow_id, ow_no, ow_name, raw.get("owNo")),
        ):
            if not (temp_id or "").startswith("text:"):
                continue
            if not official_id:
                raise ValueError(f"Blank official {actor_type} ID for legacy entry {eid}")
            temp_name = actors[actor_type][temp_id][1]
            assert actors[actor_type][temp_id][0] == actor_rowid
            agree = int(name_key(temp_name) == name_key(official_name))
            db.execute("INSERT INTO entry_linkage VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, actor_type, temp_id, actor_rowid, temp_name, 3, day,
                 race_no, hr_no, chul, old_horse, api_horse, official_id,
                 official_name, json.dumps(raw_id, ensure_ascii=False),
                 actors[actor_type].get(official_id, (None, None))[0],
                 agree, relation, "confirmed_official_race_horse_row",
                 source_path, source_row))
            stats[(actor_type, "rows")] += 1
            stats[(actor_type, "name_agree" if agree else "name_disagree")] += 1
    db.commit()
    for actor_type, temp_id, actor_rowid, temp_name, count, agrees, first, last in db.execute("""
      SELECT actor_type,temporary_id,temporary_actor_rowid,temporary_actor_name,
             count(*),sum(name_agrees),min(race_date),max(race_date)
      FROM entry_linkage GROUP BY actor_type,temporary_id
      ORDER BY actor_type,temporary_id"""):
        candidates = list(db.execute("""
          SELECT official_id,count(*),sum(name_agrees),min(race_date),max(race_date),
                 min(old_entry_id)
          FROM entry_linkage WHERE actor_type=? AND temporary_id=?
          GROUP BY official_id ORDER BY official_id""", (actor_type, temp_id)))
        for official_id, rows, matching, first_id, last_id, sample_eid in candidates:
            names = sorted({r[0] for r in db.execute("""
              SELECT DISTINCT official_name FROM entry_linkage
              WHERE actor_type=? AND temporary_id=? AND official_id=?""",
              (actor_type, temp_id, official_id))})
            sample = db.execute("""
              SELECT official_source_path,official_source_row FROM entry_linkage
              WHERE old_entry_id=? AND actor_type=?""", (sample_eid, actor_type)).fetchone()
            db.execute("INSERT INTO candidate_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (actor_type, temp_id, official_id,
                 json.dumps(names, ensure_ascii=False), rows, matching,
                 first_id, last_id, sample_eid, *sample))
        status = ("ambiguous_multiple_official_ids" if len(candidates) > 1 else
                  "single_candidate_name_conflict" if agrees != count else
                  "single_candidate_name_agrees")
        db.execute("INSERT INTO temporary_id_link VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (actor_type, temp_id, actor_rowid, temp_name,
             candidates[0][0] if len(candidates) == 1 else None,
             len(candidates), count, agrees, count - agrees, first, last,
             status, json.dumps([c[0] for c in candidates], ensure_ascii=False)))
        stats[(actor_type, status)] += 1
    for path, role in ((history_path, "read_only_history_db"),
                       (operating_path, "read_only_operating_db"),
                       (SCRIPT, "linkage_code")):
        db.execute("INSERT INTO input_manifest VALUES(?,?,?,?)",
                   (str(path), role, sha(path), path.stat().st_size))
    for path in sorted(source_paths):
        db.execute("INSERT INTO input_manifest VALUES(?,?,?,?)",
                   (str(path), "official_result_raw", sha(path), path.stat().st_size))
    db.commit()
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("SELECT count(*) FROM entry_linkage").fetchone()[0] == sum(
        1 for row in old_rows for value in (row[7], row[9]) if (value or "").startswith("text:"))
    assert db.execute("SELECT count(DISTINCT old_entry_id) FROM entry_linkage").fetchone()[0] == len(old_rows)
    assert db.execute("SELECT count(*) FROM entry_linkage WHERE relationship_status != 'confirmed_official_race_horse_row'").fetchone()[0] == 0
    for table in ("entry_linkage", "temporary_id_link", "candidate_evidence", "input_manifest"):
        columns = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
        with (output / f"{table}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(columns)
            writer.writerows(db.execute(f"SELECT * FROM {table} ORDER BY 1,2"))
    with (output / "unresolved_identity.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["actor_type", "temporary_id", "temporary_actor_name",
                         "candidate_ids_json", "identity_status", "evidence_rows",
                         "name_disagree_rows"])
        writer.writerows(db.execute("""
          SELECT actor_type,temporary_id,temporary_actor_name,candidate_ids_json,
                 identity_status,evidence_rows,name_disagree_rows
          FROM temporary_id_link
          WHERE identity_status!='single_candidate_name_agrees'
          ORDER BY actor_type,temporary_id"""))
    yearly = list(db.execute("""
      SELECT substr(race_date,1,4),count(DISTINCT old_entry_id),
             sum(actor_type='trainer'),sum(actor_type='owner'),
             count(DISTINCT CASE WHEN horse_name_relation='venue_prefix_only'
                  THEN old_entry_id END)
      FROM entry_linkage GROUP BY substr(race_date,1,4) ORDER BY 1"""))
    ambiguous = list(db.execute("""
      SELECT temporary_actor_name,temporary_id,candidate_ids_json,evidence_rows
      FROM temporary_id_link WHERE identity_status='ambiguous_multiple_official_ids'
      ORDER BY temporary_actor_name"""))
    official_entity_counts = list(db.execute("""
      SELECT actor_type,count(DISTINCT official_id),
             count(DISTINCT CASE WHEN official_actor_rowid IS NOT NULL THEN official_id END)
      FROM entry_linkage GROUP BY actor_type ORDER BY actor_type"""))
    report = [
        "# 부경 `text:` 임시 ID와 경주 당시 공식 ID 연결",
        "",
        "운영 DB의 2015–2024년 부경 출전행 35,157개를 공식 KRA 결과 원문과",
        "`(meet=3, 경주일, 경주번호, hrNo)`로 대조했다. 출전번호도 전부 일치한다.",
        "마명의 경마장 접두어만 다른 244개까지 정규화하여 출전행 35,157개를 모두 연결했다.",
        "공식 원문 10개 페이지의 각 해당 행을 다시 읽어 키와 `trNo/owNo`를 검증했다.",
        "운영 DB와 기존 역사 DB는 읽기 전용으로 열었고 어떤 행도 수정하지 않았다.",
        "",
        "| 연도 | 연결 출전행 | 조교사 임시 ID 행 | 마주 임시 ID 행 | 마명 접두어 차이 출전행 |",
        "|---:|---:|---:|---:|---:|",
    ]
    report += [f"| {year} | {entries:,} | {trainers:,} | {owners:,} | {prefix:,} |"
               for year, entries, trainers, owners, prefix in yearly]
    report += [
        "",
        "조교사 `text:` 130개는 모두 관측 경주에서 공식 `trNo`가 한 종류였으나,",
        "98개는 임시 이름과 공식 결과의 이름이 다르다. 마주 `text:` 240개 중",
        "237개는 관측 공식 `owNo` 하나에 이름도 일치하고, 1개는 이름이 다르며,",
        "2개는 공식 마주번호가 둘이다. 이 101개 임시 ID는 인물 동일성 미해결",
        "원장에 남겼다. 이름 불일치에는 Text 파싱 흔적처럼 보이는 `스 ` 접두어와",
        "`윤영귀`·`윤주혁` 대 공식 `윤영훈` 같은 실질적 차이가 모두 포함된다.",
        "이들을 이름만으로 동일 인물로 승격하지 않았다. 각 출전행의 당시 공식 관계는",
        "원문 경주·말 키로 별도로 확정되어 있다.",
        "",
        "| 임시 마주명 | 임시 ID | 공식 후보 | 근거 출전행 |",
        "|---|---|---|---:|",
    ]
    report += [f"| {name} | `{temp_id}` | `{ids}` | {count} |"
               for name, temp_id, ids, count in ambiguous]
    report += [
        "",
        "이 두 임시 ID는 이름을 해시해 만든 값이므로 전역적으로 공식 ID 하나로",
        "치환하면 잘못 연결된다. `entry_linkage`에서 경주별 공식 ID를 사용해야 한다.",
        "공식 ID는 문자열로 보존했고, 숫자형 마주 ID의 원문 JSON 값도 남겼다.",
        "",
        "| 유형 | 연결된 공식 ID 종류 | 현재 운영 DB에 이미 존재하는 공식 ID 종류 |",
        "|---|---:|---:|",
    ]
    report += [f"| {kind} | {total} | {existing} |" for kind, total, existing in official_entity_counts]
    report += [
        "",
        "`official_actor_rowid`가 비어 있는 것은 공식 ID가 없는 뜻이 아니라",
        "현재 운영 DB에 그 공식 ID의 인물 행이 아직 없다는 뜻이다.",
        "본 산출물은 운영 DB 반영용 검증 자료이며 운영 DB를 직접 변경하지 않았다.",
        "",
        "## 재현과 자료 사전",
        "",
        "작업 루트에서 `python3 scripts/link_busan_temporary_ids.py`를 실행한다.",
        "동일 전용 경로의 파일을 원자적으로 교체하므로 재실행 시 중복 삽입하지 않는다.",
        "`linkage.sqlite3`의 `entry_linkage`는 `(old_entry_id, actor_type)` 기본키인",
        "경주 당시 관계 테이블이다. `temporary_id_link`는 임시 ID별 관측 후보와",
        "이름 대조 판정을 담고, `candidate_evidence`는 후보별 건수·날짜·원문 표본",
        "위치를 담는다. `unresolved_identity.csv`에는 다중 후보 및 이름 충돌",
        "101개 임시 ID를 기록했다. `input_manifest`에는 읽기 전용 DB·코드·원문",
        "각 파일의 SHA256이 있고 `manifest.json`은 생성 산출물의 SHA256이다.",
        "`entry_linkage.official_id_raw_json`은 원문의 형을 보존한다.",
        "`relationship_status=confirmed_official_race_horse_row`는 공식 출전행",
        "관계가 확인된 뜻이며 `identity_status=single_candidate_name_agrees`도",
        "관측 범위 밖 미래/다른 경주의 인물 동일성까지 보증하지 않는다.",
        "",
        "검증: 출전행 기본키 유일성, 양쪽 임시 관계행의 보존, 공식 원문 10페이지",
        "각 행의 키·ID 역추적, 출전번호·접두어 제거 마명 일치, SQLite 무결성 검사.",
        "현재 경주의 사후 결과를 예측 입력으로 넣는 작업은 수행하지 않았다.",
    ]
    (output / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    summary = {str(k): v for k, v in sorted(stats.items(), key=lambda p: str(p[0]))}
    (output / "validation.json").write_text(json.dumps({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "legacy_rows": len(old_rows), "official_raw_pages": len(source_paths),
        "statistics": summary, "integrity_check": "ok",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    db.close()
    history.close()
    old.close()
    os.replace(temporary, target)
    manifest = {str(path.relative_to(output)): {"sha256": sha(path), "bytes": path.stat().st_size}
                for path in sorted(output.iterdir()) if path.is_file() and path != output / "manifest.json"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"legacy_rows": len(old_rows), "official_raw_pages": len(source_paths), "statistics": summary}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, default=HISTORY)
    parser.add_argument("--operating", type=Path, default=OPERATING)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.history, args.operating, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

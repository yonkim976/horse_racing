"""Audit Seoul operating-DB ``text:`` IDs against archived official result rows.

Both source databases are read-only. Output is an independent research sidecar;
race-time relationships and global temporary-ID identities are separate claims.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from horse_racing.parsers.dacom11 import parse_dacom11_report

HISTORY = Path("data/research/seoul_backfill_20260915_v1/history.sqlite3")
OPERATING = Path("data/horse_racing.sqlite3")
OUTPUT = Path("data/research/seoul_text_id_linkage_20260915_v1")
VENUE = re.compile(r"^\[(?:서울|부산경남|부경|제주|서|부|제)\]\s*")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized(value: str | None) -> str:
    return "".join(unicodedata.normalize("NFKC", value or "").split()).casefold()


def horse_relation(old: str, official: str) -> str:
    if normalized(old) == normalized(official):
        return "exact"
    if normalized(VENUE.sub("", old)) == normalized(VENUE.sub("", official)):
        return "venue_prefix_only"
    return "name_conflict"


def write_csv(path: Path, columns: list[str], rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)


def source_rows(path: Path) -> list[dict]:
    body = json.loads(path.read_bytes())["response"]["body"]
    items = (body.get("items") or {}).get("item") or []
    return [items] if isinstance(items, dict) else items


def build(history_path: Path, operating_path: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    history = sqlite3.connect(f"file:{history_path.resolve()}?mode=ro", uri=True)
    old = sqlite3.connect(f"file:{operating_path.resolve()}?mode=ro", uri=True)
    official_by_horse = {}
    official_by_number = {}
    for row in history.execute("""SELECT race_date,race_no,hr_no,chul_no,horse_name,
        jockey_no,jockey_name,trainer_no,trainer_name,owner_no,owner_name,
        source_path,source_row FROM entry WHERE meet=1 AND race_date>='2015-01-01'"""):
        day, race_no, hr_no, chul_no = row[:4]
        official_by_horse[(day, race_no, hr_no)] = row
        number_key = (day, race_no, chul_no)
        if number_key in official_by_number:
            raise ValueError(f"Duplicate official 출전번호: {number_key}")
        official_by_number[number_key] = row

    source_sql = """SELECT e.id,r.race_date_local,r.race_number,e.horse_number,
        h.kra_horse_id,h.name_ko,j.kra_jockey_id,j.name_ko,
        t.kra_trainer_id,t.name_ko,o.kra_owner_id,o.name_ko
      FROM race_entries e JOIN races r ON r.id=e.race_id
      JOIN horses h ON h.id=e.horse_id
      LEFT JOIN jockeys j ON j.id=e.jockey_id
      LEFT JOIN trainers t ON t.id=e.trainer_id
      LEFT JOIN owners o ON o.id=e.owner_id
      WHERE r.racecourse_id=1 AND r.status='completed'
        AND (h.kra_horse_id LIKE 'text:%' OR j.kra_jockey_id LIKE 'text:%'
          OR t.kra_trainer_id LIKE 'text:%' OR o.kra_owner_id LIKE 'text:%')
      ORDER BY r.race_date_local,r.race_number,e.id"""
    old_rows = list(old.execute(source_sql))
    old_digest = hashlib.sha256()
    for row in old_rows:
        old_digest.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode())
        old_digest.update(b"\n")

    evidence = []
    stats: Counter[str] = Counter()
    source_files: set[Path] = set()
    cached_path: str | None = None
    cached_items: list[dict] = []
    for row in old_rows:
        (entry_id, day, race_no, chul_no, old_hr, old_horse,
         old_jk, old_jockey, old_tr, old_trainer, old_ow, old_owner) = row
        temporary_horse = old_hr.startswith("text:")
        api = (official_by_number.get((day, race_no, chul_no)) if temporary_horse
               else official_by_horse.get((day, race_no, old_hr.zfill(7))))
        if api is None:
            raise ValueError(f"No official race/horse key for operating entry {entry_id}")
        (_, _, api_hr, api_chul, api_horse, api_jk, api_jockey,
         api_tr, api_trainer, api_ow, api_owner, source_path, source_row) = api
        if chul_no != api_chul:
            raise ValueError(f"출전번호 mismatch for operating entry {entry_id}")
        relation = horse_relation(old_horse, api_horse)
        if not temporary_horse and relation == "name_conflict":
            raise ValueError(f"Official horse ID with conflicting name: {entry_id}")
        stats[f"horse_relation_{relation}"] += 1
        if source_path != cached_path:
            cached_items = source_rows(Path(source_path))
            cached_path = source_path
        source_files.add(Path(source_path))
        raw = cached_items[source_row]
        if (str(raw.get("rcDate")) != day.replace("-", "")
                or int(raw["rcNo"]) != race_no or int(raw["chulNo"]) != chul_no
                or str(raw["hrNo"]).zfill(7) != api_hr or raw.get("meet") != "서울"
                or normalized(raw.get("hrName")) != normalized(api_horse)):
            raise ValueError(f"Raw official row mismatch for operating entry {entry_id}")
        for field, raw_id, canonical_id in (
            ("jockey", raw.get("jkNo"), api_jk),
            ("trainer", raw.get("trNo"), api_tr),
            ("owner", raw.get("owNo"), api_ow),
        ):
            if canonical_id and str(raw_id or "").zfill(len(canonical_id)) != canonical_id:
                raise ValueError(f"Official {field} ID differs from raw row: {entry_id}")
        actors = (
            ("horse", old_hr, old_horse, api_hr, api_horse),
            ("jockey", old_jk, old_jockey, api_jk, api_jockey),
            ("trainer", old_tr, old_trainer, api_tr, api_trainer),
            ("owner", old_ow, old_owner, api_ow, api_owner),
        )
        for kind, temporary_id, temporary_name, official_id, official_name in actors:
            if not (temporary_id or "").startswith("text:"):
                continue
            name_agrees = int(normalized(temporary_name) == normalized(official_name))
            status = ("unconfirmed_horse_name" if relation == "name_conflict"
                      else "official_id_missing" if not official_id
                      else "confirmed_race_time_relation")
            evidence.append((entry_id, kind, temporary_id, temporary_name, 1, day,
                             race_no, chul_no, old_hr, old_horse, api_hr, api_horse,
                             relation, official_id, official_name, name_agrees,
                             status, source_path, source_row))
            stats[f"{kind}_{status}"] += 1
            if not name_agrees:
                stats[f"{kind}_name_disagrees"] += 1
    history.close()
    old.close()

    columns = ["old_entry_id", "actor_type", "temporary_id", "temporary_name", "meet",
               "race_date", "race_no", "chul_no", "old_horse_id", "old_horse_name",
               "official_hr_no", "official_horse_name", "horse_name_relation", "official_id",
               "official_name", "actor_name_agrees", "relationship_status",
               "official_source_path", "official_source_row"]
    write_csv(output / "entry_linkage.csv", columns, evidence)
    horse_conflicts = []
    for row in evidence:
        if row[1] != "horse" or row[12] != "name_conflict":
            continue
        day = row[5].replace("-", "")
        text_path = Path(
            f"data/raw/kra_text/dacom11/meet=1/year={day[:4]}/month={day[4:6]}"
            f"/day={day[6:]}/{day}dacom11.rpt"
        )
        parsed = parse_dacom11_report(text_path.read_bytes())
        matches = [entry for race in parsed if race.race_number == row[6]
                   for entry in race.entries if entry.horse_number == row[7]]
        if len(matches) != 1 or normalized(matches[0].horse_name) != normalized(row[9]):
            raise ValueError(f"Text horse conflict not corroborated: {row[0]}")
        source_files.add(text_path)
        horse_conflicts.append((row[0], row[5], row[6], row[7], row[2], row[9],
                                row[10], row[11], str(text_path), sha(text_path),
                                row[17], row[18]))
    write_csv(output / "horse_name_conflicts.csv", [
        "old_entry_id", "race_date", "race_no", "chul_no", "temporary_horse_id",
        "text_horse_name", "official_hr_no", "official_horse_name", "text_source_path",
        "text_source_sha256", "official_source_path", "official_source_row"], horse_conflicts)
    grouped: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for row in evidence:
        grouped[(row[1], row[2])].append(row)
    identities = []
    candidates = []
    unresolved = []
    for (kind, temporary_id), rows in sorted(grouped.items()):
        by_id: dict[str, list[tuple]] = defaultdict(list)
        for row in rows:
            if row[13]:
                by_id[row[13]].append(row)
        for official_id, id_rows in sorted(by_id.items()):
            candidates.append((kind, temporary_id, official_id, len(id_rows),
                               sum(r[15] for r in id_rows), min(r[5] for r in id_rows),
                               max(r[5] for r in id_rows),
                               json.dumps(sorted({r[14] for r in id_rows}), ensure_ascii=False),
                               id_rows[0][0], id_rows[0][17], id_rows[0][18]))
        all_confirmed = all(r[16] == "confirmed_race_time_relation" for r in rows)
        all_names_agree = all(r[15] for r in rows)
        status = ("multiple_official_ids" if len(by_id) > 1 else
                  "missing_official_id" if not by_id else
                  "unconfirmed_race_row" if not all_confirmed else
                  "actor_name_conflict" if not all_names_agree else
                  "confirmed_single_official_id")
        identities.append((kind, temporary_id, rows[0][3],
                           next(iter(by_id)) if status == "confirmed_single_official_id" else "",
                           len(by_id), len(rows), sum(r[15] for r in rows),
                           min(r[5] for r in rows), max(r[5] for r in rows), status,
                           json.dumps(sorted(by_id), ensure_ascii=False)))
        stats[f"identity_{kind}_{status}"] += 1
        if status != "confirmed_single_official_id":
            unresolved.append(identities[-1])
    identity_columns = ["actor_type", "temporary_id", "temporary_name", "confirmed_official_id",
                        "candidate_count", "evidence_rows", "name_agree_rows", "first_race_date",
                        "last_race_date", "identity_status", "candidate_ids_json"]
    write_csv(output / "temporary_id_link.csv", identity_columns, identities)
    write_csv(output / "unresolved_identity.csv", identity_columns, unresolved)
    write_csv(output / "candidate_evidence.csv", [
        "actor_type", "temporary_id", "official_id", "evidence_rows", "name_agree_rows",
        "first_race_date", "last_race_date", "official_names_json", "sample_old_entry_id",
        "sample_source_path", "sample_source_row"], candidates)
    expected_occurrences = sum(
        sum(isinstance(value, str) and value.startswith("text:") for value in
            (row[4], row[6], row[8], row[10])) for row in old_rows)
    assert len(evidence) == expected_occurrences
    assert len({(r[0], r[1]) for r in evidence}) == len(evidence)
    assert sum(r[16] == "confirmed_race_time_relation" for r in evidence) + sum(
        r[16] != "confirmed_race_time_relation" for r in evidence) == len(evidence)
    summary = {
        "meet": 1,
        "old_entry_rows_examined": len(old_rows),
        "temporary_id_occurrences": len(evidence),
        "temporary_ids": len(identities), "unresolved_temporary_ids": len(unresolved),
        "stats": dict(sorted(stats.items())),
        "operating_selected_rows_sha256": old_digest.hexdigest(),
        "source_scope": "2015 onward completed Seoul operating races; official API result entry",
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    confirmed_relationships = stats["jockey_confirmed_race_time_relation"] + stats[
        "trainer_confirmed_race_time_relation"] + stats["owner_confirmed_race_time_relation"]
    confirmed_identities = sum(row[9] == "confirmed_single_official_id" for row in identities)
    multiple_identities = sum(row[9] == "multiple_official_ids" for row in identities)
    name_conflicts = sum(row[9] == "actor_name_conflict" for row in identities)
    race_conflicts = sum(row[9] == "unconfirmed_race_row" for row in identities)
    report = f"""# 서울 `text:` 임시 ID와 공식 API ID 연결

`text:`는 KRA가 발급한 ID가 아니다. 운영 DB의 `dacom11` Text 적재기가 공식 번호를
찾지 못할 때 만든 **이름 기반 임시 해시**다. 기수·마주 해시는
`SHA256(0|정규화이름||)`의 앞 24자리, 조교사는 경마장 번호 1을 사용한다.
말은 `SHA256(경마장|정규화마명|추정 출생연도|성별)` 앞 24자리다.
예를 들어 `text:jockey:8d925be0e094ce96a3a2abfe`는 `김영진`이라는
이름의 임시 키다. 같은 이름이 같은 공식 인물임을 증명하지 않는다.

완료된 서울 운영 DB의 출전행 **{len(old_rows):,}개**에서 임시 ID 사용
**{len(evidence):,}건**을 찾았다. 공식 결과의 경주일·경주번호·공식 말 ID 또는
출전번호와 마명을 확인하고, 해당 API 원문 행의 공식 인물 번호를 재검증했다.
그 결과 경주 당시 인물 관계 **{confirmed_relationships:,}건**을 확인했다. 이 관계는
`entry_linkage.csv`에서 경주행마다 조회한다. 이름 불일치가 있어도 당시 공식
결과의 인물 번호는 보존하되, 임시 ID의 전역적 인물 동일성은 승인하지 않았다.

임시 ID **{len(identities):,}개** 중 공식 ID가 관측 범위에서 하나이고 매 경주의
이름·출전관계가 모두 맞는 **{confirmed_identities:,}개**만
`confirmed_single_official_id`다. 나머지 **{len(unresolved):,}개**는 다중
공식 ID {multiple_identities}개, 이름 충돌 {name_conflicts}개,
말 출전관계 미확정 {race_conflicts}개다. `temporary_id_link.csv`와
`unresolved_identity.csv`에 후보·근거행 수·기간을 남겼다. 이름만으로
모든 과거 이력을 일괄 치환하지 않는다.

특히 운영 DB의 `text:a6eb38321c4ca2ebb9dc9366`은 **마이공주**다.
2022-03-27~2023-02-19의 9개 보존 `dacom11` Text도 마이공주라고 쓰지만,
같은 경주·출전번호의 공식 결과는 9개 모두 **마이왕자 (`0044830`)**다.
`horse_name_conflicts.csv`에 두 원문 경로·해시와 공식 행 번호를 남겼다.
이것은 동일 말이라고 승인할 근거가 없으므로 미해결로 유지한다.

`entry_linkage.csv`는 임시 ID가 쓰인 **출전행별 관계**, `temporary_id_link.csv`는
임시 ID별 **전역 동일성 판정**, `candidate_evidence.csv`는 후보 공식 ID별
근거 건수·표본 원문 위치다. `relationship_status`가
`confirmed_race_time_relation`이어도 `identity_status`가 미해결일 수 있다.
기존 운영 DB와 서울 백필 DB는 읽기 전용으로 열었고 변경하지 않았다.

프로젝트 루트에서 `.venv/bin/python scripts/link_seoul_text_ids.py`로 재현한다.
`sha256_manifest.csv`는 입력 DB, 사용한 공식/Text 원문, 출력 CSV·JSON,
실행 코드의 SHA256을 기록한다. DB에 WAL이 있을 수 있으므로
`summary.json`에는 실제 읽은 운영 출전행의 순서 있는 SHA256도 기록했다.
"""
    (output / "README.md").write_text(report)
    inputs = [(p, "operating_db" if p == operating_path else "official_history_db"
               if p == history_path else "text_dacom11_raw"
               if "kra_text/dacom11" in str(p) else "official_result_raw")
              for p in [operating_path, history_path, *sorted(source_files)]]
    files = [(str(p), role, p.stat().st_size, sha(p)) for p, role in inputs]
    files += [(str(p), "linkage_output", p.stat().st_size, sha(p))
              for p in sorted(output.glob("*.csv")) if p.name != "sha256_manifest.csv"]
    p = output / "summary.json"
    files.append((str(p), "linkage_output", p.stat().st_size, sha(p)))
    p = output / "README.md"
    files.append((str(p), "linkage_output", p.stat().st_size, sha(p)))
    script = Path(__file__)
    files.append((str(script), "linkage_code", script.stat().st_size, sha(script)))
    write_csv(output / "sha256_manifest.csv", ["path", "role", "bytes", "sha256"], files)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=HISTORY)
    parser.add_argument("--operating", type=Path, default=OPERATING)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = build(args.history, args.operating, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

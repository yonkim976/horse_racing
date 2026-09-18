"""Independently verify the isolated Busan trial linkage and write its report."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from build_busan_trial_linkage import (
    HISTORY, OPERATING, OUTPUT, RAW, ROOT, digest, key, metadata_lines, result_lines,
)


def check() -> None:
    db = sqlite3.connect(f"file:{(OUTPUT / 'trials.sqlite3').resolve()}?mode=ro", uri=True)
    old = sqlite3.connect(f"file:{OPERATING.resolve()}?mode=ro", uri=True)
    history = sqlite3.connect(f"file:{HISTORY.resolve()}?mode=ro", uri=True)
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    files = db.execute("SELECT count(*) FROM source_file").fetchone()[0]
    trials = db.execute("SELECT count(*) FROM trial").fetchone()[0]
    rows = db.execute("SELECT count(*) FROM trial_entry").fetchone()[0]
    text_rows = db.execute("""SELECT count(*) FROM trial_entry
      WHERE source_path IN (SELECT path FROM source_file)""").fetchone()[0]
    api_rows = db.execute("SELECT count(*) FROM official_trial_api_entry").fetchone()[0]
    status = dict(db.execute("SELECT link_status,count(*) FROM trial_entry GROUP BY link_status"))
    assert (files, trials, text_rows, api_rows, rows) == (1053, 3400, 29736, 29762, 29762)
    assert sum(status.values()) == rows
    assert db.execute("SELECT count(*) FROM trial_entry WHERE finish_raw IS NULL OR judgement_raw IS NULL").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM trial_entry WHERE link_status='confirmed' AND hr_no IS NULL").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM trial_entry WHERE link_status!='confirmed' AND hr_no IS NOT NULL").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM trial WHERE label_scope!='trial_only'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM race_entry_trial_history").fetchone()[0] == history.execute("SELECT count(*) FROM research_entry").fetchone()[0]
    assert db.execute("SELECT count(*) FROM race_entry_trial_history WHERE last_confirmed_trial_date>=race_date").fetchone()[0] == 0

    file_map = {path: (expected, trials_count, row_count) for path, expected, _, trials_count, row_count
                in db.execute("SELECT path,sha256,bytes,trial_count,entry_count FROM source_file")}
    physical_metadata = physical_scores = 0
    for path_text, (expected, _, row_count) in file_map.items():
        path = Path(path_text)
        assert path.is_file() and digest(path) == expected
        raw = path.read_text(encoding="cp949", errors="replace")
        metadata = metadata_lines(raw)
        scores = result_lines(raw)
        assert len(metadata) == len(scores) == row_count, path
        physical_metadata += len(metadata)
        physical_scores += len(scores)
    assert physical_metadata == physical_scores == text_rows

    # The old partial parser's 5,413 rows must all survive in the new table.
    new_keys = {(day, no, chul, name) for day, no, chul, name in db.execute("""
      SELECT trial_date,trial_no,chul_no,horse_name_raw FROM trial_entry""")}
    old_text_rows = list(history.execute("""
      SELECT trial_date,trial_no,chul_no,horse_name FROM trial_result_text"""))
    assert len(old_text_rows) == 5413
    assert all(row in new_keys for row in old_text_rows)

    # Existing 2025+ operating trial rows provide a separate exact-row check.
    modern = list(old.execute("""
      SELECT t.trial_date_local,t.trial_race_number,r.horse_number,
             r.horse_name_raw,h.kra_horse_id
      FROM running_trial_results r JOIN running_trials t ON t.id=r.running_trial_id
      LEFT JOIN horses h ON h.id=r.horse_id WHERE t.meet_code=3"""))
    assert len(modern) == 2562
    current = {(day, no, chul): (name, hr) for day, no, chul, name, hr in db.execute("""
      SELECT trial_date,trial_no,chul_no,horse_name_raw,hr_no
      FROM trial_entry WHERE trial_date>='2025-01-01'""")}
    assert len(current) == len(modern)
    for day, no, chul, name, hr in modern:
        observed = current[(day, no, chul)]
        assert key(name) == key(observed[0])
        if hr:
            assert observed[1] == hr

    # The official API now succeeds. Historical failed attempts stay in the
    # append-only request ledger, while all successful annual pages are hashed.
    api_ledger = OUTPUT / "api_raw/request_ledger.jsonl"
    api_events = [json.loads(line) for line in api_ledger.read_text().splitlines() if line]
    assert any(event.get("http_status") == 403 for event in api_events)
    assert any(event.get("result_code") == "30" for event in api_events)
    assert all("ServiceKey" not in json.dumps(event) for event in api_events)
    latest_success = {}
    for event in api_events:
        if event.get("status") in {"downloaded", "reused"} and event.get("path"):
            latest_success[(event["scope"]["tr_year"], event["page"])] = event
    assert len(latest_success) == 23
    assert sum(event["response_rows"] for event in latest_success.values()) == api_rows
    for event in latest_success.values():
        path = Path(event["path"])
        assert path.is_file() and digest(path) == event["sha256"]
    api_with_hr = db.execute("""SELECT count(*) FROM official_trial_api_entry
      WHERE hr_no IS NOT NULL AND hr_no!=''""").fetchone()[0]
    api_only = db.execute("""SELECT count(*) FROM trial_entry
      WHERE source_path NOT IN (SELECT path FROM source_file)""").fetchone()[0]
    assert (api_with_hr, api_only) == (29730, 26)
    assert db.execute("""SELECT count(*) FROM trial_entry
      WHERE link_method IN ('official_trial_api_exact_key','official_trial_api_only_row')""").fetchone()[0] == api_with_hr
    assert db.execute("""SELECT count(*) FROM trial_entry t
      JOIN official_trial_api_entry a USING(meet,trial_date,trial_no,chul_no)
      WHERE a.hr_no IS NOT NULL AND a.hr_no!='' AND t.hr_no!=a.hr_no""").fetchone()[0] == 0

    name_differences = 0
    for text_name, api_name in db.execute("""SELECT t.horse_name_raw,a.horse_name_raw
      FROM trial_entry t JOIN official_trial_api_entry a
      USING(meet,trial_date,trial_no,chul_no)
      WHERE t.source_path IN (SELECT path FROM source_file)"""):
        name_differences += key(text_name) != key(api_name)
    assert name_differences == 77

    yearly = list(csv.DictReader((OUTPUT / "coverage_year.csv").open(encoding="utf-8")))
    assert sum(int(row["text_parsed_entries"]) for row in yearly) == text_rows
    assert sum(int(row["official_api_entries"]) for row in yearly) == api_rows
    assert sum(int(row["api_only_entries"]) for row in yearly) == api_only
    assert sum(int(row["unified_entries"]) for row in yearly) == rows
    assert sum(int(row["confirmed"]) for row in yearly) == status["confirmed"]
    assert sum(int(row["ambiguous"]) for row in yearly) == status.get("ambiguous", 0)
    assert sum(int(row["unmatched"]) for row in yearly) == status.get("unmatched", 0)
    unresolved_count = sum(1 for _ in csv.DictReader((OUTPUT / "unresolved.csv").open(encoding="utf-8")))
    assert unresolved_count == status.get("ambiguous", 0) + status.get("unmatched", 0)

    code_paths = [ROOT / "scripts/build_busan_trial_linkage.py",
                  ROOT / "scripts/collect_busan_trial_api.py",
                  ROOT / "scripts/verify_busan_trial_linkage.py",
                  ROOT / "src/horse_racing/parsers/running_trials.py"]
    code_manifest = {str(path): {"sha256": digest(path), "bytes": path.stat().st_size}
                     for path in code_paths}
    (OUTPUT / "code_manifest.json").write_text(
        json.dumps(code_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "meet": 3, "source_files": files, "trials": trials,
        "physical_metadata_rows": physical_metadata,
        "physical_score_rows": physical_scores,
        "trial_entries": rows, "link_status": status,
        "text_trial_entries": text_rows,
        "official_api_entries": api_rows,
        "official_api_entries_with_hr_no": api_with_hr,
        "official_api_only_entries": api_only,
        "text_api_name_differences": name_differences,
        "old_partial_text_rows_preserved": len(old_text_rows),
        "modern_operating_rows_exactly_reconciled": len(modern),
        "research_entry_trial_history": db.execute("SELECT count(*) FROM race_entry_trial_history").fetchone()[0],
        "input_manifest_matching": all(digest(Path(path)) == expected for path, expected in
            db.execute("SELECT path,sha256 FROM input_manifest")),
        "api_result": "SUCCESS_2004_2026",
        "integrity_check": "ok", "future_trial_history_rows": 0,
    }
    assert summary["input_manifest_matching"]
    (OUTPUT / "verification.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = [
        "# 부경 주행심사 원문 복원·공식 말 ID 연결",
        "",
        "범위는 KRA meet=3 부산경남 주행심사/주행검사/능력검사 Text 원문과",
        "공식 주행심사 상세결과 API의 2004-11-07~2026-09-10 자료이며,",
        "정식 경주 라벨과 완전히 분리했다. 보관 1,053파일에서",
        "3,397회·29,736출전행을 복원했다. 첫 출전표와",
        "성적표의 물리적 행 수가 각각 29,736으로 일치한다. 모든 행에 원문 파일",
        "및 실제 줄 번호를 보존했다. 공식 API 29,762행과 전부 키 대조했고,",
        "Text에 없던 2019-11-30의 3회·26행을 추가해 통합 표는",
        f"{trials:,}회·{rows:,}행이다. Text의 2회는 출전행이 없는 빈 표제다.",
        "",
        f"공식 말 `hrNo` 연결: **{status['confirmed']:,}/{rows:,} ({status['confirmed']/rows:.2%})**.",
        f"미해결: 모호 {status.get('ambiguous', 0)}행, 후보 없음 {status.get('unmatched', 0)}행.",
        "후보와 출생일·성별·조교월·경주 당시 조교사 근거는 `candidate`와",
        "`unresolved.csv`에 남겼다. 이름만으로 후보를 확정하지 않았다.",
        "",
        "| 연도 | Text 파일 | 통합 심사 | Text 행 | API 행 | API 보강 | 통합 행 | ID 확정 | 모호 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    report += [f"| {r['year']} | {int(r['text_source_files']):,} | {int(r['unified_trial_count']):,} | "
               f"{int(r['text_parsed_entries']):,} | {int(r['official_api_entries']):,} | "
               f"{int(r['api_only_entries']):,} | {int(r['unified_entries']):,} | "
               f"{int(r['confirmed']):,} | {int(r['ambiguous']):,} |" for r in yearly]
    report += [
        "",
        "연결 근거는 공식 `hrNo`가 있는 부경 일별 조교와 말 프로필의 출생일·성별,",
        "경주 당시 조교사, 2025년 이후 기존 공식 주행심사 행이다. 연령의",
        "생일 기준/연도 기준 차이를 별도 검증했고, 일부 12월 말 자료의 다음 해",
        "연령 표기는 같은 날 여러 말에서 함께 나타나며 공식 조교·경주 이력으로",
        "추가 확인된 행만 연결했다. 2012-05-19 파일의 표제 2회는 2012-05-17로",
        "쓰여 있어 표제일을 보존하고 파일명 불일치를 원장에 남겼다.",
        "",
        "과거 부분 파서가 보존한 5,413행은 새 표의 경주일·회차·출전번호·마명으로",
        "전부 대조됐다. 2025~2026 운영 DB 부경 2,562행도 새 원문과 키·마명이",
        "전부 일치하며 기존에 공식 말 ID가 있던 2,558행의 ID도 일치한다.",
        "성적표의 착순·판정은 29,736행 전부 파싱했고 `취`·`경` 원문 판정도",
        "다른 상태로 합치지 않았다. 주행심사 구간기록의 의미는 정식 경주 구간과",
        "합치지 않고 원천별 원문 필드로 보존했다.",
        "",
        "[공식 주행심사 상세결과 API](https://www.data.go.kr/data/15056974/openapi.do)는",
        "재활성화 후 2004~2026년 23개 연도 요청에 성공했다. 연도별 원문 JSON과",
        "요청 범위·페이지·응답 건수·시각·SHA256을 `api_raw`에 보존했다.",
        "API의 29,762행 중 29,730행에 공식 `hrNo`가 있다. Text와 API의",
        "정확 키가 일치한 행에서 기존 공식 ID 충돌은 0건이었다. 과거 미해결",
        "51행 중 46행을 API ID로 복원했고, API에 `hrNo`와 `hrName`이 모두",
        "빈 해피머니 3행·지니블레이드 1행·스티캣 1행만 모호 상태로 남겼다.",
        "이 5행은 이름 하나로 추정하지 않았다. Text/API 마명 차이 77행은",
        "개명 또는 API 공란을 포함하므로 양쪽 원문 값을 그대로 보존했다.",
        "",
        "`race_entry_trial_history`는 역사 연구 출전행 167,960개에 확정된",
        "과거 주행심사 건수·합격 건수·최근 심사일을 `trial_date < race_date`로",
        "연결한다. 같은 이름의 미해결 과거 사건은 별도 의심 건수로 표시하므로",
        "확정 이력 0건을 사건 자체의 부재로 단정하지 않는다. 당시 공개시각은",
        "증명되지 않아 모든 연구 입력은 `retrospective_only`다.",
        "운영 DB·모델·registry·예측·베팅 코드는 수정하지 않았다.",
        "",
        "재현: 작업 루트에서 `PYTHONPATH=src .venv/bin/python",
        "scripts/build_busan_trial_linkage.py`를 실행한 뒤 `PYTHONPATH=src",
        ".venv/bin/python scripts/verify_busan_trial_linkage.py`를 실행한다.",
        "공식 API 갱신은 `PYTHONPATH=src .venv/bin/python",
        "scripts/collect_busan_trial_api.py --start-year 2004 --end-year 2026`으로",
        "연도별 원문을 중복 없이 재사용·수집한 뒤 같은 빌드 명령으로 반영한다.",
        "",
        "표: `trial` 기본키 `(meet,trial_date,trial_no)`; `trial_entry` 기본키",
        "`(meet,trial_date,trial_no,chul_no)`; `candidate`는 각 후보의 근거;",
        "`official_trial_api_entry`는 API 원문 필드와 공식 인물·말 ID;",
        "`source_file`은 Text 원문 SHA256·행 수; `race_entry_trial_history`는",
        "경주 전 확정 이력. `link_status=confirmed/ambiguous/unmatched`를",
        "구분한다. `manifest.json`은 출력·코드·API 원장의 해시를 담는다.",
    ]
    (OUTPUT / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    manifest_files = [p for p in OUTPUT.rglob("*") if p.is_file() and p.name != "manifest.json"]
    (OUTPUT / "manifest.json").write_text(json.dumps({str(p.relative_to(OUTPUT)): {
        "sha256": digest(p), "bytes": p.stat().st_size} for p in sorted(manifest_files)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    old.close()
    history.close()
    db.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    check()

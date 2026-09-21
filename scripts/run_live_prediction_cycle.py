"""One guarded race-day sync and Jeju prediction publication cycle.

This deliberately does not publish Thoroughbred or scratched Jeju races until
their current-card feature rebuilds are implemented and verified.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/bin/python"
KST = ZoneInfo("Asia/Seoul")
PUBLISHER = (
    ROOT / ".agents/skills/horse-racing-prediction-publisher/scripts/publish_prediction_bundle.py"
)
VALIDATOR = (
    ROOT / ".agents/skills/horse-racing-prediction-publisher/scripts/validate_prediction_payload.py"
)
RESOLVER = ROOT / ".agents/skills/horse-racing-prediction-publisher/scripts/resolve_main_model.py"
OFFICIAL_INPUTS_BY_DATE = {
    "20260919": ROOT / "data/predictions/jeju_20260919_official_inputs_20260918_attempt2",
}


def _run(command: list[str], *, stage: str, timeout: int) -> str:
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        # Do not echo stderr: lower-level network/DB tools might include credentials.
        raise RuntimeError(f"{stage} 실패 (exit={result.returncode})")
    return result.stdout.strip()


def _database_url(project_ref: str, secret: str, gcp_project: str) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from sync_live_race_day import _database_url as load_url

    return load_url(project_ref, secret, gcp_project)


def _snapshot(connection, race_date: str) -> dict[str, int]:
    values = (
        connection.execute(
            text("""
        select
          (select count(*) from race_results rr
            join race_entries re on re.id=rr.race_entry_id
            join races r on r.id=re.race_id
            join racecourses rc on rc.id=r.racecourse_id
            where r.race_date_local=cast(:race_date as date)
              and rc.kra_meet_code in (1,2)
              and rr.finish_position between 1 and 89
              and re.scratched is false) finishers,
          (select count(*) from jockey_changes
            where race_date_local=cast(:race_date as date) and meet_code in (1,2)) jockey_changes,
          (select count(*) from race_scratches
            where race_date_local=cast(:race_date as date) and meet_code in (1,2)) scratches
        """),
            {"race_date": race_date},
        )
        .mappings()
        .one()
    )
    return {key: int(value) for key, value in values.items()}


def _jeju_candidates(connection, race_date: str) -> list[int]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_jeju_live_update_bundles import (
        _card_has_changed,
        _db_entries,
        _published_card,
    )

    by_race: dict[int, list[dict]] = {}
    for entry in _db_entries(connection, race_date):
        by_race.setdefault(int(entry["race_number"]), []).append(entry)
    now_ms = int(datetime.now(KST).timestamp() * 1000)
    candidates: list[int] = []
    for race_no, entries in by_race.items():
        if any(row["scratched"] for row in entries):
            continue
        if entries[0]["race_status"] == "completed":
            continue
        if (
            not entries[0]["scheduled_at_ms"]
            or now_ms > int(entries[0]["scheduled_at_ms"]) - 30 * 60 * 1000
        ):
            continue
        latest, published = _published_card(connection, int(entries[0]["race_id"]))
        if latest is not None and _card_has_changed(entries, published):
            candidates.append(race_no)
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="YYYYMMDD, Asia/Seoul")
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--gcp-secret", required=True)
    parser.add_argument("--gcp-project", required=True)
    parser.add_argument("--skip-sync", action="store_true", help="read-only test option")
    parser.add_argument("--dry-run", action="store_true", help="never publish predictions")
    parser.add_argument("--confirm-write", action="store_true")
    args = parser.parse_args()
    now = datetime.now(KST)
    if args.date != now.strftime("%Y%m%d"):
        print(json.dumps({"skipped": "requested date is not today in KST"}))
        return 0
    if now.hour >= 19:
        print(json.dumps({"skipped": "race-day automation ended at 19:00 KST"}))
        return 0
    if not args.dry_run and not args.confirm_write:
        parser.error("운영 예측 게시에는 --confirm-write가 필요합니다")

    lock_path = ROOT / "data/predictions/live_cycle.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"skipped": "another live prediction cycle is running"}))
            return 0

        for domain in ("jeju", "thoroughbred"):
            _run(
                [str(PYTHON), str(RESOLVER), "--repo-root", ".", "--domain", domain],
                stage=f"{domain} 활성 모델 검증",
                timeout=60,
            )

        database_url = _database_url(args.project_ref, args.gcp_secret, args.gcp_project)
        engine = create_engine(database_url, pool_size=1, max_overflow=0, pool_pre_ping=True)
        with engine.connect() as connection:
            before = _snapshot(connection, f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:]}")

        if not args.skip_sync:
            _run(
                [
                    str(PYTHON),
                    str(ROOT / "scripts/sync_live_race_day.py"),
                    "--date",
                    args.date,
                    "--meets",
                    "1",
                    "2",
                    "--project-ref",
                    args.project_ref,
                    "--gcp-secret",
                    args.gcp_secret,
                    "--gcp-project",
                    args.gcp_project,
                    "--page-size",
                    "100",
                    "--confirm-write",
                ],
                stage="공식 데이터 동기화",
                timeout=600,
            )

        with engine.connect() as connection:
            date_iso = f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:]}"
            after = _snapshot(connection, date_iso)
            candidates = _jeju_candidates(connection, date_iso)
        engine.dispose()
        new_official = {key: after[key] - before[key] for key in after}
        if not candidates:
            print(
                json.dumps(
                    {
                        "date": args.date,
                        "published": [],
                        "new_official_records": new_official,
                        "skipped": "no changed eligible Jeju card",
                        "thoroughbred": (
                            "not published: current-card feature recomputation is not verified"
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        stamp = datetime.now(KST).strftime("%Y%m%dT%H%M%S%z")
        inference = ROOT / "data/predictions" / f"auto_jeju_{stamp}"
        official_inputs = OFFICIAL_INPUTS_BY_DATE.get(args.date)
        if official_inputs is None or not (official_inputs / "manifest.json").is_file():
            raise RuntimeError("검증된 제주 공식 보조 입력을 찾지 못했습니다")
        _run(
            [
                str(PYTHON),
                str(ROOT / "scripts/predict_jeju_live_hy_r_form.py"),
                "--date",
                args.date,
                "--output",
                str(inference),
                "--official-inputs",
                str(official_inputs),
            ],
            stage="HY_R_FORM 예측",
            timeout=300,
        )
        _run(
            [
                str(PYTHON),
                str(VALIDATOR),
                str(inference / "horse_predictions.parquet"),
                "--domain",
                "jeju",
            ],
            stage="HY_R_FORM 출력 검증",
            timeout=30,
        )
        output_root = ROOT / "data/predictions" / f"auto_jeju_bundles_{stamp}"
        built_raw = _run(
            [
                str(PYTHON),
                str(ROOT / "scripts/build_jeju_live_update_bundles.py"),
                "--inference-dir",
                str(inference),
                "--output-root",
                str(output_root),
                "--project-ref",
                args.project_ref,
                "--gcp-secret",
                args.gcp_secret,
                "--gcp-project",
                args.gcp_project,
            ],
            stage="경주별 publication 묶음 생성",
            timeout=180,
        )
        build_summary = json.loads(built_raw)
        published: list[dict] = []
        failures: list[dict] = []
        for item in build_summary["built"]:
            bundle = Path(item["bundle"])
            _run(
                [
                    str(PYTHON),
                    str(VALIDATOR),
                    str(bundle / "runner_predictions.parquet"),
                    "--domain",
                    "jeju",
                    "--publication",
                ],
                stage=f"제주 {item['race_no']}경주 publication 검증",
                timeout=30,
            )
            if args.dry_run:
                continue
            try:
                result = _run(
                    [
                        str(PYTHON),
                        str(PUBLISHER),
                        str(bundle),
                        "--publication-mode",
                        "live",
                        "--expected-project-ref",
                        args.project_ref,
                        "--gcp-secret",
                        args.gcp_secret,
                        "--gcp-project",
                        args.gcp_project,
                        "--confirm-write",
                    ],
                    stage=f"제주 {item['race_no']}경주 게시",
                    timeout=120,
                )
                stored = json.loads(result)
                published.append(
                    {
                        "race_no": item["race_no"],
                        "run_id": stored["prediction_run_id"],
                        "runners": stored["runner_rows"],
                    }
                )
            except RuntimeError as exc:
                failures.append({"race_no": item["race_no"], "error": str(exc)})
        print(
            json.dumps(
                {
                    "date": args.date,
                    "published": published,
                    "new_official_records": new_official,
                    "preflight_jeju_candidates": candidates,
                    "eligible_bundles": build_summary["built"],
                    "skipped": build_summary["skipped"],
                    "failures": failures,
                    "thoroughbred": (
                        "not published: current-card feature recomputation is not verified"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from None

"""Run one scheduled refresh and record only the receipt belonging to this run."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
REFRESH_HOME = ROOT / "jeju/research/20261017_core_refresh"
STATUS_PATH = REFRESH_HOME / "launchd_execution_status.json"
CORE_ARGS = [str(ROOT / ".venv/bin/python"), "-u", "-m", "jeju.refresh.run", "--apply"]


def now_kst() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def open_regular(path: Path, flags: int) -> int:
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        os.close(fd)
        raise ValueError("unsafe_regular_file")
    return fd


def load_state() -> dict[str, Any]:
    try:
        fd = open_regular(STATUS_PATH, os.O_RDONLY)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd, "r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("invalid_status_state")
    return value


def atomic_write_state(value: dict[str, Any]) -> None:
    parent = STATUS_PATH.parent
    if parent.resolve() != parent.absolute() or not parent.is_dir():
        raise ValueError("unsafe_status_directory")
    if STATUS_PATH.is_symlink():
        raise ValueError("unsafe_status_file")
    fd, temporary_name = tempfile.mkstemp(prefix=".launchd-status-", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(value, output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if STATUS_PATH.is_symlink():
            raise ValueError("unsafe_status_file")
        os.replace(temporary, STATUS_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def final_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{") or not candidate.endswith("}"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def receipt_path(stdout_value: dict[str, Any]) -> Path:
    raw = stdout_value.get("manifest")
    if not isinstance(raw, str) or not raw:
        raise ValueError("receipt_path_missing")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    resolved = path.resolve(strict=True)
    resolved.relative_to((REFRESH_HOME / "runs").resolve())
    if path.name != "application_manifest.json" or path.is_symlink():
        raise ValueError("invalid_receipt_path")
    return resolved


def read_receipt(path: Path) -> dict[str, Any]:
    fd = open_regular(path, os.O_RDONLY)
    with os.fdopen(fd, "r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("invalid_receipt")
    return value


def partial_failure_details(receipt: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    failures = receipt.get("source_failures")
    if isinstance(failures, list):
        if failures:
            reasons.append("source_failures")
        source_failure_count = len(failures)
    else:
        source_failure_count = 0
        reasons.append("source_failure_status_unknown")

    coverage = receipt.get("family_coverage")
    if not isinstance(coverage, dict):
        coverage = receipt.get("source_family_coverage")
    family_failures: dict[str, int] = {}
    if isinstance(coverage, dict):
        for family, summary in coverage.items():
            if not isinstance(summary, dict):
                continue
            failed = summary.get("failed")
            if isinstance(failed, int) and not isinstance(failed, bool) and failed > 0:
                family_failures[str(family)] = failed
        if family_failures:
            reasons.append("family_failures")
    else:
        reasons.append("family_coverage_unknown")

    website_status = receipt.get("starting_training_website_status")
    if website_status != "complete":
        reasons.append("starting_training_website_incomplete")
    return {
        "partial_failure": bool(reasons),
        "reasons": reasons,
        "source_failure_count": source_failure_count,
        "family_failures": family_failures,
        "starting_training_website_status": website_status,
    }


def status_record(status: str, *, started_at: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "started_at_kst": started_at, "finished_at_kst": now_kst(), **extra}


def save_execution(execution: dict[str, Any], successful_receipt: dict[str, Any] | None = None) -> None:
    state = load_state()
    state["last_execution"] = execution
    state["updated_at_kst"] = execution["finished_at_kst"]
    if successful_receipt is not None:
        state["last_success"] = {
            "at_kst": execution["finished_at_kst"],
            "run_id": successful_receipt.get("run_id"),
            "receipt": execution.get("receipt"),
            "database_sha256_after": successful_receipt.get("database_sha256_after"),
        }
    atomic_write_state(state)


def execute() -> int:
    started = now_kst()
    # Validate the status destination before a core run can mutate the research DB.
    load_state()
    completed = subprocess.run(
        CORE_ARGS,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        shell=False,
    )
    output = final_json(completed.stdout)
    if completed.returncode == 0 and output and output.get("status") == "already_running":
        execution = status_record("busy_duplicate", started_at=started)
        save_execution(execution)
        print(json.dumps(execution, ensure_ascii=False, separators=(",", ":")), flush=True)
        return 0

    if completed.returncode == 0 and output and output.get("status") == "applied_verified":
        try:
            manifest_path = receipt_path(output)
            receipt = read_receipt(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            execution = status_record(
                "no_receipt",
                started_at=started,
                error_type=type(error).__name__,
            )
            save_execution(execution)
            print(json.dumps(execution, ensure_ascii=False, separators=(",", ":")), flush=True)
            return 1

        if receipt.get("status") != "applied_verified" or not receipt.get("run_id"):
            execution = status_record("invalid_receipt", started_at=started)
            save_execution(execution)
            print(json.dumps(execution, ensure_ascii=False, separators=(",", ":")), flush=True)
            return 1

        details = partial_failure_details(receipt)
        is_partial = details.pop("partial_failure")
        manifest_relative = str(manifest_path.relative_to(ROOT))
        execution = status_record(
            "partial_failure" if is_partial else "success",
            started_at=started,
            run_id=receipt["run_id"],
            receipt=manifest_relative,
            **details,
        )
        save_execution(execution, None if is_partial else receipt)
        print(json.dumps(execution, ensure_ascii=False, separators=(",", ":")), flush=True)
        return 2 if is_partial else 0

    status = output.get("status") if output else None
    execution = status_record(
        "core_failed" if completed.returncode else "no_receipt",
        started_at=started,
        core_exit_code=completed.returncode,
        core_status=status,
        core_error_type=output.get("error_type") if output else None,
    )
    save_execution(execution)
    print(json.dumps(execution, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 1


def main() -> int:
    try:
        return execute()
    except Exception as error:
        # Do not persist exception text or a child traceback; it may contain sensitive context.
        failure = status_record("runner_failed", started_at=now_kst(), error_type=type(error).__name__)
        try:
            save_execution(failure)
        except Exception:
            pass
        print(json.dumps(failure, ensure_ascii=False, separators=(",", ":")), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

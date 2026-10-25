"""Manage the Jeju research refresh LaunchAgent for the current macOS user."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LABEL = "com.horse-racing.jeju-research-refresh"
DOMAIN = f"gui/{os.getuid()}"
TARGET = f"{DOMAIN}/{LABEL}"
PYTHON = ROOT / ".venv/bin/python"
PLIST_PATH = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = Path.home() / "Library/Logs/horse-racing"
OUT_LOG = LOG_DIR / "jeju-research-refresh.out.log"
ERR_LOG = LOG_DIR / "jeju-research-refresh.err.log"
STATUS_PATH = ROOT / "jeju/research/20261017_core_refresh/launchd_execution_status.json"


def secure_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.resolve() != path.absolute() or not path.is_dir():
        raise ValueError("unsafe_directory")
    if path.stat().st_uid != os.getuid():
        raise ValueError("directory_owner_mismatch")
    os.chmod(path, 0o700)


def open_regular(path: Path, flags: int) -> int:
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        os.close(fd)
        raise ValueError("unsafe_regular_file")
    return fd


def configuration() -> dict[str, Any]:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(PYTHON), "-u", "-m", "jeju.refresh.launchd_runner"],
        "WorkingDirectory": str(ROOT),
        "StartCalendarInterval": {"Hour": 22, "Minute": 0},
        "RunAtLoad": False,
        "KeepAlive": False,
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
        },
        "StandardOutPath": str(OUT_LOG),
        "StandardErrorPath": str(ERR_LOG),
    }


def require_kst() -> None:
    local = datetime.now().astimezone()
    localtime = Path("/etc/localtime")
    zone_path = str(localtime.resolve()) if localtime.exists() else ""
    exact_zone = zone_path.endswith("/zoneinfo/Asia/Seoul")
    kst_name = time.tzname[0] == "KST" and time.tzname[1] == "KST"
    if local.utcoffset() != timedelta(hours=9) or not (exact_zone or kst_name):
        raise SystemExit("설치는 시스템 시간대가 Asia/Seoul(KST)인 경우에만 가능합니다.")


def read_owned_plist(path: Path) -> dict[str, Any] | None:
    try:
        fd = open_regular(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as source:
        value = plistlib.load(source)
    if value.get("Label") != LABEL or value.get("WorkingDirectory") != str(ROOT):
        raise SystemExit("기존 LaunchAgent가 지정 label 및 프로젝트 경로 소유 파일과 일치하지 않습니다.")
    return value


def ensure_log_files() -> None:
    secure_directory(LOG_DIR)
    for path in (OUT_LOG, ERR_LOG):
        fd = open_regular(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)


def validate_plist_with_plutil(path: Path) -> None:
    try:
        result = subprocess.run(
            ["plutil", "-lint", str(path)], capture_output=True, text=True, check=False
        )
    except FileNotFoundError as error:
        raise SystemExit("plutil을 찾을 수 없어 LaunchAgent 설치를 중단했습니다.") from error
    if result.returncode != 0:
        raise SystemExit("plutil -lint 실패: " + (result.stderr.strip() or result.stdout.strip()))


def write_plist(path: Path, config: dict[str, Any]) -> None:
    secure_directory(path.parent)
    encoded = plistlib.dumps(config, fmt=plistlib.FMT_XML, sort_keys=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{LABEL}-", suffix=".plist", dir=path.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        validate_plist_with_plutil(temporary)
        if path.is_symlink():
            raise SystemExit("LaunchAgent 대상 파일이 심볼릭 링크라 설치를 거부했습니다.")
        current = path.lstat() if path.exists() else None
        if current is not None and (
            not stat.S_ISREG(current.st_mode)
            or current.st_uid != os.getuid()
            or current.st_nlink != 1
        ):
            raise SystemExit("LaunchAgent 대상이 현재 사용자 소유의 일반 파일이 아닙니다.")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def launchctl_print() -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", "print", TARGET], capture_output=True, text=True, check=False)


def install() -> None:
    require_kst()
    existing = read_owned_plist(PLIST_PATH)
    loaded_state = launchctl_print()
    loaded = loaded_state.returncode == 0
    if existing is None and loaded:
        raise SystemExit("같은 label의 서비스가 로드됐지만 소유 plist가 없어 설치를 거부했습니다.")
    ensure_log_files()
    config = configuration()
    if existing == config and loaded:
        subprocess.run(["launchctl", "enable", TARGET], check=True)
        print(f"{LABEL} 이미 설치됨: 매일 22:00 Asia/Seoul; 실행 중인 작업은 유지")
        return
    if loaded and any(line.strip() == "state = running" for line in loaded_state.stdout.splitlines()):
        raise SystemExit("실행 중인 제주 갱신 작업을 중단하지 않고 재설치를 보류했습니다.")
    write_plist(PLIST_PATH, config)
    if existing is not None and loaded:
        subprocess.run(["launchctl", "bootout", TARGET], check=True)
    subprocess.run(["launchctl", "enable", TARGET], check=True)
    subprocess.run(["launchctl", "bootstrap", DOMAIN, str(PLIST_PATH)], check=True)
    print(f"{LABEL} 설치 완료: 매일 22:00 Asia/Seoul")


def status() -> None:
    result = launchctl_print()
    print(f"{LABEL}: {'loaded' if result.returncode == 0 else 'not_loaded'}")
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.strip().startswith(("state =", "runs =", "last exit code =")):
                print(line.strip())
    print(f"plist: {'installed' if PLIST_PATH.exists() else 'absent'}")
    try:
        fd = open_regular(STATUS_PATH, os.O_RDONLY)
    except FileNotFoundError:
        return
    with os.fdopen(fd, "r", encoding="utf-8") as source:
        saved = json.load(source)
    execution = saved.get("last_execution", {})
    print("last execution:", execution.get("status", "unknown"))
    if execution.get("run_id"):
        print("run_id:", execution["run_id"])


def stop() -> None:
    if read_owned_plist(PLIST_PATH) is None:
        raise SystemExit("소유 LaunchAgent plist가 없어 중지를 거부했습니다.")
    subprocess.run(["launchctl", "disable", TARGET], check=True)
    subprocess.run(["launchctl", "bootout", TARGET], capture_output=True, check=False)
    print(f"{LABEL} stopped; plist preserved")


def run_now() -> None:
    if read_owned_plist(PLIST_PATH) is None:
        raise SystemExit("소유 LaunchAgent plist가 없어 kickstart를 거부했습니다.")
    subprocess.run(["launchctl", "kickstart", TARGET], check=True)
    print(f"{LABEL} kickstart requested")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "stop", "run"))
    args = parser.parse_args()
    if args.action == "install":
        install()
    elif args.action == "status":
        status()
    elif args.action == "stop":
        stop()
    else:
        run_now()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

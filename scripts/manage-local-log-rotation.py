"""Manage ONLY the daily local collector log archive/truncate LaunchAgent."""

import argparse
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.horse-racing.log-rotation"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "stop"))
    args = parser.parse_args()
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{LABEL}"
    if args.action == "status":
        raise SystemExit(subprocess.run(["launchctl", "print", target], check=False).returncode)
    if args.action == "stop":
        subprocess.run(["launchctl", "disable", target], check=True)
        subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
        print("로그 정리 예약만 중지했습니다. 수집기와 보관본은 유지합니다.")
        return
    source = ROOT / "scripts/launchd" / f"{LABEL}.plist"
    config = plistlib.loads(source.read_bytes())
    expected = [str(ROOT / ".venv/bin/python"), "-m",
                "horse_racing.jobs.local_log_rotation", "--apply"]
    if (
        config.get("Label") != LABEL or config.get("WorkingDirectory") != str(ROOT)
        or config.get("ProgramArguments") != expected
        or config.get("StartCalendarInterval") != {"Hour": 3, "Minute": 0}
        or config.get("RunAtLoad") is not False
        or config.get("StandardOutPath") != "/dev/null"
        or config.get("StandardErrorPath") != "/dev/null"
    ):
        raise SystemExit("로그 정리 예약 설정이 검증된 범위와 다릅니다.")
    destination = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    if destination.is_symlink():
        raise SystemExit("예약 파일 심볼릭 링크를 덮어쓰지 않습니다.")
    if destination.exists() and plistlib.loads(destination.read_bytes()).get("Label") != LABEL:
        raise SystemExit("다른 LaunchAgent를 덮어쓰지 않습니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o600)
    subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
    subprocess.run(["launchctl", "enable", target], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(destination)], check=True)
    print("설치 완료: 매일 03:00(시스템 시간대 Asia/Seoul), 등록 즉시 실행하지 않음.")
    print("수집기 로그 6개만 gzip 보관·내용 비우기, 7일 초과 보관본만 삭제.")
    print("정리 결과: ~/Library/Logs/horse-racing/rotation-status.json")


if __name__ == "__main__":
    main()

"""Install/status/stop only the laptop race-day LaunchAgent. Never alters cloud schedules."""

import argparse
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.horse-racing.live-race-day"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "status", "stop"])
    args = parser.parse_args()
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{LABEL}"
    destination = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    if args.action == "status":
        raise SystemExit(subprocess.run(["launchctl", "print", target], check=False).returncode)
    if args.action == "stop":
        subprocess.run(["launchctl", "disable", target], check=True)
        subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
        print("예약 중지. plist는 보존되어 있습니다. 재등록 시 다시 실행됩니다.")
        raise SystemExit(0)
    source = TASK_ROOT / "scripts/launchd" / f"{LABEL}.plist"
    config = plistlib.loads(source.read_bytes())
    if config["Label"] != LABEL or Path(config["WorkingDirectory"]) != TASK_ROOT:
        raise SystemExit("프로젝트 경로와 LaunchAgent 설정이 다릅니다. 설치하지 않았습니다.")
    if destination.exists():
        existing = plistlib.loads(destination.read_bytes())
        if existing.get("Label") != LABEL:
            raise SystemExit("다른 예약 파일이 있어 덮어쓰지 않았습니다.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    log_dir = Path.home() / "Library/Logs/horse-racing"
    for key in ("StandardOutPath", "StandardErrorPath"):
        if Path(config[key]).parent != log_dir:
            raise SystemExit("자동 실행 로그는 Library/Logs/horse-racing 아래에 있어야 합니다.")
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    for key in ("StandardOutPath", "StandardErrorPath"):
        log_path = Path(config[key])
        log_path.touch(mode=0o600, exist_ok=True)
        os.chmod(log_path, 0o600)
    # The reviewed plist contains no keys, passwords, or webhook URL.
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o600)
    subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
    subprocess.run(["launchctl", "enable", target], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(destination)], check=True)
    print(f"설치 완료: {LABEL}, 120초 간격. 실제 실행/성공은 로그로 확인하세요.")
    print("노트북 로그인·인터넷·잠자기 해제 상태가 필요합니다.")
    print(f"자동 실행 로그: {log_dir}. 바탕화면 프로젝트 접근 권한은 별도로 필요합니다.")


if __name__ == "__main__":
    main()

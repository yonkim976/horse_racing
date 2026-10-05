"""Manage only the two project-local post-race LaunchAgents, never cloud jobs."""

import argparse
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ("com.horse-racing.closing-dividends", "com.horse-racing.post-race-repair")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "stop"))
    args = parser.parse_args()
    domain = f"gui/{os.getuid()}"
    for label in LABELS:
        target = f"{domain}/{label}"
        if args.action == "status":
            result = subprocess.run(
                ["launchctl", "print", target], capture_output=True, text=True, check=False
            )
            print(label, "registered" if result.returncode == 0 else "not_registered")
            for line in result.stdout.splitlines():
                if line.strip().startswith(
                    ("state =", "runs =", "last exit code =", "run interval =")
                ):
                    print(line.strip())
            continue
        if args.action == "stop":
            subprocess.run(["launchctl", "disable", target], check=True)
            subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
            print(label, "stopped; plist preserved")
            continue
        source = ROOT / "scripts/launchd" / f"{label}.plist"
        config = plistlib.loads(source.read_bytes())
        if config.get("Label") != label or Path(config["WorkingDirectory"]) != ROOT:
            raise SystemExit("LaunchAgent project/label mismatch")
        destination = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
        if destination.exists() and plistlib.loads(destination.read_bytes()).get("Label") != label:
            raise SystemExit("Refusing to overwrite an unrelated LaunchAgent")
        destination.parent.mkdir(parents=True, exist_ok=True)
        log_dir = Path.home() / "Library/Logs/horse-racing"
        for key in ("StandardOutPath", "StandardErrorPath"):
            if Path(config[key]).parent != log_dir:
                raise SystemExit("LaunchAgent logs must be in Library/Logs/horse-racing")
        log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        for key in ("StandardOutPath", "StandardErrorPath"):
            log_path = Path(config[key])
            log_path.touch(mode=0o600, exist_ok=True)
            os.chmod(log_path, 0o600)
        shutil.copyfile(source, destination)
        os.chmod(destination, 0o600)
        subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
        subprocess.run(["launchctl", "enable", target], check=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(destination)], check=True)
        print(label, "installed")
    if args.action == "install":
        print("배당: 경마 시간대 15분 간격 / 최근 7일 결과와 배당 보완: 매일 09:00, 20:30")
        print("Mac 로그인·인터넷·잠자기 해제 필요. 시스템 시간대 Asia/Seoul 기준.")
        print("자동 실행 로그: ~/Library/Logs/horse-racing.")
        print("바탕화면 프로젝트 접근 권한은 별도로 필요합니다.")


if __name__ == "__main__":
    main()

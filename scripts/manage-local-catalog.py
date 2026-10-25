"""Install/status/stop only the five local reference-data LaunchAgents."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from horse_racing.jobs.local_catalog import LABELS, MODES, SCHEDULES
from horse_racing.jobs.local_log_rotation import open_regular, secure_directory
from horse_racing.jobs.local_race_day import ROOT


def configuration(mode):
    logs = Path.home() / "Library/Logs/horse-racing"
    return {
        "Label": LABELS[mode],
        "ProgramArguments": [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "horse_racing.jobs.local_catalog",
            "--mode",
            mode,
            "--apply",
            "--scheduled",
        ],
        "WorkingDirectory": str(ROOT),
        "StartCalendarInterval": SCHEDULES[mode],
        "EnvironmentVariables": {
            "PATH": "/Users/kimyongjin/google-cloud-sdk/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
        },
        "StandardOutPath": str(logs / f"local-catalog-{mode}.log"),
        "StandardErrorPath": str(logs / f"local-catalog-{mode}.err.log"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "stop"))
    parser.add_argument("--mode", choices=MODES)
    args = parser.parse_args()
    domain = f"gui/{os.getuid()}"
    for mode in [args.mode] if args.mode else MODES:
        label = LABELS[mode]
        target = f"{domain}/{label}"
        if args.action == "status":
            result = subprocess.run(
                ["launchctl", "print", target], capture_output=True, text=True, check=False
            )
            print(label, "registered" if result.returncode == 0 else "not_registered")
            for line in result.stdout.splitlines():
                if line.strip().startswith(("state =", "runs =", "last exit code =")):
                    print(line.strip())
            continue
        if args.action == "stop":
            subprocess.run(["launchctl", "disable", target], check=True)
            subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
            print(label, "stopped; plist preserved")
            continue
        if datetime.now().astimezone().utcoffset() != timedelta(hours=9):
            raise SystemExit("Installation requires the Mac's KST calendar timezone")
        destination = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
        secure_directory(destination.parent)
        if destination.exists():
            with os.fdopen(open_regular(destination, os.O_RDONLY), "rb") as handle:
                previous = plistlib.load(handle)
            if previous.get("Label") != label or previous.get("WorkingDirectory") != str(ROOT):
                raise SystemExit("Refusing unrelated LaunchAgent overwrite")
        config = configuration(mode)
        logs = Path(config["StandardOutPath"]).parent
        secure_directory(logs)
        for key in ("StandardOutPath", "StandardErrorPath"):
            fd = open_regular(Path(config[key]), os.O_CREAT | os.O_APPEND | os.O_WRONLY)
            os.fchmod(fd, 0o600)
            os.close(fd)
        with os.fdopen(open_regular(destination, os.O_CREAT | os.O_WRONLY), "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.truncate(0)
            plistlib.dump(config, handle)
        subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
        subprocess.run(["launchctl", "enable", target], check=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(destination)], check=True)
        print(label, "installed", config["StartCalendarInterval"])
    if args.action == "install":
        print("KST 기준. Mac 로그인·잠자기 해제·인터넷·Desktop 접근 권한 필요.")


if __name__ == "__main__":
    main()

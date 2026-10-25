"""Install/status/stop only the local failed-job recovery LaunchAgent."""

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

from horse_racing.jobs.local_log_rotation import open_regular, secure_directory
from horse_racing.jobs.local_race_day import ROOT
from horse_racing.jobs.local_recovery import LABEL


def configuration():
    logs = Path.home() / "Library/Logs/horse-racing"
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "horse_racing.jobs.local_recovery",
            "--apply",
        ],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "StartInterval": 300,
        "EnvironmentVariables": {
            "PATH": "/Users/kimyongjin/google-cloud-sdk/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
        },
        "StandardOutPath": str(logs / "local-recovery.log"),
        "StandardErrorPath": str(logs / "local-recovery.err.log"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "stop"))
    action = parser.parse_args().action
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{LABEL}"
    if action == "status":
        result = subprocess.run(["launchctl", "print", target], capture_output=True, text=True)
        print(LABEL, "registered" if result.returncode == 0 else "not_registered")
        for line in result.stdout.splitlines():
            if line.strip().startswith(("state =", "runs =", "last exit code =", "run interval =")):
                print(line.strip())
        return
    if action == "stop":
        subprocess.run(["launchctl", "disable", target], check=True)
        subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
        print(LABEL, "stopped; plist preserved")
        return
    config = configuration()
    destination = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    secure_directory(destination.parent)
    if destination.exists():
        with os.fdopen(open_regular(destination, os.O_RDONLY), "rb") as handle:
            previous = plistlib.load(handle)
        if previous.get("Label") != LABEL or previous.get("WorkingDirectory") != str(ROOT):
            raise SystemExit("Refusing unrelated LaunchAgent overwrite")
    secure_directory(Path(config["StandardOutPath"]).parent)
    for field in ("StandardOutPath", "StandardErrorPath"):
        fd = open_regular(Path(config[field]), os.O_CREAT | os.O_APPEND | os.O_WRONLY)
        os.fchmod(fd, 0o600)
        os.close(fd)
    with os.fdopen(open_regular(destination, os.O_CREAT | os.O_WRONLY), "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.truncate(0)
        plistlib.dump(config, handle)
    subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
    subprocess.run(["launchctl", "enable", target], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(destination)], check=True)
    print(LABEL, "installed; 300-second checks; no healthy-job reruns")


if __name__ == "__main__":
    main()

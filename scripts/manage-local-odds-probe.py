"""Install a date-pinned, local-only API301 experiment; never modify other jobs."""

import argparse
import os
import plistlib
import subprocess
from datetime import date, datetime
from pathlib import Path

from horse_racing.jobs.local_log_rotation import open_regular, secure_directory
from horse_racing.jobs.local_odds_probe import KST, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "stop"))
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    label = f"com.horse-racing.odds-probe-{args.date:%Y%m%d}"
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"
    if args.action == "status":
        result = subprocess.run(
            ["launchctl", "print", target], capture_output=True, text=True, check=False
        )
        print(label, "registered" if result.returncode == 0 else "not_registered")
        for line in result.stdout.splitlines():
            if line.strip().startswith(("state =", "pid =", "runs =", "last exit code =")):
                print(line.strip())
        return
    if args.action == "stop":
        subprocess.run(["launchctl", "disable", target], check=True)
        subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
        print(label, "stopped; files preserved")
        return
    if args.date != datetime.now(KST).date():
        raise SystemExit("Only today's explicitly selected experiment can be installed")
    logs = Path.home() / "Library/Logs/horse-racing"
    destination = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    secure_directory(logs)
    secure_directory(destination.parent)
    config = {
        "Label": label,
        "ProgramArguments": [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "horse_racing.jobs.local_odds_probe",
            "--date",
            str(args.date),
            "--apply",
            "--watch",
        ],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 120,
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "StandardOutPath": str(logs / f"local-odds-probe-{args.date:%Y%m%d}.log"),
        "StandardErrorPath": str(logs / f"local-odds-probe-{args.date:%Y%m%d}.err.log"),
    }
    if destination.exists():
        with os.fdopen(open_regular(destination, os.O_RDONLY), "rb") as handle:
            previous = plistlib.load(handle)
        if previous.get("Label") != label or previous.get("WorkingDirectory") != str(ROOT):
            raise SystemExit("Refusing unrelated LaunchAgent overwrite")
    for name in ("StandardOutPath", "StandardErrorPath"):
        os.close(open_regular(Path(config[name]), os.O_CREAT | os.O_APPEND | os.O_WRONLY))
    with os.fdopen(open_regular(destination, os.O_CREAT | os.O_WRONLY), "wb") as handle:
        plistlib.dump(config, handle)
        handle.truncate()
    subprocess.run(["launchctl", "bootout", target], capture_output=True, check=False)
    subprocess.run(["launchctl", "enable", target], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(destination)], check=True)
    print(label, "installed; local-only, date-guarded, no Discord or production DB")


if __name__ == "__main__":
    main()

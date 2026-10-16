"""macOS login startup and private, read-only paper-test progress checks."""

import argparse
import json
import os
import plistlib
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from .alpaca import AlpacaPaper
from .automation import NEW_YORK


def private_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        os.chmod(temporary, 0o600)
        stream.write(content)
    os.replace(temporary, path)


def install_service(port=8000):
    if sys.platform != "darwin":
        raise ValueError("Login service installation requires macOS.")
    home = Path.home()
    logs = home / ".tradingagents/logs"
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    domain = f"gui/{os.getuid()}"
    installed = []
    for suffix, command, schedule in (
        ("dashboard", ["/usr/bin/caffeinate", "-s", sys.executable, "-m", "tradingagents.dashboard.server", "--port", str(port)], {"KeepAlive": True, "ThrottleInterval": 30}),
        ("progress", [sys.executable, "-m", "tradingagents.dashboard.operations", "check", "--port", str(port)], {"StartCalendarInterval": {"Hour": 14, "Minute": 15}}),
    ):
        label = f"dev.tradingagents.{suffix}"
        path = home / "Library/LaunchAgents" / f"{label}.plist"
        log = str(logs / f"{suffix}.console.log")
        private_write(path, plistlib.dumps({"Label": label, "ProgramArguments": command,
                      "WorkingDirectory": str(Path.cwd()), "RunAtLoad": True, "Umask": 0o077,
                      "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
                      "StandardOutPath": log, "StandardErrorPath": log, **schedule}))
        # bootout may report an unloaded job on the first installation.
        subprocess.run(["/bin/launchctl", "bootout", f"{domain}/{label}"], capture_output=True, check=False)
        # launchd can finish removing the previous job after bootout returns.
        for attempt in range(20):
            loaded = subprocess.run(["/bin/launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True, check=False)
            if loaded.returncode == 0:
                break
            if attempt == 19:
                raise RuntimeError(f"Could not start {label}: {loaded.stderr.strip()}")
            time.sleep(0.25)
        installed.append(str(path))
    return installed


def fetch(port, route):
    # Login jobs start concurrently; allow the HTTP server time to initialize.
    for attempt in range(10):
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/{route}", timeout=2 if route == "health" else 90) as response:
                return json.load(response)
        except OSError:
            if route != "health" or attempt == 9:
                raise
            time.sleep(1)


def check_progress(port=8000):
    now = datetime.now(UTC)
    today = now.astimezone(NEW_YORK).date().isoformat()
    folder = Path.home() / ".tradingagents/dashboard"
    destination = folder / "progress" / now.strftime("%Y-%m-%dT%H%M%S%fZ")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = {"checked_at": now.isoformat(), "issues": [], "backups": []}
    for route, key in (("health", "health"), ("state", "research"), ("paper/status", "paper")):
        try:
            data = fetch(port, route)
            if key == "research":
                data = {k: data.get(k) for k in ("provider", "quick_model", "deep_model", "active")}
                if data["active"]:
                    data["active"] = {k: data["active"].get(k) for k in ("ticker", "status", "completed", "stats", "error")}
            result[key] = data
        except Exception:
            result["issues"].append(f"Dashboard {key} unavailable; check the background service and its log.")
    health, paper = result.get("health", {}), result.get("paper", {})
    if health and not health.get("ok"):
        result["issues"].append("The research scheduler is unhealthy.")
    if paper:
        if not paper.get("connected"):
            result["issues"].append("Paper account data unavailable.")
        if not paper.get("enabled"):
            result["issues"].append("Daily automation is paused.")
        latest = {}
        for run in sorted(paper.get("runs", []), key=lambda r: (r["day"], r["updated"]), reverse=True):
            latest.setdefault(run["ticker"], run)
        for ticker in paper.get("symbols", []):
            run = latest.get(ticker, {})
            if run.get("status") == "error":
                result["issues"].append(f"Latest {ticker} attempt failed; inspect the saved journal.")
        if any(o.get("status") in ("rejected", "suspended") and str(o.get("submitted_at", "")).startswith(today) for o in paper.get("orders", [])):
            result["issues"].append("A paper order was rejected or suspended today.")
        if paper.get("mode") == "alpaca" and paper.get("connected"):
            try:
                broker = AlpacaPaper.load(folder / "alpaca-paper.json")
                calendar = broker.request("GET", "/v2/calendar", params={"start": today, "end": today})
                if calendar and paper.get("enabled"):
                    close = datetime.fromisoformat(today + "T" + calendar[0]["close"]).replace(tzinfo=NEW_YORK)
                    if now >= close:
                        missing = [s for s in paper["symbols"] if latest.get(s, {}).get("day") != today]
                        if missing:
                            result["issues"].append("Missing today's research: " + ", ".join(missing))
            except Exception:
                result["issues"].append("Exchange calendar unavailable; cannot verify today's research coverage.")
    for name in ("paper.sqlite3", "forward.sqlite3"):
        source = folder / name
        if not source.exists():
            result["issues"].append(f"Missing {name}; no backup was created.")
            continue
        target = destination / name
        temporary = target.with_suffix(".tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.close(fd)
            os.chmod(temporary, 0o600)
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src, closing(sqlite3.connect(temporary)) as dst:
                if src.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("Database integrity check failed")
                if name == "paper.sqlite3":
                    settings = src.execute("SELECT account FROM automation WHERE id=1").fetchone()
                    if settings and src.execute("SELECT 1 FROM paper_runs WHERE account=? AND status IN ('unknown','submitting') LIMIT 1", settings).fetchone():
                        result["issues"].append("An uncertain broker submission requires reconciliation; do not resubmit it.")
                src.backup(dst)
            os.replace(temporary, target)
            result["backups"].append(str(target))
        except Exception:
            result["issues"].append(f"Could not verify and back up {name}; investigate the local database.")
    result["ok"] = not result["issues"]
    private_write(destination / "summary.json", json.dumps(result, indent=2).encode())
    return result, destination / "summary.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "check"))
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Choose a port between 1 and 65535.")
    if args.action == "install":
        print(json.dumps({"installed": install_service(args.port)}))
    else:
        result, path = check_progress(args.port)
        paper = result.get("paper", {})
        print(json.dumps({"ok": result["ok"], "checked_at": result["checked_at"], "issues": result["issues"],
                          "mode": paper.get("mode"), "enabled": paper.get("enabled"),
                          "symbols": paper.get("symbols"), "account": paper.get("account"), "snapshot": str(path)}))
        sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()

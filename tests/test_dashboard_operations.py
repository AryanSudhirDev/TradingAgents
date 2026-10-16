"""Login recovery, scheduler liveness, and read-only progress snapshots."""

import json
import plistlib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tradingagents.dashboard import operations
from tradingagents.dashboard.server import Desk
from tradingagents.default_config import DEFAULT_CONFIG


def test_login_jobs_use_current_environment_and_ac_only_sleep_prevention(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(operations.sys, "platform", "darwin")
    calls = []
    monkeypatch.setattr(operations.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0))
    paths = operations.install_service(8123)
    dashboard, progress, shadow = [plistlib.loads(Path(path).read_bytes()) for path in paths]
    assert dashboard["ProgramArguments"] == ["/usr/bin/caffeinate", "-s", operations.sys.executable,
                                              "-m", "tradingagents.dashboard.server", "--port", "8123"]
    assert dashboard["KeepAlive"] and dashboard["RunAtLoad"]
    assert dashboard["WorkingDirectory"] == str(Path.cwd())
    assert dashboard["Umask"] == 0o077
    assert progress["StartCalendarInterval"] == {"Hour": 14, "Minute": 15}
    assert progress["RunAtLoad"] and "KeepAlive" not in progress
    assert shadow["StartCalendarInterval"] == {"Hour": 14, "Minute": 45}
    assert shadow["ProgramArguments"][-3:] == ["-m", "tradingagents.strategy_shadow", "run"]
    assert shadow["RunAtLoad"] and "KeepAlive" not in shadow
    assert len(calls) == 6 and all(call[0][0] == "/bin/launchctl" for call in calls)
    assert all(Path(path).stat().st_mode & 0o777 == 0o600 for path in paths)


def test_install_waits_for_launchd_to_finish_unloading_the_previous_job(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(operations.sys, "platform", "darwin")
    failures, sleeps = [], []

    def launch(args, **kwargs):
        if args[1] == "bootstrap" and not failures:
            failures.append(True)
            return SimpleNamespace(returncode=5, stderr="Previous job is still unloading")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(operations.subprocess, "run", launch)
    monkeypatch.setattr(operations.time, "sleep", sleeps.append)
    assert len(operations.install_service()) == 3
    assert failures and sleeps == [0.25]


def test_service_install_rejects_other_platforms(monkeypatch):
    monkeypatch.setattr(operations.sys, "platform", "linux")
    with pytest.raises(ValueError, match="macOS"):
        operations.install_service()


def test_progress_waits_for_the_server_during_login_startup(monkeypatch):
    from io import StringIO

    calls, sleeps = [], []

    def opening(url, **kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise ConnectionRefusedError
        return StringIO('{"ok": true}')

    monkeypatch.setattr(operations, "urlopen", opening)
    monkeypatch.setattr(operations.time, "sleep", sleeps.append)
    assert operations.fetch(8000, "health") == {"ok": True}
    assert len(calls) == 3 and sleeps == [1, 1]


def test_worker_recovers_after_a_database_poll_error(tmp_path, monkeypatch):
    auto = Desk(DEFAULT_CONFIG, tmp_path / "paper.sqlite3").automation
    recovered = threading.Event()
    attempts = []

    def settings():
        attempts.append(True)
        if len(attempts) == 1:
            raise sqlite3.OperationalError("temporarily locked")
        recovered.set()
        return {"enabled": False}

    monkeypatch.setattr(auto, "settings", settings)
    monkeypatch.setattr(auto.shutdown, "wait", lambda timeout: len(attempts) >= 2)
    auto.start()
    auto.worker.join(timeout=2)
    assert recovered.is_set() and len(attempts) == 2
    assert auto.scheduler_error is None and auto.last_poll
    assert not auto.health()["ok"]  # The test worker has finished.


def test_health_endpoint_reports_a_dead_or_stale_worker(tmp_path):
    from fastapi.testclient import TestClient

    from tradingagents.dashboard.server import create_app

    app = create_app(db_path=tmp_path / "paper.sqlite3")
    auto = app.state.desk.automation
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").json()["worker_alive"]
        auto.last_poll = (datetime.now(UTC) - timedelta(minutes=3)).isoformat()
        assert client.get("/api/health").status_code == 503
        auto.stop()
        auto.worker.join(timeout=2)
        assert client.get("/api/health").status_code == 503


@pytest.fixture
def progress(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 16, 22, tzinfo=UTC)

    monkeypatch.setattr(operations, "datetime", Clock)
    desk = Desk(DEFAULT_CONFIG, tmp_path / ".tradingagents/dashboard/paper.sqlite3")
    paper = {"connected": True, "enabled": True, "mode": "alpaca", "symbols": ["NVDA"],
             "account": {"cash": "100000", "equity": "100000"}, "orders": [],
             "runs": [{"ticker": "NVDA", "day": "2026-10-16", "status": "skipped", "updated": "2026-10-16"}]}
    state = {"provider": "chatgpt", "quick_model": "quick", "deep_model": "deep",
             "active": {"ticker": "NVDA", "status": "done", "reports": {"Market": "large report"}}}
    payloads = {"health": {"ok": True}, "state": state, "paper/status": paper}
    monkeypatch.setattr(operations, "fetch", lambda port, route: payloads[route])

    def request(method, path, **kwargs):
        assert method == "GET" and path == "/v2/calendar"
        return [{"date": "2026-10-16", "close": "16:00"}]

    monkeypatch.setattr(operations.AlpacaPaper, "load", lambda path: SimpleNamespace(request=request))
    return desk, payloads


def test_progress_snapshots_and_consistent_backups_do_not_change_the_ledger(progress):
    desk, _ = progress
    before = desk.store.snapshot()
    result, path = operations.check_progress()
    assert result["ok"] and len(result["backups"]) == 2
    assert json.loads(path.read_text())["paper"]["symbols"] == ["NVDA"]
    assert "reports" not in result["research"]["active"]
    assert desk.store.snapshot() == before
    for name in result["backups"]:
        with sqlite3.connect(name) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute("SELECT cash FROM account").fetchone()[0] == 10_000_000
        assert Path(name).stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.glob("*alpaca*"))


def test_progress_flags_missing_research_after_close_and_uncertain_submissions(progress):
    desk, payloads = progress
    payloads["paper/status"]["runs"] = []
    with desk.store.connect() as db:
        db.execute("UPDATE automation SET account='paper-account' WHERE id=1")
        db.execute("INSERT INTO paper_runs (account,day,ticker,client_id,status,note,updated) VALUES ('paper-account','2026-10-15','NVDA','uncertain','unknown','timeout','2026-10-15')")
    result, _ = operations.check_progress()
    assert not result["ok"]
    assert any("Missing today's research: NVDA" in issue for issue in result["issues"])
    assert any("uncertain" in issue for issue in result["issues"])


def test_progress_does_not_expect_research_on_a_market_holiday(progress, monkeypatch):
    _, payloads = progress
    payloads["paper/status"]["runs"] = []
    monkeypatch.setattr(operations.AlpacaPaper, "load", lambda path: SimpleNamespace(request=lambda *a, **k: []))
    assert operations.check_progress()[0]["ok"]


def test_outage_is_recorded_and_databases_are_still_backed_up(progress, monkeypatch):
    def offline(*args):
        raise TimeoutError("private diagnostic must not be published")

    monkeypatch.setattr(operations, "fetch", offline)
    result, path = operations.check_progress()
    assert not result["ok"] and len(result["backups"]) == 2
    assert "private diagnostic" not in path.read_text()

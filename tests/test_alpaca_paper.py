"""Paper endpoint isolation, deterministic sizing and durable submission boundaries."""

import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import requests

from tradingagents.dashboard import alpaca, automation
from tradingagents.dashboard.alpaca import AlpacaPaper, BrokerError, order_intent
from tradingagents.dashboard.server import Desk
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.fixture
def account():
    return {"id": "paper-account", "status": "ACTIVE", "currency": "USD", "cash": "100000", "equity": "100000", "last_equity": "100000"}


@pytest.fixture
def quote():
    return {"bp": 99.99, "ap": 100, "t": datetime.now(UTC).isoformat()}


def test_requests_are_pinned_to_paper_and_never_follow_redirects(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "request", lambda *a, **k: calls.append((a, k)) or SimpleNamespace(status_code=200, json=lambda: {}))
    client = AlpacaPaper("P" * 20, "s" * 40)
    client.submit({"symbol": "NVDA", "qty": "1", "side": "buy", "limit_price": "100"}, "unique")
    args, kwargs = calls[0]
    assert args == ("POST", "https://paper-api.alpaca.markets/v2/orders")
    assert kwargs["allow_redirects"] is False
    assert kwargs["json"]["extended_hours"] is False
    assert kwargs["json"]["type"] == "limit" and kwargs["json"]["time_in_force"] == "day"
    monkeypatch.setattr(requests, "request", lambda *a, **k: SimpleNamespace(status_code=401, text="secret-should-not-be-exposed"))
    with pytest.raises(BrokerError, match="HTTP 401") as error:
        client.account()
    assert "secret-should-not-be-exposed" not in str(error.value)


def test_credentials_are_private_and_do_not_expose_values(tmp_path):
    path = tmp_path / "alpaca-paper.json"
    client = AlpacaPaper("P" * 20, "s" * 40)
    client.save(path)
    assert AlpacaPaper.load(path).headers == client.headers
    if __import__("os").name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(BrokerError) as error:
        AlpacaPaper("bad\nkey", "sensitive")
    assert "sensitive" not in str(error.value)


def test_rating_sizing_never_uses_llm_quantities(account, quote):
    assert order_intent("NVDA", "Buy", account, [], quote)["qty"] == "99"
    assert order_intent("NVDA", "Overweight", account, [], quote)["qty"] == "49"
    assert order_intent("NVDA", "Hold", account, [], None) is None
    assert order_intent("NVDA", "REVIEW", account, [], None) is None
    position = {"symbol": "NVDA", "qty": "9", "market_value": "900"}
    assert order_intent("NVDA", "Underweight", account, [position], quote)["qty"] == "5"
    assert order_intent("NVDA", "Sell", account, [position], quote)["qty"] == "9"
    assert order_intent("NVDA", "Sell", account, [], quote) is None
    position["qty"] = "120"
    assert order_intent("NVDA", "Buy", account, [position], quote) is None


def test_total_exposure_and_cash_reserve_limit_buys(account, quote):
    positions = [{"symbol": "MSFT", "qty": "100", "market_value": "39900"}]
    assert order_intent("NVDA", "Buy", account, positions, quote) is None
    positions[0]["market_value"] = "35000"
    assert order_intent("NVDA", "Buy", account, positions, quote)["qty"] == "49"
    account["cash"] = "10050"
    assert order_intent("NVDA", "Buy", account, [], quote) is None


@pytest.mark.parametrize("changes", [
    {"bp": 0}, {"ap": "NaN"}, {"bp": 101}, {"bp": 90},
    {"t": (datetime.now(UTC)-timedelta(minutes=6)).isoformat()},
    {"t": (datetime.now(UTC)+timedelta(minutes=6)).isoformat()},
])
def test_bad_or_stale_quotes_fail_closed(account, quote, changes):
    with pytest.raises(BrokerError):
        order_intent("NVDA", "Buy", account, [], {**quote, **changes})


def test_fractional_managed_positions_cannot_be_rounded_into_orders(account, quote):
    with pytest.raises(BrokerError, match="whole"):
        order_intent("NVDA", "Sell", account, [{"symbol": "NVDA", "qty": "1.5"}], quote)


def test_exchange_clock_holidays_early_closes_and_schedule():
    clock = {"timestamp": "2026-11-27T09:45:00-05:00", "next_close": "2026-11-27T13:00:00-05:00", "is_open": True}
    assert automation.trading_window(clock)[1]
    assert not automation.trading_window(clock, scheduled=True)[1]
    assert not automation.trading_window({**clock, "timestamp": "2026-11-27T12:30:00-05:00"})[1]
    assert not automation.trading_window({**clock, "is_open": False})[1]


@pytest.fixture
def auto(tmp_path, account, quote, monkeypatch):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["results_dir"] = str(tmp_path / "reports")
    desk = Desk(config, tmp_path / "paper.sqlite3")
    monkeypatch.setattr(desk, "market", lambda ticker: {"price": 100, "as_of": "2026-10-16"})
    controller = desk.automation

    class Broker:
        sent = []
        open_orders = []

        def account(self):
            return account.copy()

        def positions(self):
            return []

        def orders(self, status="all"):
            return self.open_orders if status == "open" else self.sent

        def clock(self):
            return {"timestamp": "2026-10-16T12:00:00-04:00", "next_close": "2026-10-16T16:00:00-04:00", "is_open": True}

        def quote(self, ticker):
            return quote.copy()

        def order(self, client_id):
            return next((o for o in self.sent if o["client_order_id"] == client_id), None)

        def submit(self, intent, client_id):
            order = {**intent, "client_order_id": client_id, "status": "filled", "filled_qty": intent["qty"]}
            self.sent.append(order)
            return order

    controller.broker = Broker()
    with controller.store.connect() as db:
        db.execute("UPDATE automation SET account=?, symbols='[\"NVDA\"]' WHERE id=1", (account["id"],))

    def research(ticker, **kwargs):
        assert kwargs["portfolio"].cash == 100000 and kwargs["day"] == "2026-10-16"
        desk.active["status"] = "done"
        return {"final_trade_decision": "Rating: Buy", "final_rating": "Buy"}

    monkeypatch.setattr(desk, "analyze", research)
    return controller


def cycle(auto):
    assert auto.run_lock.acquire(blocking=False)
    auto.cycle(scheduled=False)


def test_cycle_researches_with_broker_book_and_submits_once_across_restart(auto):
    cycle(auto)
    assert len(auto.broker.sent) == 1 and auto.broker.sent[0]["qty"] == "99"
    assert auto.status()["runs"][0]["status"] == "submitted"
    restarted = automation.PaperAutomation(auto.desk)
    restarted.broker = auto.broker
    cycle(restarted)
    assert len(auto.broker.sent) == 1


def test_uncertain_submission_is_not_retried_even_if_lookup_returns_nothing(auto, monkeypatch):
    attempts = []

    def disconnect(*args):
        attempts.append(args)
        raise requests.Timeout("sensitive transport detail")

    monkeypatch.setattr(auto.broker, "submit", disconnect)
    cycle(auto)
    assert auto.status()["runs"][0]["status"] == "unknown"
    cycle(auto)
    assert len(attempts) == 1
    assert "sensitive" not in auto.status()["message"]


def test_unresolved_order_from_yesterday_blocks_new_symbols_today(auto):
    with auto.store.connect() as db:
        db.execute("INSERT INTO paper_runs (account,day,ticker,client_id,status,note,updated) VALUES ('paper-account','2026-10-15','MSFT','old-uncertain','unknown','network interruption','2026-10-15')")
    cycle(auto)
    assert not auto.broker.sent
    assert "uncertain" in auto.message


def test_scheduler_waits_for_manual_analysis(auto):
    auto.desk.active = {"ticker": "MSFT", "status": "running"}
    auto.kick()
    assert not auto.run_lock.locked() and not auto.broker.sent
    assert auto.desk.active["status"] == "running"


def test_two_workers_cannot_run_against_the_same_database(auto):
    import fcntl

    with auto.store.path.with_suffix(".worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        cycle(auto)
        assert not auto.broker.sent
        assert "Another paper worker" in auto.message


def test_timeout_after_broker_acceptance_recovers_without_second_order(auto, monkeypatch):
    original = auto.broker.submit

    def accepted_then_timeout(intent, client_id):
        original(intent, client_id)
        raise requests.Timeout()

    monkeypatch.setattr(auto.broker, "submit", accepted_then_timeout)
    cycle(auto)
    assert auto.status()["runs"][0]["status"] == "unknown"
    cycle(auto)
    assert len(auto.broker.sent) == 1
    assert auto.status()["runs"][0]["status"] == "submitted"


def test_pause_during_research_prevents_submission(auto, monkeypatch):
    def research(*a, **k):
        auto.control("pause")
        auto.desk.active["status"] = "done"
        return {"final_trade_decision": "Rating: Buy", "final_rating": "Buy"}

    monkeypatch.setattr(auto.desk, "analyze", research)
    cycle(auto)
    assert not auto.broker.sent
    assert auto.status()["runs"][0]["status"] == "skipped"


def test_open_orders_block_new_research_and_orders(auto):
    auto.broker.open_orders = [{"status": "new"}]
    cycle(auto)
    assert not auto.broker.sent and not auto.status()["runs"]


def test_failed_research_cannot_submit_and_is_visible_in_journal(auto, monkeypatch):
    monkeypatch.setattr(auto.desk, "analyze", lambda *a, **k: None)
    cycle(auto)
    assert not auto.broker.sent
    assert auto.status()["runs"][0]["status"] == "error"


def test_paper_credentials_and_controls_require_local_origin(tmp_path, monkeypatch, account):
    from fastapi.testclient import TestClient

    from tradingagents.dashboard.server import create_app

    app = create_app(db_path=tmp_path / "paper.sqlite3")
    monkeypatch.setattr(alpaca.AlpacaPaper, "account", lambda self: account.copy())
    monkeypatch.setattr(alpaca.AlpacaPaper, "positions", lambda self: [])
    monkeypatch.setattr(alpaca.AlpacaPaper, "orders", lambda self: [])
    monkeypatch.setattr(alpaca.AlpacaPaper, "clock", lambda self: {"is_open": True})
    with TestClient(app, base_url="http://127.0.0.1") as client:
        body = {"key": "P" * 20, "secret": "s" * 40}
        assert client.post("/api/paper/connect", json=body).status_code == 403
        response = client.post("/api/paper/connect", json=body, headers={"origin": "http://127.0.0.1"})
        assert response.status_code == 200 and body["secret"] not in response.text
        status = client.get("/api/paper/status")
        assert body["secret"] not in status.text
        assert client.post("/api/paper/control", json={"action": "run", "symbols": ["INVALID"]}, headers={"origin": "http://127.0.0.1"}).status_code == 400


def test_run_once_preserves_daily_schedule_and_switching_modes_pauses(auto, monkeypatch):
    monkeypatch.setattr(auto, "kick", lambda **kwargs: None)
    auto.control("enable", ["NVDA"])
    auto.control("run", ["NVDA"])
    assert auto.settings()["enabled"]
    auto.control("select", mode="local")
    settings = auto.settings()
    assert settings["mode"] == "local" and not settings["enabled"]


def test_keyless_cycle_accounts_for_slippage_and_isolates_books(auto, monkeypatch):
    auto.broker = None
    auto.control("select", mode="local")
    auto.cancel.clear()
    day = ["2026-10-16"]
    monkeypatch.setattr(auto.desk, "market", lambda ticker: {"price": 100, "as_of": day[0]})
    monkeypatch.setattr(auto, "window", lambda *a, **k: (datetime.fromisoformat(day[0]+"T12:00:00-04:00"), True))
    cycle(auto)
    book = auto.simulator.store.snapshot()
    assert book["positions"][0]["quantity"] == 99
    assert book["trades"][0]["price"] == 10005
    assert book["total_value"] == 10_000_000 - 495
    assert auto.desk.store.snapshot()["cash"] == 10_000_000
    assert not auto.desk.store.snapshot()["positions"]
    performance = auto.status()["performance"]
    assert performance["pnl"] == -495 and performance["spy_return_pct"] == 0
    assert performance["count"] == 2
    cycle(auto)
    assert len(auto.simulator.store.snapshot()["trades"]) == 1

    day[0] = "2026-10-19"

    def exit_position(ticker, **kwargs):
        assert kwargs["portfolio"].positions[0].quantity == 99
        auto.desk.active["status"] = "done"
        return {"final_trade_decision": "Rating: Sell", "final_rating": "Sell"}

    monkeypatch.setattr(auto.desk, "analyze", exit_position)
    cycle(auto)
    flat = auto.simulator.store.snapshot()
    assert flat["cash"] == 9_999_010 and flat["realized"] == -990
    assert not flat["positions"] and len(flat["trades"]) == 2
    assert auto.status()["performance"]["pnl"] == -990


def test_keyless_cycle_waits_when_there_is_no_bar_for_that_day(auto, monkeypatch):
    auto.control("select", mode="local")
    auto.cancel.clear()
    monkeypatch.setattr(auto, "window", lambda *a, **k: (datetime.fromisoformat("2026-10-19T16:30:00-04:00"), True))
    cycle(auto)
    assert not auto.status()["runs"] and not auto.simulator.store.snapshot()["trades"]
    assert "No Yahoo daily bar" in auto.message


def test_performance_tracks_full_history_drawdown_and_missing_benchmark(auto):
    with auto.store.connect() as db:
        db.executemany("INSERT INTO paper_equity VALUES (?,?,?,?)", [
            ("paper-account", "2026-10-14", 10000000, 10000),
            ("paper-account", "2026-10-15", 11000000, None),
            ("paper-account", "2026-10-16", 9900000, 10500),
        ])
    p = auto.performance("paper-account")
    assert p["pnl"] == -100000
    assert p["return_pct"] == pytest.approx(-1)
    assert p["drawdown_pct"] == pytest.approx(-10)
    assert p["spy_return_pct"] == pytest.approx(5)


def test_order_report_is_immutable_and_survives_restart(auto):
    from fastapi.testclient import TestClient

    from tradingagents.dashboard.server import create_app

    cycle(auto)
    run = auto.status()["runs"][0]
    assert run["has_report"]
    app = create_app(auto.desk.config, auto.store.path)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/paper/report/" + run["client_id"])
        assert response.status_code == 200 and "Rating: Buy" in response.text
        assert client.get("/api/paper/report/does-not-exist").status_code == 404


def test_stale_scheduler_trigger_cannot_run_after_mode_switch(auto):
    auto.control("select", mode="local")
    auto.kick(scheduled=True)
    assert auto.cancel.is_set() and not auto.run_lock.locked()

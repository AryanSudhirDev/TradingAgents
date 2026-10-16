"""Paper money, local HTTP boundaries, and the current graph's dashboard lifecycle."""

import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from tradingagents.dashboard import server
from tradingagents.dashboard.store import INITIAL_CASH, PaperStore, price_cents, stock_symbol
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.fixture
def store(tmp_path):
    return PaperStore(tmp_path / "desk" / "paper.sqlite3")


def fill(store, side="BUY", quantity=10, price="100.01", **kwargs):
    return store.trade("NVDA", side, quantity, price, "2026-10-16", kwargs.pop("request_id", str(uuid4())), **kwargs)


def test_cash_basis_and_realized_profit_survive_a_restart(store):
    fill(store)
    fill(store, price="110.01")
    fill(store, "SELL", 5, "120.01")
    book = PaperStore(store.path).snapshot()
    assert book["cash"] == INITIAL_CASH - 210020 + 60005
    assert book["positions"][0]["quantity"] == 15
    assert book["positions"][0]["basis"] == 157515
    assert book["realized"] == 7500
    assert book["total_value"] == book["cash"] + 15 * 12001
    fill(store, "SELL", 15, "90.01")
    flat = store.snapshot()
    assert not flat["positions"]
    assert flat["cash"] == INITIAL_CASH + flat["realized"]
    if os.name != "nt":
        assert store.path.stat().st_mode & 0o777 == 0o600


def test_duplicate_submission_is_idempotent_and_cannot_change_intent(store):
    request = str(uuid4())
    original = fill(store, request_id=request)
    assert fill(store, price="200.00", request_id=request) == original
    assert len(store.snapshot()["trades"]) == 1
    with pytest.raises(ValueError, match="different trade"):
        fill(store, quantity=11, request_id=request)


@pytest.mark.parametrize("side,quantity,price", [
    ("BUY", 1001, 100), ("SELL", 1, 100), ("BUY", 0, 100),
    ("BUY", -1, 100), ("BUY", 1.5, 100), ("BUY", True, 100),
    ("BUY", 1, "nan"), ("BUY", 1, "inf"), ("BUY", 1, 0),
    ("BUY", 1, -100), ("SHORT", 1, 100),
])
def test_rejected_trade_does_not_change_cash_or_positions(store, side, quantity, price):
    before = store.snapshot()
    with pytest.raises(ValueError):
        fill(store, side, quantity, price)
    assert store.snapshot() == before


def test_concurrent_buys_cannot_overspend(store):
    def buy(_):
        try:
            fill(store, quantity=700, price=100)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(buy, range(4))) == 1
    assert store.snapshot()["cash"] == 3_000_000


def test_concurrent_first_start_initializes_one_account(tmp_path):
    path = tmp_path / "paper.sqlite3"
    with ThreadPoolExecutor(max_workers=4) as pool:
        books = list(pool.map(lambda _: PaperStore(path).snapshot(), range(4)))
    assert all(book["cash"] == INITIAL_CASH and len(book["watchlist"]) == 4 for book in books)


def test_watchlist_persists_and_removing_a_symbol_keeps_its_position(store):
    fill(store)
    for symbol in store.snapshot()["watchlist"]:
        store.watch(symbol, remove=True)
    reopened = PaperStore(store.path)
    assert reopened.snapshot()["watchlist"] == []
    assert reopened.snapshot()["positions"][0]["ticker"] == "NVDA"
    reopened.watch("brk-b")
    assert reopened.snapshot()["watchlist"] == ["BRK-B"]


@pytest.mark.parametrize("symbol", ["../NVDA", "BTC-USD", "0700.HK", "NVDA'", "<script>", None])
def test_symbol_boundary_is_us_stocks_and_etfs(symbol):
    with pytest.raises(ValueError):
        stock_symbol(symbol)


def test_prices_are_rounded_once_to_cents():
    assert price_cents("100.005") == 10001
    with pytest.raises(ValueError):
        price_cents("0.001")


@pytest.fixture
def app(tmp_path):
    pytest.importorskip("fastapi")
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["results_dir"] = str(tmp_path / "reports")
    return server.create_app(config, tmp_path / "desk.sqlite3")


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def test_browser_boundaries_reject_foreign_origins_and_hosts(client):
    assert client.get("/api/state", headers={"host": "attacker.example"}).status_code == 400
    assert client.post("/api/watch", json={"ticker": "AMD"}, headers={"origin": "https://attacker.example"}).status_code == 403
    assert client.post("/api/watch", json={"ticker": "AMD"}).status_code == 403
    assert client.post("/api/watch", content="ticker=AMD", headers={"origin": "http://127.0.0.1", "content-type": "text/plain"}).status_code == 415
    response = client.post("/api/watch", json={"ticker": "AMD"}, headers={"origin": "http://127.0.0.1"})
    assert response.status_code == 200
    assert "AMD" in client.get("/api/state").json()["portfolio"]["watchlist"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.post("/api/watch", content="x" * 8193, headers={"origin": "http://127.0.0.1", "content-type": "application/json"}).status_code == 413


def test_paper_fill_uses_the_server_quote_and_no_client_price(client, app, monkeypatch):
    monkeypatch.setattr(app.state.desk, "market", lambda t: {"price": 123.45, "as_of": "2026-10-16"})
    body = {"ticker": "NVDA", "side": "BUY", "quantity": 2, "price": 1, "request_id": str(uuid4())}
    response = client.post("/api/trade", json=body, headers={"origin": "http://127.0.0.1"})
    assert response.status_code == 200
    assert response.json()["trade"]["price"] == 12345
    assert app.state.desk.store.snapshot()["cash"] == INITIAL_CASH - 24690
    assert client.post("/api/trade", json=body, headers={"origin": "http://127.0.0.1"}).status_code == 200
    assert len(app.state.desk.store.snapshot()["trades"]) == 1


def test_unavailable_quotes_do_not_create_a_trade(client, app, monkeypatch):
    def fail(_):
        raise OSError("offline")

    monkeypatch.setattr(app.state.desk, "market", fail)
    before = app.state.desk.store.snapshot()
    response = client.post("/api/trade", json={"ticker": "NVDA", "side": "BUY", "quantity": 1, "request_id": str(uuid4())}, headers={"origin": "http://127.0.0.1"})
    assert response.status_code == 503
    assert app.state.desk.store.snapshot() == before


def test_latest_report_loads_and_unsafe_markdown_is_escaped(client, app):
    folder = server.Path(app.state.desk.config["results_dir"]) / "NVDA/TradingAgentsStrategy_logs"
    folder.mkdir(parents=True)
    data = {"company_of_interest": "NVDA", "trade_date": "2026-10-15", "final_rating": "Overweight", "final_trade_decision": "<script>alert('bad')</script>", "trader_investment_plan": "A small starter."}
    (folder / "full_states_log_2026-10-15.json").write_text(json.dumps(data))
    (folder / "full_states_log_2026-10-14.json").write_text("[]")
    (folder / "full_states_log_2026-10-13.json").write_text(json.dumps({"company_of_interest": "NVDA", "final_trade_decision": "Incomplete."}))
    state = client.get("/api/state").json()
    assert state["latest"]["NVDA"]["rating"] == "Overweight"
    page = client.get("/api/report/NVDA/2026-10-15")
    assert page.status_code == 200 and "<script>alert" not in page.text
    assert client.get("/api/report/NVDA/2026-10-14").status_code == 404
    assert client.get("/").status_code == client.get("/app.js").status_code == 200


def test_market_reads_as_of_rows_and_keeps_last_quote_date(app, monkeypatch):
    calls = []
    frame = pd.DataFrame({"Date": pd.to_datetime(["2026-10-14", "2026-10-15"]), "Close": [100, 102.25]})
    monkeypatch.setattr(server, "load_ohlcv", lambda *a, **k: calls.append(a) or frame)
    result = app.state.desk.market("NVDA")
    assert result["as_of"] == "2026-10-15" and result["price"] == 102.25
    assert app.state.desk.market("NVDA") == result and len(calls) == 1


def test_analysis_uses_current_stream_lifecycle_and_paper_holdings(app, monkeypatch):
    desk = app.state.desk
    fill(desk.store)
    seen = {}

    class Graph:
        def __init__(self, **kwargs):
            self.propagator = SimpleNamespace(get_graph_args=lambda **k: {"config": {}})

        def create_run_state(self, ticker, day, portfolio):
            seen["portfolio"] = portfolio
            return {"company_of_interest": ticker, "trade_date": day}

        def begin_checkpoint(self, *a, **k):
            return "thread"

        def checkpoint_input(self, state):
            return state

        def stream_run(self, state, **kwargs):
            assert kwargs["config"]["configurable"]["thread_id"] == "thread"
            yield [], {**state, "market_report": "Verified prices.", "investment_debate_state": {"bull_history": "Bull argument."}}
            yield [], {"final_trade_decision": "**Rating**: Overweight", "final_rating": "Overweight"}

        def record_decision(self, ticker, day, state):
            seen["state"] = state

        def save_reports(self, *a):
            seen["saved"] = True

        def clear_checkpoint_on_success(self, *a, **k):
            seen["cleared"] = True

        def end_checkpoint(self):
            seen["closed"] = True

    monkeypatch.setattr(server, "TradingAgentsGraph", Graph)
    desk.active = {"ticker": "NVDA", "status": "running"}
    desk.analyze("NVDA")
    assert desk.active["status"] == "done" and "Bull" in desk.active["completed"]
    assert seen["portfolio"].positions[0].quantity == 10
    assert seen["portfolio"].cash == (INITIAL_CASH - 100010) / 100
    assert seen["state"]["market_report"] == "Verified prices."
    assert seen["saved"] and seen["cleared"] and seen["closed"]


def test_an_active_analysis_blocks_a_second_request(app):
    app.state.desk.active = {"status": "running"}
    with pytest.raises(ValueError, match="already running"):
        app.state.desk.start("NVDA")


def test_live_stats_are_visible_before_the_first_analyst_finishes(app):
    desk = app.state.desk
    desk.claim("NVDA")
    desk.stats = server.StatsCallbackHandler()
    desk.stats.on_chat_model_start({}, [])
    assert desk.state()["active"]["stats"]["llm_calls"] == 1
    assert desk.state()["active"]["completed"] == []


def test_failed_analysis_preserves_checkpoint_and_closes_it(app, monkeypatch):
    closed = []

    class BrokenGraph:
        def __init__(self, **kwargs):
            pass

        def create_run_state(self, *a, **k):
            raise RuntimeError("provider-sensitive-detail")

        def end_checkpoint(self):
            closed.append(True)

    monkeypatch.setattr(server, "TradingAgentsGraph", BrokenGraph)
    app.state.desk.active = {"ticker": "NVDA", "status": "running"}
    app.state.desk.analyze("NVDA")
    assert closed and app.state.desk.active["status"] == "error"
    assert "provider-sensitive-detail" not in app.state.desk.active["error"]

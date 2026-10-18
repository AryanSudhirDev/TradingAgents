"""Past-only replay boundaries, frozen forecasts and confirmed holding deadlines."""
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tradingagents import timestral_backtest as backtest
from tradingagents.dashboard.alpaca import BrokerError
from tradingagents.dashboard.holdings import deadline, sync_holdings
from tradingagents.dashboard.server import Desk
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.timestral_engine import TimestralEngine, decide, digest


def forecast(price=103):
    return {"rows": [{"median": price, "q10": price * .99, "q90": price * 1.01}] * 5}


def test_fixed_policy_accounts_for_reference_and_existing_positions():
    assert decide(forecast(), 100)["rating"] == "Overweight"
    assert decide(forecast(), 103)["rating"] == "Hold"
    assert decide(forecast(), 100, held=True)["rating"] == "Hold"
    assert decide(forecast(), 104, held=True)["rating"] == "Sell"
    assert decide(forecast(99), 100)["rating"] == "Hold"
    with pytest.raises(ValueError):
        decide(forecast(), float("nan"))


def test_forecaster_sees_only_history_and_reuses_hash_verified_output(tmp_path):
    engine = TimestralEngine({"results_dir": str(tmp_path)})
    calls = []
    levels = np.linspace(0, 1, 21)

    def predict(values, prediction_length):
        calls.append(values.copy())
        assert prediction_length == 5
        quantiles = values[-1] + np.linspace(-.02, .02, 21)
        return SimpleNamespace(quantiles=np.tile(quantiles, (1, 1, 5, 1)), quantile_levels=levels)

    engine.model = SimpleNamespace(forecast=predict)
    dates = [str(d.date()) for d in pd.bdate_range("2025-01-01", periods=133)]
    values = np.arange(128) + 100
    result = engine.forecast_history("AAPL", dates[:128], values, dates[128:])
    assert np.allclose(calls[0], np.log(values))
    assert result["last_session"] < result["rows"][0]["date"]
    assert engine.forecast_history("AAPL", dates[:128], values, dates[128:])["cache_hit"]
    assert len(calls) == 1
    path = next(tmp_path.rglob("*.json"))
    saved = json.loads(path.read_text())
    saved["inputs"]["closes"][-1] += 1
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="hash changed"):
        engine.forecast_history("AAPL", dates[:128], values, dates[128:])
    with pytest.raises(ValueError, match="strictly before"):
        engine.forecast_history("AAPL", dates[:128], values, dates[127:132])
    with pytest.raises(ValueError):
        engine.forecast_history("AAPL", dates[:128], np.full(128, np.nan), dates[128:])


class PrefixEngine:
    def __init__(self):
        self.inputs = []

    def forecast_history(self, ticker, dates, values, future):
        self.inputs.append((ticker, list(dates), values.tolist(), list(future)))
        assert dates[-1] < future[0]
        return {**forecast(float(values[-1]) * 1.05), "input_sha256": digest([dates, values.tolist()])}


def test_future_price_changes_cannot_change_earlier_decisions_and_portfolio():
    dates = [str(d.date()) for d in pd.bdate_range("2025-01-01", periods=148)]
    frames = {s: pd.DataFrame({"Open": 100., "Close": 100.}, index=dates) for s in backtest.SYMBOLS}
    first, second = PrefixEngine(), PrefixEngine()
    a = backtest.replay(frames, first, dates[128], dates[143], session_dates=dates)
    changed = {s: f.copy() for s, f in frames.items()}
    for frame in changed.values():
        frame.loc[dates[138]:, ["Open", "Close"]] *= 2
    b = backtest.replay(changed, second, dates[128], dates[143], session_dates=dates)
    assert [d for d in a["decisions"] if d["day"] < dates[138]] == [d for d in b["decisions"] if d["day"] < dates[138]]
    assert [r for r in a["curve"] if r["day"] < dates[138]] == [r for r in b["curve"] if r["day"] < dates[138]]
    assert first.inputs[:40] == second.inputs[:40]
    assert all(d["shares_before"] > 0 for d in a["decisions"][4:8])
    assert all(t["held_sessions"] <= 5 for t in a["trades"] if t.get("held_sessions"))
    assert any(t.get("deadline_exit") for t in a["trades"])
    assert all(r["cash"] >= 0 for r in a["curve"])
    broken = {s: f.drop(dates[130]) for s, f in frames.items()}
    with pytest.raises(ValueError, match="every exchange"):
        backtest.replay(broken, first, dates[128], dates[143], session_dates=dates)


def test_deadline_counts_exchange_sessions_including_entry_and_holiday():
    days = ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27", "2026-11-30"]
    assert deadline(days[0], [{"date": d} for d in days]) == "2026-11-30"
    with pytest.raises(BrokerError):
        deadline("2026-11-26", [{"date": d} for d in days])


def test_confirmed_ownership_survives_restart_without_resubmitting(tmp_path):
    desk = Desk({**DEFAULT_CONFIG, "results_dir": str(tmp_path)}, tmp_path / "paper.sqlite3")
    auto = desk.automation
    with auto.store.connect() as db:
        db.execute("UPDATE automation SET symbols='[\"AAPL\"]' WHERE id=1")
        db.execute("INSERT INTO paper_runs (account,day,ticker,client_id,status,note,updated,intent) VALUES ('paper','2026-10-16','AAPL','owned','submitted','','2026-10-16',?)", (json.dumps({"side": "buy", "qty": "5"}),))
    order = {"symbol": "AAPL", "side": "buy", "filled_qty": "2", "status": "partially_filled", "submitted_at": "2026-10-16T14:00:00Z"}
    broker = SimpleNamespace(order=lambda _: order)
    book = [{"symbol": "AAPL", "qty": "2"}]
    held = sync_holdings(auto, broker, book, "paper")
    assert held["AAPL"]["first_day"] == "2026-10-16"
    order.update(filled_qty="5", status="filled", filled_at="2026-10-19T14:00:00Z")
    book[0]["qty"] = "5"
    assert sync_holdings(auto, broker, book, "paper")["AAPL"]["first_day"] == "2026-10-16"
    broker.order = lambda _: pytest.fail("Confirmed terminal fills should be durable")
    assert sync_holdings(auto, broker, book, "paper")["AAPL"]["quantity"] == "5"
    with pytest.raises(BrokerError, match="differs"):
        sync_holdings(auto, broker, [{"symbol": "AAPL", "qty": "6"}], "paper")


def test_cross_market_evaluation_uses_each_calendar_and_keeps_targets_out_of_inputs():
    from tradingagents.timestral_markets import evaluate
    dates = [str(d.date()) for d in pd.date_range("2025-01-01", periods=148)]
    frame = pd.DataFrame({"Close": np.arange(148) + 100.}, index=dates)
    first, second = PrefixEngine(), PrefixEngine()
    a = evaluate(frame, first, "BTC-USD", dates, dates[128], dates[-1])
    changed = frame.copy()
    changed.loc[dates[138]:, "Close"] *= 2
    b = evaluate(changed, second, "BTC-USD", dates, dates[128], dates[-1])
    assert a["resolved"] == 4
    assert a["cells"][:2] == b["cells"][:2]
    assert first.inputs[:3] == second.inputs[:3]  # Even the third origin cannot see that day's close.
    assert all(c["input_last"] < c["origin"] <= c["target"] for c in a["cells"])
    with pytest.raises(ValueError, match="Missing expected"):
        evaluate(frame.drop(dates[130]), first, "BTC-USD", dates, dates[128], dates[-1])


def test_migration_preserves_history_pauses_once_and_separates_equity_epoch(tmp_path):
    path = tmp_path / "paper.sqlite3"
    auto = Desk(DEFAULT_CONFIG, path).automation
    with auto.store.connect() as db:
        db.execute("UPDATE automation SET engine_version='legacy',enabled=1 WHERE id=1")
        db.execute("INSERT INTO paper_equity VALUES ('paper','2026-01-01T00:00:00+00:00',10000000,100)")
    changed = Desk(DEFAULT_CONFIG, path).automation
    assert not changed.settings()["enabled"] and changed.settings()["engine_started_at"]
    assert not changed.performance("paper")["samples"]
    with changed.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM paper_equity").fetchone()[0] == 1
        db.execute("UPDATE automation SET enabled=1 WHERE id=1")
    assert Desk(DEFAULT_CONFIG, path).automation.settings()["enabled"]

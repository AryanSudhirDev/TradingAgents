"""One fixed walk-forward paper replay; the model never receives target outcomes."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.dashboard.alpaca import AlpacaPaper, size_order
from tradingagents.dashboard.operations import private_write
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.timestral_engine import (
    CONTEXT,
    HORIZON,
    MIN_CONTEXT,
    TimestralEngine,
    decide,
    digest,
)

SYMBOLS = ("AAPL", "MSFT", "NVDA", "JPM")
START, END = "2026-04-01", "2026-10-15"
COST = 0.005


def replay(frames, engine, start=START, end=END, arm="timestral", session_dates=None):
    """Carry cash, shares and entry age forward; decide using past forecasts and opening quotes."""
    if arm not in ("timestral", "always_enter", "random"):
        raise ValueError("Unknown fixed control")
    dates = list(frames[SYMBOLS[0]].index)
    sessions = sorted(set(session_dates or dates))
    if dates != [d for d in sessions if dates[0] <= d <= dates[-1]]:
        raise ValueError("Price history must include every exchange session; no gap filling.")
    if any(list(frames[s].index) != dates for s in SYMBOLS):
        raise ValueError("Every symbol must have identical completed session coverage.")
    for frame in frames.values():
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError("Price sessions must be unique and ordered")
        if not np.isfinite(frame[["Open", "Close"]].to_numpy()).all() or (frame[["Open", "Close"]] <= 0).any().any():
            raise ValueError("Prices must be finite and positive")
    cash, positions, opened = 100000.0, {}, {}
    curve, trades, decisions = [], [], []
    peak, drawdown = cash, 0.0
    for index, day in enumerate(dates):
        if not start <= day <= end:
            continue
        future = [d for d in sessions if d >= day][:HORIZON]
        if index < MIN_CONTEXT or len(future) != HORIZON:
            raise ValueError("Insufficient warm-up or horizon labels")
        for ticker in SYMBOLS:
            frame = frames[ticker]
            # Only prior closes cross the model boundary. Today's open is a decision-time execution proxy.
            history = frame["Close"].iloc[max(0, index - CONTEXT):index]
            forecast = engine.forecast_history(ticker, list(history.index), history.to_numpy(), future) if arm == "timestral" else None
            held = positions.get(ticker, 0)
            due = bool(held and index - opened[ticker] >= HORIZON - 1)
            reference = float(frame.loc[day, "Open"])
            if due:
                rating = "Sell"
            elif forecast:
                rating = decide(forecast, reference * (1 + COST if not held else 1 - COST), bool(held))["rating"]
            elif held:
                rating = "Hold"
            elif arm == "always_enter":
                rating = "Overweight"
            else:
                # Stable, predeclared coin per ticker/day; no search over random seeds or paths.
                rating = "Overweight" if int(digest(["timestral-random-v1", ticker, day])[:8], 16) % 2 else "Hold"
            decisions.append({"day": day, "ticker": ticker, "rating": rating, "cash_before": cash,
                              "shares_before": held, "deadline_exit": due,
                              "input_last_session": history.index[-1], "input_sha256": forecast["input_sha256"] if forecast else None})
            if rating == "Hold":
                continue
            book = [{"symbol": s, "qty": str(q), "market_value": str(q * float(frames[s].loc[day, "Open"]))} for s, q in positions.items() if q]
            equity = cash + sum(float(p["market_value"]) for p in book)
            price = round(reference * (1 + COST if rating == "Overweight" else 1 - COST), 2)
            intent = size_order(ticker, rating, {"equity": equity, "cash": cash}, book, price)
            if not intent:
                continue
            qty = int(intent["qty"])
            if intent["side"] == "buy":
                cash -= qty * price
                positions[ticker] = held + qty
                if not held:
                    opened[ticker] = index
            else:
                cash += qty * price
                positions[ticker] = held - qty
            if cash < -0.005:
                raise ValueError("Replay overspent cash")
            trades.append({"day": day, "ticker": ticker, "side": intent["side"], "quantity": qty, "price": price,
                           "deadline_exit": due, "held_sessions": index - opened[ticker] + 1 if intent["side"] == "sell" else None})
        equity = cash + sum(q * float(frames[s].loc[day, "Close"]) for s, q in positions.items())
        peak = max(peak, equity)
        drawdown = min(drawdown, (equity / peak - 1) * 100)
        curve.append({"day": day, "equity": equity, "cash": cash, "exposure_pct": (equity - cash) / equity * 100})
        print(arm, day, "complete", flush=True)
    if not curve:
        raise ValueError("No replay sessions")
    # Liquidate remaining positions at the last close with the same adverse cost; mark this boundary explicitly.
    for ticker, qty in positions.items():
        if qty:
            price = round(float(frames[ticker].loc[curve[-1]["day"], "Close"]) * (1 - COST), 2)
            cash += qty * price
            trades.append({"day": curve[-1]["day"], "ticker": ticker, "side": "sell", "quantity": qty,
                           "price": price, "boundary_liquidation": True, "held_sessions": None})
    peak = max(peak, cash)
    drawdown = min(drawdown, (cash / peak - 1) * 100)
    curve[-1].update(equity=cash, cash=cash)
    return {"arm": arm, "sessions": len(curve), "return_pct": (cash / 100000 - 1) * 100,
            "drawdown_pct": drawdown, "fills": len(trades), "average_exposure_pct": sum(r["exposure_pct"] for r in curve) / len(curve),
            "trades": trades, "decisions": decisions, "curve": curve}


def run(folder, engine=None):
    root = (Path.home() / ".tradingagents/experiments/timestral").resolve()
    folder = Path(folder).expanduser().resolve()
    if not folder.is_relative_to(root) or folder == root:
        raise ValueError("Use a private Timestral experiment folder")
    plan = {"start": START, "end": END, "symbols": list(SYMBOLS), "cost_per_side": COST,
            "engine": TimestralEngine.metadata(), "entry": "next-session adjusted open proxy", "initial_cash": 100000}
    manifest = folder / "plan.json"
    if manifest.exists() and json.loads(manifest.read_bytes()) != plan:
        raise ValueError("Saved plan differs; do not retune this run")
    private_write(manifest, json.dumps(plan, indent=2).encode())
    frames, hashes = {}, {}
    for ticker in SYMBOLS:
        path = folder / "prices" / f"{ticker}.csv"
        if not path.exists():
            with run_config(DEFAULT_CONFIG):
                frame = load_ohlcv(ticker, "2026-10-16", fill_gaps=False)
            private_write(path, frame.to_csv(index=False).encode())
        frame = pd.read_csv(path)
        frame["Date"] = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
        frames[ticker] = frame.set_index("Date")[["Open", "Close"]]
        hashes[ticker] = hashlib.sha256(path.read_bytes()).hexdigest()
    calendar_path = folder / "calendar.json"
    if not calendar_path.exists():
        broker = AlpacaPaper.load(Path.home() / ".tradingagents/dashboard/alpaca-paper.json")
        if not broker:
            raise ValueError("Paper credentials are required for the read-only exchange calendar.")
        private_write(calendar_path, json.dumps(broker.calendar(min(frames[SYMBOLS[0]].index), "2026-11-01")).encode())
    sessions = [row["date"] for row in json.loads(calendar_path.read_bytes())]
    hashes["calendar"] = hashlib.sha256(calendar_path.read_bytes()).hexdigest()
    previous = folder / "results.json"
    if previous.exists() and json.loads(previous.read_bytes())["price_sha256"] != hashes:
        raise ValueError("Frozen price hashes changed")
    # Future calendar labels beyond the evaluated period are harmless; no future target values cross the model boundary.
    config = {**DEFAULT_CONFIG, "results_dir": str(folder / "forecasts")}
    engine = engine or TimestralEngine(config)
    results = [replay(frames, engine, arm=arm, session_dates=sessions) for arm in ("timestral", "always_enter", "random")]
    result = {"plan": plan, "price_sha256": hashes, "completed_at": datetime.now(UTC).isoformat(), "arms": results,
              "limits": "Retrospective selected survivors and one fixed random path; not an independent significance test. Unknown pretrained-data overlap. Current adjusted OHLC is not a point-in-time corporate-action archive. Inputs use strictly prior closes and a carried portfolio. Opening fills are proxies for the production 10:00 NY execution window; no historical quotes, capacity, halts, taxes or cash yield. Fixed 0.5% cost per side does not guarantee fills. Five-session exits count entry as session one. Daily-close drawdown is sampled. End-boundary liquidation is explicit. Forecast accuracy and net trading payoffs remain distinct."}
    private_write(folder / "results.json", json.dumps(result, indent=2, allow_nan=False).encode())
    print(json.dumps([{k: a[k] for k in ("arm", "sessions", "return_pct", "drawdown_pct", "fills")} for a in results], indent=2))
    return result


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    run(parser.parse_args().folder)

"""Matched forecast scores over frozen native-study inputs; never runs a graph."""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pandas as pd

from tradingagents.backtest import iter_grid
from tradingagents.dashboard.operations import private_write
from tradingagents.dashboard.store import stock_symbol
from tradingagents.memory import TradingMemoryLog

COMPANY_SECTORS = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "JPM": "Financials", "XOM": "Energy", "UNH": "Health care", "WMT": "Staples",
    "CAT": "Industrials", "GOOGL": "Communications", "AMZN": "Discretionary",
    "NEE": "Utilities", "PLD": "Real estate", "LIN": "Materials",
}
DIRECTION = {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}


def forecast_summary(rows):
    """Zero for an abstention; signed alpha is a direction score, not short P&L."""
    claimed = [r for r in rows if r["direction"]]
    return {"cells": len(rows), "directional_claims": len(claimed),
            "holds": len(rows) - len(claimed),
            "direction_hit_rate": sum(r["direction"] * r["alpha_pct"] > 0 for r in claimed) / len(claimed) if claimed else None,
            "mean_signed_alpha_pct": sum(r["direction"] * r["alpha_pct"] for r in rows) / len(rows) if rows else None}


def compare_study(folder):
    """Read one atomic manifest snapshot and verify every supplied price file."""
    from tradingagents.sector_study import make_signals

    root = (Path.home() / ".tradingagents/experiments/agents").resolve()
    folder = Path(folder).expanduser().resolve()
    if not folder.is_relative_to(root) or folder == root:
        raise ValueError("Choose an existing private native-agent experiment.")
    content = (folder / "results.json").read_bytes()
    manifest = json.loads(content)
    tickers, dates = manifest["tickers"], manifest["dates"]
    if (not tickers or not dates or len(set(tickers)) != len(tickers) or len(set(dates)) != len(dates)
            or any(stock_symbol(t) != t for t in tickers)
            or any(iter_grid(d, d) != [d] for d in dates)):
        raise ValueError("Native companies and dates must be unique, canonical and nonempty.")
    holding = manifest["holding_sessions"]
    if type(holding) is not int or holding < 1:
        raise ValueError("The native holding period must be a positive session count.")
    frames = {}
    for ticker in dict.fromkeys(["SPY", *tickers]):
        # Filenames come from the native runner's validated stock symbols.
        ticker = stock_symbol(ticker)
        data = (folder / "validation_prices" / f"{ticker}.csv").read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest.get("validation_price_hashes", {}).get(ticker):
            raise ValueError(f"Frozen validation price hash mismatch: {ticker}")
        frame = pd.read_csv(BytesIO(data))
        frame["Date"] = pd.to_datetime(frame["Date"], errors="raise").dt.normalize()
        frame = frame.set_index("Date")
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError(f"Invalid frozen date order: {ticker}")
        frames[ticker] = frame["Close"]
    closes = pd.DataFrame(frames)
    if closes.isna().any().any() or not closes.map(lambda p: pd.notna(p) and 0 < p < float("inf")).all().all():
        raise ValueError("Frozen close coverage must be complete, finite and positive.")
    signals = make_signals(closes)
    rules = ("buy_hold", "sma_50_200", "momentum_252", "weekly_reversal")
    cells = []
    for ticker in tickers:
        for day in dates:
            when = pd.Timestamp(day)
            if when not in closes.index:
                raise ValueError(f"Missing analysis session: {ticker} {day}")
            index = closes.index.get_loc(when)
            if index < 252 or index + holding >= len(closes):
                raise ValueError(f"Incomplete warm-up or outcome window: {ticker} {day}")
            after = closes.index[index + holding]
            raw = (closes.loc[after, ticker] / closes.loc[when, ticker] - 1) * 100
            benchmark = (closes.loc[after, "SPY"] / closes.loc[when, "SPY"] - 1) * 100
            cells.append({"ticker": ticker, "date": day, "sector": COMPANY_SECTORS.get(ticker, "Unmapped"),
                          "outcome_date": str(after.date()), "raw_return_pct": float(raw), "alpha_pct": float(raw - benchmark),
                          "rules": {rule: int(signals[rule].loc[when, ticker]) for rule in rules}})
    logs, coverage = {}, {}
    for name in ("market_only", "full"):
        path = folder / "backtest" / name / "trading_memory.md"
        entries = TradingMemoryLog({"memory_log_path": str(path)}).load_entries() if path.is_file() else []
        expected = {(t, d) for t in tickers for d in dates}
        entries = [e for e in entries if (e["ticker"], e["date"]) in expected]
        eligible = [e for e in entries if not e["pending"] and e["rating"] in DIRECTION and e.get("holding") == f"{holding}d"]
        logs[name] = {(e["ticker"], e["date"]): e for e in eligible}
        coverage[name] = {"requested": len(cells), "saved": len(entries), "resolved_readable": len(logs[name]),
                          "pending": sum(e["pending"] for e in entries),
                          "horizon_mismatch": sum(not e["pending"] and e.get("holding") != f"{holding}d" for e in entries),
                          "unreadable": sum(e["rating"] not in DIRECTION for e in entries)}
    paired = [c for c in cells if all((c["ticker"], c["date"]) in logs[n] for n in logs)]
    scores = []
    for cell in paired:
        for name in (*rules, "market_only", "full"):
            direction = cell["rules"][name] if name in rules else DIRECTION[logs[name][cell["ticker"], cell["date"]]["rating"]]
            scores.append({"arm": name, "ticker": cell["ticker"], "date": cell["date"],
                           "sector": cell["sector"], "direction": direction, "alpha_pct": cell["alpha_pct"]})
    summary = {name: forecast_summary([r for r in scores if r["arm"] == name]) for name in (*rules, "market_only", "full")}
    by_sector = {sector: {name: forecast_summary([r for r in scores if r["sector"] == sector and r["arm"] == name])
                         for name in (*rules, "market_only", "full")}
                 for sector in sorted({c["sector"] for c in cells})}
    return {"study": folder.name, "tickers": tickers, "dates": dates,
            "usage": {k: sum(v.get("usage", {}).get(k, 0) for v in manifest.get("variants", []))
                      for k in ("llm_calls", "tool_calls", "tokens_in", "tokens_out")},
            "as_of": datetime.now(UTC).isoformat(), "manifest_sha256": hashlib.sha256(content).hexdigest(),
            "status": manifest.get("status"), "holding_sessions": holding, "expected_cells": len(cells),
            "paired_resolved_cells": len(paired), "coverage": coverage, "cells": cells, "scores": scores,
            "summary": summary, "by_sector": by_sector,
            "limits": "Direction times frozen SPY-relative return is a forecast score, not portfolio P&L. Hold is no direction; bearish scores are not executed shorts. Scores use common unrounded frozen prices, which can differ from native rounded/fresh outcomes. Current sector labels, selected survivors, shared dates, incomplete old text and model-training leakage limit inference."}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    args = parser.parse_args()
    try:
        result = compare_study(args.folder)
        path = Path(args.folder).expanduser().resolve() / "deterministic_baselines/results.json"
        private_write(path, json.dumps(result, indent=2, allow_nan=False).encode())
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"path": str(path), "expected_cells": result["expected_cells"], "paired_resolved_cells": result["paired_resolved_cells"]}))


if __name__ == "__main__":
    main()

"""Fixed observation-only cross-market forecasting comparison; never places trades."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.dashboard.operations import private_write
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.timestral_backtest import END, START
from tradingagents.timestral_engine import CONTEXT, HORIZON, MIN_CONTEXT, TimestralEngine

PANEL = {"SPY": "US equity", "QQQ": "US equity", "IWM": "US equity", "EFA": "International equity",
         "EEM": "International equity", "TLT": "Treasury bonds", "IEF": "Treasury bonds",
         "LQD": "Corporate bonds", "GLD": "Gold", "SLV": "Silver", "USO": "Oil fund",
         "UUP": "Dollar fund", "BTC-USD": "Crypto", "ETH-USD": "Crypto"}
LIMITS = ("Forecast scores, not trading returns. Fixed 14-series panel, one model and one period; no tuning or automatic promotion. "
          "Five observations mean five NYSE sessions for US-listed funds and five calendar days for crypto. "
          "Origins are spaced five observations apart within each series; shared market shocks still correlate scores. "
          "Dollar and oil funds are investment-product proxies, not spot FX or directly tradable futures. "
          "Unknown pretrained-data overlap, selected surviving products and current adjusted prices limit historical inference. "
          "No fees, execution, leverage, financing or portfolio are modeled here. Quantiles are uncalibrated estimates. "
          "This panel does not test electricity, demand or weather; public general forecasting benchmarks do not establish a market edge.")


def evaluate(frame, engine, ticker, sessions, start=START, end=END):
    dates = list(frame.index)
    if not dates or dates != sorted(set(dates)):
        raise ValueError("Unique ordered observations are required")
    if dates != [d for d in sessions if dates[0] <= d <= dates[-1]]:
        raise ValueError("Missing expected observations; no filling allowed")
    values = frame["Close"].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Complete positive numerical observations required")
    first = next(i for i, d in enumerate(dates) if d >= start)
    if first < MIN_CONTEXT:
        raise ValueError("Insufficient warm-up")
    cells = []
    for index in range(first, len(dates) - HORIZON + 1, HORIZON):
        if dates[index + HORIZON - 1] > end:
            break
        past = dates[max(0, index - CONTEXT):index]
        context = values[max(0, index - CONTEXT):index]
        future = dates[index:index + HORIZON]
        forecast = engine.forecast_history(ticker, past, context, future)
        last, actual = float(context[-1]), float(values[index + HORIZON - 1])
        flat = last
        drift = float(np.exp(np.log(last) + HORIZON * np.diff(np.log(context[-21:])).mean()))
        terminal = forecast["rows"][-1]
        median = terminal["median"]
        cells.append({"origin": future[0], "target": future[-1], "input_last": past[-1],
                      "input_sha256": forecast["input_sha256"], "actual": actual, "median": median,
                      "model_ape": abs(median / actual - 1) * 100, "flat_ape": abs(flat / actual - 1) * 100,
                      "drift_ape": abs(drift / actual - 1) * 100,
                      "covered_q10_q90": terminal["q10"] <= actual <= terminal["q90"],
                      "direction_correct": bool((median - last) * (actual - last) > 0) if actual != last else None})
    if not cells:
        raise ValueError("No resolved forecast windows")
    def mean(key):
        return float(np.mean([c[key] for c in cells]))
    flat_error = mean("flat_ape")
    directional = [c["direction_correct"] for c in cells if c["direction_correct"] is not None]
    return {"ticker": ticker, "market": PANEL.get(ticker, "fixture"), "resolved": len(cells),
            "model_mape_pct": mean("model_ape"), "flat_mape_pct": flat_error, "drift_mape_pct": mean("drift_ape"),
            "skill_vs_flat_pct": (1 - mean("model_ape") / flat_error) * 100 if flat_error else None,
            "interval_coverage_pct": mean("covered_q10_q90") * 100,
            "direction_accuracy_pct": float(np.mean(directional)) * 100 if directional else None,
            "cells": cells}


def run(folder):
    root = Path.home() / ".tradingagents/experiments/timestral"
    folder = Path(folder).expanduser().resolve()
    if not folder.is_relative_to(root.resolve()) or folder == root.resolve():
        raise ValueError("Use a private Timestral experiment folder")
    plan = {"panel": PANEL, "start": START, "end": END, "stride": 5, "engine": TimestralEngine.metadata(),
            "baselines": ["last completed close", "20-observation log drift"], "mode": "observation-only"}
    manifest = folder / "plan.json"
    if manifest.exists() and json.loads(manifest.read_bytes()) != plan:
        raise ValueError("Saved plan differs; no silent retuning")
    if not manifest.exists():
        private_write(manifest, json.dumps(plan, indent=2).encode())
    previous = folder / "results.json"
    old = json.loads(previous.read_bytes()) if previous.exists() else None
    engine = TimestralEngine({**DEFAULT_CONFIG, "results_dir": str(folder / "forecasts")})
    aggregates, hashes, failed = [], {}, []
    for ticker in PANEL:
        try:
            path = folder / "prices" / f"{ticker}.csv"
            if not path.exists():
                with run_config(DEFAULT_CONFIG):
                    frame = load_ohlcv(ticker, "2026-10-16", fill_gaps=False)
                private_write(path, frame.to_csv(index=False).encode())
            hashes[ticker] = hashlib.sha256(path.read_bytes()).hexdigest()
            if old and ticker in old["price_sha256"] and old["price_sha256"][ticker] != hashes[ticker]:
                raise ValueError("Frozen data hash changed")
            frame = pd.read_csv(path)
            frame["Date"] = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
            frame = frame.set_index("Date")
            start_date, end_date = min(frame.index), max(frame.index)
            if ticker.endswith("-USD"):
                sessions = [str(d.date()) for d in pd.date_range(start_date, end_date)]
            else:
                import exchange_calendars
                calendar = exchange_calendars.get_calendar("XNYS", start=start_date, end=end_date)
                sessions = [str(d.date()) for d in calendar.sessions_in_range(start_date, end_date)]
            result = evaluate(frame, engine, ticker, sessions)
            private_write(folder / "cells" / f"{ticker}.json", json.dumps(result["cells"], indent=2).encode())
            aggregates.append({k: v for k, v in result.items() if k != "cells"})
            print(ticker, "resolved", result["resolved"], flush=True)
        except Exception as exc:
            failed.append({"ticker": ticker, "error": type(exc).__name__ + ": " + str(exc)})
            print(ticker, "failed", type(exc).__name__, flush=True)
    saved = {"plan": plan, "price_sha256": hashes, "aggregates": aggregates, "failed": failed,
             "completed_at": datetime.now(UTC).isoformat(), "limits": LIMITS}
    private_write(previous, json.dumps(saved, indent=2, allow_nan=False).encode())
    print(json.dumps(saved["aggregates"], indent=2))
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    run(parser.parse_args().folder)

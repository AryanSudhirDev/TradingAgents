"""Isolated historical strategy comparisons; never submits broker orders."""

import argparse
import hashlib
import json
import math
import os
import time
from dataclasses import asdict
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path

import pandas as pd

from cli.stats_handler import StatsCallbackHandler
from tradingagents.backtest import iter_grid, run_backtest, summarize
from tradingagents.dashboard.operations import private_write
from tradingagents.dashboard.store import stock_symbol
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.files import locked
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import _NOT_IN_SIGNATURE
from tradingagents.reporting import write_report_tree

INITIAL_EQUITY = 100_000.0
RULES = {
    "basket_hold": "Buy and hold basket",
    "sma_50_200": "50/200-day trend",
    "momentum_126": "126-session momentum",
    "spy_matched": "SPY: matched initial allocation",
    "spy_100": "SPY: 100% initial allocation",
    "cash": "Cash: no interest",
}


def render_comparison(report):
    rows = []
    stress = {r["rule"]: r for r in report["results"] if r["slippage_bps"] == 20}
    for row in (r for r in report["results"] if r["slippage_bps"] == 5):
        rows.append("<tr>" + "".join(f"<td>{value}</td>" for value in (
            escape(row["label"]), f'{row["return_pct"]:+.2f}%', f'{row["max_drawdown_pct"]:.2f}%',
            f'{row["average_exposure_pct"]:.1f}%', str(row["fill_count"]), f'{stress[row["rule"]]["return_pct"]:+.2f}%',
        )) + "</tr>")
    notes = "".join(f"<li>{escape(note)}</li>" for note in report["assumptions"])
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Historical strategy comparison</title><style>
body{{margin:0;font-family:var(--font-sans,system-ui);color:var(--foreground,CanvasText);background:transparent;line-height:1.5}}h2{{font-size:1.2em;font-weight:500}}p,li{{max-width:75ch}}.muted{{color:var(--muted-foreground,GrayText)}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{padding:10px 8px;text-align:right;border-bottom:1px solid var(--border,GrayText)}}th:first-child,td:first-child{{text-align:left}}th{{font-weight:500}}details{{margin-top:20px}}li{{margin-bottom:8px}}
</style><main><h2>Historical price-rule comparison</h2>
<p>{escape(report["first_session"])} to {escape(report["last_session"])} · {report["sessions"]} sessions · {escape(", ".join(report["tickers"]))}</p>
<p class="muted">$100,000 simulated starting capital. Basket and matched SPY start with up to {report["entry_allocation_pct"]:g}% exposure; holdings can drift above it. The 100% SPY reference has different initial risk. Total returns below are cumulative, not annual.</p>
<div class="scroll"><table><thead><tr><th>Strategy</th><th>Total return</th><th>Max drawdown</th><th>Average exposure</th><th>Fills</th><th>Return at higher cost</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p class="muted">Base cost: 0.05% adverse slippage per fill. Higher-cost column: 0.20% per fill. These price rules do not measure the TradingAgents team's performance.</p>
<details><summary>Method and limits</summary><ul>{notes}</ul></details></main></html>'''


def run_agent_comparison(tickers, dates, config=None, resume=None):
    """Exercise the native decision evaluator with isolated full and market-only runs."""
    tickers = list(dict.fromkeys(stock_symbol(t) for t in tickers))
    dates = list(dict.fromkeys(dates))
    if not 1 <= len(tickers) <= 8 or not dates:
        raise ValueError("Choose one to eight companies and at least one analysis date.")
    if any(iter_grid(day, day) != [day] for day in dates):
        raise ValueError("Choose canonical analysis dates that are not in the future.")
    config = config or DEFAULT_CONFIG
    root = (Path.home() / ".tradingagents/experiments/agents").resolve()
    folder = Path(resume).expanduser().resolve() if resume else root / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    if not folder.is_relative_to(root) or folder == root:
        raise ValueError("Resume an experiment inside ~/.tradingagents/experiments/agents/.")
    if not resume:
        folder.mkdir(parents=True, mode=0o700)
    with locked(folder / "experiment", wait=False) as acquired:
        if not acquired:
            raise ValueError("This experiment is already running; do not start another copy.")
        return _run_agent_comparison(tickers, dates, config, folder, resume)


def _run_agent_comparison(tickers, dates, config, folder, resume):
    experiment = {"tickers": tickers, "dates": dates, "provider": config["llm_provider"],
                  "quick_model": config["quick_think_llm"], "deep_model": config["deep_think_llm"],
                  "settings_hash": hashlib.sha256(json.dumps({k: v for k, v in config.items() if k not in _NOT_IN_SIGNATURE}, sort_keys=True, default=str).encode()).hexdigest(),
                  "options": {k: config.get(k) for k in ("quick_think_provider", "deep_think_provider", "max_debate_rounds", "max_risk_discuss_rounds", "temperature", "output_language", "data_vendors", "tool_vendors")},
                  "holding_sessions": config.get("holding_period_days", 5), "variants": [],
                  "usage_note": "Observed model calls and tokens, not a dollar bill or subscription-credit conversion. Interrupted responses may omit usage; pre-instrumentation runs are excluded.",
                  "limits": "Decision scoring, not a portfolio simulation. Historical text coverage is incomplete; model training may contain later events. One sample per cell cannot establish an edge."}
    if resume:
        saved = json.loads((folder / "results.json").read_text())
        if any(saved.get(key) != experiment[key] for key in ("tickers", "dates", "provider", "quick_model", "deep_model", "holding_sessions")):
            raise ValueError("Resume with the original companies, dates, provider, models and holding period.")
        if "options" in saved and saved["options"] != experiment["options"]:
            raise ValueError("Resume with the original agent and data settings.")
        if "settings_hash" in saved and saved["settings_hash"] != experiment["settings_hash"]:
            raise ValueError("Resume with the original model and data configuration.")
        saved.setdefault("options", experiment["options"])
        saved.setdefault("settings_hash", experiment["settings_hash"])
        saved.setdefault("usage_note", experiment["usage_note"])
        experiment = saved
    experiment["status"] = "running"
    experiment["updated_at"] = datetime.now(UTC).isoformat()
    private_write(folder / "results.json", json.dumps(experiment, indent=2).encode())
    for name, analysts in (("market_only", ["market"]), ("full", ["market", "social", "news", "fundamentals"])):
        _run_agent_variant(name, analysts, experiment, config, folder)
    experiment["status"] = "incomplete" if any(v["status"] != "complete" for v in experiment["variants"]) else "complete"
    private_write(folder / "results.json", json.dumps(experiment, indent=2, allow_nan=False).encode())
    return experiment, folder


def _run_agent_variant(name, analysts, experiment, config, folder):
    tickers, dates = experiment["tickers"], experiment["dates"]
    started = time.monotonic()
    isolated = {**config, "results_dir": str(folder), "data_cache_dir": str(folder / name / "cache")}
    print(json.dumps({"variant_started": name, "cells": len(tickers) * len(dates), "folder": str(folder)}), flush=True)
    previous = next((v for v in experiment["variants"] if v["name"] == name), {})
    attempts = list(previous.get("attempts", []))
    if previous and not attempts:
        attempts.append({"failures": previous.get("failures", []), "settlement_failures": previous.get("settlement_failures", [])})
    cells_run = previous.get("cells_run", 0)
    path = folder / "backtest" / name / "trading_memory.md"
    if path.exists():
        saved = summarize(path)
        cells_run = saved.resolved + saved.pending + saved.unscored
    stats = StatsCallbackHandler()
    prior_usage = previous.get("usage", {})

    def save_progress(done, total, ticker, day):
        usage = {k: prior_usage.get(k, 0) + v for k, v in stats.get_stats().items()}
        running = {**previous, "name": name, "analysts": analysts, "status": "running",
                   "current_cell": {"ticker": ticker, "date": day, "index": done, "remaining_this_attempt": total},
                   "attempts": attempts, "cells_run": cells_run,
                   "usage": usage, "elapsed_seconds": previous.get("elapsed_seconds", 0) + time.monotonic() - started}
        if path.exists():
            running["summary"] = asdict(summarize(path))
            running["cells_run"] = sum(running["summary"][k] for k in ("resolved", "pending", "unscored"))
        experiment["variants"] = [v for v in experiment["variants"] if v["name"] != name] + [running]
        experiment["updated_at"] = datetime.now(UTC).isoformat()
        private_write(folder / "results.json", json.dumps(experiment, indent=2, allow_nan=False).encode())
        print(json.dumps({"variant": name, "cell": f"{done}/{total}", "ticker": ticker, "day": day}), flush=True)

    for attempt in range(2):
        result = run_backtest(tickers, dates, isolated, selected_analysts=analysts, run_id=name,
                              progress=save_progress, callbacks=[stats])
        cells_run += result.cells_run
        attempts.append({"cells_run": result.cells_run, "skipped": result.skipped,
                         "failures": result.failures, "settlement_failures": result.settlement_failures})
        if not result.failures and not result.settlement_failures:
            break
        if attempt == 0:
            print(json.dumps({"retrying_variant": name, "reason": "Resume failed cells/checkpoints or retry settlement once; completed cells are skipped."}), flush=True)
    reports = []
    for ticker in tickers:
        for day in dates:
            state_path = result.log_path.parent / ticker / "TradingAgentsStrategy_logs" / f"full_states_log_{day}.json"
            if state_path.exists():
                state = json.loads(state_path.read_text())
                report_path = write_report_tree(state, ticker, result.log_path.parent / "reports" / ticker / day, settings=state.get("run_settings"))
                reports.append(str(report_path.with_suffix(".html")))
    variant = {"name": name, "analysts": analysts, "elapsed_seconds": previous.get("elapsed_seconds", 0) + time.monotonic() - started,
               "status": "incomplete" if result.failures or result.settlement_failures else "complete",
               "usage": {k: prior_usage.get(k, 0) + v for k, v in stats.get_stats().items()},
               "cells_run": cells_run, "attempts": attempts, "failures": result.failures,
               "skipped_cells": result.skipped,
               "settlement_failures": result.settlement_failures, "log_path": str(result.log_path),
               "reports": reports,
               "summary": asdict(summarize(result))}
    experiment["variants"] = [v for v in experiment["variants"] if v["name"] != name] + [variant]
    experiment["updated_at"] = datetime.now(UTC).isoformat()
    private_write(folder / "results.json", json.dumps(experiment, indent=2, allow_nan=False).encode())
    print(json.dumps({"variant_finished": name, "cells_run": cells_run, "failures": len(result.failures), "resolved": variant["summary"]["resolved"]}), flush=True)


def historical_bounds(start, end):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end or end >= date.today():
        raise ValueError("Choose an ordered historical range ending before today.")
    return start, end


def prepare_prices(frames, tickers, start, end, warmup_sessions=200):
    start, end = historical_bounds(start, end)
    if type(warmup_sessions) is not int or warmup_sessions < 200:
        raise ValueError("Use at least 200 whole warm-up sessions.")
    cleaned = {}
    for ticker in dict.fromkeys([*tickers, "SPY"]):
        frame = frames[ticker].copy()
        frame["Date"] = pd.to_datetime(frame["Date"]).dt.tz_localize(None).dt.normalize()
        if frame["Date"].isna().any():
            raise ValueError(f"{ticker} has invalid dates.")
        frame = frame.set_index("Date")[["Open", "Close"]]
        frame = frame.loc[frame.index <= pd.Timestamp(end)]
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            raise ValueError(f"{ticker} dates must be unique and increasing.")
        if not frame.map(lambda p: isinstance(p, (int, float)) and math.isfinite(p) and p > 0).all().all():
            raise ValueError(f"{ticker} has missing or invalid prices; gaps are not filled.")
        cleaned[ticker] = frame
    sessions = cleaned["SPY"].loc[str(start):str(end)].index
    if len(sessions) < 2:
        raise ValueError("The requested range needs at least two market sessions.")
    warmup = cleaned["SPY"].loc[cleaned["SPY"].index < sessions[0]].tail(warmup_sessions).index
    if len(warmup) < warmup_sessions:
        raise ValueError(f"SPY needs {warmup_sessions} warm-up sessions before the first trade.")
    required = warmup.append(sessions)
    for ticker, frame in cleaned.items():
        if not required.isin(frame.index).all():
            raise ValueError(f"{ticker} is missing a benchmark session; cannot compare it fairly.")
    opens = pd.DataFrame({t: f["Open"].reindex(required) for t, f in cleaned.items()})
    closes = pd.DataFrame({t: f["Close"].reindex(required) for t, f in cleaned.items()})
    # No strategy can observe the execution session's closing price.
    signals = {
        "basket_hold": pd.DataFrame(True, index=closes.index, columns=tickers),
        "sma_50_200": (closes[tickers].rolling(50).mean() > closes[tickers].rolling(200).mean()).shift(1, fill_value=False),
        "momentum_126": (closes[tickers] > closes[tickers].shift(126)).shift(1, fill_value=False),
        "spy_matched": pd.DataFrame(True, index=closes.index, columns=["SPY"]),
        "spy_100": pd.DataFrame(True, index=closes.index, columns=["SPY"]),
        "cash": pd.DataFrame(False, index=closes.index, columns=tickers),
    }
    return opens.loc[sessions], closes.loc[sessions], {k: v.loc[sessions] for k, v in signals.items()}, cleaned


def simulate(opens, closes, signals, allocation, slippage_bps, target_weight=None):
    """Fractional adjusted-price units, next-open fills, sell before buy; no rebalancing."""
    if not 0 <= allocation <= 1 or not 0 <= slippage_bps <= 100:
        raise ValueError("Allocation must be 0..1 and slippage 0..100 basis points.")
    cash, units, fills, curve = INITIAL_EQUITY, dict.fromkeys(signals.columns, 0.0), [], []
    target = min(0.10, allocation / len(units)) if len(units) > 1 else allocation
    if target_weight is not None:
        if not 0 <= target_weight <= allocation:
            raise ValueError("The per-position entry target must be within the portfolio allocation.")
        target = target_weight
    slip = slippage_bps / 10_000
    for day, active in signals.iterrows():
        opening = opens.loc[day]
        for ticker in units:
            if units[ticker] and not active[ticker]:
                price = float(opening[ticker]) * (1 - slip)
                quantity = units[ticker]
                cash += quantity * price
                units[ticker] = 0.0
                fills.append({"day": str(day.date()), "ticker": ticker, "side": "sell", "units": quantity, "price": price})
        for ticker in units:
            if active[ticker] and not units[ticker]:
                gross = sum(q * float(opening[t]) for t, q in units.items())
                equity = cash + gross
                budget = max(0, min(equity * target, equity * allocation - gross, cash))
                if budget > 1e-7:
                    price = float(opening[ticker]) * (1 + slip)
                    units[ticker] = budget / price
                    cash -= budget
                    fills.append({"day": str(day.date()), "ticker": ticker, "side": "buy", "units": units[ticker], "price": price})
        gross = sum(q * float(closes.loc[day, t]) for t, q in units.items())
        equity = cash + gross
        if cash < -1e-7 or not math.isfinite(equity) or equity <= 0:
            raise ValueError("The simulation produced an invalid portfolio.")
        curve.append({"day": str(day.date()), "equity": equity, "exposure_pct": gross / equity * 100})
    values = pd.Series([INITIAL_EQUITY, *[r["equity"] for r in curve]])
    elapsed = max(1, (signals.index[-1] - signals.index[0]).days + 1) / 365.25
    return {"final_equity": curve[-1]["equity"], "return_pct": (curve[-1]["equity"] / INITIAL_EQUITY - 1) * 100,
            "cagr_pct": ((curve[-1]["equity"] / INITIAL_EQUITY) ** (1 / elapsed) - 1) * 100,
            "max_drawdown_pct": float((values / values.cummax() - 1).min() * 100),
            "average_exposure_pct": sum(r["exposure_pct"] for r in curve) / len(curve),
            "fill_count": len(fills), "fills": fills, "curve": curve}


def run_comparison(tickers, start, end, config=None):
    historical_bounds(start, end)
    tickers = list(dict.fromkeys(stock_symbol(t) for t in tickers))
    if not 1 <= len(tickers) <= 8:
        raise ValueError("Choose one to eight US stocks or ETFs.")
    config = config or DEFAULT_CONFIG
    folder = Path.home() / ".tradingagents/experiments/strategies" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    with run_config(config):
        frames = {t: load_ohlcv(t, end, fill_gaps=False) for t in dict.fromkeys([*tickers, "SPY"])}
    opens, closes, signals, cleaned = prepare_prices(frames, tickers, start, end)
    report = {"created_at": datetime.now(UTC).isoformat(), "requested_start": start, "requested_end": end,
              "first_session": str(opens.index[0].date()), "last_session": str(opens.index[-1].date()),
              "sessions": len(opens), "tickers": tickers, "initial_equity": INITIAL_EQUITY,
              "entry_allocation_pct": min(0.4, 0.1 * len(tickers)) * 100,
              "data_hashes": {}, "results": [], "assumptions": [
                  "No LLM, news, fundamentals or social inputs; these results do not measure TradingAgents performance.",
                  "Yahoo dividend/split-adjusted OHLC, fractional adjusted units; a return model, not historical broker shares.",
                  "Signals use the previous session's close; entries and exits execute at the next available session open.",
                  "Basket positions target at most 10% of equity on entry; total purchases respect a 40% gross ceiling. Holdings can drift above it.",
                  "Positions are held until a signal turns off; no daily rebalancing, shorts or leverage. Cash earns no interest.",
                  "Adverse slippage of 5 and 20 basis points on every fill; commissions, taxes, liquidity and market impact omitted.",
                  "Open positions are marked at the final close, not liquidated. SPY 100% has more initial exposure than the basket.",
                  "The companies are selected today: survivorship/selection bias applies. Parameters were fixed before inspecting these results.",
                  "Historical slices are descriptive; neither a fresh sample nor proof of future performance. No strategy is promoted automatically.",
              ]}
    for ticker, frame in cleaned.items():
        content = frame.to_csv().encode()
        private_write(folder / "data" / f"{ticker}.csv", content)
        report["data_hashes"][ticker] = hashlib.sha256(content).hexdigest()
    for bps in (5, 20):
        for rule, active in signals.items():
            report["results"].append({"rule": rule, "label": RULES[rule], "slippage_bps": bps,
                                      **simulate(opens, closes, active, 1.0 if rule == "spy_100" else min(0.4, 0.1 * len(tickers)), bps)})
    private_write(folder / "results.json", json.dumps(report, indent=2, allow_nan=False).encode())
    private_write(folder / "report.html", render_comparison(report).encode())
    return report, folder


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default="AAPL,MSFT,NVDA,JPM")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--agents", action="store_true", help="Run full versus market-only native decision scoring on a date grid; calls the configured models.")
    parser.add_argument("--resume", help="Continue a native --agents experiment from its private output folder.")
    parser.add_argument("--every", type=int, default=7, help="Calendar days between --agents analysis dates (default: 7). Choose exchange sessions.")
    args = parser.parse_args()
    if args.resume and not args.agents:
        parser.error("--resume requires --agents.")
    try:
        if args.agents:
            result, folder = run_agent_comparison(args.tickers.split(","), iter_grid(args.start, args.end, args.every), resume=args.resume)
            print(json.dumps({"folder": str(folder), "variants": result["variants"]}, indent=2))
            if any(v["failures"] or v["settlement_failures"] for v in result["variants"]):
                parser.exit(1)
            return
        result, folder = run_comparison(args.tickers.split(","), args.start, args.end)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        parser.error(str(exc))
    summary = [{k: r[k] for k in ("label", "slippage_bps", "return_pct", "max_drawdown_pct", "fill_count")} for r in result["results"]]
    print(json.dumps({"folder": str(folder), "sessions": result["sessions"], "results": summary}, indent=2))


if __name__ == "__main__":
    main()

"""A fixed, retrospective ETF price-rule experiment; no model or broker calls."""

import argparse
import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from tradingagents.dashboard.operations import private_write
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv
from tradingagents.strategy_comparison import INITIAL_EQUITY, prepare_prices, simulate

ASSETS = {
    "XLB": {"label": "Materials", "group": "sector"},
    "XLC": {"label": "Communication services", "group": "sector"},
    "XLE": {"label": "Energy", "group": "sector"},
    "XLF": {"label": "Financials", "group": "sector"},
    "XLI": {"label": "Industrials", "group": "sector"},
    "XLK": {"label": "Technology", "group": "sector"},
    "XLP": {"label": "Consumer staples", "group": "sector"},
    "XLRE": {"label": "Real estate", "group": "sector"},
    "XLU": {"label": "Utilities", "group": "sector"},
    "XLV": {"label": "Health care", "group": "sector"},
    "XLY": {"label": "Consumer discretionary", "group": "sector"},
    "SPY": {"label": "Broad US equities", "group": "us_equity"},
    "QQQ": {"label": "Large growth equities", "group": "us_equity"},
    "IWM": {"label": "Small-cap equities", "group": "us_equity"},
    "IWD": {"label": "Value equities", "group": "us_equity"},
    "IWF": {"label": "Growth equities", "group": "us_equity"},
    "EFA": {"label": "Developed international equities", "group": "international_equity"},
    "EEM": {"label": "Emerging-market equities", "group": "international_equity"},
    "SHY": {"label": "Short Treasury bonds", "group": "treasury"},
    "IEF": {"label": "Intermediate Treasury bonds", "group": "treasury"},
    "TLT": {"label": "Long Treasury bonds", "group": "treasury"},
    "GLD": {"label": "Gold", "group": "real_asset"},
    "DBC": {"label": "Commodities", "group": "real_asset"},
}
WINDOWS = {
    "development": {"start": "2022-11-01", "end": "2024-12-31"},
    "validation": {"start": "2025-01-02", "end": "2025-12-31"},
    "evaluation": {"start": "2026-01-02", "end": "2026-10-15"},
}
RULE_LABELS = {
    "buy_hold": "Buy and hold",
    "sma_50_200": "50/200-session trend",
    "momentum_252": "252-session momentum",
    "weekly_reversal": "Prior-week negative return: long-only timing",
    "sector_hold": "Buy and hold all 11 sectors",
    "sector_momentum_12_1": "Monthly top-four positive sector momentum (12–1)",
}
SINGLE_RULES = ("buy_hold", "sma_50_200", "momentum_252", "weekly_reversal")
COSTS = (5, 20)
SOURCES = [
    {"title": "Time Series Momentum", "url": "https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum"},
    {"title": "French Data Library: prior (2–12) return portfolios", "url": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.French/Data_Library/det_10_port_form_pr_12_2_daily.html"},
    {"title": "Fads, Martingales, and Market Efficiency", "url": "https://www.nber.org/papers/w2533"},
    {"title": "Trading Costs of Asset Pricing Anomalies", "url": "https://pages.stern.nyu.edu/~afrazzin/pdf/Trading%20Cost%20of%20Asset%20Pricing%20Anomalies%20-%20Frazzini,%20Israel%20and%20Moskowitz.pdf"},
    {"title": "State Street Select Sector ETFs", "url": "https://www.ssga.com/us/en/individual/capabilities/equities/sector-investing/select-sector-etfs"},
]
ASSUMPTIONS = [
    "All three chronological windows are retrospective and exploratory, including the window named evaluation; none is an untouched holdout. No strategy is promoted automatically.",
    "The current ETF universe has selection and survivorship bias. This fixed plan is frozen before this run's calculations, not before the historical periods occurred.",
    "These are price-only, long-only ETF adaptations motivated by the linked literature, not replications of academic results or measurements of TradingAgents model performance.",
    "Yahoo dividend/split-adjusted OHLC and fractional adjusted-price units model returns, not historical broker share counts. SPY supplies the common session calendar; gaps are rejected and at least 253 pre-window sessions are required so the prior-close decision has a full 252-session return.",
    "Each comparison starts fresh with $100,000. Singles enter a 40% sleeve; sector hold targets 40%/11 per entry; sector momentum targets 10% per entry in up to four positive sectors. These are different position weights with a common initial maximum risk budget, not continuously equal-risk portfolios.",
    "Single-asset rules are hold, SMA50 above SMA200, positive 252-session return, and a long-only timing adaptation that holds when the preceding completed calendar week's return is negative.",
    "Sector momentum ranks close(t-21)/close(t-252)-1 after each calendar month end, selects up to four strictly positive scores, and keeps membership until the next monthly update. Ties follow the fixed universe order.",
    "Weekly and monthly values publish at W-FRI and calendar-month-end timestamps, using only closes then known. On a holiday or weekend boundary they first appear at the next trading close, adding a conservative session of delay; they are never backdated to an earlier trading day.",
    "Decision-close signals shift exactly one trading session before next-open execution. Insufficient indicator history stays in cash. Continuing positions are not rebalanced; exposure can drift above the entry budget, and existing exposure can limit replacement purchases.",
    "No shorts, leverage, cash yield, taxes, commissions, liquidity or market-impact model. One-way adverse slippage is 5 or 20 basis points on every fill. Positions are marked at the final close without a final liquidation charge.",
    "Each single rule uses its own ETF buy-and-hold sleeve at the same cost as benchmark; sector momentum uses sector hold. Excess returns do not adjust for different realized exposures or multiple comparisons.",
    "Volatility and Sharpe use daily portfolio returns including the first session versus starting cash, 252 sessions per year and a zero cash rate; zero standard deviation gives no Sharpe. Traded notional sums both sides at simulated fill prices relative to initial equity.",
    "Source price CSVs, hashes and run artifacts remain in the private local experiment directory. Only aggregate results should be published.",
]


def _publish_at_calendar_boundary(values, index):
    # Union preserves non-session publication timestamps without backdating them.
    return values.reindex(values.index.union(index)).ffill().reindex(index).fillna(False).astype(bool)


def make_signals(closes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Unshifted close decisions; calendar boundary signals never inspect a future bar."""
    sectors = [t for t in ASSETS if ASSETS[t]["group"] == "sector" and t in closes]
    weekly = closes.resample("W-FRI").last().pct_change(fill_method=None).lt(0)
    scores = (closes[sectors].shift(21) / closes[sectors].shift(252) - 1).resample("ME").last()
    selected = scores.gt(0) & scores.rank(axis=1, method="first", ascending=False).le(4)
    return {
        "buy_hold": pd.DataFrame(True, index=closes.index, columns=closes.columns),
        "sma_50_200": closes.rolling(50).mean().gt(closes.rolling(200).mean()),
        "momentum_252": closes.gt(closes.shift(252)),
        "weekly_reversal": _publish_at_calendar_boundary(weekly, closes.index),
        "sector_hold": pd.DataFrame(True, index=closes.index, columns=sectors),
        "sector_momentum_12_1": _publish_at_calendar_boundary(selected, closes.index),
    }


def _portfolio_statistics(result):
    equity = pd.Series([INITIAL_EQUITY, *[point["equity"] for point in result["curve"]]])
    daily = equity.pct_change().dropna()
    deviation = float(daily.std())
    return {
        "annualized_volatility_pct": deviation * math.sqrt(252) * 100,
        "sharpe_zero_cash": float(daily.mean() / deviation * math.sqrt(252)) if deviation else None,
        "traded_notional_pct_initial": sum(fill["units"] * fill["price"] for fill in result["fills"]) / INITIAL_EQUITY * 100,
    }


def evaluate_frames(frames, windows=WINDOWS) -> list[dict]:
    """Evaluate the fixed arms with independent capital for each window and cost."""
    tickers = list(ASSETS)
    results = []
    for window, bounds in windows.items():
        opens, closes, _, cleaned = prepare_prices(frames, tickers, **bounds, warmup_sessions=253)
        historical_closes = pd.DataFrame({t: cleaned[t]["Close"] for t in tickers}).reindex(cleaned["SPY"].index)
        decisions = make_signals(historical_closes)
        execution = {name: signal.shift(1, fill_value=False).loc[opens.index] for name, signal in decisions.items()}
        sectors = list(execution["sector_hold"].columns)
        if not sectors:
            raise ValueError("The sector study requires sector ETF prices.")
        for bps in COSTS:
            arms = []
            for ticker, asset in ASSETS.items():
                for rule in SINGLE_RULES:
                    result = simulate(opens, closes, execution[rule][[ticker]], 0.4, bps)
                    arms.append({"ticker": ticker, **asset, "rule": rule, **result})
            for rule in ("sector_hold", "sector_momentum_12_1"):
                result = simulate(opens, closes, execution[rule], 0.4, bps,
                                  target_weight=0.4 / len(sectors) if rule == "sector_hold" else 0.1)
                arms.append({"ticker": "SECTORS", "label": "Sector basket", "group": "sector_basket", "rule": rule, **result})
            benchmarks = {row["ticker"]: row["return_pct"] for row in arms if row["rule"] in ("buy_hold", "sector_hold")}
            for row in arms:
                benchmark = benchmarks[row["ticker"]]
                results.append({**row, "window": window, **bounds, "slippage_bps": bps,
                                "first_session": str(opens.index[0].date()), "last_session": str(opens.index[-1].date()), "sessions": len(opens),
                                "benchmark_rule": "sector_hold" if row["ticker"] == "SECTORS" else "buy_hold",
                                "benchmark_return_pct": benchmark, "excess_return_pct": row["return_pct"] - benchmark,
                                **_portfolio_statistics(row)})
    return results


def run_study(config=None):
    """Freeze the plan and vendor data privately before evaluating the fixed suite."""
    created = datetime.now(UTC)
    folder = Path.home() / ".tradingagents/experiments/sectors" / created.strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True, mode=0o700)
    cache = folder / "cache"
    cache.mkdir(mode=0o700)
    plan = {"created_at": created.isoformat(), "study": "retrospective_exploratory_sector_price_rules",
            "assets": ASSETS, "windows": WINDOWS, "rules": RULE_LABELS, "slippage_bps": COSTS,
            "initial_equity": INITIAL_EQUITY, "warmup_sessions": 253, "entry_allocation_pct": 40,
            "case_count": (len(ASSETS) * len(SINGLE_RULES) + 2) * len(WINDOWS) * len(COSTS),
            "assumptions": ASSUMPTIONS, "sources": SOURCES}
    plan_bytes = json.dumps(plan, indent=2, allow_nan=False).encode()
    private_write(folder / "plan.json", plan_bytes)
    report = {"created_at": created.isoformat(), "status": "running", "plan": json.loads(plan_bytes),
              "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(), "tickers": list(ASSETS), "windows": WINDOWS,
              "case_count": plan["case_count"], "initial_equity": INITIAL_EQUITY, "entry_allocation_pct": 40,
              "data_hashes": {}, "results": [], "assumptions": ASSUMPTIONS, "sources": SOURCES}
    private_write(folder / "results.json", json.dumps(report, indent=2, allow_nan=False).encode())
    try:
        frames = {}
        end = max(bounds["end"] for bounds in WINDOWS.values())
        isolated = {**(config or {}), "data_cache_dir": str(cache), "results_dir": str(folder)}
        with run_config(isolated):
            for ticker in ASSETS:
                frame = load_ohlcv(ticker, end, fill_gaps=False)
                data = frame.to_csv(index=False).encode()
                private_write(folder / "data" / f"{ticker}.csv", data)
                report["data_hashes"][ticker] = hashlib.sha256(data).hexdigest()
                frames[ticker] = frame
        report["results"] = evaluate_frames(frames, windows=WINDOWS)
        if len(report["results"]) != plan["case_count"]:
            raise ValueError("The completed result count differs from the frozen plan.")
        report["status"] = "complete"
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        private_write(folder / "results.json", json.dumps(report, indent=2, allow_nan=False).encode())
        raise
    private_write(folder / "results.json", json.dumps(report, indent=2, allow_nan=False).encode())
    return report, folder


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        report, folder = run_study()
    except Exception as exc:
        parser.exit(1, f"Sector study failed: {exc}\n")
    print(json.dumps({"folder": str(folder), "status": report["status"], "simulations": len(report["results"])}))


if __name__ == "__main__":
    main()

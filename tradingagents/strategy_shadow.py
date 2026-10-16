"""Prospective, observation-only price-rule journal; never places or simulates orders."""

import argparse
import hashlib
import json
import math
import os
import subprocess
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

import pandas as pd

from tradingagents.dashboard.operations import private_write
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.files import locked
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv
from tradingagents.sector_study import ASSETS, RULE_LABELS, SINGLE_RULES, SOURCES, make_signals

NEW_YORK = ZoneInfo("America/New_York")
CAPTURE_AFTER = time(16, 30)
HORIZONS = (5, 20, 63)
SIGNAL_DEFINITIONS = {
    "buy_hold": "Always long.",
    "sma_50_200": "Long when the decision close's 50-session mean exceeds its 200-session mean; otherwise Hold.",
    "momentum_252": "Long when the decision close exceeds the close 252 sessions earlier; otherwise Hold.",
    "weekly_reversal": "Long-only reversal timing: long when the latest completed calendar week's return is negative; otherwise Hold. W-FRI publication timestamps are never backdated over holidays.",
    "sector_momentum_12_1": "Record up to four positive sector close(t-21)/close(t-252)-1 scores at calendar month ends; ties follow universe order and membership persists. Non-session publication boundaries wait until the next trading close.",
}
ASSUMPTIONS = [
    "Observation-only forecasts, not orders, positions, a backtest or portfolio P&L. Sector membership is recorded without a portfolio outcome score.",
    "Capture uses a completed current New York trading-day close after 16:30 New York time. A holiday or lagging vendor never causes a backdated forecast. Local timestamps and file hashes are not independent timestamp attestations.",
    "Entry is the first SPY-calendar session strictly after the capture date, at its adjusted open. A 5/20/63-session endpoint counts entry as session one and uses that endpoint's adjusted close.",
    "Both entry and exit prices come from the same newly fetched Yahoo adjusted series at scoring time; archived capture prices are never mixed with a later adjustment basis. Vendor revisions can change rescored outcomes.",
    "asset_return_pct is gross adjusted open-to-close return; spy_return_pct uses the identical dates. alpha_pct is asset_return_pct minus spy_return_pct, a reference difference without an equal-risk claim.",
    "direction is 1 for Long or 0 for Hold/abstain, never short. gross_direction_score_pct is direction times asset_return_pct. direction_alpha_score_pct is direction times alpha_pct. These are forecast scores, not portfolio returns; no costs, sizing or cash yield are modeled.",
    "Forecasts and their horizons overlap and are correlated. Scores are not compounded or summed into P&L. Different assets have different risks; comparing their SPY differences does not equalize those risks.",
    "Rules are long-only ETF adaptations motivated by the linked research, not academic replications or TradingAgents model performance. No model, broker or order API is used.",
]


def _clock(now):
    now = now if now is not None else datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("The shadow clock must be timezone-aware.")
    return now.astimezone(UTC), now.astimezone(NEW_YORK)


def _root():
    root = Path.home() / ".tradingagents/experiments/shadow"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _lock_path(folder, name):
    descriptor = os.open(folder / f"{name}.lock", os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(descriptor)
    return folder / name


def _prices(frame, ticker, as_of, limit=None):
    frame = frame[["Date", "Open", "Close"]].copy()
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.tz_localize(None).dt.normalize()
    if frame["Date"].isna().any():
        raise ValueError(f"{ticker} has invalid dates.")
    frame = frame.set_index("Date")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{ticker} dates must be unique and increasing.")
    frame = frame.loc[frame.index <= pd.Timestamp(as_of)]
    if limit is not None:
        frame = frame.tail(limit)
    if frame.empty or not frame.map(lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0).all().all():
        raise ValueError(f"{ticker} has missing or invalid prices; gaps are not filled.")
    return frame


def _csv(frame):
    return frame.reset_index().to_csv(index=False).encode()


def _source_commit():
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=5, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def capture_shadow(config=None, now=None):
    """Freeze today's close decisions only after the capture cutoff; never backdate."""
    utc, local = _clock(now)
    day = local.date().isoformat()
    metadata = {"created_at": utc.isoformat(), "capture_date": day, "status": "skipped"}
    if local.weekday() >= 5 or local.time() < CAPTURE_AFTER:
        return {**metadata, "reason": "weekend" if local.weekday() >= 5 else "before_16_30_new_york"}, None
    root = _root()
    folder = root / day
    folder.mkdir(exist_ok=True, mode=0o700)
    with locked(_lock_path(folder, "capture"), wait=False) as acquired:
        if not acquired:
            return {**metadata, "reason": "capture_in_progress"}, None
        forecast = folder / "forecast.json"
        if forecast.exists():
            previous = json.loads(forecast.read_bytes())
            if previous.get("status") == "complete":
                return previous, folder
        metadata.update(status="capturing", last_price_session=None, horizons=list(HORIZONS),
                        entry_policy="First SPY-calendar session strictly after capture_date, at the adjusted open.",
                        assets=ASSETS, rules={rule: RULE_LABELS[rule] for rule in SINGLE_RULES},
                        signal_definitions=SIGNAL_DEFINITIONS, sources=SOURCES, assumptions=ASSUMPTIONS,
                        source_commit=_source_commit(),
                        signal_source_sha256=hashlib.sha256(Path(__file__).with_name("sector_study.py").read_bytes()).hexdigest(),
                        data_hashes={}, signals=[], sector_membership={})
        try:
            with TemporaryDirectory(prefix=".capture-cache-", dir=root) as temporary:
                isolated = {**(config or {}), "data_cache_dir": temporary, "results_dir": str(folder)}
                with run_config(isolated):
                    spy = _prices(load_ohlcv("SPY", day, fill_gaps=False), "SPY", day, limit=320)
                    if spy.index[-1].date() < local.date():
                        return {**metadata, "status": "skipped", "reason": "holiday_or_vendor_lag", "last_price_session": str(spy.index[-1].date())}, None
                    if len(spy) < 253:
                        raise ValueError("SPY needs at least 253 completed closes for shadow signals.")
                    frames = {}
                    for ticker in ASSETS:
                        frame = spy if ticker == "SPY" else _prices(load_ohlcv(ticker, day, fill_gaps=False), ticker, day, limit=320)
                        if frame.index[-1].date() != local.date() or not spy.index.isin(frame.index).all():
                            raise ValueError(f"{ticker} is missing a current SPY-calendar session.")
                        frames[ticker] = frame.reindex(spy.index)
            closes = pd.DataFrame({ticker: frame["Close"] for ticker, frame in frames.items()})
            decisions = make_signals(closes)
            for ticker, asset in ASSETS.items():
                for rule in SINGLE_RULES:
                    direction = int(decisions[rule].loc[spy.index[-1], ticker])
                    metadata["signals"].append({"ticker": ticker, **asset, "rule": rule, "direction": direction,
                                                "decision": "Long" if direction else "Hold"})
                data = _csv(frames[ticker])
                private_write(folder / "data" / f"{ticker}.csv", data)
                metadata["data_hashes"][ticker] = hashlib.sha256(data).hexdigest()
            metadata["sector_membership"] = {ticker: bool(value) for ticker, value in decisions["sector_momentum_12_1"].iloc[-1].items()}
            metadata.update(status="complete", last_price_session=day)
            private_write(forecast, json.dumps(metadata, indent=2, allow_nan=False).encode())
            return metadata, folder
        except Exception as exc:
            metadata.update(status="failed", error=str(exc))
            private_write(forecast, json.dumps(metadata, indent=2, allow_nan=False).encode())
            raise


def _forecasts(root):
    forecasts = []
    for path in sorted(root.glob("????-??-??/forecast.json")):
        data = path.read_bytes()
        forecast = json.loads(data)
        if forecast.get("status") != "complete":
            continue
        capture = date.fromisoformat(forecast["capture_date"])
        created = datetime.fromisoformat(forecast["created_at"])
        if capture.isoformat() != path.parent.name or created.tzinfo is None or created.astimezone(NEW_YORK).date() != capture or forecast["last_price_session"] != capture.isoformat():
            raise ValueError(f"Invalid frozen forecast date in {path.parent.name}.")
        if created.astimezone(NEW_YORK).weekday() >= 5 or created.astimezone(NEW_YORK).time() < CAPTURE_AFTER:
            raise ValueError(f"Frozen forecast was not captured after a weekday close: {path.parent.name}.")
        if set(forecast["data_hashes"]) != set(ASSETS) or forecast["horizons"] != list(HORIZONS):
            raise ValueError(f"Invalid frozen forecast universe or horizons in {path.parent.name}.")
        for ticker in ASSETS:
            source = (path.parent / "data" / f"{ticker}.csv").read_bytes()
            if hashlib.sha256(source).hexdigest() != forecast["data_hashes"][ticker]:
                raise ValueError(f"Frozen source hash mismatch for {path.parent.name}/{ticker}.")
        expected = {(ticker, rule) for ticker in ASSETS for rule in SINGLE_RULES}
        recorded = {(row["ticker"], row["rule"]) for row in forecast["signals"]}
        if recorded != expected or len(forecast["signals"]) != len(expected) or any(type(row["direction"]) is not int or row["direction"] not in (0, 1) or row["decision"] != ("Long" if row["direction"] else "Hold") for row in forecast["signals"]):
            raise ValueError(f"Invalid frozen forecast directions in {path.parent.name}.")
        forecasts.append((forecast, hashlib.sha256(data).hexdigest()))
    return forecasts


def _score_rows(forecasts, frames):
    rows = []
    calendar = frames["SPY"].index
    for forecast, digest in forecasts:
        if pd.Timestamp(forecast["capture_date"]) not in calendar:
            raise ValueError(f"Fresh SPY prices do not cover capture date {forecast['capture_date']}; cannot identify its next session.")
        sessions = calendar[calendar > pd.Timestamp(forecast["capture_date"])]
        for ticker in ASSETS:
            if not sessions.isin(frames[ticker].index).all():
                raise ValueError(f"{ticker} is missing a SPY-calendar session while scoring.")
        for signal in forecast["signals"]:
            for horizon in HORIZONS:
                row = {**signal, "capture_date": forecast["capture_date"], "forecast_sha256": digest,
                       "horizon_sessions": horizon, "status": "pending", "entry_date": str(sessions[0].date()) if len(sessions) else None,
                       "exit_date": None, "asset_return_pct": None, "spy_return_pct": None, "alpha_pct": None,
                       "gross_direction_score_pct": None, "direction_alpha_score_pct": None}
                if len(sessions) >= horizon:
                    entry, endpoint = sessions[0], sessions[horizon - 1]
                    asset = frames[signal["ticker"]]
                    opened, closed = float(asset.loc[entry, "Open"]), float(asset.loc[endpoint, "Close"])
                    spy_open = float(frames["SPY"].loc[entry, "Open"])
                    spy_close = float(frames["SPY"].loc[endpoint, "Close"])
                    asset_return = (closed / opened - 1) * 100
                    spy_return = (spy_close / spy_open - 1) * 100
                    alpha = asset_return - spy_return
                    row.update(status="complete", exit_date=str(endpoint.date()), entry_open=opened, exit_close=closed,
                               spy_entry_open=spy_open, spy_exit_close=spy_close, asset_return_pct=asset_return,
                               spy_return_pct=spy_return, alpha_pct=alpha,
                               gross_direction_score_pct=signal["direction"] * asset_return,
                               direction_alpha_score_pct=signal["direction"] * alpha)
                rows.append(row)
    return rows


def score_shadow(config=None, now=None):
    """Score frozen directions against common-basis future prices without portfolio P&L."""
    utc, local = _clock(now)
    root = _root()
    with locked(_lock_path(root, "scoring"), wait=False) as acquired:
        if not acquired:
            return {"status": "skipped", "reason": "scoring_in_progress"}
        forecasts = _forecasts(root)
        cutoff = local.date() if local.time() >= CAPTURE_AFTER else local.date() - timedelta(days=1)
        report = {"status": "complete", "created_at": utc.isoformat(), "price_as_of": cutoff.isoformat(),
                  "last_price_session": None, "forecasts": len(forecasts), "complete": 0, "pending": 0,
                  "horizons": list(HORIZONS), "assumptions": ASSUMPTIONS, "results": [], "scoring_data_hashes": {}}
        if forecasts:
            with TemporaryDirectory(prefix=".scoring-cache-", dir=root) as temporary:
                isolated = {**(config or {}), "data_cache_dir": temporary, "results_dir": str(root)}
                with run_config(isolated):
                    frames = {ticker: _prices(load_ohlcv(ticker, cutoff.isoformat(), fill_gaps=False), ticker, cutoff) for ticker in ASSETS}
            report["last_price_session"] = str(frames["SPY"].index[-1].date())
            report["scoring_data_hashes"] = {ticker: hashlib.sha256(_csv(frame)).hexdigest() for ticker, frame in frames.items()}
            report["results"] = _score_rows(forecasts, frames)
            report["complete"] = sum(row["status"] == "complete" for row in report["results"])
            report["pending"] = len(report["results"]) - report["complete"]
        private_write(root / "scores.json", json.dumps(report, indent=2, allow_nan=False).encode())
        return report


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run"])
    parser.parse_args()
    try:
        capture, folder = capture_shadow()
        scores = score_shadow()
    except Exception as exc:
        parser.exit(1, f"Shadow journal failed: {exc}\n")
    print(json.dumps({"capture_status": capture["status"], "capture_date": capture["capture_date"],
                      "folder": str(folder) if folder else None,
                      "scoring": {key: scores.get(key) for key in ("status", "forecasts", "complete", "pending")}}))


if __name__ == "__main__":
    main()

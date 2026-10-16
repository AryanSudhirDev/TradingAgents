"""Fresh close capture, immutable inputs, calendar horizons and adjusted-basis scores."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from tradingagents import strategy_shadow as shadow
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.files import locked

CAPTURE = datetime(2026, 10, 16, 21, 45, tzinfo=UTC)


@pytest.fixture
def market(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(shadow, "ASSETS", {ticker: shadow.ASSETS[ticker] for ticker in ("XLB", "XLE", "SPY")})
    monkeypatch.setattr(shadow, "_source_commit", lambda: "frozen-test-commit")
    dates = pd.bdate_range(end="2026-10-16", periods=400)
    frames = {}
    for ticker, price, slope in (("XLB", 100, 0.1), ("XLE", 300, -0.1), ("SPY", 200, 0)):
        close = [price + i * slope for i in range(len(dates))]
        frames[ticker] = pd.DataFrame({"Date": dates, "Open": close, "Close": close})
    calls = []

    def fetch(ticker, as_of, *, fill_gaps):
        cache = Path(get_config()["data_cache_dir"])
        assert cache.is_relative_to(tmp_path / ".tradingagents/experiments/shadow")
        assert cache.exists() and cache.stat().st_mode & 0o777 == 0o700
        assert fill_gaps is False
        calls.append((ticker, as_of, cache))
        return frames[ticker].copy()

    monkeypatch.setattr(shadow, "load_ohlcv", fetch)
    return frames, calls


def add_future(frames, count=70):
    dates = pd.bdate_range("2026-10-19", periods=count)
    for ticker in frames:
        frames[ticker][["Open", "Close"]] /= 2
        opening = {"XLB": 50.0, "XLE": 100.0, "SPY": 200.0}[ticker]
        future = pd.DataFrame({"Date": dates, "Open": opening, "Close": [opening + i + 1 for i in range(count)]})
        frames[ticker] = pd.concat([frames[ticker], future], ignore_index=True)
    return dates


@pytest.mark.parametrize("now,reason", [
    (datetime(2026, 10, 16, 20, 29, tzinfo=UTC), "before_16_30_new_york"),
    (datetime(2026, 10, 17, 21, 45, tzinfo=UTC), "weekend"),
    (datetime(2026, 1, 16, 21, 29, tzinfo=UTC), "before_16_30_new_york"),
])
def test_capture_before_cutoff_and_weekends_reads_no_inputs_or_calls(market, tmp_path, now, reason):
    _, calls = market
    result, folder = shadow.capture_shadow(now=now)
    assert result["status"] == "skipped" and result["reason"] == reason
    assert folder is None and calls == []
    assert not (tmp_path / ".tradingagents").exists()


def test_naive_clock_is_rejected_before_any_inputs(market):
    with pytest.raises(ValueError, match="timezone-aware"):
        shadow.capture_shadow(now=datetime(2026, 10, 16, 17, 45))
    assert market[1] == []


def test_capture_freezes_320_common_sessions_signals_hashes_and_private_files(market):
    frames, calls = market
    original_config = get_config()
    result, folder = shadow.capture_shadow({"data_cache_dir": "must-not-use"}, now=CAPTURE)
    assert result["status"] == "complete"
    assert result["created_at"] == CAPTURE.isoformat()
    assert result["capture_date"] == result["last_price_session"] == "2026-10-16"
    assert result["source_commit"] == "frozen-test-commit"
    assert result["horizons"] == [5, 20, 63]
    assert len(result["signals"]) == len(frames) * 4
    assert len(calls) == len(frames)
    assert set(result["sector_membership"]) == {"XLB", "XLE"}
    for ticker in frames:
        path = folder / "data" / f"{ticker}.csv"
        data = pd.read_csv(path)
        assert list(data) == ["Date", "Open", "Close"]
        assert len(data) == 320
        assert data["Date"].iloc[-1] == "2026-10-16"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == result["data_hashes"][ticker]
    for path in folder.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    assert folder.stat().st_mode & 0o777 == 0o700
    assert all(not cache.exists() for _, _, cache in calls)
    assert get_config() == original_config


def test_capture_filters_future_bars_and_is_idempotent_without_overwriting(market):
    frames, calls = market
    add_future(frames)
    first, folder = shadow.capture_shadow(now=CAPTURE)
    saved = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in folder.rglob("*") if path.is_file()}
    for frame in frames.values():
        frame[["Open", "Close"]] *= 10
    calls.clear()
    second, second_folder = shadow.capture_shadow(now=CAPTURE)
    assert first == second and folder == second_folder
    assert calls == []
    for path, (data, modified) in saved.items():
        assert path.read_bytes() == data and path.stat().st_mtime_ns == modified
    assert first["last_price_session"] == "2026-10-16"


def test_lagging_spy_skips_without_backdating_a_forecast(market):
    frames, calls = market
    frames["SPY"] = frames["SPY"].iloc[:-1]
    result, folder = shadow.capture_shadow(now=CAPTURE)
    assert result["status"] == "skipped" and result["reason"] == "holiday_or_vendor_lag"
    assert result["last_price_session"] == "2026-10-15"
    assert folder is None
    assert [ticker for ticker, _, _ in calls] == ["SPY"]
    assert not list(Path.home().glob(".tradingagents/experiments/shadow/*/forecast.json"))
    assert all(not cache.exists() for _, _, cache in calls)


@pytest.mark.parametrize("problem", ["gap", "stale", "nonfinite", "warmup"])
def test_incomplete_current_capture_is_failed_and_not_scored(market, problem):
    frames, _ = market
    if problem == "gap":
        frames["XLB"] = frames["XLB"].drop(index=300)
    elif problem == "stale":
        frames["XLB"] = frames["XLB"].iloc[:-1]
    elif problem == "nonfinite":
        frames["XLB"].loc[399, "Open"] = float("nan")
    else:
        frames["SPY"] = frames["SPY"].tail(252)
    with pytest.raises(ValueError):
        shadow.capture_shadow(now=CAPTURE)
    folder = Path.home() / ".tradingagents/experiments/shadow/2026-10-16"
    assert json.loads((folder / "forecast.json").read_bytes())["status"] == "failed"
    report = shadow.score_shadow(now=CAPTURE)
    assert report["forecasts"] == report["complete"] == report["pending"] == 0


def test_network_failure_records_failed_manifest_and_raises(market, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("vendor unavailable")

    monkeypatch.setattr(shadow, "load_ohlcv", unavailable)
    with pytest.raises(OSError, match="vendor unavailable"):
        shadow.capture_shadow(now=CAPTURE)
    path = Path.home() / ".tradingagents/experiments/shadow/2026-10-16/forecast.json"
    assert json.loads(path.read_bytes())["status"] == "failed"
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.parent.glob(".capture-cache-*"))


def test_nonblocking_capture_lock_avoids_duplicate_fetches(market):
    root = shadow._root()
    folder = root / "2026-10-16"
    folder.mkdir(mode=0o700)
    with locked(shadow._lock_path(folder, "capture"), wait=False):
        result, output = shadow.capture_shadow(now=CAPTURE)
    assert result["reason"] == "capture_in_progress" and output is None
    assert market[1] == []


def test_frozen_csv_hash_mismatch_refuses_scoring_before_network(market):
    _, calls = market
    _, folder = shadow.capture_shadow(now=CAPTURE)
    with (folder / "data/XLB.csv").open("ab") as stream:
        stream.write(b"tampered")
    calls.clear()
    with pytest.raises(ValueError, match="Frozen source hash mismatch"):
        shadow.score_shadow(now=CAPTURE)
    assert calls == []
    assert not (folder.parent / "scores.json").exists()


def test_no_available_outcomes_are_pending_and_frozen_forecast_is_unchanged(market):
    _, folder = shadow.capture_shadow(now=CAPTURE)
    frozen = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    report = shadow.score_shadow(now=CAPTURE)
    assert report["forecasts"] == 1
    assert report["complete"] == 0 and report["pending"] == len(shadow.ASSETS) * 4 * 3
    assert all(row["entry_date"] is None and row["asset_return_pct"] is None for row in report["results"])
    for path, data in frozen.items():
        assert path.read_bytes() == data
    assert (folder.parent / "scores.json").stat().st_mode & 0o777 == 0o600


def test_scoring_rejects_an_intraday_capture_timestamp(market):
    _, folder = shadow.capture_shadow(now=CAPTURE)
    path = folder / "forecast.json"
    record = json.loads(path.read_text())
    record["created_at"] = "2026-10-16T19:00:00+00:00"
    path.write_text(json.dumps(record))
    market[1].clear()
    with pytest.raises(ValueError, match="weekday close"):
        shadow.score_shadow(now=CAPTURE)
    assert market[1] == []


def test_next_open_endpoints_include_entry_session_and_share_fresh_adjusted_basis(market):
    frames, calls = market
    _, folder = shadow.capture_shadow(now=CAPTURE)
    dates = add_future(frames)
    now = datetime.combine(dates[19].date(), shadow.CAPTURE_AFTER, tzinfo=shadow.NEW_YORK)
    report = shadow.score_shadow(now=now)
    assert report["complete"] == len(shadow.ASSETS) * 4 * 2
    assert report["pending"] == len(shadow.ASSETS) * 4
    assert report["price_as_of"] == report["last_price_session"] == str(dates[19].date())
    rows = {(row["ticker"], row["rule"], row["horizon_sessions"]): row for row in report["results"]}
    five = rows["XLB", "buy_hold", 5]
    twenty = rows["XLB", "buy_hold", 20]
    assert five["entry_date"] == "2026-10-19"
    assert five["exit_date"] == str(dates[4].date())
    assert five["entry_open"] == 50
    assert five["exit_close"] == 55
    assert five["asset_return_pct"] == pytest.approx(10)
    assert five["spy_return_pct"] == pytest.approx(2.5)
    assert five["alpha_pct"] == pytest.approx(7.5)
    assert five["gross_direction_score_pct"] == pytest.approx(10)
    assert five["direction_alpha_score_pct"] == pytest.approx(7.5)
    assert twenty["exit_date"] == str(dates[19].date())
    assert twenty["asset_return_pct"] == pytest.approx(40)
    abstain = rows["XLE", "momentum_252", 5]
    assert abstain["direction"] == 0 and abstain["decision"] == "Hold"
    assert abstain["asset_return_pct"] > 0
    assert abstain["gross_direction_score_pct"] == abstain["direction_alpha_score_pct"] == 0
    assert len(report["results"]) == len(shadow.ASSETS) * 4 * 3
    assert not list(folder.parent.glob(".scoring-cache-*"))
    assert all(not cache.exists() for _, _, cache in calls)


def test_63_session_endpoint_and_pre_cutoff_exclude_current_daily_bar(market):
    frames, calls = market
    shadow.capture_shadow(now=CAPTURE)
    dates = add_future(frames)
    now = datetime.combine(dates[63].date(), shadow.CAPTURE_AFTER.replace(minute=29), tzinfo=shadow.NEW_YORK)
    calls.clear()
    report = shadow.score_shadow(now=now)
    row = next(row for row in report["results"] if row["ticker"] == "XLB" and row["rule"] == "buy_hold" and row["horizon_sessions"] == 63)
    assert row["exit_date"] == str(dates[62].date())
    assert row["asset_return_pct"] == pytest.approx(126)
    assert {as_of for _, as_of, _ in calls} == {(now.date() - pd.Timedelta(days=1)).isoformat()}


def test_scoring_refuses_truncated_future_history_that_cannot_identify_first_entry(market):
    frames, _ = market
    shadow.capture_shadow(now=CAPTURE)
    dates = add_future(frames)
    for ticker in frames:
        frames[ticker] = frames[ticker].tail(10)
    now = datetime.combine(dates[-1].date(), shadow.CAPTURE_AFTER, tzinfo=shadow.NEW_YORK)
    with pytest.raises(ValueError, match="do not cover capture date"):
        shadow.score_shadow(now=now)


def test_cli_reports_failure_with_nonzero_status(monkeypatch):
    monkeypatch.setattr(shadow.os, "umask", lambda value: None)
    monkeypatch.setattr("sys.argv", ["strategy_shadow", "run"])

    def failed():
        raise ValueError("bad frozen inputs")

    monkeypatch.setattr(shadow, "capture_shadow", failed)
    with pytest.raises(SystemExit) as error:
        shadow.main()
    assert error.value.code == 1
